"""tier2_review.py — interactive Tier 2 deep-review CLI (job_radar_SPEC §5.3 Step 6).

    python tier2_review.py --input "corpus/raw/clean_*.jsonl"

For each unlabelled record (extraction not yet populated) the loop:
  1. shows raw_text truncated to 500 chars
  2. runs extraction (PLACEHOLDER — see ``extract_placeholder``)
  3. shows the extraction field by field
  4. prompts ``[a]ccept / [e]dit / [s]kip``
  5. accept → write to ``corpus/manual/tier2_{date}.jsonl`` with ``tier=2``
  6. edit  → field-by-field correction, then write as above
  7. skip  → append to the skipped file

The loop is interruptible and resumable: the reviewed-id set is checkpointed to
``corpus/tier2_progress.json`` after every record, so a re-run skips records
already handled. Input expects deduped records (real content-hash ids) so the
checkpoint key is stable.

NOTE: extraction here is a placeholder that returns no values — the human fills
them via edit mode. Step 7 (pipeline/label.py, Claude Batch API) replaces it.
Per the project's "Batch API only for labelling" rule, this tool never calls
the Claude API synchronously.
"""

from __future__ import annotations

import argparse
import glob
import json
import logging
import os
from datetime import date

from models.record import _EXTRACTION_FIELDS, JDRecord, validate

log = logging.getLogger(__name__)

CHECKPOINT_PATH = "corpus/tier2_progress.json"
OUT_DIR = "corpus/manual"

# Extraction fields that hold a list of strings (edited as comma-separated input).
LIST_FIELDS = frozenset(
    {
        "role_type",
        "required_technologies",
        "required_competencies",
        "nice_to_have_technologies",
        "nice_to_have_competencies",
        "domain",
        "delivery_motion",
        "leadership_geography",
        "culture_signals",
    }
)


# --- extraction placeholder (Step 7 replaces) ---

def extract_placeholder(record: JDRecord) -> dict:
    """Return an empty extraction (every field unset).

    TODO(Step 7): replace with real Claude Batch extraction from
    pipeline/label.py. Kept as a placeholder so the review loop is buildable and
    testable before labelling exists.
    """
    return {field: None for field in _EXTRACTION_FIELDS}


# --- checkpoint ---

def load_checkpoint(path: str) -> dict:
    if not os.path.exists(path):
        return {"reviewed": []}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save_checkpoint(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


# --- io helpers ---

def load_records(input_glob: str) -> list[JDRecord]:
    """Read all JSONL records matching ``input_glob`` (sorted, deduped)."""
    records: list[JDRecord] = []
    for path in sorted(glob.glob(input_glob)):
        with open(path, encoding="utf-8") as fh:
            records.extend(JDRecord.from_jsonl(line) for line in fh if line.strip())
    return records


def is_unlabelled(record: JDRecord) -> bool:
    """A record is unlabelled until extraction has populated ``role_type``."""
    return record.role_type is None


def _append_jsonl(path: str, record: JDRecord) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(record.to_jsonl() + "\n")


def _fmt(value) -> str:
    return "—" if value is None else str(value)


# --- review loop ---

def apply_extraction(record: JDRecord, extraction: dict) -> None:
    """Write extraction values onto the record and mark it Tier 2."""
    for field in _EXTRACTION_FIELDS:
        setattr(record, field, extraction.get(field))
    record.tier = 2


def _parse_field_value(field: str, current, raw: str):
    raw = raw.strip()
    if raw == "":
        return current  # blank keeps the current value
    if field in LIST_FIELDS:
        return [s.strip() for s in raw.split(",") if s.strip()]
    return raw


def _display(record: JDRecord, extraction: dict, output_fn) -> None:
    output_fn("=" * 64)
    output_fn(f"{record.company}  |  tier {record.tier}  |  {record.source_url}")
    output_fn("--- raw_text (first 500 chars) ---")
    output_fn((record.raw_text or "")[:500])
    output_fn("--- extraction ---")
    for field in _EXTRACTION_FIELDS:
        output_fn(f"  {field}: {_fmt(extraction.get(field))}")


def _prompt_choice(input_fn, output_fn) -> str:
    while True:
        ans = input_fn("[a]ccept / [e]dit / [s]kip: ").strip().lower()
        if ans in ("a", "e", "s"):
            return ans
        output_fn("Please enter a, e, or s.")


def _edit(extraction: dict, input_fn, output_fn) -> dict:
    output_fn("--- edit (blank keeps current; lists are comma-separated) ---")
    updated = dict(extraction)
    for field in _EXTRACTION_FIELDS:
        current = updated.get(field)
        raw = input_fn(f"  {field} [{_fmt(current)}]: ")
        updated[field] = _parse_field_value(field, current, raw)
    return updated


def run(
    records: list[JDRecord],
    *,
    accepted_path: str,
    skipped_path: str,
    checkpoint_path: str = CHECKPOINT_PATH,
    extract=extract_placeholder,
    input_fn=input,
    output_fn=print,
) -> dict:
    """Drive the interactive review over ``records``. Returns a counts dict.

    Resumable: records whose id is already in the checkpoint are skipped, and
    the checkpoint is rewritten after every record so an interrupted run resumes
    cleanly.
    """
    reviewed = set(load_checkpoint(checkpoint_path).get("reviewed", []))
    counts = {"accepted": 0, "edited": 0, "skipped": 0, "already_reviewed": 0}

    for record in records:
        if record.id in reviewed:
            counts["already_reviewed"] += 1
            continue

        extraction = extract(record)
        _display(record, extraction, output_fn)
        choice = _prompt_choice(input_fn, output_fn)

        if choice == "s":
            _append_jsonl(skipped_path, record)
            counts["skipped"] += 1
        else:
            if choice == "e":
                extraction = _edit(extraction, input_fn, output_fn)
                counts["edited"] += 1
            else:
                counts["accepted"] += 1
            apply_extraction(record, extraction)
            errors = validate(record)
            if errors:
                output_fn(f"  ⚠ {len(errors)} validation issue(s) (placeholder extraction): {errors}")
            _append_jsonl(accepted_path, record)

        reviewed.add(record.id)
        save_checkpoint(checkpoint_path, {"reviewed": sorted(reviewed)})

    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Interactive Tier 2 deep review.")
    parser.add_argument("--input", required=True, help="Glob for cleaned JSONL (e.g. 'corpus/raw/clean_*.jsonl')")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    date_str = date.today().strftime("%Y%m%d")
    accepted_path = os.path.join(OUT_DIR, f"tier2_{date_str}.jsonl")
    skipped_path = os.path.join(OUT_DIR, f"tier2_skipped_{date_str}.jsonl")

    records = [r for r in load_records(args.input) if is_unlabelled(r)]
    if not records:
        print("No unlabelled records to review.")
        return 0

    print(f"{len(records)} unlabelled record(s) to review. Ctrl-C is safe — progress is checkpointed.\n")
    counts = run(records, accepted_path=accepted_path, skipped_path=skipped_path)
    print(
        f"\nDone. accepted={counts['accepted']} edited={counts['edited']} "
        f"skipped={counts['skipped']} already_reviewed={counts['already_reviewed']}"
    )
    print(f"Accepted → {accepted_path}\nSkipped  → {skipped_path}\nProgress → {CHECKPOINT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
