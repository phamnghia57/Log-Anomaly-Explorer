import { useQuery } from "@tanstack/react-query";
import { AppShell } from "@/components/layout/AppShell";
import { API_BASE_URL } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { RefreshCw } from "lucide-react";

// Local dev: point VITE_HEALTH_BASE_URL at Vite dev server (proxy rules).
// Production: configure it to the public Caddy gateway, which exposes only /health.
const HEALTH_BASE = (import.meta.env.VITE_HEALTH_BASE_URL as string | undefined)?.replace(/\/$/, "") || API_BASE_URL;
const SERVICES = [
  { id: "query", label: "Query API", path: "/health" },
  { id: "ingestion", label: "Ingestion", path: "/health/ingestion" },
  { id: "demo", label: "Demo App", path: "/health/demo-app" },
] as const;

type Check = { ok: boolean; message: string };
async function checkHealth(path: string, signal: AbortSignal): Promise<Check> {
  try {
    const response = await fetch(`${HEALTH_BASE}${path}`, { signal, cache: "no-store", credentials: "omit" });
    if (!response.ok) return { ok: false, message: `HTTP ${response.status}` };
    const body: unknown = await response.json();
    if (!body || typeof body !== "object" || !("status" in body) || body.status !== "ok") {
      return { ok: false, message: "Trạng thái không xác định" };
    }
    return { ok: true, message: "Hoạt động" };
  } catch {
    if (signal.aborted) throw new Error("aborted");
    return { ok: false, message: "Không kết nối được (kiểm tra gateway/CORS)" };
  }
}

export function SystemStatusPage() {
  const { data, isLoading, isFetching, refetch } = useQuery({
    queryKey: ["services-health", HEALTH_BASE],
    queryFn: async ({ signal }) => Promise.all(SERVICES.map((service) => checkHealth(service.path, signal))),
    refetchInterval: 30_000,
  });
  return (
    <AppShell title="Trạng thái hệ thống">
      <div className="space-y-4">
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm text-muted-foreground">Kiểm tra trực tiếp endpoint /health (30 giây/lần). Clustering là worker, không có HTTP /health.</p>
          <Button variant="outline" size="sm" onClick={() => refetch()} disabled={isFetching}>
            <RefreshCw className="mr-2 h-4 w-4" /> Kiểm tra lại
          </Button>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {SERVICES.map((service, index) => {
            const result = data?.[index];
            return (
              <div className="rounded-xl border bg-card p-4" key={service.id}>
                <div className="mb-2 flex items-center gap-2">
                  <span role="status" aria-label={result?.ok ? "Hoạt động" : "Không hoạt động"}
                    className={`h-3 w-3 rounded-full ${!result ? "bg-muted-foreground/50" : result.ok ? "bg-emerald-500" : "bg-red-500"}`} />
                  <strong className="text-sm">{service.label}</strong>
                </div>
                <p className="text-sm text-muted-foreground">{!result && isLoading ? "Đang kiểm tra..." : result?.message ?? "Chưa có dữ liệu"}</p>
              </div>
            );
          })}
        </div>
      </div>
    </AppShell>
  );
}
