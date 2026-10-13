from __future__ import annotations

import errno
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from agents_memory import private_io
from agents_memory.domain import DomainError


def test_partial_write_failure_never_publishes_final_file(tmp_path, monkeypatch):
    target = tmp_path / "receipt"
    write = os.write
    calls = 0

    def fail_after_prefix(fd, raw):
        nonlocal calls
        calls += 1
        if calls == 1:
            return write(fd, raw[:3])
        raise OSError(errno.EIO, "injected partial write")

    monkeypatch.setattr(private_io.os, "write", fail_after_prefix)
    with pytest.raises(OSError):
        private_io.private_write(target, b"complete-private-receipt")
    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


def test_short_writes_are_completed_before_publication(tmp_path, monkeypatch):
    target = tmp_path / "receipt"
    write = os.write
    link = os.link
    raw = b"bounded-private-receipt"

    monkeypatch.setattr(private_io.os, "write", lambda fd, value: write(fd, value[:2]))

    def publish(source, destination, **kwargs):
        assert not target.exists()
        assert Path(source).read_bytes() == raw
        return link(source, destination, **kwargs)

    monkeypatch.setattr(private_io.os, "link", publish)
    private_io.private_write(target, raw)
    assert target.read_bytes() == raw
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert list(tmp_path.iterdir()) == [target]


def test_concurrent_publication_cannot_clobber_a_winner(tmp_path, monkeypatch):
    target = tmp_path / "receipt"
    link = os.link

    def publish_after_winner(source, destination, **kwargs):
        target.write_bytes(b"other-publisher-complete")
        return link(source, destination, **kwargs)

    monkeypatch.setattr(private_io.os, "link", publish_after_winner)
    with pytest.raises(FileExistsError):
        private_io.private_write(target, b"loser-content")
    assert target.read_bytes() == b"other-publisher-complete"
    assert list(tmp_path.iterdir()) == [target]


def test_failed_replace_preserves_original_and_symlink_is_refused(tmp_path, monkeypatch):
    target = tmp_path / "owned"
    private_io.private_write(target, b"original")
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(DomainError):
        private_io.private_write(link, b"replacement", replace=True)

    def fail_sync(fd):
        raise OSError(errno.EIO, "injected fsync failure")

    monkeypatch.setattr(private_io, "sync_file", fail_sync)
    with pytest.raises(OSError):
        private_io.private_write(target, b"replacement", replace=True)
    assert target.read_bytes() == b"original"
    assert {item.name for item in tmp_path.iterdir()} == {"owned", "link"}


def test_cleanup_does_not_unlink_a_replaced_temporary_entry(tmp_path, monkeypatch):
    target = tmp_path / "receipt"
    displaced = tmp_path / "owned-temp-displaced"

    def replace_temp_then_fail(source, destination, **kwargs):
        os.rename(source, displaced)
        Path(source).write_bytes(b"not-owned-by-this-write")
        raise OSError(errno.EIO, "injected publication failure")

    monkeypatch.setattr(private_io.os, "link", replace_temp_then_fail)
    with pytest.raises(OSError):
        private_io.private_write(target, b"private-content")
    assert not target.exists()
    assert displaced.read_bytes() == b"private-content"
    assert next(tmp_path.glob(".memory-private-*")).read_bytes() == b"not-owned-by-this-write"


@pytest.mark.parametrize("point", ["partial_write", "published"])
def test_process_crash_exposes_only_absent_or_complete_final_file(tmp_path, point):
    target = tmp_path / "receipt"
    script = r'''
import os
import sys
from pathlib import Path
from agents_memory import private_io

target = Path(sys.argv[1])
point = sys.argv[2]
if point == "partial_write":
    write = os.write
    def crash_write(fd, raw):
        write(fd, raw[:3])
        os._exit(77)
    private_io.os.write = crash_write
else:
    link = os.link
    def crash_publish(source, destination, **kwargs):
        link(source, destination, **kwargs)
        os._exit(77)
    private_io.os.link = crash_publish
private_io.private_write(target, b"complete-private-receipt")
'''
    result = subprocess.run(
        [sys.executable, "-c", script, str(target), point], check=False, capture_output=True
    )
    assert result.returncode == 77, result.stderr.decode()
    leftovers = tuple(tmp_path.glob(".memory-private-*"))
    assert len(leftovers) == 1
    assert stat.S_IMODE(leftovers[0].stat().st_mode) == 0o600
    if point == "partial_write":
        assert not target.exists()
        private_io.private_write(target, b"complete-private-receipt")
    else:
        assert target.read_bytes() == b"complete-private-receipt"
        with pytest.raises(FileExistsError):
            private_io.private_write(target, b"cannot-overwrite")
    assert target.read_bytes() == b"complete-private-receipt"
    assert leftovers[0].exists()


def test_directory_publication_follows_the_descriptor_not_the_path(tmp_path):
    parent, moved = tmp_path / "parent", tmp_path / "moved"
    parent.mkdir()
    directory = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)

    def refuse():
        raise DomainError("REFUSED", "publication refused")

    try:
        parent.rename(moved)
        private_io.private_write(parent / "receipt", b"pinned", directory=directory)
        with pytest.raises(FileExistsError):
            private_io.private_write(parent / "receipt", b"loser", directory=directory)
        with pytest.raises(DomainError):
            private_io.private_write(parent / "receipt", b"refused", replace=True, before_publish=refuse, directory=directory)
    finally:
        os.close(directory)
    assert not parent.exists()
    assert (moved / "receipt").read_bytes() == b"pinned"
    assert list(moved.iterdir()) == [moved / "receipt"]


def test_fullfsync_follows_fsync_and_preserves_real_io_errors(monkeypatch):
    calls = []
    monkeypatch.setattr(private_io.sys, "platform", "darwin")
    monkeypatch.setattr(private_io.fcntl, "F_FULLFSYNC", 51, raising=False)
    monkeypatch.setattr(private_io.os, "fsync", lambda fd: calls.append(("fsync", fd)))
    monkeypatch.setattr(private_io.fcntl, "fcntl", lambda fd, command: calls.append(("fullfsync", fd, command)))
    private_io.sync_file(12)
    assert calls == [("fsync", 12), ("fullfsync", 12, 51)]

    def unsupported(fd, command):
        raise OSError(errno.ENOTSUP, "unsupported")

    monkeypatch.setattr(private_io.fcntl, "fcntl", unsupported)
    private_io.sync_file(12)

    def failed(fd, command):
        raise OSError(errno.EIO, "disk failure")

    monkeypatch.setattr(private_io.fcntl, "fcntl", failed)
    with pytest.raises(OSError) as denied:
        private_io.sync_file(12)
    assert denied.value.errno == errno.EIO
