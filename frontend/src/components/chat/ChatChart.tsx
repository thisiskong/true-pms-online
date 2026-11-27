import ReactEChartsCore from "echarts-for-react/lib/core";
import * as echarts from "echarts/core";
import { BarChart, LineChart, PieChart } from "echarts/charts";
import { GridComponent, LegendComponent, TitleComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { CHART_THEME } from "../../lib/echartsTheme";
import type { ChartPart } from "../../hooks/useChat";

echarts.use([PieChart, BarChart, LineChart, GridComponent, TooltipComponent, LegendComponent, TitleComponent, CanvasRenderer]);

const PALETTE = ["#1d4ed8", "#27272a", "#f59e0b", "#e11d48", "#7c3aed", "#0891b2", "#65a30d", "#db2777", "#71717a", "#ea580c"];
const AXIS = { axisLabel: { color: "#71717a" }, axisLine: { lineStyle: { color: "#d4d4d8" } } };
const SPLIT = { splitLine: { lineStyle: { color: "#f4f4f5" } } };

function option(p: ChartPart) {
  const unit = p.unit ? ` ${p.unit}` : "";
  const fmt = (v: number) => `${v.toLocaleString()}${unit}`;
  const multi = p.series.length > 1;
  const base = {
    animation: false,
    color: PALETTE,
    title: { text: p.title, left: 8, top: 6, textStyle: { fontSize: 13, fontWeight: 600, color: "#18181b" } },
  };
  if (p.chart_type === "pie") {
    const s = p.series[0];
    return {
      ...base,
      tooltip: { trigger: "item", valueFormatter: fmt },
      legend: { type: "scroll", orient: "vertical", right: 8, top: 40, bottom: 8, textStyle: { color: "#52525b", fontSize: 12 } },
      series: [{
        type: "pie", name: s.name, radius: ["40%", "70%"], center: ["38%", "56%"],
        label: { formatter: "{b}: {d}%", color: "#3f3f46", fontSize: 11 },
        data: p.labels.map((name, i) => ({ name, value: s.values[i] })),
      }],
    };
  }
  const horizontal = p.chart_type === "hbar";
  const cat = { type: "category", data: p.labels, ...AXIS, axisTick: { show: false }, ...(horizontal ? { inverse: true } : {}) };
  const val = { type: "value", ...AXIS, ...SPLIT, axisLine: { show: false } };
  return {
    ...base,
    tooltip: { trigger: "axis", axisPointer: { type: p.chart_type === "line" ? "line" : "shadow" }, valueFormatter: fmt },
    legend: multi ? { top: 6, right: 8, textStyle: { color: "#52525b", fontSize: 12 } } : undefined,
    grid: { left: 12, right: 20, top: 44, bottom: 8, containLabel: true },
    xAxis: horizontal ? val : { ...cat, axisLabel: { ...AXIS.axisLabel, rotate: p.labels.length > 8 ? 35 : 0 } },
    yAxis: horizontal ? cat : val,
    series: p.series.map((s) => ({
      type: p.chart_type === "line" ? "line" : "bar", name: s.name, data: s.values,
      barMaxWidth: 28, smooth: false, symbolSize: 6,
      itemStyle: p.chart_type === "line" ? undefined : { borderRadius: horizontal ? [0, 3, 3, 0] : [3, 3, 0, 0] },
    })),
  };
}

export default function ChatChart({ p }: { p: ChartPart }) {
  const height = p.chart_type === "hbar" ? Math.max(220, 60 + p.labels.length * 24) : 300;
  return (
    <div className="overflow-hidden rounded-lg border border-zinc-200 bg-white">
      <ReactEChartsCore echarts={echarts} theme={CHART_THEME} style={{ height }} notMerge option={option(p)} />
    </div>
  );
}
