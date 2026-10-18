from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import runpy
import subprocess
import types
from pathlib import Path, PurePosixPath
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
CHECKER_COMMIT = "89512553cd85a608b02845e1dd1c3d81b4727dca"
CHECKER_SHA256 = "0eb61a66acdd1ec4031c4cb8aedf78aced785f0b69c46e50a0234241adbd3f5f"
CHECKER_URL = f"https://raw.githubusercontent.com/chonamdoo/agent-flow/{CHECKER_COMMIT}/scripts/hooks/comment-checker.py"
CHECKER_BYTES = 20256
MAX_FILES = 4096
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
SHA = re.compile(r"[0-9a-f]{40}\Z")


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _first_parent(head: str) -> str:
    argv = ["git", "--no-pager", "-C", str(ROOT), "cat-file"]
    try:
        size = subprocess.run([*argv, "-s", head], capture_output=True, timeout=10, check=True)
        require(len(size.stdout) <= 32 and len(size.stderr) <= 8192, "COMMIT_METADATA_BOUND")
        count = int(size.stdout)
        require(0 < count <= 1024 * 1024, "COMMIT_METADATA_BOUND")
        record = subprocess.run([*argv, "commit", head], capture_output=True, timeout=10, check=True)
        require(len(record.stdout) == count and len(record.stderr) <= 8192, "COMMIT_METADATA_BOUND")
    except subprocess.SubprocessError:
        raise ValueError("COMMIT_METADATA_UNAVAILABLE") from None
    parents = [line[7:].decode("ascii") for line in record.stdout.split(b"\n\n", 1)[0].splitlines()
               if line.startswith(b"parent ")]
    require(bool(parents) and SHA.fullmatch(parents[0]) is not None, "COMPARISON_PARENT_REQUIRED")
    return parents[0]


def comparison_base(head: str) -> dict:
    require(SHA.fullmatch(head) is not None, "EXACT_HEAD_REQUIRED")
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        raise ValueError("EVENT_METADATA_REQUIRED")
    path = Path(event_path)
    with path.open("rb") as stream:
        raw = stream.read(2 * 1024 * 1024 + 1)
    require(len(raw) <= 2 * 1024 * 1024, "EVENT_METADATA_BOUND")
    event = json.loads(raw)
    require(isinstance(event, dict), "EVENT_METADATA_INVALID")
    name = os.environ.get("GITHUB_EVENT_NAME")
    if name == "pull_request":
        try:
            base, basis = event["pull_request"]["base"]["sha"], "pull_request_base"
        except (KeyError, TypeError):
            raise ValueError("PR_COMPARISON_METADATA_REQUIRED") from None
    elif name == "push" and event.get("before") != "0" * 40:
        base, basis = event.get("before"), "push_before"
    else:
        base, basis = _first_parent(head), "head_first_parent"
    require(isinstance(base, str) and SHA.fullmatch(base) is not None and base != head,
            "EXACT_DISTINCT_COMPARISON_BASE_REQUIRED")
    return {"base_sha": base, "basis": basis}


def git(*arguments: str, limit: int = 8192, seconds: float = 20):
    from agents_memory.evaluation_runtime import CommandLease

    return CommandLease(["git", "--no-pager", "-C", str(ROOT), *arguments], dict(os.environ),
                        stdin=b"", seconds=seconds, stdout_limit=limit, stderr_limit=8192).close(5)


def git_bytes(*arguments: str, limit: int = 8192, seconds: float = 20) -> bytes:
    observation = git(*arguments, limit=limit, seconds=seconds)
    require(observation.completed, "GIT_METADATA_INCOMPLETE")
    return observation.stdout


def load_checker():
    with urlopen(CHECKER_URL, timeout=20) as response:
        source = response.read(CHECKER_BYTES + 1)
    require(len(source) == CHECKER_BYTES and digest(source) == CHECKER_SHA256, "CANONICAL_CHECKER_MISMATCH")
    module = types.ModuleType("canonical_agent_flow_comment_checker")
    module.__file__ = CHECKER_URL
    exec(compile(source, CHECKER_URL, "exec"), module.__dict__)
    return module


def blob(oid: str, mode: str) -> bytes:
    if mode == "000000":
        require(oid == "0" * 40, "ABSENT_BLOB_IDENTITY")
        return b""
    require(mode in {"100644", "100755"} and SHA.fullmatch(oid) is not None, "REGULAR_SOURCE_REQUIRED")
    count = int(git_bytes("cat-file", "-s", oid))
    require(0 <= count <= MAX_FILE_BYTES, "SOURCE_FILE_BOUND")
    raw = git_bytes("cat-file", "blob", oid, limit=MAX_FILE_BYTES)
    require(len(raw) == count, "SOURCE_BLOB_BOUND")
    return raw


def compare(checker, base: str, head: str) -> dict:
    probe = git("cat-file", "-e", base + "^{commit}")
    if not probe.completed:
        require(probe.state == "completed" and probe.exit_code in {1, 128}
                and probe.stdout_complete and probe.stderr_complete and probe.helper_cleanup,
                "COMPARISON_BASE_PROBE_INCOMPLETE")
        git_bytes("fetch", "--no-tags", "--no-recurse-submodules", "--depth=1", "origin", base,
                  seconds=45)
    raw = git_bytes("diff", "--no-ext-diff", "--no-textconv", "--raw", "-z", "--no-renames",
                    "--no-abbrev", base, head, "--", limit=4 * 1024 * 1024)
    parts = raw.split(b"\0")
    require(parts[-1] == b"" and len(parts) % 2 == 1, "SOURCE_DIFF_METADATA_INVALID")
    changes = (len(parts) - 1) // 2
    require(changes <= MAX_FILES, "SOURCE_FILE_COUNT_BOUND")
    files, findings, total, finding_count = [], [], 0, 0
    for index in range(0, len(parts) - 1, 2):
        metadata = re.fullmatch(rb":([0-7]{6}) ([0-7]{6}) ([0-9a-f]{40}) ([0-9a-f]{40}) ([AMDT])", parts[index])
        if metadata is None:
            raise ValueError("SOURCE_DIFF_METADATA_INVALID")
        path = parts[index + 1].decode("utf-8")
        require(bool(path) and not PurePosixPath(path).is_absolute() and ".." not in PurePosixPath(path).parts,
                "SOURCE_PATH_SCOPE")
        if not checker.should_check_file(path):
            continue
        old_mode, new_mode, old_oid, new_oid, status = (item.decode("ascii") for item in metadata.groups())
        old, new = blob(old_oid, old_mode), blob(new_oid, new_mode)
        total += len(old) + len(new)
        require(total <= MAX_TOTAL_BYTES, "SOURCE_TOTAL_BOUND")
        path_digest = digest(path.encode())
        files.append({"path_digest": path_digest, "status": status, "old_mode": old_mode, "new_mode": new_mode,
                      "old_oid": old_oid, "new_oid": new_oid, "old_bytes": len(old), "new_bytes": len(new)})
        detected = checker.check_payload({"tool_name": "MultiEdit", "tool_input": {"edits": [{
            "file_path": path, "old_string": old.decode("utf-8"), "new_string": new.decode("utf-8")}]}})
        for detected_path, line, _ in detected:
            require(detected_path == path and type(line) is int and line >= 1, "CHECKER_FINDING_INVALID")
            finding_count += 1
            if len(findings) < 200:
                findings.append({"path_digest": path_digest, "line": line})
    files.sort(key=lambda item: item["path_digest"])
    return {"changed_files": changes, "eligible_files": len(files), "excluded_files": changes - len(files),
            "input_bytes": total, "files": files, "manifest_digest": digest(canonical(files)),
            "finding_count": finding_count, "findings": findings, "coverage_complete": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="Actions-only exact canonical added-comment policy check")
    parser.add_argument("--result-dir", type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get("GITHUB_ACTIONS") != "true":
        parser.error("Do not execute this checker locally; GitHub Actions only")
    helpers = runpy.run_path(str(Path(__file__).with_name("run-tests.py")))
    head = os.environ.get("CI_TESTED_SHA", "")
    before = helpers["source_digest"]()
    result = {"schema": 1, "complete": False, "tested_sha": head, "source_before": before,
              "checker": {"commit": CHECKER_COMMIT, "sha256": CHECKER_SHA256,
                          "url": CHECKER_URL, "bytes": CHECKER_BYTES, "license": "MIT"},
              "actions": {"run_id": os.environ["GITHUB_RUN_ID"], "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
                          "job_id": os.environ["GITHUB_JOB"]}, "stage": "identity"}
    try:
        require(SHA.fullmatch(head) is not None and git_bytes("rev-parse", "HEAD").decode().strip() == head,
                "EXACT_HEAD_REQUIRED")
        result["comparison"] = comparison_base(head)
        result["stage"] = "canonical_source"
        checker = load_checker()
        result["stage"] = "changed_comments"
        result["coverage"] = compare(checker, result["comparison"]["base_sha"], head)
        result["source_after"] = helpers["source_digest"]()
        result["complete"] = before == result["source_after"] and result["coverage"]["finding_count"] == 0
        result["code"] = "CHECKED" if result["complete"] else "COMMENT_POLICY_FAILED"
    except Exception as error:
        result["code"] = "COMMENT_CHECK_INCOMPLETE"
        result["error_type"] = type(error).__name__ if type(error).__name__ in {
            "OSError", "ValueError", "TypeError", "KeyError", "ImportError", "ModuleNotFoundError",
            "HTTPError", "URLError", "TimeoutError", "UnicodeDecodeError",
        } else "BoundaryError"
        result["failure_code"] = str(error) if isinstance(error, ValueError) and re.fullmatch(
            r"[A-Z][A-Z0-9_]{0,79}", str(error)) else "CHECKER_FAILURE"
        result["source_after"] = helpers["source_digest"]()
    finally:
        helpers["write_result"](args.result_dir / "comment-check.json", result)
    print(json.dumps({key: result[key] for key in ("complete", "code", "stage", "tested_sha")}, sort_keys=True))
    return 0 if result["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
