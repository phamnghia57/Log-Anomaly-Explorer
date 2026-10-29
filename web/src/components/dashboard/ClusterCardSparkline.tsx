import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import { GridComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import ReactEChartsCore from "echarts-for-react/esm/core";
import { useMemo } from "react";
import type { ClusterHistoryPoint } from "@/lib/api";

// Import modular, cung quy uoc voi AnomalyScoreChart/ClusterScoreHistoryChart.
echarts.use([LineChart, GridComponent, CanvasRenderer]);

const STATUS_COLOR: Record<ClusterHistoryPoint["status"], string> = {
  normal: "#94a3b8",
  anomalous: "#f59e0b",
  alerted: "#ef4444",
};

// Ban thu nho KHONG truc/tooltip cua ClusterScoreHistoryChart (trang chi
// tiet) - dat trong card danh sach, chi can thay XU HUONG tang/giam, khong
// can doc so chinh xac tung diem.
export function ClusterCardSparkline({ points }: { points: ClusterHistoryPoint[] }) {
  const sorted = useMemo(
    () => [...points].sort((a, b) => a.recorded_at.localeCompare(b.recorded_at)),
    [points],
  );

  if (sorted.length < 2) return null;

  const latestStatus = sorted[sorted.length - 1].status;
  const option = {
    grid: { left: 0, right: 0, top: 2, bottom: 2 },
    xAxis: { type: "time", show: false },
    yAxis: { type: "value", show: false, min: 0 },
    series: [
      {
        type: "line",
        data: sorted.map((p) => [p.recorded_at, p.score]),
        showSymbol: false,
        lineStyle: { width: 1.5, color: STATUS_COLOR[latestStatus] },
        areaStyle: { color: STATUS_COLOR[latestStatus], opacity: 0.12 },
      },
    ],
  };

  return <ReactEChartsCore echarts={echarts} option={option} style={{ height: 32 }} />;
}
