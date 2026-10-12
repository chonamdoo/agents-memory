# 개인 self-host cloud 메모리 서비스: remote MCP 지원과 운영 경계

조사일: 2026-10-11. 공개 공식 문서와 공개 source만 읽었다. 설치, 로그인, 모델/API 호출, cloud 배포, 프로젝트 코드 변경, GitHub 게시는 수행하지 않았다. 아래 **문서 사실**은 문서가 선언한 기능과 조건이고, **[INFERENCE]**는 그 사실로부터 도출한 설계 판단이다. 모든 사용자 계정 연결, 읽기/쓰기 왕복, 자동 수집, 성능, 삭제/복원은 **미실측**이다. 기존 [종합 연구 §§5–8](issue-316-cloud-memory.ko.md#5-공통-엔진과-두-독립-배포)의 공통 엔진 및 독립 신뢰 경계 논의를 보완한다. #316/PR #334의 최신 상태 판단은 이 문서의 범위가 아니다.

## 1. 결론과 가장 강한 반론

**[INFERENCE] 기본 후보는 ‘동일 OSS memory domain/service + 업무용 로컬 설치 + 개인용 독립 cloud 배포 + host별 MCP adapter’다.** MCP는 연결 protocol이고, installer/Compose/daemon은 설치·배포·수명주기다. 둘 중 하나를 고르는 문제로 만들면 storage, worker, auth, backup이 사라진다. 같은 기록→추출→회상→reflect→정정→철회 계약을 유지하되 회사/고객/개인의 DB, 인증 principal, host/session, credential, backup을 각각 분리한다. 공통 소스가 데이터 sync나 공통 계정의 근거는 아니다.

**이 후보의 가장 강한 반론은 remote MCP endpoint를 완성해도 사용자의 hosted agent가 임의 서버에 인증하여 자동 기록·회상할 수 있다는 보장이 없다는 점이다.** Claude cloud에는 project 설정과 connector 경로가 따로 있고, ChatGPT Web Plugins에는 등록·OAuth·workspace·publication 조건이 있다. Codex Cloud의 HTTP 네트워크 접근은 임의 MCP 서버의 native tool 등록 증거가 아니다. 특히 개인 plan에서 private read/write plugin을 쓸 수 있는지는 현재 계정에서 확인해야 한다. MCP adapter가 표준을 준수한다는 사실만으로 전체 host 지원을 약속할 수 없다.

두 번째 반론은 ‘한 서비스’가 운영 부담까지 통일하지 않는다는 점이다. 단일 VM은 장애 지점이 하나이고, Cloud Run은 ephemeral storage와 CPU lifecycle 때문에 동일 package의 내부 worker를 그대로 옮기기 어렵다. 외부 IdP, managed PG, queue, secret, backup 비용과 연결 실패 대응을 사용자가 책임진다. vendor-managed 상품이 이 부담과 host 연결을 더 잘 해결할 수 있다. 다만 이는 운영 편의의 대안이지 **동일 OSS backend**의 증명은 아니다.

**[INFERENCE] 선택 순서:** 개인 규모에서는 single VM/Compose + durable PostgreSQL + worker를 먼저 비교한다. managed PG는 같은 OSS 엔진을 유지하면서 DB 운영만 맡기는 타협이다. Cloud Run은 외부 durable DB와 명시적 worker/job 경계를 갖출 때 비교한다. 특정 hosted 표면이 임의 remote MCP를 지원하지 않으면 이를 unsupported/미확인으로 표시하고, 직접 운영 VM의 CLI/Agent SDK 또는 명시적인 API adapter를 대안으로 제시한다. **API adapter를 native MCP 지원이라고 부르거나, 자동 수집·추출·reflect를 수동 note 저장으로 축소하지 않는다.**

## 2. 핵심 1차 출처 12개

아래 12개는 결정 가치가 큰 대표 출처다. 세부 claim의 규범·host·운영 보충 출처는 해당 절에서 별도로 링크했다. 제품 소개를 실행 증거로 취급하지 않았다.

| ID | 직접 읽은 1차 출처 | 이 조사에서 확인한 범위 |
|---|---|---|
| S1 | [MCP 2026-07-28 공식 release](https://blog.modelcontextprotocol.io/posts/2026-07-28/) | 새 stable revision, stateless core, initialize/session 제거, CIMD 전환, DCR deprecation |
| S2 | [MCP 2026-07-28 authorization](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization) | OAuth resource server, discovery, PKCE, issuer/audience/resource/scope 검증, token passthrough 금지 |
| S3 | [MCP architecture](https://modelcontextprotocol.io/specification/2026-07-28/architecture) | 전체 conversation은 host 소유; 서버는 필요한 context만 받음 |
| S4 | [Claude Code cloud environments](https://code.claude.com/docs/en/cloud-environments.md) | repo `.mcp.json`과 local 설정 차이, connector 별도 경로, Network=None 예외, plan별 secret |
| S5 | [OpenAI MCP host reference](https://learn.chatgpt.com/docs/extend/mcp) | local host의 stdio/HTTP/Bearer/OAuth; Web은 local config 미사용, plugin 경로 |
| S6 | [OpenAI Plugins](https://learn.chatgpt.com/docs/plugins) | Chat/Work의 web/desktop/mobile 지원, desktop-only 예외, host별 hooks/auth/data sharing |
| S7 | [OpenAI plugin authentication](https://developers.openai.com/plugins/build/auth) | 자체 OAuth 서버 가능, S256 필수, 정확한 callback/issuer, ChatGPT의 custom key/M2M 제한 |
| S8 | [Codex Cloud environments](https://learn.chatgpt.com/docs/environments/cloud-environments) | task별 filesystem, domain policy, HTTPS proxy secrets, 개인 vault, VPN/OIDC 별도 설정 |
| S9 | [Cloud Run runtime contract](https://docs.cloud.google.com/run/docs/container-contract) | volatile filesystem, TLS termination, CPU/lifecycle, 종료·timeout, Linux amd64 |
| S10 | [Cloud Run service-to-service auth](https://docs.cloud.google.com/run/docs/authenticating/service-to-service) | Google-signed ID token + run.invoker, Run audience, application Authorization과 분리 가능 |
| S11 | [Hindsight services](https://hindsight.vectorize.io/developer/services) | same package/image의 API·worker, PG task broker, retain/recall/reflect, durable PG |
| S12 | [Supermemory self-hosting overview](https://supermemory.ai/docs/self-hosting/overview) | self-host binary는 비공개 source, 같은 API≠OSS; local MCP/connector와 platform 차이 |

## 3. MCP stable와 2025 compatibility를 분리한다

**문서 사실:** S1의 2026-07-28 release는 `initialize`/`initialized`, `Mcp-Session-Id`를 제거했다. request는 자체 version/client/capability를 담고 `server/discover`는 선택 사항이다. app의 memory/workflow state가 없어지는 것은 아니다. DCR은 backward compatibility를 위해 유지되지만 deprecated이며 CIMD를 권장한다. 이 날짜 이후에도 모든 설치 host가 이 revision을 사용한다는 뜻은 아니다.

| 차이 | [2026 Streamable HTTP](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http) | [2025-11-25 transport](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports) | 배포 영향 [INFERENCE] |
|---|---|---|---|
| 시작/상태 | self-contained request, protocol session 제거 | 초기화 및 선택적 session ID | 같은 domain에 별도 transport compatibility layer를 두고 실제 host revision을 기록 |
| endpoint/stream | 단일 POST, JSON 또는 request-scoped SSE; change notification은 `subscriptions/listen` POST | POST/GET, 선택적 GET stream/resume/session | reverse proxy가 구형 GET/SSE와 신형 POST stream을 각각 처리해야 함 |
| routing | `MCP-Protocol-Version`, `Mcp-Method`, 해당 요청의 `Mcp-Name`; body/header 일치 검증 | 초기 협상 version과 후속 version header | gateway가 도구 이름만 보고 권한을 결정하지 않음; 본문과 일치 검증 필요 |
| 취소 | SSE disconnect는 해당 요청 취소 | disconnect를 취소로 간주하지 않음, 명시적 notification | adapter에서 혼합하면 장기 추출/reflect의 종료 의미가 달라짐 |
| SSE | request-scoped stream은 남음; `Last-Event-ID` resumability 없음 | resumability 구현 가능 | ‘2026에서는 SSE 자체가 사라졌다’는 설명은 틀림 |

**Claude의 문서상 지원:** [MCP client runtimes](https://code.claude.com/docs/en/mcp.md#mcp-client-runtimes)는 SDK 1.x/2.0 runtime을 구분한다. feature flag를 fetch하는 session은 v2.1.232+, fetch하지 않는 열거된 session은 v2.1.274+에서 v2 기본값을 명시한다. v2는 새 revision 지원 여부를 확인하고 미지원 server에는 구형 방식을 사용한다. Anthropic이 특정 server를 구형 protocol에 유지하는 flag, `MCP_SDK_GENERATION`/`MCP_PROTOCOL_NEGOTIATION` 선택도 있다. **CLI version만으로 이 계정의 협상 결과를 확정하지 않는다.** S5의 Codex 문서는 OAuth CIMD/DCR를 명시하지만 `instructions`의 initialization 설명도 남아 있다. 그 설명을 ‘Codex의 모든 표면이 이미 2026 stateless’라는 증거로 사용할 수 없다.

2025 호환 session을 여러 cloud instance에서 운영할 때는 선택 SDK의 state 공유 또는 routing/reconnect 전략을 따로 확인한다. 2026 stateless의 load-balancing 장점을 구형 client에도 적용했다고 주장하지 않는다. memory operation ID, 동시 정정, 철회 revision, outbox 상태는 transport session과 독립적인 domain state로 둔다 [INFERENCE].

## 4. remote HTTPS OAuth와 Cloud Run IAM은 다른 인증이다

S2에서 authorization은 protocol 전체의 필수 기능이 아니라 **OPTIONAL**이다. HTTP에서 지원하면 이 규격을 따르는 것이 **SHOULD**다. 그렇다고 개인 memory 서비스의 공개 무인증 운영을 권고하는 것은 아니다. 이 서비스의 private data/쓰기에는 application auth와 ACL을 요구한다 [설계 제안].

**S2/S7의 문서 사실:**

- MCP server는 OAuth resource server이며 access token을 매 request 검증한다. protected-resource metadata(RFC9728)와 authorization-server/OIDC discovery를 제공한다. client는 authorize/token request에 canonical MCP `resource`를 넣고 server는 자신의 audience를 검증한다.
- PKCE `S256`, expiration/scope 검증이 필요하다. authorization server의 발급자 `issuer`와 callback의 `iss`는 정확히 일치해야 한다. 규격에서 AS의 `iss` 포함은 **SHOULD**이고, advertised=true인데 누락하거나 present 값이 다르면 client는 reject한다. 모든 AS가 무조건 `iss`를 보내는 것으로 쓰지 않는다.
- MCP client credential은 발급 issuer에 묶인다. 다른 upstream API를 위해 발급된 token을 memory 서버가 받아 사용하거나 그대로 LLM/DB/provider에 넘기는 token passthrough는 금지된다.
- ChatGPT auth 문서는 OAuth 코드+PKCE/CIMD/DCR/predefined client 경로를 설명한다. `S256` metadata가 없으면 unsupported라고 명시한다. 실제 management 화면에 표시되는 정확한 callback URL을 IdP에 등록해야 한다. refresh token 발급·rotation·폐기는 또 다른 운영 조건이다.

**S10의 문서 사실:** private Cloud Run 호출에는 Google-signed OIDC **ID token**, 받는 서비스 URL 또는 configured audience, 호출 principal의 `roles/run.invoker`가 필요하다. `Authorization` 또는 `X-Serverless-Authorization`을 사용할 수 있다. 후자는 app의 `Authorization`이 별도 인증을 사용할 때 쓸 수 있으나, 이것이 모든 MCP host가 두 token을 생성한다는 뜻은 아니다.

**[INFERENCE] 안전한 구성 두 가지:**

1. 네트워크로 도달 가능한 HTTPS MCP ingress에서 application OAuth/ACL을 강제한다. Cloud Run의 platform IAM check를 열었더라도 memory API가 무인증이어서는 안 된다.
2. OAuth gateway가 client의 access token을 검증하고 private Run backend를 gateway 전용 Google identity로 호출한다. end-user principal/operation scope를 검증된 내부 경로로 전달하고, backend의 서비스 계정과 user identity를 혼동하지 않는다.

외부 ChatGPT connector에 service-account key를 주거나 사용자의 일반 OAuth access token이 private Run IAM을 통과할 것이라고 전제하지 않는다. S7은 ChatGPT가 client-credentials/service-account/JWT-bearer 같은 M2M OAuth grant, custom API key, 고객 제공 mTLS certificate를 지원하지 않는다고 명시한다. OpenAI-managed mTLS certificate는 **OpenAI client 식별**이고 end-user memory ACL의 대체물이 아니다. Codex **local** host는 Bearer/header/helper를 지원하지만 S5의 `http_headers_helper`는 remote execution environment를 통한 연결에는 지원하지 않는다. 같은 credential helper를 hosted task에 이식할 수 있다는 주장은 성립하지 않는다.

## 5. host별 지원 matrix: native MCP와 curl/API를 구분한다

표 전체는 문서상 기능이다. 이 사용자의 실제 plan, account flag, admin policy, plugin 설치, OAuth, read/write는 모두 미실측이다. ‘remote’는 사용자 Mac 없이 memory 서버에 도달하는 연결을 뜻하며, Web UI를 통해 Mac을 원격 조종하는 것과도 구분한다.

| 실제 실행 표면 | native MCP/등록 경로 | 인증·읽기/쓰기 조건 | local 설정·자동 수집 경계 | 미확인/판단 |
|---|---|---|---|---|
| Claude Code local CLI/직접 운영 cloud VM의 CLI | [HTTP 또는 stdio 등록](https://code.claude.com/docs/en/mcp.md); remote HTTP 권장 | OAuth 또는 명시적 header; 도구 permission/tenant ACL 별도 | config/credential은 실행 host에 있음. VM에는 따로 넣어야 함 | 2026/2025 협상, timeout, 실제 recall/retain/retract 검증 필요 |
| Anthropic-hosted Claude Code cloud session, 단일 repo | S4가 committed project `.mcp.json` 로드를 명시 | repo config에 URL만 있다고 auth 완료 아님. interactive AWS SSO 등은 미지원. cloud plan의 환경/secret 정책 확인 | `~/.claude.json` local/user MCP, user hook/plugin/설치물은 자동 전달 안 됨. committed repo hook/permission은 단일 repo에서 로드 | project MCP와 claude.ai connector는 별도 경로. auth grant/실제 native call은 미실측 |
| Claude cloud connector/routine | 활성 connector는 Anthropic 서버 경로로 도구 연결(S4) | 사용자 connector authorization 및 session/routine에서 활성화 필요 | VM domain allowlist를 우회. 따라서 Network=None은 connector/Anthropic/GitHub/network-secret 전체 차단 아님 | project MCP transport의 VM 요청도 자동 우회한다고 일반화 금지; 실제 egress path 확인 |
| Claude Remote Control | S4는 자신의 machine/files/network에 연결한다고 구분 | 자기 host의 auth/tool 권한 | cloud VM이 아님; Mac이 꺼지면 독립 cloud 실행을 보장 못함 | ‘집 Mac이 꺼져도 다른 cloud agent가 사용’의 대체안 아님 [INFERENCE] |
| Codex CLI/ChatGPT desktop의 Codex/IDE, 동일 local host | S5: stdio + Streamable HTTP, same host `config.toml` 공유 | Bearer/OAuth CIMD/DCR, per-tool approval; IDE는 Plugins 자체 미지원(S6) | local user/project config. remote executor의 stdio `experimental_environment`는 local-orchestrated 기능이며 Web 등록과 다름 | arbitrary HTTP 서버 가능 경로가 문서화됨. 계정 OAuth 성공과 backend ACL은 별도 |
| ChatGPT Web Chat/Work Plugins, 지원 계정 | S5/S6: Plugins의 remote MCP-backed tools; [custom server 등록→plugin 생성](https://developers.openai.com/plugins/build/plugins#create-and-test-a-plugin-locally-with-an-mcp-server) 문서화 | private data/write는 OAuth/권한/approval/connector grant 필요. account/workspace feature와 plugin policy에 종속 | Web은 local Codex config/command menu 미사용. plugin hooks는 cloud-orchestrated Work에서 지원되지 않음 | 임의 서버 등록 경로는 존재하지만 모든 개인 plan의 private write 성공까지 입증 안 됨 |
| Codex Cloud ‘Work in > Cloud’ 새 task | S8: published environment에서 task별 workspace, 별도 networking/secret/VPN/OIDC | HTTPS port443 network secret은 proxy 치환; domain 허용≠권한 부여 | PC의 config/key/helper가 자동 승계된다고 명시하지 않음. published filesystem과 task identity 별도 | S8 자체는 arbitrary MCP URL의 native catalog 등록을 보장하지 않음. S5의 hosted plugin 경로가 해당 task에 붙는지 계정에서 따로 확인. curl로 API 호출 가능은 다른 주장 |
| Codex Cloud (Legacy) Code Review/Linear/GitHub integrations | S8이 새 환경과 legacy를 구분하며 deprecation 계획 명시 | legacy 환경의 별도 정책 | 새 cloud 문서의 secret/Plugin 조건을 legacy에도 그대로 적용 금지 | generic private memory MCP support 미확인; reviewer memory 연결은 기본 opt-out 제안 |
| ChatGPT legacy developer-mode custom MCP app | [Help 공식 문서](https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt): Business/Enterprise/Edu full MCP beta; Pro read/fetch | admin/RBAC/scan/OAuth/도구 action 승인. risky action block 가능 | web-only, custom app은 agent mode 미사용, deep research는 read/fetch only. frozen tool snapshot | 이 경로의 mobile/write 제한을 새로운 Plugins 전체에 덮어씌우지 않음 |
| 직접 운영 VM/container의 Claude Agent SDK | [SDK `mcpServers`, project source, allowedTools](https://code.claude.com/docs/en/agent-sdk/mcp.md) | HTTP/stdio/in-process 도구 구성과 permission 제어. model provider 인증·비용은 별도 | 자신이 capture adapter/hooks/event flow 배치 가능. 자동 수집은 이를 실제 구현해야 함 | 가장 통제 가능한 대안 [INFERENCE]이나 agent 운영·격리·provider policy 책임 추가 |

### Claude Network=None과 project 설정의 정확한 범위

S4는 `.mcp.json` 로드를 **session with one repository** 조건으로 명시한다. 여러 repo와 self-hosted runner는 별도 설정 규칙 링크를 제공한다. ‘repo 어디에든 있으면 모든 cloud task에서 로드’로 확대하지 않는다. repo가 선언한 `enabledPlugins`/`extraKnownMarketplaces`의 plugin은 cloud session이 설치하지 않는다고 명시한다.

S4의 **None**은 ‘session의 network를 통한 outbound가 없음’이다. Anthropic API, GitHub 별도 proxy, 활성 MCP connectors, network-secret 허용 host는 다른 경로로 남는다. network secrets는 현재 **Pro/Max**, 기존 Anthropic-hosted environment와 internet-reachable API에 제공되며 Team/Enterprise에는 아직 없고 self-hosted environment에도 없다. env variable은 agent가 읽을 수 있는 값이고 network secret은 VM 밖 proxy가 붙이는 값이다. setup-script 요청, 일부 provider/package registry/telemetry 요청에는 secret을 붙이지 않는 예외도 있다. **secret으로 curl 성공을 확인해도 OAuth/native MCP/tool permission 성공을 증명하지 않는다.**

### OpenAI 임의 서버와 publication의 실제 조건

[Plugin packaging](https://developers.openai.com/plugins/build/plugins)에는 **Add custom MCP server → URL/connection details → risk warning → Create as a plugin** 경로가 있다. 그러나 local/repo marketplace의 discoverability, workspace publication, universal public directory publication은 서로 다른 배포 범위다. local marketplace/project `.codex/config.toml` 설정은 supported local clients에 적용되고 workspace installation policy를 바꾸지 않는다. workspace 게시에는 admin과 role policy가 필요하며 `features.plugin_sharing=false`로 막을 수 있다.

[Public submission](https://developers.openai.com/plugins/deploy/submission)은 remote HTTPS endpoint, domain verification, OAuth/noauth/mixed 지원, review용 별도 test account와 positive/negative cases를 요구한다. package에서 여러 server를 선언해도 실제 연결은 현재 plugin당 **하나**다. schema가 `api_key`를 받아도 submission portal에는 API-key/Bearer input flow가 없고 nonempty server headers는 reject한다. `apps`/`.app.json` reference 및 lifecycle hooks를 담은 ZIP도 public submission 불가다. **manifest 문법 지원은 runtime/auth/공개 심사 지원과 같지 않다.**

S6은 Plugins가 지원 계정에서 Chat/Work web/desktop/mobile에 제공됨과 **Desktop only** 예외를 구분한다. 개인이 만든 arbitrary-server plugin에 이 지원 범위가 모두 열렸는지는 계정 UI에서 확인해야 한다. public plugin과 legacy custom app의 도구 갱신도 다르다. public plugin은 daily automated scan을 통과한 eligible tool changes를 반영하고, legacy custom app은 admin-approved frozen snapshot을 사용한다. MCP catalog의 새 revision이 이 배포 경로에서 즉시 사용된다고 기대하지 않는다.

## 6. 자동 memory capture는 MCP와 별도 기능이다

**문서 사실:** S3는 전체 conversation history가 host에 남고 server는 필요한 context만 받는다고 명시한다. MCP 연결만으로 새 server가 provider 내부 memory, 모든 대화, hidden reasoning, 다른 server의 결과를 읽는 기능은 없다. [OpenAI Plugins](https://learn.chatgpt.com/docs/plugins)의 hooks 설명도 web 설치가 script를 배포하지 않는다고 명시하며, cloud-orchestrated Work는 plugin hooks를 지원하지 않는다. enterprise의 admin-defined MCP hooks도 지원 events에 한정되고 complete compliance audit trail이 아니다(S5).

**[INFERENCE] 요구를 충족하는 경로는 다음처럼 분리해야 한다.**

1. host별 opt-in capture/export adapter가 승인된 event/source span과 실행 결과를 수집한다. credential, hidden chain-of-thought, 고객 자료의 개인 store 전송은 제외한다. 수집 실패/host unsupported를 보인다.
2. 공통 service가 provenance와 안정 source ID를 보존하고 자동 extraction/consolidation/reflect를 실행한다. 해당 model/provider의 data egress와 비용을 별도로 허가한다.
3. 다음 task의 host adapter가 적절한 recall을 호출해 결과를 context에 실제로 넣는다. server가 저장했다는 사실과 다음 task가 사용했다는 사실을 분리한다.
4. 정정/철회는 raw, fact, embedding/graph, summary/mental model, cache, pending worker의 lineage와 revision을 따라 적용한다. old source가 재수집되거나 restore에서 다시 노출되지 않도록 별도 계약이 필요하다.

model이 상황에 따라 memory tool을 호출하는 것, hook이 원문을 보내는 것, provider native memory가 내용을 저장하는 것은 다른 수집 방식이다. 지원하지 않는 hosted 표면을 ‘사용자가 수동으로 기록하면 된다’로 대체하여 자동 capture 요구가 충족된 것처럼 보고하지 않는다.

## 7. single VM/Compose와 Cloud Run/managed PG 비교

S11의 Hindsight는 retain(ingest·fact·graph), recall(search), reflect(answer generation)를 memory engine의 작업으로 구분한다. API는 stateless이고 state는 PG에 저장한다고 명시한다. worker는 **같은 package/image의 다른 entry point**이며 PG의 pending tasks를 polling한다. [Installation](https://hindsight.vectorize.io/developer/installation)은 production에 embedded pg0를 비추천하고 PostgreSQL 14+ 및 지원 vector extension을 요구한다. 이미지 full/slim의 model 위치도 다르다. 아래는 이 구조를 사용한 **설계 비교**이며 이 저장소에서 배포된 topology가 아니다.

| 운영 항목 | single VM/Compose + PG + worker | Cloud Run API + external/managed PG + 별도 worker | 결정 영향 |
|---|---|---|---|
| durable data | persistent disk/volume의 PG; VM disk failure에 별도 backup 필요 | S9: container writable filesystem은 RAM이며 instance 종료 시 소실. PG/raw/spool/outbox를 여기에 둘 수 없음 | same container image≠same storage contract. DB를 PG sidecar/pg0로 Run에 넣는 cutover 금지 [INFERENCE] |
| background CPU | OS/container service가 지속 실행되는 동안 polling worker 가능. host/process 종료 대응 필요 | [Billing](https://docs.cloud.google.com/run/docs/configuring/billing-settings): request-based는 요청 동안만 CPU, instance-based도 instance 종료 가능 | 응답 뒤 coroutine/내부 dispatcher를 durable worker로 간주하지 않음. worker pool/VM 또는 명시적 Tasks/Jobs/sweep 경로 필요 |
| engine worker 적합성 | S11의 PG polling worker와 자연스럽게 맞음 [INFERENCE] | Tasks가 임의 polling worker를 push-handler로 자동 변환하지 않음. S11 worker는 자신이 제공하는 entry point/lifecycle을 기준으로 배치 | backend의 내부 queue를 먼저 재사용. cloud 편의 때문에 두 queue의 상태를 중복 권위로 만들지 않음 |
| outbox | raw/event와 job intent를 동일 PG transaction에 commit하고 worker가 회수하는 형태 가능 [설계] | Tasks를 추가하면 PG commit→enqueue 사이 gap 발생. request 안의 enqueue + independent sweep 필요 [설계] | [Tasks pitfalls](https://docs.cloud.google.com/tasks/docs/common-pitfalls)는 at-least-once/중복/nonordered. idempotency, revision fence, durable failure status 필요 |
| TLS/network | 사용자가 certificate renewal, proxy, firewall, DNS, stream timeout 운영 | S9: Run이 TLS terminate; 외부 URL·gateway·IAM/application OAuth 경계는 직접 설계 | TLS가 end-user ACL이나 OAuth issuer 검증을 대체하지 않음 |
| IdP/secret | 기존 IdP 선택, 최소권한 credential 저장·rotation·backup 복구 책임 | [Run secrets](https://docs.cloud.google.com/run/docs/configuring/services/secrets): Secret Manager 권한, env는 startup resolve/version pin 권장, volume은 읽을 때 최신 값 | secret rotation 시 새/기존 instance 차이와 실패 조건 확인. Secret Manager는 OAuth consent/tenant policy의 대체물이 아님 |
| backup/restore | SQL dump, coherent filesystem snapshot, WAL/PITR를 직접 구성 | [Cloud SQL backups](https://docs.cloud.google.com/sql/docs/postgres/backup-recovery/backups): 일정·retention·encrypted backup 제공, instance 삭제 뒤 backup 잔존 가능 | managed DB가 domain 철회/삭제를 알지는 못함. restore 전에 최신 deletion head/ledger를 독립 경로에서 재적용 [설계] |
| 비용/가용성 | VM provisioned floor + disk/backup + model/운영 시간. 한 VM은 HA 아님 | Run min/CPU/Tasks + managed PG floor/backup/network/secret + model. scale-to-zero가 DB 비용을 없애지 않음 | 사용량 없이 총 월액이나 더 싼 안을 확정하지 않음 |
| portability | OS/arch/image/version과 PG extension을 고정하면 명시적 운영 가능 | S9 Run은 Linux amd64, runtime/concurrency/DB connection limits 고려 | local Mac binary와 동일 artifact/speed 보장 불가; common schema/contract를 유지하는 것이 목표 |

### durability와 backup의 수용 기준

**[설계 제안] API 성공 ACK는 최소한 승인된 event/job intent가 durable commit됐다는 의미를 가져야 한다.** extraction/reflect가 pending인지 완료됐는지는 operation 상태로 따로 보인다. enqueue 성공만으로 memory indexing 성공이라 하지 않는다. Cloud Tasks의 순서나 드물게 발생하는 중복에 의존하지 않고, source revision과 idempotency key로 worker commit을 제한한다. API timeout 후 client가 retry한 요청의 결과를 확인할 수 있어야 한다.

VM의 Docker volume은 데이터 위치이지 backup이 아니다. [PostgreSQL backup 문서](https://www.postgresql.org/docs/18/backup.html)는 SQL dump, filesystem backup, continuous archiving을 구분한다. [Filesystem backup](https://www.postgresql.org/docs/18/backup-file.html)은 단순 파일 copy에는 shutdown이 필요하고 live consistent snapshot은 WAL을 포함해야 하며 여러 disk의 snapshot 일관성도 요구한다. ‘VM disk를 복사해 두었다’만으로 복구 가능이라고 쓰지 않는다.

Cloud SQL은 backup/export를 구분하며 standard on-demand backup은 수동 삭제 전까지 무기한 보존될 수 있다. 데이터 DB 삭제는 backup 삭제와 다르다. restore는 과거 state를 재현하므로 이미 철회한 개인 memory를 다시 노출할 수 있다 [INFERENCE]. restore 후 조회를 열기 전에 DB rollback과 독립적으로 보존한 최신 deletion watermark를 확인·재적용한다 [설계]. raw/object storage를 추가하면 PG와 storage/Tasks 간 원자 transaction이 생기지 않으므로 source/derived/outbox reconcile 책임을 더한다.

S11의 ‘workers without conflicts’는 제품 문서의 선언이다. 이를 stale worker의 철회 후 commit 방지나 모든 worker crash의 자동 recovery 검증으로 확대하지 않는다. 설치 문서는 stable worker ID와 stuck operation 복구를 따로 설명한다. 선택 backend/version의 실제 shutdown, lease/recovery, worker-id 규칙은 배포 전에 확인해야 한다.

## 8. user self-host cloud, vendor managed API, MCP 등록은 서로 다르다

**user self-host cloud**는 사용자가 선택한 cloud 계정에 OSS engine을 배포하고 DB/schema/version/provider/auth/backup을 통제하는 것이다. managed PG를 써도 memory engine의 소스와 계약을 직접 운영할 수 있다. cloud provider가 인프라를 관리한다는 사실과 vendor memory engine을 managed-only API로 소비한다는 사실은 다르다 [정의/설계].

**문서 사실:** Hindsight의 [고정 commit LICENSE](https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/LICENSE)는 MIT다. S11과 설치 문서는 같은 API/worker package를 직접 운영하는 경로를 제공한다. 이는 후보인 이유이지 noauth/tenant ACL, 한국어 품질, 삭제/복원, external model egress가 이미 해결됐다는 증거가 아니다. hosted Hindsight의 내부 code/config와 OSS 배포가 완전히 동일하다는 주장도 하지 않는다.

**S12의 중요한 반례:** Supermemory는 같은 memory engine/API의 local binary를 제공한다고 설명하지만 **binary source는 별도 비공개 codebase**라고 명시한다. 공개 SDK/MCP/plugin의 OSS license가 이를 바꾸지 않는다. 공식 local/platform 표는 local에서 connectors와 Supermemory MCP가 제공되지 않는 차이, proprietary hosted extraction model, telemetry opt-out, URL ingestion의 hosted reader 경로도 표시한다. [Local vs Enterprise](https://supermemory.ai/docs/self-hosting/local-vs-enterprise)는 local의 single key/one-machine와 Enterprise의 조직 auth/managed infrastructure를 구분한다. 따라서 ‘vendor API만이 유일한 배포’라고 잘못 쓰지 않되 **self-host 가능≠OSS engine, API 동일≠실제 model/품질/거버넌스 동일**이라고 평가한다. 별도 wrapper를 만들 수 있다는 가능성도 vendor 전체 engine의 source 공개나 portability를 증명하지 않는다.

**[MCP Registry 공식 설명](https://modelcontextprotocol.io/registry/about)의 문서 사실:** registry는 package/remote URL과 설치 정보의 metadata repository이며 closed-source server도 받는다. namespace ownership을 검증하지만 actual server code scanning은 underlying package registry/downstream aggregator에 맡긴다. private server용 public registry도 아니다. 따라서 등록·installer·plugin packaging·OAuth scan은 provenance 또는 연결/배포 편의를 높일 수 있지만 retrieval 품질, transaction 내구성, bank ACL, poisoning 방어, purge, backup restore를 인증하지 않는다 [INFERENCE]. public OSS 소스 배포를 위해 사용자의 private memory endpoint나 corpus를 public directory에 공개할 필요는 없다.

## 9. privacy, upstream, publication 범위를 분리한다

- **기억 소유/분리 [설계]:** 회사·고객 저장소와 개인 store 사이 sync/fallback을 만들지 않는다. endpoint/profile뿐 아니라 agent home, session/history/native memory, API credential, 원문/추출물, log/export/backup 경계를 분리한다. 이미 업무 context를 읽은 같은 session을 개인 cloud로 돌리는 것은 서버 ACL로 해결되지 않는다.
- **upstream 전송 [문서 사실+추론]:** S4에서 Claude connector traffic은 Anthropic 경로이고 S6는 MCP 서비스에 전송한 데이터에 그 서비스의 terms/privacy가 적용된다고 설명한다. self-host memory DB도 host/model provider의 prompt·tool result 처리나 extraction/embedding/rerank/reflect provider 전송을 없애지 않는다. 승인된 provider/region/retention/training 계약은 계정별 확인 사항이다. 서버가 집/개인 cloud에 있다는 이유로 전체 workflow no-egress라 하지 않는다.
- **공개 산출물 [설계]:** 연구, synthetic fixture, OSS source, installer metadata만 공개 후보로 삼는다. 고객 corpus, 개인 memory, tokens, callback state, host local config의 비밀값, 실제 endpoint identity, backup, provider request log, review 계정 credential은 게시 범위에서 제외한다.
- **private/public 배포 [문서 사실]:** OpenAI workspace-published plugin은 universal directory 게시와 다르고 workspace boundary에 남는다. public submission은 별도 domain/identity/review/게시 절차다. test account에는 sample data를 써야 하며 실제 개인 계정을 review용으로 제공하지 않는다. registry namespace 검증과 OSS LICENSE는 개인정보 공개 허가가 아니다.
- **폐기 [문서 사실]:** S6는 plugin uninstall과 separately connected MCP integration disconnect가 별도라고 명시한다. 설치 제거만으로 OAuth grant/token/서버 memory/backup까지 삭제됐다고 말하지 않는다. server API 철회와 provider host history·native memory·이미 생성된 commit의 삭제 범위도 분리한다.

## 10. 사용자 계정/선택 배포에서 실측할 항목

아래는 수행한 검증이 아니라 채택 전 필요한 관찰이다. 실제 endpoint 연결의 최소 증거는 **정확한 host/surface/version/plan + protocol + auth principal + native tool call + durable read/write 결과**다.

| 항목 | 필요한 실제 관찰 | 실패하면 달라지는 결정 |
|---|---|---|
| host 지원 | Claude 단일/다중 repo, connector/routine, Codex local/new Cloud/legacy, ChatGPT Web 개인 plugin 각각에서 catalog에 memory tool이 나타나는지 | 문서 없는 표면을 supported라고 출시하지 않음; own-VM/SDK/API 경로와 명확히 구분 |
| native vs API | host MCP tool invocation 기록과 server request를 대응. curl/HTTP API 호출은 별도 결과로 기록 | 네트워크/secret만 성공한 것을 MCP 연결 성공으로 처리하지 않음 |
| protocol | 2026 version/body/header, 구형 initialize/session, streaming/cancel/timeout, tool update 반영 | adapter revision과 compatibility 범위를 제한 |
| OAuth/IAM | exact issuer/resource/audience/redirect, CIMD/DCR/pre-registration, scope step-up, refresh/rotation/revoke, incorrect issuer/audience/expired token 거절 | 현재 host와 IdP 조합 unsupported 또는 gateway 필요 |
| hosted plugin | custom arbitrary URL 등록 가능 여부, private read/write, admin/role/plan/mobile, approve/reject, tool snapshot update | 개인 plan에 read만 가능하면 자동 capture/write 요구 미충족을 표시 |
| capture/recall/reflect | 승인 source의 자동 capture→durable ingest→추출→다음 task 회상→reflect를 source ID로 연결. unsupported hooks와 수집 누락 표시 | 수동 memory note 제품으로 축소하지 않고 host adapter 범위 조정 |
| 독립 cloud 접근 | 사용자 Mac을 쓰지 않는 cloud task가 read/write하고 Mac offline에도 endpoint 사용 가능 | local relay/Remote Control이 개인 cloud 독립성의 단일 의존점이면 탈락 |
| durable worker | API 종료/instance 교체/enqueue gap/duplicate/out-of-order/model timeout에서 operation 유실·이중 commit이 없는지 | VM worker 유지 또는 Run worker/queue 설계 수정 |
| 정정/철회/restore | derived state·cache·pending job·stale device/spool에 철회 적용, 과거 backup restore 후 조회 재개 전에 최신 deletion head 반영 | 도입 불가 또는 명시적으로 좁힌 삭제 계약 필요 |
| 개인정보/egress | source·summary·vector·로그·telemetry·model request·backup 경로, None 예외와 connector proxy 실제 관찰 | 업무 strict는 별도 승인된 host/provider/네트워크 경계 필요 |
| 비용/품질 | 동일 corpus/언어/LLM/embedding/budget의 no-memory·plain RAG 대조; p95/cold-start/capture 비용/reflect 비용/restore 시간 | managed 제품 숫자를 self-host 성능/월액으로 바꾸지 않음 |

**반환 가능한 결론:** 동일 OSS 서비스의 로컬·개인 cloud 두 배포는 문서상 구성 가능한 방향이다. 이를 ‘어느 cloud agent에서나 같은 설정으로 자동 기억이 동작한다’거나 ‘MCP 등록으로 운영 품질이 보증된다’고 게시할 근거는 없다. common domain/schema와 자동 수집·추출·회상·reflect 요구를 유지하면서, host별 실제 지원과 data/auth/backup 경계를 별도로 충족해야 한다.
