# agents-memory 체크포인트

## 현재 수정 재개 — development/20261016-110757

- 네 번째 공식12개 결과는3 approve/9 request-changes였다. 정상 fix-loop 한도 뒤 사용자가 기록 보존 후 계속을 선택해 기존 run을 정상 종료하고 같은 branch/worktree에서 재개했다. 이전 판정·guard·pin을 바꾸거나 승인을 재사용하지 않는다.
- source/test/pyproject/lock `35d854f6…422daf0`에서 operator 철회/generation과 Jev 파일 변경 직렬화·strict scalar·명시 효과, fenced readiness, 설치 효과/upgrade code, 부모 선종료 자손 정리, remote pending-only/backoff/취소와 단일 flush 경계를 수정했다.
- wheel `5c0c838c…31abb1b`의46 source 일치와 실제 개인/회사 PG·launchd·Jev fence/unavailable·명시 stop/start·capture replay 보존 smoke를 확인했다. 합성 vendor callback이며 새 live Jev·구독 판단·native hook 보호를 뜻하지 않는다.
- [PR #9 P1](https://github.com/chonamdoo/agents-memory/pull/9#discussion_r4293624349)은 모든 ingress mode의 실제 loopback peer 요구로 수정했다. PG/ASGI66 pass와 개인/회사 실제 nonloopback TCP8개403·loopback200·정상 Caddy HTTPS를 확인했다. README PC service 순서와 fresh 양 모드 configure→service install→host-install→doctor도 실제 통과했다. direct Docker/합성 agent 증거이지 Compose·모델·운영 배포/침해 조사 증거가 아니다.
- 첫 fixture/OOM 실패·중간 source 변경 실행을 보존했다. frozen 새 전체 `uv run pytest -q`는 **2311 pass/skip0/573.27초**, Ruff/build·새 설치46파일 일치가 통과했다. OS network-deny sdist→동일 wheel과 hash 필수 build9/runtime34 새 consumer 설치도 통과했다. 새 공식 독립 review/QA/handoff·추가 commit/push·thread resolve·배포 완료는 아직 주장하지 않는다.
- 상세 실행과 한계는 [검증 기록](verification.ko.md#네-번째-리뷰-후-권한복구와-pr-보안-수정--development20261016-110757)을 따른다. 아래는 각 이전 checkpoint의 이력이며 현재 새 코드의 원격 게시나 전체 #5/trial/출시 승인으로 재사용하지 않는다.


## 공식 리뷰 후 fix-loop 체크포인트 — development/20261015-131245

### 현재 작업 checkpoint 게시 범위 — 2026-10-16

사용자가 “일단 지금까지 한 것으로 커밋·푸시·PR”을 명시 요청했다. 이전의 전체 완료 뒤에만 게시한다는 사용자 조건은 **현재 snapshot의 checkpoint commit/push와 Draft PR 게시에 한해 변경**한다. 기존 `docs/local-cloud-roadmap`→`main` PR #9을 갱신하며 native 보호·탐지 UX·공식 승인 review/QA/handoff·운영/평가/trial·merge/출시 gate를 완료 처리하지 않는다. 이 아래의 미게시 문구는 해당 실행 시점의 보존 기록이다. 실제 commit/remote HEAD·Draft 상태는 PR 기록으로 확인한다.

### 세 번째 리뷰 후 남은 코드 결함 수정

- genuine Opus5.5/Sol6.1 공식 결과는3 approve/8 request-changes/1 timeout이었다. 정상 fix-loop에서7개 blocking finding을 수정했고 다음 독립 리뷰·공식 QA/handoff로 진행한다. 전체 #5·trial·출시 완료는 아니다.
- 현재 source/test fingerprint `72cdb923…225cbb7`, wheel `290b2d08…31adaa8`의 noneditable46 source 일치를 확인했다. 첫 집중831개는826 pass/5 fixture fail, private state/producer credential 준비만 수정해 해당5개 pass다. 새 단일 전체 green으로 합치지 않는다.
- 실제 설치 launchd/PG에서 stalled/slow-drip 전체15초·408/not_started·부분 source0·회수 뒤 capture202, SIGKILL 재시작·DB ready·명시 stop/start를 확인했다. 실제 PG Jev 교체 장애는 선택 유지·구 토큰 거절·명시 재선택으로 복구했다. 합성 key/서비스/schema/실행 폴더는 제거하고 PG를 중지했다.
- Claude force-on/settings env·doctor effective provider/project 경계·과거 strict receipt의 active 거절·service 오류 효과를 수정했다. native trust·기억 본문·사용자 원본 키를 변경하지 않았다. 이미 실행 중인 old binary나 실제 native 보호를 해결했다는 뜻은 아니다.
- age Sigsum 검증기 실행·변조 negative, 공개213 checksum·Go module h1/license, 격리 Linux canary를 확인했다. out-of-band 키 신원·전체 P3/native 격리·copyleft/법적 배포 승인은 남는다. 상세·이전 실패 이력은 [검증 기록](verification.ko.md)을 따른다.

### 남은 작업 재개 — native 진단·안정 상태 확인

- `native-status`·`doctor --project`와 설치 결과의 metadata-only 공존 경고를 구현했다. 새 회귀29개와 실제 Codex CLI 진단을 실행했고, 합성 project layer disabled·project hook0/user4를 관측했다. trust를 쓰지 않았고 callback/보호는 미검증이다.
- 안정 배포를 정상 DSN/schema 해석 후 read-only transaction으로 조회했다. 현재0004·failed6/DLQ6이며 구형 실패를 retired/성공으로 바꾸지 않았다. 기존 CLI 기본 config 경로 부재와 schema 옵션을 직접 DSN에 전달한 probe 실패는 보존했다.
- 공식 PBS Python3.13.16/SQLite3.53.1과 build9/runtime34 hash closure로 OS network-deny sdist/wheel build·새 consumer 설치/CLI·46 source 일치·누락 wheel 거절을 실행했다. PG/vector·새 app image·age 공개 archive도 반입 자료로 보존한다. whole-OS/offline 제품 운영·법적 승인은 별도다.
- 당시 병렬 작업자들은 worktree guard 거절로 코드를 쓰지 않았다. 실제 쓰기는 bound controller가 수행했고 guard/pin/binding을 바꾸거나 worker를 공식 reviewer로 세지 않았다. 이후 정상 unprefixed status의 불가를 뜻하지 않는다.
- 같은 source fingerprint `7aca16e0…f5543`의 전체 첫 실행은1954 pass/235 fail/1 error였다. QA 임시 경로를 Git 밖으로 옮기고 일치 `VIRTUAL_ENV`를 준 뒤 제품/테스트 bytes 변경 없이236개 실패만 전부 통과했다. lint/build도 성공했다. 이를 단일 전체2190-pass로 합치지 않는다.
- 실제 Opus5.5 Jev-deny/agent preflight P01/P02/R04는 각각 discard·조건/예외 claim 재조회·의미 재유입 discard를 관측했다. 중간 MCP 오류4회·다른 claim의 gold 미판정·native 소비 미관측을 남겼고 전체 품질/효익/trial로 확대하지 않는다.
- 삭제된 #3의 보존 원문에서 A1–A7/B1–B7을 재확인해 [runbook](release-runbook.ko.md#원래-계획-리뷰14건의-증거-연결)에14개를 각각 연결했다. native/OS/stable/독립 gold·고정 workload/제한 운영의 공백을 완료로 바꾸지 않는다.
- 별도 범위인 transcript/tool-I/O capture 확장·도구 digest P2·건강관리 writer/자동 audit·임베딩 도입은 이번 patch에 넣지 않는다. 기존4도구·원문·승인·삭제 core를 유지하며 실제 데이터/허가/평가 없이 자동 승격·추가 egress를 열지 않는다.


### 이슈 #5 후속 — 승인 없는 구현·검증

- 현재 fingerprint `744b84b1d7cbd6a885a7ed494c035081d90b19d97f3fbe99d093a0e187297f15`, wheel `d16b73fe4ffe25515dd21e9fa95b3fdc96b563b2765d512936fe3155b08ed73d`. 새 Codex `--strict`를 쓰기 전 명시 거절하며 자동 advisory downgrade하지 않는다. 명시 구독 MCP는 유지하고 native 보호 구현 완료와 구분한다.
- 새 설치 CLI의 strict 신규/기존 advisory 파일 불변·foreign MCP/hook 보존 uninstall, 실제 advisory stdio MCP→HTTP/PG의 retract/purge 두 재유입 경로를 확인했다. 옛 origin/body/claim/lineage는 부활하지 않고 새 origin은 재판단 전 비노출·판단 후 새 claim/source만 citation이다. R05 오류 계약을 보완했다.
- 설치/업그레이드/incident runbook을 작성하고 app+runtime34 hash local 설치·pip check·isolated43파일 일치·lock SBOM/35 license-file inventory를 준비했다. 전체 OS/interpreter/PG/tools/age/build backend·다른 ABI·legal/release 승인은 별도다.
- Ruff/build 성공. 첫476pass/7fail 계약 fixture와2113pass/48fail의 Homebrew Cellar0775 ancestry 거절을 보존했다. private regular interpreter·정상 ownership·동일 binary/prefix alias·isolated source와 실패 표면69개를 검증한 뒤 **정확한 `uv run pytest -q`:2161 passed·skip0·518.79초**를 통과했다. 공식 QA 승인은 아니다.
- normal native approval용 cold fixture는 이전 ce8a4d99 wheel/strict 정의다. 새 candidate의 지원 strict로 취급하거나 source 일치 검사 없이 시작하지 않는다. native 승인만으로 보호 구현이 완료되지 않는다. fresh 공식 승인 review/QA/handoff·안정 cutover/OS lifecycle·frozen 평가/PMPA·native memory 탐지 UX·실제1–2주 trial·commit/push/runtime PR/merge는 여전히 미완료다.


### 직전 source의 재개·두 번째 공식 review/fix-loop — 2026-10-16

- 설치형 canonical status/continue를 보호 설정 변경 없이 복구했다. fresh confined Opus5.5/Sol6.1 wave는10완료(approve4/request-changes6)·Claude2timeout으로 request-changes였고 정상 두 번째 fix-loop에 있다.
- 재시도별 Jev admission, deny crash의 reallow 복구, 발급 전 private intent와 PG clock commit 직렬화, 명시 invalid-state repair, effective provider 표시와 project-add committed effect를 수정했다. 익명 readiness는 단일 live journal 검증을 공유·종료 시 join한다.
- 새 lint/build·집중 회귀와 checkout 밖43-file 일치 wheel의 실제 HTTP503/복구·합성 live Jev remember/active claim을 확인했다. 키는 프로그램만 읽고 원본을 보존했으며 사본 삭제·deny/agent·native service disabled/stopped로 종료했다.
- QA interpreter와 MCP 자식의 project 설치 prerequisite를 정상 격리 환경에서 수정했다. 제품 guard·테스트·Homebrew 권한을 바꾸지 않고 **정확한 `uv run pytest -q`:2164 passed·skip0·518.43초**를 통과했다. 첫48실패와 다음1실패·각 원인은 검증 이력에 남겼다. copied interpreter/locked hashed dependencies/editable current project를 `UV_NO_SYNC=1`로 재사용했으며 공식 QA 승인과 구분한다.
- 같은 새 wheel에서 실제 구독 Claude Opus5.5·Codex6.1Sol·OMP openai-codex6.1Sol도 deny/agent·키 없음으로 다시 실행했다. 원문 판단·active claim·전체 relevance·같은 claim과19시간/audit 예외 최종 context를 각각 확인했다. 이는 native strict 첫 행동 차단이나 신규 preconnect/TCP0 관측이 아니다.
- 사용자 승인 통지 후 실제 Codex0.162.1의 정상 hooks/list/config/read를 실행했다. 당시 user source4개·project0개였고, project `.codex` layer가 exact folder의 trusted-project 미등록으로 disabled라고 명시됐다. 정상 Folder access→Trust and continue와 이어진 project exact-hook 검토가 필요하다. 이 현재 이유를 과거 patch 실패 전체 원인으로 단정하지 않으며 trust state/API write나 입력 carrier 우회는 하지 않았다. 실제 native 보호/복구·승인 재리뷰·공식 QA/handoff·전체 #5·trial·runtime 게시는 아직 아니다.
- 이번 재개 검증의 임시 native 등록3개·credential6개·private project/trace·QA env/cache를 정리했다. owned service disabled/stopped와 PG stopped를 확인했다. 정상 native 승인 재검증용 최소 private fixture만 보존했으며 Downloads 원본·global auth/trust·user research·공식 run 증거는 유지했다.

### 첫 fix-loop 당시 기록 — 후속 수정 전

- 실제 공식 리뷰는 request-changes였다(11완료: approve4/request-changes7, 별도1timeout). HTTP 전체 deadline·recovery budget·spool 단일 flusher·launchd crash intent·Jev 정책/retirement/commit 경합·bootstrap/CA/Unix socket/공개 ingress 경계를 수정했다.
- 최종 source 직접 gate는 Ruff/build 성공, **전체2,143 passed·skip0·511.34초**다. 실제 slow HTTP/TLS16경우, launchd 설치/삭제 crash intent·SIGKILL·durable stop, 새 개인/회사 cloud43개 source와 HTTPS+DB crash recovery, checkout 밖 새 wheel 소비자를 실행했다.
- Downloads 키는 프로그램만 읽어 합성 live Jev remember·active claim을 다시 확인했다. 원본은 유지했고 검증 후 deny+agent와0600 사본 삭제를 확인했다. 안정 운영 Jev나 실제 회사 corpus 전송을 켠 것이 아니다.
- 최종 source의 실제 구독 Claude·Codex·OMP는 모두 deny/agent에서 독립 원문 판단·claim·전체 relevance·동일 claim과 예외 최종 read를 통과했다. 이는 advisory MCP 결과이며 native strict 보호와 다르다.
- **Codex strict는 미완료:** 유효 단일 patch가 실제 파일을 변경했다. owned 합성 파일은 기록 후 원복했고 invalid-patch 실패를 차단 성공으로 계산하지 않았다. native 활성·신뢰·실제 callback 확인이 필요하다. Claude 실제 Read의 healthy/stop/recovery 차단과 무부작용은 확인했지만 provider input 소비 보장은 아니다.
- 당시 canonical launcher와 소유 TUI stdin 제어가 guard에 거절된 기록을 보존했다. 위 재개에서 launcher는 정상 복구했으며 TUI/trust를 우회하지 않았다. 현재 gate와 source별 실행 경계는 [최신 상세](verification.ko.md#공식-리뷰-후-fix-loop--development20261015-131245)를 따른다.
- 검증 뒤 owned native entry5개·서비스·합성 schema/role·container7개·VM 비밀/data·private key/trace/QA 상태를 정리했다. unrelated container2개의 ID/running/start time과 Downloads 원본·global auth/trust는 보존했다. 새 실행에는 정상 fixture 재준비가 필요하다.
- 후속 최종 정리로 재개용 private Python/venv/cache와 partial 실패 manifest까지 포함한 임시 root도 제거했다. owned root 프로세스0·runtime container0, 미사용 proof image tag2개 제거를 기록했다. 공식 run 증거·user research·shared base/cache·사용자 서비스·LSP mux는 보존했다. 재개 때 정상 런타임/fixture 준비가 필요하다.

## 구현-phase 실행 기록 — development/20261015-131245

- PR #9 remote는 문서·이미지8개이며 runtime은 이 managed worktree에만 있다. commit/push·merge·안정 운영 설치를 하지 않았다. 아래 “최신 전환” 등의 제목은 과거 실행 당시의 기록이다.
- 최신 사용자 지시에 따라 cloud **개발·합성 실행**을 실제1–2주 trial 이전에 진행했다. 실제 운영 cloud provisioning·회사/개인 corpus 이동·배포·게시의 별도 승인을 없앤 것이 아니다.
- 로컬/클라우드 × 개인/회사 × deny·allow미선택·allow명시Jev의12경우를 분리했다. 네 선택 Jev 경우는 프로그램만 읽는 비공개 키와 실제 vendor 응답으로 검증했고, 나머지8경우는 구독 Claude Opus5.5/Codex6.1Sol/OMP의 실제 원문 판단·엄격한 extraction·전체 relevance·동일 claim 최종 read로 실행했다. no-call의 내부 request counter와 원격 packet 관측 범위는 [현재 검증 절](verification.ko.md#pr-9-후속-원격-구현--development20261015-131245)을 따른다.
- typed remote client·현재 PG 권한에 묶인 bearer/OAuth·한 binding bootstrap·검증 HTTPS·PC-only spool supervisor·safe not-started session 재초기화·offline owned cleanup을 구현했다. PC는 DB/operator 비밀을 받지 않는다.
- 실제 migration Unix hostname 해석 실패, shared namespace app crash 뒤 Caddy HTTPS 미복구, clean launchd의 frozen Claude path 미사용으로 인한 outbox 정체, stop→즉시 start race를 재현·수정했다. 독립 proxy/app Compose·정확한 private peer·기존 SCRAM PG socket의 새 package와 원격 PC 복구를 실제 실행했다. proxy에 app 비밀/journal/socket을 mount하지 않는다.
- SQLite 영향 WAL 버전은 spool 생성 전에 거절한다. 실제 지원 private Python3.13.16/SQLite3.53.1과 새 설치 wheel의 전체34 module·8 migration bytes, checkout 밖 설치 CLI/SDK4도구·macOS client 운영·offline cleanup을 확인했다. 세부 hash·실패 이력·한계는 검증 절에 기록했다.
- 통합은2017 pass/1 fail/11 skip이었다. 마지막 missing-cwd 분류 수정 뒤 실패 node만1 pass/4 deselected를 확인했다. 전체 green이나 fresh 공식 QA라고 하지 않는다. build는 해당 수정 후 성공했고 설치 wheel도 그 source와 일치했다.
- 선택 Jev의 양 local mode 실제 launchd crash/stop/outbox 결합과 양 cloud mode의 실제 HTTPS correction/retraction·encrypted archive restore·최신 삭제 floor/새 credential 다음 read도 실행했다. 개인 driver가 마지막 operator를 잘못 폐기한 cleanup 실패는 숨기지 않았고 부모가 해당 owned 합성 배포를 정상 철거했다(인증 우회/권한 재활성화 없음). 회사와 shared PG는 보존했다. 이 기록 시점 공식 runner는 `implement`이며, 이후 공식 review/QA/handoff 결과와 미완료 gate는 run report·정본 이슈를 따른다. 전체 #5 운영·평가·실제 trial·게시 완료를 대신하지 않는다.
- OSS·DB 성장·provenance/health audit/Accept/Reject/coalesce 검토는 [2026-10-15 연구 기록](research/)과 이슈 #5의 연구 댓글에 있다. 자동 건강 관리 writer·나이 기반 삭제·추가 telemetry/egress·embedding engine을 승인 없이 넣지 않았다.

## stage-0 동시성·복구 수정 — development/20261015-043508

- 사용자 승인 범위의 네 결함(MCP 세션 복구, 단일 DB 지원 계약, 창당 단일 판단 승자·응답 유실 재시도, 요청 상한·pool 기한·잠금 없는 인증)을 구현했다. 설계 근거는 `research/local-concurrency-observer-design.ko.md` P0-1..P0-4, 기록은 [이슈 #5 댓글](https://github.com/chonamdoo/agents-memory/issues/5#issuecomment-6184732526)이다.
- 처음 추가한 회귀 37개 중 26개가 수정 전 실패했고 수정 후 모두 통과했다. 리뷰 R1–R3에서 추가한 회귀는 수정 전 코드로 실행하지 않았다(reviewer 재현에 의존). 공식 리뷰 4회(R1–R3 지적 수정, R4 Codex 6개 approve; Claude는 R2에서만 실행), 공식 QA gate 3/3, 최종 wheel `a461ac83…`의 실제 서비스 smoke를 통과했다. 상세는 [검증 기록](verification.ko.md)의 stage-0 절이다.

## 이전 전환 이력 — recovery development/20261014-154435

- [이슈 #5](https://github.com/chonamdoo/agents-memory/issues/5)와 [확정 결정 댓글](https://github.com/chonamdoo/agents-memory/issues/5#issuecomment-6150124320)만 현재 작업 정본이다. 개인·회사 모두 사용 중 Claude/Codex의 MCP 판단→서버 검증으로 전환했고 Qwen 판단 경로는 제거했다. 회사 B·별도 회사 selection 승인은 없으며 lexical/entity는 후보 색인이다.
- R4 native 지적3건(note coverage·stale-quarantine replacement 삭제·OMP IPC 소비 타입)을 수정했고 새 실패15개만 `-W error`로15 passed/3.69s, 보고된 경고0을 확인했다. 실제 current-source CLI/HTTP MCP/PG 개인 schema는 note/reason coverage0·partial=false와 미판단 document coverage1·partial=true, raw note 보존을 확인했다. 실제 두 SQLite connection과 rendered TS/Node child IPC도 실행했다. 변경 Python lint·sdist/wheel build는 통과했다. owned process/schema/비밀 state는 제거했으며 전체 suite·native 모델·stable S9 proof는 아니다. 이전 negative/timeout/rate-limit·round3를 보존해 canonical abort하고 사용자 선택의 동일 범위 recovery run을 시작했다. 새 공식 리뷰/QA/handoff·원래 failed6·publication은 미완료다. 보고서는 현재 작업 뒤 읽도록 보류했다.
- R5 현재 Codex6개는 모두 완료/request-changes로 정식 FIX-LOOP에 반영했고 Claude는 OAuth401이었다. 첫 partial wave 원본12개·manifest는 hash 검증 archive로 보존했다. OMP prep/capture 타입·late remote completion replacement fence·secret prepare durable gap의 새 실패10개만 red→green(1.54s, `-W error`, 보고된 경고0)으로 확인했다. CorrectCommand는 domain 소유로 옮겨 실제 producer HTTP 정정→다음 MCP old-source 비노출까지 실행했다. 실제 CLI hook→capture→MCP complete-window discard 뒤에도 session/human-presence gap 때문에 unclassified0/incomplete1/partial=true임을 확인했다. 설치된 rendered TS→실제 CLI child→HTTP finding capture와 별도 CLI 프로세스의 secret gap 보존도 관측했다. 소유 임시 host/service/schema/비밀 state/driver는 제거했고 native trust·원래 stable 상태는 바꾸지 않았다. 새 source proof를 native 모델·stable S9 완료로 표현하지 않으며 현재 수정 후 fresh review/QA는 남아 있다.
- R6 fresh Codex6개가 모두 완료/request-changes였고 Claude는 OAuth401이었다. 새 NULL admission decoder·취소된 migration thread의 조기 lock 해제를 수정했다. immutable R5에서 신규5건만 실패를 재현하고 현재 code에서1 passed/1.29s·4 passed/2.16s(`-W error`, 보고된 경고0)를 확인했다. 이미 통과한1건·R4/R5·전체 suite는 반복하지 않았다. 실제 PG thread 중단→CLI startup exit3/listener refusal→명시 CLI recovery와 실제 HTTP SDK MCP의 stale/not_started·selection0→새 같은-key judgment commit/selection1·역사 admission 보존도 확인했다. service exit143·두 UUID schema 부재·비밀 state/driver/baseline 제거를 관측했다. 원래 S9/실제 failed6는 변경·승인하지 않았고 현재 수정 후 official review/QA는 남아 있다.
- 첫 리뷰 전 실제 합성 개인/company MCP·CLI에서 source selection, 두 호출 relevance/expansion, 네 관계, pending cleanup, reject 이유·재제안 차단·명시적 새 근거 reopening, secret·agent_note 경계를 실행했다. 실제0004 암호화 archive→0006 restore 후 surviving deletion floor와 fresh credentials·다음 읽기도 확인했다. 실행 시점별 결과와 증거 층위는 [검증 기록의 최신 전환 절](verification.ko.md#공통-coding-agent-판단-전환--development20261013-234417)을 따른다.
- 추가 사용자 지시에 따라 MCP의 CWD/리더/워크트리 제한을 제거했다. 두 실제 Git checkout의 동일 credential/binding 조회·cross-binding 거부 회귀가 통과했다. 당시 작업 프로젝트 자체에도 immutable bdcc1d…7c473 MCP entry를 임시 등록해 현재 coding agent의 실제 사용자 발언 판단→relevance→근거685B 회수를 실행했다. 이는 SDK 전송 증거이며 native invocation·안정 복구로 표현하지 않는다. 임시 연결/schema/비밀 state는 정리했다. fork 경고는 상속 closure/강제 fork를 명시적 인자의 fresh spawn으로 교체해 제거했다. 원래 exit41·복구·설정 보존 검증과 부모 스레드가 살아 있는 실제 smoke를 유지했고, 당시 host 집중447개도 경고를 오류로 처리해 통과했다.
- 사용자 승인 안정 전환은 아직 미실행이다. 새 immutable wheel/env는 준비했지만 current AF binding이 leader-root host-uninstall을 실행 전에 차단했다. guard/binding을 바꾸거나 다른 호출로 우회하지 않았다. 기존 안정 DB/config0004, v3 host3개, failed6/DLQ6은 그대로다. exact failure metadata·전환 전 owned receipts를 private evidence로 보존했으며 실패를 지우거나 완료로 세지 않았다.
- 리더 경로를 운영할 정식 실행 컨텍스트에서 ingress 차단·drain·암호화 backup·새 package/schema/owned host 전환·현재 agent의 legacy disposition과 stable native read 증거를 마쳐야 한다. 첫 fresh native review는 완료됐지만 request-changes이며, 수정 후 재리뷰·공식 QA/local-handoff는 미완료다. 당시 controller `w18:p9`는 더 이상 live agent가 아니며 새 리더-cwd pane 생성도 현재 guard가 실행 전에 차단했다. 다른 pane을 controller로 추정하거나 보호를 우회하지 않는다. 사용자는 이후 검증 준비 시 commit/push/PR을 조건부 승인했으며 merge는 승인하지 않았다. 아직 게시·commit·push·PR은 실행하지 않았다.
- 현재 bare canonical AF status/continue의 installed-assets-old 안내는 남아 있으며 pytest 경고와 별개다. 고정 run의 assets/runtime/profile/guard를 바꾸거나 안내를 숨기지 않았다. 이전 managed-launcher 호출에서 안내가 없었던 기록을 현재 경고 해소로 표시하지 않는다.
- 첫 리뷰 전 실제 native OMP18.10.4/Codex0.162.1 수동 MCP에서 각 모델의 판단 제출·근거 인용 회수·cross-binding 거부를 관측했다. Codex 회수는1785B/omitted2/partial, OMP는685B이며 capture completeness는 unknown이다. 별도 DB audit으로 selection2개·caller-grounded claim6개를 확인했고 소유한 임시 service/schema/비밀 state를 제거했다. 입력 거부·수정 시도와 요청 밖의 durable reject도 검증 기록에 보존했다. 안정 복구 증거와 혼동하지 않는다.
- 첫 공식 review는 Claude5개·Codex6개 request-changes, Claude I/O1개 timeout이었다. 정식 fix-loop에서 만료 cleanup·거절 이력 paging·cross-page 관계·삭제 전파·MCP wire 경계를 수정했다. R1 전체 **1,470 passed/254.25s, skip0, 보고된 경고0**, lint/wheel build가 통과했다. immutable5661495e…62c1011의 실제 서비스에서 source/request snapshot 분리를 확인했고 OMP/Codex native CLI도 각각 exit0이었다. 독립 audit은 remember2개·claim3개·feedback0개를 확인했다. 이는 R2 수정본의 실행 증거가 아니다.
- R2 공식 review는 Codex6개 request-changes였다. Claude는 OAuth 만료401로 실행되지 않았다. 부분 철회 후 legacy pending 유실, selection/feedback 삭제 경계, 큰 저장 판단의 전체 조회, temporal eligibility·agent_note capacity·empty host context·legacy spool secret receipt를 수정했다. R2 최종 전체 **1,533 passed/284.29s, skip0, 보고된 경고0**, lint/build/offline install이 통과했다. 새 immutable ee28459c…40a85df의 실제 CLI→HTTP MCP에서 judgment30,645B/8창·selection17,449B/5창을 전체 복원하고 철회 뒤 기존 continuation의 본문 비노출을 확인했다. 관측 wire 최대6,353B로16KiB 상한을 유지했다. 소유한 임시 service/schema/비밀 state·driver는 정리했다. 이 증거는 R2 native 모델 소비나 안정 S9 전환 완료가 아니며 공식 재리뷰·QA/local-handoff는 남아 있다.
- R3는 bounded rejection 후보/선택 history, request/derived privacy, genuine legacy reject/초기화/승인-intent 복구, 독립 relation lineage, non-deriving 재개/held, 고정 cleanup progress, neutral complete feedback와 durable host/spool secret 경계를 수정했다. 처음 전체는1,654 pass/4 fail이었고 구형 note 검증2개 제거·snapshot history fixture2개 수정 뒤 관련52개가 통과했다. 사용자 지시로 전체 재검사를1,543 pass에서 중단했으며 전체 green으로 표시하지 않는다. 이후 실패 경로만 확인했다.
- R3 historical wheel은79f54ae4…218566ab이고 당시 offline install·실제 설치 HTTP complete feedback6,900B/2창·철회 비노출 등이 관측됐다. R4/R5/R6 배포물 identity와 build 증거는 recovery run의 `runtime-proof/r4-package-identities.json`·`r5-package-identities.json`·`r6-package-identities.json`에 각각 기록하며 source-service MCP proof와 구분한다. 과거 R1/R2 native 결과를 이번 수정의 native 증거로 재사용하지 않는다.
- 사용자는 #5 전체 해결 후에만 commit/push/PR, main merge 확인 후 실제 Agent Flow 폴더의 merged MCP 설치/동작 확인을 요구했다. 아직 commit/push/PR/merge/최종 Agent Flow 설치는 하지 않았다. trial 기준은 정의만 했고 실사용 trial·memory-health 측정·회사 보안 우회·native 로그인/trust 변경은 없다. 아래는 이전 시점의 누적 이력이다.


## 2026-10-12 당시 결론과 상태 (이력)

독립 Python 메모리 서비스가 기준이다. Agent Flow·Claude Code·Codex·omp는 소비자이며 제품의 런타임 의존성이 아니다. 회사 로컬과 향후 개인 클라우드는 같은 application handler·승인·철회·출처·publication 계약을 사용한다. 회사 corpus를 개인 클라우드로 동기화하지 않는다.

현재 구현과 실제 실행 근거는 보존하지만 **정식 AF 리뷰·QA·handoff 완료, 1–2주 실사용 완료, 클라우드 배포 완료를 주장하지 않는다.** 사용자가 기존 워크트리 삭제와 리더 기준 최신 AF 업데이트·작업 재개를 지시했다. 아래 실행 순서는 계획이며, 실행 결과는 GitHub 이슈와 후속 승계 기록에 별도로 남긴다.

## 이미 구현·실행한 범위

- 독립 `agents-memory` CLI / `agents_memory` 패키지 / 소비자 `.agents-memory` 이름. 과거 불투명 저장 경로·opaque ID는 이름 변경을 이유로 마이그레이션하지 않는다.
- 공식 Python MCP modern/legacy 전송이 동일한 application handler를 호출한다. 연결 시 corpus/rule body를 제공하지 않으며, 요청 시 bounded context만 제공한다.
- 실제 PostgreSQL 18·pgvector, durable fenced 작업 큐, credential-bound principal/project/purpose, 정확한 revision 승인과 철회, 삭제·restore publication barrier.
- capture → 추출·조건·시간·entity → consolidation → hybrid recall·rerank → 근거 인용 reflect → correction/retraction → 다음 consumer read. 승인되지 않은 candidate는 규칙 authority가 아니다.
- 적용 범위 세 가지: 이 로컬 프로젝트 / 이 배포 안의 내 프로젝트 / 팀·프로젝트 공유. 개인 프로젝트 규칙에 팀 배포를 강제하지 않는다.
- opt-in Claude/Codex/omp adapters, host별 truthful capability, source/snapshot 검사, local spool·doctor·token·암호화 backup/restore journal.
- 루트 AGENTS.md/CLAUDE.md에 전체 convention·skill·memory catalog를 넣지 않는다. 명시된 모델 경로 외의 외부 route, 회사→개인 fallback, 모델 자체 승인, 연결 시 preload를 금지한다.

### 관찰된 검증 — 기존 실행과 승계 후 실행을 구분

상세 원본: [verification.ko.md](verification.ko.md).

- 직전 전체 실행: **747 passed, 91.75s, skips 0**, ruff exit 0, package build exit 0.
- fresh wheel을 checkout 밖의 offline/no-deps 환경에서 설치하여 실제 snapshot inspect를 실행했다.
- R19 실제 서비스에서 Claude Opus 5.5 xhigh / omp Codex 6.1 Sol xhigh / Codex 6.1 Sol xhigh가 각각 실제 MCP 호출 3회를 수행했다. 수정된 14일 근거, 승인된 규칙이 아닌 사실/candidate, 이전 source 철회, 다음 조회의 stale body 미반환을 확인했다.
- 실제 API 및 설치 CLI의 source/snapshot missing·mismatch 거부와 exact match 반환을 확인했다.
- discovery 282 UTF-8 B / 4-tool catalog 3,922 B / connection instructions empty / context 749 B / 그 응답 wire 1,741 B를 관찰했다. **전체 native prompt 비용이 0이라는 뜻이 아니며, bytes를 token 수로 바꾸지 않는다.**
- 위 수치는 직전 실행 증거다. 워크트리·설치 경로를 바꾸면 실제 기동·호출을 다시 확인해야 한다.

## 추가 조사와 실제 native 1차 리뷰

현재 정본은 [통합 이슈 #5](https://github.com/chonamdoo/agents-memory/issues/5)다. 삭제된 #1–#3의 원문은 #5 댓글에 보존되어 있으며, 아래 조사·리뷰 기록은 당시 이력이지 별도 현행 이슈가 아니다.

로컬의 [2026-10-12 조사 자료](research/2026-10-12-memory-skills/)에는 Boundary/HumanLayer/BAML 원문 조사, Skills over MCP 사양·SDK·host 조사, Runlayer 영상 Opus 원문 감사, 실제 Opus/Sol 1차 리뷰와 provenance, 추가 공개 소스 확인을 보존한다. 이 디렉터리는 **조사 자료이지 연결 시 주입되는 skill/corpus가 아니다.**

### 동일 잣대와 모델 실행 근거

- public/synthetic frozen packet: 27,917 UTF-8 B, SHA-256 `e616627f23ed5c7182956cbd990af6809894b96c490f2a9f4d146f5c1d15fac7`.
- 동일 prefix를 포함한 native stdin: 28,564 B, SHA-256 `13d0f5d8b2320888f428705fe99fc19b47d8a3fae71a0d880928907e48bb988f`.
- 두 작업을 병렬로 실행했다. Opus는 실제 Claude CLI `claude-opus-5-5 --effort xhigh`, exit 0, 411.454s; native JSON의 `modelUsage`에서도 모델 ID가 관찰되었다. effort는 전달한 CLI 설정이지 서버가 echo한 증명이 아니다.
- Sol은 실제 Codex CLI `gpt-6.1-sol`, `model_reasoning_effort="xhigh"`, exit 0, 308.157s; JSONL에 모델/effort 식별자가 별도 관찰되지는 않았다. argv 설정과 exit를 근거로 기록하며 self-report를 모델 증명으로 쓰지 않는다.
- 두 stdin이 같다는 증거이며 host system prompt까지 같다는 증거가 아니다. 두 리뷰는 read-only·도구 미사용이고 제품 성능 실험이 아니다.
- **신규 조사에 대한 1차 리뷰는 완료, 상호 반박/합의와 도입 결정은 미완료**다. 초기 설계 조사에서 완료했던 별도 round2와 혼동하지 않는다.

### 통합 시 바로잡아야 할 점

1. `procedure`는 이미 `MemoryWrite` 종류에 있다. 신규 memory kind를 만들자는 1차 리뷰 의견을 그대로 채택하지 않는다. 기존 `rule_candidate`도 승인 경로와 함께 재사용한다.
2. 새 Tech Bridge 영상 `jDdgfTp_PXw`와 AI Engineer 원본 `u-o0sW9nwmk`는 동일 발화의 재업로드다. 독립 두 사례가 아니다. 36→100은 vendor 단일 사례이며 n·기간·holdout·oracle·로그가 공개되지 않았다. 전후 동일 Sonnet 4.6·동일 harness를 자막만으로 검증하지 못했다.
3. Boundary 영상 `mAKUL12h1n8`의 stale-memory 대응·승인/거절 피드백·학습은 구현 수준과 향후 계획을 구분한다. **CueFinder 제품·codegraph 재사용·SQLite/FTS5 최소 구성 검토를 이 영상의 주장으로 포함하지 않는다.**
4. Python Skills SDK PR #3485 소스 병합은 실제 설치된 SDK 기능·Claude/Codex/omp native consent 지원을 증명하지 않는다. 확인한 SDK client 소스 위치는 `mcp/client/extensions/skills.py`다. main branch에 존재한다는 사실과 출시 패키지를 분리한다.
5. required applicability가 UNKNOWN이면 현재 계약의 fail-closed를 지킨다. 일반 advisory label로 바꿔 protected action을 진행시키지 않는다.
6. AGENTS/CLAUDE root 주입, catalog preload, untrusted skill의 자동 실행·자동승격, 조직 broadcast, 회사 cloud gateway, 부정적 feedback의 자동 authority 변경은 도입하지 않는다.

### 잠정 제안 — 코드 도입 승인이 아님

현 서비스·4개 bounded tool·PG authority·exact approval·lineage closure를 유지한다. 신규 기능을 즉시 추가하기보다 실제 trial에서 기존 procedure/candidate 경로의 재사용을 먼저 평가한다.

| 후보 | 현재 처리 | 이득 | 비용·위험·선행 조건 |
|---|---|---|---|
| 기존 procedure/candidate 재사용·명시적 사용자 feedback | trial 지침부터, 신규 authority 없음 | 잘못된 반복 제안·절차 재사용을 관찰 | feedback persist와 검증된 outcome을 혼동하지 않음; 승인/거절 revision을 정확히 연결 |
| 긴 규칙 stub + bounded/paged inspect·관련성 선택 | trial 후 별도 검토 | 긴 절차를 root preload 없이 필요할 때 읽음 | mandatory 범위·완전성·overflow·철회 검사 유지, 새 연결 시 catalog 금지 |
| 코드 의존성 변화에 따른 재검토 | stale trigger 설계부터 | 문서·코드 변화에 오래된 기억 재검토 | content hash를 코드 유효성 oracle로 취급하지 않음; unknown required는 거부 |
| opt-in verified outcome / 소량 tool trace / candidate distiller | 검증 기준과 host capture 가능성 확인 후 | 실패·수정의 원인과 다음 run 연계 | self-reported success가 verifier가 아님; 개인 opt-in, 경로 허용, 보존·삭제·비용 한도 |
| Skills over MCP | 지금 core 전환·5번째 대형 tool 없음 | 향후 정적·불변 읽기 전용 projection | 실제 출시 SDK·host consent·digest 재동의·origin identity·철회·lazy get을 먼저 검증 |
| 회사 corpus의 개인 클라우드 동기화·무인 자동승격 | 거절 | 해당 없음 | 보안·승인·배포 격리 불변식 위반 |

이 표는 동일 잣대의 현재 조사 분류다. 최종 순서·범위는 실제 두 native의 상호 반박 결과와 trial 근거로 확정한다.

## AF 업데이트 계약과 보존한 로컬 delta

- 이전 프로젝트 설치: v0.3.15, 공식 source `0ffba881a0c3f1c20f41359f205ef4e517ed5482`; global AF는 v0.3.14였다. 이번 요청은 **리더 프로젝트 설치**의 최신 갱신이며 global/다른 프로젝트를 임의 업그레이드하지 않는다.
- 2026-10-12 authenticated GitHub 조회에서 최신 공식 main은 `5b92996a38c6411c61f36d7be10aed1dc26405e5`였다. semver가 같아도 source commit이 달라 갱신 대상이다.
- `agent-flow update`는 확인 명령이지 설치 갱신 명령이 아니다. 공식 checkout과 리더에 복사된 managed assets를 별도로 갱신한다. active run 중 덮어쓰지 않는다.
- 선택 architecture는 `local`, frozen digest `11bb919aa0fe7defd4da85237192b8396c867740e8007753888d0d00b219a816`. `.agent-flow/project.yaml`, `profiles/python.local.yaml`, local architecture 원문·gates·모델 설정을 보존한다. 기존 run의 workflow binding/approval을 새 버전에 재핀하지 않는다.
- 사용자가 승인했던 프로젝트 private delta는 [timeout patch](../patches/agent-flow-0.3.15-review-timeout.patch)에 보관했다. default 600s; `AGENT_FLOW_REVIEW_TIMEOUT_S` 정수 1–3600; 실제 재리뷰 설정 1800s. 원 공식 `hosted.py` SHA-256은 `c55b644e6c7a1674776c500bfc870e019dd95e333a05666cf4ece882db7a897d`다.
- 패치의 실제 malformed/zero 설정은 CLI exit 2로 거부됐으며, 1800s native 재리뷰를 시작했다. 이전 600s timeout을 승인 verdict로 바꾸지 않았다. 새 공식 버전에 **무조건 재적용하지 않는다**. 공식 지원 여부와 exact source baseline을 확인하여 중복·충돌을 피한다.

## 다음 작업 — 순서 고정

1. 구현·문서·조사·승인된 runtime delta를 local commit으로 보존하고, 추가 조사 전체·현재 완료/미완료·모델 증거·원문 정정·다음 순서를 GitHub #1/#2에 게시한다. 소스 push·공개 배포는 하지 않는다.
2. 소유한 reviewer parent를 정상 interrupt하여 자식 process group을 종료한다. 지원되는 `abort`로 기존 run의 active 상태를 끝낸다. 공식 `abort`는 run 상태 변경이며 그 자체로 OS 프로세스 종료를 보장하지 않는다.
3. 기존 AF 설치·local profile·norm·원문·추가 조사 입력을 checkout 밖에 보존한다. 실제 지원되는 `worktree remove --keep-branch`의 run archive 검증을 이용해 **해당 owned checkout만** 삭제한다. DB·journal·tokens·모델·backup·사용자 연구 파일·다른 worktree는 삭제하지 않는다.
4. 리더를 보존된 `agents-memory` branch에 안전하게 전환하고, 개인 변경을 유지한 채 최신 공식 소스의 프로젝트 설치를 갱신한다. old run의 승인·marker를 새 run 완료로 재사용하지 않는다.
5. 게시된 GitHub 이슈와 승계 artifact를 다시 읽고, 최신 AF 계약으로 remaining-work successor run을 시작한다. Source 경로 변경 후 MCP 서비스·CLI·snapshot/native 경로를 실제 실행하여 확인한다.
6. 추가 조사 Opus/Sol 상호 반박: 각자가 상대 보고서와 위 원문 정정을 읽고 동일 잣대로 재평가한다. source 확인·제품 runtime proof·proposal을 구분하여 최종 도입/보류 결정을 기록한다.
7. 필요 수정만 구현하고 해당 경계 smoke를 수행한다. fresh formal reviewer 결과 → 필요한 수정 → gates → QA → handoff 순서를 완료한다. 그 뒤에 실제 1–2주 personal trial을 시작한다. trial 기간이 지나기 전 성공을 만들어 쓰지 않는다.
8. trial 결과로 장기 절차 전달·관련성·verified outcome 우선순위를 결정한다. 개인 cloud 인프라와 별도 credentials·network policy가 마련된 뒤에만 cloud deployment를 진행한다.

## 보안·취급 제한

회사 코드·대화·memory corpus·비밀을 GitHub/외부 연구 모델/개인 클라우드로 보내지 않는다. 팀 Claude/Codex 계약은 승인된 모델 route의 근거일 수 있으나 로컬 memory의 zero-egress 증명이 아니다. Git에는 token/DSN/age private key·개인 corpus·full raw provider internals·설치 venv를 넣지 않는다. 원문 자막 및 native 실행의 공용 근거 cache는 별도로 보존하고, 공개 성과로 과장하지 않는다.

## 리더 이전과 승계 실행의 실제 상태 — 2026-10-12

| 요청 항목 | 실제 결과 | 범위·제한 |
|---|---|---|
| 로컬 보존 | 리더 `agents-memory`에 `75474d9`, `970e9c8` 커밋 | 소스 push·main merge 없음. raw provider 내부 출력·token·DSN은 커밋하지 않음 |
| 조사 게시 | #2에 원문 조사·두 native 1차 리뷰·동일 입력의 2차 상호 반박·최종 도입/보류 결정 게시, 본문 일치 확인 | native 조사 보고서는 새 AF formal approval이 아님 |
| 이전 worktree 정리 | owned `feat-local-first-memory-pipeline` run을 중단·archive한 뒤 공식 remove 실행 | DB·journal·credentials·모델·backup 보존. 미완료 old verdict는 승계 승인에 쓰지 않음 |
| 프로젝트 AF 갱신 | 공식 v0.3.15/source `5b92996a38c6411c61f36d7be10aed1dc26405e5` 설치 | 기존 local profile/norm 보존. 사용자 승인 timeout forwarding delta만 exact compatible baseline에 재적용. global AF는 변경하지 않음 |
| 새 작업 재개 | `development/20261012-113028`, owned `feat-agents-memory-resume`, branch `feat/agents-memory-resume-local` | 리더 branch는 `agents-memory` 유지. 새 explore·implementation-plan 작성 |
| 첫 전체 검증 | 수정 후 공식 `gates --phase all`: lint·test·package 3/3, 834 tests 통과 | native locator 이전·시간 reflection 추가 발견 전 코드의 결과. 이후 수정은 다시 검증해야 함 |
| 실제 원천 시각 | 로컬 Qwen 추출·consolidation 이후 2020년 event time과 null event time을 recall/inspect에서 동일하게 관측 | 원래 recorded_at과 구분. 날짜 metadata가 fact validity·승인·supersession의 근거가 되는 것은 아님 |

2차 native 조사 전체와 최종 결정:

- [Opus 5.5·Codex 6.1 Sol 동일 입력 상호 반박 전문과 실행 근거](https://github.com/chonamdoo/agents-memory/issues/2#issuecomment-6124122866)
- [원문 정정·직접 영향 비교·최종 도입/보류 결정](https://github.com/chonamdoo/agents-memory/issues/2#issuecomment-6124123429)

재개 중 발견한 native 경로 문제는 같은 binding의 명시 operator 이전으로 해결했다. revision 1→2, roster 2 유지와 exact replay를 실제 CLI에서 관측했다. 삭제된 old worktree의 세 owned 설치를 정리하고 stable 리더 경로에 설치했다. Claude·Codex·OMP가 실제 `memory_context`와 두 `memory_inspect`를 호출하여 2020년 event time과 null event time, 원래 recorded_at을 동일하게 반환했다. native trust·provider-input attestation·strict 전체 lifecycle 성공을 주장하지 않는다.

실제 시간 reflection은 `MODEL_OUTPUT_INVALID`로 실패한 상태를 그대로 기록한다. exact-admission 읽기 전용 진단에서 로컬 모델이 허용되지 않은 `source_event_time of ...`/null field prose를 생성했다. 정확히 인용된 `field=ISO8601` annotation과 unknown prose의 경계는 별도 검증했다. source나 query를 바꾸어 원래 reflection이 성공했다고 표시하지 않았으며 validator·prompt를 완화하지 않았다.

이후 전체 공식 `gates --phase all`은 lint·test·package 3/3, **845 tests**가 통과했다. malformed native state의 실제 CLI는 body offer/reset 없이 `HOST_STATE_INVALID`를 보고했다. 다음 순서는 fresh confined Claude/Codex AF review → 필요한 수정 → QA → local handoff/커밋이다. 추가 조사에서 제안한 trace·distiller·Skills 기능을 끼워 넣지 않는다. 실제 personal 1–2주 trial과 cloud는 그 이후 별도 작업이다.

## 현재 fix-loop 재개 결과 — 2026-10-13

- 실제 source/check cwd는 `feat-agents-memory-resume` worker이며 leader `agents-memory`는 보호 상태다. 기존 공식 run `20261012-113028`을 이어갔고 회사 lexical/entity 기능은 넣지 않았다.
- HostRecovery를 parent 검토했다. 실제 loop fixture를 수정하고 validated receipt bytes의 single-read 경계를 검증했다. modern deletion-only removing intent 복구와 body-free native deny를 실제 filesystem/CLI cutpoint smoke로 확인했다.
- ModelApprovalRecovery에 publication 이후 current actor identity/generation fence를 보완했다. 실제 pending retry의 초기 journal barrier가 잘못된 not_started를 보고하는 결함을 재현하고 unknown으로 수정했다. 초기 authority close는 publication 전에 완료한다. isolated PG+actual model artifacts에서 확정 보상·최신 무관 설정 보존·exact retry·fresh admission을 확인했다.
- SemanticRecovery는 모델의 timestamp 재타이핑 예외를 제거했다. typed provenance selection과 strict assertions를 분리하고 source clocks는 각 cited sentence에 code-attached source_provenance로 전달한다. 실제 temporal/ordinary reflection이 성공했고 원래 failed owner도 query 변경 없이 명시 retry로 semantic_ready가 됐다. 원래 failed proof는 보존한다.
- 현재 route `d42da38effe7c83029ac9e691e94188cc64d6b05d5b5e936e1b1229b5b540463`, vector geometry `5746aa946889325cd26d84aafb3e1ac05ae4fccba400bfc6597431b26a1ac13a`. 실제 rerank relevant ordering과 9,295-token 입력의 8,192-token bound 거절을 관측했다.
- 전체 공식 lint/test/package gates는 **885 passed**, zero skips, green3/3이다. final comment checker도 pass다. 기존 7 approve/5 RC는 수정 전 snapshot이며 fresh review·QA 승인으로 재사용하지 않는다.
- 최신 wheel `afd0b5ee427da2a7509ce7d191d04eb52c15cdc8501d73477c58da9bf495ec6c`의 immutable offline noneditable venv와 서비스 R28을 실행했다. 실제 Codex authenticated plain-stdio가 retract 후 source/claim 본문 없음과 temporal provenance를 확인했다.
- 아직 설치된 Claude/Codex/OMP leader receipts는 worker executable을 가리킨다. bound AF가 leader uninstall을 실행 전에 차단했으며 우회·설정 변경은 하지 않았다. worker 삭제 금지. 공식 run 종료 뒤 허용된 operator 경계에서 owned uninstall/reinstall과 installed-native 호출을 완료해야 한다.
- epoch343 live stats는 failed6/DLQ6이며 전역 clean이 아니다. 오류 row를 삭제하거나 historical-only라고 하지 않는다.

다음은 fix-loop 증거 → fresh 공식 12 native 리뷰 → 필요한 실제 지적 수정 → QA → stable installed-host cutover/local handoff다. 정확히 승인된 leader 연구18개 drift의 승인은 미래 변경 허가가 아니다. 기존 AF 완료 후 회사 lexical/entity capability를 별도 공식 run으로 구현하며 optional native judge의 무인실행/반출 승인은 개인 smoke로 대체하지 않는다. MCP 배포 방식은 로컬 기능 완료 뒤 결정하고 실제 배포 승인은 분리한다.

## Fresh 리뷰 재진입 후 현재 상태

공식 fresh review는 Codex6개 **3 approve/3 request-changes**, Claude는 OAuth 만료401·5개 skipped였다. 각 실제 artifact hash/verdict를 취합해 overall RC로 fix-loop에 재진입했다. 새 지적 두 종류(limitations 누락, revoked/restored credential에 갇힌 approval intent)와 same-revision purpose narrowing 경계를 수정했다.

현재 소스의 공식 gates는 **892 passed**, zero skips, lint/test/package green3/3이다. 실제 persisted Application.inspect caveat 보존, actual artifact+isolated PG의 CLI commit 직후 exit41→restore authority recovery→fresh operator exact-intent-hash 승인, 이전 설정의 Store에 대한 omitted-purpose/old-admission 거절을 smoke했다. 마지막 comment checker도 pass다. `fresh-review-fix-smoke.proof.json`에 증거 층위와 한계를 기록했다.

다음 필수 전제는 사용자 native Claude OAuth 재인증(`claude auth login`)이다. auth status의 loggedIn true는 actual401을 해결한 증거가 아니다. 재인증 전 재실행·pin 변경·Claude 결과 복사·Codex-only 완료로 대신하지 않는다. 공식 phase는 다시 fix-loop이며 다음 전체12-pool review·QA·installed leader receipt cutover·local handoff가 남아 있다. source 작업 워크트리와 DB/journal/credentials/모델은 보존한다. 회사 capability 별도 run과 MCP 배포 결정은 이 기존 run 완료 뒤다.

최신 stable wheel은 `84ba86ade65a208e4f8390fbec59910e72fcd95e86b35b3ba7700b904e24a72e`, owned 서비스는 R29/pid41455/port8768이다. 실제 Codex의 inspect4회가 일반 reflection의 저장된 caveat4개, 원래 시간 provenance, 철회된 source/claim 본문 없음을 확인했다. 이전 package와 첫 smoke proof를 보존한다. 기존 세 leader receipts의 worker executable은 아직 이전하지 않았다. 다음 사용자 재인증 후 official continue부터 이어가며 worker를 제거하지 않는다.

## 최신 사용자 지시: Claude 제외, Codex 리뷰로 진행

“클로드 빼고 코덱스로 리뷰하고 넘어가 그냥”이 이전 stop/로그인 대기와12개/two-provider 조건을 대체한다. Claude OAuth R3를 종료하고 공식 지원 `AGENT_FLOW_REVIEWERS=codex`를 해당 invocation에만 적용한다. 현재892-pass 소스에 fresh 독립 Codex6개 angle(gpt-6.1-sol/xhigh)을 실행한 뒤 실제 verdict 취합→필요 수정→QA→owned installed-host executable cutover/local handoff를 완료한다. 이전3 approve/3 RC와 옛 Claude 승인은 재사용하지 않는다. runtime/profile/pin/보호/global 설정은 그대로다. 회사 기능 별도 run·실제 배포 승인은 여전히 이후의 별도 경계다.

## 설치형 leader 연동 — 2026-10-13

- 사용자 지시로 leader 프로젝트에 MCP를 실제 설치해 연동했다. 빈 bugfix run `20261013-040212`는 abort했다(산출물 보존).
- 현재 소스(917 passed)로 immutable wheel `0086e6c930c8…`, route `9e01d646…`, 서비스 R30을 띄웠다. 세 host receipt를 stable 실행 경로로 owned 재설치했고 AF 설정은 보존됐다.
- Claude record → Codex recall/inspect → OMP feedback(candidate 유지) → Claude reflect → Codex reflection read가 모두 성공했다.
- 남은 일: 3차 host 수정의 새 bugfix run(리뷰·QA·handoff), 실행 중 OMP 세션 재시작, 예외 구절 분리 품질 관찰.

## 인계 이후 stable 교체 — R31

- 수정된 worker의 wheel SHA256: `3ad2fb0a4627eee3ca62a66c5d5508d6af55470dc457192dce78e07728332172`. hash별 locked/offline venv에 설치했고 package 소스가 worker와 같았다.
- semantic digest와 route revision은 R30과 동일해 재승인하지 않았다. R30 PID9379를 종료했고 서비스 `AgentsMemoryMcpStable20261013R31` PID96967이 `/tmp`, `127.0.0.1:8768`에서 ready였다. doctor·stats exit0.
- 세 leader host owned uninstall→install 성공. 기본 operator credential의 최초 `AUTH_DENIED / not_started` 뒤 복원 후 operator token을 명시했다. 비소유 설정 비교 9개 모두 동일, MCP·hook·OMP extension이 새 package python을 참조한다.
- 현재 controller pane과 다른 프로젝트 OMP 4개를 유지했다. 새 leader OMP process와 Claude/Codex가 실제 `memory_context`·`memory_inspect`로 같은 synthetic claim을 읽었다. 첫 OMP/Codex 동시 recall의 `MODEL_BUSY` 증거를 보존했고 순차 smoke는 도구 오류 없이 성공했다.
- recall은 기존 failed6/DLQ6 때문에 `partial`이다. 후보의 원문 speaker는 `agent_note`, 승인 규칙은 없다. Codex permanent trust 변경·회사 enable·회사 native 무인 승인·배포·push·commit·AF guard 우회는 하지 않았다.
- 증거: `docs/research/2026-10-12-memory-skills/installed-leader-integration-r31.proof.json`; 상세 한계는 `docs/verification.ko.md`의 R31 절.
- 다음 작업은 회사 caller-grounded lexical/entity capability의 별도 공식 `development` run이다. 기존 queue 하나와 4 tools를 유지하고, 개인 full-semantic은 그대로 둔다.

## 같은 범위 복구 — development/20261013-221430

- 기존 run의 fresh 공식 native 리뷰 5차는 Codex의 독립 OS subprocess 6개 approve였고 당시 Claude probe는 unavailable이었다. 해당 결과와 round-2/3/4 수정 증거를 보존한다. 새 복구 run의 current native 리뷰는 Claude6/Codex6의 독립 subprocess **12개 모두 approve**이며 stale 결과는 쓰지 않았다. HEAD·index·commit·push·PR은 변경하지 않았다.
- round-4 fix-loop 검증은 ruff·pytest **1413 passed/skip 0**·uv build 통과였다. wheel SHA256 `e06b33eee23388069ece512652bb38850e94578de3cb96ac7ac76a129cfbe2f3`. 독립 synthetic DB의 실제 service/MCP에서 shape와 strict decoder의 일치·malformed variant 거절을 확인했고, 실제 CLI의 FIFO·oversize·symlink·nonprivate credential은 `CREDENTIAL_INVALID/not_started`였다. 앞선 spool/upgrade·window·규칙·relocate·purge/restore 증거는 verification에 보존했다. 이후 공식 QA 실패를 이 이전 통과 결과로 대체하지 않는다.
- PR #4 squash `33095d6`와 수정 commit `7512aa6`의 3-way working-tree 통합은 유지한다. HEAD와 index는 바꾸지 않았다.
- 기존 `development/20261013-103527`의 공식 QA는 1412 passed/1 failed 뒤 fix-loop 3회 제한으로 차단됐다. 실제 PG clock의 backward step2/max2.067403초와 원인 연결의 추론 한계는 verification에 보존했다. 사용자가 **동일 범위 복구 run**을 선택하여 기존 run은 공식 abort로 종료했고 모든 artifacts는 보존했다. 기존 counter·guard·pin은 바꾸지 않았다.
- 사용자 확정 결정은 [이슈 #5](https://github.com/chonamdoo/agents-memory/issues/5)와 [댓글 6150124320](https://github.com/chonamdoo/agents-memory/issues/5#issuecomment-6150124320) 하나로 관리한다. 삭제된 #1–#3을 새 작업 추적에 쓰지 않는다.
- 이번 run 범위·순서는 바꾸지 않는다. 이 구현을 회사 전용 lexical 기본 경로로 확정하지 않는다. 기억 판단은 사용 중 coding-agent LLM이 MCP로 제출하고 서버는 검증한다. 회사도 같은 경로이며 B·별도 회사 승인 절차는 폐기된 결정이다.
- 다음 별도 전환 run: 개인 capture의 `source_selection`, 로컬 Qwen 추출·consolidate·reflect 제거, coding-agent의 중복·지지·모순·대체 판단, 다음 호출로 넘기는 pending cleanup, 거부 이유의 다음 판단 입력과 새 근거 없는 동일 의미 재제안 차단, recall 질의 확장·관련성 판단, requirements·architecture·README의 개인/회사 공통 경로 갱신. lexical/entity는 후보 색인이며 기억 판단 기본값이 아니다. 메모리 건강도는 범위 밖이다.
- #5의 별도 미결 작업: 개인 failed6/DLQ6, digest/spool 전 단일 secret rejection과 gap quarantine, agent_note self-grounding 정책, PMPA·재진입·host 자체 기억 중복 시나리오, 시작 전 1–2주 trial 범위·성공 기준. 현재 run 완료 또는 이미 실행된 trial로 보고하지 않는다.
- 복구 run `development/20261013-221430`은 같은 작업 트리·branch·기능 범위를 유지하고 fixture 시간 준비만 수정했다. 업무 assertions·제품 scheduler/backoff는 그대로다. 집중 회귀8개, 실제 PG future/due/retry 불변 smoke, fresh native12개 approve, **공식 QA 3/3·1413 passed/skip0/190.79s**를 완료했고 runner가 handoff phase로 전환했다. 제품 Python/TS35개와 wheel은 기존 실제 service 검증본과 같다. `handoff.md`에 controller w18:p9 인계 내용·비차단 위험·#5 다음 범위를 기록했다. 최종 workflow 종료 상태는 canonical run report/status를 따른다. 게시·commit·push는 controller 소관이며 이 인계가 실제 회사 enablement나 다음 공통 LLM 전환 완료를 뜻하지 않는다.
