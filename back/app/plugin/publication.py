"""Stage a signed catalogue locally from independently qualified declarative releases."""

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated, Literal, cast

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from pydantic import Field, HttpUrl, StringConstraints, field_validator

from .bundles import MAX_UPLOAD_BYTES, read_bundle
from .contracts import Digest, ManifestModel
from .remote_catalog import CatalogueIndex, CatalogueRelease, MAX_INDEX_BYTES, SIGNATURE_BYTES, verify_signed_index

MAX_RELEASES = 128
MAX_QUALIFICATION_BYTES = 16 * 1024
type QualificationCheck = Literal["bundle", "compatibility", "permissions", "localization", "lifecycle"]


class ReleaseQualification(ManifestModel):
    format_version: Literal[1]
    digest: Digest
    source_repository: HttpUrl
    source_commit: Annotated[str, StringConstraints(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")]
    report_digest: Digest
    checks: Annotated[list[QualificationCheck], Field(min_length=5, max_length=5)]

    @field_validator("source_repository")
    @classmethod
    def https_source(cls, value: HttpUrl) -> HttpUrl:
        if value.scheme != "https" or value.username or value.password or value.query or value.fragment:
            raise ValueError("A public HTTPS source repository is required")
        return value

    @field_validator("checks")
    @classmethod
    def distinct_checks(cls, value: list[QualificationCheck]) -> list[QualificationCheck]:
        if len(set(value)) != 5:
            raise ValueError("All qualification checks are required")
        return value


@dataclass(frozen=True, slots=True)
class _QualifiedBytes:
    archive: bytes
    attestation: bytes
    signature: bytes


def _read(path: Path, limit: int) -> bytes:
    with path.open("rb") as source:
        data = source.read(limit + 1)
    if not data or len(data) > limit:
        raise ValueError(f"Missing or oversized publication input: {path.name}")
    return data


def _qualify(
    content: bytes, release: CatalogueRelease, attestation: Path, signature: Path, key: Ed25519PublicKey,
) -> _QualifiedBytes:
    if release.manifest.executable:
        raise ValueError("The public catalogue accepts declarative plugins only")
    if release.signer == sha256(key.public_bytes_raw()).hexdigest():
        raise ValueError("A publisher cannot qualify its own release")
    proof = _read(attestation, MAX_QUALIFICATION_BYTES)
    signed = _read(signature, SIGNATURE_BYTES)
    key.verify(signed, proof)
    if ReleaseQualification.model_validate_json(proof).digest != release.digest:
        raise ValueError("Qualification must name the approved archive digest")
    return _QualifiedBytes(content, proof, signed)


def stage_catalogue(
    candidates: Path, output: Path, catalogue_key: Ed25519PrivateKey, qualification_key: Ed25519PublicKey,
    *, previous: Path | None = None, revoke: tuple[str, ...] = (),
) -> CatalogueIndex:
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    if catalogue_key.public_key().public_bytes_raw() == qualification_key.public_bytes_raw():
        raise ValueError("Catalogue and qualification authorities must use different keys")
    published = None
    if previous is not None:
        published = verify_signed_index(
            _read(previous / "index.sig", SIGNATURE_BYTES) + _read(previous / "index.json", MAX_INDEX_BYTES),
            catalogue_key.public_key().public_bytes_raw(),
        )
    releases = {item.digest: item for item in published.releases} if published else {}
    revoked = set(revoke)
    if published is not None:
        revoked.update(published.revoked)
    paths = list(candidates.glob("*.zip"))
    if len(paths) > MAX_RELEASES:
        raise ValueError("Too many archives in the publication staging area")
    qualified: dict[str, _QualifiedBytes] = {}
    for path in sorted(paths):
        content = _read(path, MAX_UPLOAD_BYTES)
        bundle = read_bundle(content)
        if bundle.digest in revoked:
            raise ValueError("Qualification must name the approved, non-revoked archive digest")
        release = CatalogueRelease(manifest=bundle.manifest, signer=bundle.signer, digest=bundle.digest)
        qualified[bundle.digest] = _qualify(
            content, release, path.with_suffix(".qualification.json"), path.with_suffix(".qualification.sig"), qualification_key,
        )
        releases[bundle.digest] = release

    now = datetime.now(timezone.utc)
    if published is not None and now < published.issued_at:
        raise ValueError("Publication time precedes the previous signed index")
    index = CatalogueIndex(
        format_version=1, sequence=published.sequence + 1 if published else 1,
        issued_at=now, expires_at=now + timedelta(days=1), releases=list(releases.values()), revoked=sorted(revoked),
    )
    body = index.model_dump_json().encode()
    if len(body) > MAX_INDEX_BYTES:
        raise ValueError("Signed catalogue exceeds the reader's size limit")
    with TemporaryDirectory(dir=output.parent, prefix=".plugin-catalogue-") as staging:
        root = Path(staging) / "catalogue"
        archives = root / "archives"
        attestations = root / "qualification"
        archives.mkdir(parents=True)
        attestations.mkdir()
        for item in index.releases:
            if item.digest in revoked:
                continue
            name = f"{item.digest}.zip"
            verified = qualified.get(item.digest)
            if verified is None:
                assert previous is not None
                content = _read(previous / "archives" / name, MAX_UPLOAD_BYTES)
                bundle = read_bundle(content)
                if (bundle.digest, bundle.signer, bundle.manifest) != (item.digest, item.signer, item.manifest):
                    raise ValueError("Previous archive differs from the signed catalogue")
                verified = _qualify(content, item, previous / "qualification" / f"{item.digest}.json",
                                    previous / "qualification" / f"{item.digest}.sig", qualification_key)
            (archives / name).write_bytes(verified.archive)
            (attestations / f"{item.digest}.json").write_bytes(verified.attestation)
            (attestations / f"{item.digest}.sig").write_bytes(verified.signature)
        (root / "index.json").write_bytes(body)
        (root / "index.sig").write_bytes(catalogue_key.sign(body))
        root.rename(output)
    return index


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidates", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--catalogue-key", required=True, type=Path, help="Ed25519 private key in PEM format")
    parser.add_argument("--qualification-key", required=True, type=Path, help="Ed25519 public key in raw hexadecimal form")
    parser.add_argument("--previous", type=Path, help="Previous signed catalogue directory")
    parser.add_argument("--revoke", action="append", default=[], help="Archive digest to revoke")
    args = parser.parse_args()
    key = load_pem_private_key(_read(cast(Path, args.catalogue_key), 4096), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("The catalogue key must be Ed25519")
    qualification_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(
        _read(cast(Path, args.qualification_key), 128).decode("ascii").strip(),
    ))
    stage_catalogue(cast(Path, args.candidates), cast(Path, args.output), key, qualification_key,
                    previous=cast(Path | None, args.previous), revoke=tuple(cast(list[str], args.revoke)))


if __name__ == "__main__":
    main()
