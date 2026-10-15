import React from "react";
import { FONT_MONO as mono, FONT_SANS as sans } from "../../styles/tokens";

export interface CheckItem {
  key: string;
  label: string;
  ok: boolean;
  hint?: string;
}

export interface ChecklistInput {
  kind: string;
  outcome: string | null;
  summary: string | null;
  content: string | null;
  insights: string[];
  hypothesis: string | null;
  no_artifacts_reason: string | null;
  artifacts_total?: number | null;
}

/**
 * Build the canonical commit-readiness checklist. Mirrors the backend
 * contract gates in `node_service._get_contract_warnings` plus the
 * Atlas payload_json shape every CLI commit ships with:
 *
 *   { stage_session_id, base_committed_revision, staged_payload: {
 *       title, kind, content, summary, hypothesis, insights,
 *       no_artifacts_reason, repo_context
 *   } }
 *
 * Keep this in sync with the CLI's `nodes:create` schema so users
 * who toggle between the UI and the CLI get the same gate semantics.
 */
export function getChecklist(n: ChecklistInput): CheckItem[] {
  const items: CheckItem[] = [
    {
      key: "kind",
      label: "kind set",
      ok: n.kind !== "untyped",
      hint: "select insight or empirical above",
    },
    {
      key: "outcome",
      label: "outcome set",
      ok: !!n.outcome,
      hint: "completed, failed, or canceled",
    },
    {
      key: "summary",
      label: "summary added",
      ok: !!n.summary,
      hint: "one-line takeaway for the graph card",
    },
  ];

  if (n.kind === "insight") {
    items.push({
      key: "insights",
      label: "insight recorded",
      ok: (n.insights?.length || 0) > 0,
      hint: "add at least one insight bullet",
    });
  }

  if (n.kind === "empirical") {
    items.push({
      key: "hypothesis",
      label: "hypothesis recorded",
      ok: !!n.hypothesis,
      hint: "what you expected before running",
    });
    if (n.outcome === "completed") {
      const hasArtifact = (n.artifacts_total ?? 0) > 0;
      const hasReason = !!n.no_artifacts_reason;
      items.push({
        key: "evidence",
        label: hasArtifact ? "artifacts attached" : "no-artifacts reason",
        ok: hasArtifact || hasReason,
        hint: hasArtifact
          ? `${n.artifacts_total} artifact${n.artifacts_total === 1 ? "" : "s"} attached`
          : "attach an artifact OR fill in no_artifacts_reason",
      });
    }
  }

  return items;
}

interface ContractWarning {
  code: string;
  message: string;
}

interface CommitChecklistProps {
  checklist: CheckItem[];
  warnings?: ContractWarning[];
  revision?: number;
}

const wrapStyle: React.CSSProperties = {
  marginBottom: 16,
  paddingBottom: 14,
  borderBottom: "1px solid var(--color-border)",
  display: "flex",
  flexDirection: "column",
  gap: 8,
};

const headStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 6,
  fontFamily: mono,
  fontSize: 9.5,
  letterSpacing: "0.16em",
  color: "var(--color-text-faint)",
};

const headProgress: React.CSSProperties = {
  marginLeft: "auto",
  fontFamily: mono,
  fontSize: 9.5,
  letterSpacing: "0.04em",
  color: "var(--color-text)",
  fontVariantNumeric: "tabular-nums",
};

const rowStyle = (ok: boolean): React.CSSProperties => ({
  display: "grid",
  gridTemplateColumns: "12px minmax(0, 1fr) auto",
  alignItems: "center",
  gap: 8,
  padding: "5px 8px",
  background: ok ? "transparent" : "var(--color-bg-subtle)",
  border: `1px solid ${ok ? "transparent" : "var(--color-border)"}`,
  borderLeft: `2px solid ${ok ? "var(--color-success)" : "var(--color-warning)"}`,
  borderRadius: 2,
});

const dotStyle = (ok: boolean): React.CSSProperties => ({
  width: 6,
  height: 6,
  borderRadius: 999,
  background: ok ? "var(--color-success)" : "var(--color-warning)",
  boxShadow: ok
    ? "0 0 0 2px var(--color-success-muted)"
    : "0 0 0 2px var(--color-warning-muted)",
  justifySelf: "center",
});

const labelStyle = (ok: boolean): React.CSSProperties => ({
  fontFamily: mono,
  fontSize: 11,
  color: ok ? "var(--color-text)" : "var(--color-text-muted)",
  letterSpacing: "0.01em",
});

const hintStyle: React.CSSProperties = {
  fontFamily: sans,
  fontSize: 10.5,
  color: "var(--color-text-faint)",
  textAlign: "right",
  whiteSpace: "nowrap",
  overflow: "hidden",
  textOverflow: "ellipsis",
  maxWidth: 180,
};

const warningStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 4,
  padding: "8px 10px",
  border: "1px solid var(--color-warning)",
  borderLeft: "2px solid var(--color-warning)",
  background: "var(--color-warning-muted)",
  fontFamily: mono,
  fontSize: 10.5,
  color: "var(--color-text)",
  lineHeight: 1.4,
};

export const CommitChecklist = React.memo(function CommitChecklist({
  checklist,
  warnings,
  revision,
}: CommitChecklistProps) {
  const okCount = checklist.filter((c) => c.ok).length;
  const total = checklist.length;
  const ratio = total > 0 ? Math.round((okCount / total) * 100) : 0;

  return (
    <div style={wrapStyle}>
      <div style={headStyle}>
        <span
          style={{
            width: 5,
            height: 5,
            borderRadius: 999,
            background:
              okCount === total ? "var(--color-success)" : "var(--color-warning)",
            boxShadow:
              okCount === total
                ? "0 0 0 2px var(--color-success-muted)"
                : "0 0 0 2px var(--color-warning-muted)",
          }}
        />
        <span>commit gate</span>
        <span style={headProgress}>
          <span style={{ color: "var(--color-text-faint)" }}>{ratio}% · </span>
          <span style={{ color: "var(--color-text)" }}>
            {okCount}/{total}
          </span>
          {revision !== undefined && (
            <span style={{ color: "var(--color-text-faint)" }}> · r{revision}</span>
          )}
        </span>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {checklist.map((c) => (
          <div key={c.key} style={rowStyle(c.ok)}>
            <span style={dotStyle(c.ok)} />
            <span style={labelStyle(c.ok)}>{c.label}</span>
            {c.hint && <span style={hintStyle}>{c.hint}</span>}
          </div>
        ))}
      </div>

      {warnings && warnings.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {warnings.map((w) => (
            <div key={w.code} style={warningStyle}>
              <span
                style={{
                  fontFamily: mono,
                  fontSize: 9,
                  letterSpacing: "0.16em",
                  color: "var(--color-warning)",
                }}
              >
                ! {w.code.replace(/_/g, " ")}
              </span>
              <span
                style={{
                  color: "var(--color-text-muted)",
                  fontFamily: sans,
                  fontSize: 11.5,
                  lineHeight: 1.5,
                }}
              >
                {w.message}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
});
