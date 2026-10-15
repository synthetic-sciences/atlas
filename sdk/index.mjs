export class AtlasError extends Error {
  constructor(response, body) {
    const detail = body?.detail;
    super(typeof detail === "string" ? detail : detail?.message || `Atlas returned HTTP ${response.status}`);
    this.name = "AtlasError";
    this.status = response.status;
    this.body = body;
  }
}

export class AtlasClient {
  constructor({ baseUrl = "http://127.0.0.1:8002/api/v1", token, fetch: transport = globalThis.fetch } = {}) {
    this.baseUrl = new URL(`${baseUrl.replace(/\/+$/, "")}/`);
    if (!["http:", "https:"].includes(this.baseUrl.protocol)) throw new TypeError("Atlas requires an HTTP or HTTPS base URL");
    if (this.baseUrl.username || this.baseUrl.password) throw new TypeError("Use the token option instead of URL credentials");
    this.token = token;
    this.transport = transport;
  }

  async request(method, path, { query = {}, body, signal, idempotencyKey } = {}) {
    const url = new URL(path.replace(/^\/+/, ""), this.baseUrl);
    if (url.origin !== this.baseUrl.origin || !url.pathname.startsWith(this.baseUrl.pathname)) {
      throw new TypeError("Atlas requests must stay within the configured API");
    }
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null) url.searchParams.set(key, String(value));
    }
    const token = typeof this.token === "function" ? await this.token() : this.token;
    const headers = { Accept: "application/json" };
    if (token) headers.Authorization = `Bearer ${token}`;
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (idempotencyKey) headers["Idempotency-Key"] = idempotencyKey;
    const response = await this.transport(url, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), signal });
    if (response.status === 204) return undefined;
    const text = await response.text();
    const payload = response.headers.get("content-type")?.includes("json") && text ? JSON.parse(text) : text;
    if (!response.ok) throw new AtlasError(response, payload);
    return payload;
  }

  listProjects(query) { return this.request("GET", "projects", { query }); }
  createProject(body, options) { return this.request("POST", "projects", { ...options, body }); }
  listNodes(query) { return this.request("GET", "nodes", { query }); }
  getNode(id) { return this.request("GET", `nodes/${encodeURIComponent(id)}`); }
  createNode(body, options) { return this.request("POST", "nodes", { ...options, body }); }
  commitNode(id, body, options) { return this.request("POST", `nodes/${encodeURIComponent(id)}/commit`, { ...options, body }); }
  branchNode(id, body, options) { return this.request("POST", `nodes/${encodeURIComponent(id)}/branch`, { ...options, body }); }
  getGraph(query) { return this.request("GET", "graph", { query }); }
  listResearchLog(query) { return this.request("GET", "research/log", { query }); }
  appendResearchLog(body, options) { return this.request("POST", "research/log", { ...options, body }); }
}
