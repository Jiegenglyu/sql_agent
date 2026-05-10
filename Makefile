.PHONY: backend frontend mcp test db-up db-down db-reset db-logs

env_var = $(shell awk -F= '$$1 == "$(1)" {print $$2; exit}' .env 2>/dev/null)

UV_CACHE_DIR ?= $(or $(call env_var,UV_CACHE_DIR),.uv-cache)
BACKEND_HOST ?= $(or $(call env_var,BACKEND_HOST),0.0.0.0)
BACKEND_PORT ?= $(or $(call env_var,BACKEND_PORT),8000)
FRONTEND_HOST ?= $(or $(call env_var,FRONTEND_HOST),127.0.0.1)
FRONTEND_PORT ?= $(or $(call env_var,FRONTEND_PORT),5173)

backend:
	UV_CACHE_DIR=$(UV_CACHE_DIR) uv run uvicorn backend.app.main:app --reload --host $(BACKEND_HOST) --port $(BACKEND_PORT)

frontend:
	cd frontend && npm run dev -- --host $(FRONTEND_HOST) --port $(FRONTEND_PORT)

db-up:
	docker compose up -d postgres

db-down:
	docker compose down

db-reset:
	docker compose down -v
	docker compose up -d postgres

db-logs:
	docker compose logs -f postgres

mcp:
	UV_CACHE_DIR=$(UV_CACHE_DIR) uv run python -m backend.app.mcp.server

test:
	UV_CACHE_DIR=$(UV_CACHE_DIR) uv run python -m unittest discover backend/tests
