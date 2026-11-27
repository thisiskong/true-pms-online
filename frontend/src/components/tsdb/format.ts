// Formatting helpers for tsdb values and epoch-ms timestamps (shown as Bangkok wall-clock time).

const DT = new Intl.DateTimeFormat("sv-SE", {
  timeZone: "Asia/Bangkok", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
});

export function fmtMs(ms: number | null | undefined): string {
  return ms === null || ms === undefined ? "—" : DT.format(new Date(ms));
}

export function agoMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  const s = Math.max(0, (Date.now() - ms) / 1000);
  if (s < 90) return "just now";
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400 * 2) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

const COMPACT = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 2 });
const PLAIN = new Intl.NumberFormat("en-US", { maximumFractionDigits: 3 });

/** 1234567 -> "1.23M"; small numbers keep up to 3 decimals. */
export function compact(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return Math.abs(v) >= 10_000 ? COMPACT.format(v) : PLAIN.format(v);
}

export function bytes(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  const u = ["B", "KB", "MB", "GB", "TB", "PB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < u.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v >= 100 || i === 0 ? 0 : 1)} ${u[i]}`;
}

/** "20261126" -> "2026-11-26" */
export function fmtDay(d: string | null | undefined): string {
  return d && d.length === 8 ? `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6)}` : "—";
}
