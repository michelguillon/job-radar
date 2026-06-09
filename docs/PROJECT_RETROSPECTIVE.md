# PROJECT_RETROSPECTIVE.md — jd-refinery

> **This document captures what happened during the build.**
> **For the implemented system, see `PROJECT_ARCHITECTURE.md`.**

*Status: stub — to be completed post-build in a dedicated conversation.*
*See `SPEC_JD_REFINERY.md §12` for the starter prompt.*

---

## What I Thought I Was Building

A data collection pipeline that ingests job descriptions from public ATS APIs,
labels them with Claude, and produces a fine-tuning corpus.

The schema seemed straightforward: role type, seniority, required skills,
domain, remote policy. A few fields, a clear structure.

---

## What I Actually Built

*[Complete post-build]*

---

## What Changed

*[Complete post-build — known pre-build pivots to document:]*

- Schema required 10 changes across 10 manually-labelled JDs before any
  automation ran. The original `required_skills` field became 4 fields.
  `company_stage` was dropped then reinstated. `culture_signals`,
  `delivery_motion`, and `leadership_geography` were not in the original design.

- The tier model evolved from 4 tiers to a more nuanced human/machine
  validation split than originally planned.

- `application_decision` replaced a simple `applied: bool` after it became
  clear that fit score and application decision are orthogonal.

---

## Biggest Wins

*[Complete post-build]*

---

## Biggest Mistakes

*[Complete post-build]*

---

## Learning Shifts

### Before

The schema could be designed upfront from first principles. The fields were
obvious: role type, seniority, required skills, domain.

### After

The schema that works is the one that survived contact with real data. 10 JDs
triggered 10 changes. The most significant was splitting `required_skills`
into four fields — technologies and competencies are orthogonal dimensions
that a flat list conflates.

---

### Before

"Required skills" and "nice to have skills" are natural JD categories that
map cleanly to schema fields.

### After

Many JDs don't use these headings explicitly. The extraction prompt must
handle signal words ("must have", "ideally", "a plus") and the schema
must enforce the distinction structurally, not by convention.

---

### Before

`company_stage` (Series A, B, C) is useful and extractable from JDs.

### After

Funding stage is almost never stated in JDs. `company_size_signal` is
extractable. `company_stage` is only populated when explicitly stated or
unambiguously inferable (named investors, valuation mentioned).

---

*[Add further learning shifts post-build]*

---

## Top Learning Shifts

*[Complete post-build — minimum 8, maximum 10]*

---

## If I Did It Again

*[Complete post-build]*
