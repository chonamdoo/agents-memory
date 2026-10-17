from __future__ import annotations

import os
import select
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import suppress

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
