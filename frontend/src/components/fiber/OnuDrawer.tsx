import { lazy, Suspense, useEffect } from "react";
import { Link } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { fiberApi } from "../../api/fiber";
import { Button, cx, ErrorBox, Spinner } from "../ui";
import { CapNotes, LikelyLocation, OnuFacts, onuPageUrl, SENSITIVITY, useAskAiOnu, WhyScore } from "./OnuSections";
import { db, runLabel, ScoreChip, scoreTone } from "./score";

const RxHistoryChart = lazy(() => import("./FiberCharts").then((m) => ({ default: m.RxHistoryChart })));

/** Quick preview of one ONU's score; the full page (OnuPage) adds siblings, a larger chart and the run picker. */
export function OnuDrawer({ deviceId, deviceName, ponport, ontid, date, onClose }: {
  deviceId: number; deviceName: string | null; ponport: string; ontid: string; date?: string; onClose: () => void;
}) {
  const q = useQuery({ queryKey: ["fiberOnu", deviceId, ponport, ontid, date], queryFn: () => fiberApi.onu(deviceId, ponport, ontid, date) });
  const ask = useAskAiOnu(deviceId, deviceName);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const d = q.data;
  const o = d?.onu;

  return (
    <div className="fixed inset-0 top-14 z-30 flex justify-end bg-black/20" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <aside role="dialog" aria-label={`ONU ${ponport}:${ontid}`} className="flex h-full w-full flex-col border-l border-zinc-200 bg-white shadow-xl sm:w-[520px]">
        <header className="flex items-start justify-between gap-3 border-b border-zinc-100 px-5 py-3">
          <div className="min-w-0">
            <div className="text-xs text-zinc-500">ONU fiber score{d && ` · ${runLabel(d.date, d.window)}`}</div>
            <h2 className="truncate font-mono text-sm font-semibold text-zinc-900">{deviceName} · {ponport} : {ontid}</h2>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <Link to={onuPageUrl(deviceId, ponport, ontid, date)}
              className="rounded-md px-2 py-1 text-xs font-medium text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900">Open full page ↗</Link>
            <button type="button" onClick={onClose} aria-label="Close" className="rounded-md p-1 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900">✕</button>
          </div>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {q.isLoading && <div className="flex justify-center p-10"><Spinner className="size-6" /></div>}
          {q.error && <ErrorBox error={q.error} />}
          {o && d && (
            <div className="flex flex-col gap-5">
              <div className="flex items-center gap-4">
                <ScoreChip score={o.score} conf={o.conf} size="lg" />
                <div>
                  <div className="text-lg font-semibold text-zinc-900">{o.score != null ? `${scoreTone(o.score).label}` : "Not scored"} <span className="text-sm font-normal text-zinc-400">/ 10</span></div>
                  <div className={cx("text-xs", (o.conf ?? 0) < 0.5 ? "text-amber-600" : "text-zinc-500")}>
                    confidence {o.conf?.toFixed(2) ?? "—"} · {o.days_obs ?? 0} of {d.window} days observed
                  </div>
                </div>
              </div>
              <CapNotes o={o} className="-mt-2" />
              <WhyScore o={o} />
              <section>
                <h3 className="mb-1 text-xs font-medium text-zinc-500">Rx: measured vs expected</h3>
                {d.history.length ? (
                  <Suspense fallback={<div className="h-[200px]" />}>
                    <RxHistoryChart history={d.history} expected={o.expected_rx} mae={d.model_mae_db} sensitivity={SENSITIVITY} />
                  </Suspense>
                ) : <p className="text-xs text-zinc-400">No daily history in the lake for this ONU.</p>}
                <p className="text-[11px] text-zinc-400">Green band = expected Rx ± model error ({db(d.model_mae_db, 1)} dB). Red dots = days with BIP errors.</p>
              </section>
              <LikelyLocation o={o} />
              <section><OnuFacts o={o} /></section>
            </div>
          )}
        </div>
        {o && (
          <footer className="flex justify-end border-t border-zinc-100 px-5 py-3">
            <Button variant="primary" onClick={() => ask(d)}>✦ Ask AI about this ONU</Button>
          </footer>
        )}
      </aside>
    </div>
  );
}
