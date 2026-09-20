"""Manual executor test.

Usage:
    docker compose exec backend python tests/manual/test_executor.py
"""

import os
from uuid import UUID
from app.agent.executor_service import run as executor_run
from app.task import task_service

async def main():
    task_id = UUID(os.environ["MANUAL_TASK_ID"])

    print("=" * 60)
    print(f"🤖 Executor Test: {task_id}")
    print("=" * 60)

    task = await task_service.get_by_id(task_id)

    if task is None:
        return

    print(f"  - ID: {task.id}")
    print(f"  - Label: {task.label}")
    if task.objective is not None:
        print(f"  - Objective: {task.objective.strip()}")

    # Execute the task.
    result = await executor_run(task, save_change=False)
    
    print("\n" + "=" * 60)
    print("📊 Execution result:")
    print("=" * 60)
    print(f"✅ Success: {result.success}")
    print(f"📝 Result: {result.result}")
    print(f"💰 Cost: ${result.cost:.4f}")
    print(f"⏱️  Execution time: {result.execution_time:.2f}s")
    print(f"🛠️  Tools used: {', '.join(result.tools_used) if result.tools_used else 'None'}")
    
    print("\n" + "=" * 60)
    print("📝 COMPLETE PROMPT")
    print("=" * 60)
    print(result.prompt)
    
    if result.error:
        print(f"❌ Error: {result.error}")
