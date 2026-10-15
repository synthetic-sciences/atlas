import { describe, it } from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import http from "node:http";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { mkdirSync, mkdtempSync, readFileSync, readdirSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { getCommand } from "../src/atlas-runtime/commands.mjs";
import { runCommand } from "../src/atlas-runtime/handlers.mjs";
import { AtlasHttpClient } from "../src/atlas-runtime/http-client.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const CLI_ROOT = path.resolve(__dirname, "..");
const BIN = path.join(CLI_ROOT, "bin", "atlas.mjs");

const CORE_COMMANDS = [
  "login",
  "logout",
  "whoami",
  "doctor",
  "init",
  "secret:clear",
  "secret:set",
  "config:list",
  "config:set",
  "config:show",
  "config:unset",
  "account:update",
  "ops:maps:export",
  "ops:maps:export-stream",
  "ops:maps:list",
  "program:snapshot",
  "map:view",
  "link:add",
  "node:history",
  "node:branch",
  "link:children",
  "node:save",
  "node:create",
  "repo:pin",
  "repo:capture",
  "draft:create",
  "node:delete",
  "node:delete-bulk",
  "node:files",
  "node:show",
  "node:list",
  "node:merge",
  "link:parents",
  "link:remove",
  "map:lineage",
  "map:summary",
  "map:tree",
  "node:resolve",
  "access:show",
  "access:set",
  "access:set-bulk",
  "access:summaries",
  "draft:derive-hypothesis",
  "draft:derive-insights",
  "draft:lock",
  "draft:renew",
  "draft:unlock",
  "evidence:refresh",
  "evidence:link",
  "label:assign",
  "label:create",
  "label:delete",
  "label:update",
  "evidence:delete",
  "evidence:delete-bulk",
  "evidence:show",
  "evidence:list",
  "evidence:note",
  "evidence:add",
  "evidence:finalize",
  "evidence:prepare",
  "evidence:download",
  "evidence:files",
  "run:record",
  "run:compare",
  "run:chart",
  "leaderboard",
  "optimize:start",
  "optimize:status",
  "optimize:stop",
  "optimize:verify",
  "optimize:progress",
  "autoresearch",
  "hypothesis:add",
  "hypothesis:update",
  "experiment:plan",
  "decision:add",
  "eval:define",
  "brief",
  "reproduce",
  "note:add",
  "notebook:cell",
  "log:append",
  "log:tail",
  "log:search",
  "fork",
  "history:export",
  "map:export",
  "map:summary:export",
  "map:summary:pdf",
  "map:summary:render-pdf",
  "map:summary:stream",
  "map:import",
  "github:disconnect",
  "github:set",
  "github:link",
  "github:reconnect",
  "github:refresh-repos",
  "github:status",
  "integration:huggingface:remove",
  "integration:huggingface:set",
  "integration:status",
  "integration:wandb:remove",
  "integration:wandb:set",
  "key:create",
  "key:delete",
  "key:list",
  "key:rotate",
  "web:search",
  "web:fetch",
  "node:share",
  "project:list",
  "project:create",
  "project:merge",
  "run:spool:clear",
  "run:spool:flush",
  "run:spool:list",
  "usage:summary",
  "explore",
  "researchers",
  "competitions",
  "competition",
].sort();

describe("Gateway direct HTTP runtime CLI", () => {
  it("prints package version", () => {
    const result = run(["--version"]);
    assert.equal(result.status, 0, result.stderr);
    assert.match(result.stdout, /^\d+\.\d+\.\d+/);
  });

  it("exposes the Gateway CLI, skills, auth, and research command surface", () => {
    const result = run(["help", "--format=json"]);
    assert.equal(result.status, 0, result.stderr);
    const payload = JSON.parse(result.stdout);
    assert.deepEqual(payload.commands.map((command) => command.name).sort(), CORE_COMMANDS);
    assert.equal(payload.commands.some((command) => command.name.startsWith("knowledge:")), false);
    assert.equal(payload.commands.some((command) => command.name.startsWith("hooks:")), false);
    assert.equal(payload.commands.some((command) => command.name.startsWith(`${"ni"}a:`)), false);
    assert.equal(payload.commands.some((command) => /mcp|tools\/call/i.test(command.path)), false);
    assert.equal(payload.commands.every((command) => command.endpoints?.every((endpoint) => /^[A-Z]+ \//.test(endpoint))), true);
  });

  it("exposes the optimize loop surface with the agreed schemas", () => {
    const chart = getCommand("run:chart");
    assert.ok(chart?.local, "run:chart should be a local command");
    assert.deepEqual(chart.schema.required, ["project_id"]);
    assert.ok(chart.schema.properties.metric);

    const record = getCommand("run:record");
    for (const field of ["parent_run_id", "candidate_idx", "scorecard_json"]) {
      assert.ok(record.schema.properties[field], `run:record schema missing ${field}`);
    }

    const start = getCommand("optimize:start");
    assert.ok(start?.local);
    assert.deepEqual(start.schema.required.sort(), ["benchmark", "objective", "target"]);
    assert.ok(start.schema.properties.parallel, "optimize:start schema missing parallel");
    for (const field of ["search_seeds", "search_aggregation", "require_grounding"]) {
      assert.ok(start.schema.properties[field], `optimize:start schema missing ${field}`);
    }

    const verify = getCommand("optimize:verify");
    assert.ok(verify?.local, "optimize:verify should be local");
    assert.deepEqual(verify.schema.required.sort(), ["benchmark", "node_id"]);
    for (const field of ["seeds", "threshold", "alpha", "gate", "cluster"]) {
      assert.ok(verify.schema.properties[field], `optimize:verify schema missing ${field}`);
    }

    const progress = getCommand("optimize:progress");
    assert.equal(progress.method, "POST");
    assert.equal(progress.path, "/optimize:progress");
    assert.ok(progress.bodyParams.includes("budget_used"));
    assert.ok(progress.bodyParams.includes("stop_reason"));

    for (const name of ["optimize:status", "optimize:stop"]) {
      const cmd = getCommand(name);
      assert.ok(cmd?.local, `${name} should be local`);
      assert.deepEqual(cmd.schema.required, ["node_id"]);
    }
  });

  it("exposes the autoresearch campaign surface", () => {
    const ar = getCommand("autoresearch");
    assert.ok(ar?.local, "autoresearch should be a local command");
    assert.equal(ar.group, "optimize");
    assert.deepEqual(ar.schema.required, ["goal"]);
    for (const field of ["path", "target", "benchmark", "metric", "budget", "seeds", "alpha", "ground", "resume", "scaffold_only", "dry_run", "yes"]) {
      assert.ok(ar.schema.properties[field], `autoresearch schema missing ${field}`);
    }
  });

  it("infers metric direction, metric token, and budget from a goal", async () => {
    const { inferMetricDirection, deriveMetricToken, parseDurationSeconds, buildSuccessCriterion } =
      await import("../src/atlas-runtime/autoresearch.mjs");
    assert.equal(inferMetricDirection("reduce val_bpb in a fixed budget"), "min");
    assert.equal(inferMetricDirection("make this kernel faster"), "min");
    assert.equal(inferMetricDirection("raise eval accuracy"), "max");
    assert.equal(inferMetricDirection("push the benchmark score"), "max");
    assert.equal(deriveMetricToken("reduce val_bpb"), "val_bpb");
    assert.equal(deriveMetricToken("improve F1 on the holdout"), "f1");
    assert.equal(parseDurationSeconds("8h"), 28800);
    assert.equal(parseDurationSeconds("30m"), 1800);
    assert.equal(parseDurationSeconds("90s"), 90);
    assert.throws(() => parseDurationSeconds("soon"), /budget must look like/);
    assert.match(buildSuccessCriterion({ metric: "min", baseline: 0.748, seeds: 10, alpha: "0.05" }), /verified mean < 0\.748 .* n >= 10/);
  });

  it("autoresearch --dry-run researchifies a fork without spending budget", () => {
    const repo = mkdtempSync(path.join(tmpdir(), "atlas-ar-"));
    const git = (gitArgs) => spawnSync("git", gitArgs, { cwd: repo, encoding: "utf8" });
    git(["init", "-q"]);
    git(["config", "user.email", "t@t.co"]);
    git(["config", "user.name", "t"]);
    writeFileSync(path.join(repo, "train.py"), 'print("epoch 1 val_loss: 2.10")\nprint("epoch 2 val_loss: 1.85")\n');
    writeFileSync(path.join(repo, "run.sh"), "#!/usr/bin/env bash\npython3 train.py\n");
    git(["add", "-A"]);
    git(["commit", "-qm", "init"]);

    const out = spawnSync(process.execPath, [BIN, "autoresearch", "--path", repo, "--goal", "reduce val_loss on the holdout", "--dry-run", "--format=json"], {
      cwd: repo, encoding: "utf8", env: { ...process.env, ATLAS_API_KEY: "test-token" },
    });
    assert.equal(out.status, 0, out.stderr);
    const result = JSON.parse(out.stdout);
    assert.equal(result.dry_run, true);
    assert.match(result.plan.metric, /^min/, "val_loss goal should infer min");
    assert.equal(result.plan.target, "train.py");
    assert.deepEqual(result.generated, [".atlas/benchmark.sh", ".atlas/score.py", ".atlas/gate.sh"]);

    // The generated benchmark must satisfy the contract on the seed.
    const bench = spawnSync("bash", [path.join(repo, ".atlas/benchmark.sh"), path.join(repo, "train.py")], {
      cwd: repo, encoding: "utf8",
      env: { ...process.env, ATLAS_OPTIMIZE_TARGET: path.join(repo, "train.py") },
    });
    assert.equal(bench.status, 0, bench.stderr);
    const contract = JSON.parse(bench.stdout);
    assert.equal(contract.score, 1.85, "score.py should read the final-epoch val_loss");
    assert.ok(Array.isArray(contract.examples) && contract.examples.length >= 1);
  });

  it("routes --parent-run and --project aliases for the optimize surface", () => {
    // run:record: --parent-run is sugar for --parent-run-id.
    const record = runEcho([
      "optimize:progress",
      "--node", "node-123",
      "--status", "running",
      "--budget-total", "50",
      "--format=json",
    ]);
    assert.equal(record.status, 0, record.stderr);
    const payload = JSON.parse(record.stdout);
    assert.equal(payload.request.body.node_id, "node-123");
    assert.equal(payload.request.body.status, "running");
    assert.equal(payload.request.body.budget_total, 50);
  });

  it("does not expose removed endpoint-shaped command names", () => {
    for (const oldName of [
      "nodes:commit-new",
      "artifacts:upload",
      "graph:get",
      "sources:create",
      "entry:create",
      "entry:save",
      "draft:claim",
      "draft:touch",
      "draft:release",
      "evidence:entry-files",
    ]) {
      const result = run([oldName, "--format=json"]);
      assert.notEqual(result.status, 0, `${oldName} unexpectedly succeeded`);
      assert.match(result.stderr, new RegExp(`unknown command: ${oldName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`));
    }
  });

  it("renders command schema through help", () => {
    const direct = run(["nodes:create", "--schema", "--format=json"]);
    assert.notEqual(direct.status, 0);
    assert.match(direct.stderr, /--schema is only valid/);

    const result = run(["help", "nodes:create", "--schema", "--format=json"]);
    assert.equal(result.status, 0, result.stderr);
    const payload = JSON.parse(result.stdout);
    // Invoked via the pre-0.8 alias; help resolves to the canonical name.
    assert.equal(payload.name, "node:create");
    assert.match(payload.schema, /payload_json/);

    const backfill = run(["help", "draft:derive-hypothesis", "--schema", "--format=json"]);
    assert.equal(backfill.status, 0, backfill.stderr);
    const backfillSchema = JSON.parse(backfill.stdout);
    assert.match(backfillSchema.schema, /expected_revision/);
    assert.match(backfillSchema.schema, /node_id/);
  });

  it("derives schemas for renamed commands without explicit overrides", () => {
    const result = run(["help", "keys:delete", "--format=json"]);
    assert.equal(result.status, 0, result.stderr);
    const payload = JSON.parse(result.stdout);
    assert.deepEqual(payload.required.map((field) => field.name), ["key_id"]);
    assert.match(payload.schema, /key_id/);
  });

  it("maps map:view to direct HTTP query shape", () => {
    const result = runEcho(["map:view", "--page-size", "100", "--cursor", "abc", "--filter", "include:tag:x", "--format=json"]);
    assert.equal(result.status, 0, result.stderr);
    assert.deepEqual(JSON.parse(result.stdout).request, {
      method: "GET",
      path: "/graph",
      query: { page_size: 100, cursor: "abc", filter: "include:tag:x" },
      body: null,
      raw: false,
      external: false,
    });
  });

  it("maps nodes:save payload_json to POST /nodes/{id}/commit", () => {
    const result = runEcho([
      "nodes:save",
      "--node-id",
      "node-1",
      "--payload-json",
      '{"staged_payload":{"title":"Committed"}}',
      "--format=json",
    ]);
    assert.equal(result.status, 0, result.stderr);
    const request = JSON.parse(result.stdout).request;
    assert.equal(request.method, "POST");
    assert.equal(request.path, "/nodes/node-1/commit");
    assert.deepEqual(request.body, { staged_payload: { title: "Committed" } });
  });

  it("normalizes comma-list bodies for merge, tag assignment, and bulk delete", () => {
    const merge = runEcho([
      "nodes:merge",
      "--node-ids",
      "n1,n2",
      "--expected-revision-by-node",
      '{"n1":1,"n2":2}',
      "--format=json",
    ]);
    assert.equal(merge.status, 0, merge.stderr);
    assert.deepEqual(JSON.parse(merge.stdout).request.body.node_ids, ["n1", "n2"]);

    const tags = runEcho(["labels:assign", "--node-id", "n1", "--tag-ids", "", "--expected-revision", "4", "--format=json"]);
    assert.equal(tags.status, 0, tags.stderr);
    assert.deepEqual(JSON.parse(tags.stdout).request.body.tag_ids, []);

    const deletion = runEcho(["nodes:delete-bulk", "--node-ids", "n1,n2", "--yes", "--format=json"]);
    assert.equal(deletion.status, 0, deletion.stderr);
    assert.deepEqual(JSON.parse(deletion.stdout).request.body.node_ids, ["n1", "n2"]);
  });

  it("requires --yes for destructive commands", () => {
    const missing = runEcho(["nodes:delete", "--node-id", "n1", "--format=json"]);
    assert.notEqual(missing.status, 0);
    assert.match(missing.stderr, /requires --yes/);

    const ok = runEcho(["nodes:delete", "--node-id", "n1", "--delete-mode", "cascade", "--yes", "--format=json"]);
    assert.equal(ok.status, 0, ok.stderr);
    const request = JSON.parse(ok.stdout).request;
    assert.equal(request.method, "DELETE");
    assert.equal(request.path, "/nodes/n1");
    assert.deepEqual(request.query, { delete_mode: "cascade" });
  });

  it("includes query params in generated idempotency keys", async () => {
    const seen = [];
    const server = http.createServer((req, res) => {
      seen.push({
        url: req.url,
        key: req.headers["idempotency-key"],
      });
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ ok: true }));
    });
    await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
    try {
      const { port } = server.address();
      const client = new AtlasHttpClient({
        apiKey: "test-token",
        baseUrl: `http://127.0.0.1:${port}`,
        timeoutMs: 5_000,
        retryMax: 0,
      });
      await client.requestJson("DELETE", "/nodes/n1", { query: { delete_mode: "detach_shared" } });
      await client.requestJson("DELETE", "/nodes/n1", { query: { delete_mode: "cascade" } });
    } finally {
      await new Promise((resolve) => server.close(resolve));
    }
    assert.equal(seen.length, 2);
    assert.equal(seen[0].url, "/nodes/n1?delete_mode=detach_shared");
    assert.equal(seen[1].url, "/nodes/n1?delete_mode=cascade");
    assert.ok(seen[0].key);
    assert.ok(seen[1].key);
    assert.notEqual(seen[0].key, seen[1].key);
  });

  it("loads JSON arguments from @file values", () => {
    const tmp = mkdtempSync(path.join(tmpdir(), "atlas-payload-"));
    const payloadPath = path.join(tmp, "commit-new.json");
    writeFileSync(payloadPath, JSON.stringify({ staged_payload: { title: "From file" } }));
    const result = runEcho(["nodes:create", "--payload-json", `@${payloadPath}`, "--format=json"]);
    assert.equal(result.status, 0, result.stderr);
    assert.deepEqual(JSON.parse(result.stdout).request.body, { staged_payload: { title: "From file" } });
  });

  it("uses env indirection for integration secrets", () => {
    const result = runEcho(["integrations:wandb:set", "--api-key-env", "WANDB_API_KEY", "--format=json"], {
      WANDB_API_KEY: "wandb-secret",
    });
    assert.equal(result.status, 0, result.stderr);
    assert.deepEqual(JSON.parse(result.stdout).request.body, { api_key: "wandb-secret" });
  });

  it("connects GitHub from the CLI via github:set with env indirection", () => {
    const result = runEcho(["github:set", "--token-env", "GITHUB_PAT", "--format=json"], {
      GITHUB_PAT: "ghp_cli_token",
    });
    assert.equal(result.status, 0, result.stderr);
    const req = JSON.parse(result.stdout).request;
    assert.equal(req.method, "POST");
    assert.equal(req.path, "/auth/github/pat");
    assert.deepEqual(req.body, { token: "ghp_cli_token" });
  });

  it("github:set requires a token", () => {
    const result = runEcho(["github:set", "--format=json"], {});
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /token or token_env is required/);
  });

  it("plans browser login locally without requiring a key in echo mode", () => {
    const result = runWithBin(BIN, ["login", "--format=json"], {
      cwd: CLI_ROOT,
      env: { ATLAS_HTTP_ECHO: "1", ATLAS_API_KEY: "" },
    });
    assert.equal(result.status, 0, result.stderr);
    const payload = JSON.parse(result.stdout);
    assert.equal(payload.requests[0].path, "/auth/cli/browser/start");
    assert.equal(payload.requests[1].path, "/auth/cli/browser/redeem");
  });

  it("does not advertise or dispatch retired Library commands", () => {
    const help = run(["help", "--format=json"]);
    assert.equal(help.status, 0, help.stderr);
    assert.ok(!JSON.stringify(JSON.parse(help.stdout)).includes("library:"));

    const retired = runEcho(["library:list", "--format=json"]);
    assert.notEqual(retired.status, 0);
    assert.match(retired.stderr, /unknown command/i);
  });


  it("auto-applies atlas.json project id for log and web commands", () => {
    const dir = mkdtempSync(path.join(tmpdir(), "atlas-project-"));
    writeFileSync(path.join(dir, "atlas.json"), JSON.stringify({
      project_id: "proj-123",
      auto: { enabled: true, log: true, web: "prefer_atlas" },
    }));

    const webSearch = runWithBin(BIN, ["web:search", "--query", "recent moe routing", "--num-results", "3", "--format=json"], {
      cwd: dir,
      env: { ATLAS_HTTP_ECHO: "1", ATLAS_API_KEY: "test-token" },
    });
    assert.equal(webSearch.status, 0, webSearch.stderr);
    assert.deepEqual(JSON.parse(webSearch.stdout).request, {
      method: "POST",
      path: "/web/search",
      query: {},
      body: {
        query: "recent moe routing",
        project_id: "proj-123",
        num_results: 3,
      },
      raw: false,
      external: false,
    });

    const webFetch = runWithBin(BIN, ["web:fetch", "--url", "https://example.com/paper", "--text-limit", "12000", "--format=json"], {
      cwd: dir,
      env: { ATLAS_HTTP_ECHO: "1", ATLAS_API_KEY: "test-token" },
    });
    assert.equal(webFetch.status, 0, webFetch.stderr);
    assert.equal(JSON.parse(webFetch.stdout).request.body.project_id, "proj-123");
    assert.equal(JSON.parse(webFetch.stdout).request.body.text_limit, 12000);

    const logTail = runWithBin(BIN, ["log:tail", "--limit", "5", "--format=json"], {
      cwd: dir,
      env: { ATLAS_HTTP_ECHO: "1", ATLAS_API_KEY: "test-token" },
    });
    assert.equal(logTail.status, 0, logTail.stderr);
    assert.equal(JSON.parse(logTail.stdout).request.query.project_id, "proj-123");

    const logSearch = runWithBin(BIN, ["log:search", "--query", "ablation", "--format=json"], {
      cwd: dir,
      env: { ATLAS_HTTP_ECHO: "1", ATLAS_API_KEY: "test-token" },
    });
    assert.equal(logSearch.status, 0, logSearch.stderr);
    assert.deepEqual(JSON.parse(logSearch.stdout).request.body, {
      project_id: "proj-123",
      query: "ablation",
    });
  });

  it("preserves documented draft lock body fields", () => {
    const result = runEcho([
      "draft:lock",
      "--node-id",
      "node-1",
      "--base-committed-revision",
      "7",
      "--stage-session-id",
      "stage-client-1",
      "--purpose",
      "edit",
      "--format=json",
    ]);
    assert.equal(result.status, 0, result.stderr);
    assert.deepEqual(JSON.parse(result.stdout).request.body, {
      base_committed_revision: 7,
      stage_session_id: "stage-client-1",
      purpose: "edit",
    });
  });

  it("maps core map collaboration commands to direct Gateway routes", () => {
    const audit = runEcho(["nodes:history", "--node-id", "node-1", "--limit", "5", "--format=json"]);
    assert.equal(audit.status, 0, audit.stderr);
    assert.deepEqual(JSON.parse(audit.stdout).request, {
      method: "GET",
      path: "/nodes/node-1/audit",
      query: { limit: 5 },
      body: null,
      raw: false,
      external: false,
    });

    const hypothesis = runEcho([
      "draft:derive-hypothesis",
      "--node-id",
      "node-1",
      "--expected-revision",
      "3",
      "--format=json",
    ]);
    assert.equal(hypothesis.status, 0, hypothesis.stderr);
    assert.deepEqual(JSON.parse(hypothesis.stdout).request, {
      method: "POST",
      path: "/nodes/node-1/stage/backfill/hypothesis",
      query: {},
      body: { expected_revision: 3 },
      raw: false,
      external: false,
    });

    const adminList = runEcho(["ops:maps:list", "--owner-user-id", "u1", "--page-size", "10", "--format=json"]);
    assert.equal(adminList.status, 0, adminList.stderr);
    assert.equal(JSON.parse(adminList.stdout).request.path, "/admin/graphs");

    const adminExport = runEcho(["ops:maps:export", "--root-node-id", "root-1", "--max-nodes", "25", "--format=json"]);
    assert.equal(adminExport.status, 0, adminExport.stderr);
    assert.deepEqual(JSON.parse(adminExport.stdout).request, {
      method: "GET",
      path: "/admin/graphs/root-1/export",
      query: { max_nodes: 25 },
      body: null,
      raw: false,
      external: false,
    });

    const stream = runEcho(["ops:maps:export-stream", "--page-size", "2", "--format=json"]);
    assert.equal(stream.status, 0, stream.stderr);
    assert.equal(JSON.parse(stream.stdout).request.raw, true);
    assert.equal(JSON.parse(stream.stdout).request.path, "/admin/graphs/export-stream");

    const blob = runEcho(["evidence:download", "--storage-path", "node/artifact.txt", "--format=json"]);
    assert.equal(blob.status, 0, blob.stderr);
    assert.deepEqual(JSON.parse(blob.stdout).request, {
      method: "GET",
      path: "/blobs",
      query: { storage_path: "node/artifact.txt" },
      body: null,
      raw: true,
      external: false,
    });
  });

  it("stores local profile config without printing raw secrets", () => {
    const tmp = mkdtempSync(path.join(tmpdir(), "atlas-config-"));
    const configPath = path.join(tmp, "config.json");
    const env = { ATLAS_CLI_CONFIG_PATH: configPath, ATLAS_API_KEY: "" };

    const set = runWithBin(BIN, [
      "config:set",
      "--name",
      "lab",
      "--base-url",
      "https://atlas.example.test/api/v1",
      "--api-key-env",
      "ATLAS_LAB_KEY",
      "--default-format",
      "table",
      "--timeout-ms",
      "1234",
      "--retry-max",
      "0",
      "--format=json",
    ], { cwd: CLI_ROOT, env });
    assert.equal(set.status, 0, set.stderr);
    const setBody = JSON.parse(set.stdout);
    assert.equal(setBody.profile.name, "lab");
    assert.equal(setBody.profile.api_key_env, "ATLAS_LAB_KEY");
    assert.equal(setBody.profile.api_key_storage, "env");
    assert.doesNotMatch(set.stdout, /thk_|secret/i);

    const listed = runWithBin(BIN, ["config:list", "--format=json"], { cwd: CLI_ROOT, env });
    assert.equal(listed.status, 0, listed.stderr);
    const listBody = JSON.parse(listed.stdout);
    assert.equal(listBody.active_profile, "lab");
    assert.equal(listBody.profiles.some((profile) => profile.name === "lab"), true);
    assert.doesNotMatch(listed.stdout, /thk_|secret/i);

    const rawConfig = JSON.parse(readFileSync(configPath, "utf8"));
    assert.equal(rawConfig.profiles.lab.api_key_env, "ATLAS_LAB_KEY");
    assert.equal(rawConfig.profiles.lab.api_key, undefined);

    const unset = runWithBin(BIN, ["config:unset", "--name", "lab", "--format=json"], { cwd: CLI_ROOT, env });
    assert.equal(unset.status, 0, unset.stderr);
    assert.equal(JSON.parse(unset.stdout).unset, true);
  });

  it("plans one-shot evidence uploads without tool transport", () => {
    const tmp = mkdtempSync(path.join(tmpdir(), "atlas-artifact-"));
    const artifactPath = path.join(tmp, "report.txt");
    writeFileSync(artifactPath, "hello artifact");
    const result = runEcho([
      "evidence:add",
      "--node-id",
      "node-1",
      "--expected-revision",
      "3",
      "--items",
      JSON.stringify([{ local_path: artifactPath, artifact_type: "text" }]),
      "--format=json",
    ]);
    assert.equal(result.status, 0, result.stderr);
    const payload = JSON.parse(result.stdout);
    assert.equal(payload.requests[0].path, "/nodes/node-1/artifacts/uploads/prepare");
    assert.equal(payload.requests[1].method, "PUT");
    assert.equal(payload.requests[2].path, "/nodes/node-1/artifacts/uploads/finalize");
  });

  it("resolves relative prepared evidence upload URLs against the Gateway base URL", async () => {
    const seen = [];
    const server = http.createServer((req, res) => {
      seen.push({ method: req.method, url: req.url });
      if (req.method === "POST" && req.url === "/api/v1/nodes/node-1/artifacts/uploads/prepare") {
        res.writeHead(201, { "Content-Type": "application/json" });
        res.end(JSON.stringify({
          batch_token: "batch-1",
          items: [
            {
              method: "PUT",
              upload_url: "/api/v1/artifacts/uploads/upload-1",
              headers: { "Content-Type": "text/plain" },
            },
          ],
        }));
        return;
      }
      if (req.method === "PUT" && req.url === "/api/v1/artifacts/uploads/upload-1") {
        req.resume();
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ uploaded: true }));
        return;
      }
      if (req.method === "POST" && req.url === "/api/v1/nodes/node-1/artifacts/uploads/finalize") {
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ revision: 4 }));
        return;
      }
      res.writeHead(404, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: "unexpected route" }));
    });
    await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
    try {
      const { port } = server.address();
      const tmp = mkdtempSync(path.join(tmpdir(), "atlas-upload-"));
      const artifactPath = path.join(tmp, "artifact.txt");
      writeFileSync(artifactPath, "hello artifact");
      const client = new AtlasHttpClient({
        apiKey: "test-token",
        baseUrl: `http://127.0.0.1:${port}/api/v1`,
        timeoutMs: 5_000,
        retryMax: 0,
      });
      const result = await runCommand(getCommand("evidence:add"), {
        node_id: "node-1",
        expected_revision: 3,
        items: [{ local_path: artifactPath, artifact_type: "text" }],
      }, client);
      assert.deepEqual(result, { revision: 4 });
    } finally {
      await new Promise((resolve) => server.close(resolve));
    }
    assert.deepEqual(seen.map((item) => `${item.method} ${item.url}`), [
      "POST /api/v1/nodes/node-1/artifacts/uploads/prepare",
      "PUT /api/v1/artifacts/uploads/upload-1",
      "POST /api/v1/nodes/node-1/artifacts/uploads/finalize",
    ]);
  });

  it("accepts --node as an alias for --node-id and surfaces a slug hint when missing", () => {
    const aliased = runEcho(["nodes:show", "--node", "11111111-1111-1111-1111-111111111111", "--format=json"]);
    assert.equal(aliased.status, 0, aliased.stderr);
    const request = JSON.parse(aliased.stdout).request;
    assert.equal(request.path, "/nodes/11111111-1111-1111-1111-111111111111");

    const missing = runEcho(["map:summary", "--format=json"]);
    assert.notEqual(missing.status, 0);
    // The error should suggest a discovery command, not just say "node_id is required".
    assert.match(missing.stderr, /--node-id is required/);
    assert.match(missing.stderr, /atlas node:list/);
  });

  it("renders human-friendly text on TTY but stays JSON when format is explicit", () => {
    // ``--format=json`` always preserves the machine-readable shape so this
    // never regresses the scripting contract.
    const json = runEcho(["node:list", "--format=json"]);
    assert.equal(json.status, 0, json.stderr);
    assert.doesNotThrow(() => JSON.parse(json.stdout));
  });

  it("exposes project:list and the keys:list --active-only flag in help", () => {
    const projectHelp = run(["help", "project:list", "--format=json"]);
    assert.equal(projectHelp.status, 0, projectHelp.stderr);
    assert.equal(JSON.parse(projectHelp.stdout).name, "project:list");

    const keysHelp = run(["help", "keys:list", "--format=json"]);
    assert.equal(keysHelp.status, 0, keysHelp.stderr);
    const keysSchema = JSON.parse(keysHelp.stdout);
    assert.ok(
      keysSchema.optional.some((field) => field.name === "active_only"),
      "keys:list should expose --active-only as an optional flag",
    );
  });

  it("maps the research-loop verbs to their routes with comma-list coercion", () => {
    const hyp = runEcho([
      "hypothesis:add",
      "--project", "11111111-1111-1111-1111-111111111111",
      "--claim", "expert-choice routing beats top-2 at equal FLOPs",
      "--assumptions", "same data, same budget",
      "--disconfirmers", "val_loss regression, throughput collapse",
      "--format=json",
    ]);
    assert.equal(hyp.status, 0, hyp.stderr);
    const hypRequest = JSON.parse(hyp.stdout).request;
    assert.equal(hypRequest.method, "POST");
    assert.equal(hypRequest.path, "/hypotheses:add");
    assert.equal(hypRequest.body.project_id, "11111111-1111-1111-1111-111111111111");
    assert.deepEqual(hypRequest.body.assumptions, ["same data", "same budget"]);
    assert.deepEqual(hypRequest.body.disconfirmers, ["val_loss regression", "throughput collapse"]);

    const plan = runEcho([
      "experiment:plan",
      "--project", "11111111-1111-1111-1111-111111111111",
      "--hypothesis", "22222222-2222-2222-2222-222222222222",
      "--metric", "metrics.val_loss",
      "--success-criterion", "metrics.val_loss < 2.0",
      "--format=json",
    ]);
    assert.equal(plan.status, 0, plan.stderr);
    const planRequest = JSON.parse(plan.stdout).request;
    assert.equal(planRequest.path, "/experiments:plan");
    assert.equal(planRequest.body.hypothesis_id, "22222222-2222-2222-2222-222222222222");
    assert.equal(planRequest.body.success_criterion, "metrics.val_loss < 2.0");

    const decision = runEcho([
      "decision:add",
      "--project", "11111111-1111-1111-1111-111111111111",
      "--decision", "drop top-2 routing",
      "--basis", "33333333-3333-3333-3333-333333333333,44444444-4444-4444-4444-444444444444",
      "--format=json",
    ]);
    assert.equal(decision.status, 0, decision.stderr);
    const decisionRequest = JSON.parse(decision.stdout).request;
    assert.equal(decisionRequest.path, "/decisions:add");
    assert.deepEqual(decisionRequest.body.basis, [
      "33333333-3333-3333-3333-333333333333",
      "44444444-4444-4444-4444-444444444444",
    ]);
  });

  it("maps brief to the project context-packet route via --project", () => {
    const result = runEcho([
      "brief",
      "--project", "11111111-1111-1111-1111-111111111111",
      "--format=json",
    ]);
    assert.equal(result.status, 0, result.stderr);
    const request = JSON.parse(result.stdout).request;
    assert.equal(request.method, "GET");
    assert.equal(request.path, "/projects/11111111-1111-1111-1111-111111111111/brief");
  });

  it("maps --project onto run:compare's root query param", () => {
    const result = runEcho([
      "run:compare",
      "--project", "11111111-1111-1111-1111-111111111111",
      "--sort", "metrics.val_loss",
      "--best",
      "--format=json",
    ]);
    assert.equal(result.status, 0, result.stderr);
    const request = JSON.parse(result.stdout).request;
    assert.equal(request.path, "/runs:compare");
    assert.equal(request.query.root, "11111111-1111-1111-1111-111111111111");
    assert.equal(request.query.sort, "metrics.val_loss");
    assert.equal(request.query.best, true);
  });

  it("detects git code state from a working tree (auto-capture for run:record)", async () => {
    const { detectGitState } = await import("../src/atlas-runtime/local-commands.mjs");
    // The repo this test runs in is itself a git checkout — a stable fixture.
    const state = await detectGitState(CLI_ROOT);
    assert.ok(state, "expected git state inside the repo");
    assert.match(state.head_commit_sha, /^[0-9a-f]{40}$/);
    assert.equal(typeof state.git_dirty, "boolean");
    // A directory that is definitely not a git repo yields null (no capture).
    const none = await detectGitState(mkdtempSync(path.join(tmpdir(), "atlas-no-git-")));
    assert.equal(none, null);
  });

  it("rejects legacy key=value argument syntax", () => {
    const result = runEcho(["nodes:show", "node_id=n1", "--format=json"]);
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /legacy argument syntax/);
  });

  it("packs a runnable direct runtime CLI artifact", () => {
    const tmp = mkdtempSync(path.join(tmpdir(), "atlas-pack-"));
    const pack = spawnSync("npm", ["pack", "--pack-destination", tmp], {
      cwd: CLI_ROOT,
      encoding: "utf8",
    });
    assert.equal(pack.status, 0, pack.stderr);

    const tarball = readdirSync(tmp).find((name) => name.endsWith(".tgz"));
    assert.ok(tarball, `npm pack did not produce a tarball in ${tmp}`);

    const installDir = path.join(tmp, "consumer");
    const install = spawnSync("npm", ["install", "--ignore-scripts", "--prefix", installDir, path.join(tmp, tarball)], {
      encoding: "utf8",
    });
    assert.equal(install.status, 0, install.stderr);

    const extractDir = path.join(installDir, "node_modules", "@synsci", "atlas");
    const packedBin = path.join(extractDir, "bin", "atlas.mjs");
    const help = runWithBin(packedBin, ["help", "--format=json"], { cwd: extractDir });
    assert.equal(help.status, 0, help.stderr);
    assert.deepEqual(JSON.parse(help.stdout).commands.map((command) => command.name).sort(), CORE_COMMANDS);
  });

  it("contains direct runtime files in the raw npm tarball", () => {
    const tmp = mkdtempSync(path.join(tmpdir(), "atlas-pack-"));
    const pack = spawnSync("npm", ["pack", "--pack-destination", tmp], {
      cwd: CLI_ROOT,
      encoding: "utf8",
    });
    assert.equal(pack.status, 0, pack.stderr);
    const tarball = readdirSync(tmp).find((name) => name.endsWith(".tgz"));
    const tar = spawnSync("tar", ["-tzf", path.join(tmp, tarball)], { encoding: "utf8" });
    assert.equal(tar.status, 0, tar.stderr);
    assert.match(tar.stdout, /package\/src\/atlas-runtime\/dispatch\.mjs/);
    assert.match(tar.stdout, /package\/src\/atlas-runtime\/http-client\.mjs/);
    assert.match(tar.stdout, /package\/src\/atlas-runtime\/commands\.mjs/);
    assert.match(tar.stdout, /package\/src\/atlas-runtime\/optimize-harness\/atlas_gepa\.py/);
    assert.match(tar.stdout, /package\/src\/atlas-runtime\/optimize-harness\/optimize\.py/);
    assert.match(tar.stdout, /package\/src\/atlas-runtime\/optimize-harness\/verify\.py/);
    assert.doesNotMatch(tar.stdout, /package\/skills\//);
    assert.doesNotMatch(tar.stdout, /agent-install\.mjs|web-log-hook\.mjs|postinstall\.mjs/);
    assert.doesNotMatch(tar.stdout, /legacy-mcp-skills/);
    assert.doesNotMatch(tar.stdout, /src\/runtime\//);
    assert.doesNotMatch(tar.stdout, /mcp-writer/);
  });
});

function run(args) {
  return runWithBin(BIN, args, { cwd: CLI_ROOT });
}

function runEcho(args, env = {}) {
  return runWithBin(BIN, args, {
    cwd: CLI_ROOT,
    env: {
      ATLAS_HTTP_ECHO: "1",
      ATLAS_API_KEY: "test-token",
      ...env,
    },
  });
}

function runWithBin(bin, args, { cwd, env = {} }) {
  return spawnSync(process.execPath, [bin, ...args], {
    cwd,
    encoding: "utf8",
    env: {
      ...process.env,
      ATLAS_API_KEY: "test-token",
      ...env,
    },
  });
}
