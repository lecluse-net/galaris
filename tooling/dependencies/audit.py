"""Read-only dependency inventory, registry lookups and Trivy report aggregation.

Only public package metadata is fetched. No package is installed or imported.
The host wrapper provides a Git-visible snapshot, never the live application.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import fcntl
import hashlib
import html
import json
from pathlib import Path
import re
import sys
import threading
import time
import tomllib
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

SEVERITIES = ("UNKNOWN", "LOW", "MEDIUM", "HIGH", "CRITICAL")
PIN = re.compile(r"\b([A-Za-z0-9][A-Za-z0-9_.-]*)(?:\[[^\]]+\])?==([A-Za-z0-9_.+!-]+)")
NPM_PIN = re.compile(r"(?<![\w/])(@[\w.-]+/[\w.-]+|[\w.-]+)@(\d+\.\d+\.\d+(?:-[\w.-]+)?)\b")
_request_lock = threading.Lock()
_next_request: dict[str, float] = {}


def pace_request(host: str, delay: float = 0.25) -> None:
    with _request_lock:
        now = time.monotonic()
        allowed = max(now, _next_request.get(host, now))
        _next_request[host] = allowed + delay
    time.sleep(max(0, allowed - now))


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def dependency_name(requirement: str) -> str:
    match = re.match(r"[\w.-]+", requirement)
    return normalize(match[0]) if match else ""


def inventory(root: Path) -> dict:
    packages, manifests, references, gaps, errors = [], [], [], [], []
    generated = root / "generated"
    generated.mkdir(exist_ok=True)

    def package(ecosystem, name, version, source, **metadata):
        packages.append(dict(ecosystem=ecosystem, name=name, version=version, source=source, **metadata))

    def manifest(path, kind, target=None, count=0):
        manifests.append(dict(path=path, kind=kind, target=target, packages=count))

    for file in sorted((root / "repo").rglob("*")):
        if not file.is_file():
            continue
        source = file.relative_to(root / "repo").as_posix()
        target = file.relative_to(root).as_posix()
        try:
            if file.name == "uv.lock":
                lock = tomllib.loads(file.read_text())
                project_file = file.with_name("pyproject.toml")
                project = tomllib.loads(project_file.read_text()) if project_file.exists() else {}
                direct = {dependency_name(value) for value in project.get("project", {}).get("dependencies", [])}
                dev = {dependency_name(value) for group in project.get("dependency-groups", {}).values()
                       for value in group if isinstance(value, str)}
                count = 0
                for entry in lock.get("package", []):
                    origin = entry.get("source", {})
                    if "editable" in origin or "virtual" in origin:
                        continue
                    if origin.get("registry", "https://pypi.org/simple").rstrip("/") != "https://pypi.org/simple":
                        gaps.append(f"{source}: non-PyPI dependency {entry['name']}; registry update lookup excluded")
                        continue
                    if "git" in origin or "url" in origin:
                        gaps.append(f"{source}: external dependency {entry['name']}; inspect its built image")
                        continue
                    name = entry["name"]
                    package("PyPI", name, entry["version"], source, direct=normalize(name) in direct | dev,
                            development=normalize(name) in dev)
                    count += 1
                manifest(source, "uv", target, count)
            elif file.name in {"package-lock.json", "npm-shrinkwrap.json"}:
                lock = read_json(file)
                if lock.get("lockfileVersion") not in {2, 3}:
                    raise ValueError("Only npm lockfile versions 2 and 3 are supported")
                entries = lock["packages"]
                direct = {name for key in ("dependencies", "devDependencies", "optionalDependencies")
                          for name in entries.get("", {}).get(key, {})}
                count = 0
                for key, entry in entries.items():
                    if not key or entry.get("link"):
                        continue
                    name = entry.get("name") or key.rsplit("node_modules/", 1)[-1]
                    resolved = entry.get("resolved", "")
                    if resolved and not resolved.startswith("https://registry.npmjs.org/"):
                        gaps.append(f"{source}: external npm dependency {name}; public registry lookup excluded")
                        continue
                    package("npm", name, entry["version"], source, direct=key == f"node_modules/{name}" and name in direct,
                            development=bool(entry.get("dev")))
                    count += 1
                manifest(source, "npm", target, count)
            elif file.name.startswith("requirements") and file.suffix == ".txt":
                content = file.read_text()
                pins = PIN.findall(content)
                for name, version in pins:
                    package("PyPI", name, version, source, direct=True, development=False)
                lines = content.replace("\\\n", " ").splitlines()
                if any(line.strip() and not line.lstrip().startswith("#") and not PIN.match(line.strip()) for line in lines):
                    errors.append(f"{source}: requirements include unsupported constraints, includes or unpinned dependencies")
                if file.name != "requirements.txt":
                    copy = generated / hashlib.sha256(source.encode()).hexdigest()[:12] / "requirements.txt"
                    copy.parent.mkdir(parents=True, exist_ok=True)
                    copy.write_text(content)
                    target = copy.relative_to(root).as_posix()
                manifest(source, "requirements (direct only)", target, len(pins))
            elif file.name in {"package.json", "pyproject.toml"}:
                project = read_json(file) if file.suffix == ".json" else tomllib.loads(file.read_text())
                dependencies = any(project.get(key) for key in ("dependencies", "devDependencies", "optionalDependencies")) if file.suffix == ".json" else bool(project.get("project", {}).get("dependencies"))
                locks = ("package-lock.json", "npm-shrinkwrap.json") if file.suffix == ".json" else ("uv.lock",)
                if dependencies and not any(file.with_name(name).exists() for name in locks):
                    errors.append(f"{source}: dependencies declared without a supported lockfile")
                manifest(source, "manifest")
            elif file.name == "Dockerfile" or file.name.startswith("Dockerfile."):
                content = file.read_text().replace("\\\n", " ")
                args = dict(re.findall(r"^ARG\s+(\w+)=(\S+)", content, re.M))
                stages = set()
                for match in re.finditer(r"^FROM\s+(?:--platform=\S+\s+)?(\S+)(?:\s+AS\s+(\S+))?", content, re.M | re.I):
                    image, stage = match.groups()
                    image = re.sub(r"\$\{(\w+)\}", lambda value, defaults=args: defaults.get(value[1], value[0]), image)
                    if image.lower() not in stages and image != "scratch":
                        references.append(dict(kind="docker", source=source, current=image))
                    if stage:
                        stages.add(stage.lower())
                for image in re.findall(r"^COPY\s+.*?--from=(\S+)", content, re.M | re.I):
                    if image.lower() not in stages and ("/" in image or ":" in image):
                        references.append(dict(kind="docker", source=source, current=image))
                for repository in re.findall(r"https://github\.com/([\w.-]+/[\w.-]+?)\.git\b", content):
                    references.append(dict(kind="github-source", source=source, current=repository))
                    gaps.append(f"{source}: downloaded Git source {repository}; scan the built image for its resolved dependencies")
                python_pins = []
                node_pins = []
                for line in content.splitlines():
                    if not line.startswith("RUN "):
                        continue
                    if re.search(r"\b(pip|uv)\s+(?:pip\s+)?install\b", line):
                        python_pins.extend(PIN.findall(line))
                    if re.search(r"\b(npm\s+install|corepack\s+prepare)\b", line):
                        node_pins.extend(NPM_PIN.findall(line))
                if python_pins or node_pins:
                    folder = generated / hashlib.sha256(source.encode()).hexdigest()[:12]
                    folder.mkdir(exist_ok=True)
                    if python_pins:
                        scan = folder / "requirements.txt"
                        scan.write_text("\n".join(f"{name}=={version}" for name, version in python_pins) + "\n")
                        manifest(source, "Dockerfile Python pins (direct only)", scan.relative_to(root).as_posix(), len(python_pins))
                        for name, version in python_pins:
                            package("PyPI", name, version, source, direct=True, development=False)
                    if node_pins:
                        scan = folder / "package-lock.json"
                        write_json(scan, dict(name="audit-inline-pins", lockfileVersion=3, packages={
                            "": {"dependencies": dict(node_pins)},
                            **{f"node_modules/{name}": {"version": version} for name, version in node_pins},
                        }))
                        manifest(source, "Dockerfile npm pins (direct only)", scan.relative_to(root).as_posix(), len(node_pins))
                        for name, version in node_pins:
                            package("npm", name, version, source, direct=True, development=False)
                manifest(source, "container recipe")
            elif file.suffix in {".yaml", ".yml"} and (file.name.startswith("compose") or source.startswith(".github/workflows/")):
                content = file.read_text()
                for current in re.findall(r"^\s*image:\s*(.+?)\s*$", content, re.M):
                    current = current.strip().strip("\"'")
                    # Resolve public defaults, never load .env or Docker credentials.
                    current = re.sub(r"\$\{\w+:-([^}]+)\}", r"\1", current)
                    references.append(dict(kind="docker", source=source, current=current))
                for current in re.findall(r"\buses:\s*[\"']?([\w.-]+/[\w./-]+@[\w./-]+)", content):
                    references.append(dict(kind="github-action", source=source, current=current))
            elif file.suffix == ".sh" and source.startswith("bin/"):
                for current in re.findall(r"\b(?:aquasec/trivy|semgrep/semgrep):[\w.-]+", file.read_text()):
                    references.append(dict(kind="docker", source=source, current=current))
        except (ValueError, KeyError, TypeError) as exc:
            errors.append(f"{source}: invalid dependency declaration: {exc}")
    # Do not hide OS packages or transitive SDK dependencies behind a clean source scan.
    gaps.extend([
        "OS packages and dependencies installed by external SDK builds require built-image scans (IMAGES=...).",
        "requirements.txt and inline Dockerfile pins cover declared versions only, not unresolved transitive dependencies.",
        "Latest published versions are informational; Python/Node compatibility and declared ranges still need review.",
    ])
    references = list({(entry["kind"], entry["source"], entry["current"]): entry for entry in references}.values())
    fingerprint = hashlib.sha256()
    for path in sorted({entry["path"] for entry in manifests} | {entry["source"] for entry in references}):
        fingerprint.update(path.encode() + b"\0" + (root / "repo" / path).read_bytes() + b"\0")
    return dict(manifests=manifests, packages=packages, references=references, gaps=sorted(set(gaps)),
                errors=errors, dependencies_sha256=fingerprint.hexdigest())


def fetch_json(url: str):
    for attempt in range(3):
        pace_request(urlsplit(url).netloc)
        try:
            request = Request(url, headers={"User-Agent": "galaris-dependency-audit", "Accept": "application/json"})
            with urlopen(request, timeout=20) as response:
                return json.load(response)
        except HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt == 2:
                raise RuntimeError(f"registry HTTP {exc.code}") from None
            retry = exc.headers.get("Retry-After", "") if exc.headers else ""
            pause = min(60, int(retry)) if retry.isdigit() else 10 * (attempt + 1)
            with _request_lock:
                host = urlsplit(url).netloc
                _next_request[host] = max(_next_request.get(host, 0), time.monotonic() + pause)
        except (URLError, TimeoutError):
            if attempt == 2:
                raise RuntimeError("registry unavailable after three attempts") from None
            time.sleep(1)
    raise RuntimeError("registry unavailable")


def latest_package(key: tuple[str, str]) -> dict:
    ecosystem, name = key
    try:
        if ecosystem == "PyPI":
            data = fetch_json(f"https://pypi.org/pypi/{quote(name, safe='')}/json")
            version = data["info"]["version"]
            return dict(latest=version, requires_python=data["info"].get("requires_python"),
                        url=f"https://pypi.org/project/{quote(name, safe='')}/{quote(version, safe='')}/")
        data = fetch_json(f"https://registry.npmjs.org/{quote(name, safe='')}/latest")
        return dict(latest=data["version"], engines=data.get("engines", {}),
                    url=f"https://www.npmjs.com/package/{quote(name, safe='@/')}")
    except (RuntimeError, KeyError, ValueError) as exc:
        return dict(error=str(exc))


def latest_reference(key: tuple[str, str]) -> dict:
    kind, current = key
    try:
        if kind in {"github-action", "github-source"}:
            repository = "/".join(current.split("@", 1)[0].split("/")[:2])
            try:
                data = fetch_json(f"https://api.github.com/repos/{repository}/releases/latest")
                return dict(latest=data["tag_name"], url=data["html_url"])
            except RuntimeError as exc:
                if kind != "github-source" or str(exc) != "registry HTTP 404":
                    raise
                data = fetch_json(f"https://api.github.com/repos/{repository}/commits/HEAD")
                return dict(latest=data["sha"], url=data["html_url"], status="No published release; default-branch HEAD")
        if "$" in current or current.startswith("galaris-") or ":" not in current:
            return dict(status="local or variable image; supply its built image with IMAGES")
        tag_ref, _, digest = current.partition("@")
        image, tag = tag_ref.rsplit(":", 1)
        if image.startswith(("ghcr.io/", "mcr.microsoft.com/", "quay.io/")):
            return dict(status="external registry; supply its built image with IMAGES")
        if image.startswith("docker.io/"):
            image = image[len("docker.io/"):]
        if "/" not in image:
            image = "library/" + image
        if "." in image.split("/")[0]:
            return dict(status="external registry; supply its built image with IMAGES")
        data = fetch_json(f"https://hub.docker.com/v2/repositories/{image}/tags/{quote(tag, safe='')}")
        if not isinstance(data.get("digest"), str):
            raise ValueError("registry response has no tag digest")
        return dict(latest_digest=data["digest"], pinned_digest=digest or None,
                    digest_changed=bool(digest) and digest != data["digest"],
                    tag_updated=data.get("last_updated"), url=f"https://hub.docker.com/r/{image}/tags")
    except (RuntimeError, KeyError, ValueError) as exc:
        return dict(error=str(exc))


def lookups(keys, function, cache: dict, *, refresh=False) -> dict:
    values = {}
    now = time.time()
    remaining = []
    for key in keys:
        saved = cache.get(json.dumps(key))
        if (not refresh and isinstance(saved, dict) and isinstance(saved.get("fetched_at"), (int, float))
            and isinstance(saved.get("value"), dict) and "error" not in saved["value"]
            and 0 <= now - saved["fetched_at"] < 3600):
            values[key] = {**saved["value"], "metadata_fetched_at": saved["fetched_at"], "metadata_cached": True}
        else:
            remaining.append(key)
    with ThreadPoolExecutor(max_workers=12) as pool:
        pending = {pool.submit(function, key): key for key in remaining}
        for future in as_completed(pending):
            key = pending[future]
            try:
                values[key] = future.result()
            except Exception as exc:
                # The external boundary must not discard completed scan evidence.
                values[key] = dict(error=f"metadata lookup failed ({type(exc).__name__})")
            if "error" not in values[key]:
                fetched = time.time()
                cache[json.dumps(key)] = dict(fetched_at=fetched, value=values[key])
                values[key] = {**values[key], "metadata_fetched_at": fetched, "metadata_cached": False}
            if len(values) % 100 == 0:
                print(f"Registry metadata: {len(values)}/{len(keys)}", flush=True)
    return values


def load_scan(path: Path) -> dict:
    data = read_json(path)
    if not isinstance(data, dict) or not isinstance(data.get("Results"), list):
        raise ValueError("scanner report has no Results array")
    for entry in data["Results"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("Target"), str):
            raise ValueError("scanner result has no target")
        if not isinstance(entry.get("Vulnerabilities", []), list):
            raise ValueError("scanner vulnerabilities are not an array")
        for finding in entry.get("Vulnerabilities", []):
            if not isinstance(finding, dict) or not all(isinstance(finding.get(key), str) for key in (
                "PkgName", "InstalledVersion", "VulnerabilityID",
            )) or finding.get("Severity", "UNKNOWN") not in SEVERITIES:
                raise ValueError("scanner finding has an invalid identity or severity")
    return data


def persist_cache(path: Path, cache: dict, run: str) -> None:
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            current = read_json(path) if path.exists() else {}
            if not isinstance(current, dict):
                current = {}
        except (ValueError, OSError):
            current = {}
        for key, entry in cache.items():
            if not isinstance(entry, dict) or not isinstance(entry.get("fetched_at"), (int, float)) or not isinstance(entry.get("value"), dict):
                continue
            saved = current.get(key)
            if not isinstance(saved, dict) or not isinstance(saved.get("fetched_at"), (int, float)) or entry["fetched_at"] >= saved["fetched_at"]:
                current[key] = entry
        temporary = path.with_suffix(f".{run}.tmp")
        write_json(temporary, current)
        temporary.replace(path)


def report(root: Path, output: Path, fail_on: str, *, lookup=True, all_versions=False,
           metadata_cache: Path | None = None, refresh_versions=False) -> int:
    data = read_json(output / "inventory.json")
    errors = list(data["errors"])
    source_paths = {entry["target"]: entry["path"] for entry in data["manifests"] if entry["target"]}
    findings = []
    results = []
    scan_status = read_json(output / "scans.json")
    if not isinstance(scan_status, list) or not all(isinstance(scan, dict) and
        isinstance(scan.get("name"), str) and isinstance(scan.get("report"), str) and
        isinstance(scan.get("exit_code"), int) for scan in scan_status):
        errors.append("Invalid scanner status inventory")
        scan_status = []
    if sum(scan["name"] == "source" for scan in scan_status) != 1:
        errors.append("Exactly one source scan is required")
    for scan in scan_status:
        if scan["exit_code"] != 0:
            errors.append(f"{scan['name']}: scanner failed (exit {scan['exit_code']}); see its .log")
            continue
        try:
            result = load_scan(output / scan["report"])
        except (ValueError, OSError) as exc:
            errors.append(f"{scan['name']}: invalid scanner output: {exc}")
            continue
        for entry in result["Results"]:
            target = entry["Target"]
            source = source_paths.get(target.removeprefix("/snapshot/"), target)
            if scan["name"].startswith("image-"):
                image_name = output / f"{scan['name']}.name.txt"
                image = image_name.read_text().strip() if image_name.exists() else scan["name"]
                source = f"{image}: {target}"
            results.append(dict(scan=scan["name"], target=target, type=entry.get("Type")))
            for finding in entry.get("Vulnerabilities", []):
                findings.append(dict(scan=scan["name"], source=source, package=finding["PkgName"],
                    installed=finding["InstalledVersion"], severity=finding.get("Severity", "UNKNOWN"),
                    id=finding["VulnerabilityID"], title=finding.get("Title", ""),
                    fixed=finding.get("FixedVersion") or None, url=finding.get("PrimaryURL", "")))
    targets = {entry["target"].removeprefix("/snapshot/") for entry in results if entry["scan"] == "source"}
    for manifest in data["manifests"]:
        if manifest["packages"] and manifest["target"] not in targets:
            errors.append(f"{manifest['path']}: dependency file was not covered by the scanner")
    vulnerable = {normalize(finding["package"]) for finding in findings}
    keys = sorted({(entry["ecosystem"], entry["name"]) for entry in data["packages"]
                   if all_versions or entry["direct"] or normalize(entry["name"]) in vulnerable})
    reference_keys = sorted({(entry["kind"], entry["current"]) for entry in data["references"]})
    cache = {}
    if metadata_cache and metadata_cache.exists():
        try:
            cache = read_json(metadata_cache)
            if not isinstance(cache, dict):
                cache = {}
        except (ValueError, OSError):
            cache = {}
    metadata = lookups(keys, latest_package, cache, refresh=refresh_versions) if lookup else {}
    references = lookups(reference_keys, latest_reference, cache, refresh=refresh_versions) if lookup else {}
    if metadata_cache:
        try:
            persist_cache(metadata_cache, cache, output.name)
        except OSError:
            errors.append("Could not persist registry metadata cache")
    for key, value in list(metadata.items()) + list(references.items()):
        if "error" in value:
            errors.append(f"{key[0]} {key[1]}: {value['error']}")
    packages = []
    seen = set()
    for package in data["packages"]:
        key = (package["source"], package["ecosystem"], package["name"], package["version"])
        if key in seen:
            continue
        seen.add(key)
        key = (package["ecosystem"], package["name"])
        packages.append({**package, "version_lookup": "queried" if key in metadata else "transitive; use ALL_VERSIONS=1",
                         **metadata.get(key, {})})
    for reference in data["references"]:
        reference.update(references.get((reference["kind"], reference["current"]), {}))
    blocking = [finding for finding in findings if SEVERITIES.index(finding["severity"]) >= SEVERITIES.index(fail_on)]
    exit_code = 2 if errors else 1 if blocking else 0
    differing = sum(bool(package.get("latest")) and package["latest"] != package["version"] for package in packages)
    images = sum(scan["name"].startswith("image-") for scan in scan_status)
    summary = dict(generated_at=datetime.now(timezone.utc).isoformat(), exit_code=exit_code, fail_on=fail_on,
                   dependencies_sha256=data["dependencies_sha256"],
                   vulnerabilities=len(findings), blocking=len(blocking), errors=len(errors),
                   package_versions=len(packages), registry_packages=len(keys), images=images,
                   differing_versions=differing,
                   all_versions=all_versions,
                   by_severity={severity: sum(f["severity"] == severity for f in findings) for severity in SEVERITIES})
    write_json(output / "report.json", dict(summary=summary, manifests=data["manifests"], packages=packages,
        references=data["references"], vulnerabilities=findings, coverage=data["gaps"], errors=errors, scans=results))
    lines = ["# Dependency audit", "", f"UTC: {summary['generated_at']}", "",
        f"Dependency snapshot SHA256: `{data['dependencies_sha256']}`", "",
        f"Exit: **{exit_code}** (0: no findings at the selected threshold; 1: vulnerable; 2: incomplete).",
        f"Threshold: {fail_on}. Findings: {len(findings)}; blocking: {len(blocking)}; errors: {len(errors)}.",
        f"Package versions: {len(packages)}; differing published versions: {differing}; unique registry lookups: {len(keys)}; built image scans requested: {images}.", "",
        "## Vulnerabilities", "", "| Source | Package | Installed | Severity | Advisory | Fixed versions |",
        "|---|---|---|---|---|---|"]
    for finding in sorted(findings, key=lambda entry: (-SEVERITIES.index(entry["severity"]), entry["source"], entry["package"], entry["id"])):
        lines.append(row(finding["source"], finding["package"], finding["installed"], finding["severity"],
                         finding["id"] + " " + finding["url"], finding["fixed"] or "No published fix"))
    if not findings:
        lines.extend(["", "No vulnerabilities reported by the completed scans. Check coverage and errors below."])
    lines.extend(["", "## Published versions differing from locked versions", "",
        "Public registry metadata is cached for at most one hour; timestamps are retained in JSON. REFRESH_VERSIONS=1 bypasses it.",
        "Version lookups cover all packages." if all_versions else "Version lookups cover direct and vulnerable dependencies. Use ALL_VERSIONS=1 for every transitive package.",
        "Latest is not a compatibility recommendation. Full inventory, engine constraints and advisory links: `report.json`.", "",
        "| Source | Package | Locked | Latest published | Direct |", "|---|---|---|---|---|"])
    for package in packages:
        if package.get("latest") and package["latest"] != package["version"]:
            lines.append(row(package["source"], package["name"], package["version"], package["latest"], package["direct"]))
    lines.extend(["", "## Container and GitHub Action references", "",
        "Docker lookups compare the pinned digest with the current digest of the same tag, not another release series.", "",
        "| Source | Reference | Published release / digest / scope |", "|---|---|---|"])
    for reference in data["references"]:
        lines.append(row(reference["source"], reference["current"], reference.get("latest") or reference.get("latest_digest") or reference.get("status") or reference.get("error", "Not queried")))
    lines.extend(["", "## Coverage", "", "| File | Scope | Declared package versions |", "|---|---|---|"])
    lines.extend(row(entry["path"], entry["kind"], entry["packages"]) for entry in data["manifests"])
    lines.extend(["", *[f"- {escape(gap)}" for gap in data["gaps"]], "", "## Errors", ""])
    lines.extend([f"- {escape(error)}" for error in errors] or ["None."])
    (output / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Dependencies: {len(packages)} versions; differing published versions: {differing}; vulnerabilities: {len(findings)}; blocking: {len(blocking)}; errors: {len(errors)}")
    for finding in sorted(findings, key=lambda entry: -SEVERITIES.index(entry["severity"]))[:50]:
        print(f"{finding['severity']} {finding['id']} {finding['package']} {finding['installed']} -> {finding['fixed'] or 'no published fix'} ({finding['source']})")
    if len(findings) > 50:
        print(f"{len(findings) - 50} additional findings are retained in summary.md and report.json")
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    return exit_code


def escape(value) -> str:
    return html.escape(str(value)).replace("|", "&#124;").replace("\n", " ")


def row(*values) -> str:
    return "| " + " | ".join(escape(value) for value in values) + " |"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["inventory", "report"])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fail-on", choices=SEVERITIES, default="HIGH")
    parser.add_argument("--all-versions", action="store_true")
    parser.add_argument("--metadata-cache", type=Path)
    parser.add_argument("--refresh-versions", action="store_true")
    args = parser.parse_args()
    if args.operation == "inventory":
        write_json(args.output / "inventory.json", inventory(args.root))
        return 0
    return report(args.root, args.output, args.fail_on, all_versions=args.all_versions,
                  metadata_cache=args.metadata_cache, refresh_versions=args.refresh_versions)


if __name__ == "__main__":
    sys.exit(main())
