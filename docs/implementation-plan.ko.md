# 로컬 구현 계약

현재 계약은 개인·회사 공통 `agent_judged`이며 [architecture](architecture.ko.md)·[requirements](requirements.ko.md)를 따른다. 현재 Claude/Codex 등 coding agent가 네 MCP 도구로 기억 채택·관계·relevance를 판단한다. 서버는 원문 span·revision·credential/grant·binding·snapshot·deletion·deadline을 검증하고 lexical/entity 후보 index를 유지한다. 서버 LLM·model gateway·자동 extraction/consolidation/rerank/reflection·회사-only selection approval은 현재 실행 경로가 아니다.

이 문서는 API/영속 계약과 아직 실행하지 않은 proof 정의다. 실제 결과는 [검증 기록](verification.ko.md)의 run별 evidence를 따른다. API가 존재하거나 source를 읽었다는 사실을 실제 service/native 검증으로 표시하지 않는다.

## 소유권·검증

공식 공통 전환 run은 `development/20261013-234417`이며 authority는 [issue #5](https://github.com/chonamdoo/agents-memory/issues/5)의 댓글6150124320이다.

| 담당 | 소유 범위 |
|---|---|
| Integration owner | application/edge/context, consumer 연결·통합 회귀, 실제 검증·verification/CHANGELOG/checkpoint·공식 runner |
| Authority | store/domain/selection/semantic/semantic_contract/migrations와 authority/grounding 회귀 |
| ModelOps | config/initialization/ops/cli/jobs, obsolete model 파일·dependency 제거와 대응 회귀 |
| Host | hosts/spool/client/host_templates 및 대응 회귀, 공통 source-secret guard와의 연결 |
| Docs | README/requirements/architecture/이 구현 계약, 기존 architecture9–10절의 시나리오·trial 정의 |

writer는 build/lint/tests/formatter·live service·native trust/설정·git publication을 실행하지 않는다. 통합 owner가 모든 writer 완료 후 선언된 `uv run ruff check src tests`, `uv run pytest -q`, `uv build`와 실제 isolated PG/API/SDK/native 시나리오를 실행한다. in-session worker는 공식 confined native reviewer를 대체하지 않는다. 현재 문서 갱신은 이 검증을 실행하지 않았다. 원격 push/PR/merge와 기존 research 변경은 별도 승인이다.

## 설정·CLI·명시적 upgrade

`Settings.capability: Literal["agent_judged"] = "agent_judged"`는 개인·회사 공통이다. `cleanup_interval_seconds=3600`은1–86400, `read_admission_timeout_seconds=180`은1–3600이다. 기존 queue/source/HTTP/MCP/spool/authority bounds는 유지한다. `models`, `allowed_model_purposes`, `lease_seconds`, `heartbeat_seconds`, `job_attempt_limit`은 제거한다. empty model purposes를 다른 capability 허가로 해석하지 않는다.

stage-0 run `development/20261015-043508`이 추가한 설정: `max_concurrent_requests=16`(1–256, 초과 시 인증 전 `SERVICE_BUSY`), `pool_acquire_timeout_seconds=5.0`(0 초과·60 이하, 초과 시 `DATABASE_BUSY`). 둘 다 `not_started`/503이다. DB 지원 계약은 `agents_memory.database`의 `POSTGRES_MAJOR=18`·`MINIMUM_VECTOR=(0,8,7)` 하나이며 `Store.open`/`preflight_initialization`·migrations·`ops` backup/restore가 공유한다. `BackupRuntime`에는 더 이상 PG/pgvector 버전 pin이 없고 archive metadata는 live 버전을 기록한다. 단일 승자·admission 재시도·세션 복구의 규범은 [architecture](architecture.ko.md)의 transport 절을 따른다.

- `record --judgment-file`: key/binding/kind를 포함한 완전한 strict `RecordInput` JSON. 별도 `--binding/--key/--body-file/--kind`와 혼합하지 않는다. note/rule_candidate의 기존 body-file 방식은 유지한다.
- `context --expansions-file`: bounded JSON 문자열 배열을 `query_expansions`로 읽는다.
- `context --admission-id ... --relevance-file ...`: 첫 호출에서 저장된 admission에 대한 전체 exact relevance JSON 배열. query/path/purpose/host/snapshot/expansions의 의미는 첫 요청과 같아야 한다.
- `inspect --ref pending --byte-start ... --max-bytes ...`: pending cursor page. source ref는 original UTF-8 byte window이고 `--rejection-cursor`는 rejection history의 다음 페이지다. `inspect --ref judgment --claim-id ...`를 반복해 최대20 unique claims를 공동 선택한다. cleanup item ref는 해당 pending manifest를 제공한다. 큰 claim은 draft_window의 body를 next_byte 순서로 이어 전체 digest/total_bytes를 확인한 뒤 UTF-8 JSON을 decode한다.
- 현재 CLI에는 `model`, `selection-policy`, `reflect`, `--mode` recall/reflect 선택, `retry`, `reprocess`, `index-status`, `index-recover`, `--selection-file`이 없다. `init --mode personal/company`는 배포 mode이며 제거한 context mode와 다르다.

기존 배포는 stopped-service current operator가 `migrate --confirm-deployment ... --upgrade-config`를 명시 실행한다. `ops.migrate_authority(...,*,config_path=None,original_config=None,retire_model_approval_intent=None)`는 같은 local DB/schema·migrator DSN·current operator·exclusive authority lock을 DDL 전에 검사한다. config 원본은 private exact bytes로 보존한다. historical approval intent가 있으면 마지막 인자에 파일 전체 SHA256을 명시하고 별도 approval flock·원본/audit 보존·모든 구형 route disable·application auth 재검증 후만 exact intent를 retire한다. opaque request digest는 받지 않으며 원래 효과는 unknown_not_attested다. 중단 재개도 재인증하고 원래 model approval 성공/모델 재실행을 만들지 않는다. service/restore fence·미완료 init을 무시하지 않는다. genuine format-one init의13개 retired model 필드는 decode/검증만 하고 원래 서명/config/token을 보존한 뒤 명시 upgrade한다. private original에는 credential/token/key 경로가 남으므로 public 기록에서 제외하고 필요시 실제 credential을 회전한다.

`serve`와 `Store.open()`은 자동 DDL/config cutover를 하지 않는다. 구형 capability/model knobs는 `CONFIG_UPGRADE_REQUIRED`다. 원래 operator/init recovery intent·model approval intent는 증거이며 migration을 통과하려고 수동 삭제하지 않는다. 이 run의 문서 작성은 **live upgrade를 수행하지 않았다**.

## 네 MCP 도구·strict 입력

modern/legacy official SDK edge·private API·CLI는 같은 typed handler/decoder를 사용한다. `memory_context`, `memory_inspect`, `memory_record`, `memory_feedback`만 agent-plane에 노출한다. 연결 instructions/corpus/rule body는0이며 직접 만든 `CallToolResult`의 TextContent 한 plane으로 반환한다. stdio/client는 loopback HTTP 또는 explicit verified HTTPS relay이며 별도 DB/engine을 만들지 않는다.

### 원격 authority·PC client

- 서버 ingress profile은0600 별도 파일이다. canonical HTTPS origin·deployment/realm·bearer 또는 고정 issuer/audience/public JWKS/scope/subject/client_id→현재 PG credential generation 매핑을 검증한다. 매 요청/session의 role/grant를 재인증하며 remote operator bootstrap은 없다.
- Compose는 독립 Caddy/app namespace와 private backend network를 사용한다. private mode의 `serve`만 backend에 bind하고 exact RFC1918 `trusted_proxy_ip`+XFPhttps를 요구한다. Caddy 외 peer의 local Host 위조도 차단한다. backend 미publish·Caddy의 app state/journal/DB socket 미mount·기존 Unix socket SCRAM 권한을 유지한다.
- PC `RemoteClientSettings`는 `kind=remote_client,version=1`과 HTTPS origin/identity/mode/bounds/private state/auth mode/public CA digest만 가진다. DSN/operator를 금지한다. private CA·no proxy/redirect·absolute body deadline·DB/identity readiness 이후 token을 전송한다.
- `/api/client-bootstrap`은 현재 agent/producer의 분리된 credential·role·one-binding grant/revision·bounds만 반환한다. 같은 operator가 발급한 두 credential은 `Store.issue_token` 계약상 같은 `principal_id`를 가지므로 credential 분리를 독립 principal identity로 표현하지 않는다. host-install은 두 응답을 대조하고 remote receipt에 profile을 고정한다. cloud는 PC locator를 stat하지 않는다.
- remote `service`는 PC capture recovery만 관리한다. stop intent·unsafe SQLite·CA drift를 전송/enable 전에 검사하고 새 event 없이 bounded spool을 비운다. offline stop/uninstall은 server token/CA/network 없이 owned 설정만 제거하고 pending/foreign native entry를 보존한다.
- `SESSION_NOT_FOUND/404/not_started`만 reinitialize+원 요청1회 재전송한다. unknown/dispatched write는 자동 재전송하지 않는다. selected Jev 실패는 pending·visible unavailable이며 coding-agent 자동 fallback이 아니다.


### source_selection

`SourceSelectionCommand`의 필드:

- `kind="source_selection"`, optional `binding_id`, nonempty `idempotency_key`, inspected `admission_id`.
- `source_id`, `source_revision>=1`, `binding_revision>=1`, nullable 요청 `snapshot`. source inspect의 `source_snapshot`은 원래 nullable provenance이고 command에는 window의 `snapshot`을 쓴다. 저장 selection은 원래 snapshot과 request_snapshot을 구분한다.
- original `byte_start>=0`, `byte_end>byte_start`, 최대4096 UTF-8 bytes의 window, exact `window_digest`.
- `policy_revision`, `policy_epoch`: 둘 다 non-null 현재 metadata다. revision은 명시 contract digest이며 epoch는 strict nonnegative integer로0이 유효하다. source/AST hashing·company operator selection 승인을 뜻하지 않는다.
- `label=remember/discard/review`, `coverage=complete_window/incomplete_window`, required `reason`, `prior_rejection_ids` 최대8개(default empty).
- `rejection_comparisons` 최대16개: unique `{rejection_id,decision:"unrelated"|"reopen",reason}`. 직접 비교는 현재 inspected IDs이며 reopen 집합만 그 command의 prior_rejection_ids와 같아야 한다. 기본 필수 관련 후보는 최대8개이고 전체 history 순회는 게시 조건이 아니다. 선택적 `rejection_cursor="history"`는 raw32개/eligible8개 이내 live page이며 empty page도 next cursor가 있으면 계속한다. 같은 원문 window/snapshot의 review selection을 최대16개 rejection_review_ids로 연결할 수 있다. remember는 필수 후보+explicit prior를 직접/receipt로 덮고 receipt의 reopening ref는 최종 prior에 재나열하지 않는다. 모든 label의 metadata·fingerprint를 검증하고 무관한 신규 history로 과거 비교를 무효화하지 않는다.
- optional `extraction: GeneratedExtraction`; remember만 extraction을 받을 수 있다. remember-only 또는 zero-claim은 selection_recorded, 유효 claim 게시만 candidate_ready다.

`GeneratedExtraction`은 `claims`(최대32), `individual_qualifications`/`shared_qualifications`(각64), `validities`(32), `unused_span_ids`(128)를 갖는다. assertion ID는 `a0000`처럼 `a`+숫자4자리다. 단일 assertion의 condition/exception은 individual qualification이고 shared는 적어도2개 assertion을 요구한다. 검색 가능한 기억은 remember와 extraction을 원자적으로 제출해야 한다. complete remember-only는 claim 없이 창을 점유하며 나중에 extraction을 덧붙이지 못한다. `resolve_selection()`은 exact source/binding/snapshot/contract/window digest·원래 UTF-8·inventory/qualification/literal grounding을 검증하고 absolute original offsets로 바꾼다. 조건·예외·validity·unused original span을 보존한다. 근거 없는 새 숫자·identifier·qualification은 거절하며 window/policy 변경은 `SELECTION_STALE`다. 원문 normalization/derivative rewrite·사실 entailment 보장·모델 호출은 없다.

speaker `agent_note`는 raw log/inspection만 보존하고 새 source-selection admission·pending·독립 backlog를 만들지 않는다. note-only 기억과 memory/injected echo는 독립 grounding이 아니며 과거 note discard도 인간 근거의 필수 비교를 오염시키지 않는다. human/tool/document 역시 declared provenance이지 인간 현존·진실성·approval의 보장은 아니다.

### claim_judgment

`ClaimJudgmentCommand`의 필드:

- `kind="claim_judgment"`, optional `binding_id`, nonempty `idempotency_key`, inspected `admission_id`, exact `manifest_digest`.
- `claims: tuple[RevisionRef,...]` 1–20개, `sources` 1–128개. 각 ref는 `{id,revision}`이며 unique ID/전체 inspected manifest의 순서·내용을 그대로 제출한다.
- `relations` 최대16개(default 없는 필수 배열). 각 항목은 `left_id`, `right_id`, `relation=duplicate/supports/contradicts/supersedes`, required `reason`이다. pair는 distinct·in-manifest이며 unordered pair 중복은 금지한다.
- required 전체 `reason`. 관계가 없다는 명시 판단은 empty relations로 표현할 수 있다.

`memory_inspect(ref="judgment",claim_ids=[...])`/cleanup ref의 complete claims/sources/snapshot/admission_id/manifest_digest를 사용한다. 최대20 claims·128개 현재 logical relation ref/요약8개이며 overflow를 숨기지 않는다. 각 판단은 같은 pair/manifest라도 자기 asserted edge와 전체 actual-input dependency를 독립 소유한다. 자기 edge가 사라지면 완전한 judgment로 공개하지 않고 독립 적격 derivation은 남긴다. logical read의 dedup은 eligibility 검사 뒤 bound 전에 한다. 공개 duplicate는 저장 duplicates를 정규화한 하나의 이름이다. agent는 원문·부정·조건·예외·modality·scope·valid time·독립 origin을 판단한다. 반대 polarity/qualification 손실/disjoint validity는 JUDGMENT_RELATION_INVALID이며 recorded time은 supersession 근거가 아니다. 관계 판단은 required rule 활성화·source 삭제 권한이 아니다.

`RecordInput`/`RECORD_ADAPTER`는 note/rule_candidate `RecordCommand`, `SourceSelectionCommand`, `ClaimJudgmentCommand`의 strict discriminated union이다. flat MCP root schema도 variant별 required/allowed 필드를 유지한다. tools/list는 presentation-only title만 제거하고 validation constraints/refs는 유지한다. snapshot secret·범위 밖 cursor·잘못된 ref/claim_ids/rejection_cursor 조합은 admission 저장 전에 거절한다. native provider의 schema 수용은 실제 관측 대상이며 JSON Schema 정의만으로 native 호환 pass를 주장하지 않는다.

### 두 호출 memory_context

`ContextCommand`는 binding/query/paths/purpose/host/snapshot/causal_operation/max_bytes/limit에 다음을 더한다.

- `query_expansions: tuple[str,...]=()` 최대8개, nonblank, 각512 UTF-8 bytes/합계4096 bytes.
- `admission_id: Handle|None`, `relevance: tuple[RelevanceJudgment,...]|None` 최대20개. 두 필드는 함께 present/absent여야 한다.
- `RelevanceJudgment`는 unique `claim_id`, strict boolean `relevant`, required bounded `reason`이다.

후보가 있는 첫 호출은 eligible lexical/entity pool을 authority에서 admit한다. `status="judgment_required"`, saved admission_id, 단일 candidate_manifest를 반환하고 모든 claim_id/inspection_ref를 보존한다. wire 예산 안에서 최대160-byte preview/partial·polarity·modality·arms를 추가하며 선택적 상세 축약은 partial로 표시한다. 중복 manifest/candidates aliases·query expansion echo를 제공하지 않는다. relevance 전 context에는 independent required rules만 넣는다. 후보가 없으면 적용 가능한 승인 optional rule도 바로 전달한다.

두 번째 호출은 **같은 saved admission**을 사용한다. canonical request digest는 query/query_expansions/paths/purpose/host/snapshot을 묶고 max_bytes/limit·decisions는 제외한다. exact 전체 saved candidate IDs 각각에 relevant/irrelevant+reason을 제출해야 하며 누락/추가/중복·다른 request/snapshot·만료·authority 변경은 거절한다. empty relevance는 empty manifest에서만 유효하다. index ranking은 default judgment가 아니며 caller decision 순서로 relevant claim을 선택한다. final delivery는 전체 actual pool/source/relation/rule snapshot을 재검사한다.

필수 rule 선택은 candidate retrieval/relevance/cleanup과 독립이다. TRUE는 완전 body/revision, FALSE는 제외, UNKNOWN은 일반 조회에 body/stamp 없는 bounded opaque ref이며 protected action은 UNKNOWN/overflow refusal이다. optional 기본3개/2400 UTF-8 bytes, native marker/newline 포함1800 bytes, tool 최대16KiB wire bound를 유지한다. offered receipt는 consumed/준수/enforced 증거가 아니다.

## Store 공개 경계

`Store(settings: Settings,journal: DeletionJournal)`가 asyncpg pool/transaction을 소유하며 `Application(settings,store)`에 runtime/model/세 번째 shim 인자가 없다. handler가 SQL을 복제하지 않는다. actor는 current credential로 인증한 Principal이며 Store도 scoped auth/currentness를 재검사한다.

| API | 현재 의미 |
|---|---|
| `capture(actor,CaptureCommand)->Operation` | producer/operator, source+pointer+source_selection pending+receipt의 durable capture. no extract job |
| `record(actor,RecordInput)->Operation` | note log/rule candidate 또는 validated source/claim judgment. source selection·claims/index·receipt, 관계 judgment·manifest dependency를 atomic commit |
| `feedback(actor,FeedbackCommand)->Operation` | agent correct/reject/retract_request 후보. correct/reject body 필수, reject body는 persisted reason이며 source evidence identity 연결 |
| `inspect(actor,binding_id,ref,snapshot=None,*,byte_start=0,max_bytes=4096,claim_ids=None,rejection_cursor=None,representation_bytes=None,measure_json=None)->dict` | source/pending/judgment와 complete stored claim/selection/judgment/feedback continuation. 기본 sizer는 neutral JSON, application은 실제 framing sizer/cap을 주입한다. 저장 body의 volatile epoch는 밖에 두고 bigint 폭을 예약해 digest/offset을 안정화한다. source 판단 context는 별도 refs로 읽고 모든 chunk의 current dependency/scope를 검사한다 |
| `search_lexical(actor,binding_id,lexical_tokens,snapshot,limit=20,*,request_digest)->(rows,NonmodelAdmission)` | eligible lexical/entity RRF 후보와 actual pool/source/relation/revision/request manifest를 같은 authority tx에 저장 |
| `recall_admission(actor,binding_id,admission_id,request_digest,snapshot)->(NonmodelAdmission,list[Claim])` | 같은 saved caller_recall manifest 복구·current authority 재검사. 두 번째 call에서 새 검색/admission으로 갈아끼우지 않음 |
| `delivery(actor,binding_id,admissions,rule_versions,snapshot=None,relation_ids=(),*,nonmodel_admission=None,selected_claim_ids=())->dict` | complete current auth/manifest/relation/rule fence. optional 전달은 saved nonmodel admission subset 필요, rules-only는 독립 |
| `schedule_cleanup()->dict` | pending32·고정 insertion bucket4·scope group32 이내 examined work와 durable cycle progress/more. empty/current/revision/held eligibility를 보존하고 유효한 동일 manifest 재예약 방지. 의미 판정·자동 LLM 없음 |
| `operation/stats` | current_operations/current_jobs/dlq는 unresolved successor만 현재 복구 대상으로 집계. historical_operations/historical_jobs/recovery_jobs는 원래 실패·attempt·successor disposition 보존 |
| `claim/relations/rules` | scoped current actual-input dependency·snapshot·revision·approval 검사, whole lineage 보존 |
| `correct/retract/purge` | producer/operator의 실제 source correction·logical withdrawal/floor·physical local row purge, agent feedback과 구분 |
| `bootstrap/authenticate/register_binding/list_bindings/issue_token/revoke_token` | credential-bound identity/grant. body/CWD/branch/MCP session은 권한 아님 |
| `propose_rule/approve_rule/withdraw_rule` | exact body/selector/required/scope/target-set digest 승인. 이 프로젝트/내 frozen projects/팀 또는 project 공유의 세 범위 |

`NonmodelAdmission`은 credential generation·realm·binding revision·epoch/deletion generation·contract policy_revision/epoch·source revision refs·actual claim IDs·snapshot·deadline·request_digest와 inspected `rejection_ids`(최대8개/default empty)다. persisted admissions의 `claim_revisions`도 currentness fence에 쓰인다. fake model revision·route/vector가 없다. empty candidate pool도 recall admission을 만들며 rules-only 전달에는 이를 억지로 요구하지 않는다.

`selection_contract_revision()`은 common source/claim schema와 validators/lexical/semantic contract의 digest다. 이름에 policy가 남은 metadata는 승인 authority가 아니며 과거 `am_selection_policies`/approval receipt는 historical restore/audit용이다. current CLI approve/enable alias를 제공하지 않는다.

## 거절 이유·보수적 evidence guard

source inspect의 bounded `judgment_context`는 `accepted_memories`, `rejections`, `context_partial`을 제공한다. 긴 statement/reason은 inspection 필요 표시를 사용하며 목록의 제한을 전체 memory/rejection catalog로 해석하지 않는다.

- 같은 source overlap/새 origin 동일 body 차단은 candidate index와 독립이며 unresolved identity bound는 fail closed한다. draft 변경으로 EVIDENCE_REJECTED를 우회하지 못한다.
- reopening은 독립 human/tool/document 원문·실제 prior ref·이유가 필요하다. assistant는 일반 capture 판단 대상일 수 있지만 독립 reopening 증거는 아니다.
- remember는 inspected 필수 후보+explicit prior를 정확히 비교한다. 모든 label의 제출 비교/review를 검증하고 scope/target 전체 dependency·별도 feedback reason source에 현재 privacy를 적용한다. 전체 history 순회나 무관한 신규 rejection 재검토를 요구하지 않는다.
- 의미 동등성/독립성은 현재 coding LLM이 판단한다. hashed lexical/entity 후보와 exact byte identity는 의미 판정이 아니며 source 전체 차단이 무해한 다른 주장도 막을 수 있음을 숨기지 않는다.
- discard/reject는 삭제·floor 확장이 아니다. non-deriving selection 철회는 uncovered raw work를 다시 열며 global claim은 scoped audit 때문에 private scope가 되지 않는다. agent_note는 raw inspect만 남기고 새 판단 admission/pending/backlog 및 과거 note-discard 오염을 만들지 않는다.

## Pending·scheduler·provenance

`CleanupScheduler(settings,store)`는 due work만 예약한다. pending32·고정20-position page4·binding/snapshot group32와 durable high-water/keyset/group cursor로 transaction을 제한한다. `more`는 transaction 사이 `await asyncio.sleep(0)` 뒤 이어 처리하며 실패 시 이전 more 상태로 spin하지 않는다. 새 낮은 UUID/삭제/만료로 기존 page를 재배열하지 않는다. held legacy owner는 restore/reopen으로 reset하지 않는다. local_drained는 scheduler 상태이지 provider/agent 종료 증거가 아니다.

`inspect(ref="pending",byte_start=cursor,max_bytes=4096)`의 next_cursor/partial을 따라 page를 읽는다. cursor는 original source byte offset과 달리 pending 목록 위치다. page ID 목록은 bounded preview이며 full item/source/judgment ref를 inspect한다. source selection의 review는 unresolved이며 incomplete-window를 whole-session 완료로 표시하지 않는다.

`CaptureCoverage`는 producer_reported observed_window/truncated/unknown·gaps·nullable original_bytes다. `SourcePointer`는 source/binding revision·snapshot·speaker·nullable event_time·recorded_at·byte_length·coverage의 body-free locator다. 실제 read grant·전체 session/consumer 관측 증거가 아니다. evidence span은 canonical source에서 `source_speaker/source_event_time/source_recorded_at`을 얻고 event time null을 recorded time으로 대체하지 않는다. Claim의 `interpretation_role/selection_id/policy_revision/revision/awaiting_revalidation`을 보존한다.

## 0006 영속·복원 계약

forward revision은 `0006_agent_judged`, parent는 `0005_company_selection`이다. old migration bytes는 바꾸지 않는다.

| 저장 변경 | 내용 |
|---|---|
| am_claims | old lexical_entity만 agent_judged로 전환. revision(default1), awaiting_revalidation 추가; model_derived_candidate는 true. legacy full_semantic/route/vector provenance 유지, caller claim은 route/embedding/vector NULL·selection/policy link |
| am_source_selections | nullable historical reason·required new-command reason, prior_rejection_ids(default empty), rejection_comparisons JSON(default empty). 원문/claim draft 사본 없음 |
| am_feedback | reason, rejected_source_ids(default empty), active/retracted state |
| am_admissions | request_digest, claim_revisions JSON(default empty), rejection_ids(default empty). current caller admission은 strict complete manifest/inspected rejection context |
| am_jobs | retired_at 추가. original state/error/attempt/generation/time 보존 |
| am_pending_judgments | source_selection/cleanup/legacy_revalidation, source/claim IDs·snapshot, pending/held/resolved/retracted·reason·original_job_id·timestamps. binding/snapshot cleanup pending 중복 제한 |
| am_retired_jobs | job FK·original complete row JSON·successor pending FK·retired_at. original executable job evidence 보존 |
| am_claim_judgments | binding/operation/credential generation/admission/digest, exact claims/sources/relations/reason·state/time |
| am_relations | judgment_id FK와 기존 full input dependency. wire duplicate와 storage duplicates 구분 |

pending/leased/blocked/failed old jobs는 original row audit를 남기고 executable ownership만 retirement한다. active source body가 남으면 legacy_revalidation pending, 아니면 held다. old model claims를 caller_grounded_candidate로 relabel하거나 context에 자동 주입하지 않으며 원문부터 current agent가 revalidate한다. 기존 실패 row/count를 지우지 않는다.

current archive table inventory는 새 세 table과 기존 authority를 포함한다. 0001–0005 historical archive는 revision별 exact allowlist로 검증한다. 새 FK/table cleanup과 archive SQL은 같은 uncommitted transaction에서 처리하고 authenticated age EOF·digest/size·SQL producer 성공 후 commit한다. restore 후 current forward migration·fresh credential/rule reapproval·deletion journal/floor를 적용한다. purge floor는 inaccessible historical row도 scrub하며 old spool/import/backup으로 근거를 부활시키지 않는다. config audit·independent journal은 private이고 repository/archive 원문 metric에 넣지 않는다.

`DeletionJournal(directory,deployment_id)`는 restore 밖의 body-free HMAC source/origin/artifact floor chain이다. verify/entries가 absent journal을 자동 initialize하지 않는다. exact latest head·pending intent reconciliation 없이는 authority를 열지 않는다. operator-supplied head는 외부 witness attestation이 아니며 같은 UID·WAL/media/retained encrypted archive forensic erasure 보장은 없다.

## Host·transport·보호 행동

owned project/native config entry만 install/uninstall하며 Agent Flow/user hooks·native trust·native memory 설정을 변경하지 않는다. older exact historical receipts는 owned cleanup-only다. Claude canonical native key와 설치 소유권은 MCP의 credential/project grant와 구분한다. 연결된 MCP는 리더/워크트리·호출 CWD와 무관하게 같은 authorized binding을 사용하며, 자동 capture/protected-action hook의 경로 범위 검사는 유지한다. relocate는 operator expected_revision+locator CAS이며 uninstall→relocate→reinstall 순서를 따른다. deleted root는 explicit --project-deleted private native cleanup 후 root 재등장 때 일반 uninstall로 마친다.

capture→durable ACK/body-free pointer→agent-visible pending과 inspect→judgment를 구분한다. malformed/lost/unknown ACK는 original exact-key reconciliation 대상이며 clock/revision을 발명하지 않는다. spool original24h TTL은 quarantine/retry/reopen으로 늘리지 않으며 expiry/unknown-age는 safe gap다. secret raw envelope는 공통 guard로 digest/spool 전에 거절하고 body-free gap만 유지한다. typed validated object를 enqueue할 때 별도 derivative rewrite를 하지 않으며 network admission은 독립 trust boundary다.

per-agent/thread/lineage/context generation을 구분한다. resume/compact/fork/child에서 보존을 확인하지 못하면 generation을 갱신한다. marked injected memory는 reentry grounding이 아니며 unmarked native memory 복사는 caller가 비교해야 한다. native duplicate 시나리오는 architecture9절 H01–H04가 정본이다.

Claude prompt attribution, Codex child/hosted tool, OMP print/ACP·후속 provider input은 미관측 경로를 유지한다. OMP 새 strict는 HOST_STRICT_UNSUPPORTED로 쓰기 전 거절하고 advisory/manual MCP만 지원한다. historical strict owned cleanup과 host restart가 필요하며 receipt rejection을 이미 로드된 옛 provider 호출 차단으로 주장하지 않는다. required TRUE/UNKNOWN/overflow·first-action guard는 optional relevance와 독립이다. code/transport/source proof는 native enforced proof가 아니다.

## Historical proof와 아직 실행하지 않은 proof

`development/20261013-103527` 회사 capability A 및 같은 범위 recovery `development/20261013-221430`의 기록은 보존한다. original run은 QA fixture 실패·3회 제한 뒤 사용자 선택으로 artifacts를 보존하고 공식 abort했다. recovery는 fixture 시간 준비만 수정했고 집중 회귀8개·실제 PG smoke·fresh native12개 approve·공식 QA **1413 passed/skip0·lint/build3/3**를 완료했다. 제품35파일/wheel은 당시 실제 service 검증본과 같았으며 handoff/report의 canonical 상태를 따른다. 개인 full-semantic baseline/R31 proof도 당시 범위의 historical 증거다.

이 결과는 이번 common agent_judged 전환의 QA·native compatibility·elapsed trial·의미 품질·회사 운영 enablement 증거가 아니다. 현재 acceptance는 architecture9절 A01–A16, PMPA P01–P04, secret/content reentry R01–R05, hostnative H01–H04와 공식 explore S1–S12다. 모든 항목은 실제 executor·입력 revision·expected/observed result·미관측 경계를 구분해 integration owner가 기록한다.

1–2주 paired memory-on/off 제한 trial의 frozen task/corpus·동일 host/model/budget·required 보호·native 잔류 제외·수동 지표·즉시 중단·판정 기준은 architecture10절이 정본이다. **trial은 시작하지 않았고 measured benefit은 없다.** 건강/health metrics 기능·cloud provisioning·publication은 이번 범위 밖이다.
