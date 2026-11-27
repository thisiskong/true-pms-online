import ReactEChartsCore from "echarts-for-react/lib/core";
import * as echarts from "echarts/core";
import { BarChart, PieChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { CHART_THEME } from "../../lib/echartsTheme";
import type { InterfaceSummary } from "../../api/types";

echarts.use([PieChart, BarChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer]);

const OPER_COLOR: Record<string, string> = {
  up: "#10b981", down: "#f43f5e", lowerLayerDown: "#f59e0b", dormant: "#a1a1aa", notPresent: "#d4d4d8", unknown: "#e4e4e7",
};

const SPEED_ORDER = ["0 / unknown", "< 1G", "1G", "10G", "25G-40G", "100G", "400G+"];

export function OperDonut({ s, onSelect }: { s: InterfaceSummary; onSelect?: (oper: string) => void }) {
  const data = Object.entries(s.by_oper).sort((a, b) => b[1] - a[1]).map(([name, value]) => ({
    name, value, itemStyle: { color: OPER_COLOR[name] ?? "#71717a" },
  }));
  return (
    <ReactEChartsCore echarts={echarts} theme={CHART_THEME} style={{ height: 200 }} notMerge
      onEvents={onSelect ? { click: (p: { name: string }) => onSelect(p.name) } : undefined}
      option={{
        animation: false,
        tooltip: { trigger: "item", formatter: "{b}: {c} ({d}%)" },
        legend: { orient: "vertical", right: 0, top: "middle", icon: "circle", textStyle: { color: "#52525b", fontSize: 12 } },
        series: [{
          type: "pie", radius: ["55%", "80%"], center: ["35%", "50%"], avoidLabelOverlap: true,
          label: { show: true, position: "center", formatter: () => `${s.total.toLocaleString()}\ninterfaces`, fontSize: 13, color: "#3f3f46", lineHeight: 18 },
          labelLine: { show: false }, data,
        }],
      }} />
  );
}

export function SpeedBars({ s }: { s: InterfaceSummary }) {
  const keys = SPEED_ORDER.filter((k) => s.by_speed[k]);
  return (
    <ReactEChartsCore echarts={echarts} theme={CHART_THEME} style={{ height: 200 }} notMerge
      option={{
        animation: false,
        tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
        grid: { left: 8, right: 16, top: 10, bottom: 4, containLabel: true },
        xAxis: { type: "value", splitLine: { lineStyle: { color: "#f4f4f5" } }, axisLabel: { color: "#a1a1aa" } },
        yAxis: { type: "category", data: keys, inverse: true, axisTick: { show: false }, axisLine: { show: false }, axisLabel: { color: "#52525b" } },
        series: [{ type: "bar", data: keys.map((k) => s.by_speed[k]), itemStyle: { color: "#27272a", borderRadius: [0, 4, 4, 0] }, barMaxWidth: 18 }],
      }} />
  );
}
