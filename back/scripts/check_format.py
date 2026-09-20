"""One formatting scope shared by Make and CI."""

import subprocess
import sys
from pathlib import Path

targets = Path(__file__).with_name("format_targets.txt").read_text().splitlines()
raise SystemExit(subprocess.call(["ruff", "format", *sys.argv[1:], *targets]))
