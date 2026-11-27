import ReactEChartsCore from "echarts-for-react/lib/core";
import * as echarts from "echarts/core";
import { BarChart, LineChart } from "echarts/charts";
import { GridComponent, MarkAreaComponent, MarkLineComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { CHART_THEME } from "../../lib/echartsTheme";
import type { OnuHistoryDay } from "../../api/fiber";
import { scoreTone } from "./score";

echarts.use([BarChart, LineChart, GridComponent, TooltipComponent, MarkLineComponent, MarkAreaComponent, CanvasRenderer]);

const AXIS = { color: "#a1a1aa" };
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

/** Daily measured Rx against the model's expected Rx (± MAE band) and the sensitivity line. */
export function RxHistoryChart({ history, expected, mae, sensitivity = -28 }: {
  history: OnuHistoryDay[]; expected: number | null; mae: number | null; sensitivity?: number;
}) {
  const rx = history.map((h) => h.rx).filter((v): v is number => v != null);
  const lo = Math.min(sensitivity, ...rx, expected != null ? expected - (mae ?? 0) : 0) - 1.5;
  const hi = Math.max(...rx, expected != null ? expected + (mae ?? 0) : -40, sensitivity) + 1.5;
  const markArea = expected != null && mae != null
    ? { silent: true, itemStyle: { color: "rgba(16,185,129,0.10)" }, data: [[{ yAxis: expected - mae }, { yAxis: expected + mae }]] }
    : undefined;
  const lines = [
    { yAxis: sensitivity, lineStyle: { color: "#dc2626", type: "dotted" }, label: { formatter: `sensitivity ${sensitivity}`, color: "#dc2626", position: "insideEndTop" } },
    ...(expected != null ? [{ yAxis: Number(expected.toFixed(2)), lineStyle: { color: "#059669", type: "dashed" }, label: { formatter: `expected ${expected.toFixed(1)}`, color: "#059669", position: "insideEndBottom" } }] : []),
  ];
  return (
    <ReactEChartsCore echarts={echarts} theme={CHART_THEME} style={{ height: 200 }} notMerge
      option={{
        animation: false,
        tooltip: {
          trigger: "axis",
          formatter: (ps: { axisValue: string; dataIndex: number }[]) => {
            const h = history[ps[0].dataIndex];
            return `${ps[0].axisValue}<br/>Rx <b>${h.rx ?? "—"}</b> dBm<br/>BIP in ${h.bip_in ?? "n/a"} · lost carrier ${h.lostcarrier ?? "n/a"}`;
          },
        },
        grid: { left: 8, right: 12, top: 12, bottom: 4, containLabel: true },
        xAxis: { type: "category", data: history.map((h) => h.date.slice(5)), axisTick: { show: false }, axisLine: { lineStyle: { color: "#e4e4e7" } }, axisLabel: AXIS },
        yAxis: { type: "value", min: Math.floor(lo), max: Math.ceil(hi), splitLine: SPLIT, axisLabel: { ...AXIS, formatter: "{value}" }, name: "dBm", nameTextStyle: AXIS },
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
