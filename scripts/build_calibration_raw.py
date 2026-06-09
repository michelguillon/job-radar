"""Build the 13 raw calibration JDRecords from docs/jobs_calibration_corpus.txt.

One-off corpus maintenance (scripts/, like backfill_manual_hashes.py). Parses the
hand-split calibration text into Tier-4 raw records (extraction/annotation all
None), assigns content-hash ids through the *real* dedupe pipeline (Learning 4 —
never a parallel hash), and writes corpus/calibration/raw_calibration.jsonl.

These are scorer-regression FIXTURES, not training data — they live under
corpus/calibration/ and are excluded from every fine-tune export (export.py).

Section 12 of the source bundles two JDs (News Corp + OneOcean); we split them, so
12 sections → 13 records. Run via Docker:
    docker compose run --rm job-radar python -m scripts.build_calibration_raw
"""

from __future__ import annotations

import os
import re

from collectors.base import build_raw_record
from pipeline.dedupe import dedupe

SRC = "docs/jobs_calibration_corpus.txt"
OUT_DIR = "corpus/calibration"
OUT = os.path.join(OUT_DIR, "raw_calibration.jsonl")
COLLECTED_AT = "2026-06-09"

# company per JD number (1–13). Section 12 splits into 12 (News Corp) + 13 (OneOcean).
COMPANIES = {
    1: "Fin (Intercom)",
    2: "Fin (Intercom)",
    3: "Fin (Intercom)",
    4: "Fin (Intercom)",
    5: "Appian",
    6: "Grey Matter Recruitment",
    7: "Executive Recruit (BPO/BPM)",
    8: "Marex",
    9: "BBC",
    10: "Socure",
    11: "Ryan, LLC",
    12: "News Corp UK",
    13: "OneOcean Group",
}

_SEP = re.compile(r"(?m)^=+$\n?")
_ONEOCEAN_SPLIT = "Senior Product Manager\nOneOcean Group Limited"


def parse_blocks(text: str) -> list[tuple[int, str]]:
    """Return ``[(jd_number, raw_text), …]`` for all 13 calibration JDs."""
    segments = [s.strip() for s in _SEP.split(text)]
    blocks: list[tuple[int, str]] = []
    pending_header = False
    for seg in segments:
        if seg.startswith("JOB DESCRIPTION"):
            pending_header = True
            continue
        if not pending_header or not seg:
            continue
        pending_header = False
        n = len(blocks) + 1  # 1-based; will re-number after the 12/13 split
        blocks.append((n, seg))

    # Split section 12 (News Corp body bundles the OneOcean JD beneath it).
    out: list[tuple[int, str]] = []
    for n, body in blocks:
        if n == 12 and _ONEOCEAN_SPLIT in body:
            news, ocean = body.split(_ONEOCEAN_SPLIT, 1)
            out.append((12, news.strip()))
            out.append((13, (_ONEOCEAN_SPLIT.split("\n", 1)[0] + "\n" + ocean).strip()))
        else:
            out.append((n, body))
    return out


def main() -> int:
    with open(SRC, encoding="utf-8") as fh:
        text = fh.read()

    blocks = parse_blocks(text)
    assert len(blocks) == 13, f"expected 13 calibration JDs, parsed {len(blocks)}"

    records = [
        build_raw_record(
            source_url="unknown",
            source_ats="manual",
            company=COMPANIES[n],
            collected_at=COLLECTED_AT,
            raw_text=body,
        )
        for n, body in blocks
    ]

    # Assign ids through the live pipeline; dropped==0 doubles as a no-collision check.
    kept, dropped = dedupe(records, set())
    assert dropped == 0, f"{dropped} calibration records collided on content hash"

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        for rec in kept:
            fh.write(rec.to_jsonl() + "\n")

    print(f"Wrote {len(kept)} raw calibration records → {OUT}")
    for n, (rec, (num, _)) in enumerate(zip(kept, blocks), 1):
        print(f"  JD{num:<2} {rec.company:<26} {rec.id[:18]}…  ({len(rec.raw_text)} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
