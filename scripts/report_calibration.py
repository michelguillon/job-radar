"""Score the calibration corpus and print the full per-record breakdown.

Read-only review tool (no writes) — loads validated calibration JDRecords, runs
the scorer, and prints every field the calibration review needs: company, role,
fit_score, fit_label, fit_label_reason, requirement_gaps, blocking_constraints,
and the Stage-1 per-dimension breakdown (signal sub-scores + gate outcomes).

    docker compose run --rm job-radar python -m scripts.report_calibration
"""

from __future__ import annotations

import glob
from collections import Counter

from models.record import JDRecord
from scoring.profile import load_profile
from scoring.scorer import score, stage1_fit, unmet_required_technologies

import sys

# Default: calibration only. Pass "--full" to include the 10 manual records too.
CAL_GLOB = "corpus/calibration/validated_*.jsonl"
MANUAL_GLOB = "corpus/manual/manual_*.jsonl"
SCORED_AT = "2026-06-09T00:00:00Z"


def main() -> int:
    profile = load_profile()
    globs = [CAL_GLOB]
    if "--full" in sys.argv:
        globs = [MANUAL_GLOB, CAL_GLOB]
    paths = sorted(p for g in globs for p in glob.glob(g))
    if not paths:
        print(f"no validated records at {globs}")
        return 1

    rows = []
    for path in paths:
        for line in open(path, encoding="utf-8"):
            if line.strip():
                rows.append(JDRecord.from_jsonl(line))

    labels = Counter()
    for jd in rows:
        fit, b = stage1_fit(jd, profile)
        rec = score(jd, profile, SCORED_AT)
        labels[rec.fit_label] += 1
        unmet = len(unmet_required_technologies(jd, profile))
        print("=" * 100)
        print(f"{jd.company}  —  role_type={jd.role_type}  seniority={jd.seniority}  depth={jd.technical_depth}")
        print(f"  domain={jd.domain}  remote={jd.remote_policy}  location={jd.location!r}  stage={jd.company_stage}")
        print(f"  SIGNAL  role={b.role:g}(x2)  domain={b.domain:g}(x2)  depth={b.technical_depth:g}(x1)  -> signal={b.signal:g}")
        print(f"  GATES   seniority={b.seniority_gate}(-{b.seniority_penalty:g})  location={b.location_gate}(-{b.location_penalty:g})  | unmet_req_tech={unmet}")
        print(f"  => fit_score={rec.fit_score}   priority={rec.priority_score}   FIT_LABEL={rec.fit_label}")
        print(f"  reason: {rec.fit_label_reason}")
        if rec.requirement_gaps:
            print(f"  requirement_gaps:    {rec.requirement_gaps}")
        if rec.blocking_constraints:
            print(f"  blocking_constraints: {rec.blocking_constraints}")
    print("=" * 100)
    print(f"\nfit_label spread ({len(rows)} records): {dict(sorted(labels.items()))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
