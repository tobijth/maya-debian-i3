#!/bin/bash
# Read-only checks; does not open the browser or print authentication files.
set -u
base=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
check() {
    printf '\n--- %s ---\n' "$*"
    "$@"
    local result=$?
    printf '[exit %s]\n' "$result"
    return 0
}
check cat /etc/os-release
check uname -a
check id
printf '\nSession: type=%s display=%s desktop=%s\n' "${XDG_SESSION_TYPE:-unset}" "${DISPLAY:-unset}" "${XDG_CURRENT_DESKTOP:-unset}"
check readlink /bin/sh
check df -h "$base" /tmp
check findmnt -T "$base"
check free -h
check xdg-settings get default-web-browser
check xdg-mime query default x-scheme-handler/adskidmgr
check systemctl --no-pager --full status adsklicensing.service
check timedatectl status
check glxinfo -B
check dpkg-query -W '-f=${binary:Package} ${db:Status-Status} ${Version}\n' libc6 libstdc++6 libssl3t64 libwebkit2gtk-4.1-0 libsecret-1-0 gnome-keyring rpm
check namei -l /opt/Autodesk/AdskLicensing/Current
check namei -l /opt/Autodesk/AdskIdentityManager/Current
check namei -l "$base/install/usr/autodesk/maya2027/bin/maya"
if command -v rpm >/dev/null; then
    check rpm -qa
fi
echo 'A failed check may mean a missing command or agent sandbox restriction; inspect its message.'
