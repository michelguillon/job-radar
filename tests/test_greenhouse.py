"""Tests for collectors.greenhouse and the shared collectors.base plumbing.

HTTP is mocked by monkeypatching ``collectors.base.requests.get`` with a fake
that returns scripted status codes / JSON, so no network or extra dependency is
needed. Backoff sleeps are injected as no-ops.
"""

import requests

import collectors.base as base
from collectors.base import NotFound, fetch_json
from collectors.greenhouse import fetch_company


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")


def patch_get(monkeypatch, responses):
    """Make ``requests.get`` return successive ``responses`` per call."""
    calls = {"n": 0}

    def fake_get(url, **kwargs):
        i = min(calls["n"], len(responses) - 1)
        calls["n"] += 1
        return responses[i]

    monkeypatch.setattr(base.requests, "get", fake_get)
    return calls


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


def _job(content="<p>Hello</p>", url="https://boards.greenhouse.io/acme/jobs/1"):
    # Greenhouse returns the content HTML-entity-escaped.
    import html

    return {"absolute_url": url, "content": html.escape(content)}


def test_fetch_company_maps_jobs_to_records(monkeypatch):
    payload = {"jobs": [_job(), _job(url="https://x/2")]}
    patch_get(monkeypatch, [FakeResponse(200, payload)])
    records = fetch_company("acme", "Acme", collected_at="2026-06-09")

    assert len(records) == 2
    r = records[0]
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


def test_fetch_company_404_returns_empty(monkeypatch):
    patch_get(monkeypatch, [FakeResponse(404)])
    assert fetch_company("nope", "Nope") == []


def test_fetch_company_persistent_429_returns_empty(monkeypatch):
    patch_get(monkeypatch, [FakeResponse(429)])
    assert fetch_company("busy", "Busy", sleep=lambda _: None) == []


def test_fetch_company_records_round_trip(monkeypatch):
    from models.record import JDRecord

    patch_get(monkeypatch, [FakeResponse(200, {"jobs": [_job()]})])
    record = fetch_company("acme", "Acme", collected_at="2026-06-09")[0]
    # to_jsonl -> from_jsonl preserves the record (valid JSONL envelope).
    assert JDRecord.from_jsonl(record.to_jsonl()) == record
