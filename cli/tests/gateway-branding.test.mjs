import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const CLI_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const PACKAGE = JSON.parse(readFileSync(path.join(CLI_ROOT, "package.json"), "utf8"));
const WIRE_HEADERS = ["X-Atlas-Cli-Command", "X-Atlas-Cli-Invocation-Id"];

function lineFor(text, offset) {
  return text.slice(0, offset).split("\n").length;
}

function withoutApprovedCompatibilityTokens(file, text) {
  if (file !== "src/atlas-runtime/http-client.mjs") return text;
  let clean = text;
  for (const header of WIRE_HEADERS) {
    assert.equal(clean.split(header).length - 1, 1, `${header} must remain exactly once`);
    clean = clean.replace(header, "APPROVED_WIRE_HEADER");
  }
  return clean;
}

describe("retired Gateway package branding", () => {
  it("keeps only the required atlas compatibility identifiers", () => {
    assert.equal(PACKAGE.name, "@synsci/atlas");
    assert.equal(PACKAGE.version, "0.15.0");
    assert.equal(PACKAGE.bin.atlas, "bin/atlas.mjs");

    const runtime = readFileSync(path.join(CLI_ROOT, "src/atlas-runtime/http-client.mjs"), "utf8");
    const config = readFileSync(path.join(CLI_ROOT, "src/atlas-runtime/config.mjs"), "utf8");
    assert.match(runtime, /class AtlasHttpClient\b/);
    assert.match(runtime, /X-Atlas-Cli-Command/);
    assert.match(runtime, /X-Atlas-Cli-Invocation-Id/);
    assert.match(config, /ATLAS_API_KEY/);
    assert.match(config, /ATLAS_BASE_URL/);
  });

  it("ships no Atlas skills, agent installer, hook, or post-install promotion", () => {
    assert.equal(existsSync(path.join(CLI_ROOT, "src/atlas-runtime/agent-install.mjs")), false);
    assert.equal(existsSync(path.join(CLI_ROOT, "src/atlas-runtime/hooks/web-log-hook.mjs")), false);
    assert.equal(existsSync(path.join(CLI_ROOT, "scripts/postinstall.mjs")), false);
    assert.equal(PACKAGE.scripts.postinstall, undefined);
    assert.equal(PACKAGE.dependencies.inquirer, undefined);

    const packed = spawnSync("npm", ["pack", "--dry-run", "--json", "--ignore-scripts"], {
      cwd: CLI_ROOT,
      encoding: "utf8",
    });
    assert.equal(packed.status, 0, packed.stderr);
    const manifest = JSON.parse(packed.stdout)[0];
    const files = manifest.files.map((entry) => entry.path);
    assert.ok(files.includes("bin/atlas.mjs"));
    assert.equal(files.some((file) => file.startsWith("skills/")), false);
    assert.equal(files.some((file) => /agent-install|web-log-hook|postinstall/.test(file)), false);

    for (const file of files) {
      const text = readFileSync(path.join(CLI_ROOT, file), "utf8");
      const visible = withoutApprovedCompatibilityTokens(file, text);
      const match = /\bAtlas\b/.exec(visible);
      assert.equal(
        match,
        null,
        match ? `${file}:${lineFor(visible, match.index)} contains unapproved Atlas product branding` : file,
      );
    }
  });

  it("removes the skill installer from help", () => {
    const help = spawnSync(process.execPath, [path.join(CLI_ROOT, "bin/atlas.mjs"), "help", "--format=json"], {
      cwd: CLI_ROOT,
      encoding: "utf8",
    });
    assert.equal(help.status, 0, help.stderr);
    const commands = JSON.parse(help.stdout).commands;
    assert.equal(commands.some((command) => command.name === "install"), false);
    assert.doesNotMatch(help.stdout, /bundled skills|coding agents/i);
  });
});
