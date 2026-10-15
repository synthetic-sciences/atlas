# Atlas

Private research graph engine, HTTP API, CLI, client contract, and graph UI for
Synthetic Sciences. This repository is extracted from dashboard commit
`566904ae1e6157a4157a7469212f800bd026995f`; `extraction.json` records ownership.
Public discovery and retired features retain their existing visibility.

Accounts, organizations, Wallet, Stripe, managed inference/search, credentials,
session telemetry, and administration live in `synthetic-sciences/dashboard`.
An embedding host supplies those services through `atlas_graph.runtime.Host`.
The graph implementation has no imports from dashboard source.

## Local graph API and CLI

```sh
cd backend
uv sync --extra dev --extra pg
uv run atlas-graph --port 8002
```

In another terminal at the repository root:

```sh
npm ci
ATLAS_BASE_URL=http://127.0.0.1:8002/api/v1 ATLAS_API_KEY=local node cli/bin/atlas.mjs project:create --title "My research"
ATLAS_BASE_URL=http://127.0.0.1:8002/api/v1 ATLAS_API_KEY=local node cli/bin/atlas.mjs project:list
```

Local mode accepts loopback clients and loopback browser origins only. Set
`ATLAS_DATA_DIR` to select a storage directory. An optional `ATLAS_LOCAL_TOKEN`
overrides the local development token. `ATLAS_DATABASE_URL` selects PostgreSQL;
SQLite is the default. Both initialize only the graph schema and an author
profile cache; neither creates account, billing, credential, or telemetry tables.

The optional direct embedding adapter uses `ATLAS_EMBEDDING_API_KEY`,
`ATLAS_EMBEDDING_BASE_URL`, and `ATLAS_EMBEDDING_MODEL`. Provider keys never come
from graph data. Managed embeddings are supplied by the dashboard adapter.

## Graph UI

The package exports `@synsci/atlas/ui` and `@synsci/atlas/ui/*`. The existing
components and their rendered UI are preserved. `configureAtlasUI` supplies
the host's authenticated request helpers, account shell, toast, and confirmation
behavior. Graph permissions remain authoritative on the server.

## Checks

```sh
uv run --project backend python -m pytest backend/tests --timeout=30
npm run typecheck
npm run test:ui
npm run test:cli
uv build --project backend --wheel
npm pack --dry-run --json --ignore-scripts
```

The npm package remains private, has no installer hooks, and is not a public
product launch. Historical package deprecation is owned by dashboard operations.
CLI command, configuration, and wire identifiers are retained for compatibility.

