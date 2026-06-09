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

**Outcome:** Live verified: 5 records labelled at $0.055 total with prompt
caching active (9,712 cache-read tokens vs 7,045 fresh input — the schema
+ examples preamble was paid once across the batch). Full corpus of 200 JDs
at this rate ≈ $2.20 — well within budget for Phase 1 labelling.

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

**Outcome:** Phase 1 complete with CLI as the only write path. The UI
(Phase 5) will consume `corpus/index.json` generated by
`stats.py --export-index` — a flat denormalised array written by the CLI
after each pipeline run. The UI contract is defined in Phase 1; the UI
itself is built in Phase 5.

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

### Structural fit before requirement matching

**Context:** Most job recommendation systems optimise for keyword overlap.
This fails for non-linear career paths like Michel's — semiconductor
background, solutions consulting leadership, AI projects — where the
strongest opportunities are defined by patterns of experience rather than
shared keywords.

**Decision:** The Phase 2 scorer evaluates in three stages: (1) Structural
Fit — role, seniority, delivery_motion, technical_depth, domain alignment.
Produces `fit_score`. (2) Blocking Constraint Assessment — hard requirements
that prevent success regardless of fit. Produces `requirement_gaps` and
`blocking_constraints`. (3) Opportunity Classification — plain-English
`fit_label`: strong_fit, good_fit, stretch, blocked_fit, interview_practice,
income_bridge. Search mode (`selective` / `active` / `broad`) in
`candidate_profile.yaml` controls how fit labels are filtered — not the
scorer itself.

**Outcome:** *[Defined pre-Phase 2 — evaluate after Phase 2 complete]*

**Reusability:** For any recommendation system serving a non-linear career
profile: score structural pattern alignment first, surface blocking
constraints second, present interpretations rather than raw numbers.
Dynamic filtering by urgency mode is reusable for any personal tool
where the user's constraints change over time.

---

### Output model Option A — a new record type beats migrating the old one

**Context:** Phase 2 needed somewhere to put scoring output (fit_score, fit_label,
priority, gaps). Phase 1 had parked annotation fields *inside* `JDRecord` as a
temporary home. Two paths: migrate those fields out of `JDRecord` into a new
record now, or add the new record and leave `JDRecord` alone.

**Decision (Option A, locked by Michel 2026-06-09):** Add an `ApplicationRecord`
dataclass as the scorer's *only* output. Do **not** migrate `JDRecord`'s legacy
annotation fields (they become dead stubs the scorer never reads or writes). Do
not introduce `JobPosting` yet. Bump the project `SCHEMA_VERSION` to `1.3` for the
new record type, but keep `JDRecord`'s on-disk envelope frozen at `1.2` via a
separate `JDRECORD_SCHEMA_VERSION` constant — the existing corpus is not rewritten
(CLAUDE.md: append-only, never migrate in place).

**Outcome:** The 10 v1.2 JD records keep loading, validating, and round-tripping
unchanged; all 95 Phase-1 tests stayed green through the version bump (only the
three call sites that hard-coded `SCHEMA_VERSION` for a *JDRecord* envelope —
`factories`, `test_record`, `stats.export_index` — were repointed at
`JDRECORD_SCHEMA_VERSION`). `ApplicationRecord` is a flat, single-owner record
(no extraction/annotation envelope) written to `corpus/scored/`. Two schema
versions now coexist in the same module, keyed by record type.

**Reusability:** When a new consumer needs new fields, prefer a new record type
over migrating a record that other stages already depend on. Version *per record
type*, not globally — a single project-wide version constant forces a migration
every time any one record evolves. The cost is two constants and a one-line
repoint of every site that conflated "the project version" with "this record's
version"; the benefit is zero data migration and an untouched, still-valid corpus.

---

### Scoring: profile says WHAT, scorer says HOW; mode is presentation not scoring

**Context:** The candidate profile is a managed asset Michel edits; the scorer is
code. Where does each rule live? Two specific tensions: (1) requirement-gap
detection — the profile lists gaps to watch for, but detecting them in a JD needs
regex; (2) `search_mode` — it changes what the user sees, but the scoring must
stay stable so scores are comparable over time.

**Decision:** Split ownership by what changes and who changes it. The profile's
`requirement_gap_watchlist` declares WHAT to watch (Michel's vocabulary); the
scorer's `_GAP_TRIGGERS` defines HOW to detect each phrase (regex, keyed by the
exact phrase). Generic blocking rules (clearance/language/sponsorship) are
entirely scorer-owned — they are not personal, so they are not in the profile.
And `search_mode`/`--min-fit` are pure presentation: they live in `score.py`'s
`is_shown` filter (§6.3 table), never in `scorer.py`. The scored file always holds
every record; filtering only changes the printed/served view.

**Outcome:** Running the scorer on the 10 manual records produced a plausible,
honest spread (8 strong_fit, 2 good_fit — the corpus is curated relevant roles),
with requirement_gaps firing where expected (data-science, contact-centre,
Salesforce/RevOps) and no language false-positives. `scorer.py` is pure and
deterministic (`scored_at` injected), so the same inputs always reproduce the same
ApplicationRecord — re-scoring is safe and diff-able.

**Reusability:** For any rule-based system driven partly by a user-edited config:
put declarative intent in the config and detection/mechanism in code, keyed so a
config change can't silently break detection. Keep the scoring function pure and
inject the clock; make filtering a view over a complete artifact, not a deletion
from it — so the durable output stays stable while presentation flexes.

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

### Learning 10 — VC board scraping is not viable with BeautifulSoup

#### Learning

All major VC portfolio job boards (Balderton via Consider, Atomico via Getro,
Index Ventures via Vue + Elasticsearch) use JavaScript-rendered frontends. The
HTML source contains zero job listings — only JS framework scaffolding.
BeautifulSoup gets nothing useful. One board (Index Ventures) exposed
Elasticsearch credentials in the page source but the account had no search
permissions.

#### Surprise

The assumption that VC boards would be simpler than ATS platforms was wrong.
They are more complex — custom-branded React/Vue SPAs built on platforms like
Consider and Getro, with no public API. The era of static HTML VC job boards is
over.

#### Reusable Pattern

Before speccing a scraping source, verify the HTML source directly (Ctrl+U) to
confirm job listings are present without JavaScript. A loading spinner in the
raw HTML is an immediate disqualifier for BeautifulSoup. For JS-rendered
sources, the options are: Playwright (adds complexity and maintenance), a paid
aggregator API (Apify, TheirStack), or deferral. For a Phase 1 build, deferral
is almost always correct — don't let a hard scraping problem block a working
pipeline.

---

### Learning 11 — Make interactive CLIs testable by injecting IO and side effects

#### Learning

`tier2_review.py` is an interactive accept/edit/skip loop, normally driven by a
human at a TTY. The review loop takes `input_fn`, `output_fn` and `extract` as
parameters (defaulting to `input`, `print`, and the placeholder extractor). The
test suite drives the whole flow — including field-by-field edit mode and
checkpoint/resume — with a scripted input iterator and a no-op output, no TTY
or mocking of builtins required.

#### Surprise

The same seam that makes the loop testable (injecting `extract`) is exactly the
seam Step 7 needs to swap the placeholder for the real Claude Batch extractor.
The testability boundary and the extension boundary turned out to be the same
line.

#### Reusable Pattern

For any interactive or side-effecting CLI, pass IO (`input`/`print`) and the
external dependency (here, extraction) as injectable parameters with sensible
defaults. Tests supply scripted fakes; production uses the defaults. A scripted
input iterator that raises `StopIteration` if over-consumed also asserts "no
unexpected prompt" for free — e.g. the resume test proves already-reviewed
records are never re-prompted.

---

### Learning 12 — Whole-record validation collides with the layered-ownership boundary

#### Learning

After Claude (Batch API) labelled the extraction fields of a Tier-4 record, every
record still failed `validate()` — not on a single extraction field, but on the
*annotation* fields (`applied`, `application_decision`, `location_workable`, …)
being `None`. Collectors leave annotation `None`, and Claude correctly never
writes annotation (the strict extraction/annotation boundary). So a
freshly-labelled record is extraction-complete yet whole-record-invalid. Fix: the
*pipeline* (`merge_results`) seeds neutral annotation defaults
(`applied=False`, `application_decision="pending"`, …) — placeholders, not
judgements — so the record is schema-valid and ready for a human to annotate.

#### Surprise

The three-layer separation (objective extraction / system product / human
annotation) is enforced at *write* time — each owner writes only its layer — but
`validate()` checks the *whole* record at once. The two views disagree: a record
can be "done" for its current owner yet invalid as a whole. Nobody owns "fill the
not-yet-relevant layers with neutral defaults" until you notice the gap.

#### Reusable Pattern

When data has layered ownership but a single all-fields validator, decide
explicitly who seeds the not-yet-owned layers and when. Seed neutral
machine-defaults at the transition point (here: on label-merge), keeping them
distinct from real values so a later owner can tell "untouched default" from
"deliberately set." Don't let a validator that spans all layers imply that one
layer's writer is responsible for all of them.

---

### Learning 13 — Generate the model prompt from the executable schema, not a copy

#### Learning

`pipeline/label.py` builds the extraction system prompt's closed-vocabulary
section directly from the `models.record` enums (`SENIORITY`, `DOMAIN`, …) rather
than hand-listing the allowed values. Add a value to the schema and the prompt
updates itself. Two batch-API mechanics also bit: `custom_id` must match
`^[a-zA-Z0-9_-]{1,64}$`, so the `sha256:…` record id (illegal `:`, 71 chars) can't
be used — requests are keyed by index and mapped back by position; and marking
the shared system prompt with `cache_control` made prompt caching real (the live
run billed 9,712 cache-read tokens against 7,045 fresh input — the schema+examples
preamble was paid for once across the 5 requests).

#### Surprise

The prompt is the *third* copy of the schema (after `models/record.py` and
CORPUS_FINDINGS §1.1) and the one most likely to silently rot — a model happily
emits an enum value the code then rejects. Deriving it from the code removes the
copy entirely. And batch caching "just worked" only because the volatile per-JD
text was in the user turn, behind the cached system prefix — the standard
caching prefix rule, but easy to break by templating the JD into the system block.

#### Reusable Pattern

Anything you tell a model about a schema should be generated from the schema's
executable definition, not transcribed. For batch jobs, put the large shared
context in a cache-marked system prefix and the per-item payload in the user turn
so caching pays off; and check ID-format constraints (`custom_id` charset/length)
before keying requests on a domain identifier.

---

### Learning 14 — One flat dataclass, two serialisation shapes, paid off twice

#### Learning

Step 1 modelled `JDRecord` as a *flat* dataclass but serialised it to a *nested*
JSONL envelope (`extraction` / `annotation` groups) via a hand-written `to_dict`.
Step 8's UI index needed the opposite shape — a fully denormalised flat row per
record — and got it for free: `dataclasses.asdict(record)` returns the flat field
map directly, so `export_index` is a one-liner. The same model serves the
storage format (nested, ownership-grouped) and the UI contract (flat,
query-friendly) without a second model or a mapping layer.

#### Surprise

The "extra" complexity added back in Step 1 — keeping the dataclass flat while
translating to a nested envelope — looked like overhead at the time. It turned
out to be exactly the seam that made two later, opposite serialisation needs
trivial. The flat in-memory shape is the pivot both formats project from.

#### Reusable Pattern

Keep the in-memory model in its most neutral (usually flattest) shape and treat
every serialisation — storage envelope, API payload, UI index — as a projection
from it. Resist baking one wire format into the model. When a new consumer wants
a different shape, it's a new projection, not a migration.

---

### Learning 15 — Keep the eval set out of the labels it is meant to judge

#### Learning

The fine-tuning export's `eval` set is Tier 1+2+3 only — Tier 4 is excluded. Tier
4 is Claude's *automated, unreviewed* extraction; the model fine-tuned on the
corpus learns from exactly those automated labels. Evaluating that model on Tier
4 would grade its output against labels of the same provenance — a mirror, not a
test. The eval set is restricted to human-reviewed tiers so it stays an
independent yardstick.

#### Surprise

The split that matters for trustworthy evaluation isn't train/test by *record*,
it's by *label provenance*. Two records can be identical in shape yet belong on
opposite sides of the line purely because of who/what produced their labels.

#### Reusable Pattern

When the thing you're evaluating also produced (or is trained on) some of your
labels, partition the eval set by label provenance, not just by a random split.
Hold back only labels created independently of the model under test.

**Resolved — train vs full distinction (job_radar_SPEC.md §5.3 Step 9):**
`eval` = Tier 1+2+3 human-reviewed, held-out, never for training.
`train` = all tiers validated, the actual fine-tuning input.
`full` = everything including failures, inspection only, never for training.
`train` ≈ `full` currently because Tier 4 records are few and failure rate
is low — the separation exists by design for when scale makes it matter.

---

*[Claude Code: append new entries here as each step and phase completes.
Do not rewrite existing entries. Use the template above.]*
