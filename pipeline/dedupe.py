"""Deduplication — SHA-256 hash on cleaned text, drop exact duplicates.

The dedup key is the SHA-256 of the *normalised* JD text, not the source URL:
the same JD appears on multiple ATS platforms (docs/SPEC_JD_REFINERY.md §3.7).
This is exact-match only; near-duplicate detection (MinHash/SimHash) is out of
scope for the initial build.
"""

from __future__ import annotations

import hashlib

from models.record import JDRecord
from pipeline.clean import clean, normalise


def record_hash(normalised_text: str) -> str:
    """Return ``sha256:{hex}`` for already-normalised text."""
    digest = hashlib.sha256(normalised_text.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _content_hash(record: JDRecord) -> str:
    """Compute the content hash for a record from its raw content.

    Uses the full HTML cleaning pipeline when ``raw_html`` is present, otherwise
    normalises the plain ``raw_text`` (e.g. manual records).
    """
    if record.raw_html:
        text = clean(record.raw_html)
    else:
        text = normalise(record.raw_text)
    return record_hash(text)


def dedupe(
    records: list[JDRecord], seen: set[str]
) -> tuple[list[JDRecord], int]:
    """Assign content-hash ids and drop exact duplicates.

    Each record's ``id`` is set to its content hash. A record is dropped if its
    hash is already in ``seen`` (corpus-wide duplicate) or appeared earlier in
    this batch. ``seen`` is updated in place with every kept hash.

    Returns ``(kept_records, dropped_count)``.
    """
    kept: list[JDRecord] = []
    dropped = 0
    for record in records:
        digest = _content_hash(record)
        record.id = digest
        if digest in seen:
            dropped += 1
            continue
        seen.add(digest)
        kept.append(record)
    return kept, dropped
