"""Descriptive whole-run counts, without treating repetitions as independent cases."""

from uuid import UUID

from sqlalchemy import JSON, and_, func, or_, select

from core.database import get_db
from .comparison_schemas import ComparisonSummary
from .models import LabEvaluationRunCase as Result


async def summarize(left_id: UUID, right_id: UUID, *, comparable: bool) -> ComparisonSummary:
    input_data = Result.case_snapshot["input_data"]
    reference = Result.case_snapshot["expected_output"]
    counts = (
        select(Result.run_id, input_data.label("input"), reference.label("reference"),
               Result.repetition, func.count().label("n"),
               func.max(Result.score_percent).label("score"),
               func.count().filter(Result.judge_output.is_not(None),
                   Result.judge_output != JSON.NULL).label("judged"),
               func.count().filter(Result.error.is_not(None), Result.error != "").label("failed"))
        .where(Result.run_id.in_((left_id, right_id)))
        .group_by(Result.run_id, input_data, reference, Result.repetition)
        .cte("summary_counts")
    )
    left = select(counts).where(counts.c.run_id == left_id).subquery("before_counts")
    right = select(counts).where(counts.c.run_id == right_id).subquery("after_counts")
    paired = (
        select(func.coalesce(left.c.input, right.c.input).label("input"),
               func.coalesce(left.c.reference, right.c.reference).label("reference"),
               left.c.n.label("left_n"), right.c.n.label("right_n"),
               left.c.score.label("left_score"), right.c.score.label("right_score"),
               left.c.judged.label("left_judged"), right.c.judged.label("right_judged"),
               left.c.failed.label("left_failed"), right.c.failed.label("right_failed"))
        .select_from(left.join(right, and_(left.c.input == right.c.input,
            left.c.reference == right.c.reference, left.c.repetition == right.c.repetition), full=True))
        .cte("summary_pairs")
    )
    matched = and_(paired.c.left_n == 1, paired.c.right_n == 1)
    failed = and_(matched, or_(paired.c.left_failed > 0, paired.c.right_failed > 0))
    judged = and_(matched, paired.c.left_judged == 1, paired.c.right_judged == 1,
                  paired.c.left_score.is_not(None), paired.c.right_score.is_not(None))
    valid = and_(judged, paired.c.left_failed == 0, paired.c.right_failed == 0)
    distinct_cases = select(paired.c.input, paired.c.reference).distinct().subquery()
    row = (await get_db().execute(select(
        select(func.count()).select_from(distinct_cases).scalar_subquery().label("cases"),
        func.count().label("observations"),
        func.count().filter(matched).label("matched"),
        func.count().filter(paired.c.left_n.is_(None)).label("missing_left"),
        func.count().filter(paired.c.right_n.is_(None)).label("missing_right"),
        func.count().filter(paired.c.left_n.is_not(None), paired.c.right_n.is_not(None),
            or_(paired.c.left_n > 1, paired.c.right_n > 1)).label("ambiguous"),
        func.count().filter(matched, ~judged).label("unjudged"),
        func.count().filter(failed).label("failed"),
        func.count().filter(valid, paired.c.right_score > paired.c.left_score).label("increased"),
        func.count().filter(valid, paired.c.right_score < paired.c.left_score).label("decreased"),
        func.count().filter(valid, paired.c.right_score == paired.c.left_score).label("equal"),
    ).select_from(paired))).mappings().one()
    result = ComparisonSummary.model_validate(dict(row))
    if not comparable:
        result.increased = result.decreased = result.equal = None
    return result
