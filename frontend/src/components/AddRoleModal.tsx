import { useState } from "react";
import { Loader2, Plus } from "lucide-react";
import { api, ApiError, type ManualIngestResult } from "@/lib/api";
import { cn } from "@/lib/utils";
import { fitBadgeClass, TOAST } from "@/lib/ui";
import { LABEL_TEXT } from "@/lib/jobs";
import { useUnlock } from "@/components/UnlockProvider";
import { Dialog } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

// "Add role manually" — paste a JD from outside the monitored ATS universe (Workday, custom
// career pages, referrals). Owner-only: the button is hidden unless unlocked. On submit it
// POSTs to /api/manual-ingest, which extracts + scores synchronously (~10–20s) and returns the
// scored result; we refetch the index so the role appears in Browse. All Tailwind, no globals.

const FIELD = "w-full rounded-md border border-line px-[9px] py-[6px] text-[13px] focus:border-brand focus:outline-none disabled:opacity-50";
const LABEL = "block text-[11px] text-ink-soft mb-[3px]";

export function AddRoleModal({ onAdded }: { onAdded: () => Promise<void> }) {
  const { unlocked, requestUnlock } = useUnlock();
  const [open, setOpen] = useState(false);
  const [company, setCompany] = useState("");
  const [title, setTitle] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [notes, setNotes] = useState("");
  const [rawText, setRawText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [result, setResult] = useState<ManualIngestResult | null>(null);

  if (!unlocked) return null; // owner-only affordance

  function reset() {
    setCompany(""); setTitle(""); setSourceUrl(""); setNotes(""); setRawText("");
    setErr(null); setResult(null); setBusy(false);
  }
  function close() {
    if (busy) return; // never close mid-flight
    setOpen(false);
    reset();
  }
  async function openModal() {
    if (!(await requestUnlock())) return;
    reset();
    setOpen(true);
  }

  async function submit() {
    setErr(null);
    if (!company.trim() || !title.trim()) { setErr("Company and role title are required."); return; }
    if (rawText.trim().length < 200) { setErr("Paste the full job description (at least 200 characters)."); return; }
    setBusy(true);
    try {
      const res = await api.manualIngest({
        company: company.trim(), title: title.trim(), raw_text: rawText,
        source_url: sourceUrl.trim() || undefined, notes: notes.trim() || undefined,
      });
      setResult(res);
      await onAdded(); // role now in Browse
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setErr("This role is already in your corpus.");
      else if (e instanceof ApiError && e.status === 422) setErr(e.message);
      else setErr(e instanceof Error ? e.message : "Something went wrong — try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button
        onClick={() => void openModal()}
        className="mt-[10px] flex w-full items-center justify-center gap-[6px] rounded-md border border-brand bg-brand py-[7px] text-[12.5px] font-semibold text-white hover:bg-[#245fd0]"
      >
        <Plus className="h-3.5 w-3.5" /> Add role manually
      </button>

      <Dialog
        open={open} onClose={close} title="Add role manually"
        description="Paste a job description from any source — it's extracted, scored, and added to your corpus."
        className="max-w-xl"
      >
        {result ? (
          <div className="space-y-4">
            <div className={cn("rounded-md px-3 py-2 text-[13px]", TOAST.ok)}>
              Added <span className="font-semibold">{result.title}</span> at <span className="font-semibold">{result.company}</span>.
            </div>
            <div className="flex items-center gap-2 text-[13px]">
              <span className={cn("inline-block rounded-full px-2 py-[2px] text-[11px] font-bold", fitBadgeClass(result.fit_label))}>
                {LABEL_TEXT[result.fit_label] || result.fit_label}
              </span>
              <span className="text-ink-soft">fit {result.fit_score} · priority {result.priority_score}</span>
            </div>
            {result.warnings?.length > 0 && (
              <div className={cn("space-y-1 rounded-md px-3 py-2 text-[12px]", TOAST.warn)}>
                <p className="font-semibold">⚠ Extraction warnings — stored as-is:</p>
                <ul className="list-disc space-y-[2px] pl-4">
                  {result.warnings.map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              </div>
            )}
            <p className="text-[12px] text-ink-faint">It now appears in Browse.</p>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={reset}>Add another</Button>
              <Button onClick={close}>Done</Button>
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            {err && <div className={cn("rounded-md px-3 py-2 text-[13px]", TOAST.err)}>{err}</div>}
            <div className="grid grid-cols-2 gap-3">
              <div><label className={LABEL}>Company *</label><input className={FIELD} value={company} disabled={busy} onChange={(e) => setCompany(e.target.value)} /></div>
              <div><label className={LABEL}>Role title *</label><input className={FIELD} value={title} disabled={busy} onChange={(e) => setTitle(e.target.value)} /></div>
            </div>
            <div><label className={LABEL}>Source URL</label><input className={FIELD} value={sourceUrl} placeholder="https://… (optional)" disabled={busy} onChange={(e) => setSourceUrl(e.target.value)} /></div>
            <div><label className={LABEL}>Notes</label><input className={FIELD} value={notes} placeholder="Owner notes (optional)" disabled={busy} onChange={(e) => setNotes(e.target.value)} /></div>
            <div>
              <label className={LABEL}>Job description *</label>
              <textarea
                className={cn(FIELD, "font-sans")} rows={10} value={rawText} disabled={busy}
                placeholder="Paste the full job description here…" onChange={(e) => setRawText(e.target.value)}
              />
            </div>
            {busy && (
              <div className={cn("rounded-md px-3 py-2 text-[13px]", TOAST.warn)}>
                Extracting and scoring role… this usually takes 10–20 seconds.
              </div>
            )}
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={close} disabled={busy}>Cancel</Button>
              <Button onClick={() => void submit()} disabled={busy}>
                {busy && <Loader2 className="h-4 w-4 animate-spin" />} Add role
              </Button>
            </div>
          </div>
        )}
      </Dialog>
    </>
  );
}
