import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { fiberApi, type Attribution, type BadOnuRow } from "../../api/fiber";
import { DataTable, type Column } from "../DataTable";
import { Button, Card, cx, ErrorBox, Field, inputCls, Pagination } from "../ui";
import { num } from "../../lib/format";
import { ATTRIBUTION, Db, hwFaults, ScoreChip } from "./score";

const mono = (v: string | null | undefined, c = "text-zinc-700") => <span className={cx("font-mono text-xs", c)}>{v ?? "—"}</span>;

const COLUMNS: Column<BadOnuRow>[] = [
  { key: "score", header: "Score", sortable: true, render: (r) => <ScoreChip score={r.score} conf={r.conf} /> },
  { key: "device", header: "OLT", sortable: true, render: (r) => mono(r.device, r.device_id ? "text-zinc-900" : "text-zinc-400") },
  { key: "province", header: "Province", render: (r) => <span className="block max-w-[180px] truncate text-zinc-600" title={r.province ?? undefined}>{r.province ?? <span className="text-zinc-300">unknown</span>}</span> },
  { key: "ponport", header: "PON", sortable: true, render: (r) => mono(r.ponport) },
  { key: "ontid", header: "ONT", sortable: true, render: (r) => <span className="tabular-nums">{r.ontid}</span> },
  { key: "l2name", header: "L2", sortable: true, render: (r) => mono(r.l2name, "text-zinc-600") },
  { key: "vendor", header: "Vendor", render: (r) => <span className="text-zinc-600">{r.vendor ?? "—"}</span> },
  { key: "rx_med", header: "Rx", sortable: true, render: (r) => <span className={cx("tabular-nums", r.rx_med != null && r.rx_med < -28 && "font-semibold text-red-600")}>{r.rx_med?.toFixed(1) ?? "—"}</span> },
  { key: "expected_rx", header: "Expected", render: (r) => <span className="tabular-nums text-zinc-500">{r.expected_rx?.toFixed(1) ?? "—"}</span> },
  { key: "excess_loss", header: "Excess", sortable: true, render: (r) => <Db v={r.excess_loss} unit={false} /> },
  { key: "peer_delta_l2", header: "Peer Δ L2", sortable: true, render: (r) => <Db v={r.peer_delta_l2} signed unit={false} /> },
  { key: "bip_days", header: "BIP days", sortable: true, render: (r) => r.bip_days == null ? <span className="text-zinc-300">n/a</span> : <span className={cx("tabular-nums", r.bip_days > 0 && "text-red-600")}>{r.bip_days}</span> },
  { key: "hw_flag", header: "Hardware", render: (r) => {
    const f = hwFaults(r);
    if (!r.hw_flag && !f.length) return null;
    return (
      <span title="ONU readings outside the normal range (days in the window)"
        className={cx("whitespace-nowrap rounded px-1 text-[10px] font-semibold ring-1 ring-inset", r.hw_flag ? "bg-violet-50 text-violet-700 ring-violet-600/20" : "bg-zinc-50 text-zinc-500 ring-zinc-300")}>
        {f.length ? f.join(" · ") : "HW"}
      </span>
    );
  } },
];

const NOTE: Record<Attribution, string> = {
  drop: "Isolated bad ONUs whose L2 siblings are healthy: check the drop cable, connectors and the ONU itself.",
  l2: "Bad ONUs explained by a suspect L2 segment. Fixing the L2 splitter or distribution fiber should fix them together.",
  l1: "Bad ONUs explained by a suspect PON (L1). May be feeder fiber, the L1 splitter, or the OLT PON optic.",
  device: "Bad ONUs on an OLT that is bad as a whole: optics batch, configuration, or site power/temperature.",
  onu_hw: "Isolated bad ONUs whose own hardware readings (Tx, voltage, temperature or current) are out of range: likely the ONU, not the fiber.",
};

/** Network-wide list of bad ONUs with one likely location. Row click opens the ONU on its OLT's Fiber health tab. */
export function BadOnuList({ att, date, page, sort, order, q, onChange, onClose }: {
  att: Attribution; date?: string; page: number; sort: string; order: "asc" | "desc"; q: string;
  onChange: (patch: Record<string, string | number | null>) => void; onClose: () => void;
}) {
  const navigate = useNavigate();
  const [size, setSize] = useState(25);
  const [qDraft, setQDraft] = useState(q);
  useEffect(() => setQDraft(q), [q]);
  useEffect(() => {
    if (qDraft === q) return;
    const t = setTimeout(() => onChange({ oq: qDraft, opage: null }), 300);
    return () => clearTimeout(t);
  }, [qDraft]); // eslint-disable-line react-hooks/exhaustive-deps

  const params = { attributed_to: att, date, q, sort, order, page, size };
  const list = useQuery({
    queryKey: ["fiberBadOnus", params],
    queryFn: ({ signal }) => fiberApi.badOnus(params, signal),
    placeholderData: keepPreviousData,
  });
  const x = ATTRIBUTION[att];
  const open = (r: BadOnuRow) => {
    if (r.device_id) navigate(`/devices/${r.device_id}?${new URLSearchParams({ tab: "fiber", onu: `${r.ponport}:${r.ontid}` })}`);
  };
  const onSort = (key: string) => onChange({ osort: key, oorder: sort === key && order === "asc" ? "desc" : "asc", opage: null });

  return (
    <Card bodyClass="p-0"
      title={<span className="inline-flex items-center gap-2"><span className="size-2.5 rounded-full" style={{ background: x.hex }} />Bad ONUs · {x.label}
        {list.data && <span className="text-sm font-normal text-zinc-400">{num(list.data.total)}</span>}</span>}
      actions={<Button variant="ghost" onClick={onClose} aria-label="Close list">✕</Button>}>
      <div className="flex flex-wrap items-end justify-between gap-3 px-4 pt-3">
        <p className="max-w-3xl text-xs text-zinc-500">{NOTE[att]} Click a row to open the ONU on its OLT.</p>
        <div className="w-64">
          <Field label="Search">
            <input className={inputCls} placeholder="OLT, L1 or L2 name" value={qDraft} onChange={(e) => setQDraft(e.target.value)} />
          </Field>
        </div>
      </div>
      <div className="px-1 pt-2">
        {list.error ? <div className="p-4"><ErrorBox error={list.error} /></div> : (
          <DataTable columns={COLUMNS} rows={list.data?.items ?? []} loading={list.isFetching} dense
            rowKey={(r) => `${r.device}|${r.ponport}|${r.ontid}`} sort={sort} order={order} onSort={onSort} onRowClick={open}
            empty="No bad ONUs match" />
        )}
      </div>
      <div className="px-4 pb-3">
        <Pagination page={page} size={size} total={list.data?.total ?? 0} onPage={(p) => onChange({ opage: p })}
          onSize={(n) => { setSize(n); onChange({ opage: null }); }} />
      </div>
    </Card>
  );
}
