import { describe, expect, it } from "vitest";
import type { ClusterRecord } from "@/lib/api";
import { UNKNOWN_SERVICE, crossFilterClusters, serviceOf } from "./facet-filters";

function cluster(over: Partial<ClusterRecord>): ClusterRecord {
  return {
    cluster_id: "c", score: 1, trace_ids: [], first_seen: "", last_seen: "",
    status: "normal", ...over,
  } as ClusterRecord;
}

const CLUSTERS = [
  cluster({ cluster_id: "1", service: "demo-web", status: "alerted" }),
  cluster({ cluster_id: "2", service: "demo-web", status: "normal" }),
  cluster({ cluster_id: "3", service: "demo-mobile-api", status: "alerted" }),
  cluster({ cluster_id: "4", status: "anomalous" }), // khong co `service`
];

const ids = (list: ClusterRecord[]) => list.map((c) => c.cluster_id).sort();

describe("serviceOf", () => {
  it("gom cum khong co field service vao nhan 'unknown'", () => {
    expect(serviceOf(cluster({ service: "demo-web" }))).toBe("demo-web");
    expect(serviceOf(cluster({}))).toBe(UNKNOWN_SERVICE);
  });
});

describe("crossFilterClusters", () => {
  it("khong chon gi: ca 3 danh sach deu la toan bo", () => {
    const { grid, forStatusFacets, forServiceFacets } = crossFilterClusters(CLUSTERS, "all", "all");
    expect(ids(grid)).toEqual(["1", "2", "3", "4"]);
    expect(ids(forStatusFacets)).toEqual(["1", "2", "3", "4"]);
    expect(ids(forServiceFacets)).toEqual(["1", "2", "3", "4"]);
  });

  it("grid thoa CA HAI facet", () => {
    const { grid } = crossFilterClusters(CLUSTERS, "alerted", "demo-web");
    expect(ids(grid)).toEqual(["1"]);
  });

  it("facet Status dem trong pham vi Service dang chon (khong tu loc theo status)", () => {
    const { forStatusFacets } = crossFilterClusters(CLUSTERS, "alerted", "demo-web");
    // Van giu ca cum demo-web co status khac -> nguoi dung thay duoc
    // "neu bo chon alerted thi con bao nhieu cum demo-web".
    expect(ids(forStatusFacets)).toEqual(["1", "2"]);
  });

  it("facet Service dem trong pham vi Status dang chon (khong tu loc theo service)", () => {
    const { forServiceFacets } = crossFilterClusters(CLUSTERS, "alerted", "demo-web");
    expect(ids(forServiceFacets)).toEqual(["1", "3"]);
  });

  it("loc duoc theo nhan 'unknown' cho cum thieu field service", () => {
    const { grid } = crossFilterClusters(CLUSTERS, "all", UNKNOWN_SERVICE);
    expect(ids(grid)).toEqual(["4"]);
  });

  it("to hop khong con cum nao: grid rong nhung facet van con so dem de quay lai", () => {
    const { grid, forStatusFacets, forServiceFacets } =
      crossFilterClusters(CLUSTERS, "normal", "demo-mobile-api");
    expect(grid).toEqual([]);
    expect(ids(forStatusFacets)).toEqual(["3"]); // cum demo-mobile-api (alerted)
    expect(ids(forServiceFacets)).toEqual(["2"]); // cum normal (demo-web)
  });
});
