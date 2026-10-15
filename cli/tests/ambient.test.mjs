import { describe, it } from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { mkdtempSync, readFileSync, writeFileSync, existsSync, realpathSync } from "node:fs";
import { tmpdir } from "node:os";

import { projectAutoConfig, writeProjectConfig } from "../src/atlas-runtime/project-config.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const CLI_ROOT = path.resolve(__dirname, "..");
const BIN = path.join(CLI_ROOT, "bin", "atlas.mjs");

function runEchoIn(dir, args) {
  return spawnSync(process.execPath, [BIN, ...args], {
    cwd: dir,
    encoding: "utf8",
    env: { ...process.env, ATLAS_HTTP_ECHO: "1", ATLAS_API_KEY: "test-token" },
  });
}

// Like runEchoIn but lets a test override env (e.g. HOME) — os.homedir() honors
// $HOME on POSIX, so pointing HOME at a temp dir lets us exercise the
// home-directory guard without ever touching the real home.
function runEchoEnv(dir, args, extraEnv = {}) {
  return spawnSync(process.execPath, [BIN, ...args], {
    cwd: dir,
    encoding: "utf8",
    env: { ...process.env, ATLAS_HTTP_ECHO: "1", ATLAS_API_KEY: "test-token", ...extraEnv },
  });
}

describe("atlas.json activation contract", () => {
  it("projectAutoConfig fills sane defaults and honors opt-outs", () => {
    assert.deepEqual(projectAutoConfig({}), {
      enabled: true,
      log: true,
      web: "prefer_atlas",
      capture: "suggest",
    });
    assert.equal(projectAutoConfig({ auto: { enabled: false } }).enabled, false);
    assert.equal(projectAutoConfig({ auto: { log: false } }).log, false);
    assert.equal(projectAutoConfig({ auto: { web: "native" } }).web, "native");
  });

  it("writeProjectConfig deep-merges auto and scrubs retired source bindings", async () => {
    const dir = mkdtempSync(path.join(tmpdir(), "atlas-cfg-"));
    writeFileSync(path.join(dir, "atlas.json"), JSON.stringify({ source_ids: ["retired"] }));
    await writeProjectConfig(dir, { project_id: "p", auto: { enabled: false, log: true } });
    await writeProjectConfig(dir, { auto: { web: "native" } });
    const parsed = JSON.parse(readFileSync(path.join(dir, "atlas.json"), "utf8"));
    assert.equal(parsed.project_id, "p", "project_id preserved across writes");
    assert.equal(parsed.source_ids, undefined, "retired source_ids removed");
    assert.deepEqual(parsed.auto, { enabled: false, log: true, web: "native" }, "auto deep-merged");
  });
});

describe("atlas init (echo)", () => {
  it("writes atlas.json with project id and ambient defaults", () => {
    const dir = mkdtempSync(path.join(tmpdir(), "atlas-init-"));
    const result = runEchoIn(dir, ["init", "--format=json"]);
    assert.equal(result.status, 0, result.stderr);
    const manifest = JSON.parse(readFileSync(path.join(dir, "atlas.json"), "utf8"));
    assert.equal(manifest.project_id, "echo-project");
    assert.equal(manifest.source_ids, undefined);
    assert.deepEqual(manifest.auto, {
      enabled: true,
      log: true,
      web: "prefer_atlas",
      capture: "suggest",
    });
    assert.equal(manifest.privacy, "private");
  });

  it("honors opt-out flags", () => {
    const dir = mkdtempSync(path.join(tmpdir(), "atlas-init2-"));
    const result = runEchoIn(dir, [
      "init",
      "--no-log",
      "--web-mode", "native",
      "--capture-mode", "auto",
      "--privacy", "public",
      "--format=json",
    ]);
    assert.equal(result.status, 0, result.stderr);
    const manifest = JSON.parse(readFileSync(path.join(dir, "atlas.json"), "utf8"));
    assert.equal(manifest.auto.log, false);
    assert.equal(manifest.auto.web, "native");
    assert.equal(manifest.auto.capture, "auto");
    assert.equal(manifest.privacy, "public");
  });

  it("refuses to run in $HOME (would scope ambient mode to everything) and writes nothing", () => {
    // realpath so HOME matches the child's physical process.cwd() on macOS
    // (/var -> /private/var); real home dirs like /Users/x aren't symlinked.
    const fakeHome = realpathSync(mkdtempSync(path.join(tmpdir(), "atlas-fakehome-")));
    // cwd === HOME === homedir() -> the guard must fire.
    const result = runEchoEnv(fakeHome, ["init", "--format=json"], { HOME: fakeHome });
    assert.notEqual(result.status, 0, "init in $HOME must fail");
    assert.match(`${result.stderr}${result.stdout}`, /home directory|Refusing/i);
    assert.ok(!existsSync(path.join(fakeHome, "atlas.json")), "must not write atlas.json on refusal");
  });

  it("refuses to run in a filesystem root", () => {
    const dir = mkdtempSync(path.join(tmpdir(), "atlas-init-root-"));
    const result = runEchoIn(dir, ["init", "--path", path.parse(dir).root, "--format=json"]);
    assert.notEqual(result.status, 0, "init in / must fail");
    assert.match(`${result.stderr}${result.stdout}`, /filesystem root|Refusing/i);
  });

  it("--force overrides the home guard (writes into the fake home, never real $HOME)", () => {
    const fakeHome = realpathSync(mkdtempSync(path.join(tmpdir(), "atlas-fakehome2-")));
    const result = runEchoEnv(fakeHome, ["init", "--force", "--format=json"], { HOME: fakeHome });
    assert.equal(result.status, 0, `--force should bypass the guard: ${result.stderr}`);
    assert.ok(existsSync(path.join(fakeHome, "atlas.json")), "--force should write atlas.json");
  });
});

describe("ambient project auto-resolution (echo)", () => {
  it("auto-resolves brief's project from atlas.json with no --project", () => {
    const dir = mkdtempSync(path.join(tmpdir(), "atlas-brief-"));
    writeFileSync(
      path.join(dir, "atlas.json"),
      JSON.stringify({ project_id: "11111111-1111-1111-1111-111111111111", auto: { enabled: true } }),
    );
    const result = runEchoIn(dir, ["brief", "--format=json"]);
    assert.equal(result.status, 0, result.stderr);
    const request = JSON.parse(result.stdout).request;
    assert.equal(request.path, "/projects/11111111-1111-1111-1111-111111111111/brief");
    assert.match(result.stderr, /using project/);
  });

  it("does not auto-resolve when the project opted out (auto.enabled:false)", () => {
    const dir = mkdtempSync(path.join(tmpdir(), "atlas-optout-"));
    writeFileSync(
      path.join(dir, "atlas.json"),
      JSON.stringify({ project_id: "proj-x", auto: { enabled: false } }),
    );
    const result = runEchoIn(dir, ["log:tail", "--format=json"]);
    assert.equal(result.status, 0, result.stderr);
    // The opted-out project's id must NOT be injected into the request.
    const request = JSON.parse(result.stdout).request;
    assert.equal(request.query.project_id, undefined, "project_id should not be auto-injected when auto.enabled:false");
    assert.doesNotMatch(result.stderr, /using project/);
  });

  it("--no-log turns off ambient provenance logging on web:search", () => {
    const dir = mkdtempSync(path.join(tmpdir(), "atlas-nolog-"));
    writeFileSync(
      path.join(dir, "atlas.json"),
      JSON.stringify({ project_id: "proj-y", auto: { enabled: true, log: true } }),
    );
    const result = runEchoIn(dir, ["web:search", "--query", "x", "--no-log", "--format=json"]);
    assert.equal(result.status, 0, result.stderr);
    const body = JSON.parse(result.stdout).request.body;
    assert.equal(body.log, false);
    assert.equal(body.project_id, "proj-y");
  });
});
