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
import logging
import os
from datetime import date

import yaml

from collectors import ashby, greenhouse, lever

log = logging.getLogger(__name__)

SEEDS_PATH = "company_seeds.yaml"
RAW_DIR = "corpus/raw"

# ATS name -> fetch_company(slug, company_name, *, collected_at=...) callable.
COLLECTORS = {
    "greenhouse": greenhouse.fetch_company,
    "lever": lever.fetch_company,
    "ashby": ashby.fetch_company,
}

SOURCES = (*sorted({"greenhouse", "lever", "ashby", "vc_board"}), "all")


def load_companies(path: str = SEEDS_PATH) -> list[dict]:
    """Load the company seed list from ``company_seeds.yaml``."""
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)["companies"]


def select(companies: list[dict], source: str, company: str | None) -> list[dict]:
    """Filter the seed list by ``--source`` (ATS, or ``all``) and ``--company``.

    ``--company`` matches either the slug or the display name, case-insensitively.
    """
    selected = []
    for c in companies:
        if source != "all" and c["ats"] != source:
            continue
        if company is not None and company.lower() not in (
            c["slug"].lower(),
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
) -> list:
    """Run the matching collector for each company and return all records."""
    registry = COLLECTORS if registry is None else registry
    records = []
    for c in companies:
        fetch = registry.get(c["ats"])
        if fetch is None:
            log.warning("no collector for ats %r (%s) — skipping", c["ats"], c["name"])
            continue
        records.extend(fetch(c["slug"], c["name"], collected_at=collected_at))
    return records


def write_records(records: list, *, out_dir: str = RAW_DIR, date_str: str | None = None) -> str:
    """Append records as JSONL to ``corpus/raw/raw_{YYYYMMDD}.jsonl``.

    Returns the path written to. Creates ``out_dir`` if needed.
    """
    date_str = date_str or date.today().strftime("%Y%m%d")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"raw_{date_str}.jsonl")
    with open(path, "a", encoding="utf-8") as fh:
        for record in records:
            fh.write(record.to_jsonl() + "\n")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect raw JDs from ATS sources.")
    parser.add_argument("--source", default="all", choices=SOURCES, help="ATS to collect from (default: all)")
    parser.add_argument("--company", help="Restrict to one company (slug or name)")
    parser.add_argument("--dry-run", action="store_true", help="Print count without writing")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    companies = select(load_companies(), args.source, args.company)
    records = collect(companies)

    if args.dry_run:
        print(f"[dry-run] {len(records)} records from {len(companies)} companies (not written)")
        return 0

    path = write_records(records)
    print(f"Wrote {len(records)} records to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
