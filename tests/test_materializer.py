from taskview_be.materializer import preview_rows
from taskview_be.schemas import PurposeSpec, TransformPlanItem, ViewPlan


def test_preview_rows_support_age_band_without_exposing_exact_age():
    plan = ViewPlan(
        purpose_spec=PurposeSpec(
            objective="연령대별 문의 유형을 비교한다",
            decision_to_support="도움말 콘텐츠 순서를 정한다",
            audience="support",
            requested_fields=["created_at", "age", "message"],
        ),
        selected_sources=["voc"],
        transformations=[
            TransformPlanItem(
                source="voc",
                input_fields=["age"],
                output_field="age_band",
                transformation="age_band",
                rationale="정확한 나이 대신 연령대 구간만 제공",
            )
        ],
        preview_columns=["week", "age_band", "case_count"],
    )

    rows = preview_rows(plan)

    assert rows
    assert all(set(row) == {"week", "age_band", "case_count"} for row in rows)
    assert all(row["age_band"] in {"20대", "30대", "40대", "50대 이상"} for row in rows)
    assert all("age" not in row for row in rows)
