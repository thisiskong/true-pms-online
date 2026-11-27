// Backend sends ISO strings with +07:00; display as Bangkok wall-clock "YYYY-MM-DD HH:MM".
export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const m = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(iso);
  return m ? `${m[1]} ${m[2]}` : iso;
}

export function ago(iso: string | null | undefined): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "—";
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 90) return "just now";
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400 * 2) return `${Math.round(s / 3600)}h ago`;
  if (s < 86400 * 60) return `${Math.round(s / 86400)}d ago`;
  return `${Math.round(s / (86400 * 30))}mo ago`;
}

export function num(n: number | null | undefined): string {
  return n === null || n === undefined ? "—" : n.toLocaleString("en-US");
}

export function dash(v: unknown): string {
  return v === null || v === undefined || v === "" ? "—" : String(v);
}
