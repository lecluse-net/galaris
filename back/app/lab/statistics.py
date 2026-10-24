"""Descriptive uncertainty over case clusters, never over individual repetitions."""

from math import isfinite, log, sqrt
from random import Random
from statistics import fmean

from pydantic import BaseModel


class CaseEstimate(BaseModel):
    cases: int
    observations: int
    mean: float | None = None
    lower: float | None = None
    upper: float | None = None
    confidence: float = 0.95
    method: str = "case-cluster-percentile-bootstrap/v1"
    resamples: int = 2000
    sufficient: bool = False


def estimate(clusters: list[list[float]], *, bounds: tuple[float, float] | None = None) -> CaseEstimate:
    """Give each source case equal weight; keep its repeated measurements together.

    Intervals describe this sampled corpus with this judge. Twenty source cases is
    a reporting floor, not evidence that synthetic examples are independent or
    representative. A fixed seed makes the read-only report reconstructible.
    """
    valid = [values for values in clusters if values and all(isfinite(v) for v in values)]
    samples = sorted(fmean(values) for values in valid)
    result = CaseEstimate(cases=len(samples), observations=sum(len(values) for values in valid),
                          mean=fmean(samples) if samples else None, sufficient=len(samples) >= 20)
    if bounds is not None:
        result.method = "case-cluster-hoeffding/v1"
        result.resamples = 0
    if len(samples) < 2:
        return result
    if bounds is not None:
        radius = (bounds[1] - bounds[0]) * sqrt(log(40) / (2 * len(samples)))
        result.lower = max(bounds[0], fmean(samples) - radius)
        result.upper = min(bounds[1], fmean(samples) + radius)
        return result
    random = Random(0)
    draws = sorted(fmean(random.choices(samples, k=len(samples))) for _ in range(result.resamples))
    result.lower = draws[49]
    result.upper = draws[1949]
    return result
