"""score.py — CLI for the Phase 2 scoring engine (job_radar_SPEC §6.8).

    python score.py
    python score.py --input "corpus/validated/validated_*.jsonl" --min-fit 6
    python score.py --mode active

Reads validated JDRecords, scores each against candidate_profile.yaml, and writes
one ApplicationRecord per JDRecord to corpus/scored/scored_{ts}.jsonl
(application_status="new"). The validated JDRecord files are never mutated.

The scored file is the complete, durable artifact — every record is written.
``--min-fit`` and ``--mode`` are *presentation* filters (job_radar_SPEC §6.3):
they change the printed "shown vs filtered" summary, not what is scored or stored.

Default --input is corpus/validated/validated_*.jsonl (the spec §6.8 path
corpus/labelled/validated_* is stale — Step 8 writes to corpus/validated/).
"""

from __future__ import annotations

import argparse
import glob
import json
import logging
import os
from collections import Counter
from datetime import datetime, timezone

from models.record import JDRecord, SchemaVersionError, validate_application_record
from scoring.profile import load_profile
from scoring.scorer import score

OUT_DIR = "corpus/scored"
DEFAULT_INPUT = "corpus/validated/validated_*.jsonl"

log = logging.getLogger("score")

# §6.3 filter table. A label is visible at a mode unless listed here as hidden;
# "separate" labels are visible but flagged for a separate UI section.
_HIDDEN = {
    "selective": {"interview_practice", "income_bridge"},
    "active": {"income_bridge"},
    "broad": set(),
}
_SEPARATE = {
    "selective": set(),
    "active": {"interview_practice"},
    "broad": {"income_bridge"},
}


def is_shown(fit_label: str, fit_score: int, mode: str, min_fit: int) -> bool:
    """True if a record is presented under the active mode and --min-fit."""
    return fit_label not in _HIDDEN[mode] and fit_score >= min_fit


def load_records(input_glob: str) -> list[JDRecord]:
    """Parse validated JDRecords, skipping unparseable / wrong-version lines."""
    records: list[JDRecord] = []
    for path in sorted(glob.glob(input_glob, recursive=True)):
        with open(path, encoding="utf-8") as fh:
            for n, line in enumerate(fh, 1):
                if not line.strip():
                    continue
                try:
                    records.append(JDRecord.from_jsonl(line))
                except (SchemaVersionError, ValueError, json.JSONDecodeError) as exc:
                    log.warning("skipping %s:%d — %s", path, n, exc)
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score validated JDs against the candidate profile.")
    parser.add_argument("--input", default=DEFAULT_INPUT, help=f"Glob for validated JSONL (default: {DEFAULT_INPUT})")
    parser.add_argument("--profile", default="candidate_profile.yaml", help="Path to candidate_profile.yaml")
    parser.add_argument("--min-fit", type=int, default=1, dest="min_fit", help="Presentation filter: only show fit_score >= this")
    parser.add_argument("--mode", choices=("selective", "active", "broad"), help="Override the profile search_mode for this run")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    profile = load_profile(args.profile)
    mode = args.mode or profile.search_mode

    records = load_records(args.input)
    if not records:
        log.warning("no records loaded from %r — nothing to score", args.input)

    scored_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    results = [score(jd, profile, scored_at, mode=mode) for jd in records]

    # Belt-and-braces: never write an invalid ApplicationRecord.
    for rec in results:
        errors = validate_application_record(rec)
        if errors:
            log.warning("invalid ApplicationRecord for %s: %s", rec.job_id, errors)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, f"scored_{ts}.jsonl")
    with open(out_path, "w", encoding="utf-8") as fh:
        for rec in results:
            fh.write(rec.to_jsonl() + "\n")

    distribution = dict(sorted(Counter(r.fit_label for r in results).items()))
    shown = [r for r in results if is_shown(r.fit_label, r.fit_score, mode, args.min_fit)]
    separate = [r for r in shown if r.fit_label in _SEPARATE[mode]]

    print(f"Scored {len(results)} record(s) against profile v{profile.profile_version} (mode: {mode}).")
    print(f"fit_label distribution: {distribution}")
    print(f"Shown: {len(shown)}  |  Filtered: {len(results) - len(shown)}  (min-fit {args.min_fit})")
    if separate:
        sep = dict(sorted(Counter(r.fit_label for r in separate).items()))
        print(f"  of shown, in a separate section: {sep}")
    print(f"Scored → {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
