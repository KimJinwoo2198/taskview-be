from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Audience = Literal["product", "operations", "support", "executive"]
Status = Literal["proposed", "approved", "rejected", "blocked"]


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PreviewRequest(StrictRequest):
    purpose: str = Field(min_length=10, max_length=1000)
    audience: Audience = "product"
    ttl_days: int = Field(default=7, ge=1, le=30)
    region: Literal["KR", "JP", "VN", "APAC", "GLOBAL"] = "GLOBAL"
    output_mode: Literal["dashboard", "api", "dashboard_api"] = "dashboard_api"


class PurposeSpec(BaseModel):
    objective: str
    decision_to_support: str
    audience: Audience
    requested_fields: list[str]


class TransformPlanItem(BaseModel):
    source: Literal["product", "operations", "voc"]
    input_fields: list[str]
    output_field: str
    transformation: Literal[
        "select", "drop", "mask", "age_band", "region_group", "aggregate", "classify"
    ]
    rationale: str


class ViewPlan(BaseModel):
    purpose_spec: PurposeSpec
    selected_sources: list[Literal["product", "operations", "voc"]]
    transformations: list[TransformPlanItem]
    preview_columns: list[str]
    assumptions: list[str] = []
    needs_owner_approval: bool = True


class PolicyFinding(BaseModel):
    code: str
    severity: Literal["info", "warning", "block"]
    field: str | None = None
    message: str
    action: str


class UtilityReport(BaseModel):
    selected_field_count: int
    removed_field_count: int
    estimated_rows: int
    utility_score: int = Field(ge=0, le=100)


class DecisionRequest(StrictRequest):
    approved: bool
    reason: str | None = Field(default=None, max_length=500)


class RefineRequest(StrictRequest):
    instruction: str = Field(min_length=5, max_length=500)
    ttl_days: int | None = Field(default=None, ge=1, le=30)


class RequesterSummary(BaseModel):
    display_name: str
    email: str


class EvidenceContract(BaseModel):
    view_id: str
    purpose: str
    sources: list[str]
    transformations: list[TransformPlanItem]
    policy_version: str
    approved_by: str
    created_at: datetime
    expires_at: datetime
    row_count: int
    minimum_group_size: int
    content_sha256: str
    requester: str | None = None
    data_owner: str | None = None
    utility_test: str = "Top-k insight preserved"
    privacy_controls: list[str] = Field(default_factory=lambda: ["PII DENY", "group ≥ 20"])
    ttl_export: str = "controlled"
    approval_reason: str | None = None


class NeedexResponse(BaseModel):
    id: str
    status: Status
    purpose: str
    audience: Audience
    ttl_days: int
    region: Literal["KR", "JP", "VN", "APAC", "GLOBAL"] = "GLOBAL"
    output_mode: Literal["dashboard", "api", "dashboard_api"] = "dashboard_api"
    plan: ViewPlan
    policy_findings: list[PolicyFinding]
    utility: UtilityReport
    preview_rows: list[dict[str, str | int]]
    data_origin: Literal["synthetic_demo", "public_live"] = "synthetic_demo"
    created_at: datetime
    revision: int = Field(default=1, ge=1)
    created_by: str | None = None
    requester: RequesterSummary | None = None
    reviewed_by: str | None = None
    review_reason: str | None = None
    evidence: EvidenceContract | None = None


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    ai_url: str
    database: Literal["postgresql"] = "postgresql"
    authentication: Literal["database-session"] = "database-session"
