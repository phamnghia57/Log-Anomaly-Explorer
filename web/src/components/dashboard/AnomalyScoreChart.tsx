import * as echarts from "echarts/core";
import { BarChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import ReactEChartsCore from "echarts-for-react/esm/core";
import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import type { ClusterRecord } from "@/lib/api";

// Import modular (khong phai toan bo "echarts") - chi lay bar chart + grid/
// tooltip component can dung, giam dang ke bundle size so voi import mac
// dinh cua echarts-for-react (xem canh bao chunk size luc build).
echarts.use([BarChart, GridComponent, TooltipComponent, CanvasRenderer]);

const STATUS_COLOR: Record<ClusterRecord["status"], string> = {
  normal: "#94a3b8",
  anomalous: "#f59e0b",
  alerted: "#ef4444",
};

// Bieu do cot ngang: diem anomaly score cua tung cum, mau theo status - giup
// nhan dien nhanh cum nao dang bat thuong nhat trong toan he thong (ECharts,
// theo yeu cau truc quan hoa log/anomaly).
export function AnomalyScoreChart({ clusters }: { clusters: ClusterRecord[] }) {
  const navigate = useNavigate();

  const sorted = useMemo(
    () => [...clusters].sort((a, b) => b.score - a.score).slice(0, 10),
    [clusters],
  );

  if (sorted.length === 0) return null;

  const option = {
    grid: { left: 8, right: 24, top: 8, bottom: 8, containLabel: true },
    tooltip: {
      trigger: "item",
      formatter: (p: { data: { signature: string; status: string } ; value: number }) =>
        `<div style="max-width:260px;white-space:normal">${p.data.signature}</div>score: <b>${p.value}</b> · ${p.data.status}`,
    },
    xAxis: { type: "value", splitLine: { lineStyle: { color: "#e2e8f0" } } },
    yAxis: {
      type: "category",
      data: sorted.map((c) => c.cluster_id),
      axisLabel: {
        formatter: (id: string) => {
          const c = sorted.find((x) => x.cluster_id === id);
          const sig = c?.signature || id;
          return sig.length > 28 ? `${sig.slice(0, 28)}…` : sig;
        },
        fontSize: 11,
      },
      inverse: true,
    },
    series: [
      {
        type: "bar",
        data: sorted.map((c) => ({
          value: Number(c.score.toFixed(2)),
          signature: c.signature || c.cluster_id,
          status: c.status,
          clusterId: c.cluster_id,
          itemStyle: { color: STATUS_COLOR[c.status], borderRadius: [0, 4, 4, 0] },
        })),
        barMaxWidth: 18,
      },
    ],
  };

  return (
    <ReactEChartsCore
      echarts={echarts}
      option={option}
      style={{ height: Math.max(160, sorted.length * 34) }}
      onEvents={{
        click: (params: { data?: { clusterId?: string } }) => {
          if (params.data?.clusterId) navigate(`/clusters/${encodeURIComponent(params.data.clusterId)}`);
        },
      }}
    />
  );
}
