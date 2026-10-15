.PHONY: dev-up dev-down test lint build check migrate seed-demo e2e logs backup restore

dev-up:
	@test -f .env || { cp .env.example .env; echo "Created .env from development-only defaults; review it before use."; }
	docker compose up --build -d

dev-down:
	docker compose down

test:
	npm run typecheck
	PYTHONPATH=services/api uv run pytest

lint:
	npm run typecheck
	uv run ruff check services/api tests

build:
	npm run build
	docker compose build

check:
	npm run api:generate
	git diff --exit-code -- apps/web/src/api/public.generated.ts apps/web/src/admin/admin.generated.ts
	npm run typecheck
	npm run build
	uv run ruff check services/api tests
	uv run mypy services/api
	PYTHONPATH=services/api uv run pytest
	npm ci --prefix deploy/worker
	npm --prefix deploy/worker run typecheck
	npm --prefix deploy/worker test
	npm --prefix deploy/worker run deploy:dry-run

migrate:
	docker compose run --rm init python -m app.cli migrate

seed-demo:
	docker compose run --rm init python -m app.cli seed-demo

e2e:
	PYTHONPATH=services/api uv run python -m app.cli run-demo --rounds 20

logs:
	docker compose logs -f --tail=200

backup:
	./scripts/backup.sh

restore:
	./scripts/restore.sh
