"""score_report.py — production scoring-run report (Phase 3).

Joins scored ApplicationRecords with their validated JDRecords (for the scorer
signal breakdown) and the metadata sidecar (for titles), and prints the
first-production-run review Michel asked for:

  - total labelled / scored
  - cost (from the last label run in corpus/stats.json)
  - fit_label distribution
  - top 15 roles (by priority then fit)
  - all blocked_fit roles
  - any strong_fit where role is NOT the top signal contributor (probes
    Known Limitation F — domain/depth carrying a score the role doesn't justify)

    python -m scripts.score_report \
        --scored "corpus/scored/scored_*.jsonl" \
        --validated "corpus/validated/validated_*.jsonl" \
        --meta "corpus/raw/meta_20260609.jsonl"
"""

from __future__ import annotations

import argparse
import glob
import json
from collections import Counter

from models.record import ApplicationRecord, JDRecord
from scoring.profile import load_profile
from scoring.scorer import DEPTH_WEIGHT, DOMAIN_WEIGHT, ROLE_WEIGHT, stage1_fit


def _latest(globs: str) -> str:
    paths = sorted(glob.glob(globs))
    if not paths:
        raise SystemExit(f"no files match {globs!r}")
    return paths[-1]


def _load_scored(path: str) -> list[ApplicationRecord]:
    return [ApplicationRecord.from_jsonl(l) for l in open(path, encoding="utf-8") if l.strip()]


def _load_jds(globs: str) -> dict[str, JDRecord]:
    out: dict[str, JDRecord] = {}
    for path in sorted(glob.glob(globs)):
        for l in open(path, encoding="utf-8"):
            if l.strip():
                jd = JDRecord.from_jsonl(l)
                out[jd.id] = jd
    return out


def _load_meta(globs: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for path in sorted(glob.glob(globs)):
        for l in open(path, encoding="utf-8"):
            if l.strip():
                m = json.loads(l)
                out[m.get("source_url", "")] = m
    return out


def _last_label_cost(stats_path: str) -> dict | None:
    try:
        runs = json.load(open(stats_path, encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    labels = [r for r in runs if r.get("step") == "label"]
    return labels[-1] if labels else None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Report on a production scoring run.")
    p.add_argument("--scored", default="corpus/scored/scored_*.jsonl")
    p.add_argument("--validated", default="corpus/validated/validated_*.jsonl")
    p.add_argument("--meta", default="corpus/raw/meta_*.jsonl")
    p.add_argument("--profile", default="candidate_profile.yaml")
    p.add_argument("--stats", default="corpus/stats.json")
    args = p.parse_args(argv)

    scored = _load_scored(_latest(args.scored))
    jds = _load_jds(args.validated)
    meta = _load_meta(args.meta)
    profile = load_profile(args.profile)

    def title_of(app: ApplicationRecord) -> str:
        jd = jds.get(app.job_id)
        if jd and jd.source_url in meta:
            return meta[jd.source_url].get("title", "") or "?"
        return jd.company if jd else app.job_id[:16]

    def company_of(app):
        jd = jds.get(app.job_id)
        return jd.company if jd else "?"

    print("=" * 70)
    print("PRODUCTION SCORING RUN — REPORT")
    print("=" * 70)

    # total + cost
    cost = _last_label_cost(args.stats)
    print(f"total scored      : {len(scored)}")
    if cost:
        print(f"labelled          : {cost.get('labelled')}/{cost.get('records')} (failed {cost.get('failed')})")
        print(f"label cost        : ${cost.get('cost_usd', 0):.4f}  tokens={cost.get('tokens')}")

    # fit_label distribution
    dist = dict(sorted(Counter(a.fit_label for a in scored).items(), key=lambda kv: -kv[1]))
    print(f"\nfit_label distribution: {dist}")

    # top 15 by priority then fit
    ranked = sorted(scored, key=lambda a: (a.priority_score, a.fit_score), reverse=True)
    print("\nTOP 15 ROLES (by priority, then fit):")
    print(f"  {'pri':>3} {'fit':>3}  {'label':<18} {'company':<14} title")
    for a in ranked[:15]:
        print(f"  {a.priority_score:>3} {a.fit_score:>3}  {a.fit_label:<18} {company_of(a):<14} {title_of(a)}")

    # all blocked_fit
    blocked = [a for a in scored if a.fit_label == "blocked_fit"]
    print(f"\nALL blocked_fit ({len(blocked)}):")
    for a in sorted(blocked, key=lambda a: -a.fit_score):
        print(f"  fit={a.fit_score} {company_of(a):<14} {title_of(a)}")
        print(f"      {a.fit_label_reason}")

    # strong_fit where role is NOT the top signal contributor
    print("\nSTRONG_FIT where role is NOT the top signal contributor (probes Known Limit F):")
    flagged = 0
    for a in scored:
        if a.fit_label != "strong_fit":
            continue
        jd = jds.get(a.job_id)
        if not jd:
            continue
        _, bd = stage1_fit(jd, profile)
        role_c, domain_c, depth_c = bd.role * ROLE_WEIGHT, bd.domain * DOMAIN_WEIGHT, bd.technical_depth * DEPTH_WEIGHT
        if domain_c > role_c or depth_c > role_c:
            flagged += 1
            print(f"  {company_of(a):<14} {title_of(a)}")
            print(f"      role={role_c} domain={domain_c} depth={depth_c}  | role_type={jd.role_type} domain={jd.domain}")
    if not flagged:
        print("  (none — role was the top contributor for every strong_fit)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
