"""Synthetic repository and scanner/registry boundaries; no external network."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import audit


class DependencyAuditTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.output = self.root / "report"
        self.repo.mkdir()
        self.output.mkdir()

    def file(self, path, content):
        destination = self.repo / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content)
        return destination

    def prepare(self):
        data = audit.inventory(self.root)
        audit.write_json(self.output / "inventory.json", data)
        return data

    def scan(self, findings=(), *, status=0, target="repo/front/package-lock.json"):
        audit.write_json(self.output / "scans.json", [{"name": "source", "report": "source.trivy.json", "exit_code": status}])
        audit.write_json(self.output / "source.trivy.json", {"Results": [{"Target": target, "Type": "npm", "Vulnerabilities": list(findings)}]})

    def report(self, **options):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            status = audit.report(self.root, self.output, options.pop("fail_on", "HIGH"), **options)
        return status, audit.read_json(self.output / "report.json")

    def test_discovery_covers_nested_locks_dev_tools_and_inline_sdk_pins(self):
        self.file("back/pyproject.toml", '[project]\ndependencies=["synthetic-api==1.0"]\n[dependency-groups]\ndev=["synthetic-tester==2.0"]\n')
        self.file("back/uv.lock", '''[[package]]
name="synthetic-api"
version="1.0"
source={registry="https://pypi.org/simple"}
[[package]]
name="synthetic-tester"
version="2.0"
source={registry="https://pypi.org/simple"}
''')
        self.file("nested/tool/package.json", '{"devDependencies":{"synthetic-build":"1.0.0"}}')
        self.file("nested/tool/package-lock.json", json.dumps({"lockfileVersion": 3, "packages": {
            "": {"devDependencies": {"synthetic-build": "1.0.0"}},
            "node_modules/synthetic-build": {"version": "1.0.0", "dev": True},
            "node_modules/synthetic-build/node_modules/child": {"version": "2.0.0", "dev": True},
        }}))
        self.file("sdk/Dockerfile", '''ARG BASE=example/synthetic:1.0
FROM ${BASE} AS build
COPY --from=example/synthetic-tool:2.0 /tool /tool
COPY --from=workspace_assets /asset /asset
RUN python -m pip install 'synthetic-sdk==3.0.0'
RUN npm install --global synthetic-runner@4.0.0
RUN git clone https://github.com/synthetic/sdk.git /sdk
FROM build AS final
''')
        self.file("sdk/requirements.txt", "synthetic-server[standard]==5.0.0 --hash=sha256:synthetic\n")
        data = self.prepare()
        self.assertEqual(data["errors"], [])
        names = {entry["name"]: entry for entry in data["packages"]}
        self.assertEqual(set(names), {"synthetic-api", "synthetic-tester", "synthetic-build", "child", "synthetic-sdk", "synthetic-runner", "synthetic-server"})
        self.assertTrue(names["synthetic-tester"]["development"])
        self.assertFalse(names["child"]["direct"])
        self.assertEqual({(item["kind"], item["current"]) for item in data["references"]}, {
            ("docker", "example/synthetic:1.0"), ("docker", "example/synthetic-tool:2.0"), ("github-source", "synthetic/sdk"),
        })
        for entry in data["manifests"]:
            if entry["packages"]:
                self.assertTrue((self.root / entry["target"]).is_file())

    def test_reports_all_severities_and_unfixed_findings_with_configurable_exit(self):
        self.prepare()
        findings = [{"PkgName": "synthetic-lib", "InstalledVersion": "1.0", "Severity": severity,
                     "VulnerabilityID": "SYNTHETIC-" + severity, "FixedVersion": "2.0" if severity == "MEDIUM" else ""}
                    for severity in ("LOW", "MEDIUM", "HIGH", "CRITICAL")]
        self.scan(findings)
        status, report = self.report(lookup=False)
        self.assertEqual(status, 1)
        self.assertEqual(report["summary"]["blocking"], 2)
        self.assertEqual(len(report["vulnerabilities"]), 4)
        self.assertIsNone(report["vulnerabilities"][-1]["fixed"])
        status, report = self.report(lookup=False, fail_on="CRITICAL")
        self.assertEqual(status, 1)
        self.assertEqual(report["summary"]["blocking"], 1)
        self.scan(findings[:2])
        self.assertEqual(self.report(lookup=False)[0], 0)
        self.assertEqual(self.report(lookup=False, fail_on="MEDIUM")[0], 1)

    def test_missing_new_project_coverage_and_bad_reports_are_incomplete(self):
        self.file("new/package.json", '{"dependencies":{"synthetic-lib":"1.0.0"}}')
        self.prepare()
        self.scan()
        self.assertEqual(self.report(lookup=False)[0], 2)
        self.file("new/package-lock.json", '{"lockfileVersion":3,"packages":{"node_modules/synthetic-lib":{"version":"1.0.0"}}}')
        self.prepare()
        status, report = self.report(lookup=False)
        self.assertEqual(status, 2)
        self.assertIn("not covered", " ".join(report["errors"]))
        self.scan(target="repo/new/package-lock.json")
        self.assertEqual(self.report(lookup=False)[0], 0)
        (self.output / "source.trivy.json").write_text('{}')
        self.assertEqual(self.report(lookup=False)[0], 2)
        self.scan([{"PkgName": "synthetic-lib", "InstalledVersion": "1", "VulnerabilityID": "SYNTHETIC-1", "Severity": "invalid"}])
        self.assertEqual(self.report(lookup=False)[0], 2)
        audit.write_json(self.output / "scans.json", [])
        self.assertEqual(self.report(lookup=False)[0], 2)

    def test_registry_outage_retains_vulnerabilities_and_produces_an_error_report(self):
        self.file("requirements.txt", "synthetic-lib==1.0\n")
        self.prepare()
        self.scan([{"PkgName": "synthetic-lib", "InstalledVersion": "1.0", "Severity": "HIGH", "VulnerabilityID": "SYNTHETIC-1"}], target="repo/requirements.txt")
        with patch.object(audit, "fetch_json", side_effect=RuntimeError("synthetic registry outage")):
            status, report = self.report()
        self.assertEqual(status, 2)
        self.assertEqual(report["summary"]["blocking"], 1)
        self.assertIn("synthetic registry outage", " ".join(report["errors"]))
        self.assertTrue((self.output / "summary.md").is_file())

    def test_scanner_failure_cannot_look_clean_and_does_not_discard_other_scans(self):
        self.prepare()
        self.scan(status=17)
        scans = audit.read_json(self.output / "scans.json")
        scans.append({"name": "image-0", "report": "image-0.trivy.json", "exit_code": 0})
        audit.write_json(self.output / "scans.json", scans)
        audit.write_json(self.output / "image-0.trivy.json", {"Results": [{"Target": "synthetic-os", "Vulnerabilities": [
            {"PkgName": "synthetic-system", "InstalledVersion": "1", "Severity": "CRITICAL", "VulnerabilityID": "SYNTHETIC-OS"}]}]})
        status, report = self.report(lookup=False)
        self.assertEqual(status, 2)
        self.assertEqual(report["vulnerabilities"][0]["id"], "SYNTHETIC-OS")
        self.assertIn("exit 17", report["errors"][0])

    def test_package_metadata_preserves_compatibility_information_and_scoped_names(self):
        with patch.object(audit, "fetch_json", return_value={"version": "3.0.0", "engines": {"node": ">=26"}}) as fetch:
            result = audit.latest_package(("npm", "@synthetic/worker"))
        self.assertIn("%40synthetic%2Fworker", fetch.call_args.args[0])
        self.assertEqual(result["engines"], {"node": ">=26"})
        with patch.object(audit, "fetch_json", return_value={"info": {"version": "2.0", "requires_python": ">=3.15"}}):
            self.assertEqual(audit.latest_package(("PyPI", "synthetic"))["requires_python"], ">=3.15")

    def test_latest_queries_cover_direct_and_vulnerable_packages_with_opt_in_full_inventory(self):
        self.file("front/package-lock.json", json.dumps({"lockfileVersion": 3, "packages": {
            "": {"dependencies": {"synthetic-app": "1.0.0"}},
            **{f"node_modules/{name}": {"version": "1.0.0"} for name in ("synthetic-app", "synthetic-child", "synthetic-unsafe")},
        }}))
        self.prepare()
        self.scan([{"PkgName": "synthetic-unsafe", "InstalledVersion": "1.0.0", "Severity": "HIGH", "VulnerabilityID": "SYNTHETIC-1"}])
        with patch.object(audit, "latest_package", return_value={"latest": "2.0.0"}) as lookup:
            status, report = self.report()
        self.assertEqual(status, 1)
        self.assertEqual({call.args[0][1] for call in lookup.call_args_list}, {"synthetic-app", "synthetic-unsafe"})
        self.assertEqual(report["summary"]["package_versions"], 3)
        self.assertIn("ALL_VERSIONS", next(item for item in report["packages"] if item["name"] == "synthetic-child")["version_lookup"])
        with patch.object(audit, "latest_package", return_value={"latest": "2.0.0"}) as lookup:
            self.report(all_versions=True)
        self.assertEqual(lookup.call_count, 3)

    def test_unexpected_registry_failure_is_incomplete_instead_of_losing_the_report(self):
        self.file("requirements.txt", "synthetic-lib==1.0\n")
        self.prepare()
        self.scan(target="repo/requirements.txt")
        with patch.object(audit, "latest_package", side_effect=OSError("synthetic socket failure")):
            status, report = self.report()
        self.assertEqual(status, 2)
        self.assertIn("OSError", report["errors"][0])

    def test_timestamped_metadata_cache_expires_and_forced_refresh_does_not_hide_failure(self):
        self.file("requirements.txt", "synthetic-lib==1.0\n")
        self.prepare()
        self.scan(target="repo/requirements.txt")
        cache = self.root / "metadata.json"
        with patch.object(audit, "latest_package", return_value={"latest": "2.0"}):
            self.assertEqual(self.report(metadata_cache=cache)[0], 0)
        with patch.object(audit, "latest_package", side_effect=OSError("synthetic outage")) as lookup:
            status, report = self.report(metadata_cache=cache)
            self.assertEqual(status, 0)
            self.assertTrue(report["packages"][0]["metadata_cached"])
            lookup.assert_not_called()
            self.assertEqual(self.report(metadata_cache=cache, refresh_versions=True)[0], 2)
        data = audit.read_json(cache)
        for value in data.values():
            value["fetched_at"] -= 3601
        audit.write_json(cache, data)
        with patch.object(audit, "latest_package", return_value={"latest": "3.0"}) as lookup:
            status, report = self.report(metadata_cache=cache)
            self.assertEqual(status, 0)
            self.assertEqual(report["packages"][0]["latest"], "3.0")
            self.assertFalse(report["packages"][0]["metadata_cached"])
            self.assertEqual(lookup.call_count, 1)
        # A concurrent run finishing later must not overwrite fresher registry metadata.
        newer = audit.read_json(cache)
        key = next(iter(newer))
        older = {key: {"fetched_at": newer[key]["fetched_at"] - 10, "value": {"latest": "obsolete"}}}
        audit.persist_cache(cache, older, "synthetic-concurrent")
        self.assertEqual(audit.read_json(cache)[key]["value"]["latest"], "3.0")
        cache.write_text('{"broken":"synthetic invalid cache entry"}')
        with patch.object(audit, "latest_package", return_value={"latest": "4.0"}):
            status, report = self.report(metadata_cache=cache)
        self.assertEqual(status, 0)
        self.assertEqual(report["packages"][0]["latest"], "4.0")


if __name__ == "__main__":
    unittest.main()
