# Atlas CLI

Command-line access to Atlas research graphs, revisions, evidence, tags, and
research logs. The package installs no agent skills or hooks.

```sh
npm install --global @synsci/atlas
ATLAS_BASE_URL=http://127.0.0.1:8002/api/v1 ATLAS_API_KEY=local atlas project:create --title "My research"
atlas help
```

Run the standalone graph service from the Atlas repository, or configure an
existing hosted profile with `atlas config` and `atlas login`. Existing profile,
command, and wire identifiers remain compatible. Account, billing, and managed
provider commands require the hosted account service; local graph storage does
not implement those services.

Source and releases are maintained in Synthetic Sciences' private Atlas
repository. This npm package is public and licensed under Apache-2.0.
