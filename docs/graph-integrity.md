# Graph mutations and portable evidence

Creating a node with parents requires write access to every parent. All parent
checks happen before the node or any edge is created. Branching claims the
parent's `expected_revision` atomically: concurrent callers using the same
revision receive one successful branch and conflicts for the others.

## Idempotent mutations

Send an `Idempotency-Key` on a mutation when retrying a request must not create a
second result. Keys are scoped to the authenticated user, HTTP method, and path.
Atlas records a durable claim before dispatching the mutation. An identical
completed request replays its original JSON response; a different body using
the same key returns HTTP 409.

A simultaneous request returns HTTP 409 with `Retry-After: 1` while the first
request is unresolved. Retry the same request and key after the original call
finishes. Successful responses are retained for seven days. Authorization and
throttling rejections release their claims so the request can be retried after
the caller's state changes.

A server interruption or ambiguous failure may happen after a database commit.
Atlas retains an unresolved claim, including beyond the normal replay expiry,
instead of automatically running that mutation again. If retries continue to
report an unknown outcome, inspect the resulting graph before issuing a new
mutation. Operators should reconcile that claim against the graph and audit
record before removing it. Binary responses or JSON responses above the replay
limit cannot be replayed; the retry returns a conflict directing the caller to
read the resulting resource. Read-only export endpoints do not use this cache.

## Export and import

Graph JSON exports use version 2. Each node includes an `artifacts` array with
artifact type, title, note, payload, metadata, and execution reference. Uploaded
evidence includes a `blob` containing base64 bytes, the byte count, a SHA-256
checksum, media type, and filename. External artifact URLs remain explicit
references; the server does not fetch those URLs during export or import.

Import validates encoded bytes and checksums, creates fresh node and artifact
IDs, and stores evidence at new paths owned by the imported graph. Structured
node and artifact references within the archive are remapped to the new IDs.
Original server storage paths cannot be supplied as imported evidence. Nodes,
edges, and artifact records are committed together; failed imports remove their
newly uploaded blobs. Existing version 1 node-only exports remain importable,
but cannot recover attachments that were absent from the original export.

An archive supports up to 64 MiB of decoded evidence, with each artifact subject
to the normal upload limit (10 MiB by default). The two import endpoints accept
idempotent JSON requests up to 96 MiB to accommodate base64 encoding. Export
fails if graph-owned evidence cannot be read or exceeds these limits. Legacy
volume-backed evidence must first be uploaded into graph storage. An export
does not silently omit unavailable evidence.

This interchange format creates a new graph; it is not an account backup.
Access policies, graph tags, and audit records are not restored by subgraph
import. Use the separate history export and the operator data-transfer workflow
when retaining those records is required.
