import hashlib
import json
from datetime import UTC, datetime, timedelta

from .schemas import EvidenceContract, NeedexResponse, ViewPlan

SAMPLE_ROWS = [
    {
        "week": "2026-W31",
        "region": "서울",
        "age_band": "20대",
        "issue_type": "검색 정확도",
        "feature": "검색",
        "usage_count": 1280,
        "status": "완료",
        "avg_resolution_hours": 6,
        "case_count": 64,
        "os_family": "iOS",
        "os_version": "18.x",
        "signup_step": "email verification",
        "error_category": "verification timeout",
        "complaint_theme": "인증 코드 지연",
        "region_group": "Kanto",
        "channel": "Phone",
        "agency": "DEP",
        "complaint_type": "Water System",
        "manufacturer": "Example Motors",
        "model_year": 2024,
        "component": "ELECTRICAL SYSTEM",
        "crash_count": 1,
        "fire_count": 0,
    },
    {
        "week": "2026-W31",
        "region": "경기",
        "age_band": "30대",
        "issue_type": "알림 지연",
        "feature": "알림",
        "usage_count": 930,
        "status": "처리 중",
        "avg_resolution_hours": 11,
        "case_count": 41,
        "os_family": "iOS",
        "os_version": "17.x",
        "signup_step": "profile setup",
        "error_category": "validation error",
        "complaint_theme": "입력 오류",
        "region_group": "Kansai",
        "channel": "Web",
        "agency": "DOT",
        "complaint_type": "Street Condition",
        "manufacturer": "Example Motors",
        "model_year": 2023,
        "component": "SERVICE BRAKES",
        "crash_count": 0,
        "fire_count": 0,
    },
    {
        "week": "2026-W32",
        "region": "서울",
        "age_band": "40대",
        "issue_type": "검색 정확도",
        "feature": "검색",
        "usage_count": 1140,
        "status": "완료",
        "avg_resolution_hours": 5,
        "case_count": 57,
        "os_family": "iOS",
        "os_version": "18.x",
        "signup_step": "terms consent",
        "error_category": "network error",
        "complaint_theme": "연결 불안정",
        "region_group": "Kanto",
        "channel": "Email",
        "agency": "NYPD",
        "complaint_type": "Illegal Parking",
        "manufacturer": "Sample Automotive",
        "model_year": 2024,
        "component": "STEERING",
        "crash_count": 1,
        "fire_count": 0,
    },
    {
        "week": "2026-W32",
        "region": "부산",
        "age_band": "50대 이상",
        "issue_type": "온보딩",
        "feature": "온보딩",
        "usage_count": 620,
        "status": "대기",
        "avg_resolution_hours": 14,
        "case_count": 28,
        "os_family": "iOS",
        "os_version": "17.x",
        "signup_step": "account creation",
        "error_category": "duplicate account",
        "complaint_theme": "기존 계정 충돌",
        "region_group": "Kyushu",
        "channel": "Phone",
        "agency": "DSNY",
        "complaint_type": "Missed Collection",
        "manufacturer": "Sample Automotive",
        "model_year": 2022,
        "component": "FUEL SYSTEM",
        "crash_count": 0,
        "fire_count": 1,
    },
]


class SyntheticMaterializationError(ValueError):
    """The demo materializer cannot safely produce the requested schema."""


def preview_rows(plan: ViewPlan) -> list[dict[str, str | int]]:
    columns = list(plan.preview_columns)
    duplicate_columns = sorted(column for column in set(columns) if columns.count(column) > 1)
    supported_columns = set.intersection(*(set(row) for row in SAMPLE_ROWS))
    unsupported_columns = sorted(set(columns) - supported_columns)
    if duplicate_columns or unsupported_columns:
        problems: list[str] = []
        if duplicate_columns:
            problems.append("duplicate columns: " + ", ".join(duplicate_columns))
        if unsupported_columns:
            problems.append("unsupported synthetic columns: " + ", ".join(unsupported_columns))
        raise SyntheticMaterializationError("; ".join(problems))

    return [{column: row[column] for column in plan.preview_columns} for row in SAMPLE_ROWS]


def create_evidence(view: NeedexResponse, reviewer: str) -> EvidenceContract:
    now = datetime.now(UTC)
    encoded = json.dumps(view.preview_rows, ensure_ascii=False, sort_keys=True).encode()
    return EvidenceContract(
        view_id=view.id,
        purpose=view.purpose,
        sources=list(view.plan.selected_sources),
        transformations=view.plan.transformations,
        policy_version="taskview-policy/2026-08-18",
        approved_by=reviewer,
        created_at=now,
        expires_at=now + timedelta(days=view.ttl_days),
        row_count=sum(int(row.get("case_count", 0)) for row in view.preview_rows),
        minimum_group_size=20,
        content_sha256=hashlib.sha256(encoded).hexdigest(),
        requester=view.requester.display_name if view.requester else None,
        data_owner=reviewer,
        approval_reason=view.review_reason,
    )
