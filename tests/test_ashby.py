"""Tests for collectors.ashby (HTTP mocked via tests.fake_http)."""

from collectors.ashby import fetch_company
from models.record import JDRecord
from tests.fake_http import FakeResponse, patch_get


def _job(html="<p>Role</p>", plain=None):
    job = {
        "jobUrl": "https://jobs.ashbyhq.com/acme/uuid-1",
        "title": "Solutions Architect",
        "location": "London",
        "secondaryLocations": [{"location": "Dublin"}],
        "workplaceType": "Hybrid",
        "isRemote": True,
        "address": {"postalAddress": {"addressCountry": "United Kingdom", "addressLocality": "London"}},
        "descriptionPlain": plain if plain is not None else "Role",
    }
    if html is not None:
        job["descriptionHtml"] = html
    return job


def test_fetch_company_maps_jobs_to_records(monkeypatch):
    patch_get(monkeypatch, [FakeResponse(200, {"jobs": [_job(), _job()]})])
    jobs = fetch_company("acme", "Acme", collected_at="2026-06-09")

    assert len(jobs) == 2
    r = jobs[0].record
    assert r.source_ats == "ashby"
    assert r.company == "Acme"
    assert r.tier == 4
    assert r.source_url == "https://jobs.ashbyhq.com/acme/uuid-1"
    assert r.raw_html == "<p>Role</p>"
    assert r.raw_text == ""  # html present → plain not duplicated
    assert r.seniority is None


def test_fetch_company_captures_metadata(monkeypatch):
    patch_get(monkeypatch, [FakeResponse(200, {"jobs": [_job()]})])
    meta = fetch_company("acme", "Acme")[0].meta
    assert meta["title"] == "Solutions Architect"
    assert meta["country"] == "United Kingdom"
    assert meta["workplace_type"] == "hybrid"
    assert meta["is_remote"] is True
    # primary + secondary locations joined
    assert meta["location_str"] == "London | Dublin"


def test_fetch_company_falls_back_to_plain_text(monkeypatch):
    # No descriptionHtml — fall back to descriptionPlain into raw_text.
    patch_get(monkeypatch, [FakeResponse(200, {"jobs": [_job(html=None, plain="Plain JD")]})])
    r = fetch_company("acme", "Acme")[0].record
    assert r.raw_html is None
    assert r.raw_text == "Plain JD"


def test_fetch_company_404_returns_empty(monkeypatch):
    patch_get(monkeypatch, [FakeResponse(404)])
    assert fetch_company("nope", "Nope") == []


def test_fetch_company_records_round_trip(monkeypatch):
    patch_get(monkeypatch, [FakeResponse(200, {"jobs": [_job()]})])
    record = fetch_company("acme", "Acme")[0].record
    assert JDRecord.from_jsonl(record.to_jsonl()) == record
