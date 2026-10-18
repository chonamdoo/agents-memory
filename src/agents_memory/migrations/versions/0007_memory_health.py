from alembic import op

revision = '0007_memory_health'
down_revision = '0006_agent_judged'
branch_labels = None
depends_on = None

DDL = (
    "ALTER TABLE am_operations ADD COLUMN actor_generation bigint",
    "ALTER TABLE am_sources ADD COLUMN health_restore_revision bigint",
    "ALTER TABLE am_admissions ADD COLUMN health_manifest jsonb",
    "ALTER TABLE am_pending_judgments DROP CONSTRAINT am_pending_judgments_kind_check",
    "ALTER TABLE am_pending_judgments ADD CONSTRAINT am_pending_judgments_kind_check CHECK(kind IN ('source_selection','cleanup','legacy_revalidation','health'))",
    "ALTER TABLE am_pending_judgments ADD COLUMN health_key text",
    "ALTER TABLE am_pending_judgments ADD COLUMN health_revision bigint NOT NULL DEFAULT 0",
    "ALTER TABLE am_pending_judgments ADD COLUMN health_payload jsonb NOT NULL DEFAULT '{}'",
    "CREATE UNIQUE INDEX am_health_pending_key ON am_pending_judgments(binding_id,health_key) WHERE kind='health' AND health_key IS NOT NULL",
    """CREATE TABLE am_health_policies (
        binding_id text PRIMARY KEY REFERENCES am_bindings(id), revision bigint NOT NULL CHECK(revision>0),
        enabled boolean NOT NULL, allow_jev_health boolean NOT NULL,
        max_audit_sources integer NOT NULL CHECK(max_audit_sources BETWEEN 1 AND 128),
        max_audit_claims integer NOT NULL CHECK(max_audit_claims BETWEEN 1 AND 20),
        max_audit_bytes integer NOT NULL CHECK(max_audit_bytes BETWEEN 1024 AND 131072),
        CHECK(enabled OR NOT allow_jev_health))""",
    """CREATE TABLE am_code_workspaces (
        id text PRIMARY KEY, binding_id text NOT NULL REFERENCES am_bindings(id),
        revision bigint NOT NULL CHECK(revision>0), root_fingerprint text NOT NULL,
        producer_credential_id text NOT NULL REFERENCES am_credentials(id), producer_generation bigint NOT NULL,
        binding_revision bigint NOT NULL, last_sequence bigint NOT NULL DEFAULT 0,
        state text NOT NULL DEFAULT 'active' CHECK(state IN ('active','retracted')))""",
    """CREATE TABLE am_code_observations (
        id text PRIMARY KEY, binding_id text NOT NULL REFERENCES am_bindings(id),
        workspace_id text NOT NULL REFERENCES am_code_workspaces(id), workspace_revision bigint NOT NULL,
        relative_path text NOT NULL, symbol_name text NOT NULL DEFAULT '',
        sequence bigint NOT NULL, fingerprint text NOT NULL, metadata jsonb,
        state text NOT NULL DEFAULT 'active' CHECK(state IN ('active','retracted')),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp())""",
    "CREATE UNIQUE INDEX am_code_current ON am_code_observations(workspace_id,relative_path,symbol_name) WHERE state='active'",
    """CREATE TABLE am_claim_health (
        claim_id text PRIMARY KEY REFERENCES am_claims(id), claim_revision bigint NOT NULL,
        binding_id text NOT NULL REFERENCES am_bindings(id), version bigint NOT NULL DEFAULT 1 CHECK(version>0),
        support text NOT NULL DEFAULT 'unknown' CHECK(support IN ('supported','contradicted','unknown')),
        freshness text NOT NULL DEFAULT 'unknown' CHECK(freshness IN ('observed_current','stale','unknown')),
        needs_review boolean NOT NULL DEFAULT false, restore_unknown boolean NOT NULL DEFAULT false,
        operator_review text CHECK(operator_review IN ('accept','reject')), review_event_id text,
        assessment_event_id text)""",
    """CREATE TABLE am_code_links (
        claim_id text NOT NULL REFERENCES am_claims(id), claim_revision bigint NOT NULL,
        observation_id text NOT NULL REFERENCES am_code_observations(id),
        PRIMARY KEY(claim_id,claim_revision,observation_id))""",
    """CREATE TABLE am_health_events (
        id text PRIMARY KEY, binding_id text NOT NULL REFERENCES am_bindings(id),
        operation_id text NOT NULL REFERENCES am_operations(id), kind text NOT NULL,
        credential_id text NOT NULL REFERENCES am_credentials(id), credential_generation bigint NOT NULL,
        realm text NOT NULL, role text NOT NULL, target_ref text,
        reason_source_id text REFERENCES am_sources(id), source_ids text[] NOT NULL DEFAULT '{}',
        claim_ids text[] NOT NULL DEFAULT '{}', payload jsonb,
        state text NOT NULL DEFAULT 'active' CHECK(state IN ('active','retracted')),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp())""",
    "CREATE INDEX am_health_event_target ON am_health_events(binding_id,target_ref,created_at,id)",
    """CREATE TABLE am_session_observations (
        id text PRIMARY KEY, binding_id text NOT NULL REFERENCES am_bindings(id),
        credential_id text NOT NULL REFERENCES am_credentials(id), credential_generation bigint NOT NULL,
        stream_id text NOT NULL, segment_id text NOT NULL, event_id text NOT NULL,
        sequence bigint NOT NULL, digest text NOT NULL, payload jsonb,
        state text NOT NULL DEFAULT 'active' CHECK(state IN ('active','retracted')),
        UNIQUE(binding_id,credential_id,credential_generation,stream_id,segment_id,event_id),
        UNIQUE(binding_id,credential_id,credential_generation,stream_id,segment_id,sequence))""",
    "ALTER TABLE am_feedback ADD COLUMN health_version bigint NOT NULL DEFAULT 0",
    "ALTER TABLE am_feedback ADD COLUMN resolution_event_id text",
    """INSERT INTO am_claim_health(claim_id,claim_revision,binding_id)
        SELECT id,revision,binding_id FROM am_claims WHERE state='active' AND draft IS NOT NULL""",
)


def upgrade() -> None:
    for statement in DDL:
        op.execute(statement)


def downgrade() -> None:
    raise RuntimeError('Memory health downgrade is not supported; restore an explicitly inspected archive')
