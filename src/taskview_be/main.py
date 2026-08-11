from contextlib import asynccontextmanager

import asyncpg
import httpx
from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .auth import (
    AccountLockedError,
    CurrentUser,
    DuplicateEmailError,
    InvalidCredentialsError,
    OwnerUser,
    SessionToken,
    can_access_view,
    log_in,
    revoke_session,
    rotate_session,
    sign_up,
)
from .auth_schemas import AuthSessionResponse, LoginRequest, SignUpRequest, UserPublic
from .config import get_settings
from .schemas import (
    DecisionRequest,
    EvidenceContract,
    HealthResponse,
    PreviewRequest,
    RefineRequest,
    TaskViewResponse,
)
from .service import (
    TaskViewConflictError,
    TaskViewNotFoundError,
    create_preview,
    decide,
    refine,
)
from .store import store


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await store.start()
    try:
        yield
    finally:
        await store.stop()


app = FastAPI(title="TaskView BE", version="0.3.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(asyncpg.PostgresError)
async def postgres_error_handler(_request: Request, _exc: asyncpg.PostgresError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": "데이터베이스를 사용할 수 없습니다."})


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    await store.ping()
    return HealthResponse(ai_url=get_settings().taskview_ai_url)


@app.post(
    "/v1/auth/signup",
    response_model=AuthSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def signup(request: SignUpRequest) -> AuthSessionResponse:
    try:
        return await sign_up(request, get_settings(), store)
    except DuplicateEmailError as exc:
        raise HTTPException(status_code=409, detail="이미 가입된 이메일입니다.") from exc


@app.post("/v1/auth/login", response_model=AuthSessionResponse)
async def login(request: LoginRequest) -> AuthSessionResponse:
    try:
        return await log_in(request, get_settings(), store)
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다.") from exc
    except AccountLockedError as exc:
        raise HTTPException(
            status_code=429,
            detail="로그인 시도가 너무 많습니다. 잠시 후 다시 시도하세요.",
        ) from exc


@app.get("/v1/auth/me", response_model=UserPublic)
async def me(user: CurrentUser) -> UserPublic:
    return user


@app.post("/v1/auth/session/refresh", response_model=AuthSessionResponse)
async def refresh_session(token: SessionToken, user: CurrentUser) -> AuthSessionResponse:
    return await rotate_session(token, user, get_settings(), store)


@app.post("/v1/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(token: SessionToken) -> Response:
    await revoke_session(token, store)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def get_authorized_view(view_id: str, user: UserPublic) -> TaskViewResponse:
    view = await store.get(view_id)
    if not view or not can_access_view(user, view.created_by):
        raise HTTPException(status_code=404, detail="Task View를 찾을 수 없습니다.")
    return view


@app.post("/v1/taskviews/preview", response_model=TaskViewResponse)
async def preview(request: PreviewRequest, user: CurrentUser) -> TaskViewResponse:
    try:
        return await create_preview(request, get_settings(), store, user.id)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="AI 계획 서비스에 연결하지 못했습니다.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="AI 계획 결과가 유효하지 않습니다.") from exc


@app.get("/v1/taskviews", response_model=list[TaskViewResponse])
async def list_views(user: CurrentUser) -> list[TaskViewResponse]:
    created_by = user.id if user.role == "requester" else None
    return await store.list_views(created_by=created_by)


@app.get("/v1/taskviews/{view_id}", response_model=TaskViewResponse)
async def get_view(view_id: str, user: CurrentUser) -> TaskViewResponse:
    return await get_authorized_view(view_id, user)


@app.post("/v1/taskviews/{view_id}/decision", response_model=TaskViewResponse)
async def make_decision(
    view_id: str, request: DecisionRequest, user: OwnerUser
) -> TaskViewResponse:
    try:
        return await decide(view_id, request, str(user.email), store)
    except TaskViewNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Task View를 찾을 수 없습니다.") from exc
    except TaskViewConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/v1/taskviews/{view_id}/refine", response_model=TaskViewResponse)
async def refine_view(
    view_id: str, request: RefineRequest, user: CurrentUser
) -> TaskViewResponse:
    await get_authorized_view(view_id, user)
    try:
        return await refine(view_id, request, get_settings(), store)
    except TaskViewNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Task View를 찾을 수 없습니다.") from exc
    except TaskViewConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="AI 계획 서비스에 연결하지 못했습니다.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="AI 계획 결과가 유효하지 않습니다.") from exc


@app.get("/v1/taskviews/{view_id}/evidence", response_model=EvidenceContract)
async def get_evidence(view_id: str, user: CurrentUser) -> EvidenceContract:
    view = await get_authorized_view(view_id, user)
    if not view.evidence:
        raise HTTPException(status_code=409, detail="승인 완료 후 Evidence Contract가 생성됩니다.")
    return view.evidence
