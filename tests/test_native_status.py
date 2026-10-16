from __future__ import annotations

import json
import os
import select
import signal
import subprocess
import sys
import textwrap
import time
from contextlib import suppress

import pytest

from agents_memory import native_status
from agents_memory.domain import DomainError


def response(project, *, disabled="Synthetic project is not trusted"):
    return ({"layers": [{
        "name": {"type": "project", "dotCodexFolder": str(project / ".codex")},
        "disabledReason": disabled,
        "config": {"privateValue": "never-display-config"},
    }]}, {"data": [{"cwd": str(project), "hooks": [{
        "source": "user", "enabled": True, "trustStatus": "trusted",
        "command": "never-display-foreign-command",
    }], "warnings": ["never-display-warning"], "errors": ["never-display-error"]}]})


def test_disabled_project_with_trusted_user_hook_is_not_project_activation(tmp_path):
    config, hooks = response(tmp_path)
    result = native_status._summarize(tmp_path, config, hooks)
    assert result["project_layers"] == [{
        "config_folder": str(tmp_path / ".codex"), "trust_target": str(tmp_path), "state": "disabled",
    }]
    assert result["hook_counts"]["project"] == 0
    assert result["hook_counts"]["user"] == 1
    assert result["inventory_error_count"] == 1
    assert "never-display" not in json.dumps(result)


@pytest.mark.parametrize("change", ["wrong_scope", "missing_scope", "foreign_layer", "wrong_hooks", "wrong_errors"])
def test_native_inventory_refuses_scope_and_schema_ambiguity(tmp_path, change):
    config, hooks = response(tmp_path)
    if change == "wrong_scope":
        hooks["data"][0]["cwd"] = str(tmp_path / "other")
    elif change == "missing_scope":
        hooks["data"] = []
    elif change == "foreign_layer":
        config["layers"][0]["name"]["dotCodexFolder"] = str(tmp_path / "other" / ".codex")
    elif change == "wrong_hooks":
        hooks["data"][0]["hooks"] = None
    else:
        hooks["data"][0]["errors"] = "never-display-provider-error"
    with pytest.raises(DomainError) as caught:
        native_status._summarize(tmp_path, config, hooks)
    assert caught.value.code == "HOST_NATIVE_STATUS_UNAVAILABLE"
    assert "never-display" not in json.dumps(caught.value.public())


def test_missing_layer_disabled_state_remains_unknown(tmp_path):
    config, hooks = response(tmp_path)
    del config["layers"][0]["disabledReason"]
    result = native_status._summarize(tmp_path, config, hooks)
    assert result["project_layers"][0]["state"] == "unknown"


@pytest.mark.skipif(os.name != "posix", reason="Native inventory process supervision requires POSIX")
@pytest.mark.parametrize("behavior", ["timeout", "oversize", "malformed"])
def test_unavailable_native_process_is_bounded_and_no_raw_output_escapes(tmp_path, monkeypatch, behavior):
    executable = tmp_path / "native-probe"
    executable.write_text(
        "#!" + sys.executable + "\nimport os,sys,time\n"
        "sys.stdin.readline()\n"
        + {
            "timeout": "time.sleep(30)\n",
            "oversize": "os.write(2,b'never-display-provider-error'*1000)\ntime.sleep(30)\n",
            "malformed": "print('never-display-provider-error',flush=True)\ntime.sleep(30)\n",
        }[behavior],
    )
    executable.chmod(0o700)
    monkeypatch.setattr(native_status, "_DEADLINE_SECONDS", 0.15)
    monkeypatch.setattr(native_status, "_RESPONSE_BYTES", 512)
    started = time.monotonic()
    with pytest.raises(DomainError) as caught:
        native_status._codex_inventory(tmp_path, executable)
    assert caught.value.code == "HOST_NATIVE_STATUS_UNAVAILABLE"
    assert "never-display" not in json.dumps(caught.value.public())
    assert time.monotonic() - started < 5


@pytest.mark.skipif(os.name != "posix", reason="Native inventory process supervision requires POSIX")
@pytest.mark.parametrize("parent_mode", ["parent_first", "parent_on_term", "parent_ignores_term"])
@pytest.mark.parametrize("failure", ["malformed", "timeout"])
@pytest.mark.parametrize("wait_failure", [None, "timeout", "oserror"])
def test_native_inventory_ends_descendants_and_closes_pipes_on_failure(
    tmp_path, monkeypatch, parent_mode, failure, wait_failure,
):
    monkeypatch.setenv("HOME", str(tmp_path))
    lifetime = tmp_path / "descendant-lifetime"
    os.mkfifo(lifetime, 0o600)
    observer = os.open(lifetime, os.O_RDONLY | os.O_NONBLOCK)
    executable = tmp_path / "native-probe"
    executable.write_text("#!" + sys.executable + "\n" + textwrap.dedent(f"""
        import os
        import signal
        import sys

        parent_mode = {parent_mode!r}
        if parent_mode == "parent_ignores_term":
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
        ready_read, ready_write = os.pipe()
        parent_read, parent_write = os.pipe()
        if os.fork() == 0:
            os.close(ready_read)
            os.close(parent_write)
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            lifetime = os.open({str(lifetime)!r}, os.O_WRONLY)
            os.write(lifetime, b"R")
            os.write(ready_write, b"R")
            os.close(ready_write)
            if parent_mode == "parent_first":
                os.read(parent_read, 1)
                if {failure!r} == "malformed":
                    print("never-display-provider-error", flush=True)
            os.close(parent_read)
            while True:
                signal.pause()
        os.close(ready_write)
        os.close(parent_read)
        os.read(ready_read, 1)
        os.close(ready_read)
        sys.stdin.readline()
        if parent_mode == "parent_first":
            os._exit(0)
        if {failure!r} == "malformed":
            print("never-display-provider-error", flush=True)
        while True:
            signal.pause()
    """))
    executable.chmod(0o700)
    monkeypatch.setattr(native_status, "_DEADLINE_SECONDS", 1)
    monkeypatch.setattr(native_status, "_CLEANUP_SECONDS", 0.15)
    real_popen = subprocess.Popen
    processes = []

    def start(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        processes.append((process, process.wait))
        if wait_failure is not None:
            def fail_wait(timeout):
                if wait_failure == "timeout":
                    raise subprocess.TimeoutExpired(process.args, timeout)
                raise OSError("never-display-wait-failure")

            monkeypatch.setattr(process, "wait", fail_wait)
        return process

    monkeypatch.setattr(native_status.subprocess, "Popen", start)
    try:
        started = time.monotonic()
        with pytest.raises(DomainError) as caught:
            native_status._codex_inventory(tmp_path, executable)
        assert time.monotonic() - started < 4
        assert caught.value.code == "HOST_NATIVE_STATUS_UNAVAILABLE"
        assert caught.value.public()["effect"] == "not_started"
        assert "never-display" not in json.dumps(caught.value.public())
        assert os.read(observer, 1) == b"R"
        assert select.select([observer], [], [], 1)[0] == [observer]
        assert os.read(observer, 1) == b""
        process, real_wait = processes[0]
        assert all(stream.closed for stream in (process.stdin, process.stdout, process.stderr))
        expected = {"parent_first": 0, "parent_on_term": -signal.SIGTERM, "parent_ignores_term": -signal.SIGKILL}
        assert real_wait(timeout=1) == expected[parent_mode]
    finally:
        for process, real_wait in processes:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            real_wait(timeout=2)
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()
        os.close(observer)
