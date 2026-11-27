import { useNavigate, useSearchParams } from "react-router";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api, type Params } from "../api/client";
import type { FleetInterface } from "../api/types";
import { DataTable, type Column } from "../components/DataTable";
import { FacetSelect } from "../components/FacetSelect";
import { useDraft } from "../hooks/useDraft";
import { Button, Card, ErrorBox, Field, inputCls, Pagination, Spinner, StatusBadge, PAGE_CLS } from "../components/ui";
import { ago, dash, fmtTime, num } from "../lib/format";

const COLUMNS: Column<FleetInterface>[] = [
  { key: "device_name", header: "Device", sortable: true, render: (r) => <span className="font-mono text-xs font-medium text-zinc-900">{dash(r.device_name)}</span> },
  { key: "device_ip", header: "Device IP", sortable: true, render: (r) => <span className="font-mono text-xs">{dash(r.device_ip)}</span> },
  { key: "name", header: "Name", sortable: true, className: "max-w-[220px] truncate", render: (r) => <span className="font-mono text-xs" title={r.name ?? ""}>{dash(r.name)}</span> },
  { key: "altname", header: "Alt name", sortable: true, render: (r) => <span className="font-mono text-xs">{dash(r.altname)}</span> },
  { key: "ifspeed", header: "Speed", sortable: true, render: (r) => <span className="whitespace-nowrap">{dash(r.speed_text)}</span> },
  { key: "ifoper", header: "Oper", sortable: true, render: (r) => <StatusBadge value={r.ifoper} /> },
  { key: "dsttype", header: "Dst type", sortable: true, render: (r) => dash(r.dsttype) },
  { key: "dstsite", header: "Dst site", sortable: true, render: (r) => <span className="font-mono text-xs">{dash(r.dstsite)}</span> },
  { key: "dstport", header: "Dst port", sortable: true, render: (r) => <span className="font-mono text-xs">{dash(r.dstport)}</span> },
  { key: "moduleclass", header: "Module class", sortable: true, render: (r) => dash(r.moduleclass) },
  { key: "lastseen", header: "Last seen", sortable: true, render: (r) => <span className="whitespace-nowrap text-zinc-500" title={fmtTime(r.lastseen)}>{ago(r.lastseen)}</span> },
];

const FILTERS = [["ifoper", "Oper"], ["dsttype", "Dst type"], ["moduleclass", "Module class"]] as const;

export function InterfacesPage() {
  const [sp, setSp] = useSearchParams();
  const navigate = useNavigate();
  const page = Number(sp.get("page") ?? 1);
  const size = Number(sp.get("size") ?? 50);
  const sort = sp.get("sort") ?? "name";
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
    queryKey: ["fleetInterfaces", params],
    queryFn: ({ signal }) => api.fleetInterfaces(params, signal),
    placeholderData: keepPreviousData,
  });
  const facets = useQuery({ queryKey: ["intfFacets"], queryFn: api.intfFacets, staleTime: 3_600_000 });

  const active = ["device", "q", ...FILTERS.map(([f]) => f)].filter((k) => sp.get(k)).length;
  const slowSearch = !!sp.get("q") && !sp.get("device");

  return (
    <div className={PAGE_CLS}>
      <div>
        <h1 className="text-xl font-semibold text-zinc-900">Interfaces</h1>
        <p className="text-sm text-zinc-500">Every interface in the inventory, across all devices. Click a row to open its device.</p>
      </div>

      <Card bodyClass="p-0">
        <div className="grid grid-cols-2 gap-3 border-b border-zinc-100 p-4 sm:grid-cols-3 lg:grid-cols-6">
          <Field label="Device">
            <input className={inputCls} placeholder="Device name or IP prefix" value={device} onChange={(e) => setDevice(e.target.value)} />
          </Field>
          <div className="col-span-2 sm:col-span-2">
            <Field label="Interface text">
              <input className={inputCls} placeholder="Name, alt name, description, dst site or port" value={q} onChange={(e) => setQ(e.target.value)} />
            </Field>
          </div>
          {FILTERS.map(([f, label]) => (
            <FacetSelect key={f} name={label} value={sp.get(f) ?? ""} options={facets.data?.[f]} loading={facets.isLoading} showCounts={false}
              onChange={(v) => update({ [f]: v, page: null })} />
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2 px-4 py-2 text-sm text-zinc-500">
          {list.isFetching && <Spinner />}
          {list.data && <span><b className="text-zinc-800">{num(list.data.total)}</b> interfaces</span>}
          {slowSearch && list.isFetching && <span className="text-xs text-zinc-400">Searching all interfaces takes a few seconds; add a device to narrow it.</span>}
          {active > 0 && (
            <Button variant="ghost" onClick={() => { setDevice(""); setQ(""); setSp(new URLSearchParams(sort !== "name" || order !== "asc" ? { sort, order } : {}), { replace: true }); }}>
              Clear {active} filter{active > 1 ? "s" : ""}
            </Button>
          )}
        </div>
        <div className="px-1">
          {list.error ? <div className="p-4"><ErrorBox error={list.error} /></div> : (
            <DataTable columns={COLUMNS} rows={list.data?.items ?? []} rowKey={(r) => r.id} dense
              sort={sort} order={order} onSort={(key) => update({ sort: key, order: sort === key && order === "asc" ? "desc" : "asc", page: null })}
              loading={list.isFetching} empty="No interfaces match these filters"
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
