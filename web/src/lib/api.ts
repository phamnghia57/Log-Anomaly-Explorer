// Client cho Query & Incident API (query-api, Nghia). Hop dong du lieu xem
// docs/architect/contracts/api-contract.md, log-schema.json, cluster-record.schema.json.
//
// Frontend (web/, deploy Vercel) va backend (query-api, deploy rieng - xem
// docs/task/deployment.md) la 2 noi deploy khac nhau, nen base URL luon cau
// hinh qua bien moi truong (VITE_API_BASE_URL), khong hardcode.

export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined)
  ?.replace(/\/$/, "") || "http://localhost:9002";

// Jaeger UI (xem docker-compose.yml muc "jaeger") - rong = khong hien lien
// ket trace (vd. moi truong chua trien khai Jaeger).
const JAEGER_URL = (import.meta.env.VITE_JAEGER_URL as string | undefined)?.replace(/\/$/, "");

// trace_id trong log-schema.json la hex 32 ky tu (128-bit, dung chuan
// W3C Trace Context) - dung duoc thang lam duong dan /trace/{id} cua Jaeger
// UI ma khong can chuyen dinh dang.
export function getJaegerTraceUrl(traceId: string): string | null {
  if (!JAEGER_URL || !traceId) return null;
  return `${JAEGER_URL}/trace/${encodeURIComponent(traceId)}`;
}

export type LogLevel = "DEBUG" | "INFO" | "WARN" | "ERROR" | "FATAL";

// StructuredLog - docs/architect/contracts/log-schema.json
export interface StructuredLog {
  log_id?: string;
  timestamp: string;
  level: LogLevel;
  service: string;
  trace_id: string;
  span_id: string;
  request_id?: string;
  message: string;
  stack_trace?: string | null;
  metadata?: Record<string, unknown>;
}

export type ClusterStatus = "normal" | "anomalous" | "alerted";

// ClusterRecord - docs/architect/contracts/cluster-record.schema.json
// (+ "logs" duoc query-api dien them o GET /clusters/{id}, xem api-contract.md)
export interface ClusterRecord {
  cluster_id: string;
  signature?: string;
  score: number;
  log_ids?: string[];
  trace_ids: string[];
  first_seen: string;
  last_seen: string;
  status: ClusterStatus;
  logs?: StructuredLog[];
  // Tong so log_ids cua cum, khong bi cat boi logs_limit - de biet con bao
  // nhieu log chua tai (GET /clusters/{id} phan trang `logs`).
  logs_total?: number;
}

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

async function getJson<T>(path: string, params?: Record<string, string | undefined>): Promise<T> {
  const url = new URL(`${API_BASE_URL}${path}`);
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value) url.searchParams.set(key, value);
  }

  let res: Response;
  try {
    res = await fetch(url.toString());
  } catch {
    throw new ApiError(
      `Khong ket noi duoc toi API (${API_BASE_URL}). Kiem tra VITE_API_BASE_URL va backend co dang chay khong.`,
      0,
    );
  }
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new ApiError(body || `API tra ve loi ${res.status}`, res.status);
  }
  return (await res.json()) as T;
}

export interface SearchParams {
  from?: string;
  to?: string;
  service?: string;
  trace_id?: string;
  q?: string;
  [key: string]: string | undefined;
}

export function searchLogs(params: SearchParams) {
  return getJson<{ total: number; results: StructuredLog[] }>("/search", params);
}

export function listClusters(params: { status?: ClusterStatus | ""; since?: string }) {
  return getJson<{ total: number; clusters: ClusterRecord[] }>("/clusters", {
    status: params.status || undefined,
    since: params.since,
  });
}

export function getCluster(clusterId: string, params?: { logsLimit?: number; logsOffset?: number }) {
  return getJson<ClusterRecord>(`/clusters/${encodeURIComponent(clusterId)}`, {
    logs_limit: params?.logsLimit?.toString(),
    logs_offset: params?.logsOffset?.toString(),
  });
}

// ClusterHistoryPoint - docs/architect/contracts/cluster-history-schema.json
// (xu huong anomaly score theo thoi gian cua 1 cum, khac ClusterRecord.score
// o tren - chi 1 diem hien tai). points co the rong: cum ton tai nhung
// clustering chua ghi history.
export interface ClusterHistoryPoint {
  cluster_id: string;
  score: number;
  status: ClusterStatus;
  recorded_at: string;
}

export function getClusterHistory(clusterId: string) {
  return getJson<{ cluster_id: string; points: ClusterHistoryPoint[] }>(
    `/clusters/${encodeURIComponent(clusterId)}/history`,
  );
}
