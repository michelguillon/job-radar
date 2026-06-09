"""One-shot: backfill raw_text + SHA-256 ids on the 10 manual records.

Step 2 left every manual record with ``raw_text: "stored separately"`` and
``id: "sha256:pending"`` because the real JD text lived in
``corpus/manual/JD_SOURCE_TEXTS.md`` (hashing the placeholder would have
collapsed all 10 into one). This script:

  1. Parses the raw text block for each company out of JD_SOURCE_TEXTS.md
  2. Sets ``raw_text`` on the matching record
  3. Runs ``pipeline.dedupe.dedupe`` to assign content-hash ids AND prove no
     two records collide (dropped count must be 0)
  4. Rewrites corpus/manual/manual_20260606.jsonl in place

Idempotent: re-running on already-backfilled records recomputes identical
hashes. Run once via:

    docker compose run --rm job-radar python -m scripts.backfill_manual_hashes
"""

from __future__ import annotations

import re

from models.record import JDRecord
from pipeline.dedupe import dedupe

JSONL_PATH = "corpus/manual/manual_20260606.jsonl"
SOURCE_PATH = "corpus/manual/JD_SOURCE_TEXTS.md"

# "## Record 1 — Airwallex" -> "Airwallex", followed (eventually) by a ``` block.
_RECORD_RE = re.compile(
    r"^##\s+Record\s+\d+\s+[—-]\s+(?P<company>.+?)\s*$.*?```\s*\n(?P<text>.*?)\n```",
    re.MULTILINE | re.DOTALL,
)


def parse_source_texts(markdown: str) -> dict[str, str]:
    """Return ``{company: raw_text}`` for every record block in the source file."""
    texts: dict[str, str] = {}
    for m in _RECORD_RE.finditer(markdown):
        texts[m.group("company").strip()] = m.group("text").strip()
    return texts


def main() -> int:
    with open(SOURCE_PATH, encoding="utf-8") as fh:
        texts = parse_source_texts(fh.read())

    with open(JSONL_PATH, encoding="utf-8") as fh:
        records = [JDRecord.from_jsonl(line) for line in fh if line.strip()]

    missing = [r.company for r in records if r.company not in texts]
    if missing:
        raise SystemExit(f"No source text for: {missing}")

    for record in records:
        record.raw_text = texts[record.company]

    # dedupe assigns record.id on every record and drops collisions.
    kept, dropped = dedupe(records, set())
    if dropped:
        raise SystemExit(f"Hash collision: {dropped} duplicate record(s) — aborting")

    with open(JSONL_PATH, "w", encoding="utf-8") as fh:
        for record in records:
            fh.write(record.to_jsonl() + "\n")

    print(f"Backfilled {len(records)} records, {len(set(r.id for r in records))} unique hashes.")
    for record in records:
        print(f"  {record.id[:23]}…  {record.company}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
