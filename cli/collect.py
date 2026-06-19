"""collect.py — CLI entry point for the collection phase.

Reads company slugs from ``company_seeds.yaml``, routes each company to the
collector for its ``ats``, and appends the raw ``JDRecord`` objects to
``corpus/raw/raw_{YYYYMMDD}.jsonl``.

    python collect.py --source greenhouse
    python collect.py --source greenhouse --company anthropic
    python collect.py --source all
    python collect.py --dry-run

Collectors do not extract or deduplicate — that happens in later pipeline
steps. ``--dry-run`` reports the record count without writing anything.

Lever, Ashby and VC-board collectors are registered here as they are built
(Steps 4–5); until then a company on an unregistered ATS is logged and skipped.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

from collectors import ashby, greenhouse, lever, vc_boards

log = logging.getLogger(__name__)

SEEDS_PATH = "company_seeds.yaml"
RAW_DIR = "corpus/raw"
CURSOR_DIR = "corpus"

# ATS name -> collector module. The module exposes fetch_company(...) plus the
# SUPPORTS_INCREMENTAL flag, so the incremental-source set is derived, not
# hand-maintained.
COLLECTOR_MODULES = {
    "greenhouse": greenhouse,
    "lever": lever,
    "ashby": ashby,
}
COLLECTORS = {name: m.fetch_company for name, m in COLLECTOR_MODULES.items()}

# Sources whose public API exposes a per-job timestamp we can filter on
# client-side (greenhouse: updated_at, ashby: publishedAt). Lever has none, so it
# is excluded and always does a full collection. See collectors/CLAUDE.md.
INCREMENTAL_SOURCES = frozenset(
    name for name, m in COLLECTOR_MODULES.items() if getattr(m, "SUPPORTS_INCREMENTAL", False)
)

# vc_boards is collected by board (vc_boards.yaml), not by company slug, so it
# routes through vc_boards.collect() rather than the COLLECTORS registry.
SOURCES = (*sorted(COLLECTORS), "vc_boards", "all")


# --- incremental cursor (per source; gitignored under corpus/) ---------------
# The cursor records the START timestamp of the last successful collection for a
# source. Using the start (not finish) means a job updated *during* a run is
# re-collected next time rather than skipped. Falls back to full collection when
# no cursor exists. See collectors/CLAUDE.md + job_radar_SPEC §8.

def cursor_path(source: str, cursor_dir: str | None = None) -> str:
    return os.path.join(cursor_dir if cursor_dir is not None else CURSOR_DIR, f".last_collected_{source}")


def read_cursor(source: str, cursor_dir: str | None = None) -> str | None:
    path = cursor_path(source, cursor_dir)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return fh.read().strip() or None


def write_cursor(source: str, ts: str, cursor_dir: str | None = None) -> None:
    target = cursor_dir if cursor_dir is not None else CURSOR_DIR
    os.makedirs(target, exist_ok=True)
    with open(cursor_path(source, target), "w", encoding="utf-8") as fh:
        fh.write(ts)


def load_companies(path: str = SEEDS_PATH) -> list[dict]:
    """Load the company seed list from ``company_seeds.yaml``.

    Accepts either a bare top-level list (the v2 metadata format) or a
    ``{companies: [...]}`` mapping (the v1.1 wrapped format) — both ship from
    the same generator and either is valid. Each entry is ``{name, ats, slug}``
    plus the optional v2 metadata (``domain``, ``fit_hypothesis``, ``action``,
    ``notes``) — all optional, missing → absent (the consumer defaults them).
    """
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data["companies"] if isinstance(data, dict) else data


def load_company_seeds(db=None) -> list[dict]:
    """Load the company universe from SQLite (the source of truth after the seeds migration,
    SPEC_COMPANY_SEEDS_DB / deviation 55), excluding ``action='remove'`` companies.

    Falls back to ``company_seeds.yaml`` when the table is empty (a fresh install before the
    one-shot ``python -m cli.seeds import`` has run), logging a warning. ``db`` is injectable
    for tests; when None a connection is opened (and closed) here.
    """
    own = db is None
    if own:
        from cli.db import get_db, init_db
        init_db()  # idempotent CREATE TABLE IF NOT EXISTS — ensures the table exists to query
        db = get_db()
    try:
        rows = db.execute(
            "SELECT * FROM company_seeds WHERE action NOT IN ('remove') ORDER BY name"
        ).fetchall()
        if rows:
            return [dict(r) for r in rows]
    finally:
        if own:
            db.close()

    # Fallback: empty table (fresh install before migration). Read the YAML directly.
    seeds_path = Path(SEEDS_PATH)
    if seeds_path.exists():
        log.warning("company_seeds table empty — falling back to %s", SEEDS_PATH)
        return load_companies(SEEDS_PATH)
    return []


def select(companies: list[dict], source: str, company: str | None) -> list[dict]:
    """Filter the seed list by ``--source`` (ATS, or ``all``) and ``--company``.

    ``--company`` matches either the slug or the display name, case-insensitively.
    Manual watch entries (``slug: null``) only match by name — they carry no slug.
    """
    selected = []
    for c in companies:
        if source != "all" and c["ats"] != source:
            continue
        if company is not None and company.lower() not in (
            (c.get("slug") or "").lower(),
            c["name"].lower(),
        ):
            continue
        selected.append(c)
    return selected


def collect(
    companies: list[dict],
    *,
    registry: dict | None = None,
    collected_at: str | None = None,
    updated_after_by_source: dict | None = None,
) -> list:
    """Run the matching collector for each company and return all CollectedJobs.

    ``updated_after_by_source`` maps an ATS name to its incremental cursor (or
    None for full collection); each company's collector is passed the cursor for
    its source. Non-incremental sources are simply absent from the map.
    """
    registry = COLLECTORS if registry is None else registry
    cursors = updated_after_by_source or {}
    jobs = []
    for c in companies:
        # Editorial `action` is advisory in v1 (BACKLOG_YIELD_TRACKING §8): `pause`
        # logs a skip notice but still collects (no automatic behaviour change yet);
        # `investigate_ats` is surfaced only in the yield report. Neither alters flow.
        if c.get("action") == "pause":
            log.info("action=pause for %s — still collecting in v1 (skip is a future enhancement)", c["name"])
        fetch = registry.get(c["ats"])
        if fetch is None:
            # ats=manual (slug: null) watch entries land here too — logged and skipped
            # cleanly, never an error (BACKLOG_YIELD_TRACKING — manual watch entries).
            log.info("no collector for ats %r (%s) — skipping", c["ats"], c["name"])
            continue
        jobs.extend(
            fetch(c["slug"], c["name"], collected_at=collected_at, updated_after=cursors.get(c["ats"]))
        )
    return jobs


def write_records(jobs: list, *, out_dir: str = RAW_DIR, date_str: str | None = None) -> str:
    """Append the raw ``JDRecord`` of each CollectedJob to ``raw_{YYYYMMDD}.jsonl``.

    Returns the path written to. Creates ``out_dir`` if needed.
    """
    date_str = date_str or date.today().strftime("%Y%m%d")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"raw_{date_str}.jsonl")
    with open(path, "a", encoding="utf-8") as fh:
        for job in jobs:
            fh.write(job.record.to_jsonl() + "\n")
    return path


def write_meta(jobs: list, *, out_dir: str = RAW_DIR, date_str: str | None = None) -> str:
    """Append each CollectedJob's metadata sidecar to ``meta_{YYYYMMDD}.jsonl``.

    The sidecar holds the structured title + location signal (keyed by
    ``source_url``) used by the pre-label filter and, later, the extraction
    prompt. ``raw_text`` is never modified — this stays a separate artifact.
    """
    date_str = date_str or date.today().strftime("%Y%m%d")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"meta_{date_str}.jsonl")
    with open(path, "a", encoding="utf-8") as fh:
        for job in jobs:
            fh.write(json.dumps(job.meta, ensure_ascii=False) + "\n")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect raw JDs from ATS sources.")
    parser.add_argument("--source", default="all", choices=SOURCES, help="ATS to collect from (default: all)")
    parser.add_argument("--company", help="Restrict to one company (slug or name)")
    parser.add_argument("--dry-run", action="store_true", help="Print count without writing")
    parser.add_argument(
        "--full",
        action="store_true",
        help="Ignore incremental cursors and re-fetch everything (after a schema change or for debugging)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    # Cursor is the run START (so a job updated mid-run is re-caught next time).
    run_start = datetime.now(timezone.utc).isoformat()
    companies = select(load_company_seeds(), args.source, args.company)
    selected_sources = {c["ats"] for c in companies}

    # Per-source incremental cursor: only for sources that support it, only when
    # not --full. A missing cursor → None → full collection for that source.
    updated_after_by_source = {
        src: (None if args.full else read_cursor(src))
        for src in selected_sources & INCREMENTAL_SOURCES
    }
    incremental = {s: c for s, c in updated_after_by_source.items() if c}
    if incremental:
        log.info("incremental collection from cursors: %s", incremental)

    jobs = collect(companies, updated_after_by_source=updated_after_by_source)

    # VC boards are board-based, not company-based, and currently all skipped.
    if args.source in ("vc_boards", "all"):
        jobs.extend(vc_boards.collect())

    if args.dry_run:
        print(f"[dry-run] {len(jobs)} records from {len(companies)} companies (not written)")
        return 0

    raw_path = write_records(jobs)
    meta_path = write_meta(jobs)

    # Advance each incremental source's cursor to this run's start — but only on a
    # full-source run (no --company) and only for a source that actually returned
    # jobs, so a --company subset or a transient total-fetch failure never skips
    # postings on the next run.
    counts = Counter(job.record.source_ats for job in jobs)
    advanced = []
    if args.company is None:
        for src in sorted(selected_sources & INCREMENTAL_SOURCES):
            if counts.get(src, 0) > 0:
                write_cursor(src, run_start)
                advanced.append(src)

    print(f"Wrote {len(jobs)} records to {raw_path} and metadata to {meta_path}")
    if advanced:
        print(f"Cursor advanced to {run_start} for: {', '.join(advanced)}")
    elif args.company is not None:
        print("(--company run — cursors not advanced)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
