from unittest.mock import Mock

import pytest

from scripts import healthcheck


@pytest.mark.parametrize('status,exit_code', [(200, 0), (503, 1), (None, 1)])
def test_readiness_probe_always_checks_local_backend(monkeypatch, status, exit_code):
    monkeypatch.setenv('HEALTHCHECK_URL', 'https://obsolete.example.test/')
    connection = Mock()
    connection.getresponse.return_value = Mock(status=status, reason='test')
    if status is None:
        connection.request.side_effect = OSError('offline')
    factory = Mock(return_value=connection)
    monkeypatch.setattr(healthcheck.http.client, 'HTTPConnection', factory)
    with pytest.raises(SystemExit) as error:
        healthcheck.health_check()
    assert error.value.code == exit_code
    factory.assert_called_once_with('127.0.0.1', 8000, timeout=5)
    connection.request.assert_called_once_with('GET', '/api/health/ready')
    connection.close.assert_called_once()
