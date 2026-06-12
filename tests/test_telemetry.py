"""Tests for cli.telemetry + the pipeline trace-row builders.

The suite runs with no LANGFUSE_PUBLIC_KEY (conftest pops it), so the langfuse SDK is
never imported and every recorder is a clean no-op — that contract is what these tests
pin. The row-builders (build_trace_rows / build_scoring_rows) are pure assembly and are
tested directly: they must produce the exact shape telemetry.record_* consumes.
"""

import os

import pytest

import cli.label as label_cli
import cli.score as score_cli
from cli import telemetry
from pipeline import label
from scoring.profile import load_profile
from tests.factories import make_record


# --- is_enabled / no-op contract -------------------------------------------


def test_disabled_without_key(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    assert telemetry.is_enabled() is False


def test_enabled_with_key(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    assert telemetry.is_enabled() is True


def test_recorders_are_noop_when_disabled(monkeypatch):
    """With no key, the recorders must return None WITHOUT importing langfuse."""
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    assert telemetry.record_extraction_batch("batch_1", [{"job_id": "x"}], {"date": "20260612"}) is None
    assert telemetry.record_scoring_run("run_1", [{"job_id": "x"}], {"run_date": "t"}) is None
    telemetry.init_langfuse()   # also a no-op — must not raise
    telemetry.flush()           # also a no-op — must not raise


def test_debug_trace_disabled_shape(monkeypatch):
    """The debug probe returns the documented verdict dict and a null trace when disabled."""
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    info = telemetry.debug_trace()
    assert info == {
        "enabled": False,
        "host": info["host"],   # whatever the host resolves to
        "trace_id": None,
        "auth_check": None,
        "error": None,
    }


def test_resolved_host_precedence(monkeypatch):
    monkeypatch.setenv("LANGFUSE_BASE_URL", "http://internal:3000")
    monkeypatch.setenv("LANGFUSE_HOST", "https://public.example")
    assert telemetry._resolved_host() == "http://internal:3000"
    monkeypatch.delenv("LANGFUSE_BASE_URL")
    assert telemetry._resolved_host() == "https://public.example"


# --- build_trace_rows (extraction batch) -----------------------------------


def _ext_results(custom_ids_status):
    """Build label.download_results-shaped entries: [(custom_id, status), ...]."""
    out = []
    for cid, status in custom_ids_status:
        entry = {"custom_id": cid, "status": status}
        if status == "succeeded":
            entry["raw_text"] = '{"ok": true}'
            entry["usage"] = {"input": 100, "output": 50, "cache_read": 0, "cache_write": 0}
        else:
            entry["error"] = "overloaded"
        out.append(entry)
    return out


def test_build_trace_rows_shape_and_validation_flag():
    records = [make_record(id=f"sha256:{i}", company=f"Co{i}", source_url=f"u{i}") for i in range(2)]
    results = _ext_results([("rec-0", "succeeded"), ("rec-1", "errored")])
    labelled = [records[0]]   # only rec-0 survived merge

    rows = label_cli.build_trace_rows(records, results, labelled, meta_index={})

    assert [r["job_id"] for r in rows] == ["sha256:0", "sha256:1"]
    assert rows[0]["validated"] is True
    assert rows[1]["validated"] is False
    assert rows[0]["input_tokens"] == 100 and rows[0]["output_tokens"] == 50
    assert rows[0]["model"] == label.MODEL
    # The prompt is rebuilt with the same builder the batch used.
    assert rows[0]["prompt"] == label.build_user_content(records[0], None)
    assert rows[0]["completion"] == '{"ok": true}'
    assert rows[1]["completion"] == ""   # errored entries carry no raw_text -> default ""
    assert rows[1]["input_tokens"] == 0  # ...and no usage dict


def test_build_trace_rows_includes_meta_block():
    rec = make_record(id="sha256:m", company="MetaCo", source_url="https://x/m", raw_text="Body")
    results = _ext_results([("rec-0", "succeeded")])
    meta = {"https://x/m": {"title": "SE", "location_str": "London"}}
    rows = label_cli.build_trace_rows([rec], results, [rec], meta_index=meta)
    assert "[ATS METADATA]" in rows[0]["prompt"]


# --- build_scoring_rows (scoring run) --------------------------------------


def test_build_scoring_rows_shape():
    profile = load_profile("candidate_profile.yaml")
    jd = make_record(id="sha256:s", company="ScoreCo", raw_text="Director, Solutions Engineering")
    scored_at = "2026-06-12T00:00:00Z"
    from scoring.scorer import score

    rec = score(jd, profile, scored_at)
    rows = score_cli.build_scoring_rows([jd], [rec], profile)

    assert len(rows) == 1
    row = rows[0]
    assert row["job_id"] == "sha256:s"
    assert row["company"] == "ScoreCo"
    assert row["fit_label"] == rec.fit_label
    assert row["fit_score"] == rec.fit_score
    dims = {d["dimension"] for d in row["dimensions"]}
    assert dims == {"role", "domain", "technical_depth", "seniority", "location"}
    # Gate dimensions carry a non-positive penalty score; rationale names the gate outcome.
    gate = next(d for d in row["dimensions"] if d["dimension"] == "seniority")
    assert gate["score"] <= 0
    assert gate["rationale"].startswith("gate ")
