from taskview_be.ai_client import _fake_intent, _fake_plan
from taskview_be.experience_schemas import PurposeInterpretationRequest
from taskview_be.schemas import PreviewRequest


def test_fake_plan_routes_nyc_purpose_to_public_operations_schema() -> None:
    request = PreviewRequest(
        purpose="최근 NYC 311 민원에서 담당 기관별 처리 지연을 찾아 인력을 배치하고 싶다",
        audience="operations",
    )

    plan = _fake_plan(request)

    assert plan.selected_sources == ["operations"]
    assert plan.preview_columns == [
        "week",
        "region",
        "agency",
        "complaint_type",
        "avg_resolution_hours",
        "case_count",
    ]


def test_fake_intent_works_without_remote_ai() -> None:
    request = PurposeInterpretationRequest(
        purpose="최근 NHTSA 차량 안전 신고에서 제조사별 화재 신호를 찾고 싶다",
        audience="support",
        region="GLOBAL",
        ttl_days=7,
        output_mode="dashboard_api",
    )

    intent = _fake_intent(request)

    assert intent.selected_source == "voc"
    assert intent.subject == "차량 안전 신고"
    assert intent.needs_clarification is False
