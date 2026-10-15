export interface AtlasOptions {
  baseUrl?: string;
  token?: string | (() => string | undefined | Promise<string | undefined>);
  fetch?: typeof globalThis.fetch;
}
export interface RequestOptions {
  query?: Record<string, string | number | boolean | undefined | null>;
  body?: unknown;
  signal?: AbortSignal;
  idempotencyKey?: string;
}
export interface GraphNode {
  node_id: string;
  title: string;
  revision: number;
  [field: string]: unknown;
}
export class AtlasError extends Error {
  status: number;
  body: unknown;
}
export class AtlasClient {
  constructor(options?: AtlasOptions);
  request<T = unknown>(method: string, path: string, options?: RequestOptions): Promise<T>;
  listProjects(query?: RequestOptions["query"]): Promise<{ projects: Array<GraphNode & { project_id: string }> }>;
  createProject(body: { title: string; repo_url?: string; branch_name?: string; dedupe_key?: string }, options?: RequestOptions): Promise<{ project_id: string }>;
  listNodes(query?: RequestOptions["query"]): Promise<{ nodes: GraphNode[]; total: number }>;
  getNode(id: string): Promise<GraphNode>;
  createNode(body: Record<string, unknown>, options?: RequestOptions): Promise<GraphNode>;
  commitNode(id: string, body: Record<string, unknown>, options?: RequestOptions): Promise<GraphNode>;
  branchNode(id: string, body: Record<string, unknown>, options?: RequestOptions): Promise<GraphNode>;
  getGraph(query?: RequestOptions["query"]): Promise<unknown>;
  listResearchLog(query?: RequestOptions["query"]): Promise<unknown>;
  appendResearchLog(body: Record<string, unknown>, options?: RequestOptions): Promise<unknown>;
}
