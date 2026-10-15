# Contributing to Atlas

Atlas keeps research graphs useful across the terminal, API, and browser. Good
contributions make those contracts clearer, more reliable, or easier to use.
Source and the CLI, SDK, and UI packages are public under Apache-2.0.

## Where to start

Small fixes and documentation repairs can go straight to a pull request. For a
new feature or a change to graph semantics, open an issue with the problem and
proposed behavior first. A bug report should include a minimal reproduction,
expected and actual behavior, the package version, and the relevant environment.

Graph behavior belongs here. Account identity, organizations, billing, managed
providers, credentials, telemetry, and platform administration belong in
Dashboard. Keep host adapters explicit; graph implementation must not import
Dashboard code or require a sibling checkout.

## Prerequisites and setup

- Node.js 22, as used in CI; published CLI and SDK packages support Node.js 18+.
- Python 3.12 or newer and [uv](https://docs.astral.sh/uv/).
- Bun 1.3.14 only when working on `landing/`.
- An isolated PostgreSQL server with pgvector for database integration checks.

```sh
npm ci --ignore-scripts
uv sync --project backend --frozen --extra dev --extra pg
uv run --project backend atlas-graph --port 8002
```

Local mode uses SQLite and the loopback-only development token `local`.
Use a scratch `ATLAS_DATA_DIR` when testing destructive operations. Supply
credentials through your environment or secret store; never commit `.env`
files, production data, API keys, or authentication state.
See [server configuration](docs/development.md) for PostgreSQL and host adapters.

The database files under `backend/src/atlas_graph/db/` define empty graph
schemas and versioned migrations. Keep those source files. Local databases,
backups, and hosted data exports must stay outside Git. The CI safety job rejects
database snapshots and scans source history with Gitleaks; run
`gitleaks git . --redact=100 --log-opts=--all --max-archive-depth=3` locally too.

## Development loops

| Area | Command |
| --- | --- |
| CLI | `node cli/bin/atlas.mjs --help` |
| Backend | `uv run --project backend python -m pytest backend/tests --timeout=30` |
| TypeScript | `npm run typecheck` |
| Graph UI build | `npm run build:ui` |
| Graph UI tests | `npm run test:ui` |
| CLI tests | `npm run test:cli` |
| SDK tests | `npm run test:sdk` |
| Registry checks | `node --test scripts/registry.test.mjs` |
| Python wheel | `uv build --project backend --wheel` |
| Package checks | `node scripts/pack-release.mjs` |

Set `ATLAS_TEST_PG_DSN` to a disposable loopback database named `atlas_graph_*`
to enable the real PostgreSQL tests. These tests create and remove temporary
databases and roles; use a local test server, never a production connection.
CI runs them against pgvector PostgreSQL 16.

The landing site has a separate Bun lockfile and React 18 dependency tree:

```sh
cd landing
bun install --frozen-lockfile
bunx tsc --noEmit -p tsconfig.app.json
bun run build
```

The graph UI uses React 19. Preserve both dependency boundaries.

## Pull requests

Describe the problem, the resulting behavior, and how you verified it. Include
a reproduction for a bug and a screenshot for a visual change. Keep unrelated
cleanup out of the change. Follow [AGENTS.md](AGENTS.md) and update the relevant
guide when an API, command, configuration option, or workflow changes.

Test behavior with the real implementation where practical. Cover graph access,
revision conflicts, idempotent replay, and failure recovery when they are affected.
Database changes must work in SQLite and PostgreSQL and preserve existing IDs
and customer history. Preserve the graph UI and public/hidden feature flags.

Every pull request is **squash merged** after its required checks pass. Use a
clear final PR title: it becomes the commit title. Maintainers perform releases
from an exact green `main` commit; ordinary contributions should not publish
packages or change release credentials. See [releases](docs/releases.md).

Keep third-party authorship, notices, and licenses with any derived work.
Contributions are licensed under [Apache-2.0](LICENSE). Participation follows
the [Code of Conduct](CODE_OF_CONDUCT.md); report security issues privately as
described in [SECURITY.md](SECURITY.md).
