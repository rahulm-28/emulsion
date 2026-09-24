.PHONY: install dev dev-local api worker web test lint fmt check clean

# Machine-local settings — EMULSION_AUTH, CLERK_*, AZURE_*. Absent by default, and
# absent means single-user local mode. The API reads os.environ directly, so without
# this every target would need the variables typed on the command line; forget them
# with accounts switched on in the browser and the API quietly falls back to the dev
# identity, filing a signed-in person's work under `local-user`.
-include local.mk
export

install:
	uv sync
	cd apps/web && pnpm install

# One command, no infrastructure: the API runs an inline worker thread.
dev:
	@echo "API  → http://127.0.0.1:8000"
	@echo "Web  → http://127.0.0.1:3000"
	@echo
	@$(MAKE) -j2 api web

# A deliberately isolated free demo, even with real credentials in .env/local.mk.
dev-local:
	mkdir -p .data-local
	$(MAKE) dev EMULSION_AUTH=dev EMULSION_ADAPTER=echo EMULSION_INLINE_WORKER=1 \
		EMULSION_DATA_DIR=.data-local DATABASE_URL=sqlite:///.data-local/emulsion.db \
		NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=

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
