// Shared orderings, labels, and the filter/sort logic — ported from the Phase 5
// ui/app.js so the React views render the same funnel order and badges.
import type { Job } from "@/lib/api";

// Canonical orderings (mirror models/record.py enums) so empty buckets still render in a
// sensible order and the pipeline lanes read like a funnel.
export const FIT_LABELS = [
  "strong_fit", "good_fit", "stretch", "interview_practice", "income_bridge", "blocked_fit",
];
export const STATUS_ORDER = [
  "new", "review", "shortlisted", "applied", "interviewing", "offer",
  // terminal — hidden by default (SPEC_WORKFLOW_UPDATE §5)
  "rejected", "will_not_apply", "archived",
];
// Pipeline lane order: most-progressed/active stages on top, the big untriaged "new"
// backlog below them, terminal states at the bottom (the funnel STATUS_ORDER reads the
// other way and is still used by the stats bar + filters). SPEC_WORKFLOW_UPDATE §6.
export const PIPELINE_ORDER = [
  "offer", "interviewing", "applied", "shortlisted", "review", "new",
  // terminal — hidden by default, shown when filtered in
  "rejected", "will_not_apply", "archived",
];
export const LABEL_TEXT: Record<string, string> = {
  strong_fit: "strong", good_fit: "good", stretch: "stretch",
  interview_practice: "practice", income_bridge: "bridge", blocked_fit: "blocked",
};

export interface Filters {
  search: string;
  fitMin: number; fitMax: number;
  priMin: number; priMax: number;
  locWorkable: boolean;
  fitLabels: Set<string>;
  statuses: Set<string>;
  domains: Set<string>;
  roles: Set<string>;
  hideActiveCompanies: boolean;
}

// Active-company filter persistence (SPEC_ACTIVE_COMPANY_FILTER §4). Default on — most of
// the time you want sibling roles at companies you're already in play with gone.
export const HIDE_ACTIVE_KEY = "jr_hide_active_companies";
export function readHideActivePref(): boolean {
  try {
    const v = localStorage.getItem(HIDE_ACTIVE_KEY);
    return v === null ? true : v === "true";
  } catch {
    return true;
  }
}
export function writeHideActivePref(on: boolean): void {
  try {
    localStorage.setItem(HIDE_ACTIVE_KEY, String(on));
  } catch {
    /* storage unavailable (private mode) — toggle still works for the session */
  }
}

export function emptyFilters(): Filters {
  return {
    search: "", fitMin: 1, fitMax: 10, priMin: 1, priMax: 10, locWorkable: false,
    fitLabels: new Set(), statuses: new Set(), domains: new Set(), roles: new Set(),
    hideActiveCompanies: readHideActivePref(),
  };
}

// Terminal/dead lanes hidden from the default dashboard — they're done, not actionable.
// Tick them in the Status filter to review them. Three distinct terminal states that must
// never be conflated (SPEC_WORKFLOW_UPDATE §2): rejected = they decided, will_not_apply =
// you decided, archived = passive cleanup.
export const TERMINAL_STATUSES = new Set(["rejected", "will_not_apply", "archived"]);

// A recorded outcome is the stronger signal of where a role actually is than the status
// lane (which a CLI --outcome write, or a missed UI step, may not have moved). Derive an
// effective status so a rejection never shows as "applied" anywhere (SPEC §10.10 item 5).
// A withdrawal / declined offer is an internal "no" → will_not_apply, not archived
// (SPEC_WORKFLOW_UPDATE §7).
export function effectiveStatus(job: Job): string {
  const o = job.outcome;
  if (o) {
    if (o.startsWith("rejected")) return "rejected";
    if (o === "withdrew" || o === "offer_declined") return "will_not_apply";
    if (o === "offer_accepted") return "offer";
  }
  return job.application_status;
}

// --- Active-company filter (SPEC_ACTIVE_COMPANY_FILTER) ---------------------------
// 14-day window: a company counts as "active" while an application there is recent enough to
// be in play (response window + gap before first interview). After 14 days with no movement
// the filter releases and sibling roles reappear; an `interviewing` event resets the clock.
export const ACTIVE_COMPANY_WINDOW_MS = 14 * 24 * 60 * 60 * 1000;

function companyKey(company: string): string {
  return company.toLowerCase().trim();
}

// Set of company keys (lowercased) with an `applied`/`interviewing` role inside the window.
export function getActiveCompanies(jobs: Job[]): Set<string> {
  const cutoff = Date.now() - ACTIVE_COMPANY_WINDOW_MS;
  const active = new Set<string>();
  for (const job of jobs) {
    const status = effectiveStatus(job);
    if (status === "applied" || status === "interviewing") {
      const appliedAt = job.application_date ? new Date(job.application_date).getTime() : NaN;
      if (!isNaN(appliedAt) && appliedAt > cutoff) active.add(companyKey(job.company));
    }
  }
  return active;
}

// True when this role is the active application itself (never hidden) rather than a sibling.
function isActiveRole(job: Job): boolean {
  const s = effectiveStatus(job);
  return s === "applied" || s === "interviewing";
}

// How many companies / sibling roles the active-company filter would hide — for the sidebar
// count hint. Counts across the full record set, independent of the other filters.
export function activeCompanyHiddenCounts(records: Job[]): { companies: number; roles: number } {
  const active = getActiveCompanies(records);
  const companies = new Set<string>();
  let roles = 0;
  for (const r of records) {
    if (isActiveRole(r)) continue;
    const key = companyKey(r.company);
    if (active.has(key)) { roles++; companies.add(key); }
  }
  return { companies: companies.size, roles };
}

export function applyFilters(records: Job[], f: Filters): Job[] {
  // Active companies are derived from the FULL input set (not the post-filter view) so a
  // sibling is hidden regardless of how the other filters are set (SPEC §2/§3).
  const activeCompanies = f.hideActiveCompanies ? getActiveCompanies(records) : null;
  return records.filter((r) => {
    if (r.fit_score < f.fitMin || r.fit_score > f.fitMax) return false;
    if (r.priority_score < f.priMin || r.priority_score > f.priMax) return false;
    if (f.locWorkable && r.location_workable !== "yes") return false;
    if (f.fitLabels.size && !f.fitLabels.has(r.fit_label)) return false;
    // Status filter (on the effective status): an explicit selection shows exactly those
    // (so ticking "rejected" reveals rejected); with no selection, terminal lanes hide.
    const status = effectiveStatus(r);
    if (f.statuses.size) {
      if (!f.statuses.has(status)) return false;
    } else if (TERMINAL_STATUSES.has(status)) {
      return false;
    }
    // Active-company filter: hide sibling roles at a company with an active application; the
    // applied/interviewing role itself is always visible.
    if (activeCompanies && status !== "applied" && status !== "interviewing"
        && activeCompanies.has(companyKey(r.company))) {
      return false;
    }
    if (f.domains.size && !(r.domain || []).some((d) => f.domains.has(d))) return false;
    if (f.roles.size && !(r.role_type || []).some((d) => f.roles.has(d))) return false;
    if (f.search) {
      const hay = `${r.company} ${r.title}`.toLowerCase();
      if (!hay.includes(f.search)) return false;
    }
    return true;
  });
}

export interface Sort { key: keyof Job; dir: "asc" | "desc"; }

export function sortRows(rows: Job[], { key, dir }: Sort): Job[] {
  const mul = dir === "asc" ? 1 : -1;
  return rows.slice().sort((a, b) => {
    const av = a[key], bv = b[key];
    if (typeof av === "number" && typeof bv === "number") {
      if (av !== bv) return (av - bv) * mul;
    } else {
      const c = String(av ?? "").localeCompare(String(bv ?? ""));
      if (c) return c * mul;
    }
    return (b.priority_score - a.priority_score) || a.company.localeCompare(b.company);
  });
}

export function fmtDate(s: string | null | undefined): string {
  if (!s) return "—";
  const d = new Date(s);
  return isNaN(d.getTime()) ? String(s).slice(0, 10) : d.toISOString().slice(0, 10);
}

export function listText(v: unknown): string {
  return Array.isArray(v) ? v.join(", ") : String(v ?? "");
}

// --- Application age + staleness -------------------------------------------------
export const STALE_DAYS = 21; // ~3 weeks with no movement after applying → likely dead

export function daysSince(dateStr: string | null | undefined): number | null {
  if (!dateStr) return null;
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return null;
  return Math.floor((Date.now() - d.getTime()) / 86_400_000);
}

/** An applied role with no further movement for STALE_DAYS — worth chasing or archiving.
 * Uses the effective status, so a role with a rejection outcome is never flagged stale. */
export function isStaleApplied(job: Job): boolean {
  if (effectiveStatus(job) !== "applied") return false;
  const n = daysSince(job.application_date);
  return n !== null && n >= STALE_DAYS;
}

// --- Outcomes (models/record.py OUTCOME) -----------------------------------------
export const OUTCOMES = [
  "rejected_pre_screen", "rejected_post_screen", "rejected_interview", "rejected_final",
  "offer_accepted", "offer_declined", "withdrew",
];

// Auto-pick the rejection stage from where the role currently sits in the workflow, so
// "mark rejected" captures the stage without the user hunting through the enum.
export function rejectionStageFor(status: string): string {
  switch (status) {
    case "offer": return "rejected_final";
    case "interviewing": return "rejected_interview";
    case "applied": return "rejected_post_screen";
    default: return "rejected_pre_screen";
  }
}

// Structured rejection reasons (models/record.py REJECTION_REASON) — why a role wasn't
// pursued despite its score. Recorded as a rejection_reason annotation (BACKLOG §2);
// label → value, value validated server-side for the rejection_reason type.
export const REJECTION_REASONS: Array<{ label: string; value: string }> = [
  { label: "Wrong level", value: "wrong_level" },
  { label: "Wrong function", value: "wrong_function" },
  { label: "Too sales-focused", value: "too_salesy" },
  { label: "Too research-heavy", value: "too_research_heavy" },
  { label: "Too delivery/consulting", value: "too_delivery_consulting" },
  { label: "Domain not interesting", value: "domain_not_interesting" },
  { label: "Company not a fit", value: "company_not_fit" },
  { label: "Seniority mismatch", value: "seniority_mismatch" },
  { label: "Requirement mismatch", value: "requirement_mismatch" },
  { label: "Location mismatch", value: "location_mismatch" },
  { label: "Applied elsewhere (same company)", value: "applied_elsewhere_same_company" },
  { label: "Other", value: "other" },
];

// When an outcome is recorded, the workflow lane it implies (model C keeps them separate,
// but the UI moves the lane too so the pipeline reflects reality). null = leave lane as-is.
export function statusForOutcome(outcome: string): string | null {
  if (outcome.startsWith("rejected")) return "rejected";
  if (outcome === "withdrew" || outcome === "offer_declined") return "will_not_apply";
  if (outcome === "offer_accepted") return "offer";
  return null;
}
