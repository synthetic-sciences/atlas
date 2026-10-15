CREATE EXTENSION IF NOT EXISTS vector;
CREATE TYPE public.artifact_kind AS ENUM ('text', 'table', 'json', 'image', 'banner', 'html', 'plotly_html', 'vega', 'checkpoint', 'binary', 'diff_carousel');
CREATE TYPE public.lifecycle_state AS ENUM ('staged', 'committed');
CREATE TYPE public.node_kind AS ENUM ('untyped', 'empirical', 'insight', 'hypothesis', 'decision');
CREATE TYPE public.outcome_state AS ENUM ('completed', 'failed', 'canceled', 'inconclusive');
CREATE TYPE public.sharing_mode AS ENUM ('private', 'unlisted', 'public');

CREATE OR REPLACE FUNCTION public.cleanup_project_dedupe_marker()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.external_transcript_ref LIKE 'atlas-project-dedupe:%' THEN
            PERFORM pg_advisory_xact_lock(
                hashtextextended(
                    OLD.owner_user_id::text || ':' || OLD.external_transcript_ref,
                    0
                )
            );
            DELETE FROM project_dedupe_keys
            WHERE owner_user_id = OLD.owner_user_id
              AND dedupe_marker = OLD.external_transcript_ref
              AND project_id = OLD.node_id;
        END IF;
        RETURN OLD;
    END IF;

    IF OLD.external_transcript_ref IS DISTINCT FROM NEW.external_transcript_ref
       AND OLD.external_transcript_ref LIKE 'atlas-project-dedupe:%' THEN
        PERFORM pg_advisory_xact_lock(
            hashtextextended(
                OLD.owner_user_id::text || ':' || OLD.external_transcript_ref,
                0
            )
        );
        DELETE FROM project_dedupe_keys
        WHERE owner_user_id = OLD.owner_user_id
          AND dedupe_marker = OLD.external_transcript_ref
          AND project_id = OLD.node_id;
    END IF;
    RETURN NEW;
END;
$function$;

CREATE OR REPLACE FUNCTION public.enforce_project_dedupe_marker()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE
    authoritative_id UUID;
BEGIN
    IF NEW.external_transcript_ref IS NULL
       OR NEW.external_transcript_ref NOT LIKE 'atlas-project-dedupe:%' THEN
        RETURN NEW;
    END IF;

    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            NEW.owner_user_id::text || ':' || NEW.external_transcript_ref,
            0
        )
    );

    SELECT project_id INTO authoritative_id
    FROM project_dedupe_keys
    WHERE owner_user_id = NEW.owner_user_id
      AND dedupe_marker = NEW.external_transcript_ref;

    IF authoritative_id IS NULL THEN
        IF EXISTS (
            SELECT 1 FROM nodes
            WHERE owner_user_id = NEW.owner_user_id
              AND external_transcript_ref = NEW.external_transcript_ref
              AND node_id <> NEW.node_id
        ) THEN
            RAISE EXCEPTION 'project_dedupe_conflict' USING ERRCODE = '23505';
        END IF;

        INSERT INTO project_dedupe_keys (
            owner_user_id, dedupe_marker, project_id, created_at
        ) VALUES (
            NEW.owner_user_id,
            NEW.external_transcript_ref,
            NEW.node_id,
            COALESCE(NEW.created_at, now())
        ) ON CONFLICT (owner_user_id, dedupe_marker) DO NOTHING;

        SELECT project_id INTO authoritative_id
        FROM project_dedupe_keys
        WHERE owner_user_id = NEW.owner_user_id
          AND dedupe_marker = NEW.external_transcript_ref;
    END IF;

    IF authoritative_id IS DISTINCT FROM NEW.node_id THEN
        RAISE EXCEPTION 'project_dedupe_conflict' USING ERRCODE = '23505';
    END IF;
    RETURN NEW;
END;
$function$;


--
-- PostgreSQL database dump
--


-- Dumped from database version 16.15 (Debian 16.15-1.pgdg12+2)
-- Dumped by pg_dump version 16.15 (Debian 16.15-1.pgdg12+2)




--
-- Name: artifact_upload_batches; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.artifact_upload_batches (
    batch_token text NOT NULL,
    node_id uuid NOT NULL,
    expected_revision integer NOT NULL,
    items jsonb NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: artifacts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.artifacts (
    artifact_id uuid DEFAULT gen_random_uuid() NOT NULL,
    node_id uuid NOT NULL,
    artifact_type public.artifact_kind NOT NULL,
    title text NOT NULL,
    note text,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    execution_id uuid,
    storage_path text,
    volume_path text,
    storage_url text,
    mime text,
    size_bytes bigint,
    created_by_agent_id text,
    project_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: audit_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_events (
    event_id uuid DEFAULT gen_random_uuid() NOT NULL,
    actor_user_id uuid,
    oauth_client_id text,
    node_id uuid,
    operation text,
    idempotency_key text,
    expected_revision integer,
    result_revision integer,
    request_hash text,
    "timestamp" timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: campaign_budgets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.campaign_budgets (
    budget_id text NOT NULL,
    root_node_id text NOT NULL,
    organizer_user_id uuid NOT NULL,
    participant_user_id uuid,
    hard_cap_cents integer DEFAULT 0 NOT NULL,
    spent_cents integer DEFAULT 0 NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    name text,
    description text,
    per_user_hard_cap_cents integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: competition_entries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.competition_entries (
    entry_id text NOT NULL,
    competition_id text NOT NULL,
    root_node_id text,
    user_id text NOT NULL,
    score double precision,
    note text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: competitions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.competitions (
    competition_id text NOT NULL,
    slug text NOT NULL,
    title text NOT NULL,
    summary text,
    description text,
    host_org text,
    metric_label text,
    metric_goal text DEFAULT 'min'::text NOT NULL,
    metric_unit text,
    dataset text,
    constraint_text text,
    prize text,
    repo_url text,
    paper_url text,
    credits text,
    status text DEFAULT 'live'::text NOT NULL,
    starts_at timestamp with time zone,
    ends_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    seeded integer DEFAULT 0 NOT NULL
);


--
-- Name: graph_stars; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.graph_stars (
    id bigint NOT NULL,
    root_node_id uuid NOT NULL,
    user_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: graph_stars_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.graph_stars_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: graph_stars_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.graph_stars_id_seq OWNED BY public.graph_stars.id;


--
-- Name: idempotency_keys; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.idempotency_keys (
    idempotency_key text NOT NULL,
    request_hash text,
    response_body text,
    status_code integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone NOT NULL
);


--
-- Name: knowledge_chunks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.knowledge_chunks (
    chunk_id uuid DEFAULT gen_random_uuid() NOT NULL,
    source_id text NOT NULL,
    node_id uuid,
    chunk_text text NOT NULL,
    embedding public.vector(1536),
    ordinal integer NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: knowledge_sources; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.knowledge_sources (
    source_id text NOT NULL,
    owner_user_id uuid,
    source_type text NOT NULL,
    display_name text,
    external_ref text,
    status text DEFAULT 'pending'::text NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: node_access_rules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.node_access_rules (
    id bigint NOT NULL,
    node_id uuid NOT NULL,
    user_id uuid NOT NULL,
    access_level text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: node_access_rules_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.node_access_rules_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: node_access_rules_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.node_access_rules_id_seq OWNED BY public.node_access_rules.id;


--
-- Name: node_edges; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.node_edges (
    id bigint NOT NULL,
    parent_id uuid NOT NULL,
    child_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: node_edges_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.node_edges_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: node_edges_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.node_edges_id_seq OWNED BY public.node_edges.id;


--
-- Name: nodes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.nodes (
    node_id uuid DEFAULT gen_random_uuid() NOT NULL,
    owner_user_id uuid NOT NULL,
    slug_name text,
    title text,
    summary text,
    content text,
    node_type public.node_kind DEFAULT 'untyped'::public.node_kind NOT NULL,
    lifecycle public.lifecycle_state DEFAULT 'staged'::public.lifecycle_state NOT NULL,
    outcome public.outcome_state,
    hypothesis text,
    no_artifacts_reason text,
    insights jsonb DEFAULT '[]'::jsonb NOT NULL,
    repo_url text,
    branch_name text,
    head_commit_sha text,
    origin_host text,
    updated_by text,
    external_transcript_ref text,
    revision integer DEFAULT 0 NOT NULL,
    sharing_mode public.sharing_mode DEFAULT 'private'::public.sharing_mode NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    failure_mode text,
    seeded boolean DEFAULT false NOT NULL,
    run_cluster_key text,
    run_data jsonb,
    semantic_data jsonb
);


--
-- Name: project_dedupe_keys; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.project_dedupe_keys (
    owner_user_id uuid NOT NULL,
    dedupe_marker text NOT NULL,
    project_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: research_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.research_log (
    entry_id uuid DEFAULT gen_random_uuid() NOT NULL,
    project_id uuid NOT NULL,
    entry_type text NOT NULL,
    title text NOT NULL,
    body text,
    refs jsonb DEFAULT '[]'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    created_by text NOT NULL
);


--
-- Name: stage_leases; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.stage_leases (
    stage_session_id text DEFAULT (gen_random_uuid())::text NOT NULL,
    user_id uuid NOT NULL,
    node_id uuid,
    expected_revision integer,
    status text DEFAULT 'active'::text NOT NULL,
    purpose text,
    expires_at timestamp with time zone NOT NULL,
    released_at timestamp with time zone,
    release_reason text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    heartbeat_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: tag_assignments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tag_assignments (
    id bigint NOT NULL,
    tag_id text NOT NULL,
    node_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: tag_assignments_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.tag_assignments_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: tag_assignments_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.tag_assignments_id_seq OWNED BY public.tag_assignments.id;


--
-- Name: tag_history; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tag_history (
    id bigint NOT NULL,
    tag_id text NOT NULL,
    node_id uuid NOT NULL,
    history_index integer NOT NULL,
    superseded_at timestamp with time zone,
    superseded_by_node_id uuid
);


--
-- Name: tag_history_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.tag_history_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: tag_history_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.tag_history_id_seq OWNED BY public.tag_history.id;


--
-- Name: tags; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tags (
    tag_id text NOT NULL,
    root_node_id uuid NOT NULL,
    name text NOT NULL,
    bg_color text DEFAULT '#6366f1'::text NOT NULL,
    text_color text DEFAULT '#ffffff'::text NOT NULL,
    one_only boolean DEFAULT false NOT NULL,
    track_history boolean DEFAULT false NOT NULL,
    history_next_index integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS public.users (
 user_id UUID PRIMARY KEY,
 email TEXT UNIQUE NOT NULL,
 display_name TEXT,
 github_username TEXT,
 avatar_url TEXT,
 created_at TIMESTAMPTZ NOT NULL,
 updated_at TIMESTAMPTZ NOT NULL,
 deleted_at TIMESTAMPTZ
);


--
-- Name: graph_stars id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.graph_stars ALTER COLUMN id SET DEFAULT nextval('public.graph_stars_id_seq'::regclass);


--
-- Name: node_access_rules id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.node_access_rules ALTER COLUMN id SET DEFAULT nextval('public.node_access_rules_id_seq'::regclass);


--
-- Name: node_edges id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.node_edges ALTER COLUMN id SET DEFAULT nextval('public.node_edges_id_seq'::regclass);


--
-- Name: tag_assignments id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tag_assignments ALTER COLUMN id SET DEFAULT nextval('public.tag_assignments_id_seq'::regclass);


--
-- Name: tag_history id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tag_history ALTER COLUMN id SET DEFAULT nextval('public.tag_history_id_seq'::regclass);


--
-- Name: artifact_upload_batches artifact_upload_batches_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.artifact_upload_batches
    ADD CONSTRAINT artifact_upload_batches_pkey PRIMARY KEY (batch_token);


--
-- Name: artifacts artifacts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.artifacts
    ADD CONSTRAINT artifacts_pkey PRIMARY KEY (artifact_id);


--
-- Name: audit_events audit_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_events
    ADD CONSTRAINT audit_events_pkey PRIMARY KEY (event_id);


--
-- Name: campaign_budgets campaign_budgets_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.campaign_budgets
    ADD CONSTRAINT campaign_budgets_pkey PRIMARY KEY (budget_id);


--
-- Name: competition_entries competition_entries_competition_id_root_node_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.competition_entries
    ADD CONSTRAINT competition_entries_competition_id_root_node_id_key UNIQUE (competition_id, root_node_id);


--
-- Name: competition_entries competition_entries_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.competition_entries
    ADD CONSTRAINT competition_entries_pkey PRIMARY KEY (entry_id);


--
-- Name: competitions competitions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.competitions
    ADD CONSTRAINT competitions_pkey PRIMARY KEY (competition_id);


--
-- Name: competitions competitions_slug_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.competitions
    ADD CONSTRAINT competitions_slug_key UNIQUE (slug);


--
-- Name: graph_stars graph_stars_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.graph_stars
    ADD CONSTRAINT graph_stars_pkey PRIMARY KEY (id);


--
-- Name: graph_stars graph_stars_root_node_id_user_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.graph_stars
    ADD CONSTRAINT graph_stars_root_node_id_user_id_key UNIQUE (root_node_id, user_id);


--
-- Name: idempotency_keys idempotency_keys_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.idempotency_keys
    ADD CONSTRAINT idempotency_keys_pkey PRIMARY KEY (idempotency_key);


--
-- Name: knowledge_chunks knowledge_chunks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_chunks
    ADD CONSTRAINT knowledge_chunks_pkey PRIMARY KEY (chunk_id);


--
-- Name: knowledge_sources knowledge_sources_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_sources
    ADD CONSTRAINT knowledge_sources_pkey PRIMARY KEY (source_id);


--
-- Name: node_access_rules node_access_rules_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.node_access_rules
    ADD CONSTRAINT node_access_rules_pkey PRIMARY KEY (id);


--
-- Name: node_edges node_edges_parent_id_child_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.node_edges
    ADD CONSTRAINT node_edges_parent_id_child_id_key UNIQUE (parent_id, child_id);


--
-- Name: node_edges node_edges_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.node_edges
    ADD CONSTRAINT node_edges_pkey PRIMARY KEY (id);


--
-- Name: nodes nodes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.nodes
    ADD CONSTRAINT nodes_pkey PRIMARY KEY (node_id);


--
-- Name: nodes nodes_slug_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.nodes
    ADD CONSTRAINT nodes_slug_name_key UNIQUE (slug_name);


--
-- Name: project_dedupe_keys project_dedupe_keys_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_dedupe_keys
    ADD CONSTRAINT project_dedupe_keys_pkey PRIMARY KEY (owner_user_id, dedupe_marker);


--
-- Name: research_log research_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.research_log
    ADD CONSTRAINT research_log_pkey PRIMARY KEY (entry_id);


--
-- Name: stage_leases stage_leases_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stage_leases
    ADD CONSTRAINT stage_leases_pkey PRIMARY KEY (stage_session_id);


--
-- Name: tag_assignments tag_assignments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tag_assignments
    ADD CONSTRAINT tag_assignments_pkey PRIMARY KEY (id);


--
-- Name: tag_assignments tag_assignments_tag_id_node_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tag_assignments
    ADD CONSTRAINT tag_assignments_tag_id_node_id_key UNIQUE (tag_id, node_id);


--
-- Name: tag_history tag_history_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tag_history
    ADD CONSTRAINT tag_history_pkey PRIMARY KEY (id);


--
-- Name: tags tags_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tags
    ADD CONSTRAINT tags_pkey PRIMARY KEY (tag_id);


--
-- Name: users users_email_key; Type: CONSTRAINT; Schema: public; Owner: -
--



--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--



--
-- Name: idx_artifacts_metadata_gin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_artifacts_metadata_gin ON public.artifacts USING gin (metadata);


--
-- Name: idx_artifacts_node_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_artifacts_node_id ON public.artifacts USING btree (node_id, created_at DESC);


--
-- Name: idx_artifacts_payload_gin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_artifacts_payload_gin ON public.artifacts USING gin (payload);


--
-- Name: idx_audit_events_node_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_events_node_timestamp ON public.audit_events USING btree (node_id, "timestamp");


--
-- Name: idx_audit_events_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_events_timestamp ON public.audit_events USING btree ("timestamp");


--
-- Name: idx_campaign_budgets_root; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_campaign_budgets_root ON public.campaign_budgets USING btree (root_node_id);


--
-- Name: idx_competition_entries_comp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_competition_entries_comp ON public.competition_entries USING btree (competition_id);


--
-- Name: idx_competition_entries_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_competition_entries_user ON public.competition_entries USING btree (user_id);


--
-- Name: idx_graph_stars_root; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_graph_stars_root ON public.graph_stars USING btree (root_node_id);


--
-- Name: idx_graph_stars_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_graph_stars_user ON public.graph_stars USING btree (user_id);


--
-- Name: idx_idempotency_keys_expires_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_idempotency_keys_expires_at ON public.idempotency_keys USING btree (expires_at);


--
-- Name: idx_knowledge_chunks_embed; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_knowledge_chunks_embed ON public.knowledge_chunks USING hnsw (embedding public.vector_cosine_ops) WITH (m='16', ef_construction='64');


--
-- Name: idx_knowledge_chunks_node_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_knowledge_chunks_node_id ON public.knowledge_chunks USING btree (node_id);


--
-- Name: idx_knowledge_chunks_source_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_knowledge_chunks_source_id ON public.knowledge_chunks USING btree (source_id);


--
-- Name: idx_knowledge_sources_metadata_gin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_knowledge_sources_metadata_gin ON public.knowledge_sources USING gin (metadata);


--
-- Name: idx_knowledge_sources_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_knowledge_sources_name ON public.knowledge_sources USING btree (display_name);


--
-- Name: idx_knowledge_sources_owner; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_knowledge_sources_owner ON public.knowledge_sources USING btree (owner_user_id);


--
-- Name: idx_knowledge_sources_ref; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_knowledge_sources_ref ON public.knowledge_sources USING btree (external_ref);


--
-- Name: idx_knowledge_sources_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_knowledge_sources_type ON public.knowledge_sources USING btree (source_type);


--
-- Name: idx_node_access_rules_node_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_node_access_rules_node_user ON public.node_access_rules USING btree (node_id, user_id);


--
-- Name: idx_node_edges_child_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_node_edges_child_id ON public.node_edges USING btree (child_id);


--
-- Name: idx_node_edges_parent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_node_edges_parent_id ON public.node_edges USING btree (parent_id);


--
-- Name: idx_nodes_insights_gin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_nodes_insights_gin ON public.nodes USING gin (insights);


--
-- Name: idx_nodes_owner_updated; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_nodes_owner_updated ON public.nodes USING btree (owner_user_id, updated_at DESC);


--
-- Name: idx_nodes_owner_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_nodes_owner_user_id ON public.nodes USING btree (owner_user_id);


--
-- Name: idx_nodes_shared_updated; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_nodes_shared_updated ON public.nodes USING btree (updated_at DESC) WHERE (sharing_mode = ANY (ARRAY['public'::public.sharing_mode, 'unlisted'::public.sharing_mode]));


--
-- Name: idx_nodes_slug_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_nodes_slug_name ON public.nodes USING btree (slug_name);


--
-- Name: idx_research_log_project_time; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_research_log_project_time ON public.research_log USING btree (project_id, created_at DESC);


--
-- Name: idx_research_log_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_research_log_type ON public.research_log USING btree (project_id, entry_type);


--
-- Name: idx_tag_assignments_node_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tag_assignments_node_id ON public.tag_assignments USING btree (node_id);


--
-- Name: idx_tag_assignments_tag_node; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tag_assignments_tag_node ON public.tag_assignments USING btree (tag_id, node_id);


--
-- Name: idx_tag_history_node_history; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tag_history_node_history ON public.tag_history USING btree (node_id, history_index);


--
-- Name: idx_tags_root_node_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tags_root_node_id ON public.tags USING btree (root_node_id);


--
-- Name: idx_upload_batches_items_gin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_upload_batches_items_gin ON public.artifact_upload_batches USING gin (items);


--
-- Name: nodes_dedupe_key_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX nodes_dedupe_key_idx ON public.nodes USING btree (owner_user_id, external_transcript_ref) WHERE (external_transcript_ref ~~ 'atlas-project-dedupe:%'::text);


--
-- Name: nodes_owner_user_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX nodes_owner_user_id_idx ON public.nodes USING btree (owner_user_id, updated_at DESC);


--
-- Name: nodes_run_cluster_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX nodes_run_cluster_idx ON public.nodes USING btree (owner_user_id, run_cluster_key) WHERE (run_cluster_key IS NOT NULL);


--
-- Name: users_email_lower_idx; Type: INDEX; Schema: public; Owner: -
--




--
-- Name: nodes trg_nodes_project_dedupe_delete; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_nodes_project_dedupe_delete AFTER DELETE ON public.nodes FOR EACH ROW EXECUTE FUNCTION public.cleanup_project_dedupe_marker();


--
-- Name: nodes trg_nodes_project_dedupe_insert; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_nodes_project_dedupe_insert BEFORE INSERT ON public.nodes FOR EACH ROW EXECUTE FUNCTION public.enforce_project_dedupe_marker();


--
-- Name: nodes trg_nodes_project_dedupe_update; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_nodes_project_dedupe_update BEFORE UPDATE OF external_transcript_ref ON public.nodes FOR EACH ROW EXECUTE FUNCTION public.enforce_project_dedupe_marker();


--
-- Name: nodes trg_nodes_project_dedupe_update_cleanup; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_nodes_project_dedupe_update_cleanup AFTER UPDATE OF external_transcript_ref ON public.nodes FOR EACH ROW EXECUTE FUNCTION public.cleanup_project_dedupe_marker();


--
-- Name: artifact_upload_batches artifact_upload_batches_node_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.artifact_upload_batches
    ADD CONSTRAINT artifact_upload_batches_node_id_fkey FOREIGN KEY (node_id) REFERENCES public.nodes(node_id) ON DELETE CASCADE;


--
-- Name: artifacts artifacts_node_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.artifacts
    ADD CONSTRAINT artifacts_node_id_fkey FOREIGN KEY (node_id) REFERENCES public.nodes(node_id) ON DELETE CASCADE;


--
-- Name: campaign_budgets campaign_budgets_organizer_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.campaign_budgets
    ADD CONSTRAINT campaign_budgets_organizer_user_id_fkey FOREIGN KEY (organizer_user_id) REFERENCES public.users(user_id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: campaign_budgets campaign_budgets_participant_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.campaign_budgets
    ADD CONSTRAINT campaign_budgets_participant_user_id_fkey FOREIGN KEY (participant_user_id) REFERENCES public.users(user_id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: competition_entries competition_entries_competition_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.competition_entries
    ADD CONSTRAINT competition_entries_competition_id_fkey FOREIGN KEY (competition_id) REFERENCES public.competitions(competition_id) ON DELETE CASCADE;


--
-- Name: graph_stars graph_stars_root_node_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.graph_stars
    ADD CONSTRAINT graph_stars_root_node_id_fkey FOREIGN KEY (root_node_id) REFERENCES public.nodes(node_id) ON DELETE CASCADE;


--
-- Name: graph_stars graph_stars_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.graph_stars
    ADD CONSTRAINT graph_stars_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: knowledge_chunks knowledge_chunks_node_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_chunks
    ADD CONSTRAINT knowledge_chunks_node_id_fkey FOREIGN KEY (node_id) REFERENCES public.nodes(node_id) ON DELETE CASCADE;


--
-- Name: knowledge_chunks knowledge_chunks_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_chunks
    ADD CONSTRAINT knowledge_chunks_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.knowledge_sources(source_id) ON DELETE CASCADE;


--
-- Name: knowledge_sources knowledge_sources_owner_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_sources
    ADD CONSTRAINT knowledge_sources_owner_user_id_fkey FOREIGN KEY (owner_user_id) REFERENCES public.users(user_id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: node_access_rules node_access_rules_node_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.node_access_rules
    ADD CONSTRAINT node_access_rules_node_id_fkey FOREIGN KEY (node_id) REFERENCES public.nodes(node_id) ON DELETE CASCADE;


--
-- Name: node_access_rules node_access_rules_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.node_access_rules
    ADD CONSTRAINT node_access_rules_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: node_edges node_edges_child_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.node_edges
    ADD CONSTRAINT node_edges_child_id_fkey FOREIGN KEY (child_id) REFERENCES public.nodes(node_id) ON DELETE CASCADE;


--
-- Name: node_edges node_edges_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.node_edges
    ADD CONSTRAINT node_edges_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.nodes(node_id) ON DELETE CASCADE;


--
-- Name: nodes nodes_owner_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.nodes
    ADD CONSTRAINT nodes_owner_user_id_fkey FOREIGN KEY (owner_user_id) REFERENCES public.users(user_id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: project_dedupe_keys project_dedupe_keys_owner_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_dedupe_keys
    ADD CONSTRAINT project_dedupe_keys_owner_user_id_fkey FOREIGN KEY (owner_user_id) REFERENCES public.users(user_id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: research_log research_log_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.research_log
    ADD CONSTRAINT research_log_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.nodes(node_id) ON DELETE CASCADE;


--
-- Name: stage_leases stage_leases_node_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stage_leases
    ADD CONSTRAINT stage_leases_node_id_fkey FOREIGN KEY (node_id) REFERENCES public.nodes(node_id) ON DELETE CASCADE;


--
-- Name: stage_leases stage_leases_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stage_leases
    ADD CONSTRAINT stage_leases_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: tag_assignments tag_assignments_node_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tag_assignments
    ADD CONSTRAINT tag_assignments_node_id_fkey FOREIGN KEY (node_id) REFERENCES public.nodes(node_id) ON DELETE CASCADE;


--
-- Name: tag_assignments tag_assignments_tag_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tag_assignments
    ADD CONSTRAINT tag_assignments_tag_id_fkey FOREIGN KEY (tag_id) REFERENCES public.tags(tag_id) ON DELETE CASCADE;


--
-- Name: tag_history tag_history_node_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tag_history
    ADD CONSTRAINT tag_history_node_id_fkey FOREIGN KEY (node_id) REFERENCES public.nodes(node_id) ON DELETE CASCADE;


--
-- Name: tag_history tag_history_superseded_by_node_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tag_history
    ADD CONSTRAINT tag_history_superseded_by_node_id_fkey FOREIGN KEY (superseded_by_node_id) REFERENCES public.nodes(node_id) ON DELETE SET NULL;


--
-- Name: tag_history tag_history_tag_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tag_history
    ADD CONSTRAINT tag_history_tag_id_fkey FOREIGN KEY (tag_id) REFERENCES public.tags(tag_id) ON DELETE CASCADE;


--
-- Name: tags tags_root_node_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tags
    ADD CONSTRAINT tags_root_node_id_fkey FOREIGN KEY (root_node_id) REFERENCES public.nodes(node_id) ON DELETE CASCADE;


--
-- Name: artifact_upload_batches; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.artifact_upload_batches ENABLE ROW LEVEL SECURITY;

--
-- Name: artifacts; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.artifacts ENABLE ROW LEVEL SECURITY;

--
-- Name: audit_events; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.audit_events ENABLE ROW LEVEL SECURITY;

--
-- Name: campaign_budgets; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.campaign_budgets ENABLE ROW LEVEL SECURITY;

--
-- Name: competition_entries; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.competition_entries ENABLE ROW LEVEL SECURITY;

--
-- Name: competitions; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.competitions ENABLE ROW LEVEL SECURITY;

--
-- Name: graph_stars; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.graph_stars ENABLE ROW LEVEL SECURITY;

--
-- Name: idempotency_keys; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.idempotency_keys ENABLE ROW LEVEL SECURITY;

--
-- Name: knowledge_chunks; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.knowledge_chunks ENABLE ROW LEVEL SECURITY;

--
-- Name: knowledge_sources; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.knowledge_sources ENABLE ROW LEVEL SECURITY;

--
-- Name: node_access_rules; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.node_access_rules ENABLE ROW LEVEL SECURITY;

--
-- Name: node_edges; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.node_edges ENABLE ROW LEVEL SECURITY;

--
-- Name: nodes; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.nodes ENABLE ROW LEVEL SECURITY;

--
-- Name: project_dedupe_keys; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.project_dedupe_keys ENABLE ROW LEVEL SECURITY;

--
-- Name: research_log; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.research_log ENABLE ROW LEVEL SECURITY;

--
-- Name: stage_leases; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.stage_leases ENABLE ROW LEVEL SECURITY;

--
-- Name: tag_assignments; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.tag_assignments ENABLE ROW LEVEL SECURITY;

--
-- Name: tag_history; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.tag_history ENABLE ROW LEVEL SECURITY;

--
-- Name: tags; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.tags ENABLE ROW LEVEL SECURITY;

--
-- Name: users; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;

--
-- PostgreSQL database dump complete
--


