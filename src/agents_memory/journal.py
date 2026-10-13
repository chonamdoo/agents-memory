from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .domain import DomainError
from .private_io import private_read, private_write, sync_file


def _encoded(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


class DeletionJournal:
    def __init__(self, directory: Path, deployment_id: str) -> None:
        self.directory = Path(directory)
        self.deployment_id = deployment_id
        self._mutex = threading.RLock()

    def _error(self) -> DomainError:
        return DomainError("DELETION_BARRIER", "The independent deletion journal cannot be verified", status=503)

    def _check(self, path: Path, directory: bool = False) -> None:
        try:
            info = path.lstat()
        except OSError:
            raise self._error() from None
        wanted = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
        if not wanted or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise self._error()

    @contextmanager
    def _locked(self, create: bool = False) -> Iterator[None]:
        with self._mutex:
            if create:
                missing = []
                current = self.directory
                while not current.exists():
                    missing.append(current)
                    current = current.parent
                for path in reversed(missing):
                    path.mkdir(mode=0o700, exist_ok=True)
                    parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        os.fsync(parent)
                    finally:
                        os.close(parent)
            self._check(self.directory, directory=True)
            try:
                descriptor = os.open(self.directory / "lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            except OSError:
                raise self._error() from None
            try:
                self._check(self.directory / "lock")
                fcntl.flock(descriptor, fcntl.LOCK_EX)
                yield
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)

    def _sync_directory(self) -> None:
        descriptor = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _atomic(self, name: str, content: bytes) -> None:
        temporary = self.directory / f".pending-{secrets.token_hex(16)}"
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                sync_file(stream.fileno())
            os.replace(temporary, self.directory / name)
            self._sync_directory()
        finally:
            temporary.unlink(missing_ok=True)

    def initialize(self) -> dict:
        with self._locked(create=True):
            if any((self.directory / name).exists() for name in ("key", "metadata", "entries", "head")):
                raise DomainError("JOURNAL_EXISTS", "A deletion journal already exists")
            key = secrets.token_bytes(32)
            self._atomic("key", key)
            metadata = {"schema": 1, "deployment_id": self.deployment_id, "nonce": secrets.token_hex(32)}
            metadata["mac"] = hmac.new(key, _encoded(metadata), hashlib.sha256).hexdigest()
            self._atomic("metadata", _encoded(metadata))
            self._atomic("entries", b"")
            genesis = hashlib.sha256(_encoded(metadata)).hexdigest()
            self._atomic("head", _encoded({"head": genesis, "sequence": 0}))
            return {"head": genesis, "sequence": 0, "deployment_id": self.deployment_id}

    def _initialization_plan(self, intent_id: str, fingerprint: str, operator_token: str) -> dict | None:
        if not self.directory.exists():
            return None
        self._check(self.directory, directory=True)
        marker = self.directory / "initialization"
        if not marker.exists() and not marker.is_symlink():
            if any(path.name != "lock" for path in self.directory.iterdir()):
                raise DomainError("JOURNAL_EXISTS", "An unrelated deletion journal cannot be adopted")
            return None
        try:
            plan = json.loads(private_read(marker, 8192))
            fields = {"schema", "deployment_id", "intent_id", "fingerprint", "key", "nonce", "mac"}
            if not isinstance(plan, dict) or set(plan) != fields:
                raise self._error()
            unsigned = {name: value for name, value in plan.items() if name != "mac"}
            authentication_key = hashlib.sha256(("journal-initialization\0" + operator_token).encode()).digest()
            if (type(plan["schema"]) is not int or plan["schema"] != 1
                    or plan["deployment_id"] != self.deployment_id
                    or plan["intent_id"] != intent_id or plan["fingerprint"] != fingerprint
                    or any(not self._digest(plan[name]) for name in ("intent_id", "fingerprint", "key", "nonce", "mac"))
                    or not hmac.compare_digest(plan["mac"], hmac.new(authentication_key, _encoded(unsigned), hashlib.sha256).hexdigest())):
                raise self._error()
            key = bytes.fromhex(plan["key"])
            metadata = {"schema": 1, "deployment_id": self.deployment_id, "nonce": plan["nonce"]}
            metadata["mac"] = hmac.new(key, _encoded(metadata), hashlib.sha256).hexdigest()
            genesis = hashlib.sha256(_encoded(metadata)).hexdigest()
            components = {"key": key, "metadata": _encoded(metadata), "entries": b"",
                "head": _encoded({"head": genesis, "sequence": 0})}
            complete = all((self.directory / name).exists() for name in components)
            for name, expected in components.items():
                path = self.directory / name
                if not path.exists() and not path.is_symlink():
                    continue
                self._check(path)
                if (name in {"key", "metadata"} or not complete) and private_read(path, 8192) != expected:
                    raise self._error()
            if complete:
                self._verify(repair=False)
            return plan
        except (OSError, ValueError, KeyError, TypeError, RecursionError):
            raise self._error() from None

    def preflight_initialization(self, *, intent_id: str, fingerprint: str, operator_token: str) -> bool:
        with self._mutex:
            plan = self._initialization_plan(intent_id, fingerprint, operator_token)
            return plan is not None and all(
                (self.directory / name).exists() for name in ("key", "metadata", "entries", "head")
            )

    def initialize_owned(self, *, intent_id: str, fingerprint: str, operator_token: str) -> dict:
        with self._locked(create=True):
            plan = self._initialization_plan(intent_id, fingerprint, operator_token)
            if plan is None:
                plan = {"schema": 1, "deployment_id": self.deployment_id, "intent_id": intent_id,
                    "fingerprint": fingerprint, "key": secrets.token_hex(32), "nonce": secrets.token_hex(32)}
                authentication_key = hashlib.sha256(("journal-initialization\0" + operator_token).encode()).digest()
                plan["mac"] = hmac.new(authentication_key, _encoded(plan), hashlib.sha256).hexdigest()
                private_write(self.directory / "initialization", _encoded(plan))
            key = bytes.fromhex(plan["key"])
            metadata = {"schema": 1, "deployment_id": self.deployment_id, "nonce": plan["nonce"]}
            metadata["mac"] = hmac.new(key, _encoded(metadata), hashlib.sha256).hexdigest()
            genesis = hashlib.sha256(_encoded(metadata)).hexdigest()
            components = {"key": key, "metadata": _encoded(metadata), "entries": b"",
                "head": _encoded({"head": genesis, "sequence": 0})}
            for name, raw in components.items():
                path = self.directory / name
                if not path.exists():
                    private_write(path, raw)
            result, _ = self._verify()
            return result

    def _key(self) -> bytes:
        self._check(self.directory / "key")
        key = (self.directory / "key").read_bytes()
        if len(key) != 32:
            raise self._error()
        return key

    def _metadata(self, key: bytes) -> dict:
        self._check(self.directory / "metadata")
        try:
            metadata = json.loads((self.directory / "metadata").read_bytes())
            if not isinstance(metadata, dict) or set(metadata) != {"schema", "deployment_id", "nonce", "mac"}:
                raise self._error()
            mac = metadata.pop("mac")
            if (
                type(metadata["schema"]) is not int or metadata["schema"] != 1
                or metadata["deployment_id"] != self.deployment_id
                or not self._digest(metadata["nonce"]) or not self._digest(mac)
                or not hmac.compare_digest(mac, hmac.new(key, _encoded(metadata), hashlib.sha256).hexdigest())
            ):
                raise self._error()
            metadata["mac"] = mac
            return metadata
        except (OSError, ValueError, KeyError, TypeError):
            raise self._error() from None

    def _token(self, key: bytes, kind: str, values: tuple[str, ...]) -> str:
        return hmac.new(key, _encoded({"kind": kind, "values": values}), hashlib.sha256).hexdigest()

    def source_token(self, source_id: str) -> str:
        with self._locked():
            key = self._key()
            self._metadata(key)
            return self._token(key, "source", (source_id,))

    def origin_token(self, binding_id: str, origin_key: str) -> str:
        with self._locked():
            key = self._key()
            self._metadata(key)
            return self._token(key, "origin", (binding_id, origin_key))

    def artifact_tokens(self, refs: tuple[tuple[str, str], ...]) -> dict[tuple[str, str], str]:
        with self._locked():
            key = self._key()
            self._metadata(key)
            return {ref: self._token(key, "artifact", ref) for ref in refs}

    def _digest(self, value) -> bool:
        return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None

    def _verify(self, expected_head: str | None = None, *, repair: bool = True) -> tuple[dict, list[dict]]:
        key = self._key()
        for name in ("metadata", "entries", "head"):
            self._check(self.directory / name)
        try:
            metadata = self._metadata(key)
            previous = hashlib.sha256(_encoded(metadata)).hexdigest()
            historical_heads = {0: previous}
            recorded = json.loads((self.directory / "head").read_bytes())
            if (
                not isinstance(recorded, dict) or set(recorded) != {"head", "sequence"}
                or type(recorded["sequence"]) is not int or recorded["sequence"] < 0
                or not self._digest(recorded["head"])
            ):
                raise self._error()
            entries = []
            complete_bytes = 0
            torn = False
            with (self.directory / "entries").open("rb") as stream:
                for sequence, line in enumerate(stream, 1):
                    if not line.endswith(b"\n"):
                        torn = True
                        break
                    entry = json.loads(line)
                    if not isinstance(entry, dict):
                        raise self._error()
                    entry_mac = entry.pop("mac")
                    fields = {"sequence", "previous", "binding_token", "source_tokens", "origin_tokens"}
                    if set(entry) not in (fields, fields | {"artifact_tokens"}):
                        raise self._error()
                    token_fields = ("source_tokens", "origin_tokens", "artifact_tokens")
                    if (
                        type(entry["sequence"]) is not int or entry["sequence"] != sequence
                        or entry["previous"] != previous or not self._digest(entry_mac)
                        or not self._digest(entry["binding_token"])
                        or any(not isinstance(entry.get(field, []), list) for field in token_fields)
                        or any(not self._digest(token) for field in token_fields for token in entry.get(field, []))
                        or not hmac.compare_digest(entry_mac, hmac.new(key, _encoded(entry), hashlib.sha256).hexdigest())
                    ):
                        raise self._error()
                    entry["mac"] = entry_mac
                    previous = hashlib.sha256(_encoded(entry)).hexdigest()
                    historical_heads[sequence] = previous
                    entries.append(entry)
                    complete_bytes += len(line)
            if historical_heads.get(recorded["sequence"]) != recorded["head"]:
                raise self._error()
            if expected_head is not None and (
                not self._digest(expected_head) or not hmac.compare_digest(expected_head, previous)
            ):
                raise self._error()
            if not repair and (torn or recorded["sequence"] != len(entries)):
                raise self._error()
            if torn:
                descriptor = os.open(self.directory / "entries", os.O_WRONLY | os.O_NOFOLLOW)
                try:
                    os.ftruncate(descriptor, complete_bytes)
                    sync_file(descriptor)
                finally:
                    os.close(descriptor)
            result = {"head": previous, "sequence": len(entries), "deployment_id": self.deployment_id}
            if recorded["sequence"] != len(entries):
                self._atomic("head", _encoded({"head": previous, "sequence": len(entries)}))
            return result, entries
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            raise self._error() from None

    def _snapshot(self, expected_head: str | None = None) -> tuple[dict, list[dict]]:
        with self._locked():
            return self._verify(expected_head)

    def verify(self, expected_head: str | None = None) -> dict:
        with self._locked():
            result, _ = self._verify(expected_head)
            return result

    def entries(self) -> list[dict]:
        with self._locked():
            _, entries = self._verify()
            return entries

    def append(self, binding_id: str, source_ids: tuple[str, ...], origin_keys: tuple[str, ...], artifact_refs: tuple[tuple[str, str], ...] = ()) -> dict:
        if not source_ids and not origin_keys and not artifact_refs:
            raise DomainError("RETRACTION_TARGET_REQUIRED", "A deletion intent requires an explicit source, origin or artifact")
        with self._locked():
            current, _ = self._verify()
            key = self._key()
            entry = {
                "sequence": current["sequence"] + 1,
                "previous": current["head"],
                "binding_token": self._token(key, "binding", (binding_id,)),
                "source_tokens": sorted({self._token(key, "source", (value,)) for value in source_ids}),
                "origin_tokens": sorted({self._token(key, "origin", (binding_id, value)) for value in origin_keys}),
            }
            if artifact_refs:
                entry["artifact_tokens"] = sorted({self._token(key, "artifact", ref) for ref in artifact_refs})
            entry["mac"] = hmac.new(key, _encoded(entry), hashlib.sha256).hexdigest()
            descriptor = os.open(self.directory / "entries", os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW)
            with os.fdopen(descriptor, "ab") as stream:
                stream.write(_encoded(entry) + b"\n")
                stream.flush()
                sync_file(stream.fileno())
            head = hashlib.sha256(_encoded(entry)).hexdigest()
            self._atomic("head", _encoded({"head": head, "sequence": entry["sequence"]}))
            return {"head": head, "sequence": entry["sequence"], "deployment_id": self.deployment_id}
