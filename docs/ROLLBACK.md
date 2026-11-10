# Undo installation and helper changes

Close Maya and `mayapy` first. Session-only Hotbox changes and detached windows disappear when Maya exits. The rollback command previews its work unless you add `--apply`.

## Full installation

New installer runs save a private before-state record under `state/rollback`. Preview the system rollback from the original repository location:

```bash
sudo /usr/bin/python3 scripts/rollback-maya.py
```

To include removal of newly installed Debian dependencies and cleanup of recorded local helper files, preview with the same options you intend to apply:

```bash
sudo /usr/bin/python3 scripts/rollback-maya.py --remove-dependencies --clean-workspace
```

Read the preview, then execute it:

```bash
sudo /usr/bin/python3 scripts/rollback-maya.py --remove-dependencies --clean-workspace --apply
```

This stops the clone's i3 helper and the licensing service, removes the generated Hotbox startup block, runs recorded vendor RPM uninstall callbacks with fresh-uninstall argument `0`, erases the exact recorded RPMs, and restores captured system files, symlinks, directories and permissions. Vendor callbacks are run with Bash, matching installation. Their output on failure is kept in private `state/rollback/last-error.txt`.

The before-state includes the original targets or contents of replaced `/usr/local/bin` links and Maya menu integration, the certificate and WebKit aliases, loader and RPM macro files, RPM database state, user desktop entries and MIME defaults. RPM payload paths are added to the record before each package is installed. Existing symlinks are restored as symlinks, including broken links; they are not dereferenced into replacement files.

The fresh installer refuses existing Autodesk directories, an existing `adsklic` account/group, or an already active/enabled licensing unit. Newly created `adsklic` accounts/groups are removed only if they still match the recorded identity. Unexpected RPM packages or keys, changed Debian package versions, changed managed files, modified before-state backups, and redirected parent paths stop automatic removal.

Without `--remove-dependencies`, Debian dependencies remain installed. With it, only packages absent before installation and present in the recorded APT installation plan are eligible, and an APT simulation must show no removals or installations of other packages. Packages added outside that plan are kept. The script never runs autoremove or downgrades existing packages. The installer now refuses an APT plan that would replace an existing package version; this keeps future removal from relying on unavailable old packages. Debian package removal uses `remove`, so residual package configuration is retained rather than purged.

## Standalone UI fixes

For an existing Maya installation, use the actual `MAYA_APP_DIR`:

```bash
python3 scripts/rollback-maya.py --ui-only --app-dir "$HOME/maya"
python3 scripts/rollback-maya.py --ui-only --app-dir "$HOME/maya" --apply
```

Run this as your normal user. It removes only the marked startup block, preserving other startup commands, and stops the panel helper from this clone. It also works for startup blocks created before system rollback recording was added. For this repository's native installation, the default app directory is `<repo>/user`.

New startup installs keep a small private before-state sidecar beside `userSetup.py`; removal can delete a file created only for this fix and restore a missing final newline exactly. A new file containing later user code is kept. Startup backups remain available after removal.

## Media, downloads, caches and diagnostic files

The media preparer, compatibility downloader, launcher, URI helper, panel helper and Hotbox diagnostic now record their local output locations before changing them. To restore those locations:

```bash
python3 scripts/rollback-maya.py --workspace-only
python3 scripts/rollback-maya.py --workspace-only --apply
```

Run this as your normal user after closing Maya and waiting for any media preparation/download to finish. The script checks operation locks before local restoration. This mode does not uninstall system software or remove a startup block in an external Maya app directory; use the corresponding modes above as well. `--clean-workspace` combines local cleanup with system rollback or `--ui-only`.

Local records are under `state/local-undo`. Overlapping scopes are restored in reverse recording order. Current files are moved into private `retained` directories in those records before the previous contents are restored. A newly created, empty `user` or `projects` container can be removed; a container with preferences or scenes is kept. The original Autodesk archive is never removed. Read-only preflight and X11 inspection scripts have no settings to undo.

## Standalone RPM database initialization

The empty-database helper saves the original directory state in an adjacent `<database>.maya-undo` directory before creating or changing a database:

```bash
python3 scripts/rollback-maya.py --rpm-db /absolute/path/to/database
python3 scripts/rollback-maya.py --rpm-db /absolute/path/to/database --apply
```

Use sudo for a root-owned database. The rollback refuses any database that now contains packages or signing-key records, and refuses to run while initialization holds its operation lock. If the original directory existed, its empty contents and original permissions are restored. If it did not exist, it is removed. The current database is retained privately. The native installation uses its full system record for shared database restoration.

## Interrupted installation or rollback

Normal installer exits, including ordinary errors and handled interrupts, record the resulting after-state. A machine crash or `SIGKILL` can leave the record unsealed. Preview such a record with `--allow-incomplete`; this permits only the missing after-state check and retains current managed paths privately during restoration. It does not override foreign packages, unknown account identities, redirected paths, or corrupted backups. Missing information can still require manual review.

Each completed removal/restoration step is recorded. If rollback itself fails, inspect the error and private journal, then use `--resume` with the same options. A failed post-uninstall callback is retried even if RPM erasure already succeeded. Do not edit the journal or delete markers to force progress. Completed rollback is a no-op on repeated invocation.

Keep the repository at its original path throughout installation and rollback. After completed removal, archive the private records and use a fresh working copy for a new installation; completed records are intentionally not silently overwritten.

## Retained data and limits

Rollback restores recorded changes, not a byte-for-byte snapshot of the entire operating system. It retains projects, Maya preferences, user Autodesk account files, source installation media, logs and recovery evidence. Service state is copied privately before vendor uninstall callbacks can delete it; remaining service/runtime data is also retained when managed paths are restored. The private journal may therefore need substantial extra disk space. If preservation fails, rollback stops before continuing deletion.

Package-manager caches, package configuration left by `remove`, and external Autodesk account/activation events are not rewound. Opaque vendor callbacks may have effects beyond their RPM payload and the explicitly captured locations; this implementation has isolated tests but has not been validated through a complete install/uninstall on a second workstation. The [test notes](TESTING.md) describe this limit.

Old installations made without these records cannot be reconstructed exactly. The system mode refuses those instead of guessing original symlink targets, deleting arbitrary Autodesk data, or pretending that removal of a few links reverses vendor installation. Keep their existing `backups` and logs for a manual inventory. The standalone UI removal remains available.

All records and retained files are private runtime data, ignored by Git. Do not include `state`, `backups`, retained service data, or adjacent database undo directories in a shared archive. Delete recovery backups only after inspecting them and confirming that no needed data remains.
