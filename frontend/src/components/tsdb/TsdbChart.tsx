import ReactEChartsCore from "echarts-for-react/lib/core";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import { DataZoomComponent, GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { CHART_THEME } from "../../lib/echartsTheme";
import { compact, fmtMs } from "./format";

echarts.use([LineChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, CanvasRenderer]);

export interface ChartSeries {
  name: string;
  data: [number, number | null][];   // [ms, value]
  /** Draw against the right-hand y-axis. */
  right?: boolean;
}

const PALETTE = ["#2563eb", "#16a34a", "#dc2626", "#9333ea", "#ea580c", "#0891b2", "#ca8a04", "#db2777", "#4f46e5", "#65a30d"];

const yAxis = (position: "left" | "right", grid: boolean) => ({
  type: "value", position, scale: false,
  axisLabel: { color: "#a1a1aa", formatter: (v: number) => compact(v) },
  splitLine: { show: grid, lineStyle: { color: "#f4f4f5" } },
});

/** `group`: charts sharing a group move their crosshair and zoom together. */
export function TsdbChart({ series, startMs, endMs, height = 360, group }: {
  series: ChartSeries[]; startMs: number; endMs: number; height?: number; group?: string;
}) {
  const dual = series.some((s) => s.right) && series.some((s) => !s.right);
  return (
    <ReactEChartsCore echarts={echarts} theme={CHART_THEME} style={{ height }} notMerge
      onChartReady={(chart: echarts.ECharts) => {
        if (!group) return;
        chart.group = group;
        echarts.connect(group);
      }}
      option={{
        animation: false,
        color: PALETTE,
        tooltip: {
          trigger: "axis",
          confine: true,
          formatter: (items: { axisValue: number; marker: string; seriesName: string; value: [number, number | null] }[]) => {
            if (!items.length) return "";
            const rows = items
              .filter((i) => i.value[1] !== null && i.value[1] !== undefined)
              .sort((a, b) => (b.value[1] as number) - (a.value[1] as number))
              .slice(0, 15)
              .map((i) => `${i.marker}${i.seriesName}<span style="float:right;margin-left:16px;font-weight:600">${compact(i.value[1])}</span>`);
            return `<div style="font-size:12px"><div style="margin-bottom:4px;color:#71717a">${fmtMs(items[0].axisValue)}</div>${rows.join("<br/>") || "no data"}</div>`;
          },
        },
        legend: series.length > 1 ? { type: "scroll", bottom: 0, icon: "roundRect", itemGap: 18, itemWidth: 12, itemHeight: 4, textStyle: { color: "#52525b", fontSize: 12 } } : undefined,
        grid: { left: 8, right: 16, top: 16, bottom: series.length > 1 ? 72 : 44, containLabel: true },
        xAxis: {
          type: "time", min: startMs, max: endMs,
          axisLabel: { color: "#71717a", hideOverlap: true },
          axisLine: { lineStyle: { color: "#e4e4e7" } },
          splitLine: { show: false },
        },
        yAxis: dual ? [yAxis("left", true), yAxis("right", false)] : yAxis("left", true),
        dataZoom: [
          { type: "inside", filterMode: "none" },
          { type: "slider", height: 18, bottom: series.length > 1 ? 30 : 6, filterMode: "none", borderColor: "#e4e4e7", showDetail: false },
        ],
        series: series.map((s) => ({
          name: s.name, type: "line", data: s.data, showSymbol: false, connectNulls: false,
          yAxisIndex: dual && s.right ? 1 : 0, lineStyle: { width: 1.5, type: dual && s.right ? "dashed" : "solid" },
          emphasis: { focus: "series" },
        })),
      }} />
  );
}
