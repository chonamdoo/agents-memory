# 요구사항·완료 계약

상태: **로컬 기본 구성과 클라우드 원격 경로를 작업트리에 구현하고 격리 합성 검증 중**이다. 배포 위치·개인/회사 운영·Jev 허가/명시선택은 독립 축이며 [12개 사례](../README.md#배포-위치--운영-주체--jev-정책)를 유지한다. 새 정책의 실제 Jev vendor/API와 구독 coding-agent 실행은 검증 기록의 배포·모델·범위에만 적용한다. PR remote 코드·병합/운영 설치·공식 QA·elapsed trial·일반 출시와 별개다. 최신 cloud 개발 지시는 실제 계정 provisioning·실제 corpus 저장/이동·egress나 publication을 승인하지 않는다.

이 문서는 공통 coding-agent 판단의 제품 요구 계약이다. 실행 결과는 해당 run의 [검증 기록](verification.ko.md)에만 적용한다. 이전 Qwen/full-semantic 및 회사 lexical/entity 기록을 다른 실행의 증거로 재사용하지 않으며 요구 표·시나리오 정의를 완료 주장으로 사용하지 않는다.

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
| U10 | Python 적합성 확인 | Python≥3.12·공식 SDK2 실제 wire 호출. PC spool의 patched SQLite runtime 검사·unsafe 버전의 쓰기 전 거절. 제품 runtime 증거는 probe와 분리 |
| U11 | 로컬 환경 기본 구성과 운영 복구 | loopback agents-memory·PG18·host·stdio. 개인/회사 기본 agent의 실제 PG/MCP 판단과 macOS 서비스 복구·중지·DB readiness·capture 자동 전송을 검증. native 등록과 실제 로그인 관측 구분, Jev 새 live API는 별도 U32 |
| U12 | 1–2주 직접 사용 trial | architecture10절의 frozen paired memory-on/off trial은 미시작. 로컬/클라우드 기능 구현·합성 검증과 별도로 실제 기간·기록·중단·판정 조건 준수, elapsed/효익 조작 금지 |
| U13 | 개인·회사 클라우드 원격 경로 | 동일 core/schema/API/rule, verified HTTPS·bearer/OAuth·현재 PG 권한·one-binding bootstrap·PC remote profile·capture recovery 구현. source/API/native/배포 proof를 구분하고 실제 계정 provisioning·corpus 이동은 별도 |
| U14 | corpus별 저장·외부 전송 허가와 격리 유지 | 회사·개인·고객 corpus를 독립 deployment로 격리하고 각 corpus의 명시적 허가 준수. 다른 deployment로의 자동 동기화·무승인 이전 금지. 승인된 회사 클라우드는 회사 배포이며 “회사”라는 명칭만으로 외부 memory 저장을 일괄 금지하거나 허용하지 않음 |
| U15 | 배포 위치·운영 주체·Jev 허가/선택의 독립 축 | 12개 사례. 개인/회사 × 로컬/클라우드 모두 default-deny, allow와 provider 선택 분리. 실제 Jev·구독 agent·no-call 관측 범위 및 미검증 행을 사례별 명시 |
| U16 | 구독 coding-agent 판단과 허가 분리 | Jev 불가·미설정·미선택이면 Claude Code·Codex·OMP 현재 세션이 MCP inspect → source_selection·관계 판단 → record. 서버가 구독을 API 키처럼 쓰지 않음. coding-agent 모델 처리·memory 저장·Jev 외부 전송 허가는 별개이며 자동 fallback이 아님 |
| U17 | 명시 egress 정책·strict no-egress | 개인/회사 모두 허가 누락·deny 시 Jev 키 검증/전송/게시 차단, allow만으로 provider 변경·네트워크 호출 없음. 허가된 coding-agent 경로·OS/network 경계는 별도이며 자동 fallback 없음 |
| U18 | review·컨벤션이 skill처럼 갱신 | candidate→exact revision 승인→active rule→조건별 선택→정정·철회 |
| U19 | 적용 범위 정확히 세 가지 | 이 로컬 프로젝트 / 내 프로젝트들 / 팀 또는 프로젝트 공유 |
| U20 | 개인 프로젝트는 팀 배포 불필요 | local-project 승인·적용 가능. team/Git/PR 강제 없음 |
| U21 | 팀 공유도 root 규칙 비대화 금지 | root AGENTS.md·CLAUDE.md·eager rulebook에 full body/catalog 설치하지 않음 |
| U22 | PR334·341 및 기존 논의 고려 | 이전 source 조사·유효 contract를 재사용하되 AF core cutover·obsolete 경로는 만들지 않음 |
| U23 | 제공 자료·논문·GitHub·영상 고려 | frozen research provenance 유지. 요청 [Shorts 원문 설명·단독 분석과 관측 한계](research/2026-10-16-shorts-lTja2ZxXYyI.ko.md)를 별도 연결하며 전체 재생·embedding 실측 완료를 주장하지 않음. CueFinder 앱 codegraph 재사용 주장은 제외 |
| U24 | SIE 포함 OSS 참고 | 버전·source pin·license·보안·채택/참고/제외 이유 기록. SIE v1 기반을 SDK2처럼 사용하지 않음 |
| U25 | DB·검색·queue·모델·ops까지 비교 | 실제 source로 정본·queue owner·모델 license·운영 경계 선택 |
| U26 | 실제 두 모델 parallel 적대적 review | native gpt-6.1-sol·claude-opus-5-5 xhigh 설정, 동일 입력 hash·overlap·exit·output 검증 |
| U27 | 두 모델 의견 교환·수정 | 각 모델이 peer의 원문을 읽고 수용·반박·자기 수정하는 두 번째 실제 호출 |
| U28 | 영향 범위·장단점·최적안 | 선택·기각 이유, 모듈·API·storage·host·운영·migration 영향 명시 |
| U29 | 최신 Agent Flow 설치 | 고정된 최신 main의 실제 version·설치 결과. 기존 global tool은 보존 |
| U30 | 프로젝트 성질에 맞춘 AF 설정 | Python, local architecture, local verification gates, 요청된 두 native reviewer |
| U31 | 최종안을 Agent Flow로 실행 | 실제 run·isolated worktree·phase artifact·review·QA·local handoff. PR/merge는 별도 사용자 승인 |
| U32 | 판단 provider 선택·동일 검증 | 두 mode 모두 allow·egress 확인·유효 키·명시선택 때만 Jev worker, 나머지는 구독 coding-agent MCP. 동일 span/revision/권한/삭제/snapshot 검증과 request/response/publication fence. MCP 조회만·키0600·값 미노출. 새 정책의 실제 vendor proof를 옛 PR 이력과 구분 |
| U33 | 구현·증거·실배포 구분 | 로컬/remote 구현과 격리 TLS/PG/vendor/native 실행, fresh 공식 review/QA/handoff, 실제 trial, 계정 provisioning·외부 witness·corpus 승인·publication을 별도 기록. cloud 개발은 최신 지시로 trial과 독립 진행하되 운영 승인으로 확대하지 않음 |
| U34 | macOS 자동 시작·장애 복구·명시 중지 | per-user launchd RunAtLoad·abnormal restart. DB 왕복 ready 후 연결·새 event 없는 bounded spool 전송·unavailable/지원 strict fail-closed. stop은 disabled를 먼저 저장하고 native unload를 bounded 확인, client/install/recovery 부활 금지. remote는 PC recovery만 관리 |
| U35 | 건강 관리·DB 비대화 제안 적대적 리뷰 | provenance/Health Audit/Accept-Reject/coalesce/retention·구형 DB/backup·참고 OSS의 실제 성장 대책을 비교. 리뷰는 새 health subsystem·자동 삭제·전송·승격 구현 승인이 아님 |

## 추가 필수 불변식

| ID | 계약 | 관측 가능한 실패 사례 |
|---|---|---|
| I01 | source·claim·조건·부정·시간·entity·evidence graph | 조건이 다른 주장을 합치거나 단순 latest-write로 삭제하지 않음 |
| I02 | capture→원문 inspect→source_selection→claim_judgment→candidate manifest→전체 relevance→정정→next use | runtime `mode=personal`·`mode=company`에서 동일한 기본 `agent` provider의 실제 PG/MCP loop. server LLM·lexical 자동 판단·echo/mock를 대체 증거로 쓰지 않음 |
| I03 | 구형 model work retirement와 pending successor | 원래 job/오류/attempt/generation/시간 audit 보존. Qwen 재시도·성공 relabel·실패 삭제 금지 |
| I04 | caller admission와 게시/최종 전달 모두 eligibility 검사 | source/claim revision·credential/grant·binding·contract·snapshot·deadline·deletion 변경 후 stale 판단/전달 거절. 구형 NULL request_digest도 DTO 내부 오류 대신 ADMISSION_STALE/not_started이며 새 inspect로 재개 |
| I05 | logical retract·local drain·provider unknown·physical purge 분리 | cancel/소켓 종료를 provider erasure라고 하지 않음 |
| I06 | causal read와 accepted/indexed 분리 | pending을 빈 corpus나 queryable 완료로 표현하지 않음 |
| I07 | idempotency payload fingerprint | 같은 key·다른 payload conflict. 응답 유실 retry도 하나의 operation |
| I08 | principal·realm·binding 신뢰 경계 | body/CWD/branch/MCP session을 authority로 쓰지 않음. 연결된 MCP는 리더/워크트리·호출 CWD와 무관하게 같은 credential/project binding으로 동작. 설치 소유권·자동 capture/hook 경로 검사는 별도 유지 |
| I09 | 전체 입력 dependency lineage | 인용하지 않은 입력도 철회에 영향을 줌 |
| I10 | source identity·spool replay·삭제 floor | 과거 spool/import/backup으로 철회 자료가 부활하지 않음 |
| I11 | PG restore 밖 본문 없는 journal | 최신 head 확인 불가·reconciliation 미완료 때 읽기 차단 |
| I12 | approval exact digest·target-set revision | body/selector/예외/범위 변경 후 이전 승인 재사용 거절. 기억 판단과 required-rule 승인은 별개 |
| I13 | candidate와 active rule 분리 | 모델 confidence·human=true·MCP hint가 활성화 권한이 아님 |
| I14 | 선택·전달·model-input·준수·enforcement 구분 | receipt만 기록하고 첫 보호 행동을 allow하지 않음 |
| I15 | child·resume·compact·fork context generation | 보존 확인 불가 시 새 generation, 다른 agent의 receipt 재사용 금지 |
| I16 | unknown selector·writer footprint | unknown을 false로 치환하지 않음. strict 지원 불가 행동은 block/capability gap |
| I17 | text/structured 본문 한 plane | facts·rule body를 SDK/host가 두 번 렌더링하지 않도록 구성·실측 |
| I18 | auth·Host/Origin·body/queue/backpressure | 비인증·교차 realm·DNS rebinding·초과 입력 거절, 비밀 포함 오류 금지 |
| I19 | 판단 executor는 현재 coding-agent | 별도 서버 모델·model purposes·gateway·lease 설정·자동 download·외부 fallback 제거. lexical/entity는 candidate index뿐 |
| I20 | local restore·토큰 폐기·명시 migration | current auth·0006 forward/old archive floor·원래 private config/서명/token 보존. 실제 format-one init resume와 exact-file SHA256 명시 model-intent retirement·중단 재개. 취소된 DDL thread 종료까지 exclusive lock 유지, unknown은 request/operator-bound durable fence와 명시 복구. migration/restore intent 구분·보존 원본과 exact published target 재검증. 구형 route disable·원래 효과 unknown, live 실행 증거는 별도 |
| I21 | 운영 보장의 한계 | 같은 UID unrestricted agent를 인간 승인으로 포장하지 않음. 별도 identity/approver는 선택적 공유 규칙 활성화 경계이며 회사 기억판단의 별도 승인 절차가 아님 |
| I22 | proof 층위 분리 | source 사실·설계 선택·실행 결과·unverified·trial pending 별도 표기 |
| I23 | runtime `mode=personal`·`mode=company`의 단일 `agent_judged` capability | 배포 환경 분류와 다른 축. `full_semantic`/company-only `lexical_entity` 기본·selection-policy approve/enable 제거. 모델-derived legacy claim은 원래 provenance/awaiting_revalidation 유지 |
| I24 | capture ≠ 판단 ≠ candidate | capture는 `captured`, 판단은 `selection_recorded`, grounded 게시만 `candidate_ready`. discard/reject는 삭제가 아니며 오류는 판단 label이 아님 |
| I25 | saved candidate manifest의 두 호출 relevance | 첫 응답은 전체 candidate IDs/ref·admission·required rules. wire 예산 부족은 선택적 preview만 축약/partial, ID 삭제 금지. 둘째는 같은 admission/request·전체 exact IDs의 relevant/irrelevant/reason. 후보0이면 승인 optional rule도 전달 |
| I26 | 관계는 명시 원문 근거·complete manifest | claim_ids 공동20개·기존 logical 관계128 ref/요약8개·overflow 명시. 각 judgment의 독립 전체 dependency/edge를 보존하고 적격 logical read만 중복 제거. 공개 duplicate 정규화·조건/부정/예외 보존 |
| I27 | bounded cleanup은 pending scheduling뿐 | transaction당 pending32·고정 삽입위치20개 bucket4·scope group32와 durable progress/more. 현재 manifest·pending ID·관계0 dependency·held 보존. non-deriving 철회는 extraction floor 없이 uncovered 원문 재개. server LLM 없음 |
| I28 | 거절 이유와 재진입 방지 | 관련 색인 후보 최대8개만 필수 비교, 선택적 history/review와 현재 fingerprint 검사. 무관한 새 history로 전체 재검토 강제 금지. exact evidence 차단은 색인과 독립·scope/파생 target privacy 선검사. 새 독립 근거 reopening만 허용하며 의미 판단은 agent |
| I29 | agent_note는 독립 grounding 아님 | raw log/inspection은 보존하되 판단 admission·신규 pending·독립 backlog·미판단 coverage를 만들지 않음. note/feedback reason만 남으면 partial 원인이 아니며 미해결 human·일반 assistant·tool·document는 여전히 반영. note-only remember·memory echo는 새 support가 아니며 과거 note discard로 인간 근거를 오염시키지 않음 |
| I30 | 비밀은 저장·digest 이전 거절 | generic SOURCE_SECRET_REJECTED/not_started/422·body-free durable host gap. legacy outbox/quarantine 모두 scrub, 앞 transient 실패로 뒤 secret 잔존 금지. local invalid 판정은 읽은 key+digest+payload가 같은 row에만 적용하며 새 durably_spooled replacement와 gap/error 집계를 오염시키지 않음. body/key/digest 노출·원문 rewrite 금지 |
| I31 | hostile exact-source와 hostnative 중복 시나리오 | architecture 9절 PMPA·secret/content reentry·native memory 공존 expected result를 실제 executor별로 확인. source-only/SDK/native proof 혼합 금지 |
| I32 | trial/health/publication 범위 분리 | trial 미시작·효익 미측정. 건강 관리 제안 리뷰와 구현 승인을 분리하며 새 metrics/telemetry·자동 audit/삭제/전송은 이번에 켜지 않음. commit/push/PR/merge는 별도 사용자 지시 경계 |
| I33 | 사라진 MCP 세션의 안전한 복구 | 재시작·유휴 만료·세션 수 초과 뒤 요청은 SESSION_NOT_FOUND/404/not_started, 다른 credential 세션은 SESSION_CREDENTIAL_DENIED/403. relay는 모든 필드가 검증된 SESSION_NOT_FOUND+not_started에서만 재initialize 후 원 요청을 1회 재전송하며 unknown 효과는 재전송 금지. 재연결 실패·다른 protocol version 협상 시 요청을 보내지 않고 SESSION_NOT_FOUND/not_started |
| I34 | 하나의 DB 지원 계약 | serve·migrate·backup·restore 모두 PostgreSQL 18.x·pgvector ≥0.8.7·같은 major PG 도구. archive는 live 버전 기록, restore는 같은 계약으로 검사. 위반은 journal reconcile·DDL·restore fence 전 DATABASE_VERSION_UNSUPPORTED/not_started(backup은 staging·recipients 전) |
| I35 | 원문 창당 하나의 판단 승자와 응답 유실 재시도 | 같은 source revision·contract·snapshot의 겹치는 창을 잡는 active complete remember/discard는 하나뿐(SELECTION_ALREADY_RECORDED, review 예외, 거절·파생 floor 우선). 게시한 claim이 모두 철회된 remember는 창을 놓으며 파생 floor가 새 claim을 막음, claim 없이 기록한 remember는 창을 계속 잡음. 같은 admission·같은 판단의 새 key 재시도는 원래 operation, 다른 판단은 ADMISSION_CONSUMED. receipt digest 불변 |
| I36 | 과부하의 not_started 거절 | 동시 요청 상한 초과는 인증 전 SERVICE_BUSY/503, pool 획득 기한 초과는 DATABASE_BUSY/503 모두 not_started. 인증은 전역 am_clock 잠금을 기다리지 않음 |
| I37 | recovery와 명시 stop의 우선순위 | disabled intent를 native stop 전에 영속화. shared healthy 조회·exclusive mutation, 시작 전에 intent 재검사. stop 직후 native drain 중 상태를 즉시 종료로 위장하지 않음 |
| I38 | readiness와 미확정 쓰기 | process가 아니라 DB·identity·삭제 barrier 확인. native와 HTTP 전체 deadline 공유. unavailable를 empty로 바꾸지 않고 unknown-effect business write를 재전송하지 않음 |
| I39 | shutdown failure isolation | 한 recovery/judge/scheduler stop 실패에도 나머지 join·application drain·DB close를 시도하고 원래 실패 보존, 본문 없는 operator diagnostics |

`source_selection.coverage="complete_window"`는 판단한 원문 창의 계약이다. native capture의 전체 session·human-presence 관측 gap은 판단 완료로 없어지지 않으며, unclassified0이어도 incomplete/partial이 남을 수 있다. OMP preparation secret 거부는 source digest 이전에 body-free gap으로 durable하게 기록하고 기존 capture/offer 권한·generation은 전진시키지 않는다.

Spool의 local invalid 판정뿐 아니라 늦은 remote ACK·확정 거절도 읽은 key+digest+payload를 fence로 사용한다. TTL 만료 receipt가 bounded cache에서 퇴출된 뒤 같은 key의 새 원문이 durably_spooled한 경우에도 이전 결과로 새 row를 삭제하거나 committed로 오표시하지 않는다.

## 공개·권한 경계

기존 `research/`는 사용자의 기존 파일이다. 일괄 stage/삭제하지 않고 이번 작업 소유 제품·설계 파일만 명시적으로 stage한다. 회사 자료·credential·원문 capture·로컬 DB·모델 weight·backup은 repository에 넣지 않는다. 사용자는 **#5 전체 항목 해결과 공식 검증 후에만 commit→push→PR**, **main merge 확인 후 실제 Agent Flow 프로젝트 폴더에 merged MCP 설치·동작 확인**을 요구했다. 부분/draft PR로 대체하지 않으며 merge·원문/credential 공개 승인은 없다. 최신 검증 지시는 실패 항목만 재검사하는 것이므로 이미 통과한 테스트와 전체 suite를 반복하지 않고 중단/부분 결과를 정확히 기록한다.
