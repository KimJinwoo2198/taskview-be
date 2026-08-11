.PHONY: install db dev test lint create-owner

install:
	uv sync

db:
	docker compose up -d postgres

dev:
	uv run uvicorn taskview_be.main:app --reload --host 0.0.0.0 --port $${PORT:-8200}

test: db
	TASKVIEW_DATABASE_URL=$${TASKVIEW_DATABASE_URL:-postgresql://taskview:taskview@127.0.0.1:54329/taskview} uv run pytest -q

lint:
	uv run ruff check .

create-owner:
	uv run python scripts/create_user.py --email owner@taskview.dev --name "TaskView Owner" --role data_owner
