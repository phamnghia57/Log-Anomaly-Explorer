import { Suspense, lazy, useState } from "react";
import type { ClusterStatus } from "@/lib/api";
import { useClusters } from "@/lib/queries";
import { AppShell } from "@/components/layout/AppShell";
import { StatCards } from "@/components/dashboard/StatCards";
import { ClusterGrid } from "@/components/dashboard/ClusterGrid";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";

// ECharts kha nang (~400kB gzip) - tach rieng chunk, chi tai khi Dashboard
// thuc su render (khong chan FCP cua shell/skeleton).
const AnomalyScoreChart = lazy(() =>
  import("@/components/dashboard/AnomalyScoreChart").then((m) => ({ default: m.AnomalyScoreChart })),
);

const STATUS_FILTERS: { value: ClusterStatus | "all"; label: string }[] = [
  { value: "all", label: "Tất cả" },
  { value: "alerted", label: "Alerted" },
  { value: "anomalous", label: "Anomalous" },
  { value: "normal", label: "Normal" },
];

export function DashboardPage() {
  const [status, setStatus] = useState<ClusterStatus | "all">("all");
  const { data, isLoading, isError, error } = useClusters(status === "all" ? "" : status);

  return (
    <AppShell title="Dashboard">
      <div className="space-y-6">
        {isLoading && (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-20" />
            ))}
          </div>
        )}

        {isError && (
          <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
            {error instanceof Error ? error.message : "Không tải được dữ liệu."}
          </div>
        )}

        {data && <StatCards clusters={data.clusters} />}

        {data && data.clusters.length > 0 && (
          <div className="rounded-xl border bg-card p-4">
            <h2 className="mb-3 text-sm font-semibold text-muted-foreground">
              Top 10 cụm theo anomaly score
            </h2>
            <Suspense fallback={<Skeleton className="h-40" />}>
              <AnomalyScoreChart clusters={data.clusters} />
            </Suspense>
          </div>
        )}

        <div>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-muted-foreground">Cụm bất thường</h2>
            <Tabs value={status} onValueChange={(v) => setStatus(v as ClusterStatus | "all")}>
              <TabsList>
                {STATUS_FILTERS.map((f) => (
                  <TabsTrigger key={f.value} value={f.value}>
                    {f.label}
                  </TabsTrigger>
                ))}
              </TabsList>
            </Tabs>
          </div>

          {isLoading ? (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-36" />
              ))}
            </div>
          ) : (
            data && <ClusterGrid clusters={data.clusters} />
          )}
        </div>
      </div>
    </AppShell>
  );
}
