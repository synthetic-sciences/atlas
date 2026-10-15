import { describe, it, expect } from "vitest";
import type { Node } from "../../api/types.js";
import type { Node as RFNode, Edge as RFEdge } from "@xyflow/react";
import { profileGraph, groupValueOf, layoutAdaptive } from "./adaptiveLayout.js";

function mk(id: string, over: Partial<Node>): Node {
  return {
    node_id: id, slug_name: id, title: id, summary: null, content: null, updated_by: null,
    kind: "empirical", lifecycle: "committed", outcome: "completed", hypothesis: null,
    no_artifacts_reason: null, insights: [], parent_ids: [], child_ids: [], repo_url: null,
    branch_name: null, head_commit_sha: null, origin_host: null, external_transcript_ref: null,
    revision: 1, graph_tags: [], tag_ids: [], tag_history: [], semantic_data: null,
    created_at: "2026-03-14T00:00:00Z", updated_at: "2026-03-14T00:00:00Z", ...over,
  };
}

function run(id: string, bpb: number, tier: string): Node {
  return mk(id, { kind: "empirical", parent_ids: ["root"], semantic_data: { metrics: { val_bpb: bpb }, tier } });
}

function toRf(nodes: Node[]): { rfNodes: RFNode[]; rfEdges: RFEdge[] } {
  const rfNodes = nodes.map((n) => ({ id: n.node_id, type: "research-node", position: { x: 0, y: 0 }, data: { node: n } }));
  const rfEdges: RFEdge[] = [];
  const ids = new Set(nodes.map((n) => n.node_id));
  for (const n of nodes) for (const p of n.parent_ids) if (ids.has(p)) rfEdges.push({ id: `${p}->${n.node_id}`, source: p, target: n.node_id });
  return { rfNodes, rfEdges };
}

describe("adaptiveLayout", () => {
  it("reads a group attribute generically from semantic_data (and config)", () => {
    expect(groupValueOf(mk("a", { semantic_data: { tier: "xl" } }))).toBe("tier:xl");
    expect(groupValueOf(mk("b", { semantic_data: { config: { wave: "v3" } } }))).toBe("wave:v3");
    expect(groupValueOf(mk("c", { semantic_data: { metrics: { val_bpb: 1 } } }))).toBeNull();
  });

  it("selects 'progression' for a scored graph with no groups", () => {
    const nodes = [mk("root", { kind: "insight", parent_ids: [] }),
      run("a", 0.95, ""), run("b", 0.93, ""), run("c", 0.91, "")].map((n) =>
      ({ ...n, semantic_data: n.node_id === "root" ? null : { metrics: { val_bpb: Number(n.title) || 0.9 } } }));
    // strip the tier so there are no groups
    const clean = nodes.map((n) => n.node_id === "root" ? n : mk(n.node_id, { semantic_data: { metrics: (n.semantic_data as { metrics: unknown }).metrics }, parent_ids: ["root"] }));
    const { rfNodes, rfEdges } = toRf(clean);
    expect(profileGraph(clean, rfEdges).strategy).toBe("progression");
    const out = layoutAdaptive(rfNodes, rfEdges);
    expect(out.frames).toHaveLength(0);
  });

  it("selects 'clustered' and emits a frame per tier when nodes carry a group attribute", () => {
    const nodes = [
      mk("root", { kind: "insight", parent_ids: [] }),
      run("xl1", 0.91, "xl"), run("xl2", 0.92, "xl"), run("xl3", 0.93, "xl"),
      run("md1", 0.95, "medium"), run("md2", 0.96, "medium"), run("md3", 0.97, "medium"),
      run("sm1", 1.12, "small"), run("sm2", 1.13, "small"), run("sm3", 1.14, "small"),
    ];
    const { rfNodes, rfEdges } = toRf(nodes);
    const p = profileGraph(nodes, rfEdges);
    expect(p.strategy).toBe("clustered");
    expect(p.groups?.size).toBe(3);
    const out = layoutAdaptive(rfNodes, rfEdges);
    // a frame per tier (+ possibly an "other" for the ungrouped root)
    const tierFrames = out.frames.filter((f) => f.label.startsWith("tier"));
    expect(tierFrames).toHaveLength(3);
    // ordered small -> medium -> large -> xl by x
    const byKey = new Map(out.frames.map((f) => [f.key, f.x]));
    expect(byKey.get("small")!).toBeLessThan(byKey.get("xl")!);
    // every research node is positioned inside some frame's box
    const frames = out.frames;
    const placed = out.nodes.filter((n) => n.type === "research-node");
    for (const n of placed) {
      const inside = frames.some((f) => n.position.x >= f.x && n.position.x <= f.x + f.width && n.position.y >= f.y && n.position.y <= f.y + f.height);
      expect(inside).toBe(true);
    }
  });

  it("a rich SCORED graph with no group attribute selects progression, NOT kind-buckets", () => {
    // A research graph with runs + reasoning must read as the run flow with
    // reasoning hung off it -- kind is colour, never a spatial partition.
    const nodes: Node[] = [mk("root", { kind: "insight", parent_ids: [] })];
    for (let i = 0; i < 5; i++) nodes.push(mk(`run${i}`, { kind: "empirical", parent_ids: ["root"], semantic_data: { metrics: { val_bpb: 0.9 + i / 100 } } }));
    for (let i = 0; i < 4; i++) nodes.push(mk(`hyp${i}`, { kind: "hypothesis", parent_ids: ["root"] }));
    for (let i = 0; i < 4; i++) nodes.push(mk(`ins${i}`, { kind: "insight", parent_ids: ["root"] }));
    for (let i = 0; i < 3; i++) nodes.push(mk(`dec${i}`, { kind: "decision", parent_ids: ["root"] }));
    const { rfNodes, rfEdges } = toRf(nodes);
    const out = layoutAdaptive(rfNodes, rfEdges);
    expect(out.profile.strategy).toBe("progression");
    expect(out.profile.groupSource).toBeNull();
    expect(out.frames).toHaveLength(0); // no kind frames
  });

  it("falls back to clustering BY KIND only for a SPINELESS typed graph (no metrics)", () => {
    // No scored runs => nothing to plot as a curve; the honest fallback is to
    // separate the reasoning kinds into regions.
    const nodes: Node[] = [mk("root", { kind: "insight", parent_ids: [] })];
    for (let i = 0; i < 4; i++) nodes.push(mk(`hyp${i}`, { kind: "hypothesis", parent_ids: ["root"], semantic_data: null }));
    for (let i = 0; i < 4; i++) nodes.push(mk(`ins${i}`, { kind: "insight", parent_ids: ["root"], semantic_data: null }));
    for (let i = 0; i < 3; i++) nodes.push(mk(`dec${i}`, { kind: "decision", parent_ids: ["root"], semantic_data: null }));
    const { rfNodes, rfEdges } = toRf(nodes);
    const out = layoutAdaptive(rfNodes, rfEdges);
    expect(out.profile.strategy).toBe("clustered");
    expect(out.profile.groupSource).toBe("kind");
    const labels = out.frames.map((f) => f.label);
    expect(labels.some((l) => l.includes("hypothesis"))).toBe(true);
    expect(labels.some((l) => l.includes("decision"))).toBe(true);
  });

  it("progression keeps the reasoning ribs and anchors them under their run", () => {
    // spine: 3 chained runs; hyp -> run1 (idea motivated it); run2 -> insight
    const nodes: Node[] = [
      mk("root", { kind: "insight", parent_ids: [] }),
      mk("run0", { kind: "empirical", parent_ids: ["root"], semantic_data: { metrics: { val_bpb: 0.95 }, completed_at: "2026-03-01T00:00:00Z" } }),
      mk("run1", { kind: "empirical", parent_ids: ["run0"], semantic_data: { metrics: { val_bpb: 0.93 }, completed_at: "2026-03-02T00:00:00Z" } }),
      mk("run2", { kind: "empirical", parent_ids: ["run1"], semantic_data: { metrics: { val_bpb: 0.91 }, completed_at: "2026-03-03T00:00:00Z" } }),
      mk("hyp0", { kind: "hypothesis", parent_ids: ["root"], child_ids: ["run1"] }),
      mk("ins0", { kind: "insight", parent_ids: ["run2"] }),
    ];
    // Edges as the real CLI builds them: the root parents the spine head + every
    // reasoning node (containment); hyp0 -> run1 is the --hypothesis_id rib in;
    // run2 -> ins0 is the link:add rib out.
    const rfNodes: RFNode[] = nodes.map((n) => ({ id: n.node_id, type: "research-node", position: { x: 0, y: 0 }, data: { node: n } }));
    const rfEdges: RFEdge[] = [
      { id: "root->run0", source: "root", target: "run0" },
      { id: "root->hyp0", source: "root", target: "hyp0" },
      { id: "root->ins0", source: "root", target: "ins0" },
      { id: "run0->run1", source: "run0", target: "run1" },
      { id: "run1->run2", source: "run1", target: "run2" },
      { id: "hyp0->run1", source: "hyp0", target: "run1" },
      { id: "run2->ins0", source: "run2", target: "ins0" },
    ];
    const out = layoutAdaptive(rfNodes, rfEdges);
    expect(out.profile.strategy).toBe("progression");
    const keptIds = new Set(out.edges.map((e) => e.id));
    expect(keptIds.has("run0->run1")).toBe(true); // lineage
    expect(keptIds.has("hyp0->run1")).toBe(true); // rib in
    expect(keptIds.has("run2->ins0")).toBe(true); // rib out
    // the hypothesis sits at its run's column and above the spine; insight below
    const pos = new Map(out.nodes.map((n) => [n.id, n.position]));
    expect(pos.get("hyp0")!.x).toBe(pos.get("run1")!.x);
    expect(pos.get("hyp0")!.y).toBeLessThan(0);
    expect(pos.get("ins0")!.x).toBe(pos.get("run2")!.x);
    expect(pos.get("ins0")!.y).toBeGreaterThan(pos.get("run2")!.y);
  });

  it("a thin graph (runs + a couple notes) stays progression, not kind-clustered", () => {
    const nodes: Node[] = [mk("root", { kind: "insight", parent_ids: [] }),
      mk("n1", { kind: "insight", parent_ids: ["root"] })];
    for (let i = 0; i < 12; i++) nodes.push(mk(`r${i}`, { kind: "empirical", parent_ids: ["root"], semantic_data: { metrics: { val_bpb: 0.9 + i / 100 } } }));
    const { rfNodes, rfEdges } = toRf(nodes);
    // only 1 kind (empirical) has >=3 nodes -> no kind cluster -> progression
    expect(layoutAdaptive(rfNodes, rfEdges).profile.strategy).toBe("progression");
  });

  it("scales: a 300-node grouped graph stays clustered with bounded frames", () => {
    const tiers = ["small", "medium", "large", "xl"];
    const nodes: Node[] = [mk("root", { kind: "insight", parent_ids: [] })];
    for (let i = 0; i < 300; i++) nodes.push(run(`r${i}`, 0.9 + (i % 50) / 100, tiers[i % 4]));
    const { rfNodes, rfEdges } = toRf(nodes);
    const out = layoutAdaptive(rfNodes, rfEdges);
    expect(out.profile.strategy).toBe("clustered");
    expect(out.frames.filter((f) => f.label.startsWith("tier"))).toHaveLength(4);
    expect(out.nodes.filter((n) => n.type === "research-node")).toHaveLength(301);
  });
});
