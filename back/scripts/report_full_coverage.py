"""Report every backend domain, including sources never imported by the tests."""

from pathlib import Path
import json
from defusedxml.ElementTree import parse

from coverage import Coverage

from scripts.check_critical_coverage import Domain, measure


def domain_config(xml: Path) -> dict[str, Domain]:
    domains: dict[str, Domain] = {}
    root = parse(xml).getroot()
    assert root is not None
    for row in root.findall(".//class"):
        if not row.findall("./lines/line"):
            continue
        filename = row.attrib["filename"].removeprefix("back/")
        parts = filename.split("/")
        # Infrastructure files such as core/runtime.py share a distinct core root.
        prefix = "/".join(parts[:2]) + "/" if len(parts) > 2 else filename
        domains.setdefault(prefix, Domain(prefixes=[prefix], line_min=0, branch_min=0))
    if not domains:
        raise ValueError("The full coverage report contains no production sources")
    return domains


def report(xml: Path, output: Path) -> None:
    counts, _ = measure(xml, domain_config(xml))
    rows = {
        name: {
            "lines": round(row.line_percent, 2),
            "branches": round(row.branch_percent, 2),
            "line_count": row.lines,
            "missing_lines": row.lines - row.covered,
            "branch_count": row.branches,
            "missing_branches": row.branches - row.covered_branches,
        }
        for name, row in sorted(counts.items())
    }
    output.write_text(json.dumps({"scope": "all backend core/app/bridge sources", "domains": rows}, indent=2) + "\n")
    for name, row in sorted(rows.items(), key=lambda item: -item[1]["missing_branches"]):
        print(f"{name}: lines {row['lines']:.2f}%, branches {row['branches']:.2f}%, "
              f"{row['missing_branches']} missing branches")


def main() -> None:
    artifacts = Path("/repo/artifacts")
    full = Coverage(config_file="coverage-all.ini")
    full.load()
    full.xml_report(outfile=str(artifacts / "coverage-full.xml"))
    full.html_report(directory=str(artifacts / "coverage-html"))
    report(artifacts / "coverage-full.xml", artifacts / "coverage-full.json")
    # Use the same execution data for the original critical selection and floors.
    critical = Coverage(config_file="coverage-critical.ini")
    critical.load()
    critical.xml_report(outfile=str(artifacts / "coverage.xml"), include=critical.config.run_include)
    percent = critical.report(include=critical.config.run_include)
    if percent < critical.config.fail_under:
        raise SystemExit(f"Critical coverage {percent:.2f}% is below {critical.config.fail_under}%")


if __name__ == "__main__":
    main()
