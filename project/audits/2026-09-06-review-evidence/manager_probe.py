import asyncio
import importlib.util
import os
import sys
import tempfile
from pathlib import Path
from cryptography.fernet import Fernet

os.environ['HARNESS_MANAGER_SECRET'] = Fernet.generate_key().decode()
os.environ['BASE_DIR'] = '/tmp/audit-unused'
spec = importlib.util.spec_from_file_location('audit_manager', '/repo/harness_manager/main.py')
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

async def main():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        module.BASE_DIR = base
        instance = base / 'demo'
        instance.mkdir()
        folder = instance / 'shared'
        folder.mkdir()
        (folder / 'file.txt').write_text('allowed')
        outside = base / 'outside-instance'
        outside.mkdir()
        (outside / 'file.txt').write_text('outside-private-canary')
        response = module.download_raw('demo', 'shared/file.txt')
        folder.rename(instance / 'previous')
        folder.symlink_to(outside, target_is_directory=True)
        received = b''.join([chunk async for chunk in response.body_iterator])
        assert received == b'outside-private-canary'
        assert response.headers['content-length'] == '7'
        print('CONFIRMED: deferred download opens outside instance after directory symlink swap')
        print('CONFIRMED: announced length=7, actual length=' + str(len(received)))

asyncio.run(main())
