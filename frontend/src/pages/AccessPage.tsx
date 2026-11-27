import type { ReactNode } from "react";
import { Link, useParams } from "react-router";
import { AccessSearch } from "../components/AccessSearch";
import { useQuery } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import type { AccessLookup, Ticket } from "../api/types";
import { DataTable, type Column } from "../components/DataTable";
import { AttributionBadge, db, Db, runLabel, ScoreChip } from "../components/fiber/score";
import { Button, Card, Empty, ErrorBox, Spinner } from "../components/ui";
import { useChatCtx } from "../hooks/chatContext";
import { dash, fmtTime, num } from "../lib/format";

const TICKET_COLS: Column<Ticket>[] = [
  { key: "createtime", header: "Created", render: (t) => <span className="whitespace-nowrap tabular-nums">{fmtTime(t.createtime)}</span> },
  { key: "completetime", header: "Completed", render: (t) => <span className="whitespace-nowrap tabular-nums text-zinc-500">{fmtTime(t.completetime)}</span> },
  { key: "faulttype", header: "Fault type", render: (t) => dash(t.faulttype) },
  { key: "subcategory", header: "Subcategory", render: (t) => dash(t.subcategory) },
  { key: "faultcause", header: "Cause", render: (t) => <span className="text-zinc-600">{dash(t.faultcause)}</span> },
  { key: "faultstatus", header: "Status", render: (t) => dash(t.faultstatus) },
  { key: "networkdisp", header: "Network dispatch", render: (t) => <span className="font-mono text-xs">{dash(t.networkdisp)}</span> },
  { key: "ticketid", header: "Ticket", render: (t) => <span className="font-mono text-xs text-zinc-500">{t.ticketid}</span> },
];

function Rows({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[140px_1fr] gap-x-4 gap-y-2 text-sm">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-zinc-500">{k}</dt>
          <dd className="min-w-0 break-words text-zinc-900">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

const meters = (m: number | null) => (m == null ? "—" : `${num(Math.round(m))} m`);
const Dbm = ({ v }: { v: number | null }) =>
  v == null ? <span className="text-zinc-300">—</span> : <span className="tabular-nums text-zinc-900">{db(v, 1)}<span className="text-zinc-400"> dBm</span></span>;
const ratio = (r: number | null) => (r == null ? "" : ` · 1:${r}`);

function OdnPath({ r }: { r: AccessLookup }) {
  const o = r.onu;
  const hops: { label: string; name: ReactNode; sub?: string }[] = [
    { label: "OLT", name: r.device.name, sub: `PON ${o.ponport}` },
    { label: "L1 splitter", name: dash(o.l1name), sub: `${meters(o.l1len)}${ratio(o.l1ratio)}` },
    { label: "L2 splitter", name: dash(o.l2name), sub: `${meters(o.l2len)}${ratio(o.l2ratio)}` },
    { label: "ONU", name: `ONT ${o.ontid}`, sub: o.dropwire != null ? `drop ${meters(o.dropwire)}` : undefined },
  ];
  return (
    <div className="flex flex-wrap items-stretch gap-1.5">
      {hops.map((h, i) => (
        <div key={h.label} className="flex items-center gap-1.5">
          {i > 0 && <span className="text-zinc-300" aria-hidden>→</span>}
          <div className="rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2">
            <div className="text-[11px] font-medium uppercase tracking-wide text-zinc-400">{h.label}</div>
            <div className="font-mono text-xs font-medium text-zinc-900">{h.name}</div>
            {h.sub && <div className="text-xs tabular-nums text-zinc-500">{h.sub}</div>}
          </div>
        </div>
      ))}
    </div>
  );
}

export function AccessPage() {
  const { accessid = "" } = useParams();
  const chat = useChatCtx();
  const q = useQuery({ queryKey: ["access", accessid], queryFn: () => api.access(accessid), enabled: !!accessid, retry: false });
  const r = q.data;
  const notFound = q.error instanceof ApiError && (q.error.status === 404 || q.error.status === 422);

  const ask = () => {
    if (!r) return;
    if (r.device.id != null) chat.setDevice({ id: r.device.id, name: r.device.name });
    chat.setDrawerOpen(true);
    chat.send(
      `Investigate access id ${r.accessid} (OLT ${r.device.name}, PON ${r.onu.ponport}, ONT ${r.onu.ontid}). ` +
      "Summarize its fiber score, its L2 siblings and its trouble tickets, and say what the likely problem is.",
    );
  };

  const devLink = r?.device.id != null ? `/devices/${r.device.id}` : null;

  return (
    <div className="mx-auto max-w-6xl space-y-4 p-4 sm:p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold tracking-tight text-zinc-900">Access id lookup</h1>
          <p className="text-sm text-zinc-500">Find a subscriber's ONU, ODN path, fiber score and trouble tickets by circuit number.</p>
        </div>
        <AccessSearch initial={accessid} />
      </div>

      {!accessid && <Card><Empty>Enter an access id to look it up.</Empty></Card>}
      {q.isLoading && <div className="flex justify-center py-12"><Spinner /></div>}
      {notFound && <Card><Empty>{(q.error as Error).message}</Empty></Card>}
      {q.error && !notFound && <ErrorBox error={q.error} />}

      {r && (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <span className="font-mono text-xl font-semibold text-zinc-900">{r.accessid}</span>
            {r.fiber && <ScoreChip score={r.fiber.score} conf={r.fiber.conf} size="lg" />}
            <div className="ml-auto flex gap-2">
              {devLink && <Link to={`${devLink}?tab=ponports`}><Button>Open OLT</Button></Link>}
              <Button variant="primary" onClick={ask}>✦ Ask AI</Button>
            </div>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Subscriber ONU">
              <Rows rows={[
                ["OLT", devLink ? <Link to={devLink} className="font-mono text-brand-700 hover:underline">{r.device.name}</Link> : <span className="font-mono">{r.device.name}</span>],
                ["OLT IP / model", `${dash(r.device.ip)} · ${dash(r.device.vendor)} ${r.device.model ?? ""}`],
                ["PON port", <span className="font-mono">{r.onu.ponport}</span>],
                ["ONT id", <span className="font-mono">{r.onu.ontid}</span>],
                ["ONU serial", <span className="font-mono">{dash(r.onu.devicesn)}</span>],
                ["Optic class", dash(r.onu.moduleclass)],
                ["Location", [r.device.province, r.device.sitename].filter(Boolean).join(" · ") || "—"],
                ["Service since", fmtTime(r.onu.hsidate)],
              ]} />
            </Card>

            <Card title="Fiber score" actions={r.fiber && devLink && (
              <Link to={`${devLink}?tab=fiber&onu=${encodeURIComponent(`${r.onu.ponport}:${r.onu.ontid}`)}`} className="text-xs font-medium text-brand-700 hover:underline">
                Score details →
              </Link>
            )}>
              {!r.fiber ? <p className="py-4 text-sm text-zinc-600">{r.fiber_note ?? "This ONU is not in the latest fiber-score run."}</p> : (
                <Rows rows={[
                  ["Score", <span className="flex items-center gap-2"><ScoreChip score={r.fiber.score} conf={r.fiber.conf} /><span className="text-xs text-zinc-500">run {runLabel(r.fiber.date)} · confidence {r.fiber.conf?.toFixed(2) ?? "—"}</span></span>],
                  ["Likely fault", r.fiber.bad ? <AttributionBadge a={r.fiber.attributed_to} /> : <span className="text-zinc-500">not bad (score &gt; 4)</span>],
                  ["Rx measured", <Dbm v={r.fiber.rx_med} />],
                  ["Rx expected", <Dbm v={r.fiber.expected_rx} />],
                  ["Excess loss", <Db v={r.fiber.excess_loss} signed />],
                  ["vs L2 peers", <Db v={r.fiber.peer_delta_l2} signed />],
                  ["ONU hardware", r.fiber.hw_flag ? <span className="text-amber-700">readings out of range</span> : "ok"],
                ]} />
              )}
            </Card>
          </div>

          <Card title="ODN path">
            <OdnPath r={r} />
            <p className="mt-3 text-xs text-zinc-500">
              Split ratio {r.onu.splitratio != null ? `1:${r.onu.splitratio}` : "—"} · ranging {meters(r.onu.ranging)} · L2 since {fmtTime(r.onu.l2date)}
            </p>
          </Card>

          <Card title={`Trouble tickets${r.tickets.items.length ? ` (${r.tickets.items.length}${r.tickets.truncated ? "+" : ""})` : ""}`}
            actions={<span className="text-xs text-zinc-400">ticket data {dash(r.tickets.data_from)} – {dash(r.tickets.data_to)}</span>}
            bodyClass="px-2 pb-3 pt-1">
            <DataTable columns={TICKET_COLS} rows={r.tickets.items} rowKey={(t) => t.ticketid} dense
              empty={`No tickets for this access id between ${dash(r.tickets.data_from)} and ${dash(r.tickets.data_to)}.`} />
          </Card>
        </>
      )}
    </div>
  );
}
