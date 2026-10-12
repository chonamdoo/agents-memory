# 영상형 knowledge pipeline의 독립 제품 적용: MCP·host capture·memory engine 경계

조사일: 2026-10-11. 대상: 회사·외주 고객의 local 환경과 개인 self-host cloud에서 **같은 지식 처리 의미**를 유지하는 독립 OSS. 이 문서는 공개 공식 문서와 지정된 Hindsight core source를 조사한 근거 자료다. 제품을 설치하거나 실행한 결과가 아니며, 새 배포를 요구하지 않는다. 영상 발언·시연의 판정은 부모가 다시 확보한 전체 스크립트 분석에 맡긴다. 이 문서에는 영상에서 실제 구현됐다고 주장하는 내용이나 특정 프로젝트 적용안이 없다. 이전 native model verdict와 제공된 다른 AI 보고서는 읽지 않았다.

## 1. 결론

**재사용할 수 있는 것은 memory engine의 저장·검색·합성 연산과 MCP 접속 면이다. 자동 capture, 사람의 correction 판별, 독립 조사 횟수 집계, 승인 권위, 최신성 확인은 별도의 extraction-control layer가 맡아야 한다.** 다만 이를 전부 처음부터 구현할 필요는 없다. 현재 Claude Code와 Codex 공식 문서는 host lifecycle hooks와 context 반환을 제공한다. 지원되는 host에 맞는 작은 adapter를 두고 공통 처리 계약으로 정규화할 수 있다. [M1–M5, C1–C3, O1–O2, H1–H10]

세 가지를 분리해야 한다.

- **MCP**: host가 서버의 tools/resources/prompts를 발견하고 호출하는 접속 규약. 서버가 자동으로 전체 대화 기록을 받는 규약이 아니다.
- **Capture adapter**: host의 이벤트, transcript/export 또는 사용자가 제출한 자료를 받아 원문과 출처를 확보하는 부분. remote MCP 연결만으로 생기지 않는다. 반대로 현재 host는 lifecycle event가 MCP tool을 직접 호출하도록 구성할 수도 있으므로 “MCP는 어떤 자동화도 못 한다” 역시 부정확하다.
- **Installer/배포물**: engine, adapter, host 설정, 데이터 저장 위치와 운영 절차를 배포한다. 설치가 capture completeness·무외부전송·승인 정책을 증명하지 않는다.

**회사 local과 개인 cloud에 같은 domain pipeline을 두는 것은 가능성이 확인된 설계 방향이지, 데이터와 자격증명을 공유하자는 뜻이 아니다.** 같은 원문 계약·분류 규칙·승인 상태·집계 단위·평가 기준을 재사용하고, endpoint·DB·capture spool·host session·credential·backup·egress 정책은 분리해야 한다. Hindsight 단일 PG를 미리 승자로 둘 근거는 없다. Hindsight는 아래 기능을 재사용할 수 있는 후보지만, 별도의 통제층 필요성을 없애지 않는다. [M2, H1, H8–H10]

## 2. 출처와 버전 고정

아래 ID를 본문에 사용한다. 공식 문서는 변할 수 있으므로 조사일의 문서 내용과 core commit을 구분한다. 모든 H source는 **`a9eeed77f9bce99d8f97d39a30d3281747300824`**로 읽었다. GitHub commit API의 author/committer 날짜는 `2026-10-10T14:24:47Z`, message는 `chore(deps): bump handlebars to 4.7.10 in root lockfile (#5481)`이다. [commit](https://github.com/vectorize-io/hindsight/commit/a9eeed77f9bce99d8f97d39a30d3281747300824)

### 2.1 공식 문서

| ID | Primary URL / 읽은 절 | 버전·확인 범위 |
|---|---|---|
| M1 | [MCP specification](https://modelcontextprotocol.io/specification) | 요청 URL이 **2026-07-28**로 resolve됨. 조사일의 current revision이다. 예전 revision을 current로 가정하지 않았다. |
| M2 | [Architecture](https://modelcontextprotocol.io/specification/2026-07-28/architecture) | Host/Clients/Servers, Design Principles, Capability Negotiation |
| M3 | [Tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools) | User Interaction Model, schema/annotations, 호출 흐름 |
| M4 | [Resources](https://modelcontextprotocol.io/specification/2026-07-28/server/resources) | application-driven context inclusion, capabilities |
| M5 | [Elicitation](https://modelcontextprotocol.io/specification/2026-07-28/client/elicitation) | form/URL modes, 지원 capability, 사용자 선택 |
| C1 | [Claude Code MCP](https://code.claude.com/docs/en/mcp) | local stdio·remote HTTP, 설정 scope·trust와 별도 승인. live docs, 문서 commit SHA 미공개 |
| C2 | [Claude Code hooks](https://code.claude.com/docs/en/hooks) | Hook locations, common input, MCP tool hooks, SessionStart/UserPromptSubmit/Stop/SubagentStop/PermissionDenied, additionalContext. live docs, 문서 commit SHA 미공개 |
| C3 | [Claude Code permission modes](https://code.claude.com/docs/en/permission-modes) | classifier payload, server-side review, plan/auto와 human approvals. live docs, 문서 commit SHA 미공개 |
| O1 | [요청한 Codex MCP 문서](https://developers.openai.com/codex/mcp) → [resolved MCP 문서](https://learn.chatgpt.com/docs/extend/mcp?surface=cli) | local Codex host의 CLI/IDE/desktop 구성과 web/cloud 예외, live docs |
| O2 | [Codex hooks](https://learn.chatgpt.com/docs/hooks) | tool coverage, common fields, trust, MCP tool hooks, local/cloud 제한, schema 문서의 release-vs-main 경고 |
| D1 | [Hindsight installation](https://hindsight.vectorize.io/developer/installation) | HTML 문서 버전 **0.10**, local/production PG·Docker/pip·local inference 조건 |
| D2 | [Hindsight models](https://hindsight.vectorize.io/developer/models) | HTML 문서 버전 **0.10**, LLM/embedding/reranker·자동 model download·언어 및 provider 조건 |

추가 HTTP fetch의 원문 바이트 SHA-256(설치/모델의 HTML은 배포 때 다시 변할 수 있음):

- M1 revision Markdown: `f8df03767e5cbdd4921ae569d1d69e8da9e455e1629fadf4d0613cd658dd632f` (`5817` bytes).
- O1 resolved `.md?surface=cli`: `adb28990c0c7be47b9ff6c177e3cdeae5803978935cd792f781af2c8b5643e92` (`18256` bytes).
- O2 `.md`: `724881d81f1a9fdb35ea42d4851a11b1f6606bbc6e9d2d05c1e8c466fc25c630` (`46965` bytes).
- D1 HTML: `a6974b86d878b7cee0b66ab9d7ea2d86e4bf856f15e5470a8ece5ddceccd2884` (`184028` bytes).
- D2 HTML: `92904540aad5faafbc1598f03031106c378164b5961ecbb1ffe564c2a94eeb06` (`349229` bytes).

C1–C3은 reader의 alternate Markdown 경로로 본문을 확보했다. 별도 urllib byte-hash fetch는 `403 Forbidden`이므로 SHA를 만들었다고 주장하지 않는다. M2–M5는 revision URL로 고정했다. 호스트 실행 binary 버전은 확인하지 않았으며 live docs의 지원을 설치된 binary 지원으로 동일시하지 않는다. 특히 M1의 2026-07-28 규약은 stateless/per-request capabilities를 기술하지만, O1은 여전히 initialization `instructions`를 설명한다. **current spec 페이지와 모든 host·SDK의 실제 협상 버전이 같다는 보장은 없다.** 지원표는 각 host 공식 문서의 범위이며 해당 revision과의 wire conformance 검증은 아니다.

### 2.2 고정 core source

`H1` 같은 ID는 다음 permalink의 실제 source와 symbol에 대응한다. blob SHA는 GitHub recursive tree API에서 확인했다.

| ID | 고정 source / 핵심 symbol | Git blob SHA |
|---|---|---|
| H1 | [mcp_tools.py](https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-api-slim/hindsight_api/mcp_tools.py): `_ALL_TOOLS`, `_register_retain`, `_register_recall`, `_register_reflect`, `_register_create_directive`, `_register_invalidate_memory`, `MentalModelTriggerInput` | `b0bb2ed4c760ad67f956c818bf8291b226d9d112` |
| H2 | [fact_extraction.py](https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-api-slim/hindsight_api/engine/retain/fact_extraction.py): `Fact`, `ExtractedFact`, `_BASE_FACT_EXTRACTION_PROMPT`, `_CONCISE_GUIDELINES`, `_DEFAULT_LANGUAGE_RULE` | `093e41d4030e0b26c334065e127a6dbde312b3bd` |
| H3 | [documents.py](https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-api-slim/hindsight_api/engine/memories/pg/documents.py): `recall_source_facts`, `recall_chunks`, `get_document_with_counts`, `delete_document_rows` | `8918ed8f89aa29ba0948c3aba1b15d6018df2b86` |
| H4 | [retractions.py](https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-api-slim/hindsight_api/engine/reflect/retractions.py): `RetractedGrounding.unresolvable`, `partition_retracted`, `prune_based_on` | `d7be2b2f40353df3fe7ad798e2fe3dafaeeb7902` |
| H5 | [operation_validator.py](https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-api-slim/hindsight_api/extensions/operation_validator.py): `ValidationResult`, `RetainContext`, `RetainResult` | `2ac6221c3af99f3c703af91df68609d00502caec` |
| H6 | [orchestrator.py](https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-api-slim/hindsight_api/engine/retain/orchestrator.py): `_classify_chunk_diff`, `_try_delta_retain`, `assert_append_extends_stored_body` | `e8f437aa958d5ec6cb8eb5cfcfd7b29c395d897e` |
| H7 | [mcp_local.py](https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-api-slim/hindsight_api/mcp_local.py): `main` | `6dc0adbe43a71ee424c138e811b51d1e4b065a0f` |
| H8 | [builtin/tenant.py](https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-api-slim/hindsight_api/extensions/builtin/tenant.py): `DefaultTenantExtension`, `ApiKeyTenantExtension` | `c2ab3f89985aa52ee547d6b56ed855082b291740` |
| H9 | [transfer/export.py](https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-api-slim/hindsight_api/engine/transfer/export.py): replayed/carried/skipped tables, `stream_export_documents` | `074c02cc56d77f830d3e85d63c8c408f3650ad64` |
| H10 | [transfer/importer.py](https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-api-slim/hindsight_api/engine/transfer/importer.py): `ImportResult`, `parse_archive`, `import_documents` | `2bf7435c7210ff455b1ef5a209a2c7c3cb43f16a` |
| H11 | [api/mcp.py](https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-api-slim/hindsight_api/api/mcp.py): `create_mcp_server`, `_make_tools_tolerant` | `a2dfc3f826349c3477104ce6c35968ef6f3a0844` |

공식 `llms.txt`도 discovery 용도로 읽었으나 [현재 `/sdks/mcp`](https://hindsight.vectorize.io/sdks/mcp)는 404였다. 그 index의 `hindsight-mcp-server` 설치·옛 memory type 설명을 현재 구현의 근거로 채택하지 않았다. H1의 머리말은 `mcp_local.py`를 stdio라 부르지만, **고정 H7의 실제 entrypoint는 main HTTP API를 시작하는 thin wrapper**다. 따라서 이 revision을 “local entrypoint는 stdio”라 요약하면 틀린다. 일반 MCP host의 stdio 지원과 해당 제품 entrypoint의 transport는 별개다.

## 3. MCP로 보장되는 것과 보장되지 않는 것

### 근거 문장

- M2: “Servers should not be able to read the whole conversation”; “Full conversation history stays with the host.” host가 context aggregation과 consent를 담당한다.
- M3: tools는 “model-controlled”; protocol은 특정 interaction model을 강제하지 않는다. schema와 tool annotation은 존재하지만 annotations는 trusted server가 아니면 untrusted로 취급해야 한다.
- M4: resources는 “application-driven”; host가 UI 선택, 검색, heuristic 기반 자동 포함 중 무엇을 할지 결정한다.
- M5: elicitation은 기존 client request 처리에 **nested**한 추가 사용자 입력이다. host의 capability가 지원하는 mode만 요청할 수 있다. form elicitation으로 API key·password·access token을 요구하면 안 된다.

### 설계 추론

1. `retain/recall/reflect` tools를 remote MCP로 제공하면 공통 API 재사용은 가능하다. 그러나 질문 전 자동 recall, 모든 turn 자동 capture, 원문 파일 업로드, 승인 이력 저장은 별도 host 행동·설정 또는 외부 application orchestration이 필요하다.
2. resources subscription은 **서버가 제공하는 resource 변경**을 알려주는 기능이다. 사용자의 대화 입력이 자동으로 서버에 mirror되는 기능으로 해석할 수 없다.
3. elicitation의 `accept/decline/cancel`을 memory 후보 승인 UI의 일부로 사용할 수는 있다. 하지만 어떤 후보·revision을 누가 승인했는지, 승인 권한과 충돌 정책, 거절 후 재제안 조건은 domain 모델이 구현해야 한다. 단순 tool execution 승인과 “이 주장이 사실이며 앞으로 규칙으로 적용해도 된다”는 승인을 구분해야 한다.
4. remote MCP는 host의 local transcript path를 읽을 수 있다고 가정할 수 없다. `transcript_path` 문자열만 remote tool에 전달해도 파일 bytes가 전송된 것은 아니다. host adapter가 허용된 원문을 읽고 redaction·scope 판단 후 전달해야 한다. local stdio도 host가 연결을 만들었다는 이유만으로 모든 host event가 자동 전달되지는 않는다.
5. schema는 **형태·타입 계약**이다. `classification='human_correction'`, `verified=true`가 JSON Schema를 통과했다는 사실은 correction의 작성자·원문 근거·현재 정확성을 증명하지 않는다. H2의 구조화 fact에도 진실 검사나 승인 권위가 자동으로 생기지 않는다.

## 4. 지원할 수 있는 host 조건과 미지원 범위

아래는 **문서상 가능한 접속·관찰 경로**다. 실제 설치 검증은 하지 않았다.

| Host/환경 | 가능한 reuse | 반드시 남는 조건·반례 |
|---|---|---|
| Claude Code terminal/IDE extension/Desktop의 Code session | C1의 local stdio 또는 remote HTTP 접속; C2 lifecycle hooks. `UserPromptSubmit`, tool events, `Stop/SubagentStop`로 capture; command/HTTP handler로 공통 control service 호출; `additionalContext`로 회상 결과 반환 | 허용된 hooks 설정·관리 정책·설치 버전 필요. user/project/plugin hooks는 `allowManagedHooksOnly` 정책으로 제한될 수 있다. Desktop 전체·일반 Claude chat·Cowork까지 같은 지원이라고 확대할 수 없다. |
| Claude Code cloud session | C2는 같은 hook events가 cloud session에도 발생한다고 설명 | local `~/.claude/settings.json`이 그대로 읽히지 않는다. runner 설정·plugin 전달 여부·network 접근 가능성과 transcript 가용성을 별도로 확인해야 한다. 회사 local endpoint가 cloud runner에서 닿는다고 가정하면 안 된다. |
| Claude Code `SessionStart` 자동 context | command hook 또는 준비된 로컬 HTTP 처리 경로에서 retrieval 후 context 반환 가능 | **launch의 `SessionStart`와 `Setup`에서는 MCP tool hooks가 서버 준비 전이므로 skip**된다. “MCP recall hook 하나면 처음부터 자동 회상”은 틀리다. `/clear`·compaction 뒤의 SessionStart는 조건이 달라진다. C2. |
| Codex local CLI/IDE/desktop host | O1 stdio/Streamable HTTP와 같은 host config 재사용; O2 local command·MCP tool hooks; `SessionStart/UserPromptSubmit`의 `additionalContext`가 developer context로 들어감 | non-managed hook는 exact definition hash를 review/trust해야 실행된다. project-local layer는 trusted project 필요. `prompt/agent` handler는 현재 문서상 **parsed but skipped**다. Claude prompt hook 설정을 그대로 옮길 수 없다. |
| Codex MCP tool hook | 이미 연결된 MCP 서버를 host event가 자동 호출 가능 | 서버를 시작하거나 재연결하지 않는다. `SessionStart`가 ready 전에 실행될 수 있고 errors/missing server가 operation을 block하지 않는다. `SessionEnd` MCP tool hook 미지원. tool hook 자체는 일반 tool approval 요청이나 다른 hooks를 유발하지 않는다. O2. |
| Work Cloud local-computer-access orchestration | O1/O2의 조건부 enterprise managed remote MCP hooks | cloud orchestrator의 admin-managed hooks에 한정. local config/plugin/command hooks와 `SessionEnd` MCP hooks는 지원되지 않으며 개인 계정에 이 enterprise hook 경로를 적용할 수 없다. local tool 실행과 local orchestration을 혼동하면 안 된다. |
| 일반 MCP 호환 chat host | host가 실제 지원하는 tools/resources/prompts와 optional elicitation | 이 조사로 lifecycle capture·transcript export·자동 context 주입이 확인된 것이 아니다. host가 별도 API를 제공하지 않으면 manual retain/recall 또는 사용자 export import만 지원한다고 명시해야 한다. |
| 설치형 standalone collector/application | 자료 제출·export import·공통 engine API를 직접 호출하는 own orchestration 가능 | installer는 host 내부에 관찰 API를 만들지 않는다. 지원되지 않은 host의 비공개 transcript scraping을 안정적 capture 계약으로 광고하면 안 된다. |

### 자동 주입과 선택적 회상의 차이

C2의 `additionalContext`는 UI chat에 보이지 않는 system reminder로 들어갈 수 있고, O2의 해당 event 반환은 developer context로 들어간다. host가 이를 높은 우선순위 메시지에 넣는다는 사실과 저장된 문장의 domain authority는 별개다. [설계 추론] hook wrapper는 회상 내용을 **출처가 있는 참고자료**로 구분하고, source 안의 명령을 규칙으로 해석하지 않게 해야 한다. 승인된 standing rule도 적용 scope·revision을 따로 확인한다.

질문별 MCP recall는 model이 필요성을 판단해 호출하는 선택적 경로이며, hook recall는 host lifecycle에 따른 자동 경로다. 자동이라고 전체 Facts를 매 turn 붙여야 하는 것은 아니다. [설계 추론] 가벼운 source index/관련 문서 참조와 task-scoped retrieval을 비교하고, 결과를 확인할 때 원문을 선택적으로 읽는 방식도 허용한다. H1/H3의 provenance carrier를 이 경로에 재사용할 수 있다. Claude hook context는 10,000 characters를 넘으면 file로 spill하고, Codex도 configurable token cap과 spill을 기술한다. spill된 file path가 실제 모델에 읽혔다는 뜻은 아니므로 context 전달과 source consumption을 구분한다. C2/O2.

### 모든 이벤트를 관찰했다고 해도 자동 완전성은 아니다

- **Claude transcript 지연**: C2의 `transcript_path`는 asynchronously written이며 현재 turn의 최근 메시지가 없을 수 있다. Stop에서 final text는 `last_assistant_message`를 우선 사용할 수 있다. SubagentStop에는 parent `transcript_path`와 child `agent_transcript_path`가 다르다. v2.1.271 이후 SubagentHandback을 쓰면 마지막 assistant text가 실제 delivered report가 아닐 수 있어 해당 tool message도 관찰해야 한다.
- **중단·오류**: Claude Stop은 user interrupt에서 실행되지 않고 API error는 StopFailure로 간다. Stop만 capture 지점으로 두면 누락된다. Codex는 main `Interrupt`가 따로 있지만 subagent Interrupt는 없으며 transcript path가 null일 수 있다.
- **Codex coverage**: O2는 local function tools를 폭넓게 관찰하지만 hosted `WebSearch`는 Pre/PostToolUse를 거치지 않는다고 명시한다. specialized path의 opt-out도 허용한다. 따라서 tool hooks만으로 모든 조사 source·모든 실패·완전한 audit를 확보했다는 주장은 금지한다.
- **UI 승인 누락**: C2 PermissionDenied는 **auto mode denial**만 관찰한다. 사용자가 수동 dialog에서 거절한 경우, PreToolUse block, deny rule에는 발생하지 않는다. O2 PermissionRequest는 승인 필요 직전이며, 사람이 최종 선택한 모든 결과를 내보내는 후속 feedback API로 기술되어 있지 않다. 이번에 읽은 docs로 전체 human accept/reject 이력을 자동 수집한다고 보장할 수 없다.
- **Fail-open**: O2 MCP tool hook 오류/timeout/malformed response가 tool을 자동 차단하지 않을 수 있다. C2도 기본 non-blocking 오류 경로가 있고 command/HTTP `onFailure: 'block'`은 v2.1.295+ 조건이다. capture 실패를 silence로 처리하면 “저장됨” 표시와 실제 데이터가 어긋난다. 정책 집행이 필요하면 host별 실패 의미를 명시해야 한다.

## 5. Engine 재사용과 새 extraction-control layer의 분담

| 요구 | 지정 Hindsight source에서 확인한 reuse | 별도로 구현하거나 입증해야 할 것 |
|---|---|---|
| 원문 provenance | H1 retain에 `document_id`, timestamp, metadata, tags. H3은 `original_text`, `chunk_id`, document/source fact 읽기를 제공 | original event identity·원문 byte hash·speaker/actor·source URI/commit/line range·수집 허가·redaction 전후 관계. engine chunk 연결은 임의 assertion의 실제 source span을 증명하지 않는다. 원문 비저장 옵션도 있으므로 실제 보존 범위 명시 필요. |
| 일반 facts·corrections 추출 | H2는 LLM으로 what/when/where/who/why/entities·perspective 추출. user preferences/rules/corrections/constraints는 world로 취급하도록 prompt에 명시 | correction 대상 claim, human-vs-agent 작성자, 근거 충돌, 작업 중 제안/미실행/실행 완료, coding artifact의 revision·scope를 판별하는 domain extraction과 검증. “correction을 전혀 못 저장한다”도 틀리고 “coding correction 통제를 자동 제공한다”도 틀리다. |
| 반복조사 집계 | H1 recall는 semantic/keyword/graph/temporal search; H2 experience에는 agent가 실제 한 조사도 표현할 수 있음 | topic identity와 **독립 parent run** 단위의 조사 episode, unresolved→resolved outcome, repeated costly work 기준, 같은 원문 재전송/요약/child handback 중복 제거. 검색 graph edge 수·observation source 수를 횟수로 대신하지 않기. |
| 형식 검사 | H2 Pydantic/schema와 H1 typed MCP arguments·response_schema | schema-typed≠truth. source 증거와 독립 validator, conflict/unsupported 분류. H11은 unknown tool args를 strip하고 string-encoded dict/list를 coerce한다. 이를 strict rejection 정책으로 과장할 수 없다. |
| 선택적 승인 | H5 operation validator는 accept/reject 및 tags/contents enrichment 가능 | reviewer 권한·candidate revision·approve/reject/defer 기록, 승인 없이 적용할 저위험 fact와 반드시 승인할 규칙의 구분. extension point는 구현된 승인 제품이 아니다. |
| 규칙 승격 | H1 directive create/delete, priority/is_active/tags와 reflect 적용 | recurrence/LLM recommendation만으로 active directive 만들지 않도록 권한 통제. 누구의 어느 환경에서 유효한 규칙인지와 promotion/revocation 기록. engine directive가 자동으로 host의 CLAUDE.md/AGENTS.md 권위로 바뀌지 않는다. |
| recall | H1 검색 budget/types/tags/tag_groups/min_scores, prefer_observations; H3 source enrichment 읽기 | 현재 task에 맞는 query·filter·scope, approved/current 상태 우선, 결과의 원문 재확인, host 주입·token budget·미회상 사유. MCP recall signature에는 include_chunks/include_source_facts 입력이 없으므로 내부 enrichment 기능을 모든 MCP 호출에 자동 노출된다고 하면 안 된다. |
| reflect·주기 합성 | H1 reflect/query/context/response_schema; based_on/trace 옵션; mental model full/delta·cron 또는 consolidation trigger | 합성을 진실/승인/현재성으로 대체하지 않기. 최신 provenance·거절 후보 제외·집계 근거를 유지. **MCP reflect는 include_based_on·include_trace가 기본 false**라 결과 text만 저장하면 provenance가 빠질 수 있다. |
| stale·retraction | H1 invalidate/restore, H4 based_on의 live ID 검사·pruning | artifact 변경·source URL 수정·환경 변경에 따른 **의미적 stale** 판정과 refresh 대상 선정. bank가 새 memory를 받았다는 사실은 외부 코드가 여전히 맞는다는 증명이 아니다. |
| forget·restore | H1 invalidate는 soft-retire/restore이며 audit 보존. H3 document delete는 row와 FK fact cascade. H9/H10 transfer 기능 | soft-retire를 개인정보 삭제라고 부르지 않기. host transcript·capture spool·backup·archive·cache·이미 주입된 context의 삭제·복원 의미까지 별도 명시. |

### 재사용 범위가 넓다는 반례도 반영

“engine는 단순 vector store이고 나머지는 모두 새 구현”은 지정 source에 맞지 않는다. H2는 generic fact extraction을 이미 갖고, H1에는 directive·mental model·invalidations·restore·operation 조회가 있으며 H5에는 request 통제 확장점이 있다. 같은 이유로 이를 복제한 두 번째 generic extraction/search/consolidation 계층을 무조건 만드는 것은 유지관리 비용만 늘릴 수 있다.

새 층은 **host 자료를 domain evidence로 바꾸고 적용 권위를 관리하는 작은 부분**에 집중한다. domain-specific extraction이 기존 H2의 custom instructions/strategy로 충족되는지 먼저 구분하되, 반복조사 ledger·approval 상태·원문 event identity를 prompt 한 문장으로 대신해서는 안 된다. 이것은 구현 완료 판정이 아니라 책임 경계에 대한 설계 추론이다.

## 6. 중복 집계·승인 feedback·최신성의 구체 반례

아래 예시는 설계 검토용 가상 사례이며 영상에서 관찰한 사건이 아니다.

### 6.1 세션과 parent-run

Codex O2는 subagent hook의 `session_id`가 **parent session ID**라고 명시하고 child를 `agent_id/agent_transcript_path`로 식별한다. Claude C2 역시 child events가 parent transcript와 child transcript를 함께 가리킬 수 있다.

가상 사례: 사용자가 한 번 조사 요청 → parent가 child 3개를 띄움 → 각 child final report → parent handback 요약 → Stop → SessionEnd export. 문자열만 보면 5개 이상의 “이 주제를 조사했다” 기록이 생기지만, 독립 사용 요청은 하나다. resume/compaction/Stop continuation이 추가되면 hook 호출 횟수는 더 커진다. **hook event count는 recurring-investigation count가 아니다.**

[설계 추론] 공통 envelope에는 최소 환경/host/session/root-run/turn/agent/event identity, original source hash와 span, parent-child 관계를 둔다. host가 root-run을 직접 주지 않으면 adapter가 제공 가능한 event identity에서 일관되게 매핑하고 미확정을 보존한다. 같은 event 재처리는 같은 집계 결과를 만들고, child와 parent 요약은 같은 investigation episode의 evidence로 합친다. 독립 episode 여부를 알 수 없을 때 “반복”으로 승격하지 않는다.

H6의 dedup는 같은 문서의 chunk index와 content hash를 비교하며, H5의 `processed_content_tokens`는 resubmitted growing document에서 실제 extraction을 거친 token 수를 표현한다. 이것은 유용한 **수집·추출 중복 최적화**지만 다른 문서·다른 표현의 child/parent 의미 중복이나 독립 조사 회수를 판정하는 기능은 아니다. bytes가 같아도 다른 날 같은 문제를 실제 다시 조사한 episode는 두 번일 수 있으며, bytes가 달라도 같은 run을 재요약한 것은 한 번일 수 있다.

### 6.2 승인과 거절

가상 사례: 사용자가 `retain` 실행을 허용했지만 저장 내용의 “모든 고객은 cloud endpoint를 사용한다”는 추론은 승인하지 않았다. tool permission을 fact approval로 승격하면 잘못된 규칙이 된다. 다른 경우 사용자의 “아니, 회사는 외부전송 금지”는 명시 correction이고, “지금 승인 dialog를 닫음”은 주장 반박이 아닌 cancel이다.

[설계 추론] host execution permission, capture consent, factual correction, candidate acceptance, rule promotion approval을 서로 다른 이벤트 타입으로 기록한다. 거절 이유가 없으면 `rejected_unknown_reason`에 머무르며 사실이 거짓이라고 학습하지 않는다. 같은 candidate revision을 다시 제안해 승인을 얻는 과정도 원래 rejection을 지우지 않는다. M5 elicitation은 UI 전달에 재사용할 수 있지만 actor 권위와 event 보존은 새 층의 책임이다.

### 6.3 stale·retraction·restore

H4는 **메모리 row의 부재**를 retracted grounding으로 검사한다. 살아 있는 source fact가 가리키는 repository 코드가 바뀌었다면 row live 검사는 여전히 통과한다. 즉 live≠current.

더 강한 반례는 `RetractedGrounding.unresolvable`이다. 모든 cited IDs가 한꺼번에 사라졌다면 import의 새 ID와 broken provenance일 수 있으므로 prose를 유지하고 dangling citations를 정리하는 쪽을 택한다. source comment는 그 결과로 **실제로 모든 grounding이 retract된 작은 page는 stale sentence를 이후 refresh까지 남길 수 있다**는 false negative를 인정한다. 이 정책을 “retraction은 항상 즉시 지식 문장까지 완전히 삭제한다”로 요약하면 틀린다. 본 조사에서는 해당 pure helper와 정책을 읽었고 모든 refresh caller가 모든 상황에서 얼마나 빨리 실행되는지 실행 검증하지 않았다.

H10은 target embedding으로 다시 embed하고 facts에 fresh ID를 만들며 whole-bank restoration에서 based_on ID repair를 고려한다. 따라서 logical transfer와 byte-identical DB restore는 다른 작업이다. 최신성 판정은 source revision/digest·확인 시각·scope를 별도로 보존하고, stale candidate를 재검증하는 경로가 필요하다. 복원도 삭제한 authority·rejected state·외부전송 권한까지 자동으로 되살리는 동작으로 취급하면 안 된다.

## 7. local/cloud의 의미 동일성과 strict no-egress

### 7.1 두 의미를 먼저 분리

- **memory plane만 local**: capture·DB·engine는 회사 내부에 있지만 host 모델이나 extraction/reflect/classifier는 승인된 외부 provider에 요청할 수 있다.
- **strict no-egress**: 회사 자료·프롬프트·사람 correction·파생 memory가 조직 경계 밖으로 나가지 않는다. DB가 local인 것만으로 충족되지 않는다.

D1은 extraction/entity resolution/answer generation에 LLM이 필요하다고 설명하며, Docker full image도 **LLM은 external process/API**, local inference를 포함해 이미지 밖에서 제공된다고 명시한다. 이것은 반드시 Internet이라는 뜻은 아니다. 같은 승인된 local network의 Ollama/vLLM/LM Studio/llama.cpp endpoint를 둘 수 있다. D2는 embedding과 cross-encoder의 초기 model download를 명시한다. 따라서 offline 환경은 model artifacts를 미리 준비하고 모든 모델 경로를 조직 경계 내부로 잡아야 한다.

C3의 hosted classifier는 user messages, read-only lookup을 제외한 tool calls, CLAUDE.md를 본다. 자체 classifier request에는 tool results가 stripped되지만 별도 server-side probe가 incoming results를 검사하며, server-side review는 session model requests 안에 포함될 수 있다. **“classifier가 위험 egress를 막으니 classifier로 보내는 transcript 자체도 no-egress다”라는 주장은 성립하지 않는다.** manual permission은 classifier 의존을 줄일 수 있지만 main host 모델의 외부 전송을 local로 바꾸지 않는다. 현재 이 조사에서 Claude Code의 완전 local inference를 입증하지 않았다.

[설계 추론] strict no-egress와 hosted model/classifier는 회사 자료가 그 provider로 실제 전달되는 한 양립하지 않는다. 양립하려면 (a) 경계를 승인된 private deployment까지 정의하고 계약·기술 정책이 이를 허용하거나, (b) 외부로 보낼 자료를 재식별·기밀 노출 없이 완전히 제거한 별도 경로로 한정하거나, (c) 모든 관련 inference를 내부로 옮겨야 한다. (a)는 public-hosted egress를 strict 금지한 요구와는 다른 운영 등급이다. redaction이나 private-network URL이라는 이름만으로 충족을 주장하지 않는다.

수집 hook의 HTTP endpoint, MCP remote endpoint, LLM, embedding, reranker, classifier, logging/tracing, model 다운로드, backup 업로드는 각각 별도 egress 경로다. MCP scope나 tool allowlist만으로 이 전체 경로를 통제했다고 할 수 없다. hook process가 parent environment를 상속한다는 C2 조건 때문에 memory adapter에 model/provider credential 전체를 넘기는 것 역시 자동으로 안전한 기본값이 아니다.

### 7.2 회사·개인 분리

H8 기본 `DefaultTenantExtension`은 **인증이 없고** 단일 schema를 사용한다. `ApiKeyTenantExtension`은 하나의 API key를 검증한 뒤 같은 schema를 반환하며, schema-per-tenant는 custom extension 책임이다. H11 single-bank endpoint·tool allowlist는 접속 면을 줄이지만 자체 고객별 authorization을 대체하지 않는다.

[설계 추론] 동일 domain pipeline을 다음처럼 재사용한다.

| 같은 것으로 유지 | 분리할 것 |
|---|---|
| evidence envelope·extraction taxonomy·correction 대상 연결·독립 episode 집계·candidate 상태 전이·규칙 승격 요건·recall eligibility·평가 fixture 의미 | 회사/외주 고객/개인 endpoint·DB/tenant 접근 권한·local spool·raw transcript·host config home/session/cache·API/OAuth credentials·model endpoints·backup 저장소·암호화 key·logs·운영자 권한 |

회사 원문을 개인 cloud에서 reflect하거나, 개인 host user-scope MCP 설정을 업무 session에 자동 사용하거나, 같은 bank ID라는 이유로 환경을 선택하면 분리를 깨뜨린다. connection token은 어느 tenant/bank를 읽고 쓸 수 있는지 server-side에서 제한해야 하며 caller가 준 tags를 authorization으로 삼으면 안 된다.

### 7.3 같은 engine와 DB만으로 같은 결과는 아니다

D1은 PostgreSQL 14+와 vector extension을 요구하며 embedded pg0는 development용이고 production에 권하지 않는다. Docker/pip/Helm 등 운영 형태가 다르다. 이는 Hindsight 후보의 설치·운영 제약이지, 모든 독립 제품이 PG여야 한다는 근거가 아니다.

H9/H10 logical export/import는 embeddings·DB IDs·derived links를 그대로 복사하지 않고 target에서 재생성한다. source는 **raw document uploads는 운반하지 않고 extracted `original_text`를 이용한다**고 명시한다. 다만 whole-bank data scope의 attachment rows와 그 bytes는 `attachments.json`/`blobs/` entries로 별도 운반하며 H10은 target file storage에 이를 복원한다. `file_storage` table을 skip한다는 이유로 모든 바이너리 자료가 archive에서 빠진다고 판단하면 안 된다. bank rows에는 config/directives/webhooks가 포함될 수 있다. 또한 H9의 streaming whole-bank export는 read 단계마다 connection을 빌리므로 동시에 수정된 bank의 여러 시점을 읽을 수 있다고 명시한다. logical archive는 자동으로 원자적 point-in-time backup이 아니다. 따라서 export archive를 데이터만 든 안전한 백업이라고 가정하거나 회사 archive를 개인 환경에 그대로 import하면 안 된다.

[설계 추론] 같은 의미를 검증하려면 source/extraction/control 정책 버전, model snapshot과 provider 설정, embedding/reranker, retrieval filter, prompt와 output-language 정책을 함께 고정한다. 동일 binary라도 다른 model 또는 target corpus에서는 결과가 달라질 수 있다. 같은 domain 계약은 **동일한 결정 규칙과 보존 가능한 근거**를 뜻하며 byte-identical 답변이나 동일 recall ranking을 뜻하지 않는다.

## 8. 비용·한국어·held-out action 검토

본 조사에서 모델이나 embedding을 호출하지 않았으므로 실제 비용·지연·한국어 정확도 측정값은 없다.

- D2 기본 embedding은 `BAAI/bge-small-en-v1.5`, cross-encoder는 `cross-encoder/ms-marco-MiniLM-L-6-v2`다. 한국어 품질을 English default 모델 이름만으로 입증할 수 없다. H2는 input 언어·script를 유지하도록 prompt를 넣고 explicit output-language 옵션을 지원하지만, **출력 한국어 유지와 한국어 검색/entailment/correction 품질은 다른 문제**다. H2의 상대일자 fallback regex가 `today/yesterday/last week` 등 English에 한정된 부분도 있다. 이것만으로 전체 한국어 처리가 불가능하다고 단정할 수는 없지만 English fallback의 이득을 한국어에 자동 전이했다고 할 수 없다.
- H1 recall의 `max_tokens`는 사실의 text budget이다. ID/tags/scores/date가 추가되므로 전체 MCP response는 더 크다. `min_scores`의 reranker absolute score는 query 간 calibrated가 아니며 temporal window는 특정 기간 밖의 memory를 hard exclude하지 않는다. token cap·score floor·날짜 window를 정확성/최신성 보증으로 쓰면 안 된다.
- H1 retain의 `status: 'accepted'`는 async storage initiation이다. operation completion이나 사실 정확성·human approval 완료를 의미하지 않는다.
- H1 mental-model cron은 stale 조건과 interval floor로 불필요 refresh 비용을 줄일 수 있다. H5 processed_content_tokens·folded_with는 실제 extraction 비용 attribution에 도움을 주지만 새 control layer의 LLM classification, host classifier, recall 주입으로 커진 host context, reflect, re-embedding 비용을 모두 포함하지 않는다.

[평가 설계 제안, 미실행] model/provider snapshot, reasoning effort, extraction prompt·schema·engine/control revision을 같은 조건으로 고정하고 **보지 않은 사건 기반 action 평가**를 둔다. 성공 기준은 저장한 fact 문장의 자연스러움만이 아니다.

1. 한국어와 혼합 code/identifier에서 human correction을 assistant 제안과 분리하는가.
2. child report·parent summary·resume export가 독립 조사 횟수를 부풀리지 않는가.
3. 승인되지 않은 rule candidate가 다음 작업의 행동을 바꾸지 않는가.
4. source revision 변경 후 stale 사실을 단정하지 않고 실제 artifact를 재확인하는가.
5. retract/forget/restore 뒤 다음 action이 폐기된 근거를 사용하지 않는가.
6. 회사 local에서 personal cloud credential·bank·backup 경로를 호출하지 않는가.
7. 필요한 사실이 recall되지 않은 경우 abstain/재조사를 선택하는가.

한국어·영어·혼합언어 strata와 무memory/선택적 recall/자동 context injection을 동일 모델 버전에서 비교해야 한다. 비용은 raw capture→extraction→approval→recall→reflect→host action까지 구간별로 기록하고, 고품질 but 큰 context가 action을 악화시키는 반례도 평가에 포함한다. 이 평가를 실행하거나 수치를 생성하지 않았다.

## 9. 최소 유지관리 범위와 미확인

**최소 유지관리 설계 추론**: 지원 host를 무제한으로 선언하지 말고, 확인된 Claude Code·Codex local adapter와 manual/export 경로를 capability별로 명시한다. 공통 원문/event envelope, 작은 extraction-control domain 모델, 하나의 engine adapter, 하나의 배포 정책 계약을 재사용한다. installer는 승인된 host 설정·service lifecycle·data 위치·backup/upgrade를 다루고, memory engine의 generic 검색·합성은 가능한 한 재구현하지 않는다. hosted/personal-cloud connector를 추가해도 회사 strict 모드의 경계는 바꾸지 않는다.

이 범위만으로도 관리할 것은 host 이벤트·transcript 포맷의 변경, hook trust/managed policy, 모델·embedding 설정, 데이터 migration, provenance ID remap, control state restore, credential/backup 분리다. 반대로 모든 host scraping, 모든 모델/provider fallback, 사용자 모르게 규칙 파일 자동 수정, global personal memory 동기화는 이번 근거로 필수 구성이라고 결론 낼 수 없다.

### 확인한 것

- 조사일 MCP current redirect revision과 protocol의 host/server 경계.
- Claude Code와 Codex live official docs의 capture·주입·MCP tool hook 기능 및 명시된 예외.
- 지정 core revision의 일반 extraction, MCP 연산, provenance carrier, dedup, invalidate/restore, retraction helper의 false-negative 정책, tenant 기본값, logical transfer 의미.
- 현재 installation/models 문서의 version 0.10과 local inference·PG·model 다운로드 제약.

### 확인하지 않은 것과 결정 영향

- 영상 전체의 시연/발언/개선 제안/미실행 구분: 부모의 transcript 재분석 대상이며 이 문서의 도구 기능을 영상 구현으로 소급하지 않는다.
- 설치된 host binary의 실제 hook support·network 연결·event loss율·current MCP revision 협상: 지원 선언 전 host/version 계약과 실행 확인이 필요하다.
- 전체 인간 UI 승인/거절 outcome export의 completeness: 읽은 hook docs는 이를 보장하지 않는다. domain approval UI/event를 따로 두거나 지원 범위를 제한해야 한다.
- Hindsight 모든 refresh caller·delete/restore 경로의 실행 시점과 모든 파생 state 정리: 읽은 source 범위만으로 즉시성·완전성을 보장하지 않는다.
- 다른 engine 후보들의 같은 조건 비교: 이 조사는 Hindsight source 재사용 경계에 한정한다. Hindsight/단일PG의 우승 verdict는 내리지 않는다.
- 한국어 품질·실제 단가·held-out action 성공률·strict offline 배포: 모델·서비스·제품 실행 없이 측정할 수 없으므로 수치를 주장하지 않는다.

**최종 반례**: remote MCP 하나를 연결해도 전체 대화 capture는 생기지 않고, local DB를 두어도 hosted classifier/model은 외부 데이터 경로가 될 수 있다. 일반 correction fact와 directive 도구가 있어도 human authority·independent-run 집계·live source 최신성은 자동으로 생기지 않는다. 반대로 현재 Claude/Codex host hooks와 Hindsight의 generic extraction·curation·reflect를 무시하고 모든 층을 새로 만드는 결론 역시 source에 맞지 않는다.
