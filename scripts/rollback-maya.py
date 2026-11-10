#!/usr/bin/env python3
"""Preview or undo recorded Maya installer changes; default is read-only."""
import argparse
import fcntl
import importlib.util
import os
from pathlib import Path
import pwd
import re
import shutil
import signal
import subprocess
import sys
import time

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / 'scripts/helpers'))
from rollback_state import Journal


def run(*args, check=True, env=None):
    return subprocess.run(args, text=True, capture_output=True, check=check, env=env)


def run_as_user(uid, *args):
    account = pwd.getpwuid(uid)
    def demote():
        os.initgroups(account.pw_name, account.pw_gid)
        os.setgid(account.pw_gid)
        os.setuid(uid)
    subprocess.run(args, check=True, preexec_fn=demote,
                   env=dict(os.environ, HOME=account.pw_dir))


def packages():
    rows = run('dpkg-query', '-W', '-f=${binary:Package}\t${db:Status-Status}\t${Version}\n').stdout
    return {name: version for name, status, version in (line.split('\t') for line in rows.splitlines())
            if status == 'installed'}


def stop_watcher():
    status = BASE / 'state/i3/panels-status.json'
    if not status.exists():
        return
    import json
    pid = json.loads(status.read_text()).get('pid')
    if not isinstance(pid, int) or pid <= 1:
        raise ValueError('Invalid panel helper PID.')
    proc = Path('/proc') / str(pid)
    try:
        command = (proc / 'cmdline').read_bytes().split(b'\0')
    except FileNotFoundError:
        return
    if os.fsencode(BASE / 'scripts/helpers/maya-i3-panels.py') not in command or b'--watch' not in command:
        raise ValueError('Panel helper PID was reused; no process stopped.')
    os.kill(pid, signal.SIGTERM)
    for _ in range(50):
        if not proc.exists() or not status.exists():
            return
        time.sleep(.1)
    raise ValueError('Panel helper has not stopped; retry after it exits.')


def require_maya_closed(uid):
    for proc in Path('/proc').iterdir():
        if not proc.name.isdecimal():
            continue
        try:
            if proc.stat().st_uid == uid and (proc / 'comm').read_text().strip() in ('maya.bin', 'mayapy'):
                raise ValueError('Close Maya and mayapy before rollback (this also removes session-only UI fixes).')
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue


def capture(journal, home, uid, config_home=None):
    if journal.manifest.exists():
        if journal.data['phase'] in ('applying', 'complete'):
            raise ValueError('This installation has been rolled back; use a fresh working copy for another installation.')
        if not journal.data.get('capture_complete'):
            raise ValueError('Before-state capture was interrupted. Inspect the private journal before starting installation.')
        problems = journal.conflicts()
        if problems:
            raise ValueError('\n'.join(problems))
        journal.data['phase'] = 'recording'
        journal.save()
        return
    if (BASE / 'state/installer/fresh.checked').exists():
        raise ValueError('An older installation exists without a rollback record. Refusing to invent its before-state.')
    account = pwd.getpwuid(uid)
    if Path(account.pw_dir).resolve() != home.resolve():
        raise ValueError('--home must match the installing user account.')
    for path in ('/opt/Autodesk', '/var/opt/Autodesk', '/usr/autodesk', '/var/lib/Autodesk/CER'):
        if Path(path).exists() or Path(path).is_symlink():
            raise ValueError(f'Fresh installation required: {path}')
    if run('getent', 'passwd', 'adsklic', check=False).stdout or run('getent', 'group', 'adsklic', check=False).stdout:
        raise ValueError('An adsklic account/group already exists; inventory the older installation first.')
    journal.data.update(uid=uid, home=str(home), repo=str(BASE), deb_before=packages(),
                        auto_before=run('apt-mark', 'showauto').stdout.splitlines(),
                        adsklic_user_before=run('getent', 'passwd', 'adsklic', check=False).stdout,
                        adsklic_group_before=run('getent', 'group', 'adsklic', check=False).stdout)
    for state_command in ('is-active', 'is-enabled'):
        if run('systemctl', state_command, 'adsklicensing.service', check=False).returncode == 0:
            raise ValueError('An Autodesk licensing unit is already active/enabled; inventory it before a fresh installation.')
    journal.data['rpm_before'] = (run('rpm', '--dbpath', '/var/lib/rpm', '-qa', '--qf', '%{NAME}\t%{VERSION}-%{RELEASE}.%{ARCH}\n', check=False).stdout.splitlines()
                                  if shutil.which('rpm') and Path('/var/lib/rpm/rpmdb.sqlite').is_file() else [])
    journal.save()
    for path in ('/opt/Autodesk', '/var/opt/Autodesk', '/var/lib/Autodesk/CER'):
        journal.add(path, volatile=True)
    for path in (
        '/usr/autodesk', '/etc/rpm/macros.maya-native', '/var/lib/rpm', '/var/lib/rpm.maya-undo',
        '/root/.rpmdb', '/root/.local/share/rpm',
        '/etc/ld.so.conf.d/autodesk-compat-debian13.conf',
        '/usr/lib/x86_64-linux-gnu/webkit2gtk-4.0', '/etc/pki/tls/certs/ca-bundle.crt',
        '/usr/local/bin/maya', '/usr/local/bin/Render', '/usr/local/bin/fcheck', '/usr/local/bin/imgcvt',
        '/usr/share/applications/Autodesk-Maya2027.desktop',
        '/usr/share/desktop-directories/Autodesk-Maya2027.directory',
        '/usr/share/icons/hicolor/48x48/apps/Maya2027.png',
        '/etc/systemd/system/adsklicensing.service',
        '/etc/systemd/system/multi-user.target.wants/adsklicensing.service',
        '/usr/lib/systemd/system/adsklicensing.service', '/etc/init.d/adsklicensing',
        home / '.rpmdb', home / '.local/share/rpm',
        home / '.local/share/applications', BASE / 'state/desktop', BASE / 'compat-local',
        BASE / 'install', BASE / 'scripts/maya-2027'):
        # SQLite journals and licensing databases change during normal use.
        journal.add(path, volatile=str(path) == '/var/lib/rpm')
    config = config_home or home / '.config'
    path = config / 'mimeapps.list'
    journal.add(path)
    if path.is_symlink():
        journal.add(path.resolve())
    journal.data['capture_complete'] = True
    journal.save()


def register_rpm(journal, key, package, prefix):
    if any(entry['key'] == key for entry in journal.data['rpms']):
        return
    name, version = run('rpm', '-qp', '--qf', '%{NAME}\n%{VERSION}-%{RELEASE}.%{ARCH}', str(package)).stdout.splitlines()
    rows = run('rpm', '-qp', '--qf', '[%{FILENAMES}\t%{FILEMODES}\n]', str(package)).stdout
    for row in rows.splitlines():
        filename, mode = row.split('\t')
        path = Path(filename)
        if not path.is_absolute() or '..' in path.parts:
            raise ValueError(f'Unexpected RPM path: {filename}')
        if prefix and (filename == '/usr' or filename.startswith('/usr/')):
            path = Path(prefix) / filename.removeprefix('/usr').lstrip('/')
        if path != Path('/'):
            journal.add(path, directory_only=(int(mode) & 0o170000) == 0o040000)
    scripts = {}
    for tag in ('PREUN', 'POSTUN'):
        content = run('rpm', '-qp', '--qf', '%{' + tag + '}', str(package)).stdout
        if content == '(none)':
            content = ''
        target = journal.directory / f'{key}-{tag}.sh'
        target.write_text(content)
        os.chmod(target, 0o600)
        run('bash', '-n', str(target))
        scripts[tag] = content
    journal.data['rpms'].append(dict(key=key, name=name, version=version, prefix=prefix, scripts=scripts, removed=False))
    journal.save()


def guard_apt(journal, plan, requested=()):
    before = {name.removesuffix(':amd64') for name in journal.data['deb_before']}
    planned = []
    for line in plan.read_text().splitlines():
        match = re.match(r'Inst (\S+)', line)
        if match and match[1].removesuffix(':amd64') in before:
            raise ValueError(f'APT would change an existing package ({match[1]}). Refusing an installation that cannot restore that version automatically.')
        if match:
            planned.append(match[1].removesuffix(':amd64'))
    journal.data['deb_planned_new'] = planned
    journal.data['deb_requested'] = list(requested)


def seal(journal):
    if not journal.data.get('capture_complete'):
        raise ValueError('Before-state capture did not finish; no system installation should have started.')
    journal.data['deb_after'] = packages()
    journal.data['auto_after'] = run('apt-mark', 'showauto').stdout.splitlines()
    journal.data['adsklic_user_after'] = run('getent', 'passwd', 'adsklic', check=False).stdout
    journal.data['adsklic_group_after'] = run('getent', 'group', 'adsklic', check=False).stdout
    journal.data['rpm_after'] = (run('rpm', '--dbpath', '/var/lib/rpm', '-qa', '--qf', '%{NAME}\t%{VERSION}-%{RELEASE}.%{ARCH}\n', check=False).stdout.splitlines()
                                  if shutil.which('rpm') and Path('/var/lib/rpm').exists() else [])
    journal.seal()


def removal_plan(journal, remove_dependencies):
    problems = []
    installed = (run('rpm', '--dbpath', '/var/lib/rpm', '-qa', '--qf', '%{NAME}\t%{VERSION}-%{RELEASE}.%{ARCH}\n', check=False)
                 if shutil.which('rpm') and Path('/var/lib/rpm/rpmdb.sqlite').is_file() else subprocess.CompletedProcess([], 0, '', ''))
    if installed.returncode and any(not p['removed'] for p in journal.data['rpms']):
        problems.append('Cannot query the shared RPM database; inspect it before removal.')
    known = dict(line.split('\t') for line in journal.data.get('rpm_before', []))
    known.update({p['name']: p['version'] for p in journal.data['rpms']})
    for line in installed.stdout.splitlines():
        name, version = line.split('\t')
        if ((name == 'gpg-pubkey' and line not in journal.data.get('rpm_after', []) + journal.data.get('rpm_before', []))
                or (name != 'gpg-pubkey' and known.get(name) != version)):
            problems.append(f'Unrecorded/changed RPM: {name} {version}')
    after = journal.data['deb_after'] if 'deb_after' in journal.data else packages()
    new_debs = {name: version for name, version in after.items()
                if name not in journal.data['deb_before']
                and name.removesuffix(':amd64') in journal.data.get('deb_planned_new', [])}
    current = packages()
    remove = [name for name in new_debs if name in current]
    if remove_dependencies:
        for name in remove:
            if current[name] != new_debs[name]:
                problems.append(f'Debian package changed since installation: {name}')
        if remove:
            simulated = run('apt-get', '-s', '-o', 'APT::Get::AutomaticRemove=false', 'remove', '--', *remove, check=False)
            if simulated.returncode:
                problems.append('APT cannot produce a safe dependency removal plan.')
            allowed = {name.removesuffix(':amd64') for name in remove}
            for line in simulated.stdout.splitlines():
                match = re.match(r'(Remv|Inst|Conf) (\S+)', line)
                if match and (match[1] != 'Remv' or match[2].removesuffix(':amd64') not in allowed):
                    problems.append(f'APT would change another package: {line}')
    return problems, remove


def apply(journal, args, new_debs):
    if journal.data['phase'] == 'complete':
        print('Rollback already completed.')
        return
    if journal.data['phase'] == 'applying' and not args.resume:
        raise ValueError('Rollback was interrupted; inspect its record and use --resume.')
    journal.data['phase'] = 'applying'
    journal.save()
    stop_watcher()
    uid = journal.data['uid']
    run_as_user(uid, '/usr/bin/python3', str(BASE / 'scripts/install-maya-ui-fixes.py'), '--remove',
                '--app-dir', str(BASE / 'user'))
    for service in ('adsklicensing.service',):
        if run('systemctl', 'is-active', '--quiet', service, check=False).returncode == 0:
            run('systemctl', 'stop', service)
    # Vendor uninstall callbacks can delete runtime state. Preserve it before
    # invoking them, rather than assuming it will survive until file restore.
    for entry in journal.data['entries']:
        path = Path(entry['path'])
        if entry['volatile'] and (path.exists() or path.is_symlink()):
            target = journal.directory / 'before-uninstall' / entry['backup']
            if not target.exists() and not target.is_symlink():
                target.parent.mkdir(mode=0o700, exist_ok=True)
                run('cp', '-a', '--reflink=auto', '--', str(path), str(target))
    for package in reversed(journal.data['rpms']):
        if package['removed']:
            continue
        exists = run('rpm', '--dbpath', '/var/lib/rpm', '-q', package['name'], check=False).returncode == 0
        phase = package.get('undo_phase', 'pending')
        if exists or phase in ('preun', 'erased'):
            env = dict(os.environ)
            if package['prefix']:
                env['RPM_INSTALL_PREFIX'] = package['prefix']
            for tag in ('PREUN', 'POSTUN'):
                if tag == 'PREUN' and phase != 'pending':
                    continue
                if tag == 'POSTUN' and exists:
                    run('rpm', '--dbpath', '/var/lib/rpm', '-e', '--nodeps', '--noscripts', package['name'])
                    package['undo_phase'] = 'erased'
                    journal.save()
                content = package['scripts'][tag]
                if content:
                    script = journal.directory / f'{package["key"]}-{tag}.sh'
                    # Use the root-owned recorded text, not editable installer backups.
                    script.write_text(content)
                    run('bash', str(script), '0', env=env)
                package['undo_phase'] = 'preun' if tag == 'PREUN' else 'postun'
                journal.save()
        package['removed'] = True
        journal.save()
    for kind, command in (('user', 'userdel'), ('group', 'groupdel')):
        before = journal.data.get(f'adsklic_{kind}_before')
        after = journal.data.get(f'adsklic_{kind}_after')
        current = run('getent', 'passwd' if kind == 'user' else 'group', 'adsklic', check=False).stdout
        if not before and current:
            if not after or current != after:
                raise ValueError(f'adsklic {kind} does not match the recorded account; manual review required.')
            run(command, 'adsklic')
    journal.restore(retain_current=args.allow_incomplete)
    run('systemctl', 'daemon-reload')
    run('/sbin/ldconfig')
    appdir = Path(journal.data['home']) / '.local/share/applications'
    if appdir.exists() and shutil.which('update-desktop-database'):
        run_as_user(uid, 'update-desktop-database', str(appdir))
    if args.remove_dependencies and new_debs:
        # Rerun the solver after vendor uninstall before allowing any APT changes.
        problems, new_debs = removal_plan(journal, True)
        if problems:
            raise ValueError('\n'.join(problems))
        if new_debs:
            run('apt-get', '-y', '-o', 'APT::Get::AutomaticRemove=false', 'remove', '--', *new_debs)
    if args.clean_workspace:
        run_as_user(uid, '/usr/bin/python3', str(BASE / 'scripts/helpers/local_undo.py'), 'restore', '--apply')
    current = packages()
    restore_auto = sorted(set(journal.data['auto_before']) - set(journal.data.get('auto_after', [])))
    requested = {name.removesuffix(':amd64') for name in journal.data.get('deb_requested', [])}
    restore_auto = [name for name in restore_auto if name.removesuffix(':amd64') in requested]
    current_names = {name.removesuffix(':amd64') for name in current}
    restore_auto = [name for name in restore_auto if name.removesuffix(':amd64') in current_names]
    if restore_auto:
        run('apt-mark', 'auto', '--', *restore_auto)
    journal.data['phase'] = 'complete'
    journal.save()
    print('Recorded system changes restored. Projects, preferences, media, logs and private recovery backups are retained.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Execute the previewed system rollback (requires sudo).')
    parser.add_argument('--remove-dependencies', action='store_true', help='Also remove newly installed Debian packages after a safe solver check; never autoremove or downgrade.')
    parser.add_argument('--allow-incomplete', action='store_true', help='Allow an unsealed interrupted installation; retain current managed paths in private recovery backups.')
    parser.add_argument('--resume', action='store_true', help='Resume an interrupted rollback after reviewing its record.')
    parser.add_argument('--ui-only', action='store_true', help='Remove the marked startup block and stop this clone\'s panel helper without system removal.')
    parser.add_argument('--app-dir', type=Path, help='MAYA_APP_DIR for --ui-only (default: this clone/user).')
    parser.add_argument('--workspace-only', action='store_true', help='Restore local media/download/cache/log scopes recorded by the helpers, without system changes.')
    parser.add_argument('--clean-workspace', action='store_true', help='Also restore recorded local helper scopes; retain current data privately.')
    parser.add_argument('--rpm-db', type=Path, help='Undo standalone empty-database initialization using its adjacent .maya-undo record.')
    parser.add_argument('--record', choices=('capture', 'rpm', 'seal', 'guard-apt'), help=argparse.SUPPRESS)
    parser.add_argument('--home', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--config-home', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--uid', type=int, help=argparse.SUPPRESS)
    parser.add_argument('--key', help=argparse.SUPPRESS)
    parser.add_argument('--package', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--prefix', default='', help=argparse.SUPPRESS)
    parser.add_argument('--apt-plan', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--apt-requested', nargs='+', default=[], help=argparse.SUPPRESS)
    args = parser.parse_args()
    os.umask(0o077)
    os.environ['LC_ALL'] = 'C'
    installer_lock = None
    if args.ui_only or args.workspace_only:
        lock_path = BASE / 'state/installer/lock'
        if lock_path.exists():
            installer_lock = lock_path.open('r')
            fcntl.flock(installer_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if args.rpm_db or args.workspace_only:
        if args.ui_only or args.record or args.remove_dependencies or args.clean_workspace or args.resume or args.allow_incomplete or args.app_dir:
            parser.error('Use --workspace-only or --rpm-db separately from other modes.')
        if args.rpm_db and args.workspace_only:
            parser.error('Use one rollback mode at a time.')
        import local_undo
        if args.rpm_db:
            local_undo.database_restore(args.rpm_db, args.apply)
        else:
            if os.geteuid() == 0:
                parser.error('Run --workspace-only as your normal user, without sudo.')
            require_maya_closed(os.getuid())
            if args.apply:
                stop_watcher()
            local_undo.restore(args.apply)
        return
    if args.ui_only:
        if args.record or args.remove_dependencies or args.resume or args.allow_incomplete:
            parser.error('--ui-only cannot be combined with system rollback options.')
        if os.geteuid() == 0:
            parser.error('Run --ui-only as your normal desktop user, without sudo.')
        require_maya_closed(os.getuid())
        app = args.app_dir or BASE / 'user'
        print(f'Remove marked Hotbox startup block from {app}/2027/scripts/userSetup.py and stop this clone\'s panel helper.')
        if args.clean_workspace:
            import local_undo
            local_undo.restore(False)
        if args.apply:
            stop_watcher()
            spec = importlib.util.spec_from_file_location('ui_install', BASE / 'scripts/install-maya-ui-fixes.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            print(module.configure(app, '2027', remove=True))
            if args.clean_workspace:
                import local_undo
                local_undo.restore(True)
        return
    if args.app_dir:
        parser.error('--app-dir requires --ui-only.')
    if os.geteuid() != 0:
        parser.error('Use sudo for system preview/rollback, or --ui-only for standalone UI fixes.')
    state = BASE / 'state/installer'
    if not args.record and not (BASE / 'state/rollback/manifest.json').exists():
        raise ValueError('No before-state record. Older installations cannot be automatically reversed safely; see docs/ROLLBACK.md.')
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Recorder calls are children of the installer, which already owns lock.
    with (state / ('record.lock' if args.record else 'lock')).open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        journal = Journal(BASE / 'state/rollback')
        if args.record == 'capture':
            if args.home is None or args.uid is None:
                parser.error('capture requires user home and uid')
            capture(journal, args.home, args.uid, args.config_home)
            return
        if not journal.manifest.exists():
            raise ValueError('No before-state record. Older installations cannot be automatically reversed safely; see docs/ROLLBACK.md.')
        if journal.data['repo'] != str(BASE):
            raise ValueError('Repository moved; restore its recorded location before rollback.')
        if args.record:
            if args.record == 'rpm':
                register_rpm(journal, args.key, args.package, args.prefix)
            elif args.record == 'guard-apt':
                guard_apt(journal, args.apt_plan, args.apt_requested)
                journal.save()
            else:
                seal(journal)
            return
        if journal.data['phase'] == 'complete':
            print('Rollback already completed; no changes made.')
            return
        require_maya_closed(journal.data['uid'])
        problems = journal.conflicts(args.allow_incomplete)
        plan_problems, new_debs = removal_plan(journal, args.remove_dependencies)
        problems += plan_problems
        print('Rollback preview (no changes unless --apply):')
        for entry in journal.data['entries']:
            if not entry['restored']:
                print(('RESTORE ' if entry['before'] is not None else 'REMOVE  ') + entry['path']
                      + (' (retain service data privately)' if entry['volatile'] else ''))
        for package in reversed(journal.data['rpms']):
            print('UNINSTALL RPM ' + package['name'])
        print(('REMOVE' if args.remove_dependencies else 'KEEP') + ' new Debian packages: ' + ' '.join(new_debs))
        if args.clean_workspace:
            run_as_user(journal.data['uid'], '/usr/bin/python3', str(BASE / 'scripts/helpers/local_undo.py'), 'restore')
        if problems:
            raise ValueError('\n'.join(problems))
        if args.apply:
            apply(journal, args, new_debs)


if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError as error:
        report = BASE / 'state/rollback/last-error.txt'
        if report.parent.exists():
            report.write_text(str(error) + '\n' + str(error.stdout or '') + '\n' + str(error.stderr or ''))
            os.chmod(report, 0o600)
            sys.exit(f'Rollback command failed; private details: {report}')
        sys.exit(str(error))
    except (OSError, ValueError) as error:
        sys.exit(str(error))
