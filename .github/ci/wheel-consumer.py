from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import json
import os
import runpy
import subprocess
import sys
import zipfile
from pathlib import Path


def installed_identity(root: Path, wheel: Path) -> dict[str, str]:
    distribution = importlib.metadata.distribution("agents-memory")
    direct = json.loads(distribution.read_text("direct_url.json") or "null")
    if not isinstance(direct, dict) or direct.get("url") != wheel.as_uri() or "dir_info" in direct:
        raise RuntimeError("The consumer did not install the exact wheel artifact")
    package = importlib.import_module("agents_memory")
    if package.__file__ is None:
        raise RuntimeError("The wheel package has no installed source location")
    installed = Path(package.__file__).resolve(strict=True).parent
    if not installed.is_relative_to(Path(sys.prefix).resolve()) or installed.is_relative_to(root):
        raise RuntimeError("The consumer imported editable or foreign project source")
    with zipfile.ZipFile(wheel) as archive:
        members = [name for name in archive.namelist()
                   if name.startswith("agents_memory/") and name.endswith(".py")]
        if not members or len(members) != len(set(members)):
            raise RuntimeError("The wheel product module inventory is missing or duplicated")
        digests = {}
        for member in members:
            raw = archive.read(member)
            if ((installed / member.removeprefix("agents_memory/")).read_bytes() != raw
                    or (root / "src" / member).read_bytes() != raw):
                raise RuntimeError("Installed product, wheel and exact checkout bytes differ")
            digests[member] = hashlib.sha256(raw).hexdigest()
    return digests


def main() -> int:
    parser = argparse.ArgumentParser(description="Exercise the built wheel in GitHub Actions, not editable source")
    parser.add_argument("--result-dir", type=Path, required=True)
    parser.add_argument("--installed-wheel", type=Path)
    parser.add_argument("--health-only", action="store_true")
    parser.add_argument("--test-paths-json", help="Explicit changed-path installed-consumer regressions")
    parser.add_argument("--health-changes-only", action="store_true")
    args = parser.parse_args()
    if os.environ.get("GITHUB_ACTIONS") != "true":
        parser.error("This consumer gate is GitHub Actions-only")
    if os.environ.get("PYTEST_ADDOPTS"):
        parser.error("Inherited pytest selectors or reporters are not accepted")
    helpers = runpy.run_path(str(Path(__file__).with_name("run-tests.py")))
    try:
        selected_paths = helpers["parse_paths"](args.test_paths_json, tests=True)
    except (OSError, ValueError):
        parser.error("Changed-path selectors must name bounded, nonoverlapping repository tests")
    if (args.health_only and args.health_changes_only) or (
            (args.health_only or args.health_changes_only) and selected_paths is not None):
        parser.error("Health smoke and explicit regression selection are separate consumers")
    root = Path(__file__).resolve().parents[2]
    os.chdir(root)
    args.result_dir.mkdir(parents=True, exist_ok=True)
    if Path(sys.prefix).resolve() != Path(os.environ["UV_PROJECT_ENVIRONMENT"]).resolve(strict=True):
        raise RuntimeError("The consumer must use the owned frozen CI environment")
    if args.installed_wheel is None:
        wheels = list((root / "dist").glob("*.whl"))
        if len(wheels) != 1:
            raise RuntimeError("Exactly one built wheel is required")
        wheel = wheels[0].resolve(strict=True)
        subprocess.run(["uv", "pip", "install", "--python", sys.executable,
                        "--reinstall", "--no-deps", "--link-mode", "copy", str(wheel)], check=True, timeout=60)
        os.execv(sys.executable, [sys.executable, "-I", str(Path(__file__).resolve()),
                                 "--result-dir", str(args.result_dir.resolve()),
                                 "--installed-wheel", str(wheel),
                                 *(["--health-only"] if args.health_only else []),
                                 *(["--health-changes-only"] if args.health_changes_only else []),
                                 *(["--test-paths-json", json.dumps(selected_paths, separators=(",", ":"))]
                                   if selected_paths is not None else [])])
    wheel = args.installed_wheel.resolve(strict=True)
    if not sys.flags.isolated:
        raise RuntimeError("The installed consumer must use isolated Python")
    modules = installed_identity(root, wheel)
    if args.health_only or args.health_changes_only:
        helper = runpy.run_path(str(Path(__file__).with_name("run-evaluation.py")))
        return helper["health_smoke"](
            args.result_dir.resolve(), "installed", hashlib.sha256(wheel.read_bytes()).hexdigest(),
            changes_only=args.health_changes_only,
        )
    import pytest

    selectors = selected_paths if selected_paths is not None else runpy.run_path(
        str(Path(__file__).with_name("aggregate.py")))["WHEEL_SELECTORS"]
    shard = helpers["Shard"](0, 1)
    output = args.result_dir / "wheel-consumer.json"
    before = helpers["source_digest"]()
    result = {"schema": 1, "complete": False, "tested_sha": os.environ["CI_TESTED_SHA"],
              "source_before": before, "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
              "installed_module_count": len(modules), "installed_modules": modules, "pytest_exit_code": None}
    if selected_paths is not None:
        result["scope"] = {"kind": "changes", "selectors": selected_paths}
    helpers["write_result"](output, result)
    try:
        code = int(pytest.main(["-q", *selectors], plugins=[shard]))
        counts = shard.counts()
        result.update(pytest_exit_code=code, counts=counts, selected_nodeids=shard.selected,
                      reports=shard.reports, collection_issues=shard.collection_issues,
                      source_after=helpers["source_digest"]())
        result["complete"] = (code == 0 and before == result["source_after"]
                              and bool(shard.selected) and not shard.collection_issues
                              and set(shard.reports) == set(shard.selected)
                              and counts["passed"] == len(shard.selected))
        return 0 if result["complete"] else code or 1
    finally:
        helpers["write_result"](output, result)
        helpers["write_junit"](args.result_dir / "wheel-consumer-junit.xml", shard)


if __name__ == "__main__":
    raise SystemExit(main())
