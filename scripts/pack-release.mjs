import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const directory = path.join(root, "dist/releases");
mkdirSync(directory, { recursive: true });
const packages = [];
for (const workspace of ["cli", "sdk", "ui"]) {
  const metadata = JSON.parse(readFileSync(path.join(root, workspace, "package.json"), "utf8"));
  assert.equal(metadata.private, undefined);
  assert.equal(metadata.publishConfig.access, "public");
  assert.equal(metadata.license, "Apache-2.0");
  assert.equal(metadata.scripts?.postinstall, undefined);
  const packed = JSON.parse(execFileSync("npm", ["pack", "--workspace", workspace, "--ignore-scripts", "--json", "--pack-destination", directory], { cwd: root, encoding: "utf8" }))[0];
  const files = packed.files.map(file => file.path);
  assert.ok(files.includes("LICENSE"));
  assert.ok(files.includes("README.md"));
  assert.equal(files.some(file => /(^|\/)(?:\.env|node_modules|tests?|backend|landing|app)(?:[/.]|$)/.test(file)), false);
  assert.equal(files.some(file => /\.(?:test|spec)\./.test(file)), false);
  const archive = path.join(directory, packed.filename);
  packages.push({ workspace, name: packed.name, version: packed.version, filename: packed.filename, integrity: packed.integrity, sha256: createHash("sha256").update(readFileSync(archive)).digest("hex") });
}
const commit = execFileSync("git", ["rev-parse", "HEAD"], { cwd: root, encoding: "utf8" }).trim();
writeFileSync(path.join(directory, "manifest.json"), `${JSON.stringify({ commit, packages }, null, 2)}\n`);
console.log(`Checked ${packages.length} public npm artifacts from ${commit}`);
