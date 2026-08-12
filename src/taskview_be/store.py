import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

import asyncpg

from .auth_schemas import Role, UserPublic
from .config import get_settings
from .schemas import RequesterSummary, TaskViewResponse

CREATE_AUTH_TABLES = """
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY,
    email TEXT NOT NULL,
    display_name VARCHAR(80) NOT NULL,
    password_hash TEXT NOT NULL,
    role VARCHAR(24) NOT NULL DEFAULT 'requester'
        CHECK (role IN ('requester', 'data_owner', 'admin')),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    failed_login_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_login_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_users_normalized_email ON users (LOWER(email));

CREATE TABLE IF NOT EXISTS auth_sessions (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash CHAR(64) NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    revoked_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_active
    ON auth_sessions (user_id, expires_at) WHERE revoked_at IS NULL;
"""

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
ALTER TABLE task_views
    ADD COLUMN IF NOT EXISTS created_by UUID REFERENCES users(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_task_views_status_created_at
    ON task_views (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_task_views_created_by_created_at
    ON task_views (created_by, created_at DESC);
"""


@dataclass(frozen=True)
class UserAuthRecord:
    user: UserPublic
    password_hash: str
    is_active: bool
    failed_login_attempts: int
    locked_until: datetime | None


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
            max_size=10,
            command_timeout=10,
        )
        async with self._pool.acquire() as connection:
            await connection.execute(CREATE_AUTH_TABLES)
            await connection.execute(CREATE_TASK_VIEWS_TABLE)
            await connection.execute(
                "DELETE FROM auth_sessions WHERE expires_at <= CURRENT_TIMESTAMP OR revoked_at IS NOT NULL"
            )

    async def stop(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def ping(self) -> bool:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            return await connection.fetchval("SELECT 1") == 1

    async def create_user(
        self,
        *,
        email: str,
        display_name: str,
        password_hash: str,
        role: Role = "requester",
    ) -> UserPublic:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                INSERT INTO users (id, email, display_name, password_hash, role)
                VALUES ($1, LOWER($2), $3, $4, $5)
                RETURNING id, email, display_name, role, created_at
                """,
                uuid4(),
                email,
                display_name,
                password_hash,
                role,
            )
        return self._to_user_public(row)

    async def get_user_for_auth(self, email: str) -> UserAuthRecord | None:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT id, email, display_name, role, created_at, password_hash, is_active,
                       failed_login_attempts, locked_until
                FROM users
                WHERE LOWER(email) = LOWER($1)
                """,
                email,
            )
        if row is None:
            return None
        return UserAuthRecord(
            user=self._to_user_public(row),
            password_hash=row["password_hash"],
            is_active=row["is_active"],
            failed_login_attempts=row["failed_login_attempts"],
            locked_until=row["locked_until"],
        )

    async def record_login_failure(
        self, user_id: str, *, max_failures: int, lock_minutes: int
    ) -> None:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            await connection.execute(
                """
                UPDATE users
                SET failed_login_attempts = failed_login_attempts + 1,
                    locked_until = CASE
                        WHEN failed_login_attempts + 1 >= $2
                        THEN CURRENT_TIMESTAMP + ($3 * INTERVAL '1 minute')
                        ELSE locked_until
                    END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = $1
                """,
                UUID(user_id),
                max_failures,
                lock_minutes,
            )

    async def record_login_success(self, user_id: str) -> None:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            await connection.execute(
                """
                UPDATE users
                SET failed_login_attempts = 0,
                    locked_until = NULL,
                    last_login_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = $1
                """,
                UUID(user_id),
            )

    async def create_session(
        self, *, user_id: str, token_hash: str, expires_at: datetime
    ) -> datetime:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            return await connection.fetchval(
                """
                INSERT INTO auth_sessions (id, user_id, token_hash, expires_at)
                VALUES ($1, $2, $3, $4)
                RETURNING expires_at
                """,
                uuid4(),
                UUID(user_id),
                token_hash,
                expires_at,
            )

    async def get_user_by_session(self, token_hash: str) -> UserPublic | None:
        pool = self._require_pool()
        async with pool.acquire() as connection, connection.transaction():
            row = await connection.fetchrow(
                """
                SELECT u.id, u.email, u.display_name, u.role, u.created_at, s.id AS session_id
                FROM auth_sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.token_hash = $1
                  AND s.revoked_at IS NULL
                  AND s.expires_at > CURRENT_TIMESTAMP
                  AND u.is_active = TRUE
                FOR UPDATE OF s
                """,
                token_hash,
            )
            if row is None:
                return None
            await connection.execute(
                "UPDATE auth_sessions SET last_seen_at = CURRENT_TIMESTAMP WHERE id = $1",
                row["session_id"],
            )
        return self._to_user_public(row)

    async def revoke_session(self, token_hash: str) -> None:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            await connection.execute(
                """
                UPDATE auth_sessions
                SET revoked_at = CURRENT_TIMESTAMP
                WHERE token_hash = $1 AND revoked_at IS NULL
                """,
                token_hash,
            )

    async def set_user_role(self, email: str, role: Role) -> UserPublic | None:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                UPDATE users
                SET role = $2, updated_at = CURRENT_TIMESTAMP
                WHERE LOWER(email) = LOWER($1)
                RETURNING id, email, display_name, role, created_at
                """,
                email,
                role,
            )
        return None if row is None else self._to_user_public(row)

    async def save(self, view: TaskViewResponse) -> TaskViewResponse:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO task_views (
                    id, status, purpose, audience, ttl_days, payload, created_at, created_by,
                    updated_at
                ) VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, CURRENT_TIMESTAMP)
                ON CONFLICT (id) DO UPDATE SET
                    status = EXCLUDED.status,
                    purpose = EXCLUDED.purpose,
                    audience = EXCLUDED.audience,
                    ttl_days = EXCLUDED.ttl_days,
                    payload = EXCLUDED.payload,
                    created_by = EXCLUDED.created_by,
                    updated_at = CURRENT_TIMESTAMP
                """,
                view.id,
                view.status,
                view.purpose,
                view.audience,
                view.ttl_days,
                self._payload_json(view),
                view.created_at,
                UUID(view.created_by) if view.created_by else None,
            )
        return view

    async def save_if_status(self, view: TaskViewResponse, *, expected_status: str) -> bool:
        """Atomically persist a state transition only when no competing update won."""
        pool = self._require_pool()
        async with pool.acquire() as connection:
            updated = await connection.fetchval(
                """
                UPDATE task_views SET
                    status = $2,
                    purpose = $3,
                    audience = $4,
                    ttl_days = $5,
                    payload = $6::jsonb,
                    created_by = $7,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = $1 AND status = $8
                RETURNING TRUE
                """,
                view.id,
                view.status,
                view.purpose,
                view.audience,
                view.ttl_days,
                self._payload_json(view),
                UUID(view.created_by) if view.created_by else None,
                expected_status,
            )
        return updated is True

    async def get(self, view_id: str) -> TaskViewResponse | None:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT tv.payload, u.email AS requester_email,
                       u.display_name AS requester_display_name
                FROM task_views tv
                LEFT JOIN users u ON u.id = tv.created_by
                WHERE tv.id = $1
                """,
                view_id,
            )
        if row is None:
            return None
        return self._decode_view(row)

    async def list_views(
        self, *, created_by: str | None = None, limit: int = 50
    ) -> list[TaskViewResponse]:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            if created_by:
                rows = await connection.fetch(
                    """
                    SELECT tv.payload, u.email AS requester_email,
                           u.display_name AS requester_display_name
                    FROM task_views tv
                    LEFT JOIN users u ON u.id = tv.created_by
                    WHERE tv.created_by = $1
                    ORDER BY tv.created_at DESC
                    LIMIT $2
                    """,
                    UUID(created_by),
                    limit,
                )
            else:
                rows = await connection.fetch(
                    """
                    SELECT tv.payload, u.email AS requester_email,
                           u.display_name AS requester_display_name
                    FROM task_views tv
                    LEFT JOIN users u ON u.id = tv.created_by
                    ORDER BY tv.created_at DESC
                    LIMIT $1
                    """,
                    limit,
                )
        return [self._decode_view(row) for row in rows]

    async def clear(self) -> None:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            await connection.execute("TRUNCATE TABLE task_views")

    def _require_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("PostgreSQL store has not been started")
        return self._pool

    @staticmethod
    def _to_user_public(row: asyncpg.Record) -> UserPublic:
        return UserPublic(
            id=str(row["id"]),
            email=row["email"],
            display_name=row["display_name"],
            role=row["role"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _payload_json(view: TaskViewResponse) -> str:
        return view.model_copy(update={"requester": None}).model_dump_json()

    @staticmethod
    def _decode_view(row: asyncpg.Record) -> TaskViewResponse:
        payload = row["payload"]
        decoded = json.loads(payload) if isinstance(payload, str) else payload
        view = TaskViewResponse.model_validate(decoded)
        if row["requester_email"] and row["requester_display_name"]:
            view.requester = RequesterSummary(
                email=row["requester_email"],
                display_name=row["requester_display_name"],
            )
        return view


store = PostgresTaskViewStore(get_settings().taskview_database_url)
