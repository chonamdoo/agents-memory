# 로컬 구현 계약

`architecture.ko.md`와 `requirements.ko.md`가 전체 완료 기준이다. 이 문서는 구현된 core의 공개 계약과 병렬 writer 경계를 기록한다. 현재 local pipeline은 실제 PG·모델·세 native host로 실행했으며 AF 재리뷰·QA·handoff는 별도 runner 완료 기준이다. API 목록 자체가 실행 증거는 아니며 관측은 `verification.ko.md`를 따른다.

## 소유권·검증

- integration owner: `domain.py`, `config.py`, application/jobs/context/rules, MCP/producer edge, CLI/hosts/ops, project metadata·문서·실행 증거.
- storage writer: `store.py`, `journal.py`, `migrations/`, `tests/test_store*.py`, `tests/test_journal*.py`만 수정한다.
- semantic writer: `models.py`, `semantic.py`, `lexical.py`, `tests/test_semantic*.py`, `tests/test_lexical*.py`만 수정한다.
- shared domain/config 변경은 integration owner에게 요청한다. 각 writer는 전체 빌드·lint·tests·formatter를 실행하지 않는다. integration owner가 모든 writer 완료 후 선언된 gates와 실제 PG·모델·host scenario를 실행한다.
- 새로운 실제 consumer 오류·race·경계만 permanent regression으로 남긴다. wiring/source-text/default/forwarding 검사는 쓰지 않는다.
- 원격 push·PR·merge·기존 research 변경은 하지 않는다.

## Store 공개 API

`Store(settings: Settings, journal: DeletionJournal)`가 asyncpg pool을 소유한다. 외부 handler가 SQL/transaction을 복제하지 않는다. `open()`/`close()`는 연결 lifecycle만 수행하며 migration을 실행하지 않는다. 기존 배포의 operator CLI `migrate --confirm-deployment`는 `ops.migrate_authority(settings, operator_token_file, confirm_deployment)`를 사용한다. current operator·명시 동일 local migrator target·exclusive authority lock을 DDL 전에 검사하고 live service/restore fence를 거절한다. 아래 `actor`는 반드시 current credential을 검증한 `Principal`이다. 모든 API는 재검사·realm/binding scope를 내부에서 집행한다.

- `bootstrap(operator_token: str, owner_id: str) -> Principal`: 빈 배포만 초기화한다. 기존 credential이 있으면 거절한다. token 자체는 DB에 저장하지 않는다.
- Init lifecycle은 private exact intent→bootstrap→완료 receipt다. bootstrap 이후 receipt 실패는 COMMITTED/recovery-required로 표시하고 `--resume`은 원래 operator credential/owner를 인증한다. completed replay는 mutable 설정을 되감지 않는다.
- `authenticate(token: str, roles: tuple[Role, ...] | None = None) -> Principal`: 활성 token hash·generation·role·realm·grant를 조회한다.
- `register_binding(actor, label: str, locator: str | None, key: str) -> Binding`: operator만, opaque ID; 모든 actor grant 갱신은 명시적이다. bootstrap operator는 관리용 등록 grant를 받을 수 있다.
- `list_bindings(actor) -> list[Binding]`: actor의 실제 grant/owner 범위만.
- `target_set_revision(actor) -> int`: 현재 realm roster revision. approval 시 선택 snapshot을 검사하고 활성 target set은 frozen이다.
- `issue_token(actor, role: Role, bindings: tuple[str, ...], token: str) -> Principal`: operator만; 강한 회사 approver는 별도 관리 key 구성 없으면 거절한다.
- `credential_revocation_impact(actor, credential_id: str) -> dict`: operator의 body-free preview, affected/required rule IDs와 현재 epoch; mutation 없음.
- `revoke_token(actor, credential_id: str, *, acknowledge_required: bool = False) -> dict`: operator만; 활성 required 영향은 명시 ack 없으면 무효과 거절. auth·admission·publication에서 즉시 재검사하고 영향 목록을 반환한다.
- `capture(actor, command: CaptureCommand) -> Operation`: producer/operator만. 한 tx에 source+receipt+extract job. origin 충돌 body를 임의 덮어쓰지 않는다. memory/injected/echo capture는 명시적으로 거절/무시 상태를 반환한다.
- `record(actor, command: RecordCommand) -> Operation`: agent/operator의 agent_note 또는 rule candidate. human 권한으로 승격하지 않는다. rule candidate는 `artifact_id`에 proposal handle을 제공한다.
- `feedback(actor, command: FeedbackCommand) -> Operation`: candidate만 저장. MCP irreversible retract/approval 없음.
- `operation(actor, binding_id: str, operation_id: str) -> Operation`: 현재 상태·공개 error code·epoch, body 복제 없음. source reprocess/index recover가 새 owner를 만들면 원래 blocked/failed 결과를 유지하고 `successor_operation_id`로 연결한다. 명시 retry는 같은 owner의 새 attempt다. related-only floor는 살아 있는 원래 capture owner의 consolidation manifest만 재계획한다.
- `source(actor, binding_id: str, source_id: str) -> Source`: active·eligible만 원문을 읽는다. 철회 자료는 거절한다.
- `claim(actor, binding_id: str, claim_id: str, snapshot: str | None = None) -> Claim`: dependency·snapshot eligibility 재검사. evidence의 `source_speaker`는 현재 canonical source metadata에서 읽어 recall/consolidation/reflect 입력에 보존하며 agent note를 human으로 기본 변환하지 않는다. 선언된 출처 label은 인간 존재/승인 증명이 아니다.
- `inspect(actor, binding_id: str, ref: str, snapshot: str | None = None) -> dict`: scoped 현재 operation/source/claim/rule/reflection metadata·bounded evidence. active snapshot-bound source는 본문 반환 전에 같은 snapshot을 요구하며 global source는 적격이다. 철회 본문 없음.
- `stats(actor, binding_id: str, snapshot: str | None = None) -> dict`: 요청 snapshot eligibility의 active counts와 live job ownership의 pending/blocked/failed/DLQ·current_operations·복구 목록·partial 여부. historical_operations/historical_jobs는 전체 durable row의 현재 상태이며 immutable attempt log가 아니다. 중복 operations/jobs alias는 없다. retired 실패를 현재 partial로 세거나 아직 살아 있는 실패를 숨기지 않으며 전체를 top-k count로 위장하지 않는다.
- `search(actor, binding_id: str, query_vector: list[float], lexical_tokens: list[str], snapshot: str | None, limit: int = 20) -> list[tuple[Claim, tuple[str, ...]]]`: eligible exact-vector/GIN lexical/entity 후보 RRF 합치기. vector compatibility는 vector arm에만 적용하며 lexical/entity 후보를 가리지 않는다. source/snapshot/time/credential scope를 먼저 적용한다. `index-status`/`index-recover`는 vector eligibility와 embedding-only 복구를 제공한다.
- `relations(actor, binding_id: str, claim_ids: tuple[str, ...]) -> list[RelationDraft]`: 유효 양쪽/full-input lineage만. 같은 전체 manifest의 replay는 중복을 만들지 않고 독립 derivation은 별도 유지한다. recall은 eligible logical edge를 접은 뒤 완전성 budget을 검사한다.
- `rules(actor, binding_id: str) -> list[ActiveRule]`: 현재 exact approval·frozen target set·전체 source dependency가 유효한 것만.
- `propose_rule(actor, command: RuleProposal) -> dict`: immutable proposal id/digest/current target-set revision. agent는 강한/required/공유 권한을 만들지 못한다.
- `approve_rule(actor, command: RuleApproval) -> ActiveRule`: exact expected digest+target roster revision+exact 3 scope; company shared는 fresh G1 signature 없으면 unavailable. 폐기/복원으로 inactive가 된 eligible immutable proposal은 fresh key와 기존 frozen scope/targets로 새 ID/높은 revision을 승인한다. 무관한 roster 증가가 같은 frozen scope 재승인을 막지 않으며 target widening/new project 자동 포함은 거절한다. body/selector 변경은 새 proposal/approval이며 철회 source·active conflict는 거절한다.
- `withdraw_rule(actor, binding_id: str, rule_id: str, key: str) -> dict`: operator/실제 approver만; epoch 변경·이전 revision invalidate.
- `retract(actor, binding_id: str, ref: str, key: str) -> dict`: operator만. journal intent fsync→짧은 clock tx→source tombstone/모든 actual-input descendant hide. logical ack와 drain/physical/provider unknown을 별도 반환.
- `correct(actor, binding_id: str, target_ref: str, command: CaptureCommand) -> Operation`: producer/operator의 명시 correction. origin reservation→원문 journal/floor 및 기존 dependency hide→새 source/receipt/job commit 순서다. 실패 지점에 따른 partial/committed recovery와 exact retry를 제공하며 agent feedback과 구분한다.
- `configure_route(actor, revision: str, purposes: tuple[str, ...], enabled: bool) -> None`: operator만; route approval epoch/revision 변경. Gateway는 config와 이 ledger 모두 검사한다.
- `claim_job() -> JobLease | None`, `heartbeat(lease: JobLease) -> JobLease`, `fail_job(lease: JobLease, code: str, blocked: bool = False) -> None`: claim/heartbeat/retry/DLQ는 token+generation+deadline fence. payload는 IDs뿐, body 없음.
- `admit_job(lease: JobLease, route_revision: str, purpose: str) -> Admission`: current source/grant/route/snapshot/full manifest를 commit. extract는 source, consolidate/reflect는 실제 모든 claims와 그 input sources 및 query source를 포함한다.
- `admit_read(actor, binding_id: str, claim_ids: tuple[str, ...], route_revision: str, purpose: str, snapshot: str | None = None) -> Admission`: read-time model의 full eligibility manifest. query embedding의 빈 corpus manifest도 credential/route 검사한다.
- `admitted_sources(admission) -> list[Source]`, `admitted_claims(admission) -> list[Claim]`: manifest만 가져오며 currentness를 재검사한다.
- `recheck(admission) -> int`: 현재 authority stamp 반환. unrelated capture의 clock 증가만으로 모든 job을 실패시키지 않는다. source revision·credential generation·grant·route·deletion barrier·deadline을 재검사한다.
- `publish_extraction(lease, admission, extraction: Extraction, vectors: list[list[float]], lexical_rows: list[list[str]]) -> Operation`: exact original UTF-8 span 검증, vectors=claims 길이/dimension/finite 검사. claims+index+consolidation intent 또는 terminal semantic_ready를 하나의 tx로 publish.
- `publish_consolidation(lease, admission, result: Consolidation) -> Operation`: manifest 안의 양쪽 ID만 허용, 서로 다른 condition/time/snapshot을 duplicates로 지우지 않는다. semantic relation은 authority/자동 삭제 아님.
- `submit_reflection(actor, command: ContextCommand, claim_ids: tuple[str, ...]) -> Operation`: query는 단일 source에, job payload는 reference만. actual manifest 외 claims 입력 금지.
- `publish_reflection(lease, admission, result: ReflectionDraft) -> Operation`: validated manifest citation+whole-input lineage artifact. candidate이지 활성 규칙 아님.
- Historical reflection receipt는 본문을 복제하지 않으며 query도 owned source/floor에 연결한다. withdrawal는 실제 directional descendant와 equivalence group만 숨기고 upstream/독립 derivation을 제거하지 않는다.
- `retry_job(actor, job_id: str) -> None`: operator만 DLQ/blocked 재시도, 새 generation.
- `reconcile_journal(expected_head: str | None = None) -> dict`: 복원 후 모든 historical floor 재적용, active reads/publications 전 barrier. expected 최신 head 검증 불가면 fail closed. journal과 DB 둘 다 rollback된 경우 로컬 chain만으로 최신성 증명 불가.
- `purge(actor, binding_id: str, ref: str, key: str) -> dict`: tombstoned source body/vector/derived body 실제 삭제. logical/drain/backup retention과 구분.

Storage writer가 필요한 추가 helper는 내부 함수로 만든다. 공개 API 추가가 필요하면 integration owner에게 signature와 이유를 알린다. DB mutation 감사/receipt/job/admission은 원문·prompt·provider trace를 복제하지 않는다. migration id/version과 실제 PG/vector version 확인은 operator 출력에 노출한다.

## Journal 계약

`DeletionJournal(directory: Path, deployment_id: str)`는 DB restore 밖 body-free journal을 소유한다. 파일은 0600, directory 0700, key·entry·head fsync/atomic rename, process lock, HMAC source/origin identifiers와 chain 검증. `initialize()`는 명시 새 배포에서만, `.verify(expected_head: str | None = None) -> dict`, `.append(binding_id: str, source_ids: tuple[str, ...], origin_keys: tuple[str, ...]) -> dict`, `.entries() -> list[dict]`, `.source_token(source_id: str) -> str`, `.origin_token(binding_id: str, origin_key: str) -> str`를 제공한다. `verify`/`entries`는 존재하지 않는 journal을 자동 initialize하지 않는다. Store가 floor apply·pending intent reconciliation을 소유한다. directory와 DB restore unit을 같이 덮어쓰지 않는다.

## 의미 runtime 계약

`LocalSemanticRuntime(config: ModelConfig)`는 `domain.SemanticRuntime`의 실제 구현이다. `.revision`은 verified manifest의 canonical digest다. 생성은 lazy이지만 `.validate_artifacts()`는 missing/unverified artifact를 `MODEL_ROUTE_BLOCKED`로 거절한다. 외부 network·HF auto-download·proxy/telemetry·raw prompt/result logging·fake vectors·source-echo/no-op extraction을 금지한다. CPU BGE checkpoint는 실제 pinned source/weight hash/license/tokenizer/pooling/dim/normalization manifest와 일치해야 한다. generation은 승인된 loopback llama.cpp endpoint/key를 사용한다.

- `extract(Source) -> Extraction`: JSON-schema local generation; negation/modality/condition/exception/time/exact code identifier/quote/source ID를 보존. conditions/exceptions는 인용 원문의 동일 언어 구절이어야 하며 번역·원문 없는 조건을 deterministic guard에서 거절한다. data-as-instruction 방지 prompt. 원문 span은 Store가 검증하고 factual entailment·조건 누락은 별도 실제 fixture로 측정한다.
- `embed(Sequence[str]) -> list[list[float]]`: BGE-M3 1024 normalized dense, finite actual model output. to_thread/worker로 event loop heartbeat를 막지 않는다.
- `consolidate(Sequence[Claim]) -> Consolidation`: bounded true manifest; 조건/시간/부정/authority/snapshot 다르면 함부로 duplicate/supersede 하지 않는다. 0/1 claim의 pair 집합은 실제로 empty이고 model 호출이 필요 없다.
- `rerank(query, Sequence[Claim]) -> list[RankedClaim]`: 실제 BGE cross-encoder; 최종 작은 candidate도 점수 계산. invalid IDs/NaN 거절.
- `reflect(query, Sequence[Claim]) -> ReflectionDraft`: 문장별 manifest citations, grounded candidate. 문장에 새 숫자/코드 identifier가 출처에서 확인되지 않으면 거절; 모든 실제 입력이 dependency.
- `close()`: observed in-flight 작업과 close/drain 상태를 구분. thread timeout을 inference termination이라 하지 않는다.

`lexical.tokens(text: str) -> list[str]`는 NFKC 검색 view에서 Hangul bigram/원문 token/camel/snake/exact code identifier를 생성한다. evidence는 정규화하지 않는다. `semantic.validate_reflection(result, claims)`는 실제 입력 citation/identifier/number의 deterministic 경계 검증을 제공한다. model uncertainty를 자동 human approval로 승격하지 않는다.

## Integration 경계

core는 위 Store와 SemanticRuntime을 결합한 유일한 orchestrator다. worker는 한 queue만 소비한다. 모든 model 단계는 짧은 admission commit→DB 밖 inference→currentness/fence publish다. required rule selector는 true/false/unknown, overflow/unknown strict 행동은 block이다. native/model input receipt와 실제 시행·자연어 준수를 혼동하지 않는다.

Heartbeat transient continuation은 마지막 확인 lease의 monotonic cutoff 안에서만 허용한다. 동일 owner가 갱신한 deadline은 admission에서만 수용하며 exact heartbeat/publication fence와 모든 credential/source/route/나머지 lease identity 검사는 유지한다. journal의 latest exact head 요구는 유지한다.

공식 SDK2의 direct `CallToolResult`/단일 TextContent로 네 agent tools를 노출한다. producer/operator action은 별도 token·CLI/API다. legacy SDK session credential 혼합은 outer HTTP 현재 token 검증 및 credential-bound session으로 막고 실제 dual-era/cross-token 시험을 실행한다. server instructions/corpus는 빈 값이다. stdio는 같은 HTTP/core로 중계하며 별도 DB/engine을 열지 않는다. bounded 오류의 RPC ID/type/public code/effect를 검증해 효과를 보존하고 확인할 수 없는 전송 결과는 unknown이다. raw 진단/자동 mutation retry 없음.

Native adapter는 private key-level ownership intent·전역 native config lock·독립 install identity lock을 사용한다. Claude intent는 소유한 canonical project MCP key만 영속화하고 현재 native document에 병합한다. 실제 native mkdir lease의 heartbeat/ownership 및 publication 직전 current bytes를 검사하되 비협조 writer·lease 탈취·같은 UID에 대한 atomic CAS는 보장하지 않는다. host 변경은 quiescent maintenance에서 수행한다. Claude worktree canonical config key와 memory grant/root는 분리하며 native relay의 다른 CWD는 거절한다. 16MiB event decode에서 path를 먼저 projection하고 capture body는 별도 상한을 지킨다. marker/newline 포함 native envelope는 1,800 UTF-8 bytes, spool은 24시간 TTL·물리적 DB/WAL/SHM 상한·명시 gap다. required UNKNOWN 일반 조회는 revision/digest/body/stamp 없는 opaque ref, protected action은 거절한다.

OMP는 before-agent/provider callback 실패·timeout의 fail-closed native pre-request gate가 없으므로 새 strict 설치를 설정 쓰기 전에 거절한다. advisory/MCP는 지원한다. 정확한 historical strict receipt는 owned cleanup만 허용하고 active/replay는 거절하며 기존 로드된 native를 직접 차단한다고 주장하지 않는다. 옛 설치 제거·advisory 재설치 후 host 재시작이 필요하다.

Spool payload의 durable created_at/expires_at는 pending→quarantine→retry/reopen에도 유지한다. 접근/reopen과 body 전송 직전 만료를 집행하며 physically bounded backlog를 indexed metadata batches로 비운다. unknown-age legacy row는 제거/gap이며 신선한 age를 만들지 않는다. bounded expired receipt는 remote non-commit 증거가 아니며 eviction 뒤에는 기존 server-idempotency reconciliation을 따른다. 닫힌 파일의 즉시 물리 삭제/clock rollback/media erasure는 보장하지 않는다.

Advisory PreToolUse는 지원 path tool만 선택하며 자체 core MCP call은 인증된 broker에 위임한다. strict의 unknown/shell footprint 거절은 유지한다. 현재 required revision이 offered 집합에 없는 경우만 stale이며 unrelated epoch/optional stamp 변화는 소비 증명도 stale 증명도 아니다.

Operations runtime은 pinned PG18.6 dump/restore/psql을 확인한다. `restore_preparation_sql(archived_revision, schema) -> str`는 순수 SQL 생성이며 DB를 열지 않는다. preparation과 archive SQL을 같은 BEGIN 안에서 실행하고 age 인증 EOF/digest/크기·producer 성공 뒤에만 COMMIT한다. rollback과 durable private-recovery fence를 구분한다. marker 발행 전 실패는 not_started이며 발행 후 실패는 UNKNOWN/private recovery다.

실제 full-loop 이후 README/CHANGELOG/acceptance를 갱신한다. 1–2주 trial은 미래 관측이므로 완료로 표시하지 않는다.
