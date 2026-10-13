# agents-memory

실제 local 모델·PG·native host·복원 검증과 보장의 한계: [검증 기록](docs/verification.ko.md). 요구 계약과 cloud 전환 조건은 [설계](docs/architecture.ko.md)를 따른다.

Python 3.12 기반의 독립적인 로컬 메모리 서비스. Agent Flow는 선택 사항이다. Claude Code, Codex, OMP, 일반 MCP client와 CLI가 같은 인증·project binding·메모리 core를 사용한다.

- 정본: PostgreSQL 18 + pgvector. lexical/vector/entity 후보를 합치고 실제 BGE cross-encoder로 rerank한다.
- 의미 처리: 승인된 로컬 Qwen3.5-9B, BGE-M3, BGE reranker. 자동 다운로드·외부 provider fallback 없음.
- 파이프라인: capture → extract/embed → consolidate → recall/rerank → cited reflect → correction/retraction → 다음 호출.
- MCP: 공식 Python SDK `mcp==2.3.0`. `2026-07-28` stateless 호출과 기존 `2025-11-25` client가 같은 handler를 사용한다. stdio는 인증된 loopback HTTP 중계이며 별도 DB/메모리 engine이 아니다.
- 연결 시 instructions·corpus·규칙 본문은 비어 있다. 도구는 `memory_context`, `memory_inspect`, `memory_record`, `memory_feedback` 네 개다. 선택 결과가 없으면 context 본문도 빈 문자열이다.

[설계](docs/architecture.ko.md) · [요구·불변식](docs/requirements.ko.md) · [구현 API 계약](docs/implementation-plan.ko.md)

## 설치와 로컬 authority

```sh
uv sync --locked --extra local-models
uv run agents-memory --help
```

PG는 전용 database/schema로 준비한다. migrator/owner와 non-DDL app role을 나누고, owner의 기본 ACL로 app의 table SELECT/INSERT/UPDATE/DELETE 및 sequence USAGE/SELECT를 허용한다. `vector` extension을 설치한다. `public` schema CREATE 권한을 app에 주지 않는다. app 시작은 migration을 실행하지 않는다.

DSN 파일은 0600, 상위 private directory는 0700으로 준비한다. `?schema=memory`와 같이 선택 schema를 명시한다. token·DSN·원문·모델·backup은 repository에 넣지 않는다.

```sh
uv run agents-memory --config "$CONFIG" init \
  --deployment-id "$DEPLOYMENT_UUID" --realm "$REALM" --mode personal \
  --dsn-file "$APP_DSN_FILE" --migrator-dsn-file "$OWNER_DSN_FILE" \
  --state-dir "$STATE_DIR" --journal-dir "$INDEPENDENT_JOURNAL_DIR" \
  --owner-id "$OWNER_ID" --port 8768

uv run agents-memory --config "$CONFIG" project add \
  --label "$PROJECT_LABEL" --locator "$PROJECT_ROOT" --key "$REGISTRATION_KEY"

uv run agents-memory --config "$CONFIG" credential issue \
  --role agent --binding "$BINDING_ID" --output "$AGENT_TOKEN_FILE"
uv run agents-memory --config "$CONFIG" credential issue \
  --role producer --binding "$BINDING_ID" --output "$PRODUCER_TOKEN_FILE"
```

등록 응답의 opaque binding ID를 사용한다. CWD·branch·MCP session ID·요청 body의 owner/realm은 권한 증명이 아니다. 하나의 credential에 여러 project grant가 있으면 호출에 binding을 명시한다.

프로젝트 경로가 바뀌어도 memory·grant·승인 target을 새 binding으로 복제하지 않는다. operator가 현재 binding의 revision과 기존 locator를 확인한 뒤 같은 identity를 명시적으로 이전한다.

```sh
uv run agents-memory --config "$CONFIG" --token-file "$OPERATOR_TOKEN_FILE" project relocate \
  --binding "$BINDING_ID" --expected-revision "$CURRENT_REVISION" \
  --expected-locator "$OLD_PROJECT_ROOT" --locator "$NEW_PROJECT_ROOT" \
  --key "$RELOCATION_KEY"
```

새 locator는 존재하는 canonical directory여야 한다. 이전 경로는 이미 삭제됐어도 exact expected locator로 검증한다. 첫 실행은 locator·revision만 변경하고 owner·label·grant·roster·memory·frozen target은 유지한다. 같은 key/인자의 replay는 같은 결과이며, 이후 다시 이전된 binding의 과거 replay는 committed conflict로 반환한다. 경로/CWD 변경 자체는 권한이나 승인이 아니다.

회사·고객·개인은 서로 다른 deployment, database/schema, journal, state directory, token, port와 host 설정으로 운영한다. 회사→개인/cloud sync 경로는 없다. `--mode company`는 model fetch의 네트워크 사용을 허용하지 않는다. 회사에서는 검증된 offline artifact를 반입하고 승인된 내부 executor만 사용한다. 로컬 프로세스 설정만으로 같은 UID의 unrestricted agent나 OS 전체의 no-egress를 증명하지 못한다. 회사의 강한 경계에는 별도 OS/service identity, network policy와 관리되는 approver key가 필요하다.

`init`은 private recovery intent와 원래 operator credential을 먼저 영속화한다. bootstrap 이후 완료 receipt를 쓰지 못한 경우 같은 인자·owner·원래 token으로 `init --resume`한다. 기존 배포를 새 owner/token으로 묵시적으로 인수하지 않는다. 완료된 init replay는 이후 정상 변경한 model/queue 설정을 초기 기본값으로 되돌리지 않는다. 기존 migration은 변경하지 않으며 현재 `0004_operation_successors`를 operator 경로로 명시 적용한다.

기존 배포의 schema upgrade는 서비스와 worker를 먼저 정상 중지한 뒤 fresh operator로 `agents-memory --config "$CONFIG" --token-file "$OPERATOR_TOKEN_FILE" migrate --confirm-deployment "$DEPLOYMENT_ID"`를 실행한다. 명시 migrator DSN·동일 local DB/schema·current operator를 검사하고 exclusive authority lock을 획득한 경우에만 DDL을 수행한다. 살아 있는 서비스나 restore fence가 있으면 거절하며, 일반 `serve`/`Store.open()`은 schema를 몰래 변경하지 않는다.

## 로컬 모델

모델 route는 profile 설정과 PG 승인 ledger 모두 유효해야 한다. artifact가 없거나 route가 미승인이면 blocked 상태를 반환한다. 빈 메모리·성공으로 가장하지 않는다.

- 원본: Qwen3.5-9B `c202236235762e1c871ad0ccb60c8ee5ba337b9a`, Apache-2.0.
- embedding: BGE-M3 `5617a9f61b028005a4858fdac845db406aefb181`, MIT, CLS pooling·1024 dimensions·normalized.
- reranker: BGE reranker v2 M3 `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`, Apache-2.0, CPU cross-encoder.
- executor/converter: llama.cpp `5c8854fd88319125125dc4b836c98b1b215b0f23`, MIT. 변환 원본과 실제 GGUF를 manifest에 결합한다.

개인 모드의 명시적인 `model fetch --allow-network`만 원본을 다운로드한다. background inference는 HF offline/local-files-only이며 telemetry와 proxy 자동 사용을 끈다. generation executor는 인증된 loopback endpoint, offline, web UI·agent·MCP proxy·model autoload를 끈 구성을 사용한다.

`model manifest --help`의 원본/GGUF/BGE/converter 경로로 SHA256·license·runtime manifest를 만든 뒤 승인한다. manifest 출력은 기존 파일을 덮어쓰지 않는다.

```sh
uv run agents-memory --config "$CONFIG" model approve \
  --manifest "$MANIFEST_FILE" --gguf "$GGUF_FILE" \
  --embedding "$BGE_M3_DIRECTORY" --reranker "$BGE_RERANKER_DIRECTORY" \
  --generation-key-file "$GENERATION_KEY_FILE" \
  --generation-url http://127.0.0.1:9877 --cpu-threads 8
uv run agents-memory --config "$CONFIG" serve
```

승인은 private `model-approval.lock`으로 협력하는 승인 명령만 직렬화하고, config publication·DB route adoption 사이에 secret-free `model-approval-intent.json`을 남긴다. 실패의 `not_committed`는 config의 확정 보상과 intent 종료, `unknown`은 미확정 효과, `committed`는 확인된 route adoption을 뜻한다. unknown pending intent가 있으면 authority 선검증 실패도 `not_started`로 보고하지 않는다. 기본 복구는 원래 operator credential/generation·authority·config path·같은 artifact/purposes의 **정확히 같은 승인 요청**을 다시 실행한다. 무관한 최신 설정은 보존한다. 같은 route의 재승인도 기존 admission을 fence하므로 소비자는 새 admission을 받아야 한다. purposes를 좁히면 DB도 빠진 purpose를 같은 승인 transaction에서 비활성화하므로 이전 설정을 가진 소비자가 계속 사용할 수 없다. 파일 publication 직전 bytes 검사는 임의 same-UID 편집자에 대한 원자 CAS나 OS sandbox가 아니다.

revoke·restore로 원래 credential을 더는 사용할 수 없으면 현재 operator가 **새 승인**을 명시한다. private intent의 SHA256을 `shasum -a 256 "$STATE_DIR/model-approval-intent.json"`으로 확인하고, 검증할 artifact/purpose를 지정한 `model approve`에 `--supersede-pending-intent "$INTENT_SHA256"`을 추가한다. 현재 operator 인증·artifact 선검증·cooperative lock·exact intent bytes·현재 config가 기록된 before/target 중 하나라는 검사는 그대로 적용된다. 이는 이전 credential을 부활시키거나 이전 승인 결과를 대신 확인하는 동작이 아니다. 잘못된 hash·상충 config·malformed/symlink intent는 덮어쓰지 않으며 intent를 수동 삭제하지 않는다.

## Agent Flow 없이도 사용

```sh
uv run agents-memory --config "$CONFIG" host-install \
  --project "$PROJECT_ROOT" --binding "$BINDING_ID" --host claude \
  --agent-token-file "$AGENT_TOKEN_FILE" --producer-token-file "$PRODUCER_TOKEN_FILE"
```

`--host codex` 또는 `--host omp`로 같은 core에 연결한다. 설치는 소유한 project entry만 관리하고 Agent Flow/user hook을 보존한다. root `AGENTS.md`/`CLAUDE.md`에 memory corpus나 rulebook을 넣지 않는다. uninstall은 owned entry만 제거하며 사용자 변경·drift는 거절한다.

Claude MCP entry는 공유 `.mcp.json`이 아니라 개인 `.claude.json`의 native project scope에 설치한다. Git linked worktree는 Claude가 조회하는 원본 저장소 key를 사용하지만 receipt·token·binding은 선택 worktree 그대로다. 다른 worktree/CWD에서 자동 상속된 native relay는 scope 오류로 종료한다. 서로 다른 worktree에 같은 server 이름을 동시에 등록하려면 기존 owned 설치와 충돌하며 임의 덮어쓰지 않는다. 별도 명시 MCP/CLI 연결은 해당 credential의 grant를 계속 검사한다.

worktree를 옮기거나 삭제할 때는 소비 프로세스를 먼저 중지하고 기존 `--project "$OLD_PROJECT_ROOT"`·host의 owned uninstall → 같은 binding의 `project relocate` → 새 stable project의 host-install 순서로 실행한다. project 경로가 없으면 `host-uninstall`은 `HOST_PROJECT_ABSENT`로 거절한다. 경로가 이동·unmount된 것이면 다시 마운트하거나 복원한 뒤 일반 uninstall을 실행한다. 실제로 삭제됐을 때만 `--project-deleted`를 추가한다. 이 정리는 해당 host/deployment/realm/runtime에 일치하는 **private completed modern receipt**만 허용하며, private native 항목만 검증·제거하고 `native_uninstalled`와 `project_entries: unverified_absent`를 반환한다. receipt는 `native_removed`로 남는다. 이 정리가 중단돼도 receipt는 durable `native_removing` 상태라 같은 범위로만 재개된다. 같은 root가 나중에 다시 나타나면 그 안의 hook과 재설치는 모두 `HOST_UNINSTALL_INCOMPLETE`로 거절된다. 이때 `--project-deleted` 없이 `host-uninstall`을 다시 실행하면 중단된 native 정리를 먼저 마치고 project 상대 hook/MCP 항목을 제거해 `removed`로 끝낸다. 이 receipt를 호출하는 hook이 다른 event로 옮겨졌거나 바뀐 사본으로 남았거나, owned TOML·native key가 바뀌었으면 `HOST_OWNERSHIP_DRIFT`로 거절하고 `native_removed`를 유지한다. 그대로 다시 생긴 owned native key는 함께 제거한다. 이전 버전이 남긴 native-only `removing` intent도 같은 범위로 판별해 `removed`로 바로 끝내지 않는다. 마무리 정리가 중단돼도(`native_finishing`) 다음 uninstall이 현재 파일을 다시 검사한 뒤에만 `removed`로 끝낸다. 예외적으로 Claude의 modern `removing` receipt는 정확한 외부 native key의 owned before→null deletion-only intent일 때만 두 중단점 이후 재개한다. project directory를 재생성하지 않는다. symlink·drift·legacy·pending install·project-local 또는 상충 recovery intent는 거절한다. 사용자 trust·다른 host/AF 설정·credentials·pending spool은 보존한다.

host-install에 사용한 package/venv도 삭제될 임시 checkout 밖에 유지해야 한다. executable·project·endpoint·token이 바뀌면 설치를 덮어쓰지 말고 owned uninstall/reinstall을 수행한다. root rulebook이나 전체 memory catalog를 설치에 포함하지 않는다.

설치만으로 매 프롬프트마다 의미 검색하거나 기억 본문을 자동 주입하지 않는다. 필요한 순간에 네 MCP 도구 또는 workflow에서 호출한다. 자동 prompt recall을 원하는 프로젝트에만 설치 시 `--prompt-recall`을 추가한다. 이 opt-in은 조회 상한을 유지하지만 relevance·모델 준수를 보장하지 않는다. prompt 본문이 없거나 허용 크기를 넘으면 대체 검색어로 corpus를 주입하지 않는다. capture/lifecycle와 protected-action의 required-rule 검사는 이 선택과 별개다.

native workspace/MCP/hook 승인은 별도다. installer는 trust를 위조하지 않는다. Claude는 native MCP 승인이 필요할 수 있고 Codex project 설정은 trusted project에서만 로드된다. Codex noninteractive `exec`의 approval=never가 MCP 호출을 차단할 수 있다. 사용자가 검토한 선택 MCP 도구에만 per-tool `approval_mode="approve"`를 적용할 수 있으며 전체 permissions/hook trust를 bypass하지 않는다. `memory_context`는 recall과 상태를 만드는 reflect를 함께 제공하므로 도구 전체를 read-only로 표시하지 않는다. [Codex 공식 MCP 설정](https://developers.openai.com/codex/mcp)을 확인한다.

generic MCP는 자동 호출/자연어 준수를 강제하지 않는다. opt-in native adapter의 capture·context·lifecycle 지원 범위도 다르다. Claude 일반 prompt의 원본 attribution, OMP print/ACP capture, Codex hosted tool guard, 후속 provider input의 실제 보존/소비는 관측 불가 경로가 있다. Claude/Codex의 지원 strict 행동은 capability gap/block으로 처리한다. **OMP의 새 `--strict` 설치는 native pre-request 예외/timeout의 fail-closed gate가 없으므로 `HOST_STRICT_UNSUPPORTED`로 설정 쓰기 전에 거절한다.** OMP의 advisory/MCP 수동 호출은 지원한다. 역사적 strict receipt는 정확한 owned uninstall/rollback용으로만 허용하며 기존 extension은 제거·재설치 후 host를 재시작해야 한다. receipt 거절이 이미 로드된 옛 host의 직접 provider 호출을 막는다고 주장하지 않는다. offered context는 consumed/enforced가 아니다.

## 호출 계약

- capture/correct는 producer token, note/feedback/context/inspect는 agent token, approval/retract/purge/migration/restore는 operator 경계를 사용한다. agent feedback은 정정 후보이지 trusted source 교체나 irreversible 삭제가 아니다.
- idempotency key는 의미 payload fingerprint와 결합한다. 같은 key·다른 payload는 conflict다. origin replay도 삭제 floor를 통과해야 한다.
- accepted/committed는 indexed가 아니다. `await --operation "$OPERATION_ID"`로 `semantic_ready`를 확인하고 `causal_operation`으로 이후 read를 결합한다.
  source 재처리와 index 복구가 새 owner를 만들면 원래 blocked/failed receipt는 유지하고 `successor_operation_id`로 연결한다. 명시 `retry`는 기존 owner의 새 generation/attempt를 재개하는 별도 동작이다. 관련 입력만 철회된 살아 있는 capture는 같은 원래 owner에서 남은 적격 입력으로 consolidation을 재계획한다. 자신의 원문이 철회된 경우와 구분한다.
- snapshot-bound source는 같은 `snapshot` 요청에서만 읽힌다. 직접 source `memory_inspect`/API/CLI도 본문 반환 전에 이를 검사하므로 `inspect --snapshot "$SNAPSHOT"`를 사용한다. 누락·불일치는 거절하며 snapshot 없는 global source는 어느 요청 snapshot에서도 적격이다. `stats --snapshot`도 동일한 eligibility를 사용한다.
- optional 결과 기본 총 3개/2,400 UTF-8 bytes. required TRUE는 완전한 본문·revision을 전달하고 FALSE는 제외한다. UNKNOWN은 일반 조회에서 bounded opaque ref만 알리며 원문·승인 stamp를 제공하지 않는다. protected action에서는 UNKNOWN/overflow를 거절한다. native context는 marker와 newline을 포함한 1,800 UTF-8 bytes 상한이다. tool 본문은 TextContent 한 plane이고 최대 wire body는 16KiB다.
- 부정·조건·예외·valid time·snapshot·원문 revision/UTF-8 span과 **`source_speaker`**를 보존한다. claim/recall/reflect 입력의 근거는 실제 source metadata에서 speaker를 읽으므로 agent note를 human source로 합치지 않는다. 이 분류는 source의 선언된 종류이지 인간 존재·사실 검증·승인 증거가 아니다. 조건/예외는 인용된 원문의 구절이어야 한다. syntax/grounding guard는 일반적인 factual entailment나 모든 조건 누락을 증명하지 않는다. 실제 품질 검증과 사람의 정정이 필요하다.
- reflection의 각 전달 문장은 인용한 claim에 대응하는 `source_provenance`를 포함한다: `source_id`, `source_revision`, `source_speaker`, nullable `source_event_time`, `source_recorded_at`. 코드는 원래 source metadata를 붙이며 모델에 clock 재서술을 맡기지 않는다. 누락 event time은 null이고 recorded/claim 생성 시각으로 대체하지 않는다. provenance는 validity·사실 검증·승인·supersession 근거가 아니다. assertion과 limitations의 숫자/식별자 검증은 인용 원문에 한정한다. inspect는 저장된 `limitations`를 문장·provenance보다 먼저 4,096-byte 전달 budget에 넣고 전체 JSON 구분자도 센다. limitations를 모두 전달할 수 없으면 assertion 문장을 전달하지 않고 partial을 표시한다. 남은 예산을 넘는 문장도 provenance 전체와 함께 제외하며 내용을 잘라 보내지 않는다.
- stdio relay는 검증된 bounded HTTP 오류의 공개 code/effect를 보존한다. 연결 유실·잘못된/잘린/ID 불일치 응답의 durable 효과는 `unknown`이며 같은 business key로 소비자가 명시 reconcile한다. raw upstream 진단 전달이나 자동 mutation retry는 없다.
- convention은 candidate → exact digest/target-set revision 승인 → active rule이다. 적용 범위는 정확히 **이 로컬 프로젝트 / 내 프로젝트들 / 팀 또는 프로젝트 공유**다. 내 project target set은 frozen이며 새로운 project를 자동 포함하지 않는다. 같은 UID의 bearer를 인간 검토 증거로 주장하지 않는다. 회사 공유 승인은 구성된 별도 managed Ed25519 approver signature가 필요하다.

승인자 credential을 바꾸기 전 `credential revoke --credential-id "$ID" --preview`로 본문 없는 영향 목록을 확인한다. 활성 required rule이 영향받으면 `--ack-required-rules` 없이는 폐기를 거절한다. 폐기 후 같은 immutable proposal·frozen scope/targets를 fresh 승인 key로 재승인하면 새 rule ID와 더 높은 revision을 만든다. 무관한 project roster 증가 때문에 기존 frozen target의 재승인을 막거나 새 project를 자동 포함하지 않는다. 회사 공유 승인의 fresh managed signature 요건은 그대로 유지한다. 원문이 철회된 proposal이나 변경된 body/범위를 기존 승인으로 부활시키지 않는다.

## 운영

`doctor`, `stats`, `inspect`, `retry`, bounded `spool enqueue/status/flush`를 제공한다. `pending`/`blocked`/`failed`/`dlq`와 `current_operations`는 아직 소유권이 살아 있는 durable job의 복구 필요 상태를 보고한다. `historical_operations`/`historical_jobs`는 전체 durable row의 현재 상태 집계이며 immutable attempt event log가 아니다. 중복 `operations`/`jobs` alias는 제공하지 않는다. 새 successor가 복구한 retired 실패만으로 현재 partial을 만들지 않으며 원래 outcome을 보존한다. 아직 살아 있는 실패·overflow·capture gap·route blocked는 계속 보고한다. journal은 DB restore 밖에 있으며 본문 대신 HMAC source/origin identifiers와 fsync chain을 기록한다.

`index-status`로 vector compatibility별 누락을 확인하고 `index-recover`로 embedding만 다시 계산한다. prompt/extraction 계약 변경으로 기존 lexical/entity/inspect와 grounded reflection을 무효화하지 않는다. compatible vector만 vector arm에 들어가며 incompatible vector가 있는 claim도 적격 lexical/entity arm에서는 검색된다. index 복구는 새 claim 추출·모델 해석 변경이 아니다.

native capture spool의 pending·quarantine 본문은 원래 local enqueue부터 24시간 TTL이다. replay·격리·명시 retry·reopen으로 원래 deadline을 연장하지 않는다. 접근/reopen 시 만료 본문을 제거하고 전송을 차단하며 `SPOOL_PAYLOAD_EXPIRED` gap과 bounded body-free expired receipt를 남긴다. 원래 age를 모르는 구형 row는 새 age를 만들지 않고 `SPOOL_PAYLOAD_AGE_UNKNOWN`으로 제거한다. expired는 로컬 보관 손실이지 이전 unknown 원격 시도의 non-commit 증거가 아니다. receipt가 count/TTL 상한에서 퇴출되면 기존 server-idempotency reconciliation 계약을 따른다. 물리적 DB/WAL/SHM 상한을 유지하지만 닫힌 파일의 deadline 즉시 삭제·clock rollback·snapshot/media forensic erasure를 보장하지 않는다. path projection의 16MiB event decode를 그만큼 원문 저장하는 것으로 해석하지 않는다. strict/receipt는 provider 소비·첫 행동 집행 증거가 아니다.

`backup`은 PG18.6 `pg_dump` snapshot을 age로 streaming 암호화한다. operations runtime에는 같은 pin의 `pg_dump`, `pg_restore`, `psql`이 필요하다. local mode는 각각 검증한 절대 실행 경로를, Docker mode는 명시한 owned container의 세 바이너리를 사용한다. durable plaintext dump를 만들지 않으며 독립 journal을 archive에 넣지 않는다.

`backup`, `restore`, `restore-recover`의 기본 `--runtime local`에서는 `--pg-dump-binary /절대/경로/pg_dump --pg-restore-binary /절대/경로/pg_restore --psql-binary /절대/경로/psql`을 모두 명시해야 한다. 누락은 CLI 사용법 오류이며 bare/relative·없는 파일·실행 불가능한 파일은 작업 전에 거절한다. PATH 탐색이나 자동 fallback은 없다. `--runtime docker`에서는 이 세 host 경로를 생략하고, 명시한 Docker endpoint/container 내부의 `pg_dump`·`pg_restore`·`psql`을 사용한다.

`restore`는 executor/version/schema/archive/checksum/최신 독립 deletion head를 검증한 뒤 exclusive fence를 건다. 구형 format2 archive의 `0001`/`0002`/`0003` prefix도 현재 `0004` target에 복원한다. 필요한 새 FK/table 정리와 archive SQL은 하나의 미완료 transaction에서 실행하며, authenticated age EOF·digest/크기·성공한 SQL producer를 모두 확인한 경우에만 COMMIT한다. 실패/중단은 기존 table·본문·lineage·reservation을 rollback하지만 durable authority fence는 private recovery 전까지 유지한다. 성공 후 forward migration→fresh operator/이전 token 폐기→rule 재승인·route 비활성화·job fencing→surviving deletion floor를 적용한다. fresh token으로 host 설정을 갱신한다.

첫 restore marker를 durable하게 발행한 뒤 fresh token 파일을 쓰고, 그 다음 executor를 시작한다. marker 발행 전 실패는 `not_started`이며 marker/token 파일을 남기지 않으므로 동일한 `--operator-out` 경로로 원래 요청을 다시 실행할 수 있다. marker가 남은 발행 실패나 이후 token 쓰기 실패는 `UNKNOWN`이며 일반 authority 접근을 막는다. 이때 현재 operator로 `restore-recover`를 실행해야 하며, 아직 발급되지 않았거나 활성화되지 않은 fresh token을 credential로 사용하지 않는다. private recovery는 archive가 적용됐다고 증명하지 않는다.

operator가 공급한 latest head는 외부 witness의 attestation이 아니며 WAL/media/암호화된 과거 archive의 완전 삭제를 증명하지 않는다.

기존 host 설치와 token/endpoint/path가 달라지면 `host-install`은 `HOST_ALREADY_INSTALLED`로 거절한다. 기존 설정을 임의 덮어쓰지 말고 같은 `--project`·`--host`의 `host-uninstall` 후 fresh agent/producer token으로 다시 `host-install`한다. 해제는 receipt-owned entry만 제거하고 사용자·Agent Flow entry와 pending private spool은 보존한다. CLI 기본 operator 경로가 이전 파일을 가리키면 fresh `--token-file`을 명시한다.

Claude recovery intent는 canonical project의 소유한 `mcpServers.agents-memory` key만 저장·복구한다. 현재 native document에 병합하고 무관한 history/counter/trust 변경을 보존한다. 실제 native mkdir lease에 협조하며 heartbeat와 publication 직전 lease/current-bytes 검사를 수행한다. native의 모든 writer가 lock을 지키는 것은 아니므로 같은 UID의 임의 writer·정지/lease 탈취에 대한 atomic CAS 보장을 주장하지 않는다. host 설치·복구·해제는 해당 native 설정을 동시에 변경하지 않는 maintenance 구간에 실행한다.

logical retraction, local drain, provider completion unknown, local row purge와 WAL/media/backup erasure는 서로 다른 상태다. socket cancel이나 row 삭제를 모든 사본 삭제로 주장하지 않는다.

로컬 public/synthetic corpus로 **실제 1–2주 trial** 후 개인 cloud 배포를 판단한다. 아직 elapsed trial/cloud provisioning/TLS·OAuth ingress를 통과했다고 주장하지 않는다. 회사 corpus는 개인 cloud migration 대상이 아니다. 같은 core/API/schema/rule semantics를 유지하고 배포·identity·network boundary만 별도로 구성하는 것이 cloud 전환 계약이다.
