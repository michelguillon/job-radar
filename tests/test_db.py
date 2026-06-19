"""Tests for cli/db.py — SQLite schema + init (Phase 6.5 Step 1, SPEC_DB_MIGRATION §3).

Every test points JR_DB_PATH at a tmp file so nothing touches the real corpus DB.
"""

from __future__ import annotations

import sqlite3

import pytest

import cli.db as db

EXPECTED_TABLES = {"activity_log", "annotations", "cv_tailor_links", "schema_version"}


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setenv("JR_DB_PATH", str(path))
    return path


def _tables(conn) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r["name"] for r in rows}


def test_get_db_path_respects_env(tmp_db):
    assert db.get_db_path() == tmp_db


def test_init_db_creates_tables(tmp_db):
    db.init_db()
    with db.get_db() as conn:
        assert _tables(conn) >= EXPECTED_TABLES
        assert conn.execute("SELECT version FROM schema_version").fetchone()["version"] == 1


def test_init_db_creates_company_seeds_table(tmp_db):
    db.init_db()
    with db.get_db() as conn:
        assert "company_seeds" in _tables(conn)
        # The mutable reference table: confirm UPDATE works (unlike the append-only sinks).
        db.insert_company_seed(conn, {"name": "Acme", "ats": "greenhouse", "slug": "acme"})
        assert db.update_company_seed(conn, "Acme", {"fit_hypothesis": "high"})
        assert db.get_company_seed(conn, "Acme")["fit_hypothesis"] == "high"


def test_init_db_is_idempotent(tmp_db):
    db.init_db()
    with db.get_db() as conn:
        conn.execute(
            "INSERT INTO activity_log (ts, job_id, event, value) VALUES (?,?,?,?)",
            ("2026-06-13T00:00:00Z", "sha256:a", "status", "applied"),
        )
    # Second init must not raise and must not wipe data or duplicate schema_version.
    db.init_db()
    with db.get_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM activity_log").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0] == 1


def test_get_db_enables_wal(tmp_db):
    db.init_db()
    with db.get_db() as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"


def test_annotations_unique_constraint(tmp_db):
    db.init_db()
    row = ("2026-06-13T00:00:00Z", "sha256:a", "rejection_reason", None, "stale role")
    with db.get_db() as conn:
        conn.execute(
            "INSERT INTO annotations (ts, job_id, annotation_type, field, reason) VALUES (?,?,?,?,?)",
            row,
        )
    with pytest.raises(sqlite3.IntegrityError):
        with db.get_db() as conn:
            conn.execute(
                "INSERT INTO annotations (ts, job_id, annotation_type, field, reason) VALUES (?,?,?,?,?)",
                row,
            )


def test_main_init(tmp_db, capsys):
    assert db.main(["init"]) == 0
    assert tmp_db.exists()
