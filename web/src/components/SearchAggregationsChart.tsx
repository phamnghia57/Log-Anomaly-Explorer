import * as echarts from "echarts/core";
import { BarChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import ReactEChartsCore from "echarts-for-react/esm/core";
import type { SearchAggregations } from "@/lib/api";

echarts.use([BarChart, GridComponent, TooltipComponent, CanvasRenderer]);

export function SearchAggregationsChart({ data }: { data: SearchAggregations }) {
  if (!data.histogram.length) {
    return <p className="py-4 text-sm text-muted-foreground">Chưa có dữ liệu trong khoảng thời gian này.</p>;
  }
  const option = {
    grid: { left: 40, right: 12, top: 18, bottom: 65 },
    tooltip: { trigger: "axis" },
    xAxis: { type: "category", data: data.histogram.map((v) => v.time), axisLabel: { rotate: 40, hideOverlap: true } },
    yAxis: { type: "value", minInterval: 1 },
    series: [{ type: "bar", name: "Logs", data: data.histogram.map((v) => v.count), barMaxWidth: 28 }],
  };
  return <ReactEChartsCore echarts={echarts} option={option} style={{ height: 280 }} />;
}
