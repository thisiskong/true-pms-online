import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { tsdbApi, type TsdbBackend, type TsdbQuery, type TsdbResult, type TsdbStats } from "../api/tsdb";
import { Badge, Button, Card, cx, Empty, ErrorBox, Field, inputCls, PAGE_CLS, Spinner } from "../components/ui";
import { TsdbChart, type ChartSeries } from "../components/tsdb/TsdbChart";
import { agoMs, bytes, compact, fmtDay, fmtMs } from "../components/tsdb/format";
import { num } from "../lib/format";

// ---- query state (kept in the URL so a view can be shared) ------------------------------------

const AGGREGATORS = ["sum", "avg", "min", "max", "count", "dev", "zimsum", "mimmin", "mimmax", "none"];
const DS_FUNCS = ["avg", "sum", "min", "max", "count", "first", "last", "dev", "p50", "p90", "p95", "p99"];
const FILLS = ["none", "nan", "null", "zero"];
const INTERVALS = ["auto", "1m", "5m", "15m", "1h", "6h", "1d", "0all", "raw"];
const RANGES: [string, string, number][] = [
  ["1h", "1 hour", 3_600_000], ["6h", "6 hours", 6 * 3_600_000], ["24h", "24 hours", 86_400_000],
  ["7d", "7 days", 7 * 86_400_000], ["30d", "30 days", 30 * 86_400_000],
];
const STEPS: [string, number][] = [["1m", 60_000], ["5m", 300_000], ["15m", 900_000], ["1h", 3_600_000], ["6h", 21_600_000], ["1d", 86_400_000]];
const MAX_LINES = 50;
const MAX_ROWS = 10;
const LETTERS = "ABCDEFGHIJ";

interface TagRow { k: string; v: string }

/** One metric to chart. */
interface Row { metric: string; agg: string; fn: string; fill: string; tags: TagRow[]; explicit: boolean; right: boolean }

/** The whole view: metric rows plus the time settings they share. */
interface Q { rows: Row[]; iv: string; range: string; from: string; to: string; split: boolean }

const newRow = (patch: Partial<Row> = {}): Row =>
  ({ metric: "", agg: "sum", fn: "avg", fill: "none", tags: [], explicit: false, right: false, ...patch });

const tagsStr = (tags: TagRow[]) => tags.filter((t) => t.k && t.v).map((t) => `${t.k}=${t.v}`).join(",");

function parseTags(s: string): TagRow[] {
  return s.split(",").filter(Boolean).map((p) => {
    const i = p.indexOf("=");
    return i < 0 ? { k: p, v: "" } : { k: p.slice(0, i), v: p.slice(i + 1) };
  });
}

// A row in the URL: q=metric;agg;fn;fill;k=v,k2=v2;flags  (flags: e = explicitTags, r = right axis)
const encodeRow = (r: Row) =>
  [r.metric, r.agg, r.fn, r.fill, tagsStr(r.tags), `${r.explicit ? "e" : ""}${r.right ? "r" : ""}`].join(";");

function decodeRow(s: string): Row {
  const [metric = "", agg, fn, fill, tags = "", flags = ""] = s.split(";");
  return newRow({
    metric, agg: agg || "sum", fn: fn || "avg", fill: fill || "none", tags: parseTags(tags),
    explicit: flags.includes("e"), right: flags.includes("r"),
  });
}

function readQ(sp: URLSearchParams): Q {
  let rows = sp.getAll("q").map(decodeRow);
  if (!rows.length && sp.get("metric")) {
    // Links made before multi-metric queries: metric=…&agg=…&fn=…&fill=…&tags=…&explicit=1
    rows = [newRow({
      metric: sp.get("metric") ?? "", agg: sp.get("agg") ?? "sum", fn: sp.get("fn") ?? "avg",
      fill: sp.get("fill") ?? "none", tags: parseTags(sp.get("tags") ?? ""), explicit: sp.get("explicit") === "1",
    })];
  }
  return {
    rows: rows.length ? rows : [newRow()], iv: sp.get("iv") ?? "auto", range: sp.get("range") ?? "24h",
    from: sp.get("from") ?? "", to: sp.get("to") ?? "", split: sp.get("split") === "1",
  };
}

function writeQ(q: Q): URLSearchParams {
  const p = new URLSearchParams();
  for (const r of q.rows) if (r.metric) p.append("q", encodeRow(r));
  p.set("iv", q.iv);
  p.set("range", q.range);
  if (q.range === "custom") {
    p.set("from", q.from);
    p.set("to", q.to);
  }
  if (q.split) p.set("split", "1");
  return p;
}

const validRows = (q: Q) => q.rows.filter((r) => r.metric);

function timeRange(q: Q, now: number): [number, number] {
  if (q.range === "custom" && q.from) {
    const s = Date.parse(q.from);
    const e = q.to ? Date.parse(q.to) : now;
    if (!Number.isNaN(s) && !Number.isNaN(e)) return [s, e];
  }
  const span = RANGES.find(([k]) => k === q.range)?.[2] ?? 86_400_000;
  return [now - span, now];
}

/** Interval that gives roughly 150–600 points over the range. */
function autoInterval(spanMs: number): string {
  return (STEPS.find(([, ms]) => spanMs / ms <= 600) ?? STEPS[STEPS.length - 1])[0];
}

function downsample(r: Row, iv: string, spanMs: number): string | undefined {
  if (iv === "raw") return undefined;
  return `${iv === "auto" ? autoInterval(spanMs) : iv}-${r.fn}${r.fill !== "none" ? `-${r.fill}` : ""}`;
}

function buildRequest(q: Q, rows: Row[], startMs: number, endMs: number): TsdbQuery {
  return {
    start: startMs, end: endMs, msResolution: true, showQuery: true,
    queries: rows.map((r) => ({
      metric: r.metric, aggregator: r.agg, downsample: downsample(r, q.iv, endMs - startMs),
      tags: Object.fromEntries(r.tags.filter((t) => t.k && t.v).map((t) => [t.k, t.v])), explicitTags: r.explicit,
    })),
  };
}

function getUrl(q: Q, rows: Row[], startMs: number, endMs: number): string {
  const ms = rows.map((r) => {
    const tags = tagsStr(r.tags);
    const m = [r.agg, downsample(r, q.iv, endMs - startMs), r.explicit ? "explicit_tags" : undefined,
      `${r.metric}${tags ? `{${tags}}` : ""}`].filter(Boolean).join(":");
    return `&m=${m}`;
  });
  const start = q.range === "custom" ? String(Math.floor(startMs / 1000)) : `${q.range}-ago`;
  const end = q.range === "custom" && q.to ? `&end=${Math.floor(endMs / 1000)}` : "";
  return `/api/query?start=${start}${end}${ms.join("")}`;
}

/** Name for row i: the metric, plus its letter when another row uses the same metric. */
function rowLabel(rows: Row[], i: number): string {
  const r = rows[i];
  return rows.filter((o) => o.metric === r.metric).length > 1 ? `${r.metric} (${LETTERS[i]})` : r.metric;
}

// ---- results -------------------------------------------------------------------------------------

/** Line names within one sub-query's results: the tag values that differ between them. */
function tagNames(results: TsdbResult[]): string[] {
  if (results.length === 1) return [Object.entries(results[0].tags).map(([k, v]) => `${k}=${v}`).join(" ")];
  const keys = new Set(results.flatMap((r) => Object.keys(r.tags)));
  const varying = [...keys].filter((k) => new Set(results.map((r) => r.tags[k])).size > 1).sort();
  return results.map((r, i) => varying.map((k) => `${k}=${r.tags[k] ?? "—"}`).join(" ") || `series ${i + 1}`);
}

interface Line { row: number; label: string; name: string; result: TsdbResult }

/** Results grouped by the row (sub-query) they came from, each with a unique display name. */
function linesByRow(rows: Row[], results: TsdbResult[]): Line[][] {
  const groups: TsdbResult[][] = rows.map(() => []);
  for (const r of results) groups[r.query?.index ?? 0]?.push(r);
  return groups.map((rs, row) => {
    const label = rowLabel(rows, row);
    const names = tagNames(rs);
    return rs.map((result, i) => {
      const t = names[i];
      const name = rows.length === 1 ? (rs.length === 1 && t ? `${label} {${t}}` : t || label) : t ? `${label} · ${t}` : label;
      return { row, label, name, result };
    });
  });
}

const toChart = (l: Line, right: boolean): ChartSeries => ({
  name: l.name, right,
  data: Object.entries(l.result.dps).map(([t, v]) => [Number(t), v] as [number, number | null]).sort((a, b) => a[0] - b[0]),
});

interface Summary { key: string; label: string; name: string; points: number; min: number | null; avg: number | null; max: number | null; last: number | null }

function summarize(l: Line): Summary {
  const vals = Object.entries(l.result.dps).sort((a, b) => Number(a[0]) - Number(b[0])).map(([, v]) => v).filter((v): v is number => v !== null);
  const base = { key: `${l.row}:${l.name}`, label: l.label, name: l.name };
  if (!vals.length) return { ...base, points: 0, min: null, avg: null, max: null, last: null };
  return {
    ...base, points: vals.length, min: Math.min(...vals), max: Math.max(...vals),
    avg: vals.reduce((a, b) => a + b, 0) / vals.length, last: vals[vals.length - 1],
  };
}

// ---- page ------------------------------------------------------------------------------------------

export function TsdbPage() {
  const [sp, setSp] = useSearchParams();
  const applied = useMemo(() => readQ(sp), [sp]);
  const [draft, setDraft] = useState<Q>(applied);
  const [runId, setRunId] = useState(0);
  // Back/forward navigation changes the URL: show that query in the form too.
  useEffect(() => setDraft(applied), [applied]);

  const health = useQuery({ queryKey: ["tsdb", "health"], queryFn: tsdbApi.health, refetchInterval: 30_000, retry: false });
  const stats = useQuery({ queryKey: ["tsdb", "stats"], queryFn: tsdbApi.stats, refetchInterval: 60_000, retry: false });

  const run = (q: Q) => {
    setDraft(q);
    setSp(writeQ(q), { replace: false });
    setRunId((n) => n + 1);
  };

  const appliedRows = validRows(applied);
  const result = useQuery({
    queryKey: ["tsdb", "query", sp.toString(), runId],
    enabled: appliedRows.length > 0,
    placeholderData: keepPreviousData,
    retry: false,
    queryFn: async ({ signal }) => {
      const [startMs, endMs] = timeRange(applied, Date.now());
      const body = buildRequest(applied, appliedRows, startMs, endMs);
      const t0 = performance.now();
      const results = await tsdbApi.query(body, signal);
      return { q: applied, rows: appliedRows, results, startMs, endMs, body, ms: Math.round(performance.now() - t0) };
    },
  });

  const first = draft.rows.find((r) => r.metric) ?? draft.rows[0] ?? newRow();
  return (
    <div className={PAGE_CLS}>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-zinc-900">Metrics</h1>
          <p className="text-sm text-zinc-500">Time-series data stored by the tsdb service ({backendLabel(health.data?.backend ?? stats.data?.backend)}). Pick one or more metrics to chart them.</p>
        </div>
        <HealthBadge loading={health.isLoading} ok={health.data?.storage ?? health.data?.clickhouse} error={!!health.error}
          db={stats.data?.database} backend={health.data?.backend} />
      </div>

      {stats.error ? <ErrorBox error={stats.error} /> : <Overview stats={stats.data} />}

      <Explorer draft={draft} setDraft={setDraft} stats={stats.data} onRun={() => run(draft)} running={result.isFetching} />

      {appliedRows.length > 0 && <Results data={result.data} error={result.error} fetching={result.isFetching} />}

      <MetricsTable stats={stats.data} loading={stats.isLoading}
        onPick={(metric) => run({ ...draft, rows: [newRow({ agg: first.agg, fn: first.fn, fill: first.fill, metric })] })}
        onAdd={validRows(draft).length < MAX_ROWS
          ? (metric) => run({ ...draft, rows: [...validRows(draft), newRow({ agg: first.agg, fn: first.fn, fill: first.fill, metric, tags: first.tags })] })
          : undefined} />
    </div>
  );
}

function backendLabel(b?: TsdbBackend) {
  return b === "postgres" ? "Postgres" : "ClickHouse";
}

function HealthBadge({ loading, ok, error, db, backend }:
  { loading: boolean; ok?: boolean; error: boolean; db?: string; backend?: TsdbBackend }) {
  if (loading) return <Spinner />;
  const good = ok && !error;
  return (
    <span className={cx("inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-medium ring-1 ring-inset",
      good ? "bg-emerald-50 text-emerald-700 ring-emerald-600/20" : "bg-rose-50 text-rose-700 ring-rose-600/20")}>
      <span className={cx("size-2 rounded-full", good ? "bg-emerald-500" : "bg-rose-500")} />
      {good ? `tsdb service up · ${backend === "postgres" ? "schema" : "database"} ${db ?? "…"}`
        : error ? "tsdb service unreachable" : `${backendLabel(backend)} unreachable`}
    </span>
  );
}

function Tile({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="rounded-xl border border-zinc-200 bg-white px-4 py-3 shadow-sm">
      <div className="text-xs font-medium text-zinc-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums tracking-tight text-zinc-900">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-zinc-500">{sub}</div>}
    </div>
  );
}

function Overview({ stats }: { stats?: TsdbStats }) {
  const s = stats;
  const pg = s?.backend === "postgres";
  const ratio = s && s.disk_bytes && !pg ? s.uncompressed_bytes / s.disk_bytes : null;
  const perPoint = s?.rows ? `${(s.disk_bytes / s.rows).toFixed(1)} B/point` : "—";
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
      <Tile label="Metrics" value={s ? num(s.metrics.length) : "…"} sub="distinct metric names" />
      <Tile label="Series" value={s ? compact(s.series) : "…"} sub="metric + tag combinations" />
      <Tile label="Points stored" value={s ? compact(s.rows) : "…"} sub={s ? (pg ? `${num(s.parts)} daily partitions · estimate` : `${num(s.parts)} parts, before merge dedup`) : undefined} />
      <Tile label="Disk" value={s ? bytes(s.disk_bytes) : "…"}
        sub={s && ratio ? `${bytes(s.uncompressed_bytes)} raw · ${ratio.toFixed(1)}× compression · ${perPoint}`
          : s && pg ? `tables + indexes · ${perPoint}` : undefined} />
      <Tile label="Last ingest" value={s ? agoMs(s.last_ingest) : "…"}
        sub={s ? (s.days ? `data ${fmtDay(s.first_day)} → ${fmtDay(s.last_day)} (${s.days} days)` : "no data yet") : undefined} />
    </div>
  );
}

const segBtn = (on: boolean) => cx("h-8 flex-1 rounded-md border px-2 text-xs font-medium",
  on ? "border-zinc-900 bg-zinc-900 text-white" : "border-zinc-200 bg-white text-zinc-700 hover:bg-zinc-100");

function Explorer({ draft, setDraft, stats, onRun, running }: {
  draft: Q; setDraft: (q: Q) => void; stats?: TsdbStats; onRun: () => void; running: boolean;
}) {
  const set = (patch: Partial<Q>) => setDraft({ ...draft, ...patch });
  const setRow = (i: number, patch: Partial<Row>) => set({ rows: draft.rows.map((r, j) => (j === i ? { ...r, ...patch } : r)) });
  const many = draft.rows.length > 1;
  const canRun = draft.rows.some((r) => r.metric);

  return (
    <Card title="Query" actions={running && <Spinner />}>
      <form className="flex flex-col gap-4" onSubmit={(e) => { e.preventDefault(); if (canRun) onRun(); }}>
        <div className="flex flex-col gap-3">
          {draft.rows.map((r, i) => (
            <RowEditor key={i} row={r} letter={many ? LETTERS[i] : undefined} stats={stats} iv={draft.iv} dual={many}
              onChange={(patch) => setRow(i, patch)}
              onRemove={many ? () => set({ rows: draft.rows.filter((_, j) => j !== i) }) : undefined}
              onCopyTags={many ? () => set({ rows: draft.rows.map((o) => ({ ...o, tags: r.tags.map((t) => ({ ...t })), explicit: r.explicit })) }) : undefined} />
          ))}
          {draft.rows.length < MAX_ROWS && (
            <div>
              <Button onClick={() => set({ rows: [...draft.rows, newRow({ agg: draft.rows[0]?.agg, fn: draft.rows[0]?.fn, fill: draft.rows[0]?.fill })] })}>
                + Add metric
              </Button>
            </div>
          )}
        </div>

        <div className="grid grid-cols-2 items-end gap-3 border-t border-zinc-100 pt-4 md:grid-cols-4 xl:grid-cols-8">
          <Select label="Interval" value={draft.iv} options={INTERVALS} onChange={(iv) => set({ iv })} />
          <div className="col-span-2 xl:col-span-3">
            <Field label="Time range">
              <div className="flex gap-1">
                {RANGES.map(([k]) => (
                  <button key={k} type="button" onClick={() => set({ range: k })} className={segBtn(draft.range === k)}>{k}</button>
                ))}
                <button type="button" onClick={() => set({ range: "custom" })} className={segBtn(draft.range === "custom")}>custom</button>
              </div>
            </Field>
          </div>
          <div className="col-span-1 xl:col-span-2">
            <Field label="Chart">
              <div className="flex gap-1">
                <button type="button" onClick={() => set({ split: false })} className={segBtn(!draft.split)} title="All metrics on one chart">combined</button>
                <button type="button" onClick={() => set({ split: true })} className={segBtn(draft.split)} title="One chart per metric, zoom linked">split</button>
              </div>
            </Field>
          </div>
          <div className="col-span-2 flex justify-end md:col-span-4 xl:col-span-2">
            <Button type="submit" variant="primary" disabled={!canRun}>Run query</Button>
          </div>
        </div>

        {draft.range === "custom" && (
          <div className="grid grid-cols-2 gap-3 md:w-1/2">
            <Field label="From"><input type="datetime-local" className={inputCls} value={draft.from} onChange={(e) => set({ from: e.target.value })} /></Field>
            <Field label="To (empty = now)"><input type="datetime-local" className={inputCls} value={draft.to} onChange={(e) => set({ to: e.target.value })} /></Field>
          </div>
        )}
      </form>
    </Card>
  );
}

function RowEditor({ row, letter, stats, iv, dual, onChange, onRemove, onCopyTags }: {
  row: Row; letter?: string; stats?: TsdbStats; iv: string; dual: boolean;
  onChange: (p: Partial<Row>) => void; onRemove?: () => void; onCopyTags?: () => void;
}) {
  const metricInfo = stats?.metrics.find((m) => m.metric === row.metric);
  const setTag = (i: number, patch: Partial<TagRow>) => onChange({ tags: row.tags.map((t, j) => (j === i ? { ...t, ...patch } : t)) });
  const id = letter ?? "A";

  return (
    <div className={cx("flex flex-col gap-3", letter && "rounded-lg border border-zinc-200 p-3")}>
      <div className="flex items-end gap-3">
        {letter && <span className="mb-1.5 flex size-6 shrink-0 items-center justify-center rounded bg-zinc-100 text-xs font-semibold text-zinc-600">{letter}</span>}
        <div className="grid min-w-0 flex-1 grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
          <div className="col-span-2">
            <Field label="Metric">
              <input className={inputCls} list="tsdb-metrics" placeholder="e.g. in_bw" value={row.metric}
                onChange={(e) => onChange({ metric: e.target.value.trim() })} />
              <datalist id="tsdb-metrics">{stats?.metrics.map((m) => <option key={m.metric} value={m.metric} />)}</datalist>
            </Field>
          </div>
          <Select label="Aggregator" value={row.agg} options={AGGREGATORS} onChange={(agg) => onChange({ agg })} />
          <Select label="Downsample" value={row.fn} options={DS_FUNCS} onChange={(fn) => onChange({ fn })} disabled={iv === "raw"} />
          <Select label="Fill" value={row.fill} options={FILLS} onChange={(fill) => onChange({ fill })} disabled={iv === "raw"} />
          {dual && <Select label="Y axis" value={row.right ? "right" : "left"} options={["left", "right"]} onChange={(v) => onChange({ right: v === "right" })} />}
        </div>
        {onRemove && <Button variant="ghost" onClick={onRemove} title="Remove this metric">✕</Button>}
      </div>

      <div className={cx("flex flex-col gap-2", letter && "pl-9")}>
        <div className="flex items-center gap-3 text-xs font-medium text-zinc-700">
          Tags
          <span className="font-normal text-zinc-400">exact value, <code>a|b</code> (any of), or <code>*</code> (one line per value)</span>
        </div>
        {row.tags.map((t, i) => (
          <TagEditor key={i} rowId={id} row={t} metric={row.metric} keys={metricInfo?.tag_keys ?? []}
            onChange={(patch) => setTag(i, patch)} onRemove={() => onChange({ tags: row.tags.filter((_, j) => j !== i) })} />
        ))}
        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={() => onChange({ tags: [...row.tags, { k: "", v: "" }] })}>+ Add tag</Button>
          <label className="flex items-center gap-2 text-sm text-zinc-700" title="Only series whose tag keys are exactly the ones above">
            <input type="checkbox" checked={row.explicit} onChange={(e) => onChange({ explicit: e.target.checked })} />
            explicitTags
          </label>
          {onCopyTags && row.tags.some((t) => t.k && t.v) && (
            <Button variant="ghost" onClick={onCopyTags} title="Give every metric these tags and this explicitTags setting">Copy tags to all metrics</Button>
          )}
        </div>
      </div>
    </div>
  );
}

function Select({ label, value, options, onChange, disabled }: {
  label: string; value: string; options: string[]; onChange: (v: string) => void; disabled?: boolean;
}) {
  return (
    <Field label={label}>
      <select className={cx(inputCls, "disabled:bg-zinc-50 disabled:text-zinc-400")} value={value} disabled={disabled}
        onChange={(e) => onChange(e.target.value)}>
        {options.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    </Field>
  );
}

function TagEditor({ rowId, row, metric, keys, onChange, onRemove }: {
  rowId: string; row: TagRow; metric: string; keys: string[]; onChange: (p: Partial<TagRow>) => void; onRemove: () => void;
}) {
  const prefix = row.v.includes("*") || row.v.includes("|") ? "" : row.v;
  const values = useQuery({
    queryKey: ["tsdb", "suggest", metric, row.k, prefix],
    enabled: !!row.k,
    staleTime: 60_000,
    placeholderData: keepPreviousData,
    queryFn: ({ signal }) => tsdbApi.suggest({ type: "tagv", metric: metric || undefined, tagk: row.k, q: prefix, max: 50 }, signal),
  });
  const kid = `tsdb-tagk-${rowId}`;
  const vid = `tsdb-tagv-${rowId}-${row.k}`;
  return (
    <div className="flex max-w-2xl items-center gap-2">
      <div className="w-40 shrink-0">
        <input className={cx(inputCls, "font-mono")} list={kid} placeholder="key" value={row.k}
          onChange={(e) => onChange({ k: e.target.value.trim() })} />
        <datalist id={kid}>{keys.map((k) => <option key={k} value={k} />)}</datalist>
      </div>
      <span className="text-zinc-400">=</span>
      <div className="min-w-0 flex-1">
        <input className={cx(inputCls, "font-mono")} list={vid} placeholder="value, a|b or *" value={row.v}
          onChange={(e) => onChange({ v: e.target.value.trim() })} />
        <datalist id={vid}>{values.data?.map((v) => <option key={v} value={v} />)}</datalist>
      </div>
      <Button variant="ghost" onClick={onRemove} title="Remove tag">✕</Button>
    </div>
  );
}

function Results({ data, error, fetching }: {
  data?: { q: Q; rows: Row[]; results: TsdbResult[]; startMs: number; endMs: number; body: TsdbQuery; ms: number };
  error: unknown; fetching: boolean;
}) {
  const [copied, setCopied] = useState<string | null>(null);
  const prepared = useMemo(() => {
    if (!data) return null;
    const byRow = linesByRow(data.rows, data.results);
    const all = byRow.flat();
    // Table: metrics in query order, highest average first within each.
    const summaries = byRow.flatMap((lines) => lines.map(summarize).sort((a, b) => (b.avg ?? -Infinity) - (a.avg ?? -Infinity)));
    return { byRow, all, summaries, points: data.results.reduce((n, r) => n + Object.keys(r.dps).length, 0) };
  }, [data]);

  const copy = (label: string, text: string) => {
    navigator.clipboard?.writeText(text).then(() => {
      setCopied(label);
      setTimeout(() => setCopied(null), 1500);
    });
  };

  const url = data ? getUrl(data.q, data.rows, data.startMs, data.endMs) : "";
  const json = data ? JSON.stringify({ ...data.body, msResolution: undefined, showQuery: undefined }, null, 2) : "";
  const many = (data?.rows.length ?? 0) > 1;
  const r0 = data?.rows[0];

  const title = !data ? "Results" : (
    <span>
      {many ? `${data.rows.length} metrics` : r0?.metric}
      <span className="font-normal text-zinc-400"> · {many ? data.rows.map((r) => r.metric).filter((m, i, a) => a.indexOf(m) === i).join(", ") : r0?.agg} · {fmtMs(data.startMs)} → {fmtMs(data.endMs)}</span>
    </span>
  );

  return (
    <Card title={title}
      actions={data && prepared && (
        <span className="text-xs text-zinc-500">
          {data.results.length} series · {num(prepared.points)} points · {data.ms} ms {fetching && <Spinner className="ml-1 inline" />}
        </span>
      )}>
      {error ? <ErrorBox error={error} /> : !data || !prepared ? <div className="flex h-40 items-center justify-center"><Spinner /></div>
        : data.results.length === 0 ? <Empty>No data for {many ? "these metrics" : "this metric"} and tags in the selected range.</Empty> : (
        <div className="flex flex-col gap-4">
          {data.q.split ? (
            <div className="flex flex-col gap-5">
              {prepared.byRow.map((lines, i) => (
                <div key={i}>
                  <div className="mb-1 flex items-baseline gap-2 text-sm">
                    <span className="font-mono font-medium text-zinc-900">{rowLabel(data.rows, i)}</span>
                    <span className="text-xs text-zinc-400">{data.rows[i].agg} · {lines.length} series{lines.length > MAX_LINES ? `, first ${MAX_LINES} drawn` : ""}</span>
                  </div>
                  {lines.length ? (
                    <TsdbChart series={lines.slice(0, MAX_LINES).map((l) => toChart(l, false))} startMs={data.startMs} endMs={data.endMs}
                      height={260} group="tsdb-split" />
                  ) : <div className="rounded-md bg-zinc-50 px-3 py-6 text-center text-xs text-zinc-500">No data for this metric and tags in the range.</div>}
                </div>
              ))}
            </div>
          ) : (
            <>
              {prepared.all.length > MAX_LINES && (
                <div className="rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-800">
                  Showing the first {MAX_LINES} of {prepared.all.length} lines in the chart; the table lists all. Narrow the tags, use an aggregator to combine them, or switch to split charts.
                </div>
              )}
              <TsdbChart series={prepared.all.slice(0, MAX_LINES).map((l) => toChart(l, data.rows[l.row].right))}
                startMs={data.startMs} endMs={data.endMs} />
              {many && data.rows.some((r) => r.right) && data.rows.some((r) => !r.right) && (
                <div className="-mt-2 text-xs text-zinc-500">Dashed lines use the right-hand axis.</div>
              )}
            </>
          )}

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-zinc-200 text-left text-xs font-medium text-zinc-500">
                  {many && <th className="py-2 pr-4">Metric</th>}
                  <th className="py-2 pr-4">Series</th>
                  <th className="py-2 pr-4 text-right">Points</th>
                  <th className="py-2 pr-4 text-right">Min</th>
                  <th className="py-2 pr-4 text-right">Avg</th>
                  <th className="py-2 pr-4 text-right">Max</th>
                  <th className="py-2 text-right">Last</th>
                </tr>
              </thead>
              <tbody>
                {prepared.summaries.slice(0, 300).map((s) => (
                  <tr key={s.key} className="border-b border-zinc-100 last:border-0">
                    {many && <td className="py-1.5 pr-4 font-mono text-xs font-medium text-zinc-900">{s.label}</td>}
                    <td className="py-1.5 pr-4 font-mono text-xs text-zinc-800">{many ? s.name.slice(s.label.length).replace(/^ · /, "") || "—" : s.name}</td>
                    <td className="py-1.5 pr-4 text-right tabular-nums text-zinc-500">{num(s.points)}</td>
                    <td className="py-1.5 pr-4 text-right tabular-nums">{compact(s.min)}</td>
                    <td className="py-1.5 pr-4 text-right tabular-nums font-medium">{compact(s.avg)}</td>
                    <td className="py-1.5 pr-4 text-right tabular-nums">{compact(s.max)}</td>
                    <td className="py-1.5 text-right tabular-nums">{compact(s.last)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <details className="rounded-lg border border-zinc-200 bg-zinc-50">
            <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-zinc-600">OpenTSDB query (copy into scripts or curl)</summary>
            <div className="flex flex-col gap-3 px-3 pb-3">
              <div>
                <div className="mb-1 flex items-center justify-between text-xs text-zinc-500">
                  GET <Button variant="ghost" onClick={() => copy("get", url)}>{copied === "get" ? "Copied" : "Copy"}</Button>
                </div>
                <pre className="overflow-x-auto rounded-md bg-white p-2 font-mono text-xs text-zinc-800 ring-1 ring-zinc-200">{url}</pre>
              </div>
              <div>
                <div className="mb-1 flex items-center justify-between text-xs text-zinc-500">
                  POST /api/query <Button variant="ghost" onClick={() => copy("post", json)}>{copied === "post" ? "Copied" : "Copy"}</Button>
                </div>
                <pre className="max-h-64 overflow-auto rounded-md bg-white p-2 font-mono text-xs text-zinc-800 ring-1 ring-zinc-200">{json}</pre>
              </div>
            </div>
          </details>
        </div>
      )}
    </Card>
  );
}

function MetricsTable({ stats, loading, onPick, onAdd }: {
  stats?: TsdbStats; loading: boolean; onPick: (metric: string) => void; onAdd?: (metric: string) => void;
}) {
  return (
    <Card title="Metrics" actions={<span className="text-xs text-zinc-500">click a metric to chart it, + to add it to the current chart</span>} bodyClass="px-0 pb-2 pt-1">
      {loading ? <div className="flex h-24 items-center justify-center"><Spinner /></div>
        : !stats?.metrics.length ? <Empty>No metrics yet. Send data to POST /api/ingest on the tsdb service.</Empty> : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-zinc-200 text-left text-xs font-medium text-zinc-500">
                <th className="px-5 py-2">Metric</th>
                <th className="px-3 py-2 text-right">Series</th>
                <th className="px-3 py-2">Tag keys</th>
                <th className="px-3 py-2 text-right" title="Rows with a timestamp in the last 24 hours (including not-yet-merged duplicates)">Points, last 24 h</th>
                <th className="px-3 py-2">Newest point</th>
                <th className="px-3 py-2">Last ingest</th>
                <th className="px-5 py-2" />
              </tr>
            </thead>
            <tbody>
              {stats.metrics.map((m) => (
                <tr key={m.metric} onClick={() => onPick(m.metric)} className="cursor-pointer border-b border-zinc-100 last:border-0 hover:bg-zinc-50">
                  <td className="px-5 py-2 font-mono text-xs font-medium text-zinc-900">{m.metric}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{num(m.series)}</td>
                  <td className="px-3 py-2"><div className="flex flex-wrap gap-1">{m.tag_keys.map((k) => <Badge key={k}>{k}</Badge>)}</div></td>
                  <td className="px-3 py-2 text-right tabular-nums">{m.rows_24h ? num(m.rows_24h) : <span className="text-zinc-400">none</span>}</td>
                  <td className="px-3 py-2 whitespace-nowrap text-zinc-600">{m.last_ts ? fmtMs(m.last_ts) : <span className="text-zinc-400">older than 24 h</span>}</td>
                  <td className="px-3 py-2 whitespace-nowrap text-zinc-500">{agoMs(m.last_ingest)}</td>
                  <td className="px-5 py-1 text-right" onClick={(e) => onAdd && e.stopPropagation()}>
                    {onAdd && (
                      <Button variant="ghost" title="Add to the current chart, with the first metric's tags"
                        onClick={() => onAdd(m.metric)}>+</Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
