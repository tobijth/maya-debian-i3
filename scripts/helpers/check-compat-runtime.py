#!/usr/bin/env python3
"""Gate A: inspect genuine staged Debian compatibility libraries before deployment."""
import os
from pathlib import Path
import re
import subprocess
import sys

BASE = Path(__file__).resolve().parents[2]
STAGE = BASE / 'compat-stage'

def run(*args, env=None):
    return subprocess.run(args, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, env=env, check=True).stdout

def main():
    versions = {}
    for package in (BASE / 'compat-download/debs').glob('*.deb'):
        name, version = run('dpkg-deb', '-f', str(package), 'Package', 'Version').splitlines()
        versions[name.removeprefix('Package: ')] = version.removeprefix('Version: ')
    if 'libwebkit2gtk-4.0-37' not in versions or 'libjavascriptcoregtk-4.0-18' not in versions:
        sys.exit('Authentifizierte WebKit-/JavaScriptCore-DEBs fehlen.')
    webkit = versions['libwebkit2gtk-4.0-37']
    if webkit != versions['libjavascriptcoregtk-4.0-18']:
        sys.exit('WebKit/JavaScriptCore stammen nicht aus demselben Build.')
    upstream = webkit.split(':')[-1].split('-')[0]
    subprocess.run(['dpkg', '--compare-versions', upstream, 'ge', '2.46'], check=True)
    host_sonames = set(re.findall(r'^\s*(\S+)\s+\(', run('/sbin/ldconfig', '-p'), re.M))
    libdirs = [STAGE / 'usr/lib/x86_64-linux-gnu', STAGE / 'lib/x86_64-linux-gnu']
    env = dict(os.environ)
    env.pop('LD_PRELOAD', None)
    env['LD_LIBRARY_PATH'] = ':'.join(str(p) for p in libdirs if p.is_dir())
    elf_files = []
    sonames = set()
    errors = []
    for path in sorted(STAGE.rglob('*')):
        if path.is_symlink() or not path.is_file():
            continue
        with path.open('rb') as f:
            if f.read(4) != b'\x7fELF': continue
        elf_files.append(path)
        dynamic = run('readelf', '-d', str(path))
        match = re.search(r'\(SONAME\).*\[(.*?)\]', dynamic)
        if match:
            soname = match[1]
            sonames.add(soname)
            if soname in host_sonames:
                errors.append(f'SONAME bereits im Host vorhanden: {soname}; {path}')
        loaded = subprocess.run(['ldd', str(path)], text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, env=env)
        if loaded.returncode or 'not found' in loaded.stdout:
            errors.append(f'Loader-Fehler: {path}\n{loaded.stdout}')
    required = {'libwebkit2gtk-4.0.so.37', 'libjavascriptcoregtk-4.0.so.18',
                'libssl.so.1.1', 'libcrypto.so.1.1', 'libtiff.so.5'}
    if required - sonames:
        errors.append(f'Pflichtbibliotheken fehlen: {sorted(required - sonames)}')
    helpers = STAGE / 'usr/lib/x86_64-linux-gnu/webkit2gtk-4.0'
    for name in ('WebKitNetworkProcess', 'WebKitWebProcess'):
        path = helpers / name
        if not path.is_file() or not os.access(path, os.X_OK):
            errors.append(f'Ausfuehrbarer WebKit-Helfer fehlt: {path}')
    if not elf_files: errors.append('Keine ELF-Dateien im Kompatibilitaetsverzeichnis.')
    print(f'WebKit {webkit}; {len(elf_files)} ELF-Dateien geprueft.')
    if errors:
        sys.exit('\n\n'.join(errors))
    print('Gate A bestanden: Loader-Abhaengigkeiten und SONAME-Kollisionen geprueft.')

if __name__ == '__main__':
    main()
