import { useMemo, useRef } from "react";
import type { Node as RFNode, Edge as RFEdge } from "@xyflow/react";
import type { Node, NodeTreeResponse } from "../../api/types";
import { computeSegments } from "./orbit";
import { layoutAdaptive } from "./adaptiveLayout";

export type GraphStyle = "cards" | "orbit" | "timeline";

export interface GraphLayoutResult {
  nodes: RFNode[];
  edges: RFEdge[];
}

function refreshNodeData(
  previous: GraphLayoutResult,
  treeData: NodeTreeResponse,
): GraphLayoutResult {
  const freshById = new Map(treeData.nodes.map((node) => [node.node_id, node]));
  return {
    edges: previous.edges,
    nodes: previous.nodes.map((rfNode) => {
      const freshNode = freshById.get(rfNode.id);
      if (!freshNode) return rfNode; // group-frame nodes have no source node
      return {
        ...rfNode,
        data: { ...(rfNode.data as Record<string, unknown>), node: freshNode },
      };
    }),
  };
}

function buildNodesAndEdges(treeData: NodeTreeResponse): {
  rfNodes: RFNode[];
  rfEdges: RFEdge[];
} {
  const byId = new Map(treeData.nodes.map((n) => [n.node_id, n]));
  const rfNodes: RFNode[] = treeData.nodes.map((node: Node) => ({
    id: node.node_id,
    type: "research-node",
    position: { x: 0, y: 0 },
    data: { node, segments: computeSegments(node, byId) },
  }));

  const rfEdges: RFEdge[] = [];
  const nodeIds = new Set(treeData.nodes.map((n) => n.node_id));
  for (const node of treeData.nodes) {
    for (const parentId of node.parent_ids) {
      if (nodeIds.has(parentId)) {
        rfEdges.push({
          id: `${parentId}->${node.node_id}`,
          source: parentId,
          target: node.node_id,
          type: "smoothstep",
        });
      }
    }
  }
  return { rfNodes, rfEdges };
}

/**
 * Layout for the React-Flow "cards" style. Delegates positioning to the
 * adaptive engine (adaptiveLayout.ts), which profiles the graph and composes
 * the right strategy -- progression curve, layered dagre, or clustered
 * (partition by a group attribute, lay out each cluster with its own best
 * sub-layout, pack). Group frames come back as ``group-frame`` render nodes
 * prepended to the list. The "orbit"/"timeline" styles are rendered separately
 * by OrbitGraph, so this returns empty for them.
 */
export function useGraphLayout(
  treeData: NodeTreeResponse | null,
  style: GraphStyle = "cards",
): GraphLayoutResult {
  const prevKeyRef = useRef<string>("");
  const prevResultRef = useRef<GraphLayoutResult>({ nodes: [], edges: [] });

  return useMemo(() => {
    if (!treeData || treeData.nodes.length === 0 || style !== "cards") {
      return { nodes: [], edges: [] };
    }

    const structuralKey = treeData.nodes
      .map((n) => n.node_id + ":" + (n.parent_ids || []).join(","))
      .join("|");

    if (structuralKey === prevKeyRef.current) {
      const refreshed = refreshNodeData(prevResultRef.current, treeData);
      prevResultRef.current = refreshed;
      return refreshed;
    }

    const { rfNodes, rfEdges } = buildNodesAndEdges(treeData);
    const laid = layoutAdaptive(rfNodes, rfEdges);

    // Cluster frames render as background nodes behind their members.
    const frameNodes: RFNode[] = laid.frames.map((f) => ({
      id: f.id,
      type: "group-frame",
      position: { x: f.x, y: f.y },
      data: { label: f.label, count: f.count },
      style: { width: f.width, height: f.height },
      draggable: false,
      selectable: false,
      zIndex: 0,
    }));

    const result: GraphLayoutResult = {
      nodes: [...frameNodes, ...laid.nodes],
      edges: laid.edges,
    };
    prevKeyRef.current = structuralKey;
    prevResultRef.current = result;
    return result;
  }, [treeData, style]);
}
