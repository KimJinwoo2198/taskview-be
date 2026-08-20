from collections import Counter
from datetime import UTC, datetime

from .experience import SOURCE_BY_KEY, build_data_response, task_view_name
from .journey_schemas import (
    AnalyticsBucket,
    ApprovalStatusResponse,
    ApprovalTimelineItem,
    DiscoveryField,
    DiscoveryResponse,
    DiscoverySource,
    NeedexAnalytics,
)
from .schemas import NeedexResponse

DISCOVERY_FIELDS: dict[str, list[tuple[str, str, str]]] = {
    "product": [
        ("issue_type", "string", "FCC 소비자 불만의 상위 유형"),
        ("method", "string", "소비자 불만 접수 채널"),
        ("caller_id_number", "string", "전화번호이므로 수집 단계에서 제외"),
    ],
    "operations": [
        ("agency", "string", "NYC 311 담당 기관"),
        ("complaint_type", "string", "운영 수요를 설명하는 민원 유형"),
        ("exact_address", "string", "정확한 주소 대신 borough 수준으로 일반화"),
    ],
    "voc": [
        ("component", "string", "NHTSA 안전 불만의 차량 부품군"),
        ("crash", "integer", "사고 동반 보고 여부의 집계"),
        ("vin", "string", "차량 식별자이므로 수집 단계에서 제외"),
        ("summary", "text", "민원 원문이므로 수집 단계에서 제외"),
    ],
}

SOURCE_REASONS = {
    "product": "FCC 공식 소비자 불만에서 이슈·채널·주 단위 추세를 안전하게 집계합니다.",
    "operations": "NYC 311 공식 데이터에서 기관·민원 유형·처리시간 병목을 비교합니다.",
    "voc": "NHTSA 공식 안전 불만에서 차량 부품·사고·화재 신호만 집계합니다.",
}


def _field_decision(
    view: NeedexResponse, source_key: str, field_name: str
) -> tuple[str, str | None]:
    for item in view.plan.transformations:
        if item.source != source_key or field_name not in item.input_fields:
            continue
        mapping = {
            "select": "required",
            "aggregate": "required",
            "region_group": "generalize",
            "age_band": "bucket",
            "classify": "extract",
            "drop": "drop",
            "mask": "drop",
        }
        return mapping[item.transformation], (
            None if item.transformation in {"drop", "mask"} else item.output_field
        )
    if field_name in {"customer_name", "phone", "email"}:
        return "drop", None
    if field_name == "exact_address":
        return "generalize", "region_group"
    if field_name == "birth_date":
        return "bucket", "age_band"
    if field_name == "ticket_text":
        return "extract", "complaint_theme"
    if field_name in {"dropoff_step", "os_version", "device"}:
        return "required", field_name
    return "candidate", field_name


def build_discovery(view: NeedexResponse) -> DiscoveryResponse:
    selected = list(dict.fromkeys(view.plan.selected_sources))
    sources: list[DiscoverySource] = []
    candidate_count = 0
    reviewed_count = 0
    for source_key in selected:
        source = SOURCE_BY_KEY[source_key]
        fields: list[DiscoveryField] = []
        for name, data_type, rationale in DISCOVERY_FIELDS[source_key]:
            decision, task_field = _field_decision(view, source_key, name)
            candidate_count += decision != "drop"
            reviewed_count += 1
            fields.append(
                DiscoveryField(
                    name=name,
                    data_type=data_type,
                    decision=decision,
                    task_field=task_field,
                    rationale=rationale,
                )
            )
        sources.append(
            DiscoverySource(
                source_id=source.id,
                source_key=source.key,
                source_name=source.short_name,
                country_flag=source.country_flag,
                dataset=source.datasets[0],
                reason=SOURCE_REASONS[source_key],
                fields=fields,
            )
        )
    return DiscoveryResponse(
        view_id=view.id,
        purpose=view.purpose,
        requester=view.requester.display_name if view.requester else "Product Team · Seoul",
        region=view.region,
        ttl_days=view.ttl_days,
        sources=sources,
        reviewed_field_count=reviewed_count,
        candidate_field_count=candidate_count,
        completion_percent=100,
    )


def build_approval_status(
    view: NeedexResponse,
    *,
    submission: object | None,
    queue_total: int,
    queue_position: int | None,
) -> ApprovalStatusResponse:
    request_id = getattr(submission, "request_id", None)
    submitted_at = getattr(submission, "submitted_at", None)
    submitted = submission is not None
    if view.status == "approved":
        state = "approved"
    elif view.status == "rejected":
        state = "rejected"
    elif not submitted:
        state = "not_submitted"
    elif view.status == "blocked":
        state = "blocked"
    else:
        state = "pending"

    owner_status = (
        "issued"
        if state == "approved"
        else "rejected"
        if state == "rejected"
        else "review_required"
    )
    final_status = (
        "issued" if state == "approved" else "rejected" if state == "rejected" else "waiting"
    )
    timeline = [
        ApprovalTimelineItem(
            organization="Seoul Product",
            country_flag="🇰🇷",
            status="complete",
            title="요청자 확인",
            detail="Product Team · Seoul",
        ),
        ApprovalTimelineItem(
            organization="Tokyo Operations",
            country_flag="🇯🇵",
            status=owner_status,
            title="고위험 변환 검토",
            detail="상세 주소와 세분화 수준을 확인합니다.",
            affected_fields=["exact_address", "precise age"],
        ),
        ApprovalTimelineItem(
            organization="HCMC CS",
            country_flag="🇻🇳",
            status=owner_status if state in {"approved", "rejected"} else "waiting",
            title="상담 원문 정책 검토",
            detail="원문 대신 범주 추출만 허용합니다.",
            affected_fields=["raw_ticket_text"],
        ),
        ApprovalTimelineItem(
            organization="Needex",
            country_flag="T",
            status=final_status,
            title="최종 View 발급",
            detail="모든 승인 완료 후 자동 생성됩니다.",
        ),
    ]
    return ApprovalStatusResponse(
        view_id=view.id,
        request_id=request_id,
        submitted=submitted,
        state=state,
        queue_position=queue_position,
        queue_total=queue_total,
        submitted_at=submitted_at,
        estimated_response_minutes=18 if state in {"pending", "blocked"} else None,
        evidence_ready=view.evidence is not None or submitted,
        timeline=timeline,
    )


def _buckets(rows: list[dict[str, str | int]], field: str) -> list[AnalyticsBucket]:
    counts: Counter[str] = Counter()
    for row in rows:
        if field not in row or row[field] in {"", None}:
            continue
        counts[str(row[field])] += int(row.get("case_count", 1))
    total = sum(counts.values())
    if not total:
        return []
    return [
        AnalyticsBucket(key=key, count=count, share=round(count / total, 4))
        for key, count in counts.most_common(8)
    ]


def build_analytics(
    view: NeedexResponse,
    *,
    period_days: int,
    region: str,
    os: str,
    cohort: str,
) -> NeedexAnalytics:
    data = build_data_response(view)
    metrics = {
        "case_count",
        "avg_resolution_hours",
        "crash_count",
        "fire_count",
        "injury_count",
        "death_count",
    }
    fields = [field for field in data.columns if field not in metrics]
    grouped = {field: _buckets(data.rows, field) for field in fields if field in data.columns}
    remaining = max(0, (data.expires_at.date() - datetime.now(UTC).date()).days)
    return NeedexAnalytics(
        view_id=view.id,
        view_name=task_view_name(view),
        data_origin=data.data_origin,
        period_days=period_days,
        region=region,
        os=os,
        cohort=cohort,
        record_count=sum(int(row.get("case_count", 1)) for row in data.rows),
        utility_state="meets_standard" if view.utility.utility_score >= 70 else "review_required",
        remaining_ttl_days=remaining,
        grouped_insights=grouped,
        allowed_questions=[f"{field}별 상위 패턴은 무엇인가?" for field in fields[:4]],
        generated_at=datetime.now(UTC),
    )
