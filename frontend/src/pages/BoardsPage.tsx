import { useNavigate, useSearchParams } from "react-router";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api, type Params } from "../api/client";
import type { BoardRow } from "../api/types";
import { DataTable, type Column } from "../components/DataTable";
import { FacetSelect } from "../components/FacetSelect";
import { Button, Card, ErrorBox, Field, inputCls, Pagination, Spinner, StatusBadge, PAGE_CLS } from "../components/ui";
import { useDraft } from "../hooks/useDraft";
import { ago, dash, fmtTime, num } from "../lib/format";

const COLUMNS: Column<BoardRow>[] = [
  { key: "device_name", header: "Device", sortable: true, render: (r) => <span className="font-mono text-xs font-medium text-zinc-900">{dash(r.device_name)}</span> },
  { key: "device_ip", header: "Device IP", sortable: true, render: (r) => <span className="font-mono text-xs">{dash(r.device_ip)}</span> },
  { key: "boardname", header: "Board", sortable: true, render: (r) => <span className="font-mono text-xs">{dash(r.boardname)}</span> },
  { key: "boardtype", header: "Type", sortable: true, render: (r) => <span className="font-medium text-zinc-900">{dash(r.boardtype)}</span> },
  { key: "boardrole", header: "Role", sortable: true, render: (r) => dash(r.boardrole) },
  { key: "operstatus", header: "Status", sortable: true, render: (r) => <StatusBadge value={r.operstatus} /> },
  { key: "first", header: "First seen", sortable: true, render: (r) => <span className="whitespace-nowrap text-zinc-500">{fmtTime(r.first)}</span> },
  { key: "lastseen", header: "Last seen", sortable: true, render: (r) => <span className="whitespace-nowrap text-zinc-500" title={fmtTime(r.lastseen)}>{ago(r.lastseen)}</span> },
];

const FILTERS = [["operstatus", "Status"], ["boardtype", "Type"], ["boardrole", "Role"]] as const;
const DEFAULT_SORT = "device_name";

export function BoardsPage() {
  const [sp, setSp] = useSearchParams();
  const navigate = useNavigate();
  const page = Number(sp.get("page") ?? 1);
  const size = Number(sp.get("size") ?? 50);
  const sort = sp.get("sort") ?? DEFAULT_SORT;
  const order = sp.get("order") === "desc" ? "desc" : "asc";

  const update = (patch: Record<string, string | number | null>) => {
    const next = new URLSearchParams(sp);
    for (const [k, v] of Object.entries(patch)) {
      if (v === null || v === "") next.delete(k);
      else next.set(k, String(v));
    }
    setSp(next, { replace: true });
  };
  const [device, setDevice] = useDraft(sp.get("device") ?? "", (v) => update({ device: v, page: null }));
  const [q, setQ] = useDraft(sp.get("q") ?? "", (v) => update({ q: v, page: null }));

  const params: Params = { page, size, sort, order, device: sp.get("device"), q: sp.get("q") };
  for (const [f] of FILTERS) params[f] = sp.get(f);

  const list = useQuery({
    queryKey: ["boards", params],
    queryFn: ({ signal }) => api.boards(params, signal),
    placeholderData: keepPreviousData,
  });
  const facets = useQuery({ queryKey: ["boardFacets"], queryFn: api.boardFacets, staleTime: 600_000 });

  const active = ["device", "q", ...FILTERS.map(([f]) => f)].filter((k) => sp.get(k)).length;

  return (
    <div className={PAGE_CLS}>
      <div>
        <h1 className="text-xl font-semibold text-zinc-900">Boards</h1>
        <p className="text-sm text-zinc-500">
          Every board (line cards, control boards, power, fans) reported by the devices. Status wording differs by vendor. Click a row to open its device.
        </p>
      </div>

      <Card bodyClass="p-0">
        <div className="grid grid-cols-2 gap-3 border-b border-zinc-100 p-4 sm:grid-cols-3 lg:grid-cols-5">
          <Field label="Device">
            <input className={inputCls} placeholder="Device name or IP prefix" value={device} onChange={(e) => setDevice(e.target.value)} />
          </Field>
          <Field label="Board text">
            <input className={inputCls} placeholder="Board name, type or role" value={q} onChange={(e) => setQ(e.target.value)} />
          </Field>
          {FILTERS.map(([f, label]) => (
            <FacetSelect key={f} name={label} value={sp.get(f) ?? ""} options={facets.data?.[f]} loading={facets.isLoading} sortByName={f === "boardtype"}
              showCounts={false} onChange={(v) => update({ [f]: v, page: null })} />
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2 px-4 py-2 text-sm text-zinc-500">
          {list.isFetching && <Spinner />}
          {list.data && <span><b className="text-zinc-800">{num(list.data.total)}</b> boards</span>}
          {active > 0 && (
            <Button variant="ghost" onClick={() => { setDevice(""); setQ(""); setSp(new URLSearchParams(sort !== DEFAULT_SORT || order !== "asc" ? { sort, order } : {}), { replace: true }); }}>
              Clear {active} filter{active > 1 ? "s" : ""}
            </Button>
          )}
        </div>
        <div className="px-1">
          {list.error ? <div className="p-4"><ErrorBox error={list.error} /></div> : (
            <DataTable columns={COLUMNS} rows={list.data?.items ?? []} rowKey={(r) => r.id} dense
              sort={sort} order={order} onSort={(key) => update({ sort: key, order: sort === key && order === "asc" ? "desc" : "asc", page: null })}
              loading={list.isFetching} empty="No boards match these filters"
              onRowClick={(r) => r.device_id != null && navigate(`/devices/${r.device_id}`)} />
          )}
        </div>
        <div className="px-4 pb-3">
          {list.data && list.data.total > 0 && (
            <Pagination page={page} size={size} total={list.data.total}
              onPage={(p) => update({ page: p })} onSize={(s) => update({ size: s, page: null })} />
          )}
        </div>
      </Card>
    </div>
  );
}
