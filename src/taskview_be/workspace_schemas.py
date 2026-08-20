from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from .auth_schemas import Role

Region = Literal["KR-11", "JP-13", "VN-SG", "GLOBAL"]
OutputMode = Literal["dashboard", "api", "dashboard_api"]


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkspaceCreate(StrictRequest):
    name: str = Field(min_length=2, max_length=100)
    region: Region = "KR-11"
    default_ttl_days: int = Field(default=7, ge=1, le=30)
    member_role: Role = "requester"


class WorkspacePatch(StrictRequest):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    region: Region | None = None
    default_ttl_days: int | None = Field(default=None, ge=1, le=30)
    default_output_mode: OutputMode | None = None


class NotificationSettings(StrictRequest):
    approval_requested: bool = True
    view_approved: bool = True
    ttl_expiring: bool = True
    audit_events: bool = False


class WorkspacePublic(BaseModel):
    id: str
    name: str
    region: Region
    default_ttl_days: int
    default_output_mode: OutputMode
    member_role: Role
    onboarding_complete: bool
    notifications: NotificationSettings
    created_at: datetime


class InvitationInput(StrictRequest):
    email: EmailStr
    role: Role


class BatchInvitationRequest(StrictRequest):
    invitations: list[InvitationInput] = Field(min_length=1, max_length=25)


class InvitationResult(BaseModel):
    email: EmailStr
    role: Role
    status: Literal["invited", "already_member", "duplicate"]
    development_token: str | None = None


class BatchInvitationResponse(BaseModel):
    workspace_id: str
    results: list[InvitationResult]
    invited_count: int


class OnboardingCompleteRequest(StrictRequest):
    skipped_invitations: bool = False


class WorkspaceInvitationAcceptRequest(StrictRequest):
    token: str = Field(min_length=32, max_length=256)


class WorkspaceMember(BaseModel):
    id: str
    display_name: str
    email: EmailStr
    role: Role
    region: str
    status: Literal["active"] = "active"
    joined_at: datetime


class AccountPublic(BaseModel):
    id: str
    display_name: str
    email: EmailStr
    email_verified: bool
    auth_provider: str
    role: Role
    onboarding_status: str
    created_at: datetime


class AccountPatch(StrictRequest):
    display_name: str = Field(min_length=2, max_length=80)
