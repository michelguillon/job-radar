"""prefilter.py — CLI for the pre-label filter (Phase 3).

Cuts a day's raw collection down to the genuinely-relevant postings *before* any
paid Batch labelling, using the structured metadata sidecar (title + location).

    python prefilter.py                      # today's files
    python prefilter.py --date 20260609
    python prefilter.py --dry-run            # report only, write nothing

Pipeline: load raw + meta → clean+dedupe → screen (pipeline.prefilter) → divert
the GTM/partner observation watchlist → write survivors → report. The screen logic
is pure and lives in pipeline/prefilter.py; this module does the IO and prints the
survivor distribution so thresholds can be iterated against real numbers before
spending on labelling.

The **watchlist** (job_radar_SPEC §5.10) diverts location-workable GTM/partner-class
roles out of the labelling/scoring stream into an observation log — they currently
score poorly (GTM is not a profile target_role), and we gather real evidence before
any profile/scorer change. Observation only: never labelled, never scored.

Reads : corpus/raw/raw_{date}.jsonl   + corpus/raw/meta_{date}.jsonl
Writes: corpus/filtered/filtered_{date}.jsonl     (survivors for labelling)
        corpus/watchlist/watchlist_{date}.jsonl   (GTM/partner observations)
"""

from __future__ import annotations

import argparse
import glob
import json
import logging
import os
from collections import Counter
from datetime import date

from models.record import JDRecord
from pipeline.dedupe import dedupe
from pipeline.prefilter import (
    collapse_near_duplicates,
    screen,
    watchlist_signal,
)

log = logging.getLogger(__name__)

RAW_DIR = "corpus/raw"
FILTERED_DIR = "corpus/filtered"
WATCHLIST_DIR = "corpus/watchlist"

# Already-processed corpus: a job whose content hash is in either of these has
# already cost a Batch-labelling call (and likely a score), so it must not re-enter
# the paid pipeline on a full re-collect. job_id (scored) and id (labelled) are the
# same sha256 content hash that pipeline.dedupe computes.
LABELLED_GLOB = "corpus/labelled/labelled_*.jsonl"
SCORED_GLOB = "corpus/scored/scored_*.jsonl"


def load_records(path: str) -> list[JDRecord]:
    """Load JDRecords from a raw JSONL file."""
    with open(path, encoding="utf-8") as fh:
        return [JDRecord.from_jsonl(line) for line in fh if line.strip()]


def load_processed_hashes(
    labelled_glob: str = LABELLED_GLOB, scored_glob: str = SCORED_GLOB
) -> set[str]:
    """Content hashes of every job already labelled or scored (cross-run dedupe key).

    Reads the ``id`` of each labelled JDRecord and the ``job_id`` of each scored
    ApplicationRecord — both the ``sha256:…`` content hash ``pipeline.dedupe`` assigns.
    Missing files/dirs are fine (fresh deploy) → empty set → no exclusion.
    """
    seen: set[str] = set()
    for path in sorted(glob.glob(labelled_glob)):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    h = json.loads(line).get("id")
                    if h:
                        seen.add(h)
    for path in sorted(glob.glob(scored_glob)):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    h = json.loads(line).get("job_id")
                    if h:
                        seen.add(h)
    return seen


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
    seen: set[str] | None = None,
) -> tuple[list[JDRecord], dict]:
    """Clean+dedupe then screen ``records`` against their metadata.

    ``seen`` is the set of content-hash job_ids already labelled/scored
    (``load_processed_hashes``); any record whose hash is in it is dropped as
    *already-processed*, so a full re-collect never re-pays to label a job you've
    already seen. ``None``/empty → batch-only dedupe (the pure, corpus-independent
    behaviour the unit tests rely on).

    Returns ``(survivors, report)``. ``report`` holds counts and distributions
    for the stdout summary. Pure given its inputs (no IO).
    """
    corpus_seen = set(seen) if seen else set()
    raw_count = len(records)
    # 1) exact dedupe WITHIN this batch (also assigns each record.id = content hash).
    batch_unique, dropped_dupes = dedupe(records, set())
    # 2) cross-run dedupe: drop anything already labelled/scored in the corpus. Reuses
    #    the .id dedupe() just assigned, so no second (expensive) clean/hash pass.
    kept_records = [r for r in batch_unique if r.id not in corpus_seen]
    already_processed = len(batch_unique) - len(kept_records)

    entries: list[dict] = []
    watchlist: list[dict] = []
    drop_reasons: Counter = Counter()
    role_fail: Counter = Counter()
    loc_fail: Counter = Counter()
    no_meta = 0

    for record in kept_records:
        meta = meta_index.get(record.source_url)
        if meta is None:
            no_meta += 1
            drop_reasons["no_meta"] += 1
            continue
        title = meta.get("title", "")
        result = screen(meta)
        # GTM/partner observation watchlist: divert a location-workable posting
        # whose title matches a watchlist signal out of the labelling/scoring
        # stream (observation only — never scored). Restricted to the gtm_partner
        # and off_target role buckets so genuine solutions/product/customer targets
        # (e.g. "Product Manager, Ecosystem Risk") stay in scoring and sales /
        # recruiting noise (e.g. "Talent Acquisition (…GTM…)") is dropped, not
        # observed. off_target is included so a watchlist role the role-screen
        # drops (e.g. a bare "Chief of Staff") is still surfaced for review.
        if result.loc_keep and watchlist_signal(title) and result.role_bucket in ("gtm_partner", "off_target"):
            watchlist.append({
                "company": record.company,
                "title": title,
                "location": meta.get("location_str", ""),
                "source_url": record.source_url,
            })
            continue
        if not result.role_keep:
            role_fail[result.role_bucket] += 1
        if not result.loc_keep:
            loc_fail[result.loc_bucket] += 1
        if result.keep:
            entries.append({
                "record": record,
                "company": record.company,
                "title": meta.get("title", ""),
                "role_bucket": result.role_bucket,
                "loc_bucket": result.loc_bucket,
            })
        else:
            drop_reasons[result.drop_reason] += 1

    screened_kept = len(entries)
    kept_entries, collapsed = collapse_near_duplicates(entries)
    survivors = [e["record"] for e in kept_entries]

    by_company: Counter = Counter(e["company"] for e in kept_entries)
    by_role_bucket: Counter = Counter(e["role_bucket"] for e in kept_entries)
    by_loc_bucket: Counter = Counter(e["loc_bucket"] for e in kept_entries)

    report = {
        "raw_count": raw_count,
        "dropped_dupes": dropped_dupes,
        "already_processed": already_processed,
        "corpus_known": len(corpus_seen),
        "deduped_count": len(kept_records),
        "screened_kept": screened_kept,
        "near_dupes_collapsed": collapsed,
        "kept_count": len(survivors),
        "no_meta": no_meta,
        "drop_reasons": drop_reasons,
        "role_fail": role_fail,
        "loc_fail": loc_fail,
        "by_company": by_company,
        "by_role_bucket": by_role_bucket,
        "by_loc_bucket": by_loc_bucket,
        "watchlist": watchlist,
    }
    return survivors, report


def write_survivors(records: list[JDRecord], path: str) -> str:
    """Write surviving JDRecords to ``path`` (overwrites; not append)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for record in records:
            fh.write(record.to_jsonl() + "\n")
    return path


def write_watchlist(watchlist: list[dict], path: str) -> str:
    """Write the (deduped) watchlist observations to ``path`` as JSONL.

    A durable log so observations accumulate across production runs for the later
    career-strategy review. Observation only — never labelled or scored.
    """
    rows = _dedup_watchlist(watchlist)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for w in rows:
            fh.write(json.dumps(w, ensure_ascii=False) + "\n")
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
    if report.get("corpus_known"):
        print(f"  already processed  : {report['already_processed']} "
              f"(excluded vs {report['corpus_known']} labelled/scored job_ids)")
    print(f"  unique after dedupe: {report['deduped_count']}")
    if report["no_meta"]:
        print(f"  WARNING no metadata: {report['no_meta']} (treated as dropped)")
    print(f"passed screens     : {report['screened_kept']}")
    print(f"  near-dupes collapsed: {report['near_dupes_collapsed']}")
    pct = (100 * kept / raw) if raw else 0
    print(f"kept (survivors)   : {kept}  ({pct:.0f}% of raw, distinct roles)")
    print(f"dropped            : {report['deduped_count'] - kept}")

    _print_counter("drop reason (role checked before location):", report["drop_reasons"])
    _print_counter("role-fail breakdown (independent):", report["role_fail"])
    _print_counter("location-fail breakdown (independent):", report["loc_fail"])
    _print_counter("KEPT by company:", report["by_company"])
    _print_counter("KEPT by role bucket:", report["by_role_bucket"])
    _print_counter("KEPT by location bucket:", report["by_loc_bucket"])
    print_watchlist(report.get("watchlist", []))


def _dedup_watchlist(watchlist: list[dict]) -> list[dict]:
    """Collapse multi-location variants by (company, title), preserving order."""
    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    for w in watchlist:
        key = (w["company"], w["title"])
        if key not in seen:
            seen.add(key)
            out.append(w)
    return out


def print_watchlist(watchlist: list[dict]) -> None:
    """Print the GTM/partner observation watchlist (no scoring; review-only)."""
    rows = _dedup_watchlist(watchlist)
    print("\n" + "=" * 60)
    print("WATCHLIST ROLES  (GTM/partner — observation only, not scored)")
    print("=" * 60)
    print(f"count: {len(rows)}")
    for w in rows:
        print(f"  {w['company']} | {w['title']} | {w['location'] or '-'}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pre-label filter over raw + metadata.")
    parser.add_argument("--date", default=date.today().strftime("%Y%m%d"), help="YYYYMMDD of the raw/meta files")
    parser.add_argument("--raw", help="Override raw JSONL path")
    parser.add_argument("--meta", help="Override metadata JSONL path")
    parser.add_argument("--out", help="Override survivors output path")
    parser.add_argument("--dry-run", action="store_true", help="Report only; write nothing")
    parser.add_argument(
        "--include-processed",
        action="store_true",
        help="Do NOT exclude jobs already labelled/scored (re-process the whole batch — "
             "e.g. to re-label after a JD/prompt change). Default excludes them.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    raw_path = args.raw or os.path.join(RAW_DIR, f"raw_{args.date}.jsonl")
    meta_path = args.meta or os.path.join(RAW_DIR, f"meta_{args.date}.jsonl")
    out_path = args.out or os.path.join(FILTERED_DIR, f"filtered_{args.date}.jsonl")
    watchlist_path = os.path.join(WATCHLIST_DIR, f"watchlist_{args.date}.jsonl")

    records = load_records(raw_path)
    meta_index = load_meta(meta_path)
    # Cross-run dedupe: exclude jobs already in the labelled/scored corpus unless asked
    # to re-process. A full re-collect (e.g. a cursor-less first server run) otherwise
    # re-surfaces — and re-pays to label — everything already seen.
    seen = set() if args.include_processed else load_processed_hashes()
    survivors, report = run(records, meta_index, seen=seen)

    print_report(report)

    if args.dry_run:
        print(f"\n[dry-run] would write {len(survivors)} survivors to {out_path}")
        print(f"[dry-run] would log {len(_dedup_watchlist(report['watchlist']))} watchlist roles to {watchlist_path}")
        return 0

    write_survivors(survivors, out_path)
    write_watchlist(report["watchlist"], watchlist_path)
    print(f"\nWrote {len(survivors)} survivors to {out_path}")
    print(f"Logged {len(_dedup_watchlist(report['watchlist']))} watchlist roles to {watchlist_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
