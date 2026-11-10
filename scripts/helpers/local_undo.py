#!/usr/bin/env python3
"""Record local helper side effects separately from privileged installation."""
import argparse
from contextlib import ExitStack
import fcntl
from functools import wraps
import os
from pathlib import Path
import subprocess

from rollback_state import Journal

BASE = Path(__file__).resolve().parents[2]
SCOPES = {
    'media': [('media/2027.2', False)],
    'downloads': [('compat-download', False)],
    'launcher': [('cache/tmp', False), ('logs', False), ('user', True), ('projects', True)],
    'panels': [('state/i3', False), ('logs/maya-i3-panels.txt', False)],
    'diagnostic': [('logs', False)],
}


def locked(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        state = BASE / 'state'
        state.mkdir(mode=0o700, parents=True, exist_ok=True)
        with (state / 'local-undo.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            return function(*args, **kwargs)
    return wrapper


def helpers_idle(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        with ExitStack() as stack:
            for path in (BASE / 'compat-download/download.lock', BASE / 'state/local-undo/media-operation.lock'):
                if path.exists():
                    lock = stack.enter_context(path.open('r'))
                    try:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        raise ValueError(f'A helper is still running: {path}') from None
            return function(*args, **kwargs)
    return wrapper


@locked
def capture(scope):
    journal = Journal(BASE / 'state/local-undo' / scope)
    if journal.manifest.exists():
        if journal.data['phase'] == 'complete':
            raise ValueError(f'Local {scope} changes were already rolled back. Archive its state/local-undo record before using the helper again.')
        if journal.data['phase'] != 'sealed':
            raise ValueError(f'Local {scope} capture was interrupted; inspect its record before running the helper.')
        return
    journal.data['repo'] = str(BASE)
    for path, directory_only in SCOPES[scope]:
        journal.add(BASE / path, directory_only=directory_only, volatile=not directory_only)
    journal.seal()


@locked
def capture_uri(path):
    journal = Journal(BASE / 'state/local-undo/identity-uri')
    if not journal.manifest.exists():
        journal.data['repo'] = str(BASE)
        journal.add(path)
        if Path(path).is_symlink():
            journal.add(Path(path).resolve())
        journal.seal()
    elif journal.data['phase'] == 'complete':
        raise ValueError('URI handler changes were already rolled back; archive that local undo record first.')
    else:
        problems = journal.conflicts()
        if problems:
            raise ValueError('\n'.join(problems))
    return journal


@locked
@helpers_idle
def restore(apply=False):
    # Reverse timestamp order: scopes may cover overlapping local log paths.
    manifests = sorted((BASE / 'state/local-undo').glob('*/manifest.json'),
                       key=lambda p: p.stat().st_mtime_ns, reverse=True)
    for manifest in manifests:
        journal = Journal(manifest.parent)
        if journal.data['phase'] == 'complete':
            continue
        if journal.data.get('repo') != str(BASE):
            raise ValueError('Local undo record belongs to another clone location.')
        problems = journal.conflicts()
        if problems:
            raise ValueError('\n'.join(problems))
        for entry in journal.data['entries']:
            print(('RESTORE ' if entry['before'] is not None else 'REMOVE ') + entry['path'] + ' (keep current data in private retained backups)')
        if apply:
            journal.restore(retain_current=True)
            journal.data['phase'] = 'complete'
            journal.save()


def database_record(database):
    database = Path(database)
    journal = Journal(database.with_name(database.name + '.maya-undo'))
    if journal.manifest.exists():
        raise ValueError('A database undo record already exists; inspect it before reinitializing.')
    journal.data['database'] = str(database)
    journal.add(database, volatile=True)
    journal.seal()


def database_restore(database, apply=False):
    database = Path(database)
    operation = database.with_name(database.name + '.maya-undo') / 'operation.lock'
    with ExitStack() as stack:
        if operation.exists():
            lock = stack.enter_context(operation.open('r'))
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('Database initialization is still active.') from None
        _database_restore(database, apply)


def _database_restore(database, apply=False):
    database = Path(database)
    journal = Journal(database.with_name(database.name + '.maya-undo'))
    if not journal.manifest.exists() or journal.data.get('database') != str(database):
        raise ValueError('No matching standalone RPM database before-state record.')
    if journal.data['phase'] == 'complete':
        print('Standalone database rollback already completed.')
        return
    if database.exists():
        if (database / 'rpmdb.sqlite').is_file():
            result = subprocess.run(['rpm', '--dbpath', str(database), '-qa'], capture_output=True, text=True, check=True)
            if result.stdout.strip():
                raise ValueError('The standalone database contains package/key records; refusing to remove it.')
        elif any(database.iterdir()):
            raise ValueError('Unrecognized database contents; refusing to initialize or remove them during rollback.')
    problems = journal.conflicts()
    if problems:
        raise ValueError('\n'.join(problems))
    print('Restore original empty/absent database directory: ' + str(database))
    if apply:
        journal.restore(retain_current=True)
        journal.data['phase'] = 'complete'
        journal.save()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['capture', 'restore', 'database-record', 'database-restore'])
    parser.add_argument('target', nargs='?')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.action == 'capture':
            if args.target not in SCOPES:
                parser.error('Unknown local scope')
            capture(args.target)
        elif args.action == 'restore':
            restore(args.apply)
        elif args.action == 'database-record':
            database_record(args.target)
        else:
            database_restore(args.target, args.apply)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, str(error) + '\n')
