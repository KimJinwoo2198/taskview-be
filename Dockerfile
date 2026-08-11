FROM python:3.12-slim
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
COPY pyproject.toml uv.lock* README.md ./
RUN uv sync --frozen --no-dev || uv sync --no-dev
COPY src ./src
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH=/app/src PORT=8200
EXPOSE 8200
CMD ["sh", "-c", "uvicorn taskview_be.main:app --host 0.0.0.0 --port ${PORT}"]

