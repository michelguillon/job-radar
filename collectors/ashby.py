"""Ashby public API collector — fetches live JDs into JDRecord objects.

Endpoint (docs/job_radar_SPEC.md §5.4):

    GET https://api.ashbyhq.com/posting-api/job-board/{slug}

The response is ``{"jobs": [...]}``. Each job carries its description as real
HTML in ``descriptionHtml`` (preferred → ``raw_html``); if only the plain text
form is present we fall back to ``descriptionPlain`` → ``raw_text``. No fields
are extracted here.
"""

from __future__ import annotations

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

API_TEMPLATE = "https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"
SOURCE_ATS = "ashby"


def _country_of(job: dict) -> str | None:
    """Pull the country from an Ashby job's structured postal address."""
    postal = (job.get("address") or {}).get("postalAddress") or {}
    return postal.get("addressCountry")


def _meta_for(job: dict, company_name: str) -> dict:
    """Map an Ashby job's structured location fields into a metadata dict.

    Joins the primary ``location`` with any ``secondaryLocations`` so a
    multi-site posting matches on any one location. ``workplaceType`` and
    ``isRemote`` are first-class flags; ``country`` comes from the postal
    address (full name, e.g. "United Kingdom").
    """
    locations = [(job.get("location") or "").strip()]
    for sec in job.get("secondaryLocations") or []:
        name = (sec.get("location") or "").strip()
        if name:
            locations.append(name)
    location_str = " | ".join(loc for loc in locations if loc)
    workplace_type = (job.get("workplaceType") or "not_stated").lower()
    return build_meta(
        source_url=job.get("jobUrl", ""),
        source_ats=SOURCE_ATS,
        company=company_name,
        title=(job.get("title") or "").strip(),
        location_str=location_str,
        workplace_type=workplace_type,
        is_remote=job.get("isRemote"),
        country=_country_of(job),
        raw_location_payload={
            "location": job.get("location"),
            "secondaryLocations": job.get("secondaryLocations"),
            "address": job.get("address"),
        },
    )


def fetch_company(
    slug: str,
    company_name: str,
    *,
    collected_at: str | None = None,
    sleep=time.sleep,
) -> list[CollectedJob]:
    """Fetch all live jobs for ``slug`` from the Ashby job-board API.

    Returns ``CollectedJob`` objects (Tier-4 ``JDRecord`` + metadata sidecar).
    A 404 or persistent 429 is logged and yields ``[]``.
    """
    collected_at = collected_at or date.today().isoformat()
    url = API_TEMPLATE.format(slug=slug)
    try:
        data = fetch_json(url, sleep=sleep)
    except NotFound:
        log.warning("ashby: slug %r (%s) not found (404) — skipping", slug, company_name)
        return []
    except requests.HTTPError as exc:
        log.warning("ashby: slug %r (%s) failed: %s — skipping", slug, company_name, exc)
        return []

    jobs = []
    for job in data.get("jobs", []):
        raw_html = job.get("descriptionHtml")
        record = build_raw_record(
            source_url=job.get("jobUrl", ""),
            source_ats=SOURCE_ATS,
            company=company_name,
            collected_at=collected_at,
            raw_html=raw_html,
            raw_text="" if raw_html else job.get("descriptionPlain", ""),
        )
        jobs.append(CollectedJob(record=record, meta=_meta_for(job, company_name)))
    log.info("ashby: %s (%s) → %d jobs", company_name, slug, len(jobs))
    return jobs
