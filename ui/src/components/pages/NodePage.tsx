import { useState, useCallback, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useNodeStore } from "../../stores/nodeStore.js";
import { api } from "../../api/client.js";
import { ArrowLeft } from "lucide-react";
import { NodeEditor } from "../node/NodeEditor.js";
import { NodeSidebar } from "../node/NodeSidebar.js";
import { getChecklist } from "../node/CommitChecklist.js";
import { ErrorAlert, IconButton, LoadingSpinner, Button } from "../shared/index.js";
import { FONT_MONO, ICON_SIZE, Z } from "../../styles/tokens.js";
import { useConfirm } from "../../lib/useConfirm.js";
import { useToast } from "../../lib/useToast.js";
import { errorMessage } from "../../lib/errors.js";
import type { Artifact } from "../../api/types.js";

const EMPTY_ARTIFACTS: Artifact[] = [];

export function NodePage() {
  const { nodeId } = useParams<{ nodeId: string }>();
  const nav = useNavigate();
  const selectNode = useNodeStore((s) => s.selectNode);
  const node = useNodeStore((s) => s.selectedNode);
  const loading = useNodeStore((s) => s.detailLoading);
  const error = useNodeStore((s) => s.detailError);
  const commitNode = useNodeStore((s) => s.commitNode);
  const branchNode = useNodeStore((s) => s.branchNode);
  const deleteNode = useNodeStore((s) => s.deleteNode);
  const refresh = useNodeStore((s) => s.refreshSelectedNode);

  const [actLoad, setActLoad] = useState<string | null>(null);
  const [actErr, setActErr] = useState<string | null>(null);
  const confirm = useConfirm();
  const toast = useToast();

  useEffect(() => { if (nodeId) selectNode(nodeId); }, [nodeId, selectNode]);

  const save = useCallback(async (fields: Record<string, unknown>) => {
    if (!node) return;
    setActErr(null);
    try {
      await api.stageUpdate({ node_id: node.node_id, expected_revision: node.revision, ...fields });
      await refresh();
    } catch (e: unknown) {
      const msg = errorMessage(e) || "Save failed";
      setActErr(msg);
      throw e;
    }
  }, [node, refresh]);

  const doAction = useCallback(async (key: string, fn: () => Promise<void>) => {
    setActLoad(key); setActErr(null);
    try { await fn(); } catch (e: unknown) { setActErr(errorMessage(e)); }
    setActLoad(null);
  }, []);

  const doCommit = useCallback(() => {
    if (!node) return;
    return doAction("commit", async () => {
      await commitNode(node.node_id);
      toast.success("Node committed");
    });
  }, [node, commitNode, doAction, toast]);

  const doBranch = useCallback(() => {
    if (!node) return;
    const t = window.prompt("child node title:");
    if (t === null) return;
    return doAction("branch", async () => {
      const n = await branchNode(node.node_id, t || undefined);
      toast.success("Branched node");
      nav(`/nodes/${n.node_id}`);
    });
  }, [node, branchNode, nav, doAction, toast]);

  const doDelete = useCallback(async () => {
    if (!node) return;
    const ok = await confirm({
      title: "Delete node?",
      message: `"${node.title || "untitled"}" will be permanently removed.`,
      confirmLabel: "Delete",
      confirmVariant: "danger",
    });
    if (!ok) return;
    return doAction("delete", async () => {
      await deleteNode(node.node_id);
      toast.success("Node deleted");
      nav("/graphs");
    });
  }, [node, deleteNode, nav, doAction, confirm, toast]);

  /* loading / error guards */
  if (loading && !node)
    return (
      <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", background: "var(--color-bg)" }}>
        <LoadingSpinner size={20} />
      </div>
    );
  if (error)
    return (
      <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 12, padding: 24, background: "var(--color-bg)" }}>
        <ErrorAlert message={error} />
        <Button variant="secondary" size="sm" onClick={() => nav("/graphs")}>Back to graphs</Button>
      </div>
    );
  if (!node) return null;

  const ck = getChecklist({
    kind: node.kind,
    outcome: node.outcome,
    summary: node.summary,
    content: node.content,
    insights: node.insights,
    hypothesis: node.hypothesis,
    no_artifacts_reason: node.no_artifacts_reason,
    artifacts_total: node.artifacts_total ?? null,
  });
  const allOk = ck.every((c) => c.ok);
  const staged = node.lifecycle === "staged";
  const artifacts = node.artifacts ?? EMPTY_ARTIFACTS;
  const statusKey = staged ? "staged" : node.outcome || "committed";
  const statusFg =
    statusKey === "completed"
      ? "var(--color-success)"
      : statusKey === "failed"
        ? "var(--color-error)"
        : statusKey === "canceled"
          ? "var(--color-warning)"
          : "var(--color-text-muted)";
  const statusBg =
    statusKey === "completed"
      ? "var(--color-success-muted)"
      : statusKey === "failed"
        ? "var(--color-error-muted)"
        : statusKey === "canceled"
          ? "var(--color-warning-muted)"
          : "var(--color-accent-subtle)";

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", background: "var(--color-bg)", minHeight: 0 }}>
      {/* top bar */}
      <header style={{ position: "sticky", top: 0, zIndex: Z.header, display: "flex", alignItems: "center", gap: 12, padding: "8px 20px", background: "var(--color-bg)", borderBottom: "1px solid var(--color-border)", minHeight: 46 }}>
        <IconButton
          icon={<ArrowLeft size={ICON_SIZE.xl} />}
          label="Back to graphs"
          variant="subtle"
          onClick={() => nav("/graphs")}
        />
        <span style={{ fontFamily: FONT_MONO, fontSize: 11, color: "var(--color-text-faint)", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {node.slug_name || node.node_id.slice(0, 8)}
        </span>
        <span style={{ fontFamily: FONT_MONO, fontSize: 10, fontWeight: 600, letterSpacing: "0.06em", padding: "3px 9px", borderRadius: 2, background: statusBg, color: statusFg, border: `1px solid ${statusBg}` }}>
          {staged ? "staged" : node.outcome || "committed"}
        </span>
      </header>

      {/* two-column body */}
      <div style={{ display: "flex", flex: 1, minHeight: 0, overflow: "hidden" }}>
        <NodeEditor
          nodeId={node.node_id}
          slugName={node.slug_name} title={node.title} kind={node.kind} revision={node.revision}
          updatedAt={node.updated_at} staged={staged} summary={node.summary}
          content={node.content} hypothesis={node.hypothesis}
          insights={node.insights} outcome={node.outcome}
          noArtifactsReason={node.no_artifacts_reason}
          artifactsTotal={node.artifacts_total ?? null}
          artifacts={artifacts}
          semanticData={node.semantic_data ?? null}
          repoUrl={node.repo_url} branchName={node.branch_name}
          headCommitSha={node.head_commit_sha}
          save={save} actErr={actErr}
        />
        <NodeSidebar
          nodeId={node.node_id} staged={staged} allOk={allOk}
          checklist={ck} actLoad={actLoad} repoUrl={node.repo_url}
          branchName={node.branch_name} headCommitSha={node.head_commit_sha}
          revision={node.revision} graphTags={node.graph_tags || []}
          assignedTagIds={node.tag_ids || []}
          contractWarnings={node.contract_warnings || []}
          slugName={node.slug_name}
          kind={node.kind} outcome={node.outcome}
          semanticData={node.semantic_data ?? null}
          artifacts={artifacts}
          onCommit={doCommit} onBranch={doBranch} onDelete={doDelete}
          onRefresh={refresh}
        />
      </div>
    </div>
  );
}
