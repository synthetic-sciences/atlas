export type NodeKind = "untyped" | "empirical" | "insight" | "hypothesis" | "decision";
export type NodeLifecycle = "staged" | "committed";
export type NodeOutcome = "completed" | "failed" | "canceled";
export type SharingMode = "private" | "public" | "unlisted";
export type ArtifactType =
  | "text"
  | "table"
  | "json"
  | "image"
  | "banner"
  | "html"
  | "plotly_html"
  | "vega"
  | "checkpoint"
  | "binary"
  | "diff_carousel";

// Backend ``TagHistoryEntry`` (backend/app/models/tag.py) — kept in sync with
// the wire shape so consumers can render history without falling back to any.
export interface TagHistoryEntry {
  tag_id: string;
  history_index: number;
  superseded_at: string;
  superseded_by_node_id: string;
}

export interface GraphTag {
  tag_id: string;
  name: string;
  bg_color: string;
  text_color: string;
  one_only: boolean;
  track_history: boolean;
  history_next_index?: number;
}

export interface Node {
  node_id: string;
  slug_name: string | null;
  title: string | null;
  summary: string | null;
  content: string | null;
  updated_by: string | null;
  kind: NodeKind;
  lifecycle: NodeLifecycle;
  outcome: NodeOutcome | null;
  hypothesis: string | null;
  no_artifacts_reason: string | null;
  insights: string[];
  parent_ids: string[];
  child_ids: string[];
  repo_url: string | null;
  branch_name: string | null;
  head_commit_sha: string | null;
  origin_host: string | null;
  external_transcript_ref: string | null;
  revision: number;
  graph_tags: GraphTag[];
  tag_ids: string[];
  tag_history: TagHistoryEntry[];
  sharing_mode?: SharingMode;
  is_owner?: boolean;
  visibility?: string;
  can_write?: boolean;
  can_admin?: boolean;
  owner_email?: string;
  artifacts_total?: number;
  artifacts?: Artifact[];
  contract_warnings?: { code: string; message: string }[];
  /** Optional structured payload some backends attach (e.g. failure_mode, criterion_met). */
  semantic_data?: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
  graph_projection?: string;
}

export interface Artifact {
  artifact_id: string;
  artifact_type: ArtifactType;
  title: string;
  filename?: string;
  note: string | null;
  payload: unknown;
  metadata: Record<string, unknown>;
  execution_id: string | null;
  storage_path: string;
  storage_url?: string;
  created_at: string;
}

export interface AuditEvent {
  event_id: string;
  actor_user_id: string;
  oauth_client_id: string;
  node_id: string;
  operation: string;
  idempotency_key: string;
  expected_revision: number | null;
  result_revision: number;
  request_hash: string;
  timestamp: string;
}

export interface Collaborator {
  email: string;
  role: "viewer" | "editor" | "admin";
}

export interface SharingInfo {
  node_id: string;
  /** Root graph/project whose sharing policy is being shown. */
  project_id?: string;
  /** Node originally requested by the UI; sharing still applies at project_id. */
  requested_node_id?: string;
  owner_user_id: string;
  owner_email: string;
  is_owner: boolean;
  /** Server-authoritative collaboration entitlement for the graph owner. */
  collaboration_enabled: boolean;
  sharing_mode: SharingMode;
  visibility: string;
  effective: { can_view: boolean; can_write: boolean; can_admin: boolean };
  collaborators: Collaborator[];
  updated_at: string;
}

export interface NodeListResponse {
  nodes: Node[];
  total: number;
  page: number;
  per_page: number;
  has_more: boolean;
}

export interface NodeTreeResponse {
  anchor_node_id: string;
  root_node_ids: string[];
  nodes: Node[];
  node_count: number;
}

// Campaign types

export interface CampaignBudget {
  budget_id: string;
  root_node_id: string;
  organizer_user_id: string;
  participant_user_id: string | null;
  hard_cap_cents: number;
  spent_cents: number;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface CampaignSubmission {
  node_id: string;
  title: string | null;
  owner: string | null;
  outcome: string | null;
  artifact_id: string;
}

export interface CampaignSnapshot {
  root_node_id: string;
  root_title: string;
  node_count: number;
  kind_counts: Record<string, number>;
  lifecycle_counts: Record<string, number>;
  outcome_counts: Record<string, number>;
  budgets: CampaignBudget[];
  config_status: string;
  submissions: CampaignSubmission[];
  submission_count: number;
  has_leaderboard: boolean;
}

export interface CampaignBudgetsResponse {
  budgets: CampaignBudget[];
}

// ---------------------------------------------------------------------------
// Node mutation request types
// ---------------------------------------------------------------------------

export interface AddParentRequest {
  node_id: string;
  parent_id: string;
  expected_revision: number;
  expected_parent_revision: number;
}

export interface RemoveParentRequest {
  node_id: string;
  parent_id: string;
  expected_revision: number;
  expected_parent_revision: number;
}

export interface MergeNodesRequest {
  node_ids: string[];
  expected_revision_by_node: Record<string, number>;
  resolved_node: Record<string, unknown>;
}
