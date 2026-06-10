// Style decided in JS, not global CSS classes — a value (fit label / status) maps to a
// full Tailwind class string. Tailwind's JIT picks up these literal arbitrary-value classes
// from source, so there's no global namespace to collide with (the `.grid` bug, never again).

// fit_label → badge classes. Colours ported from the Phase 5 palette.
const FIT_BADGE: Record<string, string> = {
  strong_fit: "bg-[#1f9d57] text-white",
  good_fit: "bg-[#2f8fbf] text-white",
  stretch: "bg-[#c98a16] text-white",
  blocked_fit: "bg-[#98a0ad] text-white",
  interview_practice: "bg-[#8257d6] text-white",
  income_bridge: "bg-[#c4632a] text-white",
};

export function fitBadgeClass(label: string): string {
  return FIT_BADGE[label] ?? "bg-ink-faint text-white";
}

// (effective) status → pill classes. Grouped by where the role sits.
const STATUS_PILL: Record<string, string> = {
  applied: "bg-[#e6f3ec] text-[#1f7a45]",
  interviewing: "bg-[#e6f3ec] text-[#1f7a45]",
  offer: "bg-[#e6f3ec] text-[#1f7a45]",
  shortlisted: "bg-[#eaf1ff] text-[#2f5fd0]",
  review: "bg-[#eaf1ff] text-[#2f5fd0]",
  rejected: "bg-[#f3e9e9] text-[#9a5252]",
  archived: "bg-[#f3e9e9] text-[#9a5252]",
};

export function statusPillClass(status: string): string {
  return STATUS_PILL[status] ?? "bg-line-soft text-ink-soft";
}

// chip tones for the detail panel
export const CHIP = {
  default: "bg-line-soft text-ink",
  warn: "bg-[#f6e9d8] text-[#8a5a14]",
  block: "bg-[#f3dede] text-[#9a3636]",
} as const;

// toast tones
export const TOAST = {
  ok: "bg-[#e6f3ec] text-[#1f7a45]",
  warn: "bg-[#f6e9d8] text-[#8a5a14]",
  err: "bg-[#f3dede] text-[#9a3636]",
} as const;
