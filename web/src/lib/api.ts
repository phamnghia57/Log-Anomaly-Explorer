// Client cho Query & Incident API (query-api, Nghia). Hop dong du lieu xem
// docs/architect/contracts/api-contract.md, log-schema.json, cluster-record.schema.json.
//
// Frontend (web/, deploy Vercel) va backend (query-api, deploy rieng - xem
// docs/task/deployment.md) la 2 noi deploy khac nhau, nen base URL luon cau
// hinh qua bien moi truong (VITE_API_BASE_URL), khong hardcode.

import {
  clearSession, getSession, isAuthSession, SESSION_EXPIRED_MESSAGE, useAuthStore,
  type AuthSession,
} from "./auth";

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

export async function loginAdmin(username: string, password: string): Promise<AuthSession> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
      cache: "no-store",
    });
  } catch {
    throw new ApiError("Không kết nối được máy chủ. Vui lòng kiểm tra kết nối và thử lại.", 0);
  }
  if (!res.ok) {
    throw new ApiError(
      res.status >= 500
        ? "Dịch vụ đăng nhập tạm thời không khả dụng. Vui lòng thử lại."
        : "Đăng nhập không thành công. Vui lòng kiểm tra tên đăng nhập và mật khẩu.",
      res.status,
    );
  }
  const body: unknown = await res.json().catch(() => null);
  if (!isAuthSession(body)) {
    throw new ApiError("Không thể hoàn tất đăng nhập. Vui lòng thử lại.", 502);
  }
  return { token: body.token, expires_at: body.expires_at };
}

// Client chi nhan cac duong dan Query API, khong nhan URL tuy y/URL Jaeger.
type QueryPath = "/search" | "/clusters" | `/clusters/${string}`
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

  let res: Response;
  const session = getSession();
  if (!session) throw new ApiError(useAuthStore.getState().status === "expired"
    ? SESSION_EXPIRED_MESSAGE : "Vui lòng đăng nhập để xem dữ liệu.", 401);
  try {
    res = await fetch(url.toString(), {
      headers: { Authorization: `Bearer ${session.token}`, ...(payload ? { "Content-Type": "application/json" } : {}) },
      ...(payload ? { method: "POST", body: JSON.stringify(payload) } : {}),
      signal, cache: "no-store", credentials: "omit", redirect: "error",
    });
  } catch (cause) {
    if (signal?.aborted) throw cause;
    throw new ApiError(
      `Khong ket noi duoc toi API (${API_BASE_URL}). Kiem tra VITE_API_BASE_URL va backend co dang chay khong.`,
      0,
    );
  }
  if (res.status === 401) {
    // Response cua request cu khong duoc xoa session moi vua dang nhap.
    if (getSession()?.token === session.token) clearSession("expired");
    throw new ApiError(useAuthStore.getState().status === "expired"
      ? SESSION_EXPIRED_MESSAGE : "Vui lòng đăng nhập để xem dữ liệu.", 401);
  }
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new ApiError(body || `API tra ve loi ${res.status}`, res.status);
  }
  const body = await res.json() as T;
  // Request cu co the hoan tat sau logout/doi tai khoan; khong dua data do vao cache moi.
  if (getSession()?.token !== session.token) throw new ApiError(SESSION_EXPIRED_MESSAGE, 401);
  return body;
}

export interface SearchParams {
  from?: string;
  to?: string;
  service?: string;
  trace_id?: string;
  q?: string;
  [key: string]: string | undefined;
}

export function searchLogs(params: SearchParams, signal?: AbortSignal) {
  return queryJson<{ total: number; results: StructuredLog[] }>("/search", params, signal);
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
  clusterId: string, message: string,
): Promise<AssistantConversation> {
  return queryJson<AssistantConversation>(
    `/assistant/clusters/${encodeURIComponent(clusterId)}/conversation/messages`,
    undefined, undefined, { message },
  );
}
