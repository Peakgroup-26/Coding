#!/usr/bin/env bash
# Back up the database and the drawings to /var/backups/peak-takeoff (keeps 14 days).
# Run by cron every night (deploy/install.sh sets that up), and by update.sh before updating.
# Copy /var/backups/peak-takeoff off the server too (Plesk's backup manager or your own).
set -euo pipefail
cd "$(dirname "$0")/.."

DEST=/var/backups/peak-takeoff
STAMP="$(date +%Y-%m-%d_%H%M)"
mkdir -p "$DEST"
chmod 700 "$DEST"

docker compose exec -T db pg_dump -U takeoff -d takeoff --clean --if-exists | gzip > "$DEST/db-$STAMP.sql.gz"
docker compose exec -T app tar czf - -C /data . > "$DEST/files-$STAMP.tgz"
cp .env "$DEST/env-$STAMP" && chmod 600 "$DEST/env-$STAMP"

find "$DEST" -type f -mtime +14 -delete
echo "$(date): backup saved to $DEST ($STAMP)"

# To restore a database backup:
#   gunzip -c /var/backups/peak-takeoff/db-<stamp>.sql.gz | docker compose exec -T db psql -U takeoff -d takeoff
# To restore the drawings:
#   docker compose exec -T app sh -c 'tar xzf - -C /data' < /var/backups/peak-takeoff/files-<stamp>.tgz
