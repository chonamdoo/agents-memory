# 루트 지침 파일 없는 Claude Code 컨벤션: 조건부 rules, skills, hooks, MCP

조사 기준일: **2026-10-11**. 이 문서는 공개된 Anthropic 공식 문서와 고정한 first-party 예제 소스를 조사한 설계 메모다. 설치된 Claude Code 버전·계정 플래그·IDE 실행 경로·모델 준수율을 확인한 실험 보고서가 아니다. skill/hook/MCP 설정을 설치하거나 수정하지 않았고, 빌드·테스트·유료 모델 호출도 하지 않았다.

## 1. 결론: root-free는 가능하지만 zero-context/완전 강제와 다르다

**권장 최소 조합**은 다음과 같다.

1. 프로젝트의 짧은 파일별 컨벤션은 `.claude/rules/*.md`의 **명시적인 `paths`**로 배치한다. 루트 `CLAUDE.md`/`AGENTS.md`, `.claude/CLAUDE.md`, root import bridge를 전제로 하지 않는다.
2. 긴 설명·예외·작업 절차는 소수의 native skill과 그 `references/`에 둔다. 반드시 실행해야 하는 절차는 자동 선택에만 의존하지 않고 `/skill-name`으로 명시한다.
3. 승인된 동작 경계는 회사의 managed settings, permissions, sandbox, 서버 ACL로 집행한다. 필요할 때만 **작고 동기적인 `PreToolUse` command hook**을 추가한다. 긴 컨벤션 전체를 매 이벤트에 주입하지 않는다.
4. 과거 결정·선호·증거는 독립 메모리 서비스의 좁은 MCP recall로 읽는다. 메모리는 승인된 컨벤션의 원본이나 회사 정책을 자동 덮어쓰지 않는다.

공식 문서도 rules를 별도로 발견하며 root 파일의 import가 필요하다고 규정하지 않는다. 예제 트리에 `CLAUDE.md`가 보인다는 사실은 필수 의존성의 증거가 아니다. 다만 root 파일 제거는 **전체 startup context 제거가 아니다**. 사용자/managed 지침, auto memory index, skill 목록, MCP 도구명·서버 instructions, 시스템/환경 정보는 별도로 남는다. [S1][S2][S3][S8]

**중요한 구분:** 조직이 “의무”라고 정한 컨벤션도 Markdown으로 전달하면 모델이 읽는 지침이다. `MUST`라는 단어, native skill 배포, MCP 검색 결과, managed `CLAUDE.md`의 비제외성은 그 자체로 실행 차단을 뜻하지 않는다. 결정론적 검사로 표현 가능한 제한과 서버/OS 권한을 별도로 둔다. [S1][S5][S6]

## 2. `.claude/rules/`: 무엇이 언제 로드되는가

### 2.1 실제 지원과 발견 범위

| 구조/조건 | 공식 문서에 명시된 동작 | 설계상 함의 |
| --- | --- | --- |
| 프로젝트 `.claude/rules/` | `.md` 파일을 재귀 발견 | `rules/frontend/react.md`의 `frontend` 폴더명은 분류일 뿐, 그 자체가 frontend 파일 조건이 아니다. |
| `paths` 없는 rule | 세션 시작에 무조건 로드, `.claude/CLAUDE.md`와 같은 우선순위 | 한 거대 파일을 여러 unscoped 파일로 나눠도 eager loading 문제는 해결하지 못한다. |
| `paths` 있는 rule | 일치 파일에 **Read, Write, Edit**를 사용할 때 로드 | “편집할 때만”도, “읽을 때만”도 아니다. |
| Bash를 통한 파일 보기 | edit read-before-edit로 인정되는 단일 파일 읽기도 해당 rule을 로드 | 모든 Bash 명령/검색/파일 쓰기가 조건부 rule을 활성화한다는 뜻은 아니다. |
| 하위 디렉터리의 `.claude/rules/` | on-demand nested rules의 존재를 문서가 명시 | 중앙 `rules/`의 재귀 분류와 `packages/x/.claude/rules/`의 지연 발견은 구분한다. 정확한 내부 탐색 순서/모든 도구별 발견 경로는 공개된 loader 소스로 확인하지 못했다. |
| 프로젝트 setting source 제외 | `--setting-sources`에서 `project`를 빼면 project rules 제외 | v2.1.211 이전에는 lazy/path-scoped/nested rules가 제외 후에도 로드되던 차이가 있다. |
| 추가 디렉터리 | `--add-dir`의 파일 접근 권한과 memory/rules 로드는 별개 | 추가 디렉터리 memory/rules에는 `CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD=1`이 필요하다. 추가 디렉터리 skills와는 조건이 다르다. |

근거: [S1: Organize rules / Path-specific rules / Load from additional directories](https://code.claude.com/docs/en/memory#organize-rules-with-claude/rules/), [S2: rules directory](https://code.claude.com/docs/en/claude-directory), [S4: Edit tool behavior](https://code.claude.com/docs/en/tools-reference#edit-tool-behavior), [S9: additional directories](https://code.claude.com/docs/en/large-codebases#grant-access-across-packages-or-repositories).

Bash에서 read-before-edit로 인정하는 목록은 `cat`, `nl`, `bat`, `batcat`, `head`, `tail`, `sed -n 'X,Yp'`, `grep`, `egrep`, `fgrep`, `rg`다. **단일 파일, pipe/redirect 없음**, 검색 결과가 실제 존재해야 한다. 따라서 `rg -r` 식의 광역 탐색, pipe, 스크립트 내부 파일 접근까지 같은 load trigger라고 일반화하지 않는다. 최신 도구 문서는 일부 모델에서 사전 Read 없이 Edit가 가능하다고도 명시한다(v2.1.208 이후의 관련 처리). “Edit 전에 언제나 Read가 있으니 rules는 이미 알려져 있다”는 전제는 안전하지 않다. [S4]

`paths`는 rule에서 Claude Code가 읽는 **유일한 frontmatter 필드**다. YAML 목록 또는 comma-separated string을 지원한다. `taskTerms`, `required`, `scope`, `approval` 등을 써도 native routing/enforcement가 생기지 않는다. YAML 파싱 실패 시 해당 rule을 `paths` 없는 것으로 취급하여 **무조건 로드**한다. invalid glob은 일치하지 않을 수 있고, 복잡한 brace expansion에는 문서상 전체 `paths` 목록의 1,000 expanded patterns/4 MiB budget이 있다. [S1]

### 2.2 작은 root-free 예시 — 제안, 설치하지 않음

```text
project/
  .claude/
    rules/
      storage.md              # paths: src/storage/**, tests/storage/**
      public-api.md           # paths: src/api/**, tests/api/**
      private/
        workstation.md        # gitignored; 이 PC + 이 프로젝트 전용 paths
    skills/
      change-storage/
        SKILL.md              # 짧은 절차 + 언제 references를 읽는지
        references/
          migration-review.md
    settings.json             # 승인된 프로젝트 공용 설정만
    settings.local.json       # 개인 로컬 설정; 비공개
```

```markdown
---
paths:
  - "src/storage/**"
  - "tests/storage/**"
---
# Storage conventions
- 저장소 구현 변경은 기존 트랜잭션 경계를 유지한다.
- 데이터 형식 변경은 기존 migration 정책에 따라 검토한다.
```

이 예시는 실제 repo 파일 경로나 기존 정책을 판정한 것이 아니다. **좁고 실재하는 경로로 치환해야 하는 설계 예시**다. 모든 파일에 `**/*`를 지정하는 방식은 launch 로드를 늦출 수 있어도 첫 일반 파일 접근 후 전역 지침이 된다. “회사 공통”이라는 이유로 긴 본문 전체를 `paths: ["**/*"]`에 넣으면 scope 절약의 이점이 사라진다. [INFERENCE, S1]

개인 rule 전용 native `rules.local/` 또는 `.local.md` precedence는 확인한 문서에 없다. `.claude/rules/private/`는 **이 메모의 제안 경로**이며, native project rule처럼 발견되도록 하되 사용자가 선택한 로컬 Git exclude로 비공개 유지한다. private라는 이름만으로 access control/ignore가 생기지 않는다. `~/.claude/rules/`는 모든 프로젝트의 사용자 범위이므로 “이 PC + 이 프로젝트”의 대용물이 아니다. 파일이 무시되어도 Claude에 읽혀 inference context로 전달될 수 있다. [S1][S2]

### 2.3 지연 로딩의 누락과 타이밍

- 파일을 전혀 열지 않는 설계 질문·명령 제안·배포 실행·채팅 답변에는 path rule이 활성화되지 않을 수 있다. 프롬프트에서 파일명을 말한 것만으로 위 도구 기반 조건을 만족한다고 보장하지 않는다. [INFERENCE, S1]
- 최초 Write/Edit가 trigger라면 모델이 **이미 생성한 tool input**을 해당 규칙을 읽고 만들었다고 할 수 없다. 문서는 로드 trigger를 설명하지만, 내부 loader가 첫 write를 다시 계획하게 하는 보편적 barrier를 보장하지 않는다. 위험한 첫 쓰기 전에 필요한 지식은 먼저 명시적으로 읽거나, 사전 gate로 동작 자체를 판단해야 한다. [INFERENCE, S1, S4]
- 한 번 로드된 컨벤션/파일 내용은 읽는 순간만 비용을 내고 사라지는 것이 아니다. 대화 context에 남고 이후 요청에 영향을 준다. `/compact` 후 path rules와 nested instructions는 다시 일치/접근할 때 지연 로드된다. 이전 trigger가 있었으니 새 context에도 항상 남는다고 가정하지 않는다. [S1: Instructions seem lost after /compact][S8]
- `InstructionsLoaded` hook의 `load_reason=path_glob_match|nested_traversal`, `trigger_file_path`, `globs`는 이를 관찰할 수 있게 한다. 그러나 이 이벤트는 **비동기 관찰용**, loading 차단/수정/`additionalContext` 경로가 아니다. mandatory gate를 여기에 붙이면 늦거나 무효다. [S5]
- 외부 shared rule symlink는 간단한 전사 conditional 배포 대안이 아니다. 현재 문서는 working directory 밖 target은 외부 import 승인이 필요하고, 승인 뒤에도 **`paths` 없는 linked rules만 로드**한다고 명시한다. 네트워크 경로 symlink는 따라가지 않는다. 프로젝트 안에 검토된 scoped 복사본을 두거나 skills/plugin 방식으로 별도 배포하는 편이 명확하다. [S1: Share rules across projects with symlinks]

## 3. Native skills: 절차와 참고자료, 의무 규칙과의 차이

### 3.1 progressive disclosure는 선택을 보장하지 않는다

공식 skill 구조는 `SKILL.md` + 선택적 `scripts/`, `references/`, `assets/`다. first-party `skill-creator`는 metadata → body → 필요한 supporting resources의 3단계 disclosure와 “변형별 참고자료를 나누라”는 패턴을 제공한다. 같은 소스는 skills가 **undertrigger**하는 경향도 직접 경고한다. 따라서 “컨벤션을 skill로 옮기면 항상 적절한 순간에 선택된다”는 주장은 first-party 근거와도 맞지 않는다. [S10]

| 설정 | 실제 지원 | 오해하면 안 되는 점 |
| --- | --- | --- |
| 기본 skill | 이름/설명을 목록에 두고 관련성을 모델이 판단; 직접 `/name`도 가능 | 모델 선택은 결정론적 required selector가 아니다. |
| `disable-model-invocation: true` | 자동 모델 호출 금지; 설명도 context에서 제외, 사용자가 명시 호출 | 인지 비용을 줄이는 대신 사용자가 실행하지 않으면 절차도 안 들어온다. |
| `user-invocable: false` | 메뉴/사용자 직접 호출 숨김, 모델은 호출 가능 | 자동성 강화나 의무화가 아니다; 설명 overhead도 남는다. |
| `paths` | 현재 Claude Code 문서의 native skill frontmatter에 지원됨; 일치 파일 작업으로 activation 범위를 제한 | Agent Skills 공통 표준의 필드가 아니다. “only when” 범위 제한을 모든 요청에서 deterministic selection/compliance로 바꾸어 읽지 않는다. |
| `allowed-tools` | skill 호출 turn의 도구 permission grant; 다음 사용자 메시지에 해제 | allowlist로 도구 pool을 제한하는 필드가 아니다. 과도한 권한을 주지 않는다. |
| skill `hooks` | 호출된 뒤부터 세션 끝까지 등록; `once`는 skill frontmatter에서만 지원 | skill이 선택되기 **이전**의 첫 위험 행동을 보호하지 못한다. |
| subagent `skills` preload | 지정 skill 본문을 subagent 시작 시 전체 주입 | 기본 skill의 lazy loading과 다르며 startup 비용이 늘어난다. |

근거: [S3: Frontmatter / Invocation control / Skill lifecycle](https://code.claude.com/docs/en/skills#frontmatter-reference), [S5: Hooks in skills and agents](https://code.claude.com/docs/en/hooks#hooks-in-skills-and-agents), [S8: Skills / Subagents](https://code.claude.com/docs/en/features-overview#understand-how-features-load).

**부담은 본문에서 metadata로 옮겨갈 뿐 0이 아니다.** 현재 문서는 skill listing이 모든 이름을 포함하고, overflow 시 자주 사용하지 않는 설명부터 제거한다고 한다. listing budget은 모델 context의 1%를 기준으로 설정할 수 있고, description + `when_to_use`는 entry당 1,536 characters cap이 있다. 이것은 제품의 **목록 예산**이지 이 프로젝트의 절감률 측정이 아니다. 이름·설명을 짧게 하고, 실제 필요한 skill 수를 작게 유지하는 쪽이 기본이다. [S3: Skill descriptions are cut short]

호출된 skill 본문은 이후 turn에도 남는다. 동일한 rendered content 재호출은 짧은 이미-loaded note로 처리하지만 dynamic output/인자 등이 달라지면 전체 본문이 다시 append될 수 있다. 현재 문서상 compaction은 각 최근 skill invocation의 앞 5,000 tokens를 합계 25,000 tokens 범위에서 보존하며 오래된 skill은 탈락할 수 있다. supporting files도 필요한 내용만 읽어야 한다. 이 제품 상한을 컨벤션 준수 보장이나 전체 context budget으로 해석하지 않는다. [S3: Skill content lifecycle]

### 3.2 배포와 directory discovery

- **프로젝트 공유:** `.claude/skills/<name>/SKILL.md`를 승인된 PR로 commit. 루트 지침 파일 없이 발견된다. 프로젝트·개인·enterprise 동명 skill에는 우선순위가 있고 enterprise > personal > project다. plugin skill은 `/plugin:skill` namespace로 공존한다. [S3]
- **개인:** `~/.claude/skills/`는 이 머신의 여러 프로젝트에 적용된다. 특정 프로젝트의 로컬 전용 skill은 그 프로젝트 `.claude/skills/`의 검토된 gitignored 경로를 사용할 수 있다. private 폴더명은 접근 정책이 아니다. [S3][INFERENCE]
- **하위 package:** `packages/api/.claude/skills/`는 그 안/아래에서 세션을 시작하면 발견된다. 위에서 시작하면 해당 하위 파일을 처음 read/edit할 때 목록에 추가되고 이후 세션에 남는다. 그전에는 메뉴에 없으며 이름으로 호출도 못 한다. `--add-dir`/`/add-dir`로 먼저 발견할 수 있고, `/add-dir` 관련 경로에는 v2.1.257 이상 조건이 문서에 있다. [S3: Load skills in monorepos and subdirectories]
- **팀 공통:** enterprise skills 또는 내부 Git/로컬 marketplace plugin으로 배포한다. managed `extraKnownMarketplaces` + `enabledPlugins`로 force-enable할 수 있지만 설치/enable은 **skill을 매번 사용·준수한다는 뜻이 아니다**. private marketplace는 각 사용자 read 권한이 필요하다. `-p`/CI에서는 plugin background install로 첫 turn에 없을 수 있다. [S7]
- **계정/SaaS:** 현재 문서는 claude.ai account skills가 account 로그인한 terminal(v2.1.273 이후), Cowork, cloud에 sync될 수 있다고 설명한다. 반면 로컬 `~/.claude/skills/`는 Cowork/cloud에 그대로 가지 않는다. API-key/provider/bare/safe-mode/정책 등의 sync 제외 조건이 있다. 회사 승인 계정 배포와 개인 로컬 자료를 혼동하지 않는다. [S3: Skills in Cowork and cloud sessions / Skills synced from claude.ai]
- **포터빌리티:** Claude Code 확장 필드(`paths`, `disable-model-invocation`, `context`, `hooks` 등)를 claude.ai 업로드나 Skills API에서 그대로 쓸 수 없다. 현재 문서는 표준의 `name`, `description`, `license`, `compatibility`, `metadata`, `allowed-tools`만 허용하고 다른 key는 업로드/packaging error라고 명시한다. “native Agent Skills 표준”과 “Claude Code 전용 기능”을 구분해야 한다. [S3: Using skill frontmatter outside Claude Code]

## 4. Native hooks: 정확한 전달 위치와 실행 차단의 경계

### 4.1 이 문제에 관련된 지원 이벤트

| 이벤트 | matcher | context / decision | 적합한 역할 |
| --- | --- | --- | --- |
| `SessionStart` | `startup`, `resume`, `clear`, `compact`, `fork` | `hookSpecificOutput.additionalContext`; 시작/재개 차단은 안 함 | 짧은 scope/환경 정보 갱신. 모든 convention 본문을 넣으면 startup 문제 재발. |
| `UserPromptSubmit` | **지원 안 함**; 적으면 무시 | prompt 처리 전 `additionalContext`; top-level `decision: "block"` 또는 exit 2로 prompt 거부 | 파일 없는 작업의 task recall. 코드 안에서 범위를 판단해야 한다. |
| `UserPromptExpansion` | 사용자 command 이름 | expansion 전 context/차단 | 사용자 직접 `/skill` 경로의 통제. `PreToolUse(Skill)`만으로 직접 호출을 커버하지 못한다. |
| `PreToolUse` | 실제 tool 이름 | `permissionDecision: allow/deny/ask/defer`, `updatedInput`, `additionalContext` | 해당 tool call의 동기 gate. `additionalContext`만으로 이미 생성된 input을 다시 계획하지 않는다. |
| `PermissionRequest` | tool 이름 | `hookSpecificOutput.decision.behavior: allow/deny` | permission 단계의 판단. `PreToolUse`와 동일한 모든-call 이벤트가 아니다. |
| `PostToolUse` / `PostToolUseFailure` | tool 이름 | `additionalContext`; 후속 feedback | 실행 후 사실/오류 전달; 이미 발생한 파일·네트워크 변경을 취소하지 못한다. |
| `PostToolBatch` | 지원 안 함 | 배치 완료 후 context | parallel tool 결과 이후 정리. 첫 쓰기 차단 대안 아님. |
| `InstructionsLoaded` | `session_start`, `nested_traversal`, `path_glob_match`, `include`, `compact` | decision/context output은 버림; async 관찰 | rule 로드 관찰. policy injector/gate가 아니다. |
| `SubagentStart` | agent type | 시작 context만 | worker에게 필요한 짧은 정보. parent 주입이 모든 worker에 전달된다고 가정하지 않는다. |
| `Stop` / `SubagentStop` | Stop은 없음; SubagentStop은 agent type | 종료 feedback/계속 작업시킴 가능 | 사후 검토; 위험 동작 이전 통제를 대신하지 않음. |
| `FileChanged` | 감시할 파일명 | 사후 관찰/side effect; decision 없음 | Bash/IDE/외부 writer 변화 관찰, **쓰기 예방 아님**. |

이 표는 조사 범위에 필요한 subset이다. 전체 이벤트와 schema는 [S5: lifecycle / Matcher patterns / Decision control](https://code.claude.com/docs/en/hooks)에 있다. `Setup`, `Notification`, `SessionEnd`, `PostCompact`, `CwdChanged`, `DirectoryAdded` 등도 있으나 임의의 `additionalContext` output을 모든 이벤트에서 받아주는 범용 injector는 아니다.

**Matchers와 path 조건을 분리한다.** `matcher: "Edit|Write"`는 file glob이 아니라 tool 이름의 alternation이다. 현재 reference의 단순 영숫자/underscore/hyphen/space/comma/pipe 문자열은 exact 또는 exact 목록, 다른 문자가 들어가면 unanchored JavaScript regex다. case-sensitive이고 regex는 필요하면 `^...$`로 고정한다. handler의 별도 `if: "Edit(src/**)"`는 permission-rule syntax의 input 필터이며 tool events에서만 평가된다. 비-tool event에 `if`를 넣으면 handler가 실행되지 않는다. `if`는 단일 rule이고 AND/OR/list syntax가 아니다. Bash parsing은 best-effort라 parser가 결정 못하면 실행되기도 한다. 이것은 보안 경계가 아니라 process spawn을 줄이는 조건이다. [S5: Matcher patterns / Common fields / Bash if matching]

MCP tool은 `mcp__<server>__<tool>`이고 matcher 예시는 `mcp__memory__.*`다. plugin MCP는 `mcp__plugin_<plugin-name>_<server-name>__<tool>`이므로 bare server 이름으로 작성한 matcher는 맞지 않는다. 실제 노출 이름을 기준으로 해야 한다. [S5: Match MCP tools]

### 4.2 `additionalContext`의 함정: PreToolUse에서도 다음 모델 요청에 보인다

공식 reference는 context를 `hookSpecificOutput` 안에 넣고 `hookEventName`을 일치시키라고 규정한다. 예시 payload는 다음과 같다. 이것은 참고 schema이며 설치하지 않았다.

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "additionalContext": "대상 파일은 generated output이다. 원본 스키마를 확인해야 한다."
  }
}
```

`additionalContext`는 system reminder로 대화에 삽입되어 **다음 model request**에서 읽힌다. `PreToolUse`의 추가 context도 **tool result 옆**에 들어간다. 따라서 위 payload만 보내면서 tool을 허용하면 그 쓰기는 이미 생성된 input대로 실행될 수 있다. 첫 위험 쓰기에서 원본 확인이 필수라면 그 call을 `deny`하고 사유를 돌려 모델이 다시 계획하게 하거나, hook이 결정론적으로 input/action 자체를 검사해야 한다. 모델 재계획과 준수 결과까지 보장하는 것은 아니다. [S5: Add context for Claude / PreToolUse decision control]

이 context는 session transcript에 저장된다. resume/continue는 과거 turn의 값을 재실행 없이 replay하므로 오래된 scope/version/SHA가 남을 수 있다. 세션/범위 변경 시 현재 사실을 다시 확인하고, injection을 필요 최소량으로 제한한다. 각 context/plain-output string은 현재 reference상 10,000 characters cap이며 초과하면 파일 path + 최대 2,000-character preview로 바뀐다. 전체 본문이 반드시 모델에 보인다는 보장도 없다. [S5: JSON output / Add context for Claude]

### 4.3 실패·permissions·실행 경계

- 정상 구조화 decision은 **exit 0 + 순수 JSON object**로 반환한다. `PreToolUse`의 차단은 `permissionDecision: "deny"` 또는 exit 2다. exit 1, script missing/권한 없음, 잘못된 JSON, timeout은 기본적으로 **non-blocking/fail-open**이다. stdout log가 JSON 앞뒤에 붙거나 필드가 잘못된 레벨에 있으면 decision/context가 무효가 될 수 있다. [S5][S11]
- **v2.1.295 이상**의 command/HTTP handler `onFailure: "block"`는 실행 실패·timeout·invalid output 등을 block으로 바꿀 수 있다. 기본은 `continue`. background `async`/`asyncRewake`에는 효력이 없고 MCP-tool hook용으로 일반화하면 안 된다. 오래된 client에서는 이 기능을 전제로 하지 않는다. 공개 changelog에서도 이 추가를 확인했다. [S5: Block the action when a hook fails][S12]
- native command/HTTP/MCP hook timeout과 Agent SDK callback timeout은 다르다. reference는 `PreToolUse` SDK callback timeout이 block하는 반면 native handler는 기본 계속한다고 명시한다. SDK 동작을 native settings hook에 그대로 적용하지 않는다. [S5]
- async hook은 이미 행동이 진행되므로 `decision`, `permissionDecision`, `continue`로 예방하지 못한다. `PostToolUse`의 `block`도 실행 undo가 아니라 후속 feedback이다. [S5]
- PreToolUse는 실제 Claude tool 호출에만 적용된다. prompt의 `@file` inline 첨부는 Read tool call 없이 구성되므로 PreToolUse(Read)를 거치지 않는다. user direct skill invocation도 `UserPromptExpansion`이 별도 경로다. IDE에서 사용자가 직접 저장하거나 다른 프로세스가 파일을 쓰는 행위는 Claude tool call이 아니다. Bash가 파일을 쓰면 `Edit|Write` matcher도 발생하지 않는다. [S5: PreToolUse / PostToolUse][S11]
- Bash/Python/Node/PowerShell/외부 script와 MCP writer의 모든 부작용을 file-path matcher가 완벽히 파악한다는 보장은 없다. file deny rule조차 임의 subprocess가 파일을 여는 것까지 막지 못한다. command text deny는 같은 실행 파일의 다른 호출 형태에 우회될 수 있다. hard filesystem/network 경계는 sandbox/OS/server authorization이 맡아야 한다. [S6: Bash rule limits / Read and Edit][S9]
- 현재 문서상 native PreToolUse deny는 `bypassPermissions`에서도 작동하며 allow는 deny/ask 규칙을 자동 무효화하지 않는다. 그러나 user hook은 사용자가 지울 수 있고 managed-only/safe/bare/setting source 정책 등에 따라 로드되지 않을 수 있다. 현재 mods 문서 경로를 연결한 guide는 non-managed hook deny가 mod의 `tool.check`로 승인될 수 있다는 예외도 설명한다. 회사 gate를 개인 설정에만 두면 안 된다. [S11: Hooks and permission modes][S5]
- command hook은 **사용자 전체 OS 권한**으로 실행된다. hook 호출 자체가 permission prompt로 안전하게 보호된다고 기대하지 않는다. shell quoting, dependency/PATH, 절대 script 경로, symlink canonicalization, 비신뢰 입력, 로그 유출을 검토해야 한다. interactive settings hooks는 workspace trust를 기다리지만 `-p`/SDK는 folder를 trusted로 취급하여 repo hooks가 실행될 수 있다는 현재 문서의 차이도 중요하다. [S5: Security considerations]
- 모든 matching hook은 parallel이고 설정 계층 간 merge된다. 여러 hook의 `updatedInput`은 완료 순서에 영향을 받으므로 동일 input을 중복 수정하지 않는다. `deny > defer > ask > allow` decision precedence와 별개 문제다. [S5][S11]

**가장 강한 반론을 인정한다:** hook은 적절한 supported event가 발생하고 handler가 정상 실행되는 범위에서 모델의 선택보다 확실하다. “파일별 rule을 읽어 달라”보다 deterministic check가 적합한 규칙도 많다. 하지만 event 발생의 결정론성은 검사 완전성·load 성공·실패 폐쇄·모든 writer 통제·모델 후속 준수를 자동 보장하지 않는다. 이 한계를 명시하고 작은 gate로 쓰는 것이 타당하다. [S8][S5][S6]

## 5. Managed 정책과 회사/개인 배포를 분리한다

managed **settings**는 모델 prose보다 높은 운영 통제 계층이다. company login/org 제한, 승인된 MCP/marketplace, permissions, sandbox, managed hooks를 여기에 둘 수 있다. managed **`CLAUDE.md`**는 제외할 수 없는 조직 지침이지만 여전히 context이며 모델 adherence와 hard enforcement는 다르다. root-free 요구를 managed instruction file로 옮겨 “컨텍스트 문제가 해결됐다”고 주장하지 않는다. 긴 회사 공통 prose는 승인된 scoped artifacts/skills로 배포하고, 민감 권한 정책은 settings/server에서 집행한다. [S1: Organization-wide rules and settings][S6][S13]

| 사용자 선택 범위 | root-free 저장/배포 제안 | 권한·데이터 경계 |
| --- | --- | --- |
| 로컬 PC + 프로젝트 | 프로젝트 내 선택적 gitignored rule/skill + `.claude/settings.local.json`; MCP local scope | 개인 선택만으로 팀 commit/push를 요구하지 않음. 회사 정책은 그대로 적용. |
| 프로젝트 공용 | 검토된 `.claude/rules/`, `.claude/skills/`, `.claude/settings.json`; 필요 시 credential-free `.mcp.json` | repo ACL/PR 승인과 scope 선택은 별도. secrets/private recall 결과는 commit하지 않음. |
| 팀 공통 | 회사 관리 enterprise skills 또는 승인 내부 plugin; 필요한 scoped rule은 프로젝트 안 검토본 | mandatory settings는 managed tier. 개인 MCP/inference 계정으로 자동 fallback하지 않음. |

이 scope mapping은 **설계 제안**이지 Claude Code가 `local PC + project / project-shared / team-common`라는 단일 selector를 제공한다는 주장이 아니다. 내용 변경은 선택된 scope에 유지하고 더 넓은 배포는 새 승인 절차를 둔다. 원본 memory evidence에서 rule/skill로 승격할 권한도 분리한다.

회사 승인 Team/Enterprise SaaS inference를 허용하는 것과 회사 메모리·백업·규칙 원본을 개인 클라우드에 보관하는 것은 별개다. recall된 내용이 모델 prompt, host transcript, hook debug log에 들어갈 수 있으므로 회사가 승인한 inference·보존 경로만 사용한다. 개인-local artifact라는 Git 배포 구분은 “네트워크로 전혀 보내지 않음”이라는 보장이 아니다. cloud session은 사용자 머신의 local settings/skills/managed file을 그대로 읽지 않으므로 서버 관리 정책 및 cloud에 실제 배포된 artifact를 별도 확인한다. [S3][S13][S14]

## 6. 독립 memory/MCP recall과 연결할 수 있는 경로

Claude Code의 MCP는 local stdio 또는 승인된 remote HTTP를 지원한다. local scope는 `~/.claude.json`의 프로젝트별 항목, project scope는 `.mcp.json`, user scope는 전체 프로젝트용이다. native MCP 연결은 Agent Flow 의존성을 만들지 않는다. 다만 MCP 연결 성공과 **이 서비스의 recall 구현·올바른 scope enforcement·모델이 실제 호출**하는 것은 세 가지 다른 검증 대상이다. [S14]

실용적인 조합은 다음과 같다.

1. **사용자 명시 recall:** skill `/recall-conventions` 같은 절차 또는 MCP prompt `/server:prompt`로 필요한 프로젝트/작업 범위만 검색한다. 서비스는 짧은 근거·출처·유효 scope/version을 반환한다. 메모리 결과는 승인된 rule과 충돌하면 자동 승격하지 않는 참고 증거다. [제안, S3, S14]
2. **파일별 recall:** 선택적 `UserPromptSubmit` 또는 read 이후 hook으로 경로/작업에 맞는 승인된 요약을 주입한다. 파일 없는 작업도 UserPromptSubmit에서 다룰 수 있지만 prompt 전체를 외부 서버에 보낼 필요는 없다. deterministic scope selection과 서버 ACL은 모델이 보낸 project 이름만 믿지 않는다. [제안, S5]
3. **native MCP tool hook:** 현재 reference는 `type: "mcp_tool"`, `server`, `tool`, input template를 지원한다. 하지만 **launch의 SessionStart/Setup은 MCP client가 준비되기 전이므로 skip**한다. 이후 clear/compact의 SessionStart는 다를 수 있다. “MCP recall이 session 시작에 항상 자동 주입”한다고 설계하지 않는다. 서버 연결 대기·인증·`isError:true`는 기본 non-blocking이며 hook은 OAuth flow를 시작하지 않는다. initial context가 정말 필요하면 문서가 권하는 command hook 또는 명시적 첫 recall을 택하고 추가 통제를 검토한다. [S5: MCP tool hook fields]
4. **resource:** `@server:protocol://resource/path`로 지정한 MCP resource는 attachment로 가져오며 지원 서버에는 list/read tool도 생긴다. prompt 첨부나 도구 응답은 이후 context에 남기 때문에 DB를 외부화했다고 토큰이 즉시 사라지지 않는다. [S14: Use MCP resources][S8]

MCP tool search가 켜져도 **도구명·server instructions**는 startup에 남는다. 현재 기본은 지원 모델/호스트에서 schemas를 defer하되, `ENABLE_TOOL_SEARCH=auto`는 threshold 이하일 때 오히려 upfront load한다. proxy/provider/모델 호환성에 따라 fallback도 있다. 작은 recall tool surface와 짧은 descriptions/instructions를 유지하고 결과를 top-k/요약/명시적 추가 읽기로 나누는 편이 낫다. 이 저장소에서 실측 절감률은 없다. [S14: Scale with MCP tool search]

**공식 문서/릴리스 불일치:** 조사 당시 MCP reference는 description/server instructions 기본 cap을 **2,048 characters**라고 했으나, 고정한 2026-10-09 first-party changelog의 v2.1.296은 기본을 **4,096**으로 변경했다고 한다. 하나를 현재 설치 환경의 상수로 단정하지 않는다. 이 차이는 문서 지원 설명, release source, 실제 runtime을 구분해야 하는 직접 사례다. [S12][S14]

## 7. 가장 강한 대안/반론과 결정 기준

| 반론 | 타당한 부분 | 이번 요구에 맞는 응답 |
| --- | --- | --- |
| “공식 기본은 짧은 root CLAUDE.md다” | 공식 overview는 항상 알아야 하는 지식을 CLAUDE.md에 권한다. script 없는 로드, compaction 재주입도 장점이다. | 이번 사용자는 root 지침을 원하지 않는다. 그 장점을 인정하되 root bridge/import를 기본 요건으로 되살리지 않는다. 전역 지식 누락은 명시 skill/선택적 prompt hook/managed enforcement의 trade-off로 기록한다. |
| “rules 파일을 나누면 충분하다” | 팀 ownership과 정리는 좋아진다. | unscoped body는 모두 eager load한다. 진짜 경로 조건이 있어야 한다. |
| “skills로 모두 옮기면 zero-cost다” | body/reference 지연 로드는 유용하다. | metadata도 누적되고 undertrigger/잘못된 선택/compaction 누락이 있다. mandatory 안전 규칙은 skill selection에 의존하지 않는다. |
| “hook이면 반드시 모든 규칙을 지킨다” | event의 deterministic firing과 실제 call deny는 유효하다. | handler failure, 늦은 context, non-tool writes, Bash subprocess, 권한/정책별 load 차이는 별도다. 좁은 검사는 hook, hard data 경계는 sandbox/서버 권한이다. |
| “팀 plugin 하나면 공유와 의무화 완료다” | versioned distribution/namespacing/관리형 enable은 좋은 운영 수단이다. | 배포는 실행·준수의 증거가 아니다. private marketplace access/첫-turn 설치/다른 surface도 확인한다. |
| “auto memory가 이미 있으니 서비스가 필요 없다” | plain files, repository/worktree shared notes는 간단하고 실용적이다. | auto memory는 모델이 선정하는 학습이며 index가 시작에 로드된다. 회사/개인 독립 deployment, 공유 승인, 서버 ACL, 선택 범위는 별도 요구다. memory를 authoritative policy로 쓰지 않는다. |

권장안은 메커니즘을 모두 설치하라는 의미가 아니다. **scoped rules + 작은 skill**부터 쓰고, 실제 mandatory 동작/recall 시나리오에 한해 gate/MCP를 더한다. 회사 강제 정책은 이 optional 도입 순서와 무관하게 유지한다. [S1][S3][S5][S8]

## 8. PR #341와의 관계 및 후속 검증 경계

이 문서는 #341 원래 스펙의 위반을 판정하지 않는다. 원래 PR의 승인된 tracked instruction/skill promotion과 새 **root-free + 개인-local 선택** 요구의 차이는 **채택 적합성**이다. 여기서 조사한 native `paths`, hook event/schema, progressive disclosure를 Agent Flow의 `pathGlobs`/`taskTerms`와 동일한 표준·같은 실행 semantics로 취급하지 않는다. native Claude 경로만으로도 독립 OSS 서비스의 recall 소비는 가능하지만, Agent Flow 연동이 작동한다는 증거는 별도 resolver/runner 검토와 실제 실행에 있어야 한다.

설치/모델 평가를 나중에 허용할 경우 확인할 최소 관측점: root 파일 없는 시작의 loaded memory 목록, 관련/무관련 Read 및 첫 Write/Edit, 단일-file Bash와 pipe/스크립트의 차이, malformed frontmatter, nested discovery, `/compact` 후 reload, 직접 skill vs 자동 선택, hook missing/timeout/invalid JSON, MCP 인증/연결 실패, subagent 및 IDE/외부 writer 경로, 회사/개인 scope 거부. **이번 조사에서는 이 checks를 실행하지 않았다.** command gate의 문서상 지원과 실제 installed binary 지원, 모델 준수율을 분리해서 보고해야 한다.

## 9. 1차 출처와 날짜

공식 docs는 조사일의 live 문서다. 페이지에 publish/update date가 드러나지 않는 항목은 **게시일 미표시, 2026-10-11 열람**으로 처리했다. 문서의 버전 annotation은 feature 조건이지 설치 확인이 아니다. 숫자 예산은 제품 설정/상한이며 workload 절감률이 아니다.

- **[S1]** Anthropic, [How Claude remembers your project](https://code.claude.com/docs/en/memory), 특히 [Path-specific rules](https://code.claude.com/docs/en/memory#path-specific-rules), [Share rules across projects with symlinks](https://code.claude.com/docs/en/memory#share-rules-across-projects-with-symlinks), [Auto memory](https://code.claude.com/docs/en/memory#auto-memory). live, 게시일 미표시, 2026-10-11 열람.
- **[S2]** Anthropic, [Explore the .claude directory](https://code.claude.com/docs/en/claude-directory). rules 자체 발견/Read·Write·Edit, 공용·local config examples. live, 같은 열람일.
- **[S3]** Anthropic, [Extend Claude with skills](https://code.claude.com/docs/en/skills), 특히 [Frontmatter](https://code.claude.com/docs/en/skills#frontmatter-reference), [Nested discovery](https://code.claude.com/docs/en/skills#discovery-from-parent-and-nested-directories), [Content lifecycle](https://code.claude.com/docs/en/skills#skill-content-lifecycle), [Listing budget](https://code.claude.com/docs/en/skills#skill-descriptions-are-cut-short). live, 같은 열람일.
- **[S4]** Anthropic, [Tools reference — Edit tool behavior](https://code.claude.com/docs/en/tools-reference#edit-tool-behavior). read 인정 Bash 조건과 unread edit 차이. live, 같은 열람일.
- **[S5]** Anthropic, [Hooks reference](https://code.claude.com/docs/en/hooks), 특히 [Context injection](https://code.claude.com/docs/en/hooks#add-context-for-claude), [PreToolUse](https://code.claude.com/docs/en/hooks#pretooluse), [Failure handling](https://code.claude.com/docs/en/hooks#block-the-action-when-a-hook-fails), [MCP hooks](https://code.claude.com/docs/en/hooks#mcp-tool-hook-fields), [InstructionsLoaded](https://code.claude.com/docs/en/hooks#instructionsloaded), [Security](https://code.claude.com/docs/en/hooks#security-considerations). live, 같은 열람일.
- **[S6]** Anthropic, [Configure permissions](https://code.claude.com/docs/en/permissions), 특히 [Bash rule limits](https://code.claude.com/docs/en/permissions#bash-rule-limits), [Read and Edit](https://code.claude.com/docs/en/permissions#read-and-edit). live, 같은 열람일.
- **[S7]** Anthropic, [Manage plugins for your organization](https://code.claude.com/docs/en/plugins/org). force-enable, internal marketplace, trusted project/CI distribution, managed locks. live, 같은 열람일.
- **[S8]** Anthropic, [Extend Claude Code](https://code.claude.com/docs/en/features-overview), 특히 [Hook vs Skill / context costs](https://code.claude.com/docs/en/features-overview#compare-similar-features). live, 같은 열람일. [Context-window simulation](https://code.claude.com/docs/en/context-window)의 예시 token 수치는 실측 근거로 사용하지 않았다.
- **[S9]** Anthropic, [Monorepos and large codebases](https://code.claude.com/docs/en/large-codebases), path-scoped rule 비교, additional directory 접근/로드 분리, subprocess 제한. live, 같은 열람일.
- **[S10]** Anthropic first-party [`skill-creator/SKILL.md`](https://github.com/anthropics/skills/blob/dbd4588f9e1033efb41dad4bef2f7947c8993d44/skills/skill-creator/SKILL.md#L74-L123), progressive disclosure/undertrigger advisory. repository snapshot `dbd4588f9e1033efb41dad4bef2f7947c8993d44`; [commit timestamp](https://api.github.com/repos/anthropics/skills/commits/dbd4588f9e1033efb41dad4bef2f7947c8993d44) **2026-10-09 18:45:49Z**. 이 날짜는 repo snapshot 날짜이지 해당 파일 모든 내용의 최초 게시일이 아니다.
- **[S11]** Anthropic, [Automate actions with hooks](https://code.claude.com/docs/en/hooks-guide), 특히 [Limitations](https://code.claude.com/docs/en/hooks-guide#limitations), [Hooks and permission modes](https://code.claude.com/docs/en/hooks-guide#hooks-and-permission-modes), JSON wrong-level pitfalls. live, 같은 열람일.
- **[S12]** Anthropic first-party [pinned Claude Code changelog](https://github.com/anthropics/claude-code/blob/2301018b1f61073c501a8e7a4813ef48c239163b/CHANGELOG.md), v2.1.296와 v2.1.295. snapshot `2301018b1f61073c501a8e7a4813ef48c239163b`; [commit timestamp](https://api.github.com/repos/anthropics/claude-code/commits/2301018b1f61073c501a8e7a4813ef48c239163b) **2026-10-09 19:28:36Z**. snapshot은 설치 binary 검증이 아니다.
- **[S13]** Anthropic, [Deploy managed settings](https://code.claude.com/docs/en/managed-settings). settings와 instruction 구분, source precedence/merge, surface coverage, 다른 도구까지 bind하지 않는 한계. live, 같은 열람일.
- **[S14]** Anthropic, [MCP reference](https://code.claude.com/docs/en/mcp), [Scopes](https://code.claude.com/docs/en/mcp#mcp-installation-scopes), [Resources](https://code.claude.com/docs/en/mcp#use-mcp-resources), [Tool search](https://code.claude.com/docs/en/mcp#scale-with-mcp-tool-search), [Prompts](https://code.claude.com/docs/en/mcp#use-mcp-prompts-as-commands). live, 같은 열람일.

### 읽은 first-party source examples의 적용 범위

- [`examples/hooks/bash_command_validator_example.py`](https://github.com/anthropics/claude-code/blob/2301018b1f61073c501a8e7a4813ef48c239163b/examples/hooks/bash_command_validator_example.py): `PreToolUse/Bash` 등록, stdin JSON, 좁은 regex 검사, exit 2 block, JSON decode error는 exit 1. **좋은 schema 예제이나 완전한 shell 보안 parser가 아니다.** 정규식으로 모든 부작용을 포착한다는 근거로 사용하지 않았다.
- [`plugins/security-guidance/hooks/hooks.json`](https://github.com/anthropics/claude-code/blob/2301018b1f61073c501a8e7a4813ef48c239163b/plugins/security-guidance/hooks/hooks.json): 현재 first-party plugin이 SessionStart/UserPromptSubmit/PostToolUse/Stop을 조합하며 background review를 쓴다는 실제 배포 패턴이다. `PostToolUse`와 async review는 **사후 guidance**다. 별도 LLM review/SDK dependency가 있으므로 작고 로컬인 root-free gate의 그대로 복사할 기본안으로 권하지 않는다. 실행·설치하지 않았다.

Claude Code 전체 private loader/runtime 소스를 공개 예제와 동일시하지 않았다. 공개 docs·release/source examples로 지원과 설계 trade-off를 조사했으며, 관찰하지 않은 runtime 보장에는 근거를 덧붙이지 않았다.
