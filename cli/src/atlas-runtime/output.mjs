import { writeFile } from "node:fs/promises";

// ANSI escapes — gated behind ``shouldColor`` so non-TTY writers still get
// plain text. Pretty rendering uses dim/bold for hierarchy; we never colour
// values themselves because the user might pipe the output through ``less``
// or paste it elsewhere.
const ANSI = {
  reset: "[0m",
  bold: "[1m",
  dim: "[2m",
  red: "[31m",
  green: "[32m",
  yellow: "[33m",
  cyan: "[36m",
  gray: "[90m",
};

function shouldColor() {
  if (process.env.NO_COLOR) return false;
  if (process.env.FORCE_COLOR) return true;
  return Boolean(process.stdout.isTTY);
}

function paint(name, text) {
  if (!shouldColor()) return text;
  return `${ANSI[name] || ""}${text}${ANSI.reset}`;
}

function scalar(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function rowsFor(payload) {
  if (Array.isArray(payload)) return payload;
  if (payload && typeof payload === "object") {
    if (Array.isArray(payload.items)) return payload.items;
    return [payload];
  }
  return [{ value: payload }];
}

function columnsFor(rows) {
  return [...rows.reduce((set, row) => {
    Object.keys(row || {}).forEach((key) => set.add(key));
    return set;
  }, new Set())].sort((a, b) => a.localeCompare(b));
}

function csvEscape(value) {
  const text = scalar(value).replace(/\r?\n/g, " ");
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function renderDelimited(payload, delimiter) {
  const rows = rowsFor(payload);
  const columns = columnsFor(rows);
  const lines = [columns.join(delimiter)];
  for (const row of rows) {
    lines.push(columns.map((column) => scalar(row?.[column]).replace(/\r?\n/g, " ")).join(delimiter));
  }
  return `${lines.join("\n")}\n`;
}

function renderCsv(payload) {
  const rows = rowsFor(payload);
  const columns = columnsFor(rows);
  const lines = [columns.map(csvEscape).join(",")];
  for (const row of rows) {
    lines.push(columns.map((column) => csvEscape(row?.[column])).join(","));
  }
  return `${lines.join("\n")}\n`;
}

// --- Pretty-print helpers ----------------------------------------------------

// Trim long values to a column width, replace newlines with spaces, and add an
// ellipsis when truncated. Used by both the generic table renderer and the
// per-command views.
function clip(value, width) {
  const text = scalar(value).replace(/\r?\n/g, " ");
  if (text.length <= width) return text;
  return `${text.slice(0, Math.max(1, width - 1))}…`;
}

// Format an ISO timestamp as relative-ish ("3d ago" / "5m ago") for the
// most-common columns (created_at / updated_at / last_used_at). Falls back
// to the raw string if parsing fails.
function relativeTime(value) {
  if (!value) return "";
  const ts = Date.parse(String(value));
  if (!Number.isFinite(ts)) return String(value);
  const deltaSec = (Date.now() - ts) / 1000;
  if (deltaSec < 0) {
    const fwd = Math.abs(deltaSec);
    if (fwd < 60) return "in <1m";
    if (fwd < 3600) return `in ${Math.round(fwd / 60)}m`;
    if (fwd < 86400) return `in ${Math.round(fwd / 3600)}h`;
    return `in ${Math.round(fwd / 86400)}d`;
  }
  if (deltaSec < 60) return "just now";
  if (deltaSec < 3600) return `${Math.round(deltaSec / 60)}m ago`;
  if (deltaSec < 86400) return `${Math.round(deltaSec / 3600)}h ago`;
  if (deltaSec < 86400 * 30) return `${Math.round(deltaSec / 86400)}d ago`;
  if (deltaSec < 86400 * 365) return `${Math.round(deltaSec / 86400 / 30)}mo ago`;
  return `${Math.round(deltaSec / 86400 / 365)}y ago`;
}

function shortId(value, keep = 8) {
  const text = scalar(value);
  if (text.length <= keep + 1) return text;
  return text.slice(0, keep);
}

// Render an array of objects as an aligned text table. ``columns`` is
// ``[{ key, label, width?, render?(row) }]``. ``render`` lets per-command
// views compute virtual fields (e.g. ``last_used`` as ``relativeTime``).
function renderColumnTable(rows, columns) {
  if (!rows.length) return paint("dim", "(no rows)\n");
  const resolved = rows.map((row) =>
    columns.map((col) => (col.render ? col.render(row) : scalar(row?.[col.key])).toString()),
  );
  const widths = columns.map((col, idx) => {
    const headerWidth = col.label.length;
    const max = col.width || 60;
    const dataMax = resolved.reduce((acc, cells) => Math.max(acc, cells[idx].length), 0);
    return Math.min(max, Math.max(headerWidth, dataMax));
  });
  const header = columns
    .map((col, idx) => paint("bold", col.label.padEnd(widths[idx])))
    .join("  ");
  const divider = paint("dim", widths.map((w) => "─".repeat(w)).join("  "));
  const body = resolved
    .map((cells) => cells.map((cell, idx) => clip(cell, widths[idx]).padEnd(widths[idx])).join("  ").trimEnd())
    .join("\n");
  return `${header}\n${divider}\n${body}\n`;
}

function renderKeyValue(entries) {
  if (!entries.length) return paint("dim", "(empty)\n");
  const labelWidth = Math.max(...entries.map(([k]) => k.length));
  return `${entries
    .map(([k, v]) => `${paint("dim", k.padEnd(labelWidth))}  ${v}`)
    .join("\n")}\n`;
}

function statusGlyph(status) {
  const text = String(status || "").toLowerCase();
  if (["ok", "completed", "indexed", "success", "active"].includes(text)) return paint("green", "●");
  if (["error", "failed", "failure", "revoked"].includes(text)) return paint("red", "●");
  if (["pending", "running", "queued", "staged"].includes(text)) return paint("yellow", "●");
  return paint("dim", "·");
}

// --- Per-command view registry ----------------------------------------------

// Each formatter receives the raw API response and returns a string. Returning
// ``null`` falls back to the generic table renderer. The registry is keyed by
// command name so dispatch.mjs can opt into a view without payloads needing a
// magic field.
const VIEWS = {
  // ── public discovery ──────────────────────────────────────────────
  competitions: (payload) => {
    const rows = Array.isArray(payload?.competitions) ? payload.competitions : [];
    if (!rows.length) return paint("dim", "(no competitions)\n");
    const table = renderColumnTable(rows, [
      { key: "status", label: "", width: 2, render: (r) => statusGlyph(r.status === "live" ? "active" : r.status === "upcoming" ? "pending" : "·") },
      { key: "title", label: "COMPETITION", width: 34 },
      { key: "metric_label", label: "METRIC", width: 18, render: (r) => `${r.metric_goal === "min" ? "↓" : "↑"} ${r.metric_label || ""}` },
      { key: "entry_count", label: "ENTRIES", width: 7 },
      { key: "host_org", label: "HOST", width: 13 },
      { key: "leader", label: "LEADER", width: 14, render: (r) => (r.leader ? `@${r.leader.handle}` : "—") },
      { key: "slug", label: "SLUG", width: 24 },
    ]);
    return `${table}${paint("dim", `\n${rows.length} competition${rows.length === 1 ? "" : "s"} · atlas competition <slug>\n`)}`;
  },
  competition: (payload) => {
    if (!payload?.slug) return null;
    const head = [paint("bold", payload.title || payload.slug)];
    if (payload.summary) head.push(paint("dim", payload.summary));
    head.push("");
    head.push(renderKeyValue([
      ["status", String(payload.status || "")],
      ["metric", `${payload.metric_goal === "min" ? "↓ lower wins" : "↑ higher wins"} · ${payload.metric_label || ""}`],
      ["dataset", payload.dataset || "—"],
      ["constraint", payload.constraint_text || "—"],
      ["prize", payload.prize || "—"],
    ]));
    head.push("");
    const lb = Array.isArray(payload.leaderboard) ? payload.leaderboard : [];
    if (!lb.length) return `${head.join("\n")}${paint("dim", "(no entries yet)\n")}`;
    const table = renderColumnTable(lb, [
      { key: "rank", label: "#", width: 4, render: (r) => (r.rank <= 3 ? ["1st", "2nd", "3rd"][r.rank - 1] : String(r.rank)) },
      { key: "researcher", label: "RESEARCHER", width: 16, render: (r) => `@${r.researcher?.handle || "?"}` },
      { key: "score", label: (payload.metric_label || "SCORE").toUpperCase(), width: 12, render: (r) => (r.score == null ? "—" : String(r.score)) },
      { key: "graph", label: "GRAPH", width: 38, render: (r) => r.graph?.title || "—" },
    ]);
    return `${head.join("\n")}${table}\n`;
  },
  explore: (payload) => {
    const rows = Array.isArray(payload?.graphs) ? payload.graphs : [];
    if (!rows.length) return paint("dim", "(no graphs)\n");
    const table = renderColumnTable(rows, [
      { key: "title", label: "GRAPH", width: 42 },
      { key: "author", label: "AUTHOR", width: 15, render: (r) => `@${r.author?.handle || "?"}` },
      { key: "star_count", label: "★", width: 5 },
      { key: "fork_count", label: "FORKS", width: 6 },
      { key: "node_count", label: "NODES", width: 6 },
      { key: "node_id", label: "ID", width: 24 },
    ]);
    return `${table}${paint("dim", `\n${payload.total ?? rows.length} graph${(payload.total ?? rows.length) === 1 ? "" : "s"}\n`)}`;
  },
  researchers: (payload) => {
    const rows = Array.isArray(payload?.researchers) ? payload.researchers : [];
    if (!rows.length) return paint("dim", "(no researchers — add --query to search)\n");
    const table = renderColumnTable(rows, [
      { key: "handle", label: "HANDLE", width: 20, render: (r) => `@${r.handle}` },
      { key: "display_name", label: "NAME", width: 24 },
      { key: "public_graph_count", label: "GRAPHS", width: 8 },
    ]);
    return `${table}${paint("dim", `\n${payload.total ?? rows.length} researcher${(payload.total ?? rows.length) === 1 ? "" : "s"}\n`)}`;
  },
  "node:list": (payload) => {
    const rows = Array.isArray(payload?.nodes) ? payload.nodes : [];
    if (!rows.length) return paint("dim", "(no nodes)\n");
    const table = renderColumnTable(rows, [
      { key: "slug_name", label: "SLUG", width: 24 },
      { key: "title", label: "TITLE", width: 50 },
      { key: "kind", label: "KIND", width: 12 },
      { key: "lifecycle", label: "LIFECYCLE", width: 10 },
      { key: "updated_at", label: "UPDATED", width: 14, render: (row) => relativeTime(row.updated_at) },
    ]);
    let footer;
    if (payload?.has_more) {
      // Surface the actual next-page cursor when the route returns one so
      // the user can copy-paste the next command directly. Fall back to a
      // generic hint when only ``page``-style pagination is in use.
      const cursor = payload.next_cursor || payload.cursor || null;
      const tip = cursor
        ? `next page: --cursor=${cursor}`
        : "more available (use --cursor or --per-page)";
      footer = paint("dim", `\n${rows.length} shown · ${tip}\n`);
    } else {
      footer = paint("dim", `\n${rows.length} node${rows.length === 1 ? "" : "s"}\n`);
    }
    return `${table}${footer}`;
  },

  "key:list": (payload) => {
    const rows = Array.isArray(payload?.api_keys) ? payload.api_keys : [];
    if (!rows.length) return paint("dim", "(no API keys)\n");
    const table = renderColumnTable(rows, [
      {
        key: "active",
        label: " ",
        width: 1,
        render: (row) => (row.revoked_at ? paint("dim", "·") : paint("green", "●")),
      },
      { key: "name", label: "NAME", width: 32 },
      { key: "key_prefix", label: "PREFIX", width: 14 },
      {
        key: "created_at",
        label: "CREATED",
        width: 14,
        render: (row) => relativeTime(row.created_at),
      },
      {
        key: "last_used_at",
        label: "LAST USED",
        width: 14,
        render: (row) => (row.last_used_at ? relativeTime(row.last_used_at) : paint("dim", "—")),
      },
      {
        key: "state",
        label: "STATE",
        width: 10,
        render: (row) => (row.revoked_at ? paint("red", "revoked") : paint("green", "active")),
      },
    ]);
    const active = rows.filter((row) => !row.revoked_at).length;
    const footer = paint("dim", `\n${active} active · ${rows.length - active} revoked\n`);
    return `${table}${footer}`;
  },

  "usage:summary": (payload) => {
    const usage = payload?.usage || {};
    const warnings = [];
    const entries = Object.entries(usage).map(([metric, info]) => {
      const used = info?.used ?? 0;
      const limit = info?.unlimited ? "∞" : (info?.limit ?? "—");
      if (info?.unlimited || !info?.limit) {
        return [metric, `${used} / ${limit}`];
      }
      const pct = Math.round((used / info.limit) * 100);
      // ``yellow`` at 80%, ``red`` at 100%+ so the alert lands at-a-glance
      // without changing the underlying number formatting.
      let pctStr = `(${pct}%)`;
      if (pct >= 100) {
        pctStr = paint("red", `(${pct}% — OVER)`);
        warnings.push(`${metric} is OVER quota (${used}/${info.limit}).`);
      } else if (pct >= 80) {
        pctStr = paint("yellow", `(${pct}%)`);
        warnings.push(`${metric} at ${pct}% (${used}/${info.limit}).`);
      }
      return [metric, `${used} / ${limit} ${pctStr}`];
    });
    const header = renderKeyValue([
      ["tier", paint("cyan", payload?.subscription_tier || "?")],
      ["period", `${payload?.billing_period_start?.slice(0, 10) || "?"} → ${payload?.billing_period_end?.slice(0, 10) || "?"}`],
    ]);
    let out = `${header}\n${paint("bold", "Usage")}\n${renderKeyValue(entries)}`;
    if (warnings.length) {
      out += `\n${paint("bold", "Alerts")}\n${warnings.map((w) => `  ${paint("yellow", "⚠")} ${w}`).join("\n")}\n`;
    }
    return out;
  },

  whoami: (payload) => {
    if (!payload?.authenticated) return paint("red", "Not authenticated. Run `atlas login`.\n");
    const user = payload.user || {};
    const key = payload.api_key || {};
    return renderKeyValue([
      ["email", user.email || ""],
      ["name", user.full_name || user.display_name || ""],
      ["user_id", user.user_id || ""],
      ["github", user.github_username || paint("dim", "(not linked)")],
      ["api_key", key.name ? `${key.name} (${shortId(key.key_id)}…)` : paint("dim", "(none)")],
    ]);
  },

  "integration:status": (payload) => {
    const rows = [];
    const gh = payload?.github || {};
    rows.push({
      provider: "github",
      connected: gh.connected,
      detail: gh.connected
        ? `${gh.gh_username || "?"} (${gh.token_kind || "?"})`
        : "not connected",
      expires: gh.token_expires_at || null,
    });
    for (const key of ["wandb", "huggingface"]) {
      const info = payload?.[key] || {};
      rows.push({
        provider: info.provider || key,
        connected: info.connected,
        detail: info.connected ? "active" : "not connected",
        expires: null,
      });
    }
    return renderColumnTable(rows, [
      {
        key: "connected",
        label: " ",
        width: 1,
        render: (row) => (row.connected ? paint("green", "●") : paint("dim", "·")),
      },
      { key: "provider", label: "PROVIDER", width: 14 },
      { key: "detail", label: "STATUS", width: 36 },
      {
        key: "expires",
        label: "EXPIRES",
        width: 18,
        render: (row) => {
          if (!row.expires) return paint("dim", "—");
          const ts = Date.parse(row.expires);
          if (Number.isFinite(ts) && ts < Date.now()) {
            return paint("red", `EXPIRED ${relativeTime(row.expires)}`);
          }
          return relativeTime(row.expires);
        },
      },
    ]);
  },

  "run:compare": (payload) => {
    const rows = Array.isArray(payload?.rows) ? payload.rows : [];
    const columns = Array.isArray(payload?.columns) ? payload.columns : [];
    if (!rows.length || !columns.length) return paint("dim", "(no rows)\n");
    // Detect numeric columns so we can highlight min/max + annotate deltas
    // against the first row (the natural baseline when runs are listed in
    // creation order). Non-numeric cells render as-is.
    const numericIdx = new Set();
    const colNumbers = columns.map((col) => {
      const values = rows.map((r) => Number(r[col]));
      const allFinite = values.every((v) => Number.isFinite(v));
      return allFinite ? values : null;
    });
    columns.forEach((col, i) => { if (colNumbers[i]) numericIdx.add(i); });

    // For each numeric column find min / max so we can colour winners.
    const stats = columns.map((_, i) => {
      if (!numericIdx.has(i)) return null;
      const nums = colNumbers[i];
      return { min: Math.min(...nums), max: Math.max(...nums) };
    });

    const cellRender = (val, colIdx, rowIdx) => {
      if (val === null || val === undefined || val === "") return "";
      if (numericIdx.has(colIdx)) {
        const num = colNumbers[colIdx][rowIdx];
        const s = stats[colIdx];
        let text = String(val);
        if (s && s.min !== s.max) {
          if (num === s.min) text = paint("green", text);
          else if (num === s.max) text = paint("red", text);
        }
        // Delta vs. first row (baseline). Skip for the baseline itself.
        if (rowIdx > 0 && Number.isFinite(colNumbers[colIdx][0])) {
          const delta = num - colNumbers[colIdx][0];
          if (delta !== 0) {
            const sign = delta > 0 ? "+" : "";
            text += paint("dim", ` (${sign}${delta.toFixed(Math.abs(delta) < 1 ? 3 : 2)})`);
          }
        }
        return text;
      }
      if (colIdx === columns.indexOf("outcome")) {
        return `${statusGlyph(val)} ${val}`;
      }
      return String(val);
    };

    const cols = columns.map((col, i) => ({
      key: col,
      label: col.toUpperCase(),
      width: i === 0 ? 36 : 22,
      render: (row) => cellRender(row[col], i, rows.indexOf(row)),
    }));
    const table = renderColumnTable(rows, cols);
    const meta = [
      payload.root_node_id ? `root=${shortId(payload.root_node_id)}` : null,
      payload.cluster ? `cluster=${payload.cluster}` : null,
      `${payload.count ?? rows.length} run${(payload.count ?? rows.length) === 1 ? "" : "s"}`,
    ].filter(Boolean).join(" · ");
    return `${table}${paint("dim", `\n${meta}\n`)}`;
  },

  "node:show": (payload) => {
    if (!payload || typeof payload !== "object") return null;
    const entries = [
      [paint("bold", "title"), payload.title || paint("dim", "(untitled)")],
      ["slug", payload.slug_name || paint("dim", "—")],
      ["id", shortId(payload.node_id, 12)],
      ["kind", payload.kind || ""],
      ["lifecycle", payload.lifecycle || ""],
      ["outcome", payload.outcome ? `${statusGlyph(payload.outcome)} ${payload.outcome}` : paint("dim", "—")],
      ["updated", `${relativeTime(payload.updated_at)}  ${paint("dim", `by ${payload.updated_by || "?"}`)}`],
    ];
    let out = renderKeyValue(entries);
    const summary = (payload.summary || "").trim();
    if (summary) out += `\n${paint("bold", "Summary")}\n${summary}\n`;
    const hypothesis = (payload.hypothesis || "").trim();
    if (hypothesis) out += `\n${paint("bold", "Hypothesis")}\n${hypothesis}\n`;
    const insights = Array.isArray(payload.insights) ? payload.insights : [];
    if (insights.length) {
      out += `\n${paint("bold", "Insights")}\n${insights.map((i) => `  • ${i}`).join("\n")}\n`;
    }
    const children = Array.isArray(payload.child_ids) ? payload.child_ids.length : 0;
    const parents = Array.isArray(payload.parent_ids) ? payload.parent_ids.length : 0;
    out += `\n${paint("dim", `parents=${parents} · children=${children} · rev=${payload.revision ?? "?"}`)}\n`;
    return out;
  },

  "run:spool:list": (payload) => {
    const entries = Array.isArray(payload?.entries) ? payload.entries : [];
    if (!entries.length) {
      return `${paint("dim", `(spool empty — ${payload?.spool_dir || ""})`)}\n`;
    }
    const table = renderColumnTable(entries, [
      { key: "spooled_at", label: "QUEUED", width: 14, render: (row) => relativeTime(row.spooled_at) },
      { key: "route", label: "ROUTE", width: 24 },
      { key: "title", label: "TITLE", width: 42, render: (row) => row.title || paint("dim", "(no title)") },
      { key: "project_id", label: "PROJECT", width: 12, render: (row) => row.project_id ? shortId(row.project_id) : paint("dim", "—") },
      { key: "size_bytes", label: "BYTES", width: 8 },
    ]);
    return `${table}${paint("dim", `\n${payload.count || entries.length} queued in ${payload.spool_dir}\n`)}`;
  },

  "brief": (payload) => {
    if (!payload || typeof payload !== "object") return null;
    const project = payload.project || {};
    const lines = [];
    lines.push(`${paint("bold", project.title || "project")} ${paint("dim", `(${project.node_id ? shortId(project.node_id, 12) : "?"})`)}`);
    const section = (label, rows, render) => {
      if (!Array.isArray(rows) || !rows.length) return;
      lines.push("", paint("bold", label));
      for (const row of rows) lines.push(`  ${render(row)}`);
    };
    section("Hypotheses", payload.hypotheses, (h) => {
      const tested = h.tested_by ? `tested by ${h.tested_by}` : "untested";
      return `[${h.status || "proposed"}] ${h.claim || h.title || ""} ${paint("dim", `(${tested})`)}`;
    });
    section("Recent runs", payload.recent_runs, (r) => {
      const crit = r.criterion_met === true ? "  criterion: met" : r.criterion_met === false ? "  criterion: MISSED" : "";
      return `${statusGlyph(r.outcome)} ${r.title || ""}${paint("dim", `${crit}  ${relativeTime(r.created_at)}`)}`;
    });
    section("Failure clusters", payload.failures, (f) => `${f.mode || f.failure_mode || "?"}  x${f.count ?? "?"}`);
    section("Decisions", payload.decisions, (d) => `${d.title || d.decision || ""} ${paint("dim", `(${d.confidence || "?"}, ${relativeTime(d.created_at)})`)}`);
    section("Open branches", payload.open_branches, (b) => `${b.title || ""} ${paint("dim", relativeTime(b.updated_at || b.created_at))}`);
    section("Suggested next", payload.suggested_next, (s) => {
      const reason = s && typeof s === "object" ? s.reason || "" : String(s);
      const command = s && typeof s === "object" && s.command ? `\n      ${paint("dim", s.command)}` : "";
      return `${reason}${command}`;
    });
    lines.push("");
    return lines.join("\n");
  },

  "map:summary": (payload) => {
    if (!payload || typeof payload !== "object") return null;
    const nodes = Array.isArray(payload.nodes) ? payload.nodes : [];
    const anchor = nodes.find((n) => n.node_id === payload.anchor_node_id) || null;
    const header = renderKeyValue([
      ["anchor", anchor ? `${anchor.title || anchor.slug_name || ""} ${paint("dim", `(${anchor.slug_name || shortId(payload.anchor_node_id)})`)}` : shortId(payload.anchor_node_id, 12)],
      ["roots", String((payload.root_node_ids || []).length)],
      ["nodes", String(payload.node_count ?? nodes.length)],
    ]);
    const distRows = (label, counts) => {
      const entries = Object.entries(counts || {}).sort((a, b) => b[1] - a[1]);
      if (!entries.length) return "";
      return `\n${paint("bold", label)}\n${renderKeyValue(entries.map(([k, v]) => [k, String(v)]))}`;
    };
    return [
      header,
      distRows("Kinds", payload.kind_counts),
      distRows("Lifecycle", payload.lifecycle_counts),
      distRows("Outcomes", payload.outcome_counts),
    ].filter(Boolean).join("");
  },

  "map:tree": (payload) => {
    if (!payload || typeof payload !== "object") return null;
    const nodes = Array.isArray(payload.nodes) ? payload.nodes : [];
    if (!nodes.length) return paint("dim", "(empty tree)\n");
    // Build child -> [parents] / node-by-id maps. The wire shape includes
    // parent_ids on every node, so walk roots first and recurse via child_ids
    // (also present) for stable ordering.
    const byId = new Map(nodes.map((n) => [n.node_id, n]));
    const roots = (payload.root_node_ids || [])
      .map((id) => byId.get(id))
      .filter(Boolean);
    const lines = [];
    const seen = new Set();
    function walk(node, prefix, isLast, depth) {
      if (!node || seen.has(node.node_id)) return;
      seen.add(node.node_id);
      // Roots render flush-left (no branch); descendants get ├─ / └─ glyphs.
      const branch = depth === 0 ? "" : (isLast ? "└─ " : "├─ ");
      const glyph = node.outcome ? `${statusGlyph(node.outcome)} ` : "";
      const slug = node.slug_name ? paint("dim", `[${node.slug_name}]`) : "";
      const title = clip(node.title || "(untitled)", 60);
      const kind = node.kind ? paint("dim", `· ${node.kind}`) : "";
      lines.push(`${prefix}${branch}${glyph}${title} ${kind} ${slug}`.trimEnd());
      const children = (node.child_ids || [])
        .map((id) => byId.get(id))
        .filter(Boolean);
      // Continuation prefix: spaces under the parent's branch-corner, or a
      // pipe to keep the trunk visible for non-last siblings. Roots use "".
      const nextPrefix = prefix + (depth === 0 ? "" : (isLast ? "   " : "│  "));
      children.forEach((child, i) =>
        walk(child, nextPrefix, i === children.length - 1, depth + 1),
      );
    }
    roots.forEach((root, i) => walk(root, "", i === roots.length - 1, 0));
    return `${lines.join("\n")}\n${paint("dim", `\n${nodes.length} node${nodes.length === 1 ? "" : "s"}\n`)}`;
  },

  "evidence:list": (payload) => {
    const rows = Array.isArray(payload?.artifacts || payload) ? (payload?.artifacts || payload) : [];
    if (!rows.length) return paint("dim", "(no evidence)\n");
    return renderColumnTable(rows, [
      { key: "artifact_id", label: "ID", width: 10, render: (row) => shortId(row.artifact_id || row.id) },
      { key: "title", label: "TITLE", width: 40, render: (row) => row.title || paint("dim", "(no title)") },
      { key: "artifact_type", label: "TYPE", width: 12 },
      {
        key: "size_bytes",
        label: "SIZE",
        width: 8,
        render: (row) => {
          const n = Number(row.size_bytes || row.bytes || 0);
          if (!n) return paint("dim", "—");
          if (n < 1024) return `${n}B`;
          if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)}K`;
          return `${(n / 1024 / 1024).toFixed(1)}M`;
        },
      },
      { key: "created_at", label: "CREATED", width: 14, render: (row) => relativeTime(row.created_at) },
    ]);
  },

  "evidence:show": (payload) => {
    if (!payload || typeof payload !== "object") return null;
    const a = payload.artifact || payload;
    const entries = [
      [paint("bold", "title"), a.title || paint("dim", "(no title)")],
      ["id", shortId(a.artifact_id || a.id, 12)],
      ["type", a.artifact_type || ""],
      ["media", a.media_type || paint("dim", "—")],
      ["size", a.size_bytes ? `${a.size_bytes} bytes` : paint("dim", "—")],
      ["created", relativeTime(a.created_at)],
      ["node", shortId(a.node_id, 12)],
    ];
    if (a.storage_path) entries.push(["path", paint("dim", a.storage_path)]);
    if (a.url) entries.push(["url", a.url]);
    let out = renderKeyValue(entries);
    const note = (a.note || "").trim();
    if (note) out += `\n${paint("bold", "Note")}\n${note}\n`;
    return out;
  },

  "project:list": (payload) => {
    const rows = Array.isArray(payload?.nodes) ? payload.nodes : [];
    if (!rows.length) {
      return paint("dim", "(no projects yet — bootstrap one with `atlas project:create`)\n");
    }
    return renderColumnTable(rows, [
      { key: "slug_name", label: "SLUG", width: 24 },
      { key: "title", label: "TITLE", width: 50 },
      {
        key: "node_id",
        label: "ID",
        width: 12,
        render: (row) => shortId(row.node_id),
      },
      { key: "updated_at", label: "UPDATED", width: 14, render: (row) => relativeTime(row.updated_at) },
    ]);
  },

  doctor: (payload) => {
    const spoolPending = payload?.spool?.pending ?? 0;
    const entries = [
      ["profile", payload?.profile || "?"],
      ["base_url", payload?.base_url || ""],
      ["config", payload?.config_path || ""],
      ["", ""],
      [paint("bold", "auth"), payload?.auth?.ok ? paint("green", "ok") : paint("red", "fail")],
      [paint("bold", "backend"), payload?.backend?.ok ? paint("green", "ok") : paint("red", "fail")],
      [paint("bold", "spool"), spoolPending === 0 ? paint("green", "empty") : paint("yellow", `${spoolPending} pending`)],
    ];
    const warnings = Array.isArray(payload?.warnings) ? payload.warnings : [];
    let body = renderKeyValue(entries);
    if (warnings.length) {
      body += `\n${paint("bold", "Warnings")}\n`;
      for (const w of warnings) body += `  ${paint("yellow", "⚠")} ${w}\n`;
    }
    const ok = payload?.ok && !warnings.length;
    body += `\n${ok ? paint("green", "All checks passed.") : paint("yellow", "Issues detected — see above.")}\n`;
    return body;
  },
};

// --- Generic fallback --------------------------------------------------------

// Default "table" view: drop UUID / metadata columns, truncate the rest. Used
// when there's no per-command view in VIEWS and the payload is array-shaped.
const GENERIC_COLUMN_PRIORITY = [
  "slug_name",
  "title",
  "name",
  "display_name",
  "kind",
  "type",
  "status",
  "outcome",
  "lifecycle",
  "summary",
  "updated_at",
  "created_at",
];
const GENERIC_COLUMN_SKIP = new Set([
  "content",
  "metadata",
  "graph_tags",
  "tag_history",
  "insights",
  "parent_ids",
  "child_ids",
  "tag_ids",
  "graph_projection",
  "external_transcript_ref",
  "no_artifacts_reason",
  "origin_host",
  "head_commit_sha",
]);

function pickGenericColumns(rows) {
  const seen = columnsFor(rows);
  const picked = [];
  for (const candidate of GENERIC_COLUMN_PRIORITY) {
    if (seen.includes(candidate)) picked.push(candidate);
    if (picked.length >= 5) break;
  }
  if (picked.length < 5) {
    for (const col of seen) {
      if (picked.includes(col) || GENERIC_COLUMN_SKIP.has(col)) continue;
      // Drop columns that are entirely JSON-shaped (always objects/arrays).
      const allComplex = rows.every((row) => {
        const v = row?.[col];
        return v && typeof v === "object";
      });
      if (allComplex) continue;
      picked.push(col);
      if (picked.length >= 5) break;
    }
  }
  return picked.length ? picked : seen.slice(0, 5);
}

function renderGenericTable(payload) {
  const rows = rowsFor(payload);
  if (!rows.length) return paint("dim", "(empty)\n");
  if (rows.length === 1 && (!Array.isArray(payload) && payload && typeof payload === "object")) {
    return renderGenericObject(payload);
  }
  const cols = pickGenericColumns(rows);
  return renderColumnTable(
    rows,
    cols.map((key) => ({
      key,
      label: key.toUpperCase(),
      width: 40,
      render: (row) => {
        const v = row?.[key];
        if (key === "created_at" || key === "updated_at" || key === "last_used_at") return relativeTime(v);
        if (v && typeof v === "object") return JSON.stringify(v);
        return scalar(v);
      },
    })),
  );
}

function renderGenericObject(payload) {
  const entries = Object.entries(payload || {}).map(([k, v]) => {
    if (v === null || v === undefined) return [k, paint("dim", "—")];
    if (Array.isArray(v)) return [k, paint("dim", `[${v.length} item${v.length === 1 ? "" : "s"}]`)];
    if (typeof v === "object") return [k, paint("dim", `{${Object.keys(v).length} field${Object.keys(v).length === 1 ? "" : "s"}}`)];
    return [k, scalar(v)];
  });
  return renderKeyValue(entries);
}

function renderPretty(payload, commandName) {
  const view = commandName ? VIEWS[commandName] : null;
  if (view) {
    try {
      const out = view(payload);
      if (typeof out === "string") return out.endsWith("\n") ? out : `${out}\n`;
    } catch {
      // fall through to generic
    }
  }
  if (payload === null || payload === undefined) return "(no output)\n";
  if (Array.isArray(payload)) return renderGenericTable(payload);
  if (typeof payload === "object") {
    // Single-object responses with a top-level list field that's likely the
    // "interesting" data — table that instead of dumping the wrapper.
    for (const key of ["nodes", "sources", "items", "results", "rows", "data"]) {
      if (Array.isArray(payload[key])) return renderGenericTable(payload[key]);
    }
    return renderGenericObject(payload);
  }
  return `${String(payload)}\n`;
}

// Backwards-compatible table renderer (kept for ``--format=table``).
function renderTable(payload, commandName) {
  return renderPretty(payload, commandName);
}

// --- emit() ------------------------------------------------------------------

export async function emit(payload, format = "json", out = null, commandName = null) {
  let rendered;
  if (Buffer.isBuffer(payload) || payload instanceof Uint8Array) {
    if (!out || out === "-") {
      process.stdout.write(payload);
      return;
    }
    await writeFile(out, payload);
    return;
  }
  if (typeof payload === "string") rendered = payload.endsWith("\n") ? payload : `${payload}\n`;
  else if (format === "tsv") rendered = renderDelimited(payload, "\t");
  else if (format === "csv") rendered = renderCsv(payload);
  else if (format === "pretty") rendered = renderPretty(payload, commandName);
  else if (format === "table") rendered = renderTable(payload, commandName);
  else rendered = `${JSON.stringify(payload)}\n`;

  if (out && out !== "-") await writeFile(out, rendered, "utf8");
  else process.stdout.write(rendered);
}

// Exported for tests that want to render without writing to stdout.
export function _render(payload, format, commandName) {
  if (format === "pretty") return renderPretty(payload, commandName);
  if (format === "table") return renderTable(payload, commandName);
  if (format === "tsv") return renderDelimited(payload, "\t");
  if (format === "csv") return renderCsv(payload);
  return `${JSON.stringify(payload)}\n`;
}
