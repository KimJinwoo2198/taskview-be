from fastapi.testclient import TestClient

from taskview_be.config import get_settings
from taskview_be.main import app
from taskview_be.store import store


def test_preview_approve_and_evidence(monkeypatch):
    monkeypatch.setenv("TASKVIEW_BE_FAKE_AI", "true")
    get_settings.cache_clear()
    store.clear()
    client = TestClient(app)

    response = client.post(
        "/v1/taskviews/preview",
        json={
            "purpose": "VOC를 지역과 이슈별로 묶어 다음 스프린트 우선순위를 정하고 싶다",
            "audience": "product",
            "ttl_days": 7,
        },
    )
    assert response.status_code == 200
    view = response.json()
    assert view["status"] == "proposed"
    assert view["utility"]["utility_score"] >= 80

    decision = client.post(
        f"/v1/taskviews/{view['id']}/decision",
        json={"approved": True, "reviewer": "cx-owner@taskview.local"},
    )
    assert decision.status_code == 200
    assert decision.json()["status"] == "approved"

    evidence = client.get(f"/v1/taskviews/{view['id']}/evidence")
    assert evidence.status_code == 200
    assert evidence.json()["minimum_group_size"] == 20
    assert len(evidence.json()["content_sha256"]) == 64

    get_settings.cache_clear()


def test_ttl_policy_blocks_approval(monkeypatch):
    monkeypatch.setenv("TASKVIEW_BE_FAKE_AI", "true")
    get_settings.cache_clear()
    store.clear()
    client = TestClient(app)

    response = client.post(
        "/v1/taskviews/preview",
        json={
            "purpose": "장기간 VOC 변화 추세를 제품 조직과 함께 비교 분석하고 싶다",
            "audience": "product",
            "ttl_days": 14,
        },
    )
    view = response.json()
    assert view["status"] == "blocked"

    decision = client.post(
        f"/v1/taskviews/{view['id']}/decision",
        json={"approved": True, "reviewer": "cx-owner@taskview.local"},
    )
    assert decision.status_code == 409

    get_settings.cache_clear()

