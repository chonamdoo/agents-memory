# MCP context 비용: host의 Tool Search와 Code Mode — 2026-10-11

## 결론

MCP 서버에 연결했다고 저장된 memory corpus 전체가 모델 입력에 들어가는 것은 아니다. 다만 host가 도구 정의를 전부 넣거나, 시작 instructions를 길게 넣거나, memory 검색 결과·원문·출처를 많이 반환하면 context를 소비한다. **도구 정의를 늦게 공개하는 Tool Search, 결과를 실행 환경에서 걸러 내는 Code Mode, 반복 입력의 계산·가격을 줄이는 prompt caching은 서로 다른 기능**이다. 이들을 하나의 새 프로토콜이나 모든 MCP client에 자동 적용되는 기능으로 설명하면 안 된다.[S1–S5, S9–S12]

현재 Claude Code/Agent SDK는 지원 환경에서 Tool Search를 기본으로 사용한다. `auto`의 10% 기준은 선택 가능한 모드이지 현재 unset 기본값이 아니다. OpenAI Responses API와 Agents API는 설정 방식이 서로 다르다. Codex CLI는 API 문서에서 유추한 것이 아니라 **공식 release 0.162.1의 고정 source**에서 client-executed BM25 Tool Search와 MCP deferral을 직접 확인했다. 설치된 사용자의 binary/model/provider/config 동작은 확인하지 않았다.[S1–S4, C1–C8]

**[제안] 작은 memory service는 짧은 `search`/`get`/`write` 등 제한된 도구와 서버 측 검색·분량 제한부터 시작하는 편이 낫다.** 수백 개 도구, 반복 조회, 다중 서비스 join, 큰 중간 결과를 위한 Code Mode는 유용하지만, memory 검색 한 번과 짧은 결과 반환을 위해 처음부터 범용 코드 실행 플랫폼을 만들 필요는 없다. Anthropic의 현재 PTC 문서도 작은 응답/적은 호출을 weak fit으로 규정하고, 특정 sequential benchmark에서 비용 증가를 보고한다.[S2, S6, S11]

## 조사 범위와 근거 수준

- 기준일: 2026-10-11. 공식 제품 문서, Anthropic/Cloudflare engineering 글, OpenAI 공식 GitHub source/release metadata만 사실 근거로 사용했다.
- 문서의 **제품 계약**, 고정 source의 **정적 구현**, vendor의 **사례 수치**, 이 memory service에 대한 **설계 제안**을 분리한다.
- Codex source는 release `rust-v0.162.1`의 commit `092d3acd6bec3e3a14bdc7e7a2810ab628ab759d`에 고정했다. tag의 commit은 GitHub API로 확인했다.[C1–C2]
- 웹 문서는 기준일에 읽은 가변 문서다. 영구 revision이라고 주장하지 않는다. Claude 문서에 명시된 version floor는 해당 옵션에만 적용한다. Tool Search 전체의 최초 지원 버전으로 일반화하지 않는다.
- 사용자 설치 client, user config, 계정·credentials는 읽거나 바꾸지 않았다. MCP 연결/모델 API 호출, token 측정, build/lint/test/formatter를 실행하지 않았다. 저장소 제품의 실제 절감률은 미측정이다.

## 1. 어느 비용을 줄이는가

| 층 | 모델 context와 관계 | Tool Search | Code Mode | Prompt caching |
|---|---|---|---|---|
| 서버 연결·protocol session | host↔server의 통신 상태. host가 받은 자료 중 무엇을 모델에 넣을지는 별도 | 모든 schema가 모델에 들어가는 시점을 늦춘다. 서버 통신이 없어진다는 뜻은 아니다 | client/server 어느 쪽에 실행 환경을 둘지 구현에 따라 다르다 | 통신 session 자체를 캐시한다는 뜻이 아니다 |
| 도구 catalog/schema | 이름·설명·입력 schema·서버 guidance 등 | 필요한 정의만 공개. 요약/이름/instructions가 남고, 찾은 schema는 context를 쓴다 | 전체 API를 처음부터 typed description에 넣는 구현과 검색형 공개 구현을 구분해야 한다 | 같은 prefix를 재사용할 때 계산·과금 할인 |
| memory corpus | 서버 저장 자료. 검색하지 않은 corpus는 도구 정의가 아니다 | corpus 검색·압축 기능이 아니다 | 데이터 조회·필터 코드로 간접 접근할 수 있다 | 영구 memory 저장/검색 서비스가 아니다 |
| 도구 결과·인용 출처·resource attachment | host가 모델에 넣으면 입력이 된다 | 큰 결과를 작게 바꾸지 않는다 | 중간 결과를 sandbox에 두고 필요한 필드/집계만 출력할 수 있다 | 결과가 prefix에 남아 있으면 재사용 가능하지만 context 내용은 남는다 |
| 최종 답변/추론/코드 | 모델이 생성하는 토큰 | 검색 단계가 추가될 수 있다 | 코드 생성·실행 결과·오류·로그도 비용을 만든다 | 새로 생성되는 내용까지 무료로 만드는 것은 아니다 |

위 표는 공식 문서의 동작을 비교한 해석이다. `context tokens`를 네트워크 전송 bytes나 billed uncached input과 동일한 수치로 계산하지 않는다.[S1–S12]

## 2. Claude Code와 Claude Agent SDK

### 2.1 현재 기본값과 auto 기준

Claude Code의 현재 문구는 **“Only tool names and server instructions load at session start”**, **“Tool search is enabled by default”**다. 이름·서버 instructions는 시작 입력에 남으므로 도구가 수천 개이거나 instructions가 길면 overhead가 0은 아니다. MCP tool description과 서버 instructions는 각각 기본 **2,048 characters**에서 잘린다. 이것은 token budget이 아니다. `CLAUDE_CODE_MAX_MCP_DESCRIPTION_LENGTH`로 조정하는 기능은 v2.1.280 이상이다.[S1]

| `ENABLE_TOOL_SEARCH` | 현재 문서상의 의미 |
|---|---|
| unset | 지원 환경에서는 MCP 정의를 deferred loading. 특정 provider/model/proxy 조건에서는 upfront fallback |
| `true` | Tool Search를 강제하지만 모델/serving stack의 실제 미지원은 해결하지 못한다. 지원하지 않는 proxy를 통과시키면 요청 실패 가능 |
| `auto` | **defer 가능한 정의**의 합이 model context window의 10% 미만이면 upfront, 10% 이상이면 deferral |
| `auto:N` | 같은 비교에서 사용자 지정 비율. Claude Code 문서는 N=0–100을 명시 |
| `false` | upfront loading. Agent SDK 문서는 모든 turn에서 정의를 로드한다고 명시 |

Agent SDK의 `auto` 합산 대상은 remote/custom SDK MCP tool 중 `alwaysLoad`가 아닌 정의와 on-demand built-in 도구들이다. Bash/Read/Edit 같은 core built-in은 upfront이며 threshold에 포함하지 않는다. plugin mod에 의한 exposure 변경도 합산에 영향을 준다. 따라서 서버 개수·memory record 개수·한 서버만의 token count에 대한 10% 기준이라고 읽으면 틀린다.[S2]

### 2.2 모델·provider·version 경계

- Claude Code/Agent SDK 문서의 최소 model generation은 **Sonnet 4.5, Haiku 4.5, Opus 4.5와 이후 지원 모델**이다. API 문서의 현재 explicit list는 Fable/Mythos 5.1·5, Opus 5.5·5·4.8·4.7·4.6·4.5, Sonnet 5.5·5·4.6·4.5, Haiku 5.5·4.5다. Opus 4.1 이하 미지원이라고 명시한다. 목록의 Sonnet 4.5는 deprecated 표시도 있다. 계정에서 실제 선택할 수 있는지는 별도다.[S1–S3]
- Google Cloud Agent Platform은 4.5 generation 이상이면 기본 지원, 이전 generation은 beta header를 거절하는 serving stack 때문에 upfront. `ENABLE_TOOL_SEARCH=true`도 이 이전 generation 제한을 해제하지 않는다. v2.1.221 이전의 Google Cloud 기본 동작은 달랐다.[S1–S2]
- Microsoft Foundry **Hosted on Azure** deployment는 server-side 거절 후 upfront fallback. Foundry 모든 hosting 형태가 미지원이라는 뜻은 아니다.[S1–S2]
- non-first-party `ANTHROPIC_BASE_URL`이면 proxy가 `tool_reference`를 전달하지 않는 경우가 많아 기본 off. override는 기능 호환성을 보장하지 않는다.[S1–S2]
- `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS`는 Tool Search를 꺼 둔다. 개인 `ENABLE_TOOL_SEARCH`로 재활성화할 수 없다. 조직 managed override의 version floor는 v2.1.227이다.[S1–S2]

### 2.3 `alwaysLoad`는 검색/권한/캐시 옵션과 다르다

- host의 서버 config `alwaysLoad:true`: 서버 도구를 upfront로 노출한다. 작은 핵심 도구를 매 turn 쓰는 경우에 적합하다. startup도 해당 서버 도구를 기다리며 기본 5초 connect timeout 상한을 적용한다. 유효한 discovery cache가 있으면 cache가 도구를 공급한다.[S1]
- 서버가 tool `_meta["anthropic/alwaysLoad"]=true`를 주면 해당 도구가 upfront다. 이 annotation 자체는 startup을 기다리게 하지 않는다. host가 서버 전체를 defer하면 덮어쓸 수 있다.[S1]
- 서버 `_meta["anthropic/alwaysLoad"]=false`가 host `alwaysLoad:true`를 이기는 것은 **`--mcp-config`, Agent SDK application, plugin 공급 서버**에 적용되는 좁은 조건이다. 다른 서버는 upfront. 이 세부 기능은 v2.1.285 이상이다.[S1]
- host 서버 config `alwaysLoad:false`: 서버 작성자가 upfront라고 표시한 도구까지 모두 검색 뒤로 미룬다. v2.1.287 이상. 값을 생략하면 작성자 upfront annotation은 유지된다.[S1]
- 발견되었다고 호출 권한까지 승인된 것이 아니다. SDK는 MCP 실행에 explicit permission을 요구하며 `allowedTools`/`disallowedTools`를 별도로 적용한다.[S13]

`alwaysLoad`는 Anthropic host extension이다. 다른 MCP host가 같은 의미로 처리한다고 광고하면 안 된다.

### 2.4 찾은 schema의 수명, cache, resource와 결과 한계

Agent SDK 공식 문구: **“where they stay available for subsequent turns until the SDK compacts the messages where the agent discovered them.”** 기본 검색 결과는 관련 도구 최대 5개이며, 발견 메시지가 compact되면 필요할 때 다시 검색한다. catalog 상한은 10,000개다. 이는 매 turn 한 번 쓰고 schema가 자동 제거되는 방식도, 영구적으로 모든 새 세션에 보존되는 방식도 아니다.[S2]

Tool Search는 검색할 때 추가 round-trip을 만든다. SDK는 짧은 정의를 가진 약 10개 미만의 도구이면 전부 upfront하는 편이 대체로 빠르다고 설명한다. 이 숫자는 실측한 memory service의 절대 경계가 아니다.[S2]

별도의 **MCP discovery cache**는 remote HTTP/SSE 도구 목록을 이전 연결에서 저장해 startup의 실제 연결을 첫 호출까지 늦출 수 있다. v2.1.221 이상. 현재 gradual rollout 외에는 기본 off이며 `MCP_DISCOVERY_CACHE=1/0`으로 선택한다. v2.1.238 이전에는 기본 on이었다. 이 cache는 schema를 모델 context에 언제 공개하는 Tool Search와도, 모델 prompt cache와도 다르다.[S1]

Tool Search는 MCP resources/prompt/result 본문을 자동 압축하는 계약이 아니다. Claude Code에서 `@server:uri`로 참조한 resource는 **“automatically fetched and included as attachments when referenced”**다. list/read resource 도구가 있다고 corpus 전체가 자동 첨부되는 것도 아니다. interactive `list_changed` refresh는 tools/prompts/resources를 갱신하지만 headless/Agent SDK는 tool list만 refresh한다.[S1]

MCP 결과의 별도 host 한계도 남는다.[S1, S13]

- 10,000 tokens 초과 경고, 기본 최대 25,000 tokens.
- 기본 한계 초과의 성공 no-image 결과는 파일에 보관하고 경로를 모델에 알려 필요 부분을 읽게 한다. 별도 annotation이 없는 성공 text는 50,000 characters 초과에서도 파일로 간다. token setting만 올려도 character 기준은 그대로다.
- tool이 `anthropic/maxResultSizeChars`를 선언하면 text limit은 그것을 따르고, image 결과는 여전히 token limit 대상이다.
- HTTP/SSE의 decompressed JSON body 또는 event가 16 MB를 넘으면 읽기를 중단하고 요청이 실패한다. 서버에서 pagination이 필요하다.

이런 file spill은 서버의 ACL·검색 정확도·출처 유지·결과 예산을 대신하지 않는다. 나중에 파일을 크게 읽으면 그만큼 모델 context를 다시 소비한다. SDK 페이지는 대체 결과를 “error message”라고 부르고 MCP reference는 경로를 포함한 “message”라고 설명하므로, 성공 내용이 원래 형태 그대로 모델에 들어간다고 가정하지 않는다.

## 3. OpenAI Responses API, Agents API, Codex CLI

### 3.1 Responses API

공식 문구는 **“only `gpt-5.4` and later models support `tool_search`”**다. request `tools`에 `{ "type":"tool_search" }`를 넣고 deferred function 또는 MCP server definition에 `defer_loading:true`를 표시한다. namespace object 자체에 표시하는 것이 아니라 내부 function에 표시한다.[S4]

- **hosted search**: request에 전체 후보 inventory를 선언하고 OpenAI가 선택한다.
- **client-executed search**: 모델이 `tool_search_call`을 출력하면 application이 찾고 `tool_search_output`을 돌려준다. project/tenant 상태에 따른 발견에 적합하다.
- 개별 deferred function은 시작부터 이름·설명이 보여서 실질적으로 parameter schema를 미룬다. namespace/MCP grouping이면 시작에는 그룹 이름·설명만 보이고 내부 정의를 필요할 때 공개한다. grouping 자체가 모든 metadata 비용을 0으로 만들지는 않는다.
- namespace 당 10개 미만의 function을 권장한다. 전체 corpus record 수에 대한 제한이 아니다.
- 발견한 도구는 `tool_search_output.tools`에 들어가 이후 turn에도 호출 가능하다. client가 매번 같은 정의를 다시 load할 필요는 없다. 기존 loaded set을 바꾸면 그 지점부터 cache가 깨진다. 수동 conversation round-trip이면 loading item과 순서를 보존해야 한다.
- 정의를 context 끝에 추가하므로 기존 prefix cache를 유지하는 설계다. 새 schema와 search call/output 자체는 입력을 소비한다. 원래 목록에 없던 schema를 client search로 주입할 수 있는 advanced 방식은 신뢰된 정의만 노출하고 schema 검증을 요구한다.[S4]

**전체 schema가 API request에 실린다**는 것과 **모델의 최초 입력에 모두 펼쳐진다**는 것은 같지 않다.

### 3.2 Agents API는 별도 계약이다

Agents API의 function은 기본 eager loading이다. function에 `defer_loading:true`를 넣고 `agent.tools`에 Tool Search를 함께 넣어야 한다. Tool Search 하나를 넣었다고 모든 function이 deferred가 되지 않는다. session request는 여전히 전체 function definition을 공급하고 application은 발견 후 실제 호출 결과를 일반적인 방식으로 처리한다.[S4]

반면 Agents API의 **MCP 도구는 model/provider가 지원하면 runtime이 자동으로 defer하고 Tool Search를 추가**한다. remote/executor/plugin MCP에 적용된다. MCP만을 위해 Tool Search를 수동 추가하거나 Responses API의 MCP server `defer_loading` 설정을 그대로 복사하지 말라고 명시한다. 이 Agents API는 Claude Agent SDK도, OpenAI Agents SDK도, 로컬 Codex CLI 그 자체도 아니다.[S4]

### 3.3 Codex CLI: API 지원 추정이 아니라 released source 근거

최신 release metadata가 가리킨 **0.162.1, 2026-10-09 배포**의 commit을 고정해 읽었다. 현재 main commit과 release commit을 혼용하지 않는다.[C1–C2]

| 확인한 구현 | 고정 근거 | 의미와 제한 |
|---|---|---|
| MCP exposure | `mcp_tool_exposure.rs`의 `if search_tool_enabled { ToolExposure::Deferred } else { ToolExposure::Direct }` | regular MCP도 deferred 대상. Apps만 검색된다고 축소하면 틀린다 |
| model 조건 | `spec_plan.rs`가 `model_info.supports_search_tool`를 MCP registration에 전달하고, deferred searchable tool이 있을 때 search executor 등록 | model metadata/policy/exposure에 따른 조건부 기능. API 이름만 보고 모든 model/client/provider를 지원한다고 할 수 없다 |
| 실제 native search | `tool_search_spec.rs`: `ToolSpec::ToolSearch { execution: "client" ... }`; 설명은 **“Searches over deferred tool metadata with BM25 and exposes matching tools for the next model call.”** | hosted OpenAI search만 의존하는 것이 아니라 Codex client 구현도 존재 |
| 결과 wire item | `tools/context.rs`: `ResponseInputItem::ToolSearchOutput`의 `execution:"client"`, `tools` 직렬화 | 찾은 definition을 모델 history에 전달. 검색 결과를 공짜 참조로 보지 않음 |
| 모델 catalog | release `models-manager/models.json`의 `supports_search_tool:true` | GPT-5.5, GPT-6-Astra, GPT-6.1-Sol 등을 정적으로 확인. 6 계열은 `tool_mode:"code_mode_only"`도 명시 |
| retired 설정 | release `features/src/lib.rs`는 `ToolSearch`를 removed no-op, `ToolSearchAlwaysDeferMcpTools`를 removed라고 설명 | 예전 flag 안내를 현재 설정 계약으로 반복하면 안 된다 |
| 결과의 별도 truncation | `tools/context.rs`: **“History receives this budget in tokens. Code Mode keeps the raw result.”** | 직접 model 결과와 실행 환경의 raw 결과 처리가 다르다 |
| context estimate | `context_manager/history.rs`는 `ToolSearchOutput { tools }`와 `AdditionalTools`의 JSON content bytes를 estimate에 합산 | 발견한 schema는 context/accounting에서 사라지는 것이 아니다 |

위 표의 source 링크: [C3–C8]. 최소 client version 값은 모델을 사용할 수 있는 catalog metadata이지 해당 Tool Search feature의 도입 release라고 해석하지 않는다. GPT-6-Astra/GPT-6.1-Sol의 catalog minimum은 0.153.0, GPT-5.5는 0.124.0이다.[C7]

직접 tool search는 정의를 `ToolSearchOutput`으로 돌려주며, code-mode 안에서 호출한 search는 준비한 tool 정의를 코드용 이름/설명으로 반환한다. nested search는 그 sampling step의 router/policy에 없는 도구를 제외한 뒤 결과 limit을 적용한다. **host의 호출 가능성·허용 목록과 검색 visibility는 계속 필요**하다.[C4–C5]

Codex 공개 MCP 문서는 `initialize.instructions`를 서버 전체 guidance로 읽는다고 명시하고 첫 **512 characters**를 독립적으로 이해할 수 있게 쓰라고 권장한다. 이것을 모든 instructions의 절대 512-token budget으로 바꾸면 안 된다. `enabled_tools`, `disabled_tools`, per-tool output limit은 별도 설정이다.[S5]

`DeferredToolWorldState` 경로의 release source는 서버/namespace 요약 fragment를 4 KiB에 제한하고 description 첫 줄 최대 250 characters를 사용한다. 다른 경로인 search spec의 source listing에는 다른 bytes 상한이 있다. 따라서 모든 Codex 입력이 같은 작은 상한이라고 일반화하지 않는다.[C9, C4]

**미확인:** 설치된 binary와 runtime model catalog/provider/rollout, 실제 연결 시 wire 요청, resume·compaction 이후 loaded schema 재공개의 정확한 수명, token/latency/비용 개선. API의 “future turns” 계약을 근거로 Codex의 모든 compaction/resume 동작을 영구 보존이라고 광고하지 않는다. CLI 지원은 위 release의 source로 확인한 범위이며 다른 버전의 설치 상태는 조사하지 않았다.

## 4. Anthropic Code Execution과 Cloudflare Code Mode

### 4.1 두 효과를 분리해야 한다

Anthropic 2025-11-04 engineering 글은 (1) schema를 파일/API 형태로 필요한 만큼 읽기, (2) 큰 중간 결과를 코드에서 필터/집계한 뒤 반환하기를 제시한다. 예시 spreadsheet는 10,000행 중 pending order를 코드에서 걸러 처음 5행만 모델에 보여 준다. 문서 이동 workflow는 원문을 모델이 두 번 읽고 복사하는 대신 실행 환경 변수로 전달한다.[S6]

이는 설계 패턴에 대한 글이다. **그 글이 있다고 Claude Code에서 모든 연결 MCP를 자동으로 같은 sandbox에 실행한다는 뜻은 아니다.** 본문의 PII tokenization·재사용 skill도 harness 구현 예시이지 MCP server만 설치하면 제공되는 보안 보장이 아니다. 본문은 arbitrary agent code의 sandbox, resource limit, monitoring 운영비를 명시한다.[S6]

현재 Anthropic **Programmatic Tool Calling(PTC)** API는 `code_execution_20260120` 이상과 custom tool `allowed_callers`를 사용해 managed container에서 중간 결과를 처리한다. 지원 모델 목록은 Tool Search와 같지 않으며 Haiku 4.5는 해당 code execution version을 받아도 PTC는 미지원이다. 문서 metadata상 Claude API/Claude Platform on AWS는 GA, Foundry는 Hosted on Anthropic deployment 조건이다. 중요하게도 **“Tools provided by an MCP connector”는 programmatic 호출 불가**라고 명시한다. custom client-tool wrapper/custom sandbox로 MCP를 호출하는 구현과 native API MCP connector를 구분해야 한다.[S11]

### 4.2 Cloudflare 구현도 하나가 아니다

1. **초기 client-side Code Mode / 작은 `createCodeTool` adapter:** 도구를 TypeScript API로 바꾸고 코드 실행 도구 하나를 노출한다. 그러나 초기 engineering 글은 **“Currently, the entire API is loaded”**, 현재 Dynamic Workers 예제는 **“description that includes the full typed API surface”**라고 설명한다. 도구 개수가 하나라고 schema token이 상수인 것은 아니다. 이 형태의 주된 이득은 코드에서 호출을 묶고 중간 결과를 줄이는 것이다.[S7, S9]
2. **durable connector runtime:** 현재 MCP connector는 `codemode.search()`와 `codemode.describe()`로 관련 method/TypeScript documentation을 필요한 만큼 공개한다. `McpConnector`가 원 MCP `connection.client.callTool()`을 호출하고 별도 `requiresApproval` decoration을 지원한다. 이 runtime 문서의 갱신일은 2026-07-22이며 **experimental/may introduce breaking changes** 경고가 있다. 작은 adapter에는 durable approvals/search/describe가 없다고 문서가 명시한다.[S8, S10]
3. **Cloudflare API server-side Code Mode:** `search()`/`execute()` 두 MCP tool로 2,500개 이상의 Cloudflare API endpoint를 제공한다. full OpenAPI spec은 server isolate에 두고 검색 code의 결과만 반환한다. secure execution은 서버에 있으므로 client가 별도 Worker sandbox를 배송할 필요는 없다. 임의의 기존 MCP를 추가하면 자동으로 이 형태가 되는 것은 아니다.[S12]

이들 Code Mode는 일반 MCP 통신 위에 올라가는 실행·노출 방식이다. 두 도구의 고정 초기 footprint와 뒤이어 들어오는 search 결과/code/logs/final result의 가변 footprint를 구분해야 한다.

### 4.3 vendor 수치는 범위를 붙여 인용한다

| 출처 수치 | vendor가 설명한 범위 | 이 memory 설계에 대한 해석 |
|---|---|---|
| Anthropic engineering: 150,000 → 2,000 tokens, 98.7% | 큰 tool catalog를 코드 파일로 선택 공개하는 본문의 예시. 세부 재현 setup/분산은 본문에 충분히 공개되지 않음 | 작은 memory 3–5개 tool의 기대 절감률로 사용 금지 |
| Claude API Tool Search docs: multiserver 정의 약 55k, 통상 85% 이상 절감 | GitHub/Slack/Sentry/Grafana/Splunk 등 큰 catalog의 definition overhead를 3–5개 필요한 tool로 줄이는 설명 | 본문 memory corpus 결과까지 85% 줄인다는 뜻 아님 |
| Cloudflare Dynamic Workers 예제: up to 80% | Code Mode 예제 페이지의 vendor 주장. 페이지가 통일된 benchmark/model/분모를 충분히 제시하지 않음 | 일반 절감률 또는 자체 측정 결과로 쓰지 않음 |
| Cloudflare API server: 약 1,000 tokens, 99.9%, 비교 native MCP 1.17m | 2,500개 이상 endpoint API의 **초기 tool surface**를 `tiktoken`으로 비교한 특정 사례 | full task history/results/code까지 1,000 tokens 고정이라고 하지 않음. metadata의 “over 2 million”과 본문 1.17m 숫자를 섞지 않음 |
| Anthropic PTC: billed input 약 38% 절감 | production Claude model을 쓴 75-tool project-management 내부 평가, accuracy 변화 없음 | 동등 model/workflow에서의 자체 재현 없음 |
| Anthropic PTC: 약 8% 비용 증가 | τ²-bench, turn당 1–2 sequential tool calls, score 변화 없음 | 작은 memory 호출에는 실행 overhead가 이득을 넘을 수 있다는 강한 반례 |

출처: [S2–S3, S6, S9, S11–S12]. 모든 퍼센트는 vendor 사례다. 이 저장소에 대한 token measurement를 만들지 않았다.

## 5. Code sandbox에서 권한·보안·출처를 유지하는 조건

Cloudflare DynamicWorkerExecutor 예제는 isolated Worker, `globalOutbound:null`로 `fetch()` 차단, captured logs, 기본 실행당 30초 timeout을 설명한다. server-side Cloudflare API 글은 filesystem/environment variables 없음과 기본 external fetch 차단, 선택한 OAuth 권한으로 token downscope를 설명한다. 모델이 credential을 직접 갖지 않아도 허용된 RPC method를 통해 실제 외부 작업은 가능하다.[S9, S12]

Cloudflare durable runtime의 `requiresApproval:true`는 method 실행 전에 pause한다. approve하면 replay하면서 완료된 호출의 recorded result를 재사용한다. reject는 앞서 끝난 작업을 되돌리지 않는다. rollback은 현재 connector가 제공하는 `revert`로 보상할 뿐 모든 외부 API의 atomic rollback을 보장하지 않는다.[S8, S10]

**[설계 제안] memory service에서 Code Mode를 넣는다면 지켜야 할 조건:**

- ACL/tenant/workspace 정책은 서버가 각 검색·원문 조회·쓰기 호출에 적용한다. sandbox가 최종 출력에서 숨기는 것만으로 비인가 record를 먼저 읽게 하지 않는다.
- “인터넷 차단”과 “유출 불가”를 동일시하지 않는다. 허용된 외부 write tool이나 log/final output도 정보 경로다. 회사 memory를 개인 cloud connector로 전달하지 못하게 하는 destination 정책은 별도로 필요하다.
- corpus text와 tool 결과는 비신뢰 데이터로 다룬다. 검색 결과의 문장을 generated code/instruction/권한 승인으로 해석하지 않는다. PTC 공식 문서도 외부 결과를 코드로 해석할 때 injection을 경고한다.[S11]
- filtering/aggregation 결과에도 `record_id`, source URI, revision/hash, 근거 구간·선정 조건을 필요한 만큼 남긴다. 원문과 transformation 경로를 나중에 다시 확인할 수 있어야 한다. 출처 전체를 자동 덤프하지 않되 압축을 이유로 근거 연결을 버리지 않는다.
- 삭제·권한 변경 이후 derived result, sandbox file, execution history, replay cache, snippet에 남은 데이터가 계속 노출되지 않게 별도 수명·접근 정책을 둔다. 일반 Tool Search나 Code Mode 문서가 이 memory lineage/삭제 전파를 자동 보장하지 않는다.
- 출력·로그·실행시간·호출 수 예산을 별도로 둔다. raw result를 sandbox에 두어도 무제한 `console.log()`/return으로 되돌려 보내면 context 절감은 사라진다.

이 조건들은 제안이며 현재 저장소나 vendor runtime의 기존 보장을 주장하는 것이 아니다.

## 6. Prompt caching은 context 절약과 다르다

OpenAI는 cache를 **“full rendered context”**의 KV state 재사용으로 설명하며 tool definition/history도 포함한다고 명시한다. Agents API session 유지가 cache hit를 보장하지 않는다. Tool Search가 정의를 뒤에 추가하는 이유는 기존 prefix를 보존하기 위해서다. cache hit는 model/provider/retention/routing 및 prefix 일치에 달려 있다.[S4, S14]

Anthropic은 `tools`, `system`, `messages` 순서의 전체 prefix를 cache한다고 설명한다. cache read/write가 prompt 길이에 따라 과금하는 model에서 prompt length에 합산된다고 명시한다. 기본 TTL 5분과 유료 1시간은 영구 memory retention과 다르다.[S15]

**[문서에서 도출한 결론] cached input은 싸고 빠르게 재사용할 수 있지만 동일 내용이 모델 context를 차지하는 사실은 바뀌지 않는다.** 50k schema/results를 cache했다고 50k만큼 빈 window가 생기는 것은 아니다. 반대로 deferral/filtering으로 실제 모델 입력을 줄이면 window 공간도 확보할 수 있다. 할인율, uncached input, cache write/read, context footprint, 결과 품질은 각각 측정해야 한다. 특정 API 가격표를 구독형 Claude Code/Codex의 사용 allowance나 설치 client 실측 비용과 그대로 동일시하지 않는다.

## 7. 이 OSS memory service에 적용할 선택

**[제안] 기본안:** 작은 semantic tool surface + 짧은 서버 instructions + server-side scope/ACL filtering + 검색 결과 예산 + 근거를 지정 조회하는 구조다. 원문을 처음부터 매 세션 주입하지 않고, `search`는 ID/짧은 excerpt/source 위치를 주고 `get`이 필요한 근거 부분만 가져오게 한다. local과 self-host cloud는 같은 좁은 MCP interface를 쓰되 저장·권한·routing 정책은 별도로 적용한다. host가 Tool Search를 지원하지 않아 upfront해도 작은 정의만 들어가도록 설계한다.

| 대안 | 좋은 조건 | 가장 강한 반론/한계 |
|---|---|---|
| 작은 도구를 upfront | 검색·조회·쓰기 몇 개, 거의 매 task 사용, 짧은 schema | 매 turn 정의 overhead는 남지만 discovery/code 생성 단계가 없어 단순하다. 작은 catalog면 공식 SDK도 이 경로의 latency 이점을 설명한다 |
| host Tool Search 사용 | 이미 연결한 다른 서버들까지 catalog가 큼, task별 일부 도구 사용 | provider/model/host 차이가 있고 못 찾으면 capability를 놓친다. memory result 크기·출처 폭증은 해결 못함 |
| 서버 측 검색·projection·pagination·bounded `get` | memory가 크지만 도구는 적음 | 모델에게 full raw data를 주지 않으므로 retrieval recall과 근거 재조회가 중요하다. 복잡한 범용 계산은 제한될 수 있음 |
| 선택적 Code Mode | 반복 조회·join·aggregation·대량 중간 결과, 폭넓은 API catalog | 실행 플랫폼/정책/승인/로그/lineage 비용. small sequential read에는 vendor benchmark상 오히려 비쌀 수 있음. 도구 하나 안에 full types를 넣으면 startup schema 문제도 남음 |
| prompt caching | 안정된 prefix를 많은 turn에서 재사용 | window 절약 아님. cache hit/TTL/가격 조건 있음. source·ACL·삭제 수명 해결 아님 |

**가장 강한 Code Mode 찬성 논리**는 “몇 개 memory 도구라도 10,000행 결과를 여러 번 합치면 도구 개수와 무관하게 큰 절감이 가능하다”다. 타당하다. 그러나 **기본안의 강한 반론**은 “필터 조건·projection·aggregation을 memory 서버의 평범한 API로 처리하면 같은 결과 절감이 가능하고 arbitrary code 실행 책임은 추가되지 않는다”다. 범용 다중 서비스 조합이 필요한 실제 작업에서만 Code Mode가 그 제한을 넘는다. 이 선택은 자체 workload의 context·billed input·latency·retrieval 품질·근거 유지 측정으로 결정해야 한다.[S2, S6, S11]

이 조사에서 확정한 것은 공식 지원 계약과 release source다. main agent가 제품 수용 검증을 한다면 host version/model/provider 별로 초기 names/instructions/schema, search 후 누적 정의, 반복 turn, compaction/resume, memory 결과·source bytes, cache read/write와 지연을 따로 기록해야 한다. 실행 결과나 절감률은 이 notes에 없다.

## 출처

### 공식 문서·engineering

- [S1] [Claude Code MCP](https://code.claude.com/docs/en/mcp.md), 특히 `Scale with MCP tool search`, `Use MCP resources`, `MCP output limits and warnings`, `Server status detail`. 2026-10-11 열람.
- [S2] [Claude Agent SDK Tool Search](https://code.claude.com/docs/en/agent-sdk/tool-search), `How tool search works`, `Configure tool search`, `Limits`. 2026-10-11 열람.
- [S3] [Claude API Tool search tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool), `Model compatibility`, `How tool search works`. 2026-10-11 열람.
- [S4] [OpenAI Tool search](https://developers.openai.com/api/docs/guides/tools-tool-search.md), `Responses API`, `Understand what gets loaded`, `Tool search and caching`, `Agents API`, `MCP and plugin tools`. 2026-10-11 열람.
- [S5] [Codex MCP](https://developers.openai.com/codex/mcp), 현재 공식 redirect [Model Context Protocol](https://learn.chatgpt.com/docs/extend/mcp?surface=cli). `Supported MCP features`, `Other configuration options`. 2026-10-11 열람.
- [S6] [Anthropic: Code execution with MCP](https://www.anthropic.com/engineering/code-execution-with-mcp), 2025-11-04 게시; 2026-10-11 열람.
- [S7] [Cloudflare: Code Mode, the better way to use MCP](https://blog.cloudflare.com/code-mode/), `Converting MCP to TypeScript`, `Running code in a sandbox`. 2026-10-11 열람. 초기 구현 설명으로 취급.
- [S8] [Cloudflare: Use MCP tools with Code Mode](https://developers.cloudflare.com/agents/tools/codemode/mcp/index.md), 문서 갱신 2026-07-22; 2026-10-11 열람.
- [S9] [Cloudflare: Dynamic Workers Code Mode Example](https://developers.cloudflare.com/dynamic-workers/examples/codemode/index.md), 문서 갱신 2026-05-05; 2026-10-11 열람.
- [S10] [Cloudflare: Create a durable Code Mode runtime](https://developers.cloudflare.com/agents/tools/codemode/durable-runtime/index.md), 문서 갱신 2026-07-22; 2026-10-11 열람.
- [S11] [Anthropic: Programmatic tool calling](https://platform.claude.com/docs/en/agents-and-tools/tool-use/programmatic-tool-calling), support metadata, `Tool restrictions`, `Token efficiency`, `When to use programmatic calling`. 2026-10-11 열람.
- [S12] [Cloudflare: Give agents an entire API in 1,000 tokens](https://blog.cloudflare.com/code-mode-mcp/), `Server-side Code Mode`, `The Cloudflare MCP server`. 2026-10-11 열람.
- [S13] [Claude Agent SDK MCP](https://code.claude.com/docs/en/agent-sdk/mcp), `Connection timing`, `Allow MCP tools`, output limits. 2026-10-11 열람.
- [S14] [OpenAI Prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching.md), full rendered context, session vs cache hit, append-only tool updates. 2026-10-11 열람.
- [S15] [Anthropic Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching), full prefix, pricing/prompt length, TTL. 2026-10-11 열람.

### Codex release 고정 근거

- [C1] [release 0.162.1](https://github.com/openai/codex/releases/tag/rust-v0.162.1), [release API](https://api.github.com/repos/openai/codex/releases/latest)를 기준일에 읽어 최신 tag/published_at 확인. `latest` API는 가변이다.
- [C2] [tag object](https://api.github.com/repos/openai/codex/git/tags/7a078f6bb4ce0dc2a81408b334ce52979d92c603): release commit `092d3acd6bec3e3a14bdc7e7a2810ab628ab759d`.
- [C3] [mcp_tool_exposure.rs L79–92](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/core/src/mcp_tool_exposure.rs#L79-L92), `non_app_tools`/`app_tools`, `search_tool_enabled`에 따른 `ToolExposure::Deferred`/`Direct`.
- [C4] [tool_search_spec.rs L93–106](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/core/src/tools/handlers/tool_search_spec.rs#L93-L106), BM25 설명과 `execution:"client"`; [tool_search.rs L209–277](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/core/src/tools/handlers/tool_search.rs#L209-L277), `handle_call`; [L283–335](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/core/src/tools/handlers/tool_search.rs#L283-L335), `search_code_mode`의 exact step nested-tool policy.
- [C5] [spec_plan.rs L153–160](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/core/src/tools/spec_plan.rs#L153-L160), `append_mcp_tools`에 `model_info.supports_search_tool` 전달; [L393–430](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/core/src/tools/spec_plan.rs#L393-L430), searchable deferred tool 존재 시 executor 등록; [router.rs](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/core/src/tools/router.rs), native client-executed `ToolSearchCall` dispatch.
- [C6] [tools/context.rs L207–246](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/core/src/tools/context.rs#L207-L246), history result budget, `ToolSearchOutput`, `ResponseInputItem::ToolSearchOutput`, `execution:"client"`.
- [C7] [models-manager/models.json](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/models-manager/models.json), 구조화해 열람. 정확한 selector: GPT-6-Astra `slug` L4/`tool_mode` L20/`minimal_client_version` L70/[`supports_search_tool` L160](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/models-manager/models.json#L160); GPT-6.1-Sol L177/L193/L242/[L335](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/models-manager/models.json#L335); GPT-5.5 L1340/L1356/L1398/[L1448](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/models-manager/models.json#L1448).
- [C8] [features/src/lib.rs L255–258](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/features/src/lib.rs#L255-L258), removed compatibility flags; [context_manager/history.rs L1177–1179](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/core/src/context_manager/history.rs#L1177-L1179), `AdditionalTools`/`ToolSearchOutput` JSON content accounting.
- [C9] [context/world_state/tools.rs L25–26](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/core/src/context/world_state/tools.rs#L25-L26), bounded deferred namespace summary constants. 조건부 world-state 경로이며 모든 CLI 입력의 보편적 상한은 아니다.
