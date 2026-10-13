## 독립 OSS 제안 + 실제 Opus 5.5 / Codex 6.1 Sol xhigh 병렬 적대적 리뷰

**결론: 별도 OSS로 분리하는 방향을 권고한다. 다만 회사판/개인판을 두 엔진 fork로 만들지 말고, 하나의 공통 엔진을 두 독립 배포로 운영한다. MCP와 설치형은 양자택일이 아니다.**

- **제품 형태:** 설치되는 memory service가 DB·worker·정정/철회 권위를 소유하고, agent는 MCP로 접속하며 사람은 별도 관리 도구로 운영. 기본은 local HTTP / personal-cloud HTTPS, 필요한 소비자가 입증될 때만 thin stdio.
- **엔진 선택:** 처음부터 전부 재구현하기보다 Hindsight 기반 독립 OSS distribution을 우선 비교. 단, 내부 publication/fencing/삭제를 실제로 강제할 수 없으면 backend patch/fork가 필요하며 wrapper-only 보장은 하지 않음.
- **공유/분리:** source·release·domain/schema는 공유; 회사/고객과 개인의 corpus·인증·host/session·backup·반출 경계는 분리. 자동 고객-data sync는 만들지 않음.
- **한계:** 전체 자동 capture/extract/recall/reflect/correction/retraction은 유지하되, hosted host의 capture/auth/read-write 미지원이나 회사 설치·모델 금지는 명시적 unsupported 조건. 실제 memory 제품 구현·배포·계정 연결·품질/복구 검증을 완료했다고 주장하지 않음.

이 추가 분석은 #316의 [앞선 논문·영상·GitHub 조사](https://github.com/chonamdoo/agent-flow/issues/316#issuecomment-6105788769)에 **PR #334의 실제 변경, 독립 OSS 경계, 설치 lifecycle, MCP와 배포 방식 비교**를 더한 것이다. 조사 기준 2026-10-11. 공개 문서·고정 소스와 설계 판단을 구분한다. 메모리 제품 구현·설치·배포·사용자 계정의 연결·품질/복구 벤치마크는 수행하지 않았다.

### 1. 먼저 #334가 무엇을 했는지

**최신 상태 재확인(2026-10-11 06:07 UTC): #334는 MERGED다.** 최초 조회 후 추가된 head `5a9b6f6bf93913bb2a8504cada18756a3bc29bf3`가 05:59:35 UTC에 merge commit `ccbc6cc2621256c89d25ce94f7d50d7709d379aa`로 병합됐고, `phase-budget-accepted` 라벨도 현재 존재한다. 최신 diff는 같은 base `642d1792edf0b22bda2bb879ac65df145273dc19` 기준 6개 파일 +148/-36이다. 아래 native 두 리뷰의 고정 대상은 최초 head `a57c0c8a67df2814324e4e197dcd82faaff1c8b3`다. 새 head의 CLI 재리뷰/승인으로 바꾸어 주장하지 않는다.

최초 조회의 [고정 비교](https://github.com/chonamdoo/agent-flow/compare/642d1792edf0b22bda2bb879ac65df145273dc19...a57c0c8a67df2814324e4e197dcd82faaff1c8b3)는 당시 open·non-draft·unmerged, 6개 파일 +131/-31이었다. 게시 본문을 브라우저에서 확인하다 추가 커밋을 발견하여 [old→latest 변경](https://github.com/chonamdoo/agent-flow/compare/a57c0c8a67df2814324e4e197dcd82faaff1c8b3...5a9b6f6bf93913bb2a8504cada18756a3bc29bf3)과 [현재 PR](https://github.com/chonamdoo/agent-flow/pull/334)을 다시 읽고 이 댓글을 갱신했다. 추가 변경은 영문/한국어 TEAM-ADOPTION과 공통 skill 3개에 한정된다.

- 팀 규칙 승격은 **사용자가 승인한 별도 변경**으로만 제안하고 관련 없는 작업에 섞지 않는 기준을 명시했다. 독립 memory service도 자동으로 AGENTS/skill을 바꾸거나 다른 코드 작업에 규칙 승격을 끼워 넣어서는 안 된다.
- `.agent-flow/bootstrap/CLAUDE.md`는 참고 포인터일 뿐 세션 시작 때 자동 로드되지 않는다. 루트 `AGENTS.md` 옆의 루트 `CLAUDE.md`로 쓸 때 상대 `@AGENTS.md` import가 author에게 전달된다. 기존 legacy root는 일반 update가 다시 쓰지 않으므로 옛 과장 문구가 남을 수 있으며 최신 문서가 이를 정정한다.
- host 안내는 Claude Code·Codex·OMP로 명확해졌다. Gemini 등은 installed host skill 없이 generic adapter의 phase prompt를 따르며 Gemini/OMP는 reviewer pool에 추가되지 않는다.

**새 커밋과 merge에도 memory engine·DB·MCP·자동 capture·추출·주입·동기화는 추가되지 않았다.** 따라서 독립 OSS 권고는 유지하되, 최신 팀 규칙의 별도 사용자 승인 경계를 적용한다. PR 본문의 draft/라벨 미부착 및 old-head 검증 수치는 과거 보고이고 현재 API 상태와 구분한다. merge/라벨 존재를 아래 native 리뷰의 sealed gate 증거나 새 head의 모델 효과·QA/복구 검증으로 취급하지 않는다.

| 변경 | 실제 의미 | 구현하지 않은 것 |
|---|---|---|
| 공통 `code-generation-discipline` skill 2 bullets | 사용자 host memory는 선택적 참고, 현재 원문/코드/규칙으로 재확인, 유지 가치 있는 팀 규칙만 tracked PR/review/gate로 제안 | DB·추출·회상·동기화·자동 주입 |
| `lib/installer-shared.mjs` pointer 문자열/주석 | author의 `@AGENTS.md`는 유지, isolated reviewer도 같은 방식으로 읽는다는 과장을 정정 | reviewer scope/runner routing/sandbox 동작 변경 |
| 영문/한국어 `TEAM-ADOPTION.md` | root/legacy ownership, host memory와 팀 규칙, reviewer 플랫폼·전달/소비 한계 문서화 | 별도 memory service 설치 |
| 기존 pointer test의 docstring | 설명 정정, assertion은 그대로 | memory pipeline 동작/품질 테스트 |
| maintainer ledger | #333 architecture-lint 회귀와 알려진 공백 기록 | memory 기능 |

**따라서 #334에서 메모리 엔진을 “떼어내는” 것은 아니다.** 새 독립 제품을 만들거나 기존 OSS 엔진을 채택하는 별도 작업이다. 문서의 “별도 memory-analysis pipeline은 필요 없다”는 현재 Agent Flow의 host-memory 참고 정책을 설명하는 것이지, 사용자가 요청한 독립 제품을 전역 금지하는 근거가 아니다.

Agent Flow [identity/freeze policy](https://github.com/chonamdoo/agent-flow/blob/642d1792edf0b22bda2bb879ac65df145273dc19/docs/IDENTITY-AND-FREEZE-POLICY.md)는 장기 daemon·배포·운영·credential ownership을 core 밖에 둔다. **독립 OSS service가 자기 worker를 운영하고 Agent Flow author가 명시적으로 접속하면 이 경계를 유지할 수 있다.** Agent Flow installer/gate/reviewer home에 서비스를 몰래 넣는 통합은 다른 문제다.

최초 고정 head에 대한 4 focused passes, 회귀 37 passes+ownership exit75 두 subtest 실패, base 동일 실패, npm snapshot/8설치 관측과 byte budget은 **PR 작성자의 당시 보고**다. 이번에 재실행하지 않았다. 본문에는 Linux verified sandbox 부재로 `20261011-043042` reviewer run이 blocked였다는 보고가 여전히 남아 있다. 최신 PR의 실제 merge와 이 특정 run의 sealed approval·QA·handoff는 다른 주장이고, 아래 native 모델 설계 리뷰가 그 run을 완료한 것은 아니다.

### 2. MCP냐 설치형이냐: 서로 다른 축이다

[MCP architecture](https://modelcontextprotocol.io/specification/2026-07-28/architecture)와 [stdio lifecycle](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/stdio)에 따르면 MCP는 agent가 도구와 context에 접근하는 protocol이다. installer·CLI·daemon·OCI image는 설치와 실행 수명주기다. **“설치되는 메모리 제품이 MCP를 제공한다”는 조합이 가능하다. Local HTTP도 MCP다.**

| 안 | 장점 | 단점·영향 | 적절한 환경 |
|---|---|---|---|
| A. agent가 stdio child로 DB/worker까지 띄우는 올인원 MCP | 시작이 간단하고 별도 listener가 없을 수 있음 | session 종료/강제 kill, 복수 host의 중복 migration·worker, data-dir 충돌, accepted 작업의 복구·같은 UID 권한 문제 | 단일 사용자·제한된 lifecycle을 정직하게 명시하고 복구/동시성 계약을 검증한 설치. “stdio” 자체가 금지되는 것은 아님 |
| B. 로컬 service+관리 CLI/UI만, MCP 없음 | 운영/backup/승인 UX를 agent tool과 분리하기 쉬움 | hosted chat agent가 CLI를 실행할 수 없음; 각 host의 shell/API wrapper 필요; direct DB CLI는 auth 우회 위험 | 사내 전용 runner/일반 애플리케이션에서 shell/API 연동만 필요한 경우 |
| C. 공통 설치형 engine/service+관리 도구, MCP는 접속 adapter | agent session과 DB/worker lifecycle 분리; 다중 agent·local/cloud가 같은 domain operation 사용 | installer·migration·운영·auth·host compatibility의 책임 증가 | 회사/개인 공통 제품의 기본 방향. local HTTP 우선; 실제 stdio-only 소비자가 있을 때 thin shim 추가 |

A의 child가 DB/worker를 소유하지 않고 이미 설치된 service에만 연결하면 실질적으로 C다. **핵심은 transport 이름이 아니라 저장소·worker·승인의 권위와 수명주기를 누가 소유하는가**다. 현재 대상 host들이 HTTP를 지원하면 소비자 없는 stdio bridge와 별도 REST CRUD를 모두 만드는 것은 불필요한 유지관리 범위다.

### 3. “회사판/개인판”에서 공유하고 분리할 것

설계상 가능한 기본은 **하나의 OSS core/release/domain/schema, 두 독립 deployment profile**이다. 처음부터 엔진을 두 fork로 나눌 근거는 없다. 반대로 운영까지 완전히 같아야 한다는 약속은 하지 않는다.

| 항목 | 공통 계약 | 회사/외주 고객 로컬 | 개인 self-host cloud |
|---|---|---|---|
| 전체 pipeline | 승인 capture → durable ingest → 자동 extract/embed → scoped recall → evidence-grounded reflect → correction/retraction | 승인된 source/host adapter와 회사 허용 inference | 개인 source/adapter와 허용 provider |
| code/schema/API | 같은 release·migration·권한/정정/철회 의미 | 지원 OS/arch·PG/extension/model 범위를 고정 | 같은 호환 범위의 cloud release |
| 데이터/인증 | provenance·scope와 server-side authorization | 고객별 corpus·DB·token·home/session·backup | 개인 corpus와 별도 credential/backup; 고객 store 접근/동기화 없음 |
| 모델/egress | 명시적 provider/model revision, 금지 fallback 없음 | local 저장+승인 SaaS 사용 또는 strict offline 중 회사 정책에 맞는 profile | 개인이 승인한 cloud/local inference |
| agent 접속 | 같은 domain operation/receipt | loopback HTTP MCP 또는 thin stdio | TLS/remote HTTP MCP + 실제 host의 auth |
| worker/운영 | accepted와 queryable 분리, durable job/retry·revision fence | 설치된 service/supervisor 또는 검증된 유한 실행 mode | persistent VM worker, 또는 명시적으로 설계한 cloud worker |
| 관리/복구 | ownership 기반 update/uninstall·정정/철회·복원 계약 | local artifact 반입·backup/복구 직접 운영 | TLS/IdP/secret/망·DB·backup/복구 운영 |

**회사 정책을 추정해서 “클라우드 모델도 무조건 금지”라고 정하지 않는다.** 로컬 저장만 요구하면서 회사 SaaS 모델을 허용한다면 local DB+승인 provider로 전체 pipeline을 구성할 수 있다. 전송/처리도 금지라면 extractor/embed/rerank/reflect뿐 아니라 **회상 내용을 받는 host LLM까지** local/허용 사내 경로여야 한다. local memory가 고객 내용을 cloud Opus/Codex prompt로 넘기면 no-egress는 성립하지 않는다. 회사 SaaS 계약상 보호와 “전송 없음”은 다른 보장이다.

회사에서 service/DB 설치가 금지되거나 승인 모델·compute가 없으면 해당 topology/full functionality를 제공할 수 없다. stdio child에 몰래 daemon을 넣거나 reflect를 끈 뒤 동일 pipeline이라고 부르면 안 된다. 허용되는 유한 실행+복구 경로가 동일 domain 계약을 충족하는지 검증하거나 unsupported로 명시해야 한다.

같은 모델 revision·parser·data·policy의 contract parity와, 다른 모델/hardware/provider의 품질 비교를 분리한다. schema가 같다고 recall 순위·latency·가격·품질이 같아지지 않는다. 회사/개인 corpus sync는 software release update와 별개이며 기본 기능으로 넣지 않는다.

### 4. cloud에서도 어느 agent나 자동으로 된다는 보장은 없다

[MCP가 전체 대화를 보지 못한다는 architecture 계약](https://modelcontextprotocol.io/specification/2026-07-28/architecture) 때문에 **MCP 등록은 capture 완성의 증거가 아니다.** 승인된 hooks/export/event adapter와 다음 task의 실제 recall이 필요하다. 지원하지 않는 hosted surface를 수동 note 저장으로 대체하면서 원래 자동 pipeline 요구를 충족했다고 말하지 않는다.

| 실제 host | 문서상 경로 | 반드시 구분할 조건 |
|---|---|---|
| Claude Code local / 직접 운영 VM CLI | HTTP 또는 stdio MCP | 실행 host별 설정/auth, tool 권한·capture adapter·protocol 협상 |
| Anthropic-hosted Claude cloud | 단일 repo의 committed `.mcp.json`; 별도 활성 connector 경로 | Mac local/user config·hook/plugin이 자동 승계되지 않음. project MCP와 connector traffic은 같은 경로가 아님 |
| Codex local CLI/IDE/desktop의 Codex | host `config.toml` 기반 HTTP/stdio | local config/helper와 hosted 환경은 별개 |
| ChatGPT Web Plugins, 지원 계정 | custom remote server 등록→plugin 생성 경로 | 실제 plan/workspace/private read/write/OAuth/approval 조건. local Codex config를 읽는 것 아님 |
| Codex Cloud 새 task / legacy review | 별도 task 환경·network/secret·plugin 지원 범위 | curl/API 성공≠native MCP tool catalog 등록/사용 성공; legacy와 새 환경을 섞지 않음 |
| 직접 운영 cloud VM/Agent SDK | 본인이 HTTP/stdio·capture를 구성 | 가장 통제 가능하지만 agent 운영/보안·provider 비용도 본인 책임 |

출처: [Claude cloud](https://code.claude.com/docs/en/cloud-environments.md), [Claude MCP](https://code.claude.com/docs/en/mcp), [OpenAI MCP](https://learn.chatgpt.com/docs/extend/mcp), [Plugins](https://learn.chatgpt.com/docs/plugins), [custom server→plugin](https://developers.openai.com/plugins/build/plugins), [Codex Cloud environments](https://learn.chatgpt.com/docs/environments/cloud-environments).

특히 Claude cloud의 `Network=None`은 활성 connector·Anthropic API·GitHub proxy·network-secret 경로를 전부 막는 설정이 아니다. ChatGPT legacy developer-mode custom app의 plan/mobile/write 제한을 새 Plugins 전체에 일반화하지 않는다. public plugin submission은 별도 domain verification·OAuth·test account/scan 조건이며 private endpoint를 public directory에 올리는 것은 필수 제품 기능이 아니다.

MCP [2026-07-28 stable](https://blog.modelcontextprotocol.io/posts/2026-07-28/)는 stateless revision이고 2025 initialize/session 방식과 다르다. “latest spec 구현”만으로 설치 host/SDK의 호환성을 증명하지 않는다. [MCP OAuth access token](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization)과 [Cloud Run IAM OIDC ID token](https://docs.cloud.google.com/run/docs/authenticating/service-to-service)은 자동 호환되지 않는다. application OAuth ingress 또는 검증된 gateway를 설계해야 한다.

### 5. 엔진까지 새로 만들 것인가

| 선택 | 얻는 것 | 실제 추가 책임/거절 이유 |
|---|---|---|
| Hindsight 같은 기존 OSS core를 고정하여 사용, 필요한 backend patch/fork | retain/recall/reflect·PG·worker·MCP가 이미 공개된 구조. 기능을 모두 새로 쓰는 부담 감소 | 기본 noauth/cloud inference, bank ACL·worker recovery·derived correction·purge/restore를 제품 계약으로 검증해야 함. wrapper만으로 안 되는 불변식은 backend patch/upstream 유지 책임 |
| 새 PG 중심 core | 좁은 domain·승인·정정·철회 계약 직접 소유 | 추출/검색 품질·worker·auth·migration·export·restore·패키지·adapter 전체 구현/검증 책임. “PG+MCP면 끝” 아님 |
| vendor proprietary engine의 공개 MCP wrapper | client code/초기 운영 부담이 작음 | wrapper OSS≠engine OSS. strict local/full self-host 요구를 만족한다고 할 수 없음 |
| 처음부터 여러 memory/graph/queue/DB backend 지원 | 선택 폭 | 실제 두 소비자와 parity 근거 없는 추상화·지원 matrix·migration 비용. 초기 기본값으로 기각 |

기존 조사에서 [Hindsight 고정 MIT core](https://github.com/vectorize-io/hindsight/tree/a9eeed77f9bce99d8f97d39a30d3281747300824)가 가장 직접적인 재사용 후보다. [설치 문서](https://hindsight.vectorize.io/developer/installation)는 pg0를 production에 권하지 않고 external PG를 지원한다. external PG는 인터넷 DB가 아니라 **engine process 밖의 PG**이며 같은 회사 VM의 로컬 PG도 포함한다.

[현재 local MCP launcher](https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-api-slim/hindsight_api/mcp_local.py)는 HTTP API를 시작한다. [별도 Claude plugin stdio adapter](https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-integrations/claude-code/scripts/mcp_server.py)는 API를 호출한다. 이 둘을 혼동하지 않는다. 기본 OpenAI provider·초기 embedding download 때문에 “local 설치”가 default no-egress라는 말도 하지 않는다. [기본 tenant/key source](https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-api-slim/hindsight_api/extensions/builtin/tenant.py)의 bank routing/key는 principal-to-bank ACL과 구별해야 한다.

Graphiti는 temporal relation이 실제로 필요한 경우의 후보이고 group label≠ACL이며 별도 graph 운영이 생긴다. LangMem은 유용한 extraction/reflect primitives지만 완성된 durable/authenticated MCP 제품은 아니다. [archived Mem0 wrapper](https://github.com/mem0ai/mem0-mcp/tree/624024deacbbe1948572a968abdb9d9e93ded548)는 hosted API wrapper 사례이지 신규 엔진이 아니다. [Supermemory self-host binary](https://supermemory.ai/docs/self-hosting/overview)가 가능해도 backend source는 비공개라서 공개 MCP repo와 합쳐 full OSS engine이라고 부를 수 없다.

### 6. VM부터 시작할지, serverless부터 시작할지

개인 규모의 기본 비교 대상은 **한 VM/Compose + durable PG + 명시적인 worker**, 필요하면 managed PG다. 회사와 같은 worker 진입점을 재사용하기 쉽지만 VM/디스크/DB/backup/patch/TLS·인증을 직접 운영하며 한 VM은 HA가 아니다.

Cloud Run으로 가려면 [volatile filesystem과 runtime contract](https://docs.cloud.google.com/run/docs/container-contract), [request-based CPU](https://docs.cloud.google.com/run/docs/configuring/billing-settings)를 고려한다. embedded DB/응답 뒤 coroutine/min instance만으로 durable background extraction을 보장하지 않는다. Hindsight의 PG-polling worker가 Cloud Tasks push-handler로 자동 바뀌는 것도 아니다. Tasks를 추가하면 DB commit→enqueue gap·중복·순서·sweep 책임이 추가되므로 먼저 engine의 기존 queue/worker 계약을 재사용한다. scale-to-zero가 managed PG/model/backup의 비용까지 없애지는 않는다. 총액·지연 우위는 workload 실측 전 미확정이다.

### 7. 설치형 제품이 소유해야 하는 범위

- **명시적 lifecycle:** install/start/stop/status/doctor/update/backup/restore/uninstall. app package와 PG·모델 weights/runtime·OS/arch·권한·디스크/RAM을 구분하고 “의존성 없는 single binary”로 과장하지 않는다.
- **host 연결은 별도 opt-in:** source/수집 event/endpoint/host+scope/설정 diff를 공개. global AGENTS/MCP/hook 덮어쓰기·무승인 startup 등록 금지. update/uninstall은 소유한 entry만 변경하고 설치 후 사용자 편집을 보존. install/first run의 `npx @latest`/`uvx`/model download가 남으면 완성된 offline bundle이 아니다.
- **source/release 공개와 corpus 공개 분리:** memory core/service/schema/migration/worker/adapters·관리 경로를 실제 운영 가능한 OSS로 제공. 고객 원문·개인 memory·token·실제 backup·private endpoint config를 release/test corpus에 넣지 않음.
- **agent/operator 권위 분리:** 일반 source 범위 정정·철회는 허용된 data-plane 권한으로 수행하고, 정책변경·scope 통합·export·대량 파괴·팀 directive 승격 같은 고위험 operator action과 구분한다. 모든 정정에 강한 인간 승인을 강제하지 않는다. localhost·Origin·UI 버튼·approve CLI는 인간 존재/권한의 증거가 아니다. agent와 같은 UID/credential/browser/Docker socket이면 위조·우회 가능하다. 필요한 관리 승인은 별도 principal/OS·VM·sandbox 또는 digest-bound human-presence 경계를 갖추고, 없으면 human-approved 보장을 주장하지 않음. CLI도 같은 domain authorization을 통과하며 direct DB 우회를 두지 않음.
- **update≠복구:** artifact digest/서명/NOTICE/SBOM과 app-schema-PG-extension-model 호환 manifest, migration lock·backup·실패복구 필요. 이전 image가 서명됐다고 schema downgrade 가능한 것은 아니다. restore 후 조회를 열기 전에 독립 최신 deletion head를 적용하거나 fail closed. uninstall·OAuth disconnect·DB purge·backup purge도 별개.
- **OSS license≠고객/모델 권리:** 새 독자 core는 기업용 특허 조건이 명시된 [Apache-2.0](https://www.apache.org/licenses/LICENSE-2.0.txt)를 기본 검토할 수 있다. 단순 MIT도 가능하지만 upstream notices, 모델 weights/runtime, Docker Desktop, 회사/고객 IP·재배포 조건을 별도로 검토한다. license 선택으로 보안 인증/SLA/법적 면책을 얻는 것은 아니다.

운영 근거: [Compose startup/readiness](https://docs.docker.com/compose/how-tos/startup-order), [down과 volume 삭제](https://docs.docker.com/reference/cli/docker/compose/down/), [PG upgrade/downgrade 한계](https://www.postgresql.org/docs/18/pgupgrade.html), [managed PG extension 제한](https://docs.cloud.google.com/sql/docs/postgres/extensions), [HF offline/telemetry/update의 별도 범위](https://huggingface.co/docs/huggingface_hub/en/package_reference/environment_variables).

### 8. 변경 영향의 최종 경계

Agent Flow core 변경을 기본으로 요구하지 않는다. 하지만 **core 0줄≠author behavior 0**다. host MCP catalog·자동 capture/주입·recall token·반출·model 비용이 바뀐다. 그래서 서비스/모델/fixture를 기존 installer 배포자산에 혼입하지 않고 author profile의 명시적 opt-in으로 둔다. isolated Claude/Codex reviewers에는 사용자 home memory/MCP/개인 credential을 상속시키지 않으며 tracked team rule 승격은 기존 원문/근거·PR/review/gate를 유지한다.

실제 제품 채택 전에는 두 agent의 native capture→commit→추출→다음 task recall→reflect, Mac offline의 cloud 접근, 회사 허용 egress, session kill/재시작·동시 migration·응답 유실 retry·stale worker, cross-customer ACL/같은 UID operator 위조, host config ownership·update/uninstall, 정정/철회 후 derived/cache/spool·옛 backup restore, 한국어/code 검색과 held-out 후속 coding action·생애주기 비용을 관측해야 한다. 이 항목들은 **이번에 통과한 테스트가 아니라 출시 수용 기준**이다.

### 9. 실제 Opus 5.5 / Codex 6.1 Sol xhigh 병렬 적대적 리뷰

서브에이전트를 동시 실행하고 **각 실행 담당자가 해당 native CLI를 실제 호출**했다. 실행 담당자의 기본 모델에 이름만 붙여 결과를 대체한 것이 아니다. 두 모델은 위 고정 PR diff·제안·공식 source 조사로 구성한 **동일한 전체 입력 180,322 bytes**를 받고, 상대방의 리뷰를 보지 않았다. 도구/별도 web research 없이 packet을 공격한 설계 리뷰다.

| 실제 모델 | CLI와 설정 | 관찰한 native 결과 |
|---|---|---|
| Claude Opus 5.5 | Claude CLI `2.1.296`, `--model claude-opus-5-5 --effort xhigh`; empty cwd·safe-mode·tools 없음·strict empty MCP·no session persistence | exit0, JSON success/is_error=false, `modelUsage` canonical key=`claude-opus-5-5` |
| Codex GPT-6.1-Sol | Codex CLI `0.162.1`, `--model gpt-6.1-sol -c model_reasoning_effort="xhigh"`; empty cwd·auth-only isolated CODEX_HOME·ignore config/rules·ephemeral·read-only | exit0, native runtime banner=`gpt-6.1-sol / openai / xhigh`, 외부 명령/도구 호출 marker 관측 없음 |

성공 실행 중첩은 **2026-10-11 05:46:41.978–05:49:22.900 UTC, 160.922초**였다. 두 output hash를 다시 계산하고, Opus JSON의 원래 result와 저장한 리뷰 텍스트의 byte-equivalent 문자열 일치도 확인했다.

증거의 한계도 구분한다. Opus의 server-resolved effort는 반환되지 않아 CLI에 `xhigh`를 전달한 것 이상으로 attestation할 수 없다. Sol의 model/provider/effort는 native runtime banner 관찰이며 숨은 provider-side attestation은 아니다. 첫 Opus 실행은 실행 담당자가 불필요한 HOME 격리를 추가해 인증실패했으므로 리뷰로 계상하지 않고 별도 실패 기록으로 보존했다. 원래 인증 환경으로 정정한 성공 실행만 위 표에 포함했다. native CLI는 사용자 상태 파일(`~/.claude.json`) 메타데이터를 갱신했으며 내용/Keychain 불변까지 검사하거나 주장하지 않는다. credentials·세션 UUID·raw stderr/JSON은 이 댓글에 게시하지 않는다. 로그인·설정편집·설치·모델 fallback 명령은 사용하지 않았다.

**이 리뷰는 새 제안의 적대적 검토이지 #334의 Agent Flow run/gate approval이 아니다.**

#### 9.1 두 리뷰의 주요 반례와 채택 판단

아래 severity/ID는 각각 native 리뷰의 표기다. **구현이 없는 새 제품의 위험·수용 조건**이며 #334에서 공격에 성공한 취약점 목록이 아니다. 모든 관측 기준은 아직 제품에서 미실행이다.

| Native findings | 실제로 공격한 지점 | 통합 판단·수용 조건 |
|---|---|---|
| **Opus O1 P0·O7 P1 / Sol C2 P1** | 회사 작업의 같은 UID/global catalog에 개인 endpoint가 있으면 정상 write로 고객 원문이 개인 cloud/backup에 전송. local DB도 cloud host prompt까지 포함한 no-export 보장 아님 | 분리 수용. 회사/고객·개인의 home/session/token/DB/backup/egress를 별도로 강제. 회사 정책은 **local 저장+approved egress / no-external-egress·완전 air-gap / prerequisites 부족으로 unsupported**를 구분. installer profile marker만으로 보안 경계를 증명하지 않음 |
| **Opus O2 P1 / Sol C1 P1** | catalog는 연결됐지만 capture가 없거나 다음 task가 recall을 안 해 자동 loop 미완성. curl/IAM 통과와 native MCP/OAuth 사용도 다른 관측 | host×surface×version/plan별 capture trigger·recall/auth·coverage/watermark를 지원 단위로 고정. **사후 export/import 자체는 자동이 아님**; 승인된 event/schedule이 실제 자동 실행해야 자동 capture라고 표시. 모델이 가끔 retain하는 경로와 수동 import는 따로 표시 |
| **Opus O4 P1 / Sol C3 P1** | 같은 UID/browser/Compose.env의 approve CLI·direct PG·fake loopback endpoint로 operator 권위 위조 | CLI/UI는 service API client, DB credential 없음. 모든 transport가 같은 auth/scope 통과. 일반 scoped correction/retraction과 high-risk export/정책변경/scope병합/대량purge/directive승격 분리. **soft tombstone/undo는 물리 purge나 법적 삭제의 대체물이 아님** |
| **Sol C4 P1** | wrapper가 revision을 사전 확인해도 correction 뒤 engine 내부 stale retain/reflect commit이 나중에 게시 | Hindsight 재사용은 조건부. **publication/fencing/deletion을 실제 commit/read 지점에서 강제**할 수 있어야 함. gateway-only 보장 기각. 필요한 최소 backend patch/fork를 비교하고, 비용이 크면 새 PG core를 선택. 독립 원장 두 개를 권위로 두지 않음 |
| **Opus O5 P1 / Sol C5 P1** | DB와 old deletion ledger를 함께 restore, stale worker 완료, 이전 spool 재수집으로 철회 자료 부활 | 최신 deletion authority는 DB rollback/그 backup과 독립적으로 복구 가능. 최신성 확인 불가면 read fail closed. stable source identity·lineage·revision·operation digest로 raw/derived/cache/job/read/publish 경계를 통제. 해시만 붙여 해결됐다고 하지 않음. host/native/provider copy 삭제는 별도 범위 |
| **Opus O6 P1 / Sol C6 P2** | global hook 상속·tracked `.mcp.json`이 다른 사용자/cloud/reviewer에 전달, uninstall 전체 backup 복원으로 사용자 후속 편집 소실 | 기본 service-only 설치+host integration 별도 opt-in. dedicated/untracked local profile 기본, team-tracked 설정은 별도 공동 승인. owned entry/current-value 조건으로 update/remove. core 0줄≠author/reviewer 입력 영향0 |
| **Opus O3 P1 / Sol C7 P2** | tokenizer/PG extension/model dimension/revision 차이로 한국어·코드 lexical recall parity 깨짐 | 첫 baseline은 공통 release·PG/extension을 맞춘 local/cloud VM stack. managed PG는 **호환 extension/검색 fixture를 확인한 경우**만 지원하며 원천 불가라고 단정하지 않음. semantic contract와 출력·순위·품질 parity 분리 |
| **Opus O8 P2 / Sol C8 P2** | Run 응답 후 worker 중단·volatile DB·IAM/OAuth·enqueue gap·replica migration·image만 rollback | 개인 cloud 기본은 persistent VM/Compose+durable PG+실제 engine worker. 외부 IdP 재사용·migration one-shot ownership. Run은 real worker/reconcile/compatibility 경계 검증 후 별도 profile. 여러 cloud runtime과 자체 OAuth AS를 처음부터 구현하지 않음 |

#### 9.2 모델 간 차이와 최강 반론

- **Opus:** 새 memory 엔진 전부를 다시 쓰기보다 **Hindsight 기반 독립 OSS distribution**(installer·배포 profile·capture·접근경계·필요한 backend patch)을 더 강하게 권고했다. public OSS의 호환/보안 대응 책임부터 커지는 점과, 회사에서 상주 service가 금지될 수 있다는 반례도 제시했다.
- **Sol:** 재사용의 핵심 위험을 **wrapper 바깥 engine 내부 commit 권한**으로 좁혔다. 정확한 host 자동화 지원이 없으면 installer/OAuth/cloud topology만 커지는 것이 C의 가장 강한 반론이라고 봤다. managed PG를 조건부 선택으로 남겼고, A/B도 실제 제약에 맞으면 유효하다고 했다.
- **통합 판단:** C를 **local HTTP 우선의 C′**로 좁혀 채택한다. 엔진은 Hindsight 재사용을 우선 비교하되 ACL·fencing·철회·검색/복원을 제품이 실제 강제할 수 있어야 한다. 불변식을 wrapper-only로 못 지키면 backend patch/fork가 필요하다. fork 유지비가 재구현보다 크다는 근거가 생길 때 새 PG core로 전환하며, 두 엔진을 처음부터 동시 지원하지 않는다.
- **A를 일괄 금지하지 않는다.** 회사가 session subprocess만 허용한다면 같은 engine/PG·exclusive owner·durable pending queue·다음 session catch-up을 검증한 유한 실행 profile은 가능하다. “session 중에만 진행”이라는 운영 차이를 명시한다. session 종료 뒤 처리·복수 host 공유·Mac 없는 cloud 접근의 기본안은 아니다.
- **B도 일괄 금지하지 않는다.** 회사가 MCP를 금지하고 승인된 SDK/CLI/API capture·recall integration을 갖춘 경우 전체 pipeline을 운영할 수 있다. 그러나 일반 CLI 설치만으로 hosted chat 연결까지 된다고 하지 않는다.
- 공개 source를 먼저 내는 것 자체를 금지하지 않는다. 다만 공개 repo/registry 등록과 **production-ready·모든 host 지원** 표시는 별개다. Opus의 “비공개 운영검증 후 공개”는 유지관리상의 반론이며 사용자 요구를 임의로 비공개 제품으로 바꾸는 결론으로 채택하지 않았다.

#### 9.3 #334 PR의 Standards와 Spec — 별도 축

| 축 | Opus 신규 리뷰 | Sol 신규 리뷰 | 근거에 따른 판정 |
|---|---|---|---|
| **Standards** | 제공 diff의 hard violation을 찾지 못함. docs범위·정본 drift·byte 수용·draft 표현·#333 ledger 별도 PR를 judgement로 제안 | hard violation을 찾지 못함. 소비자 없는 stdio/vendor abstraction은 Speculative Generality 후보, transport/권한 경계인 adapter를 무조건 Middle Man으로 보지 않음 | hard violation 없음이라는 관찰을 approval로 바꾸지 않음. 소비자 없는 표면은 추가하지 않음. **ledger 분리 제안은 미채택**: 아래 고정 maintainer 정책이 다음 작업 PR에 누락 merged PR 기록을 보충하도록 요구 |
| **Spec** | host-memory 참고/원문 재확인/tracked teamrule/설치·reviewer 설명이라는 좁은 spec에는 부합. “No separate pipeline” 범위 한정과 shared-company memory의 별도 의미를 지적 | 좁은 spec에 부합. 새 runtime 부재는 원 spec 누락 아님. 실제 pointer bytes/skill 지침 영향과 PR 보고·실행 증거를 구분 | 이 두 판정은 고정 `a57c0c8` 기준이다. 새 `5a9b6f6`의 별도 사용자 승인·host/pointer 정정을 추가 확인했으나 두 모델이 재리뷰했다고 하지 않는다. 최신 merge/phase-budget 라벨은 §1에 갱신; #334를 새제품 구현이나 이 native 리뷰의 sealed approval로 확대하지 않음 |

Opus의 ledger judgement는 packet에 main 정책 원문이 없는 상태에서 나온 의견이다. 부모가 이후 [고정 `maintainer/verification-policy.md`의 회귀 대조/design3](https://github.com/chonamdoo/agent-flow/blob/642d1792edf0b22bda2bb879ac65df145273dc19/maintainer/verification-policy.md#회귀-대조)를 읽어 **누락된 merged PR은 다음 작업 design에서 보충해 그 작업 PR에 포함**한다는 기준을 확인했다. 따라서 #333 원장 기록을 #334에서 빼는 결론을 내리지 않는다. 원 native 리뷰 텍스트는 수정하지 않았다. 이번 요청으로 PR 본문/코드는 편집하지 않는다.

### 10. 최종 권고와 명확한 불가능 조건

**별도 OSS는 좋은 방향이고, 기본 제품 형태는 “설치되는 공통 memory service + 필요한 MCP 연결 + 별도 operator 도구”다.** #334에 장기 runtime을 끼워 넣는 대신 독립 repo/release로 둔다. 회사 로컬과 개인 cloud는 **같은 engine을 두 곳에 배포**하고 corpus/identity/host/backup은 나눈다. 두 engine fork가 필요하다는 근거는 없고, 두 deployment/egress/host adapter·운영 절차는 반드시 필요하다.

처음부터 새 엔진·여러 storage backend·관리형 SaaS·Cloud Run·모든 host plugin·필수 stdio shim을 한꺼번에 약속하지 않는다. **Hindsight 기반 공통 distribution + local HTTP / 개인 VM remote HTTPS**를 우선 대상으로 삼아 전체 자동 pipeline과 불변식의 소유권을 검증한다. model weights/runtime·OS/arch별 artifact는 같은 release의 명시적 profile이지 byte-identical binary 약속이 아니다.

아래는 단순한 환경 설정 차이가 아니라 요구를 만족할 수 없는 조건이다.

1. 회사/고객 자료 반출이 금지인데 그 내용을 읽어야 하는 개인 cloud agent를 사용: 승인된 별도 경계 없이는 양립 불가. VPN/tunnel/local DB로 이름만 바꿔 해결되지 않는다.
2. 회사가 필요한 DB/service/모델·compute를 금지하고, 동일 domain을 충족하는 승인 유한 실행 대안도 없음: full pipeline 지원 불가. manual-only/reflect-off로 몰래 축소하지 않는다.
3. hosted host가 승인된 capture·native read/write/auth·다음 task recall 경로를 제공하지 않음: 그 surface의 자동 pipeline은 미지원. 직접 운영 VM/SDK는 별도 실행 표면이며 모든 hosted 제품 지원의 증거가 아니다.
4. agent와 operator의 실제 권한이 같은데 인간 승인·고객 경계·DB 직접 접근 차단을 보장한다고 주장: 해당 강한 보장 불가. plain profile/버튼/marker로 해결되지 않는다.
5. 최신 철회 상태를 old backup과 독립적으로 회복/확인하지 못함: forget-restore 보장 불가, 조회를 fail closed해야 한다.

이 조건을 숨기지 않으면 **코드는 공통으로, 회사·개인 데이터와 운영은 분리해서** 요구를 충족하는 제품을 설계할 수 있다. 이번 결과는 그 설계·영향·반례 분석의 완료이지 실제 memory 제품 완성/연결/운영 인증은 아니다.

### 11. 로컬에 보존한 재검증 자료

사용자 작업 디렉터리의 `research/`에 새 조사·고정 PR source·동일 reviewer packet·unmodified native 리뷰·각 실행 evidence·판정표·parallel proof를 보존했다. 고객/개인 corpus나 실제 memory server credential은 입력/게시물에 넣지 않았다.

- 동일 입력: `distribution-review-input.ko.md`, SHA256 `36d909bc0a8a024b958b76edb23bf7d62c77b1c780e99216a0835aa4d24455a5`.
- Opus 원문: `distribution-review-opus-5.5-xhigh.ko.md`, SHA256 `9fe356983dd512a8817d90dec631cf913123c9af2d98fb86d81e07748c10aa0a`.
- Sol 원문: `distribution-review-codex-6.1-sol-xhigh.ko.md`, SHA256 `44328e620c5fef598c5205cb51a48aa5aab6685626e3d5853134d3b78a097b39`.
- 독립 실제 실행 proof: `distribution-native-parallel-proof.json`; native output hash/Opus JSON result 일치, 두 성공 실행 overlap 확인.
- 추가 조사: `distribution-local-sources.ko.md`, `distribution-cloud-sources.ko.md`; 고정 PR: `distribution-pr334-source.json`; 원문을 변경하지 않은 채 반례의 수용/부분수용·미채택 근거는 `distribution-disposition-opus.ko.md`, `distribution-disposition-sol.ko.md`.
