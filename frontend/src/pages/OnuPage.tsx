// Full page for one ONU's fiber score: /devices/:id/onu?pon=<ponport>&ont=<ontid>[&date=<run>].
import { lazy, Suspense, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { fiberApi, type OnuHistoryDay, type OnuScore, type OnuScoreRow } from "../api/fiber";
import { CapNotes, LikelyLocation, OnuFacts, onuPageUrl, SENSITIVITY, useAskAiOnu, WhyScore } from "../components/fiber/OnuSections";
import { AttributionBadge, BadShare, BAD_SCORE, db, Db, FiberHelpLink, runLabel, ScoreChip, scoreTone } from "../components/fiber/score";
import { Button, Card, cx, Empty, ErrorBox, inputCls, PAGE_CLS, Spinner } from "../components/ui";

const RxHistoryChart = lazy(() => import("../components/fiber/FiberCharts").then((m) => ({ default: m.RxHistoryChart })));

const RANGES = [["7d", 7], ["14d", 14], ["30d", 30], ["All", 0]] as const;

function RxSection({ history, expected, mae }: { history: OnuHistoryDay[]; expected: number | null; mae: number | null }) {
  const [range, setRange] = useState<number>(30);
  const shown = range ? history.slice(-range) : history;
  return (
    <Card title="Rx: measured vs expected" actions={
      <div className="flex rounded-md bg-zinc-100 p-0.5 text-xs" role="group" aria-label="Range">
        {RANGES.map(([label, n]) => (
          <button key={label} type="button" onClick={() => setRange(n)} aria-pressed={range === n}
            className={cx("rounded px-2 py-0.5 font-medium", range === n ? "bg-white text-zinc-900 shadow-sm" : "text-zinc-500 hover:text-zinc-800")}>
            {label}
          </button>
        ))}
      </div>}>
      {history.length ? (
        <Suspense fallback={<div className="h-[320px]" />}>
          <RxHistoryChart history={shown} expected={expected} mae={mae} sensitivity={SENSITIVITY} height={320} />
        </Suspense>
      ) : <Empty>No daily history in the lake for this ONU.</Empty>}
      <p className="mt-1 text-[11px] text-zinc-400">Green band = expected Rx ± model error ({db(mae, 1)} dB). Red dots = days with BIP errors. Hover a day for its readings.</p>
      {history.length > 0 && (
        <details className="mt-3 text-sm">
          <summary className="cursor-pointer text-xs font-medium text-zinc-600 hover:text-zinc-900">Daily readings ({shown.length} days)</summary>
          <div className="mt-2 max-h-80 overflow-auto">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-white text-left text-zinc-500">
                <tr><th className="px-2 py-1.5 font-medium">Date</th><th className="px-2 py-1.5 font-medium">Rx dBm</th><th className="px-2 py-1.5 font-medium">BIP in</th><th className="px-2 py-1.5 font-medium">Lost carrier</th><th className="px-2 py-1.5 font-medium">HW flag</th></tr>
              </thead>
              <tbody className="divide-y divide-zinc-100 tabular-nums">
                {[...shown].reverse().map((h) => (
                  <tr key={h.date}>
                    <td className="px-2 py-1">{h.date}</td>
                    <td className={cx("px-2 py-1", h.rx != null && h.rx < SENSITIVITY && "font-semibold text-red-600")}>{db(h.rx, 1)}</td>
                    <td className={cx("px-2 py-1", (h.bip_in ?? 0) > 0 && "text-red-600")}>{h.bip_in?.toLocaleString() ?? "n/a"}</td>
                    <td className="px-2 py-1">{h.lostcarrier ?? "n/a"}</td>
                    <td className="px-2 py-1">{h.hw_flag ? <span className="text-violet-700">yes</span> : "–"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </Card>
  );
}

function Siblings({ deviceId, o, date }: { deviceId: number; o: OnuScore; date: string }) {
  const params = { date, ponport: o.ponport, l2name: o.l2name ?? undefined, sort: "score", order: "asc", size: 500 };
  const sib = useQuery({ queryKey: ["fiberOnus", deviceId, params], queryFn: ({ signal }) => fiberApi.onus(deviceId, params, signal) });
  const tree = useQuery({ queryKey: ["fiberTree", deviceId, date], queryFn: () => fiberApi.tree(deviceId, date), staleTime: 300_000 });
  const port = tree.data?.items.find((p) => p.ponport === o.ponport);
  const rows = sib.data?.items ?? [];
  const nBad = rows.filter((r) => r.score != null && r.score <= BAD_SCORE).length;
  const isMe = (r: OnuScoreRow) => r.ponport === o.ponport && r.ontid === o.ontid;

  return (
    <Card title={o.l2name ? `Siblings on ${o.l2name}` : `ONUs on PON ${o.ponport} (no L2 in inventory)`}
      actions={<span className="text-xs text-zinc-500">
        {sib.data && <>{rows.length} ONUs, {nBad} bad · </>}
        this ONU vs L2 median <Db v={o.peer_delta_l2} signed /> · vs PON median <Db v={o.peer_delta_l1} signed />
      </span>} bodyClass="px-2 pb-4 pt-1">
      {sib.error ? <ErrorBox error={sib.error} /> : sib.isLoading ? <div className="flex justify-center p-6"><Spinner /></div> : (
        <div className="max-h-[480px] overflow-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-white text-left text-xs text-zinc-500">
              <tr>
                {["ONT", "Score", "Rx", "Expected", "Excess", "Peer Δ L2", "BIP days", "Likely location"].map((h) => <th key={h} className="whitespace-nowrap px-3 py-2 font-medium">{h}</th>)}
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100">
              {rows.map((r) => (
                <tr key={`${r.ponport}:${r.ontid}`} className={cx(isMe(r) ? "bg-orange-50" : "hover:bg-zinc-50")}>
                  <td className="whitespace-nowrap px-3 py-1.5">
                    {isMe(r)
                      ? <><b className="tabular-nums">{r.ontid}</b> <span className="text-[11px] text-orange-700">this ONU</span></>
                      : <Link to={onuPageUrl(deviceId, r.ponport, r.ontid, date)} className="font-medium tabular-nums text-zinc-900 underline-offset-2 hover:underline">{r.ontid}</Link>}
                  </td>
                  <td className="px-3 py-1.5"><ScoreChip score={r.score} conf={r.conf} /></td>
                  <td className={cx("px-3 py-1.5 tabular-nums", r.rx_med != null && r.rx_med < SENSITIVITY && "font-semibold text-red-600")}>{db(r.rx_med, 1)}</td>
                  <td className="px-3 py-1.5 tabular-nums text-zinc-500">{db(r.expected_rx, 1)}</td>
                  <td className="px-3 py-1.5"><Db v={r.excess_loss} unit={false} /></td>
                  <td className="px-3 py-1.5"><Db v={r.peer_delta_l2} signed unit={false} /></td>
                  <td className="px-3 py-1.5 tabular-nums">{r.bip_days == null ? <span className="text-zinc-300" title="vendor reports no BIP counters">n/a</span> : <span className={cx(r.bip_days > 0 && "text-red-600")}>{r.bip_days}</span>}</td>
                  <td className="px-3 py-1.5"><AttributionBadge a={r.attributed_to} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          {!rows.length && <Empty>No scored siblings</Empty>}
        </div>
      )}
      {port && port.l2.length > 1 && (
        <div className="mt-4 px-3">
          <h3 className="mb-2 text-xs font-medium text-zinc-500">Other L2s on PON {port.ponport}{port.l1name && ` (${port.l1name})`}</h3>
          <div className="flex flex-wrap gap-2">
            {port.l2.map((l) => {
              const me = l.l2name === o.l2name;
              return (
                <Link key={l.l2name ?? "none"} to={`/devices/${deviceId}?tab=fiber&date=${date}${l.l2name ? `&l2=${encodeURIComponent(l.l2name)}` : ""}`}
                  title={l.med_rx != null ? `median Rx ${l.med_rx} dBm · excess ${l.med_excess_loss} dB` : undefined}
                  className={cx("flex min-w-[150px] flex-col gap-1 rounded-lg border px-3 py-2 text-xs hover:border-zinc-400",
                    me ? "border-orange-200 bg-orange-50" : "border-zinc-200 bg-white", l.suspect && "ring-1 ring-inset ring-red-200")}>
                  <span className="font-mono font-semibold text-zinc-900">{l.l2name ?? "no L2"}{me && <span className="font-sans font-normal text-orange-700"> · this</span>}{l.suspect && <span className="font-sans text-red-700"> ⚠</span>}</span>
                  <BadShare bad={l.n_bad} total={l.n_onu} />
                  <span className="text-zinc-500">median Rx {db(l.med_rx, 1)}</span>
                </Link>
              );
            })}
          </div>
        </div>
      )}
    </Card>
  );
}

export function OnuPage() {
  const deviceId = Number(useParams().id);
  const [sp, setSp] = useSearchParams();
  const ponport = sp.get("pon") ?? "";
  const ontid = sp.get("ont") ?? "";
  const date = sp.get("date") ?? undefined;
  const valid = Number.isFinite(deviceId) && !!ponport && !!ontid;

  const q = useQuery({ queryKey: ["fiberOnu", deviceId, ponport, ontid, date], queryFn: () => fiberApi.onu(deviceId, ponport, ontid, date), enabled: valid });
  const runs = useQuery({ queryKey: ["fiberRuns"], queryFn: fiberApi.runs, staleTime: 300_000 });
  const d = q.data;
  const o = d?.onu;
  const ask = useAskAiOnu(deviceId, o?.device ?? null);
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    await navigator.clipboard.writeText(window.location.href);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  const pickRun = (v: string) => {
    const next = new URLSearchParams(sp);
    next.set("date", v);
    setSp(next);
  };

  return (
    <div className={PAGE_CLS}>
      <nav aria-label="Breadcrumb" className="flex flex-wrap items-center gap-1.5 text-sm text-zinc-500">
        <Link to="/devices" className="hover:text-zinc-900">Devices</Link><span aria-hidden>›</span>
        <Link to={`/devices/${deviceId}`} className="font-mono hover:text-zinc-900">{o?.device ?? deviceId}</Link><span aria-hidden>›</span>
        <Link to={`/devices/${deviceId}?tab=fiber${date ? `&date=${date}` : ""}`} className="hover:text-zinc-900">Fiber health</Link><span aria-hidden>›</span>
        <span className="font-mono text-zinc-900">ONU {ponport} : {ontid}</span>
      </nav>

      {!valid && <Card><Empty>This link needs pon and ont, e.g. /devices/{"{id}"}/onu?pon=0/2/5&amp;ont=12</Empty></Card>}
      {q.isLoading && <div className="flex justify-center p-10"><Spinner className="size-6" /></div>}
      {q.error && <ErrorBox error={q.error} />}

      {o && d && (
        <>
          <section className="flex flex-wrap items-center gap-5 rounded-xl border border-zinc-200 bg-white px-6 py-5 shadow-sm">
            <ScoreChip score={o.score} conf={o.conf} size="lg" />
            <div className="flex min-w-0 flex-[1_1_280px] flex-col gap-1">
              <h1 className="truncate font-mono text-lg font-semibold text-zinc-900">{o.device} · {o.ponport} : {o.ontid}</h1>
              <div className="text-sm">
                <b className="text-zinc-900">{o.score != null ? scoreTone(o.score).label : "Not scored"}</b>
                <span className={cx((o.conf ?? 0) < 0.5 ? "text-amber-600" : "text-zinc-500")}> / 10 · confidence {o.conf?.toFixed(2) ?? "—"} · {o.days_obs ?? 0} of {d.window} days observed</span>
              </div>
              <div className="mt-1 flex flex-wrap gap-2">
                <CapNotes o={o} className="py-1" />
                {o.attributed_to && <span className="rounded-md bg-zinc-50 px-2 py-1 ring-1 ring-inset ring-zinc-200"><AttributionBadge a={o.attributed_to} /></span>}
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <label className="flex items-center gap-2 text-xs text-zinc-500">Run
                <select className={cx(inputCls, "w-auto")} value={d.date} onChange={(e) => pickRun(e.target.value)}>
                  {(runs.data?.length ? runs.data : [{ date: d.date, window: d.window }]).map((r, i) => <option key={r.date} value={r.date}>{runLabel(r.date, r.window)}{i === 0 && runs.data?.length ? " (latest)" : ""}</option>)}
                </select>
              </label>
              <Button onClick={copy} title="Copy a link to this page">{copied ? "Copied ✓" : "Copy link"}</Button>
              <Button variant="primary" onClick={() => ask(d)}>✦ Ask AI about this ONU</Button>
            </div>
          </section>

          <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_420px]">
            <div className="flex min-w-0 flex-col gap-4">
              <RxSection history={d.history} expected={o.expected_rx} mae={d.model_mae_db} />
              <Siblings deviceId={deviceId} o={o} date={d.date} />
            </div>
            <div className="flex flex-col gap-4">
              <Card><WhyScore o={o} /></Card>
              <LikelyLocation o={o} />
              <Card title="Path & equipment"><OnuFacts o={o} peers={false} /></Card>
              <FiberHelpLink />
            </div>
          </div>
        </>
      )}
    </div>
  );
}
