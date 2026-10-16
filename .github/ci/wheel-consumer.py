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


def main() -> int:
    parser = argparse.ArgumentParser(description="Exercise the built wheel in GitHub Actions, not editable source")
    parser.add_argument("--result-dir", type=Path, required=True)
    parser.add_argument("--installed-wheel", type=Path)
    args = parser.parse_args()
    if os.environ.get("GITHUB_ACTIONS") != "true":
        parser.error("This consumer gate is GitHub Actions-only")
    if os.environ.get("PYTEST_ADDOPTS"):
        parser.error("Inherited pytest selectors or reporters are not accepted")
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
                        "--reinstall", "--no-deps", str(wheel)], check=True, timeout=60)
        os.execv(sys.executable, [sys.executable, "-I", str(Path(__file__).resolve()),
                                 "--result-dir", str(args.result_dir.resolve()),
                                 "--installed-wheel", str(wheel)])
    wheel = args.installed_wheel.resolve(strict=True)
    distribution = importlib.metadata.distribution("agents-memory")
    direct = json.loads(distribution.read_text("direct_url.json") or "null")
    if not isinstance(direct, dict) or direct.get("url") != wheel.as_uri() or "dir_info" in direct:
        raise RuntimeError("The consumer did not install the exact wheel artifact")
    package = importlib.import_module("agents_memory")
    module_file = package.__file__
    if module_file is None:
        raise RuntimeError("The wheel package has no installed source location")
    installed = Path(module_file).resolve(strict=True).parent
    if not installed.is_relative_to(Path(sys.prefix).resolve()) or installed.is_relative_to(root):
        raise RuntimeError("The consumer imported editable or foreign project source")
    with zipfile.ZipFile(wheel) as archive:
        members = [name for name in archive.namelist()
                   if name.startswith("agents_memory/") and name.endswith(".py")]
        if not members:
            raise RuntimeError("The wheel contains no product modules")
        for member in members:
            if (installed / member.removeprefix("agents_memory/")).read_bytes() != archive.read(member):
                raise RuntimeError("Installed product bytes differ from the wheel")
    import pytest

    helpers = runpy.run_path(str(Path(__file__).with_name("run-tests.py")))
    shard = helpers["Shard"](0, 1)
    output = args.result_dir / "wheel-consumer.json"
    before = helpers["source_digest"]()
    result = {"schema": 1, "complete": False, "tested_sha": os.environ["CI_TESTED_SHA"],
              "source_before": before, "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
              "installed_module_count": len(members), "pytest_exit_code": None}
    helpers["write_result"](output, result)
    try:
        code = int(pytest.main([
            "-q", "tests/test_host_import_isolation.py",
            "tests/test_cli_bind.py::test_occupied_listen_address_refuses_before_database_or_journal_work",
        ], plugins=[shard]))
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
