"""Personal Goal categories; no administrative scope bypasses creator ownership."""

from sqlalchemy import func, select

from core.database import get_db
from core.user import get_current_user_id

from .models import Goal, GoalCategory
from .schemas import GoalCategoryRead, GoalCategoryWrite


def _owner() -> int:
    user_id = get_current_user_id()
    if user_id is None:
        raise LookupError("Goal category not found")
    return user_id


async def require_owned(category_id: int, *, lock: bool = False) -> GoalCategory:
    query = select(GoalCategory).where(
        GoalCategory.id == category_id, GoalCategory.created_by == _owner()
    )
    if lock:
        query = query.with_for_update()
    category = await get_db().scalar(query)
    if category is None:
        raise LookupError("Goal category not found")
    return category


async def list_categories() -> list[GoalCategoryRead]:
    categories = await get_db().scalars(
        select(GoalCategory)
        .where(GoalCategory.created_by == _owner())
        .order_by(func.lower(GoalCategory.label), GoalCategory.label, GoalCategory.id)
    )
    return [GoalCategoryRead.model_validate(category) for category in categories]


async def create(data: GoalCategoryWrite) -> GoalCategoryRead:
    category = GoalCategory(label=data.label, created_by=_owner())
    db = get_db()
    db.add(category)
    await db.commit()
    await db.refresh(category)
    return GoalCategoryRead.model_validate(category)


async def update(category_id: int, data: GoalCategoryWrite) -> GoalCategoryRead:
    category = await require_owned(category_id, lock=True)
    category.label = data.label
    await get_db().commit()
    await get_db().refresh(category)
    return GoalCategoryRead.model_validate(category)


async def delete(category_id: int) -> None:
    # Assignments lock the category before the Goal too: deletion cannot race a new link.
    category = await require_owned(category_id, lock=True)
    db = get_db()
    goals = list(await db.scalars(
        select(Goal).where(Goal.category_id == category_id)
        .execution_options(include_historized=True).with_for_update()
    ))
    for goal in goals:
        goal.category_id = None
    category.soft_delete()
    await db.commit()
    # Retain Goal revisions and normal observers when removing a classification.
    from .goal_service import emit_updated

    for goal in goals:
        await emit_updated(goal.id)
