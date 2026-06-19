import { useEffect, useMemo, useRef, useState } from "react";
import { Lock, ShieldCheck } from "lucide-react";
import type { Job } from "@/lib/api";
import { cn } from "@/lib/utils";
import { applyFilters, emptyFilters, fmtDate, getActiveCompanies, type Filters, type Sort } from "@/lib/jobs";
import { TOAST } from "@/lib/ui";
import { useIndex } from "@/hooks/useIndex";
import { UnlockProvider, useUnlock } from "@/components/UnlockProvider";
import { StatBar } from "@/components/StatBar";
import { Sidebar } from "@/components/Sidebar";
import { BrowseView } from "@/components/BrowseView";
import { BulkActionBar } from "@/components/BulkActionBar";
import { PipelineView } from "@/components/PipelineView";
import { DetailPanel } from "@/components/DetailPanel";

type View = "browse" | "pipeline";
type AppToast = { kind: "ok" | "warn" | "err"; text: string } | null;

function OwnerIndicator() {
  const { configured, unlocked, requestUnlock, lock } = useUnlock();
  if (!configured) return null;
  if (!unlocked) {
    return (
      <button onClick={() => void requestUnlock()} title="Unlock owner access"
        className="flex items-center gap-[6px] text-[12px] text-[#d6e2ff] hover:text-white">
        <Lock className="h-3.5 w-3.5" /> Unlock
      </button>
    );
  }
  return (
    <div className="flex items-center gap-[6px] text-[12px] text-[#d6e2ff]">
      <ShieldCheck className="h-3.5 w-3.5" /> owner
      <button onClick={() => void lock()} title="Lock" className="hover:text-white">
        <Lock className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

function Tab({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button onClick={onClick}
      className={cn(
        "border-b-[2.5px] px-[14px] py-[11px] text-[13.5px] font-semibold",
        active ? "border-brand text-brand" : "border-transparent text-ink-soft hover:text-ink",
      )}>
      {children}
    </button>
  );
}

function Shell() {
  const { data, error, loading, refetch } = useIndex();
  const { configured } = useUnlock();
  const [view, setView] = useState<View>(location.hash === "#pipeline" ? "pipeline" : "browse");
  const [filters, setFiltersRaw] = useState<Filters>(emptyFilters);
  const [sort, setSort] = useState<Sort>({ key: "priority_score", dir: "desc" });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // Bulk selection (SPEC_BULK_ACTIONS) — session-only, Browse-only, owner-gated.
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [toast, setToast] = useState<AppToast>(null);
  const toastTimer = useRef<number | null>(null);

  function pushToast(kind: "ok" | "warn" | "err", text: string) {
    setToast({ kind, text });
    if (toastTimer.current) window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 4000);
  }

  // Changing any filter invalidates the current selection (a hidden role can't be acted on).
  function setFilters(next: Filters) {
    setFiltersRaw(next);
    if (selectedIds.size) {
      setSelectedIds(new Set());
      pushToast("warn", "Selection cleared — filters changed");
    }
  }
  function toggleSelect(jobId: string) {
    setSelectedIds((prev) => {
      const n = new Set(prev);
      if (n.has(jobId)) n.delete(jobId); else n.add(jobId);
      return n;
    });
  }
  function selectAll(jobIds: string[], checked: boolean) {
    setSelectedIds((prev) => {
      const n = new Set(prev);
      for (const id of jobIds) { if (checked) n.add(id); else n.delete(id); }
      return n;
    });
  }
  async function onBulkComplete() {
    await refetch();
    setSelectedIds(new Set());
  }

  useEffect(() => {
    const onHash = () => setView(location.hash === "#pipeline" ? "pipeline" : "browse");
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  function go(v: View) {
    setView(v);
    if (location.hash !== "#" + v) history.replaceState(null, "", "#" + v);
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setSelectedId(null); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const records = data?.records ?? [];
  const filtered = useMemo(() => applyFilters(records, filters), [records, filters]);
  // Active companies drive the detail-panel context line + the will-not-apply reason
  // pre-select (SPEC_ACTIVE_COMPANY_FILTER §12, §5) — derived from the full record set.
  const activeCompanies = useMemo(() => getActiveCompanies(records), [records]);
  const selected = selectedId ? records.find((r) => r.job_id === selectedId) ?? null : null;
  const selectedJobs = useMemo(() => records.filter((r) => selectedIds.has(r.job_id)), [records, selectedIds]);
  const showBulk = configured && view === "browse" && selectedJobs.length > 0;

  function toggleSort(key: keyof Job) {
    setSort((s) =>
      s.key === key
        ? { key, dir: s.dir === "asc" ? "desc" : "asc" }
        : { key, dir: key === "company" || key === "title" || key === "location" ? "asc" : "desc" },
    );
  }

  if (error) {
    return (
      <p className="p-10 text-[#9a3636]">
        Could not load <code>/api/index</code>: {error}.<br />
        Is the API up (<code>docker compose --profile ui up</code>) and has <code>python -m cli.stats --export-index</code> been run?
      </p>
    );
  }

  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex flex-wrap items-center justify-between gap-6 bg-ink px-[18px] py-[10px] text-white">
        <div className="flex items-center text-[16px] font-semibold tracking-[.2px]">
          <span className="mr-[6px] text-[#6ea8ff]">◎</span> Job&nbsp;Radar
          {data?.generated_at && <span className="ml-[10px] text-[11px] font-normal text-[#9fb0d0]">· built {fmtDate(data.generated_at)}</span>}
        </div>
        <div className="flex flex-wrap items-center gap-[18px]">
          <StatBar stats={data?.stats ?? null} />
          <OwnerIndicator />
        </div>
      </header>

      <div className="flex items-center gap-1 border-b border-line bg-panel px-[18px]">
        <Tab active={view === "browse"} onClick={() => go("browse")}>Browse</Tab>
        <Tab active={view === "pipeline"} onClick={() => go("pipeline")}>Pipeline</Tab>
        <span className="ml-auto text-[12px] text-ink-faint">
          {loading ? "loading…" : `${filtered.length} of ${records.length} roles`}
        </span>
      </div>

      <main className="flex min-h-0 flex-1">
        <Sidebar records={records} filters={filters} setFilters={setFilters} onReset={() => setFilters(emptyFilters())} onAdded={refetch} onOpenRole={setSelectedId} />
        <section className={cn("flex-1 overflow-auto px-[18px] pt-[14px]", showBulk ? "pb-28" : "pb-10")}>
          {view === "browse"
            ? <BrowseView rows={filtered} sort={sort} onSort={toggleSort} onOpen={(j) => setSelectedId(j.job_id)}
                selectable={configured} selectedIds={selectedIds} onToggle={toggleSelect} onSelectAll={selectAll} />
            : <PipelineView rows={filtered} onOpen={(j) => setSelectedId(j.job_id)} />}
        </section>
      </main>

      {selected && <DetailPanel job={selected} activeCompanies={activeCompanies} onClose={() => setSelectedId(null)} onChanged={refetch} />}

      {showBulk && (
        <BulkActionBar selectedJobs={selectedJobs} onDeselectAll={() => setSelectedIds(new Set())} onComplete={onBulkComplete} pushToast={pushToast} />
      )}

      {toast && (
        <div className={cn("fixed bottom-4 right-4 z-[60] rounded-md px-[14px] py-[10px] text-[13px] shadow-lg", TOAST[toast.kind])}>
          {toast.text}
        </div>
      )}
    </div>
  );
}

export default function App() {
  return (
    <UnlockProvider>
      <Shell />
    </UnlockProvider>
  );
}
