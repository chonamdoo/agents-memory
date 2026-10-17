# Changelog

## Unreleased

### 명시적 메모리 건강 관리와 평가 engineering

- 코드/worktree/root·파일/Python AST symbol anchor와 현재 health dependency를 claim의 검색·admission·게시·최종 delivery·관계 입력에 연결했다. required rule을 ordinary stale 필터로 숨기지 않는다.
- 이미 허용된 관측 segment와 close watermark를 bounded pending으로 연결하고 다음 권한 있는 agent/별도 허용 Jev가 판단하는 경로를 추가했다. 새 transcript 수집·구독 agent 깨우기·자동 정정/승격/삭제는 추가하지 않았다.
- relevance·support/정확성 판단·freshness와 exact-revision operator Accept/Reject를 분리했다. 늦은 판정·삭제·철회·권한 변경·code 변경을 다시 검사한다. `0007_memory_health`와 archive/init/restore closure를 연결하며 restored source의 ordinary claim은 최신 판정 증거 없이 재사용하지 않는다. 새 health disaster ledger는 없다.
- shutdown의 false drain·eventual join·원래/동시 실패를 보존하고 실제 ASGI/Uvicorn 노출 진단을 body-free로 제한했다. proposal의 전체 UTF-8 body/예외/exact source revision inspect와 권한 제한 shared-rule projection을 구분했다. coverage·stats·pending·health 분모의 current request_snapshot/policy/review dependency 자격을 통일했다.
- 고정 manifest/전체 attempt ledger·정책을 상속하는 native CLI driver·required-only off/실제 wire gateway·immutable artifact/허용 diff witness·격리 Docker oracle/control·pair scheduler·cluster bootstrap/unknown cost·평가 CLI와 명시 health evidence compiler를 추가했다. task 성공은 자동 support/freshness나 인간 승인이 아니다. raw diagnostic gold와 engineering oracle은 `provided_unattested`이며 인간 holdout을 만들어 채우지 않는다.
- MCP catalog는 flat root와 variant의 required/allowed/null 제약을 유지하면서 schema 참조·중복을 줄였다. 실제 최대 escaped JSON-RPC ID의 응답 상한을 올리지 않는다. 출력 상한에 걸린 Docker exec는 container removal 전에 닫고 기존 deadline/TTL·소유권·exact cleanup을 유지한다.
- 현재 전체 통합 health/평가 smoke·fresh whole-source formal review/QA는 미완료다. 실제 exact-head Actions와 실패 전후·부분 성공 범위는 [검증 기록](docs/verification.ko.md)을 따른다. 로컬 runtime 검증·native trust/운영/egress·human120/60task×3·실제1–2주 trial·merge/release 실행을 승인하거나 완료한 기록이 아니다.


### CI 전용 검증 전환과 OSS 후속 보완

- GitHub Actions에 실제 PG18/pgvector·지원 Python/SQLite·Node·native PG18 도구·age 준비, 전체 collection의4개 disjoint shard, lint/build·설치 wheel 소비, 누락/skip/실패/source drift·artifact mismatch를 거절하는 최종 집계를 구성했다. raw failure/captured output 대신 outcome-only JUnit을 업로드한다.
- purge/reconcile의 동일 값 UPDATE를 null-safe 조건으로 억제했다. restore된 payload 재-scrub·삭제 floor·global clock·operation epoch 의미는 유지한다.
- adapter6의 생성 hook/MCP에 Python `-I`를 적용하고 validated v5는 owned cleanup/reinstall만 허용한다. pending spool·foreign native/Agent Flow 설정은 보존한다.
- serve/service-run은 lifespan 전에 configured socket을 확보하며 bind 실패를 `SERVICE_BIND_FAILED/not_started`로 반환한다. 임의 port fallback·기존 listener kill은 없다.
- ingress 권한 재확인, stop 가능한 remote TCP/TLS/GET·최초 send, 이미 전송한 business drain, retained bad-first recovery 공정성, service uninstall 효과·upgrade 순서의 회귀를 추가/보완했다.
- [OSS 후속 조사](docs/research/2026-10-16-oss-followup.ko.md)에서 원인·고정 PR/source·회귀·license·평가 방법과 추가 적용/기존 반영/보류/거절을 구분했다. paired 평가의 identity·전체 attempt 분모·oracle 대조군·최종 artifact 불변 계약을 보완했다.
- 첫 실제 두 CI 준비 실패와 uv selector 충돌 원인을 보존했다. `c59377e`의 [실제 Actions](https://github.com/chonamdoo/agents-memory/actions/runs/38917025242)는 전체2408/skip0·lint/build·설치 wheel subset31을 통과했다. 이는 해당 source의 CI 증거이며 이후 수정·native acceptance·정상 QA/handoff·release 승인이 아니다. 로컬 test/collection/lint/build/추가 smoke는 실행하지 않았다.
- 그 source의 정상 공식 리뷰는 request-changes를 유지했다. README를 원래 owned service uninstall→새 entrypoint의 config migration 순서로 맞추고, installed replay의 durable intent 제거 효과와 CI timeout의 잔존 process-group 정리를 보완했다. file publication 오류는 DB 장애로 바꾸기 전에 구분하며 실행 host template도 CI source digest에 포함한다. 새 회귀는 수정 전/후 GitHub Actions에서만 검증한다. 원본 reviewer timeout과 외부18개 acceptance는 별도 보존한다. 정확한 source·실행·리뷰 상태는 [검증 기록](docs/verification.ko.md)을 따른다.
- 후속 `bc30804`의 [Actions38922413453](https://github.com/chonamdoo/agents-memory/actions/runs/38922413453)는 전체2430/skip0·lint/build·별도 wheel31을 통과했다. 그 전 regression-only20실패와 첫 수정본의 기존 mock-echo assertion5실패도 보존했다. 실제 파일 오류 분류·durable 효과·명시 복구 검증은 유지하며 주입한 DB 오류값을 모든 DomainError에 기대하던 assertion만 제거했다. 이는 정상 fresh review/QA/handoff나 full issue5·출시 승인이 아니다.
- 후속 양 모델12개 angle은 실제 approve였지만 원래 요구 범위의 service readiness upgrade 오류와 소멸한 PGID 재신호 위험은 controller request-changes로 남겼다. owned config의 `CONFIG_UPGRADE_REQUIRED`를 readiness에도 보존하고, TERM/존재 확인에서 이미 사라진 group은 다시 신호하지 않되 owned parent reap·살아 있는 자손의 TERM/grace/KILL은 유지한다. 회귀-only Actions의 실제2435건 중5실패를 보존했고, 수정본877a56d의 [Actions38929819006](https://github.com/chonamdoo/agents-memory/actions/runs/38929819006)는 전체2435/skip0·lint/build·별도 wheel31과 앞선5건의 setup/call/teardown을 모두 통과했다. 이 수정본의 fresh formal review·QA/handoff와 외부 acceptance는 별도다.
- `8aa611b` 당시 설치 wheel 실행기와 집계는 단일13-selector 정책을 공유했고 checks에도 실제 owned PG 준비를 요구했다. self-consistent한 import-only receipt를 승인하던 회귀의 Actions 실패2건을 보존했다. [Actions38977685346](https://github.com/chonamdoo/agents-memory/actions/runs/38977685346)는 전체2436/skip0·lint/build와 별도 noneditable wheel85를 통과했다. 설치 소비에 service readiness·HTTP/MCP·operator 권한/publication·native child 정리·TLS stop/drain·bad-first recovery 및 ESRCH 뒤 PGID 재사용 주입의 native 두 경계를 포함한다. fixture 수준의 설치 소비를 실제 native activation·운영 cloud·kernel PID wraparound·human trial/출시 승인으로 확대하지 않는다.
- 정상 독립 리뷰의 group leader 조기 reap P1를 수용했다. native/CI cleanup은 중간 poll 없이 leader PID를 최종 group 신호까지 보존하고 이미 reap된 입력에는 신호하지 않는다. grace 상수·deadline·최종 parent wait는 유지하지만 Linux에서는 zombie leader 때문에 full grace를 기다리는 지연이 생긴다. 이 안전성 trade-off와 실제 call phase 측정은 [검증 기록](docs/verification.ko.md#group-leader-소유권-보존--7df1eb4)에 명시하며 macOS 지연은 추정하지 않는다. malformed fixture의 취소 이력을 보존했고, 유효 Actions의 실제 source4/installed-native2 실패(-9/-15) 뒤 7df1eb4의 [Actions38982950669](https://github.com/chonamdoo/agents-memory/actions/runs/38982950669)는 전체2440/skip0·lint/build·별도 설치87을 통과했다. MCP 증거도 직접 Store capture 후 modern/legacy inspect→record와 별도 HTTP producer 권한 거절로 좁혔다. 실제 kernel wraparound·native 활성·운영/평가/출시 승인을 주장하지 않는다.
- macOS CPython3.12에 없는 `os.waitid` 때문에 ownership 회귀8건이 setup 실패하던 지적을 수용했다. kqueue exit 등록 뒤 child를 해제해 reap 없는 관측을 보존하고, fault injector의 owned group만 가상 처리하되 소유권 상실 시 실제 survivor에 신호하는 조건을 유지한다. 제품 exception을 삼키거나 Mac을 skip하지 않았다. 병렬 Mac3.12 job과 exact-runtime/node/phase/source 집계를 추가했다. before8setup 실패와 첫 수정6통과/2call 실패를 보존했고, 92cc360의 [Actions38987056695](https://github.com/chonamdoo/agents-memory/actions/runs/38987056695)는 별도 Mac8·Linux full2443·설치87 및 lint/build/aggregate를 통과했다. 이는 실제 native 보호나 Mac 전체 suite·운영/평가/출시 승인 증명이 아니다.
- 후속 정상12개 독립 리뷰는5approve/7request-changes였고 “fixture만의 문제” 진단이 불완전했음을 확인했다. Darwin 제품 cleanup의 EPERM은 reap 없는 leader exit와 원자적·고정 크기 libproc group census가 **그 leader 하나만** 확인할 때만 terminal로 분류한다. live leader/다른 member/관찰 실패의 권한 오류는 유지한다. 정상 EOF/TERM inventory의 유효 before4실패와 첫 제품 수정의 kqueue context-manager TypeError8실패를 보존했다. `contextlib.closing`으로 고친2656828의 [Actions38991986933](https://github.com/chonamdoo/agents-memory/actions/runs/38991986933)는 실제 Mac16·Linux 전체2451·별도 설치92와 lint/build/aggregate를 통과했다. 실제 setuid/native 보호·Mac 설치 wheel·운영/평가/출시 승인으로 확대하지 않으며 원래18개는 완료0개다.
- 후속 독립 리뷰9approve/3request-changes가 찾은 테스트 finalizer의 reap 뒤 PGID 신호를 제거했다. 두 회귀는 공통 private IPC·원본 Popen 정리를 사용하며 별도 실제 process 생존과 reap 뒤 살아 있는 자손의 해제를 검증한다. FIFO EOF는 nonblocking read를 먼저 관측하고 집계는 매개변수 없는 ID도 인정한다. 유효19teardown 실패·별도 집계1call 실패와 첫 수정의 Mac19teardown·CI 미사용 import 실패를 모두 보존했다. 6b082a5의 [Actions39001624481](https://github.com/chonamdoo/agents-memory/actions/runs/39001624481)는 Linux 전체2452·별도 설치92·실제 Mac36의 모든 phase와 lint/build/aggregate를 통과했다. 실제 native 보호·운영/평가/출시 승인으로 확대하지 않으며 원래18개는 완료0개다.


### 네 번째 리뷰 후 권한·복구와 PR #9 ingress 보안 수정

- Jev 파일 게시를 현재 operator credential/generation과 같은 PostgreSQL clock 권한 경계로 직렬화했다. private state scalar는 strict하게 검증하고 오류 효과는 명시 상태로 선택한다.
- fenced Jev 선택의 unavailable을 authenticated readiness에도 보존한다. 최초/재개 service install과 fresh host 진단의 durable/native 효과, `CONFIG_UPGRADE_REQUIRED` 전파를 바로잡았다.
- 직접 부모 선종료 뒤에도 native 진단 자손·pipe를 정리한다. 원격 spool recovery는 pending-only·cycle 간 backoff·중단 가능한 준비/DNS·cycle 범위 해석 재사용을 사용하며 기존 단일 flush owner와 unknown-effect reconciliation을 유지한다.
- localhost Host는 ingress mode와 무관하게 실제 loopback peer가 있어야 허용한다. 누락/비 loopback peer의 local operator/bearer 우회를 거절하고 정상 loopback·public OAuth 경계를 회귀로 확인했다. README의 원격 PC `service install`을 host bootstrap 앞으로 옮겼다.
- 현재 설치본의 개인/회사 실제 PG·launchd·fenced readiness·명시 stop/start·capture 보존 smoke를 확인했다. 새 live Jev·구독 모델·native hook 보호·운영 배포의 증거는 아니다. 정확한 전체 gate와 보안 socket 검증 상태는 [검증 기록](docs/verification.ko.md)을 따른다.


### 세 번째 공식 리뷰 — body deadline·전환 효과·진단

- POST body 전체15초 deadline·408/not_started·HTTP/1 연결 종료로 slow/stalled upload의 슬롯 점유를 제한했다. 실제 설치 launchd/PG에서 부분 source0·용량 회수 뒤 capture202를 확인했다.
- Jev 교체 fence 뒤 오류·crash에서 선택 provider를 유지하고 구 worker를 차단한다. 명시 재선택으로 복구하며 durable policy/선택과 unknown credential 폐기·pending intent를 구분한다.
- service start/stop의 저장된 intent 뒤 native 실패를 not_started로 보고하지 않는다. strict receipt JSON/int UID, 과거 Codex strict의 cleanup-only 로딩, pending 설치 재개 경고를 보완했다.
- Claude 환경0의 force-on·settings env unknown·진단 프로세스 provenance를 반영했다. doctor는 effective provider를 사용하고 invalid project를 조기에 거절한다. native 상태의 부작용 필드는 관측 단정이 아닌 요청 범위로 변경했다.
- 이전 공식 wave는3 approve/8 request-changes/1 timeout이었다. 새 집중 실행826 pass/5 fixture fail 뒤 해당5개를 수정·통과했고 설치 byte46·실제 launchd crash/stop/start·PG Jev fence·CLI를 확인했다. 다음 독립 승인·공식 QA/handoff·전체 suite 결과를 대신하지 않는다.
- age Sigsum positive/변조 negative·Go module h1/license와 공개213 checksum, 격리 Linux canary를 추가 검증했다. 전체 P3·native 보호·법적/출시 승인은 아니다.

### Native 공존 진단과 offline build 준비

- DB/config 없이 실행하는 `native-status`와 명시 `doctor --project`, 신규/동일 `host-install`의 metadata-only 공존 경고를 추가했다. Claude/Codex 설정 증거·storage 잔존·unknown을 분리하며 본문/auth·사용자 설정은 변경하지 않는다.
- Codex 정상 `config/read`·`hooks/list`로 layer/hook 수를 조회하는 bounded opt-in 진단을 추가했다. native callback·실제 행동 차단·신뢰 승인을 대신하지 않는다. 새 회귀29개와 실제 Codex inventory CLI를 확인했다.
- source-build backend를 `hatchling==1.32.4`로 고정했다. 공식 standalone Python3.13.16/SQLite3.53.1과 hash 고정 build9/runtime34 wheels로 OS network-deny sdist/wheel build·새 환경 전체 설치·CLI를 실행했고, 누락 wheel은 거절했다. 공개 PG/vector·새 app image·macOS age artifact도 별도 보존하며 offline 설치와 전체 offline 운영/법적 승인은 구분한다.
- 안정 DB를 read-only transaction으로 관측했다: `0004_operation_successors`, failed6/DLQ6·retirement schema 없음. 현재 값이며 해결·migration 성공으로 표시하지 않는다.
- 새 source의 첫 전체 실행은1,954 pass/235 fail/1 error였다. 제품 guard를 유지하고 저장소 내부 QA 임시 경로만 바로잡은 뒤 동일236개 실패 항목을 전부 통과했다. Ruff/build도 통과했으며 새 단일 전체-pass 실행으로 표현하지 않는다.
- Jev deny/agent에서 실제 구독 Opus5.5가 합성 악성 원문/의미 재유입을 discard하고 정상 조건/예외 claim을 최종 MCP context로 재조회했다. 중간 MCP 오류4회와 제한된 oracle·native 소비 미관측을 기록한다. 전체 PMPA·paired 평가·trial·효익의 증명은 아니다.

### 이슈 #5 후속 — strict 설치 안전성과 삭제 재유입

- 이전 checkpoint source의 정확한 `uv run pytest -q`는 **2,161 pass/skip0/518.79초**다. 최초2113pass/48fail의 Homebrew symlink ownership 거절을 보존하고 private regular interpreter·정상 ownership·isolated source와69개 실패 표면을 먼저 검증했다. 제품 guard·Homebrew 권한은 변경하지 않았다.

- Codex 신규 `--strict`는 실제 native 보호 실패 상태에서 성공처럼 등록하지 않고 `HOST_STRICT_UNSUPPORTED/not_started`로 설정 쓰기 전에 거절한다. 자동 advisory downgrade는 없으며 명시 advisory/MCP·기존 owned 정리는 유지한다. Codex native 보호 구현 완료로 표시하지 않는다.
- 삭제 identity/lineage floor와 동일 본문의 새 origin 재판단을 문서화했다. retract/purge 두 회귀와 새 설치 CLI/advisory MCP→HTTP/PG에서 기존 origin 비부활·옛 본문 부재·재판단 전 비노출·새 claim/source만 citation을 확인했다. R05의 누락 비교·잘못된 reference·비독립 근거 오류를 구분했다.
- [설치·업그레이드·장애 복구 runbook](docs/release-runbook.ko.md)을 추가했다. 문서 절차와 실제 안정 cutover·OS login/reboot/sleep·restore 수행 증거를 혼동하지 않는다.
- app+runtime34 wheels를 hash 필수·index/cache 비활성 local 입력으로 설치하고 `pip check`·isolated Python43파일 일치를 확인했다. lock CycloneDX와 실제 target35 distributions의 license-file inventory를 준비했다. Python/PG/tools/age/OS·build backend·다른 ABI·license/배포 승인까지 포함한 offline release 완료는 아니다.
- 이 checkpoint source는 `744b84b1…297f15`다. 앞선2,164 pass는 이전 source 이력이며 해당 controller 실행·남은 공식/native/trial gate는 [검증 기록](docs/verification.ko.md#이슈-5-후속--승인-없는-구현과-설치-소비자-검증)을 따른다.


### 두 번째 공식 리뷰 — Jev 재시도·발급 복구·readiness

- Jev와 key 검증의 실제 HTTP 시도마다 현재 허가를 확인한다. backoff 중 철회·provider/policy revision 변경 뒤 새 전송을 차단하며 이미 admission된 요청의 회수를 주장하지 않는다.
- deny 중단 후 reallow는 agent 전환·폐기를 먼저 완결한다. 새 credential의 발급 전 private intent와 PG clock 직렬화로 lost-response/미확정 commit을 복구한다. 손상 provider는 명시 agent 복구를 요구한다.
- 익명 readiness도 삭제 barrier를 유지하되 Store 소유의 단일 live 검증을 공유한다. 실제 HTTP timeout8건·검증1개·health 유지·해제 후 DB readiness 회복과 새 wheel의 합성 live Jev remember/active claim을 확인했다.
- effective 허가와 configured provider를 구분하고 project add의 후속 grant 실패는 committed로 보고한다. bootstrap principal 용어와 [원래 Shorts 분석의 출처 연결](docs/research/2026-10-16-shorts-lTja2ZxXYyI.ko.md)을 보완했다.
- 같은 source에서 Ruff/build와 **정확한 `uv run pytest -q`:2,164 pass/skip0**를 확인했다. QA interpreter·isolated MCP project 설치 prerequisite를 고친 과정의 실패 이력은 보존했다. 새 noneditable wheel의 실제 구독 Claude/Codex/OMP도 deny/agent·키 없음에서 원문 판단·저장·같은 claim/예외 최종 context를 통과했다.
- 두 번째 공식 리뷰의 request-changes를 controller 실행으로 승인으로 바꾸지 않았다. Codex native trust/callback·실제 보호·수정 후 승인 리뷰·공식 QA/handoff·trial·runtime 게시는 여전히 별도 gate다.
- 재개 검증용 subscriber native 등록·credential·private trace/project와 QA env/cache를 정리하고 owned service/PG를 중지했다. 정상 native 승인 재검증용 최소 private fixture는 남아 있으며 전체 철거·운영 cutover 완료를 주장하지 않는다.

### 공식 리뷰 후 deadline·경합·운영 복구 수정

- HTTP DNS/connect/TLS/send/response 전체 deadline과 종료·회수 가능한 resolver를 적용했다. unknown mutation은 재전송하지 않는다. remote recovery20초 cycle budget과 private spool 단일 flush owner를 추가했다.
- launchd 설치/삭제 durable intent·중단 후 정상 명령 재개·disabled 보존을 구현했다. Jev setup/deny/provider/credential retirement와 실제 publication commit의 cross-process 경합을 막고 미완료 revoke intent를 보존한다.
- bootstrap identity/권한 경계, public operator 거절과 business route의 인증 전 journal sweep 제거, remote CA commit rollback, MixedCase Unix socket 및 Codex context 미출력 lifecycle metadata를 수정했다. 익명 readiness의 검증 누적은 위 두 번째 리뷰에서 별도로 해결했다.
- 이 첫 fix-loop 당시 직접 실행은 Ruff/build 성공·전체2,143 pass/skip0, 실제 HTTP/TLS16경우·launchd crash intent·새 개인/회사 HTTPS package·noneditable wheel·실제 구독 Claude/Codex/OMP MCP 판단/저장/최종 read다. 후속 source의 새 통과로 재사용하지 않으며 [관측과 한계](docs/verification.ko.md#공식-리뷰-후-fix-loop--development20261015-131245)를 구분한다.
- **Codex strict native 보호는 아직 입증되지 않았고 유효 patch의 실제 변경 실패를 기록했다.** 합성 파일은 원복했다. 설치/MCP 성공을 native 첫 행동 차단으로 취급하지 않으며 native 승인이나 workflow guard를 우회하지 않는다. fresh 공식 review/QA/handoff·전체 acceptance·trial·runtime 게시는 미완료다.

### 로컬·클라우드 원격 경로와 독립 판단 정책

- 개인/회사 × 로컬/클라우드 × Jev 허용/불가의 독립 축을 유지한다. 개인·회사 로컬은 별도 `egress-policy.json` default-deny, 명시 allow+확인과 provider 선택·키 검증을 분리했다. deny는 먼저 저장하고 agent 전환·worker credential 폐기, 요청·응답·게시 revision fence를 적용한다. 키·기존 personal 설정만으로 허가를 추론하지 않는다.
- per-user macOS launchd install/start/stop/status/uninstall, 로그인 시작 등록·비정상 종료 재시작·durable manual stop을 추가했다. native 제어와 DB-inclusive `/readyz`가 하나의 전체 기한을 공유하며 살아 있는 DB-unready 서비스를 죽이지 않는다. PostgreSQL/Docker 자체는 관리하지 않는다.
- provider와 독립적인 bounded capture spool recovery가 새 host event 없이 준비 회복 후 전송한다. 기존24시간 TTL·물리 상한·stable key/unknown-effect 계약을 유지하며 owned intermediate0755/leaf0700 설치 layout을 안전하게 처리한다. operator-only body-free 상태, 실패 격리된 worker shutdown·application drain·DB close를 추가했다.
- claude-mem OMP/Claude/Codex의 실제 구현·merged/open 수정과 #5의86개 후보를 [OSS 연구](docs/research/2026-10-15-oss-local-runtime.ko.md)에 정리했다. deadline·실패 격리·production pipe·설치 소비자·비공허 native gate 검증 패턴만 기존 계약에 독립 구현하며 새 memory engine/provider·transcript 수집을 도입하지 않는다.
- 새 정책에서 개인/회사 × 로컬/클라우드 실제 Jev remember·원문 span·재조회를 합성 데이터로 확인했다. 다운로드 원본 키는 프로그램만 읽고0600 서비스 사본을 사용하며 assistant/로그/GitHub에 값을 노출하지 않는다. 구독 Claude/Codex/OMP의 실제 MCP 판단·저장·동일 claim 재조회 및 no-call 관측 범위는 [검증 기록](docs/verification.ko.md)에 구분한다. 현재 작업트리를 PR #9 remote runtime·공식 QA·일반 출시로 표현하지 않는다.
- 메모리 건강 관리 제안을 실제 native Opus5.5/Sol6.1로 독립 리뷰하고 최초 과장을 반증·정정했다. [건강 관리 리뷰](docs/research/2026-10-15-memory-health-adversarial.ko.md)는 provenance/Accept-Reject/coalesce/retention·구형 DB/backup의 영향과 권한을 구분한다. [DB 성장 조사](docs/research/2026-10-15-oss-db-growth.ko.md)는 #5 후보의 실제 merged 수정·코드·기본값·재개/삭제 위험과 별도 PG/SQLite 합성 실험을 기록한다. Reject가 즉시 recall 제외·철회가 아니고 post-backup disposition rollback은 별도 요구임을 현재 문서에 명시했다. health subsystem·자동 망각·추가 전송은 도입하지 않았다.
- strict remote profile·verified HTTPS/public CA·전체 body deadline·현재 PG bearer/OAuth 매핑·one-binding bootstrap·DB 비밀 없는 PC host receipt와 remote client supervisor를 추가했다. 정확한404/not_started session만 안전하게 재초기화하며 unknown write 재전송·원격 authority 자동 기동은 하지 않는다.
- 실제 실패를 수정했다: unsupported SQLite의 WAL 쓰기 전 차단, CLI closed-pipe 성공 exit, Python3.13 symlink-loop와 missing-cwd 분류, custom Claude native 경로의 clean-env 보존, launchd 비동기 bootout 뒤 즉시 start race, SQLAlchemy Unix DSN host decode. 원문/권한 guard를 완화하거나 기억 없음으로 숨기지 않았다.
- Caddy shared-network-namespace의 app crash 후 영구 HTTPS 장애를 재현해 독립 private-network 컨테이너와 exact proxy IP 신뢰로 전환했다. non-root/read-only·backend 미공개·proxy의 app secret/journal/socket 미mount를 유지하고 자동 HTTPS+DB 회복을 확인했다. pgBackRest/restic/Headscale·외부 삭제 witness·실제 cloud 계정 provisioning은 추가하지 않았다.
- cloud 구현·합성 검증은 최신 지시로 trial과 별도 진행한다. 실제1–2주 trial·전체 #5 acceptance·fresh 공식 review/QA/handoff·publication gate와 실제 corpus 승인 경계는 유지한다.


### 이전 PR #8 판단 provider 선택 (agent | Jev)

아래는 당시 개인 전용 구현·검증 이력이다. 현재 허용 정책은 위의 운영 주체 독립 default-deny 계약을 따른다.

- 원문 선택·관계 정리 판단 provider를 `agent`(기본, 지금 쓰는 coding agent)와 `jev`(TypeSafe Jev, 개인 배포 전용) 중에서 고른다. `init --judge`(개인 터미널에서는 대화형 질문)로 설치 때 정하고 `judge set agent|jev`·`judge status`로 언제든 바꾸고 확인한다. MCP는 `memory_inspect(ref="judge")` 조회만 하며 provider를 바꿀 수 없다. relevance는 provider와 무관하게 coding agent가 판단한다.
- provider·키·worker token은 Settings·DB가 아니라 `state_dir/judge`의 0600 파일에 둔다. Settings digest·init intent·host receipt·backup/restore 형식은 바뀌지 않는다. 키는 `--key-file` 또는 화면 표시 없는 입력으로만 받고 합성 질문으로 검증한 뒤 저장하며, 응답에는 HMAC fingerprint만 나온다. 회사 모드는 설정과 worker 실행 모두에서 `JUDGE_PROVIDER_FORBIDDEN`이다.
- serve 안 `JudgeWorker`는 전용 agent credential로 pending source window와 cleanup manifest를 기존 `inspect → record` 검증으로 기록한다. p≥0.8 span만 원문 그대로 claim으로 쓰고, 모두 p≤0.2면 discard한다. 불확실·주입 의심·이전 거절과 같은 내용·검증 실패는 pending으로 남겨 agent에게 넘기며 자동 fallback은 없다. 매 요청·기록 직전에 provider를 다시 읽어 전환 즉시 전송을 멈춘다. `project add`는 Jev worker grant를 함께 추가하고 restore 뒤에는 `judge set jev`를 다시 실행한다.
- README에 로컬(현재)·클라우드(계획) 구조도 PNG와 SVG 원본(`docs/images/`)을 추가했다.
- 검증: 새 회귀 54개와 기존 suite 1726 passed/11 skipped(age·pg_dump binary 미지정 backup 경로), ruff 통과. 사용자 키로 live Jev smoke, native Claude Code·Codex가 Jev가 넘긴 pending을 MCP로 처리하는 것을 확인했다([검증 기록](docs/verification.ko.md)).

### stage-0 동시성·복구 수정

- legacy MCP 세션이 재시작·유휴 만료·세션 수 초과로 사라지면 edge가 `SESSION_NOT_FOUND`/404/`not_started`를 반환하고, 다른 credential의 세션에는 `SESSION_CREDENTIAL_DENIED`/403을 반환한다. stdio relay는 모든 필드가 검증된 `SESSION_NOT_FOUND`/`not_started`에서만 저장한 `initialize`로 다시 연결하고 원 요청을 한 번 다시 보낸다. 재연결이 실패하거나 서버가 다른 protocol version을 협상하면 요청을 보내지 않고 `SESSION_NOT_FOUND`/`not_started`를 반환하며, 다음 요청 전에 다시 연결을 시도한다.
- serve·migrate·backup·restore가 하나의 DB 지원 계약(PostgreSQL 18.x, pgvector ≥0.8.7, 같은 major의 PG 도구)을 쓴다. backup archive는 live 버전을 기록하고 restore는 같은 계약으로 검사한다. 지원하지 않는 도구·live server·archive는 journal reconcile·DDL·restore fence 전에(backup은 staging·recipients 전에도) `DATABASE_VERSION_UNSUPPORTED`/`not_started`로 거절한다.
- 같은 source revision·contract·요청 snapshot에서 겹치는 창은 active complete remember/discard 하나만 이긴다(`SELECTION_ALREADY_RECORDED`). 게시한 claim이 모두 철회된 remember는 창을 놓고, claim 없이 기록한 remember는 계속 잡는다. 응답을 잃은 판단은 같은 admission으로 새 key 재시도 시 원래 operation을 돌려받고, 같은 admission의 다른 판단은 `ADMISSION_CONSUMED`다. 기존 receipt digest·schema·archive 형식은 바뀌지 않는다.
- `max_concurrent_requests`(기본16) 초과는 인증 전 `SERVICE_BUSY`, `pool_acquire_timeout_seconds`(기본5초) 초과는 `DATABASE_BUSY`로 `not_started` 거절한다. legacy `GET /mcp`는 stream이 열릴 때까지 상한에 포함된다. 인증은 전역 `am_clock` 잠금 없이 read-only로 수행하고 변경 트랜잭션이 잠금 아래에서 다시 확인한다.
- `restore-recover`는 migration fence를 먼저 판별한 뒤 명시 runtime을 검증하고, 그다음에 복구가 필요한지 판단한다. 이전 순서에서는 marker가 없으면 `RECOVERY_NOT_REQUIRED`가 잘못된 실행 파일의 `BINARY_REQUIRED`를 가려, 기존 CLI 회귀 12개가 실패했다.
- 업그레이드 주의: 새 설정 두 개가 `Settings` 전체 digest에 들어가므로, 이전 build가 남긴 중단된 migration fence는 이 build에서 `MIGRATION_RECOVERY_CONFLICT`로 거절된다(fail-closed). 중단된 migration은 업그레이드 전에 이전 build로 마친다.

### 공통 coding-agent 판단 전환

- 개인·회사를 `agent_judged` 하나로 전환했다. 사용 중 Claude/Codex가 MCP source_selection·관계·relevance 판단을 제출하고 서버는 exact 원문·revision·권한을 검증한다. Qwen extraction/consolidation/reflection, 서버 embedding/reranking과 obsolete model 설정·명령·의존성을 제거했다. lexical/entity는 후보 색인이고 별도 회사 selection 승인은 없다.
- saved source/retrieval admissions, 네 관계와 explicit no-change cleanup, 주기적 pending 생성, rejection 이유·bounded 관련 후보 비교·선택적 history/review·독립 근거 reopening, query expansion·두 호출 relevance를 추가했다. agent_note는 raw log로 남지만 판단 admission/pending·독립 remember 근거로 쓰지 않는다.
- source secret은 digest/spool 이전에 generic refusal로 거절한다. 기존 unknown-effect spool payload는 body-free quarantine이며 원문을 rewrite하지 않는다. whitespace-only armor false positive를 수정했다. adapter v5는 unjudged optional 후보를 주입하지 않고, optional relevance 안내 때문에 mandatory rule 예산을 줄이지 않는다.
- forward0006은 legacy executable jobs와 operation evidence를 보존해 retired/pending/held로 옮기며 legacy model claims를 awaiting_revalidation으로 남긴다. explicit config upgrade는 원본을 보존한다. 현재 identity sequence만 정확히 허용하는 archive inventory와 strict bounded MCP schema 공유 참조를 적용했다. 구형 archive·삭제 floor·credential 회전 경계를 유지했다.
- MCP stdio가 설치 root 밖 CWD를 거절하던 검사를 제거했다. 리더/linked worktree에서 같은 credential/binding으로 원문을 읽고 다른 binding은 거절하는 실제 MCP→HTTP→PG 회귀를 검증했다. 설치 ownership/receipt와 자동 capture/protected-action 경로 검사는 유지한다. 현행 README·요구사항·architecture·구현 계획의 잘못된 CWD 제한 서술도 수정했다.
- 첫 native review의 request-changes를 반영해 source/request snapshot을 분리하고 거절 history를8개 page·review receipt·현재 전체 비교로 연결했다. 같은 source는 겹친 discard span만 차단하고 reject feedback은 query-only irrelevance와 구분한다. contract revision은 명시 version에 결합하며 source/AST hashing을 제거했다.
- cleanup은 현재 적격 입력과 pending ID에 결합한다. 빈 item은 해결하고 동일 manifest/관계는 재생성하지 않는다. claim_ids 공동 manifest, 전체128 relation ref·요약8개, 관계0 판단의 철회/purge 전파, 현재 복구/historical 실패 구분, binding별 신규 capture 한도를 적용했다.
- 16KiB 상한을 유지하며 큰 claim의 전체 JSON continuation과 digest를 제공한다. 최악 query expansion의 후보 IDs를 보존하고 선택적 preview만 줄이며, 후보0에서는 승인 optional rule을 전달한다. schema title만 줄여 native catalog 예산을 지킨다. secret 역할 타입/순환 import·Claude secret turn state·body-free scheduler 진단도 수정했다.
- 첫 리뷰 수정(R1) 전체 **1470 tests**가 DeprecationWarning=error에서 경고0으로 통과했고 lint/wheel build도 통과했다. 이전 wheel에서 만료 cleanup·관계0 judgment purge 실패를 재현했으며 수정본에서 통과했다. 실제 current-project MCP/native 수동 소비와 합성0004 backup/0006 restore 증거는 검증 기록에 실행 시점별로 구분했다. 안정 서비스 전환은 승인됐지만 worktree guard가 leader-root owned host 작업을 실행 전 차단해 미완료다. 기존 실패 이력·안정 config/DB/host는 변경하지 않았으며 공식 재리뷰·QA/local-handoff는 아직 완료가 아니다.
- R2에서 일부 source 철회 뒤 살아 있는 legacy pending을 보존하고 selection reason/comparison·feedback 별도 source의 삭제/restore 경계를 수정했다. 큰 저장 selection·judgment도16KiB 상한을 늘리지 않고 전체 JSON continuation으로 읽는다. 만료·미래 claim 제외, 실제 agent_note의 capture capacity 분리, empty host context handoff, aged secret spool의 key/digest receipt 유출 방지를 적용했다. direct comparison과 receipt-backed reopening 참조 규칙도 문서에서 구분했다.
- R2 최종 전체 **1533 tests**가 DeprecationWarning=error에서 보고된 경고0으로 통과했다. lint/build/offline install과 새 immutable wheel의 실제 HTTP MCP에서30,645B judgment·17,449B selection의 전체 복원 및 철회 뒤 continuation 비노출을 확인했다. 최대 관측 wire6,353B이며 native 모델 소비·안정 전환 증거와 구분한다. 격리 임시 자원은 정리했고 원래 failed6/DLQ6·안정 운영 상태는 그대로다.
- 중단·복구 테스트의 강제 fork/상속 closure를 fresh spawn worker와 명시적 인자로 교체하고 process handle을 닫도록 했다. 같은 실제 디스크 기록 직후 exit41·재개·unowned config 보존 경계를 유지한다. 경고를 숨기지 않고 DeprecationWarning=error로 host447개와 멀티스레드 부모의 실제 crash/recovery smoke를 검증했다.
- R3는 관련 rejection 후보 최대8개/선택적 live history로 전체 이력 게시 의무를 제거하고 exact evidence 차단·snapshot/feedback ancestry privacy·모든 label metadata 검증·non-null policy를 유지한다. genuine candidate-state legacy reject를 활성 보존하고 notes의 신규 판단 queue 오염을 막는다.
- 반복 relation은 각 판단의 독립 전체 lineage/edge로 보존하고 공개 duplicate/logical read만 정규화한다. non-deriving selection 철회는 floor 없이 uncovered work를 재개하며 restored legacy held를 유지한다. cleanup은 고정 insertion bucket·examined-work 상한·durable progress로 분할한다.
- complete stored feedback까지 neutral continuation을 적용하고 live epoch/source-context를 저장 body에서 분리했다. application이 실제 framing 예산을 소유하며 source/response cap을 늘리지 않는다. nonstrict Codex child secret gap과 뒤 legacy outbox secret scrub도 durable하게 처리한다.
- genuine format-one init과 exact-SHA model approval intent retirement/replay를 추가했다. 원래 private signed/config/token·route audit를 보존하고 모든 구형 route를 disable하며 uncertain approval을 성공으로 가장하거나 Qwen을 재활성화하지 않는다.
- R3 첫 전체는1,654 pass/4 fail이었으며 폐기 note 검증2개 제거·선택 history fixture2개 수정 뒤 관련52개가 통과했다. 사용자 지시로 전체 재검사를1,543 pass에서 중단했고 이후 실패 경로만 확인했다. 전체 green을 주장하지 않는다. lint/sdist/wheel/offline install과 새 설치 CLI/HTTP MCP의 complete feedback6,900B/2창·무관 write 안정성·철회 비노출·typed malformed-kind refusal을 확인했다. 소유 임시 자원은 정리했으며 stable S9/failed6와 fresh official review/QA는 미완료다.
- R4 native 지적3건을 수정했다. note/feedback reason·memory source를 미판단 coverage에서 제외하되 미해결 human/일반 assistant/tool/document partial을 보존한다. local spool 격리는 inspected key+digest+payload CAS와 실제 mutation별 gap/error를 사용해 acknowledged replacement 유실을 막는다. OMP는 IPC object/소비 문자열을 검증하고 malformed reply를 HOST_RESPONSE_INVALID로 거절한다. 새 실패15개만 red→green(3.69s, `-W error`)으로 확인했고 실제 current-source CLI→HTTP MCP→PG에서 note/reason partial=false와 미해결 원문 partial=true를 관측했다. 이는 native 모델·stable S9·전체 QA 완료가 아니다.
- R5는 OMP의 optional preparation/capture 소비 타입 검증, expiry receipt 퇴출 뒤 늦은 remote ACK·확정 거절의 replacement 보호, prepare secret refusal의 restart-visible body-free gap을 수정했다. 새 실패10개만 red→green(1.54s, `-W error`)으로 확인했다. 공유 CorrectCommand는 wire 변경 없이 domain으로 옮겼다. 실제 설치된 rendered TS→CLI child→HTTP capture, 별도 CLI 프로세스의 거부 gap 보존, MCP 판단 완료 뒤 관측 gap의 partial 유지, 실제 producer correction 뒤 old-source 비노출을 관측했다. 이 증거는 native 모델·원래 stable S9·post-merge Agent Flow 설치 완료가 아니다.
- R6는0005 admission의 NULL request_digest를 strict DTO 이전에 ADMISSION_STALE/not_started로 거절하고 audit를 보존한다. 동기 migration thread는 반복 취소에도 실제 종료까지 exclusive lock 안에서 join하며 unknown 결과는 exact operator/request-bound migration fence로 유지한다. restore intent와 구분하고 이미 발행된 target config도 보존 원본에 결합해 재개한다. 새 실패5건만1 passed/1.29s·4 passed/2.16s(`-W error`)로 확인했다. 실제 CLI startup 차단/명시 복구와 HTTP SDK MCP의 구형 admission 거절→새 같은-key 판단 commit을 관측했다. 원래 stable S9/failed6와 공식 승인·게시 완료를 뜻하지 않는다.

### 보존된 누적 구현 이력

아래의 Qwen·회사 lexical 전용 capability·별도 selection 승인·구형 migration 서술은 이전 실행 당시 이력이며 현행 기본 경로가 아니다.


- PR #4 운영 리뷰 수정: 세 backup/restore CLI의 local PG 절대 실행 경로를 필수 입력으로 만들고 Docker container 이름은 유지했다. 첫 durable restore marker→fresh token→executor 순서로 바꿔 marker 이전 실패의 token 누수와 동일 출력 경로 retry 차단을 없앴다. 발행 후 실패는 UNKNOWN/private recovery 경계를 유지한다.
- 프로젝트·배포 패키지·CLI·MCP server 이름을 `agents-memory`, Python namespace를 `agents_memory`, 소비 프로젝트의 숨김 경로를 `.agents-memory`로 통일. 기존 데이터·삭제 저널·backup framing·실행 이력은 보존한다.
- 독립 Python 3.12 서비스와 네 개 MCP tool. 공식 SDK2.3의 modern stateless 및 legacy client가 동일 인증된 core를 사용한다.
- PG18/pgvector authority, full-input evidence graph, lexical/vector/entity retrieval 및 실제 로컬 extraction/embedding/consolidation/rerank/cited reflection.
- Current credential/project grant, semantic idempotency, heartbeat/lease-generation fencing, causal readiness 및 publication/delivery 재검사.
- Trusted producer correction, independent HMAC/fsync deletion journal, original-origin replay floor, descendant hiding 및 local row purge.
- 정확히 세 convention scopes, exact digest/target-set 승인, frozen targets, 회사 공유의 managed Ed25519 approver 경계.
- 기본 optional 총 3개/2,400 UTF-8 bytes, 빈 선택의 context 본문 0, TextContent 단일 plane, required unknown/overflow fail-closed.
- 소유권/hash/drift를 검사하는 Claude/Codex/OMP 설치·해제, standalone CLI/MCP, bounded private capture spool과 native capability-gap 보고. native hook trust를 자동 변경하지 않는다.
- Pinned PostgreSQL dump + age streaming backup/restore, durable plaintext 없음, exclusive restore fence, fresh credentials, routes/rules/job 재승인·fencing 및 최신 surviving deletion floor 복구.
- 실제 실행에서 발견한 native JSON-schema envelope, qualification 누락/번역, unrelated consolidation, reflection bookkeeping prose, snapshot-aware retrieval 통계 결함 수정. 조건·예외를 원문 evidence 구절에 결합하는 regression을 추가했다.
- 적대적 리뷰 수정: 현재 eligibility·snapshot·route에 결합한 reflection receipt, 선택된 conflict/full-input relation lineage·final delivery, orphan job 종료, directional derived withdrawal와 원문 재생성 floor, producer의 protected-artifact 경계.
- 삭제 journal append 이후 오류는 committed floor/recovery-needed로 보고하며 fake rollback을 하지 않는다. installer의 interrupted ownership intent와 poison/backlog spool 복구, private no-clobber/durable write, restore fence·age identity stdin·구형 archive migration을 강화했다.
- 실제 원본 한국어/Vega evidence를 변경하지 않고 extraction/embedding/consolidation/recall/cited reflection을 검증했다. ISO8601 동등한 `Z`/UTC offset을 허용하고 다른 시각·비인용 timestamp는 거절하는 경계를 수정했다.
- 자동 prompt 의미 검색은 별도 `host-install --prompt-recall` opt-in으로 분리했다. 기본 설치는 무요청 memory body를 주입하지 않으며 명시 MCP 조회·capture·required action guard는 그대로 유지한다.
- 2차 적대적 리뷰 수정: correction origin을 floor 이전에 예약하고 committed/partial recovery를 구분. reflection query와 historical receipt는 body-free floor에 연결하며 upstream을 지우지 않는다. exact duplicate group의 withdrawal와 독립 provenance를 분리한다.
- Semantic route와 vector compatibility를 분리하고 embedding-only `index-recover`를 제공. 구형 archive의 migration prefix를 현재 forward target에 복원하며 immutable 기존 migration은 바꾸지 않는다.
- `init --resume`의 exact private intent·원래 owner/token 재검증, completed replay의 mutable 설정 보존. bounded no-follow/FIFO IO 및 subprocess 종료·drain·reap 경계를 강화했다.
- Required FALSE 제외·UNKNOWN 일반 조회의 opaque ref/본문 없음·protected action 거절. native UTF-8 envelope/marker 1,800-byte 상한, 16MiB action path projection, 24시간 TTL 및 물리적 spool 상한.
- Claude private local MCP의 실제 Git-worktree canonical scope를 수정하고 다른 worktree의 relay 실행을 거절한다. 설치·해제는 native trust와 사용자·AF 설정을 보존한다.
- 동일한 원본 30일→14일 정정 source를 바꾸지 않고 generic qualification/기간 grounding 지시를 수정해 실제 추출을 재검증했다. 세 native host가 다음 조회에서 14일·미승인 근거를 실제 소비했다. 과거 failed/DLQ 기록은 삭제하지 않았다.
- 3차 적대적 리뷰 수정: credential 폐기 전 body-free 영향 preview, required 영향의 명시 ack, 같은 immutable proposal/frozen target의 새 revision 재승인. 현재 migration은 `0004_operation_successors`다.
- 실패한 재처리의 원래 outcome과 successor를 분리. 관련 입력만 철회된 live capture는 남은 적격 manifest로 같은 causal owner를 복구하고 old lease/admission을 fence한다. 독립 relation derivation의 lineage는 유지하면서 recall의 동일 logical edge만 접는다.
- 구형 restore의 사전 FK/table 정리를 archive SQL과 같은 명시 transaction으로 이동. pinned `psql` executor는 age EOF/integrity와 SQL producer 성공 뒤에만 COMMIT하며 실패 시 현재 데이터/lineage/reservation을 보존한다. PG18의 별도 CHECK CONSTRAINT도 같은 schema/table allowlist로 검사한다.
- native advisory 훅은 지원 path tool만 선택하고 자체 MCP 호출은 broker에 위임한다. 관련 required rule이 없는 작업에 불필요한 context warning을 넣지 않으며 offered/current required revision 집합을 비교한다. producer HTTP credential은 capture/correct만 허용하고 context/inspect를 거절한다. UNKNOWN metadata는 fitting ref 수가 아니라 전체 미결 수다.
- 4차 리뷰 수정: index 복구도 원래 blocked/failed outcome과 새 successor를 분리한다. live recovery counts와 전체 durable row 상태 집계를 구분하고 중복 stats alias를 제거했다. unrelated roster 성장 후에도 같은 frozen target만 재승인한다.
- Claude 설치/recovery intent를 소유한 MCP key로 제한하고 실제 native mkdir lease에 협조한다. 현재 document와 publication 직전 lease/bytes를 재검사하여 무관한 native 설정을 보존한다. 비협조 writer·same-UID 경쟁에 대한 atomic CAS는 주장하지 않는다.
- 기존 schema의 명시 `migrate --confirm-deployment` operator CLI를 추가했다. current credential·동일 local migrator target·exclusive authority lock을 DDL 이전에 검사하며 살아 있는 서비스/restore fence에서는 거절한다.
- restore marker 발행 전후 실패의 `not_started`/`UNKNOWN` 효과를 구분했다. UNKNOWN 일반 조회의 fitting opaque stub에서 revision/digest를 제거하고 승인 stamp/body를 전달하지 않는다. 동일 원본 Korean Polaris query의 명시 실제 retry가 cited reflection으로 완료됐으며 현재 live pending/blocked/failed/DLQ/stale counts는 0이었다.
- 5차 실제 Codex 리뷰의 source 직접 inspect snapshot 우회를 수정했다. 같은 core의 MCP/API/CLI가 active 원문 반환 전에 누락·불일치를 거절하며 global source와 matching snapshot은 유지한다.
- spool TTL을 receipt뿐 아니라 pending·quarantine 본문에 집행한다. 원래 age를 durable하게 보존하고 overdue/unknown-age legacy row를 전송하지 않으며 body-free gap/expired receipt로 손실을 알린다. 대량 expiry tombstone 때문에 fresh confirmed receipt가 즉시 퇴출되는 문제도 수정했다.
- stdio relay가 검증한 bounded HTTP 오류의 effect를 보존한다. invalid/truncated/mismatched/disconnected 결과는 unknown으로 표시하고 raw 진단·자동 mutation retry를 하지 않는다. 실제 loopback transport와 private SQLite/same-source PG smoke를 별도로 관측했다.
- 6차 실제 native 리뷰: OMP `before_agent_start` 예외 뒤에도 실제 custom provider가 한 번 dispatch된 결함을 재현했다. 새 strict 설치를 쓰기 전에 거절하고 advisory를 유지한다. 역사적 strict receipt는 owned cleanup만 가능하며 실행/replay 권위로 쓰지 않는다.
- 일시적 journal/DB heartbeat 장애는 마지막 확인 lease의 monotonic deadline 안에서만 재갱신한다. 동일 owner의 더 최신 deadline은 admission에서만 허용하고 모든 나머지 lease field·exact heartbeat/publication fence·현재 credential/source/route 검사는 유지한다. 실제 isolated PG에서 마지막 attempt의 두 healthy 작업이 consolidation까지 semantic_ready가 됐고 old heartbeat는 거절됐다.
- authoritative source speaker를 claim span/recall/reflect 입력에 보존한다. 기존 source/spans를 읽을 때 metadata를 join하므로 재추출/DB migration 없이 현행 label을 전달한다. extract 입력에는 이미 speaker가 있었으며 extraction-loss 주장에 따라 불필요한 prompt/route 변경을 하지 않았다.
- 사용자 승인 프로젝트 한정 AF runtime compatibility patch: hosted review가 기존 public `run_distribution(timeout_s=...)`에 `AGENT_FLOW_REVIEW_TIMEOUT_S`를 전달한다. 기본600초·허용1–3600초이며 이 프로젝트의 private continue wrapper는1800초/동시3을 사용한다. global AF·frozen skill·모델/xhigh·12개 angle·verdict gate는 변경하지 않는다. malformed/0 timeout은 실제 CLI에서 review dispatch 전에 거절됐으며 전체 재리뷰 통과와는 구분한다.
- 원천의 nullable `source_event_time`·distinct `source_recorded_at`을 claim evidence/recall/inspect에 보존한다. reflection generation은 typed assertion 또는 cited-source 선택으로 나누고, inspect의 각 문장에 원래 source metadata를 `source_provenance`로 결정적으로 붙인다. 모델의 timestamp/field prose 예외를 제거하여 assertion·limitations의 quote-only grounding을 유지한다. event unknown을 recording/extraction 시각이나 validity·승인으로 대신하지 않는다.
- native required-context budget에 마지막 denial envelope를 예약하고 초과 시 본문 없는 refusal을 반환한다. durable generation/state·rule stamp의 typed bounded schema를 검증하여 malformed state를 reset하거나 rule 전달 성공으로 보고하지 않는다.
- `model approve`의 중복 purpose 등 설정 오류를 artifact 검사·설정 파일 publication 이전에 검증하여 기존 private config를 보존한다.
- operator `project relocate`의 exact locator/revision CAS·semantic idempotency·current grant 검사를 추가했다. 같은 binding·memory·승인 target을 유지하고 roster를 늘리지 않는다. 삭제된 linked worktree의 exact-owned modern native cleanup은 기록된 canonical project key만 제거하고 root/trust/spool을 보존한다.
- 추가 영상·Skills Over MCP의 두 native 상호 반박과 원문 정정을 보존했다. 현행 four-tool/PG ledger·candidate≠approval·bounded opt-in을 유지하고 trace/distiller/code-shadow/Skills 기능은 실제 trial 뒤의 독립 decision gate로 분리한다.
- fix-loop native 복구: 삭제된 normal/linked Claude root의 exact modern deletion-only `removing` intent를 receipt durability/native-key publication 중단 이후 반복 재개한다. validated private receipt bytes를 한 번만 parse한다. 실제 symlink-loop 등 예상 밖 adapter 실패는 strict native body-free denial/exit0 또는 advisory warning이며 durable generation state를 reset하지 않는다.
- fix-loop model approval: hash-only exact recovery intent·cooperative lock·최신 config 보존·확정 보상과 truthful effect를 적용한다. 재인증 principal/credential/generation/role/realm을 결합하고 초기 authority close를 publication 앞에 완료한다. pending retry의 초기 journal barrier도 `unknown`이며 원래 동일 credential 요청만 reconcile한다.
- fix-loop semantic input: cross-encoder에 qualified draft·원문 quote once·speaker/event/recorded clocks만 전달하고 opaque row/extraction-time noise를 제거한다. reflection 모델에는 원문 quote/speaker만 주고 source clocks는 코드에서 전달한다. 실제 input shaping의 `models.py`를 semantic fingerprint에 포함하며 embedding geometry compatibility는 독립 유지한다.
- fresh native 리뷰 수정: reflection inspect가 저장된 limitations를 보존하고 문장/provenance보다 먼저 예산에 예약한다. caveat 누락 시 assertion을 전달하지 않으며 JSON 구분자까지 4,096-byte 상한에 포함한다.
- 확정 보상된 model approval intent는 fsync 종료하여 폐기된 credential에 묶어 두지 않는다. unknown intent는 자동 폐기하지 않고 현재 operator의 `--supersede-pending-intent <exact SHA256>` 새 승인으로만 대체할 수 있다. actual isolated PG의 CLI adoption 직후 crash→restore authority recovery→fresh-credential 승인으로 검증했다.
- 같은 semantic revision의 승인 purpose 축소는 같은 DB transaction에서 빠진 purpose를 비활성화한다. 이전 설정의 소비자와 이전 admission도 즉시 거절하며 남은 purpose는 fresh admission이 필요하다.
- 재리뷰 must-fix: 없는 project 경로의 `host-uninstall`은 `HOST_PROJECT_ABSENT`로 거절하고 `--project-deleted` 확인 뒤에만 native 항목을 정리한다. 이 경우 `native_removed`/`native_uninstalled`와 `project_entries: unverified_absent`를 보고한다. 정리 범위는 durable `native_removing` 상태로 남아 중단 뒤에도 `removed`로 끝나지 않는다. root가 다시 나타나면 stale hook과 재설치는 `HOST_UNINSTALL_INCOMPLETE`이며 일반 uninstall이 project 항목을 제거해 `removed`로 끝낸다. 바뀐·이동한 owned hook, 바뀐 TOML·native key와 비정상 `mcp_servers` 값은 부재가 아니라 `HOST_OWNERSHIP_DRIFT`다. 이전 형식 native-only `removing` intent도 `native_removed`로 끝난다. 재등장 root 정리는 `native_finishing` 중단 뒤에도 현재 파일을 재검사한 경우에만 `removed`이며, install·uninstall은 lock 대기 전에 root를 descriptor로 고정하고 intent 기록·적용·재개와 uninstall 검사를 그 기준으로 하므로 경로가 이동했다 복원돼도 부재를 삭제 완료로 보지 않고 비워진 경로를 다시 만들지 않으며, lock 직후·intent 기록 전·terminal 기록 전 경로가 고정한 디렉터리를 가리키지 않으면(lock 대기 중 소실·교체, `host-install`의 중단된 `pending`/`removing` 재개, native writer lock 대기 포함) recovery intent를 보존한 채 `HOST_CONFIG_DRIFT`이고, owned 항목 변경을 시도했거나 intent를 기록·replay한 뒤의 모든 거절(rollback 실패, native publication 뒤 lease 상실, 재개 뒤 `HOST_UNINSTALL_INCOMPLETE`·마무리 검사 거절 포함)은 effect `unknown`이며, 명령 사이에 같은 경로의 디렉터리를 바꾼 경우는 경로에 묶인 receipt 모델대로 새 디렉터리를 그 project로 검사한다. owned 설정 경로의 디렉터리·socket은 `HOST_CONFIG_INVALID`이고, 따옴표가 든 receipt 경로의 Codex hook은 `args`가 있거나 `--receipt=PATH` 형식이어도 drift로 탐지하며 해석 불가한 남의 hook은 uninstall을 막지 않는다. 모델 입력 projection의 purpose별 필드를 회귀로 고정했다. 비정상 list 상태값도 `HOST_RECEIPT_INVALID`로 거절한다.
- 재리뷰 should-fix: supersede 교체 쓰기 실패는 `MODEL_APPROVAL_RECOVERY_REQUIRED`/unknown을 그대로 보고하고, 교체 뒤 확정 보상은 원래 unknown intent bytes를 복원한다. 모델 입력 projection을 `models.py`의 include-list로 바꿔 fingerprint 밖 `domain.py` 필드가 모델에 새지 않게 했다(현재 payload는 동일). consolidation 지시에 source clock≠validity·supersession 경계를 추가했다. architecture/implementation-plan에 relocation·deleted cleanup·approval intent/supersede·reflection provenance 계약을 기록했다.
- 회사 lexical/entity capability: `init --capability lexical_entity`로 로컬 ML 없는 회사 배포를 만든다. capture coverage와 body-free source pointer, `memory_record`의 strict `source_selection` 판단(remember/discard/review), grounded candidate 게시, lexical·entity RRF recall과 durable nonmodel admission·final delivery fence, binding별 selection policy 승인·epoch, `captured`/`selection_recorded`/`candidate_ready` terminal을 추가했다. reflection·reprocess·vector 복구·model 명령은 `CAPABILITY_UNAVAILABLE`이다. forward migration `0005_company_selection`, revision별 archive allowlist, purge floor 재scrub, init capability fingerprint, host adapter v4 pointer 전달을 연결했다. 개인 full-semantic 동작은 유지한다.
- 업그레이드 안내: host adapter v4 receipt는 배포 capability(`capability`)를 기록한다. 기존 v3 receipt와 이 변경 전에 설치한 v4 receipt는 실행 전에 거절되므로 `host-uninstall` 뒤 `host-install`로 다시 설치한다. prompt recall을 켜지 않은 설치는 capture 상태를 model context에 넣지 않고 hook 결과의 `capture` metadata로만 남긴다. selection 안내는 `lexical_entity` 설치에만 나온다. 삭제 journal의 새 `purge` 기록은 이전 binary가 읽지 못하므로 업그레이드 뒤 이전 버전으로 되돌리지 않는다.
- 회사 리뷰 수정: 생략한 `memory_record.kind`는 기존 note로 처리하며 MCP에는 deployment별 flat object schema를 제공한다. dense 원문 window는 span 수와 비ASCII escape가 포함된 wire 예산에 맞춰 줄이고 continuation을 반환한다. default capture coverage는 이전 digest를 유지하며 모순된 byte coverage는 거절한다. relocate·policy revision 변경 뒤 기존 candidate를 숨기지 않고 drift를 보고한다. candidate 없는 required-context는 selection policy와 분리하고, nonmodel admission은 bounded로 만료 정리한다. purge는 irreversible journal 기록 전에 target-bound key를 선점하며 새 purge floor와 restore 때만 전체 scrub을 수행한다.
- 회사 재리뷰 수정: 확정된 `CAPTURE_COVERAGE_INVALID`는 spool quarantine으로 격리해 후속 capture가 진행된다. unknown effect는 격리하지 않는다. 구형 operation의 두 provenance 필드가 모두 absent/null인 ACK와 exact correction-origin의 `kind=correct` ACK는 scope·provenance 검사를 유지하며 reconcile한다. capability 없는 기존 v4 receipt는 정확한 historical metadata·ownership이 검증된 공식 cleanup에만 허용하고 실행은 계속 거절한다.
- 현재 run 재리뷰 수정: flat `memory_record` schema에 typed variant의 required/allowed 조건을 보존하여 누락·혼합 입력을 사전 검증할 수 있게 했다. 로컬 API credential은 owned/private regular file에서 최대2050 bytes만 nonblocking으로 읽고, FIFO·symlink·oversize·불안전한 권한을 dispatch 전에 `CREDENTIAL_INVALID/not_started`로 거절한다.
- QA fixture 안정화: publication/withdrawal 회귀의 pending/attempt0(초기 또는 재계획) 작업만 명시적으로 due 상태로 준비한다. DB wall clock이 되돌아가도 fixture setup이 즉시 lease를 가정하지 않으며, operation 범위와 attempts0 조건으로 다른 예약 retry를 건드리지 않는다. 제품 scheduler·retry 정책·업무 assertions는 변경하지 않았다.

운영 상태·검증 층위는 검증 기록을 따른다. cloud provisioning과 실제 1–2주 trial 완료는 이 변경의 완료 주장에 포함하지 않는다.
