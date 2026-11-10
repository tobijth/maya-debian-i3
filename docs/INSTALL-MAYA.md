# Maya 2027.2 installation notes: Debian 13

This records one working native installation. The scripts were adapted for other usernames and paths, but the generalized installer has not completed a full installation on a second machine. Downloads are tied to the inspected builds.

For an existing installation, start with the [known issues](#known-installation-issues) or the [individual UI fixes](UI-FIXES.md). Read [Meat Proxy's notes](../README.md#meat-proxys-notes) for authorship and the absence of support, planned updates, or pull request maintenance.

## Requirements and scope

- Debian 13 x86_64, a real X11 desktop session, and a normal user with sudo access.
- Working accelerated OpenGL (`glxinfo -B`), a correct system clock, and a desktop keyring/Secret Service.
- At least 30 GiB of free workspace. The repository must be on an executable filesystem. Its absolute path may contain only ASCII letters, digits, `/`, `_`, `.`, and `-`; this restriction is checked before system changes for compatibility with vendor scripts and desktop launchers.
- Your own Maya 2027.2 Linux installation archive from Autodesk Account and a valid Autodesk entitlement.
- A fresh installation. The installer stops at existing Autodesk system directories or an unresolved installation state. It does not migrate other Autodesk products.

Inspected builds: Maya `2027.2-1906`, Identity Manager `1.18.1.2`, Licensing `16.0.3.14414`, ADP Desktop SDK `6.4.14.18`, and CER `7.2.5.982`. Arnold/MtoA `5.6.2` was added separately in the original setup. This core installer does not automatically install Arnold, Bifrost, USD, LookdevX, or Substance.

## 1. Prepare the media

Clone the repository to its permanent installation location. Generated desktop entries, the RPM prefix, and the startup file will contain absolute paths.

```bash
cd /path/to/repo
bash scripts/preflight.sh
bash scripts/prepare-maya-media.sh /path/to/Autodesk_Maya_2027_2_Update_Linux_64bit.tgz
```

The preparation script accepts only the inspected archive with this SHA-256:

```text
7795762cd587ad0e8428be3bd1ed101bf92bdf799569299a7556cfbaaf4405c4
```

This is a locally measured integrity fingerprint, not an Autodesk-signed download confirmation. Obtain the archive from your Autodesk source. Other builds need a new review. The helper extracts only into an empty `media/2027.2`, checks the five core packages against `metadata/core-packages.sha256`, then writes the verification marker expected by the installer.

## 2. Run the installer

Read the script before running it: it installs system packages and Autodesk services and changes system configuration.

New runs record private before-state backups for [rollback](ROLLBACK.md). Keep `state` and `backups` at this clone's original location. An older run without a rollback record is refused instead of being given an invented baseline. The installer also refuses to upgrade existing Debian packages so dependency removal can be selective.

```bash
bash scripts/install-maya-native.sh
```

Start the script as your normal desktop user, without `sudo` in front of it. It uses sudo for system changes and performs these steps:

1. Simulate and install Debian dependencies; check OpenGL and Secret Service.
2. Download genuine older ABI libraries from signed Debian package indexes and verify SHA-256 hashes.
3. Check the extracted compatibility runtime for loader failures, matching WebKit/JavaScriptCore versions, and SONAME collisions with the host.
4. Install a root-owned runtime under `/opt/Autodesk/compat-debian13` and configure its loader and WebKit paths.
5. Set up a shared RPM database path, check the Autodesk signing-key fingerprint, archive vendor scriptlets, and run them explicitly with Bash. The global `/bin/sh` is unchanged.
6. Install Identity Manager, Licensing, ADP, CER, and Maya; check loading and enable the licensing service. Product registration uses `657S1`, version `2027.0.0.F`.
7. Configure the Debian certificate path, URI handlers for `adskidmgr`/`adsk.idmgr`, and desktop launchers.
8. Add the local audio library alias and automatic Hotbox fix; check Python, SSL, and ctypes.

Vendor RPM scriptlets run with fresh-install arguments. This is not an upgrade installer. Other builds require a review of their versions and system paths.

### Compatibility packages

The runtime includes genuine OpenSSL 1.1, TIFF 5, and WebKitGTK API 4.0 with matching JavaScriptCore, ICU, and codec dependencies. Modern libraries are not renamed to old SONAMEs. The native Soup 2.4 runtime is preferred.

Download sources are kept in `compat-download/sources.list`; system APT sources are unchanged. Bullseye security builds that returned HTTP 404 from the active mirror are taken from the official Debian security archive. Archive availability does not mean ongoing security maintenance. If signature or validity checks fail, investigate the repository state rather than disabling authentication.

Before extracting any compatibility packages, the installer rechecks the exact file selection, sizes, hashes, and `SHA256SUMS` against the saved authenticated `download-plan.txt`. Unexpected `.deb` files and symlinks stop installation, even if all files named in the checksum manifest would pass `sha256sum -c`. For a read-only check:

```bash
python3 scripts/helpers/compat-download-plan.py check compat-download
```

Keep the plan with the downloads. If it is missing, rerun the download helper to obtain a new plan from authenticated indexes; valid downloads can be reused. A failed package reverification removes the previous success manifest.

### Paths

| Content | Location |
|---|---|
| Maya application | `<repo>/install/usr/autodesk/maya2027` |
| Maya user data (`MAYA_APP_DIR`) | `<repo>/user` |
| Maya 2027 startup file | `<repo>/user/2027/scripts/userSetup.py` |
| Projects / temporary files | `<repo>/projects`, `<repo>/cache/tmp` |
| Logs / backups / resume state | `<repo>/logs`, `<repo>/backups`, `<repo>/state` |
| Autodesk services | `/opt/Autodesk`, with state including `/var/opt/Autodesk` |
| Compatibility runtime | `/opt/Autodesk/compat-debian13` |

System services and their state stay in system locations. The launcher preserves HOME, the D-Bus address, and the XDG runtime directory. [The rollback command](ROLLBACK.md#full-installation) handles recorded RPMs, services, links and configuration together, with separate options for dependencies and local output cleanup.

## 3. Launch and check

```bash
./scripts/maya-2027
```

Sign in to Autodesk yourself in the browser. In Maya, check:

- An empty scene, a cube, navigation, transforms, and saving/reopening.
- Detaching, moving, and docking the UV Editor and Graph Editor.
- Holding Space in a viewport: the Hotbox should be visible and usable, including on another monitor.
- Quitting and restarting Maya: the Hotbox fix should work without a Script Editor command.
- `cmds.internalVar(userAppDir=True)` should point to `<repo>/user`.
- WAV/playblast where needed, and an Arnold CPU render after installing Arnold separately.

The i3 panel helper requires the system package `python3-i3ipc`. The launcher enables it in an i3 session; a reported helper failure does not prevent Maya from starting. The Hotbox fix uses Maya's bundled PySide6 and a GUI idle callback without a global event filter. Startup activation and the Hotbox after a complete GUI restart were confirmed on the original desktop.

## Known installation issues

These workarounds come from the original installation. Package and integration issues may apply more broadly, but the exact builds and local state still matter. The full installer combines them; its internal helpers are not a general repair command for an existing system.

### APT downloads return 404

The inspected older OpenSSL/TIFF security builds were no longer available at the active mirror. [The download helper](../scripts/helpers/fetch-compat-debs.sh) uses the official security archive for those builds. [The download-plan helper](../scripts/helpers/compat-download-plan.py) checks existing files against SHA-256 values from authenticated APT indexes before reusing them. Review the package sources and versions for your own setup.

### RPM database cannot be opened

The original setup needed one shared RPM database path and a properly initialized empty SQLite database. [The initialization helper](../scripts/helpers/init-empty-rpm-database.sh) refuses nonempty or symlinked targets. It is called by the installer only under its empty-database check; do not replace an existing database to repair a permissions problem.

The helper checks every path component for symlinks, including paths supplied with trailing separators. Dot components (`.` and `..`) are refused; use an absolute path without them.

### Interrupted RPM database setup

`state/installer/rpm-db.pending` is written before initialization or any RPM query that could create a database. It becomes `rpm-db.done` only after macro installation, database initialization, permissions, and user/root queries succeed. A remaining `.pending` file stops the next installer run.

Before resuming, inspect the failed command in `logs/install-*.txt` and the recorded original paths in `backups/rpm-db-paths-*.txt`. Check all of the following:

- Both `rpm --eval '%{_dbpath}'` and `sudo rpm --eval '%{_dbpath}'` resolve to `/var/lib/rpm`.
- `/etc/rpm/macros.maya-native` is a regular root-owned file with mode `0644` and contains exactly `%_dbpath /var/lib/rpm` followed by a newline.
- `/var/lib/rpm` is a real root-owned directory with mode `0755`; its SQLite database files are readable by the desktop user.
- `rpm -qa` and `sudo rpm -qa` both succeed. At this early fresh-install stage the database must be empty; any package records require investigation against the before-install inventories.

If these checks establish that the entire step completed, rename `state/installer/rpm-db.pending` to `state/installer/rpm-db.done` and rerun the installer. Otherwise finish diagnosing the partial step first. Do not delete, rebuild, or replace an existing database, overwrite unexplained macros, or remove the pending marker just to bypass the stop.

### Licensing plugin reports missing libraries

Check the plugin in the licensing agent's library context. An isolated `ldd` call can lose the agent's RPATH context and report misleading missing dependencies. The [installer](../scripts/install-maya-native.sh) records loader checks for the inspected layout; compare those paths with your installed build.

### Identity Manager registration fails

The inspected Identity Manager does not support that option. The [desktop-entry template](../templates/autodesk-identity.desktop) invokes the shipped executable with `%u` for URI handling. The installer registers the `adskidmgr` and `adsk.idmgr` schemes.

### Installation metadata is unreadable

Some vendor scriptlets created unreadable public installation metadata. The installer runs vendor processes with umask `022` and corrects only identified public metadata. This is not a reason to change permissions across private Autodesk account or license directories.

### libaudiofile.so is missing

The installer creates a local alias to Debian's genuine `libaudiofile.so.1`. The [launcher](../scripts/maya-2027) adds that local directory to Maya's library search path. This does not substitute an unrelated modern ABI for an older library.

For an invisible Hotbox or tiled panels, use [UI-FIXES.md](UI-FIXES.md). Investigate unknown failures before rerunning installation. A `.pending` file marks an unfinished system step; do not delete it as a general repair attempt.

## Logs and limits

`logs/install-*.txt` records installation steps; `logs/loader-*.txt` contains detailed loader checks. Installation markers are in `state/installer`; vendor scriptlet backups are in `backups`.

Keep these files local. They may contain usernames, hostnames, absolute paths, package inventories, or system details. Review and redact any excerpt before sharing it. Keep Autodesk credentials, sign-in tokens, and license state out of exports.

The original machine used an AMD RX 480; Arnold GPU support was not configured. MtoA autoload does not confirm a separate Arnold batch license. Maya updates, other Qt versions, and other Debian releases require new checks. See [TESTING.md](TESTING.md) for verification details.

Sources: [Autodesk Maya dependencies](https://help.autodesk.com/cloudhelp/2026/ENU/Maya-Installlation/files/GUID-D2B5433C-E0D2-421B-9BD8-24FED217FD7F.htm), [Autodesk RPM installation](https://help.autodesk.com/cloudhelp/2025/ENU/Maya-Installlation/files/GUID-E7E054E1-0E32-4B3C-88F9-BF820EB45BE5.htm), [Maya path variables](https://help.autodesk.com/cloudhelp/2024/ENU/Maya-EnvVar/files/GUID-228CCA33-4AFE-4380-8C3D-18D23F7EAC72.htm).
