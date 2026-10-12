# 1라운드 독립 설계안: 로컬 우선 memory 서비스

## 1. 결론: 선택한 구조와 이전 제안에서 바꾼 점

**선택 [INFERENCE, 미구현]**

1. **`amm` 서비스가 권위를 가진다.** Python 3.12와 공식 `mcp==2.3.0`을 쓰는 ASGI process 하나에 세 가지를 둔다. 모두 같은 domain command handler를 호출한다.
   - dual-era MCP edge
   - hook/extension용 private adapter API
   - worker(dispatcher·reconciler)
   
   amm이 소유하는 것은 다음과 같다.
   - capture event·episode·source identity
   - 작업 원장(outbox)
   - 공개 여부와 eligibility
   - 세 범위 rule plane
   - tombstone·철회 epoch
   - backup/restore 조정
2. **Hindsight는 실행만 맡는다.** pin은 `a9eeed7`(0.10.3)이다. 운영 조건은 다음과 같다.
   - unforked이고 extension은 0개다.
   - `MCP_ENABLED=false`로 둔다.
   - 고정 `WORKER_ID`를 쓰는 embedded worker 1개만 돌린다.
   - 호스트에 포트를 공개하지 않는다.
   
   추출·embedding·consolidation·mental model refresh·recall·reflect의 **유일한 실행자**다. Hindsight에 쓰는 주체는 amm 하나다. 제품 안의 LLM 호출 경로도 Hindsight slot뿐이며 amm은 LLM을 직접 호출하지 않는다.
3. **격리 단위는 tag가 아니다.** trust domain마다 배포(PG cluster)를 나누고, binding(project)과 Hindsight bank를 1:1로 맞춘다. tag는 bank 안에서 branch와 validity를 표시하는 데만 쓰고 권한 경계로 쓰지 않는다.
4. **정확성은 binding별 `retraction_epoch` barrier로 확보한다.**
   - 엔진 읽기: epoch를 확인하고, 엔진을 호출하고, epoch를 다시 확인한다. 값이 다르면 결과를 **전체 폐기**한다.
   - 철회: 다음 순서로 진행한다. 결과 post-filter가 아니라 **입력 차단**이다.
     1. 한 txn에서 tombstone 기록, epoch 증가, barrier on
     2. 엔진 quiescence 대기
     3. 문서 삭제
     4. 해당 bank의 파생물 재구성
     5. 구조 검증
     6. 개방
5. **Hindsight directive는 쓰지 않는다(0개 유지).** 승인된 규칙은 amm이 결정적 selector로 골라 hook 경로에 원문으로 전달한다.
6. **배포 단위는 Colima 위의 compose 하나다.** 구성은 PG16+pgvector, Hindsight image digest, amm이다. 나중에 같은 artifact를 개인 VM에 올린다.

**이전 제안에서 바꾼 점**
- 이전에는 Hindsight 내부 통제 지점을 patch하는 방향이었다. 이번에는 **fork 없이 외부 quiescence barrier로 대체**한다. 대가는 두 가지다. 철회 중 해당 binding의 memory를 쓸 수 없고, 재구성에 LLM 비용이 든다.
- tag PATCH로 상태를 전이하지 않는다. PATCH는 모든 unit에 전파되고 파생 observation을 무효화한 뒤 재통합을 queue에 넣는다(engine-evidence §1, `http.py L7880-7900` 인용). TenantExtension과 validator도 쓰지 않는다. 승인 상태는 Hindsight에 넣지 않는다.
- **이전 Opus 입장(좁은 core 기본)을 수정한다.** 근거는 engine-evidence §1–3이다. amm이 권위를 전부 가져오면 Hindsight에는 semantic 실행만 남는다. 그 경계에서 필요한 통제는 fork 없이 coarse barrier로 얻을 수 있다. 단, §3의 trigger 중 하나라도 실측되면 좁은 PG engine으로 **교체**한다. 두 엔진을 병행하지 않는다.

**Python MCP 2는 이 범위에서 채택 가능하다.** packet probe 결과는 다음과 같다(local-first-python-mcp-feasibility.ko.md).
- `MCPServer` 하나와 `streamable_http_app` 하나에서 modern 저장 → legacy 조회 → auto 조회 → modern 조회가 같은 note를 반환했다.
- modern 구간에는 `Mcp-Session-Id`가 없었다.
- omp(legacy `2025-11-25`, host F1), Claude v1/legacy 강제, Codex fallback은 spec의 Legacy+Dual-era 조합으로 같은 edge에 붙는다(F2). 그래서 core를 두 개 만들지 않는다.

이 probe가 증명하지 않은 것도 분명히 한다. native host 연결, PG, auth, 제품 동작은 증명되지 않았다. 증거는 SQLite synthetic 결과다.

## 2. 소유권 경계, 작업 원장, 상태·오류 계약

| 대상 | 단일 소유자 | 다른 쪽에 있는 것 |
|---|---|---|
| capture event·actor·episode·source identity | `amm.capture_event`(append-only) | Hindsight document metadata는 권위 없는 사본 |
| **claim 추출·embedding·통합·refresh 실행** | **Hindsight `async_operations`**(embedded worker 1) | amm outbox는 전달과 관찰 job만 가진다 |
| queryable 여부·eligibility·epoch | amm | 엔진의 op 완료는 입력값일 뿐이다 |
| 규칙 본문·승인·활성화 | amm rule plane. ③ 범위는 repo 파일과 PR | Hindsight directive 0개 |
| 철회·삭제 head | amm tombstone과 cluster 밖 journal | 엔진의 delete/invalidate는 실행 수단 |
| LLM route | amm이 생성·검증한 Hindsight slot 설정 | amm의 직접 LLM 호출 0 |
| backup/restore | amm ops: cluster 단위 dump와 journal | Hindsight admin backup은 쓰지 않음 |

**같은 job을 두 queue가 소유하지 않는다.**
- amm의 `dispatch_retain`은 문서를 엔진에 넘기고 엔진의 terminal 상태를 확인하는 데까지만 소유한다.
- amm은 추출을 다시 실행하지 않는다. 재제출은 같은 `document_id`와 같은 content로만 한다. 엔진의 content_hash gate가 중복을 흡수한다(engine-evidence §1 Retain).
- amm job은 lease, fencing token, expected generation을 가진다. lease를 잃은 늦은 dispatcher의 commit은 거절한다.
- amm job 종류는 `dispatch_retain`, `dispatch_delete`, `rebuild_binding`, `restore_reconcile`, `retention_sweep`, `shared_rule_index`다.
- 엔진의 retain, consolidation, refresh에는 fencing이 없다. 그래서 §3 A3의 single-worker 조건에 의존한다.

**Event 상태:** `accepted → dispatched → engine_running → indexed → consolidated`, 또는 `failed_retryable | failed_permanent | blocked_route | superseded | retracted`.
- queryable은 `indexed`이면서 binding barrier가 꺼진 상태다.
- 엔진의 완료 표시는 data commit과 별도 txn이다(engine-evidence §1). 그래서 amm이 op 상태를 조회해 확인한 뒤에야 `indexed`로 둔다.

**읽기 envelope:**
- `status`: `ok | partial | unavailable | blocked | binding_required`
- `stamp`: `{binding, rule_set_digest, retraction_epoch, index_watermark, engine_pin, route_id, mode}`
- `coverage`: `{pending, consolidation_pending, capture_lag, excluded_reasons}`
- 각 item: `kind(rule|evidence|observation|reflect|candidate)`, `authority(approved|human_source|ai_derived|ai_consolidated|ai_reflect)`, `validity{branch, commit, historical}`, `citation`, `rev`

**오류:** `BINDING_REQUIRED`, `IDEMPOTENCY_CONFLICT`, `CONTEXT_STALE`, `RETRACTION_IN_PROGRESS`, `REQUIRED_CONTEXT_OVER_BUDGET`, `ROUTE_NOT_APPROVED`, `SERVICE_UNAVAILABLE`, `PERMISSION_DENIED`, `SCHEMA_UNSUPPORTED`. unavailable은 empty가 아니고 partial은 complete가 아니다.

**일관성이 뜻하는 범위**
- 같은 stamp에서 결정적으로 같아야 하는 것: rule 선택, binding 해석, 예산 절단(item 단위), 오류 분기, recall 후보. recall은 non-LLM retrieval+rerank라고 추정하지만 [미확정]이다.
- reflect와 추출은 LLM 출력이라 매번 같다고 약속하지 않는다. stamp로 차이의 출처를 설명할 수 있게만 한다.

## 3. 내 선호안 공격: unforked Hindsight와 amm 권위

| # | 공격 | 근거(packet) | 판정과 대응·남는 비용 |
|---|---|---|---|
| A1 | internal background 작업은 tag scope 밖이다. `observation_scopes='shared'`이면 untagged observation이 생긴다 | engine-evidence §1 읽기 범위 | **bank 분리로 무력화.** amm은 이 파라미터를 보내지 않는다. doctor가 untagged observation 0을 확인한다. bank 안의 branch 혼합은 남으므로 다른 branch fact는 historical로 표시한다 |
| A2 | untagged directive는 범위와 무관하게 항상 적용된다 | §1 | **무력화.** directive 0 정책, `ENABLE_BANK_CONFIG_API=false`, 포트 비공개, `apply_all_directives=false`. doctor가 directive 0을 확인한다 |
| A3 | lease·heartbeat·fencing이 없다. `_mark_completed`는 세대를 확인하지 않는다. cancel은 시작 시 1회만 확인하고 fail-open이다 | §1 Queue | **single-node에서만 생존.** worker 1개와 고정 WORKER_ID로 재시작 시 재claim한다(LLM 비용 중복, data는 hash로 dedup). 철회는 cancel이 아니라 processing 0 대기에 의존한다. **multi-worker나 HA가 필요해지면 fork 또는 교체** |
| A4 | 근거가 전부 사라지면 본문이 남는 false negative, consolidation pending 중 철회 지연, orphan consolidation, invalidate 뒤 파생물 정리 시점 미확정 | §1 철회, §2 | **세밀한 처리는 불가, coarse 방식으로 생존.** barrier → quiesce → delete → binding의 observation·mental model clear → 재통합/refresh → 검증 → 개방. 검증 기준: 삭제 doc을 참조하는 unit 0, 해석되지 않는 based_on 0. 가용성 손실과 비용은 trial에서 측정한다 |
| A5 | admin restore는 TRUNCATE CASCADE이고 async_operations까지 복원한다 | §1 backup | **amm 절차로 생존.** 두 schema를 함께 담는 cluster 단위 dump와 **cluster 밖 append-only deletion journal**을 둔다(hash chain, 본문 없음, ack 전 fsync). 복원 순서는 아래에 따로 적는다 |
| A6 | 사후 필터는 이미 오염된 LLM 입력을 고치지 못한다 | proposal §8 | **생존.** barrier/epoch를 호출 전에 확인하고, 호출 후 epoch가 다르면 결과 전체를 폐기한다(재시도는 1회로 제한). based_on 대조는 보조 검사다. LLM이 보고도 인용하지 않은 입력은 citation에 나오지 않는다 |
| A7 | retain에 idempotency key가 없다. append 재전송은 중복된다 | §1 Retain | **생존.** capture 문서는 불변 `amm:ev:{segment_id}`이고 replace만 쓴다. note는 `amm:note:{id}` replace. append는 금지한다 |
| A8 | `llm_requests` trace가 기본 on(1일)이다. audit을 켜면 raw가 무기한 남는다. `observation_history`가 orphan으로 남는다 | §1 purge | **조건부.** audit은 off. trace를 끌 수 없다면 [미확정] operator 전용 pin 고정 sweep SQL을 쓴다. fork는 0이지만 schema 결합은 생긴다. 상태는 `retracted`/`purged`/`backup_expired`로 나눈다 |
| A9 | default·fallback route와 egress 경로(OCR, VLM, webhook, OTEL, HF, litellm) | §4 | **조건부.** 모든 slot과 global 값을 명시하고 OCR/VLM/parser를 끈다. weights는 image에 미리 넣고 HF offline으로 둔다. webhook은 amm loopback만. Hindsight는 internal network와 allowlist egress proxy 뒤에 둔다. missing key 시 fail-closed인지는 acceptance에서 실측한다 |
| A10 | 기본 embedding과 reranker가 영어 중심이다 | §4 | **미확정.** multilingual-e5-small(onnx 정의 있음)을 쓴다. reranker 교체 가능 여부는 미확정이며 M2 eval의 hardstop으로 둔다 |

A5의 복원 순서는 다음과 같다.
1. amm edge를 닫고 Hindsight worker를 끈 상태로 기동한다.
2. 복원된 pending op를 전부 cancel한다.
3. deletion journal head를 다시 적용한다.
4. amm outbox 기준으로 재전달한다.
5. 개방한다.

transcript를 다시 스캔해도 scope-bound source identity tombstone이 재수집을 막는다.

**좁은 PG engine에 대한 역공격.** 좁은 engine이 금지된 축소가 되지 않으려면 다음을 모두 제공해야 한다.
- 구조화 추출과 entity·시간 validity
- 다국어 embedding과 rerank
- hybrid fusion. PG FTS에는 한국어 parser가 없으므로 pg_trgm이나 bigram을 따로 설계해야 한다.
- 모순·중복을 병합하는 통합
- citation이 있는 reflect
- 파생 요약과 재처리

장점은 fencing, lineage, 입력 fence를 구조적으로 갖는다는 점이다. barrier 비용도 없다. 그래서 amm 내부 경계를 `EnginePort`(retain / delete / clear_derived / rebuild / recall / reflect / op_status)로 고정한다. 교체할 때 domain, barrier, rule plane은 그대로 둔다. 이것은 교체 seam이지 두 번째 core가 아니다.

**교체 trigger [제안 수치, 측정 전]:** 다음 중 하나라도 실측되면 교체한다.
1. trial 크기의 binding에서 철회 재구성 p95가 30분을 넘거나, 비용이 하루 추출 비용을 넘는다.
2. multi-worker가 필요해진다.
3. 한국어 recall이 matched baseline보다 낮다.
4. pin을 올렸더니 API 계약이 깨진다.
5. 회사 purge 의무가 있는데 pin 고정 SQL 없이는 처리할 수 없다.
6. license나 오프라인 weights 조건을 맞출 수 없다.

## 4. Identity·lineage·호출 표면·context·세 범위 규칙

**Identity**
- deployment(trust domain)는 설치 때 고정한다.
- binding은 `realpath(git common-dir)`가 operator가 등록한 alias에 있을 때만 해석된다. 그렇지 않으면 `BINDING_REQUIRED`이고 default나 global bank로 넘어가지 않는다.
- worktree는 같은 binding이다. branch, HEAD, worktree path는 provenance로 남긴다.
- principal은 설치별 token으로 정한다. `clientInfo`, `serverInfo`, MCP session, JSON-RPC id는 identity나 key로 쓰지 않는다(F2, F11).
- root_run은 adapter가 host root session을 처음 볼 때 발급하는 UUID다. host session id는 속성으로만 둔다.
- agent_path 출처: Claude와 Codex는 `agent_id`, omp는 `ctx.agent` chain이다. omp에서 module-global 상태는 금지한다(F7).
- domain idempotency key는 `(root_run, host turn/event id, kind)`의 digest다.

**fork·compact·resume·child (F6, F7)**

| 사건 | Claude | Codex | omp | amm 처리 |
|---|---|---|---|---|
| compact | SessionStart `compact` | SessionStart `compact` | `session_compact` | ctx_gen 증가, 아직 적용되는 mandatory만 재전달(optional은 재전달 안 함) |
| resume | `resume`(주입한 text replay) | 미확인 | 미확인 | ctx_gen 유지, revision 재검사, 바뀐 rule만 supersede 원문 전달 |
| fork | `fork`(≥2.1.214) | hook 신호 없음 | switch/branch reason fork | 새 root_run(parent link)에 receipt 복사. Codex는 capability `none`이라 degraded로 표시 |
| child | fork가 아닌 subagent는 새 context | session_id가 parent 것 | MCP proxy 공유 | 빈 receipt 또는 복사. omp는 adapter API에 `ctx.agent`를 명시해 전달 |

**호출 표면**
- session을 시작할 때 memory·rule 본문은 0이다.
- MCP tool은 4개이고 instructions는 512자 이하다(F3, F10). 각 tool이 받는 인자는 다음과 같다.
  - `memory_context`: query, mode=recall|reflect, budget
  - `memory_inspect`: item_ref
  - `memory_record`: note 또는 candidate
  - `memory_feedback`: correct, reject, retract_request
- 모델 tool로는 human이나 approved 권위를 자가 선언할 수 없다. retract_request는 사람이 CLI나 host 권한 prompt로 확인해야 실행된다. 이것이 prompt injection을 통한 memory 삭제 공격을 막는다.
- capture, 승인, admin은 CLI와 adapter API로만 한다.

**Per-prompt hook(UPS, `before_agent_start`)이 주입하는 것**
- (a) 아직 전달되지 않은 `phase=any ∧ path=any` mandatory rule의 원문
- (b) optional recall. [제안] score 임계값 이상, 최대 3개, rendered 600 token 이하, 이번 ctx_gen에서 아직 전달하지 않은 것만
- 해당하는 것이 없으면 **0 bytes**다.
- 예산은 item 단위로 자른다. mandatory를 자르지 않고 `REQUIRED_CONTEXT_OVER_BUDGET`을 반환한다.
- 주입 block에는 receipt marker를 넣는다. capture는 이 block을 제외해 재귀적 capture를 막는다.
- Claude는 timeout이 나면 context를 버리고 prompt를 진행한다(F4). 이 경우 degraded로 기록한다.

**세 범위**
- **① 이 로컬 프로젝트**: deployment와 binding에 묶인다. amm DB에만 있고 Git이나 팀과 무관하다.
- **② 내 프로젝트들**: 같은 deployment와 principal의 모든 binding에 적용된다. 회사 배포의 "내 프로젝트"는 회사 배포 안에만 머문다.
- **③ 팀·프로젝트 공유**: repo의 비-eager 경로(`.agent-memory/rules/`)에 있는 파일이다. 기본 branch에 merge된 revision이 정본이고 PR 승인이 권위다. amm은 digest projection만 가진다. approver가 구성되지 않았으면 선택지는 남기고 사용 불가 사유를 표시한다.

제시할 때는 항상 이 세 옵션이다. 취소하거나 응답이 없으면 candidate로만 남는다. 승인은 body, selector, exception, target의 digest에 묶인다. 적용 조건을 넓히면 다시 승인받아야 한다. 같은 `rule_key`에서 ③은 기본적으로 override할 수 없다. 충돌은 활성화 시점에 표시한다.

**First-action barrier**
- Claude와 Codex는 PreToolUse, omp는 `tool_call`에서 Write, Edit, apply_patch의 대상 path를 계산한다.
- 아직 전달되지 않은 path rule이 있으면 **deny하고 사유에 rule id, rev, 원문을 담는다.** receipt를 기록한 뒤 재시도는 allow한다.
- allow+context 방식은 전달로 세지 않는다(F5).
- 다음은 coverage gap으로 표시한다: Bash, hosted tool, IDE, Codex fail-open. 검사 가능한 규칙은 lint와 CI로 집행한다.
- `.omp/rules`로 내보내지 않는다(F12). root `CLAUDE.md`와 `AGENTS.md`에는 쓰지 않는다.

## 5. 전체 semantic chain과 단계별 실패 가시성

| 단계 | 소유 | 실패 시 소비자가 보는 상태 |
|---|---|---|
| capture | host adapter → 0600 bounded spool → adapter API | `capture_lag`. spool이 넘쳐도 버리지 않고 `capture_gap`과 해당 구간 watermark를 기록 |
| durable ingest | amm: event와 outbox를 한 txn에 | `IDEMPOTENCY_CONFLICT`, `BINDING_REQUIRED`, `rejected_tombstoned` |
| signal 선택 | amm의 결정적 규칙(LLM 0) | 제외 사유를 coverage에 기록. 조용히 버리지 않음 |
| claim 추출·embedding | Hindsight retain | `blocked_route`, `failed_retryable` / `failed_permanent` |
| 통합 | Hindsight auto consolidation | `consolidation_pending` |
| recall | amm epoch gate → recall → authority·validity enrich | `unavailable`, `RETRACTION_IN_PROGRESS`, `partial` |
| reflect | 명시 mode에서만. `include_based_on=true`, 결과는 candidate | `CONTEXT_STALE`, 300s timeout |
| 정정·철회 | 사람 채널 → tombstone·barrier → delete, rebuild | ack 시점에 barrier on. 재구성 중에는 `unavailable` |
| 다음 작업 | hook, barrier, tool | delivery receipt |

- **사람의 정정**은 human_source event로 남는다. 거기서 추출된 fact의 권위는 ai_derived이며, 출처가 사람이라는 사실은 provenance로 함께 남는다. 정정이 특정 item의 오류를 가리키면 해당 source를 철회하고 barrier를 건다.
- **recurring investigation**은 서로 다른 root_run의 수로 센다. event 수로 세지 않는다.
- **거절한 candidate**는 `(rule_key, normalized digest)` 기준 rejection ledger로 재제안을 막는다. 새 근거가 있을 때만 다시 제안한다.
- **철회 중에도 rule plane은 독립적으로 동작한다.** 그래서 memory를 철회하는 동안에도 보호 대상 행동의 mandatory 규칙은 계속 전달된다.

## 6. 모듈·설치·로컬 milestone·실행 가능한 acceptance

```
amm/domain/    commands·states·errors·invariants (I/O 없음)
amm/store/     amm schema migrations, outbox(lease/fencing), receipts
amm/journal/   cluster 밖 deletion journal (hash chain)
amm/capture/   envelope·episode·source identity·selection·redaction
amm/engine/    EnginePort + HindsightAdapter (routes·op 관찰·rebuild)
amm/rules/     revisions·3 scopes·resolver·receipts·shared index
amm/context/   budget·rendering·token count·stamp
amm/edge/      mcp.py(MCPServer dual-era) · adapter_api.py
amm/ops/       install·bind·host enable·doctor·backup·restore·trial report
adapters/{claude,codex}/  stdlib 전용 hook client(unix socket)
adapters/omp/             TS extension (ctx.agent 키)
deploy/compose.yaml       pg16+pgvector · hindsight@digest · amm · egress proxy
eval/                     corpus·baseline·metrics
```

**설치 단계는 따로 실행한다.** `amm install`(Colima를 자동으로 시작하지 않음) → `amm project bind`(operator) → `amm host enable <host> --project` → `amm doctor`.
- `host enable`은 project-local에 owned entry와 marker만 쓴다. host trust 승인(Codex hash, Claude workspace)은 **사용자가 직접 수동으로** 한다.
- uninstall해도 data는 기본 보존한다.

**Milestone (의존 순서, 전부 미실행 [제안])**

| M | 내용 | 실행 가능한 acceptance |
|---|---|---|
| M0 | bootstrap: Python 3.12 lock, `mcp==2.3.0` pin, Agent Flow 설정 | research 파일 sha256 불변, 빈 test green |
| M1 | store, outbox, journal | **실제 PG**에서: 같은 key와 digest면 같은 receipt, digest가 다르면 conflict, 늦은 lease commit 거절, journal-PG 사이 crash 후 복구 |
| M2 | compose와 Hindsight route | 한·영 합성 corpus로 retain, recall, reflect(based_on) 확인. proxy log에 승인 host만 기록. key가 없을 때 fail-closed 실측. retain 중 kill -9 후 재기동 시 unit 중복 없음 |
| M3 | edge | **amm과 PG로** 4-mode probe 재실행. era를 넘는 idempotent replay. 미등록 cwd는 `BINDING_REQUIRED`. 예산 초과 오류 |
| M4 | capture와 lineage | host 3개 각각 compact, resume, fork, child. service down일 때 spool 후 flush. child event를 반복으로 세지 않음 |
| M5 | rule와 barrier | 새 파일의 첫 Write는 deny하고 rule id 반환, 두 번째는 allow. root 파일 hash 불변. 취소는 candidate만. ② 규칙이 회사 binding에 적용되지 않음 |
| M6 | 철회와 restore | 무작위 interleaving property test로 ack 이후 recall과 reflect에 0건. 오래된 snapshot restore 후 개방 전에 journal 재적용. transcript 재스캔으로 부활하지 않음 |
| M7 | E2E와 eval | memory-on과 off를 같은 model, corpus, budget으로 비교. token 계측 |

**Agent Flow 사용**
- pin은 0.3.15 `0ffba88`이고 이 project의 설정만 바꾼다. Agent Flow core 변경은 0줄이다.
- milestone은 isolated worktree task로 실행한다.
- reviewer는 `AMM_MODE=off`로 돌리고 memory MCP를 상속받지 않는다. role별 env 지원 여부는 [미확정]이다.
- bootstrap commit에는 task가 소유한 파일만 넣는다. worktree에 설계 입력이 필요하므로 research는 byte-identical 별도 commit으로 넣기를 권한다. 다만 **parent의 확인을 받은 뒤에** 한다.

## 7. 1–2주 trial hardstop과 cloud 계약

**순서**
- 0–2일: public·synthetic 자료만 쓴다.
- 이후: 개인 project를 쓴다.
- 회사 자료는 이번 trial 범위가 아니다. 별도 route 승인 뒤에만 다룬다.

매일 `amm doctor`와 `trial report`로 다음을 기록한다.
- startup과 turn당 rendered token, 추가 왕복 수, p50/p95 latency
- 승인·거절·false promotion, 중복·누락·blocked
- 철회 재구성 시간과 비용
- 후속 수정의 품질
- 운영에 든 시간

**즉시 중단하는 경우**
- binding이나 trust domain을 넘어 노출됨
- ack 이후 철회한 내용이 반환됨
- degraded 표시 없이 hook 경로에서 mandatory 규칙이 우회됨
- 승인되지 않은 egress가 관측됨
- watermark 불일치가 상태 표시 없이 발생함
- root 파일이 변경됨
- 선언한 RPO를 넘는 손실
- 중복 효과 발생

날짜만 채웠다고 통과로 보지 않는다.

**Cloud 진입 조건**
- local acceptance M1–M7과 hardstop 0건
- 같은 image digest, schema, policy
- 같은 단일 VM 구성에 TLS proxy와 SDK의 `token_verifier`/`AuthSettings`를 더하고, 암호화된 offsite backup과 개인 route를 둔다.
- legacy client는 sticky routing이 필요하다고 명시한다.
- 개인 corpus만 export/import하고 deletion head를 검증한다. **회사 corpus는 옮기지 않는다.**
- 지금 cloud를 provisioning하지 않는다.

## 8. 불확실성, peer가 공격할 질문, 선택을 바꿀 증거

**남은 불확실성:** 다음은 아직 확인하지 못했다.
- L9924 이후 reflect·refresh 코드
- recall이 observation의 based_on을 반환하는지
- tag 필터에 OR, 즉 "현재 branch ∨ 기본 branch ∨ branch 중립"이 가능한지
- trace를 끌 수 있는지
- Hindsight license
- 다국어 reranker 지원
- 설치된 host binary의 실제 negotiate 결과
- Codex fork 신호와 UPS replay

SIE는 round2 증거를 기다린다. pinned SIE MCP 패키지는 `mcp<2`라 edge로 쓰지 않는다. 다음 조건을 모두 만족할 때만 embedding·rerank의 HTTP 런타임 후보로 둔다.
- localhost에서 오프라인으로 동작한다.
- license 조건을 만족한다.
- Hindsight가 fork 없이 provider 설정으로 호출할 수 있다.

원격 `SIE_BASE_URL`은 egress로 취급한다.

**Peer 질문**
1. 문서를 delete하거나 invalidate하면 파생 observation과 mental model이 동기적으로 정리되는가? 그렇다면 binding 전체 재구성은 과잉 설계인가?
2. bank를 1:1로 나누면 internal background와 shared observation 예외가 정말 완전히 닫히는가? bank 안의 consolidation이 branch tag batch를 넘나드는 경로가 있는가?
3. coarse barrier로 생기는 가용성 손실이 normal prompt workflow에서 수용 가능한가? 아니면 처음부터 좁은 engine이 더 싼가?
4. PreToolUse deny 사유에 규칙 원문을 담는 방식이 Codex와 omp에서도 모델에게 그대로 보이는가? 길이 제한은 얼마인가?
5. per-prompt optional recall이 "의미 없는 context"인가? agent가 직접 호출하는 방식만 남겨야 하는가?
6. cluster 밖 deletion journal은 "단일 PG 권위" 원칙을 깨는가? 대안이 있는가?
7. amm의 결정적 signal 선택이 추출 품질을 떨어뜨리는가?
8. retract_request에 사람 확인을 요구하면 정정 루프가 너무 느려지는가?

**선택을 바꿀 증거**
- **좁은 PG engine 쪽으로 바꿀 증거**
  - 철회 재구성 시간이나 비용이 §3 trigger를 넘는다.
  - 한국어 eval이 baseline보다 낮다.
  - trace나 purge를 pin 고정 SQL 없이는 처리할 수 없다.
  - license나 오프라인 조건을 맞출 수 없다.
  - pin을 올리면 계약이 깨진다.
- **Hindsight 유지를 강화할 증거:** 동기적 파생 정리와 완전한 lineage가 source로 확인되면 barrier를 가볍게 줄인다.
- **queue 쪽:** lease와 fencing을 갖춘 PG 기반 job OSS가 확인되면 자체 outbox 대신 그것을 채택한다.
- **edge 쪽:** 설치된 host가 dual-era edge에 실패하면 같은 core 앞에 stdio shim만 추가한다.

이 문서의 모든 내용은 설계 판단이다. 구현, 테스트, native hook, 제품 동작은 아직 입증되지 않았다.