import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import {
  forceCollide,
  forceLink,
  forceManyBody,
  forceRadial,
  forceSimulation,
  type Simulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force";
import { select } from "d3-selection";
import { zoom, zoomIdentity, type ZoomBehavior, type ZoomTransform } from "d3-zoom";
import { Maximize, Minus, Plus } from "lucide-react";
import type { Node, NodeTreeResponse } from "../../api/types";
import {
  outcomeColor,
  kindColor,
  computeSegments,
  timeAgo,
  shortDateTime,
  columnLabel,
  scorecardOf,
  scorecardSegments,
  type Scorecard,
} from "./orbit";

/**
 * Bespoke d3 graph for the "orbit" style. Restrained, Flywheel-like: small
 * muted nodes, roots as bright labeled circles, hairline edges, generous space.
 *
 * mode="force":    live d3-force simulation (organic settle + fans).
 * mode="timeline": swimlane layout. x = research time (semantic achieved/
 *                  completed time, reasoning inheriting its run's time), laid
 *                  out in time *order* with uniform spacing - never proportional
 *                  to elapsed time, so uneven timestamps can't open whitespace
 *                  gulfs. y = a lane per kind (ideas above the run spine,
 *                  learnings/decisions below). Sparse date markers are drawn
 *                  where the calendar label changes.
 *
 * Hovering a node focuses it + its neighbors (others dim). Click centers the
 * node smoothly and opens it. Selection keeps the node + direct links lit.
 */

interface FNode extends SimulationNodeDatum {
  id: string;
  r: number;
  isRoot: boolean;
}
interface FLink extends SimulationLinkDatum<FNode> {
  source: string | FNode;
  target: string | FNode;
  staged: boolean;
  /** A membership edge from the project anchor (root/hub) to a node that also
   *  has a real lineage parent. It conveys "belongs to" not "led to", so the
   *  radial layout ignores it for depth and the renderer draws it faintly. */
  containment?: boolean;
}

/** A sparse timeline marker: data-space x + the label that starts there. */
interface ColMarker {
  x: number;
  label: string;
}

const ROOT_R = 12;
const BASE_R = 9;

/** Timeline geometry: uniform column width + left origin. */
const COL_W = 116;
const COL_X0 = 80;

const MIN_ZOOM = 0.15;
const MAX_ZOOM = 3;

/** Scorecard ring: sits just outside the glyph, one arc per example. */
const RING_OFFSET = 4;
const RING_STROKE = 2.5;
const RING_MAX_SEGMENTS = 32;

const MONO = "'JetBrains Mono', monospace";
const SERIF = "var(--font-serif)";

/** Clockwise arc from angle a0 to a1 (radians) on a circle of radius r. */
function ringArcPath(r: number, a0: number, a1: number): string {
  const x0 = r * Math.cos(a0);
  const y0 = r * Math.sin(a0);
  const x1 = r * Math.cos(a1);
  const y1 = r * Math.sin(a1);
  const large = a1 - a0 > Math.PI ? 1 : 0;
  return `M ${x0.toFixed(2)} ${y0.toFixed(2)} A ${r} ${r} 0 ${large} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
}

function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" &&
    Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches);
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}

/** Fade labels out as the view zooms away, instead of letting them overlap. */
function labelFade(k: number, from: number, to: number): number {
  return clamp((k - from) / (to - from), 0, 1);
}

type Props = {
  treeData: NodeTreeResponse;
  selectedIds?: Set<string>;
  onNodeClick?: (id: string, shiftKey: boolean) => void;
  mode?: "force" | "timeline";
};

export function OrbitGraph({ treeData, selectedIds, onNodeClick, mode = "force" }: Props) {
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const simRef = useRef<Simulation<FNode, FLink> | null>(null);
  const zoomRef = useRef<ZoomBehavior<SVGSVGElement, unknown> | null>(null);
  const transformRef = useRef<ZoomTransform>(zoomIdentity);
  const animRef = useRef<number | null>(null);
  /** True once the user pans/zooms; blocks auto-fit from fighting them. */
  const userMovedRef = useRef(false);
  const fitViewRef = useRef<((animate?: boolean) => void) | null>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [transform, setTransform] = useState<ZoomTransform>(zoomIdentity);
  const [hover, setHover] = useState<{ id: string; x: number; y: number } | null>(null);
  const [, setTick] = useState(0);

  const byId = useMemo(
    () => new Map(treeData.nodes.map((n) => [n.node_id, n])),
    [treeData],
  );

  // Parsed once per tree, not per render tick: force mode re-renders at
  // simulation rate and scorecard parsing may involve JSON.parse.
  const scorecardsById = useMemo(() => {
    const m = new Map<string, Scorecard>();
    for (const n of treeData.nodes) {
      const sc = scorecardOf(n);
      if (sc) m.set(n.node_id, sc);
    }
    return m;
  }, [treeData]);

  const { nodes, links, colMarkers } = useMemo(() => {
    const present = (id: string) => byId.has(id);
    // Uniform node size: scaling a node by child-count read as arbitrary visual
    // noise. Every node is the same; only the root reads slightly larger as the
    // single origin marker. Meaning is carried by colour (kind) + position.
    const fnodes: FNode[] = treeData.nodes.map((n) => {
      const isRoot = n.parent_ids.filter(present).length === 0;
      return { id: n.node_id, r: isRoot ? ROOT_R : BASE_R, isRoot };
    });
    const flinks: FLink[] = [];
    for (const n of treeData.nodes) {
      for (const p of n.parent_ids) {
        if (present(p)) flinks.push({ source: p, target: n.node_id, staged: n.lifecycle === "staged" });
      }
    }
    // Flag containment (membership) edges: an edge from the project anchor (a
    // root, or a hub fanning out to many children) to a node that ALSO has a
    // real lineage parent. These shortcut depth and clutter the radial view, so
    // they're marked here and ignored by the spiral layout / drawn faintly.
    {
      const ANCHOR_OUT = 8;
      const parentCount = new Map<string, number>();
      const outDeg = new Map<string, number>();
      const isRootId = new Map(fnodes.map((n) => [n.id, n.isRoot] as const));
      for (const l of flinks) {
        parentCount.set(l.target as string, (parentCount.get(l.target as string) ?? 0) + 1);
        outDeg.set(l.source as string, (outDeg.get(l.source as string) ?? 0) + 1);
      }
      for (const l of flinks) {
        const anchorSrc = isRootId.get(l.source as string) || (outDeg.get(l.source as string) ?? 0) > ANCHOR_OUT;
        if (anchorSrc && (parentCount.get(l.target as string) ?? 0) > 1) l.containment = true;
      }
    }

    let markers: ColMarker[] | null = null;
    if (mode === "timeline") {
      // Swimlane timeline: x = research time, y = a lane per role (ideas above
      // the run spine, learnings/decisions below). General by construction -- it
      // reads the time and kind already on each node and never depends on the
      // graph being shaped a particular way:
      //  - time comes from the semantic achieved_at/completed_at when present
      //    (the moment the result happened), NOT just created_at -- otherwise a
      //    batch-created graph collapses to a single instant. Reasoning nodes
      //    inherit the time of the run they relate to, so an idea sits at the
      //    experiment it motivated and a learning at the run it came from.
      const parseSem = (raw: unknown): Record<string, unknown> | null => {
        if (raw == null) return null;
        if (typeof raw === "string") {
          try { const p: unknown = JSON.parse(raw); return p && typeof p === "object" && !Array.isArray(p) ? (p as Record<string, unknown>) : null; } catch { return null; }
        }
        return typeof raw === "object" && !Array.isArray(raw) ? (raw as Record<string, unknown>) : null;
      };
      const semTime = (n: Node): number | null => {
        const sd = parseSem(n.semantic_data);
        const cfg = sd && typeof sd.config === "object" && sd.config !== null ? (sd.config as Record<string, unknown>) : null;
        for (const v of [sd?.achieved_at, cfg?.achieved_at, sd?.completed_at, cfg?.completed_at]) {
          if (typeof v === "string") { const t = Date.parse(v); if (Number.isFinite(t)) return t; }
        }
        return null;
      };
      const createdOf = (n: Node): number | null => { const t = Date.parse(n.created_at); return Number.isFinite(t) ? t : null; };

      const baseT = new Map<string, number>(); // nodes with their own research time
      for (const n of treeData.nodes) { const t = semTime(n); if (t != null) baseT.set(n.node_id, t); }
      const timeOf = new Map<string, number>();
      for (const n of treeData.nodes) {
        let t = baseT.get(n.node_id);
        if (t == null) {
          for (const m of [...(n.parent_ids || []), ...(n.child_ids || [])]) {
            if (baseT.has(m)) { t = baseT.get(m); break; } // inherit a connected run's time
          }
        }
        if (t == null) t = createdOf(n) ?? undefined;
        if (t != null) timeOf.set(n.node_id, t);
      }

      if (timeOf.size === fnodes.length && fnodes.length > 1) {
        // lanes (top -> bottom): framing/root, ideas, the run spine, learnings,
        // decisions. The run spine sits in the middle so the eye reads it first.
        const laneOf = (k: string | undefined) =>
          k === "hypothesis" ? 1 : k === "empirical" ? 2 : k === "insight" ? 3 : k === "decision" ? 4 : 0;
        const LANE_H = 150;
        const ordered = [...fnodes].sort((a, b) => (timeOf.get(a.id)! - timeOf.get(b.id)!) || a.id.localeCompare(b.id));
        ordered.forEach((n, i) => {
          n.x = COL_X0 + i * COL_W;
          n.y = laneOf(byId.get(n.id)?.kind) * LANE_H;
        });

        // Sparse date markers: only where the formatted label changes.
        const times = [...timeOf.values()];
        const span = Math.max(...times) - Math.min(...times);
        markers = [];
        let prevLabel = "";
        for (const n of ordered) {
          const t = timeOf.get(n.id);
          if (t == null || n.x == null) continue;
          const label = columnLabel(t, span);
          if (label !== prevLabel) { markers.push({ x: n.x, label }); prevLabel = label; }
        }
      }
    }

    return { nodes: fnodes, links: flinks, colMarkers: markers };
  }, [treeData, byId, mode]);

  // adjacency for hover focus
  const neighbors = useMemo(() => {
    const m = new Map<string, Set<string>>();
    const add = (a: string, b: string) => {
      if (!m.has(a)) m.set(a, new Set());
      m.get(a)?.add(b);
    };
    for (const l of links) {
      const s = typeof l.source === "string" ? l.source : l.source.id;
      const t = typeof l.target === "string" ? l.target : l.target.id;
      add(s, t);
      add(t, s);
    }
    return m;
  }, [links]);

  useEffect(() => {
    const el = wrapperRef.current;
    if (!el) return;
    const update = () => {
      const rect = el.getBoundingClientRect();
      setSize({ w: rect.width, h: rect.height });
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    if (mode !== "force" || size.w === 0 || size.h === 0) return;
    const { w, h } = size;
    const cx = w / 2;
    const cy = h / 2;

    // Encode the DAG as concentric orbits: lineage depth -> radius, so roots
    // sit at the centre and each generation flows outward in its own ring,
    // with each subtree owning an angular wedge. This turns the old
    // everything-pulled-to-centre force blob into a readable radial flow that
    // actually shows who-led-to-what, while force still relaxes it organically.
    // Build the lineage DAG from STRUCTURAL edges only (drop containment, so
    // the project anchor's membership fan never shortcuts depth).
    const childrenOf = new Map<string, string[]>();
    const parentsOf = new Map<string, string[]>();
    for (const l of links) {
      if (l.containment) continue;
      const s = typeof l.source === "string" ? l.source : l.source.id;
      const t = typeof l.target === "string" ? l.target : l.target.id;
      (childrenOf.get(s) ?? childrenOf.set(s, []).get(s)!).push(t);
      (parentsOf.get(t) ?? parentsOf.set(t, []).get(t)!).push(s);
    }
    const rootIds = nodes.filter((n) => n.isRoot).map((n) => n.id);
    // Depth = LONGEST path from a root (DAG): a run sits one ring beyond the run
    // it built on, so the lineage spine spirals outward instead of collapsing to
    // one ring. (Shortest-path BFS would let a single hyp->deep-run or a
    // containment edge pull a late node back to ring 1.)
    const depth = new Map<string, number>();
    const inProg = new Set<string>();
    const depthOf = (id: string): number => {
      const cached = depth.get(id);
      if (cached != null) return cached;
      if (inProg.has(id)) return 0; // acyclic by construction; guard anyway
      inProg.add(id);
      let d = 0;
      for (const p of parentsOf.get(id) ?? []) d = Math.max(d, depthOf(p) + 1);
      inProg.delete(id);
      depth.set(id, d);
      return d;
    };
    for (const n of nodes) depthOf(n.id);
    let maxDepth = 0;
    for (const d of depth.values()) maxDepth = Math.max(maxDepth, d);
    // A non-root with no structural parent is detached -> park it on the outer
    // ring rather than at the centre with the roots.
    for (const n of nodes) {
      if (!n.isRoot && (depth.get(n.id) ?? 0) === 0 && !(parentsOf.get(n.id)?.length)) depth.set(n.id, maxDepth + 1);
    }
    maxDepth = 0;
    for (const d of depth.values()) maxDepth = Math.max(maxDepth, d);

    // Subtree weight (descendants along the spine) so the wedge split favours
    // the lineage continuation: the main spine keeps a wide, coherent sweep and
    // reasoning leaves take thin slivers, instead of an even fan that shreds the
    // chain into equal slices.
    const weight = new Map<string, number>();
    const weightOf = (id: string): number => {
      const cached = weight.get(id);
      if (cached != null) return cached;
      weight.set(id, 1); // recursion guard
      let w = 1;
      for (const c of childrenOf.get(id) ?? []) {
        if ((depth.get(c) ?? 0) > (depth.get(id) ?? 0)) w += weightOf(c);
      }
      weight.set(id, w);
      return w;
    };
    for (const n of nodes) weightOf(n.id);

    // Angular wedge per subtree: split each node's arc among its deeper children
    // in proportion to their weight (heaviest = the spine = the widest wedge).
    const angle = new Map<string, number>();
    const visited = new Set<string>();
    const assignAngle = (id: string, a0: number, a1: number) => {
      if (visited.has(id)) return;
      visited.add(id);
      angle.set(id, (a0 + a1) / 2);
      const kids = (childrenOf.get(id) ?? []).filter(
        (c) => !visited.has(c) && (depth.get(c) ?? 0) > (depth.get(id) ?? 0),
      );
      if (!kids.length) return;
      kids.sort((a, b) => weightOf(b) - weightOf(a)); // spine first, deterministic
      const total = kids.reduce((s, c) => s + weightOf(c), 0) || 1;
      let a = a0;
      for (const c of kids) {
        const span = (a1 - a0) * (weightOf(c) / total);
        assignAngle(c, a, a + span);
        a += span;
      }
    };
    const rootSpan = (2 * Math.PI) / Math.max(1, rootIds.length);
    rootIds.forEach((r, i) => assignAngle(r, i * rootSpan, (i + 1) * rootSpan));
    let leftover = 0;
    for (const n of nodes) {
      if (!angle.has(n.id)) angle.set(n.id, (leftover++ / Math.max(1, nodes.length)) * 2 * Math.PI);
    }

    // ── Ring spacing (ONE formula for every graph) ───────────────────────────
    // Radius = lineage depth, so each generation flows outward in its own ring.
    // The natural per-ring spacing reads well, but a very DEEP lineage (a long
    // history — e.g. an 85-generation world-record chain) at that spacing would
    // push the outer ring ~6000px off-screen, so fit-to-screen collapses every
    // node to a speck. Cap the orbit's OUTER radius so ANY graph lands at a
    // consistent on-screen extent: shallow/bushy graphs stay under the cap and
    // are untouched; deeper ones simply tighten their rings (and the same forces
    // wind the lineage in). No per-graph special-casing — one rule, applied
    // everywhere.
    const baseGap = Math.max(150, Math.min(w, h) * 0.17);
    const fitGap = (Math.min(w, h) * 0.42) / Math.max(1, maxDepth);
    const idealGap = Math.max(70, Math.min(baseGap, fitGap));
    // Largest outer radius fit-to-screen still frames legibly (~the extent a
    // depth-18 bushy graph already occupies, which reads well).
    const maxOuterR = Math.min(w, h) * 2.2;
    const ringGap = Math.min(idealGap, maxOuterR / Math.max(1, maxDepth));
    const radiusOf = (id: string) => {
      const d = depth.get(id) ?? 0;
      // multiple roots get a small inner ring instead of stacking at the centre
      return d === 0 && rootIds.length > 1 ? ringGap * 0.45 : d * ringGap;
    };

    // Seed at the target orbit so the simulation only has to relax, not search.
    nodes.forEach((n) => {
      const rr = radiusOf(n.id);
      const aa = angle.get(n.id) ?? 0;
      n.x = cx + rr * Math.cos(aa);
      n.y = cy + rr * Math.sin(aa);
    });

    const sim = forceSimulation<FNode>(nodes)
      // Nodes are SEEDED at their radial target positions, so the sim only needs
      // to RELAX, not search. Decay faster than the default (0.0228) so it
      // settles in ~1.5s — fewer per-tick re-renders, a shorter intro, a
      // jank-free graph sooner. Stronger velocity damping prevents oscillation.
      .alphaDecay(0.045)
      .velocityDecay(0.5)
      .force(
        "link",
        forceLink<FNode, FLink>(links.filter((l) => !l.containment))
          .id((d) => d.id)
          .distance(ringGap * 0.7)
          .strength(0.22), // gentle: keep lineage tight without fighting the rings
      )
      .force("charge", forceManyBody<FNode>().strength(-Math.max(180, w * 0.18)))
      .force("radial", forceRadial<FNode>((d) => radiusOf(d.id), cx, cy).strength(0.9))
      .force("collide", forceCollide<FNode>((d) => d.r + 14).iterations(2))
      .on("tick", () => setTick((t) => t + 1))
      .on("end", () => {
        // Gentle fit once the layout settles - skipped if the user already
        // grabbed the view, so we never fight their pan/zoom.
        if (!userMovedRef.current) fitViewRef.current?.(true);
      });
    simRef.current = sim;
    // Fit immediately to the structured radial seed so the view is correct from
    // the first frame (the seed is already the meaningful layout); the on-end
    // fit then refines once the simulation relaxes. Without this, a slower-
    // settling deep graph shows unfitted until "end" eventually fires.
    requestAnimationFrame(() => {
      if (!userMovedRef.current) fitViewRef.current?.(false);
    });
    return () => {
      sim.stop();
    };
  }, [nodes, links, size.w, size.h, mode]);

  useEffect(() => {
    const svgEl = svgRef.current;
    if (!svgEl) return;
    const z = zoom<SVGSVGElement, unknown>()
      .scaleExtent([MIN_ZOOM, MAX_ZOOM])
      .on("zoom", (e) => {
        if (e.sourceEvent) userMovedRef.current = true;
        transformRef.current = e.transform;
        setTransform(e.transform);
      });
    select(svgEl).call(z);
    zoomRef.current = z;
    return () => {
      select(svgEl).on(".zoom", null);
      zoomRef.current = null;
    };
  }, []);

  // cancel any in-flight zoom tween on unmount
  useEffect(() => () => {
    if (animRef.current != null) cancelAnimationFrame(animRef.current);
  }, []);

  /** Tween the zoom transform (instant under prefers-reduced-motion). */
  const animateTo = useCallback((target: ZoomTransform, durationMs = 350) => {
    const svgEl = svgRef.current;
    const z = zoomRef.current;
    if (!svgEl || !z) return;
    if (animRef.current != null) cancelAnimationFrame(animRef.current);
    if (durationMs <= 0 || prefersReducedMotion()) {
      select(svgEl).call(z.transform, target);
      return;
    }
    const start = transformRef.current;
    const begin = performance.now();
    const step = (now: number) => {
      const p = Math.min(1, (now - begin) / durationMs);
      const e = 1 - Math.pow(1 - p, 3); // ease-out cubic
      const k = start.k + (target.k - start.k) * e;
      const x = start.x + (target.x - start.x) * e;
      const y = start.y + (target.y - start.y) * e;
      select(svgEl).call(z.transform, zoomIdentity.translate(x, y).scale(k));
      animRef.current = p < 1 ? requestAnimationFrame(step) : null;
    };
    animRef.current = requestAnimationFrame(step);
  }, []);

  /**
   * Fit the graph into the viewport. The timeline reads like a log: zoom is
   * never allowed to collapse below label legibility - instead the view
   * anchors at the root (left edge) and the user pans right through time.
   */
  const fitView = useCallback(
    (animate = true) => {
      const { w, h } = size;
      if (w === 0 || h === 0) return;
      let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
      for (const n of nodes) {
        if (n.x == null || n.y == null) continue;
        minX = Math.min(minX, n.x - n.r);
        maxX = Math.max(maxX, n.x + n.r);
        minY = Math.min(minY, n.y - n.r);
        maxY = Math.max(maxY, n.y + n.r);
      }
      if (!isFinite(minX)) return;
      const pad = 70;
      const bw = Math.max(1, maxX - minX + pad * 2);
      const bh = Math.max(1, maxY - minY + pad * 2);
      const fitK = Math.min(w / bw, h / bh);
      const k = mode === "timeline" ? clamp(fitK, 0.8, 1.1) : clamp(fitK, MIN_ZOOM, 1.25);
      const overflowsX = k * bw > w;
      const tx = mode === "timeline" && overflowsX
        ? pad - k * minX // anchor the root at the left edge
        : (w - k * (minX + maxX)) / 2;
      const ty = (h - k * (minY + maxY)) / 2;
      animateTo(zoomIdentity.translate(tx, ty).scale(k), animate ? 400 : 0);
    },
    [nodes, size, animateTo, mode],
  );
  fitViewRef.current = fitView;

  /** Zoom in/out around the viewport center. */
  const zoomBy = useCallback(
    (factor: number) => {
      const { w, h } = size;
      const t = transformRef.current;
      const k = clamp(t.k * factor, MIN_ZOOM, MAX_ZOOM);
      if (k === t.k) return;
      const cx = w / 2;
      const cy = h / 2;
      const tx = cx - (k / t.k) * (cx - t.x);
      const ty = cy - (k / t.k) * (cy - t.y);
      animateTo(zoomIdentity.translate(tx, ty).scale(k), 220);
    },
    [size, animateTo],
  );

  /** Smoothly center a node (click-to-focus). */
  const centerOn = useCallback(
    (n: FNode) => {
      if (n.x == null || n.y == null) return;
      userMovedRef.current = true; // deliberate focus; don't auto-refit over it
      const { w, h } = size;
      const k = clamp(Math.max(transformRef.current.k, 0.85), MIN_ZOOM, 1.5);
      animateTo(zoomIdentity.translate(w / 2 - k * n.x, h / 2 - k * n.y).scale(k), 380);
    },
    [size, animateTo],
  );

  // On mode / graph change: timeline gets an immediate fit (its layout extent
  // is arbitrary), force resets to identity (the sim settles around center).
  // Keyed on the anchor id, not the treeData object, so refetches after node
  // mutations don't throw away the user's pan/zoom.
  useEffect(() => {
    if (size.w === 0 || size.h === 0) return;
    userMovedRef.current = false;
    if (mode === "timeline") {
      fitView(false);
    } else {
      const svgEl = svgRef.current;
      const z = zoomRef.current;
      if (svgEl && z) select(svgEl).call(z.transform, zoomIdentity);
    }
    // Re-fit only when the layout fundamentally changes, not on pan/zoom.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, treeData.anchor_node_id, size.w === 0]);

  const nodeById = useMemo(() => {
    const m = new Map<string, FNode>();
    for (const n of nodes) m.set(n.id, n);
    return m;
  }, [nodes]);

  // Selection emphasis: with a selection and no hover, keep the selected
  // node(s) + direct links lit and recede everything else.
  const selectionFocus = useMemo(() => {
    if (!selectedIds || selectedIds.size === 0) return null;
    const focus = new Set<string>(selectedIds);
    for (const id of selectedIds) {
      for (const nb of neighbors.get(id) ?? []) focus.add(nb);
    }
    return focus;
  }, [selectedIds, neighbors]);

  const hoveredNode = hover ? byId.get(hover.id) : null;
  const hoverFocus = hover ? neighbors.get(hover.id) : null;
  const isDimmed = (id: string): boolean => {
    if (hover) return id !== hover.id && !hoverFocus?.has(id);
    if (selectionFocus) return !selectionFocus.has(id);
    return false;
  };
  const isLinkLit = (sId: string, tId: string): boolean => {
    if (hover) return hover.id === sId || hover.id === tId;
    if (selectedIds && selectedIds.size > 0) return selectedIds.has(sId) || selectedIds.has(tId);
    return true;
  };

  const handleNodeClick = useCallback(
    (n: FNode, shiftKey: boolean) => {
      if (!shiftKey) centerOn(n);
      onNodeClick?.(n.id, shiftKey);
    },
    [centerOn, onNodeClick],
  );

  // Label legibility by zoom level: timeline labels are part of the layout
  // contract (one per column) and fade out only when very zoomed out; force
  // mode reveals all labels once the view is zoomed in past ~1.1x.
  const rootLabelOpacity = labelFade(transform.k, 0.28, 0.45);
  const nodeLabelOpacity =
    mode === "timeline" ? labelFade(transform.k, 0.35, 0.55) : labelFade(transform.k, 1.05, 1.35);

  // Sparse date markers in screen space (recomputed per pan/zoom; cheap).
  const axisTicks = useMemo(() => {
    if (!colMarkers || size.w === 0) return [];
    return colMarkers
      .map((m) => ({ ...m, sx: transform.applyX(m.x) }))
      .filter((m) => m.sx > -120 && m.sx < size.w + 120);
  }, [colMarkers, transform, size.w]);

  const showAxis = mode === "timeline" && colMarkers != null;

  return (
    <div
      ref={wrapperRef}
      style={{ position: "relative", width: "100%", height: "100%", background: "var(--color-bg)", overflow: "hidden" }}
    >
      <svg ref={svgRef} width={size.w} height={size.h} style={{ display: "block", cursor: "grab" }}>
        {/* session gridlines: one hairline where each new date/time begins */}
        {showAxis && (
          <g aria-hidden>
            {axisTicks.map((tk) => (
              <line
                key={`grid-${tk.x}`}
                x1={tk.sx}
                x2={tk.sx}
                y1={0}
                y2={size.h}
                stroke="var(--color-border)"
                strokeOpacity={0.4}
              />
            ))}
          </g>
        )}

        {/* keyed by mode so switching orbit <-> timeline re-runs the fade */}
        <g
          key={mode}
          className="orbit-fade"
          transform={`translate(${transform.x},${transform.y}) scale(${transform.k})`}
        >
          {links.map((l, i) => {
            const s = typeof l.source === "string" ? nodeById.get(l.source) : l.source;
            const t = typeof l.target === "string" ? nodeById.get(l.target) : l.target;
            if (!s || !t || s.x == null || s.y == null || t.x == null || t.y == null) return null;
            const sId = typeof l.source === "string" ? l.source : l.source.id;
            const tId = typeof l.target === "string" ? l.target : l.target.id;
            const lit = isLinkLit(sId, tId);
            const emphasized = lit && (Boolean(hover) || Boolean(selectedIds?.size));
            const stroke = emphasized ? "var(--color-text-faint)" : "var(--color-border-strong)";
            // Containment (membership) edges are background in the radial view:
            // the lineage + reasoning ribs carry the story, so draw the anchor
            // fan barely-there (kept full strength in the timeline commit graph).
            const strokeOpacity = l.containment && mode !== "timeline"
              ? (lit ? 0.16 : 0.04)
              : lit ? (l.staged ? 0.4 : 0.6) : 0.12;
            const strokeWidth = emphasized ? 1.4 : 1;
            if (mode === "timeline") {
              // Horizontal-tangent cubic, like a git graph: branches peel off
              // and rejoin smoothly instead of slicing across the canvas.
              const mx = (s.x + t.x) / 2;
              return (
                <path
                  key={i}
                  className="orbit-el"
                  d={`M ${s.x} ${s.y} C ${mx} ${s.y}, ${mx} ${t.y}, ${t.x} ${t.y}`}
                  fill="none"
                  stroke={stroke}
                  strokeOpacity={strokeOpacity}
                  strokeWidth={strokeWidth}
                  strokeDasharray={l.staged ? "3 3" : undefined}
                />
              );
            }
            return (
              <line
                key={i}
                className="orbit-el"
                x1={s.x}
                y1={s.y}
                x2={t.x}
                y2={t.y}
                stroke={stroke}
                strokeOpacity={strokeOpacity}
                strokeWidth={strokeWidth}
              />
            );
          })}

          {nodes.map((n) => {
            if (n.x == null || n.y == null) return null;
            const node = byId.get(n.id);
            if (!node) return null;
            const staged = node.lifecycle === "staged";
            const sel = selectedIds?.has(n.id);
            // Color by kind (matches the index/cards); outcome is shown as a
            // small corner dot below, not by recoloring the whole glyph.
            const oc = kindColor(node.kind);
            const outcomeDot = node.outcome ? outcomeColor(node.outcome) : null;
            const hovered = hover?.id === n.id;
            const rr = hovered || sel ? n.r + 2 : n.r;
            const dim = isDimmed(n.id);
            const showLabel = mode === "timeline" || n.isRoot || nodeLabelOpacity > 0.02;
            const labelOpacity = n.isRoot
              ? Math.max(rootLabelOpacity, nodeLabelOpacity)
              : nodeLabelOpacity;
            const diamond = !n.isRoot && node.kind === "insight";
            const side = rr * 1.55;
            // Timeline labels sit *under* the node, centered in the column,
            // so they can never collide with a neighboring column's label.
            const below = mode === "timeline";
            // Per-example evaluation ring just outside the glyph; the
            // selection halo and side label step outward to clear it.
            const scorecard = scorecardsById.get(n.id) ?? null;
            const ringSegs = scorecard ? scorecardSegments(scorecard, RING_MAX_SEGMENTS) : null;
            const ringR = rr + RING_OFFSET;
            const ringSpan = ringSegs ? (2 * Math.PI) / ringSegs.length : 0;
            const ringGap = ringSegs ? Math.min(1.6 / ringR, ringSpan * 0.3) : 0;
            const labelX = ringSegs ? ringR + 8 : rr + 8;
            return (
              <g
                key={n.id}
                className="orbit-el"
                transform={`translate(${n.x},${n.y})`}
                style={{ cursor: "pointer", opacity: dim ? 0.22 : 1 }}
                onClick={(e) => handleNodeClick(n, e.shiftKey)}
                onMouseEnter={(e) => setHover({ id: n.id, x: e.clientX, y: e.clientY })}
                onMouseMove={(e) => setHover({ id: n.id, x: e.clientX, y: e.clientY })}
                onMouseLeave={() => setHover((h) => (h?.id === n.id ? null : h))}
              >
                {sel && (
                  <circle r={ringSegs ? ringR + 5 : rr + 5} fill="none" stroke="var(--color-accent)" strokeWidth={1.5} />
                )}
                {n.isRoot ? (
                  <circle r={rr} fill="var(--color-text)" stroke="var(--color-bg)" strokeWidth={1.5} />
                ) : diamond ? (
                  <rect
                    x={-side / 2}
                    y={-side / 2}
                    width={side}
                    height={side}
                    transform="rotate(45)"
                    fill={oc}
                    fillOpacity={staged ? 0.07 : 0.16}
                    stroke={oc}
                    strokeOpacity={staged ? 0.4 : hovered ? 0.95 : 0.65}
                    strokeWidth={Math.max(2, rr * 0.32)}
                    strokeDasharray={staged ? "2 2" : undefined}
                  />
                ) : (
                  <circle
                    r={rr}
                    fill={oc}
                    fillOpacity={staged ? 0.07 : 0.16}
                    stroke={oc}
                    strokeOpacity={staged ? 0.4 : hovered ? 0.95 : 0.65}
                    strokeWidth={Math.max(2, rr * 0.32)}
                    strokeDasharray={staged ? "2 2" : undefined}
                  />
                )}
                {/* scorecard ring: one arc per example, pass green / fail red */}
                {ringSegs && (
                  <g aria-hidden>
                    {ringSegs.map((pass, i) => {
                      const a0 = -Math.PI / 2 + i * ringSpan + ringGap / 2;
                      const a1 = -Math.PI / 2 + (i + 1) * ringSpan - ringGap / 2;
                      return (
                        <path
                          key={i}
                          d={ringArcPath(ringR, a0, a1)}
                          fill="none"
                          stroke={pass ? "var(--color-success)" : "var(--color-error)"}
                          strokeWidth={RING_STROKE}
                          strokeOpacity={0.9}
                        />
                      );
                    })}
                  </g>
                )}
                {/* outcome badge: small corner dot, so kind color stays intact */}
                {outcomeDot && !n.isRoot && (
                  <circle
                    cx={rr * 0.95}
                    cy={-rr * 0.95}
                    r={Math.max(3, rr * 0.4)}
                    fill={outcomeDot}
                    stroke="var(--color-bg)"
                    strokeWidth={1.5}
                  />
                )}
                {showLabel && labelOpacity > 0.02 && (
                  <text
                    x={below ? 0 : labelX}
                    y={below ? rr + 15 : 0}
                    dy={below ? 0 : "0.34em"}
                    textAnchor={below ? "middle" : "start"}
                    fontSize={below ? 10 : n.isRoot ? 13 : 11}
                    fontWeight={n.isRoot ? 500 : 400}
                    fill={n.isRoot ? "var(--color-text)" : "var(--color-text-muted)"}
                    fillOpacity={hovered ? 1 : labelOpacity}
                    style={{ fontFamily: SERIF, pointerEvents: "none" }}
                  >
                    {truncate(node.title || node.slug_name || "untitled", below ? 17 : 26)}
                  </text>
                )}
              </g>
            );
          })}
        </g>

        {/* date strip: fixed to the bottom, one label per new date/time */}
        {showAxis && (
          <g aria-hidden>
            <rect x={0} y={size.h - 26} width={size.w} height={26} fill="var(--color-bg)" fillOpacity={0.88} />
            <line x1={0} x2={size.w} y1={size.h - 26} y2={size.h - 26} stroke="var(--color-border)" />
            {axisTicks.map((tk) => (
              <g key={`tick-${tk.x}`}>
                <line x1={tk.sx} x2={tk.sx} y1={size.h - 26} y2={size.h - 21} stroke="var(--color-border-strong)" />
                <text
                  x={tk.sx + 5}
                  y={size.h - 9}
                  fontSize={9}
                  fill="var(--color-text-faint)"
                  style={{ fontFamily: MONO, pointerEvents: "none" }}
                >
                  {tk.label}
                </text>
              </g>
            ))}
          </g>
        )}
      </svg>

      {hoveredNode && hover && <OrbitTooltip x={hover.x} y={hover.y} node={hoveredNode} byId={byId} />}

      {/* zoom / pan controls */}
      <div
        style={{
          position: "absolute",
          right: 16,
          top: 56,
          display: "flex",
          flexDirection: "column",
          gap: 2,
          padding: 3,
          background: "var(--color-surface-solid)",
          border: "1px solid var(--color-border)",
          borderRadius: 2,
          boxShadow: "var(--glass-shadow)",
        }}
      >
        <button type="button" onClick={() => zoomBy(1.4)} title="Zoom in" aria-label="Zoom in" style={zoomBtnStyle}>
          <Plus size={13} />
        </button>
        <button type="button" onClick={() => zoomBy(1 / 1.4)} title="Zoom out" aria-label="Zoom out" style={zoomBtnStyle}>
          <Minus size={13} />
        </button>
        <button type="button" onClick={() => fitView(true)} title="Reset view" aria-label="Reset view" style={zoomBtnStyle}>
          <Maximize size={12} />
        </button>
      </div>

      <OrbitLegend />
    </div>
  );
}

const zoomBtnStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  width: 24,
  height: 24,
  border: "none",
  borderRadius: 2,
  background: "transparent",
  color: "var(--color-text-muted)",
  cursor: "pointer",
};

function LegendGlyph({ shape, color }: { shape: "root" | "circle" | "diamond" | "staged" | "dot"; color: string }) {
  return (
    <svg width={11} height={11} viewBox="0 0 12 12" aria-hidden style={{ flexShrink: 0, color }}>
      {shape === "root" && <circle cx={6} cy={6} r={4.5} fill="var(--color-text)" />}
      {shape === "circle" && <circle cx={6} cy={6} r={4} fill="currentColor" fillOpacity={0.16} stroke="currentColor" strokeWidth={1.8} />}
      {shape === "diamond" && (
        <rect x={2.6} y={2.6} width={6.8} height={6.8} transform="rotate(45 6 6)" fill="currentColor" fillOpacity={0.16} stroke="currentColor" strokeWidth={1.6} />
      )}
      {shape === "staged" && (
        <circle cx={6} cy={6} r={4} fill="none" stroke="currentColor" strokeWidth={1.6} strokeDasharray="2 2" />
      )}
      {shape === "dot" && <circle cx={6} cy={6} r={3.4} fill="currentColor" />}
    </svg>
  );
}

function LegendItem({
  shape,
  color,
  label,
}: {
  shape: "root" | "circle" | "diamond" | "staged" | "dot";
  color: string;
  label: string;
}) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
      <LegendGlyph shape={shape} color={color} />
      <span style={{ color: "var(--color-text-muted)" }}>{label}</span>
    </span>
  );
}

const legendRowStyle: CSSProperties = { display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" };

/**
 * Two-line decoder pinned top-left — the one canvas corner that stays clear
 * of the page chrome (zoom controls top-right, workspace pill bottom-left,
 * multi-select bar bottom-center, FAB bottom-right). Top row = kinds (the
 * node color), bottom row = outcome dots + interaction hints.
 */
function OrbitLegend() {
  const [open, setOpen] = useState(false); // collapsed by default; click to reveal
  return (
    <div
      style={{
        position: "absolute",
        left: 16,
        top: 16,
        display: "flex",
        flexDirection: "column",
        alignItems: "flex-start",
        gap: 6,
        pointerEvents: "none",
        userSelect: "none",
      }}
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        title={open ? "Hide legend" : "Show legend"}
        style={{
          pointerEvents: "auto",
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
          padding: "5px 11px",
          background: "var(--color-surface)",
          border: "1px solid var(--color-border)",
          borderRadius: 2,
          boxShadow: "var(--glass-shadow)",
          fontFamily: MONO,
          fontSize: 11,
          color: "var(--color-text-muted)",
          cursor: "pointer",
        }}
      >
        <span style={{ fontSize: 9, opacity: 0.7 }}>{open ? "▾" : "▸"}</span>
        Legend
      </button>
      {open && (
        <div
          aria-hidden
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 9,
            maxWidth: "min(540px, 64vw)",
            padding: "10px 13px",
            background: "var(--color-surface)",
            border: "1px solid var(--color-border)",
            borderRadius: 2,
            boxShadow: "var(--glass-shadow)",
            fontFamily: MONO,
            fontSize: 10,
            color: "var(--color-text-muted)",
          }}
        >
          <div style={legendGroupStyle}>
            <span style={legendGroupLabelStyle}>kinds</span>
            <div style={legendRowStyle}>
              <LegendItem shape="root" color="var(--color-text)" label="root" />
              <LegendItem shape="diamond" color="var(--kind-insight)" label="insight" />
              <LegendItem shape="circle" color="var(--kind-empirical)" label="empirical" />
              <LegendItem shape="circle" color="var(--kind-hypothesis)" label="hypothesis" />
              <LegendItem shape="circle" color="var(--kind-decision)" label="decision" />
            </div>
          </div>
          <div style={legendGroupStyle}>
            <span style={legendGroupLabelStyle}>status</span>
            <div style={{ ...legendRowStyle, color: "var(--color-text-faint)" }}>
              <LegendItem shape="dot" color="var(--color-success)" label="done" />
              <LegendItem shape="dot" color="var(--color-error)" label="failed" />
              <LegendItem shape="staged" color="var(--color-text-faint)" label="staged" />
            </div>
          </div>
          <div style={{ fontSize: 9.5, color: "var(--color-text-faint)", paddingTop: 1 }}>
            click to focus · ⇧ click to select · esc to clear
          </div>
        </div>
      )}
    </div>
  );
}

const legendGroupStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 10,
  flexWrap: "wrap",
};

const legendGroupLabelStyle: CSSProperties = {
  fontFamily: MONO,
  fontSize: 9,
  letterSpacing: "0.04em",
  color: "var(--color-text-faint)",
  minWidth: 44,
};

function OrbitTooltip({
  x,
  y,
  node,
  byId,
}: {
  x: number;
  y: number;
  node: Node;
  byId: Map<string, Node>;
}) {
  const segs = computeSegments(node, byId);
  const completed = segs.filter((s) => s === "completed").length;
  const scorecard = scorecardOf(node);
  const updatedRel = timeAgo(node.updated_at);
  const updatedAbs = shortDateTime(node.updated_at);
  return (
    <div
      style={{
        position: "fixed",
        left: x + 16,
        top: y + 16,
        zIndex: 50,
        pointerEvents: "none",
        maxWidth: 300,
        background: "var(--color-surface-solid)",
        border: "1px solid var(--color-border-strong)",
        borderRadius: 4,
        boxShadow: "var(--shadow-md)",
        padding: "8px 11px",
      }}
    >
      <div style={{ fontFamily: SERIF, fontSize: 13, fontWeight: 500, color: "var(--color-text)", lineHeight: 1.3 }}>
        {node.title || node.slug_name || "untitled"}
      </div>
      <div style={{ marginTop: 4, fontFamily: MONO, fontSize: 9.5, color: "var(--color-text-faint)" }}>
        {node.kind}
        {" · "}
        {node.outcome ?? (node.lifecycle === "staged" ? "staged" : "untyped")}
        {segs.length ? ` · ${completed}/${segs.length} children done` : ""}
      </div>
      {scorecard && (
        <div style={{ marginTop: 2, fontFamily: MONO, fontSize: 9.5, color: "var(--color-text-faint)" }}>
          {scorecard.passed}/{scorecard.total} examples passed
        </div>
      )}
      {updatedRel && (
        <div style={{ marginTop: 2, fontFamily: MONO, fontSize: 9.5, color: "var(--color-text-faint)" }}>
          updated {updatedRel}
          {updatedAbs ? ` · ${updatedAbs}` : ""}
        </div>
      )}
      {node.summary && (
        <div
          style={{
            marginTop: 6,
            fontFamily: SERIF,
            fontSize: 11.5,
            color: "var(--color-text-muted)",
            lineHeight: 1.5,
            display: "-webkit-box",
            WebkitLineClamp: 3,
            WebkitBoxOrient: "vertical",
            overflow: "hidden",
          }}
        >
          {node.summary}
        </div>
      )}
    </div>
  );
}
