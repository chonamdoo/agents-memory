from __future__ import annotations

import os
import select
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import ExitStack, suppress
from pathlib import Path
from types import SimpleNamespace

import pytest


def _finish_owned_process(
    process: subprocess.Popen[bytes], real_wait: Callable[..., int],
) -> None:
    try:
        if process.returncode is None:
            process.kill()
    finally:
        try:
            real_wait(timeout=2)
        finally:
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    with suppress(BrokenPipeError):
                        stream.close()


@pytest.fixture
def group_reuse_witness(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[int, subprocess.Popen[bytes]]]:
    survivor = subprocess.Popen(
        [sys.executable, "-c", "import sys\nprint('ready', flush=True)\n"
         "for line in sys.stdin:\n print('alive', flush=True)\n"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    tracked: dict[int, subprocess.Popen[bytes]] = {}
    real_killpg = os.killpg

    def signal_group(pgid: int, sig: int) -> None:
        process = tracked.get(pgid)
        if process is not None and process.returncode is not None:
            return real_killpg(survivor.pid, sig)
        return real_killpg(pgid, sig)

    monkeypatch.setattr(os, "killpg", signal_group)
    try:
        assert survivor.stdin is not None and survivor.stdout is not None
        assert select.select([survivor.stdout], [], [], 2)[0] == [survivor.stdout]
        assert os.read(survivor.stdout.fileno(), 64) == b"ready\n"
        yield tracked
        survivor.stdin.write(b"ping\n")
        survivor.stdin.flush()
        assert select.select([survivor.stdout], [], [], 2)[0] == [survivor.stdout]
        assert os.read(survivor.stdout.fileno(), 64) == b"alive\n"
    finally:
        _finish_owned_process(survivor, survivor.wait)


@pytest.fixture
def owned_descendants(
    tmp_path: Path, group_reuse_witness: dict[int, subprocess.Popen[bytes]],
) -> Iterator[SimpleNamespace]:
    with ExitStack() as cleanup:
        lifetime = tmp_path / "descendant-lifetime"
        os.mkfifo(lifetime, 0o600)
        observer = os.open(lifetime, os.O_RDONLY | os.O_NONBLOCK)
        cleanup.callback(os.close, observer)
        control = tmp_path / "descendant-control"
        os.mkfifo(control, 0o600)
        anchor = os.open(control, os.O_RDONLY | os.O_NONBLOCK)
        cleanup.callback(os.close, anchor)
        release = os.open(control, os.O_WRONLY | os.O_NONBLOCK)
        cleanup.callback(os.close, release)
        processes = []

        def observe_descendant_exit() -> None:
            deadline = time.monotonic() + 2
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not select.select([observer], [], [], remaining)[0]:
                    break
                if os.read(observer, 4096) == b"":
                    return
            pytest.fail("Controlled descendant did not close its lifetime descriptor")

        cleanup.callback(observe_descendant_exit)

        def track(process: subprocess.Popen[bytes]) -> None:
            group_reuse_witness[process.pid] = process
            real_wait = process.wait
            processes.append((process, real_wait))
            cleanup.callback(_finish_owned_process, process, real_wait)

        try:
            yield SimpleNamespace(
                lifetime=lifetime, control=control, observer=observer,
                processes=processes, track=track,
            )
        finally:
            os.write(release, b"X")
