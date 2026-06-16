# SPEC_ACTIVE_COMPANY_FILTER.md
## Active Application Company Filter

**Status:** ✅ Built (2026-06-16) — frontend filter + `applied_elsewhere_same_company`
REJECTION_REASON value. Deviation 52.
**Scope:** Frontend filter + one new REJECTION_REASON value
**Last updated:** 2026-06-16

> **Build note (2026-06-16):** Shipped as specced. The filter logic lives in
> `frontend/src/lib/jobs.ts` (`getActiveCompanies`, `activeCompanyHiddenCounts`,
> `applyFilters`), the toggle in `Sidebar.tsx` (default on, `localStorage`
> `jr_hide_active_companies`), the detail-panel context + will-not-apply pre-select in
> `DetailPanel.tsx` (`activeCompanies` threaded from `App.tsx`). Per `frontend/CLAUDE.md`
> there is **no JS test toolchain**, so the §9 `getActiveCompanies`/`applyFilters` unit
> tests were verified by `tsc -b` + manual browser check rather than added as JS tests
> (same posture as deviation 51); the §9 vocab test ships as pytest
> (`test_applied_elsewhere_in_rejection_reason` in `test_record.py` + `test_api.py`).

---

## 1. Problem

As the corpus grows and companies post multiple roles, Browse and Pipeline
fill up with roles at companies where you already have an active
application. You end up manually declining them one by one with `will_not_apply`
even though the real reason is simply "I'm already in play here."

This creates noise in the `will_not_apply` pile — the Writer cluster is
a clear example: 4 Writer roles declined as `other` because you applied
to the 5th. These aren't real rejections, they're noise from a corpus
that monitors multiple roles per company.

---

## 2. Solution: Browse/Pipeline filter toggle

Add a toggle in the filter sidebar:

```
☑ Hide companies with active applications
```

When enabled: any role from a company where **any other role** currently
has `applied` or `interviewing` status is hidden from Browse and Pipeline.

The filter operates at the **company level**, not the role level — if
you're in play at Writer, all other Writer roles disappear from the
default view. The one you applied to remains visible.

---

## 3. Logic

### Active company detection

A company is "active" if any role at that company has an effective status
of `applied` or `interviewing` with an `applied` event within the last
**14 days**.

```typescript
function getActiveCompanies(jobs: Job[]): Set<string> {
  const active = new Set<string>()
  const cutoff = Date.now() - 14 * 24 * 60 * 60 * 1000

  for (const job of jobs) {
    const status = effectiveStatus(job)
    if (status === 'applied' || status === 'interviewing') {
      const appliedAt = job.application_date
        ? new Date(job.application_date).getTime()
        : null
      if (appliedAt && appliedAt > cutoff) {
        active.add(job.company.toLowerCase().trim())
      }
    }
  }
  return active
}
```

### Filter application

```typescript
function applyActiveCompanyFilter(jobs: Job[], activeCompanies: Set<string>): Job[] {
  return jobs.filter(job => {
    const status = effectiveStatus(job)
    // Never hide the role you actually applied to
    if (status === 'applied' || status === 'interviewing') return true
    // Hide other roles at active companies
    return !activeCompanies.has(job.company.toLowerCase().trim())
  })
}
```

**Important:** the role you applied to is always visible — only the
sibling roles at the same company are hidden. You can still see your
active application and track it through the pipeline.

---

## 4. UI

### Filter sidebar

Add below the existing status filter:

```
─── Company filters ──────────────────────────
☑ Hide companies with active applications
  (roles at Writer, Anthropic, etc. hidden
   while applications are in progress)
```

Default: **on**. Most of the time you want the noise gone. Toggle off
when you want to see the full picture (e.g. reviewing all Writer roles
together).

Show a small count hint when active:
```
☑ Hide companies with active applications (3 companies, 8 roles hidden)
```

### Persistence

Store the toggle state in `localStorage` under `jr_hide_active_companies`
so it survives page reloads. Default to `true` on first load.

---

## 5. 14-day window rationale

14 days covers:
- The typical response window after applying (1–2 weeks)
- The gap between applying and first interview
- Enough time to not accidentally re-engage a company mid-process

After 14 days with no `interviewing` event, the filter releases and
sibling roles reappear. If you move to `interviewing`, the clock resets
to 14 days from that event.

The window is not configurable in v1 — add a settings option later if
needed.

---

## 6. New REJECTION_REASON value

Add `applied_elsewhere_same_company` to `REJECTION_REASON` in
`models/record.py`:

```python
REJECTION_REASON = frozenset({
    "wrong_level",
    "wrong_function",
    "too_salesy",
    "too_research_heavy",
    "too_delivery_consulting",
    "domain_not_interesting",
    "company_not_fit",
    "seniority_mismatch",
    "location_mismatch",
    "requirement_mismatch",
    "applied_elsewhere_same_company",  # new
    "other",
})
```

When you do manually decline a sibling role (e.g. you want to consciously
close it out), the dropdown pre-selects `applied_elsewhere_same_company`
if the company is in the active set. Skippable as always.

---

## 7. What does NOT change

- No new API endpoints
- No backend changes
- No SQLite schema changes
- No `SCHEMA_VERSION` bump (constants only)
- The role you applied to is always visible — filter never hides active
  applications
- Terminal states (`rejected`, `will_not_apply`, `archived`) hidden by
  default as before — this filter is additive, not a replacement

---

## 8. Data availability

All data needed is already in the index:
- `job.company` — company name per role
- `job.application_status` / `effectiveStatus(job)` — current status
- `job.application_date` — derived from earliest `applied` event, already
  in the index overlay

No new fields needed.

---

## 9. Tests

- `test_get_active_companies_applied` — role with `applied` status within
  14 days → company in active set
- `test_get_active_companies_interviewing` — role with `interviewing`
  status → company in active set
- `test_get_active_companies_expired` — role applied 15 days ago → company
  NOT in active set
- `test_filter_hides_sibling_roles` — applied to Writer role A → Writer
  roles B/C hidden, role A still visible
- `test_filter_never_hides_applied_role` — the applied role itself is
  always returned
- `test_applied_elsewhere_in_rejection_reason` — new vocab value accepted
  by `POST /api/annotations`

---

## 10. Definition of Done

1. Toggle in filter sidebar, default on
2. Roles at companies with active applications hidden when toggle is on
3. The applied role itself always visible
4. Count hint shows "N companies, M roles hidden"
5. Toggle state persists in localStorage
6. `applied_elsewhere_same_company` in `REJECTION_REASON` vocab
7. Dropdown pre-selects it when declining a sibling of an active application
8. 14-day window releases the filter when no active status remains
9. All existing tests pass + new filter tests pass
10. `tsc -b` clean

---

## 12. Detail panel — application context

Two pieces of contextual information shown in the detail panel summary
card, below the fit score and status line:

**On the role you applied to** (`effectiveStatus === 'applied'` or
`'interviewing'`):
```
Applied: 2026-06-12
```
Derived from `job.application_date` (already in the index overlay).

**On sibling roles** (different role, same company, active application
exists elsewhere at that company):
```
Active application at Writer
```
Subtle secondary text — not a warning, just context. Only shown when the
active company filter is in effect (i.e. `getActiveCompanies()` includes
this company) AND this specific role is not the applied one.

Neither is shown for roles at companies with no active applications.

---

## 13. Future enhancements

- Configurable window (7 / 14 / 30 days) in settings
- "Show hidden roles" expandable section at the bottom of Browse so you
  can see what's being filtered without toggling off
- Extend to `shortlisted` status (if you shortlisted a role at a company,
  suppress other roles there too) — more aggressive, opt-in
