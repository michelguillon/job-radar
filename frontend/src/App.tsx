import { useEffect, useMemo, useState } from "react";
import { Lock, ShieldCheck } from "lucide-react";
import type { Job } from "@/lib/api";
import { cn } from "@/lib/utils";
import { applyFilters, emptyFilters, fmtDate, type Filters, type Sort } from "@/lib/jobs";
import { useIndex } from "@/hooks/useIndex";
import { UnlockProvider, useUnlock } from "@/components/UnlockProvider";
import { StatBar } from "@/components/StatBar";
import { Sidebar } from "@/components/Sidebar";
import { BrowseView } from "@/components/BrowseView";
import { PipelineView } from "@/components/PipelineView";
import { DetailPanel } from "@/components/DetailPanel";

type View = "browse" | "pipeline";

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
  const [view, setView] = useState<View>(location.hash === "#pipeline" ? "pipeline" : "browse");
  const [filters, setFilters] = useState<Filters>(emptyFilters);
  const [sort, setSort] = useState<Sort>({ key: "priority_score", dir: "desc" });
  const [selectedId, setSelectedId] = useState<string | null>(null);

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
  const selected = selectedId ? records.find((r) => r.job_id === selectedId) ?? null : null;

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
        <section className="flex-1 overflow-auto px-[18px] pb-10 pt-[14px]">
          {view === "browse"
            ? <BrowseView rows={filtered} sort={sort} onSort={toggleSort} onOpen={(j) => setSelectedId(j.job_id)} />
            : <PipelineView rows={filtered} onOpen={(j) => setSelectedId(j.job_id)} />}
        </section>
      </main>

      {selected && <DetailPanel job={selected} onClose={() => setSelectedId(null)} onChanged={refetch} />}
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
