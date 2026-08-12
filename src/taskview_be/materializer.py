import hashlib
import json
from datetime import UTC, datetime, timedelta

from .schemas import EvidenceContract, TaskViewResponse, ViewPlan

SAMPLE_ROWS = [
    {
        "week": "2026-W31",
        "region": "서울",
        "issue_type": "검색 정확도",
        "feature": "검색",
        "usage_count": 1280,
        "status": "완료",
        "avg_resolution_hours": 6,
        "case_count": 64,
    },
    {
        "week": "2026-W31",
        "region": "경기",
        "issue_type": "알림 지연",
        "feature": "알림",
        "usage_count": 930,
        "status": "처리 중",
        "avg_resolution_hours": 11,
        "case_count": 41,
    },
    {
        "week": "2026-W32",
        "region": "서울",
        "issue_type": "검색 정확도",
        "feature": "검색",
        "usage_count": 1140,
        "status": "완료",
        "avg_resolution_hours": 5,
        "case_count": 57,
    },
    {
        "week": "2026-W32",
        "region": "부산",
        "issue_type": "온보딩",
        "feature": "온보딩",
        "usage_count": 620,
        "status": "대기",
        "avg_resolution_hours": 14,
        "case_count": 28,
    },
]


def preview_rows(plan: ViewPlan) -> list[dict[str, str | int]]:
    return [{column: row[column] for column in plan.preview_columns} for row in SAMPLE_ROWS]


def create_evidence(view: TaskViewResponse, reviewer: str) -> EvidenceContract:
    now = datetime.now(UTC)
    encoded = json.dumps(view.preview_rows, ensure_ascii=False, sort_keys=True).encode()
    return EvidenceContract(
        view_id=view.id,
        purpose=view.purpose,
        sources=list(view.plan.selected_sources),
        transformations=view.plan.transformations,
        policy_version="taskview-policy/2026-08-01",
        approved_by=reviewer,
        created_at=now,
        expires_at=now + timedelta(days=view.ttl_days),
        row_count=sum(int(row.get("case_count", 0)) for row in view.preview_rows),
        minimum_group_size=20,
        content_sha256=hashlib.sha256(encoded).hexdigest(),
    )
