#!/usr/bin/env bash
# Weekly collection — runs every Sunday at 08:00.
# Cron: 0 8 * * 0 /home/michel/dev/job-radar/cron/collect_weekly.sh
#
# Incremental by default (collect.py reads per-source cursors), so only jobs
# new/updated since the last run enter the paid downstream pipeline. Each stage
# runs in the Docker service; output is timestamped to a rotating log.
set -euo pipefail

PROJECT_DIR="/home/michel/dev/job-radar"
LOG_DIR="/var/log/job-radar"
LOG_FILE="${LOG_DIR}/collect_weekly.log"

mkdir -p "${LOG_DIR}"
cd "${PROJECT_DIR}"

# Prefix every line of stdout+stderr with a UTC timestamp, append to the log,
# and also echo to the console (useful when run manually).
exec > >(while IFS= read -r line; do printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${line}"; done | tee -a "${LOG_FILE}") 2>&1

echo "=== collect_weekly start ==="
docker compose run --rm job-radar python -m cli.collect --source all
docker compose run --rm job-radar python -m cli.dedupe
docker compose run --rm job-radar python -m cli.prefilter
docker compose run --rm job-radar python -m cli.label
docker compose run --rm job-radar python -m cli.validate
docker compose run --rm job-radar python -m cli.score
docker compose run --rm job-radar python -m cli.stats --export-index
echo "=== collect_weekly done ==="
