from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import stat
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .private_io import sync_file
from .wire import decode_json


class ArtifactError(ValueError):
    pass


def digest_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def safe_path(value: str, *, depth: int, path_bytes: int, component_bytes: int) -> tuple[str, ...]:
    if not isinstance(value, str) or not value or unicodedata.normalize("NFC", value) != value:
        raise ArtifactError("PATH_REPRESENTATION")
    if any(ord(char) < 32 or ord(char) == 127 for char in value) or any(char in value for char in "\\:\x00"):
        raise ArtifactError("PATH_REPRESENTATION")
    parts = tuple(value.split("/"))
    if len(parts) > depth or len(value.encode("utf-8")) > path_bytes:
        raise ArtifactError("PATH_BOUND")
    if any(part in {"", ".", ".."} or part.endswith((" ", ".")) or len(part.encode("utf-8")) > component_bytes for part in parts):
        raise ArtifactError("PATH_REPRESENTATION")
    return parts


@dataclass(frozen=True)
class ArtifactLimits:
    bundle_bytes: int
    entries: int
    file_bytes: int
    total_bytes: int
    depth: int
    path_bytes: int
    component_bytes: int
    edits: int
    replacement_bytes: int

    def __post_init__(self) -> None:
        if any(type(value) is not int or value < 1 for value in vars(self).values()):
            raise ArtifactError("POSITIVE_LIMIT_REQUIRED")


@dataclass(frozen=True)
class ArtifactEntry:
    path: str
    kind: str
    mode: int
    content: bytes
    sha256: str

    def __post_init__(self) -> None:
        if self.kind not in {"file", "directory"} or type(self.content) is not bytes:
            raise ArtifactError("ENTRY_TYPE")
        if type(self.mode) is not int or self.mode < 0 or self.mode > 0o777:
            raise ArtifactError("ENTRY_MODE")
        if self.kind == "directory" and self.content:
            raise ArtifactError("DIRECTORY_CONTENT")
        if self.sha256 != digest_bytes(self.content):
            raise ArtifactError("CONTENT_DIGEST")

    def manifest(self) -> dict:
        return {"path": self.path, "kind": self.kind, "mode": self.mode, "size": len(self.content), "sha256": self.sha256}


@dataclass(frozen=True)
class ArtifactBundle:
    entries: tuple[ArtifactEntry, ...]
    limits: ArtifactLimits

    def __post_init__(self) -> None:
        if type(self.entries) is not tuple or len(self.entries) > self.limits.entries:
            raise ArtifactError("ENTRY_BOUND")
        paths: dict[str, ArtifactEntry] = {}
        folded: set[str] = set()
        total = 0
        for entry in self.entries:
            safe_path(entry.path, depth=self.limits.depth, path_bytes=self.limits.path_bytes, component_bytes=self.limits.component_bytes)
            if entry.path in paths or entry.path.casefold() in folded:
                raise ArtifactError("DUPLICATE_OR_CASE_AMBIGUOUS")
            paths[entry.path] = entry
            folded.add(entry.path.casefold())
            if len(entry.content) > self.limits.file_bytes:
                raise ArtifactError("FILE_BOUND")
            total += len(entry.content)
            if total > self.limits.total_bytes:
                raise ArtifactError("TOTAL_BOUND")
        if tuple(sorted(paths)) != tuple(entry.path for entry in self.entries):
            raise ArtifactError("ENTRY_ORDER")
        for entry in self.entries:
            parts = entry.path.split("/")
            for end in range(1, len(parts)):
                parent = paths.get("/".join(parts[:end]))
                if parent is None or parent.kind != "directory":
                    raise ArtifactError("ALL_PATHS_REQUIRED")
        if len(self.to_bytes()) > self.limits.bundle_bytes:
            raise ArtifactError("BUNDLE_BOUND")

    @property
    def digest(self) -> str:
        return digest_bytes(canonical_bytes({"schema": 1, "entries": [entry.manifest() for entry in self.entries]}))

    def to_bytes(self) -> bytes:
        return canonical_bytes({"schema": 1, "entries": [dict(entry.manifest(), content=base64.b64encode(entry.content).decode("ascii")) for entry in self.entries]})


def load_submission(path: Path, *, limits: ArtifactLimits) -> ArtifactBundle:
    if ".." in path.parts or not path.name:
        raise ArtifactError("SUBMISSION_PATH")
    parent = os.open("/" if path.is_absolute() else ".", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        parts = path.parts[1:-1] if path.is_absolute() else path.parts[:-1]
        for part in parts:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent)
            parent = next_fd
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    finally:
        os.close(parent)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > limits.bundle_bytes:
            raise ArtifactError("SUBMISSION_TYPE_OR_BOUND")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(limits.bundle_bytes + 1)
        after = os.fstat(fd)
        if len(raw) > limits.bundle_bytes or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ArtifactError("SUBMISSION_UNSTABLE")
    finally:
        os.close(fd)
    value = decode_json(raw)
    if set(value) != {"schema", "entries"} or type(value["schema"]) is not int or value["schema"] != 1 or not isinstance(value["entries"], list):
        raise ArtifactError("SUBMISSION_SCHEMA")
    if len(value["entries"]) > limits.entries:
        raise ArtifactError("ENTRY_BOUND")
    entries = []
    total = 0
    for item in value["entries"]:
        if not isinstance(item, dict) or set(item) != {"path", "kind", "mode", "size", "sha256", "content"}:
            raise ArtifactError("ENTRY_SCHEMA")
        size, encoded = item["size"], item["content"]
        if type(size) is not int or not 0 <= size <= limits.file_bytes or not isinstance(encoded, str) or len(encoded) > ((limits.file_bytes + 2) // 3) * 4:
            raise ArtifactError("FILE_BOUND")
        try:
            content = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            raise ArtifactError("CONTENT_ENCODING") from None
        if base64.b64encode(content).decode("ascii") != encoded or len(content) != size:
            raise ArtifactError("CONTENT_SIZE_OR_ENCODING")
        total += size
        if total > limits.total_bytes:
            raise ArtifactError("TOTAL_BOUND")
        entries.append(ArtifactEntry(item["path"], item["kind"], item["mode"], content, item["sha256"]))
    return ArtifactBundle(tuple(entries), limits)


def open_private_directory(path: Path) -> int:
    if not path.is_absolute():
        raise ArtifactError("ABSOLUTE_DIRECTORY_REQUIRED")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ArtifactError("PRIVATE_DIRECTORY_REQUIRED")
        result, fd = fd, -1
        return result
    finally:
        if fd >= 0:
            os.close(fd)


def materialize_snapshot(bundle: ArtifactBundle, destination: Path) -> None:
    parent = open_private_directory(destination.parent)
    root = -1
    try:
        os.mkdir(destination.name, 0o700, dir_fd=parent)
        root = os.open(destination.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        directories: list[ArtifactEntry] = []
        for entry in bundle.entries:
            parts = entry.path.split("/")
            current = os.dup(root)
            try:
                for part in parts[:-1]:
                    next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
                    os.close(current)
                    current = next_fd
                if entry.kind == "directory":
                    os.mkdir(parts[-1], 0o700, dir_fd=current)
                    directories.append(entry)
                else:
                    fd = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=current)
                    try:
                        view = memoryview(entry.content)
                        while view:
                            count = os.write(fd, view)
                            if count <= 0:
                                raise OSError("snapshot write made no progress")
                            view = view[count:]
                        os.fchmod(fd, entry.mode)
                        sync_file(fd)
                    finally:
                        os.close(fd)
                os.fsync(current)
            finally:
                os.close(current)
        for entry in reversed(directories):
            current = os.dup(root)
            try:
                for part in entry.path.split("/"):
                    next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
                    os.close(current)
                    current = next_fd
                os.fchmod(current, entry.mode)
                os.fsync(current)
            finally:
                os.close(current)
        os.fchmod(root, 0o755)
        os.fsync(root)
        os.fsync(parent)
    finally:
        if root >= 0:
            os.close(root)
        os.close(parent)


@dataclass(frozen=True)
class EditableSpan:
    path: str
    start: int
    end: int


@dataclass(frozen=True)
class ModePermission:
    path: str
    before: int
    after: int


@dataclass(frozen=True)
class EditPolicy:
    baseline_digest: str
    spans: tuple[EditableSpan, ...]
    creates: tuple[str, ...]
    deletes: tuple[str, ...]
    modes: tuple[ModePermission, ...]

    @property
    def digest(self) -> str:
        return digest_bytes(canonical_bytes({"baseline": self.baseline_digest, "spans": [vars(span) for span in self.spans], "creates": self.creates, "deletes": self.deletes, "modes": [vars(mode) for mode in self.modes]}))


@dataclass(frozen=True)
class ByteEdit:
    path: str
    start: int
    end: int
    replacement: bytes


@dataclass(frozen=True)
class EditWitness:
    baseline_digest: str
    final_digest: str
    edits: tuple[ByteEdit, ...]
    creates: tuple[ArtifactEntry, ...]
    deletes: tuple[str, ...]
    modes: tuple[ModePermission, ...]


@dataclass(frozen=True)
class StructuralOutcome:
    passed: bool
    baseline_digest: str
    final_digest: str
    policy_digest: str
    code: str


def verify_allowed_edits(baseline: ArtifactBundle, final: ArtifactBundle, policy: EditPolicy, witness: EditWitness) -> StructuralOutcome:
    def reject(code: str) -> StructuralOutcome:
        return StructuralOutcome(False, baseline.digest, final.digest, policy.digest, code)

    if baseline.digest != policy.baseline_digest or baseline.digest != witness.baseline_digest or final.digest != witness.final_digest:
        return reject("EDIT_IDENTITY")
    if any(type(value) is not tuple for value in (policy.spans, policy.creates, policy.deletes, policy.modes, witness.edits, witness.creates, witness.deletes, witness.modes)):
        return reject("IMMUTABLE_WITNESS_REQUIRED")
    limit = baseline.limits
    if sum(map(len, (witness.edits, witness.creates, witness.deletes, witness.modes))) > limit.edits or sum(len(edit.replacement) for edit in witness.edits) + sum(len(entry.content) for entry in witness.creates) > limit.replacement_bytes:
        return reject("EDIT_BOUND")
    original = {entry.path: entry for entry in baseline.entries}
    result = dict(original)
    for span in policy.spans:
        entry = original.get(span.path)
        if entry is None or entry.kind != "file" or type(span.start) is not int or type(span.end) is not int or not 0 <= span.start <= span.end <= len(entry.content):
            return reject("POLICY_SPAN")
    previous: tuple[str, int, int] | None = None
    cursor = 0
    path = ""
    chunks: list[bytes] = []
    for edit in witness.edits:
        entry = original.get(edit.path)
        key = (edit.path, edit.start, edit.end)
        if entry is None or entry.kind != "file" or type(edit.start) is not int or type(edit.end) is not int or type(edit.replacement) is not bytes or not 0 <= edit.start <= edit.end <= len(entry.content):
            return reject("EDIT_SPAN")
        if previous is not None and (key <= previous or (edit.path == previous[0] and edit.start < previous[2])):
            return reject("EDIT_OVERLAP_OR_ORDER")
        if not any(span.path == edit.path and span.start <= edit.start and edit.end <= span.end for span in policy.spans):
            return reject("EDIT_NOT_ALLOWED")
        if edit.path != path:
            if path:
                old = original[path]
                content = b"".join(chunks) + old.content[cursor:]
                result[path] = ArtifactEntry(path, "file", old.mode, content, digest_bytes(content))
            path, cursor, chunks = edit.path, 0, []
        chunks.extend((entry.content[cursor:edit.start], edit.replacement))
        cursor, previous = edit.end, key
    if path:
        old = original[path]
        content = b"".join(chunks) + old.content[cursor:]
        result[path] = ArtifactEntry(path, "file", old.mode, content, digest_bytes(content))
    if len(set(witness.deletes)) != len(witness.deletes):
        return reject("DUPLICATE_DELETE")
    for path in witness.deletes:
        if path not in policy.deletes or path not in original or any(edit.path == path for edit in witness.edits):
            return reject("DELETE_NOT_ALLOWED")
        del result[path]
    created: set[str] = set()
    for entry in witness.creates:
        if entry.path in original or entry.path in created or entry.path not in policy.creates:
            return reject("CREATE_NOT_ALLOWED")
        created.add(entry.path)
        result[entry.path] = entry
    changed_modes: set[str] = set()
    for mode in witness.modes:
        entry = result.get(mode.path)
        if entry is None or mode.path in changed_modes or mode not in policy.modes or entry.mode != mode.before:
            return reject("MODE_NOT_ALLOWED")
        changed_modes.add(mode.path)
        result[mode.path] = ArtifactEntry(entry.path, entry.kind, mode.after, entry.content, entry.sha256)
    try:
        reconstructed = ArtifactBundle(tuple(result[key] for key in sorted(result)), final.limits)
    except ArtifactError:
        return reject("RECONSTRUCTION_INVALID")
    if reconstructed.entries != final.entries:
        return reject("RETAINED_BYTES_OR_ALL_PATHS_CHANGED")
    return StructuralOutcome(True, baseline.digest, final.digest, policy.digest, "EXACT_RECONSTRUCTION")
