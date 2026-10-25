"""Generate immutable inputs; keep answers and run controls outside the candidate."""

from __future__ import annotations

import hashlib
import json
import random
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import NAMESPACE_URL, uuid5


def uri(path: str) -> str:
    return "fixture://" + quote(path, safe="/")


def save(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def source_hash() -> str:
    package = Path(__file__).parent
    backend = package.parents[1]
    paths = [*package.glob("*.py"), *backend.glob("*.py")]
    for directory in ("app", "core", "bridge"):
        paths.extend((backend / directory).rglob("*.py"))
    return hashlib.sha256(
        b"".join(p.relative_to(backend).as_posix().encode() + p.read_bytes() for p in sorted(paths))
    ).hexdigest()


def generate(root: Path, *, phase: str, repetitions: int = 5) -> dict[str, Any]:
    if root.exists():
        raise FileExistsError("Use a new campaign directory; frozen inputs are never overwritten")
    if phase not in {"pilot", "decision"} or not 1 <= repetitions <= 10:
        raise ValueError("Invalid phase or repetition count")
    root.mkdir(parents=True)
    corpus = root / "corpus"
    cases: list[dict[str, Any]] = []

    def put(path: str, content: str | bytes) -> str:
        target = corpus / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode() if isinstance(content, str) else content)
        return uri(path)

    def case(name: str, family: str, question: str, answer: dict[str, Any]) -> None:
        cases.append(dict(id=name, family=family, question=question, expected=answer))

    for prefix in ("pilot", "holdout"):
        for number in range(8):
            put(
                f"{prefix}/archive/{number}/note.txt",
                f"batch=archive-{number}\nvalue=unused-{number}\n",
            )
    pilot_uri = put("pilot/current/note.txt", "batch=current\nvalue=PV-7391\n")
    case(
        "pilot_find",
        "discovery",
        "Find the current pilot batch value under pilot/. Return {uri, value}.",
        dict(uri=pilot_uri, value="PV-7391"),
    )
    pilot_tail = put("pilot/reading.txt", "pilot filler\n" * 2100 + "final_value=PT-2846\n")
    case(
        "pilot_read",
        "reading",
        "Read pilot/reading.txt through its end. Return {uri, final_value}.",
        dict(uri=pilot_tail, final_value="PT-2846"),
    )
    found = put("holdout/current/approved/note.txt", "batch=approved-current\nvalue=HV-4917\n")
    case(
        "nested",
        "discovery",
        "Find the approved current batch under holdout/. Return {uri, value}.",
        dict(uri=found, value="HV-4917"),
    )
    unicode = put("names/Équipe été/東京 compte rendu.txt", "approval=UN-6825\n")
    put("names/Equipe ete/東京 compte rendu.txt", "approval=draft\n")
    case(
        "unicode",
        "names",
        "Read the Tokyo report inside the exact folder names/Équipe été/. Return {uri, approval}.",
        dict(uri=unicode, approval="UN-6825"),
    )
    close = put("names/report final.txt", "version=approved\ncode=NF-9372\n")
    put("names/report final old.txt", "version=old\ncode=obsolete\n")
    put("names/report-final.txt", "version=draft\ncode=draft\n")
    case(
        "similar",
        "names",
        "Read exactly names/report final.txt. Return {uri, code}.",
        dict(uri=close, code="NF-9372"),
    )
    tail = put("reading/ledger.txt", "intermediate entry\n" * 3600 + "final_value=LT-5318\n")
    case(
        "tail",
        "reading",
        "Read reading/ledger.txt through its end. Return {uri, final_value}.",
        dict(uri=tail, final_value="LT-5318"),
    )
    first = put("cross/order.txt", "quantity=174\n")
    second = put("cross/receipt.txt", "quantity=169\n")
    case(
        "cross",
        "crossing",
        "Compare cross/order.txt and cross/receipt.txt. Return {order_uri, receipt_uri, ordered, received, difference}.",
        dict(order_uri=first, receipt_uri=second, ordered=174, received=169, difference=5),
    )
    inventory: list[str] = []
    for number in range(507):
        path = f"pagination/entry-{number:04}.txt"
        put(path, f"value={number * 3 + 7}\n")
        inventory.append(uri(path))
    case(
        "pagination",
        "pagination",
        "List EVERY entry directly inside pagination/. Return {count, last_uri}, where last_uri is the lexicographically last canonical file URI. Continue any listing pages.",
        dict(count=len(inventory), last_uri=inventory[-1]),
    )
    tasks: list[tuple[str, str, str]] = []
    for number, (date, status) in enumerate(
        (("2026-01-01", "SUCCESS"), ("2026-02-01", "ERROR"), ("2026-03-01", "EXEC"))
    ):
        task_uri = (
            f"galaris://task/{uuid5(NAMESPACE_URL, 'synthetic-navigation-task-' + str(number))}"
        )
        resource = put(
            f"tasks/{task_uri.rsplit('/', 1)[1]}.json",
            json.dumps(dict(uri=task_uri, created_at=date, status=status)),
        )
        tasks.append((resource, task_uri, status))
    case(
        "task",
        "business",
        "Read the synthetic Task snapshots under tasks/. Find the one with the latest created_at. Return {source_uri, task_uri, status}.",
        dict(source_uri=tasks[-1][0], task_uri=tasks[-1][1], status=tasks[-1][2]),
    )
    for surface in ("mail", "messenger"):
        for parent, value in (("previous", "obsolete"), ("approved", f"{surface.upper()}-8293")):
            put(
                f"{surface}/{parent}/message.json",
                json.dumps(dict(subject="shipment", state=parent)),
            )
            attachment = put(f"{surface}/{parent}/attachments/report.txt", f"code={value}\n")
        case(
            surface,
            "attachments",
            f"Under {surface}/ find the report.txt attached to the message whose state is approved. Return {{uri, code}}.",
            dict(uri=attachment, code=f"{surface.upper()}-8293"),
        )
    binary = put("binary/signature.bin", b"\x89PNG\r\n\x1a\n")
    case(
        "binary",
        "binary",
        "Inspect binary/signature.bin. Return {uri, format, bytes}, using format PNG if the signature matches PNG.",
        dict(uri=binary, format="PNG", bytes=8),
    )
    put(
        "faults/README.txt",
        "unavailable.txt cannot be retrieved. interrupted/ enumeration is unavailable. Report incomplete results explicitly.\n",
    )
    (corpus / "faults/interrupted").mkdir()
    case(
        "unavailable",
        "failure",
        "Read faults/unavailable.txt. If it cannot be read, return {uri, complete:false}; never invent its content.",
        dict(uri=uri("faults/unavailable.txt"), complete=False),
    )
    case(
        "interrupted",
        "failure",
        "Enumerate faults/interrupted/ completely. If enumeration fails, return {uri, complete:false}; an inaccessible directory is not an empty collection.",
        dict(uri=uri("faults/interrupted/"), complete=False),
    )
    records = [
        {
            "path": p.relative_to(corpus).as_posix(),
            "bytes": p.stat().st_size,
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        }
        for p in sorted(corpus.rglob("*"))
        if p.is_file()
    ]
    digest = hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest()
    frozen_time = datetime(2026, 4, 1, tzinfo=timezone.utc).timestamp()
    for path in [*corpus.rglob("*"), corpus]:
        os.utime(path, (frozen_time, frozen_time))
    selected = cases[:2] if phase == "pilot" else cases[2:]
    runs: list[dict[str, Any]] = []
    # Order is frozen before any candidate result exists, alternating within pairs.
    rng = random.Random(24791)
    for repeat in range(repetitions):
        for item in selected:
            arms = ["mcp", "filesystem"]
            rng.shuffle(arms)
            for arm in arms:
                runs.append(
                    dict(
                        id=f"{item['id']}-r{repeat + 1}-{arm}",
                        case=item["id"],
                        arm=arm,
                        repetition=repeat + 1,
                        question=item["question"],
                    )
                )
    manifest = dict(
        version=1,
        synthetic=True,
        phase=phase,
        repetitions=repetitions,
        corpus_sha256=digest,
        files=records,
        cases=selected,
        runs=runs,
        clock="2026-04-01T00:00:00Z",
        reasoning_effort="none",
        temperature=0,
        limits=dict(
            max_iterations=12,
            max_seconds=180,
            max_completion_tokens=2048,
            max_campaign_tokens=8_000_000,
        ),
        decision=dict(
            success_gain=0.10,
            cost_reduction=0.20,
            noninferiority_margin=0.05,
            confidence=0.95,
            bootstrap_samples=10000,
            bootstrap_seed=75231,
            second_campaign=False,
        ),
    )
    save(root / "manifest.json", manifest)
    # Controlled EACCES is identical to the provider's injected listing failure.
    (corpus / "faults/interrupted").chmod(0)
    return manifest
