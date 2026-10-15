# Atlas graph UI

React components for graph topology, nodes, revisions, evidence, tags, and
sharing. Requires React 19 and React DOM 19. Components use the host's theme.

```tsx
import { configureAtlasUI, GraphDashboard } from "@synsci/atlas-ui";

configureAtlasUI({ request, publicRequest, getAuthHeaders, api, Shell, useToast, useConfirm });
```

Supply the authenticated request, account shell, notifications, and confirmation
adapters once before rendering. Public discovery defaults to disabled and must
be explicitly enabled by a host. Server permissions remain authoritative.

Compiled JavaScript and TypeScript declarations are shipped on npm; tests,
credentials, account implementation, and backend source are excluded.
Licensed under Apache-2.0.
