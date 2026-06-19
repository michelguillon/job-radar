// Bulk actions in Browse (SPEC_BULK_ACTIONS) — pure logic, kept out of the components so it
// stays testable-shaped (the standing "no JS test toolchain" convention, frontend/CLAUDE.md +
// deviations 51f/52e, means it's verified by `tsc -b` + manual browser check, not a JS runner).
// Each bulk action fans out to the SAME per-role endpoints the detail panel uses — no bulk API.
import { api, ApiError, type Job } from "@/lib/api";
import { effectiveStatus, LABEL_TEXT } from "@/lib/jobs";

// One bulk action, mirroring the four detail-panel write controls. Status uses the restricted
// set (review / shortlisted / will_not_apply / archived) — applied/interviewing/offer are
// individual milestones, never batch decisions (SPEC §2).
export type BulkAction =
  | { kind: "fit"; fit_label: string; reason: string }
  | { kind: "status"; status: string; rejection_reason: string }
  | { kind: "flag"; annotation_type: string; field: string; observed: string; expected: string; reason: string }
  | { kind: "note"; text: string };

export type ActionKind = BulkAction["kind"];
export const ACTION_KINDS: ActionKind[] = ["fit", "status", "flag", "note"];

// The status values offered in bulk + their display labels (real models/record.py values).
export const BULK_STATUSES: Array<{ value: string; label: string }> = [
  { value: "review", label: "Review" },
  { value: "shortlisted", label: "Shortlist" },
  { value: "will_not_apply", label: "Will not apply" },
  { value: "archived", label: "Archive" },
];

// Forward-lane progression rank (terminal states are deliberately absent — they're sinks, not
// points on the ladder, so the "more advanced than target" rule never fires against them).
const PROGRESS_RANK: Record<string, number> = {
  new: 0, review: 1, shortlisted: 2, applied: 3, interviewing: 4, offer: 5,
};
const ACTIVE_STATUSES = new Set(["applied", "interviewing", "offer"]);

// Why a status change would be skipped for this role, or null if it applies. Permissive: only
// status changes can skip — fit override / flag / note are always safe to apply (SPEC §3).
export function statusSkipReason(job: Job, target: string): string | null {
  const cur = effectiveStatus(job);
  if (cur === target) return "already at this status";
  // Don't discard an in-flight application by archiving / declining it in bulk.
  if ((target === "will_not_apply" || target === "archived") && ACTIVE_STATUSES.has(cur)) {
    return "already applied — won't archive active application";
  }
  // Don't walk a role backwards (e.g. set `review` on an `applied` role).
  const curRank = PROGRESS_RANK[cur];
  const targetRank = PROGRESS_RANK[target];
  if (curRank !== undefined && targetRank !== undefined && curRank > targetRank) {
    return "status more advanced";
  }
  return null;
}

// Human summary of the action for the confirmation header.
export function actionSummary(action: BulkAction): string {
  switch (action.kind) {
    case "fit": return `Override fit → ${LABEL_TEXT[action.fit_label] || action.fit_label}`;
    case "status": return `Set status → ${action.status.replace(/_/g, " ")}`;
    case "flag": return `Flag scoring issue · ${action.annotation_type}`;
    case "note": return "Add note";
  }
}

// Per-row "current → new" text for the confirmation list (the part after the company/title).
export function rowOutcomeText(action: BulkAction, job: Job): string {
  switch (action.kind) {
    case "status": return `${effectiveStatus(job)} → ${action.status}`;
    case "fit": return `${LABEL_TEXT[job.fit_label] || job.fit_label} → ${LABEL_TEXT[action.fit_label] || action.fit_label}`;
    case "flag": return `flag · ${action.annotation_type}`;
    case "note": return "add note";
  }
}

// The minimal slice of the API client the executor needs — injectable so the execution logic
// can be exercised in isolation (matches `api`'s shape).
export interface BulkApi {
  setFitOverride: typeof api.setFitOverride;
  setStatus: typeof api.setStatus;
  flagAnnotation: typeof api.flagAnnotation;
  addNote: typeof api.addNote;
}

export type RoleResult = "updated" | "skipped" | "failed";

// Apply one action to one role. A duplicate annotation (409) counts as skipped, not failed —
// the flag already exists, which is fine (SPEC §5). Any other error → failed.
export async function executeRole(action: BulkAction, job: Job, client: BulkApi = api): Promise<RoleResult> {
  try {
    switch (action.kind) {
      case "fit":
        await client.setFitOverride(job.job_id, action.fit_label, action.reason.trim() || undefined);
        return "updated";
      case "note":
        await client.addNote(job.job_id, action.text.trim());
        return "updated";
      case "flag":
        try {
          await client.flagAnnotation({
            job_id: job.job_id,
            annotation_type: action.annotation_type,
            field: action.field.trim() || null,
            observed: action.observed.trim(),
            expected: action.expected.trim(),
            reason: action.reason.trim(),
          });
          return "updated";
        } catch (e) {
          if (e instanceof ApiError && e.status === 409) return "skipped"; // duplicate flag
          throw e;
        }
      case "status": {
        await client.setStatus(job.job_id, action.status);
        // will_not_apply + a real reason → also record the structured rejection_reason. A 409 on
        // this secondary write is benign (the status move already succeeded) → still "updated".
        if (action.status === "will_not_apply" && action.rejection_reason) {
          try {
            await client.flagAnnotation({
              job_id: job.job_id,
              annotation_type: "rejection_reason",
              field: null,
              observed: [job.scorer_fit_label, String(job.scorer_fit_score)],
              expected: [],
              reason: action.rejection_reason,
            });
          } catch (e) {
            if (!(e instanceof ApiError && e.status === 409)) throw e;
          }
        }
        return "updated";
      }
    }
  } catch {
    return "failed";
  }
}

// ---- Composite (multi-action) layer ---------------------------------------------
// The composer lets the owner stage several actions (fit + status + flag + note) and apply them
// all in one pass (SPEC_BULK_ACTIONS, multi-action revision). Skips stay per (role, action) —
// only status skips — so a role can take the fit override while its status change is skipped.

export interface CompositeItem { action: BulkAction; skipReason: string | null; }
export interface CompositeRolePlan { job: Job; items: CompositeItem[] }

// Per-role plan across every staged action, for the confirmation screen.
export function planComposite(actions: BulkAction[], jobs: Job[]): CompositeRolePlan[] {
  return jobs.map((job) => ({
    job,
    items: actions.map((action) => ({
      action,
      skipReason: action.kind === "status" ? statusSkipReason(job, action.status) : null,
    })),
  }));
}

export interface CompositeOutcome {
  updated: number;       // (role, action) operations that succeeded
  skipped: number;       // operations skipped (status skip plan) + 409 duplicates
  failed: number;        // operations that errored
  rolesAffected: number; // distinct roles that took at least one successful change
  totalOps: number;      // operations actually attempted (excludes plan skips) — drives progress
}

// Apply every staged action across every role. Plan-skipped (role, action) pairs are dropped up
// front; the rest fan out concurrently (independent per-role writes, SPEC §5).
export async function executeComposite(
  actions: BulkAction[],
  jobs: Job[],
  onProgress?: (done: number, total: number) => void,
  client: BulkApi = api,
): Promise<CompositeOutcome> {
  const ops: Array<{ job: Job; action: BulkAction }> = [];
  let planSkipped = 0;
  for (const job of jobs) {
    for (const action of actions) {
      const skip = action.kind === "status" ? statusSkipReason(job, action.status) : null;
      if (skip) { planSkipped++; continue; }
      ops.push({ job, action });
    }
  }
  let done = 0;
  const results = await Promise.all(
    ops.map((op) =>
      executeRole(op.action, op.job, client).then((r) => {
        onProgress?.(++done, ops.length);
        return { jobId: op.job.job_id, r };
      }),
    ),
  );
  const updated = results.filter((x) => x.r === "updated");
  return {
    updated: updated.length,
    skipped: planSkipped + results.filter((x) => x.r === "skipped").length,
    failed: results.filter((x) => x.r === "failed").length,
    rolesAffected: new Set(updated.map((x) => x.jobId)).size,
    totalOps: ops.length,
  };
}
