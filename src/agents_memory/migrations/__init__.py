from __future__ import annotations

import asyncio
import re
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from ..database import CANDIDATE_VECTOR_SQL, INSTALLED_VECTOR_SQL, require_server

MIGRATIONS = ("0001_authority", "0002_directional_tombstones", "0003_origin_and_vector_compat", "0004_operation_successors", "0005_company_selection", "0006_agent_judged", "0007_memory_health", "0008_judge_escalations")
MIGRATION = MIGRATIONS[-1]


def _arguments(dsn: str) -> tuple[str, dict]:
    parts = urlsplit(dsn)
    query = dict(parse_qsl(parts.query))
    schema = query.pop("schema", None)
    options = {"passfile": "/dev/null"}
    host = unquote(parts.netloc.rsplit("@", 1)[-1].split(":", 1)[0])
    if host.startswith("/"):
        options["host"] = host
    if schema is not None:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema):
            raise ValueError("Invalid schema name")
        options["server_settings"] = {"search_path": f'"{schema}"'}
    url = urlunsplit(("postgresql+asyncpg", parts.netloc, parts.path, urlencode(query), parts.fragment))
    return url, options


async def _migrate(dsn: str) -> dict:
    url, options = _arguments(dsn)
    engine = create_async_engine(url, connect_args=options)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(current_database() || :migration_tag, 0))"),
                {"migration_tag": ":agent-memory-explicit-migration"},
            )
            version = int((await connection.execute(text("SHOW server_version_num"))).scalar_one())
            # Validate the existing or to-be-created extension version before any DDL.
            require_server(version, (await connection.execute(text(CANDIDATE_VECTOR_SQL))).scalar_one())
            await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public"))
            vector = (await connection.execute(text(INSTALLED_VECTOR_SQL))).scalar_one()
            require_server(version, vector)
            configuration = Config()
            configuration.set_main_option("script_location", str(Path(__file__).parent))
            def upgrade(sync_connection) -> None:
                configuration.attributes["connection"] = sync_connection
                command.upgrade(configuration, "head")
            await connection.run_sync(upgrade)
            migration = (await connection.execute(text("SELECT version_num FROM alembic_version"))).scalar_one()
            return {"migration": migration, "postgresql_version": version, "vector_version": vector}
    finally:
        await engine.dispose()


def migrate(dsn: str) -> dict:
    return asyncio.run(_migrate(dsn))


def restore_preparation_sql(archived_revision: str, schema: str) -> str:
    """Prepare dependencies inside the executor's uncommitted restore transaction.

    pg_restore --clean replaces every archived table, including its newer columns.
    Newer cross-table foreign keys and tables absent from the archive must be
    removed first. This function never opens or changes a database.
    """
    if archived_revision not in MIGRATIONS:
        raise ValueError("Unsupported archived authority migration")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema):
        raise ValueError("Invalid schema name")
    statements = [
        f'SET LOCAL search_path = "{schema}", public',
        "SELECT pg_advisory_xact_lock(hashtextextended(current_database() || ':agent-memory-explicit-migration', 0))",
        "DO $$ BEGIN IF (SELECT version_num FROM alembic_version) IS DISTINCT FROM "
        f"'{MIGRATION}' THEN RAISE EXCEPTION 'Unsupported current authority migration'; END IF; END $$",
    ]
    archived_index = MIGRATIONS.index(archived_revision)
    if archived_index < 7:
        statements.append("DROP TABLE am_judge_escalations")
    if archived_index < 6:
        statements.extend([
            "DROP TABLE am_code_links",
            "DROP TABLE am_health_events",
            "DROP TABLE am_session_observations",
            "DROP TABLE am_claim_health",
            "DROP TABLE am_code_observations",
            "DROP TABLE am_code_workspaces",
            "DROP TABLE am_health_policies",
        ])
    if archived_index < 5:
        statements.extend([
            "ALTER TABLE am_claims DROP COLUMN cleanup_sequence",
            "ALTER TABLE am_clock DROP COLUMN cleanup_progress",
            "DROP INDEX am_rejection_history_selection",
            "DROP INDEX am_rejection_history_feedback",
            "DROP INDEX am_feedback_reason_source",
            "DROP TABLE am_rejection_tokens",
            "DROP TABLE am_rejection_evidence",
            "ALTER TABLE am_relations DROP CONSTRAINT am_relations_judgment_id_fkey",
            "ALTER TABLE am_admissions DROP COLUMN pending_id",
            "DROP TABLE am_claim_judgments",
            "DROP TABLE am_retired_jobs",
            "DROP TABLE am_pending_judgments",
        ])
    if archived_index < 4:
        statements.extend([
            "ALTER TABLE am_claims DROP CONSTRAINT am_claims_selection_id_fkey",
            "DROP TABLE am_selection_sources",
            "DROP TABLE am_source_selections",
            "DROP TABLE am_selection_policies",
        ])
    if archived_index < 3:
        statements.append("ALTER TABLE am_operations DROP CONSTRAINT am_operations_successor_operation_id_fkey")
    if archived_index < 2:
        statements.append("DROP TABLE am_origin_reservations")
        statements.append("ALTER TABLE am_claims DROP CONSTRAINT am_claims_extraction_operation_id_fkey")
        statements.append("ALTER TABLE am_claims DROP CONSTRAINT am_claims_superseded_by_fkey")
    if archived_index < 1:
        statements.append("DROP TABLE am_relation_claims")
    return ";\n".join(statements) + ";\n"
