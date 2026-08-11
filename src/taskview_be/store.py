import json

import asyncpg

from .config import get_settings
from .schemas import TaskViewResponse

CREATE_TASK_VIEWS_TABLE = """
CREATE TABLE IF NOT EXISTS task_views (
    id VARCHAR(32) PRIMARY KEY,
    status VARCHAR(16) NOT NULL,
    purpose TEXT NOT NULL,
    audience VARCHAR(32) NOT NULL,
    ttl_days INTEGER NOT NULL CHECK (ttl_days BETWEEN 1 AND 30),
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_task_views_status_created_at
    ON task_views (status, created_at DESC);
"""


class PostgresTaskViewStore:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self._pool: asyncpg.Pool | None = None

    async def start(self) -> None:
        if self._pool is not None:
            return
        self._pool = await asyncpg.create_pool(
            self._database_url,
            min_size=1,
            max_size=5,
            command_timeout=10,
        )
        async with self._pool.acquire() as connection:
            await connection.execute(CREATE_TASK_VIEWS_TABLE)

    async def stop(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def ping(self) -> bool:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            return await connection.fetchval("SELECT 1") == 1

    async def save(self, view: TaskViewResponse) -> TaskViewResponse:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO task_views (
                    id, status, purpose, audience, ttl_days, payload, created_at, updated_at
                ) VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, CURRENT_TIMESTAMP)
                ON CONFLICT (id) DO UPDATE SET
                    status = EXCLUDED.status,
                    purpose = EXCLUDED.purpose,
                    audience = EXCLUDED.audience,
                    ttl_days = EXCLUDED.ttl_days,
                    payload = EXCLUDED.payload,
                    updated_at = CURRENT_TIMESTAMP
                """,
                view.id,
                view.status,
                view.purpose,
                view.audience,
                view.ttl_days,
                view.model_dump_json(),
                view.created_at,
            )
        return view

    async def get(self, view_id: str) -> TaskViewResponse | None:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            payload = await connection.fetchval(
                "SELECT payload FROM task_views WHERE id = $1",
                view_id,
            )
        if payload is None:
            return None
        decoded = json.loads(payload) if isinstance(payload, str) else payload
        return TaskViewResponse.model_validate(decoded)

    async def clear(self) -> None:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            await connection.execute("TRUNCATE TABLE task_views")

    def _require_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("PostgreSQL store has not been started")
        return self._pool


store = PostgresTaskViewStore(get_settings().taskview_database_url)
