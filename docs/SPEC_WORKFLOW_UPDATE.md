# SPEC_WORKFLOW_UPDATE.md
## Job Radar — Workflow Status Redesign

**Status:** ✅ **Built** (2026-06-14). See SPEC §7.2 + §10.10 item 8 and
LEARNINGS. Deviations from this spec during the build are noted inline below
(search "BUILD NOTE").
**Trigger:** Current `archived` status is doing too many jobs — stale
roles, deliberate no-decisions, and withdrawals are all conflated.
**Last updated:** 2026-06-14

---

## 1. Problem

The current 8-state vocabulary (`new → review → shortlisted → applied →
interviewing → offer → rejected → archived`) has two gaps:

1. **No "I decided no"** — roles you consciously decided not to pursue
   end up in `archived` alongside truly stale roles. These are
   fundamentally different decisions.

2. **Controls don't reflect context** — every status shows the same
   buttons regardless of what makes sense next. Moving from `review`
   to `applied` requires going through `shortlist` even if you want to
   apply immediately.

---

## 2. New status vocabulary (9 states)

| Status | Meaning | Initiated by |
|---|---|---|
| `new` | Just ingested or manually added | System |
| `review` | Looked at, might be interesting, needs more thought | You |
| `shortlist` | Like it, preparing docs | You |
| `applied` | Application sent | You |
| `interviewing` | Active interview process in progress | You |
| `offer` | Offer received | Them |
| `rejected` | They said no (any stage) or no response after time | Them |
| `will_not_apply` | Conscious decision not to pursue | You |
| `archived` | Stale, old, never got to a decision | Time / you |

**Key distinction:**
- `rejected` = external outcome (they decided)
- `will_not_apply` = internal decision (you decided)
- `archived` = passive cleanup (time / indifference)

These three must never be conflated.

---

## 3. Controls per status

Only contextually relevant buttons shown. No button that doesn't make
sense for the current state.

```
new            → [Review] [Shortlist] [Applied] [Will not apply] [Archive]
review         → [Shortlist] [Applied] [Will not apply] [Archive]
shortlist      → [Applied] [Will not apply] [Archive]
applied        → [Interviewing] [Rejected] [Withdraw]
interviewing   → [Offer] [Rejected] [Withdraw]
offer          → outcome: [Accepted] [Declined]
rejected       → [Archive]
will_not_apply → [Archive] [Restore to new]
archived       → [Restore to new]
```

**Notes:**
- `review → [Applied]` is a direct path — no forced shortlist if you
  want to apply immediately
- `Withdraw` is an action, not a status — it moves to `will_not_apply`
  with `withdrew` pre-selected as rejection reason
- `will_not_apply → [Restore to new]` only visible when you've
  filtered to show that state (hidden by default) — you've deliberately
  gone looking at your "no" pile to reconsider
- `archived → [Restore to new]` same — escape hatch when filtered in

---

## 4. Rejection reason integration per terminal action

Three different UX approaches based on who initiated the decision:

### `Will not apply` button
- Rejection reason dropdown appears pre-expanded below the button
- Uses the `REJECTION_REASON` vocabulary:
  `wrong_level | wrong_function | too_salesy | too_research_heavy |
  too_delivery_consulting | domain_not_interesting | company_not_fit |
  seniority_mismatch | requirement_mismatch | location_mismatch | other`
  (`requirement_mismatch` added 2026-06-14 from real use — under-qualified on a hard
  requirement, e.g. technical depth / experience / specific skills; constants-only)
- Skippable — can save without selecting
- If selected: `POST /api/annotations` with `annotation_type:
  "rejection_reason"`, same as existing annotation path

### `Withdraw` button
- Pre-selects `withdrew` in the rejection reason dropdown
- Skippable
- Moves status to `will_not_apply`

> **BUILD NOTE.** `withdrew` is an `OUTCOME`, not a `REJECTION_REASON`, so it can't be
> posted as the annotation `reason` (the API validates `rejection_reason` against
> `REJECTION_REASON` → 422). As built, `withdrew` is the dropdown's default sentinel
> option: the withdrawal is captured structurally via `POST /api/outcome {withdrew}` (plus
> `POST /api/status {will_not_apply}`), and a `rejection_reason` annotation is posted **only**
> if the owner changes the selection to a real `REJECTION_REASON`. Net: "pre-selects withdrew,
> skippable" holds and nothing invalid ever reaches the backend.

### `Rejected` button (employer-initiated)
- Free text field: "What happened?" — company feedback, stage reached,
  or "No response after X weeks"
- No structured vocabulary — this is qualitative external feedback
- Stored via `POST /api/outcome` with `outcome_notes` (already exists)
- Optional date field: "Date rejected / last contact"

---

## 5. Default visibility in Browse and Pipeline

| Visible by default | Hidden by default (toggle in filter) |
|---|---|
| `new` | `rejected` |
| `review` | `will_not_apply` |
| `shortlist` | `archived` |
| `applied` | |
| `interviewing` | |
| `offer` | |

The three terminal states are hidden by default — no graveyard
cluttering the active pipeline. Tick them in the Status filter to
review them.

`will_not_apply` hidden by default: you made a decision, you don't
need it in your face every time. If you want to reconsider, actively
filter for it.

---

## 6. Pipeline lane order

```
offer
interviewing
applied
shortlist
review
new
─────────── (separator — hidden by default) ───────────
rejected
will_not_apply
archived
```

Active funnel at the top (furthest progressed first), passive/terminal
below the separator and hidden unless toggled.

---

## 7. `effectiveStatus()` update

The `effectiveStatus()` function (derives display status from outcome
at read time) needs updating for the new `will_not_apply` state:

```typescript
function effectiveStatus(job: Job): string {
  const outcome = job.outcome
  if (outcome === 'withdrew' || outcome === 'offer_declined')
    return 'will_not_apply'
  if (outcome?.startsWith('rejected_'))
    return 'rejected'
  if (outcome === 'offer_accepted')
    return 'offer'
  return job.application_status
}
```

---

## 8. Models / constants changes

### `APPLICATION_STATUS` (models/record.py)

Add `will_not_apply`:

```python
APPLICATION_STATUS = frozenset({
    "new", "review", "shortlisted", "applied",
    "interviewing", "offer", "rejected",
    "will_not_apply",   # new
    "archived"
})
```

**Note on `shortlisted` vs `shortlist`:** the current enum uses
`shortlisted` (past tense). The UI label is "Shortlist" (verb). Keep
`shortlisted` in the enum for backwards compatibility — the UI button
label is cosmetic.

### `OUTCOME` — no changes needed

`withdrew` already exists. `will_not_apply` status is derived from
`withdrew` outcome via `effectiveStatus()` — no new outcome values.

---

## 9. API changes

### `POST /api/status`

Add `will_not_apply` to the validated `APPLICATION_STATUS` values.
No other endpoint changes — `will_not_apply` is a status like any other,
set via the existing status endpoint.

### `POST /api/outcome` — no changes

Already handles `withdrew`. The Withdraw button POSTs status
`will_not_apply` + outcome `withdrew` in two calls (same pattern as
existing rejected flow).

---

## 10. What does NOT change

- `OUTCOME` vocabulary — unchanged
- `REJECTION_REASON` vocabulary — unchanged (reused for will_not_apply)
- `activity_log` schema — unchanged (append-only events)
- SQLite schema — `will_not_apply` is a valid `APPLICATION_STATUS`
  value, no migration needed
- Scorer, pipeline, collection — untouched
- `SCHEMA_VERSION` — constants only, no bump

---

## 11. Definition of Done

1. `APPLICATION_STATUS` includes `will_not_apply`
2. Controls per status match §3 exactly — no button shown that doesn't
   make contextual sense
3. `Will not apply` shows pre-expanded rejection reason dropdown,
   skippable
4. `Withdraw` pre-selects `withdrew`, skippable, moves to
   `will_not_apply`
5. `Rejected` shows free text field for feedback/notes
6. Terminal states (`rejected`, `will_not_apply`, `archived`) hidden
   by default in Browse and Pipeline
7. `will_not_apply` and `archived` show `[Restore to new]` when
   filtered in
8. `effectiveStatus()` handles `will_not_apply` correctly
9. Pipeline lane order matches §6
10. All existing tests pass + new tests for `will_not_apply` state
11. `tsc -b` clean

> **BUILD NOTE (tests).** `effectiveStatus()` is a frontend TS function and the project has
> no JS test toolchain (frontend/CLAUDE.md) — the two `test_effective_status_*` cases from the
> build prompt are covered by `tsc -b` + manual browser verification, not pytest. Backend
> coverage that *does* run: `test_will_not_apply_in_application_status` +
> `test_will_not_apply_is_a_valid_status_event` (test_record.py),
> `test_status_will_not_apply_accepted` + `test_status_invalid_still_rejected` (test_api.py),
> and a `will_not_apply` terminal-transition case (test_track.py). The detail panel's manual
> **Outcome** dropdown (deviation 32) was removed — outcome recording is now driven by the
> contextual Rejected/Withdraw/Accepted/Declined buttons.
