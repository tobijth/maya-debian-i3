#!/bin/bash
# Native Debian installation derived from ../docs/INSTALL-MAYA.md.
# Run as your desktop user in an X11 terminal, WITHOUT sudo on this script.
set -Eeuo pipefail
umask 077
base=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd "$base"
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
unset LD_LIBRARY_PATH LD_PRELOAD PYTHONHOME PYTHONPATH QT_PLUGIN_PATH QT_QPA_PLATFORM_PLUGIN_PATH
die() { printf '\nSTOP: %s\n' "$*" >&2; exit 1; }
[[ $EUID != 0 ]] || die 'Als normaler Desktop-Benutzer ohne sudo starten.'
[[ $base =~ ^/[a-zA-Z0-9_./-]+$ ]] || die 'Installationspfad: nur ASCII-Buchstaben, Ziffern, /, _, . und - verwenden (Vendor-Skripte und Desktop-Eintraege).'
[[ ${XDG_SESSION_TYPE:-} == x11 && -n ${DISPLAY:-} ]] || die 'Ein Terminal in der echten X11-Desktopsitzung verwenden.'
source /etc/os-release
[[ $ID == debian && $VERSION_ID == 13 && $(uname -m) == x86_64 ]] || die 'Dieser Ablauf gilt nur fuer Debian 13 x86_64.'
mkdir -p logs backups state/installer user projects cache/tmp install/usr
exec 9>state/installer/lock
flock -n 9 || die 'Ein Installationslauf ist bereits aktiv.'
run=$(date +%Y%m%d-%H%M%S)
log="$base/logs/install-$run.txt"
exec > >(tee -a "$log") 2>&1
rollback_recorded=0
failed() {
    local line=$1 status=$2
    trap - ERR
    printf '\nAbbruch in Zeile %s (Status %s). Protokoll: %s\n' "$line" "$status" "$log" >&2
    exit "$status"
}
finished() {
    local status=$?
    trap - ERR EXIT
    if (( rollback_recorded )); then
        if ! sudo /usr/bin/python3 scripts/rollback-maya.py --record seal; then
            printf 'Rollback-Nachzustand unvollstaendig; docs/ROLLBACK.md lesen.\n' >&2
            (( status != 0 )) || status=1
        fi
    fi
    exit "$status"
}
trap 'failed "$LINENO" "$?"' ERR
trap finished EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
printf 'Maya 2027.2: native Installation auf Debian 13. Protokoll: %s\n' "$log"
[[ -z $(find state/installer -maxdepth 1 -name '*.pending' -print -quit) ]] || die 'Ein vorheriger Systemschritt blieb unvollstaendig. Die .pending-Datei und das Protokoll zuerst untersuchen; nicht blind erneut installieren.'
# This deliberately fails immediately inside the restricted agent environment.
sudo -v
systemctl --no-pager list-unit-files > "logs/system-units-$run.txt"
timedatectl status
[[ $(df --output=avail -k . | tail -n 1) -ge 31457280 ]] || die 'Mindestens 30 GiB freien Arbeitsbereich bereitstellen.'
[[ ,$(findmnt -n -o OPTIONS -T .), != *,noexec,* ]] || die 'Der Installationsordner liegt auf einem noexec-Dateisystem.'
bash scripts/preflight.sh > "logs/preflight-host-$run.txt" 2>&1
dpkg-query -W > "backups/dpkg-before-$run.txt"
sudo /usr/bin/python3 scripts/rollback-maya.py --record capture --home "$HOME" --uid "$UID" --config-home "${XDG_CONFIG_HOME:-$HOME/.config}"
rollback_recorded=1
if [[ ! -f state/installer/fresh.checked ]]; then
    for path in /usr/autodesk /opt/Autodesk /var/opt/Autodesk /var/lib/Autodesk/CER \
        /etc/rpm/macros.maya-native /etc/ld.so.conf.d/autodesk-compat-debian13.conf; do
        [[ ! -e $path && ! -L $path ]] || die "Bestehende Installation/Konfiguration zuerst inventarisieren: $path"
    done
    for path in "$HOME/maya" "$HOME/.autodesk" "$HOME/Autodesk"; do
        if [[ -e $path || -L $path ]]; then ls -ld "$path"; fi
    done > "backups/user-paths-$run.txt"
    for path in "$HOME/.config" "$HOME/.cache" "$HOME/.local/share"; do
        find "$path" -maxdepth 1 -iname '*autodesk*' -printf '%M %u %g %p\n' 2>/dev/null || true
    done >> "backups/user-paths-$run.txt"
    # Vendor postinstall replaces these links. Save them before any changes.
    mkdir -p "backups/integration-$run"
    for path in /usr/local/bin/maya /usr/local/bin/Render /usr/local/bin/fcheck /usr/local/bin/imgcvt \
        /usr/share/applications/Autodesk-Maya2027.desktop \
        /usr/share/desktop-directories/Autodesk-Maya2027.directory \
        /usr/share/icons/hicolor/48x48/apps/Maya2027.png; do
        if [[ -e $path || -L $path ]]; then
            sudo cp -a --parents "$path" "backups/integration-$run/"
        else
            printf '%s\n' "$path" >> "backups/integration-$run/previously-absent.txt"
        fi
    done
    touch state/installer/fresh.checked
fi
[[ -f media/2027.2/.verified-extraction ]] || die 'Das Originalmedium muss zuerst geprueft und vollstaendig entpackt werden (docs/INSTALL-MAYA.md, section 1).'
sha256sum -c media/2027.2/core-packages.sha256

packages=(python3 gnupg rpm rpm2cpio cpio binutils unzip desktop-file-utils xdg-utils xauth x11-utils
    mesa-utils ca-certificates uuid-runtime libsecret-1-0 gnome-keyring libgtk-3-0t64
    libgtk2.0-0t64 libnss3 libasound2t64 libgl1 libglu1-mesa libopengl0 libx11-xcb1
    libxmu6 libxpm4 libxtst6 libxi6 libxrender1 libxrandr2 libxinerama1 libxcursor1
    libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1
    libxcb-render-util0 libxcb-xinerama0 libxcb-xkb1 libatomic1 libattr1 libcurl4t64
    libpcre2-16-0 libpcre2-32-0 libpq5 libaudiofile1 libaom3 libgav1-1 libyuv0
    libjbig0 libdeflate0 libharfbuzz-icu0 libenchant-2-2 libflite1 libhyphen0
    libmanette-0.2-0 libsoup-2.4-1 bubblewrap glib-networking gstreamer1.0-plugins-base
    gstreamer1.0-plugins-good xfonts-75dpi xfonts-100dpi fonts-liberation)
if [[ ! -f state/installer/dependencies.done ]]; then
    sudo apt-get update
    LC_ALL=C apt-get -s --no-remove --no-upgrade install "${packages[@]}" > "logs/apt-plan-$run.txt"
    cat "logs/apt-plan-$run.txt"
    ! grep -Eq '^Remv |will be DOWNGRADED' "logs/apt-plan-$run.txt" || die 'APT wuerde Pakete entfernen/herabstufen.'
    sudo /usr/bin/python3 scripts/rollback-maya.py --record guard-apt --apt-plan "logs/apt-plan-$run.txt" --apt-requested "${packages[@]}"
    sudo apt-get --no-remove --no-upgrade -o APT::Get::allow-Downgrades=false -y install "${packages[@]}"
    touch state/installer/dependencies.done
fi
glxinfo -B > "logs/glxinfo-$run.txt"
cat "logs/glxinfo-$run.txt"
grep -q 'direct rendering: Yes' "logs/glxinfo-$run.txt" || die 'Keine direkte OpenGL-Beschleunigung.'
! grep -Eqi 'llvmpipe|softpipe|software rasterizer' "logs/glxinfo-$run.txt" || die 'OpenGL verwendet Software-Rendering.'
busctl --user list > "logs/user-bus-$run.txt"
grep -q org.freedesktop.secrets "logs/user-bus-$run.txt" || die 'Secret Service fehlt in der Desktopsitzung. Schluesselbund zuerst normal starten/entsperren.'

if [[ ! -f state/installer/compat.done ]]; then
    if [[ ! -f compat-download/debs/SHA256SUMS ]]; then bash scripts/helpers/fetch-compat-debs.sh; fi
    python3 scripts/helpers/compat-download-plan.py check compat-download
    if [[ -e compat-stage ]]; then
        cmp compat-download/debs/SHA256SUMS compat-stage/.download-checksums || die 'compat-stage gehoert nicht zum vollstaendig entpackten Downloadsatz; vorherigen Lauf pruefen.'
    else
        mkdir compat-stage
        for deb in compat-download/debs/*.deb; do dpkg-deb -x "$deb" compat-stage; done
        cp compat-download/debs/SHA256SUMS compat-stage/.download-checksums
    fi
    python3 scripts/helpers/check-compat-runtime.py | tee "logs/compat-check-$run.txt"
    touch state/installer/compat.pending
    sudo test ! -e /opt/Autodesk/compat-debian13
    sudo test ! -L /opt/Autodesk/compat-debian13
    sudo install -d -m 0755 /opt/Autodesk/compat-debian13
    sudo cp -a compat-stage/. /opt/Autodesk/compat-debian13/
    sudo chown -R root:root /opt/Autodesk/compat-debian13
    sudo chmod -R a+rX,go-w /opt/Autodesk/compat-debian13
    for libdir in usr/lib/x86_64-linux-gnu lib/x86_64-linux-gnu; do
        if [[ -d /opt/Autodesk/compat-debian13/$libdir ]]; then printf '/opt/Autodesk/compat-debian13/%s\n' "$libdir"; fi
    done > state/installer/autodesk-compat-debian13.conf
    sudo install -m 0644 state/installer/autodesk-compat-debian13.conf /etc/ld.so.conf.d/autodesk-compat-debian13.conf
    helperdir=/usr/lib/x86_64-linux-gnu/webkit2gtk-4.0
    [[ ! -e $helperdir && ! -L $helperdir ]] || die "Vorhandener WebKit-Helferpfad: $helperdir"
    sudo ln -sT /opt/Autodesk/compat-debian13/usr/lib/x86_64-linux-gnu/webkit2gtk-4.0 "$helperdir"
    sudo ldconfig
    mv state/installer/compat.pending state/installer/compat.done
fi

check_loader() {
    local file=$1 output
    [[ -f $file ]] || die "Datei fehlt: $file"
    output=$(ldd "$file" 2>&1) || { printf '%s\n' "$output"; die "Loader-Fehler: $file"; }
    printf '\nldd %s\n%s\n' "$file" "$output" >> "logs/loader-$run.txt"
    if grep -Eq 'not found|version .* not found' <<< "$output"; then
        printf '%s\n' "$output"
        die "Bibliothek/Symbol fehlt: $file (Details: logs/loader-$run.txt)"
    fi
    printf 'OK: Bibliotheken fuer %s\n' "$file"
}
public_install_file() {
    # These are vendor-generated installation metadata, never credentials or
    # user authentication state. Repair the old installer's inherited umask 077.
    local file=$1
    [[ -f $file && ! -L $file ]] || die "Erwartete Installationsmetadaten fehlen: $file"
    if [[ ! -r $file ]]; then
        sudo stat -c '%a %n' "$file" >> "backups/public-metadata-modes-$run.txt"
        sudo chmod 0644 "$file"
    fi
    [[ -r $file ]] || die "Installationsmetadaten nicht lesbar: $file"
}
if [[ ! -f state/installer/rpm-db.done ]]; then
    # Debian's rpm package creates an empty root-owned /var/lib/rpm. A query
    # tries to initialize it when rpmdb.sqlite is absent and fails as a user.
    # Initialize only a genuinely empty shared directory before user queries.
    user_db=$(rpm --eval '%{_dbpath}')
    root_db=$(sudo rpm --eval '%{_dbpath}')
    printf 'RPM-Datenbankpfade: Benutzer=%s Administrator=%s\n' "$user_db" "$root_db"
    # Even queries may initialize an absent database. Guard the whole step
    # before its first possible write, including initialization and macros.
    printf 'user_db=%s\nroot_db=%s\n' "$user_db" "$root_db" > "backups/rpm-db-paths-$run.txt"
    touch state/installer/rpm-db.pending
    if [[ $user_db == /var/lib/rpm && $root_db == /var/lib/rpm && ! -e /var/lib/rpm/rpmdb.sqlite ]]; then
        sudo bash scripts/helpers/init-empty-rpm-database.sh /var/lib/rpm
    fi
    rpm -qa > "backups/rpm-user-before-$run.txt"
    sudo rpm -qa > "backups/rpm-root-before-$run.txt"
    [[ ! -s backups/rpm-user-before-$run.txt && ! -s backups/rpm-root-before-$run.txt ]] || die 'Bestehende RPM-Datenbanken zuerst pruefen.'
    [[ ! -e /etc/rpm/macros.maya-native ]] || die 'RPM-Makrodatei existiert bereits.'
    # Refuse to hide a third existing database by changing the macro.
    if [[ -d /var/lib/rpm ]]; then
        sudo rpm --dbpath /var/lib/rpm -qa > "backups/rpm-system-before-$run.txt"
        [[ ! -s backups/rpm-system-before-$run.txt ]] || die 'Bestehende systemweite RPM-Datenbank zuerst pruefen.'
    fi
    printf '%%_dbpath /var/lib/rpm\n' > state/installer/macros.maya-native
    sudo install -d -m 0755 /etc/rpm /var/lib/rpm
    sudo install -m 0644 state/installer/macros.maya-native /etc/rpm/macros.maya-native
    sudo rpm --initdb
    sudo chmod a+rX /var/lib/rpm
    sudo find /var/lib/rpm -maxdepth 1 -type f -exec chmod a+r '{}' +
    [[ $(rpm --eval '%{_dbpath}') == /var/lib/rpm && $(sudo rpm --eval '%{_dbpath}') == /var/lib/rpm ]] || die 'RPM-Datenbankpfad stimmt nicht ueberein.'
    rpm -qa
    mv state/installer/rpm-db.pending state/installer/rpm-db.done
fi

# The licensing media includes Autodesk's signing key. Verify its full
# fingerprint before importing it; never suppress signature verification.
if [[ ! -f state/installer/autodesk-signing-key.done ]]; then
    key=media/2027.2/Packages/Licensing/AdskLicensing_key.asc
    mkdir -p cache/rpm-key-inspection
    gpg --batch --no-options --homedir "$base/cache/rpm-key-inspection" --with-colons --show-keys "$key" \
        > "logs/autodesk-signing-key-$run.txt"
    fingerprint=$(awk -F: '$1 == "fpr" { print $10; exit }' "logs/autodesk-signing-key-$run.txt")
    [[ $fingerprint == 74EFCA6B48B7E2E696563AFC8F0DA98C1D9DB31F ]] || die 'Unerwarteter Autodesk-Schluessel im Installationsmedium.'
    sudo rpmkeys --import "$key"
    sudo find /var/lib/rpm -maxdepth 1 -type f -exec chmod a+r '{}' +
    rpmkeys --checksig --verbose media/2027.2/Packages/Licensing/adsklicensing16.0.3.14414-0-0.x86_64.rpm
    touch state/installer/autodesk-signing-key.done
fi

install_rpm() {
    local key=$1 package=$2 prefix=${3:-} script tag name
    name=$(rpm -qp --qf '%{NAME}' "$package")
    if [[ -f state/installer/$key.done ]]; then rpm -q "$name"; return; fi
    ! rpm -q "$name" >/dev/null 2>&1 || die "RPM $name ist bereits installiert; Zustand zuerst pruefen."
    mkdir -p "backups/rpm-$key"
    rpm -qp --scripts "$package" > "backups/rpm-$key/scriptlets.txt"
    rpm -qp --requires "$package" > "backups/rpm-$key/requires.txt"
    rpm -qpl "$package" > "backups/rpm-$key/files.txt"
    sha256sum "$package" > "backups/rpm-$key/package.sha256"
    for tag in PREIN POSTIN PREUN POSTUN; do
        script="backups/rpm-$key/$tag.sh"
        rpm -qp --qf "%{$tag}" "$package" > "$script"
        if [[ $(cat "$script") == '(none)' ]]; then : > "$script"; fi
        bash -n "$script"
    done
    sudo /usr/bin/python3 scripts/rollback-maya.py --record rpm --key "$key" --package "$package" --prefix "$prefix"
    touch "state/installer/$key.pending"
    if [[ -s backups/rpm-$key/PREIN.sh ]]; then
        sudo bash -c 'umask 022; exec bash "$@"' -- "backups/rpm-$key/PREIN.sh" 1
    fi
    if [[ -n $prefix ]]; then
        sudo rpm -ivh --nodeps --noscripts --prefix "$prefix" "$package"
    else
        sudo rpm -ivh --nodeps --noscripts "$package"
    fi
    if [[ $key == cer ]]; then check_loader /opt/Autodesk/AdskCER/service/cer_service; fi
    if [[ -s backups/rpm-$key/POSTIN.sh ]]; then
        if [[ -n $prefix ]]; then
            sudo env RPM_INSTALL_PREFIX="$prefix" bash -c 'umask 022; exec bash "$@"' -- "backups/rpm-$key/POSTIN.sh" 1
        elif [[ $key == cer ]]; then
            sudo bash -c 'umask 022; exec bash "$@"' -- "backups/rpm-$key/POSTIN.sh" 1 | tee "logs/cer-restore-$run.txt"
            grep -q 'RESTORE_CODE: 0$' "logs/cer-restore-$run.txt" || die 'CER-Restore ist fehlgeschlagen.'
        else
            sudo bash -c 'umask 022; exec bash "$@"' -- "backups/rpm-$key/POSTIN.sh" 1
        fi
    fi
    # Keep the shared database readable for Identity Manager's user queries.
    sudo find /var/lib/rpm -maxdepth 1 -type f -exec chmod a+r '{}' +
    mv "state/installer/$key.pending" "state/installer/$key.done"
}
install_rpm identity media/2027.2/Packages/AdskIdentityManager/adskidentitymanager1.18.1.2-1.x86_64.rpm
idm=/opt/Autodesk/AdskIdentityManager/Current
[[ $(readlink -f "$idm") == /opt/Autodesk/AdskIdentityManager/1.18.1.2 ]] || die 'Unerwartete Identity-Manager-Version.'
public_install_file /opt/Autodesk/AdskIdentityManager/AdskIdentityManagerInstallList.ini
public_install_file /opt/Autodesk/AdskIdentityManager/1.18.1.2/AdskIdentityManagerInstall.config
test -s /opt/Autodesk/AdskIdentityManager/AdskIdentityManagerInstallList.ini
test -s "$idm/AdskIdentityManagerInstall.config"
python3 - "$idm/AdskIdentityManagerInstall.config" <<'PY'
import json, sys, uuid
with open(sys.argv[1]) as stream:
    config = json.load(stream)
uuid.UUID(config['ssoServer']['guid'])
print('OK: Identity-Manager-Installationskonfiguration lesbar und gueltig.')
PY
check_loader "$idm/AdskIdentityManager"
check_loader "$idm/libIdServicesCore.so"
install_rpm licensing media/2027.2/Packages/Licensing/adsklicensing16.0.3.14414-0-0.x86_64.rpm
lic=/opt/Autodesk/AdskLicensing/Current
[[ $(readlink -f "$lic") == /opt/Autodesk/AdskLicensing/16.0.3.14414 ]] || die 'Unerwartete Licensing-Version.'
getent passwd adsklic
getent group adsklic
agent="$lic/AdskLicensingAgent"
# The executable's $ORIGIN/lib RPATH supplies these libraries to dlopen'ed
# plugins. Checking a plugin directly loses that executable search context.
# Reproduce it for these diagnostics only, including Autodesk's matching Qt.
for file in AdskLicensingAgent plugins/libbrowser_native.so.5.30.2.352 platforms/libqxcb.so; do
    LD_LIBRARY_PATH="$agent/lib" check_loader "$agent/$file"
done
sudo systemctl daemon-reload
sudo systemctl enable --now adsklicensing.service
systemctl --quiet is-active adsklicensing.service
helper="$lic/helper/AdskLicensingInstHelper"
"$helper" list

if [[ ! -f state/installer/adp.done ]]; then
    [[ ! -e /opt/Autodesk/AdpDesktopSDK && ! -L /opt/Autodesk/AdpDesktopSDK ]] || die 'ADP-Verzeichnis existiert bereits.'
    touch state/installer/adp.pending
    sudo install -d -m 0755 /opt/Autodesk/AdpDesktopSDK/6.4.14.18
    sudo unzip -q media/2027.2/Packages/AdpSdk/adp-desktop-sdk.zip -d /opt/Autodesk/AdpDesktopSDK/6.4.14.18
    sudo chown -R root:root /opt/Autodesk/AdpDesktopSDK
    sudo chmod -R a+rX,go-w /opt/Autodesk/AdpDesktopSDK
    sudo ln -sT 6.4.14.18 /opt/Autodesk/AdpDesktopSDK/bin
    mv state/installer/adp.pending state/installer/adp.done
fi
for file in AdpSDKCore.so AdpSDKUI.so ADPClientService; do check_loader "/opt/Autodesk/AdpDesktopSDK/bin/$file"; done
install_rpm cer media/2027.2/Packages/CER/autodesk.cer.service-7.2.5.982-1.x86_64.rpm
check_loader /opt/Autodesk/AdskCER/service/cer_service
/opt/Autodesk/AdskCER/service/cer_service status
install_rpm maya media/2027.2/Packages/Maya2027_64-2027.2-1906.x86_64.rpm "$base/install/usr"
public_install_file /opt/Autodesk/Synergy/Maya2027.2027.1.64.syncfg
app="$base/install/usr/autodesk/maya2027"
for file in "$app/bin/maya.bin" "$app/lib/libOGSMayaBridge.so" "$app/plugins/platforms/libqxcb.so"; do
    LD_LIBRARY_PATH="$app/lib:$app/lib/el9" check_loader "$file"
done
"$helper" list > "logs/registered-products-$run.json"
if ! grep -q 657S1 "logs/registered-products-$run.json"; then
    sudo "$helper" register --prod_key 657S1 --prod_ver 2027.0.0.F \
        --config_file /var/opt/Autodesk/Adlm/Maya2027/MayaConfig.pit --eula_locale US
    "$helper" list > "logs/registered-products-$run.json"
fi
python3 - "logs/registered-products-$run.json" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
def matches(x):
    if isinstance(x, dict):
        if '657S1' in x.values() and '2027.0.0.F' in x.values(): return True
        return any(matches(v) for v in x.values())
    return isinstance(x, list) and any(matches(v) for v in x)
if not matches(data): raise SystemExit('Exakte Maya-2027-Produktregistrierung fehlt.')
PY
if [[ ! -e /etc/pki/tls/certs/ca-bundle.crt && ! -L /etc/pki/tls/certs/ca-bundle.crt ]]; then
    test -s /etc/ssl/certs/ca-certificates.crt
    sudo install -d -m 0755 /etc/pki/tls/certs
    sudo ln -sT /etc/ssl/certs/ca-certificates.crt /etc/pki/tls/certs/ca-bundle.crt
    touch state/installer/ca-link.created
fi
# IDM 1.18.1.2 rejects --register (confirmed in IdServices.log). Its embedded
# desktop template instead uses a plain executable followed by %u. The shipped
# entry below reproduces that template, supporting both vendor URI schemes.
# Never add a fake WebKit package check proactively; see manual section 7.2.
mkdir -p "$HOME/.local/share/applications" state/desktop
handler="$HOME/.local/share/applications/com.autodesk.AdskIdentityManager.desktop"
authoritative_handler="$base/state/desktop/com.autodesk.AdskIdentityManager.desktop"
install -m 0644 templates/autodesk-identity.desktop "$authoritative_handler"
desktop-file-validate "$authoritative_handler"
if [[ ! -e $handler && ! -L $handler ]]; then
    ln -sT "$authoritative_handler" "$handler"
fi
test -s "$handler"
desktop-file-validate "$handler"
for scheme in adskidmgr adsk.idmgr; do
    if [[ ! -f backups/uri-handler-$scheme.before ]]; then
        xdg-mime query default "x-scheme-handler/$scheme" > "backups/uri-handler-$scheme.before"
    fi
    python3 scripts/helpers/set-identity-uri.py "$scheme"
    [[ $(xdg-mime query default "x-scheme-handler/$scheme") == com.autodesk.AdskIdentityManager.desktop ]] || die "URI-Zuordnung fehlgeschlagen: $scheme"
done
chmod u+x scripts/maya-2027
desktop="$base/state/desktop/maya-2027.desktop"
cat > "$desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Autodesk Maya 2027.2
Comment=3D-Modellierung, Animation und Rendering
Exec=$base/scripts/maya-2027 %F
TryExec=$base/scripts/maya-2027
Icon=$app/desktop/Maya.png
Terminal=false
Categories=Graphics;3DGraphics;
EOF
desktop-file-validate "$desktop"
menu="$HOME/.local/share/applications/maya-2027.desktop"
if [[ -e $menu || -L $menu ]]; then
    [[ $(readlink -f "$menu") == "$desktop" ]] || die "Vorhandener Menueeintrag: $menu"
else
    ln -sT "$desktop" "$menu"
fi
update-desktop-database "$HOME/.local/share/applications"
mkdir -p compat-local/lib
audio=/usr/lib/x86_64-linux-gnu/libaudiofile.so.1
[[ -f $audio ]] || die 'Debian-Audiofile-Laufzeit fehlt trotz libaudiofile1.'
if [[ ! -e compat-local/lib/libaudiofile.so && ! -L compat-local/lib/libaudiofile.so ]]; then
    ln -s "$audio" compat-local/lib/libaudiofile.so
fi
[[ $(readlink -f compat-local/lib/libaudiofile.so) == "$(readlink -f "$audio")" ]] || die 'Vorhandenen lokalen Audiofile-Alias zuerst pruefen.'
python3 scripts/install-maya-ui-fixes.py --app-dir "$base/user" --version 2027
LD_LIBRARY_PATH="$app/lib:$app/lib/el9" "$app/bin/mayapy" -c \
    'import ssl, ctypes, sys, PySide6; print(sys.version); print(ssl.OPENSSL_VERSION); print(PySide6.__version__)'
sudo apt-get check
rpm -qa > "logs/rpm-after-$run.txt"
systemctl --quiet is-active adsklicensing.service
touch state/installer/core-validated
printf '\nSysteminstallation und technische Pruefungen abgeschlossen.\n'
printf 'Jetzt starten: %s/scripts/maya-2027\n' "$base"
printf 'Im Browser selbst mit Autodesk anmelden. Danach die Abnahmepruefungen der Installationsanleitung durchfuehren.\n'
