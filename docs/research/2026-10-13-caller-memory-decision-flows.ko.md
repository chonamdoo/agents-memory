# MCP 메모리 OSS: caller 판단·모델 없는 저장 경로의 실제 제어 흐름

## 요약

세 저장소를 지정 SHA의 GitHub 디렉터리와 raw source로 정적으로 추적했다. 설치·clone·빌드·테스트·lint·실행·기존 source/config/AF artifact 변경은 하지 않았다. 아래 `durable`은 코드에 있는 SQLite commit/transaction 경계를 뜻하며 crash/power-loss 내구성을 실측한 표현은 아니다.

- **Engram:** `mem_save`가 observation을 **먼저 commit**한다. 그 뒤 lexical 후보마다 durable `pending` relation을 만들고 caller에게 `judgment_id`를 준다. `mem_judge`는 caller가 내린 관계를 기록할 뿐, `conflicts_with`라고 판단해도 observation을 보류 저장소로 옮기거나 `supersedes`로 기존 내용을 자동 교체하지 않는다.
- **codex-agent-mem:** 모델 judge가 아니라 **deterministic policy로 이미 저장된 메모리의 retrieval/pack 노출을 결정**한다. 중복·stale repair는 원본 삭제 대신 `repair_events.after_ref.exclude_observation_ids`를 저장한다. 모순은 `supported_apply=false`로 자동 적용을 거부한다. 원문 turn JSON과 provenance 연결은 있지만 `source_span`은 검증된 문자 범위가 아니다.
- **Memharness:** `nearDuplicates`로 유사 사실을 읽은 뒤에도 `remember`는 **항상 새 fact를 저장**하고 advisory를 반환한다. caller가 정확한 `old_fact_id`를 지정한 `revise`를 별도로 호출하면 old/new 사실을 transaction으로 연결한다. 별도의 source freshness `current/stale/unresolved`는 사실의 진실성 판정이나 signed approval이 아니라 git 관측 신호다.

우리에게 유용한 결합은 **Engram의 pair별 judge ID**, **codex-agent-mem의 비파괴적인 exclusion overlay**, **Memharness의 successor history 및 확인 불가 상태 분리**다. 세 구현 중 조사한 경로에는 우리 계약의 “원문 span 검증 + 승인된 처리 route + 해당 연산에 필요한 권한·규칙 승인” 전체를 대신하는 것이 없다. 회사가 승인한 모델이라는 조건을 모든 fact 저장의 인간 승인 요구로 확대하지 않는다. 세 제품이 같은 3분류 UI를 제공한다고 해석하지 않는다.

## 조사 범위·고정 버전

| 저장소 | 고정 SHA | 주요 구현 |
|---|---|---|
| Gentleman-Programming/engram | `5c4171845958f046968c14d7d57a325eb4a83b7e` | `internal/mcp/mcp.go`, `internal/store/{store,relations,candidate_relevance,prompt_capture}.go` |
| MarceloCaporale/codex-agent-mem | `d594c8a86207fb9a8a5b48a6aab323349680707a` | `src/codex_agent_mem/{policy_engine,db,mcp_stdio,ingest,retrieval_hygiene,health}.py`, `providers/noop.py` |
| las7/memharness | `faed4b346e445d2344ed02e8211759999acd946d` | `packages/core/src/{memory,staleness,sql,db}.ts`, `packages/mcp/src/{server,index,staleness}.ts` |

`policy_engine.py`는 repository root가 아니라 `src/codex_agent_mem/` 아래다. 처음 root raw URL은 404였지만 pinned 디렉터리에서 실제 위치를 찾아 읽었다. GitHub tree API는 403이어서 pinned HTML 디렉터리와 raw GitHub로 조사했다. 이 보고서의 source 링크는 모두 위 SHA에 고정했다. `mcp-memory-keeper`는 최소 요구 세 가지 상이한 형태를 이미 확보했으므로 추가 조사하지 않았다.

## 1. Engram — 저장 후 관계 후보 생성, 외부 caller의 judge 영속화

### Sourceflow miniature

```text
caller가 title/content/type/project/scope/topic_key를 선택
  → handleSave: content/title/옵션/project/session 검증
  → implicit session 생성 시도
  → AddObservationWithResult transaction
       topic_key 동일: previous title/content snapshot → 기존 observation 갱신
       아니면 bounded exact-normalized duplicate: counter/time 갱신, 기존 ID 반환
       아니면 new obs sync_id + observation INSERT + 선택적 review_after
       → observation sync mutation/operation ledger(해당 옵션일 때) → COMMIT
  → 현재 runtime prompt 별도 capture(있으면; 실패 nonfatal)
  → FindCandidates(savedID): title OR FTS5 + project/scope + relevance gate
       → 신규 pair마다 memory_relations pending/pending INSERT
       → candidate observation id/sync_id + relation judgment_id 반환
  → caller가 필요 시 full observation을 가져와 의미 판단
  → mem_judge(judgment_id, relation, reason?, evidence?, confidence?)
       → 관계 존재·verb·project guard → relation UPDATE judged
       → enrolled source project이면 같은 tx에 relation sync mutation → COMMIT
       → observation 자체는 그대로
```

핵심 함수·경계: [handleSave][E-save], [AddObservationWithResult][E-add], [FindCandidates][E-candidate], [JudgeRelation][E-judge].

### 1.1 무엇이 저장 전에 결정되고, 무엇이 저장 후 남는가

1. `handleSave`는 content가 없으면 error, title 검증 실패면 session 생성 전에 error를 반환한다. `capture_prompt`의 비boolean도 error다. project resolution과 fallback session 오류도 tool error다. 이후 implicit session 생성 오류는 `_ = ensureImplicitSessionWithCWD(...)`로 무시한다. 따라서 “모든 실패는 side-effect 없음”은 아니다: observation 저장 전에 session 생성 시도가 있으며, 뒤 단계 실패 시 이미 생긴 session이 남을 수 있다. [E-save]
2. `AddObservationWithResult`는 project normalize, `<private>` redaction, content truncation 뒤 저장한다. 저장값이 원래 메시지의 byte-for-byte 원문이라는 보장은 없다. 기본 maximum은 50,000 bytes이며 truncation marker를 덧붙인다. [E-content]
3. `topic_key`가 같은 project/scope의 기존 observation과 맞으면 **semantic 비교 전에 upsert**한다. old title/content를 `observation_versions`에 먼저 snapshot하고 revision_count를 증가시킨다. 같은 내용이어도 이 branch에는 equality no-op 판정이 없다. 제목 이름이 같아야만 patch하는 것도 아니다. caller가 부여한 topic identity가 우선이다. [E-add], [E-version]
4. topic branch가 아니면 lowercased/whitespace-collapsed content SHA-256와 **동일 title/type/project/scope**, 생성시각 dedupe window를 같이 검사한다. 기본 window는 15분이다. 맞으면 새 observation은 만들지 않지만 duplicate_count/last_seen_at/updated_at와 sync 기록은 바뀐다. **strict no-op가 아니라 reinforcement/update**다. 제목이 다르거나 paraphrase인 내용은 이 branch로 합쳐지지 않는다. [E-add], [E-hash]
5. 새 observation의 `review_after`는 decision 6개월, policy 12개월, preference 3개월; 다른 type은 null이다. `active/needs_review`는 `review_after`와 현재시각으로 계산하는 virtual lifecycle이며 candidate 관계의 `pending`과 다른 축이다. topic update와 dedupe에서는 새 review_after를 설정하지 않는다. [E-state]
6. 저장이 성공한 뒤 candidate query가 실패하면 stderr에만 기록하고 save 성공 응답을 계속한다. 따라서 `judgment_required=false`는 “모델이 conflict 없음을 확인했다”도 “검사가 성공했다”도 아니다. 후보가 없거나 lookup 실패/insert skip인 경우에도 false일 수 있다. [E-save], [E-candidate]

### 1.2 candidate ID·retrieval·pending의 정확한 의미

- saved observation `id`는 로컬 integer key, `sync_id`는 portable observation identity다. `candidates[].id/sync_id`는 **기존 비교 대상 observation**, `candidates[].judgment_id`는 이 saved→candidate pair의 **relation `rel-…` sync_id**다. top-level judgment_id는 첫 후보의 convenience alias이며 다른 후보에게 재사용하면 안 된다. [E-save], [E-candidate]
- title에서 만든 OR FTS query가 corpus BM25 rank를 얻고 같은 project/scope·not deleted·not self·양방향 already-judged relation 제외 조건을 적용한다. MCP save는 relevance gate를 켠다: 같은 topic key 또는 두 개 이상 distinct title term 공유, 혹은 양쪽 모두 한 term이고 그 term이 같은 경우다. **내용의 incidental FTS match만으로 후보가 되지 않게 만든 deterministic rule**다. 기본 candidate limit은 3이고 `<=0`도 3으로 처리한다. [E-rank], [E-relevance]
- 후보 응답에는 title/type/topic_key/score/IDs만 있으며 full content·원문 spans는 없다. 도구 설명의 `mem_get_observation`은 full content를 얻는 경로지만 caller가 반드시 이를 실행했는지 store가 검증하지 않는다. [E-save], [E-tools]
- `FindCandidates`는 observation save transaction 바깥에서 pair별 INSERT한다. 전체 후보 집합을 하나의 atomic transaction으로 commit하는 경로가 아니고, INSERT 실패는 로그 후 그 후보를 skip한다. [E-candidate]
- **재응답 함정:** pending pair가 이미 있으면 conditional INSERT `WHERE NOT EXISTS`가 0 rows여서 candidate를 응답에 넣지 않는다. judged pair는 query 단계에서 제외하고, pending pair는 query에 잡혀도 insert 단계에서 제외한다. 따라서 같은 observation을 다시 save하여 동일 pair를 다시 찾는다고 durable pending judgment IDs를 재발급/재열거하는 것은 아니다. 이는 코드 추론이며 실제 재시도 실험은 하지 않았다. [E-candidate], [E-rank]

### 1.3 mem_judge / mem_compare: useful decision·증거·승인의 경계

- 허용 verdict는 `related | compatible | scoped | conflicts_with | supersedes | not_conflict`다. `retain/exclude/duplicate`라는 별도 verdict는 없다. `pending` 자체도 제출 가능한 verdict가 아니다. [E-judge]
- `mem_judge`의 `reason/evidence`는 optional string이다. evidence는 JSON **문자열 또는 free text**로 전달·저장하며 JSON decode, 원문 quote 포함 여부, message/speaker/span offsets/hash 일치 검증을 하지 않는다. `marked_by_actor/kind`는 MCP handler가 모두 `agent`로 지정하고 model ID는 빈 문자열이다. `session_id`도 caller optional 문자열이다. provenance 라벨은 signed human approval이 아니다. [E-handler], [E-judge]
- 지침은 confidence <0.7 또는 architecture/policy/decision의 supersedes/conflicts_with일 때 user에게 물으라고 한다. **이 조건을 store/handler가 enforce하는 승인 gate는 아니다.** `mem_judge`는 바로 관계를 갱신한다. [E-tools], [E-handler]
- `JudgeRelation`은 relation row를 `judged`로 갱신하고 enrolled source project일 경우 동일 transaction 안에 cloud sync mutation을 기록한다. observation content/delete/review_after를 변경하지 않는다. 저장된 supersedes도 **관계 annotation**이며 old fact를 숨기거나 교체하는 Memharness revise와 다르다. FTS search 구현에는 not-deleted/type/project/scope filter만 있고 supersedes exclusion이 없다. [E-judge], [E-search]
- `not_conflict`도 durable judged 관계이므로 이후 이 pair 후보 검색에서 제외된다. “아무것도 안 저장”이라는 no-op가 아니다. 동일 judgment_id 재판정은 기존 reason/evidence/confidence/provenance를 덮어쓴다. append-only judgment audit log는 이 함수에 없다. [E-judge], [E-rank]
- `mem_compare`는 외부에서 이미 판단한 two observation IDs + relation/confidence/reasoning을 받아 `JudgeBySemantic`으로 기록한다. 양방향 pair에 row가 있으면 같은 sync_id를 쓰되 source/target 방향을 입력 방향으로 갱신한다. provenance는 `marked_by_actor=engram`, `kind=system`, caller가 제공한 model을 저장한다. **system 라벨은 서버가 실제 모델을 실행했다는 증거가 아니다.** [E-compare]

### 1.4 no-op / malformed / failure 및 문서 불일치

| 경우 | 관측된 처리 | no-op와 차이 |
|---|---|---|
| title/content 없음, invalid relation, unknown judgment_id, 두 nonempty project 불일치 | tool IsError; judge update 전에 reject 또는 transaction rollback | 성공·제외 판단으로 취급 불가 |
| duplicate save | 기존 ID + counter/time/sync 변경 | 새 row 없음 != strict no-op |
| topic_key update | prior version 저장 + in-place update | 자동 patch, conflict 판단보다 먼저 수행 |
| `not_conflict` | durable judged relation | negative verdict를 기록한 성공 |
| candidate lookup/INSERT 실패 | save 성공 + log; 후보 없으면 judgment_required=false | 오류가 “conflict 없음”처럼 보일 수 있음 |
| store `OperationID` exact replay | 동일 fingerprint이면 ledger의 ID를 반환하고 transaction 내 observation 재변경 생략 | MCP handleSave는 OperationID를 넘기지 않으므로 이 no-op를 MCP save의 기본 계약으로 주장 불가 |

두 가지 설명/코드 불일치도 중요하다. `mem_judge` description은 confidence default 1.0이라고 하지만 optional confidence가 빠지면 handler는 nil pointer를 전달하고 SQL에는 null이 저장된다. 잘못된 타입의 optional reason/evidence/confidence는 type assertion 때문에 생략되는 경우가 있다. confidence 범위 검사는 MCP handler에는 있으나 `JudgeRelation` store 함수에는 별도 검사하지 않는다. `mem_compare` description은 reasoning max 200 chars라고 하지만 읽은 handler/store 경로에는 그 길이 enforcement가 없다. [E-tools], [E-handler], [E-judge], [E-compare]

cross-project guard도 “다른 프로젝트의 두 유효한 endpoint”를 거부하는 수준이다. 두 endpoint의 project가 모두 nonempty일 때만 다름을 reject한다. 비어 있거나 로컬 observation이 없는 경우를 항상 fail-closed하는 endpoint authorization으로 보아서는 안 된다. [E-guard]

### 1.5 원문 보존과 borrowing

`observation_versions`는 overwrite 전 observation title/content를 보존하지만 원 대화 turn을 보존·검증하는 장치는 아니다. `CapturePromptForSave`는 runtime의 현재 prompt가 있고 capture가 enabled이면 **독립 prompt row**를 저장하며 observation-ID link는 없다; false/empty는 intentional no-op, capture error는 nonfatal이다. 따라서 “source를 반드시 보존했다”는 보장이 아니다. [E-version], [E-prompt]

**차용:** pair별 candidate IDs와 reasoned negative verdict의 영속화; observation identity와 judgment identity 분리; lexical prefilter는 모델 inference 없이 사용 가능. **그대로 못 차용:** save-first를 의미 판단 완료나 필수 규칙 승인과 혼동하지 말 것. 검토 후보를 durable하게 보관하는 것과 실제 사용 자격은 분리해야 한다. caller retain/create/patch/no-op/conflict-hold의 별도 결과, 원문 spans, publication fence를 보존한다. title/topic_key auto-upsert를 의미적 approval로 간주하거나 swallowed detection error를 no-conflict로 반환하지 않는다. 명시적 승인은 기존 계약이 요구하는 규칙 활성화·권한 변경에 적용하며 모든 optional fact create에 새 인간 gate를 추가하지 않는다.

## 2. codex-agent-mem — rule-driven retain/exclude + 비파괴 repair overlay

### Sourceflow miniature

```text
host event envelope + raw payload
  → upsert project/session/turn: raw_payload + input/assistant/tool events + hash 저장
  → classify_event = HeuristicSummarizer (모델 호출 아님)
  → observations INSERT OR IGNORE + 신규 row provenance 연결

caller가 mem_policy_validate/add 또는 mem_repair_propose/apply 호출
  → policy validation → normalized selector/rule durable memory_policies INSERT
  → health duplicates/stale/contradictions → proposal
       duplicates/stale: supported_apply=true, observation_ids
       contradiction: review_contradictions, supported_apply=false
  → apply 지원된 proposal: repair_events(after_ref.exclude_ids, approved=1) INSERT
  → evaluate_policy_effects: tag/keep/never-archive/excluded key sets 계산
  → search/context pack이 sets를 적용; original observations/turns는 유지
```

[E와 다른 결정형태] 중요한 것인지 LLM에게 물어보는 judge가 아니다. caller가 선언한 selector 기반 policy가 기존 memory를 **pack/retrieval에서 유지·제외**하며 aging과 repair를 deterministic하게 적용한다. [C-policy], [C-policy-db], [C-repair], [C-ingest]

### 2.1 실제 rules·precedence

`selector_matches`는 types/statuses/ids를 해당 값과 exact 비교, text_contains는 lowercased item text의 모든 substring 포함, tags는 요구 집합과 하나라도 교집합이 있는지 검사한다. 필터 종류 사이에는 AND다. tag_as를 먼저 순서대로 적용하므로 tag 기반 후속 매칭에 영향을 줄 수 있다. policy마다 matched IDs가 `observation:<id>` 또는 `decision:<id>` key로 나온다. [C-policy]

실제 effect는 다음 식이다.

```text
archive_excluded = auto_archive_after의 stale 대상 ∪ approved repair exclude IDs
retrieval_excluded = archive_excluded - never_archive
pack_excluded = explicit exclude_from_pack ∪ retrieval_excluded
keep_priority = always_keep_priority - pack_excluded
```

즉 never_archive는 aging/repair exclusion을 막지만 **explicit exclude_from_pack은 막지 않는다.** always_keep_priority는 excluded item을 부활시키지 않는다. auto_archive_after는 `updated_at`을 사용하며 invalid/missing ISO면 stale=false다. original observation에 archived status를 UPDATE하는 함수가 아니라 derived sets/filter이다. [C-policy], [C-governance]

**문서/구현 경계:** validation은 `apply_to`를 normalize하고 default `pack/retrieval/repair` scopes를 저장한다. 그러나 `evaluate_policy_effects`는 `apply_to`를 읽지 않는다. 이 field가 enforcement된 scope control이라고 말할 수 없다. validation은 invalid integer IDs를 조용히 제거하고 빈 filter면 non-tag policy를 invalid로 반환한다. 알 수 없는 kind/positive days 없는 auto_archive 등은 invalid; `mem_policy_add`는 invalid에 ValueError이고 MCP는 IsError=true로 변환한다. 이것은 정상 exclusion/no-match가 아니다. [C-policy], [C-policy-db], [C-mcp]

### 2.2 duplicate / conflict / review / approved의 의미

- health duplicate는 **type + normalize_state_text(summary/detail/title)** bucket이다. arbitrary semantic equivalence 모델 판단이 아니다. duplicate proposal은 목록 첫 ID는 남기고 나머지 중 never_archive 보호 없는 observation IDs를 archive overlay로 제안한다. [C-health], [C-repair]
- stale proposal은 health report의 stale summaries와 operational observation summary를 맞춰 IDs를 만든다. conflict는 pending↔completed, blocker↔completed의 text match 및 closure mismatch처럼 **운영 상태 상충**이다. 일반 두 장문의 semantic contradiction judge를 구현한 것으로 확장해서 해석하지 않는다. [C-health]
- contradiction과 DoD gap은 `supported_apply=false`, `reason=manual_review_required`다. `apply_repair`는 이를 ValueError로 reject한다. proposal은 조회 시 derived object이고, report가 없으면 writable 호출에서 health report를 기록할 수 있다. “review 필요”가 원본 observation의 durable pending status로 전이되는 것은 아니다. [C-repair]
- 지원된 repair를 apply하면 repair event에 `approved=1`을 **함수 자체가 literal로 저장**한다. 요청에는 approver identity/signature/user message/span을 요구하지 않고, 기록 provenance는 프로젝트 최신 turn을 가져온다. 따라서 이 boolean은 우리 signed approval 증거가 아니다. 최신 turn 연결은 approval utterance의 정확한 원문 link도 아니다. 호출자의 실제 인가 여부를 소스에서 추정하지 않는다. [C-repair], [C-mcp]
- repair 뒤 원본 rows를 delete/update하지 않고 이후 governance 계산에서 제외한다. 같은 proposal 반복 apply의 existing-event/idempotency 검사는 이 함수에 없어 매번 repair row를 더 만들 수 있다. `list_repairs` limit=50을 통해 approved repairs를 가져오는 점도 무기한 exclusion policy 기록과는 다르다. [C-repair], [C-governance]

### 2.3 원문과 provenance는 있는가

`upsert_turn`은 caller-supplied timestamp, input messages JSON, assistant message, tool events JSON, raw payload JSON, sorted-JSON SHA-256 content_hash를 저장한다. `get_provenance`는 observation의 turn reference를 join해 **실제 저장된 source_turn 원문 payload**를 돌려준다. 이 셋 중 raw conversation linkage의 가장 직접적인 힌트다. [C-turn], [C-provenance]

그러나 `upsert_observation`의 `source_span`은 `{source_kind, observation_type, title, files}`다. offset/length/exact quote/hash 조건을 검증하지 않는다. `record_provenance`는 받은 dictionary를 JSON으로 INSERT OR REPLACE한다. `model_name`은 event metadata에서 가져오는데 extraction은 HeuristicSummarizer이므로 **host model metadata 존재 != 그 model이 해당 memory useful decision을 내림**이다. [C-observation], [C-provenance]

단계별 `with self.conn`이 분리되어 있어 raw turn과 observation, files/decision, provenance가 하나의 atomic admission transaction은 아니다. provenance write 전에 실패하면 앞선 raw/observation commit이 남을 수 있다. 또한 `(session, external_turn_id)` 재사용을 INSERT OR IGNORE로 처리하므로 동일 ID에 다른 payload를 보냈을 때 원래 raw turn은 유지된다. 이후 classify는 새 `event`를 사용하고 observation hash는 turn_id뿐 아니라 text를 포함하므로, 새 text observation이 원래 raw turn에 붙을 수 있다. **source-span 검증이 있었다는 주장을 하지 말아야 하는 중요한 정적 추론**이다. [C-turn], [C-ingest], [C-observation]

### 2.4 no-op·heuristic exclusions·caller 수동 메모

- `classify_event`는 `providers/noop.py`의 HeuristicSummarizer를 직접 사용한다. diagnostic prompt patterns가 맞으면 `extract_observations`는 `[]`를 반환하지만 raw turn은 이미 저장된다. 그 밖에는 session_summary와 정규식 라벨 기반 decision/operational items를 만든다. input/assistant의 출처는 코드로 구별하지만 model usefulness 판정은 아니다. 이름 `noop.py`가 “아무 계산도 하지 않는다”는 뜻도 아니다. [C-ingest], [C-heuristic]
- ingestion observation exact dedupe hash는 project/session/**turn** IDs와 type/title/summary/detail를 포함한다. cross-turn semantic no-op가 아니라 **동일 extraction replay** 억제다. `inserted_turn=false`, 동일 observation IDs는 성공 결과이지 malformed error가 아니다. project updated_at는 ingestion 때 갱신되므로 요청 전체 strict no-op로 단정하지 않는다. [C-turn], [C-ingest]
- caller `mem_note_create`는 normalized text/title/tags/project/session의 hash로 INSERT OR IGNORE하고 `created=false`와 기존 observation ID를 구분해 반환한다. raw turn 없이 저장하며 provenance에도 turn_id/hash/model은 null이다. 이는 approved caller가 중요 메모를 직접 선정하는 데 사용할 수 있는 모델 없는 저장 경로지만 **선정 근거·원문 speaker/span 의무를 저장 서버가 강제하지 않는다.** [C-note]
- retrieval dedupe는 normalized type/status/text의 SHA-256으로 반환 목록만 합치며 duplicate_session_ids/count 등을 enrichment한다. DB fact deletion/merge가 아니다. [C-retrieval]
- policy no-match는 empty matched_keys 성공; `remove_policy`에 없는 ID는 `removed=false` 성공. invalid definitions와 unsupported repair는 MCP IsError=true다. 다만 잘못된 `rule`/selector object 타입은 안전한 schema validation 대신 AttributeError 등으로 빠질 수도 있으며 MCP dispatcher는 일반 Exception도 error payload로 바꾼다. [C-policy], [C-policy-db], [C-mcp]

### 2.5 borrowing·우리와 다른 경계

**차용:** raw turn + hash + stable memory/provenance IDs, exclusions를 원본 파괴와 분리하는 overlay, repair proposal과 apply 분리, ordinary no-match/created=false와 IsError 구분. **못 차용:** 정책 효과를 model retain/exclude verdict로 명명하지 말 것. `approved=1`을 signed consent로 사용하지 말 것. 최신 turn을 arbitrary repair evidence로 엮거나 advisory provenance_confidence=high를 모델 판단 신뢰도로 사용하지 말 것. 우리에서는 exact original spans 및 actor-scoped 승인 artifacts를 검증하고 immutable decision event에 reference해야 한다. policy_engine의 `apply_to`를 실제 enforce한 것처럼 표기하지 않는 것이 특히 중요하다.

## 3. Memharness — 유사성 advisory, caller explicit revise, 독립 source freshness

### Sourceflow miniature

```text
caller remember(subject, fact, basis?, source_ref?, source_commit?, source_path?)
  → MCP size gate(>1500 chars: Not stored text, isError 없음)
  → nearDuplicates: 같은 exact subject의 current facts 읽기, lexical Jaccard
  → remember: new integer fact ID INSERT(유사/동일해도 blocking 없음)
  → Remembered #newID + similar #oldID/score advisory

caller가 모순/업데이트라고 판단하고 revise(old_fact_id, new_fact, source...)
  → transaction: old 존재·already-superseded·time 검증
  → 새 fact INSERT + old.valid_to/old.superseded_by UPDATE → COMMIT
  → old/new IDs; why는 ancestor/descendant chain 반환

cold staleness CLI(이 조사에서는 실행 안 함)
  → git HEAD/ancestor/path diff 관측 → classifyFreshness
  → setStaleness로 freshness/checked_at/checked_head만 UPDATE
  → recall ranking에서 stale/unresolved demote; 원문 factual assertion은 유지
```

근거: [M-core-write], [M-advisory], [M-mcp-write], [M-revise], [M-sql], [M-staleness].

### 3.1 유사 후보는 durable gate가 아니다

core `nearDuplicates`는 `clock.peek()`와 read-only query를 쓰며 source text·same-subject current facts의 significant token set Jaccard를 계산한다. default minSimilarity .5, core default limit 5, scanned cap 1000이다. core에 queryVector를 준 경우에만 sqlite-vec cosine similarity와 max를 취한다. **MCP remember caller는 queryVector를 넘기지 않아서 이 후보 생성은 hybrid enabled여도 lexical이다.** exact subject 경계 안에서만 비교하며 arbitrary cross-subject equivalence는 찾지 않는다. [M-advisory], [M-mcp-write]

서버가 insert 전에 후보를 계산하지만 **후보가 있으면 저장을 멈추는 게 아니다.** 바로 `mem.remember`를 호출한 뒤 candidate ID/score advisory를 응답에 붙인다. candidate list 자체와 conflict pending row는 저장하지 않는다. exact same fact를 remember한 경우도 INSERT 경로가 동일하므로 semantic no-op를 제공하지 않는다. 모델 retain/exclude 여부는 caller가 도구 호출 여부를 정하는 수준에 남는다. [M-core-write], [M-mcp-write]

basis의 user-stated/verified/reported/inferred는 각각 confidence 1/.95/.8/.6으로 매핑되는 **caller assertion**이다. default basis는 user-stated이고 confidence override도 가능하다. speaker 원문/span이나 verified evidence를 서버가 검사하지 않는다. source_ref도 optional free string이며 core default는 `""`; source_commit/source_path는 optional 저장 columns다. 어떤 지침에서 “항상 source_ref를 써라”라고 했다고 코드의 필수 source 의무가 구현된 것은 아니다. [M-mcp-write], [M-core-write]

### 3.2 durable revise와 raw history

`revise`는 old ID가 없으면 NotFoundError, 이미 superseded면 live chain head의 ID/내용을 인용한 ValidationError로 caller가 다시 판단하도록 한다. 새 사실을 insert한 뒤 old.valid_to를 new.valid_from으로 닫고 superseded_by=newID로 연결하는 transaction이다. subject/predicate와 kind/importance는 old에서 물려받지만 source_ref/commit/path는 **자동 상속하지 않는다**. confidence는 old에서 상속하지 않고 입력/default를 쓴다. old.fact·old.tx_at는 보존된다. [M-revise], [M-sql]

새 valid_from은 default txAt, 명시값이 미래이면 reject, old가 실제 backdated였을 때 그보다 더 앞서는 backdate도 reject한다. 학습시점만 있던 old에는 더 이른 correction을 허용해서 old empty interval이 될 수 있다. history model의 intentional semantics이지 exclude/no-op가 아니다. [M-revise]

same newFact인 경우 equality 검사는 없어서 새 ID와 chain을 만든다. conflict 여부는 caller의 old_fact_id 선택에 달렸고, approval/evidence reason을 별도 저장하지 않는다. `why`는 fact ancestry를 반환할 뿐 외부 대화의 exact quotation/spans를 검증하지 않는다. `forget`는 retracted_at만 표시하며 이미 retract됐거나 nonexistent ID면 0 count를 반환할 수 있다. core invalid fact/importance/kind/confidence/time는 typed error다. [M-revise], [M-forget], [M-sql]

MCP wrapper는 MemharnessError면 `isError=true`, 다른 exception은 rethrow한다. 반면 `remember`의 >1500-char gate는 **정상 text `Not stored: …`를 반환**하고 isError를 세우지 않는다. 따라서 “HTTP/MCP success == memory retained”는 성립하지 않는다. 이 refuse는 intentional exclusion보다 size validation refusal에 가깝고 structured outcome enum도 아니다. 또한 size gate는 읽은 `revise` handler에 적용되지 않는다. [M-errors], [M-mcp-write]

### 3.3 vectors disabled·모델 inference 경계를 source로 확인

이 SHA에서 실제 toggle은 다음과 같다. [M-index], [M-db]

- core open은 `loadVecExtension`을 시도하고 실패 catch시 vecEnabled=false로 FTS-only가 된다. **sqlite-vec native extension의 거리 계산은 LLM/embedding model inference가 아니다.**
- MCP index는 `MEMHARNESS_HYBRID === "1" && mem.vecEnabled`일 때만 `@memharness/embed`를 dynamic import하고 provider를 연결한다. flag unset이면 embed provider가 없다. package import 실패 또는 vec load 실패도 stderr 안내 후 FTS-only다. **환경 toggle 없는 회사 경로에 local embedding model을 설치해야 한다는 것은 아니다.** 그러나 native sqlite/better-sqlite3/vec 실행 허가가 실제로 있는지는 이 소스로 판단할 수 없다.
- hybrid가 켜지고 provider가 존재하면 server recall은 embedding backfill과 query embedding을 수행한다. provider의 model은 optional local embedding package로 공급된다. 이 경로는 회사의 local ML 설치 불가 계약에서 그대로 사용할 수 없다. core remember/revise에 모델이 없다는 것과 서버 전체 hybrid path에 모델이 없다는 것은 다른 주장이다. [M-index], [M-backfill]
- Engram normalized SHA-256/FTS trigram과 codex-agent-mem SHA-256, Memharness token Jaccard는 deterministic 계산이다. **hash·trigram이라는 말만으로 local ML inference라고 분류하지 않는다.** 이 보고서에서 학습된 embedding 모델 없는 hashed vector 구현을 따로 확인했다고 주장하지도 않는다.

### 3.4 source freshness와 명확한 불확실성

core `classifyFreshness`는 unknown SHA→unresolved, same HEAD→current, nonancestor→unresolved, ancestor with changed path/whole-repo pin→stale, unchanged path→current다. `setStaleness`는 freshness/checked_at/checked_head 및 optional source pin만 갱신하며 fact/confidence/tx_at/validity를 바꾸지 않는다. stale/unresolved는 recall score multiplier이지 automatic exclude, truth correction, candidate usefulness judgment가 아니다. unchecked/null은 neutral이지 검증 완료가 아니다. [M-staleness], [M-set-stale], [M-sql]

`parseSourceRef`는 opaque repo@SHA[:path] 또는 standalone SHA-looking token을 파싱하지만 실제 repo ownership/auth/원문 content hash/span 검증이 아니다. CLI worklist는 source_commit IS NOT NULL을 요구해서 **free-text source_ref만으로 모든 사실의 SHA를 자동 backfill한다는 주장은 틀리다.** CLI는 matching pin에 source_path를 refine하는 branch를 가진다. [M-staleness], [M-cold], [M-sql]

읽은 cold CLI에는 다음 구현 위험도 있다(모두 정적 추론·미실행).

1. `stalenessTargets(limit)`는 같은 live pinned rows를 `ORDER BY id LIMIT`로 반복 반환하며 checked_at로 제외하거나 offset/cursor를 받지 않는다. CLI는 write mode에서 full 200-row page일 때 루프를 계속한다. setStaleness가 worklist membership를 바꾸지 않으므로 **live pinned 200개 이상이면 첫 페이지 반복 가능성**이 있다. 주석의 paging 표현과 구현이 불일치한다.
2. ancestor + nonempty path일 때 diff exit 1만 pathChanged=true이고 그 외 exit, 오류 포함은 false로 둔다. 따라서 diff error가 current로 분류될 위험이 있다. pure helper가 unknown→unresolved를 보장한다고 실제 subprocess error mapping까지 완전히 fail-closed라고 말할 수 없다.

두 점은 source-driven borrowing에서 tri-state 분류뿐 아니라 input-observation의 오류 state와 worklist cursor까지 검토해야 한다는 힌트다. 우리 조사는 git command를 실제 실행하지 않았다. [M-cold], [M-sql]

### 3.5 borrowing·우리와 다른 경계

**차용:** title 동일성 아닌 same-subject content candidate retrieval, explicit exact old ID를 통한 append-successor revision, old payload 보존, source freshness를 사실 validity와 독립 축으로 다루기. **그대로 못 차용:** advisory 후 unconditional create는 duplicate/conflict hold gate가 아니다. source_ref의 존재를 원문span 검증으로 바꾸어 읽지 말 것. caller basis=verified는 signed approval이나 server verification이 아니다. 우리에서는 후보를 create 전에 frozen evidence artifact로 저장하고 approved caller decision을 요구할 수 있지만, 이는 OSS에 이미 있다는 주장이 아니라 우리 borrowing 설계다.

## 4. Evidence / missing 매트릭스

| 계약 질문 | Engram | codex-agent-mem | Memharness |
|---|---|---|---|
| useful retain/exclude의 결정 주체 | caller가 mem_save 선택; 관계 의미는 caller judge | caller 정책·수동 note + regex extraction; exposure는 deterministic rule | caller가 remember/revise 선택; 유사성은 advisory |
| 신규 save 전 durable review 후보 | 없음: observation부터 commit | raw turn 먼저 저장; repair proposal은 derived, 보고서는 별도 durable 가능 | 없음: nearDuplicates read-only |
| save 후 durable pending/hold | pair별 pending relation; observation은 활성 유지 | contradiction supported_apply=false; 원본 pending admission state 아님 | 없음; 같은 유사 fact도 저장 |
| stable candidate/decision identity | obs int/sync ID + pair rel judgment_id | observation IDs + policy IDs/health report ID/repair event ID | fact IDs; advisory candidate는 existing fact ID |
| 이름 아닌 유사성 | title term/topic gate+FTS candidate, caller 의미 판단 | normalized text/hash와 운영 text matching | same-subject token Jaccard; core optional cosine |
| strict no-op | store OperationID replay만; MCP 미연결. duplicate는 counter update | note created=false / exact extraction replay, retrieval collapse; 요청 전체 no-op와 구분 | remember/revise equality no-op 없음; forget 0 count는 가능 |
| patch/supersede | topic-key overwrite+snapshot; judge supersedes는 relation annotation | exclusion overlay; 이 경로에 semantic patch 없음 | append new fact+old validity closure+chain |
| 원 대화 payload | optional independent runtime prompt, observation-ID link 없음 | raw turn JSON + hash + join 가능 | caller fact 문자열/source_ref; raw turn store 아님 |
| 검증된 original span | 읽은 경로에 없음; free-text evidence | 이름 source_span이지만 descriptor JSON, offset/quote 검증 없음 | 없음; optional source fields |
| model judgment의 provenance | mem_judge actor=agent/model 없음; compare system label/caller model | host metadata model과 heuristic extraction 구분 필요 | caller basis mapping; ML adjudicator 없음 |
| signed approval | 지침의 ask-user만; handler/store signature gate 없음 | approved=1 literal; signed consent 아님 | 없음 |
| malformed와 정상 제외 구분 | 기본 IsError; candidate detection failure는 save success로 삼켜짐 | invalid policy/unsupported repair IsError; no-match는 success | core typed error; oversized remember는 성공 text refusal |
| 회사 local ML 불가 적용 | 읽은 MCP save/judge/compare 경로는 서버 ML 필요 없음; 실제 caller 승인 미확인 | 읽은 ingestion/policy/note 경로는 heuristic·SQLite; 실제 host 승인 미확인 | default provider 없음을 확인; hybrid local model path는 부적합, native 실행 허가는 별도 |

위의 “없음”은 **명시적으로 읽은 대상 control flow에 없다는 뜻**이다. 저장소 전체의 모든 보안/approval 기능이 없다는 exhaustive negative claim은 아니다. runtime 정확도, conflict recall/precision, malformed fuzzing, 후보 손실 빈도, durable recovery, model cost/latency는 미측정이다.

## 5. 우리 계약에 맞춘 borrowing 결론

다음은 **[설계 제안]**이며 위 OSS의 구현 사실과 구별한다.

1. host 원문과 speaker/time/session metadata를 immutable source artifact로 보존하고 candidate는 해당 artifact의 exact spans/hash를 reference한다. source transport metadata는 사실 관측일 뿐 useful decision이 아니다.
2. deterministic hash/FTS/Jaccard 등은 모델 없는 후보 생성·명백한 replay 분류에 사용한다. lexical 후보 없음과 의미적 no-conflict/no-op 판정을 합치지 않는다.
3. 회사에서는 승인된 Claude/Codex caller 또는 허가된 team-native 실행만 judge 역할을 맡긴다. “이 OSS가 Claude를 지원한다”는 실제 회사 승인의 증거가 아니다. 개인 Jev 경로는 가능해도 회사 원문을 개인 backend로 fallback하는 설계를 넣지 않는다.
4. caller useful result(retain/exclude/review-required)와 merge operation(no-op/create/patch/conflict-hold)을 서로 다른 typed result/state로 기록한다. 외형 3분류를 OSS 명칭에 맞추어 억지로 mapping하지 않는다.
5. pair별 stable decision IDs(Engram), non-destructive visibility overlay(codex-agent-mem), immutable successor history(Memharness)를 조합한다. decisions에는 exact evidence refs와 판단 actor/model을 결합하고, apply는 기존 authenticated grant·publication fence 및 연산별 승인 계약을 지킨다. **규칙 활성화의 명시적 승인과 일반 optional fact 처리를 분리한다.** metadata/자기보고 confidence/system label/approved boolean을 인간 승인으로 승격하지 않으며 모든 fact 저장에 새 인간 서명을 요구하지 않는다.
6. detection unavailable/malformed/authorization missing을 정상 no-op/exclude와 별도 오류 상태로 반환한다. saved-first state가 있으면 그 사실과 아직 미판정임을 노출한다. oversized success text refusal·swallowed detection error·pending re-enumeration 누락 같은 ambiguity를 우리 결과 envelope에서 피한다.

## 6. SHA-pinned source index

### Engram

[E-save]: https://github.com/Gentleman-Programming/engram/blob/5c4171845958f046968c14d7d57a325eb4a83b7e/internal/mcp/mcp.go#L1474-L1689
[E-tools]: https://github.com/Gentleman-Programming/engram/blob/5c4171845958f046968c14d7d57a325eb4a83b7e/internal/mcp/mcp.go#L1054-L1139
[E-handler]: https://github.com/Gentleman-Programming/engram/blob/5c4171845958f046968c14d7d57a325eb4a83b7e/internal/mcp/mcp.go#L2609-L2676
[E-add]: https://github.com/Gentleman-Programming/engram/blob/5c4171845958f046968c14d7d57a325eb4a83b7e/internal/store/store.go#L4069-L4275
[E-content]: https://github.com/Gentleman-Programming/engram/blob/5c4171845958f046968c14d7d57a325eb4a83b7e/internal/store/store.go#L4789-L4823
[E-version]: https://github.com/Gentleman-Programming/engram/blob/5c4171845958f046968c14d7d57a325eb4a83b7e/internal/store/store.go#L12050-L12061
[E-hash]: https://github.com/Gentleman-Programming/engram/blob/5c4171845958f046968c14d7d57a325eb4a83b7e/internal/store/store.go#L13195-L13200
[E-state]: https://github.com/Gentleman-Programming/engram/blob/5c4171845958f046968c14d7d57a325eb4a83b7e/internal/store/store.go#L185-L211
[E-candidate]: https://github.com/Gentleman-Programming/engram/blob/5c4171845958f046968c14d7d57a325eb4a83b7e/internal/store/relations.go#L364-L535
[E-rank]: https://github.com/Gentleman-Programming/engram/blob/5c4171845958f046968c14d7d57a325eb4a83b7e/internal/store/relations.go#L1104-L1162
[E-relevance]: https://github.com/Gentleman-Programming/engram/blob/5c4171845958f046968c14d7d57a325eb4a83b7e/internal/store/candidate_relevance.go#L38-L88
[E-judge]: https://github.com/Gentleman-Programming/engram/blob/5c4171845958f046968c14d7d57a325eb4a83b7e/internal/store/relations.go#L621-L746
[E-guard]: https://github.com/Gentleman-Programming/engram/blob/5c4171845958f046968c14d7d57a325eb4a83b7e/internal/store/relations.go#L748-L773
[E-compare]: https://github.com/Gentleman-Programming/engram/blob/5c4171845958f046968c14d7d57a325eb4a83b7e/internal/store/relations.go#L774-L929
[E-search]: https://github.com/Gentleman-Programming/engram/blob/5c4171845958f046968c14d7d57a325eb4a83b7e/internal/store/store.go#L5875-L5902
[E-prompt]: https://github.com/Gentleman-Programming/engram/blob/5c4171845958f046968c14d7d57a325eb4a83b7e/internal/store/prompt_capture.go#L5-L17

### codex-agent-mem

[C-policy]: https://github.com/MarceloCaporale/codex-agent-mem/blob/d594c8a86207fb9a8a5b48a6aab323349680707a/src/codex_agent_mem/policy_engine.py#L84-L296
[C-policy-db]: https://github.com/MarceloCaporale/codex-agent-mem/blob/d594c8a86207fb9a8a5b48a6aab323349680707a/src/codex_agent_mem/db.py#L2360-L2439
[C-repair]: https://github.com/MarceloCaporale/codex-agent-mem/blob/d594c8a86207fb9a8a5b48a6aab323349680707a/src/codex_agent_mem/db.py#L2652-L2785
[C-governance]: https://github.com/MarceloCaporale/codex-agent-mem/blob/d594c8a86207fb9a8a5b48a6aab323349680707a/src/codex_agent_mem/db.py#L2572-L2574
[C-ingest]: https://github.com/MarceloCaporale/codex-agent-mem/blob/d594c8a86207fb9a8a5b48a6aab323349680707a/src/codex_agent_mem/db.py#L1021-L1064
[C-turn]: https://github.com/MarceloCaporale/codex-agent-mem/blob/d594c8a86207fb9a8a5b48a6aab323349680707a/src/codex_agent_mem/db.py#L662-L703
[C-observation]: https://github.com/MarceloCaporale/codex-agent-mem/blob/d594c8a86207fb9a8a5b48a6aab323349680707a/src/codex_agent_mem/db.py#L768-L883
[C-provenance]: https://github.com/MarceloCaporale/codex-agent-mem/blob/d594c8a86207fb9a8a5b48a6aab323349680707a/src/codex_agent_mem/db.py#L1757-L1828
[C-note]: https://github.com/MarceloCaporale/codex-agent-mem/blob/d594c8a86207fb9a8a5b48a6aab323349680707a/src/codex_agent_mem/db.py#L885-L1020
[C-retrieval]: https://github.com/MarceloCaporale/codex-agent-mem/blob/d594c8a86207fb9a8a5b48a6aab323349680707a/src/codex_agent_mem/retrieval_hygiene.py#L74-L152
[C-heuristic]: https://github.com/MarceloCaporale/codex-agent-mem/blob/d594c8a86207fb9a8a5b48a6aab323349680707a/src/codex_agent_mem/providers/noop.py#L212-L272
[C-health]: https://github.com/MarceloCaporale/codex-agent-mem/blob/d594c8a86207fb9a8a5b48a6aab323349680707a/src/codex_agent_mem/health.py#L27-L120
[C-mcp]: https://github.com/MarceloCaporale/codex-agent-mem/blob/d594c8a86207fb9a8a5b48a6aab323349680707a/src/codex_agent_mem/mcp_stdio.py#L958-L1009

### Memharness

[M-core-write]: https://github.com/las7/memharness/blob/faed4b346e445d2344ed02e8211759999acd946d/packages/core/src/memory.ts#L349-L372
[M-advisory]: https://github.com/las7/memharness/blob/faed4b346e445d2344ed02e8211759999acd946d/packages/core/src/memory.ts#L384-L429
[M-revise]: https://github.com/las7/memharness/blob/faed4b346e445d2344ed02e8211759999acd946d/packages/core/src/memory.ts#L577-L656
[M-forget]: https://github.com/las7/memharness/blob/faed4b346e445d2344ed02e8211759999acd946d/packages/core/src/memory.ts#L676-L707
[M-set-stale]: https://github.com/las7/memharness/blob/faed4b346e445d2344ed02e8211759999acd946d/packages/core/src/memory.ts#L298-L323
[M-sql]: https://github.com/las7/memharness/blob/faed4b346e445d2344ed02e8211759999acd946d/packages/core/src/sql.ts#L4-L169
[M-staleness]: https://github.com/las7/memharness/blob/faed4b346e445d2344ed02e8211759999acd946d/packages/core/src/staleness.ts#L1-L93
[M-mcp-write]: https://github.com/las7/memharness/blob/faed4b346e445d2344ed02e8211759999acd946d/packages/mcp/src/server.ts#L202-L322
[M-errors]: https://github.com/las7/memharness/blob/faed4b346e445d2344ed02e8211759999acd946d/packages/mcp/src/server.ts#L187-L200
[M-backfill]: https://github.com/las7/memharness/blob/faed4b346e445d2344ed02e8211759999acd946d/packages/mcp/src/server.ts#L112-L157
[M-index]: https://github.com/las7/memharness/blob/faed4b346e445d2344ed02e8211759999acd946d/packages/mcp/src/index.ts#L39-L82
[M-db]: https://github.com/las7/memharness/blob/faed4b346e445d2344ed02e8211759999acd946d/packages/core/src/db.ts#L67-L81
[M-cold]: https://github.com/las7/memharness/blob/faed4b346e445d2344ed02e8211759999acd946d/packages/mcp/src/staleness.ts#L83-L189
