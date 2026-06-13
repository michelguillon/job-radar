"""db.py — SQLite store for interactive product state (Phase 6.5, SPEC_DB_MIGRATION).

Three JSONL state files move to SQLite; everything else stays JSONL (pipeline
artefacts — see SPEC_DB_MIGRATION §1 boundary):

    corpus/activity_log.jsonl     -> activity_log table
    corpus/annotations.jsonl      -> annotations table
    corpus/cv_tailor_links.jsonl  -> cv_tailor_links table

Append-only discipline is preserved at the application layer: only INSERT — never
UPDATE, never DELETE. ``project()``-style "current state" is a SQL query over the
event log, exactly as it was a Python fold over the JSONL file.

WAL mode is enabled on every connection so the API (writing) and CLI (reading)
can run simultaneously without file-lock contention (SPEC_DB_MIGRATION §7).
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

# Resolved lazily (function, not a module constant) so JR_DB_PATH set after import
# — e.g. a test monkeypatching the env — is still honoured.
_DEFAULT_DB_PATH = "corpus/job_radar.db"


def get_db_path() -> Path:
    """Resolve the DB path: ``JR_DB_PATH`` env var, else ``corpus/job_radar.db``."""
    return Path(os.getenv("JR_DB_PATH", _DEFAULT_DB_PATH))


# Back-compat module attribute for call sites / docs that reference DB_PATH.
DB_PATH = get_db_path()


def get_db() -> sqlite3.Connection:
    """Open a connection with row access by name, WAL mode, and FKs enabled."""
    path = get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Create tables + indexes if they don't exist. Idempotent."""
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS activity_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                ts         TEXT NOT NULL,
                job_id     TEXT NOT NULL,
                event      TEXT NOT NULL,
                value      TEXT,
                notes      TEXT DEFAULT '',
                v          INTEGER DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_al_job_id ON activity_log (job_id);
            CREATE INDEX IF NOT EXISTS idx_al_event  ON activity_log (event);
            CREATE INDEX IF NOT EXISTS idx_al_ts     ON activity_log (ts DESC);

            CREATE TABLE IF NOT EXISTS annotations (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                ts               TEXT NOT NULL,
                job_id           TEXT NOT NULL,
                annotation_type  TEXT NOT NULL,
                field            TEXT,
                observed         TEXT,
                expected         TEXT,
                reason           TEXT NOT NULL,
                scorer_label     TEXT,
                scorer_fit_score INTEGER,
                v                INTEGER DEFAULT 1,
                created_at       TEXT DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_ann_job_id ON annotations (job_id);
            CREATE INDEX IF NOT EXISTS idx_ann_type   ON annotations (annotation_type);
            -- Duplicate-prevention key, equivalent to the current Python dedup
            -- (annotations.py: job_id + type + field + reason). A table-level
            -- UNIQUE(...field...) would NOT dedupe rejection_reasons, which carry
            -- field=NULL (deviation 39): standard SQL treats NULLs as distinct, so
            -- two identical null-field rows would both insert. IFNULL(field,'')
            -- collapses NULL to '' for the key, matching Python's None == None.
            CREATE UNIQUE INDEX IF NOT EXISTS idx_ann_unique
                ON annotations (job_id, annotation_type, IFNULL(field, ''), reason);

            CREATE TABLE IF NOT EXISTS cv_tailor_links (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                ts               TEXT NOT NULL,
                job_id           TEXT NOT NULL,
                cv_tailor_run_id TEXT NOT NULL,
                fit_score        REAL,
                coverage_score   REAL,
                cv_quality_score REAL,
                cvcm_enabled     INTEGER,
                tailoring_mode   TEXT,
                output_link      TEXT,
                notes            TEXT DEFAULT '',
                source           TEXT DEFAULT 'manual',
                v                INTEGER DEFAULT 1,
                created_at       TEXT DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_ctl_job_id ON cv_tailor_links (job_id);
            CREATE INDEX IF NOT EXISTS idx_ctl_run_id ON cv_tailor_links (cv_tailor_run_id);

            -- version is the PRIMARY KEY (not the spec's bare INTEGER NOT NULL) so
            -- INSERT OR IGNORE actually no-ops on re-init; otherwise init_db would
            -- append a duplicate version row every run and break idempotency.
            CREATE TABLE IF NOT EXISTS schema_version (
                version    INTEGER PRIMARY KEY,
                applied_at TEXT DEFAULT (datetime('now'))
            );
            INSERT OR IGNORE INTO schema_version (version) VALUES (1);
            """
        )


def main(argv: list[str] | None = None) -> int:
    """CLI entry: ``python -m cli.db init`` creates/upgrades the DB."""
    import sys

    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] != "init":
        print(f"usage: python -m cli.db init  (got: {argv})")
        return 2
    init_db()
    print(f"Initialised SQLite DB at {get_db_path()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
