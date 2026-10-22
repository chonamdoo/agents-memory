from alembic import op

revision = '0008_judge_escalations'
down_revision = '0007_memory_health'
branch_labels = None
depends_on = None

DDL = (
    "ALTER TABLE am_pending_judgments ADD COLUMN escalation_generation bigint NOT NULL DEFAULT 0",
    "ALTER TABLE am_pending_judgments ADD COLUMN manifest_digest text",
    """CREATE TABLE am_judge_escalations (
        pending_id text NOT NULL REFERENCES am_pending_judgments(id),
        binding_id text NOT NULL REFERENCES am_bindings(id),
        binding_revision bigint NOT NULL,
        scope text NOT NULL CHECK(scope IN ('item','window','health')),
        source_id text, source_revision bigint, byte_start bigint, byte_end bigint,
        window_digest text, manifest_digest text, health_revision bigint, health_policy_revision bigint,
        reason text NOT NULL CHECK(reason ~ '^[a-z0-9_]{1,64}$'),
        credential_id text NOT NULL REFERENCES am_credentials(id),
        provider text NOT NULL CHECK(provider ~ '^[a-z]{1,32}$'),
        provider_revision bigint NOT NULL CHECK(provider_revision>=0),
        escalated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        CHECK((source_id IS NULL) = (source_revision IS NULL)),
        CHECK(byte_end>=byte_start),
        CHECK(CASE scope
            WHEN 'window' THEN source_id IS NOT NULL AND byte_start IS NOT NULL AND byte_end IS NOT NULL
                AND window_digest IS NOT NULL AND manifest_digest IS NULL
                AND health_revision IS NULL AND health_policy_revision IS NULL
            WHEN 'health' THEN health_revision IS NOT NULL AND health_policy_revision IS NOT NULL
                AND source_id IS NULL AND byte_start IS NULL AND byte_end IS NULL
                AND window_digest IS NULL AND manifest_digest IS NULL
            ELSE byte_start IS NULL AND byte_end IS NULL AND window_digest IS NULL
                AND health_revision IS NULL AND health_policy_revision IS NULL END),
        CONSTRAINT am_judge_escalation_key UNIQUE NULLS NOT DISTINCT (pending_id,scope,source_id,byte_start,byte_end))""",
    "CREATE INDEX am_judge_escalation_owner ON am_judge_escalations(binding_id,credential_id,pending_id)",
)


def upgrade() -> None:
    for statement in DDL:
        op.execute(statement)


def downgrade() -> None:
    raise RuntimeError('Judge escalation downgrade is not supported; restore an explicitly inspected archive')
