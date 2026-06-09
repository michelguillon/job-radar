# jd-refinery

A pipeline for collecting, cleaning, labelling, and exporting job descriptions
into a structured corpus for fine-tuning and CV-tailoring workflows.

---

## Project Summary

jd-refinery collects job descriptions from public ATS APIs (Greenhouse, Lever,
Ashby) and VC portfolio job boards, cleans and deduplicates them, extracts
structured labels using the Claude Batch API, validates the output against a
locked schema, and exports a fine-tuning-ready corpus.

The corpus is the upstream input to Project 4 (fine-tuned JD analyser) and a
reusable asset for fit scoring and application prioritisation.

---

## Why I Built This

Fine-tuning a domain-specific model requires clean, labelled data before a
single training run can start. Most practitioners skip this step and wonder
why their fine-tuned model underperforms.

This project builds the data pipeline that makes Project 4 possible:

- A curated corpus of 200+ labelled job descriptions across AI, FinTech,
  infrastructure, and developer tools verticals
- A validated extraction schema derived empirically from 10 real JDs before
  any code was written
- A human-validated eval set with ground truth labels for model evaluation
- A cost baseline (tokens per JD, total labelling cost) before training begins

The schema was designed through practice, not assertion — 10 JDs were labelled
by hand before any automation ran, triggering 10 schema changes that improved
the final design.

---

## Key Features

- **Multi-source collection** — Greenhouse, Lever, Ashby public APIs + VC
  portfolio board scraper (BeautifulSoup) + manual drop folder
- **Hash-based deduplication** — SHA-256 on normalised text, catches cross-ATS
  duplicates that URL deduplication misses
- **Empirically-derived schema** — 15 extraction fields and 8 annotation fields,
  validated on 10 real JDs across 2 tiers before automation
- **Claude Batch API labelling** — 50% cost discount vs synchronous, cost tracked
  per run
- **Four-tier validation model** — Tier 1 (human-authored), Tier 2 (deep review),
  Tier 3 (light review), Tier 4 (automated). Every record carries its tier.
- **Fine-tuning export** — prompt/completion pairs in the format training
  pipelines expect
- **Corpus statistics** — record count by tier, source, role type; dedup rate;
  labelling cost to date

---

## Architecture in One Paragraph

Raw job descriptions enter the pipeline from four sources: Greenhouse, Lever,
and Ashby public APIs (no authentication required) and a VC portfolio board
scraper. Each record is cleaned (HTML stripped, whitespace normalised,
boilerplate removed), hashed for deduplication, and written to a JSONL
checkpoint. The Claude Batch API extracts structured labels against a locked
schema. A validation pass checks every record against the schema and logs
failures separately. The export step produces prompt/completion pairs for
fine-tuning and an eval set drawn from human-validated Tier 1 and Tier 2
records only. All state lives in JSONL files — no database, no web UI.

---

## Architecture Diagram

```text
Job Description Sources
↓
Greenhouse API / Lever API / Ashby API / VC Board Scraper / Manual
↓
collect.py
↓
corpus/raw/ (raw JSONL)
↓
dedupe.py (SHA-256 hash, boilerplate strip)
↓
corpus/raw/clean_* (deduplicated JSONL)
↓
label.py (Claude Batch API)
↓
corpus/labelled/ (extraction schema applied)
↓
validate.py (schema validation)
↓
corpus/labelled/validated_* / failures_*
↓
export.py
↓
corpus/finetune_export/ (prompt/completion pairs)
corpus/eval_set/ (human-validated ground truth)
corpus/stats.json (cost, dedup rate, failure rate)
```

---

## Key Findings

*To be completed post-build — see `PROJECT_ARCHITECTURE.md` and
`PROJECT_RETROSPECTIVE.md`.*

---

## Lessons Learned

*To be completed post-build — see `PROJECT_LEARNINGS.md`.*

---

## Running Locally

```bash
git clone https://github.com/michelguillon/jd-refinery
cd jd-refinery
cp .env.example .env
# Add ANTHROPIC_API_KEY to .env

docker compose build
docker compose run app python collect.py --dry-run --source greenhouse
docker compose run app python stats.py
```

**First run checklist:**
1. Verify Greenhouse slugs for at least 2 companies manually before running
2. Inspect 2 VC board pages and populate selectors in `vc_boards.yaml`
3. Copy Tier 1/2 JSONL records from `CORPUS_FINDINGS.md` into
   `corpus/manual/manual_20260606.jsonl`

---

## Live Demo

Not applicable — CLI pipeline, no web UI.

---

## Documentation

- [Architecture](PROJECT_ARCHITECTURE.md)
- [Retrospective](PROJECT_RETROSPECTIVE.md)
- [Learnings](PROJECT_LEARNINGS.md)
- [Specification](SPEC_JD_REFINERY.md)
- [Corpus Findings](CORPUS_FINDINGS.md)
