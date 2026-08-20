from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

Role = Literal["requester", "data_owner", "admin"]


class SignUpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    display_name: str = Field(min_length=2, max_length=80)
    password: str = Field(min_length=8, max_length=128)
    terms_accepted: bool = True
    marketing_opt_in: bool = False

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str) -> str:
        return " ".join(value.split())

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, value: str) -> str:
        if not any(character.isalpha() for character in value) or not any(
            character.isdigit() for character in value
        ):
            raise ValueError("비밀번호에는 영문과 숫자가 각각 하나 이상 필요합니다.")
        return value

    @model_validator(mode="after")
    def require_terms(self) -> "SignUpRequest":
        if not self.terms_accepted:
            raise ValueError("이용약관과 개인정보 처리방침에 동의해야 합니다.")
        return self


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserPublic(BaseModel):
    id: str
    email: EmailStr
    display_name: str
    role: Role
    created_at: datetime
    email_verified: bool = True
    onboarding_status: Literal[
        "email_verification", "workspace_setup", "team_invite", "complete"
    ] = "complete"
    auth_provider: Literal["password", "google"] = "password"


class AuthSessionResponse(BaseModel):
    user: UserPublic
    session_token: str
    expires_at: datetime
    next_path: str = "/dashboard"
    verification_token: str | None = None


class TokenDeliveryResponse(BaseModel):
    accepted: bool = True
    expires_at: datetime | None = None
    retry_after_seconds: int = 60
    development_token: str | None = None


class OAuthStartResponse(BaseModel):
    authorization_url: str


class EmailVerificationConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=32, max_length=256)


class EmailVerificationStatus(BaseModel):
    email: EmailStr
    verified: bool
    onboarding_status: str


class PasswordResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr


class PasswordResetConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=32, max_length=256)
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def validate_password_strength(cls, value: str) -> str:
        if not any(character.isalpha() for character in value) or not any(
            character.isdigit() for character in value
        ):
            raise ValueError("비밀번호에는 영문과 숫자가 각각 하나 이상 필요합니다.")
        return value
