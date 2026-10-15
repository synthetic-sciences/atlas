import React, { useState, useCallback, useEffect, useRef } from "react";
import { Link as RouterLink } from "react-router-dom";
import { api } from "../../api/client";
import type {
  Artifact,
  AuditEvent,
  SharingInfo,
  SharingMode,
  ArtifactType,
  Collaborator,
  GraphTag,
} from "../../api/types";
import { ArtifactList } from "../artifacts/ArtifactList";
import { ExportPanel } from "../export/ExportPanel";
import { SharingPanel } from "../sharing/SharingPanel";
import { TagManager } from "../tags/TagManager";
import { BASE_URL } from "../../lib/config";
import {
  GitBranch,
  Check,
  Trash2,
  Upload,
  ChevronRight,
  Paperclip,
  Tag,
  Users,
  History,
  Download,
  Gauge,
} from "lucide-react";
import { CommitChecklist, type CheckItem } from "./CommitChecklist";
import { errorMessage } from "../../lib/errors";
import { FONT_MONO as mono, FONT_SANS as sans } from "../../styles/tokens";
import { timeAgo, optimizeRunOf, formatScore, type OptimizeRun } from "../graph/orbit";
const labelStyle: React.CSSProperties = {
  fontFamily: sans,
  fontSize: 11,
  fontWeight: 500,
  letterSpacing: "0.06em",
  color: "var(--color-text-muted)",
};

/* -- Collapsible section with Lucide icon -- */
function SectionInner({
  title,
  icon: Icon,
  count,
  open: openProp,
  onToggle,
  children,
}: {
  title: string;
  icon: React.ComponentType<{ size?: number; style?: React.CSSProperties }>;
  count?: number;
  open?: boolean;
  onToggle?: () => void;
  children: React.ReactNode;
}) {
  const isControlled = onToggle !== undefined;
  const [internalOpen, setInternalOpen] = useState(!!openProp);
  const open = isControlled ? !!openProp : internalOpen;
  const handleToggle = () => {
    if (isControlled) {
      onToggle?.();
    } else {
      setInternalOpen((v) => !v);
    }
  };
  return (
    <div style={{ borderBottom: "1px solid var(--color-border)" }}>
      <button
        onClick={handleToggle}
        style={{
          all: "unset",
          cursor: "pointer",
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "10px 0",
          width: "100%",
          borderRadius: 2,
          transition: "background 150ms, color 150ms",
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.background = "var(--color-accent-subtle)";
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.background = "transparent";
        }}
      >
        <Icon size={13} style={{ color: "var(--color-text-faint)", flexShrink: 0 }} />
        <span style={labelStyle}>{title}</span>
        {count != null && count > 0 && (
          <span style={{ ...labelStyle, opacity: 0.6, marginLeft: -4 }}>{count}</span>
        )}
        <span style={{ flex: 1 }} />
        <ChevronRight
          size={12}
          style={{
            color: "var(--color-text-faint)",
            transform: open ? "rotate(90deg)" : "rotate(0)",
            transition: "transform 120ms ease",
          }}
        />
      </button>
      {open && (
        <div
          style={{
            paddingBottom: 12,
            fontFamily: sans,
            fontSize: 11,
            color: "var(--color-text-muted)",
          }}
        >
          {children}
        </div>
      )}
    </div>
  );
}
const Section = React.memo(SectionInner);

/* -- Memoised sub-sections -- */

const ArtifactsSection = React.memo(function ArtifactsSection({
  artifacts,
  staged,
  nodeId,
  revision,
  onRefresh,
}: {
  artifacts: Artifact[];
  staged: boolean;
  nodeId: string;
  revision: number;
  onRefresh: () => Promise<void>;
}) {
  const [uploading, setUploading] = useState(false);
  const [uploadErr, setUploadErr] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [localArtifacts, setLocalArtifacts] = useState(artifacts);

  useEffect(() => {
    setLocalArtifacts(artifacts);
  }, [artifacts]);

  const doUpload = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      if (!e.target.files?.length) return;
      const f = e.target.files[0];
      setUploading(true);
      setUploadErr(null);
      try {
        const ext = f.name.split(".").pop()?.toLowerCase() || "";
        let at: ArtifactType = "binary";
        if (["png", "jpg", "jpeg", "gif", "webp", "svg"].includes(ext)) at = "image";
        else if (ext === "json") at = "json";
        else if (["csv", "tsv"].includes(ext)) at = "table";
        else if (["txt", "md", "log"].includes(ext)) at = "text";
        else if (["html", "htm"].includes(ext)) at = "html";
        const prep = (await api.prepareUploads({
          node_id: nodeId,
          expected_revision: revision,
          items: [
            {
              artifact_type: at,
              filename: f.name,
              media_type: f.type || "application/octet-stream",
              title: f.name,
            },
          ],
        })) as { batch_token: string; items: { upload_url: string }[] };
        let url = prep.items[0].upload_url;
        if (url.startsWith("/")) url = BASE_URL.replace(/\/api$/, "") + url;
        await api.uploadArtifactBytes(url, f);
        await api.finalizeUploads({ node_id: nodeId, batch_token: prep.batch_token });
        setLocalArtifacts(await api.listArtifacts(nodeId));
        await onRefresh();
      } catch (err: unknown) {
        setUploadErr(errorMessage(err));
      }
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    },
    [nodeId, revision, onRefresh],
  );

  return (
    <Section title="evidence" icon={Paperclip} count={localArtifacts.length} open={localArtifacts.length > 0}>
      <ArtifactList artifacts={localArtifacts} />
      {staged && (
        <div style={{ marginTop: 8 }}>
          <input ref={fileRef} type="file" style={{ display: "none" }} onChange={doUpload} />
          <button
            onClick={() => fileRef.current?.click()}
            disabled={uploading}
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: 5,
              fontFamily: mono,
              fontSize: 10,
              color: "var(--color-text-faint)",
              background: "none",
              border: "1px dashed var(--color-border)",
              borderRadius: 2,
              padding: "7px 10px",
              cursor: "pointer",
              width: "100%",
              transition: "all 120ms",
            }}
          >
            <Upload size={11} />
            {uploading ? "uploading..." : "upload artifact"}
          </button>
          {uploadErr && (
            <p style={{ fontFamily: mono, fontSize: 10, color: "var(--color-error)", marginTop: 4 }}>{uploadErr}</p>
          )}
        </div>
      )}
    </Section>
  );
});

const TagsSection = React.memo(function TagsSection({
  graphTags,
  assignedTagIds,
  nodeId,
  revision,
  onRefresh,
}: {
  graphTags: GraphTag[];
  assignedTagIds: string[];
  nodeId: string;
  revision: number;
  onRefresh: () => Promise<void>;
}) {
  const getFreshRoot = useCallback(async () => {
    const sharing = await api.getSharing(nodeId);
    const rootId = sharing.project_id || sharing.node_id || nodeId;
    return api.getNode(rootId, "core", { fresh: true });
  }, [nodeId]);

  const onToggleTag = useCallback(
    async (tagId: string, on: boolean) => {
      const ids = on
        ? [...assignedTagIds, tagId]
        : assignedTagIds.filter((x) => x !== tagId);
      await api.setTagAssignments({
        node_id: nodeId,
        expected_revision: revision,
        tag_ids: ids,
      });
      await onRefresh();
    },
    [nodeId, revision, assignedTagIds, onRefresh],
  );
  const onCreateTag = useCallback(
    async (t: { name: string; bg_color: string; text_color: string }) => {
      const root = await getFreshRoot();
      await api.createTag({
        root_node_id: root.node_id,
        expected_revision: root.revision,
        ...t,
      });
      await onRefresh();
    },
    [getFreshRoot, onRefresh],
  );
  const onDeleteTag = useCallback(
    async (id: string) => {
      const root = await getFreshRoot();
      await api.deleteTag({
        root_node_id: root.node_id,
        tag_id: id,
        expected_revision: root.revision,
      });
      await onRefresh();
    },
    [getFreshRoot, onRefresh],
  );

  return (
    <Section title="tags" icon={Tag} count={assignedTagIds.length}>
      <TagManager
        graphTags={graphTags}
        assignedTagIds={assignedTagIds}
        onToggleTag={onToggleTag}
        onCreateTag={onCreateTag}
        onDeleteTag={onDeleteTag}
      />
    </Section>
  );
});

const SharingSection = React.memo(function SharingSection({
  nodeId,
}: {
  nodeId: string;
}) {
  const [sharing, setSharing] = useState<SharingInfo | null>(null);

  useEffect(() => {
    api.getSharing(nodeId).then(setSharing).catch(() => {});
  }, [nodeId]);

  const onSharingMode = useCallback(
    async (m: SharingMode) => {
      setSharing(await api.setSharing(nodeId, { node_id: nodeId, sharing_mode: m }));
    },
    [nodeId],
  );
  const onAddCollab = useCallback(
    async (email: string, role: Collaborator["role"]) => {
      if (!sharing) return;
      const c = [...sharing.collaborators, { email, role }];
      setSharing(await api.setSharing(nodeId, { node_id: nodeId, collaborators: c }));
    },
    [nodeId, sharing],
  );
  const onRemoveCollab = useCallback(
    async (email: string) => {
      if (!sharing) return;
      const c = sharing.collaborators.filter((x) => x.email !== email);
      setSharing(await api.setSharing(nodeId, { node_id: nodeId, collaborators: c }));
    },
    [nodeId, sharing],
  );

  return (
    <Section title="sharing" icon={Users}>
      {sharing && (
        <SharingPanel
          sharingInfo={sharing}
          onChangeMode={onSharingMode}
          onAddCollaborator={onAddCollab}
          onRemoveCollaborator={onRemoveCollab}
        />
      )}
    </Section>
  );
});

const repoRowStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 8,
  fontFamily: mono,
  fontSize: 10,
  lineHeight: 1.6,
};
const repoRowLabel: React.CSSProperties = {
  color: "var(--color-text-faint)",
  flexShrink: 0,
};
const repoRowValue: React.CSSProperties = {
  color: "var(--color-text)",
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
  textAlign: "right",
};
const repoLinkStyle: React.CSSProperties = {
  ...repoRowValue,
  textDecoration: "none",
};

/* GEPA optimize-run telemetry for control nodes (semantic_data.type === "optimize_run") */
const OptimizationSection = React.memo(function OptimizationSection({
  run,
}: {
  run: OptimizeRun;
}) {
  const used = run.budgetUsed;
  const total = run.budgetTotal;
  const pct =
    used != null && total != null && total > 0
      ? Math.min(100, Math.max(0, (used / total) * 100))
      : null;
  const statusColor =
    run.status === "done"
      ? "var(--color-success)"
      : run.status === "error"
        ? "var(--color-error)"
        : run.status === "stopped"
          ? "var(--color-warning)"
          : "var(--color-accent)";
  return (
    <Section title="optimization" icon={Gauge} open>
      {run.objective && (
        <p
          style={{
            fontFamily: sans,
            fontSize: 12.5,
            lineHeight: 1.55,
            color: "var(--color-text)",
            margin: "0 0 10px",
          }}
        >
          {run.objective}
        </p>
      )}

      {run.target && (
        <div style={repoRowStyle}>
          <span style={repoRowLabel}>target</span>
          <span style={repoRowValue} title={run.target}>{run.target}</span>
        </div>
      )}
      {run.metric && (
        <div style={repoRowStyle}>
          <span style={repoRowLabel}>metric</span>
          <span style={repoRowValue}>{run.metric}</span>
        </div>
      )}
      {run.status && (
        <div style={repoRowStyle}>
          <span style={repoRowLabel}>status</span>
          <span style={{ ...repoRowValue, display: "inline-flex", alignItems: "center", gap: 5 }}>
            <span
              aria-hidden
              style={{
                width: 5,
                height: 5,
                borderRadius: "50%",
                flexShrink: 0,
                background: statusColor,
                animation: run.status === "running" ? "pulse 1.6s ease-in-out infinite" : undefined,
              }}
            />
            {run.status}
          </span>
        </div>
      )}

      {used != null && (
        <div style={{ margin: "4px 0 8px" }}>
          <div style={{ ...repoRowStyle, marginBottom: 4 }}>
            <span style={repoRowLabel}>budget</span>
            <span style={repoRowValue}>
              {total != null ? `${used}/${total} evals` : `${used} evals`}
            </span>
          </div>
          {pct != null && (
            <div
              aria-hidden
              style={{
                height: 4,
                borderRadius: 2,
                background: "var(--color-bg-subtle)",
                border: "1px solid var(--color-border)",
                overflow: "hidden",
              }}
            >
              <span
                style={{
                  display: "block",
                  height: "100%",
                  width: `${pct}%`,
                  borderRadius: 2,
                  background: "var(--color-accent)",
                }}
              />
            </div>
          )}
        </div>
      )}

      {(run.bestScore != null || run.bestNodeId) && (
        <div style={repoRowStyle}>
          <span style={repoRowLabel}>best</span>
          {run.bestNodeId ? (
            <RouterLink
              to={`/nodes/${run.bestNodeId}`}
              title="open best candidate node"
              style={{ ...repoLinkStyle, color: "var(--color-text)" }}
            >
              {run.bestScore != null ? formatScore(run.bestScore) : "candidate"} →
            </RouterLink>
          ) : (
            <span style={repoRowValue}>{formatScore(run.bestScore!)}</span>
          )}
        </div>
      )}
      {run.candidatesEvaluated != null && (
        <div style={repoRowStyle}>
          <span style={repoRowLabel}>candidates</span>
          <span style={repoRowValue}>{run.candidatesEvaluated}</span>
        </div>
      )}
      {run.paretoSize != null && (
        <div style={repoRowStyle}>
          <span style={repoRowLabel}>pareto</span>
          <span style={repoRowValue}>{run.paretoSize}</span>
        </div>
      )}
      {run.stopReason && (
        <div style={repoRowStyle}>
          <span style={repoRowLabel}>stop reason</span>
          <span style={{ ...repoRowValue, color: "var(--color-warning)" }}>{run.stopReason}</span>
        </div>
      )}
      {run.updatedAt && (
        <div style={repoRowStyle}>
          <span style={repoRowLabel}>updated</span>
          <span style={repoRowValue} title={run.updatedAt}>{timeAgo(run.updatedAt)}</span>
        </div>
      )}
    </Section>
  );
});

const RepositorySection = React.memo(function RepositorySection({
  repoUrl,
  branchName,
  headCommitSha,
  staged,
  nodeId,
  revision,
  onRefresh,
}: {
  repoUrl: string | null;
  branchName: string | null;
  headCommitSha: string | null;
  staged: boolean;
  nodeId: string;
  revision: number;
  onRefresh: () => Promise<void>;
}) {
  const [repoInput, setRepoInput] = useState(repoUrl || "");

  useEffect(() => {
    setRepoInput(repoUrl || "");
  }, [repoUrl]);

  if (!repoUrl && !branchName && !headCommitSha && !staged) return null;

  const repoHref = repoUrl
    ? repoUrl.startsWith("http")
      ? repoUrl
      : `https://${repoUrl}`
    : null;

  const commitHref =
    headCommitSha && repoUrl
      ? `https://${repoUrl.replace(/^https?:\/\//, "")}/commit/${headCommitSha}`
      : null;

  const saveRepoUrl = async () => {
    const v = repoInput.trim();
    if (v === (repoUrl || "")) return;
    await api.stageUpdate({
      node_id: nodeId,
      expected_revision: revision,
      repo_url: v || null,
    });
    await onRefresh();
  };

  return (
    <Section title="repository" icon={GitBranch}>
      <div style={repoRowStyle}>
        <span style={repoRowLabel}>repo_url</span>
        {repoUrl ? (
          <a
            href={repoHref!}
            target="_blank"
            rel="noopener noreferrer"
            style={repoLinkStyle}
          >
            {repoUrl}
          </a>
        ) : staged ? (
          <input
            value={repoInput}
            onChange={(e) => setRepoInput(e.target.value)}
            onBlur={saveRepoUrl}
            onKeyDown={(e) => e.key === "Enter" && saveRepoUrl()}
            placeholder="owner/repo"
            style={{
              fontFamily: mono,
              fontSize: 10,
              color: "var(--color-text)",
              background: "none",
              border: "1px solid var(--color-border)",
              borderRadius: 2,
              padding: "2px 6px",
              outline: "none",
              width: 120,
              textAlign: "right",
            }}
          />
        ) : (
          <span style={{ ...repoRowValue, color: "var(--color-text-faint)" }}>--</span>
        )}
      </div>

      {branchName && (
        <div style={repoRowStyle}>
          <span style={repoRowLabel}>branch</span>
          <span style={repoRowValue}>{branchName}</span>
        </div>
      )}

      {headCommitSha && (
        <div style={repoRowStyle}>
          <span style={repoRowLabel}>commit</span>
          {commitHref ? (
            <a
              href={commitHref}
              target="_blank"
              rel="noopener noreferrer"
              style={repoLinkStyle}
            >
              {headCommitSha.slice(0, 7)}
            </a>
          ) : (
            <span style={repoRowValue}>{headCommitSha.slice(0, 7)}</span>
          )}
        </div>
      )}
    </Section>
  );
});

const AuditSection = React.memo(function AuditSection({ audit }: { audit: AuditEvent[] }) {
  return (
    <Section title="audit" icon={History} count={audit.length}>
      {audit.length === 0 ? (
        <p style={{ fontFamily: mono, fontSize: 10, color: "var(--color-text-faint)" }}>no events</p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {audit.map((ev, i) => (
            <div
              key={i}
              style={{
                fontFamily: mono,
                fontSize: 10,
                color: "var(--color-text-faint)",
                display: "flex",
                justifyContent: "space-between",
              }}
            >
              <span>{ev.operation || "event"}</span>
              <span style={{ opacity: 0.5 }}>
                {new Date(ev.timestamp).toLocaleTimeString("en-US", {
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </span>
            </div>
          ))}
        </div>
      )}
    </Section>
  );
});

const ExportSection = React.memo(function ExportSection({ nodeId }: { nodeId: string }) {
  return (
    <Section title="export" icon={Download}>
      <ExportPanel nodeId={nodeId} />
    </Section>
  );
});

/* ================================================================
   NodeSidebar -- right column with actions, checklist, sections
   ================================================================ */

interface NodeSidebarProps {
  nodeId: string;
  staged: boolean;
  allOk: boolean;
  checklist: CheckItem[];
  actLoad: string | null;
  repoUrl: string | null;
  branchName: string | null;
  headCommitSha: string | null;
  revision: number;
  graphTags: GraphTag[];
  assignedTagIds: string[];
  contractWarnings?: { code: string; message: string }[];
  slugName?: string | null;
  kind?: string;
  outcome?: string | null;
  /** Raw semantic_data (object or JSON string, depending on backend path). */
  semanticData?: Record<string, unknown> | string | null;
  artifacts: Artifact[];
  onCommit: () => void;
  onBranch: () => void;
  onDelete: () => void;
  onRefresh: () => Promise<void>;
}

export function NodeSidebar({
  nodeId,
  staged,
  allOk,
  checklist,
  actLoad,
  repoUrl,
  branchName,
  headCommitSha,
  revision,
  graphTags,
  assignedTagIds,
  contractWarnings,
  semanticData,
  artifacts,
  onCommit,
  onBranch,
  onDelete,
  onRefresh,
}: NodeSidebarProps) {
  const [audit, setAudit] = useState<AuditEvent[]>([]);
  const optimizeRun = optimizeRunOf({ semantic_data: semanticData ?? null });

  useEffect(() => {
    api.listAudit(nodeId, 20).then(setAudit).catch(() => setAudit([]));
  }, [nodeId]);

  return (
    <aside
      className="node-sidebar"
      style={{
        flex: 4,
        overflowY: "auto",
        padding: "24px 20px",
        background: "var(--color-bg-subtle)",
        borderLeft: "1px solid var(--color-border)",
        display: "flex",
        flexDirection: "column",
      }}
    >
      {/* Actions row */}
      <div style={{ display: "flex", gap: 6, marginBottom: 14 }}>
        {staged && (
          <button
            onClick={onCommit}
            disabled={!allOk || !!actLoad}
            style={{
              flex: 1,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: 6,
              fontFamily: mono,
              fontSize: 11,
              fontWeight: allOk ? 600 : 500,
              padding: "8px 0",
              borderRadius: 2,
              border: `1px solid ${allOk ? "var(--color-text)" : "var(--color-border)"}`,
              background: allOk ? "var(--color-text)" : "var(--color-bg-elevated)",
              color: allOk ? "var(--color-bg)" : "var(--color-text-faint)",
              cursor: allOk ? "pointer" : "not-allowed",
              opacity: actLoad === "commit" ? 0.5 : 1,
              transition: "background 150ms, border-color 150ms, color 150ms, opacity 150ms",
              letterSpacing: "0.02em",
            }}
            onMouseEnter={(e) => {
              if (allOk) e.currentTarget.style.background = "var(--color-accent-hover)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = allOk
                ? "var(--color-text)"
                : "var(--color-bg-elevated)";
            }}
            title={allOk ? "commit this staged node" : "commit gate not met"}
          >
            <Check size={13} strokeWidth={allOk ? 2.4 : 1.6} />
            {actLoad === "commit" ? "committing…" : "commit"}
          </button>
        )}
        <button
          onClick={onBranch}
          disabled={!!actLoad}
          style={{
            flex: 1,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 5,
            fontFamily: mono,
            fontSize: 11,
            fontWeight: 500,
            padding: "8px 0",
            borderRadius: 2,
            border: "1px solid var(--color-border)",
            background: "var(--color-bg-elevated)",
            color: "var(--color-text-muted)",
            cursor: "pointer",
            opacity: actLoad === "branch" ? 0.5 : 1,
            transition: "background 150ms, border-color 150ms, color 150ms, opacity 150ms",
            letterSpacing: "0.02em",
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.borderColor = "var(--color-text-muted)";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.borderColor = "var(--color-border)";
          }}
          title="create a child node"
        >
          <GitBranch size={13} />
          {actLoad === "branch" ? "branching…" : "branch"}
        </button>
        <button
          onClick={onDelete}
          disabled={!!actLoad}
          title="delete node"
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontFamily: mono,
            fontSize: 11,
            padding: "8px 10px",
            borderRadius: 2,
            border: "1px solid var(--color-border)",
            background: "var(--color-bg-elevated)",
            color: "var(--color-text-faint)",
            cursor: "pointer",
            opacity: actLoad === "delete" ? 0.5 : 1,
            transition: "background 150ms, border-color 150ms, color 150ms, opacity 150ms",
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.borderColor = "var(--color-text-muted)";
            e.currentTarget.style.color = "var(--color-error)";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.borderColor = "var(--color-border)";
            e.currentTarget.style.color = "var(--color-text-faint)";
          }}
        >
          <Trash2 size={13} />
        </button>
      </div>

      {/* Commit checklist (staged only) */}
      {staged && (
        <CommitChecklist
          checklist={checklist}
          warnings={contractWarnings}
          revision={revision}
        />
      )}

      {/* Collapsible sections */}
      {optimizeRun && <OptimizationSection run={optimizeRun} />}

      <ArtifactsSection
        artifacts={artifacts}
        staged={staged}
        nodeId={nodeId}
        revision={revision}
        onRefresh={onRefresh}
      />

      <TagsSection
        graphTags={graphTags}
        assignedTagIds={assignedTagIds}
        nodeId={nodeId}
        revision={revision}
        onRefresh={onRefresh}
      />

      <SharingSection nodeId={nodeId} />

      <RepositorySection
        repoUrl={repoUrl}
        branchName={branchName}
        headCommitSha={headCommitSha}
        staged={staged}
        nodeId={nodeId}
        revision={revision}
        onRefresh={onRefresh}
      />

      <AuditSection audit={audit} />

      <ExportSection nodeId={nodeId} />
    </aside>
  );
}
