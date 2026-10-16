from __future__ import annotations

import argparse
import os
import re
import runpy
import signal
import subprocess
import time
from contextlib import suppress
from pathlib import Path


def _stop_process_group(process: subprocess.Popen[bytes]) -> None:
    if process.returncode is not None:
        return
    # Keep the leader unreaped until the final group signal.
    group_missing = False
    try:
        try:
            os.killpg(process.pid, signal.SIGTERM)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                os.killpg(process.pid, 0)
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
        except ProcessLookupError:
            group_missing = True
    finally:
        try:
            if not group_missing:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
        finally:
            process.wait()


def check(command: list[str], timeout: int) -> dict:
    began = time.monotonic()
    result = {"command": command, "exit_code": None, "timeout": False}
    try:
        process = subprocess.Popen(command, start_new_session=True)
        try:
            result["exit_code"] = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            result["timeout"] = True
            _stop_process_group(process)
            result["exit_code"] = process.returncode
    except OSError as error:
        result["error"] = type(error).__name__
    result["seconds"] = round(time.monotonic() - began, 3)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run bounded lint/build/wheel checks and preserve all outcomes")
    parser.add_argument("--result-dir", type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get("GITHUB_ACTIONS") != "true":
        parser.error("This runner is GitHub Actions-only; do not execute checks locally")
    tested_sha = os.environ.get("CI_TESTED_SHA", "")
    if re.fullmatch(r"[0-9a-f]{40}", tested_sha) is None:
        parser.error("CI_TESTED_SHA must identify the exact checked-out commit")
    helpers = runpy.run_path(str(Path(__file__).with_name("run-tests.py")))
    os.chdir(helpers["ROOT"])
    args.result_dir.mkdir(parents=True, exist_ok=True)
    output = args.result_dir / "checks.json"
    before = helpers["source_digest"]()
    result = {"schema": 1, "complete": False, "tested_sha": tested_sha,
              "source_before": before, "checks": {}}
    helpers["write_result"](output, result)
    try:
        result["checks"]["lint"] = check(["uv", "run", "ruff", "check", "src", "tests", ".github/ci"], 120)
        result["checks"]["build"] = check(["uv", "build"], 300)
        result["checks"]["wheel-consumer"] = check(
            ["uv", "run", "--no-sync", "python", ".github/ci/wheel-consumer.py",
             "--result-dir", str(args.result_dir)], 300)
        result["source_after"] = helpers["source_digest"]()
        result["complete"] = before == result["source_after"] and all(
            outcome["exit_code"] == 0 and not outcome.get("timeout") and not outcome.get("error")
            for outcome in result["checks"].values()
        )
    finally:
        helpers["write_result"](output, result)
    return 0 if result["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
