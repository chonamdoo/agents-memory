**1라운드의 선택은 Python 서비스 + 단일 PostgreSQL 권위 + 직접 소유하는 좁은 의미 엔진 + 공식 Python MCP 2.3 단일 edge입니다.** 추출·통합·recall·reflect·정정은 하나의 durable job 체계가 소유합니다. Hindsight를 별도 엔진이나 비동기 projection으로 함께 운영하지 않습니다.

이는 기존의 “Hindsight 재사용 우선” 결론을 수정한 설계 판단입니다. 제공된 새 근거에서는 unforked Hindsight의 내부 작업·commit·철회 경계를 외부 authority만으로 통제하기 어렵습니다. 직접 구현하는 비용을 받아들이되, 제품을 수동 메모·규칙 검색으로 축소하지 않겠습니다.

아래는 구현 계약과 수용 기준이며, 이번 답변에서 설치·제품 실행·native hook 검증을 수행했다는 뜻은 아닙니다. 추가 SIE·OSS 조사 결과를 받은 2라운드에서 선택을 다시 검토합니다.

## 1. Hindsight를 기본 엔진에서 제외하는 이유

Hindsight의 retain/recall/reflect 재사용 이익은 분명합니다. 그러나 현재 요구는 검색 결과를 마지막에 걸러내는 수준보다 강합니다. **잘못된 출처가 내부 추론에 들어가지 않고, 늦은 작업이 철회 이후 새 파생물을 publish하지 않아야 합니다.**

제공된 고정 소스에서 다음 경로가 남습니다.

| 공격·실패 시나리오 | 외부 authority만으로 해결되지 않는 부분 | 사용자가 보게 되는 실패 |
|---|---|---|
| worker를 재할당했지만 이전 worker가 계속 실행 | 완료 조건에 worker 세대 fencing이 없음 | 철회하거나 정정한 사실이 다시 나타남 |
| 호출자에게 scope tag를 강제 | 내부 background 작업은 scope 제한의 예외 | 다른 범위의 근거가 통합·reflect에 섞임 |
| directive를 API에서 제한 | untagged directive가 적용되는 별도 경로 존재 | 승인하지 않은 지시가 답변에 영향을 줌 |
| shared observation 옵션을 잘못 허용 | tag를 넘어 untagged 파생 observation 생성 | 프로젝트 간 사실이 오염됨 |
| 근거를 삭제하고 결과만 검사 | 내부 합성은 이미 삭제된 근거를 사용했을 수 있음 | 출처 없는 결론이 정상 답변처럼 전달됨 |
| tombstone을 같은 cluster의 다른 schema에 보관 | 전체 cluster나 과거 volume 복원은 그 기록도 되돌릴 수 있음 | 오래된 backup에서 삭제 자료 부활 |

단일 worker는 동시 실행 가능성을 줄이지만 crash·재시작·취소·관리자 복구 이후 살아 있는 이전 실행을 배제하지 못합니다. `replace`와 content hash도 같은 본문 중복에는 도움이 되지만 승인 revision·source generation·삭제 epoch의 유효성을 대신하지 않습니다.

이를 고치려면 retain의 여러 transaction, consolidation, refresh, import, 삭제 경로를 함께 수정해야 합니다. 현재 자료로 이를 “작은 extension”이나 “싼 fork”라고 부를 근거는 없습니다. 다만 제공된 조사에는 큰 모듈의 일부 미열람 범위도 있으므로, **전체 Hindsight 코드에 대한 완전 감사 결과로 확대하지는 않습니다.** [엔진 근거](research/local-first-engine-evidence.ko.md), [고정 Hindsight 소스](https://github.com/vectorize-io/hindsight/tree/a9eeed77f9bce99d8f97d39a30d3281747300824)

직접 엔진을 선택하면 기존 semantic 품질과 성숙한 연산을 잃을 위험이 있습니다. 이 비용은 작은 schema나 짧은 코드로 상쇄됐다고 주장할 수 없습니다. 아래 전체 의미 동작과 비교 평가를 구현 완료 조건으로 둡니다.

## 2. 모듈 경계와 전체 의미 엔진

제품의 권위는 deployment별 PG에 하나씩 둡니다. 회사·고객·개인 deployment는 같은 schema와 연산 의미를 사용하지만 corpus·credential·모델 경로·backup을 분리합니다.

| 모듈 | 소유 책임 |
|---|---|
| `domain` | identity, binding, command, 승인, revision, 유효성, 상태 전이 |
| `storage` | PG transaction, provenance graph, 권한 있는 조회, migration |
| `jobs` | durable queue, lease, fencing, retry, 취소, operation receipt |
| `engine` | extraction, consolidation, retrieval, reflect, correction |
| `model_gateway` | 목적별 승인 route, 입력 유효성 검사, inference admission, 비용 |
| `rules` | 정확한 세 범위, selector, 승인 revision, 충돌·전달 판단 |
| `api` | MCP와 adapter/admin API를 같은 domain handler에 연결 |
| `adapters` | Claude/Codex/omp event 변환, lineage, capture, context 전달 |
| `ops` | installer, supervisor, doctor, backup/restore, 삭제 journal |

**추출과 통합의 유일한 작업 소유자는 `jobs`를 사용하는 제품 worker입니다.** 모델 runtime은 추론 요청을 실행할 뿐 job의 성공·재시도·최종 publication을 선언하지 않습니다. MCP나 native hook도 별도 background queue를 만들지 않습니다.

전체 chain은 다음처럼 구현합니다.

1. **Capture와 ingest:** user/assistant/tool event를 구분하고 source span·digest·coverage·snapshot을 보존합니다. 원문 저장과 후속 job 등록을 한 PG transaction으로 commit합니다.
2. **Extraction:** 사실, codebase finding, preference, human correction, investigation, rule candidate를 구분합니다. claim에는 부정, 조건, 예외, 잠정성, 적용 시점과 근거 span을 남깁니다. schema 통과를 사실성 검증으로 취급하지 않습니다.
3. **Consolidation:** 같은 권한·적용 범위와 호환되는 snapshot의 claims만 묶습니다. 반복·모순·대체·조건부 관계를 표현하고 원래 근거를 유지합니다. 같은 run의 중복 export를 반복 조사 횟수로 세지 않습니다.
4. **Recall:** 권한과 유효성이 확인된 집합에서 vector와 lexical 검색을 결합합니다. code identifier는 lexical 경로를 유지합니다. provenance의 support/contradict/supersede 관계를 제한적으로 확장해 단순 top-k 이상의 근거 연결을 제공합니다.
5. **Reflect:** 선택한 evidence manifest를 가지고 질문별 합성을 실행합니다. 문장별 citation을 요구하고 존재하지 않는 출처·revision을 거절합니다. citation 존재 검사는 의미적 entailment의 완전한 증명이 아닙니다.
6. **Correction:** 정정은 새 evidence이며 기존 claim과 적용 조건별 관계를 가집니다. 영향을 받는 파생물을 무효화하고 필요한 재추출·재통합을 같은 queue로 실행합니다.
7. **다음 작업의 재사용:** 새 run에서 수정된 근거가 선택되는지 확인합니다. 로그를 저장했다는 이유만으로 학습 효과를 인정하지 않습니다.

파생물에는 lineage를 필수로 둡니다. 하나의 결론에 필요한 여러 전제는 모두 유효해야 합니다. 대체 근거가 있는 경우에는 그 대체 관계를 명시합니다. 이를 표현하지 못하면 근거 하나가 철회돼도 보수적으로 파생물을 숨깁니다.

주입한 memory, tool echo, 이전 reflect는 독립 human evidence로 다시 세지 않습니다. 모델이 만든 결론은 자동으로 승인 규칙이나 새로운 사실 권위가 되지 않습니다. [전체 loop 요구](research/local-first-invocation-contract.ko.md)

## 3. API·상태·동시성 계약

Agent-plane의 도구는 다음 네 개로 고정합니다. producer capture, 승인, publish, migration, backup은 별도 권한의 API/CLI입니다.

| 도구 | 의미 |
|---|---|
| `memory_context` | bounded recall, 또는 명시적인 reflect operation 요청 |
| `memory_inspect` | 선택한 item의 근거·유효성, operation의 진행 상태 조회 |
| `memory_record` | 모델 출처가 명시된 note/candidate 기록 |
| `memory_feedback` | 정정·거절·철회 요청 제출 |

모델 payload의 `human`, `approved`, `team` 같은 필드는 권한을 만들지 못합니다. 승인·공유 publication은 검증된 approver credential과 exact revision으로만 처리합니다.

Operation은 `accepted → queued → running → succeeded`를 기본으로 하고 `blocked`, `retry_wait`, `failed`, `cancel_requested`, `cancelled`, `superseded`를 구분합니다. 별도로 `semantic_ready`와 coverage를 표시합니다. 원문 ingest가 성공해도 추출이나 embedding이 끝나지 않았다면 검색 가능하다고 응답하지 않습니다.

주요 오류는 다음 의미를 갖습니다.

- `BINDING_REQUIRED`: 허용된 project binding을 확정하지 못함.
- `IDEMPOTENCY_CONFLICT`: 같은 key로 다른 payload 제출.
- `MODEL_ROUTE_BLOCKED`: 해당 목적의 승인 모델 경로 없음.
- `CAUSAL_NOT_READY`: 요구한 ingest/processing 지점에 도달하지 못함.
- `CONTEXT_STALE`: 선택 이후 출처·권한·policy가 바뀜.
- `TARGET_UNRESOLVED`: 보호 행동의 적용 조건을 판단할 정보 부족.
- `REQUIRED_CONTEXT_OVER_BUDGET`: 필수 본문을 안전하게 전달할 수 없음.
- `RESTORE_HEAD_UNVERIFIED`: 최신 삭제 기록을 확인하지 못함.

같은 `(principal, binding, command, idempotency_key)`와 같은 digest는 같은 effect와 operation ID를 돌려줍니다. **철회 후 replay가 예전 본문까지 그대로 돌려준다는 뜻은 아닙니다.** receipt ID는 유지하되 현재 유효성과 상태를 다시 검사합니다. MCP request ID·transport session은 이 key를 대신하지 않습니다.

권위 watermark는 commit 순서가 보장되도록 짧은 transaction 안에서 잠그는 clock row로 발급합니다. 단순 sequence 번호를 commit 완료 순서로 간주하지 않습니다. ingest head, processing coverage, operation별 materialization 상태도 구분합니다.

Worker publication transaction은 반드시 lease token, 예상 source generation, 현재 permission/policy epoch, 삭제 상태, 모델·parser/index generation을 검사합니다. 늦은 worker는 계산을 마쳤더라도 commit할 수 없습니다.

**모델 호출 전 fence도 필수입니다.** 추출·embedding·rerank·통합·reflect 모두 다음 절차를 따릅니다.

- 현재 권한과 source 유효성을 검사한 immutable input manifest 생성.
- model gateway의 admission에서 causal minimum과 현재 epoch 재검사.
- 추론 이후 publication과 전달 직전에 다시 검사.

로컬 구현에서는 gateway가 trust-domain별 shared advisory lock을 inference 동안 유지하고, 최종 철회 완료는 exclusive lock으로 기존 실행이 빠져나간 뒤 선언하는 보수적인 방식을 선택합니다. LLM을 기다리는 DB transaction은 열어 두지 않습니다. 철회 요청은 먼저 `revoking`을 commit해 새 admission을 막고, 기존 호출의 취소·timeout·종료를 기다립니다.

이 방식은 철회 완료 지연이라는 비용이 있습니다. 이미 provider로 전송된 내용을 회수한다고 주장하지 않으며, drain이 끝나지 않았다면 최종 `retracted` ack를 반환하지 않습니다. [호출·일관성 계약](research/local-first-invocation-contract.ko.md)

## 4. project·branch·fork·compaction과 세 host

권한은 operator가 등록한 deployment/project binding과 credential에서 결정합니다. CWD·remote URL·bank name은 binding 조회의 단서이며 권한 자체가 아닙니다. 미등록 workspace를 개인 global memory로 fallback하지 않습니다.

Identity는 다음을 별개로 보존합니다.

- deployment, trust domain, principal, project;
- repository incarnation, workspace/worktree, code snapshot;
- root-run, host thread, agent, turn, event, tool call.

Branch 이름만으로 현재 code truth를 판단하지 않습니다. commit과 dirty 파일 digest 등 실제 dependency가 맞아야 현재 사실로 전달합니다. 확인할 수 없으면 historical/unknown입니다. Git이 없는 프로젝트도 등록할 수 있으며, unborn repository의 identity를 첫 commit hash에 의존시키지 않습니다.

Repository fork는 기본적으로 별도 project binding입니다. 반면 session fork는 같은 project 안의 새 context lineage입니다. 상속한 대화는 새 독립 관측으로 세지 않습니다.

| Host | Adapter의 핵심 처리 | 실제 검증이 필요한 부분 |
|---|---|---|
| Claude | UserPromptSubmit recall, PreToolUse deny, agent ID 분리, compact/resume 재평가 | hook 실패 차단 설정, replay된 오래된 context |
| Codex | prompt hook, tool deny, agent/thread lineage, capability별 wrapper | fork 식별, trust hash, hosted tool 사각지대 |
| omp | `before_agent_start`, `context`, `tool_call`, `ctx.agent`별 상태 | 재진입 dedup, parent MCP proxy와 child 분리 |

omp의 module-global 변수와 공유 MCP 연결에 delivery 상태를 저장하지 않습니다. Codex의 parent session ID도 child identity로 사용하지 않습니다. fork·compact·resume에서는 새로운 context generation을 발급하고 delivery receipt를 재평가합니다. 이미 전달된 본문은 삭제할 수 없으므로 긴급 철회 때는 보호 행동을 중단하고 새 context로 전환할 수 있어야 합니다. [host 근거](research/local-first-host-evidence.ko.md)

일반 prompt도 workflow와 같은 handler를 사용합니다. session 시작에는 memory/rule 본문을 보내지 않습니다. 실제 prompt가 들어오면 등록된 binding 안에서 필요한 recall만 수행합니다. phase/path가 없으면 unknown을 유지합니다.

Python 구현 가능성은 이미 제공된 실측으로 충분히 뒷받침됩니다. **Python 3.12 + 공식 `mcp==2.3.0` 하나의 HTTP edge에서 modern store, legacy read, autodiscover read, modern read가 같은 합성 자료를 처리했습니다.** 따라서 TypeScript 서비스나 두 개의 semantic core를 만들 이유가 없습니다. 다만 native 세 host의 실제 HTTP/stdio 연결은 별도 acceptance입니다. SQLite probe는 PG 제품 증거로 재사용하지 않습니다. [Python feasibility와 실제 wire 관측 범위](research/local-first-python-mcp-feasibility.ko.md), [공식 SDK dual-era 설명](https://py.sdk.modelcontextprotocol.io/run/legacy-clients/)

## 5. 정확한 세 활성화 범위와 최소 context

새 요청을 기준으로 선택지는 정확히 다음 세 개입니다. frozen proposal의 이전 범위 구분은 수정합니다.

1. **이 로컬 프로젝트** — 이 설치와 project binding에 적용. Git commit이나 팀 배포를 요구하지 않습니다.
2. **내 프로젝트들** — 같은 principal·trust domain에서 승인한 project 집합에 적용.
3. **팀 또는 프로젝트 공유** — 구성된 팀/프로젝트 approver가 승인한 revision을 공유 대상으로 publication.

`내 프로젝트들`은 개인·회사·고객 경계를 합치는 뜻이 아닙니다. 대상 project-set revision을 승인에 포함하고 새 대상 추가는 명시적으로 확인합니다. 공유 권한이 미구성인 경우에도 세 번째 선택지를 표시하되 활성화 불가 사유를 보여줍니다.

Candidate의 반복 횟수나 confidence는 승인 권한이 아닙니다. cancel·미응답은 candidate만 보존합니다. 승인에는 본문, selector, 예외, 대상, required 여부의 exact digest를 결합합니다. 범위 문자열이 같아도 적용 대상이나 조건이 넓어지면 새 승인이 필요합니다.

규칙의 정본과 활성 ledger는 PG가 소유합니다. export bundle과 host delivery cache는 projection입니다. 개인 규칙을 자동으로 팀에 배포하지 않고, root `CLAUDE.md`/`AGENTS.md`에 본문·목록·bridge를 추가하지 않습니다. 전체 catalog를 eager skill이나 `.omp/rules`로 옮기는 방식도 선택하지 않습니다.

Required rule selector는 `true/false/unknown`으로 평가합니다. 보호 행동에 적용될 가능성이 있는데 path나 phase를 모르겠다면 unknown을 false로 처리해 통과시키지 않습니다. `TARGET_UNRESOLVED`로 차단하고 조건을 해소합니다.

첫 새 path에서 필요한 규칙이 발견되면 다음 순서를 사용합니다.

- 현재 행동 deny.
- 필요한 원문과 revision을 모델에 전달.
- 이후 모델 호출과 새 행동에서 target·policy generation을 다시 검사.

Context를 붙인 최초 Write를 그대로 allow하지 않습니다. 동시에 이 절차가 자연어 규칙의 준수를 증명하지도 않습니다. 검사가 가능한 제약은 lint/검증기에, 보안은 ACL·sandbox에 맡깁니다.

임의 Bash·외부 IDE writer는 정확한 target footprint를 모를 수 있습니다. 해당 행동을 required-rule 지원으로 선언하려면 제한된 실행 wrapper로 footprint를 확인하거나, 가능한 필수 집합을 전달해야 합니다. 둘 다 불가능하면 차단합니다. native hook만으로 모든 writer를 포괄했다고 표시하지 않습니다.

Optional memory부터 예산을 줄이고 required 본문은 자르지 않습니다. 부족하면 작업 분할이나 중단입니다. 실제 렌더링된 token과 bytes를 측정하고, rule ID/revision·context generation별로 중복 전달을 줄입니다. 서버 cache가 prompt token을 없앤다고 계산하지 않습니다.

규칙 충돌도 scope별 임의 우선순위로 덮어쓰지 않습니다. 구조화된 충돌은 차단하고, 자연어 충돌은 검토 대상으로 표시합니다. 예외·supersedes 관계에는 해당 규칙을 변경할 권한이 필요합니다.

## 6. 삭제·복원·보안의 완료 의미

`retracted`, `physically_purged`, `backup_retention_complete`를 별도 상태로 둡니다. 삭제 범위에는 raw, claims, observations, embeddings, reflect, cache, spool, jobs, exports, projections가 포함됩니다. 외부 provider retention이나 이미 전달한 transcript까지 삭제했다고 표시하지 않습니다.

복원 방어를 위해 **본문 없는 deletion journal을 PG backup과 별도로 유지**합니다. 이는 검색 엔진이나 두 번째 job queue가 아니라 복원 시 넘어서는 안 되는 삭제 floor입니다.

삭제 요청은 권한·idempotency 검증 후 journal intent를 fsync하고 PG에 반영합니다. 두 저장소 사이 crash는 journal을 기준으로 보수적으로 reconcile합니다. 최종 삭제 ack는 journal 내구성, 파생물 차단, 진행 중 inference drain을 확인한 뒤 반환합니다. journal에는 source identity·삭제 범위·operation 식별자만 남기고 삭제 본문을 복제하지 않습니다.

같은 disk의 별도 파일은 PG volume 복원에는 도움이 되지만 전체 장치 손실을 해결하지 않습니다. **현재 deletion head를 확보하지 못한 전체 복구는 `RESTORE_HEAD_UNVERIFIED`로 읽기를 닫습니다.** 과거 backup 안의 서명된 기록만으로 최신성을 증명할 수는 없습니다. 독립 보관 매체가 필요한 재해복구 보장은 실제 운영 조건으로 남깁니다.

Restore는 service 비공개 상태에서 schema 복구, 최신 삭제 floor 적용, source/derived reconciliation, 오래된 job generation 폐기, 검증 순으로 진행합니다. binary rollback과 schema rollback도 분리합니다.

보안 경계는 agent, producer, approver, operator, migration 권한을 나눕니다. loopback에도 인증·endpoint identity·Host/Origin 검증을 적용하고 DB/operator credential을 agent에게 주지 않습니다. 같은 UID는 credential과 승인 도구를 읽을 수 있으므로 개인 로컬 승인 UI를 강한 인간 인증으로 표현하지 않습니다. 공유 환경의 강한 승인은 별도 OS identity·관리 환경·IdP 같은 실제 경계가 필요합니다.

모델 경로는 목적별 manifest로 allowlist하고 개인 provider env를 상속하지 않습니다. 승인되지 않은 fallback, 자동 weight 다운로드, telemetry는 허용하지 않습니다. 승인 route가 없으면 추출·reflect를 blocked로 표시하고 full 제품 지원을 선언하지 않습니다. [보안·복구 기준](research/local-first-invocation-contract.ko.md), [기존 경계 관측](research/unified-memory-pipeline-proposal.ko.md)

## 7. 설치, OSS 선택, Agent Flow 실행 단계

서비스 언어는 Python 3.12 계열, MCP는 실측한 공식 2.3.0을 초기 lock 기준으로 삼습니다. 저장소는 PostgreSQL + pgvector + pg_trgm, job은 같은 PG를 사용합니다. Redis·Neo4j·object store·두 번째 generic memory engine은 기본 구성에 추가하지 않습니다.

설치 후보의 역할은 다음처럼 제한합니다.

| 영역 | 1라운드 결정 | 추가 근거가 필요한 부분 |
|---|---|---|
| Protocol | 공식 Python SDK 한 edge | 세 native host와 stdio 실측 |
| Memory engine | 제품이 전체 의미 chain 소유 | Hindsight와 동일 조건 품질·유지비 비교 |
| Search | PG hybrid + 제한된 provenance 확장 | 한국어·identifier 검색 평가 |
| Durable jobs | PG lease/fencing, 하나의 lifecycle | crash·lease 탈취·취소 race 검증 |
| SIE | 기본 dependency 채택 보류 | 실제 engine 경계·저장·삭제·local runtime·license |
| Model runtime | 승인된 실제 route를 gateway로 연결 | hardware, weight/runtime license, 한국어 품질 |
| Backup/security | PG 복구 + 독립 삭제 floor + 권한 분리 | 전체 장치 복구와 배포별 인증 |

현재 SIE 자료는 pinned MCP package가 `mcp>=1.9,<2`이고 configured `SIE_BASE_URL`을 호출한다는 것까지입니다. 이를 local full engine의 증거로 쓰지 않습니다. 반대로 새 OSS 조사를 받기 전에 SIE의 검색·구조화 연산 재사용 가능성까지 배제하지도 않습니다. 모델 weight와 runtime license 역시 이번 입력만으로 확정하지 않겠습니다. 이 항목은 실제 모델 milestone의 차단 조건입니다. [SIE 고정 MCP 문서](https://github.com/superlinked/sie/blob/c571e0a75d804cb6d49795a99cd03ea901307a69/packages/sie_mcp/README.md)

설치는 product-owned venv·config·volume·supervisor를 만들고 기존 global host 설정을 덮어쓰지 않습니다. Colima daemon이 꺼져 있다는 사실은 readiness 실패로 명시합니다. native host trust는 별도 실제 승인 절차이며 installer가 자동 승인하지 않습니다. uninstall은 데이터 보존이 기본입니다.

Agent Flow는 제공된 main HEAD `0ffba881a0c3f1c20f41359f205ef4e517ed5482`의 별도 checkout으로 실행합니다. `pyproject`의 0.3.15 표기를 released version으로 확대하지 않고 기존 global 0.3.14를 교체하지 않습니다.

Unborn repo에는 task-owned bootstrap만 명시적으로 commit해 isolated worktree의 기반을 만듭니다. 기존 untracked research는 그대로 보존하며 `git add .`로 포함하지 않습니다. 그 이후 **Agent Flow가 아래 구현 계획을 실제 실행하도록 설정하는 것이 delivery 범위**입니다.

| 단계 | 구현 결과 | 완료를 인정하는 증거 |
|---|---|---|
| M0 | 계약, dependency/route lock, task bootstrap, Agent Flow plan/config | 사용한 checkout·plan·binding 확인 |
| M1 | PG domain, ingest, operation, job fencing | 응답 유실 replay, crash 복구, 늦은 commit 거절 |
| M2 | 실제 모델 기반 extract→consolidate→recall→reflect | 합성 corpus의 근거·조건·모순·후속 사용 |
| M3 | correction, forget, purge, restore | 파생 철회, spool replay, 오래된 backup 부활 차단 |
| M4 | Python dual-era MCP | 양 era가 같은 PG effect·revision 조회 |
| M5 | 독립 Claude/Codex/omp adapter | 일반 prompt·workflow·child·compact·fork 수용 |
| M6 | Agent Flow consumer 연결 | 실제 계획 실행과 동일 memory 의미 확인 |
| M7 | 1~2주 trial와 평가 | 사용 기록·품질·비용·장애에 근거한 판단 |

M2는 fake 모델이나 SQLite로 통과시킬 수 없습니다. Agent Flow 없는 세 host 실행을 먼저 확인하고 같은 adapter를 Agent Flow에 연결합니다. core/runner/installer 변경은 기본 0줄입니다. 격리 reviewer에는 author memory·MCP·credential을 자동 상속하지 않습니다. clean HOME만으로 보안 격리를 증명하지도 않습니다.

## 8. 로컬 완료, 실사용 hard stop, cloud 계약

로컬 완료는 모든 모듈이 존재한다는 뜻이 아니라 다음 행동을 관측했다는 뜻입니다.

- 공개 합성 자료의 정정이 추출·통합·reflect를 거쳐 다른 host의 다음 작업에 반영됨.
- 응답 유실·cancel·재시작·동시 client에서도 effect 중복과 stale publication이 없음.
- 새로운 path의 required rule이 첫 보호 행동을 차단하고 재계획 전에 전달됨.
- compact·resume·fork·child에서 context와 capture 중복·누락을 구분함.
- 다른 project/customer와 승인되지 않은 model route를 거절함.
- source 철회가 모든 파생물에 반영되고 과거 restore·spool replay로 부활하지 않음.
- source docs의 capability와 설치 binary의 실제 동작을 따로 기록함.

1~2주 trial은 synthetic/public 개인 프로젝트부터 시작합니다. 날짜만 채우면 완료가 아닙니다. coding, review, 조사, 일반 질문에서 no-memory와 동일 조건 hybrid/RAG baseline을 함께 비교합니다.

측정에는 실제 후속 수정 성공률, 근거 오류, false promotion, candidate 거절, capture gap, blocked 작업, startup/turn/recall token, roundtrip, p50/p95 latency, 모델 비용, 저장·운영 시간이 포함됩니다. 의미 출력의 동일성을 deterministic 기준으로 요구하지 않고, API 상태·권한·revision·출처 불변식과 의미 품질 평가를 분리합니다.

다음은 trial hard stop입니다.

- 회사·고객 데이터의 잘못된 경계 접근 또는 미승인 반출.
- 철회 자료나 규칙의 부활.
- 지원한다고 선언한 보호 행동의 required-rule 우회.
- 탐지되지 않은 capture gap 또는 project/child identity 혼선.
- 승인 없는 규칙 활성화.
- 영구 실패·디스크 부족·queue 정체를 성공이나 빈 결과로 숨김.

발견 시 자동화를 중단하고 데이터를 보존한 채 원인을 수정합니다. recall-only나 reflect-off로 바꾼 상태를 full acceptance 통과로 기록하지 않습니다.

Cloud는 지금 provisioning하지 않습니다. local acceptance와 trial을 통과한 같은 artifact/schema/operation 의미에 개인 VM의 TLS·인증·backup·approved route를 추가합니다. 이전 대상은 명시적으로 선택한 개인 corpus뿐입니다. 회사 corpus를 개인 cloud에 옮기지 않으며 single VM을 HA로 표현하지 않습니다.

## 9. Peer가 공격해야 할 7개 쟁점과 선택을 바꿀 증거

다음 질문에 대한 반박을 2라운드에서 받고 싶습니다.

1. **직접 엔진의 범위가 실제로 좁은가?** 조건부 claim·모순·통합·근거 reflect·정정까지 소유하면 Hindsight fork보다 유지비가 커지는 지점은 어디인가?
2. **Inference 동안의 shared lock이 과도한가?** 철회 지연을 줄이면서 admission 전 fence와 최종 ack 의미를 유지할 더 단순한 계약이 있는가?
3. **PG와 삭제 journal의 crash 상태가 빠졌는가?** journal intent 이후 PG rollback·응답 유실·전체 장치 복원에서 효과와 receipt를 어떻게 오라클로 검증할 것인가?
4. **Unknown selector가 정상 workflow를 지나치게 막는가?** 임의 Bash와 phase 미상 작업에 대해 요구를 축소하지 않는 현실적인 지원 경계는 무엇인가?
5. **`내 프로젝트들`의 대상 관리가 사용자 의도에 맞는가?** 명시적 project-set revision보다 동적 등록을 허용해도 승인 확대와 고객 경계를 통제할 수 있는가?
6. **Lineage와 citation 검사가 의미 오류를 충분히 드러내는가?** 한국어 부정·예외·간접 정정과 대체 근거를 어떻게 평가해야 하는가?
7. **SIE나 다른 OSS가 소유 경계를 줄여 줄 수 있는가?** 동일 job lifecycle, 사전 scope 검사, stale commit 차단, 파생 철회·restore를 보존하는 구체적 재사용 단위는 무엇인가?

다음 새 증거는 선택을 바꿀 수 있습니다.

- Hindsight의 **모든** 내부 합성·publication·import 경로에 적용되는 upstream fencing/eligibility 계약과 실제 stale-worker·철회·restore 통과 결과.
- SIE 또는 다른 OSS의 전체 의미 chain, local 실행, provenance·purge·restore, license가 확인되고 제품의 단일 작업 소유권과 충돌하지 않는다는 근거.
- 같은 corpus·모델·예산에서 직접 엔진이 Hindsight의 후속 작업 품질을 달성하지 못하고, Hindsight의 필요한 통제를 유지 가능한 범위로 구현할 수 있다는 비교 결과.
- 설치된 세 host의 실제 기능이 문서 계약과 달라 현재 adapter/barrier로 정상 workflow를 지원할 수 없다는 runtime 관측.

**현재 선택은 직접 소유하는 단일 PG 의미 엔진입니다. 그 선택을 방어하는 기준은 코드 크기가 아니라 전체 semantic loop와 철회·승인 불변식을 실행 가능한 경계에서 검증할 수 있는가입니다.**
