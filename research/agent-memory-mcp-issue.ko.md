> **대상 저장소: `chonamdoo/agent-memory-mcp`.** 회사/외주 고객의 로컬 설치와 개인 self-host 클라우드를 지원하는 독립 메모리 제품의 설계·자료 조사·적대적 리뷰를 정리한다. Agent Flow core에 장기 memory runtime을 추가하는 변경이 아니다.
>
> 배경 자료: [Agent Flow 원 논의 #316](https://github.com/chonamdoo/agent-flow/issues/316), [관련 PR #334](https://github.com/chonamdoo/agent-flow/pull/334), [원 분석 댓글](https://github.com/chonamdoo/agent-flow/issues/316#issuecomment-6106087372). 이 문서의 Agent Flow 이슈/PR 참조는 저장소를 명시했다.
>
> 저장소는 게시 시점에 **private**다. 아래 OSS는 목표 제품/배포 방식을 뜻하며, 이번 게시로 저장소 공개 범위나 라이선스·제품 구현 상태를 바꾸지는 않는다.

## 독립 OSS 제안 + 실제 Opus 5.5 / Codex 6.1 Sol xhigh 병렬 적대적 리뷰

**결론: 별도 OSS로 분리하는 방향을 권고한다. 다만 회사판/개인판을 두 엔진 fork로 만들지 말고, 하나의 공통 엔진을 두 독립 배포로 운영한다. MCP와 설치형은 양자택일이 아니다.**

- **제품 형태:** 설치되는 memory service가 DB·worker·정정/철회 권위를 소유하고, agent는 MCP로 접속하며 사람은 별도 관리 도구로 운영. 기본은 local HTTP / personal-cloud HTTPS, 필요한 소비자가 입증될 때만 thin stdio.
- **엔진 선택:** Hindsight는 우선 검증할 재사용 후보이지 선정 완료가 아님. 영상형 signal·episode·candidate·feedback와 engine 내부 publication/fencing/삭제의 소유권을 확인한 뒤 기존 엔진 재사용과 좁은 단일-backend core를 같은 계약으로 비교. wrapper-only 보장은 하지 않음.
- **공유/분리:** source·release·domain/schema는 공유; 회사/고객과 개인의 corpus·인증·host/session·backup·반출 경계는 분리. 자동 고객-data sync는 만들지 않음.
- **한계:** 전체 자동 capture/extract/recall/reflect/correction/retraction은 유지하되, hosted host의 capture/auth/read-write 미지원이나 회사 설치·모델 금지는 명시적 unsupported 조건. 실제 memory 제품 구현·배포·계정 연결·품질/복구 검증을 완료했다고 주장하지 않음.

**새 영상 원문 재분석·별도 실제 병렬 리뷰:** 아래 §12–13에 `mAKUL12h1n8` 전체 자막, 시연/자기보고/후속 아이디어 구분, 두 모델의 새 반례·장단점·영향 범위를 추가했다. §9의 기존 리뷰를 영상이나 최신 PR의 새 승인으로 재사용하지 않았다.

이 추가 분석은 chonamdoo/agent-flow#316의 [앞선 논문·영상·GitHub 조사](https://github.com/chonamdoo/agent-flow/issues/316#issuecomment-6105788769)에 **PR chonamdoo/agent-flow#334의 실제 변경, 독립 OSS 경계, 설치 lifecycle, MCP와 배포 방식 비교**를 더한 것이다. 조사 기준 2026-10-11. 공개 문서·고정 소스와 설계 판단을 구분한다. 메모리 제품 구현·설치·배포·사용자 계정의 연결·품질/복구 벤치마크는 수행하지 않았다.

### 1. 먼저 chonamdoo/agent-flow#334가 무엇을 했는지

**최신 상태 재확인(2026-10-11 06:07 UTC): chonamdoo/agent-flow#334는 MERGED다.** 최초 조회 후 추가된 head `5a9b6f6bf93913bb2a8504cada18756a3bc29bf3`가 05:59:35 UTC에 merge commit `ccbc6cc2621256c89d25ce94f7d50d7709d379aa`로 병합됐고, `phase-budget-accepted` 라벨도 현재 존재한다. 최신 diff는 같은 base `642d1792edf0b22bda2bb879ac65df145273dc19` 기준 6개 파일 +148/-36이다. 아래 native 두 리뷰의 고정 대상은 최초 head `a57c0c8a67df2814324e4e197dcd82faaff1c8b3`다. 새 head의 CLI 재리뷰/승인으로 바꾸어 주장하지 않는다.

최초 조회의 [고정 비교](https://github.com/chonamdoo/agent-flow/compare/642d1792edf0b22bda2bb879ac65df145273dc19...a57c0c8a67df2814324e4e197dcd82faaff1c8b3)는 당시 open·non-draft·unmerged, 6개 파일 +131/-31이었다. 게시 본문을 브라우저에서 확인하다 추가 커밋을 발견하여 [old→latest 변경](https://github.com/chonamdoo/agent-flow/compare/a57c0c8a67df2814324e4e197dcd82faaff1c8b3...5a9b6f6bf93913bb2a8504cada18756a3bc29bf3)과 [현재 PR](https://github.com/chonamdoo/agent-flow/pull/334)을 다시 읽고 원 게시 댓글을 갱신했다. 추가 변경은 영문/한국어 TEAM-ADOPTION과 공통 skill 3개에 한정된다.

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
| maintainer ledger | chonamdoo/agent-flow#333 architecture-lint 회귀와 알려진 공백 기록 | memory 기능 |

**따라서 chonamdoo/agent-flow#334에서 메모리 엔진을 “떼어내는” 것은 아니다.** 새 독립 제품을 만들거나 기존 OSS 엔진을 채택하는 별도 작업이다. 문서의 “별도 memory-analysis pipeline은 필요 없다”는 현재 Agent Flow의 host-memory 참고 정책을 설명하는 것이지, 사용자가 요청한 독립 제품을 전역 금지하는 근거가 아니다.

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

증거의 한계도 구분한다. Opus의 server-resolved effort는 반환되지 않아 CLI에 `xhigh`를 전달한 것 이상으로 attestation할 수 없다. Sol의 model/provider/effort는 native runtime banner 관찰이며 숨은 provider-side attestation은 아니다. 첫 Opus 실행은 실행 담당자가 불필요한 HOME 격리를 추가해 인증실패했으므로 리뷰로 계상하지 않고 별도 실패 기록으로 보존했다. 원래 인증 환경으로 정정한 성공 실행만 위 표에 포함했다. native CLI는 사용자 상태 파일(`~/.claude.json`) 메타데이터를 갱신했으며 내용/Keychain 불변까지 검사하거나 주장하지 않는다. credentials·세션 UUID·raw stderr/JSON은 이 이슈에 게시하지 않는다. 로그인·설정편집·설치·모델 fallback 명령은 사용하지 않았다.

**이 리뷰는 새 제안의 적대적 검토이지 chonamdoo/agent-flow#334의 Agent Flow run/gate approval이 아니다.**

#### 9.1 두 리뷰의 주요 반례와 채택 판단

아래 severity/ID는 각각 native 리뷰의 표기다. **구현이 없는 새 제품의 위험·수용 조건**이며 chonamdoo/agent-flow#334에서 공격에 성공한 취약점 목록이 아니다. 모든 관측 기준은 아직 제품에서 미실행이다.

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

#### 9.3 chonamdoo/agent-flow#334 PR의 Standards와 Spec — 별도 축

| 축 | Opus 신규 리뷰 | Sol 신규 리뷰 | 근거에 따른 판정 |
|---|---|---|---|
| **Standards** | 제공 diff의 hard violation을 찾지 못함. docs범위·정본 drift·byte 수용·draft 표현·chonamdoo/agent-flow#333 ledger 별도 PR를 judgement로 제안 | hard violation을 찾지 못함. 소비자 없는 stdio/vendor abstraction은 Speculative Generality 후보, transport/권한 경계인 adapter를 무조건 Middle Man으로 보지 않음 | hard violation 없음이라는 관찰을 approval로 바꾸지 않음. 소비자 없는 표면은 추가하지 않음. **ledger 분리 제안은 미채택**: 아래 고정 maintainer 정책이 다음 작업 PR에 누락 merged PR 기록을 보충하도록 요구 |
| **Spec** | host-memory 참고/원문 재확인/tracked teamrule/설치·reviewer 설명이라는 좁은 spec에는 부합. “No separate pipeline” 범위 한정과 shared-company memory의 별도 의미를 지적 | 좁은 spec에 부합. 새 runtime 부재는 원 spec 누락 아님. 실제 pointer bytes/skill 지침 영향과 PR 보고·실행 증거를 구분 | 이 두 판정은 고정 `a57c0c8` 기준이다. 새 `5a9b6f6`의 별도 사용자 승인·host/pointer 정정을 추가 확인했으나 두 모델이 재리뷰했다고 하지 않는다. 최신 merge/phase-budget 라벨은 §1에 갱신; chonamdoo/agent-flow#334를 새제품 구현이나 이 native 리뷰의 sealed approval로 확대하지 않음 |

Opus의 ledger judgement는 packet에 main 정책 원문이 없는 상태에서 나온 의견이다. 부모가 이후 [고정 `maintainer/verification-policy.md`의 회귀 대조/design3](https://github.com/chonamdoo/agent-flow/blob/642d1792edf0b22bda2bb879ac65df145273dc19/maintainer/verification-policy.md#회귀-대조)를 읽어 **누락된 merged PR은 다음 작업 design에서 보충해 그 작업 PR에 포함**한다는 기준을 확인했다. 따라서 chonamdoo/agent-flow#333 원장 기록을 chonamdoo/agent-flow#334에서 빼는 결론을 내리지 않는다. 원 native 리뷰 텍스트는 수정하지 않았다. 이번 요청으로 PR 본문/코드는 편집하지 않는다.

### 10. 최종 권고와 명확한 불가능 조건

**별도 OSS는 좋은 방향이고, 기본 제품 형태는 “설치되는 공통 memory service + 필요한 MCP 연결 + 별도 operator 도구”다.** chonamdoo/agent-flow#334에 장기 runtime을 끼워 넣는 대신 독립 repo/release로 둔다. 회사 로컬과 개인 cloud는 **같은 engine을 두 곳에 배포**하고 corpus/identity/host/backup은 나눈다. 두 engine fork가 필요하다는 근거는 없고, 두 deployment/egress/host adapter·운영 절차는 반드시 필요하다.

처음부터 새 엔진·여러 storage backend·관리형 SaaS·Cloud Run·모든 host plugin·필수 stdio shim을 한꺼번에 약속하지 않는다. **local HTTP / 개인 VM remote HTTPS**를 우선 지원 표면으로 삼고, Hindsight 재사용 후보와 좁은 단일-backend core의 전체 자동 pipeline·출처·승인·삭제 계약을 같은 spike로 검증한 뒤 엔진을 선정한다. model weights/runtime·OS/arch별 artifact는 같은 release의 명시적 profile이지 byte-identical binary 약속이 아니다. 새 영상에 따른 책임 범위와 재사용 조건은 §12–13에 정리했다.

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

### 12. 새 영상 원문 재분석 — 이전과 동일 잣대

대상: [Why AI Coding Agents Need a Memory Pipeline — Boundary](https://www.youtube.com/watch?v=mAKUL12h1n8), [사용자 지정 08:20](https://www.youtube.com/watch?v=mAKUL12h1n8&t=500s). 조사일 2026-10-11. **특정 기존 앱의 코드그래프 재사용·최소 DB 구성으로 연결한 해석은 제외한다.** 영상 자체의 trace-derived code map은 별개의 설계 논점이다.

#### 12.1 원문 확보·기존 자료 포함 범위

- 로그인/cookie 없이 yt-dlp로 YouTube **자동 영어 en-orig JSON3를 새로 다운로드**했다. metadata는 Boundary, upload `20261009`, duration 3,214초다. 공식 episode 폴더의 `2026-10-06`을 업로드 날짜로 쓰지 않는다.
- raw JSON3 **1,102,804 bytes**, SHA256 `a12be7a5b4cd8916e14ab0d027515e2f51ee915a5370b19f45c75edc8553b734`. text cue 1,511개, 첫 시점 00:00:00.160, 마지막 00:53:33.599. 새 timed transcript 1–1515행 **전체를 읽었다**.
- 새 자막과 제공된 cached raw JSON3의 정규화된 전체 text가 일치했다. 제공 plain transcript도 metadata 6행을 제외한 본문이 일치했다. **원문이 다른 것이 아니라 특정 프로젝트에 대입한 분석이 잘못된 것이다.** 기존 한국어 분석을 사실로 전제하지 않고 원문/공식 자료에서 다시 판단했다.
- cached MP4에 실제 ffprobe 실행: 3,213.914초, 286,685,607 bytes, AV1 1920×1080/24fps·Opus. **500초와2,325초 프레임을 새로 decode하여 직접 확인**했다. 08:20에는 코드영역별 `Where to look`/`Rules`/`Language facts`와 session/people 집계, 38:45에는 Jev·`GPT-6 Sol`·`Opus 5.5` stage 및 BAML Query가 보인다. 화면 model label은 provider-resolved model 증명과 다르다.
- header는 **1,040 sessions / 30,963 messages / 9 people / 2026-02-18–2026-06-18**. 화자의 '한 주' 및 세션당 2 cents와 동일 분모로 단정하지 않는다.
- **이전 §9 native 리뷰에 제공된 9개 Downloads 자료가 모두 들어갔다고 주장하지 않는다.** 이번 새 리뷰에는 새로 받은 전체 자막, 기존 verified-claims의9개 원문 locator 교차 확인, 재분석 및 공식 문서/고정 코드 검증을 포함한8개 파일을 동일 입력으로 전달했다. 9개 한국어 자료 전문을 전부 다시 전달한 것은 아니다. locator의 자막 일치는 발언 존재 확인이지 발언의 사실성/제품 성능 검증이 아니다.
- 새 video 파일 다운로드·전 프레임 재생/수동 재전사·시연 pipeline/Jev API/메모리 제품의 품질·복구 실행은 하지 않았다. **아래 §13의 실제 두 native 모델 리뷰 실행은 별도이며 성공했다.**

#### 12.2 실제 시연·자기보고·후속 아이디어 구분

| 원문 | 확인한 내용·상태 | 같은 잣대의 판정 |
|---|---|---|
| [04:49–06:38](https://www.youtube.com/watch?v=mAKUL12h1n8&t=289s) | user/assistant만 남기고 tool call을 뺀 Haiku POC가 좋지 않았다는 자기평가. session/message/user ID와 enable 설명 | **초기 POC**의 citation schema다. 최종 grouping 결과에 message+offset+actor까지 보존된 것이 증명됐다고 확대하지 않는다. 실패 사례도 모든 cheap model의 보편 성능 판정은 아님 |
| [07:54–10:28](https://www.youtube.com/watch?v=mAKUL12h1n8&t=474s) | 코드영역별 Markdown 및 Where/Rules/Facts, 복수 세션/people 수를 보여주는 시연 | scope에 맞는 context shard는 유용한 방향. people 수는 session 소유자 수이지 인간 여러 명의 명시적 지지나 승인 아님. 최종 source granularity·host 주입·다음 행동 개선은 별도 검증 |
| [10:30–11:48](https://www.youtube.com/watch?v=mAKUL12h1n8&t=630s) | 보고서와 repo를 외부 agent에게 추가로 주자 기존 architecture.md 참조 누락을 발견한 사례 | **ad-hoc 후속 분석**이다. pipeline에 자동 pointer discovery가 이미 구현됐다고 하지 않는다. 새 memory 대신 기존 문서 pointer가 적합한 경우를 설계 후보로 채택 |
| [12:45–13:10](https://www.youtube.com/watch?v=mAKUL12h1n8&t=765s), [16:14–16:24](https://www.youtube.com/watch?v=mAKUL12h1n8&t=974s) | $2→2 cents/session 정정, 강한 agent 개발 탐색 약$100, 최종 보고서50 cents라는 자기 사례 | 분모·cache·재실행·model·storage·검토 시간을 분리해 측정해야 함. 제품 단가/SLA/TCO로 일반화하지 않음 |
| [15:46–19:45](https://www.youtube.com/watch?v=mAKUL12h1n8&t=946s) | 강한 agent로 유용한 결과를 탐색한 뒤 stage와 float 판단·input-hash JSON cache를 만드는 개발 방법 | typed/probability가 truth/권한은 아님. replay는 개발 최적화; prompt/parser/model/policy/source revision과 삭제/권한 상태까지 포함하지 않은 hash는 재현/철회 보장이 아님 |
| [20:05](https://www.youtube.com/watch?v=mAKUL12h1n8&t=1205s), [26:01–28:18](https://www.youtube.com/watch?v=mAKUL12h1n8&t=1561s) | **facts / human corrections / recurring investigations** 세 갈래 추출·grouping 설명과 시연 | 세 입력 신호와 최종 Where/Rules/Language facts 섹션은 **다른 축**. 1:1 대응으로 추정하지 않음. 문장별 source kind·조건·부정·customer/project·branch/revision을 보존해야 함 |
| [20:30–21:19](https://www.youtube.com/watch?v=mAKUL12h1n8&t=1230s), [23:04–23:13](https://www.youtube.com/watch?v=mAKUL12h1n8&t=1384s) | 긴 메시지 필터로 중요한 요청을 버린 bug, input inspection 설명 | middle prune와top/bottom truncate 자동 자막 표현이 어긋남. exact 절단 구현은 확정하지 않음. blanket 필터 대신 원문 offset·누락 표시·회수 경로를 요구 |
| [21:47–22:02](https://www.youtube.com/watch?v=mAKUL12h1n8&t=1307s) | 'do phase six'는 correction이 아니라 continue request라는 예시 | 실행 허가·수집 동의·정정·candidate 승인·standing rule 승격을 분리 |
| [22:16–22:58](https://www.youtube.com/watch?v=mAKUL12h1n8&t=1336s) | 모델이 쓴 내용은 이미 weights에 있다는 일반적 발언 | **일반 명제는 기각.** 새 repo/tool 자료에서 모델이 추출한 task-specific 사실과 pretrained generic 조언은 다름. 새 facts의 지지 근거는 source에서 검증 |
| [24:02–24:30](https://www.youtube.com/watch?v=mAKUL12h1n8&t=1442s) | strong-agent 비교 run에서 text60%·유용한 정보100%라는 자기보고 | 모델 agreement/golden run이지 human ground truth/independent action outcome은 아님 |
| [29:31–31:45](https://www.youtube.com/watch?v=mAKUL12h1n8&t=1771s) | facts prompt의 generic advice/개인 선호/실행 안 된 plan 제외 및 grouped pre-screen+strong judgement | coding-team artifact의 목적 제한이다. **개인 memory의 허용된 preference까지 일괄 제거하지 않음**. quoted/negated/conditional·no-match·한국어 fixture 필요 |
| [34:58–37:27](https://www.youtube.com/watch?v=mAKUL12h1n8&t=2098s) | parent→subagent 질문, file path·실제 읽은 file contents·답변으로 report/code map 생성 | trace-derived 탐색 근거이며 graph DB/기존 앱 codegraph 재사용 요구가 아님. Jev의 '질문에 답함'은 responsiveness이지 correctness. parent/child 중복·snapshot·민감 file 반출은 새 책임 |
| [38:08–43:48](https://www.youtube.com/watch?v=mAKUL12h1n8&t=2288s) | BAML spans/Query와 custom web UI 시연 | **프로그램 관측≠임의 coding host 전체 capture**. Query index≠canonical memory·approval·forget DB. agent DB key 제안은 broad raw-read 권한으로 재사용하지 않음 |
| [44:06–45:25](https://www.youtube.com/watch?v=mAKUL12h1n8&t=2646s) | 과도한 memory/skills와 새 model을 방해하는 규칙, memory health 논의 | 문제 제기/미해결 논점. 자동 health 운영 완성 아님 |
| [45:29–48:22](https://www.youtube.com/watch?v=mAKUL12h1n8&t=2729s) | 다른 memory 방식의 single-session 한계, cross-session correlation·labels/folders·cron consolidation 토론 | 화자의 비교 의견/설계 아이디어. 타사 제품 전반에 대한 검증 완료 판정은 아님. 개인/팀 corpus의 크기 차이는 signal profile로 다룸 |
| [48:23–50:12](https://www.youtube.com/watch?v=mAKUL12h1n8&t=2903s) | memory-off backtest의 replay 한계, code 영역과 memory를 연결해 stale인지 agent에게 묻는 **아이디어** | 같은 task/repo state의 독립 후속 행동 평가. 과거 assistant trace를 답안으로 재생하지 않음. agent stale 주장은 review trigger이지 확정 삭제 권위 아님 |
| [50:46–53:09](https://www.youtube.com/watch?v=mAKUL12h1n8&t=3046s) | 승인한 기억/기존 문서·거절한 기억과 이유를 네 번째 입력에 넣는 incremental/feedback 제안 | **후속 설계**다. 영속 ID/revision·거절 중복 억제·독립 재평가 필요. prompt/context 개선을 online weight 학습이나 자동 품질 향상으로 부르지 않음 |

#### 12.3 도구·공개 코드 교차 확인 — 엔진 추천과 구분

- **영상 전체 공개 코드:** [공식 episode snapshot](https://github.com/ai-that-works/ai-that-works/tree/738a9c18b0302737d5d354d9988f34482966cce6/2026-10-06-building-a-memory-pipeline) 및 [truncated:false subtree](https://api.github.com/repos/ai-that-works/ai-that-works/git/trees/0764336bebce12bcfca3fef6aee1dfbe95cabdfa?recursive=1)에는 `meta.md`와 thumbnail만 있다. 이 링크로 전체 pipeline을 clone/install할 수 있다고 하지 않으며, 인터넷 전체에 구현이 없다는 주장도 아님.
- **BAML:** [현재 소개](https://boundaryml.com/explore.md)와 [고정 canary99edb5d](https://github.com/BoundaryML/baml/tree/99edb5d249850ed92db987148feb78f551a93250)를 확인했다. pre-1.0 nightly와legacy v0 예제를 혼합하지 않음. [Query 구현](https://github.com/BoundaryML/baml/blob/99edb5d249850ed92db987148feb78f551a93250/baml_language/crates/baml_query_btel/src/lib.rs)의 Btel+content-addressable CAS가 원자료이고 `query.sqlite`는 disposable index다. CAS는 concurrency compare-and-swap가 아님. `--local`은 전체 inference/telemetry no-egress 보장이 아니다. 기록의 flush/rename을 canonical transaction/fsync 내구성으로 취급하지 않음.
- **Jev:** [모델 문서](https://docs.typesafe.ai/models.md)는 `jev-1.13.0`, text-only, input $0.042/Mtok. [confidence](https://docs.typesafe.ai/confidence.md)는 분포 집중도이며 정답 보증이 아님. [BAML adapter](https://github.com/BoundaryML/baml/blob/99edb5d249850ed92db987148feb78f551a93250/baml_language/crates/baml_builtins2/baml_std/typesafeai/ns_internal/jev.baml)의 choice/noul·bool p≥0.5 표면은 전체 probability/confidence 및 API resolved-model metadata와 다르다. [no-training와enterprise ZDR](https://docs.typesafe.ai/legal.md)은 구분해야 한다. 저가 hosted gate는 strict no-egress 회사판의 기본 의존성이 될 수 없음.
- **다른 file-memory 예제:** [pin한 memory.baml](https://github.com/BoundaryML/baml-demos/blob/dcc3d33f0fd2635d18515a62a10da91ae789f080/aie/baml_src/ns_memory/memory.baml)은 영상 전체 구현이 아니며 버전도 다르다. ASCII tokenizer/slugifier의 한국어 lexical recall·non-ASCII 이름 충돌 정적 반례를 확인했다. 실제 recall/overwrite runtime test를 실행한 것은 아니다. 공개 열람 가능성은 재배포 license 증명과 다름.
- **Host adapter:** [Claude hooks](https://code.claude.com/docs/en/hooks)와 [Codex hooks](https://learn.chatgpt.com/docs/hooks)를 재사용할 수 있다. 단, Claude launch 시 SessionStart MCP hook의 skip 경로, SessionStart의 command/mcp_tool-only, interrupt/async transcript와 Codex fail-open readiness·nullable transcript·hosted WebSearch coverage·관리형 cloud hooks 제약을 선언해야 한다. **SessionStart command에서 HTTP 요청하는 것과 type:http handler 지원은 다르다.** 최신 live 문서는 설치된 모든 binary의 지원 증명이 아니다.
- **기존 engine의 구체 반례:** [Hindsight pinned retractions helper](https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-api-slim/hindsight_api/engine/reflect/retractions.py)는 모든 cited grounding이 사라지면 import의 fresh IDs와 실제 철회를 구별 못 해 prose를 유지하는 false negative를 명시한다. 이는 정적 source 정책 확인이지 실제 공격 성공 결과가 아니다. canonical eligibility/provenance repair 없이 wrapper-only strict 철회·restore를 보장하지 않음.

### 13. 새 영상 입력으로 실제 Opus 5.5 / Codex 6.1 Sol xhigh 병렬 적대적 리뷰

**§9의 PR/distribution 리뷰를 영상에 대한 승인으로 재사용하지 않았다.** 두 기계적 subagent가 서로 다른 native CLI를 실제 실행했고, 동일 frozen input에는 상대의 결과/이전 verdict를 넣지 않았다. 원문 자막·공식 출처·A/B/C·engine 재사용/좁은 core를 **동일한 full pipeline·출처/권위·승인/철회·동시성/내구성·보안/배포·host·한국어/효용·비용/6개월 유지관리 잣대**로 비교했다.

#### 13.1 실제 실행 증거와 한계

동일 stdin: **205,168 UTF-8 bytes**, SHA256 `c046de5447908e18d0762a533058d49fe8df4699bff90ac3bdc78a9fb0b5db3b`. 8개 frozen source 전체를 두 실행에 전달했고, 실행 후 입력·raw output hash 및 Opus JSON result의 원문 일치를 확인했다.

| 실제 native 실행 | 모델/effort 확인 | UTC 시작→종료 | 실행 결과 |
|---|---|---|---|
| Claude CLI2.1.296 | `--model claude-opus-5-5 --effort xhigh`; native JSON `modelUsage.claude-opus-5-5` | 12:59:38.388347→13:11:18.131229 | exit0 / success / is_error:false, 699.762초, result44,020 bytes |
| Codex CLI0.162.1 | `--model gpt-6.1-sol`·`model_reasoning_effort="xhigh"`; native runtime banner model/provider/xhigh | 12:59:44.836342→13:07:24.671981 | exit0 / native success, 459.848초, stdout26,732 bytes |

**성공한 두 실행의 겹침459.835초**(UTC timestamp millisecond 정밀도). sequential 결과나 다른 모델 fallback을 요청 모델의 병렬 실행으로 부르지 않았다.

Opus는 빈 임시 cwd·safe-mode·empty tools/MCP·dontAsk·slash-command/session-persistence off로 실행했다. 인증 때문에 original HOME을 사용했으므로 HOME isolation/config immutability를 주장하지 않는다. Codex는 auth-only isolated CODEX_HOME·빈 cwd·ignore user config/rules·ephemeral·read-only로 실행했다. 두 임시 실행 디렉터리는 삭제했다. Opus의 **server-resolved effort field는 없어 unknown**이고 Sol effort는 native banner 증거다. 도구 호출 미관측은 Opus final metadata/설정, Sol prompt-echo 제외 stderr 범위이며 provider 내부 완전 audit/독립 attestation은 아니다.

#### 13.2 모든 새 findings의 수용·부분수용 — 제품 runtime 취약점 판정 아님

IDs는 각 모델 원문 그대로 보존한다. Sol도 `VO1…VO8`을 썼으므로 반드시 모델 이름과 함께 구별한다. P0/P1/P2는 해당 모델의 **설계 위험 우선순위**다.

| 모델·native ID | 지적 | 부모의 판정·설계 영향 |
|---|---|---|
| Opus VS3/P1 | engine 재추출/파생물이 canonical 승인·철회를 우회 | **조건부 수용.** canonical authority와 index/projection 구별, 모든 read/publish/restore eligibility·fence. lineage/ID mapping/모든 경로를 강제할 수 있을 때만 read-time join이 충분. missing lineage를 wrapper metadata로 해결했다고 하지 않음 |
| Opus VS1/P1 | **기억→주입→agent 반복→독립 지지 증가의 echo loop** | **수용.** delivery receipt(candidate/revision/hash/session/turn), source origin/derivation을 기록하고 echo를 독립 support에서 제외. 이후의 실제 새 code 관측/인간 정정까지 일괄 제외하지 않음. receipt만으로 semantic paraphrase를 전부 식별했다는 보장도 하지 않음 |
| Opus VS2/P1 | 재생성/거절 후보의 identity drift | **부분 수용.** code가 영속 ID를 할당하고 approval/rejection은 ID+revision+exact text/scope에 연결. 지원 span 집합을 identity hash로 삼아 새 근거마다 ID가 바뀌게 만들지 않음. fresh inference의 byte-identical prose를 일반 보장하지 않고 persisted/replay 안정성과 ambiguous 재매핑을 검증 |
| Opus VS4/P1 | hook의 높은 채널 권위·미검증 region trigger | **수용.** eligibility와rule 권위를 분리, unverified candidate 표시, 실제 host/version capability·scope·delivery 가시성, reviewer/CI 비활성. install/service 자체가 readiness나 region event를 보장하지 않음 |
| Opus VO2/P1 | draft writer가 facts/corrections/recurring을 섞어 Rules로 승격 | **부분 수용.** 문장별 candidate/source kind·unsupported addition audit, 항목/revision 승인. 인간의 새 명시 standing instruction도 유효할 수 있으므로 'correction에서만 Rules 생성'이라는 불필요 제한은 채택하지 않음 |
| Opus VO3/P1 | 개인1인/팀9인 corpus·고객 partition에 따라 반복 신호 의미가 달라짐 | **부분 수용.** authorized partition 내 집계·profile threshold·한 번뿐인 correction 보존. people 수를 반드시 숨길 필요는 없지만 session 소유자/발언자/명시 지지를 분명히 구별 |
| Opus VS5/P2(기록 채택시P1) | Btel/CAS/raw Query가 추가 사본·agent 접근면 | **조건부 수용.** 데이터 root/credentials/ACL/egress/retention/forget 범위 및 local datasource 명시. 불필요 raw capture와 필요한 관측을 구별. home-scoped shared CAS를 고객 격리로 주장하지 않음 |
| Opus VO1/P2 | POC citation과people 수를 최종 span provenance/인간 동의로 과대 해석 | **수용.** 최종 message/offset actor 보존 미입증으로 정정. host가 typed/pasted/injected를 구별 못 하면 unknown을 보존; 모델 추정으로 authenticated human-typed를 만들지 않음 |
| Sol VO1/P0 | continue/correction/consent/approval/rule promotion 혼동 | **수용.** authenticated actor·정확한 revision/diff·operator 권위를 구별. 동일 UID/DB 접근에서 강한 인간 승인 격리를 보장하지 않음 |
| Sol VO2/P0 | local DB를 no-egress로 오인 | **수용.** capture→classifier/extract/embedding/reflect→recording/backup→recall을 받는 host까지 허용 목적지/profile/customer 격리 |
| Sol VO3/P1 | capture/readiness·interrupt/error/subagent·nullable transcript 차이 | **수용.** adapter별 capability 및 incomplete 표시·원문 회수, fail-open과skip 공개. HTTP command와type:http 구분; 모든 host 지원을 선언하지 않음 |
| Sol VO4/P1 | grouping/truncation/parent-child/retry로 독립 지지·조건 소실 | **수용.** source span과독립 root episode 구분, branch/revision/부정/고객 조건 보존. Opus echo 위험은 이것과 별개로 추가 |
| Sol VO5/P1 | typed probability를 truth/approval로 오인 | **수용.** no-match/불충분·actual model/version·한국어/인용/부정/option order calibration; semantic model은 권한·정확한 count·worker commit을 결정하지 않음 |
| Sol VO6/P1 | hash cache/async accepted를 내구성 완료로 오인 | **수용.** durable ingest ack·worker lease/fence·cancel/replay·eligibility-aware cache. 접수/queryable/human-approved 상태를 구별 |
| Sol VO7/P0 | 철회/forget/old restore resurrection | **수용.** canonical/derived/spool/cache/recording/export/backup 범위. 최신 deletion authority가 없으면 restore/read fail closed. 이미 전달된 host context/외부 provider 보존까지 소급 제거한다고 약속하지 않음 |
| Sol VO8/P2 | 자기 golden·2cents·불완전 공개 코드의 품질/TCO/OSS 일반화 | **부분 수용.** 독립 held-out action·한국어·비용 분모·license 검증 유지. **출시 전에 실제6개월 운영 기록이 필수**라는 범위 확대는 미채택; 6개월 유지관리 위험 분석과 SLA 근거 측정은 유지 |

#### 13.3 모델 간 반론·대안 장단점 — 동의만 모으지 않음

A = session child가 engine/DB/worker 소유. B = 설치형 service+CLI/UI, MCP 없음. C = 공통 service+필요한 MCP+operator 도구/host adapter.

| 대안·쟁점 | Opus | Sol | 최종 판단·장단점·영향 |
|---|---|---|---|
| **A session-owned** | 제품으로 기각, single-user/manual fallback | full 계약의 승인된 유한 실행·내구성/복구가 가능하면 유효 | **blanket 기각은 미채택.** 설치가 제한된 환경의 좁은 profile은 가능. 다만 session 밖 batch·다중 세션 worker·remote endpoint까지 대신한다고 광고하면 안 됨. lease/fence/재시작 책임은 사라지지 않음 |
| **B 설치형만** | 먼저 출시, MCP는 소비자 생긴 뒤 | MCP 소비자 없으면 적절 | 작은 표면/운영 통합이 장점, 사용자 목표의 cross-agent/cloud MCP 접근은 별도. **B-first로 이번 제품 범위를 축소하지 않음**. 근거 없는 추가 host/transport는 구현하지 않음 |
| **C 설치형+MCP** | 구조는C, 나중 read/propose MCP | 조건부 기본 | **기본 권고 유지.** service가 durable lifecycle, MCP가 client interface를 담당. hook은 capture/자동 recall, MCP는 agent-initiated read/write proposal. 추가 auth/version drift 비용이 있지만 MCP와설치의 책임을 혼동하지 않음 |
| **MCP admin 권위** | 승인/승격/forget/export를 MCP에 절대 노출하지 않음 | actor/approval 권위 분리 | 일반 agent catalog는 scoped recall/reflect·capture/candidate proposal 중심. operator rule 승격/고위험 purge/export 권위는 agent가 접근 못 하는 별도 plane. **protocol 자체가 관리 연산을 금지하는 것은 아님**. 명시 policy의 저위험 자동 evidence 처리와관리자 전용 client/권한 가능성은 구별 |
| **기존 OSS engine 재사용** | strict canonical join/provenance spike 통과시, 아니면 이득 축소 | engine 내부 권위 통제 가능시에만, duplicated generic engine 금지 | retain/recall/reflect/worker 재사용 장점. Hindsight는 후보이지 선정 완료 아님. wrapper로 missing lineage·내부 async publish를 통제 못 하면 patch/교체 필요. reflect/mental model을 꺼서 full 요구를 몰래 축소하지 않음 |
| **좁은 신규 core+단일 backend** | 기존 engine 이득이 검색만 남고patch/store 중복이 크면 유리할 수 있음 | 재사용 실패시 같은 full 계약으로 비교 | domain 소유권·단순 배포가 장점. 검색/한국어/reflect/worker/restore/auth를 모두 구현하는 비용이 단점. 여러 engine/backend 공통 추상화는 선제 구현하지 않음 |
| **BAML/Jev 채택** | engine과직교하는 조건부 workflow/gate | type/probability와품질/권한 구분 | BAML typed orchestration/관측과Jev 저가 semantic gate를 **선택 의존성**으로 비교. nightly/hosted egress/Korean/metadata 손실 비용. 영상만으로 필수 stack에 넣지 않음 |

**가장 강한 반대 의견:** engine을 쓰면서 canonical 승인/삭제/규칙 store를 다시 만들고, provenance 없는 reflect를 모두 막아야 한다면 재사용 이득은 embedding/search만 남고 PG·upstream·migration·이중 store 비용은 계속 든다. 반대로 새 좁은 core가 한국어+code retrieval와reflect 품질을 과소평가하면 싸 보이는 설계가 실제 행동을 악화시킨다. **두 경로 모두 같은 full pipeline spike/held-out 기준을 통과해야 하며 지금 엔진 승자를 정하지 않는다.**

#### 13.4 기존 권고의 유지·수정과 영향 범위

- **유지:** 독립 OSS/release, 하나의 공통 domain/schema/operation/state/receipt, 회사 local·개인 self-host cloud의 독립 배포. **fork 두 개는 필요하다는 근거가 없지만 데이터·인증·host·backup·egress·운영 절차는 반드시 나눠야 한다.** local HTTP / 개인 VM HTTPS는 초기 지원 표면이며 '어디서든'은 실제 지원 host/version/auth/capture capability 범위다.
- **수정:** §10의 Hindsight distribution은 **우선 spike할 재사용 후보**이지 backend 선정/production 인증이 아니다. 영상형 제품에는 signal/episode/source authority/candidate/feedback/delivery layer가 필요하다. 기존 generic extractor와동일 기능을 새로 두 번 만들지 않되, wrapper-only로 이 책임이 사라진다고 하지 않음.
- **새 핵심 불변식:** source event ID≠독립 episode ID≠candidate ID≠revision≠approval≠delivery receipt. 수집/재시도 dedup뿐 아니라 **memory-origin echo를 독립 지지에서 제외**한다. source actor를 알 수 없으면 unknown이지 human-confirmed가 아니다. 새 evidence는 ID를 무조건 바꾸지 않고, 바뀐 text/revision은 이전 승인을 조용히 승계하지 않는다.
- **회사/개인 profile:** 동일 상태 기계/승인·철회 의미를 유지하되 개인 preference/1인 corpus와팀 signal threshold·허용 local/hosted inference·auth를 선언한다. **다른 모델에서 byte-identical 문장/품질까지 동일하다고 주장하지 않음**. 고객 partition을 넘어 수를 채우지 않고, 한 번뿐인 correction도 버리지 않는다.
- **영향 단계:** capture adapter/consent·source envelope → semantic extraction/grouping → canonical candidate/approval → engine publication/read eligibility → scoped delivery/receipt → feedback/health → cache/recording/export/backup/restore. author opt-in hook·설치/업데이트/제거는 실제 author 행동 변경이며 core 코드0 변경을 행동 영향0이라고 쓰지 않는다. isolated reviewer/CI는 memory 수집·주입을 기본 상속하지 않는다.
- **6개월 유지관리 비용:** host hook·MCP revision, pinned upstream/PG schema, model/embedding upgrade와re-embed, BAML nightly/Jev alias, operator auth, 한국어+code fixtures, restore drill을 소유해야 한다. 측정 없는 금액/기간 추정은 하지 않는다. canonical authority는 하나, index/directive/invalidations는 단방향 projection; 소비자 없는 stdio·멀티 backend·대시보드 중복은 피한다.
- **불가능 조건 유지:** 회사 반출 금지와개인 cloud host가 해당 내용을 읽는 요구는 승인 경계 없이 양립 불가. 필요한 service/compute/model과동등 유한 대안이 모두 금지되면 full pipeline 미지원. host가 capture/next-task recall/auth를 제공하지 않으면 해당 자동 surface 미지원. agent/operator 권한이 실제 같으면 강한 인간 승인 격리 미지원. latest deletion head를 복구 못 하면 forget-restore 보장 미지원. 이름/profile/VPN/MCP marker만으로 해결되지 않음.

#### 13.5 채택 전 관측 기준 — 아직 실행하지 않은 수용 조건

1. supported host/version 실제 event trace: interrupt/error/subagent/async transcript·readiness·scope trigger·reviewer/CI 비활성 및 수집/전달 가시성.
2. 동일 root/child/retry와memory echo fixture: 독립 support 중복 없음, 새 인간 정정/새 revision 관측 보존, 한 번뿐인 correction candidate 보존, crossed-customer leakage 없음.
3. candidate identity/revision·거절 재제안·unsupported draft sentence audit: 명시 revision 없이 승인 text 변경 없음. fresh generation의 표면 문장 일치를 품질 지표로 삼지 않음.
4. canonical/engine race: 접수와commit 구별, 승인/삭제 후 늦은 worker·reflect·mental model·cache replay가 authority를 우회하지 않음. incomplete provenance는 authority 있는 답으로 사용하지 않으며 underlying 기능을 복구/패치해야 함.
5. forget canary·recording/CAS/export/old backup 복원·latest deletion head 차단, OS/credential 권한과전체 egress 관측. 이미 밖으로 전달된 사본의 삭제 불가능/retention 범위를 명시.
6. 한국어+code/부정/인용 공격/조건/개인 preference의 held-out task/repo state, memory-on/off 후속 행동. 자기 golden agreement가 아닌 outcome을 평가하고 cold/hot/replay·전체 인프라·검토 시간을 분리 측정.

**실행한 것은 원문 다운로드·전체 자막 검토·ffprobe/2개 frame 확인·공식 source 교차 확인·실제 두 native 모델의 병렬 리뷰와hash 대조다. 메모리 제품의 위 수용 조건/품질/복구 test 통과를 보고하는 것이 아니다.** chonamdoo/agent-flow#334의 새 code review/approval을 받은 것도 아니다.

#### 13.6 보존한 새 증거

모든 파일은 이 독립 저장소의 로컬 `research/`에 보존했다. 이번 이슈 갱신은 source commit/push·저장소 공개 전환·라이선스 채택·제품 구현을 의미하지 않는다.

- 원문: `video-mAKUL12h1n8-refetch.en-orig.json3`, `video-mAKUL12h1n8-transcript.timed.en.txt`, `video-mAKUL12h1n8-source-provenance.json`, `video-mAKUL12h1n8-claims-check.json`, 확인한2개 PNG.
- source 재분석: `video-mAKUL12h1n8-reanalysis.ko.md`, `video-mAKUL12h1n8-tools.ko.md`, `video-mAKUL12h1n8-portable.ko.md`, `video-mAKUL12h1n8-primary-checks.ko.md`.
- 고정 입력/manifest: `video-review-input.ko.md`, `video-review-manifest.json`.
- Opus 원문: `video-review-opus-5.5-xhigh.ko.md`, SHA256 `c21be59dbd61809d8455582f87e01ff9ca34da0d076d80461d3a2b45b7c71f66`. exact native JSON result 및raw JSON/evidence를 별도 보존.
- Sol 원문: `video-review-codex-6.1-sol-xhigh.ko.md`, SHA256 `67bed62334d1931a092ade70d36bd70ca898da2cb7db2c8a370bf32721af2edd`. native stdout/evidence 보존.
- 검증: `video-native-parallel-proof.json`; 원문 verdict를 고치지 않은 부모 판단은 `video-disposition-opus.ko.md`, `video-disposition-codex.ko.md`; 이번 통합은 `video-review-integration.ko.md`.
