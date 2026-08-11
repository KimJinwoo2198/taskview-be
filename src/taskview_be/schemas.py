from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Audience = Literal["product", "operations", "support", "executive"]
Status = Literal["proposed", "approved", "rejected", "blocked"]


class PreviewRequest(BaseModel):
    purpose: str = Field(min_length=10, max_length=1000)
    audience: Audience = "product"
    ttl_days: int = Field(default=7, ge=1, le=30)


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


class DecisionRequest(BaseModel):
    approved: bool
    reason: str | None = Field(default=None, max_length=500)


class RefineRequest(BaseModel):
    instruction: str = Field(min_length=5, max_length=500)


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


class TaskViewResponse(BaseModel):
    id: str
    status: Status
    purpose: str
    audience: Audience
    ttl_days: int
    plan: ViewPlan
    policy_findings: list[PolicyFinding]
    utility: UtilityReport
    preview_rows: list[dict[str, str | int]]
    created_at: datetime
    created_by: str | None = None
    reviewed_by: str | None = None
    review_reason: str | None = None
    evidence: EvidenceContract | None = None


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    ai_url: str
    database: Literal["postgresql"] = "postgresql"
    authentication: Literal["database-session"] = "database-session"
