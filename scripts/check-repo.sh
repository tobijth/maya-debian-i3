#!/bin/bash
# Offline checks only: no Maya launch, package installation or system changes.
set -euo pipefail
base=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd "$base"
for tool in python3 rpm sha256sum; do
    command -v "$tool" >/dev/null || {
        printf 'Missing test dependency: %s (see docs/TESTING.md).\n' "$tool" >&2
        exit 1
    }
done
export PYTHONDONTWRITEBYTECODE=1
python3 - <<'PY'
from pathlib import Path
import subprocess
import sys

if sys.version_info < (3, 11):
    sys.exit('Repository checks require Python 3.11 or newer.')
count = 0
for directory in ('scripts', 'templates', 'tests'):
    for path in sorted(Path(directory).rglob('*')):
        if not path.is_file():
            continue
        if path.suffix == '.py':
            compile(path.read_bytes(), str(path), 'exec')
            count += 1
        elif path.suffix == '.sh' or path.name == 'maya-2027':
            subprocess.run(['bash', '-n', str(path)], check=True)
            count += 1
print(f'Syntax OK: {count} Python/Bash files.', flush=True)
PY
python3 -m unittest discover -s tests -v
sha256sum -c EXPORT-SHA256SUMS
