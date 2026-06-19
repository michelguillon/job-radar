# SPEC_INTEGRATION_PHASE4.md
## Job Radar → cv-tailor: Assessment Context Enrichment

**Status:** Step 1 ✅ built + deployed + **verified live end-to-end between
both apps (2026-06-19)**. Steps 2–3 (cv-tailor prompt wiring) and the §6 coverage
measurement remain open — see §10.
**Trigger:** 20+ full-mode cv-tailor runs with linked Job Radar roles
**Part of:** Job Radar ↔ cv-tailor Integration Spec §7
**Last updated:** 2026-06-19

---

## 1. Problem

cv-tailor currently runs its fit assessment (Phase 1) with two inputs:
- The JD text (from Phase 0 Mistral extraction)
- The candidate profile (static, from `profile.yaml`)

It does not know:
- What Job Radar's structural scorer found (fit dimensions, blockers,
  requirement gaps)
- What the owner has manually observed (fit overrides, annotations,
  notes, rejection reasons)
- Whether the owner considers this a stretch, a strong fit, or blocked

This means cv-tailor is assessing the role in a vacuum. It may spend
tailoring effort on dimensions the owner already knows are blocked, or
under-emphasise dimensions the owner has flagged as important.

---

## 2. What this is NOT

This is not a replacement of cv-tailor's Phase 0 (Mistral extraction).
That extraction serves a different purpose — keyword vocabulary, emphasis
areas, skill gap language close to the raw JD text. It stays.

This is not passing Job Radar's structured extraction *instead of*
Mistral's. The two extractions are complementary, not competing.

This is **additional context** — Job Radar's assessment and the owner's
manual feedback, passed to cv-tailor as a priming layer before Phase 1
runs. cv-tailor uses it to inform its analysis, not replace it.

---

## 3. What to pass

Extend `GET /api/jobs/{job_id}` (already public, already called by
cv-tailor at run start) to include a new `assessment` object:

```json
{
  "job_id": "sha256:abc123",
  "company": "Writer",
  "title": "Strategic AI Transformation Lead",
  "source_url": "https://...",
  "raw_text": "...",
  "extraction": {
    "role_type": ["AI Delivery"],
    "seniority": "director",
    "domain": ["AI Platform"],
    "technical_depth": "hybrid",
    "delivery_motion": ["enterprise_platform"],
    "required_technologies": [...],
    "required_competencies": [...],
    "requirement_gaps": [
      "formal management consulting background"
    ]
  },
  "assessment": {
    "fit_label": "strong_fit",
    "fit_score": 10,
    "priority_score": 9,
    "fit_override": {
      "label": "good_fit",
      "reason": "requires formal consulting track record"
    },
    "blocking_constraints": [],
    "requirement_gaps": [
      "formal management consulting background"
    ],
    "annotations": [
      {
        "type": "technical_depth_incorrect",
        "field": "technical_depth",
        "reason": "role is more strategic than technical"
      }
    ],
    "notes": [
      {
        "ts": "2026-06-14",
        "text": "Strong culture fit but consulting background a real gap"
      }
    ],
    "owner_status": "shortlisted"
  }
}
```

**What each field adds to cv-tailor:**

| Field | How cv-tailor uses it |
|---|---|
| `fit_label` / `fit_score` | Calibrate ambition level of tailoring — stretch roles need more aggressive reframing |
| `fit_override` + reason | Explicit owner signal: "I know I'm short here, compensate for it" |
| `blocking_constraints` | Don't waste tailoring effort on blocked dimensions |
| `requirement_gaps` | Focus CV coverage on closing these specific gaps |
| `annotations` | Owner corrections to the extraction — more accurate than raw Mistral output |
| `notes` | Owner's qualitative read on the role — inform tone and emphasis |
| `owner_status` | Context on urgency — shortlisted = invest more; review = lighter touch |

---

## 4. How cv-tailor uses it

The assessment context enriches **Phase 1 (fit assessment)**, not
Phase 0 (JD extraction). Phase 0 still runs as normal.

When `assessment` is present in the Job Radar API response, cv-tailor
passes it as additional context to the Phase 1 prompt:

```
You have access to a structured assessment of this role from the
candidate's job tracking system:

Fit assessment: strong_fit (score: 10/10)
Owner override: good_fit — "requires formal consulting track record"
Requirement gaps identified: formal management consulting background
Owner notes: "Strong culture fit but consulting background a real gap"

Use this context to:
1. Prioritise CV coverage of the identified requirement gaps
2. Acknowledge the override reason — don't over-claim on the gap
3. Calibrate tailoring ambition to the owner's assessment
```

cv-tailor's own Phase 1 analysis still runs independently — the Job
Radar context is a priming layer, not a replacement. The Phase 1 output
reflects both the JD analysis and the owner's perspective.

---

## 5. Job Radar changes

### 5.1 Extend `GET /api/jobs/{job_id}`

The endpoint already returns `raw_text`, `company`, `title`,
`source_url`, `fit_label`, `fit_score`. Extend to include:

**`extraction`** — from `JDRecord` (already in the scored corpus):
`role_type`, `seniority`, `domain`, `technical_depth`,
`delivery_motion`, `required_technologies`, `required_competencies`,
`nice_to_have_technologies`, `nice_to_have_competencies`,
`requirement_gaps`

**`assessment`** — from SQLite (activity_log, annotations):
- `fit_label`, `fit_score`, `priority_score` — from ApplicationRecord
- `fit_override` — latest `fit_override` event from `activity_log`
- `blocking_constraints` — from ApplicationRecord
- `requirement_gaps` — from ApplicationRecord
- `annotations` — all annotations from `annotations` table
- `notes` — all `note` events from `activity_log`
- `owner_status` — latest `status` event from `activity_log`

All fields are optional — if no override, no annotations, no notes,
the fields are absent or empty. cv-tailor handles missing gracefully.

### 5.2 No new endpoints

`GET /api/jobs/{job_id}` already exists and is already called by
cv-tailor at run start (Phase 2 pattern). This is a pure extension of
that response — no new auth, no new routes.

---

## 6. cv-tailor changes

### 6.1 Read `assessment` from Job Radar response

In `api/job_radar.py`, `fetch_job()` already returns the full response.
Map the new `assessment` field into a typed model:

```python
@dataclass
class JobRadarAssessment:
    fit_label: str | None
    fit_score: int | None
    fit_override: dict | None      # {label, reason}
    blocking_constraints: list[str]
    requirement_gaps: list[str]
    annotations: list[dict]        # [{type, field, reason}]
    notes: list[dict]              # [{ts, text}]
    owner_status: str | None
```

Store on `run_meta.json` alongside `job_radar_source`:
```json
"job_radar_assessment": { ... }
```

Write-once at run creation, same as `job_radar_source`.

### 6.2 Pass to Phase 1 fit assessment

When `job_radar_assessment` is present and non-empty, include it in
the Phase 1 system context. Keep it clearly labelled as "owner's
assessment" — not ground truth, not a constraint, just informed context.

If `job_radar_assessment` is absent (run not from Job Radar, or Job
Radar returned no assessment data): Phase 1 runs exactly as today.
No regression.

### 6.3 Log in Langfuse

Include `job_radar_assessment` as trace metadata on the cv-tailor
Langfuse trace. This enables cross-system analysis: were runs with
owner-flagged gaps better tailored than runs without?

---

## 7. What does NOT change

- Phase 0 Mistral extraction — unchanged, always runs
- cv-tailor's own fit assessment logic — unchanged
- The Phase 3 callback (cv-tailor → Job Radar) — unchanged
- Auth — `GET /api/jobs/{job_id}` is already public
- Any run not from Job Radar — unchanged, no assessment context

---

## 8. Build order

1. **Job Radar:** extend `GET /api/jobs/{job_id}` to return `extraction`
   + `assessment` — backend only, no UI changes
2. **cv-tailor:** read and store `assessment` from the response —
   `job_radar.py` + `run_meta.json`
3. **cv-tailor:** pass assessment context to Phase 1 prompt — prompt
   engineering work, requires careful testing
4. **Both:** verify in Langfuse that assessment context improves
   coverage scores on roles with flagged gaps

Step 3 is the hard part — prompt engineering to use the context well
without over-constraining the tailoring. Build steps 1–2 first and
validate the data flow before touching the Phase 1 prompt.

---

## 9. Trigger and gate

**Minimum before building:** 20 full-mode cv-tailor runs with linked
Job Radar roles, covering a variety of fit labels (strong_fit,
good_fit, stretch, blocked_fit) and at least 5 roles with manual
annotations or fit overrides.

**Why this gate matters:** the Phase 1 prompt change in step 3 needs
a calibration baseline. You need to know what cv-tailor produces
*without* the context before you can measure whether the context helps.
The Langfuse traces from those 20+ runs are the before/after comparison
set.

**Current status:** ~9 runs, mostly demo mode. Not yet at gate.

---

## 10. Definition of Done

1. ✅ `GET /api/jobs/{job_id}` returns `extraction` + `assessment` (Job Radar
   side — built, deployed, **verified live end-to-end with cv-tailor 2026-06-19**)
2. cv-tailor stores `job_radar_assessment` in `run_meta.json` *(cv-tailor repo)*
3. Phase 1 prompt uses assessment context when present *(cv-tailor repo)*
4. Runs without Job Radar source are unaffected *(cv-tailor repo)*
5. Langfuse traces include assessment metadata *(cv-tailor repo)*
6. Measurable improvement in coverage scores on gap-flagged roles
   vs baseline (from pre-Phase 4 Langfuse traces) — **open**, needs accumulated
   run data; the measurement gate, not a code task

> **2026-06-19:** Item 1 (the only Job Radar-side deliverable) is live and the
> data flows correctly between both deployed apps — cv-tailor fetches the endpoint
> at run start and receives the `extraction` + `assessment` blocks. Items 2–5 are
> cv-tailor-repo work tracked there; item 6 is the longer coverage-measurement gate.
