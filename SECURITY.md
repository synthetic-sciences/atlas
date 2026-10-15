# Security

## Reporting

Email **support@sayntheticsciences.ai** with a minimal reproduction, the affected
package and version, and the impact. Keep vulnerabilities out of public issues
and pull requests until a fix and disclosure are coordinated. Do not send live
credentials, private research data, or account exports; use a redacted example.

## Scope

Atlas owns graph access, revisions, evidence, the API, CLI, SDK, and graph UI.
The local server accepts loopback clients and origins. Its default development
token is for local use; exposing that server requires a hosted authentication
adapter, explicit persistence, and a signing secret.

The hosted account service owns identity, organizations, Wallet, provider
credentials, and platform administration. Atlas receives scoped capabilities
through host adapters. Public graph discovery remains disabled unless the host
explicitly enables it; a public npm package does not grant graph access.

Report authorization bypasses, unintended data exposure, unsafe file handling,
credential leaks, and integrity failures through the private channel above.
Include the relevant host configuration without its secret values.

## Versions

Report against the latest released version of the affected npm package, or name
the exact source commit when working from a checkout. Releases and package
integrity are documented in [docs/releases.md](docs/releases.md).
