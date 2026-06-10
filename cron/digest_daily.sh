#!/usr/bin/env bash
# Daily digest — runs weekdays at 07:30.
# Cron: 30 7 * * 1-5 /home/michel/dev/job-radar/cron/digest_daily.sh
#
# Surfaces roles scored since the last digest run (cursor: corpus/.digest_last_run)
# and writes corpus/digest_{date}.md for the morning review.
set -euo pipefail

PROJECT_DIR="/home/michel/dev/job-radar"
LOG_DIR="/var/log/job-radar"
LOG_FILE="${LOG_DIR}/digest_daily.log"

mkdir -p "${LOG_DIR}"
cd "${PROJECT_DIR}"

exec > >(while IFS= read -r line; do printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${line}"; done | tee -a "${LOG_FILE}") 2>&1

echo "=== digest_daily start ==="
docker compose run --rm job-radar python -m cli.digest --min-fit 6 --export
echo "=== digest_daily done ==="
