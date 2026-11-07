// Client cho Query & Incident API (query-api, Nghia). Hop dong du lieu xem
// docs/architect/contracts/api-contract.md, log-schema.json, cluster-record.schema.json.
//
// Frontend (web/, deploy Vercel) va backend (query-api, deploy rieng - xem
// docs/task/deployment.md) la 2 noi deploy khac nhau, nen base URL luon cau
// hinh qua bien moi truong (VITE_API_BASE_URL), khong hardcode.

import {
  authGeneration, clearSession, getSession, loginSession, refreshSession,
  SESSION_EXPIRED_MESSAGE, useAuthStore,
} from "./auth";
import { API_BASE_URL, ApiError } from "./api-base";
export { API_BASE_URL, ApiError } from "./api-base";


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
  service?: string;
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

export const loginAdmin = loginSession;

// Client chi nhan cac duong dan Query API, khong nhan URL tuy y/URL Jaeger.
type QueryPath = "/search" | "/search/aggregations" | "/clusters" | `/clusters/${string}`
  | `/assistant/clusters/${string}/conversation` | `/assistant/clusters/${string}/conversation/messages`;

async function queryJson<T>(path: QueryPath, params?: Record<string, string | undefined>, signal?: AbortSignal, payload?: Record<string, unknown>): Promise<T> {
  const url = new URL(`${API_BASE_URL}${path}`);
  const base = new URL(API_BASE_URL);
  // Khong cho dot-segment trong ID thoat ra endpoint/base path da cau hinh.
  if (url.origin !== base.origin || url.pathname !== `${base.pathname.replace(/\/$/, "")}${path}`) {
    throw new ApiError("Đường dẫn Query API không hợp lệ.", 400);
  }
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value) url.searchParams.set(key, value);
  }

  const generation = authGeneration();
  let session = getSession();
  if (!session) throw new ApiError(useAuthStore.getState().status === "expired"
    ? SESSION_EXPIRED_MESSAGE : "Vui lòng đăng nhập để xem dữ liệu.", 401);
  if (Date.parse(session.expires_at) <= Date.now()) session = await refreshSession();
  let res!: Response;
  for (let attempt = 0; attempt < 2; attempt++) {
    if (signal?.aborted) throw signal.reason;
    if (generation !== authGeneration()) throw new ApiError(SESSION_EXPIRED_MESSAGE, 401);
    try {
      res = await fetch(url.toString(), {
        headers: { Authorization: `Bearer ${session.token}`, ...(payload ? { "Content-Type": "application/json" } : {}) },
        ...(payload ? { method: "POST", body: JSON.stringify(payload) } : {}),
        signal, cache: "no-store", credentials: "omit", redirect: "error",
      });
    } catch (cause) {
      if (signal?.aborted) throw cause;
      throw new ApiError("Không kết nối được tới API. Vui lòng thử lại.", 0);
    }
    if (generation !== authGeneration()) throw new ApiError(SESSION_EXPIRED_MESSAGE, 401);
    if (res.status !== 401) break;
    if (attempt === 0 && res.headers.get("X-Auth-Reason") === "access_expired") {
      const latest = getSession();
      session = latest && latest.token !== session.token ? latest : await refreshSession(true);
      continue;
    }
    clearSession("expired");
    throw new ApiError(SESSION_EXPIRED_MESSAGE, 401);
  }
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new ApiError(body || `API tra ve loi ${res.status}`, res.status);
  }
  const body = await res.json() as T;
  // Request cu co the hoan tat sau logout/doi tai khoan; khong dua data do vao cache moi.
  if (generation !== authGeneration()) throw new ApiError(SESSION_EXPIRED_MESSAGE, 401);
  return body;
}

export interface SearchParams {
  from?: string;
  to?: string;
  service?: string;
  trace_id?: string;
  level?: LogLevel | "";
  q?: string;
  [key: string]: string | undefined;
}

export function searchLogs(params: SearchParams, signal?: AbortSignal) {
  return queryJson<{ total: number; results: StructuredLog[] }>("/search", params, signal);
}

export interface SearchAggregations {
  histogram: Array<{ time: string; count: number }>;
  levels: Array<{ key: LogLevel; count: number }>;
  services: Array<{ key: string; count: number }>;
}

export function searchAggregations(params: SearchParams, signal?: AbortSignal) {
  return queryJson<SearchAggregations>("/search/aggregations", params, signal);
}

export type ServiceHealth = { name: string; ok: boolean; status: string };

// Cac service co /health rieng. Khi deploy Vercel, health URL can tro ve
// Caddy gateway HTTPS (xem deploy/Caddyfile), khong truy cap Docker host noi bo.
export const HEALTH_ENDPOINTS = [
  { name: "Query API", url: `${API_BASE_URL}/health` },
  { name: "Ingestion", url: import.meta.env.VITE_INGESTION_HEALTH_URL || `${API_BASE_URL}/ingestion/health` },
  { name: "Demo App", url: import.meta.env.VITE_DEMO_HEALTH_URL || `${API_BASE_URL}/demo/health` },
];

export async function getSystemHealth(signal?: AbortSignal): Promise<ServiceHealth[]> {
  return Promise.all(HEALTH_ENDPOINTS.map(async ({ name, url }) => {
    try {
      const response = await fetch(url, { signal, cache: "no-store" });
      if (!response.ok) return { name, ok: false, status: `HTTP ${response.status}` };
      const body = await response.json() as { status?: string };
      return { name, ok: body.status === "ok", status: body.status ?? "unknown" };
    } catch {
      return { name, ok: false, status: "unreachable" };
    }
  }));
}

export function listClusters(params: { status?: ClusterStatus | ""; since?: string }, signal?: AbortSignal) {
  return queryJson<{ total: number; clusters: ClusterRecord[] }>("/clusters", {
    status: params.status || undefined,
    since: params.since,
  }, signal);
}

export function getCluster(clusterId: string, params?: { logsLimit?: number; logsOffset?: number }, signal?: AbortSignal) {
  return queryJson<ClusterRecord>(`/clusters/${encodeURIComponent(clusterId)}`, {
    logs_limit: params?.logsLimit?.toString(),
    logs_offset: params?.logsOffset?.toString(),
  }, signal);
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

export function getClusterHistory(clusterId: string, signal?: AbortSignal) {
  return queryJson<{ cluster_id: string; points: ClusterHistoryPoint[] }>(
    `/clusters/${encodeURIComponent(clusterId)}/history`,
    undefined, signal,
  );
}

// AssistantMessage - docs/architect/contracts/assistant-conversation-schema.json.
// role="tool" chi xuat hien khi AI tu goi tool de dieu tra truoc khi tra loi -
// UI nen hien thi khac voi tin nhan user/assistant (vd. dong "dang tra cuu...").
export type AssistantRole = "user" | "assistant" | "tool";

export interface AssistantToolCall {
  id: string;
  name: string;
  arguments: string;
}

export interface AssistantMessage {
  role: AssistantRole;
  content: string | null;
  created_at: string;
  tool_calls?: AssistantToolCall[];
  tool_call_id?: string;
  name?: string;
}

export interface AssistantConversation {
  cluster_id: string;
  messages: AssistantMessage[];
}

export function getAssistantConversation(clusterId: string, signal?: AbortSignal) {
  return queryJson<AssistantConversation>(
    `/assistant/clusters/${encodeURIComponent(clusterId)}/conversation`,
    undefined, signal,
  );
}

export function sendAssistantMessage(
  clusterId: string, message: string, signal?: AbortSignal,
): Promise<AssistantConversation> {
  return queryJson<AssistantConversation>(
    `/assistant/clusters/${encodeURIComponent(clusterId)}/conversation/messages`,
    undefined, signal, { message },
  );
}
