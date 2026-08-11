import asyncio
from uuid import uuid4

import asyncpg
import pytest
from fastapi.testclient import TestClient

from taskview_be.auth import password_hash
from taskview_be.config import get_settings
from taskview_be.main import app
from taskview_be.policy import evaluate_policy
from taskview_be.schemas import PreviewRequest, PurposeSpec, TransformPlanItem, ViewPlan
from taskview_be.store import store

TEST_PASSWORD = "TaskView-Test!2026"


async def cleanup_test_rows() -> None:
    connection = await asyncpg.connect(get_settings().taskview_database_url)
    try:
        async with connection.transaction():
            await connection.execute(
                """
                DELETE FROM task_views
                WHERE created_by IN (
                    SELECT id FROM users WHERE email LIKE '%@test.taskview.dev'
                )
                """
            )
            await connection.execute(
                "DELETE FROM users WHERE email LIKE '%@test.taskview.dev'"
            )
    finally:
        await connection.close()


@pytest.fixture(autouse=True)
def isolate_database_rows():
    asyncio.run(cleanup_test_rows())
    yield
    asyncio.run(cleanup_test_rows())


def unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}@test.taskview.dev"


def enable_fake_ai(monkeypatch) -> None:
    monkeypatch.setenv("TASKVIEW_BE_FAKE_AI", "true")
    get_settings.cache_clear()


def signup(client: TestClient, email: str) -> tuple[dict, dict[str, str]]:
    response = client.post(
        "/v1/auth/signup",
        json={"email": email, "display_name": "테스트 요청자", "password": TEST_PASSWORD},
    )
    assert response.status_code == 201
    payload = response.json()
    return payload, {"authorization": f"Bearer {payload['session_token']}"}


def seed_privileged_user(role: str) -> tuple[str, str]:
    email = unique_email(role)

    async def seed() -> None:
        await store.start()
        try:
            await store.create_user(
                email=email,
                display_name=f"테스트 {role}",
                password_hash=password_hash.hash(TEST_PASSWORD),
                role=role,
            )
        finally:
            await store.stop()

    asyncio.run(seed())
    return email, TEST_PASSWORD


def login(client: TestClient, email: str, user_password: str) -> tuple[dict, dict[str, str]]:
    response = client.post(
        "/v1/auth/login",
        json={"email": email, "password": user_password},
    )
    assert response.status_code == 200
    payload = response.json()
    return payload, {"authorization": f"Bearer {payload['session_token']}"}


def create_preview(client: TestClient, headers: dict[str, str], ttl_days: int = 7) -> dict:
    response = client.post(
        "/v1/taskviews/preview",
        headers=headers,
        json={
            "purpose": "VOC를 지역과 이슈별로 묶어 다음 스프린트 우선순위를 정하고 싶다",
            "audience": "product",
            "ttl_days": ttl_days,
        },
    )
    assert response.status_code == 200
    return response.json()


def test_signup_me_duplicate_logout_and_revocation(monkeypatch):
    enable_fake_ai(monkeypatch)
    email = unique_email("requester")
    with TestClient(app) as client:
        session, headers = signup(client, email)
        assert session["user"]["role"] == "requester"

        me = client.get("/v1/auth/me", headers=headers)
        assert me.status_code == 200
        assert me.json()["email"] == email

        duplicate = client.post(
            "/v1/auth/signup",
            json={"email": email, "display_name": "중복 사용자", "password": TEST_PASSWORD},
        )
        assert duplicate.status_code == 409

        logout = client.post("/v1/auth/logout", headers=headers)
        assert logout.status_code == 204
        assert client.get("/v1/auth/me", headers=headers).status_code == 401

    get_settings.cache_clear()


def test_session_and_view_persist_across_application_restart(monkeypatch):
    enable_fake_ai(monkeypatch)
    email = unique_email("persistent")
    with TestClient(app) as first_client:
        _, headers = signup(first_client, email)
        view = create_preview(first_client, headers)

    with TestClient(app) as restarted_client:
        assert restarted_client.get("/v1/auth/me", headers=headers).status_code == 200
        persisted = restarted_client.get(f"/v1/taskviews/{view['id']}", headers=headers)
        assert persisted.status_code == 200
        assert persisted.json()["created_by"] == view["created_by"]

    get_settings.cache_clear()


def test_requester_cannot_approve_but_owner_can(monkeypatch):
    enable_fake_ai(monkeypatch)
    owner_email, owner_password = seed_privileged_user("data_owner")
    with TestClient(app) as client:
        _, requester_headers = signup(client, unique_email("requester"))
        view = create_preview(client, requester_headers)

        forbidden = client.post(
            f"/v1/taskviews/{view['id']}/decision",
            headers=requester_headers,
            json={"approved": True},
        )
        assert forbidden.status_code == 403

        owner, owner_headers = login(client, owner_email, owner_password)
        assert owner["user"]["role"] == "data_owner"
        approved = client.post(
            f"/v1/taskviews/{view['id']}/decision",
            headers=owner_headers,
            json={"approved": True, "reason": "최소화 범위 확인"},
        )
        assert approved.status_code == 200
        assert approved.json()["reviewed_by"] == owner_email

        evidence = client.get(f"/v1/taskviews/{view['id']}/evidence", headers=requester_headers)
        assert evidence.status_code == 200
        assert len(evidence.json()["content_sha256"]) == 64

        duplicate_decision = client.post(
            f"/v1/taskviews/{view['id']}/decision",
            headers=owner_headers,
            json={"approved": False},
        )
        assert duplicate_decision.status_code == 409

        immutable_evidence = client.post(
            f"/v1/taskviews/{view['id']}/refine",
            headers=requester_headers,
            json={"instruction": "승인된 내용을 다시 바꿔 주세요"},
        )
        assert immutable_evidence.status_code == 409

    get_settings.cache_clear()


def test_requester_cannot_read_another_users_view(monkeypatch):
    enable_fake_ai(monkeypatch)
    with TestClient(app) as client:
        _, first_headers = signup(client, unique_email("first"))
        _, second_headers = signup(client, unique_email("second"))
        view = create_preview(client, first_headers)

        hidden = client.get(f"/v1/taskviews/{view['id']}", headers=second_headers)
        assert hidden.status_code == 404

    get_settings.cache_clear()


def test_ttl_policy_blocks_owner_approval(monkeypatch):
    enable_fake_ai(monkeypatch)
    owner_email, owner_password = seed_privileged_user("data_owner")
    with TestClient(app) as client:
        _, requester_headers = signup(client, unique_email("ttl"))
        _, owner_headers = login(client, owner_email, owner_password)
        view = create_preview(client, requester_headers, ttl_days=14)
        assert view["status"] == "blocked"

        decision = client.post(
            f"/v1/taskviews/{view['id']}/decision",
            headers=owner_headers,
            json={"approved": True},
        )
        assert decision.status_code == 409

    get_settings.cache_clear()


def test_login_lockout(monkeypatch):
    enable_fake_ai(monkeypatch)
    email = unique_email("lockout")
    with TestClient(app) as client:
        signup(client, email)
        for _ in range(get_settings().taskview_login_max_failures):
            failed = client.post(
                "/v1/auth/login",
                json={"email": email, "password": "Wrong-Password!2026"},
            )
            assert failed.status_code == 401
        locked = client.post(
            "/v1/auth/login",
            json={"email": email, "password": TEST_PASSWORD},
        )
        assert locked.status_code == 429

    get_settings.cache_clear()


def test_policy_blocks_hallucinated_catalog_fields():
    request = PreviewRequest(
        purpose="VOC를 지역별로 묶어 다음 스프린트의 개선 우선순위를 결정하고 싶다",
        audience="product",
        ttl_days=7,
    )
    plan = ViewPlan(
        purpose_spec=PurposeSpec(
            objective=request.purpose,
            decision_to_support="우선순위 결정",
            audience="product",
            requested_fields=["invented_field"],
        ),
        selected_sources=["product"],
        transformations=[
            TransformPlanItem(
                source="voc",
                input_fields=["invented_field"],
                output_field="invented_summary",
                transformation="aggregate",
                rationale="모델이 임의로 제안한 필드",
            )
        ],
        preview_columns=["invented_preview"],
    )

    codes = {finding.code for finding in evaluate_policy(request, plan)}
    assert "SOURCE_NOT_SELECTED" in codes
    assert "UNKNOWN_CATALOG_FIELD" in codes
    assert "UNKNOWN_PREVIEW_COLUMN" in codes
