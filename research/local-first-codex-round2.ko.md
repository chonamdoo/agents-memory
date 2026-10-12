**최종 선택은 Python 3.12 + 공식 MCP SDK 2.3 단일 edge + PostgreSQL 18 권위 + 직접 소유하는 의미 엔진입니다.** 추출·통합·다국어 hybrid recall·rerank·근거 기반 reflect·정정·후속 재사용을 모두 구현합니다. Hindsight는 이번 제품의 실행 엔진에서 제외합니다.

Opus의 재사용 이익은 인정하지만, 제시한 zero-extension barrier는 필요한 입력 격리와 stale publication 방지를 증명하지 못합니다. 동시에 **제 Codex 1라운드의 추론 중 PG advisory lock도 폐기합니다.** admission, publication, 논리적 철회 ack, 로컬 drain을 서로 다른 계약으로 정의해야 DB 연결 단절에도 보장이 유지됩니다.

이번 답변은 상호 반박과 구현 계약입니다. 관측된 상태는 Agent Flow private 설치·프로젝트 설정 및 전용 Colima VM 준비까지이며, launcher에는 run이 없습니다. 제품 PG·모델·native adapter 실행이나 품질 통과를 주장하지 않습니다.

**(1) Opus 설계의 수용·반박과 제 1라운드 수정**

| Opus 1라운드 주장 | 판단과 수정 |
|---|---|
| project와 bank를 1:1로 만들면 internal scope 예외를 무력화한다 | **반박.** 고객 간 격리에는 도움이 되지만 한 project 안에도 branch, snapshot, 조건, 철회 상태가 다른 근거가 존재합니다. background 합성에서 부적격 근거를 사용한 뒤 historical 표시를 붙여도 입력 오염은 해결되지 않습니다. |
| `processing=0`을 기다리면 quiescent다 | **반박.** 작업 상태와 data commit은 별도이며 orphan consolidation·refresh·별도 읽기 실행의 종료를 증명하지 못합니다. 완료 상태에 실행 세대 fence도 없습니다. |
| barrier 뒤 delete→derived clear→rebuild로 안전하게 개방한다 | **반박.** 필요한 clear/rebuild API의 완전성, 모든 내부 writer 정지, uncited 입력의 lineage가 source로 확인되지 않았습니다. 제품의 필수 통제를 미확인 hook에 맡길 수 없습니다. |
| 직접 엔진은 entity·시간·한국어 검색·통합·reflect를 전부 구현해야 한다 | **수용.** “좁은 core”라는 표현을 구현 난도가 작다는 뜻으로 사용하지 않겠습니다. 아래 의미 chain 전체가 완료 조건입니다. |
| 공유 규칙은 기본 branch merge와 PR이 정본이다 | **수정.** 구성된 approver가 Git 없이 승인·publish할 수 있어야 합니다. 기본 정본은 PG이고 repo export는 projection입니다. |
| resume는 generation 유지, fork는 receipt 복사, deny 후 두 번째 시도 allow | **반박.** context 보존을 확인하지 못하면 새 generation과 빈 전달 상태가 필요합니다. receipt 작성만으로 재계획이나 모델 입력을 증명할 수 없습니다. |
| cluster 밖 본문 없는 journal, 승인된 route, 실제 PG 평가 | **수용.** 다만 journal hash chain은 최신 head의 존재까지 증명하지 않으며, spool 포화 시 무제한 보존도 불가능합니다. |

Hindsight의 scope 예외, fencing 부재, cooperative cancel, 별도 completion transaction, orphan·철회 문제는 제공된 [엔진 근거](research/local-first-engine-evidence.ko.md)와 [고정 source](https://github.com/vectorize-io/hindsight/tree/a9eeed77f9bce99d8f97d39a30d3281747300824)에 근거합니다. 이는 전체 코드에 대한 완전 감사라는 주장이 아닙니다.

Opus barrier를 실제 보장으로 만들려면 적어도 edge와 새 dispatch를 닫고, 모든 engine 실행 주체의 종료와 DB writer 접근 폐쇄를 확인하고, eligible manifest만으로 새 세대 저장소를 구성해야 합니다. 그래도 **평상시 project-bank 내부의 입력 eligibility 문제는 별도로 해결해야 합니다.** 단순 polling보다 훨씬 큰 격리·재구성 체계이며, 현재 zero-extension 안의 검증된 능력이 아닙니다. 따라서 이 경로를 구현의 기본으로 선택하지 않습니다.

제 1라운드에서 바뀐 점은 명확합니다.

- **추론 중 advisory lock 제거:** 연결 단절이 provider 실행 종료를 뜻하지 않기 때문입니다.
- **철회 ack와 drain 분리:** provider 종료를 기다려야만 논리적 삭제가 완료된다는 계약을 철회합니다.
- **context 출력 구현 구체화:** 자동 typed 반환에 맡기지 않고, 본문이 한 출력 plane에만 존재하도록 구성합니다.
- **OSS 보류 항목 확정:** PG18·보안 수정 pgvector, 자체 outbox, app bigram 검색, llama.cpp 기반 로컬 모델 경로를 초기 선택으로 정합니다.
- **Agent Flow workflow 확정:** local handoff에 맞는 development workflow를 사용합니다. full-delivery를 선택한 뒤 PR·merge 승인에서 인위적으로 멈추지 않습니다.

**(2) 선택한 권위·job·API·identity와 선형화 계약**

배포마다 PG authority 하나, worker lifecycle 하나, model gateway 하나를 둡니다. 회사·개인·서로 다른 고객은 독립 deployment입니다. gateway만 모델 route credential을 가지며 worker와 host adapter는 직접 provider를 호출하지 않습니다.

PG는 source revision, claim·provenance, rule approval, operation receipt, outbox, publication을 소유합니다. 외부 journal은 복원 시 지켜야 할 삭제·철회 floor만 소유합니다. 검색 엔진이나 두 번째 queue가 아닙니다.

자체 outbox는 claim·heartbeat·완료·retry 모두 `(job_id, lease_token, generation)`을 검사합니다. publication transaction은 lease 유효성, 현재 source revision, permission·policy·route revision과 모든 입력 dependency를 함께 검증합니다. 실패하면 결과와 다음 job 등록을 전부 rollback합니다. `SKIP LOCKED`만으로 이 보장이 생기지는 않습니다.

세 선형화 지점은 다음과 같습니다.

1. **Admission:** 짧은 PG transaction에서 현재 권한·출처·causal floor를 검사하고 immutable input manifest와 inference attempt를 기록한 commit입니다. 그 순간 유효한 입력에 대한 실행 허가입니다. 모델 호출 중 DB transaction이나 advisory lock을 유지하지 않습니다.
2. **Publication:** 추론 이후 현재 lease와 manifest 전체를 재검증하고 결과·receipt·후속 outbox를 함께 commit한 순간입니다. DB가 끊긴 동안 provider가 계속 계산해도, 재접속한 stale worker는 publication에 실패합니다.
3. **논리적 철회 ack:** 본문 없는 journal intent를 fsync하고, PG에서 source 철회·generation 증가·파생 eligibility 차단을 commit한 뒤 반환합니다. journal과 PG 사이 crash는 intent를 보수적으로 재적용합니다. 이 ack 이후 선형화되는 읽기·admission·publication은 철회된 근거를 사용할 수 없습니다.

권위 변경은 같은 deployment clock row를 짧게 잠가 순서를 부여합니다. 단순 sequence 값을 commit 순서라고 간주하지 않습니다.

**Admission 전에 유효했던 입력과 철회 이후 유효한 입력은 다릅니다.** 먼저 admitted된 요청은 철회 후에도 provider에서 시작되거나 계속 실행될 수 있습니다. gateway는 미제출 요청을 폐기하고 제출 직전 재검사하지만, DB commit과 외부 provider 수신을 하나의 원자적 사건으로 만들 수는 없습니다.

따라서 상태를 분리합니다.

- `retracted`: 새 유효 읽기·admission·publication이 차단됨.
- `local_drained`: 소유한 미제출 queue·본문 buffer·실행 callback이 정리됨.
- `provider_completion_unknown`: 외부 실행 종료를 확인하지 못함.
- `physically_purged`, `backup_retention_complete`: 별도 삭제 완료 단계.

로컬 drain이 멈추면 bounded timeout 후 소유 process를 종료하고 실제 exit를 확인하거나 `DRAIN_PENDING`을 유지합니다. socket close나 task cancel을 provider erasure라고 보고하지 않습니다. 먼저 선형화된 응답이 네트워크 지연으로 ack 뒤 도착할 수도 있으므로 응답 stamp를 보존하고 보호 행동에서 최신 generation을 다시 검사합니다.

Agent-plane 도구는 네 개입니다.

| 도구 | 역할 |
|---|---|
| `memory_context` | bounded recall 또는 명시적 reflect operation |
| `memory_inspect` | item 근거·유효성 또는 operation 상태 |
| `memory_record` | 모델 출처의 note·candidate |
| `memory_feedback` | 정정·거절·철회 요청 |

Capture·approval·publish·backup·migration은 별도 인증 endpoint입니다. 모델 payload의 `human`·`approved` 값은 권한이 되지 않습니다.

Idempotency는 `(principal, binding, command, key)`와 canonical payload digest에 결합합니다. 같은 key의 다른 digest는 conflict입니다. replay는 같은 operation을 가리키지만 철회된 과거 본문을 다시 반환하지 않습니다. `accepted≠queryable`, `unavailable≠empty`, `partial≠complete`를 유지합니다.

Identity는 deployment·trust realm·principal·project binding과 host thread·agent instance·context generation을 분리합니다. CWD·remote·branch·MCP session은 권한 근거가 아닙니다. unborn·비Git 프로젝트도 등록 UUID로 지원하며 미등록 binding은 오류입니다. [호출 계약](research/local-first-invocation-contract.ko.md)

**(3) 전체 의미 chain, 규칙·host·context 구현**

실제 모듈 경계는 다음과 같습니다.

- `amm/domain`, `store`, `jobs`: command·상태·PG schema·receipt·lease·publication.
- `amm/capture`: event envelope·source identity·span·coverage·spool.
- `amm/engine/{entities,claims,extract,consolidate,retrieve,reflect,correct}.py`.
- `amm/model_gateway`: route manifest·admission·attempt·drain·비용.
- `amm/rules`, `context`: exact approval·selector·충돌·전달 상태·예산.
- `amm/edge`, `adapters/{claude,codex,omp}`, `amm/ops`: transport·host lifecycle·설치·복구.

의미 chain을 다음처럼 구현합니다.

1. **Capture·추출:** user·assistant·tool·인용문·주입 memory를 구분합니다. claim에는 entity, predicate/value, polarity, 조건·예외, 유효 기간, event time, 잠정성, snapshot dependency, evidence byte span을 저장합니다. 원문 substring 검사는 근거 존재를 확인할 뿐 entailment를 증명하지 않습니다.
2. **Entity·시간:** entity는 project namespace 안에서 관리하고 ambiguous alias를 자동 병합하지 않습니다. 기록 시각과 사실 유효 시각을 구분합니다. branch 이름만으로 현재 사실을 선언하지 않고 commit·dirty dependency digest를 검사합니다.
3. **Consolidation:** 권한·branch/snapshot·조건·시간이 호환되는 claim만 묶습니다. duplicate, supports, contradicts, supersedes 관계를 유지합니다. 서로 다른 조건의 주장이나 부정문을 다수결로 지우지 않습니다. 동일 run의 여러 export는 반복 조사 한 번입니다.
4. **Recall:** eligible 집합에서 exact vector와 lexical 후보를 구한 뒤 RRF로 합치고 bounded rerank합니다. 한글 음절 bigram, 원문 단어, camel/snake 분해와 exact identifier 경로를 사용합니다. 정규화 검색값과 실제 코드 식별자를 별도로 보존합니다.
5. **Provenance·reflect:** PG edge table로 제한된 support·contradiction 확장을 수행합니다. reflect는 현재 검증된 manifest만 받아 문장별 citation과 불확실성을 반환합니다. 사용한 전체 입력을 dependency로 남기므로 인용하지 않은 오염 입력도 철회 대상입니다. 결과는 grounded candidate이며 rule authority가 아닙니다.
6. **Correction·next use:** 정정은 적용 조건이 있는 새 evidence입니다. 영향받은 claim·통합·reflect를 숨기고 같은 queue로 재처리합니다. 다음 독립 task에서 수정 근거가 선택되는 것까지 acceptance에 포함합니다.

대체 근거가 있다고 철회된 입력으로 생성한 문장을 그대로 살리지 않습니다. 해당 문장의 독립 근거가 확인되거나 재생성되어야 합니다. schema 통과·citation 존재·높은 confidence는 사실성이나 승인을 대체하지 않습니다.

규칙 활성화 선택지는 정확히 유지합니다.

1. **이 로컬 프로젝트**
2. **내 프로젝트들**
3. **팀 또는 프로젝트 공유**

`내 프로젝트들`은 승인 당시의 **유한한 project ID 집합과 target-set revision**입니다. 미래 프로젝트 추가에는 새 동의가 필요하고 다른 고객·trust realm으로 자동 확대하지 않습니다. 공유 규칙은 구성된 approver가 Git 없이 PG에 publish할 수 있습니다. Git authority를 명시적으로 선택한 ruleset에서만 repo를 정본으로 삼으며 두 정본을 병행하지 않습니다.

본문·selector·예외·target set·required 여부를 exact approval digest에 결합합니다. cancel·미응답은 candidate만 남깁니다.

같은 UID의 unrestricted agent가 operator credential과 CLI를 사용할 수 있다는 한계는 유지합니다. 개인 로컬 역할 분리는 우발적 오용을 줄이는 보장입니다. 회사 공유 승인은 별도 관리 identity·approver device·IdP와 exact revision에 결합된 승인 절차로 처리합니다. 필요한 경우 hardware user verification을 요구하되, MCP 역할만으로 인간 현존이나 모든 agent 우회를 증명한다고 하지 않습니다.

**First-action 상태는 receipt와 분리합니다.** 지원 adapter는 다음 순서를 확인합니다.

`행동 deny → 필요한 원문 전달 → 후속 model-input generation 관측 → 그 generation의 새 행동 재검사`

hook이 receipt를 썼거나 모델이 “읽었다”고 답했다는 이유로 allow하지 않습니다. 자연어 준수는 여전히 증명할 수 없으며 검사 가능한 제약은 validator·lint로 집행합니다.

Resume·compact·fork·child에서 context 보존이 확인되지 않으면 generation을 증가시키고 전달 상태를 비웁니다. Codex parent session ID만 쓰지 않고 thread·agent를 구분합니다. omp는 `ctx.agent`별 상태를 사용하고 `before_agent_start` 재진입·cache warming·provider retry를 새 소비 증거로 세지 않습니다. 실제 후속 입력·assistant 행동 순서를 노출하지 않는 host 경로는 `CONTEXT_GENERATION_UNVERIFIED`로 표시하고 strict 보호 행동을 차단합니다.

Bash·IDE·hosted tool의 footprint를 모르면 coverage gap입니다. managed wrapper로 footprint를 제한하거나 해당 행동을 차단하며, native hook만으로 전체 writer를 덮었다고 하지 않습니다. [Host 근거 F4–F11](research/local-first-host-evidence.ko.md)

Host normalizer에 취약한 `i` 필드를 사용하지 않습니다. 필요한 handle·operation key는 비어 있지 않은 required 필드로 두고, `local://` 변환 전후 경로를 등록 workspace와 검사합니다. Optional 생략·default 정규화는 idempotency digest 계약에 포함합니다.

**Context 출력은 본문 한 plane으로 고정합니다.** 연결 시 server instructions와 corpus/rule 본문은 0이며 네 도구의 작은 catalog만 존재합니다. MCP는 직접 구성한 `CallToolResult`의 text content에 본문을 넣고 `structuredContent`에는 작은 stamp·상태·참조만 넣습니다. SDK의 자동 typed 반환으로 같은 본문이 양쪽에 복제되게 두지 않습니다. Private adapter의 control 정보도 model text에 넣지 않습니다.

초기 운영 가정은 optional 최대 3개·600 rendered tokens, 요청 전체 2,000 rendered tokens입니다. 이는 실측 성능이 아닙니다. Tokenizer가 확인되지 않은 host는 byte 예산을 우선 사용합니다. 직렬화 JSON-RPC body 16KiB 상한을 별도로 검사하고 transport framing을 포함한 실제 wire bytes도 기록합니다. Required 본문이 예산이나 host 전달 한도를 넘으면 optional 제거 후 split·block하며 문장 중간을 자르지 않습니다. 실제 host가 두 출력 plane을 렌더링한 token과 추정 token은 별도 지표입니다. [출력·SDK 근거](research/local-first-sie-protocol-oss.ko.md)

**(4) OSS 채택·참고·제외의 경계**

| 구성 | 이번 선택 |
|---|---|
| 공식 Python MCP 2.3, MIT | **채택.** dual-era·lifespan·TokenVerifier 예시를 기반으로 한 edge. Legacy와 modern은 같은 handler 사용. |
| PG18 + pgvector ≥0.8.7 | **채택.** 검증한 image digest·extension version으로 lock. Hindsight의 PG16 제약은 가져오지 않음. |
| asyncpg, Alembic | **채택.** asyncpg 기반 migration 연결과 명시적 migrator lock. 앱 시작 자동 migration 금지. |
| Procrastinate·PgQueuer·pgmq | **참고.** claim·retry 패턴만 참고하며 finish·heartbeat의 세대 fence를 제품 권위로 믿지 않음. |
| SIE, Apache-2.0 | **패턴 참고.** 결과 상한·근거 passage·추정/측정 분리. v1 FastMCP 배선, bind·OAuth·credential 기본값은 채택하지 않음. |
| Kiwi | **초기 dependency 제외.** 모델 패키지 라이선스 미확정. app bigram·identifier 검색으로 시작하고 품질 평가. |
| llama.cpp, BGE-M3·BGE reranker | **초기 로컬 경로 채택.** runtime·weight·변환 artifact를 각각 pin하고 실제 호환성 검증. |

SIE의 `mcp>=1.9,<2`, FastMCP import, 기본 `0.0.0.0` bind와 비어 있는 allowlist의 rebinding 보호 해제는 공식 SDK2 foundation으로 사용하지 않는 이유입니다. Apache 코드 복사 시 고지·변경 표시를 보존합니다. 이번 선택은 SIE 서비스나 전체 패키지를 dependency로 넣는 안이 아닙니다. [SIE 고정 source](https://github.com/superlinked/sie/tree/c571e0a75d804cb6d49795a99cd03ea901307a69), [공식 Python SDK](https://github.com/modelcontextprotocol/python-sdk/tree/2118f14f8a19bc158d8a1cf90af58d85d187f849)

검색은 eligible subset의 exact scan으로 시작합니다. ANN은 필요성과 scope-filter recall을 측정한 뒤 도입합니다. Token overlap을 BM25라고 부르거나 `array_to_tsvector`에 없는 position 정보를 있다고 가정하지 않습니다. [pgvector source](https://github.com/pgvector/pgvector/blob/f37c13f68b57d2c3472b2214fbcff699d6d34876/README.md)

현재 48GiB host의 초기 모델 조합은 **BGE-M3 + bge-reranker-v2-m3 + Qwen3.5-9B Q4 생성 후보**입니다. PG는 준비된 전용 Colima VM에, 모델 runtime은 host에 둡니다. 4GiB VM 안에 전체 모델을 넣지 않습니다. E5-small은 비용 절감 비교 후보이며, 품질 평가 없이 자동 fallback하지 않습니다.

모델 SHA·원본 라이선스·GGUF 변환 도구·변환 hash·pooling·차원·정규화를 manifest에 기록합니다. 런타임은 offline·web UI off·자동 다운로드 및 telemetry off로 구성합니다. 실제 모델 호환성과 한국어 품질은 아직 미확정입니다. Team 구독을 background 생성 API 허가로 해석하지 않으며 native CLI·HTTP route도 목적별 승인이 필요합니다. [모델·운영 OSS 근거](research/local-first-storage-ops-oss.ko.md)

**(5) Agent Flow 구현 순서, 로컬 acceptance와 trial**

설치된 private Agent Flow `0.3.15 / 0ffba881`와 Python profile·local architecture contract를 사용합니다. Global 0.3.14는 유지합니다. **Development workflow로 실제 local handoff를 수행하며 AF core fork는 없습니다.** Full SPEC과 acceptance ledger는 workflow 선택과 무관하게 필수입니다.

첫 bootstrap commit에는 SPEC·ledger·프로젝트 설정 등 task-owned 파일만 명시적으로 포함합니다. 기존 untracked research는 bulk commit하지 않습니다. Isolated worktree에 필요한 frozen packet은 hash가 있는 명시적 run input으로 전달합니다.

| Slice | 구현과 필수 증거 |
|---|---|
| S0 | SPEC·API·schema·권한·route·acceptance ledger, bootstrap, AF run 구성 |
| S1 | 실제 PG ingest·receipt·outbox·clock·lease; 응답 유실 replay와 stale heartbeat/commit 거절 |
| S2 | gateway admission·publication·drain; DB 단절 중 provider 지속, 철회 경합, route revoke |
| S3 | 실제 capture·entity/claim 추출·embedding·lexical; 한국어 부정·조건·시간·identifier fixture |
| S4 | consolidation·hybrid recall·rerank·grounded reflect; 모순과 uncited dependency 철회 |
| S5 | correction·purge·restore journal; old backup·spool replay·source reimport 부활 차단 |
| S6 | 동일 PG core의 MCP 양 era·rules·bounded 출력·exact approval·target-set 변경 |
| S7 | Claude/Codex/omp 일반 prompt·workflow·child·resume·compact·fork와 first-action gate |
| S8 | AF consumer E2E·독립 review·local handoff 후 1–2주 trial |

S3–S5는 실제 모델과 PG로 통과해야 합니다. Mock·SQLite probe·reflect-off 결과는 product acceptance를 대신하지 않습니다. Agent Flow 없이 세 host의 지원 경로를 먼저 검증하고 같은 adapter를 AF consumer에 연결합니다.

**두 독립 native reviewer는 AF review phase에서 실제 실행해야 합니다.**

- Codex: `gpt-6.1-sol`, `model_reasoning_effort="xhigh"`.
- Claude: `claude-opus-5-5`, `--effort xhigh`.

동일 SPEC·diff·acceptance evidence를 freeze/hash해 전달하고 서로의 답변과 author memory를 상속하지 않습니다. 요청 설정, 실제 banner/response, exit, 입력·출력 hash를 기록합니다. 설정 전달과 provider 내부 effort 증명은 구분합니다. 정확한 AF 설정 필드는 설치된 pin에서 확인해 사용해야 하며, 이번 리뷰에서 두 CLI를 새로 실행했다는 뜻은 아닙니다.

Native hook trust는 실제 host 승인이 필요할 수 있습니다. `hooks=true`나 installer exit 0을 trust·실행 성공으로 보고하지 않습니다. 미승인 경로는 blocked/unknown으로 남기되 독립 PG·engine 구현과 검증은 계속합니다.

Trial은 public/synthetic 개인 자료부터 시작합니다. 날짜보다 다음 관측이 중요합니다.

- 다음 task의 정정 재사용, 근거 오류·조건 누락·false promotion.
- No-memory 및 같은 corpus·모델·예산의 hybrid baseline과 비교.
- 실제 rendered tokens·wire bytes·roundtrip·latency·비용·운영시간.
- Capture gap·queue 정체·blocked 행동·후속 수정 결과.

경계 누출, 미승인 egress, 철회 부활, 승인 없는 활성화, 선언한 보호 행동 우회, 숨겨진 capture gap은 hard stop입니다. Cloud provisioning은 local acceptance와 trial 이후이며 개인 corpus만 명시적으로 이전합니다.

**(6) 운영 P0, 남은 불확실성과 구현자 제약**

Restore-floor journal은 PG volume 밖에 둡니다. 본문 없이 source·rule·credential 철회 식별자, operation·epoch·최소 audit metadata를 기록합니다. Journal intent만 durable한 crash도 재적용하며 reconciliation 전 읽기를 닫습니다. **Hash chain 검증은 최신성 검증이 아닙니다. 최신 head를 잃거나 신뢰할 수 없으면 `RESTORE_HEAD_UNVERIFIED`로 개방하지 않습니다.** 같은 장치의 파일은 전체 장치 손실 보장이 아니므로 필요한 독립 checkpoint를 해당 trust realm 안에 운영해야 합니다.

Operator P0에는 token rotate/revoke, offline spool 복구·격리, candidate queue 검토, retry exhaustion·dead-letter 처리, 디스크·queue backpressure가 포함됩니다. Bounded spool이 가득 차면 capture 수락을 중단합니다. Host를 멈출 수 없다면 정확한 gap 구간을 기록하고 full capture 완료로 표시하지 않습니다. Append-only audit에 삭제 본문을 복제하지 않습니다.

회사 profile은 구분합니다. 회사 밖 memory 저장을 금지하면서 승인된 모델 처리를 허용하는 profile과 **strict no-egress** profile은 다릅니다. 후자는 coding host를 포함한 모든 추론과 artifact를 승인된 내부 환경에서 실행해야 합니다. No-training 약속은 no-storage나 no-egress 증명이 아닙니다. 회사 local과 이후 개인 cloud는 같은 계약의 두 독립 배포이며 company sync 기능이 아닙니다.

남은 실질적 불확실성은 로컬 모델의 한국어 의미 품질·runtime 호환성, installed native host의 관측 가능한 입력 순서와 전달 한도, 실제 context 비용, 전체 장치 복구용 최신 head 보관 방식입니다. 이를 문서 capability나 모델 크기로 통과 처리하지 않습니다.

후속 구현자는 제공된 [architecture skill](.agent-flow/local-skills/architecture/SKILL.md)을 적용하고, 위 slice를 **실제 Agent Flow run과 acceptance ledger로 완료해야 합니다.** 현재 상태의 완료 표시는 설치 준비까지입니다. 전체 의미 engine과 로컬 full loop 실행은 여전히 필요한 작업입니다.
