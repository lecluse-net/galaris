"""OpenRouter usage-cost extraction."""

from __future__ import annotations

import math
from typing import Any

from core.util import as_dict


def _amount(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    return amount if math.isfinite(amount) and amount >= 0 else None


class OpenRouterUsageAccounting:
    """Prefer the amount charged for the routed request.

    OpenRouter publishes ``usage.cost`` for the customer charge and may additionally expose
    ``cost_details.upstream_inference_cost``. The latter remains a useful fallback for payload
    variants that omit the aggregate field.
    """

    def inference_cost(self, usage: dict[str, Any]) -> float | None:
        charged = _amount(usage.get("cost"))
        if charged is not None:
            return charged
        details = as_dict(usage.get("cost_details"))
        return _amount(details.get("upstream_inference_cost"))


__all__ = ["OpenRouterUsageAccounting"]
