#!/usr/bin/env bash
# Daily digest — runs weekdays at 07:30.
# Cron: 30 7 * * 1-5 /home/michel/dev/job-radar/cron/digest_daily.sh
#
# Surfaces roles scored since the last digest run (cursor: corpus/.digest_last_run)
# and writes corpus/digest_{date}.md for the morning review.
set -euo pipefail

# Derive the project dir from this script's own location (cron/..), so it works wherever
# the repo is cloned (server: /opt/apps/job-radar; dev: ~/dev/job-radar) without editing.
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${JR_LOG_DIR:-/var/log/job-radar}"   # override JR_LOG_DIR if not writable (needs mkdir perms)
LOG_FILE="${LOG_DIR}/digest_daily.log"

mkdir -p "${LOG_DIR}"
cd "${PROJECT_DIR}"

exec > >(while IFS= read -r line; do printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${line}"; done | tee -a "${LOG_FILE}") 2>&1

echo "=== digest_daily start ==="
docker compose run --rm job-radar python -m cli.digest --min-fit 6 --export
echo "=== digest_daily done ==="
