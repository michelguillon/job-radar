"""stats.py — corpus statistics + UI index export (job_radar_SPEC §5.3 Step 8).

    python stats.py --input "corpus/**/*.jsonl"            # print a summary
    python stats.py --input "corpus/validated/*.jsonl" --export-index

``--export-index`` writes ``corpus/index.json``: a flat JSON array of every
record with all fields denormalised (extraction + annotation lifted to the top
level). This is the read-only data contract for the Phase 5 UI — pre-built by
this CLI, never written by the UI.
"""

from __future__ import annotations

import argparse
import glob
import json
import logging
from collections import Counter
from dataclasses import asdict

from models.record import SCHEMA_VERSION, JDRecord

INDEX_PATH = "corpus/index.json"


def load_records(input_glob: str) -> list[JDRecord]:
    records: list[JDRecord] = []
    for path in sorted(glob.glob(input_glob, recursive=True)):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    records.append(JDRecord.from_jsonl(line))
    return records


def _counts(values) -> dict:
    """Counter as an insertion-friendly dict sorted by count desc."""
    return dict(Counter(values).most_common())


def summarize(records: list[JDRecord]) -> dict:
    """Return a summary dict over the corpus."""
    fit = [r.fit_score for r in records if r.fit_score is not None]
    return {
        "total": len(records),
        "by_tier": _counts(r.tier for r in records),
        "by_source_ats": _counts(r.source_ats for r in records),
        "by_role_type": _counts(rt for r in records for rt in (r.role_type or [])),
        "by_domain": _counts(d for r in records for d in (r.domain or [])),
        "by_application_decision": _counts(r.application_decision for r in records),
        "applied_count": sum(1 for r in records if r.applied),
        "fit_score": {
            "n": len(fit),
            "mean": round(sum(fit) / len(fit), 2) if fit else None,
            "min": min(fit) if fit else None,
            "max": max(fit) if fit else None,
        },
    }


def print_summary(summary: dict) -> None:
    print(f"Corpus: {summary['total']} records")

    def section(title, mapping):
        print(f"\n{title}:")
        for k, v in mapping.items():
            print(f"  {k}: {v}")

    section("By tier", summary["by_tier"])
    section("By source", summary["by_source_ats"])
    section("By role_type", summary["by_role_type"])
    section("By domain", summary["by_domain"])
    section("By application_decision", summary["by_application_decision"])
    fs = summary["fit_score"]
    print(f"\nApplied: {summary['applied_count']}")
    print(f"fit_score: n={fs['n']} mean={fs['mean']} min={fs['min']} max={fs['max']}")


def export_index(records: list[JDRecord], path: str = INDEX_PATH) -> str:
    """Write a flat (denormalised) JSON array of all records for the UI."""
    flat = [{"schema_version": SCHEMA_VERSION, **asdict(r)} for r in records]
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(flat, fh, ensure_ascii=False, indent=2)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Corpus statistics and UI index export.")
    parser.add_argument("--input", required=True, help="Glob for JSONL records (recursive ** supported)")
    parser.add_argument("--export-index", action="store_true", help="Also write corpus/index.json for the UI")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    records = load_records(args.input)
    print_summary(summarize(records))

    if args.export_index:
        path = export_index(records)
        print(f"\nIndex → {path} ({len(records)} records)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
