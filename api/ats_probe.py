"""api/ats_probe.py — server-side ATS auto-discovery (SPEC_COMPANY_SEEDS_DB §4.2).

Given a company name, generate slug candidates and probe Greenhouse, Ashby and Lever for a
live job board, returning the first match. Ported from the repo-root ``find_ats_slugs.py``
script (slug generation + per-ATS probes); the endpoints are aligned with the live collector
URLs (``collectors/{greenhouse,ashby,lever}.py``) rather than the script's slightly different
ones, so a probe hit matches what the collector will actually fetch.

Runs server-side (no browser CORS, one home for the probe logic). Never raises — any error or
timeout yields ``{"found": False}``. A total time budget bounds the worst case so the UI's
"Find ATS" button can't hang.
"""

from __future__ import annotations

import re
import time

import httpx

# Total wall-clock budget across all probes (SPEC §4.2: "10s total"). Per-request timeout is
# tighter so one slow host can't consume the whole budget on a single candidate.
PROBE_BUDGET_S = 10.0
_PER_REQUEST_S = 4.0
_USER_AGENT = "job-radar-ats-probe/1.0"


def slug_candidates(name: str) -> list[str]:
    """Generate plausible board slugs for a company name (deduped, order-preserving).

    Ported verbatim from ``find_ats_slugs.py`` so discovery behaves identically to the
    one-off script: collapsed words, hyphenated, first-two-words, first word, initials, and
    common-suffix-stripped variants ("Foo AI" → "foo")."""
    base = name.lower()
    base = re.sub(r"['’]", "", base)
    base = re.sub(r"[^a-z0-9 ]", " ", base)
    base = base.strip()
    words = base.split()

    candidates = ["".join(words), "-".join(words)]
    if len(words) > 1:
        candidates.append("".join(words[:2]))
    if words:
        candidates.append(words[0])
    if len(words) > 1:
        candidates.append("".join(w[0] for w in words))

    for suffix in (" ai", " labs", " technologies", " systems", " platform",
                   " analytics", " solutions", " inc", " ltd", " bank", " x"):
        if base.endswith(suffix):
            trimmed = base[: -len(suffix)].strip().replace(" ", "")
            if trimmed:
                candidates.append(trimmed)

    return list(dict.fromkeys(c for c in candidates if c))


def probe_greenhouse(slug: str, client: httpx.Client) -> bool:
    try:
        r = client.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
        return r.status_code == 200
    except Exception:
        return False


def probe_ashby(slug: str, client: httpx.Client) -> bool:
    try:
        r = client.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
        return r.status_code == 200
    except Exception:
        return False


def probe_lever(slug: str, client: httpx.Client) -> bool:
    try:
        r = client.get(f"https://api.lever.co/v0/postings/{slug}?mode=json&limit=1")
        return r.status_code == 200 and isinstance(r.json(), list)
    except Exception:
        return False


def probe_ats(name: str, *, client: httpx.Client | None = None, budget_s: float = PROBE_BUDGET_S) -> dict:
    """Probe Greenhouse → Ashby → Lever for ``name`` and return the first hit.

    Returns ``{"found": True, "ats": <ats>, "slug": <slug>}`` or ``{"found": False}``. Never
    raises. Stops early once the time budget is exhausted (returns not-found). The probe
    functions are looked up at call time, so they can be monkeypatched in tests.
    """
    own = client is None
    if own:
        client = httpx.Client(
            headers={"User-Agent": _USER_AGENT}, follow_redirects=True, timeout=_PER_REQUEST_S,
        )
    probes = [("greenhouse", probe_greenhouse), ("ashby", probe_ashby), ("lever", probe_lever)]
    start = time.monotonic()
    try:
        for ats_name, probe_fn in probes:
            for slug in slug_candidates(name):
                if time.monotonic() - start > budget_s:
                    return {"found": False}
                if probe_fn(slug, client):
                    return {"found": True, "ats": ats_name, "slug": slug}
        return {"found": False}
    except Exception:
        return {"found": False}
    finally:
        if own:
            client.close()
