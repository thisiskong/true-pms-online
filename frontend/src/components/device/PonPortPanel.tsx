import { useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router";
import { api } from "../../api/client";
import { fiberApi, type Attribution, type OnuScoreRow } from "../../api/fiber";
import { AttributionBadge, BAD_SCORE, Db, ScoreChip } from "../fiber/score";
import type { Onu, PonPort } from "../../api/types";
import { fmtTime, num } from "../../lib/format";
import { DataTable, type Column } from "../DataTable";
import { Modal } from "../Modal";
import { Card, cx, Empty, ErrorBox, inputCls, Spinner, StatusBadge } from "../ui";
import { REV_COLS } from "./InterfaceTable";

const COLUMNS: Column<PonPort>[] = [
  { key: "ponport", header: "PON port", sortable: true, render: (r) => <span className="font-mono text-xs text-zinc-700">{r.ponport ?? "—"}</span> },
  { key: "ifname", header: "Name", sortable: true, render: (r) => <span className="font-medium text-zinc-900">{r.ifname ?? "—"}</span> },
  { key: "ifoper", header: "Oper", sortable: true, render: (r) => <StatusBadge value={r.ifoper} /> },
  { key: "ifadmin", header: "Admin", sortable: true, render: (r) => <StatusBadge value={r.ifadmin} /> },
  { key: "onu_count", header: "Subscribers / available", sortable: true, render: (r) => <Usage used={r.onu_count} cap={r.onu_capacity} /> },
  { key: "iftype", header: "Type", sortable: true, render: (r) => <span className="text-zinc-500">{r.iftype ?? "—"}</span> },
  { key: "ifspeed", header: "Speed", sortable: true, render: (r) => r.speed_text ?? "—" },
  { key: "l1sp", header: "L1SP", sortable: true, render: (r) => <span className="font-mono text-xs">{r.l1sp || "—"}</span> },
  { key: "l1_max_bw", header: "L1 max DL / UL", sortable: true, render: (r) => r.l1_dl_max_bw == null && r.l1_ul_max_bw == null ? "—" : `${r.l1_dl_max_bw ?? "?"} / ${r.l1_ul_max_bw ?? "?"}` },
  { key: "bw_remaining", header: "BW remaining DL / UL", sortable: true, render: (r) => r.dl_bw_remaining || r.ul_bw_remaining ? `${r.dl_bw_remaining || "?"} / ${r.ul_bw_remaining || "?"}` : "—" },
  { key: "optic_class", header: "Class", sortable: true, render: (r) => <OpticClass port={r} /> },
  { key: "lastseen", header: "Last seen", sortable: true, render: (r) => <span className="text-zinc-500">{fmtTime(r.lastseen)}</span> },
];

/** "B+", "C+ combo", "no optic", or "unknown". */
function opticLabel(p: PonPort): string {
  if (p.optic_class === "absent") return "no optic";
  const combo = p.optic_tech === "GPON+XGS-PON" ? " combo" : "";
  return p.optic_class ? `${p.optic_class}${combo}` : combo ? "combo, class unknown" : "unknown";
}

function OpticClass({ port: p }: { port: PonPort }) {
  const title = [
    p.optic_tech === "GPON+XGS-PON" && "GPON + XGS-PON combo optic",
    `Reported module class: ${p.moduleclass ?? "none"}`,
    `Part number: ${p.vendorpn ?? "none"}`,
    p.optic_class_source === "vendorpn" && "Class inferred from the part number (other ports with this part report it)",
  ].filter(Boolean).join("\n");
  const known = p.optic_class && p.optic_class !== "absent";
  return (
    <span className="inline-flex items-baseline gap-1 whitespace-nowrap" title={title}>
      <span className={known ? "font-medium text-zinc-800" : "text-zinc-400"}>
        {p.optic_class === "absent" ? "no optic" : p.optic_class ?? "unknown"}
      </span>
      {p.optic_tech === "GPON+XGS-PON" && <span className="rounded bg-sky-50 px-1 text-[10px] font-medium text-sky-700">combo</span>}
      {p.optic_class_source === "vendorpn" && <span className="text-[10px] text-zinc-400">via PN</span>}
    </span>
  );
}

// "8396.8M" / "1.2G" -> megabits, for sorting.
const bw = (v: string | null) => {
  const m = v?.match(/^([\d.]+)\s*([KMGT]?)/i);
  if (!m) return null;
  return parseFloat(m[1]) * ({ K: 1e-3, M: 1, G: 1e3, T: 1e6 }[m[2].toUpperCase()] ?? 1);
};

// Sort value per column; null always sorts last.
const SORT_VALUE: Record<string, (r: PonPort) => SortVal> = {
  ponport: (r) => r.ponport, ifname: (r) => r.ifname,
  ifoper: (r) => r.ifoper, ifadmin: (r) => r.ifadmin,
  onu_count: (r) => (r.onu_capacity ? r.onu_count / r.onu_capacity : r.onu_count ? r.onu_count / 1e6 : null),
  iftype: (r) => r.iftype, ifspeed: (r) => r.ifspeed, l1sp: (r) => r.l1sp || null,
  l1_max_bw: (r) => r.l1_dl_max_bw, bw_remaining: (r) => bw(r.dl_bw_remaining),
  optic_class: (r) => opticLabel(r), lastseen: (r) => r.lastseen,
};

type SortVal = string | number | null | undefined;

function compare(a: SortVal, b: SortVal): number {
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
}

// Client-side sorting for small, fully loaded tables. Empty values always sort last;
// ties fall back to the default column. Columns in `descFirst` show the largest first on the first click.
function useSort<T>(rows: T[], values: Record<string, (r: T) => SortVal>, defaultKey: string, descFirst: string[] = []) {
  const [sort, setSort] = useState(defaultKey);
  const [order, setOrder] = useState<"asc" | "desc">("asc");
  const onSort = (k: string) => {
    setOrder(sort === k ? (order === "asc" ? "desc" : "asc") : descFirst.includes(k) ? "desc" : "asc");
    setSort(k);
  };
  const sorted = useMemo(() => {
    const get = values[sort] ?? values[defaultKey];
    const tie = values[defaultKey];
    const dir = order === "desc" ? -1 : 1;
    return [...rows].sort((a, b) => {
      const va = get(a), vb = get(b);
      const ea = va == null || va === "", eb = vb == null || vb === "";
      if (ea || eb) return ea && eb ? compare(tie(a), tie(b)) : ea ? 1 : -1;
      return dir * compare(va, vb) || compare(tie(a), tie(b));
    });
  }, [rows, values, sort, order, defaultKey]);
  return { rows: sorted, sort, order, onSort };
}

const pct = (used: number, cap: number) => Math.round((used / cap) * 100);

// "17 / 28 · 61%" with a thin bar; capacity is the port split ratio (odn_onu.splitratio).
function Usage({ used, cap }: { used: number; cap: number | null }) {
  if (!cap) return <span className={cx("tabular-nums", used ? "text-zinc-900" : "text-zinc-400")}>{used}</span>;
  const p = pct(used, cap);
  return (
    <div className="flex min-w-[130px] items-center gap-2" title={`${used} of ${cap} ONU slots used (split 1:${cap})`}>
      <span className="w-14 shrink-0 tabular-nums text-zinc-900">{used} / {cap}</span>
      <div className="h-1.5 w-12 shrink-0 overflow-hidden rounded-full bg-zinc-100">
        <div className={cx("h-full rounded-full", p > 100 ? "bg-rose-500" : p >= 90 ? "bg-amber-500" : "bg-zinc-700")} style={{ width: `${Math.min(p, 100)}%` }} />
      </div>
      <span className={cx("w-10 shrink-0 text-right tabular-nums text-xs", p > 100 ? "text-rose-600" : p >= 90 ? "text-amber-600" : "text-zinc-500")}>{p}%</span>
    </div>
  );
}

function count<T>(items: T[], key: (t: T) => string | null | undefined): [string, number][] {
  const m = new Map<string, number>();
  for (const it of items) { const k = key(it) || "unknown"; m.set(k, (m.get(k) ?? 0) + 1); }
  return [...m].sort((a, b) => b[1] - a[1]);
}

const m = (v: number | null) => (v == null ? "—" : `${num(Math.round(v))} m`);

// ONU row in the PON-port popup: inventory (odn_onu) joined with the latest fiber-score row by ONT id.
type OnuRow = Onu & { f?: OnuScoreRow };

const dbm = (v: number | null | undefined) => (v == null ? "—" : v.toFixed(1));

const ONU_COLS: Column<OnuRow>[] = [
  { key: "score", sortable: true, header: "Score", render: (r) => (
    <span className="inline-flex items-center gap-1">
      <ScoreChip score={r.f?.score} conf={r.f?.conf} />
      {r.f?.hw_flag && <span className="rounded bg-sky-50 px-1 text-[10px] font-semibold text-sky-700" title="ONU hardware reading out of range">HW</span>}
    </span>
  ) },
  { key: "ontid", sortable: true, header: "ONT", render: (r) => <span className="tabular-nums text-zinc-500">{r.ontid ?? "—"}</span> },
  { key: "accessid", sortable: true, header: "Access id", render: (r) => r.accessid ? (
    <Link to={`/access/${encodeURIComponent(r.accessid)}`} onClick={(e) => e.stopPropagation()} title={r.devicesn ? `ONU serial ${r.devicesn}` : undefined}
      className="font-mono text-xs font-medium text-zinc-900 hover:underline">{r.accessid}</Link>
  ) : <span className="text-zinc-300">—</span> },
  { key: "rx", sortable: true, header: "Rx / expected", render: (r) => r.f?.rx_med == null ? <span className="text-zinc-300">—</span> : (
    <span className="whitespace-nowrap tabular-nums" title="Median ONU receive power over the scoring window vs. the model's expected value for this path (about ±2 dB)">
      <span className="text-zinc-900">{dbm(r.f.rx_med)}</span><span className="text-zinc-400"> / {dbm(r.f.expected_rx)} dBm</span>
    </span>
  ) },
  { key: "excess", sortable: true, header: "Excess loss", render: (r) => <Db v={r.f?.excess_loss} signed /> },
  { key: "errors", sortable: true, header: "Error days", render: (r) => r.f?.bip_days == null ? <span className="text-zinc-300">—</span> : (
    <span className={cx("tabular-nums", r.f.bip_days ? "font-medium text-zinc-900" : "text-zinc-400")} title={`Days with BIP errors out of ${r.f.days_obs ?? "?"} observed`}>
      {r.f.bip_days}<span className="text-zinc-400">/{r.f.days_obs ?? "?"}</span>
    </span>
  ) },
  { key: "cause", sortable: true, header: "Likely cause", render: (r) => r.f?.bad ? <AttributionBadge a={r.f.attributed_to} /> : <span className="text-zinc-300">—</span> },
  { key: "l2name", sortable: true, header: "L2 splitter", render: (r) => (
    <span className="whitespace-nowrap font-mono text-xs">{r.l2name ?? "—"}{r.l2ratio ? <span className="font-sans text-zinc-400"> 1:{r.l2ratio}</span> : null}</span>
  ) },
  { key: "path", sortable: true, header: "L2 + drop", render: (r) => (
    <span className="whitespace-nowrap tabular-nums" title={`L1 ${m(r.l1len)} · L2 ${m(r.l2len)} · drop ${m(r.dropwire)} · ranging ${m(r.ranging)}${r.ranging_exclude ? " (excluded)" : ""}`}>
      {m(r.l2len)} <span className="text-zinc-400">+ {m(r.dropwire)}</span>
    </span>
  ) },
];

const ONU_SORT: Record<string, (r: OnuRow) => SortVal> = {
  score: (r) => r.f?.score, ontid: (r) => r.ontid, accessid: (r) => r.accessid,
  rx: (r) => r.f?.rx_med, excess: (r) => r.f?.excess_loss, errors: (r) => r.f?.bip_days,
  cause: (r) => (r.f?.bad ? r.f.attributed_to : null), l2name: (r) => r.l2name,
  path: (r) => (r.l2len ?? 0) + (r.dropwire ?? 0),
};
// Worst first is the default (score ascending); these show the largest first on their first click.
const ONU_DESC_FIRST = ["excess", "errors", "path"];
const NO_ONUS: OnuRow[] = [];

type PopupTab = "onus" | "revs";

function Stat({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <div className="min-w-0 rounded-lg border border-zinc-200 px-3 py-2" title={hint}>
      <div className="text-[11px] text-zinc-500">{label}</div>
      <div className="mt-0.5 text-sm text-zinc-900">{children}</div>
    </div>
  );
}

function PonPortModal({ deviceId, port, onClose }: { deviceId: number; port: PonPort; onClose: () => void }) {
  const navigate = useNavigate();
  const [tab, setTab] = useState<PopupTab>("onus");
  const [l2, setL2] = useState<string | null>(null);
  const revs = useQuery({ queryKey: ["ponportRev", port.id], queryFn: () => api.ponportRevs(deviceId, port.id), enabled: tab === "revs" });
  const onus = useQuery({ queryKey: ["onus", deviceId, port.ponport], queryFn: () => api.onus(deviceId, port.ponport ?? ""), enabled: !!port.ponport });
  const scores = useQuery({
    queryKey: ["fiberOnus", deviceId, port.ponport],
    queryFn: () => fiberApi.onus(deviceId, { ponport: port.ponport, size: 500 }),
    enabled: !!port.ponport, retry: false, staleTime: 300_000,
  });

  const rows = useMemo<OnuRow[]>(() => {
    if (!onus.data) return NO_ONUS;
    const byOnt = new Map((scores.data?.items ?? []).map((x) => [x.ontid, x]));
    return onus.data.items.map((o) => ({ ...o, f: o.ontid != null ? byOnt.get(o.ontid) : undefined }));
  }, [onus.data, scores.data]);

  // L1 values are the same for every ONU on a port; L2 splitters (usually 2-4 per port) become filter chips.
  const first = rows[0];
  const l2s = useMemo(() => {
    const g = new Map<string, { n: number; bad: number; ratio: number | null }>();
    for (const r of rows) {
      const k = r.l2name ?? "—";
      const x = g.get(k) ?? { n: 0, bad: 0, ratio: r.l2ratio };
      x.n += 1;
      if (r.f?.bad) x.bad += 1;
      g.set(k, x);
    }
    return [...g].sort((a, b) => b[1].bad - a[1].bad || a[0].localeCompare(b[0]));
  }, [rows]);
  const shown = useMemo(() => (l2 ? rows.filter((r) => (r.l2name ?? "—") === l2) : rows), [rows, l2]);
  const onuTable = useSort(shown, ONU_SORT, "score", ONU_DESC_FIRST);

  const scored = rows.filter((r) => r.f?.score != null);
  const bad = rows.filter((r) => r.f?.bad).length;
  const sc = scored.map((r) => r.f!.score!).sort((a, b) => a - b);
  const median = sc.length ? sc[Math.floor((sc.length - 1) / 2)] : null;
  const causes = new Map<Attribution, number>();
  for (const r of rows) if (r.f?.bad && r.f.attributed_to) causes.set(r.f.attributed_to, (causes.get(r.f.attributed_to) ?? 0) + 1);
  const topCause = [...causes].sort((a, b) => b[1] - a[1])[0];

  const q = tab === "onus" ? onus : revs;
  return (
    <Modal wide title={`${port.ifname ?? port.ponport ?? port.id}`} onClose={onClose}
      subtitle={<>{port.ifalias || port.ifdescr || "No description"}{port.ponport && <> · PON port <code>{port.ponport}</code></>}</>}>
      <div className="mb-3 grid grid-cols-2 gap-2 md:grid-cols-4">
        <Stat label="Port">
          <span className="inline-flex flex-wrap items-center gap-1.5">
            <StatusBadge value={port.ifoper} />
            {port.ifadmin && port.ifadmin !== "up" && <StatusBadge value={`admin ${port.ifadmin}`} />}
            <span className="text-zinc-600">{port.speed_text ?? "—"}</span>
            <span className="text-xs"><OpticClass port={port} /></span>
          </span>
        </Stat>
        <Stat label="Subscribers" hint="Connected ONUs vs. available slots (split ratio)">
          <Usage used={port.onu_count} cap={port.onu_capacity} />
        </Stat>
        <Stat label="L1 feeder" hint="Shared by every ONU on this port">
          <span className="font-mono text-xs">{first?.l1name ?? port.l1sp ?? "—"}</span>
          <span className="text-zinc-500">{first?.l1ratio ? ` · 1:${first.l1ratio}` : ""}{first?.l1len != null ? ` · ${(first.l1len / 1000).toFixed(1)} km` : ""}</span>
        </Stat>
        <Stat label={`Fiber score${scores.data ? ` · run ${scores.data.date}` : ""}`} hint={`Bad = score ${BAD_SCORE} or below. Daily batch, not live.`}>
          {scores.isLoading ? <Spinner /> : !scored.length ? <span className="text-zinc-400">Not scored</span> : (
            <span className="inline-flex flex-wrap items-center gap-x-2 gap-y-1">
              <span className={cx("font-semibold tabular-nums", bad ? "text-red-600" : "text-zinc-900")}>{bad} bad</span>
              <span className="text-xs text-zinc-500">of {scored.length}</span>
              <span className="inline-flex items-center gap-1 text-xs text-zinc-500">median <ScoreChip score={median} /></span>
              <span className="inline-flex items-center gap-1 text-xs text-zinc-500">worst <ScoreChip score={sc[0]} /></span>
            </span>
          )}
        </Stat>
      </div>
      {topCause && (
        <p className="mb-3 flex flex-wrap items-center gap-1.5 text-xs text-zinc-600">
          Most bad ONUs point to <AttributionBadge a={topCause[0]} /> ({topCause[1]} of {bad}).
        </p>
      )}

      <div className="mb-3 flex gap-1 border-b border-zinc-200">
        {([["onus", `Subscribers (${num(port.onu_count)})`], ["revs", "Revision history"]] as [PopupTab, string][]).map(([k, label]) => (
          <button key={k} type="button" onClick={() => setTab(k)}
            className={cx("-mb-px border-b-2 px-3 py-2 text-sm font-medium", tab === k ? "border-zinc-900 text-zinc-900" : "border-transparent text-zinc-500 hover:text-zinc-800")}>
            {label}
          </button>
        ))}
      </div>
      {q.error ? <ErrorBox error={q.error} /> : q.isLoading ? <div className="flex justify-center p-8"><Spinner /></div> : tab === "onus" ? (
        <>
          {l2s.length > 1 && (
            <div className="mb-2 flex flex-wrap items-center gap-1" role="group" aria-label="Filter by L2 splitter">
              <span className="mr-1 text-xs text-zinc-500">L2 splitter</span>
              <button type="button" onClick={() => setL2(null)}
                className={cx("rounded-md px-2 py-1 text-xs font-medium", !l2 ? "bg-zinc-900 text-white" : "bg-zinc-100 text-zinc-600 hover:bg-zinc-200")}>
                all <span className="opacity-60">{rows.length}</span>
              </button>
              {l2s.map(([k, x]) => (
                <button key={k} type="button" onClick={() => setL2(l2 === k ? null : k)} title={x.ratio ? `split 1:${x.ratio}` : undefined}
                  className={cx("rounded-md px-2 py-1 font-mono text-xs font-medium", l2 === k ? "bg-zinc-900 text-white" : "bg-zinc-100 text-zinc-600 hover:bg-zinc-200")}>
                  {k} <span className="font-sans opacity-60">{x.n}</span>
                  {x.bad > 0 && <span className={cx("ml-1 font-sans", l2 === k ? "text-red-300" : "text-red-600")}>{x.bad} bad</span>}
                </button>
              ))}
            </div>
          )}
          <DataTable columns={ONU_COLS} rows={onuTable.rows} rowKey={(r) => `${r.ontid}-${r.accessid}`} dense
            sort={onuTable.sort} order={onuTable.order} onSort={onuTable.onSort} empty="No subscribers recorded on this PON port"
            onRowClick={(r) => r.f && navigate(`/devices/${deviceId}?tab=fiber&onu=${encodeURIComponent(`${r.f.ponport}:${r.f.ontid}`)}`)} />
          <p className="pt-2 text-xs text-zinc-400">
            Worst score first. Click a scored ONU for its score breakdown and Rx history; click an access id for the subscriber page.
            {onus.data?.truncated ? " Showing the first 1,000 ONUs." : ""}
          </p>
        </>
      ) : (
        <>
          <p className="mb-2 text-xs text-zinc-500">Each row is a state interval from <code>ponport_rev</code>, newest first.</p>
          <DataTable columns={REV_COLS} rows={revs.data?.items ?? []} rowKey={(r) => `${r.id}-${r.rev}`} dense empty="No revisions recorded for this PON port" />
          {revs.data?.truncated && <p className="pt-2 text-xs text-zinc-400">Showing the latest 500 revisions.</p>}
        </>
      )}
    </Modal>
  );
}

type FiberPorts = { date: string; items: Record<string, { n_onu: number; n_bad: number; min_score: number | null }> };

/** Fiber-score summary for this OLT's PON ports (latest daily run): bad ONUs, affected ports, worst score. */
function FiberCard({ data, loading }: { data: FiberPorts | undefined; loading: boolean }) {
  const ports = Object.values(data?.items ?? {});
  const scored = ports.reduce((a, p) => a + p.n_onu, 0);
  const bad = ports.reduce((a, p) => a + p.n_bad, 0);
  const affected = ports.filter((p) => p.n_bad > 0).length;
  const scores = ports.map((p) => p.min_score).filter((s): s is number => s != null);
  const worst = scores.length ? Math.min(...scores) : null;
  const share = scored ? (bad / scored) * 100 : 0;
  return (
    <div className="rounded-xl border border-zinc-200 bg-white px-4 py-3 shadow-sm"
      title={`ONUs scored ${BAD_SCORE} or below count as bad. Scores come from the daily fiber-score batch, not live data.`}>
      <div className="flex items-center justify-between gap-2 text-xs text-zinc-500">
        <span>Fiber score{data ? <span className="text-zinc-400"> · run {data.date}</span> : null}</span>
        {scored > 0 && <Link to="?tab=fiber" className="font-medium text-zinc-500 hover:text-zinc-900">Details →</Link>}
      </div>
      {loading ? (
        <div className="mt-2"><Spinner /></div>
      ) : !scored ? (
        <div className="mt-1 text-sm text-zinc-400">No fiber scores for this OLT</div>
      ) : (
        <>
          <div className="mt-0.5 flex items-baseline gap-2">
            <span className={cx("text-xl font-semibold tabular-nums", bad ? "text-red-600" : "text-zinc-900")}>{num(bad)}</span>
            <span className="text-sm text-zinc-500">bad ONU{bad === 1 ? "" : "s"}</span>
            <span className="text-sm font-medium tabular-nums text-zinc-500">{share < 1 && bad ? share.toFixed(1) : Math.round(share)}%</span>
          </div>
          <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-zinc-100">
            <div className={cx("h-full rounded-full", share >= 20 ? "bg-red-600" : share >= 5 ? "bg-orange-500" : "bg-amber-400")}
              style={{ width: `${bad ? Math.max(share, 2) : 0}%` }} />
          </div>
          <div className="mt-1 flex items-center gap-1.5 text-[11px] text-zinc-400">
            <span>of {num(scored)} scored · {affected} of {ports.length} port{ports.length === 1 ? "" : "s"} affected · worst</span>
            <ScoreChip score={worst} />
          </div>
        </>
      )}
    </div>
  );
}

export function PonPortPanel({ deviceId }: { deviceId: number }) {
  const q = useQuery({ queryKey: ["ponports", deviceId], queryFn: () => api.ponports(deviceId) });
  const [oper, setOper] = useState("");
  const [text, setText] = useState("");
  const [picked, setPicked] = useState<PonPort | null>(null);

  const items = useMemo(() => q.data?.items ?? [], [q.data]);
  const byOper = useMemo(() => count(items, (p) => p.ifoper), [items]);
  const byType = useMemo(() => count(items, (p) => p.iftype), [items]);
  const byClass = useMemo(() => count(items, opticLabel), [items]);
  const filtered = useMemo(() => {
    const t = text.trim().toLowerCase();
    return items.filter((p) => (!oper || p.ifoper === oper) &&
      (!t || [p.ponport, p.ifname, p.ifalias, p.l1sp].some((v) => v?.toLowerCase().includes(t))));
  }, [items, oper, text]);
  const table = useSort(filtered, SORT_VALUE, "ponport", ["onu_count", "ifspeed", "l1_max_bw", "bw_remaining", "lastseen"]);
  // Fiber-score badge per port (worst ONU score + bad count). Optional: the table works without ML results.
  const fiber = useQuery({ queryKey: ["fiberPorts", deviceId], queryFn: () => fiberApi.ponports(deviceId), retry: false, staleTime: 300_000 });
  const columns = useMemo(() => {
    const f = fiber.data?.items;
    if (!f) return COLUMNS;
    const col: Column<PonPort> = {
      key: "fiber", header: "Fiber", render: (r) => {
        const x = r.ponport ? f[r.ponport] : undefined;
        if (!x) return <span className="text-zinc-300">—</span>;
        return (
          <span className="inline-flex items-center gap-1.5" title={`Worst ONU score ${x.min_score ?? "—"} · ${x.n_bad} of ${x.n_onu} ONUs scored ${BAD_SCORE} or below (run ${fiber.data!.date})`}>
            <ScoreChip score={x.min_score} />
            <span className={cx("text-xs tabular-nums", x.n_bad ? "text-red-600" : "text-zinc-400")}>{x.n_bad ? `${x.n_bad} bad` : "ok"}</span>
          </span>
        );
      },
    };
    const i = COLUMNS.findIndex((c) => c.key === "ifadmin");
    return [...COLUMNS.slice(0, i + 1), col, ...COLUMNS.slice(i + 1)];
  }, [fiber.data]);

  if (q.error) return <ErrorBox error={q.error} />;
  if (q.isLoading) return <div className="flex justify-center p-8"><Spinner /></div>;
  if (!items.length) return <Card><Empty>No PON ports recorded for this device</Empty></Card>;

  const subs = items.reduce((a, p) => a + p.onu_count, 0);
  const withCap = items.filter((p) => p.onu_capacity);
  const capTotal = withCap.reduce((a, p) => a + (p.onu_capacity ?? 0), 0);
  const subsOnCap = withCap.reduce((a, p) => a + p.onu_count, 0);
  const tiles: [string, number, string][] = [
    ["Total PON ports", items.length, ""],
  ];

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
        {tiles.map(([k, v, c]) => (
          <div key={k} className="rounded-xl border border-zinc-200 bg-white px-4 py-3 shadow-sm">
            <div className="text-xs text-zinc-500">{k}</div>
            <div className={cx("mt-0.5 text-xl font-semibold tabular-nums text-zinc-900", c)}>{num(v)}</div>
          </div>
        ))}
        <div className="rounded-xl border border-zinc-200 bg-white px-4 py-3 shadow-sm"
          title="Available = sum of each port's split ratio (odn_onu.splitratio); ports without subscriber records are not counted">
          <div className="text-xs text-zinc-500">Subscribers (ONUs)</div>
          <div className="mt-0.5 flex items-baseline gap-2">
            <span className="text-xl font-semibold tabular-nums text-zinc-900">{num(subs)}</span>
            {capTotal > 0 && <span className="text-sm font-medium tabular-nums text-zinc-500">{pct(subsOnCap, capTotal)}%</span>}
          </div>
          {capTotal > 0 && (
            <>
              <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-zinc-100">
                <div className="h-full rounded-full bg-zinc-700" style={{ width: `${Math.min(pct(subsOnCap, capTotal), 100)}%` }} />
              </div>
              <div className="mt-1 text-[11px] text-zinc-400">of {num(capTotal)} available on {withCap.length} port{withCap.length === 1 ? "" : "s"}</div>
            </>
          )}
        </div>
        <FiberCard data={fiber.data} loading={fiber.isLoading} />
      </div>
      <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-zinc-500">
        <span>Types: {byType.map(([k, v]) => `${k} (${v})`).join(", ")}</span>
        <span>Optic class: {byClass.map(([k, v]) => `${k} (${v})`).join(", ")}</span>
      </div>

      <Card bodyClass="p-4">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <input className={cx(inputCls, "max-w-xs")} placeholder="Filter port, name, description, L1SP" value={text} onChange={(e) => setText(e.target.value)} />
          <div className="flex flex-wrap gap-1">
            {[["", items.length] as [string, number], ...byOper].map(([o, c]) => (
              <button key={o || "all"} type="button" onClick={() => setOper(o)}
                className={cx("rounded-md px-2 py-1 text-xs font-medium", oper === o ? "bg-zinc-900 text-white" : "bg-zinc-100 text-zinc-600 hover:bg-zinc-200")}>
                {o || "all"} <span className="opacity-60">{c}</span>
              </button>
            ))}
          </div>
          <span className="ml-auto text-xs text-zinc-400">Click a port to see its subscribers and history</span>
        </div>
        <DataTable columns={columns} rows={table.rows} rowKey={(r) => r.id} dense onRowClick={setPicked}
          sort={table.sort} order={table.order} onSort={table.onSort} empty="No PON ports match" />
        {q.data?.truncated && <p className="pt-2 text-xs text-zinc-400">Showing the first 1,000 PON ports.</p>}
      </Card>
      {picked && <PonPortModal deviceId={deviceId} port={picked} onClose={() => setPicked(null)} />}
    </div>
  );
}
