# Retired compatibility runtime

`@synsci/atlas` is retired and is no longer an offered Synthetic Sciences
product. Existing command, environment-variable, config, and wire identifiers
remain in this source tree only for compatibility with previously installed
clients.

The package does not bundle or install agent skills, does not modify coding
agent configuration, and has no post-install promotion. Do not publish a new
version. The only npm workflow retained is
`.github/workflows/deprecate-cli.yml`, which applies the retirement notice to
versions already on npm and cannot publish a package.

The active product is Open Sciences in the Synthetic Sciences dashboard:
<https://app.syntheticsciences.ai/openscience>.
