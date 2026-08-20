from datetime import UTC, datetime
from uuid import uuid4

from .ai_client import request_plan
from .config import Settings
from .materializer import create_evidence, preview_rows
from .policy import REQUIRED_TRANSFORMS, calculate_utility, evaluate_policy
from .schemas import DecisionRequest, NeedexResponse, PreviewRequest, RefineRequest, ViewPlan
from .store import PostgresNeedexStore


class NeedexNotFoundError(Exception):
    pass


class NeedexConflictError(Exception):
    pass


async def _materialize_preview(
    plan: ViewPlan, repository: PostgresNeedexStore
) -> tuple[list[dict[str, str | int]], str]:
    rows = await repository.public_demo_preview(plan)
    if rows:
        return rows, "public_live"
    return preview_rows(plan), "synthetic_demo"


async def create_preview(
    request: PreviewRequest,
    settings: Settings,
    repository: PostgresNeedexStore,
    created_by: str,
    workspace_id: str,
    actor_email: str | None = None,
) -> NeedexResponse:
    plan = await request_plan(request, settings)
    findings = evaluate_policy(request, plan)
    status = "blocked" if any(item.severity == "block" for item in findings) else "proposed"
    rows, data_origin = await _materialize_preview(plan, repository)
    view = NeedexResponse(
        id=f"tv_{uuid4().hex[:12]}",
        status=status,
        purpose=request.purpose,
        audience=request.audience,
        ttl_days=request.ttl_days,
        region=request.region,
        output_mode=request.output_mode,
        plan=plan,
        policy_findings=findings,
        utility=calculate_utility(plan),
        preview_rows=rows,
        data_origin=data_origin,
        created_at=datetime.now(UTC),
        created_by=created_by,
    )
    return await repository.save(view, workspace_id=workspace_id, actor_email=actor_email)


async def decide(
    view_id: str,
    decision: DecisionRequest,
    reviewer: str,
    repository: PostgresNeedexStore,
    workspace_id: str,
) -> NeedexResponse:
    view = await repository.get(view_id, workspace_id=workspace_id)
    if not view:
        raise NeedexNotFoundError(view_id)
    if decision.approved and any(item.severity == "block" for item in view.policy_findings):
        raise NeedexConflictError("차단된 정책 항목이 있어 승인할 수 없습니다.")
    if view.status not in {"proposed", "blocked"}:
        raise NeedexConflictError("이미 검토가 완료된 Task View입니다.")

    previous_status = view.status
    expected_revision = view.revision
    expected_payload, expected_content_hash = repository.view_snapshot(view)
    view.status = "approved" if decision.approved else "rejected"
    view.reviewed_by = reviewer
    view.review_reason = decision.reason
    view.evidence = create_evidence(view, reviewer) if decision.approved else None
    action = "approved" if decision.approved else "rejected"
    if not await repository.save_if_revision(
        view,
        workspace_id=workspace_id,
        expected_revision=expected_revision,
        expected_status=previous_status,
        action=action,
        actor_email=reviewer,
        reason=decision.reason,
        require_submission_match=True,
        expected_payload=expected_payload,
        expected_content_hash=expected_content_hash,
    ):
        raise NeedexConflictError("다른 사용자가 먼저 Task View 상태를 변경했습니다.")
    return view


async def refine(
    view_id: str,
    refine_request: RefineRequest,
    settings: Settings,
    repository: PostgresNeedexStore,
    workspace_id: str,
    actor_email: str | None = None,
) -> NeedexResponse:
    current = await repository.get(view_id, workspace_id=workspace_id)
    if not current:
        raise NeedexNotFoundError(view_id)
    if current.status not in {"proposed", "blocked"}:
        raise NeedexConflictError("검토 중인 Task View만 수정할 수 있습니다.")
    if await repository.get_submission(view_id, workspace_id=workspace_id) is not None:
        raise NeedexConflictError("승인 요청을 제출한 뒤에는 Task View를 수정할 수 없습니다.")
    previous_status = current.status
    expected_revision = current.revision
    expected_payload, expected_content_hash = repository.view_snapshot(current)
    request = PreviewRequest(
        purpose=f"{current.purpose}\n추가 요구: {refine_request.instruction}",
        audience=current.audience,
        ttl_days=refine_request.ttl_days or current.ttl_days,
        region=current.region,
        output_mode=current.output_mode,
    )
    plan = await request_plan(request, settings)
    current.purpose = request.purpose
    current.ttl_days = request.ttl_days
    current.plan = plan
    current.policy_findings = evaluate_policy(request, plan)
    current.utility = calculate_utility(plan)
    current.preview_rows, current.data_origin = await _materialize_preview(plan, repository)
    current.status = (
        "blocked"
        if any(item.severity == "block" for item in current.policy_findings)
        else "proposed"
    )
    current.reviewed_by = None
    current.review_reason = None
    current.evidence = None
    if not await repository.save_if_revision(
        current,
        workspace_id=workspace_id,
        expected_revision=expected_revision,
        expected_status=previous_status,
        action="refined",
        actor_email=actor_email,
        reason=refine_request.instruction,
        metadata={"ttl_days": current.ttl_days},
        forbid_pending_submission=True,
        expected_payload=expected_payload,
        expected_content_hash=expected_content_hash,
    ):
        raise NeedexConflictError("다른 사용자가 먼저 Task View 상태를 변경했습니다.")
    return current


async def approve_recommended_alternative(
    view_id: str,
    *,
    reason: str,
    reviewer: str,
    repository: PostgresNeedexStore,
    workspace_id: str,
) -> NeedexResponse:
    """Apply only deterministic, policy-known repairs and approve in one state transition."""
    current = await repository.get(view_id, workspace_id=workspace_id)
    if not current:
        raise NeedexNotFoundError(view_id)
    if current.status not in {"proposed", "blocked"}:
        raise NeedexConflictError("이미 검토가 완료된 Task View입니다.")

    previous_status = current.status
    expected_revision = current.revision
    expected_payload, expected_content_hash = repository.view_snapshot(current)
    repaired_codes: list[str] = []
    unresolved_codes: list[str] = []
    for finding in current.policy_findings:
        if finding.severity != "block":
            continue
        if finding.code == "TTL_LIMIT":
            current.ttl_days = 7
            repaired_codes.append(finding.code)
            continue
        if finding.code in {"RAW_VOC_FOR_PRODUCT", "SENSITIVE_FIELD_TRANSFORM"} and finding.field:
            expected = REQUIRED_TRANSFORMS.get(finding.field)
            if finding.code == "RAW_VOC_FOR_PRODUCT":
                expected = "classify"
            if expected:
                for item in current.plan.transformations:
                    if finding.field not in item.input_fields:
                        continue
                    item.transformation = expected
                    if expected == "classify":
                        item.output_field = "issue_type"
                    elif expected == "region_group":
                        item.output_field = "region"
                    elif expected == "age_band":
                        item.output_field = "age_band"
                repaired_codes.append(finding.code)
                continue
        unresolved_codes.append(finding.code)

    if unresolved_codes:
        raise NeedexConflictError(
            "자동으로 안전하게 보완할 수 없는 정책 항목이 있습니다: "
            + ", ".join(sorted(set(unresolved_codes)))
        )
    if not repaired_codes:
        raise NeedexConflictError("적용할 권장 대안이 없습니다. 일반 승인 결정을 사용하세요.")

    request = PreviewRequest(
        purpose=current.purpose,
        audience=current.audience,
        ttl_days=current.ttl_days,
    )
    current.policy_findings = evaluate_policy(request, current.plan)
    if any(item.severity == "block" for item in current.policy_findings):
        raise NeedexConflictError("권장 대안을 적용한 뒤에도 차단 정책이 남아 있습니다.")

    current.utility = calculate_utility(current.plan)
    current.preview_rows, current.data_origin = await _materialize_preview(current.plan, repository)
    current.status = "approved"
    current.reviewed_by = reviewer
    current.review_reason = reason
    current.evidence = create_evidence(current, reviewer)
    if not await repository.save_if_revision(
        current,
        workspace_id=workspace_id,
        expected_revision=expected_revision,
        expected_status=previous_status,
        action="approved_alternative",
        actor_email=reviewer,
        reason=reason,
        metadata={"repaired_codes": ",".join(sorted(set(repaired_codes)))},
        require_submission_match=True,
        expected_payload=expected_payload,
        expected_content_hash=expected_content_hash,
    ):
        raise NeedexConflictError("다른 사용자가 먼저 Task View 상태를 변경했습니다.")
    return current
