"""Shared collector plumbing — HTTP fetch with retry/backoff and a raw-record
builder.

Every ATS collector (Greenhouse, Lever, Ashby) follows the same shape: GET a
public JSON endpoint, then wrap each posting in a Tier-4 ``JDRecord`` whose
extraction and annotation fields are all ``None``. Collectors *do not extract* —
that is the labelling step's job (docs/job_radar_SPEC.md §5.3). Keeping the HTTP
and record-construction logic here means each collector is just an endpoint URL
plus a field mapping.
"""

from __future__ import annotations

import logging
import time

import requests

from models.record import (
    _ANNOTATION_FIELDS,
    _EXTRACTION_FIELDS,
    JDRecord,
)

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30
MAX_RETRIES = 3
RAW_TIER = 4


class NotFound(Exception):
    """Raised when an ATS endpoint returns 404 (unknown slug)."""


def fetch_json(
    url: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    max_retries: int = MAX_RETRIES,
    sleep=time.sleep,
) -> dict:
    """GET ``url`` and return parsed JSON.

    Raises :class:`NotFound` on 404. Retries on 429 with exponential backoff
    (1s, 2s, 4s, …) up to ``max_retries`` times before re-raising. ``sleep`` is
    injectable so tests can exercise the backoff without waiting.
    """
    for attempt in range(max_retries + 1):
        resp = requests.get(url, timeout=timeout)
        if resp.status_code == 404:
            raise NotFound(url)
        if resp.status_code == 429 and attempt < max_retries:
            backoff = 2 ** attempt
            log.warning("429 from %s — retry %d/%d after %ds", url, attempt + 1, max_retries, backoff)
            sleep(backoff)
            continue
        resp.raise_for_status()
        return resp.json()
    # Loop only falls through here if the final attempt was a 429.
    resp.raise_for_status()  # pragma: no cover - defensive
    return resp.json()  # pragma: no cover - defensive


# Every extraction/annotation field is left unset on a freshly collected record.
_NONE_FIELDS = {f: None for f in (*_EXTRACTION_FIELDS, *_ANNOTATION_FIELDS)}


def build_raw_record(
    *,
    source_url: str,
    source_ats: str,
    company: str,
    collected_at: str,
    raw_html: str | None = None,
    raw_text: str = "",
) -> JDRecord:
    """Build a Tier-4 ``JDRecord`` with identity/raw fields set and every
    extraction and annotation field ``None``.

    The ``id`` is left as ``sha256:pending``; ``pipeline.dedupe`` assigns the
    real content hash once the corpus is deduplicated.
    """
    return JDRecord(
        id="sha256:pending",
        source_url=source_url,
        source_ats=source_ats,
        company=company,
        collected_at=collected_at,
        tier=RAW_TIER,
        raw_html=raw_html,
        raw_text=raw_text,
        **_NONE_FIELDS,
    )
