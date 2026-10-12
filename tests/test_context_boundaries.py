import json
from datetime import UTC, datetime

import pytest

from agents_memory.context import compose
from agents_memory.domain import (
    ActiveRule,
    Claim,
    ClaimDraft,
    ContextCommand,
    DomainError,
    EvidenceSpan,
    Quote,
    Relation,
    RuleScope,
    Selector,
)


def rule(identifier="rule-001", *, body="Keep evidence.", required=False, selector=None):
    return ActiveRule(
        id=identifier, revision=1, digest="a" * 64, body=body,
        selector=selector or Selector(), exceptions=(), required=required,
        scope=RuleScope.LOCAL_PROJECT, target_bindings=("binding-001",), source_ids=(),
    )


def claim(identifier="claim-001", *, polarity="negative"):
    quote = "회사 프로젝트에서는 2026-10-11부터 ExportPolicy.export_raw()를 실행하지 않는다."
    return Claim(
        id=identifier, binding_id="binding-001",
        draft=ClaimDraft(
            statement=quote, kind="fact", subject="ExportPolicy.export_raw()",
            predicate="execute", object="raw export", polarity=polarity,
            modality="asserted", conditions=("회사 프로젝트일 때",),
            exceptions=("익명화된 합성 데이터는 제외",),
            valid_from=datetime(2026, 10, 11, tzinfo=UTC),
            evidence=(Quote(source_id="source-001", quote=quote, byte_start=0),),
        ),
        evidence=(EvidenceSpan(source_id="source-001", source_revision=2, source_speaker="human",
            byte_start=0, byte_end=len(quote.encode("utf-8")), quote=quote),),
        input_source_ids=("source-001",), snapshot="snapshot-001",
        created_at=datetime(2026, 10, 11, tzinfo=UTC),
    )


@pytest.mark.parametrize("paths", [None, ("src\\secret.py",), ("../secret.py",), ("/src/secret.py",)])
def test_required_unknown_path_is_not_silently_dropped(paths):
    selected = rule(required=True, selector=Selector(paths=("src/**/*.py",)))
    with pytest.raises(DomainError) as caught:
        compose(
            ContextCommand(binding_id="binding-001", query="review", paths=paths),
            (selected,), (), (), protected_action=True,
        )
    assert caught.value.code == "RULE_APPLICABILITY_UNKNOWN"


def test_required_relative_path_alias_cannot_bypass_rule():
    selected = rule(required=True, selector=Selector(paths=("src/*.py",)))
    result = compose(ContextCommand(binding_id="binding-001", query="review", paths=("src/./secret.py",)), (selected,), (), ())
    assert json.loads(result.text)["approved_rules"][0]["ref"] == selected.id




def test_unknown_optional_scope_is_reported_omitted():
    result = compose(ContextCommand(query="recall"), (rule(selector=Selector(paths=("src/*.py",))),), (), ())
    assert result.omitted == 1

def test_no_selected_memory_adds_no_context_document():
    result = compose(ContextCommand(query="recall"), (), (), ())
    assert result.text == ""



def test_optional_rules_and_claims_share_the_item_budget():
    rules = tuple(rule(f"rule-{index:03}") for index in range(4))
    result = compose(ContextCommand(query="recall", limit=3), rules, (claim(),), ())
    decoded = json.loads(result.text)
    assert [entry["ref"] for entry in decoded["approved_rules"]] == ["rule-000", "rule-001", "rule-002"]
    assert decoded["memory_candidates"] == []
    assert result.omitted == 2


def test_required_rules_are_whole_or_explicitly_blocked_in_utf8_bytes():
    selected = rule(required=True, body="안전" * 1000)
    with pytest.raises(DomainError) as caught:
        compose(ContextCommand(query="review", max_bytes=2400), (selected,), (), ())
    assert caught.value.code == "REQUIRED_CONTEXT_OVERFLOW"


def test_optional_oversize_is_omitted_whole_not_truncated():
    selected = rule(body="안전" * 1000)
    result = compose(ContextCommand(query="recall", max_bytes=2400), (selected,), (claim(),), ())
    decoded = json.loads(result.text)
    assert decoded["approved_rules"] == []
    assert decoded["memory_candidates"][0]["ref"] == "claim-001"
    assert result.omitted == 1
    assert result.byte_count <= 2400


def test_original_qualification_is_not_lost_when_model_classification_is_incomplete():
    selected = claim()
    original_scope = "이 금지 규칙은 회사 프로젝트에 적용하며 익명화된 합성 데이터는 예외다."
    qualifier = EvidenceSpan(
        source_id="source-001", source_revision=2, source_speaker="human",
        byte_start=selected.evidence[0].byte_end + 1,
        byte_end=selected.evidence[0].byte_end + 1 + len(original_scope.encode()),
        quote=original_scope,
    )
    selected = selected.model_copy(update={
        "draft": selected.draft.model_copy(update={
            "statement": "ExportPolicy.export_raw()를 실행하지 않는다.",
            "conditions": (), "exceptions": (),
        }),
        "evidence": (*selected.evidence, qualifier),
    })
    result = compose(ContextCommand(query="export policy"), (), (selected,), ())
    candidate = json.loads(result.text)["memory_candidates"][0]
    assert original_scope in {span["quote"] for span in candidate["evidence"]}
    assert candidate["interpretation_role"] == "model_derived_candidate"


def test_candidate_cannot_fit_by_discarding_original_qualifying_evidence():
    selected = claim()
    long_qualification = "회사 프로젝트만 허용하며 익명화된 합성 데이터는 예외다. " * 80
    selected = selected.model_copy(update={
        "evidence": (EvidenceSpan(
            source_id="source-001", source_revision=2, source_speaker="human", byte_start=0,
            byte_end=len(long_qualification.encode()), quote=long_qualification,
        ),),
    })
    result = compose(ContextCommand(query="export policy", max_bytes=1200), (), (selected,), ())
    assert result.claim_ids == ()
    assert result.omitted == 1




def test_conflict_refuses_when_even_one_candidate_and_its_metadata_cannot_fit():
    claims = (claim("claim-001"), claim("claim-002", polarity="positive"))
    relation = Relation(id="relation-001", left_id="claim-001", right_id="claim-002", kind="contradicts", reason="Different polarity")
    base = compose(ContextCommand(query="export", max_bytes=6144), (), claims[:1], ())
    with pytest.raises(DomainError) as caught:
        compose(ContextCommand(query="export", max_bytes=base.byte_count), (), claims, (relation,))
    assert caught.value.code == "CONFLICT_CONTEXT_OVERFLOW"


def test_lower_ranked_candidate_cannot_crowd_out_known_conflict_metadata():
    claims = (claim("claim-001"), claim("claim-002", polarity="positive"), claim("claim-003"))
    relation = Relation(id="relation-001", left_id="claim-001", right_id="claim-002", kind="contradicts", reason="Different polarity")
    bare = compose(ContextCommand(query="export", max_bytes=6144), (), claims, ())
    result = compose(ContextCommand(query="export", max_bytes=bare.byte_count), (), claims, (relation,))
    assert result.claim_ids == ("claim-001", "claim-002")
    assert result.relation_ids == ("relation-001",)
    assert set(json.loads(result.text)["relations"][0]["endpoints_in_context"]) == set(result.claim_ids)
    assert result.byte_count <= bare.byte_count and result.omitted == 1


def test_unknown_required_rules_cannot_crowd_memory_with_undeliverable_bodies():
    rules = tuple(
        rule(f"rule-{index:03}", required=True, body="사내 규칙" * 1000,
             selector=Selector(paths=("other/**/*.py",)))
        for index in range(8)
    )
    result = compose(ContextCommand(query="recall", max_bytes=1200), rules, (claim(),), ())
    decoded = json.loads(result.text)
    assert result.claim_ids == ("claim-001",)
    assert decoded["approved_rules"] == []
    assert result.rule_versions == ()
    assert result.byte_count <= 1200
    assert result.omitted == len(rules) - len(result.unknown_rule_refs)
    assert result.unknown_rule_count == 8
    assert all("body" not in ref and ref["applicability"] == "unknown"
               for ref in decoded.get("unknown_required_rules", ()))
    with pytest.raises(DomainError) as caught:
        compose(ContextCommand(query="write"), rules, (), (), protected_action=True)
    assert caught.value.code == "RULE_APPLICABILITY_UNKNOWN"


def test_unresolved_required_reference_cannot_expose_an_approval_stamp():
    selected = rule("required-opaque", required=True,
                    selector=Selector(paths=("src/**/*.py",)))
    result = compose(ContextCommand(query="recall", max_bytes=512), (selected,), (), ())
    stub = json.loads(result.text)["unknown_required_rules"][0]
    assert stub["ref"] == selected.id and stub["applicability"] == "unknown"
    assert "revision" not in stub and "digest" not in stub and "body" not in stub
    assert selected.digest not in result.text and selected.body not in result.text
    assert result.rule_versions == () and result.unknown_rule_count == 1


def test_false_rule_selector_cannot_block_unrelated_memory_recall():
    selected = rule(required=True, body="안전" * 1000, selector=Selector(paths=("other/**/*.py",)))
    command = ContextCommand(query="recall", paths=("src/a.py",))
    result = compose(command, (selected,), (claim(),), ())
    assert result.claim_ids == ("claim-001",)
    assert result.rule_versions == () and result.unknown_rule_refs == ()
    assert result.omitted == 0
    guarded = compose(command, (selected,), (), (), protected_action=True)
    assert guarded.text == "" and guarded.rule_versions == ()




def test_one_selected_conflict_endpoint_keeps_opaque_missing_partner():
    relation = Relation(id="relation-001", left_id="claim-001", right_id="claim-002", kind="contradicts", reason="Different polarity")
    result = compose(ContextCommand(query="export", limit=1), (), (claim(),), (relation,))
    decoded = json.loads(result.text)
    assert decoded["relations"] == [{
        "ref": "relation-001", "left": "claim-001", "right": "claim-002",
        "kind": "contradicts", "endpoints_in_context": ["claim-001"],
    }]
    assert result.relation_ids == ("relation-001",)


def test_reflection_cannot_reason_from_one_side_of_a_known_conflict():
    relation = Relation(id="relation-001", left_id="claim-001", right_id="claim-002", kind="contradicts", reason="Different polarity")
    command = ContextCommand(query="export", mode="reflect", idempotency_key="reflect-001", limit=1)
    with pytest.raises(DomainError) as caught:
        compose(command, (), (claim(),), (relation,))
    assert caught.value.code == "REFLECTION_CONFLICT_INPUT_INCOMPLETE"


def test_selected_endpoint_cannot_drop_conflict_when_only_metadata_exceeds_budget():
    relation = Relation(id="relation-001", left_id="claim-001", right_id="claim-002", kind="contradicts", reason="Different polarity")
    baseline = compose(ContextCommand(query="export"), (), (claim(),), ())
    with pytest.raises(DomainError) as caught:
        compose(ContextCommand(query="export", max_bytes=baseline.byte_count), (), (claim(),), (relation,))
    assert caught.value.code == "CONFLICT_CONTEXT_OVERFLOW"


@pytest.mark.parametrize("pattern", ["src/./*.py", "src//*.py"])
def test_relative_pattern_alias_keeps_required_action_rule(pattern):
    selected = rule(required=True, selector=Selector(paths=(pattern,)))
    result = compose(
        ContextCommand(query="write", paths=("src/main.py",)),
        (selected,), (), (), protected_action=True,
    )
    assert result.rule_versions == ((selected.id, selected.revision, selected.digest),)
