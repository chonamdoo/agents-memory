from alembic import op

revision = "0005_company_selection"
down_revision = "0004_operation_successors"
branch_labels = None
depends_on = None

DDL = """
ALTER TABLE am_sources ADD COLUMN producer_generation bigint;
ALTER TABLE am_floors DROP CONSTRAINT am_floors_kind_check;
ALTER TABLE am_floors ADD CONSTRAINT am_floors_kind_check CHECK(kind IN ('source','origin','artifact','purge_source','purge_origin','purge_artifact'));
ALTER TABLE am_sources ADD COLUMN capture_coverage jsonb NOT NULL DEFAULT jsonb_build_object('status','unknown','gaps','[]'::jsonb,'original_bytes',NULL,'provenance','producer_reported');
ALTER TABLE am_operations ADD COLUMN source_pointer jsonb;
ALTER TABLE am_operations ADD COLUMN capture_disposition text CHECK(capture_disposition IN ('captured','ignored','retracted','unresolved'));
ALTER TABLE am_operations ADD COLUMN selection_label text CHECK(selection_label IN ('remember','discard','review'));
CREATE TABLE am_selection_policies (
 binding_id text PRIMARY KEY REFERENCES am_bindings(id), revision text NOT NULL,
 enabled boolean NOT NULL, epoch bigint NOT NULL,
 binding_revision bigint NOT NULL, realm text NOT NULL,
 approver_credential_id text NOT NULL REFERENCES am_credentials(id), approver_generation bigint NOT NULL
);
CREATE TABLE am_source_selections (
 id text PRIMARY KEY, binding_id text NOT NULL REFERENCES am_bindings(id),
 operation_id text NOT NULL REFERENCES am_operations(id), credential_id text NOT NULL REFERENCES am_credentials(id),
 credential_generation bigint NOT NULL, realm text NOT NULL, binding_revision bigint NOT NULL,
 snapshot text, source_id text NOT NULL REFERENCES am_sources(id), source_revision bigint NOT NULL,
 byte_start integer NOT NULL CHECK(byte_start>=0), byte_end integer NOT NULL CHECK(byte_end>byte_start AND byte_end-byte_start<=4096),
 window_digest text NOT NULL, judgment_digest text NOT NULL, policy_revision text NOT NULL, policy_epoch bigint NOT NULL,
 label text NOT NULL CHECK(label IN ('remember','discard','review')),
 coverage text NOT NULL CHECK(coverage IN ('complete_window','incomplete_window')),
 state text NOT NULL DEFAULT 'active' CHECK(state IN ('active','retracted')),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE am_selection_sources (
 selection_id text NOT NULL REFERENCES am_source_selections(id), source_id text NOT NULL REFERENCES am_sources(id),
 source_revision bigint NOT NULL, PRIMARY KEY(selection_id,source_id)
);
CREATE INDEX am_selection_sources_parent ON am_selection_sources(source_id,selection_id);
ALTER TABLE am_claims ALTER COLUMN route_revision DROP NOT NULL;
ALTER TABLE am_claims ADD COLUMN capability text NOT NULL DEFAULT 'full_semantic' CHECK(capability IN ('full_semantic','lexical_entity'));
ALTER TABLE am_claims ADD COLUMN interpretation_role text NOT NULL DEFAULT 'model_derived_candidate' CHECK(interpretation_role IN ('model_derived_candidate','caller_grounded_candidate'));
ALTER TABLE am_claims ADD COLUMN selection_id text REFERENCES am_source_selections(id);
ALTER TABLE am_claims ADD COLUMN policy_revision text;
ALTER TABLE am_claims ADD CONSTRAINT am_claims_capability_origin CHECK (
 (capability='full_semantic' AND route_revision IS NOT NULL AND interpretation_role='model_derived_candidate' AND selection_id IS NULL AND policy_revision IS NULL)
 OR (capability='lexical_entity' AND route_revision IS NULL AND embedding IS NULL AND vector_revision IS NULL AND interpretation_role='caller_grounded_candidate' AND selection_id IS NOT NULL AND policy_revision IS NOT NULL)
);
ALTER TABLE am_admissions ALTER COLUMN route_revision DROP NOT NULL;
ALTER TABLE am_admissions ADD COLUMN kind text NOT NULL DEFAULT 'model' CHECK(kind IN ('model','nonmodel'));
ALTER TABLE am_admissions ADD COLUMN binding_revision bigint;
ALTER TABLE am_admissions ADD COLUMN realm text;
ALTER TABLE am_admissions ADD COLUMN policy_revision text;
ALTER TABLE am_admissions ADD COLUMN policy_epoch bigint;
ALTER TABLE am_admissions ADD COLUMN relation_ids text[] NOT NULL DEFAULT '{}';
ALTER TABLE am_admissions ADD CONSTRAINT am_admissions_kind_origin CHECK (
 (kind='model' AND route_revision IS NOT NULL AND policy_revision IS NULL AND policy_epoch IS NULL)
 OR (kind='nonmodel' AND route_revision IS NULL AND binding_revision IS NOT NULL AND realm IS NOT NULL AND policy_revision IS NOT NULL AND policy_epoch IS NOT NULL AND job_id IS NULL AND lease_token IS NULL AND generation IS NULL)
)
"""


def upgrade() -> None:
    for statement in DDL.split(";"):
        if statement.strip():
            op.execute(statement)


def downgrade() -> None:
    raise RuntimeError("Authority migrations are forward-only; restore requires deletion-floor reconciliation")
