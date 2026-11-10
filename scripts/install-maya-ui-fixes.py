#!/usr/bin/env python3
"""Install/remove only our deferred Hotbox startup block; preserve other setup."""
import argparse
from datetime import datetime
import io
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import tokenize

BASE = Path(__file__).resolve().parents[1]
BEGIN = '# BEGIN maya-debian-hotbox'
END = '# END maya-debian-hotbox'


def startup_block(text):
    """Locate real, whole-line comments; marker examples in strings are user data."""
    markers = []
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        if token.type != tokenize.COMMENT or not token.string.startswith((BEGIN, END)):
            continue
        if token.start[1] != 0 or token.string not in (BEGIN, END):
            raise ValueError('Startup markers have an unexpected layout; inspect userSetup.py.')
        markers.append((token.string, token.start[0]))
    if not markers:
        return None
    if [marker for marker, _ in markers] != [BEGIN, END]:
        raise ValueError('Startup markers are incomplete, duplicated or reversed; inspect userSetup.py.')
    return markers[0][1] - 1, markers[1][1]


def configure(app_dir, version, remove=False):
    target = Path(app_dir).expanduser().resolve() / str(version) / 'scripts/userSetup.py'
    if target.is_symlink():
        raise ValueError('userSetup.py is a symlink; edit its target explicitly instead.')
    record = target.with_name('.maya-hotbox-undo.json')
    if record.is_symlink():
        raise ValueError('Startup undo record is a symlink; inspect it first.')
    undo = json.loads(record.read_text()) if record.exists() else None
    if undo is not None and (not isinstance(undo, dict)
                             or not isinstance(undo.get('original_exists'), bool)
                             or not isinstance(undo.get('original_sha256'), str)
                             or not isinstance(undo.get('separator_added'), bool)):
        raise ValueError('Invalid startup undo record; inspect .maya-hotbox-undo.json.')
    previous = target.read_bytes() if target.exists() else b''
    encoding, _ = tokenize.detect_encoding(io.BytesIO(previous).readline)
    text = previous.decode(encoding)
    compile(previous, str(target), 'exec')
    newline = '\r\n' if b'\r\n' in previous else '\n'
    match = startup_block(text)
    block = ''
    if not remove:
        source = BASE / 'scripts/fix-maya-hotbox-geometry.py'
        if not source.is_file():
            raise ValueError(f'Hotbox script missing: {source}')
        block = (BASE / 'templates/userSetup-hotbox.py').read_text(encoding='utf-8').replace(
            '__MAYA_HOTBOX_SCRIPT__', ascii(str(source))).replace('\n', newline)
    if match:
        lines = io.StringIO(text).readlines()
        start, end = match
        updated = ''.join(lines[:start]) + block + ''.join(lines[end:])
    elif block:
        updated = text + (newline if text and not text.endswith('\n') else '') + block
    else:
        return target, False, None
    result = updated.encode(encoding)
    if remove and undo and undo.get('separator_added') and updated.endswith(newline):
        candidate = updated[:-len(newline)].encode(encoding)
        if hashlib.sha256(candidate).hexdigest() == undo['original_sha256']:
            result = candidate
    if result == previous:
        return target, False, None
    compile(result, str(target), 'exec')
    target.parent.mkdir(parents=True, exist_ok=True)
    if not remove and undo is None:
        undo = dict(original_exists=target.exists(),
                    original_sha256=hashlib.sha256(previous).hexdigest(),
                    separator_added=bool(text and not text.endswith('\n') and match is None))
        with tempfile.NamedTemporaryFile(mode='w', dir=target.parent, delete=False) as stream:
            undo_temporary = Path(stream.name)
            json.dump(undo, stream)
        undo_temporary.replace(record)
    backup = None
    if target.exists():
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        backup = target.with_name('userSetup.py.before-hotbox-' + stamp)
        shutil.copy2(target, backup)
    if remove and undo and not undo['original_exists'] and result in (b'', b'\xef\xbb\xbf'):
        target.unlink()
        record.unlink(missing_ok=True)
        return target, True, backup
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(result)
        if target.exists():
            os.chmod(temporary, target.stat().st_mode & 0o777)
        temporary.replace(target)
        if remove:
            record.unlink(missing_ok=True)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return target, True, backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-dir', type=Path, required=True,
                        help='MAYA_APP_DIR used by your launcher (normally ~/maya).')
    parser.add_argument('--version', default='2027', choices=['2027'])
    parser.add_argument('--remove', action='store_true')
    args = parser.parse_args()
    try:
        target, changed, backup = configure(args.app_dir, args.version, args.remove)
    except (OSError, ValueError, SyntaxError, tokenize.TokenError) as error:
        parser.exit(1, str(error) + '\n')
    print(('Updated: ' if changed else 'Unchanged: ') + str(target))
    if backup:
        print('Backup: ' + str(backup))


if __name__ == '__main__':
    main()
