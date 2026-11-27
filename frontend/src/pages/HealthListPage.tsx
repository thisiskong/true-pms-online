import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api, type Params } from "../api/client";
import type { HealthRow, Page, UnstableRow } from "../api/types";
import { DataTable, type Column } from "../components/DataTable";
import { RevModal } from "../components/device/InterfaceTable";
import { FacetSelect } from "../components/FacetSelect";
import { Button, Card, cx, ErrorBox, Field, inputCls, Pagination, Spinner, StatusBadge, PAGE_CLS } from "../components/ui";
import { ago, dash, fmtTime, num } from "../lib/format";

type Mode = "reboots" | "unreachable" | "unstable";

const FILTERS = ["vendor", "model", "network", "topology", "region", "province"] as const;

interface ModeCfg<R> {
  title: string; desc: string; coverage: string;
  windowParam: string; windowLabel: string; windows: [number, string][]; defaultWindow: number;
  noun: string; empty: string; columns: Column<R>[]; rowKey: (r: R) => string | number;
  fetch: (p: Params, signal?: AbortSignal) => Promise<Page<R>>;
}

const timeAgo = (t: string | null | undefined) => (
  <span className="whitespace-nowrap tabular-nums" title={fmtTime(t)}>
    {fmtTime(t)} <span className="text-zinc-400">· {ago(t)}</span>
  </span>
);

const DEVICE_COLS: Column<HealthRow>[] = [
  { key: "name", header: "Name", render: (r) => <span className="font-mono text-xs font-medium text-zinc-900">{dash(r.name)}</span> },
  { key: "ip", header: "IP", render: (r) => <span className="font-mono text-xs">{dash(r.ip)}</span> },
  { key: "vendor", header: "Vendor", render: (r) => dash(r.vendor) },
  { key: "model", header: "Model", render: (r) => dash(r.model) },
  { key: "topology", header: "Topology", render: (r) => dash(r.topology) },
  { key: "region", header: "Region", render: (r) => dash(r.region) },
  { key: "province", header: "Province", className: "max-w-[220px] truncate", render: (r) => dash(r.province) },
  { key: "sitename", header: "Site", render: (r) => dash(r.sitename) },
];

const UPTIME_COVERAGE = "Covers only devices with uptime polling";

const REBOOTS: ModeCfg<HealthRow> = {
  title: "Reboots",
  desc: "Devices whose uptime reset recently, newest first. Click a row to open the device.",
  coverage: UPTIME_COVERAGE,
  windowParam: "since_hours", windowLabel: "Rebooted in the last", defaultWindow: 24,
  windows: [[24, "24 h"], [168, "7 days"], [720, "30 days"]],
  noun: "rebooted devices", empty: "No reboots in this window", rowKey: (r) => r.id, fetch: api.reboots,
  columns: [
    ...DEVICE_COLS,
    { key: "rebooted", header: "Rebooted", render: (r) => timeAgo(r.uptime?.last_reboot_at) },
    { key: "uptime", header: "Uptime now", render: (r) => <span className="tabular-nums">{dash(r.uptime?.uptime_text)}</span> },
  ],
};

const UNREACHABLE: ModeCfg<HealthRow> = {
  title: "Unreachable devices",
  desc: "Devices with no successful ping for at least the chosen time, longest first. The uptime poller only updates a device's record when its poll succeeds, so these devices have also stopped answering SNMP. A device removed from the poll list also stays here. Click a row to open the device.",
  coverage: UPTIME_COVERAGE,
  windowParam: "not_seen_for_hours", windowLabel: "No successful ping for", defaultWindow: 24,
  windows: [[1, "1 h"], [6, "6 h"], [24, "24 h"], [168, "7 days"]],
  noun: "unreachable devices", empty: "Every device answered a ping in this window", rowKey: (r) => r.id, fetch: api.unreachable,
  columns: [
    ...DEVICE_COLS,
    { key: "lastping", header: "Last ping OK", render: (r) => r.uptime?.last_ping_success_at ? timeAgo(r.uptime.last_ping_success_at)
      : <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-xs font-medium text-zinc-500" title="No successful ping on record: often misconfigured rather than down">never</span> },
    { key: "polled", header: "Last poll OK", render: (r) => <span className="whitespace-nowrap tabular-nums text-zinc-500" title="Last successful SNMP poll (the uptime record only updates on success)">{ago(r.uptime?.polled_at)}</span> },
  ],
};

const UNSTABLE: ModeCfg<UnstableRow> = {
  title: "Unstable interfaces",
  desc: "Interfaces that changed state (up/down or speed) most often in the window. Interface state is polled once a day (around 01:00), so each change is at least a day apart: this finds interfaces that are unstable day to day, not bounces within minutes. Click a row for the interface's full history.",
  coverage: "Interface history exists only for devices on the daily poll, about the same set as uptime polling",
  windowParam: "since_hours", windowLabel: "Changes in the last", defaultWindow: 168,
  windows: [[168, "7 days"], [720, "30 days"], [2160, "90 days"]],
  noun: "interfaces", empty: "No interface reached this many changes in the window", rowKey: (r) => r.id, fetch: api.unstable,
  columns: [
    { key: "device", header: "Device", render: (r) => (
      <Link to={`/devices/${r.device_id}?tab=interfaces`} onClick={(e) => e.stopPropagation()}
        className="font-mono text-xs font-medium text-zinc-900 hover:underline">{dash(r.device_name)}</Link>
    ) },
    { key: "ip", header: "IP", render: (r) => <span className="font-mono text-xs">{dash(r.device_ip)}</span> },
    { key: "ifname", header: "Interface", render: (r) => <span className="font-medium text-zinc-900">{dash(r.ifname)}</span> },
    { key: "ifalias", header: "Description", render: (r) => <span className="block max-w-[160px] truncate" title={r.ifalias ?? ""}>{r.ifalias || "—"}</span> },
    { key: "changes", header: "Changes", className: "text-right", render: (r) => <b className="tabular-nums text-zinc-900">{num(r.changes)}</b> },
    { key: "downs", header: "Went down", className: "text-right", render: (r) => <span className="tabular-nums" title="Changes into a non-up state">{num(r.down_changes)}</span> },
    { key: "speed", header: "Speed chg", className: "text-right", render: (r) => <span className={cx("tabular-nums", !r.speed_changes && "text-zinc-300")}>{num(r.speed_changes)}</span> },
    { key: "now", header: "Now", render: (r) => <StatusBadge value={r.ifoper} /> },
    { key: "last", header: "Last change", render: (r) => <span className="whitespace-nowrap tabular-nums" title={fmtTime(r.last_change)}>{ago(r.last_change)}</span> },
    { key: "vendor", header: "Vendor", render: (r) => dash(r.vendor) },
    { key: "topology", header: "Topology", render: (r) => dash(r.topology) },
    { key: "region", header: "Region", render: (r) => dash(r.region) },
  ],
};

type AnyRow = HealthRow | UnstableRow;
// Each mode's columns only see its own row type; the page itself is row-agnostic.
const MODES = { reboots: REBOOTS, unreachable: UNREACHABLE, unstable: UNSTABLE } as unknown as Record<Mode, ModeCfg<AnyRow>>;

const MIN_CHANGES: [number, string][] = [[1, "1+"], [2, "2+"], [3, "3+"], [5, "5+"], [10, "10+"]];

export function HealthListPage({ mode }: { mode: Mode }) {
  const m = MODES[mode];
  const [sp, setSp] = useSearchParams();
  const navigate = useNavigate();
  const page = Number(sp.get("page") ?? 1);
  const size = Number(sp.get("size") ?? 50);
  const win = Number(sp.get(m.windowParam) ?? m.defaultWindow);
  const includeNever = sp.get("include_never") !== "false";
  const minChanges = Number(sp.get("min_changes") ?? 2);
  const q = sp.get("q") ?? "";
  const [qDraft, setQDraft] = useState(q);
  const [picked, setPicked] = useState<UnstableRow | null>(null);
  useEffect(() => setQDraft(q), [q]);

  const update = (patch: Record<string, string | number | null>) => {
    const next = new URLSearchParams(sp);
    for (const [k, v] of Object.entries(patch)) {
      if (v === null || v === "") next.delete(k);
      else next.set(k, String(v));
    }
    setSp(next, { replace: true });
  };

  useEffect(() => {
    if (qDraft === q) return;
    const t = setTimeout(() => update({ q: qDraft, page: null }), 350);
    return () => clearTimeout(t);
  }, [qDraft]); // eslint-disable-line react-hooks/exhaustive-deps

  const filterParams: Params = { q };
  for (const f of FILTERS) filterParams[f] = sp.get(f);
  const params: Params = {
    ...filterParams, page, size, [m.windowParam]: win,
    ...(mode === "unreachable" ? { include_never: includeNever } : {}),
    ...(mode === "unstable" ? { min_changes: minChanges } : {}),
  };

  const list = useQuery({
    queryKey: [mode, params],
    queryFn: ({ signal }) => m.fetch(params, signal),
    placeholderData: keepPreviousData,
  });
  // Dropdown options only; counts are inventory counts, so they are hidden here.
  const facets = useQuery({
    queryKey: ["facets", filterParams],
    queryFn: ({ signal }) => api.facets(filterParams, signal),
    staleTime: 60_000,
    placeholderData: keepPreviousData,
  });
  const overview = useQuery({ queryKey: ["overview"], queryFn: api.overview, staleTime: 300_000 });
  const cov = overview.data;

  const activeFilters = FILTERS.filter((f) => sp.get(f)).length + (q ? 1 : 0);
  const pill = (active: boolean) => cx("rounded-md px-2.5 py-1 text-xs font-medium", active ? "bg-zinc-900 text-white" : "bg-zinc-100 text-zinc-600 hover:bg-zinc-200");

  const onRow = (r: AnyRow) => {
    if (mode === "unstable") setPicked(r as UnstableRow);
    else navigate(`/devices/${(r as HealthRow).id}`);
  };

  return (
    <div className={PAGE_CLS}>
      <div>
        <h1 className="text-xl font-semibold text-zinc-900">{m.title}</h1>
        <p className="text-sm text-zinc-500">{m.desc}</p>
        {cov && (
          <p className="mt-1 text-xs text-zinc-400">
            {m.coverage}: {num(cov.uptime.with_uptime)} of {num(cov.devices)} devices
            ({Math.round((cov.uptime.with_uptime / cov.devices) * 100)}%). A device missing here may simply not be polled.
          </p>
        )}
      </div>

      <Card bodyClass="p-0">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-zinc-100 px-4 py-3">
          <span className="text-sm text-zinc-600">{m.windowLabel}</span>
          <div className="flex gap-1" role="group" aria-label={m.windowLabel}>
            {m.windows.map(([h, label]) => (
              <button key={h} type="button" onClick={() => update({ [m.windowParam]: h === m.defaultWindow ? null : h, page: null })}
                aria-pressed={win === h} className={pill(win === h)}>
                {label}
              </button>
            ))}
          </div>
          {mode === "unreachable" && (
            <label className="flex items-center gap-2 text-sm text-zinc-600">
              <input type="checkbox" checked={includeNever} onChange={(e) => update({ include_never: e.target.checked ? null : "false", page: null })}
                className="h-4 w-4 rounded border-zinc-300" />
              Include devices that never answered
            </label>
          )}
          {mode === "unstable" && (
            <>
              <span className="text-sm text-zinc-600">At least</span>
              <div className="flex gap-1" role="group" aria-label="Minimum changes">
                {MIN_CHANGES.map(([n, label]) => (
                  <button key={n} type="button" onClick={() => update({ min_changes: n === 2 ? null : n, page: null })}
                    aria-pressed={minChanges === n} className={pill(minChanges === n)}>
                    {label}
                  </button>
                ))}
              </div>
              <span className="text-sm text-zinc-600">changes</span>
            </>
          )}
        </div>
        <div className="grid grid-cols-2 gap-3 border-b border-zinc-100 p-4 sm:grid-cols-3 lg:grid-cols-8">
          <div className="col-span-2 sm:col-span-3 lg:col-span-2">
            <Field label="Search">
              <input className={inputCls} placeholder="Device name, site or IP prefix" value={qDraft} onChange={(e) => setQDraft(e.target.value)} />
            </Field>
          </div>
          {FILTERS.map((f) => (
            <FacetSelect key={f} name={f} value={sp.get(f) ?? ""} options={facets.data?.[f]} loading={facets.isFetching} sortByName showCounts={false}
              onChange={(v) => update({ [f]: v, page: null })} />
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2 px-4 py-2 text-sm text-zinc-500">
          {list.isFetching && <Spinner />}
          {list.data && <span><b className="text-zinc-800">{num(list.data.total)}</b> {m.noun}</span>}
          {activeFilters > 0 && (
            <Button variant="ghost" onClick={() => {
              setQDraft("");
              const keep = new URLSearchParams();
              for (const k of [m.windowParam, "include_never", "min_changes"]) { const v = sp.get(k); if (v) keep.set(k, v); }
              setSp(keep, { replace: true });
            }}>
              Clear {activeFilters} filter{activeFilters > 1 ? "s" : ""}
            </Button>
          )}
        </div>
        <div className="px-1">
          {list.error ? <div className="p-4"><ErrorBox error={list.error} /></div> : (
            <DataTable columns={m.columns} rows={list.data?.items ?? []} rowKey={m.rowKey}
              loading={list.isFetching} onRowClick={onRow} empty={m.empty} />
          )}
        </div>
        <div className="px-4 pb-3">
          {list.data && list.data.total > 0 && (
            <Pagination page={page} size={size} total={list.data.total}
              onPage={(p) => update({ page: p })} onSize={(s) => update({ size: s, page: null })} />
          )}
        </div>
      </Card>

      {picked && <RevModal intf={picked} onClose={() => setPicked(null)} />}
    </div>
  );
}
