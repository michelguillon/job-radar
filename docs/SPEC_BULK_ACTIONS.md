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

## 3. UX flow

### Step 1 — Selection

Checkboxes appear on each Browse row when hovering or when any box is
already ticked. Header row has a "Select all filtered" checkbox.

```
☐  Palantir    Deployment Strategist           strong_fit  10  new
☐  Palantir    Regional Director EMEA          good_fit     8  new
☐  Palantir    Enterprise Account Executive    stretch      6  review
☐  Palantir    Sr Solutions Engineer           strong_fit  10  applied
```

"Select all filtered" selects every role currently visible in Browse
(respects active filters — not every role in the corpus).

Selection state is local to the session — cleared on page reload or
filter change.

### Step 2 — Bulk action bar

When ≥1 role is selected, a bulk action bar appears at the bottom of
the screen (sticky, above the footer):

```
─── 3 selected ──────────────────────────────────────────────────
[Override fit ▾]  [Set status ▾]  [Flag scoring issue ▾]  [Add note ▾]
                                                            [Deselect all]
```

Each button opens an inline form — identical to the single-role detail
panel forms.

### Step 3 — Fill in the action

**Override fit:**
```
Override fit label for 3 roles
Label:  [strong_fit ▾]
Reason: [                              ]  (optional)
[Preview →]
```

**Set status:**
```
Set status for 3 roles
Status: [will_not_apply ▾]
Rejection reason: [requirement_mismatch ▾]  ← shown when will_not_apply
[Preview →]
```

**Flag scoring issue:**
```
Flag scoring issue for 3 roles
Type:     [domain_incorrect ▾]
Field:    [domain             ]
Observed: [                   ]
Expected: [                   ]
Reason:   [FinTech domain preferred requirement — not a hard blocker but
           consistent pattern across all Palantir roles]
[Preview →]
```

**Add note:**
```
Add note to 3 roles
Note: [                              ]
[Preview →]
```

### Step 4 — Confirmation screen

Before executing, show a confirmation screen listing every selected role
with what will happen to it:

```
─── Confirm bulk action ──────────────────────────────────────────

Action: Set status → will_not_apply
Reason: requirement_mismatch
Note:   —

3 roles will be updated · 1 will be skipped

✓ Palantir    Deployment Strategist      new → will_not_apply
✓ Palantir    Regional Director EMEA     new → will_not_apply
✓ Palantir    Enterprise AE              review → will_not_apply
⚠ Palantir    Sr Solutions Engineer      SKIPPED — already applied

[← Back]  [Apply to 3]  [Cancel]
```

**Skip logic (permissive):**
- `will_not_apply` / `archive` skipped if current status is `applied`,
  `interviewing`, or `offer` — don't accidentally discard active
  applications
- `review` / `shortlist` skipped if current status is already further
  advanced
- Fit override and scoring flags: never skipped — always safe to apply

"Back" returns to Step 3 with all form values preserved.
"Cancel" clears selections and dismisses.
"Apply to N" shows the count of roles actually being updated (not total
selected).

### Step 5 — Execution + toast

Execute each action as N individual API calls (same endpoints as the
detail panel — `POST /api/status`, `POST /api/fit-override`,
`POST /api/annotations`, `POST /api/note`). Parallel where safe,
sequential for status+outcome combos.

On completion:
```
✓ 3 roles updated  (1 skipped)
```

Toast dismisses after 4 seconds. Browse re-fetches index. Selections
cleared.

On partial failure (some API calls failed):
```
⚠ 2 of 3 roles updated — 1 failed
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

## 8. Definition of Done

1. Checkboxes on Browse rows, "Select all filtered" in header
2. Bulk action bar appears when ≥1 role selected
3. All four actions available: fit override, status, scoring flag, note
4. Confirmation screen lists every role with outcome (updated / skipped)
5. "Apply to N" count reflects skips
6. "Back" preserves form state
7. Execution fans out individual API calls per role
8. Toast shows updated / skipped counts
9. Browse re-fetches after execution
10. Filter change clears selection with toast
11. All existing tests pass + new bulk action tests
12. `tsc -b` clean

---

## 9. Tests

- `test_select_all_filtered_respects_filters` — only visible roles selected
- `test_skip_logic_applied_role` — applied role skipped for will_not_apply
- `test_skip_logic_fit_override_never_skipped` — fit override applies to all
- `test_bulk_status_fans_out_individual_calls` — N roles → N POST /api/status calls
- `test_confirmation_screen_shows_skips` — skipped roles shown with reason
- `test_filter_change_clears_selection`
