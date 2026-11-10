# Repository review

This review covers the source and isolated tests. It does not certify a fresh Maya installation. The repository remains a set of reusable installation notes and workarounds with the maintenance limits stated in the [README](../README.md).

## What works well

- The symptom-based entry page separates individual UI fixes from a complete installation. Observations, hypotheses, and untested configurations are distinguished.
- Downloads use authenticated APT metadata and SHA-256 checks. Host-library collisions, unexpected platform versions, and existing Autodesk installations have explicit checks.
- UI changes are deliberately narrow. Startup edits have backups and removal support; the i3 helper respects manual tiling and excludes the main window.
- Temporary-directory tests exercise meaningful behavior without Autodesk media, credentials, or system installation. Private runtime directories are excluded from Git.

## Addressed in this review

- **Unchecked extra packages:** the installer previously verified only files listed in `SHA256SUMS`, then extracted every `*.deb`. It now verifies the exact set against the saved APT plan before extraction. Failed package reverification invalidates an old success manifest.
- **Startup content preservation:** marker matching previously treated marker examples inside multiline strings as editable blocks. Python tokenization now recognizes actual marker comments. Source encodings and UTF-8 BOM are also preserved. Regression tests reproduce these cases.
- **Declared installer tools:** Python and GnuPG are now explicit dependencies rather than assumptions about the desktop installation.
- **Repeatable checks:** one local offline command checks syntax, regression tests, and export integrity. The export manifest includes the checker and documentation. [Testing instructions](TESTING.md) explain prerequisites and hash regeneration.
- **RPM path protection:** initialization rejects symlinks in every path component, including trailing-slash bypasses, and rejects dot components before any writes.
- **Interrupted RPM setup:** a pending marker now covers database initialization, potentially mutating queries, and system macro installation. Failure tests exercise initialization, macro installation, and database initialization after the macro; [recovery notes](INSTALL-MAYA.md#interrupted-rpm-database-setup) describe the checks before resuming.
- **Fresh-clone diagnostics:** the Hotbox probe creates its private log directory before opening a log, with unique timestamps for repeated starts.
- **Launcher paths:** the full installer validates a restricted path character set before system changes, preventing desktop-entry metacharacters from being interpolated into launchers.
- **Recorded rollback:** system before-state backups, RPM uninstall callbacks, selective dependency removal, and helper cleanup now have a preview/apply command. Changed files and unrecorded software stop automatic removal; private state and projects are preserved. See [rollback scope and limits](ROLLBACK.md).

## Remaining priorities

| Priority | Gap | Useful next evidence or change |
|---|---|---|
| High | The generalized installer has no second complete Debian 13 installation result. | Run on a disposable Debian 13 X11 workstation with legitimate media; record package versions, service checks, sign-in, GUI restart, and scene save/reopen results. Keep personal logs local. |
| High | System rollback is implemented and isolated tests pass, but a complete vendor install/uninstall cycle has not been rehearsed on a second system. | Test successful removal and interrupted installation recovery on a disposable workstation; verify service teardown and any vendor callback effects beyond captured locations. |
| Medium | The Qt suite is skipped without a local Maya/PySide6 runtime. Mixed scaling and monitor changes lack broader desktop evidence. | Run the existing tests with Maya's `mayapy` and follow the [monitor checklist](UI-FIXES.md#laptops-and-external-monitors) on additional hardware. |

These are priorities for reuse or a future reinstall, not a promise of ongoing support. The small UI fixes are easier to reuse and validate than the complete system installer.
