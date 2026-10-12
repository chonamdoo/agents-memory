# 적대적 검토 전 제안 — 독립 memory OSS의 설치·MCP·local/cloud

문서 상태: 구현·실측이 아닌 반박 대상 설계. 사용자 요구는 회사/외주회사용 로컬과 개인용 클라우드가 같은 memory pipeline으로 동작하는 것이다. 자동 수집/추출/회상/reflect/정정·철회를 수동 기억 저장으로 축소하지 않는다. Agent Flow #334의 범위는 optional host memory 참고 + tracked team rule이고, 신규 memory runtime을 구현한 PR이 아니다.

## 두 축과 세 옵션

MCP는 agent와 service의 도구·리소스 통신 protocol이다. installer/CLI/daemon/OCI image는 배포·운영 방식이다. 설치된 제품이 MCP를 제공할 수 있으므로 이 둘은 양자택일이 아니다.

| 옵션 | 프로세스·저장소 권위 | 장점 | 반례/비용 |
|---|---|---|---|
| A. 각 agent가 stdio MCP package를 실행하고 그 안에서 DB·worker·엔진을 띄움 | agent child의 lifecycle이 engine lifecycle에 영향을 줌. 공유 DB인지 client별 embedded DB인지부터 명시해야 함 | agent 설정 하나로 시작, 별도 HTTP listener가 없을 수 있음 | agent 종료로 추출/승인/worker가 중단; 동시 Claude/Codex child가 migrations/locks/worker를 중복 실행; 일부 memory만 DB별로 갈라짐; hosted web agent는 사용자 Mac child를 띄우지 못함; MCP host를 관리자가 종료하면 background work의 안정성 계약이 깨짐 |
| B. 독립 로컬 설치 service+관리 CLI/UI만 제공, MCP 없음 | 지속 service와 하나의 DB; 외부 agent는 CLI 호출 또는 별도 HTTP API adapter 필요 | host별 transport 차이가 줄어든 operator 도구, 승인/backup/repair가 agent tool과 분리됨 | CLI를 모든 agent가 실행할 수 있는 것은 아님; hosted chat/native connector에 일반 CLI는 연결 수단이 아님; shell 허용·관리 credential 노출·host별 wrapper 비용; direct DB CLI가 권한체계를 우회하면 단일 권위가 깨짐 |
| C. 설치되는 하나의 engine/service+관리 CLI/UI, MCP는 thin adapter | canonical service/DB/operation log; local stdio/loopback adapter와 cloud HTTPS adapter는 같은 domain operation 호출 | lifecycle을 agent session과 분리, 일반 operator 도구와 다중 agent MCP 접속 공존, 같은 release/schema/domain의 두 배포 | installer·migration·worker·admin control·OAuth·compatibility 책임 증가; local thin shim이 정말 thin인지, 서비스 준비/인증/port discovery가 제품 UX의 핵심; controller를 같은 UID shell로 두면 승인 분리가 무너짐 |

제안: C를 기본 권고로 검토하되, 회사 정책상 지속 service/DB/모델/승인 boundary를 설치할 수 없는 경우 A를 은근한 대체로 약속하지 않는다. 허용되는 유한 실행 worker mode를 별도 명시하여 동일 domain semantics를 제공할 수 있는지 검증하고, 제공하지 못하면 해당 환경을 unsupported로 표시한다. 유한 실행 mode는 host가 자율적으로 startup/global hook을 바꾸는 면책이 아니다.

A에서도 하나의 기존 외부 service에 연결하는 thin child라면 실질적으로 C이며 위험이 줄어든다. stdio 자체가 나쁜 것이 아니라 DB/worker lifecycle을 stdio child마다 소유하는 것이 문제다. B도 일부 custom coding agents에 유효하지만 '어디서든 동일 연결' 보장은 아니다.

## 공통 엔진, 두 독립 배포

공통: memory 종류·scope, 승인된 capture writer/allowlist, 원문 provenance/retention, async extraction, lexical+dense recall, 근거를 갖춘 reflect, correction/supersede/retraction, outbox/worker idempotency+fencing, schema와 operation contract, audit와 export/import 포맷.

회사/고객 배포: customer마다 독립 DB·object store/백업·credential·agent home·권한 profile. offline profile은 사전 반입된 승인 모델/embedding/parser와 artifact만 사용하고 외부 fallback/telemetry/model download를 하지 않는다. local-only는 앱 설정이 아니라 model·agent·host·DNS·proxy·네트워크 egress boundary까지 묶은 배포 보장이다. 실제 회사/고객 정책을 대신 승인하지 않는다.

개인 cloud 배포: 개인 자료만, 본인 self-host VM/Compose 또는 managed PG+request-bound worker 구성. Remote HTTPS MCP + 실제 사용 agent의 auth onboarding 필요. cloud service가 회사 local DB를 읽거나 cloud backup에 고객 데이터를 올리지 않는다. reverse tunnel/VPN은 no-export 고객 데이터를 cloud agent에 전달하는 문제를 없애지 못한다.

같은 source/release를 두 곳에 배포하는 것이지 하나의 공용 DB로 회사·개인을 scope label만 나눠 합치지 않는다. software update와 memory corpus sync는 다르다. 허용되지 않은 sync/통합 export를 제품 default에 넣지 않는다.

### 동일하다고 약속할 것 / 약속하지 않을 것

- 동일 domain/API/schema 및 오류 의미; correction/forget의 write/read 경계; 낮은 신뢰도 AI 추출물을 directive·현재 코드의 권위로 승격하지 않음.
- 같은 모델·모델 revision·parser·data snapshot·설정일 때 normalized fixture의 결과 계약을 비교. worker scheduling/retry처럼 분산 실행 순서는 의미 단위로 비교한다.
- 다른 CPU/GPU·추출/embedding 모델·network·index를 쓰면 recall 순위·latency·가격·throughput의 동일성을 주장하지 않는다. 실제 임계값/품질 benchmark 전 '동일 효과'는 미검증.
- offline은 cloud 모델을 호출하지 않으므로 회사에서 전체 pipeline에 필요한 승인 local 모델/compute가 없으면 기능 동일성이 성립하지 않는다. 단순 capture/recall만 내놓고 전체 pipeline parity라고 표현하지 않는다.
- 상이한 deployment backend를 config로 숨겨도 운영이 같아지는 것은 아니다. 출시 초기에는 PG authority 하나를 common baseline으로 검토하고 storage/queue/graph provider를 소비자 없이 N개 추상화하지 않는다.

## engine의 읽기·쓰기 계약

1. Capture는 source allowlist/consent와 scope로 수집한다. MCP만 설치했다고 agent의 이전 native memories/full transcript를 읽을 수 있는 것이 아니다. host별 승인 hook/export/event ingestion adapter가 필요하다. Agent Flow installer가 그것을 자동 추가하지 않는다.
2. durable accepted operation과 pending extraction은 분리. PG의 하나의 transaction에서 operation/event/outbox를 기록; ack는 DB commit 후 반환. 원문 blob 외부저장일 때 업로드/commit 간 orphan/retry/expiry 계약이 필요하다. Cloud Run min instance나 응답 후 thread를 durability로 간주하지 않는다.
3. worker retries는 operation identity/digest, scope, schema/model generation, CAS/version, lease fencing으로 중복·stale publish를 막는다. 기억 source content hash만으로 dedup하면 서로 다른 권리/retention의 source를 합칠 수 있으므로 provenance identity 보존.
4. read는 accepted/queryable/corpus epoch와 pending/errors/coverage를 분리해 반환. 의미 검색이 빈 결과라고 '없음'을 증명하지 않는다. Korean/code exact identifier에 lexical+vector fallback; scope ACL은 DB-level authoritative filter와 query path 모두 enforce.
5. 자동 추출 event/claim은 untrusted evidence. 개인 context의 선택적 recall/reflect는 가능하지만 현재 규칙을 덮어쓰는 directive/team skill 승격은 사람의 현재 원문/근거와 기존 tracked PR/review/gate를 거친다. 자동 reflect는 memory 개선의 제안이며 무조건 재학습/오류 감소의 증거가 아님.
6. correction/forget은 source·derived claims·edges·summaries·embeddings·cache·index·queued work를 같은 deletion/revision boundary로 통제. 원문을 물리적으로 지워야 하는 요구가 있으면 immutable archive의 무조건 영구 보존과 충돌한다. tombstone/audit에는 삭제된 본문·PII 복제를 피함.
7. backup restore는 복원된 과거 DB만 믿지 않고 별도 신뢰 가능한 최신 deletion head와 화해하거나 fail closed. 새로 살아난 stale worker/connector가 철회된 source를 재수집하는 것도 차단. 실제 cloud restore/retention를 시험하기 전 forget 보장이라고 부르지 않음.

## agent-plane과 operator-plane

MCP 읽기/제안/정정 요청/forget 요청 같은 agent tools와, 정책 변경·scope 통합·export·실제 파괴 작업 승인·팀 directive 승격 같은 operator action을 구분한다. 모든 transport가 같은 domain authorization을 통과해야 하며 CLI가 DB를 직접 바꾸는 우회로가 없어야 한다. 승인 token/credential을 agent workspace/env/MCP result로 내보내지 않는다.

단순히 CLI 명령 이름을 approve로 만들거나 UI에서 버튼을 누르는 것은 인간 존재 증거가 아니다. agent shell과 operator가 같은 UID/credential/browser session 권한이면 local human approval을 꾸밀 수 있다. 필요한 보장은 별도 principal/OS 계정·VM·sandbox 또는 operation digest에 묶인 검증 가능한 human-presence/step-up boundary이다. 해당 boundary가 없는 배포는 human-approved mode를 주장하면 안 된다. locality/localhost/Origin 검사만으로 같은 UID malicious client를 차단한다고 주장하지 않는다.

Local network endpoint는 loopback으로 제한, Host/Origin/CSRF/DNS rebinding 검증, per-install credential/IPC peer checks, guest/customer별 identity·DB·agent home 분리. localhost 자체가 인증은 아니다. TCP port는 service discovery/credential binding으로 검증; agent child가 같은 port에 fake server를 띄울 수 있으므로 address만 믿지 않음.

Cloud endpoint는 TLS·resource-bound OAuth access token·issuer/audience/scope/PKCE·세션 credential storage/rotation 정책으로 접근. Cloud Run IAM OIDC ID-token은 service-to-service용이므로 사용자 MCP OAuth access-token과 자동 대체 가능하다고 하지 않음. hosting platform의 local config·connector availability·plan/SSO/write tools/network egress는 계정에서 직접 확인할 항목. MCP protocol 최신판과 host/SDK 실제 지원 범위도 분리.

## 패키지/설치 lifecycle의 전체 범위

독립 repo의 공개 core/service/MCP adapter/관리 CLI, pinned OCI image와 release manifest/compatibility matrix가 공통제품이다. 프레임워크·언어·상표·패키지 namespace는 아직 선택하지 않았고 생성하지 않았다. 회사 offline bundle과 개인 cloud deployment guide는 같은 release를 조합하는 두 배포 profile. installer가 있다면 보여주는 설치 diff/allowlist·전용 namespace·ownership metadata와 명시적 start/stop/status/doctor/export/backup/restore/update/rollback/uninstall 수명주기를 갖춘다.

- install은 install이고 host AGENTS/CLAUDE/native memory/MCP config의 자동 global rewrite가 아니다. 사용자가 고른 host와 scope만 원래 파일/marker ownership을 보존하여 변경; 관리 영역 밖 텍스트는 보존.
- service 시작/재시작 및 scheduled capture의 승인·목록·비활성화·삭제를 명시. 에이전트/terminal session 종료와 durable job의 관계를 문서화. 동시 adapter가 service를 중복 owner로 만들지 않음.
- '한 파일 설치'와 '한 command로 stack 설치'를 구별. PG·모델 weights/runtime·디스크·메모리·권한·고객 정책·Docker Desktop license 등 prerequisites를 숨기지 않음. Docker/Compose 금지 조직에는 공통 core에 붙는 승인 배포 경로만 지원; 의존성 없는 기능 동등 single binary라고 과장하지 않음.
- updater는 다운로드/공급망/승인 문제. offline artifact pin/signature/checksum/SBOM/취약점·모델 license 검토; auto internet update/원격 exec 없음. 개인 cloud도 pinned release와 migration 운영 동일.
- binary rollback ≠ schema rollback. forward/backward-compatible read 기간·migration lock·backup·restore·최신 deletion ledger 적용과 failure recovery를 실제 검증해야 함.
- uninstall은 program/config와 data purge를 분리. 기본 데이터 보존, credential/service/owned host config만 명시적으로 제거; 고객 memory/backup 삭제는 별도 실제 승인·retention 계약. installer log에 원문/secret을 넣지 않음.
- 공개 OSS license는 code에 적용. 고객 원문·개인 memory·호출 비용·모델 weights·Docker Desktop·배포된 모든 dependency/trademark까지 자동 승인하는 것이 아님. Agent Flow MIT 코드를 복사하면 고지 보존; 분리 제품은 일반적으로 MIT 또는 Apache-2.0 같은 permissive license를 검토할 수 있지만 회사 법무 검토를 대신하지 않음.

## Agent Flow 영향과 경계

- 기본 권고는 Agent Flow core 0줄 변경, installer asset에 memory service/model/data/worker/fixture를 ship하지 않음. 이는 의도한 통합 경계이지 author/reviewer behavior 영향 0의 증거가 아님.
- author가 opt-in host config로 MCP 접속하면 memory tool 결과/회상은 입력과 비용을 바꾼다. current AGENTS/skill/spec/source가 우선. author hook 자동 추가는 별도 승인 scope.
- isolated Claude/Codex reviewers에는 global user memory/MCP/native home/개인 credentials를 전달하지 않는다. 새 review의 직접 입력은 공개 PR와 이 제안뿐; 새 리뷰가 Agent Flow runner gate를 해결하지 않음.
- 일반 회사 knowledge와 개인 knowledge를 cloud에서 합칠지 선택하는 product는 이번 권고에 없다. 기본은 분리; 합치는 requirement는 고객/법적 승인과 별도 threat model이 없으면 지원하지 않음.

## 출시 전에 거짓으로 약속하면 안 되는 관측 항목

실제 두 agent 연결, session 종료/동시접속·재시작 후 작업 완료, offline 전체 pipeline egress 차단, scope 차단/같은 UID operator 위조, commit-ack crash/retry/fencing, schema update 실패/동시 migration, reinstall/uninstall ownership, correction/forget+backup restore+stale re-ingest, Korean/code recall와 full-trace baseline, 비용·지연·quality 평가. 이번 요청에서는 구현/설치/벤치마크가 아니므로 모두 출시 검증 항목이며 통과했다고 쓰지 않는다.

리뷰 질문: 제안 C가 과도한 제품 표면인가? A/B를 선택해야 하는 현실적인 환경은 무엇인가? 회사 설치 불가/승인 경계 없는 single-user 환경에서 요구를 유지할 수 있는가? 모든 병목을 config 추상화로 숨겼는가? 일반 memory correction/forget마다 강한 인간승인을 요구하면 사용가능성을 해치는가? standalone OSS 분리가 #334 core freeze를 지키면서도 사용자 요구를 실제 충족하는가?
