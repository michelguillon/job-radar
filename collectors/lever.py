"""Lever public API collector — fetches live JDs into JDRecord objects.

Endpoint (docs/job_radar_SPEC.md §5.4):

    GET https://api.lever.co/v0/postings/{slug}?mode=json

The response is a JSON *array* of postings. A posting's text is split across
``description`` (intro HTML), ``lists`` (each a ``{text, content}`` bullet
section) and ``additional`` (closing HTML); we concatenate them into one
``raw_html`` blob so the cleaning pipeline sees the whole JD. Same shape as the
Greenhouse collector otherwise — no fields are extracted here.
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

API_TEMPLATE = "https://api.lever.co/v0/postings/{slug}?mode=json"
SOURCE_ATS = "lever"


def _assemble_html(posting: dict) -> str:
    """Join a Lever posting's description, list sections and closing into HTML."""
    parts = [posting.get("description", "")]
    for section in posting.get("lists", []):
        heading = section.get("text", "")
        if heading:
            parts.append(f"<h3>{heading}</h3>")
        parts.append(section.get("content", ""))
    parts.append(posting.get("additional", ""))
    return "".join(p for p in parts if p)


def _meta_for(posting: dict, company_name: str) -> dict:
    """Map a Lever posting's structured location fields into a metadata dict.

    Lever gives the richest signal: ``workplaceType`` (onsite/remote/hybrid), a
    2-letter ``country``, and ``categories.allLocations`` (joined into
    ``location_str`` so a multi-site posting matches on any one location).
    """
    categories = posting.get("categories") or {}
    all_locations = [loc for loc in (categories.get("allLocations") or []) if loc]
    location_str = " | ".join(all_locations) or (categories.get("location") or "").strip()
    workplace_type = (posting.get("workplaceType") or "not_stated").lower()
    return build_meta(
        source_url=posting.get("hostedUrl", ""),
        source_ats=SOURCE_ATS,
        company=company_name,
        title=(posting.get("text") or "").strip(),
        location_str=location_str,
        workplace_type=workplace_type,
        is_remote=workplace_type == "remote" or None,
        country=posting.get("country"),
        raw_location_payload={"categories": categories, "workplaceType": posting.get("workplaceType")},
    )


def fetch_company(
    slug: str,
    company_name: str,
    *,
    collected_at: str | None = None,
    sleep=time.sleep,
) -> list[CollectedJob]:
    """Fetch all live postings for ``slug`` from the Lever public API.

    Returns ``CollectedJob`` objects (Tier-4 ``JDRecord`` + metadata sidecar).
    A 404 or persistent 429 is logged and yields ``[]``.
    """
    collected_at = collected_at or date.today().isoformat()
    url = API_TEMPLATE.format(slug=slug)
    try:
        postings = fetch_json(url, sleep=sleep)
    except NotFound:
        log.warning("lever: slug %r (%s) not found (404) — skipping", slug, company_name)
        return []
    except requests.HTTPError as exc:
        log.warning("lever: slug %r (%s) failed: %s — skipping", slug, company_name, exc)
        return []

    jobs = [
        CollectedJob(
            record=build_raw_record(
                source_url=posting.get("hostedUrl", ""),
                source_ats=SOURCE_ATS,
                company=company_name,
                collected_at=collected_at,
                raw_html=_assemble_html(posting),
            ),
            meta=_meta_for(posting, company_name),
        )
        for posting in postings
    ]
    log.info("lever: %s (%s) → %d jobs", company_name, slug, len(jobs))
    return jobs
