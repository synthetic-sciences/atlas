# Ownership and integration

Atlas owns graph behavior and its clients. Dashboard owns account identity,
organization policy, billing, provider credentials, telemetry, and operations.
The production dashboard embeds a versioned Atlas wheel and UI package through
one host adapter. Existing URLs, hidden flags, and rendered UI stay compatible.

`atlas_graph.runtime.Host` supplies database contexts, authentication dependencies,
collaboration capability, optional GitHub and embedding adapters, and transport
error mapping. Atlas does not inspect commercial plans or import dashboard code.
Hosted repository operations use a caller-bound adapter; Dashboard executes
the GitHub request and returns commit IDs while keeping account grants private.
`configureAtlasUI` supplies browser request/auth helpers, the host shell and
feedback components, and an explicit public-discovery flag.

Dashboard integration tests exercise real accounts and Wallet. Atlas tests
exercise graph rules without the platform. The standalone API owns its SQLite
or PostgreSQL schema and evidence store. Local auth is restricted to loopback.
A hosted deployment needs an explicit identity adapter, persistence, signing
secret, and origin policy; it must not inherit broad production credentials.

Repository extraction and service/data separation have independent release
gates. Moving live graph data needs a rehearsed migration, one writer during
cutover, compatible identities, preserved indexing and signed links, and a
reverse migration for post-cutover writes. Current customer data stays in its
existing store until those gates pass.

[Service separation and data rehearsal](service-separation.md) records the
remaining hosted contracts, the local transfer command, and cutover order.

Public npm artifacts contain only package implementation, declarations,
documentation, and Apache-2.0 license. Backend source, landing assets, tests,
credentials, and dashboard source are excluded. CLI depends only on its
browser-opening utility; SDK has no runtime dependencies; React belongs to UI.
