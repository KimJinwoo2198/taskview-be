import httpx

from .config import Settings
from .schemas import PreviewRequest, PurposeSpec, TransformPlanItem, ViewPlan


def _fake_plan(request: PreviewRequest) -> ViewPlan:
    return ViewPlan(
        purpose_spec=PurposeSpec(
            objective=request.purpose,
            decision_to_support="다음 스프린트의 개선 우선순위를 정한다",
            audience=request.audience,
            requested_fields=["created_at", "address", "message", "ticket_id"],
        ),
        selected_sources=["voc"],
        transformations=[
            TransformPlanItem(
                source="voc",
                input_fields=["created_at"],
                output_field="week",
                transformation="aggregate",
                rationale="주간 추세 비교에 필요한 시간 단위만 유지",
            ),
            TransformPlanItem(
                source="voc",
                input_fields=["address"],
                output_field="region",
                transformation="region_group",
                rationale="정확한 주소를 노출하지 않고 지역 수준으로 축약",
            ),
            TransformPlanItem(
                source="voc",
                input_fields=["message"],
                output_field="issue_type",
                transformation="classify",
                rationale="VOC 원문 대신 업무에 필요한 이슈 유형만 제공",
            ),
            TransformPlanItem(
                source="voc",
                input_fields=["ticket_id"],
                output_field="ticket_id",
                transformation="drop",
                rationale="제품 우선순위 판단에 직접 식별자는 불필요",
            ),
        ],
        preview_columns=["week", "region", "issue_type", "case_count"],
        assumptions=[f"View는 {request.ttl_days}일 뒤 만료된다", "집계 그룹은 20건 이상이어야 한다"],
    )


async def request_plan(request: PreviewRequest, settings: Settings) -> ViewPlan:
    if settings.taskview_be_fake_ai:
        return _fake_plan(request)

    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            f"{settings.taskview_ai_url.rstrip('/')}/v1/agent/plan",
            json=request.model_dump(),
        )
        response.raise_for_status()
        return ViewPlan.model_validate(response.json())

