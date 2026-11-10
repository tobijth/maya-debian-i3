#!/bin/bash
# Verify the exact locally inspected archive before extracting into an empty target.
set -euo pipefail
umask 077
base=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
archive=${1:-"$base/Autodesk_Maya_2027_2_Update_Linux_64bit.tgz"}
target="$base/media/2027.2"
expected=7795762cd587ad0e8428be3bd1ed101bf92bdf799569299a7556cfbaaf4405c4
[[ $EUID != 0 ]] || { echo 'Run as your normal user, without sudo.' >&2; exit 1; }
[[ -f $archive ]] || { echo 'Download the Maya 2027.2 Linux archive from your Autodesk Account first.' >&2; exit 1; }
actual=$(sha256sum -- "$archive")
[[ ${actual%% *} == "$expected" ]] || { echo 'Archive differs from the exact release inspected here; extraction stopped.' >&2; exit 1; }
python3 "$base/scripts/helpers/local_undo.py" capture media
exec 8>"$base/state/local-undo/media-operation.lock"
flock -n 8 || { echo 'Another media preparation or rollback is active.' >&2; exit 1; }
mkdir -p "$target"
[[ -z $(find "$target" -mindepth 1 -maxdepth 1 -print -quit) ]] || {
    echo 'media/2027.2 must be empty. Inspect an existing or interrupted extraction first.' >&2; exit 1;
}
tar --no-same-owner --no-same-permissions -xzf "$archive" -C "$target"
cd "$base"
sha256sum -c metadata/core-packages.sha256
cp metadata/core-packages.sha256 "$target/core-packages.sha256"
touch "$target/.verified-extraction"
printf 'Verified media ready: %s\n' "$target"
