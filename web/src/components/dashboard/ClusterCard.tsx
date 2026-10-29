import { lazy, Suspense } from "react";
import { Link } from "react-router-dom";
import type { ClusterRecord } from "@/lib/api";
import { useClusterHistory } from "@/lib/queries";
import { formatRelative } from "@/lib/format";
import { ClusterStatusBadge } from "@/components/StatusBadge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { GitBranch } from "lucide-react";

const ClusterCardSparkline = lazy(() =>
  import("./ClusterCardSparkline").then((m) => ({ default: m.ClusterCardSparkline })),
);

const STATUS_ACCENT: Record<ClusterRecord["status"], string> = {
  normal: "border-l-muted-foreground/30",
  anomalous: "border-l-amber-400",
  alerted: "border-l-red-500",
};

function ScoreBar({ score }: { score: number }) {
  // Truc quan tuong doi so voi ANOMALY_THRESHOLD mac dinh (2.0, xem
  // clustering/README.md), khong phai gia tri co tran.
  const pct = Math.max(4, Math.min(100, (score / 6) * 100));
  const color = score >= 2 ? "bg-red-500" : score > 0 ? "bg-amber-400" : "bg-muted-foreground/30";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-muted">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="font-mono text-xs text-muted-foreground">{score.toFixed(2)}</span>
    </div>
  );
}

export function ClusterCard({ cluster: c }: { cluster: ClusterRecord }) {
  // Lich su rieng cua cum nay, dung ve sparkline - moi card 1 request rieng
  // (so cum hien dang o muc demo-scale, vai chuc cum). Neu so cum len hang
  // tram thi nen gop thanh 1 endpoint batch thay vi N request nho le o day.
  const { data: history } = useClusterHistory(c.cluster_id);

  return (
    <Link to={`/clusters/${encodeURIComponent(c.cluster_id)}`}>
      <Card className="h-full py-4 transition hover:border-primary/40 hover:shadow-md">
        <CardHeader className="flex-row items-start justify-between gap-2 px-4">
          <ClusterStatusBadge status={c.status} />
          <span className="flex items-center gap-1 text-xs text-muted-foreground">
            <GitBranch className="h-3 w-3" />
            {(c.trace_ids ?? []).length}
          </span>
        </CardHeader>
        <CardContent className="space-y-3 px-4">
          {/* Khoi "pattern": signature da chuan hoa (normalize_message trong
              clustering/src/clustering.py) trong boi canh ro rang hon, kem
              so log cua chinh pattern nay - giong cach cac tool log/APM
              hien thi "top pattern" cua 1 cum loi. */}
          <div className={`border-l-2 pl-2 ${STATUS_ACCENT[c.status]}`}>
            <div className="mb-1 flex items-center justify-between gap-2">
              <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                Pattern
              </span>
              <span className="font-mono text-[10px] text-muted-foreground">
                {(c.log_ids?.length ?? 0).toLocaleString("vi-VN")} log
              </span>
            </div>
            <p className="line-clamp-2 font-mono text-xs">{c.signature || c.cluster_id}</p>
          </div>

          <ScoreBar score={c.score} />

          {history && history.points.length > 1 && (
            <Suspense fallback={null}>
              <ClusterCardSparkline points={history.points} />
            </Suspense>
          )}

          <p className="text-xs text-muted-foreground">Gần nhất: {formatRelative(c.last_seen)}</p>
        </CardContent>
      </Card>
    </Link>
  );
}
