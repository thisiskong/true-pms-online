import ReactEChartsCore from "echarts-for-react/lib/core";
import * as echarts from "echarts/core";
import { BarChart, LineChart } from "echarts/charts";
import { GridComponent, MarkAreaComponent, MarkLineComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { CHART_THEME } from "../../lib/echartsTheme";
import type { OnuHistoryDay } from "../../api/fiber";
import { HW_READINGS, scoreTone } from "./score";

echarts.use([BarChart, LineChart, GridComponent, TooltipComponent, MarkLineComponent, MarkAreaComponent, CanvasRenderer]);

const AXIS = { color: "#a1a1aa" };
/** ONU hardware colour (as the "ONU hardware" attribution and the Hardware row). */
const HW_BAD = "#7c3aed";
const SPLIT = { lineStyle: { color: "#f4f4f5" } };

/** ONUs per score 1..10 on a log axis (score 10 holds ~70% and would flatten the rest). */
export function ScoreHistogram({ histogram, onPick }: { histogram: Record<string, number>; onPick?: (score: number) => void }) {
  const scores = Array.from({ length: 10 }, (_, i) => i + 1);
  const total = scores.reduce((a, s) => a + (histogram[s] ?? 0), 0) || 1;
  return (
    <ReactEChartsCore echarts={echarts} theme={CHART_THEME} style={{ height: 220 }} notMerge
      onEvents={onPick ? { click: (p: { name: string }) => onPick(Number(p.name)) } : undefined}
      option={{
        animation: false,
        tooltip: {
          trigger: "axis", axisPointer: { type: "shadow" },
          formatter: (ps: { name: string; value: number }[]) => {
            const p = ps[0];
            return `Score ${p.name} · ${scoreTone(Number(p.name)).label}<br/><b>${p.value.toLocaleString()}</b> ONUs (${((p.value / total) * 100).toFixed(2)}%)`;
          },
        },
        grid: { left: 8, right: 8, top: 12, bottom: 4, containLabel: true },
        xAxis: { type: "category", data: scores.map(String), axisTick: { show: false }, axisLine: { lineStyle: { color: "#e4e4e7" } }, axisLabel: { color: "#52525b" } },
        yAxis: { type: "log", logBase: 10, min: 1000, splitLine: SPLIT, axisLabel: { ...AXIS, formatter: (v: number) => (v >= 1e6 ? `${v / 1e6}M` : `${v / 1e3}K`) } },
        series: [{
          type: "bar", barMaxWidth: 34,
          data: scores.map((s) => ({ value: histogram[s] ?? 0, itemStyle: { color: scoreTone(s).hex, borderRadius: [3, 3, 0, 0] } })),
        }],
      }} />
  );
}

const utc = (iso: string) => new Date(`${iso}T00:00:00Z`);
const fmt = (iso: string, o: Intl.DateTimeFormatOptions) => utc(iso).toLocaleDateString("en-GB", { timeZone: "UTC", ...o });
/** "16 Nov" */
const dayLabel = (iso: string) => fmt(iso, { day: "numeric", month: "short" });
/** "Mon 16 Nov 2026" */
const dayFull = (iso: string) => fmt(iso, { weekday: "short", day: "numeric", month: "short", year: "numeric" });
const isMonday = (iso: string) => utc(iso).getUTCDay() === 1;

const PLOT_LEFT = 52;
const PLOT_RIGHT = 12;

/** Day category axis: every day up to 10 days, beyond that only Mondays (start of each Monday-Sunday scoring week),
 *  with faint week separators. `labels: false` keeps the separators but hides the dates (upper stacked rows). */
function dayAxis(dates: string[], labels: boolean, gridIndex = 0) {
  const monday = (i: number) => isMonday(dates[i]);
  return {
    type: "category" as const, gridIndex, data: dates, axisLine: { lineStyle: { color: "#e4e4e7" } },
    axisTick: { show: labels && dates.length > 10, interval: monday, alignWithLabel: true, lineStyle: { color: "#d4d4d8" } },
    axisLabel: { ...AXIS, show: labels, interval: (i: number) => dates.length <= 10 || monday(i), formatter: dayLabel, hideOverlap: true },
    splitLine: { show: dates.length > 7, interval: monday, lineStyle: { color: "#e4e4e7", type: "dashed" as const } },
  };
}

/** Daily measured Rx against the model's expected Rx (± MAE band) and the sensitivity line. */
export function RxHistoryChart({ history, expected, mae, sensitivity = -28, height = 200 }: {
  history: OnuHistoryDay[]; expected: number | null; mae: number | null; sensitivity?: number; height?: number;
}) {
  const rx = history.map((h) => h.rx).filter((v): v is number => v != null);
  const lo0 = Math.min(sensitivity, ...rx, expected != null ? expected - (mae ?? 0) : 0) - 1.5;
  const hi0 = Math.max(...rx, expected != null ? expected + (mae ?? 0) : -40, sensitivity) + 1.5;
  // Snap the range to the tick step so the first and last labels are ticks too (otherwise they overlap their neighbours).
  const step = hi0 - lo0 <= 18 ? 3 : 5;
  const lo = Math.floor(lo0 / step) * step, hi = Math.ceil(hi0 / step) * step;
  const dates = history.map((h) => h.date);
  const markArea = expected != null && mae != null
    ? { silent: true, itemStyle: { color: "rgba(16,185,129,0.10)" }, data: [[{ yAxis: expected - mae }, { yAxis: expected + mae }]] }
    : undefined;
  const lines = [
    { yAxis: sensitivity, lineStyle: { color: "#dc2626", type: "dotted" }, label: { formatter: `sensitivity ${sensitivity}`, color: "#dc2626", position: "insideEndTop" } },
    ...(expected != null ? [{ yAxis: Number(expected.toFixed(2)), lineStyle: { color: "#059669", type: "dashed" }, label: { formatter: `expected ${expected.toFixed(1)}`, color: "#059669", position: "insideEndBottom" } }] : []),
  ];
  return (
    <ReactEChartsCore echarts={echarts} theme={CHART_THEME} style={{ height }} notMerge
      option={{
        animation: false,
        tooltip: {
          trigger: "axis",
          formatter: (ps: { axisValue: string; dataIndex: number }[]) => {
            const h = history[ps[0].dataIndex];
            return `${dayFull(h.date)}<br/>Rx <b>${h.rx ?? "—"}</b> dBm<br/>BIP in ${h.bip_in ?? "n/a"} · lost carrier ${h.lostcarrier ?? "n/a"}` +
              (h.hw_flag ? `<br/><span style="color:${HW_BAD}">ONU hardware out of range</span>` : "");
          },
        },
        // Fixed plot edges (not containLabel) so the days line up with HwHistoryChart below it.
        grid: { left: PLOT_LEFT, right: PLOT_RIGHT, top: 24, bottom: 24 },
        xAxis: dayAxis(dates, true),
        yAxis: { type: "value", min: lo, max: hi, interval: step, splitLine: SPLIT, axisLabel: { ...AXIS, formatter: "{value}" }, name: "dBm", nameTextStyle: AXIS },
        series: [{
          type: "line", data: history.map((h) => h.rx), connectNulls: false, symbol: "circle", symbolSize: 7,
          lineStyle: { color: "#18181b", width: 2 },
          itemStyle: { color: (p: { dataIndex: number }) => ((history[p.dataIndex].bip_in ?? 0) > 0 ? "#dc2626" : "#18181b") },
          markLine: { silent: true, symbol: "none", data: lines },
          markArea,
        }],
      }} />
  );
}


type HwKey = (typeof HW_READINGS)[number]["key"];
const HW_ROW_H = 46;
const HW_GAP = 26;     // room for each row's name above its plot
const HW_MIN_SPAN: Record<HwKey, number> = { tx: 1, voltage: 0.1, temp: 5, current: 5 };
const hwOut = (key: HwKey, v: number | null | undefined) => {
  const h = HW_READINGS.find((x) => x.key === key)!;
  return v != null && (v < h.ok[0] || v > h.ok[1]);
};

/** Daily ONU hardware readings (Tx, voltage, temperature, bias), one row each, aligned day for day with
 *  RxHistoryChart above it. Shaded band = normal range (ranges.yaml hw_ok); purple points are out of range. */
export function HwHistoryChart({ history }: { history: OnuHistoryDay[] }) {
  const dates = history.map((h) => h.date);
  const n = HW_READINGS.length;
  const top = (i: number) => 22 + i * (HW_ROW_H + HW_GAP);
  const height = top(n - 1) + HW_ROW_H + 24;

  const rows = HW_READINGS.map((r, i) => {
    const vals = history.map((h) => h[r.key] ?? null);
    const xs = vals.filter((v): v is number => v != null);
    // Range = the data, plus any bound the data crosses (so the violated threshold is on screen), padded.
    let lo = xs.length ? Math.min(...xs) : r.ok[0], hi = xs.length ? Math.max(...xs) : r.ok[1];
    if (xs.some((v) => v < r.ok[0])) hi = Math.max(hi, r.ok[0]);
    if (xs.some((v) => v > r.ok[1])) lo = Math.min(lo, r.ok[1]);
    const span = Math.max(hi - lo, HW_MIN_SPAN[r.key]);
    const mid = (lo + hi) / 2;
    lo = mid - span * 0.6; hi = mid + span * 0.6;
    const f = 10 ** r.digits;
    return {
      grid: { left: PLOT_LEFT, right: PLOT_RIGHT, top: top(i), height: HW_ROW_H },
      xAxis: dayAxis(dates, i === n - 1, i),
      yAxis: {
        type: "value" as const, gridIndex: i, min: Math.floor(lo * f) / f, max: Math.ceil(hi * f) / f, splitNumber: 2,
        splitLine: SPLIT, axisLabel: { ...AXIS, showMinLabel: false, showMaxLabel: false, formatter: (v: number) => v.toFixed(r.digits) },
        name: `${r.label} · ${r.unit}`, nameLocation: "end" as const, nameGap: 6,
        nameTextStyle: { color: "#52525b", align: "left" as const, padding: [0, 0, 0, -PLOT_LEFT + 8] },
      },
      series: {
        type: "line" as const, xAxisIndex: i, yAxisIndex: i, data: vals, connectNulls: false, symbol: "circle", symbolSize: 5,
        lineStyle: { color: "#71717a", width: 1.5 },
        itemStyle: { color: (p: { dataIndex: number }) => (hwOut(r.key, vals[p.dataIndex]) ? HW_BAD : "#71717a") },
        markArea: {
          silent: true, itemStyle: { color: "rgba(16,185,129,0.08)" },
          data: [[{ yAxis: Math.max(r.ok[0], lo) }, { yAxis: Math.min(r.ok[1], hi) }]],
        },
      },
    };
  });

  return (
    <ReactEChartsCore echarts={echarts} theme={CHART_THEME} style={{ height }} notMerge
      option={{
        animation: false,
        axisPointer: { link: [{ xAxisIndex: "all" }] },
        tooltip: {
          trigger: "axis",
          formatter: (ps: { dataIndex: number }[]) => {
            const h = history[ps[0].dataIndex];
            const lines = HW_READINGS.map((r) => {
              const v = h[r.key];
              const txt = v == null ? "—" : `${v.toFixed(r.digits)} ${r.unit}`;
              return hwOut(r.key, v)
                ? `<span style="color:${HW_BAD}">${r.label} <b>${txt}</b> (normal ${r.ok[0]}–${r.ok[1]})</span>`
                : `${r.label} <b>${txt}</b>`;
            });
            return `${dayFull(h.date)}<br/>${lines.join("<br/>")}`;
          },
        },
        grid: rows.map((r) => r.grid),
        xAxis: rows.map((r) => r.xAxis),
        yAxis: rows.map((r) => r.yAxis),
        series: rows.map((r) => r.series),
      }} />
  );
}
