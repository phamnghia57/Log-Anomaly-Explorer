import { useMemo } from "react";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import { DataZoomComponent, GridComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import ReactEChartsCore from "echarts-for-react/esm/core";
import type { ClusterHistoryPoint } from "@/lib/api";
import { chartAxis, chartTooltip, chartColors } from "@/lib/chart-theme";
import { formatDateTime } from "@/lib/format";

echarts.use([LineChart, DataZoomComponent, GridComponent, TooltipComponent, CanvasRenderer]);

export function ClusterHistoryChart({ points, compact = false }: { points: ClusterHistoryPoint[]; compact?: boolean }) {
  const option = useMemo(() => {
    const sorted = [...points].sort((a, b) => Date.parse(a.recorded_at) - Date.parse(b.recorded_at));
    return {
      animation: false,
      grid: compact
        ? { left: 4, right: 4, top: 6, bottom: 4 }
        : { left: 12, right: 20, top: 22, bottom: 64, containLabel: true },
      tooltip: {
        show: !compact,
        ...chartTooltip, trigger: "axis", axisPointer: { type: "cross", lineStyle: { color: "#8e8e96", type: "dashed" } },
        formatter: (items: { data: [string, number, ClusterHistoryPoint["status"]] }[]) => {
          const point = items[0]?.data;
          return point ? `${formatDateTime(point[0])}<br/>Anomaly score: <b>${point[1].toFixed(2)}</b> · ${point[2]}` : "";
        },
      },
      xAxis: { ...chartAxis, show: !compact, type: "time", boundaryGap: ["3%", "3%"], splitNumber: compact ? 3 : 7,
        axisLabel: { ...chartAxis.axisLabel, hideOverlap: true }, splitLine: { show: false } },
      yAxis: { ...chartAxis, show: !compact, type: "value", min: 0, scale: true, splitNumber: 4 },
      dataZoom: compact ? [] : [
        { type: "inside", filterMode: "none", zoomOnMouseWheel: "ctrl" },
        { type: "slider", filterMode: "none", bottom: 6, height: 20, borderColor: "#343438",
          backgroundColor: "#101012", fillerColor: "#73bf6920", handleStyle: { color: "#73737c" },
          dataBackground: { lineStyle: { color: "#73737c" }, areaStyle: { color: "#303035" } },
          selectedDataBackground: { lineStyle: { color: "#73bf69" }, areaStyle: { color: "#73bf6930" } },
          textStyle: { color: "#a6a6af" }, showDetail: false },
      ],
      series: [{ name: "Anomaly score", type: "line", smooth: false, connectNulls: false, silent: compact,
        data: sorted.map((p) => [p.recorded_at, p.score, p.status]),
        symbol: "circle", symbolSize: 5, showSymbol: compact ? sorted.length === 1 : sorted.length <= 20,
        lineStyle: { width: 2, color: chartColors.line },
        itemStyle: { color: (p: { data: [string, number, ClusterHistoryPoint["status"]] }) => chartColors[p.data[2]],
          borderColor: "#18181b", borderWidth: 1 },
        areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: "#73bf6926" }, { offset: 1, color: "#73bf6900" },
        ]) }, emphasis: { scale: 1.5 },
      }],
    };
  }, [points, compact]);
  if (!points.length) return null;
  return <div className="min-w-0" role="img" aria-label="Anomaly score history">
    <ReactEChartsCore echarts={echarts} option={option} style={{ height: compact ? 64 : 360, width: "100%" }} />
    {!compact && <p className="mt-1 flex items-center gap-2 text-[10px] text-muted-foreground"><span className="inline-block h-0.5 w-4 bg-[#73bf69]" />Anomaly score<span className="ml-auto">Kéo thanh để phóng to thời gian</span></p>}
  </div>;
}
