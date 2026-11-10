# Autodesk Maya 2027 on Debian + i3

## Meat Proxy's notes

This repository is for other Autodesk Maya 2027 users who foolishly tried to install it on a workstation running Debian and i3. May the scripts I had GPT-6.1-Sol (Codex, high reasoning effort) write be of some help.

Some problems you may have run into are fairly general; others, like mine, are more idiosyncratic. I hope future users and AI agents can reuse or adapt this repository to solve similar issues.

Do not expect support or updates from me. I do not plan to review or merge pull requests. I may update this repository (or have it updated...) the next time I reinstall Maya and run into new issues.

## Find your problem

Pick the issue that matches your setup. The Hotbox and i3 fixes can be used with an existing Maya installation.

| Problem | Start here |
|---|---|
| Space works, but the Hotbox is invisible | [Hotbox fix, setup, and removal](docs/UI-FIXES.md#invisible-hotbox) |
| Detached Maya panels get tiled or look maximized in i3 | [i3 panel fix](docs/UI-FIXES.md#detached-panels-in-i3) |
| APT returns 404 for old OpenSSL or TIFF packages | [Compatibility downloads](docs/INSTALL-MAYA.md#apt-downloads-return-404) |
| The RPM database cannot be opened as a normal user | [RPM database](docs/INSTALL-MAYA.md#rpm-database-cannot-be-opened) |
| The licensing plugin reports missing libraries | [Library context](docs/INSTALL-MAYA.md#licensing-plugin-reports-missing-libraries) |
| Identity Manager rejects `--register` | [Sign-in handler](docs/INSTALL-MAYA.md#identity-manager-registration-fails) |
| Installation metadata is unreadable | [Metadata permissions](docs/INSTALL-MAYA.md#installation-metadata-is-unreadable) |
| `libaudiofile.so` is missing | [Audio library alias](docs/INSTALL-MAYA.md#libaudiofileso-is-missing) |
| Maya is not installed yet | [Full installation notes](docs/INSTALL-MAYA.md) |
| Undo installation, symlinks, or helper changes | [Rollback and cleanup](docs/ROLLBACK.md) |

## What was actually tried

The original setup was Maya **2027.2 on Debian 13 x86_64, X11, i3, and AMD graphics**. Maya startup, the Hotbox fix, and activation after a complete restart were confirmed on that desktop. The generalized installer has syntax checks and isolated tests, but has not completed a second full system installation. Debian is not an Autodesk-supported Maya platform.

These are notes and scripts from one working installation. Compare your versions and symptoms before reusing a fix. In particular, the measured Hotbox problem involved three monitors; its internal cause is still uncertain.

## Reuse by people and AI agents

Start with the matching issue above, then read the relevant script. The detailed notes describe the observed symptom, the workaround, and its limits. Adapt the part you need to your own machine. Running the full installer is only appropriate for the fresh installation described in its guide.

The scripts and documentation are mainly AI-written. [Test notes](docs/TESTING.md) distinguish automated checks from observations in the original Maya desktop session. There is no support or maintenance commitment; you can copy, adapt, or fork the material under the [MIT license](LICENSE).

Keep personal paths, account details, tokens, license state, and diagnostic logs out of anything you share. Local runtime directories are excluded by `.gitignore`; logs still need checking before you copy them elsewhere.

## Check a copy before adapting it

On Linux with Bash, Python 3.11+, RPM with its SQLite backend, and GNU coreutils:

```bash
bash scripts/check-repo.sh
```

This local command checks Python/Bash syntax, runs the isolated tests, and verifies the export hashes without installing or launching Maya. Qt tests require a separate Maya runtime and otherwise report skips. Passing these checks does not establish Debian/Maya installation compatibility. See [test details](docs/TESTING.md) and the [repository review and remaining work](docs/REVIEW.md).

## Repository layout

```text
README.md                 Start with the author's notes and your symptom
LICENSE                   MIT terms and the project note
docs/
  UI-FIXES.md             Individual Hotbox and i3 fixes
  INSTALL-MAYA.md         Full installation and known installation issues
  TESTING.md              Verification and its limits
  REVIEW.md               Strengths, addressed defects, and remaining priorities
  ROLLBACK.md             Preview and undo recorded installation/helper changes
scripts/                  Main commands and the standalone Hotbox fix
  helpers/                Supporting installation and runtime scripts
  diagnostics/            Tools for investigating Maya windows
templates/                Startup and desktop-entry templates
metadata/                 Checksums for the inspected vendor packages
tests/                    Isolated regression tests
EXPORT-SHA256SUMS          Checksums of the shareable repository files
```

Run the examples from the repository root. Scripts that need the repository location derive it from their own file location, so you can also call them by absolute path from another directory. Relative file arguments refer to your current directory. Keep the repository in place after installation because generated launchers and startup files contain absolute paths.

Autodesk installation media, credentials, and license state are not included. Obtain Maya from your own Autodesk Account and sign in through Autodesk's normal setup. The MIT license covers this repository's own scripts and documentation, separately from Autodesk products and their terms.
