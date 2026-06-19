# job-radar

A personal job search intelligence system. Identifies, assesses, prioritises,
and tracks job opportunities across AI, FinTech, AdTech, and infrastructure verticals.

**Job Radar answers:** Which opportunities are worth pursuing?
**cv-tailor answers:** How should I pursue them?

---

## Why I Built This

Job searching at director/VP level in AI is a research problem, not a volume
problem. The challenge is not finding 100 roles — it is identifying the 10
worth investing time in, understanding why each one fits or doesn't, and
tracking the ones in progress.

Existing tools (LinkedIn, spreadsheets) either surface too much noise or lack
the structured analysis needed to make confident application decisions. Job
Radar replaces both with a pipeline that collects, labels, scores, and tracks
— built on the same data engineering practices used in production AI systems.

---

## Key Features

- **Multi-source collection** — Greenhouse, Lever, Ashby public APIs across
  109 monitored companies (no auth required) + manual drop folder; incremental
  collection with per-source cursors
- **Structured extraction** — 17-field schema validated on 10 real JDs before
  any automation ran; extracted via Claude Batch API (50% cost discount);
  prompt closed-vocabulary generated from executable schema enums
- **Rule-based fit scoring** — 3-stage scorer (structural fit → blocking
  constraints → opportunity classification); gates vs signal architecture;
  conditional Product role scoring; calibrated against 23-record adversarial
  corpus (10 positive + 13 negative); fit_label taxonomy:
  strong_fit / good_fit / stretch / blocked_fit / interview_practice / income_bridge
- **Application tracking** — append-only event log (Model C); workflow state
  survives re-scores; status from new → shortlisted → applied → interviewing
  → offer / rejected; outcome recording; manual fit override
- **Continuous discovery** — weekly automated collection + daily digest of new
  roles above fit threshold; since-cursor prevents re-labelling already-seen jobs
- **Corpus reporting** — `cli/analyse.py` with five reports: score distribution,
  pipeline status, company performance, requirement gaps, and company yield
  (shortlist rate, false-positive rate, cost-per-shortlist by company and domain)
- **Interactive UI** — React/Vite + FastAPI; browse, filter, inspect, and
  (owner-only, key-unlocked) manage workflow state, record rejection reasons,
  flag scoring issues, override fit labels, and download yield reports from the
  browser. Public visitors get read-only. All writes append to the same JSONL
  the CLI uses.

---

## Architecture in One Paragraph

Job descriptions enter the pipeline from public ATS APIs, are cleaned and
deduplicated by SHA-256 hash, labelled by the Claude Batch API against a
locked 17-field extraction schema, validated, and scored against a candidate
profile using a 3-stage rule-based scorer. Workflow state is tracked in an
append-only event log (separate from extraction — survives re-scores). A
pre-built joined index powers the React UI for browsing and filtering; the
FastAPI backend overlays live activity log state so writes appear immediately.
Company metadata (`domain`, `fit_hypothesis`, `action`) drives the yield
report to surface which companies produce the highest-signal roles.

---

## Architecture Diagram

```text
Sources (Greenhouse / Lever / Ashby — 109 companies)
↓
cli/collect.py  (incremental, per-source cursors)
↓
corpus/raw/ + corpus/raw/meta_* (raw JSONL + metadata sidecar)
↓
cli/prefilter.py  (location + role screen + cross-corpus dedup)
↓
corpus/filtered/
↓
cli/label.py  (Claude Batch API — 50% cost discount)
↓
corpus/labelled/
↓
cli/validate.py
↓
corpus/validated/
↓
cli/score.py  (3-stage rule-based scorer, candidate profile)
↓
corpus/scored/  (fit_score, fit_label, blocking_constraints)
↓
cli/stats.py --export-index
↓
corpus/index.json  (joined read model: score ⨝ JD ⨝ sidecar ⨝ activity log)
↓
React UI + FastAPI  (browse / filter / manage / annotate / download reports)

corpus/job_radar.db        ← SQLite (WAL): interactive state (activity log [append-only],
                             annotations, cv-tailor links) + company_seeds (109; mutable —
                             edit in UI, export to YAML). The *.jsonl twins are frozen audit
                             archives (Phase 6.5).
```

---

## Project Phases

| Phase | Name | Status |
|---|---|---|
| 1 | Corpus Engine | ✅ Complete — 95 tests |
| 2 | Scoring Engine | ✅ Complete — scorer v1 locked, calibrated |
| 3 | Job Tracker | ✅ Complete — Model C event log |
| 4 | Discovery Layer | ✅ Complete — incremental collection + digest + cron |
| 5 | Static UI | ✅ Complete |
| 6 | Interactive UI | ✅ Complete — React + FastAPI, 412 tests |
| 7 | Fine-Tuned Analyser | Future / Project 5 |

Phases 1–6 are complete. Post-Phase 6 backlog also shipped: `cli/analyse.py`
reporting, rejection reasons, company metadata v2, company yield tracking,
company universe expanded to 109 verified companies, and company-seed management
moved to SQLite with a browser UI (`cli/seeds.py`, `PATCH /api/companies`). Phase
7 (fine-tuning) is deferred until the corpus justifies it.

---

## Key Findings

See `docs/CORPUS_FINDINGS.md` (schema v1.2, labelling rules) and
`docs/job_radar_ARCHITECTURE.html`.

---

## Lessons Learned

Maintained append-only in `docs/job_radar_LEARNINGS.md` — 40 entries across
all phases and backlog work.

---

## Running Locally

```bash
git clone https://github.com/michelguillon/job-radar
cd job-radar
cp .env.example .env
# Add ANTHROPIC_API_KEY to .env

docker compose build
docker compose run --rm job-radar python -m cli.collect --dry-run --source greenhouse
docker compose run --rm job-radar python -m cli.stats
```

**Test suite:**
```bash
docker compose run --rm job-radar python -m pytest -q
# Expected: 412 passing
```

**Corpus reports:**
```bash
docker compose run --rm job-radar python -m cli.analyse --report all
docker compose run --rm job-radar python -m cli.analyse --report yield
```

**Browse + manage the corpus (interactive UI):**
```bash
# Rebuild the joined index, then serve React frontend + FastAPI backend
docker compose run --rm job-radar python -m cli.stats --export-index
docker compose --profile ui up        # → frontend :8080, API :8000
```

Public visitors get a read-only browse/filter/inspect interface. To manage
workflow state, record rejection reasons, flag scoring issues, and override
fit labels from the browser, set `JR_WRITE_KEY` in `.env` and click
**Unlock** in the top bar. No key configured = read-only for everyone
(fail-closed).

---

## Live Demo

[job-radar.michel-portfolio.co.uk](https://job-radar.michel-portfolio.co.uk)

Read-only browse/filter/inspect for public visitors. Owner unlocks write
controls (workflow + scoring flags + fit override) with `JR_WRITE_KEY`.

---

## Documentation

- [Specification](docs/job_radar_SPEC.md) — architecture, all phases, design decisions
- [Architecture](docs/job_radar_ARCHITECTURE.html) — implemented system reference
- [Learnings](docs/job_radar_LEARNINGS.md) — 40 entries, one per decision or reversal
- [Retrospective](docs/job_radar_RETROSPECTIVE.md) — what changed from spec to system
- [Corpus Findings](docs/CORPUS_FINDINGS.md) — schema v1.2, labelling rules
- [Company Universe Backlog](docs/BACKLOG_COMPANY_UNIVERSE.md)
- [Yield Tracking Backlog](docs/BACKLOG_YIELD_TRACKING.md)
