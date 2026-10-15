# Independent service and data cutover

Repository extraction is deployed separately from the live service and data
cutover. Dashboard currently hosts the pinned graph wheel. The standalone
Atlas service already runs against graph-only SQLite or PostgreSQL; its hosted
identity integration passes a two-service PostgreSQL rehearsal. Provider,
gateway, storage, and writer-cutover contracts remain separate gates.

The hosted entry point is `atlas_graph.hosted:create_app`. Its Dashboard adapter
calls `/api/internal/atlas/identity` with the incoming bearer and workspace
header plus a graph service credential. It verifies each new request through
Dashboard, caches identity only within that request, and refreshes a graph-only
profile cache without account emails or credentials. Redirects are never
followed with these headers. Collaboration is an explicit Dashboard capability
lookup, so Atlas does not reconstruct commercial policy.

Dashboard keeps this account boundary disabled until `ATLAS_SERVICE_TOKEN` is
provisioned. Atlas uses the matching `ATLAS_ACCOUNT_SERVICE_TOKEN`, a fixed
HTTPS `ATLAS_ACCOUNT_URL` (loopback HTTP for rehearsal), and its own signing
secret. This credential grants only the graph account-adapter endpoints; it
does not authenticate as a user or grant database access. A user credential is
also required for identity. No account authentication cache survives a request.

Hosted repository capture, pin, and verification use a request-bound repository
adapter. It forwards only the caller's bearer and workspace header plus the
service credential to `/api/internal/atlas/repository`. Dashboard revalidates
the caller and performs the fixed repository status, tag creation, ref read,
or commit read operation using its account-owned GitHub connection. It returns
only connection state or commit IDs. Stored OAuth/PAT grants never enter Atlas.
No user ID supplied by Atlas chooses the GitHub account, and no arbitrary URL,
method, or request headers can be proxied. Redirects and ambiguous write retries
are refused. Graph write access is required before pinning; an existing tag
counts as pinned only when it points to the requested commit.

## Managed indexing

Hosted indexing sends bounded batches to Dashboard's
`/api/internal/atlas/index/embeddings` operation. The independent
`ATLAS_INDEX_SERVICE_TOKEN` grants this workload only; identity and repository
requests continue to use `ATLAS_ACCOUNT_SERVICE_TOKEN`. Index requests never
carry a user's bearer token or the account-adapter credential. Dashboard keeps
provider keys and resolves the graph owner's Personal Wallet under its existing
managed-usage policy. Atlas cannot choose a provider, model, or funding account.

Each batch contains the owner ID, node ID, revision, and at most 16 texts of at
most 2,048 characters each. A canonical operation fingerprint binds the reply to
that exact batch. Atlas accepts only the fixed model and ordered, finite vectors
of 1,536 numbers. Dashboard retains delivery results for seven days; an expired
result returns 410 and cannot become another paid operation.

Dashboard persists a fenced operation and reservation before provider dispatch,
and a provider result and price snapshot before Wallet settlement. Retries reuse
the result and settlement. An uncertain dispatched request remains pending until
account-side reconciliation proves its reservation was terminally uncharged.
This avoids blindly repeating a provider call or debiting a second Wallet.

Atlas replaces a node's chunks atomically only after the managed operation
succeeds and the node's owner, revision, and indexed text still match. A changed
or deleted node cannot publish stale vectors, and a partial insert rolls back
the entire replacement.

The standalone schema records commit jobs in the same transaction as the audit
event. A versioned migration backfills historical commit audits, leaving drafts
alone. The opt-in `ATLAS_INDEXING_ENABLED` worker claims jobs under a database
leader lease and renews its job and leader leases while a provider is pending.
Results require the current lease, fence, and commit generation. Chunk writes
and job completion commit together; a newer commit remains pending instead of
being acknowledged by an older result. Graceful cancellation and hard process
termination leave recoverable work. Existing matching chunks with finite,
1,536-dimensional vectors are reused without another embedding request.

Temporary failures retain durable retries, funding and authorization failures
remain blocked for a later retry, and expired paid results remain failed. Error
codes contain no private provider diagnostics. Queue migration rebuilds pending
work from commit audits and never copies worker leases.

The embedded Dashboard worker remains in place until the service cutover. Its
replacement must still pass the coupled account/provider recovery rehearsal,
writer fencing, storage, gateway, and reverse migration gates. A passing
standalone scheduler test does not authorize moving the live indexer.

## Managed graph search

The standalone `/api/knowledge/search` route searches only graph chunks the
caller may read. Its request-bound query adapter forwards the user's bearer,
workspace selection, and account-service credential to Dashboard's fixed
`/api/internal/atlas/query/embeddings` operation. Provider credentials, billing
receipts, and Wallet records never enter Atlas. The independent index-service
credential cannot authorize a query or impersonate a user.

Dashboard resolves the authenticated Personal or organization Wallet and checks
current membership and funding access on every request, including replay. A
query operation is scoped to that user, resolved Wallet, and request UUID.
Reusing the UUID with different text returns a conflict. Atlas derives a stable
UUID from the incoming request path and Idempotency-Key when present; independent
requests without a key receive independent UUIDs. Query text is bounded to 8,192
characters. Requests that exclude graph search do not request an embedding.

The query and indexing paths share the durable reservation, provider-result,
price-snapshot, and settlement state machine. A lost delivery reuses its paid
result; an uncertain provider outcome cannot redispatch until account-side
reconciliation proves it was uncharged. Expired delivery remains a tombstone.
Atlas validates the exact query fingerprint, fixed model, and one finite,
1,536-dimensional vector before searching. Account and funding errors propagate
instead of silently returning an empty successful search. Generic response
replay does not bypass this current authorization and Wallet check.

## Fly layout

The selected app names are `synsci-dashboard` and `synsci-graphs`, both in
Singapore alongside the current deployment. They are separate apps because
[Fly injects app secrets into every machine in that app](https://docs.fly.io/apps/secrets).
API and indexing processes may share the graphs app once they use only graph
credentials. Account and Wallet jobs remain in the dashboard app. Keep the
existing PostgreSQL server, with separate credentials and schemas, rather than
duplicating the account database into Atlas.

The new app names are reserved without compute or storage. The existing
`thesis-synsc.fly.dev` API continues serving production until gateway, storage,
worker, replay, and writer-fencing checks pass. Its hostname must remain a
compatibility entry point after cutover. Reserving a name does not migrate
machines, credentials, volumes, or customer data.

## Database permissions

Atlas can use a separate database or a dedicated schema on the existing
PostgreSQL server. `ATLAS_DATABASE_SCHEMA` selects the schema explicitly. An
administrator creates the schema and its login; the runtime login owns only
graph objects and has no privileges on Dashboard's tables, no role memberships,
and no superuser, role-creation, database-creation, or RLS-bypass authority.
The pgvector extension remains in `public` while graph types, tables, functions,
and indexes live in the selected schema. Provision credentials through the
deployment secret store.

Startup rejects invalid or inaccessible schemas. Real PostgreSQL tests run
project creation, reads, and deduplication as a restricted login alongside
private `public.users` and `public.nodes` tables; direct reads of both private
tables are denied. This provides a tested storage boundary without giving the
graph runtime the account database's administrator credentials. It does not
authorize a live cutover by itself.

## Data rehearsal

`atlas_graph.ops.transfer` copies a consistent, read-only PostgreSQL snapshot
into a fresh graph schema, preserving stored IDs, revisions, enums, JSON numeric
precision, timestamps, graph access, evidence references, vectors, and editing
leases. It verifies every table by row count and SHA-256 of PostgreSQL's canonical
JSON representation, rebases sequences, and restores deduplication triggers.
Target tables are locked before checking emptiness. Errors roll back the copy.

Only graph tables and referenced author profiles transfer. Profiles use
synthetic email addresses; account emails, passwords, GitHub credentials,
organizations, Wallet transactions, and telemetry remain in Dashboard.

The shared legacy `idempotency_keys` table must **not** transfer. Its opaque
scope hashes cannot distinguish graph responses from private account responses,
including one-time API keys. During cutover, Dashboard must authenticate and
check legacy replay before forwarding graph requests, retaining that cache until
its final response expires. New graph replay belongs to Atlas. Tests must prove
same-body replay, different-body conflict, revocation, expiry, and user isolation
across that boundary before cutover.

The command deliberately accepts only loopback `atlas_graph_*` databases. Create
both disposable databases and initialize the target through the Atlas database
lifecycle first. Supply DSNs through environment variables, never command-line
arguments or committed files:

```sh
uv sync --project backend --extra dev --extra pg
uv run --project backend python -m atlas_graph.ops.transfer
```

`ATLAS_TRANSFER_SOURCE` and `ATLAS_TRANSFER_TARGET` select the databases.
`--source-schema` and `--target-schema` select schemas (both default to `public`),
including separate schemas in one disposable database. The
report contains counts and checksums, no row contents, and explicitly marks the
rehearsal as insufficient for production cutover. The real PostgreSQL tests
seed every transferred table alongside private platform data, continue writing
on the restored graph, then transfer that updated state to a third fresh graph
database. They also exercise concurrent source writes and failed-copy rollback.

This is a local database rehearsal, not a production migration or a complete
rollback into a Dashboard deployment. Blob bytes, outstanding signed links,
legacy response replay, and the single-writer fence have separate gates.

## Hosted boundary

| Concern | Required behavior |
| --- | --- |
| Identity | Dashboard validates API keys and browser sessions on every request; Atlas receives only a scoped graph identity or delegates verification back to Dashboard. Revocation and workspace pinning stay authoritative. |
| Profiles | Atlas caches graph author display fields and stable IDs. Account email, provider grants, passwords, and account deletion policy stay in Dashboard. |
| Collaboration | Dashboard decides the capability for the graph owner. Atlas enforces graph-level access without knowing commercial plan names. |
| Managed embeddings | Atlas requests an authorized operation from Dashboard. Dashboard resolves funding, reserves and settles Wallet, and calls the provider. Provider keys never enter Atlas. Background indexing must preserve attribution and avoid duplicate charges. |
| GitHub | Dashboard performs the authorized repository operation. Returning the user's stored OAuth token to Atlas is not an acceptable remote adapter. |
| Graph administration | Dashboard retains browser/admin authorization; Atlas returns graph statistics or applies an authorized graph operation. Dashboard's current graph SQL joins must be replaced before moving its database. |
| Skills | Dashboard owns private skill data. Graph attachment and research-log effects use Atlas operations with the same access checks. |
| HTTP and realtime | Existing browser/CLI URLs, errors, streamed exports, uploads, signed downloads, websocket initial-message auth, and hidden/public flags remain compatible through the gateway. |
| Storage | Copy and checksum evidence bytes into Atlas-owned storage, preserve path mapping and signed-link compatibility, and verify reads before switching writers. Dashboard's Supabase service-role key must never become an Atlas credential. |

## Cutover order

1. Test both services with separate schemas and least-privilege credentials.
   Exercise the existing Dashboard integration suite through the gateway, plus
   uploads/downloads, streaming, websocket updates, indexing, and provider error
   and Wallet behavior. Keep public discovery disabled.
2. Rehearse graph rows and blob transfer on disposable data. Compare every
   table and object, preserve active upload batches and leases, and verify old
   signed URLs and idempotent retries. Rehearse rollback after new writes,
   updates, and deletes; a pre-cutover backup alone is insufficient.
3. Pause graph mutations, drain uploads and workers, and fence the old graph
   writer. Copy the final snapshot and objects and validate them. Account and
   Wallet writes stay with Dashboard throughout.
4. Switch the gateway to Atlas, enable only its graph writer/indexer, and run
   authenticated CLI/UI and hidden-feature probes. Record source SHAs, artifact
   hashes, row/object manifests, writer state, and the rollback procedure.
5. Remove embedded graph execution, cross-database joins, temporary replay and
   migration controls only after the relevant compatibility window closes.
   Preserve customer history and original identifiers. Verify independent
   deployments and recovery before declaring the migration complete.

No production database or storage changes are performed by the rehearsal tool.
