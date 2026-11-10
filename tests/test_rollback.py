"""Before-state restoration and removal plans tested without system changes."""
import importlib.util
import fcntl
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/helpers'))
from rollback_state import Journal, fingerprint
import local_undo

spec = importlib.util.spec_from_file_location('rollback', ROOT / 'scripts/rollback-maya.py')
rollback = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rollback)


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.journal = Journal(self.root / 'journal')

    def test_roundtrip_restores_files_modes_symlinks_and_absent_paths(self):
        file = self.root / 'config'
        file.write_bytes(b'original\n')
        file.chmod(0o640)
        link = self.root / 'link'
        link.symlink_to('original-target')
        created = self.root / 'new/child'
        before = fingerprint(file)
        for path in (file, link, created):
            self.journal.add(path)
        file.write_text('replacement')
        link.unlink()
        link.symlink_to('new-target')
        created.parent.mkdir()
        created.write_text('generated')
        self.journal.seal()
        self.assertEqual(self.journal.conflicts(), [])
        self.journal.restore()
        self.assertEqual(fingerprint(file), before)
        self.assertEqual(os.readlink(link), 'original-target')
        self.assertFalse(created.parent.exists())
        self.journal.restore()  # Idempotent, including removed paths.

    def test_existing_directory_tree_is_restored(self):
        path = self.root / 'tree'
        path.mkdir()
        (path / 'old').write_text('before')
        (path / 'alias').symlink_to('old')
        before = fingerprint(path)
        self.journal.add(path)
        (path / 'old').write_text('after')
        (path / 'new').write_text('generated')
        self.journal.seal()
        self.journal.restore()
        self.assertEqual(fingerprint(path), before)

    def test_later_edits_and_corrupt_before_backups_are_reported(self):
        path = self.root / 'config'
        path.write_text('before')
        self.journal.add(path)
        path.write_text('installed')
        self.journal.seal()
        path.write_text('later user edit')
        self.assertIn('Changed since installation', '\n'.join(self.journal.conflicts()))
        (self.journal.directory / 'before/0').write_text('corrupted')
        self.assertIn('Before-state backup changed', '\n'.join(self.journal.conflicts()))
        self.assertEqual(path.read_text(), 'later user edit')

    def test_volatile_data_is_retained_privately_instead_of_destroyed(self):
        path = self.root / 'service-data'
        self.journal.add(path, volatile=True)
        path.mkdir()
        (path / 'license-state').write_text('private data')
        self.journal.seal()
        (path / 'more-state').write_text('changed during use')
        self.assertEqual(self.journal.conflicts(), [])
        self.journal.restore()
        self.assertFalse(path.exists())
        self.assertEqual((self.journal.directory / 'retained/0/license-state').read_text(), 'private data')
        self.assertEqual(self.journal.directory.stat().st_mode & 0o777, 0o700)

    def test_parent_symlink_change_is_refused(self):
        parent = self.root / 'parent'
        parent.mkdir()
        path = parent / 'config'
        self.journal.add(path)
        path.write_text('installed')
        self.journal.seal()
        parent.rename(self.root / 'moved')
        parent.symlink_to(self.root / 'moved', target_is_directory=True)
        self.assertIn('Parent path changed', '\n'.join(self.journal.conflicts()))
        with self.assertRaises(ValueError):
            self.journal.restore()

    def test_unsealed_state_requires_explicit_incomplete_option(self):
        self.journal.add(self.root / 'new')
        self.assertTrue(self.journal.conflicts())
        self.assertEqual(self.journal.conflicts(incomplete=True), [])

    def test_nonempty_project_directory_is_kept(self):
        path = self.root / 'projects'
        self.journal.add(path, directory_only=True)
        path.mkdir()
        (path / 'scene.ma').write_text('scene data')
        self.journal.seal()
        self.journal.restore()
        self.assertEqual((path / 'scene.ma').read_text(), 'scene data')

    def test_container_created_after_local_capture_can_be_removed_when_empty(self):
        path = self.root / 'empty-projects'
        self.journal.add(path, directory_only=True)
        self.journal.seal()
        path.mkdir()
        self.assertEqual(self.journal.conflicts(), [])
        self.journal.restore()
        self.assertFalse(path.exists())

    def test_root_and_journal_ancestor_scopes_are_refused(self):
        for path in (Path('/'), self.root, self.journal.directory):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.journal.add(path)

    def test_alias_to_the_journal_is_refused_before_copying(self):
        alias = self.root / 'alias'
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'Unsafe rollback scope'):
            self.journal.add(alias / 'journal')


class PlanTests(unittest.TestCase):
    def test_apt_guard_refuses_upgrades_of_existing_packages(self):
        with tempfile.TemporaryDirectory() as directory:
            plan = Path(directory) / 'plan'
            journal = SimpleNamespace(data={'deb_before': {'libexample:amd64': '1'}})
            plan.write_text('Inst new-package (1 Debian:stable [amd64])\n')
            rollback.guard_apt(journal, plan)
            plan.write_text('Inst libexample [1] (2 Debian:stable [amd64])\n')
            with self.assertRaises(ValueError):
                rollback.guard_apt(journal, plan)

    def test_apt_removal_refuses_removing_unrelated_packages(self):
        journal = SimpleNamespace(data={'deb_before': {'keep': '1'}, 'deb_after': {'keep': '1', 'new': '1'}, 'rpms': [], 'deb_planned_new': ['new']})
        with patch.object(rollback, 'packages', return_value={'keep': '1', 'new': '1'}), \
                patch.object(rollback, 'run', return_value=subprocess.CompletedProcess([], 0, 'Remv new [1]\nRemv keep [1]\n', '')), \
                patch.object(rollback.shutil, 'which', return_value=None):
            problems, remove = rollback.removal_plan(journal, True)
        self.assertEqual(remove, ['new'])
        self.assertTrue(any('another package' in problem for problem in problems))

    def test_changed_debian_package_version_is_not_removed(self):
        journal = SimpleNamespace(data={'deb_before': {}, 'deb_after': {'new': '1'}, 'rpms': [], 'deb_planned_new': ['new']})
        with patch.object(rollback, 'packages', return_value={'new': '2'}), \
                patch.object(rollback, 'run', return_value=subprocess.CompletedProcess([], 0, 'Remv new [2]\n', '')), \
                patch.object(rollback.shutil, 'which', return_value=None):
            problems, _ = rollback.removal_plan(journal, True)
        self.assertTrue(any('changed since installation' in problem for problem in problems))

    def test_package_added_outside_the_recorded_apt_plan_is_kept(self):
        journal = SimpleNamespace(data={'deb_before': {}, 'deb_after': {'unrelated': '1'}, 'rpms': [], 'deb_planned_new': ['ours']})
        with patch.object(rollback, 'packages', return_value={'unrelated': '1'}), \
                patch.object(rollback.shutil, 'which', return_value=None):
            problems, remove = rollback.removal_plan(journal, True)
        self.assertEqual((problems, remove), ([], []))


class LocalRollbackTests(unittest.TestCase):
    def test_active_download_lock_stops_workspace_restoration(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(local_undo, 'BASE', Path(directory)):
            root = Path(directory)
            work = root / 'compat-download'
            work.mkdir()
            local_undo.capture('downloads')
            with (work / 'download.lock').open('w') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                with self.assertRaisesRegex(ValueError, 'still running'):
                    local_undo.restore(True)
            self.assertTrue(work.exists())

    def test_uri_symlink_and_other_defaults_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(local_undo, 'BASE', Path(directory)):
            root = Path(directory)
            source = root / 'actual-mimeapps'
            original = b'# keep original formatting\n[Default Applications]\ntext/plain=editor.desktop;\n'
            source.write_bytes(original)
            link = root / 'mimeapps.list'
            link.symlink_to(source.name)
            spec = importlib.util.spec_from_file_location('uri_config', ROOT / 'scripts/helpers/set-identity-uri.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            journal = local_undo.capture_uri(link)
            module.configure(link, 'adskidmgr')
            journal.seal()
            self.assertIn('text/plain=editor.desktop;', source.read_text())
            self.assertIn('x-scheme-handler/adskidmgr=', source.read_text())
            local_undo.restore(True)
            self.assertTrue(link.is_symlink())
            self.assertEqual(source.read_bytes(), original)

    def test_downloads_restore_the_original_set_and_retain_new_files(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(local_undo, 'BASE', Path(directory)):
            root = Path(directory)
            downloads = root / 'compat-download'
            downloads.mkdir()
            (downloads / 'old.deb').write_text('before')
            local_undo.capture('downloads')
            (downloads / 'new.deb').write_text('downloaded')
            local_undo.restore(False)
            self.assertTrue((downloads / 'new.deb').exists())
            local_undo.restore(True)
            self.assertEqual((downloads / 'old.deb').read_text(), 'before')
            self.assertFalse((downloads / 'new.deb').exists())
            self.assertTrue(list((root / 'state/local-undo/downloads/retained').rglob('new.deb')))
            local_undo.restore(True)

    def test_standalone_database_restores_original_directory_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'database'
            path.mkdir(mode=0o700)
            local_undo.database_record(path)
            path.chmod(0o755)
            subprocess.run(['rpm', '--dbpath', str(path), '--initdb'], check=True)
            local_undo.database_restore(path, True)
            self.assertEqual(list(path.iterdir()), [])
            self.assertEqual(path.stat().st_mode & 0o777, 0o700)

    def test_standalone_database_with_packages_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'database'
            local_undo.database_record(path)
            path.mkdir()
            (path / 'rpmdb.sqlite').touch()
            with patch.object(local_undo.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'foreign-package\n', '')):
                with self.assertRaises(ValueError):
                    local_undo.database_restore(path, True)
            self.assertTrue(path.exists())


class UninstallSequenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.package = dict(key='maya', name='Maya2027_64', version='2027.2-1906.x86_64',
                            prefix=str(self.root / 'install/usr'), removed=False,
                            scripts={'PREUN': 'echo preun\n', 'POSTUN': 'echo postun\n'})
        self.journal = SimpleNamespace(
            directory=self.root,
            data={'phase': 'sealed', 'entries': [], 'rpms': [self.package], 'uid': os.getuid(),
                  'home': str(self.root / 'home'), 'auto_before': [], 'auto_after': [],
                  'adsklic_user_before': '', 'adsklic_group_before': ''},
            save=Mock(), restore=Mock())
        self.args = SimpleNamespace(resume=False, remove_dependencies=False,
                                    clean_workspace=False, allow_incomplete=False)

    def test_vendor_callbacks_bracket_rpm_erase_with_fresh_uninstall_argument(self):
        commands = []
        def command(*args, **kwargs):
            commands.append((args, kwargs))
            return subprocess.CompletedProcess(args, 0, '', '')
        with patch.object(rollback, 'run', side_effect=command), \
                patch.object(rollback, 'run_as_user'), patch.object(rollback, 'stop_watcher'), \
                patch.object(rollback, 'packages', return_value={}):
            rollback.apply(self.journal, self.args, [])
        preun = next(i for i, (cmd, _) in enumerate(commands) if cmd[0] == 'bash' and 'PREUN' in cmd[1])
        erase = next(i for i, (cmd, _) in enumerate(commands) if cmd[0] == 'rpm' and '-e' in cmd)
        postun = next(i for i, (cmd, _) in enumerate(commands) if cmd[0] == 'bash' and 'POSTUN' in cmd[1])
        self.assertLess(preun, erase)
        self.assertLess(erase, postun)
        for index in (preun, postun):
            self.assertEqual(commands[index][0][-1], '0')
            self.assertEqual(commands[index][1]['env']['RPM_INSTALL_PREFIX'], self.package['prefix'])
        self.journal.restore.assert_called_once_with(retain_current=False)
        self.assertEqual(self.journal.data['phase'], 'complete')

    def test_failed_postun_is_resumed_even_when_rpm_was_already_erased(self):
        def fail_postun(*args, **kwargs):
            if args[0] == 'bash' and 'POSTUN' in args[1]:
                raise subprocess.CalledProcessError(1, args)
            return subprocess.CompletedProcess(args, 0, '', '')
        with patch.object(rollback, 'run_as_user'), patch.object(rollback, 'stop_watcher'), \
                patch.object(rollback, 'packages', return_value={}):
            with patch.object(rollback, 'run', side_effect=fail_postun), self.assertRaises(subprocess.CalledProcessError):
                rollback.apply(self.journal, self.args, [])
            self.assertEqual(self.package['undo_phase'], 'erased')
            self.journal.restore.assert_not_called()
            self.args.resume = True
            commands = []
            def resume_command(*args, **kwargs):
                commands.append(args)
                absent = args[0] == 'rpm' and '-q' in args
                return subprocess.CompletedProcess(args, 1 if absent else 0, '', '')
            with patch.object(rollback, 'run', side_effect=resume_command):
                rollback.apply(self.journal, self.args, [])
            self.assertTrue(any(cmd[0] == 'bash' and 'POSTUN' in cmd[1] for cmd in commands))
            self.assertFalse(any(cmd[0] == 'rpm' and '-e' in cmd for cmd in commands))
            self.assertTrue(self.package['removed'])

    def test_old_installation_without_before_state_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'state/installer').mkdir(parents=True)
            (root / 'state/installer/fresh.checked').touch()
            with patch.object(rollback, 'BASE', root), self.assertRaisesRegex(ValueError, 'older installation'):
                rollback.capture(Journal(root / 'state/rollback'), root, os.getuid())

    def test_installer_rerun_does_not_claim_later_edits_as_its_own_changes(self):
        root = self.root / 'rerun'
        root.mkdir()
        journal = Journal(root / 'journal')
        config = root / 'config'
        config.write_text('before')
        journal.add(config)
        config.write_text('installed')
        journal.data['capture_complete'] = True
        journal.seal()
        config.write_text('later user edit')
        with patch.object(rollback, 'BASE', root), self.assertRaisesRegex(ValueError, 'Changed since installation'):
            rollback.capture(journal, root, os.getuid())
        self.assertEqual(journal.data['phase'], 'sealed')

    def test_rpm_payload_paths_are_recorded_under_the_relocated_prefix(self):
        journal = Journal(self.root / 'journal')
        prefix = self.root / 'install/usr'
        def query(*args, **kwargs):
            output = ''
            if args[0] == 'rpm':
                fmt = args[3]
                if fmt.startswith('%{NAME}'):
                    output = 'Maya2027_64\n2027.2-1906.x86_64'
                elif 'FILENAMES' in fmt:
                    output = '/usr/autodesk\t16877\n/usr/autodesk/maya.bin\t33261\n'
                elif fmt == '%{PREUN}':
                    output = 'echo remove\n'
                else:
                    output = '(none)'
            return subprocess.CompletedProcess(args, 0, output, '')
        with patch.object(rollback, 'run', side_effect=query):
            rollback.register_rpm(journal, 'maya', self.root / 'media.rpm', str(prefix))
        paths = {entry['path'] for entry in journal.data['entries']}
        self.assertIn(str(prefix / 'autodesk/maya.bin'), paths)
        self.assertNotIn('/usr/autodesk/maya.bin', paths)
        self.assertEqual(journal.data['rpms'][0]['scripts']['PREUN'], 'echo remove\n')


if __name__ == '__main__':
    unittest.main()
