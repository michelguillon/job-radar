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

from cli.stats import INDEX_PATH
from cli.track import LOG_PATH, META_GLOB, SCORED_GLOB, VALIDATED_GLOB

# New Phase-6 sink: field-level scoring flags (separate from the activity log).
ANNOTATIONS_PATH = "corpus/annotations.jsonl"


@dataclass(frozen=True)
class Settings:
    log_path: str
    scored_glob: str
    validated_glob: str
    meta_glob: str
    index_path: str
    annotations_path: str


def get_settings() -> Settings:
    """Resolve corpus paths from env (defaults = the CLI constants). FastAPI dependency."""
    return Settings(
        log_path=os.environ.get("JR_LOG_PATH", LOG_PATH),
        scored_glob=os.environ.get("JR_SCORED_GLOB", SCORED_GLOB),
        validated_glob=os.environ.get("JR_VALIDATED_GLOB", VALIDATED_GLOB),
        meta_glob=os.environ.get("JR_META_GLOB", META_GLOB),
        index_path=os.environ.get("JR_INDEX_PATH", INDEX_PATH),
        annotations_path=os.environ.get("JR_ANNOTATIONS_PATH", ANNOTATIONS_PATH),
    )
