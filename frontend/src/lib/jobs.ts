// Shared orderings, labels, and the filter/sort logic — ported from the Phase 5
// ui/app.js so the React views render the same funnel order and badges.
import type { Job } from "@/lib/api";

// Canonical orderings (mirror models/record.py enums) so empty buckets still render in a
// sensible order and the pipeline lanes read like a funnel.
export const FIT_LABELS = [
  "strong_fit", "good_fit", "stretch", "interview_practice", "income_bridge", "blocked_fit",
];
export const STATUS_ORDER = [
  "new", "review", "shortlisted", "applied", "interviewing", "offer", "rejected", "archived",
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
}

export function emptyFilters(): Filters {
  return {
    search: "", fitMin: 1, fitMax: 10, priMin: 1, priMax: 10, locWorkable: false,
    fitLabels: new Set(), statuses: new Set(), domains: new Set(), roles: new Set(),
  };
}

export function applyFilters(records: Job[], f: Filters): Job[] {
  return records.filter((r) => {
    if (r.fit_score < f.fitMin || r.fit_score > f.fitMax) return false;
    if (r.priority_score < f.priMin || r.priority_score > f.priMax) return false;
    if (f.locWorkable && r.location_workable !== "yes") return false;
    if (f.fitLabels.size && !f.fitLabels.has(r.fit_label)) return false;
    if (f.statuses.size && !f.statuses.has(r.application_status)) return false;
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
