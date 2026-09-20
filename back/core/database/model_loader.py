"""Load the complete declarative schema of every active module."""

import importlib
import importlib.util

from loguru import logger


def load_models() -> None:
    from modules import MODULES

    for module_name in MODULES:
        models_module_name = f"{module_name}.models"
        if importlib.util.find_spec(models_module_name) is None:
            continue
        # Broken imports must propagate: partial metadata could drop live tables.
        importlib.import_module(models_module_name)
        logger.debug("Loaded models from {}", models_module_name)
