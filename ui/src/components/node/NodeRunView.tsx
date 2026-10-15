import { useEffect, useMemo, useState } from "react";
import type { Artifact } from "../../api/types.js";
import { MarkdownRenderer } from "../shared/MarkdownRenderer.js";
import { fetchArtifactText } from "../../lib/artifactContent.js";
import { FONT_MONO as mono, FONT_SANS as sans } from "../../styles/tokens.js";

/**
 * NodeRunView — status banner + tabbed body (Result · Logs · Details).
 *
 * The banner says ONE word — the run's state (success / running / failure /
 * error, or draft pre-run). All the detail lives in the tabs: Result renders
 * the run's RESULTS, Logs renders the transcript, Details holds the authored
 * summary / content / hypothesis (passed in as ``details``).
 */

type RunStatus = "success" | "failure" | "error" | "draft";
type TabKey = "result" | "logs" | "details";

interface ResolvedArtifact {
  title: string;
  body: string | null;
  isJson: boolean;
}

function pickByName(arts: Artifact[], patterns: RegExp[]): Artifact | null {
  const name = (a: Artifact) => (a.title || a.filename || "").toLowerCase();
  for (const re of patterns) {
    const hit = arts.find((a) => re.test(name(a)));
    if (hit) return hit;
  }
  return null;
}

/** Resolve the result + log bodies from the artifacts already on the full node. */
function useRunArtifacts(artifacts: Artifact[]): {
  result: ResolvedArtifact | null;
  logs: ResolvedArtifact | null;
  loading: boolean;
} {
  const [result, setResult] = useState<ResolvedArtifact | null>(null);
  const [logs, setLogs] = useState<ResolvedArtifact | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    const resultArt = pickByName(artifacts, [
      /^results?\.md$/,
      /^results?\.(json|txt)$/,
      /^results?\b/,
    ]);
    const logArt = pickByName(artifacts, [
      /transcript\.(jsonl|ndjson|log|txt)$/,
      /\.(jsonl|ndjson|log)$/,
      /transcript|stdout|run.?log/,
    ]);
    Promise.all([
      resultArt ? fetchArtifactText(resultArt) : Promise.resolve(null),
      logArt ? fetchArtifactText(logArt) : Promise.resolve(null),
    ])
      .then(([resBody, logBody]) => {
        if (!alive) return;
        setResult(
          resultArt
            ? {
                title: resultArt.title || resultArt.filename || "result",
                body: resBody,
                isJson: /\.json$/.test(
                  (resultArt.title || resultArt.filename || "").toLowerCase(),
                ),
              }
            : null,
        );
        setLogs(
          logArt
            ? { title: logArt.title || logArt.filename || "logs", body: logBody, isJson: false }
            : null,
        );
        setLoading(false);
      })
      .catch(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [artifacts]);

  return { result, logs, loading };
}

/** Derive the one-word status from the durable recorded outcome. */
function runStatus(outcome: string | null, staged: boolean): RunStatus {
  if (outcome === "completed") return "success";
  if (outcome === "failed") return "failure";
  if (outcome === "canceled") return "error";
  return staged ? "draft" : "draft";
}

const STATUS_STYLE: Record<RunStatus, { label: string; fg: string; bg: string }> = {
  success: { label: "success", fg: "var(--color-success)", bg: "var(--color-success-muted)" },
  failure: { label: "failure", fg: "var(--color-error)", bg: "var(--color-error-muted)" },
  error: { label: "error", fg: "var(--color-warning)", bg: "var(--color-warning-muted)" },
  draft: { label: "draft", fg: "var(--color-text-muted)", bg: "var(--color-accent-subtle)" },
};

function StatusBanner({ status }: { status: RunStatus }) {
  const s = STATUS_STYLE[status];
  return (
    <div style={{ display: "flex", alignItems: "center", marginBottom: 16 }}>
      <span
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 7,
          padding: "5px 12px",
          borderRadius: 3,
          background: s.bg,
          border: `1px solid ${s.fg}`,
          fontFamily: mono,
          fontSize: 11,
          fontWeight: 700,
          letterSpacing: "0.1em",
          color: s.fg,
        }}
      >
        <span
          style={{
            width: 7,
            height: 7,
            borderRadius: "50%",
            background: s.fg,
          }}
        />
        {s.label}
      </span>
    </div>
  );
}

function Panel({
  loading,
  art,
  emptyText,
}: {
  loading: boolean;
  art: ResolvedArtifact | null;
  emptyText: string;
}) {
  if (loading) {
    return <p style={{ fontFamily: mono, fontSize: 11, color: "var(--color-text-faint)" }}>loading…</p>;
  }
  if (!art) {
    return <p style={{ fontFamily: sans, fontSize: 13, color: "var(--color-text-muted)" }}>{emptyText}</p>;
  }
  if (art.body == null) {
    return (
      <p style={{ fontFamily: mono, fontSize: 11.5, color: "var(--color-text-faint)" }}>
        couldn't load {art.title} — try the Evidence panel.
      </p>
    );
  }
  if (art.isJson) {
    return (
      <pre
        style={{
          margin: 0,
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
          fontFamily: mono,
          fontSize: 12.5,
          lineHeight: 1.6,
          color: "var(--color-text)",
        }}
      >
        {art.body}
      </pre>
    );
  }
  return <MarkdownRenderer content={art.body} />;
}

function LogsPanel({ loading, logs }: { loading: boolean; logs: ResolvedArtifact | null }) {
  if (loading) {
    return <p style={{ fontFamily: mono, fontSize: 11, color: "var(--color-text-faint)" }}>loading…</p>;
  }
  if (!logs || logs.body == null) {
    return (
      <p style={{ fontFamily: sans, fontSize: 13, color: "var(--color-text-muted)" }}>
        no run logs for this node.
      </p>
    );
  }
  return (
    <pre
      style={{
        margin: 0,
        maxHeight: 520,
        overflow: "auto",
        whiteSpace: "pre-wrap",
        wordBreak: "break-word",
        fontFamily: mono,
        fontSize: 11.5,
        lineHeight: 1.55,
        color: "var(--color-text)",
        background: "var(--color-bg-elevated)",
        border: "1px solid var(--color-border)",
        borderRadius: 2,
        padding: "12px 14px",
      }}
    >
      {logs.body}
    </pre>
  );
}

export function NodeRunView({
  kind,
  outcome,
  staged,
  artifacts,
  details,
}: {
  kind: string;
  outcome: string | null;
  staged: boolean;
  artifacts: Artifact[];
  details: React.ReactNode;
}) {
  const { result, logs, loading } = useRunArtifacts(artifacts);
  const status = runStatus(outcome, staged);

  // Experiments lead with Result; everything else opens on Details. Result and
  // Logs tabs are shown for experiments (or whenever those artifacts exist).
  const showRunTabs = kind === "empirical" || !!result || !!logs;
  const tabs = useMemo<{ key: TabKey; label: string }[]>(() => {
    const t: { key: TabKey; label: string }[] = [];
    if (showRunTabs) {
      t.push({ key: "result", label: "result" });
      t.push({ key: "logs", label: "logs" });
    }
    t.push({ key: "details", label: "details" });
    return t;
  }, [showRunTabs]);

  const [tab, setTab] = useState<TabKey>(showRunTabs ? "result" : "details");

  return (
    <div style={{ display: "flex", flexDirection: "column" }}>
      <StatusBanner status={status} />

      {/* Tab bar */}
      <div
        role="tablist"
        style={{
          display: "flex",
          gap: 4,
          borderBottom: "1px solid var(--color-border)",
          marginBottom: 18,
        }}
      >
        {tabs.map((t) => {
          const active = t.key === tab;
          return (
            <button
              key={t.key}
              role="tab"
              aria-selected={active}
              onClick={() => setTab(t.key)}
              style={{
                all: "unset",
                cursor: "pointer",
                padding: "7px 12px",
                fontFamily: mono,
                fontSize: 11,
                fontWeight: active ? 700 : 500,
                letterSpacing: "0.06em",
                color: active ? "var(--color-text)" : "var(--color-text-muted)",
                borderBottom: active
                  ? "1.5px solid var(--color-text)"
                  : "1.5px solid transparent",
                marginBottom: -1,
                transition: "color 120ms, border-color 120ms",
              }}
            >
              {t.label}
            </button>
          );
        })}
      </div>

      {tab === "result" && (
        <Panel loading={loading} art={result} emptyText="No result recorded for this node yet." />
      )}
      {tab === "logs" && <LogsPanel loading={loading} logs={logs} />}
      {tab === "details" && <div>{details}</div>}
    </div>
  );
}
