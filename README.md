# job-radar

A personal job search intelligence system. Identifies, assesses, prioritises,
and tracks job opportunities across AI, FinTech, infrastructure, and developer
tools verticals.

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

- **Multi-source collection** — Greenhouse, Lever, Ashby public APIs + VC
  portfolio boards (no auth required) + manual drop folder
- **Structured extraction** — 15-field schema validated on 10 real JDs before
  any automation ran; extracted via Claude Batch API (50% cost discount)
- **Rule-based fit scoring** — 5-dimension scorer against a candidate profile;
  separate fit_score and priority_score
- **Application tracking** — workflow states from new → shortlisted → applied
  → interviewing → offer/rejected
- **Continuous discovery** — weekly automated collection + daily digest of new
  roles above fit threshold
- **Read-only UI** — browse, filter, inspect — all writes through CLI only

---

## Architecture in One Paragraph

Job descriptions enter the pipeline from public ATS APIs and VC portfolio
boards, are cleaned and deduplicated by SHA-256 hash, labelled by the Claude
Batch API against a locked 15-field extraction schema, validated, and scored
against a candidate profile. Application state is tracked separately from
extraction in an ApplicationRecord layer. A pre-built index file powers a
read-only web UI for browsing and filtering. The CLI is the single source of
truth — all writes go through it.

---

## Architecture Diagram

```text
Sources (Greenhouse / Lever / Ashby / VC Boards / Manual)
↓
cli/collect.py
↓
corpus/raw/ (raw JSONL)
↓
cli/dedupe.py (SHA-256 on normalised text)
↓
corpus/raw/clean_* (deduplicated)
↓
cli/label.py (Claude Batch API)
↓
corpus/labelled/ (extraction schema applied)
↓
cli/validate.py
↓
corpus/labelled/validated_*
↓
cli/score.py (rule-based, candidate profile)
↓
corpus/scored/ (fit + priority scores)
↓
cli/stats.py --export-index
↓
corpus/index.json
↓
UI (read-only, nginx)
```

---

## Project Phases

| Phase | Name | Status |
|---|---|---|
| 1 | Corpus Engine | ✅ Complete |
| 2 | Scoring Engine | ✅ Complete |
| 3 | Job Tracker | ✅ Complete |
| 4 | Discovery Layer | ✅ Complete |
| 5 | UI | ✅ Complete |
| 6 | Fine-Tuned Analyser | Future / Project 5 |

Phases 1–5 are complete: Job Radar is feature-complete for v1 — collect →
clean/dedupe → label → validate → score → track → discover → browse. Phase 6
(fine-tuning) is deferred until the corpus is large enough to justify it. See
`docs/job_radar_SPEC.md` §2 for the detailed per-phase status.

---

## Key Findings

See `docs/CORPUS_FINDINGS.md` (schema v1.2, labelling rules) and
`docs/job_radar_ARCHITECTURE.md`.

---

## Lessons Learned

Maintained append-only in `docs/job_radar_LEARNINGS.md` — one entry per decision,
finding, or reversal across all phases (28 entries as of Phase 5).

---

## Running Locally

```bash
git clone https://github.com/michelguillon/job-radar
cd job-radar
cp .env.example .env
# Add ANTHROPIC_API_KEY to .env

docker compose build
docker compose run --rm job-radar python -m cli.collect --dry-run --source greenhouse
docker compose run --rm job-radar python -m cli.stats --input "corpus/validated/validated_*.jsonl"
```

**Test suite:**
```bash
docker compose run --rm job-radar python -m pytest -q
# Expected: 318 passing
```

**Browse the corpus (read-only UI):**
```bash
# (re)build the index the UI reads, then serve it
docker compose run --rm job-radar python -m cli.stats \
  --input "corpus/validated/validated_*.jsonl" --export-index
docker compose --profile ui up        # → http://localhost:8080
```

---

## Live Demo

Run locally — see **Browse the corpus** under *Running Locally* above
(`docker compose --profile ui up` → http://localhost:8080). The UI is a static,
read-only browse/filter interface over the pre-built `corpus/index.json`.

---

## Documentation

- [Specification](docs/job_radar_SPEC.md) — architecture, phases, UI contract (§9)
- [Architecture](docs/job_radar_ARCHITECTURE.md)
- [Learnings](docs/job_radar_LEARNINGS.md)
- [Retrospective](docs/job_radar_RETROSPECTIVE.md)
- [Corpus Findings](docs/CORPUS_FINDINGS.md) — schema v1.2, labelling rules
