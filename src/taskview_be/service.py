from datetime import UTC, datetime
from uuid import uuid4

from .ai_client import request_plan
from .config import Settings
from .materializer import create_evidence, preview_rows
from .policy import calculate_utility, evaluate_policy
from .schemas import DecisionRequest, PreviewRequest, RefineRequest, TaskViewResponse
from .store import InMemoryTaskViewStore


class TaskViewNotFoundError(Exception):
    pass


class TaskViewConflictError(Exception):
    pass


async def create_preview(
    request: PreviewRequest, settings: Settings, repository: InMemoryTaskViewStore
) -> TaskViewResponse:
    plan = await request_plan(request, settings)
    findings = evaluate_policy(request, plan)
    status = "blocked" if any(item.severity == "block" for item in findings) else "proposed"
    view = TaskViewResponse(
        id=f"tv_{uuid4().hex[:12]}",
        status=status,
        purpose=request.purpose,
        audience=request.audience,
        ttl_days=request.ttl_days,
        plan=plan,
        policy_findings=findings,
        utility=calculate_utility(plan),
        preview_rows=preview_rows(),
        created_at=datetime.now(UTC),
    )
    return repository.save(view)


def decide(
    view_id: str, decision: DecisionRequest, repository: InMemoryTaskViewStore
) -> TaskViewResponse:
    view = repository.get(view_id)
    if not view:
        raise TaskViewNotFoundError(view_id)
    if decision.approved and any(item.severity == "block" for item in view.policy_findings):
        raise TaskViewConflictError("차단된 정책 항목이 있어 승인할 수 없습니다.")

    view.status = "approved" if decision.approved else "rejected"
    view.reviewed_by = decision.reviewer
    view.review_reason = decision.reason
    view.evidence = create_evidence(view, decision.reviewer) if decision.approved else None
    return repository.save(view)


async def refine(
    view_id: str,
    refine_request: RefineRequest,
    settings: Settings,
    repository: InMemoryTaskViewStore,
) -> TaskViewResponse:
    current = repository.get(view_id)
    if not current:
        raise TaskViewNotFoundError(view_id)
    request = PreviewRequest(
        purpose=f"{current.purpose}\n추가 요구: {refine_request.instruction}",
        audience=current.audience,
        ttl_days=current.ttl_days,
    )
    plan = await request_plan(request, settings)
    current.purpose = request.purpose
    current.plan = plan
    current.policy_findings = evaluate_policy(request, plan)
    current.utility = calculate_utility(plan)
    current.status = (
        "blocked" if any(item.severity == "block" for item in current.policy_findings) else "proposed"
    )
    current.reviewed_by = None
    current.review_reason = None
    current.evidence = None
    return repository.save(current)

