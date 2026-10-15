import { describe, it, expect } from "vitest";
import { renderHook } from "@testing-library/react";
import { useGraphLayout } from "./useGraphLayout";
import type { Node, NodeTreeResponse } from "../../api/types";

function mk(id: string, over: Partial<Node>): Node {
  return {
    node_id: id,
    slug_name: id,
    title: id,
    summary: null,
    content: null,
    updated_by: null,
    kind: "empirical",
    lifecycle: "committed",
    outcome: "completed",
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
    semantic_data: null,
    created_at: "2026-03-14T00:00:00Z",
    updated_at: "2026-03-14T00:00:00Z",
    ...over,
  };
}

function run(id: string, bpb: number, day: number, parent = "root"): Node {
  const at = new Date(Date.parse("2026-03-14T00:00:00Z") + day * 86_400_000).toISOString();
  return mk(id, {
    kind: "empirical",
    parent_ids: [parent],
    created_at: at,
    semantic_data: { metrics: { val_bpb: bpb }, config: { achieved_at: at } },
  });
}

function tree(nodes: Node[]): NodeTreeResponse {
  const byId = new Map(nodes.map((n) => [n.node_id, n]));
  for (const n of nodes) for (const p of n.parent_ids) byId.get(p)?.child_ids.push(n.node_id);
  return { anchor_node_id: nodes[0].node_id, root_node_ids: [nodes[0].node_id], nodes, node_count: nodes.length };
}

describe("useGraphLayout progression", () => {
  it("lays scored runs out as a score curve with the best (lowest val_bpb) at the top", () => {
    const nodes = [
      mk("root", { kind: "insight", parent_ids: [] }),
      run("worst", 0.95, 1),
      run("mid", 0.93, 10),
      run("best", 0.91, 20),
      mk("decide", { kind: "decision", parent_ids: ["root"], semantic_data: null }),
    ];
    const { result } = renderHook(() => useGraphLayout(tree(nodes), "cards"));
    const pos = new Map(result.current.nodes.map((n) => [n.id, n.position]));

    // best (lowest val_bpb) sits above mid, which sits above worst.
    expect(pos.get("best")!.y).toBeLessThan(pos.get("mid")!.y);
    expect(pos.get("mid")!.y).toBeLessThan(pos.get("worst")!.y);
    // X increases with chronological sequence.
    expect(pos.get("worst")!.x).toBeLessThan(pos.get("mid")!.x);
    expect(pos.get("mid")!.x).toBeLessThan(pos.get("best")!.x);
    // unscored framing nodes with no run to anchor to (root, the lone decision)
    // go to the left sidebar, clear of the spine and its ribs (x < the curve).
    expect(pos.get("root")!.x).toBeLessThan(pos.get("worst")!.x);
    expect(pos.get("decide")!.x).toBeLessThan(pos.get("worst")!.x);
    // containment edges (root -> runs) are dropped in progression mode.
    expect(result.current.edges).toHaveLength(0);
  });

  it("falls back to the structural (dagre) layout when too few nodes are scored", () => {
    const nodes = [
      mk("root", { kind: "insight", parent_ids: [] }),
      run("only", 0.92, 1),
      mk("note", { kind: "insight", parent_ids: ["root"], semantic_data: null }),
    ];
    const { result } = renderHook(() => useGraphLayout(tree(nodes), "cards"));
    // dagre keeps the containment edges; progression would have dropped them.
    expect(result.current.edges.length).toBeGreaterThan(0);
  });
});
