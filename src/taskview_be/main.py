from contextlib import asynccontextmanager

import asyncpg
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

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


app = FastAPI(title="TaskView BE", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    await store.ping()
    return HealthResponse(ai_url=get_settings().taskview_ai_url)


@app.post("/v1/taskviews/preview", response_model=TaskViewResponse)
async def preview(request: PreviewRequest) -> TaskViewResponse:
    try:
        return await create_preview(request, get_settings(), store)
    except (asyncpg.PostgresError, httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="AI 계획 서비스에 연결하지 못했습니다.") from exc


@app.get("/v1/taskviews/{view_id}", response_model=TaskViewResponse)
async def get_view(view_id: str) -> TaskViewResponse:
    view = await store.get(view_id)
    if not view:
        raise HTTPException(status_code=404, detail="Task View를 찾을 수 없습니다.")
    return view


@app.post("/v1/taskviews/{view_id}/decision", response_model=TaskViewResponse)
async def make_decision(view_id: str, request: DecisionRequest) -> TaskViewResponse:
    try:
        return await decide(view_id, request, store)
    except TaskViewNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Task View를 찾을 수 없습니다.") from exc
    except TaskViewConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/v1/taskviews/{view_id}/refine", response_model=TaskViewResponse)
async def refine_view(view_id: str, request: RefineRequest) -> TaskViewResponse:
    try:
        return await refine(view_id, request, get_settings(), store)
    except TaskViewNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Task View를 찾을 수 없습니다.") from exc
    except (asyncpg.PostgresError, httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="AI 계획 서비스에 연결하지 못했습니다.") from exc


@app.get("/v1/taskviews/{view_id}/evidence", response_model=EvidenceContract)
async def get_evidence(view_id: str) -> EvidenceContract:
    view = await store.get(view_id)
    if not view:
        raise HTTPException(status_code=404, detail="Task View를 찾을 수 없습니다.")
    if not view.evidence:
        raise HTTPException(status_code=409, detail="승인 완료 후 Evidence Contract가 생성됩니다.")
    return view.evidence
