#!/bin/bash
# Download-only helper. Never installs packages or edits system APT sources.
# Read docs/INSTALL-MAYA.md before using. Downloads still require dependency review.
set -euo pipefail
umask 077
export LC_ALL=C
if (( EUID == 0 )); then
    echo 'Run this download-only script as your normal user, without sudo.' >&2
    exit 1
fi
base=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)
work="$base/compat-download"
python3 "$base/scripts/helpers/local_undo.py" capture downloads
mkdir -p "$work/lists/partial" "$work/archives/partial" "$work/debs"
exec 8>"$work/download.lock"
flock -n 8 || { echo 'Another compatibility download is active.' >&2; exit 1; }
test -r /usr/share/keyrings/debian-archive-keyring.gpg
cat > "$work/sources.list" <<'EOF'
deb [arch=amd64 signed-by=/usr/share/keyrings/debian-archive-keyring.gpg] https://deb.debian.org/debian bookworm main
deb [arch=amd64 signed-by=/usr/share/keyrings/debian-archive-keyring.gpg] https://security.debian.org/debian-security bookworm-security main
deb [arch=amd64 signed-by=/usr/share/keyrings/debian-archive-keyring.gpg] https://deb.debian.org/debian bullseye main
deb [arch=amd64 signed-by=/usr/share/keyrings/debian-archive-keyring.gpg] https://archive.debian.org/debian-security bullseye-security main
EOF
opts=(
    -o "Dir::Etc::sourcelist=$work/sources.list"
    -o 'Dir::Etc::sourceparts=-'
    -o "Dir::State::lists=$work/lists"
    -o "Dir::Cache::archives=$work/archives"
    -o 'Dir::Cache::pkgcache='
    -o 'Dir::Cache::srcpkgcache='
    -o 'APT::Get::List-Cleanup=0'
    -o 'APT::Update::Error-Mode=any'
    -o 'Acquire::Languages=none'
    -o 'Acquire::IndexTargets::deb::DEP-11::DefaultEnabled=false'
    -o 'Acquire::IndexTargets::deb::DEP-11-icons-small::DefaultEnabled=false'
    -o 'Acquire::IndexTargets::deb::DEP-11-icons::DefaultEnabled=false'
    -o 'Acquire::IndexTargets::deb::DEP-11-icons-hidpi::DefaultEnabled=false'
    -o 'Acquire::IndexTargets::deb::DEP-11-icons-large::DefaultEnabled=false'
    -o 'Acquire::IndexTargets::deb::DEP-11-icons-large-hidpi::DefaultEnabled=false'
)
packages=(
    libwebkit2gtk-4.0-37:amd64 libjavascriptcoregtk-4.0-18:amd64
    libicu72:amd64 libavif15:amd64 libdav1d6:amd64 librav1e0:amd64
    libsvtav1enc1:amd64
    libssl1.1:amd64 libtiff5:amd64 libwebp6:amd64
)
# Trixie's renamed native package still supplies the genuine soup 2.4 ABI.
# Prefer it to avoid overriding a host library with an older implementation.
soup_status=$(dpkg-query -W -f='${db:Status-Status}' libsoup-2.4-1:amd64 2>/dev/null || true)
soup_version=$(dpkg-query -W -f='${Version}' libsoup-2.4-1:amd64 2>/dev/null || true)
if [[ $soup_status == installed ]] && dpkg --compare-versions "$soup_version" ge 2.74.3; then
    printf 'Native libsoup-2.4-1 %s supplies libsoup-2.4.so.1\n' "$soup_version" > "$work/host-compat.txt"
else
    packages+=(libsoup2.4-1:amd64 libsoup2.4-common)
fi
apt-get "${opts[@]}" update
apt-cache "${opts[@]}" policy "${packages[@]}" > "$work/candidates.txt"
# APT derives these exact filenames, sizes and SHA256 values from the signed
# indexes above. No package is reused based on its filename alone.
apt-get "${opts[@]}" --print-uris download "${packages[@]}" > "$work/download-plan.txt.new"
mv "$work/download-plan.txt.new" "$work/download-plan.txt"
python3 "$base/scripts/helpers/compat-download-plan.py" prepare "$work"
mapfile -t missing < "$work/missing-packages.txt"
if (( ${#missing[@]} )); then
    (cd "$work/debs"; apt-get "${opts[@]}" download "${missing[@]}")
fi
python3 "$base/scripts/helpers/compat-download-plan.py" verify "$work"
cd "$work/debs"
for package in ./*.deb; do
    printf '\nFILE: %s\n' "$package"
    dpkg-deb -f "$package" Package Version Architecture Depends
done > ../package-metadata.txt
echo "Downloaded to $work/debs. Nothing installed. Continue with the manual's compatibility gate."
