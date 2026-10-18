from __future__ import annotations

import errno
import fcntl
import os
import secrets
import stat
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from .domain import DomainError


def sync_file(fd: int) -> None:
    os.fsync(fd)
    full_sync = getattr(fcntl, "F_FULLFSYNC", None)
    if sys.platform == "darwin" and full_sync is not None:
        try:
            fcntl.fcntl(fd, full_sync)
        except OSError as error:
            if error.errno not in {errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP, errno.ENOSYS}:
                raise


def private_read(path: Path, maximum: int, *, private: bool = True, directory: int | None = None) -> bytes:
    """A supplied parent descriptor confines a stable, single-link input to one leaf."""
    if directory is not None and (path.is_absolute() or len(path.parts) != 1 or path.name in {"", ".", ".."}):
        raise DomainError("PATH_DENIED", "Descriptor-relative input must name one leaf")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    except OSError:
        raise DomainError("PATH_DENIED", "The input is unavailable") from None
    try:
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or (private and info.st_mode & 0o077) or info.st_size > maximum
                or (directory is not None and info.st_nlink != 1)):
            raise DomainError("PATH_DENIED", "The input must be an owned permitted regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            raw = stream.read(maximum + 1)
        if len(raw) > maximum:
            raise DomainError("INPUT_TOO_LARGE", "The input exceeds its bound")
        if directory is not None:
            after = os.fstat(descriptor)
            named = os.stat(path, dir_fd=directory, follow_symlinks=False)
            if (len(raw) != info.st_size or
                    (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
                    != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                    or (named.st_dev, named.st_ino) != (info.st_dev, info.st_ino)):
                raise DomainError("PATH_DENIED", "The pinned input changed during its bounded read")
        return raw
    finally:
        os.close(descriptor)


def private_write(
    path: Path, content: str | bytes, *, replace: bool = False,
    before_publish: Callable[[], None] | None = None, directory: int | None = None,
) -> None:
    # With an open ``directory`` descriptor of ``path.parent`` only ``path.name``
    # is resolved in it and no parent is created, so a moved or replaced ancestor
    # can neither redirect the output nor be recreated.
    if directory is None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = path if directory is None else path.name
    try:
        existing = os.stat(target, dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        existing = None
    if existing is not None and (not stat.S_ISREG(existing.st_mode) or existing.st_uid != os.getuid()):
        raise DomainError("PATH_DENIED", "A private output must be an owned regular file, not a symlink")
    raw = content.encode("utf-8") if isinstance(content, str) else content
    if directory is None:
        descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=".memory-private-")
    else:
        name = ".memory-private-" + secrets.token_hex(8)
        descriptor = os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
    owned = os.fstat(descriptor)
    try:
        if not stat.S_ISREG(owned.st_mode) or owned.st_uid != os.getuid() or owned.st_mode & 0o077:
            raise DomainError("PATH_DENIED", "The temporary output is not a private owned file")
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("The private output write made no progress")
            view = view[written:]
        sync_file(descriptor)
        os.close(descriptor)
        descriptor = -1
        # A refusing guard leaves the destination intact and the temporary
        # file is cleaned below. This observation is not cross-process CAS.
        if before_publish is not None:
            before_publish()
        if replace:
            os.replace(name, target, src_dir_fd=directory, dst_dir_fd=directory)
        else:
            os.link(name, target, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
        if directory is not None:
            os.fsync(directory)
        else:
            parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
    finally:
        if descriptor != -1:
            os.close(descriptor)
        try:
            remaining = os.stat(name, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            if (remaining.st_dev, remaining.st_ino) == (owned.st_dev, owned.st_ino):
                os.unlink(name, dir_fd=directory)
