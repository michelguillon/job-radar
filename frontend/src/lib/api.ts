// Typed client for the Job Radar FastAPI backend (job_radar_SPEC §10.4). All calls are
// same-origin /api/* — the Vite dev server (and prod nginx) proxy them to the api container,
// so the HttpOnly jr_write capability cookie is sent automatically. credentials:"include"
// keeps the cookie flowing even when dev runs cross-port behind the proxy.

const BASE = "/api";

// Raised when an HTTP call fails; carries the status so callers can branch (401/403/404).
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

async function errorFrom(res: Response): Promise<ApiError> {
  let detail = `${res.status} ${res.statusText}`;
  try {
    const j = (await res.json()) as { detail?: string };
    if (j.detail) detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
  } catch {
    /* non-JSON error body */
  }
  return new ApiError(res.status, detail);
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { credentials: "include", cache: "no-store" });
  if (!res.ok) throw await errorFrom(res);
  return res.json() as Promise<T>;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw await errorFrom(res);
  return res.json() as Promise<T>;
}

// One denormalised index row — score ⨝ JDRecord ⨝ sidecar ⨝ activity-log projection
// (built by cli.stats.build_index_rows; the API overlays live workflow state on read).
export interface Job {
  job_id: string;
  company: string;
  title: string;
  // scoring (ApplicationRecord)
  fit_score: number;
  fit_label: string;
  fit_label_reason: string;
  priority_score: number;
  requirement_gaps: string[];
  blocking_constraints: string[];
  scored_at: string;
  profile_version: string;
  // live workflow state (activity-log projection)
  application_status: string;
  outcome: string | null;
  application_date: string | null;
  notes: string;
  // location + provenance
  location: string;
  location_workable: string;
  source_url: string;
  source_ats: string;
  tier: number | null;
  date_first_seen: string;
  raw_text: string;
  // extraction (filters + detail)
  domain: string[];
  role_type: string[];
  seniority: string;
  technical_depth: string;
  remote_policy: string;
  company_stage: string;
  company_size_signal: string;
  years_experience_required: string;
  required_technologies: string[];
  required_competencies: string[];
  nice_to_have_technologies: string[];
  nice_to_have_competencies: string[];
  delivery_motion: string[];
  leadership_geography: string[];
  culture_signals: string[];
  raw_observations: string;
}

export interface IndexStats {
  total: number;
  by_fit_label: Record<string, number>;
  by_application_status: Record<string, number>;
  fit_score_distribution: Record<string, number>;
  cost_to_date_usd: number;
}

export interface IndexResponse {
  schema_version: string | null;
  jdrecord_schema_version: string | null;
  generated_at: string | null;
  stats: IndexStats;
  records: Job[];
}

// Drives write-control rendering (job_radar_SPEC §10.5 table). configured but not
// unlocked → click shows the unlock dialog; not configured → controls hidden entirely.
export interface Capabilities {
  write_configured: boolean;
  write_unlocked: boolean;
}

export interface AnnotationPayload {
  job_id: string;
  annotation_type: string;
  field: string;
  observed: unknown;
  expected: unknown;
  reason: string;
}

export const api = {
  index: () => get<IndexResponse>("/index"),
  capabilities: () => get<Capabilities>("/capabilities"),
  health: () => get<{ status: string; service: string; records: number; last_indexed: string | null }>("/health"),

  unlock: (key: string) => post<{ write_unlocked: boolean }>("/unlock", { key }),
  lock: () => post<{ write_unlocked: boolean }>("/lock", {}),

  setStatus: (job_id: string, status: string, notes?: string) =>
    post<{ ok: boolean; status: string; warning: string | null }>("/status", { job_id, status, notes }),
  addNote: (job_id: string, text: string) => post<{ ok: boolean }>("/note", { job_id, text }),
  setTitle: (job_id: string, title: string) => post<{ ok: boolean; title: string }>("/title", { job_id, title }),
  setOutcome: (job_id: string, outcome: string, notes?: string) =>
    post<{ ok: boolean; outcome: string }>("/outcome", { job_id, outcome, notes }),
  flagAnnotation: (payload: AnnotationPayload) =>
    post<{ ok: boolean; annotation_type: string }>("/annotations", payload),
};
