import type { ClusterStatus, LogLevel } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";

const CLUSTER_STYLES: Record<ClusterStatus, string> = {
  normal: "bg-muted text-muted-foreground",
  anomalous: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  alerted: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300",
};

const CLUSTER_LABELS: Record<ClusterStatus, string> = {
  normal: "Normal",
  anomalous: "Anomalous",
  alerted: "Alerted",
};

export function ClusterStatusBadge({ status }: { status: ClusterStatus }) {
  return (
    <Badge variant="outline" className={cn("gap-1.5 border-transparent font-medium", CLUSTER_STYLES[status])}>
      {status === "alerted" && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-red-500" />}
      {CLUSTER_LABELS[status]}
    </Badge>
  );
}

const LEVEL_STYLES: Record<LogLevel, string> = {
  DEBUG: "text-muted-foreground",
  INFO: "text-sky-600 dark:text-sky-400",
  WARN: "text-amber-600 dark:text-amber-400",
  ERROR: "text-red-600 dark:text-red-400",
  FATAL: "text-red-700 dark:text-red-300 font-semibold",
};

export function LevelTag({ level }: { level: LogLevel }) {
  return <span className={cn("font-mono text-xs font-medium", LEVEL_STYLES[level])}>{level}</span>;
}
