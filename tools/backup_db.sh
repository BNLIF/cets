#!/bin/bash
# Nightly copy of the SQLite database to another disk, rotated.
#
#   tools/backup_db.sh /data/cets-backups [days-to-keep]
#
# ".backup" is SQLite's online backup: one read transaction, consistent
# under WAL, the service keeps running, and the copy is a plain database
# file in single-file journal mode — nothing to unpack, and readable from
# a read-only mount. db-latest.sqlite3 always names the newest copy, for
# anything that wants a stable path (mount the directory, not the file).
# Run as a user that can open the live database (the owner, in the
# service's group). Restore: stop the service, copy over db.sqlite3,
# delete db.sqlite3-wal and -shm, start the service.
set -euo pipefail

dest=${1:?destination directory}
keep=${2:-3}
db=$(cd "$(dirname "$0")/.." && pwd)/db.sqlite3
out="$dest/db-$(date +%Y-%m-%d).sqlite3"

mkdir -p "$dest"
sqlite3 "$db" ".backup '$out'"
# the copy inherits WAL; back to a single file, and prove it opens
sqlite3 "$out" "PRAGMA journal_mode=DELETE; SELECT count(*) FROM sqlite_master" >/dev/null
rm -f "$out-wal" "$out-shm"
ln -sfn "$(basename "$out")" "$dest/db-latest.sqlite3"
find "$dest" -type f -name 'db-*.sqlite3' -mtime "+$keep" -delete
echo "$(date '+%F %T') $out $(du -h "$out" | cut -f1)"
