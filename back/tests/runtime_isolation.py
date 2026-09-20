"""Keep automated test telemetry local without changing APP_ENV semantics."""

from contextlib import contextmanager
from unittest.mock import patch

import logfire


@contextmanager
def isolated_api_import():
    logfire.configure(
        send_to_logfire=False,
        distributed_tracing=False,
        console=False,
        inspect_arguments=False,
    )
    with (
        patch("core.observability.configure_observability"),
        patch("core.observability.instrument_fastapi"),
    ):
        yield
