# 로컬 우선 설계 계약 — native 모델 토론의 반박 대상

상태: 구현 전 설계안 [INFERENCE]. 저장소에 현재 product runtime은 없다. 이 문서는 기존 제안의 요구를 줄이지 않고 호출·정확성·context·실사용 완료 기준을 구체화한다. 새 source 조사와 두 native 모델의 상호 반박으로 최종 설계를 확정한다. 코드 구현·회사 정책 승인·검색 품질 실측과 구분한다.

## 1. 범위와 보장

독립 설치 service/worker와 단일 PostgreSQL 권위, 얇은 MCP edge, Claude Code/Codex/omp 별 opt-in 어댑터. Agent Flow는 일반 consumer, framework core·installer·isolated reviewer에 memory 강제 없음. 로컬 full loop 완성 및 1~2주 실사용 뒤 같은 release를 개인 persistent VM으로 전환한다. cloud provisioning은 지금 하지 않으며 회사 corpus를 개인 cloud로 이동하지 않는다.

API/DB에서 보장할 것: 승인 범위·identity·revision·출처 검증, 같은 idempotency request의 같은 효과와 replay 의미, stale publish 차단, 명시적 operation 상태, 제한된 결과 크기, source/derived 철회·복원 불변식. LLM의 사실 추출·순위·자발적 호출·준수를 100% 보장한다고 하지 않는다. 모든 workflow와 prompt가 같은 API를 사용할 수 있어야 하지만 MCP 등록만으로 매 turn 호출이 생기지 않는다. 자동화는 실제 지원 hook/wrapper 계약과 readiness를 검증한 surface에서 제공한다.

전체 loop는 capture→durable ingest→signal/claim extraction→scoped recall→grounded reflect→correction/retraction→next task. 승인 route가 없으면 extraction/reflect blocked를 노출하고 그 환경을 full 지원으로 표시하지 않는다. tool-only/manual/rules-only로 full 기능을 대체하지 않는다.

## 2. 호출 모델

- Agent-plane fixed small tool set candidate: `memory_context`(recall/explicit reflect), `memory_inspect`(선택 item의 근거·상태), `memory_record`(명시 note/candidate), `memory_feedback`(정정/거절/철회 요청). capture/approval/publish/admin는 별도 인증 API/CLI/UI. 최종 이름·schema는 모델 토론으로 한 세트 확정.
- native hooks와 omp extension, workflow wrapper, 일반 MCP 호출이 모두 같은 domain command handler를 사용한다. host별 ingest/search/승인 정책을 별도로 구현하지 않는다.
- producer가 보내는 event와 모델이 보내는 note를 구분한다. 모델 tool은 `human/approved` 권위를 자가 선언할 수 없다. 사업 session/root-run은 domain lineage이며 MCP wire session을 복원하는 우회 수단이 아니다.
- 회사/personal/customer 경계의 deployment identity와 project binding을 operator가 등록한다. repo remote·CWD·bank name·_meta.clientInfo는 권한 근거가 아니다. client credential은 principal/allowed deployment/project/purpose에 결합한다.
- server가 project를 임의로 추측해 default/global bank를 고르지 않는다. 미등록/모호한 repo·worktree·prompt project는 `BINDING_REQUIRED`다. 새 repo/project alias는 operator action. prompt에 path/phase가 없으면 unknown 상태를 보존하고 task-neutral approved 규칙과 일반 evidence만 제공하며 보호 대상 행동 전에 target resolution을 요구한다.
- workspace/worktree/fork/branch/file revision은 provenance/적용 조건, scope는 권한·공유 범위다. 동일 project의 다른 branch facts를 현재 code truth로 보여주지 않는다. 과거 facts는 historical 태그·validity로 분리한다.

## 3. 일관성·동시성 불변식

1. `schema_version`, domain command type, binding reference, client operation identity, causal minimum watermark, correlation ID를 명시한다. auth/role은 verified credential로 결정한다. model/client payload의 actor/scope 플래그는 권한을 늘리지 못한다.
2. protocol JSON-RPC request ID, MCP connection/session, operation ID, source event ID, root-run/episode identity, idempotency key는 서로 다른 개념이다.
3. 같은 `(principal, binding, command, idempotency_key)` + 같은 payload digest는 동일 effect/operation receipt. 같은 key + 다른 digest는 `IDEMPOTENCY_CONFLICT`. retry/reconnect/cancel 후에는 먼저 operation 상태를 조회하거나 같은 key를 replay한다. 삭제·승인 같은 변이는 새 key로 눈치껏 반복하지 않는다.
4. 최초 durable ingest와 outbox 등록은 한 PG transaction. producer spool flush와 server accepted는 다르다. `accepted≠queryable`, `unavailable≠empty`, `partial≠complete` 상태를 API/UI로 유지한다. exact-once delivery 대신 at-least-once delivery + effect dedup.
5. 단일 job lifecycle owner. engine 자체 operation/queue와 제품 ledger가 각각 final state를 선언하지 않도록 mapping/commit 책임을 명시한다. lease expiry·fencing token·expected generation/version으로 늦은 worker commit을 거절한다.
6. caller logical root-run과 child/handback/export dedup. actor role, typed human source, quotations, code snapshot, span, truncation/coverage를 보존한다. 동일 run 5개 event는 recurring investigation 5회가 아니다.
7. `memory_context`의 source selection/rule activation/permission은 명시 watermark snapshot. 모델 호출을 DB transaction 안에서 기다리지 않는다. reflect 완료 및 전달 전에 current source/permission/deletion eligibility를 다시 확인하며 stale이면 bounded re-evaluation 또는 `CONTEXT_STALE`다.
8. 읽기 linearization 지점과 취소/철회 순서를 계약한다. 철회 ack의 watermark 이후 요청은 최소 그 watermark를 요구한다. 이전에 시작/전달된 context가 자동 회수된다는 보장은 하지 않는다. 보호 행동은 latest policy check와 context generation이 필요하다.
9. timestamps는 기록/표시에 쓰고 최신 승인·lease·복원 권위를 client wall clock으로 결정하지 않는다. UUID/source ID collision·순서 역전·offset 재사용·파일 교체를 검출한다.
10. role/purpose 변경, scope 확대, body/selectors/applicability 수정은 exact revision에 결합. cancel/미응답 candidate only. local-only에 Git/team approval 강제 없음. 프로젝트 공유/팀 공통은 권한 있는 publication만 활성화.

## 4. root-free와 context 비용

- root CLAUDE/AGENTS에 새 본문·목록·bridge 없음. 기존 지침 삭제 아님. 다른 eager file/passive skill에 전체를 옮기지 않는다.
- session connect/start에서는 memory/rule 본문 0. fixed small schema만 노출. startup 모든 project·rule name list를 넣지 않는다. schema·native wrapper·server instructions도 실제 비용으로 측정한다.
- 작업이 정해진 때 deterministic approved rule routing; normal prompt의 phase/path unknown을 model 추측으로 허가하지 않는다. path가 새로 생기면 first-action barrier로 required minimal original을 전달하고 재계획하게 한다. semantic top-k는 optional memory용.
- per-request response budget을 bytes와 host/tokenizer의 actual rendered tokens로 관리. mandatory 집합을 예산 때문에 자르지 않는다. optional 내용부터 제외하고 부족하면 `REQUIRED_CONTEXT_OVER_BUDGET` 및 split/stop. 장문을 byte 중간에서 잘라 부정/예외를 없애지 않는다.
- private adapter API 응답의 control/receipt와 model_text를 분리한다. MCP consumer가 structured content를 전부 볼 수 있으므로 MCP 응답은 최소 stamp/coverage/citation 등으로 제한한다. detail은 inspect/status로 필요할 때만.
- delivery cache key는 principal/binding/purpose/context-generation/rule-ID/revision/policy epoch. host module-global dedup을 child sessions에 공유하지 않는다. compact/resume/newthread/fork 시 재평가. authoritative receipt와 client known-items는 권한을 대체하지 않는다.
- trace→memory→same prompt→trace recursive capture를 막는다. injected content/tool echoes는 source=user correction으로 승격하지 않고 source link/derived lineage를 유지한다.
- 최초 규칙은 pre-read/plan 단계에서 전달. PreToolUse additionalContext+allow만으로 이미 생성된 Write를 통과시키지 않는다. deny-once receipt도 미래 준수 보장이 아니며 CI/ACL/sandbox와 구분한다.

## 5. service·engine·model route

같은 PG/persistent topology를 회사 local과 이후 개인 VM에 쓴다. session child가 PG/worker owner가 아니다. thin stdio는 service client로만 필요 host에 제공한다. loopback + per-install auth + endpoint identity/Host-Origin 검사. shared company approval/DB privilege는 agent credential과 분리. HOME 분리만으로 같은 UID 격리를 보장하지 않는다.

Hindsight는 재사용 우선 후보지만 internal read/reflect/refresh/write/import가 canonical generation/retraction을 확인하는 bounded integration이 실제 source상 가능한지 평가한다. wrapper output-filter로 내부 합성 오염을 해결하지 않는다. 이를 유지할 수 없으면 단일 narrowPG core로 교체한다. 두 generic engine 병행·새 graph·Neo4j·Redis/object-store 기본 추가는 하지 않는다.

회사 approved Claude/Codex host는 유지. 새 worker/headless observer/API/embedding/reflect route는 별도 승인. allowed routes manifest·clean env·offline imported weights·no personal fallback·no implicit download/telemetry. native app-server/CLI 제공 기능과 회사 사용/구독 권한은 별개. no-training/no-storage/no-egress를 혼동하지 않는다. 클라우드에는 같은 제품 profile+TLS/IdP/approved routes만 추가; 지금 cloud 환경 부족은 local 검증을 막지 않는다.

## 6. 운영·설치·삭제

설치·project binding·host opt-in·service start는 별도 단계이며 global host config/rules 자동 overwrite 없음. owned config entry만 관리, uninstall은 data 보존이 기본이고 explicit purge는 별도. supervisor 하나, migration lock, readiness 구분, status/doctor에 capture watermarks·queue/blocked/error·protocol/capability/version 표시. service unavailable시 optional recall은 unavailable로, required protected action은 fail closed.

local spool bounded/권한/retention/backpressure·디스크 부족·무효 credential·permanent malformed job·retry exhaustion·crash recovery를 계획한다. queue는 durable PG, 다른 generic queue 기본추가 없음. 데이터·raw/derived trace 최소화; 본문은 삭제 가능 storage, immutable audit/tombstone에 삭제 본문 복제 금지.

forget/retract/physical purge/backup retention 완료를 분리. source·derived·index·cache·spool·job·exports·rule projections와 다시 import/replay되는 source identity를 통제. 과거 backup만으로 latest deletion head를 잃지 않는다. 복원 후 reconciliation 전 service 공개 금지. image rollback≠schema rollback. signed/pinned artifacts+SBOM/model/license/offline-model tests와 dataset versions, model prompt/parser/index generation 변경 시 reprocess 책임.

## 7. 로컬 구현·1~2주 실사용·cloud 전환

실행 순서의 완료 조건은 scope가 아니라 의존 관계다: contract/authority 결정→domain/PG durable operations/eligibility→통제된 engine/approved route→thin MCP와 three native host adapters→capture/rule/reflect/feedback/forget/restore 전체 smoke→local trial→cloud same release.

local completion은 Claude/Codex/omp 각각 normal prompt+workflow, new/resumed/compacted/forked sessions, same project cross-host recall, simultaneous writers/readers, error/cancel/replay, first-new-file rules, no-root-change, no-other-project/customer ingress, no-external unapproved inference, derived retraction/restore 전체 결과를 의미한다. source/docs만으로 runtime pass라고 쓰지 않는다. Agent Flow 없는 실행이 먼저 통과해야 한다.

trial은 개인 synthetic/public projects부터 시작, 회사자료는 별도 승인 후. 1~2주라는 날짜만 채우면 pass가 아니다. memory-on vs no-memory/동일조건 baseline을 비슷한 coding/review/일반질문 task로 관측: startup/turn/recall rendered tokens·extra roundtrips·p50/p95 local latency·candidate accept/reject/false promotion·중복/누락/blocked 작업·영구 실패·실제 후속 수정 품질·route/cost·운영시간. 수치 target은 측정 전 proposal로 표시하며 제품 성능으로 보고하지 않는다. 권한 혼선·반출·철회 부활·필수규칙 우회·silent capture gap이면 trial 중단/rollback. baseline root/user instructions와 private projects는 침해하지 않는다.

cloud 진입 조건은 local full acceptance와 trial guardrails 통과, same artifact/schema/policy semantics, persistent VM/TLS/auth/backup/restore 및 개인 route 결정이다. 지금 cloud account/infra를 만들지 않는다. 차후 데이터 이동은 개인 corpus의 명시 export/import 및 최신 deletion head·compatibility 검증; 회사 corpus는 이동하지 않는다.

## 8. 설계 산출물과 추가 검토 범위

최종 architecture와 domain/schema/command/result/error/operation-state 계약, scope/rule precedence, host/version/capability support matrix, local module/dependency structure, implementation milestones/acceptance matrix, token-budget instrumentation, install/update/runbook, local trial log와 cloud handoff 기준을 하나의 문서 세트로 연결한다. native model별 peer 반박·채택/기각·남은 disagreement와 실제 process/model/effort/input/output hashes를 보존한다.

추가 위험: same-UID credential/approval 접근, MCP2-only vs legacy host handshake, branch/worktree aliases, reused root-run IDs, schema/index/model drift, conflict/exception precedence, Unicode/한국어 부정·code identifier, recursion/poisoning, rate/resource budgets, observer effects, credential revocation/offline lease, disk/PG/worker failure, updates/rollback/restore source resurrection, supply-chain/licensing, provider retention and context already delivered. 위험마다 실제 domain/adapter/operations 책임과 acceptance를 매핑하고 무관한 multi-cloud/SaaS/HA scope는 추가하지 않는다.
