from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agents_memory.domain import (
    CitedSentence,
    Claim,
    ClaimDraft,
    Consolidation,
    DomainError,
    EvidenceSpan,
    Extraction,
    Quote,
    ReflectionDraft,
    RelationDraft,
    Source,
)
from agents_memory.semantic import (
    original_spans,
    resolve_extraction,
    validate_consolidation,
    validate_extraction,
    validate_reflection,
)
from agents_memory.semantic_contract import GeneratedExtraction


def claim(identifier: str, quote: str, **qualifiers) -> Claim:
    source_id = "source_" + identifier
    return Claim(
        id=identifier,
        binding_id="project_a",
        draft=ClaimDraft(
            statement=quote,
            kind="fact",
            subject="cache",
            predicate="has",
            object="limit",
            polarity="positive",
            modality="asserted",
            evidence=(Quote(source_id=source_id, quote=quote),),
            **qualifiers,
        ),
        evidence=(EvidenceSpan(
            source_id=source_id, source_revision=1, source_speaker="human", byte_start=0,
            byte_end=len(quote.encode("utf-8")), quote=quote,
        ),),
        input_source_ids=(source_id,),
        snapshot="snapshot_a",
        created_at=datetime(2026, 10, 12, tzinfo=UTC),
    )


def reflection(text: str, *claim_ids: str) -> ReflectionDraft:
    return ReflectionDraft(sentences=(CitedSentence(text=text, claim_ids=claim_ids),))


@pytest.mark.parametrize("citations", [("outside",), ("a", "outside"), ("a", "a")])
def test_foreign_or_repeated_sentence_citation_is_rejected(citations):
    with pytest.raises(DomainError, match="citation|manifest"):
        validate_reflection(reflection("근거가 제한적이다.", *citations), [claim("a", "근거 원문")])


def test_empty_sentence_citation_is_malformed():
    with pytest.raises(ValidationError):
        reflection("근거 없는 결론이다.")


def test_number_in_an_uncited_claim_cannot_support_a_sentence():
    claims = [claim("a", "cache_limit is 128."), claim("b", "timeout is 42 seconds.")]
    with pytest.raises(DomainError, match="unsupported number"):
        validate_reflection(reflection("cache_limit is 42.", "a"), claims)


@pytest.mark.parametrize("text", ["cache_limit is 12.", "cache_limit is 256.", "cacheLimit is 128."])
def test_invented_numeric_and_identifier_literals_are_rejected(text):
    with pytest.raises(DomainError, match="unsupported"):
        validate_reflection(reflection(text, "a"), [claim("a", "cache_limit is 128.")])


def test_simple_inline_code_identifier_cannot_be_invented():
    with pytest.raises(DomainError, match="unsupported identifier"):
        validate_reflection(reflection("Call `flush`.", "a"), [claim("a", "Call refresh().")])


def test_identifier_prefix_is_not_exact_identifier_evidence():
    with pytest.raises(DomainError, match="unsupported identifier"):
        validate_reflection(reflection("Use `cache`.", "a"), [claim("a", "Use cache.limit.")])


def test_valid_citations_allow_semantic_paraphrase_without_word_entailment_gate():
    validate_reflection(
        reflection("캐시 상한은 128이며 cache_limit 설정을 사용한다.", "a"),
        [claim("a", "cache_limit is 128.")],
    )
    validate_reflection(
        reflection("An evidence-based local-first approach is appropriate.", "a"),
        [claim("a", "Keep information on the user's machine.")],
    )


def test_limitations_cannot_smuggle_unsupported_numbers():
    result = reflection("근거가 제한적이다.", "a").model_copy(update={
        "limitations": ("The timeout might be 77 seconds.",),
    })
    with pytest.raises(DomainError, match="unsupported number"):
        validate_reflection(result, [claim("a", "The timeout is unknown.")])


@pytest.mark.parametrize("normalized", [
    "2026-10-11T00:00:00Z",
    "2026-10-11T09:00:00+09:00",
])
def test_cited_timestamp_accepts_equivalent_instants_without_retyping_source_evidence(normalized):
    validate_reflection(
        reflection(f"유효 시작은 {normalized}다.", "a"),
        [claim("a", "유효 시작은 2026-10-11T00:00:00+00:00다.")],
    )


def test_complete_timestamp_cannot_change_day_hidden_by_numeric_tokenization():
    with pytest.raises(DomainError) as rejected:
        validate_reflection(
            reflection("유효 시작은 2026-10-12T00:00:00Z다.", "a"),
            [claim("a", "유효 시작은 2026-10-11T00:00:00+00:00다.")],
        )
    assert rejected.value.code == "MODEL_OUTPUT_INVALID"


def test_equivalent_timestamp_in_an_uncited_claim_does_not_authorize_a_sentence():
    with pytest.raises(DomainError):
        validate_reflection(reflection("유효 시작은 2026-10-11T00:00:00Z다.", "a"), [
            claim("a", "유효 시작은 아직 정해지지 않았다."),
            claim("b", "유효 시작은 2026-10-11T00:00:00+00:00다."),
        ])


def test_compatibility_guard_preserves_conditions_and_time():
    first = claim("a", "cache_limit is 128.", conditions=("offline only",))
    second = claim("b", "cache_limit is 128.", conditions=("online only",))
    result = Consolidation(relations=(RelationDraft(
        left_id="a", right_id="b", kind="duplicates", reason="Equivalent values",
    ),))
    with pytest.raises(DomainError, match="conditions"):
        validate_consolidation(result, [first, second])
    timed = first.model_copy(update={"id": "b", "draft": first.draft.model_copy(update={
        "valid_from": datetime(2026, 10, 13, tzinfo=UTC),
    })})
    with pytest.raises(DomainError, match="valid time"):
        validate_consolidation(result, [first, timed])
    conditional = result.model_copy(update={"relations": (result.relations[0].model_copy(update={
        "kind": "conditional_variant",
    }),)})
    validate_consolidation(conditional, [first, second])


def test_normalized_search_text_is_not_accepted_as_an_evidence_quote():
    source = Source(
        id="source_a", binding_id="project_a", realm="personal", revision=1,
        body="설정은 ＡＰＩ＿Ｖ２ 를 사용한다.", speaker="human", origin_key="event_a",
        root_run_id=None, snapshot=None, event_time=None,
        recorded_at=datetime(2026, 10, 12, tzinfo=UTC),
    )
    draft = claim("a", "설정은 API_V2 를 사용한다.").draft
    with pytest.raises(DomainError, match="original span"):
        validate_extraction(Extraction(claims=(draft,)), source)


def test_utf8_offset_must_be_original_byte_offset():
    source = Source(
        id="source_a", binding_id="project_a", realm="personal", revision=1,
        body="한글 cache_limit is 128.", speaker="human", origin_key="event_a",
        root_run_id=None, snapshot=None, event_time=None,
        recorded_at=datetime(2026, 10, 12, tzinfo=UTC),
    )
    draft = claim("a", "cache_limit is 128.").draft
    bad = draft.model_copy(update={"evidence": (draft.evidence[0].model_copy(update={
        "byte_start": 3,
    }),)})
    with pytest.raises(DomainError, match="original span"):
        validate_extraction(Extraction(claims=(bad,)), source)
    good = draft.model_copy(update={"evidence": (draft.evidence[0].model_copy(update={
        "byte_start": len("한글 ".encode()),
    }),)})
    validate_extraction(Extraction(claims=(good,)), source)


def test_qualification_cannot_be_translated_away_from_its_original_evidence():
    text = "고객 코드 외부 저장 금지는 회사 프로젝트에 적용하며 익명화된 합성 데이터는 예외다."
    source = Source(
        id="source_a", binding_id="project_a", realm="personal", revision=1,
        body=text, speaker="document", origin_key="event_a", root_run_id=None,
        snapshot=None, event_time=None, recorded_at=datetime(2026, 10, 12, tzinfo=UTC),
    )
    draft = ClaimDraft(
        statement="고객 코드는 외부에 저장하지 않는다.", kind="fact",
        subject="고객 코드", predicate="저장", object="외부",
        polarity="negative", modality="asserted", conditions=("회사 프로젝트",),
        exceptions=("익명화된 합성 데이터",),
        evidence=(Quote(source_id=source.id, quote=text),),
    )
    translated = draft.model_copy(update={"conditions": ("company projects",)})
    with pytest.raises(DomainError) as rejected:
        validate_extraction(Extraction(claims=(translated,)), source)
    assert rejected.value.code == "MODEL_OUTPUT_INVALID"
    validate_extraction(Extraction(claims=(draft,)), source)


VEGA = (
    "Synthetic Vega sandbox: the default serialization format is JSON.\n"
    "For the same Synthetic Vega sandbox and the same time, the default serialization format is YAML.\n"
    "Neither statement has been selected as an approved policy."
)
KOREAN = (
    "합성 Polaris 프로젝트: PolicyGate.check()는 오프라인 검토에서만 사용한다. "
    "고객 코드는 외부 서비스에 저장하지 않는다. "
    "이 금지 규칙은 회사 프로젝트에 적용하며 익명화된 합성 데이터는 예외다. "
    "이 두 규칙의 유효기간은 2026-10-11T00:00:00+00:00부터 "
    "2026-10-25T00:00:00+00:00까지다."
)


def span_source(body: str) -> Source:
    return Source(
        id="source_a", binding_id="project_a", realm="personal", revision=1,
        body=body, speaker="document", origin_key="event_a", root_run_id=None,
        snapshot="vega-conflict-v1", event_time=None,
        recorded_at=datetime(2026, 10, 12, tzinfo=UTC),
    )


def generated_claim(source: Source, span_id: str, index=0, **updates) -> dict:
    fields = ClaimDraft(
        statement="The default serialization format is JSON.", kind="fact",
        subject="serialization format", predicate="is", object="JSON",
        polarity="positive", modality="asserted",
        evidence=(Quote(source_id=source.id, quote=source.body),),
    ).model_dump(exclude={"evidence", "conditions", "exceptions", "valid_from", "valid_until"})
    return {
        **fields, "assertion_id": f"a{index:04d}", "assertion_span_id": span_id, **updates,
    }


def qualification(kind, phrase, span_ids, targets=("a0000",)):
    assert span_ids is None or len(span_ids) == 1
    return {"kind": kind, "phrase": phrase,
            "evidence_span_id": span_ids[0] if span_ids is not None else None,
            "assertion_ids": targets}


def generated_artifact(source, claims, qualifications=(), validities=(), unused=None):
    spans = original_spans(source)
    used = {item["assertion_span_id"] for item in claims}
    individual, shared = [], []
    for item in qualifications:
        fields = {key: value for key, value in item.items() if key != "assertion_ids"}
        if len(item["assertion_ids"]) == 1:
            individual.append({**fields, "assertion_id": item["assertion_ids"][0]})
        else:
            shared.append(item)
        if item["evidence_span_id"] is not None:
            used.add(item["evidence_span_id"])
        else:
            used.update(span.span_id for span in spans if item["phrase"] in span.quote)
    for item in validities:
        used.update(item["evidence_span_ids"])
    if unused is None:
        unused = tuple(span.span_id for span in spans if span.span_id not in used)
    return GeneratedExtraction.model_validate({
        "claims": claims, "individual_qualifications": individual, "shared_qualifications": shared,
        "validities": validities, "unused_span_ids": unused,
    })


def korean_claim(source, index=0):
    return generated_claim(
        source, "s0001", index=index,
        statement="고객 코드는 외부 서비스에 저장하지 않는다.",
        subject="고객 코드", predicate="저장", object="외부 서비스", polarity="negative",
    )


def korean_validity(targets=("a0000",), **updates):
    return {
        "valid_from": datetime(2026, 10, 11, tzinfo=UTC),
        "valid_until": datetime(2026, 10, 25, tzinfo=UTC),
        "evidence_span_ids": ("s0003",), "assertion_ids": targets, **updates,
    }


def test_shared_scope_keeps_conflicting_assertions_comparable_without_erasing_context():
    source = span_source(VEGA)
    result = resolve_extraction(generated_artifact(source, [
        generated_claim(source, "s0000"),
        generated_claim(source, "s0001", index=1, object="YAML",
                        statement="The default serialization format is YAML."),
    ], qualifications=[
        qualification("condition", "Synthetic Vega sandbox", ("s0000",), ("a0000", "a0001")),
        qualification("context", "same time", ("s0001",), ("a0000", "a0001")),
        qualification("context", original_spans(source)[2].quote, ("s0002",), ("a0000", "a0001")),
    ]), source)
    assert {draft.conditions for draft in result.claims} == {("Synthetic Vega sandbox",)}
    assert {draft.object for draft in result.claims} == {"JSON", "YAML"}
    assert all(original_spans(source)[2].quote in {q.quote for q in draft.evidence}
               for draft in result.claims)


@pytest.mark.parametrize("ids", [("s9999",), ("0",), ("s0000:1",)])
def test_unknown_or_malformed_original_span_ids_are_rejected(ids):
    source = span_source(VEGA)
    artifact = generated_artifact(source, [generated_claim(source, "s0000")],
                                  [qualification("context", "Synthetic Vega sandbox", ids)])
    with pytest.raises(DomainError) as rejected:
        resolve_extraction(artifact, source)
    assert rejected.value.code == "MODEL_OUTPUT_INVALID"


@pytest.mark.parametrize("targets", [("a9999",), ("a0000", "a0000")])
def test_qualification_cannot_target_unknown_or_repeated_assertions(targets):
    source = span_source(VEGA)
    artifact = generated_artifact(source, [generated_claim(source, "s0000")],
                                  [qualification("context", "Synthetic Vega sandbox", ("s0000",), targets)])
    with pytest.raises(DomainError):
        resolve_extraction(artifact, source)


def test_repeated_literal_span_ids_keep_distinct_exact_utf8_offsets():
    source = span_source("한글 JSON. 한글 JSON.")
    spans = original_spans(source)
    result = resolve_extraction(generated_artifact(source, [
        generated_claim(source, "s0001"),
    ]), source)
    assert result.claims[0].evidence[0].byte_start == len("한글 JSON. ".encode())
    bad_quote = result.claims[0].evidence[0].model_copy(update={"byte_start": spans[1].byte_start + 1})
    bad_draft = result.claims[0].model_copy(update={"evidence": (bad_quote,)})
    with pytest.raises(DomainError):
        validate_extraction(Extraction(claims=(bad_draft,)), source)


@pytest.mark.parametrize("bound", ["valid_from", "valid_until"])
def test_fabricated_temporal_bounds_are_not_eligible_without_original_evidence(bound):
    source = span_source("The default serialization format is JSON.")
    validity = {"valid_from": None, "valid_until": None, "evidence_span_ids": ("s0000",),
                "assertion_ids": ("a0000",), bound: datetime(2099, 1, 1, tzinfo=UTC)}
    with pytest.raises(DomainError):
        resolve_extraction(generated_artifact(source, [generated_claim(source, "s0000")],
                                             validities=[validity]), source)


def test_korean_prohibition_retains_exception_and_explicit_validity_evidence():
    source = span_source(KOREAN)
    result = resolve_extraction(generated_artifact(source, [korean_claim(source)], [
        qualification("condition", "회사 프로젝트", ("s0002",)),
        qualification("exception", "익명화된 합성 데이터", ("s0002",)),
    ], [korean_validity()]), source)
    draft = result.claims[0]
    assert draft.polarity == "negative"
    assert draft.conditions == ("회사 프로젝트",)
    assert draft.exceptions == ("익명화된 합성 데이터",)
    assert draft.valid_from == datetime(2026, 10, 11, tzinfo=UTC)
    assert draft.valid_until == datetime(2026, 10, 25, tzinfo=UTC)
    assert original_spans(source)[3].quote in {quote.quote for quote in draft.evidence}


@pytest.mark.parametrize("updates", [
    {"evidence_span_ids": ("s0002",)},
    {"valid_until": datetime(2099, 10, 25, tzinfo=UTC)},
    {"assertion_ids": ("a9999",)},
    {"valid_from": None, "valid_until": None},
    {"evidence_span_ids": ("s0003", "s0003")},
])
def test_validity_requires_real_bounds_and_selected_original_evidence(updates):
    source = span_source(KOREAN)
    with pytest.raises(DomainError):
        resolve_extraction(generated_artifact(source, [korean_claim(source)],
                                             validities=[korean_validity(**updates)]), source)


def test_ambiguous_or_timezone_free_time_remains_unresolved():
    source = span_source("JSON is valid until next month or 2099-01-01T00:00:00.")
    result = resolve_extraction(generated_artifact(source, [generated_claim(source, "s0000")]), source)
    assert result.claims[0].valid_from is None and result.claims[0].valid_until is None
    validity = {"valid_from": None, "valid_until": datetime(2099, 1, 1, tzinfo=UTC),
                "evidence_span_ids": ("s0000",), "assertion_ids": ("a0000",)}
    with pytest.raises(DomainError):
        resolve_extraction(generated_artifact(source, [generated_claim(source, "s0000")],
                                             validities=[validity]), source)


def test_shared_qualification_cannot_borrow_a_phrase_from_an_uncited_span():
    source = span_source(VEGA)
    with pytest.raises(DomainError):
        resolve_extraction(generated_artifact(source, [generated_claim(source, "s0000")],
                                             [qualification("condition", "same time", ("s0000",))]), source)


@pytest.mark.parametrize("broadened", ["condition", "exception", "validity", "duplicate"])
def test_same_assertion_cannot_publish_an_unqualified_or_timeless_shadow(broadened):
    source = span_source(KOREAN)
    targets = ("a0000", "a0001")
    artifact = generated_artifact(source, [korean_claim(source), korean_claim(source, index=1)], [
        qualification("condition", "회사 프로젝트", ("s0002",),
                      ("a0000",) if broadened == "condition" else targets),
        qualification("exception", "익명화된 합성 데이터", ("s0002",),
                      ("a0000",) if broadened == "exception" else targets),
    ], [korean_validity(("a0000",) if broadened == "validity" else targets)])
    with pytest.raises(DomainError):
        resolve_extraction(artifact, source)


def test_disjoint_conditional_variants_are_not_mistaken_for_shadow_copies():
    source = span_source("JSON applies to project A and project B.")
    result = resolve_extraction(generated_artifact(source, [
        generated_claim(source, "s0000"), generated_claim(source, "s0000", index=1),
    ], [
        qualification("condition", "project A", ("s0000",), ("a0000",)),
        qualification("condition", "project B", ("s0000",), ("a0001",)),
    ]), source)
    assert {draft.conditions for draft in result.claims} == {("project A",), ("project B",)}


@pytest.mark.parametrize("unused", [(), ("s0000", "s0001", "s0002")])
def test_implicit_span_loss_and_used_unused_overlap_fail_closed(unused):
    source = span_source(VEGA)
    with pytest.raises(DomainError):
        resolve_extraction(generated_artifact(source, [generated_claim(source, "s0000")],
                                             unused=unused), source)


def test_assertion_cannot_have_two_ambiguous_validity_assignments():
    source = span_source(KOREAN)
    with pytest.raises(DomainError):
        resolve_extraction(generated_artifact(source, [korean_claim(source)],
                                             validities=[korean_validity(), korean_validity()]), source)


@pytest.mark.parametrize("body, phrase", [
    ("JSON is valid. JSON is still valid.", "JSON"),
    ("JSON is valid.", "YAML"),
])
def test_automatic_qualification_anchor_refuses_missing_or_ambiguous_evidence(body, phrase):
    source = span_source(body)
    with pytest.raises(DomainError):
        resolve_extraction(generated_artifact(source, [generated_claim(source, "s0000")],
                                             [qualification("context", phrase, None)]), source)


def test_unique_original_phrase_resolves_its_real_span_not_the_target_assertion_span():
    source = span_source(KOREAN)
    result = resolve_extraction(generated_artifact(source, [korean_claim(source)], [
        qualification("context", "합성 Polaris 프로젝트", None),
    ]), source)
    assert result.claims[0].evidence[1].byte_start == 0
    assert "PolicyGate.check()" in result.claims[0].evidence[1].quote
