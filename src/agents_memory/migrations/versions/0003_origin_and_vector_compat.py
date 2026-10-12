from alembic import op

revision = "0003_origin_and_vector_compat"
down_revision = "0002_directional_tombstones"
branch_labels = None
depends_on = None


DDL = """
ALTER TABLE am_claims ADD COLUMN vector_revision text;
ALTER TABLE am_claims ADD COLUMN extraction_operation_id text REFERENCES am_operations(id);
ALTER TABLE am_claims ADD COLUMN superseded_by text REFERENCES am_claims(id);
WITH signatures AS (
 SELECT c.id,c.created_at,c.binding_id,c.snapshot,c.draft,c.state,
  (SELECT jsonb_agg(jsonb_build_array(d.source_id,d.source_revision) ORDER BY d.source_id)
   FROM am_claim_sources d WHERE d.claim_id=c.id) AS inputs,
  (SELECT jsonb_agg(jsonb_build_array(s.source_id,s.source_revision,s.byte_start,s.byte_end,s.quote) ORDER BY s.ordinal)
   FROM am_spans s WHERE s.claim_id=c.id) AS spans
 FROM am_claims c WHERE c.draft IS NOT NULL
), canonical AS (
 SELECT id,first_value(id) OVER (
  PARTITION BY binding_id,snapshot,draft,inputs,spans ORDER BY (state='retracted') DESC,created_at,id
 ) AS canonical_id FROM signatures WHERE inputs IS NOT NULL AND spans IS NOT NULL
)
UPDATE am_claims c SET superseded_by=d.canonical_id FROM canonical d
 WHERE c.id=d.id AND d.id<>d.canonical_id;
UPDATE am_claims c SET state='retracted' WHERE c.state='active' AND EXISTS(
 SELECT 1 FROM am_claims canonical WHERE canonical.id=c.superseded_by AND canonical.state='retracted'
);
CREATE TABLE am_origin_reservations (
 origin_token text PRIMARY KEY,
 binding_id text NOT NULL REFERENCES am_bindings(id),
 origin_digest text NOT NULL,
 principal_id text NOT NULL,
 request_key text NOT NULL,
 intent_digest text NOT NULL
);
ALTER TABLE am_jobs DROP CONSTRAINT am_jobs_kind_check;
ALTER TABLE am_jobs ADD CONSTRAINT am_jobs_kind_check CHECK(kind IN ('extract','consolidate','reflect','reindex'));
UPDATE am_receipts SET result=result-'request' WHERE kind='reflect' AND result ? 'request'
"""


def upgrade() -> None:
    for statement in DDL.split(";"):
        if statement.strip():
            op.execute(statement)


def downgrade() -> None:
    raise RuntimeError("Authority migrations are forward-only; restore requires deletion-floor reconciliation")
