# Atlas UI

React 19 + Vite + TypeScript + Tailwind v3.4 frontend for the Atlas read API.

## Stack

- **React 19** with strict-mode + Suspense.
- **Vite 6** for fast dev / HMR / GPU-accelerated dev server.
- **Tailwind CSS 3.4** + custom HSL-token palette (GitHub-dark inspired).
- **Tanstack Query v5** for caching + deduping API calls.
- **Tanstack Table v8** + `react-virtual` for high-density data grids.
- **React Router v7** (data router mode).
- **Shiki** for syntax highlighting (themed `github-dark-default`).
- **Radix primitives** + `class-variance-authority` for the design system.
- **Sonner** for accessible toast notifications.

## Local development

```bash
cd atlas-lite/ui
npm install
npm run dev          # http://localhost:5173
```

The Vite dev server proxies `/api/*` to `http://127.0.0.1:8080`. In a
separate shell:

```bash
cd atlas-lite
.venv/bin/atlas serve -c atlas.yml --port 8080
```

To point at a different API:

```bash
VITE_API_PROXY=http://atlas-staging.internal npm run dev
```

## Production build

```bash
npm run build        # emits dist/, ready to serve from any static host
npm run preview      # smoke test the bundle
npm run typecheck    # tsc -b --noEmit
npm run lint         # eslint
npm run format       # prettier --write
```

## Design system

The palette and motion language are tuned for high-density tabular UIs:

- Compact 4 px base, 8/12 px gaps.
- Inter for UI, JetBrains Mono for paths and code.
- Transitions on `transform` and `opacity` only, 150–200 ms ease-spring.
- `gpu` utility class for elements that move on hover (translateZ).
- Accessible focus rings (`outline: none` + 2 px ring at the body level).

Routes are file-based under `src/routes/`. New pages:
1. Create `src/routes/<Name>Route.tsx`.
2. Wire it into `src/App.tsx`.
3. Add it to the top-nav in `src/components/layout/AppShell.tsx`.

## API contract

Response shapes live in `src/api/types.ts` and mirror
`atlas.api.models.*` from the FastAPI backend's OpenAPI document. Hooks
in `src/api/hooks.ts` are the only surface routers consume — the
`fetch` wrapper and cache keys live there.
