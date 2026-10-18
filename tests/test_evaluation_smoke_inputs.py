from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest


@pytest.fixture
def smoke():
    path = Path(__file__).resolve().parents[1] / ".github" / "ci" / "evaluation-smoke.py"
    spec = importlib.util.spec_from_file_location("evaluation_full_smoke_inputs", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_declared_engineering_approval_matches_only_exact_fixed_task_bytes(smoke, monkeypatch):
    documents, declaration = smoke.task_inputs()
    expected = smoke.predeclared_approval()
    assert (declaration["approved_task_digest"], declaration["approved_controls_digest"]) == expected
    assert documents["baseline"] != documents["correct"] != documents["wrong"]
    monkeypatch.setattr(smoke, "CORRECT_CODE", b"print('changed-but-not-approved')\n")
    assert smoke.predeclared_approval() == expected
    with pytest.raises(ValueError, match="PREDECLARED_ENGINEERING_APPROVAL_DRIFT"):
        smoke.task_inputs()


def test_declared_engineering_approval_does_not_rebind_a_changed_oracle_reference(smoke, monkeypatch):
    expected = smoke.predeclared_approval()
    monkeypatch.setattr(smoke, "REVIEW_REFERENCE", "changed-arbitrary-reference")
    assert smoke.predeclared_approval() == expected
    with pytest.raises(ValueError, match="PREDECLARED_ENGINEERING_APPROVAL_DRIFT"):
        smoke.task_inputs()


def test_non_actions_refusal_cannot_write_state_or_publish_input_strings(smoke, monkeypatch, tmp_path, capsys):
    marker = "private-unvalidated-sha-or-body"
    monkeypatch.setenv("GITHUB_ACTIONS", "false")
    monkeypatch.setenv("GITHUB_SHA", marker)
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["evaluation-smoke.py", "--wheel", str(tmp_path / "missing.whl"),
        "--expected-wheel-sha256", "a" * 64, "--consumption", "source"])
    assert smoke.main() == 1
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["complete"] is False
    assert report["tested_sha"] is None
    assert report["original18_completed"] == 0
    assert marker not in captured.out + captured.err
    assert list(tmp_path.iterdir()) == []


def test_private_runtime_output_refuses_overflow_before_writing_excess(smoke):
    stream = io.BytesIO()
    output = smoke.PrivateLog(stream)
    output.count = 8 * 1024 * 1024 - 1
    with pytest.raises(ValueError, match="PRIVATE_LOG_BOUND"):
        output.write("ab")
    assert stream.getvalue() == b""
    assert output.write("a") == 1
    assert stream.getvalue() == b"a"


def test_failure_evidence_publication_failure_does_not_interrupt_owned_cleanup(smoke, monkeypatch, tmp_path):
    def failed_publication(*args):
        raise OSError("private input-bearing failure")
    monkeypatch.setattr(smoke, "save", failed_publication)
    cleanup = {}
    try:
        raise RuntimeError("original private failure")
    except RuntimeError:
        smoke.retain_failure(tmp_path, "failure.private.txt", cleanup)
    assert cleanup == {"failure_evidence_publication_complete": False}
