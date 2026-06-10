"""Tests for collectors.greenhouse and the shared collectors.base plumbing.

HTTP is mocked via tests.fake_http (no network, no extra dependency). Backoff
sleeps are injected as no-ops.
"""

import requests

from collectors.base import NotFound, fetch_json
from collectors.greenhouse import fetch_company
from tests.fake_http import FakeResponse, patch_get


# --- fetch_json (shared) ---


def test_fetch_json_returns_payload(monkeypatch):
    patch_get(monkeypatch, [FakeResponse(200, {"jobs": []})])
    assert fetch_json("http://x") == {"jobs": []}


def test_fetch_json_raises_notfound_on_404(monkeypatch):
    patch_get(monkeypatch, [FakeResponse(404)])
    try:
        fetch_json("http://x")
        assert False, "expected NotFound"
    except NotFound:
        pass


def test_fetch_json_retries_on_429_then_succeeds(monkeypatch):
    calls = patch_get(
        monkeypatch,
        [FakeResponse(429), FakeResponse(429), FakeResponse(200, {"ok": True})],
    )
    slept = []
    assert fetch_json("http://x", sleep=slept.append) == {"ok": True}
    assert calls["n"] == 3
    assert slept == [1, 2]  # exponential backoff between the two retries


def test_fetch_json_raises_after_exhausting_retries(monkeypatch):
    patch_get(monkeypatch, [FakeResponse(429)])
    try:
        fetch_json("http://x", max_retries=2, sleep=lambda _: None)
        assert False, "expected HTTPError"
    except requests.HTTPError:
        pass


# --- fetch_company ---


def _job(content="<p>Hello</p>", url="https://boards.greenhouse.io/acme/jobs/1",
         title="Solutions Engineer", location="London, UK", updated_at="2026-06-10T12:00:00-04:00"):
    # Greenhouse returns the content HTML-entity-escaped.
    import html

    return {
        "absolute_url": url,
        "content": html.escape(content),
        "title": title,
        "location": {"name": location},
        "updated_at": updated_at,
    }


def test_fetch_company_maps_jobs_to_records(monkeypatch):
    payload = {"jobs": [_job(), _job(url="https://x/2")]}
    patch_get(monkeypatch, [FakeResponse(200, payload)])
    jobs = fetch_company("acme", "Acme", collected_at="2026-06-09")

    assert len(jobs) == 2
    r = jobs[0].record
    assert r.source_ats == "greenhouse"
    assert r.company == "Acme"
    assert r.collected_at == "2026-06-09"
    assert r.tier == 4
    assert r.id == "sha256:pending"
    # content is unescaped back into real HTML
    assert r.raw_html == "<p>Hello</p>"
    # collector does not extract
    assert r.role_type is None
    assert r.seniority is None
    assert r.fit_score is None
    # raw_text stays employer text only — title/location go to the sidecar
    assert r.raw_text == ""


def test_fetch_company_captures_metadata(monkeypatch):
    patch_get(monkeypatch, [FakeResponse(200, {"jobs": [_job()]})])
    meta = fetch_company("acme", "Acme")[0].meta
    assert meta["source_url"] == "https://boards.greenhouse.io/acme/jobs/1"
    assert meta["source_ats"] == "greenhouse"
    assert meta["company"] == "Acme"
    assert meta["title"] == "Solutions Engineer"
    assert meta["location_str"] == "London, UK"
    assert meta["country"] is None  # greenhouse exposes no country


def test_fetch_company_infers_remote_from_location(monkeypatch):
    patch_get(monkeypatch, [FakeResponse(200, {"jobs": [_job(location="Remote - US")]})])
    meta = fetch_company("acme", "Acme")[0].meta
    assert meta["is_remote"] is True
    assert meta["workplace_type"] == "remote"


def test_fetch_company_404_returns_empty(monkeypatch):
    patch_get(monkeypatch, [FakeResponse(404)])
    assert fetch_company("nope", "Nope") == []


def test_fetch_company_persistent_429_returns_empty(monkeypatch):
    patch_get(monkeypatch, [FakeResponse(429)])
    assert fetch_company("busy", "Busy", sleep=lambda _: None) == []


def test_fetch_company_records_round_trip(monkeypatch):
    from models.record import JDRecord

    patch_get(monkeypatch, [FakeResponse(200, {"jobs": [_job()]})])
    record = fetch_company("acme", "Acme", collected_at="2026-06-09")[0].record
    # to_jsonl -> from_jsonl preserves the record (valid JSONL envelope).
    assert JDRecord.from_jsonl(record.to_jsonl()) == record


# --- incremental (client-side updated_at filter) ---


def test_updated_after_keeps_only_new_or_updated(monkeypatch):
    payload = {"jobs": [
        _job(url="https://x/old", updated_at="2026-06-01T00:00:00Z"),   # before cursor
        _job(url="https://x/new", updated_at="2026-06-10T00:00:00Z"),   # after cursor
    ]}
    patch_get(monkeypatch, [FakeResponse(200, payload)])
    jobs = fetch_company("acme", "Acme", updated_after="2026-06-05T00:00:00+00:00")
    assert [j.record.source_url for j in jobs] == ["https://x/new"]


def test_no_cursor_collects_all(monkeypatch):
    payload = {"jobs": [_job(url="https://x/1", updated_at="2026-01-01T00:00:00Z"), _job(url="https://x/2")]}
    patch_get(monkeypatch, [FakeResponse(200, payload)])
    assert len(fetch_company("acme", "Acme", updated_after=None)) == 2


def test_missing_updated_at_is_kept_under_cursor(monkeypatch):
    job = _job(url="https://x/1")
    del job["updated_at"]  # malformed/missing timestamp must never be silently dropped
    patch_get(monkeypatch, [FakeResponse(200, {"jobs": [job]})])
    assert len(fetch_company("acme", "Acme", updated_after="2026-06-05T00:00:00+00:00")) == 1
