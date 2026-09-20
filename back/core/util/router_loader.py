"""Compose optional routers without hiding broken active modules."""

import importlib
import importlib.util

from fastapi import APIRouter, FastAPI
from loguru import logger

from modules import MODULES


def include_routers(app: FastAPI | APIRouter) -> None:
    for module_name in MODULES:
        router_module_name = f"{module_name}.router"
        if importlib.util.find_spec(router_module_name) is None:
            logger.debug("Module {} exposes no API router", module_name)
            continue
        router_module = importlib.import_module(router_module_name)
        router = getattr(router_module, "router", None)
        if router is None:
            # Some bridges compose named routers explicitly in main.py.
            logger.debug("Module {} has no default router", module_name)
            continue
        app.include_router(router)
        logger.debug("Included router from {}", router_module_name)
