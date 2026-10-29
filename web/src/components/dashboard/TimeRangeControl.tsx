import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";

export const TIME_RANGES = {
  "15m": { label: "15 phút qua", seconds: 15 * 60 },
  "1h": { label: "1 giờ qua", seconds: 60 * 60 },
  "6h": { label: "6 giờ qua", seconds: 6 * 60 * 60 },
  "24h": { label: "24 giờ qua", seconds: 24 * 60 * 60 },
  "7d": { label: "7 ngày qua", seconds: 7 * 24 * 60 * 60 },
} as const;

export type TimeRangeKey = keyof typeof TIME_RANGES;

export function sinceFromRange(range: TimeRangeKey): string {
  return new Date(Date.now() - TIME_RANGES[range].seconds * 1000).toISOString();
}

const AUTO_REFRESH_OPTIONS: { value: string; label: string; ms: number | false }[] = [
  { value: "off", label: "Tắt", ms: false },
  { value: "10s", label: "10 giây", ms: 10_000 },
  { value: "30s", label: "30 giây", ms: 30_000 },
  { value: "1m", label: "1 phút", ms: 60_000 },
];

export function TimeRangeControl({
  range, onRangeChange, autoRefreshMs, onAutoRefreshChange, onRefresh, isFetching,
}: {
  range: TimeRangeKey;
  onRangeChange: (range: TimeRangeKey) => void;
  autoRefreshMs: number | false;
  onAutoRefreshChange: (ms: number | false) => void;
  onRefresh: () => void;
  isFetching: boolean;
}) {
  const current = AUTO_REFRESH_OPTIONS.find((o) => o.ms === autoRefreshMs) ?? AUTO_REFRESH_OPTIONS[2];

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Select value={range} onValueChange={(v) => onRangeChange(v as TimeRangeKey)}>
        <SelectTrigger size="sm" className="w-36" aria-label="Khoảng thời gian">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {Object.entries(TIME_RANGES).map(([key, r]) => (
            <SelectItem key={key} value={key}>{r.label}</SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Select
        value={current.value}
        onValueChange={(v) => {
          const found = AUTO_REFRESH_OPTIONS.find((o) => o.value === v);
          if (found) onAutoRefreshChange(found.ms);
        }}
      >
        <SelectTrigger size="sm" className="w-40" aria-label="Tự động làm mới">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {AUTO_REFRESH_OPTIONS.map((o) => (
            <SelectItem key={o.value} value={o.value}>Tự làm mới: {o.label}</SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Button
        variant="outline"
        size="sm"
        onClick={onRefresh}
        disabled={isFetching}
        aria-label="Làm mới ngay"
      >
        <RefreshCw className={isFetching ? "h-3.5 w-3.5 animate-spin" : "h-3.5 w-3.5"} />
      </Button>
    </div>
  );
}
