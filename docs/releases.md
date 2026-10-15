# Atlas releases

Atlas owns the public npm releases for `@synsci/atlas`, `@synsci/atlas-sdk`, and
`@synsci/atlas-ui`. The source repository remains private. Package publication
does not launch hosted features or change graph access.

## Verification

Run the checks in [CONTRIBUTING.md](../CONTRIBUTING.md), build the Python wheel,
and run `node scripts/pack-release.mjs`. Review the produced manifest and
tarballs. CLI packages exclude React and graph UI dependencies; SDK has no
runtime dependencies; UI ships compiled components and declarations. Packages
install no agent skills or configuration and have no postinstall hooks.

Preserve author and license notices. Credentials, production data, Dashboard
source, tests, backend code, and landing assets must not enter npm archives.
Version changes are deliberate release changes; never reuse a published or
staged version for different contents.

## Promotion

Dispatch `.github/workflows/release-npm.yml` from `main` with the exact lowercase
40-character `release_sha`. The commit must be reachable from `main` and have a
successful completed CI push run at that same SHA. Start with `publish=false`
to inspect the checked release artifacts. `publish=true` publishes those packages
publicly and records their hashes.

The `npm` GitHub environment authenticates through each package's npm trusted
publisher, restricted to `synthetic-sciences/atlas` and `release-npm.yml`.
No npm publishing token is stored in Actions. Private repositories cannot
generate npm provenance; the release manifest records artifact integrity.

Private GitHub release records use `npm-<source commit>` and attach the checked
manifest and tarballs. SDK and UI versions can advance independently of the CLI.
Existing release tags and published package contents remain immutable.

## Staged packages and recovery

For a new package name, stage the checked tarball with `npm stage publish`,
configure its trusted publisher, and approve the initial staged release on npm.
Resume with the same checked artifacts. Staged versions are reserved and cannot
be overwritten with a direct publish.

Partial publication resumes only when an existing version's integrity matches
the manifest. Registry processing may take several minutes; verification waits
up to five minutes per package. Keep package contents unchanged while a release
is staged.

A trusted publisher permitting direct publication can publish a fresh version
while older stages remain pending. Do not approve an obsolete stage that would
move `latest` back to an older version. See the official
[npm staged publishing reference](https://docs.npmjs.com/cli/v11/commands/npm-stage/).

## Landing

`landing/` owns tryatlas.sh, with its own frozen Bun lockfile and React 18.
The `deploy-landing.yml` workflow inspects and promotes the exact source commit
while preserving the Vercel project, domains, and deployment settings. Changes
to the graph packages do not require a landing redesign.
