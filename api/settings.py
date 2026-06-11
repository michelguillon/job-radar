"""api/settings.py — corpus path resolution (test-injectable).

Every path the API reads or appends to is resolved here, from the environment, with
defaults = the ``cli.track`` / ``cli.stats`` constants (the same files the CLI uses, so
the CLI and the API are always two write paths over one set of files). Tests point these
at ``tmp_path`` by overriding ``get_settings`` via ``app.dependency_overrides`` — nothing
in a test touches the real corpus.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from cli.collect import SEEDS_PATH
from cli.stats import ANNOTATIONS_PATH, CV_TAILOR_LINKS_PATH, INDEX_PATH, STATS_PATH
from cli.track import LOG_PATH, META_GLOB, SCORED_GLOB, VALIDATED_GLOB

# ANNOTATIONS_PATH (field-level scoring flags, separate from the activity log) is the
# canonical read-model constant in cli.stats — re-exported here so the API and the index
# export resolve the same file.


@dataclass(frozen=True)
class Settings:
    log_path: str
    scored_glob: str
    validated_glob: str
    meta_glob: str
    index_path: str
    annotations_path: str
    # Yield report inputs (BACKLOG_YIELD_TRACKING). Defaulted so existing Settings(...)
    # construction (e.g. the API test fixtures) keeps working without these.
    seeds_path: str = SEEDS_PATH
    stats_path: str = STATS_PATH
    # cv-tailor run links (job_radar_SPEC §11.3). Defaulted for the same reason.
    cv_tailor_links_path: str = CV_TAILOR_LINKS_PATH


def get_settings() -> Settings:
    """Resolve corpus paths from env (defaults = the CLI constants). FastAPI dependency."""
    return Settings(
        log_path=os.environ.get("JR_LOG_PATH", LOG_PATH),
        scored_glob=os.environ.get("JR_SCORED_GLOB", SCORED_GLOB),
        validated_glob=os.environ.get("JR_VALIDATED_GLOB", VALIDATED_GLOB),
        meta_glob=os.environ.get("JR_META_GLOB", META_GLOB),
        index_path=os.environ.get("JR_INDEX_PATH", INDEX_PATH),
        annotations_path=os.environ.get("JR_ANNOTATIONS_PATH", ANNOTATIONS_PATH),
        seeds_path=os.environ.get("JR_SEEDS_PATH", SEEDS_PATH),
        stats_path=os.environ.get("JR_STATS_PATH", STATS_PATH),
        cv_tailor_links_path=os.environ.get("JR_CV_TAILOR_LINKS_PATH", CV_TAILOR_LINKS_PATH),
    )
