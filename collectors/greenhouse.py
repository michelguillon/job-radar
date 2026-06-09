"""Greenhouse public API collector — fetches live JDs into JDRecord objects.

Endpoint (docs/job_radar_SPEC.md §5.4):

    GET https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true

With ``content=true`` each job carries an HTML-entity-escaped ``content`` field
(e.g. ``&lt;p&gt;``). We unescape it back to real HTML and store it as
``raw_html`` so the cleaning pipeline (``pipeline.clean``) can parse it. No
fields are extracted here — the collector only captures raw content.
"""

from __future__ import annotations

import html
import logging
import time
from datetime import date

import requests

from collectors.base import (
    CollectedJob,
    NotFound,
    build_meta,
    build_raw_record,
    fetch_json,
)

log = logging.getLogger(__name__)

API_TEMPLATE = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
SOURCE_ATS = "greenhouse"


def fetch_company(
    slug: str,
    company_name: str,
    *,
    collected_at: str | None = None,
    sleep=time.sleep,
) -> list[CollectedJob]:
    """Fetch all live jobs for ``slug`` from the Greenhouse public API.

    Returns a list of ``CollectedJob`` (Tier-4 ``JDRecord`` + metadata sidecar).
    A 404 (unknown slug) or persistent 429 is logged and yields ``[]`` so a
    batch run continues past one bad company.

    Greenhouse exposes ``title`` and a free-form ``location.name`` but no
    workplace-policy or country flag, so those are inferred from the location
    string (``remote`` substring) and otherwise left unset for the screen.
    """
    collected_at = collected_at or date.today().isoformat()
    url = API_TEMPLATE.format(slug=slug)
    try:
        data = fetch_json(url, sleep=sleep)
    except NotFound:
        log.warning("greenhouse: slug %r (%s) not found (404) — skipping", slug, company_name)
        return []
    except requests.HTTPError as exc:
        log.warning("greenhouse: slug %r (%s) failed: %s — skipping", slug, company_name, exc)
        return []

    jobs: list[CollectedJob] = []
    for job in data.get("jobs", []):
        source_url = job.get("absolute_url", "")
        location = job.get("location") or {}
        location_str = (location.get("name") or "").strip()
        is_remote = True if "remote" in location_str.lower() else None
        record = build_raw_record(
            source_url=source_url,
            source_ats=SOURCE_ATS,
            company=company_name,
            collected_at=collected_at,
            raw_html=html.unescape(job.get("content") or ""),
        )
        meta = build_meta(
            source_url=source_url,
            source_ats=SOURCE_ATS,
            company=company_name,
            title=(job.get("title") or "").strip(),
            location_str=location_str,
            workplace_type="remote" if is_remote else "not_stated",
            is_remote=is_remote,
            country=None,
            raw_location_payload=location,
        )
        jobs.append(CollectedJob(record=record, meta=meta))
    log.info("greenhouse: %s (%s) → %d jobs", company_name, slug, len(jobs))
    return jobs
