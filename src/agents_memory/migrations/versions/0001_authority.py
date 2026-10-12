from alembic import op

revision = "0001_authority"
down_revision = None
branch_labels = None
depends_on = None


DDL = """
CREATE TABLE am_clock (
 singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
 epoch bigint NOT NULL DEFAULT 0,
 roster_revision bigint NOT NULL DEFAULT 1,
 deletion_generation bigint NOT NULL DEFAULT 0,
 deployment_id text,
 realm text,
 journal_head text
);
INSERT INTO am_clock(singleton) VALUES(true);
CREATE TABLE am_credentials (
 id text PRIMARY KEY, principal_id text NOT NULL, realm text NOT NULL,
 role text NOT NULL CHECK(role IN ('agent','producer','operator','approver')),
 token_hash text NOT NULL UNIQUE, generation bigint NOT NULL DEFAULT 1,
 active boolean NOT NULL DEFAULT true, created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE am_bindings (
 id text PRIMARY KEY, realm text NOT NULL, owner_id text NOT NULL,
 label text NOT NULL, locator text, revision bigint NOT NULL DEFAULT 1
);
CREATE TABLE am_grants (
 credential_id text NOT NULL REFERENCES am_credentials(id),
 binding_id text NOT NULL REFERENCES am_bindings(id),
 PRIMARY KEY(credential_id,binding_id)
);
CREATE TABLE am_receipts (
 principal_id text NOT NULL, binding_id text NOT NULL, kind text NOT NULL,
 request_key text NOT NULL, digest text NOT NULL, target_id text,
 result jsonb NOT NULL DEFAULT '{}', PRIMARY KEY(principal_id,binding_id,kind,request_key)
);
CREATE TABLE am_operations (
 id text PRIMARY KEY, binding_id text NOT NULL REFERENCES am_bindings(id),
 credential_id text NOT NULL REFERENCES am_credentials(id),
 kind text NOT NULL, state text NOT NULL, source_id text, artifact_id text,
 error_code text, epoch bigint NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE am_sources (
 id text PRIMARY KEY, binding_id text NOT NULL REFERENCES am_bindings(id),
 realm text NOT NULL, revision bigint NOT NULL DEFAULT 1,
 body text, speaker text NOT NULL, kind text NOT NULL,
 origin_key text NOT NULL, origin_token text NOT NULL UNIQUE, source_token text NOT NULL UNIQUE,
 origin_digest text NOT NULL, root_run_id text, agent_path text,
 snapshot text, event_time timestamptz, recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 state text NOT NULL DEFAULT 'active' CHECK(state IN ('active','retracted','purged')),
 operation_id text NOT NULL REFERENCES am_operations(id)
);
CREATE INDEX am_sources_binding ON am_sources(binding_id,state);
CREATE TABLE am_floors (kind text NOT NULL CHECK(kind IN ('source','origin')), token text NOT NULL,
 PRIMARY KEY(kind,token));
CREATE TABLE am_claims (
 id text PRIMARY KEY, binding_id text NOT NULL REFERENCES am_bindings(id),
 draft jsonb, snapshot text, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 state text NOT NULL DEFAULT 'active' CHECK(state IN ('active','retracted')),
 route_revision text NOT NULL, embedding public.vector(1024), lexical_tokens text[] NOT NULL DEFAULT '{}',
 valid_from timestamptz, valid_until timestamptz
);
CREATE INDEX am_claims_lexical ON am_claims USING gin(lexical_tokens);
CREATE INDEX am_claims_binding ON am_claims(binding_id,state);
CREATE TABLE am_claim_sources (
 claim_id text NOT NULL REFERENCES am_claims(id), source_id text NOT NULL REFERENCES am_sources(id),
 source_revision bigint NOT NULL, PRIMARY KEY(claim_id,source_id)
);
CREATE TABLE am_spans (
 claim_id text NOT NULL REFERENCES am_claims(id), ordinal integer NOT NULL,
 source_id text NOT NULL REFERENCES am_sources(id), source_revision bigint NOT NULL,
 byte_start integer NOT NULL CHECK(byte_start>=0), byte_end integer NOT NULL CHECK(byte_end>byte_start),
 quote text, PRIMARY KEY(claim_id,ordinal)
);
CREATE TABLE am_entities (
 claim_id text NOT NULL REFERENCES am_claims(id), name text NOT NULL, search_name text NOT NULL,
 PRIMARY KEY(claim_id,name)
);
CREATE INDEX am_entities_search ON am_entities(search_name,claim_id);
CREATE TABLE am_relations (
 id text PRIMARY KEY, binding_id text NOT NULL REFERENCES am_bindings(id),
 left_id text NOT NULL REFERENCES am_claims(id), right_id text NOT NULL REFERENCES am_claims(id),
 kind text NOT NULL, reason text, state text NOT NULL DEFAULT 'active',
 CHECK(left_id<>right_id)
);
CREATE TABLE am_relation_sources (
 relation_id text NOT NULL REFERENCES am_relations(id), source_id text NOT NULL REFERENCES am_sources(id),
 source_revision bigint NOT NULL, PRIMARY KEY(relation_id,source_id)
);
CREATE TABLE am_reflections (
 id text PRIMARY KEY, binding_id text NOT NULL REFERENCES am_bindings(id),
 draft jsonb, state text NOT NULL DEFAULT 'active', created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE am_reflection_sources (
 reflection_id text NOT NULL REFERENCES am_reflections(id), source_id text NOT NULL REFERENCES am_sources(id),
 source_revision bigint NOT NULL, PRIMARY KEY(reflection_id,source_id)
);
CREATE TABLE am_reflection_claims (
 reflection_id text NOT NULL REFERENCES am_reflections(id), claim_id text NOT NULL REFERENCES am_claims(id),
 PRIMARY KEY(reflection_id,claim_id)
);
CREATE TABLE am_proposals (
 id text PRIMARY KEY, binding_id text NOT NULL REFERENCES am_bindings(id),
 principal_id text NOT NULL, source_id text NOT NULL REFERENCES am_sources(id),
 selector jsonb NOT NULL, exceptions jsonb NOT NULL, required boolean NOT NULL,
 digest text NOT NULL, target_set_revision bigint NOT NULL, state text NOT NULL DEFAULT 'candidate'
);
CREATE TABLE am_proposal_sources (
 proposal_id text NOT NULL REFERENCES am_proposals(id), source_id text NOT NULL REFERENCES am_sources(id),
 source_revision bigint NOT NULL, PRIMARY KEY(proposal_id,source_id)
);
CREATE INDEX am_proposal_source_parent ON am_proposal_sources(source_id,proposal_id);
CREATE TABLE am_rules (
 id text PRIMARY KEY, proposal_id text NOT NULL REFERENCES am_proposals(id), revision bigint NOT NULL DEFAULT 1,
 digest text NOT NULL, scope text NOT NULL CHECK(scope IN ('local_project','my_projects','shared')),
 target_set_revision bigint NOT NULL, approver_credential_id text NOT NULL REFERENCES am_credentials(id),
 approver_generation bigint NOT NULL, approval jsonb NOT NULL, state text NOT NULL DEFAULT 'active', UNIQUE(proposal_id)
);
CREATE TABLE am_rule_targets (
 rule_id text NOT NULL REFERENCES am_rules(id), binding_id text NOT NULL REFERENCES am_bindings(id),
 PRIMARY KEY(rule_id,binding_id)
);
CREATE TABLE am_feedback (
 id text PRIMARY KEY, binding_id text NOT NULL REFERENCES am_bindings(id),
 target_ref text NOT NULL, kind text NOT NULL, source_id text REFERENCES am_sources(id)
);
CREATE TABLE am_routes (
 purpose text PRIMARY KEY, revision text NOT NULL, enabled boolean NOT NULL, epoch bigint NOT NULL
);
CREATE TABLE am_jobs (
 id text PRIMARY KEY, binding_id text NOT NULL REFERENCES am_bindings(id),
 operation_id text NOT NULL REFERENCES am_operations(id), credential_id text NOT NULL REFERENCES am_credentials(id),
 credential_generation bigint NOT NULL, kind text NOT NULL CHECK(kind IN ('extract','consolidate','reflect')),
 source_ids text[] NOT NULL, claim_ids text[] NOT NULL DEFAULT '{}', query_source_id text,
 snapshot text, state text NOT NULL DEFAULT 'pending', generation bigint NOT NULL DEFAULT 1,
 attempts integer NOT NULL DEFAULT 0, lease_token text, deadline timestamptz,
 available_at timestamptz NOT NULL DEFAULT clock_timestamp(), error_code text,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX am_jobs_claim ON am_jobs(state,available_at,created_at);
CREATE TABLE am_admissions (
 id text PRIMARY KEY, binding_id text NOT NULL REFERENCES am_bindings(id),
 credential_id text NOT NULL REFERENCES am_credentials(id), credential_generation bigint NOT NULL,
 epoch bigint NOT NULL, deletion_generation bigint NOT NULL, route_revision text NOT NULL,
 purpose text NOT NULL, route_epochs jsonb NOT NULL, sources jsonb NOT NULL, claim_ids text[] NOT NULL,
 deadline timestamptz NOT NULL, snapshot text,
 job_id text REFERENCES am_jobs(id), lease_token text, generation bigint,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
)
"""


def upgrade() -> None:
    for statement in DDL.split(";"):
        if statement.strip():
            op.execute(statement)


def downgrade() -> None:
    raise RuntimeError("Authority migrations are forward-only; restore requires deletion-floor reconciliation")
