# SPEC_BULK_ACTIONS.md
## Bulk Actions in Browse

**Status:** ✅ Built (frontend-only, deviation 54) — 2026-06-19
**Last updated:** 2026-06-19

> **Build note (2026-06-19).** Shipped frontend-only — no API/schema/backend change.
> Per the standing "no JS test toolchain" convention (frontend/CLAUDE.md, deviations
> 51f/52e), the §9 logic cases were **not** added as JS tests; instead the logic was
> extracted into pure functions in `frontend/src/lib/bulk.ts` (selection-independent,
> injectable-api executor) and verified by `tsc -b` + `vite build` + manual browser check.
> Refinements over the prose: (a) the whole feature is gated on `write_configured`
> (checkboxes render only when an owner write key exists — no dead affordances, SPEC §10.5);
> (b) the status dropdown posts the real enum values
> (`review`/`shortlisted`/`will_not_apply`/`archived`) under friendly labels.
>
> **UX revision — multi-action composer (supersedes §3's one-action-at-a-time flow).**
> Picking a single action then re-selecting for the next one meant several round trips. The
> bar's four buttons now each open a **tabbed composer** (tabs: Override fit / Set status /
> Flag issue / Add note). The owner stages any *combination* of the four — a tab is *included*
> when its "Apply this change" box is ticked **or** when any of its fields is edited (so fit/
> status, which have no empty state, are never applied unless intended; a • on the tab marks it
> staged, amber when it still needs required text). One **Preview →** opens a single
> confirmation that lists each role with a per-action ✓/⚠ chip, and one **Apply** fans out every
> staged action across every role. Skips remain **per (role, action)** — only status skips — so
> a role can take the fit override while its status change is skipped. See deviation 54.

---

## 1. Problem

Reviewing a company's full roster reveals patterns — a FinTech domain
requirement consistently listed as "preferred" across all roles, a
seniority level that's uniformly above profile, a domain that's never
a fit. Currently these require one-by-one action in the detail panel:
click role, set status, add reason, add note, repeat 12 times.

Bulk actions let you select multiple roles and apply the same action to
each one simultaneously — each action applied independently to each
selected job, not grouped at a company level.

---

## 2. Scope

### Actions available in bulk

All actions that are available in the single-role detail panel:

**1. Fit override** — set override label + reason (same for all selected)

**2. Workflow status** — restricted set only:
- `review`
- `shortlist`
- `will_not_apply` + rejection reason dropdown
- `archive`

Not available in bulk: `applied`, `interviewing`, `offer` — these are
individual milestones, not batch decisions.

**3. Scoring flag** — annotation type + field + reason (same for all
selected). Exactly the "flag scoring issue" form from the detail panel.

**4. Note** — free text note appended to each selected role.

---

## 3. UX flow (as built — supersedes original single-action design)

### Step 1 — Selection

Checkboxes render only when `write_configured` is true (no dead
affordances for public visitors). "Select all filtered" in the header
selects all roles currently visible after filters — not the full corpus.
Selection state is local to the session — cleared on page reload or
filter change.

```
☐  Palantir    Deployment Strategist           strong_fit  10  new
☐  Palantir    Regional Director EMEA          good_fit     8  new
☐  Palantir    Enterprise Account Executive    stretch      6  review
☐  Palantir    Sr Solutions Engineer           strong_fit  10  applied
```

### Step 2 — Bulk action bar

When ≥1 role is selected, a sticky bulk action bar appears at the
bottom of the screen:

```
─── 3 selected ──────────────────────────────────────────────────
[Override fit ▾]  [Set status ▾]  [Flag scoring issue ▾]  [Add note ▾]
                                                            [Deselect all]
```

### Step 3 — Multi-action composer (tabbed)

Each button opens a **tabbed composer** with all four actions as tabs:
`Override fit / Set status / Flag issue / Add note`.

The owner stages any **combination** of the four in one session:
- A tab is **included** (staged) when its "Apply this change" checkbox
  is ticked, or when any of its fields is edited
- `fit` and `status` tabs have no empty state — they're never applied
  unless explicitly staged
- A **•** marks a staged tab; **amber •** when required text is still
  missing
- One **Preview →** advances to the confirmation screen with all staged
  actions combined

```
┌─────────────────────────────────────────────────────────────┐
│ • Override fit  │ • Set status  │   Flag issue  │  Add note  │
├─────────────────────────────────────────────────────────────┤
│ Status: [will_not_apply ▾]                                   │
│ Rejection reason: [requirement_mismatch ▾]                   │
├─────────────────────────────────────────────────────────────┤
│                                              [Preview →]     │
└─────────────────────────────────────────────────────────────┘
```

Status dropdown posts real enum values (`review`/`shortlisted`/
`will_not_apply`/`archived`) under friendly labels.

### Step 4 — Confirmation screen

Lists every selected role with a **per-action ✓/⚠ chip** for each
staged action:

```
─── Confirm bulk actions ─────────────────────────────────────

Staged: Override fit (good_fit) · Set status (will_not_apply, requirement_mismatch)

✓ Palantir  Deployment Strategist   fit ✓  status ✓  (new → will_not_apply)
✓ Palantir  Regional Director EMEA  fit ✓  status ✓  (new → will_not_apply)
✓ Palantir  Enterprise AE           fit ✓  status ✓  (review → will_not_apply)
⚠ Palantir  Sr Solutions Engineer   fit ✓  status ⚠  SKIPPED — already applied

3 fully updated · 1 partial (fit only) · 0 failed

[← Back]  [Apply]  [Cancel]
```

**Skip logic — per (role, action), not per role:**
- Status `will_not_apply` / `archive` skipped if current status is
  `applied`, `interviewing`, or `offer`
- Status `review` / `shortlist` skipped if already more advanced
- Fit override, scoring flag, note: **never skipped**
- A role can take the fit override while its status change is skipped

"Back" returns to the composer with all staged values preserved.

### Step 5 — Execution + toast

`Promise.all()` fans out every staged action across every role. On
completion, Browse re-fetches, selections clear, toast shows summary:

```
✓ 3 roles updated  (1 partial — status skipped on 1)
```

---

## 4. Selection state and filters

**Select all filtered:** selects all roles currently visible after
applying the active status/company/fit filters. Not the full corpus —
only what's on screen. If you filter to "Palantir, new status" and
select all, you get exactly those roles.

**Filter changes clear selection:** if the user changes a filter while
roles are selected, clear the selection and show a toast: "Selection
cleared — filters changed."

**Hidden roles (terminal states):** roles hidden by the status filter
(rejected, will_not_apply, archived) are not selectable unless you
toggle them visible first.

---

## 5. API — no new endpoints

Bulk actions use the existing per-role endpoints:
- `POST /api/status` — one call per selected role
- `POST /api/fit-override` — one call per selected role
- `POST /api/annotations` — one call per selected role
- `POST /api/note` — one call per selected role

All owner-gated as normal. No bulk endpoint needed — the frontend
fans out the individual calls.

If an individual call returns 409 (duplicate annotation) — count as
skipped, not failed.

---

## 6. What does NOT change

- All existing API endpoints — unchanged
- The detail panel — unchanged
- Single-role workflow — unchanged
- Models, schema, SQLite — unchanged

---

## 7. Implementation notes

**Checkbox state:** a `selectedIds: Set<string>` in component state
(or a context if needed across views). The Browse table renders a
checkbox column when the set is non-empty or on hover.

**Confirmation screen:** a modal or a dedicated panel state, not a
separate route. Preserve the Browse view behind it so the user can see
what they selected.

**Progress during execution:** show a progress indicator during the
N API calls — "Updating 3 of 12..." — since bulk actions on a large
selection could take a few seconds.

**Skip detection:** computed in the frontend before the confirmation
screen, based on the current `effectiveStatus()` of each selected role.
No server-side skip logic needed.

---

## 8. Definition of Done — ✅ met (2026-06-19)

1. ✅ Checkboxes on Browse rows (owner-only — gated on `write_configured`)
2. ✅ "Select all filtered" in header
3. ✅ Bulk action bar appears when ≥1 role selected
4. ✅ Tabbed multi-action composer — all four actions stageable in one session
5. ✅ Tab staged indicator (• / amber •) when action is included / incomplete
6. ✅ Confirmation screen with per-action ✓/⚠ chip per role
7. ✅ Skip logic per (role, action) — status skips only; fit/flag/note never skipped
8. ✅ "Back" preserves all staged form values
9. ✅ Execution fans out via `Promise.all()` — one call per (role × action)
10. ✅ Toast shows updated / partial / skipped / failed counts
11. ✅ Browse re-fetches after execution; selections cleared
12. ✅ Filter change clears selection with toast
13. ✅ `tsc -b` + `vite build` clean

---

## 9. Tests

Per `frontend/CLAUDE.md` no-JS-test-toolchain convention (deviations
51f/52e), logic cases were not added as JS tests. Instead, skip logic
and executor were extracted into pure functions in
`frontend/src/lib/bulk.ts` and verified by `tsc -b` + `vite build` +
manual browser check. Backend tests unchanged — individual API
endpoints already covered.
