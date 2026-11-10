#!/usr/bin/env python3
"""Set one Identity Manager URI default using only the recorded MIME file."""
import argparse
import configparser
import os
from pathlib import Path
import tempfile


def configure(path, scheme):
    path = Path(path)
    if path.is_symlink():
        path = path.resolve()
    config = configparser.RawConfigParser(strict=False)
    config.optionxform = str
    if path.exists():
        with path.open(encoding='utf-8') as stream:
            config.read_file(stream)
    section = 'Default Applications'
    if not config.has_section(section):
        config.add_section(section)
    config.set(section, 'x-scheme-handler/' + scheme, 'com.autodesk.AdskIdentityManager.desktop;')
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            config.write(stream, space_around_delimiters=False)
        if path.exists():
            os.chmod(temporary, path.stat().st_mode & 0o777)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scheme', choices=['adskidmgr', 'adsk.idmgr'])
    args = parser.parse_args()
    os.umask(0o077)
    from local_undo import capture_uri
    path = Path(os.environ.get('XDG_CONFIG_HOME') or str(Path.home() / '.config')) / 'mimeapps.list'
    journal = capture_uri(path)
    configure(path, args.scheme)
    journal.seal()
