"""VC portfolio job board collector — skeleton (docs/job_radar_SPEC.md §5.3 Step 5).

Step 5 gate outcome (2026-06-09): every board in ``vc_boards.yaml`` is a
JavaScript-rendered SPA (Consider, Getro, custom Vue+Elasticsearch) with no
accessible public API. The raw HTML contains only framework scaffolding — zero
job listings — so the spec's BeautifulSoup-only constraint cannot be satisfied
for any board. All boards are marked ``status: requires_js`` and skipped.

This module therefore loads the config and logs each board as skipped, then
returns no records. It exists so ``collect.py --source vc_boards`` exits cleanly
and the deferral is explicit in the pipeline rather than silently absent.

TODO: VC board scraping requires Playwright or a paid aggregator API
(e.g. Apify VC portfolio scraper) — deferred to Phase 4 Discovery Layer.
"""

from __future__ import annotations

import logging
import time
from datetime import date

import yaml

from collectors.base import CollectedJob

log = logging.getLogger(__name__)

CONFIG_PATH = "vc_boards.yaml"
SOURCE_ATS = "vc_board"


def load_boards(path: str = CONFIG_PATH) -> list[dict]:
    """Load the board list from ``vc_boards.yaml``."""
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)["boards"]


def collect(
    *,
    collected_at: str | None = None,
    path: str = CONFIG_PATH,
) -> list[CollectedJob]:
    """Attempt to collect from VC boards.

    Every board is currently ``requires_js`` and skipped, so this always returns
    ``[]`` — but it logs a clear, per-board reason so the skip is visible.
    """
    collected_at = collected_at or date.today().isoformat()  # noqa: F841 — reserved for future scrapers
    records: list[CollectedJob] = []

    for board in load_boards(path):
        name = board.get("name", "?")
        status = board.get("status")
        if status == "requires_js":
            platform = board.get("platform", "unknown")
            notes = board.get("notes", "").strip()
            log.warning("vc_boards: SKIP %s (platform=%s, requires_js) — %s", name, platform, notes)
            continue
        # No board has a working BeautifulSoup scraper yet; treat any other
        # status as not-yet-implemented rather than silently doing nothing.
        log.warning("vc_boards: SKIP %s — no BeautifulSoup scraper implemented (status=%s)", name, status)

    log.info("vc_boards: %d records (all boards JS-rendered — see TODO, deferred to Phase 4)", len(records))
    return records
