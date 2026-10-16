# 실제 로컬·클라우드 검증 기록

## 네 번째 리뷰 후 권한·복구와 PR 보안 수정 — development/20261016-110757

이전 run의 네 번째 genuine Opus5.5/Sol6.1 wave는12완료·3 approve/9 request-changes였다. 정상 fix-loop 한도에서 중단한 뒤 사용자가 **기록 보존 후 수정 계속**을 선택했다. 정상 abort/run으로 같은 worktree·branch에 새 run을 시작했으며 workflow/guard/pin/기존 판정은 수정하지 않았다. 아래는 새 controller 구현·실행 기록이지 fresh 공식 review/QA/handoff 승인이나 PR 원격 코드 갱신이 아니다. 아래 과거 절의 “현재”는 각 실행 시점이다.

source/test/pyproject/lock fingerprint는 `35d854f6a7d362d65316c9bc2aff66b38bdcb2881c2ff8aef55cd018b422daf0`이다. smoke wheel SHA256은 `5c0c838c6c74ea63da922908436f025a5b2b8824c8e3609602bbb138a31abb1b`이며 noneditable 설치의46 source 파일이 작업트리와 일치한다. README 순서 수정 뒤 재빌드와 OS network-deny sdist→wheel도 같은 wheel hash였다. source archive hash는 해당 실행 보고서에 별도 고정하며 최종 배포·승인과 구별한다.

| 수정 표면 | 실제 관측과 범위 |
|---|---|
| operator 철회·generation | 개인/회사 각각 실제 `judge_guard` 뒤 대기 중 Store에서 철회한 operator는 `AUTH_DENIED/not_started`, policy 변화 없음. 현재 operator는 allow 게시. authority/transaction mock 아님 |
| Jev fence·readiness | 실제 PG credential 발급 제약 오류 뒤 기존 worker 철회·선택 Jev·durable fence 보존. 실제 인증 launchd HTTP는200/db_ready=true이면서 `jev_unavailable_explicit_reselection_required`/inference unavailable. vendor 검증 callback은 합성이며 live API가 아님 |
| service·host 효과 | 수정 전 직접 호출에서 최초/재개 설치의 durable receipt/plist에도 not_started, legacy config code 유실, postcommit 진단 효과 유실을 재현. 수정 후 committed intent·unknown native completion, unknown 저장/host 효과, 원래 upgrade code를 확인. native 실패는 명시 fault 주입 |
| 실제 설치 운영 | 개인/회사에서4 MCP catalog·producer capture와 같은 key replay·source1/pending1, 실제 launchd SIGKILL 뒤 replacement PID/DB ready. 명시 stop은 유지되고 readiness는 `SERVICE_STOPPED/not_started`; 명시 start 뒤 queue 보존 |
| native 자손 | 실제 fork/FIFO의 부모 선종료·TERM 저항 자손을 process-group TERM/KILL·wait·pipe EOF까지 정리. 기존 실패 전 alive 관측과 새 설치본 실행을 구분 |
| 원격 recovery | 빈 spool probe 금지·실패 cycle backoff·취소 가능한 DNS/readiness·cycle deadline과 DNS 재사용·경쟁 flusher/동시 producer committed/unknown 회귀. 실제 TLS와 개인/회사 launchd client에서 각각 pending6→0·committed receipt6, 2.911/2.877초; 명시 stop2.101/2.116초 |
| PR #9 P1 | [리뷰](https://github.com/chonamdoo/agents-memory/pull/9#discussion_r4293624349) 수정 뒤 cloud-edge66 pass/14.17초. 별도 컨테이너의 실제 nonloopback TCP peer·유효 operator/raw-agent·두 local Host/일치 Origin 조합8개가 모두403/`HOST_ORIGIN_DENIED/not_started`. 실제 loopback bootstrap200·정상 Caddy 검증 HTTPS도 통과. insecure backend port는 외부 publish하지 않음 |
| PR #9 P2 | README의 configure→PC service install→host-install→doctor를 개인/회사 fresh private Mac client에서 실제 실행. enabled/running client·설치 receipt·DB ready와 bootstrap의 현재 role/generation/binding을 확인. doctor 자체는 readiness이며 authentication_checked=false; native trust 승인은 하지 않음 |
| 원격 MCP 범위 | 개인/회사 각각 legacy2025-11-25와 stateless2026-07-28의4도구·record/feedback 동일 operation replay·wrong binding/producer write/public operator 거절. 각 DB는 source8(인간 capture6+agent note2), claim0으로 **protocol 검증이지 모델 판단·기억 효익 증거가 아님** |
| 현재 offline consumer | macOS arm64·Python3.13.16/SQLite3.53.1. OS loopback 허용0/차단EPERM 대조, hash 필수 build9/runtime34의 index/cache 없는 새 환경 설치, sdist→같은 wheel·pip check·entrypoint·46 source 일치. 임시 환경/리스너 제거; 다른 ABI/whole offline 운영은 아님 |

첫 전체 시도는1 fail/1977 pass/327 error였다. fixture private0755와 PG tmpfs/OOMKilled를 확인해 제품 guard는 유지한 채 fixture0700·소유 named data volume으로 수정했다. 두 번째2293 pass/11 skip/545.29초는 중간 P1 source 변경 때문에 helper가 `complete=false`로 거절했고 최종 green으로 재사용하지 않았다. 세 번째 **정확한 `uv run pytest -q`:2311 pass/skip0/573.27초**, source identity 불변·600초 이내를 확인했다. 실제 age1.3.2·owned PG18.6 Docker tool prerequisite를 공급했으며 현재 Ruff·`uv build`·noneditable 설치46파일 일치도 통과했다. 공식 QA 승인을 대신하지 않는다.

Native smoke 소유 job/plist/schema/role·합성 state/key·자손과 cloud proof의 소유 container37/volume16/network2/image·native adapter/service·임시 실행 state를 제거했다. 부모 PG·공유 daemon·다섯 기존 미귀속 volume은 건드리지 않았다. cloud 증거는 direct Docker이며 Compose 실행·live Jev/모델·운영 노출/침해 조사가 아니다. fresh 독립 리뷰·공식 QA/handoff·새 publication은 아직 완료 주장하지 않는다. 실제 logout/reboot/sleep·stable cutover·native Codex/OMP strict 보호·human gold/paired trial·운영 cloud/외부 witness·법적/출시 승인은 원래 gate를 유지한다.

근거: 새 run `context/native-current-observed.json`, `integration-defect-{before,after}-observed.json`, `security-cloud-edge-checks-observed.json`, `security-cloud-observed.json`, `current-offline-observed.json`, `correction-attempt-{1,2,3}-checks-observed.json`, `correction-pg18-oom-observed.json`, `ops-runtime-prepared-observed.json`. cloud helper의 초기 build 실패·정확한 container-linked volume 정리는 `security-cloud-proof/attempt-1-build-failure.json`에 보존했다. [PR 답변](https://github.com/chonamdoo/agents-memory/pull/9#discussion_r4294511478)은 미게시 한계를 명시하며 thread를 resolve하지 않았다.


## 공식 리뷰 후 fix-loop — development/20261015-131245

같은 run의 두 번째 공식 review wave는10완료(approve4/request-changes6)·Claude types/I/O2timeout으로 **request-changes**였고, timeout을 승인으로 계산하지 않았다. 그 뒤 checkpoint `6a93cb5`를 Draft PR #9에 게시했다. 아래는 각 source의 실행 이력이며, 이전 source의 전체 pass나 checkpoint 게시를 후속 source의 공식 승인으로 사용하지 않는다.

### 세 번째 공식 리뷰 뒤 수정·설치된 경로 검증

세 번째 genuine Opus5.5/Sol6.1 공식 wave는 approve3/request-changes8/Claude I/O timeout1이었다. timeout은 승인으로 세지 않고 정상 fix-loop로 전환했다. 아래는 지적 해결 뒤 controller 직접 실행이며 다음 독립 리뷰·공식 QA/handoff 승인이 아니다.

현재 source/test/pyproject/lock fingerprint는 `72cdb9234276c2004a76a9f890c5cbe3d0a5617075dcd0d75eec488a7225cbb7`, 새 wheel SHA256은 `290b2d087dfcd94a5fab12ea2c4add17f1a9f0ae5e5c50c578efb142a31adaa8`이다. private Python3.13.16/SQLite3.53.1의 noneditable 설치와46 source 파일 일치를 확인했다.

| 지적 | 수정·실제 관측 |
|---|---|
| POST body 슬롯 무기한 점유 | 인증 뒤 전체 body에 서버 절대15초 deadline. 실제 launchd 서버의 stalled/slow-drip은 각각15.073/15.046초에408·`REQUEST_BODY_TIMEOUT/not_started`, incomplete HTTP/1 연결 종료·부분 source0. 회수 뒤 두 matched capture는202·실제 PG 저장 |
| Jev 교체의 묵시 agent fallback | 기존 선택을 보존하는 revision/credential fence. 실패·crash 시 구 worker의 retry/publication과 token 읽기를 차단하고 unavailable을 표시. 실제 PG binding-lookup 장애에서 Jev 선택 유지·구 토큰 인증 거절·명시 Jev 재선택 복구 확인 |
| Jev 부분 효과·미완료 폐기 | denial/선택의 durable 변경과 미확정 credential 폐기를 구분. 오류는 기존 code/status를 보존하고 committed 단계 또는 unknown·pending intent를 보고. 발급/폐기 응답 유실·게시 중단·worker backoff 회귀 통과 |
| service start/stop 효과 | intent 저장 뒤 native 실패는 `not_started`가 아님. durable intent는 committed, 저장 여부 미확정은 unknown. 실제 설치·SIGKILL 재시작·DB readiness·명시 stop 보존·명시 start 확인. native 오류 효과는 별도 fault 회귀로 확인 |
| 과거 Codex strict 실행 | 새 loader는 과거 strict receipt도 active 실행에서 거절. passive owned uninstall·명시 advisory 재설치는 회귀 통과. 이미 로드된 옛 binary의 무력화나 native 보호 성공을 주장하지 않음 |
| Claude 메모리 오진 | 진단 환경 `0`의 force-on과 `1`의 disable을 구별. settings `env`·불확정 상위 계층은 보수적 unknown. 실제 설치 CLI에서 false 설정+환경0을 enabled로 관측 |
| doctor·native 경계 | absent/denied/invalid egress이면 configured Jev와 effective agent를 구별. invalid project는 config/DB 전 거절. pending 설치 재개에도 공존 경고, receipt strict JSON/int UID, native 부작용 단정 대신 요청 범위 필드 |

집중831개 첫 실행은826 pass/5 fail이었다. 새 fixture의 private state0755와 capture의 agent credential 때문에 각각 정상 guard가 거절했다. 제품/guard/assertion을 완화하지 않고 private0700·producer 권한으로 수정한 뒤 해당5개가2.41초에 통과했다. 이를 단일831-pass나 전체 suite green으로 합치지 않는다. 수정 전 별도7개 회귀 실패도 보존했다. Ruff·sdist/wheel build·설치 byte 검증은 통과했다.

설치 smoke는48.58초에 완료했고 synthetic verify callback만 사용했다. 새 live Jev API·구독 모델 판단·native callback/행동 보호를 추가 검증한 실행이 아니다. 소유 launchd 서비스를 정상 uninstall하고 합성 schema·fixture를 제거했으며 PG stop 반환0을 확인했다. 원본 Jev 키·지속 native trust는 읽거나 변경하지 않았다.

별도 공개 artifact 검증도 보완했다. age1.3.2의 공식 SIGSUM 문서/공개 키와 `sigsum-generic-2025-1`, private sigsum-verify0.13.1로 OS network-deny positive 검증과 변조 입력 negative를 통과했다. Go module archive2개의 h1·license/NOTICE와 Go license를 보존했고 공개 bundle213개 checksum이 일치했다. 이는 out-of-band key identity·source/binary 재현성·법적 배포 승인이 아니다. 격리 Linux container에서 HOME 파일·Unix socket·loopback의 허용 대조/격리 거절, read-only filesystem·memory/CPU/PID/fsize 제한·자식 deadline/join도 관측했다. 전체 P3·native macOS 격리로 확대하지 않는다.

근거: 같은 run의 `context/third-review-{checks,recovered,smoke}-observed.json`, `third-review-red.txt`, `third-review-focused.txt`, `third-review-recovered.txt`, `remaining-{sigsum,containment,verifier-licenses}-observed.json`. 이번 Jev 구현 worker는 정상 bound status 후 코드·회귀를 작성했고 controller가 통합 검증했다. Edge worker는 lifecycle 경합 뒤 수정하지 않았으며 controller가 수행했다. 구현 worker를 공식 reviewer로 계산하지 않는다.

### 남은 작업 후속 — native 진단·실제 판단·오프라인 반입

2026-10-16 후속 작업의 source/test/pyproject/lock fingerprint는 `7aca16e02d553901e91b7a7f880c63a89f6b8ca541f68158fb0d3d47733f5543`다. 아래는 controller 직접 실행이며 fresh 공식 review/QA/handoff나 전체 #5 완료가 아니다. 후속 변경은 아직 checkpoint `6a93cb5`와 구분한다.

| 직접 실행 | 관측과 한계 |
|---|---|
| native memory·inventory 회귀 |29 pass. 설정 우선순위·미확정 상태·generation/use 구분·경로/파일 안전성·timeout/출력 상한·자식 종료. 사용자 설정/본문/auth는 변경·출력하지 않음 |
| 전체 profile 첫 실행 |1,954 pass/235 fail/1 error·529.44초. 저장소 내부 `--basetemp` 때문에 native private 설정의 project 격리 guard가 거절한 fixture 문제. 원래 로그 보존 |
| 실패 항목만 재검증 |동일 source/test bytes, 저장소 밖 임시 경로·일치하는 `VIRTUAL_ENV`로236 pass·21.64초. 제품 guard·assertion은 그대로. 이를 새 단일 전체2190-pass 실행으로 표현하지 않음 |
| lint·sdist/wheel |Ruff 통과, 실패 항목 검증 뒤 `uv build` 통과 |
| 실제 설치 Codex 진단 |새 noneditable wheel의 정상 app-server read-only 조회: project layer disabled/project hooks0, user4 enabled/trusted. 요청은 조회 범위이며 native 프로세스 전체의 부작용을 관측한 것은 아님. callback 미관측·행동 보호 미검증·strict 명시 미지원 |
| OS 네트워크 차단 설치 |공식 PBS Python3.13.16/SQLite3.53.1, hash 필수 build 도구9개·runtime34개. loopback 허용/차단 대조 후 새 환경에서 sdist/wheel 빌드·전체 local 설치·`pip check`·설치 CLI 성공.46 source 파일 일치, asyncpg wheel 누락은 offline 설치 거절 |
| 서버 image·암호화 도구 |online 준비한 새 Linux arm64 app image를 `--network none`/read-only/capability0에서 실행.46 source 일치·PG18.6 도구·age1.2.1 합성 왕복·CLI 확인. macOS age1.3.2도 OS 네트워크 차단 합성 암복호화 성공 |
| 안정 DB 현재 조회 |program-only private config/DSN과 read-only transaction: migration `0004_operation_successors`, failed6/DLQ6, retirement schema 없음. 현재 조회이지 실패 해결·migration·cutover 성공이 아님 |

당시 offline app wheel SHA256은 `3d1798b87222c9cf0fdbb70f851635810b58235bd1f90cfc835364b699071f8c`다. Python runtime/빌드 closure와 PG/vector·새 app image, age 공개 artifact를 반입 자료로 보존한다. 서버 image의 SQLite3.46.1은 **cloud server용이며 PC spool 지원 runtime이 아니다**. Docker/host 설치·인증, 전체 offline 운영, 다른 ABI, 독립 witness, license 재배포 승인은 별도다. 이7aca 실행 시점에는 Sigsum 검증을 하지 않았으며 위 후속 public-artifact 검증과 구별한다.

**실제 구독 판단 preflight:** 실행 전에 고정한 합성 입력 SHA256 `0962d639769d79844db422ab07b1c35ea535b816a23a60a7fdbe8eadfbb77dbd`, Jev deny/agent·키 없음·네 MCP 도구만 허용한 새 Claude Opus5.5 실행이다. P01 악성 tool 원문은 discard/active claim0, P02 정상 원문은 remember·19시간/audit 예외를 가진 source-linked claim1개 최종 context·독립 UTF-8 grounding 확인, R04 기존 discard의 번역/paraphrase 재유입은 discard/active claim0이었다. 각각43.815/85.827/62.829초. P02/R04에 MCP 오류가 각2회 있었고 최종 판단은 완료됐지만 세부 오류 code는 보존하지 않아 원인은 미확정이다. P02의 다른 active claim1개까지 의미 gold로 독립 판정한 것은 아니다. raw provider trace/body는 보존·게시하지 않았고 reported token과 billing unknown을 구분했다. 소유 서비스/schema/role/임시 native project를 제거하고 PG를 중지했다.

세 preflight는 전체 PMPA·모든 언어/host·후속 coding task·기억 효익의 증명이 아니다. native input 소비는 미관측이며 `comparison_valid=false`, benefit 미확립, elapsed trial 없음이다.120 holdout의 인간 gold/독립 검토,60 task×3 paired 평가·환경/비용/resource freeze, 정상 native 승인과 실제 OS/안정 배포 acceptance는 그대로 남긴다.

근거: 같은 run `context/remaining-{profile,failed,offline,image,pmpa}-observed.json`, `remaining-full-test.txt`, `remaining-failed-only.txt`, `remaining-stable-readonly-normalized-observed.json`, `remaining-release/`의 공개 dependency/이미지·license/hash inventory. 당시 구현 worker6개는 worktree guard 거절로 코드를 쓰지 않았고 bound controller가 통합했다. 이들을 공식 reviewer로 세지 않으며 이후 정상 unprefixed status가 불가능하다는 근거로 사용하지 않는다.

### 이슈 #5 후속 — 승인 없는 구현과 설치 소비자 검증

2026-10-16 사용자가 현재까지의 작업을 먼저 커밋·푸시·PR로 게시하도록 명시 승인했다. 이 snapshot은 PR #9의 Draft checkpoint이며 전체 #5 완료·공식 gate 승인·merge·출시와 구분한다. 아래의 미게시·정리 기록은 checkpoint 게시 전 실행 이력이다. 게시 범위 변경은 문서뿐이며 아래 검증 fingerprint의 Python/test/pyproject/lock bytes는 바꾸지 않는다.

현재 source/test/pyproject/lock fingerprint는 `744b84b1d7cbd6a885a7ed494c035081d90b19d97f3fbe99d093a0e187297f15`다. 아래 직전 source `ce8a4d99…38528`의2,164 pass를 새 source 전체 결과로 재사용하지 않는다. 새 wheel SHA256은 `d16b73fe4ffe25515dd21e9fa95b3fdc96b563b2765d512936fe3155b08ed73d`이며 native trust·권한·Jev egress 설정은 변경하지 않았다.

- 새 Codex `--strict` 설치는 `HOST_STRICT_UNSUPPORTED/not_started`로 거절한다. 설정 쓰기·advisory 자동 downgrade 전에 멈추며 기존 owned 정리·명시 advisory/MCP는 유지한다. 이는 Codex native 보호를 구현 완료로 바꾼 것이 아니다.
- 삭제 floor는 identity/lineage이며 content blacklist가 아님을 문서화했다. 같은 origin replay는 철회 상태, 같은 본문의 새 origin은 새 source·별도 판단, 판단 전 비노출, 판단 후 새 source/claim만 citation을 유지한다. 살아 있는 reject/discard의 독립 근거 guard는 그대로다. R05는 누락 비교/잘못된 reference/비독립 근거를 각각 기존 오류 계약과 맞췄다.
- [설치·업그레이드·장애 복구 runbook](release-runbook.ko.md)은 quiesce/drain 한계·encrypted final backup·독립 deletion head·migration/restore-recover·fresh credential·native 재등록/owned uninstall과 실패별 복구를 구분한다. 문서 작성은 실제 안정 cutover나 OS lifecycle의 완료 증거가 아니다.

| 새 candidate 직접 실행 | 관측 범위 |
|---|---|
| strict 거절의 failing-before 회귀 | 수정 전 새 설치·기존 advisory 두 경우 모두 예상 거절에 실패. 새 계약 회귀와 native 파일 보존을 추가 |
| 첫 관련 회귀 |476 pass/7 fail. 지원하지 않는 Codex strict fixture5개·oversized advisory 기대·crash 뒤 미지원 callback 기대를 구분해 수정. 기존 실패 로그 보존 |
| Ruff / sdist·wheel | 성공. package version만이 아니라 위 source fingerprint·wheel hash로 식별 |
| Python runtime closure | app+dependency34개. online 준비 뒤 새 consumer에 `--no-cache-dir --no-index`·local wheel만·모든 입력 hash 필수로 설치, `pip check` 성공. `python -I`에서 Python43파일 byte 일치 |
| SBOM/license | uv0.11.8 experimental CycloneDX1.5 lock graph와 실제 target35 distributions의 declared license·표준 license-file hash inventory. legal/redistribution 승인·전체 OS offline bundle 아님 |
| 설치된 CLI 거절·해제 | 신규·기존 advisory에서 `--strict` 요청 후 native/adapter 파일 불변. 명시 advisory 설치·실제 MCP 소비 뒤 owned uninstall, foreign MCP/hook 보존 |
| 실제 삭제·purge 재유입 | 설치된 Codex advisory stdio MCP→loopback HTTP→실제 PG. 두 경우 모두 기존 origin 비부활·옛 body 부재·새 origin 판단 전 비노출·새 source/claim만 최종 citation. 서버 task join·합성 schema/role/실행 폴더 제거 |
| 새 전체 첫 실행 |2,113 pass/48 fail·518.27초. 서비스/remote-control 설치에서 실행 파일 ancestry 검사가 `/opt/homebrew/Cellar`의0775를 거절했고 후속 receipt 준비도 실패. 이 결과를 green으로 사용하지 않음 |
| QA prerequisite 교정 | 이미 준비한 private regular interpreter·locked/hash-verified runtime/dev deps를 재사용. `python`/`python3` argv alias가 같은 실제 private binary와 prefix임을 확인했고 정상 executable ownership·isolated Python43파일 일치 통과. 실패 표면 service/remote-control69개는 `uv run pytest -q …`로69 pass·3.04초 |
| 최신 정확한 profile 명령 | **`uv run pytest -q`:2,161 passed·skip0·518.79초**. 같은 fingerprint·정상 PG/age/backup 환경·기존600초 timeout. controller 직접 실행이며 공식 QA phase 완료가 아님 |

소비 smoke의 최초2실패도 보존했다. 첫째는 동일 event loop에서 동기 CLI를 기다린 fixture가 HTTP 처리를 막았고, 둘째는 pinned MCP2.3 SDK의 Python 필드 `is_error` 대신 `isError`를 사용한 harness 오류였다. async thread handoff와 정확한 SDK 필드로 고쳤으며 제품 guard·서버 assertion을 완화하지 않았다. full-suite preflight의 bytes/string 비교 오류도 실제 테스트 시작 전 준비 오류로 구분한다.

근거: 같은 run의 `context/issue5-actionable-checks.txt`, `issue5-actionable-checks-observed.json`, `issue5-consumer-install-observed.json`, `issue5-consumer-offline-install.txt`, `issue5-installed-smoke{,-fixed,-third}-observed.json`, `issue5-full-checks-observed.json`, `issue5-private-qa-runtime-observed.json`, `issue5-private-focused-observed.json`, `issue5-private-full-observed.json`과 대응 로그다. `issue5-release-assets/`에는 runtime wheelhouse·lock SBOM·license inventory·compatibility manifest·41 artifact의 `SHA256SUMS`를 보존했다. 현재 소비 실행은 protocol 검증이며 새 구독 LLM 판단·PMPA 의미 품질·wire traffic0·Codex native 행동 차단 proof가 아니다.

native Codex의 정상 project/exact-hook 승인·실제 callback/행동 보호, fresh 공식 승인 review/QA/handoff, 안정 배포·실제 login/reboot/sleep·frozen 평가·1–2주 trial과 publication gate는 남아 있다. 이미 로드된 옛 strict hook을 새 설치 거절이 비활성화했다고 표현하지 않는다.

이번 임시 QA/runtime·합성 실행 폴더·빈 Docker config·알려진 baseline 임시 폴더를 제거하고 관련 process 잔여0을 관측했다. 소유 PG stopped와 원래 native service enabled=false/running=false를 확인했다. 이전 source의 최소 native 재검증 fixture·candidate artifact·공식 증거·user research는 유지했다. 실제 cleanup 근거는 `issue5-actionable-cleanup-observed.json`, 이슈 #5/PR #9의 소유 status·본문 PATCH 응답 검증은 `github-issue5-actionable-observed.json`이다. 임시 실행 스크립트는 기록 후 제거했으며 runtime commit/push·PR source 변경·merge는 하지 않았다.

### 직전 source의 재개·두 번째 리뷰 수정 — 2026-10-16

- guard·pin·approval을 변경하지 않고 설치형 canonical `status/continue`로 복구했다. 동일한 Python guide body의 추가 changed-path routing identity를 정직하게 적용 기록한 뒤 정상 review→fix-loop로 돌아왔다. 소유 TUI stdin 제어 거절은 우회하지 않았다.
- Jev의 실제 client 내부 HTTP 시도마다 현재 policy/provider revision을 검증한다. backoff 중 deny·재선택·policy revision 변경이면 다음 POST와 publication을 차단한다. key 검증의 실제 내부 재시도에도 같은 admission을 전달한다. 이미 admission된 in-flight 요청의 회수나 물리적 wire-level 원자성을 주장하지 않는다.
- durable denied policy를 재허용 전에 agent 전환·기존 credential 폐기로 완결한다. 새 credential 발급 전 private token intent를 저장하며 미확정 commit은 같은 PG clock lock 뒤 조회해 폐기 또는 이미 게시된 credential에만 채택한다. 손상 provider는 네트워크 검증 전에 명시 agent 복구를 요구한다.
- journal 검증은 Store 소유의 단일 live task를 공유한다. caller timeout은 그 작업을 취소·소유권 해제하지 않고, 종료 때 join한다. 완료된 결과를 무기한 cache하지 않으며 identity·DB 왕복·삭제 barrier를 유지한다.
- effective Jev 허가가 없으면 `describe`와 readiness는 agent 경로를 표시하고 configured provider를 구별한다. project add의 후속 Jev grant 오류는 binding commit을 `committed`로 보고한다. bootstrap의 credential 분리를 독립 principal이라고 표현하지 않는다.
- [원래 Shorts 설명·단독 분석·관측 한계](research/2026-10-16-shorts-lTja2ZxXYyI.ko.md)를 U23에 직접 연결했다. full playback·embedding 실측이나 자동 모델 대체를 주장하지 않는다.

| 두 번째 fix-loop 직접 실행 | 관측 |
|---|---|
| 집중 회귀 | 최초195 pass/1 fail(import 누락); 수정 후 해당1개 pass. 기존 실패 로그 보존 |
| Ruff / sdist·wheel | 모두 성공; source/test fingerprint `ce8a4d99…38528` |
| 새 checkout 밖 wheel | SHA256 `9efeaae02749a05caf55315655b9d948319eb9b506ea5373856070b4a5ff6809`;43개 Python file bytes 일치·noneditable·private interpreter trust 통과 |
| 실제 익명 HTTP readiness | 지연된 journal에8요청이503·검증 작업1개, health200 유지; 해제 후 DB/barrier readiness200 |
| 실제 합성 Jev | 프로그램만 키 입력·0600 사본·remember와 active claim 확인; 원본 metadata 유지, 뒤에 deny+agent·키/미완료 발급 사본 제거·native service disabled/stopped |
| 새 전체 pytest 첫 실행 이력 | 2,116 pass/48 fail·517.46초. Homebrew symlink interpreter가 정상 executable ownership 검사에서 거절된 service/remote-control 사례와 후속 실패. 제품 guard·테스트·Homebrew 권한은 바꾸지 않았다 |
| QA prerequisite 수정 | private copied Python3.13.16/SQLite3.54.0·lock export+hash 검증 의존성. 기존 실패 표면69개 통과. `uv run`의 환경 재생성을 막는 정상 `UV_NO_SYNC=1`과 호환 version request3.13으로 같은 interpreter를 재사용 |
| 다음 전체 실행 이력 | 2,163 pass/1 fail·522.02초. `PYTHONPATH`를 물려받지 않는 MCP 자식의 project 설치 누락이었다. current project editable 설치·isolated import 확인 후 해당 실제 MCP 회귀1개 통과 |
| 최신 정확한 profile 명령 | **`uv run pytest -q`:2,164 passed·skip0·518.43초**. 같은 fingerprint `ce8a4d99…38528`, 전체 실제 PG/age/backup 환경·기존600초 timeout. Ruff/build도 같은 source에서 통과. 공식 QA phase 완료가 아니라 controller 직접 실행 |
| 새 wheel의 실제 구독 MCP | Jev deny/agent·키 없음에서 Claude Opus5.5·Codex6.1Sol·OMP openai-codex6.1Sol 각각 실제 원문 판단·active claim·전체 relevance·같은 claim과19시간/audit 예외 최종 context 확인. native strict 보호나 새로운 wire/preconnect0 관측으로 확대하지 않음 |
| Codex 정상 hooks/list·승인 후 진단 | 실제 binary `--version`은0.162.1. 사용자 승인 통지 직후에도 user source4개·project source0개였다. 정상 `config/read(includeLayers=true)`는 검증 폴더의 project `.codex` layer를 trusted-project 미등록 사유로 disabled 처리한다고 명시했다. 이는 이번 미발견 이유이며 과거 patch 실패 전체 원인으로 확대하지 않는다. 정상 `Folder access`→`Trust and continue`와 이후 project exact-hook 검토가 필요하며 trust/API state write는 하지 않았다 |

근거는 같은 run의 `review.md`와 per-angle 원본, `resume-r2-{focused,cli-fixed,lint-fixed,build,full-test,copied-native,copied-full,profile-isolated,profile-full}.*`, `resume-r2-profile-qa-observed.json`, `resume-r2-runtime-install-observed.json`, `resume-r2-runtime-smoke-observed.json`, `resume-r2-subscriber-{claude,codex,omp}-observed.json`, `resume-codex-hook-status-actual-authority.json`이다. 초기 실패·중간 보완 실행은 삭제하거나 최종 성공으로 바꾸지 않았다. 제어 세션의 구현 조사 subagent들은 worktree 쓰기 guard에 거절되어 코드를 변경하지 않았고 공식 reviewer로 대체하지 않았다. 실제 수정은 binding된 controller가 수행했다.
승인 통지 후 정상 native 조회의 추가 근거는 `resume-codex-hook-status-post-user-approval.json`과 `approved-codex-config-metadata.json`이다. 후자는 config 값 전체가 아니라 layer 종류·disabled reason 등 allowlisted metadata만 보존한다.

**폰 사용에 따른 신뢰 조사:** [OSS/native trust 비교](research/2026-10-16-oss-native-trust.ko.md)에 claude-mem·참고 OSS와 Codex0.162.1의 실제 TUI 저장 경로를 정리했다. native TUI도 공개 `config/batchWrite`를 사용하므로 “TUI 외에는 기술적으로 불가능”이라고 단정하지 않는다. 이는 지속 보안 설정 변경이지 전용 consent-attesting API가 아니며 이번에는 호출하지 않았다. 이번 `claude --version`은2.1.300이었고, 이전 native 행동 smoke를 새 버전의 통과로 확대하지 않는다. source 조사·버전 조회만 추가했으며 native 보호 실패·서비스 paused 상태·publication gate는 그대로다.

이번 재개 검증 뒤 임시 subscriber native 등록3개·credential6개를 정상 철회하고 private project/원본 trace를 제거했다. subscriber CWD process0과 QA CWD process0을 관측했으며 private QA env/cache/실패 준비 상태도 제거했다. owned authority는 disabled/stopped, label을 확인한 PG container도 stopped다. 정상 Codex project/exact-hook 승인·재검증용 최소 private fixture와 중지 DB만 보존했으며 전체 철거·workflow 완료로 표현하지 않는다. 근거는 `resume-r2-subscriber-retirement-observed.json`과 `resume-r2-pause-cleanup-observed.json`이다. 과거 consumer report의 process-group join field는 CLI root wait/termination 기록 범위였고, 별도 cleanup 관측보다 넓은 보장으로 사용하지 않는다.

### 첫 fix-loop의 수정·실행 — 후속 수정 전 이력

이하2,143 pass·개인/회사 TLS·세 구독 모델의 결과는 첫 fix-loop 당시 source에 대한 실행 이력이다. 위 두 번째 수정 source의 동일 전 구간 재실행이나 공식 QA 승인으로 확대하지 않는다.

- HTTP는 DNS·connect·TLS·send·status/header/body·chunk/trailer 전체에 절대 deadline을 적용한다. hostname resolver는 timeout 때 종료·회수하는 격리 프로세스다. mutation은 dispatch 전 `not_started`, 이후 `unknown`이며 unknown을 재전송하지 않는다.
- 원격 recovery 한 cycle은 준비 확인과 모든 row가 공유하는20초 budget을 사용한다. spool은 별도 private flush lock으로 전송 소유자를 하나로 제한하며 enqueue·TTL·상한 계약은 유지한다.
- launchd install/remove intent를 native side effect 전에 durable 저장한다. install 중단 후 명시 stop·재설치가 disabled를 뒤집지 않으며, plist 제거 뒤 중단된 uninstall도 같은 owned 범위로 재개한다.
- Jev vendor 검증은 lock 밖에서 하고 publish 전 정책/provider revision을 다시 확인한다. deny·agent 전환·retirement intent와 실제 record commit은 cross-process guard로 직렬화한다. revoke 실패/응답 유실 때 retirement intent를 남겨 재시도하며 allow가 예전 provider를 되살리지 않는다.
- remote profile 실패 때 새로 생성한 owned CA만 rollback한다. bootstrap의 identity/realm/mode/role/binding/revision/credential 경계, 공개 ingress의 operator 거절, business route의 인증 전 비싼 journal sweep 제거, Unix socket 대소문자 보존을 검증했다. 익명 readiness의 검증 누적은 위 후속 수정에서 별도로 해결했다.
- Codex lifecycle 중 context를 출력하지 않는 PreCompact/PostCompact에는 `additionalContextLimit`을 설정하지 않는다. 이 metadata 수정은 아래 Codex native 행동 보호를 입증하지 않는다.

| 최종 직접 실행 | 관측 |
|---|---|
| Ruff / sdist·wheel build | 모두 성공 |
| 전체 pytest | 2,143 passed / skipped0 / 511.34초; 실제 PG·backup 도구 환경 |
| 실제 HTTP/검증 TLS slow-drip | status/header/chunk-size/trailer × readiness/mutation16경우 통과. budget0.25초, 최대0.2531초. dispatch 전 business POST0, 이후 정확히1회·unknown |
| 실제 launchd crash intent | install receipt 후 plist 전 crash97, plist unlink 후 receipt 전 crash98; 정상 명령으로 재개·멱등 uninstall·명시 중지 보존 |
| 실제 launchd SIGKILL | 새 PID와 DB readiness 회복; 명시 stop은 자동 재기동하지 않음 |
| 새 개인/회사 cloud package | 각43개 Python source bytes 일치, 실제 PG18.6/vector0.8.7/SCRAM·MixedCase Unix socket·private-CA HTTPS |
| 독립 app/proxy crash | app SIGKILL 뒤 HTTPS+DB1.75초 회복; app restart1/proxy restart0. 명시 stop12초 유지 후 명시 up 회복 |
| checkout 밖 noneditable wheel | 새 venv·SQLite3.53.1,34 module·8 migration 일치; SDK4도구와 실제 HTTPS/PG claim·전체 relevance·같은 claim/19시간 규칙/audit 예외 최종 read |

최종 설치 wheel SHA256은 `c6e5778fe6e2d46e52b9ee4fa7d336c3854657d74a8df690c5de201c1b27cbb1`이다. SDK smoke는 실제 모델의 독립 판단 증거가 아니다. wheel PC의 실제 client LaunchAgent stop·missing-CA offline owned uninstall·credential revoke와 private PC 제거도 확인했다. 외부 cloud 계정 provisioning, proxy 자체 crash, 실제 OS login/reboot를 실행한 것은 아니다.

### 비공개 키와 실제 구독 모델

- Downloads 원본 키는 프로그램의 `--key-file`만 읽었다. 새 합성-only fixture에서0600 사본·실제 Jev remember·active claim을 다시 확인했다. 원본 metadata는 유지했고 검증 후 deny+agent·서비스 사본 삭제를 확인했다. 실제 corpus egress나 안정 운영 Jev 활성화가 아니다.
- 최종 source로 실제 구독 Claude Opus5.5·Codex gpt-6.1-sol·OMP openai-codex/gpt-6.1-sol을 각각 실행했다. 셋 모두 deny/agent에서 원문 전체 inspect→독립 remember/extraction→active claim→전체 candidate relevance→**같은 claim과19시간 규칙/audit 예외가 포함된 최종 context**를 확인했다. 최종 실행에는 audit observer가 없으므로 pre-connect 호출0·TCP counter0을 새로 주장하지 않는다.

### native 행동 보호: 성공과 실패를 분리

- Claude의 실제 `Read`는 healthy·명시 stop·명시 start 후 회복 세 경우 모두 native `PreToolUse:Read` callback과 무부작용을 관측했다. 정상/회복은 `HOST_PROVIDER_INPUT_UNOBSERVABLE`, 중지는 `SERVICE_STOPPED`로 거절했다. 최초 Write-only 시도는 prior Read 필요 조건 때문에 callback 전 실패했으므로 보호 성공에서 제외했다. provider input 소비나 모든 host tool을 보장하지 않는다.
- **Codex0.162.1 strict native 보호는 미완료다.** 최종 hook 정의를 정상 재설치하고, trust bypass 없이 `workspace-write`에서 유효한 단일 Update File hunk를 실행했으나 실제 `file_change`와 합성 파일 변경이 발생했다. 증거 기록 후 owned sentinel만 원복했다. 이전 invalid-patch 실패를 차단 성공으로 간주하지 않는다. native hook 활성·해시 신뢰·실제 callback 경로 확인이 필요하며 원인을 신뢰 문제 하나로 단정하지 않는다. 구독 MCP 성공은 이 보호의 증거가 아니다.
- installer는 native trust를 위조하지 않는다. OMP strict는 계속 `HOST_STRICT_UNSUPPORTED`; advisory/MCP만 지원한다. 훅이 실제로 로드·승인·실행되지 않은 세션에서 서비스가 host의 직접 파일 변경을 막는다고 주장하지 않는다.

### 남은 gate와 실행 제약

Codex native 첫 행동·중지·복구 보호, 후속 수정 source의 승인 재리뷰/공식 QA/handoff, 전체 #5 평가·운영 acceptance, 실제1–2주 paired trial, 안정 서비스 cutover, 외부 cloud provisioning과 commit/push/PR runtime 게시가 남았다. canonical launcher의 과거 거절은 정상 진입 복구로 해소됐지만 native trust/소유 TUI 입력 거절은 우회하지 않았다. 현재 공식 phase는 두 번째 fix-loop이며 완료/승인으로 표현하지 않는다.

body-free 실행 근거는 같은 run context의 `fix-loop-final-{lint,test,build}-observed.txt`, `fix-loop-http-observed.json`, `fix-loop-runtime-observed.json`, `fix-loop-cloud-observed.json`, `fix-loop-wheel-observed.json`, `fix-loop-native-{claude,codex,omp}-observed.json`이다. 키·token·DSN·비공개 manifest·원본 native trace는 공개하지 않는다. 아래는 각각 당시 실행 이력으로 보존한다.

검증 후 `fix-loop-retirement-observed.json`의 complete:true를 확인했다. owned native entry5개·서비스·정확한 합성 schema/role, 개인/회사 Compose와 QA를 포함한 owned container7개·VM 비밀/data root·비공개 key/trace/QA 상태를 정리했다. 무관한 container2개의 ID·running 상태·시작 시각은 그대로였고 기본 Docker context와 global auth/trust는 바꾸지 않았다. Downloads 원본과 의존성 Python/venv/cache는 보존했다. 재개 때는 정상 준비로 새 owned fixture가 필요하며 삭제된 locator나 옛 trace를 현재 실행으로 재사용하지 않는다.

후속 최종 정리 지시에 따라 `final-owned-temp-cleanup-observed.json`으로 지원 Python/venv/uv-cache와 실패 cloud harness의 partial manifest를 포함한 private 임시 root까지 제거했다. Root 경로/소유 CWD에 남은 프로세스0·owned runtime container0을 관측했다. `final-proof-image-retirement-observed.json`은 사용 중인 소비자가 없는 정확한 proof tag2개 제거를 기록한다. shared base image/builder cache·사용자 서비스·LSP mux·공식 run 증거·사용자 research는 보존했다. 위 의존성 보존은 첫 retirement 당시 기록이며 최종 상태는 private 임시 root 삭제다. 새 검증에는 지원 런타임과 fixture의 정상 재준비가 필요하다.

## PR #9 후속 원격 구현 — development/20261015-131245

이 절은 새 default-deny 정책과 원격 구현의 **작업트리 구현-phase 실행 기록**이다. 기록 시점 PR #9 remote는 문서·이미지8개뿐이며 runtime은 commit/push되지 않았다. 당시 공식 Agent Flow는 `implement`로, 아래 smoke는 fresh 공식 review·QA·handoff나 전체 #5 acceptance가 아니다. 이후 공식 결과는 해당 run report·정본 이슈에서 확인한다. 아래 이전 절의 key 부재/cloud 미구현 등은 각 당시 이력이며 이 절이 관측한 범위만 갱신한다.

### 비밀 입력과 판단 경로

- Downloads의 사용자 키 파일은 assistant가 열지 않고 실제 CLI의 `--key-file` 입력으로만 전달했다. 프로그램이 인증에 사용하고 0600 비공개 사본을 만들었다. 원본 메타데이터는 유지됐고 키 값은 채팅·Git·이슈·PR·body-free 증거에 싣지 않았다.
- 개인/회사 각각 로컬 및 실제 private-CA HTTPS fixture에서 `allow`와 명시 `jev` 선택 뒤 실제 `jev-1.13.0` 응답·remember·정확한 원문 span·active claim·동일 claim 재조회를 확인했다. 합성 데이터만 사용했으며 회사 이름이나 키 보유를 실제 회사 corpus 전송 승인으로 해석하지 않았다.
- Jev 실패는 provider를 바꾸지 않고 pending이다. owned cloud worker의 실제 TCP443 차단에서 `JEV_UNAVAILABLE`·같은 pending·agent fallback 없음·claim 없음, 정확한 차단 규칙 제거 뒤 새 capture 없이 처리를 관측했다. 키 사본 부재에 의한 `JUDGE_KEY_REQUIRED`는 별도 credential 장애이며 API outage로 표현하지 않는다.
- 개인/회사 모두 **실제 launchd의 선택 Jev 상태**에서 SIGKILL→새 PID·DB readiness·같은 pending/provider 보존, credential 복구 뒤 실제 Jev claim을 확인했다. explicit stop은 client 접근/install replay에도 disabled/unloaded를 유지했다. installed adapter에 typed capture를 enqueue한 뒤 explicit start만으로 outbox pending1→0·source/capture operation 정확히1개·Jev claim이 생성됐다. 새 host event·manual flush·실제 OS login을 주장하지 않는다. 마지막은 agent/deny·ready, 원본 metadata 유지·0600 사본·임시 key hold 없음이다.

### 실제 구독 coding-agent → MCP → 독립 판단 → 다음 read

아래 각 행은 새 합성 원문을 실제 모델이 전체 inspect하고, 엄격한 `a0000` assertion/individual qualification 계약으로 remember와 extraction을 원자 제출한 뒤, 전체 candidate manifest의 relevance와 **그 claim이 들어 있는 최종 `context` 문자열**까지 확인한 경우다. nineteen-hour scratch-cache 규칙과 audit-record 예외를 함께 보존했다. 고정 SDK 응답·note 저장·`memories` preview만으로 성공 처리하지 않았다.

| 배포 | 운영 주체 | Jev 정책 / provider | 실제 native 소비자 | 결과 |
|---|---|---|---|---|
| 로컬 | 개인 | deny / agent | Codex · gpt-6.1-sol | 원문 연결 active claim·전체 relevance·동일 claim 최종 read |
| 로컬 | 개인 | allow·미선택 / agent | OMP · openai-codex/gpt-6.1-sol | 같은 경로·조건과 예외 보존 |
| 로컬 | 회사 | deny / agent | Claude Code · claude-opus-5-5 | 같은 경로·조건과 예외 보존 |
| 로컬 | 회사 | allow·미선택 / agent | Codex · gpt-6.1-sol | 같은 경로·조건과 예외 보존 |
| 클라우드 | 개인 | deny / agent | OMP · openai-codex/gpt-6.1-sol | private-bridge HTTPS에서 같은 경로 |
| 클라우드 | 개인 | allow·미선택 / agent | Claude Code · claude-opus-5-5 | private-bridge HTTPS에서 같은 경로 |
| 클라우드 | 회사 | deny / agent | Codex · gpt-6.1-sol | 기존 socket/private-CA HTTPS fixture에서 같은 경로 |
| 클라우드 | 회사 | allow·미선택 / agent | OMP · openai-codex/gpt-6.1-sol | 기존 socket/private-CA HTTPS fixture에서 같은 경로 |

- 로컬 네 행은 서버의 body-free `urllib.Request` 관측기에서 Jev 요청 시도 증가 0이다. allow·미선택 두 행은 같은 backend PID의 실제 Jev 선택으로 관측기를 양성 보정했다. deny의 이전 PID까지 후속 양성 보정이 적용됐다고 확대하지 않는다.
- 원격 네 행은 해당 app namespace의 양성 보정된 외부 TCP443 packet 증가 0이다. 개인/회사 실제 Jev 선택의 양성 대조는 각각35/37 packet이었다. 이는 실제 외부 API 트래픽 관측이며 **connect 이전 Python 함수 호출 시도 0의 증거는 아니다.** 회사 보고서의 더 강한 내부 invocation acceptance 미충족을 숨기지 않는다.
- 개인 클라우드 두 모델의 첫 `CAUSAL_NOT_READY` 각2건과 Codex의 잘못된 초기 assertion/qualification, Claude의 이전 custom-config hook 실패를 보존했다. DTO를 느슨하게 하지 않고 도구 설명·실제 생성 command·증거 parser를 고쳤다.
- 실제 OMP18.11.1은 advisory 경로이며 strict 보호 지원으로 승격하지 않았다. `HOST_STRICT_UNSUPPORTED` 거절을 확인했다. 이 표는 정해진 합성 흐름의 기능 증거이지 일반 기억 정확도·memory-off 대비 효익·모든 native tool 지원의 증거가 아니다.

### 원격 배포와 실제 장애에서 드러난 수정

- `RemoteClientSettings`는 HTTPS·deployment/realm·agent/producer token과 승인 binding만 가진다. PC에 DSN/operator를 복사하지 않는다. 한 binding bootstrap, 현재 PG credential/generation·role/grant 검사, 잘못된 binding·operator·cross-deployment 거절을 실제로 실행했다.
- 실제 ES256 OAuth JWT의 issuer/audience/scope/subject 검증과 credential generation 폐기 뒤 기존 JWT·MCP session의401을 확인했다. 공개키·issuer/audience는 고정 설정이며 IdP provisioning·discovery·JWKS 자동 갱신을 구현했다고 하지 않는다.
- 최초 Unix-socket package의 SQLAlchemy migration이 percent-encoded hostname을 DNS 이름으로 써 양 mode에서 실패했다. Unix hostname decode 후 **원래 같은 init intent의 `init --resume`**가 양쪽 committed가 됐다. 일반 Store·operator DSN 제한을 풀거나 TCP relay로 우회하지 않았다.
- 최초 shared network namespace 구성은 app SIGKILL 뒤 app/DB readiness가 회복돼도 Caddy HTTPS가100.51초 동안 회복되지 않았다. 이 실패를 보존하고 독립 Caddy/app namespace·전용 private bridge·고정된 정확한 proxy peer IP·외부 비공개 backend로 전환했다.
- 새 실제 Compose package에서 개인/회사 모두 인증·TLS·DB·capture·MCP 경계를 통과했다. app SIGKILL 뒤 자동 engine restart1회와 HTTPS/DB 회복1.69초, Caddy의 수동 재시작 없음·restart0을 관측했다. 명시 Compose stop 뒤12초간 두 컨테이너가 중지 상태를 유지했고 명시 up 뒤 회복했다. Caddy 자체 crash·OS reboot·실제 외부 cloud account는 이 실행에 포함하지 않았다.
- Caddy에 app state·journal·PG socket을 mount하지 않았고 app port publication도 없다. 기존 PostgreSQL18 SCRAM Unix socket만 연결했으며 새 DB provisioning·임의 remote DSN 지원을 추가하지 않았다. 이미지 tag/version 고정과 실제 image ID 기록을 immutable `FROM` digest 고정으로 표현하지 않는다.
- 원격 PC launchd가 깨끗한 환경에서 frozen Claude config 경로 대신 현재 환경 경로를 참조해 pending이60초 넘게 남는 실패를 재현했다. receipt의 고정 경로·소유권 lock을 사용하도록 수정한 같은 실제 시나리오가14.85초에 완료됐다. 새 host event나 수동 flush 없이 pending0, client SIGKILL 뒤 새 PID, durable stop·설치 replay·offline owned uninstall·외부 MCP 보존을 확인했다.
- 실제 stop 직후 start는 이전 job이 아직 loaded여서 enabled지만 실행되지 않는 race가 있었다. stop이 최대30초 동안 native unload 부재를 확인한 뒤 반환하도록 고쳤다. 서비스 회귀31개와 양 mode의 실제 stop→즉시 start를 통과했다. provider 외부 요청의 완료를 native unload와 동일시하지 않는다.
- SQLite3.50.4의 기존 WAL 생성/쓰기 baseline을 보존했다. 수정 후 영향 버전은 디렉터리 생성 전 거절하며 실제 private Python3.13.16/SQLite3.53.1에서 durable enqueue·재열기·전송을 확인했다. Homebrew writable ancestry나 전역 파일 권한을 바꿔 trusted-chain 검사를 우회하지 않았다.

### 원격 정정·철회·암호화 복원과 다음 HTTPS read

- 개인/회사 각각 현재 bridge image의 실제 PostgreSQL18에서 새 원문·조건/예외가 연결된 claim을 만들고, producer의 `/api/correct`로 진짜 replacement를 생성했다. 다음 verified HTTPS consumer read는 새 claim/수정한 시간·기존 예외를 제공하고 옛 claim을 제공하지 않았다. 회사의 agent-role correction403, 개인의 stale admission409·잘못된 retraction 권한 거절도 확인했다.
- 실제 operator CLI의 PostgreSQL18 `pg_dump`→`age` encrypted archive를 만들었다. journal은 archive에 포함하지 않았고 plaintext dump를 영속화하지 않았다. backup 후 operator retract(회사에서는 purge도 실행)로 **archive 밖 살아 있는 삭제 head**를 전진시켰다.
- 개인의 옛 head를 제시한 restore는 `DELETION_BARRIER`로 시작 전 거절됐다. 양 mode에서 실제 archive를 명시 restore하고 살아 있는 최신 삭제 floor를 재적용했다. `tokens_rotated`, `rules_need_reapproval`, `routes_disabled`, jobs fence와 옛 승인 비활성 계약을 유지했다. recovery-only를 archive 적용 증거로 대체하지 않았다.
- 새 credential의 다음 **verified HTTPS** read와 exact handle 조회에서 옛/수정 source·claim 본문이 부활하지 않았다. 개인의 stale agent401, 회사의 stale operator `AUTH_DENIED`를 관측했다. 회사의 stale-agent HTTP 검사는 driver 재시작 때 기존 bearer를 잃어 미관측이며 다른 성공으로 채우지 않았다. 회사의 exact normalized deleted origin replay는 기존 `retracted` operation을 반환했다.
- 이 판단은 deterministic API/DTO smoke다. native LLM·공식 SDK 판단으로 표현하지 않는다. 최신 head도 operator가 archive 밖에 보존한 값이지 외부 witness의 독립 attestation이 아니다. 삭제를 WAL/media/provider/옛 archive forensic erasure로 일반화하지 않는다.
- 회사는 default fixture credential만 정상 회전해 HTTPS/DB-ready·agent/deny로 복귀했다. 최종 query는 무관한 archived blocked1 때문에 **partial**이고, 이번 두 source의 active pending은0이다. 무관한 작업을 재승인·해결한 척하지 않았다.
- 개인은 위 semantic/restore acceptance 후 cleanup driver가 binding에 grant된 credential을 넓게 골라 마지막 복원 operator를 스스로 폐기했다. 원래 report의 `complete:false`와 실패 이력을 보존한다. 부모는 인증 우회·operator 재활성화·auth row SQL 수정 대신 **해당 owned 합성 배포를 정상 철거**했다. app/proxy·소유 network/volume·전용 schema/role·남은 token hash·비공개 state를 제거했고 회사 app/검증 HTTPS/DB와 shared PG가 그대로임을 확인했다. 이를 제품 operator 복구 성공으로 부르지 않는다.
- 생성한 age key/archive·임시 credential은 제거했다. 증거는 `cloud-personal-maintenance-observed.json`, `cloud-company-maintenance-observed.json`, `cloud-personal-retirement-observed.json`이다. source/runtime 수정을 추가로 요구한 제품 결함은 관측하지 않았다.

### 통합 gate와 checkout 밖 설치 소비자

| 실행 | 실제 결과 | 적용 범위 |
|---|---|---|
| 통합 `pytest -q` | 2017 passed /1 failed /11 skipped, 499.94s | 마지막 missing-cwd 분류 수정 이전. 전체 green 아님 |
| 실패 node만 재검사 | 1 passed /4 deselected, 0.27s | `FileNotFoundError`를 `HOST_SCOPE_UNRESOLVED`로 분류한 이후. ELOOP는 기존 generic denial 유지 |
| lint | `All checks passed!` | 마지막 missing-cwd exception 분류 수정 직전 snapshot |
| build | sdist/wheel 생성 성공 | 위 분류 수정 이후 snapshot |

11 skip은 기존 backup/restore의 명시 age/pg_dump binary 환경변수 미설정 경로다. 통과한2017개를 다시 실행한 것처럼 합산하거나 fresh 공식 QA3/3으로 표시하지 않는다.

- 실제 설치 wheel SHA-256: `f3a6e507fa61c55a4037ecc643634d0ede424fed142890fb9daf4b6aecea2992`. 새 비editable private venv·checkout 밖 cwd·`PYTHONPATH` 없이 전체 Python module34개와 migration8개가 current source bytes와 일치했다. 요청한8개 module의 설치 위치·hash도 확인했다.
- 설치된 CLI의 private-CA HTTPS·DB identity·distinct agent/producer bootstrap, 생성된 `/usr/bin/env` wrapper가 **설치 venv Python**을 실행하는 host-stdio와 공식 MCP SDK2.3의4 tools를 실행했다. full source→atomic extraction→전체 relevance→동일 claim/예외 최종 context와 실제 PG active claim을 확인했다. 이 SDK 판단은 deterministic smoke이며 위 native 모델 증거와 구분한다.
- 설치 package의 실제 macOS LaunchAgent install/run/stop, stop 후3초 unloaded·`SERVICE_STOPPED`, CA 부재에서 offline host/service uninstall·foreign entry/hook 보존을 확인했다. owned credentials는 폐기했다.
- 첫 offline dependency 설치는 `mcp==2.3.0` cache 부재로 실패했고 online 설치로 성공했다. 이 실행을 전체 offline 설치 준비 완료라고 하지 않는다. editable 탐지·SDK2 속성 등 harness 실패도 보고서에 보존했다.

### 구조도 산출물과 실제 정적 표면

- `docs/images/architecture-cloud.architecture.json`의 고정 spec과 실제 HTML render는 Archify showcase9/9·오류0·경고0을 통과했다. spec SHA-256은 `20876519727f227d9088b96eaefe99f4909fe880cd85147a14efb8e6a6b2cf19`, HTML은 `70c33320d717877136acc0f05f48f51124572b7783c79e530928031a400d17fd`다. JSON을 함께 보존해 SVG/PNG의 편집 정본을 잃지 않는다.
- 전달된 SVG를 HTMLParser로 추출하고 AST-selected CSS·동일 geometry로 정적 export했다. SVG `xmllint --noout` 성공, 실제2776×2196 dark/light PNG를 열어 한국어·조건·화살표/label·외부 vendor 경계를 확인했다. 자동9체크가 놓친 vendor/region 겹침과 label/rail 간섭을 실제 이미지에서 발견해 후보를 수정·재검증·재전달했다. 집중 시각 보정2회 후 정적 SVG 표면을 통과했다.
- 이전 browser-task 차단을 우회하지 않았다. `visual-check` receipt·HTML Viewer viewport containment·UI 조작 증거는 **없으며 정적 이미지로 대체 주장하지 않는다.** authored 내용은 한국어, 고정 범례/Viewer UI·`lang`은 도구의 English fallback이다. 기존 로컬 그림은 두 독립 판단 경로와 lifecycle 계약이 그대로여서 이 후속 원격 변경에서 의도적으로 유지했다.

### 증거와 아직 주장하지 않는 범위

body-free 기록은 해당 run의 `context/`에 보존한다: `local-jev-proof-observed.json`, 두 `local-*-allowed-observed.json`, 두 local deny final-recall JSON, `cloud-jev-proof-report.json`, `cloud-company-native-observed.json`, `cloud-personal-native-observed.json`, `cloud-socket-package-report.json`, `cloud-bridge-package-observed.json`, `cloud-client-recovery-observed.json`, `cloud-wheel-consumer-observed.json`, `profile-*-observed.txt`. 비밀 manifest·원본 key·raw native trace는 공개 근거가 아니다.

선택 Jev의 provider 공통 native 운영 증거는 `local-personal-jev-lifecycle-observed.json`·`local-company-jev-lifecycle-observed.json`이며 양쪽 `passed:true`다. 현재 공개 실행 정본은 [이슈 #5 후속 실행 댓글](https://github.com/chonamdoo/agents-memory/issues/5#issuecomment-6199387466)이다. 원격 maintenance의 개인 driver cleanup 실패와 부모의 정상 owned-fixture 철거는 위 별도 절에 보존한다.

이 구현-phase 기록 시점 fresh 공식 Opus/Sol review·QA·handoff, 실제 logout/login·reboot·sleep, stable 운영 DB/host cutover와 과거 live failed/DLQ 현재 상태, 전체 #5 평가/운영 acceptance, 실제1–2주 paired trial, 운영 cloud provisioning/실제 corpus 저장·전송 승인, commit/push/PR runtime 반영·merge는 완료가 아니었다. 이후 공식 결과와 남은 gate는 run report/정본 이슈가 정본이다. 최신 지시의 cloud 코드 개발·합성 검증 허가를 실제 corpus 이동·배포·게시 승인으로 확대하지 않았다.

## 판단 provider(agent | Jev) — 2026-10-15 (이전 실행)

범위는 판단 provider 선택·Jev worker·README 구조도다. Agent Flow 공식 run·native review·QA가 아니며 실제 1–2주 trial이나 cloud를 포함하지 않는다. 모든 DB 검증은 전용 test PostgreSQL container(같은 image digest)의 일회용 schema에서 했고 사용자의 기존 container·DB는 건드리지 않았다.

- 새 회귀 54개(`test_jev_client` 15, `test_judge_settings` 18, `test_judge_worker` 16, `test_judge_cli` 5)가 실제 PG에서 모두 통과했다. 실제 TypeSafe는 호출하지 않고 in-process fake client·fake opener만 쓴다. 기존 suite는 **1726 passed, 11 skipped**(421s)이며 skip은 모두 명시 age/pg_dump binary 환경변수가 없는 backup/restore 경로다. ruff 통과.
- live Jev(사용자 키, `jev-1.13.0`): 비대화형 `init --judge jev --jev-key-file`이 합성 질문으로 키를 검증한 뒤 0600 사본을 만들고, 원래 0644 키 파일 경고를 냈다. stdout/stderr에 키 문자열은 없었다. `project add`가 worker grant를 추가했다. 합성 원문 6건에서 결정 문장 2건(영어·한국어)을 원문 그대로 remember, 잡담·불확실·단순 작업 로그 3건을 discard, tool 원문의 AI 지시 주입 1건을 기록 없이 pending으로 남겼다(8 requests, 4,945 input tokens). 이후 cleanup은 kind가 달라 검증 가능한 쌍이 없어 Jev 호출 없이 관계 0개로 기록됐다. 관계 Choice를 직접 보낸 확인에서는 같은 결정 재진술이 duplicate 0.99, 버전 교체 문장이 supersedes 0.51/contradicts 0.49로 나와 worker 규칙상 agent에게 넘길 범위였다.
- 실행 중 `judge set agent` 뒤 새 capture는 Jev 요청 수를 늘리지 않고 pending으로 남았다. 저장 키로 `judge set jev` 재활성화, `judge set agent --forget-key` 뒤 키·token 파일 삭제와 worker credential 폐기를 확인했다. agent token의 `inspect --ref judge` 응답에 키·fingerprint·credential이 없었다.
- native Claude Code 2.1.300(구독, `--mcp-config` 세션 전용 설정, 사용자 `~/.claude.json` 무변경)이 MCP로 Jev가 남긴 주입 원문을 discard하고 새 결정 원문을 remember했다. 자기 discard가 새 rejection을 만들어 첫 remember가 `REJECTION_COMPARISON_REQUIRED`였고, 다시 inspect해 비교를 넣어 성공했다(14 turns). native Codex 0.162.1(`exec --ephemeral --ignore-user-config`, 도구별 `approval_mode="approve"`)도 같은 방식으로 remember 1건·discard 1건을 기록했다. 모든 기록 credential은 agent role이었다.
- 터미널 경로: pty에서 `init`의 provider 질문과 화면 표시 없는 키 입력을 확인했다. 잘못된 키는 `JUDGE_KEY_REJECTED`/`not_started`였고 config·state 파일은 생기지 않았다.
- 한계: Jev의 kind 분류는 같은 결정을 preference와 fact로 다르게 냈다(관계 후보 쌍이 줄어든다). 임계값(0.8/0.2/0.5)은 문서 권장 출발점이며 표본으로 보정하지 않았다. capture 직후 서비스가 시작된 경우 cleanup은 다음 30초 주기에 처리됐다.

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

## PR #9 후속 로컬 운영·OSS 대조 — 2026-10-15

이 절은 **현재 작업트리**의 검증이다. PR #9 remote HEAD `1b52c4d487d0600d53cc85ec9dbca171d3cd9b3d`에 이 runtime 변경이 올라갔다거나 fresh 공식 runner review/QA/handoff가 완료됐다는 뜻이 아니다. 이전 PR8의 live Jev API 증거를 새 독립 정책 증거로 재사용하지 않는다.

### 회귀·package

- 최초 관련 회귀는 **969 passed/5 failed,228.89s**였다. recovery가 installer의 owned0755 intermediate를 거부한 실제 원인을 수정했다. leaf0700·소유권·symlink·group/other write 금지는 유지한다. 다른 실패 하나는 edge fixture의 incidental403 wording 기대였고 권한 거절·진단 비공개라는 행동 검증만 남겼다.
- 실패/신규 경계 follow-up은 **21 passed/1 failed,8.95s**였다. 원래5개 실패와 service 전체 deadline·동시 health/status·manual-stop, unsafe recovery parent, readiness deadline, 실제 worker 종료/inflight drain, production stdio paused pipe가 통과했다. 새 closed-pipe assertion 하나가 incidental code를 pin한 실패였다. 그 wording assertion만 제거하고 nonzero·재실행 없음·credential/source 비공개를 보존했다. 해당 실패 test만 재실행해 **1 passed,0.23s**였다. 이를 전체 suite green으로 합산하지 않는다.
- ruff import 지적은 targeted LSP action이 없어 surgical import 정리 후 지적 파일만 통과했다. 이미 성공한 lint/suite를 확인 목적으로 반복하지 않았다.
- `uv build`의 sdist/wheel 생성이 통과했다. wheel SHA256 `fc69d4269190831f66493d2939854cd67db092ed87872b7f6225a266296ced9d`. 새 venv에 offline 설치한 뒤 checkout/PYTHONPATH 밖에서 실제 package import·새 company schema migration·launchd·생성 Codex host-stdio·SDK MCP4도구·exact synthetic source inspect를 확인했다. 초기 fixture의 app schema/default ACL 누락은 공식 init-resume으로 준비해 해결했으며 제품 fallback을 추가하지 않았다.

### 실제 per-user launchd·DB·MCP

개인/회사 두 synthetic 배포는 독립 schema·journal·state·credential·port·host 설정을 썼다. PostgreSQL18.6/pgvector의 소유한 Docker fixture만 제어했다.

- RunAtLoad·비정상 종료 KeepAlive 등록, per-user job과 DB-inclusive ready를 확인했다. **OS logout/login·reboot·sleep 복귀를 실행한 것은 아니다.**
- 두 mode에서 default-deny는 존재하지 않는 key를 읽기 전 거절했다. 명시 allow만으로 provider가 agent에서 바뀌거나 요청하지 않았고 deny 복원도 확인했다. 실제 Jev network 대신 정책/worker 회귀의 fake API+실제 PG 경계를 검증했다.
- native SIGKILL 뒤 새 PID로 자동 복구했다. 개인39369→41779, 회사39427→55589. 같은 실행 중 stdio/MCP 소비자가 사라진 session을 안전하게 재연결해 inspect→remember→candidate_ready를 완료했다.
- durable service-stop 뒤 install replay/client가 되살리지 않았으며6초 관측 뒤에도 stop을 유지했다. recovery 중 capture pending1, 명시 start 뒤 **새 host event 없이 pending0**을 확인했다. 양 mode에서 통과했다.
- DB stop 시 `/readyz`는503/db_ready=false, 기존 service PID는 유지했다. capture는 bounded spool에 보존했고 지원 strict Claude 경로는 unavailable로 차단했다. process 존재를 ready로 보거나 장애를 ‘기억 없음’으로 바꾸지 않았다.
- 최초 DB 복구 wait는 Docker fixture의 random published port가32768→32770으로 바뀌어 실패했다. ConnectionRefused와 inspect로 원인을 특정했다. 같은 초기화 volume의 **소유한** fixture를 고정127.0.0.1:32768 endpoint로 재구성했다. 잘못된 endpoint 자동 탐색/DSN 변경을 제품에 추가하지 않았다. 누락된 복구만 이어서 검증해 두 mode의 ready 회복과 새 event 없는 spool pending0을 확인했다.
- service가 PostgreSQL/Docker 자체를 자동 시작/복구한다는 증거가 아니다. supported local loopback·등록 config·safe receipt 범위에만 적용한다. custom `CLAUDE_CONFIG_DIR`를 깨끗한 background 환경에서 재해석하는 경로는 별도 live proof가 없다.

### 실제 구독 coding agent·비공허 native 보호 행동

- 현재 company 배포에 native Codex `gpt-6.1-sol`을 연결했다. exit0/실제 MCP12호출, PG에 **agent-role source_selection remember**가 남았다. synthetic 원문은 `AltoNativeCompany retains scratch cache entries for exactly fourteen days.`이고 `source_08b7a854bca1460f84c5e002969eabc7` → `operation_2744f4099fce467ea5de3fe8f11e5915`였다. 호출 횟수만으로 최종 과제 품질/관련성 전체를 증명하지 않는다.
- claude-mem read-gate의 ‘tool이 아예 호출되지 않은 가짜 pass’를 피했다. 기존 native Claude 로그인을 그대로 사용하고 **새 owned synthetic project의 항목만 공식 host installer로 등록**했다. auth 값을 복사하지 않았다. Opus5.5 native CLI에 실제 `Write`를 요청했다.
- 정상 arm: Write attempt1, 같은 tool-use ID의 successful result1, exact sentinel 파일 존재. DB outage arm: Write attempt1, 같은 ID의 error result1/`SERVICE_UNAVAILABLE`, sentinel 없음. 모델이 Write를 포기한 결과나 단순 hook fixture pass가 아니다.
- harness 준비에서 CLI variadic 인자 파싱, isolated config의 로그인 부재/receipt guard, config home을 바꾼 기존 receipt 재사용이 먼저 실패했다. 이를 정상 실행으로 세지 않았다. 새 project·기존 공식 auth·현재 native config 경로에 설치해 검증했고 ownership/trust guard를 완화하지 않았다.
- cleanup의 공식 uninstall 뒤 owned native entry가 제거되고 다른 프로젝트·global MCP/permission/security/trust authority의 hash가 baseline과 같음을 확인했다. native hook trust 변경/bypass·자격증명 복사는 없었다. 이 증거는 해당 installed Claude 버전·executor·보호 Write에 한정되며 OMP 전체 fail-closed나 모든 native tool 지원을 뜻하지 않는다.

### OSS·건강 관리·물리 저장

- [OMP/Claude/Codex·read-gate·86개 후보 조사](research/2026-10-15-oss-local-runtime.ko.md), [DB 성장 해결 코드/PR 조사](research/2026-10-15-oss-db-growth.ko.md), [건강 관리 독립 모델 리뷰](research/2026-10-15-memory-health-adversarial.ko.md)를 작성했다. current code pin·merged/open/unmerged·기본 off·라이선스·권한 차이를 구분했다. upstream source/issue를 읽었으며 upstream 전체 test를 실행하거나 code를 복사/새 engine을 설치하지 않았다.
- native Opus5.5와 Codex6.1Sol 검토가 실제222.20286초 겹쳤다. Opus xhigh와 Sol header effort none을 구분하고, Opus self-challenge가 철회한 과장을 최종 결론에서 뺐다. 새 formal runner approval/QA나 모델 성능 benchmark가 아니다.
- 별도 owned PG/SQLite 저장 실험에서 row DELETE·checkpoint·plain VACUUM이 파일 즉시 축소와 다름을 관측했다. 합성 row/물리 byte·버전·FULL/VACUUM 결과는 DB 보고서에만 기록한다. production 성능·회수율·secure erase·상시 rewrite 권고가 아니다.
- health subsystem·자동 audit/삭제/승격·새 telemetry/원문 전송은 켜지 않았다. Reject가 미래 게시 차단이지 기존 recall 즉시 제외가 아니라는 의미, post-backup Reject/discard rollback과 삭제 journal의 구분을 문서화했다.

### 회수와 남은 증거 경계

공식 service-stop·host-uninstall·service-uninstall로 두 native job과 owned 설정을 회수했다. 추가 company wheel consumer는 자체 smoke에서 회수했다. 소유한 Docker container·그 volume, 임시 token/DSN/config/state/journal/venv·script·native output을 제거했다. 다른 프로젝트/global native authority 보존은 위 compare로 확인했다. body-free `observed.json`, `storage-probe-observed.json`, `wheel-consumer-observed.json`만0700 runtime 아래0600으로 보존했다. 기존 사용자 PG container·stable service·live corpus는 제어하지 않았다.

**미실행/미완료:** 유효 key file이 필요한 새 정책의 실제 Jev API·양 provider의 live 교차 운영, 실제 login/reboot, native OMP model/전체 host tool 보장, fresh 공식 review/QA/handoff, 실제1–2주 paired trial, cloud provisioning/remote8개 사례, commit/push/추가 PR/merge와 merged MCP 운영 설치. 부분 결과·source-only 분석·옛 PR proof로 이 상태를 덮지 않는다.

## 우측 integration owner 재개·CI 전용 후속 — 2026-10-16

`w18:pE`가 기존 dirty worktree와 모든 증거·잔여 요청을 인수했다. 정상 installed Agent Flow status/continue로 동일 `development/20261016-110757`의 fix-loop/awaiting_host에 재개했다. 원본 `w18:pA`가 pane 목록에서 사라지고 목적지 `w18:pE`만 살아 있음을 실제 관측해 private transfer receipt에 기록했다. receiver가 shared Herdr server/workspace/tab·VM/daemon/LSP를 종료하지 않았다. 이 항목의 완료는 제품 완료/QA handoff가 아니다.

### 작성한 코드·회귀, 실행하지 않은 검증

- CI environment는 Actions-only·job-owned private state/label/name을 사용한다. Python3.13.16의 실제 SQLite≥3.51.3, Node24+, 고정 age1.3.2 archive, 공식 PG18 client와 digest 고정 pgvector image의 실제 server/vector를 검사하도록 구성했다. Docker는 CI fixture 준비/정리용이며 제품 operations는 native PG18 도구의 local mode다. daemon 권한이나 제품 Docker socket guard를 완화하지 않았다.
- 전체 pytest collection의 sorted node ID·source digest·결정적 SHA256 partition과 실제 setup/call/teardown 보고를4개 shard로 기록한다. aggregate는 exact disjoint union·동일 SHA/source·실패/skip/xfail/수집 오류0·upstream job 성공과 각 prerequisite receipt를 요구한다.
- lint/build와 실제 wheel 설치 소비를 별도 기록한다. wheel 소비는 editable app을 artifact로 교체한 뒤 새 `-I` process에서 generated native commands와 occupied-port CLI를 실행한다. aggregate가 consumer의 전체 declared case·동일 source·wheel SHA256을 **다운로드한 public distribution**과 대조하도록 구성했다. 이 subset을 전체 suite 수에 중복 합산하지 않는다.
- JSON/JUnit은 explicit path의 hidden-file 업로드를 사용한다. raw traceback/captured output에는 private DSN이 섞일 수 있으므로 JUnit은 outcome-only XML이다. 누락 artifact·중단/timeout은 green이 아니다.
- 새 회귀는 실제 TLS slow headers/body·pending TCP·business TLS handshake·첫 send 전 stop·전송 후 business drain·DNS 전체 cycle budget, bad-first retained recovery와 backoff 뒤 healthy 전달을 다룬다. 기존 ingress 권한·service uninstall 효과·upgrade 순서 수정도 그대로 보존했다.
- OSS 후속으로 no-op purge/reconcile UPDATE 억제, adapter6 import isolation/owned-v5 cleanup, lifespan 전 listen 확보를 적용했다. 실제 PG row-version/restore repair·생성 command shadow imports·실제 CLI DB readiness/port 회수 회귀를 작성했다. source-only 비공식 검토는 formal Opus/Sol 승인이나 실행 증거가 아니다.

**로컬 실행0:** 이 재개 후 test·collect-only·ruff/lint·build·추가 smoke를 실행하지 않았다. **현재 수정의 Actions run도 아직 없다.** workflow/회귀/consumer 작성만으로 green·전체 통과·release 완료를 주장하지 않는다. 이전2311 pass/skip0의 고정 source/wheel과 기존 before/after 실패·성공 자료는 원래 층위로 보존한다.

### 정상 workflow·게시 의존성

마지막 게시 checkpoint는 `6a93cb55d7e22d9b3b17199ce18b8e5ba1c8ef51`이고 이후 수정은 미커밋·미push다. 실제 GitHub 조회에서 repository Actions run은0, PR #9의 head는 이 checkpoint·base는main·상태는open이었다. API의 `draft`는 **false**여서 의도한 Draft 상태라고 단정하지 않으며 receiver가 PR 상태를 변경하지 않았다.

현재 pinned profile의 lint/test/package는 `execution: local`이다. `gates --execution ci`는 선언된 CI gate만 선택할 뿐 기존 local gate를 Actions로 바꾸지 않는다. 빈 CI 선택을 QA 완료로 표시하지 않는다. 정상 hosted review는 fresh 독립 reviewer 실행 뒤 review/awaiting_host에서 멈추는 지원 경계가 있으나, 실제 Actions 결과를 local gate 통과로 import하는 지원 경로는 확인되지 않았다. pins/settings/guard·판정·기존 timeout을 바꾸지 않는다. 이후 사용자가 **최신 CI·보안·복구·OSS 수정의 CI 검증용 미검증 checkpoint commit/push만** 명시 허용했다. 정상 guard 경로만 사용하며 QA 위조·merge·출시 승인은 아니다. 위 미커밋/미push·run0은 이 허용 전 관측이고 실제 게시/실행은 별도 증거가 필요하다.

원래 Opus timeout/나머지 skipped와 Sol request-changes는 보존한다. 새 formal 양 모델 리뷰·실제 CI·정상 QA/handoff·commit/push/PR 갱신은 여전히 별도 완료 조건이다. [OSS 후속 조사](research/2026-10-16-oss-followup.ko.md)의 보류 위험과 원래18개 native/평가/운영/권한/반입/trial/release/미귀속 volume acceptance도 인수했으며 코드 작성만으로 완료 처리하지 않았다.
