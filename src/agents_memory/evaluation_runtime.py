from __future__ import annotations

import base64
import hashlib
import math
import os
import re
import selectors
import signal
import stat
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Event

from .evaluation_artifacts import canonical_bytes, digest_bytes, open_private_directory
from .private_io import private_write
from .wire import decode_json_value

OWNER_LABEL = "org.agents-memory.ci-owner"
CONFIG_LABEL = "org.agents-memory.evaluation-config"
HEX64 = re.compile(r"[0-9a-f]{64}\Z")

TOOL_PROBE_SOURCE = '''import hashlib, json, os, platform, sys
def status(path):
    with open(path, encoding="ascii") as stream:
        return dict(line.rstrip().split(":", 1) for line in stream if ":" in line)
def secure(value, uid):
    return value["Uid"].split() == [str(uid)] * 4 and int(value["CapEff"], 16) == 0 and int(value["NoNewPrivs"]) == 1 and int(value["Seccomp"]) == 2
binary = os.path.realpath(sys.executable)
digest = hashlib.sha256()
with open(binary, "rb") as stream:
    while block := stream.read(65536):
        digest.update(block)
print(json.dumps({"tool": {"executable": binary, "sha256": digest.hexdigest(), "version": sys.version, "implementation": platform.python_implementation(), "machine": platform.machine()}, "watchdog_secure": secure(status("/proc/1/status"), 0), "subject_secure": secure(status("/proc/self/status"), 65532)}))
'''

WATCHDOG_SOURCE = b'''import os, signal, sys, time
stop = False
def terminate(signum, frame):
    global stop
    stop = True
signal.signal(signal.SIGTERM, terminate)
signal.signal(signal.SIGINT, terminate)
if os.getpid() != 1 or os.getuid() != 0:
    os._exit(120)
ttl = float(sys.argv[1])
if not 0 < ttl < float("inf"):
    os._exit(121)
deadline = time.monotonic() + ttl
while not stop and time.monotonic() < deadline:
    while True:
        try:
            pid, status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            break
        if pid == 0:
            break
    time.sleep(min(0.05, max(0, deadline - time.monotonic())))
os._exit(0)
'''

OBSERVER_SOURCE = b'''import base64, json, os, stat, sys
path, limit = sys.argv[1], int(sys.argv[2])
parts = path.split("/")
if not parts or any(p in ("", ".", "..") for p in parts):
    os._exit(120)
fd = os.open("/scratch", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
try:
    for p in parts[:-1]:
        nxt = os.open(p, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
        os.close(fd)
        fd = nxt
    src = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    try:
        before = os.fstat(src)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > limit:
            os._exit(121)
        data = bytearray()
        while len(data) <= limit:
            block = os.read(src, min(65536, limit + 1 - len(data)))
            if not block:
                break
            data.extend(block)
        after = os.fstat(src)
        identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        if len(data) > limit or identity(before) != identity(after):
            os._exit(122)
        print(json.dumps({"content": base64.b64encode(data).decode("ascii"), "size": len(data)}))
    finally:
        os.close(src)
finally:
    os.close(fd)
'''


class RuntimeRefusal(ValueError):
    pass


@dataclass(frozen=True)
class Publication:
    state: str
    sha256: str


def _reconcile_publication_links(directory: int, name: str, fd: int) -> os.stat_result:
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeRefusal("RECOVERY_RECORD_IDENTITY")
    if info.st_nlink == 1:
        return info
    if info.st_nlink != 2 or stat.S_IMODE(info.st_mode) != 0o600:
        raise RuntimeRefusal("RECOVERY_RECORD_IDENTITY")
    identity = (info.st_dev, info.st_ino)
    temporary = None
    with os.scandir(directory) as entries:
        for entry in entries:
            if entry.name != name and re.fullmatch(r"\.memory-private-[0-9a-f]{16}", entry.name):
                candidate = os.stat(entry.name, dir_fd=directory, follow_symlinks=False)
                if (candidate.st_dev, candidate.st_ino) == identity:
                    temporary = entry.name
                    break
    current = os.stat(name, dir_fd=directory, follow_symlinks=False)
    if (current.st_dev, current.st_ino) != identity:
        raise RuntimeRefusal("RECOVERY_RECORD_IDENTITY")
    if os.fstat(fd).st_nlink == 1:
        return os.fstat(fd)
    if temporary is None:
        raise RuntimeRefusal("RECOVERY_RECORD_IDENTITY")
    candidate = os.stat(temporary, dir_fd=directory, follow_symlinks=False)
    if (candidate.st_dev, candidate.st_ino) != identity or candidate.st_nlink != 2:
        raise RuntimeRefusal("RECOVERY_RECORD_IDENTITY")
    os.fsync(fd)
    os.unlink(temporary, dir_fd=directory)
    os.fsync(directory)
    info = os.fstat(fd)
    current = os.stat(name, dir_fd=directory, follow_symlinks=False)
    if info.st_nlink != 1 or (current.st_dev, current.st_ino) != identity:
        raise RuntimeRefusal("RECOVERY_RECORD_IDENTITY")
    return info


def publish_or_reconcile(directory: int, name: str, raw: bytes) -> Publication:
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+", name):
        raise RuntimeRefusal("RECEIPT_NAME")
    try:
        private_write(Path(name), raw, directory=directory)
        return Publication("durable", digest_bytes(raw))
    except Exception:
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            try:
                info = _reconcile_publication_links(directory, name, fd)
                if info.st_size != len(raw):
                    return Publication("conflict", digest_bytes(raw))
                with os.fdopen(fd, "rb", closefd=False) as stream:
                    existing = stream.read(len(raw) + 1)
                if existing != raw:
                    return Publication("conflict", digest_bytes(raw))
                os.fsync(fd)
                os.fsync(directory)
                return Publication("reconciled_durable", digest_bytes(raw))
            finally:
                os.close(fd)
        except FileNotFoundError:
            return Publication("absent", digest_bytes(raw))
        except RuntimeRefusal:
            return Publication("conflict", digest_bytes(raw))
        except OSError:
            return Publication("visible_or_unknown", digest_bytes(raw))


@dataclass(frozen=True)
class EvaluationOwner:
    run_id: str
    run_attempt: str
    job_id: str
    attempt_id: str
    nonce: str

    def __post_init__(self) -> None:
        if any(not re.fullmatch(r"[a-zA-Z0-9_.-]{1,128}", item) for item in vars(self).values()):
            raise RuntimeRefusal("OWNER_IDENTITY")
        if not re.fullmatch(r"[0-9a-f]{32}", self.nonce):
            raise RuntimeRefusal("OWNER_NONCE")

    @property
    def identity(self) -> str:
        return digest_bytes(canonical_bytes(asdict(self)))

    def name(self, case_id: str) -> str:
        return "ameval-" + digest_bytes(canonical_bytes([self.identity, case_id]))[:40]

    def require_actions(self) -> None:
        if sys.platform != "linux" or os.uname().machine != "x86_64" or os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted":
            raise RuntimeRefusal("HOSTED_LINUX_AMD64_REQUIRED")
        if (os.environ.get("GITHUB_RUN_ID"), os.environ.get("GITHUB_RUN_ATTEMPT"), os.environ.get("GITHUB_JOB")) != (self.run_id, self.run_attempt, self.job_id):
            raise RuntimeRefusal("ACTIONS_OWNER_MISMATCH")


@dataclass(frozen=True)
class RuntimeLimits:
    cpu_nanos: int
    memory_bytes: int
    pids: int
    file_descriptors: int
    file_bytes: int
    scratch_bytes: int
    tmp_bytes: int
    shm_bytes: int
    wall_seconds: float
    watchdog_seconds: float
    operation_seconds: float
    cleanup_seconds: float
    stdin_bytes: int
    stdout_bytes: int
    stderr_bytes: int
    helper_bytes: int

    def __post_init__(self) -> None:
        for key, value in vars(self).items():
            if key.endswith("seconds"):
                if type(value) not in {int, float} or not math.isfinite(value) or value <= 0:
                    raise RuntimeRefusal("RUNTIME_LIMIT")
            elif type(value) is not int or value <= 0:
                raise RuntimeRefusal("RUNTIME_LIMIT")
        if self.watchdog_seconds <= self.wall_seconds + self.cleanup_seconds:
            raise RuntimeRefusal("WATCHDOG_MARGIN")


@dataclass(frozen=True)
class RuntimeSpec:
    docker_executable: Path
    docker_sha256: str
    docker_config: Path
    docker_endpoint: str
    image_reference: str
    image_id: str
    image_config_digest: str
    image_environment: tuple[str, ...]
    python_executable: str
    tool_identity: str
    watchdog_digest: str
    observer_digest: str
    limits: RuntimeLimits

    def __post_init__(self) -> None:
        if not self.docker_executable.is_absolute() or not self.docker_config.is_absolute() or not self.docker_endpoint.startswith("unix:///"):
            raise RuntimeRefusal("DOCKER_HOST_IDENTITY")
        if not re.fullmatch(r"[^\s]+@sha256:[0-9a-f]{64}", self.image_reference) or not re.fullmatch(r"sha256:[0-9a-f]{64}", self.image_id):
            raise RuntimeRefusal("PINNED_IMAGE_REQUIRED")
        if self.python_executable != "/usr/local/bin/python3" or self.watchdog_digest != digest_bytes(WATCHDOG_SOURCE) or self.observer_digest != digest_bytes(OBSERVER_SOURCE):
            raise RuntimeRefusal("TRUSTED_RUNTIME_SOURCE")
        if any(not HEX64.fullmatch(value) for value in (self.docker_sha256, self.image_config_digest, self.tool_identity)):
            raise RuntimeRefusal("RUNTIME_DIGEST")
        if type(self.image_environment) is not tuple:
            raise RuntimeRefusal("IMMUTABLE_ENVIRONMENT_REQUIRED")

    @property
    def digest(self) -> str:
        value = asdict(self)
        value["docker_executable"] = str(self.docker_executable)
        value["docker_config"] = str(self.docker_config)
        return digest_bytes(canonical_bytes(value))


@dataclass(frozen=True)
class CommandObservation:
    state: str
    exit_code: int | None
    stdout: bytes
    stderr: bytes
    elapsed_seconds: float
    stdout_complete: bool
    stderr_complete: bool
    helper_cleanup: bool

    @property
    def completed(self) -> bool:
        return self.state == "completed" and self.exit_code == 0 and self.stdout_complete and self.stderr_complete and self.helper_cleanup

    def public(self) -> dict:
        return {"state": self.state, "exit_code": self.exit_code, "elapsed_seconds": self.elapsed_seconds, "stdout_bytes": len(self.stdout), "stderr_bytes": len(self.stderr), "stdout_sha256": digest_bytes(self.stdout), "stderr_sha256": digest_bytes(self.stderr), "stdout_complete": self.stdout_complete, "stderr_complete": self.stderr_complete, "helper_cleanup": self.helper_cleanup}


class CommandLease:
    def __init__(self, argv: list[str], env: dict[str, str], *, stdin: bytes, seconds: float, stdout_limit: int, stderr_limit: int, stop_event: Event | None = None):
        self.process: subprocess.Popen[bytes] | None = None
        self.observation = CommandObservation("not_started", None, b"", b"", 0, False, False, True)
        self._started = time.monotonic()
        self._stdout = bytearray()
        self._stderr = bytearray()
        self._exit: int | None = None
        self._state = "completed"
        self._eof = {"stdout": False, "stderr": False}
        self._closed = False
        try:
            self.process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd="/", start_new_session=True)
        except OSError:
            return
        process = self.process
        assert process.stdin is not None and process.stdout is not None and process.stderr is not None
        selector = selectors.DefaultSelector()
        try:
            for stream, tag in ((process.stdout, "stdout"), (process.stderr, "stderr")):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, tag)
            if stdin:
                os.set_blocking(process.stdin.fileno(), False)
                selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")
            else:
                process.stdin.close()
            sent = 0
            deadline = self._started + seconds
            while True:
                if stop_event is not None and stop_event.is_set():
                    self._state = "aborted"
                    break
                if time.monotonic() >= deadline:
                    self._state = "timeout"
                    break
                exited = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
                if exited is not None:
                    self._exit = exited.si_status if exited.si_code == os.CLD_EXITED else -exited.si_status
                if self._exit is not None and all(self._eof.values()):
                    if sent != len(stdin):
                        self._state = "stdin_incomplete"
                    break
                for key, _ in selector.select(min(0.05, max(0, deadline - time.monotonic()))):
                    if key.data == "stdin":
                        try:
                            count = os.write(key.fd, stdin[sent:sent + 65536])
                            sent += count
                        except BrokenPipeError:
                            selector.unregister(key.fileobj)
                            key.fileobj.close()
                            self._state = "stdin_incomplete"
                            break
                        if sent == len(stdin):
                            selector.unregister(key.fileobj)
                            key.fileobj.close()
                    else:
                        block = os.read(key.fd, 65536)
                        if not block:
                            self._eof[key.data] = True
                            selector.unregister(key.fileobj)
                            continue
                        target, maximum = (self._stdout, stdout_limit) if key.data == "stdout" else (self._stderr, stderr_limit)
                        remaining = maximum - len(target)
                        target.extend(block[:remaining])
                        if len(block) > remaining:
                            self._state = "output_limit"
                            break
                if self._state != "completed":
                    break
        except (OSError, ValueError):
            self._state = "io_unknown"
        finally:
            selector.close()
        self._refresh(False)

    def _refresh(self, cleanup: bool) -> None:
        self.observation = CommandObservation(self._state, self._exit, bytes(self._stdout), bytes(self._stderr), time.monotonic() - self._started, self._eof["stdout"], self._eof["stderr"], cleanup)

    def close(self, seconds: float) -> CommandObservation:
        if self._closed or self.process is None:
            return self.observation
        self._closed = True
        process = self.process
        deadline = time.monotonic() + seconds
        cleanup = True
        try:
            if process.returncode is not None:
                cleanup = False
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    self._group_gone = True
                process.wait(timeout=max(0.001, deadline - time.monotonic()))
        except (OSError, subprocess.TimeoutExpired):
            cleanup = False
        finally:
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
        self._refresh(cleanup)
        return self.observation


@dataclass(frozen=True)
class ResourceIntent:
    schema: int
    name: str
    owner: str
    runtime: str
    configuration: str
    snapshot: str
    case_id: str
    image_id: str
    snapshot_path: str
    watchdog_path: str
    observer_path: str
    create_argv: tuple[str, ...]


@dataclass(frozen=True)
class CleanupObservation:
    state: str
    container_id: str | None
    exact_absence: bool
    ownership_verified: bool
    pending_create: bool


@dataclass(frozen=True)
class SubjectObservation:
    case_id: str
    state: str
    execution: CommandObservation | None
    effects: tuple[tuple[str, bytes | None], ...]
    cleanup: CleanupObservation
    container_id: str | None
    resource_digest: str
    operations: tuple[tuple[str, CommandObservation], ...]


class DockerRuntime:
    def __init__(self, spec: RuntimeSpec, owner: EvaluationOwner, intent_dir: Path):
        self.spec, self.owner, self.intent_dir = spec, owner, intent_dir
        self.directory = open_private_directory(intent_dir)
        self.environment = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "DOCKER_CONFIG": str(spec.docker_config), "DOCKER_HOST": spec.docker_endpoint}
        self.operations: list[tuple[str, CommandObservation]] = []
        try:
            self.record(owner.identity + ".owner.json", {"schema": 1, "owner": asdict(owner), "runtime": spec.digest})
        except Exception:
            os.close(self.directory)
            raise

    def close(self) -> None:
        os.close(self.directory)

    def record(self, name: str, value: object) -> None:
        result = publish_or_reconcile(self.directory, name, canonical_bytes(value))
        if result.state not in {"durable", "reconciled_durable"}:
            raise RuntimeRefusal("INTENT_PUBLICATION_" + result.state.upper())

    def command(self, label: str, args: list[str], *, seconds: float | None = None) -> CommandObservation:
        limit = self.spec.limits
        lease = CommandLease([str(self.spec.docker_executable), *args], self.environment, stdin=b"", seconds=seconds or limit.operation_seconds, stdout_limit=limit.helper_bytes, stderr_limit=limit.helper_bytes)
        result = lease.close(limit.cleanup_seconds)
        self.operations.append((label, result))
        return result

    def preflight(self) -> None:
        self.owner.require_actions()
        config = open_private_directory(self.spec.docker_config)
        os.close(config)
        fd = os.open(self.spec.docker_executable, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022 or info.st_size > 256 * 1024 * 1024:
                raise RuntimeRefusal("DOCKER_EXECUTABLE_IDENTITY")
            digest = hashlib.sha256()
            while block := os.read(fd, 65536):
                digest.update(block)
            if digest.hexdigest() != self.spec.docker_sha256:
                raise RuntimeRefusal("DOCKER_EXECUTABLE_IDENTITY")
        finally:
            os.close(fd)
        engine = self.command("engine", ["info", "--format", "{{json .}}"])
        value = self._object(engine)
        options = value.get("SecurityOptions", [])
        if value.get("OSType") != "linux" or value.get("Architecture") not in {"x86_64", "amd64"} or not any("seccomp" in item for item in options):
            raise RuntimeRefusal("ENGINE_CONTAINMENT_UNAVAILABLE")
        image = self._object(self.command("image", ["image", "inspect", self.spec.image_reference]), array=True)
        config_value = image.get("Config", {})
        if image.get("Id") != self.spec.image_id or image.get("Os") != "linux" or image.get("Architecture") != "amd64" or self.spec.image_reference not in image.get("RepoDigests", []):
            raise RuntimeRefusal("IMAGE_IDENTITY")
        if digest_bytes(canonical_bytes(config_value)) != self.spec.image_config_digest or tuple(config_value.get("Env") or ()) != self.spec.image_environment:
            raise RuntimeRefusal("IMAGE_CONFIG_IDENTITY")
        if any(config_value.get(key) for key in ("Volumes", "OnBuild", "Healthcheck", "Entrypoint")) or config_value.get("User") not in {"", "0", "0:0", "root"}:
            raise RuntimeRefusal("IMAGE_STARTUP_DENIED")

    @staticmethod
    def _object(observation: CommandObservation, *, array: bool = False) -> dict:
        if not observation.completed or not observation.helper_cleanup:
            raise RuntimeRefusal("DOCKER_OBSERVATION_INCOMPLETE")
        value = decode_json_value(observation.stdout)
        if array:
            if not isinstance(value, list) or len(value) != 1:
                raise RuntimeRefusal("DOCKER_INSPECTION_SHAPE")
            value = value[0]
        if not isinstance(value, dict):
            raise RuntimeRefusal("DOCKER_INSPECTION_SHAPE")
        return value

    def intent(self, *, case_id: str, snapshot: str, snapshot_path: Path, watchdog_path: Path, observer_path: Path) -> ResourceIntent:
        limit = self.spec.limits
        name = self.owner.name(case_id)
        configuration = digest_bytes(canonical_bytes([self.spec.digest, str(snapshot_path), str(watchdog_path), str(observer_path), snapshot, self.owner.identity, case_id]))
        mounts = []
        for source, target in ((snapshot_path, "/artifact"), (watchdog_path, "/watchdog.py"), (observer_path, "/observer.py")):
            if not source.is_absolute() or any(char in str(source) for char in ",\n\r"):
                raise RuntimeRefusal("MOUNT_PATH")
            mounts.extend(["--mount", f"type=bind,src={source},dst={target},readonly,bind-propagation=rprivate,bind-recursive=disabled"])
        args = ["create", "--pull=never", "--name", name, "--label", f"{OWNER_LABEL}={self.owner.identity}", "--label", f"{CONFIG_LABEL}={configuration}", "--platform", "linux/amd64", "--network", "none", "--ipc", "private", "--cgroupns", "private", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true", "--user", "0:0", "--workdir", "/", "--hostname", "evaluation", "--restart", "no", "--no-healthcheck", "--log-driver", "none", "--cpus", str(limit.cpu_nanos / 1_000_000_000), "--memory", str(limit.memory_bytes), "--memory-swap", str(limit.memory_bytes), "--pids-limit", str(limit.pids), "--ulimit", f"nofile={limit.file_descriptors}:{limit.file_descriptors}", "--ulimit", f"fsize={limit.file_bytes}:{limit.file_bytes}", "--ulimit", "core=0:0", "--shm-size", str(limit.shm_bytes), "--tmpfs", f"/scratch:rw,nosuid,nodev,noexec,size={limit.scratch_bytes},mode=1777", "--tmpfs", f"/tmp:rw,nosuid,nodev,noexec,size={limit.tmp_bytes},mode=1777", *mounts, "--entrypoint", self.spec.python_executable, self.spec.image_reference, "-I", "-S", "/watchdog.py", str(limit.watchdog_seconds)]
        return ResourceIntent(1, name, self.owner.identity, self.spec.digest, configuration, snapshot, case_id, self.spec.image_id, str(snapshot_path), str(watchdog_path), str(observer_path), tuple(args))

    def inspect(self, identity: str) -> dict | None:
        result = self.command("inspect", ["container", "inspect", identity])
        if result.completed:
            return self._object(result, array=True)
        if result.state == "completed" and result.exit_code == 1 and result.helper_cleanup:
            listing = self.command("absence", ["container", "ls", "--all", "--no-trunc", "--format", "{{.ID}} {{.Names}}"])
            if listing.completed and listing.helper_cleanup:
                lines = [line.split() for line in listing.stdout.decode("ascii").splitlines()]
                if all(len(line) == 2 and HEX64.fullmatch(line[0]) for line in lines) and not any(identity in line for line in lines):
                    return None
        raise RuntimeRefusal("INSPECTION_UNKNOWN")

    def validate_container(self, value: dict, intent: ResourceIntent, container_id: str | None = None) -> str:
        if intent.owner != self.owner.identity or intent.runtime != self.spec.digest or intent.name != self.owner.name(intent.case_id):
            raise RuntimeRefusal("FOREIGN_RESOURCE_INTENT")
        identity = value.get("Id", "")
        if not HEX64.fullmatch(identity) or (container_id is not None and identity != container_id) or value.get("Name") != "/" + intent.name or value.get("Image") != intent.image_id:
            raise RuntimeRefusal("CONTAINER_IDENTITY")
        config, host = value.get("Config", {}), value.get("HostConfig", {})
        labels = config.get("Labels") or {}
        if labels.get(OWNER_LABEL) != intent.owner or labels.get(CONFIG_LABEL) != intent.configuration:
            raise RuntimeRefusal("FOREIGN_OWNER_OR_CONFIG")
        limit = self.spec.limits
        expected = {"ReadonlyRootfs": True, "Privileged": False, "NetworkMode": "none", "IpcMode": "private", "PidMode": "", "UsernsMode": "", "CgroupnsMode": "private", "NanoCpus": limit.cpu_nanos, "Memory": limit.memory_bytes, "MemorySwap": limit.memory_bytes, "PidsLimit": limit.pids, "ShmSize": limit.shm_bytes, "PublishAllPorts": False}
        if any(host.get(key) != expected_value for key, expected_value in expected.items()):
            raise RuntimeRefusal("CONTAINER_CONSTRAINTS")
        if host.get("CapAdd") or host.get("CapDrop") != ["ALL"] or host.get("SecurityOpt") != ["no-new-privileges:true"] or any(host.get(key) for key in ("Devices", "DeviceRequests", "PortBindings", "Binds", "VolumesFrom", "Links", "ExtraHosts", "GroupAdd", "CgroupParent")):
            raise RuntimeRefusal("CONTAINER_AUTHORITY")
        if host.get("RestartPolicy", {}).get("Name") != "no" or host.get("LogConfig", {}).get("Type") != "none":
            raise RuntimeRefusal("CONTAINER_PERSISTENCE")
        ulimits = {item["Name"]: (item["Soft"], item["Hard"]) for item in host.get("Ulimits", [])}
        if ulimits != {"nofile": (limit.file_descriptors, limit.file_descriptors), "fsize": (limit.file_bytes, limit.file_bytes), "core": (0, 0)}:
            raise RuntimeRefusal("CONTAINER_ULIMIT")
        expected_tmpfs = {"/scratch": f"rw,nosuid,nodev,noexec,size={limit.scratch_bytes},mode=1777", "/tmp": f"rw,nosuid,nodev,noexec,size={limit.tmp_bytes},mode=1777"}
        if host.get("Tmpfs") != expected_tmpfs:
            raise RuntimeRefusal("CONTAINER_DISK_BOUND")
        mounts = value.get("Mounts", [])
        expected_mounts = {"/artifact": intent.snapshot_path, "/watchdog.py": intent.watchdog_path, "/observer.py": intent.observer_path}
        if len(mounts) != len(expected_mounts) or {mount.get("Destination") for mount in mounts} != set(expected_mounts):
            raise RuntimeRefusal("CONTAINER_MOUNTS")
        for mount in mounts:
            if mount.get("Type") != "bind" or mount.get("Source") != expected_mounts.get(mount.get("Destination")) or mount.get("RW") is not False or mount.get("Propagation") != "rprivate":
                raise RuntimeRefusal("CONTAINER_MOUNTS")
        configured_mounts = host.get("Mounts", [])
        if len(configured_mounts) != len(expected_mounts) or {mount.get("Target") for mount in configured_mounts} != set(expected_mounts):
            raise RuntimeRefusal("CONTAINER_MOUNT_CONFIGURATION")
        for mount in configured_mounts:
            options = mount.get("BindOptions", {})
            if mount.get("Type") != "bind" or mount.get("Source") != expected_mounts.get(mount.get("Target")) or mount.get("ReadOnly") is not True or options.get("Propagation") != "rprivate" or options.get("NonRecursive") is not True:
                raise RuntimeRefusal("CONTAINER_MOUNT_CONFIGURATION")
        if config.get("User") != "0:0" or config.get("WorkingDir") != "/" or config.get("Entrypoint") != [self.spec.python_executable] or config.get("Cmd") != ["-I", "-S", "/watchdog.py", str(limit.watchdog_seconds)] or tuple(config.get("Env") or ()) != self.spec.image_environment or config.get("Volumes") or config.get("Tty") or config.get("OpenStdin"):
            raise RuntimeRefusal("CONTAINER_STARTUP")
        return identity

    def cleanup(self, intent: ResourceIntent, container_id: str | None, *, create_uncertain: bool) -> CleanupObservation:
        try:
            if intent.owner != self.owner.identity or intent.runtime != self.spec.digest or intent.name != self.owner.name(intent.case_id):
                raise RuntimeRefusal("FOREIGN_RESOURCE_INTENT")
            value = self.inspect(container_id or intent.name)
            if value is None:
                return CleanupObservation("pending_create" if create_uncertain else "absent", container_id, not create_uncertain, False, create_uncertain)
            identity = self.validate_container(value, intent, container_id)
            self.record(intent.name + ".remove-intent.json", {"container_id": identity, "intent": asdict(intent)})
            result = self.command("remove", ["container", "rm", "--force", identity], seconds=self.spec.limits.cleanup_seconds)
            absent = self.inspect(identity) is None
            if absent and result.completed:
                return CleanupObservation("removed", identity, True, True, False)
            return CleanupObservation("removal_unknown", identity, absent, True, create_uncertain)
        except (ValueError, OSError, KeyError, TypeError):
            return CleanupObservation("ownership_or_cleanup_unknown", container_id, False, False, create_uncertain)

    def reconcile_owned(self, intent: ResourceIntent, container_id: str | None = None) -> CleanupObservation:
        if intent.owner != self.owner.identity or intent.runtime != self.spec.digest or intent.name != self.owner.name(intent.case_id):
            raise RuntimeRefusal("RECOVERY_IDENTITY")
        return self.cleanup(intent, container_id, create_uncertain=container_id is None)

    def read_private_record(self, name: str) -> dict:
        if not re.fullmatch(r"[a-zA-Z0-9_.-]+", name):
            raise RuntimeRefusal("RECEIPT_NAME")
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.directory)
        try:
            info = _reconcile_publication_links(self.directory, name, fd)
            if info.st_size > self.spec.limits.helper_bytes:
                raise RuntimeRefusal("RECOVERY_RECORD_IDENTITY")
            with os.fdopen(fd, "rb", closefd=False) as stream:
                raw = stream.read(self.spec.limits.helper_bytes + 1)
            if len(raw) > self.spec.limits.helper_bytes:
                raise RuntimeRefusal("RECOVERY_RECORD_BOUND")
            value = decode_json_value(raw)
            if not isinstance(value, dict):
                raise RuntimeRefusal("RECOVERY_RECORD_SHAPE")
            return value
        finally:
            os.close(fd)

    def reconcile_all(self, *, maximum_entries: int, maximum_intents: int) -> tuple[CleanupObservation, ...]:
        if maximum_entries <= 0 or maximum_intents <= 0:
            raise RuntimeRefusal("RECOVERY_BOUND")
        names = []
        with os.scandir(self.directory) as entries:
            for count, entry in enumerate(entries, 1):
                if count > maximum_entries:
                    raise RuntimeRefusal("RECOVERY_ENTRY_BOUND")
                if entry.name.endswith(".create-intent.json"):
                    names.append(entry.name)
                    if len(names) > maximum_intents:
                        raise RuntimeRefusal("RECOVERY_INTENT_BOUND")
        outcomes = []
        for name in sorted(names):
            value = self.read_private_record(name)
            if value.get("owner") != self.owner.identity:
                continue
            value["create_argv"] = tuple(value["create_argv"])
            intent = ResourceIntent(**value)
            expected = self.intent(case_id=intent.case_id, snapshot=intent.snapshot, snapshot_path=Path(intent.snapshot_path), watchdog_path=Path(intent.watchdog_path), observer_path=Path(intent.observer_path))
            if name != intent.name + ".create-intent.json" or intent != expected:
                raise RuntimeRefusal("RECOVERY_INTENT_CHANGED")
            container_id = None
            try:
                created = self.read_private_record(intent.name + ".created.json")
            except FileNotFoundError:
                pass
            else:
                if canonical_bytes(created.get("intent")) != canonical_bytes(asdict(intent)) or not HEX64.fullmatch(created.get("container_id", "")):
                    raise RuntimeRefusal("RECOVERY_CREATED_IDENTITY")
                container_id = created["container_id"]
            outcome = self.reconcile_owned(intent, container_id)
            record = {"intent": digest_bytes(canonical_bytes(asdict(intent))), "cleanup": asdict(outcome)}
            self.record(intent.name + ".reconciliation-" + digest_bytes(canonical_bytes(record)) + ".json", record)
            outcomes.append(outcome)
        return tuple(outcomes)

    def run(self, intent: ResourceIntent, argv: tuple[str, ...], stdin: bytes, effects: tuple[tuple[str, int], ...], *, stop_event: Event | None = None) -> SubjectObservation:
        limit = self.spec.limits
        expected_intent = self.intent(case_id=intent.case_id, snapshot=intent.snapshot, snapshot_path=Path(intent.snapshot_path), watchdog_path=Path(intent.watchdog_path), observer_path=Path(intent.observer_path))
        if intent != expected_intent:
            raise RuntimeRefusal("RESOURCE_INTENT_CHANGED")
        if len(stdin) > limit.stdin_bytes or not argv or len(argv) > 128 or sum(len(item.encode("utf-8")) for item in argv) > limit.stdin_bytes or any("\x00" in item for item in argv):
            raise RuntimeRefusal("SUBJECT_INVOCATION_BOUND")
        if limit.watchdog_seconds <= limit.wall_seconds + limit.cleanup_seconds + limit.operation_seconds * (3 + len(effects)):
            raise RuntimeRefusal("WATCHDOG_OPERATION_MARGIN")
        self.operations = []
        container_id = None
        create_uncertain = False
        execution = None
        lease = None
        state = "not_started"
        observed_effects: list[tuple[str, bytes | None]] = []
        cleanup = CleanupObservation("not_created", None, True, False, False)
        try:
            self.record(intent.name + ".create-intent.json", asdict(intent))
            create_uncertain = True
            created = self.command("create", list(intent.create_argv))
            if created.completed:
                candidate_id = created.stdout.decode("ascii").strip()
                if not HEX64.fullmatch(candidate_id):
                    raise RuntimeRefusal("CREATE_RESPONSE_IDENTITY")
                value = self.inspect(candidate_id)
                if value is None:
                    raise RuntimeRefusal("CREATE_NOT_OBSERVED")
                container_id = self.validate_container(value, intent, candidate_id)
                create_uncertain = False
            else:
                value = self.inspect(intent.name)
                if value is not None:
                    container_id = self.validate_container(value, intent)
                    self.record(intent.name + ".created.json", {"container_id": container_id, "intent": asdict(intent)})
                    create_uncertain = False
                state = "create_unknown"
                raise RuntimeRefusal("CREATE_UNKNOWN")
            self.record(intent.name + ".created.json", {"container_id": container_id, "intent": asdict(intent)})
            self.record(intent.name + ".start-intent.json", {"container_id": container_id, "configuration": intent.configuration})
            started = self.command("start", ["container", "start", container_id])
            if not started.completed:
                state = "start_unknown"
            else:
                value = self.inspect(container_id)
                if value is None:
                    raise RuntimeRefusal("START_NOT_OBSERVED")
                self.validate_container(value, intent, container_id)
                if not value.get("State", {}).get("Running"):
                    raise RuntimeRefusal("WATCHDOG_NOT_RUNNING")
                self.record(intent.name + ".tool-intent.json", {"container_id": container_id, "tool_identity": self.spec.tool_identity, "probe_digest": digest_bytes(TOOL_PROBE_SOURCE.encode("utf-8"))})
                probe = self.command("tool", ["exec", "--user", "65532:65532", "--workdir", "/", container_id, self.spec.python_executable, "-I", "-S", "-c", TOOL_PROBE_SOURCE])
                tool = self._object(probe)
                if tool.get("watchdog_secure") is not True or tool.get("subject_secure") is not True or digest_bytes(canonical_bytes(tool.get("tool"))) != self.spec.tool_identity:
                    raise RuntimeRefusal("TOOL_OR_EFFECTIVE_CONTAINMENT_IDENTITY")
                self.record(intent.name + ".exec-intent.json", {"container_id": container_id, "argv": argv, "stdin_sha256": digest_bytes(stdin), "stdin_bytes": len(stdin)})
                lease = CommandLease([str(self.spec.docker_executable), "exec", "--interactive", "--user", "65532:65532", "--workdir", "/scratch", "--env", "HOME=/scratch", "--env", "TMPDIR=/tmp", "--env", "PYTHONDONTWRITEBYTECODE=1", container_id, *argv], self.environment, stdin=stdin, seconds=limit.wall_seconds, stdout_limit=limit.stdout_bytes, stderr_limit=limit.stderr_bytes, stop_event=stop_event)
                execution = lease.observation
                state = execution.state
                if execution.state == "completed" and execution.stdout_complete and execution.stderr_complete:
                    for index, (path, maximum) in enumerate(effects):
                        self.record(intent.name + f".effect-{index}-intent.json", {"container_id": container_id, "path": path, "maximum": maximum})
                        result = self.command("effect", ["exec", "--user", "65532:65532", "--workdir", "/", container_id, self.spec.python_executable, "-I", "-S", "/observer.py", path, str(maximum)])
                        content = None
                        if result.completed:
                            value = self._object(result)
                            encoded = value.get("content")
                            if isinstance(encoded, str) and len(encoded) <= ((maximum + 2) // 3) * 4:
                                content = base64.b64decode(encoded, validate=True)
                                if len(content) > maximum or value.get("size") != len(content):
                                    content = None
                        observed_effects.append((path, content))
        except (ValueError, OSError, KeyError, TypeError):
            if state != "create_unknown":
                state = "runtime_unknown" if create_uncertain or container_id is not None else "not_started"
        finally:
            if create_uncertain or container_id is not None:
                cleanup = self.cleanup(intent, container_id, create_uncertain=create_uncertain)
            if lease is not None:
                execution = lease.close(limit.cleanup_seconds)
                self.operations.append(("exec", execution))
        return SubjectObservation(intent.case_id, state, execution, tuple(observed_effects), cleanup, container_id, digest_bytes(canonical_bytes(asdict(intent))), tuple(self.operations))

