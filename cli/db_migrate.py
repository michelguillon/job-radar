"""db_migrate.py — backfill the three JSONL state files into SQLite (Phase 6.5 Step 2).

    python -m cli.db_migrate          # backfill all three from corpus/*.jsonl

Each backfill is **idempotent**: re-running inserts 0 rows. Annotations dedupe on the
UNIQUE expression index (``INSERT OR IGNORE``); activity_log and cv_tailor_links have no
DB constraint (an append log may legitimately carry repeats), so idempotency is a
content-existence pre-check on a natural key. The existing JSONL files are never modified
— they become the audit archive (SPEC_DB_MIGRATION §2).
"""

from __future__ import annotations

import sqlite3

from cli.db import (
    get_db,
    init_db,
    insert_activity_event,
    insert_annotation,
    insert_cv_tailor_link,
)
from cli.stats import (
    ANNOTATIONS_PATH,
    CV_TAILOR_LINKS_PATH,
    _migrate_cv_tailor_fields,
)
from cli.track import LOG_PATH, load_events


def _row_exists(conn: sqlite3.Connection, table: str, key: dict) -> bool:
    """True if a row matches every (column, value) in ``key``. ``IS`` is NULL-safe,
    so a NULL key value matches a NULL column (plain ``=`` never would)."""
    where = " AND ".join(f"{col} IS ?" for col in key)
    sql = f"SELECT 1 FROM {table} WHERE {where} LIMIT 1"
    return conn.execute(sql, tuple(key.values())).fetchone() is not None


def backfill_activity_log(jsonl_path: str = LOG_PATH, db_path: str | None = None) -> int:
    """Insert every activity_log.jsonl event into the activity_log table. Idempotent
    on (ts, job_id, event, value, notes). Returns rows inserted."""
    init_db()
    inserted = 0
    with get_db(db_path) as conn:
        for ev in load_events(jsonl_path):
            key = {
                "ts": ev.get("ts"),
                "job_id": ev.get("job_id"),
                "event": ev.get("event"),
                "value": ev.get("value"),
                "notes": ev.get("notes", "") or "",
            }
            if _row_exists(conn, "activity_log", key):
                continue
            insert_activity_event(conn, ev)
            inserted += 1
    return inserted


def backfill_annotations(jsonl_path: str = ANNOTATIONS_PATH, db_path: str | None = None) -> int:
    """Insert every annotations.jsonl record into the annotations table. Idempotent via
    the UNIQUE(job_id, type, IFNULL(field,''), reason) index. Returns rows inserted."""
    init_db()
    inserted = 0
    with get_db(db_path) as conn:
        for rec in load_events(jsonl_path):
            try:
                insert_annotation(conn, rec)
                inserted += 1
            except sqlite3.IntegrityError:
                # Duplicate (re-run, or a repeated line in the JSONL) — skip gracefully.
                continue
    return inserted


def backfill_cv_tailor_links(jsonl_path: str = CV_TAILOR_LINKS_PATH, db_path: str | None = None) -> int:
    """Insert every cv_tailor_links.jsonl record into the cv_tailor_links table. The
    read-time field migration (deviation 43: cv_tailor_score -> fit_score, drop
    grounding_score) is applied before insert so the DB carries the new names. Idempotent
    on (ts, job_id, cv_tailor_run_id). Returns rows inserted."""
    init_db()
    inserted = 0
    with get_db(db_path) as conn:
        for rec in load_events(jsonl_path):
            _migrate_cv_tailor_fields(rec)
            key = {
                "ts": rec.get("ts"),
                "job_id": rec.get("job_id"),
                "cv_tailor_run_id": rec.get("cv_tailor_run_id"),
            }
            if _row_exists(conn, "cv_tailor_links", key):
                continue
            insert_cv_tailor_link(conn, rec)
            inserted += 1
    return inserted


def backfill_all(db_path: str | None = None) -> dict[str, int]:
    """Init the DB then backfill all three sinks. Returns per-table insert counts."""
    init_db()
    return {
        "activity_log": backfill_activity_log(db_path=db_path),
        "annotations": backfill_annotations(db_path=db_path),
        "cv_tailor_links": backfill_cv_tailor_links(db_path=db_path),
    }


def main(argv: list[str] | None = None) -> int:
    counts = backfill_all()
    for table, n in counts.items():
        print(f"{table}: inserted {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
