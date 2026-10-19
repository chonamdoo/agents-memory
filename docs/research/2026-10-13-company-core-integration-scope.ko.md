# 회사 no-local-ML 경로: caller 후보 제출과 선택적 native 분류기 통합 범위

## 결론

**권고는 두 개의 독립 승인 작업이다.** A는 현재 승인된 coding-session caller가 원문에 연결된 후보/제외/검토를 제출하고, 서버가 정확한 근거·권한·철회를 집행하며 lexical/entity 후보를 다시 제공하는 회사용 명시 capability다. B는 A의 동일 판단 계약을 승인된 작은 native 모델의 제한된 신규-window 배치에 연결하는 선택적 실행기다. B는 별도 회사 자동화 승인이 없으면 disabled다. TypeSafe adapter를 넣거나 Claude CLI로 generation URL을 바꾸는 것만으로 A가 완성되지 않는다.

현재 서비스는 A/B 모두 구현되어 있지 않다. `memory_record(kind=note)`는 source를 만들고 기존 extract job을 enqueue한다. extract는 embedding까지 필수이며 이후 consolidate로 넘어간다. recall도 embedding→hybrid search→rerank가 필수다. 따라서 **local ML 없이 note receipt가 committed라는 사실을 회사 memory pipeline 완료로 표시하면 잘못이다.** 반면 승인 rule 전달은 모델 없이 이미 가능하다. 이것만 켠 것을 회사 memory 전환 완료라고 부르면 안 된다.

이 보고서의 설계는 [INFERENCE/제안]이다. 아래의 “현재”는 읽은 코드에 근거한다. 회사 승인, 모델 품질, 실제 회사 native 실행, 비용 절감은 확인하지 않았다. 조사자는 설치·clone·git 변경·build·lint·test·formatter·native 실행을 하지 않았고, auth/secret 파일을 열거나 복사하지 않았다. 유일한 작성물은 이 `local://` 보고서다.

## 조사 범위와 근거 해석

- Leader 기준 `L=/Users/namdoo/Developer/Aiproject/agent-memory-mcp`.
- Frozen successor 기준 `S=/Users/namdoo/.agent-flow/worktrees/agent-memory-mcp-97e899f21134/feat-agents-memory-resume`.
- 이하 별도 접두사가 없는 source/test/docs 경로는 L 기준이다. AF source는 L의 설치된 `.agent-flow`다. S의 내용을 leader에 합치거나 승인하지 않았다.
- codegraph는 이 프로젝트에 index가 없다고 응답했다. 생성하지 않았다. `find`의 TypeSafe judge 401/authentication failure는 코드 부재 증거가 아니다. 이후 literal grep/glob 및 반환된 source range를 읽었다. 조사자는 references를 grep과 직접 호출 경로로 확인했다. Parent의 `xd://lsp` status에는 sourcekit-lsp만 configured/not-started로 보고되었으며 Python server는 등록되어 있지 않다. 이것은 exhaustive reference 증거가 아니다. 실제 exported-symbol 변경 전에 해당 구현 환경의 LSP 지원 여부와 callsite 범위를 다시 확인해야 한다.
- 공개 CLI 문서는 현행 문서의 기술 설명이다. 설치된 CLI version/managed policy와 같다고 가정하지 않는다. repo docs의 실행 수치도 **문서에 기록된 과거 결과**이지 이 조사에서 실행한 결과가 아니다.

## 1. 현재 구조와 정확한 막힘

| 책임 | 구현 위치·함수 | 현재 동작과 재사용 계약 |
|---|---|---|
| 입력 타입 | `domain.py:90-150`, `CaptureCommand`, `RecordCommand`, `FeedbackCommand`, `ContextCommand` | capture는 source body·speaker·origin·event_time·snapshot을 받는다. record는 note/rule_candidate뿐이다. selection label/grounded submission 타입이 없다. feedback은 후보일 뿐 승인/삭제가 아니다. |
| 증거와 상태 | `domain.py:154-204`, `Source`, `Quote`, `ClaimDraft`; `domain.py:258-307`, `Operation`, `JobLease`, `Admission` | 원문 source와 derived claim 분리. evidence quote/byte_start 지원. operation terminal 소비자는 semantic_ready만 정상 완료로 본다. |
| 권위 ingest | `store.py:395-445`, `_capture`, `capture`; `484-520`, `record`, `feedback` | 원문/idempotency/origin 충돌 검사 및 injected-memory 차단. 모든 새 정상 capture는 extract를 enqueue. agent note는 actor/key에서 origin을 만들며 speaker=agent_note. rule_candidate는 inactive proposal 생성. |
| 실제 worker | `jobs.py:71-143`, `Worker._process` | model(extraction)와 model(embedding) 확보→admit_job→source 1개 추출→모든 claim embed→lexical row→publish_extraction. blocking 모델 부재는 blocked이지 empty 성공이 아니다. |
| 결과 publication | `store.py:1358-1413`, `publish_extraction` | claim마다 vector 및 lexical row 1개 필수. publication fence→source span 검증→claim/source/spans/entities 기록. claim이 있으면 관련 claims까지 consolidate job 생성. standalone selection 결과 입력 경로가 아니다. |
| local runtime | `models.py:97-126,198-269,366-435,442-495,502-584` | verified local artifact/runtime pins, loopback generation, sentence-transformers embedding/cross-encoder rerank. `_generate`는 final stop, reasoning/tool_calls 없음, strict schema를 확인. `extract`는 `GeneratedExtraction`을 resolve한다. |
| 원문 validation | `semantic_contract.py:22-61`, `GeneratedExtraction`; `semantic.py:107-180`, `resolve_extraction`; `218-258`, `validate_extraction`; `store.py:1284-1309`, `_spans` | span inventory accounting, assertions/qualifications/validities references, exact UTF-8 quote, 반복 quote의 명시 offset, 조건·예외의 원문 phrase, 근거 없는 숫자/identifier/timestamp 차단. 일반 의미 entailment의 완전한 증명은 아니다. |
| 모델 route | `config.py:11-112`, `ModelConfig`, `Settings`; `store.py:797-808,1079-1090,1171-1255` | purpose enum은 extraction/embedding/consolidation/rerank/reflection. route revision은 local manifest와 semantic contract에 결합. extraction admission은 embedding route도 요구. configure_route는 operator 전용. disable/re-enable 왕복도 epoch로 fence한다. |
| recall | `application.py:50-144`, `context`; `store.py:810-849`, `search` | active claims 있으면 embedding admission→query vector→search→rerank admission 필수. vector+lexical+entity RRF(1/(60+rank)), pool 20. `ContextCommand` final limit 1–5, default 3, default byte budget 2400. 현재 lexical arm만 이용하는 공개 mode 없음. |
| 최종 제공 | `store.py:1953-1981`, `delivery`; `context.py:107-148,149-283`, `_claim`, `compose` | 실제 입력 admission·source revision·credential generation·relation 전체 lineage·active rule revision 재확인. 후보는 실행 권위 아님. conflict endpoint 또는 required applicability 모호함을 무시하지 않는다. |
| 통계와 복구 | `store.py:682-731`, `_stats`, `index_status`; `cli.py:295-325`, doctor/await/retry | embedding 없음/불일치는 stale_index_claims로 집계. await는 semantic_ready/blocked/failed/retracted에서 종료. no-vector 회사 후보가 들어오면 현재 통계와 await를 그대로 쓸 수 없다. |
| transport | `edge.py:45-65,246-333`, `SCHEMAS`, `create_app.api`, `call_tool`; `wire.py:13-46`; `stdio.py:45-120`; `client.py:21-79` | 4 MCP tool과 private API가 typed wire/shared Application을 사용. producer capture/correct 권한은 agent read 권한과 분리. duplicate JSON keys·nonfinite·strict coercion 금지. stdio/client는 loopback relay, 두 번째 engine 아님. |
| service lifetime | `edge.py:335-414`, readiness/lifespan; `application.py:146-179`, required_context/drain; `jobs.py:145-176` | readiness 모델 정보는 local artifacts_verified/blocked만 구분. worker start/stop, authority lock, source journal reconciliation 및 runtime drain. native와 caller capability를 추가하면 이 status도 바뀌어야 한다. |

**검색의 정확한 표현:** 현재는 PostgreSQL `text[]` GIN overlap과 entity exact matching이다(`0001_authority.py:52-79`, `lexical.py:1-61`). `tsvector/to_tsvector` FTS 구현이 아니다. tokenization은 NFKC/casefold 검색용 복사, camel/code 토큰, 한글 component 및 bigram을 생성한다. 이 정규화 결과를 증거 quote로 쓰지 않는다.

**embedding 금지사항:** `store._vector(:790-796)`는 실제 finite/nonzero 1024 vector를 요구하고 `embedding_revision`은 model descriptor·pooling·normalization·artifact identity를 묶는다(`semantic_contract.py:167-203`). Claude/Codex 텍스트 출력으로 숫자를 만들어 vector처럼 넣는 방안은 배제한다. no-local-ML이 no-DB/pgvector permission까지 뜻하지는 않는다. 현재 DB/pgvector 운영도 금지라면 A보다 먼저 저장소 운영 승인이라는 별도 선행 조건이 필요하다.

## 2. 세 경로 비교: 선별과 추출·검색은 다르다

| 경로 | 맡을 수 있는 일 | 못 하는 일/주의 | 권고 |
|---|---|---|---|
| 이미 읽은 승인 caller의 typed 제출 | 제공된 source window에 대한 remember/discard/review, 정확한 span references, 선택적 bounded grounded claim 초안 | 전체 source inventory를 읽었다는 증명, caller의 사실성·회사 권한 보장, 자동 수집 coverage 보장, rule/skill 승인 | A의 기본값. 같은 전체 로그 재독해를 피할 수 있지만 추가 출력·tool usage는 무료가 아니다. |
| TypeSafe custom subprocess provider | 같은 bounded state와 typed question을 native CLI 한 호출로 평가; 결과 shape를 통일 | local semantic engine/embedding/rerank를 자동 대체하지 않음. JSON shape가 의미 정확성이나 원문 provenance를 보장하지 않음 | B에서 adapter를 채택할 실제 이유가 있을 때만. 회사 core에 필수 의존성으로 넣지 않는다. |
| 현재 local embedding/rerank | 의미 vector index 및 cross-encoder 후보 정렬 | local 설치 금지 환경에서는 불가. small text classifier와 역할이 다름 | 개인 경로 유지. 회사는 명시 lexical/entity capability, 승인된 경우 B의 별도 bounded rerank 후속 범위. |

### authoritative event에 claim을 실을 수 있는가?

[INFERENCE] **가능하지만 “event authority”와 “claim truth”를 분리해야 한다.** authenticated source event가 서버에 원문 revision으로 저장되어 있고, caller 초안이 그 원문 span을 인용하면 서버는 claim의 근거 연결을 지원할 수 있다. 현재 `Quote`/`ClaimDraft`/`validate_extraction`/`_spans`를 재사용할 수 있다. 다만 현재 `CaptureCommand`에는 claim이나 selection 입력이 없고, store publication은 worker extraction+vector에 전용이다. 그냥 `Extraction`에 caller 값을 넣고 worker completed라고 표시할 수 없다.

특히 `memory_record(note)`에 caller가 쓴 요약을 저장한 뒤 그 요약을 인용하면 **agent_note를 근거로 한 주장**이지 human/tool 원문에 근거한 주장이 아니다. speaker를 human으로 승격하면 안 된다. 기존 producer token을 일반 MCP caller에게 주어 read/ingest 역할을 합치는 것도 안 된다. source가 host에서 관측되지 않은 구간은 capture gap이며 compact summary를 그 원문으로 치환하지 않는다.

## 3. 작업 A — Caller-grounded lexical 회사 capability [INFERENCE/제안]

### 결정된 최소 동작

1. **수집은 기존 source authority를 유지한다.** company caller mode에서 원문 capture는 durable source/receipt를 만들되 local extraction job을 자동 만들지 않는다. 기존 local mode는 그대로 extract→embed→consolidate로 간다. label을 받기 전 source는 unclassified로 보인다. source 저장 성공을 selection/semantic 성공이라 하지 않는다.
2. **4 MCP tool을 유지하면서 `memory_record`에 typed source-selection variant를 추가한다.** 기존 note/rule_candidate와 판별 가능한 union을 사용하고, selection variant에 원문 source IDs/revisions, window/coverage, policy revision, idempotency key, label, 근거 span IDs, 선택적 bounded claim drafts를 둔다. 모델이 actor/realm/host authenticity를 지정하지 못한다. private `/api/record`도 같은 handler를 쓴다. producer ingest만으로 자동 read 권한을 주지 않는다.
3. **remember와 claim-ready를 구분한다.** remember만 있으면 selected source window이지 searchable semantic claim이 아니다. exact evidence를 가진 claim 초안까지 정상 제출된 경우에만 lexical/entity index를 원자적으로 기록한다. source_selection provenance와 caller identity/policy를 저장하고 후보는 `caller_grounded_candidate`다. extraction completed/semantic_ready라 하지 않는다. 새로운 operation terminal `candidate_ready` 및 해당 capability의 causal read 조건을 명시한다. reject/review는 판단 기록의 완료이지 candidate-ready가 아니다.
4. **discard는 원문 purge/기존 claim 삭제/기존 rule 철회가 아니다.** review는 의미 보류다. timeout/schema/auth/route 오류는 failed/blocked로 남는다. key replay와 origin replay는 source revision+판단 payload 전체 digest가 같을 때만 같은 receipt다. 새 교정이나 새 정책 판단을 동일 이벤트/판단으로 합치지 않는다.
5. **후보 publication은 같은 DB authority transaction에서 한다.** current actor/grants, source state/revision/realm/binding/snapshot, deletion floor, selection policy approval epoch를 확인한다. 실제 원문 전체 span inventory를 제출했다는 선언과 선택된 span references를 구별한다. assertion/조건/예외/validity를 제출할 경우 기존 validators를 적용하고, 전체 extraction inventory 완료를 제출하지 않은 상태는 incomplete로 유지한다. 저장에는 am_claim_sources와 am_spans를 써서 existing deletion closure를 잇는다.
6. **검색은 explicit `lexical_entity` capability다.** 기존 eligibility CTE와 lexical/entity RRF, pool 20, final limit/byte budget을 재사용한다. vector arm·embedding call·mandatory rerank를 실행하지 않는다. 모델 미지원 reflect는 `CAPABILITY_UNAVAILABLE`류의 명시 실패로 반환한다. 필수 rules는 model-free existing required_context를 이용한다. synonym/paraphrase recall 저하는 결과 capability와 acceptance에 표시한다.
7. **최종 제공은 model-free actual-input manifest가 필요하다.** `delivery(admissions=())`만 부르면 선택한 claim/source 전체 재검증이 사라진다. current model admission과 다른 read-selection manifest를 만들거나 existing Admission을 명시 nonmodel purpose로 확장하여 credential/source revision/snapshot/policy epoch/selected claim IDs를 최종 transaction에서 재확인한다. route guard를 통째로 우회하거나 가짜 model revision으로 채우지 않는다.
8. **consolidation 미실행을 공개한다.** caller 후보의 관계 reasoning은 수행되지 않았다고 표시한다. 이미 알려진 conflicts와 complete relation lineage는 그대로 제공한다. 모순 발견을 완전히 수행했다고 주장하지 않는다. current publish_extraction의 consolidate enqueue를 재사용해 blocked queue를 만드는 대신 candidate path를 분리한다. 모델 없는 경로를 full semantic executor로 부르지 않는다.
9. **approval는 별도다.** candidate useful label·confidence·반복은 rule approval가 아니다. rule proposal→exact operator/approver approval→target scope revision→withdrawal 흐름은 유지한다. Profile/Notes/files/skills 편집은 A의 암묵적 부수효과가 아니다.

### 최소 확장 위치와 영향 파일

| 파일·현재 range | A의 영향 | 유지/추가 조건 |
|---|---|---|
| `domain.py:90-150,154-204,258-307` | record union/source-selection, source revision reference, label/coverage, candidate provenance, operation candidate_ready, nonmodel read manifest | strict extra-forbid/frozen pattern, timezone/byte bounds 유지. label 성공과 execution error 분리. |
| `config.py:11-112` | caller capability, ingestion/retrieval mode 및 bounded policy contract | company default에는 local model/artifact 검사 없음. “allowed_model_purposes=()”를 lexical permission으로 암묵 해석하지 말 것. |
| `semantic_contract.py:22-106,162-203`, `semantic.py:107-180,218-258` | caller claim validator/contract digest reuse, nonmodel selection policy version | local route semantic fingerprint에 caller/native 관련 validation/prompt 구현도 반영해야 함. `_SOURCE_NAMES`는 현재 세 파일뿐이므로 새 파일 변경이 자동 fence되지 않는다. |
| `store.py:395-445,484-520,557-568,682-749,797-849,1171-1255,1284-1413,1953-1981` | ingestion routing, source-selection receipts/publication, nullable vector 후보 indexing, lexical search, candidate inspect/stats/index-status, actual-input final fence | local vector publication은 그대로 strict. nonmodel read를 위해 existing model route 필수조건을 전역 제거하지 않는다. |
| `store.py:1564-1730,1860-1950`; `journal.py` | selection provenance/새 artifact의 correction/retraction/purge/restore closure | source-derived claim은 기존 lineage 사용. selection payload에 quote를 중복 저장한다면 그 사본도 purge 대상. journal entry에 raw body를 넣지 않음. |
| `application.py:26-144,146-179` | explicit recall capability dispatch, candidate causal readiness, unavailable reflect, drain/state | required rules·conflicts·byte omission 규칙 유지. |
| `jobs.py:71-143` | caller mode의 source가 local job로 잘못 들어가지 않게 분기 | 별도 in-memory queue 추가하지 않는다. 자동 실행 안 한 job을 done/semantic_ready로 fake finish하지 않는다. |
| `edge.py:45-65,246-333,335-414`; `wire.py:13-46` | union schemas/dispatch, authorization, readiness capability | MCP/private API 동일 handler; no token/realm trust from body. |
| `cli.py:253-325,record/context parser`; `client.py:21-79`; `stdio.py:45-120` | CLI typed submission/config/capability 출력, await의 candidate terminal, roundtrip | client/stdio business semantics 추가 금지. union schema·frame budget 호환 확인. |
| `hosts.py:62-80,1083-1134,1225-1340`; `host_templates/omp.ts:120-145`; `spool.py:195-234,304-385` | authoritative source pointer/coverage 전달과 source-selection caller mapping | 기존 raw capture spool과 판단 제출 의미를 구별. 현재 spool은 CaptureCommand 및 committed receipt 전용. 판단을 넣으려면 typed payload/expiry/quarantine/ack 재사용 계약을 명시 확장; 새 independent queue 금지. native capability는 host별 truthful. |
| `migrations/versions/0001_authority.py:39-79,132-152`; `0003_origin_and_vector_compat.py`; `0004_operation_successors.py`; `migrations/__init__.py:1-125` | 새 forward migration: selection/provenance/coverage/policy authority 및 claim origin/status metadata | 현재 embedding은 nullable라 lexical 가능. 새 tables 또는 columns의 삭제·복구·prior-schema restore 처리를 함께 정의. 기존 migration 파일 수정으로 history 치환 금지. |
| `ops.py:35-48` `_TABLES/_PRIOR_TABLES/_LATEST_TABLES`, migration/backup/restore paths | 새 persisted tables/migration manifest를 archive allowlist와 restoration prepare에 반영 | encrypted metadata cannot retarget authority; floors가 재수집·old backup resurrection을 차단해야 함. |
| `initialization.py:147-253`; `model_setup.py:15-78`; `pyproject.toml:5-26` | initialization capability/defaults, docs/optional extras 구분 | company에 local-model extra/install/download 요구 없음. local model pins와 personal explicit-network permission은 intentionally unchanged. |

새 persisted selection authority는 schema 변경 없이 client-only JSON memo로 해결할 수 없다. approvals/policy epoch/coverage와 삭제 closure를 authoritative로 다뤄야 한다. 단순히 새 method 한 개만 만드는 ticket으로 좁히지 않는다.

### A의 완료 기준과 parent 검증 대상 — 미실행

- 실제 service에서 authenticated raw event capture→caller remember+grounded claim→lexical/entity recall→inspect의 원문/speaker/time/provenance→correction/retraction→다음 consumer read까지. local ML import/install/HTTP generation이 없어야 한다.
- discard/review의 durable 판단은 inspect 가능하고 searchable useful claim으로 섞이지 않는다. failure는 정상 discard/review로 바뀌지 않는다. unobserved source window와 body budget truncation은 coverage gap으로 보인다.
- key replay/change conflict, wrong realm/project/grant/source revision, injected retrieved memory, repeated Korean UTF-8 offsets, 조건·예외, fabricated numbers/time/identifier, source deletion race, policy disable/re-enable, credential revoke, restore-old-backup 재수집을 방어한다.
- final lexical delivery가 source/revision/credential/policy/conflict lineage 변경을 거절한다. no-vector 후보는 stale-vector failure로 오분류되지 않으며 existing local stale-index 기능은 유지된다.
- 모델 없는 required rules는 유지하되 reflect/consolidation/vector 의미 검색 미지원은 명시적으로 보인다. actual native next-task consumption은 SDK/unit success와 별도 증거다.
- 기존 회귀 확장 위치: `tests/test_store_authority.py:144-333,351-568,788-1118`(admission/fences/replay/evidence/approval/restore), `test_application_boundaries.py:302-406`(worker invalidation/model blocking/model-free required rules), `test_semantic_boundaries.py:158-199,292-354`(exact evidence/inventory/validity), `test_context_boundaries.py:103-240`(qualifier/conflict/required applicability), `test_edge_boundaries.py:81-117,185-278`, `test_cli_boundaries.py:31-145`, `test_client_boundaries.py`, `test_stdio_boundaries.py`, `test_spool_boundaries.py:19-75,92-164,198-220,438-627`, `test_host_boundaries.py:442-548,1001-1018`, `test_initialization.py`, `test_ops_boundaries.py:273-328,389-587`, `test_journal_authority.py`, `test_lexical_boundaries.py`.
- 문서 변경은 `README.md`, `docs/architecture.ko.md`, `docs/requirements.ko.md`, `docs/implementation-plan.ko.md`, `docs/verification.ko.md`, `docs/update-checkpoint.ko.md`, 그리고 조사 결론과 다른 계약을 채택하면 `docs/research/2026-10-12-company-selection-cost.ko.md`. capability·未지원 semantic 기능·authorization/withdrawal·coverage·native 증거 등급을 구체적으로 기록한다. AF docs/config/artifacts는 이 ticket에서 변경하지 않는다.

## 4. 작업 B — Opt-in native small classifier [INFERENCE/제안]

A와 동일한 source-window/label/provenance 계약으로 배치 판단만 수행한다. **B는 embedding/rerank/consolidation/reflection까지 구현했다고 표시하지 않는다.** 그 기능을 추가할 때는 별도 명시 purpose/admission/품질 합격 기준이 필요하다.

### TypeSafe pinned adapter의 실제 연결점

대상 pin은 `e1d4cc938204b22fc5a3c3aca7044072fe3f712d`다. [README](https://github.com/typesafe-ai/system-one-adapter-python/blob/e1d4cc938204b22fc5a3c3aca7044072fe3f712d/README.md)의 표준 내장 provider는 API SDK(openai/anthropic/gemini)이지 team native login 자체가 아니다.

- [`providers/base.py:46-94`](https://github.com/typesafe-ai/system-one-adapter-python/blob/e1d4cc938204b22fc5a3c3aca7044072fe3f712d/src/system_one_adapter/providers/base.py#L46-L94): `ProviderResult(text,input_tokens,output_tokens)`, `SyncProvider/AsyncProvider`의 `model_name`, `request(messages, schema, structured)`, `translate_error` protocol을 custom native provider가 구현할 수 있다. 없는 usage는 None이지 0이 아니다.
- [`_client.py:327-402`](https://github.com/typesafe-ai/system-one-adapter-python/blob/e1d4cc938204b22fc5a3c3aca7044072fe3f712d/src/system_one_adapter/_client.py#L327-L402): caller-owned provider instance를 **model 인자**로 주입한다. defaults는 normalize_probabilities=False, malformed corrective retries=0, transient RetryPolicy(max_retries=0). injected provider는 client-owned provider cache에 들어가지 않아 lifecycle cleanup 책임을 caller/provider owner가 가진다.
- [`_client.py:197-279`](https://github.com/typesafe-ai/system-one-adapter-python/blob/e1d4cc938204b22fc5a3c3aca7044072fe3f712d/src/system_one_adapter/_client.py#L197-L279): schema validation+optional correction loop와 transient retry loop는 별도다. transient time/retry budget은 각 provider request 기준이어서 전체 evaluation deadline을 애플리케이션에서 따로 enforce해야 한다. request마다 `llm_attempts`에 messages/schema/raw response를 모으고 failure debug에도 들어간다.
- [`_utils/probability_normalization.py:91-94`](https://github.com/typesafe-ai/system-one-adapter-python/blob/e1d4cc938204b22fc5a3c3aca7044072fe3f712d/src/system_one_adapter/_utils/probability_normalization.py#L91-L94): discrete Choice는 one-hot 확률로 바뀐다. 따라서 confidence=1이 나와도 calibrated certainty 1이 아니다. label 모델은 `Choice(remember,discard,review)`를 쓰되 confidence로 auto approval/discard threshold를 만들지 않는다.
- [`_schema.py:147-177`](https://github.com/typesafe-ai/system-one-adapter-python/blob/e1d4cc938204b22fc5a3c3aca7044072fe3f712d/src/system_one_adapter/_schema.py#L147-L177): enum/Literal shape를 제공하지만 source span coverage나 근거 연결은 memory core validation 책임이다.

**채택 조건:** core에는 TypeSafe SDK의 회사 API 키/endpoint가 필요하지 않아야 한다. adapter가 선택적 native 실행 경로를 단순화하는 경우에만 pinned optional dependency로 넣는다. builtin API provider fallback은 회사에서 차단한다. prompts/raw responses/attempt traces를 정상 telemetry·DB receipt·repo artifact에 저장하지 않고, 필요한 경우 별도 승인된 민감 진단 보관 계약을 적용한다. public-source investigation에서 tool find의 개인 API auth failure가 발생했다는 사실을 회사 core의 TypeSafe dependency가 필요하다는 근거로 쓰지 않는다.

### native 실행 계약

- **입력 envelope:** realm/deployment/binding, admitted source IDs/revisions, speaker/event_time/recorded_at, exact raw spans와 adjoining qualification context, source-window coverage/truncation, policy+schema digest, requested provider/model/effort, invocation budget/deadline. actor와 source provenance는 서버가 구성한다. model explanation은 source evidence가 아니다. stdin 전달로 process argv에 원문을 싣지 않는다.
- **출력:** 제공된 event IDs 각각 정확히 1개 label, bounded selected evidence references/필요한 claim 초안, unknown/review reason. 누락·중복·foreign IDs·unexpected fields·nonfinite·tool call·중간 reasoning·turn failure는 invalid artifact다. code는 terminal envelope와 payload schema를 둘 다 확인한다.
- **tool/config 격리:** memory MCP/hook/skills를 분류기에서 로드하면 재귀 capture와 권한 사용이 가능하므로 차단한다. user/project customization, inherited proxy/tracing/provider route environment, session resume, model fallback을 명시 관리한다. approved provider 인증은 CLI가 처리하며 서비스는 auth 파일을 읽거나 복사하지 않는다. 동일 HOME 복제나 same UID를 보안 경계라 하지 않는다.
- **Claude:** [공식 CLI reference](https://code.claude.com/docs/en/cli-reference)상 `-p`, `--json-schema`, `--output-format json`, `--tools ""`, MCP 별도 deny/strict config, safe-mode, no-session-persistence 사용 가능하다. `--tools ""`만으로 MCP tools는 꺼지지 않는다. safe-mode도 managed hook/status/file-suggestion policy가 남을 수 있어 “아무 코드 실행 없음”으로 추정하지 않는다. [headless](https://code.claude.com/docs/en/headless) 설명의 bare는 subscription OAuth/keychain을 쓰는 로그인에 그대로 적용할 수 없으므로 bare로 안전과 team-login 재사용을 동시에 보장한다고 말하지 않는다.
- **Codex:** [공식 noninteractive](https://developers.openai.com/codex/noninteractive/)는 exec, JSONL terminal events/usage, output-schema, ephemeral, read-only sandbox와 ignore-user-config를 설명한다. read-only는 command/network/read 자체를 모두 금지하는 tool-free 계약이 아니다. 승인된 settings/provider/tool restrictions와 OS isolation으로 검증해야 한다. current CLI가 served model을 안 보고하면 requested model만 기록하고 실제 served model은 unknown으로 남긴다.
- **execution authority:** native classify purpose의 operator-approved route descriptor는 CLI executable/version/fingerprint, provider/workspace 승인 식별자(비밀값 아님), requested model/effort, prompt/schema contract digest, tool/config policy, timeout/byte budget를 포함한다. route epoch admission→외부 실행→publication recheck를 재사용한다. source/credential/route 변경 후 결과를 못 publish하게 한다. classifier가 am_routes를 승인하지 못한다.
- **lifecycle:** existing single durable job ownership을 재사용한다. 새 independent queue/항상 켜진 개인 fallback 없음. process group·hard deadline·bounded stdout/stderr·terminal detection·kill+reap·cancellation/drain을 구현한다. Python wait_for만 끝난 상태를 remote completion으로 표시하지 않는다. retry는 디폴트 0, 허용하더라도 outer total deadline/budget 내에서만. timeout·unsupported account/model·auth failure·quota·malformed→blocked/failed, never normal discard.
- **usage:** requested/served identity, total/cached input/output/reasoning tokens, process startup/context overhead, invocation/retry count, elapsed time, provider usage source를 구분한다. 미보고는 unknown. Claude client-side USD는 subscription 청구액이 아니다. usage/stats는 body-free summary로 저장하며 debug transcript 보관을 뜻하지 않는다.

### 왜 AF provider를 runtime에 그대로 import하면 안 되는가

`L/.agent-flow/local-skills/architecture/SKILL.md:8-30`는 AF/Claude/Codex/OMP를 **consumer, not runtime dependency**로 명시한다. AF source를 참고해 native lifecycle 방식을 맞출 수는 있지만 runtime을 AF workflow/worktree에 종속시키면 기존 경계를 깨뜨린다.

- `providers/subprocess.py:45-53,321-399,474-492,1030-1101`: ProviderCommand의 timeouts, OS launch, new process session, bounded outputs, kill/reap 패턴 참고 가능.
- `:892-965` sandbox profile은 `(allow default)` 뒤 file-write를 deny하고 선택 scratch/workspace 예외를 연다. **write-confinement이지 confidentiality/egress sandbox가 아니다.** arbitrary reads와 network까지 차단했다고 볼 수 없다.
- `:430-473`은 verified linked worktree identity를 요구한다. memory service의 stable daemon/caller task는 이 전제를 만족한다고 가정할 수 없다.
- `:540-570`은 provider state preparation 중 native auth 파일을 private scratch로 복사하는 구현을 포함한다. 이 조사와 새 company contract의 auth 파일 미열람/미복사 제한 아래에는 그대로 재사용할 수 없다.
- `multi_review.py:282-327`의 Codex `danger-full-access`는 **밖의 verified read-only OS sandbox 때문에만** 사용한다는 주석이 있다. 그 outer confinement 없이 classifier argv를 복사하면 안 된다. Claude plan/safe-mode도 tool-free classifier와 동치가 아니다.
- `adapters/hosted.py:139-182,580-584`의 읽기 전용/in-session Task 금지 등은 prompt 지시다. subprocess OS file-write deny와 구분한다. reviewer task envelope/AF artifact를 회사 classifier task envelope로 겸용하지 않는다.

B의 추가 영향: A의 domain/config/admission/routes/jobs/edge/cli/readiness/tests/docs, optional provider 파일과 prompts/semantic-contract fingerprint, pyproject optional dependency. `LocalSemanticRuntime`에 native small classifier를 억지로 동일 embedding-capable runtime으로 넣지 말고 bounded selection executor protocol로 분리한다. 이 프로토콜 분리는 서로 다른 capability를 정확히 표현하는 최소한의 경계이지 provider framework 확장이 아니다.

### B의 출시 전 실제 합격 조건 — 미실행

1. 회사 관리자가 해당 team workspace, model, noninteractive/headless 배치, unattended 여부, source 데이터 등급/egress/retention/telemetry 및 해당 계정 사용 계약을 승인해야 한다. native sign-in 기술 가능과 회사 승인/이용약관 합격은 다르다.
2. 실제 설치 버전과 company managed settings에서 tool/MCP/hook/skills 금지, session isolation, auth non-copy, provider fallback 없음, requested/served model 증거 및 unknown 처리 확인. 단순 prompt의 “don't use tools”로 통과하지 않는다.
3. 동일 승인 corpus에서 A caller와 B 신규-window batch를 비교: durable correction/한국어/code/조건·예외/shared scope/cut batch/injection/ambiguous context·보류·누락을 평가하고 다음 coding task까지 추적. CLI JSON 성공만으로 useful recall 품질을 통과시키지 않는다.
4. 실제 전체 사용량과 base context/startup overhead·cache·retry·wall latency·workspace quota/실제 청구 관측을 분리. 목표 수치는 회사 workload 승인 전 새로 꾸며내지 않는다.
5. 실제 kill/reap/drain, output overflow, account/model unsupported, route revocation roundtrip, source/credential revoke 중 publication race가 explicit failure로 남는지 확인한다. known completed와 unknown provider completion을 구분한다.

## 5. Leader와 frozen successor의 관계

현재 확인한 source 차이와 문서상 과거 상태를 분리한다. git mutation/diff 도구를 실행하지 않아 전체 revision 간 exhaustive diff라고 주장하지 않는다. 이 통합에 필요한 차이는 직접 읽었다.

| 항목 | L | S | 통합 판단 |
|---|---|---|---|
| source time evidence | `domain.py:204-218`, EvidenceSpan은 speaker/revision/bytes/quote; `store.py:557-564`는 speaker만 join | `S/domain.py:220-231`은 source_event_time/source_recorded_at 추가; `S/store.py:580-586`은 original source time을 join | caller/native provenance에는 S 계약이 유리. event time=null을 허용하고 recorded_at과 구분. 날짜가 validity/approval/supersession은 아님. |
| context projection | `context.py:107-141`은 model-derived candidate와 original speaker/span; source time 없음 | `S/context.py:106-134`에 source_event_time/source_recorded_at projection | A를 L에만 설계해 S metadata를 잃지 말 것. parent가 승인된 base를 정한 후 한 번 통합. |
| binding relocation | L에는 inspected domain/CLI에 explicit BindingRelocation 없음 | `S/domain.py:90-105`, `S/store.py:305-325`, `S/cli.py:263-272` | native stable locator와 caller binding pointer는 relocate revision/receipt 계약을 존중. directory path가 business identity가 아니어야 함. |
| model adoption guard | `L/cli.py:277-288` runtime construction/validation이 inspected block의 settings update 앞 | `S/cli.py:286-308` operator check→typed ModelConfig/Settings→runtime artifact validation→config publish→route approval | 새 caller/native adoption도 operator/typed policy 먼저, approved route publish/restart 필요. permission 없이 validation/side effect부터 수행하지 않는다. |
| malformed native state | S `hosts.py:1136-1173,1225-1278` validation/read boundaries 및 docs 기록 | S checkpoint는 실제 CLI HOST_STATE_INVALID와 no body offer/reset을 기록 | 새로운 source-selection metadata를 host state에 넣으면 이 strict validator/receipt shape 같이 확장. 오류를 empty generation으로 reset하지 않는다. |
| temporal reflection | S semantic/prompts는 exact source field ISO8601와 unknown prose 구분 | `S/docs/update-checkpoint.ko.md:93-123`은 actual reflection MODEL_OUTPUT_INVALID도 기록 | raw source를 바꾸거나 validator를 약화해 성공으로 만들지 않는다. caller path에도 unsupported time prose 방어 유지. |

S checkpoint는 과거 공식 all gates 834 후 추가 수정에 대해 845 tests, lint/test/package 3/3 결과를 기록하고 fresh confined Claude/Codex review→QA→local handoff를 다음 단계라고 적는다. **이는 이 조사에서 재실행하거나 현재 상태를 보증한 결과가 아니다.** 승인 완료·merge·회사 운영 완료가 아니다. A/B를 그 frozen run에 슬쩍 끼워넣지 않는다.

## 6. 실제 설치된 AF 구현 진입점과 repo instructions

전용 `implement/SKILL.md` 경로를 만들어내지 않는다. 설치된 구현 단계의 실제 source는 workflow YAML과 required discipline skill이다.

- 상속 instructions: `/Users/namdoo/AGENTS.md:1-30`. AF status-first/workflow next_command 규칙이 있지만 현재 assignment는 read-only scoping이며 AF lifecycle를 진행하지 않았다. L/S root `AGENTS.md`/`CLAUDE.md`는 glob으로 찾지 못했고 부모 `/Users/namdoo/Developer/AGENTS.md`, `/Users/namdoo/Developer/Aiproject/AGENTS.md`도 발견되지 않았다.
- installed entry skill: `/Users/namdoo/Developer/Aiproject/agent-memory-mcp/.agent-flow/skills/agent-flow/SKILL.md:1-60` 및 같은 installed runtime의 `runtime/python/agent_flow/skills/agent-flow/SKILL.md`.
- 실제 local-handoff implementation phase: `/Users/namdoo/Developer/Aiproject/agent-memory-mcp/.agent-flow/runtime/python/agent_flow/workflows/development.yaml:12-19`; required `code-generation-discipline`, artifact `implement.md`. `:21-80`은 confined review/QA/handoff. publication/merge를 허가하지 않는다.
- default workflow implementation contract: `/Users/namdoo/Developer/Aiproject/agent-memory-mcp/.agent-flow/runtime/python/agent_flow/workflows/default.yaml:214-299`.
- 실제 required skill path: `/Users/namdoo/Developer/Aiproject/agent-memory-mcp/.agent-flow/skills/code-generation-discipline/SKILL.md:1-68`; local architecture `/Users/namdoo/Developer/Aiproject/agent-memory-mcp/.agent-flow/local-skills/architecture/SKILL.md:1-30`.
- skill discovery/index: `.agent-flow/runtime/python/agent_flow/core/skill_resolver.py:60-115`, `.agent-flow/skills/index.json:160-201,235-281,294-346,882-897`. Python guide·llm-tool-development·security 관련 실제 resolved union은 parent의 새 승인 구현 run에서 선택한다. installed skill metadata approval=unattested를 회사 보안 승인으로 바꾸지 않는다.
- installed launcher: `.agent-flow/bin/agent-flow:1-38`는 runtime `python -I` 진입점을 사용한다. 이번에 실행하지 않았으며 다른 global/plugin-cache runtime을 대신 쓰지 않았다.
- Python QA profile `.agent-flow/profiles/python.local.yaml:1-29`는 lint `uv run ruff check src tests`, test `uv run pytest -q`, package `uv build`. **이 보고서가 실행 허가나 실행 결과가 아니다.** parent가 모든 구현이 끝난 뒤 승인된 run에서 한 번 검증한다.

## 7. Profile/Log/Notes/files/skills에 적용되는 권위 경계

이번 core ticket에 파일 자동 편집이나 skill compiler를 포함하지 않는다. 회사용 경로가 Notes-only 또는 rules-only 전환이라는 오해를 막기 위해 저장 의미를 명시한다.

- Log/source: 관측된 원문·화자·시각·revision·coverage. 기억 후보 판정과 다른 데이터다. unobserved native lifecycle는 Log coverage complete가 아니다.
- Notes/grounded candidates: caller의 해석·작업 상태·선호/절차 초안. 원문 근거와 candidate role을 보인다. supersession은 새 evidence/명시 교정 authority로만 처리한다.
- Profile: 개인 preference라도 realm/subject/source 범위를 좁혀 candidate로 관리한다. 회사 preference를 개인 cloud Profile로 자동 승격하지 않는다.
- files: 원문 pointer와 revision/hash를 갖춘 source일 수 있지만 검색 hit가 파일 변경 권한을 만들지 않는다. 큰 file/body export와 Notes 복제는 별도 데이터 이동이다.
- skills/rules: 실행 지침이다. useful 판단·반복·confidence에서 자동 compilation/approval 하지 않는다. exact approved revision/selector/target set, 명시 철회와 이미 전달한 host context의 남은 사본 경계를 존중한다.

동일 비용·정확성·provenance·승인/철회·realm 격리 기준을 사용한다. A의 후보 선별 성공을 이 다섯 저장/권위 영역의 자동화 성공으로 확대하지 않는다.

## 8. 남아 있는 외부 승인 경계와 parent 결정

**도구/repo에서 확인할 수 없는 실제 회사 permission:** 팀 관리자 headless/unattended/native account 사용, 작은 모델 entitlement·served identity 확인, 회사 corpus 전송/보관/telemetry 정책, native auth non-copy isolation 정책, PostgreSQL/pgvector/daemon/MCP local 설치 및 ingress 허용, CPU/disk/backup 제한, 실제 quota/예산. 개인 Jev가 가능한 사실은 회사 데이터를 개인 provider로 보낼 권한이 아니다. 이 경계를 코드/문서만 읽어 “승인됨”으로 만들 수 없다.

Parent가 결정할 구현 단위는 A 전체의 candidate ingest→evidence validation→lexical recall→inspect→approval/retraction/restore→다음 caller read다. 이는 명시적으로 제한된 **caller-grounded lexical capability**이며 기존 full semantic pipeline과 동등하다고 주장하지 않는다. 이 제한 자체에 대한 사용자 승인 없이 기존 architecture의 full pipeline 완료 요건을 낮추면 안 된다. B는 회사 native 자동화 승인을 확보한 뒤 동일 계약으로 독립 승인한다. 전체 semantic executor가 필요하면 승인된 generation/consolidation/reflection 및 실제 vector 대안의 추가 작업이 필요하고, 작은 classifier B에 이름만 붙여 포함시키지 않는다.

기존 retrieval skill의 200-character/60-overlap·항상 hybrid·final≤5 mandatory rerank 원칙을 이 회사 제한 경로에 몰래 적용하거나 준수했다고 표시하지 않는다. 이번 설계는 기존 source-span slicing을 유지하며 chunk 수 측정은 하지 않았다. no-vector/no-rerank는 **설치 금지와 명시 capability에 따른 제안된 예외**다. lexical+entity RRF, pool 20→default final 3/byte budget 계약을 설명했고, aggregate는 top-k 전수라고 하지 않으며 원래 structured stats 범위와 분리한다. 이 예외를 승인받기 전 동일 검색 품질 또는 full pipeline 완료라고 말할 수 없다.

참고 1차 공개 출처: [Claude CLI](https://code.claude.com/docs/en/cli-reference), [Claude headless](https://code.claude.com/docs/en/headless), [Claude Agent SDK scope](https://code.claude.com/docs/en/agent-sdk/overview), [Codex noninteractive](https://developers.openai.com/codex/noninteractive/), [Codex auth/workspace](https://developers.openai.com/codex/auth), [TypeSafe API](https://docs.typesafe.ai/api.md), [pinned adapter](https://github.com/typesafe-ai/system-one-adapter-python/tree/e1d4cc938204b22fc5a3c3aca7044072fe3f712d). Repo 비용 관측의 해석은 `docs/research/2026-10-12-company-selection-cost.ko.md:3-63`을 따른다: 공개 합성 입력 개인 probe일 뿐 회사 권한·모델 정확도·실청구·비용 절감 실증이 아니다.
