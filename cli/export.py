"""export.py — fine-tuning export (job_radar_SPEC §5.3 Step 9).

    python export.py --set eval     # Tier 1+2+3 only
    python export.py --set train    # all tiers
    python export.py --set full     # everything

Emits one ``{"prompt": <full JD text>, "completion": <extraction JSON string>}``
per line to corpus/finetune_export/export_{set}_{timestamp}.jsonl. The
completion is the 17 extraction fields serialised as a JSON string — exactly
what a fine-tuned extractor should learn to produce.

Exclusions (all sets): wrong schema_version (won't parse), records that fail
schema validation, and unlabelled records (no extraction). Tier 4 is excluded
from the eval set.

NOTE: with these exclusions, ``train`` and ``full`` currently select the same
records (all tiers, validated) — the spec text distinguishes them but does not
yet say how. Kept as separate modes pending the spec update; ``full`` applies no
tier filter so it stays a true superset if new tiers/record types appear.
"""

from __future__ import annotations

import argparse
import glob
import json
import logging
import os
from collections import Counter
from datetime import datetime, timezone

from models.record import _EXTRACTION_FIELDS, JDRecord, SchemaVersionError, validate

OUT_DIR = "corpus/finetune_export"
DEFAULT_INPUT = "corpus/validated/validated_*.jsonl"

# corpus/calibration/ holds scorer-regression FIXTURES (deliberately negative /
# thin / synthetic). They are never training data — excluded from every export
# set regardless of the input glob (Option 1 corpus-hygiene decision, 2026-06-09).
EXCLUDE_PATH_MARKER = "calibration"

# eval omits Tier 4 (automated, unreviewed); train = all tiers; full = no filter.
SET_TIERS = {
    "eval": {1, 2, 3},
    "train": {1, 2, 3, 4},
    "full": None,
}


def load_records(input_glob: str) -> list[JDRecord]:
    """Parse records, silently skipping wrong-schema_version / unparseable lines."""
    records: list[JDRecord] = []
    for path in sorted(glob.glob(input_glob, recursive=True)):
        if EXCLUDE_PATH_MARKER in path.replace(os.sep, "/"):
            logging.getLogger("export").info("skipping calibration fixtures: %s", path)
            continue
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    records.append(JDRecord.from_jsonl(line))
                except (SchemaVersionError, ValueError, json.JSONDecodeError):
                    continue
    return records


def is_exportable(record: JDRecord) -> bool:
    """A record is exportable if it is labelled (has extraction) and schema-valid."""
    return record.role_type is not None and not validate(record)


def select(records: list[JDRecord], set_name: str) -> list[JDRecord]:
    tiers = SET_TIERS[set_name]
    return [
        r for r in records
        if is_exportable(r) and (tiers is None or r.tier in tiers)
    ]


def to_pair(record: JDRecord) -> dict:
    """Return the ``{"prompt", "completion"}`` training pair for one record."""
    extraction = {f: getattr(record, f) for f in _EXTRACTION_FIELDS}
    return {
        "prompt": record.raw_text,
        "completion": json.dumps(extraction, ensure_ascii=False),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export prompt/completion pairs for fine-tuning.")
    parser.add_argument("--set", choices=tuple(SET_TIERS), required=True, dest="set_name")
    parser.add_argument("--input", default=DEFAULT_INPUT, help=f"Glob for validated JSONL (default: {DEFAULT_INPUT})")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    records = load_records(args.input)
    selected = select(records, args.set_name)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"export_{args.set_name}_{ts}.jsonl")
    with open(path, "w", encoding="utf-8") as fh:
        for record in selected:
            fh.write(json.dumps(to_pair(record), ensure_ascii=False) + "\n")

    per_tier = dict(sorted(Counter(r.tier for r in selected).items()))
    print(f"Exported {len(selected)} pair(s) ({args.set_name}) from {len(records)} record(s).")
    print(f"By tier: {per_tier}")
    print(f"Export → {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
