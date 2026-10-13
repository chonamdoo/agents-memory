# MCP context 비용과 공통 memory service 설계

조사 기준2026-10-11. 사용자는 'MCP 연결마다 context가 커지는가, 요즘 MCP2.0은 다른 형태 아닌가'를 묻는다. 제품 구현/호스트 설정 변경/실제 memory 서버 benchmark가 아니라 공식 source 기반 설계 판단이다. 별도 조사: mcp-context-protocol.ko.md, mcp-context-hosts.ko.md.

## 결론

**기존 공통 설치형 서비스+MCP의 배포 구조는 유지하되, context 계약은 '소수·짧은 도구 surface + 지원 host의 schema 지연 로딩 + 권한/scope 기반 memory 선택과 반환 예산'으로 명시한다.** MCP 연결이 전체 memory corpus를 모델에 넣도록 요구하지는 않는다. 하지만 eager tool schemas, 긴 server instructions, 큰 recall/reflect 결과 또는 무조건 startup 전체 memory 주입은 실제 context를 소비한다.

'MCP2.0'이라는 표현만으로 기능을 확정하지 않는다. 공식 spec은 날짜 버전2026-07-28의 실제 새 stateless core가 출시됐고, SDK semver·JSON-RPC2.0·Tool Search·Code Mode는 각각 다른 축이다. 특히 stateless MCP는 네트워크 lifecycle을 단순화할 뿐 model context를 자동 제거하지 않는다.

## 1. 연결/도구/기억/캐시는 다른 비용

| 층 | 모델 context에 들어가는 경우 | 대책과 한계 |
|---|---|---|
| MCP wire discovery/auth | host가 모델 입력에 실어야만 model tokens. 통신 자체와LLM 입력은 같은 것이 아님 | 새 stateless/discovery·catalog cache는 연결/재조회 비용 감소. 모델에 큰목록을넣는host는여전히큰context |
| 도구 catalog | host가 schema/description/name/instructions를 모델에 노출 | 작은 고정 tool surface, 짧고일반적인serverinstructions,host-native deferred loading. tool names/instructions의 startup 비용은남고unsupported host에서는작은schema upfront fallback |
| 실제 memory 결과 | recall/reflect/startup hook가 text/structured 결과를 모델에 전달 | service 내부에서 authorization·scope·freshness·eligibility·상충·독립support로선택. 모델에보낼payload예산/원문추가조회. tool search는이본문크기를줄이지않음 |
| backend 추출/reflect | worker가 source corpus를 허용된 model에 보내는 별도 inference | front agent의startup절감과다른cost/egress. 추출비용·trace/recording·승인/삭제 계약이사라지지않음 |
| prompt cache | 같은 rendered prefix의KV재사용 | 재처리비용/latency 절감이지 contextwindow공간0이나memory영구저장아님. tool ordering/prefix안정성유지하되삭제/권한변경보다cachehit를우선하지않음 |

Sources: [MCP tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools), [공식 새 spec 발표](https://blog.modelcontextprotocol.io/posts/2026-07-28/), [OpenAI prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching).

## 2. 현재 host와code execution의 source 확인

### Claude Code

[현재 공식 MCP docs의Tool Search](https://code.claude.com/docs/en/mcp#scale-with-mcp-tool-search)는 session startup에 **tool names+server instructions**만 loading한다고 설명한다. `ENABLE_TOOL_SEARCH` unset의현재default는 **all MCP tools deferred**이며 **auto**가10% threshold mode다. '기본10%넘어야만검색'은현재문서와다르다.

`alwaysLoad:true`, non-first-party proxy의 `tool_reference` 미지원, Foundry Azure deployment/이전 Agent Platform model 등은 upfront 경로를 만들 수 있다. 서버 작성자의 `anthropic/alwaysLoad` metadata는 host/config/version별 의미가 다르고, 서버가 모든 client에 deferral을 강제하는 표준이 아니다. 현재 docs의 instructions/descriptions 기본 2,048 **characters** 절단과 v2.1.280 이상의 조정 변수는 memory 결과 token budget과 다르다.

이번에는사용자client/config/modelrouting를검사/변경하지않았다. 공식currentbehavior를모든설치surface에적용된실행증거로말하지않음.

### OpenAI

[Tool Search](https://developers.openai.com/api/docs/guides/tools-tool-search)는ResponsesAPI의tool_search+defer_loading,지원model(GPT5.4+)을설명한다. namespace/MCP서버는처음name/description만,individualfunction은name/description을유지하며parameter schema주로지연한다. 새tool은context끝에append하여earlierprefix를보존한다. server registration metadata의searchability와실제memorysearch는별개다.

API 지원만으로 Codex CLI/ChatGPT 모든 surface를 보장하지 않는다. 이번에는 [Codex release 0.162.1의 고정 MCP exposure source](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/core/src/mcp_tool_exposure.rs#L79-L92)에서 regular MCP도 `search_tool_enabled`에 따라 Deferred/Direct로 노출하는 구현을 직접 확인했다. [model gate](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/core/src/tools/spec_plan.rs#L153-L160)와 GPT-6.1-Sol catalog의 `supports_search_tool:true`, native BM25/client search는 host notes에 고정 source를 첨부했다. 실제 설치 client/provider/config와 compaction/resume 수명·token 절감률은 이 source 확인만으로 입증하지 않는다.

### Code Mode

[Anthropic의 2025-11-04 Code Execution with MCP](https://www.anthropic.com/engineering/code-execution-with-mcp)는 도구 정의 on-demand loading과 중간 데이터의 sandbox 내 필터링을 제안하고, secure execution/resource limits/monitoring 비용을 명시한다.

[Cloudflare 새CodeMode MCP](https://blog.cloudflare.com/code-mode-mcp/)는Cloudflare의대규모API를search/execute두tools로노출하고generatedcode를server-isolate에서실행한다. 따라서client가nativeToolSearch를지원하지않아도작은surface와progressivediscovery가가능하다. **vendor의전체API·정적footprint수치를우리memory서비스의실제절감률로사용하지않음**. 이본문meta의'2M tokens'와본문의'1.17M tokens'도같은모수로일괄계산하지않는다.

[현재Anthropic PTC tool restrictions](https://platform.claude.com/docs/en/agents-and-tools/tool-use/programmatic-tool-calling#tool-restrictions)는**native MCP connector tools는programmatic호출불가**라고한다. customclient/toolwrappers·hostSDKsandbox·server-sideCodeMode와해당APIconnector를혼동하지않음.

## 3. memory제품에적용할계약

1. **연결시전체memory0:** company/customer/projectfact·원문·과거대화를serverinstructions/tool descriptions에삽입하지않는다. 새task에서자동회상이필요하면지원hostadapter가현재authorizedscope에맞는boundedcontext만선택해전달한다. 전체corpus주입은기본값이아님.
2. **소수고정tool surface:** 기억마다tool을만들지않는다. recall/context·reflect·capture/candidate proposal 등실제domain작업만노출하고관리자권한plane는기존설계대로분리. 도구를하나의거대한executeenum/schema로합쳐같은명세를다로드하는것은절감이아님.
3. **Host-native 지연로딩우선:** 지원host에는ToolSearch/deferred schemas를사용. client없는전용discoveryframework나사전다중transport를추가하지않는다. 미지원host도작은보편schema+동일selective retrieval로지원할수있다.
4. **Service-side 선별+응답예산:** authorization→scope/freshness/승인eligibility→검색/선택→compactevidencepayload로전달. ID/revision/source종류·조건·부정·상충을유지하고안전하게안들어가는항목은전체요약으로단정하지말고미완전표시/원문회수pointer를제공. exacttoken예산은profilemodel과serializer/metadata/hostwrapper를포함해측정·설정;임의절감률/항목수와토큰수동일시안함.
5. **결과누적통제:** 호출횟수만큼큰결과를계속쌓으면deferredtools라도context는커진다. hostadapter에서deliveredID/revision/turnreceipt와현재payload를관리. canonicalprivacyforget/approval변경은기존cache/lateworker/restorefence에계속적용한다. source를없애cachehit만남기는것이authority가아님.
6. **CodeMode는선택:** 대량원문가공/multi-toolbatch가실제필요하고benchmark로이득이있을때secureexecution을채택. 지금작은memoryAPI에단지'MCP2.0'이란이유로arbitrarycodeplatform을필수로추가하지않음. server/filteringquery만으로본문을줄일수있다. 적용시에도ACL/operator승인/egress/finaloutputbudget/provenance를sandbox가대신보장하지않으며회사로컬과개인cloud에동일계약이필요.
7. **API호환성:** 2026statelessprotocol의제거된sessionID/initialize를appidentity/worker/approval상태로사용하지않는다. 지속memory는공통domainDB에남는다. 지원client/SDKprotocolmatrix를검증하고transport기능변화를품질/권한의동등성으로오인하지않음.

## 4. 관측기준 — 실행한memorybenchmark아님

설치전targethost별fresh-sessionstartup,첫회상후,long-session후의renderedtool/instructions/memoryresulttokens와input/cachedtokens·latency·backendinferencecost를분리측정한다. eager/deferred을동일toolset/query/corpus/task/repo상태에서비교하고검색추가roundtrip/누락·한국어/조건과authority보존도같이평가한다. reconnect와새LLMsession,discoverycachehit와promptcachehit는별도조건이다.

이번에검증한것은현재공식spec/docs의내용과고정source행위다. 제품/사용자host의실제토큰수나절감률은측정하지않았고,MCPconfig/계정/외부GitHubissue는수정하지않았다.
