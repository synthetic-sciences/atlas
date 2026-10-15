# Independent service and data cutover

Repository extraction is deployed separately from the live service and data
cutover. Dashboard currently hosts the pinned graph wheel. The standalone
Atlas service already runs against graph-only SQLite or PostgreSQL; its hosted
identity and provider integration still needs a two-service rehearsal.

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

`ATLAS_TRANSFER_SOURCE` and `ATLAS_TRANSFER_TARGET` select the databases. The
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
