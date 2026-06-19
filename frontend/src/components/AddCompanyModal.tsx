import { useState } from "react";
import { Loader2, Search } from "lucide-react";
import { api, ApiError, type Company } from "@/lib/api";
import { cn } from "@/lib/utils";
import { TOAST } from "@/lib/ui";
import { ACTIONS, ATS_OPTIONS, DOMAIN_VOCABULARY, FIT_HYPOTHESES } from "@/lib/companies";
import { Dialog } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

// Add or edit a company (SPEC_COMPANY_SEEDS_DB §5.2). `existing` switches to edit mode (PATCH,
// name locked); otherwise it's an add (POST) with the "Find ATS" auto-discovery probe. Owner
// unlock is requested by the parent before this opens. All Tailwind, no globals.

const FIELD = "w-full rounded-md border border-line px-[9px] py-[6px] text-[13px] focus:border-brand focus:outline-none disabled:opacity-50";
const LABEL = "block text-[11px] text-ink-soft mb-[3px]";

type Toast = (kind: "ok" | "warn" | "err", text: string) => void;

export function AddCompanyModal({
  existing, onClose, onSaved, pushToast,
}: {
  existing: Company | null;
  onClose: () => void;
  onSaved: (name: string, created: boolean) => Promise<void>;
  pushToast: Toast;
}) {
  const isEdit = existing !== null;
  const [name, setName] = useState(existing?.name ?? "");
  const [ats, setAts] = useState(existing?.ats ?? "greenhouse");
  const [slug, setSlug] = useState(existing?.slug ?? "");
  const [domain, setDomain] = useState(existing?.domain ?? "");
  const [fit, setFit] = useState(existing?.fit_hypothesis ?? "");
  const [action, setAction] = useState(existing?.action ?? "keep");
  const [notes, setNotes] = useState(existing?.notes ?? "");
  const [busy, setBusy] = useState(false);
  const [probing, setProbing] = useState(false);
  const [probeMsg, setProbeMsg] = useState<{ kind: "ok" | "warn"; text: string } | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function findAts() {
    if (!name.trim()) { setErr("Enter a company name first."); return; }
    setProbing(true); setProbeMsg(null); setErr(null);
    try {
      const res = await api.probeAts(name.trim());
      if (res.found && res.ats) {
        setAts(res.ats);
        setSlug(res.slug ?? "");
        setProbeMsg({ kind: "ok", text: `✓ Found: ${res.ats}  slug=${res.slug}` });
      } else {
        setAts("manual");
        setProbeMsg({ kind: "warn", text: "Not found — set manually" });
      }
    } catch (e) {
      setProbeMsg({ kind: "warn", text: e instanceof Error ? e.message : "Probe failed" });
    } finally {
      setProbing(false);
    }
  }

  async function save() {
    setErr(null);
    if (!name.trim() || !ats.trim()) { setErr("Company name and ATS are required."); return; }
    setBusy(true);
    try {
      const payload = {
        slug: slug.trim() || null,
        domain: domain || null,
        fit_hypothesis: fit || null,
        action: action || "keep",
        notes: notes.trim(),
      };
      if (isEdit) {
        await api.patchCompany(existing.name, { ats, ...payload });
      } else {
        await api.createCompany({ name: name.trim(), ats, ...payload });
      }
      await onSaved(name.trim(), !isEdit);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setErr("A company with that name already exists.");
      else setErr(e instanceof Error ? e.message : "Save failed");
      pushToast("err", "Could not save company");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open onClose={() => { if (!busy) onClose(); }}
      title={isEdit ? `Edit ${existing.name}` : "Add company"}
      description={isEdit ? "Update this company's metadata." : "Add a company to the monitored universe."}
      className="max-w-md"
    >
      <div className="space-y-3">
        {err && <div className={cn("rounded-md px-3 py-2 text-[13px]", TOAST.err)}>{err}</div>}

        <div>
          <label className={LABEL}>Company name *</label>
          <input className={FIELD} value={name} disabled={isEdit || busy} onChange={(e) => setName(e.target.value)} />
          {!isEdit && (
            <div className="mt-[6px] flex items-center gap-2">
              <button
                onClick={() => void findAts()} disabled={probing || busy}
                className="flex items-center gap-[5px] rounded-md border border-line bg-white px-[10px] py-[5px] text-[12px] text-ink-soft hover:bg-line-soft disabled:opacity-50"
              >
                {probing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Search className="h-3.5 w-3.5" />} Find ATS
              </button>
              {probeMsg && (
                <span className={cn("text-[12px]", probeMsg.kind === "ok" ? "text-[#1f7a45]" : "text-[#8a5a14]")}>
                  {probeMsg.text}
                </span>
              )}
            </div>
          )}
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={LABEL}>ATS *</label>
            <select className={FIELD} value={ats} disabled={busy} onChange={(e) => setAts(e.target.value)}>
              {ATS_OPTIONS.map((o) => <option key={o} value={o}>{o}</option>)}
            </select>
          </div>
          <div>
            <label className={LABEL}>Slug</label>
            <input className={FIELD} value={slug} disabled={busy} onChange={(e) => setSlug(e.target.value)} />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={LABEL}>Domain</label>
            <select className={FIELD} value={domain} disabled={busy} onChange={(e) => setDomain(e.target.value)}>
              <option value="">—</option>
              {DOMAIN_VOCABULARY.map((o) => <option key={o} value={o}>{o}</option>)}
            </select>
          </div>
          <div>
            <label className={LABEL}>Fit hypothesis</label>
            <select className={FIELD} value={fit} disabled={busy} onChange={(e) => setFit(e.target.value)}>
              <option value="">—</option>
              {FIT_HYPOTHESES.map((o) => <option key={o} value={o}>{o}</option>)}
            </select>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={LABEL}>Action</label>
            <select className={FIELD} value={action} disabled={busy} onChange={(e) => setAction(e.target.value)}>
              {ACTIONS.map((o) => <option key={o} value={o}>{o}</option>)}
            </select>
          </div>
        </div>

        <div>
          <label className={LABEL}>Notes</label>
          <input className={FIELD} value={notes} disabled={busy} onChange={(e) => setNotes(e.target.value)} />
        </div>

        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button onClick={() => void save()} disabled={busy}>
            {busy && <Loader2 className="h-4 w-4 animate-spin" />} {isEdit ? "Save" : "Add company"}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
