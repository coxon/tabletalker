# TableTalker — local dev orchestration.
#
#   make install     install backend (uv) + frontend (pnpm) deps
#   make dev         run backend on :8000 and frontend on :3000 concurrently
#   make lint        ruff (backend) + tsc --noEmit (frontend)
#   make typecheck   pyright (backend) + tsc --noEmit (frontend)
#   make test        pytest (backend)
#   make check       lint + typecheck + test
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

.PHONY: help install install-backend install-frontend dev lint typecheck test check clean

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
	  ( cd $(BACKEND_DIR)  && uv run uvicorn app.main:app --reload --port 8000 ) & \
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

clean: ## Drop caches and build artifacts
	rm -rf $(BACKEND_DIR)/.venv $(BACKEND_DIR)/.pytest_cache $(BACKEND_DIR)/.ruff_cache \
	       $(FRONTEND_DIR)/node_modules $(FRONTEND_DIR)/.next
