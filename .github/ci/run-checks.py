from __future__ import annotations

import argparse
import errno
import json
import os
import re
import runpy
import select
import signal
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path


def _darwin_exited_only_member(pid: int) -> bool:
    if sys.platform != "darwin":
        return False
    try:
        with closing(select.kqueue()) as observer:
            try:
                events = observer.control([select.kevent(
                    pid, filter=select.KQ_FILTER_PROC,
                    flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT, fflags=select.KQ_NOTE_EXIT,
                )], 1, 0)
            except ProcessLookupError:
                pass  # Darwin cannot attach NOTE_EXIT to an already exited child.
            else:
                if not events or events[0].ident != pid:
                    return False
                event = events[0]
                if event.flags & select.KQ_EV_ERROR:
                    if event.data != errno.ESRCH:
                        return False
                elif not event.fflags & select.KQ_NOTE_EXIT:
                    return False
        import ctypes

        members = (ctypes.c_int * 2)()
        list_members = ctypes.CDLL("/usr/lib/libproc.dylib").proc_listpgrppids
        list_members.argtypes = (ctypes.c_int, ctypes.c_void_p, ctypes.c_int)
        list_members.restype = ctypes.c_int
        # One atomic, bounded census must contain only our still-unreaped leader.
        return list_members(pid, members, ctypes.sizeof(members)) == 1 and members[0] == pid
    except (AttributeError, ImportError, OSError):
        return False


def _signal_process_group(process: subprocess.Popen[bytes], sig: int) -> bool:
    try:
        os.killpg(process.pid, sig)
    except ProcessLookupError:
        return False
    except PermissionError as error:
        if error.errno != errno.EPERM or not _darwin_exited_only_member(process.pid):
            raise
        return False
    return True


def _stop_process_group(process: subprocess.Popen[bytes]) -> None:
    if process.returncode is not None:
        return
    # Keep the leader unreaped until the final group signal.
    group_present = True
    try:
        group_present = _signal_process_group(process, signal.SIGTERM)
        deadline = time.monotonic() + 5
        while group_present and time.monotonic() < deadline:
            group_present = _signal_process_group(process, 0)
            if group_present:
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
    finally:
        try:
            if group_present:
                _signal_process_group(process, signal.SIGKILL)
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
    parser.add_argument("--test-paths-json", help="Explicit changed-path installed-consumer regressions")
    parser.add_argument("--lint-paths-json", help="Explicit changed Python files, paired with test selection")
    args = parser.parse_args()
    if os.environ.get("GITHUB_ACTIONS") != "true":
        parser.error("This runner is GitHub Actions-only; do not execute checks locally")
    tested_sha = os.environ.get("CI_TESTED_SHA", "")
    if re.fullmatch(r"[0-9a-f]{40}", tested_sha) is None:
        parser.error("CI_TESTED_SHA must identify the exact checked-out commit")
    helpers = runpy.run_path(str(Path(__file__).with_name("run-tests.py")))
    try:
        selectors = helpers["parse_paths"](args.test_paths_json, tests=True)
        lint_paths = helpers["parse_paths"](args.lint_paths_json, tests=False)
    except (OSError, ValueError):
        parser.error("Changed-path checks require bounded repository test and Python-file selections")
    if (selectors is None) != (lint_paths is None):
        parser.error("Changed-path tests and lint paths must be supplied together")
    selected_arguments = ([] if selectors is None else [
        "--test-paths-json", json.dumps(selectors, separators=(",", ":")),
    ])
    os.chdir(helpers["ROOT"])
    args.result_dir.mkdir(parents=True, exist_ok=True)
    output = args.result_dir / "checks.json"
    before = helpers["source_digest"]()
    result = {"schema": 1, "complete": False, "tested_sha": tested_sha,
              "source_before": before, "checks": {}}
    if selectors is not None:
        result["scope"] = {"kind": "changes", "selectors": selectors}
        result["lint_paths"] = lint_paths
    helpers["write_result"](output, result)
    try:
        result["checks"]["lint"] = check(
            ["uv", "run", "ruff", "check", *(lint_paths if lint_paths is not None else ["src", "tests", ".github/ci"])],
            120,
        )
        result["checks"]["comments"] = check(
            ["uv", "run", "--no-sync", "python", ".github/ci/comment-check.py",
             "--result-dir", str(args.result_dir)], 120)
        result["checks"]["build"] = check(["uv", "build"], 300)
        # The installed consumer re-runs ~900 cases in fresh processes; 300s left no runner headroom.
        result["checks"]["wheel-consumer"] = check(
            ["uv", "run", "--no-sync", "python", ".github/ci/wheel-consumer.py",
             "--result-dir", str(args.result_dir), *selected_arguments], 600)
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
