import dagre from "dagre";
import type { Node as RFNode, Edge as RFEdge } from "@xyflow/react";
import type { Node } from "../../api/types.js";
import { scoreOf } from "./orbit.js";

/**
 * Adaptive graph layout engine.
 *
 * One structure-driven pipeline -- profile -> select -> compose -- that lays out
 * ANY research graph automatically, at any scale, with no per-graph code. It
 * reads only intrinsic signals on the data (node count, edge structure, scores,
 * time, a grouping attribute, kinds) and composes the right layout:
 *
 *   - progression : score-bearing runs -> a score-vs-sequence curve
 *   - layered     : a DAG of typed nodes -> dagre Sugiyama ranks
 *   - clustered   : nodes carry a group attribute (tier/track/wave/...) ->
 *                   partition, lay out each group with ITS OWN best sub-layout
 *                   (recursively), then pack the group boxes. This is the
 *                   generalization that scales: a 350-node research map becomes
 *                   a handful of legible clusters instead of one flat pile.
 *   - trivial     : a couple of nodes -> a column
 *
 * The same selection runs again inside each cluster, so the engine is recursive
 * and composes without special-casing.
 */

const NODE_WIDTH = 280;
const NODE_HEIGHT = 172;

const PROGRESSION_MIN_SCORED = 3;
const COL_W = 300;
const PLOT_H = 460;
const BAND_GAP = 150;
const BAND_STRIDE = 320;
const RIB_STACK = 196; // vertical step when several ribs share one run (> a card's height, so they never overlap)
const HYP_GAP = 210; // how far hypotheses float above the spine

// A node that is the source of more than this many edges is a containment hub
// (the project anchor); its fan is membership, not reasoning, and is dropped.
const HUB_OUT = 8;

// Cluster packing.
const GROUP_PAD = 28; // inner padding inside a cluster frame
const GROUP_HEADER = 44; // space reserved at the top of a frame for its label
const GROUP_GUTTER = 90; // gap between cluster frames
const GROUP_MIN_FOR_CLUSTER = 2; // a partition needs >= this many real groups

export type LayoutStrategy = "progression" | "layered" | "clustered" | "trivial";

export interface GraphProfile {
  n: number;
  m: number;
  components: number;
  isDAG: boolean;
  isTree: boolean;
  maxInDegree: number;
  avgDegree: number;
  density: number;
  scoredCount: number;
  /** group attribute value -> member node ids (only when a real partition exists) */
  groups: Map<string, string[]> | null;
  /** how `groups` was derived: an explicit attribute (tier/wave/...) or the
   *  kind fallback. Explicit groups partition before progression; the kind
   *  fallback is a last resort, only for graphs with no spine and no metric. */
  groupSource: "explicit" | "kind" | null;
  strategy: LayoutStrategy;
}

export interface GroupFrame {
  id: string;
  key: string; // raw group value (without the "key:" prefix)
  label: string;
  x: number;
  y: number;
  width: number;
  height: number;
  count: number;
}

export interface AdaptiveResult {
  nodes: RFNode[];
  edges: RFEdge[];
  frames: GroupFrame[];
  profile: GraphProfile;
}

/* ── grouping ─────────────────────────────────────────────────────────── */

// Low-cardinality categorical attributes we treat as an explicit grouping.
// Generic on purpose: any of these on a node's semantic_data (or its config)
// partitions the graph. No graph-specific names.
const GROUP_KEYS = ["group", "cluster", "tier", "track", "wave", "stage", "phase"];

// Known orderings so ordered partitions read left->right sensibly; anything
// unknown falls back to best-score / alphabetical ordering below.
const ORDINALS: Record<string, number> = {
  small: 0, medium: 1, large: 2, xl: 3, xxl: 4,
  v1: 0, novelty: 1, v2: 2, v3: 3, v4: 4,
  track_1: 0, track_2: 1, track_3: 2,
  // kind grouping (the fallback partition): runs first, then the reasoning
  // layers in the order an idea flows -- hypothesis -> insight -> decision.
  empirical: 0, hypothesis: 1, insight: 2, decision: 3, untyped: 4,
};

// How many distinct kinds (each with >= this many nodes) make a graph rich
// enough to cluster by kind when it carries no explicit group attribute.
const KIND_CLUSTER_MIN_KINDS = 3;
const KIND_CLUSTER_MIN_PER = 3;

function semObj(node: Node): Record<string, unknown> | null {
  const raw = node.semantic_data;
  if (raw == null) return null;
  if (typeof raw === "string") {
    try {
      const p: unknown = JSON.parse(raw);
      return p && typeof p === "object" && !Array.isArray(p) ? (p as Record<string, unknown>) : null;
    } catch {
      return null;
    }
  }
  return typeof raw === "object" && !Array.isArray(raw) ? (raw as Record<string, unknown>) : null;
}

/** The node's group value (e.g. "tier:xl"), or null. Checks semantic_data and
 *  its nested config so populate scripts can set the group either place. */
export function groupValueOf(node: Node): string | null {
  const sd = semObj(node);
  if (!sd) return null;
  const scopes: Record<string, unknown>[] = [sd];
  if (sd.config && typeof sd.config === "object" && !Array.isArray(sd.config)) {
    scopes.push(sd.config as Record<string, unknown>);
  }
  for (const scope of scopes) {
    for (const k of GROUP_KEYS) {
      const v = scope[k];
      if (typeof v === "string" && v.trim()) return `${k}:${v.trim()}`;
      if (typeof v === "number" && Number.isFinite(v)) return `${k}:${v}`;
    }
  }
  return null;
}

function groupOrdinal(rawValue: string, bestScore: number): number {
  const v = rawValue.toLowerCase();
  if (v in ORDINALS) return ORDINALS[v];
  const num = v.match(/(\d+(?:\.\d+)?)/);
  if (num) return Number(num[1]);
  // Unknown ordering: order clusters by their best (lowest) score so the
  // strongest cluster reads first; ties break alphabetically downstream.
  return 1000 + bestScore;
}

/* ── profile ──────────────────────────────────────────────────────────── */

export function profileGraph(nodes: Node[], edges: RFEdge[]): GraphProfile {
  const n = nodes.length;
  const ids = new Set(nodes.map((nd) => nd.node_id));
  const inDeg = new Map<string, number>();
  for (const e of edges) {
    if (ids.has(e.source) && ids.has(e.target)) inDeg.set(e.target, (inDeg.get(e.target) ?? 0) + 1);
  }
  const m = edges.filter((e) => ids.has(e.source) && ids.has(e.target)).length;
  let maxInDegree = 0;
  for (const d of inDeg.values()) maxInDegree = Math.max(maxInDegree, d);

  // connected components (undirected union-find)
  const parent = new Map<string, string>();
  const find = (x: string): string => {
    let r = x;
    while (parent.get(r) !== r) r = parent.get(r)!;
    return r;
  };
  for (const nd of nodes) parent.set(nd.node_id, nd.node_id);
  for (const e of edges) {
    if (!ids.has(e.source) || !ids.has(e.target)) continue;
    const a = find(e.source);
    const b = find(e.target);
    if (a !== b) parent.set(a, b);
  }
  const roots = new Set<string>();
  for (const nd of nodes) roots.add(find(nd.node_id));
  const components = n === 0 ? 0 : roots.size;

  const scoredCount = nodes.reduce((acc, nd) => acc + (scoreOf(nd) ? 1 : 0), 0);

  // grouping: a partition is "real" only when it splits the graph into a few
  // (2..n/2) groups covering most nodes, with groups of meaningful size.
  const buckets = new Map<string, string[]>();
  let grouped = 0;
  for (const nd of nodes) {
    const gv = groupValueOf(nd);
    if (gv) {
      (buckets.get(gv) ?? buckets.set(gv, []).get(gv)!).push(nd.node_id);
      grouped++;
    }
  }
  const realGroups = [...buckets.entries()].filter(([, ids2]) => ids2.length >= 2);
  const groupsValid =
    realGroups.length >= GROUP_MIN_FOR_CLUSTER &&
    realGroups.length <= Math.max(2, n / 2) &&
    grouped >= n * 0.5;
  // Explicit partition: nodes carry a real group attribute (tier/track/wave/...).
  // This is a deliberate, meaningful axis and partitions before anything else --
  // each group is then laid out with its own best sub-layout (often a per-group
  // progression curve), so a tiered graph reads as N improvement curves.
  const explicitGroups = groupsValid ? new Map(realGroups) : null;

  // Kind fallback (LAST RESORT): only when there is no explicit group AND no
  // metric spine to plot. A graph that is just typed reasoning nodes with no
  // runs has nothing better than to separate the kinds into regions. As soon as
  // there are scored runs, progression wins (kind becomes colour, not position).
  let kindGroups: Map<string, string[]> | null = null;
  if (!explicitGroups && scoredCount < PROGRESSION_MIN_SCORED) {
    const kindBuckets = new Map<string, string[]>();
    for (const nd of nodes) {
      const key = `kind:${nd.kind}`;
      (kindBuckets.get(key) ?? kindBuckets.set(key, []).get(key)!).push(nd.node_id);
    }
    const bigKinds = [...kindBuckets.entries()].filter(([, ids2]) => ids2.length >= KIND_CLUSTER_MIN_PER);
    if (bigKinds.length >= KIND_CLUSTER_MIN_KINDS) kindGroups = new Map(bigKinds);
  }
  const groups = explicitGroups ?? kindGroups;
  const groupSource: GraphProfile["groupSource"] = explicitGroups ? "explicit" : kindGroups ? "kind" : null;

  const avgDegree = n ? (2 * m) / n : 0;
  const density = n > 1 ? m / (n * (n - 1)) : 0;
  const isTree = maxInDegree <= 1;
  const isDAG = true; // Atlas edges come from parent_ids -> acyclic by construction

  // Selection order: a metric spine (progression) beats the kind fallback, so a
  // research graph reads as the flow of its runs with reasoning hung off, never
  // as type-buckets. Explicit groups still partition first (each group gets its
  // own curve); the kind fallback is reachable only for spine-less typed graphs.
  let strategy: LayoutStrategy;
  if (n <= 2) strategy = "trivial";
  else if (explicitGroups) strategy = "clustered";
  else if (scoredCount >= PROGRESSION_MIN_SCORED) strategy = "progression";
  else if (kindGroups) strategy = "clustered";
  else strategy = "layered";

  return {
    n, m, components, isDAG, isTree, maxInDegree, avgDegree, density,
    scoredCount, groups, groupSource, strategy,
  };
}

/* ── leaf layouts (return LOCAL coords + bounding box) ────────────────── */

function bbox(nodes: RFNode[]): { w: number; h: number } {
  let maxX = 0;
  let maxY = 0;
  for (const nd of nodes) {
    maxX = Math.max(maxX, nd.position.x + NODE_WIDTH);
    maxY = Math.max(maxY, nd.position.y + NODE_HEIGHT);
  }
  return { w: maxX, h: maxY };
}

function progressionTime(node: Node): number {
  const sd = semObj(node);
  const cfg = sd && typeof sd.config === "object" && sd.config !== null
    ? (sd.config as Record<string, unknown>) : null;
  // achieved_at is the canonical "when the result happened" key; completed_at is
  // what the run:record populate path writes, so accept it too -- otherwise the
  // spine orders by node creation order (parallel/unordered) and scrambles.
  const cand = [
    sd?.achieved_at, cfg?.achieved_at,
    sd?.completed_at, cfg?.completed_at,
    node.created_at,
  ].find((v) => typeof v === "string" && v) as string | undefined;
  const t = cand ? new Date(cand).getTime() : NaN;
  return Number.isFinite(t) ? t : 0;
}

/**
 * Spine-and-ribs progression. Scored runs become a score-vs-time CURVE (the
 * spine); each reasoning node hangs off the run it relates to (a rib) -- a
 * hypothesis floats above the run it motivated, an insight/decision drops below
 * the run that produced it -- so the picture reads as "this step led to this
 * conclusion" rather than a second row of buckets. Returns the edges to keep:
 * the run->run lineage plus the run<->reasoning ribs, minus any containment fan.
 * Returns null if there are too few scored nodes to form a curve.
 */
function layoutProgression(
  rfNodes: RFNode[],
  rfEdges: RFEdge[],
): { nodes: RFNode[]; scoredIds: Set<string>; keepEdges: Set<string> } | null {
  const scored: { rf: RFNode; value: number; lower: boolean; t: number }[] = [];
  const rest: { rf: RFNode; node: Node; t: number }[] = [];
  for (const rf of rfNodes) {
    const node = (rf.data as { node: Node }).node;
    const s = scoreOf(node);
    if (s) scored.push({ rf, value: s.value, lower: s.lowerIsBetter, t: progressionTime(node) });
    else rest.push({ rf, node, t: progressionTime(node) });
  }
  if (scored.length < PROGRESSION_MIN_SCORED) return null;
  scored.sort((a, b) => a.t - b.t || a.value - b.value);
  const vals = scored.map((s) => s.value);
  const min = Math.min(...vals);
  const span = Math.max(...vals) - min || 1;
  // Compress the column stride for long curves so a many-run cluster stays
  // bounded (a 70-run curve at full stride would be ~20k px). No effect on
  // normal-size curves, which keep the full stride.
  const colW = Math.max(150, Math.min(COL_W, 6000 / Math.max(1, scored.length - 1)));
  const scoredIds = new Set(scored.map((s) => s.rf.id));
  const runX = new Map<string, number>(); // scored id -> x on the spine
  const out: RFNode[] = scored.map((s, i) => {
    const norm = (s.value - min) / span;
    const fromBest = s.lower ? norm : 1 - norm;
    const x = i * colW;
    runX.set(s.rf.id, x);
    return { ...s.rf, position: { x, y: fromBest * PLOT_H } };
  });

  // Anchor each reasoning node under the run it connects to. A reasoning node is
  // a rib of run R if there is an edge R->node (run produced it: node is the
  // child) or node->R (idea motivated the run: node is the parent). Either way
  // it belongs at R's column. Containment edges from the project anchor are not
  // ribs: that anchor is the UNSCORED origin (in-degree 0) or a hub (huge
  // out-degree); a genuine reasoning node is parented to the root, so it has
  // in-degree >= 1 and is never mistaken for the origin.
  const inDeg = new Map<string, number>();
  const outDeg = new Map<string, number>();
  for (const e of rfEdges) {
    inDeg.set(e.target, (inDeg.get(e.target) ?? 0) + 1);
    outDeg.set(e.source, (outDeg.get(e.source) ?? 0) + 1);
  }
  const isHub = (id: string) => (outDeg.get(id) ?? 0) > HUB_OUT;
  const isOrigin = (id: string) => !scoredIds.has(id) && (inDeg.get(id) ?? 0) === 0;
  const anchorX = new Map<string, number>(); // rest id -> spine x
  for (const e of rfEdges) {
    if (isHub(e.source)) continue; // containment fan
    if (scoredIds.has(e.source) && !scoredIds.has(e.target)) {
      if (!anchorX.has(e.target)) anchorX.set(e.target, runX.get(e.source)!); // rib out
    } else if (scoredIds.has(e.target) && !scoredIds.has(e.source) && !isOrigin(e.source)) {
      if (!anchorX.has(e.source)) anchorX.set(e.source, runX.get(e.target)!); // rib in
    }
  }

  // Place the ribs. Hypotheses stack UP from their run (the idea that led to it);
  // insights then decisions stack DOWN (what the run produced, then what was
  // decided). Above/below each share one counter per column so a run with
  // several ribs never overlaps them (RIB_STACK >= a card's height). Reasoning
  // with no run to anchor to (framing context) goes in a tidy left sidebar,
  // clear of the spine and its ribs.
  const bandY = PLOT_H + BAND_GAP;
  const upCount = new Map<number, number>(); // x -> hypotheses stacked above
  const downCount = new Map<number, number>(); // x -> insights+decisions stacked below
  const kindOrder = (k: string) => (k === "hypothesis" ? 0 : k === "insight" ? 1 : k === "decision" ? 2 : 1);
  rest.sort((a, b) => kindOrder(a.node.kind) - kindOrder(b.node.kind) || a.t - b.t);
  const anchored = rest.filter((r) => anchorX.has(r.rf.id));
  const floating = rest.filter((r) => !anchorX.has(r.rf.id));
  for (const r of anchored) {
    const ax = anchorX.get(r.rf.id)!;
    if (r.node.kind === "hypothesis") {
      const k = upCount.get(ax) ?? 0;
      upCount.set(ax, k + 1);
      out.push({ ...r.rf, position: { x: ax, y: -HYP_GAP - k * RIB_STACK } });
    } else {
      const k = downCount.get(ax) ?? 0;
      downCount.set(ax, k + 1);
      out.push({ ...r.rf, position: { x: ax, y: bandY + k * RIB_STACK } });
    }
  }
  // Reasoning with no run to anchor to (e.g. ideas/learnings whose cited run
  // isn't in the sample) is contextual, not part of the flow. Lay it out as a
  // compact GRID to the left of the spine -- a tidy "context" block -- instead
  // of one very tall column that would blow up the graph's bounding box.
  const FLOAT_ROWS = Math.max(4, Math.ceil(Math.sqrt(floating.length)));
  const floatCols = Math.ceil(floating.length / FLOAT_ROWS) || 1;
  const floatX0 = -BAND_STRIDE - (floatCols - 1) * (NODE_WIDTH + 40);
  floating.forEach((r, i) => {
    const col = Math.floor(i / FLOAT_ROWS);
    const row = i % FLOAT_ROWS;
    out.push({ ...r.rf, position: { x: floatX0 + col * (NODE_WIDTH + 40), y: row * (NODE_HEIGHT + 28) } });
  });

  // Edges to keep: run->run lineage + run<->reasoning ribs; drop containment
  // (from the origin/hub anchor).
  const keepEdges = new Set<string>();
  for (const e of rfEdges) {
    if (scoredIds.has(e.source) && scoredIds.has(e.target)) { keepEdges.add(e.id); continue; }
    if (isHub(e.source) || isOrigin(e.source)) continue; // containment fan
    if (scoredIds.has(e.source) && anchorX.has(e.target)) keepEdges.add(e.id);
    else if (scoredIds.has(e.target) && anchorX.has(e.source)) keepEdges.add(e.id);
  }
  return { nodes: out, scoredIds, keepEdges };
}

function layoutDagre(rfNodes: RFNode[], rfEdges: RFEdge[]): RFNode[] {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "TB", nodesep: 36, ranksep: 64, marginx: 20, marginy: 20 });
  for (const node of rfNodes) g.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
  const present = new Set(rfNodes.map((n) => n.id));
  for (const e of rfEdges) if (present.has(e.source) && present.has(e.target)) g.setEdge(e.source, e.target);
  dagre.layout(g);
  return rfNodes.map((node) => {
    const p = g.node(node.id);
    return { ...node, position: { x: p.x - NODE_WIDTH / 2, y: p.y - NODE_HEIGHT / 2 } };
  });
}

function layoutColumn(rfNodes: RFNode[]): RFNode[] {
  return rfNodes.map((node, i) => ({ ...node, position: { x: 0, y: i * (NODE_HEIGHT + 32) } }));
}

/** Lay out a leaf cluster (never re-clusters) with its own best sub-layout. */
function layoutLeaf(
  rfNodes: RFNode[],
  rfEdges: RFEdge[],
  scoredCount: number,
): { nodes: RFNode[]; keepEdges: Set<string> } {
  if (rfNodes.length <= 2) return { nodes: layoutColumn(rfNodes), keepEdges: new Set() };
  if (scoredCount >= PROGRESSION_MIN_SCORED) {
    const prog = layoutProgression(rfNodes, rfEdges);
    // keep the spine lineage + reasoning ribs (drop the containment fan)
    if (prog) return { nodes: prog.nodes, keepEdges: prog.keepEdges };
  }
  return { nodes: layoutDagre(rfNodes, rfEdges), keepEdges: new Set(rfEdges.map((e) => e.id)) };
}

/* ── clustered (partition -> per-group sub-layout -> pack) ────────────── */

function layoutClustered(
  rfNodes: RFNode[],
  rfEdges: RFEdge[],
  groups: Map<string, string[]>,
): AdaptiveResult {
  const byId = new Map(rfNodes.map((n) => [n.id, n] as const));
  const assigned = new Set<string>();
  type Cluster = { gv: string; nodes: RFNode[]; ord: number; w: number; h: number };
  const clusters: Cluster[] = [];
  const keepEdgeIds = new Set<string>();

  for (const [gv, ids] of groups) {
    const members = ids.map((id) => byId.get(id)).filter((x): x is RFNode => !!x);
    members.forEach((m2) => assigned.add(m2.id));
    const memberSet = new Set(members.map((m2) => m2.id));
    const intra = rfEdges.filter((e) => memberSet.has(e.source) && memberSet.has(e.target));
    const scoredCount = members.reduce((a, m2) => a + (scoreOf((m2.data as { node: Node }).node) ? 1 : 0), 0);
    const laid = layoutLeaf(members, intra, scoredCount);
    laid.keepEdges.forEach((id) => keepEdgeIds.add(id));
    const box = bbox(laid.nodes);
    const best = Math.min(
      ...members.map((m2) => scoreOf((m2.data as { node: Node }).node)?.value ?? Infinity),
    );
    clusters.push({ gv, nodes: laid.nodes, ord: groupOrdinal(gv.split(":").slice(1).join(":"), best), w: box.w, h: box.h });
  }

  // Any node without a group goes into a trailing "other" cluster.
  const ungrouped = rfNodes.filter((n) => !assigned.has(n.id));
  if (ungrouped.length) {
    const us = new Set(ungrouped.map((n) => n.id));
    const intra = rfEdges.filter((e) => us.has(e.source) && us.has(e.target));
    const scoredCount = ungrouped.reduce((a, m2) => a + (scoreOf((m2.data as { node: Node }).node) ? 1 : 0), 0);
    const laid = layoutLeaf(ungrouped, intra, scoredCount);
    laid.keepEdges.forEach((id) => keepEdgeIds.add(id));
    const box = bbox(laid.nodes);
    clusters.push({ gv: "group:other", nodes: laid.nodes, ord: 9999, w: box.w, h: box.h });
  }

  // Shelf-pack the cluster boxes left->right, wrapping at a target width.
  clusters.sort((a, b) => a.ord - b.ord || a.gv.localeCompare(b.gv));
  const totalArea = clusters.reduce((a, c) => a + (c.w + GROUP_PAD * 2) * (c.h + GROUP_PAD * 2 + GROUP_HEADER), 0);
  const maxBoxW = Math.max(...clusters.map((c) => c.w + GROUP_PAD * 2));
  // Ordered partitions (tier/wave/track -> a known ordinal < 1000) read as a
  // left-to-right sequence, so keep a handful of them on one row. Otherwise
  // pack into a roughly-square grid so many clusters stay compact.
  const ordered = clusters.filter((c) => c.gv !== "group:other").every((c) => c.ord < 1000);
  const targetRowW =
    ordered && clusters.length <= 8
      ? Infinity
      : Math.max(maxBoxW, Math.sqrt(totalArea) * 1.5);

  const frames: GroupFrame[] = [];
  const outNodes: RFNode[] = [];
  let cx = 0;
  let cy = 0;
  let rowH = 0;
  for (const c of clusters) {
    const fw = c.w + GROUP_PAD * 2;
    const fh = c.h + GROUP_PAD * 2 + GROUP_HEADER;
    if (cx > 0 && cx + fw > targetRowW) {
      cx = 0;
      cy += rowH + GROUP_GUTTER;
      rowH = 0;
    }
    const ox = cx + GROUP_PAD;
    const oy = cy + GROUP_HEADER + GROUP_PAD;
    for (const nd of c.nodes) {
      outNodes.push({ ...nd, position: { x: nd.position.x + ox, y: nd.position.y + oy }, zIndex: 1 });
    }
    const rawVal = c.gv.split(":").slice(1).join(":");
    frames.push({
      id: `frame:${c.gv}`,
      key: rawVal,
      label: `${c.gv.split(":")[0]} · ${rawVal}`,
      x: cx, y: cy, width: fw, height: fh, count: c.nodes.length,
    });
    cx += fw + GROUP_GUTTER;
    rowH = Math.max(rowH, fh);
  }

  // Also keep cross-cluster edges -- these are the reasoning links that make a
  // research graph a DAG (hypothesis -> run -> insight -> decision) rather than
  // a set of islands. Drop only the containment fan from a hub: a node that is
  // the source of many edges is the project anchor, and its edges are
  // membership, not reasoning.
  const outDeg = new Map<string, number>();
  for (const e of rfEdges) outDeg.set(e.source, (outDeg.get(e.source) ?? 0) + 1);
  const clusterOf = new Map<string, string>();
  for (const c of clusters) for (const nd of c.nodes) clusterOf.set(nd.id, c.gv);
  for (const e of rfEdges) {
    if (keepEdgeIds.has(e.id)) continue;
    if ((outDeg.get(e.source) ?? 0) > HUB_OUT) continue; // containment fan
    if (clusterOf.has(e.source) && clusterOf.has(e.target)) keepEdgeIds.add(e.id);
  }

  const edges = rfEdges.filter((e) => keepEdgeIds.has(e.id));
  return {
    nodes: outNodes,
    edges,
    frames,
    profile: profileGraph(rfNodes.map((n) => (n.data as { node: Node }).node), rfEdges),
  };
}

/* ── public entry ─────────────────────────────────────────────────────── */

/** Lay out a graph adaptively: profile -> select strategy -> compose. */
export function layoutAdaptive(rfNodes: RFNode[], rfEdges: RFEdge[]): AdaptiveResult {
  const nodes = rfNodes.map((n) => (n.data as { node: Node }).node);
  const profile = profileGraph(nodes, rfEdges);

  if (profile.strategy === "clustered" && profile.groups) {
    return layoutClustered(rfNodes, rfEdges, profile.groups);
  }
  if (profile.strategy === "progression") {
    const prog = layoutProgression(rfNodes, rfEdges);
    if (prog) {
      // keep the spine lineage + the reasoning ribs (drop the containment fan)
      const edges = rfEdges.filter((e) => prog.keepEdges.has(e.id));
      return { nodes: prog.nodes, edges, frames: [], profile };
    }
  }
  if (profile.strategy === "trivial") {
    return { nodes: layoutColumn(rfNodes), edges: rfEdges, frames: [], profile };
  }
  return { nodes: layoutDagre(rfNodes, rfEdges), edges: rfEdges, frames: [], profile };
}
