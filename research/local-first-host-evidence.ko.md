# 다중 host 통합: MCP wire·hook·lifecycle 근거 보고 (조사일 2026-10-12)

범위: 공식 문서·고정 source의 계약만 다룬다. 실제 runtime 성공, 제품 구현, native model 리뷰가 아니다. omp 문서는 설치본 기준(18.3 이상, 정확한 버전 미기록). Claude 문서는 버전 표기가 없고 v2.1.295까지 언급한다. Codex 문서도 버전 표기가 없다.

## A. 근거 사실 12개

**F1 omp는 legacy MCP client다.** `connectToServer()`는 initialize를 `2025-11-25`로 보내고 roots를 광고하며, `ping`과 `roots/list`에 응답한다(omp://mcp-runtime-lifecycle.md "Connection establishment"). 설치 문서 전체에 `2026-07-28`, `server/discover`, `resultType`이라는 표기가 없다. legacy `sse`는 2024-11-05다. 영향: 2026 전용 server에 연결하면 실패할 가능성이 높다 [INFERENCE: spec matrix 기준].

**F2 spec이 legacy client를 위한 합법적 경로를 정해 둔다.** versioning.md의 Compatibility Matrix 기준이다.
- Legacy client + Modern server는 실패, Legacy client + Dual-era server는 동작한다.
- dual-era server는 두 era를 같은 endpoint나 process에서 동시에 제공할 수 있다(MAY).
- initialize를 받으면 legacy semantics를 그 stdio process나 HTTP session 범위에서 적용한다.
- modern-only server는 initialize 오류에 지원 version을 적어야 한다(SHOULD).
- `serverInfo`는 보안 판단에 쓰면 안 된다(SHOULD NOT, discover.md).
- 끊긴 stream은 새 request ID로 다시 보내야 하며(MUST), `Mcp-Session-Id`는 제거됐다(changelog Major 1·9).
- 따라서 JSON-RPC id나 session은 idempotency key나 identity가 될 수 없다. cross-call state는 server가 발급한 handle을 tool 인자로 넘긴다.

**F3 host마다 MCP era가 다르다.**
- Claude Code: v2 runtime은 TS SDK 2.0 기반이며 2026-07-28을 지원한다. server에 지원 여부를 묻고, 지원하지 않으면 v1처럼 연결한다. feature flag를 가져오는 session은 v2.1.232 이상, 그 밖은 v2.1.274 이상에서 기본값이다. `MCP_PROTOCOL_NEGOTIATION=legacy`로 강제할 수 있다(code.claude.com/docs/en/mcp "MCP client runtimes").
- Codex: 문서는 initialize의 instructions를 쓴다고만 적고, 앞 512자를 권장한다. source commit `f2bee854`(2026-07-28)가 discovery, MRTR, legacy fallback(test 기준 2025-06-18)을 추가했다. 이 commit은 이전 조사에서 고정한 0.162.1 source `092d3acd`의 조상이다(GitHub compare 결과 ahead, behind 0). 설치본의 실제 runtime 동작은 확인하지 않았다.

**F4 model 입력 전 hook.**
- Claude `UserPromptSubmit`: `additionalContext`를 prompt 옆에 붙이거나 block할 수 있다. 기본 timeout은 30초이고, timeout이면 context는 버려지고 prompt는 그대로 진행된다. 막으려면 `onFailure:"block"`(v2.1.295 이상)이 필요하다. 사용자가 입력한 prompt 외에 scheduled task, background subagent 보고, 다른 session의 message에도 실행된다.
- Codex `UserPromptSubmit`: developer context를 추가하거나 block할 수 있고, matcher는 지원하지 않는다.
- omp:
  - `before_agent_start`는 일반 prompt와 dequeue된 batch마다 실행되며 같은 제출에 대해 재진입할 수 있다(최대 3회 시도). handler의 외부 side effect는 롤백되지 않는다.
  - `context`는 LLM 호출마다 message를 교체하고 저장하지 않는다.
  - `input`은 interactive와 RPC에서만 실행되고 print와 ACP에서는 실행되지 않는다(omp://extensions.md "Prompt and turn lifecycle").

**F5 tool 직전 차단과 context 전달 시점.**
- Claude PreToolUse: precedence는 deny > defer > ask > allow이고 deny 사유는 Claude가 본다. `additionalContext`는 tool result 옆에 붙는다. 사용자 정의 deny·ask rule은 hook 결과와 관계없이 계속 평가된다. `if` 필터는 best-effort이므로 강제가 필요하면 permission rule을 쓰라고 안내한다. timeout은 기본적으로 차단하지 않는다.
- Codex: deny, exit 2, legacy block을 지원한다. `updatedInput`은 allow와 함께일 때만 받는다. `ask`나 `continue:false`를 반환하면 hook이 실패로 처리되고 tool은 계속 실행된다. hosted tool(WebSearch 등)에는 hook이 없다. 문서 스스로 'complete enforcement boundary가 아니다'라고 쓴다.
- omp `tool_call`: block에서 short-circuit하고 handler throw나 timeout은 fail-closed다(30초). `additionalContext`는 tool이 실제로 실행되어 오류 없이 끝났을 때만 결과 뒤에 전달된다.
- 결론: context를 붙이고 allow하는 방식은 첫 쓰기 전에 규칙을 전달하지 못한다. 실행 전에 규칙을 보장하는 수단은 deny와 사유뿐이다.

**F6 compact·resume·fork 신호.**
- Claude:
  - `SessionStart`의 source는 startup·resume·clear·compact·fork다. v2.1.214 전에는 fork가 resume으로 보고됐다.
  - 주입한 text는 transcript에 저장되고 resume 때 hook을 다시 실행하지 않고 replay한다(값이 stale해질 수 있음). context를 회수할 수 없다는 근거다.
  - PreCompact는 block할 수 있고, PostCompact는 관찰만 한다.
  - skill은 compaction 뒤 skill당 5,000 token, 합계 25,000 token까지만 다시 붙는다.
- Codex:
  - SessionStart의 source에 fork가 없다.
  - compact 뒤 `source:compact`가 다음 요청 전에 실행되며 turn 중간에도 실행된다.
  - `thread/fork`는 새 id와 `forkedFromId`를 주지만 `sessionId`는 root 것을 유지한다(app-server.md).
- omp:
  - compact: `session_before_compact`(cancel 또는 교체), `session.compacting`(context, preserveData), `session_compact`.
  - fork: `session_before_switch`/`session_switch`를 reason fork로 내보내고, 새 id와 `parentSession`을 가진다. entry fork는 `session_branch`를 reason fork로 내보낸다.

**F7 child 상태 분리.**
- omp:
  - factory는 subagent마다 다시 bind되지만 module-level 변수는 공유된다(extensions.md L67).
  - `ctx.agent`(`kind`·`id`·`name`·`depth`·`parentId`)를 key로 써야 한다.
  - child는 parent의 MCP 연결을 공유하는 proxy를 쓴다(tools/task.md L190). server는 연결만으로 parent와 child를 구분할 수 없다.
  - `session_stop`은 subagent에서 발생하지 않고, `before_subagent_spawn`은 model 선택과 block만 할 수 있다.
- Claude:
  - tool hook에 `agent_id`와 `agent_type`이 들어온다.
  - SubagentStart context는 이미 child context에 있으면 다시 넣지 않는다.
  - fork가 아닌 subagent는 새 context에 CLAUDE.md 계층을 받는다(Explore와 Plan은 제외). fork는 전체 대화를 상속한다.
  - 이름으로 참조한 `mcpServers`는 parent 연결을 공유한다.
- Codex: subagent hook의 `session_id`는 parent 것이다. SubagentStart context는 child의 developer context로 들어가며 child 시작을 막을 수 없다. mcp_servers와 skills.config는 따로 지정하지 않으면 상속된다.
- 결론: 세 host 모두 session id만으로는 child나 fork lineage를 유일하게 식별할 수 없다.

**F8 출력 소유권, 동시 실행, 예산.**
- Claude: 여러 hook의 `additionalContext`가 모두 전달된다. 10,000자를 넘으면 파일로 넘기고 앞 2,000자 preview만 준다. async hook은 결정을 내릴 수 없다.
- Codex: 같은 event에 걸린 command hook을 동시에 실행한다. `additionalContext`가 약 2,500 token을 넘으면 temp 파일로 넘긴다. background hook은 session당 최대 8개다. MCP tool hook은 연결을 새로 만들지 않고, 오류가 나도 차단하지 않는다.
- omp: `tool_call`의 `input`은 마지막 handler 값이 적용되고, 같은 내용의 context는 중복 제거된다. `before_agent_start`는 첫 message만 유지한다.

**F9 관리자와 trust 설정이 hook을 무력화할 수 있다.**
- Claude:
  - `allowManagedHooksOnly`가 켜지면 user, project, local, plugin hook이 막힌다.
  - settings hook은 workspace trust를 확인한 뒤 실행된다.
  - SessionStart 시점의 `mcp_tool` hook은 launch 때 skip된다. command hook을 써야 한다.
- Codex:
  - 관리되지 않는 hook은 hash 기준으로 trust 받아야 실행된다.
  - project hook은 project가 trusted일 때만 실행된다.
  - `requirements.toml`로 hooks를 끌 수 있다.
- 회사 환경에서는 hook capability가 none일 수 있다.

**F10 schema 공개 지연과 hidden metadata.**
- Claude: tool search가 기본이라 처음에는 tool 이름과 server instructions만 load한다. 설명과 instructions는 2,048자에서 자른다. `_meta` key로 `anthropic/alwaysLoad`, `anthropic/maxResultSizeChars`(최대 500k), `anthropic/requiresUserInteraction`가 있다.
- omp: discoverable tool을 `xd://` catalog로 보이고 문서는 필요할 때 읽는다(settings.md L616-617). server instructions를 system prompt에 4,000자까지 붙인다. tool 호출 전에 `i` 필드 제거, 값이 빈 optional 생략, `local://`를 실제 경로로 바꾼다.
- vendor `_meta`는 host마다 다르다.

**F11 재전송 위험.**
- omp: MCPTool과 DeferredMCPTool은 retriable 연결 오류가 나면 reconnect 뒤 1회 재시도한다. 수락된 SSE POST 이후에는 다시 보내지 않는다. stdio는 자동 재시작하지 않고, manager가 backoff(0.5s→4s) 뒤 연결하며, 30초 안에 5회를 넘으면 circuit breaker가 작동한다.
- MCP 2026에서는 재전송할 때 request ID가 바뀐다.
- 따라서 상태를 바꾸는 operation에는 domain idempotency key가 필수다.

**F12 omp 규칙 파일 경로는 root-free 원칙과 맞지 않는다.**
- rulebook은 이름과 설명을 system prompt에 바로 나열하고, alwaysApply는 본문 전체를 바로 주입한다.
- TTSR은 stream을 끊고 주입하며, rulebook의 globs는 권고일 뿐 강제되지 않는다(rulebook-matching-pipeline.md §5-7).
- 승인된 규칙을 `.omp/rules`로 내보내면 eager listing이 생기거나 권위 있는 사본이 둘이 된다. 기본안으로 부적합하다.

## B. 공통 capability 어휘 [제안]

각 capability의 상태는 `native`, `partial`, `none`, `unknown` 중 하나이며, host·version별 manifest로 선언한다.

- `ctx.prompt`: model 입력 전 per-turn context
- `gate.prompt`: prompt 차단
- `ctx.session{startup,resume,clear,compact,fork}`: session 시작과 재평가 trigger
- `gate.tool.deny`: tool 실행 전 deny와 사유
- `tool.rewrite`: tool 입력 교체
- `ctx.tool.after`: tool 실행 뒤 context
- `ctx.child`: subagent 시작 context
- `lineage{session,agent,turn,tool_call}`: 식별자
- `fail_mode{open,closed,configurable}`: hook 실패 처리
- `ctx.persisted{replay,ephemeral}`: 주입한 context의 저장 여부
- `mcp.era{legacy,modern,dual}`: MCP era
- `capture.turn_end`: turn 종료 시 capture

## C. host별 matrix (문서·source 계약 기준)

| 항목 | omp(설치 docs) | Claude Code | Codex(docs/source) |
|---|---|---|---|
| mcp.era | legacy 2025-11-25 | v1 legacy, v2 dual | 문서는 initialize, source는 dual |
| ctx.prompt | before_agent_start, context | UPS additionalContext | UPS additionalContext |
| gate.tool.deny | tool_call block(fail-closed) | deny(기본 fail-open, onFailure 설정 시 차단) | deny/exit2(fail-open 추정) |
| ctx.session fork | switch/branch reason fork | source fork | none(app-server의 forkedFromId만) |
| compact | before, compacting, compact | PreCompact, PostCompact, SessionStart compact | Pre/Post, SessionStart compact |
| lineage | ctx.agent, toolCallId, parentSession | session, agent_id, prompt_id, tool_use_id | parent session_id, turn_id, agent_id |
| ctx.persisted | context는 ephemeral, 나머지 unknown | replay | unknown |
| 관리자 차단 | 없음(문서 기준) | allowManagedHooksOnly | trust hash, requirements |

## D. 오래된 initialize client를 위한 명시적 edge

omp, Claude v1 runtime, `MCP_PROTOCOL_NEGOTIATION=legacy`, Codex fallback 경로는 initialize를 쓴다. 이들은 dual-era server나 별도 legacy stdio edge에 붙을 수 있으며, spec은 Legacy + Dual-era를 동작하는 조합으로 정한다(versioning.md).

조건은 다음과 같다.
- 두 edge 모두 같은 domain operation, schema, handle, idempotency key, auth binding을 써야 한다.
- legacy session이나 `Mcp-Session-Id`, `clientInfo`를 identity, 권한, worker 상태로 쓰지 않는다.
- edge가 다르면 지원 범위를 다르게 선언한다(예: legacy edge에서 MRTR 없음).
- modern-only 배포가 omp에서 실패하는 것은 정상 결과다. 'v2만으로 모든 host와 호환'이라고 주장하지 않는다.

## E. 일반 prompt에서 project·phase·path를 모를 때 [제안]

- project: hook의 cwd를 git root로 해석해 정한다. 해석이 안 되면 `scope_unresolved`를 반환하고 화면에 보이게 한다. 개인 scope로 fallback하지 않는다.
- phase를 모르는 것을 wildcard로 취급하지 않는다. phase 조건이 있는 mandatory는 보내지 않는다.
- path 조건이 있는 mandatory는 첫 실제 path가 정해질 때 `gate.tool.deny`로 처리한다.
- optional semantic 결과는 별도 예산 안에서만 보낸다.
- 이미 전달한 rule ID와 revision은 lineage watermark로 중복을 막고, compact·resume·fork 때 다시 평가한다.

## F. local 수용 시나리오 [제안, 실행하지 않음]

1. dual-era stdio에서 omp initialize client와 modern client가 같은 operation을 호출하면 결과 digest와 revision이 같다.
2. modern-only server에 legacy client가 initialize를 보내면, 오류에 지원 version이 적혀 있다.
3. commit 뒤 응답이 유실되면, request id가 새로 바뀌어도 key가 같으면 durable record는 하나만 생긴다.
4. stdio의 `notifications/cancelled`와 HTTP stream 종료가 완료와 경합해도 반쯤 commit된 상태가 생기지 않는다.
5. host 3개에서 path 없는 일반 prompt를 처리할 때 phase·path 조건 rule은 빠지고 응답은 예산 안에 든다.
6. 첫 쓰기 시도는 deny와 rule ID·digest를 받고, watermark 확인 뒤 allow된다. allow와 context만 붙인 경우는 전달로 세지 않는다.
7. Claude의 compact·fork, Codex의 compact, omp의 compact·fork 뒤 watermark를 다시 평가하고 중복을 막는다.
8. omp module 변수에 상태를 저장하지 않는다. `ctx.agent`, Claude `agent_id`, Codex `agent_id` 기준으로 child 상태가 분리된다.
9. hook timeout이 나면 Claude는 fail-open하고 omp는 fail-closed한다. 어느 쪽이든 결과에 degraded로 표시한다.
10. company와 personal route를 adapter 설정으로 선택하고, `serverInfo`나 `clientInfo`로 정하지 않는다.

## G. 금지할 과대주장

- 모든 host가 MCP 2026을 지원한다, 또는 v2만으로 모든 host와 호환된다.
- hook 출력이 model 준수를 보장한다, 또는 allow와 context가 첫 쓰기 재계획을 보장한다.
- PreToolUse가 보안 경계다.
- session_id는 child나 fork마다 유일하다.
- 한번 주입한 context를 회수할 수 있다(Claude는 resume 때 replay).
- Claude SessionStart 시점에 mcp_tool hook을 쓸 수 있다.
- Codex hook이 hosted tool도 잡는다.
- omp가 Claude의 settings JSON hook을 실행한다(근거 없음).
- tool annotation이나 serverInfo를 신뢰할 수 있다.
- Codex 0.162.1에서 modern MCP가 실제로 동작함을 확인했다(source 조상 관계만 확인).

## H. 미확인

- 설치된 Claude, Codex, omp의 정확한 version과 실제 negotiate 결과
- Codex UPS context가 저장되는지, resume 때 replay되는지
- Codex PreToolUse context의 전달 시점과, exit 2가 아닌 실패의 처리
- Codex hook에 fork source가 있는지
- omp `before_agent_start` message의 저장 방식
- Claude `prompt_id`가 재시도 사이에 안정적인지
- `updatedInput`으로 lineage를 인자에 찍을 때 allow가 함께 적용되어 approval이 생략될 위험