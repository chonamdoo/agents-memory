# 루트 없는 컨벤션: 논문 근거와 OSS 규칙 라우팅

조사 기준일: **2026-10-11**. 공개 논문 원문, 공식 호스트 문서, commit으로 고정한 공개 소스만 조사했다. 논문 실험·호스트·모델을 실행하지 않았으며 저장소/회사 자료 수집, 설정·인증 변경, GitHub 변경, 빌드·테스트·유료 모델 호출을 하지 않았다. **출시 문서의 지원, 특정 commit의 구현, 현재 설치된 호스트의 동작, 모델의 실제 준수는 네 가지 다른 증거 수준**이다.

범위는 별도 OSS `agent-memory-mcp`에서 **루트 `CLAUDE.md`/`AGENTS.md`에 팀 공통 컨벤션까지 누적하지 않으면서**, 개인 로컬·프로젝트 공유·팀 공통 범위를 유지하는 방법이다. Agent Flow나 다른 에이전트 설치를 필수로 만들지 않는다. 아래는 연구·설계 판단이며 구현 완료 보고가 아니다.

## 1. 결론

1. **불필요한 전체 로드와 중복 문서 생성을 줄일 근거는 있다. 그러나 ‘모든 정책을 검색으로 옮겨도 된다’ 또는 ‘동적 검색이 최소 상시 규칙보다 항상 낫다’는 근거는 없다.** Agent READMEs는 관찰 연구이고, Evaluating AGENTS.md는 특정 Python issue-resolution workload의 context-file 유무 비교다. 후자는 동적 규칙 검색과 최소 상시 규칙을 직접 비교하지 않았다. [P1][P2]
2. 가장 재사용하기 좋은 조합은 **짧은 발견 정보 + 권한/범위로 먼저 좁힌 목록 + 경로 기반 후보 결정 + 명시적 또는 설명 기반 skill 선택 + 선택된 원문 전달**이다. 원문 전체를 startup prompt에 넣는 것과, 발견 목록을 작게 유지하는 것은 별개 문제다. 호스트별 구현 차이는 adapter 경계로 남겨야 한다. [O1][O2][S1][H1][H2]
3. **검색에 실패한 규칙은 ‘없는 규칙’이 아니다.** 실제 contribution-policy 연구에서는 issue 해결 중 별도 정책 파일을 거의 열지 않았고, 금지·인간 이관 규칙은 발견 이후에도 잘 지켜지지 않았다. 따라서 보안·회사 반출 금지·승인 요구·공유 범위 확장은 semantic top-k나 모델의 자율 회상에만 맡길 수 없다. [P4]
4. 루트 파일을 비워도 **호스트 발견/선택 경로는 반드시 필요**하다. native skill이나 사용자가 명시적으로 선택하는 MCP 호출·prompt 등을 쓸 수 있지만, 연결된 MCP가 자동으로 매 작업 전에 호출되거나 모델에 도착한 규칙이 준수된다는 보장은 프로토콜에 없다. [H1][H2][S2]

## 2. 논문 증거 행렬

아래 수치는 모두 **저자가 해당 판본에서 보고한 값**이며 여기서 재현한 결과가 아니다. 데이터/언어/모델/harness가 다른 수치를 이 제품의 절감률·효과로 환산하지 않는다.

| 근거·읽은 판본 | 자료/실험과 무엇을 비교했는가 | 직접 뒷받침하는 것 | 뒷받침하지 않는 것·한계 |
| --- | --- | --- | --- |
| **Agent READMEs** — arXiv 2511.12884 **v2, 2026-08-09**, §3–4, §7 [P1] | AIDev 출처 후보에서 root 파일명으로 수집한 **2,303 파일 / 1,925 저장소**. 크기·Markdown 구조·수정 이력·instruction taxonomy 분석. 내용 분류는 영어 **332 파일** 표본, 변경 내용의 수동 분석은 post-adoption **100 commit**. | context 파일이 살아 있는 운영 설정처럼 유지되고, 추가가 삭제보다 많은 경향. 정책을 검토·갱신·폐기할 관리 필요. 표 3의 Testing **75.9%**, Security **14.8%**, Performance **14.5%**는 분류 표본의 주제 존재율이다. | **파일을 넣거나 빼고 작업 성공을 측정한 인과 실험이 아니다.** root 파일명·도구 3종·후보 저장소 필터는 nested/path rules·비공개 기업·다른 호스트를 대표하지 않는다. developer-committed가 순수 인간 작성임을 입증하지 않는다. topic presence는 품질·준수·보안 효과가 아니다. word/FRE는 모델 token/이해도 지표가 아니다. |
| **Evaluating AGENTS.md** — arXiv 2602.11988 **v3, 2026-09-29**, §3–5, Table 2–3, Appendix B [P2] | SWE-bench Lite **300 tasks / 11 Python repos**: None 대 agent `/init`류 LLM-generated. **CTXbench 138 instances / 12 repos**: None/LLM/Dev. Claude Code+Sonnet-4.5, Codex+GPT-5.2 및 GPT-5.1 mini, Qwen Code+Qwen3-30b-coder. instance별 한 번 sampling. 기존 파일을 제거/생성/유지하는 **작업 처리 조건 비교**. | LLM context가 성공률을 유의하게 높이지 않은 반면 평균 inference cost가 SWE-bench **20%**, CTXbench **23%** 증가했다는 §4.2 보고. None 대 LLM 성공률 비교 p=**0.87/0.37**, CTXbench None 대 Dev p=**0.21**; Dev 대 LLM p=**0.038**. 지시는 행동에 영향을 주어 테스트·탐색·특정 tooling 사용을 늘릴 수 있다. | ‘context는 무효’, ‘인간 규칙도 제거’, ‘동적 검색 승리’는 결론이 아니다. Python·특정 model/harness·test-based task success이며 보안·성능·필수 정책 준수는 주 결과가 아니다. Dev는 committed/편집된 파일이지 인간 작성 provenance의 완전 검증이 아니다. benchmark task 설명·추가 tests는 GPT-5.2/Codex 지원으로 작성 후 검토되었다. 모델별 cost와 효능은 다르다. |
| **RepoCoder** — arXiv 2303.12570 **v3, 2023-10-20**, Figure 2, §2–5 [P3] | Python repository-level line/API/function completion. in-file만 사용, 단회 RAG, 이전 생성 결과로 query를 갱신하는 iterative retrieval-generation 비교. CodeGen/GPT-3.5-Turbo 시대의 코드 snippet 검색. | 필요한 repo 정보가 다른 파일에 있고, 첫 query가 아직 구현하려는 API를 표현하지 못하면 검색을 놓칠 수 있다는 구체 사례. 생성 중 발견한 심볼·API로 **후속 retrieval을 갱신할 이유**. | coding convention 문서를 검색하는 실험도, Claude/Codex 정책 준수 실험도 아니다. ‘관련 코드를 더 잘 찾았다’가 ‘필수 규칙을 빠짐없이 찾았다’는 뜻은 아니다. 추가 retrieval/generation 비용과 오래된 모델·context 조건을 현재 제품 이득으로 옮기지 않는다. |
| **A First Look at Coding Agents’ Compliance with AI Contribution Rules in Open-Source Communities** — arXiv 2607.26819 **v1, 2026-07-29**, §3–4, Table 1, §5.4 [P4] | 실제 저장소 AI 정책의 Refuse/Disclose/Verify/Handoff. **106 issues / 49 repos**, OpenCode+DeepSeek-V4-Pro, Codex+GPT-5.3-Codex/GPT-5.5, Claude Code+Sonnet 4.6. Native, reminder, clause quote, 사후 oracle feedback. 코드 정답 대신 trace의 **정책 준수** 판정. | non-anchor Native **347 runs 중 12회(3.5%)**만 focal policy file을 열었다는 §4.1 결과. Table 1의 Native Refuse는 model별 **0/29 또는 0/30**, Native Handoff는 **0/9 또는 0/10**. 발견 문제와 준수 문제를 분리해야 한다는 강한 반례. | 특정 선택 표본·단순 issue·작은 Handoff N·LLM judge·공개 정책·harness 버전에 제한. external-MCP retriever를 시험하지 않아 이 제품의 retrieval miss rate가 아니다. ‘그 어떤 routing도 소용없다’는 보편 결론은 아니다. source abstract의 ‘모든 조건에서 never refuse’와 Table 1의 일부 Quote/Feedback nonzero 값은 불일치하므로 **Native 수치와 본문/Table 1만 제한적으로 인용**한다. |

### 2.1 판본 혼합 금지

`Evaluating AGENTS.md`의 **v1(2026-02-12)**은 새 benchmark를 **AGENTbench**라 부르고, v3는 **CTXbench**라 부른다. v1 introduction의 간략 개선/하락 설명과 v3의 통계 검정·수정 표현을 섞지 않는다. v1 abstract의 강한 ‘tend to reduce’ 문구만으로 v3의 **유의하지 않은 None–Dev/LLM 차이**를 유의한 하락처럼 보고하지 않는다. [P2][P2a]

또한 v3 abstract의 ‘over 20%’를 모든 developer-written setting의 비용 증가 하한으로 쓰지 않는다. Table 2는 agent별 비용을 제시한다. 예를 들어 CTXbench/Codex+GPT-5.2의 None **$0.38**, LLM **$0.57**, Dev **$0.54**는 그 실험의 inference 비용이며 이 제품의 가격·token 예상값이 아니다. §4.2 Dev 비용 요약의 ‘at most 19%’도 이 개별 cell의 상한으로 사용하지 않는다. **비용에는 입력 길이뿐 아니라 행동·추론·tool 경유 추가 호출이 포함**된다. [P2, Table 2; §4.3]

### 2.2 이득이 나타나는 조건과 최강 반론

- **다른 문서에 없는 정보를 제공할 때**: P2 Appendix B는 context를 생성한 뒤 `.md`·example code·`docs/` 내용을 제거하는 ablation에서, Claude Code를 비용 때문에 제외하고 LLM context의 평균 **2.7% 개선**을 보고한다. 기존 문서의 중복이 원인일 수 있다는 근거이나, 정상 repo 문서를 지우라는 처방은 아니다. [P2, Appendix B]
- **비표준 tooling/제약을 명시할 때**: P2 trace에서 이름이 언급된 tooling 사용이 증가한다. 필수 규칙은 benchmark 기능 tests에 직접 반영되지 않아도 목적이 있을 수 있다. 따라서 늘어난 검증 비용이 전부 낭비라는 결론은 틀리다. [P2, §4.3, §5]
- **최소 all-loaded baseline을 이길지는 별도 문제**: 작은 규칙 집합은 discovery 실패·query 갱신·추가 tool 왕복이 없다는 이점이 있다. 반대로 커지고 중복되면 유지/입력 비용이 늘어난다. P2는 all-loaded 문서 대 None을 비교했지, 동일 규칙 집합의 최소 all-loaded 대 path-routing 대 semantic retrieval을 비교하지 않았다. 이 우열은 **[INFERENCE] 아직 본 프로젝트에서 검증되지 않았다**.
- **길이 하나로 설명하지 않기**: P2 Appendix B의 길이별 분석은 성공률/비용의 뚜렷한 길이 의존성을 찾지 못했다고 보고한다. instruction 행동 변화와 relevance를 함께 봐야 한다. ‘짧게 만들면 자동으로 성공’도 과장이다. [P2]

## 3. 실제 OSS에서 빌릴 수 있는 라우팅 패턴

**선정은 mechanism 다양성과 1차 소스 검토에 따른 사례 조사다. GitHub 전체 조사·최고 프로젝트 선정·stars 비교가 아니다.** 파일 호환은 같은 런타임 semantics나 보안 경계를 뜻하지 않는다.

| 사례·고정 source | 실제 host와 적용 방식 | startup/선택 비용 | Claude/Codex에 그대로 작동하는가 | 독립 메모리에서 재사용할 패턴 |
| --- | --- | --- | --- | --- |
| **Continue**, `5522c6f44ca0ac3528b37244818fbfa39b5af470`, `core/llm/rules/getSystemMessageWithRules.ts`; 실제 `.continue/rules/documentation-standards.md` [O1][O1a] | Continue 문서는 Agent/Chat/Edit request의 system message rules를 설명하며 **autocomplete/apply는 제외**. 코드의 `getApplicableRules`→`shouldApplyRule`→`getSystemMessageWithRules`는 message code block/file context의 path·content를 이용해 선택하고 선택된 rule body를 이어 붙인다. `globs`, `regex`, `alwaysApply`가 조건 입력이다. [D1] | `alwaysApply:true`는 무조건, `.continue/` rule에 globs/regex가 없고 false가 아니면 implicit global. 조건부 rule은 파일 evidence가 없으면 적용되지 않는다. **파일을 숨은 경로에 옮겼다는 것만으로 lazy가 되지 않는다.** | `.continue/rules` semantics는 **Continue host 전용**. Claude/Codex가 이 frontmatter·폴더를 native 조건부 rule로 읽는 근거가 없다. docs의 description-based pulling 설명은 존재하지만 이 pinned 필터 함수 자체에는 LLM semantic 선택이 없다. 다른 callpath까지 확인하지 않았으므로 전체 agent retrieval 구현을 단정하지 않는다. | 허용된 scope 내 **deterministic path/content match**와 명시적 off를 먼저 판단, 선택된 원문+출처만 전달. 호스트 코드가 받은 file context와 실제 changed-file 집합을 혼동하지 않는다. |
| **OpenCode 역사적 source snapshot**, `fc7e4cf93e660ad5ddabb0c48ecc99e934ebfe95`, `packages/opencode/src/session/instruction.ts`, `tool/read.ts`, `session/system.ts` [O2][O2a][O2b] | `system()`은 global/project instructions와 `config.instructions`에 매칭된 파일·URL을 읽어 합친다. `resolve()`는 **읽는 대상 파일의 상위 디렉터리**에서 인접 instruction을 찾아 중복 전달을 피한다. `read.ts` L300, L355–356은 이를 호출해 read 결과의 system-reminder에 붙인다. | config의 `instructions:["rules/*.md"]`는 **작업 파일 selector가 아니라 instruction 파일을 열거해 함께 로드하는 glob**이다. nested read-triggered load는 root 전체 로드와 다르나 읽은 뒤 context/history에 남는 비용까지 0이 아니다. | 공식 **v1 docs**는 AGENTS.md 우선·CLAUDE.md fallback, `.claude/skills`/`.agents/skills` 지원을 명시한다. 그러나 이는 **OpenCode가 Claude형 파일을 읽는 것**이지 Claude/Codex가 OpenCode config/hook을 지원하는 것이 아니다. 최신 dev에서 `packages/opencode`가 제거되어 이 표는 **v1/과거 구현 근거**로 한정; v2 또는 설치본 지원 보증이 아니다. [D2][D3][O2c] | **현재 파일 접근 시 인접 범위의 원문을 전달**, content provenance와 loaded ID 기록, 중복 전달 방지. root-free 목표를 위해 새 root AGENTS의 ‘참조를 읽어라’ 안내를 필수로 만들지는 않는다. |
| **공식 openai/skills 예시**, `33a75a7b572867072dc0674bee8e63e06c19e67b`, `skills/.curated/gh-fix-ci/SKILL.md` [O3] | name/description으로 **GitHub Actions failing PR checks** 상황과 external provider 제외를 좁히고 body에서 작업 절차·bundled resource를 제공하는 실제 skill. Codex 문서는 explicit `$skill`/`/skills`와 implicit description matching을 지원한다. [H1] | skill body는 선택 후, metadata 발견 목록은 선택 전에 필요. 예시 body가 제안하는 `gh`/script 실행은 이 조사에서 하지 않았다. | 기본 SKILL.md 형식은 Agent Skills 표준을 써 Claude Code에도 형식 수준으로 재사용 가능. 폴더 위치·command 표기·부가 policy는 호스트마다 다름. 예시가 특정 gh workflow용이라는 점과 필요한 실행 권한도 남는다. [S1][H2] | 큰 root 문서 대신 **작업별 좁은 설명 + 필요 시 원문/참조**. 새 에이전트 설치가 아니라 현재 Claude/Codex의 native skill surface 활용 가능. 이 특정 skill을 컨벤션 시스템으로 설치하라는 권고가 아니다. |

### 3.1 코드가 드러내는 중요한 세부 차이

**Continue** [O1]:

- `globs`의 positive/negative 패턴과 content regex를 적용한다. 둘 다 주어진 경우 glob 매칭 파일에 regex를 검사하므로 단순한 `glob OR regex` universal 규칙으로 옮기면 다르다.
- regex가 있는데 content를 받지 못하면 해당 후보를 적용하지 않는다. file path만 아는 계획 단계에는 content rule이 누락될 수 있다.
- `rulePolicies[rule.name] === "off"`가 global 판정보다 먼저다. 이는 UI/호스트의 적용 상태이지 회사의 mandatory policy enforcement 계약이 아니다.
- non-root directory 판정의 `isFileInDirectory`는 마지막 directory name의 문자열 포함을 사용한다. **권한 격리·canonical workspace containment 로직으로 복사하면 안 된다.** 같은 이름의 다른 폴더를 구별하는 보안 경계는 별도로 필요하다.
- `appliedRules` metadata를 반환하는 패턴은 왜 적용됐는지 보여주는 데 유용하다. 그러나 delivery metadata는 모델의 읽기/준수 완료 증명이 아니다.

**OpenCode** [O2][O2a]:

- read-triggered nested injection은 **`read` tool callpath**에서 확인했다. bash로 파일을 읽거나 읽지 않고 새 파일을 작성할 때까지 같은 attachment가 보장된다고 확대하지 않는다.
- 이전 completed read의 `loaded` metadata와 message별 claim으로 중복을 피한다. compacted read는 별도 취급한다. 단순 ‘한 번 읽었으니 영원히 안 줘도 됨’으로 변환하지 않는다.
- `config.instructions` URL을 fetch해서 전부 합치는 방식은 root-file-free일 수 있어도 **all-loaded-free가 아니다**. 원격 팀 규칙의 승인·무결성·회수·회사망 제한을 자동으로 제공하지도 않는다.
- 경계 순회의 문자열 `startsWith(root)` 구현 역시 권한 validator로 재사용하지 않는다. 제안의 재사용 대상은 **event-to-scope routing과 loaded provenance**, 특정 문자열 검사 자체가 아니다.

Cursor/Roo 전용 규칙 형식은 본 조사에서 추가로 채택하지 않았다. 기존 Claude/Codex 사용자의 설치 부담을 없애는 목표에서는 **전용 host를 추가 요구하는 선택지는 필요조건이 아니기 때문**이다. 여기서 빠졌다고 ‘지원하지 않는다’ 또는 ‘그 밖의 OSS는 없다’고 주장하지 않는다.

## 4. portable skill과 순수 MCP의 정확한 경계

### 4.1 skill은 본문 지연 로드이지 zero-startup-context가 아니다

Agent Skills 표준은 name/description → SKILL.md body → 필요한 resource의 progressive disclosure를 설명한다. 하지만 표준의 `metadata`는 arbitrary string map이며 **`pathGlobs`, `taskTerms`, `alwaysApply` 등 공통 강제 routing semantics를 정의하지 않는다**. Continue, Agent Flow, native Claude/Codex의 selector를 한 schema로 취급하지 않는다. [S1]

공식 Codex 문서 [H1]는 `.agents/skills`의 CWD→repo-root 탐색, 사용자 `~/.agents/skills`, explicit/implicit invocation을 설명한다. 현재 문서는 초기 목록 budget 때문에 description을 줄이거나 skill 일부를 생략할 수 있다고도 명시한다. Claude Code [H2]는 `.claude/skills`, personal/project/nested locations와 explicit `/name`/implicit invocation을 설명하며, 많은 skill의 listing에서 description이 떨어질 수 있다고 명시한다. **검색할 metadata 자체가 잘리면 retrieval miss가 더 먼저 발생할 수 있다.**

두 문서는 서로 다른 시점의 살아 있는 제품 문서다. 조사자가 현재 설치본의 version·옵션·계정·정책을 실행 확인한 것은 아니다. 호스트 조사 노트의 검증 범위와 함께 해석해야 하며, 이 문서만으로 사용자의 Claude/Codex가 최신 listing/동적 발견 기능을 가진다고 결론 내리지 않는다.

**[INFERENCE] 재사용 권고**: 컨벤션 하나마다 전역 skill을 늘리는 대신, 선택한 scope의 작은 capability 목록과 좁은 retrieval entry skill을 두고 원문 rule을 필요할 때 가져오는 방식이 metadata 누적을 줄일 후보다. 다만 하나의 generic skill은 task matching이 약해질 수 있으므로 explicit invocation 경로와 누락 시 동작을 유지해야 한다. 이는 효과 실측이 아니라 가능한 설계 대안이다.

### 4.2 MCP만으로 가능한 것과 불가능한 것

MCP tool은 model-controlled 호출을 위한 인터페이스이지만 프로토콜은 특정 UI/interaction pattern을 강제하지 않는다. `tools/list`에 보이는 설명은 host 발견 정보이고 `tools/call` 결과는 전달 증거다. **매 코드 수정 전 자동 호출**, **repo path 자동 전달**, **회사 정책으로서의 우선순위**, **모델 준수**, **다른 filesystem/shell tool 차단**은 별도의 host/runtime 계약 없이는 MCP 메모리 서버가 보장할 수 없다. [S2]

따라서 독립 사용자는 다음 중 지원되는 경로를 선택할 수 있다.

- 기존 Claude/Codex에서 **native skill을 명시적으로 호출**하여 승인된 scope의 컨벤션을 회상.
- host가 제공하는 MCP tool/prompt 선택 UI나 사용자 task 요청으로 **이번 작업에 적용할 범위를 명시**.
- 호스트에서 실제 지원·승인된 경우에만 file/tool event adapter로 **경로 관련 규칙을 deterministic하게 전달**.

어느 경우도 Agent Flow 설치를 필수로 요구하지 않는다. 반대로 ‘MCP 연결만 했으니 일반 작업에서도 항상 필요한 규칙을 먼저 가져온다’는 광고는 하지 않는다. short entry skill/tool description도 startup/token 비용을 만들 수 있고, 연결 안 된/비활성 tool에는 discovery가 없다.

## 5. 가장 강한 retrieval-miss 반례와 enforcement 경계

### 5.1 경험적 반례: 작업과 직접 비슷하지 않은 contribution policy

단순 bug 수정 query는 `CONTRIBUTING.md`, PR template, 별도 AI policy의 **기여 금지·실행 검증·인간 이관**을 자연스럽게 검색하지 않을 수 있다. P4는 auto-loaded 파일의 anchor 조건과 별도 파일의 non-anchor 조건을 구분하고, Native trace에서 **12/347**만 focal policy file을 열었음을 보고했다. 이는 ‘파일을 저장해 두고 agent가 필요하면 알아서 찾는다’ 가정에 대한 이 조사 중 가장 직접적인 반례다. [P4, §3.4, §4.1]

하지만 두 번째 실패가 더 중요하다. Table 1의 Native Refuse/Handoff 실패는 **검색 성공률만 높이면 모든 정책 준수가 해결된다는 주장**을 반박한다. 해당 논문에서 quote/feedback도 restraint를 안정적으로 회복시키지 않았다. 작은 표본과 일부 nonzero cell을 무시하고 ‘항상 0’으로 일반화하면 안 되지만, **전달과 강제 실행을 분리해야 할 이유**는 충분하다. [P4]

### 5.2 원리적 반례: 아직 쓰이지 않은 경로와 사건 발생 전 정책

**[INFERENCE]** 사용자가 ‘로그인 오류 수정’을 요청하고 query에서 보안/개인정보를 언급하지 않았다고 하자. 회사 규칙은 ‘원문 고객 로그를 외부 inference/provider로 보내지 말라’, subsystem 규칙은 ‘새 auth handler는 기존 audit wrapper를 거쳐야 한다’다. 다음은 top-k만으로 해결할 수 없다.

1. 전역·역할별 회사 정책은 수정 경로나 query에 lexical/semantic overlap이 없어도 적용된다.
2. 아직 작성하지 않은 새 handler는 이전 changed-file context에 없을 수 있다.
3. 외부 전송 **후** 규칙을 회상하는 것은 이미 일어난 반출을 되돌리지 못한다.
4. 기존 규칙을 못 가져온 결과가 빈 배열이면 ‘자유롭게 해도 된다’고 오인하기 쉽다.

RepoCoder Figure 2의 query-gap은 2번과 닮은 코드 검색 사례지만, 회사 정책·권한 증명으로 사용하는 논문은 아니다. **필수 범위 정책을 먼저 확정하고, 예정 path가 바뀌면 관련 규칙을 다시 결정하며, 누락/접근불가를 허가로 취급하지 않는 설계**가 필요한 이유다. [P3; 설계 적용은 INFERENCE]

### 5.3 세 경계

| 경계 | 메모리/라우팅이 할 수 있는 일 | 별도 권한·실행 제어가 필요한 일 |
| --- | --- | --- |
| **회상 접근** | 서버에서 승인된 identity·tenant·scope 내의 evidence만 반환, 적용 ID/버전/출처 전달 | 모델이 임의 입력한 repo path나 scope label을 실제 workspace 권한 증거로 신뢰하면 안 됨. 회사와 개인 storage/backup/provider 경계가 필요. |
| **규칙 승격·배포** | 기억 근거와 승인된 rule 원문을 구분, draft와 active rule을 구별하여 반환 | 개인 관찰을 팀 공통 규칙으로 자동 승격, scope 선택을 publish approval로 대체, 회사 정책보다 개인 rule을 우선시키는 행동은 별도 승인 문제. |
| **작업 실행** | 관련 규칙을 모델에 전달하고 무엇을 전달했는지 기록 | 임의 shell·network·파일쓰기·업로드까지 메모리 MCP 하나가 통제하지 못함. 허용 tool·sandbox·egress·외부 승인/CI·인간 review가 실제 실행 경계. 읽기 로그·self-report는 준수 증명 아님. |

표는 **[INFERENCE] 본 요구에 대한 경계 제안**이며 보안 구현을 확인한 결과가 아니다. 팀 공통 컨벤션을 root 파일에서 빼는 요구는 존중하되, **mandatory company policy를 semantic 검색의 optional 결과로 낮추지 않는다**. 현재 host/runtime에서 필수 정책 적용을 보증하는 경로가 없다면 그 capability 한계를 공개해야 한다.

## 6. 도입 판단: 재사용할 것과 하지 않을 것

**재사용 가능**:

- root 파일이 아니라 **선택된 scope의 원문 저장소/skill/resource**를 canonical source로 삼는 방식.
- Continue의 path/content prefilter, OpenCode의 file-read-triggered local instruction delivery, native skills의 metadata/body 분리, loaded/applied-rule provenance. 제품별 구현을 그대로 복제하는 것이 아니라 책임 분리 패턴을 재사용한다.
- **local PC+project / project-shared / team-common**의 적용 범위 선택과, 공유·승격 승인 권한의 분리. 내용 수정은 기존 scope를 유지하고 범위 확대만 새 승인 대상으로 취급하는 요구와 양립한다.
- semantic retrieval은 알려진 scope/경로 매칭 **후의 발견 보조**로 사용하고, deterministic하게 적용되는 필수 정책을 top-k의 우연에 맡기지 않는 방식.
- 기존 Claude/Codex native skill 또는 MCP 사용자 선택 경로를 사용하여 **새 agent/Agent Flow를 강제하지 않는 독립 배포**.

**채택 근거가 없는 주장**:

- 자동 `/init`로 root 컨벤션을 늘리면 항상 생산성이 좋아진다.
- 모든 공통 규칙을 벡터 검색으로 옮기면 token/cost·준수·성공률이 모두 좋아진다.
- `SKILL.md`를 설치했으니 항상 올바른 규칙이 자동 활성화된다.
- OpenCode의 `instructions` glob이나 Continue의 `alwaysApply`를 Claude/Codex native 표준으로 쓸 수 있다.
- MCP 전달 로그 또는 모델의 ‘읽었다’ 응답이 필수 정책 enforcement다.

PR #341의 원래 tracked AGENTS/skill promotion 제안에 대한 correctness 검토와 이 문서의 root-free 요구는 구분한다. **루트 AGENTS promotion은 새 요구와의 채택 부적합일 수 있으나, 그 자체로 원래 PR spec의 버그라고 판정하지 않는다.** 논문은 PR의 byte 증가를 token 품질 변화로 환산하는 근거도 아니다.

### 확인이 필요하지만 이번 조사에서 실행하지 않은 비교

향후 검증을 수행한다면 **동일 규칙·동일 host/model/task**에서 최소 all-loaded, path-routed, explicit skill/MCP, semantic retrieval을 비교해야 한다. 기능 성공 외에 **필수 규칙 recall/전달/행동 준수**, 발견 누락·새 파일·scope 전환·권한 거부·규칙 갱신, startup 목록+본문+추론+검색 왕복의 전체 비용을 분리해야 한다. 이는 검증 설계 기준이지 이번 작업에 추가 구현·실험을 요구하는 계획이 아니다.

## 7. 1차 출처

### 논문

- **[P1]** Agent READMEs, arXiv2511.12884v2: <https://arxiv.org/html/2511.12884v2> — §3, §4.2, §4.3/Table 3, §7. Root collection과 내용 분류 표본을 구분. replication package는 논문이 링크한 <https://github.com/woraamy/Agent-Context-File-Analysis>; 실행하지 않음.
- **[P2]** Evaluating AGENTS.md, arXiv2602.11988v3: <https://arxiv.org/html/2602.11988v3> — §3–5, Table 2–3, Appendix A/B/C. 최신 판본의 통계·제약을 기준으로 인용.
- **[P2a]** 같은 논문 v1: <https://arxiv.org/html/2602.11988v1> — 판본 이름·강한 abstract와 최신 표현을 구분하기 위한 비교; 수치 혼합하지 않음.
- **[P3]** RepoCoder, arXiv2303.12570v3: <https://arxiv.org/html/2303.12570v3> — Figure 2와 §2의 incomplete-query retrieval gap. 새 호스트 성능 수치를 주장하지 않음.
- **[P4]** RepoComplianceBench 논문, arXiv2607.26819v1: <https://arxiv.org/html/2607.26819v1> — §3.4/§3.6, Table 1, §4.1/§4.2, §5.4. abstract·본문·table 불일치에 유의; Native 및 직접 판정 정의만 제한적으로 수치 인용.

### 고정 OSS 소스

- **[O1]** Continue selector 및 system-message construction: <https://github.com/continuedev/continue/blob/5522c6f44ca0ac3528b37244818fbfa39b5af470/core/llm/rules/getSystemMessageWithRules.ts> — `matchesGlobs`, `isGlobalRule`, `checkGlobsAndRegex`, `shouldApplyRule`, `getApplicableRules`, `getSystemMessageWithRules`.
- **[O1a]** Continue 실제 scoped rule: <https://github.com/continuedev/continue/blob/5522c6f44ca0ac3528b37244818fbfa39b5af470/.continue/rules/documentation-standards.md> — frontmatter의 globs/description/alwaysApply:false. 단순 예시 문서가 아니라 저장소의 실제 파일.
- **[O2]** OpenCode 과거 instruction source: <https://github.com/anomalyco/opencode/blob/fc7e4cf93e660ad5ddabb0c48ecc99e934ebfe95/packages/opencode/src/session/instruction.ts> — `systemPaths`, `system`, `find`, `resolve`, `extract`.
- **[O2a]** 같은 commit read callpath: <https://github.com/anomalyco/opencode/blob/fc7e4cf93e660ad5ddabb0c48ecc99e934ebfe95/packages/opencode/src/tool/read.ts#L300> ; <https://github.com/anomalyco/opencode/blob/fc7e4cf93e660ad5ddabb0c48ecc99e934ebfe95/packages/opencode/src/tool/read.ts#L355-L365>.
- **[O2b]** 같은 commit skill guidance 및 MCP instructions system composition: <https://github.com/anomalyco/opencode/blob/fc7e4cf93e660ad5ddabb0c48ecc99e934ebfe95/packages/opencode/src/session/system.ts>.
- **[O2c]** 역사적 pin 선택 이유: `packages/opencode` 제거 commit <https://github.com/anomalyco/opencode/commit/44b6938b2ad2895bdd89d5d5cf753fb01ca8e3dd> (2026-07-21), 그 parent가 `fc7e4cf...`. 조사 당시 dev `d21b0790a6c146815f28fea604e41e922f009590`에서 옛 경로는 404였다. <https://api.github.com/repos/anomalyco/opencode/commits?path=packages/opencode/src/session/system.ts&per_page=1>로 파일 이력을 확인했다. **현재 v2 전체 구현 검토를 했다는 뜻이 아니다.**
- **[O3]** 공식 openai/skills, task-specific description/body/resources 예시: <https://github.com/openai/skills/blob/33a75a7b572867072dc0674bee8e63e06c19e67b/skills/.curated/gh-fix-ci/SKILL.md>.

### 공식 host·표준 문서

문서 URL은 살아 있는 문서이며 위 OSS commit과 같은 시점으로 고정된 것은 아니다.

- **[D1]** Continue Rules: <https://docs.continue.dev/customize/deep-dives/rules> — Agent/Chat/Edit와 autocomplete/apply 적용 차이, selector/default, description과 alwaysApply 안내.
- **[D2]** OpenCode **v1** Rules: <https://opencode.ai/docs/rules/> — AGENTS/CLAUDE fallback, config instructions와 startup composition, 수동 root 참조 안내. 페이지에 v2 안내가 별도로 있어 v1 근거로 표시.
- **[D3]** OpenCode **v1** Agent Skills: <https://opencode.ai/docs/skills/> — .opencode/.claude/.agents discovery와 skill tool·permission. 새 metadata 동작을 역사적 commit으로 소급하지 않음.
- **[H1]** Codex 공식 skills URL <https://developers.openai.com/codex/skills> → 조사 당시 공식 통합 문서 <https://learn.chatgpt.com/docs/build-skills> — progressive disclosure, initial listing budget, explicit/implicit invocation, local locations.
- **[H2]** Claude Code skills: <https://code.claude.com/docs/en/skills> — 프로젝트/개인/nested 발견, explicit/implicit invocation, description listing budget와 누락, subagent preload 차이. 현재 설치본 검증 아님.
- **[S1]** Agent Skills specification: <https://agentskills.io/specification> — name/description/body/resources, progressive disclosure, arbitrary metadata, experimental allowed-tools의 host 차이.
- **[S2]** MCP 2025-11-25 Tools: <https://modelcontextprotocol.io/specification/2025-11-25/server/tools> — model-controlled discovery/invocation, interaction model 비강제, human denial 권고, trusted-server annotation 경계.
