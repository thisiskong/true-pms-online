import { useEffect, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { Interface, IntfChange } from "../../api/types";
import { fmtTime, num } from "../../lib/format";
import { DataTable, type Column } from "../DataTable";
import { Modal } from "../Modal";
import { ErrorBox, inputCls, Pagination, Spinner, StatusBadge, cx } from "../ui";

const COLUMNS: Column<Interface>[] = [
  { key: "ifindex", header: "ifIndex", sortable: true, render: (r) => <span className="tabular-nums text-zinc-500">{r.ifindex}</span> },
  { key: "ifname", header: "Name", sortable: true, render: (r) => <span className="font-medium text-zinc-900">{r.ifname ?? "—"}</span> },
  { key: "ifalias", header: "Description", sortable: true, render: (r) => <span className="block max-w-[360px] truncate" title={r.ifalias ?? ""}>{r.ifalias || "—"}</span> },
  { key: "ifoper", header: "Oper", sortable: true, render: (r) => <StatusBadge value={r.ifoper} /> },
  { key: "ifadmin", header: "Admin", sortable: true, render: (r) => <StatusBadge value={r.ifadmin} /> },
  { key: "ifspeed", header: "Speed", sortable: true, render: (r) => r.speed_text ?? "—" },
  { key: "iftype", header: "Type", sortable: true, render: (r) => <span className="text-zinc-500">{r.iftype ?? "—"}</span> },
  { key: "dstname", header: "LLDP neighbor", sortable: true, render: (r) => r.dstname ? <span>{r.dstname}<span className="text-zinc-400"> · {r.dstport}</span></span> : "—" },
  { key: "lastseen", header: "Last seen", sortable: true, render: (r) => <span className="text-zinc-500">{fmtTime(r.lastseen)}</span> },
];

export const REV_COLS: Column<IntfChange>[] = [
  { key: "rev", header: "Rev", render: (r) => <span className="tabular-nums text-zinc-500">{r.rev}</span> },
  { key: "ifoper", header: "Oper", render: (r) => <StatusBadge value={r.ifoper} /> },
  { key: "speed_text", header: "Speed", render: (r) => r.speed_text ?? "—" },
  { key: "ifname", header: "Name", render: (r) => r.ifname ?? "—" },
  { key: "first", header: "From", render: (r) => fmtTime(r.first) },
  { key: "lastseen", header: "Last seen", render: (r) => <span className="text-zinc-500">{fmtTime(r.lastseen)}</span> },
];

/** Revision history of one interface; also opened from the Unstable interfaces page. */
export function RevModal({ intf, onClose }: { intf: Pick<Interface, "id" | "device_id" | "ifname" | "ifalias">; onClose: () => void }) {
  const q = useQuery({ queryKey: ["intfRev", intf.id], queryFn: () => api.changes(intf.device_id ?? 0, { interface_id: intf.id, limit: 500 }) });
  return (
    <Modal title={`${intf.ifname ?? intf.id} · revision history`} onClose={onClose}
      subtitle={<>{intf.ifalias || "No description"} · each row is a state interval from <code>intf_rev</code>, newest first</>}>
      {q.error ? <ErrorBox error={q.error} /> : q.isLoading ? <div className="flex justify-center p-8"><Spinner /></div> : (
        <>
          <DataTable columns={REV_COLS} rows={q.data?.items ?? []} rowKey={(r) => `${r.id}-${r.rev}`} dense empty="No revisions recorded for this interface" />
          {q.data?.truncated && <p className="pt-2 text-xs text-zinc-400">Showing the latest 500 revisions.</p>}
        </>
      )}
    </Modal>
  );
}

const OPERS = ["", "up", "down", "lowerLayerDown", "dormant", "notPresent"];

export function InterfaceTable({ deviceId, oper, onOper }: { deviceId: number; oper: string; onOper: (v: string) => void }) {
  const [page, setPage] = useState(1);
  const [size, setSize] = useState(50);
  const [sort, setSort] = useState("ifindex");
  const [order, setOrder] = useState<"asc" | "desc">("asc");
  const [qDraft, setQDraft] = useState("");
  const [q, setQ] = useState("");
  const [picked, setPicked] = useState<Interface | null>(null);

  useEffect(() => {
    const t = setTimeout(() => { setQ(qDraft); setPage(1); }, 300);
    return () => clearTimeout(t);
  }, [qDraft]);
  useEffect(() => setPage(1), [oper]);

  const params = { page, size, sort, order, q, oper };
  const list = useQuery({
    queryKey: ["interfaces", deviceId, params],
    queryFn: ({ signal }) => api.interfaces(deviceId, params, signal),
    placeholderData: keepPreviousData,
  });
  // Device-wide counts per oper status (same cached query as the dashboard's summary card).
  const summary = useQuery({ queryKey: ["intfSummary", deviceId], queryFn: () => api.interfaceSummary(deviceId) });
  const count = (o: string): number | undefined =>
    summary.data && (o ? summary.data.by_oper[o] ?? 0 : summary.data.total);

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <input className={cx(inputCls, "max-w-xs")} placeholder="Filter name, description, neighbor" value={qDraft} onChange={(e) => setQDraft(e.target.value)} />
        <div className="flex flex-wrap gap-1">
          {/* Same style as the PON port filter: statuses with no interfaces are hidden (unless selected). */}
          {OPERS.filter((o) => !o || o === oper || count(o) !== 0).map((o) => {
            const n = count(o);
            return (
              <button key={o || "all"} type="button" onClick={() => onOper(o)}
                className={cx("rounded-md px-2 py-1 text-xs font-medium", oper === o ? "bg-zinc-900 text-white" : "bg-zinc-100 text-zinc-600 hover:bg-zinc-200")}>
                {o || "all"}{n !== undefined && <> <span className="opacity-60">{num(n)}</span></>}
              </button>
            );
          })}
        </div>
      </div>
      {list.error ? <ErrorBox error={list.error} /> : (
        <DataTable columns={COLUMNS} rows={list.data?.items ?? []} rowKey={(r) => r.id} dense onRowClick={setPicked}
          sort={sort} order={order} loading={list.isFetching} empty="No interfaces match"
          onSort={(k) => { setOrder(sort === k && order === "asc" ? "desc" : "asc"); setSort(k); setPage(1); }} />
      )}
      {list.data && list.data.total > 0 && (
        <Pagination page={page} size={size} total={list.data.total} onPage={setPage} onSize={(s) => { setSize(s); setPage(1); }} />
      )}
      {picked && <RevModal intf={picked} onClose={() => setPicked(null)} />}
    </div>
  );
}
