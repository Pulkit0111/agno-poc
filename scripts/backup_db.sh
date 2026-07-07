#!/usr/bin/env bash
# Back up the production Postgres database — there is no other backup path today. If the
# database volume/instance is ever lost, everything it holds (conversation memory, connected
# accounts/tokens, review history, approvals, authored skills) goes with it unless a dump like
# this one exists somewhere else.
#
# Usage:
#   DATABASE_URL=postgresql://user:pass@host:5432/bott scripts/backup_db.sh
#
# Env:
#   DATABASE_URL              required — the same Postgres URL the app itself uses.
#   BOTT_BACKUP_DIR           where dumps are written (default: ./backups).
#   BOTT_BACKUP_RETENTION_DAYS  delete dumps older than this many days (default: 14; set 0 to
#                              keep every dump forever).
#
# Scheduling (pick one — this script does not schedule itself):
#   cron (daily at 02:00):
#     0 2 * * * DATABASE_URL=postgresql://... /path/to/scripts/backup_db.sh >> /var/log/bott-backup.log 2>&1
#   systemd timer: a bott-backup.service (ExecStart=this script) + a bott-backup.timer
#     (OnCalendar=daily) is the equivalent on a systemd host.
#
# Restore:
#   gunzip -c backups/bott-<timestamp>.sql.gz | psql "$DATABASE_URL"
#   (restoring into a database that already has data will conflict — restore into a fresh
#   database, or drop/recreate the target first.)
#
# This intentionally only writes local files — piping the dump straight to off-host storage
# (S3, a backup service, etc.) is a deploy-specific decision left to whoever wires this in.
#
# Note: pg_dump refuses to run against a Postgres server NEWER than itself. Make sure
# whatever host/container runs this has a pg_dump version >= the server's.

set -euo pipefail

if [ -z "${DATABASE_URL:-}" ]; then
  echo "backup_db.sh: DATABASE_URL is not set — nothing to back up." >&2
  exit 1
fi

BACKUP_DIR="${BOTT_BACKUP_DIR:-./backups}"
RETENTION_DAYS="${BOTT_BACKUP_RETENTION_DAYS:-14}"
mkdir -p "$BACKUP_DIR"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
dest="$BACKUP_DIR/bott-${timestamp}.sql.gz"
tmp="${dest}.partial"

echo "backup_db.sh: dumping to ${dest} ..."
if ! pg_dump "$DATABASE_URL" | gzip > "$tmp"; then
  echo "backup_db.sh: pg_dump failed — removing partial file." >&2
  rm -f "$tmp"
  exit 1
fi
mv "$tmp" "$dest"
echo "backup_db.sh: wrote $(du -h "$dest" | cut -f1) to ${dest}"

if [ "$RETENTION_DAYS" -gt 0 ]; then
  deleted=$(find "$BACKUP_DIR" -name 'bott-*.sql.gz' -mtime "+${RETENTION_DAYS}" -print -delete | wc -l | tr -d ' ')
  if [ "$deleted" -gt 0 ]; then
    echo "backup_db.sh: pruned ${deleted} backup(s) older than ${RETENTION_DAYS} days."
  fi
fi
