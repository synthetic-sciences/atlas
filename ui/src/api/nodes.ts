// Node graph operations: nodes, artifacts, tags, sharing,
// audit, export/import.
import type {
  AddParentRequest,
  Artifact,
  AuditEvent,
  GraphTag,
  MergeNodesRequest,
  Node,
  NodeListResponse,
  NodeTreeResponse,
  RemoveParentRequest,
  SharingInfo,
} from "./types";
import { getAuthHeaders, publicRequest, qs, request, BASE_URL } from "./internal";

export interface PublicRepoEntry {
  name: string;
  path: string;
  type: string;
  sha?: string;
  size?: number;
}

export interface PublicRepoTree {
  repo: string;
  ref: string;
  path: string;
  entries: PublicRepoEntry[];
}

export interface PublicRepoFile {
  repo: string;
  ref: string;
  path: string;
  content: string;
  sha?: string | null;
  size?: number | null;
}

export interface PublicGraphAuthor {
  handle: string;
  github_username?: string | null;
  avatar_url?: string | null;
}

export interface PublicGraphCard {
  node_id: string;
  slug_name: string | null;
  title: string;
  summary: string;
  kind: string;
  lifecycle: string | null;
  author: PublicGraphAuthor;
  node_count: number;
  star_count: number;
  fork_count: number;
  viewer_has_starred: boolean;
  has_code: boolean;
  repo_url: string | null;
  paper_url: string | null;
  category?: string;
  forked_from: { node_id: string; title?: string | null } | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface ResearcherCard {
  handle: string;
  github_username: string | null;
  display_name: string | null;
  avatar_url: string | null;
  created_at: string | null;
  public_graph_count: number;
}

export interface ResearchersResponse {
  researchers: ResearcherCard[];
  total: number;
  page: number;
  per_page: number;
  has_more: boolean;
}

export interface PublicGraphArchive {
  graphs: PublicGraphCard[];
  total: number;
  page: number;
  per_page: number;
  has_more: boolean;
  sort: string;
  facets?: {
    stars_on_page: number;
    forks_on_page: number;
    papers_on_page: number;
    code_on_page: number;
    forked_on_page: number;
  };
}

export interface GraphSocial {
  root_node_id: string;
  star_count: number;
  fork_count: number;
  viewer_has_starred: boolean;
}

export interface PublicArtifact {
  artifact_id: string;
  title: string;
  artifact_type: string | null;
  media_type: string | null;
  size: number | null;
  note: string | null;
  created_at: string;
  external_url: string | null;
  download_url: string;
}

export const nodesApi = {
  listNodes: (params?: Record<string, string | number | boolean>): Promise<NodeListResponse> =>
    request<NodeListResponse>(`/nodes${qs(params)}`),

  listPublicNodes: (params?: Record<string, string>): Promise<NodeListResponse> =>
    publicRequest<NodeListResponse>(`/nodes/explore${qs(params)}`),

  listPublicGraphs: (params?: Record<string, string>): Promise<NodeListResponse> =>
    publicRequest<NodeListResponse>(
      `/nodes/explore${qs({ ...params, root_only: "true" })}`,
    ),

  getPublicGraphTree: (id: string): Promise<NodeTreeResponse> =>
    publicRequest<NodeTreeResponse>(`/nodes/explore/${id}/tree?projection=full`),

  // GitHub x arXiv archive of whole public graphs (authors, stars, forks,
  // paper links). Only project roots with children are returned.
  listPublicGraphArchive: (
    params?: Record<string, string>,
  ): Promise<PublicGraphArchive> =>
    request<PublicGraphArchive>(`/nodes/explore/graphs${qs(params)}`),

  getPublicGraphSocial: (id: string): Promise<GraphSocial> =>
    request<GraphSocial>(`/nodes/explore/${id}/social`),

  // Public researcher directory + profiles (collaboration surface).
  listResearchers: (params?: Record<string, string>): Promise<ResearchersResponse> =>
    publicRequest<ResearchersResponse>(`/researchers${qs(params)}`),

  getResearcher: (handle: string): Promise<ResearcherCard> =>
    publicRequest<ResearcherCard>(`/users/${encodeURIComponent(handle)}`),

  getResearcherGraphs: (
    handle: string,
    params?: Record<string, string>,
  ): Promise<PublicGraphArchive> =>
    publicRequest<PublicGraphArchive>(
      `/users/${encodeURIComponent(handle)}/graphs${qs(params)}`,
    ),

  getPublicGraphNodeArtifacts: (
    id: string,
  ): Promise<{ node_id: string; artifacts: PublicArtifact[] }> =>
    publicRequest<{ node_id: string; artifacts: PublicArtifact[] }>(
      `/nodes/explore/${id}/artifacts`,
    ).then((res) => ({
      node_id: res.node_id,
      artifacts: (res.artifacts || []).map((a) => ({
        ...a,
        download_url: `${BASE_URL}${a.download_url}`,
      })),
    })),

  starGraph: (nodeId: string): Promise<GraphSocial> =>
    request<GraphSocial>(`/nodes/${nodeId}/star`, { method: "POST" }),

  unstarGraph: (nodeId: string): Promise<GraphSocial> =>
    request<GraphSocial>(`/nodes/${nodeId}/star`, { method: "DELETE" }),

  // Public, no-auth code browsing for a shared node, pinned to the node's
  // captured commit. Public repos only (private repos return 404).
  getPublicNodeRepoTree: (
    id: string,
    path: string = "",
    ref?: string,
  ): Promise<PublicRepoTree> =>
    publicRequest<PublicRepoTree>(
      `/nodes/explore/${id}/repo/tree${qs({ path, ...(ref ? { ref } : {}) })}`,
    ),

  getPublicNodeRepoFile: (
    id: string,
    path: string,
    ref?: string,
  ): Promise<PublicRepoFile> =>
    publicRequest<PublicRepoFile>(
      `/nodes/explore/${id}/repo/read${qs({ path, ...(ref ? { ref } : {}) })}`,
    ),

  getNode: (
    id: string,
    projection: string = "core",
    opts?: { fresh?: boolean },
  ): Promise<Node> =>
    request<Node>(`/nodes/${id}?projection=${projection}`, undefined, {
      fresh: opts?.fresh,
    }),

  getNodeTree: (id: string): Promise<NodeTreeResponse> =>
    request<NodeTreeResponse>(`/nodes/${id}/tree?projection=full`),

  stageCreate: (data: Record<string, unknown>): Promise<Node> =>
    request<Node>("/nodes/stage-create", { method: "POST", body: JSON.stringify(data) }),

  stageUpdate: (data: Record<string, unknown>): Promise<Node> =>
    request<Node>("/nodes/stage-update", { method: "POST", body: JSON.stringify(data) }),

  commitNode: (data: Record<string, unknown>): Promise<Node> =>
    request<Node>("/nodes/commit", { method: "POST", body: JSON.stringify(data) }),

  branchNode: async (data: Record<string, unknown>): Promise<Node> => {
    const result = await request<{ node: Node; parent_revision: number }>("/nodes/branch", {
      method: "POST",
      body: JSON.stringify(data),
    });
    return result.node;
  },

  deleteNode: (id: string): Promise<void> =>
    request<void>(`/nodes/${id}`, { method: "DELETE" }),

  addParent: (data: AddParentRequest): Promise<Node> =>
    request<Node>("/nodes/add-parent", { method: "POST", body: JSON.stringify(data) }),

  removeParent: (data: RemoveParentRequest): Promise<Node> =>
    request<Node>("/nodes/remove-parent", { method: "POST", body: JSON.stringify(data) }),

  mergeNodes: (data: MergeNodesRequest): Promise<Node> =>
    request<Node>("/nodes/merge", { method: "POST", body: JSON.stringify(data) }),

  bulkDeleteNodes: (nodeIds: string[]): Promise<{
    success: boolean;
    deleted_count: number;
    deleted_node_ids: string[];
    skipped_non_owned: string[];
    graph_event_id: string;
  }> =>
    request("/nodes/bulk-delete", {
      method: "POST",
      body: JSON.stringify({ node_ids: nodeIds }),
    }),

  // Artifacts
  listArtifacts: (nodeId: string): Promise<Artifact[]> =>
    request<Artifact[]>(`/artifacts/${nodeId}`),

  getArtifact: (nodeId: string, artifactId: string): Promise<Artifact> =>
    request<Artifact>(`/artifacts/${nodeId}/${artifactId}`),

  prepareUploads: (data: Record<string, unknown>): Promise<Record<string, unknown>> =>
    request<Record<string, unknown>>("/artifacts/prepare", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  uploadArtifactBytes: async (uploadUrl: string, file: File): Promise<void> => {
    const authHeaders = await getAuthHeaders();
    const res = await fetch(uploadUrl, {
      method: "PUT",
      headers: {
        "Content-Type": file.type || "application/octet-stream",
        "X-Thesis-Artifact-Filename": file.name,
        ...authHeaders,
      },
      body: file,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Upload failed: HTTP ${res.status}`);
    }
  },

  finalizeUploads: (data: Record<string, unknown>): Promise<Record<string, unknown>> =>
    request<Record<string, unknown>>("/artifacts/finalize", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  // Tags. Tag writes change node tags and the tree, so the cached /nodes
  // reads must go stale too, not just /tags.
  createTag: (data: Record<string, unknown>): Promise<{ tag: GraphTag; node: Node }> =>
    request<{ tag: GraphTag; node: Node }>("/tags", {
      method: "POST",
      body: JSON.stringify(data),
    }, { invalidates: ["/nodes"] }),

  deleteTag: (data: Record<string, unknown>): Promise<void> =>
    request<void>("/tags", { method: "DELETE", body: JSON.stringify(data) }, { invalidates: ["/nodes"] }),

  setTagAssignments: (data: Record<string, unknown>): Promise<Node> =>
    request<Node>("/tags/assignments", { method: "POST", body: JSON.stringify(data) }, { invalidates: ["/nodes"] }),

  // Sharing
  getSharing: (nodeId: string): Promise<SharingInfo> =>
    request<SharingInfo>(`/sharing/${nodeId}`),

  setSharing: (nodeId: string, data: Record<string, unknown>): Promise<SharingInfo> =>
    request<SharingInfo>(`/sharing/${nodeId}`, { method: "POST", body: JSON.stringify(data) }, { invalidates: ["/nodes"] }),

  // Audit
  listAudit: (nodeId: string, limit: number = 50): Promise<AuditEvent[]> =>
    request<AuditEvent[]>(`/audit/${nodeId}?limit=${limit}`),

  // Export / Import
  exportSubgraph: (nodeIds: string[]): Promise<Record<string, unknown>> =>
    request<Record<string, unknown>>("/export/subgraph", {
      method: "POST",
      body: JSON.stringify({ node_ids: nodeIds }),
    }),

  // An import creates graphs, so the cached node list must refetch: callers
  // re-run fetchNodes() right after and would otherwise hit the 30s cache.
  importSubgraph: (data: Record<string, unknown>): Promise<Record<string, unknown>> =>
    request<Record<string, unknown>>("/import/subgraph", {
      method: "POST",
      body: JSON.stringify(data),
    }, { invalidates: ["/nodes"] }),

  exportMarkdown: (nodeIds: string[]): Promise<Record<string, unknown>> =>
    request<Record<string, unknown>>("/export/summary", {
      method: "POST",
      body: JSON.stringify({ node_ids: nodeIds, format: "markdown" }),
    }),

  exportPdf: async (nodeIds: string[]): Promise<Blob> => {
    const authHeaders = await getAuthHeaders();
    const res = await fetch(`${BASE_URL}/export/summary/pdf`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...authHeaders,
      },
      body: JSON.stringify({ node_ids: nodeIds }),
    });
    if (!res.ok) throw new Error(`PDF export failed: ${res.status}`);
    return res.blob();
  },
};
