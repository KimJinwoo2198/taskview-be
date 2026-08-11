import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated

import asyncpg
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash
from pwdlib.exceptions import PwdlibError

from .auth_schemas import AuthSessionResponse, LoginRequest, Role, SignUpRequest, UserPublic
from .config import Settings, get_settings
from .store import PostgresTaskViewStore, store

password_hash = PasswordHash.recommended()
dummy_password_hash = password_hash.hash("TaskView-not-a-real-account-2026!")
bearer_scheme = HTTPBearer(auto_error=False)


class DuplicateEmailError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


class AccountLockedError(Exception):
    pass


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def verify_password(plain_password: str, encoded_password: str) -> bool:
    try:
        return password_hash.verify(plain_password, encoded_password)
    except PwdlibError:
        return False


async def issue_session(
    user: UserPublic, settings: Settings, repository: PostgresTaskViewStore
) -> AuthSessionResponse:
    token = secrets.token_urlsafe(48)
    expires_at = datetime.now(UTC) + timedelta(days=settings.taskview_session_days)
    persisted_expiry = await repository.create_session(
        user_id=user.id,
        token_hash=hash_session_token(token),
        expires_at=expires_at,
    )
    return AuthSessionResponse(user=user, session_token=token, expires_at=persisted_expiry)


async def sign_up(
    request: SignUpRequest, settings: Settings, repository: PostgresTaskViewStore
) -> AuthSessionResponse:
    try:
        user = await repository.create_user(
            email=str(request.email).lower(),
            display_name=request.display_name,
            password_hash=password_hash.hash(request.password),
            role="requester",
        )
    except asyncpg.UniqueViolationError as exc:
        raise DuplicateEmailError from exc
    return await issue_session(user, settings, repository)


async def log_in(
    request: LoginRequest, settings: Settings, repository: PostgresTaskViewStore
) -> AuthSessionResponse:
    record = await repository.get_user_for_auth(str(request.email))
    encoded_password = record.password_hash if record else dummy_password_hash
    valid_password = verify_password(request.password, encoded_password)

    if record and record.locked_until and record.locked_until > datetime.now(UTC):
        raise AccountLockedError
    if not record or not record.is_active or not valid_password:
        if record:
            await repository.record_login_failure(
                record.user.id,
                max_failures=settings.taskview_login_max_failures,
                lock_minutes=settings.taskview_login_lock_minutes,
            )
        raise InvalidCredentialsError

    await repository.record_login_success(record.user.id)
    return await issue_session(record.user, settings, repository)


async def rotate_session(
    token: str, user: UserPublic, settings: Settings, repository: PostgresTaskViewStore
) -> AuthSessionResponse:
    await repository.revoke_session(hash_session_token(token))
    return await issue_session(user, settings, repository)


async def authenticate_session(token: str, repository: PostgresTaskViewStore) -> UserPublic | None:
    if len(token) < 40:
        return None
    return await repository.get_user_by_session(hash_session_token(token))


async def revoke_session(token: str, repository: PostgresTaskViewStore) -> None:
    await repository.revoke_session(hash_session_token(token))


async def get_session_credentials(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    return credentials.credentials


async def get_current_user(
    token: Annotated[str, Depends(get_session_credentials)],
) -> UserPublic:
    user = await authenticate_session(token, store)
    if user is None:
        raise HTTPException(status_code=401, detail="세션이 만료되었거나 유효하지 않습니다.")
    return user


def require_roles(*allowed_roles: Role):
    async def role_dependency(
        user: Annotated[UserPublic, Depends(get_current_user)],
    ) -> UserPublic:
        if user.role not in allowed_roles:
            raise HTTPException(status_code=403, detail="이 작업을 수행할 권한이 없습니다.")
        return user

    return role_dependency


CurrentUser = Annotated[UserPublic, Depends(get_current_user)]
SessionToken = Annotated[str, Depends(get_session_credentials)]
OwnerUser = Annotated[UserPublic, Depends(require_roles("data_owner", "admin"))]


def can_access_view(user: UserPublic, created_by: str | None) -> bool:
    return user.role in {"data_owner", "admin"} or created_by == user.id


def current_settings() -> Settings:
    return get_settings()
