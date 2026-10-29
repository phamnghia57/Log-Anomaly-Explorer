import { Suspense, lazy, useMemo, useState } from "react";
import type { ClusterStatus } from "@/lib/api";
import { useClusters } from "@/lib/queries";
import { AppShell } from "@/components/layout/AppShell";
import { StatCards } from "@/components/dashboard/StatCards";
import { ClusterGrid } from "@/components/dashboard/ClusterGrid";
import { StatusFacets } from "@/components/dashboard/StatusFacets";
import {
  TimeRangeControl, sinceFromRange, type TimeRangeKey,
} from "@/components/dashboard/TimeRangeControl";
import { Skeleton } from "@/components/ui/skeleton";

// ECharts kha nang (~400kB gzip) - tach rieng chunk, chi tai khi Dashboard
// thuc su render (khong chan FCP cua shell/skeleton).
const AnomalyScoreChart = lazy(() =>
  import("@/components/dashboard/AnomalyScoreChart").then((m) => ({ default: m.AnomalyScoreChart })),
);

export function DashboardPage() {
  const [status, setStatus] = useState<ClusterStatus | "all">("all");
  const [range, setRange] = useState<TimeRangeKey>("24h");
  const [autoRefreshMs, setAutoRefreshMs] = useState<number | false>(30_000);

  // QUAN TRONG: khong goi sinceFromRange(range) truc tiep trong than ham render.
  // No doc Date.now() nen moi lan render ra 1 chuoi ISO khac nhau -> queryKey
  // cua useClusters doi lien tuc -> React Query coi la query moi moi lan,
  // bao giai refetch vo han, UI ket o loading mai (da gap that, xem commit
  // nay). useMemo khoa `since` lai, chi tinh lai khi NGUOI DUNG doi `range`.
  const since = useMemo(() => sinceFromRange(range), [range]);
  const { data, isLoading, isFetching, isError, error, refetch } = useClusters(since, autoRefreshMs);

  // Loc hien thi theo status o client (data da tai day du trong khoang thoi
  // gian). StatusFacets van nhan `data.clusters` CHUA LOC de dem dung so
  // luong cho ca 4 facet, khong chi facet dang chon.
  const filtered = useMemo(() => {
    if (!data) return undefined;
    return status === "all" ? data.clusters : data.clusters.filter((c) => c.status === status);
  }, [data, status]);

  return (
    <AppShell title="Dashboard">
      <div className="space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-sm font-semibold text-muted-foreground">Tổng quan</h2>
          <TimeRangeControl
            range={range}
            onRangeChange={setRange}
            autoRefreshMs={autoRefreshMs}
            onAutoRefreshChange={setAutoRefreshMs}
            onRefresh={() => refetch()}
            isFetching={isFetching}
          />
        </div>

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

        {filtered && <StatCards clusters={filtered} />}

        {filtered && filtered.length > 0 && (
          <div className="rounded-xl border bg-card p-4">
            <h2 className="mb-3 text-sm font-semibold text-muted-foreground">
              Top 10 cụm theo anomaly score
            </h2>
            <Suspense fallback={<Skeleton className="h-40" />}>
              <AnomalyScoreChart clusters={filtered} />
            </Suspense>
          </div>
        )}

        <div>
          <h2 className="mb-3 text-sm font-semibold text-muted-foreground">Cụm bất thường</h2>

          <div className="grid gap-4 lg:grid-cols-[180px_1fr]">
            <aside className="lg:sticky lg:top-6 lg:self-start">
              {data && <StatusFacets clusters={data.clusters} value={status} onChange={setStatus} />}
            </aside>

            {isLoading ? (
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {Array.from({ length: 3 }).map((_, i) => (
                  <Skeleton key={i} className="h-36" />
                ))}
              </div>
            ) : (
              filtered && <ClusterGrid clusters={filtered} />
            )}
          </div>
        </div>
      </div>
    </AppShell>
  );
}
