import http from "node:http";
import crypto from "node:crypto";
import { execFile, spawn } from "node:child_process";
import { readFile, mkdtemp, rm, writeFile, mkdir } from "node:fs/promises";
import { homedir, tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import open from "open";
import {
  clearProfileCredentials,
  clearProfileKeychainCredential,
  configPath,
  listProfileConfigs,
  setProfileConfig,
  setProfileKeychainCredential,
  showProfileConfig,
  unsetProfileConfig,
  updateProfileConfig,
} from "./config.mjs";
import { splitCommaList } from "./parser.mjs";
import { writeProjectConfig } from "./project-config.mjs";
import { flushSpool, listSpool, spoolPayload, spoolStats, SPOOL_DIR } from "./spool.mjs";
import { unlink as fsUnlink, readFile as fsReadFile, stat as fsStat } from "node:fs/promises";
import readline from "node:readline";
import {
  inferMetricDirection,
  parseDurationSeconds,
  deriveMetricToken,
  buildSuccessCriterion,
  formatNumber,
  resolveRunCommand,
  renderBenchmarkSh,
  renderScorePy,
  renderGateSh,
} from "./autoresearch.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PACKAGE_ROOT = path.resolve(__dirname, "..", "..");

function buildUrl(baseUrl, route) {
  return `${baseUrl.replace(/\/+$/, "")}${route.startsWith("/") ? route : `/${route}`}`;
}

async function fetchJson(baseUrl, route, { method = "GET", body, apiKey, timeoutMs = 30_000 } = {}) {
  const headers = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (apiKey) headers.Authorization = `Bearer ${apiKey}`;
  const response = await fetch(buildUrl(baseUrl, route), {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(timeoutMs),
  });
  const text = await response.text();
  const payload = text ? JSON.parse(text) : {};
  if (!response.ok) throw new Error(`HTTP ${response.status}: ${text.slice(0, 500)}`);
  return payload;
}

// Atlas "Soft Porcelain" — same palette + Computer Modern serif body the
// dashboard uses, just inlined so the callback page works without any
// external assets. Auto-respects ``prefers-color-scheme`` so users in
// dark mode don't get a flashbang. The CLI still resolves the login
// before the browser reaches this page; the page is purely confirmation.
const LOGIN_COMPLETE_HTML = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Atlas — signed in</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root {
  --bg: #fafbfc;
  --surface: #ffffff;
  --ink: #0f172a;
  --muted: #475569;
  --faint: #64748b;
  --border: rgba(15, 23, 42, 0.10);
  --accent: #0f172a;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0c0c0d;
    --surface: #171717;
    --ink: #fafafa;
    --muted: #a3a3a3;
    --faint: #737373;
    --border: rgba(255, 255, 255, 0.12);
    --accent: #fafafa;
  }
}
html, body { height: 100%; margin: 0; }
body {
  font-family: 'Computer Modern Serif', 'Latin Modern Roman', Georgia, 'Times New Roman', serif;
  background: var(--bg);
  color: var(--ink);
  display: grid;
  place-items: center;
  padding: 32px;
  box-sizing: border-box;
  -webkit-font-smoothing: antialiased;
}
.card {
  width: 100%;
  max-width: 420px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 2px;
  padding: 36px 32px 28px;
  text-align: center;
}
.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--accent);
  display: inline-block;
  margin-bottom: 18px;
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--accent) 12%, transparent);
}
h1 {
  font-size: 22px;
  font-weight: 500;
  line-height: 1.15;
  margin: 0 0 8px;
  letter-spacing: -0.005em;
  color: var(--ink);
}
p.lede {
  font-size: 14px;
  line-height: 1.55;
  margin: 0 0 22px;
  color: var(--muted);
}
.hint {
  font-family: 'JetBrains Mono', 'SF Mono', ui-monospace, monospace;
  font-size: 11px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--faint);
  border-top: 1px solid var(--border);
  padding-top: 16px;
  margin: 0;
}
.brand {
  display: block;
  font-family: 'JetBrains Mono', 'SF Mono', ui-monospace, monospace;
  font-size: 10px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--faint);
  margin-bottom: 18px;
}
</style>
</head>
<body>
  <main class="card">
    <span class="brand">Atlas</span>
    <span class="dot" aria-hidden="true"></span>
    <h1>Signed in to the Atlas CLI</h1>
    <p class="lede">You can close this tab and return to your terminal.<br>The CLI already picked up your key.</p>
    <p class="hint">atlas whoami</p>
  </main>
</body>
</html>`;

function startCallbackServer(expectedState) {
  let server;
  const done = new Promise((resolve, reject) => {
    server = http.createServer((req, res) => {
      try {
        const url = new URL(req.url || "/", "http://127.0.0.1");
        if (url.pathname !== "/callback") {
          res.writeHead(404);
          res.end("Not found");
          return;
        }
        const state = url.searchParams.get("state") || "";
        const exchangeToken = url.searchParams.get("exchange_token") || "";
        if (state !== expectedState || !exchangeToken) {
          res.writeHead(400, { "Content-Type": "text/plain" });
          res.end("Atlas login failed: callback state mismatch.");
          reject(new Error("browser login callback state mismatch"));
          return;
        }
        res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
        res.end(LOGIN_COMPLETE_HTML);
        resolve({ state, exchange_token: exchangeToken });
      } catch (error) {
        reject(error);
      }
    });
    server.on("error", reject);
  });
  return new Promise((resolve, reject) => {
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      resolve({
        server,
        port: address.port,
        done,
      });
    });
    server.on("error", reject);
  });
}

async function runLogin(args, config, runtime) {
  const state = crypto.randomUUID();
  const name = args.name || "atlas-cli";
  if (process.env.ATLAS_HTTP_ECHO === "1") {
    return {
      requests: [
        {
          method: "POST",
          path: "/auth/cli/browser/start",
          body: { state, redirect_uri: "http://127.0.0.1:<port>/callback", name },
        },
        {
          method: "POST",
          path: "/auth/cli/browser/redeem",
          body: { state, exchange_token: "<exchange-token>", redirect_uri: "http://127.0.0.1:<port>/callback" },
        },
      ],
    };
  }
  const callback = await startCallbackServer(state);
  const redirectUri = `http://127.0.0.1:${callback.port}/callback`;
  try {
    const started = await fetchJson(config.baseUrl, "/auth/cli/browser/start", {
      method: "POST",
      body: { state, redirect_uri: redirectUri, name },
      timeoutMs: config.timeoutMs,
    });

    // Always print the approval URL to stderr before attempting to
    // open the browser. Three reasons:
    //   1. Headless / SSH / container shells can't open a browser at
    //      all; without the URL the user is stuck staring at nothing.
    //   2. ``open()`` returns a promise that swallows failures; the
    //      previous ``.catch(() => {})`` made silent failures invisible.
    //   3. stderr keeps ``--format=json`` clean for scripts piping the
    //      successful result on stdout.
    const approvalUrl = started.approval_url;
    process.stderr.write(
      `\nOpening browser to authorize the Atlas CLI…\n` +
        `If your browser doesn't open, paste this URL into one that's signed in:\n\n` +
        `  ${approvalUrl}\n\n` +
        `Waiting for approval (Ctrl-C to cancel)…\n`,
    );
    if (runtime.no_open !== true) {
      try {
        await open(approvalUrl);
      } catch (err) {
        // Browser launch failed - the URL is already printed above,
        // so the user can copy it. Surface the underlying reason to
        // stderr so they know why their browser didn't pop up.
        process.stderr.write(
          `(couldn't auto-open browser: ${err && err.message || err}; ` +
            `paste the URL above manually.)\n`,
        );
      }
    }

    const timeoutMs = Number(runtime.wait_timeout || process.env.ATLAS_LOGIN_TIMEOUT_MS || 300_000);
    const callbackResult = await Promise.race([
      callback.done,
      new Promise((_, reject) => setTimeout(() => reject(new Error("Atlas browser login timed out")), timeoutMs)),
    ]);
    const redeemed = await fetchJson(config.baseUrl, "/auth/cli/browser/redeem", {
      method: "POST",
      body: {
        state,
        exchange_token: callbackResult.exchange_token,
        redirect_uri: redirectUri,
      },
      timeoutMs: config.timeoutMs,
    });
    await updateProfileConfig(config.profile, {
      base_url: config.baseUrl,
      api_key: redeemed.api_key || redeemed.key,
    });

    // Human confirmation on stderr so ``--format=json`` consumers still
    // get a clean JSON blob on stdout. Pulls the most useful identifying
    // fields from ``redeemed.user`` without dumping the whole object.
    const u = redeemed.user || {};
    const who = u.email || u.display_name || u.github_username || "(unknown user)";
    process.stderr.write(
      `\n✓ Logged in as ${who}\n` +
        `  profile : ${config.profile}\n` +
        `  base    : ${config.baseUrl}\n\n`,
    );

    return {
      logged_in: true,
      profile: config.profile,
      base_url: config.baseUrl,
      user: redeemed.user || null,
    };
  } finally {
    callback.server.close();
  }
}

async function runLogout(config) {
  await clearProfileCredentials(config.profile);
  return { logged_out: true, profile: config.profile, config_path: configPath() };
}

async function runDoctor(config) {
  const result = {
    config_path: configPath(),
    profile: config.profile,
    base_url: config.baseUrl,
    auth: { api_key_present: Boolean(config.apiKey), ok: false },
    backend: { ok: false },
    integrations: null,
    spool: { pending: 0 },
    warnings: [],
  };
  try {
    const stats = await spoolStats();
    result.spool = stats;
    if (stats.pending > 0) {
      const ageHours = stats.oldest_age_ms != null ? Math.round(stats.oldest_age_ms / 3600_000) : null;
      const age = ageHours != null && ageHours > 0 ? ` (oldest ${ageHours}h old)` : "";
      const why = stats.last_error ? ` Last error: ${stats.last_error}` : "";
      result.warnings.push(
        `${stats.pending} Flight Recorder ${stats.pending === 1 ? "entry is" : "entries are"} queued in ${SPOOL_DIR}${age}. Drain with \`atlas run:spool:flush\`.${why}`,
      );
    }
  } catch {
    // spool listing is best-effort; ignore filesystem hiccups.
  }
  try {
    result.backend = await fetchJson(config.baseUrl, "/status", { timeoutMs: 10_000 });
  } catch (error) {
    result.backend = { ok: false, error: error.message };
  }
  if (config.apiKey) {
    try {
      const status = await fetchJson(config.baseUrl, "/auth/status", {
        apiKey: config.apiKey,
        timeoutMs: 10_000,
      });
      result.auth = { api_key_present: true, ok: true, status };
    } catch (error) {
      result.auth = { api_key_present: true, ok: false, error: error.message };
    }
    // Check integration freshness. ``doctor`` was returning ``ok:true`` even
    // when a connected GitHub PAT had expired — silent breakage for any
    // downstream ``repo:capture`` / ``repo:pin``. Expired or near-expiry
    // tokens now surface as warnings without changing the auth check itself.
    try {
      const integrations = await fetchJson(config.baseUrl, "/auth/integrations/status", {
        apiKey: config.apiKey,
        timeoutMs: 10_000,
      });
      result.integrations = integrations;
      const gh = integrations?.github || {};
      if (gh.connected && gh.token_expires_at) {
        const expiresMs = Date.parse(gh.token_expires_at);
        const now = Date.now();
        if (Number.isFinite(expiresMs)) {
          if (expiresMs < now) {
            result.warnings.push(`GitHub token expired ${gh.token_expires_at}. Refresh with \`atlas github:reconnect\` (or rotate via \`atlas github:set\`).`);
          } else if (expiresMs - now < 7 * 86400 * 1000) {
            const days = Math.max(1, Math.round((expiresMs - now) / 86400000));
            result.warnings.push(`GitHub token expires in ${days} day${days === 1 ? "" : "s"}. Refresh it with \`atlas github:reconnect\`.`);
          }
        }
      }
    } catch {
      // Integrations endpoint failure is non-fatal for ``doctor``.
    }
  }
  // `ok` reflects whether the compatibility runtime is usable: backend
  // reachable and auth valid. Advisory warnings (a stale spool entry, an expiring GitHub
  // token) are surfaced in `result.warnings` but must NOT flip the verdict —
  // a 44h-old queued telemetry blip doesn't mean onboarding failed. (The old
  // `warnings.length === 0` clause also defeated the stated intent above of
  // letting an expired token warn without failing the auth check.)
  result.ok = Boolean(
    result.backend?.ok
      && (!config.apiKey || result.auth.ok),
  );
  return result;
}

function profileName(args, config) {
  return args.name || config.profile || "default";
}

async function runProfileSet(args, config) {
  const profile = profileName(args, config);
  const patch = {};
  for (const key of ["base_url", "api_key_env", "default_format", "timeout_ms", "retry_max"]) {
    if (args[key] !== undefined) patch[key] = args[key];
  }
  return await setProfileConfig(profile, patch, { makeActive: args.active !== false });
}

async function runKeychainSet(args, config) {
  if (process.platform !== "darwin") {
    throw new Error("secret:set is only supported on macOS. Use config:set --api-key-env <ENV_NAME> and provide that environment variable instead.");
  }
  const profile = profileName(args, config);
  const key = await readFile(0, "utf8");
  const result = await setProfileKeychainCredential(profile, key);
  return { ...result, config_path: configPath(), api_key_present: true };
}

async function runKeychainClear(args, config) {
  const profile = profileName(args, config);
  const result = await clearProfileKeychainCredential(profile);
  return { ...result, config_path: configPath(), api_key_present: false };
}

// `atlas runs:record` — POST a run summary; on transport failure write
// it to `~/.atlas/spool/` so the next CLI run can flush it. The body
// shape is the route's body shape; both `--payload-json @run.json` and
// inline scalar flags (`--project-id`, `--title`, `--outcome`, …) are
// accepted, so an agent can construct the body inline without piping a
// file. Returns the parsed route response plus a `spool` summary line.
async function runRunsRecord(args, config) {
  const baseUrl = config.baseUrl || config.base_url;
  const apiKey = config.apiKey || config.api_key;
  if (!baseUrl) throw new Error("no base_url configured for the active profile");
  if (!apiKey) throw new Error("no api_key configured for the active profile");

  const body = await buildRunsRecordBody(args);

  // Best-effort flush of any spooled entries before the new one, so
  // queued runs from a previous offline window land roughly in order.
  const spoolSummary = await flushSpool(async (route, queuedBody) => {
    await fetchJson(baseUrl, route, { method: "POST", body: queuedBody, apiKey });
  });

  try {
    // ``baseUrl`` already includes ``/api/v1`` (the published default is
    // ``https://app.syntheticsciences.ai/api/v1``). The previous hard-coded
    // route was ``/api/v1/runs:record``, which built ``…/api/v1/api/v1/runs
    // :record`` and silently 404'd in production — Flight Recorder writes
    // looked like they spooled successfully but every single one was a
    // network failure. Just pass the route relative to the base URL.
    const result = await fetchJson(baseUrl, "/runs:record", {
      method: "POST",
      body,
      apiKey,
    });
    return { ...result, spool: spoolSummary };
  } catch (err) {
    const spoolPath = await spoolPayload("/runs:record", body);
    return {
      spooled: true,
      spool_path: spoolPath,
      error: err && err.message,
      spool: { ...spoolSummary, still_queued: spoolSummary.still_queued + 1 },
    };
  }
}

// Detect the git state of a working tree so every recorded run is linked
// to the exact code that produced it ("GitHub for science") without the
// agent having to remember a separate repo:capture call. Best-effort: any
// git failure (not a repo, git missing) returns null and the run records
// without code state. Exported for tests.
export async function detectGitState(cwd = process.cwd()) {
  const git = (gitArgs) =>
    new Promise((resolve) => {
      execFile("git", gitArgs, { cwd, timeout: 5_000 }, (error, stdout) =>
        resolve(error ? null : String(stdout || "").trim()),
      );
    });
  const sha = await git(["rev-parse", "HEAD"]);
  if (!sha) return null;
  const [repoUrl, branch, status] = await Promise.all([
    git(["remote", "get-url", "origin"]),
    git(["rev-parse", "--abbrev-ref", "HEAD"]),
    git(["status", "--porcelain"]),
  ]);
  return {
    repo_url: repoUrl || null,
    branch_name: branch && branch !== "HEAD" ? branch : null,
    head_commit_sha: sha,
    git_dirty: status === null ? null : status.length > 0,
  };
}

// Read an EVAL.md-style results doc. An explicit path (from `--eval`) must
// exist; otherwise probe the conventional locations in the cwd and return the
// first that exists (capped so a giant log can't bloat the node body). The
// detected file becomes the run node's results-first body.
const EVAL_DOC_CANDIDATES = ["EVAL.md", ".atlas/EVAL.md", "eval.md"];
const EVAL_DOC_MAX_CHARS = 20000;

export async function readEvalDoc(explicitPath) {
  const tryRead = async (p) => {
    try {
      const text = await readFile(p, "utf8");
      return text.length > EVAL_DOC_MAX_CHARS ? text.slice(0, EVAL_DOC_MAX_CHARS) : text;
    } catch {
      return null;
    }
  };
  if (explicitPath !== undefined && String(explicitPath).trim() !== "") {
    const resolved = path.resolve(String(explicitPath));
    const text = await tryRead(resolved);
    if (text === null) throw new Error(`--eval file not found: ${explicitPath}`);
    return text;
  }
  for (const rel of EVAL_DOC_CANDIDATES) {
    const text = await tryRead(path.resolve(process.cwd(), rel));
    if (text !== null) return text;
  }
  return null;
}

// Build the runs:record body from CLI args. Two shapes:
//   1) --payload-json @run.json   the whole body, verbatim
//   2) inline flags               --project-id, --title, --config-json,
//                                 --metrics-json, --stdout-tail,
//                                 --exit-code, --outcome, --failure-mode,
//                                 --run-cluster-key
// (1) wins if both are present; we shallow-merge inline flags on top so
// scripts can use a base file and override single fields.
export async function buildRunsRecordBody(args) {
  let body = {};
  if (args.payload_json) {
    body = await readJsonArg(args.payload_json);
    if (body === null || typeof body !== "object" || Array.isArray(body)) {
      throw new Error("--payload-json must contain a JSON object");
    }
  }
  if (args.project_id !== undefined) body.project_id = args.project_id;
  if (args.title !== undefined) body.title = args.title;
  if (args.stdout_tail !== undefined) body.stdout_tail = args.stdout_tail;
  if (args.exit_code !== undefined) {
    const n = Number(args.exit_code);
    if (!Number.isFinite(n)) throw new Error("--exit-code must be a number");
    body.exit_code = n;
  }
  if (args.outcome !== undefined) body.outcome = args.outcome;
  if (args.failure_mode !== undefined) body.failure_mode = args.failure_mode;
  if (args.run_cluster_key !== undefined) body.run_cluster_key = args.run_cluster_key;
  if (args.plan_id !== undefined) body.plan_id = args.plan_id;
  if (args.hypothesis_id !== undefined) body.hypothesis_id = args.hypothesis_id;
  if (args.parent_run_id !== undefined) body.parent_run_id = args.parent_run_id;
  if (args.candidate_idx !== undefined) {
    const idx = Number(args.candidate_idx);
    if (!Number.isFinite(idx)) throw new Error("--candidate-idx must be a number");
    body.candidate_idx = idx;
  }
  if (args.config_json !== undefined) body.config = await readJsonArg(args.config_json);
  if (args.metrics_json !== undefined) body.metrics = await readJsonArg(args.metrics_json);
  if (args.scorecard_json !== undefined) body.scorecard = await readJsonArg(args.scorecard_json);

  // Results-doc convention (EVAL.md): attach a human-readable results file as
  // the run's body so every run reads results-first. `--eval <path>` wins;
  // otherwise auto-detect a results doc in the cwd. `--no-eval` opts out.
  if (body.eval_markdown === undefined && args.no_eval !== true) {
    const evalDoc = await readEvalDoc(args.eval);
    if (evalDoc) body.eval_markdown = evalDoc;
  }

  // Auto-capture the working tree's git state unless the caller opted out
  // (--no-git) or already supplied code-state fields explicitly.
  if (args.no_git !== true && body.repo_url === undefined && body.head_commit_sha === undefined) {
    const gitState = await detectGitState();
    if (gitState) {
      if (gitState.repo_url) body.repo_url = gitState.repo_url;
      if (gitState.branch_name) body.branch_name = gitState.branch_name;
      body.head_commit_sha = gitState.head_commit_sha;
      if (gitState.git_dirty !== null) body.git_dirty = gitState.git_dirty;
    }
  }

  if (!body.project_id) {
    throw new Error("project_id is required (pass --project-id or include it in --payload-json)");
  }
  return body;
}

// `--payload-json @path` reads the file; otherwise parse the arg as JSON.
async function readJsonArg(value) {
  let raw = value;
  if (typeof value === "string" && value.startsWith("@")) {
    raw = await readFile(value.slice(1), "utf8");
  }
  if (typeof raw !== "string") return raw;
  try {
    return JSON.parse(raw);
  } catch (err) {
    throw new Error(`invalid JSON: ${err && err.message}`);
  }
}

async function buildLogAppendBody(args) {
  let body = {};
  if (args.payload_json) {
    body = await readJsonArg(args.payload_json);
    if (body === null || typeof body !== "object" || Array.isArray(body)) {
      throw new Error("--payload-json must contain a JSON object");
    }
  }
  if (args.project_id !== undefined) body.project_id = args.project_id;
  if (args.entry_type !== undefined) body.entry_type = args.entry_type;
  if (args.title !== undefined) body.title = args.title;
  if (args.body !== undefined) {
    body.body = typeof args.body === "string" && args.body.startsWith("@")
      ? await readFile(args.body.slice(1), "utf8")
      : args.body;
  }
  if (args.refs_json !== undefined) body.refs = await readJsonArg(args.refs_json);
  if (!body.project_id) throw new Error("project_id is required (pass --project or run inside an atlas.json project)");
  if (!body.title || !String(body.title).trim()) throw new Error("--title is required");
  if (body.refs !== undefined && !Array.isArray(body.refs)) throw new Error("--refs-json must be a JSON array");
  return body;
}

async function runLogAppend(args, config) {
  const baseUrl = config.baseUrl || config.base_url;
  const apiKey = config.apiKey || config.api_key;
  if (!baseUrl) throw new Error("no base_url configured for the active profile");
  if (!apiKey) throw new Error("no api_key configured for the active profile");
  const body = await buildLogAppendBody(args);

  const spoolSummary = await flushSpool(async (route, queuedBody) => {
    await fetchJson(baseUrl, route, { method: "POST", body: queuedBody, apiKey });
  });

  try {
    const result = await fetchJson(baseUrl, "/research/log", {
      method: "POST",
      body,
      apiKey,
    });
    return { ...result, spool: spoolSummary };
  } catch (err) {
    const spoolPath = await spoolPayload("/research/log", body);
    return {
      spooled: true,
      spool_path: spoolPath,
      error: err && err.message,
      spool: { ...spoolSummary, still_queued: spoolSummary.still_queued + 1 },
    };
  }
}

// `atlas note:add` — drop a freeform note as an insight node under a
// project. Same surface humans use in Journal; agents reach for this
// when they want to record an observation that *isn't* a run (a hunch,
// a TODO, a question for the user). The route already in place
// (POST /nodes/commit-new with a payload_json envelope) handles the
// shape; we just build the envelope.
async function runNoteAdd(args, config) {
  const baseUrl = config.baseUrl || config.base_url;
  const apiKey = config.apiKey || config.api_key;
  if (!baseUrl) throw new Error("no base_url configured for the active profile");
  if (!apiKey) throw new Error("no api_key configured for the active profile");
  if (!args.project_id) throw new Error("--project-id is required");

  let body = args.text;
  if (typeof body === "string" && body.startsWith("@")) {
    body = await readFile(body.slice(1), "utf8");
  }
  if (!body || !String(body).trim()) {
    throw new Error("--text is required (text content or @file path)");
  }
  const content = String(body).trim();
  const firstLine = content.split(/\r?\n/, 1)[0].slice(0, 140);
  const title = (args.title && String(args.title).trim()) || firstLine || "note";

  // The /nodes/commit-new envelope expects ``local_temp_node_id`` (client
  // idempotency UUID), ``parent_ids``, and ``staged_payload`` with the
  // node-shaped fields. The previous {create,update,commit} envelope was
  // an older protocol that the backend rejects with HTTP 400 —
  // ``payload_json missing required keys: local_temp_node_id, parent_ids,
  // staged_payload``.
  const envelope = {
    local_temp_node_id: crypto.randomUUID(),
    parent_ids: [args.project_id],
    staged_payload: {
      title,
      summary: title,
      content,
      kind: "insight",
      outcome: "completed",
      // Insight nodes commit only with a non-empty ``insights[]``; the
      // title is the most honest single-line distillation we have.
      insights: [title],
    },
  };
  // Same double-prefix bug as runs:record — baseUrl already ends in
  // /api/v1, so the route is plain ``/nodes/commit-new``.
  return await fetchJson(baseUrl, "/nodes/commit-new", {
    method: "POST",
    body: { payload_json: JSON.stringify(envelope) },
    apiKey,
  });
}

// `atlas notebook:cell` — record a single notebook cell + its output.
// Thin wrapper over runs:record: the cell source goes into the config
// payload (so the matrix view can show "which cell"), the output is the
// stdout_tail, and outcome defaults to success unless --errored is set.
// We keep the route shape and offline behaviour identical to runs:record
// so agents only need to learn one capture surface.
async function runNotebookCell(args, config) {
  const cellSource = args.source && args.source.startsWith("@")
    ? await readFile(args.source.slice(1), "utf8")
    : args.source;
  const cellOutput = args.output && args.output.startsWith("@")
    ? await readFile(args.output.slice(1), "utf8")
    : args.output;

  const merged = {
    ...args,
    title: args.title || (args.cell_id ? `cell ${args.cell_id}` : "notebook cell"),
    outcome: args.outcome || (args.errored ? "failure" : "success"),
    stdout_tail: cellOutput,
    // A notebook cell carries its own output; never fold a repo EVAL.md in.
    no_eval: true,
    config_json: JSON.stringify({
      kind: "notebook_cell",
      cell_id: args.cell_id,
      notebook: args.notebook,
      source: cellSource,
    }),
  };
  // Reuse runs:record's body builder + spool semantics by routing
  // through the same handler.
  return await runRunsRecord(merged, config);
}

// `atlas project:list` — list nodes that look like a project root so a user
// can find the ``--project-id`` value most other commands ask for. The
// backend doesn't have a dedicated "list projects" route, so we fan out to
// `/nodes` and locally filter by kind + title prefix. Same shape as
// `nodes:list` to keep the renderer happy.
async function runProjectList(args, config) {
  const baseUrl = config.baseUrl || config.base_url;
  const apiKey = config.apiKey || config.api_key;
  if (!baseUrl) throw new Error("no base_url configured for the active profile");
  if (!apiKey) throw new Error("no api_key configured for the active profile");
  const limit = Math.max(1, Math.min(200, Number(args.limit) || 50));
  const path = `/nodes?root_only=true&page_size=${encodeURIComponent(limit)}&projection=full`;
  const data = await fetchJson(baseUrl, path, { apiKey });
  const nodes = Array.isArray(data?.nodes) ? data.nodes : [];
  // Project identity comes from graph topology; a custom title is still a root.
  let projects = nodes;
  if (args.orphaned) {
    // No child_ids => the project has no nodes hanging off it. Cheap signal
    // for "session never produced anything"; the dashboard would render it
    // as an empty root.
    projects = projects.filter((n) => !Array.isArray(n.child_ids) || n.child_ids.length === 0);
  }
  return { nodes: projects, total: projects.length };
}

// `atlas project:create` — find-or-create the project root for this folder /
// repo through the dedupe-aware agent surface, so bootstrap can be re-run on
// every session without minting duplicates. The dedupe key prefers the repo
// identity (stable across clones and machines) and falls back to the
// absolute folder path — the same shapes the backend documents.
async function runProjectCreate(args, config) {
  // Echo mode (tests / dry inspection): don't hit the network. Return a
  // deterministic stub so `project:create` and `init` are inspectable offline.
  if (process.env.ATLAS_HTTP_ECHO === "1") {
    const cwd = args.path ? path.resolve(String(args.path)) : process.cwd();
    const title = String(args.title || "").trim() || `Project: ${path.basename(cwd)}`;
    const repoUrl = args.repo_url ? String(args.repo_url).trim() : "";
    return {
      project_id: "echo-project",
      title,
      deduped: false,
      dedupe_key: repoUrl ? `repo:${repoUrl}` : `local-folder:${cwd}`,
      repo_url: repoUrl || null,
      echo: true,
    };
  }

  const baseUrl = config.baseUrl || config.base_url;
  const apiKey = config.apiKey || config.api_key;
  if (!baseUrl) throw new Error("no base_url configured for the active profile");
  if (!apiKey) throw new Error("no api_key configured for the active profile");

  const cwd = args.path ? path.resolve(String(args.path)) : process.cwd();
  let repoUrl = args.repo_url ? String(args.repo_url).trim() : "";
  if (!repoUrl) {
    repoUrl = await new Promise((resolve) => {
      execFile(
        "git",
        ["remote", "get-url", "origin"],
        { cwd, timeout: 5_000 },
        (error, stdout) => resolve(error ? "" : String(stdout || "").trim()),
      );
    });
  }
  const dedupeKey = repoUrl ? `repo:${repoUrl}` : `local-folder:${cwd}`;
  const title = String(args.title || "").trim() || `Project: ${path.basename(cwd)}`;

  const response = await fetch(`${baseUrl.replace(/\/$/, "")}/projects`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      title,
      repo_url: repoUrl || null,
      dedupe_key: dedupeKey,
    }),
    signal: AbortSignal.timeout(30_000),
  });
  const text = await response.text();
  if (!response.ok) {
    throw new Error(`project:create failed (HTTP ${response.status}): ${text.slice(0, 400)}`);
  }
  const payload = text ? JSON.parse(text) : {};
  return {
    project_id: payload.project_id,
    title: payload.title ?? title,
    deduped: Boolean(payload.deduped),
    dedupe_key: payload.dedupe_key ?? dedupeKey,
    repo_url: payload.repo_url ?? (repoUrl || null),
  };
}

// Zero-config run-command detection: probe the conventional run scripts and
// pre-fill atlas.json's run_command so an experiment "just runs" in a research
// repo. Mirrors OpenResearch's run-script auto-detection.
const RUN_SCRIPT_CANDIDATES = [
  ".atlas/run.sh",
  "run.sh",
  "scripts/run.sh",
  "bin/run.sh",
  "runs/run.sh",
  ".atlas/speedrun.sh",
  "speedrun.sh",
  "scripts/speedrun.sh",
];

export async function detectRunCommand(cwd) {
  for (const rel of RUN_SCRIPT_CANDIDATES) {
    try {
      await readFile(path.join(cwd, rel), "utf8");
      return `bash ${rel}`;
    } catch {
      // keep probing
    }
  }
  return null;
}

// `atlas init` writes atlas.json, which turns on ambient Atlas behavior for
// every agent session at or below this directory (the CLI walks *up* the tree
// to find the nearest atlas.json). Running it in $HOME or a filesystem root
// would therefore scope ambient mode to *everything* under it and bind it to a
// generic "Project: <dirname>" — exactly what happens when someone launches
// their agent from the wrong directory by accident. Refuse loudly; --force is
// the escape hatch for the rare case someone really means it.
function assertInitableDir(cwd, force) {
  if (force) return;
  const resolved = path.resolve(cwd);
  const home = path.resolve(homedir());
  const isFsRoot = resolved === path.parse(resolved).root;
  if (resolved === home || isFsRoot) {
    const where = resolved === home ? "your home directory" : "a filesystem root";
    throw new Error(
      `Refusing to run \`atlas init\` in ${where} (${resolved}). atlas.json activates ambient ` +
        `Atlas behavior for every session at or below this directory, so this would scope it to ` +
        `everything under ${resolved} and bind it to a generic "Project: ${path.basename(resolved) || resolved}". ` +
        `cd into your research repo and re-run, or pass --path <dir>. Use --force only if you truly mean to.`,
    );
  }
}

async function runAtlasInit(args, config, runtime) {
  const cwd = args.path ? path.resolve(String(args.path)) : process.cwd();
  // `--force` is a boolean GLOBAL, so it lands in `runtime`, not `args`.
  const force = runtime?.force === true || args.force === true || args.allow_home === true;
  assertInitableDir(cwd, force);
  const project = await runProjectCreate({ ...args, path: cwd }, config);
  const auto = {
    enabled: args.no_ambient === true ? false : true,
    log: args.no_log === true ? false : true,
    web: args.web_mode || (args.no_web === true ? "native" : "prefer_atlas"),
    capture: args.capture_mode || "suggest",
  };
  const runCommand =
    typeof args.run_command === "string" && args.run_command.trim()
      ? args.run_command.trim()
      : await detectRunCommand(cwd);
  const extra = {
    project_id: project.project_id,
    auto,
    privacy: args.privacy || "private",
  };
  if (runCommand) extra.run_command = runCommand;
  const written = await writeProjectConfig(cwd, extra);
  return {
    initialized: true,
    path: written.path,
    project,
    project_id: project.project_id,
    auto,
    run_command: runCommand || null,
  };
}

// `atlas leaderboard` — rank the runs under a project by one metric.
// A preset over GET /runs:compare: sorts by the metric dot-path in the
// metric's "better" direction, marks the best row, and keeps the column
// set tight so the table reads like a leaderboard instead of a dump.
async function runLeaderboard(args, config) {
  const baseUrl = config.baseUrl || config.base_url;
  const apiKey = config.apiKey || config.api_key;
  if (!baseUrl) throw new Error("no base_url configured for the active profile");
  if (!apiKey) throw new Error("no api_key configured for the active profile");
  const root = args.root || args.project_id;
  if (!root) throw new Error("--project is required — try `atlas project:list` to find one");
  const metric = String(args.metric || "").trim();
  if (!metric) throw new Error('--metric is required (a dot-path like "metrics.val_loss")');
  const direction = String(args.direction || "min").toLowerCase();
  if (!["min", "max"].includes(direction)) {
    throw new Error("--direction must be min (lower is better) or max (higher is better)");
  }
  const columns = args.columns
    ? String(args.columns)
    : `title,${metric},outcome,run_cluster_key,created_at`;
  const query = new URLSearchParams({
    root,
    columns,
    sort: metric,
    direction: direction === "min" ? "asc" : "desc",
    best: "true",
  });
  if (args.cluster) query.set("cluster", String(args.cluster));
  if (args.outcome) query.set("outcome", String(args.outcome));
  if (args.format_table) query.set("format", "table");
  const result = await fetchJson(baseUrl, `/runs:compare?${query.toString()}`, { apiKey });
  return { ...result, metric, direction };
}

// `atlas reproduce` — assemble a reproducibility packet for a run/result
// node: the exact config, the captured code state (repo/branch/commit and
// pin), the success criterion it was tested against, and what's missing.
// Packaging only — execution is a future compute concern; the packet is
// the contract that layer will consume.
async function runReproduce(args, config) {
  const baseUrl = config.baseUrl || config.base_url;
  const apiKey = config.apiKey || config.api_key;
  if (!baseUrl) throw new Error("no base_url configured for the active profile");
  if (!apiKey) throw new Error("no api_key configured for the active profile");
  const nodeId = args.node_id;
  if (!nodeId) throw new Error("--node is required — the run/result node to reproduce");

  const node = await fetchJson(baseUrl, `/nodes/${encodeURIComponent(nodeId)}`, { apiKey });
  const parseMaybeJson = (value) => {
    if (value == null) return null;
    if (typeof value === "object") return value;
    try {
      return JSON.parse(String(value));
    } catch {
      return null;
    }
  };
  const runData = parseMaybeJson(node.run_data) || {};
  const semantics = parseMaybeJson(node.semantic_data) || {};
  const semanticCodeState = semantics.code_state && typeof semantics.code_state === "object" && !Array.isArray(semantics.code_state)
    ? semantics.code_state
    : {};

  // Walk direct parents for the experiment plan (success criterion,
  // planned config) and the project root.
  let plan = null;
  let projectId = null;
  try {
    const parents = await fetchJson(baseUrl, `/nodes/${encodeURIComponent(nodeId)}/parents`, { apiKey });
    const parentList = Array.isArray(parents?.parents) ? parents.parents : Array.isArray(parents) ? parents : [];
    for (const parent of parentList) {
      const parentSemantics = parseMaybeJson(parent.semantic_data) || {};
      if (parentSemantics.type === "experiment_plan" && !plan) {
        plan = { node_id: parent.node_id, title: parent.title, ...parentSemantics };
      } else if (!projectId) {
        projectId = parent.node_id;
      }
    }
  } catch {
    // Parents are enrichment; the packet still works without them.
  }

  // Code state: prefer fields captured on the node itself (repo:capture),
  // fall back to the program root snapshot.
  let codeState = {
    repo_url: node.repo_url || semanticCodeState.repo_url || null,
    branch_name: node.branch_name || semanticCodeState.branch_name || null,
    head_commit_sha: node.head_commit_sha || semanticCodeState.head_commit_sha || semanticCodeState.pinned_sha || null,
    pinned_tag: semanticCodeState.pinned_tag || node.pinned_tag || null,
    pinned_ref: semanticCodeState.pinned_ref || null,
    pinned_sha: semanticCodeState.pinned_sha || null,
  };
  if (!codeState.repo_url || !codeState.head_commit_sha) {
    try {
      const snapshot = await fetchJson(baseUrl, `/nodes/${encodeURIComponent(nodeId)}/campaign/snapshot`, { apiKey });
      const rootInfo = snapshot?.program_root || snapshot?.root || snapshot || {};
      codeState = {
        repo_url: codeState.repo_url || rootInfo.repo_url || null,
        branch_name: codeState.branch_name || rootInfo.branch_name || null,
        head_commit_sha: codeState.head_commit_sha || rootInfo.head_commit_sha || null,
        pinned_tag: codeState.pinned_tag || rootInfo.pinned_tag || null,
        pinned_ref: codeState.pinned_ref || rootInfo.pinned_ref || null,
        pinned_sha: codeState.pinned_sha || rootInfo.pinned_sha || null,
      };
    } catch {
      // Snapshot is a fallback only.
    }
  }

  let reachability = null;
  if (codeState.repo_url && codeState.head_commit_sha) {
    try {
      const query = new URLSearchParams({ sha: codeState.head_commit_sha });
      if (codeState.pinned_tag) query.set("tag", codeState.pinned_tag);
      reachability = await fetchJson(
        baseUrl,
        `/repos/${encodeURIComponent(nodeId)}/verify?${query.toString()}`,
        { apiKey },
      );
    } catch (err) {
      reachability = { reachable: false, error: err && err.message ? err.message : String(err) };
    }
  }

  const config_ = runData.config || (plan && plan.config) || null;
  const criterion = (plan && plan.success_criterion) || null;
  const missing = [];
  if (!config_) missing.push("config (record runs with --config-json, or plan with experiment:plan --config)");
  if (!codeState.repo_url || !codeState.head_commit_sha) {
    missing.push("code state (record runs from inside the git repo, or run `atlas repo:capture --node <id>`)");
  }
  if (runData.git_dirty === true) {
    missing.push("clean working tree (the run was recorded with uncommitted changes — the captured sha understates what actually ran)");
  }
  if (codeState.repo_url && codeState.head_commit_sha && reachability && reachability.reachable === false) {
    missing.push("reachable code state (commit/tag was not confirmed on the remote; push and pin it with `atlas repo:capture --node <id> --pin true`)");
  }
  if (!criterion) missing.push("success criterion (declare it with experiment:plan --success-criterion)");

  const steps = [];
  if (codeState.repo_url) steps.push(`git clone ${codeState.repo_url}`);
  if (codeState.head_commit_sha) steps.push(`git checkout ${codeState.pinned_tag || codeState.head_commit_sha}`);
  if (config_) steps.push("re-run the experiment with the config below");
  if (criterion) steps.push(`verify against the success criterion: ${criterion}`);

  const packet = {
    node: {
      node_id: node.node_id,
      slug_name: node.slug_name || null,
      title: node.title,
      outcome: node.outcome || null,
      created_at: node.created_at,
    },
    project_id: projectId,
    plan: plan ? { node_id: plan.node_id, title: plan.title || null } : null,
    config: config_,
    metrics_observed: runData.metrics || null,
    success_criterion: criterion,
    criterion_met: semantics.criterion_met ?? null,
    code_state: codeState,
    code_reachability: reachability,
    dataset_ref: (plan && plan.dataset_ref) || semantics.dataset_ref || null,
    steps,
    complete: missing.length === 0,
    missing,
  };
  if (args.check && missing.length) {
    throw new Error(`reproduce packet is incomplete:\n  - ${missing.join("\n  - ")}`);
  }
  return packet;
}

async function runAtlasFork(args, config) {
  const baseUrl = config.baseUrl || config.base_url;
  const apiKey = config.apiKey || config.api_key;
  if (!baseUrl) throw new Error("no base_url configured for the active profile");
  if (!apiKey) throw new Error("no api_key configured for the active profile");
  const nodeId = args.node_id;
  if (!nodeId) throw new Error("--node is required — the node/subtree to fork");

  const exported = await fetchJson(baseUrl, "/export", {
    method: "POST",
    apiKey,
    body: {
      node_ids: [nodeId],
      include_descendants: args.include_descendants !== false,
      max_nodes: args.max_nodes === undefined ? undefined : Number(args.max_nodes),
    },
  });
  const nodes = Array.isArray(exported.nodes) ? exported.nodes : [];
  const root = nodes.find((n) => n.node_id === nodeId) || nodes[0];
  if (root) {
    const parseMaybeJson = (value) => {
      if (!value) return {};
      if (typeof value === "object") return value;
      try {
        return JSON.parse(String(value));
      } catch {
        return {};
      }
    };
    const semantics = parseMaybeJson(root.semantic_data);
    semantics.forked_from = {
      node_id: nodeId,
      title: root.title || null,
      repo_url: root.repo_url || null,
      head_commit_sha: root.head_commit_sha || null,
      forked_at: new Date().toISOString(),
    };
    root.semantic_data = JSON.stringify(semantics);
    root.title = args.title || `Fork: ${root.title || nodeId}`;
  }
  const imported = await fetchJson(baseUrl, "/import", {
    method: "POST",
    apiKey,
    body: { payload: { ...exported, nodes } },
  });
  return {
    forked: true,
    source_node_id: nodeId,
    imported_count: imported.imported_count,
    id_mapping: imported.id_mapping,
    new_node_id: imported.id_mapping?.[nodeId] || null,
  };
}

// `atlas project:merge` — collapse duplicate project roots into a canonical
// one. Slugs in --canonical / --absorb are resolved client-side here so the
// backend route stays UUID-typed.
async function runProjectsMerge(args, config) {
  const baseUrl = config.baseUrl || config.base_url;
  const apiKey = config.apiKey || config.api_key;
  if (!baseUrl) throw new Error("no base_url configured for the active profile");
  if (!apiKey) throw new Error("no api_key configured for the active profile");
  const absorbList = splitCommaList(args.absorb);
  if (!absorbList.length) throw new Error("--absorb requires at least one id/slug");

  async function resolveOne(value) {
    const v = String(value || "").trim();
    if (!v) return v;
    // Already a UUID? short-circuit.
    if (/^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/.test(v)) return v;
    const resolved = await fetchJson(
      baseUrl,
      `/nodes/resolve-by-slug?slug_name=${encodeURIComponent(v)}`,
      { apiKey },
    );
    if (!resolved?.node_id) throw new Error(`could not resolve slug \`${v}\``);
    return resolved.node_id;
  }

  const canonicalId = await resolveOne(args.canonical);
  const duplicateIds = [];
  for (const v of absorbList) duplicateIds.push(await resolveOne(v));

  const response = await fetch(`${baseUrl.replace(/\/$/, "")}/projects/merge`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({ canonical_id: canonicalId, duplicate_ids: duplicateIds }),
    signal: AbortSignal.timeout(30_000),
  });
  const text = await response.text();
  if (!response.ok) {
    throw new Error(`projects:merge failed (HTTP ${response.status}): ${text.slice(0, 400)}`);
  }
  return text ? JSON.parse(text) : {};
}

// `atlas nodes:share` — ergonomic wrapper over PUT /nodes/{id}/access-policy.
// Sets ``sharing_mode`` and returns the canonical web URL alongside the
// service response so scripts can ``echo`` the URL directly. Slugs in
// ``--node`` are resolved by dispatch before this runs.
async function runNodesShare(args, config) {
  const baseUrl = config.baseUrl || config.base_url;
  const apiKey = config.apiKey || config.api_key;
  if (!baseUrl) throw new Error("no base_url configured for the active profile");
  if (!apiKey) throw new Error("no api_key configured for the active profile");
  const visibility = String(args.visibility || "").toLowerCase();
  if (!["private", "unlisted", "public"].includes(visibility)) {
    throw new Error("--visibility must be one of: private, unlisted, public");
  }
  const result = await fetchJson(
    baseUrl,
    `/nodes/${encodeURIComponent(args.node_id)}/access-policy`,
    { method: "PUT", body: { sharing_mode: visibility }, apiKey },
  );
  // The web URL doesn't live on the response so derive it from baseUrl. The
  // CLI's default base is ``https://app.syntheticsciences.ai/api/v1`` so
  // stripping ``/api/v1`` gives the dashboard origin.
  const origin = baseUrl.replace(/\/api\/v1\/?$/, "");
  const url = `${origin}/nodes/${args.node_id}`;
  return {
    node_id: args.node_id,
    sharing_mode: visibility,
    url,
    raw: result,
  };
}

// `atlas runs:spool:list` — inspect what's queued in ``~/.atlas/spool/``.
// Returns enough metadata for the user to see scope and age without dumping
// the full bodies (those land in the JSON view).
async function runSpoolList() {
  const files = await listSpool();
  const entries = [];
  for (const file of files) {
    try {
      const [raw, st] = await Promise.all([fsReadFile(file, "utf8"), fsStat(file)]);
      const record = JSON.parse(raw);
      entries.push({
        file,
        route: record.route,
        spooled_at: record.spooled_at,
        size_bytes: st.size,
        title: record.body?.title || null,
        project_id: record.body?.project_id || null,
      });
    } catch (err) {
      entries.push({ file, error: err?.message || String(err) });
    }
  }
  return { spool_dir: SPOOL_DIR, count: entries.length, entries };
}

// `atlas runs:spool:flush` — replay every queued entry. Identical to the
// best-effort flush runs:record does on the side, just callable as a
// dedicated lever (and uses the same backend posts so stale ``/api/v1/...``
// routes are migrated by flushSpool itself).
async function runSpoolFlush(_args, config) {
  const baseUrl = config.baseUrl || config.base_url;
  const apiKey = config.apiKey || config.api_key;
  if (!baseUrl) throw new Error("no base_url configured for the active profile");
  if (!apiKey) throw new Error("no api_key configured for the active profile");
  const summary = await flushSpool(async (route, body) => {
    await fetchJson(baseUrl, route, { method: "POST", body, apiKey });
  });
  return { spool_dir: SPOOL_DIR, ...summary };
}

// `atlas runs:spool:clear` — discard every queued entry without posting.
// Destructive; the command spec requires --yes.
async function runSpoolClear() {
  const files = await listSpool();
  let deleted = 0;
  const errors = [];
  for (const file of files) {
    try {
      await fsUnlink(file);
      deleted += 1;
    } catch (err) {
      errors.push({ file, error: err?.message || String(err) });
    }
  }
  return { spool_dir: SPOOL_DIR, deleted, errors };
}

// ---------------------------------------------------------------------------
// optimize / chart commands
// ---------------------------------------------------------------------------

function parseSemanticData(node) {
  const raw = node?.semantic_data;
  if (!raw) return {};
  if (typeof raw === "object") return raw;
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

// `run:chart` — turn the runs under a project into a vega-lite score
// progression (points by outcome + best-so-far step line) and attach it
// to the project node as a `vega` evidence artifact the web app renders.
async function runRunsChart(args, config) {
  const baseUrl = config.baseUrl || config.base_url;
  const apiKey = config.apiKey || config.api_key;
  if (!baseUrl) throw new Error("no base_url configured for the active profile");
  if (!apiKey) throw new Error("no api_key configured for the active profile");
  const projectId = args.project_id;
  const metric = args.metric;
  if (!metric) throw new Error("--metric is required (a dot-path like metrics.score)");

  const params = new URLSearchParams({
    root: projectId,
    columns: `title,outcome,created_at,${metric}`,
    sort: "created_at",
    direction: "asc",
  });
  if (args.cluster) params.set("cluster", args.cluster);
  const compare = await fetchJson(baseUrl, `/runs:compare?${params.toString()}`, { apiKey });
  const rows = Array.isArray(compare?.rows) ? compare.rows : [];
  const direction = args.direction === "min" ? "min" : "max";

  const values = [];
  let best = null;
  let idx = 0;
  for (const row of rows) {
    const raw = row?.[metric];
    const score = typeof raw === "number" ? raw : Number(raw);
    if (!Number.isFinite(score)) continue;
    idx += 1;
    if (best === null || (direction === "max" ? score > best : score < best)) best = score;
    values.push({
      idx,
      score,
      best_so_far: best,
      outcome: row.outcome || "inconclusive",
      title: row.title || row.node_id || `run ${idx}`,
      node_id: row.node_id,
    });
  }
  if (!values.length) {
    throw new Error(`no runs under ${projectId} carry a numeric ${metric}`);
  }

  const title = args.title || "score progression";
  const spec = {
    $schema: "https://vega.github.io/schema/vega-lite/v5.json",
    title: { text: title, anchor: "start", fontSize: 13 },
    width: 560,
    height: 280,
    background: null,
    data: { values },
    layer: [
      {
        mark: { type: "line", interpolate: "step-after", color: "#10b981", strokeWidth: 1.6, opacity: 0.85 },
        encoding: {
          x: { field: "idx", type: "quantitative", title: "candidate", axis: { tickMinStep: 1 } },
          y: { field: "best_so_far", type: "quantitative", title: metric },
        },
      },
      {
        mark: { type: "point", filled: true, size: 72, opacity: 0.95 },
        encoding: {
          x: { field: "idx", type: "quantitative" },
          y: { field: "score", type: "quantitative", title: metric },
          color: {
            field: "outcome",
            type: "nominal",
            scale: {
              domain: ["completed", "failed", "canceled", "inconclusive"],
              range: ["#10b981", "#ef4444", "#f59e0b", "#94a3b8"],
            },
          },
          tooltip: [
            { field: "title", type: "nominal" },
            { field: "score", type: "quantitative" },
            { field: "outcome", type: "nominal" },
          ],
        },
      },
    ],
  };

  const outPath = args.out
    ? path.resolve(process.cwd(), args.out)
    : path.join(await mkdtemp(path.join(tmpdir(), "atlas-chart-")), "score-progression.json");
  await writeFile(outPath, JSON.stringify(spec, null, 2), "utf8");

  const result = {
    spec_path: outPath,
    runs_charted: values.length,
    best: { score: best, direction },
  };
  if (args.no_attach === true) return result;

  // Attach via the same prepare → signed PUT → finalize flow as evidence:add.
  const node = await fetchJson(baseUrl, `/nodes/${encodeURIComponent(projectId)}`, { apiKey });
  const revision = node?.revision ?? node?.node?.revision;
  if (revision === undefined || revision === null) {
    throw new Error("could not read the project node's revision for the artifact attach");
  }
  const bytes = await readFile(outPath);
  const prepared = await fetchJson(baseUrl, `/nodes/${encodeURIComponent(projectId)}/artifacts/uploads/prepare`, {
    method: "POST",
    apiKey,
    body: {
      expected_revision: revision,
      items: [{ artifact_type: "vega", filename: "score-progression.json", media_type: "application/json", title }],
    },
  });
  const batch = prepared?.batch || prepared;
  const item = Array.isArray(batch?.items) ? batch.items[0] : null;
  if (!batch?.batch_token || !item?.upload_url) {
    throw new Error("prepare response did not include the expected upload batch envelope");
  }
  const uploadUrl = new URL(item.upload_url, `${baseUrl.replace(/\/+$/, "")}/`).toString();
  const put = await fetch(uploadUrl, {
    method: item.method || "PUT",
    headers: item.headers || { "Content-Type": "application/json" },
    body: bytes,
    signal: AbortSignal.timeout(60_000),
  });
  if (!put.ok) throw new Error(`chart upload failed: HTTP ${put.status}`);
  const finalized = await fetchJson(baseUrl, `/nodes/${encodeURIComponent(projectId)}/artifacts/uploads/finalize`, {
    method: "POST",
    apiKey,
    body: { batch_token: batch.batch_token },
  });
  return { ...result, attached: true, finalize: finalized };
}

// Engine callbacks (exact candidate lineage) and parallel proposal pipelines
// landed in gepa after the 0.1.1 PyPI release; --parallel > 1 pins this exact
// build for reproducible campaign runs. Serial runs use PyPI gepa, where the
// harness's evaluator-driven compat mode records candidates instead.
const GEPA_PYPI_SPEC = "gepa>=0.1.1";
const GEPA_PARALLEL_SPEC = "gepa @ git+https://github.com/gepa-ai/gepa.git@d750388c99a455f48aa3f3fcf4a6a28650f6dc38";

async function requireUv() {
  const uvOk = await new Promise((resolve) => {
    execFile("uv", ["--version"], { timeout: 5_000 }, (error) => resolve(!error));
  });
  if (!uvOk) {
    throw new Error("`uv` is required to run the optimize harness — install from https://docs.astral.sh/uv/ and retry");
  }
}

async function harnessPath(file) {
  const harness = path.join(PACKAGE_ROOT, "src", "atlas-runtime", "optimize-harness", file);
  const harnessStat = await fsStat(harness).catch(() => null);
  if (!harnessStat) throw new Error(`bundled harness not found at ${harness}`);
  return harness;
}

async function harnessEnv(config) {
  const env = { ...process.env };
  if (!env.ATLAS_API_KEY && (config.apiKey || config.api_key)) env.ATLAS_API_KEY = config.apiKey || config.api_key;
  // Pin the harness's persistence calls to THIS install, not whatever
  // (possibly years-old) `atlas` happens to be first on PATH.
  if (!env.ATLAS_CLI) {
    const bin = path.join(PACKAGE_ROOT, "bin", "atlas.mjs");
    if (await fsStat(bin).catch(() => null)) env.ATLAS_CLI = `${process.execPath} ${bin}`;
  }
  return env;
}

// Validate --metric explicitly so a typo (e.g. `--metric maxx`) fails loudly
// instead of silently coercing to "max". Returns the normalized direction.
function normalizeMetricDirection(metric) {
  const direction = String(metric ?? "max").toLowerCase();
  if (direction !== "min" && direction !== "max") {
    throw new Error("--metric must be min or max");
  }
  return direction;
}

// `optimize:start` — spawn the bundled GEPA harness (Python, via uv) with
// the run contract. The harness owns worktrees/benchmark/gates and streams
// every candidate into the map; this wrapper just makes it one command.
async function runOptimizeStart(args, config) {
  const harness = await harnessPath("optimize.py");
  await requireUv();

  const parallel = Math.max(1, Number(args.parallel ?? 1) || 1);
  const gepaSpec = parallel > 1 ? GEPA_PARALLEL_SPEC : GEPA_PYPI_SPEC;
  // An explicit run_dir lets the wrapper read the harness's machine-readable
  // result contract (control + winner node ids) back without scraping stdout —
  // `atlas autoresearch` needs it to referee the winner after search.
  const runDir = args.run_dir
    ? path.resolve(String(args.run_dir))
    : path.join(process.cwd(), ".atlas-optimize", `run-${Date.now()}`);
  // litellm is an optional extra of gepa but required by its reflection path;
  // cloudpickle is gepa's preferred state serializer.
  const argv = ["run", "--with", gepaSpec, "--with", "litellm", "--with", "cloudpickle", "python", harness,
    "--target", String(args.target),
    "--benchmark", String(args.benchmark),
    "--metric", normalizeMetricDirection(args.metric),
    "--objective", String(args.objective),
    "--max-metric-calls", String(args.max_metric_calls ?? 50),
    "--stall", String(args.stall ?? 5),
    "--parallel", String(parallel),
    "--run-dir", runDir,
  ];
  if (args.max_seconds !== undefined && Number(args.max_seconds) > 0) argv.push("--max-seconds", String(args.max_seconds));
  if (args.search_seeds !== undefined) argv.push("--search-seeds", String(args.search_seeds));
  if (args.search_aggregation) argv.push("--search-aggregation", String(args.search_aggregation));
  if (args.background) argv.push("--background", String(args.background));
  if (args.reflection_lm) argv.push("--reflection-lm", String(args.reflection_lm));
  if (args.label) argv.push("--run-label", String(args.label));
  if (args.project) argv.push("--project", String(args.project));
  if (args.resume) argv.push("--resume", String(args.resume));
  if (args.ground === true) argv.push("--ground");
  if (args.ground === false) argv.push("--no-ground");
  if (args.require_grounding === false) argv.push("--no-require-grounding");
  if (args.ground_every !== undefined) argv.push("--ground-every", String(args.ground_every));
  if (args.ground_max !== undefined) argv.push("--ground-max", String(args.ground_max));
  if (args.benchmark_timeout !== undefined) argv.push("--benchmark-timeout", String(args.benchmark_timeout));
  for (const gate of splitCommaList(args.gate) || []) argv.push("--gate", gate);

  const env = await harnessEnv(config);
  const exitCode = await new Promise((resolve, reject) => {
    const child = spawn("uv", argv, { stdio: "inherit", env });
    child.on("error", reject);
    child.on("close", (code) => resolve(code ?? 1));
  });
  // The harness writes optimize-result.json (control/winner node ids, stop
  // reason) into run_dir; surface it so callers don't scrape stdout.
  let result = null;
  try {
    result = JSON.parse(await readFile(path.join(runDir, "optimize-result.json"), "utf8"));
  } catch {
    // no contract file (older harness / crash before write) — exit_code only
  }
  return { exit_code: exitCode, harness, parallel, run_dir: runDir, ...(result || {}) };
}

// `optimize:verify` — the referee: replicate a recorded candidate N times at
// its exact commit and attach a referee-report node. Streams progress on
// stderr; the final JSON summary on stdout becomes the command result.
async function runOptimizeVerify(args, config) {
  const harness = await harnessPath("verify.py");
  await requireUv();

  const argv = ["run", "python", harness,
    "--node", String(args.node_id),
    "--benchmark", String(args.benchmark),
    "--metric", normalizeMetricDirection(args.metric),
    "--seeds", String(args.seeds ?? 10),
  ];
  if (args.threshold !== undefined) argv.push("--threshold", String(args.threshold));
  if (args.alpha !== undefined) argv.push("--alpha", String(args.alpha));
  if (args.cluster) argv.push("--cluster", String(args.cluster));
  if (args.project) argv.push("--project", String(args.project));
  if (args.target) argv.push("--target", String(args.target));
  if (args.benchmark_timeout !== undefined) argv.push("--benchmark-timeout", String(args.benchmark_timeout));
  for (const gate of splitCommaList(args.gate) || []) argv.push("--gate", gate);

  const env = await harnessEnv(config);
  const { exitCode, stdout } = await new Promise((resolve, reject) => {
    let out = "";
    const child = spawn("uv", argv, { stdio: ["ignore", "pipe", "inherit"], env });
    child.stdout.on("data", (chunk) => {
      out += chunk;
    });
    child.on("error", reject);
    child.on("close", (code) => resolve({ exitCode: code ?? 1, stdout: out }));
  });
  const lines = stdout.trim().split("\n").filter(Boolean);
  const last = lines[lines.length - 1];
  try {
    return JSON.parse(last);
  } catch {
    return { exit_code: exitCode, output: stdout.trim().slice(-2000) };
  }
}

// `optimize:status` — read the control node's optimize_run semantics.
async function runOptimizeStatus(args, config) {
  const baseUrl = config.baseUrl || config.base_url;
  const apiKey = config.apiKey || config.api_key;
  if (!baseUrl) throw new Error("no base_url configured for the active profile");
  if (!apiKey) throw new Error("no api_key configured for the active profile");
  const node = await fetchJson(baseUrl, `/nodes/${encodeURIComponent(args.node_id)}`, { apiKey });
  const semantics = parseSemanticData(node?.node || node);
  if (semantics.type !== "optimize_run") {
    throw new Error(`${args.node_id} is not an optimize control node (semantic type: ${semantics.type || "none"})`);
  }
  const { type, ...fields } = semantics;
  return { node_id: args.node_id, ...fields };
}

// `optimize:stop` — graceful stop for a loop started on this machine:
// GEPA's FileStopper watches <run_dir>/gepa.stop.
async function runOptimizeStop(args, config) {
  const status = await runOptimizeStatus(args, config);
  if (!status.run_dir) {
    throw new Error("control node has no run_dir recorded — the loop was not started via optimize:start on this machine");
  }
  const runDir = path.resolve(process.cwd(), status.run_dir);
  await mkdir(runDir, { recursive: true });
  const stopFile = path.join(runDir, "gepa.stop");
  await writeFile(stopFile, `requested ${new Date().toISOString()}\n`, "utf8");
  return { stop_file: stopFile, note: "GEPA exits at the next iteration boundary; the harness records the final state." };
}

// --------------------------------------------------------------------------- //
// `atlas autoresearch` — one-command refereed campaign over a forked repo.
//
// The user supplies only a repo and a plain-English --goal. This orchestrates
// the existing primitives so the rigor (pre-registration timestamp + N-seed
// referee) happens automatically instead of by hand:
//   researchify (detect artifact + generate benchmark/gate) -> measure baseline
//   -> pre-register hypothesis+plan BEFORE candidate #1 -> optimize:start (GEPA)
//   -> optimize:verify the winner AND the baseline -> report a verified delta.
// It is an orchestration layer over optimize:start/verify, not a new engine.
// --------------------------------------------------------------------------- //

const ARTIFACT_CANDIDATES = [
  "train.py", "speedrun.py", "main.py", "run.py", "solve.py", "agent.py",
  "solution.py", "model.py", "optimize.py", "policy.py", "pipeline.py",
];
const ARTIFACT_DIRS = ["", "src/", "scripts/"];

// Best-effort detection of the single file a search should mutate. Returns the
// plausible artifacts in priority order; [] when none is recognizable.
export async function detectArtifactCandidates(cwd) {
  const found = [];
  for (const rel of ARTIFACT_CANDIDATES) {
    for (const dir of ARTIFACT_DIRS) {
      const p = `${dir}${rel}`;
      // eslint-disable-next-line no-await-in-loop
      if (await readFile(path.join(cwd, p), "utf8").then(() => true).catch(() => false)) {
        found.push(p);
        break;
      }
    }
  }
  if (!found.length) {
    for (const p of ["prompt.txt", "prompts/prompt.txt", "system_prompt.txt", "prompt.md"]) {
      // eslint-disable-next-line no-await-in-loop
      if (await readFile(path.join(cwd, p), "utf8").then(() => true).catch(() => false)) {
        found.push(p);
        break;
      }
    }
  }
  return found;
}

function arLog(msg) {
  process.stderr.write(`${msg}\n`);
}

function nodeIdFrom(resp) {
  if (!resp || typeof resp !== "object") return null;
  return resp.node_id || resp.id || (resp.node && (resp.node.node_id || resp.node.id)) || null;
}

async function confirmStart(yes) {
  if (yes) return true;
  if (!process.stdin.isTTY) return false;
  const rl = readline.createInterface({ input: process.stdin, output: process.stderr });
  const answer = await new Promise((resolve) => rl.question("Proceed? [y/N] ", resolve));
  rl.close();
  return /^y(es)?$/i.test(String(answer).trim());
}

// Run a benchmark command once (baseline + contract validation). Mirrors the
// harness invocation: shell command with {target}/{worktree} substituted,
// ATLAS_OPTIMIZE_TARGET/RESULT exported, score read from the result file or stdout.
async function runBenchmarkOnce({ benchmark, targetAbs, cwd, timeoutMs }) {
  const dir = await mkdtemp(path.join(tmpdir(), "atlas-ar-"));
  const resultFile = path.join(dir, "result.json");
  const cmd = String(benchmark)
    .replace(/\{target\}/g, targetAbs)
    .replace(/\{worktree\}/g, cwd);
  const env = { ...process.env, ATLAS_OPTIMIZE_TARGET: targetAbs, ATLAS_OPTIMIZE_RESULT: resultFile };
  return await new Promise((resolve) => {
    const child = spawn(cmd, { shell: true, cwd, env });
    let out = "";
    let err = "";
    let timedOut = false;
    const timer = setTimeout(() => { timedOut = true; child.kill("SIGKILL"); }, Math.max(1000, timeoutMs));
    child.stdout?.on("data", (d) => { out += d; });
    child.stderr?.on("data", (d) => { err += d; });
    child.on("error", (e) => { clearTimeout(timer); resolve({ ok: false, error: e.message, stdout: out, stderr: err }); });
    child.on("close", async (code) => {
      clearTimeout(timer);
      let parsed = null;
      try {
        parsed = JSON.parse(await readFile(resultFile, "utf8"));
      } catch {
        try { parsed = JSON.parse(out.trim()); } catch { /* no contract JSON */ }
      }
      await rm(dir, { recursive: true, force: true }).catch(() => {});
      const score = parsed && typeof parsed.score === "number" ? parsed.score : null;
      resolve({ ok: code === 0 && score !== null && !timedOut, code, timedOut, score, stdout: out.slice(-4000), stderr: err.slice(-4000) });
    });
  });
}

async function postResearchNode(config, route, body) {
  const baseUrl = config.baseUrl || config.base_url;
  const apiKey = config.apiKey || config.api_key;
  const resp = await fetchJson(baseUrl, route, { method: "POST", body, apiKey });
  return nodeIdFrom(resp);
}

async function runAutoresearch(args, config) {
  const cwd = path.resolve(String(args.path || (Array.isArray(args._positional) && args._positional[0]) || process.cwd()));
  const goal = String(args.goal || "").trim();
  if (!goal) {
    throw new Error("--goal is required: one sentence describing what 'better' means (e.g. \"reduce val_bpb in a fixed budget\")");
  }

  const metric = args.metric ? normalizeMetricDirection(args.metric) : inferMetricDirection(goal);
  const metricInferred = !args.metric;
  const seeds = Math.max(2, Number(args.seeds ?? 10) || 10);
  const alpha = String(args.alpha ?? "0.05");
  const maxSeconds = args.budget ? parseDurationSeconds(args.budget) : 0;
  const maxMetricCalls = Number(args.max_metric_calls ?? (maxSeconds ? 10000 : 50));
  const benchmarkTimeout = Number(args.benchmark_timeout ?? 900);
  const dryRun = args.dry_run === true;
  const scaffoldOnly = args.scaffold_only === true;

  // 1. Researchify: resolve the artifact (the search always mutates one file,
  // whether or not a benchmark was supplied), then scaffold a benchmark when
  // one wasn't given.
  const generated = [];
  let target = args.target ? String(args.target) : null;
  let benchmark = args.benchmark ? String(args.benchmark) : null;
  const gates = splitCommaList(args.gate) || [];

  if (!target) {
    const candidates = await detectArtifactCandidates(cwd);
    if (candidates.length === 1) {
      target = candidates[0];
    } else if (candidates.length > 1) {
      [target] = candidates;
      arLog(`autoresearch: multiple candidate artifacts found; using ${target} (override with --target).`);
      arLog(`  candidates: ${candidates.join(", ")}`);
    } else {
      throw new Error(
        "autoresearch: could not detect the artifact to optimize. Pass --target <repo-relative file> " +
        "(the script/prompt/config the search should mutate).",
      );
    }
  }
  if (!(await readFile(path.join(cwd, target), "utf8").then(() => true).catch(() => false))) {
    throw new Error(`autoresearch: --target not found: ${target}`);
  }
  if (benchmark && benchmark.includes("{target}") === false) {
    arLog("autoresearch: note — your --benchmark has no {target} token; the candidate path won't be substituted into it.");
  }

  if (!benchmark) {
    const detectedRun = await detectRunCommand(cwd);
    const runCommand = resolveRunCommand({ detectedRunCommand: detectedRun, target });
    if (!runCommand) {
      throw new Error(
        `autoresearch: could not infer how to run ${target}. Add a run script (run.sh / speedrun.sh), ` +
        "or pass --benchmark \"<command emitting {\\\"score\\\":…}>\".",
      );
    }
    const metricToken = deriveMetricToken(goal);
    const atlasDir = path.join(cwd, ".atlas");
    await mkdir(atlasDir, { recursive: true });
    const benchPath = path.join(atlasDir, "benchmark.sh");
    const scorePath = path.join(atlasDir, "score.py");
    const gatePath = path.join(atlasDir, "gate.sh");
    await writeFile(benchPath, renderBenchmarkSh({ runCommand, target }), { mode: 0o755 });
    await writeFile(scorePath, renderScorePy({ metricToken, metric }), { mode: 0o755 });
    await writeFile(gatePath, renderGateSh(), { mode: 0o755 });
    generated.push(path.relative(cwd, benchPath), path.relative(cwd, scorePath), path.relative(cwd, gatePath));
    // Absolute paths so the scaffold works whether or not it is committed.
    benchmark = `bash ${JSON.stringify(benchPath)} {target}`;
    gates.unshift(`bash ${JSON.stringify(gatePath)} {worktree} {target}`);
    arLog(`autoresearch: generated ${generated.join(", ")}  (metric token: ${metricToken || "score — EDIT .atlas/score.py"})`);
  }

  if (scaffoldOnly) {
    return {
      scaffolded: true, target, benchmark, generated,
      next: "Review .atlas/benchmark.sh + .atlas/score.py, then re-run `atlas autoresearch` without --scaffold-only.",
    };
  }

  // 2. Build + show the plan.
  const git = await detectGitState(cwd);
  const budgetLabel = maxSeconds ? `${maxSeconds}s wall-clock` : `${maxMetricCalls} evaluations`;
  const plan = {
    repo: cwd,
    head: git?.head_commit_sha ? git.head_commit_sha.slice(0, 12) : "(no git)",
    dirty: git?.git_dirty ?? null,
    goal,
    metric: `${metric}${metricInferred ? " (inferred)" : ""}`,
    target, benchmark, gates,
    budget: budgetLabel,
    verify: `${seeds} seeds, alpha ${alpha}`,
  };
  arLog("");
  arLog("Atlas autoresearch — campaign plan");
  arLog(`  repo:       ${plan.repo}  (HEAD ${plan.head}${plan.dirty ? ", DIRTY" : ""})`);
  arLog(`  goal:       "${goal}"   → metric: ${plan.metric}`);
  arLog(`  target:     ${target}`);
  arLog(`  benchmark:  ${benchmark}`);
  arLog(`  gate(s):    ${gates.length ? gates.join(" ; ") : "(none)"}`);
  arLog(`  budget:     ${budgetLabel}   | verify: ${seeds} seeds, alpha ${alpha}`);
  arLog("  rigor:      pre-register hypothesis + plan BEFORE candidate #1; referee winner & baseline");
  arLog("");

  if (dryRun) {
    return { dry_run: true, plan, generated, note: "Re-run without --dry-run to measure the baseline and start the campaign." };
  }

  if (!(await confirmStart(args.yes === true))) {
    return { awaiting_confirmation: true, plan, generated, note: "Not confirmed. Re-run with --yes to start (or --dry-run to preview)." };
  }

  if (git && git.git_dirty) {
    const dirtyTarget = await new Promise((resolve) => {
      execFile("git", ["status", "--porcelain", "--", target], { cwd, timeout: 5000 }, (e, out) => resolve(!e && String(out || "").trim().length > 0));
    });
    if (dirtyTarget) {
      arLog(`autoresearch: WARNING — ${target} has uncommitted changes; the baseline is measured at HEAD. Commit ${target} for a clean before/after.`);
    }
  }

  await requireUv();

  // 3. Preflight: a reflection-LM key must exist, else search burns budget and
  // fails at the first proposal.
  const hasLmKey = Boolean(
    process.env.ANTHROPIC_API_KEY || process.env.OPENAI_API_KEY ||
    process.env.GEMINI_API_KEY || process.env.OPENROUTER_API_KEY || args.reflection_lm,
  );
  if (!hasLmKey) {
    throw new Error(
      "autoresearch: no reflection-LM key found. Set ANTHROPIC_API_KEY or OPENAI_API_KEY (GEPA's reflector needs one), " +
      "or pass --reflection-lm with a provider whose key is set.",
    );
  }

  // 4. Measure the baseline (validates the contract before any search budget).
  const targetAbs = path.join(cwd, target);
  arLog("autoresearch: measuring baseline on the seed artifact…");
  const baseline = await runBenchmarkOnce({ benchmark, targetAbs, cwd, timeoutMs: benchmarkTimeout * 1000 });
  if (!baseline.ok) {
    const hint = generated.length
      ? "The generated benchmark could not score the seed. Edit .atlas/score.py (METRIC=…) so it finds your metric, or pass --benchmark."
      : "Your --benchmark did not emit a valid {\"score\":…} contract on the seed.";
    return {
      ok: false, stage: "baseline", target, benchmark,
      exit_code: baseline.code, timed_out: baseline.timedOut || false,
      stderr_tail: baseline.stderr,
      error: `baseline run failed (${baseline.timedOut ? "timed out" : `exit ${baseline.code}`}). ${hint}`,
    };
  }
  const baselineScore = baseline.score;
  arLog(`autoresearch: baseline score = ${formatNumber(baselineScore)} (${metric})`);

  // 5. Resolve/create the project and PRE-REGISTER before any candidate.
  let projectId = args.project ? String(args.project) : null;
  if (!projectId) {
    const project = await runProjectCreate({ path: cwd }, config);
    projectId = project.project_id;
  }
  const successCriterion = buildSuccessCriterion({ metric, baseline: baselineScore, seeds, alpha });
  const planConfig = {
    autoresearch: true,
    budget: maxSeconds ? { wall_clock_seconds: maxSeconds } : { max_metric_calls: maxMetricCalls },
    tiers: { floor: baselineScore, target: metric === "min" ? baselineScore * 0.98 : baselineScore * 1.02 },
    hardware: process.platform,
    seed_artifact: target,
    benchmark, metric, baseline: baselineScore,
  };
  let hypothesisId = null;
  let planId = null;
  try {
    hypothesisId = await postResearchNode(config, "/hypotheses:add", {
      project_id: projectId,
      claim: goal,
      rationale: "Pre-registered by `atlas autoresearch` before the first candidate evaluation.",
      expected_observations: `verified mean improves over the baseline (${formatNumber(baselineScore)})`,
    });
    if (hypothesisId) {
      planId = await postResearchNode(config, "/experiments:plan", {
        project_id: projectId,
        hypothesis_id: hypothesisId,
        title: `autoresearch: ${goal}`.slice(0, 200),
        metric: "metrics.score",
        success_criterion: successCriterion,
        config: JSON.stringify(planConfig),
        expected_result: `verified mean beats baseline ${formatNumber(baselineScore)} (${metric}) at alpha ${alpha}`,
      });
    }
    arLog(`autoresearch: pre-registered hypothesis ${hypothesisId || "?"} + plan ${planId || "?"} (timestamp precedes candidate #1)`);
  } catch (e) {
    arLog(`autoresearch: WARNING — pre-registration failed (${e && e.message}); continuing without a bound plan.`);
  }

  // 6. Search.
  arLog("autoresearch: starting GEPA search…");
  const startResult = await runOptimizeStart({
    target, benchmark, metric, objective: goal,
    max_metric_calls: maxMetricCalls, max_seconds: maxSeconds || undefined,
    stall: args.stall, parallel: args.parallel,
    search_seeds: args.search_seeds, search_aggregation: args.search_aggregation,
    reflection_lm: args.reflection_lm, gate: gates, ground: args.ground,
    project: projectId, resume: args.resume,
    label: `autoresearch: ${goal}`.slice(0, 120),
    benchmark_timeout: benchmarkTimeout,
  }, config);

  const control = startResult.control_node_id || null;
  if (!control) {
    return { ok: false, stage: "search", exit_code: startResult.exit_code, project_id: projectId, error: "search finished but no control node was reported — see the optimizer output above." };
  }

  // 7. Referee BOTH the baseline (at HEAD) and the winner on the same protocol,
  // so the headline is a verified before→after delta.
  let baselineReport = null;
  let baselineNode = null;
  if (git?.head_commit_sha) {
    try {
      const baselineRec = await runRunsRecord({
        no_eval: true,
        payload_json: JSON.stringify({
          project_id: control,
          title: `baseline (seed @ ${git.head_commit_sha.slice(0, 12)})`,
          outcome: "success",
          metrics: { score: baselineScore },
          config: { baseline: true, target },
        }),
      }, config);
      baselineNode = nodeIdFrom(baselineRec);
    } catch (e) {
      arLog(`autoresearch: WARNING — could not record the baseline node (${e && e.message}).`);
    }
  }
  if (baselineNode) {
    arLog("autoresearch: refereeing the baseline…");
    baselineReport = await runOptimizeVerify({
      node_id: baselineNode, benchmark, metric, seeds, target, gate: gates,
      project: control, cluster: "verify/baseline", benchmark_timeout: benchmarkTimeout,
    }, config).catch((e) => ({ error: e && e.message }));
  }

  arLog("autoresearch: refereeing the winner…");
  const winnerReport = await runOptimizeVerify({
    node_id: control, benchmark, metric, seeds,
    threshold: baselineScore, alpha, target, gate: gates,
    project: control, cluster: "verify/winner", benchmark_timeout: benchmarkTimeout,
  }, config).catch((e) => ({ error: e && e.message }));

  // 8. Report + close.
  const winnerMean = typeof winnerReport?.mean === "number" ? winnerReport.mean : null;
  const baselineMean = typeof baselineReport?.mean === "number" ? baselineReport.mean : baselineScore;
  const verified = winnerReport?.verified === true;
  const delta = winnerMean !== null ? winnerMean - baselineMean : null;
  const verdict = verified
    ? `VERIFIED: ${formatNumber(baselineMean)} → ${formatNumber(winnerMean)} (Δ ${delta >= 0 ? "+" : ""}${formatNumber(delta)}, p<${alpha}, n=${seeds}, ${metric})`
    : winnerMean !== null
      ? `not verified: best verified mean ${formatNumber(winnerMean)} vs baseline ${formatNumber(baselineMean)} (n=${seeds}, ${metric})`
      : "not verified: winner replication failed";

  try {
    const basis = [winnerReport?.report_node, baselineReport?.report_node].filter(Boolean);
    await postResearchNode(config, "/decisions:add", {
      project_id: projectId, decision: verdict,
      basis: basis.join(",") || undefined, confidence: verified ? "high" : "medium",
    });
    if (hypothesisId) {
      await fetchJson(config.baseUrl || config.base_url, "/hypotheses:update", {
        method: "POST", apiKey: config.apiKey || config.api_key,
        body: { node_id: hypothesisId, status: verified ? "supported" : "weakened", because: basis.join(",") || undefined },
      }).catch(() => {});
    }
  } catch (e) {
    arLog(`autoresearch: WARNING — could not write the closing decision (${e && e.message}).`);
  }

  const appUrl = (config.baseUrl || config.base_url || "").replace(/\/api(\/v1)?\/?$/, "");
  arLog("");
  arLog(verdict);
  arLog(`  control node: ${control}`);
  arLog(`  inspect:      atlas optimize:status --node ${control}  ·  atlas map:tree --node ${control}`);
  if (appUrl) arLog(`  map:          ${appUrl}/nodes/${control}`);
  arLog("");

  return {
    ok: true, verified, verdict, metric,
    baseline_mean: baselineMean, winner_mean: winnerMean, delta, seeds, alpha,
    project_id: projectId, control_node_id: control,
    hypothesis_id: hypothesisId, plan_id: planId,
    winner_report_node: winnerReport?.report_node || null,
    baseline_report_node: baselineReport?.report_node || null,
    stop_reason: startResult.stop_reason, candidates_evaluated: startResult.candidates_recorded,
    generated, map: appUrl ? `${appUrl}/nodes/${control}` : null,
  };
}

export async function runLocalCommand(command, args, config, runtime) {
  switch (command.name) {
    case "login":
      return await runLogin(args, config, runtime);
    case "logout":
      return await runLogout(config);
    case "doctor":
      return await runDoctor(config);
    case "config:list":
      return await listProfileConfigs();
    case "config:show":
      return await showProfileConfig(args.name || config.profile);
    case "config:set":
      return await runProfileSet(args, config);
    case "config:unset":
      return await unsetProfileConfig(profileName(args, config));
    case "secret:set":
      return await runKeychainSet(args, config);
    case "secret:clear":
      return await runKeychainClear(args, config);
    case "init":
      return await runAtlasInit(args, config, runtime);
    case "log:append":
      return await runLogAppend(args, config);
    case "run:record":
      return await runRunsRecord(args, config);
    case "run:chart":
      return await runRunsChart(args, config);
    case "optimize:start":
      return await runOptimizeStart(args, config);
    case "optimize:status":
      return await runOptimizeStatus(args, config);
    case "optimize:stop":
      return await runOptimizeStop(args, config);
    case "optimize:verify":
      return await runOptimizeVerify(args, config);
    case "autoresearch":
      return await runAutoresearch(args, config);
    case "note:add":
      return await runNoteAdd(args, config);
    case "notebook:cell":
      return await runNotebookCell(args, config);
    case "project:list":
      return await runProjectList(args, config);
    case "project:create":
      return await runProjectCreate(args, config);
    case "leaderboard":
      return await runLeaderboard(args, config);
    case "reproduce":
      return await runReproduce(args, config);
    case "fork":
      return await runAtlasFork(args, config);
    case "node:share":
      return await runNodesShare(args, config);
    case "project:merge":
      return await runProjectsMerge(args, config);
    case "run:spool:list":
      return await runSpoolList();
    case "run:spool:flush":
      return await runSpoolFlush(args, config);
    case "run:spool:clear":
      return await runSpoolClear();
    default:
      throw new Error(`unknown local command: ${command.name}`);
  }
}
