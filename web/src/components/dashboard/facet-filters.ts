import type { ClusterRecord, ClusterStatus } from "@/lib/api";

// ClusterRecord.service la optional trong contract (cum cu ghi truoc khi them
// field nay van con trong index) - gom chung vao mot nhan de facet khong bo sot.
export const UNKNOWN_SERVICE = "unknown";

export function serviceOf(cluster: ClusterRecord): string {
  return cluster.service || UNKNOWN_SERVICE;
}

export function matchesStatus(cluster: ClusterRecord, status: ClusterStatus | "all"): boolean {
  return status === "all" || cluster.status === status;
}

export function matchesService(cluster: ClusterRecord, service: string | "all"): boolean {
  return service === "all" || serviceOf(cluster) === service;
}

export interface CrossFiltered {
  /** Danh sach hien thi: thoa CA HAI facet. */
  grid: ClusterRecord[];
  /** Dem cho facet Status: da loc theo Service dang chon (khong loc theo Status). */
  forStatusFacets: ClusterRecord[];
  /** Dem cho facet Service: da loc theo Status dang chon (khong loc theo Service). */
  forServiceFacets: ClusterRecord[];
}

/** Cross-filter kieu Datadog: moi facet dem tren tap da loc boi facet KIA,
 * nhung khong tu loc chinh no - neu khong, facet dang chon luon hien dung
 * tong cua no va cac lua chon con lai deu ve 0. */
export function crossFilterClusters(
  clusters: ClusterRecord[],
  status: ClusterStatus | "all",
  service: string | "all",
): CrossFiltered {
  const forStatusFacets = clusters.filter((c) => matchesService(c, service));
  const forServiceFacets = clusters.filter((c) => matchesStatus(c, status));
  return {
    grid: forStatusFacets.filter((c) => matchesStatus(c, status)),
    forStatusFacets,
    forServiceFacets,
  };
}
