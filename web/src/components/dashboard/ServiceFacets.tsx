import { useMemo } from "react";
import type { ClusterRecord } from "@/lib/api";
import { cn } from "@/lib/utils";

// Facet tinh client-side tu danh sach cum DA TAI, cung pattern voi
// StatusFacets.tsx (so cum demo-scale, khong can aggregation endpoint
// rieng). Danh sach service suy ra TU DU LIEU (khong hardcode) vi so luong
// service co the doi theo thoi gian (demo-app them fault type/service moi).
export function ServiceFacets({
  clusters, value, onChange,
}: {
  clusters: ClusterRecord[];
  value: string | "all";
  onChange: (service: string | "all") => void;
}) {
  const { services, counts } = useMemo(() => {
    const byService: Record<string, number> = { all: clusters.length };
    for (const c of clusters) {
      const service = c.service || "unknown";
      byService[service] = (byService[service] ?? 0) + 1;
    }
    const names = Object.keys(byService).filter((s) => s !== "all").sort();
    return { services: names, counts: byService };
  }, [clusters]);

  if (services.length === 0) return null;

  return (
    <nav className="space-y-1" aria-label="Lọc theo service">
      <p className="px-2 pb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        Service
      </p>
      {["all", ...services].map((service) => (
        <button
          key={service}
          type="button"
          onClick={() => onChange(service as string | "all")}
          className={cn(
            "flex w-full items-center justify-between rounded-md px-2 py-1.5 text-sm transition-colors",
            value === service
              ? "bg-accent font-medium text-accent-foreground"
              : "text-muted-foreground hover:bg-accent/50",
          )}
        >
          <span className="truncate">{service === "all" ? "Tất cả" : service}</span>
          <span className="tabular-nums">{counts[service] ?? 0}</span>
        </button>
      ))}
    </nav>
  );
}
