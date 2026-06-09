"""prefilter.py — CLI for the pre-label filter (Phase 3).

Cuts a day's raw collection down to the genuinely-relevant postings *before* any
paid Batch labelling, using the structured metadata sidecar (title + location).

    python prefilter.py                      # today's files
    python prefilter.py --date 20260609
    python prefilter.py --dry-run            # report only, write nothing

Pipeline: load raw + meta → clean+dedupe → screen (pipeline.prefilter) → write
survivors → report. The screen logic is pure and lives in pipeline/prefilter.py;
this module does the IO and prints the survivor distribution so thresholds can be
iterated against real numbers before spending on labelling.

Reads : corpus/raw/raw_{date}.jsonl   + corpus/raw/meta_{date}.jsonl
Writes: corpus/filtered/filtered_{date}.jsonl  (JDRecords only — the metadata
        sidecar stays the join source for the later labelling step)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from collections import Counter
from datetime import date

from models.record import JDRecord
from pipeline.dedupe import dedupe
from pipeline.prefilter import screen

log = logging.getLogger(__name__)

RAW_DIR = "corpus/raw"
FILTERED_DIR = "corpus/filtered"


def load_records(path: str) -> list[JDRecord]:
    """Load JDRecords from a raw JSONL file."""
    with open(path, encoding="utf-8") as fh:
        return [JDRecord.from_jsonl(line) for line in fh if line.strip()]


def load_meta(path: str) -> dict[str, dict]:
    """Load the metadata sidecar, indexed by ``source_url``."""
    index: dict[str, dict] = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            meta = json.loads(line)
            index[meta.get("source_url", "")] = meta
    return index


def run(
    records: list[JDRecord],
    meta_index: dict[str, dict],
) -> tuple[list[JDRecord], dict]:
    """Clean+dedupe then screen ``records`` against their metadata.

    Returns ``(survivors, report)``. ``report`` holds counts and distributions
    for the stdout summary. Pure given its inputs (no IO).
    """
    raw_count = len(records)
    kept_records, dropped_dupes = dedupe(records, set())

    survivors: list[JDRecord] = []
    drop_reasons: Counter = Counter()
    role_fail: Counter = Counter()
    loc_fail: Counter = Counter()
    by_company: Counter = Counter()
    by_role_bucket: Counter = Counter()
    by_loc_bucket: Counter = Counter()
    no_meta = 0

    for record in kept_records:
        meta = meta_index.get(record.source_url)
        if meta is None:
            no_meta += 1
            drop_reasons["no_meta"] += 1
            continue
        result = screen(meta)
        if not result.role_keep:
            role_fail[result.role_bucket] += 1
        if not result.loc_keep:
            loc_fail[result.loc_bucket] += 1
        if result.keep:
            survivors.append(record)
            by_company[record.company] += 1
            by_role_bucket[result.role_bucket] += 1
            by_loc_bucket[result.loc_bucket] += 1
        else:
            drop_reasons[result.drop_reason] += 1

    report = {
        "raw_count": raw_count,
        "dropped_dupes": dropped_dupes,
        "deduped_count": len(kept_records),
        "kept_count": len(survivors),
        "no_meta": no_meta,
        "drop_reasons": drop_reasons,
        "role_fail": role_fail,
        "loc_fail": loc_fail,
        "by_company": by_company,
        "by_role_bucket": by_role_bucket,
        "by_loc_bucket": by_loc_bucket,
    }
    return survivors, report


def write_survivors(records: list[JDRecord], path: str) -> str:
    """Write surviving JDRecords to ``path`` (overwrites; not append)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for record in records:
            fh.write(record.to_jsonl() + "\n")
    return path


def _print_counter(title: str, counter: Counter, *, limit: int | None = None) -> None:
    print(f"\n{title}")
    items = counter.most_common(limit)
    if not items:
        print("  (none)")
        return
    width = max(len(str(k)) for k, _ in items)
    for key, n in items:
        print(f"  {str(key).ljust(width)}  {n}")


def print_report(report: dict) -> None:
    raw = report["raw_count"]
    kept = report["kept_count"]
    print("=" * 60)
    print("PRE-LABEL FILTER REPORT")
    print("=" * 60)
    print(f"raw records        : {raw}")
    print(f"  exact dupes dropped: {report['dropped_dupes']}")
    print(f"  unique after dedupe: {report['deduped_count']}")
    if report["no_meta"]:
        print(f"  WARNING no metadata: {report['no_meta']} (treated as dropped)")
    pct = (100 * kept / raw) if raw else 0
    print(f"kept (survivors)   : {kept}  ({pct:.0f}% of raw)")
    print(f"dropped            : {report['deduped_count'] - kept}")

    _print_counter("drop reason (role checked before location):", report["drop_reasons"])
    _print_counter("role-fail breakdown (independent):", report["role_fail"])
    _print_counter("location-fail breakdown (independent):", report["loc_fail"])
    _print_counter("KEPT by company:", report["by_company"])
    _print_counter("KEPT by role bucket:", report["by_role_bucket"])
    _print_counter("KEPT by location bucket:", report["by_loc_bucket"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pre-label filter over raw + metadata.")
    parser.add_argument("--date", default=date.today().strftime("%Y%m%d"), help="YYYYMMDD of the raw/meta files")
    parser.add_argument("--raw", help="Override raw JSONL path")
    parser.add_argument("--meta", help="Override metadata JSONL path")
    parser.add_argument("--out", help="Override survivors output path")
    parser.add_argument("--dry-run", action="store_true", help="Report only; write nothing")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    raw_path = args.raw or os.path.join(RAW_DIR, f"raw_{args.date}.jsonl")
    meta_path = args.meta or os.path.join(RAW_DIR, f"meta_{args.date}.jsonl")
    out_path = args.out or os.path.join(FILTERED_DIR, f"filtered_{args.date}.jsonl")

    records = load_records(raw_path)
    meta_index = load_meta(meta_path)
    survivors, report = run(records, meta_index)

    print_report(report)

    if args.dry_run:
        print(f"\n[dry-run] would write {len(survivors)} survivors to {out_path}")
        return 0

    write_survivors(survivors, out_path)
    print(f"\nWrote {len(survivors)} survivors to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
