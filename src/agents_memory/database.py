from __future__ import annotations

import re
from dataclasses import dataclass

from .domain import DomainError

POSTGRES_MAJOR = 18
MINIMUM_VECTOR = (0, 8, 7)
_RELEASE = re.compile(r"(\d+)\.(\d+)")
_VECTOR = re.compile(r"(\d+)\.(\d+)\.(\d+)")
INSTALLED_VECTOR_SQL = "SELECT extversion FROM pg_extension WHERE extname='vector'"
# The installed extension, or the version CREATE EXTENSION would install when it is absent.
CANDIDATE_VECTOR_SQL = f"""SELECT COALESCE(
    ({INSTALLED_VECTOR_SQL}),
    (SELECT default_version FROM pg_available_extensions WHERE name='vector'))"""


@dataclass(frozen=True)
class DatabaseVersions:
    postgres: str
    vector: str


def _unsupported() -> DomainError:
    return DomainError(
        "DATABASE_VERSION_UNSUPPORTED",
        f"PostgreSQL {POSTGRES_MAJOR}.x and pgvector >= {'.'.join(map(str, MINIMUM_VECTOR))} are required",
        status=503,
    )


def require_release(release: str | None) -> str:
    """Return a PostgreSQL major.minor release string from this contract, or refuse it."""
    match = _RELEASE.fullmatch(release) if isinstance(release, str) else None
    if release is None or match is None or int(match[1]) != POSTGRES_MAJOR:
        raise _unsupported()
    return release


def require_vector(version: str | None) -> str:
    match = _VECTOR.fullmatch(version) if isinstance(version, str) else None
    if version is None or match is None or tuple(map(int, match.groups())) < MINIMUM_VECTOR:
        raise _unsupported()
    return version


def require_server(server_version_num: str | int, vector: str | None) -> DatabaseVersions:
    """Return a live server's actual versions, or refuse it; serve, migrate and ops share this."""
    try:
        number = int(server_version_num)
    except (TypeError, ValueError):
        raise _unsupported() from None
    release = require_release(f"{number // 10000}.{number % 10000}")
    return DatabaseVersions(release, require_vector(vector))


def require_tool(name: str, identity: bytes) -> str:
    """Return the release of a pg_dump/pg_restore/psql --version line on the same major, or refuse it."""
    match = re.match(re.escape(name).encode() + rb" \(PostgreSQL\) (\d+\.\d+)(?:\s|$)", identity)
    if match is None:
        raise _unsupported()
    return require_release(match[1].decode())
