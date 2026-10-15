import { memo, useContext, useState } from "react";
import { Handle, Position, useStore } from "@xyflow/react";
import type { NodeProps } from "@xyflow/react";
import type { Node, Artifact } from "../../api/types";
import type { ReactNode } from "react";
import { FileText, Image, FileJson, Table, File, X } from "lucide-react";
import { Lightbulb, Flask, Target, Scales, Circle as PhCircle } from "@phosphor-icons/react";
import type { Icon as PhosphorIcon } from "@phosphor-icons/react";
import { createPortal } from "react-dom";
import { MarkdownRenderer } from "../shared/MarkdownRenderer";
import { MultiSelectContext } from "./GraphCanvas";
import { Z } from "../../styles/tokens";
import { ArtifactImage } from "../artifacts/ArtifactImage";
import {
  timeAgo,
  shortDateTime,
  outcomeColor,
  parseSemanticData,
  scorecardOf,
  scorecardSegments,
  optimizeRunOf,
  formatScore,
  type OptimizeRun,
} from "./orbit";

interface ResearchNodeData {
  node: Node;
  [key: string]: unknown;
}

/** Small floating badge shown on hover to surface run status at a glance. */
function StatusBadge({ children, color }: { children: ReactNode; color: string }) {
  return (
    <div
      data-testid="status-badge"
      style={{
        position: "absolute",
        top: -22,
        left: "50%",
        transform: "translateX(-50%)",
        background: color,
        color: "#fff",
        borderRadius: 3,
        padding: "2px 7px",
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: 9,
        fontWeight: 600,
        textTransform: "uppercase",
        letterSpacing: "0.05em",
        whiteSpace: "nowrap",
        pointerEvents: "none",
        zIndex: 10,
      }}
    >
      {children}
    </div>
  );
}

/* Phosphor fill-weight glyphs: lightbulb = insight, flask = empirical run,
   target = hypothesis (a testable aim), scales = decision (weighing options). */
const KIND_META: Record<string, { label: string; color: string; bg: string; Icon: PhosphorIcon }> = {
  insight:    { label: "insight",    color: "var(--kind-insight)",    bg: "var(--kind-insight-bg)",    Icon: Lightbulb },
  empirical:  { label: "empirical",  color: "var(--kind-empirical)",  bg: "var(--kind-empirical-bg)",  Icon: Flask },
  hypothesis: { label: "hypothesis", color: "var(--kind-hypothesis)", bg: "var(--kind-hypothesis-bg)", Icon: Target },
  decision:   { label: "decision",   color: "var(--kind-decision)",   bg: "var(--kind-decision-bg)",   Icon: Scales },
  untyped:    { label: "untyped",    color: "var(--kind-untyped)",    bg: "var(--kind-untyped-bg)",    Icon: PhCircle },
};

const TYPE_ICON: Record<string, React.ElementType> = {
  text: FileText, image: Image, json: FileJson, table: Table,
  html: FileText, plotly_html: FileText, vega: FileJson,
  binary: File, checkpoint: File, banner: Image, diff_carousel: FileText,
};

/* Compact GEPA optimize-run strip: microcopy + status chip over a budget bar. */
function OptimizeRunStrip({ run }: { run: OptimizeRun }) {
  const used = run.budgetUsed;
  const total = run.budgetTotal;
  const pct =
    used != null && total != null && total > 0
      ? Math.min(100, Math.max(0, (used / total) * 100))
      : null;
  const bits: string[] = [];
  if (used != null && total != null) bits.push(`${used}/${total} evals`);
  else if (used != null) bits.push(`${used} evals`);
  if (run.bestScore != null) bits.push(`best ${formatScore(run.bestScore)}`);
  const chipClass =
    run.status === "done"
      ? "chip-completed"
      : run.status === "error"
        ? "chip-failed"
        : run.status === "stopped"
          ? "chip-stopped"
          : "";
  return (
    <div className="rn-opt" title={run.objective ? `optimize: ${run.objective}` : "optimize run"}>
      <div className="rn-opt-row">
        <span className="rn-opt-copy">{bits.join(" · ") || "optimize run"}</span>
        {run.status && (
          <span className={`chip rn-opt-chip ${chipClass}`.trim()}>
            {run.status === "running" && <span className="rn-opt-pulse" aria-hidden />}
            {run.status}
          </span>
        )}
      </div>
      {pct != null && (
        <div className="rn-opt-bar" aria-hidden>
          <span className="rn-opt-fill" style={{ width: `${pct}%` }} />
        </div>
      )}
    </div>
  );
}

/* Artifact preview modal - rendered via portal */
function ArtifactPreview({ artifact, onClose }: { artifact: Artifact; onClose: () => void }) {
  return createPortal(
    <div
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, zIndex: Z.modal,
        background: "rgba(0,0,0,0.7)", backdropFilter: "blur(4px)",
        display: "flex", alignItems: "center", justifyContent: "center",
        padding: 40,
      }}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          background: "var(--color-bg)", border: "1px solid var(--color-border)",
          borderRadius: 2, width: "100%", maxWidth: 720, maxHeight: "80vh",
          overflow: "auto", padding: "24px 28px", position: "relative",
        }}
      >
        <button
          onClick={onClose}
          style={{
            position: "absolute", top: 12, right: 12,
            background: "none", border: "none", cursor: "pointer",
            color: "var(--color-text-faint)", padding: 4,
          }}
        >
          <X size={16} />
        </button>

        <div style={{
          fontFamily: "'JetBrains Mono', monospace", fontSize: 10,
          color: "var(--color-text-faint)",
          letterSpacing: "0.04em", marginBottom: 8,
        }}>
          {artifact.artifact_type} · {artifact.filename}
        </div>

        <h2 style={{
          fontFamily: "'JetBrains Mono', monospace", fontSize: 14, fontWeight: 500,
          color: "var(--color-text)", marginBottom: 16,
        }}>
          {artifact.title || artifact.filename}
        </h2>

        {/* Content based on type */}
        {artifact.artifact_type === "image" || artifact.artifact_type === "banner" ? (
          artifact.storage_url ? (
            <ArtifactImage
              src={artifact.storage_url}
              alt={artifact.filename || artifact.title || "artifact preview"}
              style={{ maxWidth: "100%", borderRadius: 2 }}
            />
          ) : (
            <p style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 12, color: "var(--color-text-muted)" }}>
              no preview available
            </p>
          )
        ) : artifact.artifact_type === "text" || artifact.artifact_type === "html" ? (
          artifact.payload ? (
            <MarkdownRenderer content={typeof artifact.payload === "string" ? artifact.payload : JSON.stringify(artifact.payload, null, 2)} />
          ) : (
            <p style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 12, color: "var(--color-text-muted)" }}>
              no content
            </p>
          )
        ) : artifact.artifact_type === "json" || artifact.artifact_type === "vega" ? (
          <pre style={{
            fontFamily: "'JetBrains Mono', monospace", fontSize: 11,
            color: "var(--color-text-muted)", background: "var(--color-bg-elevated)",
            border: "1px solid var(--color-border)", borderRadius: 2,
            padding: 12, overflow: "auto", maxHeight: 400,
          }}>
            {typeof artifact.payload === "string" ? artifact.payload : JSON.stringify(artifact.payload, null, 2)}
          </pre>
        ) : (
          <p style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 12, color: "var(--color-text-muted)" }}>
            {artifact.filename} ({artifact.artifact_type})
          </p>
        )}
      </div>
    </div>,
    document.body
  );
}

export const ResearchNodeCard = memo(function ResearchNodeCard({
  data,
  selected,
}: NodeProps & { data: ResearchNodeData }) {
  const { node } = data;
  const multiSelectedIds = useContext(MultiSelectContext);
  const staged = node.lifecycle === "staged";
  const active = selected || multiSelectedIds.has(node.node_id);
  const kind = KIND_META[node.kind] ?? KIND_META.untyped;
  const KindIcon = kind.Icon;
  const artifacts = node.artifacts ?? [];
  const [previewArtifact, setPreviewArtifact] = useState<Artifact | null>(null);
  const [hovered, setHovered] = useState(false);
  // Level-of-detail: below ~0.55 zoom the full card is unreadable and a few
  // hundred of them tank paint, so collapse to a cheap chip. The selector
  // returns a boolean, so a card only re-renders when crossing the threshold,
  // not on every zoom delta. (Declared after all hooks so the early return
  // never skips a hook.)
  const lod = useStore((s) => s.transform[2] < 0.55);
  if (lod) {
    return (
      <div
        className="rn-chip"
        data-active={active ? "" : undefined}
        title={node.title || "untitled"}
        style={{ borderLeft: `3px solid ${kind.color}` }}
      >
        <Handle type="target" position={Position.Top} className="rn-port" />
        <span className="rn-chip-dot" style={{ background: kind.color }} />
        <span className="rn-chip-title">{node.title || "untitled"}</span>
        <Handle type="source" position={Position.Bottom} className="rn-port" />
      </div>
    );
  }

  // Optional structured signals (carried in semantic_data when the backend
  // provides them): failure mode for failed runs, success-criterion check,
  // per-example scorecards and GEPA optimize-run telemetry.
  const semantic = parseSemanticData(node) ?? {};
  const failureMode =
    node.outcome === "failed" && typeof semantic.failure_mode === "string"
      ? semantic.failure_mode
      : null;
  const criterionMet =
    typeof semantic.criterion_met === "boolean" ? semantic.criterion_met : null;
  const scorecard = scorecardOf(node);
  const optimizeRun = optimizeRunOf(node);
  const updatedRel = timeAgo(node.updated_at);

  // Derive which hover-badge (if any) to show.
  const hoverBadge: { label: string; color: string } | null = (() => {
    if (!hovered) return null;
    if (node.outcome === "failed") return { label: "error", color: "var(--color-error)" };
    if (node.outcome === "completed") return { label: "success", color: "var(--color-success)" };
    return null;
  })();

  return (
    <>
      <div
        className="rn stagger-fade-in"
        data-active={active ? "" : undefined}
        data-staged={staged ? "" : undefined}
        data-kind={node.kind}
        title={node.title || "untitled"}
        style={{ position: "relative", borderTop: `3px solid ${kind.color}` }}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
      >

        {/* Hover status badge — floats above the node */}
        {hoverBadge && (
          <StatusBadge color={hoverBadge.color}>{hoverBadge.label}</StatusBadge>
        )}

        <Handle type="target" position={Position.Top} className="rn-port" />

        {/* Meta row: kind chip (tinted square + filled glyph) left, staged + time right */}
        <div className="rn-meta">
          <span className="rn-kind-chip" style={{ color: kind.color, background: kind.bg }}>
            <KindIcon size={12} weight="fill" aria-hidden />
          </span>
          <span className="rn-kind" style={{ color: kind.color }}>
            {kind.label}
          </span>
          {staged && <span className="rn-flag">staged</span>}
          {updatedRel && (
            <span className="rn-time" title={`updated ${shortDateTime(node.updated_at)}`}>
              {updatedRel}
            </span>
          )}
        </div>

        {/* Title - 2 line clamp */}
        <div className="rn-title">{node.title || "untitled"}</div>

        {/* Per-example scorecard strip - pass/fail segments */}
        {scorecard && (
          <div
            className="rn-scorecard"
            title={`evaluation: ${scorecard.passed}/${scorecard.total} passed`}
            aria-hidden
          >
            {scorecardSegments(scorecard, 48).map((pass, i) => (
              <span key={i} className="rn-scorecard-seg" data-pass={pass ? "" : undefined} />
            ))}
          </div>
        )}

        {/* GEPA optimize-run strip - control nodes only */}
        {optimizeRun && <OptimizeRunStrip run={optimizeRun} />}

        {/* Summary - 3 line clamp */}
        {node.summary && (
          <div className="rn-summary">{node.summary}</div>
        )}

        {/* Artifacts row */}
        {artifacts.length > 0 && (
          <div style={{
            display: "flex", gap: 4, flexWrap: "wrap",
            marginTop: 2, paddingTop: 6,
            borderTop: "1px solid var(--color-border)",
          }}>
            {artifacts.slice(0, 4).map((a) => {
              const Icon = TYPE_ICON[a.artifact_type] ?? File;
              return (
                <button
                  key={a.artifact_id}
                  onClick={(e) => { e.stopPropagation(); setPreviewArtifact(a); }}
                  title={a.filename}
                  style={{
                    display: "flex", alignItems: "center", gap: 3,
                    padding: "2px 5px", background: "var(--color-accent-subtle)",
                    border: "1px solid var(--color-border)", borderRadius: 2,
                    cursor: "pointer", maxWidth: 80, overflow: "hidden",
                    fontFamily: "'JetBrains Mono', monospace", fontSize: 8,
                    color: "var(--color-text-muted)",
                  }}
                >
                  <Icon size={9} style={{ flexShrink: 0 }} />
                  <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {a.filename?.split("/").pop()?.slice(0, 12) || a.artifact_type}
                  </span>
                </button>
              );
            })}
            {artifacts.length > 4 && (
              <span style={{
                fontFamily: "'JetBrains Mono', monospace", fontSize: 8,
                color: "var(--color-text-faint)", padding: "2px 4px",
              }}>
                +{artifacts.length - 4}
              </span>
            )}
          </div>
        )}

        {/* Status footer: outcome dot, failure mode, scorecard, criterion - only when present */}
        {(node.outcome || criterionMet != null || scorecard) && (
          <div className="rn-status">
            {node.outcome && (
              <>
                <span className="rn-dot" style={{ background: outcomeColor(node.outcome) }} aria-hidden />
                <span>{node.outcome}</span>
              </>
            )}
            {failureMode && (
              <span className="rn-fail" title={`failure mode: ${failureMode}`}>
                · {failureMode}
              </span>
            )}
            {scorecard && (
              <span
                style={{ flexShrink: 0 }}
                title={`evaluation: ${scorecard.passed}/${scorecard.total} passed`}
              >
                {(node.outcome || failureMode) ? "· " : ""}
                {scorecard.passed}/{scorecard.total} examples
              </span>
            )}
            {criterionMet != null && (
              <span
                title={criterionMet ? "success criterion met" : "success criterion not met"}
                style={{
                  marginLeft: "auto",
                  flexShrink: 0,
                  color: criterionMet ? "var(--color-success)" : "var(--color-text-faint)",
                }}
              >
                criterion {criterionMet ? "✓" : "✗"}
              </span>
            )}
          </div>
        )}

        <Handle type="source" position={Position.Bottom} className="rn-port" />
      </div>

      {/* Preview modal */}
      {previewArtifact && (
        <ArtifactPreview artifact={previewArtifact} onClose={() => setPreviewArtifact(null)} />
      )}
    </>
  );
});
