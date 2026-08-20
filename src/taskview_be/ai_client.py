import httpx

from .config import Settings
from .experience_schemas import BusinessIntent, PurposeInterpretationRequest
from .schemas import PreviewRequest, PurposeSpec, TransformPlanItem, ViewPlan


def _is_signup_diagnosis(purpose: str) -> bool:
    normalized = purpose.casefold()
    has_signup = any(keyword in normalized for keyword in ("회원가입", "signup", "가입 이탈"))
    has_diagnosis = any(keyword in normalized for keyword in ("원인", "진단", "dropoff", "이탈"))
    return has_signup and has_diagnosis


def _fake_signup_plan(request: PreviewRequest) -> ViewPlan:
    return ViewPlan(
        purpose_spec=PurposeSpec(
            objective=request.purpose,
            decision_to_support="회원가입 이탈의 상위 원인을 정한다",
            audience=request.audience,
            requested_fields=[
                "event_time",
                "os_family",
                "os_version",
                "dropoff_step",
                "error_log",
                "exact_address",
                "birth_date",
                "ticket_text",
                "customer_name",
                "phone",
                "email",
            ],
        ),
        selected_sources=["product", "operations", "voc"],
        transformations=[
            TransformPlanItem(
                source="product",
                input_fields=["event_time"],
                output_field="week",
                transformation="aggregate",
                rationale="개별 이벤트 시각 대신 주 단위만 유지",
            ),
            TransformPlanItem(
                source="product",
                input_fields=["os_family"],
                output_field="os_family",
                transformation="select",
                rationale="OS 계열별 이탈 차이를 비교하는 최소 차원",
            ),
            TransformPlanItem(
                source="product",
                input_fields=["os_version"],
                output_field="os_version",
                transformation="select",
                rationale="세부 빌드 대신 OS 버전 계열만 유지",
            ),
            TransformPlanItem(
                source="product",
                input_fields=["dropoff_step"],
                output_field="signup_step",
                transformation="select",
                rationale="회원가입 단계별 이탈 위치를 비교",
            ),
            TransformPlanItem(
                source="product",
                input_fields=["error_log"],
                output_field="error_category",
                transformation="classify",
                rationale="오류 원문 대신 검증된 오류 범주만 제공",
            ),
            TransformPlanItem(
                source="operations",
                input_fields=["exact_address"],
                output_field="region_group",
                transformation="region_group",
                rationale="정확한 주소를 권역으로 일반화",
            ),
            TransformPlanItem(
                source="operations",
                input_fields=["birth_date"],
                output_field="age_band",
                transformation="age_band",
                rationale="생년월일 대신 연령대만 제공",
            ),
            TransformPlanItem(
                source="voc",
                input_fields=["ticket_text"],
                output_field="complaint_theme",
                transformation="classify",
                rationale="상담 원문 대신 불만 주제만 추출",
            ),
            TransformPlanItem(
                source="voc",
                input_fields=["customer_name"],
                output_field="customer_name",
                transformation="drop",
                rationale="직접 식별자는 목적에 필요하지 않음",
            ),
            TransformPlanItem(
                source="voc",
                input_fields=["phone", "email"],
                output_field="contact",
                transformation="drop",
                rationale="연락처는 Task View에서 제외",
            ),
        ],
        preview_columns=[
            "week",
            "region_group",
            "age_band",
            "os_family",
            "os_version",
            "signup_step",
            "error_category",
            "complaint_theme",
            "case_count",
        ],
        assumptions=[
            f"View는 {request.ttl_days}일 뒤 만료된다",
            "세 소스의 집계 그룹은 20건 이상이어야 한다",
            "원문과 직접 식별자는 어떤 출력에서도 반환하지 않는다",
        ],
    )


def _fake_plan(request: PreviewRequest) -> ViewPlan:
    if _is_signup_diagnosis(request.purpose):
        return _fake_signup_plan(request)
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
        assumptions=[
            f"View는 {request.ttl_days}일 뒤 만료된다",
            "집계 그룹은 20건 이상이어야 한다",
        ],
    )


async def request_plan(request: PreviewRequest, settings: Settings) -> ViewPlan:
    if settings.taskview_be_fake_ai:
        return _fake_plan(request)

    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            f"{settings.taskview_ai_url.rstrip('/')}/v1/agent/plan",
            headers=_ai_headers(settings),
            json=request.model_dump(include={"purpose", "audience", "ttl_days"}),
        )
        response.raise_for_status()
        return ViewPlan.model_validate(response.json())


async def request_business_intent(
    request: PurposeInterpretationRequest, settings: Settings
) -> BusinessIntent:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{settings.taskview_ai_url.rstrip('/')}/v1/agent/interpret",
            headers=_ai_headers(settings),
            json={
                "purpose": request.purpose,
                "audience": request.audience,
                "ttl_days": request.ttl_days,
            },
        )
        response.raise_for_status()
        return BusinessIntent.model_validate(response.json())


def _ai_headers(settings: Settings) -> dict[str, str]:
    secret = settings.taskview_ai_shared_secret
    if secret is None or not secret.get_secret_value():
        return {}
    return {"authorization": f"Bearer {secret.get_secret_value()}"}
