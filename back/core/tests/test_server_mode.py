import pytest
from core.server_mode import validate_worker_count


@pytest.mark.parametrize('args', [['uvicorn', 'main:app'], ['uvicorn', '--workers', '1'], ['python', 'script.py']])
def test_supported_topology(args, monkeypatch):
    monkeypatch.setenv('WEB_CONCURRENCY', '4')
    validate_worker_count(args)


@pytest.mark.parametrize('args', [['uvicorn', '--workers=2'], ['uvicorn', '--workers', '2'], ['uvicorn', '--workers=2', '--workers=1']])
def test_unsupported_worker_topology_is_explicit(args):
    with pytest.raises(ValueError, match='one Uvicorn worker'):
        validate_worker_count(args)


def test_backend_entrypoint_pins_one_worker_despite_legacy_environment(tmp_path, monkeypatch):
    import json
    import os
    from pathlib import Path
    import subprocess
    import sys

    # Stub database convergence and the server, while exercising the real entrypoint
    # and topology validator. This never starts services or accesses a database.
    python = tmp_path / 'python'
    python.write_text(f'#!{sys.executable}\nimport runpy, sys\nif sys.argv[1:3] == ["-m", "core.server_mode"]:\n    sys.argv = ["core.server_mode", *sys.argv[3:]]\n    runpy.run_module("core.server_mode", run_name="__main__")\n')
    python.chmod(0o755)
    uvicorn = tmp_path / 'uvicorn'
    uvicorn.write_text(f'#!{sys.executable}\nimport json, os, sys\nprint(json.dumps({{"args": sys.argv[1:], "env": os.getenv("WEB_CONCURRENCY")}}))\n')
    uvicorn.chmod(0o755)
    monkeypatch.setenv('PATH', f'{tmp_path}:{os.environ["PATH"]}')
    monkeypatch.setenv('APP_ENV', 'prod')
    monkeypatch.setenv('WEB_CONCURRENCY', '4')
    entrypoint = Path(__file__).resolve().parents[2] / 'entrypoint.sh'
    result = subprocess.run(['bash', str(entrypoint), 'uvicorn', 'main:app'], capture_output=True, text=True, check=True)
    invoked = json.loads(result.stdout)
    assert invoked['env'] is None
    assert invoked['args'][invoked['args'].index('--workers') + 1] == '1'
