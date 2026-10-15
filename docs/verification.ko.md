# 실제 로컬 검증 기록

## stage-0 동시성·복구 수정 — development/20261015-043508

범위는 네 결함뿐이다. (1) 사라진 MCP 세션 복구 (2) serve·migrate·backup·restore의 단일 PG/pgvector 계약 (3) 원문 창당 판단 단일 승자와 응답 유실 재시도 (4) 동시 요청 상한·pool 획득 기한·전역 clock 잠금 없는 인증. cloud·새 memory block·pgvector 검색·trial·`FOR SHARE`는 범위 밖이다.

- 새 회귀는 수정 전 **26 failed/11 passed**, 수정 후 **37 passed**였다(`s0-red.log`, `s0-green-first.log`). 이후 전체 suite는 **1701 passed/19 failed**(460s)였다(`s0-full-suite.log`).
- 19개 처리: `restore-recover` 12개는 marker 확인이 명시 runtime 검증보다 먼저라 `RECOVERY_NOT_REQUIRED`가 `BINARY_REQUIRED`를 가렸다. 검증을 marker 앞으로 옮겼다. 단일 승자 검사가 거절·파생 floor보다 먼저 실행돼 `EVIDENCE_REJECTED`/`DERIVATION_RETRACTED`를 가린 2개는 검사를 floor 뒤로 옮겼다. 같은 창의 두 번째 complete remember를 허용하던 옛 동작을 고정한 테스트 5개는 새 계약으로 바꿨다: capture 테스트는 `SELECTION_ALREADY_RECORDED`와 active claim 1개를 기대하고, 독립 sibling·discard는 다른 요청 snapshot에서 판단하며, model-era migration fixture는 caller selection 없는 legacy source를 복원한다. 실패했던 19개와 새 회귀만 다시 실행해 **53 passed + 3 failed**, sibling inspect의 snapshot 인자를 고친 뒤 그 3개 **3 passed**였다(`s0-failed-rerun.log`). 이미 통과한 전체 suite는 반복하지 않았다.
- `uv run ruff check src tests` 통과, `uv build` 통과. wheel SHA256 `7baf9a8ce2e479e0b2e003c8754d1b1f42af7cd548e15513ab6605ec12b6b09b`, sdist `7fbfeeb1d88c7d74d620ec47c557eb6238c575c29eddf172d278d5798afc7821`.
- **실제 current-source 서비스 smoke**(임시 UUID schema·private config, PG 180006·pgvector 0.8.7, `s0-actual-service-smoke.json`): `init`→`serve`→producer HTTP capture→`stdio` relay로 공식 MCP initialize·inspect. 서비스를 재시작한 뒤 같은 relay의 `memory_record`가 자동 재연결로 `candidate_ready`였다. 같은 판단·같은 admission의 새 key는 같은 operation id, 다른 판단은 `ADMISSION_CONSUMED`, 새 inspect의 두 번째 remember는 `SELECTION_ALREADY_RECORDED`였고 source의 selection·claim은 각 1개였다. 다른 connection이 `am_clock FOR UPDATE`를 잡은 동안 `/readyz` 인증은 200/0.006s였다. `max_concurrent_requests=1`에서 미완성 요청이 슬롯을 잡은 동안 다음 요청은 `SERVICE_BUSY`/503/`not_started`, 해제 뒤 `/healthz` 200이었다. Docker ops runtime의 실제 backup receipt는 live `18.6`/`0.8.7`/`0006_agent_judged`였다. 세 service 종료·schema 삭제를 관측했고 임시 디렉터리를 지웠다.
- smoke driver 자체 오류 3건(없는 `httpx` import, driver 직접 연결에 `schema` 파라미터 전달, 재실행 시 남은 private 파일)은 driver만 고쳤다. 제품 코드·guard·설정은 바꾸지 않았다. 첫 결과는 `s0-actual-service-smoke-driver-fault.log`에 남겼다.
- **첫 공식 리뷰(R1)**: Claude probe가 실패해 Claude 6개는 실행되지 않았다. Codex 6개 중 state-integrity만 approve, 나머지 5개는 request-changes였다. 지적 4건을 수정했다: (a) relay 재연결이 실패하면 세션 없이 남던 문제, (b) 재전송 판단이 검증된 오류 표현을 거치지 않던 문제, (c) idle `GET /mcp` stream이 요청 상한을 점유하던 문제, (d) backup·restore의 버전 검사가 journal reconcile 뒤에 있던 문제. LOW 제안대로 동시 제출과 Store 재시작 뒤 재시도 회귀도 추가했다. 새 회귀와 바뀐 경로의 테스트 실행에서 8개가 실패했다. 6개는 JSON-RPC HTTP 오류까지 edge 형식으로 검사한 내 오류였고, 1개는 재시작 테스트의 journal reconcile 누락, 1개는 `restore-recover` 검사 순서였다. 이를 고친 뒤 실패 8개와 CLI 12개만 다시 실행해 **44 passed**였다(`s0-r1-fix-focused.log`, `s0-r1-fix-rerun.log`). 새 회귀의 수정 전 실패는 reviewer들이 각자 재현한 기록에 의존하며, 이 run에서 수정 전 코드로 다시 실행하지는 않았다.
- R1 실제 서비스 smoke(`s0-r1-actual-service-smoke.json`, `max_concurrent_requests=1`): live 세션의 idle `GET /mcp` stream이 열려 있는 동안에도 relay의 `tools/list`가 성공했다(stream 200, 도구 4개). 슬롯이 점유된 동안 서비스를 재시작하자 첫 요청은 `SERVICE_BUSY`/`not_started`였고, 슬롯이 풀린 뒤 다음 요청은 재연결해 도구 4개를 반환했다. 실제 서비스에서 재연결 자체가 거절되는 순서는 만들지 못했으므로 그 경로는 단위 회귀만으로 확인했다. schema 삭제와 service 종료를 확인했다.
- R1 수정 뒤 ruff 통과, `uv build` 통과(wheel `925b005e…`).
- **두 번째 공식 리뷰(R2)**: Claude 5개 approve, Claude clean-architecture는 600초 timeout, Codex는 types·state-integrity approve, 나머지 4개 request-changes였다.
  - must-fix 두 건을 수정했다.
    - 모든 `GET /mcp`가 인증 전부터 상한을 우회하던 문제: 이제 응답이 시작될 때까지 슬롯을 쓴다.
    - backup의 live server 검사가 staging 뒤에 있던 문제: `store.open`을 staging 앞으로 옮겼다.
  - Claude should-fix도 반영했다. claim이 모두 철회된 remember는 창을 잡지 않으므로, 같은 요청 scope에서 철회 뒤 discard를 고정하던 company 회귀를 원래 형태로 되돌렸다.
  - 새 회귀와 바뀐 경로 61개는 통과했다(`s0-r2-fix-focused.log`). reorder된 backup 경로 29개도 통과했다(`s0-r2-backup-paths.log`).
- R2 실제 서비스 smoke(`s0-r2-actual-service-smoke.json`, `max_concurrent_requests=1`):
  - 슬롯이 점유된 동안 세션 없는 `GET /mcp`는 503/`SERVICE_BUSY`/`not_started`였다.
  - 열린 idle stream(200) 동안 relay `tools/list`는 도구 4개를 반환했다.
  - Docker runtime 실제 backup은 `committed`, `18.6`/`0.8.7`/`0006_agent_judged`였다.
  - schema 삭제와 service 종료를 확인했다.
- R2 build: wheel `9a93d2bb813244a611b77fd252fc8ed335f1aa17a1d17066526e8e418569f9fd`, sdist `9de0153af066445c51fddb96778250478a4383fd010ee811a83905a391bb2949`.
- 남은 비차단 위험:
  - consumed-admission 조회에 index가 없다.
  - `memory_context`의 앞 transaction이 read admission을 commit한 뒤 뒤 transaction이 `DATABASE_BUSY`를 받으면, 효과 표시는 `not_started`다. 남는 것은 TTL 180초의 read admission뿐이며 relay는 이 code를 자동 재전송하지 않는다.
  - `migrate`는 버전을 정수 형식으로 보고한다.
  - archive와 live의 버전을 서로 비교하지 않는다.
  - 세션 수 상한(64)에 도달한 상태에서는 세션이 reap될 때까지 `SESSION_NOT_FOUND`가 반복될 수 있다(재전송은 없음).
- **세 번째 공식 리뷰(R3)**: Claude probe가 실패해 Claude 6개는 실행되지 않았다. Codex는 state-integrity만 approve, 나머지 5개는 같은 지적으로 request-changes였다. R2의 "active claim 있는 remember만 승자" 조건이 처음부터 claim 없이 기록한 complete remember를 승자에서 빼, 같은 창에 두 번째 complete 판단이 저장될 수 있었다. 이제 게시한 claim이 모두 철회된 remember만 창을 놓는다. claim 없는 remember 뒤의 remember·discard 거절과 동시 제출 1승자 회귀를 추가했다. 해당 경로 23개가 통과했다(`s0-r3-fix-focused.log`). build wheel `a461ac83e40b470d52aa0199df68ef87828fab2dcca5c2a7104c9dc25df809d3`.
- **네 번째 공식 리뷰(R4)**: Claude probe 실패로 Claude 6개는 실행되지 않았고 Codex 6개는 모두 approve였다. 비차단 제안(consumed-admission index, 부분 겹침·인접 창 회귀)은 위 남은 위험에 둔다.
- **공식 QA**: `agent-flow gates --phase all --execution local`이 **3/3**(lint·test·package) 통과했다. 실제 PG·Docker ops·age 환경 변수를 준 상태에서 실행했다. gate 출력에는 pytest 개수가 나오지 않으며, 개수를 얻으려고 suite를 다시 돌리지 않았다.
- **최종 wheel smoke**(`s0-final-wheel-smoke.json`): wheel `a461ac83…`을 격리 venv에 offline 설치한 뒤 두 smoke driver를 다시 실행했다. 서비스 재시작 뒤 relay 자동 재연결(`candidate_ready`), 새 key 재시도의 같은 operation, `ADMISSION_CONSUMED`, `SELECTION_ALREADY_RECORDED`(selection·claim 각 1개), clock 잠금 중 `/readyz` 200/0.007s, `SERVICE_BUSY`가 관측됐다. 슬롯 점유 중 `GET /mcp`는 503이었고 idle stream 중 relay 호출은 성공했다. Docker backup은 `committed` 18.6/0.8.7/0006이었다. schema·service·임시 venv를 정리했다.
- **run 종료 뒤 코드 리뷰(Standards·Spec 두 축)**: 지적 중 아래를 반영했다.
  - `update-checkpoint` 증거 표현을 줄였다.
  - `_tx`의 중복 연결 실패 오류를 `_connection_failed()`로 합쳤다.
  - relay 오류 검증을 `_verified`로 합쳤다.
  - 재시작한 서버가 다른 protocol version을 협상하면 복구를 거절한다. 회귀 1개를 추가했다.
  - 예외를 던지는 버전 검사를 `require_*`로 이름을 바꾸고 `INSTALLED_VECTOR_SQL`을 공유했다.
  - I35 문구를 claim 철회 규칙에 맞췄다.
  - CHANGELOG·README의 리뷰 이력 표현을 현재 동작 기준으로 정리했다.
  - 빈 줄을 정리했다.
  - 반영하지 않은 판단: `_send`의 tuple 반환 구조, edge의 별도 상한 counter, 부분 겹침·인접 창 회귀, 다른 PG patch 버전 실측.
  - 바뀐 경로(stdio·ops·authority_concurrency·edge·CLI 전체와 preflight)는 **534 passed**였다(`s0-post-review-focused.log`). ruff 통과. 새 wheel은 `0a063e54e71edfcf7636ff44c7e464823f88754b39602118429a6d6285f5ca3f`이며, 격리 venv 설치 뒤 두 smoke driver가 앞과 같은 결과였다(`s0-post-review-wheel-smoke.json`).
  - 공식 AF QA gate 3/3은 이 리뷰 반영 전 코드(`a461ac83…`)의 결과다.
- 안정 개인 배포·회사 local 배포(8778)·개인 failed6/DLQ6은 건드리지 않았다. 공식 review/QA/handoff 결과는 run artifacts를 따른다.

## 공통 coding-agent 판단 전환 — development/20261013-234417

정본은 [통합 이슈 #5](https://github.com/chonamdoo/agents-memory/issues/5)와 [사용자 확정 결정](https://github.com/chonamdoo/agents-memory/issues/5#issuecomment-6150124320)이다. 개인·회사는 현재 Claude/Codex가 MCP로 판단을 제출하고 서버가 원문·revision·권한을 검증하는 같은 경로다. lexical/entity는 후보 색인이며 기본 판단이 아니다. Qwen 추출·consolidation·reflection과 서버 embedding/reranking 실행 경로·설정·의존성을 제거했다.

### 최신 migration 수정 — recovery development/20261014-154435(R6)

R5 수정 후 canonical fresh Codex6개가 모두 완료/request-changes였다(722.84s). Claude probe는 OAuth401이었다. types가0005 보존 admission의 NULL request_digest→DTO ValidationError/INTERNAL_ERROR를, state-integrity가 coroutine 취소 후 live migration thread보다 exclusive lock이 먼저 풀리는 경로를 직접 재현했다. 앞선 R4/R5 경계 수정은 현재 source 검사와 supplied focused evidence로 인정됐지만 원래 S9는 모든 angle에서 여전히 HIGH다. 현재 provider 원본7개·manifest·input patch·집계10개 payload를 byte/hash 검증 archive로 보존했다. SHA256은 run `r6-native-negative-before-fix-preserved.json`에 있다.

구형 admission을 shared typed decoder 이전에 stale로 거절하고, 동기 DDL task를 shield/join해 반복 취소에도 worker가 끝나기 전 lock이 풀리지 않게 했다. migration-kind durable fence는 원래 private config·operator·exact request에 결합하고 current restore recovery와 구분한다. config replace 응답이 유실돼도 exact target·retained original로 명시 재개한다. strict DTO 완화·digest 추측·audit 삭제·취소의 성공 포장은 없다.

새 회귀만 immutable R5 package의 실제 code로 먼저 실패를 재현했다. genuine0005 DDL→actual0006→modern MCP의 admission1건은 **1 failed/1.42s→1 passed/1.29s**였다. 실제 PG·worker thread·OS authority lock의 반복 취소, lost committed DDL, 잘못된 actor/request/restore recovery 거부, config 발행 전/후 유실4건은 **4 failed/1.92s→4 passed/2.16s**였다. 모두 `-W error`, 보고된 경고0이다. 먼저 통과한1건은4건 재검사에서 제외했고 R4/R5 통과 사례·전체 suite도 반복하지 않았다. 최초 four-file lint의 import-order1건은 LSP code action이 없어 수동 정리한 뒤 해당 파일만 재검사해 통과했다.

별도 개인 UUID schema에서 actual PG migration thread를 중단하고 실제 CLI `serve`를 각각 실행했다. worker가 살아 있을 때 AUTHORITY_BUSY, thread 종료 후 명시 복구 전에는 RESTORE_RECOVERY_REQUIRED가 Uvicorn lifespan stderr에 있었고 두 process는 실제 exit3/listener refusal이었다. 실제 CLI `migrate --upgrade-config`는 committed/application_verified 뒤 fence를 해제했다. 최초 throwaway probe는 stderr를 structured CLI JSON으로 잘못 가정해 실패했으며 원본 로그를 보존하고 output-plane 가정만 고쳤다.

복구된 실제 CLI service→loopback HTTP→공식 SDK2.3 MCP→PG에서 구형 NULL-digest admission은 ADMISSION_STALE/not_started, selection0이었다. 원문을 새 inspect한 caller의 같은 idempotency key discard는 committed/selection_recorded·selection1이었고 구형 admission audit도 남았다. 이 관측은 declared synthetic source/current CLI에 한정되며 actual native model·원래 stable deployment·실제 failed6 복구가 아니다.

소유 service의 SIGTERM 종료는 supervisor exit143으로 관측했다. 두 exact UUID schema 부재를 검증하고 private config/token/DSN/state·immutable baseline·throwaway driver를 제거했다. 원래 stable DB/config/hosts/failed6·native trust는 바꾸지 않았다. 이 수정 후 새 official review/QA/local-handoff와 원래 S9는 아직 미완료이며 commit/push/PR·post-merge Agent Flow 설치·deferred 보고서 읽기는 하지 않았다. 최신 package/build identity는 run의 `runtime-proof/r6-package-identities.json`에 기록한다.

### 이전 native 잔여 수정 — recovery development/20261014-154435(R5)

R4 뒤 첫 review wave의 원본12개·manifest를 byte/hash 검증한 archive로 보존했다. Codex rate-limit deadline 뒤 공개 canonical continuation의 documented per-invocation timeout으로 새 wave를 실행했다. 현재 Codex6개는 모두 완료/request-changes이고 Claude는 OAuth401로 실행 불가였다. stale Claude 결과를 재사용하지 않았고 현재 negative set을 정직하게 집계해 정식 FIX-LOOP로 돌아왔다. reviewer/provider·guard·pin·counter를 바꾸지 않았다.

잔여 원인3개를 수정했다. OMP preparation/capture의 소비 타입6개, 실제 두 SQLite connection의 expiry receipt 퇴출 뒤 늦은 ACK/확정 거절2개, fresh/prior-authority preparation secret 거부의 durable gap2개가 수정 전 실패하고 수정 후 **10 passed/1.54s, `-W error`, 보고된 경고0**이었다. 기존 통과15개·전체 suite는 재실행하지 않았다. shared CorrectCommand는 LSP references의 모든 caller를 domain으로 옮겼으며 wire shape를 바꾸거나 compatibility alias를 만들지 않았다. 변경 Python8개 lint도 통과했다.

별도 개인 UUID schema의 실제 source CLI service에서 receipt-owned OMP adapter를 임시 설치했다. 합성 `input` envelope→실제 host-hook CLI→HTTP capture→공식 SDK MCP inspect→현재 caller의 complete-window discard→다음 context는 unclassified0/incomplete1/partial=true였다. `HOST_SESSION_WINDOW_UNOBSERVED`·`HOST_HUMAN_PRESENCE_UNATTESTED`를 판단 완료로 지우지 않았다. 별도 producer LocalClient의 실제 `/api/correct`는 captured였고 다음 MCP inspection에서 old source는 retracted/body 비노출이었다. 두 독립 CLI 프로세스에서도 preparation secret refusal의 body-free gap1이 유지됐고 거부 시 generation0/preparation 없음이었다.

설치된 rendered TypeScript를 Node24.14.1로 불러 실제 Python host-hook child→현재 HTTP service의 finding capture를 실행했다. production reply의 committed/captured와 source pointer가 소비됐다. 첫 throwaway probe는 prompt recall이 꺼져 있는데 context gap 문자열을 기대했고, Node ESM 형식도 선언하지 않아 실패/경고를 남겼다. 원본 로그를 보존하고 own fixture의 type=module 선언 및 명시 finding 경로로만 수정했다. 재실행은 exit0·stderr/경고 출력 없음이었다. native OMP emitter·모델 invocation·provider input 소비 증거로 바꾸지 않는다.

owned host-uninstall은 exit0이며 native trust는 바꾸지 않았다. 확인한 own process group에만 SIGTERM을 보내 종료를 확인했고, UUID schema 부재와 private config/token/state/DSN/driver 제거를 확인했다. 즉시 PID 부재 assertion은 먼저 실패했지만 이후 state inspection은 PID 부재였다. helper 재시작 때문에 service의 raw exit code는 확보하지 못했으며 이를 -15로 추정하지 않는다. 원래 stable DB/config/owned hosts/failed6는 그대로다. 최신 배포물 identity는 run의 `runtime-proof/r5-package-identities.json`에 기록한다.

R4 fixture 진단의 interval 설명도 바로잡았다. `_housekeep()`에는 legacy scrub 호출/interval 자체가 없고 constructor가 별도로 호출한다. 원래 실패와 실제 scrub 경로로 고친 red→green을 보존했다. 현재 수정 후 fresh native review·공식 QA/local-handoff·원래 stable S9/failed6는 아직 미완료다. commit/push/PR·post-merge Agent Flow 설치와 deferred meta-loop 보고서 읽기는 하지 않았다.

### 이전 native 지적3건 수정 — recovery development/20261014-154435(R4)

이전 native Codex5개는 모두 request-changes였으며, note/feedback reason coverage·legacy spool stale 판정의 acknowledged replacement 삭제·OMP numeric additionalContext TypeError를 지적했다. 세 원인을 수정했다. 새 소비 회귀15개가 수정 전 실패했고 수정 후 **15 passed/3.69s, `-W error`, 보고된 경고0**이었다. payload race의 첫 fixture는 `status()`가 legacy scrub을 호출한다고 잘못 가정해 분류를 시작하지 못했다. `_housekeep()`에는 scrub 호출이나 interval이 없고 constructor가 별도로 scrub을 호출한다. trigger를 실제 production scrub 호출로 고친 뒤 정상 replacement 삭제를 재현했다. 최초 실패와 수정된 before/after 증거를 모두 보존했다. 기존 통과 사례·전체 suite는 재실행하지 않았다.

실제 current-source CLI serve→HTTP→공식 SDK→PG18.6의 별도 개인 UUID schema에서 note와 reject reason 뒤 coverage0/partial=false, 미판단 document capture 뒤 unclassified1/incomplete1/partial=true를 관측했다. raw note도 보존됐다. pytest의 합성 company fixture는 일반 assistant를 포함한 네 eligible speaker를 검증했고, 두 실제 SQLite connection의 durable ACK 뒤 payload/digest 보존 및 rendered TypeScript→Node24.14.1→실제 child IPC의 typed refusal5개를 확인했다. 변경 Python 파일 lint와 sdist/wheel build도 통과했다. current-source HTTP proof를 설치 wheel·native 모델 소비·stable 전환 proof로 표현하지 않는다. owned service는 SIGTERM/exit-15로 끝났고 UUID schema·비밀 state·throwaway driver를 제거했다.

이전 Claude generalist timeout/나머지5개 없음과 Codex I/O rate limit(2026-10-14T16:22:33.407038+00:00), automatic regeneration1회·fix-loop round3는 원래 run에 그대로 보존했다. 사용자 선택에 따라 canonical abort 후 같은 dirty worktree/전체 범위로 recovery run을 시작했다. 원래 incomplete negative set을 승인으로 세거나 counter/guard/pin을 수동 reset하지 않았다. 새 fresh official review/QA/handoff와 stable S9/실제 failed6는 여전히 미완료이고 commit/push/PR은 없다. meta-loop 보고서는 현재 작업 뒤 읽으라는 요청대로 아직 보류했다.


### 이번 전환에서 직접 관측한 결과

- 첫 공식 리뷰 전 통합 회귀: fork 수정 후 `pytest -q -W error::DeprecationWarning`으로 **1,376 passed, 195.66s, skip0, reported warnings0**. ruff와 sdist/wheel build도 통과했고 product wheel은 실제 MCP 검증본 `bdcc1d…7c473`과 같았다. 이는 아래 리뷰 수정의 검증 결과가 아니다. 이전 CWD 수정 직후에는1,376 passed/179.06s와 fork DeprecationWarning31개였고, 그 이전 통합은1,376 passed/175.55s였다. 최초 실패 기록도 private run에 보존했다. migration의 기존 feedback state 중복, SQL 문자열 안 semicolon 분리, 누락된 relation admission/inventory, 새 identity sequence의 archive scope, MCP tool catalog의 응답 상한을 수정했다. 보호 상한을 늘리거나 strict decoder를 느슨하게 하지 않았다.
- 실제 loopback HTTP + SDK2.3 MCP: 개인과 별도 **합성 company-mode DB**에서 capture는 captured/unclassified였고, 원문 inspect 뒤 현재 coding agent의 source_selection만 candidate_ready를 만들었다. 별도 회사 selection 승인, 로컬 모델 호출이나 실제 회사 계정 우회는 없었다. record/capture의 exact replay도 관측했다.
- 실제 두 호출 recall: expansion으로 후보를 찾은 첫 응답은 optional context0이었다. full claim/source를 읽고 relevant=true를 제출한 개인 응답은 cited context562B, 회사의 unrelated 후보에 relevant=false를 제출한 응답은 context0이었다. 다른 query의 saved admission과 철회 뒤 admission은 ADMISSION_STALE였다. 이 수치는 해당 합성 응답의 UTF-8 bytes이며 일반 품질·효익 수치가 아니다.
- 실제 cleanup: scheduler가 pending만 생성했고, agent의 명시적 no-relation judgment 후 해당 pending은 resolved였다. 별도 전체5-claim manifest에 duplicate/supports/contradicts/supersedes 네 판단과 이유를 제출했다. supersedes는 원문의 explicit change language를 근거로 했으며 기존 negative sibling은 active/원문 유지였다. source 이름·기록 시각만으로 독립 corroboration이나 날짜를 추론하지 않았다.
- 실제 거부: reject 이유가 다음 source inspection에 노출됐다. 같은 source와 새 origin의 exact-copy remember는 EVIDENCE_REJECTED였다. 새로운 합성 원문에서도 비교 누락은 REJECTION_COMPARISON_REQUIRED였다. inspected rejection 전체의 unrelated/reopen 이유와 독립 새 source를 명시한 뒤에만 좁은 offline-record observation을 게시했다. 의미 동등성 자동 검출이나 실제 세계 사실 검증을 서버의 보장으로 바꾸지 않는다.
- 실제 secret/note 경계: synthetic credential capture는422/SOURCE_SECRET_REJECTED/not_started였고, 같은 key의 후속 benign capture는202여서 거부가 key를 예약하지 않았음을 관측했다. whitespace-only private-key armor의 false positive를 재현·수정했고 실제 benign 본문 bytes를 보존했다. agent_note-only remember는 SOURCE_INELIGIBLE였으며 raw note inspect/discard는 가능했다.
- 실제 구형 운영 경로: 기존 immutable0004 패키지는 **합성 schema에서만** capture/pg_dump+age backup에 사용했고 worker·Qwen은 시작하지 않았다. 새 CLI의 authenticated migrate --upgrade-config는0004→0006와 원래 config 보존을 완료했다. 후속 withdrawal 뒤 그 실제0004 archive를 새 restore CLI로 복원해 fresh token 회전·surviving floor 재적용을 관측했다. old operator는 AUTH_DENIED, fresh MCP 조회는 empty였고 old origin replay는 retracted/SOURCE_RETRACTED로 남았다. journal을 archive에서 복원하거나 제공 head의 외부 최신성을 증명했다고 주장하지 않는다.
- 실제 정정·폐기·CLI: producer correction 직후 replacement는 captured이고 old SQLite 후보는 다음 조회에서 빠졌다. agent가 새 원문을 판단한 뒤 다음 MCP/실제 CLI의 JSON expansion·complete relevance 경로가 PostgreSQL 근거만570B로 반환했다. 별도 withdrawn legacy source의 local row purge1을 관측했으며 WAL·backup/media erasure는 unknown이다.
- owned 합성 서비스2개와 재기동1개를 종료하고 두 UUID schema·config/token·임시 archive/key를 제거했다. 비밀 없는 결과·실패·정리 증거는 run-owned private runtime-proof에 보존했다. SDK/CLI 증거를 actual native-host read 증거로 바꾸지 않는다.
- **현재 작업 프로젝트 MCP 연결**: 기존 안정 native command를 실제 feature worktree에서 호출하니 `HOST_SCOPE_UNRESOLVED`로 종료됐다. MCP 전용 CWD 검사를 제거하고, 별도 실제 Git linked-worktree·HTTP·PG 회귀에서 두 checkout의 동일 credential/binding 원문 조회와 다른 binding의 `SCOPE_DENIED`를 검증했다. 자동 capture/protected-action 경로 검사는 유지한다.
- 이어서 가상 저장소 대신 **현재 작업 checkout 자체**에 receipt-owned OMP MCP entry를 임시 등록했다. 안정 corpus와 분리한 UUID schema·app/owner role·새 scoped credentials·수정된 immutable wheel을 사용했다. 등록된 실제 command/args를 공식 SDK client로 실행해 protocol `2025-11-25`와 네 도구를 확인했다. 이번 실제 사용자 발언77 UTF-8 bytes를 capture/inspect하고, 현재 coding agent가 연결 조건을 보존한 source_selection과 relevance를 직접 제출했다. 첫 optional context0 → candidate_ready → 근거 context685B였고 다른 binding은 `SCOPE_DENIED`였다. capture coverage는 unknown으로 남겨 전체 세션 관측을 주장하지 않는다.
- 이는 **현재 프로젝트의 실제 MCP 전송/현재 coding-agent 판단 증거**이지 native host UI/tool invocation 완료나 기존 안정 배포 복구 증거가 아니다. 임시 entry는 owned CLI로 uninstall했고 native trust는 변경하지 않았다. 소유한 service를 identity 확인 후 SIGTERM으로 중지했으며 supervised exit143을 관측했다. UUID schema·임시 config/token/state·driver를 제거했다. 비밀 없는 증거는 `runtime-proof/current-project-mcp-evidence.json`과 개별 호출 결과에 보존했다.
- 후속 fork 경고 수정: 중단·복구 테스트의 `_abrupt_process`가 로컬 closure를 상속하는 강제 fork를 사용했다. module-level fault worker에 operation/인자를 명시적으로 전달하는 spawn으로 바꿨고 parent process handle도 close한다. 실제 write/unlink 직후 exit41과 원래 pending/removing/native cleanup 경계·사용자/AF 항목 보존 assertions는 유지했다. 경고 filter/ignore는 추가하지 않았다. DeprecationWarning을 오류로 처리한 host 전체447개가47.07s에 통과했다.
- 별도 실제 smoke에서도 부모 background thread가 두 child 시작 시점에 살아 있는 상태로 install pending·uninstall removing에서 exit41을 발생시켰다. 재개 후 uninstalled와 기존 native config 보존을 확인했다. `python -W error::DeprecationWarning` 실행이 exit0이었다. 최초 smoke의 동일 agent/producer fixture token은 기존 separation guard가 거절했고, 서로 다른 test credentials로 fixture만 수정했다. 실패/성공 로그를 모두 보존한다.
- **실제 native CLI의 수동 MCP 소비**도 별도로 실행했다. OMP18.10.4의 `openai-codex/gpt-6.1-sol`과 Codex0.162.1의 `gpt-6.1-sol`이 네 MCP 도구를 로드하고, 실제 사용자 원문77/213 bytes를 끝까지 읽어 각자 remember 판단을 제출했다. 서버의 별도 credential 두 개로 committed selection2개와 caller-grounded claim6개가 저장됐음을 독립 DB audit으로 확인했다.
- OMP는 연결 조건을 보존한 claim을 relevant로, 판단 주체에 관한 다른 claim은 irrelevant로 선택해 cited context685B를 받았다. Codex는 다섯 판단 주체·Qwen 제외·lexical/entity 제한을 보존한 뒤 전체6개 후보를 읽고5 relevant/1 irrelevant를 제출했다. recall은3개 인용·1785B·omitted2·partial이었다. 두 client의 권한 밖 binding 조회는 모두 `SCOPE_DENIED/not_started`였다. capture completeness는 unknown이며 자동 capture/enforcement·안정 설치 복구·OMP adapter 소스 pin18.9.1 호환성 증거가 아니다.
- 최초 시도가 모두 성공한 것은 아니다. OMP는 로컬 인자 오류4개와 grounding 거부4개, Codex는 grounding 거부1개와 context 입력 거부2개를 받은 뒤 모델이 입력을 고쳤다. Codex의 잘못된 최초 relay 경로와 기본 MCP approval 거부도 보존했다. 성공은 해당 invocation의 네 선택 도구에만 approval을 지정한 뒤 관측했고 global trust/auth는 바꾸지 않았다. provider schema 거부는 관측되지 않았으나 모든 schema 분기의 호환성을 보장하지 않는다. Codex는 추가로 무관한 공유 후보에 reject를 기록했다. 이유에는 query-only 의도라고 썼지만 **feedback 자체에는 query scope가 없고 원래 source ID가 거절 대상으로 저장됐다**. 기존 claim의 사실 부정·철회·삭제는 아니나 같은 근거의 재제안 차단에 영향을 준다. 이는 요청 밖의 모델 행동이며 올바른 query relevance 제출로 세지 않는다. Codex exit0, OMP native agent_end를 확인했지만 OMP pipeline의 exit status는 별도로 수집하지 못했다.
- 이 native 검증은 **첫 리뷰 전 wheel**의 증거다. 소유한 service child identity를 확인해 SIGTERM/exit143으로 종료하고 UUID schema가 사라진 것을 확인했다. 임시 credential/config/DSN/state/journal/driver는 제거했다. 실제 native event와 서버 receipt, 해시·DB audit·정리 결과는 private 증거 및 `runtime-proof/native-manual-mcp-evidence.json`에 보존했다.
- 첫 공식 native review는 Claude5개·Codex6개가 독립 **request-changes**, Claude I/O1개는600s timeout이었다. 복수 창 discard, 만료 cleanup, 페이지 간 관계 비교, 전체 거절 이력, 관계0 판단의 삭제 전파, 관계 중복·개수 경계, 큰 MCP 응답과 historical/live 실패 분리 등을 지적했다. 정식 fix-loop로 이동했으며 이전1,376-pass나 native 성공을 수정본 검증으로 재사용하지 않았다.
- **첫 리뷰 수정(R1) 회귀**는 `pytest -q -W error::DeprecationWarning --tb=short`로 **1,470 passed, 254.25s, skip0, reported warnings0**였다. ruff와 wheel build도 통과했다. 만료 cleanup·관계0 judgment purge는 이전 immutable wheel에서 실제 실패를 재현한 뒤 수정본에서 통과했다. 중간 전체 실행의1,474 pass/9 fail은 구형 schema fixture가 신규 컬럼을 남긴 데서 발생했다. 정확한 downgrade projection 수정 뒤9개와 전체 실행이 통과했다. 제품 migration에 IF NOT EXISTS를 붙여 오류를 숨기지 않았다. DTO/hash/default·transport-copy 검사는 제거하고 실제 소비 경계 회귀를 남겼다.
- 관계 경계는 DTO 복사/hash/default assertion 대신 실제 PG에서128개 관계 전체를 judgment inspect·recall admission으로 읽고129개째에서 명시 overflow를 확인했다. 전체 회귀에는130회 동일 관계 재판단,21개 claim의 페이지 간 공동 비교,10개 이상 rejection history의 전체 비교·변경 시 거절, 실제 encrypted historical restore도 포함된다.
- R1 wheel의 실제 서비스에서 global source를 요청 snapshot `post-review-request-scope`로 inspect했다. 반환 snapshot은 요청 scope, source_snapshot은 null이었고 실제 사용자 원문77 bytes와 next_byte=null을 보존했다. 이 추가 호출은 API/CLI smoke이며 native 모델의 판단 증거와 구분한다.
- **R1 수정 후 실제 native 수동 MCP**: 새5661495e wheel의 별도 현재 프로젝트 서비스에 OMP18.10.4와 Codex0.162.1을 연결했다. 두 CLI 모두 exit0·stderr0이었다. 모델이 사용자 원문77/213 bytes를 읽고 직접 source_selection과 전체 candidate relevance를 제출했다. 독립 DB audit에서 서로 다른 agent credential의 active remember2개·caller-grounded claim3개·resolved source pending2개·feedback0개를 확인했다. `mcp연결되면` 조건과 Qwen 제외·lexical/entity 제한의 부정 표현이 저장됐다.
- OMP의 실제 근거 회수는685B/인용1개/omitted0, Codex는1338B/인용2개/omitted0였다. 두 결과는 partial이고 session capture는 unknown이다. 권한 밖 binding 조회는 각각 정확히1회 SCOPE_DENIED/not_started였다. 모델은 max_bytes/limit·validity 등의 입력 거부와 grounding 거부를 고쳐 성공했으며 최초 성공으로 표현하지 않는다. feedback은 호출하지 않았고 이 질의의 무관함을 durable reject로 바꾸지 않았다. 이는 수동 MCP 증거이지 자동 capture/enforcement·provider-input attestation·안정 전환·adapter pin 호환성 증거가 아니다.
- 위 임시 service의 final-wheel/config 경로와 child PID를 확인한 뒤 해당 child에만 SIGTERM을 보내 supervised exit143을 관측했다. 소유한 UUID schema의 실제 삭제·부재와 임시 config/DSN/token/state/journal 제거를 확인했다. 원문·receipt·process event·파일 해시와 audit은 private run evidence에 남겼고 안정 schema/config/host는 건드리지 않았다. setup 최초에는 새 schema를 만들지 않아 INIT_RECOVERY_REQUIRED였으며 exact owned intent를 유지한 채 해당 schema 생성 후 명시 --resume으로 완료했다.
- **두 번째 공식 review(R2)**에서는 Codex 독립6개가 모두 request-changes였다. Claude probe는 OAuth 만료401로 실행되지 않았고 나머지5개는 skipped였다. 이전 Claude 결과를 이번 승인으로 재사용하지 않는다.
- R2 수정으로 다중 source legacy 작업의 일부 근거 철회 뒤 살아 있는 source를 pending에 유지한다. 원래 job/retired failure audit은 그대로다. selection의 reason·comparison은 현재 source/rejection/review-receipt 적격성을 매번 확인하며 철회·정정·restore 후 노출하지 않는다. feedback의 별도 source와 명시적 후손에도 삭제 floor와 physical row scrub을 적용한다. 독립 새 근거의 claim까지 지우지는 않는다.
- accepted judgment input에서 미래·만료 claim을 제외하고 실제 `speaker=agent_note`는 human capture capacity에서 제외한다. mandatory rule 없는 정상 empty context는 relevance handoff로 처리하며 미판단 후보 본문을 주입하지 않는다. 만료·나이 불명 legacy spool payload는 secret 검사 뒤 처리해 key/digest가 expiry receipt로 복사되지 않는다. receipt-backed reopening은 최종 direct comparison/prior ID에 다시 열거하지 않되 전체 이력의 일관성을 검증한다.
- **R2 최종 회귀**: 이전 immutable5661495e에서 새 소비 경계32개 중 **31 failed/1 passed**를 관측했다. 수정본은 `pytest -q -W error::DeprecationWarning --tb=short`로 **1,533 passed, 284.29s, skip0, reported warnings0**, lint·wheel build·offline install도 통과했다. 첫 집중 실행의 잘못된 단언5개와 전체 실행의 obsolete selection-window 거절 단언1개는 제거했다. privacy·전체 reconstruction·독립 근거 recall assertions와 실제 operation-window 거절은 유지했다. 실패와 최종 로그는 `runtime-proof/r2-*`에 보존했다.
- **R2 실제 CLI→HTTP MCP**: 새 ee28459c wheel의 UUID 격리 schema에서 합성16-relation judgment **30,645 bytes/8창**과8-comparison selection **17,449 bytes/5창**을 읽고 원래 JSON 전체·SHA256을 복원했다. 각 응답은 TextContent1개였고 관측 최대 wire6,353 bytes로16KiB 상한을 유지했다. 근거 철회 뒤 첫 창과 기존 continuation 모두 reason·relations·comparison·draft window를 반환하지 않았다. 이는 설치 패키지의 실제 전송 증거이며 R2 native-host 모델 소비나 안정 전환 증거는 아니다. 서비스 child identity를 확인해 SIGTERM/exit143으로 종료했고 schema 부재·임시 config/token/state/journal 삭제를 확인했다. throwaway driver도 제거했다.

### R3 수정과 실패 항목 한정 검증

- 관련 rejection 후보 최대8개만 필수 비교하고 전체 history는 명시적 선택 cursor로 분리했다. exact source/body 차단은 색인과 독립이며 current scope·feedback ancestry·별도 reason-source privacy를 먼저 검사한다. note는 raw inspection만 남기고 신규 판단 admission/pending/backlog를 만들지 않는다. 각 관계 판단의 독립 전체 lineage와 공개 duplicate 정규화, non-deriving 철회 뒤 uncovered work 재개/legacy held 보존, 고정 insertion bucket/durable cleanup progress를 적용했다. genuine format-one init과 exact-file SHA256 model intent retirement는 private 원본·unknown 효과를 보존하며 Qwen을 켜지 않는다.
- 분리된 집중 회귀는 서로 겹치므로 합산하지 않는다. 거절/권한51개, 관계/수명주기65개, bounded scheduler12개, 구형 init/승인/restore107개, 중립 표현/실제 admission effect/continuation138개가 각각 통과했다. 대응 로그는 `r3-rejection-scoped-focused.log`, `r3-lineage-focused-grounded.log`, `r3-cleanup-focused-reconciled.log`, `r3-legacy-focused.log`, `r3-inspection-budget-focused-corrected.log`다.
- 첫 전체 strict 실행은 **1,654 passed/4 failed, 456.05s**, 보고된 경고0이었다. 두 실패는 이제 발급하지 않는 note admission을 요구한 구형 검증이어서 제거했고 stronger no-admission/backlog 회귀는 유지했다. 나머지 snapshot modern/legacy 두 실패는 기본 후보를 전체 이력으로 간주한 fixture였다. 전체 비교 개수 단언을 제거하고 실제 선택 history inspection으로 큰 audit를 구성했다. 수정 경계52개가106.52s에 통과했으며 최소4KiB MCP cap의 원문 읽기→grounded publication도 modern/legacy에서 통과했다. 추가 cap/reserve 완화는 하지 않았다.
- 사용자의 **“실패한것들만 테스트해”** 지시로 이미 실행 중이던 전체 재검사를 SIGINT로 중단했다. 중단 시 **1,543 passed/387.74s, exit2**였으며 전체 통과로 기록하지 않는다. 이후 통과 항목/전체 pytest를 재실행하지 않았고 실패 경로만 확인했다. `r3-full-strict-first.log`, `r3-contract-focused.log`, `r3-full-strict-cancelled.log`를 구분한다. 경고 suppression·pyright ignore·test skip/retry를 추가하지 않았다.
- lint와 **sdist+wheel** build가 exit0이었고 새 wheel **79f54ae4ff6fc7e4c95e15de2622abf2e168098914bc9036fad70a48218566ab**를 별도 content-addressed venv에 offline 설치했다. 최종 전체 green을 주장하지 않으며 새 설치의 CLI/SDK 실행은 아래 실패 경로에 한정했다.
- **설치 패키지의 실제 CLI→HTTP→공식 SDK2.3→PG18.6 실패 경로 smoke**: 유효한2,721 UTF-8-byte reject 이유를 포함한 complete feedback JSON **6,900B/2창**을 원래 body/reason/target과 SHA256까지 복원했다. 무관한 write 후 첫 창/digest/offset이 같았고 operator 철회 뒤 첫 창·기존 continuation 모두 본문을 숨겼다. malformed kind 배열은 `INPUT_INVALID/not_started`였다. SDK 결과를 ASCII JSONRPC로 재직렬화한 최대값은11,228B이며 raw SSE/전체 native prompt 비용 측정은 아니다.16KiB cap은 늘리지 않았다. parent-authored synthetic 판단과 네트워크/저장 경계 증거이지 native provider·안정6건 disposition·최종 Agent Flow 설치 증거가 아니다.
- smoke 준비의 잘못된 `python -m agents_memory` 호출은 선언된 console entrypoint로 고쳤다. 누락한 새 schema는 진단 후 생성하고 원래 signed init/token bytes를 바꾸지 않은 exact `--resume`으로 완료했다. SDK tuple을 attribute로 사용한 첫 driver는 session 초기화 전 실패했으며 tuple 계약만 수정했다. 제품 fallback·approval/guard 완화는 없었다. 결과는 `r3-failed-feedback-actual-mcp-corrected.log`에 있다. 정확한 owned child64109를 canonical worktree run-command로 SIGTERM해 supervised143을 관측했고 schema 부재·private profile/token/DSN/state 제거를 확인했다. 임시 probe도 제거했다.
- R3 규범 문서·changelog는 위 bounded 정책으로 갱신했다. 이전 R1/R2의 exhaustive-history·note discard·구형 최신 wheel 서술은 당시 이력이며 R3 기본값이 아니다. fresh official native review/QA/local-handoff와 원래 stable S9/실제 failed6-DLQ6은 아직 완료하지 않았다. 사용자 조건상 모든 #5 항목 해결 전 commit/push/PR, main merge 전 실제 Agent Flow 프로젝트 최종 MCP 설치를 하지 않는다.



### 안정 배포와 공식 run은 아직 완료 아님

CWD 수정 전 wheel은 `89ebae2c36260ed7e425da20ff5660f13e3cb0cdc47dd2bd75e06ac9377b2781`, 첫 공식 리뷰 전 검증 wheel은 `bdcc1d28748aafaa57d270aaac9e8c6c0303ca16d7bac14cb6ca8fddeca7c473`, R1 검증 wheel은 `5661495e4196ada11c6b04be3d3485a173083fd8ec2d18266be0538fd62c1011`이다. **R2 검증 wheel SHA256은 `ee28459c9050521355d50d5aa7d4839cd2d5754bdb65b01827e50930e40a85df`**이며 별도 immutable hash 경로에 offline 설치했다. R2 실제 CLI/service import는 해당 venv였다. 이전 환경·실패 증거는 덮어쓰지 않았고 R1 native 결과를 R2 실행으로 재사용하지 않는다. 임시 프로젝트 검증은 안정 전환 완료를 뜻하지 않는다. 최초 MarkupSafe 캐시 부재와 같은 lock/hash의 공개 binary wheel 설치 이력도 보존한다. 모델 download/provider fallback은 켜지 않았다.

사용자가 block/drain→encrypted backup→immutable package/schema/receipt-owned host 전환·native read를 승인했으나, 현재 AF host binding은 feature worktree뿐이다. 정식 run-command의 leader-root host-uninstall이 outside-bound-worktree로 **실행 전 차단**됐다. run-command --help에는 외부 root 승인 옵션이 없다. 보호를 우회하거나 binding/guard를 바꾸지 않았다. 따라서 안정 DB/config는0004 그대로, v3 host3개는 installed 그대로이고, 안정 서비스8768의 listener는 관측되지 않았으며 프로젝트 Qwen9877 listener는 아직 중지하지 않았다. 기존 failed6/DLQ6의 exact job/source/error/attempt/time metadata는 전환 전 증거로 보존했지만 해결 완료나 historical-only로 표시하지 않는다. 안정 DB backup·migration·host 전환·fresh stable native read는 미완료다. 첫 fresh review는 위 request-changes로 끝났고, 수정 후 재리뷰·공식 QA/local-handoff도 미완료다. 리더 경로를 정식으로 운영할 실행 컨텍스트가 필요하다.
당시 publication/운영 controller `w18:p9`는 현재 live inventory에 없었다. 사용자 선택에 따라 리더-cwd 운영 컨텍스트를 열려 했으나 그 pane 생성도 동일 guard가 실행 전에 차단했다. 새 controller나 안정 운영 변경이 실행됐다고 기록하지 않는다. 이 설치/운영 실행 경계는 연결된 MCP의 권한이나 리더 필요 조건이 아니다.
후속 현재 inventory에도 정식 leader 운영 agent는 없었고 `run-command --help`에도 외부 checkout 권한 옵션은 없다. PATH의 `agent-flow status/continue`에는 installed assets가 kit보다 오래됐다는 별도 안내가 나타났고 `agent-flow-kit`는 PATH에서 실행되지 않았다(exit127). 반면 프로젝트의 **managed launcher**로 실행한 status에는 그 안내가 없었다. managed launcher는 기존 `.agent-flow/runtime/python`과 지정 Python을 사용한다. 진행 run에는 이 고정 실행 경로를 사용하며 asset/binding/guard snapshot을 갱신하지 않는다. pytest fork 경고와 구분한다.
공식 Codex reviewer stderr에는 별도로 임시 sandbox의 PATH helper 생성 거부 안내가 있었다. 해당 reviewer들은 결과를 반환했으며 이를 제품 pytest 경고나 MCP 권한 오류로 바꾸어 설명하지 않는다. 보호·global 설정을 완화해 안내를 숨기지 않았다.

PMPA·secret/content re-entry·host native memory 공존 시나리오와1–2주 paired on/off trial 기준은 architecture9–10절에 정의했다. **trial은 시작하지 않았고 memory-health 측정·publication/commit/push/PR/merge·native 로그인/trust 변경은 하지 않았다.** 사용자는 이후 검증 준비가 됐을 때 commit/push/PR을 조건부 승인했으며, 현재는 리뷰 수정 때문에 보류 중이다.

## 보존된 이전 실행 기록

이하의 Qwen·회사 lexical 전용 경로와 “현재/최신” 수치는 각 이전 실행 시점의 이력이다. 위 공통 경로의 기본값이나 이번 run의 검증 결과로 재사용하지 않는다.


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
- 당시 Canonical config key는 memory 권한 확장이 아니었다. 그 시점에는 다른 CWD의 native relay를 HTTP/token 사용 전 `HOST_SCOPE_UNRESOLVED`로 종료하는 회귀가 있었으나, **현재 공통 경로에서는 이 MCP CWD 제한을 제거했다**. 위 최신 전환 절의 credential/binding 기반 두 checkout 검증을 따른다. 설치 ownership 충돌 검사와 자동 hook의 CWD locator 검사는 별개로 유지한다.

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

## AF 승계 실행의 이전 증거 — 2026-10-12

공식 v0.3.15/source `5b92996a38c6411c61f36d7be10aed1dc26405e5` 프로젝트 설치와 승인된 timeout forwarding delta로 `development/20261012-113028`을 시작했다. 중단된 old run의 verdict를 새 approval로 쓰지 않는다.

| 변경 경계 | 실제 관측 | 제한 |
|---|---|---|
| 전체 gates | 공식 local `gates --phase all`: lint/test/package 3/3, **845 passed in 101.34s**, wheel/sdist 생성 | fresh formal review·QA/handoff 완료와 별개 |
| 기존 config 보존 | 실제 CLI의 중복 model purpose를 write 전에 거절, 기존 bytes unchanged·재로드 유효 | production config·모델 설정을 바꾸지 않은 negative smoke |
| 원천 시간 | 실제 Qwen 추출·consolidation 뒤 OLD event `2020-01-02T00:00:00Z`, NULL event `null`; 원래 source recorded_at을 recall/inspect에 동일 전달 | claim 생성 시각과 validity를 대신하지 않음 |
| binding 이전 | 같은 ID의 locator old worktree→stable 리더, revision 1→2·roster 2 유지·exact replay | 소유권·grant·frozen rule target 불변; 새 memory 복제 없음 |
| deleted native cleanup | Claude/Codex/OMP owned modern receipt 정리, 삭제된 root 재생성 없음, stable 리더 설치 | 다른 native 설정·trust·private credentials/spool 보존; 미완료/legacy recovery 거절 |
| 실제 세 native 소비 | 각 host가 context 1회·inspect 2회 성공, OLD/NULL event/recorded/speaker 값 일치 | selected tools 명시 호출; native hook 신뢰·첫 행동·모델 준수·후속 provider input 증거 아님 |
| malformed native state | 실제 installed Claude `host-hook`가 `HOST_STATE_INVALID`, bytes unchanged·본문 offer 없음 | advisory mode warning/refusal이며 strict native denial 성공이 아님 |

이 시점의 승인 route는 `38f1609ae94d2c2bacd713b5c2a012d4447e68c72ff95eb0b317b77e72431842`였다. 이 승인은 실제 추론 성공과 별개이며 기존 model artifact/purpose/CPU·timeout 설정을 바꾸지 않았다. Source time smoke의 claim은 원래 event time과 recorded_at을 분리하고 `valid_from`/`valid_until`이 null인 상태를 실제 저장 projection에서 확인했다.

원래 시간 provenance reflection operation은 당시 **failed / `MODEL_OUTPUT_INVALID`**였다. 정확한 original query·admission을 이용한 별도 읽기 전용 진단은 `source_event_time of ...`/null identifier prose를 생성했고 validator가 거절했다. 이것을 원래 terminal operation의 정확한 비공개 응답 재현이라고 주장하지 않는다. 당시 timestamp annotation 방식의 실패는 보존한다. 아래 fix-loop에서 모델의 metadata 재서술을 없애고 원래 실패 owner를 명시적으로 retry한 후속 결과와 구분한다.

Native 모델은 모두 요청 argv에서 xhigh다. Claude 출력은 `claude-opus-5-5`, OMP message는 `gpt-6.1-sol` model ID를 관측했다. Codex는 served model/effort를 노출하지 않아 argv 근거만 기록한다. 전체 host input token 수를 memory-only overhead로 해석하지 않는다.

원문 source-time·config·locator·native state·세 host의 sanitized 실행 증거는 `docs/research/2026-10-12-memory-skills/*-live-smoke.proof.json`과 `duplicate-purpose-smoke.proof.json`에 있다. raw provider internals·credentials는 source/이슈에 포함하지 않는다. fresh formal review·QA·handoff 결과는 실제 runner 완료 후 덧붙인다.

## 첫 fix-loop 실행 증거 — 2026-10-13

`development/20261012-113028`의 기존 12-review 결과는 수정 전 **7 approve / 5 request-changes**, overall request-changes다. 아래 구현·실행 확인은 fresh 공식 review나 QA 승인으로 대신하지 않는다.

| 경계 | 실제 관측 | 증거 층위·제한 |
|---|---|---|
| 전체 gates | 공식 local lint/test/package 3/3 green, **885 passed in 104.52s**, zero skips, wheel/sdist 생성 | `artifacts/gate-results.json`; 현재 코드 결과이며 formal review·QA는 별도 |
| temporal reflection | 원래 OLD/NULL query와 source 그대로 새 reflection `reflection_9544ce2314504c8f92999afc6d75e579` active; event 2020/null·distinct recorded clocks 전달 | 실제 local service와 최신 stable package의 native MCP 결과; 모델 clock prose 예외 없음 |
| 원래 실패 owner 복구 | `operation_c0cb8fc6edb940a7b352cccfd4ec3b8c` 명시 retry 후 semantic_ready, 새 artifact `reflection_21ea3838f4bf4fb6b256e02a6a7a5968` | 원래 실패의 삭제·재분류가 아닌 후속 attempt |
| 일반 assertion | 실제 “Explain how extracted claims differ from approved rules.” 질문에서 `reflection_20fc50c053504b03bf7996fcfec1b5a0` 성공 | 시간 질문만 성공시키는 special case 아님; 일반 factual entailment 보장은 아님 |
| full pipeline | synthetic FrameR26 37초 capture→extraction/consolidation→recall→reflection, 41초 trusted correction→이전 reflection 숨김→다음 recall의 새 claim | 실제 승인 route·서비스; 이후 명시 retract 완료 |
| retract 후 native read | 최신 immutable package의 실제 Codex가 corrected source/claim inspect에서 `retracted` 및 본문·evidence 없음, temporal reflection은 active | authenticated plain stdio, worker cwd, TextContent 단일 plane; 설치된 leader receipt 경로의 증거는 아님 |
| reranker | 실제 relevant/irrelevant pair 236/245 tokens, raw cross-encoder score 5.4071879386901855 / -10.908003807067871; synthetic long pair 9,295 tokens는 `MODEL_INPUT_TOO_LARGE` | 기존 8,192-token bound, truncation/forward 이전 거절; 확률·보정·일반 정확도 주장은 아님 |
| host hook | 실제 filesystem self-symlink loop에서 strict body-free native deny/exit0, advisory warning/exit0; durable state unchanged | 실제 CLI/adapter, 실제 Claude interactive session이나 OS sandbox가 아님 |
| deleted cleanup | normal/linked Git root × receipt durability/native-key publication 두 cutpoint에서 실제 child abrupt exit 후 반복 uninstall 성공 | 네 경우 모두 absent root 재생성 없음, 무관한 native 설정 보존 |
| approval recovery | actual artifact validation + isolated PG의 publication 후 journal barrier→확정 config 보상·not_committed·무관한 queue 보존; barred pending exact retry는 unknown; 복구 후 exact retry와 새 consumer admission 성공 | live authority journal을 손상시키지 않음; flock/bytes guard는 arbitrary same-UID CAS가 아님 |
| final comments | 추가된 fixture-clock 근거 comment 2줄, configured checksum과 같은 canonical checker SHA256 `0eb61a66acdd1ec4031c4cb8aedf78aced785f0b69c46e50a0234241adbd3f5f`, exit0·stdout/stderr empty | 최종 comment-only pass, native hook trust 승인과 별개 |

현재 semantic route는 `d42da38effe7c83029ac9e691e94188cc64d6b05d5b5e936e1b1229b5b540463`, embedding geometry는 `5746aa946889325cd26d84aafb3e1ac05ae4fccba400bfc6597431b26a1ac13a`다. 실제 shaping의 `models.py`도 semantic fingerprint에 포함한다. clocks는 code-attached provenance이며 event unknown을 recording/extraction/validity/승인으로 승격하지 않는다.

최신 wheel SHA256 `afd0b5ee427da2a7509ce7d191d04eb52c15cdc8501d73477c58da9bf495ec6c`를 checkout 밖 private immutable venv에 locked/offline noneditable 설치했다. `python -I`에서 CLI/hosts/models/semantic/contract/store가 모두 그 site-packages를 사용하고 worker import path가 없음을 확인했다. 실제 model artifacts도 검증했다. owned 서비스 R28은 그 interpreter로 port8768에서 실행 중이다.

당시에는 세 leader host receipt의 executable이 worker venv였다. 이후 active run이 없는 상태(아래 “설치형 leader 연동”)에서 owned uninstall/reinstall로 stable package에 옮겼다. guard는 바꾸거나 우회하지 않았다.

epoch343의 실제 stats는 pending0/blocked0/**failed6/DLQ6**/stale_index0이다. 이전 invalid-output probes와 추가 살아 있는 실패 row가 남아 있으며 “전역 clean” 또는 historical-only라고 하지 않는다. 실패 row/원문을 삭제하지 않았다. 원래 failed source-time proof SHA256 `0d50ab8b6c5f46d4d43416cf5b3a2e1251ad74d490e2a1c858a399e8b8ee346d`는 보존한다.

현재 native/package 결과는 `docs/research/2026-10-12-memory-skills/stable-runtime-native-smoke.proof.json`, fix-loop 실행 관측은 `fix-loop-live-smoke.proof.json`에 기록한다. 이전 transient smoke stdout을 새 실행 transcript로 꾸미지 않는다. selected-tool per-invocation approval은 permanent workspace/hook trust·회사 native 무인실행/egress 승인·final provider-input attestation이 아니다. 레지스트리·원격 MCP 배포·회사 capability 구현은 하지 않았다.

## Fresh native 지적 수정과 현재 재검증 — 2026-10-13

공식 runner가 첫 fix-loop 수정 후 새 review를 실행했다. 실제 Codex6개는 **3 approve / 3 request-changes**이며 manifest의 각 artifact SHA256을 검증했다. Claude generalist는 **exit1 / OAuth token expired401**, 나머지5개는 skipped다. 이전 Claude 결과는 대체하지 않는다. 두 blocking 결함 종류는 아래에서 수정했고 I/O angle의 purpose narrowing needs_validation도 확인·수정했다. 이는 후속12개 리뷰 승인이나 QA 완료가 아니다.

| 변경 | 실제 관측 | 제한 |
|---|---|---|
| reflection limitations | 실제 PG publication→Application.inspect에서 원문에 grounded된 caveat가 보존되고 candidate true/partial false | validator-checked manually supplied synthetic fixture; LLM generation 결과라고 하지 않음 |
| 전달 budget | limitations 우선, caveat overflow 시 assertion 없음·partial true, 문장/provenance 합산과 JSON comma-space까지 포함 | 영속 publish→inspect 회귀가 4,097-byte 경계도 검사 |
| 확정 승인 보상 | config의 확정 보상 뒤 intent unlink+directory fsync로 종료; revoke/generation 변경 후 현재 operator의 새 승인 가능 | unknown adoption·compensation intent는 자동 삭제하지 않음 |
| crash→restore 복구 | actual artifact validation + isolated PG, 실제 CLI route commit 직후 child exit41→실제 private restore authority recovery→옛 credential 거절·route disabled→implicit replacement 거절→fresh operator의 exact-hash 새 승인·consumer claim admission 성공 | Store.recover_after_restore 경로이며 archive SQL executor smoke로 바꾸어 주장하지 않음 |
| same-revision purpose 축소 | actual CLI에서 embedding만 승인; old-settings Store의 새 rerank/기존 rerank admission 거절, 기존 embedding admission stale, 새 embedding admission 허용 | 별도 native daemon이 아니라 실제 PG를 사용하는 이전 설정의 Store instance |
| 전체 검증 | 공식 lint/test/package green3/3, **892 passed in 105.17s**, zero skips; 최종 comment checker exit0/empty output | reviewer fix 후 소스 결과; 전체12 native pool·QA/handoff는 아직 미완료 |
| 최신 stable native | 최종 package의 실제 Codex MCP inspect4회 성공/exit0/no stderr; 일반 reflection의 원래 저장된 caveat4개가 이제 전달되고 temporal provenance·철회 body-free 결과도 유지 | actual TextContent payload 확인; worker plain authenticated stdio이며 installed leader receipt cutover 아님 |

증거: `docs/research/2026-10-12-memory-skills/fresh-review-fix-smoke.proof.json`, `fix-loop-final-comment-checker.proof.json`. 새로운 CLI 승인 옵션과 limitations 전달 계약은 README에 반영했다. 원래 실패·첫 fix-loop proof는 보존하고 새 실행으로 덮어쓰지 않았다. Semantic route/vector geometry는 이 store/CLI 수정으로 바뀌지 않는다.

README 최종 안내를 포함하여 wheel/sdist를 다시 build했고, wheel SHA256 `84ba86ade65a208e4f8390fbec59910e72fcd95e86b35b3ba7700b904e24a72e`를 immutable offline/noneditable private venv에 설치했다. isolated imports·actual model artifacts·unchanged d42 semantic/vector revisions를 확인했다. 현재 owned 서비스는 **R29 / pid41455 / port8768**이며 R28은 정상 TERM 종료했다. `final-stable-native-smoke.proof.json`은 원래 Qwen-generated ordinary reflection의 caveat4개를 실제 native read에서 관측한 증거다. 위 수동 fixture와 구분한다.

Claude native auth metadata는 loggedIn true/claude.ai/firstParty였지만 실제 confined reviewer의 OAuth 만료401을 무효화하는 증거는 아니다. OAuth env override도 없고 Claude provider는 credential 복사 방식이 아니다. sandbox/credential/모델 pin을 변경하지 않았다. 사용자가 native `claude auth login`으로 재인증한 뒤 같은 공식12-pool review를 재개해야 한다. account/token 값을 공개하거나 비공식 reviewer로 대신하지 않는다.

### 최신 사용자 승인: Codex 전용 fresh 공식 리뷰

사용자는 “클로드 빼고 코덱스로 리뷰하고 넘어가 그냥”으로 이전12개/두 provider 조건을 명시적으로 변경했다. 이 기존 run은 지원되는 invocation-scoped `AGENT_FLOW_REVIEWERS=codex`로 **fresh Codex6개 angle**을 실행한다. gpt-6.1-sol/xhigh·같은 local architecture·독립 confined process·actual artifact SHA/verdict·QA/handoff gates는 유지한다. leader profile/runtime/pin/보호 규칙/global 설정은 변경하지 않는다. 이전 수정 전 Codex6개의 3 approve/3 RC를 새 승인으로 재사용하지 않는다. Claude 로그인 대기는 종료했으며 OAuth 문제가 해결됐다고 주장하지 않는다. 이 run의 완료 전제가 더는 Claude 재인증은 아니지만 회사 capability와 회사 native 무인실행 승인은 별도 경계다.

## 관측된 운영 한계

- reads도 전역 clock lock·journal 검증·artifact pin 검사를 사용하는 보수적 구현이다. journal/corpus 증가에 대한 p50/p95나 다수 동시 workflow의 성공률·처리량을 아직 실측하지 않았다.
- local interactive model admission은 bounded이며 실제 cold 동시 recall에서 `MODEL_BUSY`를 관측했다. 무한 대기·무제한 parallel inference·외부 fallback으로 바꾸지 않는다.
- required UNKNOWN은 일반 context에서 body-free opaque ref/미결 개수만 전달하고 protected action에서는 거절한다. generic caller host/purpose/path hints는 실행 authority가 아니며, native final provider input이 보이지 않는 경로는 strict enforcement 성공으로 표시하지 않는다.
- 기존 age envelope magic·migration advisory lock·restore executor/interlock 이름은 persisted 호환·동시 실행 안전을 위한 고정 protocol identity다. 제품 이름 변경으로 이를 바꾸거나 삭제 저널·backup을 무효화하지 않는다.


## 다음 사용자 trial

private personal/synthetic deployment부터 사용한다. actor/token/프로젝트 grant를 명시하고 회사 customer corpus와 섞지 않는다. root rulebook 대신 필요한 규칙만 승인·선택한다. `stats/doctor/inspect`로 pending/blocked/DLQ/gap를 확인한다. 실제 trial 시작 시각과 매일 correction reuse·qualification omission·false claim·false rule promotion·restore/replay·호스트 gap·wire/context bytes·latency/운영 부담을 body-free metadata로 기록한다.

미승인 egress, realm 누출, 철회 부활, 무승인 rule activation, strict gap를 정상 allow로 보고, root corpus 설치 또는 중복 효과가 나오면 즉시 중단한다. 1–2주 실제 사용 이후에만 개인 cloud(TLS/OAuth audience, deploy identity, durable journal witness, network/backup)로 전환한다. 회사 자료는 이전하지 않는다.

## 설치형 leader 연동 — 2026-10-13

Agent Flow가 설치된 leader 프로젝트에서 실제 설치 경로로 연동을 검증했다. 진행 중이던 빈 bugfix run `20261013-040212`는 leader 보호를 우회하지 않으려고 abort했다(산출물 보존).

| 단계 | 실제 관측 | 한계 |
|---|---|---|
| 패키지·route | 현재 worker 소스 lint/test/package 통과(**917 passed**). immutable wheel `0086e6c930c8…` 설치, route `9e01d646…` 재승인, 서비스 R30(127.0.0.1:8768) | 3차 host 수정의 fresh 독립 리뷰는 아직 남음 |
| host cutover | Claude/Codex/OMP owned uninstall→reinstall 모두 exit0. MCP·hook 명령이 stable python을 가리키고 worker 경로가 사라짐. `.claude/settings.json` 바이트 동일, AF hook 등 비소유 항목·native 다른 키 동일 | 이미 실행 중인 OMP 세션은 재시작해야 새 extension을 쓴다 |
| record→recall | Claude 세션 `memory_record` → operator `await` semantic_ready(+1 source/+1 claim) → Codex 세션 `memory_context`·`memory_inspect`가 같은 claim(`agent_note`, approved rule 아님)을 읽음 | 예외 구절이 statement 안에 남고 conditions/exceptions로 분리되지 않음 |
| feedback | OMP 세션 `memory_feedback correct`는 candidate로 남고 원래 claim은 active 그대로 | 운영자 승인 경로는 별도 |
| reflect | Claude 세션 reflect → semantic_ready reflection(근거 claim 인용, limitation 2개) → Codex 세션이 같은 reflection을 읽음 | 모델 품질 일반화 아님 |
| capture | 세 spool pending0/gap 없음. Claude `--print`는 문서화된 `HOST_PROMPT_ORIGIN_UNOBSERVABLE` gap | Codex는 신뢰되지 않은 프로젝트라 project config·hook을 읽지 않아 설치된 command/args를 호출별 승인으로 전달. 신뢰 설정은 바꾸지 않음 |

증거: `docs/research/2026-10-12-memory-skills/installed-leader-integration-r30.proof.json`. 원문 transcript는 private checkpoint에만 0600으로 둔다. live stats는 여전히 failed6/DLQ6이다.

## Bugfix 이후 stable 교체·native 읽기 — R31

수정된 worker 소스로 wheel `3ad2fb0a4627eee3ca62a66c5d5508d6af55470dc457192dce78e07728332172`을 빌드했다. hash별 venv에 locked/offline dependency와 wheel을 설치했고, 설치된 `agents_memory` 소스가 worker와 동일함을 확인했다. R30 대비 package 소스 변경은 `hosts.py`, `private_io.py`다. 이번 세션에서는 이전 bugfix의 테스트를 재실행하지 않았다.

semantic contract digest는 두 package 모두 `9ef2866ed43795fe10b537fb5e000f7bc0357eb675aa7d87bae7c4e02062c7df`, 새 package의 route revision은 기존 승인값 `9e01d6468d901c3f42c0f90b21db535dee25894572450ba7e2290dadab01ef59`와 동일했다. 재승인 없이 R30 PID9379를 종료하고 R31 PID96967을 `/tmp`에서 시작했다. `127.0.0.1:8768` ready, doctor·stats exit0을 관측했다.

Claude/Codex/OMP owned uninstall→install은 모두 성공했다. 첫 install의 기본 operator credential은 `AUTH_DENIED`, effect `not_started`였고, 복원 후 operator token을 명시해 설치했다. `.claude/settings.json`과 OMP AF extension의 바이트 hash, 기타 hook/MCP/TOML 설정, `.claude.json`의 leader 다른 키·다른 project·top-level 키 목록 등 비소유 비교 9개가 모두 일치했다. 세 host의 MCP/hook/extension 명령은 새 stable python을 가리킨다. strict·prompt-recall은 꺼져 있고 native trust는 바꾸지 않았다.

현재 controller OMP pane은 유지했다. 다른 실행 중 OMP 4개는 별도 프로젝트 세션으로 확인돼 종료하지 않았다. 이전 leader OMP PID2009와 host-stdio PID2030은 후속 process inventory에 없었다. 새 leader cwd의 OMP process에서 설치된 extension을 로드해 native 읽기를 확인했다.

| Host | 실제 관측 | 결과·한계 |
|---|---|---|
| OMP | 새 process의 `memory_context`·`memory_inspect`, exit0 | 순차 smoke에서 두 도구 오류 없음; served model `gpt-6.1-sol` |
| Claude | `memory_context`·`memory_inspect`, exit0 | 도구 오류 없음; served model `claude-opus-5-5`; print prompt capture 보장은 아님 |
| Codex | `memory_context`·`memory_inspect`, exit0 | 순차 smoke에서 두 도구 completed; 호출별 선택 도구 승인, permanent leader trust 아님; served model 미보고 |

세 host가 synthetic R30 claim `claim_b159614a725e4aac894706c906eec5c4`를 recall하고 inspect했다. 근거 화자는 `agent_note`, `approved_rules=[]`이며 inspect에는 `approved_rule` 필드가 없다. 후보를 승인 규칙으로 승격하지 않았다. recall은 기존 live failed6/DLQ6 때문에 `partial`이고 pending0/blocked0/stale_index0이다.

첫 동시 smoke에서 OMP/Codex recall은 모델 슬롯 충돌로 `MODEL_BUSY / not_started`였다. 실패 transcript를 보존하고 두 host를 순차 실행했다. 재시도 기능이나 서비스 코드는 바꾸지 않았다. 합성 개인 입력만 사용했고 회사 데이터·배포·push·commit·AF guard 변경은 없다.

증거: `docs/research/2026-10-12-memory-skills/installed-leader-integration-r31.proof.json`. 원문 transcript는 private checkpoint에 0600으로 보존한다.

## 회사 lexical/entity capability A — no-model 실행 증거 (development/20261013-103527)

공식 run의 implement phase 안에서 수행한 parent 통합 검증이다. 이후 공식 native review·QA·local-handoff 결과로 대신하지 않는다.

### Profile gates (최종 코드, worker cwd)

- `uv run ruff check src tests` 통과. `uv run pytest -q` **1127 passed, skip 0** (실제 PG_TEST_DSN, age/age-keygen, docker 모드 pg_dump/pg_restore/psql). `uv build` 통과, wheel SHA256 `454f922ac5872165f97cfb54fbb5debc52539d68fdfe983b2dd4abfd408a5227`.
- 통합 중 실제로 발견해 수정한 결함: 0005 DDL의 JSON default `"original_bytes":null`이 SQLAlchemy bind parameter로 해석돼 migration 실패(`jsonb_build_object`로 교체), purge-floor scrub의 generator 안 `await`(`TypeError`), capture 상태 안내가 opt-in recall 본문을 budget 밖으로 밀어낸 우선순위 오류, 과거 schema fixture의 0005 역변환 누락, 이전 archive allowlist의 revision 대응. 회사 `required-context`에 실제 빈 nonmodel admission을 연결했다.

### 격리 합성 service smoke

- 환경: 새 venv에 wheel `d266b14a92224aed05fdadf68a87926625a2a48136164a7a931466b2221f777f`와 core 의존성 35개만 설치했다. `torch`·`sentence_transformers`·`llama_cpp`·`huggingface_hub`·`transformers`는 설치되지 않았다. 모든 CLI·service process를 `agents_memory.models`와 위 package import를 막고 기록하는 guard 아래 실행했다. 41개 process report 모두 import 시도 0, 적재 0이다. 소유한 임시 schema `am_smoke_company_*`, 독립 journal/state, 임시 port를 사용했고 끝난 뒤 schema와 DSN 파일·venv를 제거했다.
- init `--mode company --capability lexical_entity`: migration `0005_company_selection`, PG180006/vector0.8.7. `readyz`·`doctor`: `semantic_capabilities=unsupported`, `lexical_entity=available`, `background_inference=unsupported`, `model_route_configured=false`.
- capture: 한국어+식별자 원문 54 UTF-8 bytes → `captured`, `capture_disposition=captured`, body-free pointer(speaker human, `source_event_time=null`, `observed_window`). MCP `memory_inspect` window는 0–54/partial=false/span 1개였다.
- 판단: grounded remember → `candidate_ready`(CLI `await` 동일). 같은 key replay는 같은 operation, 같은 key의 다른 판단은 `IDEMPOTENCY_CONFLICT/not_started`. discard·review는 `selection_recorded`이며 label 집계 remember1/discard1/review1, claim은 remember 하나뿐이었다. 원문에 없는 식별자는 당시 wheel에서 `MODEL_OUTPUT_INVALID/not_started`로 거절됐다. 모델이 없는 caller 판단이므로 이후 `SELECTION_GROUNDING_INVALID`로 바꿨고, 이 변경은 실제 PG 회귀(174개 boundary 포함)로 확인했다. service smoke는 이전 wheel의 관측이다.
- recall: `capability=lexical_entity`, arms `["entity","lexical"]`, limitations 네 개, context 622 bytes/wire 1,916 bytes. claim inspect는 원문 quote·byte 0–54·speaker·nullable event time·recorded time과 `caller_grounded_candidate`를 반환했다. reflect는 `CAPABILITY_UNAVAILABLE/not_started`. `index-status`는 `vector_revision=null`, `stale_index_claims=0`.
- 실제 `/api/correct`: 원래 source와 claim은 `retracted`/본문 없음. 정정 source를 remember한 뒤 새 agent credential의 다음 recall은 14일 claim 하나만 반환했고 이전 문장은 없었다.
- coverage: 판단하지 않은 source와 `truncated` capture가 있으면 `unclassified_sources=2/incomplete_sources=2`, recall `partial`. truncated window inspect는 partial=true/status truncated.
- budget·rule: max_bytes 256 recall은 `partial`/0 bytes/omitted1이며 잘라 보내지 않았다. local-project required rule 승인 뒤 `/api/required-context`는 200/required=true/본문 포함.
- fence: policy disable 뒤 recall·record는 `SELECTION_POLICY_BLOCKED/not_started`, required-context는 503 같은 code(fail-closed). 이전 epoch 승인은 `SELECTION_POLICY_STALE`. 재승인 뒤 recall 복구. 폐기한 agent credential은 401 `AUTH_DENIED`, producer의 read는 403 `ROLE_DENIED`.
- purge·restore: 철회 없는 purge는 `RETRACTION_REQUIRED/not_started`. 실제 age+pg_dump(docker) backup 뒤 정정 source를 retract→purge(`physically_purged`, backup retention unknown)했다. service 중지 후 이 이전 archive를 실제 restore했다: committed, tokens rotated, jobs fenced, routes disabled, migration 0001–0005. 이전 operator는 `AUTH_DENIED`, policy는 비활성이며 재승인 전 recall은 `SELECTION_POLICY_BLOCKED`. purge된 source는 `purged`/본문 없음, 같은 origin replay는 `retracted`, 재승인 뒤 recall에 14일 문장이 없었다.

### 경계

- smoke는 race를 순차로 재현했다. `tests/test_company_authority.py`의 publication·delivery 회귀도 admission이나 window를 얻은 뒤 grant·revision·policy를 바꾸고 다음 호출이 거절되는지를 순차로 확인한다. 실제로 동시에 실행되는 race 증거는 아니다.
- 첫 service는 SIGTERM으로 종료돼 atexit import report가 없다. 둘째 service는 SIGINT로 종료했고 report가 있다. guard는 process 안 import 시도만 기록하며 OS 전체 egress 차단 증거가 아니다.
- 이 smoke와 회귀는 native host 실행, 실제 회사 운영 승인, optional native classifier B, 1–2주 trial을 대신하지 않는다. evidence JSON은 private runtime의 `company-smoke-20261013T211728/`에 0600으로 보존했다.

## PR #4 운영 P2 회귀 — 2026-10-13

독립 `feat/pr4-ops-fixes`의 공식 bugfix `20261013-121905`에서 published source 그대로 CLI 입력 누락12건·marker/token 발행 실패4건을 준비했다. reproduce와 implement-fix의 실제 preflight는 각각 exit1/**16 failed**였다. source 수정은 implement-fix RED 이후에만 적용했다.

최소 수정 후 `tests/test_cli_boundaries.py`와 `tests/test_ops_boundaries.py`는 실제 **137 passed**, exit0이었다. local missing/partial PG 옵션, 세 옵션 각각의 bare/relative/absent/nonexecutable 경로 거절, marker 발행 전후 및 fresh token 쓰기 전후 중단을 검증했다.

실제 owned PG18.6/pgvector0.8.7 Docker와 age에서 임시 isolated schema를 사용했다. encrypted backup의 첫 marker 발행을 실패시키면 **not_started·marker/token 없음**, 같은 archive/head/operator/`operator-out`의 exact retry는 **committed**였다. marker를 발행한 뒤 실패시키면 **UNKNOWN·token 없음·authority 차단**이고, 현재 operator의 private recovery 뒤 fresh token만 인증됐다. CLI backup→restore→restore-recover도 host PG 경로를 생략한 Docker 입력으로 성공했고, 각 이전 token은 거절됐다.

이 증거는 실제 Docker PG 도구와 host age 경로를 사용한다. host에 PG18.6 local executables가 없어 local PG 성공을 실제 실행했다고 주장하지 않는다. 개인 live DB schema·회사 데이터·host 설정·배포·AF guard/config/pins는 변경하지 않았다. 전체 공식 review/QA/gate 결과는 해당 run의 artifacts와 최종 private handoff를 따른다.

## 회사 capability A fix-loop — 2026-10-14

공식 `development/20261013-103527`의 round-2 리뷰 수정 뒤 검증이다. 위 implement smoke의 required-context와 selection policy 결합은 이 수정에서 폐기됐다. 아직 fresh native review·공식 QA·local-handoff 완료 증거는 아니다.

- worker에서 `agent-flow run-command`로 ruff, 실제 PG/age/Docker runtime의 pytest, uv build를 실행했다. **1244 passed, skip 0**, lint·package exit0. wheel SHA256 `b26e6f09b1788fc88bb83d04f547f80cdcf6c88732f9d2f40fda6c9ab339fe23`.
- core-only wheel을 격리 venv에 설치하고 실제 loopback service를 실행했다. 회사와 개인 synthetic deployment는 독립 schema·journal·state·credential·port를 썼다. kind 없는 note와 flat MCP tool schema를 확인했다. 개인 schema에는 `source_selection`이 없었다.
- 한글 dense 원문은 첫 smoke에서 `RESULT_TOO_LARGE`로 실패했다. SDK가 바깥 JSON 문자열의 비ASCII 문자를 escape하는 wire 비용을 estimator에 반영한 뒤, 같은 유형 원문을 실제 MCP로 **7개 연속 window**에서 읽어 원문과 정확히 재조립했다. 최대 wire **14,392/16,384 bytes**, span **59/128**, 마지막 `next_byte=null`이었다. 한글 dense 원문의 두 capability 회귀도 전체 suite에 포함된다.
- selection policy를 실제 비활성화한 뒤 `/api/required-context`는 **200/required=true**로 승인 규칙을 전달했고 candidate recall은 `SELECTION_POLICY_BLOCKED`였다. relocate→현재 policy 재승인 뒤 기존 candidate 한 개가 계속 recall됐다. 모순된 observed byte coverage는 **409/CAPTURE_COVERAGE_INVALID/not_started**였다.
- 두 retract된 source를 별도 CLI process에서 같은 purge key로 동시에 요청했다. 한 process만 `physically_purged/exit0`, 다른 process는 **IDEMPOTENCY_CONFLICT/exit1**이었다. 이것은 실제 동시 실행 증거다. 다른 grant·publication·delivery 회귀의 순차 mutation을 동시 race라고 부르지 않는다.
- 실제 age+Docker pg_dump backup 뒤 candidate source를 retract→purge하고, service를 중지한 뒤 이전 archive를 restore했다. **committed/tokens_rotated/deletion_floors_reapplied**. 새 service에서 이전 operator는 `AUTH_DENIED`, policy는 비활성, purge source는 `purged`/body 없음이었다. 현재 policy 재승인 전 recall은 `SELECTION_POLICY_BLOCKED`; 재승인 뒤에도 purge된 claim·문장은 없었다.
- 개인 full-semantic stats에는 회사 coverage·classification labels가 없었다. 임시 OMP 설치에서 prompt recall을 끈 synthetic native adapter event의 stdout은 비어 있었다. 설치는 owned uninstall로 회수했다. 실제 OMP model 실행이나 회사 운영 승인을 주장하지 않는다.
- import guard의 **56개 report에서 model import 시도 0·적재 0**. service report는 최종 회사와 개인 process 두 개다. 앞선 SIGTERM service는 atexit report가 없으며, 최종 회사 process는 SIGINT 뒤 report를 남겼다. guard는 OS 전체 egress 차단 증거가 아니다.
- 소유한 synthetic schema 두 개를 drop했고 임시 venv·DSN·token·backup·adapter scaffolding을 제거했다. 실패 관측과 최종 증거·gate 로그는 private runtime `company-smoke-20261013T235345/`에 남겼다. `fix-loop-evidence.json`은 0600이다. 개인 stable service와 live failed6/DLQ6은 변경하지 않았다.

이 smoke는 당시 explicit capability 구현의 증거이며 개인/회사 판단 기본값을 확정하지 않는다. 현재 확정 결정과 다음 공통 경로 전환은 [#5 댓글 6150124320](https://github.com/chonamdoo/agents-memory/issues/5#issuecomment-6150124320)을 따른다. 다음 전환을 이 smoke에서 완료했다고 주장하지 않는다.

## 회사 capability A round-3 fix-loop — 실제 spool·upgrade 경계

fresh native review 3차는 Codex 6개 중 approve1/request-changes5, Claude probe timeout이었다. 네 지적을 수정한 뒤 worker의 ruff·pytest·build를 실행했다: **1380 passed, skip 0**, lint/package exit0. 새 migration regression은 처음 Store reopen 뒤 `reconcile_journal()` 누락으로 `DELETION_BARRIER`가 발생했고, 기존 공식 절차를 추가한 후 단일 회귀와 전체 suite가 통과했다.

- 같은 core-only wheel SHA256 `d7103eddb54832075646009371fd275a58b6c92a5b8b1230660e790202e7ea82`를 새 격리 venv에 설치했다. 독립 synthetic schema와 실제 loopback service·producer credential을 사용했다.
- 변경 전 wheel에서 모순 coverage head와 정상 후속 capture를 두 번 flush해도 `pending2/committed0/quarantined0`이었다. correction-origin replay도 `CAPTURE_RECEIPT_INVALID/pending1`이었다. 새 wheel을 설치한 뒤 **동일한 기존 spool**을 reopen했다: poison은 quarantine1, 후속 capture committed1/pending0; correction replay는 원래 correction operation ID로 committed1/pending0이었다.
- 기존 isolated historical fixture로 pre-0005 schema를 구성하고 실제 CLI migration을 적용했다. 새 service의 `/api/capture` replay는 `source_pointer=null/capture_disposition=null`을 반환했고 spool은 committed1/pending0으로 drain했다. 저장된 receipt에는 pointer·disposition을 지어내지 않았다. permanent regression은 실제 lost ACK·migration·다음 capture·reopen까지 검증한다.
- 정확한 historical metadata를 가진 signed pre-capability v4 OMP receipt fixture는 변경 전 공식 uninstall이 `HOST_RECEIPT_INVALID`였다. 새 wheel의 공식 uninstall은 `uninstalled`, 재설치는 `capability=lexical_entity`였다. 마지막 설치도 owned uninstall로 회수했다. 실제 native OMP model 실행이나 회사 host enablement는 아니다.
- CLI/service import guard report **14개에서 ML import 시도0/적재0**. 서비스 세 번 모두 SIGINT 뒤 report가 있다. 이 report는 historical fixture helper나 OS 전체 egress의 증거가 아니다.
- 소유 synthetic schema를 drop했고 임시 venv·DSN·token·SQLite·adapter/script scaffolding을 제거했다. pre-fix 실패·post-fix 결과·한계는 private runtime `company-fix3-20261014T004401/{before,after,summary}.json`에 0600으로 남겼다. 실제 QA·local-handoff 완료는 다음 공식 phase의 결과를 따른다.

## 현재 run round-4 fix-loop — schema·credential 경계

fresh native review 4차의 must-fix 2건만 수정했다. ruff 통과, 실제 PG/age/Docker runtime의 pytest **1413 passed, skip 0, 173.53s**, uv build 통과. 변경 경계 선택 검증은 152 passed/1261 deselected였다. 처음 lint는 새 client 상수 앞의 빈 줄로 실패했고, targeted LSP import action이 없어 해당 빈 줄만 수정했다.

- core wheel SHA256 `e06b33eee23388069ece512652bb38850e94578de3cb96ac7ac76a129cfbe2f3`를 별도 venv에 설치하고 기존 worker venv의 dependency만 연결했다. package는 새 venv의 installed wheel에서 import됐다. 별도 synthetic DB schema·app/migrator 역할·journal·credential·port의 실제 loopback service에서 operator readiness HTTP200을 관측했다.
- 실제 modern MCP `tools/list`에서 받은 flat record schema를 strict decoder와 비교했다. kindless note와 nullable-policy selection은 둘 다 허용됐다. missing body/provenance, mixed note/selection, kindless selection은 둘 다 거절됐다. 같은 malformed 입력의 실제 MCP 호출은 `INPUT_INVALID/not_started`; shape-valid nullable policy는 authority 검증의 `SELECTION_POLICY_BLOCKED`였다. branch별 required/allowed 필드는 `if/then/else`로 표현한다. 이 결과는 native provider의 조건부 schema 지원 증거가 아니다.
- 실제 CLI의 0600 credential+newline record는 `captured/committed`였다. writer 없는 FIFO·1MiB token·symlink·0644 token은 각각 약0.11–0.13초 안에 `CREDENTIAL_INVALID/not_started`, exit1이었다. credential 읽기는 최대2050 bytes(512 UTF-8 characters+CRLF)로 제한한다. permanent regression은 opener 전 거절·bounded read·잘못된 UTF-8·512-character 경계와 기존 unknown network effect를 다룬다.
- service import guard의 ML import 시도0/적재0, SIGINT exit130을 확인했다. startup info logging은 꺼져 있으므로 log-based ready timeout은 실제 startup 실패가 아니었고 authenticated operator HTTP200으로 확인했다. owned service 종료 뒤 synthetic schema·venv·DSN·credential·state·journal·project·script를 제거했다. 0600 evidence는 private runtime `record-client-fix4-20261014T014109/{summary,imports}.json`과 gate logs에 있다. 개인 stable 서비스·failed6/DLQ6에는 손대지 않았다.
- 이 수정은 current run scope 안이다. 이후 fresh native review·공식 QA·local-handoff 완료는 각 공식 phase의 결과를 따른다. #5의 개인/회사 공통 LLM 판단 전환과 건강도 제외는 다음 run 결정이며 여기서 구현한 기능으로 보고하지 않는다.

## 기존 run의 공식 native review 5차 및 QA 차단

- installed runner가 시작한 Codex의 독립 confined subprocess 6개(generalist/types/architecture-design/state-integrity/clean-architecture/io-safety)는 모두 approve였다. Claude의 현재 probe는 unavailable이었고 stale Claude angle은 aggregate에 포함하지 않았다. current manifest의 artifact hash 7개가 일치했다. runner가 review → QA 전환을 승인했다.
- QA phase의 공식 `agent-flow gates --phase all --execution local --run-dir …`는 **2/3 통과**였다. lint/package는 exit0, pytest는 **1412 passed/1 failed, 173.64s**. 실패는 `test_related_withdrawal_preserves_live_read_and_completes_original_pipeline[claim-pending]`의 `ready_claim`에서 첫 `claim_job()`이 `None`인 fixture assertion이었다. 단순 확인용 재실행은 하지 않았다.
- 초기 job의 `available_at` default와 eligibility는 모두 PG `clock_timestamp()`를 쓴다. 실제 runtime probe는 한 connection 10000회/2.146초에서 backward step0, 두 connection 교대 100000회/21.312초에서 backward step2/max**2.067403초**를 관측했다. [INFERENCE] enqueue와 claim 사이 clock rollback은 해당 setup 실패를 설명할 수 있으나 이미 teardown된 실패 fixture의 정확한 시각은 복구할 수 없다. 실제 worker는 `None` 뒤 다음 poll을 기다린다. publication/withdrawal fixture는 scheduler delay 자체를 시험하지 않으므로 queued work를 명시적으로 due 상태로 준비하는 수정이 제안됐다. product 코드·runtime clock 변경이나 test retry/skip은 적용하지 않았다.
- `qa.md`의 request-changes 뒤 canonical continue는 **fix-loop exceeded 3 rounds routing qa → fix-loop / route_blocked**였다. 제한·counter·guard·workflow·approval token을 변경하지 않았다. 추가 fixture edit, fresh review, QA green, local-handoff는 아직 없다. controller의 공식 복구 결정이 필요한 상태다.
- 실패 gate 결과와 clock probe는 private `record-client-fix4-20261014T014109/`에 0600으로 보존했다. 최신 wheel의 기존 실제 service smoke와 round-5 source 일치 증거는 유효하지만 이 QA 실패를 대신하지 않는다. #5의 별도 전환 범위는 현재 run에 합치지 않았다.

## 동일 범위 복구 implement — development/20261013-221430

- 사용자가 증거 보존 종료와 동일 범위 복구 run을 선택했다. 공식 `abort`는 기존 run artifacts를 보존했고, `run --workflow development --reuse-existing-worktree --allow-dirty`로 같은 작업 트리·branch를 재사용했다. 원래 fix-loop counter3은 그대로다. 기존 QA에서 수정을 건너뛰거나 green으로 바꾸지 않았다.
- 변경은 `tests/test_store_authority.py`의 fixture 준비다. `make_initial_work_due`는 한 operation의 pending/attempt0 작업에만 `available_at=-infinity`를 설정한다. `ready_claim`과 해당 withdrawal scenario의 기대 claim 앞에서 호출한다. 상태·attempts·generation·lease·원문·업무 assertions를 바꾸지 않고 sleeps/retries/skips를 추가하지 않았다. 제품 scheduler와 모든 Python/TS 제품 파일35개는 기존 검증 wheel과 byte-identical이다.
- 집중 회귀는 **8 passed/1405 deselected, 4.93s**였다. 실제 독립 PG fixture smoke에서 future initial과 예약 retry가 있을 때 `claim_job()`은 `None`, initial만 명시 due로 바꾼 뒤 실제 extract lease/attempt1을 받았다. attempt1의 예약 retry는 helper를 직접 호출해도 row 전체가 불변이었다. 이 증거는 fixture/DB 경계이며 actual model pipeline이나 native host 소비 증거가 아니다. scaffold와 소유 fixture schema는 제거했다.
- implement phase의 공식 all/local gates는 **3/3 통과**, pytest **1413 passed/skip0, 174.23s**, lint/build exit0이었다. wheel SHA256은 `e06b33eee23388069ece512652bb38850e94578de3cb96ac7ac76a129cfbe2f3`로 같았다. 이전 actual service/MCP/CLI/spool/upgrade/purge/restore proof는 해당 source identity와 함께 보존하지만 새 run의 review/QA 결과를 대신하지 않는다.
- 0600 evidence/logs는 private runtime `qa-fixture-recovery-20261014T071020/`에 있다. fresh 공식 native review·QA·local-handoff는 이후 phase 대상이다. commit/index/push/PR/배포, 개인 stable service·failed6/DLQ6, 다음 공통 LLM 판단 전환·건강도 측정에는 손대지 않았다.

## 복구 run fresh review·공식 QA·인계

- `development/20261013-221430`의 installed runner가 Claude6/Codex6 독립 confined OS subprocess를 실행했다. **12개 모두 approve**, current manifest의 artifact hash12개가 일치했다. timeout/skipped/stale 결과나 parent/in-session 리뷰 대체는 없었다. 전체 original A1–A11 범위와 제품 identity를 읽어 검토했고 fixture-only delta와 다음 #5 전환을 구분했다.
- review 승인 뒤 QA 진입 시각은 `2026-10-13T22:46:42.086751+00:00`이었다. 해당 window에서 공식 all/local gates를 다시 실행했다: **lint/test/package 3/3**, pytest **1413 passed/skip0, 190.79s**, lint/build exit0. 이 결과는 이전 implement gate나 원래 실패 run의 복사본이 아니다. wheel과 제품 파일35개 identity는 그대로다.
- 실제 수정 경계는 앞 절의 독립 PG fixture smoke로 확인했다. 해당 schema·script는 제거했고 0600 logs/summary를 보존했다. 원래 실제 service/transport/spool/upgrade/restore 증거는 source-identical 제품에 대한 원래 층위이며, 이 fixture smoke를 모델·native-host 실행 증거로 대신하지 않는다.
- runner가 green QA를 받아 handoff phase로 전환했고 `handoff.md`에 controller w18:p9 소유권·검증·비차단 위험·다음 #5 범위를 기록했다. 최종 workflow 종료 상태는 canonical continue 결과/run report/status를 따른다. commit/index/push/PR/배포·실제 회사 enablement·trial·다음 공통 LLM 전환은 수행하지 않았다.
- 비차단 위험은 current `review.md`를 따른다. selection digest와 개인 model-source 결합, package 교체/손상 중 CLI import-time fingerprint I/O의 strict hook refusal 전 실패 가능성, claimless withdrawal floor/source labels, `partial`와 capture coverage, OMP 최대 envelope·provider conditional-schema 호환성, 다른 fixture의 wall-clock 의존을 숨기지 않는다. 현재 승인이나 immutable-wheel proof가 그 실패 모드 검증은 아니다.
