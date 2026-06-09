# PROJECT_LEARNINGS.md — jd-refinery

> **This document captures reusable engineering and AI-system lessons.**
> **For project history, see `PROJECT_RETROSPECTIVE.md`.**

*Status: stub — to be completed post-build in a dedicated conversation.*
*See `SPEC_JD_REFINERY.md §12` for the starter prompt.*

---

## Cross-Cutting Decisions

### Schema design as architecture

**Context:** The extraction schema determines what every downstream system
(fine-tuning, fit scoring, cv-tailor integration) can and cannot do. It is
the most load-bearing decision in the whole project.

**Decision:** Validate the schema empirically on real JDs before building any
automation. Lock the schema before any automated collection runs.

**Outcome:** 10 schema changes triggered by 10 manually-labelled JDs. Changes
included field splits, new fields, taxonomy additions, and annotation/extraction
boundary decisions that would have been wrong if made upfront.

**Reusability:** Any labelling pipeline. Design the schema last (after seeing
real data), not first. The formalisation gate — a field is promoted only if it
appears in 3+ real examples, is objectively extractable, and is useful
downstream — is reusable as a general pattern.

---

### Extraction schema vs annotation schema

**Context:** A corpus that mixes "what the JD says" with "what I think about
the JD" produces contaminated training data. The boundary must be structural.

**Decision:** Two schemas, never mixed. Extraction schema (Claude-populated,
objective, generalisable). Annotation schema (human-only, subjective, personal).

**Outcome:** Clean separation enforced at the dataclass level. Claude never
touches annotation fields. Human never has to remember which fields are which.

**Reusability:** Any labelling project where the labeller is also a consumer
of the data. The contamination risk is highest when the person labelling the
data has a personal stake in the labels.

---

### Batch API as default for offline processing

**Context:** 200 JDs × ~2,000 tokens each = significant cost at synchronous
pricing.

**Decision:** Claude Batch API exclusively for all labelling runs. 50% cost
discount. No latency requirement for an offline pipeline.

**Outcome:** *[Complete post-build with actual cost figures]*

**Reusability:** Any pipeline that processes a fixed corpus offline. Synchronous
API is only justified when latency matters. For batch jobs, it is always wrong.

---

## Learning Entries

*[Complete post-build — minimum 5 entries, using template below]*

---

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
the schema had evolved to 15 extraction fields and 8 annotation fields.
Every change was triggered by a real JD, not by upfront reasoning.

#### Surprise

The changes weren't refinements — several were structural. `required_skills`
becoming 4 fields, `delivery_motion` emerging as a first-class dimension,
`application_decision` replacing `applied: bool` — these were not
foreseeable from the spec.

#### Reusable Pattern

Label 5–10 real examples by hand before designing any extraction schema.
The schema that emerges from practice is always better than the schema
designed upfront. Budget time for this. It is not preliminary work — it is
the most valuable work in a labelling pipeline.

---

### Learning 2 — Annotation fields reveal what you actually care about

#### Learning

Fields like `location_workable`, `domain_distance`, `blocking_constraints`,
and `application_decision` were not in the original spec. They emerged from
the actual job search use case — what do I need to know to make an
application decision?

#### Surprise

The annotation schema ended up being as rich as the extraction schema.
The original spec treated annotation as an afterthought (just a fit_score
and a notes field).

#### Reusable Pattern

Before designing a labelling schema, ask: what decisions will this corpus
support? Work backwards from the decision to the fields needed. For a
personal job search corpus, the annotation schema is load-bearing.

---

*[Add further learning entries post-build]*
