"""Tests for POST /api/manual-ingest (job_radar_SPEC §11.1, manual JD entry via the UI).

The Claude extraction call is mocked (``api.routers.manual_ingest.extract_one``) — same spirit
as tests/test_label.py's faked client. The real scorer + candidate_profile.yaml are exercised
(load_profile() default path, as tests/test_scorer.py already relies on). Corpus paths are
injected at tmp_path via app.dependency_overrides, so nothing here touches the real corpus.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.routers import manual_ingest
from api.settings import Settings, get_settings
from cli.track import load_scores

KEY = "owner-secret-key"

# A full JD body, comfortably over the 200-char minimum.
JD_TEXT = (
    "Director, Solutions Engineering at Acme. Lead and scale the EMEA Solutions Engineering "
    "org: executive pre-sales technical solution design, end-to-end implementation, and GTM "
    "strategy. 10+ years client-facing experience, 3+ in senior leadership. Payments/fintech "
    "knowledge advantageous. Based in London (hybrid). Deep API platform solutioning expertise."
)

# A schema-complete extraction the mock returns (all 17 extraction keys present).
EXTRACTION = {
    "role_type": ["Solutions Engineering"],
    "seniority": "director",
    "technical_depth": "hybrid",
    "years_experience_required": "10+",
    "required_technologies": ["API platform solutioning"],
    "required_competencies": ["pre-sales team leadership", "GTM strategy ownership"],
    "nice_to_have_technologies": [],
    "nice_to_have_competencies": ["financial services domain experience"],
    "domain": ["FinTech", "Payments"],
    "remote_policy": "hybrid",
    "location": "London",
    "delivery_motion": ["pre_sales", "direct_delivery"],
    "leadership_geography": ["EMEA"],
    "company_size_signal": "scale_up",
    "company_stage": "pre_ipo",
    "culture_signals": ["builder mentality"],
    "raw_observations": "",
}
USAGE = {"input": 1200, "output": 300, "cache_read": 0, "cache_write": 0}


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        log_path=str(tmp_path / "activity_log.jsonl"),
        scored_glob=str(tmp_path / "scored" / "scored_*.jsonl"),
        validated_glob=str(tmp_path / "validated" / "validated_*.jsonl"),
        meta_glob=str(tmp_path / "raw" / "meta_*.jsonl"),
        index_path=str(tmp_path / "index.json"),
        annotations_path=str(tmp_path / "annotations.jsonl"),
        cv_tailor_links_path=str(tmp_path / "cv_tailor_links.jsonl"),
        stats_path=str(tmp_path / "stats.json"),
        # profile_path defaults to candidate_profile.yaml (real scorer profile).
    )


@pytest.fixture(autouse=True)
def _hermetic_cookie_env(monkeypatch):
    # The TestClient runs over http; a Secure cookie would be dropped. Pin it off (see test_api).
    monkeypatch.delenv("COOKIE_SECURE", raising=False)


@pytest.fixture(autouse=True)
def _mock_extraction(monkeypatch):
    """Mock the single Claude extraction call — no network, deterministic output + usage."""
    monkeypatch.setattr(manual_ingest, "extract_one", lambda record, **_: (dict(EXTRACTION), dict(USAGE)))


@pytest.fixture
def client(settings):
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as c:
        c.settings = settings
        yield c
    app.dependency_overrides.clear()


def _unlock(client) -> None:
    assert client.post("/api/unlock", json={"key": KEY}).status_code == 200


def _payload(**over) -> dict:
    body = {"company": "Acme", "title": "Director, Solutions Engineering", "raw_text": JD_TEXT}
    body.update(over)
    return body


# --- success -------------------------------------------------------------------

def test_manual_ingest_success(client, monkeypatch):
    monkeypatch.setenv("JR_WRITE_KEY", KEY)
    _unlock(client)
    r = client.post("/api/manual-ingest", json=_payload())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["company"] == "Acme" and body["title"] == "Director, Solutions Engineering"
    assert isinstance(body["fit_score"], int) and body["fit_label"]
    assert isinstance(body["priority_score"], int)
    # The scored record is now in the corpus, keyed by the content hash.
    scores = load_scores(client.settings.scored_glob)
    assert body["job_id"] in scores
    assert scores[body["job_id"]].fit_label == body["fit_label"]


# --- validation ----------------------------------------------------------------

def test_manual_ingest_too_short(client, monkeypatch):
    monkeypatch.setenv("JR_WRITE_KEY", KEY)
    _unlock(client)
    r = client.post("/api/manual-ingest", json=_payload(raw_text="Too short JD."))
    assert r.status_code == 422
    assert "too short" in r.json()["detail"].lower()


def test_manual_ingest_empty_text(client, monkeypatch):
    monkeypatch.setenv("JR_WRITE_KEY", KEY)
    _unlock(client)
    r = client.post("/api/manual-ingest", json=_payload(raw_text="   "))
    assert r.status_code == 422


# --- dedup ---------------------------------------------------------------------

def test_manual_ingest_duplicate(client, monkeypatch):
    monkeypatch.setenv("JR_WRITE_KEY", KEY)
    _unlock(client)
    first = client.post("/api/manual-ingest", json=_payload())
    assert first.status_code == 200
    second = client.post("/api/manual-ingest", json=_payload())
    assert second.status_code == 409
    assert second.json()["detail"]["job_id"] == first.json()["job_id"]


# --- auth ----------------------------------------------------------------------

def test_manual_ingest_requires_auth(client, monkeypatch):
    monkeypatch.setenv("JR_WRITE_KEY", KEY)  # configured but this client never unlocks
    assert client.post("/api/manual-ingest", json=_payload()).status_code == 403


# --- side effects: cost + source attribution -----------------------------------

def test_manual_ingest_cost_tracked(client, monkeypatch):
    monkeypatch.setenv("JR_WRITE_KEY", KEY)
    _unlock(client)
    assert client.post("/api/manual-ingest", json=_payload()).status_code == 200
    with open(client.settings.stats_path, encoding="utf-8") as fh:
        runs = json.load(fh)
    manual = [r for r in runs if r.get("step") == "manual_ingest"]
    assert len(manual) == 1
    assert manual[0]["cost_usd"] > 0


def test_manual_ingest_ats_manual(client, monkeypatch):
    monkeypatch.setenv("JR_WRITE_KEY", KEY)
    _unlock(client)
    job_id = client.post("/api/manual-ingest", json=_payload()).json()["job_id"]
    # The rebuilt index row carries ats="manual" (source attribution for cli.analyse reports).
    with open(client.settings.index_path, encoding="utf-8") as fh:
        index = json.load(fh)
    row = next(r for r in index["records"] if r["job_id"] == job_id)
    assert row["source_ats"] == "manual"


# --- soft validation (deviation 47) --------------------------------------------

# An extraction whose role_type is OFF the ROLE_TYPE vocabulary — the case the owner
# deliberately wants to add anyway (e.g. a Customer Success role outside target_roles).
EXTRACTION_UNKNOWN_ROLE = {**EXTRACTION, "role_type": ["Customer Success"]}


def test_manual_ingest_unknown_role_type(client, monkeypatch):
    """An off-vocabulary role_type is stored (200), not rejected (422), with a warning."""
    monkeypatch.setattr(
        manual_ingest, "extract_one",
        lambda record, **_: (dict(EXTRACTION_UNKNOWN_ROLE), dict(USAGE)),
    )
    monkeypatch.setenv("JR_WRITE_KEY", KEY)
    _unlock(client)
    r = client.post("/api/manual-ingest", json=_payload())
    assert r.status_code == 200, r.text
    body = r.json()
    # The record was stored and scored despite the enum violation.
    scores = load_scores(client.settings.scored_glob)
    assert body["job_id"] in scores
    assert isinstance(body["fit_score"], int)
    # The violation comes back as an advisory warning, not an error.
    assert any("role_type" in w and "Customer Success" in w for w in body["warnings"])


def test_manual_ingest_warnings_in_response(client, monkeypatch):
    """The response always carries a `warnings` list — empty when the extraction is clean."""
    monkeypatch.setenv("JR_WRITE_KEY", KEY)
    _unlock(client)
    body = client.post("/api/manual-ingest", json=_payload()).json()  # default EXTRACTION is clean
    assert body["warnings"] == []


def test_validate_record_still_strict():
    """The automated-pipeline validator still REPORTS an unknown role_type (batch unaffected)."""
    from models.record import soft_validate, validate
    from tests.factories import make_record

    rec = make_record()
    rec.role_type = ["Customer Success"]  # role_type lives in the nested extraction; set directly
    errors = validate(rec)
    assert any("role_type" in e for e in errors)
    # soft_validate runs the SAME checks — it just doesn't block the caller.
    assert soft_validate(rec) == errors


def test_manual_ingest_emits_telemetry(client, monkeypatch):
    """When tracing is enabled, the endpoint builds a well-formed manual_ingest trace row."""
    captured = {}
    monkeypatch.setattr(manual_ingest.telemetry, "is_enabled", lambda: True)
    monkeypatch.setattr(
        manual_ingest.telemetry, "record_manual_ingest",
        lambda job_id, row, metadata=None: captured.update(job_id=job_id, row=row, metadata=metadata),
    )
    monkeypatch.setenv("JR_WRITE_KEY", KEY)
    _unlock(client)
    r = client.post("/api/manual-ingest", json=_payload())
    assert r.status_code == 200, r.text

    assert captured["job_id"] == r.json()["job_id"]
    row = captured["row"]
    assert row["model"] == "claude-haiku-4-5"          # the synchronous Haiku extraction model
    assert row["completion"] == EXTRACTION             # the extraction dict (generation output)
    assert row["fit_label"] == r.json()["fit_label"]
    assert row["validated"] is True                    # default EXTRACTION is schema-clean (no warnings)
    assert "[ATS METADATA]" in row["prompt"]           # prompt rebuilt with the metadata block
    assert {d["dimension"] for d in row["dimensions"]} == {
        "role", "domain", "technical_depth", "seniority", "location"
    }
    assert captured["metadata"]["scored_at"]


def test_manual_ingest_telemetry_failure_is_nonfatal(client, monkeypatch):
    """A telemetry error never fails an ingest the user already completed (record persisted)."""
    monkeypatch.setattr(manual_ingest.telemetry, "is_enabled", lambda: True)
    def _boom(*a, **k):
        raise RuntimeError("langfuse down")
    monkeypatch.setattr(manual_ingest.telemetry, "record_manual_ingest", _boom)
    monkeypatch.setenv("JR_WRITE_KEY", KEY)
    _unlock(client)
    r = client.post("/api/manual-ingest", json=_payload())
    assert r.status_code == 200, r.text
    assert r.json()["job_id"] in load_scores(client.settings.scored_glob)  # persisted despite the error


def test_scorer_unknown_role_type():
    """The scorer scores an unknown role_type as 0 for the role dimension, never raising."""
    from scoring.profile import load_profile
    from scoring.scorer import _role_score, score
    from tests.factories import make_record

    profile = load_profile("candidate_profile.yaml")
    rec = make_record(raw_text=JD_TEXT)
    rec.role_type = ["Customer Success"]
    assert _role_score(rec, profile) == 0.0  # no primary/secondary/conditional match
    app_record = score(rec, profile, "2026-06-13T00:00:00Z")  # must not raise
    assert isinstance(app_record.fit_score, int)
