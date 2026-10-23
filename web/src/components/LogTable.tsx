import { type ColumnDef, flexRender, getCoreRowModel, useReactTable } from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useMemo, useRef, useState } from "react";
import type { StructuredLog } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { LevelTag } from "@/components/StatusBadge";
import { LogDetailDialog } from "@/components/LogDetailDialog";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";

const ROW_HEIGHT = 44;

function hasDetail(log: StructuredLog): boolean {
  return Boolean(log.stack_trace || (log.metadata && Object.keys(log.metadata).length > 0));
}

const columns: ColumnDef<StructuredLog>[] = [
  {
    id: "timestamp",
    header: "Time",
    accessorFn: (row) => row.timestamp,
    cell: ({ getValue }) => (
      <span className="whitespace-nowrap font-mono text-xs text-muted-foreground">
        {formatDateTime(getValue<string>())}
      </span>
    ),
  },
  {
    id: "level",
    header: "Level",
    accessorFn: (row) => row.level,
    cell: ({ getValue }) => <LevelTag level={getValue<StructuredLog["level"]>()} />,
  },
  {
    id: "service",
    header: "Service",
    accessorFn: (row) => row.service,
  },
  {
    id: "message",
    header: "Message",
    accessorFn: (row) => row.message,
    cell: ({ row }) => (
      <span>
        {row.original.message}
        {hasDetail(row.original) && <span className="ml-2 text-xs text-muted-foreground">(xem chi tiết)</span>}
      </span>
    ),
  },
];

export function LogTable({
  logs,
  onTraceClick,
}: {
  logs: StructuredLog[];
  onTraceClick?: (traceId: string) => void;
}) {
  const [activeLog, setActiveLog] = useState<StructuredLog | null>(null);
  const parentRef = useRef<HTMLDivElement>(null);

  // Sap xep moi nhat len dau o day (khong phu thuoc thu tu API tra ve) - vi
  // Incident View dien "logs" bang cach tra log_ids (sap theo UUID, khong
  // phai thoi gian - xem clustering/src/anomaly_score.py) qua
  // LogStore.get_by_ids(), khong dam bao thu tu thoi gian. LogTable dung
  // chung cho ca Search lan Incident View nen sua 1 cho la du cho ca 2.
  const sortedLogs = useMemo(
    () => [...logs].sort((a, b) => b.timestamp.localeCompare(a.timestamp)),
    [logs],
  );

  const table = useReactTable({ data: sortedLogs, columns, getCoreRowModel: getCoreRowModel() });
  const rows = table.getRowModel().rows;

  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 10,
  });

  if (logs.length === 0) {
    return (
      <div className="rounded-lg border border-dashed p-10 text-center text-sm text-muted-foreground">
        Không có log nào khớp.
      </div>
    );
  }

  const virtualItems = virtualizer.getVirtualItems();

  return (
    <div className="overflow-hidden rounded-lg border">
      <div ref={parentRef} className="max-h-[560px] overflow-auto">
        <Table>
          <TableHeader className="sticky top-0 z-10 bg-background">
            {table.getHeaderGroups().map((hg) => (
              <TableRow key={hg.id}>
                {hg.headers.map((header) => (
                  <TableHead key={header.id}>
                    {flexRender(header.column.columnDef.header, header.getContext())}
                  </TableHead>
                ))}
                <TableHead className="w-32">Trace</TableHead>
              </TableRow>
            ))}
          </TableHeader>
          <TableBody style={{ height: virtualizer.getTotalSize(), position: "relative", display: "block" }}>
            {virtualItems.map((vRow) => {
              const row = rows[vRow.index];
              return (
                <TableRow
                  key={row.id}
                  data-index={vRow.index}
                  ref={virtualizer.measureElement}
                  style={{ position: "absolute", top: 0, left: 0, width: "100%", transform: `translateY(${vRow.start}px)` }}
                  className={hasDetail(row.original) ? "cursor-pointer" : ""}
                  onClick={() => hasDetail(row.original) && setActiveLog(row.original)}
                >
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>
                  ))}
                  <TableCell>
                    <Button
                      variant="link"
                      size="sm"
                      className="h-auto p-0 font-mono text-xs"
                      onClick={(e) => {
                        e.stopPropagation();
                        onTraceClick?.(row.original.trace_id);
                      }}
                    >
                      {row.original.trace_id.slice(0, 12)}
                    </Button>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
      <div className="border-t bg-muted/40 px-3 py-1.5 text-xs text-muted-foreground">{logs.length} log</div>
      <LogDetailDialog log={activeLog} open={activeLog !== null} onOpenChange={(o) => !o && setActiveLog(null)} />
    </div>
  );
}
