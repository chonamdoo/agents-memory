from __future__ import annotations

import hashlib
import json

import pytest
from test_company_authority import capture
from test_company_authority import company as company

from agents_memory.domain import DomainError, Role, RuleApproval, RuleProposal, RuleScope, Selector


async def read_complete(company, actor, ref):
    cursor, parts, digest = 0, [], None
    while True:
        page = await company.store.inspect(actor, company.binding_id, ref, byte_start=cursor, max_bytes=512)
        window = page['draft_window']
        assert window['byte_start'] == cursor
        assert len(window['body'].encode()) <= 512
        assert window['digest'] == (digest or window['digest'])
        digest = window['digest']
        parts.append(window['body'].encode())
        if window['next_byte'] is None:
            raw = b''.join(parts)
            assert hashlib.sha256(raw).hexdigest() == digest
            assert len(raw) == window['total_bytes']
            return json.loads(raw)
        assert window['next_byte'] > cursor
        cursor = window['next_byte']


async def make_proposal(company, key):
    first = await capture(company, key=key + '-first', body='The project requires independent authorization.')
    second = await capture(company, key=key + '-second', body='Generated test data is exempt from deployment.')
    body = '이 규칙은 독립적인 승인과 정확한 근거를 확인한 뒤 적용한다. ' * 180
    proposal = await company.store.propose_rule(company.actor, RuleProposal(
        binding_id=company.binding_id, idempotency_key=key, body=body,
        selector=Selector(paths=('src/**', 'tests/**')), required=False,
        exceptions=('Generated test data is exempt.', 'Archived documentation is read-only.'),
        source_ids=(first.source_id, second.source_id)))
    return proposal, body, first, second


async def test_ref_only_inspection_reads_entire_utf8_meaning_and_approves_exact_content(company):
    proposal, body, first, second = await make_proposal(company, 'complete-proposal')
    independent = await company.store.issue_token(company.actor, Role.OPERATOR, (company.binding_id,),
        'independent-proposal-approver-' + 'p' * 48)
    inspected = await read_complete(company, independent, proposal['proposal_id'])
    assert len(body.encode()) > 4096
    assert inspected['body'] == body
    assert inspected['exceptions'] == ['Generated test data is exempt.', 'Archived documentation is read-only.']
    assert inspected['selector']['paths'] == ['src/**', 'tests/**']
    assert inspected['required'] is False
    assert {ref['id'] for ref in inspected['input_sources']} == {
        first.source_id, second.source_id, inspected['body_source_ref']['id']}
    assert all(ref['revision'] == 1 for ref in inspected['input_sources'])
    assert inspected['digest'] == inspected['proposal_digest'] == proposal['digest']
    assert inspected['inspection_authority']['credential_id'] == independent.credential_id
    approved = await company.store.approve_rule(independent, RuleApproval(
        proposal_id=inspected['proposal_id'], expected_digest=inspected['proposal_digest'],
        scope=RuleScope.LOCAL_PROJECT, target_bindings=(company.binding_id,),
        target_set_revision=inspected['target_set_revision'], idempotency_key='approve-inspected-exactly'))
    assert approved.body == inspected['body']
    assert list(approved.exceptions) == inspected['exceptions']
    active = await read_complete(company, independent, approved.id)
    assert active['body'] == body and active['proposal_digest'] == proposal['digest']
    assert active['digest'] == approved.digest


async def test_proposal_pages_bind_actor_and_deny_other_project(company):
    proposal, _, _, _ = await make_proposal(company, 'proposal-actor')
    other = await company.store.register_binding(company.actor, 'Other', '/synthetic/proposal-other', 'proposal-other')
    denied_actor = await company.store.issue_token(company.actor, Role.AGENT, (other.id,), 'proposal-other-agent-' + 'o' * 48)
    with pytest.raises(DomainError) as denied:
        await company.store.inspect(denied_actor, company.binding_id, proposal['proposal_id'], max_bytes=512)
    assert denied.value.code == 'SCOPE_DENIED'
    permitted = await company.store.issue_token(company.actor, Role.AGENT, (company.binding_id,), 'proposal-reader-' + 'q' * 48)
    owner_page = await company.store.inspect(company.actor, company.binding_id, proposal['proposal_id'], max_bytes=512)
    agent_page = await company.store.inspect(permitted, company.binding_id, proposal['proposal_id'], max_bytes=512)
    assert owner_page['draft_window']['digest'] != agent_page['draft_window']['digest']


async def test_dependency_revision_change_between_pages_refuses_inspection_and_old_approval(company):
    proposal, _, first, _ = await make_proposal(company, 'proposal-changing-input')
    page = await company.store.inspect(company.actor, company.binding_id, proposal['proposal_id'], max_bytes=512)
    assert page['draft_window']['next_byte'] is not None
    async with company.store.pool.acquire() as connection:
        await connection.execute('UPDATE am_sources SET revision=revision+1 WHERE id=$1', first.source_id)
    with pytest.raises(DomainError) as stale:
        await company.store.inspect(company.actor, company.binding_id, proposal['proposal_id'],
            byte_start=page['draft_window']['next_byte'], max_bytes=512)
    assert stale.value.code == 'INPUT_INELIGIBLE'
    with pytest.raises(DomainError) as approval:
        await company.store.approve_rule(company.actor, RuleApproval(
            proposal_id=proposal['proposal_id'], expected_digest=proposal['digest'],
            scope=RuleScope.LOCAL_PROJECT, target_bindings=(company.binding_id,),
            target_set_revision=proposal['target_set_revision'], idempotency_key='deny-changed-proposal'))
    assert approval.value.code in {'INPUT_INELIGIBLE', 'APPROVAL_STALE'}
