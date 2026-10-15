import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const CLI_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const REPO_ROOT = path.resolve(CLI_ROOT, "..");
const README = readFileSync(path.join(CLI_ROOT, "README.md"), "utf8");
const CHANGELOG = readFileSync(path.join(CLI_ROOT, "CHANGELOG.md"), "utf8");
const PACKAGE = JSON.parse(readFileSync(path.join(CLI_ROOT, "package.json"), "utf8"));
const LOCK = JSON.parse(readFileSync(path.join(CLI_ROOT, "package-lock.json"), "utf8"));

describe("retired CLI release contract", () => {
  it("keeps the extracted root package private without a publication workflow", () => {
    assert.equal(
      existsSync(path.join(REPO_ROOT, ".github/workflows/publish-cli.yml")),
      false,
    );
    const root = JSON.parse(readFileSync(path.join(REPO_ROOT, "package.json"), "utf8"));
    assert.equal(root.private, true);
    assert.equal(root.bin.atlas, "cli/bin/atlas.mjs");
    assert.equal(root.scripts.postinstall, undefined);
    assert.match(root.scripts.prepublishOnly, /not a public release/);
  });

  it("keeps the retired package metadata and documentation aligned", () => {
    assert.equal(PACKAGE.version, "0.15.0");
    assert.equal(LOCK.version, PACKAGE.version);
    assert.equal(LOCK.packages[""].version, PACKAGE.version);
    assert.equal(PACKAGE.private, true);
    assert.equal(PACKAGE.publishConfig, undefined);
    assert.match(PACKAGE.scripts.prepublishOnly, /must not be published/);
    assert.match(README, /^# Retired compatibility runtime$/m);
    assert.match(README, /does not bundle or install agent skills/);
    assert.doesNotMatch(README, /npm i -g|atlas install/);
    assert.match(CHANGELOG, /^## Unreleased$/m);
    assert.doesNotMatch(PACKAGE.files.join("\n"), /skills|postinstall/);
    assert.equal(PACKAGE.scripts.postinstall, undefined);
  });

  it("keeps the retired runtime dependency surface to the one imported package", () => {
    // Only `open` is imported (src/atlas-runtime/dispatch.mjs and
    // local-commands.mjs). Anything else is supply-chain surface for a
    // package that is still `npm ci`'d in CI but never republished.
    assert.deepEqual(Object.keys(PACKAGE.dependencies), ["open"]);
    assert.deepEqual(Object.keys(LOCK.packages[""].dependencies), ["open"]);
    assert.equal(PACKAGE.devDependencies, undefined);
  });

  it("matches the backend's checked-in CLI help contract fixture", () => {
    // backend/tests/test_atlas_cli_core_routes.py verifies every endpoint in
    // this fixture is a mounted backend route without needing Node. This
    // side keeps the fixture honest against the live `help --format=json`.
    const fixture = JSON.parse(
      readFileSync(
        path.join(REPO_ROOT, "backend/tests/fixtures/atlas_cli_help.json"),
        "utf8",
      ),
    );
    const live = JSON.parse(
      execFileSync(process.execPath, ["bin/atlas.mjs", "help", "--format=json"], {
        cwd: CLI_ROOT,
        encoding: "utf8",
      }),
    );
    const projected = {
      commands: live.commands.map(({ name, endpoints }) => ({ name, endpoints })),
    };
    assert.deepEqual(
      fixture,
      projected,
      "backend/tests/fixtures/atlas_cli_help.json is stale; regenerate it with the " +
        "jq command in backend/tests/test_atlas_cli_core_routes.py",
    );
  });
});
