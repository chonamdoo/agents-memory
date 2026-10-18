from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import pytest
from test_company_authority import candidate, capture, deliver, judged_context
from test_company_authority import company as company

from agents_memory.domain import (
    CaptureCommand,
    CaptureCoverage,
    ContextCommand,
    DomainError,
    FeedbackCommand,
    Role,
    RuleApproval,
    RuleProposal,
    RuleScope,
    Selector,
)
from agents_memory.health import (
    CodeLinkCommand,
    CodeObservationCommand,
    FeedbackResolutionCommand,
    HealthAssessmentCommand,
    HealthPolicyCommand,
    HealthWorkspaceCommand,
    MemoryReviewCommand,
    SessionObservationCommand,
)


def mutation(company, key):
    return dict(binding_id=company.binding_id, expected_binding_revision=1, idempotency_key=key)


async def enabled(company):
    return await company.store.health(company.actor, HealthPolicyCommand(
        **mutation(company, 'health-enable'), expected_policy_revision=0, enabled=True))


async def workspace(company):
    producer = await company.store.issue_token(company.actor, Role.PRODUCER, (company.binding_id,),
        'health-producer-' + 'x' * 48)
    await company.store.health(company.actor, HealthWorkspaceCommand(**mutation(company, 'register-workspace'),
        workspace_id='workspace_test', expected_workspace_revision=0, root_fingerprint='a' * 64,
        producer_credential_id=producer.credential_id))
    return producer


async def observe(company, producer, sequence, *, digest='b' * 64, status='present'):
    file = {'relative_path': 'src/cache.py', 'status': status}
    if status == 'present':
        file.update(file_digest=digest, byte_length=27, symbol_coverage='complete',
            symbols=[{'qualified_name': 'cache', 'kind': 'function', 'byte_start': 0, 'byte_end': 27,
                'span_digest': digest, 'resolver': 'python_ast'}])
    operation = await company.store.health(producer, CodeObservationCommand(
        **mutation(company, f'code-{sequence}'), workspace_id='workspace_test', expected_workspace_revision=1,
        root_fingerprint='a' * 64, sequence=sequence, observed_at=datetime.now(UTC),
        files=[file], coverage='explicit_paths'))
    view = await company.store.inspect(company.actor, company.binding_id, 'health:workspace:workspace_test')
    return operation, view


async def health_view(company, claim, observation=None):
    ref = 'health:claim:' + claim.id
    if observation:
        ref += ':observation:' + observation
    return await company.store.inspect(company.actor, company.binding_id, ref, claim.snapshot)


async def review(company, claim, key, decision, *, view=None, observations=()):
    view = view or await health_view(company, claim)
    return await company.store.health(company.actor, MemoryReviewCommand(**mutation(company, key),
        admission_id=view['admission']['id'], claim_ref={'id': claim.id, 'revision': claim.revision},
        expected_health_version=view['health']['version'], expected_review_event_id=view['health']['review_event_id'],
        decision=decision, reason='Operator independently reviewed the exact evidence; presence remains unattested.',
        revalidated_observation_refs=list(observations)))


async def recall(company, key='recall', *, workspace_id=None):
    return await company.store.search_lexical(company.actor, company.binding_id, ['CacheKey'], None,
        request_digest=hashlib.sha256(key.encode()).hexdigest(), code_workspace_id=workspace_id)


async def linked_claim(company, *, symbol=False):
    await enabled(company)
    producer = await workspace(company)
    _, observations = await observe(company, producer, 1)
    observation = next(item['ref'] for item in observations['observations']
        if item['symbol_name'] == ('cache' if symbol else ''))
    _, _, claim = await candidate(company)
    view = await health_view(company, claim, observation)
    command = CodeLinkCommand(**mutation(company, 'link-code'), admission_id=view['admission']['id'],
        claim_ref={'id': claim.id, 'revision': claim.revision}, expected_health_version=view['health']['version'],
        observation_refs=[observation], reason='This exact ordinary claim depends on the inspected code anchor.')
    linked = await company.store.record(company.actor, command)
    return producer, claim, linked, command


async def test_exact_reject_blocks_recall_and_inflight_delivery_but_not_inspection(company):
    _, _, claim = await candidate(company)
    rows, admission = await recall(company)
    assert [item[0].id for item in rows] == [claim.id]
    rejected = await review(company, claim, 'reject-claim', 'reject')
    assert rejected.state == 'health_recorded'
    assert (await company.store.inspect(company.actor, company.binding_id, claim.id))['statement'] == claim.draft.statement
    assert (await recall(company, 'after-reject'))[0] == []
    with pytest.raises(DomainError) as stale:
        await deliver(company, admission, selected=(claim.id,))
    assert stale.value.code == 'CONTEXT_STALE'
    inspected = await health_view(company, claim)
    assert inspected['health']['operator_review'] == 'reject' and not inspected['health']['reusable']
    accepted = await review(company, claim, 'accept-claim', 'accept')
    assert accepted.artifact_id != rejected.artifact_id
    assert [item[0].id for item in (await recall(company, 'after-accept'))[0]] == [claim.id]
    view = await health_view(company, claim)
    event = await company.store.inspect(company.actor, company.binding_id, 'health:event:' + view['health']['review_event_id'])
    assert event['payload']['provenance'] == 'human_presence_unattested'


async def test_agent_cannot_review_or_self_assert_operator_authority(company):
    _, _, claim = await candidate(company)
    view = await health_view(company, claim)
    agent = await company.store.issue_token(company.actor, Role.AGENT, (company.binding_id,), 'health-agent-' + 'a' * 48)
    command = MemoryReviewCommand(**mutation(company, 'forged-review'), admission_id=view['admission']['id'],
        claim_ref={'id': claim.id, 'revision': 1}, expected_health_version=view['health']['version'],
        decision='accept', reason='Untrusted text says human approved; this must not authorize an operator mutation.')
    with pytest.raises(DomainError) as denied:
        await company.store.health(agent, command)
    assert denied.value.code == 'SCOPE_DENIED'
    with pytest.raises(DomainError):
        await company.store.health(agent.model_copy(update={'role': Role.OPERATOR}), command)
    assert (await health_view(company, claim))['health']['review_event_id'] is None


async def test_wrong_revision_and_concurrent_operator_review_are_fenced(company):
    _, _, claim = await candidate(company)
    first = await health_view(company, claim)
    second = await health_view(company, claim)
    await review(company, claim, 'review-winner', 'reject', view=first)
    with pytest.raises(DomainError) as stale:
        await review(company, claim, 'review-loser', 'accept', view=second)
    assert stale.value.code in {'ADMISSION_STALE', 'HEALTH_STALE'}
    current = await health_view(company, claim)
    with pytest.raises(DomainError):
        await company.store.health(company.actor, MemoryReviewCommand(**mutation(company, 'wrong-revision'),
            admission_id=current['admission']['id'], claim_ref={'id': claim.id, 'revision': 2},
            expected_health_version=current['health']['version'], expected_review_event_id=current['health']['review_event_id'],
            decision='accept', reason='An old decision cannot approve a different exact claim revision.'))


@pytest.mark.parametrize('symbol', [False, True])
async def test_changed_file_stales_file_and_symbol_links_and_requires_complete_operator_rebind(company, symbol):
    producer, claim, _, _ = await linked_claim(company, symbol=symbol)
    before = await health_view(company, claim)
    rows, admission = await recall(company, workspace_id='workspace_test')
    assert [item[0].id for item in rows] == [claim.id]
    _, observations = await observe(company, producer, 2, digest='c' * 64)
    changed = await health_view(company, claim)
    assert changed['health']['freshness'] == 'stale' and not changed['health']['reusable']
    assert changed['health']['version'] > before['health']['version']
    assert (await recall(company, 'changed-code', workspace_id='workspace_test'))[0] == []
    with pytest.raises(DomainError):
        await deliver(company, admission, selected=(claim.id,))
    with pytest.raises(DomainError):
        await review(company, claim, 'cannot-waive-code', 'accept')
    replacement = next(item['ref'] for item in observations['observations']
        if item['symbol_name'] == ('cache' if symbol else ''))
    await review(company, claim, 'rebind-current-code', 'accept', observations=[replacement])
    assert [item[0].id for item in (await recall(company, 'rebound-code', workspace_id='workspace_test'))[0]] == [claim.id]
    observer = await company.store.health_observer(producer, company.binding_id)
    path = observer['workspaces'][0]['linked_paths'][0]
    assert path['relative_path'] == 'src/cache.py'
    assert ('cache' in path['symbol_names']) == symbol
    assert claim.draft.statement not in json.dumps(observer)


async def test_missing_code_anchor_cannot_be_waived_and_old_sequence_cannot_revive_it(company):
    producer, claim, _, _ = await linked_claim(company)
    await observe(company, producer, 2, status='missing')
    with pytest.raises(DomainError):
        await observe(company, producer, 1)
    with pytest.raises(DomainError):
        await review(company, claim, 'missing-anchor-accept', 'accept')
    assert not (await health_view(company, claim))['health']['reusable']


async def test_identical_observation_and_unrelated_epoch_preserve_actual_admission(company):
    producer, claim, linked, command = await linked_claim(company)
    rows, admission = await recall(company, workspace_id='workspace_test')
    assert rows
    await observe(company, producer, 2)
    await company.store.register_binding(company.actor, 'Other', '/synthetic/other', 'other-health-epoch')
    assert (await deliver(company, admission, selected=(claim.id,)))['epoch'] >= admission.epoch
    assert await company.store.health(company.actor, command) == linked


async def test_ordinary_reject_does_not_hide_or_approve_required_rules(company):
    _, _, claim = await candidate(company)
    proposal = await company.store.propose_rule(company.actor, RuleProposal(
        binding_id=company.binding_id, idempotency_key='health-required', body='Always verify authorization.',
        required=True, selector=Selector(paths=('src/**',))))
    rule = await company.store.approve_rule(company.actor, RuleApproval(proposal_id=proposal['proposal_id'],
        expected_digest=proposal['digest'], scope=RuleScope.LOCAL_PROJECT, target_bindings=(company.binding_id,),
        target_set_revision=proposal['target_set_revision'], idempotency_key='health-required-approve'))
    await review(company, claim, 'reject-ordinary-not-rule', 'reject')
    assert [item.id for item in await company.store.rules(company.actor, company.binding_id)] == [rule.id]
    with pytest.raises(DomainError) as changed:
        await company.store.delivery(company.actor, company.binding_id, (), ())
    assert changed.value.code == 'CONTEXT_STALE'
    await company.store.delivery(company.actor, company.binding_id, (), ((rule.id, rule.revision, rule.digest),))


async def test_restore_quarantines_old_accept_and_requires_new_current_operator_review(company):
    _, _, claim = await candidate(company)
    await enabled(company)
    await review(company, claim, 'pre-restore-accept', 'accept')
    old_view = await health_view(company, claim)
    _, old_admission = await recall(company)
    async with company.store.pool.acquire() as connection:
        head = await connection.fetchval('SELECT journal_head FROM am_clock WHERE singleton')
    company.actor = await company.store.recover_after_restore(company.actor.id, 'health-restored-operator-' + 'r' * 48, head)
    restored = await health_view(company, claim)
    assert restored['health']['restore_unknown']
    assert restored['health']['review_event_id'] is None
    assert restored['health']['operator_review'] is None
    assert not (await company.store.health_policy(company.actor, company.binding_id))['enabled']
    assert (await recall(company, 'restored'))[0] == []
    discovery = await company.store.inspect(company.actor, company.binding_id, 'health:quarantine')
    assert {item['claim_id'] for item in discovery['items']} == {claim.id}
    assert discovery['items'][0]['ref'] == 'health:claim:' + claim.id
    with pytest.raises(DomainError):
        await deliver(company, old_admission, selected=(claim.id,))
    with pytest.raises(DomainError):
        await review(company, claim, 'old-admission-restore', 'accept', view=old_view)
    await review(company, claim, 'fresh-post-restore-accept', 'accept')
    assert not (await health_view(company, claim))['health']['restore_unknown']
    assert [item[0].id for item in (await recall(company, 'fresh-restored'))[0]] == [claim.id]


async def test_health_reason_and_assessment_payload_are_scrubbed_by_target_purge(company):
    _, _, claim = await candidate(company)
    decision = await review(company, claim, 'purge-review', 'reject')
    event = await company.store.inspect(company.actor, company.binding_id, 'health:event:' + decision.artifact_id)
    reason = event['reason_source_ref']
    assert reason
    await company.store.retract(company.actor, company.binding_id, claim.id, 'retract-health-target-before-purge')
    await company.store.purge(company.actor, company.binding_id, claim.id, 'purge-health-target')
    async with company.store.pool.acquire() as connection:
        row = await connection.fetchrow('SELECT body,state FROM am_sources WHERE id=$1', reason)
        assert row['body'] is None and row['state'] == 'purged'
        payload = await connection.fetchval('SELECT payload FROM am_health_events WHERE id=$1', decision.artifact_id)
        assert payload is None
    direct = await company.store.inspect(company.actor, company.binding_id, reason)
    assert 'body' not in direct


async def test_feedback_accept_requires_actual_matching_authorized_successor(company):
    source = await capture(company, key='feedback-target')
    feedback = await company.store.feedback(company.actor, FeedbackCommand(
        binding_id=company.binding_id, idempotency_key='feedback-candidate', target_ref=source.source_id,
        kind='correct', body='The independent correction must be explicitly authorized before resolving this candidate.'))
    before = await company.store.inspect(company.actor, company.binding_id, 'health:feedback:' + feedback.artifact_id)
    unrelated = await capture(company, key='unrelated-successor', body='OtherKey is retained offline.')
    with pytest.raises(DomainError):
        await company.store.health(company.actor, FeedbackResolutionCommand(**mutation(company, 'wrong-successor'),
            admission_id=before['admission']['id'], feedback_ref=feedback.artifact_id, expected_feedback_version=0,
            decision='accept', reason='A capture alone is not a target-matched correction.',
            successor_operation_id=unrelated.id))
    replacement = await company.store.correct(company.actor, company.binding_id, source.source_id,
        CaptureCommand(binding_id=company.binding_id, idempotency_key='actual-successor', origin_key='actual-successor',
            speaker='human', body='CacheKey is not retained offline.',
            coverage=CaptureCoverage(status='observed_window', original_bytes=len(b'CacheKey is not retained offline.'))))
    current = await company.store.inspect(company.actor, company.binding_id, 'health:feedback:' + feedback.artifact_id)
    resolved = await company.store.health(company.actor, FeedbackResolutionCommand(**mutation(company, 'accept-correction'),
        admission_id=current['admission']['id'], feedback_ref=feedback.artifact_id,
        expected_feedback_version=current['candidate']['version'], decision='accept',
        reason='The matching authorized correction now has a durable successor receipt.',
        successor_operation_id=replacement.id))
    assert resolved.state == 'health_recorded'
    after = await company.store.inspect(company.actor, company.binding_id, 'health:feedback:' + feedback.artifact_id)
    assert after['candidate']['version'] == 1
    assert (await company.store.source(company.actor, company.binding_id, replacement.source_id)).body == 'CacheKey is not retained offline.'


@pytest.mark.parametrize(('entry', 'snapshot'), [
    ('direct', None), ('direct', 'snapshot_beta'), ('pending', 'snapshot_beta'),
])
async def test_health_feedback_withholds_reason_and_target_outside_current_snapshot(company, entry, snapshot):
    await enabled(company)
    _, _, claim = await candidate(company, snapshot='snapshot_alpha')
    marker = 'PrivateAlphaCorrection is not available in another request snapshot.'
    feedback = await company.store.feedback(company.actor, FeedbackCommand(
        binding_id=company.binding_id, idempotency_key='scoped-feedback', target_ref=claim.id,
        kind='correct', body=marker))
    ref = 'health:feedback:' + feedback.artifact_id
    if entry == 'pending':
        page = await company.store.inspect(company.actor, company.binding_id, 'health', 'snapshot_alpha')
        ref = page['items'][0]['ref']
    allowed = await company.store.inspect(company.actor, company.binding_id, ref, 'snapshot_alpha')
    assert allowed['candidate']['body'] == marker
    assert allowed['candidate']['target_ref'] == claim.id
    withheld = await company.store.inspect(company.actor, company.binding_id, ref, snapshot)
    assert withheld['candidate']['body_unavailable'] is True
    assert withheld['candidate']['body'] is None
    assert 'target_ref' not in withheld['candidate']
    assert marker not in json.dumps(withheld)
    unrelated = await capture(company, key='global-feedback-target')
    global_feedback = await company.store.feedback(company.actor, FeedbackCommand(
        binding_id=company.binding_id, idempotency_key='global-feedback', target_ref=unrelated.source_id,
        kind='correct', body='Global correction remains visible in the current snapshot.'))
    global_view = await company.store.inspect(company.actor, company.binding_id,
        'health:feedback:' + global_feedback.artifact_id, snapshot)
    assert global_view['candidate']['body'] == 'Global correction remains visible in the current snapshot.'


@pytest.mark.parametrize('snapshot', [None, 'snapshot_beta'])
async def test_health_item_requires_callers_snapshot_before_returning_exact_claim_meaning(company, snapshot):
    await enabled(company)
    _, _, claim = await candidate(company, snapshot='snapshot_alpha')
    for sequence, boundary in enumerate(('start', 'end'), 1):
        await company.store.health(company.actor, SessionObservationCommand(
            **mutation(company, 'scoped-health-' + boundary), stream_id='stream_scoped', segment_id='segment_scoped',
            event_id='event_' + boundary, sequence=sequence, event=boundary, root_run_id='run_scoped',
            agent_path='agent_scoped', claim_refs=[{'id': claim.id, 'revision': claim.revision}],
            coverage='partial', gaps=['HOST_SESSION_WINDOW_UNOBSERVED']))
    page = await company.store.inspect(company.actor, company.binding_id, 'health', 'snapshot_alpha')
    ref = page['items'][0]['ref']
    allowed = await company.store.inspect(company.actor, company.binding_id, ref, 'snapshot_alpha')
    assert allowed['claims'][0]['statement'] == claim.draft.statement
    with pytest.raises(DomainError) as denied:
        await company.store.inspect(company.actor, company.binding_id, ref, snapshot)
    assert claim.draft.statement not in str(denied.value)


async def test_health_feedback_withdrawal_scrubs_fresh_view_and_fences_prior_admission(company):
    await enabled(company)
    source, _, claim = await candidate(company)
    marker = 'WithdrawnTargetCorrection must not escape through a health candidate.'
    feedback = await company.store.feedback(company.actor, FeedbackCommand(
        binding_id=company.binding_id, idempotency_key='withdrawn-health-feedback', target_ref=claim.id,
        kind='retract_request', body=marker))
    ref = 'health:feedback:' + feedback.artifact_id
    before = await company.store.inspect(company.actor, company.binding_id, ref)
    assert before['candidate']['body'] == marker
    await company.store.retract(company.actor, company.binding_id, source.source_id, 'withdraw-feedback-target-source')
    after = await company.store.inspect(company.actor, company.binding_id, ref)
    assert after['candidate']['body_unavailable'] is True
    assert after['candidate']['body'] is None and 'target_ref' not in after['candidate']
    assert marker not in json.dumps(after)
    with pytest.raises(DomainError):
        await company.store.health(company.actor, FeedbackResolutionCommand(
            **mutation(company, 'stale-feedback-decline'), admission_id=before['admission']['id'],
            feedback_ref=feedback.artifact_id, expected_feedback_version=before['candidate']['version'],
            decision='decline', reason='A withdrawn target cannot reuse the earlier disclosed admission.'))


async def test_late_capture_revises_same_session_work_and_fences_old_assessment(company):
    await enabled(company)
    _, _, claim = await candidate(company)
    end = SessionObservationCommand(**mutation(company, 'session-end'), stream_id='stream_test', segment_id='segment_test',
        event_id='end_event', sequence=2, event='end', root_run_id='run_test', agent_path='agent_test',
        origin_keys=['late-source'], claim_refs=[{'id': claim.id, 'revision': 1}],
        coverage='partial', gaps=['HOST_HUMAN_PRESENCE_UNATTESTED'])
    await company.store.health(company.actor, end)
    pending = await company.store.inspect(company.actor, company.binding_id, 'health')
    session = next(item for item in pending['items'] if item['state'] in {'pending', 'held'})
    first = await company.store.inspect(company.actor, company.binding_id, session['ref'])
    assert not first['coverage']['complete'] and 'SESSION_ORIGIN_PENDING' in first['coverage']['gaps']
    source = await company.store.capture(company.actor, CaptureCommand(binding_id=company.binding_id,
        idempotency_key='late-capture', origin_key='late-source', body='CacheKey was corrected: it is not retained offline.',
        speaker='human', root_run_id='run_test', agent_path='agent_test',
        coverage=CaptureCoverage(status='observed_window', original_bytes=len(b'CacheKey was corrected: it is not retained offline.'))))
    current = await company.store.inspect(company.actor, company.binding_id, session['ref'])
    assert current['pending_id'] == first['pending_id']
    assert current['health_manifest_digest'] != first['health_manifest_digest']
    assert source.source_id in {ref['id'] for ref in current['input_sources']}
    with pytest.raises(DomainError) as stale:
        await company.store.record(company.actor, HealthAssessmentCommand(**mutation(company, 'late-old-assessment'),
            admission_id=first['admission']['id'], pending_id=first['pending_id'],
            health_manifest_digest=first['health_manifest_digest'], input_sources=first['input_sources'],
            input_claims=first['input_claims'], assessments=[{'claim_ref': {'id': claim.id, 'revision': 1},
                'support': 'unknown', 'freshness': 'unknown', 'relevance': 'related',
                'reason': 'The old empty evidence window cannot assess a late correction.'}]))
    assert stale.value.code in {'ADMISSION_STALE', 'HEALTH_STALE'}
    assert (await health_view(company, claim))['health']['operator_review'] is None


async def test_health_of_unselected_asserted_relation_input_fences_reuse(company):
    from agents_memory.selection import ClaimJudgmentCommand
    _, _, left = await candidate(company, key='health-relation-left')
    _, _, right = await candidate(company, key='health-relation-right', body='OtherKey is retained offline.')
    _, _, asserted = await candidate(company, key='health-relation-asserted', body='AuditKey supports the retention policy.')
    view = await company.store.inspect(company.actor, company.binding_id, 'judgment',
        claim_ids=(left.id, right.id, asserted.id))
    result = await company.store.record(company.actor, ClaimJudgmentCommand(
        kind='claim_judgment', binding_id=company.binding_id, idempotency_key='health-relation',
        admission_id=view['admission_id'], manifest_digest=view['manifest_digest'], claims=view['claims'],
        sources=view['sources'], relations=[{'left_id': left.id, 'right_id': right.id, 'relation': 'supports',
            'reason': 'The inspected retention statements have explicit supporting lineage.'}],
        reason='Every asserted claim is an exact dependency, not only the displayed endpoints.'))
    assert result.state == 'candidate_ready'
    relations = await company.store.relations(company.actor, company.binding_id, (left.id,))
    assert relations
    rows, admission = await recall(company, 'relation-before-review')
    assert rows
    await review(company, asserted, 'reject-unselected-relation-input', 'reject')
    assert await company.store.relations(company.actor, company.binding_id, (left.id,)) == []
    disclosed = await company.store.inspect(company.actor, company.binding_id, relations[0].id)
    assert disclosed['left_id'] == left.id
    with pytest.raises(DomainError):
        await deliver(company, admission, selected=(left.id,), relations=(relations[0].id,))


async def test_health_policy_change_during_assessment_refuses_late_publication(company):
    producer, claim, _, _ = await linked_claim(company)
    await observe(company, producer, 2, digest='d' * 64)
    pending = await company.store.inspect(company.actor, company.binding_id, 'health')
    work = await company.store.inspect(company.actor, company.binding_id, pending['items'][0]['ref'])
    await company.store.health(company.actor, HealthPolicyCommand(**mutation(company, 'disable-health-during-work'),
        expected_policy_revision=1, enabled=False))
    with pytest.raises(DomainError):
        await company.store.record(company.actor, HealthAssessmentCommand(**mutation(company, 'late-policy-work'),
            admission_id=work['admission']['id'], pending_id=work['pending_id'],
            health_manifest_digest=work['health_manifest_digest'], input_sources=work['input_sources'],
            input_claims=work['input_claims'], assessments=[{'claim_ref': {'id': claim.id, 'revision': 1},
                'support': 'unknown', 'freshness': 'unknown', 'relevance': 'related',
                'reason': 'Policy authorization changed while this assessment was in flight.'}]))
    assert not (await health_view(company, claim))['health']['reusable']


async def test_unchanged_machine_support_cannot_clear_code_or_operator_reject(company):
    producer, claim, _, _ = await linked_claim(company)
    await observe(company, producer, 2, digest='e' * 64)
    pending = await company.store.inspect(company.actor, company.binding_id, 'health')
    work = await company.store.inspect(company.actor, company.binding_id, pending['items'][0]['ref'])
    source = work['sources'][0]
    assessment = HealthAssessmentCommand(**mutation(company, 'positive-not-authority'),
        admission_id=work['admission']['id'], pending_id=work['pending_id'],
        health_manifest_digest=work['health_manifest_digest'], input_sources=work['input_sources'],
        input_claims=work['input_claims'], assessments=[{'claim_ref': {'id': claim.id, 'revision': 1},
            'support': 'supported', 'freshness': 'observed_current', 'relevance': 'related',
            'reason': 'The captured original supports this statement but cannot reverse operator or code authority.',
            'evidence': [{'source_ref': source['source_ref'], 'byte_start': 0,
                'byte_end': len(source['body'].encode()), 'quote': source['body']}]}])
    await review(company, claim, 'reject-before-machine', 'reject')
    with pytest.raises(DomainError):
        await company.store.record(company.actor, assessment)
    inspected = await health_view(company, claim)
    assert inspected['health']['operator_review'] == 'reject'
    assert inspected['health']['freshness'] == 'stale'
    assert not inspected['health']['reusable']
    recalled, _ = await recall(company, 'after-late-positive-assessment')
    assert claim.id not in {item.id for item in recalled}


async def test_withdrawing_current_accept_invalidates_reuse_not_independent_facts(company):
    original, _, claim = await candidate(company)
    unrelated_source, _, unrelated = await candidate(company, key='withdraw-unrelated',
        body='CacheKey has an independent audit owner.')
    accepted = await review(company, claim, 'withdraw-current-accept', 'accept')
    before = await health_view(company, claim)
    unrelated_before = await health_view(company, unrelated)
    rows, admission = await recall(company, 'before-accept-withdrawal')
    assert {row[0].id for row in rows} == {claim.id, unrelated.id}
    assert before['health']['review_event_id'] == accepted.artifact_id
    assert before['health']['operator_review'] == 'accept' and before['health']['reusable']

    await company.store.retract(company.actor, company.binding_id, accepted.artifact_id, 'withdraw-accept-event')

    after = await health_view(company, claim)
    assert after['health']['version'] > before['health']['version']
    assert after['health']['review_event_id'] is None
    assert after['health']['operator_review'] is None
    assert after['health']['needs_review'] and not after['health']['reusable']
    event = await company.store.inspect(company.actor, company.binding_id, 'health:event:' + accepted.artifact_id)
    assert event['state'] == 'retracted' and event['payload'] is None
    assert event['reason_source_ref'] is None
    assert (await company.store.claim(company.actor, company.binding_id, claim.id)).draft == claim.draft
    assert (await company.store.source(company.actor, company.binding_id, original.source_id)).body == claim.draft.statement
    assert (await health_view(company, unrelated))['health'] == unrelated_before['health']
    assert (await company.store.source(company.actor, company.binding_id, unrelated_source.source_id)).body == unrelated.draft.statement
    assert {row[0].id for row in (await recall(company, 'after-accept-withdrawal'))[0]} == {unrelated.id}
    with pytest.raises(DomainError):
        await deliver(company, admission, selected=(claim.id,))
    with pytest.raises(DomainError):
        await review(company, claim, 'reuse-withdrawn-review-admission', 'accept', view=before)
    await review(company, claim, 'fresh-review-after-withdrawal', 'accept')
    assert (await health_view(company, claim))['health']['reusable']


@pytest.mark.parametrize('withdraw_boundary', ['start', 'end'])
async def test_withdrawing_resolved_observed_segment_invalidates_parent_and_child_assessment(company, withdraw_boundary):
    await enabled(company)
    original, _, claim = await candidate(company)
    unrelated_source, _, unrelated = await candidate(company, key='session-independent',
        body='CacheKey has an independent audit owner.')
    evidence_body = claim.draft.statement
    evidence = await company.store.capture(company.actor, CaptureCommand(
        binding_id=company.binding_id, idempotency_key='session-evidence', origin_key='session-evidence',
        body=evidence_body, speaker='human', root_run_id='run_withdrawal', agent_path='agent_withdrawal',
        coverage=CaptureCoverage(status='observed_window', original_bytes=len(evidence_body.encode()))))
    boundaries = {}
    for sequence, boundary in enumerate(('start', 'end'), 1):
        boundaries[boundary] = await company.store.health(company.actor, SessionObservationCommand(
            **mutation(company, 'resolved-segment-' + boundary), stream_id='stream_withdrawal',
            segment_id='segment_withdrawal', event_id='event_' + boundary, sequence=sequence,
            event=boundary, root_run_id='run_withdrawal', agent_path='agent_withdrawal',
            source_refs=[{'id': evidence.source_id, 'revision': 1}],
            claim_refs=[{'id': claim.id, 'revision': claim.revision}], coverage='observed_segment'))
    pending = await company.store.inspect(company.actor, company.binding_id, 'health')
    assert len(pending['items']) == 1
    work_ref = pending['items'][0]['ref']
    work = await company.store.inspect(company.actor, company.binding_id, work_ref)
    assert work['coverage']['complete'] and not work['coverage']['gaps']
    assert work['input_sources'] == [{'id': evidence.source_id, 'revision': 1}]
    assert work['input_claims'] == [{'id': claim.id, 'revision': claim.revision}]
    source = work['sources'][0]
    assessed = await company.store.record(company.actor, HealthAssessmentCommand(
        **mutation(company, 'resolved-segment-assessment'), admission_id=work['admission']['id'],
        pending_id=work['pending_id'], health_manifest_digest=work['health_manifest_digest'],
        input_sources=work['input_sources'], input_claims=work['input_claims'],
        assessments=[{'claim_ref': {'id': claim.id, 'revision': claim.revision},
            'support': 'supported', 'freshness': 'observed_current', 'relevance': 'related',
            'reason': 'The exact bounded observed source supports this claim without asserting human approval.',
            'evidence': [{'source_ref': source['source_ref'], 'byte_start': source['byte_start'],
                'byte_end': source['byte_end'], 'quote': source['body']}]}]))
    before = await health_view(company, claim)
    unrelated_before = await health_view(company, unrelated)
    assert before['health']['support'] == 'supported'
    assert before['health']['freshness'] == 'observed_current'
    assert before['health']['operator_review'] is None and before['health']['reusable']
    child_id = before['health']['assessment_event_id']
    assert child_id and child_id != assessed.artifact_id
    child = await company.store.inspect(company.actor, company.binding_id, 'health:event:' + child_id)
    parent = await company.store.inspect(company.actor, company.binding_id, 'health:event:' + assessed.artifact_id)
    assert child['payload']['assessment_event_id'] == assessed.artifact_id
    assert parent['payload']['coverage']['complete']
    async with company.store.pool.acquire() as connection:
        assert await connection.fetchval('SELECT state FROM am_pending_judgments WHERE id=$1', work['pending_id']) == 'resolved'
    _, admission = await recall(company, 'resolved-segment-before-withdrawal')

    await company.store.retract(company.actor, company.binding_id, boundaries[withdraw_boundary].artifact_id,
        'withdraw-resolved-segment-boundary')

    after = await health_view(company, claim)
    assert after['health']['version'] > before['health']['version']
    assert after['health']['assessment_event_id'] is None
    assert after['health']['support'] == 'unknown'
    assert after['health']['freshness'] == 'unknown'
    assert after['health']['needs_review'] and not after['health']['reusable']
    async with company.store.pool.acquire() as connection:
        assert await connection.fetchval('SELECT state FROM am_pending_judgments WHERE id=$1', work['pending_id']) == 'retracted'
    for event_id in (assessed.artifact_id, child_id):
        event = await company.store.inspect(company.actor, company.binding_id, 'health:event:' + event_id)
        assert event['state'] == 'retracted' and event['payload'] is None
        assert event['reason_source_ref'] is None
    assert (await company.store.inspect(company.actor, company.binding_id, 'health'))['items'] == []
    with pytest.raises(DomainError):
        await company.store.inspect(company.actor, company.binding_id, work_ref)
    with pytest.raises(DomainError):
        await deliver(company, admission, selected=(claim.id,))
    with pytest.raises(DomainError):
        await review(company, claim, 'withdrawn-segment-old-review', 'accept', view=before)
    for captured in (original, evidence, unrelated_source):
        expected_body = unrelated.draft.statement if captured.source_id == unrelated_source.source_id else claim.draft.statement
        assert (await company.store.source(company.actor, company.binding_id, captured.source_id)).body == expected_body
    assert (await company.store.claim(company.actor, company.binding_id, claim.id)).draft == claim.draft
    assert (await health_view(company, unrelated))['health'] == unrelated_before['health']
    assert {row[0].id for row in (await recall(company, 'resolved-segment-after-withdrawal'))[0]} == {unrelated.id}


@pytest.mark.parametrize('withdraw_target', ['feedback', 'resolution_reason'])
async def test_feedback_disposition_survives_private_reason_erasure(company, withdraw_target):
    original, _, claim = await candidate(company)
    feedback_body = 'Private correction candidate: the retention statement needs independent review.'
    resolution_reason = 'Private operator rationale: decline this unsubstantiated correction candidate.'
    feedback = await company.store.feedback(company.actor, FeedbackCommand(
        binding_id=company.binding_id, idempotency_key='private-feedback',
        target_ref=claim.id, kind='correct', body=feedback_body))
    view = await company.store.inspect(company.actor, company.binding_id, 'health:feedback:' + feedback.artifact_id)
    resolution = await company.store.health(company.actor, FeedbackResolutionCommand(
        **mutation(company, 'private-feedback-disposition'), admission_id=view['admission']['id'],
        feedback_ref=feedback.artifact_id, expected_feedback_version=view['candidate']['version'],
        decision='decline', reason=resolution_reason))
    event_ref = 'health:event:' + resolution.artifact_id
    before = await company.store.inspect(company.actor, company.binding_id, event_ref)
    reason_ref = before['reason_source_ref']
    assert reason_ref
    assert (await company.store.source(company.actor, company.binding_id, reason_ref)).body == resolution_reason
    assert before['payload']['decision'] == 'decline'
    assert feedback_body not in json.dumps(before) and resolution_reason not in json.dumps(before)
    target = feedback.artifact_id if withdraw_target == 'feedback' else reason_ref

    await company.store.retract(company.actor, company.binding_id, target, 'retract-private-feedback-data')
    await company.store.purge(company.actor, company.binding_id, target, 'purge-private-feedback-data')

    reason = await company.store.inspect(company.actor, company.binding_id, reason_ref)
    assert reason['state'] == 'purged' and 'body' not in reason
    async with company.store.pool.acquire() as connection:
        row = await connection.fetchrow('SELECT body,state FROM am_sources WHERE id=$1', reason_ref)
        assert row['body'] is None and row['state'] == 'purged'
    after = await company.store.inspect(company.actor, company.binding_id, event_ref)
    assert after['state'] == 'active'
    assert after['event_kind'] == 'feedback_resolution'
    assert after['payload'] == before['payload']
    assert after['authority'] == before['authority']
    assert after['payload']['successor_operation_id'] is None
    assert after['payload']['provenance'] == 'human_presence_unattested'
    current = await company.store.inspect(company.actor, company.binding_id, 'health:feedback:' + feedback.artifact_id)
    assert current['candidate']['resolution_event_id'] == resolution.artifact_id
    assert current['candidate']['version'] == view['candidate']['version'] + 1
    if withdraw_target == 'feedback':
        assert current['candidate']['body'] is None and current['candidate']['body_unavailable']
        async with company.store.pool.acquire() as connection:
            row = await connection.fetchrow('SELECT reason,source_id FROM am_feedback WHERE id=$1', feedback.artifact_id)
            assert row['reason'] is None
            assert await connection.fetchval('SELECT body FROM am_sources WHERE id=$1', row['source_id']) is None
    else:
        assert current['candidate']['body'] == feedback_body
    assert resolution_reason not in json.dumps(after)
    assert (await company.store.source(company.actor, company.binding_id, original.source_id)).body == claim.draft.statement
    assert (await health_view(company, claim))['health']['reusable']
    assert [row[0].id for row in (await recall(company, 'after-feedback-private-erasure'))[0]] == [claim.id]


async def test_disabled_policy_blocks_code_recall_delivery_and_rebinding_not_ordinary_or_required_rules(company):
    _, linked, _, _ = await linked_claim(company)
    ordinary_source, _, ordinary = await candidate(company, key='policy-independent',
        body='CacheKey has an independent audit owner.')
    proposal = await company.store.propose_rule(company.actor, RuleProposal(
        binding_id=company.binding_id, idempotency_key='policy-required-rule', body='Always verify authorization.',
        required=True, selector=Selector(paths=('src/**',))))
    rule = await company.store.approve_rule(company.actor, RuleApproval(
        proposal_id=proposal['proposal_id'], expected_digest=proposal['digest'], scope=RuleScope.LOCAL_PROJECT,
        target_bindings=(company.binding_id,), target_set_revision=proposal['target_set_revision'],
        idempotency_key='policy-required-rule-approve'))
    rule_versions = ((rule.id, rule.revision, rule.digest),)
    before = await health_view(company, linked)
    observation = before['code_observations'][0]['ref']
    ordinary_before = await health_view(company, ordinary)
    rows, admission = await recall(company, 'policy-enabled-recall', workspace_id='workspace_test')
    assert {row[0].id for row in rows} == {linked.id, ordinary.id}
    assert before['health']['reusable']

    await company.store.health(company.actor, HealthPolicyCommand(
        **mutation(company, 'disable-health-code-usage'), expected_policy_revision=1, enabled=False))

    assert not (await company.store.health_policy(company.actor, company.binding_id))['enabled']
    disabled = await health_view(company, linked)
    assert not disabled['health']['reusable']
    for workspace_id in (None, 'workspace_test'):
        current_rows, current_admission = await recall(company, 'disabled-policy-' + str(workspace_id),
            workspace_id=workspace_id)
        assert [row[0].id for row in current_rows] == [ordinary.id]
        await company.store.delivery(company.actor, company.binding_id, (), rule_versions,
            nonmodel_admission=current_admission, selected_claim_ids=(ordinary.id,))
    with pytest.raises(DomainError):
        await company.store.delivery(company.actor, company.binding_id, (), rule_versions,
            nonmodel_admission=admission, selected_claim_ids=(linked.id,))
    with pytest.raises(DomainError):
        await review(company, linked, 'disabled-policy-old-rebind', 'accept', view=before, observations=[observation])
    with pytest.raises(DomainError):
        await review(company, linked, 'disabled-policy-fresh-rebind', 'accept', view=disabled, observations=[observation])
    with pytest.raises(DomainError):
        await review(company, linked, 'disabled-policy-cannot-drop-code', 'accept')
    nominated = await health_view(company, ordinary, observation)
    with pytest.raises(DomainError):
        await company.store.record(company.actor, CodeLinkCommand(
            **mutation(company, 'disabled-policy-cannot-add-code'), admission_id=nominated['admission']['id'],
            claim_ref={'id': ordinary.id, 'revision': ordinary.revision},
            expected_health_version=nominated['health']['version'], observation_refs=[observation],
            reason='Disabled observation policy must not authorize a new code dependency.'))
    assert (await health_view(company, linked))['health'] == disabled['health']
    assert (await health_view(company, ordinary))['health'] == ordinary_before['health']
    assert (await company.store.source(company.actor, company.binding_id, ordinary_source.source_id)).body == ordinary.draft.statement
    assert [item.id for item in await company.store.rules(company.actor, company.binding_id)] == [rule.id]
    with pytest.raises(DomainError):
        await company.store.delivery(company.actor, company.binding_id, (), ())
    await company.store.delivery(company.actor, company.binding_id, (), rule_versions)


@pytest.mark.parametrize('workspace_id', [None, 'workspace_other'])
async def test_two_stage_context_keeps_global_fact_when_touching_relation_is_outside_workspace(company, workspace_id):
    from agents_memory.selection import ClaimJudgmentCommand

    producer, linked, _, _ = await linked_claim(company)
    _, _, global_claim = await candidate(company, key='workspace-global-fact',
        body='CacheKey is retained offline as a global independent fact.')
    if workspace_id is not None:
        await company.store.health(company.actor, HealthWorkspaceCommand(
            **mutation(company, 'register-other-workspace'), workspace_id=workspace_id,
            expected_workspace_revision=0, root_fingerprint='d' * 64,
            producer_credential_id=producer.credential_id))
    view = await company.store.inspect(company.actor, company.binding_id, 'judgment',
        claim_ids=(global_claim.id, linked.id))
    await company.store.record(company.actor, ClaimJudgmentCommand(
        kind='claim_judgment', binding_id=company.binding_id, idempotency_key='workspace-touching-relation',
        admission_id=view['admission_id'], manifest_digest=view['manifest_digest'], claims=view['claims'],
        sources=view['sources'], relations=[{'left_id': global_claim.id, 'right_id': linked.id,
            'relation': 'supports', 'reason': 'The explicit relation has a workspace-scoped input.'}],
        reason='The exact global and code-linked source inputs were inspected together.'))
    command = ContextCommand(binding_id=company.binding_id, query='CacheKey offline', code_workspace_id=workspace_id)
    delivered = await judged_context(company, company.actor, command)
    assert delivered['refs'] == [global_claim.id]
    assert global_claim.draft.statement in delivered['context']
    assert linked.draft.statement not in delivered['context']
    assert delivered['health']['ordinary_claims'] == delivered['health']['reusable'] == 1
    matched = await judged_context(company, company.actor, command.model_copy(update={'code_workspace_id': 'workspace_test'}))
    assert set(matched['refs']) == {global_claim.id, linked.id}
    pending = await company.application.context(company.actor, command.model_copy(update={'code_workspace_id': 'workspace_test'}))
    await observe(company, producer, 2, digest='c' * 64)
    with pytest.raises(DomainError):
        await company.application.context(company.actor, ContextCommand(
            binding_id=company.binding_id, query=command.query, code_workspace_id='workspace_test',
            admission_id=pending['admission_id'],
            relevance=[{'claim_id': item['claim_id'], 'relevant': True,
                'reason': 'The old relation input cannot bypass its code revision fence.'}
                for item in pending['candidate_manifest']],
        ))
    unrelated = await judged_context(company, company.actor, command)
    assert unrelated['refs'] == [global_claim.id] and unrelated['health']['withheld'] == 0
    quarantined = await judged_context(company, company.actor, command.model_copy(update={'code_workspace_id': 'workspace_test'}))
    assert quarantined['refs'] == [global_claim.id] and quarantined['partial'] is True
    assert quarantined['health']['withheld'] == 1


async def test_quarantined_current_claims_are_partial_and_discoverable_without_exposing_other_snapshots(company):
    await enabled(company)
    claims = []
    for index in range(3):
        _, _, claim = await candidate(company, key='quarantined-global-' + str(index),
            body=f'CacheKey is retained offline for independent purpose {index}.')
        await review(company, claim, 'quarantine-accept-' + str(index), 'accept')
        accepted = await health_view(company, claim)
        await company.store.retract(company.actor, company.binding_id, accepted['health']['review_event_id'],
            'withdraw-quarantine-accept-' + str(index))
        claims.append(claim)
    _, _, scoped = await candidate(company, key='quarantined-alpha', snapshot='snapshot_alpha')
    await review(company, scoped, 'quarantine-alpha-accept', 'accept')
    accepted = await health_view(company, scoped)
    await company.store.retract(company.actor, company.binding_id, accepted['health']['review_event_id'],
        'withdraw-quarantine-alpha-accept')
    request = ContextCommand(binding_id=company.binding_id, query='CacheKey offline', snapshot='snapshot_beta')
    withheld = await company.application.context(company.actor, request)
    assert withheld['status'] == 'partial' and withheld['partial'] is True
    assert withheld['refs'] == [] and withheld['candidate_manifest'] == []
    assert withheld['health']['withheld'] == 3
    discovered, cursor = [], 0
    while True:
        page = await company.store.inspect(company.actor, company.binding_id, 'health:quarantine',
            'snapshot_beta', byte_start=cursor, max_bytes=512)
        assert len(json.dumps(page, ensure_ascii=False, separators=(',', ':')).encode()) <= 512
        discovered.extend(page['items'])
        if page['next_byte'] is None:
            break
        assert page['next_byte'] > cursor
        cursor = page['next_byte']
    assert {item['claim_id'] for item in discovered} == {claim.id for claim in claims}
    assert len(discovered) == len(claims)
    assert scoped.id not in json.dumps(discovered)
    assert all(item['ref'] == 'health:claim:' + item['claim_id'] for item in discovered)
    current = await company.store.inspect(company.actor, company.binding_id, discovered[0]['ref'], 'snapshot_beta')
    recovered_claim = next(claim for claim in claims if claim.id == discovered[0]['claim_id'])
    await review(company, recovered_claim, 'fresh-discovered-health-review', 'accept', view=current)
    delivered = await judged_context(company, company.actor, request)
    assert delivered['refs'] == [recovered_claim.id]
    assert delivered['partial'] is True and delivered['health']['withheld'] == 2
    assert delivered['coverage']['unclassified_sources'] == 0


async def test_actual_producer_partial_segments_finish_bounded_work_without_claiming_freshness(company, tmp_path, monkeypatch):
    import asyncio
    from pathlib import Path
    from urllib.parse import urlsplit

    from test_evaluation_gateway import actual_upstream

    from agents_memory import health_producer, hosts

    await enabled(company)
    _, _, claim = await candidate(company)
    company.store.settings = company.store.settings.model_copy(update={'queue_limit': 1})
    home, project = tmp_path / 'isolated-home', tmp_path / 'observed-project'
    home.mkdir(mode=0o700)
    project.mkdir()
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('XDG_CONFIG_HOME', str(home / '.config'))
    async with actual_upstream(company, tmp_path) as (agent, producer):
        principal = await company.store.authenticate(producer.token_file.read_text())
        settings = company.store.settings.model_copy(update={'port': urlsplit(agent.endpoint.base_url).port})
        installed = hosts.install_host(settings, project, company.binding_id, 'omp',
            agent.token_file, producer.token_file, strict=False, prompt_recall=True)
        receipt = hosts.load_receipt(Path(installed['receipt']))
        config, registration = health_producer.prepare_health_workspace(receipt, 'workspace_real_segments',
            principal.credential_id, expected_binding_revision=1, expected_workspace_revision=0,
            idempotency_key='real-segment-workspace', next_agent=True)
        await company.store.health(company.actor, registration)
        health_producer.configure_health_workspace(receipt, config)
        await asyncio.to_thread(health_producer.observe_health_workspace, receipt)
        client = health_producer._client(receipt)
        identity = {'key': 'a' * 64, 'root': 'run_bounded', 'path': 'b' * 64, 'limited': False}
        async def emit(event, **kwargs):
            result = await asyncio.to_thread(health_producer.observe_host_session, receipt, identity,
                event, client=client, **kwargs)
            assert result['state'] == 'durably_spooled', result
        await emit('session_start')
        command = CaptureCommand(binding_id=company.binding_id, idempotency_key='real-segment-capture',
            origin_key='real-segment-origin', body='CacheKey still needs independent freshness review.', speaker='human',
            root_run_id=identity['root'], agent_path=identity['path'])
        captured = await asyncio.to_thread(client.request, '/api/capture', command.model_dump(mode='json'))
        assert captured['effect'] == 'committed'
        await emit('capture_origin', origin_key=command.origin_key)
        await emit('session_shutdown')
        pending = await company.store.inspect(company.actor, company.binding_id, 'health')
        work = await company.store.inspect(company.actor, company.binding_id, pending['items'][0]['ref'])
        assert not work['coverage']['complete']
        assert 'HOST_SESSION_WINDOW_UNOBSERVED' in work['coverage']['gaps']
        assert claim.id in {item['id'] for item in work['input_claims']}
        operation = await company.store.record(company.actor, HealthAssessmentCommand(
            **mutation(company, 'bounded-partial-work'), admission_id=work['admission']['id'],
            pending_id=work['pending_id'], health_manifest_digest=work['health_manifest_digest'],
            input_sources=work['input_sources'], input_claims=work['input_claims'],
            assessments=[{'claim_ref': ref, 'support': 'unknown', 'freshness': 'unknown', 'relevance': 'related',
                'reason': 'Only the explicit producer segment was observed; freshness is not established.'}
                for ref in work['input_claims']]))
        history = await company.store.inspect(company.actor, company.binding_id, 'health:event:' + operation.artifact_id)
        assert history['payload']['coverage'] == work['coverage']
        remaining = await company.store.inspect(company.actor, company.binding_id, 'health')
        assert work['pending_id'] not in {item['pending_id'] for item in remaining['items']}
        state = (await health_view(company, claim))['health']
        assert state['support'] == state['freshness'] == 'unknown' and state['operator_review'] is None
        await emit('session_start')
        await emit('session_shutdown')
        next_work = await company.store.inspect(company.actor, company.binding_id, 'health')
        assert len(next_work['items']) == 1 and next_work['items'][0]['pending_id'] != work['pending_id']


async def test_refresh_conflict_work_has_exact_operator_unknown_disposition_and_reopen(company):
    from agents_memory.health import HEALTH_ADAPTER

    await enabled(company)
    _, _, claim = await candidate(company, snapshot='snapshot_alpha')
    await company.store.health(company.actor, SessionObservationCommand(
        **mutation(company, 'conflicted-session-end'), stream_id='stream_conflict', segment_id='segment_conflict',
        event_id='end_conflict', sequence=1, event='end', root_run_id='run_conflict', agent_path='agent_conflict',
        origin_keys=['conflicted-origin'], claim_refs=[{'id': claim.id, 'revision': claim.revision}],
        coverage='partial', gaps=['HOST_SESSION_WINDOW_UNOBSERVED']))
    await company.store.capture(company.actor, CaptureCommand(binding_id=company.binding_id,
        idempotency_key='conflicted-late-capture', origin_key='conflicted-origin', snapshot='snapshot_beta',
        body='CacheKey has incompatible snapshot evidence.', speaker='human', root_run_id='run_conflict', agent_path='agent_conflict'))
    page = await company.store.inspect(company.actor, company.binding_id, 'health', 'snapshot_alpha')
    item = page['items'][0]
    command = {**mutation(company, 'operator-close-unknown'), 'kind': 'health_work_disposition',
        'pending_id': item['pending_id'], 'expected_pending_revision': item['health_revision'],
        'snapshot': 'snapshot_alpha', 'decision': 'close_unknown',
        'reason': 'The conflicting inputs cannot establish an assessment; retain unknown, not success.'}
    with pytest.raises(DomainError):
        await company.store.health(company.actor, HEALTH_ADAPTER.validate_python({**command, 'snapshot': 'snapshot_beta'}))
    await company.store.health(company.actor, HEALTH_ADAPTER.validate_python(command))
    closed = await company.store.inspect(company.actor, company.binding_id, item['ref'], 'snapshot_alpha')
    assert closed['state'] == 'resolved' and closed['disposition'] == 'close_unknown'
    assert closed['assessment_complete'] is False and closed['admission'] is None
    assert (await company.store.stats(company.actor, company.binding_id, 'snapshot_alpha'))['health']['closed_unknown_work'] == 1
    assert (await company.store.stats(company.actor, company.binding_id, 'snapshot_beta'))['health']['closed_unknown_work'] == 0
    with pytest.raises(DomainError):
        await company.store.health(company.actor, HEALTH_ADAPTER.validate_python(
            {**command, 'idempotency_key': 'stale-work-disposition'}))
    reopen = {**command, 'idempotency_key': 'operator-reopen-unknown', 'decision': 'reopen',
        'expected_pending_revision': closed['health_revision']}
    await company.store.health(company.actor, HEALTH_ADAPTER.validate_python(reopen))
    current = await company.store.inspect(company.actor, company.binding_id, item['ref'], 'snapshot_alpha')
    assert current['coverage']['complete'] is False and 'SESSION_REFRESH_INCOMPLETE' in current['coverage']['gaps']
    assert (await health_view(company, claim))['health']['operator_review'] is None


@pytest.mark.parametrize('surface', ['denominator', 'operator_accept'])
async def test_current_health_qualification_excludes_obsolete_policy_but_preserves_independent_claim(company, surface):
    await enabled(company)
    _, _, obsolete = await candidate(company, key='health-obsolete-policy')
    _, _, current = await candidate(company, key='health-current-policy',
        body='AuditKey has an independent expiry owner.')
    async with company.store.pool.acquire() as connection:
        await connection.execute('''UPDATE am_source_selections SET policy_revision=$2
            WHERE id=(SELECT selection_id FROM am_claims WHERE id=$1)''', obsolete.id, '0' * 64)
    stats = await company.store.stats(company.actor, company.binding_id)
    assert stats['coverage']['unclassified_sources'] == 1
    assert stats['coverage']['incomplete_sources'] == 1
    if surface == 'denominator':
        assert stats['health']['ordinary_claims'] == 1
        assert stats['health']['reusable'] == 1
    else:
        with pytest.raises(DomainError):
            await review(company, obsolete, 'deny-obsolete-policy-accept', 'accept')
        assert (await health_view(company, obsolete))['health']['operator_review'] is None
    await review(company, current, 'accept-independent-current-policy', 'accept')
    assert (await health_view(company, current))['health']['operator_review'] == 'accept'
