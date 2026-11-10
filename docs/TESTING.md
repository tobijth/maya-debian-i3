# Verification and limits

These checks help anyone reusing the scripts assess the evidence. They do not imply ongoing testing or support. See [Meat Proxy's notes](../README.md#meat-proxys-notes).

## Repeatable repository checks

Requirements: Linux, Bash, Python 3.11 or newer, GNU coreutils, and the `rpm` command using the SQLite backend. Python's standard library is sufficient for all non-Qt tests. RPM tests operate only on temporary database directories. Missing RPM is a failed prerequisite, not a silently skipped check.

From the repository root, run syntax checks, regression tests, and export verification together:

```bash
bash scripts/check-repo.sh
```

The checker also works when called by absolute path from another directory. It runs locally and does not download packages, start Maya, or alter system configuration. These checks exercise the helpers; they do not perform a full installation on Debian.

## Isolated regression tests

To run just the tests while editing:

```bash
python3 -m unittest discover -s tests -v
```

The tests cover authenticated download reuse, rejection of unexpected packages and stale checksum manifests, RPM initialization in temporary directories, i3 panel selection, and preservation/removal of the generated startup block. Startup regressions include marker examples inside Python strings, UTF-8 BOM, declared source encodings, CRLF, and malformed markers. They do not perform a real system installation.

Installer safety tests also cover symlink path components and trailing separators, launcher path metacharacters, and failures during RPM database/macro setup. The RPM setup block is exercised with temporary system paths and stubbed privileged commands; no sudo call or system write is performed. Diagnostic startup is tested with a Qt stub to check creation of a private log directory on a fresh clone; actual GUI behavior still requires the Qt tests below.

Rollback tests exercise before/after restoration of files, modes, directory trees and broken symlinks; preservation of later edits, service data and nonempty projects; rejection of changed parents and corrupt backups; local download and standalone database cleanup; safe APT plans; and vendor callback/erase ordering with interrupted callback resumption. System commands and privilege changes in uninstall-sequence tests are stubbed. These tests do not run Autodesk callbacks or remove installed system software.

Qt regression tests are skipped without PySide6 and shiboken6. With a locally installed Maya runtime:

```bash
app="$PWD/install/usr/autodesk/maya2027"
QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH="$app/lib:$app/lib/el9" \
  "$app/bin/mayapy" -m unittest discover -s tests -p test_maya_hotbox_geometry.py -v
```

The Qt tests exercise the idle callback without a global event filter, removal of the fix, unchanged unrelated windows and flags, duplicate activation, and recalculated geometry for negative coordinates and changed monitor counts. They do not replace checks with real monitors and scaling factors.

## Observed on the original desktop

Maya startup, Hotbox geometry correction, and automatic activation after a complete GUI restart were confirmed in the original Maya 2027.2, Debian 13, X11, i3 desktop session. Additional offscreen checks used Maya's real PySide6 runtime.

The generalized native installer has not completed a full installation on a second system. Other Maya/Qt versions, other distributions, and mixed display scaling require their own checks. The [UI notes](UI-FIXES.md#laptops-and-external-monitors) include a monitor checklist for another machine.

## Export integrity

`EXPORT-SHA256SUMS` lists the shareable scripts, documentation, templates, metadata, and tests. From the repository root:

```bash
sha256sum -c EXPORT-SHA256SUMS
```

These locally generated hashes detect changes relative to this manifest. They are separate from the vendor-package hashes in `metadata/core-packages.sha256` and do not authenticate an Autodesk download.

After intentionally changing shareable source files, review the changes and regenerate the export manifest from the repository root in Bash:

```bash
files=(.gitignore LICENSE README.md
       docs/*.md metadata/*.sha256
       scripts/*.sh scripts/*.py scripts/maya-2027
       scripts/helpers/*.sh scripts/helpers/*.py scripts/diagnostics/*.py
       templates/*.py templates/*.desktop tests/test_*.py)
sha256sum "${files[@]}" > EXPORT-SHA256SUMS
bash scripts/check-repo.sh
```

Review the selected files before regeneration; these patterns select source directories, not runtime data. Add new source locations explicitly when needed. Do not regenerate the manifest to dismiss an unexplained mismatch in a downloaded copy.

## Keep local data private

Installation logs, backups, Maya user data, credentials, and runtime state are excluded by `.gitignore`. Keep them out of shared archives as well. Diagnostic excerpts can contain personal paths or machine details; redact those before sharing. A list of versions, the relevant symptom, and a minimal redacted error excerpt are usually more useful for adapting a fix than a full machine dump.
