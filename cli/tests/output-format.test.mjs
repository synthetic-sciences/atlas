import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { _render } from "../src/atlas-runtime/output.mjs";
import { friendlyHttpError } from "../src/atlas-runtime/http-client.mjs";

// Strip ANSI escapes so assertions don't need to encode colour codes. The
// real renderer only emits colour when stdout is a TTY anyway; tests run
// under the node:test reporter which is non-TTY for the assertion process.
function stripAnsi(text) {
  // eslint-disable-next-line no-control-regex
  return String(text).replace(/\x1b\[[0-9;]*m/g, "");
}

describe("output --format=pretty per-command views", () => {
  it("renders node:list as a slug/title/kind table, not raw JSON", () => {
    const payload = {
      has_more: false,
      nodes: [
        {
          node_id: "11111111-1111-1111-1111-111111111111",
          slug_name: "able-helm-1359",
          title: "Project: problem-synsci",
          kind: "project",
          lifecycle: "staged",
          updated_at: new Date(Date.now() - 3600_000).toISOString(),
        },
      ],
    };
    const out = stripAnsi(_render(payload, "pretty", "node:list"));
    assert.match(out, /SLUG/);
    assert.match(out, /TITLE/);
    assert.match(out, /able-helm-1359/);
    assert.match(out, /Project: problem-synsci/);
    // The previous renderer dumped raw arrays — make sure we don't regress
    // by accidentally embedding raw JSON-stringified objects.
    assert.doesNotMatch(out, /"node_id":/);
    assert.match(out, /1 node/);
  });

  it("renders key:list with active/revoked state and counts", () => {
    const payload = {
      api_keys: [
        {
          name: "atlas-cli",
          key_prefix: "thk_aaaa",
          created_at: new Date(Date.now() - 86400_000 * 2).toISOString(),
          last_used_at: new Date(Date.now() - 3600_000).toISOString(),
        },
        {
          name: "old-key",
          key_prefix: "thk_bbbb",
          created_at: new Date(Date.now() - 86400_000 * 30).toISOString(),
          revoked_at: new Date(Date.now() - 86400_000).toISOString(),
        },
      ],
    };
    const out = stripAnsi(_render(payload, "pretty", "key:list"));
    assert.match(out, /atlas-cli/);
    assert.match(out, /old-key/);
    assert.match(out, /active/);
    assert.match(out, /revoked/);
    assert.match(out, /1 active · 1 revoked/);
  });

  it("renders usage:summary with tier and per-metric usage", () => {
    const payload = {
      subscription_tier: "startup",
      billing_period_start: "2026-06-01T00:00:00Z",
      billing_period_end: "2026-07-01T00:00:00Z",
      usage: {
        queries: { used: 12, limit: 5000, unlimited: false },
        deep_research: { used: 0, limit: 200, unlimited: false },
        package_search: { used: 5, limit: 0, unlimited: true },
      },
    };
    const out = stripAnsi(_render(payload, "pretty", "usage:summary"));
    assert.match(out, /startup/);
    assert.match(out, /queries\s+12 \/ 5000 \(0%\)/);
    assert.match(out, /package_search\s+5 \/ ∞/);
  });

  it("renders integration:status with EXPIRED tag for past dates", () => {
    const payload = {
      github: {
        connected: true,
        gh_username: "ada",
        token_kind: "oauth",
        token_expires_at: new Date(Date.now() - 86400_000).toISOString(),
      },
      wandb: { provider: "wandb", connected: false },
      huggingface: { provider: "huggingface", connected: false },
    };
    const out = stripAnsi(_render(payload, "pretty", "integration:status"));
    assert.match(out, /github/);
    assert.match(out, /EXPIRED/);
    assert.match(out, /wandb/);
    assert.match(out, /huggingface/);
  });

  it("renders map:summary with distributions, not a raw JSON dump", () => {
    const payload = {
      anchor_node_id: "11111111-1111-1111-1111-111111111111",
      root_node_ids: ["11111111-1111-1111-1111-111111111111"],
      node_count: 4,
      kind_counts: { project: 1, insight: 2, empirical: 1 },
      lifecycle_counts: { staged: 1, committed: 3 },
      outcome_counts: { completed: 3 },
      nodes: [
        {
          node_id: "11111111-1111-1111-1111-111111111111",
          slug_name: "able-helm-1359",
          title: "Project: foo",
          kind: "project",
        },
      ],
    };
    const out = stripAnsi(_render(payload, "pretty", "map:summary"));
    assert.match(out, /anchor\s+Project: foo \(able-helm-1359\)/);
    assert.match(out, /Kinds/);
    assert.match(out, /insight\s+2/);
    assert.match(out, /Outcomes/);
    assert.doesNotMatch(out, /"anchor_node_id":/);
  });

  it("renders map:tree as an indented hierarchy, not a flat table", () => {
    const payload = {
      anchor_node_id: "11111111-1111-1111-1111-111111111111",
      root_node_ids: ["11111111-1111-1111-1111-111111111111"],
      node_count: 3,
      nodes: [
        {
          node_id: "11111111-1111-1111-1111-111111111111",
          slug_name: "root",
          title: "Root",
          kind: "project",
          child_ids: ["22222222-2222-2222-2222-222222222222"],
        },
        {
          node_id: "22222222-2222-2222-2222-222222222222",
          slug_name: "leaf",
          title: "Leaf",
          kind: "insight",
          outcome: "completed",
          child_ids: [],
        },
      ],
    };
    const out = stripAnsi(_render(payload, "pretty", "map:tree"));
    assert.match(out, /Root/);
    // Indented child with a tree branch glyph.
    assert.match(out, /└─ ● Leaf/);
    assert.match(out, /2 nodes/);
  });

  it("renders run:compare with deltas vs. the baseline row and status glyphs", () => {
    const payload = {
      root_node_id: "11111111-1111-1111-1111-111111111111",
      cluster: "lr-sweep",
      columns: ["title", "config.lr", "metrics.val_loss", "outcome"],
      count: 3,
      rows: [
        { title: "baseline", "config.lr": 0.001, "metrics.val_loss": 2.30, outcome: "success" },
        { title: "lr=3e-4", "config.lr": 0.0003, "metrics.val_loss": 2.21, outcome: "success" },
        { title: "lr=1e-2 diverged", "config.lr": 0.01, "metrics.val_loss": 4.10, outcome: "failure" },
      ],
    };
    const out = stripAnsi(_render(payload, "pretty", "run:compare"));
    assert.match(out, /CONFIG\.LR/);
    assert.match(out, /METRICS\.VAL_LOSS/);
    // Baseline gets no delta annotation; non-baseline rows do.
    assert.match(out, /lr=3e-4/);
    assert.match(out, /\(-0\.090\)/);  // val_loss delta
    assert.match(out, /3 runs/);
    assert.match(out, /cluster=lr-sweep/);
  });

  it("falls back to a generic table for unknown commands without dumping raw JSON", () => {
    const payload = [
      { title: "alpha", kind: "project", updated_at: new Date().toISOString() },
      { title: "beta", kind: "experiment", updated_at: new Date().toISOString() },
    ];
    const out = stripAnsi(_render(payload, "pretty", "made-up:command"));
    assert.match(out, /TITLE/);
    assert.match(out, /alpha/);
    assert.match(out, /beta/);
    assert.doesNotMatch(out, /\[{"title"/);
  });
});

describe("friendlyHttpError translates backend leakage into actionable text", () => {
  it("turns asyncpg UUID errors into a clear hint", () => {
    const raw = JSON.stringify({
      detail:
        "invalid input for query argument $1: 'bogus' (invalid UUID 'bogus': length must be between 32..36 characters, got 5)",
    });
    const message = friendlyHttpError(400, raw, "node:show");
    assert.match(message, /Invalid ID format/);
    assert.match(message, /atlas node:list/);
    // The asyncpg internals must not leak through.
    assert.doesNotMatch(message, /query argument/);
    assert.doesNotMatch(message, /asyncpg/);
  });

  it("maps 401 to a login hint", () => {
    const message = friendlyHttpError(401, '{"detail":"missing key"}', "node:list");
    assert.match(message, /Not authenticated/);
    assert.match(message, /atlas login/);
  });

  it("maps 429 to a quota hint", () => {
    const message = friendlyHttpError(429, '{"detail":"slow down"}', "web:search");
    assert.match(message, /Rate limited/);
    assert.match(message, /usage:summary/);
  });

  it("maps opaque 503 to a retry hint without leaking trace text", () => {
    const message = friendlyHttpError(503, "Service Unavailable: trace=abc123", "doctor");
    assert.match(message, /Service unavailable/);
    assert.match(message, /Retry shortly/);
    // An opaque (non-structured) 5xx body must never reach the agent.
    assert.doesNotMatch(message, /trace=abc123/);
  });

  it("surfaces a structured 503 provider reason (e.g. not configured)", () => {
    const body = JSON.stringify({
      detail: { code: "provider_error", message: "the search service is not configured" },
    });
    const message = friendlyHttpError(503, body, "web:search");
    assert.match(message, /Service unavailable/);
    assert.match(message, /not configured/);
    assert.match(message, /web:search/);
  });

  it("surfaces a structured 5xx provider reason but hides opaque trace bodies", () => {
    const structured = friendlyHttpError(
      502,
      JSON.stringify({ detail: { code: "provider_error", message: "the search service is busy" } }),
      "web:search",
    );
    assert.match(structured, /HTTP 502/);
    assert.match(structured, /search service is busy/);

    const opaque = friendlyHttpError(500, '{"detail":"Internal Server Error"}', "web:search");
    assert.match(opaque, /backend error/);
    assert.doesNotMatch(opaque, /Internal Server Error/);
  });
});
