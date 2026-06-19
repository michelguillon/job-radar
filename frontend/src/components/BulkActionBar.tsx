import { useMemo, useState } from "react";
import { Loader2 } from "lucide-react";
import type { Job } from "@/lib/api";
import { cn } from "@/lib/utils";
import { ANNOTATION_TYPES, FIT_LABELS, LABEL_TEXT, REJECTION_REASONS } from "@/lib/jobs";
import {
  ACTION_KINDS, actionSummary, BULK_STATUSES, executeComposite, planComposite, rowOutcomeText,
  type ActionKind, type BulkAction,
} from "@/lib/bulk";
import { useUnlock } from "@/components/UnlockProvider";

// Bulk action composer (SPEC_BULK_ACTIONS, multi-action revision). Browse-only; rendered by the
// Shell when ≥1 role is selected. The owner stages any mix of the four detail-panel writes via
// tabs, then applies them all in one pass — each fans out to the per-role endpoints (lib/bulk).
// All Tailwind, no global classes — same idiom as the detail panel.

type Mode = "bar" | "compose" | "confirm" | "running";

const FIELD = "w-full rounded-md border border-line px-[9px] py-[6px] text-[13px] focus:border-brand focus:outline-none disabled:opacity-50";
const LABEL = "block text-[11px] text-ink-soft mb-[3px]";
const BTN = "rounded-md border border-line bg-white px-[12px] py-[6px] text-[12.5px] font-semibold text-ink hover:border-brand hover:text-brand disabled:opacity-50";
const BTN_PRIMARY = "rounded-md border border-brand bg-brand px-[14px] py-[6px] text-[12.5px] font-semibold text-white hover:bg-[#245fd0] disabled:opacity-50";

const TAB_LABEL: Record<ActionKind, string> = {
  fit: "Override fit", status: "Set status", flag: "Flag issue", note: "Add note",
};

export function BulkActionBar({
  selectedJobs, onDeselectAll, onComplete, pushToast,
}: {
  selectedJobs: Job[];
  onDeselectAll: () => void;
  onComplete: () => Promise<void>; // refetch index + clear selection (Shell handles both)
  pushToast: (kind: "ok" | "warn" | "err", text: string) => void;
}) {
  const { requestUnlock } = useUnlock();
  const n = selectedJobs.length;
  const [mode, setMode] = useState<Mode>("bar");
  const [activeTab, setActiveTab] = useState<ActionKind>("fit");
  const [included, setIncluded] = useState<Record<ActionKind, boolean>>({ fit: false, status: false, flag: false, note: false });
  const [progress, setProgress] = useState({ done: 0, total: 0 });

  // Form state — persisted for the composer's lifetime so tab switches + the confirm round trip
  // preserve every value.
  const [fitLabel, setFitLabel] = useState(FIT_LABELS[0]);
  const [fitReason, setFitReason] = useState("");
  const [statusVal, setStatusVal] = useState(BULK_STATUSES[0].value);
  const [rejReason, setRejReason] = useState("");
  const [flagType, setFlagType] = useState(ANNOTATION_TYPES[0]);
  const [flagField, setFlagField] = useState("");
  const [flagObserved, setFlagObserved] = useState("");
  const [flagExpected, setFlagExpected] = useState("");
  const [flagReason, setFlagReason] = useState("");
  const [noteText, setNoteText] = useState("");

  const setInc = (k: ActionKind, on: boolean) => setIncluded((p) => ({ ...p, [k]: on }));
  const touch = (k: ActionKind) => setIncluded((p) => (p[k] ? p : { ...p, [k]: true })); // editing a tab includes it

  // Pure projection of one tab's persisted state into a BulkAction.
  function buildAction(kind: ActionKind): BulkAction {
    switch (kind) {
      case "fit": return { kind: "fit", fit_label: fitLabel, reason: fitReason };
      case "status": return { kind: "status", status: statusVal, rejection_reason: statusVal === "will_not_apply" ? rejReason : "" };
      case "flag": return { kind: "flag", annotation_type: flagType, field: flagField, observed: flagObserved, expected: flagExpected, reason: flagReason };
      case "note": return { kind: "note", text: noteText };
    }
  }

  const includedKinds = ACTION_KINDS.filter((k) => included[k]);
  // A staged tab is invalid only when it needs free text it doesn't have (flag reason / note text).
  const invalidKinds = includedKinds.filter((k) => (k === "flag" && !flagReason.trim()) || (k === "note" && !noteText.trim()));
  const canPreview = includedKinds.length > 0 && invalidKinds.length === 0;
  const stagedActions = useMemo(
    () => includedKinds.map(buildAction),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [includedKinds.join(","), fitLabel, fitReason, statusVal, rejReason, flagType, flagField, flagObserved, flagExpected, flagReason, noteText],
  );
  const plan = useMemo(() => planComposite(stagedActions, selectedJobs), [stagedActions, selectedJobs]);
  const opsToApply = plan.reduce((acc, r) => acc + r.items.filter((i) => !i.skipReason).length, 0);
  const opsSkipped = plan.reduce((acc, r) => acc + r.items.filter((i) => i.skipReason).length, 0);
  const rolesAffected = plan.filter((r) => r.items.some((i) => !i.skipReason)).length;

  if (n === 0) return null; // bar only shows with a live selection

  function openCompose(kind: ActionKind) { setActiveTab(kind); setInc(kind, true); setMode("compose"); }

  async function apply() {
    if (opsToApply === 0) return;
    if (!(await requestUnlock())) return; // owner-gated, like every other write
    setProgress({ done: 0, total: opsToApply });
    setMode("running");
    const o = await executeComposite(stagedActions, selectedJobs, (done, total) => setProgress({ done, total }));
    const chg = (k: number) => `${k} change${k === 1 ? "" : "s"}`;
    if (o.failed === 0 && o.skipped === 0) {
      pushToast("ok", `✓ ${chg(o.updated)} applied to ${o.rolesAffected} role${o.rolesAffected === 1 ? "" : "s"}`);
    } else if (o.failed === 0) {
      pushToast("ok", `✓ ${chg(o.updated)} applied · ${o.skipped} skipped`);
    } else {
      pushToast("warn", `⚠ ${chg(o.updated)} applied · ${o.skipped} skipped · ${o.failed} failed`);
    }
    await onComplete(); // refetch + clear selection (unmounts the composer)
  }

  // ---- Bar ------------------------------------------------------------------
  if (mode === "bar") {
    return (
      <BarShell n={n}>
        {ACTION_KINDS.map((k) => <button key={k} className={BTN} onClick={() => openCompose(k)}>{TAB_LABEL[k]} ▾</button>)}
        <button className={cn(BTN, "ml-auto")} onClick={onDeselectAll}>Deselect all</button>
      </BarShell>
    );
  }

  // ---- Composer (tabbed) ----------------------------------------------------
  if (mode === "compose") {
    return (
      <BarShell n={n}>
        <Panel title={`Bulk edit · ${n} role${n === 1 ? "" : "s"}`} wide>
          {/* Tab strip — a • marks a staged tab; amber when staged but missing required text. */}
          <div className="mb-[12px] flex flex-wrap gap-1 border-b border-line">
            {ACTION_KINDS.map((k) => {
              const on = activeTab === k;
              const staged = included[k];
              const invalid = invalidKinds.includes(k);
              return (
                <button key={k} onClick={() => setActiveTab(k)}
                  className={cn(
                    "flex items-center gap-[6px] border-b-[2.5px] px-[12px] py-[7px] text-[12.5px] font-semibold",
                    on ? "border-brand text-brand" : "border-transparent text-ink-soft hover:text-ink",
                  )}>
                  {TAB_LABEL[k]}
                  {staged && <span className={cn("text-[14px] leading-none", invalid ? "text-[#b4540f]" : "text-[#1f9d57]")}>•</span>}
                </button>
              );
            })}
          </div>

          {/* Include toggle for the active tab. */}
          <label className="mb-[10px] flex cursor-pointer items-center gap-[7px] text-[12.5px] font-semibold text-ink">
            <input type="checkbox" className="accent-brand" checked={included[activeTab]} onChange={(e) => setInc(activeTab, e.target.checked)} />
            Apply this change to the {n} selected role{n === 1 ? "" : "s"}
          </label>

          <div className={cn(!included[activeTab] && "opacity-55")}>
            {activeTab === "fit" && (
              <div className="flex flex-wrap items-end gap-3">
                <div>
                  <label className={LABEL}>Label</label>
                  <select className={cn(FIELD, "w-auto min-w-[150px]")} value={fitLabel} onChange={(e) => { touch("fit"); setFitLabel(e.target.value); }}>
                    {FIT_LABELS.map((l) => <option key={l} value={l}>{LABEL_TEXT[l] || l}</option>)}
                  </select>
                </div>
                <div className="min-w-[200px] flex-1">
                  <label className={LABEL}>Reason (optional)</label>
                  <input className={FIELD} value={fitReason} placeholder="Why override these?" onChange={(e) => { touch("fit"); setFitReason(e.target.value); }} />
                </div>
              </div>
            )}

            {activeTab === "status" && (
              <div className="flex flex-wrap items-end gap-3">
                <div>
                  <label className={LABEL}>Status</label>
                  <select className={cn(FIELD, "w-auto min-w-[170px]")} value={statusVal} onChange={(e) => { touch("status"); setStatusVal(e.target.value); }}>
                    {BULK_STATUSES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
                  </select>
                </div>
                {statusVal === "will_not_apply" && (
                  <div className="min-w-[220px]">
                    <label className={LABEL}>Rejection reason (optional)</label>
                    <select className={cn(FIELD, "w-auto min-w-[220px]")} value={rejReason} onChange={(e) => { touch("status"); setRejReason(e.target.value); }}>
                      <option value="">— select reason —</option>
                      {REJECTION_REASONS.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
                    </select>
                  </div>
                )}
              </div>
            )}

            {activeTab === "flag" && (
              <div className="space-y-2">
                <div className="flex flex-wrap items-end gap-3">
                  <div>
                    <label className={LABEL}>Type</label>
                    <select className={cn(FIELD, "w-auto min-w-[200px]")} value={flagType} onChange={(e) => { touch("flag"); setFlagType(e.target.value); }}>
                      {ANNOTATION_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                    </select>
                  </div>
                  <div className="min-w-[140px]"><label className={LABEL}>Field (optional)</label><input className={FIELD} value={flagField} onChange={(e) => { touch("flag"); setFlagField(e.target.value); }} /></div>
                </div>
                <div className="flex flex-wrap gap-3">
                  <div className="min-w-[140px] flex-1"><label className={LABEL}>Observed (optional)</label><input className={FIELD} value={flagObserved} onChange={(e) => { touch("flag"); setFlagObserved(e.target.value); }} /></div>
                  <div className="min-w-[140px] flex-1"><label className={LABEL}>Expected (optional)</label><input className={FIELD} value={flagExpected} onChange={(e) => { touch("flag"); setFlagExpected(e.target.value); }} /></div>
                </div>
                <div><label className={LABEL}>Reason</label><textarea className={cn(FIELD, "font-sans")} rows={2} value={flagReason} placeholder="Why is the scoring wrong for these roles?" onChange={(e) => { touch("flag"); setFlagReason(e.target.value); }} /></div>
              </div>
            )}

            {activeTab === "note" && (
              <div><label className={LABEL}>Note</label><textarea className={cn(FIELD, "font-sans")} rows={3} value={noteText} placeholder="Note appended to each selected role…" onChange={(e) => { touch("note"); setNoteText(e.target.value); }} /></div>
            )}
          </div>

          <div className="mt-[14px] flex items-center gap-2 border-t border-line pt-[12px]">
            <span className="text-[12px] text-ink-soft">
              {includedKinds.length === 0
                ? "No changes staged yet"
                : `${includedKinds.length} change${includedKinds.length === 1 ? "" : "s"} staged${invalidKinds.length ? ` · ${invalidKinds.map((k) => TAB_LABEL[k]).join(", ")} needs text` : ""}`}
            </span>
            <button className={cn(BTN_PRIMARY, "ml-auto")} disabled={!canPreview} onClick={() => setMode("confirm")}>Preview →</button>
            <button className={BTN} onClick={() => setMode("bar")}>Cancel</button>
          </div>
        </Panel>
      </BarShell>
    );
  }

  // ---- Confirmation + execution ---------------------------------------------
  return (
    <BarShell n={n}>
      <Panel title={`Confirm bulk edit · ${n} role${n === 1 ? "" : "s"}`} wide>
        <div className="mb-[8px] flex flex-wrap gap-[5px]">
          {stagedActions.map((a, i) => (
            <span key={i} className="rounded-full bg-[#eef4ff] px-[9px] py-[2px] text-[11.5px] font-semibold text-[#2f5fd0]">{actionSummary(a)}</span>
          ))}
        </div>
        <p className="mb-[10px] text-[12.5px] text-ink-soft">
          {opsToApply} change{opsToApply === 1 ? "" : "s"} across {rolesAffected} role{rolesAffected === 1 ? "" : "s"}
          {opsSkipped > 0 && <> · {opsSkipped} skipped</>}
        </p>

        <div className="max-h-[34vh] space-y-[4px] overflow-y-auto pr-1">
          {plan.map(({ job, items }) => (
            <div key={job.job_id} className="rounded-md bg-[#f7f9fc] px-[8px] py-[6px]">
              <div className="flex gap-2 text-[12.5px]">
                <span className="w-[130px] shrink-0 truncate font-semibold">{job.company}</span>
                <span className="flex-1 truncate text-ink-soft">{job.title}</span>
              </div>
              <div className="mt-[4px] flex flex-wrap gap-[5px]">
                {items.map((it, i) => (
                  <span key={i} className={cn("rounded px-[7px] py-px text-[11px]", it.skipReason ? "bg-[#f6efe6] text-[#8a5a14]" : "bg-[#e9f3ec] text-[#1f7a45]")}>
                    {it.skipReason ? `${TAB_LABEL[it.action.kind]} skipped — ${it.skipReason}` : rowOutcomeText(it.action, job)}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>

        {mode === "running" && (
          <p className="mt-3 flex items-center gap-2 text-[12.5px] text-ink-soft">
            <Loader2 className="h-4 w-4 animate-spin" /> Applying {progress.done} of {progress.total}…
          </p>
        )}

        <div className="mt-3 flex gap-2">
          <button className={BTN} disabled={mode === "running"} onClick={() => setMode("compose")}>← Back</button>
          <button className={BTN_PRIMARY} disabled={mode === "running" || opsToApply === 0} onClick={() => void apply()}>
            Apply {opsToApply} change{opsToApply === 1 ? "" : "s"}
          </button>
          <button className={BTN} disabled={mode === "running"} onClick={onDeselectAll}>Cancel</button>
        </div>
      </Panel>
    </BarShell>
  );
}

// Sticky bottom bar chrome — the selection count header sits above the action row / panel.
function BarShell({ n, children }: { n: number; children: React.ReactNode }) {
  return (
    <div className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-panel shadow-[0_-8px_30px_rgba(20,26,38,.14)]">
      <div className="mx-auto max-w-[1200px] px-[18px] py-[10px]">
        <div className="mb-[6px] text-[11px] font-bold uppercase tracking-wide text-ink-soft">{n} selected</div>
        <div className="flex flex-wrap items-center gap-[8px]">{children}</div>
      </div>
    </div>
  );
}

function Panel({ title, wide, children }: { title: string; wide?: boolean; children: React.ReactNode }) {
  return (
    <div className={cn("w-full rounded-lg border border-line bg-[#fbfcfe] p-[14px]", wide ? "" : "max-w-[720px]")}>
      <h3 className="mb-[10px] text-[11px] font-bold uppercase tracking-wide text-brand">{title}</h3>
      {children}
    </div>
  );
}
