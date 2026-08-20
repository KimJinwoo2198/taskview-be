from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UiDataSourceSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    flag: str
    name: str
    organization: str
    region: str
    pii: Literal["LOW", "MEDIUM", "HIGH"]
    engine: str
    schema_preview: str = Field(alias="schema")
    views: int
    lastSync: str
    sourceType: Literal["public-live", "workspace"] = "public-live"
    rowCount: int = 0
    officialUrl: str | None = None


class UiDataSourceStats(BaseModel):
    connected: int
    builtIn: int
    workspaceConnected: int
    fields: int
    pii: int
    activeViews: int


class UiDataSourcesPayload(BaseModel):
    sources: list[UiDataSourceSummary]
    stats: UiDataSourceStats


class UiCatalogField(BaseModel):
    field: str
    meaning: str
    sensitivity: Literal["INDIRECT", "HIGH", "MEDIUM", "LOW"]
    transform: str


class UiDataSourceDetail(BaseModel):
    name: str
    flag: str
    subtitle: str
    owner: str
    region: str
    fields: list[UiCatalogField]
    sourceType: Literal["public-live", "workspace"] = "public-live"


class DataSourceConnectionRequest(StrictRequest):
    engine: Literal["PostgreSQL", "MySQL", "BigQuery", "Snowflake"]
    name: str = Field(min_length=2, max_length=100)
    organization: str = Field(min_length=2, max_length=100)
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    database: str = Field(min_length=1, max_length=128)
    username: str = Field(min_length=1, max_length=128)
    password: SecretStr = Field(default=SecretStr(""), max_length=256)
    tls: bool | None = None


class DataSourceConnectionTest(BaseModel):
    success: bool
    read_only: bool
    tls: bool
    latency_ms: int
    message: str


class DataSourceScanResponse(BaseModel):
    job_id: str
    state: Literal["complete"] = "complete"
    table_count: int
    field_count: int
    sensitive_field_count: int
    raw_rows_returned: int = 0


class DataSourceScanCompleteRequest(StrictRequest):
    job_id: UUID
    owner: str = Field(min_length=2, max_length=100)
    region: str = Field(min_length=2, max_length=100)
    policy: str = Field(min_length=2, max_length=100)


class DataSourceScanCompleteResponse(BaseModel):
    source_id: str
    status: Literal["connected"] = "connected"


class UiApprovalRequest(BaseModel):
    id: str
    risk: Literal["HIGH RISK", "REVIEW", "APPROVED"]
    title: str
    requester: str
    owner: str
    transform: str
    finding: str
    state: Literal["pending", "approved", "rejected"]


class UiApprovalInbox(BaseModel):
    pending: int
    highRisk: int
    approved: int
    items: list[UiApprovalRequest]


class UiAuditEvent(BaseModel):
    time: str
    event: str
    view: str
    purpose: str
    actor: str
    result: str
    tone: Literal["success", "safe", "danger", "primary"]
    evidence: str | None = None
    evidenceId: str | None = None
    evidenceHash: str | None = None


class UiEvidencePayload(BaseModel):
    id: str
    view: str
    title: str
    created: str
    hash: str


class UiWorkspaceNotifications(BaseModel):
    approval: bool
    approved: bool
    expiry: bool
    audit: bool


class UiWorkspaceSettings(BaseModel):
    name: str
    region: str
    ttl: str
    output: str
    notifications: UiWorkspaceNotifications


class UiPolicySettings(StrictRequest):
    newPurpose: bool
    highRisk: bool
    lowRisk: bool
    refinement: bool
    cumulative: bool
    block: bool


class UiTeamMember(BaseModel):
    id: str
    initial: str
    name: str
    email: EmailStr
    role: str
    region: str
    status: Literal["ACTIVE"] = "ACTIVE"


class UiTeamInvitation(StrictRequest):
    email: EmailStr
    role: Literal["Product / UX", "Data Owner", "Security / Admin"]


class UiWebhook(BaseModel):
    event: str
    url: str


class UiIntegrationSettings(BaseModel):
    keyMasked: str
    lastUsed: str
    webhooks: list[UiWebhook]


class UiAccountSession(BaseModel):
    id: str
    name: str
    device: str
    when: str
    current: bool


class UiAccountPayload(BaseModel):
    name: str
    email: EmailStr
    verified: bool
    passwordChanged: str
    sessions: list[UiAccountSession]


class UiAccountPatch(StrictRequest):
    name: str = Field(min_length=2, max_length=80)
    email: EmailStr | None = None


ApiKeyScope = Literal[
    "taskviews:artifacts:read",
    "taskviews:data:read",
    "taskviews:analytics:read",
]


class ApiKeyCreateRequest(StrictRequest):
    name: str = Field(default="Production Key", min_length=2, max_length=80)
    scopes: list[ApiKeyScope] = Field(
        default_factory=lambda: [
            "taskviews:artifacts:read",
            "taskviews:data:read",
            "taskviews:analytics:read",
        ],
        min_length=1,
        max_length=3,
    )
    expiresInDays: int = Field(default=90, ge=1, le=365)


class ApiKeySummary(BaseModel):
    id: str
    name: str
    keyPrefix: str
    scopes: list[ApiKeyScope]
    createdAt: datetime
    expiresAt: datetime | None
    lastUsedAt: datetime | None
    revokedAt: datetime | None
    revokedBy: str | None
    status: Literal["active", "expired", "revoked"]


class ApiKeyCreated(ApiKeySummary):
    secret: str
