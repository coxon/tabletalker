# Backend image — Python 3.11 + uv. Mirror the boot sequence used by
# `运行脚本/start.sh`: load .env, install deps with uv, launch uvicorn
# with --proxy-headers (needed for `report_html_url` to honour
# X-Forwarded-Proto behind nginx/Caddy/an OpenShift Route).
#
# Build context: must be the REPO ROOT (not 源代码/backend) so we can also
# bake `自测报告/` and the active `eval/runs/<id>/` into the image —
# the /v1/self-test/* endpoints serve those at runtime.
#   docker buildx build -f 源代码/backend/Dockerfile .
FROM python:3.11-slim AS base

# uv is delivered as a single static binary; pin to a known release for
# reproducibility across rebuilds. (Update intentionally, not by drift.)
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_LINK_MODE=copy

WORKDIR /app

# Install deps first so the layer cache survives source edits.
COPY 源代码/backend/pyproject.toml 源代码/backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# App source. `data/` is created at runtime (mounted as a volume in
# compose, PVC in k8s) so we don't bake the local sqlite into the image.
COPY 源代码/backend/app ./app

# Self-test bundle: the auto-grader markdown plus the eval run it
# references. Together they're <15 MB so baking is cheap. The runtime
# selftest module auto-detects /app/自测报告 + /app/eval/runs/.
COPY 自测报告 ./自测报告
COPY eval/runs ./eval/runs

RUN mkdir -p /app/data && chgrp -R 0 /app && chmod -R g=u /app

EXPOSE 8000

# `--proxy-headers` honours X-Forwarded-* from a TLS-terminating proxy
# (nginx / OpenShift Route) so the backend's `report_html_url` is built
# against the public hostname instead of `http://localhost:8000`. We do
# NOT widen `--forwarded-allow-ips` here — the app-level
# ProxyHeadersMiddleware (gated by APP_TRUSTED_PROXIES) is what decides
# which clients are trusted; uvicorn's default 127.0.0.1 ringfence
# matters when the container is exposed without a proxy.
#
# We invoke uvicorn directly from the baked-in venv (NOT `uv run`)
# because `uv run` re-syncs deps at startup and writes to `.venv`.
# Under OpenShift's restricted SCC the container runs as a random
# non-root UID, so the resync fails with EACCES on /app/.venv. The
# `chgrp 0 + chmod g=u` step above also makes /app/data (the PVC mount
# point) writable by the random UID via the GID=0 group convention.
CMD ["/app/.venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
