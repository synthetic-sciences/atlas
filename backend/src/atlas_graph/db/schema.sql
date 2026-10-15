-- Graph-only SQLite baseline extracted from 566904ae.
CREATE TABLE IF NOT EXISTS users (
 user_id TEXT PRIMARY KEY,
 email TEXT UNIQUE NOT NULL,
 display_name TEXT,
 github_username TEXT,
 avatar_url TEXT,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 deleted_at TEXT
);

CREATE TABLE artifact_upload_batches (
    batch_token         TEXT PRIMARY KEY,
    node_id             TEXT NOT NULL REFERENCES nodes(node_id) ON DELETE CASCADE,
    expected_revision   INTEGER NOT NULL,
    items               TEXT NOT NULL,
    expires_at          TEXT NOT NULL,
    created_at          TEXT NOT NULL
);

CREATE TABLE artifacts (
    artifact_id         TEXT PRIMARY KEY,
    node_id             TEXT NOT NULL REFERENCES nodes(node_id) ON DELETE CASCADE,
    artifact_type       TEXT NOT NULL,
    title               TEXT NOT NULL,
    note                TEXT,
    payload             TEXT NOT NULL DEFAULT '{}',
    metadata            TEXT NOT NULL DEFAULT '{}',
    execution_id        TEXT,
    storage_path        TEXT,
    -- Harness Phase 2: assets registered from the project volume.
    -- A "volume asset" has volume_path set and auto-pins to the project root
    -- (node_id = root_id) until explicitly re-pinned to a descendant.
    volume_path         TEXT,
    storage_url         TEXT,
    mime                TEXT,
    size_bytes          INTEGER,
    created_by_agent_id TEXT,
    project_id          TEXT,
    created_at          TEXT NOT NULL
);

CREATE TABLE audit_events (
    event_id            TEXT PRIMARY KEY,
    actor_user_id       TEXT,
    oauth_client_id     TEXT,
    node_id             TEXT,
    operation           TEXT,
    idempotency_key     TEXT,
    expected_revision   INTEGER,
    result_revision     INTEGER,
    request_hash        TEXT,
    timestamp           TEXT NOT NULL
);

CREATE TABLE campaign_budgets (
    budget_id TEXT PRIMARY KEY,
    root_node_id TEXT NOT NULL,
    organizer_user_id TEXT NOT NULL,
    participant_user_id TEXT,
    hard_cap_cents INTEGER DEFAULT 0,
    spent_cents INTEGER DEFAULT 0,
    status TEXT DEFAULT 'active',
    name TEXT,
    description TEXT,
    per_user_hard_cap_cents INTEGER,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE competition_entries (
    entry_id        TEXT PRIMARY KEY,
    competition_id  TEXT NOT NULL REFERENCES competitions(competition_id) ON DELETE CASCADE,
    root_node_id    TEXT,
    user_id         TEXT NOT NULL,
    score           REAL,
    note            TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(competition_id, root_node_id)
);

CREATE TABLE competitions (
    competition_id  TEXT PRIMARY KEY,
    slug            TEXT UNIQUE NOT NULL,
    title           TEXT NOT NULL,
    summary         TEXT,
    description     TEXT,
    host_org        TEXT,
    metric_label    TEXT,
    metric_goal     TEXT NOT NULL DEFAULT 'min',
    metric_unit     TEXT,
    dataset         TEXT,
    constraint_text TEXT,
    prize           TEXT,
    repo_url        TEXT,
    paper_url       TEXT,
    credits         TEXT,
    status          TEXT NOT NULL DEFAULT 'live',
    starts_at       TEXT,
    ends_at         TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    seeded          INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE graph_stars (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    root_node_id    TEXT NOT NULL REFERENCES nodes(node_id) ON DELETE CASCADE,
    user_id         TEXT NOT NULL REFERENCES users(user_id) ON UPDATE CASCADE ON DELETE CASCADE,
    created_at      TEXT NOT NULL,
    UNIQUE(root_node_id, user_id)
);

CREATE TABLE idempotency_keys (
    idempotency_key TEXT PRIMARY KEY,
    request_hash    TEXT,
    response_body   TEXT,
    status_code     INTEGER,
    created_at      TEXT NOT NULL,
    expires_at      TEXT NOT NULL
);

CREATE TABLE knowledge_chunks (
    chunk_id     TEXT PRIMARY KEY,
    source_id    TEXT NOT NULL REFERENCES knowledge_sources(source_id) ON DELETE CASCADE,
    node_id      TEXT REFERENCES nodes(node_id) ON DELETE CASCADE,
    chunk_text   TEXT NOT NULL,
    embedding    TEXT,
    ordinal      INTEGER NOT NULL,
    metadata     TEXT NOT NULL DEFAULT '{}',
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE knowledge_sources (
    source_id       TEXT PRIMARY KEY,
    owner_user_id   TEXT REFERENCES users(user_id) ON UPDATE CASCADE ON DELETE CASCADE,
    source_type     TEXT NOT NULL,
    display_name    TEXT,
    external_ref    TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
    metadata        TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE node_access_rules (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id         TEXT NOT NULL REFERENCES nodes(node_id) ON DELETE CASCADE,
    user_id         TEXT NOT NULL REFERENCES users(user_id) ON UPDATE CASCADE ON DELETE CASCADE,
    access_level    TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE TABLE node_edges (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id   TEXT NOT NULL REFERENCES nodes(node_id) ON DELETE CASCADE,
    child_id    TEXT NOT NULL REFERENCES nodes(node_id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL,
    UNIQUE(parent_id, child_id)
);

CREATE TABLE nodes (
    node_id                 TEXT PRIMARY KEY,
    owner_user_id           TEXT NOT NULL REFERENCES users(user_id) ON UPDATE CASCADE ON DELETE CASCADE,
    slug_name               TEXT UNIQUE,
    title                   TEXT,
    summary                 TEXT,
    content                 TEXT,
    node_type               TEXT NOT NULL DEFAULT 'untyped',
    lifecycle               TEXT NOT NULL DEFAULT 'staged',
    outcome                 TEXT,
    hypothesis              TEXT,
    no_artifacts_reason     TEXT,
    insights                TEXT NOT NULL DEFAULT '[]',
    repo_url                TEXT,
    branch_name             TEXT,
    head_commit_sha         TEXT,
    origin_host             TEXT,
    updated_by              TEXT,
    external_transcript_ref TEXT,
    revision                INTEGER NOT NULL DEFAULT 0,
    sharing_mode            TEXT NOT NULL DEFAULT 'private',
    created_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL
, failure_mode TEXT, seeded INTEGER NOT NULL DEFAULT 0, run_cluster_key TEXT, run_data TEXT, semantic_data TEXT);

CREATE TABLE project_dedupe_keys (
    owner_user_id  TEXT NOT NULL REFERENCES users(user_id) ON UPDATE CASCADE ON DELETE CASCADE,
    dedupe_marker  TEXT NOT NULL,
    project_id     TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    PRIMARY KEY (owner_user_id, dedupe_marker)
);

CREATE TABLE research_log (
    entry_id        TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL REFERENCES nodes(node_id) ON DELETE CASCADE,
    entry_type      TEXT NOT NULL,
    title           TEXT NOT NULL,
    body            TEXT,
    refs            TEXT NOT NULL DEFAULT '[]',
    created_at      TEXT NOT NULL,
    created_by      TEXT NOT NULL
);

CREATE TABLE stage_leases (
    stage_session_id  TEXT PRIMARY KEY,
    user_id           TEXT NOT NULL REFERENCES users(user_id) ON UPDATE CASCADE ON DELETE CASCADE,
    node_id           TEXT REFERENCES nodes(node_id) ON DELETE CASCADE,
    expected_revision INTEGER,
    status            TEXT NOT NULL DEFAULT 'active',
    purpose           TEXT,
    expires_at        TEXT NOT NULL,
    released_at       TEXT,
    release_reason    TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    heartbeat_at      TEXT NOT NULL
);

CREATE TABLE tag_assignments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tag_id      TEXT NOT NULL REFERENCES tags(tag_id) ON DELETE CASCADE,
    node_id     TEXT NOT NULL REFERENCES nodes(node_id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL,
    UNIQUE(tag_id, node_id)
);

CREATE TABLE tag_history (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    tag_id                  TEXT NOT NULL REFERENCES tags(tag_id) ON DELETE CASCADE,
    node_id                 TEXT NOT NULL REFERENCES nodes(node_id) ON DELETE CASCADE,
    history_index           INTEGER NOT NULL,
    superseded_at           TEXT,
    superseded_by_node_id   TEXT REFERENCES nodes(node_id) ON DELETE SET NULL
);

CREATE TABLE tags (
    tag_id              TEXT PRIMARY KEY,
    root_node_id        TEXT NOT NULL REFERENCES nodes(node_id) ON DELETE CASCADE,
    name                TEXT NOT NULL,
    bg_color            TEXT NOT NULL DEFAULT '#6366f1',
    text_color          TEXT NOT NULL DEFAULT '#ffffff',
    one_only            INTEGER NOT NULL DEFAULT 0,
    track_history       INTEGER NOT NULL DEFAULT 0,
    history_next_index  INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE INDEX idx_artifacts_node_id
    ON artifacts(node_id, created_at DESC);

CREATE INDEX idx_audit_events_node_timestamp ON audit_events(node_id, timestamp);

CREATE INDEX idx_audit_events_timestamp ON audit_events(timestamp);

CREATE INDEX idx_campaign_budgets_root ON campaign_budgets(root_node_id);

CREATE INDEX idx_competition_entries_comp ON competition_entries(competition_id);

CREATE INDEX idx_competition_entries_user ON competition_entries(user_id);

CREATE INDEX idx_graph_stars_root
    ON graph_stars(root_node_id);

CREATE INDEX idx_graph_stars_user
    ON graph_stars(user_id);

CREATE INDEX idx_idempotency_keys_expires_at ON idempotency_keys(expires_at);

CREATE INDEX idx_knowledge_chunks_node_id   ON knowledge_chunks(node_id);

CREATE INDEX idx_knowledge_chunks_source_id ON knowledge_chunks(source_id);

CREATE INDEX idx_knowledge_sources_name ON knowledge_sources(display_name);

CREATE INDEX idx_knowledge_sources_owner ON knowledge_sources(owner_user_id);

CREATE INDEX idx_knowledge_sources_ref ON knowledge_sources(external_ref);

CREATE INDEX idx_knowledge_sources_type ON knowledge_sources(source_type);

CREATE INDEX idx_node_access_rules_node_user
    ON node_access_rules(node_id, user_id);

CREATE INDEX idx_node_edges_child_id  ON node_edges(child_id);

CREATE INDEX idx_node_edges_parent_id ON node_edges(parent_id);

CREATE INDEX idx_nodes_dedupe_key
    ON nodes(owner_user_id, external_transcript_ref);

CREATE INDEX idx_nodes_owner_updated
    ON nodes(owner_user_id, updated_at DESC);

CREATE INDEX idx_nodes_owner_user_id ON nodes(owner_user_id);

CREATE INDEX idx_nodes_shared_updated
    ON nodes(updated_at DESC)
    WHERE sharing_mode IN ('public', 'unlisted');

CREATE INDEX idx_nodes_slug_name     ON nodes(slug_name);

CREATE INDEX idx_research_log_project_time ON research_log(project_id, created_at DESC);

CREATE INDEX idx_research_log_type ON research_log(project_id, entry_type);

CREATE INDEX idx_tag_assignments_node_id
    ON tag_assignments(node_id);

CREATE INDEX idx_tag_assignments_tag_node
    ON tag_assignments(tag_id, node_id);

CREATE INDEX idx_tag_history_node_history
    ON tag_history(node_id, history_index);

CREATE INDEX idx_tags_root_node_id ON tags(root_node_id);

CREATE INDEX nodes_run_cluster_idx ON nodes (owner_user_id, run_cluster_key) WHERE run_cluster_key IS NOT NULL;

CREATE TRIGGER trg_nodes_project_dedupe_delete
AFTER DELETE ON nodes
WHEN OLD.external_transcript_ref LIKE 'atlas-project-dedupe:%'
BEGIN
    DELETE FROM project_dedupe_keys
    WHERE owner_user_id = OLD.owner_user_id
      AND dedupe_marker = OLD.external_transcript_ref
      AND project_id = OLD.node_id;
END;

CREATE TRIGGER trg_nodes_project_dedupe_insert
BEFORE INSERT ON nodes
WHEN NEW.external_transcript_ref LIKE 'atlas-project-dedupe:%'
BEGIN
    SELECT CASE WHEN EXISTS (
        SELECT 1 FROM project_dedupe_keys
        WHERE owner_user_id = NEW.owner_user_id
          AND dedupe_marker = NEW.external_transcript_ref
          AND project_id <> NEW.node_id
    ) THEN RAISE(ABORT, 'project_dedupe_conflict') END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM project_dedupe_keys
        WHERE owner_user_id = NEW.owner_user_id
          AND dedupe_marker = NEW.external_transcript_ref
    ) AND EXISTS (
        SELECT 1 FROM nodes
        WHERE owner_user_id = NEW.owner_user_id
          AND external_transcript_ref = NEW.external_transcript_ref
          AND node_id <> NEW.node_id
    ) THEN RAISE(ABORT, 'project_dedupe_conflict') END;
    INSERT OR IGNORE INTO project_dedupe_keys (
        owner_user_id, dedupe_marker, project_id, created_at
    ) VALUES (
        NEW.owner_user_id, NEW.external_transcript_ref, NEW.node_id, NEW.created_at
    );
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM project_dedupe_keys
        WHERE owner_user_id = NEW.owner_user_id
          AND dedupe_marker = NEW.external_transcript_ref
          AND project_id = NEW.node_id
    ) THEN RAISE(ABORT, 'project_dedupe_conflict') END;
END;

CREATE TRIGGER trg_nodes_project_dedupe_update
BEFORE UPDATE OF external_transcript_ref ON nodes
WHEN NEW.external_transcript_ref LIKE 'atlas-project-dedupe:%'
BEGIN
    SELECT CASE WHEN EXISTS (
        SELECT 1 FROM project_dedupe_keys
        WHERE owner_user_id = NEW.owner_user_id
          AND dedupe_marker = NEW.external_transcript_ref
          AND project_id <> NEW.node_id
    ) THEN RAISE(ABORT, 'project_dedupe_conflict') END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM project_dedupe_keys
        WHERE owner_user_id = NEW.owner_user_id
          AND dedupe_marker = NEW.external_transcript_ref
    ) AND EXISTS (
        SELECT 1 FROM nodes
        WHERE owner_user_id = NEW.owner_user_id
          AND external_transcript_ref = NEW.external_transcript_ref
          AND node_id <> NEW.node_id
    ) THEN RAISE(ABORT, 'project_dedupe_conflict') END;
    INSERT OR IGNORE INTO project_dedupe_keys (
        owner_user_id, dedupe_marker, project_id, created_at
    ) VALUES (
        NEW.owner_user_id, NEW.external_transcript_ref, NEW.node_id, NEW.created_at
    );
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM project_dedupe_keys
        WHERE owner_user_id = NEW.owner_user_id
          AND dedupe_marker = NEW.external_transcript_ref
          AND project_id = NEW.node_id
    ) THEN RAISE(ABORT, 'project_dedupe_conflict') END;
END;

CREATE TRIGGER trg_nodes_project_dedupe_update_cleanup
AFTER UPDATE OF external_transcript_ref ON nodes
WHEN OLD.external_transcript_ref LIKE 'atlas-project-dedupe:%'
 AND NEW.external_transcript_ref IS NOT OLD.external_transcript_ref
BEGIN
    DELETE FROM project_dedupe_keys
    WHERE owner_user_id = OLD.owner_user_id
      AND dedupe_marker = OLD.external_transcript_ref
      AND project_id = OLD.node_id;
END;
