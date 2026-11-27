import { useState, type ReactNode } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import type { Device, IntfChange, Neighbor } from "../api/types";
import { DataTable, type Column } from "../components/DataTable";
import { OperDonut, SpeedBars } from "../components/device/Charts";
import { InterfaceTable } from "../components/device/InterfaceTable";
import { PonPortPanel } from "../components/device/PonPortPanel";
import { FiberTab } from "../components/fiber/FiberTab";
import { Badge, Button, Card, cx, Empty, ErrorBox, Spinner, StatusBadge, PAGE_CLS } from "../components/ui";
import { useChatCtx } from "../hooks/chatContext";
import { ago, dash, fmtTime, num } from "../lib/format";

function KV({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[minmax(90px,auto)_1fr] gap-x-4 gap-y-1.5 text-sm">
      {items.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-zinc-500">{k}</dt>
          <dd className="min-w-0 break-words text-zinc-800">{v === null || v === undefined || v === "" ? <span className="text-zinc-300">—</span> : v}</dd>
        </div>
      ))}
    </dl>
  );
}

function uplink(ip: string | null, site: string | null, model: string | null): ReactNode {
  if (!ip) return null;
  return <span><span className="font-mono text-xs">{ip}</span>{site && <span className="text-zinc-500"> · {site}</span>}{model && <span className="text-zinc-400"> · {model}</span>}</span>;
}

function homing(id: string | null, site: string | null): ReactNode {
  if (!id && !site) return null;
  return <span>{dash(id)}{site && <span className="text-zinc-500"> · {site}</span>}</span>;
}

function Header({ d }: { d: Device }) {
  const { askAboutDevice } = useChatCtx();
  return (
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0">
        <div className="text-xs text-zinc-500"><Link to="/devices" className="hover:text-zinc-800">Devices</Link> / {d.topology ?? "device"}</div>
        <h1 className="mt-1 flex flex-wrap items-center gap-2 text-2xl font-semibold text-zinc-900">
          {d.name ?? `Device ${d.id}`}
          <StatusBadge value={d.pollstatus} />
        </h1>
        <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-zinc-600">
          <span className="font-mono">{d.ip}</span>
          <span className="text-zinc-300">|</span>
          <span>{[d.vendor, d.model].filter(Boolean).join(" ") || "—"}</span>
          {d.network && <Badge tone="brand">{d.network}</Badge>}
          {d.topology && <Badge>{d.topology}</Badge>}
          <span className="text-zinc-300">|</span>
          <span title={fmtTime(d.lastseen)}>last seen {ago(d.lastseen)}</span>
        </div>
      </div>
      <Button variant="primary" onClick={() => askAboutDevice({ id: d.id, name: d.name })}>✦ Ask about this device</Button>
    </div>
  );
}

function UptimeCard({ d }: { d: Device }) {
  const u = d.uptime;
  if (!u) {
    return <Card title="Uptime & reachability"><Empty>No uptime polling data for this device's IP.</Empty></Card>;
  }
  const pingAgeH = u.last_ping_success_at ? (Date.now() - Date.parse(u.last_ping_success_at)) / 3_600_000 : Infinity;
  const rebootRecent = u.last_reboot_at ? (Date.now() - Date.parse(u.last_reboot_at)) / 3_600_000 < 24 : false;
  return (
    <Card title="Uptime & reachability" actions={<span className="text-xs text-zinc-400">polled {ago(u.polled_at)}</span>}>
      <div className="mb-4 grid grid-cols-2 gap-3">
        <div className="rounded-lg bg-zinc-50 p-3">
          <div className="text-xs text-zinc-500">Uptime</div>
          <div className={cx("text-xl font-semibold", rebootRecent ? "text-amber-600" : "text-zinc-900")}>{u.uptime_text ?? "—"}</div>
        </div>
        <div className="rounded-lg bg-zinc-50 p-3">
          <div className="text-xs text-zinc-500">Last ping RTT</div>
          <div className="text-xl font-semibold text-zinc-900">{u.last_ping_rtt_ms != null ? `${u.last_ping_rtt_ms.toFixed(1)} ms` : "—"}</div>
        </div>
      </div>
      <KV items={[
        ["Last reboot", u.last_reboot_at && <span>{fmtTime(u.last_reboot_at)} <span className="text-zinc-400">({ago(u.last_reboot_at)})</span></span>],
        ["Last ping OK", u.last_ping_success_at && (
          <span className={cx(pingAgeH > 24 && "font-medium text-rose-600")}>{fmtTime(u.last_ping_success_at)} <span className="text-zinc-400">({ago(u.last_ping_success_at)})</span></span>
        )],
        ["Poll method", u.poll_method],
        ["Polled at", fmtTime(u.polled_at)],
      ]} />
    </Card>
  );
}

const CHANGE_COLS: Column<IntfChange>[] = [
  { key: "first", header: "From", render: (r) => fmtTime(r.first) },
  { key: "lastseen", header: "Last seen", render: (r) => <span className="text-zinc-500">{fmtTime(r.lastseen)}</span> },
  { key: "ifname", header: "Interface", render: (r) => <span className="font-medium">{r.ifname ?? r.id}</span> },
  { key: "ifalias", header: "Description", render: (r) => <span className="block max-w-[320px] truncate" title={r.ifalias ?? ""}>{r.ifalias || "—"}</span> },
  { key: "ifoper", header: "Oper", render: (r) => <StatusBadge value={r.ifoper} /> },
  { key: "speed_text", header: "Speed", render: (r) => r.speed_text ?? "—" },
  { key: "rev", header: "Rev", render: (r) => <span className="tabular-nums text-zinc-500">{r.rev}</span> },
];

const NBR_COLS: Column<Neighbor>[] = [
  { key: "ifname", header: "Local port", render: (r) => <span className="font-medium">{r.ifname}</span> },
  { key: "ifoper", header: "Oper", render: (r) => <StatusBadge value={r.ifoper} /> },
  { key: "dstname", header: "Neighbor", render: (r) => r.neighbor_device_id
    ? <Link className="font-mono text-xs text-brand-700 hover:underline" to={`/devices/${r.neighbor_device_id}`} onClick={(e) => e.stopPropagation()}>{r.dstname}</Link>
    : <span className="font-mono text-xs">{r.dstname ?? "—"}</span> },
  { key: "dstport", header: "Remote port" },
  { key: "neighbor_ip", header: "Neighbor IP", render: (r) => <span className="font-mono text-xs">{r.neighbor_ip ?? "—"}</span> },
  { key: "ifalias", header: "Description", render: (r) => <span className="block max-w-[320px] truncate" title={r.ifalias ?? ""}>{r.ifalias || "—"}</span> },
];

type SummaryTab = "device" | "interfaces" | "ponports" | "fiber";
const SUMMARY_TABS: SummaryTab[] = ["device", "interfaces", "ponports", "fiber"];
type Tab = "interfaces" | "changes" | "neighbors";

export function DeviceDashboard() {
  const id = Number(useParams().id);
  const [tab, setTab] = useState<Tab>("interfaces");
  const [oper, setOper] = useState("");
  const [sp, setSp] = useSearchParams();
  const urlTab = sp.get("tab") as SummaryTab | null;
  const sumTab: SummaryTab = urlTab && SUMMARY_TABS.includes(urlTab) ? urlTab : "device";
  // The summary tab lives in the URL (?tab=fiber) so suspect lists can deep-link into it.
  const setSumTab = (t: SummaryTab) => {
    const next = new URLSearchParams();
    if (t !== "device") next.set("tab", t);
    setSp(next, { replace: true });
  };

  const dev = useQuery({ queryKey: ["device", id], queryFn: () => api.device(id), enabled: Number.isFinite(id), retry: (n, e) => !(e instanceof ApiError && e.status === 404) && n < 2 });
  const summary = useQuery({ queryKey: ["intfSummary", id], queryFn: () => api.interfaceSummary(id), enabled: dev.isSuccess });
  const ponports = useQuery({ queryKey: ["ponports", id], queryFn: () => api.ponports(id), enabled: dev.isSuccess && dev.data?.topology === "OLT" });
  const changes = useQuery({ queryKey: ["changes", id], queryFn: () => api.changes(id, { limit: 200 }), enabled: dev.isSuccess && tab === "changes" });
  const nbrs = useQuery({ queryKey: ["neighbors", id], queryFn: () => api.neighbors(id), enabled: dev.isSuccess && tab === "neighbors" });

  if (dev.isLoading) return <div className="flex justify-center p-16"><Spinner className="size-6" /></div>;
  if (dev.error) {
    const notFound = dev.error instanceof ApiError && dev.error.status === 404;
    return (
      <div className="mx-auto max-w-xl p-8">
        {notFound ? <Card title="Device not found"><p className="text-sm text-zinc-600">No device with id {id}. <Link className="text-brand-700 underline" to="/devices">Back to devices</Link></p></Card> : <ErrorBox error={dev.error} />}
      </div>
    );
  }
  const d = dev.data!;
  const s = summary.data;
  const isOlt = d.topology === "OLT";
  const down = s ? (s.by_oper.down ?? 0) + (s.by_oper.lowerLayerDown ?? 0) : 0;

  const pickOper = (o: string) => { setOper(o); setTab("interfaces"); setSumTab("interfaces"); };

  return (
    <div className={PAGE_CLS}>
      <Header d={d} />

      <div className="flex gap-1 border-b border-zinc-200">
        {([
          ["device", "Device"],
          ["interfaces", `Interface${s ? ` (${num(s.total)})` : ""}`],
          ...(isOlt ? [["ponports", `PON port${ponports.data ? ` (${num(ponports.data.items.length)}${ponports.data.truncated ? "+" : ""})` : ""}`], ["fiber", "Fiber health"]] : []),
        ] as [SummaryTab, string][]).map(([k, label]) => (
          <button key={k} type="button" onClick={() => setSumTab(k)}
            className={cx("-mb-px border-b-2 px-3 py-2 text-sm font-medium", sumTab === k ? "border-zinc-900 text-zinc-900" : "border-transparent text-zinc-500 hover:text-zinc-800")}>
            {label}
          </button>
        ))}
      </div>
      {sumTab === "device" && (
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Identity">
          <KV items={[
            ["Device id", <span className="tabular-nums">{d.id}</span>],
            ["Vendor", d.vendor], ["Model", d.model], ["Software", d.swversion],
            ["OLT type", d.olttype], ["Chassis id", d.chassisid && <span className="font-mono text-xs">{d.chassisid}</span>],
            ["Description", d.descr && <span className="text-xs text-zinc-600">{d.descr}</span>],
            ["First seen", fmtTime(d.first)], ["Last seen", fmtTime(d.lastseen)],
            ["Poll interval", d.pollint ? `${d.pollint}s` : null],
          ]} />
        </Card>
        <Card title="Location & topology">
          <KV items={[
            ["Region", d.region], ["Province", d.province], ["Site", d.sitename],
            ["Coordinates", d.latitude != null && d.longitude != null && (
              <a className="text-brand-700 hover:underline" target="_blank" rel="noreferrer"
                href={`https://www.google.com/maps?q=${d.latitude},${d.longitude}`}>{d.latitude.toFixed(5)}, {d.longitude.toFixed(5)} ↗</a>
            )],
            ["Network", d.network], ["Topology", d.topology],
            ["AGN / RN", d.rn], ["AN / PN", d.pn], ["Sub-AN / DN", d.dn],
            ["Ring", d.ringid && <span>{d.ringid}{d.ringtopo && <span className="text-zinc-500"> · {d.ringtopo}</span>}{d.hop && <span className="text-zinc-400"> · hop {d.hop}</span>}</span>],
            ["Uplink 1", uplink(d.uplink_ip1, d.uplink_site1, d.uplink_model1)],
            ["Uplink 2", uplink(d.uplink_ip2, d.uplink_site2, d.uplink_model2)],
            ["A-homing", homing(d.a_homing_id, d.a_homing_site)],
            ["B-homing", homing(d.b_homing_id, d.b_homing_site)],
            ["C-homing", homing(d.c_homing_id, d.c_homing_site)],
          ]} />
        </Card>
        <UptimeCard d={d} />
      </div>
      )}

      {sumTab === "ponports" && isOlt && <PonPortPanel deviceId={d.id} />}
      {sumTab === "fiber" && isOlt && <FiberTab deviceId={d.id} deviceName={d.name} />}

      {sumTab === "interfaces" && (
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Interfaces by oper status" actions={s && <span className="text-xs text-zinc-400">click a slice to filter</span>}>
          {s ? (s.total ? <OperDonut s={s} onSelect={pickOper} /> : <Empty>No interfaces</Empty>) : <div className="h-[200px]" />}
        </Card>
        <Card title="Interfaces by speed">
          {s ? (s.total ? <SpeedBars s={s} /> : <Empty>No interfaces</Empty>) : <div className="h-[200px]" />}
        </Card>
        <Card title="Interface facts">
          {s ? (
            <div className="grid grid-cols-2 gap-3">
              {[
                ["Total", num(s.total), ""],
                ["Not up", num(down), down ? "text-rose-600" : ""],
                ["Admin down", num(s.by_admin.down ?? 0), ""],
                ["With LLDP neighbor", num(s.with_neighbor), ""],
              ].map(([k, v, c]) => (
                <div key={k} className="rounded-lg bg-zinc-50 p-3">
                  <div className="text-xs text-zinc-500">{k}</div>
                  <div className={cx("text-xl font-semibold tabular-nums text-zinc-900", c)}>{v}</div>
                </div>
              ))}
              <div className="col-span-2 text-xs text-zinc-500">
                Top types: {Object.entries(s.by_type).slice(0, 4).map(([k, v]) => `${k} (${v})`).join(", ") || "—"}
              </div>
            </div>
          ) : <div className="h-[200px]" />}
        </Card>
      </div>
      )}

      {/* Interface tables; hidden on the PON port tab, which has its own table. */}
      {sumTab !== "ponports" && sumTab !== "fiber" && (
      <Card bodyClass="p-0">
        <div className="flex gap-1 border-b border-zinc-100 px-3 pt-2">
          {([
            ["interfaces", `Interfaces${s ? ` (${num(s.total)})` : ""}`],
            ["changes", "Recent changes"],
            ["neighbors", `LLDP neighbors${s ? ` (${num(s.with_neighbor)})` : ""}`],
          ] as [Tab, string][]).map(([k, label]) => (
            <button key={k} type="button" onClick={() => setTab(k)}
              className={cx("-mb-px border-b-2 px-3 py-2 text-sm font-medium", tab === k ? "border-brand-600 text-brand-800" : "border-transparent text-zinc-500 hover:text-zinc-800")}>
              {label}
            </button>
          ))}
        </div>
        <div className="p-4">
          {tab === "interfaces" && <InterfaceTable deviceId={d.id} oper={oper} onOper={setOper} />}
          {tab === "changes" && (changes.error ? <ErrorBox error={changes.error} /> : (
            <>
              <p className="mb-2 text-xs text-zinc-500">Each row is a state interval: the interface had this oper status / speed from “From” until “Last seen”.</p>
              <DataTable columns={CHANGE_COLS} rows={changes.data?.items ?? []} rowKey={(r) => `${r.id}-${r.rev}`} dense
                loading={changes.isLoading} empty="No interface changes recorded for this device" />
              {changes.data?.truncated && <p className="pt-2 text-xs text-zinc-400">Showing the latest 200 changes.</p>}
            </>
          ))}
          {tab === "neighbors" && (nbrs.error ? <ErrorBox error={nbrs.error} /> : (
            <DataTable columns={NBR_COLS} rows={nbrs.data?.items ?? []} rowKey={(r) => `${r.ifname}-${r.dstname}-${r.dstport}`} dense
              loading={nbrs.isLoading} empty="No LLDP neighbors" />
          ))}
        </div>
      </Card>
      )}
    </div>
  );
}
