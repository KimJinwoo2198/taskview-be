import re
from datetime import UTC, datetime, timedelta

from .auth_schemas import UserPublic
from .experience_schemas import (
    AlternativeChange,
    ApiArtifact,
    ApprovalReason,
    ApprovalReview,
    BusinessIntent,
    CompilationResponse,
    DashboardArtifact,
    DashboardCounters,
    DashboardResponse,
    DataField,
    DataResponse,
    DataSource,
    FirewallCheck,
    NeedexArtifacts,
    NeedexCard,
    PrivacyFirewallSummary,
    PurposeInterpretation,
    PurposeInterpretationRequest,
    RecommendedAlternative,
    SchemaField,
    SemanticTransform,
    SourceLineage,
    SourceMatch,
    UtilityCandidate,
)
from .schemas import NeedexResponse, TransformPlanItem

POLICY_VERSION = "taskview-policy/2026-08-18"
DIRECT_IDENTIFIERS = ["name", "phone", "email", "customer_name", "user_id", "ticket_id"]


LEGACY_DATA_SOURCES: tuple[DataSource, ...] = (
    DataSource(
        id="src_seoul_product",
        key="product",
        name="Seoul Product DB",
        short_name="Seoul Product",
        country_code="KR",
        country_flag="🇰🇷",
        region="Seoul",
        owner="Seoul Product",
        description="signup_events · error_log",
        datasets=["signup_events", "error_log"],
        fields=[
            DataField(
                name="event_date",
                data_type="date",
                privacy_class="non_sensitive",
                allowed_transforms=["bucket"],
            ),
            DataField(
                name="event_time",
                data_type="datetime",
                privacy_class="non_sensitive",
                allowed_transforms=["bucket"],
            ),
            DataField(
                name="feature",
                data_type="string",
                privacy_class="non_sensitive",
                allowed_transforms=["select"],
            ),
            DataField(
                name="usage_count",
                data_type="integer",
                privacy_class="non_sensitive",
                allowed_transforms=["aggregate"],
            ),
            DataField(
                name="account_id",
                data_type="string",
                privacy_class="direct_identifier",
                allowed_transforms=["mask", "drop"],
            ),
            DataField(
                name="user_id",
                data_type="string",
                privacy_class="direct_identifier",
                allowed_transforms=["drop"],
            ),
            DataField(
                name="os_family",
                data_type="string",
                privacy_class="non_sensitive",
                allowed_transforms=["select"],
            ),
            DataField(
                name="os_version",
                data_type="string",
                privacy_class="quasi_identifier",
                allowed_transforms=["select"],
            ),
            DataField(
                name="dropoff_step",
                data_type="string",
                privacy_class="non_sensitive",
                allowed_transforms=["select"],
            ),
            DataField(
                name="error_log",
                data_type="text",
                privacy_class="sensitive",
                allowed_transforms=["extract_category", "drop"],
            ),
        ],
    ),
    DataSource(
        id="src_tokyo_operations",
        key="operations",
        name="Tokyo Operations DB",
        short_name="Tokyo Operations",
        country_code="JP",
        country_flag="🇯🇵",
        region="Tokyo",
        owner="Tokyo Operations",
        description="device · region · operation_issue",
        datasets=["device", "region", "operation_issue"],
        fields=[
            DataField(
                name="created_at",
                data_type="datetime",
                privacy_class="non_sensitive",
                allowed_transforms=["bucket"],
            ),
            DataField(
                name="region",
                data_type="string",
                privacy_class="quasi_identifier",
                allowed_transforms=["select", "generalize"],
            ),
            DataField(
                name="status",
                data_type="string",
                privacy_class="non_sensitive",
                allowed_transforms=["select"],
            ),
            DataField(
                name="resolution_hours",
                data_type="integer",
                privacy_class="non_sensitive",
                allowed_transforms=["aggregate"],
            ),
            DataField(
                name="ticket_id",
                data_type="string",
                privacy_class="direct_identifier",
                allowed_transforms=["drop"],
            ),
            DataField(
                name="exact_address",
                data_type="string",
                privacy_class="quasi_identifier",
                allowed_transforms=["generalize"],
            ),
            DataField(
                name="birth_date",
                data_type="date",
                privacy_class="quasi_identifier",
                allowed_transforms=["bucket"],
            ),
        ],
    ),
    DataSource(
        id="src_hcmc_cs",
        key="voc",
        name="Ho Chi Minh CS DB",
        short_name="HCMC CS",
        country_code="VN",
        country_flag="🇻🇳",
        region="Ho Chi Minh City",
        owner="HCMC CS",
        description="ticket_text · customer_context",
        datasets=["ticket_text", "customer_context"],
        fields=[
            DataField(
                name="created_at",
                data_type="datetime",
                privacy_class="non_sensitive",
                allowed_transforms=["bucket"],
            ),
            DataField(
                name="customer_name",
                data_type="string",
                privacy_class="direct_identifier",
                allowed_transforms=["drop"],
            ),
            DataField(
                name="address",
                data_type="string",
                privacy_class="quasi_identifier",
                allowed_transforms=["generalize"],
            ),
            DataField(
                name="age",
                data_type="integer",
                privacy_class="quasi_identifier",
                allowed_transforms=["bucket"],
            ),
            DataField(
                name="message",
                data_type="text",
                privacy_class="sensitive",
                allowed_transforms=["extract_category", "drop"],
            ),
            DataField(
                name="issue_type",
                data_type="string",
                privacy_class="non_sensitive",
                allowed_transforms=["select"],
            ),
            DataField(
                name="ticket_id",
                data_type="string",
                privacy_class="direct_identifier",
                allowed_transforms=["drop"],
            ),
            DataField(
                name="name",
                data_type="string",
                privacy_class="direct_identifier",
                allowed_transforms=["drop"],
            ),
            DataField(
                name="phone",
                data_type="string",
                privacy_class="direct_identifier",
                allowed_transforms=["drop"],
            ),
            DataField(
                name="email",
                data_type="string",
                privacy_class="direct_identifier",
                allowed_transforms=["drop"],
            ),
            DataField(
                name="ticket_text",
                data_type="text",
                privacy_class="sensitive",
                allowed_transforms=["extract_category", "drop"],
            ),
        ],
    ),
)

DATA_SOURCES: tuple[DataSource, ...] = (
    DataSource(
        id="src_fcc_consumer_complaints",
        key="product",
        name="FCC Consumer Complaints",
        short_name="FCC Complaints",
        country_code="US",
        country_flag="🇺🇸",
        region="United States",
        owner="Federal Communications Commission",
        provider="Federal Communications Commission",
        description="consumer complaints · issue · channel · state",
        datasets=["CGB Consumer Complaints"],
        official_url="https://catalog.data.gov/dataset/cgb-consumer-complaints-data",
        license_url="https://www.usa.gov/government-copyright",
        fields=[
            DataField(
                name="ticket_created",
                data_type="datetime",
                privacy_class="non_sensitive",
                allowed_transforms=["bucket"],
            ),
            DataField(
                name="state",
                data_type="string",
                privacy_class="quasi_identifier",
                allowed_transforms=["generalize"],
            ),
            DataField(
                name="issue_type",
                data_type="string",
                privacy_class="non_sensitive",
                allowed_transforms=["select"],
            ),
            DataField(
                name="issue",
                data_type="string",
                privacy_class="non_sensitive",
                allowed_transforms=["select"],
            ),
            DataField(
                name="method",
                data_type="string",
                privacy_class="non_sensitive",
                allowed_transforms=["select"],
            ),
            DataField(
                name="caller_id_number",
                data_type="string",
                privacy_class="direct_identifier",
                allowed_transforms=["drop"],
            ),
        ],
    ),
    DataSource(
        id="src_nyc_311",
        key="operations",
        name="NYC 311 Service Requests",
        short_name="NYC 311",
        country_code="US",
        country_flag="🇺🇸",
        region="New York City",
        owner="NYC Open Data",
        provider="NYC Open Data",
        description="agency · complaint type · borough · resolution time",
        datasets=["311 Service Requests from 2010 to Present"],
        official_url="https://data.cityofnewyork.us/resource/erm2-nwe9",
        license_url="https://opendata.cityofnewyork.us/overview/#termsofuse",
        fields=[
            DataField(
                name="created_date",
                data_type="datetime",
                privacy_class="non_sensitive",
                allowed_transforms=["bucket"],
            ),
            DataField(
                name="borough",
                data_type="string",
                privacy_class="quasi_identifier",
                allowed_transforms=["generalize"],
            ),
            DataField(
                name="agency",
                data_type="string",
                privacy_class="non_sensitive",
                allowed_transforms=["select"],
            ),
            DataField(
                name="complaint_type",
                data_type="string",
                privacy_class="non_sensitive",
                allowed_transforms=["select"],
            ),
            DataField(
                name="status",
                data_type="string",
                privacy_class="non_sensitive",
                allowed_transforms=["select"],
            ),
            DataField(
                name="resolution_hours",
                data_type="integer",
                privacy_class="non_sensitive",
                allowed_transforms=["aggregate"],
            ),
            DataField(
                name="incident_address",
                data_type="string",
                privacy_class="quasi_identifier",
                allowed_transforms=["drop"],
            ),
            DataField(
                name="latitude",
                data_type="string",
                privacy_class="quasi_identifier",
                allowed_transforms=["drop"],
            ),
            DataField(
                name="longitude",
                data_type="string",
                privacy_class="quasi_identifier",
                allowed_transforms=["drop"],
            ),
        ],
    ),
    DataSource(
        id="src_nhtsa_complaints",
        key="voc",
        name="NHTSA Vehicle Safety Complaints",
        short_name="NHTSA Safety",
        country_code="US",
        country_flag="🇺🇸",
        region="United States",
        owner="National Highway Traffic Safety Administration",
        provider="National Highway Traffic Safety Administration",
        description="vehicle · component · crash · fire · injuries",
        datasets=["NHTSA Consumer Complaints"],
        official_url="https://www.nhtsa.gov/nhtsa-datasets-and-apis",
        license_url="https://www.usa.gov/government-copyright",
        fields=[
            DataField(
                name="date_complaint_filed",
                data_type="date",
                privacy_class="non_sensitive",
                allowed_transforms=["bucket"],
            ),
            DataField(
                name="manufacturer",
                data_type="string",
                privacy_class="non_sensitive",
                allowed_transforms=["select"],
            ),
            DataField(
                name="model",
                data_type="string",
                privacy_class="non_sensitive",
                allowed_transforms=["select"],
            ),
            DataField(
                name="model_year",
                data_type="integer",
                privacy_class="non_sensitive",
                allowed_transforms=["select"],
            ),
            DataField(
                name="component",
                data_type="string",
                privacy_class="non_sensitive",
                allowed_transforms=["select"],
            ),
            DataField(
                name="crash",
                data_type="integer",
                privacy_class="non_sensitive",
                allowed_transforms=["aggregate"],
            ),
            DataField(
                name="fire",
                data_type="integer",
                privacy_class="non_sensitive",
                allowed_transforms=["aggregate"],
            ),
            DataField(
                name="vin",
                data_type="string",
                privacy_class="direct_identifier",
                allowed_transforms=["drop"],
            ),
            DataField(
                name="summary",
                data_type="text",
                privacy_class="sensitive",
                allowed_transforms=["drop"],
            ),
        ],
    ),
)

SOURCE_BY_KEY = {source.key: source for source in DATA_SOURCES}
OPERATOR_LABELS = {
    "select": "SELECT",
    "drop": "DROP",
    "mask": "MASK",
    "age_band": "BUCKET",
    "region_group": "GENERALIZE",
    "aggregate": "AGGREGATE",
    "classify": "EXTRACT_CATEGORY",
}


class NeedexExpiredError(ValueError):
    pass


def list_data_sources(
    snapshots: list[dict[str, object]] | None = None,
) -> list[DataSource]:
    snapshot_by_key = {str(item["source_key"]): item for item in snapshots or []}
    sources: list[DataSource] = []
    for source in DATA_SOURCES:
        copy = source.model_copy(deep=True)
        if snapshot := snapshot_by_key.get(source.key):
            copy.last_synced_at = snapshot.get("fetched_at")  # type: ignore[assignment]
            copy.row_count = int(snapshot.get("row_count") or 0)
        sources.append(copy)
    return sources


def task_view_name(view: NeedexResponse) -> str:
    purpose = view.purpose.casefold()
    region = "JP" if any(word in purpose for word in ("일본", "japan", "jp")) else "APAC"
    topic = (
        "SIGNUP_DIAGNOSIS"
        if any(word in purpose for word in ("회원가입", "signup", "가입 이탈"))
        else "PURPOSE_VIEW"
    )
    suffix = re.sub(r"[^A-Za-z0-9]", "", view.id)[-4:].upper()
    return f"{region}_{topic}_{suffix}"


def _matches_for_purpose(purpose: str) -> list[tuple[str, list[str], str]]:
    normalized = purpose.casefold()
    if any(word in normalized for word in ("회원가입", "signup", "가입 이탈")):
        return [
            ("product", ["issue_type", "method"], "FCC 소비자 불만의 접수 패턴을 비교합니다."),
            ("operations", ["agency", "complaint_type"], "NYC 311 운영 분류를 비교합니다."),
            ("voc", ["component", "crash"], "NHTSA 안전 불만의 위험 신호를 비교합니다."),
        ]
    matches: list[tuple[str, list[str], str]] = []
    if any(word in normalized for word in ("fcc", "통신", "로보콜", "소비자 불만", "전화")):
        matches.append(
            (
                "product",
                ["ticket_created", "state", "issue_type", "method"],
                "FCC 소비자 불만의 유형·채널·지역 추세가 목적과 일치합니다.",
            )
        )
    if any(word in normalized for word in ("311", "도시", "민원", "운영", "처리시간", "병목")):
        matches.append(
            (
                "operations",
                ["created_date", "borough", "agency", "complaint_type", "resolution_hours"],
                "NYC 311의 기관·민원 유형·처리시간이 운영 판단과 일치합니다.",
            )
        )
    if any(
        word in normalized for word in ("nhtsa", "차량", "자동차", "안전", "사고", "화재", "부품")
    ):
        matches.append(
            (
                "voc",
                ["manufacturer", "model_year", "component", "crash", "fire"],
                "NHTSA 안전 불만의 부품·사고·화재 신호가 목적과 일치합니다.",
            )
        )
    if not matches:
        matches.append(
            (
                "product",
                ["created_date", "borough", "agency", "complaint_type"],
                "공식 NYC 311 운영 데이터로 목적을 안전하게 탐색합니다.",
            )
        )
    return matches


def interpret_purpose(
    request: PurposeInterpretationRequest,
    user: UserPublic,
    intent: BusinessIntent | None = None,
) -> PurposeInterpretation:
    normalized = request.purpose.casefold()
    signup = any(word in normalized for word in ("회원가입", "signup", "가입 이탈"))
    target = "new iOS users" if "ios" in normalized else "업무 목적 대상 사용자"
    success = (
        "identify top causes"
        if any(word in normalized for word in ("원인", "진단", "cause"))
        else "support the stated decision"
    )
    task = (
        "JP signup dropoff diagnosis"
        if signup and request.region == "JP"
        else "purpose-to-data analysis"
    )
    matches = [
        SourceMatch(source=SOURCE_BY_KEY[key], matched_fields=fields, reason=reason)
        for key, fields, reason in _matches_for_purpose(request.purpose)
    ]
    if intent is None:
        intent = BusinessIntent(
            summary=request.purpose,
            subject="업무 현황",
            comparison_dimensions=["지역", "유형", "기간"],
            desired_outcome="업무 개선 우선순위를 정한다",
            region_label={
                "KR": "한국",
                "JP": "일본",
                "VN": "베트남",
                "APAC": "아시아·태평양",
                "GLOBAL": "전체 지역",
            }[request.region],
            department=request.audience,
            selected_source=matches[0].source.key,
            confidence=0.6,
        )
    return PurposeInterpretation(
        task=task,
        requester=user.display_name,
        target=target,
        region=request.region,
        success=success,
        ttl_days=request.ttl_days,
        output_mode=request.output_mode,
        matched_sources=matches,
        interpreted_at=datetime.now(UTC),
        summary=intent.summary,
        subject=intent.subject,
        comparison_dimensions=intent.comparison_dimensions,
        desired_outcome=intent.desired_outcome,
        region_label=intent.region_label,
        department=intent.department,
        confidence=intent.confidence,
        needs_clarification=intent.needs_clarification,
        clarifying_question=intent.clarifying_question,
    )


def build_dashboard(
    views: list[NeedexResponse],
    user: UserPublic,
    period_days: int,
    *,
    data_sources: list[DataSource] | None = None,
) -> DashboardResponse:
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=period_days)
    active = sum(
        view.status == "approved" and view.evidence is not None and view.evidence.expires_at > now
        for view in views
    )
    cards = [
        NeedexCard(
            id=view.id,
            name=task_view_name(view),
            purpose=view.purpose,
            ttl_days=view.ttl_days,
            status=view.status,
            requester_name=view.requester.display_name if view.requester else user.display_name,
            requester_region="Seoul",
            created_at=view.created_at,
        )
        for view in views[:5]
    ]
    return DashboardResponse(
        workspace_name=f"{user.display_name} Workspace",
        workspace_region="Seoul · KR",
        member=user,
        period_days=period_days,
        counters=DashboardCounters(
            active_task_views=active,
            created_in_period=sum(view.created_at >= cutoff for view in views),
            pending_approvals=sum(view.status == "proposed" for view in views),
            blocked_requests=sum(view.status == "blocked" for view in views),
            connected_sources=len(DATA_SOURCES),
        ),
        recent_task_views=cards,
        data_sources=data_sources or list_data_sources(),
        privacy_firewall=PrivacyFirewallSummary(
            denied_data=["direct identifiers", "raw text", "exact address"]
        ),
        generated_at=now,
    )


def _semantic_transform(item: TransformPlanItem) -> SemanticTransform:
    source = SOURCE_BY_KEY[item.source]
    return SemanticTransform(
        source_key=item.source,
        source_name=source.short_name,
        raw_fields=item.input_fields,
        operator=OPERATOR_LABELS[item.transformation],
        task_field=None if item.transformation == "drop" else item.output_field,
        rationale=item.rationale,
    )


def _firewall_checks(view: NeedexResponse) -> list[FirewallCheck]:
    checks: list[FirewallCheck] = []
    for finding in view.policy_findings:
        if finding.severity == "block":
            result = "DENY"
        elif finding.severity == "warning":
            result = "WARN"
        else:
            result = "PASS"
        checks.append(
            FirewallCheck(
                code=finding.code,
                label=finding.field or finding.code,
                result=result,
                detail=finding.message,
            )
        )
    if not any(check.code == "MINIMUM_GROUP_SIZE" for check in checks):
        checks.append(
            FirewallCheck(
                code="MINIMUM_GROUP_SIZE",
                label="group_size ≥ 20",
                result="PASS",
                detail="미리보기와 materialization은 최소 그룹 20건을 적용합니다.",
            )
        )
    return checks


def build_compilation(view: NeedexResponse) -> CompilationResponse:
    privacy_transforms = {"drop", "mask", "age_band", "region_group", "classify"}
    excluded = sorted(
        {
            field
            for item in view.plan.transformations
            if item.transformation in privacy_transforms
            for field in item.input_fields
        }
    )
    blocked = any(finding.severity == "block" for finding in view.policy_findings)
    return CompilationResponse(
        view_id=view.id,
        view_name=task_view_name(view),
        stage="blocked" if blocked else "validation_complete",
        source_match_count=len(view.plan.selected_sources),
        transforms=[_semantic_transform(item) for item in view.plan.transformations],
        utility_candidates=[
            UtilityCandidate(mode="raw", score=100, verdict="노출 최대"),
            UtilityCandidate(
                mode="static_masking",
                score=max(50, view.utility.utility_score - 18),
                verdict="맥락 손실 가능",
            ),
            UtilityCandidate(
                mode="taskview", score=view.utility.utility_score, verdict="결론 유지"
            ),
        ],
        firewall_checks=_firewall_checks(view),
        excluded_fields=excluded,
        can_submit_for_approval=is_approval_submission_allowed(view),
        policy_version=POLICY_VERSION,
    )


def _schema_type(field: str) -> str:
    if field in {"week", "event_date"}:
        return "date"
    if field in {"case_count", "usage_count", "avg_resolution_hours"}:
        return "integer"
    return "string"


def _schema_fields(view: NeedexResponse) -> list[SchemaField]:
    by_output = {
        item.output_field: item
        for item in view.plan.transformations
        if item.transformation != "drop"
    }
    fields: list[SchemaField] = []
    for column in view.plan.preview_columns:
        item = by_output.get(column)
        fields.append(
            SchemaField(
                name=column,
                data_type=_schema_type(column),
                source=SOURCE_BY_KEY[item.source].short_name if item else "Needex aggregate",
                transform=OPERATOR_LABELS[item.transformation] if item else "AGGREGATE",
            )
        )
    return fields


def _source_lineage(view: NeedexResponse) -> list[SourceLineage]:
    lineage: list[SourceLineage] = []
    for source_key in view.plan.selected_sources:
        source = SOURCE_BY_KEY[source_key]
        items = [item for item in view.plan.transformations if item.source == source_key]
        lineage.append(
            SourceLineage(
                source_id=source.id,
                source_name=source.short_name,
                country_flag=source.country_flag,
                fields=sorted({field for item in items for field in item.input_fields}),
                transforms=sorted({OPERATOR_LABELS[item.transformation] for item in items}),
            )
        )
    return lineage


def _sql_for_view(view: NeedexResponse, fields: list[SchemaField]) -> str:
    selections = []
    for field in fields:
        safe_name = field.name.replace('"', '""')
        expression = f"record ->> '{field.name}'"
        if field.data_type == "integer":
            expression = f"({expression})::integer"
        selections.append(f'    {expression} AS "{safe_name}"')
    select_list = ",\n".join(selections)
    return (
        "-- Read-only Needex projection; only approved, minimized preview data is exposed.\n"
        f"SELECT\n{select_list}\n"
        "FROM task_views\n"
        "CROSS JOIN LATERAL jsonb_array_elements(payload -> 'preview_rows') AS record\n"
        f"WHERE id = '{view.id}' AND status = 'approved';"
    )


def build_artifacts(view: NeedexResponse) -> NeedexArtifacts:
    fields = _schema_fields(view)
    privacy_transforms = {"drop", "mask", "age_band", "region_group", "classify"}
    removed = sorted(
        {
            field
            for item in view.plan.transformations
            if item.transformation in privacy_transforms
            for field in item.input_fields
        }
    )
    dimensions = [field.name for field in fields if field.data_type != "integer"]
    measures = [field.name for field in fields if field.data_type == "integer"]
    return NeedexArtifacts(
        view_id=view.id,
        view_name=task_view_name(view),
        schema_fields=fields,
        removed_fields=removed,
        sql=_sql_for_view(view, fields),
        api=ApiArtifact(path=f"/v1/taskviews/{view.id}/data", response_schema=fields),
        dashboard=DashboardArtifact(
            dimensions=dimensions,
            measures=measures,
            default_visualization="bar" if measures else "table",
        ),
        source_lineage=_source_lineage(view),
        evidence=view.evidence,
    )


def _alternative_for_view(view: NeedexResponse) -> RecommendedAlternative:
    changes: list[AlternativeChange] = []
    unresolved: list[str] = []
    for finding in view.policy_findings:
        if finding.severity != "block":
            continue
        if finding.code == "TTL_LIMIT":
            changes.append(
                AlternativeChange(
                    before=f"TTL {view.ttl_days} days", after="TTL 7 days", operator="TTL"
                )
            )
        elif finding.code == "RAW_VOC_FOR_PRODUCT":
            changes.append(
                AlternativeChange(
                    before=finding.field or "raw text",
                    after="issue category",
                    operator="EXTRACT_CATEGORY",
                )
            )
        elif finding.code == "SENSITIVE_FIELD_TRANSFORM" and finding.field in {
            "address",
            "age",
            "customer_name",
            "ticket_id",
            "user_id",
        }:
            target = {"address": "region group", "age": "age band"}.get(finding.field, "removed")
            operator = {"address": "GENERALIZE", "age": "BUCKET"}.get(finding.field, "DROP")
            changes.append(AlternativeChange(before=finding.field, after=target, operator=operator))
        else:
            unresolved.append(finding.code)
    return RecommendedAlternative(
        available=bool(changes) and not unresolved,
        changes=changes,
        unresolved_findings=unresolved,
    )


def is_approval_submission_allowed(view: NeedexResponse) -> bool:
    if view.status not in {"proposed", "blocked"}:
        return False
    if not any(finding.severity == "block" for finding in view.policy_findings):
        return True
    return _alternative_for_view(view).available


def build_approval_review(view: NeedexResponse, owner: UserPublic) -> ApprovalReview:
    blocked = any(finding.severity == "block" for finding in view.policy_findings)
    warnings = any(finding.severity == "warning" for finding in view.policy_findings)
    alternative = _alternative_for_view(view)
    return ApprovalReview(
        request_id=f"req_{view.id.removeprefix('tv_')}",
        view_id=view.id,
        view_name=task_view_name(view),
        risk_level="high" if blocked else "medium" if warnings else "low",
        request_blocked=blocked,
        requested_purpose=view.purpose,
        requester=view.requester.display_name if view.requester else None,
        existing_view=None,
        reasons=[
            ApprovalReason(title=finding.message, detail=finding.action)
            for finding in view.policy_findings
            if finding.severity == "block"
        ],
        policy_findings=view.policy_findings,
        recommended_alternative=alternative,
        assigned_owner=owner.display_name,
        can_approve_as_is=not blocked and view.status == "proposed",
        evidence_state="issued" if view.evidence else "pending",
    )


def build_data_response(view: NeedexResponse) -> DataResponse:
    if view.evidence is None:
        raise ValueError("Evidence Contract가 없는 Task View입니다.")
    if datetime.now(UTC) >= view.evidence.expires_at:
        raise NeedexExpiredError("Task View의 TTL이 만료되어 데이터 접근이 중단되었습니다.")
    return DataResponse(
        view_id=view.id,
        view_name=task_view_name(view),
        data_origin=view.data_origin,
        expires_at=view.evidence.expires_at,
        content_sha256=view.evidence.content_sha256,
        columns=view.plan.preview_columns,
        rows=view.preview_rows,
    )
