#!/usr/bin/env bash
# Weekly collection — runs every Sunday at 08:00.
# Cron: 0 8 * * 0 /opt/apps/job-radar/cron/collect_weekly.sh
#
# Incremental by default (collect.py reads per-source cursors), so only jobs
# new/updated since the last run enter the paid downstream pipeline. Each stage
# runs in the Docker service; output is timestamped to a rotating log.
set -euo pipefail

# Derive the project dir from this script's own location (cron/..), so it works wherever
# the repo is cloned (server: /opt/apps/job-radar; dev: ~/dev/job-radar) without editing.
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${JR_LOG_DIR:-/var/log/job-radar}"   # override JR_LOG_DIR if not writable (needs mkdir perms)
LOG_FILE="${LOG_DIR}/collect_weekly.log"

# Compose files: base + the tracing overlay, so cli.label/cli.score can reach the Langfuse web
# container (langfuse-langfuse-web-1) and export traces (SPEC §16, deviation 46). The overlay
# needs the external `tracing` network to exist (server prereq: `docker network create tracing`).
# Local dev / a host without that network: override to skip it —
#   JR_COMPOSE_FILES="-f docker-compose.yml" ./cron/collect_weekly.sh
# (tracing is opt-in by LANGFUSE_PUBLIC_KEY anyway, so dropping the overlay just runs untraced).
COMPOSE_FILES="${JR_COMPOSE_FILES:--f docker-compose.yml -f docker-compose.tracing.yml}"

mkdir -p "${LOG_DIR}"
cd "${PROJECT_DIR}"

# Prefix every line of stdout+stderr with a UTC timestamp, append to the log,
# and also echo to the console (useful when run manually).
exec > >(while IFS= read -r line; do printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${line}"; done | tee -a "${LOG_FILE}") 2>&1

echo "=== collect_weekly start ==="
# Each stage runs bare on sensible defaults keyed to the current UTC day, so the chain is:
#   collect (incremental) -> prefilter (screen + drop already-labelled/scored) ->
#   label (today's survivors, tier 4 -- SPENDS Batch budget) -> validate (today's labelled) ->
#   score (all validated) -> stats --export-index (writes the UI's corpus/index.json).
# Do NOT move this schedule near 00:00 UTC: collect/prefilter/label/validate key off the
# current UTC date, so a run straddling midnight would split across two date stamps.
# (cli.dedupe is an empty stub and is intentionally omitted -- prefilter does the dedup.)
docker compose ${COMPOSE_FILES} run --rm job-radar python -m cli.collect --source all
docker compose ${COMPOSE_FILES} run --rm job-radar python -m cli.prefilter
docker compose ${COMPOSE_FILES} run --rm job-radar python -m cli.label
docker compose ${COMPOSE_FILES} run --rm job-radar python -m cli.validate
docker compose ${COMPOSE_FILES} run --rm job-radar python -m cli.score
docker compose ${COMPOSE_FILES} run --rm job-radar python -m cli.stats --export-index
echo "=== collect_weekly done ==="
