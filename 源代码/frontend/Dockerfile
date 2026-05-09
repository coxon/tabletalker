# Frontend image — multi-stage `next build` → `next start`. We use
# corepack to run pnpm so the lockfile-pinned 9.15.0 is honoured without
# baking pnpm into the base image.

# ---------- deps: install node_modules with the frozen lockfile ----------
FROM node:20-alpine AS deps
RUN corepack enable
WORKDIR /app
COPY package.json pnpm-lock.yaml .npmrc ./
RUN corepack pnpm install --frozen-lockfile

# ---------- builder: produce the .next/ output ----------
FROM node:20-alpine AS builder
RUN corepack enable
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
# next.config.mjs reads BACKEND_URL at server-load time and uses it as
# the rewrite destination. Rewrites are baked into the build artefacts
# at `next build` time (not re-evaluated per request), so without
# setting BACKEND_URL HERE the rewrite array gets compiled with the
# default `http://localhost:8000` — which fails with ECONNREFUSED in
# the cluster regardless of the runtime env. Pass `--build-arg
# BACKEND_URL=http://table-talker-backend` for k8s, or rely on the
# default which works for an in-cluster Service named `backend`.
ARG BACKEND_URL=http://table-talker-backend
ENV BACKEND_URL=$BACKEND_URL
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN corepack pnpm build

# ---------- runner: minimal layer that only carries what `next start` needs ----------
FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOME=/tmp

# `next start` reads next.config.mjs and `.next/`, so we copy both. The
# `public/` dir doesn't exist in this project but we keep the COPY hint
# commented out so a future static asset doesn't silently get dropped.
# COPY --from=builder /app/public ./public
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/next.config.mjs ./next.config.mjs

EXPOSE 3000

# `BACKEND_URL` is read at request time by next.config.mjs's rewrites
# (defaults to http://localhost:8000). Override at runtime via
# `-e BACKEND_URL=http://backend:8000` in compose / env in k8s.
#
# We invoke `next start` via node directly (NOT `corepack pnpm start`)
# because OpenShift's restricted SCC runs containers as a random
# non-root UID. corepack tries to download the pinned pnpm version
# into `$HOME/.cache/node/corepack/v1` on first use; with a random
# UID and read-only HOME, that write fails with EACCES and the pod
# crashloops. Calling next directly skips corepack entirely.
CMD ["node", "/app/node_modules/next/dist/bin/next", "start"]
