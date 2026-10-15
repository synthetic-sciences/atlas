# Graph server configuration

The [contribution guide](../CONTRIBUTING.md) covers installation and checks.
The standalone server runs without Dashboard:

```sh
uv sync --project backend --frozen --extra dev --extra pg
uv run --project backend atlas-graph --port 8002
```

## Local storage and access

Local mode accepts loopback clients and origins. `ATLAS_DATA_DIR` selects its
data directory, including SQLite and local evidence files; the default is
`./data`. The graph server’s local blob backend uses POSIX directory descriptors
and runs on Linux or macOS. The CLI can also connect to a remote graph server. `ATLAS_LOCAL_TOKEN` replaces the default development token `local`.

`ATLAS_DATABASE_URL` selects PostgreSQL instead of SQLite.
`ATLAS_DATABASE_SCHEMA` selects a pre-created graph schema, defaulting to
`public`. A missing or invalid schema fails startup without falling back to
another schema. Use a login that owns only graph objects and cannot read
Dashboard tables. Keep database credentials in the deployment secret store.

The standalone schema contains graph data and author profiles. It does not
contain account credentials, organizations, Wallet, or telemetry. Public graph
discovery is disabled by default.

Optional direct embeddings use `ATLAS_EMBEDDING_API_KEY`,
`ATLAS_EMBEDDING_BASE_URL`, and `ATLAS_EMBEDDING_MODEL`. Hosted provider policy
and credentials belong to Dashboard and use the managed adapter instead.

## Hosted integration

The hosted entry point uses an explicit Dashboard identity adapter:

```sh
uv run --project backend uvicorn atlas_graph.hosted:create_app --factory
```

Configure `ATLAS_MODE=hosted`, `ATLAS_ACCOUNT_URL`, an
`ATLAS_ACCOUNT_SERVICE_TOKEN` matching Dashboard's `ATLAS_SERVICE_TOKEN`, and
an Atlas-owned `ATLAS_SIGNING_SECRET` of at least 32 characters. Supply these
through deployment secrets. Hosted Atlas rejects a Supabase service-role key;
evidence belongs in its own graph volume.
The account adapter validates each request, including API-key revocation and
workspace pinning. Atlas stores graph profile fields with synthetic email
addresses, rather than account emails or credentials.

Hosted managed embeddings use a separate `ATLAS_INDEX_SERVICE_TOKEN`. Identity
and repository operations continue to use the account service credential.
These credentials have different scopes and must not be interchangeable.

`ATLAS_INDEXING_ENABLED=true` starts the durable commit indexer with the graph
API. It is off by default. Hosted startup refuses an absent, short, or reused
index credential when indexing is enabled. Commit jobs persist even while the
worker is disabled. Database leases allow multiple API processes to run the
worker without simultaneously dispatching the same queue.

Funding and authorization failures remain blocked with a later retry; temporary
provider or service failures keep retrying with bounded backoff. An expired
managed result is retained as failed rather than silently becoming a fresh paid
operation. Inspect `atlas_index_jobs` through an authorized operator connection
when diagnosing pending or failed work; job errors contain neutral codes.

The graph host interface is `atlas_graph.runtime.Host`; the browser interface
is `configureAtlasUI`. Keep both boundaries explicit. See
[architecture](architecture.md) and [service separation](service-separation.md)
for their contracts and the remaining provider, storage, gateway, worker, and
data migration gates. Running the standalone service does not complete those
production cutover checks.

`extraction.json` records the original source provenance. Preserve third-party
notices when moving or deriving code.
