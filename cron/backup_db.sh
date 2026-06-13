#!/usr/bin/env bash
# SQLite backup — Phase 6.5 (SPEC_DB_MIGRATION §7). Snapshots corpus/job_radar.db
# (interactive state: activity_log / annotations / cv_tailor_links) to a dated file
# and prunes snapshots older than 7 days.
#
# Cron (daily, e.g. 03:30 — keep clear of 00:00 UTC like the other jobs):
#   30 3 * * * /opt/apps/job-radar/cron/backup_db.sh
#
# Uses SQLite's `.backup`, which is safe under concurrent access in WAL mode (the API may
# be writing). Pipeline artefacts stay JSONL and are covered by the existing corpus backup;
# this only adds the DB. No-op (with a notice) if the DB does not exist yet (pre-backfill).
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB_PATH="${JR_DB_PATH:-${PROJECT_DIR}/corpus/job_radar.db}"
BACKUP_DIR="${JR_DB_BACKUP_DIR:-/var/backups/job-radar}"
RETAIN_DAYS="${JR_DB_BACKUP_RETAIN_DAYS:-7}"

if [ ! -f "${DB_PATH}" ]; then
  echo "backup_db: no DB at ${DB_PATH} yet (run 'python -m cli.db_migrate' first) — nothing to back up."
  exit 0
fi
if ! command -v sqlite3 >/dev/null 2>&1; then
  echo "backup_db: sqlite3 not on PATH — install it (apt-get install -y sqlite3)." >&2
  exit 1
fi

mkdir -p "${BACKUP_DIR}"
DEST="${BACKUP_DIR}/db_$(date -u +%Y%m%d).sqlite"
sqlite3 "${DB_PATH}" ".backup '${DEST}'"
echo "backup_db: wrote ${DEST}"

# Prune snapshots older than the retention window.
find "${BACKUP_DIR}" -name 'db_*.sqlite' -mtime "+${RETAIN_DAYS}" -delete
echo "backup_db: pruned snapshots older than ${RETAIN_DAYS} days"
