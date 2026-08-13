.PHONY: install dev api worker web test lint fmt check clean

install:
	uv sync
	cd apps/web && pnpm install

# One command, no infrastructure: the API runs an inline worker thread.
dev:
	@echo "API  → http://127.0.0.1:8000"
	@echo "Web  → http://127.0.0.1:3000"
	@echo
	@$(MAKE) -j2 api web

api:
	uv run uvicorn emulsion_api:app --host 127.0.0.1 --port 8000 --reload

# Only needed when EMULSION_INLINE_WORKER=0, or to mirror production's separate process.
worker:
	EMULSION_INLINE_WORKER=0 uv run emulsion-worker

web:
	cd apps/web && pnpm dev

test:
	uv run pytest -q

lint:
	uv run ruff check .
	uv run ruff format --check .
	cd apps/web && pnpm typecheck

fmt:
	uv run ruff check --fix .
	uv run ruff format .

check: lint test

clean:
	rm -rf .data
