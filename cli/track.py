"""track.py — the Job Tracker CLI (Phase 3, job_radar_SPEC §7.4).

Moves scored opportunities through an application lifecycle and records
outcomes, *without* the scorer ever owning mutable human state.

    # write events (append-only)
    python track.py --job-id sha256:abc --status applied
    python track.py --job-id sha256:abc --status interviewing --notes "First round booked"
    python track.py --job-id sha256:abc --outcome rejected_post_screen
    python track.py --job-id sha256:abc --title "Solutions Engineer"  # display override
    python track.py --job-id sha256:abc --notes "recruiter emailed"   # pure note

    # read (joined review table)
    python track.py list
    python track.py list --status shortlisted
    python track.py list --min-fit 7 --location-workable yes

State model C (job_radar_SPEC.md §7.4 + §11.2 register item B, locked): workflow state lives in an
append-only event log ``corpus/activity_log.jsonl`` — the single source of truth
for status / notes / outcome / application_date. ``track.py`` only ever *appends*;
it never edits a scored file and never touches the scorer. A job's live state is
its latest score (regenerable) joined with a projection folded from the log by
``job_id``. Re-scoring is therefore always safe.

CLI writes; UI reads (CLAUDE.md). The scorer is pure and LOCKED — this tool reads
scores, it never changes scoring. outcome/application_date are *derived* from the
log at read time (Log-only fork); ApplicationRecord and SCHEMA_VERSION are
untouched.
"""

from __future__ import annotations

import argparse
import glob
import json
import logging
import os
import sys
from datetime import datetime, timezone

from models.record import (
    ACTIVITY_LOG_VERSION,
    APPLICATION_STATUS,
    OUTCOME,
    ApplicationRecord,
    JDRecord,
    SchemaVersionError,
    validate_activity_event,
)

log = logging.getLogger("track")

LOG_PATH = "corpus/activity_log.jsonl"
SCORED_GLOB = "corpus/scored/scored_*.jsonl"
VALIDATED_GLOB = "corpus/validated/validated_*.jsonl"
META_GLOB = "corpus/raw/meta_*.jsonl"

# Status values the tracker can move a job to. "new" is the scorer's implicit
# baseline (never logged), so it is not an option for a status event.
LOGGABLE_STATUS = sorted(APPLICATION_STATUS - {"new"})

# Lifecycle ladder for the (forgiving) transition warning. "rejected"/"archived"
# are reachable from anywhere, so they sit outside the ladder.
_LADDER = ["new", "review", "shortlisted", "applied", "interviewing", "offer"]
_TERMINAL = frozenset({"rejected", "archived"})

# Coarse UK/remote signal for deriving location_workable from the sidecar
# (profile base = London, acceptable_remote_policy = [remote], relocation = false).
_UK_TOKENS = ("london", "united kingdom", "england", "scotland", "wales", "britain")


# ---------------------------------------------------------------------------
# Pure: event construction
# ---------------------------------------------------------------------------

def build_event(job_id: str, *, event: str, value, notes: str, ts: str) -> dict:
    """Build one activity-log event dict. Raises ValueError if it is invalid."""
    record = {
        "v": ACTIVITY_LOG_VERSION,
        "ts": ts,
        "job_id": job_id,
        "event": event,
        "value": value,
        "notes": notes or "",
    }
    errors = validate_activity_event(record)
    if errors:
        raise ValueError(f"invalid activity event: {errors}")
    return record


def transition_warning(current: str, new: str) -> str | None:
    """Return a warning string for an unusual status move, else None.

    Forgiving by design (CLAUDE.md / tier2_review precedent): real job searches
    skip and backtrack stages, so this *warns* — it never blocks.
    """
    if new in _TERMINAL or new == current:
        return None
    if current in _LADDER and new in _LADDER:
        ci, ni = _LADDER.index(current), _LADDER.index(new)
        if ni == ci + 1:
            return None
        if ni < ci:
            return f"status going backward: {current} -> {new}"
        return f"status skips stage(s): {current} -> {new}"
    return None


# ---------------------------------------------------------------------------
# Pure: projection (live workflow state per job_id)
# ---------------------------------------------------------------------------

def _default_state() -> dict:
    return {
        "status": "new",
        "outcome": None,
        "application_date": None,
        "notes": "",
        "title_override": None,
    }


def project(events: list[dict]) -> dict[str, dict]:
    """Fold the activity log into live workflow state, keyed by job_id.

    Events are folded in ascending ``ts`` order (stable on ties):
      status            -> latest status event's value (default "new")
      outcome           -> latest outcome event's value (default None)
      application_date  -> date of the *earliest* status=applied event
      title_override    -> latest title event's value (default None)
      notes             -> notes of the most recent event carrying non-empty notes
    """
    ordered = sorted(events, key=lambda e: e.get("ts", ""))
    states: dict[str, dict] = {}
    for event in ordered:
        job_id = event.get("job_id")
        if not job_id:
            continue
        state = states.setdefault(job_id, _default_state())
        kind = event.get("event")
        if kind == "status":
            state["status"] = event.get("value")
            if event.get("value") == "applied" and state["application_date"] is None:
                state["application_date"] = (event.get("ts") or "")[:10]
        elif kind == "outcome":
            state["outcome"] = event.get("value")
        elif kind == "title":
            state["title_override"] = event.get("value")
        note = event.get("notes")
        if note:
            state["notes"] = note
    return states


# ---------------------------------------------------------------------------
# Pure: join + derive + present
# ---------------------------------------------------------------------------

def derive_location_workable(meta: dict | None) -> str:
    """Coarse, read-only location_workable from the sidecar (no scoring change).

    ApplicationRecord carries no location field and the JDRecord one is a legacy
    stub, so the tracker's --location-workable filter reads the sidecar signal
    against the profile (London base, remote acceptable, no relocation).
    """
    if not meta:
        return "unknown"
    hay = " ".join(
        str(meta.get(k) or "") for k in ("location_str", "country", "workplace_type")
    ).lower()
    if meta.get("is_remote") is True or "remote" in hay:
        return "yes"
    if any(token in hay for token in _UK_TOKENS):
        return "yes"
    if hay.strip():
        return "no"  # a named, non-UK, non-remote location; relocation = false
    return "unknown"


def _title_for(jd: JDRecord | None, meta: dict | None, override: str | None = None) -> str:
    """Resolve a display title. Priority: human override > sidecar title >
    raw_text first line > job_id."""
    if override:
        return override
    if meta and meta.get("title"):
        return meta["title"]
    if jd and jd.raw_text:
        return jd.raw_text.strip().splitlines()[0][:80] if jd.raw_text.strip() else jd.id
    return jd.id if jd else "(unknown job)"


def build_rows(
    scores: dict[str, ApplicationRecord],
    jds: dict[str, JDRecord],
    metas: dict[str, dict],
    workflow: dict[str, dict],
) -> list[dict]:
    """Compose one display row per scored job_id, joining score + JD + sidecar
    + projected workflow state."""
    rows: list[dict] = []
    for job_id, score in scores.items():
        jd = jds.get(job_id)
        meta = metas.get(jd.source_url) if jd else None
        state = workflow.get(job_id, _default_state())
        rows.append(
            {
                "job_id": job_id,
                "title": _title_for(jd, meta, state.get("title_override")),
                "company": jd.company if jd else "?",
                "fit_score": score.fit_score,
                "fit_label": score.fit_label,
                "priority_score": score.priority_score,
                "blocking_constraints": score.blocking_constraints,
                "status": state["status"],
                "outcome": state["outcome"],
                "application_date": state["application_date"],
                "notes": state["notes"],
                "location_workable": derive_location_workable(meta),
            }
        )
    return rows


def filter_rows(
    rows: list[dict],
    *,
    status: str | None = None,
    min_fit: int = 1,
    location_workable: str | None = None,
) -> list[dict]:
    out = rows
    if status:
        out = [r for r in out if r["status"] == status]
    if min_fit > 1:
        out = [r for r in out if r["fit_score"] >= min_fit]
    if location_workable:
        out = [r for r in out if r["location_workable"] == location_workable]
    return out


def sort_rows(rows: list[dict]) -> list[dict]:
    """Default sort: priority_score desc, then fit_score desc, then title."""
    return sorted(rows, key=lambda r: (-r["priority_score"], -r["fit_score"], r["title"].lower()))


def _truncate(value: str, width: int) -> str:
    value = value or ""
    return value if len(value) <= width else value[: width - 1] + "…"


def format_table(rows: list[dict]) -> str:
    """Render rows as a fixed-width review table (priority-sorted upstream)."""
    if not rows:
        return "(no matching jobs)"
    header = f"{'STATUS':<12} {'PRI':>3} {'FIT':>3} {'LABEL':<18} {'LOC':<4} {'COMPANY':<14} {'TITLE':<40} OUTCOME"
    lines = [header, "-" * len(header)]
    for r in rows:
        lines.append(
            f"{r['status']:<12} {r['priority_score']:>3} {r['fit_score']:>3} "
            f"{_truncate(r['fit_label'], 18):<18} {r['location_workable']:<4} "
            f"{_truncate(r['company'], 14):<14} {_truncate(r['title'], 40):<40} "
            f"{r['outcome'] or ''}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# IO (kept out of the pure functions above so tests stay deterministic)
# ---------------------------------------------------------------------------

def load_events(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    events: list[dict] = []
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError as exc:
                log.warning("skipping %s:%d — %s", path, n, exc)
    return events


def append_event(path: str, event: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")


def load_scores(input_glob: str) -> dict[str, ApplicationRecord]:
    """Latest ApplicationRecord per job_id across every scored file.

    A job_id can recur across re-score files; the most recent ``scored_at`` wins
    (ISO strings compare lexically), so the tracker always joins to current scores.
    """
    latest: dict[str, ApplicationRecord] = {}
    for path in sorted(glob.glob(input_glob)):
        with open(path, encoding="utf-8") as fh:
            for n, line in enumerate(fh, 1):
                if not line.strip():
                    continue
                try:
                    rec = ApplicationRecord.from_jsonl(line)
                except (SchemaVersionError, ValueError, json.JSONDecodeError) as exc:
                    log.warning("skipping %s:%d — %s", path, n, exc)
                    continue
                prev = latest.get(rec.job_id)
                if prev is None or rec.scored_at >= prev.scored_at:
                    latest[rec.job_id] = rec
    return latest


def load_jdrecords(input_glob: str) -> dict[str, JDRecord]:
    jds: dict[str, JDRecord] = {}
    for path in sorted(glob.glob(input_glob)):
        with open(path, encoding="utf-8") as fh:
            for n, line in enumerate(fh, 1):
                if not line.strip():
                    continue
                try:
                    jd = JDRecord.from_jsonl(line)
                except (SchemaVersionError, ValueError, json.JSONDecodeError) as exc:
                    log.warning("skipping %s:%d — %s", path, n, exc)
                    continue
                jds[jd.id] = jd
    return jds


def load_meta(input_glob: str) -> dict[str, dict]:
    metas: dict[str, dict] = {}
    for path in sorted(glob.glob(input_glob)):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                meta = json.loads(line)
                url = meta.get("source_url")
                if url:
                    metas[url] = meta
    return metas


def _clock() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_update(argv: list[str], *, now=_clock, out=print) -> int:
    parser = argparse.ArgumentParser(prog="track.py", description="Record an activity-log event for a job.")
    parser.add_argument("--job-id", required=True, help="JDRecord content hash (sha256:...)")
    parser.add_argument("--status", choices=LOGGABLE_STATUS, help="Move the job to this lifecycle status")
    parser.add_argument("--outcome", choices=sorted(OUTCOME), help="Record a terminal outcome")
    parser.add_argument("--title", help="Set a manual display-title override for this job")
    parser.add_argument("--notes", default="", help="Free-text note attached to the event")
    parser.add_argument("--force", action="store_true", help="Log even if job_id is not in the scored corpus")
    parser.add_argument("--log", default=LOG_PATH, help=f"Activity log path (default: {LOG_PATH})")
    parser.add_argument("--scored", default=SCORED_GLOB, help="Glob for scored files (job_id existence check)")
    args = parser.parse_args(argv)

    # One CLI call may record several events (e.g. --status + --title). They share
    # the same ts; the free-text --notes attaches to the first, to avoid dupes.
    actions = [(kind, val) for kind, val in
               (("status", args.status), ("outcome", args.outcome), ("title", args.title)) if val]
    if not actions and not args.notes:
        parser.error("nothing to record: pass at least one of --status / --outcome / --title / --notes")

    scores = load_scores(args.scored)
    if args.job_id not in scores and not args.force:
        out(f"ERROR: job_id {args.job_id} not found in scored corpus ({args.scored}).")
        out("       Check the hash, or pass --force to log an event for an unscored job.")
        return 1

    if args.status:
        current = project(load_events(args.log)).get(args.job_id, _default_state())["status"]
        warning = transition_warning(current, args.status)
        if warning:
            out(f"  ⚠ {warning}")

    ts = now()
    written = 0
    if actions:
        for i, (kind, value) in enumerate(actions):
            notes = args.notes if i == 0 else ""
            append_event(args.log, build_event(args.job_id, event=kind, value=value, notes=notes, ts=ts))
            written += 1
    elif args.notes:
        append_event(args.log, build_event(args.job_id, event="note", value=None, notes=args.notes, ts=ts))
        written += 1

    out(f"Logged {written} event(s) for {args.job_id} → {args.log}")
    return 0


def cmd_list(argv: list[str], *, out=print) -> int:
    parser = argparse.ArgumentParser(prog="track.py list", description="Show the joined tracker review table.")
    parser.add_argument("--status", choices=sorted(APPLICATION_STATUS), help="Filter to one workflow status")
    parser.add_argument("--min-fit", type=int, default=1, dest="min_fit", help="Only show fit_score >= this")
    parser.add_argument(
        "--location-workable",
        choices=("yes", "no", "conditional", "unknown"),
        dest="location_workable",
        help="Filter on the (coarse, sidecar-derived) location_workable signal",
    )
    parser.add_argument("--scored", default=SCORED_GLOB, help=f"Glob for scored files (default: {SCORED_GLOB})")
    parser.add_argument("--validated", default=VALIDATED_GLOB, help=f"Glob for validated JDs (default: {VALIDATED_GLOB})")
    parser.add_argument("--meta", default=META_GLOB, help=f"Glob for metadata sidecars (default: {META_GLOB})")
    parser.add_argument("--log", default=LOG_PATH, help=f"Activity log path (default: {LOG_PATH})")
    args = parser.parse_args(argv)

    scores = load_scores(args.scored)
    jds = load_jdrecords(args.validated)
    metas = load_meta(args.meta)
    workflow = project(load_events(args.log))

    rows = build_rows(scores, jds, metas, workflow)
    shown = sort_rows(
        filter_rows(rows, status=args.status, min_fit=args.min_fit, location_workable=args.location_workable)
    )
    out(format_table(shown))
    out(f"\nShown {len(shown)} of {len(rows)} scored job(s).")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if argv and argv[0] == "list":
        return cmd_list(argv[1:])
    return cmd_update(argv)


if __name__ == "__main__":
    raise SystemExit(main())
