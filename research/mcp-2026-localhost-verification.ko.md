# MCP 2026-07-28·SDK 2.x·SIE localhost: 이번 재확인

조사 기준: 2026-10-11. 공개 공식 문서·고정 소스 확인과 격리된 실제 HTTP/SQLite smoke를 구분한다. agent-memory-mcp 제품 구현·SIE cluster 실행·회사 계정/정책 검사·토큰 절감 측정은 아니다.

## 확인된 공식 변경

- 공식 protocol revision은 `2026-07-28`이며 SDK semver 2.x와 별개다. initialize/initialized, protocol session, Mcp-Session-Id가 제거됐다. 각 요청의 `_meta`에 protocolVersion/clientCapabilities를 전달한다. clientInfo는 SHOULD다. server/discover는 서버 필수 구현이지만 클라이언트 호출은 선택이며 새 mandatory handshake가 아니다.[S1–S2]
- server-to-client independent JSON-RPC 요청 대신 `resultType: input_required`, inputRequests/inputResponses의 MRTR를 사용한다. Notifications까지 전부 삭제된 것은 아니다.[S2]
- POST에는 MCP-Protocol-Version·Mcp-Method가 필요하다. Mcp-Name은 tools/call·resources/read·prompts/get에만 필요하다. 이전 GET stream은 제거됐지만 request-scoped SSE와 POST subscriptions/listen은 남는다. 'SSE 전체 제거'는 잘못이다.[S2–S3]
- list/read의 ttlMs/cacheScope는 freshness/cache 힌트다. 권한·철회·현재 rule revision 확인을 대체하지 않는다. Roots/Sampling/Logging/DCR의 earliest removal은 2027-07-28 이후 첫 revision이며 정확히 12개월 뒤 자동 삭제라는 뜻은 아니다.[S2,S5]
- STDIO도 지원된다. 회사에서 포트가 허용되지 않으면 승인된 stdio 접속 adapter를 쓸 수 있지만 agent session이 durable worker/DB를 소유해야 한다는 뜻은 아니다.[S4]
- Python 공식 latest stable은 2.3.0, TypeScript는 2.3.1을 직접 API에서 확인했다. TS는 @modelcontextprotocol/client/server/core 등 분리 패키지이므로 'TS npm mcp 2.0.0'라는 이름으로 설치하면 안 된다.[S6–S7]

## SIE에서 실제로 재사용 가능한 패턴

고정 HEAD: `c571e0a75d804cb6d49795a99cd03ea901307a69`.[S8]

- Local edge를 loopback 127.0.0.1:8088에 띄울 수 있다. README의 Local Edge Against A Cluster는 MCP edge만 로컬이며 document processing은 SIE_BASE_URL의 cluster에서 실행된다고 명시한다.[S9]
- server lifespan이 SIEAsyncClient(config.sie_base_url, api_key=...)를 만들고 tool이 그 upstream으로 보낸다. config의 base URL 기본은 localhost:8080이지만 remote URL도 가능하다. 'localhost MCP니까 모든 데이터 처리도 로컬'은 성립하지 않는다.[S10]
- cli serve의 기본 bind는 0.0.0.0이다. 회사 로컬 profile은 명시적 127.0.0.1 및 Host/Origin·DNS rebinding·인증이 필요하다. allowed_hosts가 비어 있으면 source의 DNS rebinding 보호가 disabled다. localhost는 인증이 아니다.[S10–S11]
- pinned pyproject는 mcp>=1.9,<2다. server의 FastMCP(stateless_http=True)는 이전 SDK의 state 옵션이지 handshake-free 2026 protocol 구현 증거가 아니다. SIE의 얇은 접속/engine 분리 패턴을 가져올 수 있지만 그대로 MCP 2.x 호환 reference로 선택하지 않는다.[S10,S12]

## 실제 smoke 관측

uv --no-project, 이미 설치된 Python 3.12, mcp==2.3.0, uvicorn으로 임시 SQLite 및 loopback HTTP ASGI 서버를 띄웠다. 공공 synthetic 문장 하나만 사용했다. 서로 독립적인 `Client(url, mode='2026-07-28')` 두 context 중 첫째가 저장하고 둘째가 읽었다.

최종 실행 exit0, 0.99초. 실제 네 요청은 tools/call(store_note), tools/list, tools/list, tools/call(get_note)였고 모두 HTTP 200이었다. initialize와 Mcp-Session-Id 없이, 각 요청에서 protocol header·namespaced _meta·Mcp-Method를 관측했다. tools/list에는 Mcp-Name이 없고 named tool call에는 있었다. 두 번째 client가 SQLite에 저장된 정확한 body `synthetic-protocol-smoke-note`를 회수했다. `server/discover`도 이 실행에는 없었다.

첫 실행은 plain dict return이 TextContent로 전달돼 structured_content가 None인 상황을 검사기가 실패로 판정했다. 문장 자체는 회수됐지만 이를 최종 성공에 포함하지 않았다. 임시 예제의 get_note return을 Pydantic NoteResult로 명시해 output schema를 제공한 뒤 전체 흐름을 재실행한 결과가 위 최종 관측이다. 라이브러리/제품 버그 판정이 아니다.

이것은 **새 protocol 요청이 무상태여도 application DB가 지속될 수 있다는 최소 실험**이다. native Claude/Codex 호환·인증·회사 격리·memory 자동화·품질·worker·복구·실제 context token 절감을 입증하지 않는다. 임시 실행 파일은 완료 후 제거한다.

## 공통 memory 제품에 적용할 결정 [INFERENCE]

1. 공통 installed engine/service의 memory·approval·revision·job을 DB에 둔다. protocol session이나 `_meta.clientInfo`를 identity/권한/worker state로 사용하지 않는다.
2. 회사는 독립 local loopback/승인 IPC, 개인은 별도 self-host HTTPS. 같은 domain·API·schema이고 corpus·auth·backup·허용 inference는 분리한다. stateless는 cloud load balancing을 단순화하지만 company egress 허가를 만들지 않는다.
3. 연결할 때 전체 memory/컨벤션을 보내지 않는다. 짧은 고정 tool surface, 지원 host의 deferred schemas, 권한/적용조건 기반 선택 및 실제 payload budget을 사용한다. protocol stateless·discovery cache·prompt cache·context window는 각각 다른 문제다.
4. 루트 CLAUDE/AGENTS 본문·목록·import bridge 없이 승인 rule/skill 원문을 작업별 전달한다. 필수 규칙은 semantic top-k로 누락시키지 않는다. host adapter·capture·실행 강제는 MCP가 대신하지 않는다.
5. 실제 target host/version의 protocol·auth·capture·delivery matrix를 지원 기준으로 둔다. SDK2를 설치했다고 현재 모든 Claude/Codex surface가 modern protocol에 연결됐다고 하지 않는다. 소비자 없이 여러 adapter/compatibility shim/Code Mode execution 플랫폼을 선제 추가하지 않는다.

## 출처

- [S1] https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning
- [S2] https://modelcontextprotocol.io/specification/2026-07-28/changelog
- [S3] https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http
- [S4] https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/stdio
- [S5] https://modelcontextprotocol.io/specification/2026-07-28/deprecated
- [S6] https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.3.0 ; https://py.sdk.modelcontextprotocol.io/protocol-versions/ ; https://py.sdk.modelcontextprotocol.io/run/asgi/
- [S7] https://github.com/modelcontextprotocol/typescript-sdk/releases/tag/v2.3.1
- [S8] https://github.com/superlinked/sie/commit/c571e0a75d804cb6d49795a99cd03ea901307a69
- [S9] https://github.com/superlinked/sie/blob/c571e0a75d804cb6d49795a99cd03ea901307a69/packages/sie_mcp/README.md
- [S10] https://github.com/superlinked/sie/blob/c571e0a75d804cb6d49795a99cd03ea901307a69/packages/sie_mcp/src/sie_mcp/server.py ; https://github.com/superlinked/sie/blob/c571e0a75d804cb6d49795a99cd03ea901307a69/packages/sie_mcp/src/sie_mcp/config.py
- [S11] https://github.com/superlinked/sie/blob/c571e0a75d804cb6d49795a99cd03ea901307a69/packages/sie_mcp/src/sie_mcp/cli.py
- [S12] https://github.com/superlinked/sie/blob/c571e0a75d804cb6d49795a99cd03ea901307a69/packages/sie_mcp/pyproject.toml
