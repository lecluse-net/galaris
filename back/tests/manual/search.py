"""Opt-in public search probe. Availability is not a relevance verdict."""

import argparse
import asyncio
import json
from app.util import SearchClient, SearchConnectionError, SearchRequestError

# Synthetic public queries only; never replay application conversations here.
CASES = (
    ("Lyon musée beaux-arts", "fr"),
    ("Python asyncio documentation", "en"),
    ("photosynthèse chlorophylle", "fr"),
    ("Köln Dom Architektur", "de"),
)


async def probe(client: SearchClient) -> int:
    """Report partial sources too; return 1 for missing coverage, 2 for degradation."""
    missing = degraded = False
    for query, language in CASES:
        report: dict[str, object] = {"query": query, "language": language}
        try:
            response = await client.asearch_response(query, language=language, max_results=5)
            report.update(
                status="degraded" if response.degraded else "available" if response.results else "empty",
                unavailable_engines=response.unavailable_engine_count,
                discarded_results=response.discarded_result_count,
                sources=[{"title": r.title, "url": r.url, "engine": r.engine} for r in response.results],
            )
            missing |= not response.results
            degraded |= response.degraded
        except (SearchConnectionError, SearchRequestError) as exc:
            report.update(status="failed", reason=str(exc))
            missing = True
        print(json.dumps(report, ensure_ascii=False))
    return 1 if missing else 2 if degraded else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", help="Search endpoint of an isolated comparison instance")
    args = parser.parse_args()
    client = SearchClient()
    if args.url:
        client.url = args.url
    raise SystemExit(asyncio.run(probe(client)))


if __name__ == "__main__":
    main()
