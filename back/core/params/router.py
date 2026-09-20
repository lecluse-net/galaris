from fastapi import APIRouter, HTTPException, status
from pydantic import ValidationError
from core.authorize import authorize
from core.authorize import Privileges
from core.i18n import render_prompt, tr
from .schemas import (
    ParamListItem,
    ParamUpdate,
    ParamUpdateResponse,
    ParamsListResponse,
    PromptParamMetadata,
)
from . import params_service

from loguru import logger

router = APIRouter(prefix="/params", tags=["params"])


async def _not_found(name: str) -> str:
    return render_prompt(await tr("params_api.errors.not_found"), name=name)


async def _prompt_metadata(
    name: str,
    value: str | None,
    based_on_digest: object,
) -> PromptParamMetadata | None:
    if not params_service.is_prompt(name):
        return None
    current_digest = params_service.prompt_default_digest(name)
    stored_digest = based_on_digest if isinstance(based_on_digest, str) else None
    return PromptParamMetadata(
        default_value=await params_service.declared_default(name) or "",
        customized=value is not None,
        default_changed=(
            value is not None
            and stored_digest is not None
            and stored_digest != current_digest
        ),
    )


@router.get("", response_model=ParamsListResponse)
@authorize(privileges=[Privileges.PARAMS_ACCESS, Privileges.PARAMS_EDIT])
async def read_params():
    """Return all parameter names and values.

    The frontend owns translated labels and descriptions indexed by name.
    """
    logger.info("Listing application parameters")
    params = await params_service.get_all_with_metadata()

    params_list: list[ParamListItem] = []
    for param in params:
        if params_service.is_internal(param.name):
            continue
        secret = params_service.is_secret(param.name)
        revealed = params_service.reveal(param.name, param.value)
        prompt = await _prompt_metadata(
            param.name,
            revealed,
            getattr(param, "default_digest", None),
        )
        params_list.append(
            ParamListItem(
                name=param.name,
                value=(
                    None
                    if secret
                    else await params_service.value_for_display(param.name, revealed)
                ),
                secret=secret,
                configured=bool(revealed),
                prompt=prompt,
            )
        )

    return ParamsListResponse(params=params_list)

@router.put("/{name}", response_model=ParamUpdateResponse, status_code=status.HTTP_200_OK)
@authorize(privileges=Privileges.PARAMS_EDIT)
async def update_param(
    name: str,
    param_update: ParamUpdate,
) -> ParamUpdateResponse:
    """Update an existing parameter value.

    Args:
        name: Parameter name.
        param_update: Request containing the new value.
    """
    logger.info("Updating parameter {}", name)

    if params_service.is_internal(name) or not await params_service.has(name):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=await _not_found(name),
        )

    secret = params_service.is_secret(name)
    if param_update.prompt_action is not None and not params_service.is_prompt(name):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="prompt_action is only valid for prompt parameters",
        )
    if secret and param_update.value is None and not param_update.clear_secret:
        current = await params_service.get(name)
        return ParamUpdateResponse(
            status="success",
            name=name,
            value=None,
            secret=True,
            configured=bool(current),
        )

    requested_value = None if param_update.clear_secret else param_update.value
    if param_update.prompt_action == "use_default":
        requested_value = None
    elif param_update.prompt_action == "keep_custom":
        requested_value = await params_service.get(name)
    try:
        success = await params_service.set(name, requested_value)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=await _not_found(name),
        )

    saved_value = params_service.normalize(name, requested_value)
    if (
        params_service.is_prompt(name)
        and saved_value == await params_service.declared_default(name)
    ):
        saved_value = None
    prompt = await _prompt_metadata(
        name,
        saved_value,
        params_service.prompt_default_digest(name),
    )
    return ParamUpdateResponse(
        status="success",
        name=name,
        value=(
            None
            if secret
            else await params_service.value_for_display(name, saved_value)
        ),
        secret=secret,
        configured=bool(saved_value),
        prompt=prompt,
    )
