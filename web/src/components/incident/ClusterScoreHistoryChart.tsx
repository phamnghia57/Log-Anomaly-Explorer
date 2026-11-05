import type { ClusterHistoryPoint } from "@/lib/api";
import { ClusterHistoryChart } from "@/components/ClusterHistoryChart";

export function ClusterScoreHistoryChart({ points }: { points: ClusterHistoryPoint[] }) {
  return <ClusterHistoryChart points={points} />;
}
