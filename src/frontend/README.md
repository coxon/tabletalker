# tabletalker-frontend

Next.js 15 + React 19 frontend for TableTalker. Run from the repo root with
`make dev`, or directly:

```bash
cd src/frontend
pnpm install
pnpm dev
```

Reads backend URL from `BACKEND_URL` (default `http://localhost:8000`).

> CN networks: for faster installs, set `registry=https://registry.npmmirror.com/`
> in your local `~/.npmrc`. The committed `.npmrc` keeps the default registry
> so CI and non-CN contributors aren't tied to a regional mirror.
