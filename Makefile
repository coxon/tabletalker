# TableTalker — local dev orchestration.
#
#   make install     install backend (uv) + frontend (pnpm) deps
#   make dev         run backend on :8000 and frontend on :3000 concurrently
#   make lint        ruff (backend) + tsc --noEmit (frontend)
#   make typecheck   pyright (backend) + tsc --noEmit (frontend)
#   make test        pytest (backend)
#   make check       lint + typecheck + test
#   make eval-datasets  regenerate the 15 evaluation CSVs
#   make eval-run    run the evaluation against a backend (default :8000)
#   make eval-render render eval/runs/<ts>/summary.json into the metrics doc
#   make eval        eval-datasets + eval-run + eval-render
#   make clean       drop caches and build artifacts
#
# Prereqs (one-time, install yourself):
#   - uv     https://docs.astral.sh/uv/        (Python project manager)
#   - node   v20+                              (Node runtime)
#   - pnpm   `corepack enable` ships pnpm with node; or `npm i -g pnpm`
#   - make   GNU make 3.81+ (preinstalled on macOS / Linux)

SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c

# Use `pnpm` if on PATH, else fall back to corepack's shim.
PNPM ?= $(shell command -v pnpm >/dev/null 2>&1 && echo pnpm || echo corepack pnpm)

BACKEND_DIR  := src/backend
FRONTEND_DIR := src/frontend

.PHONY: help install install-backend install-frontend dev lint typecheck test check eval eval-datasets eval-run eval-render clean

help:
	@awk 'BEGIN{FS=":.*##"} /^[a-zA-Z_-]+:.*##/ {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: install-backend install-frontend ## Install all deps

install-backend: ## uv sync (Python)
	cd $(BACKEND_DIR) && uv sync --dev

install-frontend: ## pnpm install (Node)
	cd $(FRONTEND_DIR) && $(PNPM) install

dev: ## Run backend (:8000) + frontend (:3000) concurrently
	@echo "→ backend  http://localhost:8000"
	@echo "→ frontend http://localhost:3000"
	@trap 'kill 0' INT TERM EXIT; \
	  ( cd $(BACKEND_DIR)  && uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 ) & \
	  ( cd $(FRONTEND_DIR) && $(PNPM) dev ) & \
	  wait

lint: ## ruff (backend) + tsc (frontend)
	cd $(BACKEND_DIR)  && uv run ruff check .
	cd $(FRONTEND_DIR) && $(PNPM) run typecheck

typecheck: ## pyright (backend) + tsc (frontend)
	cd $(BACKEND_DIR)  && uv run pyright
	cd $(FRONTEND_DIR) && $(PNPM) run typecheck

test: ## pytest (backend)
	cd $(BACKEND_DIR) && uv run pytest

check: lint typecheck test ## Lint + typecheck + test (pre-PR gate)

# --- Evaluation -----------------------------------------------------------
# These targets reuse the backend uv project so we don't grow a second venv
# (httpx + pyyaml are already pulled in by the backend). The runner expects
# a backend reachable at $(EVAL_BACKEND); start it separately with `make dev`
# or your own uvicorn command before running `make eval-run`.

EVAL_BACKEND ?= http://localhost:8000

eval-datasets: ## Regenerate eval/datasets/*.csv (deterministic, seeded)
	cd $(BACKEND_DIR) && uv run python ../../eval/build_datasets.py

eval-run: ## Run eval/run.py against $(EVAL_BACKEND); writes eval/runs/<ts>/
	cd $(BACKEND_DIR) && uv run python ../../eval/run.py --backend $(EVAL_BACKEND)

# Pick the most recent run directory automatically. Override with
# `make eval-render EVAL_RUN=eval/runs/<specific-ts>` to render an older one.
EVAL_RUN ?= $(shell ls -dt eval/runs/* 2>/dev/null | head -n 1)

eval-render: ## Render $(EVAL_RUN)/summary.json into 自测报告/latest_evaluation_metrics.md
	@if [ -z "$(EVAL_RUN)" ]; then echo "no run dirs under eval/runs/ — run `make eval-run` first"; exit 1; fi
	cd $(BACKEND_DIR) && uv run python ../../eval/render_metrics.py --run ../../$(EVAL_RUN) --commit $$(git rev-parse --short HEAD)

eval: eval-datasets eval-run eval-render ## Datasets + run + render (full evaluation pass)

clean: ## Drop caches and build artifacts
	rm -rf $(BACKEND_DIR)/.venv $(BACKEND_DIR)/.pytest_cache $(BACKEND_DIR)/.ruff_cache \
	       $(FRONTEND_DIR)/node_modules $(FRONTEND_DIR)/.next
