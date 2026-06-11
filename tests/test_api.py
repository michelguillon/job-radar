"""Tests for the Phase 6 FastAPI layer (job_radar_SPEC §10).

Every path is injected at tmp_path (via app.dependency_overrides) and JR_WRITE_KEY via
monkeypatch, so nothing here touches the real corpus or a real key. Covers: capabilities
matrix, unlock/lock, fail-closed 403 on every write endpoint, status/note/title append the
correct event (asserted through cli.track.load_events), unknown job_id → 404, transition
warning surfaced, annotation append + bad type, and the live activity-log overlay on
GET /api/index.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import cli.track as track
from api.main import app
from api.settings import Settings, get_settings
from models.record import ApplicationRecord

KEY = "owner-secret-key"


def _scored_line(job_id: str, *, fit=7, label="good_fit", priority=7, scored_at="2026-06-09T00:00:00Z") -> str:
    return ApplicationRecord(
        job_id=job_id, profile_version="1.2", scored_at=scored_at, fit_score=fit,
        fit_label=label, fit_label_reason="reason", requirement_gaps=[],
        blocking_constraints=[], priority_score=priority, application_status="new", notes="",
    ).to_jsonl()


@pytest.fixture
def settings(tmp_path) -> Settings:
    scored = tmp_path / "scored.jsonl"
    scored.write_text(_scored_line("sha256:j1") + "\n", encoding="utf-8")
    index = tmp_path / "index.json"
    index.write_text(json.dumps({
        "schema_version": "1.3", "jdrecord_schema_version": "1.2",
        "generated_at": "2026-06-09T00:00:00Z",
        "stats": {"total": 1},
        "records": [{
            "job_id": "sha256:j1", "company": "Acme", "title": "Solutions Engineer",
            "fit_score": 7, "fit_label": "good_fit", "scorer_fit_label": "good_fit",
            "scorer_fit_score": 7, "display_fit_label": "good_fit", "has_fit_override": False,
            "application_status": "new", "outcome": None, "application_date": None, "notes": "",
        }],
    }), encoding="utf-8")
    return Settings(
        log_path=str(tmp_path / "activity_log.jsonl"),
        scored_glob=str(scored),
        validated_glob=str(tmp_path / "validated_*.jsonl"),
        meta_glob=str(tmp_path / "meta_*.jsonl"),
        index_path=str(index),
        annotations_path=str(tmp_path / "annotations.jsonl"),
        cv_tailor_links_path=str(tmp_path / "cv_tailor_links.jsonl"),
    )


@pytest.fixture(autouse=True)
def _hermetic_cookie_env(monkeypatch):
    """Keep the suite independent of the ambient environment.

    The tests drive the unlock cookie over the TestClient's plain-http transport, which
    (like a browser) refuses to store a ``Secure`` cookie sent over http. A production
    ``.env`` with ``COOKIE_SECURE=true`` loaded into the container (e.g. ``docker compose
    run job-radar pytest`` on the server) would therefore drop the cookie and 403 every
    gated write. Pin it off so the unlock flow is exercised regardless of how pytest is run.
    """
    monkeypatch.delenv("COOKIE_SECURE", raising=False)


@pytest.fixture
def client(settings):
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as c:
        c.settings = settings  # stash for assertions
        yield c
    app.dependency_overrides.clear()


def _unlock(client) -> None:
    assert client.post("/api/unlock", json={"key": KEY}).status_code == 200


# --- capabilities matrix -------------------------------------------------------

def test_capabilities_not_configured(client, monkeypatch):
    monkeypatch.delenv("JR_WRITE_KEY", raising=False)
    caps = client.get("/api/capabilities").json()
    assert caps == {"write_configured": False, "write_unlocked": False}


def test_capabilities_configured_locked(client, monkeypatch):
    monkeypatch.setenv("JR_WRITE_KEY", KEY)
    caps = client.get("/api/capabilities").json()
    assert caps == {"write_configured": True, "write_unlocked": False}


def test_capabilities_unlocked(client, monkeypatch):
    monkeypatch.setenv("JR_WRITE_KEY", KEY)
    _unlock(client)
    caps = client.get("/api/capabilities").json()
    assert caps == {"write_configured": True, "write_unlocked": True}


# --- unlock / lock -------------------------------------------------------------

def test_unlock_wrong_key_401(client, monkeypatch):
    monkeypatch.setenv("JR_WRITE_KEY", KEY)
    assert client.post("/api/unlock", json={"key": "nope"}).status_code == 401


def test_unlock_not_configured_403(client, monkeypatch):
    monkeypatch.delenv("JR_WRITE_KEY", raising=False)
    assert client.post("/api/unlock", json={"key": KEY}).status_code == 403


def test_lock_clears_cookie(client, monkeypatch):
    monkeypatch.setenv("JR_WRITE_KEY", KEY)
    _unlock(client)
    client.post("/api/lock")
    assert client.get("/api/capabilities").json()["write_unlocked"] is False


# --- fail-closed: every write 403 without a cookie -----------------------------

@pytest.mark.parametrize("path,payload", [
    ("/api/status", {"job_id": "sha256:j1", "status": "shortlisted"}),
    ("/api/note", {"job_id": "sha256:j1", "text": "hi"}),
    ("/api/title", {"job_id": "sha256:j1", "title": "X"}),
    ("/api/annotations", {"job_id": "sha256:j1", "annotation_type": "domain_incorrect",
                          "field": "domain", "observed": [], "expected": [], "reason": "r"}),
])
def test_writes_403_without_cookie(client, monkeypatch, path, payload):
    monkeypatch.setenv("JR_WRITE_KEY", KEY)  # configured but this client never unlocks
    assert client.post(path, json=payload).status_code == 403


def test_writes_403_when_not_configured(client, monkeypatch):
    monkeypatch.delenv("JR_WRITE_KEY", raising=False)
    assert client.post("/api/status", json={"job_id": "sha256:j1", "status": "review"}).status_code == 403


# --- workflow writes append the correct event ----------------------------------

def test_status_appends_event(client, monkeypatch):
    monkeypatch.setenv("JR_WRITE_KEY", KEY)
    _unlock(client)
    r = client.post("/api/status", json={"job_id": "sha256:j1", "status": "shortlisted", "notes": "keen"})
    assert r.status_code == 200
    events = track.load_events(client.settings.log_path)
    assert len(events) == 1
    assert events[0]["event"] == "status"
    assert events[0]["value"] == "shortlisted"
    assert events[0]["notes"] == "keen"


def test_note_appends_note_event(client, monkeypatch):
    monkeypatch.setenv("JR_WRITE_KEY", KEY)
    _unlock(client)
    client.post("/api/note", json={"job_id": "sha256:j1", "text": "recruiter emailed"})
    events = track.load_events(client.settings.log_path)
    assert events[0]["event"] == "note"
    assert events[0]["value"] is None
    assert events[0]["notes"] == "recruiter emailed"


def test_title_appends_title_event(client, monkeypatch):
    monkeypatch.setenv("JR_WRITE_KEY", KEY)
    _unlock(client)
    client.post("/api/title", json={"job_id": "sha256:j1", "title": "Forward Deployed Engineer"})
    events = track.load_events(client.settings.log_path)
    assert events[0]["event"] == "title"
    assert events[0]["value"] == "Forward Deployed Engineer"


def test_outcome_appends_event(client, monkeypatch):
    monkeypatch.setenv("JR_WRITE_KEY", KEY)
    _unlock(client)
    r = client.post("/api/outcome", json={"job_id": "sha256:j1", "outcome": "rejected_interview", "notes": "no fit"})
    assert r.status_code == 200
    events = track.load_events(client.settings.log_path)
    assert events[0]["event"] == "outcome"
    assert events[0]["value"] == "rejected_interview"
    assert events[0]["notes"] == "no fit"


def test_outcome_invalid_value_422(client, monkeypatch):
    monkeypatch.setenv("JR_WRITE_KEY", KEY)
    _unlock(client)
    r = client.post("/api/outcome", json={"job_id": "sha256:j1", "outcome": "not_an_outcome"})
    assert r.status_code == 422


def test_outcome_403_without_cookie(client, monkeypatch):
    monkeypatch.setenv("JR_WRITE_KEY", KEY)
    assert client.post("/api/outcome", json={"job_id": "sha256:j1", "outcome": "withdrew"}).status_code == 403


def test_status_unknown_job_id_404(client, monkeypatch):
    monkeypatch.setenv("JR_WRITE_KEY", KEY)
    _unlock(client)
    r = client.post("/api/status", json={"job_id": "sha256:ghost", "status": "review"})
    assert r.status_code == 404


def test_status_surfaces_transition_warning(client, monkeypatch):
    monkeypatch.setenv("JR_WRITE_KEY", KEY)
    _unlock(client)
    # new -> offer skips stages → forgiving warning, still 200
    r = client.post("/api/status", json={"job_id": "sha256:j1", "status": "offer"})
    assert r.status_code == 200
    assert r.json()["warning"] is not None


def test_status_invalid_value_422(client, monkeypatch):
    monkeypatch.setenv("JR_WRITE_KEY", KEY)
    _unlock(client)
    r = client.post("/api/status", json={"job_id": "sha256:j1", "status": "bogus_status"})
    assert r.status_code == 422


# --- annotations ---------------------------------------------------------------

def test_annotation_appends_with_scorer_context(client, monkeypatch):
    monkeypatch.setenv("JR_WRITE_KEY", KEY)
    _unlock(client)
    r = client.post("/api/annotations", json={
        "job_id": "sha256:j1", "annotation_type": "domain_incorrect", "field": "domain",
        "observed": ["Enterprise Software"], "expected": [], "reason": "catch-all",
    })
    assert r.status_code == 200
    lines = track.load_events(client.settings.annotations_path)
    assert len(lines) == 1
    rec = lines[0]
    assert rec["annotation_type"] == "domain_incorrect"
    assert rec["scorer_label"] == "good_fit"   # captured from the scored corpus
    assert rec["scorer_fit_score"] == 7


def test_annotation_duplicate_409(client, monkeypatch):
    monkeypatch.setenv("JR_WRITE_KEY", KEY)
    _unlock(client)
    payload = {"job_id": "sha256:j1", "annotation_type": "domain_incorrect", "field": "domain",
               "observed": [], "expected": [], "reason": "catch-all"}
    assert client.post("/api/annotations", json=payload).status_code == 200
    # exact dup (same job_id + type + field + reason) → 409
    assert client.post("/api/annotations", json=payload).status_code == 409
    # a different reason is not a dup
    assert client.post("/api/annotations", json={**payload, "reason": "different"}).status_code == 200


def test_annotation_bad_type_422(client, monkeypatch):
    monkeypatch.setenv("JR_WRITE_KEY", KEY)
    _unlock(client)
    r = client.post("/api/annotations", json={
        "job_id": "sha256:j1", "annotation_type": "not_a_real_type", "field": "domain",
        "observed": [], "expected": [], "reason": "r",
    })
    assert r.status_code == 422


def test_rejection_reason_valid(client, monkeypatch):
    monkeypatch.setenv("JR_WRITE_KEY", KEY)
    _unlock(client)
    r = client.post("/api/annotations", json={
        "job_id": "sha256:j1", "annotation_type": "rejection_reason", "field": None,
        "observed": ["good_fit", "7"], "expected": [], "reason": "too_salesy",
    })
    assert r.status_code == 200
    rec = track.load_events(client.settings.annotations_path)[0]
    assert rec["annotation_type"] == "rejection_reason"
    assert rec["reason"] == "too_salesy"
    assert rec["field"] is None
    assert rec["scorer_label"] == "good_fit"  # captured server-side


def test_rejection_reason_invalid_reason(client, monkeypatch):
    monkeypatch.setenv("JR_WRITE_KEY", KEY)
    _unlock(client)
    r = client.post("/api/annotations", json={
        "job_id": "sha256:j1", "annotation_type": "rejection_reason", "field": None,
        "observed": [], "expected": [], "reason": "not_a_reason",
    })
    assert r.status_code == 422


def test_rejection_reason_duplicate(client, monkeypatch):
    monkeypatch.setenv("JR_WRITE_KEY", KEY)
    _unlock(client)
    payload = {"job_id": "sha256:j1", "annotation_type": "rejection_reason", "field": None,
               "observed": [], "expected": [], "reason": "too_salesy"}
    assert client.post("/api/annotations", json=payload).status_code == 200
    assert client.post("/api/annotations", json=payload).status_code == 409  # exact dup
    # a different reason for the same job is not a duplicate
    assert client.post("/api/annotations", json={**payload, "reason": "wrong_function"}).status_code == 200


def test_annotation_unknown_job_id_404(client, monkeypatch):
    monkeypatch.setenv("JR_WRITE_KEY", KEY)
    _unlock(client)
    r = client.post("/api/annotations", json={
        "job_id": "sha256:ghost", "annotation_type": "domain_incorrect", "field": "domain",
        "observed": [], "expected": [], "reason": "r",
    })
    assert r.status_code == 404


# --- fit override (Feature 1) --------------------------------------------------

def test_fit_override_appends_event(client, monkeypatch):
    monkeypatch.setenv("JR_WRITE_KEY", KEY)
    _unlock(client)
    r = client.post("/api/fit-override", json={"job_id": "sha256:j1", "fit_label": "stretch", "reason": "depth gap"})
    assert r.status_code == 200
    events = track.load_events(client.settings.log_path)
    assert events[0]["event"] == "fit_override"
    assert events[0]["value"] == "stretch"
    assert events[0]["notes"] == "depth gap"


def test_fit_override_invalid_label_422(client, monkeypatch):
    monkeypatch.setenv("JR_WRITE_KEY", KEY)
    _unlock(client)
    assert client.post("/api/fit-override", json={"job_id": "sha256:j1", "fit_label": "nonsense"}).status_code == 422


def test_fit_override_403_without_cookie(client, monkeypatch):
    monkeypatch.setenv("JR_WRITE_KEY", KEY)
    assert client.post("/api/fit-override", json={"job_id": "sha256:j1", "fit_label": "stretch"}).status_code == 403


def test_fit_override_unknown_job_404(client, monkeypatch):
    monkeypatch.setenv("JR_WRITE_KEY", KEY)
    _unlock(client)
    assert client.post("/api/fit-override", json={"job_id": "sha256:ghost", "fit_label": "stretch"}).status_code == 404


def test_index_overlays_fit_override_and_clear(client, monkeypatch):
    monkeypatch.setenv("JR_WRITE_KEY", KEY)
    _unlock(client)
    # the seeded index.json row scored good_fit; an override must show on reload (no re-export)
    client.post("/api/fit-override", json={"job_id": "sha256:j1", "fit_label": "stretch", "reason": "depth gap"})
    rec = client.get("/api/index").json()["records"][0]
    assert rec["scorer_fit_label"] == "good_fit"     # scorer preserved
    assert rec["user_fit_label"] == "stretch"
    assert rec["display_fit_label"] == "stretch" and rec["fit_label"] == "stretch"
    assert rec["has_fit_override"] is True
    # clearing reverts the display to the scorer value
    client.post("/api/fit-override", json={"job_id": "sha256:j1", "fit_label": None})
    rec = client.get("/api/index").json()["records"][0]
    assert rec["has_fit_override"] is False
    assert rec["display_fit_label"] == "good_fit" and rec["user_fit_label"] is None


def test_index_overlays_live_annotations(client, monkeypatch):
    monkeypatch.setenv("JR_WRITE_KEY", KEY)
    _unlock(client)
    client.post("/api/annotations", json={"job_id": "sha256:j1", "annotation_type": "domain_incorrect",
                                          "field": "domain", "observed": [], "expected": [], "reason": "over-tag"})
    rec = client.get("/api/index").json()["records"][0]
    assert rec["annotation_count"] == 1 and rec["has_annotations"] is True
    assert rec["annotations"][0]["annotation_type"] == "domain_incorrect"


# --- index: shape + live overlay -----------------------------------------------

def test_index_shape(client):
    body = client.get("/api/index").json()
    assert body["records"][0]["job_id"] == "sha256:j1"
    assert "stats" in body


def test_index_overlays_live_workflow(client, monkeypatch):
    monkeypatch.setenv("JR_WRITE_KEY", KEY)
    _unlock(client)
    # index.json was exported with status "new"; a write must show on reload without re-export
    client.post("/api/status", json={"job_id": "sha256:j1", "status": "applied"})
    rec = client.get("/api/index").json()["records"][0]
    assert rec["application_status"] == "applied"
    # application_date is derived from the (wall-clock) applied event ts → an ISO date
    assert rec["application_date"] and len(rec["application_date"]) == 10


def test_index_overlays_title_override(client, monkeypatch):
    monkeypatch.setenv("JR_WRITE_KEY", KEY)
    _unlock(client)
    client.post("/api/title", json={"job_id": "sha256:j1", "title": "Brand New Title"})
    rec = client.get("/api/index").json()["records"][0]
    assert rec["title"] == "Brand New Title"


# --- report: yield download ----------------------------------------------------

def test_yield_report_downloads(client, tmp_path, monkeypatch):
    """GET /api/report/yield is public, returns text/plain, and attaches as a .txt."""
    from dataclasses import replace
    from models.record import JDRecord
    from tests.factories import base_envelope

    # Validated JD for the scored job (company joins to a seed below).
    validated = tmp_path / "validated_20260609.jsonl"
    env = base_envelope()
    env.update(id="sha256:j1", company="Mistral AI")
    validated.write_text(JDRecord.from_dict(env).to_jsonl() + "\n", encoding="utf-8")

    seeds = tmp_path / "seeds.yaml"
    seeds.write_text("- {name: Mistral AI, ats: lever, slug: mistral, domain: frontier_ai, "
                     "fit_hypothesis: high, action: keep}\n", encoding="utf-8")
    stats = tmp_path / "stats.json"
    stats.write_text('[{"step": "label", "labelled": 10, "cost_usd": 0.3}]', encoding="utf-8")

    base = client.settings
    full = replace(base, validated_glob=str(validated), seeds_path=str(seeds), stats_path=str(stats))
    app.dependency_overrides[get_settings] = lambda: full

    res = client.get("/api/report/yield")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/plain")
    assert "attachment" in res.headers["content-disposition"]
    assert res.headers["content-disposition"].endswith('.txt"')
    assert "COMPANY YIELD REPORT" in res.text
    assert "Mistral AI" in res.text


# --- cv-tailor: POST results (gated) + GET job detail (public) ------------------

def test_cv_tailor_results_post_valid(client, monkeypatch):
    monkeypatch.setenv("JR_WRITE_KEY", KEY)
    _unlock(client)
    r = client.post("/api/cv-tailor-results", json={
        "job_id": "sha256:j1", "cv_tailor_run_id": "run_20260611_001",
        "cv_tailor_score": 0.72, "coverage_score": 0.81, "grounding_score": 0.96,
        "cvcm_enabled": True, "tailoring_mode": "full",
        "output_link": "https://cv-tailor.example/runs/run_20260611_001", "notes": "good",
    })
    assert r.status_code == 200
    links = track.load_events(client.settings.cv_tailor_links_path)
    assert len(links) == 1
    assert links[0]["cv_tailor_run_id"] == "run_20260611_001"
    assert links[0]["cv_tailor_score"] == 0.72
    assert links[0]["source"] == "manual"


def test_cv_tailor_results_unknown_job(client, monkeypatch):
    monkeypatch.setenv("JR_WRITE_KEY", KEY)
    _unlock(client)
    r = client.post("/api/cv-tailor-results", json={"job_id": "sha256:ghost", "cv_tailor_run_id": "run_1"})
    assert r.status_code == 404


def test_cv_tailor_results_score_out_of_range(client, monkeypatch):
    monkeypatch.setenv("JR_WRITE_KEY", KEY)
    _unlock(client)
    r = client.post("/api/cv-tailor-results", json={
        "job_id": "sha256:j1", "cv_tailor_run_id": "run_1", "cv_tailor_score": 1.5,
    })
    assert r.status_code == 422


def test_cv_tailor_results_requires_auth(client, monkeypatch):
    monkeypatch.setenv("JR_WRITE_KEY", KEY)  # configured but this client never unlocks
    r = client.post("/api/cv-tailor-results", json={"job_id": "sha256:j1", "cv_tailor_run_id": "run_1"})
    assert r.status_code == 403


def _seed_validated_jd(tmp_path, *, company="Elastic", raw_text="Full JD text...") -> str:
    """Write a validated JDRecord for sha256:j1 and return its glob (for an overridden Settings)."""
    from models.record import JDRecord
    from tests.factories import base_envelope
    validated = tmp_path / "validated_20260611.jsonl"
    env = base_envelope()
    env.update(id="sha256:j1", company=company)
    env["raw_text"] = raw_text
    validated.write_text(JDRecord.from_dict(env).to_jsonl() + "\n", encoding="utf-8")
    return str(validated)


def test_get_job_detail_found(client, tmp_path):
    from dataclasses import replace
    full = replace(client.settings, validated_glob=_seed_validated_jd(tmp_path, raw_text="Principal PM JD body"))
    app.dependency_overrides[get_settings] = lambda: full
    r = client.get("/api/jobs/sha256:j1")
    assert r.status_code == 200
    body = r.json()
    assert body["job_id"] == "sha256:j1"
    assert body["company"] == "Elastic"
    assert body["raw_text"] == "Principal PM JD body"
    assert body["fit_label"] == "good_fit" and body["fit_score"] == 7


def test_get_job_detail_not_found(client):
    assert client.get("/api/jobs/sha256:ghost").status_code == 404


def test_get_job_detail_no_auth_required(client, monkeypatch):
    # Public: no JR_WRITE_KEY, no cookie → still 200 (the JD is already public in the UI).
    monkeypatch.delenv("JR_WRITE_KEY", raising=False)
    assert client.get("/api/jobs/sha256:j1").status_code == 200


def test_index_overlays_live_cv_tailor(client, monkeypatch):
    monkeypatch.setenv("JR_WRITE_KEY", KEY)
    _unlock(client)
    # the seeded index.json row has no cv_tailor; a freshly recorded link must show on reload
    client.post("/api/cv-tailor-results", json={
        "job_id": "sha256:j1", "cv_tailor_run_id": "run_x", "cv_tailor_score": 0.5,
    })
    rec = client.get("/api/index").json()["records"][0]
    assert rec["cv_tailor"]["has_output"] is True
    assert rec["cv_tailor"]["run_id"] == "run_x"
    assert rec["cv_tailor"]["cv_score"] == 0.5


# --- health --------------------------------------------------------------------

def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["records"] == 1
    assert body["last_indexed"] == "2026-06-09T00:00:00Z"
