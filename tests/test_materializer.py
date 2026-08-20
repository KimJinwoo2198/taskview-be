import pytest

from taskview_be.materializer import SyntheticMaterializationError, preview_rows
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


def test_preview_rows_rejects_llm_output_missing_from_synthetic_fixture():
    plan = ViewPlan(
        purpose_spec=PurposeSpec(
            objective="상담 유형별 신규 안전 지표를 비교한다",
            decision_to_support="도움말 콘텐츠 순서를 정한다",
            audience="support",
            requested_fields=["issue_type"],
        ),
        selected_sources=["voc"],
        transformations=[
            TransformPlanItem(
                source="voc",
                input_fields=["issue_type"],
                output_field="new_safe_metric",
                transformation="select",
                rationale="LLM이 새 출력 이름을 제안한 상황",
            )
        ],
        preview_columns=["new_safe_metric"],
    )

    with pytest.raises(
        SyntheticMaterializationError,
        match=r"unsupported synthetic columns: new_safe_metric",
    ):
        preview_rows(plan)
