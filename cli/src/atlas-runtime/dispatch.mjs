import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import open from "open";
import { AtlasHttpClient } from "./http-client.mjs";
import { getCommand, listCommands, resolveAlias } from "./commands.mjs";
import { commandHelpJson, renderCommandHelp, renderRootHelp, rootHelpJson } from "./help.mjs";
import { emit } from "./output.mjs";
import { parseOptions, requiredFields } from "./parser.mjs";
import { resolveRuntimeConfig } from "./config.mjs";
import { runCommand } from "./handlers.mjs";
import { runLocalCommand } from "./local-commands.mjs";
import { findProjectConfig, projectAutoConfig, projectConfigProjectId } from "./project-config.mjs";

// Commands that auto-resolve their project from atlas.json when the caller
// didn't pass one. `brief` is included so the single most valuable read — "load
// the project context packet" — works with no arguments inside a research repo.
const PROJECT_ID_COMMANDS = new Set([
  "brief",
  "log:append",
  "log:tail",
  "log:search",
  "web:search",
  "web:fetch",
]);

// Gateway node IDs are UUIDs on the wire, but humans see slugs (``able-helm-
// 1359``) in the UI. Resolve any slug-shaped value in node_id / project_id /
// root_node_id flags into a UUID before dispatching, so users don't have to
// hand-paste UUIDs from ``nodes:list`` JSON. UUID-shaped values, env-driven
// flows, and ``ATLAS_HTTP_ECHO`` traffic skip the resolver.
const UUID_RE = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;
const SLUG_RESOLVE_FIELDS = ["node_id", "project_id", "root_node_id", "root", "plan_id", "hypothesis_id", "parent_run_id", "attach", "save_to", "resume", "project"];

async function resolveOneSlug(slug, config) {
  const base = (config.baseUrl || "").replace(/\/+$/, "");
  const url = `${base}/nodes/resolve-by-slug?slug_name=${encodeURIComponent(slug)}`;
  const response = await fetch(url, {
    method: "GET",
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${config.apiKey}`,
    },
    signal: AbortSignal.timeout(10_000),
  });
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(`could not resolve slug \`${slug}\`: HTTP ${response.status}${text ? ` — ${text.slice(0, 200)}` : ""}`);
  }
  const payload = await response.json().catch(() => ({}));
  return payload?.node_id || payload?.id || null;
}

async function maybeResolveSlugIdentifiers(args, config) {
  if (process.env.ATLAS_HTTP_ECHO === "1") return;
  if (!config.apiKey) return;
  for (const field of SLUG_RESOLVE_FIELDS) {
    const value = args[field];
    if (typeof value !== "string" || !value) continue;
    if (UUID_RE.test(value)) continue;
    // Looks like a slug. Try to resolve; surface a clearer error than the
    // raw HTTP 404 if the slug doesn't exist.
    try {
      const nodeId = await resolveOneSlug(value, config);
      if (nodeId) args[field] = nodeId;
    } catch (error) {
      throw new Error(`${field}: ${error.message}`);
    }
  }
}

async function maybeInjectProjectId(command, args, runtime) {
  if (!PROJECT_ID_COMMANDS.has(command.name) || runtime.no_project === true) return;
  if (args.project_id !== undefined && args.project_id !== null && args.project_id !== "") return;
  const found = await findProjectConfig();
  if (!found) return;
  // Honor the activation contract: a project that opted out of ambient
  // behavior (auto.enabled:false) should not have its id auto-injected.
  if (!projectAutoConfig(found.config).enabled) return;
  const projectId = projectConfigProjectId(found.config);
  if (!projectId) return;
  args.project_id = projectId;
  // Mirror the scope-injection note so wrong-project attribution (e.g. a
  // parent-dir atlas.json) is visible and --no-project is discoverable.
  // stderr keeps stdout machine-parseable for --format=json.
  process.stderr.write(
    `atlas: using project ${projectId} from ${found.path} (use --no-project to disable)\n`,
  );
}

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PACKAGE_PATH = path.resolve(__dirname, "..", "..", "package.json");

async function packageVersion() {
  return JSON.parse(await readFile(PACKAGE_PATH, "utf8")).version;
}

function splitCommand(argv) {
  if (!argv.length) return { kind: "help", commandName: null, rest: [] };
  if (argv[0] === "help") {
    const rest = argv.slice(1);
    const commandParts = [];
    const flagParts = [];
    let inFlags = false;
    for (const token of rest) {
      if (token.startsWith("-")) inFlags = true;
      if (inFlags) flagParts.push(token);
      else commandParts.push(token);
    }
    const commandName = commandParts.length ? resolveAlias(commandParts.join(":")) : null;
    return { kind: "help", commandName, rest: flagParts };
  }
  let command = getCommand(resolveAlias(argv[0]));
  let consumed = 1;
  if (!command && argv.length >= 2) {
    const joined = `${argv[0]}:${argv[1]}`;
    command = getCommand(resolveAlias(joined));
    consumed = 2;
  }
  if (!command) return null;
  return { kind: "command", command, rest: argv.slice(consumed) };
}

// Hint text shown next to "X is required" so the user knows where to look
// instead of just being told that they're missing a UUID. Keep short — these
// land in error messages, not docs.
const REQUIRED_FIELD_HINTS = {
  node_id: "try `atlas node:list` or pass a slug like `able-helm-1359`",
  project_id: "try `atlas project:list` to find one, or `atlas project:create` to bootstrap",
  root_node_id: "the project root; `atlas project:list` shows roots",
  artifact_id: "try `atlas evidence:list --node <id>`",
  key_id: "try `atlas key:list`",
  tag_id: "try `atlas help label:assign`",
  hypothesis_id: "try `atlas brief --project <id>` to see open hypotheses",
  plan_id: "the experiment:plan node this run executes",
  query: "pass `--query \"...\"`",
  text: "pass `--text \"...\"` (or `--text @notes.md`)",
  url: "pass `--url <https://...>`",
};

async function normalizeSecrets(args, command) {
  const normalized = { ...args };
  for (const [envArg, targetArg] of Object.entries(command.secretEnvArgs || {})) {
    if (normalized[targetArg] !== undefined || normalized[envArg] === undefined) continue;
    const envName = String(normalized[envArg] || "");
    if (!envName) throw new Error(`${envArg} must name a non-empty environment variable`);
    const secret = process.env[envName];
    if (!secret) throw new Error(`environment variable ${envName} is not set`);
    normalized[targetArg] = secret;
  }
  return normalized;
}

// Map the short ``--node`` / ``--project`` / ``--plan`` / ``--hypothesis``
// flags to the canonical ``*_id`` fields the schemas use, so users don't
// have to type the longer variant. ``--project`` is schema-aware: commands
// whose route takes ``root`` (run:compare, leaderboard) get it there.
// Done before required-field validation so the alias counts.
function applyIdAliases(normalized, command) {
  const schemaProps = command?.schema?.properties || {};
  const aliasPairs = [
    ["node", "node_id"],
    ["plan", "plan_id"],
    ["hypothesis", "hypothesis_id"],
    ["parent_run", "parent_run_id"],
  ];
  for (const [short, target] of aliasPairs) {
    if (normalized[short] !== undefined && normalized[target] === undefined) {
      normalized[target] = normalized[short];
      delete normalized[short];
    }
  }
  // Commands that declare a literal `project` field (optimize:start) keep it;
  // everywhere else --project is sugar for project_id / root.
  if (normalized.project !== undefined && !schemaProps.project) {
    const wantsRoot = !schemaProps.project_id && Boolean(schemaProps.root);
    const target = wantsRoot ? "root" : "project_id";
    if (normalized[target] === undefined) {
      normalized[target] = normalized.project;
      delete normalized.project;
    }
  }
}

// New research-verb fields that read best as comma lists on the command
// line but travel as JSON arrays on the wire. Already-parsed arrays (from
// ``--field '["a","b"]'`` or @file JSON) pass through untouched.
const COMMA_LIST_FIELDS = {
  "hypothesis:add": ["assumptions", "expected_observations", "disconfirmers"],
  "hypothesis:update": ["because"],
  "experiment:plan": ["risks"],
  "decision:add": ["alternatives", "basis"],
};

function applyCommaListFields(commandName, args) {
  const fields = COMMA_LIST_FIELDS[commandName];
  if (!fields) return;
  for (const field of fields) {
    const value = args[field];
    if (value === undefined || Array.isArray(value)) continue;
    if (typeof value === "string") {
      args[field] = value.split(",").map((item) => item.trim()).filter(Boolean);
    }
  }
}

// Subset of commands where ``--limit`` is the more intuitive flag name but
// the underlying route uses ``per_page``. Mapped explicitly so we don't
// silently rewrite ``--limit`` for routes (like node:history) where the
// API really does expect ``limit``.
const LIMIT_TO_PER_PAGE = new Set(["node:list"]);

function applyLimitAlias(commandName, args) {
  if (!LIMIT_TO_PER_PAGE.has(commandName)) return;
  if (args.limit !== undefined && args.per_page === undefined) {
    args.per_page = args.limit;
    delete args.limit;
  }
}

// Commands that get a sensible default page size if the caller didn't pass
// one explicitly. Cap is 200; default 50 matches what most users want for an
// at-a-glance view and is small enough to render readably with ``pretty``.
const DEFAULT_PER_PAGE = {
  "node:list": 50,
};

function applyDefaultPageSize(commandName, args) {
  const def = DEFAULT_PER_PAGE[commandName];
  if (def && args.per_page === undefined && args.page === undefined && args.cursor === undefined) {
    args.per_page = def;
  }
}

async function normalizeArgs(args, command, runtime) {
  const normalized = await normalizeSecrets(args, command);
  applyIdAliases(normalized, command);
  // Bind a bare positional to the sole path param so `atlas competition
  // parameter-golf` works like `--slug=parameter-golf`. Only when the command
  // has exactly one path param and it wasn't already provided as a flag.
  if (Array.isArray(command.pathParams) && command.pathParams.length === 1) {
    const only = command.pathParams[0];
    const positional = Array.isArray(normalized._positional) ? normalized._positional : [];
    if ((normalized[only] === undefined || normalized[only] === "") && positional.length) {
      normalized[only] = positional[0];
    }
  }
  // Resolve project_id from atlas.json BEFORE required-field validation so a
  // command whose project_id is required (e.g. `brief`) works with no args
  // inside a research repo. Explicit --project (mapped above) still wins.
  await maybeInjectProjectId(command, normalized, runtime);
  applyCommaListFields(command.name, normalized);
  if (command.destructive && runtime.yes !== true && runtime.force !== true) {
    throw new Error(`${command.name} is destructive and requires --yes`);
  }
  for (const field of requiredFields(command)) {
    if (field === "yes") continue;
    if (command.name === "label:assign" && field === "tag_ids" && normalized[field] === "") continue;
    if (normalized[field] === undefined || normalized[field] === null || normalized[field] === "") {
      const hint = REQUIRED_FIELD_HINTS[field];
      const suffix = hint ? ` — ${hint}` : "";
      throw new Error(`--${field.replace(/_/g, "-")} is required${suffix}`);
    }
  }
  if (command.name === "integration:wandb:set" && !normalized.api_key) {
    throw new Error("api_key or api_key_env is required");
  }
  if (command.name === "integration:huggingface:set" && !normalized.token) {
    throw new Error("token or token_env is required");
  }
  if (command.name === "github:set" && !normalized.token) {
    throw new Error("token or token_env is required");
  }
  return normalized;
}

// Client-side post-filters for endpoints whose query API doesn't already
// accept the filter. Keeps the request shape unchanged on the wire so the
// existing tests / backend continue to work; the filter only ever narrows
// the result set the user sees.
function postProcessResult(commandName, args, result) {
  if (commandName === "key:list" && args.active_only && result && Array.isArray(result.api_keys)) {
    const filtered = result.api_keys.filter((row) => !row.revoked_at);
    return { ...result, api_keys: filtered, count: filtered.length };
  }
  return result;
}

function maybeOpenUrl(command, payload, runtime) {
  if (!runtime.open || !command.openUrl) return;
  const url = payload?.url || payload?.install_url || payload?.html_url;
  if (typeof url === "string" && /^https?:\/\//.test(url)) {
    open(url).catch(() => {
      process.stderr.write(`atlas: couldn't open browser; visit ${url}\n`);
    });
  }
}

export async function tryRuntimeCommand(argv = process.argv) {
  const args = argv.slice(2);
  if (args[0] === "--version" || args[0] === "-V" || args[0] === "version") {
    await emit(await packageVersion(), "json");
    return true;
  }
  if (args[0] === "--help" || args[0] === "-h" || args.length === 0) {
    await emit(renderRootHelp(), "json");
    return true;
  }
  if (args[0] === "setup" || args[0] === "uninstall") return false;

  const split = splitCommand(args);
  if (!split) {
    const known = listCommands().map((command) => command.name).join(", ");
    throw new Error(`unknown command: ${args[0]}. Known runtime commands: ${known}`);
  }

  const { args: parsedArgs, runtime } = await parseOptions(split.rest);
  if (split.kind === "help") {
    if (runtime.schema && !split.commandName) throw new Error("--schema requires a command name");
    // ``atlas help`` defaults to human-readable text. The huge JSON
    // dump (full schema for every command) is only emitted when the
    // caller explicitly asks for it via ``--format=json`` — that's the
    // shape agents and scripts want, but it's unreadable in a terminal
    // and was previously the default. ``--schema`` implies JSON since
    // there's no useful text rendering of a JSON schema.
    const wantJson = runtime.schema || (runtime.formatExplicit && runtime.format === "json");
    if (wantJson) {
      const payload = split.commandName ? commandHelpJson(split.commandName) : rootHelpJson();
      if (!payload) throw new Error(`unknown command: ${split.commandName}`);
      if (runtime.schema) {
        await emit({ name: split.commandName, schema: payload.schema }, "json", runtime.out);
      } else {
        await emit(payload, "json", runtime.out);
      }
    } else {
      const text = split.commandName ? renderCommandHelp(split.commandName) : renderRootHelp();
      if (!text) throw new Error(`unknown command: ${split.commandName}`);
      await emit(text, "json", runtime.out);
    }
    return true;
  }

  if (runtime.help) {
    await emit(renderCommandHelp(split.command.name), "json", runtime.out);
    return true;
  }
  if (runtime.schema) throw new Error("--schema is only valid with `atlas help <command>`");

  const commandArgs = await normalizeArgs(parsedArgs, split.command, runtime);
  applyLimitAlias(split.command.name, commandArgs);
  applyDefaultPageSize(split.command.name, commandArgs);
  const config = await resolveRuntimeConfig(runtime);
  await maybeResolveSlugIdentifiers(commandArgs, config);
  // Effective format resolution. Users can:
  //   1) pass ``--format=<fmt>`` to force a format (highest precedence),
  //   2) set ``default_format`` in their profile,
  //   3) get TTY-aware defaults — humans hitting Enter at a terminal get
  //      the new ``pretty`` rendering; scripts piping the output (no TTY)
  //      keep the old JSON default so existing automation isn't broken.
  const effectiveFormat = runtime.formatExplicit
    ? runtime.format
    : (config.defaultFormat || (process.stdout.isTTY ? "pretty" : "json"));
  if (split.command.local) {
    const result = await runLocalCommand(split.command, commandArgs, config, runtime);
    await emit(result, effectiveFormat, runtime.out, split.command.name);
    return true;
  }
  const client = new AtlasHttpClient(config, {
    ...runtime,
    commandName: split.command.name,
  });
  let result = await runCommand(split.command, commandArgs, client);
  result = postProcessResult(split.command.name, commandArgs, result);
  maybeOpenUrl(split.command, result, runtime);
  if (result instanceof Response) {
    const bytes = new Uint8Array(await result.arrayBuffer());
    await emit(bytes, runtime.format, runtime.out, split.command.name);
  } else {
    await emit(result, effectiveFormat, runtime.out, split.command.name);
  }
  return true;
}
