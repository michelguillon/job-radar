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

from collectors.base import NotFound, build_raw_record, fetch_json
from models.record import JDRecord

log = logging.getLogger(__name__)

API_TEMPLATE = "https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"
SOURCE_ATS = "ashby"


def fetch_company(
    slug: str,
    company_name: str,
    *,
    collected_at: str | None = None,
    sleep=time.sleep,
) -> list[JDRecord]:
    """Fetch all live jobs for ``slug`` from the Ashby job-board API.

    Returns Tier-4 ``JDRecord`` objects with extraction fields unset. A 404 or
    persistent 429 is logged and yields ``[]``.
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

    records = []
    for job in data.get("jobs", []):
        raw_html = job.get("descriptionHtml")
        records.append(
            build_raw_record(
                source_url=job.get("jobUrl", ""),
                source_ats=SOURCE_ATS,
                company=company_name,
                collected_at=collected_at,
                raw_html=raw_html,
                raw_text="" if raw_html else job.get("descriptionPlain", ""),
            )
        )
    log.info("ashby: %s (%s) → %d jobs", company_name, slug, len(records))
    return records
