CREATE TABLE IF NOT EXISTS atlas_index_jobs (
    node_id UUID PRIMARY KEY REFERENCES nodes(node_id) ON DELETE CASCADE,
    revision INTEGER NOT NULL,
    generation BIGINT NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','running','complete','blocked','failed')),
    attempt INTEGER NOT NULL DEFAULT 0,
    next_run BIGINT NOT NULL DEFAULT 0,
    lease_token TEXT NOT NULL DEFAULT '',
    lease_until BIGINT NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    updated_at BIGINT NOT NULL DEFAULT (CAST(EXTRACT(EPOCH FROM clock_timestamp()) AS BIGINT))
);
CREATE INDEX IF NOT EXISTS atlas_index_jobs_due ON atlas_index_jobs(status,next_run,lease_until);

CREATE TABLE IF NOT EXISTS atlas_index_leader (
    singleton INTEGER PRIMARY KEY CHECK (singleton=1),
    token TEXT NOT NULL,
    lease_until BIGINT NOT NULL
);

CREATE OR REPLACE FUNCTION atlas_enqueue_index() RETURNS TRIGGER
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    IF NEW.node_id IS NOT NULL AND NEW.operation IN (
        'atlas_commit_node','atlas_commit_new_node','thesis_commit_node',
        'thesis_commit_new_node','flywheel_commit_node','flywheel_commit_new_node','commit_node'
    ) THEN
        INSERT INTO atlas_index_jobs (node_id,revision)
        SELECT node_id,COALESCE(NEW.result_revision,revision,0) FROM nodes WHERE node_id=NEW.node_id
        ON CONFLICT(node_id) DO UPDATE SET
            revision=GREATEST(atlas_index_jobs.revision,excluded.revision),
            generation=atlas_index_jobs.generation+1,
            status=CASE WHEN atlas_index_jobs.status='running' AND atlas_index_jobs.lease_until>CAST(EXTRACT(EPOCH FROM clock_timestamp()) AS BIGINT) THEN 'running' ELSE 'pending' END,
            attempt=CASE WHEN atlas_index_jobs.status='running' AND atlas_index_jobs.lease_until>CAST(EXTRACT(EPOCH FROM clock_timestamp()) AS BIGINT) THEN atlas_index_jobs.attempt ELSE 0 END,
            lease_token=CASE WHEN atlas_index_jobs.status='running' AND atlas_index_jobs.lease_until>CAST(EXTRACT(EPOCH FROM clock_timestamp()) AS BIGINT) THEN atlas_index_jobs.lease_token ELSE '' END,
            lease_until=CASE WHEN atlas_index_jobs.status='running' AND atlas_index_jobs.lease_until>CAST(EXTRACT(EPOCH FROM clock_timestamp()) AS BIGINT) THEN atlas_index_jobs.lease_until ELSE 0 END,
            next_run=0,last_error='',updated_at=CAST(EXTRACT(EPOCH FROM clock_timestamp()) AS BIGINT);
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS atlas_queue_commit ON audit_events;
CREATE TRIGGER atlas_queue_commit AFTER INSERT ON audit_events
FOR EACH ROW EXECUTE FUNCTION atlas_enqueue_index();

INSERT INTO atlas_index_jobs (node_id,revision)
SELECT n.node_id,MAX(COALESCE(a.result_revision,n.revision,0))
FROM audit_events a JOIN nodes n ON n.node_id=a.node_id
WHERE a.operation IN (
    'atlas_commit_node','atlas_commit_new_node','thesis_commit_node',
    'thesis_commit_new_node','flywheel_commit_node','flywheel_commit_new_node','commit_node'
)
GROUP BY n.node_id
ON CONFLICT(node_id) DO NOTHING;
