import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

Role = Literal["requester", "data_owner", "admin"]


class SignUpRequest(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=2, max_length=80)
    password: str = Field(min_length=12, max_length=128)

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str) -> str:
        return " ".join(value.split())

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, value: str) -> str:
        checks = [
            bool(re.search(r"[A-Za-z]", value)),
            bool(re.search(r"\d", value)),
            bool(re.search(r"[^A-Za-z0-9]", value)),
        ]
        if not all(checks):
            raise ValueError("비밀번호에는 영문, 숫자, 특수문자가 각각 하나 이상 필요합니다.")
        return value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserPublic(BaseModel):
    id: str
    email: EmailStr
    display_name: str
    role: Role
    created_at: datetime


class AuthSessionResponse(BaseModel):
    user: UserPublic
    session_token: str
    expires_at: datetime
