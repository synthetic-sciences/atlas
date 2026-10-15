import { create } from "zustand";
import { api } from "../api/client.js";
import type { AuditEvent, Node, NodeTreeResponse } from "../api/types.js";

// Per-anchor in-flight tree fetches. Module-scoped so StrictMode dev
// double-mounts and concurrent components share the same network call.
const _treeInflight = new Map<string, Promise<NodeTreeResponse>>();

// Monotonic request token for fetchNodes. A slow stale list response must not
// clobber a newer one (e.g. a filter change fires a fast follow-up), so each
// call captures the current seq and only applies its result if it's still the
// latest. Mirrors the selectNode/fetchAudit race guards below.
let _listSeq = 0;

interface NodeState {
  // List state
  nodes: Node[];
  total: number;
  page: number;
  perPage: number;
  hasMore: boolean;
  listLoading: boolean;
  listError: string | null;

  // Tree state
  treeData: NodeTreeResponse | null;
  treeLoading: boolean;
  treeError: string | null;

  // Audit state (per-anchor cache)
  auditEvents: AuditEvent[];
  auditAnchorId: string | null;
  auditLoading: boolean;
  auditError: string | null;

  // Detail state
  selectedNodeId: string | null;
  selectedNode: Node | null;
  detailLoading: boolean;
  detailError: string | null;

  // Filters
  searchQuery: string;
  kindFilter: string;
  lifecycleFilter: string;
  outcomeFilter: string;
  tagFilter: string | null;

  // Actions - list
  fetchNodes: (opts?: { rootOnly?: boolean }) => Promise<void>;

  // Actions - tree
  fetchNodeTree: (nodeId: string) => Promise<void>;

  // Actions - audit
  fetchAudit: (anchorNodeId: string) => Promise<void>;

  // Actions - selection
  selectNode: (nodeId: string | null) => Promise<void>;
  clearSelection: () => void;

  // Actions - filters
  setSearchQuery: (query: string) => void;
  setKindFilter: (kind: string) => void;
  setLifecycleFilter: (lifecycle: string) => void;
  setOutcomeFilter: (outcome: string) => void;
  setTagFilter: (tagId: string | null) => void;

  // Actions - mutations
  commitNode: (nodeId: string) => Promise<void>;
  branchNode: (parentId: string, title?: string) => Promise<Node>;
  deleteNode: (nodeId: string) => Promise<void>;
  addParent: (nodeId: string, parentId: string) => Promise<void>;
  removeParent: (nodeId: string, parentId: string) => Promise<void>;
  refreshSelectedNode: () => Promise<void>;
}

export const useNodeStore = create<NodeState>((set, get) => ({
  // List state
  nodes: [],
  total: 0,
  page: 1,
  perPage: 25,
  hasMore: false,
  listLoading: false,
  listError: null,

  // Tree state
  treeData: null,
  treeLoading: false,
  treeError: null,

  // Audit state
  auditEvents: [],
  auditAnchorId: null,
  auditLoading: false,
  auditError: null,

  // Detail state
  selectedNodeId: null,
  selectedNode: null,
  detailLoading: false,
  detailError: null,

  // Filters
  searchQuery: "",
  kindFilter: "",
  lifecycleFilter: "",
  outcomeFilter: "",
  tagFilter: null,

  // Actions - list
  fetchNodes: async (opts) => {
    const my = ++_listSeq;
    set({ listLoading: true, listError: null });
    try {
      const state = get();
      const params: Record<string, string> = {
        page: String(state.page),
        per_page: String(state.perPage),
        // The server unions owned graphs with explicit private collaborator
        // grants before pagination. Do not reconstruct this list client-side.
        scope: "owned_or_shared_private",
      };
      // The dashboard sidebar shows graph ROOTS. Without this, recently-updated
      // child nodes (e.g. a fresh batch of runs) can fill the whole first page
      // and push every root past it, leaving the sidebar empty.
      if (opts?.rootOnly) params.root_only = "true";
      if (state.searchQuery) params.title = state.searchQuery;
      if (state.kindFilter) params.kind = state.kindFilter;
      if (state.lifecycleFilter) params.lifecycle = state.lifecycleFilter;
      if (state.outcomeFilter) params.outcome = state.outcomeFilter;
      if (state.tagFilter) params.tag_id = state.tagFilter;
      const data = await api.listNodes(params);
      // A newer fetchNodes started while this was in flight — drop the stale
      // response so it can't clobber the fresher list.
      if (my !== _listSeq) return;
      set({
        nodes: data.nodes,
        total: data.total,
        page: data.page,
        perPage: data.per_page,
        hasMore: data.has_more,
        listLoading: false,
      });
    } catch (err) {
      if (my !== _listSeq) return; // a newer fetch owns the list
      set({
        listError:
          err instanceof Error ? err.message : "failed to fetch nodes",
        listLoading: false,
      });
    }
  },

  // Actions - tree
  fetchNodeTree: async (nodeId: string) => {
    // Hard dedupe: if any tree fetch for THIS node is in flight, wait
    // on it instead of issuing a duplicate. Covers two cases:
    //   (a) StrictMode double-mount - both effects start in the same
    //       tick before treeData lands (the previous "loading + same
    //       anchor" guard misses this because anchor only updates
    //       after the request completes).
    //   (b) Two components on the same page kicking off the same
    //       fetch concurrently (Dashboard + AgentPage).
    if (_treeInflight.has(nodeId)) {
      try {
        await _treeInflight.get(nodeId);
      } catch {
        // The original request will set treeError; nothing else to do.
      }
      return;
    }
    set({ treeLoading: true, treeError: null });
    const promise = api.getNodeTree(nodeId)
      .then((data) => {
        set({ treeData: data, treeLoading: false });
        return data;
      })
      .catch((err) => {
        set({
          treeError:
            err instanceof Error ? err.message : "failed to fetch node tree",
          treeLoading: false,
        });
        throw err;
      })
      .finally(() => {
        _treeInflight.delete(nodeId);
      });
    _treeInflight.set(nodeId, promise);
    try {
      await promise;
    } catch {
      // Already set treeError above.
    }
  },

  // Actions - audit
  fetchAudit: async (anchorNodeId: string) => {
    set({ auditLoading: true, auditError: null, auditAnchorId: anchorNodeId });
    try {
      const events = await api.listAudit(anchorNodeId, 200);
      if (get().auditAnchorId === anchorNodeId) {
        set({ auditEvents: events, auditLoading: false });
      }
    } catch (err) {
      set({
        auditError:
          err instanceof Error ? err.message : "failed to fetch audit events",
        auditLoading: false,
      });
    }
  },

  // Actions - selection
  selectNode: async (nodeId: string | null) => {
    if (!nodeId) {
      set({ selectedNodeId: null, selectedNode: null });
      return;
    }

    // Show what we already have for THIS node immediately (instant open), and
    // critically DON'T keep showing the previously-selected node. Without this
    // the UI flashes/sticks on the old node: the loading guard is `loading &&
    // !node`, so a non-null stale node hides the spinner. If we don't already
    // have the node, set null so the spinner shows instead of the wrong node.
    {
      const { nodes, selectedNode } = get();
      const known =
        selectedNode?.node_id === nodeId
          ? selectedNode
          : nodes.find((n) => n.node_id === nodeId) ?? null;
      set({ selectedNodeId: nodeId, selectedNode: known, detailLoading: true, detailError: null });
    }
    try {
      // Always fetch fresh on navigation — a node's status can change
      // out-of-band (its run completing) while a stale copy sits in the cache.
      const node = await api.getNode(nodeId, "full", { fresh: true });
      // Race guard: if the user navigated to a different node while this was in
      // flight, drop the stale response so a slow earlier fetch can't clobber
      // the newer selection (the root cause of "opens the same old one").
      if (get().selectedNodeId !== nodeId) return;
      const nodes = get().nodes;
      const idx = nodes.findIndex((n) => n.node_id === nodeId);
      set({
        selectedNode: node,
        nodes: idx >= 0 ? nodes.map((n) => (n.node_id === nodeId ? node : n)) : nodes,
        detailLoading: false,
      });
    } catch (err) {
      if (get().selectedNodeId !== nodeId) return; // a newer selection owns the UI
      set({
        detailError:
          err instanceof Error ? err.message : "failed to fetch node",
        detailLoading: false,
      });
    }
  },

  clearSelection: () => {
    set({ selectedNodeId: null, selectedNode: null });
  },

  // Actions - filters
  setSearchQuery: (query: string) => set({ searchQuery: query, page: 1 }),
  setKindFilter: (kind: string) => set({ kindFilter: kind, page: 1 }),
  setLifecycleFilter: (lifecycle: string) =>
    set({ lifecycleFilter: lifecycle, page: 1 }),
  setOutcomeFilter: (outcome: string) =>
    set({ outcomeFilter: outcome, page: 1 }),
  setTagFilter: (tagId: string | null) =>
    set({ tagFilter: tagId, page: 1 }),

  // Actions - mutations
  commitNode: async (nodeId: string) => {
    // Step 1: fetch latest revision (needed for expected_revision)
    const latest = await api.getNode(nodeId, "core");
    // Step 2: commit
    await api.commitNode({ node_id: nodeId, expected_revision: latest.revision });
    // Step 3: refresh everything in parallel
    const { treeData, auditAnchorId } = get();
    await Promise.all([
      get().selectNode(nodeId),
      treeData ? get().fetchNodeTree(treeData.anchor_node_id) : Promise.resolve(),
      get().fetchNodes(),
      auditAnchorId ? get().fetchAudit(auditAnchorId) : Promise.resolve(),
    ]);
  },

  branchNode: async (parentId: string, title?: string) => {
    const latest = await api.getNode(parentId, "core");
    const result = await api.branchNode({
      node_id: parentId,
      expected_revision: latest.revision,
      title: title || null,
    });
    // Refresh list, tree, audit in parallel
    const { treeData, auditAnchorId } = get();
    await Promise.all([
      get().fetchNodes(),
      treeData ? get().fetchNodeTree(treeData.anchor_node_id) : Promise.resolve(),
      auditAnchorId ? get().fetchAudit(auditAnchorId) : Promise.resolve(),
    ]);
    return result;
  },

  deleteNode: async (nodeId: string) => {
    const state = get();
    // Optimistic: immediately remove from UI
    const previousNodes = state.nodes;
    set({
      nodes: state.nodes.filter((n) => n.node_id !== nodeId),
      ...(state.selectedNodeId === nodeId
        ? { selectedNodeId: null, selectedNode: null }
        : {}),
    });

    try {
      await api.deleteNode(nodeId);
    } catch (err) {
      // Rollback on failure
      set({ nodes: previousNodes });
      throw err;
    }

    // Clear or refresh tree if the deleted node was part of it
    const { treeData, auditAnchorId } = get();
    if (treeData) {
      const wasInTree = treeData.nodes.some((n) => n.node_id === nodeId);
      if (wasInTree) {
        if (treeData.nodes[0]?.node_id === nodeId) {
          set({ treeData: null });
        } else {
          await get().fetchNodeTree(treeData.nodes[0].node_id);
        }
      }
    }
    if (auditAnchorId) {
      await get().fetchAudit(auditAnchorId);
    }
    await get().fetchNodes();
  },

  addParent: async (nodeId: string, parentId: string) => {
    const [child, parent] = await Promise.all([
      api.getNode(nodeId, "core"),
      api.getNode(parentId, "core"),
    ]);
    await api.addParent({
      node_id: nodeId,
      parent_id: parentId,
      expected_revision: child.revision,
      expected_parent_revision: parent.revision,
    });
    const { treeData } = get();
    if (treeData) await get().fetchNodeTree(treeData.anchor_node_id);
  },

  removeParent: async (nodeId: string, parentId: string) => {
    const [child, parent] = await Promise.all([
      api.getNode(nodeId, "core"),
      api.getNode(parentId, "core"),
    ]);
    await api.removeParent({
      node_id: nodeId,
      parent_id: parentId,
      expected_revision: child.revision,
      expected_parent_revision: parent.revision,
    });
    const { treeData } = get();
    if (treeData) await get().fetchNodeTree(treeData.anchor_node_id);
  },

  refreshSelectedNode: async () => {
    const nodeId = get().selectedNodeId;
    if (nodeId) {
      await get().selectNode(nodeId);
    }
  },
}));
