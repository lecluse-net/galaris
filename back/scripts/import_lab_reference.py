"""Install the public reference corpus through authenticated Lab HTTP contracts.

Run in the backend container with LAB_ACCESS_TOKEN and --install. No model is called.
Existing datasets with the same name are refused, never overwritten.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

CORPUS = Path(__file__).parents[1] / "app/lab/reference_corpus.json"


async def install(client: httpx.AsyncClient) -> dict[str, Any]:
    corpus = json.loads(CORPUS.read_text())
    prefix = f"/api/evaluation/{corpus['mechanism']}"
    existing = await client.get(f"{prefix}/datasets")
    existing.raise_for_status()
    if any(row["name"] == corpus["name"] for row in existing.json()):
        raise ValueError("Reference dataset already exists; keep its captured evidence or rename it explicitly.")
    response = await client.post(f"{prefix}/datasets", json={
        key: corpus[key] for key in ("name", "description", "purpose")
    })
    response.raise_for_status()
    dataset = response.json()
    response = await client.patch(f"{prefix}/datasets/{dataset['id']}", json={
        "revision": dataset["revision"], "name": dataset["name"],
        "purpose": corpus["purpose"], "parameters": corpus["parameters"],
    })
    response.raise_for_status()
    for case in corpus["cases"]:
        response = await client.post(f"{prefix}/datasets/{dataset['id']}/cases", json={"name": case["name"]})
        response.raise_for_status()
        saved = response.json()
        response = await client.patch(f"{prefix}/cases/{saved['id']}", json={
            "revision": saved["revision"], **case,
        })
        response.raise_for_status()
    return {"dataset_id": dataset["id"], "cases": len(corpus["cases"]), "model_calls": 0}


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    if not args.install:
        print(CORPUS.read_text())
        return
    base_url = str(args.base_url)
    address = urlparse(base_url)
    if address.scheme != "https" and not (
        address.scheme == "http" and address.hostname in {"localhost", "127.0.0.1", "::1"}
    ):
        parser.error("Use HTTPS or a loopback HTTP address for authenticated import")
    token = os.environ.get("LAB_ACCESS_TOKEN")
    if not token:
        parser.error("LAB_ACCESS_TOKEN must contain an authorized user's access token")
    async with httpx.AsyncClient(
        base_url=base_url, headers={"Authorization": f"Bearer {token}"}, timeout=30,
    ) as client:
        print(json.dumps(await install(client)))


if __name__ == "__main__":
    asyncio.run(main())
