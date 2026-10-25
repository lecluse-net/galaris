"""Read a configured development model once; stdout is a private pipe, never a log."""

import asyncio
import json
import logging
import sys
from typing import Any

from loguru import logger


async def capture(code: str) -> dict[str, Any]:
    from core.settings import settings
    from core.database import get_db_session, load_models
    from app.llm import llm_service, llm_provider_service

    if not settings.is_dev:
        raise RuntimeError("Campaign credentials may only be read in development")
    load_models()
    async with get_db_session():
        llm = await llm_service.get_llm_by_code(code)
        if llm is None or not llm.provider.is_active or llm.provider.deleted_at is not None:
            raise ValueError("Select an active configured development model")
        if (
            llm.provider.provider_type != "openai_compatible"
            or "openrouter.ai" not in llm.provider.base_url
        ):
            raise ValueError("This campaign requires a metered OpenRouter Chat Completions model")
        provider = await llm_provider_service.get_provider_with_decrypted_key(llm.llm_provider_id)
        if provider is None or not provider[1]:
            raise ValueError("Model credentials unavailable")
        return dict(
            code=llm.code,
            model=llm.llm_name,
            base_url=llm.provider.base_url,
            api_key=provider[1],
            upstream=sys.argv[2],
        )


if __name__ == "__main__":
    logger.remove()
    logging.disable(logging.CRITICAL)
    try:
        value = asyncio.run(capture(sys.argv[1]))
    except Exception as error:
        print(
            type(error).__name__ + ": development model configuration unavailable", file=sys.stderr
        )
        raise SystemExit(1) from None
    print(json.dumps(value))
