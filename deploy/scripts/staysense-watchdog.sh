#!/usr/bin/env bash
set -euo pipefail

HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8787/health}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-5}"

if ! curl -fsS --max-time "${TIMEOUT_SECONDS}" "${HEALTH_URL}" >/dev/null; then
  logger -t staysense-watchdog "healthcheck failed for ${HEALTH_URL}, restarting staysense-api.service"
  systemctl restart staysense-api.service
fi
