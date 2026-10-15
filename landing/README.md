# atlas-landing

Marketing site for **Atlas** — GitHub for scientific research. Atlas turns
your coding agent into an AI scientist.

- Live site: https://tryatlas.sh
- Parent brand: https://syntheticsciences.ai
- Company: InkVell Inc.

## Stack

- [Vite](https://vitejs.dev) + [React 18](https://react.dev) + TypeScript
- [Tailwind CSS](https://tailwindcss.com) for styling
- [Bun](https://bun.sh) as the package manager
- One Tailwind/shadcn-style `<Button>` component; everything else is hand-rolled
- Self-hosted **CMU Concrete** display font, Google-served **JetBrains Mono**
  for terminal mocks
- ASCII / grain visuals for diagrams (`SystemDiagram`, `ShiftLadder`,
  `DelegationFeed`, `MapTreeBlock`, `ReproduceBlock`, `SkillsList`,
  `LibrarySearch`, `MacTerminal`, `TextRing`)

## Development

```bash
bun install
bun run dev       # http://localhost:8080 (port auto-increments if taken)
bun run build     # production build to dist/
bun run preview   # serve the production build locally
bun run lint
```

## Repo layout

```
public/
  fonts/                  CMU Concrete (roman + bold)
  logos/                  pre-processed greyscale university logos
src/
  App.tsx                 router (only / and *)
  main.tsx                React mount
  index.css               Tailwind layers + custom utilities
  pages/
    Landing.tsx           the entire marketing page
    NotFound.tsx          minimal 404
  components/ui/button.tsx
  lib/utils.ts            cn() helper
  assets/hero-map.png     fullscreen hero artwork
index.html                meta tags + font preconnect
vercel.json               SPA rewrite rule
```

## Deploy

The site is wired to Vercel and auto-deploys on push to `main`. The custom
domain `tryatlas.sh` is attached at the Vercel project level.

```bash
git push origin main
```

## License

© InkVell Inc. All rights reserved.
