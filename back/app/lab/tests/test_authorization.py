"""Authorization contracts for isolated Lab surfaces."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.lab.access import (
    ALL_EVALUATION_LAB_PRIVILEGES,
    DISPATCHER_PRIVILEGES,
    MECHANISM_EDIT_PRIVILEGES,
    MECHANISM_PRIVILEGES,
    MECHANISM_READ_PRIVILEGES,
)
from app.lab.assertions import (
    LabMechanismEditPrivilegeAssertion,
    LabMechanismReadPrivilegeAssertion,
)
from app.lab.router import (
    create_dispatcher_dataset,
    create_mechanism_dataset,
    read_dispatcher_datasets,
    read_mechanism_datasets,
)
from core.authorize import AssertionContext, Privileges
from core.user.models import User


def test_every_evaluation_lab_has_a_distinct_read_edit_pair() -> None:
    assert set(MECHANISM_PRIVILEGES) == {
        "dispatcher",
        "task_analysis",
        "briefing",
        "planner",
        "topic_classification",
        "memory_extraction",
        "outcome_reflection",
        "goal_tracking",
        "task_executor",
        "conversation_executor",
        "voice_executor",
    }
    assert len(ALL_EVALUATION_LAB_PRIVILEGES) == 22
    assert len(set(ALL_EVALUATION_LAB_PRIVILEGES)) == 22


def test_static_and_dynamic_routes_declare_their_lab_contract() -> None:
    read_dispatcher_meta = read_dispatcher_datasets._authorize_meta  # pyright: ignore[reportFunctionMemberAccess]
    edit_dispatcher_meta = create_dispatcher_dataset._authorize_meta  # pyright: ignore[reportFunctionMemberAccess]
    read_mechanism_meta = read_mechanism_datasets._authorize_meta  # pyright: ignore[reportFunctionMemberAccess]
    edit_mechanism_meta = create_mechanism_dataset._authorize_meta  # pyright: ignore[reportFunctionMemberAccess]

    assert read_dispatcher_meta["privileges"] == list(DISPATCHER_PRIVILEGES)
    assert edit_dispatcher_meta["privileges"] == [Privileges.DISPATCHER_EVALUATION_EDIT]
    assert read_mechanism_meta == {
        "privileges": MECHANISM_READ_PRIVILEGES,
        "assertion": LabMechanismReadPrivilegeAssertion,
        "params": {},
    }
    assert edit_mechanism_meta == {
        "privileges": MECHANISM_EDIT_PRIVILEGES,
        "assertion": LabMechanismEditPrivilegeAssertion,
        "params": {},
    }


@pytest.mark.asyncio
async def test_mechanism_assertion_checks_only_the_requested_lab(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    check = AsyncMock(return_value=True)
    monkeypatch.setattr("app.lab.assertions.check_privilege", check)
    user = cast(User, SimpleNamespace())
    db = cast(AsyncSession, SimpleNamespace())
    assertion = LabMechanismReadPrivilegeAssertion()

    allowed = await assertion.assert_(
        AssertionContext(
            user=user,
            db=db,
            params={"mechanism": "briefing", "lab_access_mode": "edit"},
        )
    )

    assert allowed is True
    check.assert_awaited_once_with(
        user,
        list(MECHANISM_PRIVILEGES["briefing"]),
        db,
    )


@pytest.mark.asyncio
async def test_mechanism_assertion_rejects_an_unknown_lab(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    check = AsyncMock(return_value=True)
    monkeypatch.setattr("app.lab.assertions.check_privilege", check)
    assertion = LabMechanismReadPrivilegeAssertion()

    allowed = await assertion.assert_(
        AssertionContext(
            user=cast(User, SimpleNamespace()),
            db=cast(AsyncSession, SimpleNamespace()),
            params={"mechanism": "another_lab", "lab_access_mode": "read"},
        )
    )

    assert allowed is False
    check.assert_not_awaited()


def test_new_routes_require_the_exact_lab_privilege():
    from app.lab.router import (
        preview_lab_input,
        rejudge_benchmark,
        resume_benchmark,
        read_human_review,
        submit_human_review,
    )

    for route in (preview_lab_input, read_human_review):
        assert route._authorize_meta["assertion"] is LabMechanismReadPrivilegeAssertion
    for route in (rejudge_benchmark, resume_benchmark, submit_human_review):
        assert route._authorize_meta["assertion"] is LabMechanismEditPrivilegeAssertion
