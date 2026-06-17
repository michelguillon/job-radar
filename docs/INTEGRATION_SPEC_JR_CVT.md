# Job Radar ↔ cv-tailor Integration Spec
## Unified specification — changes to both applications

**Status:** Phase 1 ✅ built (commit 32d1a09). Phase 2 ✅ built (Job Radar button + cv-tailor
handoff). Phase 3 ✅ built (Job Radar endpoint + cv-tailor callback, commit 5b59188) —
**deployed and smoke-tested 2026-06-12** (first real callback: Sr Staff PM role, Job Radar
strong_fit 10 → cv-tailor Fit 37% / Coverage 15% / CV Quality 7.9/10, demo mode).
Phase 4 pending.
**Last updated:** 2026-06-12
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
Job Radar fit scores, update Job Radar application status, or become a job tracker.

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
   ↓ 20+ linked applications with outcomes
Phase 4 → redesign based on data (original design retired — see §7)
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
  (fit/coverage entered 0–100 → sent 0.0–1.0; cv-quality entered 0–10 → sent as-is)
- `api/settings.py` — `JR_CV_TAILOR_LINKS_PATH` env var

**Schema cleanup (deviation 43, before Phase 3):** the metrics were aligned to the
cv-tailor UI — `cv_tailor_score` → `fit_score` (0.0–1.0), `grounding_score` removed,
`cv_quality_score` (0.0–10.0, raw rubric score) added. Old records are migrated to the
new names at read time (`cli.stats._migrate_cv_tailor_fields`) — no file rewrite.

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
  "fit_score": 0.56,
  "coverage_score": 0.35,
  "cv_quality_score": 8.1,
  "cvcm_enabled": true,
  "tailoring_mode": "full",
  "output_link": "https://cv-tailor.michel-portfolio.co.uk/runs/run_20260611_001",
  "notes": "Good output, but profile needed manual tightening around AI depth.",
  "source": "manual"
}
```

The three metrics mirror the cv-tailor UI: `fit_score` + `coverage_score` are
normalised 0.0–1.0 (shown as %), `cv_quality_score` is the raw 0.0–10.0 rubric score
(shown as X.X/10). All fields except `v`, `ts`, `job_id` are optional. `source`
defaults to `"manual"` (Phase 1 manual records) and `"cv_tailor_api"` (Phase 3
callback). The cv-tailor run_id is the source of truth anchor — the score fields
here are a summary snapshot.

**New API endpoints:**

```
POST /api/cv-tailor-results    Owner capability cookie OR CV_TAILOR_SERVICE_KEY
                               Bearer token (Phase 3 m2m, deviation 43)
                               Validates job_id exists (404 if not)
                               Validates fit/coverage 0.0–1.0, cv_quality 0.0–10.0
                               (422 if not). Appends to corpus/cv_tailor_links.jsonl

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
    "fit_score": 0.56,
    "coverage_score": 0.35,
    "cv_quality_score": 8.1,
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
tab. `has_output` → `Open in cv-tailor ↗` (→ `/api/runs/<run_id>/report`); else `Create CV in
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
→ https://cv-tailor.michel-portfolio.co.uk/api/runs/<cv_tailor.run_id>/report
```

Logic:
```typescript
const url = job.cv_tailor.has_output
  ? `https://cv-tailor.michel-portfolio.co.uk/api/runs/${job.cv_tailor.run_id}/report`
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

### 5.2 Changes to cv-tailor — ✅ built

**Status:** Built (cv-tailor commit — see cv-tailor `LEARNING_NOTES` F-51 + SPEC §12.10).
As-built notes, where it deviated from / refined this spec:
- **Two server-side fetch points, not one.** A display-only **prefill proxy**
  `GET /api/job-radar/jobs/{job_id}` (so the Run page can pre-populate the JD textarea +
  company *before* the user starts — the frontend calls the cv-tailor backend, never Job
  Radar, avoiding CORS), plus the **authoritative** fetch inside `POST /api/runs` when
  `source=job_radar`. The run-start fetch is the source of truth for both the JD body and the
  stored reference; the textarea is read-only once loaded so an edited/stale preview can't drift it.
- **Reference key is `job_radar_source`** on the run's `run_meta.json` sidecar (mutable-state
  pattern, D-40/F-46 — *not* the append-only `run_log.jsonl`), **write-once at creation**. Fields:
  `{job_id, company, title, source_url, fit_label, fit_score}`.
- **Failure → HTTP 502, no run created** (network / 404 / non-JSON / empty `raw_text`). The
  request aborts before allocating a run id — never a run with an empty JD. The frontend degrades
  to manual paste (drops the linkage → a normal run) on a proxy failure, never blocking the page.
- **`job_radar_source` is owner-only:** redacted from the public archive list and blanked in
  `GET /runs/{id}/detail` for any locked request (the `source_url` points at a personal tool).
- **Env var `JOB_RADAR_API_URL`** (default `https://job-radar.michel-portfolio.co.uk`).
- Runs default `public_demo: false` (cv-tailor's existing default — not overridden).

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
Application outcome (Phase 4 — redesign pending)
↓
Future calibration
```

### 6.1 Changes to Job Radar — endpoint auth ✅ built

**Endpoint** (built in Phase 1):

```
POST /api/cv-tailor-results
```

In Phase 3 this endpoint also accepts machine-to-machine calls from
cv-tailor. **✅ Built (Job Radar side, deviation 43):** the endpoint now accepts
the owner capability cookie **OR** a `CV_TAILOR_SERVICE_KEY` Bearer token (a
shared service secret, separate from `JR_WRITE_KEY`), validated constant-time by
`api.security.has_valid_service_token`. Both paths fail closed (no cookie + no/
invalid token, or an unconfigured key → 403).

```python
# api/routers/cv_tailor.py — accepts either capability cookie OR service token
if not (
    verify_token(request.cookies.get(WRITE_COOKIE))
    or has_valid_service_token(request, settings.cv_tailor_service_key)
):
    raise HTTPException(403, "not authorised — owner unlock or service token required")
```

The `source` field distinguishes origin (validated against `CV_TAILOR_SOURCE`):
- `"manual"` — posted from the Job Radar UI (Phase 1)
- `"cv_tailor_api"` — posted by cv-tailor callback (Phase 3)

**Remaining (not yet built):** the run-history UI below — Phase 1/2 surface only
the *latest* run per job (`load_cv_tailor_links` keeps latest by `ts`). Surfacing
the collapsed previous-runs list is a later UI step, deferred until callbacks
actually produce multiple runs per job.

```
─── CV-Tailor ────────────────────────────────────
Latest run: run_20260612_002     2026-06-12
Fit: 78%   Coverage: 85%   CV Quality: 8.7/10
CVCM: enabled   Mode: full
↗ Open output

Previous runs ▾
  2026-06-11  run_20260611_001  Fit: 72%  Coverage: 81%
```

### 6.2 Changes to cv-tailor — ✅ built (commit 5b59188, 328 tests)

**Status:** Complete. See cv-tailor `LEARNING_NOTES` F-52 + `SPEC §12.10`.
As-built notes where implementation deviated from or refined the spec:
- **Sync `httpx.post`, not `asyncio.create_task`** — run completes on a worker
  thread with no event loop; `create_task` would raise. Sync POST after
  `run_complete` is the correct bridge (mirrors `fetch_job`).
- **`cv_quality_score` = aggregate `critique_score`** from the final non-frozen
  iteration checkpoint (`iteration_N.json`), not an average of per-section
  `claude_quality`. This is the exact number the cv-tailor report header and
  Scores tab display — callback and UI can never disagree.
- **EventSource held open 8s** for Job Radar-originated runs so the trailing
  `job_radar_linked` SSE indicator is deliverable after `run_complete` fires.
- **Opt-in by config:** `JOB_RADAR_SERVICE_KEY` unset → callback skipped
  silently; exact Phase 2 behaviour. No code change needed to enable/disable.
- **Metrics from on-disk checkpoints**, not `run_pipeline` return dict (which
  omits fit score, quality, and CVCM).

**Callback on run completion:**

When a run has `source=job_radar` + `job_id` and reaches `run_complete`:

1. Assemble callback payload from `PipelineOutput` (field names per deviation 43 —
   the schema the Job Radar endpoint validates):
   ```json
   {
     "job_id": "sha256:abc123",
     "cv_tailor_run_id": "run_20260612_002",
     "fit_score": 0.78,
     "coverage_score": 0.85,
     "cv_quality_score": 8.7,
     "cvcm_enabled": true,
     "tailoring_mode": "full",
     "output_link": "https://cv-tailor.michel-portfolio.co.uk/runs/run_20260612_002",
     "source": "cv_tailor_api",
     "notes": ""
   }
   ```
   Map from `PipelineOutput`: `overall_fit_score` → `fit_score` (0.0–1.0),
   grounded `keyword_coverage` (F-38) → `coverage_score` (0.0–1.0), CV quality
   rubric score → `cv_quality_score` (0.0–10.0, raw). The speculative
   `grounding_score` is dropped (no Job Radar destination field).

2. POST to `https://job-radar.michel-portfolio.co.uk/api/cv-tailor-results`
   with `Authorization: Bearer <CV_TAILOR_SERVICE_KEY>`

3. On success: show "Linked back to Job Radar ✓" in the SSE timeline
4. On failure: keep cv-tailor run successful; show warning in timeline;
   allow manual retry from the run history view

**Failure must not break run completion.** cv-tailor is not in Job
Radar's critical path and Job Radar is not in cv-tailor's.

**New env var on cv-tailor:** `JOB_RADAR_API_URL` + `CV_TAILOR_SERVICE_KEY`
(matches the key set on Job Radar). Both gitignored in `.env`.

### 6.3 Definition of Done — ✅ met

- ✅ cv-tailor POSTs completed run metrics to Job Radar automatically
- ✅ Job Radar appends the result without mutating scorer output
- ✅ Job Radar UI displays latest cv-tailor result per job
- ✅ Failed callback does not break cv-tailor run completion
- ✅ `CV_TAILOR_SERVICE_KEY` auth works independently of the browser cookie
- 🔲 Run history UI (multiple runs per job) — deferred until callbacks
  produce multiple runs; data already preserved append-only

---

## 7. Phase 4 — Deep integration (to be redesigned based on data)

**Status:** 🔄 Broader redesign still open. **Step 1 ✅ built (2026-06-17,
Job Radar side).**

**Step 1 — extraction + assessment context on the read endpoint (✅ built).**
`GET /api/jobs/{job_id}` (public, unchanged auth) now returns two nested objects
alongside its existing fields:
- `extraction` — the JDRecord extraction fields (`role_type`, `seniority`,
  `domain`, `technical_depth`, `delivery_motion`, `required_technologies`,
  `required_competencies`, `nice_to_have_technologies`,
  `nice_to_have_competencies`, `remote_policy`, `leadership_geography`); `null`
  when the role has no JDRecord (partial manual ingest).
- `assessment` — Job Radar's scorer verdict (`fit_label`, `fit_score`,
  `priority_score`, `blocking_constraints`, `requirement_gaps`) + the owner's
  live workflow state: `fit_override` (`{label, reason}`|null), `owner_status`,
  `annotations` (`[{type, field, reason}]`), `notes` (`[{ts, text}]`).

This is a **scoped revival** of the originally-retired "share Job Radar's
extraction" idea (below): it does **not** couple the two pipelines — it just
*exposes* the richer extraction + the human assessment as read-only context that
cv-tailor's Phase-0 bypass *may* consume, leaving the keyword-coverage question
to cv-tailor's own Mistral pass. Pure join over existing data; no schema, scorer,
or auth change (Job Radar CLAUDE.md deviation 53, SPEC §11.3). The broader
multi-agent-scoring redesign below is unchanged by this.

**Original design (retired narrative, kept for context):** To be redesigned once
Phase 3 data accumulates.

**Original assumption (retired):** Job Radar's 17-field `JDRecord` extraction
(Claude Sonnet/Haiku) is richer than cv-tailor's Phase 0 (Mistral mini), so
passing it to cv-tailor would improve tailoring quality.

**Why this doesn't hold:**
The two extractions serve different purposes. Job Radar extracts to score
structural fit — clean enums, blocking constraints, role/domain classification.
cv-tailor extracts to understand what the JD is asking for in order to tailor
the CV against it — keyword vocabulary, emphasis areas, skill gap language.
Mistral's Phase 0 output stays closer to the raw JD text, which is exactly
what keyword coverage matching needs. Coupling the two pipelines for marginal
and unproven gain adds complexity without a clear benefit.

Early Phase 3 data supports this: cv-tailor fit assessments (37% fit, 15%
coverage on a Job Radar strong_fit 10 role) are directionally correct and
measuring something genuinely different — CV coverage vs structural profile fit.
Both extractions appear to be doing their job well for their respective purpose.

**Direction for redesign — multi-agent scoring orchestration:**

Rather than passing one system's extraction to the other, the more interesting
design is a **shared scoring layer** that both systems could consume: a
multi-agent orchestrator that assesses a role from multiple viewpoints
(structural fit, CV coverage, market positioning, narrative coherence) and
produces a richer, more calibrated signal than either system generates alone.

This is a research-grade design problem — prompt engineering, context design,
and loop architecture all apply. Key questions to answer from Phase 3 data
before designing:

- Where do Job Radar and cv-tailor scores diverge most? (structural fit vs
  coverage gap — which dimension predicts application outcomes better?)
- Are there systematic cases where both systems are wrong in the same
  direction? (suggests a shared extraction failure mode worth fixing)
- Does demo vs full mode in cv-tailor change the divergence pattern?
- What would a third "viewpoint" add that neither system currently captures?
  (e.g. market competitiveness, narrative strength, hiring manager perspective)

**First-pass tooling for these questions ✅ built (2026-06-12, Job Radar side).**
`python -m cli.analyse --report cv_tailor` (+ `GET /api/report/cv_tailor`) is the local,
score-only calibration view: per role it shows `Δ = CVT_fit% − (JR_fit_score × 10)`, a
divergence summary (mean/most-aligned/most-divergent), and a **demo-vs-full mode
breakdown** — directly addressing the first and third questions above from the
`cv_tailor_links.jsonl` snapshot. It is the snapshot-level complement to the per-run
Langfuse evidence below; the systematic-same-direction-error and outcome-correlation
questions still need the trace layer + linked outcomes.

**Trigger for design:** 20+ linked applications with outcomes across both
systems. The data is the design brief.

**Observability for the data brief (Langfuse).** Answering these questions needs the
per-run evidence captured, not just the final scores in `cv_tailor_links.jsonl`. That
instrumentation is now being built — see `cv-tailor/docs/SPEC_LANGFUSE_INSTRUMENTATION.md`:
- **cv-tailor side ✅ built (2026-06-12, F-53).** Each run emits one Langfuse trace
  (`cv_tailor_run`) carrying `run_id`, `job_id`, `company`, and `job_radar_fit_label/score`
  in metadata, with phase/iteration spans, per-call LLM generations (token counts), and
  `fit_score`/`coverage_score`/`cv_quality_score`/`job_radar_fit_score` as trace scores.
  `run_id` and `job_id` are the join keys back to Job Radar.
- **Job Radar side 🔄 pending (Phase B).** Extraction-batch + scoring-run traces, so a role
  is queryable end-to-end (Job Radar extraction → score → cv-tailor run → outcome) in one place.
Once both sides emit traces, the §7 divergence questions are answerable by joining on `job_id`
in the Langfuse store rather than by hand.

**Relationship to Project 5 (fine-tuning):** a multi-agent scoring layer may
be a better use of the corpus than fine-tuning the existing rule-based scorer.
Worth evaluating both directions when the corpus justifies it.

---

## 8. Auth summary across all phases

| Phase | Mechanism | Direction | Status |
|---|---|---|---|
| Phase 1 — Manual POST from browser | HttpOnly capability cookie (`JR_WRITE_KEY`) — per-route (deviation 41/42) | Browser → Job Radar API | ✅ |
| Phase 2 — cv-tailor fetches JD | No auth — `GET /api/jobs/{job_id}` is public | cv-tailor server → Job Radar API | ✅ |
| Phase 3 — cv-tailor POSTs results | Bearer token (`CV_TAILOR_SERVICE_KEY`) | cv-tailor server → Job Radar API | ✅ |
| Phase 4 — redesign pending | TBD — depends on new design | TBD | 🔄 |

The browser capability cookie (HttpOnly, SameSite=Lax) is never sent in
machine-to-machine calls — it's physically inaccessible outside the browser.
Phase 3 uses a separate shared secret specifically for service-to-service auth.

**Per-route gating (deviation 41/42):** `require_unlocked` is declared on each
individual write route, not at the router level. This makes the security decision
explicit at the point of definition — a public endpoint and an owner-only endpoint
can coexist in the same router without ambiguity. All write endpoints across
`workflow.py`, `annotations.py`, and `cv_tailor.py` follow this pattern, **except**
`POST /api/cv-tailor-results`, which runs an inline cookie-OR-Bearer check instead
(it must accept both the owner cookie and the Phase 3 service token — deviation 43).

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
fit_score / coverage / cv_quality
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
| `frontend` | Smart cv-tailor button — "Create CV" (no run) or "Open in cv-tailor" (run exists) | 2 | ✅ |
| `models/record.py` + `cli/stats.py` | Schema cleanup: `fit_score`/`cv_quality_score`, drop `grounding_score`, read-time migration | 3 | ✅ (deviation 43) |
| `api/routers/cv_tailor.py` + `api/security.py` | Bearer token auth (`has_valid_service_token`) — cookie OR token | 3 | ✅ (deviation 43) |
| `api/settings.py` + `.env.example` | `CV_TAILOR_SERVICE_KEY` setting + env var | 3 | ✅ |
| `frontend` | Run history (multiple runs) in detail panel | 3 | 🔲 |
| `cli/stats.py` | `load_all_cv_tailor_links()` — full run history (un-deduplicated), for the calibration report | 4-prep | ✅ |
| `cli/analyse.py` | `--report cv_tailor` calibration report (JR vs CVT Δ, divergence summary, mode breakdown, multiple runs) | 4-prep | ✅ |
| `api/routers/reports.py` | `GET /api/report/cv_tailor` (public download, same pure functions) | 4-prep | ✅ |
| `frontend/src/{lib/api.ts,components/Sidebar.tsx}` | "CV-Tailor calibration" download button | 4-prep | ✅ |
| `api/routers/cv_tailor.py` | Return `extraction` in `GET /api/jobs/{job_id}` | 4 | 🔲 |

### cv-tailor

| File | Change | Phase | Status |
|---|---|---|---|
| `api/job_radar.py` | New — server-side Job Radar fetch (`fetch_job`, `job_radar_source`) | 2 | ✅ |
| `api/routers/job_radar.py` | New — prefill proxy `GET /api/job-radar/jobs/{id}` | 2 | ✅ |
| `api/main.py` | Register the job_radar router | 2 | ✅ |
| `api/routers/runs.py` | `POST /api/runs` `source`/`job_id` → fetch JD + store ref; detail redaction | 2 | ✅ |
| `api/run_meta.py` | `job_radar_source` write-once sidecar field | 2 | ✅ |
| `api/archive.py` | Surface `job_radar_source`; redact in public view | 2 | ✅ |
| `frontend/src/lib/api.ts` | `JobRadarSource`/`JobRadarPrefill` types, `jobRadarPrefill()`, `startRun` ref | 2 | ✅ |
| `frontend/src/pages/RunPage.tsx` | Read `?source=job_radar&job_id=`, prefill, pass ref | 2 | ✅ |
| `frontend/src/components/OutputPanel.tsx` | "From Job Radar: …" provenance line (owner) | 2 | ✅ |
| `.env.example` | `JOB_RADAR_API_URL=` | 2 | ✅ |
| `tailor/phases/phase0_jd_analysis.py` | Phase 4 redesign — TBD | 4 | 🔄 |
| `api/job_radar.py` | `post_results_to_job_radar()` — sync httpx, fire-and-forget | 3 | ✅ |
| `api/runner.py` | Read metrics from checkpoints + fire callback after `run_complete` | 3 | ✅ |
| `api/routers/runs.py` | Pass `output_dir` to `launch_run` so meta dir + callback dir match | 3 | ✅ |
| `frontend/src/lib/api.ts` | `job_radar_linked` SSE event type | 3 | ✅ |
| `frontend/src/pages/RunPage.tsx` | Hold EventSource open 8s for JR runs; show ✓/⚠ indicator | 3 | ✅ |
| `tests/test_job_radar_callback.py` | New — 7 unit tests for callback + metric extraction | 3 | ✅ |
| `.env.example` | `JOB_RADAR_SERVICE_KEY=` + `CV_TAILOR_BASE_URL=` | 3 | ✅ |

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
- Cross-system observability (Langfuse): see `cv-tailor/docs/SPEC_LANGFUSE_INSTRUMENTATION.md`
  (cv-tailor instrumentation ✅ built; Job Radar instrumentation pending) — the evidence layer
  for the §7 redesign.
ENDOFFILE