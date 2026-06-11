# Job Radar ↔ cv-tailor Integration Spec
## Unified specification — changes to both applications

**Status:** Phase 1 ✅ built (commit 32d1a09). Phases 2–4 pending.
**Last updated:** 2026-06-11
**Owned by:** Both repos — `job-radar` and `cv-tailor`

---

## 1. Purpose and boundaries

Job Radar and cv-tailor solve adjacent parts of the same workflow:

```
Job Radar  → which opportunities are worth pursuing?
cv-tailor  → how should I pursue them?
```

The missing link is **application intelligence**: connecting Job Radar's
structural fit prediction with cv-tailor's output quality metrics and
eventual application outcomes.

### What each system owns (permanent boundaries)

| Job Radar owns | cv-tailor owns |
|---|---|
| JD collection, extraction, scoring | CV tailoring, cover letters |
| Fit assessment (structural + feasibility) | CV quality, grounding, CVCM |
| Application workflow state | Run history, output files |
| Company universe, yield tracking | Model orchestration, critique loop |
| Corpus of scored opportunities | Corpus of CV versions |

**Job Radar does not:** generate CVs, store generated CV documents, edit
cv-tailor outputs, or score CV quality.

**cv-tailor does not:** decide whether a job is worth applying to, mutate
Job Radar fit scores, update Job Radar application status (until Phase 4),
or become a job tracker.

---

## 2. Why this integration exists

**Immediate value (Phase 1):** Job Radar should know whether a shortlisted
role has already gone through cv-tailor and what the output quality was.
Currently you switch between two tools with no shared state.

**Future value (Phases 3–4):** Once enough applications exist, the linked
data enables calibration questions that neither system can answer alone:

- Do high Job Radar fit scores lead to better cv-tailor coverage scores?
- Do high cv-tailor scores correlate with interview invitations?
- Do Product roles convert differently from Solutions roles?
- Are some companies high-fit but low-conversion?
- Does CVCM improve application outcomes?

The integration is built incrementally — the data model first, automation
later, analysis only once data proves which metrics matter.

---

## 3. Build order

```
Phase 1 → manual metrics (unblocked now)
   ↓ use for 5–10 real applications
Phase 2 → "Open in cv-tailor" button (Job Radar → cv-tailor handoff)
   ↓ both tools stable in daily integrated use
Phase 3 → cv-tailor sends results back (automated callback)
   ↓ Phase 3 data proves which metrics are worth using
Phase 4 → Job Radar pre-computed analysis fed to cv-tailor (deep integration)
```

Do not build Phase 3 before Phase 1 data proves which metrics to track.
Do not build Phase 4 before Phase 3 is stable.

---

## 4. Phase 1 — Manual cv-tailor metrics in Job Radar ✅ built

**Status:** Complete — commit 32d1a09, 430 tests. See `job-radar` CLAUDE.md
deviation 41 + LEARNINGS.

**As built:**
- `corpus/cv_tailor_links.jsonl` — new append-only file, gitignored
- `CV_TAILOR_LINK_VERSION = 1` + `CV_TAILOR_SOURCE` vocab + `validate_cv_tailor_link()`
  in `models/record.py` — constants only, no `SCHEMA_VERSION` bump
- `cli/stats.py` — `load_cv_tailor_links()`, `cv_tailor_view()`, join in
  `build_index_rows`; `GET /api/index` live overlay refreshes cv-tailor links
  alongside activity log and annotations
- `api/routers/cv_tailor.py` (new) — per-route gating: `POST /api/cv-tailor-results`
  (owner-gated, 404 unknown job, 422 bad score) + `GET /api/jobs/{job_id}` (public,
  no auth — returns `raw_text` for Phase 2 handoff). Per-route rather than
  router-level because the two endpoints have different access levels (deviation 41)
- React detail panel — `CvTailorSection`: read-only for all, owner Add/Edit form
  (scores entered 0–100, sent as 0.0–1.0 floats)
- `api/settings.py` — `JR_CV_TAILOR_LINKS_PATH` env var

**Trigger:** Unblocked. Build after yield tracking and rejection reasons
are stable.

**Goal:** Allow recording cv-tailor run metrics against a Job Radar role
after an application package has been generated. Creates the data model
before any API integration.

### 4.1 Changes to Job Radar

**New file:** `corpus/cv_tailor_links.jsonl` — append-only, gitignored,
same pattern as `activity_log.jsonl` and `annotations.jsonl`.

**Record format:**
```json
{
  "v": 1,
  "ts": "2026-06-11T12:00:00Z",
  "job_id": "sha256:abc123",
  "cv_tailor_run_id": "run_20260611_001",
  "cv_tailor_score": 0.72,
  "coverage_score": 0.81,
  "grounding_score": 0.96,
  "cvcm_enabled": true,
  "tailoring_mode": "full",
  "output_link": "https://cv-tailor.michel-portfolio.co.uk/runs/run_20260611_001",
  "notes": "Good output, but profile needed manual tightening around AI depth.",
  "source": "manual"
}
```

All fields except `v`, `ts`, `job_id` are optional. `source` defaults to
`"manual"` for Phase 1 manual records and `"cv_tailor_api"` for Phase 3
automated records. The cv-tailor run_id is the source of truth anchor —
the score fields here are a summary snapshot. If cv-tailor's rubric
evolves, these field names may drift; the run_id lets you trace back to
the canonical cv-tailor record.

**New API endpoints:**

```
POST /api/cv-tailor-results    Owner-protected (capability cookie)
                               Validates job_id exists (404 if not)
                               Validates scores are 0.0–1.0 (422 if not)
                               Appends to corpus/cv_tailor_links.jsonl

GET  /api/jobs/{job_id}        Public, read-only
                               Returns job detail for Phase 2 handoff
                               Includes raw_text (already visible in public UI)
                               404 if job_id not found
```

**Read model:** `stats.py --export-index` joins latest cv-tailor link per
`job_id` into `corpus/index.json`. `GET /api/index` live overlay refreshes
cv-tailor links alongside activity log and annotations.

```json
{
  "cv_tailor": {
    "has_output": true,
    "run_id": "run_20260611_001",
    "cv_score": 0.72,
    "coverage_score": 0.81,
    "grounding_score": 0.96,
    "cvcm_enabled": true,
    "tailoring_mode": "full",
    "output_link": "https://...",
    "notes": "...",
    "ts": "2026-06-11T12:00:00Z"
  }
}
```

If no link: `"cv_tailor": {"has_output": false}`

**UI — detail panel cv-tailor section:**

When `has_output === false` (owner unlocked):
```
─── CV-Tailor ────────────────────────────────────
No cv-tailor run recorded yet.
[Add cv-tailor metrics]
```

When `has_output === true`:
```
─── CV-Tailor ────────────────────────────────────
Run: run_20260611_001          2026-06-11
CV score: 72%  Coverage: 81%  Grounding: 96%
CVCM: enabled   Mode: full
Notes: Good output, but profile needed manual tightening.
↗ Open output
[Edit]  (owner only)
```

Public visitors see metrics read-only when present. Add form is
owner-gated (capability cookie), same as all write controls.

### 4.2 Changes to cv-tailor

None in Phase 1. cv-tailor is unaware of Job Radar.

### 4.3 Definition of Done

- Owner can add cv-tailor metrics from Job Radar detail panel
- Metrics append to `corpus/cv_tailor_links.jsonl`
- Metrics appear in the detail panel on reload (live overlay)
- `GET /api/jobs/{job_id}` returns job detail including `raw_text`
- `corpus/cv_tailor_links.jsonl` is gitignored
- All existing tests pass + Phase 1 tests pass

---

## 5. Phase 2 — Open job in cv-tailor

**Trigger:** 5–10 real Phase 1 applications — confirm the data model is
correct before building the handoff.

**Goal:** Smart button in Job Radar detail panel that adapts based on
whether a cv-tailor run already exists for the role.

### 5.1 Changes to Job Radar — ✅ built

**Status:** Built (frontend-only — no backend/endpoint/schema change). The smart
handoff button lives at the bottom of `CvTailorSection` (`frontend/src/components/
DetailPanel.tsx`): always visible (public + owner), never lock-gated, opens in a new
tab. `has_output` → `Open in cv-tailor ↗` (→ `/runs/<run_id>`); else `Create CV in
cv-tailor ↗` (→ `/new?source=job_radar&job_id=<job_id>`). The cv-tailor `/new`-route
handling (§5.2) remains a cv-tailor build. `tsc -b` clean; 430 pytest unchanged.

**UI only — one smart button in the detail panel:**

Visible to all users (public + owner). Not write-gated — it's a link,
not a mutation. cv-tailor's own key gate handles access control.

**State 1 — No cv-tailor run recorded (`cv_tailor.has_output === false`):**
```
[Create CV in cv-tailor ↗]
→ https://cv-tailor.michel-portfolio.co.uk/new?source=job_radar&job_id=<job_id>
```

**State 2 — Run exists (`cv_tailor.has_output === true`):**
```
[Open in cv-tailor ↗]
→ https://cv-tailor.michel-portfolio.co.uk/runs/<cv_tailor.run_id>
```

Logic:
```typescript
const url = job.cv_tailor.has_output
  ? `https://cv-tailor.michel-portfolio.co.uk/runs/${job.cv_tailor.run_id}`
  : `https://cv-tailor.michel-portfolio.co.uk/new?source=job_radar&job_id=${job.job_id}`

const label = job.cv_tailor.has_output
  ? "Open in cv-tailor ↗"
  : "Create CV in cv-tailor ↗"
```

Both states open in a new tab. Public visitors who click either button
will hit cv-tailor's own key gate — Job Radar does not need to replicate
that check.

No other Job Radar changes needed. `GET /api/jobs/{job_id}` was built in
Phase 1 and is already public. The `cv_tailor.has_output` and
`cv_tailor.run_id` fields are already in the index row.

### 5.2 Changes to cv-tailor

**New query parameter handling on the `/new` route:**

When opened with `?source=job_radar&job_id=<job_id>`:

1. Call Job Radar `GET /api/jobs/{job_id}`
2. Populate the JD input field with `raw_text`
3. Pre-fill company name and role title in the run metadata
4. Store the external reference on the run:
   ```json
   {
     "source": "job_radar",
     "job_id": "sha256:abc123",
     "company": "Elastic",
     "title": "Principal PM, AI agents",
     "source_url": "https://...",
     "job_radar_fit_label": "strong_fit",
     "job_radar_fit_score": 10
   }
   ```
5. Continue normal cv-tailor workflow

**Fallback:** if the Job Radar API fetch fails:
- Show a clear inline error: "Could not load JD from Job Radar — paste
  manually"
- Allow manual paste
- Do not silently create a run with an empty JD body
- Do not block the page

**No new auth required.** `GET /api/jobs/{job_id}` is public.
cv-tailor fetches it server-side to avoid CORS.

### 5.3 Definition of Done

- Job Radar detail panel has "Open in cv-tailor" button
- cv-tailor opens with the selected JD pre-populated
- cv-tailor stores the `job_id` reference on the run
- Failed fetch shows error and allows manual paste
- No run is created with an empty JD body

---

## 6. Phase 3 — cv-tailor sends results back to Job Radar

**Trigger:** Both tools stable in daily integrated use. Phase 1 data
confirms which metrics are worth tracking automatically.

**Goal:** When a cv-tailor run completes (and has `source=job_radar` +
`job_id`), cv-tailor POSTs summary metrics to Job Radar. Closes the loop:

```
Job Radar fit prediction
↓
cv-tailor output quality
↓
Application outcome (Phase 4)
↓
Future calibration
```

### 6.1 Changes to Job Radar

**New endpoint** (already specified in Phase 1):

```
POST /api/cv-tailor-results
```

In Phase 3 this endpoint also accepts machine-to-machine calls from
cv-tailor. The auth mechanism changes from capability cookie (browser) to
a **shared service secret** — `CV_TAILOR_SERVICE_KEY` env var on Job Radar,
sent as a `Bearer` token by cv-tailor.

```python
# Job Radar: validates either capability cookie OR service token
if not (has_valid_cookie(request) or has_valid_service_token(request)):
    raise HTTPException(403)
```

The `source` field distinguishes origin:
- `"manual"` — posted from the Job Radar UI (Phase 1)
- `"cv_tailor_api"` — posted by cv-tailor callback (Phase 3)

**UI additions:**

Multiple cv-tailor runs per job are preserved. In the detail panel:

```
─── CV-Tailor ────────────────────────────────────
Latest run: run_20260612_002     2026-06-12
CV score: 78%  Coverage: 85%  Grounding: 98%
CVCM: enabled   Mode: full
↗ Open output

Previous runs ▾
  2026-06-11  run_20260611_001  CV: 72%  Coverage: 81%
```

### 6.2 Changes to cv-tailor

**Callback on run completion:**

When a run has `source=job_radar` + `job_id` and reaches `run_complete`:

1. Assemble callback payload from `PipelineOutput`:
   ```json
   {
     "job_id": "sha256:abc123",
     "cv_tailor_run_id": "run_20260612_002",
     "cv_tailor_score": 0.78,
     "coverage_score": 0.85,
     "grounding_score": 0.98,
     "cvcm_enabled": true,
     "tailoring_mode": "full",
     "output_link": "https://cv-tailor.michel-portfolio.co.uk/runs/run_20260612_002",
     "notes": ""
   }
   ```
   Map from `PipelineOutput`: `overall_fit_score` → `cv_tailor_score`,
   grounded `keyword_coverage` (F-38) → `coverage_score`,
   `1 - (fabrication_flags / total_claims)` → `grounding_score`.

2. POST to `https://job-radar.michel-portfolio.co.uk/api/cv-tailor-results`
   with `Authorization: Bearer <CV_TAILOR_SERVICE_KEY>`

3. On success: show "Linked back to Job Radar ✓" in the SSE timeline
4. On failure: keep cv-tailor run successful; show warning in timeline;
   allow manual retry from the run history view

**Failure must not break run completion.** cv-tailor is not in Job
Radar's critical path and Job Radar is not in cv-tailor's.

**New env var on cv-tailor:** `JOB_RADAR_API_URL` + `CV_TAILOR_SERVICE_KEY`
(matches the key set on Job Radar). Both gitignored in `.env`.

### 6.3 Definition of Done

- cv-tailor POSTs completed run metrics to Job Radar automatically
- Job Radar appends the result without mutating scorer output
- Job Radar UI displays latest cv-tailor result + run history per job
- Failed callback does not break cv-tailor run completion
- `CV_TAILOR_SERVICE_KEY` auth works independently of the browser cookie

---

## 7. Phase 4 — Job Radar pre-computed analysis fed to cv-tailor

**Trigger:** Phase 3 stable. Sufficient linked data to confirm that
cv-tailor's Phase 0 JD extraction is the limiting quality factor (i.e.
Job Radar's richer extraction would produce meaningfully better tailoring).

**Goal:** Skip cv-tailor's Phase 0 (JD extraction via Mistral) and instead
use Job Radar's pre-computed `JDRecord` extraction, which is richer
(17 fields, calibrated schema, validated against real JDs) and already
paid for. Reduces per-run cost and improves tailoring quality for
structured extraction fields.

### 7.1 Changes to Job Radar

**Extend `GET /api/jobs/{job_id}`** to include structured extraction fields:

```json
{
  "job_id": "sha256:abc123",
  "company": "Elastic",
  "title": "Principal PM, AI agents",
  "source_url": "https://...",
  "location": "United Kingdom",
  "fit_label": "strong_fit",
  "fit_score": 10,
  "priority_score": 10,
  "raw_text": "Full JD text...",
  "extraction": {
    "role_type": ["Product", "AI Delivery"],
    "seniority": "director",
    "domain": ["AI Platform", "Enterprise Software"],
    "technical_depth": "hybrid",
    "delivery_motion": ["enterprise_platform", "partner_led"],
    "required_technologies": ["Elasticsearch", "Python", "REST APIs"],
    "required_competencies": ["product roadmap", "cross-functional leadership"],
    "nice_to_have_technologies": ["Kubernetes", "Terraform"],
    "nice_to_have_competencies": ["partner channel management"],
    "remote_policy": "hybrid",
    "leadership_geography": "EMEA",
    "company_stage": "public",
    "culture_signals": ["move fast", "customer obsession"]
  }
}
```

No schema changes — these fields are already on `JDRecord`. Just expose
them through the API.

### 7.2 Changes to cv-tailor

**Phase 0 bypass when Job Radar extraction is available:**

When a run has `source=job_radar` + `job_id` + Job Radar returns an
`extraction` object:

1. Skip Phase 0 Mistral extraction
2. Map `JDRecord.extraction` fields to cv-tailor's `JDAnalysis` schema:
   - `required_technologies` → `required_skills` (technical)
   - `required_competencies` → `required_skills` (soft/domain)
   - `role_type` → `role_type`
   - `domain` → `industry`
   - `delivery_motion` → inform Phase 1 CVCM context
   - `culture_signals` → `company_culture`
3. Populate `JDAnalysis` from mapped fields; mark
   `source: "job_radar_extraction"` in the run audit trail
4. Proceed to Phase 1 (fit assessment) as normal

**Fallback:** if mapping fails for any reason, fall back to Phase 0
Mistral extraction. Do not block the run.

**No new auth.** Uses the same `job_id` fetch from Phase 2/3.

### 7.3 Definition of Done

- cv-tailor uses Job Radar extraction fields when available
- Phase 0 is skipped (cost reduction logged in cost_breakdown)
- `source: "job_radar_extraction"` appears in the run audit trail
- Fallback to Phase 0 extraction on any mapping error
- cv-tailor output quality is measurably maintained or improved

---

## 8. Auth summary across all phases

| Phase | Mechanism | Direction | Status |
|---|---|---|---|
| Phase 1 — Manual POST from browser | HttpOnly capability cookie (`JR_WRITE_KEY`) — per-route (deviation 41/42) | Browser → Job Radar API | ✅ |
| Phase 2 — cv-tailor fetches JD | No auth — `GET /api/jobs/{job_id}` is public | cv-tailor server → Job Radar API | 🔲 |
| Phase 3 — cv-tailor POSTs results | Bearer token (`CV_TAILOR_SERVICE_KEY`) | cv-tailor server → Job Radar API | 🔲 |
| Phase 4 — cv-tailor fetches extraction | No auth — same public endpoint as Phase 2 | cv-tailor server → Job Radar API | 🔲 |

The browser capability cookie (HttpOnly, SameSite=Lax) is never sent in
machine-to-machine calls — it's physically inaccessible outside the browser.
Phase 3 uses a separate shared secret specifically for service-to-service auth.

**Per-route gating (deviation 41/42):** `require_unlocked` is declared on each
individual write route, not at the router level. This makes the security decision
explicit at the point of definition — a public endpoint and an owner-only endpoint
can coexist in the same router without ambiguity. All write endpoints across
`workflow.py`, `annotations.py`, and `cv_tailor.py` follow this pattern.

---

## 9. Data flow (all phases combined)

```
Job Radar                          cv-tailor
──────────────────────────────────────────────────────────────
corpus/scored/                     data/cvs/
corpus/activity_log.jsonl          outputs/<run_id>/
corpus/cv_tailor_links.jsonl  ←──  Phase 3 POST callback
       │                                    │
       ▼                                    ▼
GET /api/jobs/{job_id}  ──────────► Phase 0 bypass (Phase 4)
                                    Phase 1 fit assessment
"Open in cv-tailor" ──────────────► Pre-populated JD input
       │                            (Phase 2 URL handoff)
       ▼
cv_tailor.has_output: true
cv_score / coverage / grounding
output_link ──────────────────────► ↗ Open output (in UI)
```

---

## 10. File changes summary

### Job Radar

| File | Change | Phase | Status |
|---|---|---|---|
| `corpus/cv_tailor_links.jsonl` | New append-only file | 1 | ✅ |
| `models/record.py` | `CV_TAILOR_LINK_VERSION` + `CV_TAILOR_SOURCE` vocab + `validate_cv_tailor_link()` | 1 | ✅ |
| `cli/stats.py` | `load_cv_tailor_links()` + `cv_tailor_view()` + join in `build_index_rows` | 1 | ✅ |
| `api/routers/cv_tailor.py` | `POST /api/cv-tailor-results` (owner) + `GET /api/jobs/{job_id}` (public) — per-route gating | 1 | ✅ |
| `api/settings.py` | `JR_CV_TAILOR_LINKS_PATH` env var | 1 | ✅ |
| `api/main.py` | Register cv_tailor router | 1 | ✅ |
| `api/routers/index.py` | Live overlay refreshes cv-tailor links | 1 | ✅ |
| `frontend/src/lib/api.ts` | `CvTailor` types + `recordCvTailorResult()` | 1 | ✅ |
| `frontend/src/components/DetailPanel.tsx` | `CvTailorSection` component | 1 | ✅ |
| `.gitignore` | `corpus/cv_tailor_links.jsonl` | 1 | ✅ |
| `api/routers/workflow.py` | Per-route `require_unlocked` (deviation 42 refactor) | 1 | ✅ |
| `api/routers/annotations.py` | Per-route `require_unlocked` (deviation 42 refactor) | 1 | ✅ |
| `frontend` | Smart cv-tailor button — "Create CV" (no run) or "Open in cv-tailor" (run exists) | 2 | 🔲 |
| `api/routers/cv_tailor.py` | Add Bearer token auth for service calls | 3 | 🔲 |
| `frontend` | Run history (multiple runs) in detail panel | 3 | 🔲 |
| `api/routers/cv_tailor.py` | Return `extraction` in `GET /api/jobs/{job_id}` | 4 | 🔲 |
| `.env.example` | `CV_TAILOR_SERVICE_KEY=` | 3 | 🔲 |

### cv-tailor

| File | Change | Phase |
|---|---|---|
| `tailor/phases/phase0_jd_analysis.py` | Accept pre-computed extraction | 4 |
| `tailor/models.py` | `job_radar_source` field on `JDAnalysis` | 2/4 |
| `tailor/tailor.py` | Phase 2 URL parameter handling | 2 |
| `tailor/tailor.py` | Phase 3 callback on `run_complete` | 3 |
| `backend/routes/` | Query param handling for `?source=job_radar&job_id=` | 2 |
| `frontend/src/` | Prefill JD from Job Radar API response | 2 |
| `frontend/src/` | "Linked back to Job Radar" confirmation in SSE timeline | 3 |
| `.env.example` | `JOB_RADAR_API_URL=` + `CV_TAILOR_SERVICE_KEY=` | 3 |

---

## 11. What this enables long-term

Once all four phases are live and 20+ applications have gone through
the full pipeline, the linked data answers:

```
SELECT
  job_radar_fit_score,
  cv_tailor_coverage_score,
  application_outcome
FROM linked_applications
WHERE tailoring_mode = 'full'
```

This is the calibration loop that closes the system: Job Radar predicts
which roles are worth pursuing; cv-tailor determines how well the CV
covers the role; outcomes show whether the predictions were right. Both
scorers can be refined from the same evidence base.

---

## 12. Relationship to existing specs

- Job Radar changes: see `docs/job_radar_SPEC.md §11.3`
- cv-tailor Phase 0–6 pipeline: see `cv_tailor_ARCHITECTURE.md §3`
- cv-tailor security model: see `cv_tailor_ARCHITECTURE.md §9`
- Job Radar security model: see `docs/job_radar_SPEC.md §10.5`
ENDOFFILE