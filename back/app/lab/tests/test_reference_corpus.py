"""Public reference cases stay executable through the same Lab contracts as the UI."""
import json
from pathlib import Path

import pytest

from app.lab import mechanism_evaluation_service as service
from app.lab.models import LabEvaluationDataset
from app.lab.schemas import EvaluationCaseCreate, MechanismCaseUpdate
from app.lab.contracts import resolve_input
from app.lab.objective_checks import check_output


@pytest.mark.asyncio
async def test_reference_import_uses_http_authorization_and_never_overwrites(client):
    import httpx
    from scripts.import_lab_reference import install

    with pytest.raises(httpx.HTTPStatusError):
        await install(client)
    credentials = {"email": "reference-admin@example.com", "password": "reference-password-123"}
    assert (await client.post("/api/auth/register", json=credentials)).status_code == 201
    login = await client.post("/api/auth/login-json", json=credentials)
    client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
    result = await install(client)
    assert result["cases"] == 6
    assert result["model_calls"] == 0
    with pytest.raises(ValueError, match="already exists"):
        await install(client)


@pytest.mark.asyncio
async def test_reference_corpus_can_be_saved_resolved_and_checked(db):
    corpus = json.loads((Path(__file__).parents[1] / "reference_corpus.json").read_text())
    dataset = LabEvaluationDataset(
        name=corpus["name"], mechanism=corpus["mechanism"],
        purpose=corpus["purpose"], parameters=corpus["parameters"],
    )
    db.add(dataset)
    await db.commit()
    for case in corpus["cases"]:
        saved = await service.create_case(corpus["mechanism"], dataset.id, EvaluationCaseCreate(name=case["name"]))
        saved = await service.update_case(corpus["mechanism"], saved.id, MechanismCaseUpdate(
            revision=saved.revision, **case,
        ))
        _, native = resolve_input(corpus["mechanism"], saved.input_data, corpus["parameters"])
        assert native["objective"].startswith("<p>")
        assert "expected_output" not in native
        checks = check_output(corpus["mechanism"], native, saved.expected_output)
        assert all(row["passed"] for row in checks), checks
        assert saved.categories == case["categories"]
