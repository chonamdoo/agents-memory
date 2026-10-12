# SIE `sie_mcp` + MCP 2 Python OSS reference 조사 (2026-10-12, read-only)

## 0. 표기와 검증 상태

- [근거]: 고정 source나 1차 문서를 직접 읽은 내용입니다.
- [INFERENCE]: 추론입니다.
- [미확정]: 확인하지 못한 내용입니다.

이번 조사에서는 실행, 빌드, 테스트, 설치를 하지 않았습니다(0건). 실제로 실행된 근거는 parent가 돌린 smoke 하나뿐입니다(`research/local-first-python-wire-observation.json`).
- 환경: SDK 2.3.0, Py 3.12.13, HTTP loopback, SQLite.
- 결과: modern 저장 → legacy·auto·modern 읽기가 모두 통과했습니다.
- 이 smoke가 증명하지 않는 것: 제품, Hindsight/PG, native host, 인증, stdio, 기본값이 아닌 transport_security, 토큰 비용.

**라인 번호 주의**
- GitHub raw reader는 연속된 빈 줄을 하나로 합칩니다(documents.py에서 실제 33줄이 32줄로 읽힘을 확인).
- 그래서 SIE 파일 전부와 PY `transport_security.py`, `lowlevel/server.py`의 streamable 구간은 GitHub blame으로 정확한 줄을 확인했습니다.
- `≈`가 붙은 번호는 reader 기준이라 몇 줄 오차가 있을 수 있습니다.

**약칭**
- SIE/ = https://github.com/superlinked/sie/blob/c571e0a75d804cb6d49795a99cd03ea901307a69/packages/sie_mcp/
- PY/ = https://github.com/modelcontextprotocol/python-sdk/blob/2118f14f8a19bc158d8a1cf90af58d85d187f849/
- PY1/ = https://github.com/modelcontextprotocol/python-sdk/blob/v1.28.1/ (tag 기준)

## 1. 고정 기준과 라이선스 [근거]

- **SIE main HEAD**: 2026-10-12 기준 `c571e0a75d804cb6d49795a99cd03ea901307a69`입니다(2026-10-11T06:14:01Z, #689). 기존 research의 pin과 같습니다.
- **`packages/sie_mcp` 마지막 변경**: `addfe0245480fc484a92e74b4c47df439e651836`(release 0.10.0, 2026-10-09). pyproject 버전은 0.10.0입니다.
- **SIE 라이선스**
  - GitHub repo 메타데이터의 SPDX는 `Apache-2.0`입니다.
  - 루트에 Apache-2.0 LICENSE 파일이 있고, NOTICE 파일은 없습니다.
  - `packages/sie_mcp/pyproject.toml`에 `license = { text = "Apache-2.0" }`가 있습니다.
- **SIE 의존성**
  - 선언: `mcp>=1.9,<2`, `starlette>=1.3.1`, `uvicorn[standard]`, `jsonschema`, `pypdfium2`, `pillow`, `sie-sdk`, Python `>=3.12,<3.13`.
  - 루트 `uv.lock`: mcp **1.28.1**, starlette 1.3.1, uvicorn 0.46.0.
- **Python SDK** `2118f14`(= v2.3.0, 2026-10-02 공개)
  - LICENSE 파일, pyproject `license={text="MIT"}`, PyPI `mcp 2.3.0` 모두 MIT입니다.
  - 의존성은 `httpx2>=2.10.0`, `mcp-types==2.3.0`입니다.
- **TS SDK** `b022522`의 LICENSE: MIT에서 Apache-2.0으로 넘어가는 중입니다. 새 기여는 Apache-2.0이고, 재라이선스 동의가 없는 기존 기여는 MIT로 남아 있어 혼합 상태입니다.
- **FastMCP 4.1.0**: PyPI 기준 Apache-2.0입니다. `fastmcp-slim[server]==4.1.0`이 `mcp>=2.0.0,<3`을 요구합니다(fastmcp-slim 업로드 2026-10-08).
- **cloudflare/agents**: main LICENSE가 MIT입니다(고정하지 않음).
- **제약 해석**: SIE upstream에 SDK v2 이전 PR은 보이지 않았습니다(제목 검색, MCP 관련 5건이 모두 v1 기반 보안·정확성 수정).

## 2. Source table

| # | 경로·범위 | 라이선스 | 핵심 사실 | 상태 |
|---|---|---|---|---|
| S1 | SIE/pyproject.toml; 루트 uv.lock(`name="mcp"` 1.28.1) | Apache-2.0 | v1 SDK 고정 | source |
| S2 | SIE/src/sie_mcp/server.py L14 `from mcp.server.fastmcp import Context, FastMCP`; L74-83 `_lifespan`(L76 `SIEAsyncClient(config.sie_base_url, api_key=…)`, L81 base URL INFO 로그); L88-106 `_transport_security`(allowlist가 비면 L106에서 `enable_dns_rebinding_protection=False`); L109-114 `FastMCP("sie-mcp", stateless_http=True, lifespan=…, transport_security=…)`; tool 8개(L117/158/202/251/290/329/368/414); L457 `return server` | Apache-2.0 | v1 생성자 배선. 보호를 끄는 기본값 | source |
| S3 | SIE/src/sie_mcp/app.py L22-37: `build_server(config).streamable_http_app()`, `/healthz`, OAuth routes(L35), `ConnectorSecretAuthMiddleware`(L36) | Apache-2.0 | Starlette factory | source |
| S4 | SIE/src/sie_mcp/cli.py L31-49: `serve` 기본 host `"0.0.0.0"`(L32), port 8088, `uvicorn.run("sie_mcp.app:build_app", factory=True)`(L45-49) | Apache-2.0 | HTTP 전용, stdio 명령 없음 | source |
| S5 | SIE/src/sie_mcp/auth.py L25 `_EXEMPT_PATHS`(healthz/well-known/register/authorize/token); L38 loopback 집합; L56-88 RFC 9110 Host 파서와 `_host_trusted`; L91 `base_url`; L104-121 Bearer 접두어 없는 raw token도 허용; L124-133 `authenticate`(secret 없고 anonymous 미허용이면 거부); L136-161 pure-ASGI. `scope.state.user_id`에 저장하지만 tool은 이 값을 쓰지 않음 | Apache-2.0 | 버퍼링 없는 인증 게이트 | source(upstream PR #305는 auth 테스트 61개 통과를 주장, 재현하지 않음) |
| S6 | SIE/src/sie_mcp/config.py L11 cluster 기본 `http://localhost:8080`; L56 claude.ai callback; L164-271 `MCPConfig`: L224-225 `SIE_BASE_URL`·`SIE_API_KEY`, L229 anonymous 기본 False, L232 `SIE_MCP_ALLOWED_HOSTS`, L257 timeout 300s, L270 **OAuth 기본 True** | Apache-2.0 | env 기반 frozen dataclass와 clamp | source |
| S7 | SIE/src/sie_mcp/oauth.py L1-21 docstring(code는 in-process, 단일 worker); L79 `AuthCodeStore`; L146-169 code를 교환하면 **connector secret 자체**를 반환; L252-261 DCR이 client_id를 발급하지만 저장하지 않음; L334 `{"access_token": secret}`; L339 routes | Apache-2.0 | S256-only, compare_digest, 정확한 redirect 비교 | source(issue #275, PR #292/#305로 origin poisoning 수정됨) |
| S8 | SIE/src/sie_mcp/offload.py L61 `EXTRACT_MAX_CHARS`; L114 `estimate_tokens_saved`(chars/4); L119-180 map-reduce 요약과 `token_savings_estimate`; L392 `pii_map_returned: False`; L401 `redact_text` | Apache-2.0 | 결과 최소화, 상한 | source |
| S9 | SIE/src/sie_mcp/savings.py(전체): live 추정(`markdown_tokens_estimated: True`)과 커밋된 benchmark 측정을 분리 표기 | Apache-2.0 | 추정/측정 분리 | source |
| S10 | SIE/src/sie_mcp/structured.py L212-244 `_validate_against_schema`: jsonschema가 없으면(L229) 또는 SchemaError면(L240) **검증을 건너뜀(fail-open)** | Apache-2.0 | 사전·사후 검증 | source |
| S11 | SIE/src/sie_mcp/qa.py docstring: TRANSIENT 검색이라 저장 없음, 답변과 함께 근거 passage 반환 | Apache-2.0 | 근거가 드러나는 답변 | source |
| S12 | SIE/src/sie_mcp/plugin_pack.py L65 `del connector_secret`(팩에 secret을 저장하지 않음); L129-145 설치 가이드가 `claude mcp add --scope user --transport http … --header "Authorization: Bearer ${SIE_MCP_CONNECTOR_SECRET:?…}"`를 생성하고 `cp -R claude-code/* ~/.claude/skills/` 안내 | Apache-2.0 | 설치 UX | source |
| S13 | SIE/Dockerfile: non-root `sie` 사용자, `/healthz` HEALTHCHECK(인증 없음, cluster 확인 없음), `CMD --host 0.0.0.0` | Apache-2.0 | 이후 cloud 참고용 | source |
| P1 | PY/src/mcp/server/fastmcp.py: import 시 `ModuleNotFoundError` 발생(FastMCP→MCPServer 개명). v2.0.1 release에도 같은 안내 | MIT | v1 코드가 그대로 깨짐 | source |
| P2 | PY/src/mcp/server/transport_security.py L48: 설정이 없으면 보호 off; L50-66: Host wildcard를 `host.startswith(base_host + ":")`로 비교(prefix 방식); L72-76: Origin이 없으면 통과; 잘못된 Host/Origin 값을 WARNING 로그에 그대로 남김; `RequestBodyLimitMiddleware` 기본 4 MiB | MIT | | source |
| P3 | PY/src/mcp/server/lowlevel/server.py L732 `streamable_http_app`, L752-758: host가 127.0.0.1/localhost/::1이고 설정이 없으면 보호 자동 on(allowlist `127.0.0.1:*` 등). `Server.run` docstring ≈L711-715(+~5): HTTP session manager가 lifespan을 소유 | MIT | | source |
| P4 | PY/src/mcp/server/mcpserver/server.py ≈L1284-1311 `streamable_http_app(... stateless_http=False, transport_security=None, host="127.0.0.1")`; ≈L1070 `run_stdio_async`; `subscriptions=False`(v2.3 release) | MIT | 전송 옵션은 생성자가 아니라 run/app에 줌 | source |
| P5 | PY/docs/run/deploy.md ≈L7-27(Host allowlist, 421/403, non-localhost `host=`는 보호를 끔), ≈L73-83(stateless_http는 legacy 전용); docs/run/legacy-clients.md ≈L103-171; docs/run/asgi.md ≈L40-46, L99-110(CORS); docs/whats-new.md ≈L121, L151; docs/protocol-versions.md ≈L37-40; docs/client/transports.md ≈L124-129(stdio 자식 env allow-list) | MIT | 공식 운영 계약 | 문서 |
| P6 | PY/examples/stories/dual_era/{server.py,README.md}; bearer_auth/server.py; middleware/server.py; lifespan/server.py; _hosting.py(`NO_DNS_REBIND`는 하네스 전용); caching/README.md(미구현); mcpserver/memory.py | MIT | §4 참고 | source |
| P7 | PY1/src/mcp/server/lowlevel/server.py ≈L643-660 `run()`이 **실행마다** `self.lifespan(self)`에 진입; PY1/src/mcp/server/streamable_http_manager.py ≈L167-201 stateless 경로가 요청마다 `app.run(..., stateless=True)` 호출 | MIT | SIE의 lifespan이 요청마다 실행됨 | source-traced, 실행 안 함 |
| X1 | https://pypi.org/pypi/fastmcp-slim/4.1.0/json; https://gofastmcp.com/getting-started/upgrading/from-fastmcp-3.md ≈L179-180, L385-450 | Apache-2.0 | mcp>=2. dual-era 주장. modern에서 `ctx.set_state`가 호출 간에 보이지 않고, elicit는 era-gated, ping은 routing 안 됨 | 메타데이터·문서만 |
| X2 | https://ts.sdk.modelcontextprotocol.io/v2/protocol-versions.md ≈L45-51, L100-109, L134, L160-166 | MIT/Apache 혼합 | **client 기본은 legacy(probe 없음)**. `createMcpHandler` 기본 `legacy:'stateless'`. stdio probe는 별도 sibling 프로세스 사용 | 문서만 |
| X3 | Cloudflare handler-api.md ≈L21-24, L186, L198-200, L248-265, L494 | agents MIT | per-request factory, legacy 기본 stateless. 'cross-request data는 인증된 handle 뒤에 저장, MCP session ID 사용 금지'. CORS는 인증이 아님. token을 로그에 남기지 말 것 | 문서만 |
| X4 | https://code.claude.com/docs/en/mcp.md ≈L79-80, L420, L533-539, L604, L629-666, L708, L959-1044 | live 문서 | user·local scope가 `~/.claude.json`에 저장됨. `claude mcp add`는 검증 없이 저장. `${VAR}` 확장 지원. `headersHelper`는 trust 이후에만 실행되고 repo가 제공한 helper에서는 credential env를 제거. 출력은 10k tokens에서 경고, 기본 상한 25k, 50k자 초과 시 파일로 저장 | 문서만 |

## 3. SIE 항목별 판정

**3.1 SDK import, 버전, 고정, wire [근거]**
- v1 `FastMCP(stateless_http=True)`를 사용합니다(S2 L14, L110-114). lock은 1.28.1입니다.
- SDK 2.x에서 막히는 지점은 두 가지입니다.
  - P1: import 자체가 실패합니다.
  - P4/whats-new: `stateless_http`, `transport_security`, `host`가 생성자에서 app builder/run으로 옮겨졌습니다.
- 따라서 pin만 올리는 업그레이드는 불가능합니다. `stateless_http=True`는 v1 legacy 경로의 옵션일 뿐이고, 2026-07-28 wire를 지원한다는 증거가 아닙니다.
- SIE 자체의 2026 wire 지원: 증거 없음 [미확정·현재 코드로는 불가 INFERENCE].

**3.2 localhost 기본값, HTTP/stdio**
- CLI 기본 bind는 0.0.0.0이고 Docker도 같습니다(S4 L32, S13). README의 local edge 예시만 `--host 127.0.0.1`을 명시합니다.
- cluster 기본값은 `http://localhost:8080`이지만 원격 URL로 바꿀 수 있고, http 평문도 거부하지 않습니다(S6 L11, L224).
- stdio 실행 경로는 없습니다.
- 'localhost MCP'라고 해서 처리가 로컬이라는 뜻은 아닙니다. edge는 문서 전체를 `SIE_BASE_URL`로 보냅니다(S2 L76, S8).
- HEAD 커밋 메시지에 따르면 SIE Cloud는 'SIE Relay(partner capacity)'로 요청을 넘길 수 있습니다. egress 체인이 설정한 gateway 너머로 이어질 수 있다는 뜻입니다 [근거: c571e0a 메시지 / 적용 범위는 INFERENCE].

**3.3 프로세스 수명주기**
- 단일 uvicorn 프로세스(factory)이고 `--reload`는 개발용입니다. supervisor는 없습니다.
- `/healthz`는 인증 없이 항상 ok를 반환하므로 readiness를 구분하지 못합니다.
- OAuth code store는 메모리에만 있어 재시작하면 사라지고 단일 worker 전제입니다(S7 docstring).
- 중요: v1 stateless에서는 lifespan이 요청마다 실행됩니다(P7). SIE docstring의 'process당 1회'와 다르게 요청마다 `MCPConfig.from_env()`와 `SIEAsyncClient` 생성·close가 일어납니다 [source-traced, 미실행].
- SDK v2에서는 session manager가 lifespan을 소유합니다(P3 docstring, PY lifespan story). 우리 PG pool은 v2 기준으로 smoke 확인이 필요합니다.

**3.4 ingress 인증, Host/Origin/CORS/OAuth**
- 인증은 정적 shared secret 맵(env CSV `secret:user`)이고, Bearer 접두어 없는 raw token도 받습니다(S5).
- anonymous는 fail-closed입니다(L229, L133). 이 부분은 좋습니다.
- DNS-rebinding 보호는 allowlist가 비면 꺼집니다(S2 L106). loopback에 bind해도 마찬가지입니다.
- CORS middleware는 없습니다(PR #305 sweep으로 확인).
- OAuth bridge가 기본으로 켜져 있습니다(L270).
  - /register, /authorize, /token은 인증 없이 열려 있습니다(L25).
  - access token이 곧 정적 connector secret이라 만료, audience, 개별 폐기가 없습니다(S7 L169, L334).
  - 공개 origin은 PUBLIC_URL로 고정하거나 loopback/allowlist에서만 파생합니다(#275 → #292/#305 수정).
- 인증된 identity(`state.user_id`)가 tool 동작에 쓰이지 않습니다. memory 도메인이라면 scope 누출로 이어집니다 [INFERENCE].

**3.5 env 정리 vs credential 전달**
- edge 프로세스가 cluster key(`SIE_API_KEY`)와 client secret 맵을 모두 env로 읽습니다.
- plugin-pack은 secret 인자를 받아도 버립니다(L65). 이 부분은 좋습니다.
- 그러나 생성되는 가이드의 `claude mcp add --scope user … --header "Authorization: Bearer ${…}"`는 shell이 값을 먼저 펼치기 때문에 **실제 secret 문자열이 `~/.claude.json` user scope(모든 프로젝트)에 평문으로 저장**됩니다 [INFERENCE: shell 확장 + X4 L533-535, L604, L708].
- 같은 가이드가 `~/.claude/skills` 전역 복사를 안내하는데, 우리의 3-scope 원칙 및 global eager 금지와 충돌합니다.
- 참고 사항:
  - SDK v2 client stdio는 자식 프로세스에 최소 allow-list env(`HOME/LOGNAME/PATH/SHELL/TERM/USER`)와 `env=`만 넘깁니다(P5). 이는 SDK client의 동작이며 host마다 정책이 다릅니다.
  - Claude `headersHelper`는 repo/plugin이 제공한 경우 credential 변수를 제거하고, trust를 받은 뒤에만 실행합니다(X4 ≈L1029-1044).

**3.6 작은 카탈로그, tool search, offload 결과, 로그, egress**
- tool 8개가 긴 docstring(Args 포함)과 함께 항상 노출됩니다. deferred loading이나 tool search는 없습니다.
- protocol이 stateless여도 tools/list 카탈로그의 렌더링 토큰은 매번 듭니다. SDK caching hint는 `ttl_ms=0`이고 override hook이 아직 구현되지 않았습니다(P6 caching README). 따라서 카탈로그 비용은 host별 실측 대상입니다 [실측 없음].
- 결과 구성에서 좋은 점:
  - artifact와 metadata를 분리합니다.
  - 추정값(`*_estimate`, `estimated: True`)과 커밋된 측정값을 섞지 않습니다(S9).
  - 원문 PII map을 돌려주지 않습니다(S8 L392).
  - 입력 bytes/chars/질문 수/chunk 수에 상한이 있습니다(S6, S8).
  - QA가 사용한 passage를 함께 반환합니다(S11).
- 나쁜 점: 구조화 출력의 사후 검증이 fail-open입니다(S10).
- 로그:
  - base URL을 INFO로 남깁니다(URL userinfo에 credential이 있으면 그대로 노출됨, INFERENCE).
  - oauth.py에는 로그 호출이 없습니다(#275 보고자가 확인).
  - OCR 실패 시 `exc_info` warning을 남깁니다.
  - uvicorn access log는 path, status, IP를 기록합니다.

## 4. SIE 외 공식·유지 modern 예시 (2–4개 + 상태)

1. **PY dual_era**(server.py, README)
   - 하나의 factory가 두 era를 서빙합니다. era 분기 키는 `ctx.request_context.protocol_version`이고 `MODERN_PROTOCOL_VERSIONS`와 비교합니다.
   - README caveat 1: HTTP era 분기는 현재 header만 봅니다. `MCP-Protocol-Version` 헤더가 빠진 2026 client는 legacy로 잘못 라우팅됩니다.
   - README caveat 2: 'bare stdio 실행은 legacy만 동작'한다고 적혀 있습니다. 반면 protocol-versions.md는 stdio에서도 server/discover를 받는다고 해서 **문서 간 모순**입니다. 결론: [미확정, stdio 미시험].
   - 판정: **채택(edge 기본형)**.
2. **PY bearer_auth**(`TokenVerifier`→`AccessToken(subject, scopes, resource)`, `AuthSettings(validate_token_resource=True)`, `get_access_token()`)
   - per-install token 검증과 principal 전달에 씁니다.
   - 판정: **채택**. 예시가 쓰는 `NO_DNS_REBIND`는 하네스 전용이라 복사하지 않습니다.
3. **PY middleware + lifespan**
   - `MCPServer.middleware`로 method만 감사 로그에 남기고(payload는 남기지 않음), binding을 확인할 수 없으면 거부합니다.
   - `MCPServer[AppState](lifespan=…)`로 DB pool을 보유합니다.
   - 판정: **채택**.
4. **PY 운영 문서**(deploy/asgi/legacy-clients)
   - loopback 기본 보호, 실제 hostname에서는 421, CORS 규칙, `stateless_http`는 legacy 전용(back-channel이 없어짐), 다중 worker에는 `RequestStateSecurity(keys)`와 같은 server name 필요, legacy session은 메모리 저장이라 sticky가 필요합니다.
   - 판정: **채택(운영 계약)**.

참고 또는 기각:
- **PY `mcpserver/memory.py`**: OpenAI embedding/LLM으로 egress가 발생하고, `postgres:postgres` DSN이 하드코딩되어 있으며, `~/.mcp/$USER`에 씁니다. → **기각**.
- **FastMCP 4.1**: 의존성 메타데이터와 문서만 확인했습니다. → **채택 안 함**(공식 SDK에 레이어만 하나 더 생기고 Prefect 의존성이 늘어남). 2026 wire 지원은 '거짓'이 아니라 **미확정**입니다.
  - 다만 Hindsight가 `fastmcp>=3.2.0`을 상한 없이 쓰므로(engine evidence L61), 새로 resolve하면 4.x(mcp 2.x)가 들어와 동작이 달라질 위험이 있습니다. lock으로 고정하거나 Hindsight native MCP를 외부에 노출하지 않아야 합니다 [INFERENCE, 미시험].
- **TS SDK v2**: 참고만 합니다. client 기본이 legacy라서, TS 기반 host는 opt-in하지 않으면 2025 handshake로 붙을 수 있습니다 [INFERENCE: host별 설정은 미확정]. 그래서 우리 서버는 legacy 서빙이 필수입니다.
- **Cloudflare createMcpHandler**: Workers(cloud) 런타임이라 지금 local 기반으로는 **기각**합니다. 원칙만 참고합니다: 인증된 handle 뒤에 저장, token을 로그·반환하지 않음, CORS는 인증이 아님.

## 5. 지원 matrix와 source-only 경계

| 구성 | 라이브러리 major | 2026-07-28 wire | ≤2025-11-25 | stdio | HTTP | 상태 |
|---|---|---|---|---|---|---|
| sie-mcp 0.10.0 | mcp 1.x(1.28.1) | 증거 없음 / 2.x import 불가 | 지원(v1) | 없음 | 있음 | source-only |
| mcp 2.3.0 MCPServer | 2.x | 지원 | 지원(같은 endpoint) | 문서 모순 [미확정] | 지원 | **HTTP는 parent가 시험함**. auth·non-default security·stdio·PG는 미시험 |
| FastMCP 4.1.0 | 4.x(mcp>=2) | 문서상 지원 | 문서상 지원 | 문서 | 문서 | 메타데이터·문서만 |
| TS SDK v2.3.1 | 2.x | 문서상 | 문서상(client 기본 legacy) | `serveStdio` 문서 | 문서 | 문서만 |
| Cloudflare agents | — | 문서상 | stateless legacy | — | Workers | 문서만 |
| Hindsight native MCP | fastmcp>=3.2 | [미확정] | — | — | — | 기존 evidence |

혼동하지 말아야 할 구분:
- 라이브러리 major(mcp 2, FastMCP 4)와 protocol date는 서로 다른 축입니다.
- protocol의 statelessness(initialize/session이 없음)와 app의 상태(DB는 지속됨)는 다릅니다.
- startup handshake가 사라진 것과 prompt token 비용(카탈로그, 응답)은 별개입니다.

## 6. Reuse map (→ 우리 모듈, contract §2/§5/§6 기준)

- **edge app**(memory_context/inspect/record/feedback)
  - 출발점: PY dual_era + lifespan.
  - 구성: `MCPServer(…, subscriptions=False if unused)`. `streamable_http_app(host="127.0.0.1", max_request_body_size=명시, transport_security=None→loopback 자동 보호)`. 출력은 Pydantic.
  - SIE app.py에서는 factory/`/healthz` 형태만 참고하되, `/readyz`(DB·worker·watermark)를 따로 둡니다.
- **edge.auth**
  - PY bearer_auth의 `TokenVerifier`를 씁니다. per-install token은 Keychain이나 0600 파일에 두고 `hmac.compare_digest`로 비교합니다. principal은 binding/scope로 매핑해 domain에서 강제합니다.
  - SIE auth.py에서는 pure-ASGI 방식과 RFC 9110 Host 파서 아이디어만 참고합니다(Host를 어딘가에 반영할 때만 필요).
  - raw token 허용과 shared secret CSV는 기각합니다.
- **edge.policy**
  - PY middleware를 씁니다: method와 결과 코드만 감사 로그에 남기고, binding을 알 수 없을 때 required 동작은 거부합니다.
  - protocol_version은 진단용으로만 쓰고 identity로 쓰지 않습니다.
- **service.config**
  - SIE config.py의 frozen dataclass, fail-closed, clamp를 적응해 씁니다.
  - 기본값을 바꿉니다: loopback, OAuth off, 모든 route allowlist 명시, 원격 http 거부.
- **service.result_composer / budget**
  - SIE savings/offload에서 추정·측정 분리 표기와 입력·출력 상한을 가져옵니다.
  - qa의 '사용한 근거 반환'은 citation ID와 provenance 반환으로 적응합니다.
  - redact의 'raw 원문을 반환하지 않음' 원칙을 따릅니다.
  - transient 검색 의미론은 기각합니다(우리는 durable).
- **extract/reflect 검증**: SIE structured의 사전 subset 검사와 사후 jsonschema 검증을 쓰되, 반드시 **fail-closed**로 바꿉니다.
- **capture ingest**: MCP tool 인자로 받지 않습니다(4 MiB 제한, 권한 분리). hook에서 로컬 ingest API/CLI로 보냅니다.
- **installer/doctor**
  - SIE plugin_pack에서 'secret을 산출물에 쓰지 않음'과 URL normalize를 가져옵니다.
  - 등록은 local/project scope + `headersHelper`(Keychain) 또는 `${VAR}`로 합니다.
  - user-scope `--header` 리터럴과 `~/.claude/skills` 전역 복사는 기각합니다.
  - doctor는 era, protocol, Host 보호 상태, body 한도를 표시합니다.
- **나중의 개인 cloud**
  - PY deploy(정확한 allowlist, proxy-headers, RequestStateSecurity), 진짜 AS + `AuthSettings`를 씁니다.
  - SIE oauth의 하드닝 항목(S256-only, 정확한 redirect, 고정 PUBLIC_URL, X-Forwarded-* 무시)만 참고합니다.
  - '정적 secret을 access token으로 쓰는' bridge는 기각합니다.

## 7. 가장 강한 위험

1. **비호환**: SIE를 SDK 2로 옮기려면 사실상 재작성이 필요합니다(P1/P4).
   - SIE를 fork해도 문서 offload 도메인과 v1 배선만 남습니다.
   - stdio 2026 경로는 문서가 서로 모순되어 [미확정]입니다.
   - 2026 client라도 헤더를 빠뜨리면 legacy로 잘못 라우팅됩니다(dual_era caveat).
2. **로컬 노출**: SIE 기본값(0.0.0.0, 보호 off, OAuth on, 인증 없는 bootstrap route)을 회사 장비에서 그대로 쓰면 LAN에 노출됩니다. 정적 secret 하나가 유일한 방어선이 됩니다.
3. **같은 UID 한계**
   - SDK 기본 보호는 브라우저 DNS-rebinding만 막습니다. Origin이 없으면 통과하므로(P2 L75), 로컬의 비브라우저 프로세스는 bearer token 없이는 막을 수 없습니다.
   - 반대로 같은 UID 프로세스는 token 파일이나 Keychain에 접근할 수 있으므로 loopback 인증이 같은 UID 격리가 되지는 않습니다(기존 결론과 일치).
4. **Host wildcard prefix 비교**(P2 L66)
   - SIE PR #305가 1.28.1에서 보고한 패턴(`host:443@evil`)과 같은 비교가 2.3에도 남아 있습니다.
   - 브라우저 rebinding 방어에는 영향이 작습니다 [INFERENCE]. 다만 Host 값을 OAuth metadata나 링크에 반영하면 안 되고, allowlist는 정확한 값으로 씁니다.
5. **수명주기**: v1 stateless는 lifespan을 요청마다 실행합니다(P7). v2는 lifespan이 process 범위이며, PG pool·worker는 edge 밖 service가 소유해야 합니다(contract §5).
6. **egress**
   - edge가 로컬이어도 처리 경로는 원격일 수 있습니다(S2/S8, SIE Relay).
   - 우리 쪽에서는 Hindsight/LLM route allowlist를 시작 시점에 검증하고, 승인되지 않은 route는 fail-closed로 막아야 합니다.
7. **credential 누출**
   - 설치 가이드 패턴 때문에 `~/.claude.json`에 평문 secret이 남고, user scope라 회사·개인 프로젝트가 섞입니다.
   - URL userinfo가 INFO 로그로 남을 수 있습니다.
   - SDK가 잘못된 Host/Origin 값을 WARNING에 그대로 기록합니다(log injection).
8. **정확성**
   - 구조화 출력 검증이 fail-open입니다(S10).
   - dict 반환 시 structured_content가 비는 문제가 parent smoke에서 관찰됐습니다. Pydantic 출력이 필수입니다.
9. **context 비용**: 카탈로그 캐싱은 미구현이고 host 출력 상한은 25k tokens입니다(X4). 응답 예산은 host별 실측 토큰 기준으로 관리해야 합니다.
10. **공급망과 라이선스**
   - fastmcp 상한이 없어 4.x drift 위험이 있습니다.
   - TS SDK는 MIT/Apache 혼합입니다.
   - SIE 코드를 복사하면 Apache-2.0 §4에 따라 고지와 변경 표시를 해야 합니다(NOTICE 파일은 없음).

## 8. 미확정 사항과 parent smoke 후보 (실행하지 않음)

- SDK 2.3 stdio dual-era: `run_stdio_async` + `Client(StdioServerParameters, mode=auto/2026)`.
- non-default `transport_security`의 421/403 동작. Origin이 없을 때 통과하는지.
- body 4 MiB 초과 시 413.
- `TokenVerifier`에서 401과 PRM 응답.
- lifespan이 process당 한 번만 실행되는지(요청 N회 동안 pool이 하나인지).
- `subscriptions=False`일 때 listen 응답.
- 헤더 없는 2026 요청이 legacy로 잘못 라우팅되는지.
- FastMCP 4 소스 경로 검증.
- Hindsight가 fastmcp 4.x에서 동작하는지.