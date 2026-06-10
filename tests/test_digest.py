"""Tests for digest.py — the morning review tool (Phase 4, SPEC §8.2).

Covers the pure core (since resolution, row build, min-fit + tracked filter,
table/markdown render) and cmd_digest end-to-end with an injected clock + IO
paths, so nothing here writes to the real corpus or depends on wall-clock time.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

import cli.digest as digest
from models.record import ApplicationRecord

from tests.factories import make_record


# --- fixtures ------------------------------------------------------------------

def _now_dt() -> datetime:
    return datetime(2026, 6, 10, 9, 0, 0, tzinfo=timezone.utc)


def _scored_line(job_id, *, fit=7, label="good_fit", priority=7, scored_at="2026-06-10T08:00:00Z") -> str:
    return ApplicationRecord(
        job_id=job_id,
        profile_version="1.2",
        scored_at=scored_at,
        fit_score=fit,
        fit_label=label,
        fit_label_reason="reason",
        requirement_gaps=[],
        blocking_constraints=[],
        priority_score=priority,
        application_status="new",
        notes="",
    ).to_jsonl()


def _write(path, lines: list[str]) -> str:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def _ev(job_id, kind, value, *, ts, notes="") -> dict:
    return {"v": 1, "ts": ts, "job_id": job_id, "event": kind, "value": value, "notes": notes}


# --- parse_since ---------------------------------------------------------------

def test_parse_since_yesterday():
    assert digest.parse_since("yesterday", _now_dt()) == "2026-06-09T09:00:00Z"


def test_parse_since_today():
    assert digest.parse_since("today", _now_dt()) == "2026-06-10T00:00:00Z"


def test_parse_since_iso_date_passthrough():
    assert digest.parse_since("2026-06-09", _now_dt()) == "2026-06-09"


def test_parse_since_rejects_garbage():
    with pytest.raises(ValueError):
        digest.parse_since("not-a-date", _now_dt())


# --- resolve_since -------------------------------------------------------------

def test_resolve_since_explicit_arg_wins():
    assert digest.resolve_since("2026-06-01", "2026-06-05T00:00:00Z", _now_dt()) == "2026-06-01"


def test_resolve_since_uses_cursor_when_no_arg():
    assert digest.resolve_since(None, "2026-06-05T00:00:00Z", _now_dt()) == "2026-06-05T00:00:00Z"


def test_resolve_since_falls_back_to_24h():
    assert digest.resolve_since(None, None, _now_dt()) == "2026-06-09T09:00:00Z"


# --- build_digest_rows ---------------------------------------------------------

def test_build_digest_rows_excludes_before_since():
    scores = {
        "j1": ApplicationRecord.from_jsonl(_scored_line("j1", scored_at="2026-06-10T08:00:00Z")),
        "j2": ApplicationRecord.from_jsonl(_scored_line("j2", scored_at="2026-06-08T08:00:00Z")),
    }
    jds = {"j1": make_record(id="j1"), "j2": make_record(id="j2")}
    rows = digest.build_digest_rows(scores, jds, {}, {}, since="2026-06-09T00:00:00Z")
    assert [r["job_id"] for r in rows] == ["j1"]


def test_build_digest_rows_joins_company_title_location_url():
    jd = make_record(id="j1", source_url="http://x/1", company="Figma")
    scores = {"j1": ApplicationRecord.from_jsonl(_scored_line("j1"))}
    metas = {"http://x/1": {"source_url": "http://x/1", "title": "Solutions Consultant", "location_str": "London"}}
    row = digest.build_digest_rows(scores, {"j1": jd}, metas, {}, since="2026-06-01")[0]
    assert row["company"] == "Figma"
    assert row["title"] == "Solutions Consultant"
    assert row["location"] == "London"
    assert row["source_url"] == "http://x/1"


def test_build_digest_rows_location_falls_back_to_jd():
    # No sidecar meta → location comes from the JDRecord (base factory = "Remote").
    jd = make_record(id="j1", source_url="http://x/1")
    scores = {"j1": ApplicationRecord.from_jsonl(_scored_line("j1"))}
    row = digest.build_digest_rows(scores, {"j1": jd}, {}, {}, since="2026-06-01")[0]
    assert row["location"] == "Remote"


# --- filter_digest -------------------------------------------------------------

def _rows():
    return [
        {"job_id": "a", "fit_score": 5, "status": "new", "priority_score": 5, "title": "A"},
        {"job_id": "b", "fit_score": 8, "status": "new", "priority_score": 8, "title": "B"},
        {"job_id": "c", "fit_score": 9, "status": "applied", "priority_score": 9, "title": "C"},
    ]


def test_filter_digest_min_fit():
    assert [r["job_id"] for r in digest.filter_digest(_rows(), min_fit=6)] == ["b"]


def test_filter_digest_excludes_tracked_by_default():
    # c is fit 9 but already 'applied' → excluded; only new b survives min-fit 6
    assert [r["job_id"] for r in digest.filter_digest(_rows(), min_fit=6)] == ["b"]


def test_filter_digest_all_includes_tracked():
    assert {r["job_id"] for r in digest.filter_digest(_rows(), min_fit=6, include_tracked=True)} == {"b", "c"}


# --- format ---------------------------------------------------------------------

def test_format_markdown_has_table_and_summary():
    rows = [{"priority_score": 8, "fit_score": 8, "fit_label": "strong_fit", "company": "Figma",
             "title": "Solutions Consultant", "location": "London", "source_url": "http://x/1"}]
    md = digest.format_markdown(rows, since="2026-06-09", generated="2026-06-10T09:00:00Z")
    assert "1 new role(s) since 2026-06-09" in md
    assert "| Pri | Fit | Label | Company | Role | Location | Source |" in md
    assert "[link](http://x/1)" in md


def test_format_table_empty():
    assert digest.format_table([]) == "(no new roles)"


# --- cmd_digest (end-to-end with temp corpus) ----------------------------------

def _corpus(tmp_path):
    scored = _write(tmp_path / "scored.jsonl", [
        _scored_line("sha256:j1", fit=8, label="strong_fit", priority=8, scored_at="2026-06-10T08:00:00Z"),
        _scored_line("sha256:j2", fit=5, label="stretch", priority=5, scored_at="2026-06-10T08:00:00Z"),
        _scored_line("sha256:old", fit=9, label="strong_fit", priority=9, scored_at="2026-06-01T08:00:00Z"),
    ])
    jd1 = make_record(id="sha256:j1", source_url="http://x/1", company="Figma")
    jd2 = make_record(id="sha256:j2", source_url="http://x/2", company="Mistral")
    jdo = make_record(id="sha256:old", source_url="http://x/3", company="Stripe")
    validated = _write(tmp_path / "validated.jsonl", [jd1.to_jsonl(), jd2.to_jsonl(), jdo.to_jsonl()])
    metap = tmp_path / "meta.jsonl"
    metap.write_text(
        json.dumps({"source_url": "http://x/1", "title": "Solutions Consultant", "location_str": "London"}) + "\n",
        encoding="utf-8",
    )
    return scored, validated, str(metap)


def test_cmd_digest_default_window_and_minfit(tmp_path):
    scored, validated, metap = _corpus(tmp_path)
    logp = str(tmp_path / "log.jsonl")
    cursor = str(tmp_path / ".digest_last_run")
    msgs: list[str] = []
    rc = digest.cmd_digest(
        ["--scored", scored, "--validated", validated, "--meta", metap, "--log", logp, "--cursor", cursor],
        now=_now_dt, out=lambda *a: msgs.append(" ".join(str(x) for x in a)),
    )
    assert rc == 0
    table = "\n".join(msgs)
    # cursor absent → 24h window from 2026-06-10T09 → since 2026-06-09T09; j1/j2 in, old out.
    # min-fit 6 default → only j1 (fit 8); j2 (fit 5) filtered.
    assert "1 new role(s) since 2026-06-09T09:00:00Z" in table
    assert "Solutions Consultant" in table
    assert "Stripe" not in table  # scored before the window
    # default run advances the cursor to run start
    assert digest.read_cursor(cursor) == "2026-06-10T09:00:00Z"


def test_cmd_digest_explicit_since_does_not_advance_cursor(tmp_path):
    scored, validated, metap = _corpus(tmp_path)
    logp = str(tmp_path / "log.jsonl")
    cursor = str(tmp_path / ".digest_last_run")
    digest.write_cursor(cursor, "2026-06-05T00:00:00Z")
    msgs: list[str] = []
    digest.cmd_digest(
        ["--since", "2026-06-09", "--scored", scored, "--validated", validated,
         "--meta", metap, "--log", logp, "--cursor", cursor],
        now=_now_dt, out=lambda *a: msgs.append(" ".join(str(x) for x in a)),
    )
    assert "since 2026-06-09" in "\n".join(msgs)
    assert digest.read_cursor(cursor) == "2026-06-05T00:00:00Z"  # unchanged


def test_cmd_digest_excludes_already_tracked(tmp_path):
    scored, validated, metap = _corpus(tmp_path)
    # j1 already applied → excluded by default
    logp = _write(tmp_path / "log.jsonl", [json.dumps(_ev("sha256:j1", "status", "applied", ts="2026-06-10T08:30:00Z"))])
    cursor = str(tmp_path / ".digest_last_run")
    msgs: list[str] = []
    digest.cmd_digest(
        ["--scored", scored, "--validated", validated, "--meta", metap, "--log", logp, "--cursor", cursor],
        now=_now_dt, out=lambda *a: msgs.append(" ".join(str(x) for x in a)),
    )
    assert "0 new role(s)" in "\n".join(msgs)


def test_cmd_digest_all_includes_tracked(tmp_path):
    scored, validated, metap = _corpus(tmp_path)
    logp = _write(tmp_path / "log.jsonl", [json.dumps(_ev("sha256:j1", "status", "applied", ts="2026-06-10T08:30:00Z"))])
    cursor = str(tmp_path / ".digest_last_run")
    msgs: list[str] = []
    digest.cmd_digest(
        ["--all", "--scored", scored, "--validated", validated, "--meta", metap, "--log", logp, "--cursor", cursor],
        now=_now_dt, out=lambda *a: msgs.append(" ".join(str(x) for x in a)),
    )
    assert "1 new role(s)" in "\n".join(msgs)  # j1 back in


def test_cmd_digest_export_writes_file(tmp_path):
    scored, validated, metap = _corpus(tmp_path)
    logp = str(tmp_path / "log.jsonl")
    cursor = str(tmp_path / ".digest_last_run")
    export_dir = tmp_path / "out"
    msgs: list[str] = []
    digest.cmd_digest(
        ["--export", "--export-dir", str(export_dir), "--scored", scored, "--validated", validated,
         "--meta", metap, "--log", logp, "--cursor", cursor],
        now=_now_dt, out=lambda *a: msgs.append(" ".join(str(x) for x in a)),
    )
    written = export_dir / "digest_20260610.md"
    assert written.exists()
    body = written.read_text(encoding="utf-8")
    assert "Job Radar digest" in body and "Solutions Consultant" in body


def test_cmd_digest_rejects_bad_since(tmp_path):
    scored, validated, metap = _corpus(tmp_path)
    with pytest.raises(SystemExit):
        digest.cmd_digest(
            ["--since", "garbage", "--scored", scored, "--validated", validated, "--meta", metap,
             "--log", str(tmp_path / "log.jsonl"), "--cursor", str(tmp_path / ".cur")],
            now=_now_dt, out=lambda *_: None,
        )
