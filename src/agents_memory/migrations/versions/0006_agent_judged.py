from alembic import op

revision = "0006_agent_judged"
down_revision = "0005_company_selection"
branch_labels = None
depends_on = None

DDL = (
    "ALTER TABLE am_claims DROP CONSTRAINT am_claims_capability_origin",
    "ALTER TABLE am_claims DROP CONSTRAINT am_claims_capability_check",
    "UPDATE am_claims SET capability='agent_judged' WHERE capability='lexical_entity'",
    "ALTER TABLE am_claims ADD CONSTRAINT am_claims_capability_check CHECK(capability IN ('full_semantic','agent_judged'))",
    """ALTER TABLE am_claims ADD CONSTRAINT am_claims_capability_origin CHECK (
     (capability='full_semantic' AND route_revision IS NOT NULL AND interpretation_role='model_derived_candidate' AND selection_id IS NULL AND policy_revision IS NULL)
     OR (capability='agent_judged' AND route_revision IS NULL AND embedding IS NULL AND vector_revision IS NULL AND interpretation_role='caller_grounded_candidate' AND selection_id IS NOT NULL AND policy_revision IS NOT NULL)
    )""",
    "ALTER TABLE am_claims ADD COLUMN revision bigint NOT NULL DEFAULT 1",
    "ALTER TABLE am_claims ADD COLUMN awaiting_revalidation boolean NOT NULL DEFAULT false",
    "UPDATE am_claims SET awaiting_revalidation=true WHERE interpretation_role='model_derived_candidate'",
    "ALTER TABLE am_source_selections ADD COLUMN reason text",
    "ALTER TABLE am_source_selections ADD COLUMN prior_rejection_ids text[] NOT NULL DEFAULT '{}'",
    "ALTER TABLE am_source_selections ADD COLUMN rejection_comparisons jsonb NOT NULL DEFAULT '[]'",
    "ALTER TABLE am_source_selections ADD COLUMN request_snapshot text",
    "UPDATE am_source_selections SET request_snapshot=snapshot",
    "ALTER TABLE am_source_selections ADD COLUMN rejection_inputs jsonb NOT NULL DEFAULT '{}'",
    "ALTER TABLE am_source_selections ADD COLUMN rejection_review_ids text[] NOT NULL DEFAULT '{}'",
    "ALTER TABLE am_source_selections ADD COLUMN deletion_generation bigint NOT NULL DEFAULT -1",
    "ALTER TABLE am_feedback ADD COLUMN reason text",
    "ALTER TABLE am_feedback ADD COLUMN rejected_source_ids text[] NOT NULL DEFAULT '{}'",
    "ALTER TABLE am_feedback ALTER COLUMN state SET DEFAULT 'active'",
    "UPDATE am_feedback SET state='active' WHERE kind='reject' AND state='candidate'",
    "ALTER TABLE am_admissions ADD COLUMN request_digest text",
    "ALTER TABLE am_admissions ADD COLUMN claim_revisions jsonb NOT NULL DEFAULT '[]'",
    "ALTER TABLE am_admissions ADD COLUMN rejection_ids text[] NOT NULL DEFAULT '{}'",
    "ALTER TABLE am_admissions ADD COLUMN rejection_inputs jsonb NOT NULL DEFAULT '{}'",
    "ALTER TABLE am_jobs ADD COLUMN retired_at timestamptz",
    """CREATE TABLE am_pending_judgments (
     id text PRIMARY KEY, binding_id text NOT NULL REFERENCES am_bindings(id),
     sequence bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
     kind text NOT NULL CHECK(kind IN ('source_selection','cleanup','legacy_revalidation')),
     source_ids text[] NOT NULL DEFAULT '{}', claim_ids text[] NOT NULL DEFAULT '{}',
     snapshot text,
     state text NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','held','resolved','retracted')),
     reason text, original_job_id text UNIQUE REFERENCES am_jobs(id),
     created_at timestamptz NOT NULL DEFAULT clock_timestamp(), resolved_at timestamptz
    )""",
    "ALTER TABLE am_admissions ADD COLUMN pending_id text REFERENCES am_pending_judgments(id)",
    "CREATE INDEX am_pending_judgments_binding ON am_pending_judgments(binding_id,state,sequence)",
    "CREATE UNIQUE INDEX am_cleanup_pending ON am_pending_judgments(binding_id,COALESCE(snapshot,'')) WHERE kind='cleanup' AND state='pending'",
    """CREATE TABLE am_retired_jobs (
     job_id text PRIMARY KEY REFERENCES am_jobs(id), original jsonb NOT NULL, original_operation jsonb NOT NULL,
     successor_id text NOT NULL REFERENCES am_pending_judgments(id),
     retired_at timestamptz NOT NULL DEFAULT clock_timestamp()
    )""",
    """INSERT INTO am_pending_judgments(id,binding_id,kind,source_ids,claim_ids,snapshot,state,reason,original_job_id)
     SELECT 'pending_' || j.id,j.binding_id,'legacy_revalidation',j.source_ids,j.claim_ids,j.snapshot,
     CASE WHEN cardinality(j.source_ids)>0 AND NOT EXISTS(SELECT 1 FROM unnest(j.source_ids) AS i(id)
      LEFT JOIN am_sources s ON s.id=i.id WHERE s.id IS NULL OR s.state<>'active' OR s.body IS NULL OR s.speaker IN ('memory','agent_note'))
     THEN 'pending' ELSE 'held' END,
     'Legacy executable work retired; original job evidence retained; caller judgment required',j.id
     FROM am_jobs j WHERE j.state IN ('pending','leased','blocked','failed')""",
    """INSERT INTO am_retired_jobs(job_id,original,original_operation,successor_id)
     SELECT j.id,to_jsonb(j),to_jsonb(o),'pending_' || j.id FROM am_jobs j
     JOIN am_operations o ON o.id=j.operation_id JOIN am_pending_judgments p ON p.original_job_id=j.id""",
    """UPDATE am_jobs SET state='retired',retired_at=clock_timestamp(),generation=generation+1,lease_token=NULL,deadline=NULL
     WHERE id IN (SELECT job_id FROM am_retired_jobs)""",
    """INSERT INTO am_pending_judgments(id,binding_id,kind,source_ids,snapshot,state,reason)
     SELECT 'pending_source_' || s.id,s.binding_id,'legacy_revalidation',ARRAY[s.id],s.snapshot,
     'pending',
     'Captured legacy source retained; inspection under the current caller contract required'
     FROM am_sources s WHERE s.state='active' AND s.body IS NOT NULL
     AND s.speaker NOT IN ('memory','agent_note')
     AND NOT EXISTS(SELECT 1 FROM am_pending_judgments p WHERE s.id=ANY(p.source_ids))""",
    "UPDATE am_feedback f SET reason=s.body FROM am_sources s WHERE f.kind='reject' AND s.id=f.source_id",
    """WITH RECURSIVE targets(feedback_id,ref) AS (
     SELECT id,target_ref FROM am_feedback WHERE kind='reject'
     UNION SELECT t.feedback_id,COALESCE(o.artifact_id,r.proposal_id) FROM targets t
     LEFT JOIN am_operations o ON o.id=t.ref LEFT JOIN am_rules r ON r.id=t.ref
     WHERE COALESCE(o.artifact_id,r.proposal_id) IS NOT NULL
    ), evidence AS (
     SELECT t.feedback_id,s.id AS source_id FROM targets t JOIN am_sources s ON s.id=t.ref
     UNION SELECT t.feedback_id,o.source_id FROM targets t JOIN am_operations o ON o.id=t.ref
      WHERE o.artifact_id IS NULL AND o.source_id IS NOT NULL
     UNION SELECT t.feedback_id,f.source_id FROM targets t JOIN am_feedback f ON f.id=t.ref WHERE f.source_id IS NOT NULL
     UNION SELECT t.feedback_id,d.source_id FROM targets t JOIN am_claim_sources d ON d.claim_id=t.ref
     UNION SELECT t.feedback_id,d.source_id FROM targets t JOIN am_selection_sources d ON d.selection_id=t.ref
     UNION SELECT t.feedback_id,d.source_id FROM targets t JOIN am_relation_sources d ON d.relation_id=t.ref
     UNION SELECT t.feedback_id,d.source_id FROM targets t JOIN am_reflection_sources d ON d.reflection_id=t.ref
     UNION SELECT t.feedback_id,d.source_id FROM targets t JOIN am_proposal_sources d ON d.proposal_id=t.ref
    ), collected AS (
     SELECT feedback_id,array_agg(source_id ORDER BY source_id) AS source_ids FROM evidence GROUP BY feedback_id
    )
    UPDATE am_feedback f SET rejected_source_ids=c.source_ids FROM collected c WHERE c.feedback_id=f.id""",
    "ALTER TABLE am_clock ADD COLUMN retired_authority jsonb NOT NULL DEFAULT '{}'",
    """UPDATE am_clock SET retired_authority=jsonb_build_object(
     'routes',COALESCE((SELECT jsonb_agg(to_jsonb(r) ORDER BY purpose) FROM am_routes r),'[]'::jsonb),
     'selection_policies',COALESCE((SELECT jsonb_agg(to_jsonb(p) ORDER BY binding_id) FROM am_selection_policies p),'[]'::jsonb))""",
    "UPDATE am_routes SET enabled=false",
    "UPDATE am_selection_policies SET enabled=false",
    """CREATE TABLE am_claim_judgments (
     id text PRIMARY KEY, binding_id text NOT NULL REFERENCES am_bindings(id),
     operation_id text NOT NULL REFERENCES am_operations(id),
     credential_id text NOT NULL REFERENCES am_credentials(id), credential_generation bigint NOT NULL,
     admission_id text NOT NULL, manifest_digest text NOT NULL,
     claims jsonb NOT NULL, sources jsonb NOT NULL, relations jsonb, reason text, snapshot text,
     state text NOT NULL DEFAULT 'active' CHECK(state IN ('active','retracted')),
     created_at timestamptz NOT NULL DEFAULT clock_timestamp()
    )""",
    "ALTER TABLE am_relations ADD COLUMN judgment_id text REFERENCES am_claim_judgments(id)",
    """CREATE TABLE am_rejection_evidence (
        binding_id text NOT NULL REFERENCES am_bindings(id),
        rejection_id text NOT NULL,
        source_id text NOT NULL REFERENCES am_sources(id),
        snapshot text NOT NULL,
        source_revision bigint NOT NULL,
        body_digest text NOT NULL CHECK(body_digest ~ '^[a-f0-9]{64}$'),
        byte_start integer,
        byte_end integer,
        PRIMARY KEY(rejection_id,source_id),
        CHECK(
            (byte_start IS NULL AND byte_end IS NULL)
            OR (
                byte_start IS NOT NULL AND byte_end IS NOT NULL
                AND byte_start>=0 AND byte_end>byte_start
            )
        )
    )""",
    """CREATE INDEX am_rejection_evidence_source
       ON am_rejection_evidence(binding_id,source_id,snapshot,rejection_id)""",
    """CREATE INDEX am_rejection_evidence_body
       ON am_rejection_evidence(binding_id,body_digest,snapshot,rejection_id)""",
    """CREATE TABLE am_rejection_tokens (
        binding_id text NOT NULL REFERENCES am_bindings(id),
        token_digest text NOT NULL CHECK(token_digest ~ '^[a-f0-9]{64}$'),
        rejection_id text NOT NULL,
        snapshot text NOT NULL,
        PRIMARY KEY(binding_id,token_digest,snapshot,rejection_id)
    )""",
    """CREATE INDEX am_rejection_tokens_owner
       ON am_rejection_tokens(binding_id,rejection_id)""",
    """CREATE INDEX am_rejection_history_selection
       ON am_source_selections(binding_id,id)
       WHERE label='discard' AND state='active'""",
    """CREATE INDEX am_rejection_history_feedback
       ON am_feedback(binding_id,id)
       WHERE kind='reject' AND state='active'""",
    """CREATE INDEX am_feedback_reason_source
       ON am_feedback(binding_id,source_id,id)""",
    "ALTER TABLE am_claims ADD COLUMN cleanup_sequence bigint GENERATED ALWAYS AS IDENTITY UNIQUE",
    "ALTER TABLE am_clock ADD COLUMN cleanup_progress jsonb NOT NULL DEFAULT '{}'",
    """ALTER TABLE am_clock ADD CONSTRAINT am_clock_cleanup_progress_object
        CHECK(jsonb_typeof(cleanup_progress)='object')""",
    """CREATE INDEX am_cleanup_scan ON am_pending_judgments(sequence)
        WHERE kind='cleanup' AND state IN ('pending','held')""",
    """CREATE INDEX am_cleanup_owner ON am_pending_judgments(
        binding_id,COALESCE(snapshot,''),state)
        WHERE kind='cleanup' AND state IN ('pending','held')""",
    """CREATE INDEX am_cleanup_recent ON am_pending_judgments(
        binding_id,COALESCE(snapshot,''),created_at DESC)
        WHERE kind='cleanup'""",
    """CREATE INDEX am_cleanup_judged_manifest ON am_claim_judgments(
        binding_id,manifest_digest,created_at DESC,id DESC)
        WHERE state='active'""",
)


def upgrade() -> None:
    import hashlib

    from sqlalchemy import text

    from agents_memory.lexical import tokens

    def _rejection_scope(connection, rejection_id, source_ids):
        scoped = connection.execute(text(
            "SELECT snapshot FROM am_sources WHERE id=ANY(:ids) AND snapshot IS NOT NULL"
        ), {"ids": source_ids}).scalars().all()
        scopes = set(scoped)
        ref, visited = rejection_id, set()
        for _ in range(32):
            if ref in visited:
                return None
            visited.add(ref)
            metadata = connection.execute(text("""
                SELECT * FROM (
                    SELECT 'operation' AS kind,to_jsonb(t) AS data FROM am_operations t WHERE id=:ref
                    UNION ALL SELECT 'source',to_jsonb(t) FROM am_sources t WHERE id=:ref
                    UNION ALL SELECT 'selection',to_jsonb(t) FROM am_source_selections t WHERE id=:ref
                    UNION ALL SELECT 'claim',to_jsonb(t) FROM am_claims t WHERE id=:ref
                    UNION ALL SELECT 'judgment',to_jsonb(t) FROM am_claim_judgments t WHERE id=:ref
                    UNION ALL SELECT 'relation',to_jsonb(t) FROM am_relations t WHERE id=:ref
                    UNION ALL SELECT 'reflection',to_jsonb(t) FROM am_reflections t WHERE id=:ref
                    UNION ALL SELECT 'proposal',to_jsonb(t) FROM am_proposals t WHERE id=:ref
                    UNION ALL SELECT 'feedback',to_jsonb(t) FROM am_feedback t WHERE id=:ref
                    UNION ALL SELECT 'rule',to_jsonb(t) FROM am_rules t WHERE id=:ref
                ) metadata LIMIT 1
            """), {"ref": ref}).mappings().first()
            if metadata is None:
                return None
            target = metadata["data"]
            scopes.update(target[name] for name in ("snapshot", "request_snapshot")
                          if target.get(name) is not None)
            kind = metadata["kind"]
            if kind == "operation":
                ref = target["artifact_id"] or target["source_id"]
            elif kind == "feedback":
                ref = target["target_ref"]
            elif kind == "relation":
                ref = target["judgment_id"]
            elif kind == "rule":
                ref = target["proposal_id"]
            else:
                break
            if ref is None:
                break
        else:
            return None
        return next(iter(scopes), "") if len(scopes) <= 1 else None

    def _backfill_rejection_index(connection) -> None:
        after = ""
        while True:
            rows = connection.execute(
                text(
                    """SELECT * FROM (
                           SELECT binding_id,id,'selection' AS rejection_kind,
                                  ARRAY[source_id] AS source_ids,
                                  source_revision,byte_start,byte_end
                           FROM am_source_selections WHERE label='discard'
                           UNION ALL
                           SELECT binding_id,id,'feedback' AS rejection_kind,
                                  rejected_source_ids AS source_ids,
                                  NULL::bigint AS source_revision,
                                  NULL::integer AS byte_start,NULL::integer AS byte_end
                           FROM am_feedback WHERE kind='reject'
                       ) rejected WHERE id>:after ORDER BY id LIMIT 32"""
                ),
                {"after": after},
            ).mappings().all()
            if not rows:
                return
            for row in rows:
                after = row["id"]
                source_ids = row["source_ids"]
                scope = _rejection_scope(connection, row["id"], source_ids)
                if scope is None:
                    continue
                token_digests = set()
                for source_id in sorted(set(source_ids)):
                    source = connection.execute(
                        text(
                            """SELECT * FROM am_sources
                               WHERE id=:source_id AND binding_id=:binding_id
                                 AND body IS NOT NULL
                                 AND speaker NOT IN ('agent_note','memory')"""
                        ),
                        {
                            "source_id": source_id,
                            "binding_id": row["binding_id"],
                        },
                    ).mappings().first()
                    if source is None:
                        continue
                    if (
                        row["rejection_kind"] == "selection"
                        and row["source_revision"] != source["revision"]
                    ):
                        continue
                    body = source["body"]
                    start, end = row["byte_start"], row["byte_end"]
                    indexed_body = (
                        body.encode()[start:end].decode()
                        if start is not None and end is not None else body
                    )
                    connection.execute(
                        text(
                            """INSERT INTO am_rejection_evidence(
                                   binding_id,rejection_id,source_id,source_revision,
                                   body_digest,byte_start,byte_end,snapshot
                               ) VALUES(
                                   :binding_id,:rejection_id,:source_id,:source_revision,
                                   :body_digest,:byte_start,:byte_end,:snapshot
                               )"""
                        ),
                        {
                            "binding_id": row["binding_id"],
                            "rejection_id": row["id"],
                            "source_id": source_id,
                            "source_revision": source["revision"],
                            "body_digest": hashlib.sha256(body.encode()).hexdigest(),
                            "byte_start": start,
                            "byte_end": end,
                            "snapshot": scope,
                        },
                    )
                    token_digests.update(
                        hashlib.sha256(token.encode()).hexdigest()
                        for token in tokens(indexed_body)[:16]
                    )
                if token_digests:
                    connection.execute(
                        text(
                            """INSERT INTO am_rejection_tokens(
                                   binding_id,token_digest,rejection_id,snapshot
                               ) VALUES(:binding_id,:token_digest,:rejection_id,:snapshot)"""
                        ),
                        [
                            {
                                "binding_id": row["binding_id"],
                                "token_digest": token_digest,
                                "snapshot": scope,
                                "rejection_id": row["id"],
                            }
                            for token_digest in sorted(token_digests)
                        ],
                    )

    for statement in DDL:
        op.execute(statement)
    _backfill_rejection_index(op.get_bind())


def downgrade() -> None:
    raise RuntimeError("Authority migrations are forward-only; restore requires deletion-floor reconciliation")
