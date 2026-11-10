"""Private before/after journal for explicitly managed filesystem paths."""
import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess


def fingerprint(path, directory_only=False):
    path = Path(path)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    result = {'mode': stat.S_IMODE(info.st_mode), 'uid': info.st_uid, 'gid': info.st_gid}
    if stat.S_ISLNK(info.st_mode):
        result.update(kind='link', target=os.readlink(path))
    elif stat.S_ISREG(info.st_mode):
        with path.open('rb') as stream:
            result.update(kind='file', sha256=hashlib.file_digest(stream, 'sha256').hexdigest())
    elif stat.S_ISDIR(info.st_mode):
        result['kind'] = 'directory'
        if not directory_only:
            result['children'] = {p.name: fingerprint(p) for p in sorted(path.iterdir())}
    else:
        raise ValueError(f'Unsupported special file: {path}')
    return result


class Journal:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.manifest = self.directory / 'manifest.json'
        self.data = json.loads(self.manifest.read_text()) if self.manifest.exists() else {
            'version': 1, 'phase': 'recording', 'entries': [], 'rpms': []}
        if self.data['version'] != 1:
            raise ValueError('Unsupported rollback journal version.')

    def save(self):
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.directory.is_symlink():
            raise ValueError('Rollback directory must not be a symlink.')
        temporary = self.directory / 'manifest.new'
        with temporary.open('w', encoding='utf-8') as stream:
            os.chmod(temporary, 0o600)
            json.dump(self.data, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self.manifest)

    def add(self, path, directory_only=False, volatile=False):
        path = Path(os.path.abspath(path))
        if path == Path('/') or path == self.directory or self.directory.is_relative_to(path):
            raise ValueError(f'Unsafe rollback scope: {path}')
        # Parent symlinks such as Debian's /lib -> /usr/lib are canonicalized;
        # the last component is deliberately not resolved.
        path = path.parent.resolve() / path.name
        if path == Path('/') or path == self.directory or self.directory.is_relative_to(path):
            raise ValueError(f'Unsafe rollback scope after resolving parent aliases: {path}')
        directory_link = directory_only and path.is_symlink()
        if directory_link:
            directory_only = False
        if not directory_only and path.is_symlink() and path.is_dir() and not directory_link:
            raise ValueError(f'Directory scope must not be a symlink: {path}')
        for entry in self.data['entries']:
            parent = Path(entry['path'])
            if path == parent or (not entry['directory_only'] and path.is_relative_to(parent)):
                return
        if not path.parent.exists():
            self.add(path.parent, directory_only=True)
        before = fingerprint(path, directory_only)
        backup = str(len(self.data['entries']))
        if before is not None and not directory_only:
            target = self.directory / 'before' / backup
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            subprocess.run(['cp', '-a', '--', str(path), str(target)], check=True)
        self.data['entries'].append(dict(path=str(path), before=before, backup=backup,
                                         directory_only=directory_only, volatile=volatile,
                                         parent=str(path.parent.resolve()), restored=False))
        self.save()

    def seal(self):
        for entry in self.data['entries']:
            entry['after'] = fingerprint(entry['path'], entry['directory_only']) if not entry['volatile'] else None
        self.data['phase'] = 'sealed'
        self.save()

    def conflicts(self, incomplete=False):
        problems = []
        if self.data['phase'] == 'recording' and not incomplete:
            problems.append('Installation was interrupted before its after-state was recorded; use --allow-incomplete only after reviewing the preview.')
        for entry in self.data['entries']:
            if entry['restored']:
                continue
            path = Path(entry['path'])
            if str(path.parent.resolve()) != entry['parent']:
                problems.append(f'Parent path changed: {path}')
                continue
            if entry['before'] is not None and not entry['directory_only']:
                if fingerprint(self.directory / 'before' / entry['backup']) != entry['before']:
                    problems.append(f'Before-state backup changed: {path}')
            current = fingerprint(path, entry['directory_only']) if not entry['volatile'] else None
            if entry['directory_only'] and entry['before'] is None and current and current['kind'] == 'directory':
                # New containers can now hold user projects/preferences. Restore
                # only their absence when empty, never their later contents.
                continue
            if (self.data['phase'] == 'sealed' and not entry['volatile']
                    and current not in (entry.get('after'), entry['before'])):
                problems.append(f'Changed since installation: {path}')
        return problems

    def restore(self, retain_current=False):
        # Children before container directories. All conflicts must be checked
        # before vendor removal; vendor scriptlets will themselves change paths.
        for entry in sorted(self.data['entries'], key=lambda e: len(Path(e['path']).parts), reverse=True):
            if entry['restored']:
                continue
            path = Path(entry['path'])
            if str(path.parent.resolve()) != entry['parent']:
                raise ValueError(f'Parent changed during rollback: {path}')
            before = entry['before']
            if ((before is None and not path.exists() and not path.is_symlink())
                    or (before is not None and fingerprint(path, entry['directory_only']) == before)):
                entry['restored'] = True
                self.save()
                continue
            if entry['directory_only']:
                if before is None:
                    try:
                        path.rmdir()
                    except FileNotFoundError:
                        pass
                    except OSError as error:
                        if error.errno not in (errno.ENOTEMPTY, errno.EEXIST):
                            raise
                        print(f'Kept nonempty container directory: {path}')
                elif before['kind'] == 'directory':
                    if not path.exists():
                        path.mkdir(parents=True)
                    if not path.is_dir() or path.is_symlink():
                        raise ValueError(f'Expected directory: {path}')
                    os.chmod(path, before['mode'])
                    os.chown(path, before['uid'], before['gid'])
                else:
                    raise ValueError(f'Expected directory: {path}')
            else:
                if path.exists() or path.is_symlink():
                    if entry['volatile'] or retain_current:
                        retained = self.directory / 'retained' / entry['backup']
                        retained.parent.mkdir(mode=0o700, exist_ok=True)
                        if retained.exists() or retained.is_symlink():
                            raise ValueError(f'Retained backup already exists: {retained}')
                        shutil.move(str(path), str(retained))
                    elif path.is_dir() and not path.is_symlink():
                        shutil.rmtree(path)
                    else:
                        path.unlink()
                if before is not None:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    subprocess.run(['cp', '-a', '--', str(self.directory / 'before' / entry['backup']), str(path)], check=True)
            entry['restored'] = True
            self.save()
