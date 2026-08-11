from fastapi.testclient import TestClient

from taskview_be.config import get_settings
from taskview_be.main import app
from taskview_be.policy import evaluate_policy
from taskview_be.schemas import PreviewRequest, PurposeSpec, TransformPlanItem, ViewPlan


def enable_fake_ai(monkeypatch) -> None:
    monkeypatch.setenv("TASKVIEW_BE_FAKE_AI", "true")
    get_settings.cache_clear()


def test_preview_approve_and_evidence(monkeypatch):
    enable_fake_ai(monkeypatch)
    with TestClient(app) as client:
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


def test_postgres_persists_across_application_restart(monkeypatch):
    enable_fake_ai(monkeypatch)
    with TestClient(app) as first_client:
        response = first_client.post(
            "/v1/taskviews/preview",
            json={
                "purpose": "운영 지표를 지역별로 묶어 지원 인력 우선순위를 정하고 싶다",
                "audience": "operations",
                "ttl_days": 3,
            },
        )
        assert response.status_code == 200
        view_id = response.json()["id"]

    with TestClient(app) as restarted_client:
        persisted = restarted_client.get(f"/v1/taskviews/{view_id}")
        assert persisted.status_code == 200
        assert persisted.json()["id"] == view_id

    get_settings.cache_clear()


def test_ttl_policy_blocks_approval(monkeypatch):
    enable_fake_ai(monkeypatch)
    with TestClient(app) as client:
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
