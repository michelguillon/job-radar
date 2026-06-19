import { useCallback, useEffect, useMemo, useState } from "react";
import { Download, Loader2, Pause, Pencil, Plus, Trash2, X } from "lucide-react";
import { api, ApiError, COMPANIES_EXPORT_URL, type Company } from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  actionClass, ACTIONS, ATS_OPTIONS, CompanySortKey, DOMAIN_VOCABULARY, filterCompanies,
  FIT_HYPOTHESES, fitHypothesisClass, isMuted, sortCompanies,
} from "@/lib/companies";
import { useUnlock } from "@/components/UnlockProvider";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { AddCompanyModal } from "@/components/AddCompanyModal";

// Company-universe management (SPEC_COMPANY_SEEDS_DB §5). Owner-only view (the App tab is hidden
// unless write_configured). Reads GET /api/companies; edits via PATCH; add/delete via the row
// actions + modal. All Tailwind, no global classes (frontend/CLAUDE.md).

type Toast = (kind: "ok" | "warn" | "err", text: string) => void;

const COLUMNS: Array<{ label: string; sort?: CompanySortKey; width: string }> = [
  { label: "Name", sort: "name", width: "20%" },
  { label: "ATS", width: "11%" },
  { label: "Domain", sort: "domain", width: "20%" },
  { label: "Fit", sort: "fit_hypothesis", width: "11%" },
  { label: "Action", sort: "action", width: "13%" },
  { label: "Notes", width: "17%" },
  { label: "", width: "8%" },
];

// One inline-editable cell: click to edit (select for vocab fields, text for notes); save on
// Enter/blur, cancel on Escape. Owner unlock is requested by the parent's onSave.
function EditableCell({
  value, options, onSave, render, placeholder,
}: {
  value: string;
  options?: readonly string[];
  onSave: (next: string) => Promise<void>;
  render: (v: string) => React.ReactNode;
  placeholder?: string;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);

  async function commit(next: string) {
    setEditing(false);
    if (next === value) return;
    await onSave(next);
  }

  if (!editing) {
    return (
      <button
        className="w-full cursor-pointer truncate text-left hover:underline decoration-dotted"
        title="Click to edit"
        onClick={(e) => { e.stopPropagation(); setDraft(value); setEditing(true); }}
      >
        {render(value)}
      </button>
    );
  }

  if (options) {
    return (
      <select
        autoFocus
        className="w-full rounded-md border border-brand px-1 py-[3px] text-[12px] focus:outline-none"
        value={draft}
        onChange={(e) => { setDraft(e.target.value); void commit(e.target.value); }}
        onBlur={() => setEditing(false)}
        onKeyDown={(e) => { if (e.key === "Escape") setEditing(false); }}
      >
        {/* allow clearing an optional field */}
        <option value="">—</option>
        {options.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    );
  }

  return (
    <input
      autoFocus
      className="w-full rounded-md border border-brand px-1 py-[3px] text-[12px] focus:outline-none"
      value={draft}
      placeholder={placeholder}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => void commit(draft)}
      onKeyDown={(e) => {
        if (e.key === "Enter") void commit(draft);
        if (e.key === "Escape") setEditing(false);
      }}
    />
  );
}

function Pill({ className, children }: { className: string; children: React.ReactNode }) {
  return <span className={cn("inline-block rounded-full px-2 py-[2px] text-[11px] font-semibold", className)}>{children}</span>;
}

export function CompaniesView({ pushToast }: { pushToast: Toast }) {
  const { requestUnlock } = useUnlock();
  const [rows, setRows] = useState<Company[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<{ key: CompanySortKey; dir: "asc" | "desc" }>({ key: "name", dir: "asc" });
  const [addOpen, setAddOpen] = useState(false);
  const [editing, setEditing] = useState<Company | null>(null);

  const refetch = useCallback(async () => {
    try {
      setRows(await api.companies());
    } catch (e) {
      pushToast("err", e instanceof Error ? e.message : "Failed to load companies");
    } finally {
      setLoading(false);
    }
  }, [pushToast]);

  useEffect(() => { void refetch(); }, [refetch]);

  const view = useMemo(
    () => sortCompanies(filterCompanies(rows, search), sort.key, sort.dir),
    [rows, search, sort],
  );

  function toggleSort(key?: CompanySortKey) {
    if (!key) return;
    setSort((s) => (s.key === key ? { key, dir: s.dir === "asc" ? "desc" : "asc" } : { key, dir: "asc" }));
  }

  // Run a write after ensuring owner unlock; refetch + toast on success, surface errors.
  async function withUnlock(fn: () => Promise<void>, okMsg?: string) {
    if (!(await requestUnlock())) return;
    try {
      await fn();
      await refetch();
      if (okMsg) pushToast("ok", okMsg);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) pushToast("err", e.message);
      else pushToast("err", e instanceof Error ? e.message : "Update failed");
    }
  }

  const patchField = (name: string, field: string, next: string) =>
    withUnlock(async () => { await api.patchCompany(name, { [field]: next || null }); });

  const setAction = (c: Company, action: string) =>
    withUnlock(async () => { await api.patchCompany(c.name, { action }); }, `${c.name} → ${action}`);

  async function remove(c: Company) {
    if (!window.confirm(`Delete ${c.name}? This cannot be undone. (Use "Remove" to keep history instead.)`)) return;
    await withUnlock(() => api.deleteCompany(c.name), `Deleted ${c.name}`);
  }

  return (
    <div className="px-[18px] pb-10 pt-[14px]">
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <h2 className="text-[15px] font-semibold text-ink">
          Company Universe <span className="text-ink-faint">({rows.length})</span>
        </h2>
        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={() => void withUnlock(async () => setAddOpen(true))}
            className="flex items-center gap-[6px] rounded-md border border-brand bg-brand px-3 py-[6px] text-[12.5px] font-semibold text-white hover:bg-[#245fd0]"
          >
            <Plus className="h-3.5 w-3.5" /> Add company
          </button>
          <a
            href={COMPANIES_EXPORT_URL} download
            className="flex items-center gap-[6px] rounded-md border border-line bg-white px-3 py-[6px] text-[12.5px] text-ink-soft hover:bg-line-soft"
          >
            <Download className="h-3.5 w-3.5" /> Export YAML
          </a>
          <input
            type="search" placeholder="Search company…" value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-[180px] rounded-md border border-line bg-white px-[10px] py-[6px] text-[13px] focus:border-brand focus:outline-none"
          />
        </div>
      </div>

      {loading ? (
        <p className="p-10 text-center text-ink-faint">Loading companies…</p>
      ) : (
        <Table>
          <colgroup>{COLUMNS.map((c) => <col key={c.label} style={{ width: c.width }} />)}</colgroup>
          <TableHeader>
            <TableRow className="border-b-line">
              {COLUMNS.map((c) => {
                const on = !!c.sort && c.sort === sort.key;
                return (
                  <TableHead
                    key={c.label}
                    onClick={c.sort ? () => toggleSort(c.sort) : undefined}
                    className={cn(c.sort ? "cursor-pointer hover:text-ink" : "cursor-default")}
                  >
                    {c.label}
                    {on && <span className="text-brand">{sort.dir === "asc" ? " ▴" : " ▾"}</span>}
                  </TableHead>
                );
              })}
            </TableRow>
          </TableHeader>
          <TableBody>
            {view.map((c) => {
              const muted = isMuted(c);
              return (
                <TableRow key={c.name} className={cn("group hover:bg-rowhover", muted && "opacity-50")}>
                  <TableCell className={cn("font-semibold", muted && "italic")}>
                    {c.name}
                    {c.slug && <span className="ml-[6px] text-[11px] font-normal text-ink-faint">{c.slug}</span>}
                  </TableCell>
                  <TableCell>
                    <EditableCell
                      value={c.ats} options={ATS_OPTIONS}
                      onSave={(v) => patchField(c.name, "ats", v)}
                      render={(v) => <span className="text-[12px] text-ink-soft">{v || "—"}</span>}
                    />
                  </TableCell>
                  <TableCell>
                    <EditableCell
                      value={c.domain ?? ""} options={DOMAIN_VOCABULARY}
                      onSave={(v) => patchField(c.name, "domain", v)}
                      render={(v) => <span className="text-[12px] text-ink-soft">{v || "—"}</span>}
                    />
                  </TableCell>
                  <TableCell>
                    <EditableCell
                      value={c.fit_hypothesis ?? ""} options={FIT_HYPOTHESES}
                      onSave={(v) => patchField(c.name, "fit_hypothesis", v)}
                      render={(v) => v ? <Pill className={fitHypothesisClass(v)}>{v}</Pill> : <span className="text-ink-faint">—</span>}
                    />
                  </TableCell>
                  <TableCell>
                    <EditableCell
                      value={c.action} options={ACTIONS}
                      onSave={(v) => patchField(c.name, "action", v || "keep")}
                      render={(v) => <Pill className={actionClass(v)}>{v}</Pill>}
                    />
                  </TableCell>
                  <TableCell>
                    <EditableCell
                      value={c.notes} placeholder="notes…"
                      onSave={(v) => patchField(c.name, "notes", v)}
                      render={(v) => <span className="block truncate text-[12px] text-ink-soft" title={v}>{v || "—"}</span>}
                    />
                  </TableCell>
                  <TableCell className="overflow-visible text-clip">
                    <div className="flex items-center justify-end gap-1 opacity-0 transition-opacity group-hover:opacity-100">
                      <IconBtn title="Edit" onClick={() => void withUnlock(async () => setEditing(c))}><Pencil className="h-3.5 w-3.5" /></IconBtn>
                      {c.action !== "pause" && <IconBtn title="Pause" onClick={() => void setAction(c, "pause")}><Pause className="h-3.5 w-3.5" /></IconBtn>}
                      {c.action !== "remove" && <IconBtn title="Remove (keep history)" onClick={() => void setAction(c, "remove")}><X className="h-3.5 w-3.5" /></IconBtn>}
                      <IconBtn title="Delete permanently" danger onClick={() => void remove(c)}><Trash2 className="h-3.5 w-3.5" /></IconBtn>
                    </div>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      )}
      {!loading && !view.length && <p className="p-10 text-center text-ink-faint">No companies match the search.</p>}

      {(addOpen || editing) && (
        <AddCompanyModal
          existing={editing}
          onClose={() => { setAddOpen(false); setEditing(null); }}
          onSaved={async (name, created) => {
            setAddOpen(false); setEditing(null);
            await refetch();
            pushToast("ok", created ? `Added: ${name}` : `Updated: ${name}`);
          }}
          pushToast={pushToast}
        />
      )}
    </div>
  );
}

function IconBtn({ title, danger, onClick, children }: { title: string; danger?: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      title={title} onClick={(e) => { e.stopPropagation(); onClick(); }}
      className={cn(
        "rounded-md border border-line bg-white p-[5px] text-ink-soft hover:bg-line-soft",
        danger && "hover:border-[#d8b4b4] hover:text-[#9a3636]",
      )}
    >
      {children}
    </button>
  );
}
