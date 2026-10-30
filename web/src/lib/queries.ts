import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  type SearchParams,
  getAssistantConversation,
  getCluster,
  getClusterHistory,
  listClusters,
  searchLogs,
  sendAssistantMessage,
} from "./api";

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

export function useSearchLogs(params: SearchParams, enabled: boolean) {
  return useQuery({
    queryKey: ["search", params],
    queryFn: ({ signal }) => searchLogs(params, signal),
    enabled,
  });
}

export function useAssistantConversation(clusterId: string | undefined) {
  return useQuery({
    queryKey: ["assistant-conversation", clusterId],
    queryFn: ({ signal }) => getAssistantConversation(clusterId as string, signal),
    enabled: Boolean(clusterId),
  });
}

export function useSendAssistantMessage(clusterId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ message, signal }: { message: string; signal?: AbortSignal }) =>
      sendAssistantMessage(clusterId, message, signal),
    // Ghi thang vao cache thay vi invalidate+refetch: response da la TOAN BO
    // hoi thoai moi nhat (xem api-contract.md), khong can goi lai GET.
    onSuccess: (conversation) => {
      queryClient.setQueryData(["assistant-conversation", clusterId], conversation);
    },
  });
}
