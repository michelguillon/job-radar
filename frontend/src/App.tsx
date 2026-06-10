import { useEffect, useMemo, useState } from "react";
import { Lock, ShieldCheck } from "lucide-react";
import type { Job } from "@/lib/api";
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
      <button className="owner-tag" onClick={() => void requestUnlock()} title="Unlock owner access">
        <Lock className="h-3.5 w-3.5" /> Unlock
      </button>
    );
  }
  return (
    <div className="owner-tag">
      <ShieldCheck className="h-3.5 w-3.5" /> owner
      <button onClick={() => void lock()} title="Lock" style={{ background: "none", border: 0, cursor: "pointer" }}>
        <Lock className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

function Shell() {
  const { data, error, loading, refetch } = useIndex();
  const [view, setView] = useState<View>(location.hash === "#pipeline" ? "pipeline" : "browse");
  const [filters, setFilters] = useState<Filters>(emptyFilters);
  const [sort, setSort] = useState<Sort>({ key: "priority_score", dir: "desc" });
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // Bookmarkable #browse / #pipeline (parity with the Phase 5 hash routing).
  useEffect(() => {
    const onHash = () => setView(location.hash === "#pipeline" ? "pipeline" : "browse");
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  function go(v: View) {
    setView(v);
    if (location.hash !== "#" + v) history.replaceState(null, "", "#" + v);
  }

  // Esc closes the drawer.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setSelectedId(null); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const records = data?.records ?? [];
  const filtered = useMemo(() => applyFilters(records, filters), [records, filters]);
  // Keep the open drawer bound to live data so a write refetch updates it in place.
  const selected = selectedId ? records.find((r) => r.job_id === selectedId) ?? null : null;

  function toggleSort(key: keyof Job) {
    setSort((s) =>
      s.key === key
        ? { key, dir: s.dir === "asc" ? "desc" : "asc" }
        : { key, dir: key === "company" || key === "title" || key === "location" ? "asc" : "desc" },
    );
  }

  function reset() {
    setFilters(emptyFilters());
  }

  if (error) {
    return (
      <p style={{ padding: 40, color: "#9a3636" }}>
        Could not load <code>/api/index</code>: {error}.<br />
        Is the API up (<code>docker compose --profile ui up</code>) and has{" "}
        <code>python -m cli.stats --export-index</code> been run?
      </p>
    );
  }

  return (
    <>
      <header className="topbar">
        <div className="brand">
          <span className="logo">◎</span> Job&nbsp;Radar
          {data?.generated_at && <span className="generated">· built {fmtDate(data.generated_at)}</span>}
        </div>
        <div style={{ display: "flex", gap: 18, alignItems: "center", flexWrap: "wrap" }}>
          <StatBar stats={data?.stats ?? null} />
          <OwnerIndicator />
        </div>
      </header>

      <div className="tabs">
        <button className={"tab" + (view === "browse" ? " active" : "")} onClick={() => go("browse")}>Browse</button>
        <button className={"tab" + (view === "pipeline" ? " active" : "")} onClick={() => go("pipeline")}>Pipeline</button>
        <span className="result-count">
          {loading ? "loading…" : `${filtered.length} of ${records.length} roles`}
        </span>
      </div>

      <main className="layout">
        <Sidebar records={records} filters={filters} setFilters={setFilters} onReset={reset} />
        <section className="content">
          {view === "browse"
            ? <BrowseView rows={filtered} sort={sort} onSort={toggleSort} onOpen={(j) => setSelectedId(j.job_id)} />
            : <PipelineView rows={filtered} onOpen={(j) => setSelectedId(j.job_id)} />}
        </section>
      </main>

      {selected && (
        <DetailPanel job={selected} onClose={() => setSelectedId(null)} onChanged={refetch} />
      )}
    </>
  );
}

export default function App() {
  return (
    <UnlockProvider>
      <Shell />
    </UnlockProvider>
  );
}
