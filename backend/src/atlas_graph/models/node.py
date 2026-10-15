from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from .common import NodeKind, NodeLifecycle, NodeOutcome, Projection


class GraphTag(BaseModel):
    tag_id: str
    name: str
    bg_color: str
    text_color: str
    one_only: bool = False
    track_history: bool = False
    history_next_index: int | None = None


class Node(BaseModel):
    node_id: str
    slug_name: str | None = None
    title: str | None = None
    summary: str | None = None
    content: str | None = None
    updated_by: str | None = None

    kind: NodeKind = NodeKind.untyped
    lifecycle: NodeLifecycle = NodeLifecycle.staged
    outcome: NodeOutcome | None = None

    hypothesis: str | None = None
    no_artifacts_reason: str | None = None
    insights: list[str] = Field(default_factory=list)

    parent_ids: list[str] = Field(default_factory=list)
    child_ids: list[str] = Field(default_factory=list)

    repo_url: str | None = None
    branch_name: str | None = None
    head_commit_sha: str | None = None
    origin_host: str | None = None
    external_transcript_ref: str | None = None

    revision: int = 0

    graph_tags: list[GraphTag] = Field(default_factory=list)
    tag_ids: list[str] = Field(default_factory=list)
    tag_history: list[dict[str, Any]] = Field(default_factory=list)

    is_owner: bool | None = None
    visibility: str | None = None
    can_write: bool | None = None
    can_admin: bool | None = None
    owner_email: str | None = None

    artifacts_total: int | None = None
    artifacts_truncated: bool | None = None

    created_at: str = ""
    updated_at: str = ""

    # graph_projection ("core" | "full") and contract_warnings are both
    # populated by node_service for every response — kept; the three
    # previously-defined ``home_domain`` / ``hidden_incoming_count`` /
    # ``hidden_outgoing_count`` fields had no writer anywhere in the codebase
    # and were dropped in PR #118.
    graph_projection: Projection | None = None
    contract_warnings: list[dict[str, str]] | None = None


class StageNodeCreateRequest(BaseModel):
    title: str | None = None
    summary: str | None = None
    content: str | None = None
    kind: NodeKind | None = None
    hypothesis: str | None = None
    parent_ids: list[str] | None = None
    repo_url: str | None = None
    branch_name: str | None = None
    head_commit_sha: str | None = None
    origin_host: str | None = None
    updated_by: str | None = None
    external_transcript_ref: str | None = None


class StageNodeUpdateRequest(BaseModel):
    node_id: str
    expected_revision: int
    title: str | None = None
    summary: str | None = None
    content: str | None = None
    kind: NodeKind | None = None
    outcome: NodeOutcome | None = None
    hypothesis: str | None = None
    no_artifacts_reason: str | None = None
    insights: list[str] | None = None
    updated_by: str | None = None
    repo_url: str | None = None
    branch_name: str | None = None
    head_commit_sha: str | None = None
    origin_host: str | None = None
    external_transcript_ref: str | None = None


class CommitNodeRequest(BaseModel):
    node_id: str
    expected_revision: int
    summary: str | None = None


class BranchNodeRequest(BaseModel):
    node_id: str
    expected_revision: int
    title: str | None = None
    updated_by: str | None = None


class MergeNodesRequest(BaseModel):
    node_ids: list[str]
    expected_revision_by_node: dict[str, int]
    resolved_node: dict[str, Any]
    title: str | None = None
    updated_by: str | None = None


class AddParentRequest(BaseModel):
    node_id: str
    parent_id: str
    expected_revision: int
    expected_parent_revision: int
    updated_by: str | None = None


class RemoveParentRequest(BaseModel):
    node_id: str
    parent_id: str
    expected_revision: int
    expected_parent_revision: int
    updated_by: str | None = None


class DeleteNodeRequest(BaseModel):
    node_id: str
    delete_mode: str = "cascade"


class BulkDeleteRequest(BaseModel):
    node_ids: list[str]


class ListNodesRequest(BaseModel):
    owners: list[str] | None = None
    writers: list[str] | None = None
    visibility: str | None = None
    kind: str | None = None
    lifecycle: str | None = None
    outcome: str | None = None
    root_only: bool | None = None
    repo_url: str | None = None
    projection: str = "core"
    page: int = 1
    per_page: int = 50


class NodeTreeResponse(BaseModel):
    anchor_node_id: str
    root_node_ids: list[str]
    nodes: list[Node]
    node_count: int


class BulkDeleteResponse(BaseModel):
    success: bool
    deleted_count: int
    deleted_node_ids: list[str]
    skipped_non_owned: list[str]
    graph_event_id: str
