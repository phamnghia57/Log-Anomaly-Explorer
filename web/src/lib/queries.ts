import { useQuery } from "@tanstack/react-query";
import {
  type ClusterStatus,
  type SearchParams,
  getCluster,
  getClusterHistory,
  listClusters,
  searchLogs,
} from "./api";

export function useClusters(status: ClusterStatus | "") {
  return useQuery({
    queryKey: ["clusters", status],
    queryFn: ({ signal }) => listClusters({ status }, signal),
    refetchInterval: 30_000, // du lieu "song" - cum co the doi status/score giua cac lan clustering chay
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
