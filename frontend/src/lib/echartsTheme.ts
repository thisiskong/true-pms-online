import * as echarts from "echarts/core";

// ECharts draws on a canvas and does not inherit CSS fonts; keep this in sync with --font-sans in index.css.
export const CHART_THEME = "app";

echarts.registerTheme(CHART_THEME, {
  textStyle: { fontFamily: '"Inter Variable", "Noto Sans Thai", "Segoe UI", system-ui, sans-serif' },
});
