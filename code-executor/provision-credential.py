"""Initialize a private control-plane credential without application secrets."""

import os
from pathlib import Path
import secrets

root = Path("/run/galaris-code")
root.mkdir(parents=True, exist_ok=True)
os.chown(root, 0, 19997)
os.chmod(root, 0o750)
path = root / "token"
try:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o440)
except FileExistsError:
    if len(path.read_text().strip()) < 32:
        raise RuntimeError("Invalid code runtime credential")
else:
    with os.fdopen(descriptor, "w") as target:
        target.write(secrets.token_urlsafe(48))
os.chown(path, 0, 19997)
os.chmod(path, 0o440)
