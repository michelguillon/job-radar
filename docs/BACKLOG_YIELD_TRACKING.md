# Backlog Spec — Company Yield Tracking

**Status:** Backlog — do not build until prerequisites are met (see §1).
**Trigger:** §11.1 company metadata built + 4+ weeks production data accumulated.

---

## 1. Prerequisites (sequencing)

Build in this order — each is a hard dependency:

1. **`cli/analyse.py`** (already in §11.1 backlog) — the read-only reporting
   infrastructure this feature builds on. Yield tracking is an extension of
   analyse.py, not a separate system.

2. **Company metadata** (§11.1 backlog) — `domain`, `fit_hypothesis`, `notes`
   per company in `company_seeds.yaml`. Required for category rollups by domain
   and sector. The archetype and complexity_type rollups depend on additional
   metadata fields that are also in the §11.1 backlog but lower priority — add
   them to `company_seeds.yaml` alongside or after domain/fit_hypothesis.

3. **4+ weeks production data** — yield metrics are meaningless on small samples.
   `shortlist_rate` on 3 jobs from a company tells you nothing. Wait until most
   companies have ≥10 scored jobs before drawing conclusions.

---

## 2. Motivation

As Job Radar moves into production, every monitored company has a real operational
cost: collection, Batch API labelling, scoring, and review time. A 60+ company
universe with weekly collection runs needs operational visibility.

The system should help answer:

- Am I monitoring the right companies?
- Which companies produce shortlisted roles?
- Which companies produce high-scoring false positives?
- Which companies generate many jobs but no useful opportunities?
- Which sectors generate the best candidates?
- Which companies are worth the model spend?

This feature is **evidence gathering and operating discipline** — not scoring
input. It comes before using company metadata in the scorer.

---

## 3. Cost estimation

Full per-company cost attribution requires tagging each Batch API run with the
source company slug — a pipeline change. Defer that.

Instead, use **estimated cost per job** as a constant approximation:

```python
COST_PER_JOB_USD = total_labelling_cost / total_jobs_labelled
# e.g. $3.18 / 117 = ~$0.027 per job (from corpus/stats.json)
```

Recompute this constant on each analyse run from `corpus/stats.json`. Then:

```python
estimated_cost_usd = jobs_labelled * COST_PER_JOB_USD
```

This is an approximation — JD length varies, prompt caching affects cost — but
it's good enough for "is this company worth its tokens?" decisions. Flag it as
estimated in the output. Revisit per-company cost attribution if the approximation
proves too coarse after real usage.

---

## 4. Data model

All inputs are derived from existing files — no new storage required:

| Source | Provides |
|---|---|
| `company_seeds.yaml` | company name, ATS, slug, domain, sector group |
| `corpus/validated/*.jsonl` | jobs collected per company (via `company` field) |
| `corpus/scored/*.jsonl` | jobs scored, fit_score, fit_label per job |
| `corpus/activity_log.jsonl` | status events (shortlisted, applied, rejected, archived) |
| `corpus/annotations.jsonl` | high_score_rejected flags (annotation_type: fit_score_disagree on high-scoring roles) |
| `corpus/stats.json` | total cost → derives cost_per_job constant |

**No new files written.** `cli/analyse.py` reads and joins these at report time.

---

## 5. Metrics per company

```yaml
company_yield:
  company_name: Writer
  sector: ai_application_platforms       # from company_seeds.yaml grouping
  domain: ai_application_platform        # from company metadata (§11.1 prereq)
  ats: ashby
  slug: writer

  # Volume
  jobs_collected: 18        # validated JDRecords with company == Writer
  jobs_labelled: 18         # same (all validated records are labelled)
  jobs_scored: 18           # ApplicationRecords with matching job_id

  # Workflow outcomes (from activity_log.jsonl projection)
  reviewed: 12              # status ever moved from 'new' (any event recorded)
  shortlisted: 5            # latest status == shortlisted
  applied: 1                # latest status == applied | interviewing | offer | rejected
  rejected: 7               # latest status == rejected (or outcome event)
  archived: 6               # latest status == archived

  # Quality signals
  high_score_rejected: 3    # fit_score >= 7 AND status == rejected
                            # proxy for false positives — scorer said good, you said no

  # Cost (estimated)
  estimated_cost_usd: 0.49  # jobs_labelled * COST_PER_JOB_USD
  last_collected_at: 2026-06-11
```

**What `high_score_rejected` means:** a role the scorer rated well (≥7) that
you rejected. This is the primary signal for "scorer is wrong about this company"
— it does not mean the role was bad, it means the scorer's assessment didn't match
your decision. High rates warrant investigation: is the domain tagging wrong? Is
there a consistent blocker the scorer misses?

---

## 6. Derived metrics

Calculated at report time, never stored:

```python
review_rate         = reviewed / jobs_scored          # what % do you actually look at?
shortlist_rate      = shortlisted / max(reviewed, 1)  # of roles reviewed, how many make the cut?
apply_rate          = applied / max(reviewed, 1)
rejection_rate      = rejected / max(reviewed, 1)
false_positive_rate = high_score_rejected / max(reviewed, 1)  # scorer overconfidence signal
cost_per_shortlist  = estimated_cost_usd / shortlisted if shortlisted > 0 else None
cost_per_application = estimated_cost_usd / applied if applied > 0 else None
```

All rates displayed as percentages. `None` displayed as `—` (avoid division by zero
or misleading precision on small samples).

**Minimum sample guard:** suppress derived metrics (show `—`) when `jobs_scored < 5`.
A 50% shortlist_rate on 2 jobs is not information.

---

## 7. Category rollups

Roll up the same metrics aggregated by:

| Rollup | Source | Prerequisite |
|---|---|---|
| `sector` | company_seeds.yaml group name | None — already in seeds |
| `ats_provider` | company_seeds.yaml `ats` field | None — already in seeds |
| `domain` | company metadata §11.1 | §11.1 company metadata built |
| `archetype` | company metadata (extended) | Extended company metadata (after domain) |
| `complexity_type` | company metadata (extended) | Extended company metadata |

Build sector and ats_provider rollups in v1. Add domain rollup when §11.1
metadata is in place. Defer archetype and complexity_type rollups until those
fields are defined and populated.

---

## 8. Company action field

A manual annotation on each company — what to do with it next. Stored in
`company_seeds.yaml` as an optional `action` field:

```yaml
- {name: Writer, ats: ashby, slug: writer, action: keep}
- {name: CrowdStrike, ats: greenhouse, slug: crowdstrike, action: pause}
```

Vocabulary:

| Action | Meaning |
|---|---|
| `keep` | Monitoring is working — continue |
| `promote` | Increase priority — consider adding more seed variants |
| `downgrade` | Still monitoring but lower expectation |
| `pause` | Stop collecting until further notice (set in seeds, skip in collect.py) |
| `remove` | Delete from seeds entirely |
| `investigate_ats` | Slug may be wrong or company changed ATS |
| `review_manually` | Something interesting — look more carefully |

**Important:** action is editorial input only. It does not automatically change
collection behaviour in v1. A `pause` entry is noted in the report; the collection
skip behaviour is a future enhancement. This prevents accidental automation before
the data is trustworthy.

---

## 9. Report output

`cli/analyse.py --yield` (or `cli/analyse.py --report yield`) produces a
terminal-formatted report. No new UI view needed.

**Report sections:**

```
COMPANY YIELD REPORT — 2026-06-11
Corpus: 117 scored jobs | 62 companies | est. cost $3.18 | COST_PER_JOB $0.027

━━ Best performers (shortlist_rate desc) ━━━━━━━━━━━━━━━━━━━━
Company          Sector                Jobs  Reviewed  Shortlist%  Cost/shortlist
Writer           ai_application        18    12        42%         $0.10
Mistral AI       foundation_models     41    18        28%         $0.12
...

━━ High-volume noise (jobs_scored desc, shortlist_rate < 10%) ━━━━━
Company          Sector                Jobs  Reviewed  Shortlist%  FP%
CoreWeave        ai_data_infra         52    8         0%          38%
...

━━ High false-positive rate (false_positive_rate desc) ━━━━━━
Company          Jobs  FP%   Notes
...

━━ No live jobs ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Companies in seeds with zero validated records this run: ...

━━ Actions flagged ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Company          Action         Notes
CrowdStrike      pause          "Cybersecurity domain — poor fit despite technical roles"
...

━━ Category rollup (sector) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Sector                     Companies  Jobs  Shortlist%  Est. cost
foundation_models          6          89    31%         $2.40
ai_application_platforms   12         134   18%         $3.62
...
```

**Download from UI:** A "Download yield report" button in the React sidebar triggers
`GET /api/report/yield` → returns the same terminal-formatted text as a
`text/plain` download (`.txt` file). No new UI view, no new visualisation — just
the report as a file the browser saves. One endpoint, one download button.

---

## 10. Implementation steps (when prerequisites are met)

1. Add `action` field (optional) to `company_seeds.yaml` schema in
   `collectors/CLAUDE.md` and validate in `collect.py`
2. Build company yield aggregation in `cli/analyse.py`:
   - Join validated, scored, activity_log, annotations by company
   - Compute metrics per company
   - Compute sector and ats_provider rollups
   - Apply minimum sample guard (< 5 jobs → suppress rates)
3. `GET /api/report/yield` FastAPI endpoint — runs the aggregation, returns
   plain text
4. "Download yield report" button in React sidebar — calls the endpoint,
   triggers browser download
5. Add `estimated_cost_usd` column to `corpus/stats.json` schema (additive,
   no migration) so the constant can be read without recomputing
6. Docs: SPEC §11.1 updated, LEARNINGS entry, CLAUDE.md deviation if anything
   deviated

**Definition of Done:**
- `python -m cli.analyse --yield` produces a readable report against the live corpus
- Download button in UI works end-to-end
- `pause` action entries are visible in the report (collection skip is a future step)
- All existing tests pass

---

## 11. Non-goals (explicitly out of scope)

- Automatic company removal or pausing from collection
- Inferring personal preference from one rejected role
- Changing scoring based on company yield
- Per-company cost attribution from pipeline tagging (approximation is enough)
- Complex UI visualisation (terminal report + download is sufficient)
- Inferring "positive surprise" automatically (requires a definition — defer)
