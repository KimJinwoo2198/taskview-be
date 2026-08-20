from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from .experience_schemas import DataOrigin, RegionCode, SourceKey


class DiscoveryField(BaseModel):
    name: str
    data_type: str
    decision: Literal["required", "candidate", "generalize", "bucket", "extract", "drop"]
    task_field: str | None = None
    rationale: str


class DiscoverySource(BaseModel):
    source_id: str
    source_key: SourceKey
    source_name: str
    country_flag: str
    dataset: str
    reason: str
    fields: list[DiscoveryField]


class DiscoveryResponse(BaseModel):
    view_id: str
    purpose: str
    requester: str
    region: RegionCode
    ttl_days: int
    sources: list[DiscoverySource]
    reviewed_field_count: int
    candidate_field_count: int
    completion_percent: int = Field(ge=0, le=100)


class ApprovalSubmission(BaseModel):
    request_id: str
    view_id: str
    state: Literal["pending", "approved", "rejected", "blocked"]
    queue_position: int
    queue_total: int
    assigned_owners: list[str]
    submitted_at: datetime
    idempotent_replay: bool = False


class ApprovalTimelineItem(BaseModel):
    organization: str
    country_flag: str
    status: Literal["complete", "review_required", "waiting", "issued", "rejected"]
    title: str
    detail: str
    affected_fields: list[str] = []


class ApprovalStatusResponse(BaseModel):
    view_id: str
    request_id: str | None
    submitted: bool
    state: Literal["not_submitted", "pending", "approved", "rejected", "blocked"]
    queue_position: int | None
    queue_total: int
    submitted_at: datetime | None
    estimated_response_minutes: int | None
    evidence_ready: bool
    timeline: list[ApprovalTimelineItem]


class AnalyticsBucket(BaseModel):
    key: str
    count: int = Field(ge=0)
    share: float = Field(ge=0, le=1)


class NeedexAnalytics(BaseModel):
    view_id: str
    view_name: str
    data_origin: DataOrigin
    period_days: int
    region: str
    os: str
    cohort: str
    record_count: int
    direct_identifier_count: int = 0
    utility_state: Literal["meets_standard", "review_required"]
    remaining_ttl_days: int
    grouped_insights: dict[str, list[AnalyticsBucket]]
    allowed_questions: list[str]
    generated_at: datetime
