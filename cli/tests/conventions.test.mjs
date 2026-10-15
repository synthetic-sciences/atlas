import { describe, it } from "node:test";
import assert from "node:assert/strict";

import { COMMANDS, getCommand, legacyAliasFor } from "../src/atlas-runtime/commands.mjs";

// cli/CONVENTIONS.md, enforced. If you're here because a new command failed:
// read that file first — extending these whitelists is a review decision,
// not a test fix.

const BARE_COMMANDS = new Set([
  "login",
  "logout",
  "whoami",
  "doctor",
  "init",
  "fork",
  "brief",
  "leaderboard",
  "reproduce",
  "autoresearch",
  // public discovery / browse commands
  "explore",
  "researchers",
  "competitions",
  "competition",
]);

const NAMESPACES = new Set([
  "access",
  "account",
  "config",
  "decision",
  "draft",
  "eval",
  "evidence",
  "experiment",
  "github",
  "history",
  "hypothesis",
  "integration",
  "key",
  "label",
  "library",
  "link",
  "log",
  "map",
  "node",
  "note",
  "notebook",
  "ops",
  "optimize",
  "program",
  "project",
  "repo",
  "run",
  "secret",
  "usage",
  "web",
]);

// Pre-0.8 plural namespaces that must never come back as canonical names.
const BANNED_NAMESPACES = ["nodes", "labels", "keys", "secrets", "integrations", "projects", "runs", "evals"];

describe("CLI naming conventions", () => {
  it("every canonical name is bare-whitelisted or in an approved singular namespace", () => {
    for (const command of COMMANDS) {
      const { name } = command;
      if (!name.includes(":")) {
        assert.ok(
          BARE_COMMANDS.has(name),
          `bare command "${name}" is not whitelisted in cli/tests/conventions.test.mjs`,
        );
        continue;
      }
      const namespace = name.split(":")[0];
      assert.ok(
        NAMESPACES.has(namespace),
        `namespace "${namespace}:" (from "${name}") is not in the approved set`,
      );
      assert.ok(
        !BANNED_NAMESPACES.includes(namespace),
        `"${name}" uses a banned plural namespace`,
      );
    }
  });

  it("command names nest at most three levels", () => {
    for (const command of COMMANDS) {
      assert.ok(
        command.name.split(":").length <= 3,
        `"${command.name}" nests deeper than namespace:sub:verb`,
      );
    }
  });

  it("every pre-0.8 name still resolves through aliases", () => {
    const legacyNames = [
      "nodes:list",
      "nodes:show",
      "nodes:create",
      "nodes:save",
      "nodes:share",
      "nodes:delete",
      "labels:assign",
      "keys:list",
      "secrets:set",
      "integrations:status",
      "projects:merge",
      "runs:record",
      "runs:compare",
      "runs:spool:list",
      "runs:spool:flush",
      "runs:spool:clear",
      "github:refresh",
    ];
    for (const legacy of legacyNames) {
      const command = getCommand(legacy);
      assert.ok(command, `legacy name "${legacy}" no longer resolves`);
      assert.notEqual(
        command.name,
        legacy,
        `legacy name "${legacy}" is still canonical — it should be an alias`,
      );
    }
  });

  it("legacyAliasFor round-trips the rename table", () => {
    assert.equal(legacyAliasFor("node:list"), "nodes:list");
    assert.equal(legacyAliasFor("run:record"), "runs:record");
    assert.equal(legacyAliasFor("project:merge"), "projects:merge");
    assert.equal(legacyAliasFor("login"), null);
  });

  it("destructive commands stay flagged", () => {
    for (const name of ["node:delete", "node:delete-bulk", "run:spool:clear", "project:merge"]) {
      const command = getCommand(name);
      assert.ok(command, `${name} should exist`);
      assert.equal(command.destructive, true, `${name} must be destructive: true`);
    }
  });
});
