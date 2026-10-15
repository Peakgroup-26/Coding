#!/usr/bin/env bash
# Install Peak Take-off on an Ubuntu server (works alongside Plesk). Run from the repository folder:
#   sudo ./deploy/install.sh
# Safe to run again: it keeps an existing .env and data.
set -euo pipefail

cd "$(dirname "$0")/.."
APP_DIR="$(pwd)"

if [[ $EUID -ne 0 ]]; then echo "Run this with sudo: sudo ./deploy/install.sh"; exit 1; fi
if ! grep -qi ubuntu /etc/os-release; then echo "This script is for Ubuntu."; exit 1; fi

say() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }

# 1. Docker (skipped if Plesk's Docker extension or anything else already installed it)
if ! command -v docker >/dev/null 2>&1; then
  say "Installing Docker from Docker's official package repository"
  apt-get update -q
  apt-get install -y -q ca-certificates curl
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -q
  apt-get install -y -q docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
if ! docker compose version >/dev/null 2>&1; then
  say "Installing the Docker Compose plugin"
  apt-get install -y -q docker-compose-plugin
fi

# 2. Settings (.env), made once with random secrets
if [[ ! -f .env ]]; then
  say "Creating the settings file (.env)"
  rand() { tr -dc 'A-Za-z0-9' </dev/urandom | head -c "$1"; }
  port=8000
  while ss -ltn "( sport = :$port )" | grep -q LISTEN; do port=$((port + 1)); done
  read -rp "Your email (the first admin login): " admin_email
  read -rsp "Anthropic API key for AI reading (paste it; leave blank to add later): " api_key; echo
  admin_password="$(rand 16)"
  cp .env.example .env
  sed -i "s|^SECRET_KEY=.*|SECRET_KEY=$(rand 64)|" .env
  sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(rand 32)|" .env
  sed -i "s|^ADMIN_EMAIL=.*|ADMIN_EMAIL=${admin_email}|" .env
  sed -i "s|^ADMIN_PASSWORD=.*|ADMIN_PASSWORD=${admin_password}|" .env
  sed -i "s|^ANTHROPIC_API_KEY=.*|ANTHROPIC_API_KEY=${api_key}|" .env
  sed -i "s|^# APP_PORT=.*|APP_PORT=${port}|" .env
  chmod 600 .env
  echo
  echo "  First sign-in:  ${admin_email}"
  echo "  Password:       ${admin_password}"
  echo "  (Write it down now. Change it after you sign in.)"
fi
PORT="$(grep -E '^APP_PORT=' .env | cut -d= -f2)"; PORT="${PORT:-8000}"

# 3. Build and start
say "Building and starting the app (the first build takes a few minutes)"
docker compose up -d --build

say "Waiting for the app to come up"
for i in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then ok=1; break; fi
  sleep 3
done
if [[ -z "${ok:-}" ]]; then
  echo "The app didn't start. Recent logs:"; docker compose logs --tail 50 app; exit 1
fi

# 4. Nightly backups at 2:15 am, kept for 14 days
say "Setting up nightly backups to /var/backups/peak-takeoff"
cat > /etc/cron.d/peak-takeoff <<EOF
15 2 * * * root ${APP_DIR}/deploy/backup.sh >> /var/log/peak-takeoff-backup.log 2>&1
EOF
chmod 644 /etc/cron.d/peak-takeoff

say "Done. The app is running on this server at http://127.0.0.1:${PORT}"
cat <<EOF

Next, in Plesk, point your web address at it (deploy/PLESK.md, step 4):
  Additional nginx directives -> forward to http://127.0.0.1:${PORT}

EOF
