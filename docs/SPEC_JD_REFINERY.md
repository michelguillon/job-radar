# SPEC_JD_REFINERY.md — jd-refinery
## Architecture Specification

> **This document reflects the original design intent.**
> **For the implemented system, see `PROJECT_ARCHITECTURE.md`.**

**Project:** 3.5 — JD Dataset Builder (bridge project)  
**Repository:** jd-refinery (standalone)  
**Status:** Pre-implementation — schema locked at v1.2, ready for Claude Code  
**Last updated:** 2026-06-06  
**Deployment target:** M720q home server, Ubuntu Server 24.04, Docker  
**Feeds into:** Project 4 — Fine-tuned JD Analyser  
**Related project:** cv-tailor (live in production — see §10)

---

## 1. Project Goals

**Learning goal:** Build a real data engineering pipeline — collection,
cleaning, deduplication, schema design, weak labelling, eval set creation,
and cost modelling. These are the skills that appear before any fine-tuning
project starts and that practitioners who haven't done it tend to
underestimate.

**Real-use goal:** Produce a reusable, curated corpus of job descriptions
that appreciates over time. The corpus feeds Project 4 (fine-tuning), informs
fit scoring, and serves as the raw material for any future application
prioritisation work. The schema was validated against 6 real JDs before any
code was written — see `CORPUS_FINDINGS.md §5`.

**Portfolio goal:** Demonstrate data pipeline engineering, not just model
usage. The ability to design and validate a labelling schema empirically —
through practice, not upfront assertion — and to reason about weak supervision,
eval set contamination, and cost modelling is what separates a practitioner
from someone who calls APIs.

---

## 2. What This System Does

A CLI pipeline with five sequential phases: collect → clean/dedup → label
→ validate → export. Each phase produces a durable JSONL checkpoint. No
phase depends on the previous one completing in the same session — the
pipeline is resumable at any point.

```
collect.py      → fetch JDs from Greenhouse / Lever / Ashby APIs + VC board scraper
                  output: corpus/raw/raw_{timestamp}.jsonl

dedupe.py       → hash-based deduplication, text cleaning
                  output: corpus/raw/clean_{timestamp}.jsonl

label.py        → Claude Batch API extraction against locked schema
                  output: corpus/labelled/labelled_{timestamp}.jsonl

validate.py     → schema validation, failure logging, cost summary
                  output: corpus/labelled/validated_{timestamp}.jsonl
                          corpus/labelled/failures_{timestamp}.jsonl

export.py       → fine-tuning format + corpus statistics
                  output: corpus/finetune_export/export_{timestamp}.jsonl
                          corpus/stats.json
```

**Manual drop folder:** `corpus/manual/` — JSONL records authored by hand
using the same schema as the API collector. Used for Tier 1 and Tier 2
work and for companies not covered by any API source. Six Tier 1 records
already exist here — see `CORPUS_FINDINGS.md §5`.

**The pipeline does not run continuously.** It is invoked on demand.
A cron job (weekly) runs `collect.py` to grow the corpus passively after
the initial build is complete.

---

## 3. Architecture Decisions

### 3.1 — Phase ordering: schema before collection

**Decision:** Draft and validate the extraction schema before building the
automated collector. The schema determines what fields `corpus/raw/`
records must carry. Building the collector first and designing the schema
second means either re-running collection or writing a migration.

**The sequence:**
1. Seed schema drafted (this spec, §4)
2. Tier 1 work (6 JDs completed) — schema iterated by hand ✅
3. Tier 2 (10 JDs in progress) — deep review, schema evolving ✅
4. Schema v1.2 — see `CORPUS_FINDINGS.md` for full record set
5. Collector built against frozen schema
6. Automated phases run

**Alternatives rejected:**
*Collect first, schema later* — creates a migration problem when the raw
format and the extraction schema turn out to be coupled. Discovered on
every data project that skips this step.

**What this teaches:** Schema design is not a downstream concern in a
labelling pipeline. It is the first constraint that everything else must
satisfy.

---

### 3.2 — Schema design: empirical discovery, not upfront assertion

**Decision:** The extraction schema was not fully designed upfront. It was
discovered through Tier 1 practice and locked after 6 JDs. The process:

**Seed schema** — fields confident from first principles. Present in
almost every JD, objectively extractable, unambiguous definitions.

**Free-text escape valve** (`raw_observations`) — captures anything the
seed schema does not cover. After Tier 1, patterns reviewed and promoted
to fields where they met the formalisation gate.

**The formalisation gate:** A field is promoted from observation to schema
field only if it appears in 3+ Tier 1 JDs, is distinct from existing
fields, can be extracted objectively, and is useful downstream.

**The freeze point:** Schema locked after Tier 1 (6 JDs) with two open
questions deferred to Tier 2. No new fields after Tier 2 completes.

**What happened in practice:** 8 schema changes were triggered by 6 JDs.
The most significant were the four-field skills split (required_technologies,
required_competencies, nice_to_have_technologies, nice_to_have_competencies)
and the addition of culture_signals and application_decision. Full change
log in `CORPUS_FINDINGS.md §1.2`.

**Alternatives rejected:**
*Design the full schema upfront* — the fields look obvious until you read
10 real JDs and discover that "seniority" is stated differently across
companies, "required skills" and "nice to have" are blurred, and some
fields you assumed were universal are absent 40% of the time.

**What this teaches:** Schema design for labelling pipelines is an
empirical activity. The schema that works is the one that survived contact
with real data, not the one that looked right on a whiteboard.

---

### 3.3 — Two schemas, clearly separated

**Decision:** The pipeline operates with two distinct schemas that are
never mixed in the same record.

**Extraction schema** — what Claude extracts from every JD. Objective,
consistent fields that generalise across all JDs regardless of who is
reading them. This feeds fine-tuning. Claude populates this.

**Annotation schema** — fields only Michel fills in, never Claude. Tracks
personal job search activity, subjective fit assessment, and application
decisions. Claude never touches these fields.

```
Extraction schema fields (locked v1.1 — see §4.1 for full definition):
  role_type, seniority, technical_depth, years_experience_required,
  required_technologies, required_competencies,
  nice_to_have_technologies, nice_to_have_competencies,
  domain, remote_policy, location, company_size_signal, company_stage,
  culture_signals, raw_observations

Annotation schema fields (human-only, never extraction targets):
  fit_score                  # 1–10 integer, Michel's personal assessment
  applied                    # bool
  application_date           # ISO date or null
  application_decision       # "applied" | "not_applied_fit" |
                             # "not_applied_structural" |
                             # "not_applied_timing" | "pending"
  application_decision_notes # free text
  location_workable          # "yes" | "no" | "conditional" | "unknown"
  location_notes             # free text — e.g. "Paris hybrid, workable if travel covered"
  blocking_constraints       # list[str] — hard stops beyond location
  notes                      # personal free text
```

**Why `red_flags` and `fit_indicators` were dropped:** Both are subjective.
"Red flag" means different things to different candidates. A schema field
that varies by reader is noise, not a training signal. These belong in
`notes` as personal observations.

**Why `application_decision` was added:** `applied: bool` alone doesn't
capture why an application was or wasn't made. A fit_score of 5 can still
produce an application; a fit_score of 7 can be blocked by a structural
gap. Separating fit from decision is critical for downstream fit scoring
model training.

**What this teaches:** The boundary between "what the data says" and "what
I think about the data" is a design decision. Conflating them produces a
corpus contaminated by the labeller's personal priors.

---

### 3.4 — Tier model: four validation tiers

**Decision:** The corpus is not uniformly validated. Records carry a `tier`
field that documents exactly how much human validation they received.

**Tier 1 — Schema-forming (6 JDs — COMPLETE ✅):**
Michel reads the full JD, forms independent judgement on every field,
uses Claude to structure and express that judgement in the schema format.
Claude is a formatting and articulation tool, not an extraction engine.

**Tier 2 — Deep review (15 JDs — 10 complete, 5 remaining):**
Claude extracts first. Michel does a field-by-field review. Michel is the
authority. Schema is stress-tested on harder cases. Two open questions
from Tier 1 resolved here. Schema fully frozen after Tier 2.

**Tier 3 — Light review (50 JDs):**
Claude extracts. Michel spends 2–3 minutes per JD checking for systematic
failures: wrong seniority, hallucinated skills, misclassified role type.
Not field-by-field — failure mode detection only.

**Tier 4 — Automated (130+ JDs, ~200 total):**
Claude extracts. Schema validation runs in code. Failures logged.
No per-JD human review. Aggregate QA only.

**Phase gates between tiers:**
- Tier 1 → Tier 2: schema stable ✅ (complete)
- Tier 2 → Tier 3: Claude agreement rate on Tier 2 ≥80% (field by field;
  `required_technologies` and `required_competencies` excluded — partial
  matches expected)
- Tier 3 → Tier 4: no systematic failure mode in Tier 3 (same field wrong
  in 3+ records = systematic)

---

### 3.5 — Collection sources: four-source strategy

**Decision:** Four source types, each with a defined role and maintenance
cost ceiling.

**Source 1 — Greenhouse public API (primary):**
```
GET https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true
```
No auth. Returns structured JSON with full JD content. Covers Series B+
tech companies. Slug is usually company name lowercased.

**Source 2 — Lever public API (secondary):**
```
GET https://api.lever.co/v0/postings/{slug}?mode=json
```
No auth. Same pattern as Greenhouse. Covers some AI companies not on
Greenhouse (Hugging Face, Cohere, Mistral confirmed on Lever).

**Source 3 — Ashby public API (secondary):**
```
GET https://api.ashbyhq.com/posting-api/job-board/{slug}
```
No auth. ATS of choice for AI-native startups and VC-backed companies
that haven't scaled to Greenhouse.

**Source 4 — VC portfolio job boards (HTML scrape, scoped):**
Eight boards, one scrape per board. BeautifulSoup only — no Playwright.
If a board requires JavaScript, mark `status: requires_js` in
`vc_boards.yaml` and skip.

| VC | Board URL | Coverage focus |
|---|---|---|
| a16z | jobs.a16z.com | US AI, infrastructure |
| Sequoia | jobs.sequoiacap.com | US AI, SaaS, fintech |
| Index Ventures | jobs.indexventures.com | EU/US B2B SaaS, fintech |
| Balderton | jobs.balderton.com | EU deep tech, B2B |
| Atomico | jobs.atomico.com | EU AI, infrastructure |
| Accel | accel.com/jobs | US/EU enterprise SaaS |
| General Catalyst | jobs.generalcatalyst.com | US AI, healthtech |
| Lightspeed | jobs.lsvp.com | US/EU enterprise, AI |

**`corpus/manual/` drop folder:**
JSONL records authored by hand. Used for Tier 1/Tier 2 and for companies
not covered by any API. Six Tier 1 records live here already.

**Explicitly excluded:**
LinkedIn, Indeed, Glassdoor — anti-bot measures, high-effort, low-reliability.

---

### 3.6 — Claude Batch API for labelling (not synchronous)

**Decision:** Phase 3 (labelling) uses the Anthropic Batch API exclusively.

**Why:** 50% cost discount. A corpus of 200 JDs at ~2,000 tokens per JD
costs roughly $0.60 synchronous vs $0.30 batch at current Sonnet pricing.
The pipeline is not latency-sensitive.

**The batch pattern:**
1. Build batch request: one request object per unlabelled JD
2. Submit to `/v1/messages/batches`
3. Poll until `processing_status == "ended"`
4. Download results, match to original records by `custom_id`
5. Validate schema on each result, log failures separately

**Cost tracking:** Every batch run logs to `corpus/stats.json`:
```json
{
  "batch_runs": [{
    "run_id": "batch_abc123",
    "timestamp": "2026-06-06T...",
    "records_submitted": 130,
    "records_succeeded": 128,
    "records_failed": 2,
    "input_tokens": 280000,
    "output_tokens": 45000,
    "estimated_cost_usd": 0.31
  }]
}
```

**What this teaches:** The Batch API is the default choice for any offline
processing pipeline. Using it is baseline competence, not a differentiator.

---

### 3.7 — Deduplication: hash on cleaned text, not URL

**Decision:** Deduplication key is SHA-256 of normalised JD text, not
the source URL. The same JD can appear on multiple ATS platforms.

**Normalisation before hashing:**
- Strip HTML tags
- Collapse whitespace
- Lowercase
- Strip common boilerplate footers (EEO statements etc.)

**Near-duplicate limitation:** Exact text hashing misses 95%-identical
JDs with minor edits. Near-duplicate detection (MinHash/SimHash) is out
of scope for the initial build.

---

### 3.8 — Corpus volume: 200 target, grow passively

**Decision:** Initial build target is 200 JDs. After the initial build,
`collect.py` runs weekly via cron and appends new records passively.

**The 200 breakdown:**
- Tier 1: 6 JDs (schema-forming — complete ✅)
- Tier 2: 15 JDs (deep review, schema frozen after)
- Tier 3: 50 JDs (light review)
- Tier 4: 129 JDs (automated)

**Eval set:** 30–40 JDs drawn from Tier 1 and Tier 2 records only.

---

### 3.9 — No web UI, no database — files all the way down

**Decision:** JSONL files, not a database. No web UI. CLI scripts only.

**Why JSONL:** The pipeline produces JSONL at every stage because that is
the format fine-tuning pipelines consume. A database layer would require
an export step to return to JSONL for Project 4.

**Inspection tooling:** `stats.py` prints corpus statistics to terminal.
This is the "dashboard" for a data pipeline — a script you run, not a
page you visit.

---

## 4. Schemas

### 4.1 — Locked extraction schema (v1.2)

Schema at v1.2 after Tier 1 and Tier 2 validation. Full change log in
`CORPUS_FINDINGS.md §1.2`.

```python
SCHEMA_VERSION = "1.2"

@dataclass
class JDRecord:
    # --- Identity ---
    id: str                      # SHA-256 of normalised text
    source_url: str
    source_ats: str              # "greenhouse"|"lever"|"ashby"|"vc_board"|"manual"
    company: str
    collected_at: str            # ISO datetime
    tier: int                    # 1 / 2 / 3 / 4

    # --- Raw content ---
    raw_html: str | None
    raw_text: str

    # --- Extraction schema (Claude-populated Tier 3+, human-structured Tier 1-2) ---
    role_type: list[str]         # max 3 values
                                 # "Solutions Engineering" | "Solutions Consulting" |
                                 # "Solutions Architecture" | "AI Delivery" |
                                 # "Delivery Leadership" | "Pre-Sales" |
                                 # "Strategic Pursuits" | "Partner SA" |
                                 # "Product" | "GTM"

    seniority: str               # "ic" | "senior_ic" | "lead" | "manager" |
                                 # "director" | "vp" | "exec"

    technical_depth: str         # "hands_on" | "hybrid" | "leadership"

    years_experience_required: str  # never inferred — "not_stated" if not explicit

    required_technologies: list[str]
    required_competencies: list[str]
    nice_to_have_technologies: list[str]
    nice_to_have_competencies: list[str]

    domain: list[str]            # "AI Platform" | "AI/ML" | "Data & Analytics" |
                                 # "FinTech" | "Payments" | "Financial Services" |
                                 # "Product Design" | "SaaS" | "Enterprise Software" |
                                 # "Consulting" | "AdTech" | "Infrastructure" |
                                 # "Developer Tools" | "Customer Experience" |
                                 # "Revenue Technology"

    remote_policy: str           # "remote" | "hybrid" | "onsite" | "not_stated"

    location: str                # verbatim from JD — never normalised or inferred

    delivery_motion: list[str]   # "pre_sales" | "direct_delivery" | "partner_delivery" |
                                 # "partner_enablement" | "customer_success" |
                                 # "professional_services"

    leadership_geography: list[str]  # e.g. ["EMEA"] | ["Global"] | []
                                     # empty for IC roles or scope not stated

    company_size_signal: str     # "startup" | "scale_up" | "enterprise" | "not_stated"

    company_stage: str           # "seed" | "series_a" | "series_b" | "series_c_plus" |
                                 # "pre_ipo" | "listed" | "not_stated"

    culture_signals: list[str]   # verbatim phrases only

    raw_observations: str

    # --- Annotation schema (human-only, never extraction targets) ---
    fit_score: int | None        # 1–10 integer
    applied: bool
    application_date: str | None
    application_decision: str    # "applied" | "want_to_apply" | "pending" |
                                 # "not_applied_fit" | "not_applied_structural" |
                                 # "not_applied_timing"
    application_decision_notes: str
    location_workable: str       # "yes" | "no" | "conditional" | "unknown"
    location_notes: str
    domain_distance: str         # "low" | "medium" | "high" | "not_assessed"
    blocking_constraints: list[str]
    notes: str
```

---

### 4.2 — Raw JSONL record envelope

```json
{
  "schema_version": "1.2",
  "id": "sha256:abc123...",
  "source_url": "https://boards.greenhouse.io/anthropic/jobs/12345",
  "source_ats": "greenhouse",
  "company": "Anthropic",
  "collected_at": "2026-06-06T14:32:00Z",
  "tier": 4,
  "raw_html": "<div>...",
  "raw_text": "About the role...",
  "extraction": {
    "role_type": ["Solutions Engineering", "Pre-Sales"],
    "seniority": "senior_ic",
    "technical_depth": "hybrid",
    "years_experience_required": "5+",
    "required_technologies": ["Python", "LLM APIs"],
    "required_competencies": ["enterprise sales cycle", "executive communication"],
    "nice_to_have_technologies": ["LangChain", "RAG"],
    "nice_to_have_competencies": ["MEDDPICC"],
    "domain": ["AI Platform"],
    "remote_policy": "hybrid",
    "location": "London",
    "delivery_motion": ["pre_sales"],
    "leadership_geography": [],
    "company_size_signal": "scale_up",
    "company_stage": "not_stated",
    "culture_signals": ["be curious", "move fast"],
    "raw_observations": ""
  },
  "annotation": {
    "fit_score": null,
    "applied": false,
    "application_date": null,
    "application_decision": "pending",
    "application_decision_notes": "",
    "location_workable": "yes",
    "location_notes": "London hybrid — no issue",
    "domain_distance": "not_assessed",
    "blocking_constraints": [],
    "notes": ""
  }
}
```

**`schema_version`** is written on every record. Current version is `"1.2"`.
Increment if schema changes after Tier 2 freeze (it should not). Append-only
— never migrate records in place. Full version history in
`CORPUS_FINDINGS.md §1.2`.

---

### 4.3 — Labelling rules (from Tier 1 practice)

| Rule | Definition |
|---|---|
| Remote policy default | `"based in [city]"` = `"hybrid"`. Only `"onsite"` if explicitly stated. |
| Location extraction | Extract verbatim. Never normalise. `"not_stated"` when absent. Never infer from company HQ knowledge. |
| Location workable | Annotation only. `"yes"` = London or remote. `"no"` = relocation outside commutable range required. `"conditional"` = nearby city hybrid workable if travel covered. `"unknown"` = location not stated. |
| delivery_motion | Reflects how value is delivered, not what function. Can be multi-value: `["pre_sales", "direct_delivery"]` for hybrid roles. |
| leadership_geography | Empty `[]` for IC roles. Populate only when scope explicitly stated or clearly implied by title. |
| Years not stated | Never infer from context. `"not_stated"` if not explicit. Qualitative signal goes in `raw_observations`. |
| No external knowledge | Extract only what the JD states. No company policy knowledge imported into extraction fields. |
| Technology vs competency | Tool/system = technology. Behaviour/capability = competency. "Collaborating with X" is a competency. |
| Proprietary platforms | Extract as stated, note in `raw_observations` that platform is proprietary. Never infer capabilities. |
| company_stage inference | Explicit or unambiguously inferable only. Never from company name alone. |
| Sparse culture signals | Do not pad. A short list is a valid signal about company culture. |
| role_type pairing | `"Solutions Consulting"` paired with `"Pre-Sales"` or `"AI Delivery"` where motion is clear. |
| Contamination rule | Claude extraction on Tier 1 JDs runs only after human labels saved. |

---

## 5. Implementation Steps

Work through these in order. Do not move to the next step until the
current one passes its verification check. Tier 1 is complete — start
at Step 0.

---

### Step 0 — Project scaffold

```
jd-refinery/
├── corpus/
│   ├── manual/          ← Tier 1 records already here; gitignored
│   ├── raw/             ← collector output; gitignored
│   ├── labelled/        ← Claude extraction output; gitignored
│   ├── eval_set/        ← human-validated ground truth; gitignored
│   └── finetune_export/ ← prompt/completion pairs; gitignored
├── collectors/
│   ├── __init__.py
│   ├── greenhouse.py
│   ├── lever.py
│   ├── ashby.py
│   └── vc_boards.py
├── pipeline/
│   ├── __init__.py
│   ├── clean.py
│   ├── dedupe.py
│   ├── label.py
│   └── validate.py
├── models/
│   └── record.py        ← JDRecord dataclass + schema version
├── collect.py
├── dedupe.py
├── label.py
├── validate.py
├── export.py
├── stats.py
├── company_seeds.yaml
├── vc_boards.yaml
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env
├── .env.example
├── .gitignore
└── README.md
```

**`company_seeds.yaml` format:**
```yaml
companies:
  - name: Anthropic
    ats: greenhouse
    slug: anthropic
  - name: Mistral
    ats: lever
    slug: mistral
```

**`.gitignore` must include:** `corpus/`, `.env`, `*.jsonl`

**Claude Code prompt:**
> Create the project scaffold defined in SPEC_JD_REFINERY.md §5 Step 0.
> Create all directories with .gitkeep files, all Python modules as empty
> files with a module docstring, the YAML seed files with the format shown,
> and the Docker setup (python:3.13-slim, one service, bind-mount).
> Copy the 10 Tier 1/2 JSONL records from CORPUS_FINDINGS.md §5 into
> corpus/manual/manual_20260606.jsonl. Do not write any pipeline logic yet.
> Verify the Docker setup builds cleanly.

*Verification:* `docker compose build` succeeds. Directory tree matches
spec. Tier 1 records exist in `corpus/manual/`.

---

### Step 1 — JDRecord model + schema validation

Build `models/record.py`:
- `JDRecord` dataclass with all fields from §4.1
- `SCHEMA_VERSION = "1.1"`
- `to_jsonl() -> str`
- `from_jsonl(line: str) -> JDRecord` — validate schema version, raise on mismatch
- `validate(record: JDRecord) -> list[str]` — returns validation errors

**Claude Code prompt:**
> Build models/record.py as defined in SPEC_JD_REFINERY.md §4.1 and §5
> Step 1. Include the JDRecord dataclass, SCHEMA_VERSION = "1.2",
> to_jsonl / from_jsonl methods, and a validate() function that returns
> a list of validation error strings. Write tests/test_record.py with
> round-trip serialisation tests and validation tests for known-bad records.
> Use the 10 records from corpus/manual/manual_20260606.jsonl as
> real test fixtures — they must all pass round-trip and validation.

*Verification:* `pytest tests/test_record.py` passes. All 6 Tier 1 records
deserialise and re-serialise without data loss.

---

### Step 2 — Text cleaning + deduplication

Build `pipeline/clean.py` and `pipeline/dedupe.py`.

**`clean.py`:**
- `strip_html(text: str) -> str`
- `normalise(text: str) -> str` — collapse whitespace, lowercase
- `strip_boilerplate(text: str) -> str` — EEO footer patterns (starts empty,
  populated from Tier 1/2 observations)
- `clean(raw_html: str) -> str` — pipeline: strip_html → strip_boilerplate → normalise

**`dedupe.py`:**
- `record_hash(normalised_text: str) -> str` — SHA-256, returns `"sha256:{hex}"`
- `dedupe(records, seen) -> tuple[list[JDRecord], int]`

**Claude Code prompt:**
> Build pipeline/clean.py and pipeline/dedupe.py as defined in
> SPEC_JD_REFINERY.md Step 2. Boilerplate strip list starts with three
> common EEO footer patterns. Write tests. Also use clean() to compute
> the SHA-256 hashes for the 6 Tier 1 records in corpus/manual/ and
> update their id fields from "sha256:pending" to real values.

*Verification:* `pytest tests/test_clean.py tests/test_dedupe.py` passes.
Tier 1 records have real SHA-256 ids.

---

### Step 3 — Greenhouse collector

Build `collectors/greenhouse.py` and `collect.py` CLI:

```python
def fetch_company(slug: str, company_name: str) -> list[JDRecord]:
    """Fetch all live jobs from Greenhouse public API."""
```

- 404 → log warning, return empty list
- 429 → exponential backoff, 3 retries
- Leave all extraction fields as `None`
- `tier = 4` default

**CLI:**
```bash
python collect.py --source greenhouse
python collect.py --source greenhouse --company anthropic
python collect.py --source all
python collect.py --dry-run
```

Output: appends to `corpus/raw/raw_{YYYYMMDD}.jsonl`

**Claude Code prompt:**
> Build collectors/greenhouse.py and collect.py CLI as defined in
> SPEC_JD_REFINERY.md Step 3. Read slugs from company_seeds.yaml.
> Exponential backoff on 429. Log and skip on 404. Tests with mocked
> HTTP responses.

*Verification:* Dry run prints count without writing. Live run against
one verified slug writes valid JSONL. Tests pass.

---

### Step 4 — Lever and Ashby collectors

Same pattern as Step 3.

**Lever:** `GET https://api.lever.co/v0/postings/{slug}?mode=json`  
**Ashby:** `GET https://api.ashbyhq.com/posting-api/job-board/{slug}`

**Claude Code prompt:**
> Build collectors/lever.py and collectors/ashby.py following the same
> pattern as collectors/greenhouse.py. Extend collect.py to route by
> the ats field in company_seeds.yaml. Tests with mocked responses.

*Verification:* Dry runs succeed. Live tests against one Lever and one
Ashby slug confirmed working.

---

### Step 5 — VC board scraper

Build `collectors/vc_boards.py`.

**Constraints:** BeautifulSoup only. If JS required, mark `status: requires_js`
in `vc_boards.yaml` and skip gracefully. Per-board selector config in YAML —
do not hardcode selectors.

**`vc_boards.yaml` format:**
```yaml
boards:
  - name: a16z
    url: https://jobs.a16z.com
    status: active
    selector: ".job-listing"
    fields:
      title: ".job-title"
      company: ".company-name"
      url: "a[href]"
    notes: ""
```

> **Before building:** Inspect two boards manually and populate their
> selectors in vc_boards.yaml. Do not guess selectors.

**Claude Code prompt:**
> Build collectors/vc_boards.py with per-board config from vc_boards.yaml.
> BeautifulSoup scraping, selector-driven. Add --source vc_boards to
> collect.py. Skip boards with status: requires_js gracefully. Log record
> count per board.

*Verification:* Two boards scraped successfully. requires_js boards
skipped without error.

---

### Step 6 — Tier 2 labelling tooling

Build support for the Tier 2 workflow. Tier 2 records come from any source
(manual or API-collected) and go through deep human review.

**`tier2_review.py` CLI:**
```bash
python tier2_review.py --input corpus/raw/clean_*.jsonl
```

For each unlabelled record:
1. Display raw_text in terminal (truncated to 500 chars)
2. Run Claude extraction against the locked schema
3. Display extraction output field by field
4. Prompt for review decision: `[a]ccept / [e]edit / [s]kip`
5. On accept: write to `corpus/manual/tier2_{date}.jsonl` with `tier=2`
6. On edit: open field-by-field correction mode
7. On skip: log to skipped file, continue

**Claude Code prompt:**
> Build tier2_review.py as defined in SPEC_JD_REFINERY.md Step 6.
> Use the locked extraction prompt from Step 7 (placeholder for now —
> insert after Step 7 is built). The review loop should be interruptible
> and resumable — track which records have been reviewed in a
> corpus/tier2_progress.json checkpoint file.

*Verification:* Review loop runs on 3 test records. Accept/edit/skip all
work. Progress checkpoint written. Resuming from checkpoint skips already-
reviewed records.

---

### Step 7 — Claude Batch API labelling pipeline

Build `pipeline/label.py` and `label.py` CLI.

**Extraction prompt** (written after Tier 2 schema validation — placeholder
in Step 6, real prompt inserted here):

The prompt must:
- Include full schema definition with field descriptions and allowed values
- Include 3 worked examples drawn from Tier 1 human-labelled records
  (Airwallex, Mistral, Databricks — chosen for variety)
- Instruct Claude to respond with valid JSON only, no preamble
- Include explicit ambiguity handling:
  - `"If seniority is ambiguous, choose the more senior option and note in raw_observations"`
  - `"If required vs nice-to-have is unclear, classify as required only if the JD uses must/essential/required language"`
  - `"If remote_policy is not stated, return 'not_stated' — never infer"`
  - `"If company_stage cannot be determined from JD content, return 'not_stated' — never infer from company name"`

**Batch API flow:**
```python
def run_batch(records: list[JDRecord]) -> str
def poll_batch(batch_id: str) -> str
def download_results(results_url: str) -> list[dict]
def merge_results(records, results) -> tuple[list[JDRecord], list[dict]]
```

**Claude Code prompt:**
> Build pipeline/label.py with the four functions defined in Step 7.
> Build label.py CLI: --input (clean JSONL), --tier (3 or 4 only).
> Append cost summary to corpus/stats.json after each run. Use the
> extraction prompt with 3 Tier 1 examples as few-shot anchors.

*Verification:* Batch submitted against 5 test records. Results merged.
Cost entry written to stats.json.

---

### Step 8 — Schema validation + stats

Build `pipeline/validate.py` and `stats.py`.

**`validate.py`:** Reads labelled JSONL, validates each record, writes:
- `validated_{timestamp}.jsonl` — passed
- `failures_{timestamp}.jsonl` — failed, with error list

**`stats.py`:** Prints corpus summary:
```
Corpus statistics — 2026-06-06
────────────────────────────────
Total records:        203
  Tier 1 (human):       6
  Tier 2 (deep review): 15
  Tier 3 (light review):50
  Tier 4 (automated):  132

By source:
  Greenhouse:          140
  Lever:                28
  Ashby:                20
  VC boards:            12
  Manual:                3

Schema validation failure rate: 1.4% (3/203)
Dedup rate: 8.2% (18 dropped from 221 collected)
Labelling cost to date: $0.34
```

**Claude Code prompt:**
> Build pipeline/validate.py and stats.py as defined in Step 8.

*Verification:* validate.py writes both output files. stats.py prints
plausible summary. Failure rate logged.

---

### Step 9 — Fine-tuning export

Build `export.py`.

**Fine-tuning format:**
```json
{"prompt": "<full JD text>", "completion": "<extraction schema JSON>"}
```

**Export modes:**
```bash
python export.py --set eval     # Tier 1+2+3 only
python export.py --set train    # all tiers
python export.py --set full     # everything
```

**Filters:** Exclude schema validation failures. Exclude wrong
schema_version. Tier 4 excluded from eval set.

**Claude Code prompt:**
> Build export.py as defined in Step 9. Three --set modes. All exclusion
> filters applied. Print export count and cost per tier.

*Verification:* eval export excludes Tier 4. Every record has `prompt`
and `completion` fields. Completion is valid JSON.

---

## 6. Corpus Seed List (initial)

**Greenhouse (verify slugs before running):**

| Company | Slug | Sector |
|---|---|---|
| Anthropic | anthropic | AI |
| Databricks | databricks | AI/Data |
| Snowflake | snowflake | Data |
| Stripe | stripe | FinTech |
| Adyen | adyen | FinTech |
| Figma | figma | Dev Tools |
| Confluent | confluent | Infrastructure |
| HashiCorp | hashicorp | Infrastructure |
| Criteo | criteo | AdTech |
| The Trade Desk | thetradedesk | AdTech |

**Lever (verify slugs before running):**

| Company | Slug | Sector |
|---|---|---|
| Hugging Face | huggingface | AI |
| Cohere | cohere | AI |
| Mistral | mistral | AI |
| Scale AI | scaleai | AI |

**Ashby (verify slugs before running):**

| Company | Slug | Sector |
|---|---|---|
| Perplexity | perplexity | AI |
| Anyscale | anyscale | AI Infrastructure |
| Modal | modal | AI Infrastructure |

> All slugs must be verified manually before the first collector run.
> A 404 means the company is not on that ATS — try alternate slugs
> before marking as not found.

---

## 7. Open Questions (parking lot)

**From Tier 1 — deferred to Tier 2:**
- `leadership_geography` field — captures geographic scope of leadership
  responsibility (EMEA, APAC, LATAM etc). Seen in Figma and Airwallex.
  Add if it appears in 3+ Tier 2 JDs.
- `technologies_are_background_credentials` flag — boolean to mark JDs
  where listed technologies are past-tense background, not active
  requirements (seen in AI Consultancy JD). Add if pattern recurs in
  Tier 2.

**Infrastructure (post-pipeline):**
- Near-duplicate detection — MinHash/SimHash for 95%-identical JDs.
  Out of scope for initial build.
- Weekly cron automation — set up after pipeline proven end-to-end.
- VC board selector maintenance policy — test monthly, mark deprecated
  if broken for >2 runs.

---

## 8. Handoff to Project 4

Project 4 (fine-tuned JD analyser) starts with:

- `corpus/finetune_export/export_train_*.jsonl` — 200 records, validated
- `corpus/finetune_export/export_eval_*.jsonl` — Tier 1–3, human-validated
- `CORPUS_FINDINGS.md` — full record set, schema change log, failure mode profile
- `corpus/stats.json` — cost baseline, dedup rate, schema failure rate
- `SCHEMA_VERSION = "1.2"` — locked

The extraction schema locked here is the prediction target for the
fine-tuned model. Project 4 cannot start until the schema is frozen and
the eval set is populated.

---

## 9. Interview Narrative

**Data engineering before model engineering.** Most people learning AI
go straight to model training. This project demonstrates understanding
of the pipeline that makes training possible — schema design, weak
supervision, eval set construction, contamination avoidance.

**Empirical schema design.** The schema was not asserted upfront. It was
discovered through practice on 6 real JDs and locked after validation.
8 changes were triggered. The Tier model and the formalisation gate are
concrete examples of engineering discipline applied to data quality.

**Cost awareness.** Batch API chosen from the start. Cost tracked per
run. Training corpus has a known cost baseline before Project 4 begins.

**Eval set discipline.** Eval set drawn from human-validated records only.
Claude extraction on Tier 1 JDs ran after human labels were saved.
Contamination risk identified and prevented by design.

**Schema as architecture.** The four-field skills split
(required_technologies / required_competencies / nice_to_have_technologies
/ nice_to_have_competencies) and the separation of extraction schema from
annotation schema are architectural decisions — not data modelling details.
The boundary between "what the JD says" and "what I think about the JD"
is enforced structurally.

---

## 10. Relationship to cv-tailor

### Current state

cv-tailor is live in production. It performs its own JD analysis in
Phase 0 using Mistral Small, producing a `JDAnalysis` object:

```python
@dataclass
class JDAnalysis:
    raw_text: str
    role_title: str
    seniority_level: str        # inferred
    key_requirements: list[str] # flat list
    nice_to_haves: list[str]    # flat list
    company_context: str
    tone_signals: list[str]
```

jd-refinery's extraction schema is richer and more structured than
cv-tailor's `JDAnalysis`. The two systems currently operate independently
and do not share state.

### The consistency requirement

The most important constraint: **cv-tailor and jd-refinery must not
produce contradictory signals on the same JD.**

If jd-refinery labels a role `fit_score: 8` and cv-tailor's Phase 1
produces `outcome: "no_fit"` on the same role, the system is broken from
a user trust perspective. This can happen because:

- cv-tailor's keyword scoring is mechanical (token presence) while
  jd-refinery's fit_score is semantic (human judgement)
- cv-tailor extracts a flat `key_requirements` list; jd-refinery
  separates technologies from competencies

Until the systems are integrated, the user (Michel) is the consistency
layer — he knows both outputs and can reconcile them manually.

### Schema alignment

The approximate mapping between the two schemas:

| jd-refinery field | cv-tailor equivalent |
|---|---|
| `role_type` | `role_title` (partial) |
| `seniority` | `seniority_level` |
| `required_technologies` + `required_competencies` | `key_requirements` (flat) |
| `nice_to_have_technologies` + `nice_to_have_competencies` | `nice_to_haves` (flat) |
| `culture_signals` | `tone_signals` (partial) |
| `domain` + `company_size_signal` + `company_stage` | `company_context` (unstructured) |

jd-refinery's schema is a strict superset of cv-tailor's `JDAnalysis`.
cv-tailor's flat lists are a lossy projection of jd-refinery's four-field
skills structure.

### No changes to cv-tailor

cv-tailor is not modified as part of this project. It is production software
with a working pipeline. Changes are deferred until a planned future
integration.

### Future integration (not in scope for this project)

Once both systems are mature and usage patterns are understood, a merge
is possible. The natural integration point:

- jd-refinery becomes the upstream source of truth for JD analysis
- cv-tailor optionally consumes jd-refinery output via a `--jd-analysis`
  flag, skipping its own Phase 0 extraction
- jd-refinery exports a cv-tailor-compatible format:
  `python export.py --format cvtailor --id {sha256_id}`

This integration is **not planned for this project.** It will be designed
when both systems are live, usage patterns are real, and the architectural
decisions can be grounded in evidence rather than speculation.

The decision to defer is deliberate: premature integration of a production
system with a pipeline still under construction creates coupling before
either system is stable. Build both independently. Merge when the time
is right.

---

## 11. Tier 2 Plan

**Status:** 10 of 15 JDs complete. 5 remaining.

**Complete (Tier 1 + Tier 2):**
Airwallex, JPMC, AI Consultancy, Figma, Mistral, Databricks, Writer,
Zendesk, Outreach, Fin/Intercom — all records in `CORPUS_FINDINGS.md §5`.

**Coverage gaps to fill in remaining 5:**
- Pure IC roles (`"ic"` seniority — none in corpus yet)
- Non-EMEA roles (tests `remote_policy` and regional signal behaviour)
- Product/GTM roles (target corpus but absent so far)
- At least 2 JDs from Greenhouse API output (not manual) to validate
  collector output format

**Deferred schema observation to resolve:**
- `deal_motion` — appears in 2 JDs (Zendesk, Outreach). Promote if
  appears in 1 more remaining Tier 2 JD.

**Schema freeze:** After Tier 2 complete. No new fields after that point.

---

## 12. Documentation Standard

This project follows the standard documentation structure defined in
`PROJECT_DOCUMENTATION_STANDARD.md`. All documents are produced by
Claude Code at the end of the build, except the retrospective and
learnings which are written post-build with Claude's help.

### Document inventory

| File | Purpose | When written | Who writes |
|---|---|---|---|
| `README.md` | Landing page — what, why, how at a glance | Post-build | Claude Code |
| `PROJECT_ARCHITECTURE.md` | How the implemented system works today | Post-build | Claude Code |
| `PROJECT_RETROSPECTIVE.md` | What happened, what changed, what was learned | Post-build | Michel + Claude |
| `PROJECT_LEARNINGS.md` | Reusable engineering lessons for future projects | Post-build | Michel + Claude |
| `SPEC_JD_REFINERY.md` | This file — original design intent | Pre-build | Done ✅ |
| `CORPUS_FINDINGS.md` | Schema, labelling rules, all JD records | Ongoing | Michel + Claude |

### Claude Code instructions — post-build documentation

When the pipeline is complete and end-to-end verified, run the following
Claude Code prompt to generate the README and architecture document:

> Read SPEC_JD_REFINERY.md, CORPUS_FINDINGS.md, and all source files in
> the jd-refinery repository. Produce two documents following
> PROJECT_DOCUMENTATION_STANDARD.md exactly:
>
> 1. README.md — landing page. Include: project summary, why I built this,
>    key features, architecture in one paragraph, architecture diagram using
>    the standard arrow format, key findings from CORPUS_FINDINGS.md,
>    lessons learned, running locally instructions, live demo (N/A for this
>    project), links to all documentation files.
>
> 2. PROJECT_ARCHITECTURE.md — describe the implemented system as it exists,
>    not as it was planned. Include: overview, design principles, high-level
>    architecture diagram, component breakdown (collect → clean → dedupe →
>    label → validate → export), user journeys for the three main workflows
>    (manual Tier 1/2 labelling, automated collection, fine-tuning export),
>    data flow diagram, technical stack, major architecture decisions with
>    rationale. Do not describe historical evolution — that belongs in the
>    retrospective.
>
> Both documents must follow the diagram standard: arrows only, no boxes,
> no Mermaid, no external diagram tools.

### Retrospective and learnings — written after build

`PROJECT_RETROSPECTIVE.md` and `PROJECT_LEARNINGS.md` are written in a
dedicated conversation after the pipeline is complete and at least one
full end-to-end run has been executed. They cannot be written by Claude
Code because they require reflection on what actually happened, not what
was planned.

Starter prompt for that conversation:
> Open SPEC_JD_REFINERY.md, CORPUS_FINDINGS.md, and PROJECT_ARCHITECTURE.md.
> Help me write PROJECT_RETROSPECTIVE.md and PROJECT_LEARNINGS.md following
> PROJECT_DOCUMENTATION_STANDARD.md. We will work through each section
> together — I will provide the content, you will structure it.
