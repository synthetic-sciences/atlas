# Atlas graph UI

React components for graph topology, nodes, revisions, evidence, tags, and
sharing. Requires React 19 and React DOM 19. Components use the host's theme, shared
form primitives, and Tailwind 4 utilities. Import the graph stylesheet and
register the installed components with Tailwind in the host stylesheet:

```css
@import "tailwindcss";
@import "@synsci/atlas-ui/graph.css";
/* Adjust this path relative to the host stylesheet. */
@source "../../node_modules/@synsci/atlas-ui/dist";
```

The host supplies `--color-*`, `--font-*`, `--kind-*`, and spacing tokens.
The graph stylesheet owns node cards, graph layout chrome, and sidebar density.

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
