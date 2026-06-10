"""Tests for track.py — the Job Tracker (Phase 3, SPEC §7.4).

Covers the pure core (event build, projection, join, derive, filter/sort) and
the two commands with injected IO paths + clock, so nothing here writes to the
real corpus or depends on wall-clock time.
"""

from __future__ import annotations

import json

import pytest

import cli.track as track
from models.record import SCHEMA_VERSION, ApplicationRecord

from tests.factories import make_record


# --- fixtures ------------------------------------------------------------------

def _scored_line(job_id: str, *, fit=7, label="good_fit", priority=7, scored_at="2026-06-09T00:00:00Z") -> str:
    rec = ApplicationRecord(
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
    )
    return rec.to_jsonl()


def _write(path, lines: list[str]) -> str:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def _ev(job_id, kind, value, *, ts, notes="") -> dict:
    return {"v": 1, "ts": ts, "job_id": job_id, "event": kind, "value": value, "notes": notes}


# --- build_event ---------------------------------------------------------------

def test_build_event_valid():
    ev = track.build_event("sha256:a", event="status", value="applied", notes="hi", ts="2026-06-10T00:00:00Z")
    assert ev["event"] == "status" and ev["value"] == "applied" and ev["notes"] == "hi"
    assert ev["v"] == 1


def test_build_event_rejects_bad_value():
    with pytest.raises(ValueError):
        track.build_event("sha256:a", event="status", value="nonsense", notes="", ts="2026-06-10T00:00:00Z")


# --- transition_warning --------------------------------------------------------

@pytest.mark.parametrize(
    "current,new,warns",
    [
        ("new", "review", False),          # single step forward
        ("applied", "interviewing", False),
        ("new", "applied", True),          # skips stages
        ("interviewing", "shortlisted", True),  # backward
        ("applied", "rejected", False),    # terminal from anywhere
        ("new", "archived", False),        # terminal from anywhere
        ("applied", "applied", False),     # no-op
    ],
)
def test_transition_warning(current, new, warns):
    assert (track.transition_warning(current, new) is not None) == warns


# --- project -------------------------------------------------------------------

def test_project_default_state_for_unknown_job():
    assert track.project([]) == {}


def test_project_latest_status_and_outcome_and_notes():
    events = [
        _ev("j1", "status", "review", ts="2026-06-01T00:00:00Z", notes="first"),
        _ev("j1", "status", "applied", ts="2026-06-03T00:00:00Z", notes=""),
        _ev("j1", "status", "interviewing", ts="2026-06-05T00:00:00Z", notes="R1"),
        _ev("j1", "outcome", "rejected_interview", ts="2026-06-09T00:00:00Z"),
    ]
    state = track.project(events)["j1"]
    assert state["status"] == "interviewing"
    assert state["outcome"] == "rejected_interview"
    assert state["application_date"] == "2026-06-03"  # earliest 'applied'
    assert state["notes"] == "R1"  # latest non-empty note


def test_project_folds_in_ts_order_even_if_log_is_unordered():
    events = [
        _ev("j1", "status", "interviewing", ts="2026-06-05T00:00:00Z"),
        _ev("j1", "status", "review", ts="2026-06-01T00:00:00Z"),
    ]
    assert track.project(events)["j1"]["status"] == "interviewing"


def test_project_application_date_is_earliest_applied():
    events = [
        _ev("j1", "status", "applied", ts="2026-06-03T00:00:00Z"),
        _ev("j1", "status", "rejected", ts="2026-06-08T00:00:00Z"),
        _ev("j1", "status", "applied", ts="2026-06-10T00:00:00Z"),  # re-applied later
    ]
    assert track.project(events)["j1"]["application_date"] == "2026-06-03"


# --- derive_location_workable --------------------------------------------------

@pytest.mark.parametrize(
    "meta,expected",
    [
        (None, "unknown"),
        ({"is_remote": True}, "yes"),
        ({"location_str": "Remote - EMEA"}, "yes"),
        ({"location_str": "London, United Kingdom"}, "yes"),
        ({"location_str": "McLean, Virginia"}, "no"),
        ({"location_str": ""}, "unknown"),
    ],
)
def test_derive_location_workable(meta, expected):
    assert track.derive_location_workable(meta) == expected


# --- build_rows / join ---------------------------------------------------------

def test_build_rows_joins_score_jd_meta_and_workflow():
    jd = make_record(id="sha256:j1", source_url="http://x/1", company="Figma")
    scores = {"sha256:j1": ApplicationRecord.from_jsonl(_scored_line("sha256:j1", fit=8, label="strong_fit", priority=8))}
    jds = {"sha256:j1": jd}
    metas = {"http://x/1": {"source_url": "http://x/1", "title": "Solutions Consultant", "location_str": "London"}}
    workflow = track.project([_ev("sha256:j1", "status", "applied", ts="2026-06-10T00:00:00Z")])

    rows = track.build_rows(scores, jds, metas, workflow)
    assert len(rows) == 1
    row = rows[0]
    assert row["title"] == "Solutions Consultant"
    assert row["company"] == "Figma"
    assert row["fit_score"] == 8 and row["fit_label"] == "strong_fit"
    assert row["status"] == "applied"
    assert row["location_workable"] == "yes"


def test_build_rows_title_falls_back_to_raw_text_first_line_without_meta():
    jd = make_record(id="sha256:j2", source_url="http://x/2", raw_text="Staff Engineer\nWe are hiring...")
    scores = {"sha256:j2": ApplicationRecord.from_jsonl(_scored_line("sha256:j2"))}
    rows = track.build_rows(scores, {"sha256:j2": jd}, {}, {})
    assert rows[0]["title"] == "Staff Engineer"
    assert rows[0]["status"] == "new"  # no workflow events → baseline


def test_title_override_wins_over_sidecar_and_raw_text():
    jd = make_record(id="sha256:j1", source_url="http://x/1", raw_text="Ugly first line")
    scores = {"sha256:j1": ApplicationRecord.from_jsonl(_scored_line("sha256:j1"))}
    metas = {"http://x/1": {"source_url": "http://x/1", "title": "Sidecar Title"}}
    # override beats the sidecar
    workflow = track.project([_ev("sha256:j1", "title", "Human Title", ts="2026-06-10T00:00:00Z")])
    assert track.build_rows(scores, {"sha256:j1": jd}, metas, workflow)[0]["title"] == "Human Title"


def test_project_keeps_latest_title_override():
    events = [
        _ev("j1", "title", "First", ts="2026-06-01T00:00:00Z"),
        _ev("j1", "title", "Second", ts="2026-06-05T00:00:00Z"),
    ]
    assert track.project(events)["j1"]["title_override"] == "Second"


# --- filter / sort -------------------------------------------------------------

def _rows():
    return [
        {"job_id": "a", "title": "A", "company": "C", "fit_score": 5, "fit_label": "stretch",
         "priority_score": 5, "status": "new", "outcome": None, "application_date": None,
         "notes": "", "location_workable": "yes", "blocking_constraints": []},
        {"job_id": "b", "title": "B", "company": "C", "fit_score": 8, "fit_label": "strong_fit",
         "priority_score": 9, "status": "applied", "outcome": None, "application_date": None,
         "notes": "", "location_workable": "no", "blocking_constraints": []},
    ]


def test_filter_rows_by_status_minfit_location():
    rows = _rows()
    assert [r["job_id"] for r in track.filter_rows(rows, status="applied")] == ["b"]
    assert [r["job_id"] for r in track.filter_rows(rows, min_fit=6)] == ["b"]
    assert [r["job_id"] for r in track.filter_rows(rows, location_workable="yes")] == ["a"]


def test_sort_rows_priority_then_fit():
    assert [r["job_id"] for r in track.sort_rows(_rows())] == ["b", "a"]


# --- load_scores ---------------------------------------------------------------

def test_load_scores_keeps_latest_per_job_id(tmp_path):
    old = _write(tmp_path / "scored_1.jsonl", [_scored_line("j1", fit=4, scored_at="2026-06-01T00:00:00Z")])
    new = _write(tmp_path / "scored_2.jsonl", [_scored_line("j1", fit=9, scored_at="2026-06-09T00:00:00Z")])
    scores = track.load_scores(str(tmp_path / "scored_*.jsonl"))
    assert scores["j1"].fit_score == 9  # most recent scored_at wins


# --- cmd_update ----------------------------------------------------------------

def test_cmd_update_appends_status_event(tmp_path):
    scored = _write(tmp_path / "scored.jsonl", [_scored_line("sha256:j1")])
    logp = str(tmp_path / "activity_log.jsonl")
    rc = track.cmd_update(
        ["--job-id", "sha256:j1", "--status", "applied", "--notes", "referral", "--log", logp, "--scored", scored],
        now=lambda: "2026-06-10T12:00:00Z",
        out=lambda *_: None,
    )
    assert rc == 0
    events = track.load_events(logp)
    assert len(events) == 1
    assert events[0]["event"] == "status" and events[0]["value"] == "applied"
    assert events[0]["notes"] == "referral" and events[0]["ts"] == "2026-06-10T12:00:00Z"


def test_cmd_update_rejects_unknown_job_id(tmp_path):
    scored = _write(tmp_path / "scored.jsonl", [_scored_line("sha256:known")])
    logp = str(tmp_path / "activity_log.jsonl")
    msgs: list[str] = []
    rc = track.cmd_update(
        ["--job-id", "sha256:typo", "--status", "applied", "--log", logp, "--scored", scored],
        now=lambda: "t", out=msgs.append,
    )
    assert rc == 1
    assert any("not found" in m for m in msgs)
    assert track.load_events(logp) == []  # nothing written


def test_cmd_update_force_logs_unknown_job_id(tmp_path):
    scored = _write(tmp_path / "scored.jsonl", [_scored_line("sha256:known")])
    logp = str(tmp_path / "activity_log.jsonl")
    rc = track.cmd_update(
        ["--job-id", "sha256:new", "--status", "review", "--force", "--log", logp, "--scored", scored],
        now=lambda: "t", out=lambda *_: None,
    )
    assert rc == 0 and len(track.load_events(logp)) == 1


def test_cmd_update_warns_on_odd_transition(tmp_path):
    scored = _write(tmp_path / "scored.jsonl", [_scored_line("sha256:j1")])
    logp = str(tmp_path / "activity_log.jsonl")
    msgs: list[str] = []
    track.cmd_update(
        ["--job-id", "sha256:j1", "--status", "offer", "--log", logp, "--scored", scored],
        now=lambda: "t", out=msgs.append,
    )
    assert any("skips stage" in m for m in msgs)  # new -> offer skips stages, but still logs


def test_cmd_update_requires_something_to_record(tmp_path):
    scored = _write(tmp_path / "scored.jsonl", [_scored_line("sha256:j1")])
    with pytest.raises(SystemExit):
        track.cmd_update(["--job-id", "sha256:j1", "--scored", scored], now=lambda: "t", out=lambda *_: None)


def test_cmd_update_title_override_event(tmp_path):
    scored = _write(tmp_path / "scored.jsonl", [_scored_line("sha256:j1")])
    logp = str(tmp_path / "activity_log.jsonl")
    track.cmd_update(
        ["--job-id", "sha256:j1", "--title", "Solutions Engineer", "--log", logp, "--scored", scored],
        now=lambda: "t", out=lambda *_: None,
    )
    events = track.load_events(logp)
    assert len(events) == 1 and events[0]["event"] == "title" and events[0]["value"] == "Solutions Engineer"


def test_cmd_update_status_and_title_in_one_call(tmp_path):
    scored = _write(tmp_path / "scored.jsonl", [_scored_line("sha256:j1")])
    logp = str(tmp_path / "activity_log.jsonl")
    track.cmd_update(
        ["--job-id", "sha256:j1", "--status", "applied", "--title", "SE", "--notes", "n",
         "--log", logp, "--scored", scored],
        now=lambda: "t", out=lambda *_: None,
    )
    events = track.load_events(logp)
    assert [e["event"] for e in events] == ["status", "title"]
    assert events[0]["notes"] == "n" and events[1]["notes"] == ""  # notes attach to first only


def test_cmd_update_outcome_only(tmp_path):
    scored = _write(tmp_path / "scored.jsonl", [_scored_line("sha256:j1")])
    logp = str(tmp_path / "activity_log.jsonl")
    track.cmd_update(
        ["--job-id", "sha256:j1", "--outcome", "rejected_post_screen", "--log", logp, "--scored", scored],
        now=lambda: "t", out=lambda *_: None,
    )
    events = track.load_events(logp)
    assert len(events) == 1 and events[0]["event"] == "outcome"


# --- cmd_list (end-to-end with temp corpus) ------------------------------------

def test_cmd_list_renders_joined_state(tmp_path):
    scored = _write(tmp_path / "scored.jsonl", [
        _scored_line("sha256:j1", fit=8, label="strong_fit", priority=8),
        _scored_line("sha256:j2", fit=5, label="stretch", priority=5),
    ])
    jd1 = make_record(id="sha256:j1", source_url="http://x/1", company="Figma")
    jd2 = make_record(id="sha256:j2", source_url="http://x/2", company="Mistral")
    validated = _write(tmp_path / "validated.jsonl", [jd1.to_jsonl(), jd2.to_jsonl()])
    metap = tmp_path / "meta.jsonl"
    metap.write_text(
        json.dumps({"source_url": "http://x/1", "title": "Solutions Consultant", "location_str": "London"}) + "\n"
        + json.dumps({"source_url": "http://x/2", "title": "AI Deployment Strategist", "location_str": "Remote"}) + "\n",
        encoding="utf-8",
    )
    logp = _write(tmp_path / "log.jsonl", [json.dumps(_ev("sha256:j1", "status", "applied", ts="2026-06-10T00:00:00Z"))])

    msgs: list[str] = []
    rc = track.cmd_list(
        ["--scored", scored, "--validated", validated, "--meta", str(metap), "--log", logp],
        out=lambda *a: msgs.append(" ".join(str(x) for x in a)),
    )
    assert rc == 0
    table = "\n".join(msgs)
    assert "Solutions Consultant" in table and "applied" in table
    assert "Shown 2 of 2" in table


def test_cmd_list_status_filter(tmp_path):
    scored = _write(tmp_path / "scored.jsonl", [_scored_line("sha256:j1"), _scored_line("sha256:j2")])
    logp = _write(tmp_path / "log.jsonl", [json.dumps(_ev("sha256:j1", "status", "shortlisted", ts="2026-06-10T00:00:00Z"))])
    msgs: list[str] = []
    track.cmd_list(
        ["--scored", scored, "--validated", str(tmp_path / "none_*.jsonl"),
         "--meta", str(tmp_path / "none_*.jsonl"), "--log", logp, "--status", "shortlisted"],
        out=lambda *a: msgs.append(" ".join(str(x) for x in a)),
    )
    assert "Shown 1 of 2" in "\n".join(msgs)
