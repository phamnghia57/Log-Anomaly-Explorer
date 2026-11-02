import type { SearchFacets as Facets } from "@/lib/api";

function formatTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("vi-VN", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export function SearchFacets({ facets, selectedLevel, selectedService, onLevel, onService }: {
  facets: Facets;
  selectedLevel?: string;
  selectedService?: string;
  onLevel: (value?: string) => void;
  onService: (value?: string) => void;
}) {
  const values = facets.timeline ?? [];
  const max = Math.max(1, ...values.map((p) => p.doc_count));
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(220px,1fr)]">
      <section className="min-w-0 rounded-xl border bg-card p-4" aria-label="Biểu đồ phân bố log theo thời gian">
        <h2 className="mb-3 text-sm font-semibold">Phân bố log theo thời gian</h2>
        {values.length ? (
          <>
            <div className="flex h-36 items-end gap-px overflow-x-auto border-b pb-1" role="img" aria-label="Histogram số log theo giờ hoặc ngày">
              {values.map((point) => (
                <div key={point.key_as_string} className="group flex h-full min-w-[3px] flex-1 items-end" title={`${formatTime(point.key_as_string)}: ${point.doc_count} log`}>
                  <div className="w-full rounded-t-sm bg-primary/70 transition-colors group-hover:bg-primary"
                    style={{ height: `${Math.max(point.doc_count ? 4 : 0, (point.doc_count / max) * 100)}%` }} />
                </div>
              ))}
            </div>
            <div className="mt-2 flex justify-between gap-2 text-xs text-muted-foreground">
              <span>{formatTime(values[0].key_as_string)}</span>
              <span>{formatTime(values[values.length - 1].key_as_string)}</span>
            </div>
          </>
        ) : <p className="text-sm text-muted-foreground">Không có dữ liệu trong khoảng thời gian này.</p>}
      </section>
      <section className="space-y-4 rounded-xl border bg-card p-4">
        <div>
          <h2 className="mb-2 text-sm font-semibold">Theo mức độ</h2>
          <div className="flex flex-wrap gap-2">
            {(facets.levels ?? []).map((item) => (
              <button key={item.key} type="button" aria-pressed={selectedLevel === item.key}
                className={`rounded-md border px-2 py-1 text-xs hover:bg-accent ${selectedLevel === item.key ? "border-primary bg-accent font-semibold" : ""}`}
                onClick={() => onLevel(selectedLevel === item.key ? undefined : item.key)}>
                {item.key} · {item.doc_count}
              </button>
            ))}
          </div>
        </div>
        <div>
          <h2 className="mb-2 text-sm font-semibold">Theo service</h2>
          <div className="flex flex-wrap gap-2">
            {(facets.services ?? []).map((item) => (
              <button key={item.key} type="button" aria-pressed={selectedService === item.key}
                className={`rounded-md border px-2 py-1 text-xs hover:bg-accent ${selectedService === item.key ? "border-primary bg-accent font-semibold" : ""}`}
                onClick={() => onService(selectedService === item.key ? undefined : item.key)}>
                {item.key} · {item.doc_count}
              </button>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
