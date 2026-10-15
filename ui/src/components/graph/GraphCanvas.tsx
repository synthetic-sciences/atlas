import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  useNodesState,
  useEdgesState,
  useReactFlow,
  ReactFlowProvider,
  type Node as RFNode,
  type NodeMouseHandler,
  type Connection,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useNavigate } from "react-router-dom";

import { ResearchNodeCard } from "./ResearchNodeCard.js";
import { GroupFrameNode } from "./GroupFrameNode.js";
import { OrbitGraph } from "./OrbitGraph.js";
import { useGraphLayout, type GraphStyle } from "./useGraphLayout.js";
import { useNodeStore } from "../../stores/nodeStore.js";
import { api } from "../../api/client.js";
import type { NodeTreeResponse } from "../../api/types.js";
import { useToast } from "../../lib/useToast.js";

export const MultiSelectContext = React.createContext<Set<string>>(new Set());

const nodeTypes = {
  "research-node": ResearchNodeCard,
  "group-frame": GroupFrameNode,
};

const ASCII_EMPTY = `
          \u2591\u2591\u2591
       \u2591\u2591     \u2591\u2591
     \u2591\u2591  \u25CB   \u25CB  \u2591\u2591
    \u2591\u2591   \u2502   \u2502   \u2591\u2591
    \u2591  \u25CB\u2500\u2500\u2500\u25CB\u2500\u2500\u2500\u25CB  \u2591
    \u2591\u2591   \u2502       \u2591\u2591
     \u2591\u2591  \u25CB       \u2591
       \u2591\u2591     \u2591\u2591
          \u2591\u2591\u2591
`;

interface GraphCanvasProps {
  treeData: NodeTreeResponse | null;
  /** If true, clicking a node navigates to /nodes/:id instead of selecting */
  navigateOnClick?: boolean;
  /** If true, render without graph mutation or protected navigation controls. */
  readOnly?: boolean;
  /** Optional node click callback for read-only graph browsers. */
  onReadOnlyNodeClick?: (nodeId: string | null) => void;
  /** Current node count to display */
  nodeCount?: number;
  /** Node rendering style: classic cards or the donut/orbit view. */
  graphStyle?: GraphStyle;
}

export function GraphCanvas({
  treeData,
  navigateOnClick,
  readOnly,
  onReadOnlyNodeClick,
  nodeCount,
  graphStyle,
}: GraphCanvasProps) {
  return (
    <ReactFlowProvider>
      <GraphCanvasInner
        treeData={treeData}
        navigateOnClick={navigateOnClick}
        readOnly={readOnly}
        onReadOnlyNodeClick={onReadOnlyNodeClick}
        nodeCount={nodeCount}
        graphStyle={graphStyle}
      />
    </ReactFlowProvider>
  );
}

function GraphCanvasInner({
  treeData,
  navigateOnClick,
  readOnly = false,
  onReadOnlyNodeClick,
  graphStyle = "cards",
}: GraphCanvasProps) {
  const { nodes: layoutNodes, edges: layoutEdges } = useGraphLayout(
    treeData,
    graphStyle
  );
  const [nodes, setNodes, onNodesChange] = useNodesState(layoutNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(layoutEdges);
  const selectNode = useNodeStore((s) => s.selectNode);
  const selectedNodeId = useNodeStore((s) => s.selectedNodeId);
  const fetchNodes = useNodeStore((s) => s.fetchNodes);
  // Distinguishes the cold-load skeleton (treeLoading=true) from the
  // genuine empty state (treeData loaded but no nodes). Without this the
  // canvas flashed "no nodes yet" while the request was still in flight.
  const treeLoading = useNodeStore((s) => s.treeLoading);
  const toast = useToast();
  const navigate = useNavigate();
  useReactFlow(); // keep provider context active
  const importInputRef = useRef<HTMLInputElement>(null);
  const [importing, setImporting] = useState(false);
  const [multiSelectedIds, setMultiSelectedIds] = useState<Set<string>>(
    new Set()
  );
  const [exporting, setExporting] = useState(false);

  // Sync layout results when the graph projection changes.
  useEffect(() => {
    setNodes(layoutNodes);
    setEdges(layoutEdges);
  }, [layoutNodes, layoutEdges, setNodes, setEdges]);

  const toggleMultiSelect = useCallback((nodeId: string) => {
    setMultiSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(nodeId)) {
        next.delete(nodeId);
      } else {
        next.add(nodeId);
      }
      return next;
    });
  }, []);

  const onNodeClick: NodeMouseHandler = useCallback(
    (event: React.MouseEvent, node: RFNode) => {
      if (readOnly) {
        setMultiSelectedIds(new Set());
        onReadOnlyNodeClick?.(node.id);
      } else if (event.shiftKey) {
        toggleMultiSelect(node.id);
      } else if (navigateOnClick) {
        setMultiSelectedIds(new Set());
        navigate(`/nodes/${node.id}`);
      } else {
        setMultiSelectedIds(new Set());
        selectNode(node.id);
      }
    },
    [selectNode, toggleMultiSelect, navigateOnClick, navigate, readOnly, onReadOnlyNodeClick]
  );

  const onOrbitNodeClick = useCallback(
    (id: string, shiftKey: boolean) => {
      if (readOnly) {
        setMultiSelectedIds(new Set());
        onReadOnlyNodeClick?.(id);
      } else if (shiftKey) {
        toggleMultiSelect(id);
      } else if (navigateOnClick) {
        setMultiSelectedIds(new Set());
        navigate(`/nodes/${id}`);
      } else {
        setMultiSelectedIds(new Set());
        selectNode(id);
      }
    },
    [readOnly, onReadOnlyNodeClick, toggleMultiSelect, navigateOnClick, navigate, selectNode]
  );

  const orbitSelectedIds = useMemo(() => {
    const ids = new Set(multiSelectedIds);
    if (selectedNodeId) ids.add(selectedNodeId);
    return ids;
  }, [multiSelectedIds, selectedNodeId]);

  const onPaneClick = useCallback(() => {
    setMultiSelectedIds(new Set());
    if (readOnly) {
      onReadOnlyNodeClick?.(null);
    } else {
      selectNode(null);
    }
  }, [selectNode, readOnly, onReadOnlyNodeClick]);

  // Escape clears selection (multi-select + focused node), unless the user
  // is typing in an input/textarea elsewhere on the page.
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      const target = e.target as HTMLElement | null;
      const tag = target?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || target?.isContentEditable) return;
      onPaneClick();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onPaneClick]);

  const handleImport = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file) return;
      setImporting(true);
      try {
        const text = await file.text();
        const data = JSON.parse(text);
        await api.importSubgraph(data);
        await fetchNodes();
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "import failed");
      } finally {
        setImporting(false);
        if (importInputRef.current) importInputRef.current.value = "";
      }
    },
    [fetchNodes, toast]
  );

  const handleExportJson = useCallback(async () => {
    if (multiSelectedIds.size === 0) return;
    setExporting(true);
    try {
      const result = await api.exportSubgraph(Array.from(multiSelectedIds));
      const blob = new Blob([JSON.stringify(result, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "thesis-export.json";
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "export failed");
    } finally {
      setExporting(false);
    }
  }, [multiSelectedIds, toast]);

  const handleExportMarkdown = useCallback(async () => {
    if (multiSelectedIds.size === 0) return;
    setExporting(true);
    try {
      const result = await api.exportMarkdown(Array.from(multiSelectedIds));
      const text =
        typeof result === "string"
          ? result
          : (result as Record<string, unknown>).markdown ??
            (result as Record<string, unknown>).content ??
            JSON.stringify(result, null, 2);
      const blob = new Blob([String(text)], { type: "text/markdown" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "thesis-export.md";
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "export failed");
    } finally {
      setExporting(false);
    }
  }, [multiSelectedIds, toast]);

  const onConnect = useCallback(async (connection: Connection) => {
    if (!connection.source || !connection.target) return;
    try {
      // source = parent, target = child (top-down DAG direction)
      const [parent, child] = await Promise.all([
        api.getNode(connection.source, "core"),
        api.getNode(connection.target, "core"),
      ]);
      await api.addParent({
        node_id: connection.target,
        parent_id: connection.source,
        expected_revision: child.revision,
        expected_parent_revision: parent.revision,
      });
      // Refresh tree
      const { treeData } = useNodeStore.getState();
      if (treeData) await useNodeStore.getState().fetchNodeTree(treeData.anchor_node_id);
    } catch (err) {
      console.error("Failed to add parent:", err);
    }
  }, []);

  const [deleting, setDeleting] = useState(false);

  const handleBulkDelete = useCallback(async () => {
    if (multiSelectedIds.size === 0) return;
    const ids = Array.from(multiSelectedIds);
    const confirmed = window.confirm(
      `Delete ${ids.length} node${ids.length > 1 ? "s" : ""}? This cannot be undone.`
    );
    if (!confirmed) return;
    setDeleting(true);
    try {
      await api.bulkDeleteNodes(ids);
      setMultiSelectedIds(new Set());
      // Refresh tree
      const { treeData } = useNodeStore.getState();
      if (treeData) {
        await useNodeStore.getState().fetchNodeTree(treeData.anchor_node_id);
      }
      await fetchNodes();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "delete failed");
    } finally {
      setDeleting(false);
    }
  }, [multiSelectedIds, fetchNodes, toast]);

  // Default viewport: fit all nodes
  const defaultViewport = useMemo(
    () => ({ x: 50, y: 50, zoom: 0.85 }),
    []
  );

  const isLoading = treeLoading && !treeData;

  if (isLoading) {
    return (
      <div
        className="flex flex-1 items-center justify-center"
        style={{
          minHeight: 0,
          width: "100%",
          height: "100%",
          background: "var(--color-bg)",
        }}
      >
        <p
          style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 11,
            color: "var(--color-text-faint)",
            letterSpacing: "0.04em",
          }}
        >
          loading graph…
        </p>
      </div>
    );
  }

  const isEmpty = !treeData || treeData.nodes.length === 0;
  if (isEmpty) {
    return (
      <div
        className="flex flex-1 items-center justify-center"
        style={{
          minHeight: 0,
          width: "100%",
          height: "100%",
          background: "radial-gradient(ellipse at center, rgba(255,255,255,0.02) 0%, transparent 70%), var(--color-bg)",
        }}
      >
        <div className="flex flex-col items-center text-center">
          <pre
            className="select-none"
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: "14px",
              lineHeight: 1.5,
              color: "var(--color-text-faint)",
              opacity: 0.25,
              whiteSpace: "pre",
            }}
          >
            {ASCII_EMPTY}
          </pre>

          <p style={{
            fontFamily: "'Computer Modern', 'Latin Modern Roman', Georgia, 'Times New Roman', serif",
            fontSize: 14, fontWeight: 500,
            color: "var(--color-text-muted)",
            marginTop: 8,
          }}>
            no nodes yet
          </p>
          <p style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 11,
            color: "var(--color-text-faint)",
            marginTop: 6,
          }}>
            use + to create a node or import a graph
          </p>
          <span className="blink-cursor" style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 10, color: "var(--color-text-faint)",
            opacity: 0.4, marginTop: 12,
          }}>_</span>
        </div>
      </div>
    );
  }

  return (
    <div
      className="relative flex flex-1 flex-col"
      style={{
        minHeight: 0,
        width: "100%",
        height: "100%",
        backgroundColor: "var(--color-bg)",
      }}
    >
      {/* Main content area */}
      <div className="relative flex-1" style={{ minHeight: 0, width: "100%" }}>
        <MultiSelectContext.Provider value={multiSelectedIds}>
          {graphStyle !== "cards" ? (
            <OrbitGraph
              treeData={treeData}
              selectedIds={orbitSelectedIds}
              onNodeClick={onOrbitNodeClick}
              mode={graphStyle === "timeline" ? "timeline" : "force"}
            />
          ) : (
            <ReactFlow
              nodes={nodes}
              edges={edges}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onNodeClick={onNodeClick}
              onPaneClick={onPaneClick}
              nodeTypes={nodeTypes}
              defaultViewport={defaultViewport}
              fitView
              fitViewOptions={{ padding: 0.2 }}
              minZoom={0.1}
              maxZoom={2}
              proOptions={{ hideAttribution: true }}
              onConnect={readOnly ? undefined : onConnect}
              nodesDraggable={false}
              nodesConnectable={!readOnly}
              onlyRenderVisibleElements
              style={{ width: "100%", height: "100%" }}
            >
              <Background
                variant={BackgroundVariant.Dots}
                gap={20}
                size={0.8}
                color="var(--color-border)"
                style={{ opacity: 0.4 }}
              />
            </ReactFlow>
          )}
        </MultiSelectContext.Provider>
      </div>

      {/* Hidden import input (kept for programmatic use) */}
      <input
        ref={importInputRef}
        type="file"
        accept=".json,application/json"
        onChange={handleImport}
        disabled={importing}
        style={{ display: "none" }}
      />

      {/* Multi-select floating action bar */}
      {!readOnly && multiSelectedIds.size > 0 && (
        <div
          className="absolute bottom-4 left-1/2 z-20 flex items-center gap-3 rounded-lg px-4 py-2.5"
          style={{
            transform: "translateX(-50%)",
            backgroundColor: "var(--color-surface)",
            border: "1px solid var(--color-border)",
            boxShadow: "0 4px 16px rgba(0, 0, 0, 0.25)",
          }}
        >
          <span
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: "11px",
              fontWeight: 500,
              color: "var(--color-text)",
            }}
          >
            {multiSelectedIds.size} node{multiSelectedIds.size > 1 ? "s" : ""}{" "}
            selected
          </span>

          <div
            style={{
              width: 1,
              height: 16,
              backgroundColor: "var(--color-border)",
            }}
          />

          <button
            onClick={handleExportJson}
            disabled={exporting}
            className="rounded px-2.5 py-1 transition-opacity hover:opacity-80 disabled:opacity-40"
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: "10px",
              fontWeight: 600,
              color: "var(--color-accent)",
            }}
          >
            export json
          </button>

          <button
            onClick={handleExportMarkdown}
            disabled={exporting}
            className="rounded px-2.5 py-1 transition-opacity hover:opacity-80 disabled:opacity-40"
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: "10px",
              fontWeight: 600,
              color: "var(--color-accent)",
            }}
          >
            export markdown
          </button>

          <div
            style={{
              width: 1,
              height: 16,
              backgroundColor: "var(--color-border)",
            }}
          />

          <button
            onClick={handleBulkDelete}
            disabled={deleting}
            className="rounded px-2.5 py-1 transition-opacity hover:opacity-80 disabled:opacity-40"
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: "10px",
              fontWeight: 600,
              color: "var(--color-error)",
            }}
          >
            delete
          </button>

          <div
            style={{
              width: 1,
              height: 16,
              backgroundColor: "var(--color-border)",
            }}
          />

          <button
            onClick={() => setMultiSelectedIds(new Set())}
            className="rounded px-2 py-1 transition-opacity hover:opacity-80"
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: "10px",
              fontWeight: 500,
              color: "var(--color-text-faint)",
            }}
          >
            clear
          </button>
        </div>
      )}
    </div>
  );
}
