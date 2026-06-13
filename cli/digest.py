"""digest.py — the morning review tool (Phase 4, job_radar_SPEC §8.2).

Surfaces roles scored since the last digest run, joined with workflow state, so
the daily question — *what is new and worth my attention this morning?* — has a
one-command answer.

    python -m cli.digest                     # since last run, fit >= 6
    python -m cli.digest --min-fit 7         # higher bar
    python -m cli.digest --since 2026-06-09  # explicit ISO date/datetime
    python -m cli.digest --since yesterday   # convenience keyword
    python -m cli.digest --export            # also write corpus/digest_{date}.md
    python -m cli.digest --all               # include already-tracked roles

Design (mirrors track.py): the pure functions (resolve_since / build_digest_rows
/ filter_digest / format_*) take plain data so tests stay deterministic; IO
(scored / validated / meta / log globs, the cursor file, the clock) is injected
through argv + ``now=``.

CLI writes, UI reads (CLAUDE.md). The digest only ever *reads* the scored corpus
and the activity log, and writes its own cursor (``corpus/.digest_last_run``) +
the optional export — it never touches a scored file or the scorer.

**Since-cursor** (same reasoning as collect.py): the cursor holds the *start*
timestamp of the last default digest run, so a record scored mid-run is re-shown
next time rather than skipped. No cursor → fall back to the last 24h. An explicit
``--since`` is a one-off lookback and does **not** advance the cursor.

Note: a record is "new" to the digest when its ``scored_at`` is at/after ``since``.
Because the weekly cron only labels+scores the *incremental* collection, the
scored set entering the digest is bounded to genuinely-new postings; a manual
full re-score (which restamps every record) will legitimately resurface the whole
corpus — use ``--min-fit`` / the already-tracked filter to keep that readable.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

from cli.track import (
    LOG_PATH,
    META_GLOB,
    SCORED_GLOB,
    VALIDATED_GLOB,
    _default_state,
    _title_for,
    _truncate,
    load_activity_events,
    load_jdrecords,
    load_meta,
    load_scores,
    project,
    sort_rows,
)

log = logging.getLogger("digest")

CURSOR_PATH = "corpus/.digest_last_run"
EXPORT_DIR = "corpus"
DEFAULT_MIN_FIT = 6


# ---------------------------------------------------------------------------
# Pure: clock helpers + since resolution
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_since(value: str, now_dt: datetime) -> str:
    """Resolve an explicit ``--since`` to an ISO timestamp for lexical comparison.

    Accepts the convenience keywords ``yesterday`` / ``today`` or any ISO date /
    datetime (a bare date like ``2026-06-09`` sorts before any ``...T..`` on the
    same day, so it includes that whole day). Raises ValueError on garbage.
    """
    v = value.strip()
    low = v.lower()
    if low == "yesterday":
        return _iso(now_dt - timedelta(hours=24))
    if low == "today":
        return now_dt.strftime("%Y-%m-%dT00:00:00Z")
    try:
        datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            f"invalid --since {value!r}: use an ISO date/datetime, 'yesterday', or 'today'"
        ) from exc
    return v


def resolve_since(arg_since: str | None, cursor_value: str | None, now_dt: datetime) -> str:
    """Window start: explicit ``--since`` > saved cursor > 24h ago."""
    if arg_since:
        return parse_since(arg_since, now_dt)
    if cursor_value:
        return cursor_value
    return _iso(now_dt - timedelta(hours=24))


# ---------------------------------------------------------------------------
# Pure: row composition + filtering
# ---------------------------------------------------------------------------

def build_digest_rows(scores, jds, metas, workflow, *, since: str) -> list[dict]:
    """One row per job scored at/after ``since``, joining score + JD + sidecar
    + projected workflow state."""
    rows: list[dict] = []
    for job_id, score in scores.items():
        if score.scored_at < since:
            continue
        jd = jds.get(job_id)
        meta = metas.get(jd.source_url) if jd else None
        state = workflow.get(job_id, _default_state())
        location = ""
        if meta and meta.get("location_str"):
            location = meta["location_str"]
        elif jd and jd.location:
            location = jd.location
        rows.append(
            {
                "job_id": job_id,
                "title": _title_for(jd, meta, state.get("title_override")),
                "company": jd.company if jd else "?",
                "fit_score": score.fit_score,
                "fit_label": score.fit_label,
                "priority_score": score.priority_score,
                "location": location,
                "source_url": jd.source_url if jd else "",
                "status": state["status"],
            }
        )
    return rows


def filter_digest(rows: list[dict], *, min_fit: int = DEFAULT_MIN_FIT, include_tracked: bool = False) -> list[dict]:
    """Keep fit_score >= ``min_fit``; drop roles already in the pipeline
    (status != "new") unless ``include_tracked``."""
    out = [r for r in rows if r["fit_score"] >= min_fit]
    if not include_tracked:
        out = [r for r in out if r["status"] == "new"]
    return out


# ---------------------------------------------------------------------------
# Pure: presentation
# ---------------------------------------------------------------------------

def summary_line(rows: list[dict], since: str) -> str:
    return f"{len(rows)} new role(s) since {since}"


def format_table(rows: list[dict]) -> str:
    """Render rows as a fixed-width review table (priority-sorted upstream)."""
    if not rows:
        return "(no new roles)"
    header = (
        f"{'PRI':>3} {'FIT':>3} {'LABEL':<18} {'COMPANY':<16} "
        f"{'TITLE':<36} {'LOCATION':<22} SOURCE"
    )
    lines = [header, "-" * len(header)]
    for r in rows:
        lines.append(
            f"{r['priority_score']:>3} {r['fit_score']:>3} "
            f"{_truncate(r['fit_label'], 18):<18} {_truncate(r['company'], 16):<16} "
            f"{_truncate(r['title'], 36):<36} {_truncate(r['location'], 22):<22} "
            f"{r['source_url']}"
        )
    return "\n".join(lines)


def _md_cell(value: str) -> str:
    return (value or "").replace("|", "\\|").replace("\n", " ")


def format_markdown(rows: list[dict], *, since: str, generated: str) -> str:
    """Render the same table as a Markdown document for ``--export``."""
    lines = [
        f"# Job Radar digest — {generated}",
        "",
        f"**{summary_line(rows, since)}**",
        "",
    ]
    if not rows:
        lines.append("_No new roles._")
        return "\n".join(lines) + "\n"
    lines.append("| Pri | Fit | Label | Company | Role | Location | Source |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in rows:
        url = r["source_url"]
        source = f"[link]({url})" if url else ""
        lines.append(
            f"| {r['priority_score']} | {r['fit_score']} | {_md_cell(r['fit_label'])} | "
            f"{_md_cell(r['company'])} | {_md_cell(r['title'])} | {_md_cell(r['location'])} | {source} |"
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# IO (kept out of the pure functions above so tests stay deterministic)
# ---------------------------------------------------------------------------

def read_cursor(path: str) -> str | None:
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return fh.read().strip() or None


def write_cursor(path: str, ts: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(ts)


def write_export(export_dir: str, date_str: str, content: str) -> str:
    os.makedirs(export_dir, exist_ok=True)
    path = os.path.join(export_dir, f"digest_{date_str}.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return path


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------

def cmd_digest(argv: list[str], *, now=_now, out=print) -> int:
    parser = argparse.ArgumentParser(prog="digest.py", description="Surface roles scored since the last digest run.")
    parser.add_argument("--min-fit", type=int, default=DEFAULT_MIN_FIT, dest="min_fit", help=f"Only show fit_score >= this (default: {DEFAULT_MIN_FIT})")
    parser.add_argument("--since", help="Window start: ISO date/datetime, 'yesterday', or 'today' (overrides the cursor; does not advance it)")
    parser.add_argument("--all", action="store_true", dest="include_tracked", help="Include roles already tracked (status != new)")
    parser.add_argument("--export", action="store_true", help="Also write the table to corpus/digest_{date}.md")
    parser.add_argument("--scored", default=SCORED_GLOB, help=f"Glob for scored files (default: {SCORED_GLOB})")
    parser.add_argument("--validated", default=VALIDATED_GLOB, help=f"Glob for validated JDs (default: {VALIDATED_GLOB})")
    parser.add_argument("--meta", default=META_GLOB, help=f"Glob for metadata sidecars (default: {META_GLOB})")
    parser.add_argument("--log", default=LOG_PATH, help=f"Activity log path (default: {LOG_PATH})")
    parser.add_argument("--cursor", default=CURSOR_PATH, help=f"Digest cursor file (default: {CURSOR_PATH})")
    parser.add_argument("--export-dir", default=EXPORT_DIR, dest="export_dir", help=f"Directory for --export output (default: {EXPORT_DIR})")
    args = parser.parse_args(argv)

    run_start_dt = now()
    run_start = _iso(run_start_dt)
    try:
        since = resolve_since(args.since, read_cursor(args.cursor), run_start_dt)
    except ValueError as exc:
        parser.error(str(exc))

    scores = load_scores(args.scored)
    jds = load_jdrecords(args.validated)
    metas = load_meta(args.meta)
    workflow = project(load_activity_events(args.log))

    rows = build_digest_rows(scores, jds, metas, workflow, since=since)
    shown = sort_rows(filter_digest(rows, min_fit=args.min_fit, include_tracked=args.include_tracked))

    out(summary_line(shown, since))
    out(format_table(shown))

    if args.export:
        date_str = run_start_dt.strftime("%Y%m%d")
        path = write_export(args.export_dir, date_str, format_markdown(shown, since=since, generated=_iso(run_start_dt)))
        out(f"\nExported to {path}")

    # Advance the cursor only on a default (cursor-driven) run — an explicit
    # --since is a one-off lookback and must not move the forward cursor.
    if not args.since:
        write_cursor(args.cursor, run_start)

    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    return cmd_digest(argv)


if __name__ == "__main__":
    raise SystemExit(main())
