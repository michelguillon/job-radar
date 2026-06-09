"""label.py — CLI for Claude Batch API labelling (job_radar_SPEC §5.3 Step 7).

    python label.py --input "corpus/raw/clean_*.jsonl" --tier 4

Reads cleaned JSONL, submits a Claude Batch extraction job, waits for it, merges
the results, and writes:
  - corpus/labelled/labelled_{timestamp}.jsonl   (successfully extracted, tier set)
  - corpus/labelled/failures_{timestamp}.jsonl   (errored / unparseable)
and appends a cost summary to corpus/stats.json after the run.

``--tier`` accepts 3 or 4 only — the Claude-labelled tiers (Tier 1/2 are human).
"""

from __future__ import annotations

import argparse
import glob
import json
import logging
import os
from datetime import datetime, timezone

from models.record import JDRecord
from pipeline import label

OUT_DIR = "corpus/labelled"
STATS_PATH = "corpus/stats.json"


def load_records(input_glob: str) -> list[JDRecord]:
    records: list[JDRecord] = []
    for path in sorted(glob.glob(input_glob)):
        with open(path, encoding="utf-8") as fh:
            records.extend(JDRecord.from_jsonl(line) for line in fh if line.strip())
    return records


def _write_jsonl(path: str, records) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for r in records:
            fh.write((r.to_jsonl() if isinstance(r, JDRecord) else json.dumps(r, ensure_ascii=False)) + "\n")


def append_stats(entry: dict, path: str = STATS_PATH) -> None:
    """Append a run entry to the corpus/stats.json array (created if absent)."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    runs = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            try:
                runs = json.load(fh)
            except json.JSONDecodeError:
                runs = []
    runs.append(entry)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(runs, fh, ensure_ascii=False, indent=2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Label cleaned JDs via the Claude Batch API.")
    parser.add_argument("--input", required=True, help="Glob for cleaned JSONL (e.g. 'corpus/raw/clean_*.jsonl')")
    parser.add_argument("--tier", type=int, choices=(3, 4), required=True, help="Tier to assign (3 or 4 — Claude-labelled)")
    parser.add_argument("--poll-interval", type=int, default=30, help="Seconds between batch status polls")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    records = load_records(args.input)
    if not records:
        print("No records to label.")
        return 0
    print(f"Labelling {len(records)} record(s) at tier {args.tier} via Claude Batch API…")

    batch_id = label.run_batch(records)
    label.poll_batch(batch_id, interval=args.poll_interval)
    results = label.download_results(batch_id)
    labelled, failures = label.merge_results(records, results, tier=args.tier)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    labelled_path = os.path.join(OUT_DIR, f"labelled_{ts}.jsonl")
    _write_jsonl(labelled_path, labelled)
    failures_path = None
    if failures:
        failures_path = os.path.join(OUT_DIR, f"failures_{ts}.jsonl")
        _write_jsonl(failures_path, failures)

    cost = label.estimate_cost(results)
    append_stats(
        {
            "run": ts,
            "step": "label",
            "batch_id": batch_id,
            "tier": args.tier,
            "records": len(records),
            "labelled": len(labelled),
            "failed": len(failures),
            **cost,
        }
    )

    print(f"\nLabelled {len(labelled)}/{len(records)} (failed: {len(failures)}).")
    print(f"Cost: ${cost['cost_usd']:.4f}  tokens={cost['tokens']}")
    print(f"Labelled → {labelled_path}")
    if failures_path:
        print(f"Failures → {failures_path}")
    print(f"Stats    → {STATS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
