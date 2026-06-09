"""Shared HTTP test double for collector tests.

Monkeypatches ``collectors.base.requests.get`` with a scripted sequence of
``FakeResponse`` objects, so collector tests need no network and no extra
dependency (``responses``/``pytest-httpx``).
"""

from __future__ import annotations

import requests

import collectors.base as base


class FakeResponse:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")


def patch_get(monkeypatch, responses: list[FakeResponse]) -> dict:
    """Make ``requests.get`` return successive ``responses`` per call.

    Returns a dict whose ``"n"`` key tracks how many times it was called.
    """
    calls = {"n": 0}

    def fake_get(url, **kwargs):
        i = min(calls["n"], len(responses) - 1)
        calls["n"] += 1
        return responses[i]

    monkeypatch.setattr(base.requests, "get", fake_get)
    return calls
