import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const cli = path.join(root, "cli");
const metadata = JSON.parse(readFileSync(path.join(cli, "package.json"), "utf8"));

describe("Atlas npm release", () => {
  it("ships a public CLI without installers, secrets, or dashboard source", () => {
    const packed = JSON.parse(execFileSync("npm", ["pack", "--dry-run", "--json", "--ignore-scripts"], {cwd: cli, encoding: "utf8"}))[0];
    const files = packed.files.map(entry => entry.path);
    assert.ok(files.includes("bin/atlas.mjs"));
    assert.ok(files.includes("LICENSE"));
    assert.equal(files.some(file => /(^|\/)(?:\.env|skills|node_modules|backend|landing)(?:[/.]|$)/.test(file)), false);
    assert.equal(metadata.private, undefined);
    assert.equal(metadata.license, "Apache-2.0");
    assert.equal(metadata.scripts.postinstall, undefined);
    assert.deepEqual(Object.keys(metadata.dependencies), ["open"]);
  });
  it("reports the published package version", () => {
    const version = execFileSync(process.execPath, ["bin/atlas.mjs", "--version"], {cwd: cli, encoding: "utf8"}).trim();
    assert.equal(version, metadata.version);
  });
  it("preserves the full checked-in command contract", () => {
    const expected = JSON.parse(readFileSync(path.join(root, "backend/tests/fixtures/atlas_cli_help.json"), "utf8"));
    const help = JSON.parse(execFileSync(process.execPath, ["bin/atlas.mjs", "help", "--format=json"], {cwd: cli, encoding: "utf8"}));
    assert.deepEqual({commands: help.commands.map(({name,endpoints}) => ({name,endpoints}))}, expected);
    assert.equal(help.commands.some(command => command.name === "install"), false);
  });
});
