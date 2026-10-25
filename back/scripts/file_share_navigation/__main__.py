import argparse
import json
from pathlib import Path

from .analysis import report
from .corpus import generate


parser = argparse.ArgumentParser(description="Synthetic File Share navigation experiment")
parser.add_argument("operation", choices=("generate", "report"))
parser.add_argument("directory", type=Path)
parser.add_argument("--phase", choices=("pilot", "decision"), default="pilot")
parser.add_argument("--repetitions", type=int, default=5)
args = parser.parse_args()
if args.operation == "generate":
    manifest = generate(args.directory, phase=args.phase, repetitions=args.repetitions)
    print(json.dumps(dict(corpus_sha256=manifest["corpus_sha256"], runs=len(manifest["runs"]))))
else:
    print(json.dumps(report(args.directory), ensure_ascii=False))
