# PROJECT_ARCHITECTURE.md — jd-refinery

> **This document describes the implemented system.**
> **For original design intent, see `SPEC_JD_REFINERY.md`.**
> **For schema, labelling rules, and corpus records, see `CORPUS_FINDINGS.md`.**

*Status: stub — to be completed post-build by Claude Code.*
*See `SPEC_JD_REFINERY.md §12` for the Claude Code prompt that generates this document.*

---

## Overview

*[Claude Code completes post-build]*

jd-refinery is a CLI data pipeline that collects, cleans, labels, and exports
job descriptions into a structured corpus for fine-tuning and fit scoring.

---

## Design Principles

- **Schema before collection.** The extraction schema was validated on 10 real
  JDs before any automated collection ran. Schema decisions are architectural
  constraints, not data modelling afterthoughts.

- **Files all the way down.** JSONL at every stage. No database. The output
  format of one phase is the input format of the next and the final format
  for downstream consumers (fine-tuning pipelines).

- **Validation tier as first-class metadata.** Every record carries its tier
  (1–4). Downstream consumers filter by tier based on the quality bar they
  need. Uniform validation is a false standard.

- **Cost awareness by default.** Batch API used exclusively for labelling.
  Cost tracked per run. Total labelling cost is known before fine-tuning begins.

- **Extraction schema separated from annotation schema.** What the JD says
  (extraction) is never mixed with personal judgement (annotation). The
  boundary is enforced structurally, not by convention.

- **Empirical schema design.** The schema that works is the one that survived
  contact with real data, not the one that looked right on a whiteboard.

---

## High-Level Architecture

```text
Sources
↓
collect.py
↓
Raw JSONL checkpoint
↓
dedupe.py
↓
Clean JSONL checkpoint
↓
label.py (Claude Batch API)
↓
Labelled JSONL checkpoint
↓
validate.py
↓
Validated JSONL + Failures JSONL
↓
export.py
↓
Fine-tuning export + Eval set + Stats
```

---

## Component Breakdown

*[Claude Code completes post-build with actual implementation details]*

### collect.py

**Purpose:** Fetch job descriptions from all configured sources.

**Inputs:** `company_seeds.yaml`, `vc_boards.yaml`

**Outputs:** `corpus/raw/raw_{YYYYMMDD}.jsonl`

**Sources:**
```text
Greenhouse API → /v1/boards/{slug}/jobs?content=true
Lever API      → /v0/postings/{slug}?mode=json
Ashby API      → /posting-api/job-board/{slug}
VC Boards      → BeautifulSoup scrape per board config
Manual         → corpus/manual/ drop folder
```

---

### dedupe.py

**Purpose:** Remove exact duplicates, clean text.

**Inputs:** `corpus/raw/raw_*.jsonl`

**Outputs:** `corpus/raw/clean_{timestamp}.jsonl`

**Dedup key:** SHA-256 of normalised text (not URL — same JD can appear on
multiple ATS platforms).

---

### label.py

**Purpose:** Extract structured schema fields from raw JD text via Claude
Batch API.

**Inputs:** `corpus/raw/clean_*.jsonl`

**Outputs:** `corpus/labelled/labelled_{timestamp}.jsonl`

**Model:** claude-sonnet-4-6 via `/v1/messages/batches`

---

### validate.py

**Purpose:** Validate labelled records against schema v1.2. Log failures.

**Inputs:** `corpus/labelled/labelled_*.jsonl`

**Outputs:**
- `corpus/labelled/validated_{timestamp}.jsonl`
- `corpus/labelled/failures_{timestamp}.jsonl`

---

### export.py

**Purpose:** Produce fine-tuning-ready prompt/completion pairs and eval set.

**Inputs:** `corpus/labelled/validated_*.jsonl`

**Outputs:**
- `corpus/finetune_export/export_train_*.jsonl`
- `corpus/finetune_export/export_eval_*.jsonl`
- `corpus/stats.json`

---

### stats.py

**Purpose:** Print corpus statistics to terminal.

**Inputs:** All JSONL files in `corpus/`

**Outputs:** Terminal summary (record count, cost, dedup rate, failure rate)

---

## User Journeys

### Manual Tier 1/2 labelling

```text
Raw JD text (paste or file)
↓
manual_add.py / tier2_review.py
↓
Human labels every extraction field
↓
Claude structures output into schema format
↓
corpus/manual/ JSONL record
↓
Claude extraction run (Tier 1: after human labels saved)
↓
Comparison written to corpus/eval_set/
```

### Automated collection and labelling

```text
company_seeds.yaml + vc_boards.yaml
↓
collect.py --source all
↓
corpus/raw/raw_{date}.jsonl
↓
dedupe.py
↓
corpus/raw/clean_{date}.jsonl
↓
label.py --tier 4
↓
Claude Batch API (50% cost discount)
↓
corpus/labelled/labelled_{date}.jsonl
↓
validate.py
↓
corpus/labelled/validated_{date}.jsonl
```

### Fine-tuning export

```text
corpus/labelled/validated_*.jsonl
↓
export.py --set eval   (Tier 1+2+3, human-validated)
export.py --set train  (all tiers)
↓
{"prompt": "<JD text>", "completion": "<extraction JSON>"}
↓
corpus/finetune_export/
↓
Handoff to Project 4
```

---

## Data Flow

```text
Raw HTML / text
↓
strip_html() → strip_boilerplate() → normalise()
↓
record_hash() → SHA-256 dedup key
↓
JDRecord (extraction fields: null, annotation fields: null)
↓
Claude Batch API extraction
↓
JDRecord (extraction fields populated)
↓
validate() → schema check
↓
JSONL checkpoint
↓
export() → prompt/completion pairs
```

---

## Technical Stack

| Component | Technology |
|---|---|
| Language | Python 3.13 |
| Containerisation | Docker, python:3.13-slim |
| HTTP clients | httpx (async), requests |
| HTML parsing | BeautifulSoup4, lxml |
| LLM labelling | Anthropic Batch API, claude-sonnet-4-6 |
| Storage | JSONL files |
| Config | YAML (company_seeds, vc_boards) |
| Testing | pytest |
| Scheduling | cron (weekly collection) |

---

## Major Architecture Decisions

*[Claude Code completes post-build — confirm which decisions from
SPEC_JD_REFINERY.md §3 were implemented as designed and which deviated]*

Key decisions from spec (verify against implementation):

- Batch API over synchronous labelling — §3.6
- SHA-256 on normalised text for dedup — §3.7
- JSONL over database — §3.9
- Schema before collection phase ordering — §3.1
- Four-tier validation model — §3.4
