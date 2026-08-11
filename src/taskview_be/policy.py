from .schemas import PolicyFinding, PreviewRequest, UtilityReport, ViewPlan

REQUIRED_TRANSFORMS = {
    "user_id": "drop",
    "customer_name": "drop",
    "ticket_id": "drop",
    "account_id": "mask",
    "address": "region_group",
    "age": "age_band",
}

CATALOG_FIELDS = {
    "product": {"event_date", "feature", "account_id", "user_id", "usage_count"},
    "operations": {"ticket_id", "created_at", "status", "assignee", "region", "resolution_hours"},
    "voc": {"ticket_id", "created_at", "customer_name", "address", "age", "message", "issue_type"},
}


def evaluate_policy(request: PreviewRequest, plan: ViewPlan) -> list[PolicyFinding]:
    findings: list[PolicyFinding] = []
    for item in plan.transformations:
        if item.source not in plan.selected_sources:
            findings.append(
                PolicyFinding(
                    code="SOURCE_NOT_SELECTED",
                    severity="block",
                    field=item.source,
                    message=f"변환 소스 {item.source}가 선택된 소스에 없습니다.",
                    action="카탈로그 검색 결과와 selected_sources를 일치시키세요.",
                )
            )
        for field in item.input_fields:
            if field not in CATALOG_FIELDS[item.source]:
                findings.append(
                    PolicyFinding(
                        code="UNKNOWN_CATALOG_FIELD",
                        severity="block",
                        field=field,
                        message=f"{item.source} 카탈로그에 {field} 필드가 없습니다.",
                        action="카탈로그에 등록된 필드만 사용하세요.",
                    )
                )
            expected = REQUIRED_TRANSFORMS.get(field)
            if expected and item.transformation != expected:
                findings.append(
                    PolicyFinding(
                        code="SENSITIVE_FIELD_TRANSFORM",
                        severity="block",
                        field=field,
                        message=f"{field} 필드는 {expected} 변환이 필요합니다.",
                        action=f"변환을 {expected}로 변경하세요.",
                    )
                )
            if field == "message" and request.audience == "product" and item.transformation != "classify":
                findings.append(
                    PolicyFinding(
                        code="RAW_VOC_FOR_PRODUCT",
                        severity="block",
                        field=field,
                        message="제품 분석에는 VOC 원문을 제공할 수 없습니다.",
                        action="원문을 issue_type으로 분류하세요.",
                    )
                )

    produced_columns = {
        item.output_field for item in plan.transformations if item.transformation != "drop"
    } | {"case_count"}
    for column in plan.preview_columns:
        if column not in produced_columns:
            findings.append(
                PolicyFinding(
                    code="UNKNOWN_PREVIEW_COLUMN",
                    severity="block",
                    field=column,
                    message=f"{column} 컬럼은 변환 계획에서 생성되지 않았습니다.",
                    action="미리보기 컬럼을 검증된 변환 결과로 제한하세요.",
                )
            )

    if request.ttl_days > 7:
        findings.append(
            PolicyFinding(
                code="TTL_LIMIT",
                severity="block",
                message="Task View의 최대 TTL은 7일입니다.",
                action="TTL을 7일 이하로 줄이세요.",
            )
        )

    if not findings:
        findings.append(
            PolicyFinding(
                code="POLICY_READY",
                severity="info",
                message="필수 최소화·변환 규칙을 충족했습니다.",
                action="데이터 소유자 승인을 요청하세요.",
            )
        )
    return findings


def calculate_utility(plan: ViewPlan) -> UtilityReport:
    removed = sum(1 for item in plan.transformations if item.transformation == "drop")
    selected = len(plan.preview_columns)
    score = max(0, min(100, 92 - removed * 4))
    return UtilityReport(
        selected_field_count=selected,
        removed_field_count=removed,
        estimated_rows=480,
        utility_score=score,
    )
