import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { waitForPackage } from "./registry.mjs";

assert.ok(["true", "false"].includes(process.env.ATLAS_PUBLISH), "The release workflow must select publication or a dry run explicitly");
const publish = process.env.ATLAS_PUBLISH === "true";
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const directory = path.join(root, "dist/releases");
const manifest = JSON.parse(readFileSync(path.join(directory, "manifest.json"), "utf8"));
assert.equal(manifest.commit, process.env.RELEASE_SHA);
for (const item of manifest.packages) {
  const archive = path.join(directory, item.filename);
  assert.equal(createHash("sha256").update(readFileSync(archive)).digest("hex"), item.sha256);
  const spec = `${item.name}@${item.version}`;
  const existing = spawnSync("npm", ["view", spec, "dist.integrity", "--json"], { encoding: "utf8" });
  if (existing.status === 0) {
    assert.equal(JSON.parse(existing.stdout), item.integrity, `Refusing to replace different existing package ${spec}`);
    console.log(`${spec} already matches this release`);
    continue;
  }
  const error = JSON.parse(existing.stdout || "{}").error;
  assert.equal(error?.code, "E404", `Registry lookup failed for ${spec}: ${error?.code || existing.status}`);
  execFileSync("npm", ["publish", archive, "--access", "public", `--provenance=${publish}`, ...(!publish ? ["--dry-run"] : [])], { stdio: "inherit" });
  if (!publish) continue;
  console.log(`Waiting for registry processing of ${spec}`);
  await waitForPackage(item.name, item.version, item.integrity);
}
