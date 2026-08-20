from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .auth_schemas import UserPublic
from .schemas import EvidenceContract, PolicyFinding, Status

SourceKey = Literal["product", "operations", "voc"]
RegionCode = Literal["KR", "JP", "VN", "APAC", "GLOBAL"]
OutputMode = Literal["dashboard", "api", "dashboard_api"]
DataOrigin = Literal["synthetic_demo", "public_live"]


class DataField(BaseModel):
    name: str
    data_type: Literal["string", "integer", "date", "datetime", "text"]
    privacy_class: Literal["non_sensitive", "quasi_identifier", "direct_identifier", "sensitive"]
    allowed_transforms: list[str]


class DataSource(BaseModel):
    id: str
    key: SourceKey
    name: str
    short_name: str
    country_code: Literal["KR", "JP", "VN", "US"]
    country_flag: str
    region: str
    owner: str
    description: str
    datasets: list[str]
    fields: list[DataField]
    status: Literal["connected"] = "connected"
    source_type: Literal["public_live", "workspace"] = "public_live"
    provider: str | None = None
    official_url: str | None = None
    license_url: str | None = None
    last_synced_at: datetime | None = None
    row_count: int = 0


class SourceMatch(BaseModel):
    source: DataSource
    matched_fields: list[str]
    reason: str


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PurposeInterpretationRequest(StrictRequest):
    purpose: str = Field(min_length=10, max_length=1000)
    audience: Literal["product", "operations", "support", "executive"] = "product"
    region: RegionCode = "GLOBAL"
    ttl_days: int = Field(default=7, ge=1, le=30)
    output_mode: OutputMode = "dashboard_api"


class PurposeInterpretation(BaseModel):
    task: str
    requester: str
    target: str
    region: RegionCode
    success: str
    ttl_days: int
    output_mode: OutputMode
    matched_sources: list[SourceMatch]
    interpreted_at: datetime
    summary: str
    subject: str
    comparison_dimensions: list[str] = Field(min_length=1, max_length=4)
    desired_outcome: str
    region_label: str
    department: Literal["product", "operations", "support", "executive"]
    confidence: float = Field(ge=0, le=1)
    needs_clarification: bool = False
    clarifying_question: str | None = None


class BusinessIntent(BaseModel):
    summary: str
    subject: str
    comparison_dimensions: list[str] = Field(min_length=1, max_length=4)
    desired_outcome: str
    region_label: str
    department: Literal["product", "operations", "support", "executive"]
    selected_source: SourceKey
    confidence: float = Field(ge=0, le=1)
    needs_clarification: bool = False
    clarifying_question: str | None = None


class DashboardCounters(BaseModel):
    active_task_views: int
    created_in_period: int
    pending_approvals: int
    blocked_requests: int
    connected_sources: int


class NeedexCard(BaseModel):
    id: str
    name: str
    purpose: str
    ttl_days: int
    status: Status
    requester_name: str | None = None
    requester_region: str | None = None
    created_at: datetime


class PrivacyFirewallSummary(BaseModel):
    default_action: Literal["deny"] = "deny"
    max_ttl_days: int = 7
    denied_data: list[str]
    minimum_group_size: int = 20


class DashboardResponse(BaseModel):
    workspace_name: str
    workspace_region: str
    member: UserPublic
    period_days: int
    counters: DashboardCounters
    recent_task_views: list[NeedexCard]
    data_sources: list[DataSource]
    privacy_firewall: PrivacyFirewallSummary
    generated_at: datetime


class SemanticTransform(BaseModel):
    source_key: SourceKey
    source_name: str
    raw_fields: list[str]
    operator: Literal[
        "SELECT", "DROP", "MASK", "GENERALIZE", "BUCKET", "AGGREGATE", "EXTRACT_CATEGORY"
    ]
    task_field: str | None
    rationale: str


class UtilityCandidate(BaseModel):
    mode: Literal["raw", "static_masking", "taskview"]
    score: int = Field(ge=0, le=100)
    verdict: str


class FirewallCheck(BaseModel):
    code: str
    label: str
    result: Literal["PASS", "DENY", "GENERALIZE", "WARN"]
    detail: str


class CompilationResponse(BaseModel):
    view_id: str
    view_name: str
    stage: Literal["validation_complete", "blocked"]
    source_match_count: int
    transforms: list[SemanticTransform]
    utility_candidates: list[UtilityCandidate]
    firewall_checks: list[FirewallCheck]
    excluded_fields: list[str]
    can_submit_for_approval: bool
    policy_version: str


class SchemaField(BaseModel):
    name: str
    data_type: Literal["string", "integer", "date", "datetime"]
    source: str
    transform: str


class SourceLineage(BaseModel):
    source_id: str
    source_name: str
    country_flag: str
    fields: list[str]
    transforms: list[str]
    usage: Literal["used"] = "used"


class ApiArtifact(BaseModel):
    method: Literal["GET"] = "GET"
    path: str
    authentication: Literal["Bearer session token"] = "Bearer session token"
    response_schema: list[SchemaField]


class DashboardArtifact(BaseModel):
    dimensions: list[str]
    measures: list[str]
    default_visualization: Literal["table", "bar", "line"]


class NeedexArtifacts(BaseModel):
    view_id: str
    view_name: str
    schema_fields: list[SchemaField]
    removed_fields: list[str]
    sql: str
    api: ApiArtifact
    dashboard: DashboardArtifact
    source_lineage: list[SourceLineage]
    evidence: EvidenceContract | None


class ApprovalReason(BaseModel):
    title: str
    detail: str


class AlternativeChange(BaseModel):
    before: str
    after: str
    operator: Literal["DROP", "GENERALIZE", "BUCKET", "EXTRACT_CATEGORY", "TTL"]


class RecommendedAlternative(BaseModel):
    available: bool
    changes: list[AlternativeChange]
    unresolved_findings: list[str]


class ApprovalReview(BaseModel):
    request_id: str
    view_id: str
    view_name: str
    risk_level: Literal["low", "medium", "high"]
    request_blocked: bool
    requested_purpose: str
    requester: str | None
    existing_view: str | None
    reasons: list[ApprovalReason]
    policy_findings: list[PolicyFinding]
    recommended_alternative: RecommendedAlternative
    assigned_owner: str
    can_approve_as_is: bool
    evidence_state: Literal["pending", "issued"]


class ApprovalDecisionRequest(StrictRequest):
    decision: Literal["approve", "approve_recommended_alternative", "reject"]
    reason: str = Field(min_length=2, max_length=500)


class DataResponse(BaseModel):
    view_id: str
    view_name: str
    data_origin: DataOrigin
    expires_at: datetime
    content_sha256: str
    columns: list[str]
    rows: list[dict[str, str | int]]


class AuditEvent(BaseModel):
    id: int
    view_id: str
    action: Literal[
        "created",
        "refined",
        "submitted",
        "approved",
        "approved_alternative",
        "rejected",
        "downloaded",
    ]
    actor_email: str | None
    from_status: Status | None
    to_status: Status
    reason: str | None
    metadata: dict[str, str | int | bool]
    created_at: datetime
