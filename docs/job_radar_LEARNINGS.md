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

### A cheap structured screen beats paying a model to read noise

**Context:** Phase 3's first real collection pulled **2,507** global postings from
10 ATS boards. Labelling all of them via the Batch API (~$0.016/record) is ~$40 to
extract mostly off-target US engineering roles. The raw records also had no
structured `title`/`location` — collectors had discarded the ATS fields.

**Decision:** Capture the discarded ATS `title` + location into a **metadata
sidecar** (`meta_{date}.jsonl`, keyed by `source_url`) rather than overloading the
schema-locked `JDRecord` or injecting a synthetic header into `raw_text` (which
stays employer text only). Then a pure, code-only **pre-label filter** screens on
that metadata (location: UK / remote-EU / ambiguous keep, clear non-UK drop; role:
target families keep, pure-sales / recruiting / off-target drop) *before* any
labelling spend. The screen is deliberately generous — recall over precision.

**Outcome:** 2,507 → 116 exact dupes → 2,391 unique → **66 survivors (3%)** — a
~38× cut, dropping the labelling bill from ~$40 to ~$1. The biggest lessons came
from *inspecting* the survivors and drops, not from the headline count: three
recall bugs hid behind plausible totals — `Applied AI Architect` (Anthropic's
densest on-target cluster) was dropped because the keep-list lacked the phrase;
`Solutions Architecture` / `Field Engineering` were dropped by a `\barchitect\b` /
`\bfield engineer\b` word-boundary bug (the `-ure`/`-ing` suffix); and **US-state
remote** roles ("Remote - California") survived as "ambiguous" because the non-UK
matcher knew "US" but not state names. Each was a generosity failure invisible in
aggregate and obvious in a sampled list.

**Reusability:** Before spending model tokens on a corpus, screen it with cheap
deterministic code on whatever structured signal you can recover — and capture
that signal in a sidecar rather than bending a locked schema. When tuning a
keep/drop screen, **always sample the surviving and dropped sets**; counts confirm
volume but only inspection reveals false negatives. Word-boundary regexes silently
miss morphological variants (`architect`/`architecture`); enumerate suffixes.

---

### Exact-hash dedupe is not enough for multi-location job boards

**Context:** After the screen cut the corpus to 66 survivors, inspecting them
(prompted by Michel asking "are some of these duplicates?") showed ~14 were the
*same role* posted many times: Databricks "AI Engineer – FDE" across 5 EU
countries, Stripe "Customer Success Manager" in 4 language variants
(—/French/German/Spanish), Databricks "Delivery Solutions Architect" ×3. The
content-hash dedupe (`pipeline.dedupe`, SHA-256 of cleaned body) can't catch these
— each posting's body genuinely differs (location string, language requirement),
so the hashes differ.

**Decision:** Add a semantic **near-dedupe** *after* screening
(`collapse_near_duplicates`): group survivors by `(company, language-stripped
title)` and keep one best-located representative (UK first). The key strips
*language* qualifiers ("(French speaking)") but **not** specialisation
parentheticals ("(Enterprise Accounts)" vs "(Utilities/Energy)") — so genuinely
distinct roles that happen to share a base title are preserved. 66 → 62 distinct.

**Outcome:** The same inspection round also caught a *recall* miss hiding among the
borderline roles: "Deployment Strategist" (which Databricks literally describes as
"PM for the field" on its forward-deployed team, and Mistral ships as "AI
Deployment Strategist – UK") had no keep-list entry and was being dropped as
off-target. Pulling 2-3 real JD bodies for each borderline role into a throwaway
md — rather than deciding from the title alone — is what surfaced it. Both fixes
landed in one pass; 62 distinct survivors, recall good on the target families.

**Reusability:** Dedup has two layers — *byte-identical* (cheap hash) and
*semantically same* (same role, different location/language/variant). Job boards
produce the second constantly; budget for a domain-keyed collapse on top of the
hash. When a screen has borderline keep/drop calls, **judge from the artifact, not
the label** — read the actual content of a sample, because a title ("Deployment
Strategist") rarely tells you whether it's on-target.

---

### First production scoring run — the capability blocker earns its keep; Known Limit F bites

**Context:** First real labelling + scoring run (Phase 3, 2026-06-09). To avoid a
Databricks-skewed first review (23 of 62 survivors, mostly deep-technical), Michel
specified a representative subset: all non-Databricks survivors + 5 Databricks
across role buckets + max 2 Customer Success Managers. 44 records, labelled via
Batch API at **$0.7672** (0 failures), then validated and scored.

Two pipeline gaps had to be closed first: collected survivors have `raw_text=""`
(only `raw_html`), and the scorer derives the job title from the first line of
`raw_text` — but `clean()` lowercases everything to one line. So a **`clean_readable`**
(HTML/boilerplate stripped, line breaks + case kept) populates `raw_text` for
labelling/scoring, and the sidecar title/location ride in as a separate
**`[ATS METADATA]`** block in the prompt — never merged into `raw_text`.

**Outcome — fit_label dist: strong_fit 18 · stretch 7 · blocked_fit 8 · good_fit 6
· interview_practice 5.** What the real data showed:
- **The capability blocker is the scorer's highest-value rule.** All 8 blocked_fit
  were genuinely hands-on roles Michel can't execute (Applied AI Architect, three
  Forward-Deployed Engineers, deep Databricks SA/AI-Eng, a technical CS *Engineer*).
  It cleanly split same-named roles by depth: Databricks "Deployment Strategist"
  (hybrid, "PM for the field") → strong_fit 10, while Mistral "AI Deployment
  Strategist – UK" (hands-on) → blocked_fit. This is the rule that turns a
  pre-filter survivor list into a *feasibility-aware* ranking.
- **CSM distinction works** (the reason for keeping CSMs): pure Stripe CSM →
  interview_practice (4), strategic Anthropic CSM / CS leadership → good_fit (6),
  technical Perplexity CS *Engineer* → blocked_fit. A real spread on role nature.
- **Known Limitation F (extraction over-tagging) confirmed in production.** Mistral
  "Senior Product Marketing Manager – Studio" — a *marketing* role — was extracted
  as `role_type=['Product','GTM']` and, because Product conditional-qualifies on an
  AI Platform domain and "Enterprise Software" was (over-)tagged as a strong domain,
  scored **strong_fit 10**. Nearly every record carried "Enterprise Software". This
  is an *extraction* defect, not a scorer bug — the scorer is locked; the fix is the
  deferred extraction-prompt/corpus work.
- **The "strong_fit where role isn't top contributor" probe came back empty — but
  it has a blind spot.** It flags `domain_contrib > role_contrib`; the Product
  Marketing case had role==domain (4==4, a tie), so it slipped through. A mis-tagged
  *role* (Marketing→Product) defeats a metric that assumes the role tag is honest.

**Reusability:** (1) A locked scorer is only as good as the extraction beneath it —
validate the *extraction* on real data before trusting score distributions; an
over-generous role/domain tag silently inflates downstream. (2) Feasibility gates
(can the candidate actually do the hands-on work?) discriminate far more on real
postings than fit signals do — the survivors all "look" like fits; the blocker is
what separates them. (3) A diagnostic that assumes its input labels are correct
can't catch a mislabel; pair "is the score justified?" checks with "is the *tag*
right?" spot-reads.

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

### Learning 16 — A scorer that only sees positive examples scores everything high

#### Learning

The first real run of the Phase-2 scorer (flat 5-dimension, equal-weight, summed
model from SPEC §6.5) put 8 of 10 curated JDs in `strong_fit`. The instinct was
"the labels must be wrong" — they weren't. The per-dimension breakdown showed the
cause: on a corpus of roles the candidate had hand-picked, `seniority` scored 2/2
for **all 10** records and `location` and `role` were nearly saturated too. Four
of five dimensions did no discriminating work; only `domain` varied. The fix split
dimensions into **signal** (role/domain/depth — set the scale) and **gates**
(seniority/location — penalty-only, never inflate). Separately, the Databricks JD
exposed a second gap: strong SA/AI-Platform enums but mandatory hands-on Spark/
SQL/Databricks/multi-cloud the candidate can't execute — so a **capability
blocker** was added that lets Stage 2 (requirement assessment) override a high
Stage 1 (structural) score. Threshold (≥3 unmet required techs on a hands-on role)
was set from where real examples fell: Databricks 6 unmet vs JP Morgan 2 / Mistral
1.

#### Surprise

Two surprises. First, a dimension that never varies *looks* like it's working —
it contributes points to every score — but it is pure noise dressed as signal; you
only see it by printing the per-dimension spread, not the final scores. Second,
the saturation was an artifact of the **corpus**, not the model: every example was
a role the candidate already liked, so "table stakes" dimensions were always met.
Without a negative example, there was nothing to reveal that seniority did no work
— or that structural fit and feasibility had silently been conflated.

#### Reusable Pattern

Calibrate a scorer against **negative examples**, not just positives — roles that
should score low, and structurally-attractive-but-infeasible roles. Add them to
the corpus deliberately, set thresholds from where real positives/negatives fall,
and pin the calibration with a test ("X must be blocked_fit"). Audit each
dimension's variance across the corpus, not just the output: a near-constant
dimension is inflating every score and should become a gate (penalty-only) or be
reweighted. And keep "does it fit" separate from "can they do it" — let the
feasibility check override structural fit, or you ship "everything is a strong
fit."

---

### Learning 17 — A binary role match fails a domain-conditional target

#### Learning

The candidate's targets are mostly universal (Solutions Engineering is on-target
anywhere) but one — Product — is only a strong target *in the right domain*. A
Product role in AdTech/AI is a top opportunity; a Product role in maritime
logistics is not. A flat `target_roles` lookup can't express that: include Product
and every PM scores 2.0; exclude it and the good ones score 0. The fix was a
**three-tier** role dimension — primary (2.0) / `conditional_primary` (2.0 if the
JD is in a relevant domain or pairs a strong+weak signal, else 1.0) / secondary
(1.0) / none (0) — with the conditional rule driven by the profile (domains +
signal lists) and the detection by the scorer.

#### Surprise

The first cut of the conditional domain list was too generous: it included
`Enterprise Software` and `Data & Analytics`. The maritime OneOcean PM was
(defensibly) extracted as `Enterprise Software` → it qualified as primary and got
the full boost — the exact false-positive the tier was meant to prevent. The tier
only works if its qualifying domains are *narrow and differentiating*; a catch-all
domain in the list silently re-creates the binary "every PM is primary" behaviour.

#### Reusable Pattern

When a target is conditional rather than universal, model the condition explicitly
(a separate tier with its own qualifying criteria) instead of forcing it into the
same flat list as the unconditional targets. Keep the qualifying set deliberately
narrow — and validate it against a *negative* example (a target-role JD in a wrong
domain) that must NOT qualify, or a broad qualifier will quietly defeat the tier.

---

### Learning 18 — Calibrating against negatives: every miss was a rule, not a threshold

#### Learning

Scoring a 13-JD corpus built deliberately from negatives + conditional cases
surfaced six mismatches — and **not one was fixed by moving a `fit_label`
threshold.** Each was a specific rule: (A) the language blocker tripped on "French
is *a plus*" and wrongly blocked the best positive; (B) a role mismatch (role 0)
still reached good_fit on domain+depth alone — the profile's `negative_signals`
weren't wired in; (C) an M&A Director scored good_fit because M&A was a soft gap,
not a blocker; (D) the conditional Product domain list was too broad (Learning 17);
(E) the location gate was fooled by a "London" substring when the body said
"McLean, Virginia, onsite". Fixes: optional-framing exclusion; a `negative_signal`
fit ceiling; promote M&A to a blocker when it's a *core* requirement (title or
required competency, not nice-to-have); narrow the domains; strict onsite
("clean base city only"). Spread went from 8/10-strong-ish to a genuine range.

#### Surprise

A separate, irreducible cause emerged that the scorer *can't* fix (F): the Tier-4
automated extraction is generous — it maps off-target roles onto target
`role_type`s and defaults to `Enterprise Software` as a catch-all domain. Because
`Enterprise Software` is a *strong* domain (+4), a single over-tag inflates a
clearly-wrong role (the maritime PM stayed strong_fit even after its role correctly
fell to 1.0). No scoring rule undoes a bad upstream label; that's an
extraction/corpus task, deferred.

#### Reusable Pattern

When calibrating a rule-based scorer, resist reaching for the thresholds first —
walk each miss back to the *rule* that produced it; thresholds are the last lever,
not the first. And separate "the scorer scored it wrong" from "the scorer was fed a
wrong label": conflating the two leads to over-fitting scorer rules to paper over
extraction errors. Fix the rule where the rule is wrong; log the extraction ceiling
as a known limitation and fix it at the source.

---

### Learning 19 — The contribution view turns calibration into a one-line detector

#### Learning

After A–E, re-scoring the full 23-record corpus (10 schema-forming + 13
calibration) showed the scorer separates genuine positives from negatives cleanly,
and the **provisional thresholds held without adjustment** — set from where real
positives/negatives actually fell, not from assumption. Decomposing the 11
`strong_fit` records by *weighted contribution* (role ×2, domain ×2, depth ×1) told
the rest of the story: **role is the dominant contributor in 10 of 11** (a primary
or qualifying-conditional role match), **domain separates the tiers** (strong-domain
4 → the 10s; adjacent 2 → the 8s), and **depth is only a tiebreaker** (Mistral's
`hands_on` 0.5 made it 9 not 10). Most importantly, the *residual* errors
(OneOcean, Fin CSM still `strong_fit`) were **extraction-quality** problems, not
scorer-rule problems — generous `role_type` mapping and `Enterprise Software` as a
catch-all domain — which no threshold or rule can undo.

#### Surprise

The contribution view yielded a free diagnostic: **"a `strong_fit` where role is not
the top contributor" flags an extraction-inflated record.** OneOcean was the only
strong_fit carried by domain alone (its role had correctly fallen to the secondary
tier) — i.e. a record propped up by a generous domain tag rather than genuine role
alignment. A property of *how a score was composed* turned out to be a sharper
quality signal than the score itself.

#### Reusable Pattern

Don't just rank by the final score — inspect **what composed it**. Per-dimension
contribution makes "right answer for the wrong reason" visible and often hands you a
cheap, durable anomaly detector (here: dominant-dimension ≠ expected-dimension).
And when calibration thresholds set from evidence hold against a fresh, deliberately
adversarial corpus, that is the signal to **stop tuning the scorer** and fix the
remaining errors at their true source (extraction) — over-fitting scorer rules to
paper over upstream label noise is the failure mode to avoid.

---

### Learning 20 — First production scoring run: the capability blocker is the killer feature

#### Learning

The first real 44-record production run (39 non-Databricks + 5 Databricks + 2 CSM
variants, $0.77 Batch API) confirmed the scorer works as designed on data it has
never seen. The capability blocker split same-named roles by feasibility: Databricks
"Deployment Strategist" (hybrid, PM for the field) → strong_fit 10, Mistral "AI
Deployment Strategist–UK" (hands-on) → blocked_fit. The CSM spread was genuine: pure
Stripe CSM → interview_practice(4), strategic Anthropic CS leadership → good_fit(6),
technical Perplexity CS Engineer → blocked. The "strong_fit where role isn't the top
contributor" diagnostic confirmed as a production monitoring tool — it correctly
flagged zero false positives in the first run (the Product Marketing case had role
tied domain, not domain > role, so it didn't trip the detector — a known blind spot
to watch).

#### Surprise

The most important confirmation wasn't a new finding — it was that Known Limitation F
(Enterprise Software over-tagging, Product Marketing → Product) is now an observed
production fact, not a theoretical risk. It's real, it's producing false positives in
the feed, and it's the highest-value next fix. The scorer correctly identified it as
an extraction problem rather than a scoring problem — it stayed locked.

#### Reusable Pattern

Ship the scorer when calibration holds against real adversarial data; don't optimise
further in isolation. The first production run either confirms the calibration held
(correct — move to extraction quality) or surfaces a new rule failure (fix the rule).
In this case it confirmed. The next lever is always upstream of the scorer: better
extraction labels produce better scores without touching scoring logic.

---

### Learning 21 — Build an observation watchlist before changing the model

#### Learning

Tightening the extraction prompt (Product Marketing → GTM, no Enterprise-Software
default) deflated the over-tag and exposed a cluster of GTM / partner-enablement /
strategic-partnerships / Chief-of-Staff roles that had been propped up by the
Enterprise-Software domain inflation. With the inflation gone they collapsed —
because `GTM` is not in the profile's `target_roles`, so they score 0 on the role
dimension. The instinct is to "fix" it by adding GTM to `target_roles`. Instead
Michel chose a **watchlist**: a deterministic, no-LLM, no-scoring pass that diverts
this class out of the labelling/scoring stream into an append-only observation log
(`corpus/watchlist/`), to gather real evidence ("would Michel actually pursue
these?") before touching the profile or scorer.

#### Surprise

The watchlist's first real run flagged two false positives that title-keyword
matching alone produced: "Product Manager, **Ecosystem** Risk" (a genuine product
role caught by the `ecosystem` signal) and "Talent Acquisition (…**GTM**…)" (a
recruiting role caught by `GTM` in a skills-list parenthetical). The fix wasn't a
better keyword list — it was **composing the watchlist with the existing role
screen**: divert only when the role bucket is `gtm_partner` or `off_target`, never
a genuine `solutions`/`product`/`customer` target, and never `sales`/`recruiting`.
The classifier already knew what these roles were; the watchlist just had to ask it.

#### Reusable Pattern

When a model change exposes a systematically mis-valued class, **resist re-tuning
the model on a hunch**. Build a cheap observation mechanism that *sets the class
aside with evidence* and answer the value question ("would the user actually want
these?") from real data before changing targets or weights. And a keyword filter is
almost always sharper when it **defers to an existing classifier** for the "is this
even the right kind of thing?" question rather than trying to encode that in the
keywords themselves.

---

### Learning 22 — Fixing extraction beat tuning the scorer; the deflation exposed a masked gap

#### Learning

Known Limitation F (Learning 20) was fixed at its source: three disambiguation rules
added to the extraction prompt — Product Marketing → `GTM` (not `Product`); post-sales
/ Customer Success is not `AI Delivery`; and **no "Enterprise Software" default** (an
empty `domain: []` when nothing in the vocabulary clearly applies, since `domain` is a
list with no `not_stated` value). The 44 production + 13 calibration records were
re-labelled into **new** files (the calibration baseline kept as the locked
regression fixture) and the old vs new extractions scored through the **unchanged**
scorer, so every label delta is an extraction effect. Result: "Enterprise Software"
in `domain` fell **27→10** (prod) and **6→1** (calibration); both Product-Marketing
roles left `strong_fit`; OneOcean dropped `strong_fit`→`good_fit` as its
Enterprise-Software tag vanished (the exact Learning-19 residual, fixed); the
Customer Success *Engineer* moved off `AI Delivery`; and — critically — **no
calibration negative flipped positive** (regression integrity held).

#### Surprise

De-inflating the domain didn't just correct over-scores — it **exposed a gap the
over-tag had been masking**: a cluster of GTM / partner-enablement / Chief-of-Staff
roles collapsed `good_fit`→`interview_practice`, because they score 0 on the role
dimension (`GTM` is not a `target_role`) and had been propped up entirely by the
spurious Enterprise-Software domain. The fix didn't create the problem; it revealed
it. (That cluster became the watchlist, Learning 21 — not a scorer change.) A second
surprise: re-labelling is **non-deterministic** — one Figma "Solutions Consultant"
flipped `strong_fit`→`blocked_fit` purely because the model tagged `technical_depth`
differently this run, nothing to do with the prompt change.

#### Reusable Pattern

The cheapest, highest-leverage quality fix in an extract→score pipeline is almost
always **upstream, in the extraction prompt** — not in the scoring rules. But two
disciplines make it safe: (1) re-label into **new** files and diff old-vs-new through
the **unchanged** scorer, so you measure the extraction effect in isolation and never
overwrite a locked regression fixture; (2) expect collateral — fixing an over-tag can
**unmask latent gaps** elsewhere (here, a missing target_role) and surface
run-to-run model variance. Read the full before/after diff and triage which deltas
are the intended fix, which are newly-exposed structure, and which are just noise.

---

### Learning 23 — A pure regenerable artifact can't own mutable human state; put the state in an event log beside it

#### Context

The Job Tracker (`track.py`) had to let a human move a scored job through an
application lifecycle (status, notes, outcome, application date). But `score.py`
**regenerates every `ApplicationRecord` from scratch** on each run — the scorer is
pure and always emits `application_status="new"`, `notes=""`. SPEC §7.4 as written
said the tracker "updates `ApplicationRecord` in `corpus/scored/`" *and* "appends to
`corpus/activity_log.jsonl`" — a direct contradiction: any state written into a
scored record dies on the next collection→label→score cycle.

#### What we did

Resolved the fork *before* writing code (three options A/B/C surfaced in the plan;
chosen with the user). **Model C:** the append-only event log
`corpus/activity_log.jsonl` is the **single source of truth** for workflow state;
`track.py` only ever *appends*. A job's live state = its latest score (regenerable)
**joined** with a **projection** folded from the log by `job_id`. **Log-only**
fork: `outcome`/`application_date` are *derived* at read time, never persisted on
`ApplicationRecord` — so `SCHEMA_VERSION` and the locked scorer stay untouched.
Rejected B (carry state forward in `score.py`) precisely because it couples the
pure scorer to mutable state.

#### Reusable Pattern

When one artifact is **pure and regenerable** (a deterministic score, a derived
view, a rebuilt index) it must not also be the **system of record for mutable human
input** — the regeneration will silently wipe the input. The clean separation is an
**append-only event log keyed by a stable id**, projected into live state on read.
You get re-computation safety, a free audit trail (when did it go
`applied→interviewing`?), and every convention honoured (append-only, CLI-writes-
UI-reads, no in-place mutation) for the cost of a fold-on-read. Two corollaries that
proved their worth here: (1) **derive, don't persist** anything the log already
implies (`application_date` = date of the earliest `applied` event — storing it
would just be another field to keep in sync); (2) the **join key carries a caveat
worth stating out loud** — `job_id` is the JD content hash, so a JD text edit yields
a new id and the workflow legitimately does *not* carry to the new revision. Naming
that as accepted behaviour up front stops it being filed as a bug later. Acceptance
test mattered: the join only proved itself when run against the **real 44-record
corpus** (titles from the sidecar, scores from `corpus/scored/`, state from the
log) — fixtures alone wouldn't have caught a wrong join path.

---

### Learning 24 — A spare-capacity event log absorbs the next feature for free; and a content-hash join makes collection-method variants distinct on purpose

#### Context

Two things surfaced the day after `track.py` shipped, both downstream of scoring
the original 10 hand-authored records and joining them into the tracker.

1. **No title to show.** The schema-locked `JDRecord` (v1.2) has no `title` field —
   that signal lives in the metadata sidecar, keyed by `source_url`. But the legacy
   manual records carry `source_url="unknown"`, so the sidecar both *misses* them
   and would *collide* eight-to-one if it tried to key them. The tracker fell back
   to the first line of `raw_text`, which for hand-pasted JD bodies is prose
   ("About Airwallex", "Job Responsibilities"), not a title.
2. **The same real job, twice.** Several of the 10 (Figma, Mistral, Databricks)
   are the *same roles* already present in the 44-record collected set. They did
   **not** dedupe — a hand-authored body and an ATS-collected body hash to different
   `job_id`s. Worse, they scored differently: the Mistral "AI Deployment Strategist –
   UK" was `strong_fit` hand-labelled but `blocked_fit` auto-labelled (the capability
   blocker fired on the generous Tier-4 extraction, Known Limit F, not the human one).

#### What we did

For (1): added a **`title` event** to the *existing* append-only activity log rather
than a new store. The projection already folded events per `job_id`; one more event
kind and a `title_override` field gave a CLI-set, UI-readable display title, with
resolution **override → sidecar → raw_text first line → job_id**. Zero new
machinery — the model-C log (Learning 23) had spare capacity. For (2): treated the
duplication as a **curation** decision, not a code problem — removed the manual
Mistral from the (regenerable) validated+scored set, keeping the collected record as
canonical. The hand-authored fixtures stay in `corpus/manual/` untouched.

#### Reusable Pattern

**An append-only-event-log-projected-on-read design has spare capacity: the next
per-entity, mutable, latest-wins attribute is a new `event` kind plus one projected
field — not a new table.** Title override here, but the same hole fits a priority
pin, a snooze-until date, a "hidden" flag. Resist spinning up a parallel store each
time; you already have the mechanism, the validator, and the audit trail. Watch one
boundary: keep *presentation* overrides clearly non-scoring (the `title` event never
touches the scorer) so the log can carry human annotation without leaking into the
pure pipeline. Second, **a content-hash join key is a deliberate identity choice
with consequences worth stating**: it makes the *same real-world job* a *different
record* when its text differs (collected vs hand-authored vs a later revision). That
is correct for provenance and for not silently merging a generous auto-extraction
with a careful human one — but it means cross-source dedup is a **curation** step you
own, not something identity gives you for free. The score gap between the two Mistral
copies was itself the most useful artifact: a free, head-to-head measurement of
extraction quality (Known Limit F) that only existed *because* the join kept them
apart.

---

### Learning 25 — Verify the API before implementing the param; then move the filter to where the cost actually is

#### Context

The task specified incremental collection by "passing the `updated_after` query
parameter" to Greenhouse, and "check whether Lever/Ashby support a date filter."
The intuitive read is: add a server-side filter param per source. Checking the
**authoritative** API docs (not memory, not the task's assumption) changed the
shape of the whole feature:

- **Greenhouse**'s `updated_after` exists — but only on the **Harvest API**
  (authenticated). The public **Job Board** API `/jobs` endpoint takes only
  `content`. It *does* return a per-job `updated_at`, though.
- **Ashby**'s board API has no date param either, but each job carries
  `publishedAt` (and **no** `updatedAt` — so first-publish only).
- **Lever**'s v0 postings feed has no date param **and no timestamp field at
  all** — incremental is simply impossible.

#### What we did

Implemented incremental **client-side**: fetch the (single, cheap) full list and
keep only jobs at/after a per-source cursor, filtering on whatever timestamp the
source actually exposes (`updated_at` / `publishedAt` / none). Capability is a
flag on each collector (`SUPPORTS_INCREMENTAL`), and `collect.py` derives the
incremental-source set from those flags rather than hard-coding it. Lever stays
full and leans on the existing dedupe. The key reframing: the **expensive** part
of "collection" was never the HTTP GET (one free request per company) — it is the
**downstream Batch labelling spend**. A client-side filter cuts the records that
enter that paid pipeline to ≈O(new), achieving the actual goal even though the
GET is unchanged.

#### Reusable Pattern

**Verify the endpoint's real capabilities before designing around a parameter —
the same param name often lives on a *different* (privileged) API tier than the
one you're using** (`updated_after` is Harvest, not Job Board; this exact
board-vs-admin split recurs across ATS/SaaS vendors). And when the server won't
filter, ask *where the cost actually is* before concluding you can't optimize:
here the bulk fetch was free and the spend was one stage downstream, so a
client-side filter delivered the entire benefit. Two design rules that fell out
and generalize: (1) **make the capability a per-source flag and derive behaviour
from it** — heterogeneous backends (one filters, one half-filters, one can't) stay
honest when the orchestrator reads a declared flag instead of special-casing names;
(2) **on an incremental boundary, fail toward over-collection** — a missing or
unparseable timestamp must *keep* the item, because over-collecting is recovered
for free by dedupe while under-collecting is silent data loss. The cursor stores
the run's **start**, not finish, for the same reason: re-collecting a few mid-run
updates is cheap; missing them is not.

---

### Learning 26 — Moving a script into a package changes how it must be run (`-m`), not just where it lives

#### Context

The 10 pipeline-stage CLIs sat in the repo root and were run as `python score.py`.
They import repo-root packages (`from scoring.scorer import score`,
`from models.record import …`). Moving them into a `cli/` package looked purely
cosmetic — but `python cli/score.py` then **fails to import** those packages.

#### What we did

Ran them as modules instead: `python -m cli.score`. The full suite (292) stayed
green; the only code change was test imports (`import score` → `import cli.score`).

#### Reusable Pattern

`python path/to/script.py` puts **the script's own directory** on `sys.path[0]`,
not the directory you launched from — so a script that imports sibling top-level
packages works in the repo root but breaks the moment it moves into a subdir.
`python -m pkg.script`, run from the repo root, puts the **repo root** on the path
(and keeps CWD there, so relative data paths like `corpus/…` still resolve). So
"organize the scripts into a folder" is really two changes: the move *and* the
invocation switch to `-m` (plus an `__init__.py` to make the folder a package).
Worth catching before it bites in a cron wrapper or a teammate's muscle memory —
and it pairs cleanly with any existing `python -m scripts.X` convention, so adopt
the same form rather than inventing a `sys.path` hack.

---

### Learning 27 — The digest is a *view*, not a new pipeline stage; reuse the tracker's join and let the cursor solve the "what's new" question

#### Context

Phase 4's digest had to answer "what should I look at this morning?" The obvious
instinct is a new pipeline stage that recomputes something. But everything the
digest needs already exists: the latest score per `job_id` (`load_scores`), the JD
+ sidecar join, and the workflow projection from the activity log — all built for
`track.py list`. The digest is the same join with a different lens (a time window,
a fit floor, and a "skip what I've already engaged with" filter).

#### What we did

`cli/digest.py` imports `cli.track`'s loaders, `project`, `_title_for`, `_truncate`
and `sort_rows` rather than re-deriving them, then adds only what's genuinely new:
a `since` window, `--min-fit`, the already-tracked exclusion, and a Markdown export.
"What's new" is a **cursor** (`corpus/.digest_last_run`) holding the *start* of the
last default run — the exact same start-not-finish trick the collect cursor uses,
for the exact same reason (a record scored mid-run is re-shown next time, never
skipped). An explicit `--since` is a one-off lookback and deliberately does **not**
advance the cursor — mirroring collect's "a `--company` subset doesn't advance."

#### Surprise

"New since last run" keys on `scored_at`, and the scorer restamps **every** record
on a full re-score — so a manual `python -m cli.score` over the whole validated set
would legitimately resurface the entire corpus in the next digest. This isn't a bug
to fix in the digest; it's why incremental collection matters end-to-end: the weekly
cron only labels+scores the *incremental* set, so in normal operation only genuinely
new postings get a fresh `scored_at` and the digest stays bounded. The `--min-fit`
floor and already-tracked filter are the backstops for the manual-re-score case.

#### Reusable Pattern

When a "new" feature is really a new *presentation* of existing state, resist adding
a stage. Find the read path that already assembles the state (here, the tracker's
join), import its pure pieces, and add only the projection-specific bits. And when a
tool needs "what changed since last time," a single start-timestamp cursor file —
advanced only on the unfiltered default run — is usually the whole answer; you don't
need per-record "seen" bookkeeping.

---

### Learning 28 — The UI's data contract was wrong on paper; the read model is the tracker's join, and "single file" forced the stats inside it

#### Context

Phase 5's UI reads one pre-built file, `corpus/index.json`, generated by
`cli.stats --export-index`. SPEC §9.4 described that file as "a flat denormalised
array of all validated records" — i.e. JDRecords. But the browse table the same
section asks for needs `fit_label`, `fit_score`, `priority_score`,
`fit_label_reason`, `requirement_gaps`, and **live `application_status`** — none of
which live on a JDRecord. `fit_score`/`blocking_constraints` *exist* on JDRecord as
Phase-1 annotation fields, but those are legacy stubs the scorer never writes
(CLAUDE.md schema summary). So the documented contract could not produce the
documented UI. The real read model had been built twice already — `track.py list`
and `cli.digest` both join latest `ApplicationRecord` ⨝ `JDRecord` ⨝ sidecar ⨝
activity-log projection.

#### What we did

Rebuilt `export_index` to emit that **same join** (importing `cli.track`'s loaders +
`project` + `_title_for` + `derive_location_workable`), one denormalised row per
**scored** job — the spine is the score, not the JDRecord, because only scored roles
have anything to show. The output is now an **object**, not an array:
`{schema_version, jdrecord_schema_version, generated_at, stats, records}`. The
`stats` block (counts, `fit_score_distribution`, `cost_to_date_usd`) is *embedded*
because the Docker UI service mounts only `index.json` — it has no access to
`stats.json` or the corpus, so a "single self-contained file" literally cannot
reach a second file for the cost-to-date number. The UI is three static files
(`ui/index.html` + `app.js` + `style.css`), vanilla JS, no framework/build/CDN,
strictly read-only.

#### Surprises

1. **The Docker bind-mount fought the `:ro` flag.** Mounting `./corpus/index.json`
   onto `…/html/data/index.json` requires Docker to create the nested `data/`
   mountpoint *inside* the `ui` mount. With `ui` mounted `:ro`, that mkdir fails
   ("read-only file system"). Fix: leave the `ui` mount writable (the prompt's spec
   never asked for `:ro` on it) and put `:ro` only on the data file. The read-only
   guarantee the UI actually needs is behavioural (the JS never writes), not a mount
   flag on the code directory.
2. **Verifying a static UI is cheap if you reach for the browser already on the
   box.** No Playwright was installed, but headless Edge (`--screenshot`) rendered
   browse + pipeline, and a ~40-line CDP script (Node 22's global `WebSocket`) drove
   a real row-click to confirm the detail drawer — no new dependency, and it caught
   that the render actually executes against live data rather than just parsing.

#### Reusable Pattern

Before building a producer for a documented data contract, check the contract
against the *consumer's* field list — if the consumer needs fields the contract's
source record doesn't carry, the contract is the bug, not the consumer. And when the
same read model has already been assembled elsewhere (here, the tracker's join),
the new producer should import those pure pieces, not re-derive them — the SPEC prose
is the thing to fix, per the tie-break rule.

---

### Learning 29 — A second write path is safe when it reuses the first one's validator-and-append, not just its file

#### Context

Phase 6 adds a FastAPI layer so the browser can do what `python -m cli.track` does:
append workflow events to `corpus/activity_log.jsonl`. The temptation with an HTTP
layer is to re-implement the write — parse JSON, build a dict, open the file, append.
That would make the API a *second* definition of "what a valid event is," free to
drift from the CLI's. The locked invariant is "CLI writes, UI reads," now bent to
"CLI **and** API write, both through one validator."

#### What we did

The write routers import `cli.track`'s `build_event` (which runs
`validate_activity_event`) and `append_event` and call nothing else of their own —
the API contributes the HTTP shell (Pydantic request model, gating, 404/422 mapping)
and **zero** write logic. Annotations, a genuinely new sink (`annotations.jsonl`),
got the same treatment: a new `validate_annotation_event` in `models/record.py`
(constants + validator only, no `SCHEMA_VERSION` bump — same pattern as `OUTCOME`),
reused by the router. The scorer/labeller/pipeline are never imported. Result: the
M1 checkpoint proved a `POST /api/status` is indistinguishable from a CLI write —
`python -m cli.track list` reflected the API's event with no special-casing.

#### Surprises

1. **The spec contradicted itself on the cookie library** — §10.8 step 8 listed
   `itsdangerous`, but step 2 said "copy cv-tailor's `api/security.py`," which is
   zero-dep stdlib `hmac`+`hashlib`. Copying the proven module won; `itsdangerous`
   never entered `requirements.txt`. When a spec names both "copy the working thing"
   and "add this dependency," the working thing is the real instruction.
2. **A file-serve read model goes stale the instant the first write lands.**
   `index.json` is pre-built by `cli.stats --export-index`; workflow events land in
   `activity_log.jsonl` *after* that export. Serving the file verbatim would show the
   pre-write status until the next manual re-export. Fix: `GET /api/index` re-projects
   the live activity log over the file on every read (`load_events` → `project`,
   cheap) — the same projection the tracker and the exporter already use. The read
   model is the file **plus** the log, not the file alone.
3. **No new Docker image was needed.** The existing `job-radar` image already
   `pip install`s `requirements.txt`; adding fastapi/uvicorn there meant the `api`
   service is just `uvicorn api.main:app` over the same image — the spec's separate
   `Dockerfile.api` was avoidable complexity.

#### Reusable Pattern

When you add a second interface (HTTP) over logic that already has one (CLI), make
the new interface import the existing validate-and-append seam and own only the
transport concerns. The test that proves it: a write through the new path must be
readable, unmodified, through the old path's reader. And any pre-built read cache
served over HTTP needs its mutable overlay re-applied per request, or it lies right
after the first write.

---

### Learning 30 — Porting a sibling's frontend is mostly free; the costs are an image-name collision and a controlled-input quirk

#### Context

Phase 6 M2 replaced the Phase 5 vanilla-JS `ui/` with a React/TS/Vite/Tailwind SPA,
adapting cv-tailor's proven `frontend/` (UnlockProvider, `lib/api`, vite/nginx/Docker
config, shadcn-style `ui/` primitives). The browse/pipeline/detail/filter logic already
existed as `ui/app.js`; the job was to port it to React components and add the owner-only
write controls (status/notes/title + flag-scoring-issue) that M1's endpoints enable.

#### What we did

Ported the visual design wholesale — the badge/pill/grid/drawer CSS classes moved verbatim
from `ui/style.css` into `index.css`, and the React components emit the same class names, so
the look is identical and only the state management changed. `lib/jobs.ts` carries the
filter/sort/ordering logic from `app.js`. The write path reuses M1: `DetailPanel`'s controls
call `lib/api` methods that hit the same validated endpoints the CLI's logic backs — no
write/validation logic on the client. Controls render only when `write_configured`; the
first click calls `requestUnlock()` (resolves once the cookie lands). `useIndex().refetch()`
after each write re-pulls the live-overlaid index, so the drawer reflects the new state.

#### Surprises

1. **A manual `docker build -t job-radar-frontend` silently shadowed the compose build.**
   Compose names a service's built image `<project>-<service>` = `job-radar-frontend` — the
   exact tag used for a one-off `Dockerfile.prod` compile-check. So `docker compose up` found
   that image present and **reused the nginx prod image instead of building `Dockerfile.dev`**;
   the container ran nginx on :80 while compose mapped :3000, and the frontend was simply
   unreachable (HTTP 000) with no error. Fix: `up --build` to force the dev build. Lesson:
   don't hand-tag throwaway images with a name compose will compute.
2. **The unlock flow's queued action completing after unlock is a feature, not a bug.**
   Clicking a status button while locked opens the dialog *and* the `requestUnlock()` promise
   stays pending; when the key submits, the promise resolves `true` and the original write
   runs. The verification saw two events (the queued Review, then a deliberate Apply) — exactly
   the intended "click → unlock → the thing you clicked happens" UX, but worth knowing when
   reading the activity log after a test.
3. **Browser verification needed no new dependency.** Headless Edge `--screenshot` rendered
   the React SPA (it waits for JS), and a ~60-line CDP driver over Node 22's global `WebSocket`
   drove a real row-click, unlock-dialog fill, and status write — reusing the Phase 5 pattern
   (Learning 28). Controlled inputs need the native-setter + `dispatchEvent('input')` trick to
   register with React, not a bare `.value =`.

#### Reusable Pattern

When a sibling repo already solved the same shell (auth cookie, API client, dev/prod Docker,
component primitives), copy it verbatim and change only the domain nouns — the port is cheap
and the proven config avoids a class of config bugs. Keep the *new* surface minimal: the
write controls added zero client-side validation, deferring entirely to the endpoints that
already validate. And verify the running app, not just the build — the image-collision bug
compiled and "came up" green; only a real HTTP fetch through the browser exposed it.

---

### Learning 31 — A vocab + a CLI flag aren't a feature until something surfaces them; derive the fiddly enum from context

#### Context

Using the new UI, the owner hit a wall: a role applied to could not be marked *rejected*
from the browser. The data model already had the `OUTCOME` enum (rejected_pre_screen …
offer_accepted), `project()` already folded `outcome` events, the live `/api/index` overlay
already carried `outcome` and `application_date`, and the CLI already had `--outcome`. Every
layer supported it except the one the human actually touches — there was no `POST /api/outcome`
and no control in the detail panel. The capability existed on paper and on the command line,
but not as a feature.

#### What we did

Added the missing seam: `POST /api/outcome {job_id, outcome, notes?}` (gated, `build_event`
validates against `OUTCOME`) and an Outcome control that appears once a role has been applied.
Two refinements made it usable rather than just present: (1) the **rejection stage is
auto-derived from the current workflow status** (`applied→post_screen`, `interviewing→interview`,
`offer→final`) so the user doesn't hunt through a seven-value enum to say the obvious thing —
the default is editable for the exceptions; (2) recording an outcome also POSTs `/api/status`
to move the lane, because the granular outcome and the workflow lane are orthogonal under
model C but a human thinks "I was rejected" as one action. Application age + a "stale past 21
days" flag were surfaced from the already-derived `application_date` (no new storage).

#### Surprises

1. **The whole stack was ready; only the doorknob was missing.** No schema bump, no scorer
   touch, no projection change, no overlay change — just one endpoint + one panel + three
   tests. The earlier model-C design (Learning 23) had already made outcomes first-class in
   the log; the cost of "add rejection tracking" was therefore tiny, which is the payoff of
   having put workflow state in an append-only event log rather than on the record.
2. **Auto-deriving the enum from status is what made it feel finished.** The first instinct is
   to drop the raw `OUTCOME` dropdown in and call it done. But "the stage of rejection
   automatically captured" was the actual request — the user shouldn't have to translate
   "where am I" into "which rejected_* constant." Mapping current status → likely stage,
   defaulted-but-editable, is the difference between exposing a field and modelling the task.

#### Reusable Pattern

When a capability "already exists" but a user can't reach it, the missing piece is usually the
human-facing seam, and it's cheap to add precisely because everything beneath it is built.
And when that seam involves a closed enum the user must choose from, derive the default from
the context you already have (here, workflow status) so the common case is one click — expose
the full enum only as the override.

---

### Learning 32 — When two fields can disagree, pick the stronger one and derive the rest; don't make the user reconcile them

#### Context

Model C keeps the workflow **status** lane and the granular **outcome** as separate log
events (Learning 23) — deliberately, so the pure scorer can't wipe either. But that
separation surfaced a UX bug: a role marked rejected via the CLI's `--outcome` (which logs
an outcome event but doesn't move the status lane) still showed as **"applied"** in the
dashboard. The two fields disagreed, and the UI was naively trusting the weaker one.

#### What we did

Added a read-time `effectiveStatus(job)` that derives the displayed status from the outcome
when one is present (`rejected_* → rejected`, `withdrew`/`offer_declined → archived`,
`offer_accepted → offer`), falling back to the logged lane otherwise — the outcome is the
stronger signal of where a role actually is. Routed every status read (Browse pill, Pipeline
lane, Status filter + counts, default-hide of terminal lanes, the detail header + the
"current" button highlight, and `isStaleApplied`) through it. The append-only log is
untouched; this is pure projection, consistent with deriving outcome/application_date at read
time. Separately, made `rejected` a first-class quick-status button (the ladder was only 4 of
7 states) and hid terminal lanes from the default view (tick to reveal) so dead roles stop
cluttering the active dashboard.

#### Surprises

1. **The fix for "rejected shows as applied" wasn't to write more data — it was to read it
   right.** The instinct is to backfill a status event so the lane matches. But the data
   isn't wrong, it's *incomplete*, and a derivation makes every present-and-future case
   correct without a migration — including outcomes logged by the CLI, which never goes
   through the UI's status-coupling. Backfilling would have fixed one row; deriving fixes the
   rule.
2. **"Hidden by default, tick to show" fell out of one filter rule.** Treating an empty
   status selection as "all except terminal" and a non-empty selection as "exactly these"
   gives default-hide *and* reveal-on-tick with no extra toggle — the status checkboxes the
   user already had became the show/hide control.

#### Reusable Pattern

When two stored fields model the same thing at different granularities and can fall out of
sync, don't force the user (or a migration) to reconcile them — designate the stronger signal
and derive the presentation from it at read time, applied uniformly everywhere that field is
shown. And prefer overloading an existing control (here, the status filter's empty-vs-selected
states) to adding a new toggle when the semantics line up.

---

### Phase 6 §10.9 — Caddy-fronted prod deploy (mirroring cv-tailor)

**Context:** Prepare job-radar for `job-radar.michel-portfolio.co.uk` behind the
shared Caddy + Cloudflare home-server stack, reusing the cv-tailor pattern (nginx
frontend = single entry point, FastAPI api internal-only). No live infra touched —
repo overlay + a server runbook only.

#### Decisions

1. **Reused the existing `Dockerfile.prod` + `nginx.conf` as-is, plus a new
   `docker-compose.prod.yml` overlay** — no app restructure. The overlay sets
   `container_name`s, `ports: !override []`, joins the frontend to the external
   `caddy` network, drops `--reload`, and `restart: unless-stopped`. Validated with
   `docker compose ... config` (no host ports survive; frontend on `caddy`+`default`)
   and `... build api frontend` (the prod bundle compiles).
2. **The `/api` nginx upstream had to change from the bare `api` alias to the
   `job-radar-api` container_name** (PLAYBOOK gotcha #6). `api` is an extremely
   common service name; on the shared `caddy` network two apps with an `api` alias
   would give Docker DNS multiple A records and flaky cross-app bleed. Container
   names stay globally unique. The base dev path is unaffected (dev uses the Vite
   server, not nginx).

#### Surprises

1. **The served surface spends zero API budget — the exposure model is the
   *opposite* of cv-tailor's.** cv-tailor's risk is per-run spend; job-radar's api
   makes no model calls at all. The real risk is that public `GET /api/index` leaks
   the entire personal pipeline incl. private notes. So the cost section became an
   *exposure* section: Cloudflare Access (email-gate), not a spend cap.
2. **`index.json` is the only derived artefact, and it's cheap to rebuild — but the
   `scored/` records are load-bearing for *writes*, not just the index.** A write
   404s unless the `job_id` is in `corpus/scored/`. So seeding can't just ship
   `index.json`; the scored records must travel too. The clean split: scp the
   source-of-truth JSONL (scored/validated/meta/activity_log/annotations/stats),
   regenerate `index.json` on the server via the pure-join `cli.stats --export-index`
   (no Batch spend).

#### Reusable Pattern

When adding an app to a shared reverse-proxy network, the overlay is mechanical
(container_names + `!override []` ports + external net + no-reload + restart), but
**audit every intra-stack hostname for service-alias collisions** — anything a
sidecar resolves by bare service name (`api`, `frontend`, `backend`) must become a
container_name once it joins the shared network. And **map the data dependencies by
*operation*, not just "what the homepage reads"**: the read path and the write path
can need different files (here, index vs scored), and only the irreplaceable/expensive
ones must be copied — the cheap joins regenerate in place.

---

### Learning 33 — Porting global CSS into a utility-class app is a silent-collision trap; the bug isn't the symptom, it's the architecture

#### Context

The Browse table's headers stopped lining up with their columns. The proximate cause took a
while to find: the `<table>` had `class="grid"`, and **Tailwind ships a `.grid` utility
(`display:grid`)**. So the table became a CSS grid container, `thead`/`tbody` became grid
items, and the header row sized itself independently of the body — headers bunched left,
body spread right. The deeper cause: M2 had copied the Phase 5 hand-written global
stylesheet (`.grid`/`.pill`/`.badge`/`.drawer`/…) wholesale into a Tailwind app. Global
class names live in one namespace shared with every Tailwind utility, and the collisions
fail *silently* — no error, just broken layout. We'd already burned several rounds on
CSS whack-a-mole from this same root.

#### What we did

Stopped patching CSS and rearchitected the styling to how the stack is meant to work:
Tailwind utility classes directly on the JSX + the shadcn `components/ui/` primitives, with
**dynamic** value→colour styling moved into JS lookup maps (`src/lib/ui.ts` — a `fit_label`
or status string returns a full Tailwind class string). Deleted the entire global semantic
stylesheet; `index.css` now holds only `@tailwind` + the design tokens + a body reset. The
Browse table uses shadcn `ui/table.tsx` (`table-fixed` + a `<colgroup>` to pin columns).
Every view (App, StatBar, Sidebar, BrowseView, PipelineView, DetailPanel) was converted.
The design and all behaviour are unchanged; 354 tests still pass (frontend-only); verified
the table's header and cell x-positions are now identical.

#### Surprises

1. **The maddening part was that an explicit `.grid thead { display: table-header-group }`
   with `!important` *didn't* fix it.** Because the table itself was `display:grid`, fixing
   the thead was meaningless — the children were already grid items. The tell was
   `getComputedStyle(table).display === "grid"`, not anything about thead. Diagnose the
   container, not the child.
2. **A class name that "describes the thing" is exactly the danger.** `.grid` for a data
   grid, `.table`, `.card`, `.hidden`, `.flex` — the most natural semantic names are all
   taken by Tailwind utilities. In a utility-class app there is no safe global namespace;
   the only safe move is to not have one.

#### Reusable Pattern

Don't mix a global semantic stylesheet with a utility-class framework — the namespaces
overlap and collisions are silent. Style with the framework's utilities on the elements,
push dynamic styling into JS maps that return class strings (collision-proof and
co-located with the logic), and keep the global stylesheet to resets + tokens only. When a
layout bug resists CSS patches, check the computed `display` of the *container* before
theorising about the children — and treat a recurring bug class as a signal to fix the
architecture, not the Nth symptom.

---

### Phase 6 §10.9 — prod `.env` contaminating the test suite (COOKIE_SECURE)

**Context:** Running the deploy smoke test on the server — `docker compose run --rm
job-radar python -m pytest -q` — failed 14 of the `tests/test_api.py` cases (all the
unlock-gated write paths: status/note/title/outcome/annotations + the live overlay), while
340 passed. The same suite is green on the dev box.

#### Surprise / root cause

The `job-radar` compose service loads `.env` via `env_file`. The deploy `.env` sets
`COOKIE_SECURE=true` (correct for prod — the browser↔proxy leg is HTTPS). But pytest inherits
that env, so the `/api/unlock` endpoint issues the `jr_write` capability cookie with the
`Secure` flag — and the FastAPI/Starlette `TestClient` talks to `http://testserver`, so (like
a browser) it **refuses to store a Secure cookie over plain http**. Every subsequent gated
write arrives cookie-less → 403. The tests that *don't* depend on a persisted cookie
(`capabilities_locked`, `unlock_wrong_key_401`) passed, which is the tell: it's a transport/
cookie issue, not a logic regression. **The deployed app is correct** — in prod the cookie
*should* be Secure and the real browser uses HTTPS.

#### Fix

An `autouse` fixture in `tests/test_api.py` that `monkeypatch.delenv("COOKIE_SECURE")`, making
the suite hermetic regardless of the ambient `.env`. Verified by forcing `COOKIE_SECURE=true`
into the container and confirming all 27 api tests still pass. Also corrected the runbook: the
pytest smoke step now overrides `-e COOKIE_SECURE=` (belt-and-braces for servers that haven't
pulled the fixture yet), and the load-bearing corpus smoke checks are `cli.stats` + `cli.track
list`, not pytest.

#### Reusable Pattern

A test that exercises a security feature must **pin the env that toggles that feature**, not
inherit it. Secure-cookie/HTTPS-only behaviour in particular is invisible until something runs
the suite in a prod-shaped environment (a server `.env`, CI secrets). Pin such flags off in an
autouse fixture so "how was pytest invoked" can never change the result — and don't make a
green test suite a *server* deployment gate when the same artifact already ran green in CI/dev.

---

### Phase 4/6 — the pipeline had no cross-corpus dedupe (re-paid to re-label seen jobs)

**Context:** First production run of the 102-company universe on the deployed server.
Collect pulled 5,498 raw → prefilter cut to 99 survivors — but ~half were jobs already
labelled/scored on the dev box, about to be sent to the paid labeller a second time.

#### Root cause

`cli.prefilter` called `dedupe(records, set())` with an **empty** `seen` set, so it only
deduped *within the current batch*. `pipeline.dedupe` is explicitly built to drop
"corpus-wide duplicates" via `seen`, and `job_id`/`id` in the scored/labelled files **is**
the same `sha256:` content hash it computes — but nothing ever seeded `seen` from the
existing corpus. The incremental **collection cursor** (the intended re-fetch guard) didn't
help here because a fresh server deploy has no cursor → full pull (and a `--full` run does
the same). And `cli/dedupe.py` turned out to be an **empty stub** ("no logic yet"), so the
cron's `dedupe` step is a no-op and prefilter's within-batch pass was the *only* dedup in
the whole running pipeline. (The cron's bare `cli.label` is also broken — it requires
`--input`/`--tier` — i.e. the documented weekly sequence was never actually runnable.)

#### Fix

`prefilter.load_processed_hashes()` reads every `labelled_*.jsonl` `id` + `scored_*.jsonl`
`job_id` into a set; `run()` takes a `seen` arg and drops matches as *already-processed*
(reusing the `.id` that the within-batch `dedupe` already assigned — no second expensive
clean/hash pass). Default-on; `--include-processed` opts out to deliberately re-label after
a JD/prompt change. +4 tests (358 total). The report now prints "already processed: N
(excluded vs M labelled/scored job_ids)".

#### Reusable Pattern

A dedup/idempotency mechanism is only as good as what you seed its "seen" set from — an
empty seed silently degrades "skip everything I've already done" into "skip dupes in this
one batch," and the gap stays invisible until volume (or a fresh environment with migrated
output but no cursor) makes the re-processing obvious. When migrating state between
environments, the *derived guards* (cursors, seen-sets) must be reconstructable from the
migrated data — here, rebuilding "already processed" from the labelled/scored hashes is
robust precisely because it doesn't depend on a gitignored cursor that never travels.

---

### Phase 4 — the "automated weekly pipeline" had never actually run

**Context:** First real end-to-end run of the discovery pipeline (102-company universe,
on the deployed server), done stage-by-stage by hand. Three of the six stages errored on
invocation, each the same way the cron would have.

#### Surprise

`cron/collect_weekly.sh` called every stage bare (`python -m cli.label`, `… cli.validate`,
`… cli.stats --export-index`), but **all three had `--input` `required=True`** (label also
`--tier`), so each bare line exits non-zero — and `cli/dedupe.py` is an empty stub, so its
cron line was a silent no-op. The weekly cron, shipped and documented since Phase 4, could
never have completed a single run. It was never exercised because the corpus was always
built by ad-hoc commands during development; the wrapper was written but never run.

#### Fix

Gave the stages bare-invocation defaults keyed to the current UTC day (matching `prefilter`'s
existing `--date` default and `label`'s UTC output stamp): `label` → today's
`filtered_<date>.jsonl` + `meta_<date>.jsonl` + `--tier 4`; `validate` → today's
`labelled_<date>T*.jsonl` (only the day's output, not a whole-corpus re-validate); `stats
--input` → `VALIDATED_GLOB`. Rewrote the cron to the by-hand-validated sequence, dropped the
stub `dedupe` line, and baked in a "don't schedule near 00:00 UTC" caveat (the date-keyed
stages would straddle two stamps). +4 tests.

#### Reusable Pattern

A wrapper script (cron job, Makefile target, CI step) that has **never been executed** is
documentation, not automation — treat it as unverified until something runs it end-to-end.
The first real run is the test. And when a recurring automated job spends money (here, the
Batch labeller), its stages must be invokable *exactly* as the scheduler calls them — bare,
non-interactive, with safe defaults — not require the args a human happened to pass while
developing. The required-`--input` guards were reasonable for a money-spending stage, but
they silently made the headless path impossible; the resolution was day-scoped defaults that
keep bare runs safe (today's data only) rather than dropping the guard entirely.

---

### Phase 6 (§10.11) — fit override + annotation visibility: the "display vs scorer" split

**Context:** Two usability gaps from daily use (SPEC §10.11). Feature 1: the scorer's
`fit_label` is sometimes wrong for the owner's situation, with no way to reflect that without
mutating locked scorer output. Feature 2: annotations appended silently — no way to see
existing flags or avoid duplicates. Both built as event-log-append + read-model-join, no
scorer/schema/pipeline change.

#### Decisions / surprises

- **An override is a workflow decision, not a correction.** It rides the *same* append-only
  activity log as status/notes (a new `fit_override` `ACTIVITY_EVENT`, value ∈ `FIT_LABEL` or
  `null` to clear), and the scored `ApplicationRecord` is never touched. So `scorer_fit_label`
  and `user_fit_label` coexist forever — the scorer value stays clean for corpus quality
  analysis / future fine-tuning, while the UI shows the owner's call. Annotation (Feature 2)
  is the *other* lane: "the system may be wrong, review later" — it changes nothing the owner
  acts on today. Keeping the two orthogonal (and saying so in the SPEC table) stopped them
  from collapsing into one muddy "feedback" concept.
- **Resolve display in the read model, keep the field names the UI already uses.** Rather
  than rename `fit_label`/`priority_score` everywhere and touch every view, `build_index_rows`
  sets `fit_label` to the *display* value (override or scorer) and adds explicit
  `scorer_*`/`user_*`/`display_*`/`has_fit_override` alongside. The whole existing UI
  (sort/filter/badge/stats) then reflects the override with zero churn, and the detail panel
  shows scorer-vs-override using the explicit fields. The live `GET /api/index` overlay
  recomputes the display from the *preserved* `scorer_fit_label`, so it's correct even on an
  index.json built before the override.
- **Two-event folding gotcha.** `project` folds any event's non-empty `notes` into the
  workflow `notes`. A `fit_override`'s `notes` is its *reason*, not a workflow note, so it had
  to be excluded from that fold (and stored as `fit_override_reason`) — otherwise saving an
  override silently overwrote the role's note. Caught only because the existing
  `test_project_latest_..._notes` pinned the behaviour; my first cut (folding the dispatch and
  the notes into one `if/elif` chain) also broke status-with-notes. The fix keeps the notes
  fold a *separate* step that skips `fit_override`.
- **Duplicate prevention is server-enforced, client-courteous.** The API is the backstop
  (`409` on exact `job_id`+`type`+`field`+`reason`); the UI's "this flag already exists,
  submit anyway?" is a pre-flight courtesy read from the embedded annotations. "Submit anyway"
  then legitimately hits the `409` — the client warning just saves a round-trip and explains
  the rejection. The same `load_annotations` projection feeds both the export embed and the
  live overlay, so a freshly submitted flag shows on reload (revising the earlier "annotations
  don't affect the read model" note now that they're part of it).

#### Reusable pattern

When a model output needs a human override but the producer is locked, **don't mutate the
output — add an override event in the existing log and resolve a `display_*` in the read
model, preserving the original `producer_*` beside it.** The UI keeps its field names; the
provenance survives for later analysis; re-running the producer can't wipe the human's call.
+19 tests (381 total); frontend `tsc -b` clean.

---

### `cli/analyse.py` — reporting is just a third reader over the same join

**Context:** Built a read-only reporting CLI (score-distribution / status / companies /
gaps) over the existing corpus. The temptation with a "reports" tool is to write fresh
queries; instead it imports the exact loaders + `project` join that `cli.track` and
`cli.digest` already use, and adds only *aggregation* on top.

#### Decisions / surprises

- **Three tools, one join.** `track` (review table), `digest` (since-cursor view), and now
  `analyse` (aggregates) are all the same `load_scores ⨝ load_jdrecords ⨝ project(load_events)`
  with a different reducer at the end. Reusing the join (not reimplementing it) means a future
  change to how workflow state is derived propagates to all three for free — the same payoff
  that made `cli.stats --export-index` reuse the tracker join (deviation 27).
- **The projection only knows *current* lane, not history.** "Shortlisted" counts roles
  *parked* at shortlisted right now, not roles that passed through it — a role currently
  `applied` is no longer counted as shortlisted. So lane-count rates (shortlist/apply) are
  rough by construction. v1 accepts this (documented in the report); a true funnel would need
  to fold the *set* of statuses each job has ever held, which the append-only log supports but
  the current `project` (latest-wins) discards. Worth knowing before anyone reads the apply
  rate as a true conversion.
- **A spec example can contradict the spec body — trust the explicit rule.** The build
  prompt's companies-report *mock-up* showed "minimum 3 scored jobs to appear", but its
  implementation notes + DoD said show all companies and suppress *rates* below 5 scored.
  Illustrative output is not a contract; the explicit instruction is. Resolved in favour of
  the DoD and recorded as deviation 38 rather than silently picking one.
- **Cost-per-job is derived, never stored.** `est. cost $X.XX ($Y.YY/job avg)` divides
  `cost_to_date` (summed from `stats.json`) by jobs *labelled* (summed over `step=="label"`
  runs), and degrades to no cost line if `stats.json` is absent — an informational figure
  must never be load-bearing.

#### Reusable pattern

A reporting/analytics tool over an existing pipeline should be a **pure reducer over the
canonical read join**, not a parallel query layer: import the same loaders, keep aggregation
in pure functions (testable without IO), and put the only IO in a thin `main()`. The
integration test then just runs every report against the live corpus and asserts non-empty,
exception-free output (skipping when the gitignored corpus is absent). +11 tests (392 total).

---

### Rejection reasons — a second use of one sink, not a second sink

**Context:** Recording *why a role wasn't pursued despite its score* ("scores strong_fit 9
but it's too salesy"). The instinct is a new endpoint/file/schema; instead it is a new
`ANNOTATION_TYPE` (`rejection_reason`) flowing through the existing `POST /api/annotations`
+ `annotations.jsonl`, with a `REJECTION_REASON` vocabulary in the structured `reason` field.

#### Decisions / surprises

- **One sink, two meanings, kept apart by `annotation_type`.** A scoring annotation says
  "the system is wrong about a field"; a rejection_reason says "the system is right but I'm
  out for this reason". They share storage and the dedup rule (`job_id`+`type`+`field`+
  `reason`) but stay distinguishable by type — so the analyse report can scope to one without
  a schema split. Adding a use case to an existing append-only log beat inventing a parallel
  one, the same way the activity log carries status/outcome/note/title/fit_override.
- **`field: null` forced a validator relaxation.** A rejection is about the *whole role*, not
  a field, so it carries `field: null` — but `validate_annotation_event` required `field` to
  be a string and `AnnotationRequest.field` was `str` (Pydantic would 422 a null before the
  handler). Relaxed both to `str | None`, keeping the "wrong *type* still fails" guard (a
  numeric field still errors). A new value in a shared structure surfaces assumptions the
  original callers never exercised.
- **Type-specific validation, by design only here.** The API validates `reason` against the
  vocab *only* for `rejection_reason`; every other annotation type keeps `reason` free text.
  Structured-where-it-matters beats forcing a closed vocab on the free-form flags.
- **A layout mock is not a data contract.** The build prompt's UI sketch showed an optional
  free-text notes field on the rejection control, but neither the annotation record nor the
  POST body has a destination for it — including the input would silently drop user text. I
  omitted it (structured `reason` is the payload) and recorded the divergence (deviation 39)
  rather than add a field that goes nowhere.

#### Reusable pattern

Before adding an endpoint/file/schema for a "new" kind of record, ask whether it is the same
*shape* as an existing append-only log with a different *meaning* — if so, add a type/enum
value and let the consumer scope by it. The cost is auditing the shared validators for
assumptions the new value breaks (here, `field` non-null). +8 tests (400 total); `tsc -b` clean.

---

### Company metadata + yield tracking (§11.1 / BACKLOG_YIELD_TRACKING) — built 2026-06-11

Added per-company v2 metadata (`domain`/`fit_hypothesis`/`action`/`notes`) and a fifth
analyse report, `--report yield`, plus a read-only `GET /api/report/yield` download and a
React sidebar button. The yield report joins company seeds ⨝ scored corpus ⨝ workflow ⨝
validated JDs ⨝ rejection annotations into per-company rows + domain/ATS rollups — all
derived at report time, no new corpus file.

- **The join is by exact company name — fixed at the data layer, not with an alias map.**
  First live run put ~22 of 53 scored jobs under domain `(unknown)`: corpus values like
  "Mistral" didn't match the seed name "Mistral AI", and Perplexity had been dropped from the
  seeds entirely. Rather than add a fuzzy/alias matcher (which would *hide* drift it should
  expose), the fix was to **align the seed `name` to the corpus string** (rename "Mistral AI"
  → "Mistral") and **reinstate the dropped seed** (Perplexity, which already had scored roles).
  The only rows left under `(unknown)` are genuine one-off manual/calibration records (JP
  Morgan Chase, AI Consultancy, Fin (Intercom), Outreach, Zendesk) that were never part of the
  monitored ATS universe — correctly *not* invented as seeds. Lesson: when a join key drifts,
  fix the key at the source of truth; don't paper over it in the consumer. (A side find: the
  v2 seed file's own header said "73 companies" but it actually held 80 — the count was never
  asserted anywhere, so it silently rotted. Now 81, with the breakdown in the header.)
- **Editorial `action` is advisory in v1 — wiring it to behaviour was explicitly resisted.**
  `pause` logs a skip notice but still collects; `investigate_ats`/`manual` only surface in
  the report. The backlog spec (§8) is emphatic: don't automate collection changes before the
  yield data is trustworthy. So the field is captured and reported, and the collection-skip is
  a named future step — evidence first, automation later.
- **`ats: manual` + `slug: null` fell out cleanly because collection already fails soft.**
  A manual watch entry hits `registry.get("manual") → None` and is logged+skipped, exactly
  like an unregistered ATS — no special case needed in `collect()`. The only real fix was
  guarding `select()`'s `c["slug"].lower()` against `None` (a `--company` filter would have
  crashed). Watch entries appear under "no live jobs" with a manual tag.
- **Two seed-file shapes, one loader.** v1.1 shipped wrapped (`companies:`); v2 ships as a
  bare list. Rather than re-indent 73 entries, `load_companies` accepts both
  (`data["companies"] if isinstance(data, dict) else data`). The generator can emit either.
- **Reused the pure functions across CLI and API, verbatim.** `GET /api/report/yield` imports
  `build_yield_report` + `format_yield` from `cli.analyse` and returns their output as a
  `text/plain` attachment — the endpoint is ~15 lines of IO. Same discipline as the rest of
  the thin API layer: the CLI and the HTTP route are two front-ends over one aggregation.
- **`cost_per_job=None` must not crash the report.** Missing/empty `stats.json` → no cost
  columns rather than a `TypeError`; every cost cell renders `—` and the header says
  `COST_PER_JOB n/a`. Cost is informational, never load-bearing (same rule as the existing
  score-distribution cost line).
- **Settings grew two fields with defaults to avoid breaking existing construction.**
  `seeds_path`/`stats_path` default to the CLI constants, so the API test fixtures that build
  `Settings(...)` positionally keep working untouched.

#### Reusable pattern

When a report needs a *new input file*, thread it through the same settings/loader plumbing
the corpus files already use and default it to the canonical constant — then the new path is
test-injectable and the API/CLI share one resolution. And when a join key is dirty (names,
here), have the report *show* the mismatch (`(unknown)` bucket) rather than fuzzy-match it —
then fix the real ones by aligning the source of truth (seed names) to the data, leaving only
the genuinely-unmonitored records visible. The visible gap is the diagnostic; the alias map is
the trap. +20 tests (412 total); full suite green; live `--report yield` produces all sections.

---

### cv-tailor integration Phase 1 (§11.3) — a fourth append-only sink, same shape — built 2026-06-11

**What was built.** A manual way to record cv-tailor run metrics against a Job Radar role:
a new append-only file `corpus/cv_tailor_links.jsonl`, an owner-gated `POST /api/cv-tailor-results`,
a public `GET /api/jobs/{job_id}`, the `cv_tailor` section on every index row, and a CV-Tailor
panel in the React detail drawer. Zero dependency on cv-tailor being reachable — nothing calls
it, nothing imports it.

#### What was learned / confirmed

- **The "constants-only sidecar sink" pattern held for a fourth time.** `activity_log.jsonl`
  (workflow), `annotations.jsonl` (scoring flags + rejection reasons), and now
  `cv_tailor_links.jsonl` are all the same recipe: a version constant + a `validate_*` vocab
  guard in `models/record.py`, **no `SCHEMA_VERSION` bump**, an append-only `.jsonl`, a
  `load_*` latest-per-`job_id` loader, and a join into the read model. The scorer and the two
  record dataclasses stay frozen. Reaching for this pattern instead of a new field is now the
  default for "record a fact about a job that the scorer doesn't produce."
- **Embed at export AND overlay live — or a fresh write looks stale.** The `cv_tailor` section
  is built into `index.json` by `cli.stats` *and* re-projected by `GET /api/index` (exactly
  like annotations, deviation 37). Skipping the live overlay would mean a just-recorded run
  doesn't show until the next re-export — the same trap the activity-log overlay was built to
  avoid. Any new per-job read-model section must be added in *both* places.
- **Per-route gating beats router-level gating when one router mixes public + owner routes.**
  `cv_tailor.py` deliberately does **not** put `Depends(require_unlocked)` on the router (as
  workflow.py/annotations.py do) because `GET /api/jobs/{job_id}` is public. The POST carries
  its own per-route dependency. Co-locating the two cv-tailor endpoints in one router is worth
  the small asymmetry — they're one feature.
- **`GET /api/jobs/{job_id}` is built now, used later.** It returns `raw_text` for the Phase 2
  "Open in cv-tailor" handoff that doesn't exist yet. It exposes nothing new (the JD text is
  already in the public detail panel), so shipping it early costs nothing and means Phase 2 is
  a pure cv-tailor build with no Job Radar change.
- **Unit conversion lives at the UI edge.** cv-tailor's metrics are 0.0–1.0 floats (its native
  rubric scale); humans read percentages. The form takes 0–100 and divides by 100 before POST;
  the API validates and stores the fraction; display multiplies back. Storing the canonical
  unit and converting only at the input/render boundary keeps the file faithful to cv-tailor.
- **Read view for everyone, write affordance for the owner — gate on `unlocked`, not
  `configured`.** The CV-Tailor panel renders its read state for all visitors; the Add/Edit
  buttons appear only when `unlocked`. A read-only-deploy fallback also renders the panel when
  writes aren't `configured` at all, so a recorded snapshot is never hidden behind missing
  write controls.

#### Reusable pattern

A new "fact about a job the scorer doesn't compute" = a new append-only sidecar sink, never a
schema change: version constant + `validate_*` + `load_*`-latest-per-job + a read-model section
embedded **at export and in the live overlay**. Gate writes per-route when the feature's router
also serves a public read. +12 tests (430 total); full suite green; `tsc -b` clean.

---

### Per-route security gating > router-level (§10.4) — refactor 2026-06-11

Moved `require_unlocked` off the APIRouter constructor and onto each individual write route
(workflow.py, annotations.py), matching the cv_tailor.py pattern (deviation 41/42). Per-route
gating is **more explicit** than router-level: the security decision is visible at the point of
definition, every new endpoint forces a conscious public-vs-owner choice, and one router can
safely mix a public GET with owner-only POSTs (the trigger — cv_tailor.py serves both). Pure
refactor, zero behaviour change: same endpoints 403 without a cookie, same GETs public — the
unchanged 430-test suite is the proof. Default for any new endpoint: owner-only unless the spec
says "public" (then comment it). No PUT/PATCH exist — the model is append-only; a proposed
mutation should be re-modelled as an append event first.

---

### cv-tailor integration Phase 2 (§11.3 / INTEGRATION_SPEC §5.1) — built 2026-06-11

The whole Job Radar side of "open in cv-tailor" was **one frontend link button** — because
Phase 1 had already shipped the two things it needs (`GET /api/jobs/{job_id}` public, and
`cv_tailor.has_output`/`run_id` on every index row). Sequencing the data model + public read
first (Phase 1) turned the handoff into a zero-backend change: a `<a target="_blank">` whose
URL/label branch on `has_output`, never lock-gated (it's a link, not a mutation — cv-tailor's
own key gate guards non-owner access). `tsc -b` clean; 430 pytest unchanged.

---

### cv-tailor schema cleanup + Phase 3 Bearer auth (§11.3 / deviation 43) — built 2026-06-12

Two pre-Phase-3 changes to `corpus/cv_tailor_links.jsonl` and its endpoint.

- **Name the fields after the UI they mirror, before automation bakes them in.** Phase 1
  shipped `cv_tailor_score`/`coverage_score`/`grounding_score` — but the cv-tailor UI actually
  shows *Fit %*, *Grounded Coverage %*, and *CV Quality X.X/10*, and `grounding_score` mapped to
  nothing. Renaming to `fit_score`/`coverage_score`/`cv_quality_score` and dropping the
  speculative field *now* (manual records only, before the callback writes thousands) is far
  cheaper than after. The lesson: a speculative field added "while we're here" is a liability
  until something real populates it — Phase 1 was the right time to delete one.
- **Two scales in one record is a real footgun — encode it in the validator, not a comment.**
  `fit_score`/`coverage_score` are 0.0–1.0; `cv_quality_score` is 0.0–10.0 (raw rubric). The
  validator enforces the *different* range per field, the UI form labels the scale ("0–10") and
  converts only fit/coverage (÷100), and the display renders `X.X/10` vs `%`. Mixing them would
  silently store 8.1 as "810%". The range lives in `validate_cv_tailor_link`, the one place every
  write path (CLI-none-here, API, cv-tailor callback) funnels through.
- **Read-time migration beat a file rewrite for an append-only log.** Old lines keep their old
  names on disk forever (append-only); `cli.stats._migrate_cv_tailor_fields` maps them on load.
  No migration stage, no rewrite, no schema bump — consistent with "append-only, never migrate in
  place." The cost is one tiny normaliser at the read boundary, paid once per load.
- **Dual-auth is an inline check, the deliberate exception to per-route `require_unlocked`.**
  `POST /api/cv-tailor-results` must accept the owner cookie (browser, Phase 1) OR a service
  Bearer token (machine, Phase 3), so it can't use the single `require_unlocked` dependency
  (deviation 42). The inline `verify_token(cookie) or has_valid_service_token(request, key)` both
  fail closed; the service key is separate from `JR_WRITE_KEY` and unset → Bearer path closed. The
  per-route convention still holds everywhere else — this one endpoint documents its exception.

440 tests; `tsc -b` clean.

---

## 2026-06-12 — Manual JD entry via UI (job_radar_SPEC §11.1, deviation 44)

- **The "Batch API only — never synchronous extraction" rule has exactly one sanctioned
  exception, and it earned it.** Manual UI ingest must score ONE pasted JD interactively, so
  batch (with its minutes-to-hours latency) is simply the wrong tool. `pipeline.label.extract_one`
  is a single synchronous `messages.create` that **reuses the batch path's prompt + parser**
  (`build_system_prompt` / `build_user_content` / `parse_extraction`), so the extraction is
  identical in shape — only the transport differs. The convention now reads "batch for bulk
  labelling; the manual-ingest endpoint is the documented single-JD exception." A blanket rule with
  a named, justified exception beats a rule quietly broken.
- **Different model, different price table — don't reuse the batch `COST_PER_MTOK`.** The batch
  path is Opus at the 50%-off batch rate; the sync path is Haiku 4.5 at *standard* rates ($1/$5 per
  1M). `SYNC_COST_PER_MTOK` is its own constant and `estimate_sync_cost` is shaped exactly like
  `estimate_cost` so the entry drops into `corpus/stats.json` and `load_cost_to_date` sums it with
  no special-casing. Picking the model/pricing from the live `claude-api` reference (not memory)
  kept the numbers honest.
- **Hash the *normalised* text, not the raw paste.** The build sketch said `record_hash(raw_text)`,
  but the automated pipeline hashes `normalise(clean(...))`. Using `record_hash(normalise(raw_text))`
  means a manually-entered JD and its later auto-collected twin land on the **same** `job_id` — the
  dedup actually works across entry points. A subtly-different hash would have silently created
  duplicates that only diverge by whitespace/case.
- **Synthesise a unique `source_url` when none is given.** The title/location sidecar is keyed by
  `source_url`; two manual entries with an empty URL would collide in the join and clobber each
  other's title. `source_url = body.source_url or f"manual:{job_id}"` keeps the key unique without
  inventing a new keying scheme.
- **Write next to the read glob, not to a hard-coded dir.** `_out_path` derives the output directory
  from the settings read glob and emits `{prefix}_manual_{ts}.jsonl` matching the glob's pattern, so
  the just-written file is immediately visible to `load_scores`/`load_jdrecords`/`load_meta` — and
  tests point the globs at `tmp_path` with zero corpus-path special-casing.
- **Tier vs source are orthogonal.** A manual UI entry is `source_ats="manual"` (browser entry
  point) **and** `tier=4` (Claude-extracted method) — distinct from the human-structured Tier-1/2
  records in `corpus/manual/`. The two axes answer different questions; don't collapse them.

447 tests; `tsc -b` clean.

---

## 2026-06-12 — CV-Tailor calibration report (`cli.analyse --report cv_tailor`, §11.1 + §11.3)

A sixth read-only report, comparing Job Radar's fit verdict against cv-tailor's per role.

- **Two loaders for one sink, by design.** `load_cv_tailor_links` keeps the *latest* run per
  `job_id` (the read-model contract used by the index join + overlay). The calibration report
  needs the *full* history to show multiple runs of one role, so a new
  `load_all_cv_tailor_links` returns the un-deduplicated list. Same migration
  (`_migrate_cv_tailor_fields`), same skip-no-job_id rule — just no dedup. Adding a second loader
  was cleaner than bolting an `all=True` flag onto the existing one and reasoning about two return
  *types* from one function.
- **Normalise both scales before comparing — the delta is the whole point.** JR `fit_score` is
  1–10; cv-tailor `fit_score` is 0.0–1.0. `Δ = CVT×100 − JR×10` puts both on 0–100. The report is
  only useful because that single number makes "the two systems disagree by 64 points on the Trade
  Desk role" legible at a glance. Most-aligned / most-divergent rank by `|Δ|` (robust to the rare
  positive delta), not by raw value.
- **Surface orphan runs, don't drop them.** A cv-tailor `job_id` not in the scored corpus (a run
  done before the role was collected, or for a role since pruned) is real diagnostic data. It can't
  get a Δ (no JR score) so it can't sit in the fit-sorted main table — it goes in a separate
  "(not in corpus)" block. Silently dropping it would have hidden a class of "why is this run
  here?" questions.
- **Mode breakdown counts latest-per-role, not total runs.** The "demo N runs" line groups the
  same latest-per-job rows the main table uses, so the role count in the header and the run count
  in the breakdown agree. `demo`/`full` always render (even at 0) so the demo-vs-full bias is
  always visible; any other observed mode appends after.
- **The API endpoint is the CLI report verbatim.** `GET /api/report/cv_tailor` calls the *same*
  `build_cv_tailor_report` + `format_cv_tailor` pure functions over settings-resolved paths —
  identical to how `/api/report/yield` reuses the yield functions. No reimplementation, no second
  source of truth; the browser just streams the text/plain attachment.

454 tests; `tsc -b` clean.

---

## Langfuse instrumentation (Phase B) — pipeline observability, opt-in & fail-open

- **One SDK import surface, gated by one env var.** `cli/telemetry.py` is the only module
  that touches the langfuse SDK (lazily, inside functions), and `LANGFUSE_PUBLIC_KEY` is the
  single on/off gate — unset → every recorder is a clean no-op. The suite (now 462 tests)
  runs untraced via `conftest.py` popping the key (escape hatch `JR_TRACE_TESTS=1`).
  Observability never raises into the pipeline; a failed trace logs a WARNING and continues.
- **Post-hoc spans, because the Batch API is async.** Unlike cv-tailor's real-time pipeline,
  Job Radar's extraction results arrive after the batch ends, so the two recorders
  (`record_extraction_batch` in `cli/label.py`, `record_scoring_run` in `cli/score.py`) build
  their trace tree from already-collected data, let the root span CLOSE, then `flush()` — the
  CLI exits with no periodic exporter, so flush-after-close is what makes the trace exist
  (`langfuse_LEARNINGS.md` §7/§8).
- **Pure row-builders, scorer untouched.** `build_trace_rows` rebuilds the extraction prompt
  with the same `build_user_content` the batch used; `build_scoring_rows` re-derives the
  dimension breakdown with `stage1_fit` (read-only). Both are unit-testable without the SDK —
  no business-logic, prompt, or schema change (`SCHEMA_VERSION` unchanged).
- **Trust the verified artifact over the spec sketch.** The instrumentation spec's §3 sketch
  used a different langfuse API than the cv-tailor module already proven live against the same
  v4.7.1 server. Mirrored the proven surface (`create_trace_id` / `start_as_current_observation`
  / `create_score(observation_id=…)`) and introspected the installed SDK to confirm every
  signature before wiring. See `docs/langfuse_LEARNINGS.md` §8 and SPEC §16.

462 tests; langfuse 4.7.1 surface introspected in-container; `debug-trace` verified (disabled path).

---

## Manual ingest: soft validation — a human add isn't subject to the pipeline's enum gate

- **The closed-vocabulary gate exists for the *automated* pipeline, not for deliberate human
  decisions.** `validate`'s enum checks (`role_type ∈ ROLE_TYPE`, etc.) keep the batch-labelled
  corpus clean — but when the owner pastes a role via `POST /api/manual-ingest`, hard-failing on
  `role_type: ["Customer Success"]` (not in the enum) throws away a deliberate choice. Manual
  ingest now uses `models.record.soft_validate` (same checks, advisory): the record is stored
  as-is and the findings ride back as `warnings` in the 200 body (amber in the UI), instead of a
  422. `validate` itself is unchanged — the automated path still treats a non-empty result as a
  hard failure, and `ROLE_TYPE` is **not** expanded (the enum still benefits the pipeline).
- **The fix was a call-site decision, not a new validator.** `validate` already *returned* a list
  (callers decide whether to raise); the build prompt assumed it raised. `soft_validate` is a
  thin, intentionally-named seam over it so the bypass is explicit where it happens. The scorer
  needed no guard — set-intersection role matching already scores an unknown `role_type` as 0
  without raising — and the endpoint already skipped the prefilter entirely (confirmed, not
  assumed). Lesson: read what the code does before adding a layer the prompt presumes is missing.
  See CLAUDE.md deviation 47 + SPEC §11.1. 466 tests; `tsc -b` clean.

---

## Langfuse Phase B — two bugs that only showed up live (and a doc-pointer correction)

- **`langfuse.trace.name` is what the worker ingests on.** Traces uploaded to MinIO but never
  appeared in the UI. Diffing the MinIO payloads against cv-tailor's working spans showed the
  difference: cv-tailor spans carry a `langfuse.trace.name` attribute; ours didn't. The worker
  needs it to promote a trace from MinIO into ClickHouse. Fix: wrap every root span in
  `propagate_attributes(trace_name=…)` (mirroring `tailor/telemetry.run_trace`).
  `start_as_current_observation` has no `trace_name` param — `propagate_attributes` is the only
  way. Lesson: "the SDK accepted the calls and uploaded blobs" is not "it works" — verify the
  trace reaches the store the UI reads.
- **Instrumenting the CLIs left the *manual ingest* path dark.** After the trace-name fix the
  debug probe appeared but a real manual ingest still didn't. `POST /api/manual-ingest` runs its
  own inline `extract_one` + `score` in the API process — it never calls `cli.label`/`cli.score`,
  where the recorders live, so it emitted no trace at all (the tell: no "trace created" WARNING in
  `job-radar-api` logs). Fix: a third recorder, `record_manual_ingest`, called from the endpoint
  after persistence and fully guarded. Lesson: instrument by *code path actually executed*, not by
  *conceptual stage* — two paths that both "extract and score" can share zero lines.
- **Doc-pointer correction.** The earlier Phase-B entry above points to `langfuse_LEARNINGS.md §8`
  and `SPEC §16`; both were removed during SPEC review. The current homes are
  `docs/SPEC_LANGFUSE_INSTRUMENTATION.md §3` (as-built: three trace targets + the trace-name
  requirement + flush-after-close) and CLAUDE.md deviation 46. 468 tests; `debug-trace` + a real
  manual ingest both verified live in the job-radar project. Forward work: refine *what* we trace
  from real usage (cost/latency on generations, prune low-value metadata) — not more plumbing.

---

## Small debt clearance — soft_validate split, prefilter pin, Open-role button, SSE live updates

Four independent §11.1 follow-ups, one commit each.

- **`soft_validate` now classifies, it doesn't re-implement.** Splitting structural errors
  (hard-fail) from enum gaps (advisory) was tempting to do by duplicating `validate`'s checks
  into two functions — exactly what CLAUDE.md warns against. Instead `soft_validate` runs
  `validate()` unchanged and buckets each finding by message suffix: `"not in allowed values"`
  (emitted only by `_check_enum` / `_check_subset`'s bad-value branch — a value that's the right
  type but off-vocabulary) → warning; everything else (the "must be a …"-shaped type/missing
  findings) → hard error. The checks and their wording stay in one place; `soft_validate` only
  decides what blocks. Known limit: `_check_enum` is membership-only, so a *list* handed to a
  scalar enum field would be mis-bucketed as a warning — rare model output, and the scorer
  tolerates it. See CLAUDE.md deviation 47 (revised).

- **The prefilter bypass was already real — the work was *pinning* it.** Manual ingest never
  imported `pipeline/prefilter`, so a deliberate owner add was already never screened. Rather
  than trust the comment, two regression guards now fail loudly if that regresses: a behavioural
  test (a JD the automated pipeline would drop on both role and location screens still returns
  200) and a static one (`not hasattr(manual_ingest, "prefilter")`). Cheap insurance on an
  invariant that's invisible by absence.

- **SSE live updates: in-process bus, no Redis, sync-endpoint thread hop.** The architecture
  decision worth recording. (a) **No external broker.** This is a single-process FastAPI app, so
  the event bus is just a `set` of per-connection `asyncio.Queue`s in `api/events.py`; a write
  calls `emit_index_updated()`, which fans an `index_updated` notice out to every open
  `GET /api/events` stream. Redis/pub-sub is deferred to the §11.4 PostgreSQL/multi-process step
  — and only that one module changes; the *contract* doesn't. (b) **The sync-endpoint gotcha.**
  All write endpoints are `def` (not `async def`), so Starlette runs them in a threadpool — they
  cannot touch an `asyncio.Queue` directly (`put_nowait` schedules loop callbacks and is
  thread-unsafe off-loop). Fix: capture the loop at app startup (`bind_loop` in the FastAPI
  `lifespan` handler) and have `emit_index_updated` hop onto it via
  `call_soon_threadsafe`. No loop bound / no subscribers → clean no-op, so a write is never
  coupled to the bus being live (existing tests that POST writes stayed green untouched).
  (c) **Two complementary frontend signals.** `visibilitychange` re-fetch (covers "came back from
  cv-tailor" instantly, zero backend) *and* the SSE `EventSource` (covers a tab left open,
  including the cv-tailor callback). (d) **Portability.** `GET /api/events` is a backend contract;
  the §11.5 Cursor rebuild reconnects unchanged, where the event becomes a targeted-query trigger
  rather than a full reload. See CLAUDE.md deviation 48 + SPEC §11.1.

- **The "Open role →" button** was a pure wiring change: `App.tsx` already owned the detail-panel
  selection (`setSelectedId`); threading it down as `onOpenRole` through `Sidebar` → `AddRoleModal`
  reused the exact mechanism Browse/Pipeline rows use. The only subtlety: capture `result.job_id`
  *before* `close()` (which resets `result` to null), then open the panel.

## SSE: emit on /api/note and /api/title too

- The first SSE build omitted `note`/`title` from the emit list, but both change the read model
  (notes render in the detail panel, title overrides in Browse), so a tab left open went stale on
  those writes. Added `emit_index_updated()` to both — the rule is simply "every write that changes
  the read model emits." Updated CLAUDE.md deviation 48 + api/CLAUDE.md to drop the now-false
  "not note/title" carve-out.

## Phase 6.5 Step 1 — two corrections to the spec's SQLite DDL

The migration build prompt (SPEC_DB_MIGRATION) shipped a literal DDL block. Two defects
in it surfaced the moment the idempotency + dedup requirements were tested — both fixed in
`cli/db.py` before committing Step 1, and both worth recording because they are classic
SQLite footguns:

- **`UNIQUE` with a nullable column does NOT dedupe NULL rows.** The spec wrote
  `UNIQUE (job_id, annotation_type, field, reason)` to replace the current Python dedup
  (`annotations.py`: 409 on same job_id + type + field + reason). But standard SQL — and
  SQLite — treat `NULL` as *distinct from every other NULL* in a UNIQUE constraint. A
  `rejection_reason` annotation carries `field = NULL` (deviation 39), so two identical
  rejection_reason rows would *both* insert — silently breaking the 409 the Step-4 design
  relies on. Python's check matched because `None == None` is `True`. Fix: a unique
  **expression index** over `IFNULL(field, '')` collapses NULL to `''` for the key, exactly
  reproducing the Python semantics. Lesson: when porting a Python equality dedup to a SQL
  UNIQUE, audit every nullable column in the key.

- **`INSERT OR IGNORE` only no-ops against a UNIQUE/PK constraint.** The spec's
  `schema_version (version INTEGER NOT NULL)` had no UNIQUE on `version`, so
  `INSERT OR IGNORE ... VALUES (1)` had nothing to conflict against and appended a fresh row
  on every `init_db()` — making init non-idempotent (a stated requirement). Fix: make
  `version` the PRIMARY KEY. Lesson: `OR IGNORE` is meaningless without a constraint to
  ignore *against*; if you use it for idempotency, confirm the target column is actually
  constrained.

General principle reaffirmed: a DDL block in a spec is prose, not an executable artifact —
trust the test (idempotency, dedup) over the literal schema, and fix the schema. (Same
tie-break rule the project applies to SPEC-vs-`record.py`.)

## Phase 6.5 Step 3 — dual-read is only as good as its read-path *shapes*

The migration's safety hinges on a dual-read gate: build the UI index from JSONL and
from SQLite, and refuse to advance unless they are byte-identical. Two things made that
gate trustworthy rather than theatre:

- **The SQLite loaders must return the EXACT shapes the existing consumers expect, or the
  comparison is meaningless.** The build sketch had `load_events_sqlite` return a
  `dict[job_id -> list]`, but the only consumer is `project()`, which folds a *flat* list
  of events. A grouped dict would have iterated job_id strings and silently produced empty
  state — and the dual-read would then have compared two equally-broken outputs and passed.
  Returning a flat list (drop-in for `load_events`) is what makes the equality check
  actually exercise `project()`. Lesson: when you add a parallel read path to validate
  against, match the *interface*, not just the data — a wrong shape can make a comparison
  pass for the wrong reason.
- **Round-trip the encodings, then assert the state actually landed.** `cvcm_enabled`
  (bool↔INTEGER 0/1) and `observed`/`expected` (list↔JSON TEXT) are the fields most likely
  to silently differ; the dual-read test asserts not just `compare == []` but also that the
  SQLite row carried `status="applied"`, 2 annotations, and `cvcm_enabled is True` — so a
  "both empty, trivially equal" pass can't masquerade as success.

The JSONL↔SQL mapping (`insert_*` + `_enc`/`_dec`/`_bool_to_int`) and both read paths all
live in `cli/db.py` so write (backfill/dual-write) and read can't drift apart.

## Phase 6.5 Step 4 — dual-write, and the test-isolation trap of an env-resolved DB path

Switching writes to dual-write (JSONL + SQLite) was mostly mechanical, but one thing was
non-obvious and would have silently corrupted state in the test suite:

- **An env-resolved store is invisible to the dependency-override test harness.** The API
  tests inject every *path* through a `Settings` object (`app.dependency_overrides`), so
  nothing touches the real corpus. But `cli.db.get_db()` resolves the DB from `JR_DB_PATH`,
  which `Settings` does not cover — so the first dual-write test would have written to the
  **real** `corpus/job_radar.db`, and worse, annotation-dedup tests would 409 against rows
  left by previous runs. Fix: an autouse `conftest._isolate_db` fixture points `JR_DB_PATH`
  at a per-test tmp DB for the *whole* suite. Lesson: when you add a new persistence backend
  to an app that already has a hermetic test harness, check that the new backend's path is
  resolved through the *same* injection seam — a second resolution mechanism (env var vs
  injected settings) silently escapes the harness.
- **Order the dual-write by who owns the invariant.** For annotations the 409 must come from
  the SQLite UNIQUE index, so SQLite is written FIRST — a duplicate raises before any JSONL
  append, leaving no orphan line. For the unconstrained logs (activity/cv-tailor) JSONL is
  written first (it stays the read source until Step 5, so it's the safety net). The rule:
  write the store that enforces the constraint first; write the current source-of-truth such
  that a failure in the *other* store can't lose data.
- **Self-healing schema beats ordering assumptions.** The `write_*` helpers each call
  `init_db()` (idempotent `CREATE TABLE IF NOT EXISTS`) so a fresh/absent DB — a brand-new
  test tmp path, a fresh deploy before the lifespan hook runs — never throws "no such table".
  The API also inits at lifespan startup; belt and suspenders, both cheap.

## Phase 6.5 Step 5 — an existence-based read switch is a loaded gun; and "auto" must not poison the comparison

Switching reads to SQLite via `use_sqlite() == get_db_path().exists()` is elegant (no flag,
CLI tools just work) but had two traps that shaped the implementation:

- **Existence-as-switch + lazy-create = silent state loss.** Because the read source flips
  the instant the DB file appears, anything that creates an *empty* DB before the backfill
  runs would make the overlay read an empty store and the entire UI would go blank. The
  original Step-4 plan put `init_db()` in the API lifespan — meaning a simple API restart on
  a not-yet-backfilled host would zero the displayed state. Removed it: the lifespan no longer
  touches the DB. The DB is now created only by the backfill, the first dual-write, or an
  explicit `--source sqlite/both`. Deploy ordering is documented: backfill BEFORE serving.
  Lesson: if file-existence is your cutover signal, no code path may create the file empty
  ahead of the data — make creation and population the same act, or don't create on the read path.
- **Auto-detect must not collapse the dual-read comparison.** `--source both` only means
  something if one side is provably JSONL and the other provably SQLite. So the bare
  `load_annotations` / `load_cv_tailor_links` / `load_events` stay PURE JSONL (the comparison
  baseline + `interactive_from_jsonl`), and auto-detection lives in *separate* `_auto`
  wrappers (`load_activity_events`, `load_*_auto`) that the API overlay and CLI tools call. A
  single auto-detecting `load_events` (as the migration sketch suggested) would have made both
  sides of `--source both` read SQLite — a comparison that can never fail. Two-named-functions
  (pure vs auto) is the cost of keeping the safety gate honest.
- **`load_events` is overloaded, so it can't be the auto seam.** `cli.stats` reuses
  `cli.track.load_events` as a generic JSONL line reader for *annotations* and *cv-tailor
  links* too — so making `load_events` itself auto-detect to the `activity_log` table (the
  sketch's suggestion) would have made the annotation/cv-tailor loaders read the wrong table.
  The auto seam had to be a new, activity-log-specific function.

index.json decision: **Option A** — keep it as the pre-built *pipeline* cache (scored ⨝ JD ⨝
meta); the overlay supplies interactive state live from SQLite. Dropping it (Option B) waits
for the PostgreSQL/multi-process step, if it ever happens.

## Phase 6.5 — the dual-read gate earned its keep (None vs '' on real prod data)

The first `--source both` run on the *production* corpus flagged 11 divergences: every
cv-tailor row had `notes: None` from JSONL but `notes: ''` from SQLite. Cause: my
`insert_cv_tailor_link` coerced `rec.get("notes") or ""`, turning the cv-tailor callback's
`notes: null` into an empty string. The JSONL read model (`cv_tailor_view`) preserves `None`,
so the two stores disagreed on every link.

Two lessons:
- **`x or ""` is not a null-safe default for a round-tripped column.** It collapses `None`,
  `''`, `0`, `False` all to `''`. If the source can legitimately hold `None` and the read model
  preserves it, store it as-is (`rec.get("notes")` → SQL NULL → reads back `None`). The
  SQLite column's `DEFAULT ''` only applies when the column is *omitted* from the INSERT, not
  when you pass an explicit `None` — so a faithful insert just passes the value through.
- **Test fixtures must mirror the real payload shape, not a convenient one.** Local tests used
  `notes=""`; production data uses `notes: null` (the cv-tailor machine callback). The bug was
  invisible until the gate ran against real data. The dual-read comparison is exactly the
  safety net that's supposed to catch "looked fine in tests" — and it did. Added a regression
  test with `notes=None` so the local suite now reproduces the prod shape.

Activity-log notes did NOT diverge: `build_event` always writes `notes` as a string (`notes or
""`), so the JSONL never carries `null` there — the coercion was harmless for that sink and
only wrong for cv-tailor links, which accept a nullable `notes`.

---

## Langfuse Phase C — per-role scoring decision traces (the scorer has no LLM call)

Phase B traced the batch *infrastructure* (one `scoring_run` trace per batch, a `jd_scoring`
span per JD). Phase C adds one **independent** `role_scoring_decision` trace per scored role —
the permanent "why did Job Radar say this?" record, keyed by a deterministic trace id
(`Langfuse.create_trace_id(seed=job_id)`) so cv-tailor can enrich the *same* trace later
without storing a Langfuse id. Built: `record_role_scoring_decision()` + `on_cv_tailor_result()`
in `cli/telemetry.py`; wired in `cli/score.py` (per role, after the batch trace) and
`api/routers/cv_tailor.py` (after persist, deviation 50).

The decisive finding (the build prompt asked me to investigate it): **Job Radar's scorer is
purely rule-based — there is NO LLM call at scoring time.** `stage1_fit()` and the whole of
`scoring/scorer.py` are deterministic regex + enum lookups over the *already-extracted*
JDRecord. The LLM call that produced that data ran earlier, during **extraction** (batch
`cli.label` / synchronous `extract_one`), and is already traced by `record_extraction_batch` /
`record_manual_ingest`. So the spec's `claude_stage1` "generation" had no real LLM behind it.

Decisions that fell out of that:
- **Kept the spec's stage1-generation shape, populated honestly.** The generation is preserved
  (it satisfies the §3.6 DoD and the trace structure reviewers look for) but the wiring passes
  `model="rule_based_scorer"`, zero tokens, the JD text as the prompt, and the structured
  sub-scores JSON as the response. The docstrings say plainly that scoring is deterministic, so
  the trace is not misread as "an LLM scored this". Faithful beats decorative.
- **Gate vocabulary mismatch is harmless by construction.** The Breakdown uses
  `seniority_gate ∈ {"pass","miss"}` and `location_gate ∈ {"pass","unclear","fail"}`; the spec's
  signature said `"pass"|"fail"`. The score mapping is `1.0 if == "pass" else 0.0` (seniority)
  and `pass→1.0 / unclear→0.5 / else→0.0` (location), so the raw breakdown strings pass straight
  through — `"miss"` scores 0.0 correctly. Passed the raw values (metadata shows the true gate
  outcome) rather than re-mapping.
- **Dimension scores attach raw (0–2), fit/priority normalised (÷10).** Per §3.2: `role_score`/
  `domain_score`/`depth_score` are the raw signal sub-scores (0–2), `fit_score`/`priority_score`
  are normalised 0–10→0–1 so they chart on one axis. The negative-signal ceiling means the
  trace's `fit_score` (final ApplicationRecord value) can sit below the stage-1 `composite`
  (raw signal) — that gap is itself signal, kept visible.
- **Divergence + normalisation extracted as pure helpers** (`_norm10`, `_divergence`) so the
  arithmetic is unit-tested without a live Langfuse client (the suite runs with no key). The
  recorders call the helpers; the tests assert `_divergence(9, 0.5) == 0.4`, etc.
- **`on_cv_tailor_result` skips None metrics.** The cv-tailor request fields are all optional;
  creating a NUMERIC score with `None` would raise and (inside the one try/except) abort the
  remaining scores. Guarded each on `is not None`; divergence needs both the JR fit and the
  cv-tailor fit present. Best-effort, fired AFTER persist (a tracing failure can never fail the
  callback — same rule as manual-ingest, deviation 46).

No scorer/business-logic/schema change (`SCHEMA_VERSION` unchanged); `build_role_decision_kwargs`
re-derives the breakdown read-only via `stage1_fit`. Tests: 512 pass (506 baseline + 6 new),
all with no `LANGFUSE_PUBLIC_KEY`. Live verification (debug-trace returning a trace_id, scoring
a role, confirming the trace + scores in the UI — §3.5 steps 5–7) runs on the M720q server with
the job-radar Langfuse keys; locally the probe reports `enabled: false` cleanly.

---

## Workflow status redesign — three distinct terminal states + contextual controls (2026-06-14)

**Context.** The 8-state workflow lifecycle overloaded `archived`: stale roles, conscious
"I decided not to pursue", and active withdrawals all landed in the same bucket. SPEC_WORKFLOW_UPDATE
split them. The build added one status (`will_not_apply`), redesigned the detail-panel controls to be
contextual, and tightened default visibility.

**The three-way terminal distinction is the whole point — and it's a vocabulary decision, not a
mechanism one.** `rejected` (they decided), `will_not_apply` (you decided), `archived` (time/
indifference) are semantically different events that were being conflated. The fix needed no new
machinery: append-only event log, `project()` fold, and `APPLICATION_STATUS` validation already
existed. Adding the value to the frozenset is *sufficient* for the whole backend — `POST /api/status`
validates against it, `build_event`/`validate_activity_event` accept it, SQLite stores it as text.
Lesson: when the data model is append-only events over a closed vocab, a new lifecycle state is a
one-line constant change plus the read-side ordering/visibility lists. Resist the urge to add an
endpoint.

**`effectiveStatus()` is the single read-time choke point for "where is this role really".** Two
places had to flip `withdrew`/`offer_declined` from `→ archived` to `→ will_not_apply`:
`effectiveStatus` (display) and `statusForOutcome` (the lane the outcome buttons move to). Keeping
them in lockstep matters — if they disagree, a withdrawn role shows in one lane but the button moves
it to another. Both are pure functions in `lib/jobs.ts`; the ordering lists (`STATUS_ORDER`,
`PIPELINE_ORDER`, `TERMINAL_STATUSES`) are the other read-side surfaces that all needed the new value.

**Contextual controls > a flat ladder.** The old panel showed every status button regardless of
state. Replacing it with a `STATUS_BUTTONS` map keyed by effective status (only sensible next moves)
removed a class of nonsensical transitions and let `review → applied` be a direct path. The dispatch
is a small `onButton(key)` switch: pure status keys move the lane directly; `withdraw`/`rejected`/
`accepted`/`declined`/`restore` are *actions* that compose status + outcome (+ optional annotation).

**`withdrew` is an OUTCOME, not a REJECTION_REASON — the spec's "pre-select withdrew in the reason
dropdown" can't be taken literally.** Posting `withdrew` as a `rejection_reason` annotation would
422 (the API validates that type against `REJECTION_REASON`). Resolution: `withdrew` is a sentinel
default option in the Withdraw dropdown; the withdrawal is captured structurally via
`POST /api/outcome {withdrew}`, and a `rejection_reason` annotation is posted only if the owner
picks a real reason. The literal DoD ("pre-selects withdrew, skippable") holds while nothing invalid
reaches the backend. Lesson: when a spec conflates two closed vocabularies, honour the *intent*
(capture the withdrawal + optional reason) and document the divergence (BUILD NOTE in the spec).

**No JS test toolchain means TS-only logic is verified by `tsc -b` + manual, not unit tests.** The
build prompt listed `test_effective_status_*` cases, but those assert a frontend TS function and the
project deliberately has no JS test runner (frontend/CLAUDE.md). Adding vitest just for two
assertions would be a larger architectural change than the feature. The backend constant/endpoint/
transition behaviour *is* covered by pytest (517 tests); the frontend derivation is covered by a
clean type-check and browser verification. Recorded as a BUILD NOTE so the gap is explicit, not
silent.

---

## Active-application company filter (2026-06-16, deviation 52)

- **A purely client-side filter beats new state when the data is already in the index.**
  "Hide companies I'm already in play with" needs no field, endpoint, or schema change —
  `application_status`/`application_date`/`company` are all in the live index overlay, so
  `getActiveCompanies()` + a clause in `applyFilters()` is the whole feature. The only
  persistent change is one `REJECTION_REASON` constant (`applied_elsewhere_same_company`),
  validated by the existing rejection_reason path with zero backend code. Reach for a derived
  client filter before a new write path when the inputs already exist.
- **Derive the active-company set from the *unfiltered* records, or siblings leak through.**
  `applyFilters` computes `getActiveCompanies(records)` from its full input, not the running
  filtered view — otherwise a status/fit filter could drop the *applied* role from the set and
  un-hide its siblings. The active role is also explicitly exempted from the hide clause so the
  application you're tracking is never filtered out of its own pipeline lane.
- **14-day window with no config knob.** The window (response gap + first-interview lead time)
  is a hard constant in v1; an `interviewing` event keeps a company active because its
  `application_date` advances. Configurable window deferred to settings — the constant is the
  right default and avoids a settings round-trip for a filter that's already opt-out-able.
- **No JS test toolchain (again): TS filter logic verified by `tsc -b` + browser, vocab by
  pytest.** Same posture as deviation 51(f) — the spec's `getActiveCompanies`/`applyFilters`
  unit cases would need vitest the project deliberately doesn't have; the one backend-testable
  case (`applied_elsewhere_same_company` accepted by `POST /api/annotations`) ships as pytest.
  Recorded as a BUILD NOTE in the spec so the gap is explicit.

---

## cv-tailor integration Phase 4 Step 1 — extraction + assessment on the read endpoint (2026-06-17)

- **A "retired" design can come back scoped.** INTEGRATION_SPEC §7 retired "share Job Radar's
  extraction with cv-tailor" because the two extractions serve different purposes (structural
  fit vs keyword coverage). Step 1 revives only the *read-only exposure* — `GET /api/jobs/{job_id}`
  now returns `extraction` + `assessment` — without coupling the pipelines. The retirement was of
  *pipeline coupling*, not of *making the data available*; surfacing it as optional context
  cv-tailor may consume costs nothing and keeps both extractions independent.
- **Read API paths use the auto-detecting loaders, never raw SQLite — even when a build prompt
  says otherwise.** The prompt sketched `get_db().execute("SELECT … FROM activity_log")`. That
  would (a) violate the Phase 6.5 dual-source contract (empty on a fresh host with no DB yet —
  deviation 49) and (b) raise "no such table" in tests, where the per-test DB has no tables until
  a write runs. Reusing `load_activity_events`+`project` and `load_annotations_auto` (the same
  source the `/api/index` overlay reads) gives SQLite-when-present, JSONL-fallback, and
  test-hermetic behaviour for free. When a prompt's data-access sketch contradicts an established
  read convention, the convention wins — the prompt describes intent, not the integration.
- **Note text is in the event's `notes` field, not `value`.** `note` events are built
  `value=None, notes=text`; the prompt's `text: r["value"]` would have returned null. Verified
  against `workflow.py`'s `add_note` and `project()`'s note fold before writing the join — cheaper
  than debugging an all-null `notes` array after the fact.
- **`assessment` is always present, `extraction` can be null.** The endpoint already 404s an
  unscored role, so the ApplicationRecord (the assessment source) always exists by the time we
  build the body; only the JDRecord (extraction) can be absent (a partial manual ingest), so only
  `extraction` needs a null path. Matching the null-handling to what can actually be missing
  avoided a redundant assessment-null branch the prompt's generic guidance implied.

---

## cv-tailor Phase 4 Step 1 — verified live end-to-end in production (2026-06-19)

- **Deployed (API-only) + confirmed working between the two live apps.** The Step 1 change
  (`extraction` + `assessment` on `GET /api/jobs/{job_id}`) is backend-only, so the prod
  update was the fast `api`-only path (`docker compose … up -d --build api` — no React
  bundle recompile, since the frontend was unchanged). cv-tailor, fetching the endpoint at
  its run start, now receives and consumes both blocks in production. The thin-read-layer
  design paid off again: no corpus re-seed, no schema/scorer change, and no restart-only
  shortcut (the code is baked into the image, so `--build` is required, not a bare restart).
- **"Built" and "live" are distinct doc states worth separating.** The first commit marked
  Step 1 *built*; only after the prod deploy + cross-app smoke test is it *verified live*.
  Recording both (with the divergent dates 06-17 / 06-19) keeps the integration spec honest
  about what's proven in production vs merely merged — and keeps the cv-tailor-side DoD items
  (2–5) and the coverage-measurement gate (6) clearly flagged as still-open, not implied-done
  by "it worked."

---

## Bulk actions in Browse — frontend-only, convention over prompt (2026-06-19)

- **A build prompt asking for tests doesn't override a standing no-test convention — surface it,
  don't silently pick.** The prompt named 8 frontend logic tests in its DoD, but the repo has a
  firmly-established "no JS test toolchain" rule (frontend/CLAUDE.md, deviations 51f/52e) and bulk
  actions are frontend-only, so there's nothing for pytest to cover. Rather than quietly skip the
  tests *or* unilaterally introduce vitest (reversing a convention), asked the owner; they chose
  the convention. The resolution still honors the prompt's *intent*: the logic that the 8 tests
  would target (`statusSkipReason`, `planBulk`, `executeRole`/`executeBulk`) was extracted into
  pure functions in `lib/bulk.ts` with an **injectable** `BulkApi`, so it's testable-shaped and
  could grow JS tests later without rework — verified now by `tsc -b` + `vite build` + browser.
- **Gate the whole feature on `write_configured`, not just the apply button.** The prompt said
  "checkboxes always visible," but rendering selection UI on a read-only deploy (no owner key)
  would be a dead affordance — the same anti-pattern §10.5 and the detail panel already avoid by
  hiding `WriteControls` when `!configured`. Threading a `selectable` prop into `BrowseView` (so
  the checkbox column simply isn't rendered) kept it consistent with the rest of the UI.
- **Two 409s on the `will_not_apply` path mean opposite things.** A 409 on a *primary* flag
  annotation means the flag already exists → the role is **skipped** (benign, not a failure). But
  the *secondary* `rejection_reason` annotation that rides a `will_not_apply` status move can also
  409 — and there the status write already succeeded, so swallowing it and counting the role as
  **updated** is correct (treating it as a skip would under-report a real status change). Encoding
  both in `executeRole` up front avoided a confusing "1 skipped" that was actually a success.
- **Clearing selection inside a `setState` updater is a side-effect trap.** The first cut called
  `pushToast` from inside `setSelectedIds(prev => …)`, which fires a setter during another
  component's update. Reading the current `selectedIds` from the render closure in the wrapped
  `setFilters` (recreated each render, so never stale for a single filter change) is both simpler
  and pure — state updaters stay free of side effects.
- **Docker typecheck leaves an empty `node_modules` mountpoint even with an anonymous volume.**
  `-v /app/node_modules` shadows the real install (good — host stays clean of deps), but Docker
  still materializes an empty `node_modules/` dir and npm writes `package-lock.json` into the bind
  mount. Both must be `rm`'d after, or they poison the compose build (frontend-typecheck-in-docker
  memory). `git status` is the cheap final check that only the intended files changed.
- **The single-action flow became a multi-action composer after the owner used it.** The first
  build (per the prompt) was one-action-at-a-time: pick fit *or* status *or* flag *or* note, apply,
  re-select, repeat. Reviewing a roster usually wants several changes at once, so the owner asked
  to stage them together. The clean refactor kept the single-write primitive (`executeRole`,
  injectable api) and added a thin composite layer on top (`planComposite`/`executeComposite`) +
  a tabbed UI — the per-role/per-action skip model and the two-409 semantics carried over
  unchanged. **Lesson: build the per-item primitive first; batching/composition is a layer above
  it, not a rewrite.** The "include a tab when its toggle is ticked *or* a field is edited" rule
  was the one genuinely new decision — needed because fit/status have no empty state to infer
  intent from (unlike flag/note, where empty required text already means "not staged").

---

*[Claude Code: append new entries here as each step and phase completes.
Do not rewrite existing entries. Use the template above.]*
