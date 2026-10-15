# Atlas SDK

A JavaScript client for Atlas graph servers, with TypeScript declarations and
no runtime dependencies. Requires a browser with `fetch` or Node.js 18+.

```js
import { AtlasClient } from "@synsci/atlas-sdk";

const graph = new AtlasClient({
  baseUrl: "http://127.0.0.1:8002/api/v1",
  token: "local",
});
const project = await graph.createProject({ title: "My research" });
const node = await graph.getNode(project.project_id);
```

`request(method, path, options)` exposes the full server contract. Options
include JSON `body`, `query`, `signal`, and `idempotencyKey`. Failed HTTP
responses throw `AtlasError` with `status` and `body`. Mutations are never
automatically retried. A token callback can supply refreshed credentials.

Licensed under Apache-2.0. Source is maintained in the public
[Atlas repository](https://github.com/synthetic-sciences/atlas).

Copyright 2026 InkVell Inc. (dba Synthetic Sciences).
Contact: [support@sayntheticsciences.ai](mailto:support@sayntheticsciences.ai).
