# Native 계정 judge 후보: effortless / Jevbridge 고정 소스 적대적 검토

## 0. 범위·판정

공개 소스 읽기만 수행했다. 설치·clone·실행·빌드·테스트·formatter·benchmark는 수행하지 않았고, 작업 트리 및 인증/secret 파일도 열거나 변경하지 않았다. 아래 테스트 언급은 **테스트 소스에 적힌 계약**이지 통과 결과가 아니다. GitHub tree API의 최초 요청은 403, URL 대상 `find`는 `Path not found`였다. GitHub 웹 tree 및 raw 고정 URL로 대체해 실제 파일과 내부 호출을 읽었다. 따라서 최초 실패를 구현 부재의 증거로 사용하지 않았다. codegraph는 전달받은 no-index 조건에 따라 사용/생성하지 않았다.

| 대상 | 고정 SHA / 확인한 package 버전 | 결론 |
|---|---|---|
| **HeyCubit/effortless** | `e553b18e9f5e8ce3533f3ce9c666e7e8bc9234f9` / manifest `1.71.0` | `askHaiku`는 실제로 Claude Code 내부 mods API인 `$.model.complete`를 호출한다. 기존 세션 credentials를 사용하는 기술 경로가 공식 문서에도 명시되어 있다. 단, 외부 MCP/Node가 import해서 쓰는 일반 Anthropic SDK/API가 아니다. 회사 승인 없는 mod 설치나 runtime pin 없이 그대로 채택하지 않는다. |
| **tacticocc/Jevbridge** | `d4e8f7d483b8a5649218970eedbaf4f4a1e1e832` / package `0.2.0` | 분류기의 Claude 경로는 **Anthropic API key + HTTP Messages API**다. native Claude/Codex를 연결하는 ACP proxy 경로도 존재하지만 **별도 생성 upstream**이며 judge가 native 구독 실행으로 fallback하는 경로는 아니다. 개인 cloud Jev seam의 참고로 제한한다. |

`crystal-aim/effortless-claude-code`는 다른 제품이며 본 조사 근거에 포함하지 않았다. Native 기술 가능성 ≠ 회사 설치/사용 승인 ≠ 서비스 약관 허용 ≠ 비용·품질 보장이다.

## 1. 출처 및 라이선스

두 프로젝트 모두 **MIT**다. effortless는 `Copyright (c) 2026 HeyCubit`, Jevbridge는 `Copyright (c) 2026 Tactico Technologies`. 복사/상당 부분 재사용 시 copyright 및 permission notice 유지가 필요하며 AS IS, 무보증 조항이 있다. 이 라이선스는 Claude Code runtime, Claude 구독, TypeSafe 서비스 이용권/약관을 대신하지 않는다. [E-L][J-L]

### 고정 출처 목록

이 보고서의 `[E…]`, `[J…]`는 모두 아래 SHA 고정 링크다. 함수 이름으로 재탐색할 수 있도록 주요 entry와 parser를 함께 명시했다.

- **[E-L]** [effortless LICENSE](https://github.com/HeyCubit/effortless/blob/e553b18e9f5e8ce3533f3ce9c666e7e8bc9234f9/LICENSE)
- **[E-R]** [effortless README](https://github.com/HeyCubit/effortless/blob/e553b18e9f5e8ce3533f3ce9c666e7e8bc9234f9/README.md)
- **[E-M]** [plugin manifest / userConfig](https://github.com/HeyCubit/effortless/blob/e553b18e9f5e8ce3533f3ce9c666e7e8bc9234f9/.claude-plugin/plugin.json)
- **[E-H]** [hooks/modules loader](https://github.com/HeyCubit/effortless/blob/e553b18e9f5e8ce3533f3ce9c666e7e8bc9234f9/hooks/hooks.json)
- **[E-P]** [JUDGE_SYSTEM, parseVerdict, contextFrom](https://github.com/HeyCubit/effortless/blob/e553b18e9f5e8ce3533f3ce9c666e7e8bc9234f9/hooks/register.tsx#L351-L415)
- **[E-J]** [parseJevAnswer, key selection, judge, askJev, askHaiku](https://github.com/HeyCubit/effortless/blob/e553b18e9f5e8ce3533f3ce9c666e7e8bc9234f9/hooks/register.tsx#L518-L809)
- **[E-X]** [prompt.submit → judge → turn.step](https://github.com/HeyCubit/effortless/blob/e553b18e9f5e8ce3533f3ce9c666e7e8bc9234f9/hooks/register.tsx#L4045-L4277)
- **[E-S]** [register / session.start / stored state](https://github.com/HeyCubit/effortless/blob/e553b18e9f5e8ce3533f3ce9c666e7e8bc9234f9/hooks/register.tsx#L3773-L3839)
- **[E-G]** [proof logging](https://github.com/HeyCubit/effortless/blob/e553b18e9f5e8ce3533f3ce9c666e7e8bc9234f9/hooks/register.tsx#L1027-L1063)
- **[E-U]** [latestFromGit, latestAvailable, startTimers, afterLoad](https://github.com/HeyCubit/effortless/blob/e553b18e9f5e8ce3533f3ce9c666e7e8bc9234f9/hooks/register.tsx#L2620-L2789)
- **[E-C]** [Haiku compaction / cold handoff](https://github.com/HeyCubit/effortless/blob/e553b18e9f5e8ce3533f3ce9c666e7e8bc9234f9/hooks/register.tsx#L3694-L3802)
- **[E-T]** [judge timeout/error mocked tests](https://github.com/HeyCubit/effortless/blob/e553b18e9f5e8ce3533f3ce9c666e7e8bc9234f9/tests/effortless.test.ts#L1058-L1090), [Jev unsure test](https://github.com/HeyCubit/effortless/blob/e553b18e9f5e8ce3533f3ce9c666e7e8bc9234f9/tests/effortless.test.ts#L1562-L1587)
- **[J-L]** [Jevbridge LICENSE](https://github.com/tacticocc/Jevbridge/blob/d4e8f7d483b8a5649218970eedbaf4f4a1e1e832/LICENSE)
- **[J-R]** [README](https://github.com/tacticocc/Jevbridge/blob/d4e8f7d483b8a5649218970eedbaf4f4a1e1e832/README.md), [SECURITY](https://github.com/tacticocc/Jevbridge/blob/d4e8f7d483b8a5649218970eedbaf4f4a1e1e832/SECURITY.md)
- **[J-E]** [evaluate / resolveBackend](https://github.com/tacticocc/Jevbridge/blob/d4e8f7d483b8a5649218970eedbaf4f4a1e1e832/src/evaluate.ts)
- **[J-C]** [evaluateJev](https://github.com/tacticocc/Jevbridge/blob/d4e8f7d483b8a5649218970eedbaf4f4a1e1e832/src/client.ts)
- **[J-A]** [systemOnePrompt, coerceAnswers, extractJson, chatAnthropic, evaluateLlm](https://github.com/tacticocc/Jevbridge/blob/d4e8f7d483b8a5649218970eedbaf4f4a1e1e832/src/llm-adapter.ts)
- **[J-N]** [clamp01, normalizeMap, argmax, flattenState](https://github.com/tacticocc/Jevbridge/blob/d4e8f7d483b8a5649218970eedbaf4f4a1e1e832/src/normalize.ts)
- **[J-K]** [envJev / envLlm](https://github.com/tacticocc/Jevbridge/blob/d4e8f7d483b8a5649218970eedbaf4f4a1e1e832/src/env.ts), [provider catalog](https://github.com/tacticocc/Jevbridge/blob/d4e8f7d483b8a5649218970eedbaf4f4a1e1e832/src/providers.ts)
- **[J-Q]** [parseQuestion / parseQuestions](https://github.com/tacticocc/Jevbridge/blob/d4e8f7d483b8a5649218970eedbaf4f4a1e1e832/src/questions.ts), [types / endpoint](https://github.com/tacticocc/Jevbridge/blob/d4e8f7d483b8a5649218970eedbaf4f4a1e1e832/src/types.ts)
- **[J-M]** [MCP tools / runEvaluate / callMcpTool](https://github.com/tacticocc/Jevbridge/blob/d4e8f7d483b8a5649218970eedbaf4f4a1e1e832/src/mcp/tools.ts), [MCP stdio](https://github.com/tacticocc/Jevbridge/blob/d4e8f7d483b8a5649218970eedbaf4f4a1e1e832/src/mcp/stdio.ts)
- **[J-B]** [package](https://github.com/tacticocc/Jevbridge/blob/d4e8f7d483b8a5649218970eedbaf4f4a1e1e832/package.json), [bin launcher](https://github.com/tacticocc/Jevbridge/blob/d4e8f7d483b8a5649218970eedbaf4f4a1e1e832/bin/jevbridge.mjs), [CLI](https://github.com/tacticocc/Jevbridge/blob/d4e8f7d483b8a5649218970eedbaf4f4a1e1e832/src/cli.ts)
- **[J-U]** [ACP upstream presets](https://github.com/tacticocc/Jevbridge/blob/d4e8f7d483b8a5649218970eedbaf4f4a1e1e832/src/acp/upstream.ts), [ACP spawn/stdio](https://github.com/tacticocc/Jevbridge/blob/d4e8f7d483b8a5649218970eedbaf4f4a1e1e832/src/acp/stdio.ts)
- **[J-P]** [ACP proxy](https://github.com/tacticocc/Jevbridge/blob/d4e8f7d483b8a5649218970eedbaf4f4a1e1e832/src/acp/proxy.ts), [interceptToolCall](https://github.com/tacticocc/Jevbridge/blob/d4e8f7d483b8a5649218970eedbaf4f4a1e1e832/src/acp/intercept.ts)
- **[J-S]** [ACP sidecar](https://github.com/tacticocc/Jevbridge/blob/d4e8f7d483b8a5649218970eedbaf4f4a1e1e832/src/acp/sidecar.ts), [SessionStore](https://github.com/tacticocc/Jevbridge/blob/d4e8f7d483b8a5649218970eedbaf4f4a1e1e832/src/acp/session-store.ts)
- **[J-G]** [gate](https://github.com/tacticocc/Jevbridge/blob/d4e8f7d483b8a5649218970eedbaf4f4a1e1e832/src/gate.ts), [MCP test source](https://github.com/tacticocc/Jevbridge/blob/d4e8f7d483b8a5649218970eedbaf4f4a1e1e832/src/mcp/tools.test.ts)

공식 runtime 문서는 **고정 SHA 소스가 아닌 조사 시점의 live 문서**다. 대상 SHA에서 쓰는 API와 현재 공식 설명을 구분해야 한다.

- **[O-A]** [Claude Code mods API — Call a model](https://code.claude.com/docs/en/plugins/mods/api#call-a-model)
- **[O-R]** [Mods reference — methods / limits](https://code.claude.com/docs/en/plugins/mods/reference)
- **[O-V]** [Mods overview — where mods run / early-access flag / permissions](https://code.claude.com/docs/en/plugins/mods/overview)
- **[O-E]** [Hook failure / middleware behavior](https://code.claude.com/docs/en/plugins/mods/events#handle-a-hook-that-fails)
- **[O-T]** [Official public declaration snapshot, mutable main](https://github.com/anthropics/claude-code/blob/main/mods/types/claude-code.d.ts)

## 2. effortless: 실제 실행·인증 seam

### 2.1 호출 그래프

```text
hooks/hooks.json: modules [./register.tsx]
  → export register(on, options)
  → on('prompt.submit')
      origin composer / bridge / sdk 확인
      auto 여부, slash skill, model cacheSafe, follow-up/명시 effort 처리
      → judge($, shown, current)
          → recentContext → $.session.messages → contextFrom
          → (judge != haiku인 경우) jevKey
          → 키 있으면 askJev
              정상 확신 → Jev verdict
              unsure → haikuAfter → askHaiku
              HTTP/parse/timeout 실패 → askHaiku
          → 키 없으면 askHaiku
              → $.model.complete
              → parseVerdict
      → tipped / bounded / capped → choose
  → on('turn.step')에서 next에 전달할 model / effort 실제 수정
```

이것은 단순 source prompt 지침이 아니라 hook 함수가 실제 request를 바꾸는 코드다. 다만 `JUDGE_SYSTEM`의 의미·품질 요청은 여전히 자연어 지침이며 파서가 정확성까지 보장하지 않는다. [E-H][E-S][E-X][E-J]

### 2.2 `$.model.complete`는 무엇인가

`register.tsx`는 `atom/read/update`와 `EngineInterface`를 **`claude-code`**에서 import하고, `$`는 runtime이 hook 인자로 주입한다. `askHaiku` 자체는 키를 파싱하거나 OAuth credential 파일을 열지 않으며 별도 `claude -p` subprocess도 실행하지 않는다. `$.model.complete({ model, system, prompt, maxTokens:160, effort:'low', timeoutMs:6000 })`를 호출한다. [E-J]

**중요 교정:** 이는 third-party가 꾸며낸 `$`만으로 판단할 수 있는 미공식 hack도, 일반 Anthropic Messages API의 stock 메서드도 아니다. 현재 **Anthropic 공식 Claude Code docs에 문서화된 mods API**다. 공식 문서는 complete/fork가 “session's credentials”를 사용하여 **사용자 plan, API key, cloud provider**에 청구된다고 명시한다. 따라서 기존 Claude 로그인으로 동작한다는 사용자 관찰은 공개 소스·공식 문서와 정합적이다. 하지만 이 세션이 구독 인증인지 API 인증인지는 코드만으로 결정하지 않는다. [O-A][O-V]

외부 MCP 서버에서 `$`를 생성하거나 `claude-code` npm import만 하면 이 기능을 쓸 수 있다는 근거는 없다. 공식 문서는 mod가 Claude Code **안에서** 실행되며 외부 접근은 mods API를 통한다고 설명한다. 설치된 mod는 `claude -p`/Agent SDK에서도 hooks를 실행할 수 있다고 설명하지만, effortless 자체의 입력 origin·model gate를 모두 통과한다는 실실행 검증은 하지 않았다. [O-V][E-X]

**버전 계약이 핵심:** README는 CLI에서 `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1`를 제안하고 2.1.285/286/288에서 시험했다고 주장한다. 현재 공식 docs는 terminal 2.1.287+, Desktop 2.1.286부터 mods 지원, 2.1.287+에서 해당 early-access env는 무시되므로 제거하라고 설명한다. 또 읽은 공식 GitHub `main` 선언은 `complete: Promise<string>` 및 model/prompt/system/maxTokens만을 적지만, effortless는 `{isAnswered,text,usage}`와 effort/timeoutMs를 기대한다. 공식 reference는 GitHub 선언이 installed build보다 오래될 수 있으며 **build별 생성 타입을 우선**하라고 명시한다. 이 차이를 감추고 모든 stock Claude 버전에서 보장된다고 하면 안 된다. 현재 문서는 mods를 공식 지원 경로로 설명하지만, API 장기 불변/SLA를 보증하지 않는다. [E-R][O-V][O-R][O-T]

### 2.3 입력·출력과 상태 한계

- complete는 **하나의 user prompt**, attribution + 선택 system만 보낸다. session history/CLAUDE.md/도구는 자동 첨부하지 않는다. fork는 반대로 기존 conversation/project context를 포함한다. effortless effort judge는 complete를 사용한다. [O-A]
- `contextFrom`: 최근 user 앞 **400 chars**, 최근 nonempty assistant 끝 **2,000 chars**. Haiku `judgeQuestion`: 다음 메시지 앞 **2,000 chars**, current pair, recent conversation. 추가로 관측된 context window 사용 비율을 넣는다. Jev는 다음 메시지 앞 **4,000 chars**를 전송한다. 이것은 토큰 상한이나 원문 근거 보존이 아니라 **문자 기반 잘림**이다. 이미지/첨부는 type/count를 표시하고 실제 내용은 읽지 않는다. [E-P][E-J][E-X]
- 짧은 follow-up은 기존 effort를 유지하여 호출을 생략한다. assistant의 질문에 답하는 follow-up이면 recent context를 근거로 재판단한다. 이 최적화는 effort 조절 맥락에 특화되어 있으며 memory 후보 분류에 그대로 옮기면 서로 다른 후보를 동일 판정으로 취급할 위험이 있다. 마지막 문장은 적용상의 **[INFERENCE]**다. [E-P][E-X]
- Haiku 출력은 자연어 “JSON only” 요청일 뿐 **JSON Schema / constrained output 요청은 없다**. `parseVerdict`는 첫 `{`부터 마지막 `}`까지 greedy 추출, JSON.parse, model lookup, effort enum 검사. model은 정확 enum뿐 아니라 model ID나 `key.includes(m.key)`도 허용한다. sure는 number 0..1일 때만 보존, why는 없어도 빈 문자열이며 최대 60 chars, handoff는 비어 있지 않은 문자열 최대 70 chars다. 추가 필드는 거부하지 않는다. **형태 일부만 검사하며 근거 인용·확신 calibration·출처 검증은 없다.** [E-P]
- Jev parser는 effort enum을 검사하고 model이 누락/미상이어도 current model/sonnet으로 대체한다. confidence 또는 선택지 확률이 number이고 current가 있을 때 `<0.5`면 `unsure, keeping`을 반환하여 Haiku로 넘긴다. 숫자의 finite/0..1 범위를 엄격하게 검사하지 않고 확률 합계도 확인하지 않는다. 확신이 없으면 why 빈 문자열로도 verdict가 된다. [E-J]
- module variables/reactive atom 및 store로 pick/config/cost 등을 유지한다. `session.start`는 저장된 설정/일부 pick을 복원한다. 이는 memory 후보별 immutable receipt, 승인·철회 상태, source hash, realm별 격리 모델이 아니다. 공식 `$.store`는 같은 머신의 여러 세션이 공유한다고 설명하므로 realm 격리를 자동 가정하면 안 된다. [E-S][O-R]

### 2.4 실패·재시도·취소·비용

| seam | 소스에서 확인한 동작 | 보장하지 않는 것 |
|---|---|---|
| askHaiku | `claude-haiku-5-5` 호출이 `isAnswered:false`이면 `haiku` alias 한 번 호출. 최종 응답의 parse 및 usage만 집계 | invalid JSON인데 `isAnswered:true`면 alias 재시도 없음. 첫 호출이 throw하면 alias로 넘어가지 않음. timeout은 요청 필드이며 내부 retry 횟수/정확한 취소는 runtime 구현 미관찰 |
| askJev | `$.http.fetch`와 3,000ms sleep을 Promise.race. non-2xx/parse 불가/throw/timeout이면 undefined → Haiku. 401/403,402,429 등을 사용자 경고로 구분 | Promise.race 자체는 진행 중 HTTP를 abort하지 않음. 소스에 request abort/`next.signal` 전달 없음. 즉 fallback이 병렬로 외부 호출·비용을 계속 남길 수 있음 **[INFERENCE]** |
| 전체 | Jev unsure면 Haiku의 정상 verdict 우선, Haiku 실패면 Jev의 기존 effort 유지. verdict가 없으면 새 pick을 적용하지 않음 | “오류 = 제외/낮은 중요도” 판정이 아님. 3+6+6은 요청 timeout 값의 단순 합일 뿐 end-to-end SLA가 아님 |
| 예외 | judge 주석은 “Never throws”라고 주장하지만 askHaiku 주변 catch가 없고 prompt hook에는 finally만 있음 | 공식 API는 조직 차단 model처럼 보낼 수 없는 요청은 reject한다고 명시. runtime의 hook failure skip은 세션 계속하기 정책이지 classifier 성공 보장이 아님 |

위 표의 직접 근거는 [E-J][E-X], API reject와 기본 hook 실패 시 next handler로 넘어가는 정책은 [O-A][O-E]다. 기존 mocked tests는 Jev timeout/HTTP 실패 → Haiku를 명시하지만 실제 로그인·네트워크·취소·품질의 실증은 아니다. [E-T]

비용 계수도 완전한 영수증이 아니다. askHaiku는 최종 answered 응답의 input/output만 더하고 cache creation/read 및 실패한 첫 요청 usage를 전부 합산하지 않는다. Haiku alias가 어떤 모델로 해석될지, plan usage가 어떤 비율로 소모될지는 installed runtime/provider에 달린다. README의 비용 절감·속도·정확도 숫자는 저자 marketing/bench 결과이지 본 조사 결과 또는 회사 memory 분류기의 성능 보장이 아니다. [E-J][E-R]

### 2.5 Privacy / 과대 권한

- effort judge가 전송하는 것은 **잘린 다음 prompt + 일부 이전 대화 + current 상태**다. “내 prompt만 보낸다”를 previous context도 전송하지 않는다는 뜻으로 해석하면 틀린다. [E-J]
- Haiku route는 세션 provider로, Jev route는 기본 TypeSafe로 보낸다. `JEV_URL` override를 허용하므로 secret header가 언제나 TypeSafe에만 전송된다는 README 문구를 코드상 불변식으로 취급하면 안 된다. 키 우선순위 및 명시 jev 선택 시 env 파일 참조 코드가 있지만 **그 파일의 실제 값은 읽지 않았다.** [E-J][E-R]
- proof log는 보통 off, `EFFORTLESS_LOG` 또는 dev-mods 경로에서 활성화. prompt 앞 50 chars, verdict/why/model/effort 등의 일부 원문을 기록하며 파일에는 최근 200 lines를 쓴다. 배열 자체는 계속 push한다. source evidence receipt도, 비밀정보 redaction logger도 아니다. [E-G][E-X]
- plugin 전체는 classifier보다 훨씬 넓다. load 및 6시간 timer에서 버전 확인을 하고 GitHub git fetch, 실패 시 HTTP 및 `claude plugin marketplace update`를 실행할 수 있다. compaction 기본값은 Haiku이며 최대 2,400,000 chars transcript를 별도 모델로 보내는 경로, handoff/파일/업데이트 기능이 있다. 따라서 “외부 통신은 judge뿐”으로 전체 mod 권한을 승인하면 안 된다. 조사가 이런 동작을 **실행한 것은 아니다**. [E-U][E-C][E-M]
- 공식 docs도 mod는 sandboxed가 아니며 파일·process·network·session·usage 접근을 갖는다고 명시한다. “공식 API라서 회사 허용”이라는 결론은 성립하지 않는다. [O-V]

## 3. Jevbridge: Claude API와 native upstream을 분리해서 읽기

### 3.1 MCP judge 실제 경로

```text
bin/jevbridge.mjs
  → spawn 현재 Node (--experimental-strip-types --no-warnings src/cli.ts …)
  → cli mcp → serveMcp → handleMcpRequest(tools/call)
  → callMcpTool('jev_decide')
      → parseQuestions / asState / backendOf
      → runEvaluate → envJev / envLlm → evaluate
          explicit heuristic → evaluateHeuristic
          explicit/auto jev → evaluateJev → POST /v1/systemone
          explicit/auto llm → evaluateLlm
              anthropic → chatAnthropic → POST /v1/messages
              기타 → chatOpenAICompat → POST /chat/completions
```

`resolveBackend(auto)`는 **키 유무 선택**이다: Jev key > LLM key > heuristic. **Jev 요청 실패 → Claude/native/heuristic 재시도라는 fallback은 없다.** explicit jev/llm에 key 없으면 throw한다. [J-B][J-M][J-E]

참고로 CLI `eval`은 `envLlm()`을 쓰지 않고 Jev config만 넘기므로, LLM key만 있어도 그 CLI 경로에서는 auto가 heuristic을 선택한다. MCP/ACP 경로와 같다고 가정하지 않는다. [J-B][J-K]

### 3.2 인증·환경·SDK

- `envJev`: `TYPESAFE_API_KEY`, `TYPESAFE_BASE_URL`, `JEVBRIDGE_JEV_MODEL`. 기본 URL `https://api.typesafe.ai/v1/systemone`, model `jev-latest`. `evaluateJev`는 Node fetch POST, Bearer API key, `{model,state,questions}`. TypeSafe SDK를 import하지 않는다. [J-K][J-Q][J-C]
- `envLlm`: provider는 `JEVBRIDGE_LLM` 없으면 **xai**. Claude를 의도하면 provider를 `anthropic`으로 명시해야 한다. key는 `JEVBRIDGE_API_KEY || XAI_API_KEY || OPENAI_API_KEY || ANTHROPIC_API_KEY || OPENCODE_API_KEY` 순서로 **provider와 독립적으로** 선택한다. model/base URL은 `JEVBRIDGE_LLM_MODEL`/`JEVBRIDGE_BASE_URL` override 가능. [J-K]
- **[INFERENCE, 소스에서 도출]** 회사 공용 process 환경에 다른 provider key가 같이 있으면 선택 provider와 key가 불일치할 수 있다. 예컨대 ANTHROPIC key만 두고 provider를 생략하면 기본 xai endpoint에 그 key를 보내는 경로다. 실제 key 유출을 시험한 것이 아니다.
- Claude는 `fetch`, `x-api-key`, `anthropic-version:2023-06-01`, `model`, `temperature:0`, `max_tokens:900`, 단일 user message로 구현. **Anthropic SDK도 native `claude` 실행도 subscription credential lookup도 없다.** env/provider catalog를 통한 정상 기본 URL은 `https://api.anthropic.com/v1/messages`. `chatAnthropic`를 직접 호출하는 설정에 baseUrl이 없으면 내부 default는 `https://api.anthropic.com/messages`가 되어 `/v1` 없는 URL을 조합한다. 실제 endpoint 성공/실패 검증은 하지 않았다. [J-A][J-K]
- package는 runtime npm dependency 선언 없이 Node `>=22`; wrapper/scripts는 experimental type-stripping flag를 사용한다. “zero dependency”는 외부 inference endpoint/키나 proxy upstream 프로그램이 불필요하다는 뜻이 아니다. Node 모든 22 minor 호환성이나 production SLA도 검증하지 않았다. [J-B]

### 3.3 native Claude/Codex ACP는 존재하되 judge auth와 다르다

`jevbridge acp --upstream claude`는 `npx -y @agentclientprotocol/claude-agent-acp`, codex는 `npx -y @agentclientprotocol/codex-acp` preset을 spawn한다. 임의 command/args 환경 설정도 지원하며 child에 `process.env`를 그대로 준다. 즉 **native 계열 upstream 연결 경로 자체는 실제 소스에 있다**. 다만 adapter package 버전은 이 preset에서 pin되지 않았다. 해당 외부 adapter 내부 인증을 이 대상 SHA의 구현으로 주장할 수 없다. [J-U]

`AcpProxy.onClient`는 authenticate를 포함한 일반 요청을 upstream으로 forward하고, prompt 및 updates를 저장한다. permission 요청/일부 pending tool update에서 `runIntercept → interceptToolCall → evaluate(auto)`를 호출하지만 그 judge는 여전히 `envJev/envLlm` 키를 사용한다. **upstream Claude 로그인 세션을 judge에 넘겨서 분류시키는 코드는 아니다.** ask 결과는 실제 permission option 선택/forward에 관여한다. upstream 메시지를 감시할 수 있다는 점과 upstream 자체 native inference를 judge 대체로 사용한다는 점을 구분해야 한다. [J-P]

upstream 없는 `AcpSidecar`의 authenticate는 `{}` 응답이며 native Claude 로그인 구현이 아니다. sidecar prompt도 `evaluate`로 가고, state는 현재 prompt/cwd 또는 computer observation이다. persist된 history 전체를 judge 입력으로 합치지 않는다. [J-S]

### 3.4 입력 schema와 출력 validation의 차이

MCP 입력은 enum/required를 광고하고 runtime `parseQuestions`로 타입, nonempty instructions, choice 최소 2, score rubric string 최소 2를 확인한다. 빈 questions도 거부한다. state는 string 또는 object를 받아 넘긴다. 그러나 일반 library `evaluate`는 TS type만 기대하고 이 parser를 직접 호출하지 않는다. 질문 수·state 길이·전체 토큰 budget 제한은 이 호출 경로에 없다. [J-M][J-Q][J-E]

LLM 경로 `systemOnePrompt`는 STATE와 QUESTIONS를 평문 문자열에 붙이며, JSON only / 모든 option 확률 합 1 등을 **prompt로 요청**한다. Anthropic 요청에 JSON Schema나 tool-based constrained output을 설정하지 않는다. OpenAI-compatible 경로는 `response_format:{type:'json_object'}`이며 schema-constrained output은 아니다. 둘 다 `extractJson`으로 fence 또는 첫 `{`/마지막 `}`를 찾아 JSON.parse한다. JSON 형식 실패는 throw한다. 원문 prompt injection 격리나 citation 검증의 구현은 이 seam에서 확인되지 않았다. [J-A]

**핵심 거부 근거: `coerceAnswers`는 strict validator가 아니라 값을 만들어 채우는 coercer다. Jev 결과에도 같은 coercer를 사용한다.** [J-C][J-A][J-N]

| 잘못되거나 누락된 출력 | 소스 동작 | bounded memory judge 위험 |
|---|---|---|
| 누락 noul, NaN | Number 변환 후 `clamp01`은 nonfinite를 **0**으로 변환 | 응답 누락을 `not useful`/`not destructive` 등 false와 혼동 가능 |
| choice 확률 전부 누락/0 | normalizeMap이 **균등 분포**, argmax는 첫 key | “무응답”이 schema상 유효한 특정 choice로 바뀜 |
| choice만 있음 | 그 option에 확률 1을 합성 | 실제 분포 미제공인데 confident 결과를 만들 수 있음 |
| 명시 confidence=0 | `Number(confidence) || peakedness(...)` 때문에 0을 대체 | 명시 낮은 confidence를 보존하지 않음 |
| score 값 | finite면 그대로 사용 | rubric index 범위 밖 score를 reject/clamp하지 않음 |
| response type/extra fields | request 질문의 type으로 결과를 재작성; 알 수 없는 필드/확률 key는 걸러짐 | 원 응답 불일치와 정보 손실이 에러로 남지 않음 |

위 표의 위험 시나리오는 코드에 대한 **[INFERENCE]**이며 런타임 실험이 아니다. 특히 `{answers:{}}`가 JSON parse를 통과하면 누락된 질문마다 결과를 만들어낼 수 있다. 회사 분류기에 이 coercion을 복사하지 않는다.

`gate`는 execute/confirm/escalate/abort로 action을 나누며 기본 thresholds 0.72/0.46/0.18, destructive 0.62를 사용한다. 그러나 choice `done/complete` shortcut은 destructive 검사보다 먼저 실행한다. confidence는 모델 자가보고 또는 entropy 기반 peakedness이지 calibration 검증 결과가 아니다. **gate abort는 해당 memory 후보가 가치 없다는 뜻이 아니며 confidence 부족과 실제 의미적 거부를 혼합해 저장해서는 안 된다.** [J-G]

### 3.5 오류·timeout·cancel·privacy

- Jev/LLM non-2xx는 status와 response body 앞 280 chars를 포함한 Error. JSON parse/fetch 오류도 propagate한다. MCP `callMcpTool`은 catch하여 `isError:true` text로 내보낸다. transport의 기타 예외는 JSON-RPC internal error로 매핑한다. **401 인증 실패는 exclude가 아니다.** [J-C][J-A][J-M]
- 읽은 inference 함수에는 자체 retry/backoff, timeout, AbortSignal이 없다. Node/서비스 기본 동작까지 “timeout이 없다”라고 단정하지 않지만 **제품이 설정한 bounded deadline/cancel 계약은 없다**. max_tokens:900은 응답 상한이지 입력 상한이나 네트워크 deadline이 아니다. [J-C][J-A]
- MCP stdio는 각 line을 await하여 순차 처리하고 id 없는 notification은 무시한다. 이 경로에서 notifications/cancel이 inflight fetch를 abort하지 않는다. sidecar cancel은 flag 및 마지막 stopReason에만 관여하고 fetch signal이 없다. sidecar read loop 자체도 dispatch를 await한다. proxy는 cancel notification을 upstream에 forward하지만 judge cancellation과 같은 일이 아니다. [J-M][J-S][J-U]
- proxy `handlePermission/runIntercept`는 inference 오류를 “ask human”으로 전환하는 catch를 두지 않는다. low-confidence의 ask 경로와 network/API 실패 경로는 구별된다. 장시간 API 실패가 안전한 승인 대기 상태로 보장된다고 읽지 않는다. [J-P]
- SECURITY 문서는 공급한 state가 TypeSafe 및/또는 설정 LLM provider로 나간다고 명시한다. MCP judge는 제공한 state/questions를 전달하며 redaction/realm authorization를 수행하지 않는다. openWorldHint:false 같은 MCP annotation은 outbound fetch를 막는 정책 enforcement가 아니다. [J-R][J-C][J-A][J-M]
- ACP는 기본 `~/.jevbridge/sessions` 또는 `JEVBRIDGE_SESSION_DIR`에 JSON으로 user prompt와 session updates를 저장한다. history는 append하며 전체 JSON을 writeFile한다. 관찰한 저장 구현에 암호화/redaction/자동 retention 상한은 없고, 목록 PAGE_SIZE=50은 history 길이 상한이 아니다. MCP judge 경로의 stdout 결과와 ACP disk history를 혼동하지 않는다. [J-S]
- HTTP 오류 body 일부가 MCP/ACP 오류에 포함되므로 downstream host 로그로 원문이 전파될 수 있다 **[INFERENCE]**. provider 저장/학습/retention 정책은 이 소스 조사만으로 확인하지 않았다.

## 4. Marketing, source contract, runtime contract 분리

| 주장 | 분류 | 이번 조사로 말할 수 있는 것 |
|---|---|---|
| effortless “own Claude login, no key” | README 주장 + 실제 mod call + 공식 runtime 문서 | session credentials 이용 seam은 확인. 실제 회사 계정에서 허용/품질/요금 검증은 없음 |
| effortless “약 1초”, Jev “4x faster”, 절감·정확도 수치 | 저자 benchmark/marketing | 회사 useful/exclude/review 판정에 일반화하지 않음. 본 조사 benchmark 없음 |
| effortless “Never throws”, “nothing except judge” | source comment / README 주장 | host reject 가능, previous context 전송, update 네트워크 경로로 제한/반례 존재 |
| effortless “cheaper model” | manifest에서 experimental/off 기본 | 실험성은 이 모델 라우팅 옵션에 명시됨. 모든 judge/runtime이 experimental이라는 주장도, 모든 runtime이 영구 stable이라는 주장도 하지 않음 |
| Jevbridge “Claude/Codex alongside”, “Native Jev” | README 용어 | Native Jev는 TypeSafe HTTP API. Claude/Codex proxy는 별도 upstream. subscription-native judge라는 뜻이 아님 |
| TypeSafe typed decisions | 프로토콜/제품 설명 | 고정 src는 typed questions를 보내나 로컬 응답은 coercion. 구조 보장이 의미 정확성·근거 provenance를 보장하지 않음 |
| confidence gate | 실제 runtime branching | 이 threshold가 회사 데이터에서 calibrated라는 근거 없음. heuristic fallback 존재를 성공한 ML 추론으로 위장하면 안 됨 |

## 5. 우리 bounded company classifier에 대한 구체적 재사용/거부안

아래는 **설계 권고**이며 변경·설치·도입 결정은 parent 소유다. 두 제품을 memory architecture의 완성품으로 취급하지 않는다.

### 재사용할 수 있는 최소 아이디어

1. **승인 Claude Code 내부 sidecar seam 후보:** effortless의 `askHaiku` 호출 방식만 참고한다. 공식 mods complete는 tools/history/project context 자동 첨부 없이 작은 분류 request를 만드는 좋은 seam이다. 조직이 mods를 허용하고 회사 승인 runtime의 실제 결과 타입/model allowlist가 확인된 경우에만 후보가 된다. `$`는 외부 MCP에서 사용할 수 없으므로 회사 local MCP와 native mod 간 별도 경계가 필요하다는 점은 **[INFERENCE]**다. 통합 설계/구현을 여기서 수행하지 않았다.
2. **개인 cloud Jev request seam:** Jevbridge `evaluateJev`의 `{model,state,questions}`와 explicit backend metadata를 참고할 수 있다. 회사 realm에는 TypeSafe key/endpoint로 routing하지 않는다. provider를 key 탐색으로 자동 결정하는 envLlm 패턴은 버린다.
3. **실패 ≠ semantic exclude:** effortless의 non-answer/fallback 구별, Jevbridge의 MCP `isError:true`를 원칙으로 삼되 자동 외부 provider fallback은 복사하지 않는다. judge_unavailable/auth_error/timeout/schema_error와 실제 useful/exclude/review는 별도 상태여야 한다.
4. **prompt와 runtime 검사 분리:** closed decision enum은 참고하되 parser는 strict하게 바꿔야 한다. source IDs, 원문 span/hash 및 인용이 실제 입력에 존재하는지 검증하는 runtime receipt가 없으므로 두 프로젝트의 why/confidence를 provenance로 쓰지 않는다.

### 그대로 채택하지 않을 것

- effortless 전체 plugin: effort/model routing, compaction/handoff, 업데이트/프로세스/파일 권한이 bounded classifier보다 넓다. 비용 sliders, follow-up shortcut, alias fallback 및 shared store를 memory 판정에 가져오지 않는다.
- Jevbridge Claude adapter를 native 계정 대안으로 채택: API key 의존이다. ACP upstream을 연결해도 judge의 API 인증 경로는 바뀌지 않는다.
- Jevbridge auto/heuristic fallback과 permissive coercion: 키 누락 또는 형식 실패가 그럴듯한 선택/false로 채워져 exclude로 잘못 흘러갈 수 있다. heuristic tokenize는 영문 정규식 기반이며 한국어 의미 분류 품질을 보장하지 않는다. [J-N]
- source에 임의 output token cap만 있는 상태를 전체 budget/deadline 보장으로 부르기; 자가 confidence를 calibrated confidence로 부르기; “mod install 승인”을 “각 영구 memory write 승인”으로 부르기.

### 적용 전 반드시 분리할 계약

- **회사 realm:** 승인 native runtime만 허용, 외부 Jev/API fallback 없음. 승인된 입력만 최소 길이로 보내고 잘린 사실을 receipt에 기록한다. credentials를 MCP가 복사·추출하지 않는다.
- **개인 cloud realm:** Jev/API는 별도 명시 정책으로 허용 가능하나 회사 source/evidence를 crossing시키지 않는다.
- **판정 payload:** useful/exclude/review와 transport error를 분리하고 malformed/missing/nonfinite/out-of-enum 출력을 성공으로 coercion하지 않는다. 원문 source/span/hash 및 judge model/backend/runtime/prompt-schema version을 함께 남기는 구조가 필요하다.
- **저장·승인:** 판정은 후보일 뿐 Profile/Log/Notes/files/skills 중 어디에 반영할지 및 승인/철회/삭제 권한은 deterministic 정책으로 분리한다. 두 대상의 judge/gate 구현에는 이 다섯 destination 구분 및 원문 근거 기반 영구 반영 계약이 제공되지 않는다. 확인한 함수 범위를 넘어 일반 memory 시스템 전체 부재까지 주장하는 것은 아니다.
- **취소·비용:** end-to-end bounded input/output/deadline, cancel 전파, 모델/realm 허용목록과 최종 usage accounting은 이 사례들에서 완성된 계약으로 받지 않는다. runtime 내부 retry와 billable failed calls는 미확인이다.

## 6. 미확인 사항 / parent handoff

확인된 것은 **고정 공개 코드의 실행 분기와 공식 live 문서의 session-credential 계약**이다. underlying Claude Code closed runtime의 wire auth 구현/재시도/실제 plan debit, 설치된 회사 runtime의 API shape, 외부 ACP adapters 내부 인증, provider privacy/retention, 회사 승인 및 서비스 이용약관 판단은 이번 자료만으로 확인되지 않는다. 특히 official mutable declaration과 docs/effortless result shape가 다르므로 build별 계약 확인 없이 코드 복사하면 안 된다.

Parent가 통합 결정 시 검토할 항목은 승인 runtime/API 계약, realm routing, strict validator 및 source receipt, 실패 상태 전파, 로그 redaction/retention, 승인·철회 정책이다. 이번 assignment는 검증 실행을 요구/허용하지 않으므로 어떤 check도 실행하지 않았다. test 소스에는 mocked judge 분기와 heuristic MCP/gate 계약이 있으며, live subscription·TypeSafe 분류 품질 또는 회사용 provenance acceptance를 증명하지 않는다.
