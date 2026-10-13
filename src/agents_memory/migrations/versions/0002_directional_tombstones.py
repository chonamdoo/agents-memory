from alembic import op

revision = "0002_directional_tombstones"
down_revision = "0001_authority"
branch_labels = None
depends_on = None


DDL = """
ALTER TABLE am_floors DROP CONSTRAINT IF EXISTS am_floors_kind_check;
ALTER TABLE am_floors ADD CONSTRAINT am_floors_kind_check CHECK(kind IN ('source','origin','artifact'));
ALTER TABLE am_feedback ADD COLUMN IF NOT EXISTS state text NOT NULL DEFAULT 'candidate';
CREATE TABLE IF NOT EXISTS am_relation_claims (
 relation_id text NOT NULL REFERENCES am_relations(id),
 claim_id text NOT NULL REFERENCES am_claims(id),
 PRIMARY KEY(relation_id,claim_id)
);
INSERT INTO am_relation_claims(relation_id,claim_id)
 SELECT DISTINCT r.id,c.claim_id FROM am_relations r
 JOIN am_relation_sources d ON d.relation_id=r.id
 JOIN am_claim_sources c ON c.source_id=d.source_id
 ON CONFLICT DO NOTHING;
INSERT INTO am_relation_claims(relation_id,claim_id)
 SELECT id,left_id FROM am_relations UNION SELECT id,right_id FROM am_relations
 ON CONFLICT DO NOTHING
"""


def upgrade() -> None:
    for statement in DDL.split(";"):
        if statement.strip():
            op.execute(statement)


def downgrade() -> None:
    raise RuntimeError("Authority migrations are forward-only; restore requires deletion-floor reconciliation")
