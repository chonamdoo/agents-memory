# 실제 로컬 검증 기록

2026-10-11 시작한 Agent Flow development run `20261011-173040`의 product smoke 기록이다. source 사실, 결정, deterministic 회귀, native 실행, 운영 외부 조건과 미관측 상태를 분리한다. 실제 1–2주 trial이나 cloud 배포를 통과했다고 주장하지 않는다. private token·DSN·원문 회사 자료는 이 문서에 넣지 않는다.

## 실행 환경·관측

- AF0.3.15, main `0ffba881a0c3f1c20f41359f205ef4e517ed5482`, Python local profile/isolated feature worktree. 기존 global AF0.3.14는 변경하지 않았다.
- Python3.12.13, 공식 `mcp2.3`, PG18.6, pgvector0.8.7. PG image `pgvector/pgvector@sha256:9d9c930220cb9bf2f956d10a8f909cf9973d9672ca0278aef2c1e6facccad2e0`. 실제 product DB와 app/operator 분리 권한을 사용했다.
- generation: post-trained Qwen3.5-9B `c202236235762e1c871ad0ccb60c8ee5ba337b9a`를 실제 llama.cpp `5c8854fd88319125125dc4b836c98b1b215b0f23`로 F16 변환·Q4_K_M 양자화. 별도 converter runtime, 원본/license/tokenizer/converter/native executable/GGUF의 manifest pin을 기록했다.
- embedding BGE-M3 `5617a9f61b028005a4858fdac845db406aefb181`, actual 1,024 dimensions. cross-encoder BGE-reranker-v2-M3 `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`. 가짜 vector·mock provider로 full-loop proof를 대체하지 않았다.
- 실제 local model 목적별 route 승인 후 capture→extract/embed→consolidate→hybrid recall/rerank→문장별 cited reflection→trusted correction→다른 native 세션의 next recall을 수행했다. reflection은 active rule이 아니다.
- 최신 코드의 actual PG/age runtime을 제공한 `uv run pytest -q`: **747 passed, 91.75s, skips0**. `uv run ruff check src tests`: pass. `uv build`: `agents_memory` sdist/wheel pass. 5차의 fresh receipt eviction1개와 잘못된 새 HTTP default/header 입력4개는 수정 후717개 통과했다. 6차 첫 통합은742 passed/5 failed였으며 다섯 새 assertion이 extraction publication만 실행하고 consolidation 전 `semantic_ready`를 기대했다. pipeline completion 단계를 실제 실행하도록 fixture/smoke를 수정했으며 제품 readiness를 pending에서 임의 승격하지 않았다. 전체 재실행이 위747개다. 테스트는 LLM 일반 정확도나 native enforcement 증거를 대체하지 않는다.
- 사용자 지시에 따라 GitHub 저장소·배포 패키지·CLI·MCP 이름은 `agents-memory`, Python namespace는 `agents_memory`, 소비 프로젝트 숨김 경로는 `.agents-memory`, 현재 Git branch는 `agents-memory`다. 같은 AF run·DB·journal·원문 source를 유지했다. 역사적 AF 실행 식별자와 기존 private runtime locator는 브랜드 기본값이 아니며 보존한다.

## 제품 smoke

### 영어 full loop와 다음 소비

복원 전 실행 기록: 합성 Orion의 offline-export 전용 codec와 company-code 외부 저장 금지/anonymous 예외를 캡처했다. 실제 두 claim·lexical/vector 두 retrieval arm·761 context UTF-8 bytes가 반환됐다. 실제 reflection은 세 cited 문장으로 게시됐다. producer의 정정으로 explicit owner approval을 추가하자 이전 reflection은 즉시 retracted/본문 없음이 되고, 다음 recall은 819 bytes와 새 source revision만 반환했다. 새 Claude·Codex·OMP 세션 각각 실제 `memory_context` 호출에서 정정된 owner-approval 조건을 읽었다. 이후 정정 전 archive의 복원으로 정정 후 본문은 되돌아오지 않았다. 이를 현재 corpus에도 남아 있다고 주장하지 않는다.

### 한국어 품질 실패·수정

초기 실제 추출은 회사 적용 범위를 바꾸거나 예외를 번역했다. strict validator가 이를 거절하거나 해당 source를 철회했다. 반복 추출에서는 qualifier 분류와 claim 개수가 달라졌다. 모델이 원문을 다시 쓰는 방식 대신, deterministic 원문 span inventory와 assertion/개별·공유 qualification/기간 참조를 단일 모델 호출로 선택하게 했다. 알 수 없는·중복 참조, 모호한 literal anchor, 미분류 span, 무근거 시간, 동일 assertion의 넓어진 무조건 duplicate는 게시하지 않는다.

변경하지 않은 원본 Polaris source의 SHA256은 `540b0fe95f2ac2df4be2885079162e5d5a55281dbdde939217f1480fb570613d`다. 현재 승인 route에서 `operation_cb86055ee77745ed8edc9aebb7c33dab`는 `semantic_ready`. 실제 recall은 **2,172 UTF-8 bytes**, 고객 코드 금지와 회사 적용·익명 합성 예외·기간의 원문 byte spans를 전달했다. `valid_time`은 원문 UTC 2026-10-11–25다. 일부 structured conditions가 빈 배열인 실행도 관측했으므로 올바른 분류·일반 entailment를 보장하지 않는다. 모든 supporting 원문 구절을 후보와 함께 전달하며, 예산 때문에 일부 qualification을 제거한 claim을 보내지 않는다.

실제 reflection이 `+00:00`을 같은 instant의 `Z`로 출력하자 숫자 tokenizer가 정상 결과를 거절했다. timezone-bearing timestamp 전체를 cited evidence의 instant와 대조한 뒤 숫자·코드 guard와 분리했다. 다른 날짜와 uncited timestamp는 거절한다. 현재 `reflection_b8666932d75d40019968c57f0e219bd9`의 실제 세 cited 문장은 회사 적용·예외, ISO UTC 기간, 고객 코드 저장 금지를 포함한다. candidate이며 승인 규칙이 아니다.

원본 Vega source SHA256 `3569442f94b9a602b9fd8b1a1e36aec997a25a7b878223d15183e8df98406f3f`도 그대로 재처리했다. `operation_930ee602989443e286c7024eca17057a`는 `semantic_ready`; 실제 recall은 **1,707 bytes**, JSON/YAML 두 후보와 `contradicts` 관계를 포함했다. `reflection_45772de0a1e74d1083a37e182be89a9b`는 두 주장을 각각 인용하고 어느 쪽도 approved policy가 아니라고 인용한다. winner를 선택하지 않았다.

새 successor의 성공이 이전 failed owner의 outcome을 지우지 않는다. 앞선 smoke 당시 stale claim과 미복구 live failed/DLQ 작업이 남아 current causal 완료와 전체 pipeline clean 상태는 달랐다. 4차 수정은 retired outcome과 live recovery counts를 분리했다. 명시 동일 owner retry의 실제 성공과 새 successor에 의한 복구는 별도 동작이며, 아래 최신 관측을 앞선 epoch의 상태로 소급하지 않는다.

같은 현재 Vega reflection을 operator CLI로 실제 철회한 후, `inspect`에서 reflection은 `retracted`/본문 없음, 원본 source와 JSON/YAML 두 claim은 모두 `active`/원문 evidence 유지였다. upstream/sibling을 지우지 않는 directional derived deletion을 실제 epoch80/head `867532192b6089f5c4282c8c75f60b291d7dd3891d019b774329fd56dcc77aa2`에서 관측했다. 위 reflection 생성 성공과 이후의 의도적 철회 상태를 혼동하지 않는다.

### backup/restore와 폐기

소유한 새 synthetic product DB의 정정 전 snapshot을 pg_dump+age로 실제 암호화했다. 독립 journal이 이후 정정/철회 head로 전진한 상태에서 service를 중지하고 **정정 전 archive를 실제 main DB에 복원**했다. 다음을 관측했다:

- 이전 operator/agent token은 AUTH_DENIED. fresh operator와 재발급 agent/producer만 사용 가능.
- routes disabled, rules 재승인 필요, jobs fenced, 현재 independent deletion floor 재적용.
- 이전 영어·잘못된 한국어 source와 reflection은 retracted이며 body/sentences가 없다.
- 같은 old origin을 fresh producer로 replay해도 `SOURCE_RETRACTED`; 부활/semantic_ready가 아니다.
- 실제 local purge는 source body1/claim2 rows를 scrub했다. local drain pending/provider completion·backup/WAL/media erasure unknown을 별도로 반환했다.

journal은 archive 밖에 존재하고 body-free HMAC/fsync chain이다. 같은 UID가 journal·DB를 함께 rollback하는 위협은 external head witness 없이는 해결되지 않는다. 이 archive에는 과거 source가 암호화되어 남으며 row purge를 archive/media 완전 삭제로 주장하지 않는다. 복원 후 목적별 route를 명시 재승인하고 세 host를 fresh credential로 지원 uninstall/reinstall하여 현재 로컬 서비스를 재가동했다.

### 2차 수정 이후 재실행

- 변경하지 않은 OrionR2의 30일 관찰 source를 trusted operator가 14일로 정정했다. 새 source `source_27d56a489b4941edb0817b844103a401`의 본문은 `OrionR2 keeps project cache entries for 14 days. This is an observed project setting, not an approved convention.`이다. 처음 모델은 미승인 문장을 별개 numeric claim으로 만들거나 근거 없는 calendar validity를 만들어 거절됐다. fixture/source/validator를 약하게 바꾸지 않고 generic qualification·numeric grounding·명시된 calendar bound만 허용하는 지시를 수정했다. 동일 새 source의 재처리 `operation_911457a7c04e4719b1b2783fffa94511`는 epoch114에서 `semantic_ready`.
- 실제 다음 native Claude/OMP/Codex 모두 `memory_context`와 두 `memory_inspect`를 호출했다. 현재 14일 assertion은 source bytes `[0,48]`, 미승인 qualification은 `[49,113]`, approved rules는 비어 있다. context body는 **699 UTF-8 bytes**, top-k omission을 명시한 partial이다. 기존 30일 source는 철회됐고 본문이 전달되지 않았다. 이후 journal 재적용의 metadata state와 앞선 물리 purge 관측을 구분한다.
- 기존 grounded claims의 lexical/entity/inspect/reflect eligibility를 generation route에서 분리했다. incompatible vector는 vector arm만 제외하고 embedding-only 복구를 실제 수행했다. 당시 확인한 snapshot 범위에서 `stale_index_claims=0`. epoch124의 pending0/blocked0/failed1/DLQ1은 아직 복구하지 않은 **live** `MODEL_OUTPUT_INVALID` job이었다. 이를 단순 historical이라고 부른 표현을 정정한다. 4차 실제 원본 retry 성공은 아래에 별도로 기록한다.
- 소유한 두 임시 DB에서 실제 init의 bootstrap 후 완료 receipt 쓰기를 한 번 실패시켰다. 응답은 `INIT_RECOVERY_REQUIRED`/COMMITTED. exact `--resume`은 원래 credential·owner를 인증하고 credential을 중복 발급하지 않았다. 정상 변경한 queue 설정은 completed replay 후에도 보존됐다.
- 실제 format2 archive의 `0001_authority`/`0002_directional_tombstones`를 이미 `0003_origin_and_vector_compat`인 별도 owned target에 복원했다. current forward migration3개, old operator `AUTH_DENIED`, fresh operator만 활성, routes disabled/jobs fenced, surviving floor의 본문 scrub을 관측했다. 임시 DB/파일은 제거했으며 main DB를 이 probe로 교체하지 않았다. 공급한 head는 operator provenance이며 외부 최신성 attestation이 아니다.
- 실제 synthetic required rule을 local-project 범위로 승인했다. 일반 UNKNOWN 조회는 규칙 본문과 `stamp.rules` 없이 opaque unresolved ref를 반환했지만 당시 fitting stub에는 revision/digest가 남아 있었다. 4차 수정은 이 승인 정보를 제거하고 실제 fitting stub으로 재검증했다. 별도 `/api/required-context`의 protected action에서는 UNKNOWN **409/RULE_APPLICABILITY_UNKNOWN**, known TRUE **200/321 context bytes/required=true**, FALSE **200/0 context bytes/required=false**를 관측했다. synthetic 규칙을 즉시 철회하고 source를 purge했다. 일반 MCP context의 paths hint만으로 protected action을 실행한 것으로 해석하지 않는다.

### 3차 수정 이후 재실행

- Main service를 멈춘 뒤 owner 경로로 `0004_operation_successors`를 명시 적용했다. actual PG180006/vector0.8.7을 관측하고 현재 코드로 local service를 다시 실행했다. `healthz`200과 실제 `doctor`가 기존 deployment/realm/independent journal을 확인했다.
- 실제 CLI `credential revoke --preview`는 required 영향 목록을 본문 없이 반환했다. ack 없는 폐기는 `REQUIRED_RULE_REVOCATION_ACK_REQUIRED`이며 token은 살아 있었다. `--ack-required-rules` 폐기 후 같은 immutable proposal/frozen local target의 재승인은 새 ID, revision1→3, 동일 body digest였다. 사용한 임시 credential은 폐기했고 synthetic rule source는 철회/purge했다.
- 실제 local generation/embedding으로 LynxR3의 11일 source A와 17일 source B를 추출했다. consolidation route를 명시 중지하여 B의 related A+B manifest를 `blocked/MODEL_ROUTE_BLOCKED`로 관측했다. A를 철회하자 같은 B owner의 manifest가 B만 남고 generation이 전진/attempts0이었다. route를 재승인한 뒤 **같은 원래 B operation**이 `semantic_ready`; causal HTTP read200/2,332 context bytes는 17일과 미승인 qualification을 반환하고 11일을 반환하지 않았다. 두 synthetic source는 이후 철회/purge했다.
- 실제 authenticated API에서 producer token의 context/inspect는 각각403/SCOPE_DENIED, 원문 없음이었다. real-PG 회귀는 같은 producer의 capture202와 read403을 함께 검증한다.
- 실제 UNKNOWN required8개/max_bytes256 조회는 HTTP200, `unresolved_required_rule_count=8`, fitting opaque refs0, context bytes0였다. 미결을 empty success로 숨기거나 본문을 넣지 않았다. synthetic 규칙/source는 철회/purge했다. 처음 smoke caller가 private internal 필드명을 public API명으로 잘못 사용한 실패는 caller를 수정했으며 제품 응답을 바꾸지 않았다.
- 실제 installed `host-hook --envelope`로 native prompt generation을 먼저 관측했다. required rule 없는 지원 Write의 context bytes0/state ok; opt-in prompt에 offered한 required revision은 unrelated credential epoch 변경 뒤에도 `HOST_CONTEXT_STALE`이 아닌 **HOST_PROVIDER_INPUT_UNOBSERVABLE**이었다. provider 소비를 성공으로 주장하지 않는다. 자체 MCP call은 delegated/추가 context0이었다. 준비 없는 action의 `HOST_GENERATION_UNOBSERVED`는 올바른 lifecycle gap이며 억제하지 않았다. probe 후 Claude prompt recall은 다시 기본 disabled로 복구했다.
- 현재 설치와 코드에서 새 Claude Opus5.5 xhigh, OMP6.1Sol xhigh, Codex6.1Sol xhigh 모두 실제 context+두 source inspect를 완료했다. 14일·미승인 qualification·old source body 없음은 유지됐다. Codex는 이전과 같은 explicit selected-tool 승인 invocation이며 permanent trust 승인이 아니다.
- 소유한 별도 실제 DB에서 authenticated format2/0002→현재0004 age/pg_restore/psql 복원 smoke가 성공했다. 실제 회귀의 preparation 실패·archive SQL 실패는 **am_sources/claims/lineage/origin reservations의 전체 rows와 current schema/FK를 그대로 보존**했고 private recovery 후 같은 archive 복원이 성공했다. 성공 smoke와 failure regression을 구분한다. 임시 DB/파일은 제거했으며 main corpus를 교체하지 않았다.

### 4차 수정 이후 재실행

- index 재처리의 원래 blocked/failed outcome·successor 연결·lease fencing·snapshot/source floor와 현재/전체 durable 상태 집계를 실제 PG 회귀로 검증했다. unrelated roster 추가 뒤 기존 frozen scope 재승인과 company shared fresh signature도 검증했다. 중복 stats alias는 제거했다.
- 새 operator `migrate --confirm-deployment`의 real-PG `0001`/`0002`/`0003` prefix upgrade는 기존 source body/floor/journal/current operator를 보존했다. main 실제 CLI는 살아 있는 service에서 `AUTHORITY_BUSY/not_started`로 거절했고 서비스 정상 중지 후 기존0004 replay/PG180006/vector0.8.7/application_verified=true로 완료했다. 일반 service의 묵시 DDL은 없다.
- 실제 Claude2.1.296의 isolated temporary HOME/config에서 native add-json이 동일 mkdir lease 뒤에서 기다리고 intervening counter/history/trust를 보존한 경로를 관측했다. native에는 unlocked writer도 있으므로 모든 same-UID 변경의 atomic CAS를 증명한 것이 아니다. 실제 owned Claude/Codex/OMP entry를 새 key-level intent/token으로 갱신했고 trust·기본 prompt recall disabled는 유지했다. interrupted recovery·unrelated native edits·publication 직전 bytes/lease 변경·owned conflict는 경계 회귀로 검증했다.
- restore marker 발행 전 쓰기 실패 smoke의 before는 UNKNOWN인데 fence가 없었다. 수정 후 `RESTORE_NOT_STARTED/not_started`, fence 없음, executor 시작0, recovery 불필요를 실제 private file 경로에서 관측했다. 발행 후 실패는 실제 fence/private recovery를 유지하는 별도 회귀다.
- 실제 authenticated HTTP 일반 UNKNOWN의 required1/max_bytes512는200/296 context bytes/fitting stub1/unresolved total1이었다. opaque ref/required/applicability/body_omitted_reason만 전달했고 revision/digest/body 및 `stamp.rules`는 없었다. synthetic rule/source는 즉시 철회/purge했다.
- 같은 요청 모델/effort의 실제 native Claude/OMP/Codex 모두 현재 서비스에서 context와 source/operation inspect를 성공했다. cold 동시 admission은 `MODEL_BUSY/not_started`를 실제 노출했고 native caller의 명시 재호출 후 성공했다. 서버의 자동 retry·무제한 parallel inference·외부 fallback은 없다. 그 시점에는 미복구 live failed1/DLQ1·top-k omission partial을 소비했고 이를 현재 clean 상태로 포장하지 않는다.
- 이후 source `source_565c3e94f9dc459689383604e5bf6d8d`의 원래 Korean Polaris query를 바꾸지 않고 같은 durable job `job_1d42f29e71ef4cb884baadc5ccd636bf`를 operator가 명시 retry했다. **같은 operation_e2b83c743a02401b8e84f6110ef9862b가 semantic_ready**가 됐다. 실제 `reflection_4218dad8f0824fa79b40c03d6003345d`는 적용범위·익명 synthetic 예외·명시 UTC 유효기간·외부저장 제한을 원문 두 claim에 인용한 candidate3문장/partial=false였다. approved policy나 일반 entailment 증거는 아니다.
- 이 실제 retry 후 main stats의 live pending/blocked/failed/DLQ/stale counts와 recovery_jobs가0, partial=false였다. historical 집계는 전체 durable row의 현재 상태이며 immutable attempt event log가 아니다. 동일 owner의 실제 완료를 실패 삭제나 새 successor가 원래 outcome을 덮어쓴 것으로 해석하지 않는다.

### 5차 실제 리뷰와 수정 재실행

- 실제 같은 AF run의 12개 model/angle 중 fresh 결과7개, timeout5개였다. Claude generalist/types/architecture는 approve, Codex generalist/types/architecture/IO는 request_changes였다. timeout은 approve가 아니며 별도 내부 subagent 출력으로 실제 AF verdict를 대체하지 않았다.
- 실제 HTTP before에서 같은 active source의 누락·wrong·matching snapshot 모두200/본문 노출이었다. 수정·전체 gates 후 새 R18에서 누락·wrong은409/`SNAPSHOT_INELIGIBLE`/본문 없음, matching `round2-correction-v1`만200/본문이었다. 실제 no-initialize MCP 두 거절도 같은 공개 code/no body를 반환했다. global/unbound 및 matching source의 정상 전달은 경계 회귀에 포함했다.
- 원문 생성 시각을 유지하는 24시간 pending/quarantine TTL을 실제 private SQLite로 관측했다. unknown 전송과 confirmed reject 각각 한 개를 담은 뒤 synthetic clock을 원래 age+24h1s로 이동하자 pending/quarantine/bytes가0, expiry gap2, stale 전송0이었다. explicit resolve/enqueue는 expired를 반환했다. 대량 expiry 뒤 fresh commit receipt를 즉시 잃었던 첫 통합 실패도 수정했다. synthetic-clock smoke는 닫힌 파일 즉시 삭제·clock rollback·forensic erasure 증거가 아니다.
- 실제 owned loopback HTTP에서 mutation receipt를 저장한 뒤502를 반환해 committed를 보존했다. 다른 verified502의 not_started와 응답 없는 disconnect의 unknown도 반환했으며 raw diagnostics/자동 retry는 없었다. truncated/mismatched/oversized/invalid response와 legacy/modern state는 경계 회귀에서 검증했다.
- 새 R18의 actual Claude Opus5.5 xhigh, OMP6.1Sol xhigh, Codex6.1Sol xhigh 세 native 모두 같은 context와 두 source inspect를 완료했다. 14일·미승인 qualification·699 context bytes·기존30일 원문 없음·live pending/blocked/failed/DLQ/stale0을 소비했다. Codex explicit selected-tool approval은 permanent trust가 아니다. 별도 앞선 R17 native probe의 kernel loss를 성공 evidence로 세지 않는다.
- 새 R18의 numeric RPC ID/no initialize `server/discover`는282B/instructions empty/no session header, 네 tool catalog3,922B, context wire1,667B/하나의 TextContent/no structuredContent였다. UTF-8 context699B와 top-k omission partial을 확인했다. 앞선 string RPC ID probe의298/3,933/1,678B와 request-ID wire 차이를 startup corpus 증가로 해석하지 않는다. 이 수치는 전체 host prompt/token 사용량 증거가 아니다.
- 앞선 smoke에서 실제 snapshot-bound source의 snapshot을 누락하고 MCP 본문에 API의 stamp를 기대한 실패는 caller 오류였다. matching snapshot/body approved_rules 계약을 사용한 위 실제 재실행과 구분하며 retrieval 버그나 통과로 바꾸어 적지 않는다.

### 6차 실제 리뷰와 수정 재실행

- 실제 동일 AF run·변경 없는 두 모델/xhigh·12개 필수 angle에서 MAX_WORKERS=3은6 fresh/5 timeout/1 missing으로 exit2였다. Claude generalist/architecture/state/clean과 Codex types는 approve, Codex generalist는 request_changes였다. Claude types/IO 및 Codex architecture/state/clean은600초 timeout, Codex IO는 이번 fresh 결과가 없다. 앞선 verdict를 재활용하거나 이를12개 통과로 세지 않는다. 현재 수정 뒤의 필수 AF 재리뷰·QA·handoff는 미완료다.
- OMP의 실제18.9.2 native runner에 옛 strict adapter를 설치하고 observable custom provider로 실행했다. `HOST_HOSTED_PROVIDER_FOOTPRINT_UNSUPPORTED`가 출력된 뒤 provider가1회 dispatch했다. native exit1은 그 dispatch 뒤의 fixture 중단이므로 blocking 성공이 아니다. 새 strict 설치는 설정/receipt 쓰기·native launch 이전에 거절돼0 launch/0 dispatch였고 exact historical 설치를 안전하게 제거했다. 새 advisory adapter의 같은 실제 probe는1 dispatch였다. 이 fixture의 잘못된 isolated token을 실제 memory 호출 성공 증거로 삼지 않는다.18.9.1 source pin은18.9.2 acceptance와 구별한다.
- 실제 owned PG의 두 별도 schema·독립 journal·actual Worker/Store에서 마지막 attempt4의 admission-renewal race와 unrelated journal barrier를 재현했다. before는 각각 LEASE_STALE/DELETION_BARRIER와 failed/active claims0, after는 extraction publication 후 actual consolidation까지 semantic_ready/job done/attempt4/active claim1이었다. old heartbeat는 LEASE_STALE, unrelated source는 retracted다. 통제한 extraction/vector fixture이며 live-model 의미 품질 시험은 아니다. 모호한 lost renewal response는 exact fence로 여전히 거절된다.
- fresh 실제 recall의 근거에는 원문 kind가 없었지만 matching source inspect는 human이었다. 수정 후 `source_speaker`가 authority source join에서 보존된다. 실제 PG의 human capture/agent-note record→publication→scoped claim inspect/server context regression은 서로 다른 종류를 유지했다. extraction 입력에는 이미 source metadata의 speaker가 있었으므로 그 손실 주장은 기각했고 prompt/route를 변경하지 않았다. label은 human-presence/approval 증명이 아니다.
- owned OMP advisory만 uninstall/reinstall하고 새 R19를 기동했다. 실제 requested Opus5.5 xhigh·OMP6.1Sol xhigh·Codex6.1Sol xhigh 모두 context+두 source inspect를 완료했다. raw public tool evidence에서 corrected14일/미승인·source_speaker human/human·749 context bytes·approved_rules empty·old source retracted/no body·live pending/blocked/failed/DLQ/stale0을 확인했다. 모델의 최종 prose만으로 판단하지 않았다.
- 새 R19의 실제 no-initialize numeric-ID MCP: discovery282B/instructions empty/no session header; 네 tool catalog3,922B; 단일 TextContent/no structuredContent context wire1,741B/UTF-8 context749B. 추가 provenance로 인한 context 증가이며 corpus를 연결마다 주입한 것이 아니다. 전체 host prompt/token 크기와는 다른 측정이다. 실제 HTTP source snapshot 누락/wrong은409/no body, matching은200/body였다.
- 새 wheel을 checkout 밖 임시 directory에 offline/no-deps 설치하고 실제 설치된 CLI로 source inspect를 실행했다. package agents-memory/mcp2.3.0이며 누락/wrong snapshot은exit1/no body, matching은exit0/body였다. temporary install과 isolated PG schemas/journals를 제거했다.
- latest exact deletion head를 요구하는 실제 private journal probe는 더 최신 유효 event 뒤 옛 head를 DELETION_BARRIER로 거절하고 최신 exact head만 받아들였다. later prefix를 받아 stale floors/restore authority를 약화하는 제안은 채택하지 않았다. 큰 Store 책임 범위·전역 clock/scaling·allowlist 유지관리 지적은 위험으로 기록하되 실행한 bug와 무관한 backend/layer 재작성은 하지 않았다.

### 사용자 승인 프로젝트 한정 AF 호환 패치

- 공식 project runtime0.3.15/source `0ffba881a0c3f1c20f41359f205ef4e517ed5482`의 hosted 호출부가 기존 public distribution의 기본600초를 바꿀 설정을 전달하지 않아 필수 리뷰가 시간 초과했다. 사용자 선택에 따라 **이 프로젝트의 private runtime caller만** `AGENT_FLOW_REVIEW_TIMEOUT_S`를 읽어 `run_distribution(timeout_s=...)`에 전달했다. 기본은600초, 유효 범위는 정수1–3600초, private continue wrapper의 실행값은1800초/MAX_WORKERS3이다. frozen skill·실제 두 모델/xhigh·12개 review angle·verdict/QA/handoff gate·global AF0.3.14는 그대로다.
- 첫 실제 malformed-timeout CLI는 승인된 hosted.py 수정에 대해 leader-drift 보호를 먼저 거절했다. 이를 timeout validation proof로 세지 않았다. 이어 공식 `continue --accept-leader-drift`로 표시된 그 한 경로를 재baseline한 실제 CLI는 review phase 진입 후 `AGENT_FLOW_REVIEW_TIMEOUT_S must be an integer from 1 to 3600`/exit2로 거절했다. zero-timeout도 같은 실제 CLI에서 exit2였다. 파라미터 mock/echo나 수동 verdict로 실제 native 재리뷰를 대신하지 않는다.
- 원래 hosted.py SHA256은 `c55b644e6c7a1674776c500bfc870e019dd95e333a05666cf4ece882db7a897d`였다. patch의 위치는 leader `.agent-flow/runtime/python/agent_flow/adapters/hosted.py`의 import/hosted review caller이며, wrapper는 private runtime `af-runtime-continue.py`다. 프로젝트 AF 재설치/업그레이드는 이 local patch를 덮어쓸 수 있으므로 공식 timeout-forwarding 지원과 호환 여부를 다시 확인해야 한다. global source upgrade나 review 약화가 rollback 경로가 아니다. official runtime 복원과 wrapper timeout 환경변수 제거는 patch rollback이며600초 한계도 다시 적용된다.
- 전체 새 native 리뷰·QA·handoff의 완료 여부는 후속 실제 결과로 별도 기록한다. 영상/Skills 추가 조사는 별도의 ignored worker-local research artifact에 두며 이번 compatibility patch나 완료 verdict에 자동 채택하지 않는다.





## MCP/native wire 증거

- modern `2026-07-28`: no initialize의 `server/discover` 실제282 bytes/instructions empty/no session ID, `tools/list` 실제 네 tool/3,922 bytes, startup corpus0. 요청 `_meta`와 protocol/method/name headers를 공식 SDK 요구에 맞춰 전달했다.
- modern business `memory_context`: actual HTTP200/no session ID, 하나의 TextContent/no structuredContent. 동일 schema의 legacy2025-11-25 초기화·notification·tools/list도 실제 성공했다. thin stdio의 modern no-initialize와 legacy initialization 모두 실제 JSON-RPC/exit0/stderr empty를 관측했다.
- no bearer401, cross-binding403. 실제 legacy session credential를 revoke한 뒤 동일 token401, 다른 fresh credential의 기존 session reuse403을 관측했다.
- 최초 영어 정정 소비는 Claude2.1.296/native claude-opus-5-5 xhigh, Codex0.162.1/native gpt-6.1-sol xhigh, OMP18.9.1/native openai-codex/gpt-6.1-sol xhigh에서 실행했다. 이름 변경 후 세 native에서 원본 Vega의 실제 inspect→context 호출과 JSON/YAML 충돌·양쪽 미승인·1,707 context bytes를 확인했다. 이때 OMP binary는 18.9.2였으며 adapter의 소스 계약 pin18.9.1과 구분한다. SDK-client probe만을 native 실행이라고 부르지 않는다.
- Codex print/ephemeral consumer는 선택 MCP 도구 두 개에만 per-tool `approval_mode=approve`와 이 invocation의 explicit server config를 주어 실제 호출했다. default never/auto 및 untrusted project 설정 경로는 실제 blocked였으며 성공을 workspace/hook trust 승인으로 일반화하지 않는다. recall/reflect 복합 도구 자체를 read-only로 선언하지 않는다.
- Claude prompt attribution/final subsequent provider-input, Codex hosted actions, OMP print/ACP capture와 후속 model-input/action footprint는 지원되지 않거나 미관측이다. OMP18.9.2 print에서 `before_agent_start`의 자동 context 메시지는 실제 관측했으나 이를 인간 input capture나 최종 provider-input attestation으로 확대하지 않는다. strict unsupported 첫 행동은 block/capability gap이며 receipt를 소비·준수·enforcement로 주장하지 않는다.
- Host native total input tokens에는 기존 AF/global instructions가 포함된다. 이를 memory 전용 token 비용이라고 하지 않는다. 위 수치는 actual wire/body bytes이며 token 추정·host token 집계를 서로 대체하지 않는다.
- OMP에서 명시 MCP 호출 이전에 다른 subject의 memory가 자동 주입되는 실제 경로를 발견했다. 기본 설치의 자동 prompt recall을 끄고 별도 `--prompt-recall` opt-in으로 분리했다. 새 OMP print 실행에서는 자동 `agents-memory.bounded-context` 메시지0과 명시 inspect/context 성공을 함께 관측했다. 기존 AF/global prompt token은 제거하거나 memory 비용으로 재분류하지 않았다.
- 최신 Claude2.1.296의 native local scope는 Git linked worktree가 아닌 원본 Git project key였다. 실제 공식 `mcp add-json --scope local`의 임시 owned 진단 entry를 확인·제거하고 installer를 수정했다. 현재 `claude mcp get agents-memory`는 Connected이며 explicit `--mcp-config` override 없이 Opus5.5 xhigh의 세 MCP 호출이 실제 성공했다. native config는 private `.claude.json`, project shared `.mcp.json`은 변경하지 않았다.
- Canonical config key는 memory 권한 확장이 아니다. receipt/binding/token은 설치 worktree 그대로이며 다른 CWD의 native relay는 HTTP/token 사용 전 `HOST_SCOPE_UNRESOLVED`로 종료하는 실제 subprocess 회귀가 있다. 수정 후 Claude/OMP/Codex의 실제 세 호출을 다시 수행했다. 다른 동시 worktree의 같은 server 이름은 overwrite가 아니라 ownership conflict이며 explicit generic 연결은 별도 grant 계약을 따른다.

## 요구사항 coverage

| ID | 상태·증거 또는 정확한 경계 |
|---|---|
| U01 | 독립 CLI/MCP service/배포 package 실제 실행·build. AF runtime 의존성 없음. |
| U02 | AF active isolated worktree의 native consumer가 같은 memory core를 호출. AF phase 자체 완료 상태는 아래 workflow 기록으로 판단. |
| U03 | native Claude 실제 inspect/context. 자동 strict 전 경로 pass는 아님. |
| U04 | native Codex 실제 inspect/context. workspace trust는 자동 변경하지 않음. |
| U05 | native OMP 실제 inspect/context. print capture/strict input attestation은 지원하지 않음. |
| U06 | workflow 없는 native CLI 세션 실제 호출. child/resume/fork/compact는 회귀·지원 선언, 모든 native lifecycle을 실측한 것은 아님. |
| U07 | 동일 typed handlers/current auth/idempotency/fencing 회귀+wire. LLM 호출·의미 truth의 무조건 정확도는 제공하지 않음. |
| U08 | empty instructions/startup corpus0/4-tool catalog/empty selected body0/3-item shared optional budget·byte bound. 기본 native prompt recall off; 실제 OMP 재실행에서 무요청 memory 메시지0. |
| U09 | official modern/legacy 실제 HTTP·stdio wire. |
| U10 | Python3.12.13/SDK2.3 실제 service/build. |
| U11 | 실제 local PG/native generation/embedding/rerank/full-loop. cloud 계정 없음. |
| U12 | public/synthetic trial 시작 준비. elapsed1–2주 통과는 pending. |
| U13 | 단일 core/schema/API/rule 설계. cloud ingress/runtime provisioning은 다음 작업. |
| U14 | deployment/realm/binding 분리, sync/fallback 없음. 회사 corpus를 smoke에 넣지 않음. |
| U15 | auth/approval/journal/암호화 backup/restore 회귀·실제 실행. 같은 UID 권한은 강한 보안 경계가 아님. |
| U16 | approved host model processing와 background API/memory 저장 허가를 구분. 팀 구독으로 route를 자동 승인하지 않음. |
| U17 | unconfigured route blocked 회귀, 실제 offline/local pins. 회사 OS/network deny 정책은 실제 회사 환경에서 별도 검증 필요. |
| U18 | candidate→exact digest/target-set approval→active/withdraw 회귀. 모델 confidence가 승인 권한이 아님. |
| U19 | 정확히 local_project/my_projects/shared 세 scopes 회귀. |
| U20 | G0 local-project approval, 팀 배포·PR 강제 없음. |
| U21 | root 규칙 corpus 미설치, on-demand bounded delivery. |
| U22 | frozen AF source 조사·설계 반영; AF core의 옛 memory alias/shim 추가 없음. |
| U23 | 기존 research 보존, CueFinder codegraph 재사용 제외. 이전 source 조사와 제품 runtime proof는 별도. |
| U24 | architecture §8 source/version/license/채택·참고·제외. SIE는 SDK1 참고이며 runtime 채택 아님. |
| U25 | PG owned durable jobs/graph/vector/lexical, SQLite spool only, 실제 local model pins/ops. |
| U26 | implementation 전 native 두 모델 동일 입력 실제2round/양쪽 exit0/overlap548.298s·434.966s. AF 독립 review는 별도 단계. |
| U27 | 두 번째 실제 native round에서 peer 원문/hash를 읽고 반박·수정 완료. |
| U28 | architecture·implementation-plan의 API/module/ops/host/선택·기각 근거. |
| U29 | 최신 pinned AF0.3.15 설치, global tool 보존. |
| U30 | Python/local architecture snapshot, 세 local gates, 두 요청 native model/xhigh candidates. |
| U31 | 실제 AF run/isolated worktree/explore/implementation. native review→QA→handoff는 완료 후 별도 기록. 원격 공개 없음. |

## 불변식 coverage

| ID | 검증 층위·제한 |
|---|---|
| I01 | actual bilingual claims/qualifiers/time/entities/citations; scope/negation/duplicate-invalid 회귀. 모델 entailment는 후보. |
| I02 | actual English full loop, 한국어 actual fresh pipeline. SQLite/echo/vector fake 대체 없음. |
| I03 | real-PG current lease/heartbeat/token/generation/expired-publish/next-job 회귀. |
| I04 | auth/source/route/floor/admission/publish/delivery current-clock 검사 회귀. |
| I05 | actual logical hide/purge 상태와 drain/provider/WAL/archive unknown 분리. |
| I06 | accepted→pending→semantic_ready 실제 관측, causal pending/failed/DLQ contract 회귀. |
| I07 | real-PG concurrent duplicate/lost receipt replay/changed payload conflict 회귀. |
| I08 | actual cross-binding denial/current bearer 및 realm/grant 회귀. |
| I09 | full input dependency edges 및 uncited-source retract closure real-PG 회귀. |
| I10 | actual old archive restore/old-origin replay denial 및 spool/floor 회귀. |
| I11 | actual surviving journal head restore; missing/inconsistent head fail-closed 회귀. |
| I12 | digest/selector/target-set/roster mismatch 승인 거절 real-PG 회귀. |
| I13 | agent approve denial/candidate separation/G1 exact signed statement 회귀. |
| I14 | offered≠model-input≠준수≠first-action enforce. unsupported strict native 경로 block/capgap, actual final input attestation 없음. |
| I15 | per-agent/generation/fork/compact receipt bounds 회귀. 모든 native lifecycle 실측 pass는 아님. |
| I16 | UNKNOWN required selectors/unknown writer footprint 거절 회귀. |
| I17 | actual TextContent single plane/stdio wire, empty context0·optional total budget 회귀. |
| I18 | actual unauthorized/cross-binding/revocation; Host/Origin/body/duplicate-key/queue limits 회귀. |
| I19 | actual artifact/runtime pins와 prompt·schema·validator·semantic source contract를 포함한 route revision. 현재 contract `73a3a0500c3e66083e2e70ce7acab0df30f9049f8e1fe0ec1c1a3f0d51579862`, route `5b1f5ea9adf77de9a4eed19eb10e342846e77024b0d0f8a257891281df75b6da`; vector compatibility는 별도 `5746aa946889325cd26d84aafb3e1ac05ae4fccba400bfc6597431b26a1ac13a`. 실제 torch/runtime 불일치와 실행 중 semantic drift는 blocked. 전체 package 모든 파일 hash라고 주장하지 않음. |
| I20 | actual explicit migration/backup/restore/token rotation; quarantine/drain/retry/DLQ 회귀. |
| I21 | bearer/same-UID human-presence 미보장; G1 externally managed key의 exact signature 계약·회귀. |
| I22 | 이 기록의 native/unit/runtime/unverified/pending 분리. |

## architecture acceptance

| ID | 증거 |
|---|---|
| A01 | real-PG concurrency/idempotency 회귀. |
| A02 | real-PG lease heartbeat/publish/generation 회귀. |
| A03 | real-PG source/credential/route 변경 후 stale admission/publish 거절 회귀. |
| A04 | real-PG delivery-current-clock/retract 경계 회귀; actual purge state 관측. |
| A05 | 원본 bilingual source의 actual extraction/rerank 및 원문 scope/exception/explicit-time spans, 실제 cited UTC 기간 reflection. structured qualifier 분류·일반 entailment 정확도는 후보이며 보장 아님. |
| A06 | 원본 Vega 실제 consolidate→`contradicts`→bounded 두 후보→두 source-backed claim을 인용하는 unresolved reflection 성공. relation current/full-input lineage 및 omitted-endpoint 회귀 별도. |
| A07 | actual trusted correction, 새 Claude/Codex/OMP next read. |
| A08 | actual old reflection immediate hide, full input source retract closure 회귀. |
| A09 | actual stale main backup restore+fresh-auth old-origin replay denial; unknown head fail-closed 회귀. |
| A10 | scopes/frozen targets/cancel/agent denial/G1 signatures/realm 회귀. |
| A11 | 세 native 실제 MCP calls. strict unsupported/missing lifecycle attestation은 gap이며 pass로 바꾸지 않음. |
| A12 | 최신 actual modern282B discovery/3922B catalog/single body; 정정 후 actual context699B. historical semantic761/819/876B와 구분하며 token attribution 분리. |
| A13 | actual401/403/live revoke/session credential boundary + security regression. |
| A14 | actual local route/model full loop + missing/unapproved route blocked 회귀. |
| A15 | actual encrypted stale restore/token revoke/physical purge; bounded spool/DLQ/drain 회귀. |
| A16 | AF native multi-review/fix/QA/handoff의 실제 runner 완료 후 별도 기록. |

## 관측된 운영 한계

- reads도 전역 clock lock·journal 검증·artifact pin 검사를 사용하는 보수적 구현이다. journal/corpus 증가에 대한 p50/p95나 다수 동시 workflow의 성공률·처리량을 아직 실측하지 않았다.
- local interactive model admission은 bounded이며 실제 cold 동시 recall에서 `MODEL_BUSY`를 관측했다. 무한 대기·무제한 parallel inference·외부 fallback으로 바꾸지 않는다.
- required UNKNOWN은 일반 context에서 body-free opaque ref/미결 개수만 전달하고 protected action에서는 거절한다. generic caller host/purpose/path hints는 실행 authority가 아니며, native final provider input이 보이지 않는 경로는 strict enforcement 성공으로 표시하지 않는다.
- 기존 age envelope magic·migration advisory lock·restore executor/interlock 이름은 persisted 호환·동시 실행 안전을 위한 고정 protocol identity다. 제품 이름 변경으로 이를 바꾸거나 삭제 저널·backup을 무효화하지 않는다.


## 다음 사용자 trial

private personal/synthetic deployment부터 사용한다. actor/token/프로젝트 grant를 명시하고 회사 customer corpus와 섞지 않는다. root rulebook 대신 필요한 규칙만 승인·선택한다. `stats/doctor/inspect`로 pending/blocked/DLQ/gap를 확인한다. 실제 trial 시작 시각과 매일 correction reuse·qualification omission·false claim·false rule promotion·restore/replay·호스트 gap·wire/context bytes·latency/운영 부담을 body-free metadata로 기록한다.

미승인 egress, realm 누출, 철회 부활, 무승인 rule activation, strict gap를 정상 allow로 보고, root corpus 설치 또는 중복 효과가 나오면 즉시 중단한다. 1–2주 실제 사용 이후에만 개인 cloud(TLS/OAuth audience, deploy identity, durable journal witness, network/backup)로 전환한다. 회사 자료는 이전하지 않는다.
