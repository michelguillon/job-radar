"""validate.py — CLI for schema validation (job_radar_SPEC §5.3 Step 8).

    python validate.py --input "corpus/labelled/labelled_*.jsonl"

Reads labelled JSONL and writes, into corpus/validated/:
  - validated_{timestamp}.jsonl  — records that pass schema v1.2
  - failures_{timestamp}.jsonl   — records that fail, each with a
    "validation_errors" list (also covers unparseable / wrong-schema_version lines)
"""

from __future__ import annotations

import argparse
import glob
import json
import logging
import os
from datetime import datetime, timezone

from models.record import JDRecord, SchemaVersionError
from pipeline.validate import validate_records

OUT_DIR = "corpus/validated"


def load_lines(input_glob: str) -> tuple[list[JDRecord], list[dict]]:
    """Parse every JSONL line; return ``(records, parse_failures)``.

    A line that won't parse or has the wrong schema_version becomes a failure
    entry rather than aborting the run.
    """
    records: list[JDRecord] = []
    parse_failures: list[dict] = []
    for path in sorted(glob.glob(input_glob)):
        with open(path, encoding="utf-8") as fh:
            for n, line in enumerate(fh, 1):
                if not line.strip():
                    continue
                try:
                    records.append(JDRecord.from_jsonl(line))
                except (SchemaVersionError, ValueError, json.JSONDecodeError) as exc:
                    parse_failures.append({"source": f"{path}:{n}", "validation_errors": [str(exc)]})
    return records, parse_failures


def _write_jsonl(path: str, items) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for item in items:
            fh.write((item.to_jsonl() if isinstance(item, JDRecord) else json.dumps(item, ensure_ascii=False)) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate labelled JSONL against schema v1.2.")
    parser.add_argument("--input", required=True, help="Glob for labelled JSONL")
    parser.add_argument("--out-dir", default=OUT_DIR, help=f"Output directory (default: {OUT_DIR})")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    records, parse_failures = load_lines(args.input)
    passed, failed = validate_records(records)
    failed = parse_failures + failed

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    validated_path = os.path.join(args.out_dir, f"validated_{ts}.jsonl")
    failures_path = os.path.join(args.out_dir, f"failures_{ts}.jsonl")
    _write_jsonl(validated_path, passed)
    _write_jsonl(failures_path, failed)

    total = len(passed) + len(failed)
    print(f"Validated {len(passed)}/{total} (failed: {len(failed)}).")
    print(f"Passed   → {validated_path}")
    print(f"Failures → {failures_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
