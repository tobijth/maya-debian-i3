#!/usr/bin/env python3
"""Resume APT downloads using hashes from its authenticated --print-uris plan."""
from datetime import datetime
import hashlib
from pathlib import Path
import re
import shlex
import sys
from urllib.parse import unquote, urlsplit


def read_plan(path):
    entries = []
    seen = set()
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        fields = shlex.split(line)
        if len(fields) != 4:
            raise ValueError(f'Unerwartete APT-Planzeile: {line}')
        url, filename, size, digest = fields
        match = re.fullmatch(r'([a-z0-9][a-z0-9+.-]*)_([^/\s_]+)_(amd64|all)\.deb', filename)
        if not match or filename in seen:
            raise ValueError(f'Ungueltiger/doppelter Paketdateiname: {filename}')
        if not re.fullmatch(r'SHA256:[0-9a-fA-F]{64}', digest) or not size.isdecimal():
            raise ValueError(f'APT-SHA256/Groesse fehlt: {filename}')
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.hostname not in {
            'deb.debian.org', 'security.debian.org', 'archive.debian.org'
        }:
            raise ValueError(f'Unerwartete Paketquelle: {url}')
        name, version, arch = match.groups()
        version = unquote(version)
        if not re.fullmatch(r'[0-9][a-zA-Z0-9.+:~\-]*', version):
            raise ValueError(f'Ungueltige Paketversion: {version}')
        entries.append(dict(filename=filename, size=int(size), sha256=digest[7:].lower(),
                            package=f'{name}:{arch}={version}'))
        seen.add(filename)
    if not entries:
        raise ValueError('APT-Downloadplan ist leer.')
    return entries


def matches(path, entry):
    if path.is_symlink() or not path.is_file() or path.stat().st_size != entry['size']:
        return False
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest() == entry['sha256']


def prepare(work, entries):
    debs = work / 'debs'
    names = {entry['filename'] for entry in entries}
    backup = None

    def preserve(path):
        nonlocal backup
        if backup is None:
            backup = work / 'previous' / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
            backup.mkdir(parents=True)
        path.rename(backup / path.name)
        print(f'Vorherigen Download gesichert: {path.name} -> {backup}')

    # Staging extracts *.deb, so keep only the exact authenticated selection.
    for path in sorted(debs.glob('*.deb')):
        if path.name not in names:
            preserve(path)
    missing = []
    reused = 0
    for entry in entries:
        path = debs / entry['filename']
        if matches(path, entry):
            reused += 1
            print(f'SHA256 bestaetigt, wird wiederverwendet: {path.name}')
        else:
            if path.exists() or path.is_symlink():
                preserve(path)
            missing.append(entry['package'])
    # The install driver must not see a completed checksum manifest after a
    # partial refresh or failed download.
    manifest = debs / 'SHA256SUMS'
    if manifest.exists() or manifest.is_symlink():
        preserve(manifest)
    (work / 'missing-packages.txt').write_text(''.join(p + '\n' for p in missing))
    print(f'{reused} Pakete verifiziert; {len(missing)} Pakete nachzuladen.')


def validate_files(work, entries):
    debs = work / 'debs'
    expected = {entry['filename'] for entry in entries}
    actual = {p.name for p in debs.glob('*.deb')}
    if actual != expected:
        raise ValueError(f'Paketdateien fehlen/sind unerwartet: {sorted(actual ^ expected)}')
    for entry in entries:
        if not matches(debs / entry['filename'], entry):
            raise ValueError(f'Groessen-/SHA256-Pruefung fehlgeschlagen: {entry["filename"]}')


def manifest_text(entries):
    return ''.join(f'{e["sha256"]}  {e["filename"]}\n' for e in entries)


def check(work, entries):
    """Read-only installation gate, including files absent from SHA256SUMS."""
    validate_files(work, entries)
    manifest = work / 'debs/SHA256SUMS'
    if (manifest.is_symlink() or not manifest.is_file()
            or manifest.read_text(encoding='utf-8') != manifest_text(entries)):
        raise ValueError('SHA256SUMS stimmt nicht mit dem authentifizierten Downloadplan ueberein.')
    print(f'Installationssatz vollstaendig: {len(entries)} Pakete gegen den APT-Plan geprueft.')


def verify(work, entries):
    debs = work / 'debs'
    # A failed recheck must not leave an earlier success marker available.
    (debs / 'SHA256SUMS').unlink(missing_ok=True)
    validate_files(work, entries)
    temporary = debs / 'SHA256SUMS.new'
    temporary.write_text(manifest_text(entries), encoding='utf-8')
    temporary.replace(debs / 'SHA256SUMS')
    print(f'Alle {len(entries)} Pakete gegen die APT-Pruefsummen verifiziert.')


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in {'prepare', 'verify', 'check'}:
        raise ValueError('Aufruf: compat-download-plan.py prepare|verify|check DOWNLOADORDNER')
    work = Path(sys.argv[2])
    entries = read_plan(work / 'download-plan.txt')
    {'prepare': prepare, 'verify': verify, 'check': check}[sys.argv[1]](work, entries)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as error:
        sys.exit(str(error))
