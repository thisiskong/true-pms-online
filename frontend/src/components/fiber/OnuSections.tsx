// Sections of one ONU's fiber score, shared by the ONU drawer and the full ONU page.
import type { ReactNode } from "react";
import type { OnuDetail, OnuScore } from "../../api/fiber";
import { useChatCtx } from "../../hooks/chatContext";
import { cx } from "../ui";
import { AttributionBadge, db, Db, HW_READINGS, runLabel } from "./score";

// Mirrors ml/fiber/ranges.yaml (score.weights, score.caps, min_days_for_trend).
const WEIGHTS = { power: 0.4, excess: 0.25, error: 0.2, stability: 0.15 };
export const SENSITIVITY = -28;
const MIN_DAYS = 3;

const NO_BIP_VENDORS = ["GCOM", "Raisecom"];

/** Link to the full ONU page. The PON port (e.g. 0/2/5) goes in the query string because it can hold slashes. */
export function onuPageUrl(deviceId: number, ponport: string, ontid: string, date?: string | null): string {
  const p = new URLSearchParams({ pon: ponport, ont: ontid });
  if (date) p.set("date", date);
  return `/devices/${deviceId}/onu?${p}`;
}

function caps(o: OnuScore): string[] {
  const out: string[] = [];
  if (o.rx_med != null && o.rx_med < -30) out.push("Rx below −30 dBm → score fixed at 1");
  else if (o.rx_med != null && o.rx_med < SENSITIVITY) out.push(`Rx below sensitivity (${SENSITIVITY} dBm) → score at most 3`);
  if (o.bip_obs != null && o.bip_obs >= MIN_DAYS && o.bip_days === o.bip_obs) out.push("BIP errors on every observed day → score at most 5");
  return out;
}

export function CapNotes({ o, className }: { o: OnuScore; className?: string }) {
  return <>{caps(o).map((c) => <div key={c} className={cx("rounded-md bg-red-50 px-3 py-1.5 text-xs text-red-700", className)}>Cap applied: {c}</div>)}</>;
}

function SubScore({ label, value, weight, children }: { label: string; value: number | null; weight: number; children: ReactNode }) {
  const missing = value == null;
  return (
    <div className="grid grid-cols-[72px_1fr_92px_40px] items-start gap-2 py-1.5 text-sm">
      <span className="font-medium text-zinc-800">{label}</span>
      <span className="text-xs leading-5 text-zinc-600">{children}</span>
      {missing ? <span className="text-xs text-zinc-400">not available</span> : (
        <span className="flex items-center gap-1.5">
          <span className="h-1.5 w-12 overflow-hidden rounded-full bg-zinc-100">
            <span className={cx("block h-full rounded-full", value >= 0.7 ? "bg-emerald-600" : value >= 0.4 ? "bg-amber-400" : "bg-red-600")} style={{ width: `${value * 100}%` }} />
          </span>
          <span className="tabular-nums text-xs text-zinc-700">{value.toFixed(2)}</span>
        </span>
      )}
      <span className={cx("text-right text-xs tabular-nums", missing ? "text-zinc-300 line-through" : "text-zinc-500")}>{Math.round(weight * 100)}%</span>
    </div>
  );
}

/** The four sub-scores with their effective weights (a missing sub-score's weight is shared out). */
export function WhyScore({ o }: { o: OnuScore }) {
  const noBip = o.s_error == null && NO_BIP_VENDORS.includes(o.vendor ?? "");
  const present = (Object.keys(WEIGHTS) as (keyof typeof WEIGHTS)[]).filter((k) => o[`s_${k}`] != null);
  const wsum = present.reduce((a, k) => a + WEIGHTS[k], 0) || 1;
  const eff = (k: keyof typeof WEIGHTS) => (o[`s_${k}`] != null ? WEIGHTS[k] / wsum : 0);
  return (
    <section>
      <h3 className="mb-1 flex justify-between text-xs font-medium text-zinc-500"><span>Why this score</span><span>sub-score · weight</span></h3>
      <div className="divide-y divide-zinc-100">
        <SubScore label="Power" value={o.s_power} weight={eff("power")}>
          median Rx <b className="text-zinc-900">{db(o.rx_med, 1)} dBm</b>{o.rx_p10 != null && <> (low tail {db(o.rx_p10, 1)})</>}
          {o.overload && <span className="text-red-600"> · overload</span>}
        </SubScore>
        <SubScore label="Excess" value={o.s_excess} weight={eff("excess")}>
          <b className="text-zinc-900">{db(o.excess_loss, 1)} dB</b> {o.excess_loss != null && o.excess_loss >= 0 ? "more" : "less"} loss than expected for this path ({db(o.expected_rx, 1)} dBm expected)
        </SubScore>
        <SubScore label="Errors" value={o.s_error} weight={eff("error")}>
          {o.s_error == null
            ? noBip ? <>{o.vendor} reports no BIP counters; weight redistributed</> : <>no BIP data; weight redistributed</>
            : <>BIP in errors on <b className="text-zinc-900">{o.bip_days ?? 0}/{o.bip_obs ?? 0}</b> days{o.bip_log_mean != null && o.bip_log_mean > 0 && <> · ~{Math.round(10 ** o.bip_log_mean - 1).toLocaleString()}/day</>}</>}
        </SubScore>
        <SubScore label="Stability" value={o.s_stability} weight={eff("stability")}>
          {o.rx_sd == null ? "needs ≥ 3 days" : <>day-to-day sd {db(o.rx_sd, 2)} dB, trend {db(o.rx_slope, 2, true)} dB/day</>}
          {o.lc_days != null && o.lc_days > 0 && <> · lost carrier on {o.lc_days} days</>}
        </SubScore>
      </div>
    </section>
  );
}

function locationText(o: OnuScore): string {
  switch (o.attributed_to) {
    case "l2": return `the L2 splitter ${o.l2name ?? ""} or its distribution fiber — this ONU's L2 group is worse than the other L2s on the PON`;
    case "l1": return `the L1 feeder or the OLT PON optic — the whole PON ${o.ponport} is affected`;
    case "device": return "the OLT or its site — most PONs on this OLT are bad";
    case "onu_hw": return "the ONU itself — its Tx, voltage, temperature or bias current is out of range";
    case "drop": return "the drop cable, a connector or the ONU — its siblings on the same L2 are healthy";
    default: return "";
  }
}

export function LikelyLocation({ o }: { o: OnuScore }) {
  if (!o.attributed_to) return null;
  return (
    <section className="rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2">
      <div className="text-xs text-zinc-500">Likely location</div>
      <div className="mt-0.5"><AttributionBadge a={o.attributed_to} /></div>
      <p className="mt-1 text-xs text-zinc-600">Most likely {locationText(o)}.</p>
    </section>
  );
}

function Row({ k, children }: { k: string; children: ReactNode }) {
  return <div className="contents"><dt className="text-zinc-500">{k}</dt><dd className="text-zinc-800">{children}</dd></div>;
}

/** Peers, topology, path, equipment, hardware readings and data-quality flags. */
export function OnuFacts({ o, peers = true }: { o: OnuScore; peers?: boolean }) {
  return (
    <dl className="grid grid-cols-[110px_1fr] gap-x-3 gap-y-1 text-sm">
      {peers && <>
        <Row k="Peers (L2)"><Db v={o.peer_delta_l2} signed /> <span className="text-xs text-zinc-400">vs median of {o.peer_n_l2 ?? "?"} ONUs on {o.l2name}</span></Row>
        <Row k="Peers (L1)"><Db v={o.peer_delta_l1} signed /> <span className="text-xs text-zinc-400">vs median of the PON</span></Row>
      </>}
      <Row k="Topology"><span className="font-mono text-xs">{o.l1name ?? "—"} → {o.l2name ?? "—"}</span></Row>
      <Row k="Path">{o.len_km != null ? `${o.len_km.toFixed(2)} km` : "—"} · split 1:{o.splitratio ?? "?"} ({o.l1ratio ?? "?"}×{o.l2ratio ?? "?"}){o.ranging != null && <span className="text-zinc-400"> · ranging {(o.ranging / 1000).toFixed(2)} km</span>}</Row>
      <Row k="Equipment">{o.vendor ?? "—"} {o.model && <span className="text-zinc-500">· {o.model}</span>} <span className="text-zinc-500">· class {o.moduleclass ?? "—"}</span></Row>
      {o.tx_med !== undefined && (
        <Row k="Hardware">
          <span className="flex flex-wrap gap-x-3 gap-y-0.5">
            {HW_READINGS.map((h) => {
              const v = o[`${h.key}_med`], days = o[`hw_${h.key}_days`] ?? 0;
              return (
                <span key={h.key} title={`normal ${h.ok[0]} to ${h.ok[1]} ${h.unit}${days ? ` · out of range on ${days} day(s)` : ""}`}
                  className={cx("tabular-nums", days ? "font-semibold text-violet-700" : "text-zinc-700")}>
                  <span className="font-normal text-zinc-400">{h.label} </span>{v == null ? "—" : v.toFixed(h.digits)}<span className="font-normal text-zinc-400"> {h.unit}</span>
                  {days > 0 && <span className="font-normal"> ({days}d)</span>}
                </span>
              );
            })}
          </span>
        </Row>
      )}
      <Row k="Flags">
        {[o.hw_flag && "ONU hardware", o.dq_no_odn && "no ODN row", o.dq_topo_mismatch && "topology mismatch",
          o.dq_l2_multi_device && "L2 on several OLTs", o.range_mismatch && "ranging ≠ inventory length"].filter(Boolean).join(" · ") || <span className="text-zinc-400">none</span>}
      </Row>
    </dl>
  );
}

/** Opens the chat drawer with a prompt about this ONU. */
export function useAskAiOnu(deviceId: number, deviceName: string | null) {
  const chat = useChatCtx();
  return (d: OnuDetail | undefined) => {
    const o = d?.onu;
    if (!o || !d) return;
    chat.setDevice({ id: deviceId, name: deviceName });
    chat.setDrawerOpen(true);
    chat.send(
      `Explain the fiber score of ONU ${o.device} (device_id ${deviceId}) PON ${o.ponport} ONT ${o.ontid}, run ${d.date} (${runLabel(d.date, d.window)}) ` +
      `(score ${o.score}/10). Compare it with its L2 siblings, then say the likely cause and what the field team should check first.`,
      deviceId,
    );
  };
}
