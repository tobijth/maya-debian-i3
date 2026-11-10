"""Exercise installer guards with all system writes redirected or stubbed."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'scripts/install-maya-native.sh').read_text()


class InstallerSafetyTests(unittest.TestCase):
    def test_install_path_guard_rejects_desktop_entry_metacharacters(self):
        guard = next(line for line in SOURCE.splitlines() if line.startswith('[[ $base '))
        command = 'die() { exit 1; }; base=$1; ' + guard
        for path, valid in (('/home/user/maya-repo_1.0', True),
                            ('/tmp/maya%F', False), ('/tmp/maya$HOME', False),
                            ('/tmp/maya"repo', False), ('/tmp/maya\\repo', False),
                            ('/tmp/maya repo', False), ('/tmp/maya\nrepo', False),
                            ('/tmp/mayä', False), ('/tmp/maya;repo', False)):
            with self.subTest(path=path):
                result = subprocess.run(['bash', '-c', command, '--', path], capture_output=True)
                self.assertEqual(result.returncode == 0, valid)

    def test_rpm_step_retains_pending_marker_after_each_mutation_failure(self):
        start = SOURCE.index('if [[ ! -f state/installer/rpm-db.done ]]')
        end = SOURCE.index('\n# The licensing media', start)
        block = SOURCE[start:end]
        for failure in ('initialize', 'macro', 'initdb', ''):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                work = Path(directory)
                (work / 'state/installer').mkdir(parents=True)
                (work / 'backups').mkdir()
                database = work / 'system/rpm'
                database.mkdir(parents=True)
                macros = work / 'system/etc-rpm'
                isolated = block.replace('/var/lib/rpm', str(database)).replace('/etc/rpm', str(macros))
                # Stub sudo and rpm; install/chmod/find only see temporary paths.
                harness = r'''
set -euo pipefail
run=test
die() { echo "$*" >&2; exit 1; }
rpm() {
    case "$1" in
        --eval) printf '%s\n' "$TEST_DATABASE" ;;
        --initdb) [[ $FAILURE != initdb ]] ;;
        --dbpath) return 0 ;;
        -qa) return 0 ;;
        *) return 90 ;;
    esac
}
sudo() {
    if [[ $1 == rpm && ${2:-} == --eval ]]; then rpm "$2" "$3"; return; fi
    [[ -f state/installer/rpm-db.pending ]] || return 91
    if [[ $1 == bash ]]; then
        touch "$TEST_DATABASE/rpmdb.sqlite"
        [[ $FAILURE != initialize ]]
    else
        "$@"
        if [[ $1 == install && ${2:-} == -m && $FAILURE == macro ]]; then return 92; fi
    fi
}
'''
                result = subprocess.run(['bash', '-c', harness + isolated], cwd=work,
                                        env=dict(os.environ, TEST_DATABASE=str(database), FAILURE=failure),
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, not failure, result.stderr)
                self.assertEqual((work / 'state/installer/rpm-db.pending').exists(), bool(failure))
                self.assertEqual((work / 'state/installer/rpm-db.done').exists(), not failure)
                if failure == 'macro':
                    self.assertTrue((macros / 'macros.maya-native').exists())


class DiagnosticStartupTests(unittest.TestCase):
    def test_fresh_clone_creates_private_log_directory_and_starts_probe(self):
        app = SimpleNamespace()
        qt = SimpleNamespace(QtCore=SimpleNamespace(QObject=object),
                             QtWidgets=SimpleNamespace(QApplication=SimpleNamespace(instance=lambda: app)))
        spec = importlib.util.spec_from_file_location(
            'probe_startup', ROOT / 'scripts/diagnostics/diagnose-maya-hotbox.py')
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'PySide6': qt}):
            spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            module.BASE = Path(directory)
            module.HotboxProbe = Mock()
            with patch.object(module.subprocess, 'run'):
                module.start_probe()
            logs = list((module.BASE / 'logs').glob('*.jsonl'))
            self.assertEqual(len(logs), 1)
            self.assertEqual(logs[0].stat().st_mode & 0o777, 0o600)
            self.assertEqual(logs[0].parent.stat().st_mode & 0o777, 0o700)
            module.HotboxProbe.assert_called_once_with(app, logs[0])
            app._maya_hotbox_probe.start.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
