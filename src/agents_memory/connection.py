from __future__ import annotations

import errno
import fcntl
import hashlib
import http.client
import io
import ipaddress
import json
import os
import re
import select
import socket
import ssl
import stat
import subprocess
import sys
import threading
import time
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator

from .config import Settings, load_settings
from .domain import DomainError, EffectState, Handle, TypedModel
from .private_io import private_read, private_write
from .wire import decode_json

_MAX_PROFILE_BYTES = 262144
_MAX_CA_BYTES = 1048576
_MAX_OAUTH_CHARACTERS = 16384


def https_origin(value: str) -> str:
    try:
        if not isinstance(value, str) or not value.isascii() or any(c.isspace() or ord(c) < 33 for c in value):
            raise ValueError
        url = urlsplit(value)
        if (url.scheme != "https" or not url.hostname or url.username is not None or url.password is not None
                or url.path not in {"", "/"} or "?" in value or "#" in value or "\\" in value):
            raise ValueError
        host = url.hostname
        try:
            address = ipaddress.ip_address(host)
            host = f"[{address.compressed}]" if address.version == 6 else address.compressed
        except ValueError:
            if (len(host) > 253 or host.endswith(".") or any(
                    re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) is None
                    for label in host.split("."))):
                raise ValueError
        port = url.port
        if port is not None and not 1 <= port <= 65535:
            raise ValueError
        authority = host + (f":{port}" if port not in {None, 443} else "")
        if url.netloc.lower() not in {authority, authority + ":443" if port == 443 else authority}:
            raise ValueError
        return "https://" + authority
    except (TypeError, ValueError):
        raise DomainError("DESTINATION_DENIED", "An explicit credential-free HTTPS root origin is required") from None


def _absolute_path(value: Path) -> Path:
    if not value.is_absolute() or ".." in value.parts or value != value.resolve():
        raise ValueError("Remote client paths must be absolute and canonical")
    for parent in value.parents:
        if not parent.exists():
            continue
        info = parent.stat()
        sticky_root = info.st_uid == 0 and bool(info.st_mode & stat.S_ISVTX)
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid not in {0, os.getuid()}
                or (info.st_mode & 0o022 and not sticky_root)):
            raise ValueError("Remote client paths require owned protected ancestors")
    return value


def _state_directory(path: Path) -> None:
    try:
        try:
            info = path.lstat()
        except FileNotFoundError:
            parent = path.parent
            while not parent.exists() and parent != parent.parent:
                parent = parent.parent
            info = parent.lstat()
        forbidden = 0o077 if path.exists() else 0o022
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & forbidden:
            raise DomainError("PATH_DENIED", "Remote client state requires a private owned directory")
    except OSError:
        raise DomainError("PATH_DENIED", "Remote client state is unavailable", status=503) from None


class RemoteClientSettings(TypedModel):
    kind: Literal["remote_client"] = "remote_client"
    version: Literal[1] = 1
    deployment_id: Handle
    realm: Handle
    mode: Literal["personal", "company"]
    capability: Literal["agent_judged"] = "agent_judged"
    base_url: str
    state_dir: Path
    auth_mode: Literal["bearer", "oauth"]
    ca_bundle: Path | None = None
    ca_bundle_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    max_capture_bytes: int = Field(default=131072, ge=1024, le=1048576, strict=True)
    max_http_body_bytes: int = Field(default=65536, ge=16384, le=262144, strict=True)
    max_mcp_response_bytes: int = Field(default=16384, ge=4096, le=65536, strict=True)
    spool_limit_bytes: int = Field(default=16777216, ge=65536, le=1073741824, strict=True)

    @field_validator("base_url")
    @classmethod
    def canonical_origin(cls, value: str) -> str:
        return https_origin(value)

    @field_validator("version", mode="before")
    @classmethod
    def integer_version(cls, value):
        if type(value) is not int:
            raise ValueError("The remote profile version must be an integer")
        return value

    @field_validator("state_dir", "ca_bundle")
    @classmethod
    def absolute_paths(cls, value: Path | None) -> Path | None:
        return _absolute_path(value) if value is not None else None

    @model_validator(mode="after")
    def private_client_paths(self) -> RemoteClientSettings:
        _state_directory(self.state_dir)
        if (self.ca_bundle is None) != (self.ca_bundle_sha256 is None):
            raise ValueError("A private CA bundle and its digest must be supplied together")
        if self.ca_bundle is not None and not self.ca_bundle.is_relative_to(self.state_dir):
            raise ValueError("The copied CA bundle must be inside private client state")
        return self


@dataclass(frozen=True)
class _RemoteConnectionCycle:
    profile: RemoteClientSettings
    deadline: float
    stop_event: threading.Event
    addresses: dict = field(default_factory=dict)


_remote_cycle: ContextVar[_RemoteConnectionCycle | None] = ContextVar("remote_connection_cycle", default=None)


def current_remote_cycle(profile: RemoteClientSettings) -> _RemoteConnectionCycle | None:
    cycle = _remote_cycle.get()
    return cycle if cycle is not None and cycle.profile == profile else None


@contextmanager
def remote_connection_cycle(
    profile: RemoteClientSettings, *, deadline: float, stop_event: threading.Event,
) -> Iterator[None]:
    token = _remote_cycle.set(_RemoteConnectionCycle(profile, deadline, stop_event))
    try:
        yield
    finally:
        _remote_cycle.reset(token)




def _ca_bytes(settings: RemoteClientSettings) -> bytes | None:
    if settings.ca_bundle is None:
        return None
    try:
        raw = private_read(settings.ca_bundle, _MAX_CA_BYTES)
        if hashlib.sha256(raw).hexdigest() != settings.ca_bundle_sha256:
            raise ValueError
        raw.decode("ascii")
        return raw
    except (DomainError, OSError, ValueError, UnicodeError):
        raise DomainError("CA_BUNDLE_INVALID", "The private remote CA bundle is unavailable or changed", status=503) from None


def remote_ssl_context(settings: RemoteClientSettings) -> ssl.SSLContext:
    try:
        _absolute_path(settings.state_dir)
        if settings.ca_bundle is not None:
            _absolute_path(settings.ca_bundle)
    except (OSError, ValueError):
        raise DomainError("PATH_DENIED", "Remote client paths have changed", status=503) from None
    _state_directory(settings.state_dir)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    try:
        raw = _ca_bytes(settings)
        if raw is not None:
            context.load_verify_locations(cadata=raw.decode("ascii"))
        else:
            defaults = ssl.get_default_verify_paths()
            cafile = defaults.openssl_cafile if defaults.openssl_cafile and Path(defaults.openssl_cafile).is_file() else None
            capath = defaults.openssl_capath if defaults.openssl_capath and Path(defaults.openssl_capath).is_dir() else None
            if cafile is None and capath is None:
                raise ValueError
            context.load_verify_locations(cafile=cafile, capath=capath)
    except (OSError, ValueError, ssl.SSLError):
        raise DomainError("CA_BUNDLE_INVALID", "Verified remote TLS trust is unavailable", status=503) from None
    return context


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("The HTTP deadline expired")
    return remaining


def _check_stop(stop_event: threading.Event | None) -> None:
    if stop_event is not None and stop_event.is_set():
        raise DomainError("SERVICE_DRAINING", "The remote connection stopped before business dispatch", status=503)


def _wait_socket(sock, deadline: float, stop_event: threading.Event | None, *, write: bool = False) -> None:
    while True:
        _check_stop(stop_event)
        readable, writable, _ = select.select(
            [] if write else [sock], [sock] if write else [], [], min(_remaining(deadline), 0.05),
        )
        if readable or writable:
            _check_stop(stop_event)
            return


class _DeadlineReader(io.RawIOBase):
    def __init__(self, raw, sock, deadline: float, *, stop_event: threading.Event | None = None) -> None:
        self.raw = raw
        self.sock = sock
        self.deadline = deadline
        self.stop_event = stop_event

    def readable(self) -> bool:
        return True

    def readinto(self, buffer) -> int:
        if self.stop_event is None:
            self.sock.settimeout(_remaining(self.deadline))
            count = self.raw.readinto(buffer)
        else:
            while True:
                _check_stop(self.stop_event)
                _remaining(self.deadline)
                self.sock.setblocking(False)
                try:
                    count = self.raw.readinto(buffer)
                    if count is not None:
                        break
                except ssl.SSLWantWriteError:
                    _wait_socket(self.sock, self.deadline, self.stop_event, write=True)
                    continue
                except (ssl.SSLWantReadError, BlockingIOError):
                    pass
                _wait_socket(self.sock, self.deadline, self.stop_event)
        _remaining(self.deadline)
        return count

    def close(self) -> None:
        try:
            self.raw.close()
        finally:
            super().close()


class _DeadlineSocket:
    def __init__(
        self, sock, deadline: float, *, stop_event: threading.Event | None = None, cancel_response: bool = False,
    ) -> None:
        self.sock = sock
        self.deadline = deadline
        self.dispatched = False
        self.stop_event = stop_event
        self.cancel_response = cancel_response

    def __getattr__(self, name):
        return getattr(self.sock, name)

    def sendall(self, data) -> None:
        if not self.dispatched:
            _check_stop(self.stop_event)
        try:
            self.sock.settimeout(_remaining(self.deadline))
        except TimeoutError:
            if self.dispatched:
                raise
            raise DomainError("SERVICE_UNAVAILABLE", "The HTTP deadline expired before dispatch", status=503) from None
        self.dispatched = True
        if not self.cancel_response:
            self.sock.sendall(data)
        else:
            # Only read-only readiness may cancel after sending. Business I/O drains.
            remaining = memoryview(data)
            self.sock.setblocking(False)
            while remaining:
                _check_stop(self.stop_event)
                _remaining(self.deadline)
                try:
                    sent = self.sock.send(remaining)
                    if sent == 0:
                        raise OSError("The remote readiness connection closed during dispatch")
                    remaining = remaining[sent:]
                except ssl.SSLWantReadError:
                    _wait_socket(self.sock, self.deadline, self.stop_event)
                except (ssl.SSLWantWriteError, BlockingIOError):
                    _wait_socket(self.sock, self.deadline, self.stop_event, write=True)
        _remaining(self.deadline)

    def makefile(self, mode, buffering=None):
        raw = self.sock.makefile(mode, buffering=0)
        return io.BufferedReader(_DeadlineReader(
            raw, self.sock, self.deadline, stop_event=self.stop_event if self.cancel_response else None,
        ))


def _resolve_tcp(host: str, port: int, deadline: float, *, stop_event: threading.Event | None = None):
    try:
        ipaddress.ip_address(host)
    except ValueError:
        # getaddrinfo cannot be cancelled in-process. Isolate only hostname
        # resolution, without credentials or inherited Python customization.
        command = (
            "import json,socket,sys; host,port=json.load(sys.stdin); "
            "json.dump(socket.getaddrinfo(host,port,0,socket.SOCK_STREAM),sys.stdout)"
        )
        _remaining(deadline)
        if stop_event is not None and stop_event.is_set():
            raise DomainError("SERVICE_DRAINING", "Readiness stopped before resolution", status=503)
        with subprocess.Popen(
            [sys.executable, "-I", "-S", "-X", "utf8", "-c", command],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", cwd="/",
            env={"PATH": os.defpath, "LANG": "C", "LC_ALL": "C"},
        ) as process:
            try:
                pending_input = json.dumps([host, port])
                while True:
                    if stop_event is not None and stop_event.is_set():
                        raise DomainError("SERVICE_DRAINING", "Readiness stopped during resolution", status=503)
                    remaining = _remaining(deadline)
                    try:
                        output, _ = process.communicate(
                            pending_input, timeout=min(remaining, 0.05) if stop_event is not None else remaining,
                        )
                        break
                    except subprocess.TimeoutExpired:
                        pending_input = None
                        _remaining(deadline)
            except BaseException:
                process.kill()
                process.wait()
                raise
            _remaining(deadline)
            if process.returncode:
                raise OSError("The HTTP endpoint could not be resolved")
        try:
            return [(family, kind, protocol, name, tuple(target))
                    for family, kind, protocol, name, target in json.loads(output)]
        except (ValueError, TypeError):
            raise OSError("The HTTP endpoint resolution was invalid") from None
    return socket.getaddrinfo(
        host, port, 0, socket.SOCK_STREAM, 0, socket.AI_NUMERICHOST | socket.AI_NUMERICSERV,
    )


def _connect_tcp(
    address, deadline: float, source_address=None, *,
    stop_event: threading.Event | None = None, resolution_cache: dict | None = None,
):
    host, port = address
    _remaining(deadline)
    if stop_event is not None and stop_event.is_set():
        raise DomainError("SERVICE_DRAINING", "Readiness stopped before connection", status=503)
    addresses = resolution_cache.get(address) if resolution_cache is not None else None
    if addresses is None:
        addresses = (_resolve_tcp(host, port, deadline, stop_event=stop_event) if stop_event is not None
                     else _resolve_tcp(host, port, deadline))
        if resolution_cache is not None:
            resolution_cache[address] = addresses
    failure = OSError("No address is available for the HTTP endpoint")
    for family, kind, protocol, _, target in addresses:
        _remaining(deadline)
        if stop_event is not None and stop_event.is_set():
            raise DomainError("SERVICE_DRAINING", "Readiness stopped before connection", status=503)
        sock = socket.socket(family, kind, protocol)
        try:
            sock.settimeout(_remaining(deadline))
            if source_address:
                sock.bind(source_address)
            if stop_event is None:
                sock.connect(target)
            else:
                sock.setblocking(False)
                result = sock.connect_ex(target)
                if result not in {0, errno.EISCONN}:
                    if result not in {errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EALREADY, errno.EINTR}:
                        raise OSError(result, os.strerror(result))
                    _wait_socket(sock, deadline, stop_event, write=True)
                    result = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                    if result:
                        raise OSError(result, os.strerror(result))
            sock.settimeout(_remaining(deadline))
            _check_stop(stop_event)
            return sock
        except OSError as error:
            failure = error
            sock.close()
        except BaseException:
            sock.close()
            raise
    _remaining(deadline)
    raise failure


class _DeadlineConnection:
    def __init__(
        self, *args, deadline: float, stop_event: threading.Event | None = None,
        resolution_cache: dict | None = None, cancel_response: bool = False, **kwargs,
    ) -> None:
        self.deadline = deadline
        self.stop_event = stop_event
        self.resolution_cache = resolution_cache
        self.cancel_response = cancel_response
        super().__init__(*args, **kwargs)
        self._create_connection = self._connect

    def _connect(self, address, timeout, source_address=None):
        return _connect_tcp(
            address, self.deadline, source_address,
            stop_event=self.stop_event, resolution_cache=self.resolution_cache,
        )

    def _prepare_connection(self) -> None:
        super().connect()

    def connect(self) -> None:
        try:
            self._prepare_connection()
            _remaining(self.deadline)
            _check_stop(self.stop_event)
        except TimeoutError:
            self.close()
            raise DomainError("SERVICE_UNAVAILABLE", "The HTTP deadline expired before dispatch", status=503) from None
        except ssl.SSLCertVerificationError:
            self.close()
            raise
        except OSError:
            self.close()
            raise DomainError("SERVICE_UNAVAILABLE", "The HTTP connection failed before dispatch", status=503) from None
        except BaseException:
            self.close()
            raise
        self.sock = _DeadlineSocket(
            self.sock, self.deadline, stop_event=self.stop_event, cancel_response=self.cancel_response,
        )


class _DeadlineHTTPConnection(_DeadlineConnection, http.client.HTTPConnection):
    pass


class _DeadlineHTTPSConnection(_DeadlineConnection, http.client.HTTPSConnection):
    def _prepare_connection(self) -> None:
        if self.stop_event is None:
            super()._prepare_connection()
            return
        http.client.HTTPConnection.connect(self)
        self.sock = self._context.wrap_socket(
            self.sock, server_hostname=self._tunnel_host or self.host, do_handshake_on_connect=False,
        )
        self.sock.setblocking(False)
        while True:
            _check_stop(self.stop_event)
            _remaining(self.deadline)
            try:
                self.sock.do_handshake()
                break
            except ssl.SSLWantReadError:
                _wait_socket(self.sock, self.deadline, self.stop_event)
            except ssl.SSLWantWriteError:
                _wait_socket(self.sock, self.deadline, self.stop_event, write=True)
        self.sock.settimeout(_remaining(self.deadline))


class _DeadlineHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, request):
        deadline = getattr(request, "_agents_memory_deadline", None)
        if deadline is None:
            deadline = time.monotonic() + request.timeout
        return self.do_open(
            lambda *args, **kwargs: _DeadlineHTTPConnection(*args, deadline=deadline, **kwargs), request,
        )


class _DeadlineHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, *, context, stop_event=None, resolution_deadline=None, resolution_cache=None):
        super().__init__(context=context)
        self.stop_event = stop_event
        self.resolution_deadline = resolution_deadline
        self.resolution_cache = {} if resolution_cache is None else resolution_cache

    def https_open(self, request):
        deadline = getattr(request, "_agents_memory_deadline", None)
        if deadline is None:
            deadline = time.monotonic() + request.timeout
        return self.do_open(
            lambda *args, **kwargs: _DeadlineHTTPSConnection(
                *args, deadline=deadline, stop_event=self.stop_event,
                resolution_cache=(self.resolution_cache if self.resolution_deadline is not None
                                  and time.monotonic() < self.resolution_deadline else None),
                cancel_response=getattr(request, "_agents_memory_cancel_response", False),
                **kwargs,
            ), request,
            context=self._context,
        )


def local_opener(redirect_handler: urllib.request.HTTPRedirectHandler):
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}), redirect_handler, _DeadlineHTTPHandler(),
    )


def remote_opener(
    settings: RemoteClientSettings, redirect_handler: urllib.request.HTTPRedirectHandler, *,
    stop_event: threading.Event | None = None, resolution_deadline: float | None = None,
):
    cycle = current_remote_cycle(settings)
    if cycle is not None:
        stop_event = cycle.stop_event if stop_event is None else stop_event
        resolution_deadline = min(resolution_deadline, cycle.deadline) if resolution_deadline is not None else cycle.deadline
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}), redirect_handler,
        _DeadlineHTTPSHandler(
            context=remote_ssl_context(settings), stop_event=stop_event, resolution_deadline=resolution_deadline,
            resolution_cache=cycle.addresses if cycle is not None else None,
        ),
    )


def open_http(opener, request: urllib.request.Request, *, deadline: float):
    try:
        timeout = _remaining(deadline)
    except TimeoutError:
        raise DomainError("SERVICE_UNAVAILABLE", "The HTTP deadline expired before dispatch", status=503) from None
    request._agents_memory_deadline = deadline
    return opener.open(request, timeout=timeout)


def _read_ca_source(source: Path) -> bytes:
    raw = private_read(source, _MAX_CA_BYTES, private=False)
    if b"PRIVATE KEY" in raw:
        raise DomainError("CA_BUNDLE_INVALID", "Trust bundles must not contain private key material")
    try:
        ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT).load_verify_locations(cadata=raw.decode("ascii"))
    except (ValueError, UnicodeError, ssl.SSLError):
        raise DomainError("CA_BUNDLE_INVALID", "The selected CA bundle is invalid") from None
    return raw




def load_remote_settings(path: Path) -> RemoteClientSettings:
    try:
        value = decode_json(private_read(path, _MAX_PROFILE_BYTES))
        if value.get("kind") != "remote_client" or type(value.get("version")) is not int or value["version"] != 1:
            raise ValueError
        settings = RemoteClientSettings.model_validate(value)
        remote_ssl_context(settings)
        return settings
    except (DomainError, OSError, ValueError, TypeError):
        raise DomainError("CONFIG_INVALID", "The private remote client configuration is invalid") from None


def load_connection_settings(path: Path) -> Settings | RemoteClientSettings:
    try:
        value = decode_json(private_read(path, _MAX_PROFILE_BYTES))
    except (DomainError, OSError, ValueError, TypeError):
        raise DomainError("CONFIG_INVALID", "The private connection configuration is invalid") from None
    if "kind" in value:
        return load_remote_settings(path)
    return load_settings(path)


def read_remote_credential(path: Path, settings: RemoteClientSettings) -> str:
    oauth = settings.auth_mode == "oauth"
    try:
        raw = private_read(path, (_MAX_OAUTH_CHARACTERS if oauth else 512 * 4) + 2)
        token = raw.decode("ascii" if oauth else "utf-8")
        token = token.removesuffix("\r\n").removesuffix("\n") if oauth else token.strip()
        if not token or len(token) > (_MAX_OAUTH_CHARACTERS if oauth else 512) or any(c.isspace() for c in token):
            raise ValueError
        if oauth and re.fullmatch(r"[A-Za-z0-9._~+/\-]+=*", token) is None:
            raise ValueError
        return token
    except (DomainError, OSError, ValueError, UnicodeError):
        raise DomainError("CREDENTIAL_INVALID", "The remote credential file is unavailable or invalid", status=401) from None


def validate_remote_endpoint(settings: RemoteClientSettings, base_url: str, state_dir: Path | None,
                             deployment_id: str | None) -> None:
    if (not isinstance(settings, RemoteClientSettings) or base_url != settings.base_url
            or state_dir != settings.state_dir or deployment_id != settings.deployment_id):
        raise DomainError("DESTINATION_DENIED", "The endpoint does not match the explicit remote client profile")


def validate_remote_project(settings: RemoteClientSettings, project_root: Path) -> None:
    try:
        project = _absolute_path(project_root)
    except (OSError, ValueError):
        raise DomainError("PATH_DENIED", "The PC project root must be an absolute protected path") from None
    state = settings.state_dir
    if state.is_relative_to(project) or project.is_relative_to(state):
        raise DomainError("PATH_DENIED", "Remote client state must be disjoint from the PC project root")


def configure_remote_client(
    path: Path, settings: RemoteClientSettings, *, ca_source: Path | None = None,
) -> dict:
    path = _absolute_path(path.absolute())
    ca_raw = None
    destination = None
    if ca_source is not None:
        if settings.ca_bundle is not None:
            raise DomainError("INPUT_INVALID", "Choose the profile CA bundle or --ca-file, not both", status=422)
        ca_raw = _read_ca_source(ca_source)
        destination = _absolute_path(settings.state_dir / "remote-ca.pem")
        settings = settings.model_copy(update={
            "ca_bundle": destination, "ca_bundle_sha256": hashlib.sha256(ca_raw).hexdigest(),
        })
    else:
        remote_ssl_context(settings)
    # Refuse a different committed profile before publishing any new CA.
    if path.exists() or path.is_symlink():
        if load_remote_settings(path) != settings:
            raise DomainError("CONFIG_EXISTS", "The existing remote profile differs; uninstall its owned entries before changing it")
    settings.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    _state_directory(settings.state_dir)
    descriptor = os.open(
        settings.state_dir / "client-configuration.lock",
        os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600,
    )
    created_ca = None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise DomainError("PATH_DENIED", "The client configuration lock must be private and owned")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise DomainError("CLIENT_CONFIGURATION_BUSY", "Another client configuration is in progress", status=409) from None
        replay = path.exists() or path.is_symlink()
        if replay:
            if load_remote_settings(path) != settings:
                raise DomainError("CONFIG_EXISTS", "The existing remote profile differs; uninstall its owned entries before changing it")
        else:
            if destination is not None:
                try:
                    private_write(destination, ca_raw)
                except FileExistsError:
                    if private_read(destination, _MAX_CA_BYTES) != ca_raw:
                        raise DomainError("CA_BUNDLE_CONFLICT", "The existing private CA bundle differs; it was not replaced") from None
                else:
                    info = destination.lstat()
                    created_ca = (info.st_dev, info.st_ino)
            remote_ssl_context(settings)
            private_write(path, settings.model_dump_json(indent=2) + "\n")
    except BaseException:
        if created_ca is not None and not path.exists() and not path.is_symlink():
            try:
                info = destination.lstat()
                if ((info.st_dev, info.st_ino) == created_ca
                        and stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                        and private_read(destination, _MAX_CA_BYTES) == ca_raw):
                    destination.unlink()
                    directory = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                    try:
                        os.fsync(directory)
                    finally:
                        os.close(directory)
            except OSError:
                raise DomainError(
                    "CLIENT_CONFIGURATION_CLEANUP_FAILED", "The profile was not committed and its owned CA cleanup failed",
                    status=503, effect=EffectState.UNKNOWN,
                ) from None
        raise
    finally:
        os.close(descriptor)
    return {
        "config_file": str(path), "kind": settings.kind, "deployment_id": settings.deployment_id,
        "realm": settings.realm, "mode": settings.mode, "base_url": settings.base_url,
        "auth_mode": settings.auth_mode, "native_configuration": "unchanged", "replay": replay,
    }


def read_http_body(response, *, maximum: int, deadline: float) -> bytes:
    _remaining(deadline)
    raw = response.read(maximum + 1)
    _remaining(deadline)
    # Bounded HTTPResponse.read can reach premature EOF without raising IncompleteRead.
    headers = getattr(response, "headers", None)
    length = headers.get("Content-Length") if headers is not None else None
    if (len(raw) <= maximum and length is not None and not getattr(response, "chunked", False)
        and (not length.isascii() or not length.isdecimal() or int(length) != len(raw))):
        raise http.client.HTTPException("The HTTP response is incomplete")
    return raw
