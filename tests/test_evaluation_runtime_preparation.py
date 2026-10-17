from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import os
from dataclasses import asdict
from pathlib import Path

import pytest

from agents_memory.evaluation_artifacts import canonical_bytes, digest_bytes, open_private_directory
from agents_memory.evaluation_runtime import (
    CommandObservation,
    DockerRuntime,
    EvaluationOwner,
    RuntimeLimits,
    RuntimeRefusal,
)


@pytest.fixture
def helper():
    path = Path(__file__).resolve().parents[1] / ".github/ci/evaluation-runtime.py"
    spec = importlib.util.spec_from_file_location("evaluation_ci_runtime", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def prepared_inputs(tmp_path, monkeypatch, helper):
    root = tmp_path / "agents-memory-evaluation"
    root.mkdir(mode=0o700)
    for name in ("docker-config", "verifier"):
        (root / name).mkdir(mode=0o700)
    binary = tmp_path / "docker"
    binary.write_bytes(b"engineering-device-not-an-executable-runtime")
    binary.chmod(0o755)
    limits = RuntimeLimits(1000000000, 134217728, 64, 128, 1048576, 1048576, 1048576, 1048576, 2, 60, 2, 2, 4096, 4096, 4096, 65536)
    (root / "limits.json").write_bytes(canonical_bytes(asdict(limits)))
    (root / "limits.json").chmod(0o600)
    for key, value in (("GITHUB_RUN_ID", "123"), ("GITHUB_RUN_ATTEMPT", "1"), ("GITHUB_JOB", "runtime"), ("RUNNER_TEMP", str(tmp_path))):
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(EvaluationOwner, "require_actions", lambda self: None)
    monkeypatch.setattr(helper.Preparation, "pin", lambda self: None)
    args = argparse.Namespace(state_root=root, image_reference=helper.IMAGE, docker_binary=binary, docker_endpoint="unix:///var/run/docker.sock", docker_config=root / "docker-config", limits_file=root / "limits.json", spec_output=root / "runtime-spec.json", spec_file=root / "runtime-spec.json")
    return args, limits


class DockerDevice:
    def __init__(self, helper, args, limits):
        self.helper, self.args, self.limits = helper, args, limits
        self.calls = []
        self.container = None
        self.identity = "a" * 64
        self.create_lost = False
        self.create_pending = False
        self.start_lost = False
        self.remove_lost = False
        self.bad_tool = False
        self.foreign = False
        self.alias = helper.IMAGE
        self.image_config = {"Env": ["PATH=/usr/local/bin:/usr/bin:/bin"], "User": ""}
        self.tool = {"executable": "/usr/local/bin/python3.12", "sha256": "b" * 64, "version": "engineering-fixture-only", "implementation": "CPython", "machine": "x86_64"}

    def result(self, value=b"", *, code=0, state="completed"):
        raw = value if isinstance(value, bytes) else canonical_bytes(value)
        return CommandObservation(state, code, raw, b"private diagnostic must not escape", 0.01, True, True, True)

    def probe_container(self, args):
        limit = self.limits
        labels = {}
        for index, value in enumerate(args):
            if value == "--label":
                key, content = args[index + 1].split("=", 1)
                labels[key] = content
        if self.foreign:
            labels[self.helper.OWNER_LABEL] = "foreign"
        return {"Id": self.identity, "Name": "/" + args[args.index("--name") + 1], "Image": "sha256:" + "c" * 64, "Config": {"Labels": labels, "User": "65532:65532", "WorkingDir": "/", "Entrypoint": ["/usr/local/bin/python3"], "Cmd": ["-I", "-S", "-c", self.helper.TOOL_PROBE_SOURCE], "Env": self.image_config["Env"], "Healthcheck": {"Test": ["NONE"]}}, "Mounts": [], "HostConfig": {"ReadonlyRootfs": True, "Privileged": False, "NetworkMode": "none", "IpcMode": "private", "PidMode": "", "UsernsMode": "", "CgroupnsMode": "private", "NanoCpus": limit.cpu_nanos, "Memory": limit.memory_bytes, "MemorySwap": limit.memory_bytes, "PidsLimit": limit.pids, "ShmSize": limit.shm_bytes, "PublishAllPorts": False, "CapDrop": ["ALL"], "SecurityOpt": ["no-new-privileges:true"], "Ulimits": [{"Name": name, "Soft": value, "Hard": value} for name, value in (("nofile", limit.file_descriptors), ("fsize", limit.file_bytes), ("core", 0))], "RestartPolicy": {"Name": "no"}, "LogConfig": {"Type": "none"}}}

    def dispatch(self, argv):
        args = argv[1:]
        self.calls.append(args)
        if args[0] == "info":
            return self.result({"OSType": "linux", "Architecture": "x86_64", "SecurityOptions": ["name=seccomp,profile=builtin"]})
        if args[:2] == ["image", "inspect"]:
            return self.result([{"Id": "sha256:" + "c" * 64, "Os": "linux", "Architecture": "amd64", "RepoDigests": [self.alias], "Config": self.image_config}])
        if args[0] == "create":
            assert (self.args.state_root / "probe-create-intent.json").exists()
            assert "--pull=never" in args and "--mount" not in args
            assert args[args.index("--user") + 1] == "65532:65532"
            if not self.create_pending:
                self.container = self.probe_container(args)
            return self.result(state="timeout", code=None) if self.create_lost or self.create_pending else self.result(self.identity.encode())
        if args[:2] == ["container", "inspect"]:
            if self.container is not None and args[2] in (self.identity, self.container["Name"][1:]):
                return self.result([copy.deepcopy(self.container)])
            return self.result(code=1)
        if args[:2] == ["container", "ls"]:
            line = b"" if self.container is None else (self.identity + " " + self.container["Name"][1:] + "\n").encode()
            return self.result(line)
        if args[:2] == ["container", "start"]:
            assert (self.args.state_root / "probe-start-intent.json").exists()
            return self.result(state="timeout", code=None) if self.start_lost else self.result({"tool": self.tool, "subject_secure": not self.bad_tool, "watchdog_secure": False})
        if args[:2] == ["container", "rm"]:
            assert args == ["container", "rm", "--force", self.identity]
            self.container = None
            return self.result(state="timeout", code=None) if self.remove_lost else self.result(self.identity.encode())
        raise AssertionError("Unexpected device operation")


@pytest.fixture
def device(monkeypatch, helper, prepared_inputs):
    args, limits = prepared_inputs
    device = DockerDevice(helper, args, limits)

    class Lease:
        def __init__(self, argv, env, *, stdin, seconds, stdout_limit, stderr_limit):
            assert stdin == b"" and seconds > 0
            assert stdout_limit == stderr_limit == limits.helper_bytes
            assert env == {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "DOCKER_CONFIG": str(args.docker_config), "DOCKER_HOST": args.docker_endpoint}
            self.observation = device.dispatch(argv)

        def close(self, seconds):
            assert seconds == limits.cleanup_seconds
            return self.observation
    monkeypatch.setattr(helper, "CommandLease", Lease)
    return device


def test_actual_measurements_are_bound_only_after_probe_removal(helper, prepared_inputs, device):
    args, _ = prepared_inputs
    summary = helper.prepare(args)
    spec = helper.load_runtime(json.loads(args.spec_output.read_bytes()))
    assert summary["complete"] and summary["runtime_digest"] == spec.digest
    assert spec.docker_sha256 == digest_bytes(args.docker_binary.read_bytes())
    assert spec.tool_identity == digest_bytes(canonical_bytes(device.tool))
    assert spec.image_config_digest == digest_bytes(canonical_bytes(device.image_config))
    assert device.container is None
    assert sum(call[0] == "create" for call in device.calls) == 1
    assert sum(call[:2] == ["container", "start"] for call in device.calls) == 1
    assert helper.cleanup(args)["complete"]


def test_exact_dockerhub_normalization_preserves_observed_runtime_reference(helper, prepared_inputs, device):
    args, _ = prepared_inputs
    device.alias = "python@" + helper.IMAGE_DIGEST
    assert helper.prepare(args)["complete"]
    assert helper.load_runtime(json.loads(args.spec_output.read_bytes())).image_reference == device.alias


@pytest.mark.parametrize("fault", ["create_lost", "create_pending", "start_lost", "remove_lost", "bad_tool"])
def test_fault_never_publishes_or_replays_and_cleanup_recovers_without_spec(helper, prepared_inputs, device, fault):
    args, _ = prepared_inputs
    setattr(device, fault, True)
    with pytest.raises(RuntimeRefusal):
        helper.prepare(args)
    assert not args.spec_output.exists()
    assert (args.state_root / "preparation.json").exists()
    assert sum(call[0] == "create" for call in device.calls) == 1
    if fault in {"create_lost", "create_pending"}:
        assert not any(call[:2] == ["container", "start"] for call in device.calls)
    before = len(device.calls)
    device.remove_lost = False
    result = helper.cleanup(args)
    assert result["complete"] is (fault != "create_pending")
    assert not any(call[0] == "create" or call[:2] == ["container", "start"] for call in device.calls[before:])
    if fault == "create_pending":
        assert result["probe_cleanup"] == "pending_create"


def test_foreign_probe_is_not_started_or_removed(helper, prepared_inputs, device):
    args, _ = prepared_inputs
    device.foreign = True
    with pytest.raises(RuntimeRefusal, match="PROBE_OWNER_OR_CONFIG"):
        helper.prepare(args)
    with pytest.raises(RuntimeRefusal, match="PROBE_OWNER_OR_CONFIG"):
        helper.cleanup(args)
    assert device.container is not None
    assert not any(call[:2] in (["container", "start"], ["container", "rm"]) for call in device.calls)


def test_duplicate_preparation_preserves_original_claim_and_does_no_commands(helper, prepared_inputs, device):
    args, _ = prepared_inputs
    helper.prepare(args)
    original = (args.state_root / "preparation.json").read_bytes()
    calls = len(device.calls)
    with pytest.raises(FileExistsError):
        helper.prepare(args)
    assert len(device.calls) == calls
    assert (args.state_root / "preparation.json").read_bytes() == original


@pytest.mark.parametrize("mutate", ["extra", "missing", "bool", "nonfinite", "oversized"])
def test_all_limits_are_explicit_strict_and_bounded(helper, prepared_inputs, mutate):
    _, limits = prepared_inputs
    value = asdict(limits)
    if mutate == "extra":
        value["unknown"] = 1
    elif mutate == "missing":
        del value["stdin_bytes"]
    elif mutate == "bool":
        value["pids"] = True
    elif mutate == "nonfinite":
        value["wall_seconds"] = float("inf")
    else:
        value["helper_bytes"] = 4 * 1024 * 1024 + 1
    with pytest.raises(RuntimeRefusal):
        helper.load_limits(value)


@pytest.mark.parametrize("identity_record", ["created", "start"])
def test_cleanup_reconciles_actual_known_owned_verifier_intents(helper, prepared_inputs, device, monkeypatch, identity_record):
    args, _ = prepared_inputs
    helper.prepare(args)
    spec = helper.load_runtime(json.loads(args.spec_output.read_bytes()))
    intent_dir = args.state_root / "verifier" / "pytest-0" / "test-owned"
    intent_dir.mkdir(parents=True, mode=0o700)
    intent_dir.parent.chmod(0o700)
    owner = EvaluationOwner("123", "1", "runtime", "engineering-case", "d" * 32)
    runtime = DockerRuntime(spec, owner, intent_dir)
    try:
        intent = runtime.intent(case_id="case", snapshot="e" * 64, snapshot_path=intent_dir / "case.snapshot", watchdog_path=intent_dir / "watchdog.py", observer_path=intent_dir / "observer.py")
        runtime.record(intent.name + ".create-intent.json", asdict(intent))
        if identity_record == "created":
            runtime.record(intent.name + ".created.json", {"container_id": "f" * 64, "intent": asdict(intent)})
        else:
            runtime.record(intent.name + ".start-intent.json", {"container_id": "f" * 64})
    finally:
        runtime.close()
    monkeypatch.setattr(DockerRuntime, "command", lambda self, label, arguments, **kwargs: device.dispatch([str(spec.docker_executable), *arguments]))
    result = helper.cleanup(args)
    assert result["complete"] and result["owners"] == result["resources"] == 1
    assert list(intent_dir.glob("*.reconciliation-*.json"))
    assert not any(call[:2] == ["container", "rm"] and call[-1] == "f" * 64 for call in device.calls)


def test_inventory_refuses_ownerless_intent_and_does_not_follow_links(helper, prepared_inputs):
    args, _ = prepared_inputs
    root = args.state_root / "verifier"
    outside = args.state_root / "outside"
    outside.mkdir(mode=0o700)
    (outside / "foreign.create-intent.json").write_text("{}")
    (root / "current").symlink_to(outside, target_is_directory=True)
    assert helper.verifier_inventory(root) == []
    fd = open_private_directory(root)
    try:
        helper.record(fd, "orphan.create-intent.json", {"owner": "0" * 64})
    finally:
        os.close(fd)
    with pytest.raises(RuntimeRefusal, match="INVENTORY_MISSING_OWNER"):
        helper.verifier_inventory(root)
    assert (outside / "foreign.create-intent.json").read_text() == "{}"


def test_inventory_bound_counts_unknown_entries(helper, prepared_inputs, monkeypatch):
    args, _ = prepared_inputs
    root = args.state_root / "verifier"
    for index in range(3):
        (root / str(index)).write_bytes(b"")
    monkeypatch.setattr(helper, "MAX_ENTRIES", 2)
    with pytest.raises(RuntimeRefusal, match="INVENTORY_ENTRY_BOUND"):
        helper.verifier_inventory(root)


def test_spec_publication_failure_does_not_reexecute_probe(helper, prepared_inputs, device, monkeypatch):
    args, _ = prepared_inputs
    original = helper.record

    def fail_spec(directory, name, value):
        if name == "runtime-spec.json":
            raise RuntimeRefusal("PUBLICATION_VISIBLE_OR_UNKNOWN")
        return original(directory, name, value)
    monkeypatch.setattr(helper, "record", fail_spec)
    with pytest.raises(RuntimeRefusal, match="PUBLICATION_VISIBLE_OR_UNKNOWN"):
        helper.prepare(args)
    assert device.container is None and not args.spec_output.exists()
    before = len(device.calls)
    assert helper.cleanup(args)["complete"]
    assert not any(call[0] == "create" or call[:2] == ["container", "start"] for call in device.calls[before:])


def test_public_failure_is_body_and_path_free(helper, prepared_inputs, device, capsys):
    args, _ = prepared_inputs
    device.foreign = True
    code = helper.main(["prepare", "--image-reference", helper.IMAGE, "--docker-binary", str(args.docker_binary), "--docker-endpoint", args.docker_endpoint, "--docker-config", str(args.docker_config), "--state-root", str(args.state_root), "--limits-file", str(args.limits_file), "--spec-output", str(args.spec_output)])
    assert code == 1
    output = capsys.readouterr()
    result = json.loads(output.out)
    assert not result["complete"] and result["type"] == "RuntimeRefusal"
    assert "private diagnostic" not in output.out + output.err
    assert str(args.state_root) not in output.out + output.err
    assert device.tool["version"] not in output.out + output.err


@pytest.mark.parametrize("field", ["NetworkMode", "Privileged", "CapDrop", "Mounts", "Memory"])
def test_probe_drift_is_refused_before_start_and_removal(helper, prepared_inputs, device, field):
    args, _ = prepared_inputs
    original = device.probe_container

    def changed(arguments):
        value = original(arguments)
        value["HostConfig"][field] = {"NetworkMode": "host", "Privileged": True, "CapDrop": [], "Mounts": [{"Source": "/host"}], "Memory": 1}[field]
        return value
    device.probe_container = changed
    with pytest.raises(RuntimeRefusal):
        helper.prepare(args)
    with pytest.raises(RuntimeRefusal):
        helper.cleanup(args)
    assert device.container is not None and not args.spec_output.exists()
    assert not any(call[:2] in (["container", "start"], ["container", "rm"]) for call in device.calls)


def test_late_create_remains_owned_and_can_only_be_removed(helper, prepared_inputs, device):
    args, _ = prepared_inputs
    device.create_pending = True
    with pytest.raises(RuntimeRefusal):
        helper.prepare(args)
    assert not helper.cleanup(args)["complete"]
    create = next(call for call in device.calls if call[0] == "create")
    device.container = device.probe_container(create)
    before = len(device.calls)
    assert helper.cleanup(args)["complete"]
    assert device.container is None and not args.spec_output.exists()
    assert not any(call[0] == "create" or call[:2] == ["container", "start"] for call in device.calls[before:])
    assert (args.state_root / "preparation-failure.json").exists()


def test_publication_after_manifest_link_is_recoverable_before_spec(helper, prepared_inputs, device, monkeypatch):
    args, _ = prepared_inputs
    original = helper.private_write

    def published_then_failed(path, content, **kwargs):
        original(path, content, **kwargs)
        raise OSError("private path and body must not escape")
    monkeypatch.setattr(helper, "private_write", published_then_failed)
    with pytest.raises(OSError):
        helper.prepare(args)
    assert (args.state_root / "preparation.json").exists()
    assert not device.calls
    assert helper.cleanup(args)["complete"]


def test_replaced_private_config_is_not_adopted_on_recovery(helper, prepared_inputs, device):
    args, _ = prepared_inputs
    helper.prepare(args)
    args.docker_config.rename(args.state_root / "original-config")
    args.docker_config.mkdir(mode=0o700)
    before = len(device.calls)
    with pytest.raises(RuntimeRefusal, match="PREPARATION_DIRECTORY_IDENTITY"):
        helper.cleanup(args)
    assert len(device.calls) == before


def test_inspection_with_wrong_full_id_is_never_removed(helper, prepared_inputs, device):
    args, _ = prepared_inputs
    device.start_lost = True
    with pytest.raises(RuntimeRefusal):
        helper.prepare(args)
    device.container["Id"] = "0" * 64
    before = len(device.calls)
    with pytest.raises(RuntimeRefusal, match="PROBE_CONTAINER_IDENTITY"):
        helper.cleanup(args)
    assert not any(call[:2] == ["container", "rm"] for call in device.calls[before:])
