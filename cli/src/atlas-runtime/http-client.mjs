import crypto from "node:crypto";

// Only TRANSIENT failures are auto-retried. 429 (rate limited) and 409
// (conflict) are deliberate, non-transient responses — auto-retrying them just
// hammers the server (a 429 retry-storm can saturate a single-worker backend)
// and never succeeds; surface the friendly message and let the caller back off.
const RETRY_STATUSES = new Set([408, 425, 500, 502, 503, 504]);

// Translate backend error bodies into messages a human can act on. The
// previous behaviour was ``HTTP 400: {"detail":"invalid input for query
// argument $1: 'bogus' (invalid UUID 'bogus': length must be between
// 32..36 characters, got 5)"}`` — raw asyncpg leaking through. The patterns
// below cover the common shapes (UUID parse, not found, auth, validation)
// without changing the underlying error class or status code semantics.
export function friendlyHttpError(status, body, commandName = null) {
  let detail = body;
  // Backend structured errors ({code, message}) — e.g. quota (402) and the
  // library layer's vendor-sanitized errors. The message is deliberate and
  // safe to surface verbatim; a structured message is how we distinguish "a
  // reason worth showing" from opaque 5xx/trace bodies we must keep hidden.
  let structuredMessage = null;
  try {
    const parsed = JSON.parse(body || "{}");
    if (typeof parsed === "object" && parsed) {
      detail = parsed.detail ?? parsed.message ?? parsed.error ?? body;
      if (Array.isArray(detail)) detail = detail.map((d) => d?.msg || JSON.stringify(d)).join("; ");
      if (detail && typeof detail === "object" && typeof detail.message === "string") {
        structuredMessage = detail.message;
      }
    }
  } catch {
    // body wasn't JSON — fall back to the raw text
  }
  const detailText = structuredMessage || (typeof detail === "string" ? detail : JSON.stringify(detail));
  const command = commandName ? ` (${commandName})` : "";

  // asyncpg's UUID parser leaks through as ``invalid input for query argument
  // $1: '...' (invalid UUID ...)`` on /nodes/{id}-shaped GETs. Translate to a
  // human message that names the parameter the user actually typed.
  if (/invalid UUID/i.test(detailText) || /invalid input for query argument/i.test(detailText)) {
    return `Invalid ID format${command}. Gateway IDs are UUIDs — try \`atlas node:list\` to find one, or pass a slug (e.g. able-helm-1359).`;
  }
  if (status === 401) {
    return `Not authenticated${command}. Run \`atlas login\` or set ATLAS_API_KEY.`;
  }
  if (status === 402) {
    // Insufficient wallet credit for a managed model or enhanced-search call. The backend is the
    // single source of truth for this message — render its structured
    // ``detail.message`` verbatim so every client shows the same words.
    const msg =
      detail && typeof detail === "object" && detail.message
        ? detail.message
        : detailText ||
          "Insufficient CLI wallet credit. Add your own provider key in Integrations, or top up your wallet in Billing.";
    return `${String(msg).slice(0, 400)}${command}`;
  }
  if (status === 403) {
    return `Forbidden${command}: ${detailText.slice(0, 200)}`;
  }
  if (status === 404) {
    return `Not found${command}: ${detailText.slice(0, 200) || "the resource does not exist or you can't see it."}`;
  }
  if (status === 409) {
    return `Conflict${command}: ${detailText.slice(0, 200)} — re-fetch the latest revision and retry.`;
  }
  if (status === 422) {
    return `Validation failed${command}: ${detailText.slice(0, 300)}`;
  }
  if (status === 429) {
    return `Rate limited${command}. Wait a moment and retry; \`atlas usage:summary\` shows your quotas.`;
  }
  if (status === 503) {
    // 503 carries a deliberate, server-sanitized reason (e.g. "the library
    // service is not configured") when present; opaque/transient 503s without
    // a structured message fall back to a retry hint and never echo trace text.
    if (structuredMessage) return `Service unavailable${command}: ${structuredMessage.slice(0, 250)}`;
    return `Service unavailable${command}. Retry shortly; check status.syntheticsciences.ai.`;
  }
  if (status >= 500) {
    // Surface a structured, sanitized reason (e.g. a library upstream error)
    // when the backend provided one; otherwise keep the generic hint so raw
    // 500/502/504 trace bodies are never echoed to the agent.
    const reason = structuredMessage ? `: ${structuredMessage.slice(0, 250)}` : "";
    return `Gateway backend error${command} (HTTP ${status})${reason}. Try again or check status.syntheticsciences.ai.`;
  }
  return `HTTP ${status}${command}: ${detailText.slice(0, 300)}`;
}


function stableJson(value) {
  if (Array.isArray(value)) return `[${value.map((item) => stableJson(item)).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableJson(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

function defaultIdempotencyKey(method, path, query, body) {
  const digest = crypto.createHash("sha256")
    .update(`${method} ${path}\n${stableJson(query || {})}\n${stableJson(body || {})}`)
    .digest("hex");
  return `atlas-cli-${digest}`;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function buildUrl(baseUrl, path, query = {}) {
  const url = new URL(`${baseUrl.replace(/\/+$/, "")}${path.startsWith("/") ? path : `/${path}`}`);
  for (const [key, value] of Object.entries(query || {})) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) {
      for (const item of value) url.searchParams.append(key, String(item));
    } else {
      url.searchParams.set(key, String(value));
    }
  }
  return url;
}

export class AtlasHttpClient {
  constructor(config, runtime = {}) {
    this.config = config;
    this.runtime = runtime;
  }

  headers(method, path, query, body, extra = {}, isPublic = false) {
    const headers = {
      Accept: "application/json",
      "User-Agent": "atlas-cli",
      "X-Atlas-Cli-Command": this.runtime.commandName || "",
      "X-Atlas-Cli-Invocation-Id": this.runtime.invocationId || crypto.randomUUID(),
      ...extra,
    };
    // Public discovery commands reach anonymous endpoints; never attach a
    // (possibly stale) stored key, which optional-auth would reject with 401.
    if (this.config.apiKey && !isPublic) headers.Authorization = `Bearer ${this.config.apiKey}`;
    if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
      headers["Content-Type"] = headers["Content-Type"] || "application/json";
      headers["Idempotency-Key"] = this.runtime.idempotency_key || defaultIdempotencyKey(method, path, query, body);
    }
    return headers;
  }

  echo(method, path, { query, body, raw = false, external = false } = {}) {
    return {
      request: {
        method,
        path,
        query: query || {},
        body: body ?? null,
        raw,
        external,
      },
    };
  }

  async requestJson(method, path, { query, body, public: isPublic = false } = {}) {
    if (process.env.ATLAS_HTTP_ECHO === "1") {
      return this.echo(method, path, { query, body, raw: false });
    }
    const response = await this.requestRaw(method, path, { query, body, public: isPublic });
    const text = await response.text();
    return text ? JSON.parse(text) : {};
  }

  async requestRaw(method, path, { query, body, public: isPublic = false } = {}) {
    if (process.env.ATLAS_HTTP_ECHO === "1") {
      return this.echo(method, path, { query, body, raw: true });
    }
    // Public discovery commands (explore, researchers, competitions) reach
    // unauthenticated endpoints, so they don't require a stored API key.
    if (!this.config.apiKey && !isPublic) {
      throw new Error("ATLAS_API_KEY is not set. Export ATLAS_API_KEY or configure ~/.config/atlas-cli/config.json.");
    }
    const url = buildUrl(this.config.baseUrl, path, query);
    const retryMax = this.runtime.no_retry ? 0 : Number(this.runtime.retryMax ?? this.config.retryMax ?? 2);
    let lastError = null;
    for (let attempt = 0; attempt <= retryMax; attempt += 1) {
      try {
        const response = await fetch(url, {
          method,
          headers: this.headers(method, path, query, body, {}, isPublic),
          body: body === undefined || body === null ? undefined : JSON.stringify(body),
          signal: AbortSignal.timeout(Number(this.runtime.timeoutMs || this.config.timeoutMs)),
        });
        if (response.ok) return response;
        // Non-retryable statuses (e.g. 4xx) must throw immediately so we never
        // re-send a write. Only retry the retryable statuses, and only while
        // attempts remain.
        if (!RETRY_STATUSES.has(response.status) || attempt >= retryMax) {
          const text = await response.text().catch(() => "");
          throw new Error(friendlyHttpError(response.status, text, this.runtime.commandName));
        }
        const retryAfter = Number(response.headers.get("Retry-After") || 0);
        await sleep(retryAfter > 0 ? retryAfter * 1000 : 250 * (attempt + 1));
      } catch (error) {
        lastError = error;
        if (attempt >= retryMax) throw error;
        await sleep(250 * (attempt + 1));
      }
    }
    throw lastError || new Error("request failed");
  }

  async requestRawExternal(method, absoluteUrl, { rawBody, extraHeaders } = {}) {
    if (process.env.ATLAS_HTTP_ECHO === "1") {
      return this.echo(method, absoluteUrl, { body: rawBody ? { bytes: rawBody.byteLength ?? rawBody.length ?? 0 } : null, raw: true, external: true });
    }
    const response = await fetch(absoluteUrl, {
      method,
      headers: extraHeaders || {},
      body: rawBody,
      signal: AbortSignal.timeout(Number(this.runtime.timeoutMs || this.config.timeoutMs)),
    });
    if (!response.ok) {
      throw new Error(`external upload failed with HTTP ${response.status}`);
    }
    return response;
  }
}
