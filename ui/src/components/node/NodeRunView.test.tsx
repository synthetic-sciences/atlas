import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

const mockFetchArtifactText = vi.fn<() => Promise<string | null>>();

vi.mock("../../lib/artifactContent", () => ({
  fetchArtifactText: () => mockFetchArtifactText(),
}));

vi.mock("../shared/MarkdownRenderer", () => ({
  MarkdownRenderer: () => null,
}));

import { NodeRunView } from "./NodeRunView.js";

beforeEach(() => {
  mockFetchArtifactText.mockReset().mockResolvedValue("result body");
});

const RESULT_ARTIFACT = {
  artifact_id: "a1",
  artifact_type: "text" as const,
  title: "results.md",
  note: null,
  payload: null,
  metadata: {},
  execution_id: null,
  storage_path: "/tmp/results.md",
  created_at: "2026-01-01T00:00:00Z",
};

describe("NodeRunView artifacts", () => {
  it("resolves an artifact body once and not on unrelated re-renders", async () => {
    const artifacts = [RESULT_ARTIFACT];
    const { rerender } = render(
      <NodeRunView kind="empirical" outcome="completed" staged artifacts={artifacts} details={null} />,
    );
    await waitFor(() => expect(mockFetchArtifactText).toHaveBeenCalledTimes(1));
    rerender(
      <NodeRunView kind="empirical" outcome="completed" staged artifacts={artifacts} details={<span>x</span>} />,
    );
    // give any stray effect a tick
    await new Promise((r) => setTimeout(r, 0));
    expect(mockFetchArtifactText).toHaveBeenCalledTimes(1);
  });
});
