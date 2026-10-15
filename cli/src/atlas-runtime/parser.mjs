import { readFile } from "node:fs/promises";

const GLOBAL_FLAGS = new Set([
  "format",
  "env",
  "out",
  "open",
  "no_open",
  "no_retry",
  "retry_max",
  "wait",
  "wait_timeout",
  "allow_self",
  "timeout",
  "idempotency_key",
  "force",
  "yes",
  "debug",
  "verbose",
  "schema",
  "api_key",
  "base_url",
  "no_project",
]);

const BOOLEAN_GLOBALS = new Set([
  "open",
  "no_open",
  "no_retry",
  "wait",
  "allow_self",
  "force",
  "yes",
  "debug",
  "verbose",
  "schema",
  "no_project",
]);

function kebabToSnake(value) {
  return value.replace(/-/g, "_");
}

function looksLikeJson(value) {
  return (
    (value.startsWith("{") && value.endsWith("}")) ||
    (value.startsWith("[") && value.endsWith("]"))
  );
}

export async function parseValue(value) {
  if (typeof value !== "string") return value;
  if (value.startsWith("@@")) return value.slice(1);
  if (value.startsWith("@")) {
    const target = value.slice(1);
    const raw = target === "-" ? await readFile(0, "utf8") : await readFile(target, "utf8");
    try {
      return JSON.parse(raw);
    } catch {
      return raw;
    }
  }
  if (value === "true") return true;
  if (value === "false") return false;
  if (/^-?\d+$/.test(value)) {
    // Only numericize when it round-trips losslessly — past 2^53 this drops
    // precision, and leading zeros (e.g. zero-padded IDs) are corrupted too.
    // Keep the original string in those cases so numeric IDs survive intact.
    const parsed = Number.parseInt(value, 10);
    return String(parsed) === value ? parsed : value;
  }
  if (/^-?\d+\.\d+$/.test(value)) {
    const parsed = Number.parseFloat(value);
    return String(parsed) === value ? parsed : value;
  }
  if (looksLikeJson(value)) {
    try {
      return JSON.parse(value);
    } catch {
      return value;
    }
  }
  return value;
}

export function normalizeFormat(format) {
  const value = String(format || "json").toLowerCase();
  if (["json", "tsv", "csv", "table", "pretty"].includes(value)) return value;
  throw new Error(`invalid format: ${format}. Expected json, tsv, csv, table, or pretty`);
}

export async function parseOptions(tokens = []) {
  const args = {};
  const runtime = { format: "json" };
  const positional = [];

  for (let index = 0; index < tokens.length; index += 1) {
    const token = tokens[index];
    if (/^[a-zA-Z_][\w-]*=.*/.test(token) && !token.startsWith("--")) {
      throw new Error(`legacy argument syntax is not supported: ${token}. Use --${token.replace(/=.*/, "")} value`);
    }
    if (token === "-h" || token === "--help") {
      runtime.help = true;
      continue;
    }
    if (!token.startsWith("--")) {
      positional.push(token);
      continue;
    }

    const body = token.slice(2);
    const eq = body.indexOf("=");
    const rawKey = eq === -1 ? body : body.slice(0, eq);
    const key = kebabToSnake(rawKey);
    let rawValue = eq === -1 ? undefined : body.slice(eq + 1);
    if (rawValue === undefined) {
      const next = tokens[index + 1];
      if (BOOLEAN_GLOBALS.has(key)) {
        rawValue = "true";
      } else if (next !== undefined && !next.startsWith("--")) {
        rawValue = next;
        index += 1;
      } else {
        rawValue = "true";
      }
    }
    const value = await parseValue(rawValue);
    if (GLOBAL_FLAGS.has(key)) {
      if (key === "format") {
        runtime.format = normalizeFormat(value);
        // Track whether the caller explicitly asked for a format so
        // ``atlas help`` can default to human text but still respect
        // ``--format=json`` for agents and scripts.
        runtime.formatExplicit = true;
      }
      else if (key === "timeout") runtime.timeoutMs = Number(value) * 1000;
      else if (key === "retry_max") runtime.retryMax = Number(value);
      else if (key === "api_key") runtime.apiKey = String(value);
      else if (key === "base_url") runtime.baseUrl = String(value);
      else runtime[key] = value;
    } else {
      args[key] = value;
    }
  }

  if (positional.length) args._positional = positional;
  return { args, runtime };
}

export function requiredFields(command) {
  if (Array.isArray(command.requiredOrder)) return command.requiredOrder;
  const schema = command.schema && typeof command.schema === "object" ? command.schema : {};
  return Array.isArray(schema.required) ? schema.required : [];
}

export function optionalFields(command) {
  const schema = command.schema && typeof command.schema === "object" ? command.schema : {};
  const props = schema.properties || {};
  const required = new Set(requiredFields(command));
  return Object.keys(props).filter((key) => !required.has(key)).sort((a, b) => a.localeCompare(b));
}

export function splitCommaList(value) {
  if (Array.isArray(value)) return value;
  if (value === "" || value === undefined || value === null) return [];
  return String(value).split(",").map((item) => item.trim()).filter(Boolean);
}

export function ensureObject(value, name) {
  if (value && typeof value === "object" && !Array.isArray(value)) return value;
  if (typeof value === "string") {
    try {
      const parsed = JSON.parse(value);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) return parsed;
    } catch {
      // handled below
    }
  }
  throw new Error(`${name} must decode to a JSON object`);
}

export function ensureArray(value, name) {
  if (Array.isArray(value)) return value;
  if (typeof value === "string") {
    try {
      const parsed = JSON.parse(value);
      if (Array.isArray(parsed)) return parsed;
    } catch {
      // handled below
    }
  }
  throw new Error(`${name} must decode to a JSON array`);
}
