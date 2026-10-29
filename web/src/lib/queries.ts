import { useQuery } from "@tanstack/react-query";
import {
  type SearchParams,
  getCluster,
  getClusterHistory,
  listClusters,
  searchLogs,
} from "./api";

export function useClusters(since?: string, refetchIntervalMs: number | false = 30_000) {
  // Khong loc `status` o day: Dashboard can danh sach DAY DU trong khoang
  // thoi gian de tinh dung so dem facet theo tung status (StatusFacets),
  // loc hien thi lam o phia component goi (client-side, du lieu nho).
  return useQuery({
    queryKey: ["clusters", since],
    queryFn: () => listClusters({ since }),
    refetchInterval: refetchIntervalMs, // du lieu "song" - cum co the doi status/score giua cac lan clustering chay
  });
}

export function useCluster(clusterId: string | undefined, logsLimit?: number) {
  return useQuery({
    // logsLimit nam trong queryKey: doi so log can tai thi phai fetch lai,
    // khong duoc dung lai cache cua trang nho hon.
    queryKey: ["cluster", clusterId, logsLimit],
    queryFn: () => getCluster(clusterId as string, { logsLimit }),
    enabled: Boolean(clusterId),
  });
}

export function useClusterHistory(clusterId: string | undefined) {
  return useQuery({
    queryKey: ["cluster-history", clusterId],
    queryFn: () => getClusterHistory(clusterId as string),
    enabled: Boolean(clusterId),
  });
}

export function useSearchLogs(params: SearchParams, enabled: boolean) {
  return useQuery({
    queryKey: ["search", params],
    queryFn: () => searchLogs(params),
    enabled,
  });
}
