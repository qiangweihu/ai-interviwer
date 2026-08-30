#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="/opt/ai-interviwer"
DATA_DIR="/var/lib/ai-interviwer"
cd "$APP_DIR"
if [[ ! -f .env ]]; then
  echo "missing $APP_DIR/.env; copy .env.example and set MIMO_API_KEY" >&2
  exit 1
fi
git fetch origin
git pull --ff-only origin main
mkdir -p "$DATA_DIR/backups" "$DATA_DIR/models"
if [[ -f "$DATA_DIR/interview.db" ]]; then
  cp "$DATA_DIR/interview.db" "$DATA_DIR/backups/interview-$(date +%Y%m%d-%H%M%S).db"
fi
docker compose build --pull
docker compose run --rm app alembic -c backend/alembic.ini upgrade head
docker compose up -d

# The container can report "Started" before Uvicorn has finished importing
# the application. Retry the probe so a healthy deployment is not reported as
# failed merely because startup took a few seconds.
for attempt in $(seq 1 15); do
  if curl -fsS http://127.0.0.1:8000/health; then
    printf '\n'
    exit 0
  fi
  sleep 2
done

echo "health check failed after waiting for the application" >&2
docker compose ps >&2
docker compose logs --tail=100 app >&2
exit 1
