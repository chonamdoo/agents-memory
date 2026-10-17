from __future__ import annotations

import ast
import hashlib
import io
import os
import stat
import tokenize
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator

from .domain import DomainError, TypedModel, canonical_digest
from .health import CodeFileObservation, CodeSymbolObservation, Digest, relative_code_path

_FILE_BYTES = 262144
_PARSE_BYTES = 131072
_PARSE_NODES = 16384
_PARSE_DEPTH = 64
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_SymbolCoverage = Literal["complete", "partial", "unsupported"]
_UnresolvedStatus = Literal["missing", "unreadable", "oversized", "unstable"]


class RootPin(TypedModel):
    root: str = Field(min_length=1, max_length=4096)
    device: int = Field(ge=0, strict=True)
    inode: int = Field(ge=1, strict=True)
    nonce: Digest

    @field_validator("root")
    @classmethod
    def absolute_root(cls, value: str) -> str:
        path = Path(value)
        if (not path.is_absolute() or str(path) != value or value == "/"
                or any(part in {".", ".."} for part in value.split("/"))):
            raise ValueError("root must be an explicit normalized absolute directory")
        return value

    @property
    def fingerprint(self) -> str:
        return canonical_digest(self.model_dump(mode="json"))


@contextmanager
def _root_descriptor(root: str):
    descriptor = os.open("/", _DIRECTORY_FLAGS)
    try:
        for part in Path(root).parts[1:]:
            child = os.open(part, _DIRECTORY_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        yield descriptor
    finally:
        os.close(descriptor)


def pin_root(root: Path, nonce: str) -> RootPin:
    RootPin(root=str(root), device=0, inode=1, nonce=nonce)
    try:
        with _root_descriptor(str(root)) as descriptor:
            info = os.fstat(descriptor)
            return RootPin(root=str(root), device=info.st_dev, inode=info.st_ino, nonce=nonce)
    except OSError:
        raise DomainError("HEALTH_ROOT_UNAVAILABLE", "The explicit root cannot be pinned without symlinks") from None


def _matches_pin(descriptor: int, pin: RootPin) -> bool:
    info = os.fstat(descriptor)
    return (info.st_dev, info.st_ino) == (pin.device, pin.inode)


def _signature(info: os.stat_result) -> tuple:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


@contextmanager
def _parent(root: int, relative_path: str):
    descriptor = os.dup(root)
    try:
        for part in relative_path.split("/")[:-1]:
            child = os.open(part, _DIRECTORY_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        yield descriptor
    finally:
        os.close(descriptor)


def _python_symbols(raw: bytes, names: tuple[str, ...]) -> tuple[_SymbolCoverage, list[CodeSymbolObservation]]:
    if len(raw) > _PARSE_BYTES or len(names) > 16:
        return "partial", []
    try:
        encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
        if encoding != "utf-8":
            return "unsupported", []
        text = raw.decode("utf-8")
        tree = ast.parse(text)
    except (UnicodeError, SyntaxError, ValueError, RecursionError, MemoryError):
        return "unsupported", []
    offsets = [0]
    for line in raw.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    found: dict[str, list[CodeSymbolObservation]] = {}
    stack: list[tuple[ast.AST, tuple[str, ...], bool, int]] = [(tree, (), False, 0)]
    count = 0
    while stack:
        node, scope, class_scope, depth = stack.pop()
        count += 1
        if count > _PARSE_NODES or depth > _PARSE_DEPTH:
            return "partial", []
        nested_scope, nested_class = scope, class_scope
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = ".".join((*scope, node.name))
            nested_scope = (*scope, node.name)
            nested_class = isinstance(node, ast.ClassDef)
            if name in names:
                first_line, first_column = node.lineno, node.col_offset
                if node.decorator_list:
                    first = min(node.decorator_list, key=lambda item: (item.lineno, item.col_offset))
                    first_line, first_column = first.lineno, max(0, first.col_offset - 1)
                if node.end_lineno is None or node.end_col_offset is None:
                    return "partial", []
                start = offsets[first_line - 1] + first_column
                end = offsets[node.end_lineno - 1] + node.end_col_offset
                if not 0 <= start < end <= len(raw):
                    return "partial", []
                symbol = CodeSymbolObservation(
                    qualified_name=name,
                    kind="class" if nested_class else "method" if class_scope else "function",
                    byte_start=start, byte_end=end,
                    span_digest=hashlib.sha256(memoryview(raw)[start:end]).hexdigest(),
                    resolver="python_ast",
                )
                found.setdefault(name, []).append(symbol)
        for child in ast.iter_child_nodes(node):
            stack.append((child, nested_scope, nested_class, depth + 1))
    symbols = [found[name][0] for name in names if len(found.get(name, [])) == 1]
    return ("complete" if len(symbols) == len(names) else "partial"), symbols


def observe_file(pin: RootPin, relative_path: str, symbol_names: tuple[str, ...] = ()) -> CodeFileObservation:
    relative_code_path(relative_path)
    if (len(symbol_names) > 16 or len(set(symbol_names)) != len(symbol_names)
            or any(not name or len(name) > 512 for name in symbol_names)):
        raise DomainError("HEALTH_SYMBOL_LIMIT", "Choose at most sixteen distinct bounded symbols")
    def unresolved(status: _UnresolvedStatus) -> CodeFileObservation:
        return CodeFileObservation(relative_path=relative_path, status=status)

    try:
        with _root_descriptor(pin.root) as root:
            if not _matches_pin(root, pin):
                return unresolved("unstable")
            with _parent(root, relative_path) as parent:
                descriptor = os.open(
                    relative_path.split("/")[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                    dir_fd=parent,
                )
                try:
                    before = os.fstat(descriptor)
                    if not stat.S_ISREG(before.st_mode):
                        return unresolved("unreadable")
                    if before.st_size > _FILE_BYTES:
                        return unresolved("oversized")
                    with os.fdopen(descriptor, "rb", closefd=False) as stream:
                        raw = stream.read(_FILE_BYTES + 1)
                    after = os.fstat(descriptor)
                finally:
                    os.close(descriptor)
                if len(raw) > _FILE_BYTES:
                    return unresolved("oversized")
                if _signature(before) != _signature(after) or len(raw) != after.st_size:
                    return unresolved("unstable")
                # Reopen every ancestor: a detached-but-still-open parent is not current-path proof.
                with _root_descriptor(pin.root) as current_root:
                    if not _matches_pin(current_root, pin):
                        return unresolved("unstable")
                    with _parent(current_root, relative_path) as current_parent:
                        current = os.stat(relative_path.split("/")[-1], dir_fd=current_parent, follow_symlinks=False)
                        if _signature(current) != _signature(after):
                            return unresolved("unstable")
    except FileNotFoundError:
        # A replaced/disappeared root is not a missing file in the registered root.
        try:
            with _root_descriptor(pin.root) as root:
                if not _matches_pin(root, pin):
                    return unresolved("unstable")
        except OSError:
            return unresolved("unstable")
        return unresolved("missing")
    except OSError:
        return unresolved("unreadable")
    coverage: _SymbolCoverage = "unsupported"
    symbols: list[CodeSymbolObservation] = []
    if relative_path.endswith(".py"):
        coverage, symbols = _python_symbols(raw, symbol_names)
    return CodeFileObservation(
        relative_path=relative_path, status="present", byte_length=len(raw),
        file_digest=hashlib.sha256(raw).hexdigest(), symbol_coverage=coverage, symbols=symbols,
    )
