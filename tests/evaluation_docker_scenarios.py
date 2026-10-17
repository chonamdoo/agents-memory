from __future__ import annotations

import os
import secrets
from dataclasses import asdict, replace
from pathlib import Path
from threading import Event

import pytest

from agents_memory.evaluation_artifacts import (
    ArtifactBundle,
    ArtifactEntry,
    ArtifactLimits,
    ByteEdit,
    EditableSpan,
    EditPolicy,
    EditWitness,
    digest_bytes,
    materialize_snapshot,
)
from agents_memory.evaluation_runtime import (
    OBSERVER_SOURCE,
    WATCHDOG_SOURCE,
    CleanupObservation,
    CommandObservation,
    DockerRuntime,
    EvaluationOwner,
    RuntimeLimits,
    RuntimeSpec,
)
from agents_memory.evaluation_verifier import (
    ControlArtifact,
    FileExpectation,
    IndependentControlApproval,
    OracleCase,
    OracleTask,
    VerifierExecutor,
    VerifierSpec,
    compare_case,
    controls_digest,
    verifier_source_digest,
)
from agents_memory.private_io import private_read, private_write
from agents_memory.wire import decode_json


@pytest.fixture
def prepared_runtime():
    name = os.environ.get("AGENTS_MEMORY_EVALUATION_RUNTIME_SPEC")
    if not name:
        pytest.fail("Explicit Actions-only engineering runtime specification is required")
    value = decode_json(private_read(Path(name), 65536))
    value["docker_executable"] = Path(value["docker_executable"])
    value["docker_config"] = Path(value["docker_config"])
    value["image_environment"] = tuple(value["image_environment"])
    value["limits"] = RuntimeLimits(**value["limits"])
    return RuntimeSpec(**value)


def actual_owner():
    return EvaluationOwner(os.environ["GITHUB_RUN_ID"], os.environ["GITHUB_RUN_ATTEMPT"], os.environ["GITHUB_JOB"], "engineering-" + secrets.token_hex(8), secrets.token_hex(16))


def file_entry(path, raw):
    return ArtifactEntry(path, "file", 0o644, raw, digest_bytes(raw))


def program_bundle(raw):
    limits = ArtifactLimits(262144, 20, 65536, 131072, 8, 512, 128, 20, 131072)
    return ArtifactBundle((file_entry("solve.py", raw), file_entry("unchanged.txt", b"retained exact bytes\r\n")), limits)


def proof(before, after):
    edits = () if before.digest == after.digest else (ByteEdit("solve.py", 0, len(before.entries[0].content), after.entries[0].content),)
    return EditWitness(before.digest, after.digest, edits, (), (), ())


def test_actual_controls_outer_oracle_and_exact_retention(tmp_path, prepared_runtime, monkeypatch):
    tmp_path.chmod(0o700)
    before = program_bundle(b"import sys\nprint(int(sys.stdin.read()))\n")
    correct = program_bundle(b"import sys\nprint(int(sys.stdin.read()) + 1)\n")
    wrong = program_bundle(b"import sys\nprint(int(sys.stdin.read()) + 2)\n")
    policy = EditPolicy(before.digest, (EditableSpan("solve.py", 0, len(before.entries[0].content)),), (), (), ())
    cases = tuple(OracleCase("number-" + str(index), (prepared_runtime.python_executable, "-I", "-S", "/artifact/solve.py"), str(number).encode(), (str(number + 1) + "\n").encode(), b"", 0, ()) for index, number in enumerate((0, -7, 23)))
    task = OracleTask("engineering-not-human-gold", "fixture-1", "engineering-fixture-not-independent-human-approval", before.digest, policy, proof(before, correct), cases)
    spec = VerifierSpec(prepared_runtime, digest_bytes(Path(__file__).read_bytes()), verifier_source_digest(), 10, 10, 128 * 1024 * 1024)
    executor = VerifierExecutor(spec, actual_owner(), tmp_path)
    controls = (ControlArtifact("correct", correct, proof(before, correct)), ControlArtifact("noop", before, proof(before, before)), ControlArtifact("plausible_wrong", wrong, proof(before, wrong)))
    approval = IndependentControlApproval(task.digest, controls_digest(controls), "engineering-fixture-only-not-acceptance")
    precheck = executor.precheck(before, task, controls, approval)
    assert precheck.eligible
    assert [receipt.success for receipt in precheck.receipts] == [True, False, False]
    original_run = DockerRuntime.run
    duplicates = []
    def paused_after_claim(instance, *args, **kwargs):
        names = set(tmp_path.iterdir())
        duplicate = executor.verify(before, correct, task)
        duplicates.append(duplicate)
        assert duplicate.error_code == "ATTEMPT_CLAIM_UNKNOWN_OR_EXISTING"
        assert duplicate.private_artifact is None and duplicate.terminal_artifact is None
        assert set(tmp_path.iterdir()) == names
        return original_run(instance, *args, **kwargs)
    monkeypatch.setattr(DockerRuntime, "run", paused_after_claim)
    receipt = executor.verify(before, correct, task)
    assert receipt.success and receipt.cleanup_complete
    assert receipt.publication.state in {"durable", "reconciled_durable"}
    assert len(duplicates) == len(cases)
    monkeypatch.setattr(DockerRuntime, "run", original_run)
    replay = executor.verify(before, correct, task)
    assert not replay.success and replay.error_code == "ATTEMPT_CLAIM_UNKNOWN_OR_EXISTING"
    damaged = ArtifactBundle((file_entry("solve.py", correct.entries[0].content), file_entry("unchanged.txt", b"deleted retained line")), before.limits)
    rejected = executor.verify(before, damaged, replace(task, witness=proof(before, damaged)))
    assert not rejected.success and not rejected.structural.passed
    assert all(case.observation is None for case in rejected.cases)


@pytest.fixture
def actual_runtime(tmp_path, prepared_runtime):
    tmp_path.chmod(0o700)
    instance = DockerRuntime(prepared_runtime, actual_owner(), tmp_path)
    instance.preflight()
    try:
        yield instance
    finally:
        instance.close()


def contained_program(instance, raw, *, effects=(), stop_event=None):
    before = program_bundle(raw)
    stem = secrets.token_hex(16)
    snapshot = instance.intent_dir / (stem + ".snapshot")
    instance.record(stem + ".snapshot-intent.json", {"digest": before.digest, "path": str(snapshot)})
    materialize_snapshot(before, snapshot)
    watchdog = instance.intent_dir / (stem + ".watchdog.py")
    observer = instance.intent_dir / (stem + ".observer.py")
    for path, source in ((watchdog, WATCHDOG_SOURCE), (observer, OBSERVER_SOURCE)):
        instance.record(path.name + ".intent.json", {"sha256": digest_bytes(source)})
        private_write(path, source, directory=instance.directory)
        path.chmod(0o444)
    intent = instance.intent(case_id=stem, snapshot=before.digest, snapshot_path=snapshot, watchdog_path=watchdog, observer_path=observer)
    result = instance.run(intent, (instance.spec.python_executable, "-I", "-S", "/artifact/solve.py"), b"", effects, stop_event=stop_event)
    return result


class ScenarioFailure(AssertionError):
    def __init__(self, code):
        super().__init__(code)
        self.ci_failure_code = code


def require_execution(observation, expected):
    actual = observation.execution.state if observation.execution is not None else "missing"
    if actual != expected:
        raise ScenarioFailure("EVALUATION_SCENARIO_" + expected.upper() + "_STATE_" + actual.upper())
    if not observation.cleanup.exact_absence or observation.cleanup.pending_create:
        raise ScenarioFailure("EVALUATION_SCENARIO_" + expected.upper() + "_CLEANUP_INCOMPLETE")


def test_actual_timeout_and_output_overflow_are_not_zero_exit_success(actual_runtime):
    timeout = contained_program(actual_runtime, b"import time\nwhile True: time.sleep(1)\n")
    require_execution(timeout, "timeout")
    overflow = contained_program(actual_runtime, b"import os\nwhile True: os.write(1, b'x' * 65536)\n")
    require_execution(overflow, "output_limit")
    if len(overflow.execution.stdout) != actual_runtime.spec.limits.stdout_bytes:
        raise ScenarioFailure("EVALUATION_SCENARIO_OUTPUT_LIMIT_CAPTURE_BOUND")


def test_actual_root_watchdog_cannot_be_killed_by_subject(actual_runtime):
    result = contained_program(actual_runtime, b"import os, signal\ntry:\n os.kill(1, signal.SIGKILL)\nexcept PermissionError:\n print('denied')\nelse:\n print('unexpected')\n")
    assert result.execution.exit_code == 0 and result.execution.stdout == b"denied\n"
    assert result.cleanup.exact_absence


def test_actual_double_fork_and_inherited_output_are_whole_container_cleanup(actual_runtime):
    result = contained_program(actual_runtime, b"import os, time\nif os.fork() == 0:\n os.setsid()\n if os.fork() == 0:\n  while True: time.sleep(1)\n os._exit(0)\nos._exit(0)\n")
    assert result.cleanup.exact_absence
    assert result.cleanup.state == "removed"
    assert actual_runtime.inspect(result.container_id) is None


def test_actual_declared_file_effect_uses_trusted_observer(actual_runtime):
    result = contained_program(actual_runtime, b"from pathlib import Path\nPath('/scratch/effect').write_bytes(b'exact effect')\n", effects=(("effect", 1024),))
    assert result.execution.exit_code == 0
    assert result.effects == (("effect", b"exact effect"),)
    assert result.cleanup.exact_absence
    symlink = contained_program(actual_runtime, b"import os\nos.symlink('/etc/passwd', '/scratch/effect')\n", effects=(("effect", 1024),))
    assert symlink.effects == (("effect", None),)
    assert symlink.cleanup.exact_absence


@pytest.mark.parametrize("exit_code", [0, 2])
def test_actual_private_file_effect_and_expected_nonzero_exit(actual_runtime, exit_code):
    raw = b"import os\nos.umask(0o077)\nwith open('/scratch/report', 'wb') as stream:\n stream.write(b'error report')\nraise SystemExit(" + str(exit_code).encode() + b")\n"
    result = contained_program(actual_runtime, raw, effects=(("report", 32),))
    case = OracleCase("private-report", (actual_runtime.spec.python_executable,), b"", b"", b"", exit_code, (FileExpectation("report", 32, b"error report"),))
    assert result.execution.exit_code == exit_code
    assert result.effects == (("report", b"error report"),)
    assert result.cleanup.exact_absence and not result.cleanup.pending_create
    assert compare_case(case, result).passed
    assert not compare_case(replace(case, expected_exit=exit_code + 1), result).passed


def test_actual_lost_create_response_recovers_full_id_without_replay(actual_runtime, monkeypatch):
    instance = actual_runtime
    original_command = instance.command
    calls = []
    def lose_create(label, args, **kwargs):
        calls.append(label)
        result = original_command(label, args, **kwargs)
        if label == "create":
            assert result.completed
            return replace(result, state="timeout", exit_code=None, stdout=b"", stdout_complete=False, stderr_complete=False)
        return result
    monkeypatch.setattr(instance, "command", lose_create)
    result = contained_program(instance, b"raise RuntimeError('must not execute')\n")
    assert result.state == "create_unknown" and result.execution is None
    assert result.container_id and result.cleanup.exact_absence
    assert calls.count("create") == 1 and "start" not in calls and "tool" not in calls
    reopened = DockerRuntime(instance.spec, instance.owner, instance.intent_dir)
    try:
        recovered = reopened.reconcile_all(maximum_entries=100, maximum_intents=10)
        assert len(recovered) == 1 and recovered[0].container_id == result.container_id
        assert recovered[0].exact_absence and not recovered[0].pending_create
    finally:
        reopened.close()
    assert calls.count("create") == 1


@pytest.mark.parametrize("record_kind", ["owner", "created"])
def test_actual_recovery_after_created_publication_temporary_link(actual_runtime, monkeypatch, record_kind):
    instance = actual_runtime
    original_command = instance.command
    created_ids = []
    def lose_start(label, args, **kwargs):
        if label == "start":
            created_ids.append(args[-1])
            return CommandObservation("timeout", None, b"", b"", 1, False, False, True)
        return original_command(label, args, **kwargs)
    monkeypatch.setattr(instance, "command", lose_start)
    monkeypatch.setattr(instance, "cleanup", lambda intent, container_id, *, create_uncertain: CleanupObservation("ownership_or_cleanup_unknown", container_id, False, False, create_uncertain))
    result = contained_program(instance, b"raise RuntimeError('must not execute')\n")
    assert result.state == "start_unknown" and result.execution is None
    assert not result.cleanup.exact_absence and created_ids == [result.container_id]
    with os.scandir(instance.directory) as entries:
        names = [item.name for item in entries if item.name.endswith(".created.json")]
    assert len(names) == 1
    temporary = instance.intent_dir / ".memory-private-0123456789abcdef"
    name = instance.owner.identity + ".owner.json" if record_kind == "owner" else names[0]
    os.link(instance.intent_dir / name, temporary)
    reopened = DockerRuntime(instance.spec, instance.owner, instance.intent_dir)
    try:
        recovered = reopened.reconcile_all(maximum_entries=100, maximum_intents=10)
        assert len(recovered) == 1 and recovered[0].exact_absence
        assert recovered[0].state == "removed" and recovered[0].ownership_verified
        assert not recovered[0].pending_create and not temporary.exists()
    finally:
        reopened.close()


def test_actual_cancellation_preserves_failure_and_owned_cleanup(actual_runtime):
    cancelled = Event()
    cancelled.set()
    result = contained_program(actual_runtime, b"print('never accepted')\n", stop_event=cancelled)
    assert result.execution.state == "aborted"
    assert result.cleanup.exact_absence


def test_actual_watchdog_expires_without_host_subject_supervision(actual_runtime):
    instance = actual_runtime
    stem = secrets.token_hex(16)
    snapshot = instance.intent_dir / (stem + ".snapshot")
    bundle = program_bundle(b"print('unused')\n")
    instance.record(stem + ".snapshot-intent.json", {"path": str(snapshot), "digest": bundle.digest})
    materialize_snapshot(bundle, snapshot)
    watchdog = instance.intent_dir / (stem + ".watchdog.py")
    observer = instance.intent_dir / (stem + ".observer.py")
    for path, source in ((watchdog, WATCHDOG_SOURCE), (observer, OBSERVER_SOURCE)):
        instance.record(path.name + ".intent.json", {"sha256": digest_bytes(source)})
        private_write(path, source, directory=instance.directory)
        path.chmod(0o444)
    intent = instance.intent(case_id=stem, snapshot=bundle.digest, snapshot_path=snapshot, watchdog_path=watchdog, observer_path=observer)
    instance.record(intent.name + ".create-intent.json", asdict(intent))
    identity = None
    try:
        created = instance.command("create", list(intent.create_argv))
        assert created.completed
        identity = created.stdout.decode("ascii").strip()
        instance.validate_container(instance.inspect(identity), intent, identity)
        instance.record(intent.name + ".start-intent.json", {"container_id": identity})
        assert instance.command("start", ["container", "start", identity]).completed
        waited = instance.command("watchdog-wait", ["container", "wait", identity], seconds=instance.spec.limits.watchdog_seconds + instance.spec.limits.operation_seconds)
        assert waited.completed and waited.stdout.strip() == b"0"
        stopped = instance.inspect(identity)
        instance.validate_container(stopped, intent, identity)
        assert stopped["State"]["Running"] is False
    finally:
        cleanup = instance.cleanup(intent, identity, create_uncertain=identity is None)
    assert cleanup.exact_absence


def test_actual_private_nonzero_effect_controls_enable_verification(tmp_path, prepared_runtime):
    tmp_path.chmod(0o700)
    def program(report):
        return program_bundle(b"import os\nos.umask(0o077)\nwith open('/scratch/report', 'wb') as stream:\n stream.write(" + repr(report).encode() + b")\nraise SystemExit(2)\n")
    before, correct, wrong = (program(report) for report in (b"noop", b"error report", b"wrong report"))
    policy = EditPolicy(before.digest, (EditableSpan("solve.py", 0, len(before.entries[0].content)),), (), (), ())
    case = OracleCase("expected-error-report", (prepared_runtime.python_executable, "-I", "-S", "/artifact/solve.py"), b"", b"", b"", 2, (FileExpectation("report", 32, b"error report"),))
    task = OracleTask("engineering-private-error-report", "1", "engineering-only-not-human-gold", before.digest, policy, proof(before, correct), (case,))
    spec = VerifierSpec(prepared_runtime, digest_bytes(Path(__file__).read_bytes()), verifier_source_digest(), 3, 3, 128 * 1024 * 1024)
    executor = VerifierExecutor(spec, actual_owner(), tmp_path)
    controls = (
        ControlArtifact("correct", correct, proof(before, correct)),
        ControlArtifact("noop", before, proof(before, before)),
        ControlArtifact("plausible_wrong", wrong, proof(before, wrong)),
    )
    approval = IndependentControlApproval(task.digest, controls_digest(controls), "engineering-only-not-independent-approval")
    precheck = executor.precheck(before, task, controls, approval)
    assert precheck.eligible and [receipt.success for receipt in precheck.receipts] == [True, False, False]
    receipt = executor.verify(before, correct, task)
    assert receipt.success and receipt.cleanup_complete
    assert receipt.cases[0].exit_equal and receipt.cases[0].effects_equal
