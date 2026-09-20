
"""
Logging setup and authentication helpers.
"""

import sys
import logging
from typing import Any
from loguru import logger
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from core import settings
from core.secrets import auth_secret_key
from core.i18n import t
import logfire

security = HTTPBearer()

# Redirect standard-library, Uvicorn, and FastAPI logs to Loguru.
class InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        # Resolve the matching Loguru level.
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Walk the stack to find the original caller.
        frame, depth = logging.currentframe(), 2
        while frame is not None and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())

def setup_logging() -> None:
    # Replace default handlers to avoid duplicate Uvicorn output.
    logging.root.handlers = [InterceptHandler()]
    logging.root.setLevel(logging.INFO)

    # Propagate every known logger to Loguru.
    for name in logging.root.manager.loggerDict.keys():
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True

    # Reduce noisy httpx long-poll request logs.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # Configure Loguru.
    logger.remove()
    
    # Format JSON
    # logger.add(sys.stdout, format="{time} {level} {message}", level="INFO", serialize=True)
    
    # Human-readable development format; production can later opt into JSON.
    logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level=settings.LOG_LEVEL
    )

    # Keep the local console sink and mirror the same structured records to
    # Logfire when a token is configured. In test mode Logfire is explicitly
    # local-only, so test output never leaves the process.
    logger.add(
        logfire.LogfireLoggingHandler(fallback=logging.NullHandler()),
        level=settings.LOG_LEVEL,
    )
    
    logger.info(f"Logging configured for {settings.APP_NAME}")


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict[str, Any]:
    """
    Verify a bearer token and return its JWT payload.
    """
    
    token = credentials.credentials
    try:
        payload = jwt.decode(token, auth_secret_key(), algorithms=[settings.ALGORITHM])  # type: ignore
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=t("user_api.errors.invalid_or_expired_token"),
            headers={"WWW-Authenticate": "Bearer"},
        )
