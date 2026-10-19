# MCP 메모리 OSS의 서버·모델 결정 경로 — 고정 소스 조사

## 0. 요약

- **LangMem**: 검색으로 가져온 기존 기억과 대화를 함께 Trustcall extractor에 제공한다. 모델이 insert/update/remove를 구성하고, `MemoryStoreManager`가 기존 값과 최종 값의 **정확한 equality**를 비교하여 불필요한 put을 생략한다. `MemoryManager` 자체는 저장하지 않는다. quote를 “when necessary” 하라는 프롬프트와 달리 기본 스키마에는 원문 citation/span/hash 필드가 없다. store wrapper는 승인 없이 직접 put/delete한다.
- **mnema**: 추출 후보 preview와 LLM 없는 apply를 분리하고, 별도 batched contradiction judge의 결과를 `unresolved` relation으로 저장한다. 원본 파일 SHA-256, 실제 message UUID, redacted excerpt/hash, 모델·프롬프트 버전을 저장한다. fabricated citation ID를 제거하는 실제 검증은 있으나, **본문이 근거에서 entail되는지 검증하지 않는다**. MCP `resolve_preview → resolve_commit`은 content-bound 확인 토큰을 검사하지만 **인간의 signed approval은 아니다**.
- **Mem0는 버전 구분이 필수**: 조사 시 `main` Atom 최상단 SHA의 OSS `Memory.add(infer=True)`는 **단일 LLM ADD-only pipeline**이다. ADD/UPDATE/DELETE/NONE는 과거 v1.0.0 SHA에서 실제 실행되며, current `prompts.py`에 과거 4-operation prompt가 남아 있다고 해서 current add가 그것을 사용한다고 말하면 틀린다. current add docstring의 update/delete 설명도 구현과 다르다.
- **Mem0 MCP도 두 경로가 다르다**: 과거 OpenMemory MCP는 OSS `Memory.from_config`를 호출한다. 별도 `mem0ai/mem0-mcp`의 조사 시 SHA는 archived API wrapper이며 `MemoryClient`로 플랫폼을 호출한다. 이 MCP와 OSS add 구현을 동일한 실행 경로로 연결해서 설명하면 안 된다.

아래 내용은 HTTP/GitHub raw 파일 정적 조사다. 모델 호출, 설치, clone, build, lint, formatter, test, 실제 MCP 실행을 하지 않았다. optional basic-memory는 이번 보고서에서 조사하지 않았다.

## 1. 조사 범위·고정 revision·라이선스

| 코드 | 고정 revision | 의미 |
|---|---|---|
| langchain-ai/langmem | `48e3c11f5bb527282c7d5339c6a87a0b35abccfc` | 지정된 extraction.py 및 관련 utils/dependency |
| Ray0907/mnema | `eed19586156ae9664451cb94859f8f3f16b3ac4a` | 지정된 conflict/store/MCP, 실제 연결되는 distill/schema/canonical/CLI/LLM/db/transcript |
| mem0ai/mem0 current 관측 | `b7ad69afda6b6ed030347c66d48a13e4de9dec08` | main Atom feed에서 최상단 commit을 얻고 모든 본문은 이 SHA로 고정; pyproject `2.2.1`, Apache-2.0 |
| mem0ai/mem0 과거 비교 | `394203d1b5f56385d28690ea27c0d746007ff940` | v1.0.0 Atom 최상단 commit; ADD/UPDATE/DELETE/NONE의 실제 구현 및 당시 OpenMemory MCP; Apache-2.0 |
| mem0ai/mem0-mcp | `624024deacbbe1948572a968abdb9d9e93ded548` | main Atom 최상단; pyproject `0.2.1`, Apache-2.0; pinned README는 archived라고 명시 |

GitHub API `commits/HEAD` 및 recursive tree는 HTTP 403이었으므로 Atom feed와 GitHub 정적 tree로 대체했다. “current”는 조사 때 가져온 main feed의 관측값이지 이후 main까지 보장하는 표현이 아니다.

근거: [current Mem0 commit](https://github.com/mem0ai/mem0/commit/b7ad69afda6b6ed030347c66d48a13e4de9dec08), [current pyproject](https://github.com/mem0ai/mem0/blob/b7ad69afda6b6ed030347c66d48a13e4de9dec08/pyproject.toml#L5-L24), [current LICENSE](https://github.com/mem0ai/mem0/blob/b7ad69afda6b6ed030347c66d48a13e4de9dec08/LICENSE), [historical LICENSE](https://github.com/mem0ai/mem0/blob/394203d1b5f56385d28690ea27c0d746007ff940/LICENSE), [MCP pyproject](https://github.com/mem0ai/mem0-mcp/blob/624024deacbbe1948572a968abdb9d9e93ded548/pyproject.toml#L5-L43), [MCP LICENSE](https://github.com/mem0ai/mem0-mcp/blob/624024deacbbe1948572a968abdb9d9e93ded548/LICENSE), [archived README](https://github.com/mem0ai/mem0-mcp/blob/624024deacbbe1948572a968abdb9d9e93ded548/README.md).

## 2. 분류명이 아닌 실제 상태·연산 매핑

| 관심사 | LangMem | mnema | Mem0 과거 4-op | Mem0 current ADD-only |
|---|---|---|---|---|
| 기억할 후보 | extractor의 새 structured Memory | run.json `candidates` | 첫 LLM `facts`, 둘째 LLM `ADD` | LLM `memory[].text` |
| 제외/기억할 것 없음 | 새 extraction 없음; 기존 값 유지 | prompt 제외 + 실제 invalid IDs/over-limit drop + accept 제외 | facts 빈 배열; action `NONE`; omitted action | 빈 `memory`, text 누락, exact-hash duplicate |
| 검토 필요 | 별도 pending review 없음 | conflict relation `unresolved`, 오류 `error` | 별도 conflict pending 없음 | 별도 conflict pending 없음 |
| create | 새로운 ID를 namespace에 put | candidate apply 또는 direct add → canonical 파일 | `_create_memory` → vector insert/history ADD | batch insert/history ADD |
| patch/update | 기존 stable ID의 최종 content를 put | 모델 patch 없음; 수동 편집은 manual_revision | `_update_memory` → vector overwrite/history UPDATE | add에서 없음; explicit `update()`는 존재 |
| no-op | store kind/content 정확히 같으면 put 안 함 | candidate_key 또는 op_key replay; conflict=false는 relation 안 만듦 | NONE는 content 유지하되 session metadata를 쓸 수 있음 | model semantic skip + 서버 text MD5 exact dedup |
| delete/충돌 보류 | RemoveDoc → store delete(허용 시); 보류 아님 | 두 기억 유지 + unresolved relation; keep loser는 downweight | DELETE 즉시 vector delete/history DELETE | add에서 없음; explicit delete API 별도 |

이 매핑은 세 가지 UI 분류를 각 OSS가 갖고 있다는 주장이 아니다. 후보 추출, 기존 기억 비교, 승인, 최종 mutation은 서로 다른 단계다.

## 3. LangMem: 실제 extraction → store operations

### 3.1 MemoryManager는 모델 결정기이며 저장기가 아니다

`MemoryManager.__init__`는 BaseChatModel을 그대로 쓰거나 `init_chat_model(model)`을 만든다. 기본 schema `Memory`에는 `content: str` 하나만 있다. 기본 insert/update=true, delete=false. `_MEMORY_INSTRUCTIONS`는 essential information, uncertain inference caveat, novelty/redundancy 비교, prune/consolidate를 요구하며 **“Quote supporting information when necessary”**라고 한다. 또한 deduction/induction/abduction을 허용한다. 따라서 모델 생성 메모리는 반드시 직접 발화 fact만이라는 계약도 아니다.

소스: [Memory 및 instructions](https://github.com/langchain-ai/langmem/blob/48e3c11f5bb527282c7d5339c6a87a0b35abccfc/src/langmem/knowledge/extraction.py#L81-L221).

`ainvoke`와 `invoke`의 흐름:

1. messages를 `_prepare_messages`로 대화 문자열 및 임의 session UUID wrapper에 넣는다. 기존 memories는 `(id, kind, value)`로 변환한다. 기존 문자열 목록 입력에는 새 UUID를 부여한다.
2. `trustcall.create_extractor`에 schemas, enable insert/update/delete, `existing_schema_policy=False`를 전달한다. **추출과 기존 기억 비교를 같은 extractor call에서 한다.** Mem0 과거의 facts-only 첫 call과는 다르다.
3. `max_steps` 기본 1. responses/response_metadata를 zip하고 patch 대상 `json_doc_id`가 있으면 그 ID를, 새로운 응답에는 UUID를 사용한다. `RemoveDoc`는 자기 `json_doc_id`를 사용한다.
4. response에서 **빠진 기존 기억은 모두 결과 dict에 다시 넣어 보존**한다. omitted existing memory를 delete로 취급하지 않는다.
5. 두 번째 iteration부터 Done tool을 더한다. Done이나 AI message의 tool_calls 없음이면 stop. 추가 step은 직전 결과를 existing으로 다시 보내 refine한다. 중간 RemoveDoc는 다음 existing에서 제외한다.
6. 최종 `_filter_response`는 외부 기존 기억에 대한 RemoveDoc만 남긴다. 이번 invocation 안에서 생성했다가 제거한 internal memory는 store 삭제 대상으로 내보내지 않는다.
7. 반환은 `ExtractedMemory(id, content)` 목록이다. 이 class에는 store.put/delete가 없다. `create_memory_manager` docstring의 “all automatically persisted” 표현을 이 경로의 실제 저장으로 해석하면 안 된다.

소스: [async loop](https://github.com/langchain-ai/langmem/blob/48e3c11f5bb527282c7d5339c6a87a0b35abccfc/src/langmem/knowledge/extraction.py#L223-L326), [sync loop 및 preparation/filter](https://github.com/langchain-ai/langmem/blob/48e3c11f5bb527282c7d5339c6a87a0b35abccfc/src/langmem/knowledge/extraction.py#L327-L520), [factory/docstring](https://github.com/langchain-ai/langmem/blob/48e3c11f5bb527282c7d5339c6a87a0b35abccfc/src/langmem/knowledge/extraction.py#L522-L677).

### 3.2 StoreManager는 semantic retrieval 뒤 exact diff를 적용한다

`MemoryStoreManager.ainvoke`:

1. store 제공값 또는 LangGraph context store를 찾고 namespace template를 적용한다. 미설정 store는 ValueError.
2. query_model이 지정됐으면 검색 tool을 모델에 bind하고 **모델이 낸 tool calls만** 병렬 search한다. 없으면 `get_dialated_windows(messages, query_limit // 4)`에서 얻은 최근 대화 windows를 검색한다. query_limit 기본 5이면 N=1이라 검색 query는 마지막 message window 하나다. 전체 대화는 이후 extraction에 전달된다. query_limit<4이면 N=0이어서 window query가 없다.
3. 검색 결과는 namespace/key로 dedup 후 score 순 전역 `query_limit`개만 비교 대상으로 선택한다. stable ID는 namespace+key의 UUID5. **전체 store에 대해 중복/충돌을 검사하는 것이 아니다.**
4. 검색 결과가 없고 default_factory가 있으면 extractor보다 **먼저** `key='default'`를 저장한다. 이후 extraction failure가 있어도 이 default write는 이미 일어날 수 있다.
5. 검색 기억 `store_based`를 MemoryManager에 existing으로 제공한다. `_apply_manager_output`에서 기존 stable ID는 기존 값을 교체하고 새 ID는 ephemeral로 둔다. RemoveDoc는 store-backed ID이면 removed_ids에 넣고 목록에서 제거한다.
6. optional phases를 순서대로 실행한다. phase마다 기존+ephemeral을 다시 비교하며 `include_messages` 기본 false이다.
7. 최종 diff: 기존 key의 kind/content가 다를 때만 put; 새로운 memory는 put; removed_ids는 delete. async는 `asyncio.gather(aput..., adelete...)`로 직접 실행하고 **final_puts만 반환**한다. 삭제-only 결과도 반환 목록은 빈 배열이다. 반환 `[]`만으로 no-op을 판별하면 안 된다.

소스: [init/store/stable ID/apply/sort](https://github.com/langchain-ai/langmem/blob/48e3c11f5bb527282c7d5339c6a87a0b35abccfc/src/langmem/knowledge/extraction.py#L811-L987), [async full operation](https://github.com/langchain-ai/langmem/blob/48e3c11f5bb527282c7d5339c6a87a0b35abccfc/src/langmem/knowledge/extraction.py#L988-L1116), [window formatting](https://github.com/langchain-ai/langmem/blob/48e3c11f5bb527282c7d5339c6a87a0b35abccfc/src/langmem/utils.py#L88-L112).

여기서 semantic no-op은 모델이 기존 사실과 같다고 판단해 변경을 만들지 않는 부분이고, deterministic no-op은 host가 kind/content equality를 확인해 put을 생략하는 부분이다. 내용이 다른 새 UUID를 모델이 잘못 생성하면 host diff만으로 semantic duplicate를 막지 못한다.

### 3.3 omitted/empty/invalid/error와 기본값 함정

- 정상 responses가 비었고 기존 기억이 있으면 기존 값이 유지된다. 기존 기억도 없으면 일반적으로 빈 출력이다. 다만 default_factory 선저장 및 deletion-only 반환은 별도다.
- 응답 shape를 host가 완전히 검증하는 별도 code는 이 manager에 없다. `responses`, `response_metadata`, `messages[-1]`를 직접 사용한다. malformed shape 또는 extractor exception을 review-needed로 변환하는 catch가 없다. zip 길이 불일치가 발생한다면 긴 쪽이 잘릴 수 있다 `[INFERENCE: Python zip semantics]`.
- schema validation/retry/repair는 Trustcall dependency 내부에 위임된다. 이 repo는 `trustcall>=0.0.39`로만 지정하므로 **이 SHA만으로 어떤 installed Trustcall의 invalid-output 재시도 정책까지 고정할 수 없다**. “invalid 출력은 항상 빈 목록으로 안전 처리”라고 단정할 근거가 없다.
- public `create_memory_store_manager(enable_deletes=False)`와 class constructor `MemoryStoreManager(enable_deletes=True)`의 default가 다르다. public docstring은 delete default true라고 써 있으나 signature는 false다. 추가 phases의 `_build_phase_manager`는 phase enable_deletes 기본 true이므로 top-level false가 모든 phase의 deletion까지 봉쇄하는 전역 승인 정책은 아니다.
- async write는 multi-operation transaction이 이 class에 없고 gather 중 실패 시 이미 다른 write가 성공했을 수 있다. sync 경로는 executor에 submit한 put/delete Future에 `.result()`를 하지 않아 mutation Future exception을 명시적으로 propagate하지 않는다 `[INFERENCE: concurrent Future semantics; code에 result retrieval 없음]`.

소스: [loop result parsing](https://github.com/langchain-ai/langmem/blob/48e3c11f5bb527282c7d5339c6a87a0b35abccfc/src/langmem/knowledge/extraction.py#L262-L324), [phase defaults](https://github.com/langchain-ai/langmem/blob/48e3c11f5bb527282c7d5339c6a87a0b35abccfc/src/langmem/knowledge/extraction.py#L955-L968), [sync mutations](https://github.com/langchain-ai/langmem/blob/48e3c11f5bb527282c7d5339c6a87a0b35abccfc/src/langmem/knowledge/extraction.py#L1247-L1259), [public signature/doc](https://github.com/langchain-ai/langmem/blob/48e3c11f5bb527282c7d5339c6a87a0b35abccfc/src/langmem/knowledge/extraction.py#L1644-L1689), [dependency](https://github.com/langchain-ai/langmem/blob/48e3c11f5bb527282c7d5339c6a87a0b35abccfc/pyproject.toml#L7-L17).

### 3.4 원문 근거·승인·실행 시점

`get_conversation`은 merge_message_runs 후 pretty_repr를 이어 붙인다. 원래 message role/content가 모델 입력의 문맥으로 쓰일 수 있으나 default memory store payload는 `{kind, content}`뿐이다. source ID, speaker provenance, 원문 span, transcript hash, quote-entailment 검사, signed approval은 default 흐름에 없다. 커스텀 schema로 필드를 추가하는 가능성과 실제 기본 보존/검증은 구분해야 한다. session wrapper UUID는 invocation 내부에서 새로 만드는 값이지 원문 source ID가 아니다.

public docstring은 “maintains a versioned history of all changes”라고 하지만 이 extraction.py 구현은 put/delete하며 자체 revision log를 기록하지 않는다. 특정 BaseStore가 history를 제공하는지는 별도이며 본 조사에서 확인하지 않았다.

이 클래스는 호출당 messages batch를 처리한다. max_steps는 **한 invocation 안의 반복 consolidation**이지 session-end event 감지가 아니다. source 범위에는 인간 승인 인터럽트나 세션 종료 hook이 없으며 caller가 호출 시점을 정한다. BaseChatModel 지원 또는 Anthropic/OpenAI dependency 존재는 회사의 Claude/Codex caller 통합이 승인됐다는 뜻이 아니다.

소스: [formatter](https://github.com/langchain-ai/langmem/blob/48e3c11f5bb527282c7d5339c6a87a0b35abccfc/src/langmem/utils.py#L88-L112), [default schema](https://github.com/langchain-ai/langmem/blob/48e3c11f5bb527282c7d5339c6a87a0b35abccfc/src/langmem/knowledge/extraction.py#L81-L88), [write payload](https://github.com/langchain-ai/langmem/blob/48e3c11f5bb527282c7d5339c6a87a0b35abccfc/src/langmem/knowledge/extraction.py#L1081-L1116), [history claim](https://github.com/langchain-ai/langmem/blob/48e3c11f5bb527282c7d5339c6a87a0b35abccfc/src/langmem/knowledge/extraction.py#L1660-L1664).

## 4. mnema: 후보 preview/apply + unresolved relation + preview/commit

### 4.1 후보 추출은 usefulness prompt, host는 citation 존재를 검사

`parseTranscript`는 Claude Code JSONL의 `type=user|assistant`, `uuid`, text content만 뽑는다. blank/non-dialogue record는 건너뛰고 parse error나 missing uuid는 unsupported count에 더한다. 관측하는 speaker는 record.type이고, 발화 timestamp는 읽지 않는다. message.role 일치 검증도 하지 않는다.

`buildPreview`:

1. 각 메시지 text를 redact한 뒤 `[id] role: text`로 LLM에 준다. preferences/decisions/constraints/non-obvious durable fact만 추출하고, one-off debugging/code/git/pleasantries/assistant explanations를 제외하라는 prompt다. usefulness exclusion은 모델 판단이지 host의 의미 분류기 아니다.
2. 응답은 JSON.parse + Zod `{candidates:[{body:string,message_ids:string[]}]}`. omitted candidates, invalid JSON/type는 throw한다. `candidates:[]`는 정상 빈 preview다.
3. 후보 200개까지만 처리한다. message_ids를 실제 transcript ID 집합과 대조해 모르는 ID는 제거하며, 남는 ID가 0이면 후보 drop. 일부만 실존하면 그 subset으로 후보가 살아남는다.
4. 실제 redacted message text를 host가 이어 붙여 excerpt를 만들고 8KiB 문자수 상한으로 자른다. body token>128은 drop. raw body 빈 문자열/zero-token을 이 루프에서 명시적으로 drop하지는 않는다; 이후 `loadRun`의 candidate schema min(1) 검사에서 거절될 수 있다.
5. candidate_key는 `sha256(message_ids.join(',') + '|' + sha256(sorted tokens))`. 이것은 source IDs+토큰 bag의 결정적 키다. semantic duplicate 비교가 아니며, 같은 fact를 다른 IDs로 말하면 새 candidate가 될 수 있다. 순서가 다른 같은 토큰들의 사실은 같은 normalized fact hash가 될 수 있다.
6. run.json에는 source ref/raw transcript SHA-256/redaction_version/model/prompt_version/candidates와 `relations:[]`를 둔다. `run_key=sha256(JSON.stringify(rest))`. 주석의 “M6 adds batched contradiction call”과 달리 **이 함수는 extraction call 하나만 하며 relation 판단은 하지 않는다**.

소스: [transcript parser](https://github.com/Ray0907/mnema/blob/eed19586156ae9664451cb94859f8f3f16b3ac4a/src/transcript.ts#L1-L64), [distill prompt/preview](https://github.com/Ray0907/mnema/blob/eed19586156ae9664451cb94859f8f3f16b3ac4a/src/distill.ts#L17-L113).

### 4.2 apply는 기존 semantic memory 비교가 아니라 선택·idempotency·create

CLI `distill <jsonl> --output <run.json>`는 preview를 만들고 파일만 저장한다. `distill --apply <run.json> [--accept keys]`는 loadRun 후 applyRun을 호출한다. 자동 session-end ingestion이나 resident extraction daemon은 이 경로에 없다.

`loadRun`은 파일 10MB 상한, Zod schema, run_key 재계산 일치를 검사한다. **원본 transcript를 다시 읽어 ref_sha256와 비교하거나 excerpt가 transcript에 있는지 재검증하지 않는다.** run hash는 unkeyed이며 누구든 altered run의 hash를 재계산할 수 있으므로 authenticated approval/signature가 아니다.

`applyRun`은 LLM을 호출하지 않는다. accept_keys가 지정됐으면 해당 key만 저장하고 그 밖은 제외한다. **accept_keys를 생략하면 모든 후보를 accept**한다. 같은 candidate_key가 store에 있으면 skipped. 그 외에는 ULID, `kind=derived`, revision=1, body capture/current SHA-256, `contradiction_status=pending`, captured_at=현재시간, source transcript provenance를 만들어 addMemory한다. 기존 기억과 semantic 비교해서 patch하는 단계는 없다. 별도 rejected 후보 사유 ledger도 없다. 후보마다 순차 add하며 전체 run transaction은 없다.

소스: [loadRun/applyRun](https://github.com/Ray0907/mnema/blob/eed19586156ae9664451cb94859f8f3f16b3ac4a/src/distill.ts#L115-L177), [CLI distill/apply/resolve/check](https://github.com/Ray0907/mnema/blob/eed19586156ae9664451cb94859f8f3f16b3ac4a/src/cli.ts#L115-L168).

### 4.3 原文·speaker·hash는 무엇까지 보존하는가

Derived canonical source에는 `ref`, `ref_sha256`, 실제 `message_ids`, redacted `excerpt`, `excerpt_sha256`, model/prompt/redaction_version이 필수다. body capture/current hash도 따로 있다. 이것은 LangMem default보다 훨씬 구체적인 provenance다. 하지만:

- excerpt는 redacted text의 concatenation이고 저장 excerpt 자체에는 역할 라벨/각 message boundary ID mapping이 없다. source schema에는 speaker 필드나 byte/character span이 없다.
- 전체 원문을 canonical memory에 복사하지 않는다. raw 원문 파일의 위치·해시와 redacted 일부를 보존한다. source 파일이 없어도 excerpt는 남지만 raw 전체를 이 메모리만으로 복원하지 못한다.
- ID 존재 검증은 **citation identity 검증**이지 모델 memory body의 semantic support 검증이 아니다. “사용자 발화만 citation으로 허용”하는 runtime gate도 없고 실제 assistant ID도 알려진 ID다.
- source hash/excerpt hash는 schema에서 형식을 검증하고 생성 시 host가 계산한다. apply 때 원본 파일을 재검증하지 않는다. run_key는 run 전체 tamper-evidence 정도이지 서명된 증거 승인 아니다.
- `applyManualRevision`은 현재 body hash 불일치 시 revision을 올리고 `kind=manual_revision`, `source={type:revised,original:...,supports_current_body:false}`로 전환한다. 기존 원문이 수정된 body를 여전히 증명한다고 거짓 표시하지 않는 **명시적인 support-invalidated 상태**는 좋은 힌트다.
- observed_at은 schema에 optional로 존재하지만 이 transcript parser/buildPreview/applyRun 경로는 설정하지 않는다. captured_at은 저장 시 host 현재시각이다.

소스: [source/body/time schema](https://github.com/Ray0907/mnema/blob/eed19586156ae9664451cb94859f8f3f16b3ac4a/src/schema.ts#L11-L69), [host-generated citation/excerpt](https://github.com/Ray0907/mnema/blob/eed19586156ae9664451cb94859f8f3f16b3ac4a/src/distill.ts#L74-L112), [persisted source](https://github.com/Ray0907/mnema/blob/eed19586156ae9664451cb94859f8f3f16b3ac4a/src/distill.ts#L143-L175), [manual revision](https://github.com/Ray0907/mnema/blob/eed19586156ae9664451cb94859f8f3f16b3ac4a/src/canonical.ts#L55-L73).

### 4.4 addMemory와 idempotent no-op

`addMemory`는 schema를 검증하는 serialize를 거쳐 journal → lock → manifest pending → canonical markdown → DB/FTS → journal cleanup 순으로 저장한다. DB transaction 실패 시 canonical/journal이 남는 `durable`을 반환하며 committed와 구분한다. 동일 op_key/hash는 기존 ID를 반환하는 replay이고 동일 key/다른 payload hash는 throw한다. 이는 semantic equality 판정이 아니다.

MCP add는 direct kind이며 caller body/note/tags/stable/op_key를 받아 바로 이 함수를 실행한다. transcript evidence 없이 `source={type:direct,note}`이고 LLM usefulness filter도 없다. MCP description의 “~128 tokens”와 실제 MCP input validator는 다르다: body max2048 characters를 검사하며 128-token 검사 함수는 이 direct add handler에 없다.

소스: [store add protocol/op key](https://github.com/Ray0907/mnema/blob/eed19586156ae9664451cb94859f8f3f16b3ac4a/src/store.ts#L114-L179), [MCP direct add](https://github.com/Ray0907/mnema/blob/eed19586156ae9664451cb94859f8f3f16b3ac4a/src/mcp-server.ts#L67-L107).

### 4.5 batched conflict detector: pending/error → checked 또는 unresolved relation

`checkConflicts`는 embedder가 없으면 throw한다. DB에서 memory contradiction_status `pending|error`를 가져온다. embeddings를 준비하고 각 후보의 vecKnn 6개 중 self 및 distance>=0.3을 제외하며, 이미 존재하는 relation 파일 및 중복 pair를 제외한다. 0.3은 파일에 pilot/recalibrate라고 명시된 값이며 측정된 보편 threshold가 아니다.

모든 pairs를 **한 judge call**에 준다. judge prompt는 current-state contradiction과 situational variation을 구별한다. true verdict만 `makeRelation`으로 `status=unresolved,resolution=null,resolved_at=null` relation YAML을 생성한다. false는 relation을 생성하지 않는다. memory body를 rewrite/delete하지 않는다. judge invocation이 throw하면 memory status는 error, 다음 명시적 check에서 다시 대상이 된다. 정상 invocation이면 pending rows를 checked로 rewrite한다.

**출력 completeness/validation의 실제 경계**:

- `AnthropicLlm.judge`는 JSON.parse 결과를 TypeScript cast하고 `parsed.verdicts`만 반환한다. Zod로 판정 스키마/expected pairs/전체 coverage를 검사하지 않는다.
- 정상 `verdicts:[]`나 일부 pair만 담은 출력도 모든 pending memory를 checked로 만든다. omitted pair를 review-needed로 보존하지 않는다.
- omitted `verdicts`가 undefined라면 judge 자체는 반환할 수 있으나 store의 이후 for-of가 throw할 수 있다. 이 iteration은 judge try/catch 밖이다 `[INFERENCE: JavaScript iteration semantics]`.
- 반환 IDs가 요청 pair에 속하는지 store가 대조하지 않는다. DB에 두 ID가 존재하는지 현재 hash 조회로만 확인한다.
- **judge 중 body 변경 race**: 입력 pairs는 이전 body 문자열인데, await 이후 makeRelation에 넣는 input_hashes는 그때의 DB hash다. 이전 snapshot hash와 비교하는 코드가 없다. `rows_pending.content_hash`도 이 guard에 쓰지 않는다. 두 ID가 여전히 존재하면 바뀐 hash를 예전 verdict에 붙일 수 있다. “member changed/vanished” 주석보다 실제 guard가 좁다. 이는 정적 코드에서 확인되는 mismatch이지 동시성 실행으로 재현한 결과는 아니다.

소스: [batched detector](https://github.com/Ray0907/mnema/blob/eed19586156ae9664451cb94859f8f3f16b3ac4a/src/store.ts#L293-L355), [pending/error rows](https://github.com/Ray0907/mnema/blob/eed19586156ae9664451cb94859f8f3f16b3ac4a/src/db.ts#L314-L326), [judge prompt/relation](https://github.com/Ray0907/mnema/blob/eed19586156ae9664451cb94859f8f3f16b3ac4a/src/conflicts.ts#L4-L52), [unvalidated verdict adapter](https://github.com/Ray0907/mnema/blob/eed19586156ae9664451cb94859f8f3f16b3ac4a/src/llm.ts#L44-L72), [pilot constants](https://github.com/Ray0907/mnema/blob/eed19586156ae9664451cb94859f8f3f16b3ac4a/src/store.ts#L533-L536).

### 4.6 unresolved → preview → commit 및 relation lifecycle

MCP write tools는 `MNEMA_ENABLE_WRITE === '1'`일 때만 등록된다. readOnlyHint/destructiveHint는 보안 enforcement가 아니라 hint라고 소스가 명시한다.

`resolve_preview(a_id,b_id)`는 unresolved relation과 양쪽 body/reason/input_hashes를 읽고 `sha256(relation_id+'|'+hashes.join(','))[0:16]` 토큰을 출력한다. `resolve_commit`은 같은 preview를 다시 읽고 같은 식으로 token을 재계산하여 equality를 검사한 뒤 `store.resolve`한다. token mismatch는 throw한다.

`Store.resolve`는:

- relation 존재와 unresolved 여부 검사;
- 현재 DB content hashes와 relation.input_hashes 일치 검사. 불일치 시 stale로 파일을 바꾸고 throw;
- keep:<id>는 실제 member이어야 하고 loser→winner edge 추가가 supersession cycle을 만들면 거절;
- keep_both 외의 resolution은 거절;
- status=resolved/resolution/resolved_at을 relation 파일에 기록하고 reconcile.

reconcile은 member 없음→orphaned, hash 변경→stale, stale에서 원래 hash 복원→unresolved로 전환한다. stale/orphaned의 resolution은 지운다. resolved keep loser의 superseded flag는 relation graph로부터 **DB에 유도**하며 원래 canonical memory body는 유지한다. 검색 score에 0.2 penalty를 줄 뿐 delete가 아니다. keep_both는 loser를 만들지 않는다.

**인간 승인과 다른 것**: token은 비밀키 없는 deterministic content token이고 actor identity, 승인 서명, expiry, one-use, resolution choice binding, persisted preview receipt가 없다. 모델도 preview를 호출해 token을 읽고 commit할 수 있으며 값 자체를 계산할 수도 있다. host는 실제 preview 호출이 있었다는 event를 저장하지 않는다. CLI `resolve`는 이 MCP token 단계를 거치지 않고 Store.resolve를 호출한다. 따라서 “human approval 필수”보다 **“MCP의 content-bound 2단계 확인 UX 및 stale guard”**가 정확하다.

검색은 hit 중 한쪽이라도 걸리는 unresolved relations를 반환한다. MCP search의 문구는 “both sides shown”이지만 실제 handler는 conflict pair IDs/reason과 top-k hits만 출력하며 상대방 body를 추가 fetch하지 않는다. 양쪽 body가 항상 출력되는 보장은 **resolve_preview**에 있다.

소스: [MCP write flag 및 preview/commit](https://github.com/Ray0907/mnema/blob/eed19586156ae9664451cb94859f8f3f16b3ac4a/src/mcp-server.ts#L29-L155), [Store.resolve/preview](https://github.com/Ray0907/mnema/blob/eed19586156ae9664451cb94859f8f3f16b3ac4a/src/store.ts#L359-L423), [relation reconcile](https://github.com/Ray0907/mnema/blob/eed19586156ae9664451cb94859f8f3f16b3ac4a/src/store.ts#L250-L288), [cycle check](https://github.com/Ray0907/mnema/blob/eed19586156ae9664451cb94859f8f3f16b3ac4a/src/conflicts.ts#L54-L79), [unresolved query](https://github.com/Ray0907/mnema/blob/eed19586156ae9664451cb94859f8f3f16b3ac4a/src/db.ts#L297-L306), [penalty](https://github.com/Ray0907/mnema/blob/eed19586156ae9664451cb94859f8f3f16b3ac4a/src/store.ts#L548-L564), [CLI bypass](https://github.com/Ray0907/mnema/blob/eed19586156ae9664451cb94859f8f3f16b3ac4a/src/cli.ts#L147-L166).

### 4.7 설치·provider·회사 경계

`llm.ts`는 fetch로 Anthropic `/v1/messages`를 호출하고 ANTHROPIC_API_KEY 미설정, HTTP non-OK, text block 없음은 throw한다. 호출은 explicit distill preview/check-conflicts 단계다. 기본 model string은 `claude-sonnet-5`이며 이를 실제 유효 모델이라고 시험하지 않았다. MCP/CLI는 기본 TransformersEmbedder를 생성하고 MNEMA_NO_EMBED가 truthy일 때 embedding 없이 열지만, checkConflicts는 embedder 없음을 거절한다.

즉 회사에서 로컬 embedding 설치가 불가한 상황에 이 conflict detector를 그대로 쓸 수 있다는 근거는 아니다. Anthropic SDK/API provider가 존재한다는 사실 역시 승인된 Claude/Codex caller 재사용이나 허가된 team-native route를 구현했다는 뜻이 아니다.

소스: [Anthropic adapter](https://github.com/Ray0907/mnema/blob/eed19586156ae9664451cb94859f8f3f16b3ac4a/src/llm.ts#L1-L72), [MCP embedder](https://github.com/Ray0907/mnema/blob/eed19586156ae9664451cb94859f8f3f16b3ac4a/src/mcp-server.ts#L15-L26), [embedding precondition](https://github.com/Ray0907/mnema/blob/eed19586156ae9664451cb94859f8f3f16b3ac4a/src/store.ts#L293-L303).

## 5. Mem0 current: 실제 add는 ADD-only, 비교는 중복 억제 용도

### 5.1 source와 old prompt를 분리해야 한다

current `Memory.add` docstring은 infer=true가 add/update/delete를 결정한다고 설명하지만 실제 `_add_to_vector_store`는 V3 phased batch pipeline이다. main.py import는 `ADDITIVE_EXTRACTION_PROMPT`와 `generate_additive_extraction_prompt`이며, 과거 `DEFAULT_UPDATE_MEMORY_PROMPT`가 current prompts.py에 남아 있어도 이 함수에서 호출하지 않는다. README도 ADD-only를 설명한다.

소스: [current imports](https://github.com/mem0ai/mem0/blob/b7ad69afda6b6ed030347c66d48a13e4de9dec08/mem0/memory/main.py#L19-L26), [stale docstring/current add](https://github.com/mem0ai/mem0/blob/b7ad69afda6b6ed030347c66d48a13e4de9dec08/mem0/memory/main.py#L740-L858), [actual additive pipeline](https://github.com/mem0ai/mem0/blob/b7ad69afda6b6ed030347c66d48a13e4de9dec08/mem0/memory/main.py#L897-L1068), [retained old prompt](https://github.com/mem0ai/mem0/blob/b7ad69afda6b6ed030347c66d48a13e4de9dec08/mem0/configs/prompts.py#L176-L193), [README](https://github.com/mem0ai/mem0/blob/b7ad69afda6b6ed030347c66d48a13e4de9dec08/README.md).

### 5.2 infer=true actual stages

1. `add`는 entity scope metadata/filters를 준비한다. str→user message, dict→list로 변환하며 잘못된 outer messages type/memory_type은 validation error. timestamp argument는 OSS unsupported로 ValueError를 낸다.
2. session_scope별 최근 메시지 10개를 SQLite에서 가져온다. 현재 messages를 role-prefixed text로 serialize한다.
3. 전체 parsed conversation을 embedding하고 tenant/session filters로 기존 memory top_k=10을 검색한다. 기존 UUID를 integer-string IDs로 매핑해 text와 모델에 준다. mapping dict는 이 ADD pipeline에서 update/delete 적용에 사용되지 않는다.
4. **한 LLM call**에 existing memories + new messages + last messages + custom instructions를 제공한다. prompt는 user/assistant 양쪽에서 추출, vague acknowledgement 제외, 기존과 semantic equivalent이며 meaningful new context가 없으면 skip, 변화한 preference/new event는 별도 ADD하도록 한다. existing은 dedup/link reference이지 수정 대상이 아니다.
5. LLM response의 `memory` 목록을 parse한다. text를 batch embedding하고 실패 시 individual embedding으로 내려간다. 개별 embedding 실패 memory는 skip된다.
6. fetched existing top10 memory hashes + current batch seen hashes와 `MD5(extracted text)`를 비교해 exact text duplicate를 skip한다. **전 store hash uniqueness 또는 semantic equality enforcement가 아니다.**
7. record마다 UUID, data/text_lemmatized/hash, host created_at/updated_at 및 caller metadata를 만든다. `attributed_to`는 모델에 있으면 그대로 복사하며 allowed-values 또는 speaker-source binding을 검사하지 않는다.
8. vector insert batch 실패 시 individual insert를 시도한다. 실제 persisted records만 history/entity linking/result ADD에 넣는다. 모두 insert 실패면 messages를 저장한 뒤 VectorStoreError. 일부 성공이면 성공분 반환이다.
9. history batch 실패 시 개별 history 쓰기로 내려가고 그래도 실패하면 log만 남긴다. entity linking 실패도 log/warning으로 넘어간다. 따라서 memory 저장과 history/evidence 저장은 하나의 all-or-nothing transaction이 아니다.
10. 마지막으로 session messages 저장 후 results ADD만 반환한다. ADD-only여도 entity-store의 linked_memory_ids 등 **검색 보조 entity index는 update**한다. 이는 기존 memory text를 model patch하는 것과 다르다.

소스: [add normalization/temporal limitation](https://github.com/mem0ai/mem0/blob/b7ad69afda6b6ed030347c66d48a13e4de9dec08/mem0/memory/main.py#L799-L850), [retrieval/extraction](https://github.com/mem0ai/mem0/blob/b7ad69afda6b6ed030347c66d48a13e4de9dec08/mem0/memory/main.py#L897-L973), [embed/dedup/metadata/insert](https://github.com/mem0ai/mem0/blob/b7ad69afda6b6ed030347c66d48a13e4de9dec08/mem0/memory/main.py#L975-L1077), [entity index/save/return](https://github.com/mem0ai/mem0/blob/b7ad69afda6b6ed030347c66d48a13e4de9dec08/mem0/memory/main.py#L1079-L1190), [prompt semantic skip/add rule](https://github.com/mem0ai/mem0/blob/b7ad69afda6b6ed030347c66d48a13e4de9dec08/mem0/configs/prompts.py#L464-L515).

### 5.3 empty/omitted/invalid를 같게 처리하는 부분과 구분하는 부분

- LLM provider exception은 `LLMError`로 **다시 throw**한다. comment는 provider failure를 빈 facts와 구별하도록 바뀌었다고 명시한다. 이 source는 특정 company/personal fallback을 실행하지 않으며 caller fallback 가능성 언급일 뿐이다.
- empty/whitespace response, `memory` omitted(`.get('memory',[])`), 정상 empty array, JSON parse 실패는 결과적으로 empty extraction에 합쳐진다. **parse failure가 error/review state로 보존되지 않는다.** 그 경우에도 incoming messages는 save되고 results=[]다.
- JSON parse 후 list item schema validation이 없다. `memory`가 truthy한 잘못된 container이거나 non-dict item이면 후속 `.get` processing에서 exception이 발생할 수 있다 `[INFERENCE: Python operation semantics]`.
- text missing/falsy, embedding 실패, exact hash duplicate도 결과에서 빠진다. 이때 skip reason은 structured results로 나오지 않는다. omitted/excluded/duplicate/retrieval-miss를 구별하는 모델 결정 ledger는 없다.
- LLM id/event 필드는 실제 create op 선택에 사용되지 않는다. event='DELETE'라고 출력해도 이 parser는 event switch를 하지 않고 text가 유효하면 ADD 대상으로 취급한다.

소스: [provider vs parse error](https://github.com/mem0ai/mem0/blob/b7ad69afda6b6ed030347c66d48a13e4de9dec08/mem0/memory/main.py#L938-L973), [text/dedup processing](https://github.com/mem0ai/mem0/blob/b7ad69afda6b6ed030347c66d48a13e4de9dec08/mem0/memory/main.py#L975-L1030).

### 5.4 evidence prompt와 enforced provenance는 다르다

current prompt는 “evidence-bound”, “No Fabrication”, “Every detail must trace to inputs”, “Correct Attribution”이라고 명시한다. output fields는 id/text/attributed_to/optional linked_memory_ids이다. host는 id 존재, linked IDs의 relation validity, text span support를 검증하지 않는다. 특히 **모델 output의 memory-level `linked_memory_ids`는 이 add record payload에 복사하지 않는다**. 실제 entity-linking은 별도 entity extraction으로 만든 index다. prompt linking과 구현 side effect를 혼동하지 말아야 한다.

source 메시지는 SQLite에 role/content/name과 host UUID/created_at로 저장하지만 session_scope당 최근 10개만 남기고 그 이전을 DELETE한다. memory record에는 어느 메시지 UUID/span이 근거인지 연결하지 않는다. 이 최근-context cache는 **영구 원문 증거 archive가 아니다**. text MD5는 추출된 memory text의 exact dedup용이지 source transcript hash가 아니다. 모델 attributed_to와 실제 host message role은 다른 신뢰 층이다.

infer=false는 LLM usefulness/comparison을 우회하고 system role을 제외한 입력 messages를 직접 embed/create한다. role/name을 각각 role/actor_id metadata로 복사하는 실제 host-side attribution은 있지만, 이것도 citation span/verified entailment/signed approval을 제공하지 않는다.

current explicit `_update_memory`는 이전 payload를 deepcopy하고 identity keys를 보호하며 text/hash/time을 바꾼다. `_delete_memory`는 vector record를 삭제하고 old text history를 남긴다. 이 함수들이 존재한다는 사실은 `add`가 모델 판단으로 호출한다는 뜻이 아니다.

소스: [prompt integrity/linking](https://github.com/mem0ai/mem0/blob/b7ad69afda6b6ed030347c66d48a13e4de9dec08/mem0/configs/prompts.py#L659-L687), [prompt fields](https://github.com/mem0ai/mem0/blob/b7ad69afda6b6ed030347c66d48a13e4de9dec08/mem0/configs/prompts.py#L893-L916), [actual payload](https://github.com/mem0ai/mem0/blob/b7ad69afda6b6ed030347c66d48a13e4de9dec08/mem0/memory/main.py#L1005-L1030), [message cache and eviction](https://github.com/mem0ai/mem0/blob/b7ad69afda6b6ed030347c66d48a13e4de9dec08/mem0/memory/storage.py#L256-L325), [raw infer=false](https://github.com/mem0ai/mem0/blob/b7ad69afda6b6ed030347c66d48a13e4de9dec08/mem0/memory/main.py#L860-L895), [explicit update/delete](https://github.com/mem0ai/mem0/blob/b7ad69afda6b6ed030347c66d48a13e4de9dec08/mem0/memory/main.py#L2030-L2118).

current add는 호출당 messages batch + 최근 cache 기반 incremental ingestion이다. session-end detector/인간 승인 queue는 이 경로에 없다. conflict를 unresolved로 보류하지 않고 기존도 새 것도 유지하는 additive 전략이다. temporal current-state adjudication이나 signed conflict resolution까지 구현됐다고 해석하면 안 된다.

## 6. Mem0 과거 v1.0.0: ADD/UPDATE/DELETE/NONE 실제 실행

### 6.1 두 단계 모델 판단

`_add_to_vector_store(infer=True)`는:

1. messages를 role-prefixed text로 바꾼다. custom extraction prompt가 없으면 agent scope/messages 조건에 따라 user 또는 agent extraction prompt를 선택한다. 기본 user prompt의 assistant/system 제외는 **prompt 요구**이며 serializer는 system/user/assistant를 모두 담는다.
2. 첫 LLM call에서 `facts`를 추출한다. 빈 response, key omission/parse failure는 catch하여 facts=[]가 된다. 첫 provider generate_response 자체는 parsing try 밖이라 provider failure는 propagate한다.
3. 각 fact를 embed하고 existing limit=5를 user/agent/run filters로 검색한다. id로 union/dedup하고 UUID→integer string mapping을 만든다. **candidate별 기존 retrieval을 먼저 한 뒤 모든 facts와 union old memories를 둘째 LLM에 함께 준다.**
4. `get_update_memory_messages`로 ADD/UPDATE/DELETE/NONE를 요청한다. 둘째 provider failure는 log 후 empty response가 되고 invalid/empty JSON도 `{}`로 처리한다. facts=[]이면 이 둘째 call은 생략한다.
5. `memory` 목록을 순회해 event를 즉시 적용한다. 별도 approve/preview/review queue는 없다.

소스: [full two-call flow](https://github.com/mem0ai/mem0/blob/394203d1b5f56385d28690ea27c0d746007ff940/mem0/memory/main.py#L381-L518), [role serializer/prompt selection](https://github.com/mem0ai/mem0/blob/394203d1b5f56385d28690ea27c0d746007ff940/mem0/memory/utils.py#L10-L38), [4-op prompt](https://github.com/mem0ai/mem0/blob/394203d1b5f56385d28690ea27c0d746007ff940/mem0/configs/prompts.py#L179-L315).

### 6.2 operation별 side effects와 omission

| event | 실제 실행 | 중요한 경계 |
|---|---|---|
| ADD | `_create_memory`에서 새 UUID/vector insert/history ADD | 모델이 준 new ID를 store ID로 쓰지 않는다. semantic duplicate 판정은 둘째 LLM에 의존 |
| UPDATE | mapped 기존 UUID로 text/vector overwrite, history old→new | “patch”는 memory text replacement이며 JSON field patch가 아니다. source span support 검증 없음 |
| DELETE | mapped UUID vector delete/history old→None | conflict 보류나 인간 승인 없이 삭제 |
| NONE | content 유지; agent_id/run_id 주어지면 metadata 및 updated_at을 vector payload에 write | **이름은 NONE지만 영구 side effect가 있을 수 있다.** returned results에는 NONE가 포함되지 않음 |
| omitted | loop에 없는 기억은 그대로 남음 | omitted existing를 DELETE로 해석하지 않음 |
| invalid | empty text는 모든 event에서 skip; unknown event는 적용 branch 없음; invalid target ID는 KeyError 등 item catch/log | invalid result가 review state로 남지 않고 일부 action만 성공할 수 있음 |

모델을 JSON response_format으로 요청할 뿐 `memory` entries를 operation discriminated schema로 검증하지 않는다. 모든 action은 먼저 nonempty text를 요구하므로 DELETE도 text가 없으면 수행하지 않는다. action별 exception을 catch/log해 계속 진행한다. 즉 배치 전체 atomicity가 없고 returned list는 전체 decision coverage/오류 내역을 제공하지 않는다.

소스: [event switch/NONE/error](https://github.com/mem0ai/mem0/blob/394203d1b5f56385d28690ea27c0d746007ff940/mem0/memory/main.py#L518-L584), [create/update/delete/history](https://github.com/mem0ai/mem0/blob/394203d1b5f56385d28690ea27c0d746007ff940/mem0/memory/main.py#L1062-L1088), [update/delete](https://github.com/mem0ai/mem0/blob/394203d1b5f56385d28690ea27c0d746007ff940/mem0/memory/main.py#L1129-L1199), [async search/actions](https://github.com/mem0ai/mem0/blob/394203d1b5f56385d28690ea27c0d746007ff940/mem0/memory/main.py#L1473-L1620).

과거 `_update_memory`는 새 metadata dict부터 만들고 기존 session IDs/actor_id/role만 명시적으로 보존한다. 임의 source evidence metadata 전체를 deepcopy하는 current 방식과 다르므로 caller가 metadata에 원문 링크를 넣었다고 해서 모든 과거 update에서 자동 보존된다고 단정할 수 없다. history의 old/new text는 추출물 revision audit이지 원문 transcript citation이 아니다. returned `previous_memory`는 모델 `old_memory` 값이지만 실제 history old value는 vector payload에서 가져온다.

소스: [metadata preservation/history](https://github.com/mem0ai/mem0/blob/394203d1b5f56385d28690ea27c0d746007ff940/mem0/memory/main.py#L1129-L1180), [model-reported previous_memory](https://github.com/mem0ai/mem0/blob/394203d1b5f56385d28690ea27c0d746007ff940/mem0/memory/main.py#L536-L550).

## 7. Mem0 MCP: OSS 호출과 플랫폼 wrapper를 분리

### 7.1 과거 OpenMemory MCP → OSS Memory

같은 historical SHA의 `openmemory/api/app/mcp_server.py:add_memories(text)`는 user_id/client_name context와 app active 여부를 확인하고 `get_memory_client_safe()`를 가져온다. getter는 `mem0.Memory`를 import하여 config로 `Memory.from_config(config_dict=config)`를 초기화한다. MCP add는 `memory_client.add(text,user_id=uid,metadata={source_app:'openmemory',mcp_client:client_name})`를 호출한다. 여기에는 inference를 끄는 인자가 없으며 approval/confirmation token도 없다.

후속 OpenMemory SQLAlchemy mirror는 result event **ADD와 DELETE만** 처리한다. ADD는 active/content 생성 또는 갱신, DELETE는 deleted/deleted_at/status history를 기록한다. **UPDATE branch가 없다.** 따라서 이 소스 조합에서 core가 UPDATE를 내면 vector memory는 바뀌어도 OpenMemory mirror content 갱신은 이 handler에 없다. 이는 source-level mismatch이며 실행하여 drift를 확인한 것은 아니다. `changed_by=user.id`는 context상 owner 기록이지 인간이 모델 decision을 승인했다는 증거가 아니다.

source_app/mcp_client는 host provenance metadata지만 raw source transcript id/span/hash는 아니다. text tool input 자체가 caller가 압축한 fact일 수 있다.

중요한 재현성 경계: historical OpenMemory requirements는 `mem0ai>=0.1.92`로 설치 버전을 고정하지 않는다. 같은 repo SHA의 OSS class를 위에서 비교했지만 **배포된 OpenMemory가 꼭 그 SHA의 core를 설치했다는 주장까지 하지 않는다**.

소스: [historical MCP handler](https://github.com/mem0ai/mem0/blob/394203d1b5f56385d28690ea27c0d746007ff940/openmemory/api/app/mcp_server.py#L42-L140), [OSS factory](https://github.com/mem0ai/mem0/blob/394203d1b5f56385d28690ea27c0d746007ff940/openmemory/api/app/utils/memory.py#L282-L382), [unpinned dependency](https://github.com/mem0ai/mem0/blob/394203d1b5f56385d28690ea27c0d746007ff940/openmemory/api/requirements.txt#L1-L19).

### 7.2 별도 mem0-mcp archived wrapper → 플랫폼 API

조사 시 `mem0ai/mem0-mcp` pinned README는 archive를 선언하고 현재 hosted MCP 문서로 안내한다. source의 `_mem0_client`는 **MemoryClient(api_key=...)**이고 OSS Memory가 아니다. add_memory는 text를 user-role message로 만들거나 ToolMessage(role/content) 목록을 넣어 `client.add`를 호출한다. ToolMessage는 source ID/span/hash 필드를 정의하지 않는다. metadata는 opaque JSON이다.

update_memory/delete_memory docstring은 “user confirms exact memory_id”라고 쓰지만 signature에는 memory_id/text/context만 있고 confirmation token, signed approval, preview receipt 검사 없이 바로 `client.update`/`client.delete`한다. bulk delete도 confirmed scope라는 docstring과 달리 별도 confirmation gate가 없다. `_mem0_call`은 MemoryError를 JSON error/status/payload로 반환한다.

현재 pinned SDK의 `MemoryClient`는 기본 `https://api.mem0.ai`에 `POST /v3/memories/add/`를 보낸다. 그러나 wrapper dependency는 `mem0ai>=1.0.1`라 실제 설치 SDK SHA는 고정되지 않으며, **플랫폼 내부 decision control flow는 OSS current Memory.add로 증명할 수 없다**. hosted service의 동작/승인 enforcement도 본 조사로 확인하지 않았다.

소스: [wrapper client/error/settings](https://github.com/mem0ai/mem0-mcp/blob/624024deacbbe1948572a968abdb9d9e93ded548/src/mem0_mcp_server/server.py#L93-L130), [add](https://github.com/mem0ai/mem0-mcp/blob/624024deacbbe1948572a968abdb9d9e93ded548/src/mem0_mcp_server/server.py#L159-L233), [update/delete/confirmation docstring](https://github.com/mem0ai/mem0-mcp/blob/624024deacbbe1948572a968abdb9d9e93ded548/src/mem0_mcp_server/server.py#L329-L400), [message schema](https://github.com/mem0ai/mem0-mcp/blob/624024deacbbe1948572a968abdb9d9e93ded548/src/mem0_mcp_server/schemas.py#L10-L43), [wrapper dependency](https://github.com/mem0ai/mem0-mcp/blob/624024deacbbe1948572a968abdb9d9e93ded548/pyproject.toml#L36-L43), [current SDK host](https://github.com/mem0ai/mem0/blob/b7ad69afda6b6ed030347c66d48a13e4de9dec08/mem0/client/main.py#L211-L250), [current SDK HTTP add](https://github.com/mem0ai/mem0/blob/b7ad69afda6b6ed030347c66d48a13e4de9dec08/mem0/client/main.py#L292-L330).

## 8. 우리 계약에 가져올 architecture hints — 도입 권고가 아니다

1. **추출 candidate와 기존 memory comparison을 분리해 생각한다.** LangMem은 둘을 같은 model call에 넣고 exact final diff를 host가 수행한다. 과거 Mem0는 facts extraction→candidate별 retrieval→op decision의 두 call이다. current Mem0는 retrieval→ADD-only extraction 한 call이며 comparison의 목적이 dedup/linking이지 mutation 선택이 아니다. 이를 같은 “자동 기억” 기능으로 뭉뚱그리지 않는다.
2. **no-op을 두 층으로 정의한다.** 모델 useful/semantic duplicate 판단과 deterministic equality/idempotency 판단은 별개다. LangMem exact diff, mnema op/candidate keys, Mem0 text MD5에서 빌릴 수 있는 힌트는 있지만 이것들만으로 의미 중복이나 전-store 충돌 해결이 보장되지 않는다. 과거 Mem0 NONE의 metadata write처럼 “no-op” 명칭만 보지 말고 side effect를 명세한다.
3. **omitted/empty/invalid를 분리한 계약이 필요하다.** 조사 대상은 동일한 empty 결과로 합치는 곳이 많다. mnema judge의 partial verdict를 checked로 만드는 경로, Mem0 parse error를 empty extraction으로 만드는 경로, LangMem delete-only final_puts=[]는 우리 상태와 1:1로 매핑하면 위험하다. 실제 operation/result/error coverage를 따로 기록하는 설계 힌트다.
4. **모델에게 quote를 요청하는 것과 host evidence 검증은 다르다.** 가장 구체적인 힌트는 mnema의 실제 source ID membership 검사·host-generated excerpt/hash·수정 후 supports_current_body=false다. 그러나 span/role/time binding, semantic support, 원문 hash 재확인, signed approval까지 제공하는 완성 계약은 아니다. host-observed speaker/time와 model-attributed useful fact를 분리해야 한다.
5. **충돌은 데이터 관계로 보존할 수 있다.** mnema unresolved/stale/orphaned/resolved 및 keep/keep_both는 loser 원문을 삭제하지 않는 힌트다. 다만 2단계 token은 인간 승인이 아니므로 signed approval을 따로 정의해야 하며 judge-input snapshot hash와 commit-current hash를 정확히 bind하는 경계가 필요하다.
6. **반환값과 영구 side effect를 별도로 읽는다.** default 선저장, final_puts에 deletion 미포함, NONE metadata write, message cache writes on empty extraction, entity-index mutation, vector/history/mirror drift 등은 control-flow 비교에서 숨기면 안 된다.
7. **실행 route의 승인 여부는 별도 증명 대상이다.** OSS에 Anthropic/OpenAI/provider abstraction이 있다는 사실을 회사 permission으로 해석하지 않는다. 이 조사에서 승인된 Claude/Codex caller 재사용 또는 허가된 team-native executable route를 구현·검증했다고 주장하지 않는다. 로컬 LLM/embedding/reranker 설치나 회사→개인 Jev fallback을 제안·실행하지 않았다. 개인 Jev 가능 여부와 회사 data route는 독립이다.

## 9. 미확인·미측정 사항

- 모델 실제 usefulness/중복/충돌 판정 정확도, 한국어 처리 성능, threshold calibration, latency/cost는 측정하지 않았다.
- LangMem installed Trustcall의 retry/validation 정책 및 실제 BaseStore atomicity/history는 이 SHA와 범위로 고정하지 못한다.
- Mem0 hosted backend/현재 hosted MCP 구현은 공개 OSS SDK와 동일하다고 가정하지 않았다.
- 위 race/partial-write/SDK-drift 관련 지적은 관측한 코드와 언어 semantics의 정적 분석이다. `[INFERENCE]` 표시한 exception/concurrency 결과를 실행 재현했다고 말하지 않는다.
- 기존 회사 source/config/AF artifact는 수정하지 않았다. 생성한 것은 parent 통합용 이 local research report뿐이다. 실행 검증이 금지된 조사이므로 parent에 tests/build를 요구하지 않는다.
