from __future__ import annotations

import argparse
import asyncio
import base64
import ctypes
import hashlib
import importlib
import json
import os
import re
import runpy
import secrets
import select
import signal
import subprocess
import sys
import time
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[2]
CI = Path(__file__).resolve().parent
LIMITS = {
    "cpu_nanos": 1000000000, "memory_bytes": 268435456, "pids": 128,
    "file_descriptors": 128, "file_bytes": 1048576, "scratch_bytes": 8388608,
    "tmp_bytes": 8388608, "shm_bytes": 1048576, "wall_seconds": 2,
    "watchdog_seconds": 120, "operation_seconds": 5, "cleanup_seconds": 5,
    "stdin_bytes": 65536, "stdout_bytes": 65536, "stderr_bytes": 65536,
    "helper_bytes": 1048576,
}


def helpers() -> dict:
    return runpy.run_path(str(CI / "run-tests.py"))


def gate() -> dict:
    return runpy.run_path(str(CI / "aggregate.py"))


def actions() -> dict:
    return {key: os.environ[environment] for key, environment in
            (("run_id", "GITHUB_RUN_ID"), ("run_attempt", "GITHUB_RUN_ATTEMPT"), ("job_id", "GITHUB_JOB"))}


def envelope(before: str) -> dict:
    return {"schema": 1, "complete": False, "tested_sha": os.environ["CI_TESTED_SHA"],
            "source_before": before, "actions": actions()}


def admitted() -> Path:
    if os.environ.get("GITHUB_ACTIONS") != "true" or sys.platform != "linux":
        raise ValueError("HOSTED_ACTIONS_REQUIRED")
    if os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted" or os.environ.get("RUNNER_ARCH") != "X64":
        raise ValueError("STANDARD_HOSTED_AMD64_REQUIRED")
    if re.fullmatch(r"[0-9a-f]{40}", os.environ.get("CI_TESTED_SHA", "")) is None:
        raise ValueError("EXACT_TESTED_SHA_REQUIRED")
    owner = actions()
    if not owner["job_id"] or any(re.fullmatch(r"[1-9][0-9]*", owner[key]) is None
                                  for key in ("run_id", "run_attempt")):
        raise ValueError("ACTIONS_OWNER_REQUIRED")
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "OWNED_SUBREAPER_REQUIRED")
    os.umask(0o077)
    sys.dont_write_bytecode = True
    os.chdir(ROOT)
    root = Path(os.environ["RUNNER_TEMP"])
    if not root.is_absolute():
        raise ValueError("ABSOLUTE_RUNNER_TEMP_REQUIRED")
    return root.resolve(strict=True)


def private_save(path: Path, value: dict) -> None:
    from agents_memory.evaluation_artifacts import canonical_bytes
    from agents_memory.private_io import private_write
    private_write(path, canonical_bytes(value))


def public_terminal(path: Path, value: dict) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")


def reap_owned_descendants(root: Path, label: str) -> bool:
    deadline = time.monotonic() + 15
    count = 0
    complete = False
    try:
        while time.monotonic() < deadline and count < 512:
            with Path(f"/proc/self/task/{os.getpid()}/children").open("rb") as stream:
                raw = stream.read(65537)
            if len(raw) > 65536:
                raise ValueError("OWNED_CHILD_INVENTORY_BOUND")
            children = [int(item) for item in raw.split()]
            if not children:
                complete = True
                break
            for pid in children:
                descriptor = os.pidfd_open(pid)
                try:
                    fields = Path(f"/proc/{pid}/stat").read_bytes().rsplit(b") ", 1)[1].split()
                    if int(fields[1]) != os.getpid():
                        raise ValueError("OWNED_CHILD_PARENT_CHANGED")
                    with Path(f"/proc/{pid}/cmdline").open("rb") as stream:
                        command_line = stream.read(1048577)
                    if len(command_line) > 1048576:
                        raise ValueError("OWNED_CHILD_COMMAND_BOUND")
                    private_save(root / f"{label}-child-{count:04d}-intent.json",
                                 {"actions": actions(), "pid": pid, "start_ticks": int(fields[19]),
                                  "command_sha256": hashlib.sha256(command_line).hexdigest()})
                    try:
                        signal.pidfd_send_signal(descriptor, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    if not select.select([descriptor], [], [], max(0, deadline - time.monotonic()))[0]:
                        raise TimeoutError("OWNED_CHILD_REAP_BOUND")
                    os.waitpid(pid, 0)
                    count += 1
                finally:
                    os.close(descriptor)
    except (OSError, ValueError, TimeoutError):
        complete = False
    private_save(root / (label + "-descendants.json"),
                 {"actions": actions(), "complete": complete, "reaped": count})
    return complete


def command(root: Path, label: str, argv: list[str], seconds: float, *, env: dict | None = None):
    from agents_memory.evaluation_runtime import CommandLease
    private_save(root / (label + "-intent.json"), {"argv": argv, "actions": actions()})
    result = CommandLease(argv, dict(os.environ) if env is None else env, stdin=b"", seconds=seconds,
                          stdout_limit=16 * 1024 * 1024, stderr_limit=4 * 1024 * 1024).close(15)
    descendants_reaped = reap_owned_descendants(root, label)
    result = replace(result, helper_cleanup=result.helper_cleanup and descendants_reaped)
    private_save(root / (label + "-observation.json"), {**result.public(),
                 "stdout": base64.b64encode(result.stdout).decode("ascii"),
                 "stderr": base64.b64encode(result.stderr).decode("ascii")})
    return result


def require_completed(result) -> None:
    if not result.completed:
        raise ValueError("OWNED_COMMAND_INCOMPLETE")


def runtime_receipt(raw: bytes, before: str) -> dict:
    value = json.loads(raw)
    allowed = {"schema", "stage", "code", "type", "complete", "runtime_digest", "image_config_digest",
               "tool_digest", "cleanup_complete", "owners", "resources", "probe_cleanup"}
    if not isinstance(value, dict) or not set(value) <= allowed:
        raise ValueError("RUNTIME_PUBLIC_RECEIPT_BOUNDARY")
    return {**value, "tested_sha": os.environ["CI_TESTED_SHA"], "source_before": before,
            "source_after": helpers()["source_digest"](), "actions": actions()}


def health_smoke(result_dir: Path, consumption: str, wheel_digest: str | None = None) -> int:
    runner = admitted()
    accounting = helpers()
    before = accounting["source_digest"]()
    value = envelope(before)
    value.update(consumption=consumption, wheel_sha256=wheel_digest)
    result_dir.mkdir(parents=True, exist_ok=True)
    output = result_dir / ("health-" + consumption + ".json")
    if output.exists():
        raise ValueError("HEALTH_EVIDENCE_ALREADY_EXISTS")
    private = runner / ("agents-memory-health-orchestration-" + consumption + "-" + secrets.token_hex(16))
    private.mkdir(mode=0o700)
    try:
        environment = dict(os.environ)
        if consumption == "source":
            package = importlib.import_module("agents_memory")
            if Path(package.__file__).resolve().parent != ROOT / "src" / "agents_memory":
                raise ValueError("SOURCE_HEALTH_RESOLVED_INSTALLED_PACKAGE")
            environment["PYTHONPATH"] = str(ROOT / "src")
        argv = [sys.executable, *(["-I"] if consumption == "installed" else []), str(CI / "health-smoke.py"),
                "--result-dir", str(result_dir / ("health-" + consumption))]
        result = command(private, "health-smoke", argv, 420, env=environment)
        value["execution"] = result.public()
        value["health"] = json.loads((result_dir / ("health-" + consumption) / "health-smoke.json").read_text())
        require_completed(result)
        value["complete"] = value["health"].get("complete") is True
    except Exception as error:
        value["complete"] = False
        value["error_type"] = type(error).__name__
    finally:
        value["source_after"] = accounting["source_digest"]()
        value["complete"] = value["complete"] and before == value["source_after"]
        public_terminal(output, value)
    return 0 if value["complete"] else 1


def runtime_identity(state: Path) -> dict[str, str]:
    module = runpy.run_path(str(CI / "evaluation-runtime.py"))
    from agents_memory.private_io import private_read
    from agents_memory.wire import decode_json
    raw = private_read(state / "runtime-spec.json", 4 * 1024 * 1024)
    spec = module["load_runtime"](decode_json(raw))
    return {"runtime_digest": spec.digest, "runtime_spec_sha256": hashlib.sha256(raw).hexdigest(),
            "docker_sha256": spec.docker_sha256, "tool_identity": spec.tool_identity,
            "image_id_digest": hashlib.sha256(spec.image_id.encode()).hexdigest(),
            "image_config_digest": spec.image_config_digest,
            "python_executable_sha256": hashlib.sha256(Path(sys.executable).resolve().read_bytes()).hexdigest()}


def runtime_digest(state: Path) -> str:
    return runtime_identity(state)["runtime_digest"]


def scenarios(result_dir: Path, wheel: Path) -> int:
    accounting = helpers()
    if (result_dir / "evaluation-scenarios.json").exists():
        raise ValueError("SCENARIOS_ALREADY_INVOKED")
    before = accounting["source_digest"]()
    state = Path(os.environ["RUNNER_TEMP"]) / "agents-memory-evaluation"
    value = envelope(before)
    value.update(runtime_digest=runtime_digest(state), wheel_sha256=wheel_sha256(wheel))
    consumer = runpy.run_path(str(CI / "wheel-consumer.py"))
    value["installed_modules"] = consumer["installed_identity"](ROOT, wheel)
    shard = accounting["Shard"](0, 1)
    import pytest
    try:
        with (state / "scenarios-output.private").open("x") as stream, redirect_stdout(stream), redirect_stderr(stream):
            code = int(pytest.main(["-q", "tests/evaluation_docker_scenarios.py", "--basetemp", str(state / "verifier"),
                                   "-o", "tmp_path_retention_policy=all"], plugins=[shard]))
        value.update(pytest_exit_code=code, all_nodeids=shard.collected, selected_nodeids=shard.selected,
                     reports=shard.reports, collection_issues=shard.collection_issues, counts=shard.counts())
        gate()["execution"](value, gate()["SCENARIO_NODEIDS"])
        value["complete"] = (shard.collected == shard.selected == gate()["SCENARIO_NODEIDS"]
                             and not shard.collection_issues)
        value["complete"] = value["complete"] and value["installed_modules"] == consumer["installed_identity"](ROOT, wheel)
    finally:
        value["source_after"] = accounting["source_digest"]()
        value["complete"] = value["complete"] and before == value["source_after"]
        public_terminal(result_dir / "evaluation-scenarios.json", value)
        accounting["write_junit"](result_dir / "evaluation-scenarios-junit.xml", shard)
    return 0 if value["complete"] else 1


def wheel_sha256(wheel: Path) -> str:
    return hashlib.sha256(wheel.read_bytes()).hexdigest()


def run(result_dir: Path, wheel: Path) -> int:
    accounting = helpers()
    before = accounting["source_digest"]()
    value = envelope(before)
    value.update(consumption="installed", wheel_origin="evaluation-job-built", wheel_sha256=wheel_sha256(wheel),
                 phases={}, image_reference=gate()["EVALUATION_IMAGE"])
    output = result_dir / "evaluation-job.json"
    if output.exists():
        raise ValueError("EVALUATION_ALREADY_INVOKED")
    result_dir.mkdir(parents=True, exist_ok=True)
    state = Path(os.environ["RUNNER_TEMP"]) / "agents-memory-evaluation"
    state.mkdir(mode=0o700)
    for name in ("docker-config", "verifier"):
        (state / name).mkdir(mode=0o700)
    private_save(state / "orchestration-owner.json", {"actions": actions(), "tested_sha": os.environ["CI_TESTED_SHA"]})
    private_save(state / "limits.json", LIMITS)
    accounting["write_result"](output, value)
    try:
        consumer = runpy.run_path(str(CI / "wheel-consumer.py"))
        value["installed_modules"] = consumer["installed_identity"](ROOT, wheel)
        docker_env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "DOCKER_CONFIG": str(state / "docker-config"),
                      "DOCKER_HOST": "unix:///var/run/docker.sock"}
        acquired = command(state, "image-acquisition", ["/usr/bin/docker", "pull", "--platform", "linux/amd64",
                                                        gate()["EVALUATION_IMAGE"]], 120, env=docker_env)
        value["phases"]["image-acquisition"] = acquired.public()
        require_completed(acquired)
        prepared = command(state, "runtime-prepare", [sys.executable, "-I", str(CI / "evaluation-runtime.py"), "prepare",
                           "--image-reference", gate()["EVALUATION_IMAGE"], "--docker-binary", "/usr/bin/docker",
                           "--docker-endpoint", "unix:///var/run/docker.sock", "--docker-config", str(state / "docker-config"),
                           "--state-root", str(state), "--limits-file", str(state / "limits.json"),
                           "--spec-output", str(state / "runtime-spec.json")], 300)
        value["phases"]["runtime-prepare"] = prepared.public()
        public = runtime_receipt(prepared.stdout, before)
        public_terminal(result_dir / "evaluation-runtime-prepare.json", public)
        require_completed(prepared)
        value["runtime"] = runtime_identity(state)
        environment = dict(os.environ, AGENTS_MEMORY_EVALUATION_RUNTIME_SPEC=str(state / "runtime-spec.json"))
        tested = command(state, "scenarios", [sys.executable, "-I", str(Path(__file__).resolve()), "scenarios",
                         "--result-dir", str(result_dir), "--installed-wheel", str(wheel)], 600, env=environment)
        value["phases"]["scenarios"] = tested.public()
        require_completed(tested)
        full = command(state, "full-smoke", [sys.executable, "-I", str(CI / "evaluation-smoke.py"),
                       "--wheel", str(wheel), "--expected-wheel-sha256", value["wheel_sha256"],
                       "--consumption", "installed", "--result-dir", ".ci-results"], 900, env=environment)
        value["phases"]["full-smoke"] = full.public()
        diagnostic = json.loads(full.stdout)
        if isinstance(diagnostic, dict) and diagnostic.get("tested_sha") in (None, os.environ["CI_TESTED_SHA"]):
            value["smoke_diagnostic"] = {
                name: diagnostic[name] for name in ("code", "error_type", "failure_code")
                if isinstance(diagnostic.get(name), str)
                and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}", diagnostic[name])
            }
            value["smoke_diagnostic"]["source_identity_admitted"] = diagnostic.get("tested_sha") == os.environ["CI_TESTED_SHA"]
        require_completed(full)
        value["complete"] = True
    except Exception as error:
        value["error_type"] = type(error).__name__
    finally:
        value["source_after"] = accounting["source_digest"]()
        value["complete"] = value["complete"] and before == value["source_after"]
        accounting["write_result"](output, value)
    return 0 if value["complete"] else 1


async def schema_cleanup(state: Path) -> bool:
    import asyncpg

    from agents_memory.evaluation_artifacts import open_private_directory
    from agents_memory.private_io import private_read
    from agents_memory.wire import decode_json

    root = state / "verifier" / "full-smoke"
    if not root.exists():
        return True
    descriptor = open_private_directory(root)
    os.close(descriptor)
    try:
        intent = decode_json(private_read(root / "schema-intent.json", 4096))
    except FileNotFoundError:
        return True
    owner = actions()
    if (intent.get("schema") != 1 or any(intent.get(key) != owner[key] for key in owner)
            or re.fullmatch(r"am_evaluation_[0-9a-f]{32}", intent.get("name", "")) is None):
        raise ValueError("SCHEMA_OWNER_MISMATCH")
    name = intent["name"]
    created = decode_json(private_read(root / "schema-created.json", 4096))
    if created != {"schema": 1, "name": name}:
        raise ValueError("SCHEMA_CREATION_UNCONFIRMED")
    parts = urlsplit(os.environ["PG_TEST_DSN"])
    query = dict(parse_qsl(parts.query))
    query.pop("schema", None)
    dsn = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
    connection = await asyncpg.connect(dsn, timeout=10, command_timeout=30)
    try:
        private_save(root / ("parent-schema-cleanup-" + secrets.token_hex(16) + "-intent.json"), {"actions": owner, "name": name})
        await connection.execute(f'DROP SCHEMA IF EXISTS "{name}" CASCADE')
        absent = not await connection.fetchval("SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname=$1)", name)
        private_save(root / ("parent-schema-cleanup-" + secrets.token_hex(16) + "-observation.json"), {"name": name, "exact_absence": absent})
        return absent
    finally:
        await connection.close(timeout=10)


def cleanup(result_dir: Path) -> int:
    accounting = helpers()
    before = accounting["source_digest"]()
    value = envelope(before)
    value.update(runtime_exact_absent=False, schema_exact_absent=False, prerequisites_exact_absent=False,
                 processes_reaped=False, private_evidence_retained=True)
    result_dir.mkdir(parents=True, exist_ok=True)
    state = Path(os.environ["RUNNER_TEMP"]) / "agents-memory-evaluation"
    from agents_memory.evaluation_artifacts import open_private_directory
    parent = Path(os.environ["RUNNER_TEMP"])
    try:
        descriptor = open_private_directory(state)
        os.close(descriptor)
        parent = state
    except (OSError, ValueError):
        pass
    journal = parent / ("parent-evaluation-cleanup-" + secrets.token_hex(16))
    journal.mkdir(mode=0o700)
    process_cleanup = True
    try:
        try:
            value["runtime_digest"] = runtime_digest(state)
        except Exception:
            value["runtime_digest"] = None
        try:
            result = command(journal, "runtime-cleanup", [sys.executable, "-I", str(CI / "evaluation-runtime.py"), "cleanup",
                             "--state-root", str(state), "--spec-file", str(state / "runtime-spec.json")], 300)
            process_cleanup = process_cleanup and result.helper_cleanup
            public = runtime_receipt(result.stdout, before)
            public_terminal(result_dir / "evaluation-runtime-cleanup.json", public)
            value["runtime_exact_absent"] = result.completed and public.get("complete") is True and public.get("cleanup_complete") is True
        except Exception:
            value["runtime_exact_absent"] = False
        try:
            value["schema_exact_absent"] = asyncio.run(schema_cleanup(state))
        except Exception:
            value["schema_exact_absent"] = False
        try:
            from agents_memory.private_io import private_read
            from agents_memory.wire import decode_json
            pg_state = Path(os.environ["RUNNER_TEMP"]) / "agents-memory-ci"
            manifest = decode_json(private_read(pg_state / "manifest.json", 65536))
            if manifest.get("job") != ":".join(actions().values()):
                raise ValueError("PREREQUISITE_OWNER_MISMATCH")
            private_save(journal / "prerequisite-manifest.json", manifest)
            result = command(journal, "prerequisite-cleanup", [sys.executable, "-I", str(CI / "environment.py"), "cleanup",
                             "--state-dir", str(pg_state)], 180)
            process_cleanup = process_cleanup and result.helper_cleanup
            require_completed(result)
            absent = not pg_state.exists()
            for kind in ("container", "volume"):
                name = manifest.get(kind)
                if not isinstance(name, str) or not re.fullmatch(r"am-ci-[0-9a-f]{24}" + ("-data" if kind == "volume" else ""), name):
                    raise ValueError("PREREQUISITE_RESOURCE_MISSING")
                probe = command(journal, kind + "-absence", ["/usr/bin/docker", kind, "ls",
                                *(["--all"] if kind == "container" else []), "--filter", f"name=^{name}$",
                                "--format", "{{.Names}}" if kind == "container" else "{{.Name}}"], 30)
                process_cleanup = process_cleanup and probe.helper_cleanup
                require_completed(probe)
                absent = absent and name not in probe.stdout.decode("ascii").splitlines()
            value["prerequisites_exact_absent"] = absent
        except Exception:
            value["prerequisites_exact_absent"] = False
        try:
            from agents_memory.private_io import private_read
            from agents_memory.wire import decode_json
            for label in gate()["EVALUATION_PHASES"]:
                if not (state / (label + "-intent.json")).exists():
                    continue
                prior = decode_json(private_read(state / (label + "-descendants.json"), 4096))
                if prior.get("actions") != actions() or prior.get("complete") is not True:
                    process_cleanup = False
        except (OSError, ValueError):
            process_cleanup = False
        value["processes_reaped"] = process_cleanup
        value["source_after"] = accounting["source_digest"]()
        value["complete"] = before == value["source_after"] and all(value[key] is True for key in
            ("runtime_exact_absent", "schema_exact_absent", "prerequisites_exact_absent", "processes_reaped"))
    finally:
        public_terminal(result_dir / "evaluation-cleanup.json", value)
    return 0 if value["complete"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Owned installed-wheel evaluation engineering in hosted Actions only")
    parser.add_argument("action", choices=("run", "cleanup", "scenarios", "health-source"))
    parser.add_argument("--result-dir", type=Path, default=Path(".ci-results"))
    parser.add_argument("--installed-wheel", type=Path)
    args = parser.parse_args()
    try:
        admitted()
        if args.result_dir.resolve() != ROOT / ".ci-results":
            raise ValueError("EXACT_RESULT_DIRECTORY_REQUIRED")
        if os.environ.get("PYTEST_ADDOPTS"):
            raise ValueError("INHERITED_TEST_SELECTION_REFUSED")
        if args.action == "health-source":
            return health_smoke(args.result_dir.resolve(), "source")
        if args.action == "cleanup":
            return cleanup(args.result_dir.resolve())
        if args.installed_wheel is None:
            wheels = list((ROOT / "dist").glob("*.whl"))
            if len(wheels) != 1:
                raise ValueError("EXACT_EVALUATION_WHEEL_REQUIRED")
            wheel = wheels[0].resolve(strict=True)
            subprocess.run(["uv", "pip", "install", "--python", sys.executable,
                            "--reinstall", "--no-deps", "--link-mode", "copy", str(wheel)],
                           check=True, timeout=60)
            os.execv(sys.executable, [sys.executable, "-I", str(Path(__file__).resolve()), args.action,
                                     "--result-dir", str(args.result_dir.resolve()), "--installed-wheel", str(wheel)])
        wheel = args.installed_wheel.resolve(strict=True)
        if not sys.flags.isolated:
            raise ValueError("ISOLATED_INSTALLED_CONSUMER_REQUIRED")
        if args.action == "scenarios":
            return scenarios(args.result_dir.resolve(), wheel)
        return run(args.result_dir.resolve(), wheel)
    except Exception:
        print("EVALUATION_CI_INCOMPLETE", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
