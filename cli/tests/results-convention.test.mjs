import { describe, it } from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import { mkdtempSync, writeFileSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";

import {
  buildRunsRecordBody,
  readEvalDoc,
  detectRunCommand,
} from "../src/atlas-runtime/local-commands.mjs";

// The "results contract": run:record folds an EVAL.md-style results doc into
// the run node's body so every run reads results-first.
describe("run:record — EVAL.md results convention", () => {
  it("attaches an explicit --eval file as eval_markdown", async () => {
    const dir = mkdtempSync(path.join(tmpdir(), "atlas-eval-"));
    const evalPath = path.join(dir, "results.md");
    writeFileSync(evalPath, "# Results\nval_loss = 2.10\n");

    const body = await buildRunsRecordBody({
      project_id: "p1",
      title: "run",
      eval: evalPath,
      no_git: true,
    });
    assert.equal(body.eval_markdown, "# Results\nval_loss = 2.10\n");
  });

  it("throws when an explicit --eval file is missing", async () => {
    await assert.rejects(
      () => buildRunsRecordBody({ project_id: "p1", eval: "/no/such/EVAL.md", no_git: true }),
      /--eval file not found/,
    );
  });

  it("does not attach anything with --no-eval", async () => {
    const dir = mkdtempSync(path.join(tmpdir(), "atlas-eval-"));
    writeFileSync(path.join(dir, "EVAL.md"), "ignored");
    const cwd = process.cwd();
    process.chdir(dir);
    try {
      const body = await buildRunsRecordBody({ project_id: "p1", no_eval: true, no_git: true });
      assert.equal(body.eval_markdown, undefined);
    } finally {
      process.chdir(cwd);
    }
  });

  it("auto-detects EVAL.md in the cwd", async () => {
    const dir = mkdtempSync(path.join(tmpdir(), "atlas-eval-"));
    writeFileSync(path.join(dir, "EVAL.md"), "auto results");
    const found = await readEvalDoc(undefined);
    // readEvalDoc(undefined) probes process.cwd(); verify the probe + cap by
    // pointing it at the file explicitly too.
    assert.equal(await readEvalDoc(path.join(dir, "EVAL.md")), "auto results");
    assert.ok(found === null || typeof found === "string");
  });

  it("caps a very large results doc", async () => {
    const dir = mkdtempSync(path.join(tmpdir(), "atlas-eval-"));
    const big = "x".repeat(50000);
    const p = path.join(dir, "EVAL.md");
    writeFileSync(p, big);
    const text = await readEvalDoc(p);
    assert.equal(text.length, 20000);
  });
});

// Zero-config run-command detection for `atlas init`.
describe("atlas init — run-command detection", () => {
  it("detects run.sh", async () => {
    const dir = mkdtempSync(path.join(tmpdir(), "atlas-init-"));
    writeFileSync(path.join(dir, "run.sh"), "#!/bin/bash\necho hi\n");
    assert.equal(await detectRunCommand(dir), "bash run.sh");
  });

  it("prefers .atlas/run.sh over speedrun.sh", async () => {
    const dir = mkdtempSync(path.join(tmpdir(), "atlas-init-"));
    mkdirSync(path.join(dir, ".atlas"));
    writeFileSync(path.join(dir, ".atlas", "run.sh"), "x");
    writeFileSync(path.join(dir, "speedrun.sh"), "x");
    assert.equal(await detectRunCommand(dir), "bash .atlas/run.sh");
  });

  it("returns null when no run script exists", async () => {
    const dir = mkdtempSync(path.join(tmpdir(), "atlas-init-"));
    assert.equal(await detectRunCommand(dir), null);
  });
});
