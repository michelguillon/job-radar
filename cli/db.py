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

import json
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


def get_db(path: str | Path | None = None) -> sqlite3.Connection:
    """Open a connection with row access by name, WAL mode, and FKs enabled.

    ``path`` overrides the resolved DB path (used by the backfill's ``db_path`` arg);
    when None it falls back to ``get_db_path()`` (``JR_DB_PATH`` env or the default).
    """
    db_path = Path(path) if path is not None else get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
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


# ---------------------------------------------------------------------------
# Row I/O — one home for the JSONL-dict <-> SQL-row mapping so backfill
# (Step 2), dual-write (Step 4), and dual-read (Step 3/5) cannot drift apart.
# ---------------------------------------------------------------------------

def _enc(value):
    """JSON-encode a complex column value (annotations observed/expected) for TEXT.

    None maps to SQL NULL (not the string ``"null"``) so it round-trips to None and
    matches the JSONL loaders, which return None for an absent/null field. Lists, dicts
    and scalars are JSON-encoded and decoded by ``_dec`` on read.
    """
    return None if value is None else json.dumps(value, ensure_ascii=False)


def _dec(text):
    """Inverse of ``_enc``: SQL NULL -> None, else ``json.loads``."""
    return None if text is None else json.loads(text)


def _bool_to_int(value):
    """SQLite has no bool: True/False -> 1/0, None stays NULL."""
    return None if value is None else int(bool(value))


def insert_activity_event(conn: sqlite3.Connection, event: dict) -> None:
    """INSERT one activity-log event (plain INSERT — append-only, no dedup).

    ``value`` is a scalar (str|None) per ``validate_activity_event``, stored raw so it
    stays human-readable in the ``sqlite3`` CLI; ``notes`` defaults to ''.
    """
    conn.execute(
        "INSERT INTO activity_log (ts, job_id, event, value, notes, v) VALUES (?,?,?,?,?,?)",
        (
            event.get("ts"),
            event.get("job_id"),
            event.get("event"),
            event.get("value"),
            event.get("notes", "") or "",
            event.get("v", 1),
        ),
    )


def insert_annotation(conn: sqlite3.Connection, rec: dict) -> None:
    """INSERT one annotation. Raises ``sqlite3.IntegrityError`` on a duplicate
    (the IFNULL(field,'') unique index) — the dual-write path maps that to a 409."""
    conn.execute(
        "INSERT INTO annotations "
        "(ts, job_id, annotation_type, field, observed, expected, reason, "
        " scorer_label, scorer_fit_score, v) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            rec.get("ts"),
            rec.get("job_id"),
            rec.get("annotation_type"),
            rec.get("field"),
            _enc(rec.get("observed")),
            _enc(rec.get("expected")),
            rec.get("reason"),
            rec.get("scorer_label"),
            rec.get("scorer_fit_score"),
            rec.get("v", 1),
        ),
    )


def insert_cv_tailor_link(conn: sqlite3.Connection, rec: dict) -> None:
    """INSERT one cv-tailor link (plain INSERT — multiple runs per job_id are kept)."""
    conn.execute(
        "INSERT INTO cv_tailor_links "
        "(ts, job_id, cv_tailor_run_id, fit_score, coverage_score, cv_quality_score, "
        " cvcm_enabled, tailoring_mode, output_link, notes, source, v) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            rec.get("ts"),
            rec.get("job_id"),
            rec.get("cv_tailor_run_id"),
            rec.get("fit_score"),
            rec.get("coverage_score"),
            rec.get("cv_quality_score"),
            _bool_to_int(rec.get("cvcm_enabled")),
            rec.get("tailoring_mode"),
            rec.get("output_link"),
            rec.get("notes") or "",
            rec.get("source", "manual") or "manual",
            rec.get("v", 1),
        ),
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
