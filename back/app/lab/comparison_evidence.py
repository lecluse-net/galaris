"""SQL projections of paired evidence; never materialize whole-run output bodies."""

from uuid import UUID

from sqlalchemy import Float, and_, case, cast, func, literal, or_, select, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import CTE

from core.database import get_db
from .models import LabEvaluationRunCase as Result
from .comparison_schemas import ComparisonPerformance, ComparisonRisks, PairedMetric


def json_number(value: ColumnElement[object]) -> ColumnElement[float]:
    return case((func.jsonb_typeof(value) == "number", cast(value, Float[float]())), else_=None)


def json_array(value: ColumnElement[object]) -> ColumnElement[object]:
    return case((func.jsonb_typeof(value) == "array", value), else_=literal([], type_=JSONB))


def paired_evidence(left_id: UUID, right_id: UUID) -> CTE:
    rows = (
        select(
            Result.id,
            Result.run_id,
            Result.repetition,
            Result.case_snapshot["input_data"].label("input"),
            Result.case_snapshot["expected_output"].label("reference"),
            Result.judge_output.label("judgment"),
            Result.score_details.label("details"),
            Result.score_percent.label("score"),
            Result.verdict,
            Result.error,
            Result.cost,
            Result.duration,
            func.count()
            .over(
                partition_by=(
                    Result.run_id,
                    Result.repetition,
                    Result.case_snapshot["input_data"],
                    Result.case_snapshot["expected_output"],
                )
            )
            .label("n"),
        )
        .where(Result.run_id.in_((left_id, right_id)))
        .cte("evidence_rows")
    )
    left, right = rows.alias("before_evidence"), rows.alias("after_evidence")
    return (
        select(
            *(
                column.label(f"{prefix}_{column.key}")
                for prefix, source in (("left", left), ("right", right))
                for column in source.c
            )
        )
        .select_from(
            left.join(
                right,
                and_(
                    left.c.input == right.c.input,
                    left.c.reference == right.c.reference,
                    left.c.repetition == right.c.repetition,
                ),
            )
        )
        .where(left.c.run_id == left_id, right.c.run_id == right_id, left.c.n == 1, right.c.n == 1)
        .cte("evidence_pairs")
    )


def assessed(pairs: CTE) -> ColumnElement[bool]:
    return and_(
        func.coalesce(pairs.c.left_error, "") == "",
        func.coalesce(pairs.c.right_error, "") == "",
        pairs.c.left_score.is_not(None),
        pairs.c.right_score.is_not(None),
        pairs.c.left_judgment["rubric_version"].astext.is_not(None),
        pairs.c.left_judgment["rubric_version"] == pairs.c.right_judgment["rubric_version"],
        func.jsonb_typeof(pairs.c.left_judgment["critical_failures"]) == "array",
        func.jsonb_typeof(pairs.c.right_judgment["critical_failures"]) == "array",
    )


def critical_regression(pairs: CTE) -> ColumnElement[bool]:
    # Explanations are prose, not stable failure identifiers. Compare absence to presence.
    def has_failure(side: str) -> ColumnElement[bool]:
        return or_(
            func.jsonb_array_length(json_array(pairs.c[f"{side}_judgment"]["critical_failures"]))
            > 0,
            func.coalesce(
                cast(pairs.c[f"{side}_details"]["checks"], JSONB).contains(
                    [{"critical": True, "passed": False}]
                ),
                False,
            ),
        )

    return and_(assessed(pairs), ~has_failure("left"), has_failure("right"))


def verdict_regression(pairs: CTE) -> ColumnElement[bool]:
    return and_(assessed(pairs), pairs.c.left_verdict == "pass", pairs.c.right_verdict == "fail")


def dimension_evidence(pairs: CTE) -> CTE:
    sides: list[CTE] = []
    for prefix in ("left", "right"):
        values = (
            func.jsonb_array_elements(json_array(pairs.c[f"{prefix}_judgment"]["dimensions"]))
            .table_valued("value")
            .lateral(f"{prefix}_dimensions")
        )
        value = cast(values.c.value, JSONB)
        code, score = value["code"].astext, json_number(value["score_percent"])
        sides.append(
            select(pairs.c.left_id, code.label("code"), func.max(score).label("score"))
            .select_from(pairs.join(values, true()))
            .where(assessed(pairs), code.is_not(None))
            .group_by(pairs.c.left_id, code)
            .having(func.count() == 1, func.max(score).between(0, 100))
            .cte(f"{prefix}_dimension_scores")
        )
    left, right = sides
    return (
        select(left.c.left_id, left.c.code, (right.c.score - left.c.score).label("delta"))
        .join(right, and_(left.c.left_id == right.c.left_id, left.c.code == right.c.code))
        .cte("dimension_pairs")
    )


def first_output(pairs: CTE, side: str) -> ColumnElement[float]:
    details = pairs.c[f"{side}_details"]["performance"]
    value = json_number(details["first_output_seconds"])
    return case(
        (and_(details["version"].astext == "lab-executor-stream/v1", value >= 0), value), else_=None
    )


async def summarize_evidence(
    pairs: CTE, dimensions: CTE
) -> tuple[ComparisonRisks, ComparisonPerformance]:
    counts = (
        (
            await get_db().execute(
                select(
                    func.count().filter(assessed(pairs)).label("assessed_pairs"),
                    func.count().filter(critical_regression(pairs)).label("introduced_critical"),
                    func.count().filter(verdict_regression(pairs)).label("pass_to_fail"),
                ).select_from(pairs)
            )
        )
        .mappings()
        .one()
    )
    rows = (
        (
            await get_db().execute(
                select(
                    dimensions.c.code,
                    func.count().label("pairs"),
                    func.count().filter(dimensions.c.delta < 0).label("decreased"),
                    func.count().filter(dimensions.c.delta > 0).label("increased"),
                    func.count().filter(dimensions.c.delta == 0).label("equal"),
                    func.avg(dimensions.c.delta).label("mean_delta"),
                )
                .group_by(dimensions.c.code)
                .order_by(dimensions.c.code)
            )
        )
        .mappings()
        .all()
    )
    risks = ComparisonRisks.model_validate(
        {**dict(counts), "dimensions": [dict(row) for row in rows]}
    )
    metrics: dict[str, PairedMetric] = {}
    for name in ("first_output", "cost", "duration", "quality"):
        left = (
            first_output(pairs, "left")
            if name == "first_output"
            else pairs.c[f"left_{'score' if name == 'quality' else name}"]
        )
        right = (
            first_output(pairs, "right")
            if name == "first_output"
            else pairs.c[f"right_{'score' if name == 'quality' else name}"]
        )
        valid = and_(
            left.is_not(None),
            right.is_not(None),
            left >= 0,
            right >= 0,
            pairs.c.left_details["candidate_status"].astext == "completed",
            pairs.c.right_details["candidate_status"].astext == "completed",
        )
        if name == "quality":
            valid = and_(valid, assessed(pairs))
        row = (
            (
                await get_db().execute(
                    select(
                        func.count().label("pairs"),
                        func.percentile_cont(0.5).within_group(left).label("left_median"),
                        func.percentile_cont(0.5).within_group(right).label("right_median"),
                        func.percentile_cont(0.5).within_group(right - left).label("median_delta"),
                    )
                    .select_from(pairs)
                    .where(valid)
                )
            )
            .mappings()
            .one()
        )
        metrics[name] = PairedMetric.model_validate(dict(row))
    return risks, ComparisonPerformance.model_validate(metrics)
