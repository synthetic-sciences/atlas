import type { Node, NodeOutcome } from "../../api/types.js";

/**
 * Color + child helpers for the orbit / timeline graph styles (OrbitGraph).
 * Outcome tones use Atlas design tokens so the graph stays cohesive with the
 * rest of the app and adapts to light/dark.
 */

export const ORBIT_COLORS = {
  completed: "var(--color-success)",
  failed: "var(--color-error)",
  canceled: "var(--color-warning)",
  none: "var(--color-text-faint)",
} as const;

export function outcomeColor(outcome: NodeOutcome | null | undefined): string {
  switch (outcome) {
    case "completed":
      return ORBIT_COLORS.completed;
    case "failed":
      return ORBIT_COLORS.failed;
    case "canceled":
      return ORBIT_COLORS.canceled;
    default:
      return ORBIT_COLORS.none;
  }
}

/**
 * Node color by kind, matching the card/index palette so the same node reads
 * the same in both views. Kind is the node's identity; outcome is shown
 * separately (a corner dot in the graph, a chip on the card).
 */
export function kindColor(kind: string | null | undefined): string {
  switch (kind) {
    case "insight":
      return "var(--kind-insight)";
    case "empirical":
      return "var(--kind-empirical)";
    case "hypothesis":
      return "var(--kind-hypothesis)";
    case "decision":
      return "var(--kind-decision)";
    default:
      return "var(--kind-untyped)";
  }
}

/** Outcomes of each child present in the tree, in child_ids order. */
export function computeSegments(
  node: Node,
  byId: Map<string, Node>,
): (NodeOutcome | null)[] {
  const segments: (NodeOutcome | null)[] = [];
  for (const childId of node.child_ids || []) {
    const child = byId.get(childId);
    if (child) segments.push(child.outcome ?? null);
  }
  return segments;
}

/* ── semantic_data parsing (shared by OrbitGraph / ResearchNodeCard / NodeSidebar) ── */

/**
 * Anything that carries a `semantic_data` field. Typed loosely because some
 * backend paths deliver the payload as a JSON string rather than an object.
 */
type SemanticCarrier = { semantic_data?: Record<string, unknown> | string | null };

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

const str = (v: unknown): string | null => (typeof v === "string" && v.length > 0 ? v : null);
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

/** Safely materialize semantic_data as an object (accepts object or JSON string). */
export function parseSemanticData(node: SemanticCarrier): Record<string, unknown> | null {
  const raw: unknown = node.semantic_data;
  if (raw == null) return null;
  if (typeof raw === "string") {
    try {
      const parsed: unknown = JSON.parse(raw);
      return isRecord(parsed) ? parsed : null;
    } catch {
      return null;
    }
  }
  return isRecord(raw) ? raw : null;
}

export interface ScorecardItem {
  ref: string | null;
  score: number | null;
  pass: boolean;
}

/** Per-example evaluation results (semantic_data.scorecard, spec evaluation_v1). */
export interface Scorecard {
  metric: string | null;
  items: ScorecardItem[];
  /** Aggregate counts: backend numbers when present, else derived from items. */
  passed: number;
  total: number;
  score: number | null;
}

/**
 * Parse semantic_data.scorecard. Returns null unless spec === "evaluation_v1"
 * and items is a non-empty array.
 */
export function scorecardOf(node: SemanticCarrier): Scorecard | null {
  const sd = parseSemanticData(node);
  if (!sd) return null;
  let raw: unknown = sd.scorecard;
  if (typeof raw === "string") {
    try {
      raw = JSON.parse(raw);
    } catch {
      return null;
    }
  }
  if (!isRecord(raw) || raw.spec !== "evaluation_v1" || !Array.isArray(raw.items)) return null;
  const items: ScorecardItem[] = raw.items.filter(isRecord).map((it) => ({
    ref: str(it.ref),
    score: num(it.score),
    pass: it.pass === true,
  }));
  if (items.length === 0) return null;
  const agg = isRecord(raw.aggregate) ? raw.aggregate : null;
  const aggN = num(agg?.n);
  const aggPassed = num(agg?.passed);
  return {
    metric: str(raw.metric),
    items,
    passed: aggPassed ?? items.filter((i) => i.pass).length,
    total: aggN != null && aggN > 0 ? aggN : items.length,
    score: num(agg?.score),
  };
}

/**
 * Pass/fail flags for rendering, deterministically downsampled to at most
 * `max` segments (evenly strided over the items) so dense scorecards stay
 * legible at glyph scale.
 */
export function scorecardSegments(sc: Scorecard, max: number): boolean[] {
  const n = sc.items.length;
  if (n <= max) return sc.items.map((i) => i.pass);
  const out: boolean[] = [];
  for (let i = 0; i < max; i++) out.push(sc.items[Math.floor((i * n) / max)].pass);
  return out;
}

export type OptimizeRunStatus = "running" | "done" | "error" | "stopped";

/** Normalized view of an optimize_run control node's semantic_data. */
export interface OptimizeRun {
  objective: string | null;
  target: string | null;
  metric: string | null;
  status: OptimizeRunStatus | null;
  budgetTotal: number | null;
  budgetUsed: number | null;
  stallLimit: number | null;
  bestScore: number | null;
  bestNodeId: string | null;
  candidatesEvaluated: number | null;
  paretoSize: number | null;
  stopReason: string | null;
  runDir: string | null;
  updatedAt: string | null;
}

const OPTIMIZE_STATUSES = new Set<string>(["running", "done", "error", "stopped"]);

/** Parse an optimize_run control payload; null unless type === "optimize_run". */
export function optimizeRunOf(node: SemanticCarrier): OptimizeRun | null {
  const sd = parseSemanticData(node);
  if (!sd || sd.type !== "optimize_run") return null;
  const status = str(sd.status);
  return {
    objective: str(sd.objective),
    target: str(sd.target),
    metric: str(sd.metric),
    status: status && OPTIMIZE_STATUSES.has(status) ? (status as OptimizeRunStatus) : null,
    budgetTotal: num(sd.budget_total),
    budgetUsed: num(sd.budget_used),
    stallLimit: num(sd.stall_limit),
    bestScore: num(sd.best_score),
    bestNodeId: str(sd.best_node_id),
    candidatesEvaluated: num(sd.candidates_evaluated),
    paretoSize: num(sd.pareto_size),
    stopReason: str(sd.stop_reason),
    runDir: str(sd.run_dir),
    updatedAt: str(sd.updated_at),
  };
}

/** Short score formatting for microcopy: 0.81, 0.5, 12.3. */
export function formatScore(v: number): string {
  return String(Math.round(v * 100) / 100);
}

/** A node's headline numeric score, dug out of semantic_data. */
export interface NodeScore {
  value: number;
  /** The metric key it came from (e.g. "val_bpb", "best_score"). */
  metric: string;
  /** True when a smaller value is better (loss/bpb/error/perplexity). */
  lowerIsBetter: boolean;
}

const _LOWER_IS_BETTER =
  /loss|bpb|bits.?per.?byte|error|err|perplex|ppl|nll|rank|regret|fid|time|second|minute|latency|wall|steps|duration/i;

function _lowerIsBetter(metric: string): boolean {
  return _LOWER_IS_BETTER.test(metric);
}

/**
 * Extract a node's headline numeric score from semantic_data, for layouts that
 * position by result (the progression view). Looks at, in order:
 * ``metrics.<first numeric>`` (the run:record shape), ``best_score`` (optimize
 * control nodes), then a scorecard aggregate. Returns null when the node has no
 * numeric result -- those nodes (notes, decisions, the root) sit off the curve.
 */
export function scoreOf(node: SemanticCarrier): NodeScore | null {
  const sd = parseSemanticData(node);
  if (!sd) return null;

  const metrics = sd.metrics;
  if (isRecord(metrics)) {
    // Prefer a conventionally-named metric, else the first finite number.
    const keys = Object.keys(metrics);
    const preferred = keys.find((k) => _LOWER_IS_BETTER.test(k)) ?? keys[0];
    for (const k of preferred ? [preferred, ...keys] : keys) {
      const v = num(metrics[k]);
      if (v != null) return { value: v, metric: k, lowerIsBetter: _lowerIsBetter(k) };
    }
  }

  const best = num(sd.best_score);
  if (best != null) {
    const m = str(sd.metric) ?? "score";
    return { value: best, metric: m, lowerIsBetter: _lowerIsBetter(m) };
  }

  const sc = scorecardOf(node);
  if (sc?.score != null) {
    const m = sc.metric ?? "score";
    return { value: sc.score, metric: m, lowerIsBetter: _lowerIsBetter(m) };
  }
  return null;
}

/* ── Time helpers (shared by the orbit/timeline views and node cards) ── */

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/** Compact relative timestamp: "just now", "4m ago", "3h ago", "12d ago". */
export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "";
  const ms = Date.now() - new Date(iso).getTime();
  if (!isFinite(ms)) return "";
  if (ms < MINUTE) return "just now";
  if (ms < HOUR) return `${Math.floor(ms / MINUTE)}m ago`;
  if (ms < DAY) return `${Math.floor(ms / HOUR)}h ago`;
  const days = Math.floor(ms / DAY);
  if (days < 365) return `${days}d ago`;
  return `${Math.floor(days / 365)}y ago`;
}

/** Short absolute timestamp: "Jun 3, 2026, 14:05". */
export function shortDateTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (!isFinite(d.getTime())) return "";
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/**
 * Label for a timeline column at timestamp `t`, given the full graph span.
 * The timeline lays nodes out in time *order* (ordinal columns), so markers
 * are emitted where this label changes rather than at fixed intervals:
 * sub-2-day graphs get clock times, longer spans get calendar dates.
 */
export function columnLabel(t: number, span: number): string {
  const d = new Date(t);
  if (span <= 36 * HOUR) {
    return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  }
  if (span <= 300 * DAY) {
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }
  return d.toLocaleDateString(undefined, { month: "short", year: "numeric" });
}
