"""Manual dispatcher test.

Usage:
    docker compose exec backend python tests/manual/test_dispatcher.py
"""

import asyncio
from uuid import UUID
from sqlalchemy.orm import joinedload
from core.database import AsyncSessionLocal
from app.task import Task
from app.agent import dispatcher_service


async def main():
    task_id = UUID("99767858-07b9-4d5e-afd6-d93df6518e07")

    print("=" * 60)
    print(f"📋 Task: {task_id}")
    print("=" * 60)

    async with AsyncSessionLocal() as db:
        # Load the task and its agent eagerly to avoid asynchronous lazy loading.
        from sqlalchemy import select
        from app.task.models import Task as TaskModel

        result = await db.execute(
            select(TaskModel)
            .options(joinedload(TaskModel.agent))
            .where(TaskModel.id == task_id)
        )
        task: Task | None = result.scalar_one_or_none()

        if task is None:
            print(f"✗ Task {task_id} not found!")
            return

        # task.objective = "Write a note about Louis X of France"
        # task.objective = "Grade Emile's homework"
        # task.objective = "How is Filibert?"
        task.objective = (
            "Do you have information about the Six-Day War? I want a complete report "
            "written by a specialist."
        )

        print(f"  - ID: {task.id}")
        print(f"  - Label: {task.label}")
        if task.objective:
            print(f"  - Objective: {task.objective.strip()}")  # type: ignore
            
        print(f"  - Status: {task.status}")
        print(f"  - AI: {task.ai}")

        try:
            result = await dispatcher_service.run(
                task, use_default_params=True, use_memory=False
            )

            print("\n" + "=" * 60)
            print("📊 DISPATCHER RESULT")
            print("=" * 60)
            print(f"  - Route: {result.decision.route}")
            print(f"  - Cost: ${result.cost:.6f}")
            print(f"  - Duration: {result.execution_time:.2f}s")

            print("\n" + "=" * 60)
            print("📝 COMPLETE PROMPT")
            print("=" * 60)
            print(result.prompt)

        except Exception as e:
            print("\n✗ Error while running the dispatcher:")
            print(f"  {type(e).__name__}: {e}")
            import traceback

            traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
