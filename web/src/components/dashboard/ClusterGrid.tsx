import type { ClusterRecord } from "@/lib/api";
import { ClusterCard } from "./ClusterCard";

export function ClusterGrid({ clusters }: { clusters: ClusterRecord[] }) {
  if (clusters.length === 0) {
    return (
      <div className="rounded-lg border border-dashed p-10 text-center text-sm text-muted-foreground">
        Không có cụm nào khớp bộ lọc.
      </div>
    );
  }

  const sorted = [...clusters].sort((a, b) => b.score - a.score);

  return (
    <div className="cluster-card-grid min-w-0">
      {sorted.map((c) => (
        <ClusterCard key={c.cluster_id} cluster={c} />
      ))}
    </div>
  );
}
