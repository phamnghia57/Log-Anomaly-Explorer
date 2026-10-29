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
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {sorted.map((c) => (
        <ClusterCard key={c.cluster_id} cluster={c} />
      ))}
    </div>
  );
}
