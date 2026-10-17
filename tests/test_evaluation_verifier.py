from __future__ import annotations

import base64
import copy
import os
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from agents_memory import evaluation_runtime as runtime
from agents_memory import evaluation_verifier as verifier
from agents_memory.evaluation_artifacts import (
    ArtifactBundle,
    ArtifactEntry,
    ArtifactError,
    ArtifactLimits,
    ByteEdit,
    EditableSpan,
    EditPolicy,
    EditWitness,
    ModePermission,
    canonical_bytes,
    digest_bytes,
    load_submission,
    materialize_snapshot,
    verify_allowed_edits,
)
from agents_memory.evaluation_runtime import (
    OBSERVER_SOURCE,
    WATCHDOG_SOURCE,
    CleanupObservation,
    CommandObservation,
    DockerRuntime,
    EvaluationOwner,
    RuntimeLimits,
    RuntimeRefusal,
    RuntimeSpec,
    SubjectObservation,
    publish_or_reconcile,
)
from agents_memory.evaluation_verifier import FileExpectation, OracleCase, compare_case
from agents_memory.private_io import private_write


@pytest.fixture
def limits():
    return ArtifactLimits(65536, 50, 4096, 8192, 8, 512, 128, 20, 8192)


def entry(path, content=b"", *, kind="file", mode=0o644):
    return ArtifactEntry(path, kind, mode, content, digest_bytes(content))


def bundle(limits, content=b"keep\nold\nkeep\n"):
    return ArtifactBundle((entry("a.py", content), entry("retained", b"exact\r\n")), limits)


def witness(before, after, edits=(), creates=(), deletes=(), modes=()):
    return EditWitness(before.digest, after.digest, edits, creates, deletes, modes)


def test_exact_witness_preserves_all_other_bytes(limits):
    before = bundle(limits)
    after = bundle(limits, b"keep\nnew\nkeep\n")
    policy = EditPolicy(before.digest, (EditableSpan("a.py", 5, 8),), (), (), ())
    proof = witness(before, after, (ByteEdit("a.py", 5, 8, b"new"),))
    assert verify_allowed_edits(before, after, policy, proof).passed
    assert before.entries[0].content == b"keep\nold\nkeep\n"


@pytest.mark.parametrize("change", ["truncation", "unrelated", "delete", "hidden", "mode", "newline"])
def test_desired_value_does_not_authorize_other_changes(limits, change):
    before = bundle(limits)
    entries = [entry("a.py", b"keep\nnew\nkeep\n"), entry("retained", b"exact\r\n")]
    if change == "truncation":
        entries[0] = entry("a.py", b"keep\nnew\n")
    elif change == "unrelated":
        entries[1] = entry("retained", b"changed")
    elif change == "delete":
        entries.pop()
    elif change == "hidden":
        entries.append(entry(".hidden", b"new"))
    elif change == "mode":
        entries[0] = replace(entries[0], mode=0o755)
    else:
        entries[1] = entry("retained", b"exact\n")
    after = ArtifactBundle(tuple(sorted(entries, key=lambda item: item.path)), limits)
    policy = EditPolicy(before.digest, (EditableSpan("a.py", 5, 8),), (), (), ())
    assert not verify_allowed_edits(before, after, policy, witness(before, after, (ByteEdit("a.py", 5, 8, b"new"),))).passed


@pytest.mark.parametrize("path", ["/absolute", "../escape", "a/../escape", "a//b", "a\\b", "a:b", "a/", "a\x00b", "a\nb", "x."])
def test_bundle_refuses_ambiguous_paths(limits, path):
    with pytest.raises(ArtifactError):
        ArtifactBundle((entry(path),), limits)


def test_bundle_requires_explicit_directories_and_case_identity(limits):
    with pytest.raises(ArtifactError, match="ALL_PATHS"):
        ArtifactBundle((entry("missing/a"),), limits)
    with pytest.raises(ArtifactError, match="CASE_AMBIGUOUS"):
        ArtifactBundle((entry("A"), entry("a")), limits)
    with pytest.raises(ArtifactError, match="CASE_AMBIGUOUS"):
        ArtifactBundle((entry("a"), entry("a")), limits)


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "socket", "fifo", "device", "archive"])
def test_bundle_only_contains_literal_files_and_directories(kind):
    with pytest.raises(ArtifactError, match="ENTRY_TYPE"):
        entry("a", kind=kind)


def test_all_bounds_and_digest_are_enforced(limits):
    with pytest.raises(ArtifactError, match="CONTENT_DIGEST"):
        ArtifactEntry("a", "file", 0o644, b"a", "0" * 64)
    with pytest.raises(ArtifactError, match="ENTRY_MODE"):
        entry("a", mode=0o4755)
    with pytest.raises(ArtifactError, match="ENTRY_BOUND"):
        ArtifactBundle((entry("a"), entry("b")), replace(limits, entries=1))
    with pytest.raises(ArtifactError, match="FILE_BOUND"):
        ArtifactBundle((entry("a", b"long"),), replace(limits, file_bytes=3))
    with pytest.raises(ArtifactError, match="TOTAL_BOUND"):
        ArtifactBundle((entry("a", b"abc"), entry("b", b"abc")), replace(limits, total_bytes=5))


def test_load_bundle_is_literal_and_immutable(tmp_path, limits):
    before = bundle(limits)
    path = tmp_path / "submission.json"
    path.write_bytes(before.to_bytes())
    loaded = load_submission(path, limits=limits)
    path.write_bytes(b"not the previous bytes")
    assert loaded == before
    assert loaded.digest == before.digest


def test_load_rejects_duplicate_keys_symlinks_hardlinks_and_intermediate_links(tmp_path, limits):
    path = tmp_path / "bundle"
    path.write_bytes(b'{"schema":1,"schema":1,"entries":[]}')
    with pytest.raises(ValueError):
        load_submission(path, limits=limits)
    path.write_bytes(bundle(limits).to_bytes())
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(OSError):
        load_submission(link, limits=limits)
    directory_link = tmp_path / "directory-link"
    directory_link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(OSError):
        load_submission(directory_link / "bundle", limits=limits)
    os.link(path, tmp_path / "hard")
    with pytest.raises(ArtifactError):
        load_submission(path, limits=limits)


def test_loader_rejects_content_truncation_and_unknown_fields(tmp_path, limits):
    value = {"schema": 1, "entries": [{"path": "a", "kind": "file", "mode": 0o644, "size": 3, "sha256": digest_bytes(b"abc"), "content": base64.b64encode(b"ab").decode()}]}
    path = tmp_path / "bundle"
    path.write_bytes(canonical_bytes(value))
    with pytest.raises(ArtifactError):
        load_submission(path, limits=limits)
    value["entries"][0]["kind"] = "symlink"
    value["entries"][0]["target"] = "/etc/passwd"
    path.write_bytes(canonical_bytes(value))
    with pytest.raises(ArtifactError):
        load_submission(path, limits=limits)


def test_snapshot_materializes_exact_modes_and_never_replaces(tmp_path, limits):
    tmp_path.chmod(0o700)
    before = ArtifactBundle((entry("d", kind="directory", mode=0o755), entry("d/a", b"\x00literal", mode=0o640)), limits)
    target = tmp_path / "snapshot"
    materialize_snapshot(before, target)
    assert (target / "d/a").read_bytes() == b"\x00literal"
    assert (target / "d/a").stat().st_mode & 0o777 == 0o640
    with pytest.raises(FileExistsError):
        materialize_snapshot(before, target)


def test_overlapping_witness_and_wrong_identity_are_refused(limits):
    before = bundle(limits)
    policy = EditPolicy(before.digest, (EditableSpan("a.py", 0, 14),), (), (), ())
    overlap = witness(before, before, (ByteEdit("a.py", 0, 5, b""), ByteEdit("a.py", 4, 8, b"")))
    assert verify_allowed_edits(before, before, policy, overlap).code == "EDIT_OVERLAP_OR_ORDER"
    assert not verify_allowed_edits(before, before, policy, replace(overlap, baseline_digest="0" * 64)).passed


def test_explicit_creates_deletes_modes_are_exact(limits):
    before = bundle(limits)
    after = ArtifactBundle((entry("a.py", before.entries[0].content, mode=0o755), entry("created", b"new")), limits)
    mode = ModePermission("a.py", 0o644, 0o755)
    policy = EditPolicy(before.digest, (), ("created",), ("retained",), (mode,))
    proof = witness(before, after, creates=(entry("created", b"new"),), deletes=("retained",), modes=(mode,))
    assert verify_allowed_edits(before, after, policy, proof).passed
    assert not verify_allowed_edits(before, after, replace(policy, creates=()), proof).passed


@pytest.fixture
def runtime_spec(tmp_path):
    limits = RuntimeLimits(1_000_000_000, 128 * 1024 * 1024, 32, 64, 1024 * 1024, 8 * 1024 * 1024, 8 * 1024 * 1024, 1024 * 1024, 1, 10, 2, 2, 65536, 65536, 65536, 1024 * 1024)
    config = tmp_path / "docker-config"
    config.mkdir(mode=0o700)
    return RuntimeSpec(Path("/usr/bin/docker"), "1" * 64, config, "unix:///var/run/docker.sock", "python@sha256:" + "2" * 64, "sha256:" + "3" * 64, "4" * 64, (), "/usr/local/bin/python3", "5" * 64, digest_bytes(WATCHDOG_SOURCE), digest_bytes(OBSERVER_SOURCE), limits)


def owner():
    return EvaluationOwner("123", "1", "engineering", "attempt", "a" * 32)


def container_fixture(spec, intent):
    limit = spec.limits
    expected_mounts = {"/artifact": intent.snapshot_path, "/watchdog.py": intent.watchdog_path, "/observer.py": intent.observer_path}
    return {"Id": "b" * 64, "Name": "/" + intent.name, "Image": spec.image_id, "State": {"Running": True}, "Config": {"Labels": {runtime.OWNER_LABEL: intent.owner, runtime.CONFIG_LABEL: intent.configuration}, "User": "0:0", "WorkingDir": "/", "Entrypoint": [spec.python_executable], "Cmd": ["-I", "-S", "/watchdog.py", str(limit.watchdog_seconds)], "Env": list(spec.image_environment)}, "Mounts": [{"Type": "bind", "Source": source, "Destination": target, "RW": False, "Propagation": "rprivate"} for target, source in expected_mounts.items()], "HostConfig": {"ReadonlyRootfs": True, "Privileged": False, "NetworkMode": "none", "IpcMode": "private", "PidMode": "", "UsernsMode": "", "CgroupnsMode": "private", "NanoCpus": limit.cpu_nanos, "Memory": limit.memory_bytes, "MemorySwap": limit.memory_bytes, "PidsLimit": limit.pids, "ShmSize": limit.shm_bytes, "PublishAllPorts": False, "CapDrop": ["ALL"], "SecurityOpt": ["no-new-privileges:true"], "RestartPolicy": {"Name": "no"}, "LogConfig": {"Type": "none"}, "Ulimits": [{"Name": name, "Soft": soft, "Hard": hard} for name, soft, hard in (("nofile", limit.file_descriptors, limit.file_descriptors), ("fsize", limit.file_bytes, limit.file_bytes), ("core", 0, 0))], "Tmpfs": {"/scratch": f"rw,nosuid,nodev,noexec,size={limit.scratch_bytes},mode=1777", "/tmp": f"rw,nosuid,nodev,noexec,size={limit.tmp_bytes},mode=1777"}, "Mounts": [{"Type": "bind", "Source": source, "Target": target, "ReadOnly": True, "BindOptions": {"Propagation": "rprivate", "NonRecursive": True}} for target, source in expected_mounts.items()]}}


@pytest.fixture
def owned_runtime(tmp_path, runtime_spec):
    tmp_path.chmod(0o700)
    instance = DockerRuntime(runtime_spec, owner(), tmp_path)
    intent = instance.intent(case_id="engineering-fixture", snapshot="c" * 64, snapshot_path=tmp_path / "snapshot", watchdog_path=tmp_path / "watchdog", observer_path=tmp_path / "observer")
    try:
        yield instance, intent
    finally:
        instance.close()


@pytest.mark.parametrize("mutation", ["owner", "id", "network", "writable", "extra-mount", "recursive", "privileged", "volume", "caps"])
def test_container_inspection_rejects_authority_drift(owned_runtime, mutation):
    instance, intent = owned_runtime
    value = container_fixture(instance.spec, intent)
    assert instance.validate_container(value, intent, "b" * 64) == "b" * 64
    value = copy.deepcopy(value)
    if mutation == "owner":
        value["Config"]["Labels"][runtime.OWNER_LABEL] = "foreign"
    elif mutation == "id":
        value["Id"] = "c" * 64
    elif mutation == "network":
        value["HostConfig"]["NetworkMode"] = "host"
    elif mutation == "writable":
        value["Mounts"][0]["RW"] = True
    elif mutation == "extra-mount":
        value["Mounts"].append({"Type": "bind", "Source": "/var/run/docker.sock"})
    elif mutation == "recursive":
        value["HostConfig"]["Mounts"][0]["BindOptions"]["NonRecursive"] = False
    elif mutation == "privileged":
        value["HostConfig"]["Privileged"] = True
    elif mutation == "volume":
        value["Config"]["Volumes"] = {"/extra": {}}
    else:
        value["HostConfig"]["CapAdd"] = ["SYS_ADMIN"]
    with pytest.raises(RuntimeRefusal):
        instance.validate_container(value, intent, "b" * 64)


def test_foreign_cleanup_never_calls_remove(owned_runtime, monkeypatch):
    instance, intent = owned_runtime
    value = container_fixture(instance.spec, intent)
    value["Config"]["Labels"][runtime.OWNER_LABEL] = "foreign"
    monkeypatch.setattr(instance, "inspect", lambda identity: value)
    def forbidden(*args, **kwargs):
        raise AssertionError("foreign resource mutation")
    monkeypatch.setattr(instance, "command", forbidden)
    result = instance.cleanup(intent, "b" * 64, create_uncertain=False)
    assert not result.exact_absence and not result.ownership_verified


def test_absence_does_not_resolve_pending_create(owned_runtime, monkeypatch):
    instance, intent = owned_runtime
    monkeypatch.setattr(instance, "inspect", lambda identity: None)
    result = instance.cleanup(intent, None, create_uncertain=True)
    assert result.pending_create and not result.exact_absence
    result = instance.cleanup(intent, "b" * 64, create_uncertain=False)
    assert result.exact_absence


def test_lost_remove_response_retains_ambiguity(owned_runtime, monkeypatch):
    instance, intent = owned_runtime
    values = iter([container_fixture(instance.spec, intent), None])
    monkeypatch.setattr(instance, "inspect", lambda identity: next(values))
    monkeypatch.setattr(instance, "command", lambda *args, **kwargs: CommandObservation("timeout", None, b"", b"", 1, False, False, True))
    result = instance.cleanup(intent, "b" * 64, create_uncertain=False)
    assert result.exact_absence and result.state == "removal_unknown"


def observation(stdout=b"answer\n", *, state="completed", exit_code=0, cleanup=True):
    command = CommandObservation(state, exit_code, stdout, b"", 1, True, True, True)
    return SubjectObservation("functional", state, command, (), CleanupObservation("removed" if cleanup else "removal_unknown", "b" * 64, cleanup, True, False), "b" * 64, "c" * 64, ())


def test_outer_oracle_does_not_trust_candidate_success_records():
    case = OracleCase("functional", ("/candidate",), b"input", b"answer\n", b"", 0, ())
    assert compare_case(case, observation()).passed
    for stdout in (b'{"success":true,"passed":999}', b"", b"plausible-but-wrong\n"):
        assert not compare_case(case, observation(stdout)).passed
    assert not compare_case(case, observation(state="timeout")).passed
    assert not compare_case(case, observation(state="output_limit")).passed
    assert not compare_case(case, observation(cleanup=False)).passed


def test_publication_recovers_post_link_fsync_error_without_reexecution(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    descriptor = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    original = runtime.private_write
    calls = []
    def after_link(*args, **kwargs):
        calls.append(1)
        original(*args, **kwargs)
        raise OSError("engineering post-publication fault")
    monkeypatch.setattr(runtime, "private_write", after_link)
    try:
        result = publish_or_reconcile(descriptor, "receipt.json", b"exact private bytes")
        assert result.state == "reconciled_durable"
        assert len(calls) == 1
        conflict = publish_or_reconcile(descriptor, "receipt.json", b"different")
        assert conflict.state == "conflict"
        assert (tmp_path / "receipt.json").read_bytes() == b"exact private bytes"
    finally:
        os.close(descriptor)


@pytest.mark.parametrize("lost", ["create", "start"])
def test_lost_mutation_response_never_replays_or_executes(owned_runtime, monkeypatch, lost):
    instance, intent = owned_runtime
    value = container_fixture(instance.spec, intent)
    calls = []
    removed = False
    def inspect(identity):
        return None if removed else value
    def command(label, argv, **kwargs):
        nonlocal removed
        calls.append(label)
        if label == lost:
            return CommandObservation("timeout", None, b"", b"", 1, False, False, True)
        if label == "remove":
            removed = True
        return CommandObservation("completed", 0, (("b" * 64) + "\n").encode(), b"", 1, True, True, True)
    monkeypatch.setattr(instance, "inspect", inspect)
    monkeypatch.setattr(instance, "command", command)
    result = instance.run(intent, ("/candidate",), b"", ())
    assert result.state == lost + "_unknown"
    assert result.cleanup.exact_absence
    assert calls.count(lost) == 1
    assert "tool" not in calls and result.execution is None
    if lost == "create":
        assert "start" not in calls
    reopened = DockerRuntime(instance.spec, instance.owner, instance.intent_dir)
    try:
        monkeypatch.setattr(reopened, "inspect", lambda identity: None)
        recovered = reopened.reconcile_all(maximum_entries=30, maximum_intents=5)
        assert len(recovered) == 1
        assert recovered[0].container_id == "b" * 64
        assert recovered[0].exact_absence and not recovered[0].pending_create
        assert calls.count(lost) == 1 and "tool" not in calls
    finally:
        reopened.close()


def test_changed_resource_intent_cannot_supply_host_argv(owned_runtime):
    instance, intent = owned_runtime
    with pytest.raises(RuntimeRefusal, match="RESOURCE_INTENT_CHANGED"):
        instance.run(replace(intent, create_argv=("run", "--privileged", "foreign")), ("/candidate",), b"", ())


def test_watchdog_requires_an_effective_lifetime_margin(owned_runtime):
    instance, intent = owned_runtime
    with pytest.raises(RuntimeRefusal, match="WATCHDOG_OPERATION_MARGIN"):
        instance.run(intent, ("/candidate",), b"", (("output", 10),))


def test_file_effect_comparison_stays_in_outer_oracle():
    case = OracleCase("functional", ("/candidate",), b"input", b"answer\n", b"", 0, (FileExpectation("result", 32, b"expected"),))
    assert compare_case(case, replace(observation(), effects=(("result", b"expected"),))).passed
    assert not compare_case(case, replace(observation(), effects=(("result", b'{"success": true}'),))).passed
    assert not compare_case(case, replace(observation(), effects=(("result", None),))).passed


def test_cleanup_rejects_foreign_intent_before_daemon_access(owned_runtime, monkeypatch):
    instance, intent = owned_runtime
    def forbidden(*args, **kwargs):
        raise AssertionError("foreign intent must not reach daemon")
    monkeypatch.setattr(instance, "inspect", forbidden)
    result = instance.cleanup(replace(intent, owner="f" * 64), "b" * 64, create_uncertain=False)
    assert not result.exact_absence and not result.ownership_verified


def test_crash_recovery_uses_durable_owner_and_full_id(owned_runtime, monkeypatch):
    instance, intent = owned_runtime
    saved_owner = instance.read_private_record(instance.owner.identity + ".owner.json")
    assert saved_owner["owner"] == asdict(instance.owner)
    instance.record(intent.name + ".create-intent.json", asdict(intent))
    instance.record(intent.name + ".created.json", {"container_id": "b" * 64, "intent": asdict(intent)})
    observed_ids = []
    def absent(identity):
        observed_ids.append(identity)
        return None
    monkeypatch.setattr(instance, "inspect", absent)
    result = instance.reconcile_all(maximum_entries=30, maximum_intents=5)
    assert len(result) == 1 and result[0].exact_absence
    assert observed_ids == ["b" * 64]


def test_crash_recovery_does_not_clear_an_unobserved_late_create(owned_runtime, monkeypatch):
    instance, intent = owned_runtime
    instance.record(intent.name + ".create-intent.json", asdict(intent))
    monkeypatch.setattr(instance, "inspect", lambda identity: None)
    result = instance.reconcile_all(maximum_entries=30, maximum_intents=5)
    assert result[0].pending_create and not result[0].exact_absence


def test_duplicate_claim_cannot_publish_over_inflight_observations(tmp_path, runtime_spec, limits, monkeypatch):
    tmp_path.chmod(0o700)
    before = bundle(limits, b"old")
    correct = bundle(limits, b"new")
    wrong = bundle(limits, b"bad")
    policy = EditPolicy(before.digest, (EditableSpan("a.py", 0, 3),), (), (), ())
    correct_proof = witness(before, correct, (ByteEdit("a.py", 0, 3, b"new"),))
    case = OracleCase("functional", ("/candidate",), b"", b"answer\n", b"", 0, ())
    task = verifier.OracleTask("engineering-claim-race", "1", "engineering-only", before.digest, policy, correct_proof, (case,))
    spec = verifier.VerifierSpec(runtime_spec, "d" * 64, verifier.verifier_source_digest(), 3, 1, 1024 * 1024)
    executor = verifier.VerifierExecutor(spec, owner(), tmp_path)
    controls = (
        verifier.ControlArtifact("correct", correct, correct_proof),
        verifier.ControlArtifact("noop", before, witness(before, before)),
        verifier.ControlArtifact("plausible_wrong", wrong, witness(before, wrong, (ByteEdit("a.py", 0, 3, b"bad"),))),
    )
    monkeypatch.setattr(DockerRuntime, "preflight", lambda self: None)
    executed = []
    def run(self, intent, *args, **kwargs):
        executed.append(intent.case_id)
        return observation(b"answer\n" if intent.snapshot == correct.digest else b"wrong\n")
    monkeypatch.setattr(DockerRuntime, "run", run)
    approval = verifier.IndependentControlApproval(task.digest, verifier.controls_digest(controls), "engineering-only")
    assert executor.precheck(before, task, controls, approval).eligible
    duplicates = []
    def paused_after_claim(self):
        names = set(tmp_path.iterdir())
        duplicate = executor.verify(before, correct, task)
        duplicates.append(duplicate)
        assert duplicate.error_code == "ATTEMPT_CLAIM_UNKNOWN_OR_EXISTING"
        assert duplicate.private_artifact is None and duplicate.terminal_artifact is None
        assert set(tmp_path.iterdir()) == names
    monkeypatch.setattr(DockerRuntime, "preflight", paused_after_claim)
    result = executor.verify(before, correct, task)
    assert len(duplicates) == 1 and len(executed) == 4
    assert result.success and result.error_code is None
    assert result.publication.state in {"durable", "reconciled_durable"}
    private = (tmp_path / result.private_artifact).read_bytes()
    assert digest_bytes(private) == result.private_sha256
    assert b"YW5zd2VyCg==" in private


def test_completed_nonzero_exit_still_observes_declared_effects(owned_runtime, monkeypatch):
    instance, _ = owned_runtime
    instance.spec = replace(instance.spec, limits=replace(instance.spec.limits, watchdog_seconds=30))
    intent = instance.intent(case_id="nonzero-effect", snapshot="c" * 64, snapshot_path=instance.intent_dir / "snapshot", watchdog_path=instance.intent_dir / "watchdog", observer_path=instance.intent_dir / "observer")
    removed = False
    calls = []
    def command(label, args, **kwargs):
        nonlocal removed
        calls.append(label)
        if label == "remove":
            removed = True
        raw = (("b" * 64) + "\n").encode()
        if label == "tool":
            raw = canonical_bytes({"watchdog_secure": True, "subject_secure": True, "tool": {"engineering": True}})
        elif label == "effect":
            raw = canonical_bytes({"content": base64.b64encode(b"error report").decode(), "size": 12})
        return CommandObservation("completed", 0, raw, b"", 1, True, True, True)
    instance.spec = replace(instance.spec, tool_identity=digest_bytes(canonical_bytes({"engineering": True})))
    intent = instance.intent(case_id=intent.case_id, snapshot=intent.snapshot, snapshot_path=Path(intent.snapshot_path), watchdog_path=Path(intent.watchdog_path), observer_path=Path(intent.observer_path))
    value = container_fixture(instance.spec, intent)
    monkeypatch.setattr(instance, "inspect", lambda identity: None if removed else value)
    monkeypatch.setattr(instance, "command", command)
    class CompletedSubject:
        def __init__(self, *args, **kwargs):
            self.observation = CommandObservation("completed", 2, b"", b"", 1, True, True, True)
        def close(self, seconds):
            return self.observation
    monkeypatch.setattr(runtime, "CommandLease", CompletedSubject)
    result = instance.run(intent, ("/candidate",), b"", (("report", 32),))
    case = OracleCase("nonzero-effect", ("/candidate",), b"", b"", b"", 2, (FileExpectation("report", 32, b"error report"),))
    assert result.effects == (("report", b"error report"),)
    assert calls.count("effect") == 1 and result.execution.exit_code == 2
    assert compare_case(case, result).passed
    assert not compare_case(replace(case, expected_exit=0), result).passed


@pytest.mark.parametrize("record_kind", ["owner", "created"])
def test_recovery_reconciles_only_private_writer_temporary_links(owned_runtime, monkeypatch, record_kind):
    instance, intent = owned_runtime
    instance.record(intent.name + ".create-intent.json", asdict(intent))
    created_name = intent.name + ".created.json"
    instance.record(created_name, {"container_id": "b" * 64, "intent": asdict(intent)})
    name = instance.owner.identity + ".owner.json" if record_kind == "owner" else created_name
    temporary = instance.intent_dir / ".memory-private-0123456789abcdef"
    os.link(instance.intent_dir / name, temporary)
    reopened = DockerRuntime(instance.spec, instance.owner, instance.intent_dir)
    try:
        assert reopened.read_private_record(name)
        assert not temporary.exists()
        assert (instance.intent_dir / name).stat().st_nlink == 1
        monkeypatch.setattr(reopened, "inspect", lambda identity: None)
        result = reopened.reconcile_all(maximum_entries=30, maximum_intents=5)
        assert result[0].container_id == "b" * 64
        assert result[0].exact_absence and not result[0].pending_create
    finally:
        reopened.close()


@pytest.mark.parametrize("link_kind", ["unrecognized", "mismatched", "symlink", "extra-link", "nonprivate", "foreign"])
def test_recovery_rejects_unproven_publication_links(owned_runtime, monkeypatch, link_kind):
    instance, _ = owned_runtime
    name = "private-record.json"
    raw = canonical_bytes({"engineering": True})
    private_write(instance.intent_dir / name, raw, directory=instance.directory)
    target = instance.intent_dir / name
    temporary = instance.intent_dir / ".memory-private-0123456789abcdef"
    if link_kind in {"mismatched", "symlink"}:
        private_write(temporary, raw, directory=instance.directory)
        if link_kind == "symlink":
            temporary.unlink()
            temporary.symlink_to(target)
        os.link(target, instance.intent_dir / "unrecognized")
    else:
        os.link(target, instance.intent_dir / "unrecognized" if link_kind == "unrecognized" else temporary)
        if link_kind == "extra-link":
            os.link(target, instance.intent_dir / ".memory-private-fedcba9876543210")
        elif link_kind == "nonprivate":
            target.chmod(0o644)
        elif link_kind == "foreign":
            monkeypatch.setattr(runtime.os, "getuid", lambda: target.stat().st_uid + 1)
    with pytest.raises(RuntimeRefusal, match="RECOVERY_RECORD_IDENTITY"):
        instance.read_private_record(name)
    assert target.read_bytes() == raw and target.stat().st_nlink >= 2
    if link_kind != "unrecognized":
        assert temporary.exists()


def test_publication_recovers_actual_private_writer_unlink_interruption(owned_runtime, monkeypatch):
    instance, _ = owned_runtime
    original_unlink = os.unlink
    interrupted = []
    def interrupt_once(path, *, dir_fd=None):
        if str(path).startswith(".memory-private-") and dir_fd == instance.directory and not interrupted:
            interrupted.append(str(path))
            raise OSError("engineering interruption before temporary cleanup")
        return original_unlink(path, dir_fd=dir_fd)
    monkeypatch.setattr(runtime.os, "unlink", interrupt_once)
    value = {"engineering": "retained exact observation"}
    result = publish_or_reconcile(instance.directory, "interrupted.json", canonical_bytes(value))
    assert result.state == "reconciled_durable" and len(interrupted) == 1
    assert instance.read_private_record("interrupted.json") == value
    assert not (instance.intent_dir / interrupted[0]).exists()
    assert (instance.intent_dir / "interrupted.json").stat().st_nlink == 1
