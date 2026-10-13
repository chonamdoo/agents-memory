from alembic import op

revision = "0004_operation_successors"
down_revision = "0003_origin_and_vector_compat"
branch_labels = None
depends_on = None


DDL = """
ALTER TABLE am_operations ADD COLUMN successor_operation_id text REFERENCES am_operations(id);
ALTER TABLE am_rules DROP CONSTRAINT am_rules_proposal_id_key;
ALTER TABLE am_rules ADD CONSTRAINT am_rules_proposal_revision_key UNIQUE(proposal_id,revision);
CREATE UNIQUE INDEX am_rules_active_proposal ON am_rules(proposal_id) WHERE state='active'
"""


def upgrade() -> None:
    for statement in DDL.split(";"):
        if statement.strip():
            op.execute(statement)


def downgrade() -> None:
    raise RuntimeError("Authority migrations are forward-only; restore requires deletion-floor reconciliation")
