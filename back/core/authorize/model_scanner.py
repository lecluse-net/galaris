"""
Model Scanner for RBAC Resource Rules.

Scans SQLAlchemy models decorated with @authorize(target="resource")
and auto-registers their rules in the RuleProvider.
"""

from __future__ import annotations

from typing import Any, List, Type

from loguru import logger

from core.database import Base
from .resource_rules import RuleProvider


def scan_models(rule_provider: RuleProvider) -> int:
    """
    Scan all SQLAlchemy models (subclasses of Base) for _authorize_rules
    and register them in the RuleProvider.

    Returns the number of rules registered.

    This is called by AuthorizeService.start() at application startup.
    """
    count = 0

    # Walk all subclasses of Base (recursively)
    for model_class in _get_all_subclasses(Base):
        rules = getattr(model_class, "_authorize_rules", None)
        if not rules:
            continue

        resource_type = model_class.__name__
        for rule in rules:
            rule_provider.add(resource_type, rule)
            count += 1
            logger.debug(
                f"ModelScanner: registered rule for {resource_type} "
                f"(privileges={rule.privileges}, assertion={rule.assertion})"
            )

    logger.info(f"ModelScanner: registered {count} resource rules from models")
    return count


def _get_all_subclasses(cls: Type[Any]) -> List[Type[Any]]:
    """Recursively get all subclasses of a class."""
    result: List[Type[Any]] = []
    for subclass in cls.__subclasses__():
        result.append(subclass)
        result.extend(_get_all_subclasses(subclass))
    return result
