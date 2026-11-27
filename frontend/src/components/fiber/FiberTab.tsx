import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { fiberApi, type OnuScoreRow, type TreePort } from "../../api/fiber";
import { num } from "../../lib/format";
import { DataTable, type Column } from "../DataTable";
import { Card, cx, Empty, ErrorBox, Pagination, Spinner } from "../ui";
import { OnuDrawer } from "./OnuDrawer";
import { AttributionBadge, BadShare, BAD_SCORE, Db, FiberHelpLink, ScoreChip } from "./score";

type Sel = { ponport: string; l1name: string | null; l2name?: string | null } | null;

const ONU_COLS: Column<OnuScoreRow>[] = [
  { key: "score", header: "Score", sortable: true, render: (r) => <ScoreChip score={r.score} conf={r.conf} /> },
  { key: "ponport", header: "PON", sortable: true, render: (r) => <span className="font-mono text-xs">{r.ponport}</span> },
  { key: "ontid", header: "ONT", sortable: true, render: (r) => <span className="tabular-nums">{r.ontid}</span> },
  { key: "l2name", header: "L2", sortable: true, render: (r) => <span className="font-mono text-xs text-zinc-600">{r.l2name ?? "—"}</span> },
  { key: "rx_med", header: "Rx", sortable: true, render: (r) => <span className={cx("tabular-nums", r.rx_med != null && r.rx_med < -28 && "font-semibold text-red-600")}>{r.rx_med?.toFixed(1) ?? "—"}</span> },
  { key: "expected_rx", header: "Expected", render: (r) => <span className="tabular-nums text-zinc-500">{r.expected_rx?.toFixed(1) ?? "—"}</span> },
  { key: "excess_loss", header: "Excess", sortable: true, render: (r) => <Db v={r.excess_loss} unit={false} /> },
  { key: "peer_delta_l2", header: "Peer Δ L2", sortable: true, render: (r) => <Db v={r.peer_delta_l2} signed unit={false} /> },
  { key: "bip_days", header: "BIP days", sortable: true, render: (r) => r.bip_days == null ? <span className="text-zinc-300" title="vendor reports no BIP counters">n/a</span> : <span className={cx("tabular-nums", r.bip_days > 0 && "text-red-600")}>{r.bip_days}</span> },
  { key: "attributed_to", header: "Likely location", render: (r) => <AttributionBadge a={r.attributed_to} /> },
];

function SuspectFlag({ on, label }: { on: boolean; label: string }) {
  if (!on) return null;
  return <span title={`On the ${label} suspect list`} className="rounded bg-red-50 px-1 text-[10px] font-semibold text-red-700 ring-1 ring-inset ring-red-600/20">{label} ⚠</span>;
}

function Tree({ ports, sel, onSel, expanded, toggle }: {
  ports: TreePort[]; sel: Sel; onSel: (s: Sel) => void; expanded: Set<string>; toggle: (p: string) => void;
}) {
  return (
    <div className="flex flex-col text-sm">
      <button type="button" onClick={() => onSel(null)}
        className={cx("rounded-md px-2 py-1.5 text-left text-xs font-medium", !sel ? "bg-zinc-900 text-white" : "text-zinc-600 hover:bg-zinc-100")}>
        All PONs
      </button>
      {ports.map((p) => {
        const open = expanded.has(p.ponport);
        const active = sel?.ponport === p.ponport && !sel.l2name;
        return (
          <div key={`${p.ponport}|${p.l1name}`} className={cx("rounded-md", p.suspect && "ring-1 ring-inset ring-red-200")}>
            <div className={cx("flex items-center gap-1 rounded-md pr-2", active ? "bg-zinc-100" : "hover:bg-zinc-50")}>
              <button type="button" onClick={() => toggle(p.ponport)} aria-label={open ? "Collapse" : "Expand"} className="w-6 shrink-0 py-1.5 text-xs text-zinc-400 hover:text-zinc-800">{open ? "▾" : "▸"}</button>
              <button type="button" onClick={() => onSel({ ponport: p.ponport, l1name: p.l1name })} className="flex min-w-0 flex-1 items-center gap-2 py-1.5 text-left">
                <span className="w-16 shrink-0 font-mono text-xs text-zinc-800">{p.ponport}</span>
                <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-zinc-500">{p.l1name ?? "no L1"}</span>
                <SuspectFlag on={p.suspect} label="L1" />
                <BadShare bad={p.n_bad} total={p.n_onu} />
              </button>
            </div>
            {open && (
              <div className="mb-1 ml-6 border-l border-zinc-200 pl-1">
                {p.l2.map((l) => {
                  const a = sel?.ponport === p.ponport && sel.l2name === l.l2name && sel.l2name !== undefined;
                  return (
                    <button key={l.l2name ?? "none"} type="button" onClick={() => onSel({ ponport: p.ponport, l1name: p.l1name, l2name: l.l2name })}
                      title={l.med_peer_delta != null ? `median Rx ${l.med_rx} dBm · peer Δ ${l.med_peer_delta} dB · excess ${l.med_excess_loss} dB` : undefined}
                      className={cx("flex w-full items-center gap-2 rounded-md px-2 py-1 text-left", a ? "bg-zinc-100" : "hover:bg-zinc-50", l.suspect && "ring-1 ring-inset ring-red-200")}>
                      <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-zinc-600">{l.l2name ?? "no L2"}</span>
                      <SuspectFlag on={l.suspect} label="L2" />
                      <BadShare bad={l.n_bad} total={l.n_onu} />
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

export function FiberTab({ deviceId, deviceName }: { deviceId: number; deviceName: string | null }) {
  const [sp, setSp] = useSearchParams();
  const date = sp.get("date") ?? undefined;
  const tree = useQuery({ queryKey: ["fiberTree", deviceId, date], queryFn: () => fiberApi.tree(deviceId, date), staleTime: 300_000 });
  const [onlyBad, setOnlyBad] = useState(true);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [sel, setSel] = useState<Sel>(null);
  const [sort, setSort] = useState("score");
  const [order, setOrder] = useState<"asc" | "desc">("asc");
  const [page, setPage] = useState(1);
  // ODN tree order: PON port (default) or worst first; ?tree=worst keeps it in the link.
  const worstFirst = sp.get("tree") === "worst";

  const setParam = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(sp);
    for (const [k, v] of Object.entries(patch)) v ? next.set(k, v) : next.delete(k);
    setSp(next, { replace: true });
  };

  // Deep link: ?l1=...&l2=... selects (and expands) that node once the tree has loaded.
  useEffect(() => {
    const t = tree.data;
    if (!t) return;
    const l1 = sp.get("l1"), l2 = sp.get("l2");
    if (!l1 && !l2) {
      const worst = t.items.filter((p) => p.suspect).map((p) => p.ponport);
      if (worst.length) setExpanded(new Set(worst));
      return;
    }
    const port = t.items.find((p) => (l2 && p.l2.some((x) => x.l2name === l2)) || (!l2 && p.l1name === l1));
    if (port) {
      setSel({ ponport: port.ponport, l1name: port.l1name, ...(l2 ? { l2name: l2 } : {}) });
      setExpanded(new Set([port.ponport]));
    }
  }, [tree.data]); // eslint-disable-line react-hooks/exhaustive-deps

  const ports = useMemo(() => {
    const items = tree.data?.items ?? [];
    const list = onlyBad ? items.filter((p) => p.n_bad > 0).map((p) => ({ ...p, l2: p.l2.filter((l) => l.n_bad > 0) })) : items;
    // The API returns ports in natural port order (0-0-1-2 before 0-0-1-10).
    if (!worstFirst) return list;
    return [...list].sort((a, b) => Number(b.suspect) - Number(a.suspect) || b.n_bad / b.n_onu - a.n_bad / a.n_onu || a.ponport.localeCompare(b.ponport, undefined, { numeric: true }));
  }, [tree.data, onlyBad, worstFirst]);

  const onSel = (s: Sel) => {
    setSel(s);
    setPage(1);
    setParam({ l1: s && !s.l2name ? s.l1name : null, l2: s?.l2name ?? null });
  };
  const toggle = (p: string) => setExpanded((e) => { const n = new Set(e); n.has(p) ? n.delete(p) : n.add(p); return n; });

  const params = {
    date, ponport: sel?.ponport, l2name: sel?.l2name ?? undefined,
    max_score: onlyBad && !sel ? BAD_SCORE : undefined, sort, order, page, size: 50,
  };
  const onus = useQuery({
    queryKey: ["fiberOnus", deviceId, params],
    queryFn: ({ signal }) => fiberApi.onus(deviceId, params, signal),
    placeholderData: keepPreviousData,
    enabled: tree.isSuccess,
  });

  const onuParam = sp.get("onu");
  const [onuPort, onuId] = onuParam ? [onuParam.slice(0, onuParam.lastIndexOf(":")), onuParam.slice(onuParam.lastIndexOf(":") + 1)] : [null, null];

  if (tree.error) return <ErrorBox error={tree.error} />;
  if (tree.isLoading) return <div className="flex justify-center p-8"><Spinner /></div>;
  const t = tree.data!;
  if (!t.n_onu) return <Card><Empty>No fiber scores for this OLT in run {t.date}.</Empty></Card>;

  const selLabel = !sel ? (onlyBad ? `Bad ONUs on ${t.device}` : `All ONUs on ${t.device}`) : sel.l2name !== undefined ? `L2 ${sel.l2name ?? "(none)"} on PON ${sel.ponport}` : `PON ${sel.ponport} · L1 ${sel.l1name ?? "—"}`;

  return (
    <div className="flex flex-col gap-4">
      <div className="-mb-2 flex justify-end"><FiberHelpLink /></div>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        {([
          ["ONUs scored", num(t.n_onu), ""],
          [`Bad ONUs (≤ ${BAD_SCORE})`, `${num(t.n_bad)} · ${((t.n_bad / t.n_onu) * 100).toFixed(1)}%`, t.n_bad ? "text-red-600" : ""],
          ["PON ports", num(t.n_ports), ""],
          ["Suspect PONs (L1)", num(t.n_suspect_l1), t.n_suspect_l1 ? "text-red-600" : ""],
          ["Suspect L2 segments", num(t.n_suspect_l2), t.n_suspect_l2 ? "text-orange-600" : ""],
        ] as [string, string, string][]).map(([k, v, c]) => (
          <div key={k} className="rounded-xl border border-zinc-200 bg-white px-4 py-3 shadow-sm">
            <div className="text-xs text-zinc-500">{k}</div>
            <div className={cx("mt-0.5 text-xl font-semibold tabular-nums text-zinc-900", c)}>{v}</div>
          </div>
        ))}
      </div>
      {t.device_suspect && (
        <div className="rounded-lg border border-violet-200 bg-violet-50 px-3 py-2 text-sm text-violet-800">
          This OLT is on the suspect list as a whole: most of its PONs are bad. Check optics batch, configuration, or site power and temperature before dispatching fiber crews.
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(320px,420px)_1fr]">
        <Card title="ODN tree" actions={
          <div className="flex items-center gap-3">
            <div className="flex rounded-md bg-zinc-100 p-0.5 text-xs" role="group" aria-label="Sort ports">
              {([["Port", false], ["Worst first", true]] as const).map(([label, w]) => (
                <button key={label} type="button" onClick={() => setParam({ tree: w ? "worst" : null })}
                  className={cx("rounded px-2 py-0.5 font-medium", worstFirst === w ? "bg-white text-zinc-900 shadow-sm" : "text-zinc-500 hover:text-zinc-800")}>
                  {label}
                </button>
              ))}
            </div>
            <label className="flex items-center gap-1.5 text-xs text-zinc-600">
              <input type="checkbox" checked={onlyBad} onChange={(e) => { setOnlyBad(e.target.checked); setPage(1); }} /> Only bad
            </label>
          </div>} bodyClass="px-3 pb-3 pt-1">
          <p className="mb-2 px-2 text-[11px] text-zinc-400">PON (L1) → L2. Bar = share of ONUs scored ≤ {BAD_SCORE}. ⚠ = on a suspect list. Run {t.date}.</p>
          <div className="max-h-[640px] overflow-y-auto">
            {ports.length ? <Tree ports={ports} sel={sel} onSel={onSel} expanded={expanded} toggle={toggle} /> : <Empty>No bad ONUs on this OLT</Empty>}
          </div>
        </Card>
        <Card title={selLabel} actions={<span className="text-xs text-zinc-400">click an ONU for its score breakdown</span>} bodyClass="px-2 pb-3 pt-1">
          {onus.error ? <ErrorBox error={onus.error} /> : (
            <DataTable columns={ONU_COLS} rows={onus.data?.items ?? []} rowKey={(r) => `${r.ponport}:${r.ontid}`} dense loading={onus.isFetching}
              sort={sort} order={order}
              onSort={(k) => { setOrder(sort === k && order === "asc" ? "desc" : "asc"); setSort(k); setPage(1); }}
              onRowClick={(r) => setParam({ onu: `${r.ponport}:${r.ontid}` })} empty="No ONUs" />
          )}
          <div className="px-2"><Pagination page={page} size={50} total={onus.data?.total ?? 0} onPage={setPage} /></div>
        </Card>
      </div>

      {onuPort && onuId && (
        <OnuDrawer deviceId={deviceId} deviceName={deviceName} ponport={onuPort} ontid={onuId} date={date} onClose={() => setParam({ onu: null })} />
      )}
    </div>
  );
}
