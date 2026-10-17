from __future__ import annotations

import argparse
import base64
import hashlib
import os
import re
import secrets
import stat
from dataclasses import asdict, fields
from pathlib import Path

from agents_memory.evaluation_artifacts import canonical_bytes, digest_bytes, open_private_directory
from agents_memory.evaluation_runtime import (
    CONFIG_LABEL,
    HEX64,
    OBSERVER_SOURCE,
    OWNER_LABEL,
    TOOL_PROBE_SOURCE,
    WATCHDOG_SOURCE,
    CommandLease,
    DockerRuntime,
    EvaluationOwner,
    ResourceIntent,
    RuntimeLimits,
    RuntimeRefusal,
    RuntimeSpec,
    _reconcile_publication_links,
    publish_or_reconcile,
)
from agents_memory.private_io import private_write
from agents_memory.wire import decode_json_value

IMAGE = "docker.io/library/python@sha256:2ed6491b93cd49272ee6de2b5a38440c3448360322c089fc23e370722d74179d"
MAX_RECORD = 65536
MAX_ENTRIES = 32768
MAX_DIRECTORIES = 1024
MAX_INTENTS = 4096
MAX_DEPTH = 16
MAX_COMMANDS = 256
IMAGE_DIGEST = IMAGE.split("@", 1)[1]
IMAGE_ALIASES = tuple(repository + "@" + IMAGE_DIGEST for repository in ("docker.io/library/python", "library/python", "python", "index.docker.io/library/python"))


def record(directory: int, name: str, value: object) -> None:
    result = publish_or_reconcile(directory, name, canonical_bytes(value))
    if result.state not in {"durable", "reconciled_durable"}:
        raise RuntimeRefusal("PUBLICATION_" + result.state.upper())


def read_record(directory: int, name: str, maximum: int = MAX_RECORD) -> dict:
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+", name):
        raise RuntimeRefusal("RECORD_NAME")
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        before = _reconcile_publication_links(directory, name, fd)
        if before.st_size > maximum:
            raise RuntimeRefusal("RECORD_BOUND")
        raw = bytearray()
        while len(raw) <= maximum:
            block = os.read(fd, min(65536, maximum + 1 - len(raw)))
            if not block:
                break
            raw.extend(block)
        after = os.fstat(fd)
        def identity(item):
            return (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns)
        if len(raw) > maximum or identity(before) != identity(after):
            raise RuntimeRefusal("RECORD_CHANGED_OR_BOUND")
        value = decode_json_value(bytes(raw))
        if not isinstance(value, dict):
            raise RuntimeRefusal("RECORD_SHAPE")
        return value
    finally:
        os.close(fd)


def binary_digest(path: Path) -> str:
    if not path.is_absolute():
        raise RuntimeRefusal("DOCKER_BINARY_PATH")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_mode & 0o022 or not before.st_mode & 0o111 or before.st_size > 256 * 1024 * 1024:
            raise RuntimeRefusal("DOCKER_BINARY_IDENTITY")
        digest = hashlib.sha256()
        size = 0
        while block := os.read(fd, 65536):
            size += len(block)
            if size > 256 * 1024 * 1024:
                raise RuntimeRefusal("DOCKER_BINARY_BOUND")
            digest.update(block)
        after = os.fstat(fd)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise RuntimeRefusal("DOCKER_BINARY_CHANGED")
        return digest.hexdigest()
    finally:
        os.close(fd)


def actual_owner() -> EvaluationOwner:
    owner = EvaluationOwner(os.environ.get("GITHUB_RUN_ID", ""), os.environ.get("GITHUB_RUN_ATTEMPT", ""), os.environ.get("GITHUB_JOB", ""), "runtime-preparation", secrets.token_hex(16))
    owner.require_actions()
    return owner


def state_directory(path: Path) -> int:
    actual_owner()
    temporary = Path(os.environ.get("RUNNER_TEMP", ""))
    if not temporary.is_absolute() or path != temporary / "agents-memory-evaluation":
        raise RuntimeRefusal("STATE_ROOT_IDENTITY")
    return open_private_directory(path)


def runtime_value(spec: RuntimeSpec) -> dict:
    value = asdict(spec)
    for name in ("docker_executable", "docker_config"):
        value[name] = str(value[name])
    return value


def load_runtime(value: dict) -> RuntimeSpec:
    if set(value) != {item.name for item in fields(RuntimeSpec)}:
        raise RuntimeRefusal("SPEC_FIELDS")
    value = dict(value)
    value["docker_executable"] = Path(value["docker_executable"])
    value["docker_config"] = Path(value["docker_config"])
    value["image_environment"] = tuple(value["image_environment"])
    value["limits"] = load_limits(value["limits"])
    return RuntimeSpec(**value)


def load_limits(value: dict) -> RuntimeLimits:
    if not isinstance(value, dict) or set(value) != {item.name for item in fields(RuntimeLimits)}:
        raise RuntimeRefusal("LIMIT_FIELDS")
    limits = RuntimeLimits(**value)
    if limits.helper_bytes > 4 * 1024 * 1024 or limits.operation_seconds > 120 or limits.cleanup_seconds > 120 or limits.wall_seconds > 300 or limits.watchdog_seconds > 1800:
        raise RuntimeRefusal("PREPARATION_LIMIT_BOUND")
    return limits


def directory_identity(directory: int) -> dict:
    info = os.fstat(directory)
    return {"device": info.st_dev, "inode": info.st_ino}


class Preparation:
    def __init__(self, root: Path, directory: int, manifest: dict, journal: int):
        self.root, self.directory, self.manifest, self.journal = root, directory, manifest, journal
        self.owner = EvaluationOwner(**manifest["owner"])
        self.owner.require_actions()
        self.limits = load_limits(manifest["limits"])
        if manifest.get("schema") != 1 or manifest.get("image_reference") != IMAGE or manifest.get("state_root") != str(root) or manifest.get("docker_config") != str(root / "docker-config") or manifest.get("spec_output") != str(root / "runtime-spec.json"):
            raise RuntimeRefusal("PREPARATION_IDENTITY")
        self.binary = Path(manifest["docker_executable"])
        self.config = open_private_directory(root / "docker-config")
        identities = {"state": directory_identity(directory), "config": directory_identity(self.config)}
        if identities != manifest.get("directory_identities"):
            os.close(self.config)
            raise RuntimeRefusal("PREPARATION_DIRECTORY_IDENTITY")
        self.index = 0

    def close(self) -> None:
        os.close(self.config)

    def pin(self) -> None:
        for path, fd in ((self.root, self.directory), (self.root / "docker-config", self.config)):
            current = open_private_directory(path)
            try:
                if (os.fstat(current).st_dev, os.fstat(current).st_ino) != (os.fstat(fd).st_dev, os.fstat(fd).st_ino):
                    raise RuntimeRefusal("DIRECTORY_REPLACED")
            finally:
                os.close(current)
        if binary_digest(self.binary) != self.manifest["docker_sha256"]:
            raise RuntimeRefusal("DOCKER_BINARY_CHANGED")
        endpoint = self.manifest["docker_endpoint"]
        if not isinstance(endpoint, str) or not endpoint.startswith("unix:///") or any(char in endpoint for char in "\r\n\x00"):
            raise RuntimeRefusal("DOCKER_ENDPOINT")
        socket = Path(endpoint[7:])
        if not stat.S_ISSOCK(socket.lstat().st_mode):
            raise RuntimeRefusal("DOCKER_SOCKET_IDENTITY")

    def command(self, stage: str, args: list[str], *, seconds: float | None = None):
        self.pin()
        self.index += 1
        if self.index > MAX_COMMANDS:
            raise RuntimeRefusal("COMMAND_BOUND")
        stem = f"{self.index:04d}-{stage}"
        record(self.journal, stem + ".intent.json", {"owner": self.owner.identity, "argv": args})
        environment = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "DOCKER_CONFIG": self.manifest["docker_config"], "DOCKER_HOST": self.manifest["docker_endpoint"]}
        lease = CommandLease([str(self.binary), *args], environment, stdin=b"", seconds=seconds or self.limits.operation_seconds, stdout_limit=self.limits.helper_bytes, stderr_limit=self.limits.helper_bytes)
        result = lease.close(self.limits.cleanup_seconds)
        record(self.journal, stem + ".observation.json", {**result.public(), "stdout": base64.b64encode(result.stdout).decode("ascii"), "stderr": base64.b64encode(result.stderr).decode("ascii")})
        return result

    def inspect(self, identity: str) -> dict | None:
        result = self.command("inspect", ["container", "inspect", identity])
        if result.completed:
            return DockerRuntime._object(result, array=True)
        if result.state == "completed" and result.exit_code == 1 and result.stdout_complete and result.stderr_complete and result.helper_cleanup:
            listing = self.command("absence", ["container", "ls", "--all", "--no-trunc", "--format", "{{.ID}} {{.Names}}"])
            if listing.completed:
                lines = [line.split() for line in listing.stdout.decode("ascii").splitlines()]
                if len(lines) <= MAX_INTENTS and all(len(line) == 2 and HEX64.fullmatch(line[0]) for line in lines) and not any(identity in line for line in lines):
                    return None
        raise RuntimeRefusal("INSPECTION_UNKNOWN")

    def create_intent(self, measured: dict) -> dict:
        limit = self.limits
        configuration = digest_bytes(canonical_bytes({"manifest": self.manifest, "image": measured, "probe": digest_bytes(TOOL_PROBE_SOURCE.encode())}))
        name = self.owner.name("trusted-image-probe")
        args = ["create", "--pull=never", "--name", name, "--label", f"{OWNER_LABEL}={self.owner.identity}", "--label", f"{CONFIG_LABEL}={configuration}", "--platform", "linux/amd64", "--network", "none", "--ipc", "private", "--cgroupns", "private", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true", "--user", "65532:65532", "--workdir", "/", "--hostname", "evaluation", "--restart", "no", "--no-healthcheck", "--log-driver", "none", "--cpus", str(limit.cpu_nanos / 1_000_000_000), "--memory", str(limit.memory_bytes), "--memory-swap", str(limit.memory_bytes), "--pids-limit", str(limit.pids), "--ulimit", f"nofile={limit.file_descriptors}:{limit.file_descriptors}", "--ulimit", f"fsize={limit.file_bytes}:{limit.file_bytes}", "--ulimit", "core=0:0", "--shm-size", str(limit.shm_bytes), "--entrypoint", "/usr/local/bin/python3", IMAGE, "-I", "-S", "-c", TOOL_PROBE_SOURCE]
        return {"schema": 1, "owner": self.owner.identity, "name": name, "configuration": configuration, "image": measured, "argv": args}

    def validate(self, value: dict, intent: dict, identity: str | None = None) -> str:
        if intent != self.create_intent(intent["image"]):
            raise RuntimeRefusal("PREPARATION_INTENT_CHANGED")
        found = value.get("Id", "")
        if not isinstance(found, str) or not HEX64.fullmatch(found) or identity is not None and identity != found or value.get("Name") != "/" + intent["name"] or value.get("Image") != intent["image"]["image_id"]:
            raise RuntimeRefusal("PROBE_CONTAINER_IDENTITY")
        config, host = value.get("Config", {}), value.get("HostConfig", {})
        if (config.get("Labels") or {}).get(OWNER_LABEL) != self.owner.identity or (config.get("Labels") or {}).get(CONFIG_LABEL) != intent["configuration"]:
            raise RuntimeRefusal("PROBE_OWNER_OR_CONFIG")
        limit = self.limits
        expected = {"ReadonlyRootfs": True, "Privileged": False, "NetworkMode": "none", "IpcMode": "private", "PidMode": "", "UsernsMode": "", "CgroupnsMode": "private", "NanoCpus": limit.cpu_nanos, "Memory": limit.memory_bytes, "MemorySwap": limit.memory_bytes, "PidsLimit": limit.pids, "ShmSize": limit.shm_bytes, "PublishAllPorts": False}
        if any(host.get(key) != expected_value for key, expected_value in expected.items()):
            raise RuntimeRefusal("PROBE_CONSTRAINTS")
        if host.get("CapDrop") != ["ALL"] or host.get("SecurityOpt") != ["no-new-privileges:true"] or any(host.get(key) for key in ("CapAdd", "Devices", "DeviceRequests", "PortBindings", "Binds", "VolumesFrom", "Links", "ExtraHosts", "GroupAdd", "CgroupParent", "Mounts", "Tmpfs")) or value.get("Mounts"):
            raise RuntimeRefusal("PROBE_AUTHORITY")
        ulimits = {item["Name"]: (item["Soft"], item["Hard"]) for item in host.get("Ulimits", [])}
        if ulimits != {"nofile": (limit.file_descriptors, limit.file_descriptors), "fsize": (limit.file_bytes, limit.file_bytes), "core": (0, 0)} or host.get("RestartPolicy", {}).get("Name") != "no" or host.get("LogConfig", {}).get("Type") != "none":
            raise RuntimeRefusal("PROBE_PERSISTENCE_OR_LIMITS")
        if config.get("User") != "65532:65532" or config.get("WorkingDir") != "/" or config.get("Entrypoint") != ["/usr/local/bin/python3"] or config.get("Cmd") != ["-I", "-S", "-c", TOOL_PROBE_SOURCE] or tuple(config.get("Env") or ()) != tuple(intent["image"]["image_environment"]) or config.get("Healthcheck") not in (None, {}, {"Test": ["NONE"]}) or any(config.get(key) for key in ("Volumes", "Tty", "OpenStdin", "OnBuild")):
            raise RuntimeRefusal("PROBE_STARTUP")
        return found

    def cleanup_probe(self) -> dict:
        try:
            intent = read_record(self.directory, "probe-create-intent.json")
        except FileNotFoundError:
            return {"state": "not_created", "complete": True}
        if intent != self.create_intent(intent["image"]):
            raise RuntimeRefusal("PREPARATION_INTENT_CHANGED")
        identity = None
        try:
            created = read_record(self.directory, "probe-created.json")
        except FileNotFoundError:
            pass
        else:
            if created.get("intent") != digest_bytes(canonical_bytes(intent)) or not isinstance(created.get("container_id"), str) or not HEX64.fullmatch(created["container_id"]):
                raise RuntimeRefusal("PROBE_CREATED_IDENTITY")
            identity = created["container_id"]
        value = self.inspect(identity or intent["name"])
        if value is None:
            return {"state": "absent" if identity else "pending_create", "complete": identity is not None}
        identity = self.validate(value, intent, identity)
        record(self.directory, "probe-created.json", {"container_id": identity, "intent": digest_bytes(canonical_bytes(intent))})
        record(self.journal, "remove-intent.json", {"container_id": identity, "intent": digest_bytes(canonical_bytes(intent))})
        removed = self.command("remove", ["container", "rm", "--force", identity], seconds=self.limits.cleanup_seconds)
        absent = self.inspect(identity) is None
        outcome = {"state": "removed" if removed.completed and absent else "removal_unknown", "complete": removed.completed and absent}
        record(self.journal, "probe-cleanup.json", outcome)
        return outcome


def prepare(args: argparse.Namespace) -> dict:
    root = args.state_root
    directory = state_directory(root)
    preparation = None
    journal = -1
    try:
        if args.image_reference != IMAGE or args.docker_config != root / "docker-config" or args.limits_file != root / "limits.json" or args.spec_output != root / "runtime-spec.json":
            raise RuntimeRefusal("PREPARATION_INPUT_IDENTITY")
        limits = load_limits(read_record(directory, "limits.json"))
        owner = actual_owner()
        config_fd = open_private_directory(args.docker_config)
        try:
            identities = {"state": directory_identity(directory), "config": directory_identity(config_fd)}
        finally:
            os.close(config_fd)
        manifest = {"schema": 1, "owner": asdict(owner), "state_root": str(root), "docker_executable": str(args.docker_binary), "docker_sha256": binary_digest(args.docker_binary), "docker_endpoint": args.docker_endpoint, "docker_config": str(args.docker_config), "image_reference": IMAGE, "limits": asdict(limits), "spec_output": str(args.spec_output)}
        manifest["directory_identities"] = identities
        private_write(Path("preparation.json"), canonical_bytes(manifest), directory=directory)
        os.mkdir("prepare-operations", 0o700, dir_fd=directory)
        os.fsync(directory)
        journal = open_private_directory(root / "prepare-operations")
        preparation = Preparation(root, directory, manifest, journal)
        engine = DockerRuntime._object(preparation.command("engine", ["info", "--format", "{{json .}}"]))
        if engine.get("OSType") != "linux" or engine.get("Architecture") not in {"amd64", "x86_64"} or not any(isinstance(item, str) and "seccomp" in item for item in engine.get("SecurityOptions", [])):
            raise RuntimeRefusal("ENGINE_CONTAINMENT_UNAVAILABLE")
        image = DockerRuntime._object(preparation.command("image", ["image", "inspect", IMAGE]), array=True)
        config = image.get("Config")
        references = [reference for reference in IMAGE_ALIASES if reference in image.get("RepoDigests", [])]
        if not isinstance(config, dict) or image.get("Os") != "linux" or image.get("Architecture") != "amd64" or not references or not isinstance(image.get("Id"), str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", image["Id"]):
            raise RuntimeRefusal("IMAGE_IDENTITY")
        if any(config.get(key) for key in ("Volumes", "OnBuild", "Healthcheck", "Entrypoint")) or config.get("User") not in {"", "0", "0:0", "root"} or not all(isinstance(item, str) for item in config.get("Env") or []):
            raise RuntimeRefusal("IMAGE_STARTUP_DENIED")
        measured = {"image_reference": references[0], "image_id": image["Id"], "image_config_digest": digest_bytes(canonical_bytes(config)), "image_environment": config.get("Env") or []}
        record(directory, "image-measured.json", measured)
        intent = preparation.create_intent(measured)
        record(directory, "probe-create-intent.json", intent)
        created = preparation.command("create", intent["argv"])
        candidate = created.stdout.decode("ascii").strip() if created.completed else None
        if candidate is not None and not HEX64.fullmatch(candidate):
            raise RuntimeRefusal("CREATE_RESPONSE_IDENTITY")
        inspected = preparation.inspect(candidate or intent["name"])
        if inspected is None:
            raise RuntimeRefusal("CREATE_UNKNOWN")
        identity = preparation.validate(inspected, intent, candidate)
        record(directory, "probe-created.json", {"container_id": identity, "intent": digest_bytes(canonical_bytes(intent))})
        if not created.completed:
            raise RuntimeRefusal("CREATE_UNKNOWN")
        record(directory, "probe-start-intent.json", {"container_id": identity, "configuration": intent["configuration"]})
        probe = DockerRuntime._object(preparation.command("start", ["container", "start", "--attach", identity]))
        tool = probe.get("tool")
        if probe.get("subject_secure") is not True or probe.get("watchdog_secure") is not False or not isinstance(tool, dict) or set(tool) != {"executable", "sha256", "version", "implementation", "machine"} or not isinstance(tool.get("sha256"), str) or not HEX64.fullmatch(tool["sha256"]) or tool.get("machine") != "x86_64" or tool.get("implementation") != "CPython" or not isinstance(tool.get("version"), str) or not isinstance(tool.get("executable"), str) or not tool["executable"].startswith("/usr/local/bin/python"):
            raise RuntimeRefusal("TRUSTED_TOOL_IDENTITY")
        record(directory, "tool-measured.json", probe)
        cleanup = preparation.cleanup_probe()
        if not cleanup["complete"]:
            raise RuntimeRefusal("PREPARATION_CLEANUP_INCOMPLETE")
        spec = RuntimeSpec(args.docker_binary, manifest["docker_sha256"], args.docker_config, args.docker_endpoint, measured["image_reference"], measured["image_id"], measured["image_config_digest"], tuple(measured["image_environment"]), "/usr/local/bin/python3", digest_bytes(canonical_bytes(tool)), digest_bytes(WATCHDOG_SOURCE), digest_bytes(OBSERVER_SOURCE), limits)
        record(directory, "runtime-spec.json", runtime_value(spec))
        summary = {"schema": 1, "stage": "prepare", "code": "READY", "complete": True, "runtime_digest": spec.digest, "image_config_digest": spec.image_config_digest, "tool_digest": spec.tool_identity, "cleanup_complete": True}
        record(directory, "preparation-summary.json", summary)
        return summary
    except Exception as error:
        if preparation is not None:
            record(directory, "preparation-failure.json", {"schema": 1, "stage": "prepare", "type": type(error).__name__, "code": "PREPARATION_INCOMPLETE"})
        raise
    finally:
        if preparation is not None:
            preparation.close()
        if journal >= 0:
            os.close(journal)
        os.close(directory)


def verifier_inventory(root: Path) -> list[tuple[Path, dict]]:
    found = []
    count = 0
    directories = 0

    def visit(path: Path, depth: int) -> None:
        nonlocal count, directories
        directories += 1
        if depth > MAX_DEPTH or directories > MAX_DIRECTORIES:
            raise RuntimeRefusal("INVENTORY_DIRECTORY_BOUND")
        fd = open_private_directory(path)
        try:
            children = []
            local_owners = set()
            local_intents = []
            with os.scandir(fd) as entries:
                for entry in entries:
                    count += 1
                    if count > MAX_ENTRIES:
                        raise RuntimeRefusal("INVENTORY_ENTRY_BOUND")
                    info = entry.stat(follow_symlinks=False)
                    if entry.name.endswith(".owner.json"):
                        owner = read_record(fd, entry.name)
                        if entry.name != EvaluationOwner(**owner["owner"]).identity + ".owner.json" or owner.get("schema") != 1:
                            raise RuntimeRefusal("INVENTORY_OWNER_IDENTITY")
                        found.append((path, owner))
                        local_owners.add(EvaluationOwner(**owner["owner"]).identity)
                        if len(found) > MAX_INTENTS:
                            raise RuntimeRefusal("INVENTORY_OWNER_BOUND")
                    elif entry.name.endswith(".create-intent.json"):
                        intent = read_record(fd, entry.name, 4 * 1024 * 1024)
                        local_intents.append(intent)
                        if len(local_intents) > MAX_INTENTS:
                            raise RuntimeRefusal("INVENTORY_INTENT_BOUND")
                    elif stat.S_ISDIR(info.st_mode):
                        if entry.name.endswith(".snapshot"):
                            snapshot = read_record(fd, entry.name.removesuffix(".snapshot") + ".snapshot-intent.json")
                            if snapshot.get("path") != str(path / entry.name) or not isinstance(snapshot.get("digest"), str) or not HEX64.fullmatch(snapshot["digest"]):
                                raise RuntimeRefusal("INVENTORY_SNAPSHOT_IDENTITY")
                        else:
                            children.append(path / entry.name)
                    elif not stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode):
                        raise RuntimeRefusal("INVENTORY_FILE_KIND")
            for intent in local_intents:
                if intent.get("owner") not in local_owners:
                    raise RuntimeRefusal("INVENTORY_MISSING_OWNER")
                for field in ("snapshot_path", "watchdog_path", "observer_path"):
                    source = Path(intent[field])
                    if source.parent != path or source.name in {"", ".", ".."}:
                        raise RuntimeRefusal("INVENTORY_MOUNT_SCOPE")
            for child in sorted(children):
                visit(child, depth + 1)
        finally:
            os.close(fd)
    visit(root, 0)
    return found


def recover_known_start_ids(runtime: DockerRuntime) -> None:
    names = []
    with os.scandir(runtime.directory) as entries:
        for count, entry in enumerate(entries, 1):
            if count > MAX_ENTRIES:
                raise RuntimeRefusal("RECOVERY_ENTRY_BOUND")
            if entry.name.endswith(".create-intent.json"):
                names.append(entry.name)
                if len(names) > MAX_INTENTS:
                    raise RuntimeRefusal("RECOVERY_INTENT_BOUND")
    for name in sorted(names):
        value = runtime.read_private_record(name)
        if value.get("owner") != runtime.owner.identity:
            continue
        value["create_argv"] = tuple(value["create_argv"])
        intent = ResourceIntent(**value)
        expected = runtime.intent(case_id=intent.case_id, snapshot=intent.snapshot, snapshot_path=Path(intent.snapshot_path), watchdog_path=Path(intent.watchdog_path), observer_path=Path(intent.observer_path))
        if intent != expected or name != intent.name + ".create-intent.json":
            raise RuntimeRefusal("RECOVERY_INTENT_CHANGED")
        try:
            runtime.read_private_record(intent.name + ".created.json")
        except FileNotFoundError:
            try:
                started = runtime.read_private_record(intent.name + ".start-intent.json")
            except FileNotFoundError:
                continue
            identity = started.get("container_id")
            if not isinstance(identity, str) or not HEX64.fullmatch(identity) or set(started) not in ({"container_id"}, {"container_id", "configuration"}) or started.get("configuration", intent.configuration) != intent.configuration:
                raise RuntimeRefusal("RECOVERY_START_IDENTITY")
            runtime.record(intent.name + ".start-id-recovery.json", {"source": digest_bytes(canonical_bytes(started)), "intent": digest_bytes(canonical_bytes(asdict(intent))), "container_id": identity})
            runtime.record(intent.name + ".created.json", {"container_id": identity, "intent": asdict(intent)})


def cleanup(args: argparse.Namespace) -> dict:
    directory = state_directory(args.state_root)
    journal = -1
    preparation = None
    try:
        if args.spec_file != args.state_root / "runtime-spec.json":
            raise RuntimeRefusal("SPEC_PATH_IDENTITY")
        manifest = read_record(directory, "preparation.json")
        name = "cleanup-" + secrets.token_hex(16)
        os.mkdir(name, 0o700, dir_fd=directory)
        os.fsync(directory)
        journal = open_private_directory(args.state_root / name)
        preparation = Preparation(args.state_root, directory, manifest, journal)
        probe = preparation.cleanup_probe()
        complete = probe["complete"]
        try:
            spec = load_runtime(read_record(directory, "runtime-spec.json"))
        except FileNotFoundError:
            spec = None
        if spec is not None:
            measured = read_record(directory, "image-measured.json")
            probe_tool = read_record(directory, "tool-measured.json")
            if spec.image_reference != measured["image_reference"] or spec.image_id != measured["image_id"] or spec.image_config_digest != measured["image_config_digest"] or spec.image_environment != tuple(measured["image_environment"]) or spec.tool_identity != digest_bytes(canonical_bytes(probe_tool["tool"])):
                raise RuntimeRefusal("SPEC_MEASUREMENT_MISMATCH")
        inventory = verifier_inventory(args.state_root / "verifier")
        resources = 0
        owners = 0
        for path, owner_record in inventory:
            if spec is None:
                raise RuntimeRefusal("VERIFIER_RUNTIME_MISSING")
            owner = EvaluationOwner(**owner_record["owner"])
            owner.require_actions()
            if owner_record.get("runtime") != spec.digest:
                raise RuntimeRefusal("VERIFIER_RUNTIME_MISMATCH")
            if str(spec.docker_executable) != manifest["docker_executable"] or spec.docker_sha256 != manifest["docker_sha256"] or str(spec.docker_config) != manifest["docker_config"] or spec.docker_endpoint != manifest["docker_endpoint"] or spec.image_reference not in IMAGE_ALIASES or asdict(spec.limits) != manifest["limits"]:
                raise RuntimeRefusal("SPEC_MANIFEST_MISMATCH")
            runtime = DockerRuntime(spec, owner, path)
            try:
                preparation.pin()
                runtime.preflight()
                recover_known_start_ids(runtime)
                outcomes = runtime.reconcile_all(maximum_entries=MAX_ENTRIES, maximum_intents=MAX_INTENTS)
                resources += len(outcomes)
                complete = complete and all(item.exact_absence and not item.pending_create and item.state in {"removed", "absent"} for item in outcomes)
                owners += 1
                record(journal, f"verifier-{owners:04d}.json", {"owner_digest": owner.identity, "outcomes": [asdict(item) for item in outcomes]})
            finally:
                runtime.close()
        summary = {"schema": 1, "stage": "cleanup", "code": "CLEAN" if complete else "CLEANUP_INCOMPLETE", "complete": complete, "cleanup_complete": complete, "owners": owners, "resources": resources, "probe_cleanup": probe["state"]}
        record(journal, "summary.json", summary)
        return summary
    finally:
        if preparation is not None:
            preparation.close()
        if journal >= 0:
            os.close(journal)
        os.close(directory)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare and reconcile the owned Actions-only evaluation runtime")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare")
    prepare_parser.add_argument("--image-reference", required=True)
    for name in ("docker-binary", "docker-config", "state-root", "limits-file", "spec-output"):
        prepare_parser.add_argument("--" + name, type=Path, required=True)
    prepare_parser.add_argument("--docker-endpoint", required=True)
    cleanup_parser = commands.add_parser("cleanup")
    cleanup_parser.add_argument("--state-root", type=Path, required=True)
    cleanup_parser.add_argument("--spec-file", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        summary = prepare(args) if args.command == "prepare" else cleanup(args)
    except Exception as error:
        summary = {"schema": 1, "stage": args.command, "code": "RUNTIME_PREPARATION_FAILED", "type": type(error).__name__, "complete": False, "cleanup_complete": False}
    print(canonical_bytes(summary).decode("utf-8"))
    return 0 if summary["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
