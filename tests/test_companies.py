"""Tests for the company-management API (SPEC_COMPANY_SEEDS_DB §4, deviation 55).

Paths are injected at tmp_path (app.dependency_overrides) and JR_WRITE_KEY via monkeypatch,
so nothing here touches the real corpus or DB. The autouse conftest._isolate_db points
JR_DB_PATH at a per-test SQLite file, so the company_seeds table is hermetic per test.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api.ats_probe as ats_probe
from api.main import app
from api.settings import Settings, get_settings
from collectors.base import build_raw_record

KEY = "owner-secret-key"


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        log_path=str(tmp_path / "activity_log.jsonl"),
        scored_glob=str(tmp_path / "scored_*.jsonl"),
        validated_glob=str(tmp_path / "validated_*.jsonl"),
        meta_glob=str(tmp_path / "meta_*.jsonl"),
        index_path=str(tmp_path / "index.json"),
        annotations_path=str(tmp_path / "annotations.jsonl"),
    )


@pytest.fixture(autouse=True)
def _hermetic_cookie_env(monkeypatch):
    monkeypatch.delenv("COOKIE_SECURE", raising=False)


@pytest.fixture
def client(settings, monkeypatch):
    monkeypatch.setenv("JR_WRITE_KEY", KEY)
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as c:
        c.settings = settings
        yield c
    app.dependency_overrides.clear()


def _unlock(client) -> None:
    assert client.post("/api/unlock", json={"key": KEY}).status_code == 200


def _add(client, name="Anthropic", ats="greenhouse", **kw) -> None:
    r = client.post("/api/companies", json={"name": name, "ats": ats, **kw})
    assert r.status_code == 200, r.text


def _write_validated_jd(settings, company: str) -> None:
    rec = build_raw_record(
        source_url=f"https://{company}/1", source_ats="greenhouse",
        company=company, collected_at="2026-06-19", raw_html="<p>x</p>",
    )
    with open(settings.validated_glob.replace("*", "test"), "w", encoding="utf-8") as fh:
        fh.write(rec.to_jsonl() + "\n")


# --- reads (public) ------------------------------------------------------------

def test_get_companies_returns_all(client):
    _unlock(client)
    _add(client, "Anthropic")
    _add(client, "Cohere", "ashby", slug="cohere")
    # Public read — no unlock required.
    client.post("/api/lock")
    rows = client.get("/api/companies").json()
    assert [r["name"] for r in rows] == ["Anthropic", "Cohere"]  # ordered by name


# --- create --------------------------------------------------------------------

def test_post_company_creates(client):
    _unlock(client)
    r = client.post("/api/companies", json={
        "name": "Moveworks", "ats": "greenhouse", "slug": "moveworks",
        "domain": "ai_application_platform", "fit_hypothesis": "high",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Moveworks"
    assert body["action"] == "keep"          # default applied
    assert body["notes"] == ""
    assert client.get("/api/companies").json()[0]["name"] == "Moveworks"


def test_post_company_duplicate_409(client):
    _unlock(client)
    _add(client, "Anthropic")
    r = client.post("/api/companies", json={"name": "Anthropic", "ats": "greenhouse"})
    assert r.status_code == 409


def test_post_company_missing_ats_422(client):
    _unlock(client)
    r = client.post("/api/companies", json={"name": "NoAts"})
    assert r.status_code == 422


def test_post_company_requires_unlock(client):
    r = client.post("/api/companies", json={"name": "Anthropic", "ats": "greenhouse"})
    assert r.status_code == 403


# --- patch ---------------------------------------------------------------------

def test_patch_company_updates_field(client):
    _unlock(client)
    _add(client, "Anthropic", fit_hypothesis="high")
    r = client.patch("/api/companies/Anthropic", json={"fit_hypothesis": "medium", "action": "pause"})
    assert r.status_code == 200
    assert r.json()["fit_hypothesis"] == "medium"
    assert r.json()["action"] == "pause"


def test_patch_company_not_found_404(client):
    _unlock(client)
    r = client.patch("/api/companies/Ghost", json={"notes": "x"})
    assert r.status_code == 404


# --- delete --------------------------------------------------------------------

def test_delete_company_no_corpus_records_204(client):
    _unlock(client)
    _add(client, "Anthropic")
    r = client.delete("/api/companies/Anthropic")
    assert r.status_code == 204
    assert client.get("/api/companies").json() == []


def test_delete_company_has_corpus_records_409(client):
    _unlock(client)
    _add(client, "Anthropic")
    _write_validated_jd(client.settings, "Anthropic")
    r = client.delete("/api/companies/Anthropic")
    assert r.status_code == 409
    assert "action: remove" in r.json()["detail"]


def test_delete_company_not_found_404(client):
    _unlock(client)
    r = client.delete("/api/companies/Ghost")
    assert r.status_code == 404


# --- probe-ats -----------------------------------------------------------------

def test_probe_ats_found(client, monkeypatch):
    _unlock(client)
    monkeypatch.setattr(ats_probe, "probe_greenhouse", lambda slug, c: slug == "moveworks")
    monkeypatch.setattr(ats_probe, "probe_ashby", lambda slug, c: False)
    monkeypatch.setattr(ats_probe, "probe_lever", lambda slug, c: False)
    r = client.post("/api/companies/probe-ats", json={"name": "Moveworks"})
    assert r.json() == {"found": True, "ats": "greenhouse", "slug": "moveworks"}


def test_probe_ats_not_found(client, monkeypatch):
    _unlock(client)
    monkeypatch.setattr(ats_probe, "probe_greenhouse", lambda slug, c: False)
    monkeypatch.setattr(ats_probe, "probe_ashby", lambda slug, c: False)
    monkeypatch.setattr(ats_probe, "probe_lever", lambda slug, c: False)
    r = client.post("/api/companies/probe-ats", json={"name": "Nope Inc"})
    assert r.json() == {"found": False}


def test_probe_ats_requires_unlock(client):
    r = client.post("/api/companies/probe-ats", json={"name": "Moveworks"})
    assert r.status_code == 403


# --- export --------------------------------------------------------------------

def test_export_returns_yaml(client):
    _unlock(client)
    _add(client, "Anthropic", slug="anthropic", domain="frontier_ai", fit_hypothesis="high")
    r = client.get("/api/companies/export")
    assert r.status_code == 200
    assert "text/yaml" in r.headers["content-type"]
    assert "attachment" in r.headers["content-disposition"]
    assert "# company_seeds.yaml" in r.text
    assert "Anthropic" in r.text


def test_export_requires_unlock(client):
    _unlock(client)
    _add(client, "Anthropic")
    client.post("/api/lock")
    assert client.get("/api/companies/export").status_code == 403
