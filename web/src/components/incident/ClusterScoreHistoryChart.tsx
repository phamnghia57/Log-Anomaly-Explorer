import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import ReactEChartsCore from "echarts-for-react/esm/core";
import { useMemo } from "react";
import type { ClusterHistoryPoint } from "@/lib/api";
import { formatDateTime } from "@/lib/format";

// Import modular, cung cach AnomalyScoreChart.tsx (giam bundle size).
echarts.use([LineChart, GridComponent, TooltipComponent, CanvasRenderer]);

const STATUS_COLOR: Record<ClusterHistoryPoint["status"], string> = {
  normal: "#94a3b8",
  anomalous: "#f59e0b",
  alerted: "#ef4444",
};

type PointDatum = [string, number, ClusterHistoryPoint["status"]];

// Bieu do duong: xu huong anomaly score theo thoi gian CUA MOT CUM (khac
// AnomalyScoreChart - so sanh diem HIEN TAI giua nhieu cum). Moi diem to mau
// theo status luc do, de thay duoc luc nao cum vuot nguong/duoc alert.
export function ClusterScoreHistoryChart({ points }: { points: ClusterHistoryPoint[] }) {
  const sorted = useMemo(
    () => [...points].sort((a, b) => a.recorded_at.localeCompare(b.recorded_at)),
    [points],
  );

  if (sorted.length === 0) return null;

  const option = {
    grid: { left: 8, right: 16, top: 24, bottom: 8, containLabel: true },
    tooltip: {
      trigger: "item",
      formatter: (p: { data: PointDatum }) =>
        `${formatDateTime(p.data[0])}<br/>score: <b>${p.data[1]}</b> · ${p.data[2]}`,
    },
    xAxis: { type: "time", axisLabel: { fontSize: 11 } },
    yAxis: { type: "value", splitLine: { lineStyle: { color: "#e2e8f0" } } },
    series: [
      {
        type: "line",
        data: sorted.map((p): PointDatum => [p.recorded_at, Number(p.score.toFixed(2)), p.status]),
        symbolSize: 7,
        itemStyle: {
          color: (params: { data: PointDatum }) => STATUS_COLOR[params.data[2]],
        },
        lineStyle: { color: "#94a3b8" },
      },
    ],
  };

  return <ReactEChartsCore echarts={echarts} option={option} style={{ height: 220 }} />;
}
