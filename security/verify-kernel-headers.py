"""Verify the artifact-specific premise of the reviewed SSH kernel VEX statements."""

import json
from pathlib import Path
import subprocess


def query(*arguments: str) -> str:
    return subprocess.run(
        ["dpkg-query", *arguments], check=True, capture_output=True, text=True,
    ).stdout


def main() -> None:
    package = "linux-libc-dev"
    headers = 0
    for name in query("-L", package).splitlines():
        path = Path(name)
        if path.is_dir():
            continue
        resolved = path.resolve(strict=True)
        header = resolved.is_relative_to("/usr/include") and resolved.suffix == ".h"
        documentation = resolved.is_relative_to(f"/usr/share/doc/{package}")
        if not (header or documentation):
            raise SystemExit(f"Unexpected kernel-header package payload: {path}")
        if resolved.stat().st_mode & 0o111 or resolved.read_bytes()[:4] == b"\x7fELF":
            raise SystemExit(f"Executable payload in kernel-header package: {path}")
        headers += int(header)
    if not headers:
        raise SystemExit("Kernel-header package has no verified headers")
    for row in query("-W", "-f=${binary:Package} ${db:Status-Status}\n").splitlines():
        name, status = row.split()
        if status == "installed" and name.startswith((
            "linux-image", "linux-modules", "linux-objects", "linux-source", "linux-headers",
        )):
            raise SystemExit(f"Kernel implementation package present: {name}")
    for root in (Path("/boot"), Path("/lib/modules"), Path("/usr/lib/modules")):
        if root.exists() and any(path.is_file() for path in root.rglob("*")):
            raise SystemExit(f"Kernel implementation payload present: {root}")
    print(json.dumps({
        "package": package,
        "version": query("-W", "-f=${Version}", package),
        "verified_headers": headers,
        "kernel_payload_present": False,
    }))


if __name__ == "__main__":
    main()
