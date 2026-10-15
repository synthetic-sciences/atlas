import { useState, useCallback, useEffect, useRef } from "react";
import { MarkdownRenderer } from "../shared/MarkdownRenderer.js";
import { NodeRunView } from "./NodeRunView.js";
import { NodeStructured } from "./NodeStructured.js";
import { Pencil, Lock, Check, Plus, X } from "lucide-react";
import { FONT_MONO as mono, FONT_SANS as sans } from "../../styles/tokens.js";
import type { Artifact } from "../../api/types.js";

/* ── shared style fragments ── */

const sectionLabel: React.CSSProperties = {
  fontFamily: sans,
  fontSize: 10,
  fontWeight: 600,
  letterSpacing: "0.08em",
  color: "var(--color-text-faint)",
  margin: 0,
  userSelect: "none",
};

const editWell: React.CSSProperties = {
  width: "100%",
  fontFamily: mono,
  fontSize: 13,
  lineHeight: 1.7,
  color: "var(--color-text)",
  background: "var(--color-accent-subtle)",
  border: "1px solid var(--color-border-strong)",
  borderLeft: "2px solid var(--color-text-faint)",
  borderRadius: 2,
  resize: "vertical" as const,
  padding: "10px 12px",
  transition: "border-color 150ms, box-shadow 150ms",
};

const editWellFocus =
  "border-color: var(--color-text-muted); box-shadow: 0 0 0 3px var(--color-accent-subtle);";

const errorBanner: React.CSSProperties = {
  fontFamily: mono,
  fontSize: 11,
  color: "var(--color-error)",
  padding: "12px 14px",
  marginTop: 12,
  background: "rgba(229, 77, 66, 0.06)",
  border: "1px solid rgba(229, 77, 66, 0.2)",
  borderRadius: 2,
};

/* ── Inline select ── */

function Sel({
  value,
  options,
  onChange,
  disabled,
}: {
  value: string;
  options: { v: string; l: string }[];
  onChange: (v: string) => void;
  disabled?: boolean;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled}
      style={{
        fontFamily: mono,
        fontSize: 10,
        fontWeight: 500,
        padding: "3px 8px",
        borderRadius: 2,
        background: "var(--color-bg-subtle)",
        color: "var(--color-text-muted)",
        border: "1px solid var(--color-border)",
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.35 : 1,
        letterSpacing: "0.02em",
        transition: "border-color 150ms",
      }}
    >
      {options.map((o) => (
        <option key={o.v} value={o.v}>
          {o.l}
        </option>
      ))}
    </select>
  );
}

/* ── "Saved" flash ── */

function SavedFlash({ visible }: { visible: boolean }) {
  if (!visible) return null;
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 3,
        fontFamily: mono,
        fontSize: 9,
        fontWeight: 500,
        color: "var(--color-success)",
        letterSpacing: "0.04em",
        animation: "fade-in 150ms ease both",
      }}
    >
      <Check size={10} strokeWidth={2.5} />
      saved
    </span>
  );
}

/* ── Section header with label + edit affordance ── */

function SectionHead({
  label,
  staged,
  editing,
  onEdit,
  savedField,
  extra,
}: {
  label: string;
  staged: boolean;
  editing: boolean;
  onEdit?: () => void;
  savedField: string | null;
  extra?: React.ReactNode;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        marginBottom: 10,
        minHeight: 18,
      }}
    >
      <p style={sectionLabel}>{label}</p>
      {!staged && (
        <Lock size={10} style={{ color: "var(--color-text-faint)", opacity: 0.5 }} />
      )}
      {staged && !editing && onEdit && (
        <button
          onClick={onEdit}
          title={`Edit ${label}`}
          style={{
            all: "unset",
            cursor: "pointer",
            display: "inline-flex",
            alignItems: "center",
            gap: 3,
            fontFamily: mono,
            fontSize: 9,
            color: "var(--color-text-faint)",
            padding: "2px 6px",
            borderRadius: 2,
            border: "1px solid transparent",
            transition: "border-color 150ms, color 150ms, background 150ms",
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.borderColor = "var(--color-border)";
            e.currentTarget.style.background = "var(--color-accent-subtle)";
            e.currentTarget.style.color = "var(--color-text-muted)";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.borderColor = "transparent";
            e.currentTarget.style.background = "transparent";
            e.currentTarget.style.color = "var(--color-text-faint)";
          }}
        >
          <Pencil size={9} />
          edit
        </button>
      )}
      <SavedFlash visible={savedField === label} />
      {extra}
    </div>
  );
}

/* ── Editable placeholder (non-editing state) ── */

function EditablePlaceholder({
  text,
  placeholder,
  staged,
  onActivate,
  fontSize = 13,
  useMono = false,
}: {
  text: string | null;
  placeholder: string;
  staged: boolean;
  onActivate: () => void;
  fontSize?: number;
  useMono?: boolean;
}) {
  const hasContent = !!text;
  return (
    <div
      onClick={() => staged && !hasContent && onActivate()}
      style={{
        fontFamily: useMono ? mono : sans,
        fontSize,
        lineHeight: 1.7,
        color: hasContent ? "var(--color-text)" : "var(--color-text-faint)",
        cursor: staged && !hasContent ? "text" : "default",
        margin: 0,
        whiteSpace: "pre-wrap",
        ...(staged && !hasContent
          ? {
              padding: "8px 12px",
              border: "1px dashed var(--color-border)",
              borderRadius: 2,
              background: "var(--color-accent-subtle)",
              transition: "border-color 150ms",
            }
          : {}),
      }}
      onMouseEnter={(e) => {
        if (staged && !hasContent)
          e.currentTarget.style.borderColor = "var(--color-text-faint)";
      }}
      onMouseLeave={(e) => {
        if (staged && !hasContent)
          e.currentTarget.style.borderColor = "var(--color-border)";
      }}
    >
      {text || placeholder}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════
   MAIN COMPONENT
   ═══════════════════════════════════════════════════════════════════ */

interface NodeEditorProps {
  nodeId: string;
  slugName: string | null;
  title: string | null;
  kind: string;
  revision: number;
  updatedAt: string;
  staged: boolean;
  summary: string | null;
  content: string | null;
  hypothesis: string | null;
  insights: string[];
  outcome: string | null;
  noArtifactsReason: string | null;
  artifactsTotal?: number | null;
  artifacts: Artifact[];
  semanticData?: Record<string, unknown> | string | null;
  repoUrl?: string | null;
  branchName?: string | null;
  headCommitSha?: string | null;
  save: (fields: Record<string, unknown>) => Promise<void>;
  actErr: string | null;
}

export function NodeEditor({
  slugName,
  title,
  kind,
  revision,
  updatedAt,
  staged,
  summary,
  content,
  hypothesis,
  insights,
  outcome,
  noArtifactsReason,
  artifactsTotal,
  artifacts,
  semanticData,
  repoUrl,
  branchName,
  headCommitSha,
  save,
  actErr,
}: NodeEditorProps) {
  /* ── editing state ── */
  const [editSummary, setEditSummary] = useState(false);
  const [summaryVal, setSummaryVal] = useState("");
  const summaryRef = useRef<HTMLTextAreaElement>(null);

  const [editContent, setEditContent] = useState(false);
  const [contentVal, setContentVal] = useState("");
  const contentRef = useRef<HTMLTextAreaElement>(null);
  const [contentExpanded, setContentExpanded] = useState(false);

  const [editHypothesis, setEditHypothesis] = useState(false);
  const [hypothesisVal, setHypothesisVal] = useState("");
  const hypothesisRef = useRef<HTMLTextAreaElement>(null);

  // De-dup: the standalone Hypothesis section repeats text the Content
  // write-up already contains (the agent embeds the hypothesis under a
  // "## Hypothesis" heading in content). In read mode, hide the standalone
  // section ONLY when its text is genuinely contained in content — so we never
  // hide a hypothesis that isn't covered elsewhere. While staged/editing, keep
  // all fields visible so each remains editable.
  const _norm = (s: string | null | undefined) =>
    (s || "").replace(/\s+/g, " ").trim().toLowerCase();
  const hypothesisShownInContent =
    !!hypothesis && !!content && _norm(content).includes(_norm(hypothesis));

  const [editNoArtifacts, setEditNoArtifacts] = useState(false);
  const [noArtifactsVal, setNoArtifactsVal] = useState("");
  const noArtifactsRefEl = useRef<HTMLTextAreaElement>(null);

  const [editInsightIdx, setEditInsightIdx] = useState<number | null>(null);
  const [insightEditVal, setInsightEditVal] = useState("");
  const insightRef = useRef<HTMLInputElement>(null);

  const [editTitle, setEditTitle] = useState(false);
  const [titleVal, setTitleVal] = useState("");
  const titleRef = useRef<HTMLInputElement>(null);

  /* ── saved flash ── */
  const [savedField, setSavedField] = useState<string | null>(null);
  const savedTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const flashSaved = useCallback((field: string) => {
    setSavedField(field);
    if (savedTimer.current) clearTimeout(savedTimer.current);
    savedTimer.current = setTimeout(() => setSavedField(null), 1800);
  }, []);

  /* ── focus effects ── */
  useEffect(() => {
    if (editSummary && summaryRef.current) summaryRef.current.focus();
  }, [editSummary]);
  useEffect(() => {
    if (editContent && contentRef.current) contentRef.current.focus();
  }, [editContent]);
  useEffect(() => {
    if (editHypothesis && hypothesisRef.current) hypothesisRef.current.focus();
  }, [editHypothesis]);
  useEffect(() => {
    if (editNoArtifacts && noArtifactsRefEl.current) noArtifactsRefEl.current.focus();
  }, [editNoArtifacts]);
  useEffect(() => {
    if (editInsightIdx !== null && insightRef.current) {
      insightRef.current.focus();
      insightRef.current.select();
    }
  }, [editInsightIdx]);
  useEffect(() => {
    if (editTitle && titleRef.current) {
      titleRef.current.focus();
      titleRef.current.select();
    }
  }, [editTitle]);

  /* ── Cmd+Enter handler for textareas ── */
  const cmdEnter = useCallback(
    (e: React.KeyboardEvent, saveFn: () => void) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
        e.preventDefault();
        saveFn();
      }
    },
    [],
  );

  /* ── save helpers ── */
  const saveSummary = useCallback(async () => {
    const v = summaryVal.trim();
    if (v === (summary || "")) {
      setEditSummary(false);
      return;
    }
    try {
      await save({ summary: v || null });
      setEditSummary(false);
      flashSaved("summary");
    } catch {
      // Keep edit mode open so user can retry
    }
  }, [summaryVal, summary, save, flashSaved]);

  const saveTitle = useCallback(async () => {
    const v = titleVal.trim();
    if (v === (title || "")) {
      setEditTitle(false);
      return;
    }
    try {
      await save({ title: v || null });
      setEditTitle(false);
      flashSaved("title");
    } catch {
      // Keep edit mode open so user can retry
    }
  }, [titleVal, title, save, flashSaved]);

  const saveContent = useCallback(async () => {
    const v = contentVal.trim();
    if (v === (content || "")) {
      setEditContent(false);
      return;
    }
    try {
      await save({ content: v || null });
      setEditContent(false);
      flashSaved("content");
    } catch {
      // Keep edit mode open so user can retry
    }
  }, [contentVal, content, save, flashSaved]);

  const saveHypothesis = useCallback(async () => {
    const v = hypothesisVal.trim();
    if (v === (hypothesis || "")) {
      setEditHypothesis(false);
      return;
    }
    try {
      await save({ hypothesis: v || null });
      setEditHypothesis(false);
      flashSaved("hypothesis");
    } catch {
      // Keep edit mode open so user can retry
    }
  }, [hypothesisVal, hypothesis, save, flashSaved]);

  const saveNoArtifactsReason = useCallback(async () => {
    const v = noArtifactsVal.trim();
    if (v === (noArtifactsReason || "")) {
      setEditNoArtifacts(false);
      return;
    }
    try {
      await save({ no_artifacts_reason: v || null });
      setEditNoArtifacts(false);
      flashSaved("no_artifacts_reason");
    } catch {
      // Keep edit mode open so user can retry
    }
  }, [noArtifactsVal, noArtifactsReason, save, flashSaved]);

  const saveInsightEdit = useCallback(
    async (idx: number) => {
      const v = insightEditVal.trim();
      if (!v) {
        setEditInsightIdx(null);
        return;
      }
      const current = [...(insights || [])];
      if (current[idx] === v) {
        setEditInsightIdx(null);
        return;
      }
      current[idx] = v;
      try {
        await save({ insights: current });
        setEditInsightIdx(null);
        flashSaved("insights");
      } catch {
        // Keep edit mode open so user can retry
      }
    },
    [insightEditVal, insights, save, flashSaved],
  );

  const addInsight = useCallback(async () => {
    const current = [...(insights || []), ""];
    await save({ insights: current });
    setEditInsightIdx(current.length - 1);
    setInsightEditVal("");
  }, [insights, save]);

  const removeInsight = useCallback(
    async (idx: number) => {
      const current = [...(insights || [])];
      current.splice(idx, 1);
      await save({ insights: current });
      flashSaved("insights");
    },
    [insights, save, flashSaved],
  );

  /* ════════════════════════════════════════════════════════════════ */

  return (
    <div
      style={{
        flex: 6,
        overflowY: "auto",
        padding: "44px 40px 88px",
        display: "flex",
        flexDirection: "column",
      }}
    >
      <div
        className="ne-doc"
        style={{
          width: "100%",
          maxWidth: 760,
          margin: "0 auto",
          display: "flex",
          flexDirection: "column",
        }}
      >
        {/* ── Document hero: dateline + title ── */}
        <div
          style={{
            display: "flex",
            gap: 12,
            flexWrap: "wrap",
            alignItems: "center",
            fontFamily: mono,
            fontSize: 10,
            color: "var(--color-text-faint)",
            marginBottom: 14,
          }}
        >
          {slugName && <span style={{ opacity: 0.7 }}>{slugName}</span>}
          <span style={{ fontWeight: 600, letterSpacing: "0.04em", color: "var(--color-text-muted)" }}>
            {kind}
          </span>
          <span>r{revision}</span>
          <span>
            {new Date(updatedAt).toLocaleDateString("en-US", {
              month: "short",
              day: "numeric",
              hour: "2-digit",
              minute: "2-digit",
            })}
          </span>
          {staged && (
            <div style={{ display: "flex", gap: 8, marginLeft: "auto" }}>
              <Sel
                value={kind}
                options={[
                  { v: "untyped", l: "untyped" },
                  { v: "insight", l: "insight" },
                  { v: "empirical", l: "empirical" },
                ]}
                onChange={(v) => save({ kind: v })}
              />
              <Sel
                value={outcome || ""}
                options={[
                  { v: "", l: "outcome" },
                  { v: "completed", l: "completed" },
                  { v: "failed", l: "failed" },
                  { v: "canceled", l: "canceled" },
                ]}
                onChange={(v) => save({ outcome: v || null })}
              />
            </div>
          )}
        </div>

        {editTitle ? (
          <input
            ref={titleRef}
            value={titleVal}
            onChange={(e) => setTitleVal(e.target.value)}
            onBlur={saveTitle}
            onKeyDown={(e) => {
              if (e.key === "Enter") saveTitle();
              if (e.key === "Escape") setEditTitle(false);
            }}
            placeholder="Untitled"
            style={{
              fontFamily: sans,
              fontSize: 27,
              fontWeight: 500,
              lineHeight: 1.15,
              color: "var(--color-text)",
              background: "none",
              border: "none",
              outline: "none",
              width: "100%",
              padding: 0,
              margin: 0,
            }}
          />
        ) : (
          <h1
            onClick={() => {
              if (staged) {
                setEditTitle(true);
                setTitleVal(title || "");
              }
            }}
            style={{
              fontFamily: sans,
              fontSize: 27,
              fontWeight: 500,
              lineHeight: 1.15,
              color: title ? "var(--color-text)" : "var(--color-text-faint)",
              margin: 0,
              cursor: staged ? "text" : "default",
            }}
          >
            {title || "untitled"}
            <SavedFlash visible={savedField === "title"} />
          </h1>
        )}

        <div style={{ height: 1, background: "var(--color-border)", marginTop: 24, marginBottom: 28 }} />

      {/* Structured payload by kind: empirical run header (metric + code state),
          decision / hypothesis / plan fields. Renders nothing for plain nodes. */}
      <NodeStructured
        node={{
          kind,
          outcome,
          summary,
          semantic_data: semanticData ?? null,
          repo_url: repoUrl ?? null,
          branch_name: branchName ?? null,
          head_commit_sha: headCommitSha ?? null,
        }}
      />

      {actErr && <div style={errorBanner}>{actErr}</div>}

      {/* Run status banner + tabbed body (Result · Logs · Details). The authored
          sections below become the Details tab. */}
      <NodeRunView
        kind={kind}
        outcome={outcome}
        staged={staged}
        artifacts={artifacts}
        details={
          <>
      {/* ── SUMMARY ── */}
      <div
        style={{
          paddingTop: 20,
          paddingBottom: 20,
          borderBottom: "1px solid var(--color-border)",
        }}
      >
        <SectionHead
          label="summary"
          staged={staged}
          editing={editSummary}
          onEdit={() => {
            setEditSummary(true);
            setSummaryVal(summary || "");
          }}
          savedField={savedField}
        />
        {editSummary ? (
          <>
            <style>{`.ne-well:focus { ${editWellFocus} }`}</style>
            <textarea
              className="ne-well"
              ref={summaryRef}
              value={summaryVal}
              onChange={(e) => setSummaryVal(e.target.value)}
              onBlur={saveSummary}
              onKeyDown={(e) => cmdEnter(e, saveSummary)}
              rows={3}
              placeholder="Describe the key finding or purpose of this node..."
              style={editWell}
            />
            <p
              style={{
                fontFamily: sans,
                fontSize: 9,
                color: "var(--color-text-faint)",
                marginTop: 4,
                opacity: 0.7,
              }}
            >
              Cmd+Enter to save, or click away
            </p>
          </>
        ) : (
          <EditablePlaceholder
            text={summary}
            placeholder={staged ? "Click to add a summary..." : "No summary"}
            staged={staged}
            onActivate={() => {
              setEditSummary(true);
              setSummaryVal("");
            }}
          />
        )}
      </div>

      {/* ── CONTENT ── */}
      <div
        style={{
          paddingTop: 20,
          paddingBottom: 20,
          borderBottom: "1px solid var(--color-border)",
        }}
      >
        <SectionHead
          label="content"
          staged={staged}
          editing={editContent}
          onEdit={() => {
            setEditContent(true);
            setContentVal(content || "");
          }}
          savedField={savedField}
          extra={
            content ? (
              <button
                onClick={() => setContentExpanded(!contentExpanded)}
                style={{
                  all: "unset",
                  cursor: "pointer",
                  fontFamily: mono,
                  fontSize: 9,
                  color: "var(--color-text-faint)",
                  padding: "2px 6px",
                  borderRadius: 2,
                  border: "1px solid transparent",
                  transition: "border-color 150ms, background 150ms",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = "var(--color-border)";
                  e.currentTarget.style.background = "var(--color-accent-subtle)";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = "transparent";
                  e.currentTarget.style.background = "transparent";
                }}
              >
                {contentExpanded ? "collapse" : "expand"}
              </button>
            ) : undefined
          }
        />
        {editContent ? (
          <>
            <style>{`.ne-well:focus { ${editWellFocus} }`}</style>
            <textarea
              className="ne-well"
              ref={contentRef}
              value={contentVal}
              onChange={(e) => setContentVal(e.target.value)}
              onBlur={saveContent}
              onKeyDown={(e) => cmdEnter(e, saveContent)}
              rows={14}
              placeholder="Write your research notes, methodology, observations..."
              style={{ ...editWell, fontSize: 12 }}
            />
            <p
              style={{
                fontFamily: sans,
                fontSize: 9,
                color: "var(--color-text-faint)",
                marginTop: 4,
                opacity: 0.7,
              }}
            >
              Cmd+Enter to save, or click away
            </p>
          </>
        ) : (
          <div
            onClick={() => {
              if (staged && !content) {
                setEditContent(true);
                setContentVal("");
              }
            }}
            style={{
              maxHeight: contentExpanded ? "none" : 300,
              overflow: "hidden",
              position: "relative",
              cursor: staged && !content ? "text" : "default",
            }}
          >
            {content ? (
              <MarkdownRenderer content={content} />
            ) : (
              <EditablePlaceholder
                text={null}
                placeholder={
                  staged
                    ? "Click to add content - research notes, methodology, observations..."
                    : "No content"
                }
                staged={staged}
                onActivate={() => {
                  setEditContent(true);
                  setContentVal("");
                }}
                fontSize={12}
              />
            )}
            {!contentExpanded && content && content.length > 400 && (
              <div
                style={{
                  position: "absolute",
                  bottom: 0,
                  left: 0,
                  right: 0,
                  height: 48,
                  background: "linear-gradient(transparent, var(--color-bg))",
                  pointerEvents: "none",
                }}
              />
            )}
          </div>
        )}
      </div>

      {/* ── HYPOTHESIS (empirical nodes) ── */}
      {(kind === "empirical" || hypothesis) && !(!staged && hypothesisShownInContent) && (
        <div
          style={{
            paddingTop: 20,
            paddingBottom: 20,
            borderBottom: "1px solid var(--color-border)",
          }}
        >
          <SectionHead
            label="hypothesis"
            staged={staged}
            editing={editHypothesis}
            onEdit={() => {
              setEditHypothesis(true);
              setHypothesisVal(hypothesis || "");
            }}
            savedField={savedField}
          />
          {editHypothesis ? (
            <>
              <style>{`.ne-well:focus { ${editWellFocus} }`}</style>
              <textarea
                className="ne-well"
                ref={hypothesisRef}
                value={hypothesisVal}
                onChange={(e) => setHypothesisVal(e.target.value)}
                onBlur={saveHypothesis}
                onKeyDown={(e) => cmdEnter(e, saveHypothesis)}
                rows={3}
                placeholder="State your testable hypothesis..."
                style={editWell}
              />
              <p
                style={{
                  fontFamily: mono,
                  fontSize: 9,
                  color: "var(--color-text-faint)",
                  marginTop: 4,
                  opacity: 0.7,
                }}
              >
                Cmd+Enter to save, or click away
              </p>
            </>
          ) : (
            <EditablePlaceholder
              text={hypothesis}
              placeholder={
                staged ? "Click to add a hypothesis..." : "No hypothesis"
              }
              staged={staged}
              onActivate={() => {
                setEditHypothesis(true);
                setHypothesisVal("");
              }}
              useMono
            />
          )}
        </div>
      )}

      {/* ── NO_ARTIFACTS_REASON (empirical + completed without artifacts) ── */}
      {(kind === "empirical" &&
        outcome === "completed" &&
        (artifactsTotal ?? 0) === 0) ||
      noArtifactsReason ? (
        <div
          style={{
            paddingTop: 20,
            paddingBottom: 20,
            borderBottom: "1px solid var(--color-border)",
          }}
        >
          <SectionHead
            label="no-artifacts reason"
            staged={staged}
            editing={editNoArtifacts}
            onEdit={() => {
              setEditNoArtifacts(true);
              setNoArtifactsVal(noArtifactsReason || "");
            }}
            savedField={savedField}
            extra={
              <span
                style={{
                  fontFamily: mono,
                  fontSize: 9,
                  letterSpacing: "0.12em",
                  color: noArtifactsReason
                    ? "var(--color-success)"
                    : "var(--color-warning)",
                }}
              >
                {noArtifactsReason ? "set" : "required to commit"}
              </span>
            }
          />
          {editNoArtifacts ? (
            <>
              <style>{`.ne-well:focus { ${editWellFocus} }`}</style>
              <textarea
                className="ne-well"
                ref={noArtifactsRefEl}
                value={noArtifactsVal}
                onChange={(e) => setNoArtifactsVal(e.target.value)}
                onBlur={saveNoArtifactsReason}
                onKeyDown={(e) => cmdEnter(e, saveNoArtifactsReason)}
                rows={3}
                placeholder='e.g. "logged via wandb run https://wandb.ai/...; not re-uploaded here"'
                style={editWell}
              />
              <p
                style={{
                  fontFamily: sans,
                  fontSize: 9,
                  color: "var(--color-text-faint)",
                  marginTop: 4,
                  opacity: 0.7,
                }}
              >
                Cmd+Enter to save, or click away. The backend rejects empirical
                commits without artifacts unless this is set.
              </p>
            </>
          ) : (
            <EditablePlaceholder
              text={noArtifactsReason}
              placeholder={
                staged
                  ? "Click to explain why this completed run has no attached artifacts..."
                  : "No reason recorded"
              }
              staged={staged}
              onActivate={() => {
                setEditNoArtifacts(true);
                setNoArtifactsVal("");
              }}
              fontSize={12}
            />
          )}
        </div>
      ) : null}

      {/* ── INSIGHTS (insight nodes) ── */}
      {(kind === "insight" || (insights && insights.length > 0)) && (
        <div
          style={{
            paddingTop: 20,
            paddingBottom: 20,
            borderBottom: "1px solid var(--color-border)",
          }}
        >
          <SectionHead
            label="insights"
            staged={staged}
            editing={editInsightIdx !== null}
            savedField={savedField}
            extra={
              staged ? (
                <button
                  onClick={addInsight}
                  title="Add insight"
                  style={{
                    all: "unset",
                    cursor: "pointer",
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 3,
                    fontFamily: mono,
                    fontSize: 9,
                    color: "var(--color-text-faint)",
                    padding: "2px 6px",
                    borderRadius: 2,
                    border: "1px solid transparent",
                    transition: "border-color 150ms, color 150ms, background 150ms",
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.borderColor = "var(--color-border)";
                    e.currentTarget.style.background = "var(--color-accent-subtle)";
                    e.currentTarget.style.color = "var(--color-text-muted)";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.borderColor = "transparent";
                    e.currentTarget.style.background = "transparent";
                    e.currentTarget.style.color = "var(--color-text-faint)";
                  }}
                >
                  <Plus size={10} strokeWidth={2} />
                  add
                </button>
              ) : undefined
            }
          />
          {insights && insights.length > 0 ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {insights.map((ins, i) => (
                <div
                  key={i}
                  style={{
                    display: "flex",
                    alignItems: "flex-start",
                    gap: 8,
                    padding: "6px 10px",
                    borderRadius: 2,
                    background:
                      editInsightIdx === i
                        ? "var(--color-accent-subtle)"
                        : "transparent",
                    border:
                      editInsightIdx === i
                        ? "1px solid var(--color-border-strong)"
                        : "1px solid transparent",
                    borderLeft:
                      editInsightIdx === i
                        ? "2px solid var(--color-text-faint)"
                        : "2px solid var(--color-border)",
                    transition: "background 150ms, border-color 150ms",
                  }}
                >
                  <span
                    style={{
                      fontFamily: mono,
                      fontSize: 10,
                      fontWeight: 600,
                      color: "var(--color-text-faint)",
                      minWidth: 16,
                      paddingTop: 2,
                    }}
                  >
                    {i + 1}.
                  </span>
                  {editInsightIdx === i ? (
                    <input
                      ref={insightRef}
                      value={insightEditVal}
                      onChange={(e) => setInsightEditVal(e.target.value)}
                      onBlur={() => saveInsightEdit(i)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") saveInsightEdit(i);
                        if (e.key === "Escape") setEditInsightIdx(null);
                      }}
                      placeholder="Type your insight..."
                      style={{
                        flex: 1,
                        fontFamily: mono,
                        fontSize: 12,
                        lineHeight: 1.6,
                        color: "var(--color-text)",
                        background: "none",
                        border: "none",
                        outline: "none",
                        padding: 0,
                      }}
                    />
                  ) : (
                    <span
                      onClick={() => {
                        if (staged) {
                          setEditInsightIdx(i);
                          setInsightEditVal(ins);
                        }
                      }}
                      style={{
                        flex: 1,
                        fontFamily: mono,
                        fontSize: 12,
                        lineHeight: 1.6,
                        color: ins ? "var(--color-text)" : "var(--color-text-faint)",
                        cursor: staged ? "text" : "default",
                      }}
                    >
                      {ins || (staged ? "Click to edit..." : "")}
                    </span>
                  )}
                  {staged && editInsightIdx !== i && (
                    <button
                      onClick={() => removeInsight(i)}
                      title="Remove insight"
                      style={{
                        all: "unset",
                        cursor: "pointer",
                        display: "inline-flex",
                        alignItems: "center",
                        padding: 2,
                        borderRadius: 2,
                        color: "var(--color-text-faint)",
                        opacity: 0.5,
                        transition: "opacity 150ms, color 150ms",
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.opacity = "1";
                        e.currentTarget.style.color = "var(--color-error)";
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.opacity = "0.5";
                        e.currentTarget.style.color = "var(--color-text-faint)";
                      }}
                    >
                      <X size={12} strokeWidth={2} />
                    </button>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <EditablePlaceholder
              text={null}
              placeholder={
                staged
                  ? 'No insights yet - click "add" above'
                  : "No insights recorded"
              }
              staged={false}
              onActivate={() => {}}
              fontSize={12}
            />
          )}
        </div>
      )}
          </>
        }
      />

      </div>
    </div>
  );
}
