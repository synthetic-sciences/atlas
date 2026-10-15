# Atlas graph repository

Atlas owns graph storage, semantics, evidence, graph access, research records,
the graph API, CLI, SDK, and graph UI. Account identity, organizations, billing,
managed inference/search, credentials, telemetry, and product administration
belong to `synthetic-sciences/dashboard` and enter through host adapters.

Preserve the existing graph UI and hidden/public feature flags. GitHub stays
private. CLI, SDK, and UI packages are public npm releases under Apache-2.0.
Publication does not enable anonymous graph access, launch hidden hosted
features, or restore retired compute or agent services.

Keep graph rules and tests independent of a dashboard checkout. Host adapters
must fail closed for authorization and must not import dashboard implementation
modules. Compatibility adapters in dashboard own any transitional integration.
Keep SQLite and PostgreSQL schemas aligned. Never discard customer history or
change stored IDs and wire fields without a versioned migration.

Never put credentials or production data in source, fixtures, or build output.
Run backend tests with the project interpreter (`uv run python -m pytest`),
the CLI tests, UI tests, and TypeScript check before releasing changes.


Run SDK tests and package checks too. Keep the CLI free of React dependencies.
Landing uses its own Bun lock and React 18, independently of the React 19 UI.
Release credentials belong in encrypted CI secrets, never source or artifacts.
