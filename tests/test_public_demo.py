from taskview_be.public_demo import (
    SENSITIVE_SOURCE_FIELDS,
    aggregate_records,
    normalize_fcc,
    normalize_nhtsa,
    normalize_nyc_311,
    project_public_records,
)
from taskview_be.schemas import PurposeSpec, TransformPlanItem, ViewPlan


def test_normalizers_drop_sensitive_source_fields() -> None:
    rows = [
        normalize_fcc(
            {
                "ticket_id": "fcc-1",
                "ticket_created": "2026-08-20T10:00:00.000",
                "state": "CA",
                "issue_type": "Telemarketing",
                "issue": "Robocalls",
                "method": "Phone",
                "caller_id_number": "+1-555-0100",
            }
        ),
        normalize_nyc_311(
            {
                "unique_key": "311-1",
                "created_date": "2026-08-20T10:00:00.000",
                "closed_date": "2026-08-20T12:00:00.000",
                "borough": "BROOKLYN",
                "agency": "DEP",
                "complaint_type": "Water System",
                "incident_address": "1 Private Street",
                "latitude": "40.0",
                "longitude": "-73.0",
            }
        ),
        normalize_nhtsa(
            {
                "odiNumber": "nhtsa-1",
                "dateComplaintFiled": "08/20/2026",
                "manufacturer": "Example Motors",
                "make": "EXAMPLE",
                "model": "SAFE",
                "modelYear": 2024,
                "components": "SERVICE BRAKES, ELECTRICAL SYSTEM",
                "vin": "SECRET-VIN",
                "summary": "raw complaint narrative",
            }
        ),
    ]
    assert all(row is not None for row in rows)
    for row in rows:
        assert row is not None
        assert not SENSITIVE_SOURCE_FIELDS.intersection(row.payload)
        assert "SECRET" not in str(row.payload)
        assert "Private Street" not in str(row.payload)
        assert "+1-555" not in str(row.payload)


def test_aggregate_records_enforces_minimum_group_size() -> None:
    plan = ViewPlan(
        purpose_spec=PurposeSpec(
            objective="FCC complaint priorities",
            decision_to_support="priorities",
            audience="product",
            requested_fields=[],
        ),
        selected_sources=["product"],
        transformations=[
            TransformPlanItem(
                source="product",
                input_fields=["issue_type"],
                output_field="issue_type",
                transformation="select",
                rationale="safe category",
            )
        ],
        preview_columns=["week", "region", "issue_type", "channel", "case_count"],
    )
    common = {
        "week": "2026-W34",
        "region": "CA",
        "issue_type": "Robocalls",
        "channel": "Phone",
        "case_count": 1,
    }
    records = [dict(common) for _ in range(20)] + [{**common, "issue_type": "Singleton"}]
    result = aggregate_records(plan, {"product": records})
    assert result == [{**common, "case_count": 20}]


def test_full_export_is_not_limited_to_dashboard_preview() -> None:
    plan = ViewPlan(
        purpose_spec=PurposeSpec(
            objective="운영 그룹 전체 다운로드",
            decision_to_support="운영 우선순위를 정한다",
            audience="operations",
            requested_fields=[],
        ),
        selected_sources=["operations"],
        transformations=[],
        preview_columns=["week", "region", "agency", "complaint_type", "case_count"],
    )
    records = [
        {
            "week": "2026-W34",
            "region": f"REGION-{group}",
            "agency": "AGENCY",
            "complaint_type": "TYPE",
            "case_count": 1,
        }
        for group in range(30)
        for _ in range(20)
    ]

    preview = aggregate_records(plan, {"operations": records})
    full_export = aggregate_records(plan, {"operations": records}, limit=None)

    assert len(preview) == 24
    assert len(full_export) == 30
    assert sum(row["case_count"] for row in full_export) == 600


def test_public_record_export_uses_only_approved_safe_columns() -> None:
    plan = ViewPlan(
        purpose_spec=PurposeSpec(
            objective="공개 운영 데이터 다운로드",
            decision_to_support="운영 우선순위를 정한다",
            audience="operations",
            requested_fields=[],
        ),
        selected_sources=["operations"],
        transformations=[],
        preview_columns=[
            "week",
            "region",
            "agency",
            "complaint_type",
            "avg_resolution_hours",
            "case_count",
        ],
    )
    records = [
        {
            "week": "2026-W34",
            "region": "BROOKLYN",
            "agency": "DEP",
            "complaint_type": "Water System",
            "resolution_hours": 2.5,
            "case_count": 1,
            "descriptor": "Hydrant Running Full",
            "incident_address": "must never be exported",
        },
        {
            "week": "2026-W34",
            "region": "QUEENS",
            "agency": "NYPD",
            "complaint_type": "Illegal Parking",
            "resolution_hours": None,
            "case_count": 1,
            "external_id_hash": "must never be exported",
        },
    ]

    exported = project_public_records(plan, {"operations": records})

    assert exported == [
        {
            "week": "2026-W34",
            "region": "BROOKLYN",
            "agency": "DEP",
            "complaint_type": "Water System",
            "avg_resolution_hours": 2.5,
            "case_count": 1,
        },
        {
            "week": "2026-W34",
            "region": "QUEENS",
            "agency": "NYPD",
            "complaint_type": "Illegal Parking",
            "avg_resolution_hours": "",
            "case_count": 1,
        },
    ]
