// Company-universe vocabularies + value→class maps (SPEC_COMPANY_SEEDS_DB §5). Mirrors the
// company_seeds.yaml header vocabulary. Style decided in JS (full Tailwind class strings), never
// global CSS classes — same convention as lib/ui.ts.
import type { Company } from "@/lib/api";

// domain vocabulary (company_seeds.yaml header). Free text is still allowed, but these drive the
// edit dropdown so the common values are one click away.
export const DOMAIN_VOCABULARY = [
  "frontier_ai",
  "ai_application_platform",
  "ai_data_platform",
  "ai_infrastructure",
  "developer_tooling",
  "fintech_infrastructure",
  "fintech_platform",
  "adtech_martech",
  "identity_security",
  "enterprise_software",
  "semiconductor_ai_compute",
  "strategic_ai_delivery",
  "retail_media_data",
  "customer_data_martech",
  "mlops_observability",
  "enterprise_crm_platform",
] as const;

export const FIT_HYPOTHESES = ["high", "medium", "low", "watch_only"] as const;
export const ACTIONS = [
  "keep", "promote", "downgrade", "pause", "remove", "investigate_ats", "review_manually",
] as const;
export const ATS_OPTIONS = ["greenhouse", "ashby", "lever", "manual", "unknown"] as const;

// fit_hypothesis → badge classes: high=green, medium=amber, low=grey, watch_only=blue.
const FIT_BADGE: Record<string, string> = {
  high: "bg-[#e6f3ec] text-[#1f7a45]",
  medium: "bg-[#f6e9d8] text-[#8a5a14]",
  low: "bg-line-soft text-ink-soft",
  watch_only: "bg-[#eaf1ff] text-[#2f5fd0]",
};
export function fitHypothesisClass(v: string | null): string {
  return (v && FIT_BADGE[v]) ?? "bg-line-soft text-ink-soft";
}

// action → badge classes: keep=default, pause=amber, remove=red, investigate_ats=orange.
const ACTION_BADGE: Record<string, string> = {
  keep: "bg-line-soft text-ink-soft",
  promote: "bg-[#e6f3ec] text-[#1f7a45]",
  downgrade: "bg-[#f6e9d8] text-[#8a5a14]",
  pause: "bg-[#f6e9d8] text-[#8a5a14]",
  remove: "bg-[#f3dede] text-[#9a3636]",
  investigate_ats: "bg-[#fbe7d4] text-[#b4540f]",
  review_manually: "bg-[#fbe7d4] text-[#b4540f]",
};
export function actionClass(v: string): string {
  return ACTION_BADGE[v] ?? "bg-line-soft text-ink-soft";
}

// A company is visually muted (paused / removed) but never hidden — still in the table.
export function isMuted(c: Company): boolean {
  return c.action === "pause" || c.action === "remove";
}

export type CompanySortKey = "name" | "domain" | "fit_hypothesis" | "action";

const FIT_RANK: Record<string, number> = { high: 0, medium: 1, low: 2, watch_only: 3 };

export function sortCompanies(rows: Company[], key: CompanySortKey, dir: "asc" | "desc"): Company[] {
  const mul = dir === "asc" ? 1 : -1;
  const val = (c: Company): string | number => {
    if (key === "fit_hypothesis") return FIT_RANK[c.fit_hypothesis ?? ""] ?? 99;
    return (c[key] ?? "").toString().toLowerCase();
  };
  return [...rows].sort((a, b) => {
    const va = val(a), vb = val(b);
    if (va < vb) return -1 * mul;
    if (va > vb) return 1 * mul;
    return a.name.toLowerCase().localeCompare(b.name.toLowerCase());
  });
}

export function filterCompanies(rows: Company[], search: string): Company[] {
  const q = search.trim().toLowerCase();
  if (!q) return rows;
  return rows.filter((c) => c.name.toLowerCase().includes(q));
}
