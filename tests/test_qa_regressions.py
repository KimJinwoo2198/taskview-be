import asyncio
from uuid import uuid4

import asyncpg
import pytest
from fastapi.testclient import TestClient

from taskview_be.config import get_settings
from taskview_be.main import app

TEST_PASSWORD = "TaskView-Test!2026"


async def cleanup_test_rows() -> None:
    connection = await asyncpg.connect(get_settings().taskview_database_url)
    try:
        async with connection.transaction():
            await connection.execute(
                """
                DELETE FROM task_views
                WHERE created_by IN (
                    SELECT id FROM users WHERE email LIKE '%@qa-regression.taskview.dev'
                )
                """
            )
            await connection.execute(
                "DELETE FROM users WHERE email LIKE '%@qa-regression.taskview.dev'"
            )
    finally:
        await connection.close()


@pytest.fixture(autouse=True)
def isolate_database_rows():
    asyncio.run(cleanup_test_rows())
    yield
    asyncio.run(cleanup_test_rows())


def unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}@qa-regression.taskview.dev"


def bearer(payload: dict) -> dict[str, str]:
    return {"authorization": f"Bearer {payload['session_token']}"}


def test_owner_sees_requester_and_blocked_ttl_can_be_repaired(monkeypatch):
    monkeypatch.setenv("TASKVIEW_BE_FAKE_AI", "true")
    get_settings.cache_clear()
    requester_email = unique_email("requester")
    owner_email = unique_email("owner")

    with TestClient(app) as client:
        requester_signup = client.post(
            "/v1/auth/signup",
            json={
                "email": requester_email,
                "display_name": "회귀 요청자",
                "password": TEST_PASSWORD,
            },
        )
        assert requester_signup.status_code == 201
        requester_headers = bearer(requester_signup.json())

        blocked = client.post(
            "/v1/taskviews/preview",
            headers=requester_headers,
            json={
                "purpose": "VOC를 지역과 이슈별로 집계해 다음 우선순위를 결정한다",
                "audience": "product",
                "ttl_days": 14,
            },
        )
        assert blocked.status_code == 200
        assert blocked.json()["status"] == "blocked"

        owner_signup = client.post(
            "/v1/auth/signup",
            json={
                "email": owner_email,
                "display_name": "회귀 소유자",
                "password": TEST_PASSWORD,
            },
        )
        assert owner_signup.status_code == 201

        async def promote_owner() -> None:
            connection = await asyncpg.connect(get_settings().taskview_database_url)
            try:
                await connection.execute(
                    "UPDATE users SET role = 'data_owner' WHERE email = $1",
                    owner_email,
                )
            finally:
                await connection.close()

        asyncio.run(promote_owner())
        owner_login = client.post(
            "/v1/auth/login",
            json={"email": owner_email, "password": TEST_PASSWORD},
        )
        assert owner_login.status_code == 200
        owner_headers = bearer(owner_login.json())

        owner_list = client.get("/v1/taskviews", headers=owner_headers)
        assert owner_list.status_code == 200
        owner_view = next(item for item in owner_list.json() if item["id"] == blocked.json()["id"])
        assert owner_view["requester"] == {
            "display_name": "회귀 요청자",
            "email": requester_email,
        }

        repaired = client.post(
            f"/v1/taskviews/{blocked.json()['id']}/refine",
            headers=requester_headers,
            json={
                "instruction": "TTL을 정책 기준에 맞게 줄여 주세요",
                "ttl_days": 7,
            },
        )
        assert repaired.status_code == 200
        assert repaired.json()["ttl_days"] == 7
        assert repaired.json()["status"] == "proposed"
        assert all(finding["code"] != "TTL_LIMIT" for finding in repaired.json()["policy_findings"])

    get_settings.cache_clear()
