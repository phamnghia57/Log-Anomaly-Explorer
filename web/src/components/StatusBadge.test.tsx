import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ClusterStatusBadge, LevelTag } from "./StatusBadge";

describe("ClusterStatusBadge", () => {
  it.each([
    ["normal", "Normal"],
    ["anomalous", "Anomalous"],
    ["alerted", "Alerted"],
  ] as const)("hien dung nhan cho status=%s", (status, label) => {
    render(<ClusterStatusBadge status={status} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });
});

describe("LevelTag", () => {
  it("hien dung text level", () => {
    render(<LevelTag level="ERROR" />);
    expect(screen.getByText("ERROR")).toBeInTheDocument();
  });
});
