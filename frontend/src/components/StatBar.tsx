import type { IndexStats } from "@/lib/api";
import { cn } from "@/lib/utils";
import { STATUS_ORDER } from "@/lib/jobs";

function Stat({ value, label }: { value: string | number; label: string }) {
  return (
    <div className="flex flex-col leading-[1.15]">
      <span className="text-[16px] font-bold">{value}</span>
      <span className="text-[10px] uppercase tracking-wide text-[#9fb0d0]">{label}</span>
    </div>
  );
}

export function StatBar({ stats }: { stats: IndexStats | null }) {
  if (!stats) return null;
  const strong = stats.by_fit_label?.strong_fit ?? 0;
  const active = STATUS_ORDER
    .filter((k) => !["new", "rejected", "archived"].includes(k))
    .reduce((n, k) => n + (stats.by_application_status?.[k] ?? 0), 0);

  const dist = stats.fit_score_distribution || {};
  const max = Math.max(1, ...Object.values(dist));

  return (
    <div className="flex flex-wrap items-center gap-[18px]">
      <Stat value={stats.total} label="roles" />
      <Stat value={strong} label="strong fit" />
      <Stat value={active} label="in pipeline" />
      {typeof stats.cost_to_date_usd === "number" && (
        <Stat value={`$${stats.cost_to_date_usd.toFixed(2)}`} label="cost to date" />
      )}
      <div className="flex flex-col leading-[1.15]">
        <div className="flex h-[26px] items-end gap-[2px]" title="fit_score distribution (1–10)">
          {Array.from({ length: 10 }, (_, i) => {
            const score = i + 1;
            const c = dist[String(score)] ?? 0;
            return (
              <div
                key={score}
                className={cn("w-[7px] rounded-t-[1px]", score < 6 ? "bg-[#3a4763]" : "bg-[#4f7fe0]")}
                style={{ height: `${Math.max(2, Math.round((c / max) * 26))}px` }}
                title={`score ${score}: ${c}`}
              />
            );
          })}
        </div>
        <span className="text-[10px] uppercase tracking-wide text-[#9fb0d0]">score 1–10</span>
      </div>
    </div>
  );
}
