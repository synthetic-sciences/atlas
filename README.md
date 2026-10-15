# Atlas

Research graph engine, API, CLI, JavaScript SDK, and embeddable graph UI.
The GitHub repository stays private. Its npm packages are public under Apache-2.0.

| Directory | Responsibility |
| --- | --- |
| `backend` | Graph storage, topology, revisions, evidence, permissions, research logs, indexing, HTTP API |
| `cli` | `@synsci/atlas`, the graph CLI and compatible hosted client commands |
| `sdk` | `@synsci/atlas-sdk`, dependency-free JavaScript/TypeScript client |
| `ui` | `@synsci/atlas-ui`, compiled React components and declarations |
| `landing` | Existing tryatlas.sh website and Vercel configuration |

Accounts, organizations, Wallet, Stripe, managed inference/search, provider
credentials, session telemetry, and platform administration belong to the
separate private dashboard repository. Hosts supply identity, capabilities,
storage, and providers through `atlas_graph.runtime.Host`. Graph implementation
never imports dashboard code. The browser boundary is `configureAtlasUI`.

## Local development

```sh
npm ci
uv sync --project backend --extra dev --extra pg
uv run --project backend atlas-graph --port 8002
```

In another terminal:

```sh
ATLAS_BASE_URL=http://127.0.0.1:8002/api/v1 ATLAS_API_KEY=local node cli/bin/atlas.mjs project:create --title "My research"
ATLAS_BASE_URL=http://127.0.0.1:8002/api/v1 ATLAS_API_KEY=local node cli/bin/atlas.mjs project:list
```

Local mode accepts loopback clients and origins. Set `ATLAS_DATA_DIR` for
persistent storage and `ATLAS_LOCAL_TOKEN` to override the local token.
`ATLAS_DATABASE_URL` selects PostgreSQL; SQLite is the default. The standalone
schema contains graph data and author profiles, with no account credentials,
organizations, Wallet, or telemetry. Hosted mode requires an explicit identity
adapter and signing secret and otherwise fails closed. Public discovery is
disabled by default. Optional direct embeddings use `ATLAS_EMBEDDING_API_KEY`,
`ATLAS_EMBEDDING_BASE_URL`, and `ATLAS_EMBEDDING_MODEL`.

## Checks and releases

```sh
npm run typecheck
npm run build:ui
npm run test:cli
npm run test:ui
npm run test:sdk
node --test scripts/registry.test.mjs
uv run --project backend python -m pytest backend/tests --timeout=30
uv build --project backend --wheel
node scripts/pack-release.mjs
```

Npm releases promote an exact CI-green main commit. Each package is packed and
checked before publication; partial releases resume only when existing package
integrity matches. Packages install no agent skills, write no agent configuration,
and have no postinstall hooks. The private repository cannot generate npm
provenance, which requires public source; release manifests retain artifact hashes.

Landing keeps its own frozen Bun lockfile and React 18 dependency tree. Run
`bun install --frozen-lockfile` and `bun run build` there. The graph UI uses
React 19 independently. `extraction.json` records source provenance.

Releases authenticate to npm through the repository's `release-npm.yml`
trusted publisher in the `npm` environment. No npm publishing token is stored
in Actions. The release workflow checks the exact source commit and artifact
integrity before publishing.

For a new package name, first stage the checked tarball with `npm stage publish`,
configure its trusted publisher, and approve the initial staged release on npm.
A staged version is reserved and cannot be overwritten by a direct publish.
Resume the release with the same checked artifacts after approval; published
versions are accepted only when their integrity matches the manifest. Registry
processing may take several minutes, so verification waits up to five minutes
per package. Keep package contents unchanged while a release is staged.
