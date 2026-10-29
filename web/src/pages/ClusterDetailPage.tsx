import { Suspense, lazy, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useCluster, useClusterHistory } from "@/lib/queries";
import { formatDateTime } from "@/lib/format";
import { getJaegerTraceUrl } from "@/lib/api";
import { AppShell } from "@/components/layout/AppShell";
import { ClusterStatusBadge } from "@/components/StatusBadge";
import { LogTable } from "@/components/LogTable";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ArrowLeft, ExternalLink, GitBranch } from "lucide-react";

const TRACE_PREVIEW_COUNT = 40;
// Khop mac dinh `logs_limit` cua GET /clusters/{id} (api-contract.md).
const LOGS_PAGE_SIZE = 100;
// Tran `logs_limit` cua API - xin qua muc nay API tra 422, nen phai chan o day.
const LOGS_MAX = 1000;

// Tach rieng chunk ECharts, cung ly do voi AnomalyScoreChart o DashboardPage.
const ClusterScoreHistoryChart = lazy(() =>
  import("@/components/incident/ClusterScoreHistoryChart").then((m) => ({
    default: m.ClusterScoreHistoryChart,
  })),
);

// Panel AI Assistant - tach rieng chunk vi khong phai ai cung mo, khong can
// tai cung luc voi phan con lai cua Incident View.
const AssistantPanel = lazy(() =>
  import("@/components/incident/AssistantPanel").then((m) => ({ default: m.AssistantPanel })),
);

export function ClusterDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [showAllTraces, setShowAllTraces] = useState(false);
  const [logsLimit, setLogsLimit] = useState(LOGS_PAGE_SIZE);

  const { data: cluster, isLoading, isError, error, isFetching } = useCluster(id, logsLimit);
  const { data: history } = useClusterHistory(id);

  return (
    <AppShell title="Incident View">
      <div className="space-y-6">
        <Button variant="ghost" size="sm" asChild className="-ml-2 gap-1.5">
          <Link to="/">
            <ArrowLeft className="h-4 w-4" />
            Về danh sách cụm
          </Link>
        </Button>

        {isLoading && (
          <div className="space-y-3">
            <Skeleton className="h-40" />
            <Skeleton className="h-64" />
          </div>
        )}

        {isError && (
          <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
            {error instanceof Error ? error.message : `Không tìm thấy cụm "${id}".`}
          </div>
        )}

        {cluster && (
          <>
            <Card className="py-5">
              <CardContent className="px-5">
                <div className="mb-3 flex flex-wrap items-center gap-3">
                  <ClusterStatusBadge status={cluster.status} />
                  <span className="font-mono text-xs text-muted-foreground">{cluster.cluster_id}</span>
                </div>
                <h2 className="mb-4 break-words font-mono text-lg font-semibold">
                  {cluster.signature || "(không có signature)"}
                </h2>

                <dl className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
                  <div>
                    <dt className="text-xs uppercase tracking-wide text-muted-foreground">Anomaly score</dt>
                    <dd className="mt-1 font-mono text-xl font-semibold">{cluster.score.toFixed(2)}</dd>
                  </div>
                  <div>
                    <dt className="text-xs uppercase tracking-wide text-muted-foreground">Logs liên quan</dt>
                    <dd className="mt-1 text-xl font-semibold">
                      {cluster.logs?.length ?? cluster.log_ids?.length ?? 0}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs uppercase tracking-wide text-muted-foreground">First seen</dt>
                    <dd className="mt-1">{formatDateTime(cluster.first_seen)}</dd>
                  </div>
                  <div>
                    <dt className="text-xs uppercase tracking-wide text-muted-foreground">Last seen</dt>
                    <dd className="mt-1">{formatDateTime(cluster.last_seen)}</dd>
                  </div>
                </dl>

                {cluster.trace_ids?.length > 0 && (
                  <div className="mt-5 border-t pt-4">
                    <p className="mb-2 flex items-center gap-1.5 text-xs uppercase tracking-wide text-muted-foreground">
                      <GitBranch className="h-3.5 w-3.5" />
                      Trace / request liên quan ({cluster.trace_ids.length})
                    </p>
                    <div className="flex flex-wrap gap-2">
                      {(showAllTraces ? cluster.trace_ids : cluster.trace_ids.slice(0, TRACE_PREVIEW_COUNT)).map(
                        (tid) => {
                          const jaegerUrl = getJaegerTraceUrl(tid);
                          return (
                            <div key={tid} className="flex items-stretch overflow-hidden rounded-md bg-secondary">
                              <Button
                                variant="secondary"
                                size="sm"
                                className="h-auto rounded-none px-2 py-1 font-mono text-xs"
                                onClick={() => navigate(`/search?trace_id=${encodeURIComponent(tid)}`)}
                                title="Lọc log theo trace này"
                              >
                                {tid.slice(0, 16)}
                              </Button>
                              {jaegerUrl && (
                                <a
                                  href={jaegerUrl}
                                  target="_blank"
                                  rel="noreferrer"
                                  title="Xem trace trên Jaeger"
                                  className="flex items-center border-l border-background/50 px-1.5 text-muted-foreground hover:text-foreground"
                                >
                                  <ExternalLink className="h-3 w-3" />
                                </a>
                              )}
                            </div>
                          );
                        },
                      )}
                      {!showAllTraces && cluster.trace_ids.length > TRACE_PREVIEW_COUNT && (
                        <Button variant="link" size="sm" onClick={() => setShowAllTraces(true)}>
                          +{cluster.trace_ids.length - TRACE_PREVIEW_COUNT} trace khác
                        </Button>
                      )}
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>

            {history && history.points.length > 0 && (
              <div className="rounded-xl border bg-card p-4">
                <h2 className="mb-3 text-sm font-semibold text-muted-foreground">
                  Xu hướng anomaly score
                </h2>
                <Suspense fallback={<Skeleton className="h-40" />}>
                  <ClusterScoreHistoryChart points={history.points} />
                </Suspense>
              </div>
            )}

            <section>
              <h2 className="mb-3 text-sm font-semibold text-muted-foreground">
                Log trong cụm
                {cluster.logs_total !== undefined && (
                  <span className="ml-1 font-normal">
                    ({cluster.logs?.length ?? 0}/{cluster.logs_total})
                  </span>
                )}
              </h2>
              <LogTable
                logs={cluster.logs ?? []}
                onTraceClick={(traceId) => navigate(`/search?trace_id=${encodeURIComponent(traceId)}`)}
              />

              {cluster.logs_total !== undefined && cluster.logs_total > logsLimit && (
                <div className="mt-3 flex justify-center">
                  {logsLimit < LOGS_MAX ? (
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={isFetching}
                      onClick={() =>
                        setLogsLimit((current) => Math.min(current + LOGS_PAGE_SIZE, LOGS_MAX))
                      }
                    >
                      {isFetching
                        ? "Đang tải…"
                        : `Tải thêm ${Math.min(LOGS_PAGE_SIZE, cluster.logs_total - logsLimit)} log`}
                    </Button>
                  ) : (
                    <p className="text-xs text-muted-foreground">
                      Đã tải tối đa {LOGS_MAX} log — lọc tiếp bằng trang Search nếu cần xem phần
                      còn lại.
                    </p>
                  )}
                </div>
              )}
            </section>

            <Suspense fallback={<Skeleton className="h-[28rem]" />}>
              <AssistantPanel clusterId={cluster.cluster_id} />
            </Suspense>
          </>
        )}
      </div>
    </AppShell>
  );
}
