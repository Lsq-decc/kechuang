#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

if [[ ! -f .env.production ]]; then
  echo "Missing .env.production. Copy .env.production.example first." >&2
  exit 1
fi

docker compose \
  --env-file .env.production \
  -f docker-compose.prod.yml \
  up -d --build

echo "Deployment started. Check status with:"
echo "docker compose --env-file .env.production -f docker-compose.prod.yml ps"

