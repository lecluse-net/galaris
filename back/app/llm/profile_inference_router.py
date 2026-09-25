"""Profile discovery and specialized endpoints outside conversational protocols."""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from core.authorize import independent_auth
from core.i18n import tr
from .call_router import authenticate_llm_api
from .decision_contracts import DecisionResult
from .profile_gateway import profile_models
from .profile_inference import (
    ProfileDecisionRequest, ProfileEmbeddingRequest, profile_decision, profile_embeddings,
)
from .provider_facade import ProviderAuthenticationError
from .schemas import ProxyModelList


router = APIRouter(prefix="/profile", tags=["Profile inference"])


async def _standalone_auth(request: Request) -> None:
    if await authenticate_llm_api(request) is not None:
        raise HTTPException(status_code=403, detail=await tr("llm_api.errors.inference_runtime_required"))


@router.get("/models", response_model=ProxyModelList)
@independent_auth(reason="User with LLM_API_ACCESS or managed-runtime token")
async def models(request: Request) -> ProxyModelList:
    await authenticate_llm_api(request)
    return ProxyModelList(data=await profile_models(("chat", "embedding", "decision")))


@router.post("/openai/embeddings")
@independent_auth(reason="User with LLM_API_ACCESS; standalone embedding inference")
async def embeddings(request: Request, body: ProfileEmbeddingRequest) -> JSONResponse:
    await _standalone_auth(request)
    try:
        payload, call_id = await profile_embeddings(body)
        return JSONResponse(payload, headers={"X-Galaris-LLM-Call-Id": call_id})
    except ProviderAuthenticationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/decisions", response_model=DecisionResult)
@independent_auth(reason="User with LLM_API_ACCESS; standalone decision inference")
async def decisions(request: Request, body: ProfileDecisionRequest) -> DecisionResult:
    await _standalone_auth(request)
    try:
        return await profile_decision(body)
    except ProviderAuthenticationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
