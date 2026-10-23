import { useQuery } from "@tanstack/react-query";
import { type ClusterStatus, type SearchParams, getCluster, listClusters, searchLogs } from "./api";

export function useClusters(status: ClusterStatus | "") {
  return useQuery({
    queryKey: ["clusters", status],
    queryFn: () => listClusters({ status }),
    refetchInterval: 30_000, // du lieu "song" - cum co the doi status/score giua cac lan clustering chay
  });
}

export function useCluster(clusterId: string | undefined) {
  return useQuery({
    queryKey: ["cluster", clusterId],
    queryFn: () => getCluster(clusterId as string),
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
