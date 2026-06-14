"""Tests for cli/db_migrate.py — JSONL -> SQLite backfill (Phase 6.5 Step 2).

Every test points JR_DB_PATH at a tmp DB and writes its own tmp JSONL fixtures, so
nothing touches the real corpus.
"""

from __future__ import annotations

import json

import pytest

import cli.db as db
import cli.db_migrate as migrate


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("JR_DB_PATH", str(tmp_path / "test.db"))
    return tmp_path


def _write_jsonl(path, records: list[dict]) -> str:
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return str(path)


# --- activity_log --------------------------------------------------------------

def test_backfill_activity_log_inserts_all_rows(tmp_db):
    path = _write_jsonl(tmp_db / "activity_log.jsonl", [
        {"v": 1, "ts": "2026-06-10T00:00:00Z", "job_id": "sha256:a", "event": "status", "value": "applied", "notes": ""},
        {"v": 1, "ts": "2026-06-11T00:00:00Z", "job_id": "sha256:a", "event": "note", "value": None, "notes": "called back"},
        {"v": 1, "ts": "2026-06-12T00:00:00Z", "job_id": "sha256:b", "event": "fit_override", "value": "good_fit", "notes": "looks great"},
    ])
    assert migrate.backfill_activity_log(path) == 3
    with db.get_db() as conn:
        rows = conn.execute("SELECT * FROM activity_log ORDER BY ts").fetchall()
    assert [r["event"] for r in rows] == ["status", "note", "fit_override"]
    assert rows[0]["value"] == "applied"
    assert rows[1]["value"] is None              # note carries null value
    assert rows[2]["notes"] == "looks great"


def test_backfill_idempotent(tmp_db):
    path = _write_jsonl(tmp_db / "activity_log.jsonl", [
        {"v": 1, "ts": "2026-06-10T00:00:00Z", "job_id": "sha256:a", "event": "status", "value": "applied", "notes": ""},
    ])
    assert migrate.backfill_activity_log(path) == 1
    assert migrate.backfill_activity_log(path) == 0   # second run is a no-op
    with db.get_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM activity_log").fetchone()[0] == 1


def test_backfill_activity_log_keeps_distinct_same_key_different_value(tmp_db):
    # Two events sharing ts+job+event but differing on value are NOT collapsed.
    path = _write_jsonl(tmp_db / "activity_log.jsonl", [
        {"v": 1, "ts": "2026-06-10T00:00:00Z", "job_id": "sha256:a", "event": "status", "value": "applied", "notes": ""},
        {"v": 1, "ts": "2026-06-10T00:00:00Z", "job_id": "sha256:a", "event": "status", "value": "interviewing", "notes": ""},
    ])
    assert migrate.backfill_activity_log(path) == 2


# --- annotations ---------------------------------------------------------------

def test_backfill_annotations_inserts_and_encodes(tmp_db):
    path = _write_jsonl(tmp_db / "annotations.jsonl", [
        {"v": 1, "ts": "2026-06-10T00:00:00Z", "job_id": "sha256:a", "annotation_type": "extraction_error",
         "field": "domain", "observed": ["X"], "expected": ["Y", "Z"], "reason": "wrong",
         "scorer_label": "weak_fit", "scorer_fit_score": 4},
    ])
    assert migrate.backfill_annotations(path) == 1
    with db.get_db() as conn:
        row = conn.execute("SELECT * FROM annotations").fetchone()
    assert json.loads(row["observed"]) == ["X"]
    assert json.loads(row["expected"]) == ["Y", "Z"]
    assert row["scorer_fit_score"] == 4


def test_backfill_annotations_duplicate_constraint(tmp_db):
    # Two identical rows in the JSONL (incl. field=null) collapse to one via INSERT OR IGNORE.
    rec = {"v": 1, "ts": "2026-06-10T00:00:00Z", "job_id": "sha256:a", "annotation_type": "rejection_reason",
           "field": None, "observed": None, "expected": None, "reason": "compensation_below_range",
           "scorer_label": "good_fit", "scorer_fit_score": 8}
    path = _write_jsonl(tmp_db / "annotations.jsonl", [rec, dict(rec)])
    assert migrate.backfill_annotations(path) == 1
    assert migrate.backfill_annotations(path) == 0
    with db.get_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM annotations").fetchone()[0] == 1


# --- cv_tailor_links -----------------------------------------------------------

def test_backfill_cv_tailor_links_fields_correct(tmp_db):
    path = _write_jsonl(tmp_db / "cv_tailor_links.jsonl", [
        {"v": 1, "ts": "2026-06-10T00:00:00Z", "job_id": "sha256:a", "cv_tailor_run_id": "run-1",
         "fit_score": 0.8, "coverage_score": 0.6, "cv_quality_score": 7.5,
         "cvcm_enabled": True, "tailoring_mode": "full", "output_link": "http://x", "notes": "", "source": "manual"},
    ])
    assert migrate.backfill_cv_tailor_links(path) == 1
    with db.get_db() as conn:
        row = conn.execute("SELECT * FROM cv_tailor_links").fetchone()
    assert row["fit_score"] == 0.8
    assert row["coverage_score"] == 0.6
    assert row["cv_quality_score"] == 7.5
    assert row["cvcm_enabled"] == 1          # bool -> int
    assert row["tailoring_mode"] == "full"
    assert row["source"] == "manual"


def test_backfill_cv_tailor_links_migrates_old_fields(tmp_db):
    # Old schema: cv_tailor_score + grounding_score -> fit_score, grounding dropped (deviation 43).
    path = _write_jsonl(tmp_db / "cv_tailor_links.jsonl", [
        {"v": 1, "ts": "2026-06-01T00:00:00Z", "job_id": "sha256:a", "cv_tailor_run_id": "run-0",
         "cv_tailor_score": 0.9, "grounding_score": 0.5, "source": "manual"},
    ])
    assert migrate.backfill_cv_tailor_links(path) == 1
    with db.get_db() as conn:
        row = conn.execute("SELECT * FROM cv_tailor_links").fetchone()
    assert row["fit_score"] == 0.9
    assert "grounding_score" not in row.keys()


def test_backfill_cv_tailor_links_preserves_null_notes(tmp_db):
    # The cv-tailor callback posts notes=null; the read model preserves None. Coercing
    # None -> '' here would diverge from JSONL in --source both (regression guard).
    path = _write_jsonl(tmp_db / "cv_tailor_links.jsonl", [
        {"v": 1, "ts": "2026-06-12T00:00:00Z", "job_id": "sha256:a", "cv_tailor_run_id": "run-1",
         "fit_score": 0.4, "notes": None, "source": "cv_tailor_api"},
    ])
    assert migrate.backfill_cv_tailor_links(path) == 1
    from cli.db import get_db, load_cv_tailor_links_sqlite
    conn = get_db()
    try:
        row = conn.execute("SELECT notes FROM cv_tailor_links").fetchone()
        assert row["notes"] is None                      # stored as NULL, not ''
        link = load_cv_tailor_links_sqlite(conn)["sha256:a"]
    finally:
        conn.close()
    assert link["notes"] is None
    assert link["source"] == "cv_tailor_api"


def test_backfill_cv_tailor_links_idempotent(tmp_db):
    path = _write_jsonl(tmp_db / "cv_tailor_links.jsonl", [
        {"v": 1, "ts": "2026-06-10T00:00:00Z", "job_id": "sha256:a", "cv_tailor_run_id": "run-1", "fit_score": 0.8},
    ])
    assert migrate.backfill_cv_tailor_links(path) == 1
    assert migrate.backfill_cv_tailor_links(path) == 0


# --- missing files -------------------------------------------------------------

def test_backfill_missing_file_is_noop(tmp_db):
    assert migrate.backfill_activity_log(str(tmp_db / "nope.jsonl")) == 0
    assert migrate.backfill_annotations(str(tmp_db / "nope.jsonl")) == 0
    assert migrate.backfill_cv_tailor_links(str(tmp_db / "nope.jsonl")) == 0
