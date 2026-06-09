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

from collectors.base import NotFound, build_raw_record, fetch_json
from models.record import JDRecord

log = logging.getLogger(__name__)

API_TEMPLATE = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
SOURCE_ATS = "greenhouse"


def fetch_company(
    slug: str,
    company_name: str,
    *,
    collected_at: str | None = None,
    sleep=time.sleep,
) -> list[JDRecord]:
    """Fetch all live jobs for ``slug`` from the Greenhouse public API.

    Returns a list of Tier-4 ``JDRecord`` objects with extraction fields unset.
    A 404 (unknown slug) or persistent 429 is logged and yields ``[]`` so a
    batch run continues past one bad company.
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

    records: list[JDRecord] = []
    for job in data.get("jobs", []):
        records.append(
            build_raw_record(
                source_url=job.get("absolute_url", ""),
                source_ats=SOURCE_ATS,
                company=company_name,
                collected_at=collected_at,
                raw_html=html.unescape(job.get("content") or ""),
            )
        )
    log.info("greenhouse: %s (%s) → %d jobs", company_name, slug, len(records))
    return records
