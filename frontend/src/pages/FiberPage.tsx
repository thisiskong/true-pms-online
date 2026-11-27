import { useEffect, useState, type ReactNode } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import type { Params } from "../api/client";
import { fiberApi, type Attribution, type FacetValue, type FiberSummary, type Level, type Suspect } from "../api/fiber";
import { BadOnuList } from "../components/fiber/BadOnuList";
import { DataTable, type Column } from "../components/DataTable";
import { ScoreHistogram } from "../components/fiber/FiberCharts";
import { ATTRIBUTION, ATTRIBUTION_ORDER, BadShare, BAD_SCORE, Db, FiberHelpLink, LEVEL_LABEL, runLabel, runShort } from "../components/fiber/score";
import { Badge, Button, Card, cx, ErrorBox, Field, inputCls, Pagination, Spinner, PAGE_CLS } from "../components/ui";
import { num } from "../lib/format";

const LEVELS: Level[] = ["l2", "l1", "device"];
const FILTERS = ["region", "province", "vendor"] as const;

const pct = (v: number | null | undefined, d = 0) => (v == null ? "—" : `${(v * 100).toFixed(d)}%`);
const where = (r: Suspect) => (
  <span className="block max-w-[200px] truncate text-zinc-600" title={[r.region, r.province, r.sitename].filter(Boolean).join(" · ")}>
    {r.province ?? <span className="text-zinc-300">unknown</span>}
  </span>
);
const devCell = (r: Suspect) => <span className={cx("font-mono text-xs", r.device_id ? "text-zinc-800" : "text-zinc-400")} title={r.device_id ? undefined : "not found in the device inventory"}>{r.device}</span>;
const name = (v: string | undefined) => <span className="font-mono text-xs font-medium text-zinc-900">{v ?? "—"}</span>;
const impact = (r: Suspect) => <span className="font-semibold tabular-nums text-zinc-900" title="bad ONUs attributed here × median excess loss">{r.impact.toFixed(0)}</span>;
const stats = (r: Suspect) => `Adjusted bad rate ${pct(r.bad_rate_shrunk, 1)} (shrunk toward the network rate for small groups) · p = ${r.p_value.toExponential(1)}`;
const bad = (r: Suspect) => <span title={stats(r)}><BadShare bad={r.n_bad} total={r.n_onu} wide /></span>;

const COMMON_TAIL: Column<Suspect>[] = [
  { key: "med_rx", header: "Median Rx", sortable: true, render: (r) => <span className="tabular-nums">{r.med_rx?.toFixed(1) ?? "—"}</span> },
  { key: "med_peer_delta", header: "Peer Δ", sortable: true, render: (r) => <Db v={r.med_peer_delta} signed /> },
  { key: "med_excess_loss", header: "Excess loss", sortable: true, render: (r) => <Db v={r.med_excess_loss} /> },
  { key: "impact", header: "Impact", sortable: true, render: impact },
];

const COLUMNS: Record<Level, Column<Suspect>[]> = {
  l2: [
    { key: "l2name", header: "L2 splitter", sortable: true, render: (r) => name(r.l2name) },
    { key: "l1name", header: "L1", sortable: true, render: (r) => <span className="font-mono text-xs text-zinc-600">{r.l1name}</span> },
    { key: "device", header: "OLT", sortable: true, render: devCell },
    { key: "province", header: "Province", sortable: true, render: where },
    { key: "n_bad", header: "Bad ONUs", sortable: true, render: bad },
    { key: "n_sibling_l2", header: "Sibling L2s", render: (r) => <span className="tabular-nums text-zinc-500">{r.n_sibling_l2 ?? "—"}</span> },
    ...COMMON_TAIL,
  ],
  l1: [
    { key: "l1name", header: "L1 / PON", sortable: true, render: (r) => name(r.l1name) },
    { key: "device", header: "OLT", sortable: true, render: devCell },
    { key: "province", header: "Province", sortable: true, render: where },
    { key: "n_bad", header: "Bad ONUs", sortable: true, render: bad },
    { key: "n_bad_l2", header: "Bad L2s", render: (r) => <span className="tabular-nums text-zinc-600">{r.n_bad_l2 ?? "—"}/{r.n_l2 ?? "—"}</span> },
    { key: "n_sibling_l1", header: "PONs on OLT", render: (r) => <span className="tabular-nums text-zinc-500">{r.n_sibling_l1 ?? "—"}</span> },
    ...COMMON_TAIL,
  ],
  device: [
    { key: "device", header: "OLT", sortable: true, render: (r) => name(r.device) },
    { key: "vendor", header: "Vendor / model", render: (r) => <span className="text-zinc-600">{r.vendor} {r.model && <span className="text-zinc-400">· {r.model}</span>}</span> },
    { key: "province", header: "Province", sortable: true, render: where },
    { key: "n_bad", header: "Bad ONUs", sortable: true, render: bad },
    { key: "n_suspect_l1", header: "Suspect PONs", render: (r) => <span className="tabular-nums text-zinc-600">{r.n_suspect_l1 ?? "—"}/{r.n_l1 ?? "—"}</span> },
    ...COMMON_TAIL,
  ],
};

const LEVEL_NOTE: Record<Level, string> = {
  l2: "L2 splitters whose ONUs are worse than sibling L2s on the same PON. Likely the L2 splitter or distribution fiber.",
  l1: "PONs that are bad as a whole while sibling PONs on the OLT are fine. L1 maps 1:1 to the PON port, so this may be the OLT PON optic rather than the feeder fiber.",
  device: "OLTs where most PONs are bad: optics batch, configuration, or site power/temperature. Not a fiber fault.",
};

function Delta({ now, prev, invert = true }: { now: number | undefined; prev: number | undefined; invert?: boolean }) {
  if (now == null || prev == null || now === prev) return null;
  const d = now - prev;
  const good = invert ? d < 0 : d > 0;
  return <span className={cx("text-xs font-medium tabular-nums", good ? "text-emerald-600" : "text-red-600")}>{d < 0 ? "▼" : "▲"} {num(Math.abs(d))}</span>;
}

function Kpi({ label, value, sub, delta, tone, title }: { label: string; value: ReactNode; sub?: ReactNode; delta?: ReactNode; tone?: string; title?: string }) {
  return (
    <div className="rounded-xl border border-zinc-200 bg-white px-4 py-3 shadow-sm" title={title}>
      <div className="text-xs text-zinc-500">{label}</div>
      <div className="mt-0.5 flex items-baseline gap-2">
        <span className={cx("text-xl font-semibold tabular-nums text-zinc-900", tone)}>{value}</span>
        {delta}
      </div>
      {sub && <div className="mt-0.5 text-[11px] text-zinc-400">{sub}</div>}
    </div>
  );
}

function KpiStrip({ s }: { s: FiberSummary }) {
  const p = s.prev;
  const mae = s.model.holdout_mae_db;
  const vs = p ? `vs ${runShort(p.date, p.window)}${p.days < s.window ? ` (${p.days}-day run)` : ""}` : undefined;
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      <Kpi label="ONUs scored" value={num(s.onus)} sub={`${s.days.length} of ${s.window} days · mean confidence ${s.mean_conf.toFixed(2)}`} />
      <Kpi label={`Bad ONUs (score ≤ ${s.bad_threshold})`} value={num(s.bad_onus)} tone="text-red-600"
        sub={<>{pct(s.global_bad_rate, 2)} of scored{vs && <> · {vs}</>}</>} delta={<Delta now={s.bad_onus} prev={p?.bad_onus} />} />
      <Kpi label="Suspect L2 segments" value={num(s.suspects.l2)} delta={<Delta now={s.suspects.l2} prev={p?.suspects.l2} />} sub={vs} />
      <Kpi label="Suspect L1 / PON" value={num(s.suspects.l1)} delta={<Delta now={s.suspects.l1} prev={p?.suspects.l1} />} sub={vs} />
      <Kpi label="Suspect OLTs" value={num(s.suspects.device)} delta={<Delta now={s.suspects.device} prev={p?.suspects.device} />} sub={vs} />
      <Kpi label="Expected-Rx model error" value={mae != null ? `${mae.toFixed(2)} dB` : "—"} tone={mae != null && mae > 1.5 ? "text-amber-600" : undefined}
        title="Mean absolute error of the expected-Rx model on held-out PON ports. Target is below 1.5 dB."
        sub={<>target &lt; 1.5 dB · baseline {s.model.baseline_mae_db?.toFixed(2) ?? "—"}{s.model.mae_drift_db ? ` · drift ${s.model.mae_drift_db.toFixed(2)}` : ""}</>} />
    </div>
  );
}

function AttributionBars({ s, active, onPick }: { s: FiberSummary; active: Attribution | null; onPick: (a: Attribution | null) => void }) {
  const total = Object.values(s.attributed).reduce((a, b) => a + (b ?? 0), 0) || 1;
  return (
    <div className="flex flex-col gap-1.5">
      {ATTRIBUTION_ORDER.map((k) => {
        const v = s.attributed[k] ?? 0;
        const x = ATTRIBUTION[k];
        return (
          <button key={k} type="button" title={`${x.hint} · click to list these ONUs`} disabled={!v}
            onClick={() => onPick(active === k ? null : k)} aria-pressed={active === k}
            className={cx("-mx-2 rounded-md px-2 py-1 text-left transition-colors disabled:cursor-default", active === k ? "bg-zinc-100 ring-1 ring-inset ring-zinc-300" : "hover:bg-zinc-50")}>
            <div className="flex items-baseline justify-between text-sm">
              <span className={cx("text-zinc-700", v > 0 && "underline decoration-zinc-300 decoration-dotted underline-offset-4")}>{x.label}</span>
              <span className="tabular-nums text-zinc-900">{num(v)} <span className="text-xs text-zinc-400">{pct(v / total)}</span></span>
            </div>
            <div className="mt-1 h-2 overflow-hidden rounded-full bg-zinc-100">
              <div className="h-full rounded-full" style={{ width: `${Math.max(v ? 0.6 : 0, (v / total) * 100)}%`, background: x.hex }} />
            </div>
          </button>
        );
      })}
      <p className="text-xs text-zinc-400">Each bad ONU is counted once, at the highest level that explains it. Fixing one shared segment fixes all ONUs below it. Click a row to list its ONUs.</p>
    </div>
  );
}

function ModelPanel({ s }: { s: FiberSummary }) {
  const fi = Object.entries(s.model.feature_importance_gain ?? {}).sort((a, b) => b[1] - a[1]);
  const max = fi[0]?.[1] || 1;
  const inv = s.inventory;
  return (
    <div className="grid gap-6 md:grid-cols-2">
      <div>
        <h3 className="mb-2 text-xs font-medium text-zinc-500">Expected-Rx model inputs (share of gain)</h3>
        <div className="flex flex-col gap-1.5">
          {fi.map(([k, v]) => (
            <div key={k} className="grid grid-cols-[100px_1fr_44px] items-center gap-2 text-xs">
              <span className="font-mono text-zinc-600">{k}</span>
              <div className="h-1.5 rounded-full bg-zinc-100"><div className="h-full rounded-full bg-zinc-700" style={{ width: `${(v / max) * 100}%` }} /></div>
              <span className="text-right tabular-nums text-zinc-500">{pct(v)}</span>
            </div>
          ))}
        </div>
        <p className="mt-2 text-xs text-zinc-400">
          Model {s.model.model_date ?? "—"}, trained on {num(s.model.train_onus)} presumed-healthy ONUs and checked on {num(s.model.holdout_onus)} ONUs from held-out PON ports.
          Most remaining error is per-PON OLT launch power, which no input captures yet.
        </p>
      </div>
      <div>
        <h3 className="mb-2 text-xs font-medium text-zinc-500">Inventory flags (not part of the score)</h3>
        <dl className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-1 text-sm">
          {([
            ["No ODN inventory row", inv.no_odn],
            ["Ranging differs from L1+L2 length by > 2 km", inv.range_mismatch],
            ["L2 name used on more than one OLT", inv.l2_multi_device],
            ["Metric and inventory topology disagree", inv.topology_mismatch],
          ] as [string, number | undefined][]).map(([k, v]) => (
            <div key={k} className="contents"><dt className="text-zinc-600">{k}</dt><dd className="text-right tabular-nums text-zinc-900">{num(v)}</dd></div>
          ))}
        </dl>
        <p className="mt-2 text-xs text-zinc-400">Run {runLabel(s.date, s.window)} (dated {s.date}) · data {s.days[0]} → {s.days[s.days.length - 1]} · ODN inventory {s.odn_date ?? "—"}.</p>
      </div>
    </div>
  );
}

function FacetSelect({ label, value, options, onChange }: { label: string; value: string; options: FacetValue[] | undefined; onChange: (v: string) => void }) {
  const list = value && !(options ?? []).some((o) => o.value === value) ? [{ value, count: 0 }, ...(options ?? [])] : options ?? [];
  return (
    <Field label={label}>
      <select className={inputCls} value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">All</option>
        {list.map((o) => <option key={o.value} value={o.value}>{o.value} ({o.count})</option>)}
      </select>
    </Field>
  );
}

export function FiberPage() {
  const [sp, setSp] = useSearchParams();
  const navigate = useNavigate();
  const date = sp.get("date") ?? undefined;
  const level = (LEVELS.includes(sp.get("level") as Level) ? sp.get("level") : "l2") as Level;
  const page = Number(sp.get("page") ?? 1);
  const size = Number(sp.get("size") ?? 50);
  const sort = sp.get("sort") ?? "impact";
  const order = (sp.get("order") ?? "desc") as "asc" | "desc";
  const q = sp.get("q") ?? "";
  const [qDraft, setQDraft] = useState(q);
  const [showModel, setShowModel] = useState(false);
  const att = (ATTRIBUTION_ORDER as string[]).includes(sp.get("att") ?? "") ? (sp.get("att") as Attribution) : null;

  const update = (patch: Record<string, string | number | null>) => {
    const next = new URLSearchParams(sp);
    for (const [k, v] of Object.entries(patch)) {
      if (v === null || v === "") next.delete(k);
      else next.set(k, String(v));
    }
    setSp(next, { replace: true });
  };

  useEffect(() => setQDraft(q), [q]);
  useEffect(() => {
    if (qDraft === q) return;
    const t = setTimeout(() => update({ q: qDraft, page: null }), 300);
    return () => clearTimeout(t);
  }, [qDraft]); // eslint-disable-line react-hooks/exhaustive-deps

  const runs = useQuery({ queryKey: ["fiberRuns"], queryFn: fiberApi.runs, staleTime: 300_000 });
  const summary = useQuery({ queryKey: ["fiberSummary", date], queryFn: () => fiberApi.summary(date), staleTime: 300_000 });
  const params: Params = { date, level, page, size, sort, order, q };
  for (const f of FILTERS) params[f] = sp.get(f);
  const list = useQuery({
    queryKey: ["fiberSuspects", params],
    queryFn: ({ signal }) => fiberApi.suspects(params, signal),
    placeholderData: keepPreviousData,
  });

  const onSort = (key: string) => update({ sort: key, order: sort === key && order === "desc" ? "asc" : "desc", page: null });
  const open = (r: Suspect) => {
    if (!r.device_id) return;
    const p = new URLSearchParams({ tab: "fiber" });
    if (r.l1name) p.set("l1", r.l1name);
    if (r.l2name) p.set("l2", r.l2name);
    navigate(`/devices/${r.device_id}?${p}`);
  };
  const { page: _p, size: _s, ...csvParams } = params;
  const s = summary.data;

  if (summary.error) {
    return (
      <div className="mx-auto max-w-xl p-8">
        <Card title="Fiber health">
          <p className="text-sm text-zinc-600">No fiber-score results are available. Run the pipeline in <code className="text-xs">ml/</code> first:</p>
          <pre className="mt-2 rounded-md bg-zinc-50 p-2 text-xs">uv run fiber/run.py --date &lt;yesterday&gt;</pre>
          <div className="mt-3"><ErrorBox error={summary.error} /></div>
        </Card>
      </div>
    );
  }

  return (
    <div className={PAGE_CLS}>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-zinc-900">Fiber health</h1>
          <p className="text-sm text-zinc-500">
            Fiber score 1 (poor) – 10 (excellent) per ONU from the daily ML batch, and the shared segments most likely causing bad ONUs.
            {" "}<FiberHelpLink className="ml-1 align-middle" />
          </p>
        </div>
        <div className="flex items-end gap-2">
          {s && <Badge tone="slate">{s.window}-day window · confidence {s.mean_conf.toFixed(2)}</Badge>}
          <Field label="Run">
            <select className={cx(inputCls, "w-auto")} value={date ?? s?.date ?? ""} onChange={(e) => update({ date: e.target.value === runs.data?.[0]?.date ? null : e.target.value, page: null })}>
              {(runs.data ?? []).map((r) => <option key={r.date} value={r.date}>{runLabel(r.date, r.window)}{r.days < r.window ? ` (${r.days}-day)` : ""}</option>)}
            </select>
          </Field>
        </div>
      </div>

      {s ? <KpiStrip s={s} /> : <div className="flex h-[76px] items-center justify-center"><Spinner /></div>}

      <div className="grid gap-4 lg:grid-cols-5">
        <Card className="lg:col-span-3" title="ONUs by fiber score" actions={<span className="text-xs text-zinc-400">log scale · bad = score ≤ {BAD_SCORE}</span>}>
          {s ? <ScoreHistogram histogram={s.histogram} /> : <div className="h-[220px]" />}
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-zinc-500">
            {[["1–3 Poor", "bg-red-600"], ["4–5 Weak", "bg-orange-500"], ["6–7 Fair", "bg-amber-400"], ["8–10 Good", "bg-emerald-600"]].map(([l, c]) => (
              <span key={l} className="inline-flex items-center gap-1.5"><span className={cx("size-2.5 rounded-sm", c)} />{l}</span>
            ))}
          </div>
        </Card>
        <Card className="lg:col-span-2" title="Where the bad ONUs are">
          {s ? <AttributionBars s={s} active={att} onPick={(a) => update({ att: a, opage: null, osort: null, oorder: null, oq: null })} /> : <div className="h-[220px]" />}
        </Card>
      </div>

      {att && (
        <BadOnuList att={att} date={date} page={Number(sp.get("opage") ?? 1)} sort={sp.get("osort") ?? "score"}
          order={(sp.get("oorder") ?? "asc") as "asc" | "desc"} q={sp.get("oq") ?? ""} onChange={update}
          onClose={() => update({ att: null, opage: null, osort: null, oorder: null, oq: null })} />
      )}

      <Card bodyClass="p-0">
        <div className="flex flex-wrap items-center gap-1 border-b border-zinc-100 px-4 pt-3">
          {LEVELS.map((l) => (
            <button key={l} type="button" onClick={() => update({ level: l === "l2" ? null : l, page: null, sort: null, order: null })}
              className={cx("-mb-px border-b-2 px-3 py-2 text-sm font-medium", level === l ? "border-zinc-900 text-zinc-900" : "border-transparent text-zinc-500 hover:text-zinc-800")}>
              Suspect {LEVEL_LABEL[l]} {s?.suspects[l] != null && <span className="ml-1 text-xs text-zinc-400">{num(s.suspects[l])}</span>}
            </button>
          ))}
        </div>
        <div className="grid grid-cols-2 gap-3 p-4 sm:grid-cols-4 lg:grid-cols-6">
          <div className="col-span-2">
            <Field label="Search">
              <input className={inputCls} placeholder="OLT, L1, L2 or site" value={qDraft} onChange={(e) => setQDraft(e.target.value)} />
            </Field>
          </div>
          {FILTERS.map((f) => (
            <FacetSelect key={f} label={f[0].toUpperCase() + f.slice(1)} value={sp.get(f) ?? ""} options={list.data?.facets[f]}
              onChange={(v) => update({ [f]: v, page: null })} />
          ))}
          <div className="flex items-end justify-end">
            <a href={fiberApi.suspectsCsvUrl(csvParams)}
              className="inline-flex h-8 items-center gap-1.5 rounded-md border border-zinc-200 bg-white px-3 text-sm font-medium text-zinc-900 shadow-sm transition-colors hover:bg-zinc-100">⬇ CSV</a>
          </div>
        </div>
        <p className="px-4 pb-2 text-xs text-zinc-500">{LEVEL_NOTE[level]} Ranked by impact (bad ONUs × median excess loss). Click a row to open the OLT's fiber view.</p>
        <div className="px-1">
          {list.error ? <div className="p-4"><ErrorBox error={list.error} /></div> : (
            <DataTable columns={COLUMNS[level]} rows={list.data?.items ?? []} loading={list.isFetching} dense
              rowKey={(r) => `${r.device}|${r.l1name ?? ""}|${r.l2name ?? ""}`} sort={sort} order={order} onSort={onSort} onRowClick={open}
              empty="No suspects match these filters" />
          )}
        </div>
        <div className="px-4 pb-3">
          <Pagination page={page} size={size} total={list.data?.total ?? 0} onPage={(p) => update({ page: p })} onSize={(n) => update({ size: n, page: null })} />
        </div>
      </Card>

      {s && (
        <Card title="Model & data quality" actions={<Button variant="ghost" onClick={() => setShowModel(!showModel)}>{showModel ? "Hide" : "Show"}</Button>}
          bodyClass={showModel ? undefined : "hidden"}>
          <ModelPanel s={s} />
        </Card>
      )}
    </div>
  );
}
