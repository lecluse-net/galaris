"""Generate, validate and score a corpus in an isolated standard-library container."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .generate import export, generate
from .io import json_records, load, record
from .score import STAGES, observations, score
from .validate import validate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("generate", help="Build a new entirely fictional corpus")
    build.add_argument("--output", type=Path, default=Path("/output/corpus-v1"))
    build.add_argument("--seed", type=int, default=1847)
    build.add_argument("--repetitions", type=int, default=5)
    build.add_argument("--distractors", type=int, default=200)
    build.add_argument("--profiles", nargs="*", default=[])
    check = commands.add_parser("validate", help="Check checksums, coverage and oracle consistency")
    check.add_argument("corpus", type=Path)
    merge = commands.add_parser("aggregate", help="Merge complete real-engine database partitions")
    merge.add_argument("corpus", type=Path)
    merge.add_argument("campaign", type=Path)
    merge.add_argument("--output", type=Path, required=True)
    merge.add_argument("--expected-queries", type=int, help="Explicitly allow a complete-world subset of this size")
    evaluate = commands.add_parser("score", help="Score ranked IDs produced by a real engine adapter")
    evaluate.add_argument("corpus", type=Path)
    evaluate.add_argument("observations", type=Path)
    evaluate.add_argument("--output", type=Path, required=True)
    evaluate.add_argument("--k", type=int, default=8)
    evaluate.add_argument("--label", default="unlabelled-external-observations")
    evaluate.add_argument("--splits", nargs="*", choices=("development", "validation", "heldout"), default=[])
    evaluate.add_argument("--stages", nargs="*", choices=STAGES, default=[])
    args = parser.parse_args()
    try:
        if args.command == "generate":
            corpus = generate(seed=args.seed, repetitions=args.repetitions, distractors=args.distractors,
                              profile_keys=tuple(args.profiles))
            summary = validate(corpus)
            export(corpus, args.output, seed=args.seed, repetitions=args.repetitions, distractors=args.distractors)
            summary["output"] = str(args.output)
        elif args.command == "validate":
            summary = validate(load(args.corpus))
        elif args.command == "aggregate":
            from .aggregate import aggregate

            summary = aggregate(args.corpus, args.campaign, args.output, expected_queries=args.expected_queries)
        else:
            output = Path(args.output)
            if output.exists() or output.is_symlink():
                raise ValueError("Report output must be a new directory")
            report, results = score(load(args.corpus), observations(json_records(args.observations)),
                                    k=args.k, splits=tuple(args.splits), stages=tuple(args.stages))
            report["provenance"] = {
                "label": str(args.label),
                "corpus_manifest_sha256": hashlib.sha256((args.corpus / "manifest.json").read_bytes()).hexdigest(),
                "observations_sha256": hashlib.sha256(args.observations.read_bytes()).hexdigest(),
            }
            output.mkdir(parents=True)
            (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            with (output / "per-query.jsonl").open("w", encoding="utf-8") as stream:
                for result in results:
                    stream.write(json.dumps(asdict(result), ensure_ascii=False) + "\n")
            summary = {"output": str(output), "queries": report["query_count"], "stages": list(record(report["stages"]))}
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, KeyError, OSError) as error:
        print(f"Benchmark error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
