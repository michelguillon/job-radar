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

*[Claude Code: append new entries here as each step and phase completes.
Do not rewrite existing entries. Use the template above.]*
