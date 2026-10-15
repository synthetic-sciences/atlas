# Adaptive graph layout engine

`adaptiveLayout.ts` is the structure-driven layout engine behind the `cards`
graph view (`useGraphLayout.ts` delegates to it). It lays out ANY research graph
automatically from intrinsic signals — no per-graph code.

Pipeline: **profile → select → compose (recursive)**.

- `profileGraph(nodes, edges)`: n, edges, density, components, isDAG/isTree,
  maxInDegree, scoredCount, and a generic **group partition** (`groupValueOf`
  reads any low-cardinality categorical attr — `tier`/`track`/`wave`/`group`/
  `cluster`/`stage`/`phase` — from a node's `semantic_data` or its nested
  `config`). A partition is "real" only when 2..n/2 groups cover ≥50% of nodes.
- `selectStrategy`: trivial → **clustered** (groups) → **progression** (≥3
  scored) → **layered** (dagre).
- `layoutClustered`: partition by group → lay out EACH cluster with its own best
  sub-layout (recursive: scored → progression curve, structural → dagre, tiny →
  column) → shelf-pack the boxes (ordered groups like tier/wave stay in a
  left→right row; many groups → grid). Frames return as `group-frame` render
  nodes (`GroupFrameNode.tsx`, registered in `GraphCanvas`).

Scale: `ResearchNodeCard` collapses to a cheap `.rn-chip` below ~0.55 zoom (a
boolean `useStore` selector → re-renders only on threshold crossing), paired
with `onlyRenderVisibleElements`. Progression column stride compresses for long
curves.

To make a graph cluster: populate scripts just set a group attr (e.g.
`semantic_data.config.tier`) — the engine does the rest. Tests:
`adaptiveLayout.test.ts`, `useGraphLayout.progression.test.ts`. Embodies
[[build-general-not-oneoff]].
