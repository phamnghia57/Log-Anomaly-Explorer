import { getJaegerTraceUrl, type StructuredLog } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { LevelTag } from "@/components/StatusBadge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { ExternalLink } from "lucide-react";

export function LogDetailDialog({
  log,
  open,
  onOpenChange,
}: {
  log: StructuredLog | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        {log && (
          <>
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2 font-mono text-base">
                <LevelTag level={log.level} />
                {log.service}
              </DialogTitle>
              <DialogDescription>{formatDateTime(log.timestamp)}</DialogDescription>
            </DialogHeader>

            <p className="text-sm">{log.message}</p>

            <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
              <div className="flex gap-1">
                <dt className="font-medium text-muted-foreground">trace_id:</dt>
                <dd className="truncate font-mono">{log.trace_id}</dd>
              </div>
              <div className="flex gap-1">
                <dt className="font-medium text-muted-foreground">span_id:</dt>
                <dd className="truncate font-mono">{log.span_id}</dd>
              </div>
            </dl>

            {getJaegerTraceUrl(log.trace_id) && (
              <Button variant="outline" size="sm" className="w-fit gap-1.5" asChild>
                <a href={getJaegerTraceUrl(log.trace_id)!} target="_blank" rel="noreferrer">
                  Xem trace trên Jaeger
                  <ExternalLink className="h-3.5 w-3.5" />
                </a>
              </Button>
            )}

            {log.stack_trace && (
              <pre className="max-h-64 overflow-auto rounded bg-muted p-3 text-xs">{log.stack_trace}</pre>
            )}

            {log.metadata && Object.keys(log.metadata).length > 0 && (
              <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-3">
                {Object.entries(log.metadata).map(([k, v]) => (
                  <div key={k} className="flex gap-1">
                    <dt className="font-medium text-muted-foreground">{k}:</dt>
                    <dd className="truncate font-mono">{String(v)}</dd>
                  </div>
                ))}
              </dl>
            )}
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
