## 독립 OSS로 분리하는 안: 로컬 설치형과 개인 클라우드형을 같은 메모리 엔진으로 운영할 수 있는가

이 추가 분석은 #316의 [앞선 논문·영상·GitHub 조사](https://github.com/chonamdoo/agent-flow/issues/316#issuecomment-6105788769)에 **PR #334의 실제 변경, 독립 OSS 경계, 설치 lifecycle, MCP와 배포 방식 비교**를 더한 것이다. 조사 기준 2026-10-11. 공개 문서·고정 소스와 설계 판단을 구분한다. 메모리 제품 구현·설치·배포·사용자 계정의 연결·품질/복구 벤치마크는 수행하지 않았다.

### 1. 먼저 #334가 무엇을 했는지

고정 비교: base/merge base `642d1792edf0b22bda2bb879ac65df145273dc19` → head `a57c0c8a67df2814324e4e197dcd82faaff1c8b3`. [PR](https://github.com/chonamdoo/agent-flow/pull/334)과 [immutable diff](https://github.com/chonamdoo/agent-flow/compare/642d1792edf0b22bda2bb879ac65df145273dc19...a57c0c8a67df2814324e4e197dcd82faaff1c8b3)를 직접 확인했다. 조회 당시 API는 **open·non-draft·unmerged**, 6개 파일 +131/-31이다. 본문의 과거 draft 표현과 현재 상태가 다르며, ready 표시가 review/gate 승인은 아니다.

| 변경 | 실제 의미 | 구현하지 않은 것 |
|---|---|---|
| 공통 `code-generation-discipline` skill 2 bullets | 사용자 host memory는 선택적 참고, 현재 원문/코드/규칙으로 재확인, 유지 가치 있는 팀 규칙만 tracked PR/review/gate로 제안 | DB·추출·회상·동기화·자동 주입 |
| `lib/installer-shared.mjs` pointer 문자열/주석 | author의 `@AGENTS.md`는 유지, isolated reviewer도 같은 방식으로 읽는다는 과장을 정정 | reviewer scope/runner routing/sandbox 동작 변경 |
| 영문/한국어 `TEAM-ADOPTION.md` | root/legacy ownership, host memory와 팀 규칙, reviewer 플랫폼·전달/소비 한계 문서화 | 별도 memory service 설치 |
| 기존 pointer test의 docstring | 설명 정정, assertion은 그대로 | memory pipeline 동작/품질 테스트 |
| maintainer ledger | #333 architecture-lint 회귀와 알려진 공백 기록 | memory 기능 |

**따라서 #334에서 메모리 엔진을 “떼어내는” 것은 아니다.** 새 독립 제품을 만들거나 기존 OSS 엔진을 채택하는 별도 작업이다. 문서의 “별도 memory-analysis pipeline은 필요 없다”는 현재 Agent Flow의 host-memory 참고 정책을 설명하는 것이지, 사용자가 요청한 독립 제품을 전역 금지하는 근거가 아니다.

Agent Flow [identity/freeze policy](https://github.com/chonamdoo/agent-flow/blob/642d1792edf0b22bda2bb879ac65df145273dc19/docs/IDENTITY-AND-FREEZE-POLICY.md)는 장기 daemon·배포·운영·credential ownership을 core 밖에 둔다. **독립 OSS service가 자기 worker를 운영하고 Agent Flow author가 명시적으로 접속하면 이 경계를 유지할 수 있다.** Agent Flow installer/gate/reviewer home에 서비스를 몰래 넣는 통합은 다른 문제다.

PR의 4 focused passes, 회귀 37 passes+ownership exit75 두 subtest 실패, base 동일 실패, npm snapshot/8설치 관측과 byte budget은 **PR 작성자의 보고**다. 이번에 재실행하지 않았다. Linux verified sandbox 부재로 `20261011-043042` reviewer run이 blocked인 것도 그대로다. 아래 native 모델 설계 리뷰가 그 run의 sealed approval·QA·handoff를 대신하지 않는다.

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
