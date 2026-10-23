import { Link } from "react-router-dom";
import type { ClusterRecord } from "@/lib/api";
import { formatRelative } from "@/lib/format";
import { ClusterStatusBadge } from "@/components/StatusBadge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { GitBranch } from "lucide-react";

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
        <Link key={c.cluster_id} to={`/clusters/${encodeURIComponent(c.cluster_id)}`}>
          <Card className="h-full py-4 transition hover:border-primary/40 hover:shadow-md">
            <CardHeader className="flex-row items-start justify-between gap-2 px-4">
              <ClusterStatusBadge status={c.status} />
              <span className="flex items-center gap-1 text-xs text-muted-foreground">
                <GitBranch className="h-3 w-3" />
                {(c.trace_ids ?? []).length}
              </span>
            </CardHeader>
            <CardContent className="space-y-3 px-4">
              <p className="line-clamp-2 font-mono text-xs text-muted-foreground">
                {c.signature || c.cluster_id}
              </p>
              <ScoreBar score={c.score} />
              <p className="text-xs text-muted-foreground">Gần nhất: {formatRelative(c.last_seen)}</p>
            </CardContent>
          </Card>
        </Link>
      ))}
    </div>
  );
}
