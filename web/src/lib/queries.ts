import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  type AssistantStreamEvent,
  type SearchParams,
  type ClusterRecord,
  type IncidentAction,
  getAssistantConversation,
  getCluster,
  getClusterHistory,
  listClusters,
  searchLogs,
  searchAggregations,
  getSystemHealth,
  sendAssistantMessage,
  streamAssistantMessage,
  updateIncident,
} from "./api";
import { ApiError } from "./api-base";

export function useClusters(since?: string, refetchIntervalMs: number | false = 30_000) {
  // Khong loc `status` o day: Dashboard can danh sach DAY DU trong khoang
  // thoi gian de tinh dung so dem facet theo tung status (StatusFacets),
  // loc hien thi lam o phia component goi (client-side, du lieu nho).
  return useQuery({
    queryKey: ["clusters", since],
    queryFn: ({ signal }) => listClusters({ since }, signal),
    refetchInterval: refetchIntervalMs, // du lieu "song" - cum co the doi status/score giua cac lan clustering chay
  });
}

export function useCluster(clusterId: string | undefined, logsLimit?: number) {
  return useQuery({
    // logsLimit nam trong queryKey: doi so log can tai thi phai fetch lai,
    // khong duoc dung lai cache cua trang nho hon.
    queryKey: ["cluster", clusterId, logsLimit],
    queryFn: ({ signal }) => getCluster(clusterId as string, { logsLimit }, signal),
    enabled: Boolean(clusterId),
  });
}

export function useClusterHistory(clusterId: string | undefined) {
  return useQuery({
    queryKey: ["cluster-history", clusterId],
    queryFn: ({ signal }) => getClusterHistory(clusterId as string, signal),
    enabled: Boolean(clusterId),
  });
}

export function useUpdateIncident(clusterId: string) {
  const queryClient = useQueryClient();
  const queryKey = ["cluster", clusterId];
  return useMutation({
    mutationFn: (change: IncidentAction) => updateIncident(clusterId, change),
    onSuccess: async (incident) => {
      await queryClient.cancelQueries({ queryKey });
      queryClient.setQueriesData<ClusterRecord>({ queryKey }, (cluster) =>
        cluster ? { ...cluster, incident } : cluster,
      );
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409) {
        void queryClient.invalidateQueries({ queryKey });
      }
    },
  });
}

export function useSearchLogs(params: SearchParams, enabled: boolean) {
  return useQuery({
    queryKey: ["search", params],
    queryFn: ({ signal }) => searchLogs(params, signal),
    enabled,
  });
}

export function useSearchAggregations(params: SearchParams, enabled: boolean) {
  return useQuery({
    queryKey: ["search-aggregations", params],
    queryFn: ({ signal }) => searchAggregations(params, signal),
    enabled,
  });
}

export const SYSTEM_HEALTH_QUERY_KEY = ["system-health"] as const;

export function useSystemHealth() {
  return useQuery({
    queryKey: SYSTEM_HEALTH_QUERY_KEY,
    queryFn: ({ signal }) => getSystemHealth(signal),
    refetchInterval: 15_000,
    retry: false,
  });
}

export function useAssistantConversation(clusterId: string | undefined) {
  return useQuery({
    queryKey: ["assistant-conversation", clusterId],
    queryFn: ({ signal }) => getAssistantConversation(clusterId as string, signal),
    enabled: Boolean(clusterId),
  });
}

// `onEvent` co thi dung ban streaming (chu hien dan tung doan); khong co thi
// giu nguyen ban JSON cu - cung mot endpoint, xem api.ts.
export function useSendAssistantMessage(
  clusterId: string, onEvent?: (event: AssistantStreamEvent) => void,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ message, signal }: { message: string; signal?: AbortSignal }) =>
      onEvent
        ? streamAssistantMessage(clusterId, message, onEvent, signal)
        : sendAssistantMessage(clusterId, message, signal),
    // Ghi thang vao cache thay vi invalidate+refetch: response da la TOAN BO
    // hoi thoai moi nhat (xem api-contract.md), khong can goi lai GET.
    onSuccess: (conversation) => {
      queryClient.setQueryData(["assistant-conversation", clusterId], conversation);
    },
  });
}
