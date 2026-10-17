from __future__ import annotations

import base64
import os
import re
import stat
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from threading import Event

from .evaluation_artifacts import (
    ArtifactBundle,
    EditPolicy,
    EditWitness,
    StructuralOutcome,
    canonical_bytes,
    digest_bytes,
    materialize_snapshot,
    open_private_directory,
    safe_path,
    verify_allowed_edits,
)
from .evaluation_runtime import (
    HEX64,
    OBSERVER_SOURCE,
    WATCHDOG_SOURCE,
    DockerRuntime,
    EvaluationOwner,
    Publication,
    RuntimeRefusal,
    RuntimeSpec,
    SubjectObservation,
    publish_or_reconcile,
)
from .private_io import private_write


@dataclass(frozen=True)
class FileExpectation:
    path: str
    maximum_bytes: int
    expected: bytes

    def __post_init__(self) -> None:
        safe_path(self.path, depth=32, path_bytes=4096, component_bytes=255)
        if type(self.expected) is not bytes or type(self.maximum_bytes) is not int or not 0 <= len(self.expected) <= self.maximum_bytes:
            raise RuntimeRefusal("FILE_EXPECTATION_BOUND")


@dataclass(frozen=True)
class OracleCase:
    case_id: str
    argv: tuple[str, ...]
    stdin: bytes
    expected_stdout: bytes
    expected_stderr: bytes
    expected_exit: int
    effects: tuple[FileExpectation, ...]

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,128}", self.case_id) or type(self.argv) is not tuple or not self.argv or any(not isinstance(arg, str) or "\x00" in arg for arg in self.argv):
            raise RuntimeRefusal("ORACLE_INVOCATION")
        if any(type(value) is not bytes for value in (self.stdin, self.expected_stdout, self.expected_stderr)) or type(self.expected_exit) is not int or type(self.effects) is not tuple:
            raise RuntimeRefusal("ORACLE_TYPE")
        if len({effect.path for effect in self.effects}) != len(self.effects):
            raise RuntimeRefusal("DUPLICATE_EFFECT")

    def identity(self) -> dict:
        return {"case_id": self.case_id, "argv": self.argv, "stdin": digest_bytes(self.stdin), "stdout": digest_bytes(self.expected_stdout), "stderr": digest_bytes(self.expected_stderr), "exit": self.expected_exit, "effects": [{"path": effect.path, "maximum": effect.maximum_bytes, "expected": digest_bytes(effect.expected)} for effect in self.effects]}


@dataclass(frozen=True)
class OracleTask:
    task_id: str
    revision: str
    independently_reviewed_reference: str
    baseline_digest: str
    policy: EditPolicy
    witness: EditWitness
    cases: tuple[OracleCase, ...]

    def __post_init__(self) -> None:
        if not self.task_id or not self.revision or not self.independently_reviewed_reference or type(self.cases) is not tuple or not self.cases or len({case.case_id for case in self.cases}) != len(self.cases):
            raise RuntimeRefusal("TASK_IDENTITY")
        if self.baseline_digest != self.policy.baseline_digest:
            raise RuntimeRefusal("TASK_BASELINE")

    @property
    def digest(self) -> str:
        return digest_bytes(canonical_bytes({"task_id": self.task_id, "revision": self.revision, "review": self.independently_reviewed_reference, "baseline": self.baseline_digest, "policy": self.policy.digest, "cases": [case.identity() for case in self.cases]}))


@dataclass(frozen=True)
class VerifierSpec:
    runtime: RuntimeSpec
    controller_digest: str
    verifier_source_digest: str
    max_cases: int
    max_effects: int
    private_receipt_bytes: int

    def __post_init__(self) -> None:
        if any(not HEX64.fullmatch(value) for value in (self.controller_digest, self.verifier_source_digest)) or any(type(value) is not int or value < 1 for value in (self.max_cases, self.max_effects, self.private_receipt_bytes)):
            raise RuntimeRefusal("VERIFIER_SPEC")

    @property
    def digest(self) -> str:
        return digest_bytes(canonical_bytes({"runtime": self.runtime.digest, "controller": self.controller_digest, "verifier_source": self.verifier_source_digest, "max_cases": self.max_cases, "max_effects": self.max_effects, "private_receipt_bytes": self.private_receipt_bytes}))


def verifier_source_digest() -> str:
    entries = []
    for name in ("evaluation_artifacts.py", "evaluation_runtime.py", "evaluation_verifier.py"):
        path = Path(__file__).with_name(name)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_size > 4 * 1024 * 1024:
                raise RuntimeRefusal("TRUSTED_SOURCE_BOUND")
            with os.fdopen(fd, "rb", closefd=False) as stream:
                raw = stream.read(4 * 1024 * 1024 + 1)
            after = os.fstat(fd)
            if len(raw) != before.st_size or (before.st_ino, before.st_mtime_ns, before.st_ctime_ns) != (after.st_ino, after.st_mtime_ns, after.st_ctime_ns):
                raise RuntimeRefusal("TRUSTED_SOURCE_UNSTABLE")
            entries.append([name, digest_bytes(raw)])
        finally:
            os.close(fd)
    return digest_bytes(canonical_bytes(entries))


@dataclass(frozen=True)
class CaseOutcome:
    case_id: str
    state: str
    passed: bool
    stdout_equal: bool | None
    stderr_equal: bool | None
    exit_equal: bool | None
    effects_equal: bool | None
    observation: SubjectObservation | None

    def public(self) -> dict:
        value = {key: item for key, item in vars(self).items() if key != "observation"}
        observation = self.observation
        if observation is not None:
            value["execution"] = observation.execution.public() if observation.execution else None
            value["cleanup"] = asdict(observation.cleanup)
            value["resource_digest"] = observation.resource_digest
            value["operations"] = [{"stage": stage, **command.public()} for stage, command in observation.operations]
        return value


def compare_case(case: OracleCase, observation: SubjectObservation) -> CaseOutcome:
    execution = observation.execution
    if execution is None:
        return CaseOutcome(case.case_id, observation.state, False, None, None, None, None, observation)
    stdout_equal = execution.stdout == case.expected_stdout
    stderr_equal = execution.stderr == case.expected_stderr
    exit_equal = execution.exit_code == case.expected_exit
    effects_equal = dict(observation.effects) == {effect.path: effect.expected for effect in case.effects}
    complete = observation.state == "completed" and execution.state == "completed" and execution.stdout_complete and execution.stderr_complete and execution.helper_cleanup
    cleanup = observation.cleanup.exact_absence and not observation.cleanup.pending_create and observation.cleanup.state in {"removed", "absent"}
    passed = complete and cleanup and stdout_equal and stderr_equal and exit_equal and effects_equal
    return CaseOutcome(case.case_id, "passed" if passed else "rejected", passed, stdout_equal, stderr_equal, exit_equal, effects_equal, observation)


@dataclass(frozen=True)
class VerifierReceipt:
    schema: int
    state: str
    success: bool
    role: str
    owner: str
    verifier_digest: str
    task_digest: str
    baseline_digest: str
    submission_digest: str
    structural: StructuralOutcome | None
    cases: tuple[CaseOutcome, ...]
    cleanup_complete: bool
    controls_digest: str | None
    private_artifact: str | None
    private_sha256: str | None
    terminal_artifact: str | None
    publication: Publication
    error_code: str | None

    def public(self) -> dict:
        value = {key: item for key, item in vars(self).items() if key not in {"structural", "cases", "publication"}}
        value["structural"] = asdict(self.structural) if self.structural else None
        value["cases"] = [case.public() for case in self.cases]
        return value


@dataclass(frozen=True)
class ControlArtifact:
    role: str
    bundle: ArtifactBundle
    witness: EditWitness


@dataclass(frozen=True)
class IndependentControlApproval:
    task_digest: str
    controls_digest: str
    approval_reference: str


@dataclass(frozen=True)
class ControlReceipt:
    task_digest: str
    verifier_digest: str
    controls_digest: str
    approval_reference: str
    receipts: tuple[VerifierReceipt, ...]
    eligible: bool


def controls_digest(controls: tuple[ControlArtifact, ...]) -> str:
    return digest_bytes(canonical_bytes([{ "role": item.role, "bundle": item.bundle.digest, "witness": witness_digest(item.witness)} for item in controls]))


def witness_digest(witness: EditWitness) -> str:
    return digest_bytes(canonical_bytes({"baseline": witness.baseline_digest, "final": witness.final_digest, "edits": [{"path": edit.path, "start": edit.start, "end": edit.end, "replacement": digest_bytes(edit.replacement)} for edit in witness.edits], "creates": [entry.manifest() for entry in witness.creates], "deletes": witness.deletes, "modes": [asdict(mode) for mode in witness.modes]}))


def _private_observations(cases: tuple[CaseOutcome, ...]) -> bytes:
    def encode(value: object) -> object:
        if isinstance(value, bytes):
            return {"base64": base64.b64encode(value).decode("ascii")}
        if isinstance(value, dict):
            return {key: encode(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [encode(item) for item in value]
        return value

    return canonical_bytes(encode([asdict(case) for case in cases]))


class VerifierExecutor:
    def __init__(self, spec: VerifierSpec, owner: EvaluationOwner, intent_dir: Path):
        self.spec, self.owner, self.intent_dir = spec, owner, intent_dir
        fd = open_private_directory(intent_dir)
        os.close(fd)
        self._controls: ControlReceipt | None = None

    def precheck(self, baseline: ArtifactBundle, task: OracleTask, controls: tuple[ControlArtifact, ...], approval: IndependentControlApproval) -> ControlReceipt:
        if type(controls) is not tuple or tuple(item.role for item in controls) != ("correct", "noop", "plausible_wrong"):
            raise RuntimeRefusal("THREE_ORDERED_CONTROLS_REQUIRED")
        identity = controls_digest(controls)
        if approval.task_digest != task.digest or approval.controls_digest != identity or not approval.approval_reference:
            raise RuntimeRefusal("INDEPENDENT_CONTROL_APPROVAL_REQUIRED")
        if controls[1].bundle.digest != baseline.digest or len({item.bundle.digest for item in controls}) != 3:
            raise RuntimeRefusal("CONTROL_IDENTITIES")
        self._controls = None
        receipts = tuple(self._verify(baseline, item.bundle, replace(task, witness=item.witness), role="control_" + item.role, require_controls=False, stop_event=None) for item in controls)
        correct, noop, wrong = receipts
        eligible = correct.success and correct.cleanup_complete and all(case.passed for case in correct.cases)
        for rejected in (noop, wrong):
            observed = all(case.observation is not None and case.observation.execution is not None and case.observation.state == "completed" and case.observation.execution.state == "completed" and case.observation.execution.stdout_complete and case.observation.execution.stderr_complete and case.observation.execution.helper_cleanup for case in rejected.cases)
            eligible = eligible and not rejected.success and rejected.cleanup_complete and rejected.structural is not None and rejected.structural.passed and observed and rejected.error_code is None
        eligible = eligible and all(receipt.publication.state in {"durable", "reconciled_durable"} for receipt in receipts)
        result = ControlReceipt(task.digest, self.spec.digest, identity, approval.approval_reference, receipts, bool(eligible))
        runtime = DockerRuntime(self.spec.runtime, self.owner, self.intent_dir)
        try:
            runtime.record("controls-" + digest_bytes(canonical_bytes([task.digest, self.spec.digest, identity])) + ".json", {"task": task.digest, "verifier": self.spec.digest, "controls": identity, "approval_reference": approval.approval_reference, "eligible": result.eligible, "receipts": [receipt.public() for receipt in receipts]})
        finally:
            runtime.close()
        self._controls = result
        return result

    def verify(self, baseline: ArtifactBundle, submission: ArtifactBundle, task: OracleTask, *, stop_event: Event | None = None) -> VerifierReceipt:
        return self._verify(baseline, submission, task, role="evaluation", require_controls=True, stop_event=stop_event)

    def _verify(self, baseline: ArtifactBundle, submission: ArtifactBundle, task: OracleTask, *, role: str, require_controls: bool, stop_event: Event | None) -> VerifierReceipt:
        key = digest_bytes(canonical_bytes([self.owner.identity, self.spec.digest, task.digest, submission.digest, witness_digest(task.witness), role]))
        runtime = DockerRuntime(self.spec.runtime, self.owner, self.intent_dir)
        structural = None
        cases = tuple(CaseOutcome(case.case_id, "not_started", False, None, None, None, None, None) for case in task.cases)
        error_code = None
        control_identity = self._controls.controls_digest if self._controls is not None else None
        private_name, private_digest = None, None
        terminal_name = key + ".terminal.json"
        try:
            claim = {"owner": self.owner.identity, "verifier": self.spec.digest, "task": task.digest, "baseline": baseline.digest, "submission": submission.digest, "witness": witness_digest(task.witness), "role": role}
            try:
                private_write(Path(key + ".attempt-intent.json"), canonical_bytes(claim), directory=runtime.directory)
            except Exception:
                return VerifierReceipt(1, "unknown", False, role, self.owner.identity, self.spec.digest, task.digest, baseline.digest, submission.digest, None, cases, False, control_identity, None, None, None, Publication("claim_unknown_or_existing", digest_bytes(canonical_bytes(claim))), "ATTEMPT_CLAIM_UNKNOWN_OR_EXISTING")
            if require_controls and (self._controls is None or not self._controls.eligible or self._controls.task_digest != task.digest or self._controls.verifier_digest != self.spec.digest):
                raise RuntimeRefusal("CONTROL_PRECHECK_REQUIRED")
            if baseline.digest != task.baseline_digest or len(task.cases) > self.spec.max_cases or sum(len(case.effects) for case in task.cases) > self.spec.max_effects:
                raise RuntimeRefusal("TASK_IDENTITY_OR_BOUND")
            limit = self.spec.runtime.limits
            if any(len(case.stdin) > limit.stdin_bytes or len(case.expected_stdout) > limit.stdout_bytes or len(case.expected_stderr) > limit.stderr_bytes or any(effect.maximum_bytes > limit.file_bytes for effect in case.effects) for case in task.cases):
                raise RuntimeRefusal("ORACLE_RESOURCE_BOUND")
            if verifier_source_digest() != self.spec.verifier_source_digest:
                raise RuntimeRefusal("VERIFIER_SOURCE_CHANGED")
            structural = verify_allowed_edits(baseline, submission, task.policy, task.witness)
            if structural.passed:
                try:
                    runtime.preflight()
                finally:
                    runtime.record(key + ".runtime-preflight.json", {"operations": [{"stage": stage, **command.public()} for stage, command in runtime.operations]})
                snapshot = self.intent_dir / (key + ".snapshot")
                runtime.record(key + ".snapshot-intent.json", {"path": str(snapshot), "digest": submission.digest})
                materialize_snapshot(submission, snapshot)
                watchdog = self.intent_dir / (key + ".watchdog.py")
                observer = self.intent_dir / (key + ".observer.py")
                for path, source in ((watchdog, WATCHDOG_SOURCE), (observer, OBSERVER_SOURCE)):
                    runtime.record(path.name + ".intent.json", {"sha256": digest_bytes(source), "mode": 0o444})
                    private_write(path, source, directory=runtime.directory)
                    fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=runtime.directory)
                    try:
                        os.fchmod(fd, 0o444)
                        os.fsync(fd)
                    finally:
                        os.close(fd)
                outcomes = []
                for index, case in enumerate(task.cases):
                    if stop_event is not None and stop_event.is_set():
                        outcomes.extend(cases[index:])
                        break
                    intent = runtime.intent(case_id=key + "-" + case.case_id, snapshot=submission.digest, snapshot_path=snapshot, watchdog_path=watchdog, observer_path=observer)
                    observation = runtime.run(intent, case.argv, case.stdin, tuple((effect.path, effect.maximum_bytes) for effect in case.effects), stop_event=stop_event)
                    outcome = compare_case(case, observation)
                    outcomes.append(outcome)
                    cases = tuple(outcomes) + cases[len(outcomes):]
                    case_raw = _private_observations((outcome,))
                    if len(case_raw) > self.spec.private_receipt_bytes:
                        raise RuntimeRefusal("PRIVATE_OBSERVATION_BOUND")
                    case_name = key + f".case-{index}.observations.json"
                    case_publication = publish_or_reconcile(runtime.directory, case_name, case_raw)
                    if case_publication.state not in {"durable", "reconciled_durable"}:
                        raise RuntimeRefusal("CASE_PUBLICATION_" + case_publication.state.upper())
                    runtime.record(key + f".case-{index}.json", {"case": outcome.public(), "observations": digest_bytes(case_raw), "private_artifact": case_name})
                    if not observation.cleanup.exact_absence or observation.cleanup.pending_create:
                        break
                cases = tuple(outcomes) + cases[len(outcomes):]
        except (ValueError, OSError, KeyError, TypeError) as error:
            error_code = str(error) if isinstance(error, RuntimeRefusal) else "VERIFIER_BOUNDARY_" + type(error).__name__.upper()
        finally:
            try:
                raw = _private_observations(cases)
                if len(raw) > self.spec.private_receipt_bytes:
                    error_code = "PRIVATE_OBSERVATION_BOUND"
                else:
                    private_name = key + ".observations.json"
                    private_digest = digest_bytes(raw)
                    result = publish_or_reconcile(runtime.directory, private_name, raw)
                    if result.state not in {"durable", "reconciled_durable"}:
                        error_code = "PRIVATE_PUBLICATION_" + result.state.upper()
            finally:
                runtime.close()
        cleanup_complete = all(case.observation is None or (case.observation.cleanup.exact_absence and not case.observation.cleanup.pending_create and case.observation.cleanup.state in {"removed", "absent"}) for case in cases)
        if not cleanup_complete:
            error_code = error_code or "OWNED_CLEANUP_INCOMPLETE"
        success = error_code is None and structural is not None and structural.passed and len(cases) == len(task.cases) and all(case.passed for case in cases) and cleanup_complete
        receipt = VerifierReceipt(1, "passed" if success else "rejected" if error_code is None else "incomplete", success, role, self.owner.identity, self.spec.digest, task.digest, baseline.digest, submission.digest, structural, cases, cleanup_complete, control_identity, private_name, private_digest, terminal_name, Publication("pending", ""), error_code)
        directory = open_private_directory(self.intent_dir)
        try:
            publication = publish_or_reconcile(directory, terminal_name, canonical_bytes(receipt.public()))
        finally:
            os.close(directory)
        if publication.state not in {"durable", "reconciled_durable"}:
            return replace(receipt, state="publication_unknown", success=False, publication=publication)
        return replace(receipt, publication=publication)
