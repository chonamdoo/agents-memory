from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import secrets
import shutil
import stat
import subprocess
import tarfile
import time
import urllib.request
from pathlib import Path

PYTHON = "3.13.16"
IMAGE = "pgvector/pgvector@sha256:ad249f9fb9572979643a47694e59b9a8cdcdf6abc6accebf49bb80ad5f20ff9b"
AGE_URL = "https://github.com/FiloSottile/age/releases/download/v1.3.2/age-v1.3.2-linux-amd64.tar.gz"
AGE_SHA256 = "cbe24006683f8eb669266162894b9a522a1af52f2665fbc63a4bb032ed26ac10"
PGDG_FINGERPRINT = "B97B0AFCAA1A47F044F244A07FCC7D46ACCC4CF8"
LABEL = "org.agents-memory.ci-owner"
ROOT = Path(__file__).resolve().parents[2]


def run(command: list[str], *, env: dict | None = None, timeout: float = 300) -> str:
    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"Prerequisite command failed: {Path(command[0]).name} (exit {result.returncode})")
    return result.stdout.strip()


def save(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")
    temporary.replace(path)


def state_path(value: Path) -> Path:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("Runtime preparation and cleanup are GitHub Actions-only")
    if platform.system() != "Linux" or platform.machine() not in {"x86_64", "AMD64"}:
        raise RuntimeError("This pinned runtime requires a Linux amd64 Actions runner")
    root = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
    expected = root / "agents-memory-ci"
    if not value.is_absolute() or value != expected or value.is_symlink():
        raise RuntimeError("The state directory must be the explicit run-owned RUNNER_TEMP child")
    if value.exists():
        info = value.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise RuntimeError("CI state is not an owned private directory")
    return expected


def job_identity() -> str:
    values = [os.environ.get(key, "") for key in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB")]
    if not all(values):
        raise RuntimeError("An actual Actions run, attempt and job identity are required")
    return ":".join(values)


def download(url: str, destination: Path, *, maximum: int = 64 * 1024 * 1024) -> None:
    with urllib.request.urlopen(url, timeout=60) as response, destination.open("xb") as stream:
        total = 0
        while block := response.read(1024 * 1024):
            total += len(block)
            if total > maximum:
                raise RuntimeError("The pinned prerequisite download exceeded its limit")
            stream.write(block)


def export(values: dict[str, str]) -> None:
    with Path(os.environ["GITHUB_ENV"]).open("a", encoding="utf-8") as stream:
        for key, value in values.items():
            if "\n" in value or "\r" in value:
                raise RuntimeError("CI environment values must be single-line")
            stream.write(f"{key}={value}\n")


def python_runtime(state: Path) -> tuple[dict[str, str], dict]:
    values = {
        "UV_PYTHON_INSTALL_DIR": str(state / "python"),
        "UV_PYTHON_BIN_DIR": str(state / "bin"),
        "UV_PROJECT_ENVIRONMENT": str(state / "venv"),
    }
    env = os.environ | values
    subprocess.run(["uv", "python", "install", "--managed-python", PYTHON],
                   env=env, check=True, timeout=300)
    binary = Path(run(["uv", "python", "find", "--managed-python", PYTHON], env=env)).resolve(strict=True)
    if not binary.is_relative_to(state / "python"):
        raise RuntimeError("uv did not select the owned managed Python")
    observed = json.loads(run([str(binary), "-I", "-c",
        "import json,sqlite3,sys; print(json.dumps({'python':list(sys.version_info[:3]),"
        "'sqlite':list(sqlite3.sqlite_version_info)}))"]))
    if observed["python"] != [3, 13, 16] or tuple(observed["sqlite"]) < (3, 51, 3):
        raise RuntimeError("The actual managed Python/SQLite does not meet the pinned patched runtime")
    node = run(["node", "--version"])
    if int(node.removeprefix("v").split(".")[0]) < 24:
        raise RuntimeError("Node24 or newer is required for host regressions")
    values["UV_PYTHON"] = str(binary)
    return values, {"python": observed["python"], "sqlite": observed["sqlite"],
                    "node": node, "uv": run(["uv", "--version"])}


def age_runtime(state: Path) -> tuple[Path, Path]:
    archive = state / "age.tar.gz"
    download(AGE_URL, archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != AGE_SHA256:
        raise RuntimeError("The official age archive checksum does not match its pinned release")
    directory = state / "age"
    directory.mkdir(mode=0o700)
    with tarfile.open(archive, "r:gz") as bundle:
        for name in ("age", "age-keygen"):
            member = bundle.getmember(f"age/{name}")
            if not member.isfile():
                raise RuntimeError("The age archive did not contain the expected regular binary")
            source = bundle.extractfile(member)
            if source is None:
                raise RuntimeError("The age binary cannot be read")
            with source, (directory / name).open("xb") as target:
                shutil.copyfileobj(source, target)
            (directory / name).chmod(0o700)
    return directory / "age", directory / "age-keygen"


def postgres_tools(state: Path) -> dict[str, Path]:
    key = state / "pgdg.asc"
    download("https://www.postgresql.org/media/keys/ACCC4CF8.asc", key, maximum=1024 * 1024)
    fingerprints = run(["gpg", "--batch", "--show-keys", "--with-colons", str(key)])
    if not any(line.split(":")[9] == PGDG_FINGERPRINT
               for line in fingerprints.splitlines() if line.startswith("fpr:")):
        raise RuntimeError("The official PGDG signing key fingerprint did not match")
    key_target = "/usr/share/keyrings/agents-memory-ci.asc"
    source = state / "pgdg.sources"
    source.write_text("Types: deb\nURIs: https://apt.postgresql.org/pub/repos/apt\n"
                      "Suites: noble-pgdg\nArchitectures: amd64\nComponents: main\n"
                      f"Signed-By: {key_target}\n", encoding="utf-8")
    run(["sudo", "install", "-m", "644", str(key), key_target])
    run(["sudo", "install", "-m", "644", str(source), "/etc/apt/sources.list.d/agents-memory-ci.sources"])
    run(["sudo", "apt-get", "update"])
    run(["sudo", "apt-get", "install", "-y", "--no-install-recommends", "postgresql-client-18"])
    return {name: Path("/usr/lib/postgresql/18/bin") / name for name in ("pg_dump", "pg_restore", "psql")}


def postgres_runtime(state: Path, manifest: dict) -> tuple[dict[str, str], dict]:
    age, keygen = age_runtime(state)
    tools = postgres_tools(state)
    versions = {name: run([str(path), "--version"]) for name, path in tools.items()}
    if any(" 18." not in version for version in versions.values()):
        raise RuntimeError("Native PostgreSQL client tools must be major18")
    nonce = manifest["owner"].rsplit(":", 1)[1]
    container, volume = f"am-ci-{nonce}", f"am-ci-{nonce}-data"
    manifest.update(container=container, volume=volume)
    save(state / "manifest.json", manifest)
    run(["docker", "volume", "create", "--label", f"{LABEL}={manifest['owner']}", volume])
    password = secrets.token_hex(24)
    print(f"::add-mask::{password}", flush=True)
    env = os.environ | {"POSTGRES_PASSWORD": password}
    run(["docker", "run", "--detach", "--name", container,
         "--label", f"{LABEL}={manifest['owner']}", "--publish", "127.0.0.1::5432",
         "--env", "POSTGRES_PASSWORD", "--env", "POSTGRES_DB=agents_memory",
         "--mount", f"type=volume,src={volume},dst=/var/lib/postgresql", IMAGE], env=env)
    document = json.loads(run(["docker", "inspect", container]))[0]
    bindings = document["NetworkSettings"]["Ports"]["5432/tcp"]
    if len(bindings) != 1 or bindings[0]["HostIp"] != "127.0.0.1":
        raise RuntimeError("The owned database must publish exclusively on loopback")
    port = bindings[0]["HostPort"]
    pg_env = os.environ | {"PGPASSWORD": password, "PGHOST": "127.0.0.1", "PGPORT": port,
                           "PGUSER": "postgres", "PGDATABASE": "agents_memory", "PGCONNECT_TIMEOUT": "2"}
    psql = [str(tools["psql"]), "--no-psqlrc", "--set", "ON_ERROR_STOP=1", "--tuples-only", "--no-align"]
    deadline = time.monotonic() + 90
    while True:
        try:
            run([*psql, "--command", "SELECT 1"], env=pg_env, timeout=3)
            break
        except (RuntimeError, subprocess.TimeoutExpired):
            if time.monotonic() >= deadline:
                raise RuntimeError("The owned PostgreSQL did not become ready within90 seconds") from None
            time.sleep(0.5)
    run([*psql, "--command", "CREATE EXTENSION IF NOT EXISTS vector"], env=pg_env)
    server = json.loads(run([*psql, "--command",
        "SELECT json_build_object('server',current_setting('server_version'),"
        "'vector',(SELECT extversion FROM pg_extension WHERE extname='vector'))"], env=pg_env))
    if not server["server"].startswith("18.") or tuple(map(int, server["vector"].split("."))) < (0, 8, 7):
        raise RuntimeError("The actual PostgreSQL/vector versions do not meet the product contract")
    dsn = f"postgresql://postgres:{password}@127.0.0.1:{port}/agents_memory"
    print(f"::add-mask::{dsn}", flush=True)
    values = {
        "PG_TEST_DSN": dsn,
        "OPS_TEST_RUNTIME": json.dumps({"mode": "local", "age_binary": str(age),
            "pg_dump_binary": str(tools["pg_dump"]), "pg_restore_binary": str(tools["pg_restore"]),
            "psql_binary": str(tools["psql"])}),
        "AGE_KEYGEN_TEST_BINARY": str(keygen),
    }
    return values, {"postgres": server, "postgres_clients": versions, "postgres_image": IMAGE,
                    "operations_mode": "local", "age": run([str(age), "--version"]),
                    "age_keygen": run([str(keygen), "--version"]), "age_archive_sha256": AGE_SHA256}


def prepare(state: Path, postgres: bool) -> None:
    state.mkdir(mode=0o700)
    manifest = {"schema": 1, "job": job_identity(), "owner": job_identity() + ":" + secrets.token_hex(12),
                "container": None, "volume": None}
    save(state / "manifest.json", manifest)
    values, observed = python_runtime(state)
    if postgres:
        pg_values, pg_observed = postgres_runtime(state, manifest)
        values.update(pg_values)
        observed.update(pg_observed)
    export(values)
    result_dir = ROOT / ".ci-results"
    result_dir.mkdir(exist_ok=True)
    save(result_dir / "prerequisites.json", {"schema": 1, "complete": True,
         "tested_sha": os.environ["CI_TESTED_SHA"], "postgres_enabled": postgres, "observed": observed})


def cleanup(state: Path) -> None:
    if not state.exists():
        return
    path = state / "manifest.json"
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError("The ownership manifest is not a private owned regular file")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema") != 1 or manifest.get("job") != job_identity():
        raise RuntimeError("Cleanup refused a different job's runtime")
    owner = manifest["owner"]
    for kind in ("container", "volume"):
        name = manifest.get(kind)
        if name is None:
            continue
        expected = "am-ci-" + owner.rsplit(":", 1)[1] + ("-data" if kind == "volume" else "")
        if name != expected:
            raise RuntimeError("Cleanup refused an unexpected resource name")
        listed = run(["docker", kind, "ls", *(["--all"] if kind == "container" else []),
                      "--filter", f"name=^{name}$", "--format", "{{.Names}}" if kind == "container" else "{{.Name}}"])
        if name not in listed.splitlines():
            continue
        document = json.loads(run(["docker", kind, "inspect", name]))[0]
        labels = document.get("Labels") if kind == "volume" else document["Config"].get("Labels")
        if not isinstance(labels, dict) or labels.get(LABEL) != owner:
            raise RuntimeError("Cleanup refused a resource without the exact owned label")
        run(["docker", kind, "rm", *(["--force"] if kind == "container" else []), name])
    shutil.rmtree(state)


def main() -> int:
    parser = argparse.ArgumentParser(description="Provision or clean exclusively run-owned Actions prerequisites")
    parser.add_argument("action", choices=("prepare", "cleanup"))
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--postgres", action="store_true")
    args = parser.parse_args()
    try:
        state = state_path(args.state_dir)
        if args.action == "prepare":
            prepare(state, args.postgres)
        else:
            cleanup(state)
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        reason = str(error) if type(error) is RuntimeError else type(error).__name__
        print(f"CI prerequisite {args.action} failed: {reason}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
