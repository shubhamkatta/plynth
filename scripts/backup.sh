#!/usr/bin/env bash
# Nightly Postgres backup → Backblaze B2.
#
# Usage (from the repo root, as the deploy user):
#   ./scripts/backup.sh
#
# Cron suggestion (3:13 AM daily — odd minute spreads load across hosts):
#   13 3 * * * cd /opt/platform && ./scripts/backup.sh >> /var/log/platform-backup.log 2>&1
#
# Requires:
#   - The `b2` CLI logged in: `b2 account authorize <keyId> <appKey>`
#   - A bucket named `$B2_BUCKET` (private; lifecycle rule to delete >30 days)
#   - Docker + the platform stack running
#
# Env overrides:
#   COMPOSE_FILES   default "-f docker-compose.yml -f docker-compose.prod.yml"
#   DB_SERVICE      default "db"
#   DB_USER         default "platform"
#   DB_NAME         default "platform"
#   B2_BUCKET       default "platform-backups"
#   KEEP_LOCAL_DAYS default 7

set -euo pipefail

COMPOSE_FILES="${COMPOSE_FILES:--f docker-compose.yml -f docker-compose.prod.yml}"
DB_SERVICE="${DB_SERVICE:-db}"
DB_USER="${DB_USER:-platform}"
DB_NAME="${DB_NAME:-platform}"
B2_BUCKET="${B2_BUCKET:-platform-backups}"
KEEP_LOCAL_DAYS="${KEEP_LOCAL_DAYS:-7}"

BACKUP_DIR="/var/backups/platform"
mkdir -p "$BACKUP_DIR"

STAMP="$(date -u +%Y-%m-%dT%H-%M-%SZ)"
DUMP_PATH="$BACKUP_DIR/platform-$STAMP.sql.gz"

echo "[$(date -u +%FT%TZ)] starting backup → $DUMP_PATH"

# pg_dump from inside the db container, piped through gzip on the host.
docker compose $COMPOSE_FILES exec -T "$DB_SERVICE" \
    pg_dump -U "$DB_USER" -d "$DB_NAME" --format=plain --no-owner --no-acl \
    | gzip -9 > "$DUMP_PATH"

SIZE_BYTES="$(stat -c%s "$DUMP_PATH")"
echo "[$(date -u +%FT%TZ)] dumped $SIZE_BYTES bytes"

# Sanity: refuse to ship a tiny / empty dump.
if [ "$SIZE_BYTES" -lt 1024 ]; then
    echo "ERROR: dump suspiciously small ($SIZE_BYTES bytes); not uploading" >&2
    exit 1
fi

# Upload to B2.
if command -v b2 >/dev/null 2>&1; then
    b2 file upload "$B2_BUCKET" "$DUMP_PATH" "platform-$STAMP.sql.gz" >/dev/null
    echo "[$(date -u +%FT%TZ)] uploaded to b2://$B2_BUCKET/platform-$STAMP.sql.gz"
else
    echo "WARN: b2 CLI not installed; skipping upload. Run: pip install b2" >&2
fi

# Prune local copies older than $KEEP_LOCAL_DAYS days.
find "$BACKUP_DIR" -name 'platform-*.sql.gz' -mtime +"$KEEP_LOCAL_DAYS" -delete

echo "[$(date -u +%FT%TZ)] done"
