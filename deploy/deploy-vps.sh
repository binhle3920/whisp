#!/usr/bin/env bash
# Redeploy Whisp on the VPS from the latest origin/main.
#
# This script is the forced command for the GitHub Actions deploy key (see
# ~/.ssh/authorized_keys), so it is the only thing that key can run.
#
# It deliberately uses fetch + reset --hard rather than a re-clone: .env,
# credentials/ and config/assistant.toml live in this directory untracked, and
# a re-clone would destroy them (which is how the previous deployment was lost).
set -euo pipefail

APP_DIR="${WHISP_APP_DIR:-/home/binh3920/apps/whisp}"
BRANCH="${WHISP_BRANCH:-main}"

cd "$APP_DIR"

echo "==> Fetching origin/$BRANCH"
git fetch --prune origin "$BRANCH"
git reset --hard "origin/$BRANCH"

# Required untracked files. Bail out before touching the running container so a
# misconfigured host fails loudly instead of restarting into a broken state.
for required in .env credentials/google_credentials.json config/assistant.toml; do
  if [[ ! -f "$required" ]]; then
    echo "ERROR: missing $APP_DIR/$required -- refusing to deploy" >&2
    exit 1
  fi
done

echo "==> Building and starting containers"
export WHISP_UID="$(id -u)" WHISP_GID="$(id -g)"
docker compose -f docker-compose.yml -f compose.vps.yml up -d --build --remove-orphans

echo "==> Waiting for health"
for attempt in $(seq 1 30); do
  status="$(docker inspect --format '{{.State.Health.Status}}' whisp-whisp-1 2>/dev/null || echo unknown)"
  if [[ "$status" == "healthy" ]]; then
    echo "==> Healthy after ${attempt}0s"
    docker image prune -f >/dev/null 2>&1 || true
    echo "==> Deployed $(git rev-parse --short HEAD)"
    exit 0
  fi
  if [[ "$status" == "unhealthy" ]]; then
    break
  fi
  sleep 10
done

echo "ERROR: container did not become healthy (last status: ${status:-unknown})" >&2
docker compose -f docker-compose.yml -f compose.vps.yml logs --tail 50 whisp >&2
exit 1
