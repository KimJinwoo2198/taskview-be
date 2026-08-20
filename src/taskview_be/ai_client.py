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

    source = _source_for_purpose(request.purpose, request.audience)
    if source == "operations":
        return ViewPlan(
            purpose_spec=PurposeSpec(
                objective=request.purpose,
                decision_to_support="운영 인력 배치 우선순위를 정한다",
                audience=request.audience,
                requested_fields=[
                    "created_date",
                    "borough",
                    "agency",
                    "complaint_type",
                    "resolution_hours",
                    "incident_address",
                    "latitude",
                    "longitude",
                ],
            ),
            selected_sources=["operations"],
            transformations=[
                TransformPlanItem(
                    source="operations",
                    input_fields=["created_date"],
                    output_field="week",
                    transformation="aggregate",
                    rationale="민원 접수를 주 단위로 집계",
                ),
                TransformPlanItem(
                    source="operations",
                    input_fields=["borough"],
                    output_field="region",
                    transformation="region_group",
                    rationale="상세 주소 없이 borough 수준만 유지",
                ),
                TransformPlanItem(
                    source="operations",
                    input_fields=["agency"],
                    output_field="agency",
                    transformation="select",
                    rationale="담당 기관별 병목 비교",
                ),
                TransformPlanItem(
                    source="operations",
                    input_fields=["complaint_type"],
                    output_field="complaint_type",
                    transformation="select",
                    rationale="민원 유형별 운영 수요 비교",
                ),
                TransformPlanItem(
                    source="operations",
                    input_fields=["resolution_hours"],
                    output_field="avg_resolution_hours",
                    transformation="aggregate",
                    rationale="개별 민원이 아닌 평균 처리시간 제공",
                ),
                TransformPlanItem(
                    source="operations",
                    input_fields=["incident_address", "latitude", "longitude"],
                    output_field="precise_location",
                    transformation="drop",
                    rationale="정확한 위치는 수집·출력하지 않음",
                ),
            ],
            preview_columns=[
                "week",
                "region",
                "agency",
                "complaint_type",
                "avg_resolution_hours",
                "case_count",
            ],
            assumptions=[
                f"View는 {request.ttl_days}일 뒤 만료된다",
                "NYC 공식 공개 데이터에서 20건 이상 그룹만 제공한다",
            ],
        )
    if source == "product":
        return ViewPlan(
            purpose_spec=PurposeSpec(
                objective=request.purpose,
                decision_to_support="소비자 불만 대응 우선순위를 정한다",
                audience=request.audience,
                requested_fields=[
                    "ticket_created",
                    "state",
                    "issue_type",
                    "method",
                    "caller_id_number",
                ],
            ),
            selected_sources=["product"],
            transformations=[
                TransformPlanItem(
                    source="product",
                    input_fields=["ticket_created"],
                    output_field="week",
                    transformation="aggregate",
                    rationale="접수 시각을 주 단위로 집계",
                ),
                TransformPlanItem(
                    source="product",
                    input_fields=["state"],
                    output_field="region",
                    transformation="region_group",
                    rationale="상세 위치 없이 주 수준만 유지",
                ),
                TransformPlanItem(
                    source="product",
                    input_fields=["issue_type"],
                    output_field="issue_type",
                    transformation="select",
                    rationale="불만 유형별 개선 우선순위 비교",
                ),
                TransformPlanItem(
                    source="product",
                    input_fields=["method"],
                    output_field="channel",
                    transformation="select",
                    rationale="접수 채널별 차이 비교",
                ),
                TransformPlanItem(
                    source="product",
                    input_fields=["caller_id_number"],
                    output_field="caller_id_number",
                    transformation="drop",
                    rationale="전화번호는 수집·출력하지 않음",
                ),
            ],
            preview_columns=["week", "region", "issue_type", "channel", "case_count"],
            assumptions=[
                f"View는 {request.ttl_days}일 뒤 만료된다",
                "FCC 공식 공개 데이터에서 20건 이상 그룹만 제공한다",
            ],
        )
    return ViewPlan(
        purpose_spec=PurposeSpec(
            objective=request.purpose,
            decision_to_support="차량 안전 조사 우선순위를 정한다",
            audience=request.audience,
            requested_fields=[
                "date_complaint_filed",
                "manufacturer",
                "model_year",
                "component",
                "crash",
                "fire",
                "vin",
                "summary",
            ],
        ),
        selected_sources=["voc"],
        transformations=[
            TransformPlanItem(
                source="voc",
                input_fields=["date_complaint_filed"],
                output_field="week",
                transformation="aggregate",
                rationale="접수일을 주 단위로 집계",
            ),
            TransformPlanItem(
                source="voc",
                input_fields=["manufacturer"],
                output_field="manufacturer",
                transformation="select",
                rationale="제조사별 안전 신호 비교",
            ),
            TransformPlanItem(
                source="voc",
                input_fields=["model_year"],
                output_field="model_year",
                transformation="select",
                rationale="연식별 위험 신호 비교",
            ),
            TransformPlanItem(
                source="voc",
                input_fields=["component"],
                output_field="component",
                transformation="select",
                rationale="부품군별 안전 이슈 비교",
            ),
            TransformPlanItem(
                source="voc",
                input_fields=["crash"],
                output_field="crash_count",
                transformation="aggregate",
                rationale="사고 보고 건수를 집계",
            ),
            TransformPlanItem(
                source="voc",
                input_fields=["fire"],
                output_field="fire_count",
                transformation="aggregate",
                rationale="화재 보고 건수를 집계",
            ),
            TransformPlanItem(
                source="voc",
                input_fields=["vin", "summary"],
                output_field="raw_complaint",
                transformation="drop",
                rationale="VIN과 원문은 수집·출력하지 않음",
            ),
        ],
        preview_columns=[
            "manufacturer",
            "model_year",
            "component",
            "crash_count",
            "fire_count",
            "case_count",
        ],
        assumptions=[
            f"View는 {request.ttl_days}일 뒤 만료된다",
            "NHTSA 공식 공개 데이터에서 20건 이상 그룹만 제공한다",
        ],
    )


def _source_for_purpose(purpose: str, audience: str) -> str:
    normalized = purpose.casefold()
    if any(keyword in normalized for keyword in ("311", "도시 운영", "처리 지연", "처리시간")):
        return "operations"
    if any(
        keyword in normalized for keyword in ("nhtsa", "차량", "자동차", "안전", "사고", "화재")
    ):
        return "voc"
    if any(keyword in normalized for keyword in ("fcc", "통신", "소비자 불만", "로보콜")):
        return "product"
    return {"operations": "operations", "support": "voc"}.get(audience, "product")


def _fake_intent(request: PurposeInterpretationRequest) -> BusinessIntent:
    source = _source_for_purpose(request.purpose, request.audience)
    if source == "operations":
        subject = "도시 민원 처리"
        dimensions = ["지역", "담당 기관", "민원 유형"]
        outcome = "운영 인력 배치 우선순위를 정한다"
        region = "뉴욕시 전체"
    elif source == "voc":
        subject = "차량 안전 신고"
        dimensions = ["제조사", "연식", "문제 부위"]
        outcome = "안전 조사 우선순위를 정한다"
        region = "미국 전체"
    else:
        subject = "소비자 불만"
        dimensions = ["지역", "불만 유형", "접수 방법"]
        outcome = "소비자 대응 우선순위를 정한다"
        region = "미국 전체"
    return BusinessIntent(
        summary=request.purpose.strip(),
        subject=subject,
        comparison_dimensions=dimensions,
        desired_outcome=outcome,
        region_label=region,
        department=request.audience,
        selected_source=source,
        confidence=0.72,
        needs_clarification=False,
        clarifying_question=None,
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
    if settings.taskview_be_fake_ai:
        return _fake_intent(request)
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
