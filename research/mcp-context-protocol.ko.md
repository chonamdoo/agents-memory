# MCP 규격·stateless·tool discovery와 모델 context 비용

조사 기준: **2026-10-11**. 공식 MCP 규격·공식 SEP·공식 SDK 문서만 사실 근거로 사용했다. 로컬 MCP 설정/credentials를 읽거나 바꾸지 않았고, MCP 서버·모델 호출·빌드·테스트·token 측정은 실행하지 않았다. 이 문서는 **wire 규격과 SDK의 문서상 지원** 조사다. 특정 사용자 host가 어떤 입력을 모델에 넣는지는 별도 제품 근거/관찰이 필요하다.

## 1. 압축 결론

- 현재 공식 revision은 **`2026-07-28`, stage `Current`**다. **2026-07-28 공식 발표로 공개 출시된 새 규격**이며 실제로 stateless로 바뀌었다. `initialize`/`notifications/initialized` handshake와 protocol-level session/Mcp-Session-Id를 제거하고, 매 요청 `_meta`에 protocol version과 client capabilities를 전달한다. ‘새 버전이 없다’거나 아직 제안 단계라고만 설명하면 틀린다. [S1–S4, S18]
- 그러나 이 변화는 **서버의 세션 상태·load balancing·복원성** 문제를 해결한다. **tool schema와 결과를 모델 context에서 자동으로 없애는 규칙이 아니다.** 동일한 stateless 서버를 두 host가 써도 하나는 모든 schema를 모델에 넣고 다른 하나는 필요한 것만 넣을 수 있다. [S3, S9, S12]
- 확인한 공식 protocol 명명은 날짜 revision이다. `jsonrpc: "2.0"`은 **JSON-RPC 메시지 표준**이고, TypeScript/Python **SDK v2는 라이브러리의 major version**이다. ‘MCP 2.0’이라는 별도 정식 protocol version을 확인한 공식 versioning·latest·changelog·SEP에서는 찾지 못했다. **그 표현이 전 세계에 존재하지 않는다고 증명한 것은 아니다.** 누군가 최신 stateless 전환, SDK v2, host의 tool search/code mode를 통칭할 수 있으므로 해당 원문을 구별해야 한다. [S1–S5, S13–S16]
- **memory corpus 전체를 매 MCP 연결 시 전송하는 protocol obligation은 없다.** 초기 정보/능력 조회, tool 목록, resource metadata 목록, resource 내용 읽기, memory search 결과는 서로 다른 행위다. 전체 corpus가 노출된다면 거대한 instructions/description, export-all 도구 결과, host의 자동 resource ingestion 등 구체적 설계/제품 행동을 따져야 한다. [S6–S9, S12]
- 실제 context 절약은 **host의 progressive discovery/deferred injection**, 작은 tool 표면, 필요할 때만 bounded retrieval, 필요한 결과만 모델에 반환하는 실행 방식으로 만든다. MCP server가 description/임의 `_meta`를 제공한다고 표준 host의 defer를 강제할 수 있다는 근거는 확인하지 못했다. [S8, S9, S12]

공식 출시 발표는 “Today, we’re officially pushing the release button on the next version … `2026-07-28`”라고 명시한다. 게시일은 **2026-07-28**, metadata published timestamp는 **2026-07-28T09:00:00Z**다. 같은 발표의 Enrico Toniato testimonial이 “The new SDK v2”라고 표현한 대상은 **SDK**이며 별도 `MCP 2.0` protocol revision의 증거가 아니다. 또한 “Dropping the protocol-level session doesn’t force your application to be stateless”라고 명시한다. persistent memory·provenance·approval fencing은 transport session cache가 대신 해주는 기능이 아니라 application 설계 책임이다. [S18]

## 2. 날짜·stage·‘2.0’의 서로 다른 의미

| 대상 | 확인된 공식 문구 / 상태 | 정확한 의미와 경계 |
|---|---|---|
| MCP protocol versioning | “following the format `YYYY-MM-DD`”; “The **current** protocol version is **2026-07-28**.” | backwards-incompatible 변경일 기반 문자열. `Current`는 사용 준비된 현재 규격이며 backwards-compatible 변경은 계속 가능하다. `Final`은 변경하지 않는 과거 규격; `Draft`는 아직 소비 준비가 안 된 진행 중 규격이다. [S1] |
| latest alias | `specification/latest/index.md`가 `specification/2026-07-28.md`로 해석됨 | 조회 당시 latest와 dated Current가 일치했다. 별도 `2.0` revision이 아니다. [S2] |
| JSON-RPC 2.0 | “All messages … **MUST** follow the **JSON-RPC 2.0** … specification.” | MCP wire 메시지 envelope의 표준. `jsonrpc:"2.0"`과 MCP protocolVersion `2026-07-28`은 별개 필드/버전이다. [S3] |
| SEP-2575 Make MCP Stateless | **Status: Final; Type: Standards Track; Created: 2025-06-18** | Created는 SEP 파일에 적힌 생성일이며 구현 출시일/merge일이 아니다. 현재 changelog가 SEP-2575를 규격 변경으로 연결한다. SEP 본문에 남은 “current … not stateless”는 변경 전 문제 설명이지 최신 규격 상태가 아니다. [S4, S5] |
| TypeScript SDK v2 | “v2 of the SDK … the stable release line, implementing … 2026-07-28”; README가 v2 release **2026-07-27** 명시 | `@modelcontextprotocol/server`/`client` 등 패키지의 major generation. v1.x는 별도 유지보수 branch. **v2 설치만으로 최신 wire 사용이 자동 보장되지 않는다.** [S13, S14] |
| Python SDK v2 | “v2 is the stable line”; “`pip install mcp` installs 2.x”; “v2 speaks the 2026-07-28 revision” | SDK와 protocol의 두 변화가 동시에 있었음을 공식 문서가 명시한다. modern과 legacy를 함께 지원하지만 old host의 요청을 modern으로 강제 승격한다는 뜻은 아니다. [S15] |
| ‘MCP 2.0’ | 공식 날짜 versioning/현재 latest/changelog/SEP에 별도 protocol version명으로 확인되지 않음 | 조사 범위 안의 명명 결과다. marketing/커뮤니티 표현 전체의 부재, 모든 future draft의 부재, 특정 host 지원의 부재를 주장하지 않는다. |

확인한 검색도 공식 도메인에 제한했다: `site:modelcontextprotocol.io "MCP 2.0"` 결과는 JSON-RPC 2.0을 쓰는 규격 페이지와 Java SDK `2.0.0` 문서 등을 반환했다. **검색의 부정 결과만으로 부재를 입증하지 않고**, 위 positive versioning 문구를 결론 근거로 쓴다.

## 3. wire와 모델 입력은 어디서 갈리는가

### 3.1 legacy와 modern의 초기 행위

**2025-11-25 및 이전**: initialization이 첫 interaction이어야 한다. client는 `initialize`에 protocolVersion·client capabilities·clientInfo를 보내고, server는 protocolVersion·server capabilities·serverInfo·optional `instructions`로 답한다. 이후 client가 `notifications/initialized`를 보낸다. 이 초기 교환의 예제에는 memory corpus나 모든 tool schema/resource body를 포함하는 필드가 없다. Tool/resource 발견·읽기는 별도 RPC다. [S6, S8, S9]

**2026-07-28**: handshake 없이 요청마다 `io.modelcontextprotocol/protocolVersion`과 `io.modelcontextprotocol/clientCapabilities`를 `_meta`로 전달한다. `clientInfo`는 **SHOULD**, 필수는 아니다. 최신 basic 문서의 Required 표가 이를 분명히 구별한다. HTTP는 protocol version을 `MCP-Protocol-Version`에도 싣는다. [S3, S4]

`server/discover`는 **server가 MUST 구현**, **client 호출은 optional**인 RPC다. supportedVersions·capabilities·server identity metadata·optional instructions와 caching hints를 반환한다. tools나 corpus 전체를 반환하는 RPC가 아니다. Dual-era stdio client의 legacy 판별 probe 등에는 호출을 권장한다. [S7, S16]

### 3.2 행위별 전달 내용과 모델 context 경계

| 행위 | client↔server wire 내용 | 모델 입력에 관한 규격/공식 문서 경계 |
|---|---|---|
| legacy `initialize` / modern `server/discover` | protocol version·capabilities·identity·optional server instructions | instructions는 자연어 guidance다. SEP의 설명은 “can be used by clients … (e.g., by including it in a system prompt)”이다. **가능한 host 사용 방식**이지 모든 host가 MUST system prompt에 넣는 규칙이 아니다. [S5–S7] |
| `tools/list` | tool 이름·설명·inputSchema·optional outputSchema/annotations 등; nextCursor 및 modern cache hints | metadata/schema 목록은 client로 전송된다. 모델에 언제/어떤 tool 정의를 넣는지는 host 구현 문제다. official progressive-discovery 문서가 client fetch와 model injection을 명시적으로 분리한다. [S8, S12] |
| `tools/call` | name·arguments를 보내고 content/structuredContent 등 결과를 받음 | 일반 direct tool loop에서는 결과를 모델로 보내는 흐름이 있으나, official client guide는 sandbox/code mode에서 중간 결과를 모델에 넣지 않고 최종 출력만 전달하는 구현도 설명한다. **모든 wire result = 모든 모델 입력**으로 동일시하면 안 된다. [S8, S12] |
| `resources/list` / templates list | URI·이름·설명·mimeType 등 resource metadata 또는 URI template | resource 본문과 다르다. 모든 resource를 읽거나 모델에 넣도록 요구하지 않는다. [S9] |
| `resources/read` | 지정 URI를 요청하고 contents(text/blob 등)를 받음 | “host applications determining how to incorporate context”가 공식 문구. UI 명시 선택, 검색/필터, heuristic/model 기반 자동 inclusion이 모두 가능한 예다. URI 하나의 read가 여러 contents를 반환할 수도 있으므로 작은 URI 개수가 작은 내용량을 보장하지 않는다. [S9] |
| pagination | 한 페이지 + opaque nextCursor, 이후 client가 cursor로 이어서 요청 | **wire response를 chunk로 나누는 기능**이다. model-context relevance 검색·top-k selection·lazy injection 보장이 아니다. [S10, S14] |
| modern caching | server가 `ttlMs`/`cacheScope` freshness/scope hints 제공; client가 RPC 결과를 재사용 | “reduce unnecessary re-fetching”이 목적. host cache에 저장한 schema를 모델에 다시 넣는 것과 별개다. prompt cache와도 별개다. [S11, S12] |

host architecture는 LLM integration 및 “Manages context aggregation across clients”를 **host 역할**로 둔다. 서버는 전체 대화를 원래 모두 보는 위치가 아니며, “Full conversation history stays with the host”라고 명시한다. MCP protocol session의 수명, 대화의 수명, 모델 호출의 입력은 동일 개념이 아니다. [S17]

## 4. stateless가 바꾸는 것 / 바꾸지 않는 것

### 바뀐 것 — 규격에 포함됨

현재 basic 문구는 “MCP is a **stateless protocol**: all the information needed to process a request is contained in the request itself.”이다. server는 같은 connection의 과거 요청으로 protocolVersion/capabilities/client identity를 추론하면 안 된다. cross-request application state는 client가 각 요청에 넘기는 명시적 identifier로 참조한다. open STDIO process나 connection이 곧 conversation/session이라는 보장도 없다. [S3]

changelog는 다음을 명시한다. [S4]

1. protocol-level session 및 HTTP `Mcp-Session-Id` 제거;
2. initialize handshake 제거, per-request metadata 및 `server/discover` 추가;
3. server-initiated requests 대신 MRTR `InputRequiredResult`/재요청 방식;
4. subscriptions/listen을 통한 요청 범위 알림 스트림;
5. list/resource 결과의 cache hints 및 deterministic tool ordering.

SEP의 동기는 load balancing·sticky sessions·server failure 복구·per-client state 관리 복잡성이다. **LLM tool schema token 절약을 stateless의 보장으로 제시한 것이 아니다.** [S5]

### 바뀌지 않은 것 — 자동 context 절약이라고 말할 근거 없음

- protocol metadata를 요청마다 붙이는 것은 **wire 정보의 위치 이동**이다. 모델 context에서 instructions/schema/result를 지우라는 규칙이 아니다.
- `tools/list`는 여전히 available tools의 schema 목록을 반환한다. 최신 tools 문구가 deterministic ordering의 이점을 “improves LLM prompt cache hit rates **when tools are included in model context**”라고 조건부 표현한다. [S8]
- modern list set은 authorization에 따라 달라질 수 있지만 connection별로 달라지거나 같은 connection의 다른 요청 부작용으로 바뀌면 안 된다. ‘처음엔 한 도구만 내보내고 search를 한번 호출하면 이 connection에서 나머지를 reveal’하는 구현을 곧바로 stateless 표준 progressive discovery로 간주하면 안 된다. Host-side catalog와 deferred injection은 다른 층이다. [S8]
- `ttlMs`는 context window에서 token을 빼는 필드가 아니다. positive TTL에서도 변동 가능하며 freshness hint이지 불변성/무과금 보장이 아니다. [S11]

## 5. context 절약의 실제 공식 설계 위치

공식 Client Best Practices에는 다음 세 문장이 연속으로 있다. [S12]

> “The host fetches tool definitions via `tools/list` as normal, but defers injecting them into the model's context.”
>
> “The host provides a lightweight `search_tools` meta-tool to the model.”
>
> “The host loads full definitions into context only as needed.”

이것이 **host의 tool discovery**다. memory database에서 relevant records를 찾는 **corpus retrieval**과 검색 대상 자체가 다르다. 한 서버의 도구가 적다면 모두 upfront 제공해도 합리적일 수 있다는 문서의 반례도 함께 읽어야 한다. 많은 서버/많은 schema일 때 progressive discovery가 특히 유용하다.

문서는 host-side schema memoization에 대해 “This is separate from what's currently in the model's context.”라고 명시한다. 또한 code mode/programmatic calling은 host가 sandbox를 구현해야 하며, 중간 결과는 sandbox 안에서 조합/필터하고 최종 return/log만 모델에 넣는 방식이다. **MCP 서버를 연결했다는 이유만으로 이 sandbox가 생기지 않는다.** [S12]

Prompt caching의 한계도 공식 문서에 있다. tool array를 대화 중 추가/제거하면 provider의 prompt-prefix cache를 무효화하여 예상보다 비쌀 수 있다. 문서는 cache breakpoint 뒤에 새 정의를 append하거나 안정된 `call_tool({name,args})` meta-tool 등 전략을 안내한다. **RPC 결과 캐싱, prompt-prefix 캐시, context에 아예 안 넣기**는 각각 다른 절약이며, 이 조사에서는 특정 provider의 요금·cache capacity 계약이나 사용자의 절약률을 측정하지 않았다. 문서 그림의 token 숫자는 이 memory 설계에 대한 실측으로 재사용하지 않았다. [S11, S12]

### 서버가 host tool-defer를 강제할 수 있는가

**검토한 core 규격에는 해당 강제 계약을 확인하지 못했다.** Tools는 model-controlled를 의도하지만 “protocol itself does not mandate any specific user interaction model”이라고 명시한다. Resource audience/priority annotations도 “hints to clients”이다. server instructions는 optional guidance이고 임의 metadata만으로 host의 model-input pipeline을 바꾸는 상호운용 보장이 되지 않는다. [S5, S7–S9]

서버가 **제공량을 직접 줄일 수는** 있다. 짧은 instructions, 작고 안정적인 tool 표면, 검색 결과의 bounded size, resource_link/record handle로 상세 내용 읽기 분리 등이 그렇다. 이는 server/API 설계 효과다. 원하는 host가 지원하지 않는 ‘defer’를 원격 서버가 강제했다는 뜻은 아니다. Resource link는 client가 fetch할 수 있는 URI를 전달하며 실제 본문과 다르고, link가 resources/list에 꼭 등장하는 것도 아니다. [S8]

## 6. 특히 중요한 반례 / 지원 판정

| 과도한 주장 | 공식 반례 / 판정 |
|---|---|
| ‘새 stateless는 아직 SEP라 실제 규격이 아니다’ | 현재 versioning이 2026-07-28을 Current로 명시하고 changelog/basic에 통합됐다. SEP-2575도 Final이다. **현재 규격에는 지원됨.** [S1, S3–S5] |
| ‘SDK v2면 wire도 최신이고 모든 host가 modern이다’ | TS migration: “Nothing in v2 puts a 2026-07-28 byte on the wire by default”; default Client는 legacy initialize. `versionNegotiation` auto/pin, modern HTTP `createMcpHandler`, modern stdio `serveStdio` 등의 선택을 따로 설명한다. Python은 default modern probe/fallback 및 dual-era를 문서화한다. **SDK별 지원·default가 다름; 제품 전반 지원은 불확정.** [S14–S16] |
| ‘페이지를 잘게 쪼개면 모델에는 일부 도구만 들어간다’ | TS v2 `listTools()`를 cursor 없이 부르면 **auto-aggregate every page**한다. Wire pagination이 host lazy injection을 보장하지 않는 명확한 반례다. **pagination 지원, 자동 context selection 보장은 아님.** [S10, S14] |
| ‘stateless_http 옵션은 최신 protocol stateless와 같다’ | Python v2 문서는 `stateless_http=True`가 **2025-era clients serving에만 영향**, 2026 traffic은 이를 읽지 않는다고 구별한다. legacy transport/session 관리 옵션과 새 core stateless를 혼동하지 않는다. [S15] |
| ‘연결하면 corpus가 무조건 전송된다’ | resources/list는 metadata; read는 별도. 반대로 host는 heuristic/model 선택 기반 **automatic context inclusion**도 구현할 수 있으며 URI 하나의 read가 여러 contents를 반환할 수 있다. **protocol 의무 아님; 특정 host 자동 ingestion은 불확정.** [S9] |
| ‘cache hints만 있으면 tokens가 안 든다’ | 캐시 목적은 재조회 감소. host가 같은 정의를 다시 model tools array에 넣을 수 있다. provider prompt caching도 prefix 변경으로 깨질 수 있다. **wire caching 지원, 자동 zero-context/zero-cost 보장은 미지원.** [S11, S12] |
| ‘모든 annotations/instructions가 모델 context를 통제한다’ | optional guidance/hints이며 host가 aggregate/LLM integration을 관리한다. **표준 host defer 강제 계약은 확인하지 못함.** [S5, S7–S9, S17] |

문서상 작은 불일치도 숨기지 않는다. 현재 specification overview의 Extensions 문단에는 여전히 “negotiated during initialization”이라는 표현이 보였다. 반면 authoritative basic/versioning/current changelog는 handshake 제거와 per-request capabilities를 명시한다. 이 잔존 문구 하나를 근거로 ‘현재도 mandatory initialize’라고 해석하지 않았다. Similarly, tools/resources 예제 안내에서 clientInfo를 필수 `_meta`와 함께 나열하지만 basic Required 표는 clientInfo를 optional/SHOULD로 구별한다. 구현 계약에는 상세 basic/versioning의 명시적 필수 조건을 적용한다. [S2–S4, S8, S9, S16]

## 7. 독립 memory service + local/self-host cloud 설계에 적용

아래는 protocol facts로부터의 **[INFERENCE: 설계 권고]**이며 이번 조사에서 memory 구현/runtime를 확인한 결과는 아니다.

1. **corpus 크기와 bootstrap context 크기를 분리**한다. 서비스 DB에 쌓인 전체 memory는 보관 상태이고, 작은 tool schema/instructions와 검색 결과만 client에 전달하도록 API를 설계한다. corpus text를 schema description이나 server instructions에 붙이지 않는다.
2. 안정된 소수의 memory search/read/write 도구를 제공한다. 검색은 record ID/짧은 요약/근거 위치를 반환하고 필요한 record만 상세 조회한다. DB 전체 export와 매-turn retrieval은 자동으로 하지 않는다. 고정된 token 절약률은 주장하지 않는다.
3. local과 cloud에서 같은 작은 도구 표면을 유지하면 host가 eager일 때도 불필요한 schema 비용을 제한할 수 있다. 하지만 **최종 비용은 host가 instructions/schema/results를 모델에 넣는 방식과 각 결과 길이에 달린다.** self-host 위치만 바꿔서는 이 부분이 바뀌지 않는다.
4. ‘2026-07-28 modern 지원’, ‘legacy dual-era 지원’, ‘host tool search/defer 지원’, ‘memory corpus retrieval 크기’, ‘provider prompt cache’를 **각각 acceptance 항목**으로 기록한다. latest spec/current SDK 지원이 특정 installed host의 지원 증거가 되지 않는다.
5. cloud scale-out에서 protocol session 제거는 이점이다. 사용자/회사 scope·conversation handle·authorization은 여전히 명시적이어야 하며 application-level persistent memory가 사라지는 것은 아니다. stateless는 **memory가 없는 서비스**라는 뜻이 아니다.
6. 개인/회사 memory의 modern cached read/list가 사용자별이면 `cacheScope:"private"`를 올바르게 사용하고, 접근 통제 자체는 따로 구현한다. cacheScope만으로 unauthorized retrieval을 막는 보장은 없다. [S11]

## 8. 원문 출처 및 고정 provenance

모든 URL은 조사일 직접 읽은 primary source다. 아래 dated site 경로도 Current 문서라 backwards-compatible 수정될 수 있다. 고정 가능한 핵심 규격 자료는 GitHub API에서 조사 기준일까지의 default-branch 최신 commit을 얻어 pin했다.

- MCP repository pin: **`1f520964b295d58494d944f2aea8a5ab51c79f77`**, commit timestamp **2026-10-11T04:39:32Z**. API: https://api.github.com/repos/modelcontextprotocol/modelcontextprotocol/commits?until=2026-10-11T23%3A59%3A59Z&per_page=1
- TypeScript SDK pin: **`b022522089a0c8b632595c6e7b536453945ed5a9`**, commit timestamp **2026-10-05T14:38:02Z**. API: https://api.github.com/repos/modelcontextprotocol/typescript-sdk/commits?until=2026-10-11T23%3A59%3A59Z&per_page=1
- 위 timestamp는 source commit 시각이지 MCP release 시각/SDK package publish 시각이 아니다. Pin 링크는 직접 읽은 파일에 한해서 아래에 적었다. 기타 SDK/site 문서는 조사일 읽은 live 문서이며 독립 snapshot을 만들지 않았다.

### 공식 source 목록

- **S1 Versioning**: https://modelcontextprotocol.io/docs/2026-07-28/learn/versioning.md — Current 및 날짜 version format. [직접 읽은 pin](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/1f520964b295d58494d944f2aea8a5ab51c79f77/docs/docs/2026-07-28/learn/versioning.mdx)
- **S2 Specification/latest**: 요청 URL https://modelcontextprotocol.io/specification/latest/index.md → 응답 URL https://modelcontextprotocol.io/specification/2026-07-28.md — overview 및 JSON-RPC와 host/client/server 구분.
- **S3 Basic overview**: https://modelcontextprotocol.io/specification/2026-07-28/basic/index.md — Messages, Statelessness, `_meta` Required 표.
- **S4 Key Changes**: 요청 URL https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/changelog.mdx . [직접 읽은 pin](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/1f520964b295d58494d944f2aea8a5ab51c79f77/docs/specification/2026-07-28/changelog.mdx)
- **S5 SEP-2575**: 요청 URL https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/2575-stateless-mcp.md . [직접 읽은 pin](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/1f520964b295d58494d944f2aea8a5ab51c79f77/seps/2575-stateless-mcp.md) — Final/Standards Track/Created, motivation, optional instruction 설명.
- **S6 Legacy lifecycle**: https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle.md — mandatory initialize 및 응답 instructions.
- **S7 Discovery**: https://modelcontextprotocol.io/specification/2026-07-28/server/discover.md — MUST implement/MAY call 및 instructions.
- **S8 Tools**: https://modelcontextprotocol.io/specification/2026-07-28/server/tools.md — list/call, schema, deterministic ordering, per-connection 제한, resource links와 structured results.
- **S9 Resources**: https://modelcontextprotocol.io/specification/2026-07-28/server/resources.md — application-driven incorporation, metadata list/read body 분리, multi-content read, annotation hints.
- **S10 Pagination**: https://modelcontextprotocol.io/specification/2026-07-28/server/utilities/pagination.md — opaque cursor, server page size, list operations.
- **S11 Caching**: https://modelcontextprotocol.io/specification/2026-07-28/server/utilities/caching.md — ttlMs/cacheScope, cache key, private scope, access control 경계.
- **S12 Client Best Practices**: https://modelcontextprotocol.io/docs/2026-07-28/develop/clients/client-best-practices.md . [직접 읽은 pin](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/1f520964b295d58494d944f2aea8a5ab51c79f77/docs/docs/2026-07-28/develop/clients/client-best-practices.mdx) — progressive discovery, host-side caching 분리, prompt-cache 주의, code mode.
- **S13 TypeScript SDK README**: https://github.com/modelcontextprotocol/typescript-sdk/blob/main/README.md . [직접 읽은 pin](https://github.com/modelcontextprotocol/typescript-sdk/blob/b022522089a0c8b632595c6e7b536453945ed5a9/README.md) — stable SDK v2, release 2026-07-27, protocol revision 구현.
- **S14 TypeScript SDK migration**: https://ts.sdk.modelcontextprotocol.io/v2/migration/upgrade-to-v2.md 및 https://ts.sdk.modelcontextprotocol.io/v2/migration/support-2026-07-28.md — list auto-aggregation 및 latest wire opt-in.
- **S15 Python SDK v2**: https://py.sdk.modelcontextprotocol.io/whats-new/ — stable line, SDK/protocol 구별, default modern probe/fallback, stateless_http의 legacy 한정 의미; README https://github.com/modelcontextprotocol/python-sdk/blob/main/README.md 도 읽음.
- **S16 Versioning/compatibility**: https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning.md 및 https://ts.sdk.modelcontextprotocol.io/v2/protocol-versions.md — modern/legacy/dual-era matrix 및 TypeScript default legacy/auto/pin.
- **S17 Architecture**: https://modelcontextprotocol.io/specification/2026-07-28/architecture/index.md — host context aggregation 및 full conversation 경계.
- **S18 Official release announcement**: https://blog.modelcontextprotocol.io/posts/2026-07-28/ — “The 2026-07-28 Specification”, David Soria Parra/Den Delimarsky (Lead Maintainers), 2026-07-28 공개 발표; stateless core 출시, updated SDKs, list caching/ordering, application state와 protocol session 분리. SDK v2 testimonial의 package-size/speed 수치는 해당 당사자의 주장일 뿐 이 memory service의 context/token 실측이나 보편 효과로 사용하지 않았다.

보조 발견: https://modelcontextprotocol.io/llms.txt 및 https://modelcontextprotocol.io/docs/2026-07-28/sdk.md 로 공식 페이지/SDK 위치를 확인했다. 읽기를 시도한 Python v1 `https://py.sdk.modelcontextprotocol.io/v1/server/streamable-http/`는 404라 근거로 사용하지 않았다. legacy stateless_http 의미는 성공적으로 읽은 S15에 이미 명시돼 있다.
