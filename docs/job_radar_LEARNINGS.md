# job_radar_LEARNINGS.md — job-radar

> **This document captures reusable engineering and AI-system lessons.**
> **For project history, see `job_radar_RETROSPECTIVE.md`.**
> **For the implemented system, see `job_radar_ARCHITECTURE.html`.**

*Status: partially complete — cross-cutting decisions and early learnings captured.*
*Claude Code should append new learning entries as each phase completes.*
*See `SPEC_JOB_RADAR.md §13` for the post-build completion prompt.*

---

## How Claude Code should use this file

After completing each implementation step or phase, append a new learning
entry if something unexpected happened, a decision was reversed, or a pattern
emerged that would be useful on future projects. Use the template in §Learning
Entry Template. Do not rewrite existing entries — append only.

---

## Cross-Cutting Decisions

### Schema design as architecture

**Context:** The extraction schema determines what every downstream system
(scoring, fine-tuning, cv-tailor integration) can and cannot do. It is the
most load-bearing decision in the whole project — not a data modelling
detail.

**Decision:** Validate the schema empirically on real JDs before building any
automation. Lock the schema before any automated collection runs. The
formalisation gate: a field is promoted only if it appears in 3+ real
examples, is objectively extractable, and is useful downstream.

**Outcome:** 10 schema changes triggered by 10 manually-labelled JDs before
a single line of collector code was written. Changes included structural
field splits, new dimensions (delivery_motion, leadership_geography), and
boundary decisions that would have been wrong if made upfront.

**Reusability:** Any labelling pipeline. Design the schema last (after seeing
real data), not first. The formalisation gate is reusable as a general
pattern for deciding when an observation becomes a field.

---

### Three-layer schema separation

**Context:** Early design had a flat `JDRecord` with extraction fields and
annotation fields mixed together. This contaminated the training corpus —
personal judgement (fit_score, blocking_constraints) mixed with objective
extraction (role_type, seniority) is neither good training data nor a clean
product model.

**Decision:** Three dataclasses, three owners, never mixed:
- `JDRecord` — extraction only, Claude-populated, objective
- `JobPosting` — product layer, system-populated, operational
- `ApplicationRecord` — annotation only, Michel-populated, subjective

**Outcome:** Clean separation enforced structurally. Claude never touches
annotation fields. The product layer (JobPosting) can evolve independently
of the extraction layer. Fine-tuning consumes JDRecord only — no personal
judgement in the training data.

**Reusability:** Any labelling project where the labeller is also a consumer
of the data. The three-layer pattern (objective extraction / product state /
personal annotation) generalises to any domain where an AI system labels
data that a human also assesses personally.

---

### Batch API as default for offline processing

**Context:** Labelling 200+ JDs at ~2,000 tokens each at synchronous pricing
is approximately double the cost of batch processing for identical output.

**Decision:** Claude Batch API exclusively for all labelling runs. No
synchronous extraction calls anywhere in the pipeline.

**Outcome:** *[Complete post-build with actual cost figures from corpus/stats.json]*

**Reusability:** Any pipeline that processes a fixed corpus offline. Synchronous
API is only justified when latency matters to the user. For batch jobs it is
always wrong. Cost tracking per run is also a design decision — knowing the
cost baseline before committing to fine-tuning is the input to the Phase 6
budget decision.

---

### Project scope reframe: corpus builder → job search intelligence system

**Context:** The original Project 3.5 (jd-refinery) was scoped as a standalone
corpus builder — a data engineering project whose output was a fine-tuning
corpus. Useful as a portfolio piece, not useful as a daily tool.

**Decision:** Reframed as Job Radar (Project 4) — a personal job search
intelligence system with six phases. The corpus builder becomes Phase 1.
Fine-tuning becomes Phase 6 (deferred). The product that's actually useful
is the scoring + tracking + UI layers built on top of the corpus.

**Outcome:** Same Phase 1 build, materially different product vision. The
architecture decisions (three-layer schema, CLI writes/UI reads, rule-based
scoring before fine-tuning) only make sense in the context of a multi-phase
product, not a one-shot corpus builder.

**Reusability:** A common pattern in AI projects — the "corpus" or "dataset"
framing undersells the product. The data pipeline is infrastructure for
something useful, not the product itself. Identifying what the data enables
is more valuable than optimising the pipeline in isolation.

---

### CLI writes; UI reads

**Context:** Phase 5 introduces a web UI. The temptation is to make the UI
bidirectional — update application status, add notes, trigger collection.

**Decision:** All writes go through CLI scripts. The UI reads a pre-built
index file (`corpus/index.json`) generated by `stats.py --export-index`.
The UI never writes to JSONL directly.

**Outcome:** *[Complete post-build]*

**Reusability:** For any system where a CLI is the primary interface and a UI
is added for visibility — keep the CLI as the single source of truth. A UI
that participates in the same persistence contract as the CLI (reads the same
files, writes through the same pipeline) is maintainable. A UI with its own
write path creates two sources of truth immediately.

---

### Collector adapters: each ATS is a URL plus a field mapping

**Context:** Three ATS sources (Greenhouse, Lever, Ashby) expose different
public JSON endpoints but feed the same `JDRecord` model. Three standalone
HTTP clients would triplicate retry/backoff, error handling, and record
construction.

**Decision:** A shared `collectors/base.py` owns the cross-cutting plumbing —
`fetch_json` (404 → skip, 429 → exponential backoff) and `build_raw_record`
(Tier-4 record, every extraction/annotation field `None`). Each collector is
then just an endpoint URL and a per-field mapping. Collection is kept separate
from both extraction (labelling, later) and hashing (dedupe, later): collected
records carry `id: "sha256:pending"` and no extracted fields.

**Outcome:** The Greenhouse collector is ~40 lines. Lever and Ashby (Step 4)
should be field-mapping only. `collect.py` routes by a one-line registry entry
per ATS, so adding a source is additive, not a rewrite.

**Reusability:** Any multi-source ingestion. Centralise transport and
record-shape concerns; keep per-source code to the part that actually differs
(URL + response shape). Splitting collect / extract / hash into distinct stages
keeps each independently testable and re-runnable.

---

## Learning Entries

### Learning Entry Template

#### Learning
What happened during the build.

#### Surprise
What was unexpected about it.

#### Reusable Pattern
How this applies to future projects.

---

### Learning 1 — Schema discovery through practice

#### Learning

The original seed schema had 9 fields. After 10 manually-labelled JDs,
the schema had grown to 17 extraction fields on JDRecord, plus 9 annotation
fields on ApplicationRecord (Phase 2+), plus 8 fields on JobPosting. Every
change was triggered by a real JD, not by upfront reasoning.

#### Surprise

The changes weren't refinements — several were structural. `required_skills`
splitting into four fields, `delivery_motion` emerging as a first-class
dimension orthogonal to `role_type`, and `application_decision` replacing
`applied: bool` were not foreseeable from the spec. The annotation schema
ended up as rich as the extraction schema — the original spec treated it
as an afterthought.

#### Reusable Pattern

Label 5–10 real examples by hand before designing any extraction schema.
The schema that emerges from practice is always better than the schema
designed upfront. This is not preliminary work — it is the most valuable
work in a labelling pipeline. Budget time for it explicitly.

---

### Learning 2 — Annotation fields reveal what you actually care about

#### Learning

Fields like `location_workable`, `domain_distance`, `blocking_constraints`,
`application_decision`, and `priority_score` were not in the original spec.
They emerged from asking: what do I need to know to make an application
decision? The answer was not "what does the JD say" but "how does this JD
relate to my constraints and goals."

#### Surprise

The annotation schema (personal judgement) ended up being as structurally
important as the extraction schema (objective facts). A corpus designed only
around what Claude can extract misses the downstream use case entirely.

#### Reusable Pattern

Before designing a labelling schema, ask: what decisions will this corpus
support? Work backwards from the decision to the fields needed. For any
corpus where a human is both labeller and end-user, the annotation schema
is load-bearing — not a post-processing concern.

---

### Learning 3 — The scope reframe happened after the build started

#### Learning

Steps 0–2 were complete (42 tests passing) when the project was reframed
from jd-refinery (corpus builder) to job-radar (job search intelligence
system). The reframe did not require any code changes — only documentation
and architecture updates.

#### Surprise

The Phase 1 build was completely correct for both framings. The corpus
engine is the same regardless of whether it feeds a fine-tuning project or
a scoring + tracking product. The reframe changed the destination, not the
foundation.

#### Reusable Pattern

Build the data layer first, even when the product vision is unclear. A clean
data pipeline with a well-designed schema is reusable across product framings.
The investment in schema design (Learning 1) paid off twice — once for the
corpus builder framing and again when the product was reframed around the
same data.

---

### Learning 4 — Assign corpus ids through the real pipeline, not a parallel hash

#### Learning

The Step 2 SHA-256 backfill (`scripts/backfill_manual_hashes.py`) assigns each
manual record's id by running the production `dedupe(records, set())` rather
than computing hashes inline. The `dropped == 0` return value doubles as the
"no two records share a hash" verification.

#### Surprise

The obvious approach — loop and `record_hash(normalise(text))` by hand — works,
but silently risks drifting from what the live pipeline produces (e.g. if
`_content_hash` later changes which fields it normalises). Reusing the real
function made the backfill self-verifying for free.

#### Reusable Pattern

When backfilling or migrating data, drive it through the same code the live
system uses, never a re-implementation. A parallel hand-rolled version is a
second source of truth that rots. Bonus: the pipeline's own invariants (here,
collision detection) become your verification step.

---

### Learning 5 — Upstream JSON can be HTML-entity-escaped

#### Learning

Greenhouse's `?content=true` returns each JD's HTML entity-escaped
(`&lt;p&gt;…`). Stored verbatim, BeautifulSoup treats it as literal text, so
`clean()` strips not a single tag. The collector runs `html.unescape()` before
storing `raw_html`.

#### Surprise

The bug is invisible at the collection boundary — the fetch "works", the JSONL
looks fine, and only the cleaned/deduped text downstream reveals the tags
survived. Encoding assumptions fail one stage after where they're made.

#### Reusable Pattern

Verify the *cleaned* output of any new source, not just that the fetch
succeeded. Normalise upstream encoding (unescape, decode) at the ingest
boundary so every downstream stage sees canonical content.

---

### Learning 6 — Hash on real content, never placeholders

#### Learning

At Step 2 all 10 manual records held `raw_text: "stored separately"` (the real
text lived in `JD_SOURCE_TEXTS.md`). Hashing then would have collapsed 9
records into a single duplicate. The backfill was deliberately deferred until
the real text was in place, and folded into Step 3.

#### Surprise

A content-addressed id scheme is only as good as the content it sees. A shared
placeholder doesn't merely produce wrong ids — it makes distinct records look
identical and get dropped as duplicates.

#### Reusable Pattern

Never run content hashing / dedup against placeholder or stub content. Gate the
id-assignment step on real data being present, and treat "all ids identical" as
a loud failure, not a quiet one.

---

### Learning 7 — The executable model is the schema source of truth

#### Learning

Step 1 spec prose said `SCHEMA_VERSION = "1.1"` while CORPUS_FINDINGS §1.1 and
`models/record.py` both said `1.2`. The build followed the code and findings
(1.2).

#### Surprise

Two "sources of truth" disagreed, and the human-written step text was the wrong
one. The dataclass — the artifact tests actually run against — was right.

#### Reusable Pattern

When spec prose and executable schema diverge, trust the executable artifact and
fix the prose. Name one source as canonical up front (here: `models/record.py`
in sync with CORPUS_FINDINGS §1.1) so the tie-break is decided before it bites.

---

### Learning 8 — Renaming a project directory orphans the tooling, not the code

#### Learning

Renaming `jd-refinery` → `job-radar` keyed Claude Code's per-project memory to
the old path (it does not follow the move), and a botched save left the root
convention file as `CLAUDE.md.md` — so the documented "read CLAUDE.md" had
nothing to read until it was restored. Zero source files changed.

#### Surprise

A rename is a docs/tooling event masquerading as a no-op: the code compiles and
tests pass throughout, yet the memory link and the most load-bearing context
file silently broke.

#### Reusable Pattern

Treat a project rename as a checklist of non-code steps — copy the tool's memory
dir to the new path key, fix the root context filename, update git remotes and
the compose service name. The code is the easy part; the surrounding scaffolding
is what breaks.

---

### Learning 9 — The base abstraction paid off: new ATS = response shape only

#### Learning

Adding Lever and Ashby (Step 4) on top of `collectors/base.py` came to a URL
template, a per-job field mapping, and a one-line registry entry each — no new
retry, backoff, error-handling, or record-construction code. The three sources
disagree on envelope shape: Greenhouse and Ashby return `{"jobs": [...]}`, Lever
returns a bare JSON array; Lever further splits a JD across `description` +
`lists` + `additional`, so the collector reassembles them into one `raw_html`.

#### Surprise

How *differently* three "public JSON job APIs" model the same thing. The
abstraction held only because it drew the line in the right place — transport
and record shape shared, response parsing per-source — rather than trying to
unify the responses themselves.

#### Reusable Pattern

Validate a base abstraction by adding the second and third implementation, not
by admiring the first. The right seam is the one where adding source N+1 touches
only the part that genuinely differs. If a new source forces edits to the shared
layer, the seam was in the wrong place.

---

*[Claude Code: append new entries here as each step and phase completes.
Do not rewrite existing entries. Use the template above.]*
