import hashlib
import json
from datetime import UTC, datetime, timedelta

from .schemas import EvidenceContract, TaskViewResponse


def preview_rows() -> list[dict[str, str | int]]:
    return [
        {"week": "2026-W31", "region": "서울", "issue_type": "검색 정확도", "case_count": 64},
        {"week": "2026-W31", "region": "경기", "issue_type": "알림 지연", "case_count": 41},
        {"week": "2026-W32", "region": "서울", "issue_type": "검색 정확도", "case_count": 57},
        {"week": "2026-W32", "region": "부산", "issue_type": "온보딩", "case_count": 28},
    ]


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

