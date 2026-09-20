"""Measure connection acquisition, including queueing, connect and pre-ping."""

from time import perf_counter

import logfire
from sqlalchemy.exc import TimeoutError as PoolTimeout
from sqlalchemy.pool import AsyncAdaptedQueuePool, PoolProxiedConnection

_acquisition = logfire.metric_histogram("db_pool_acquisition_seconds", unit="s")


class ObservedAsyncPool(AsyncAdaptedQueuePool):
    def connect(self) -> PoolProxiedConnection:
        started = perf_counter()
        outcome = "error"
        try:
            connection = super().connect()
            outcome = "acquired"
            return connection
        except PoolTimeout:
            outcome = "timeout"
            raise
        finally:
            _acquisition.record(perf_counter() - started, {"outcome": outcome})
