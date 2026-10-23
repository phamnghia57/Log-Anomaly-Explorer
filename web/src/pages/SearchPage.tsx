import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import type { SearchParams } from "@/lib/api";
import { useSearchLogs } from "@/lib/queries";
import { AppShell } from "@/components/layout/AppShell";
import { SearchForm, type SearchFormValues } from "@/components/SearchForm";
import { LogTable } from "@/components/LogTable";
import { Skeleton } from "@/components/ui/skeleton";

export function SearchPage() {
  const [urlParams, setUrlParams] = useSearchParams();
  const traceIdFromUrl = urlParams.get("trace_id") ?? undefined;

  const [params, setParams] = useState<SearchParams>({ trace_id: traceIdFromUrl });
  const [hasSearched, setHasSearched] = useState(Boolean(traceIdFromUrl));

  useEffect(() => {
    if (traceIdFromUrl) {
      setParams({ trace_id: traceIdFromUrl });
      setHasSearched(true);
    }
  }, [traceIdFromUrl]);

  const { data, isFetching, isError, error } = useSearchLogs(params, hasSearched);

  const runSearch = (values: SearchFormValues) => {
    setParams(values);
    setHasSearched(true);
    setUrlParams(values.trace_id ? { trace_id: values.trace_id } : {});
  };

  return (
    <AppShell title="Search log">
      <div className="space-y-6">
        <div className="rounded-xl border bg-card p-4">
          {/* key = traceIdFromUrl: remount form de dong bo lai input khi trace_id
              tren URL doi (vd. bam trace trong ket qua search ngay tren trang nay) -
              react-hook-form chi ap dung defaultValues luc mount, khong tu dong
              cap nhat khi props doi neu khong co key. */}
          <SearchForm key={traceIdFromUrl ?? "empty"} defaultValues={{ trace_id: traceIdFromUrl }} onSubmit={runSearch} />
        </div>

        {isError && (
          <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
            {error instanceof Error ? error.message : "Tìm kiếm thất bại."}
          </div>
        )}

        {isFetching && (
          <div className="space-y-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-11" />
            ))}
          </div>
        )}

        {!isFetching && data && (
          <>
            <p className="text-xs text-muted-foreground">{data.total} kết quả</p>
            <LogTable logs={data.results} onTraceClick={(traceId) => setUrlParams({ trace_id: traceId })} />
          </>
        )}

        {!hasSearched && !isFetching && (
          <div className="rounded-lg border border-dashed p-10 text-center text-sm text-muted-foreground">
            Nhập điều kiện rồi bấm Tìm kiếm — mặc định không có từ khoá sẽ trả về log 24h gần nhất.
          </div>
        )}
      </div>
    </AppShell>
  );
}
