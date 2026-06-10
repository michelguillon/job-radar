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
from dataclasses import dataclass, field
from datetime import datetime, timezone

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

# Fields carried by a metadata sidecar record (corpus/raw/meta_{date}.jsonl).
# The sidecar holds the structured title + location signal the ATS APIs return
# but JDRecord (schema-locked v1.2) has no field for. It is keyed by
# ``source_url`` (stable at collection time, before dedupe assigns the content
# hash) and used for the deterministic pre-label filter (pipeline.prefilter) and,
# later, passed to the extraction prompt as separate context — never injected
# into raw_text, which stays employer-provided JD text only.
META_FIELDS = (
    "source_url",
    "source_ats",
    "company",
    "title",
    "location_str",
    "workplace_type",
    "is_remote",
    "country",
    "raw_location_payload",
)


def _parse_iso(value) -> datetime | None:
    """Parse an ISO-8601 timestamp to an aware datetime, or None if unparseable.

    Handles a trailing ``Z`` and fractional seconds; naive timestamps are
    assumed UTC so all comparisons are timezone-safe.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def passes_cursor(job_ts, cutoff: str | None) -> bool:
    """True if a job with timestamp ``job_ts`` should be collected this run.

    Incremental collection is **client-side**: the public board APIs expose no
    server-side date filter, but each Greenhouse/Ashby job carries its own
    timestamp, so a collector keeps a job only when it is at/after the cursor.

    - ``cutoff is None`` (no cursor / ``--full``) → collect everything.
    - an unparseable or missing ``job_ts`` → **collect it** (never silently drop
      a job because its timestamp was malformed; dedupe handles the re-collect).
    """
    if cutoff is None:
        return True
    job_dt = _parse_iso(job_ts)
    cut_dt = _parse_iso(cutoff)
    if job_dt is None or cut_dt is None:
        return True
    return job_dt >= cut_dt


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


def build_meta(
    *,
    source_url: str,
    source_ats: str,
    company: str,
    title: str,
    location_str: str,
    workplace_type: str = "not_stated",
    is_remote: bool | None = None,
    country: str | None = None,
    raw_location_payload=None,
) -> dict:
    """Build a metadata sidecar dict for one posting (see ``META_FIELDS``).

    ``location_str`` is the *combined* human location string (all listed
    locations joined with " | ") so the location screen can match a multi-site
    posting on any one of its locations. ``raw_location_payload`` keeps the
    original structured location object for later inspection.
    """
    return {
        "source_url": source_url,
        "source_ats": source_ats,
        "company": company,
        "title": title,
        "location_str": location_str,
        "workplace_type": workplace_type,
        "is_remote": is_remote,
        "country": country,
        "raw_location_payload": raw_location_payload,
    }


@dataclass(frozen=True)
class CollectedJob:
    """A collected posting: the raw ``JDRecord`` plus its metadata sidecar.

    Collectors return ``list[CollectedJob]`` so the record and its structured
    title/location metadata stay paired. ``collect.py`` splits the two streams
    into ``raw_{date}.jsonl`` and ``meta_{date}.jsonl``.
    """

    record: JDRecord
    meta: dict = field(default_factory=dict)
