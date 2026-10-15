import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import type { Node } from "../../api/types.js";

// Mock @xyflow/react Handle + Position — they need a React Flow internal
// context that we don't want to set up in unit tests.
vi.mock("@xyflow/react", () => ({
  Handle: () => null,
  Position: { Top: "top", Bottom: "bottom" },
  // useStore drives the level-of-detail chip; feed it zoom=1 so the full card
  // renders (lod=false) for these unit tests.
  useStore: (selector: (s: { transform: number[] }) => unknown) =>
    selector({ transform: [0, 0, 1] }),
}));

// MultiSelectContext is from GraphCanvas — mock to avoid pulling in the whole canvas.
vi.mock("./GraphCanvas", () => ({
  MultiSelectContext: {
    // React.createContext returns an object with a Provider and _currentValue;
    // we replicate the minimal shape so useContext(MultiSelectContext) works.
    _currentValue: new Set<string>(),
    Provider: ({ children }: { children: React.ReactNode }) => children,
  },
}));

// MarkdownRenderer – keep tests lean, no markdown parsing.
vi.mock("../shared/MarkdownRenderer", () => ({
  MarkdownRenderer: ({ content }: { content: string }) => (
    <div data-testid="markdown">{content}</div>
  ),
}));

// ArtifactImage – not under test here.
vi.mock("../artifacts/ArtifactImage", () => ({
  ArtifactImage: () => null,
}));

import { ResearchNodeCard } from "./ResearchNodeCard.js";

function makeNode(overrides: Partial<Node> = {}): Node {
  return {
    node_id: "n-1",
    slug_name: null,
    title: "Test Node",
    summary: null,
    content: null,
    updated_by: null,
    kind: "insight",
    lifecycle: "committed",
    outcome: null,
    hypothesis: null,
    no_artifacts_reason: null,
    insights: [],
    parent_ids: [],
    child_ids: [],
    repo_url: null,
    branch_name: null,
    head_commit_sha: null,
    origin_host: null,
    external_transcript_ref: null,
    revision: 1,
    graph_tags: [],
    tag_ids: [],
    tag_history: [],
    artifacts: [],
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

// ResearchNodeCard is a React Flow custom node; it receives `data` + `selected`
// as top-level props. Render it directly – no ReactFlowProvider needed since
// we mock Handle above.
function renderCard(
  nodeOverrides: Partial<Node> = {},
  extra: Record<string, unknown> = {},
  selected = false,
) {
  const node = makeNode(nodeOverrides);
  return render(
    <ResearchNodeCard
      data={{ node, ...extra }}
      selected={selected}
      // Minimal stub props that React Flow injects into custom node components.
      id="n-1"
      type="research-node"
      dragging={false}
      isConnectable={false}
      zIndex={0}
      positionAbsoluteX={0}
      positionAbsoluteY={0}
      selectable={true}
      deletable={true}
      draggable={false}
    />,
  );
}

describe("ResearchNodeCard – hover status badge (Task 14)", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  it("shows 'error' badge on hover when outcome is 'failed'", () => {
    const { container } = renderCard({ outcome: "failed" });
    const card = container.querySelector(".rn") as HTMLElement;
    fireEvent.mouseEnter(card);
    expect(screen.getByTestId("status-badge")).toHaveTextContent("error");
  });

  it("shows 'success' badge on hover when outcome is 'completed'", () => {
    const { container } = renderCard(
      { outcome: "completed" },
    );
    const card = container.querySelector(".rn") as HTMLElement;
    fireEvent.mouseEnter(card);
    expect(screen.getByTestId("status-badge")).toHaveTextContent("success");
  });

  it("shows NO badge on hover for idle node (no running, no outcome)", () => {
    const { container } = renderCard();
    const card = container.querySelector(".rn") as HTMLElement;
    fireEvent.mouseEnter(card);
    expect(screen.queryByTestId("status-badge")).not.toBeInTheDocument();
  });

});
