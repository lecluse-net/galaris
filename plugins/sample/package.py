"""Build reproducible signed ZIPs from a staged plugin directory."""

import argparse
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import re
from typing import cast
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def build(source: Path, key: Ed25519PrivateKey) -> bytes:
    manifest = cast(dict[str, object], json.loads((source / "manifest.json").read_text(encoding="utf-8")))
    files: dict[str, bytes] = {}
    contributions = manifest["contributions"]
    if not isinstance(contributions, list):
        raise ValueError("The manifest must declare a contribution list")
    for contribution in cast(list[dict[str, object]], contributions):
        code = contribution["code"]
        family = contribution["family"]
        if not isinstance(code, str):
            raise ValueError("Invalid contribution code")
        if family == "service_preset" and re.fullmatch(r"[a-z][a-z0-9-]*", code):
            entries = {"sha256": f"services/{code}.yaml"}
        elif family == "document_format" and re.fullmatch(r"[a-z][a-z0-9-]*(\.[a-z][a-z0-9-]*)+", code):
            entries = {"sha256": f"backend/{code}.py", "frontend_sha256": f"frontend/{code}.mjs"}
        elif family in {"llm_provider", "preview_converter", "file_share_protocol"} and re.fullmatch(r"[a-z][a-z0-9-]*(\.[a-z][a-z0-9-]*)+", code):
            entries = {"sha256": f"backend/{code}.py"}
        elif family == "data_template" and re.fullmatch(r"[a-z][a-z0-9-]*(\.[a-z][a-z0-9-]*)+", code):
            entries = {"sha256": f"data/{code}.json"}
        else:
            raise ValueError("Unsupported contribution family or code")
        for field, path in entries.items():
            if path in files:
                raise ValueError("Duplicate contribution file")
            content = (source / path).read_bytes()
            files[path] = content
            contribution[field] = sha256(content).hexdigest()
    encoded = json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode()
    files["manifest.json"] = encoded
    files["manifest.sig"] = key.sign(encoded)
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        for path, content in sorted(files.items()):
            archive.writestr(ZipInfo(path), content, compress_type=ZIP_DEFLATED)
    return output.getvalue()


def read_key(path: Path) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("An Ed25519 private key is required")
    return key


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for action in ("init-key", "public-key", "build", "sign-index"):
        subcommand = commands.add_parser(action)
        subcommand.add_argument("key", type=Path)
        if action in {"build", "sign-index"}:
            subcommand.add_argument("source", type=Path)
            subcommand.add_argument("output", type=Path)
    args = parser.parse_args()
    key_path = cast(Path, args.key)
    if args.command == "init-key":
        key = Ed25519PrivateKey.generate()
        pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        with os.fdopen(os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as writer:
            writer.write(pem)
    elif args.command == "public-key":
        print(read_key(key_path).public_key().public_bytes_raw().hex())
    elif args.command == "sign-index":
        body = cast(Path, args.source).read_bytes()
        cast(Path, args.output).write_bytes(read_key(key_path).sign(body))
    else:
        cast(Path, args.output).write_bytes(build(cast(Path, args.source), read_key(key_path)))


if __name__ == "__main__":
    main()
