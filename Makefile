.PHONY: install dev test lint

install:
	uv sync

dev:
	uv run uvicorn taskview_be.main:app --reload --host 0.0.0.0 --port $${PORT:-8200}

test:
	uv run pytest -q

lint:
	uv run ruff check .

