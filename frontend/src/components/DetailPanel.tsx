import { useEffect, useState } from "react";
import { api, ApiError, type Annotation, type Job } from "@/lib/api";
import { cn } from "@/lib/utils";
import { CHIP, fitBadgeClass, statusPillClass, TOAST } from "@/lib/ui";
import {
  daysSince, effectiveStatus, FIT_LABELS, fmtDate, isStaleApplied, LABEL_TEXT, listText,
  OUTCOMES, REJECTION_REASONS, rejectionStageFor, statusForOutcome,
} from "@/lib/jobs";
import { useUnlock } from "@/components/UnlockProvider";

// Centered modal — read fields plus owner-only write controls (job_radar_SPEC §10.6).
// Controls are hidden when writes aren't configured; when configured-but-locked, the first
// write opens the unlock dialog via requestUnlock(). All Tailwind, no global classes.

type Toast = { kind: "ok" | "warn" | "err"; text: string } | null;

const ANNOTATION_TYPES = [
  "role_type_incorrect", "domain_incorrect", "seniority_incorrect", "technical_depth_incorrect",
  "fit_score_disagree", "should_be_blocked", "false_block", "extraction_other",
];

function observedFor(type: string, r: Job): { field: string; observed: unknown } {
  switch (type) {
    case "role_type_incorrect": return { field: "role_type", observed: r.role_type };
    case "domain_incorrect": return { field: "domain", observed: r.domain };
    case "seniority_incorrect": return { field: "seniority", observed: r.seniority };
    case "technical_depth_incorrect": return { field: "technical_depth", observed: r.technical_depth };
    case "fit_score_disagree": return { field: "fit_score", observed: r.fit_score };
    case "should_be_blocked": return { field: "blocking_constraints", observed: r.blocking_constraints };
    case "false_block": return { field: "blocking_constraints", observed: r.blocking_constraints };
    default: return { field: "", observed: "" };
  }
}

const FIELD_INPUT = "w-full rounded-md border border-line px-[9px] py-[6px] text-[13px] focus:border-brand focus:outline-none disabled:opacity-50";
const BTN = "rounded-md border border-line bg-white px-[14px] py-[6px] text-[12.5px] font-semibold text-ink hover:border-brand hover:text-brand disabled:opacity-50";
const BTN_PRIMARY = "rounded-md border border-brand bg-brand px-[14px] py-[6px] text-[12.5px] font-semibold text-white hover:bg-[#245fd0] disabled:opacity-50";
const LABEL = "block text-[11px] text-ink-soft mb-[3px]";
const SECTION_H = "mb-[7px] text-[11px] font-bold uppercase tracking-wide text-ink-soft";

function KV({ label, value }: { label: string; value: string }) {
  if (!value) return null;
  return (<><dt className="text-ink-soft">{label}</dt><dd className="m-0">{value}</dd></>);
}
function Chips({ items, tone = "default" }: { items: string[]; tone?: keyof typeof CHIP }) {
  return (
    <div className="flex flex-wrap gap-[5px]">
      {items.map((it, i) => <span key={i} className={cn("rounded-[5px] px-2 py-[2px] text-[12px]", CHIP[tone])}>{it}</span>)}
    </div>
  );
}
function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return <div className="mt-[18px]"><h3 className={SECTION_H}>{title}</h3>{children}</div>;
}
function Pill({ status }: { status: string }) {
  return <span className={cn("inline-block rounded-[5px] px-2 py-[2px] text-[11px] font-semibold", statusPillClass(status))}>{status}</span>;
}
// cv-tailor scores are 0.0–1.0 floats on the wire (job_radar_SPEC §11.3); the UI shows + edits
// them as 0–100 percentages. Empty input → null (the field is optional, not zero).
function toPercentStr(v: number | null | undefined): string {
  return v == null ? "" : String(Math.round(v * 100));
}
function pctDisplay(v: number | null | undefined): string {
  return v == null ? "—" : `${Math.round(v * 100)}%`;
}
function toFraction(s: string): number | null {
  const t = s.trim();
  if (!t) return null;
  const n = Number(t);
  if (isNaN(n)) return null;
  return Math.max(0, Math.min(1, n / 100));
}

// cv_quality_score is the raw 0.0–10.0 rubric score — NOT a fraction. Input + display use the
// 0–10 scale directly (shown as X.X/10), unlike fit/coverage which are stored 0.0–1.0.
function qualityStr(v: number | null | undefined): string {
  return v == null ? "" : String(v);
}
function qualityDisplay(v: number | null | undefined): string {
  return v == null ? "—" : `${v}/10`;
}
function toQuality(s: string): number | null {
  const t = s.trim();
  if (!t) return null;
  const n = Number(t);
  if (isNaN(n)) return null;
  return Math.max(0, Math.min(10, n));
}

const CV_TAILOR_MODES = ["full", "targeted", "minimal"];

// CV-Tailor section (job_radar_SPEC §11.3). Read-only for everyone; the Add/Edit form is
// owner-gated (rendered only when unlocked, first write still goes through requestUnlock()).
// Records a manual snapshot of a cv-tailor run against this role — never mutates a score.
function CvTailorSection({ job, onChanged }: { job: Job; onChanged: () => Promise<void> }) {
  const { unlocked, requestUnlock } = useUnlock();
  const cv = job.cv_tailor || { has_output: false };
  // cv-tailor handoff (Phase 2, INTEGRATION_SPEC §5.1): a plain link, not a mutation — visible
  // to everyone, never lock-gated (cv-tailor's own key gate handles non-owner access). A run
  // exists → open it; none yet → start one pre-seeded with this job_id (cv-tailor fetches the
  // JD via the public GET /api/jobs/{job_id} built in Phase 1).
  const cvTailorUrl = cv.has_output
    ? `https://cv-tailor.michel-portfolio.co.uk/runs/${cv.run_id}`
    : `https://cv-tailor.michel-portfolio.co.uk/new?source=job_radar&job_id=${job.job_id}`;
  const cvTailorLabel = cv.has_output ? "Open in cv-tailor ↗" : "Create CV in cv-tailor ↗";
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<Toast>(null);

  const [runId, setRunId] = useState(cv.run_id || "");
  const [fitScore, setFitScore] = useState(toPercentStr(cv.fit_score));
  const [coverage, setCoverage] = useState(toPercentStr(cv.coverage_score));
  const [cvQuality, setCvQuality] = useState(qualityStr(cv.cv_quality_score));
  const [cvcm, setCvcm] = useState(!!cv.cvcm_enabled);
  const [mode, setMode] = useState(cv.tailoring_mode || "full");
  const [link, setLink] = useState(cv.output_link || "");
  const [notes, setNotes] = useState(cv.notes || "");

  function resetForm() {
    setRunId(cv.run_id || ""); setFitScore(toPercentStr(cv.fit_score));
    setCoverage(toPercentStr(cv.coverage_score)); setCvQuality(qualityStr(cv.cv_quality_score));
    setCvcm(!!cv.cvcm_enabled); setMode(cv.tailoring_mode || "full");
    setLink(cv.output_link || ""); setNotes(cv.notes || "");
  }
  useEffect(() => { resetForm(); setEditing(false); setToast(null); }, [job.job_id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function save() {
    if (!(await requestUnlock())) return;
    if (!runId.trim()) { setToast({ kind: "err", text: "Run ID is required" }); return; }
    setBusy(true);
    try {
      await api.recordCvTailorResult({
        job_id: job.job_id,
        cv_tailor_run_id: runId.trim(),
        fit_score: toFraction(fitScore),
        coverage_score: toFraction(coverage),
        cv_quality_score: toQuality(cvQuality),
        cvcm_enabled: cvcm,
        tailoring_mode: mode,
        output_link: link.trim() || null,
        notes: notes.trim() || null,
      });
      setEditing(false);
      setToast({ kind: "ok", text: "CV-Tailor metrics saved" });
      await onChanged();
    } catch (e) {
      setToast({ kind: "err", text: e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-[18px] rounded-lg border border-line bg-[#fbfcfe] p-[14px]">
      <h3 className="mb-[10px] text-[11px] font-bold uppercase tracking-wide text-brand">CV-Tailor</h3>

      {editing ? (
        <div className="space-y-2">
          <div>
            <label className={LABEL}>Run ID (required)</label>
            <input className={FIELD_INPUT} value={runId} placeholder="run_20260611_001" disabled={busy} onChange={(e) => setRunId(e.target.value)} />
          </div>
          <div className="grid grid-cols-3 gap-2">
            <div><label className={LABEL}>Fit score (0–100)</label><input className={FIELD_INPUT} inputMode="numeric" value={fitScore} disabled={busy} onChange={(e) => setFitScore(e.target.value)} /></div>
            <div><label className={LABEL}>Coverage (0–100)</label><input className={FIELD_INPUT} inputMode="numeric" value={coverage} disabled={busy} onChange={(e) => setCoverage(e.target.value)} /></div>
            <div><label className={LABEL}>CV Quality (0–10)</label><input className={FIELD_INPUT} inputMode="decimal" value={cvQuality} placeholder="8.1" disabled={busy} onChange={(e) => setCvQuality(e.target.value)} /></div>
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex items-center gap-[6px] text-[12.5px] text-ink">
              <input type="checkbox" checked={cvcm} disabled={busy} onChange={(e) => setCvcm(e.target.checked)} /> CVCM enabled
            </label>
            <div>
              <label className={LABEL}>Mode</label>
              <select className={cn(FIELD_INPUT, "w-auto min-w-[120px]")} value={mode} disabled={busy} onChange={(e) => setMode(e.target.value)}>
                {CV_TAILOR_MODES.map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
            </div>
          </div>
          <div><label className={LABEL}>Output link</label><input className={FIELD_INPUT} value={link} placeholder="https://cv-tailor…/runs/…" disabled={busy} onChange={(e) => setLink(e.target.value)} /></div>
          <div><label className={LABEL}>Notes</label><textarea className={cn(FIELD_INPUT, "font-sans")} rows={2} value={notes} disabled={busy} onChange={(e) => setNotes(e.target.value)} /></div>
          <div className="flex gap-2">
            <button className={BTN_PRIMARY} onClick={save} disabled={busy}>Save</button>
            <button className={BTN} onClick={() => { resetForm(); setEditing(false); }} disabled={busy}>Cancel</button>
          </div>
        </div>
      ) : cv.has_output ? (
        <div className="text-[13px] text-ink">
          <div className="mb-[6px] flex flex-wrap items-center justify-between gap-2">
            <span><span className="text-ink-soft">Run:</span> <span className="font-semibold">{cv.run_id}</span></span>
            <span className="text-[11px] text-ink-faint">{fmtDate(cv.ts)}</span>
          </div>
          <div className="mb-[4px] flex flex-wrap gap-x-[18px] gap-y-1 tabular-nums">
            <span><span className="text-ink-soft">Fit:</span> {pctDisplay(cv.fit_score)}</span>
            <span><span className="text-ink-soft">Coverage:</span> {pctDisplay(cv.coverage_score)}</span>
            <span><span className="text-ink-soft">CV Quality:</span> {qualityDisplay(cv.cv_quality_score)}</span>
          </div>
          <div className="mb-[4px] flex flex-wrap gap-x-[18px] text-[12.5px] text-ink-soft">
            <span>CVCM: {cv.cvcm_enabled ? "enabled" : "disabled"}</span>
            {cv.tailoring_mode && <span>Mode: {cv.tailoring_mode}</span>}
          </div>
          {cv.notes && <p className="mb-[4px] text-[12.5px] text-ink-soft">Notes: {cv.notes}</p>}
          {cv.output_link && <a className="text-[12px] text-brand hover:underline" href={cv.output_link} target="_blank" rel="noopener">↗ Open output</a>}
          {unlocked && (
            <div className="mt-[10px]">
              <button className={BTN} onClick={() => { resetForm(); setEditing(true); }} disabled={busy}>Edit</button>
            </div>
          )}
        </div>
      ) : (
        <div className="text-[13px] text-ink-soft">
          <p className="mb-[8px]">{unlocked ? "No cv-tailor run recorded yet." : "No cv-tailor run recorded."}</p>
          {unlocked && <button className={BTN} onClick={() => { resetForm(); setEditing(true); }} disabled={busy}>Add cv-tailor metrics</button>}
        </div>
      )}

      {/* Handoff link (Phase 2) — always visible, never lock-gated; opens in a new tab. */}
      <div className="mt-[12px] border-t border-line-soft pt-[12px]">
        <a href={cvTailorUrl} target="_blank" rel="noopener" className={cn(BTN, "inline-block no-underline")}>{cvTailorLabel}</a>
      </div>

      {toast && <div className={cn("mt-2 rounded-md px-[9px] py-[6px] text-[12px]", TOAST[toast.kind])}>{toast.text}</div>}
    </div>
  );
}

function AnnotationItem({ a }: { a: Annotation }) {
  const exp = listText(a.expected);
  return (
    <div className="rounded-md border border-line-soft bg-white px-[10px] py-[7px]">
      <div className="mb-[2px] flex items-center justify-between gap-2">
        <span className="rounded-[4px] bg-[#eef1f6] px-[7px] py-px text-[11px] font-semibold text-ink-soft">{a.annotation_type}</span>
        <span className="text-[11px] text-ink-faint">{fmtDate(a.ts)}</span>
      </div>
      <p className="text-[12.5px] text-ink">{a.reason}</p>
      {exp && <p className="mt-[2px] text-[11.5px] text-ink-faint">expected: {exp}</p>}
    </div>
  );
}

function WriteControls({ job, onChanged }: { job: Job; onChanged: () => Promise<void> }) {
  const { requestUnlock } = useUnlock();
  const [toast, setToast] = useState<Toast>(null);
  const [flagToast, setFlagToast] = useState<Toast>(null);
  const [busy, setBusy] = useState(false);
  const [noteText, setNoteText] = useState(job.notes || "");
  const [titleText, setTitleText] = useState(job.title || "");
  const [flagType, setFlagType] = useState(ANNOTATION_TYPES[0]);
  const [expected, setExpected] = useState("");
  const [reason, setReason] = useState("");
  const [outcome, setOutcomeSel] = useState(rejectionStageFor(job.application_status));
  const [outcomeNotes, setOutcomeNotes] = useState("");
  const [fitSel, setFitSel] = useState(job.user_fit_label || job.scorer_fit_label);
  const [fitReason, setFitReason] = useState(job.user_fit_reason || "");
  const [editingOverride, setEditingOverride] = useState(false);

  // Latest recorded rejection reason for this role (annotations are append-only, so the
  // most recent rejection_reason entry is the current one).
  const rejectionAnns = (job.annotations || []).filter((a) => a.annotation_type === "rejection_reason");
  const recordedReason = rejectionAnns.length ? String(rejectionAnns[rejectionAnns.length - 1].reason) : null;
  const [rejToast, setRejToast] = useState<Toast>(null);
  const [rejReason, setRejReason] = useState(recordedReason || "");
  const [showReject, setShowReject] = useState(false);     // revealed after clicking Rejected
  const [editingReject, setEditingReject] = useState(false);

  useEffect(() => {
    setNoteText(job.notes || ""); setTitleText(job.title || "");
    setFlagType(ANNOTATION_TYPES[0]); setExpected(""); setReason("");
    setOutcomeSel(rejectionStageFor(job.application_status)); setOutcomeNotes("");
    setFitSel(job.user_fit_label || job.scorer_fit_label); setFitReason(job.user_fit_reason || "");
    setEditingOverride(false);
    setRejReason(recordedReason || ""); setShowReject(false); setEditingReject(false); setRejToast(null);
    setToast(null); setFlagToast(null);
  }, [job.job_id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function guarded(run: () => Promise<Toast>, setT: (t: Toast) => void = setToast) {
    if (!(await requestUnlock())) return;
    setBusy(true);
    try {
      setT(await run());
      await onChanged();
    } catch (e) {
      setT({ kind: "err", text: e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  }

  const setStatus = (status: string) => guarded(async () => {
    if (status === "archived" && !window.confirm("Archive this role?")) return null;
    const res = await api.setStatus(job.job_id, status);
    return res.warning ? { kind: "warn", text: `Saved · ${res.warning}` } : { kind: "ok", text: `Status → ${status}` };
  });
  const saveNote = () => guarded(async () => {
    if (!noteText.trim()) return { kind: "err", text: "Note is empty" };
    await api.addNote(job.job_id, noteText.trim());
    return { kind: "ok", text: "Note saved" };
  });
  const saveTitle = () => guarded(async () => {
    if (!titleText.trim()) return { kind: "err", text: "Title is empty" };
    await api.setTitle(job.job_id, titleText.trim());
    return { kind: "ok", text: "Title override saved" };
  });
  const recordOutcome = () => guarded(async () => {
    await api.setOutcome(job.job_id, outcome, outcomeNotes.trim() || undefined);
    const lane = statusForOutcome(outcome);
    if (lane && lane !== job.application_status) await api.setStatus(job.job_id, lane);
    setOutcomeNotes("");
    return { kind: "ok", text: `Recorded: ${outcome.replace(/_/g, " ")}` };
  });
  const saveOverride = () => guarded(async () => {
    await api.setFitOverride(job.job_id, fitSel, fitReason.trim() || undefined);
    setEditingOverride(false);
    return { kind: "ok", text: `Fit override → ${LABEL_TEXT[fitSel] || fitSel}` };
  });
  const clearOverride = () => guarded(async () => {
    await api.setFitOverride(job.job_id, null);
    setEditingOverride(false);
    return { kind: "ok", text: "Override cleared" };
  });
  const recordRejection = () => guarded(async () => {
    if (!rejReason) return { kind: "err", text: "Select a reason" };
    await api.flagAnnotation({
      job_id: job.job_id, annotation_type: "rejection_reason", field: null,
      observed: [job.scorer_fit_label, String(job.scorer_fit_score)], expected: [], reason: rejReason,
    });
    setEditingReject(false);
    return { kind: "ok", text: `Rejection reason recorded: ${rejReason.replace(/_/g, " ")}` };
  }, setRejToast);
  const submitFlag = () => guarded(async () => {
    if (!reason.trim()) return { kind: "err", text: "Reason is required" };
    const { field, observed } = observedFor(flagType, job);
    // Client-side duplicate check (job_radar_SPEC §10.11 Feature 2): same type + field +
    // reason as an existing flag. Courtesy warning — the API is the backstop (409).
    const dup = (job.annotations || []).some(
      (a) => a.annotation_type === flagType && a.field === field && a.reason === reason.trim(),
    );
    if (dup && !window.confirm("This flag already exists. Submit anyway?")) return null;
    await api.flagAnnotation({ job_id: job.job_id, annotation_type: flagType, field, observed, expected: expected.trim(), reason: reason.trim() });
    setExpected(""); setReason("");
    return { kind: "ok", text: "Flag submitted" };
  }, setFlagToast);

  const { observed } = observedFor(flagType, job);
  const eff = effectiveStatus(job);
  const STATUS_BTNS: Array<{ label: string; value: string; danger?: boolean }> = [
    { label: "Review", value: "review" }, { label: "Shortlist", value: "shortlisted" },
    { label: "Apply", value: "applied" }, { label: "Interview", value: "interviewing" },
    { label: "Offer", value: "offer" }, { label: "Rejected", value: "rejected", danger: true },
    { label: "Archive", value: "archived", danger: true },
  ];
  const ageDays = daysSince(job.application_date);
  const stale = isStaleApplied(job);
  const hasApplied = !!job.application_date || ["applied", "interviewing", "offer", "rejected"].includes(eff);
  const wcLabel = "w-16 shrink-0 text-[12px] text-ink-soft";

  return (
    <>
      <div className="mt-[18px] rounded-lg border border-line bg-[#fbfcfe] p-[14px]">
        <h3 className="mb-[10px] text-[11px] font-bold uppercase tracking-wide text-brand">Fit assessment</h3>
        <div className="mb-[10px] text-[12.5px] text-ink-soft">
          <span className="font-semibold text-ink">Scorer</span>{" "}
          <span className={cn("ml-1 inline-block rounded-full px-2 py-px text-[11px] font-bold", fitBadgeClass(job.scorer_fit_label))}>{LABEL_TEXT[job.scorer_fit_label] || job.scorer_fit_label}</span>
          <span className="ml-2 tabular-nums">fit {job.scorer_fit_score} · priority {job.scorer_priority_score}</span>
        </div>

        {job.has_fit_override && !editingOverride ? (
          <div className="rounded-md border border-[#e2c98f] bg-[#fdf7e8] p-[10px]">
            <div className="mb-[6px] flex flex-wrap items-center gap-2 text-[12px]">
              <span className="font-bold uppercase tracking-wide text-[#8a5a14]">⚠ Manual override active</span>
              <span className={cn("inline-block rounded-full px-2 py-px text-[11px] font-bold", fitBadgeClass(job.user_fit_label || ""))}>{LABEL_TEXT[job.user_fit_label || ""] || job.user_fit_label}</span>
            </div>
            {job.user_fit_reason && <p className="mb-[8px] text-[12.5px] italic text-ink-soft">“{job.user_fit_reason}”</p>}
            <div className="flex flex-wrap gap-[6px]">
              <button className={BTN} onClick={() => { setFitSel(job.user_fit_label || job.scorer_fit_label); setFitReason(job.user_fit_reason || ""); setEditingOverride(true); }} disabled={busy}>Edit override</button>
              <button className={BTN} onClick={clearOverride} disabled={busy}>Clear override</button>
            </div>
          </div>
        ) : (
          <div className="flex flex-wrap items-end gap-2">
            <div>
              <label className={LABEL}>Override fit label</label>
              <select className={cn(FIELD_INPUT, "w-auto min-w-[150px]")} value={fitSel} disabled={busy} onChange={(e) => setFitSel(e.target.value)}>
                {FIT_LABELS.map((l) => <option key={l} value={l}>{LABEL_TEXT[l] || l}</option>)}
              </select>
            </div>
            <input className={cn(FIELD_INPUT, "min-w-[140px] flex-1")} value={fitReason} placeholder="Reason (recommended)…" disabled={busy} onChange={(e) => setFitReason(e.target.value)} />
            <button className={BTN_PRIMARY} onClick={saveOverride} disabled={busy}>Save override</button>
            {editingOverride && <button className={BTN} onClick={() => setEditingOverride(false)} disabled={busy}>Cancel</button>}
          </div>
        )}
      </div>

      <div className="mt-[18px] rounded-lg border border-line bg-[#fbfcfe] p-[14px]">
        <h3 className="mb-[10px] text-[11px] font-bold uppercase tracking-wide text-brand">Workflow</h3>

        <div className="mb-[10px] flex flex-wrap items-center gap-2">
          <span className={wcLabel}>Status</span>
          <div className="flex flex-wrap gap-[6px]">
            {STATUS_BTNS.map((b) => (
              <button key={b.value} disabled={busy} onClick={() => { setStatus(b.value); if (b.value === "rejected") setShowReject(true); }}
                className={cn(
                  "rounded-md border px-[11px] py-[5px] text-[12.5px] font-semibold disabled:opacity-50",
                  eff === b.value ? "border-brand bg-brand text-white"
                    : b.danger ? "border-line bg-white text-ink hover:border-[#c0392b] hover:text-[#c0392b]"
                    : "border-line bg-white text-ink hover:border-brand hover:text-brand",
                )}>
                {b.label}
              </button>
            ))}
          </div>
        </div>

        <div className="mb-[10px] flex flex-wrap items-center gap-2">
          <span className={wcLabel}>Notes</span>
          <input className={cn(FIELD_INPUT, "min-w-[140px] flex-1")} value={noteText} placeholder="Add a note…" disabled={busy} onChange={(e) => setNoteText(e.target.value)} />
          <button className={BTN} onClick={saveNote} disabled={busy}>Save</button>
        </div>

        <div className="mb-[10px] flex flex-wrap items-center gap-2">
          <span className={wcLabel}>Title</span>
          <input className={cn(FIELD_INPUT, "min-w-[140px] flex-1")} value={titleText} placeholder="Display title override…" disabled={busy} onChange={(e) => setTitleText(e.target.value)} />
          <button className={BTN} onClick={saveTitle} disabled={busy}>Override</button>
        </div>

        {hasApplied && (
          <div className="mt-1 border-t border-dashed border-line pt-[10px]">
            <div className="mb-[10px] flex flex-wrap items-center gap-2">
              <span className={wcLabel}>Applied</span>
              <span className="text-[13px]">
                {job.application_date || <span className="text-ink-faint">date not recorded</span>}
                {ageDays !== null && <span className="text-ink-faint"> · {ageDays}d ago</span>}
                {stale && <span className="ml-2 rounded-full bg-[#f6e3d3] px-[7px] py-px text-[10.5px] font-bold uppercase tracking-wide text-[#b4540f]" title={`No movement for ${ageDays} days`}>stale</span>}
                {job.outcome && <span className="ml-2 rounded-[5px] bg-[#f3dede] px-2 py-px text-[11px] font-semibold text-[#9a3636]">{job.outcome.replace(/_/g, " ")}</span>}
              </span>
            </div>
            <div className="mb-[10px] flex flex-wrap items-center gap-2">
              <span className={wcLabel}>Outcome</span>
              <select className={cn(FIELD_INPUT, "w-auto min-w-[168px] shrink-0")} value={outcome} disabled={busy} onChange={(e) => setOutcomeSel(e.target.value)}>
                {OUTCOMES.map((o) => <option key={o} value={o}>{o.replace(/_/g, " ")}</option>)}
              </select>
              <input className={cn(FIELD_INPUT, "min-w-[140px] flex-1")} value={outcomeNotes} placeholder="Reason / notes…" disabled={busy} onChange={(e) => setOutcomeNotes(e.target.value)} />
              <button className={BTN} onClick={recordOutcome} disabled={busy}>Record</button>
            </div>
          </div>
        )}

        {toast && <div className={cn("mt-2 rounded-md px-[9px] py-[6px] text-[12px]", TOAST[toast.kind])}>{toast.text}</div>}
      </div>

      {(eff === "rejected" || showReject) && (
        <div className="mt-[18px] rounded-lg border border-line bg-[#fbfcfe] p-[14px]">
          <h3 className="mb-[8px] text-[11px] font-bold uppercase tracking-wide text-brand">Rejection reason</h3>
          {recordedReason && !editingReject ? (
            <div className="flex flex-wrap items-center gap-2 text-[13px]">
              <span className="text-ink-soft">Already recorded:</span>
              <span className="rounded-[5px] bg-[#f3e9e9] px-2 py-px text-[12px] font-semibold text-[#9a5252]">{recordedReason.replace(/_/g, " ")}</span>
              <button className={BTN} onClick={() => setEditingReject(true)} disabled={busy}>Edit</button>
            </div>
          ) : (
            <>
              <p className="mb-[8px] text-[12.5px] text-ink-soft">Why didn't you pursue this?</p>
              <div className="flex flex-wrap items-end gap-2">
                <select className={cn(FIELD_INPUT, "w-auto min-w-[200px]")} value={rejReason} disabled={busy} onChange={(e) => setRejReason(e.target.value)}>
                  <option value="">— select reason —</option>
                  {REJECTION_REASONS.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
                </select>
                <button className={BTN_PRIMARY} onClick={recordRejection} disabled={busy}>Record reason</button>
                {editingReject && <button className={BTN} onClick={() => setEditingReject(false)} disabled={busy}>Cancel</button>}
              </div>
            </>
          )}
          {rejToast && <div className={cn("mt-2 rounded-md px-[9px] py-[6px] text-[12px]", TOAST[rejToast.kind])}>{rejToast.text}</div>}
        </div>
      )}

      <CvTailorSection job={job} onChanged={onChanged} />

      <div className="mt-[18px] rounded-lg border border-line bg-[#fbfcfe] p-[14px]">
        <h3 className="mb-[10px] text-[11px] font-bold uppercase tracking-wide text-brand">
          Flag scoring issue{!!(job.annotations || []).length && ` · ${job.annotations.length} existing`}
        </h3>
        {!!(job.annotations || []).length && (
          <div className="mb-[12px] space-y-[6px]">
            {job.annotations.map((a, i) => <AnnotationItem key={i} a={a} />)}
          </div>
        )}
        <label className={LABEL}>Type</label>
        <select className={cn(FIELD_INPUT, "mb-2")} value={flagType} disabled={busy} onChange={(e) => setFlagType(e.target.value)}>
          {ANNOTATION_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <label className={LABEL}>Observed (from record)</label>
        <input className={cn(FIELD_INPUT, "mb-2")} value={listText(observed)} readOnly disabled />
        <label className={LABEL}>Expected</label>
        <input className={cn(FIELD_INPUT, "mb-2")} value={expected} placeholder="What it should be…" disabled={busy} onChange={(e) => setExpected(e.target.value)} />
        <label className={LABEL}>Reason</label>
        <textarea className={cn(FIELD_INPUT, "mb-2 font-sans")} rows={2} value={reason} placeholder="Why is the scoring wrong?" disabled={busy} onChange={(e) => setReason(e.target.value)} />
        <div className="flex justify-end">
          <button className={BTN_PRIMARY} onClick={submitFlag} disabled={busy}>Submit Flag</button>
        </div>
        {flagToast && <div className={cn("mt-2 rounded-md px-[9px] py-[6px] text-[12px]", TOAST[flagToast.kind])}>{flagToast.text}</div>}
      </div>
    </>
  );
}

export function DetailPanel({ job, onClose, onChanged }: { job: Job; onClose: () => void; onChanged: () => Promise<void> }) {
  const { configured } = useUnlock();
  const niceToHave = [...(job.nice_to_have_technologies || []), ...(job.nice_to_have_competencies || [])];

  return (
    <>
      <div className="fixed inset-0 z-40 bg-[#141a26]/50" onClick={onClose} />
      <aside
        aria-label="role detail"
        className="fixed left-1/2 top-1/2 z-50 h-[80vh] max-h-[92vh] w-[80vw] max-w-[1040px] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-[14px] border border-line bg-panel shadow-[0_24px_70px_rgba(20,26,38,.32)]"
      >
        <div className="sticky top-0 z-10 rounded-t-[14px] border-b border-line bg-panel px-6 py-4">
          <button onClick={onClose} title="Close (Esc)" className="float-right text-[22px] leading-none text-ink-faint hover:text-ink">×</button>
          <div className="text-[12px] uppercase tracking-wide text-ink-soft">{job.company}</div>
          <h2 className="mb-[10px] mt-[2px] text-[19px] font-semibold">{job.title}</h2>
          <div className="flex flex-wrap items-center gap-2">
            <span className={cn("inline-block rounded-full px-2 py-[2px] text-[11px] font-bold", fitBadgeClass(job.fit_label))}>{LABEL_TEXT[job.fit_label] || job.fit_label}</span>
            {job.has_fit_override && <span className="rounded-full bg-[#fdf7e8] px-[7px] py-px text-[10.5px] font-bold uppercase tracking-wide text-[#8a5a14]" title={`Overridden — scorer said ${LABEL_TEXT[job.scorer_fit_label] || job.scorer_fit_label}`}>override</span>}
            <Pill status={effectiveStatus(job)} />
            {job.outcome && <span className="rounded-[5px] bg-[#f3dede] px-2 py-px text-[11px] font-semibold text-[#9a3636]">{job.outcome.replace(/_/g, " ")}</span>}
            {isStaleApplied(job) && <span className="rounded-full bg-[#f6e3d3] px-[7px] py-px text-[10.5px] font-bold uppercase tracking-wide text-[#b4540f]">stale</span>}
            {job.location && <span className="text-ink-faint">{job.location}</span>}
          </div>
          <div className="mt-3 flex gap-[22px]">
            <div><div className="text-[22px] font-extrabold">{job.fit_score}</div><div className="text-[10px] uppercase tracking-wide text-ink-soft">fit score</div></div>
            <div><div className="text-[22px] font-extrabold">{job.priority_score}</div><div className="text-[10px] uppercase tracking-wide text-ink-soft">priority</div></div>
            {job.location_workable && <div><div className="text-[22px] font-extrabold">{job.location_workable}</div><div className="text-[10px] uppercase tracking-wide text-ink-soft">location</div></div>}
          </div>
        </div>

        <div className="mx-auto max-w-[760px] px-6 pb-12 pt-2">
          {configured && <WriteControls job={job} onChanged={onChanged} />}
          {/* Read-only-deploy fallback (no write key): WriteControls is hidden, but the
              cv-tailor snapshot should still be visible when present (job_radar_SPEC §11.3). */}
          {!configured && <CvTailorSection job={job} onChanged={onChanged} />}

          {job.fit_label_reason && <Section title="Assessment"><p className="rounded-md bg-line-soft px-[11px] py-[9px] italic text-ink">{job.fit_label_reason}</p></Section>}
          {!!(job.blocking_constraints || []).length && <Section title="Blocking constraints"><Chips items={job.blocking_constraints} tone="block" /></Section>}
          {!!(job.requirement_gaps || []).length && <Section title="Requirement gaps"><Chips items={job.requirement_gaps} tone="warn" /></Section>}
          {job.notes && <Section title="Notes"><p>{job.notes}</p></Section>}

          <Section title="Extraction">
            <dl className="grid grid-cols-[150px_1fr] gap-x-3 gap-y-1">
              <KV label="Role type" value={listText(job.role_type)} />
              <KV label="Domain" value={listText(job.domain)} />
              <KV label="Seniority" value={job.seniority} />
              <KV label="Technical depth" value={job.technical_depth} />
              <KV label="Remote policy" value={job.remote_policy} />
              <KV label="Company stage" value={job.company_stage} />
              <KV label="Company size" value={job.company_size_signal} />
              <KV label="Experience" value={job.years_experience_required} />
              <KV label="Delivery motion" value={listText(job.delivery_motion)} />
              <KV label="Source" value={job.source_ats} />
              <KV label="First seen" value={fmtDate(job.date_first_seen)} />
              {job.application_date && <KV label="Applied" value={job.application_date} />}
            </dl>
          </Section>

          {!!(job.required_technologies || []).length && <Section title="Required technologies"><Chips items={job.required_technologies} /></Section>}
          {!!(job.required_competencies || []).length && <Section title="Required competencies"><Chips items={job.required_competencies} /></Section>}
          {!!niceToHave.length && <Section title="Nice to have"><Chips items={niceToHave} /></Section>}
          {!!(job.culture_signals || []).length && <Section title="Culture signals"><Chips items={job.culture_signals} /></Section>}
          {job.raw_observations && <Section title="Raw observations"><p className="text-ink-faint">{job.raw_observations}</p></Section>}
          {job.raw_text && <Section title="Full JD text"><div className="max-h-[360px] overflow-y-auto whitespace-pre-wrap break-words rounded-[7px] border border-line-soft bg-[#fbfbfd] p-3 text-[12.5px] leading-[1.55] text-ink-soft">{job.raw_text}</div></Section>}
          {job.source_url && <Section title="Source"><a className="text-[12px] text-brand hover:underline" href={job.source_url} target="_blank" rel="noopener">{job.source_url}</a></Section>}
        </div>
      </aside>
    </>
  );
}
