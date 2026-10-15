import React, { useEffect, useState, useCallback, useMemo, Suspense } from "react";
import { useNodeStore } from "../../stores/nodeStore";
import { Layout } from "../Layout";
import { SpotlightSearch } from "./SpotlightSearch";
import { FloatingActionButton } from "./FloatingActionButton";
import { GraphListPanel } from "./GraphListPanel";
import type { ViewMode } from "./ViewModeToggle";
import type { GraphStyle } from "../graph/useGraphLayout";
import { GraphSkeleton } from "../shared/Skeletons";
import { safeLocalStorage } from "../../lib/safeStorage";

const GraphCanvas = React.lazy(() =>
  import("../graph/GraphCanvas").then((m) => ({ default: m.GraphCanvas }))
);

const VIEW_MODE_KEY = "dashboard.viewMode";
const GRAPH_STYLE_KEY = "dashboard.graphStyle";
const ACTIVE_GRAPH_KEY = "dashboard.activeGraph";

// These run inside useState initializers on the first render of /graphs, so
// they must never throw when site storage is blocked.
function loadActiveGraph(): string | null {
  return safeLocalStorage.getItem(ACTIVE_GRAPH_KEY);
}

function loadViewMode(): ViewMode {
  return safeLocalStorage.getItem(VIEW_MODE_KEY) === "timeline" ? "timeline" : "graph";
}

function loadGraphStyle(): GraphStyle {
  return safeLocalStorage.getItem(GRAPH_STYLE_KEY) === "orbit" ? "orbit" : "cards";
}

export function Dashboard() {
  const treeData = useNodeStore((s) => s.treeData);
  const nodes = useNodeStore((s) => s.nodes);
  const fetchNodes = useNodeStore((s) => s.fetchNodes);
  const fetchNodeTree = useNodeStore((s) => s.fetchNodeTree);
  const listLoading = useNodeStore((s) => s.listLoading);
  const treeLoading = useNodeStore((s) => s.treeLoading);

  const [activeGraphId, setActiveGraphId] = useState<string | null>(loadActiveGraph);
  const [viewMode, setViewModeState] = useState<ViewMode>(loadViewMode);
  const [graphStyle, setGraphStyleState] = useState<GraphStyle>(loadGraphStyle);

  const setViewMode = useCallback((mode: ViewMode) => {
    setViewModeState(mode);
    safeLocalStorage.setItem(VIEW_MODE_KEY, mode);
  }, []);

  const setGraphStyle = useCallback((style: GraphStyle) => {
    setGraphStyleState(style);
    safeLocalStorage.setItem(GRAPH_STYLE_KEY, style);
  }, []);

  useEffect(() => {
    fetchNodes({ rootOnly: true });
    // Pre-warm the GraphCanvas chunk in parallel with the list fetch
    // so the user doesn't pay JS-chunk load + tree load serially. The
    // import is the same one ``React.lazy`` does at line 11; the
    // browser dedupes it.
    import("../graph/GraphCanvas").catch(() => {
      /* network jitter - React.lazy will retry on actual render */
    });
  }, [fetchNodes]);

  // Speculatively load the last-viewed graph's tree on mount, in parallel with
  // the (slower) list fetch, so the canvas isn't blocked behind it. If the
  // remembered graph is still the active one - the common case - its tree is
  // ready by the time the list lands; fetchNodeTree dedupes the redundant call
  // the effect below would otherwise make.
  useEffect(() => {
    const remembered = loadActiveGraph();
    if (remembered) fetchNodeTree(remembered);
    // mount only - intentionally empty deps
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Remember the active graph so the next visit can prefetch its tree.
  useEffect(() => {
    if (activeGraphId) safeLocalStorage.setItem(ACTIVE_GRAPH_KEY, activeGraphId);
  }, [activeGraphId]);

  const rootGraphs = useMemo(
    () => nodes.filter((n) => !n.parent_ids || n.parent_ids.length === 0),
    [nodes],
  );

  useEffect(() => {
    if (rootGraphs.length === 0) {
      if (activeGraphId) setActiveGraphId(null);
      return;
    }

    const activeGraphStillVisible = rootGraphs.some(
      (graph) => graph.node_id === activeGraphId
    );
    if (!activeGraphId || !activeGraphStillVisible) {
      const firstRoot = rootGraphs[0].node_id;
      setActiveGraphId(firstRoot);
      fetchNodeTree(firstRoot);
    }
  }, [rootGraphs, activeGraphId, fetchNodeTree]);

  const handleSelectGraph = useCallback(
    (nodeId: string) => {
      setActiveGraphId(nodeId);
      fetchNodeTree(nodeId);
    },
    [fetchNodeTree]
  );

  const activeTreeData =
    treeData && treeData.anchor_node_id === activeGraphId ? treeData : null;
  const nodeCount = activeTreeData?.nodes?.length ?? 0;
  const activeGraph = rootGraphs.find((g) => g.node_id === activeGraphId);
  const isGraphPending =
    listLoading || treeLoading || (rootGraphs.length > 0 && !activeTreeData);
  // While the list/tree are still loading we don't actually know whether the
  // user has zero graphs or many, so don't shout "no graph" at them - show
  // a quiet loading hint and reserve "no graph" for the truly-empty state.
  const activeGraphName = activeGraph?.title
    ? activeGraph.title
    : activeGraph?.node_id
      ? activeGraph.node_id.slice(0, 8)
      : isGraphPending
        ? "loading…"
        : "no graph";

  return (
    <Layout>
      <div style={dashboardShellStyle}>
        <div className="atlas-dashboard-topbar" style={topBarStyle}>
          <div style={titleColStyle}>
            <div style={eyebrowStyle}>graphs</div>
            <div style={graphTitleStyle}>
              {/* Pulsing dot is a stronger in-progress signal than "loading…"
                  alone — confirms the request is in flight rather than stuck. */}
              {isGraphPending && (
                <span
                  aria-label="loading"
                  style={pulsingDotStyle}
                />
              )}
              {activeGraphName}
            </div>
          </div>
          <div className="atlas-dashboard-controls" style={controlsRowStyle}>
            <div style={segmentStyle}>
              {(["graph", "timeline"] as ViewMode[]).map((mode) => (
                <button
                  key={mode}
                  onClick={() => setViewMode(mode)}
                  style={segmentButtonStyle(viewMode === mode)}
                >
                  {mode}
                </button>
              ))}
            </div>
            {viewMode === "graph" && (
              <div style={segmentStyle}>
                {(["cards", "orbit"] as GraphStyle[]).map((style) => (
                  <button
                    key={style}
                    onClick={() => setGraphStyle(style)}
                    style={segmentButtonStyle(graphStyle === style)}
                  >
                    {style}
                  </button>
                ))}
              </div>
            )}
            <div style={statStyle}>
              <strong>{nodeCount}</strong>
              <span>{isGraphPending ? "loading" : "nodes"}</span>
            </div>
          </div>
        </div>

        <div style={canvasFrameStyle}>
          {isGraphPending ? (
            <GraphSkeleton />
          ) : activeTreeData ? (
            <Suspense fallback={<GraphSkeleton />}>
              <GraphCanvas
                treeData={activeTreeData}
                navigateOnClick
                nodeCount={nodeCount}
                graphStyle={viewMode === "timeline" ? "timeline" : graphStyle}
              />
            </Suspense>
          ) : (
            <GraphSkeleton />
          )}

          <SpotlightSearch />

          <GraphListPanel
            rootGraphs={rootGraphs}
            activeGraphId={activeGraphId}
            activeGraphName={activeGraphName}
            nodeCount={nodeCount}
            onSelectGraph={handleSelectGraph}
          />

          <FloatingActionButton />
        </div>
      </div>
    </Layout>
  );
}

const mono = "'JetBrains Mono', monospace";
const sans = "'Computer Modern', 'Latin Modern Roman', Georgia, 'Times New Roman', serif";

const dashboardShellStyle: React.CSSProperties = {
  flex: 1,
  display: "grid",
  gridTemplateRows: "auto 1fr",
  minWidth: 0,
  minHeight: 0,
  background: "var(--color-bg)",
};

const topBarStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  flexWrap: "wrap",
  gap: 12,
  padding: "10px 18px",
  borderBottom: "1px solid var(--color-border)",
  background: "var(--color-bg)",
};

const titleColStyle: React.CSSProperties = {
  minWidth: 0,
  flex: 1,
};

const controlsRowStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  flexWrap: "wrap",
  gap: 8,
  minWidth: 0,
  maxWidth: "100%",
  flexShrink: 1,
};

const eyebrowStyle: React.CSSProperties = {
  fontFamily: sans,
  fontSize: 9,
  letterSpacing: "0.14em",
  color: "var(--color-text-faint)",
};

const graphTitleStyle: React.CSSProperties = {
  marginTop: 2,
  fontFamily: sans,
  fontSize: 14,
  fontWeight: 500,
  color: "var(--color-text)",
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
  display: "flex",
  alignItems: "center",
  gap: 8,
};

// Reuses the ``thesis-pulse-dot`` keyframes injected by Skeletons.tsx so we
// don't need to add another @keyframes block.
const pulsingDotStyle: React.CSSProperties = {
  display: "inline-block",
  width: 6,
  height: 6,
  borderRadius: "50%",
  background: "var(--color-text-muted)",
  animation: "thesis-pulse-dot 1.2s ease-in-out infinite",
};

const segmentStyle: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 2,
  padding: 2,
  border: "1px solid var(--color-border)",
  background: "var(--color-bg-subtle)",
};

const segmentButtonStyle = (active: boolean): React.CSSProperties => ({
  border: "none",
  background: active ? "var(--color-bg-elevated)" : "transparent",
  color: active ? "var(--color-text)" : "var(--color-text-muted)",
  fontFamily: sans,
  fontSize: 11,
  padding: "4px 9px",
  cursor: "pointer",
});

const statStyle: React.CSSProperties = {
  minWidth: 56,
  display: "flex",
  flexDirection: "column",
  alignItems: "flex-end",
  gap: 1,
  fontFamily: mono,
  color: "var(--color-text-faint)",
  fontSize: 9,
  letterSpacing: "0.08em",
};

const canvasFrameStyle: React.CSSProperties = {
  position: "relative",
  display: "flex",
  flexDirection: "column",
  minWidth: 0,
  minHeight: 0,
  width: "100%",
  height: "100%",
  overflow: "hidden",
};
