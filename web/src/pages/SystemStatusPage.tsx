import { AppShell } from "@/components/layout/AppShell";
import { useSystemHealth } from "@/lib/queries";
import { Button } from "@/components/ui/button";
import { formatDateTime } from "@/lib/format";

export function SystemStatusPage() {
  const { data, isPending, refetch } = useSystemHealth();
  return (
    <AppShell title="Trạng thái hệ thống">
      <div className="space-y-4">
        <div className="flex items-center justify-between gap-2">
          <p className="text-sm text-muted-foreground">Kiểm tra /health của từng dịch vụ, làm mới mỗi 15 giây.</p>
          <Button variant="outline" size="sm" onClick={() => { void refetch(); }}>Kiểm tra lại</Button>
        </div>
        {isPending && <p role="status">Đang kiểm tra dịch vụ…</p>}
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {data?.map((service) => (
            <div className="rounded-xl border bg-card p-4" key={service.name}>
              <div className="flex items-center justify-between gap-3">
                <h2 className="font-semibold">{service.name}</h2>
                <span aria-label={service.ok ? "Hoạt động" : "Có sự cố"} className={`flex items-center gap-2 text-sm ${service.ok ? "text-green-600" : "text-red-600"}`}>
                  <span aria-hidden className={`h-2.5 w-2.5 rounded-full ${service.ok ? "bg-green-500" : "bg-red-500"}`} />
                  {service.ok ? "Hoạt động" : "Có sự cố"}
                </span>
              </div>
              <p className="mt-3 text-xs text-muted-foreground">{service.status}</p>
              {service.lastProcessedAt && (
                <p className="mt-1 text-xs text-muted-foreground">
                  Xử lý lần cuối {formatDateTime(service.lastProcessedAt)}
                </p>
              )}
              {service.lastCallAt && <p className="mt-1 text-xs text-muted-foreground">Gọi Azure OpenAI lần cuối {formatDateTime(service.lastCallAt)}</p>}
            </div>
          ))}
        </div>
      </div>
    </AppShell>
  );
}
