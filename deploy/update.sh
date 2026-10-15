#!/usr/bin/env bash
# Update Peak Take-off to the latest version on main. Run from the repository folder:
#   sudo ./deploy/update.sh
# Takes a backup first. Database changes are applied automatically when the app starts.
set -euo pipefail
cd "$(dirname "$0")/.."

./deploy/backup.sh
git pull --ff-only origin main
docker compose up -d --build

PORT="$(grep -E '^APP_PORT=' .env | cut -d= -f2)"; PORT="${PORT:-8000}"
for i in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then echo "Updated and running."; exit 0; fi
  sleep 3
done
echo "The app didn't come back up. Recent logs:"
docker compose logs --tail 50 app
exit 1
