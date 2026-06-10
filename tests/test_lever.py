"""Tests for collectors.lever (HTTP mocked via tests.fake_http)."""

from collectors.lever import fetch_company
from models.record import JDRecord
from tests.fake_http import FakeResponse, patch_get


def _posting():
    return {
        "hostedUrl": "https://jobs.lever.co/acme/abc-123",
        "text": "Sales Engineer",
        "country": "GB",
        "workplaceType": "hybrid",
        "categories": {"location": "London", "team": "Field", "allLocations": ["London", "Paris"]},
        "description": "<p>Intro</p>",
        "lists": [
            {"text": "What you'll do", "content": "<ul><li>Build</li></ul>"},
            {"text": "", "content": "<ul><li>No heading</li></ul>"},
        ],
        "additional": "<p>Closing</p>",
    }


def test_updated_after_is_ignored_lever_has_no_timestamp(monkeypatch):
    # Lever's v0 feed has no per-posting timestamp → cursor cannot filter; a
    # passed updated_after is ignored and collection stays full.
    from collectors.lever import SUPPORTS_INCREMENTAL

    assert SUPPORTS_INCREMENTAL is False
    patch_get(monkeypatch, [FakeResponse(200, [_posting(), _posting()])])
    jobs = fetch_company("acme", "Acme", updated_after="2099-01-01T00:00:00+00:00")
    assert len(jobs) == 2  # full collection despite a far-future cursor


def test_fetch_company_maps_array_to_records(monkeypatch):
    # Lever returns a JSON array, not an object.
    patch_get(monkeypatch, [FakeResponse(200, [_posting(), _posting()])])
    jobs = fetch_company("acme", "Acme", collected_at="2026-06-09")

    assert len(jobs) == 2
    r = jobs[0].record
    assert r.source_ats == "lever"
    assert r.company == "Acme"
    assert r.tier == 4
    assert r.source_url == "https://jobs.lever.co/acme/abc-123"
    assert r.role_type is None  # collector does not extract


def test_fetch_company_captures_metadata(monkeypatch):
    patch_get(monkeypatch, [FakeResponse(200, [_posting()])])
    meta = fetch_company("acme", "Acme")[0].meta
    assert meta["title"] == "Sales Engineer"
    assert meta["country"] == "GB"
    assert meta["workplace_type"] == "hybrid"
    # allLocations joined so a multi-site posting matches on any one location
    assert meta["location_str"] == "London | Paris"


def test_assemble_html_joins_sections(monkeypatch):
    patch_get(monkeypatch, [FakeResponse(200, [_posting()])])
    html = fetch_company("acme", "Acme")[0].record.raw_html
    assert "<p>Intro</p>" in html
    assert "<h3>What you'll do</h3>" in html  # list heading rendered
    assert "<li>Build</li>" in html
    assert "<li>No heading</li>" in html  # empty-heading section still included
    assert "<p>Closing</p>" in html


def test_fetch_company_404_returns_empty(monkeypatch):
    patch_get(monkeypatch, [FakeResponse(404)])
    assert fetch_company("nope", "Nope") == []


def test_fetch_company_records_round_trip(monkeypatch):
    patch_get(monkeypatch, [FakeResponse(200, [_posting()])])
    record = fetch_company("acme", "Acme")[0].record
    assert JDRecord.from_jsonl(record.to_jsonl()) == record
