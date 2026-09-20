"""HTTP API for complete skill packages and agent activation permissions."""

from __future__ import annotations


from pathlib import Path
from typing import Literal, cast
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from core.authorize import Privileges, authorize
from app.agent import current_management_scope

from . import learning_service, skill_service, storage
from .models import LearnedSkill, LearnedSkillEvidence, Skill
from .schemas import (
    LearnedSkillDetail,
    LearnedSkillEvidencePublic,
    LearnedSkillLearningStatus,
    LearnedSkillMutationResult,
    LearnedSkillPage,
    LearnedSkillPublic,
    LearnedSkillSuspensionUpdate,
    SkillAgent,
    SkillAuthorizationResult,
    SkillAuthorizations,
    SkillAuthorizationUpdate,
    SkillCategoryAssignmentResult,
    SkillCategoryAssignmentUpdate,
    SkillCategoryAuthorizationResult,
    SkillCategoryAuthorizationUpdate,
    SkillCategoryCreate,
    SkillCategoryDeleteResult,
    SkillCategoryPublic,
    SkillCategoryResult,
    SkillCategoryUpdate,
    SkillCreate,
    SkillDeleteResult,
    SkillFile,
    SkillFileContent,
    SkillGlobalAuthorizationUpdate,
    SkillImportResult,
    SkillPublic,
    SkillRescanResult,
    SkillUpdate,
)


router = APIRouter(prefix="/skills", tags=["skills"])


async def _require_global_scope() -> None:
    if not (await current_management_scope()).is_global:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Le management global des agents est requis",
        )


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, FileExistsError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


async def _record(skill_id: int) -> Skill:
    record = await skill_service.get(skill_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Compétence introuvable")
    return record


@router.get("", response_model=list[SkillPublic])
@authorize(privileges=[Privileges.SKILL_ACCESS, Privileges.SKILL_EDIT, Privileges.SKILL_ASSIGN])
async def list_skills() -> list[SkillPublic]:
    return [skill_service.to_public(record) for record in await skill_service.get_all()]


@router.post("/rescan", response_model=SkillRescanResult)
@authorize(privileges=Privileges.SKILL_EDIT)
async def rescan_skills() -> SkillRescanResult:
    await _require_global_scope()
    result = await skill_service.sync_from_disk()
    return SkillRescanResult(
        created=result["created"],
        restored=result["restored"],
        invalid_directories=result["invalid_directories"],
    )


@router.post("/import", response_model=SkillImportResult)
@authorize(privileges=Privileges.SKILL_EDIT)
async def import_skill(
    file: UploadFile = File(...),
    code: str | None = Form(default=None),
    label: str | None = Form(default=None),
    overwrite: bool = Form(default=False),
) -> SkillImportResult:
    await _require_global_scope()
    content = await file.read(storage.MAX_UPLOAD_SIZE + 1)
    try:
        record, created = await skill_service.import_upload(
            file.filename or "skill.zip", content, code, label, overwrite
        )
    except (ValueError, OSError, FileExistsError) as exc:
        raise _http_error(exc) from exc
    return SkillImportResult(skill=skill_service.to_public(record), created=created)


@router.get("/agents", response_model=list[SkillAgent])
@authorize(privileges=[Privileges.SKILL_ACCESS, Privileges.SKILL_EDIT, Privileges.SKILL_ASSIGN])
async def list_skill_agents() -> list[SkillAgent]:
    scope = await current_management_scope()
    return [
        SkillAgent(
            id=agent.id,
            code=agent.code,
            label=f"{agent.first_name} {agent.last_name}".strip(),
            driver=agent.agent_driver,
        )
        for agent in await skill_service.list_skill_agents(agent_ids=scope.agent_ids)
    ]


@router.get("/authorizations", response_model=SkillAuthorizations)
@authorize(privileges=Privileges.SKILL_ASSIGN)
async def list_skill_authorizations(
    agent_id: int | None = Query(default=None, gt=0),
    skill_id: int | None = Query(default=None, gt=0),
    category_id: int | None = Query(default=None, gt=0),
) -> SkillAuthorizations:
    try:
        scope = await current_management_scope()
        if agent_id is not None and not scope.allows(agent_id):
            raise HTTPException(status_code=404, detail="Agent introuvable")
        authorizations = await skill_service.list_authorizations(
            agent_id,
            skill_id,
            category_id,
            agent_ids=scope.agent_ids,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Compétence introuvable") from exc
    except ValueError as exc:
        raise _http_error(exc) from exc
    return SkillAuthorizations(authorizations=authorizations)


@router.get("/categories", response_model=list[SkillCategoryPublic])
@authorize(privileges=[Privileges.SKILL_ACCESS, Privileges.SKILL_EDIT, Privileges.SKILL_ASSIGN])
async def list_skill_categories() -> list[SkillCategoryPublic]:
    return [
        skill_service.to_category_public(category)
        for category in await skill_service.get_categories()
    ]


@router.post(
    "/categories",
    response_model=SkillCategoryResult,
    status_code=status.HTTP_201_CREATED,
)
@authorize(privileges=Privileges.SKILL_EDIT)
async def create_skill_category(data: SkillCategoryCreate) -> SkillCategoryResult:
    await _require_global_scope()
    try:
        category = await skill_service.create_category(data)
    except FileExistsError as exc:
        raise _http_error(exc) from exc
    return SkillCategoryResult(category=skill_service.to_category_public(category))


@router.put("/categories/{category_id}", response_model=SkillCategoryResult)
@authorize(privileges=Privileges.SKILL_EDIT)
async def update_skill_category(
    category_id: int,
    data: SkillCategoryUpdate,
) -> SkillCategoryResult:
    await _require_global_scope()
    try:
        category = await skill_service.update_category(category_id, data)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Catégorie introuvable") from exc
    except FileExistsError as exc:
        raise _http_error(exc) from exc
    return SkillCategoryResult(category=skill_service.to_category_public(category))


@router.delete(
    "/categories/{category_id}",
    response_model=SkillCategoryDeleteResult,
)
@authorize(privileges=Privileges.SKILL_EDIT)
async def delete_skill_category(category_id: int) -> SkillCategoryDeleteResult:
    await _require_global_scope()
    try:
        skill_ids, agent_ids = await skill_service.delete_category(category_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Catégorie introuvable") from exc
    return SkillCategoryDeleteResult(
        affected_skill_ids=skill_ids,
        affected_agent_ids=agent_ids,
    )


@router.put(
    "/categories/{category_id}/authorization/agents/{agent_id}",
    response_model=SkillCategoryAuthorizationResult,
)
@authorize(privileges=Privileges.SKILL_ASSIGN)
async def update_category_authorization(
    category_id: int,
    agent_id: int,
    data: SkillCategoryAuthorizationUpdate,
) -> SkillCategoryAuthorizationResult:
    try:
        scope = await current_management_scope()
        if not scope.allows(agent_id):
            raise HTTPException(status_code=404, detail="Agent introuvable")
        state, agent_ids = await skill_service.set_category_authorization(
            category_id,
            agent_id,
            data.state,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Catégorie introuvable") from exc
    except ValueError as exc:
        raise _http_error(exc) from exc
    return SkillCategoryAuthorizationResult(
        category_id=category_id,
        agent_id=agent_id,
        state=state,
        affected_agent_ids=agent_ids,
    )


def _learned_public(record: LearnedSkill) -> LearnedSkillPublic:
    return LearnedSkillPublic(
        id=record.id,
        agent_id=record.agent_id,
        code=record.code,
        label=record.label,
        description=record.description,
        revision=record.revision,
        positive_weight=record.positive_weight,
        negative_weight=record.negative_weight,
        evidence_count=record.evidence_count,
        score=record.score,
        suspended=record.suspended,
        injectable=learning_service.is_injectable(record),
        last_evidence_at=record.last_evidence_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _learned_evidence_public(record: LearnedSkillEvidence) -> LearnedSkillEvidencePublic:
    return LearnedSkillEvidencePublic(
        id=record.id,
        source_ref=record.source_ref,
        operation=cast(Literal["CREATE", "REINFORCE", "REVISE", "WEAKEN"], record.operation),
        polarity=cast(Literal["positive", "negative"], record.polarity),
        weight=record.weight,
        confidence=record.confidence,
        evidence_refs=list(record.evidence_refs),
        rationale=record.rationale,
        created_at=record.created_at,
    )


@router.get("/learned", response_model=LearnedSkillPage)
@authorize(privileges=[Privileges.SKILL_ACCESS, Privileges.SKILL_EDIT])
async def list_learned_skills(
    agent_id: int | None = Query(default=None, gt=0),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
) -> LearnedSkillPage:
    scope = await current_management_scope()
    if agent_id is not None and not scope.allows(agent_id):
        raise HTTPException(status_code=404, detail="Agent introuvable")
    records, total = await learning_service.list_records(
        agent_id=agent_id,
        page=page,
        page_size=page_size,
        agent_ids=scope.agent_ids,
    )
    return LearnedSkillPage(
        items=[_learned_public(record) for record in records],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/learned/status", response_model=LearnedSkillLearningStatus)
@authorize(privileges=[Privileges.SKILL_ACCESS, Privileges.SKILL_EDIT])
async def get_learned_skill_status() -> LearnedSkillLearningStatus:
    mode = learning_service.learning_mode()
    return LearnedSkillLearningStatus(mode=mode, enabled=mode != "off")


@router.get("/learned/{learned_skill_id}", response_model=LearnedSkillDetail)
@authorize(privileges=[Privileges.SKILL_ACCESS, Privileges.SKILL_EDIT])
async def get_learned_skill(learned_skill_id: UUID) -> LearnedSkillDetail:
    record = await learning_service.get_record(learned_skill_id)
    scope = await current_management_scope()
    if record is None or not scope.allows(record.agent_id):
        raise HTTPException(status_code=404, detail="Compétence apprise introuvable")
    public = _learned_public(record)
    return LearnedSkillDetail(
        **public.model_dump(),
        markdown=record.markdown,
        evidences=[_learned_evidence_public(item) for item in record.evidences],
    )


@router.put(
    "/learned/{learned_skill_id}/suspension",
    response_model=LearnedSkillMutationResult,
)
@authorize(privileges=Privileges.SKILL_EDIT)
async def suspend_learned_skill(
    learned_skill_id: UUID,
    data: LearnedSkillSuspensionUpdate,
) -> LearnedSkillMutationResult:
    existing = await learning_service.get_record(learned_skill_id)
    scope = await current_management_scope()
    if existing is None or not scope.allows(existing.agent_id):
        raise HTTPException(status_code=404, detail="Compétence apprise introuvable")
    record = await learning_service.set_suspended(learned_skill_id, data.suspended)
    if record is None:
        raise HTTPException(status_code=404, detail="Compétence apprise introuvable")
    return LearnedSkillMutationResult(
        skill=_learned_public(record),
        affected_agent_ids=[],
    )


@router.post("", response_model=SkillPublic, status_code=status.HTTP_201_CREATED)
@authorize(privileges=Privileges.SKILL_EDIT)
async def create_skill(data: SkillCreate) -> SkillPublic:
    await _require_global_scope()
    try:
        record = await skill_service.create(data)
    except (ValueError, OSError, FileExistsError) as exc:
        raise _http_error(exc) from exc
    return skill_service.to_public(record)


@router.get("/{skill_id}", response_model=SkillPublic)
@authorize(privileges=[Privileges.SKILL_ACCESS, Privileges.SKILL_EDIT, Privileges.SKILL_ASSIGN])
async def get_skill(skill_id: int) -> SkillPublic:
    return skill_service.to_public(await _record(skill_id))


@router.put("/{skill_id}", response_model=SkillPublic)
@authorize(privileges=Privileges.SKILL_EDIT)
async def update_skill(
    skill_id: int,
    data: SkillUpdate,
) -> SkillPublic:
    await _require_global_scope()
    try:
        record = await skill_service.update(skill_id, data)
    except (ValueError, OSError) as exc:
        raise _http_error(exc) from exc
    if record is None:
        raise HTTPException(status_code=404, detail="Compétence introuvable")
    return skill_service.to_public(record)


@router.delete("/{skill_id}", response_model=SkillDeleteResult)
@authorize(privileges=Privileges.SKILL_EDIT)
async def delete_skill(skill_id: int) -> SkillDeleteResult:
    await _require_global_scope()
    try:
        deleted, agent_ids = await skill_service.delete_skill(skill_id)
    except ValueError as exc:
        raise _http_error(exc) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Compétence introuvable")
    return SkillDeleteResult(affected_agent_ids=agent_ids)


@router.put("/{skill_id}/category", response_model=SkillCategoryAssignmentResult)
@authorize(privileges=Privileges.SKILL_EDIT)
async def assign_skill_category(
    skill_id: int,
    data: SkillCategoryAssignmentUpdate,
) -> SkillCategoryAssignmentResult:
    await _require_global_scope()
    try:
        skill, agent_ids = await skill_service.set_skill_category(
            skill_id,
            data.category_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Compétence ou catégorie introuvable") from exc
    return SkillCategoryAssignmentResult(
        skill=skill_service.to_public(skill),
        affected_agent_ids=agent_ids,
    )


@router.put(
    "/{skill_id}/authorization/global",
    response_model=SkillAuthorizationResult,
)
@authorize(privileges=Privileges.SKILL_ASSIGN)
async def update_global_authorization(
    skill_id: int,
    data: SkillGlobalAuthorizationUpdate,
    agent_id: int = Query(gt=0),
) -> SkillAuthorizationResult:
    try:
        await _require_global_scope()
        authorization, affected = await skill_service.set_global_authorization(
            skill_id, agent_id, data.state
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Compétence introuvable") from exc
    except ValueError as exc:
        raise _http_error(exc) from exc
    return SkillAuthorizationResult(
        **authorization.model_dump(),
        affected_agent_ids=affected,
    )


@router.put(
    "/{skill_id}/authorization/agents/{agent_id}",
    response_model=SkillAuthorizationResult,
)
@authorize(privileges=Privileges.SKILL_ASSIGN)
async def update_agent_authorization(
    skill_id: int,
    agent_id: int,
    data: SkillAuthorizationUpdate,
) -> SkillAuthorizationResult:
    try:
        scope = await current_management_scope()
        if not scope.allows(agent_id):
            raise HTTPException(status_code=404, detail="Agent introuvable")
        authorization = await skill_service.set_agent_authorization(
            skill_id, agent_id, data.state
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Compétence introuvable") from exc
    except ValueError as exc:
        raise _http_error(exc) from exc
    return SkillAuthorizationResult(
        **authorization.model_dump(),
        affected_agent_ids=(
            [agent_id]
            if skill_service.runtime_requires_skill_sync(authorization.agent_driver)
            else []
        ),
    )


@router.get("/{skill_id}/download")
@authorize(privileges=[Privileges.SKILL_ACCESS, Privileges.SKILL_EDIT, Privileges.SKILL_ASSIGN])
async def download_skill(skill_id: int) -> FileResponse:
    record = await _record(skill_id)
    try:
        archive = storage.create_zip(record.code)
    except (ValueError, OSError, FileNotFoundError) as exc:
        raise _http_error(exc) from exc
    return FileResponse(
        archive,
        media_type="application/zip",
        filename=f"{record.code}.zip",
        background=BackgroundTask(archive.unlink, missing_ok=True),
    )


@router.get("/{skill_id}/files", response_model=list[SkillFile])
@authorize(privileges=[Privileges.SKILL_ACCESS, Privileges.SKILL_EDIT, Privileges.SKILL_ASSIGN])
async def list_skill_files(skill_id: int) -> list[SkillFile]:
    record = await _record(skill_id)
    try:
        return [SkillFile(**item) for item in storage.list_files(record.code)]
    except (ValueError, OSError, FileNotFoundError) as exc:
        raise _http_error(exc) from exc


@router.get("/{skill_id}/content", response_model=SkillFileContent)
@authorize(privileges=[Privileges.SKILL_ACCESS, Privileges.SKILL_EDIT, Privileges.SKILL_ASSIGN])
async def read_skill_file(skill_id: int, path: str) -> SkillFileContent:
    record = await _record(skill_id)
    try:
        content = storage.read_text(record.code, path)
        resolved = storage.resolve_file(record.code, path)
    except (ValueError, OSError, FileNotFoundError) as exc:
        raise _http_error(exc) from exc
    return SkillFileContent(path=path, content=content, size=resolved.stat().st_size)


@router.get("/{skill_id}/file")
@authorize(privileges=[Privileges.SKILL_ACCESS, Privileges.SKILL_EDIT, Privileges.SKILL_ASSIGN])
async def download_skill_file(skill_id: int, path: str) -> FileResponse:
    record = await _record(skill_id)
    try:
        resolved = storage.resolve_file(record.code, path)
        if not resolved.is_file():
            raise FileNotFoundError(path)
    except (ValueError, OSError, FileNotFoundError) as exc:
        raise _http_error(exc) from exc
    return FileResponse(resolved, filename=Path(path).name)
