# 요구사항·완료 계약

상태: 제품 요구 계약. 구현의 실제 runtime/native/회귀 증거와 미관측·운영 외부·trial pending 경계는 [검증 기록](verification.ko.md)에서 항목별로 확인한다. 요구 표 자체를 완료 주장으로 사용하지 않는다.

## 사용자 요구

| ID | 요구 | 완료 관측·범위 |
|---|---|---|
| U01 | 독립 agents-memory 오픈소스 | Agent Flow 자체 수정 없이 독립 설치·실행·패키징 |
| U02 | Agent Flow에서도 사용 | 같은 core API·adapter를 실제 AF workflow에서 소비 |
| U03 | Claude Code에서도 사용 | 설치된 native Claude의 실제 MCP 호출과 지원 adapter 경로 |
| U04 | Codex에서도 사용 | 설치된 native Codex의 실제 MCP 호출과 지원 adapter 경로 |
| U05 | omp에서도 사용 | 설치된 native omp의 실제 MCP 호출과 지원 adapter 경로 |
| U06 | 일반 prompt·여러 workflow·child | workflow 없는 호출도 가능. lifecycle별 지원·불가 경계를 분리 |
| U07 | 정확하고 일관된 호출 | 한 core handler, strict schema, 인증 principal·binding, 의미 idempotency |
| U08 | 세션마다 불필요한 context 방지 | 연결 시 corpus·규칙 본문 0, 작은 고정 catalog, 요청별 bounded selection |
| U09 | MCP 2 형태 | 공식 SDK의 modern protocol 실제 호출. legacy 동일 handler 경로 별도 확인 |
| U10 | Python 적합성 확인 | Python 3.12·공식 SDK2 실제 wire 호출. 제품 runtime 증거는 probe와 분리 |
| U11 | 로컬 우선 | cloud 계정·서비스 없이 실제 PG·모델·전체 semantic pipeline 실행 |
| U12 | 1–2주 직접 사용 후 cloud | elapsed trial을 조작하지 않음. 시작·지표·중단·통과 조건 제공 |
| U13 | 로컬·cloud 동일 설계 | core·schema·API·rule semantics 유지. 배포·인증·모델 route만 구성 차이 |
| U14 | 회사 정보는 외부 memory 저장 불가 | 회사·개인·고객 deployment 분리. 회사→개인/cloud sync 없음 |
| U15 | 개인도 보안 필요 | loopback·인증·권한·egress·secret·backup·삭제·복구 정책 동일 core |
| U16 | 회사 팀 Claude/Codex 사용 | 승인된 모델 처리와 외부 memory 저장을 구분. 구독을 background API 허가로 간주하지 않음 |
| U17 | strict no-egress 회사도 고려 | 승인된 내부/offline 모델 경로. unconfigured route는 blocked, cloud fallback 금지 |
| U18 | review·컨벤션이 skill처럼 갱신 | candidate→exact revision 승인→active rule→조건별 선택→정정·철회 |
| U19 | 적용 범위 정확히 세 가지 | 이 로컬 프로젝트 / 내 프로젝트들 / 팀 또는 프로젝트 공유 |
| U20 | 개인 프로젝트는 팀 배포 불필요 | local-project 승인·적용 가능. team/Git/PR 강제 없음 |
| U21 | 팀 공유도 root 규칙 비대화 금지 | root AGENTS.md·CLAUDE.md·eager rulebook에 full body/catalog 설치하지 않음 |
| U22 | PR334·341 및 기존 논의 고려 | 이전 source 조사·유효 contract를 재사용하되 AF core cutover·obsolete 경로는 만들지 않음 |
| U23 | 제공 자료·논문·GitHub·영상 고려 | frozen research provenance 유지. CueFinder 앱 codegraph 재사용 주장은 제외 |
| U24 | SIE 포함 OSS 참고 | 버전·source pin·license·보안·채택/참고/제외 이유 기록. SIE v1 기반을 SDK2처럼 사용하지 않음 |
| U25 | DB·검색·queue·모델·ops까지 비교 | 실제 source로 정본·queue owner·모델 license·운영 경계 선택 |
| U26 | 실제 두 모델 parallel 적대적 review | native gpt-6.1-sol·claude-opus-5-5 xhigh 설정, 동일 입력 hash·overlap·exit·output 검증 |
| U27 | 두 모델 의견 교환·수정 | 각 모델이 peer의 원문을 읽고 수용·반박·자기 수정하는 두 번째 실제 호출 |
| U28 | 영향 범위·장단점·최적안 | 선택·기각 이유, 모듈·API·storage·host·운영·migration 영향 명시 |
| U29 | 최신 Agent Flow 설치 | 고정된 최신 main의 실제 version·설치 결과. 기존 global tool은 보존 |
| U30 | 프로젝트 성질에 맞춘 AF 설정 | Python, local architecture, local verification gates, 요청된 두 native reviewer |
| U31 | 최종안을 Agent Flow로 실행 | 실제 run·isolated worktree·phase artifact·review·QA·local handoff. PR/merge는 별도 사용자 승인 |

## 추가 필수 불변식

| ID | 계약 | 관측 가능한 실패 사례 |
|---|---|---|
| I01 | source·claim·조건·부정·시간·entity·evidence graph | 조건이 다른 주장을 합치거나 단순 latest-write로 삭제하지 않음 |
| I02 | capture→extract→embed→consolidate→hybrid recall→rerank→reflect→correction→next use | 실제 모델·PG로 full loop. SQLite/echo/mocked provider를 대체 증거로 쓰지 않음 |
| I03 | job lease token·generation fencing | 만료 lease의 heartbeat·publish·후속 job 생성 거절 |
| I04 | 입력 admission와 publish 모두 eligibility 검사 | 철회·권한·route·snapshot 변경 후 stale 결과 게시 거절 |
| I05 | logical retract·local drain·provider unknown·physical purge 분리 | cancel/소켓 종료를 provider erasure라고 하지 않음 |
| I06 | causal read와 accepted/indexed 분리 | pending을 빈 corpus나 queryable 완료로 표현하지 않음 |
| I07 | idempotency payload fingerprint | 같은 key·다른 payload conflict. 응답 유실 retry도 하나의 operation |
| I08 | principal·realm·binding 신뢰 경계 | body/CWD/branch/MCP session을 authority로 쓰지 않음 |
| I09 | 전체 입력 dependency lineage | 인용하지 않은 입력도 철회에 영향을 줌 |
| I10 | source identity·spool replay·삭제 floor | 과거 spool/import/backup으로 철회 자료가 부활하지 않음 |
| I11 | PG restore 밖 본문 없는 journal | 최신 head 확인 불가·reconciliation 미완료 때 읽기 차단 |
| I12 | approval exact digest·target-set revision | body/selector/예외/범위 변경 후 이전 승인 재사용 거절 |
| I13 | candidate와 active rule 분리 | 모델 confidence·human=true·MCP hint가 활성화 권한이 아님 |
| I14 | 선택·전달·model-input·준수·enforcement 구분 | receipt만 기록하고 첫 보호 행동을 allow하지 않음 |
| I15 | child·resume·compact·fork context generation | 보존 확인 불가 시 새 generation, 다른 agent의 receipt 재사용 금지 |
| I16 | unknown selector·writer footprint | unknown을 false로 치환하지 않음. strict 지원 불가 행동은 block/capability gap |
| I17 | text/structured 본문 한 plane | facts·rule body를 SDK/host가 두 번 렌더링하지 않도록 구성·실측 |
| I18 | auth·Host/Origin·body/queue/backpressure | 비인증·교차 realm·DNS rebinding·초과 입력 거절, 비밀 포함 오류 금지 |
| I19 | model artifact·runtime·route pin | offline no-auto-download·no hidden provider fallback·목적별 route 승인 |
| I20 | local restore·토큰 폐기·DLQ·migration | 명시적 migrator, rotate/revoke, stop/drain, encrypted backup/restore 실동작 |
| I21 | 운영 보장의 한계 | 같은 UID unrestricted agent를 인간 승인 보장으로 포장하지 않음. 강한 회사 승인에는 별도 identity/approver 경계 |
| I22 | proof 층위 분리 | source 사실·설계 선택·실행 결과·unverified·trial pending 별도 표기 |

## 공개·권한 경계

기존 `research/`는 사용자의 기존 파일이다. 초기 commit에 일괄 포함하거나 삭제하지 않는다. 이번 작업 소유의 제품·설계 파일만 명시적으로 stage한다. 회사 자료·credential·원문 capture·로컬 DB·모델 weight·backup을 repository에 포함하지 않는다. 현재 요청은 로컬 실행과 handoff이며 원격 push·PR·merge 승인이 아니다.
