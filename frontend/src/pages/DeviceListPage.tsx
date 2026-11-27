import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api, type Params } from "../api/client";
import type { DeviceRow } from "../api/types";
import { DataTable, type Column } from "../components/DataTable";
import { FacetSelect } from "../components/FacetSelect";
import { Button, Card, ErrorBox, Field, inputCls, Pagination, Spinner, StatusBadge, PAGE_CLS } from "../components/ui";
import { ago, fmtTime } from "../lib/format";

const FILTERS = ["vendor", "model", "network", "topology", "region", "province"] as const;

const COLUMNS: Column<DeviceRow>[] = [
  { key: "name", header: "Name", sortable: true, render: (r) => <span className="font-mono text-xs font-medium text-zinc-900">{r.name ?? "—"}</span> },
  { key: "ip", header: "IP", sortable: true, render: (r) => <span className="font-mono text-xs">{r.ip ?? "—"}</span> },
  { key: "vendor", header: "Vendor", sortable: true },
  { key: "model", header: "Model", sortable: true },
  { key: "network", header: "Network", sortable: true },
  { key: "topology", header: "Topology", sortable: true },
  { key: "region", header: "Region", sortable: true },
  { key: "province", header: "Province", sortable: true, className: "max-w-[220px] truncate" },
  { key: "sitename", header: "Site", sortable: true },
  { key: "pollstatus", header: "Poll", sortable: true, render: (r) => <StatusBadge value={r.pollstatus} /> },
  { key: "lastseen", header: "Last seen", sortable: true, render: (r) => <span title={fmtTime(r.lastseen)}>{ago(r.lastseen)}</span> },
];

export function DeviceListPage() {
  const [sp, setSp] = useSearchParams();
  const navigate = useNavigate();
  const page = Number(sp.get("page") ?? 1);
  const size = Number(sp.get("size") ?? 50);
  const sort = sp.get("sort") ?? "name";
  const order = (sp.get("order") ?? "asc") as "asc" | "desc";
  const q = sp.get("q") ?? "";
  const [qDraft, setQDraft] = useState(q);

  useEffect(() => setQDraft(q), [q]);

  // Debounced free-text search
  useEffect(() => {
    if (qDraft === q) return;
    const t = setTimeout(() => update({ q: qDraft, page: null }), 350);
    return () => clearTimeout(t);
  }, [qDraft]); // eslint-disable-line react-hooks/exhaustive-deps

  const update = (patch: Record<string, string | number | null>) => {
    const next = new URLSearchParams(sp);
    for (const [k, v] of Object.entries(patch)) {
      if (v === null || v === "") next.delete(k);
      else next.set(k, String(v));
    }
    setSp(next, { replace: true });
  };

  const params: Params = { page, size, sort, order, q, pollstatus: sp.get("pollstatus") };
  for (const f of FILTERS) params[f] = sp.get(f);

  // Facet counts depend on the active filters (not on paging/sorting).
  const { page: _pg, size: _sz, sort: _so, order: _or, ...filterParams } = params;
  const facets = useQuery({
    queryKey: ["facets", filterParams],
    queryFn: ({ signal }) => api.facets(filterParams, signal),
    staleTime: 60_000,
    placeholderData: keepPreviousData,
  });
  const list = useQuery({
    queryKey: ["devices", params],
    queryFn: ({ signal }) => api.devices(params, signal),
    placeholderData: keepPreviousData,
  });

  const onSort = (key: string) =>
    update({ sort: key, order: sort === key && order === "asc" ? "desc" : "asc", page: null });

  const activeFilters = FILTERS.filter((f) => sp.get(f)).length + (q ? 1 : 0) + (sp.get("pollstatus") ? 1 : 0);
  const { page: _p, size: _s, ...exportParams } = params;

  return (
    <div className={PAGE_CLS}>
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold text-zinc-900">Devices</h1>
          <p className="text-sm text-zinc-500">Network element inventory from discovery. Click a row to open its dashboard.</p>
        </div>
      </div>

      <Card bodyClass="p-0">
        <div className="grid grid-cols-2 gap-3 border-b border-zinc-100 p-4 sm:grid-cols-3 lg:grid-cols-9">
          <div className="col-span-2 sm:col-span-3 lg:col-span-2">
            <Field label="Search">
              <input className={inputCls} placeholder="Name, site or IP prefix" value={qDraft} onChange={(e) => setQDraft(e.target.value)} />
            </Field>
          </div>
          {FILTERS.map((f) => (
            <FacetSelect key={f} name={f} value={sp.get(f) ?? ""} options={facets.data?.[f]} loading={facets.isFetching} sortByName
              onChange={(v) => update({ [f]: v, page: null })} />
          ))}
          <FacetSelect name="Poll status" value={sp.get("pollstatus") ?? ""} options={facets.data?.pollstatus} loading={facets.isFetching}
            onChange={(v) => update({ pollstatus: v, page: null })} />
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-2">
          <div className="flex items-center gap-2 text-sm text-zinc-500">
            {list.isFetching && <Spinner />}
            {list.data && <span><b className="text-zinc-800">{list.data.total.toLocaleString()}</b> devices</span>}
            {activeFilters > 0 && (
              <Button variant="ghost" onClick={() => { setQDraft(""); setSp(new URLSearchParams({ sort, order }), { replace: true }); }}>
                Clear {activeFilters} filter{activeFilters > 1 ? "s" : ""}
              </Button>
            )}
          </div>
          <a href={api.exportUrl(exportParams)} className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-200 bg-white px-3 py-1.5 text-sm font-medium text-zinc-700 hover:bg-zinc-50">
            ⤓ Export CSV
          </a>
        </div>
        <div className="px-1">
          {list.error ? <div className="p-4"><ErrorBox error={list.error} /></div> : (
            <DataTable columns={COLUMNS} rows={list.data?.items ?? []} rowKey={(r) => r.id}
              sort={sort} order={order} onSort={onSort} loading={list.isFetching}
              onRowClick={(r) => navigate(`/devices/${r.id}`)} empty="No devices match these filters" />
          )}
        </div>
        <div className="px-4 pb-3">
          {list.data && (
            <Pagination page={page} size={size} total={list.data.total}
              onPage={(p) => update({ page: p })} onSize={(s) => update({ size: s, page: null })} />
          )}
        </div>
      </Card>
    </div>
  );
}
