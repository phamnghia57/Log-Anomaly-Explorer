import { useMemo } from "react";
import type { ClusterRecord, ClusterStatus } from "@/lib/api";
import { cn } from "@/lib/utils";

const FACETS: { value: ClusterStatus | "all"; label: string }[] = [
  { value: "all", label: "Tất cả" },
  { value: "alerted", label: "Alerted" },
  { value: "anomalous", label: "Anomalous" },
  { value: "normal", label: "Normal" },
];

// Facet tinh client-side tu danh sach cum DA TAI (so cum demo-scale, khong
// can aggregation endpoint rieng). Chi facet theo `status`: ClusterRecord
// (cluster-record.schema.json, additionalProperties: false) KHONG co field
// `service` - service chi nam trong cluster_id dang sha1 mot chieu, khong
// doc nguoc lai duoc. Muon facet theo service phai doi contract (Nam), chua
// lam o day.
export function StatusFacets({
  clusters, value, onChange,
}: {
  clusters: ClusterRecord[];
  value: ClusterStatus | "all";
  onChange: (status: ClusterStatus | "all") => void;
}) {
  const counts = useMemo(() => {
    const byStatus: Record<string, number> = { all: clusters.length };
    for (const c of clusters) byStatus[c.status] = (byStatus[c.status] ?? 0) + 1;
    return byStatus;
  }, [clusters]);

  return (
    <nav className="space-y-1" aria-label="Lọc theo trạng thái">
      <p className="px-2 pb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        Trạng thái
      </p>
      {FACETS.map((f) => (
        <button
          key={f.value}
          type="button"
          onClick={() => onChange(f.value)}
          className={cn(
            "flex w-full items-center justify-between rounded-md px-2 py-1.5 text-sm transition-colors",
            value === f.value
              ? "bg-accent font-medium text-accent-foreground"
              : "text-muted-foreground hover:bg-accent/50",
          )}
        >
          <span>{f.label}</span>
          <span className="tabular-nums">{counts[f.value] ?? 0}</span>
        </button>
      ))}
    </nav>
  );
}
