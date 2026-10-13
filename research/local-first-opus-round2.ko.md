# 2라운드 응답: Opus R1 작성자가 Codex R1에 반박하고 수정함

**요약 결론**

엔진 선택을 바꿉니다. **Hindsight는 runtime에서 빼고, amm이 PostgreSQL 하나 안에서 전체 의미 엔진과 job을 직접 소유합니다.** 이는 Codex R1의 핵심 선택을 받아들인 것입니다. 다만 Codex R1이 제안한 "inference 동안 shared advisory lock 유지"는 기각하고 durable admission ledger로 대체합니다.

세 범위 중 ③은 PR 전용이 아닙니다. 기본은 approver를 구성한 service ledger입니다.

이번 리뷰에서는 아무것도 실행·설치·테스트하지 않았습니다. 아래 설치 사실은 parent가 관측한 내용을 인용한 것입니다: AF 0.3.15 `0ffba881`의 private checkout, Colima `agent-memory-mcp`(2CPU/4GiB/30GiB, `--mount none`), PG·모델 미기동, unborn repo.

| 결정 | 선택 |
|---|---|
| 의미 엔진 | amm이 소유하는 단일 PG 엔진. 추출 → entity·시간·조건·부정 claim → consolidation → hybrid recall과 rerank → provenance graph → cited reflect → correction → next use |
| job 권위 | `amm.job` outbox 하나. 모델 runtime은 상태를 갖지 않는 executor |
| inference fence | DB lock을 쓰지 않음. admission row(DB clock 기준 deadline), commit CAS, delivery recheck를 binding clock row로 직렬화 |
| 규칙 | 선택지는 정확히 세 개. ③은 approver credential 기반 service ledger, Git authority는 대상별로 명시 선택 |
| context | MCP 결과는 text 한 plane. control 정보는 private API. 연결 시점 본문 0 |
| stack | Py 3.12, `mcp==2.3.0`, asyncpg, Alembic, PG18 + pgvector ≥0.8.7(project Colima), llama.cpp native(Metal), pg_dump+age, host 파일시스템 journal |
| 실행 | AF의 기존 development workflow를 쓰고 local handoff까지만. reviewer 두 개, 둘 다 xhigh |

## 0. 내 R1에서 바꾼 점

| R1 주장 | R2 | 바꾼 이유 |
|---|---|---|
| unforked Hindsight를 유일한 실행자로 두고 binding barrier로 통제 | **철회**, owned core로 전환 | `processing=0`이 quiescence가 아니고, amm은 엔진 내부의 LLM 입력을 fence할 수 없음(§1-1) |
| PG16 compose | PG18 + pgvector ≥0.8.7 | PG16은 Hindsight 정합 때문이었음. 그 제약이 없어졌고 보안 지원 기간이 더 김 |
| multilingual-e5-small, reranker 미정 | bge-m3 + bge-reranker-v2-m3 기본, KURE-v1 A/B. e5-small은 평가 후 저자원 fallback | storage 조사 결과 |
| binding 전체 barrier와 bank 재구성 | source 단위 `revoking`, admission drain, lineage 대상 cascade | binding 전체가 멈추는 비용 제거 |
| ③ = repo 파일과 PR merge가 정본 | service ledger + configured approver가 기본, Git은 명시적으로 선택할 때만 | Git 없이도 공유 승인이 가능해야 함 |
| ② = 같은 principal의 모든 binding | 명시적 project-set revision, trust realm 하나 | 미래 project나 고객사로 자동 확장되는 위험 |
| receipt가 있으면 재시도를 allow | `offered`와 `present`를 구분. 같은 ctx_gen에서 실제로 전달된 deny만 인정 | omp 재진입, Codex parent session id 공유, persist 미확인 |
| research를 byte-identical 별도 commit으로 권장 | **철회**. untracked 상태 유지 | 사용자 제약 |
| compose 안의 Hindsight와 egress proxy | PG만 Colima에 두고 amm과 llama.cpp는 native | 4GiB VM에서는 Metal을 쓸 수 없고, Hindsight도 제거됨 |
| retract_request의 사람 확인을 injection 방어로 설명 | 유지하되 G0로 이름을 바꿈 | same-UID 환경에서는 human presence를 증명할 수 없음 |

## 1. 쟁점별 판정

### 1-1. 엔진: Codex의 owned PG를 수용하고 내 barrier는 철회

내 barrier가 성립하려면 세 조건이 필요한데, 제공된 source로는 어느 것도 증명되지 않습니다.

**① quiescence가 증명되지 않음**

processing이 0이어도 다음 경우를 배제하지 못합니다.
- cancel은 cooperative라서 진행 중인 batch는 끝까지 씁니다(`http.py` L8061-8077).
- 취소 확인은 시작할 때 한 번이고, 조회에 실패하면 그대로 진행합니다(`memory_engine` L4505~).
- 완료 표시는 data commit과 다른 txn입니다(`poller` L885-899).
- orphan consolidation이 scope 불변식을 깹니다(`consolidator` L84-89).

정확한 quiescence는 **엔진 process를 정지하는 것**뿐입니다. 그러면 철회할 때마다 다음 순서가 필요합니다.
1. 엔진 전체 정지
2. worker-off 기동 모드로 다시 띄움(이 모드가 있는지 미확인)
3. 삭제
4. clear/rebuild(L9924 이후는 읽지 못해 미증명)
5. bank 전체 재통합(LLM 비용 발생)

**② 입력 fence가 불가능함**

엔진이 LLM을 process 안에서 호출하므로 amm이 admission 시점의 eligibility를 강제할 수 없습니다. epoch 전후 비교는 전달 단계만 막고, 내부 observation과 mental model의 오염은 막지 못합니다.

**③ bank 안에 eligibility 등급이 섞임**

bank 하나에 branch validity, human/AI 권위, 인용된 AI 로그, 주입 echo가 함께 들어 있습니다. tag는 consolidation batch만 나누고, internal background 작업은 scope 예외입니다.

따라서 normal path를 막으려면 검증되지 않은 control hook이 필요합니다. 교체를 "미래 trigger"로 미루지 않습니다.

Hindsight는 **reference로만** 씁니다. 참고할 아이디어는 content-hash replace, scope 사전 주입, 같은 scope로 batch 구성, merge 임계값, reflect의 반복·시간 상한입니다. packet에 license가 없으므로 코드는 복사하지 않습니다.

**Codex R1에 대한 반박:** Codex R1은 rerank, 시간 validity, entity 해소, 조건·부정 claim의 저장 형식, 대상 재통합 범위를 정하지 않았습니다. §3에서 이를 구체화합니다. 직접 만든 엔진의 품질 저하 위험은 그대로 남으므로 no-memory와 matched hybrid RAG를 baseline으로 평가합니다.

### 1-2. inference fence: Codex의 shared advisory lock 기각

session advisory lock은 DB 연결이 끊기면 풀리지만 provider는 계속 계산합니다. 그래서 "exclusive 획득 = drain 완료"라는 등식이 거짓이 됩니다. 대신 다음 계약을 씁니다.

- **`binding_clock(binding, ingest_seq, deletion_epoch, policy_epoch, rule_epoch)`**
  - 철회와 정책 변경은 이 행을 `UPDATE`합니다.
  - admission과 delivery recheck는 이 행을 `FOR SHARE`로 읽습니다.
  - 모두 짧은 txn입니다.
- **admission**
  - manifest의 모든 source가 tombstone이나 `revoking`이 아닌지 확인합니다.
  - `inference_admission(job_id, lease_token, manifest_digest, source_ids, deadline_at=now()+max_wall, state=admitted)`를 insert합니다.
  - gateway는 deadline보다 짧은 client timeout으로 연결을 끊습니다. provider 쪽 중단이나 삭제는 약속하지 않습니다.
- **철회의 linearization**
  - journal intent를 append하고 fsync합니다.
  - PG txn에서 tombstone을 `revoking`으로 바꾸고 `deletion_epoch++`합니다.
  - 이 commit 뒤의 admission, recall, recheck는 모두 그 source를 제외합니다. 새 읽기에서는 즉시 배제됩니다.
- **drain**: 그 commit 전에 admitted였던 해당 admission이 `returned/delivered/aborted`가 되거나, deadline이 지나 sweeper가 CAS로 `expired`를 기록할 때까지 기다립니다.
- **publication**
  - commit txn에서 `job.lease_token` 일치, generation 일치, admission `admitted→returned` CAS, 모든 source가 철회되지 않았는지를 확인합니다.
  - 0행이면 rollback합니다. 늦게 도착한 결과는 폐기합니다.
- **delivery**
  - 응답 직전 recheck txn에서 `delivered`를 기록합니다.
  - 철회 commit보다 앞서면 "철회 전 전달"로 기록하고 회수했다고 주장하지 않습니다.
  - 뒤라면 `CONTEXT_STALE`입니다.
- **`retracted` ack**
  - 조건: journal 내구성, 파생물 cascade commit, drain 완료.
  - 지연 상한은 최대 deadline(제안값: 추출 120s, reflect 300s)에 sweep 주기를 더한 값입니다.
- **DB 단절 시**: gateway는 publish도 deliver도 할 수 없으므로 안전한 쪽으로 실패합니다.

### 1-3. 팀 공유와 승인 경계: Codex 수용, 내 PR 전용안 철회

선택지는 **① 이 로컬 프로젝트, ② 내 프로젝트들, ③ 팀 또는 프로젝트 공유** 세 개로 고정합니다.

**②**
- operator가 만든 `project_set` revision(binding 목록, trust realm 하나)이 승인 digest에 들어갑니다.
- 새로 bind한 project는 자동으로 편입되지 않습니다. 사용자가 확인하면 새 revision이 만들어집니다.
- realm이 다르면 경고가 아니라 거부합니다.

**③**
- 대상(team/project)마다 approver와 authority mode를 등록합니다.
- 기본값 `service`: PG ledger가 정본이고, approver credential이 exact revision을 승인합니다. Git이 필요 없습니다.
- `git`: 명시적으로 선택한 대상에만 씁니다. 보호 branch에 merge된 파일의 digest가 정본이고 amm은 mirror만 합니다.
- service 모드의 repo export는 projection일 뿐 권위가 아닙니다.
- approver가 구성되지 않았으면 선택지를 비활성으로 두고 사유를 표시합니다.

**보장 등급**

| 등급 | 보장하는 것 | 보장하지 않는 것 |
|---|---|---|
| **G0**(현재 로컬) | agent token으로는 승인·publish·retract를 못 함. operator CLI가 digest를 보여 주고 확인을 받음 | same-UID agent가 shell로 CLI·token·Colima context를 쓰는 것은 못 막음. Keychain 확인창은 마찰일 뿐 보장이 아님 |
| **G1**(회사 ③ 필수) | amm·PG가 agent UID가 쓸 수 없는 별도 OS 사용자나 VM에서 동작하고, approver 서명 key가 agent UID 밖(FIDO2 touch 또는 IdP)에 있음. 또는 회사 branch protection을 쓰는 `git` 모드 | 이 조건이 없으면 회사 ③은 unavailable |

### 1-4. delivery receipt는 소비나 준수의 증거가 아님

상태는 `offered`(hook이 반환함)와 `present`(현재 ctx_gen 입력에 들어 있음이 확인됨) 둘뿐입니다. 준수 여부는 상태로 만들지 않습니다. 준수는 lint, CI, ACL의 몫입니다.

**ctx_gen key**
- 구성: (principal, binding, host, thread lineage, agent_path, gen)
- compact, resume, clear, fork 때 gen이 증가하고, child는 새 agent_path를 받습니다.
- Codex에서 parent `session_id`만 있고 `agent_id`가 없으면 receipt를 turn 단위로 좁힙니다. deny가 늘어나지만 잘못된 allow는 생기지 않습니다.
- omp는 `ctx.agent` chain을 씁니다. module-global 상태는 금지합니다.

**`present`로 인정하는 경우**
- (a) barrier의 deny 사유로 전달됐고, 같은 ctx_gen에서 재시도한 경우. Claude는 문서 근거가 있고 Codex와 omp는 실측 전까지 unknown입니다.
- (b) host가 transcript에 주입 context를 저장하고, 마지막 compact 경계 뒤에서 marker가 확인된 경우. 실측이 필요합니다.
- omp `before_agent_start`(최대 3회 재진입)와 Codex UPS 주입은 `offered`만 인정합니다.

**barrier 절차**
1. target path를 계산합니다(Write/Edit/apply_patch).
2. required rule의 적용 여부를 true/false/unknown으로 판정합니다.
3. `present`가 아니면 deny하고 본문, id/rev, marker를 함께 보냅니다.
4. unknown이면 `TARGET_UNRESOLVED`입니다.
5. Claude hook timeout은 fail-open이므로 `degraded`로 기록합니다.

**footprint를 알 수 없는 쓰기**(Bash, hosted tool, IDE)
- path 조건이 있는 required rule이 있으면 기본은 `block`입니다.
- 사용자가 `gap`을 고르면 허용하되 status에 표시합니다.
- 실행 전후 git digest로 미선언 쓰기를 찾는 것은 사후 탐지라고 명시합니다.

**normalizer 대응**
- schema에 `i`라는 필드 이름을 쓰지 않습니다.
- 빈 optional 값에 의미를 두지 않습니다.
- `local://`가 재작성된 뒤 realpath와 binding을 검사합니다.
- 변경 tool의 dedup은 인자가 아니라 server key로 합니다: (principal, binding, tool, payload digest, 10분 창).

### 1-5. context 비용

- agent MCP tool 네 개는 **outputSchema와 structuredContent 없이 text 하나만** 돌려줍니다. 첫 줄은 `amm status=… gen=… cov=…`입니다.
- control 정보와 receipt는 private API로만 보냅니다. 같은 fact나 rule 본문이 두 번 나가지 않습니다.
- mcp 2.3에서 text-only `CallToolResult`를 돌려줄 수 있는지는 wire 캡처로 확인합니다 [미확정].

**기본 예산 가정**(측정값이 아님)

| 항목 | 상한 |
|---|---|
| server instructions | ≤300자 |
| tools/list wire | ≤2 KiB 목표 |
| UPS 주입 | 기본 0 B, optional은 ≤3 item·2,400 B |
| `memory_context` | 기본 6 KiB, 최대 16 KiB |
| hook 주입 총량 | ≤6,000자. Claude는 10,000자, Codex는 약 2,500 token에서 파일로 넘어가므로 그보다 낮게 잡음 |

- required rule이 예산을 넘으면 `REQUIRED_CONTEXT_OVER_BUDGET`입니다.
- 기록은 세 가지를 따로 남깁니다: 최악의 경우 wire bytes(상한 합), 실제 wire bytes, host가 보고한 token. 추정치에는 `estimated:true`를 붙입니다.

### 1-6. OSS(상세는 §4)

- SIE는 Apache-2.0 패턴만 참고합니다. v1 FastMCP, 0.0.0.0 bind, 꺼진 보호, 정적 secret OAuth는 기각합니다.
- 공식 SDK 2.3(MIT) 하나로 edge를 만듭니다.
- PG job OSS는 finish·heartbeat를 id로만 처리하므로 outbox를 직접 만듭니다.
- 한국어 lexical 검색은 app의 bigram과 identifier 분해가 기본입니다. Kiwi는 model license를 확인하기 전까지 쓰지 않습니다.

### 1-7. Agent Flow

**workflow**
- 기존 development workflow를 쓰고 local handoff로 끝냅니다.
- push, PR, merge를 하지 않고, full delivery 후 forge 승인 대기 방식도 고르지 않습니다.
- 각 task의 완료 조건은 SPEC과 acceptance ledger(A1–A15)입니다.

**reviewer**
- AF review 단계에서 실제 CLI 두 개를 실행합니다.
  - Claude Code `claude-opus-5-5`, effort xhigh
  - Codex `gpt-6.1-sol`, `model_reasoning_effort="xhigh"`
- 설정은 AF project 설정에서만 합니다. core fork는 0입니다.
- AF 출력이나 receipt로 실제 적용된 model과 effort를 확인합니다. 설정할 수 없으면 조용히 낮추지 않고 gap으로 보고합니다.
- reviewer에는 amm MCP나 author memory를 상속하지 않습니다. AF가 role별 env를 지원하는지는 확인이 필요합니다.

**bootstrap**
- `git add <명시 경로>`로만 추가합니다. 대상은 다음과 같습니다.
  - `pyproject.toml`, `src/amm/__init__.py`
  - 자체 완결적인 `docs/spec/`(research는 경로와 sha256으로만 인용)
  - `.agent-flow/` 중 설치 receipt가 소유한 파일
  - `.gitignore`(research를 숨기지 않음)
- commit 전후에 research의 sha256과 `??` 상태가 바뀌지 않았는지 확인합니다.

**host trust**
- Codex hash와 Claude workspace trust는 사용자가 직접 실행합니다.
- doctor는 이 상태를 `pending_user_trust`로 보고합니다.
- AF hook 항목은 수정하지 않습니다.

### 1-8. 복구와 배포 profile

**journal**
- 위치: `~/Library/Application Support/amm/<deployment>/journal/`. VM disk 밖이고 0600, append-only, hash chain입니다.
- 본문과 평문 content hash를 넣지 않습니다. 넣는 것은 deployment key로 HMAC한 source identity, 범위, epoch, op id, 시각입니다. 경로도 HMAC합니다.

**head 판정**: PG의 `journal_applied(seq, chain)`과 journal head를 비교합니다.

| 상황 | 처리 |
|---|---|
| journal이 PG보다 앞섬 | 재적용 |
| journal이 뒤처지거나 chain 불일치 | `RESTORE_HEAD_UNVERIFIED`. rule plane을 포함한 모든 읽기를 닫고 보호 행동은 deny |
| 둘 다 과거로 돌아감 | 로컬에서는 탐지할 수 없음. 독립 head witness가 없으면 operator attestation이 필요하고 `head_witness=none`으로 표시 |

**restore candidate**: 별도 DB에 복원 → journal 재적용 → 불변식 검사 → 서비스를 닫은 상태에서 교체합니다.

**profile**

| profile | 의미 |
|---|---|
| `personal-local` | 현재 trial |
| `company-approved-route` | 회사 경계 안의 데이터, 승인된 route만 사용 |
| `strict-no-egress` | local weights만 사용. OS 수준 차단은 운영 조건 |

두 배포는 서로 독립이고 sync하지 않습니다.

**weights**
- operator가 `amm models fetch`를 명시적으로 실행할 때만 네트워크를 씁니다.
- manifest에 HF revision, sha256, SPDX, 변환기 버전을 기록합니다.
- runtime은 `HF_HUB_OFFLINE=1`, `--offline --no-webui --api-key-file`로 실행합니다.

**P0 운영**
- token rotate/revoke: token은 해시로 저장하고, 변경 commit 때 다시 검사합니다.
- spool: 상한은 256 MiB 또는 7일(제안값). 도달하면 capture를 멈추고 gap marker를 남깁니다.
- 철회된 source는 spool에서도 purge하고, flush 때 `rejected_tombstoned`로 처리합니다.
- backpressure는 status에 노출합니다.

## 2. 선택한 architecture, job 권위, API, identity

**Process 배치**
- **macOS host**
  - `amm`(Py 3.12 venv, launchd): MCP edge(127.0.0.1, dual-era), producer API(UDS 0600), worker tasks
  - llama.cpp 세 개(embed, rerank, gen): loopback과 api-key
  - journal, spool(stdlib sqlite3)
- **project Colima**: PG18 + pgvector 0.8.7 image(digest로 고정)
  - `127.0.0.1` publish
  - role: migrator, app, worker, readonly
  - builtin `C.UTF-8`
  - 명시적인 docker context만 쓰고 default VM은 건드리지 않습니다.

**Plane 구분**
- agent: MCP 네 개
- producer: capture, prompt context, barrier, lineage
- operator: CLI
- approver: G1 서명

**Identity 요소**
- deployment, trust_realm, principal(token)
- binding: operator alias. `realpath(git common-dir)` 또는 non-git path. unborn repo는 설치 시 만든 UUID를 incarnation으로 씁니다.
- workspace, code_snapshot(HEAD와 dirty digest)
- root_run, host_thread, agent_path, ctx_gen, turn/event/tool_call
- MCP session, request id, clientInfo는 identity가 아닙니다.

**Job 권위는 `amm.job` 하나**
- kind: `extract_segment`, `embed`, `consolidate_group`, `reflect`, `cascade_invalidate`, `reindex_manifest`, `purge`, `retention_sweep`, `restore_reconcile`
- `UNIQUE(kind, scope_key, idem_key)`를 이력 전체에 걸고, lease_token은 sequence로, generation도 함께 둡니다.
- heartbeat는 0행이 되거나 generation이 바뀌면 스스로 중단합니다.

**MCP tool**
- `memory_context(query, mode=recall|reflect, paths?, budget?)`
- `memory_inspect(ref)`
- `memory_record(note|candidate)`
- `memory_feedback(correct|reject|retract_request)`: retract는 operator가 확인하기 전까지 pending입니다.

**Operation 상태와 오류**
- 상태: `accepted→queued→running→succeeded | blocked | retry_wait | failed | cancel_requested | cancelled | superseded`. item마다 `semantic_ready`와 coverage를 둡니다.
- 오류: `BINDING_REQUIRED`, `IDEMPOTENCY_CONFLICT`, `MODEL_ROUTE_BLOCKED`, `CAUSAL_NOT_READY`, `CONTEXT_STALE`, `TARGET_UNRESOLVED`, `REQUIRED_CONTEXT_OVER_BUDGET`, `RESTORE_HEAD_UNVERIFIED`, `PERMISSION_DENIED`, `SERVICE_UNAVAILABLE`, `SCHEMA_UNSUPPORTED`
- `unavailable≠empty`, `partial≠complete`

## 3. 전체 semantic chain과 module·slice 계획

| 단계 | 메커니즘 | 불변식 |
|---|---|---|
| capture | 사전 결정적 필터: 주입 marker 제거, tool echo와 인용된 AI 로그는 non-human으로 표시, hidden CoT는 수집하지 않음 | event·receipt·outbox를 한 txn으로 commit. `accepted≠queryable` |
| 추출 | gen route에 JSON schema 지정. claim 필드: `kind`(fact, codebase_finding, preference, human_correction, investigation, rule_candidate, plan), subject/predicate/object, `polarity`, `modality`(asserted, uncertain, hypothetical, planned), `conditions[]`, `exceptions[]`, `valid_time`, `code_scope`, `evidence[{segment, quote}]` | quote가 NFKC 기준 substring인지 fail-closed로 검증. speaker는 envelope 값으로 덮어씀. human_source는 사용자가 입력한 원문에만 부여 |
| entity | identifier는 exact key, path는 repo 상대 경로. fuzzy 일치는 `possible_same` edge로만 남김 | binding을 넘는 자동 병합 금지 |
| index | NFKC → Hangul 음절 bigram + camel/snake 분해 + ASCII 단어를 `array_to_tsvector`·GIN으로. halfvec(1024) bge-m3 | `tokenizer_rev`와 embedding manifest가 다르면 함께 질의하지 않음 |
| consolidation | 같은 eligibility class(scope, authority, 호환되는 validity) 안에서 entity와 vector로 후보를 묶고 judge가 관계를 판정: duplicate, refines, contradicts, supersedes, conditional_variant, unrelated | 부정과 긍정을 합치지 않음. supersede는 더 늦은 valid_time이거나 human correction일 때만. observation lineage는 AND 그룹과 OR 대안으로 기록 |
| recall | eligibility SQL로 사전 필터 → lexical, exact vector(필터 안에서 수행하므로 ANN 후처리 손실 없음), entity 세 arm → RRF → bge-reranker로 top-30 rerank → contradicts/supersedes 1-hop 확장 → current/historical/other-branch 표시 | arm마다 status 반환. HNSW는 p95를 측정한 뒤에만 |
| reflect | 명시 mode에서만. manifest ≤12. 문장마다 cite. 검증: cite ⊆ manifest, 문장마다 1개 이상, 숫자·식별자가 인용문에 존재 | 결과는 candidate artifact. 1-2의 admission과 recheck 적용 |
| correction | 사용자 입력은 human_source. model의 `correct`는 ai_derived candidate. supersedes edge → lineage cascade → 영향받은 entity 그룹만 재통합 | AND 전제가 철회되면 observation 철회, OR 대안이 남아 있으면 유지 |
| next use | superseded는 historical로 표시, correction이 위로 올라옴. 반복 조사는 서로 다른 root_run 수로 셈(fork 상속분 제외). 거절 ledger는 새 근거가 있을 때만 재제안 | 의미의 결정성은 약속하지 않고, 상태와 권위의 불변식은 보장 |

**module**

```
src/amm/{domain, store(asyncpg, alembic), jobs(outbox, admission), journal, gateway(routes, llama.cpp),
 extract, entity, index, consolidate, recall, reflect, feedback, rules, context, edge(mcp, adapter_api, auth, cli), ops}
adapters/{claude,codex}(stdlib hook client)  adapters/omp(TS, ctx.agent)  eval/  deploy/
```

**Slice**(AF task, 의존 순서대로)

| slice | 내용 | acceptance |
|---|---|---|
| S0 | bootstrap, SPEC/ledger, AF reviewer 설정 | — |
| S1 | PG, migration, identity·binding, ingest·idempotency | A1, A9 |
| S2 | outbox, admission, journal, 철회 상태 기계 | A2 |
| S3 | gateway, route, weights manifest, llama.cpp | A13 |
| S4 | 추출, entity, index | A5 일부 |
| S5 | consolidation, provenance, cascade | A7 |
| S6 | recall, rerank, reflect, feedback | A3, A4, A5, A6 |
| S7 | MCP edge, auth, 예산 | A1(era 간), A12, A14 |
| S8 | rule plane | A9, A10 |
| S9 | host adapter 세 개 | A11 |
| S10 | ops(backup/restore, spool, doctor) | A8, A15 |
| S11 | AF consumer 연결, trial 계측 | — |

fake executor를 쓴 단위 테스트는 단위 테스트로만 표기하고 acceptance로 세지 않습니다.

## 4. OSS 채택, 참고, 기각

| 대상 | 판정 | 근거와 경계 |
|---|---|---|
| python-sdk 2.3.0 (MIT) | Adopt | dual_era, bearer_auth `TokenVerifier`, middleware, lifespan. Host wildcard는 prefix 비교라 exact allowlist를 씀. Origin이 없으면 통과하므로 token 필수 |
| SIE `sie_mcp` (Apache-2.0) | Reference | 가져올 것: frozen config와 clamp(기본값은 반대로), 추정·측정 분리, 입출력 상한, 근거 반환. 기각: v1, 0.0.0.0, 꺼진 보호, 정적 secret OAuth, raw token, fail-open 검증, user-scope 평문 secret, 전역 skills 복사. 코드는 복사하지 않음 |
| FastMCP 4.1 | Reject | 레이어 하나가 더 생김 |
| Hindsight | Reference | 아이디어만. license 미확인 |
| asyncpg (Apache) | Adopt | psycopg(LGPL)는 피함 |
| Alembic (MIT) | Adopt | `pg_advisory_xact_lock`, migrator role, forward-only |
| Procrastinate, PgQueuer, pgmq | Reference | `SKIP LOCKED` 패턴만. fence가 없음 |
| DBOS | Reject | — |
| PG18 + pgvector ≥0.8.7 | Adopt | IVFFlat 미사용 |
| pg_bigm | 2순위 조건부 | — |
| PGroonga, ParadeDB(AGPL), sqlite-vec | Reject | — |
| kiwipiepy | 보류 | model license 미확인 |
| llama.cpp (MIT) | Adopt | — |
| Ollama | 대안 | — |
| mlx-lm | Reject | — |
| bge-m3 (MIT), bge-reranker-v2-m3 (Apache) | Adopt | — |
| KURE-v1 (MIT) | A/B 후보 | — |
| Qwen3.5-9B Q4 (Apache) | 개인 trial의 local gen 후보 | 상향 경로는 35B-A3B Q4(약 21GB, 48GiB host에 들어감) |
| jina-v3 (NC), license `other` 모델 | Reject | — |
| pg_dump + age | Adopt(local) | — |
| pgBackRest ≥2.59.3, restic | 개인 VM에서 나중에 | — |

Python 런타임 의존성의 상한은 `mcp`(starlette, uvicorn, pydantic, httpx2 포함), asyncpg, Alembic과 SQLAlchemy입니다.

## 5. local acceptance, trial, cloud 조건

**A1–A15**: 실제 service, PG, local 모델로 실행합니다. 지금은 모두 미실행입니다.

- **A1**: 같은 key·digest면 같은 receipt, digest가 다르면 conflict. modern/legacy 응답이 유실된 뒤 replay해도 효과는 하나.
- **A2**: SIGSTOP으로 worker를 멈춤 → lease 회수 → 재개 후 commit이 0행.
- **A3**: 추출 도중 철회 → 해당 source를 포함한 publication 0건, 읽기에서는 즉시 배제, ack는 drain 이후.
- **A4**: reflect 전달과 철회가 경합 → "철회 전 전달" 기록 또는 `CONTEXT_STALE`. 두 경우 외에는 없음.
- **A5**: 한국어·영어 합성 fixture(부정, 조건, 예외, 시간 supersede, 2음절 어휘, `retry_backoff_ms`)에서 claim·관계 oracle 대비 품질 제안 임계값.
- **A6**: 정정 후 다른 host session에서 다음 사용 시 반영.
- **A7**: AND 전제 하나를 철회하면 observation이 철회되고, OR 대안이 있으면 유지.
- **A8**: 철회 전 backup으로 restore candidate를 만들어도 부활 0. journal을 삭제하면 `RESTORE_HEAD_UNVERIFIED`와 deny.
- **A9**: 미등록 cwd, set 밖 project, realm이 다른 편입 모두 거부.
- **A10**: cancel은 candidate만 남김. agent token으로 승인하면 거부. selector를 넓히면 재승인. root 파일 hash 불변.
- **A11**: host별로 새 path의 첫 Write는 deny, 같은 ctx_gen의 재시도는 allow, compact 뒤에는 다시 deny, omp UPS는 불충족, Bash는 block 또는 gap을 표시.
- **A12**: 연결 시점 wire bytes와 본문이 한 번만 나가는지, host 보고 token을 따로 기록.
- **A13**: route가 없으면 `MODEL_ROUTE_BLOCKED`와 `full_loop=unsupported`. 실행 중 외부 연결 관측(관측 한계는 명시).
- **A14**: token을 revoke하면 다음 요청과 진행 중인 commit이 거부됨.
- **A15**: spool이 상한에 도달하면 gap을 표시하고, 철회된 source의 flush는 거부.

**Trial**
- 처음 0–2일은 public·synthetic 자료만 쓰고, 그다음 개인 project로 넓힙니다. 회사 자료는 제외합니다.
- memory-on과 no-memory, matched RAG를 비교합니다.
- 기록: token, 왕복 수, p50/p95, 재처리 비용, false promotion, gap, 운영 시간.
- 즉시 중단: realm 노출, ack 뒤 부활, degraded 표시 없는 required 우회, 미승인 egress, 표시 없는 오류, root 변경, 중복 효과.

**Cloud 진입 조건**
- A1–A15를 통과하고 hardstop이 0건이어야 합니다.
- 같은 artifact, schema, 정책을 쓰고 TLS, `AuthSettings`, offsite backup, 개인 route를 더합니다.
- legacy client는 sticky가 필요합니다.
- 개인 corpus만 deletion head를 검증하면서 이전합니다. 회사 corpus는 옮기지 않습니다. 지금은 provisioning하지 않습니다.

## 6. 남은 실제 불확실성과 구현자 제약

**불확실성**
- Codex와 omp에서 deny 사유를 모델이 보는지, 그 길이 제한은 얼마인지
- Codex UPS 주입과 Claude transcript marker가 저장·확인되는지
- mcp 2.3에서 text-only 결과를 낼 수 있는지, stdio dual-era가 되는지
- `--ssh-config=false` 상태에서 Colima port forwarding이 되는지
- llama.cpp가 연결 단절 시 생성을 멈추는지
- Qwen3.5-9B Q4의 한국어 추출 품질. 가장 큰 제품 위험입니다.
- kiwipiepy_model과 e5-small의 license
- Time Machine이 VM disk와 journal을 어떻게 다루는지
- 설치된 host binary의 실제 era 협상 결과
- AF reviewer의 effort 설정과 role별 env 지원 여부

**구현자 제약**
- LLM 호출 동안 DB txn이나 lock을 잡지 않습니다.
- 모든 파생물 쓰기는 lease, generation, admission, tombstone CAS를 거칩니다.
- `amm.job` 외의 queue는 두지 않습니다.
- MCP 결과의 본문은 한 번만 내보냅니다.
- connection-time instructions, root 파일, 전역 skill에 본문을 넣지 않습니다.
- `offered`만으로 allow하지 않습니다.
- journal에 본문이나 평문 hash를 넣지 않습니다.
- 모델 route는 명시하고, fallback과 자동 다운로드는 금지합니다.
- G0를 human presence로 표기하지 않습니다.
- fake 결과나 SQLite 결과를 PG 제품 acceptance로 보고하지 않습니다.