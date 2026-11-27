// Shared visual language for fiber scores (docs/fiber-score-ui.md §5).
import type { Attribution, Level } from "../../api/fiber";
import { cx } from "../ui";

export const BAD_SCORE = 4;

type Tone = { label: string; chip: string; hollow: string; bar: string; hex: string };

const POOR: Tone = { label: "Poor", chip: "bg-red-600 text-white", hollow: "text-red-700 ring-red-600", bar: "bg-red-600", hex: "#dc2626" };
const WEAK: Tone = { label: "Weak", chip: "bg-orange-500 text-white", hollow: "text-orange-600 ring-orange-500", bar: "bg-orange-500", hex: "#f97316" };
const FAIR: Tone = { label: "Fair", chip: "bg-amber-400 text-amber-950", hollow: "text-amber-700 ring-amber-400", bar: "bg-amber-400", hex: "#fbbf24" };
const GOOD: Tone = { label: "Good", chip: "bg-emerald-600 text-white", hollow: "text-emerald-700 ring-emerald-600", bar: "bg-emerald-600", hex: "#059669" };

export function scoreTone(score: number): Tone {
  if (score <= 3) return POOR;
  if (score <= 5) return WEAK;
  if (score <= 7) return FAIR;
  return GOOD;
}

/** Round chip with the number inside. Low confidence (< 0.5) renders hollow. */
export function ScoreChip({ score, conf, size = "sm" }: { score: number | null | undefined; conf?: number | null; size?: "sm" | "lg" }) {
  if (score == null) return <span className="text-zinc-300">—</span>;
  const t = scoreTone(score);
  const low = conf != null && conf < 0.5;
  const dim = size === "lg" ? "size-12 text-xl" : "size-6 text-xs";
  return (
    <span title={`${t.label} · score ${score}/10${conf != null ? ` · confidence ${conf.toFixed(2)}` : ""}${low ? " (low)" : ""}`}
      className={cx("inline-flex shrink-0 items-center justify-center rounded-full font-semibold tabular-nums", dim,
        low ? cx("bg-white ring-2 ring-inset", t.hollow) : t.chip)}>
      {score}
    </span>
  );
}

export function db(v: number | null | undefined, digits = 1, signed = false): string {
  if (v == null) return "—";
  const s = v.toFixed(digits);
  return signed && v > 0 ? `+${s}` : s;
}

/** Excess loss / peer delta: bold past the 3 dB attribution threshold. */
export function Db({ v, signed, warnAbove = 3, unit = true }: { v: number | null | undefined; signed?: boolean; warnAbove?: number; unit?: boolean }) {
  if (v == null) return <span className="text-zinc-300">—</span>;
  const strong = Math.abs(v) >= warnAbove;
  return <span className={cx("tabular-nums", strong ? "font-semibold text-zinc-900" : "text-zinc-600")}>{db(v, 1, signed)}{unit && <span className="font-normal text-zinc-400"> dB</span>}</span>;
}

// Mirrors ml/fiber/ranges.yaml hw_ok (ONU hardware readings considered normal).
export const HW_READINGS = [
  { key: "tx", label: "Tx", unit: "dBm", ok: [0.5, 7], digits: 2 },
  { key: "voltage", label: "Voltage", unit: "V", ok: [3.0, 3.6], digits: 2 },
  { key: "temp", label: "Temp", unit: "°C", ok: [-40, 80], digits: 0 },
  { key: "current", label: "Bias", unit: "mA", ok: [0, 60], digits: 1 },
] as const;

type HwRow = Partial<Record<`${(typeof HW_READINGS)[number]["key"]}_med` | `hw_${(typeof HW_READINGS)[number]["key"]}_days`, number | null>>;

/** Readings that were out of range on at least one day, e.g. ["Tx 7d"]. Empty when the run has no hardware columns. */
export function hwFaults(r: HwRow): string[] {
  return HW_READINGS.filter((h) => (r[`hw_${h.key}_days`] ?? 0) > 0).map((h) => `${h.label} ${r[`hw_${h.key}_days`]}d`);
}

/** "bad/total" with a thin bad-share bar. */
export function BadShare({ bad, total, wide }: { bad: number; total: number; wide?: boolean }) {
  const p = total ? bad / total : 0;
  return (
    <span className="inline-flex items-center gap-2" title={`${bad} of ${total} ONUs scored ${BAD_SCORE} or below`}>
      <span className={cx("tabular-nums", bad ? "text-zinc-900" : "text-zinc-400", wide ? "w-16" : "w-12")}>{bad}/{total}</span>
      <span className={cx("h-1.5 shrink-0 overflow-hidden rounded-full bg-zinc-100", wide ? "w-20" : "w-12")}>
        <span className={cx("block h-full rounded-full", p >= 0.5 ? "bg-red-600" : p >= 0.2 ? "bg-orange-500" : p > 0 ? "bg-amber-400" : "")}
          style={{ width: `${Math.max(p > 0 ? 6 : 0, p * 100)}%` }} />
      </span>
    </span>
  );
}

export const ATTRIBUTION: Record<Attribution, { label: string; hint: string; hex: string }> = {
  drop: { label: "Drop / connector / ONU", hint: "isolated bad ONU whose siblings on the same L2 are healthy", hex: "#71717a" },
  l2: { label: "L2 splitter / distribution", hint: "its L2 group is shifted while sibling L2s on the same L1 are fine", hex: "#f97316" },
  l1: { label: "L1 feeder / PON optic", hint: "the whole PON is affected; L1 maps 1:1 to the PON, so this may be the OLT PON SFP", hex: "#dc2626" },
  device: { label: "OLT / site", hint: "most PONs on the OLT are bad: optics batch, configuration, power or temperature", hex: "#7c3aed" },
  onu_hw: { label: "ONU hardware", hint: "the ONU's own Tx, voltage, temperature or bias current is out of range", hex: "#0ea5e9" },
};

export const ATTRIBUTION_ORDER: Attribution[] = ["drop", "l2", "l1", "device", "onu_hw"];

export const LEVEL_LABEL: Record<Level, string> = { l2: "L2 segment", l1: "L1 / PON", device: "OLT" };

export function AttributionBadge({ a }: { a: Attribution | null | undefined }) {
  if (!a) return <span className="text-zinc-300">—</span>;
  const x = ATTRIBUTION[a];
  return (
    <span title={x.hint} className="inline-flex items-center gap-1.5 text-xs text-zinc-700">
      <span className="size-2 rounded-full" style={{ background: x.hex }} />{x.label}
    </span>
  );
}

export const FIBER_HELP_URL = "/help/fiber-score.html";

export function FiberHelpLink({ className }: { className?: string }) {
  return (
    <a href={FIBER_HELP_URL} target="_blank" rel="noopener"
      className={cx("inline-flex items-center gap-1 text-xs font-medium text-zinc-500 underline-offset-2 hover:text-zinc-900 hover:underline", className)}>
      <span aria-hidden className="inline-flex h-4 w-4 items-center justify-center rounded-full border border-current text-[10px] font-bold">?</span>
      How the fiber score works
    </a>
  );
}
