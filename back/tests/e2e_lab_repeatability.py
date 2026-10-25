"""Entirely synthetic saved judgments for the assembled Lab reader journey."""

from copy import deepcopy
from uuid import uuid4

from core.database import get_db
from app.lab.mechanism_rubrics import get_rubric
from app.lab.models import LabEvaluationDataset, LabEvaluationRun, LabEvaluationRunCase, LabJudgmentCampaign, LabJudgmentResult


async def seed_repeatability() -> dict[str, str]:
    db = get_db()
    rubric = get_rubric("planner").prompt_value()
    dataset = LabEvaluationDataset(name=f"Synthetic judge repeatability {uuid4().hex}", mechanism="planner")
    db.add(dataset)
    await db.flush()
    model = {"label": "Synthetic saved judge", "code": "synthetic-judge", "binding": "synthetic-model-binding"}
    run = LabEvaluationRun(dataset_id=dataset.id, status="completed", phase="finished",
        total_cases=2, completed_cases=2, judged_cases=2, score_percent=90,
        llm_snapshot={"label": "Synthetic saved candidate"}, judge_llm_snapshot=model,
        configuration_snapshot={"rubric": rubric})
    db.add(run)
    await db.flush()
    outputs = [LabEvaluationRunCase(run_id=run.id,
        case_snapshot={"id": str(uuid4()), "name": f"Synthetic report {index}",
            "input_data": {"variable_value": f"Prepare synthetic report {index}"}, "expected_output": {}},
        actual_output={"result": f"Synthetic fixed output {index}"}, score_percent=90, verdict="pass",
        score_details={"candidate_status": "completed"}) for index in range(2)]
    db.add_all(outputs)
    await db.flush()
    for sequence, score in ((1, 80), (2, 90)):
        campaign = LabJudgmentCampaign(run_id=run.id, sequence=sequence, status="completed",
            configuration={"model": model, "rubric": deepcopy(rubric), "pass_threshold": 75, "reasoning_effort": None})
        db.add(campaign)
        await db.flush()
        for output in outputs:
            db.add(LabJudgmentResult(campaign_id=campaign.id, result_id=output.id, status="completed",
                score_percent=score, verdict="pass", output={"rubric_version": rubric["version"]}))
    await db.commit()
    return {"lab_run_id": str(run.id), "lab_dataset_name": dataset.name}
