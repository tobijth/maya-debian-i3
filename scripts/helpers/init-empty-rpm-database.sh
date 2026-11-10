#!/bin/bash
# Called with sudo by the installer for /var/lib/rpm. Also supports an isolated
# unprivileged test directory. Never clears or rebuilds an existing database.
set -euo pipefail
umask 022
[[ $# == 1 && $1 == /* && $1 != / ]] || {
    echo 'An absolute, empty database directory is required.' >&2
    exit 1
}
database=$1
# Strip trailing separators before lstat-style checks; link/ follows the link.
while [[ $database != / && $database == */ ]]; do database=${database%/}; done
[[ $database != / ]] || { echo 'The filesystem root is not a database target.' >&2; exit 1; }
component_path=$database
while [[ $component_path != / && -n $component_path ]]; do
    component=${component_path##*/}
    [[ $component != . && $component != .. ]] || {
        echo 'Dot path components are not allowed in the database path.' >&2; exit 1;
    }
    [[ ! -L $component_path ]] || {
        echo "Refusing a symlink in the database path: $component_path" >&2; exit 1;
    }
    component_path=${component_path%/*}
done
if [[ -e $database ]]; then
    [[ -d $database ]] || { echo "Not a directory: $database" >&2; exit 1; }
    first=$(find "$database" -mindepth 1 -maxdepth 1 -print -quit)
    [[ -z $first ]] || {
        echo "Database directory is not empty; inspect it instead of initializing: $database" >&2
        exit 1
    }
fi
python3 "$(dirname -- "${BASH_SOURCE[0]}")/local_undo.py" database-record "$database"
exec 8>"$database.maya-undo/operation.lock"
flock -n 8 || { echo 'Database initialization or rollback is already active.' >&2; exit 1; }
install -d -m 0755 "$database"
rpm --dbpath "$database" --initdb
test -s "$database/rpmdb.sqlite"
# SQLite's WAL/SHM files must also be readable for queries from the user session.
find "$database" -maxdepth 1 -type f -exec chmod a+r '{}' +
rpm --dbpath "$database" -qa
printf 'Leere RPM-Datenbank initialisiert: %s\n' "$database"
