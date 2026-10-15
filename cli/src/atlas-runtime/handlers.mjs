import { readFile, stat } from "node:fs/promises";
import path from "node:path";
import { ensureArray, ensureObject, splitCommaList } from "./parser.mjs";

const MAX_UPLOAD_BYTES = 100 * 1024 * 1024;
const MAX_UPLOAD_ITEMS = 50;

const ALLOWED_ARTIFACT_TYPES = new Set([
  "text",
  "table",
  "json",
  "image",
  "banner",
  "html",
  "plotly_html",
  "vega",
  "checkpoint",
  "binary",
  "diff_carousel",
]);

function definedEntries(obj) {
  return Object.fromEntries(Object.entries(obj).filter(([, value]) => value !== undefined && value !== null));
}

function valueFor(args, key) {
  if (args[key] !== undefined) return args[key];
  if (key === "slug" && args.slug_name !== undefined) return args.slug_name;
  return undefined;
}

function fillPath(pathTemplate, args, params = []) {
  let path = pathTemplate;
  for (const param of params) {
    const value = valueFor(args, param);
    if (value === undefined || value === null || value === "") throw new Error(`${param} is required`);
    path = path.replaceAll(`{${param}}`, encodeURIComponent(String(value)));
  }
  return path;
}

function nonPathArgs(args, command) {
  const skip = new Set(command.pathParams || []);
  delete skip._positional;
  return Object.fromEntries(
    Object.entries(args).filter(([key, value]) => key !== "_positional" && !skip.has(key) && value !== undefined && value !== null),
  );
}

function bodyFromParams(args, params = []) {
  return definedEntries(Object.fromEntries(params.map((key) => [key, args[key]])));
}

function queryFromParams(args, params = []) {
  return bodyFromParams(args, params);
}

function normalizeNodeIds(value, field = "node_ids") {
  const items = splitCommaList(value);
  if (!items.length) throw new Error(`${field} must contain at least one value`);
  return items;
}

function defaultBody(args, command) {
  if (command.bodyParams) return bodyFromParams(args, command.bodyParams);
  return nonPathArgs(args, command);
}

function requestFor(command, args) {
  const path = fillPath(command.path, args, command.pathParams);
  const method = command.method;
  if (command.queryParams) {
    return { method, path, query: queryFromParams(args, command.queryParams) };
  }
  if (method === "GET") return { method, path, query: nonPathArgs(args, command) };

  switch (command.bodyMode) {
    case "payload_json": {
      const body = ensureObject(args.payload_json, "payload_json");
      // Fold capture-by-value pointers in when passed as top-level flags
      // (e.g. `--repo_url "$(git remote get-url origin)"`), so they reach
      // the backend instead of being silently dropped from a payload-only
      // command. The backend reads these from the node payload.
      for (const key of ["repo_url", "branch_name", "head_commit_sha"]) {
        if (args[key] !== undefined && body[key] === undefined) body[key] = args[key];
      }
      return { method, path, body };
    }
    case "payload":
      return { method, path, body: ensureObject(args.payload, "payload") };
    case "node_ids":
      return { method, path, body: { node_ids: normalizeNodeIds(args.node_ids) } };
    case "subgraph_export":
      return {
        method,
        path,
        body: definedEntries({
          node_ids: normalizeNodeIds(args.node_ids),
          include_descendants: args.include_descendants,
          max_nodes: args.max_nodes,
        }),
      };
    case "merge":
      return {
        method,
        path,
        body: definedEntries({
          node_ids: normalizeNodeIds(args.node_ids),
          expected_revision_by_node: ensureObject(args.expected_revision_by_node, "expected_revision_by_node"),
          title: args.title,
          resolved_node: args.resolved_node === undefined ? undefined : ensureObject(args.resolved_node, "resolved_node"),
        }),
      };
    case "tag_assign":
      return {
        method,
        path,
        body: {
          tag_ids: splitCommaList(args.tag_ids),
          expected_revision: args.expected_revision,
        },
      };
    case "node_delete_bulk":
      return {
        method,
        path,
        body: definedEntries({
          node_ids: normalizeNodeIds(args.node_ids),
          delete_mode: args.delete_mode,
        }),
      };
    case "artifact_delete_bulk":
      return {
        method,
        path,
        body: {
          artifact_ids: normalizeNodeIds(args.artifact_ids, "artifact_ids"),
          expected_revision: args.expected_revision,
        },
      };
    case "wandb_secret":
      return { method, path, body: { api_key: args.api_key } };
    case "huggingface_secret":
      return { method, path, body: { access_token: args.token } };
    case "github_secret":
      return { method, path, body: { token: args.token } };
    case "web_search":
      return {
        method,
        path,
        body: definedEntries({
          query: args.query,
          project_id: args.project_id,
          // Accept --num-results or --top-k; send a single canonical field.
          num_results:
            args.num_results !== undefined
              ? Number(args.num_results)
              : args.top_k !== undefined
                ? Number(args.top_k)
                : undefined,
          category: args.category,
          search_type: args.search_type,
          // --log false and --no-log both turn ambient provenance logging off.
          log: args.no_log === true ? false : args.log,
        }),
      };
    case "web_fetch":
      return {
        method,
        path,
        body: definedEntries({
          url: args.url,
          project_id: args.project_id,
          with_summary:
            args.no_summary === true || args.no_with_summary === true ? false : args.with_summary,
          text_limit: args.text_limit === undefined ? undefined : Number(args.text_limit),
          log: args.no_log === true ? false : args.log,
        }),
      };
    default:
      return { method, path, body: defaultBody(args, command) };
  }
}

function detectMediaType(filename) {
  const ext = path.extname(filename).toLowerCase();
  switch (ext) {
    case ".json": return "application/json";
    case ".txt":
    case ".md": return "text/plain";
    case ".csv": return "text/csv";
    case ".html":
    case ".htm": return "text/html";
    case ".png": return "image/png";
    case ".jpg":
    case ".jpeg": return "image/jpeg";
    case ".svg": return "image/svg+xml";
    case ".pdf": return "application/pdf";
    default: return "application/octet-stream";
  }
}

function resolveUploadUrl(uploadUrl, baseUrl) {
  if (!uploadUrl || typeof uploadUrl !== "string") throw new Error("prepare response included an invalid upload_url");
  return new URL(uploadUrl, `${baseUrl.replace(/\/+$/, "")}/`).toString();
}

async function normalizeUploadItems(items) {
  const rawItems = ensureArray(items, "items");
  if (!rawItems.length) throw new Error("items must contain at least one upload item");
  if (rawItems.length > MAX_UPLOAD_ITEMS) throw new Error(`items must contain at most ${MAX_UPLOAD_ITEMS} entries`);
  const normalized = [];
  for (const [index, item] of rawItems.entries()) {
    if (!item || typeof item !== "object" || Array.isArray(item)) throw new Error(`items[${index}] must be an object`);
    if (!item.local_path || typeof item.local_path !== "string") throw new Error(`items[${index}].local_path must be a non-empty string`);
    if (!item.artifact_type || typeof item.artifact_type !== "string") throw new Error(`items[${index}].artifact_type must be a non-empty string`);
    if (!ALLOWED_ARTIFACT_TYPES.has(item.artifact_type)) {
      throw new Error(`items[${index}].artifact_type must be one of ${[...ALLOWED_ARTIFACT_TYPES].join(", ")}`);
    }
    const absolutePath = path.isAbsolute(item.local_path) ? item.local_path : path.resolve(process.cwd(), item.local_path);
    const fileStat = await stat(absolutePath).catch(() => null);
    if (!fileStat || !fileStat.isFile()) throw new Error(`local_path not found or not a regular file: ${item.local_path}`);
    if (fileStat.size > MAX_UPLOAD_BYTES) throw new Error(`${item.local_path} exceeds max size ${MAX_UPLOAD_BYTES} bytes`);
    const filename = path.basename(absolutePath);
    normalized.push({
      absolutePath,
      localPath: item.local_path,
      prepare: definedEntries({
        artifact_type: item.artifact_type,
        filename,
        media_type: item.media_type || detectMediaType(filename),
        title: item.title,
        execution_id: item.execution_id,
        note: item.note,
        metadata: item.metadata && typeof item.metadata === "object" && !Array.isArray(item.metadata) ? item.metadata : undefined,
      }),
    });
  }
  return normalized;
}

async function runOneShotUpload(command, args, client) {
  const nodeId = args.node_id;
  const uploadItems = await normalizeUploadItems(args.items);
  const preparePath = fillPath(command.path, args, command.pathParams);
  const prepareBody = {
    expected_revision: args.expected_revision,
    items: uploadItems.map((item) => item.prepare),
  };
  if (process.env.ATLAS_HTTP_ECHO === "1") {
    return {
      requests: [
        { method: "POST", path: preparePath, body: prepareBody },
        ...uploadItems.map((item) => ({ method: "PUT", path: "signed-upload-url", body: { local_path: item.localPath } })),
        { method: "POST", path: `/nodes/${encodeURIComponent(nodeId)}/artifacts/uploads/finalize`, body: { batch_token: "echo-batch-token" } },
      ],
    };
  }
  const prepared = await client.requestJson("POST", preparePath, { body: prepareBody });
  const batch = prepared?.batch || prepared;
  const batchToken = batch?.batch_token;
  const batchItems = batch?.items;
  if (!batchToken || !Array.isArray(batchItems) || batchItems.length !== uploadItems.length) {
    throw new Error("prepare response did not include the expected upload batch envelope");
  }
  for (let index = 0; index < uploadItems.length; index += 1) {
    const bytes = await readFile(uploadItems[index].absolutePath);
    await client.requestRawExternal(batchItems[index].method || "PUT", resolveUploadUrl(batchItems[index].upload_url, client.config.baseUrl), {
      rawBody: bytes,
      extraHeaders: batchItems[index].headers || { "Content-Type": uploadItems[index].prepare.media_type },
    });
  }
  return await client.requestJson("POST", `/nodes/${encodeURIComponent(nodeId)}/artifacts/uploads/finalize`, {
    body: { batch_token: batchToken },
  });
}

export async function runCommand(command, args, client) {
  if (command.bodyMode === "artifact_upload") {
    return await runOneShotUpload(command, args, client);
  }
  const request = requestFor(command, args);
  if (command.raw && process.env.ATLAS_HTTP_ECHO === "1") {
    return client.echo(request.method, request.path, { query: request.query, body: request.body, raw: true });
  }
  if (command.raw) return await client.requestRaw(request.method, request.path, { ...request, public: command.public });
  return await client.requestJson(request.method, request.path, { ...request, public: command.public });
}
