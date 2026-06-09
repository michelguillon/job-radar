"""build_score_subset.py — first production scoring subset (Phase 3).

Selects a representative subset of the pre-label filter survivors for the first
real labelling + scoring run, so the run isn't distorted by Databricks
over-representation (23 of 62 survivors, skewed to technically-deep roles where
Michel is less likely to be feasible) and the labelling budget isn't spent on
many near-adjacent false positives.

Selection rules (Michel, 2026-06-09):
  - Keep ALL non-Databricks survivors.
  - For Databricks, pick 5 representative roles across the most relevant buckets,
    preferring UK/London:
      1 Forward Deployed / AI Engineer · 1 Deployment Strategist ·
      1 Delivery Solutions Architect · 1 Senior Solutions Architect ·
      1 Product / GTM / partner-adjacent (if present).
  - Cap "Customer Success Manager" titles at 2 (prefer UK/London) — borderline but
    kept to test whether the scorer separates technical/strategic CSM from pure
    account-management CSM.

Sets each selected record's raw_text to the human-readable cleaned JD
(clean_readable — HTML stripped, line breaks + case preserved) so the labeller
reads a normal JD and the scorer's first-line title heuristic behaves. The ATS
title/location stay in the sidecar (meta_{date}.jsonl), passed to the labeller as
separate context — never injected into raw_text.

    python -m scripts.build_score_subset \
        --filtered corpus/filtered/filtered_20260609.jsonl \
        --meta corpus/raw/meta_20260609.jsonl \
        --out corpus/labelled_input/subset_20260609.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import re

from models.record import JDRecord
from pipeline.clean import clean_readable

# Databricks role buckets, in selection order. Each picks one survivor whose title
# matches, preferring a UK/London location. A record is assigned to the first
# bucket it matches so it can't be picked twice.
DATABRICKS_BUCKETS = [
    ("Forward Deployed / AI Engineer", re.compile(r"forward deployed|\bfde\b|ai engineer", re.I)),
    ("Deployment Strategist", re.compile(r"deployment strategist", re.I)),
    ("Delivery Solutions Architect", re.compile(r"delivery solutions architect", re.I)),
    ("Senior Solutions Architect", re.compile(r"senior solutions architect", re.I)),
    ("Product / GTM / Partner", re.compile(r"product|gtm|go-to-market|partner|alliance", re.I)),
]
_CSM_RE = re.compile(r"customer success manager", re.I)


def _is_uk(meta: dict) -> bool:
    loc = (meta.get("location_str") or "").lower()
    country = (meta.get("country") or "").upper()
    return "london" in loc or "united kingdom" in loc or bool(re.search(r"\buk\b", loc)) or country in {"GB", "UK", "UNITED KINGDOM"}


def _prefer_uk(records, meta_index):
    """Sort UK/London first, then by title, for deterministic selection."""
    return sorted(records, key=lambda r: (0 if _is_uk(meta_index.get(r.source_url, {})) else 1,
                                          (meta_index.get(r.source_url, {}).get("title") or "")))


def select(records: list[JDRecord], meta_index: dict, *, databricks_n: int = 5, csm_max: int = 2):
    """Return (selected_records, log_rows). Pure given its inputs."""
    non_dbx = [r for r in records if r.company != "Databricks"]
    dbx = [r for r in records if r.company == "Databricks"]

    # --- Databricks: one per bucket, UK-preferred, no double-pick ---
    picked_dbx, used = [], set()
    for _name, rx in DATABRICKS_BUCKETS:
        if len(picked_dbx) >= databricks_n:
            break
        candidates = [r for r in dbx if r.source_url not in used
                      and rx.search(meta_index.get(r.source_url, {}).get("title", ""))]
        for r in _prefer_uk(candidates, meta_index):
            picked_dbx.append(r)
            used.add(r.source_url)
            break

    selected = non_dbx + picked_dbx

    # --- Cap Customer Success Manager titles at csm_max (UK-preferred) ---
    csm = [r for r in selected if _CSM_RE.search(meta_index.get(r.source_url, {}).get("title", ""))]
    if len(csm) > csm_max:
        keep_csm = set(r.source_url for r in _prefer_uk(csm, meta_index)[:csm_max])
        selected = [r for r in selected
                    if not _CSM_RE.search(meta_index.get(r.source_url, {}).get("title", ""))
                    or r.source_url in keep_csm]

    log_rows = [
        {
            "company": r.company,
            "title": meta_index.get(r.source_url, {}).get("title", ""),
            "location": meta_index.get(r.source_url, {}).get("location_str", ""),
            "databricks": r.company == "Databricks",
        }
        for r in selected
    ]
    return selected, log_rows


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Build the first production scoring subset.")
    p.add_argument("--filtered", default="corpus/filtered/filtered_20260609.jsonl")
    p.add_argument("--meta", default="corpus/raw/meta_20260609.jsonl")
    p.add_argument("--out", default="corpus/labelled_input/subset_20260609.jsonl")
    p.add_argument("--databricks-n", type=int, default=5)
    p.add_argument("--csm-max", type=int, default=2)
    args = p.parse_args(argv)

    records = [JDRecord.from_jsonl(l) for l in open(args.filtered, encoding="utf-8") if l.strip()]
    meta_index = {m["source_url"]: m for m in
                  (json.loads(l) for l in open(args.meta, encoding="utf-8") if l.strip())}

    selected, log_rows = select(records, meta_index, databricks_n=args.databricks_n, csm_max=args.csm_max)

    # Populate raw_text with the readable cleaned JD for labelling + scoring.
    for r in selected:
        if r.raw_html:
            r.raw_text = clean_readable(r.raw_html)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        for r in selected:
            fh.write(r.to_jsonl() + "\n")

    dbx = [row for row in log_rows if row["databricks"]]
    print(f"SUBSET: {len(selected)} records ({len(selected) - len(dbx)} non-Databricks + {len(dbx)} Databricks)")
    print(f"\nDatabricks picks ({len(dbx)}):")
    for row in dbx:
        print(f"  - {row['title']}  |  {row['location']}")
    print(f"\nNon-Databricks ({len(selected) - len(dbx)}):")
    for row in sorted(log_rows, key=lambda x: (x["company"], x["title"])):
        if not row["databricks"]:
            print(f"  {row['company']:14} {row['title']}  |  {row['location']}")
    print(f"\nWrote → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
