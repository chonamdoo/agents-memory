# Codex의 root-free·범위별 convention 적용 — 2026-10-11

## 결론

**Agent Flow 없이도 root `AGENTS.md`를 만들지 않고 Codex에 convention을 제공할 수 있다.** 가장 이식성이 높은 기본 경로는 짧은 설명을 가진 `.agents/skills/<name>/SKILL.md`와 명시적 skill 호출이다. 자동 task matching은 모델 판단이며, 파일 경로에 따른 필수 적용을 보장하지 않는다. 경로·작업별 선택을 확실히 하려면 **지원되는 Codex hook 또는 독립 host wrapper가 입력을 판정하고 필요한 규칙만 전달**해야 한다. MCP 서버만 연결해서는 그 판정이 자동 실행되지 않는다.[D1–D4, D7, C3–C6]

현재 Codex에는 `UserPromptSubmit`, `PreToolUse`, `PermissionRequest` 등이 있으며 **모델에 전달되는 `additionalContext`와 일부 작업 차단을 실제로 지원한다.** “Codex에는 notify만 있고 문맥 주입/차단 hook이 없다”는 설명은 이 조사 기준일의 공식 문서와 release 0.162.1 source에 맞지 않는다. 반대로 **Claude hook과 동일한 이름/비슷한 JSON이라는 이유로 모든 필드가 작동한다고 가정해도 안 된다.** `PreToolUse.permissionDecision: "ask"`는 schema에 있어도 현재 지원하지 않으며, 오류를 보고한 뒤 tool을 계속 실행한다.[D3, C5–C8]

중첩 `AGENTS.md`는 root 파일을 없애는 데는 쓸 수 있지만 **읽거나 고칠 파일에 맞춰 본문을 늦게 읽는 일반적인 rule loader가 아니다.** CWD의 ancestor chain을 합쳐 넣는다. 규칙을 `TEAM_GUIDE.md`로 바꾸거나 byte cap을 늘리는 것은 context 증가 원인을 해결하지 못한다.[D2, C9–C11]

**[제안] 독립 OSS memory pipeline의 기본값은 작은 skill + 제한된 MCP 검색/원문 조회 + 서버 측 scope/ACL/분량 제한 + 일반 CI 검사다.** 지원 host에서만 선택적으로 hook adapter를 제공한다. “모든 Codex surface에서 파일별 자동 적용”, “hook이 회사 정책의 완전한 enforcement boundary”, “설치만 하면 모델이 항상 준수”는 제품 약속에서 제외해야 한다.

## 근거와 조사 경계

- 공식 문서는 2026-10-11에 읽은 가변 문서다. 기존 `developers.openai.com/codex/...` 링크 상당수는 현재 `learn.chatgpt.com/docs/...`로 이동하며, desktop 명칭도 **Codex in the ChatGPT desktop app**으로 설명한다. 구 Codex Cloud 링크는 **Codex Cloud (Legacy)** 문서로 이동했다. 이전 글의 host 구분을 그대로 현재 사실로 쓰지 않는다.[D1–D3, D5, D11]
- source는 공식 `openai/codex`의 공개 정식 release **`rust-v0.162.1` / `092d3acd6bec3e3a14bdc7e7a2810ab628ab759d`**에 고정했다. release는 2026-10-09 공개되었고 GitHub tag object를 따라 commit을 확인했다. `main`이나 fork의 미출시 기능을 release 사실로 사용하지 않았다.[C1–C2]
- 공식 제품 계약, 고정 source의 정적 구현, 이 프로젝트에 대한 **[제안]**, source를 바탕으로 한 **[INFERENCE]**를 구분한다. source 존재는 사용자 설치 runtime, 계정 권한, 실제 모델 준수 또는 성능 개선의 증거가 아니다.
- 사용자 binary/runtime/config/credentials를 조사하거나 바꾸지 않았다. Agent Flow 수정, 모델 호출, MCP 연결 실행, build/lint/tests/formatter는 하지 않았다. 이 파일 외에는 저장소 파일을 쓰지 않았다.

## 1. native skills: 발견과 활성화는 다른 단계다

### 1.1 발견 위치와 초기 context

Codex는 Git repository에서 **CWD부터 repository root까지 각 디렉터리의 `.agents/skills`**를 탐색한다. 다음과 같이 구분한다.[D1]

| 배치 위치 | native 발견 범위 | 사용자 요구와의 관계 |
|---|---|---|
| `<repo>/.agents/skills` | 해당 repo에서 시작한 CWD의 ancestor 탐색 | project-shared skill을 version control로 배포할 수 있다. root `AGENTS.md`는 불필요 |
| `<repo>/services/payments/.agents/skills` | payments 또는 그 하위 CWD에서 시작한 경우 | 작업 디렉터리 범위다. repo root에서 시작해 payments 파일을 수정한다고 자동 발견된다는 계약은 없음 |
| `$HOME/.agents/skills` | 여러 repo에서 쓰는 user skill | user-wide다. **로컬 PC + 특정 project** 범위와 동일하지 않음 |
| `/etc/codex/skills` | machine/container의 admin skill | 조직 관리 배포에 쓸 수 있지만 mandatory 정책 enforcement와 동일하지 않음 |
| Codex bundled system skills | host 내장 | OSS memory pipeline이 소유한 convention과 구분 |

symlinked skill folder도 지원한다. 동일 `name`의 skill 둘은 자동 merge되지 않고 selector에 함께 나타날 수 있다. 고정 source의 명시 선택은 enabled skill의 canonical/discovery path를 먼저 처리하며, plain `$name`은 중복이나 connector 이름 충돌이 있으면 선택하지 않는다. **[제안] 자동 wrapper는 이름 추측 대신 발견된 정확한 path/identity로 선택한다.**[D1, C3]

초기에는 skill의 name·description·path 목록이 들어가고, 선택되면 전체 `SKILL.md` 본문을 읽는다. 현재 공식 문서의 초기 목록 예산은 model context window의 최대 **2%**, window를 모르면 **8,000 characters**다. 설명을 먼저 줄이고 목록 일부를 생략할 수 있으며 경고를 표시한다. **본문 예산이나 memory 결과 예산이 아니라 초기 catalog 예산**이다. skill 수가 많으면 작은 catalog도 누적되고 필요한 skill이 초기 목록에서 빠질 수 있다.[D1]

### 1.2 명시 호출, 암묵 호출, 선택 보장

- CLI/IDE는 `/skills` 또는 `$skill-name`으로 명시 호출한다. implicit invocation은 user task와 `description`이 맞는다고 **모델이 판단**하는 방식이다.[D1]
- `agents/openai.yaml`의 `policy.allow_implicit_invocation: false`는 암묵 선택을 끄고 명시 선택은 허용한다. 기본은 true다. 이것은 task/path predicate나 적용 의무가 아니다. 고정 source의 `SkillMetadata::allows_implicit_invocation()`도 생략 시 true다.[D1, C4]
- custom app-server client는 `turn/start`의 text와 함께 `{type: "skill", name, path}` input item을 보내 full skill instructions를 주입할 수 있다. 공식 문서는 이 방식을 권장하며 `$name`만 보내면 모델의 이름 해석/파일 탐색에 의존한다고 설명한다.[D7, C3]
- 이 경로는 **선택·전달을 결정적으로 만들 수 있을 뿐 준수를 결정적으로 만들지 않는다.** 모델이 본문을 따르는지, 올바른 reference를 읽는지, 작업 결과가 규칙에 맞는지는 별도 검증 대상이다.

Agent Skills 표준은 `name`, `description`, 선택적 `metadata`, `compatibility`, 실험적 `allowed-tools`와 progressive disclosure를 정의한다. **`pathGlobs`, `taskTerms`, 단계별 `require/offer`가 모든 host에서 동작하는 표준 selector는 아니다.** 임의 metadata를 저장할 수 있다는 사실도 해당 predicate를 host가 실행한다는 뜻이 아니다. Codex 문서와 확인한 skill policy 모델에도 그 universal selector 계약은 없다. Agent Flow의 자체 matching을 이식하려면 별도 adapter/wrapper의 명시 계약이어야 한다.[D1, D12, C4]

### 1.3 local PC + project를 어떻게 유지할 것인가

**[제안]** 개인-local convention은 해당 repo에서 native가 발견하는 `.agents/skills`에 두되, **그 개인 파일만 로컬 Git exclude에 넣는 방법**을 선택지로 제공할 수 있다. 공유 파일을 담은 `.agents/skills` 전체를 ignore하는 방식은 project-shared 배포를 깨뜨린다. 이 조사에서는 exclude/config를 만들지 않았다. 이 방식은 `repo`라는 host discovery 분류를 쓰면서 실제 배포를 개인-local로 유지하는 것이며, native에 별도 “개인-local 프로젝트 scope”가 있다는 주장과 다르다.

또는 독립 wrapper가 repo identity에 연결한 외부 local rule store를 조회한다. app-server의 `skills/list`는 CWD별 extra user roots, `skills/extraRoots/set`은 비영속 process roots를 제공한다. 다만 extra root의 host scope는 `user`이고 root 설정은 접근권한이 아니므로 wrapper가 project binding을 따로 검증해야 한다. 모든 native IDE/desktop UI가 그 wrapper 선택을 자동 재현하는 것은 아니다.[D7]

## 2. nested AGENTS와 진짜 늦은 로딩의 차이

공식 문서상 기본 chain은 global `$CODEX_HOME/AGENTS.override.md` 또는 `AGENTS.md`, 이어 project root→CWD의 파일을 합치는 방식이다. 각 디렉터리에서는 override/기본/fallback 중 최대 하나를 선택한다. project byte limit은 기본 32 KiB다. 낮은 경로의 내용이 뒤에 붙어 앞선 내용보다 우선한다.[D2]

고정 source의 `agents_md.rs`는 ancestor directory 목록을 만들고 각 파일을 실제로 읽어 합친다. untrusted project에서는 project instruction load를 건너뛰며, project root marker 설정을 project config 자체가 바꾸지 못하도록 비-project layer에서 해석한다.[C9]

| 방식 | 본문이 들어오는 시점 | root-free 요구 판정 |
|---|---|---|
| root `AGENTS.md`를 여러 nested 파일로 분리 | 해당 CWD의 ancestor chain을 로드할 때 | root 파일은 제거 가능. chain에 포함된 본문은 eager |
| fallback `TEAM_GUIDE.md` | 동일 discovery chain | 이름 변경일 뿐 늦은 로딩이 아님 |
| `.agents/skills` | catalog 먼저, 선택된 skill 본문 나중 | 본문을 늦게 읽는 native 대안. catalog 비용은 남음 |
| MCP `search/get` | tool을 실제 호출하고 결과가 모델에 전달될 때 | corpus를 미리 넣지 않음. 자동 호출/필수 선택은 별도 |
| prompt/tool hook 또는 wrapper | handler가 task/path를 판정한 뒤 | 선택 로직을 deterministic하게 만들 수 있음. 지원 host 한정 |

문서는 chain을 “once per run/session”이라고 요약하지만, 0.162.1의 `AgentsMdManager::refresh()`는 startup/request boundary에서 snapshot을 다루고 environment selection 또는 project trust 변화 시 repository 내용을 다시 로드한다. world-state renderer에는 replacement/removal notice도 있다. **따라서 해당 release가 변화에 전혀 대응하지 못한다고 단정하지 않는다.** 그러나 이 구현도 arbitrary 파일 read/edit마다 하위 디렉터리 rule을 lazy activate하는 구현은 아니다. 일반 shell `cd`가 host의 session CWD 선택을 자동 바꾼다고 가정하지 않는다.[D2, C10–C11]

## 3. Codex hooks: 현재 계약을 그대로 구분해야 한다

### 3.1 exact event 목록과 matcher

현재 공식 문서에 열거된 event는 아래 **12개**다. 다른 agent의 event 이름을 추가하지 않는다.[D3]

| Event | `matcher`의 대상 | 핵심 용도/주의 |
|---|---|---|
| `SessionStart` | `startup`, `resume`, `clear`, `compact` | 초기/압축 이후 context 전달. startup에 모든 규칙을 넣으면 root 문제 재현 |
| `SessionEnd` | 현재 `other` | main thread 종료. subagent에 실행되지 않으며 MCP handler 미지원 |
| `SubagentStart` | agent type | subagent context. `continue:false`로 시작을 막을 수 없음 |
| `SubagentStop` | agent type | 계속 작업하게 하는 blocking decision 지원 |
| `UserPromptSubmit` | **무시** | prompt 판정, developer context 전달, prompt 거부 |
| `PreToolUse` | tool name/alias | 지원 tool 실행 전 차단/입력 수정/context 전달 |
| `PermissionRequest` | tool name/alias | **승인이 필요한 경우에만** allow/deny. 모든 tool-call 사전 검사 아님 |
| `PostToolUse` | tool name/alias | 실행 후 feedback/context. 이미 발생한 side effect를 취소하지 않음 |
| `PreCompact` | `manual`, `auto` | 압축 전 event |
| `PostCompact` | `manual`, `auto` | 압축 후 event |
| `Stop` | **무시** | `decision:block`은 turn 거부가 아니라 reason으로 continuation prompt를 만듦 |
| `Interrupt` | **무시** | main thread interruption; subagent에는 실행되지 않음 |

`PreToolUse`/`PostToolUse`는 shell/unified exec를 `Bash`, patch를 `apply_patch` 및 `Edit`/`Write` alias, MCP를 MCP tool 이름으로 관찰한다. local function tool 대부분도 포함한다. **hosted WebSearch는 제외**, 일부 specialized path는 opt-out 가능하며, 이미 시작한 unified exec에 `write_stdin`을 보내거나 poll할 때 `PreToolUse`를 다시 실행하지 않는다. “모든 파일/네트워크 행위를 가로챈다”는 보장이 아니다.[D3]

### 3.2 어디에 두고 누가 승인하는가

- active config layer 옆의 `hooks.json` 또는 inline `[hooks]`를 발견한다. 대표 위치는 user `~/.codex/`와 project `<repo>/.codex/`다. project hook은 project가 trusted일 때만 로드한다.[D3]
- 여러 source의 matching hook은 모두 합쳐 실행한다. 높은 layer가 낮은 layer hook을 대체하지 않는다. 같은 event의 matching command handler는 concurrent하게 시작하므로 다른 hook의 시작 자체를 막을 수 없다.[D3]
- non-managed hook은 **정확한 정의 hash에 대해 review/trust**해야 실행된다. 변경된 정의는 다시 검토하기 전까지 skip한다. plugin 설치/enable도 hook trust를 자동 부여하지 않는다.[D3–D4]
- managed system/MDM/cloud/requirements source hook은 정책에 의해 trusted로 표시되며 사용자가 hook browser에서 끌 수 없다. `allow_managed_hooks_only`는 user/project/session/plugin hook을 제외한다. 개인-local 선택은 mandatory managed policy를 우회하는 허가가 아니다.[D3, D6]
- release 0.162.1 feature registry는 `hooks`를 Stable/default true, `plugins`도 Stable/default true로 둔다. `plugin_hooks`는 Removed이다. 예전 experimental toggle을 현재 설치 전제로 요구하지 않는다. 다만 실제 runtime override/관리 정책은 이 조사에서 확인하지 않았다.[C12]

### 3.3 context와 permission blocking은 있지만 Claude 전체 호환은 아니다

`SessionStart`, `SubagentStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`는 문서에 event-specific `additionalContext` 경로가 있다. Codex source의 `HookAdditionalContext::role()`은 **`developer`**를 반환한다. `systemMessage`는 UI/event warning이지 같은 모델 instruction channel이 아니다.[D3, C6]

지원되는 대표 응답 형태는 다음과 같다. **설치용 예제가 아니라 현재 contract 차이를 설명하는 예제**다.[D3, C5–C8]

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "additionalContext": "이번 patch에 적용되는 승인된 경로 규칙만 전달한다."
  }
}
```

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "해당 작업은 이 범위의 승인된 정책에 의해 허용되지 않는다."
  }
}
```

- `UserPromptSubmit`: structured `additionalContext` 또는 plain stdout을 developer context로 넣는다. `decision:block` + reason 또는 exit 2 + stderr로 prompt를 막을 수 있다. event input에는 `prompt`, `cwd`, session/turn ID 등이 있지만 **신뢰된 changed-files 목록은 없다**.[D3, C7]
- `PreToolUse`: deny, legacy block, exit 2를 지원한다. context만 전달할 수도 있다. `permissionDecision:allow` + `updatedInput`은 지원 tool input을 바꾼다. Bash/patch는 string `command`가 필요하다. **allow는 모든 sandbox/관리 정책을 해제하는 허가로 해석하지 않는다.**[D3, C5]
- `PreToolUse`의 `ask`, legacy `approve`, `continue:false`, `stopReason`, `suppressOutput`은 현재 미지원이다. 특히 **schema에 enum/field가 있다는 것과 실행된다는 것은 다르다.** pinned parser가 invalid reason을 만들고 block reason을 비우는 것을 확인했다.[D3, C5, C8]
- `PermissionRequest`는 nested `decision.behavior:allow/deny`다. 여러 hook의 deny가 우선하며 아무도 결정하지 않으면 normal approval flow다. `updatedInput`, `updatedPermissions`, `interrupt`는 reserved이고 현재 fail-closed다. `PreToolUse`의 JSON을 그대로 복사하는 event가 아니다.[D3]
- `PostToolUse.block`은 완료된 명령을 undo하지 않고 feedback으로 tool result를 대체한다. `Stop.block`은 재작업 turn을 이어가므로 loop 방지가 필요하다.[D3]
- `command`, `mcp_tool` handler를 지원한다. `prompt`/`agent` handler는 parse되어도 skip한다. async command hook은 informational output을 다음 safe point에 전달할 뿐 **차단/승인/수정할 수 없다**.[D3]

### 3.4 context 누적과 fail-open 경계

기본 model-visible hook output limit은 메시지당 약 **2,500 tokens**다. 긴 output은 `<temp_dir>/hook_outputs/...`에 저장하고 preview+path를 준다. `additionalContextLimit`은 각 command handler의 해당 context threshold이고, `0`은 전량 전달이다. 여러 hook의 총합 cap 또는 세션 전체 누적 cap은 아니다. 같은 규칙을 prompt마다 다시 넣거나 `SessionStart:compact`마다 corpus를 재주입하면 context 문제가 돌아온다. spill 파일에 민감정보를 출력해도 위험은 사라지지 않는다.[D3]

MCP hook은 이미 연결된 server를 호출하며 서버를 새로 시작/reconnect하지 않는다. normal tool approval이나 다른 hook도 추가로 trigger하지 않는다. **명시적 supported deny는 차단할 수 있지만 server/tool 부재, callback error, timeout, malformed response가 무조건 차단되는 것은 아니다.** 일반 tool path coverage의 예외도 있으므로 mandatory 회사 정보 유출 방지를 hook에만 맡길 수 없다.[D3, D6]

**[제안]** hook은 승인된 convention 전달의 보조 adapter로 사용한다. 결과는 rule ID/version/scope·짧은 규칙·source pointer만 담고 이미 전달한 동일 version은 반복하지 않는다. 중요 scope 전환에는 이전 규칙이 더 이상 적용되지 않는다는 notice를 주되, 이것을 과거 context나 파일의 물리적 삭제로 광고하지 않는다. 큰 scope 전환은 새 thread를 선택지로 둔다. mandatory ACL/network/export 통제는 서버·실행 환경에서 별도로 적용한다.

## 4. plugins: 배포 묶음이지 universal policy 엔진이 아니다

현재 portable package는 root `plugin.json`의 Agent Plugins schema, `skills/`, 필요할 때 `mcp.json`을 사용한다. OpenAI-specific app mapping/hook/presentation은 `extensions.com.openai`에 둔다. `.codex-plugin/plugin.json`은 compatibility fallback이다. 임의로 모든 Claude plugin manifest를 Codex-native라고 부르지 않는다.[D4]

| artifact/정책 | 역할 | 별도로 필요한 것 |
|---|---|---|
| `<repo>/.agents/plugins/marketplace.json` | project/team catalog | package 검토·version/ref pin·host 지원 |
| `~/.agents/plugins/marketplace.json` | personal local catalog | project 한정이 아님; 회사 자료의 개인 배포 금지 |
| `<repo>/.codex/config.toml`의 `plugins."name@marketplace".enabled` | trusted project의 local-marketplace plugin enable/disable | package 설치 및 connector 인증; workspace imported plugin의 상태를 바꾸는 기능이 아님 |
| marketplace `policy.installation` | `AVAILABLE`, `INSTALLED_BY_DEFAULT`, `NOT_AVAILABLE` 등 install policy | invocation마다 rule이 맞는지/준수하는지와 별도 |
| `policy.authentication` | 설치 시/첫 사용 인증 시점 | 실제 서비스 ACL·호출 승인과 별도 |
| plugin MCP `enabled_tools`, `disabled_tools`, approval mode | host tool 노출/호출 policy | memory record별 scope authorization은 서버가 담당 |
| managed marketplace source allowlist | 지원 local client에서 add/install/refresh 거부 및 runtime filtering | content 심사·암호학적 신뢰·웹/mobile 정책을 자동 대체하지 않음 |

plugin connector는 사용자/서비스의 권한을 늘리지 않는다. 설치, 인증, hook trust, tool action approval, convention을 team-shared로 승격할 권한은 각각 다른 승인이다. managed `config.toml` marketplace default는 사용자가 override 가능한 기본값이며 enforced `requirements.toml`과 동일하지 않다.[D4–D6]

공식 package 문서는 **plugin lifecycle hooks를 manually installed Codex desktop plugin으로 제한하고 hook 포함 package는 public directory 제출 불가**라고 명시한다. 한편 hooks/runtime 문서는 enabled plugin hook loading과 CLI의 hook review도 설명한다. **이 차이를 지워 CLI/web/IDE 모두에 plugin-hook package를 배포해도 된다고 결론내리지 않는다.** public 배포에서는 skill/MCP만 portable core로 두고, hook은 지원 local runtime의 별도 선택 설치로 구분하는 편이 안전하다.[D3–D5]

관리자가 Git marketplace source를 제한할 때 URL과 optional exact ref 또는 anchored host pattern을 사용하며 local source는 normalized absolute path다. official OpenAI-curated Git source도 allowlist에 맞아야 한다. 그러나 bundled/remote workspace plugin은 별도 정책이다. Git branch ref가 승인되었다고 그 branch의 미래 내용까지 검토된 것은 아니다. **[제안] 실제 승인 artifact는 commit/digest에 연결한다.**[D6]

## 5. surface별 적용표

아래는 문서/released source의 지원 경계다. **실제 설치된 host나 계정의 검증표가 아니다.** `조건부`는 지원/정책/실행 위치를 확인하기 전 제품이 보장하면 안 된다는 뜻이다.

| surface | standalone skills | plugins | local hooks / task-path 자동 선택 | MCP·wrapper 적용 |
|---|---|---|---|---|
| Codex CLI 0.162.1 계열 | 공식 지원; `.agents/skills`, 명시/암묵 호출 | `/plugins` 및 configured marketplace 지원 | core hooks 지원, default on; trust/managed policy·tool coverage 제한 | STDIO/HTTP 지원. 독립 wrapper가 app-server/exec 입력을 선택 가능 |
| Codex IDE extension | 공식 standalone skill 지원 | **미지원이라고 명시** | 공유 core/app-server에 hooks/list가 있어도 IDE의 trust UI·각 lifecycle 동일 실행을 확인한 것은 아님. CLI와 완전 동일하다고 보장 금지 | 공식 local MCP 공유 config 지원; 별도 wrapper를 IDE가 자동 사용하는 것은 아님 |
| Codex in ChatGPT desktop app | 공식 standalone skill 지원 | public/local/repo marketplace 지원 | 지원 local Codex runtime hooks. plugin packaging은 manual desktop 제한 확인 | 같은 Codex host의 MCP config 공유; 계정/실행 환경 조건 별도 |
| `codex exec`, SDK로 만든 CI/local automation | local runtime 기반; runner에 artifact와 올바른 CWD 필요 | runtime/package provisioning·trust에 조건부 | headless에서 human trust prompt가 해결된다고 가정 금지. 검토되지 않은 hook trust 우회 기본값 금지 | exec/SDK 지원; wrapper 선택과 structured output 가능. 일반 lint/CI는 모델 불필요 |
| Codex Cloud (Legacy: code review/Linear/GitHub) | 이 문서만으로 local skill auto-discovery 동등성 확인 불가 | local marketplace 그대로 소비한다는 보장 없음 | local config/hook이 자동 배포되는 것으로 추론 금지 | cloud checkout/container/setup/network가 별도; 공개 문서로 미확인 부분은 미지원 단정 대신 보장 제외 |
| ChatGPT web/mobile의 Chat/Work | plugin-bundled skills 사용 가능; local standalone 폴더와 다름 | account/workspace supported plugins | local command/plugin hook 미지원인 cloud orchestration 존재. personal Work Cloud local-access에는 enterprise hook 미적용 | hosted remote plugin tool, local STDIO/config와 동일하지 않음 |
| Enterprise Work Cloud + Local computer access / dots | 계정·workspace·surface별 | workspace policy 별도 | 관리 remote MCP hook만 지원되는 orchestration 경로. local command/plugin hook 미지원; callback failure 차단 보장 없음 | local executor와 cloud orchestrator policy 별도. memory 동기화 요구가 아님 |
| 독립 app-server client | `skills/list`와 정확한 skill input item | 일부 plugin RPC는 under development; production 사용 금지 문구 | 해당 runtime에 대한 explicit adapter. 모든 native host에 동일 선택 강제 불가 | stdio JSON-RPC custom client 가능. WebSocket은 experimental/unsupported production 경계 |

근거: standalone discovery/IDE [D1], plugin surface [D4–D5], shared local MCP [D8], hook/enterprise [D3, D6], app-server [D7], exec/SDK [D9–D10], legacy cloud [D11]. Desktop/CLI가 같은 설정을 공유한다고 account feature와 executor filesystem까지 같다는 뜻은 아니다.

## 6. 독립 memory pipeline의 선택지 비교

| 선택지 | 규칙 선택 주체 | 장점 | 강한 반론/빠지는 입력 |
|---|---|---|---|
| description 기반 native skill | 모델 | 별도 Agent Flow/wrapper 불필요, 본문을 늦게 읽음 | 필수 선택 보장 없음, description 축약/skill omission/이름 충돌, task에 path 없음 |
| 명시 `$skill` | 사용자+host | 가장 단순한 root-free opt-in | 사용자가 선택을 빼먹을 수 있음; `$name`만으로 중복 identity 문제 |
| Codex task/tool hook | 승인된 handler | supported prompt/tool boundary에서 결정적 판정과 전달/차단 가능 | platform/version/trust/managed-only 제한; shell 문자열에서 정확한 파일 추정 어려움, coverage 예외/fail-open |
| 독립 custom host wrapper | wrapper | 실제 diff/path/task 입력을 통제하고 exact skill item을 전달 가능 | wrapper를 거치지 않는 IDE/desktop/native CLI는 적용 안 됨; 별도 host 유지보수 책임 |
| 일반 MCP `select/search/get` | 도구 호출은 모델/사용자, 결과 필터는 서버 | 여러 host와 Agent Flow 비사용자 지원; corpus를 미리 주입하지 않음 | 호출을 강제하지 못함; 모델이 보낸 project/path/task는 authorization 증거가 아님 |
| MCP lifecycle hook | 지원 Codex host가 event를 호출, 서버가 predicate 판정 | custom wrapper 없이도 supported host에서 event 기반 실행 가능 | ordinary MCP 기능과 다름; already-connected 필요; unavailable/error에서 차단되지 않을 수 있음 |
| ordinary server-side filtering | 서버 | scope ACL, 승인 status, 경로 predicate, 응답 cap을 host와 독립 구현 가능 | server가 실제 파일 edit나 hidden task를 모르며 선택 호출 자체는 보장 못함 |
| 일반 linter/static check/CI | 코드·설정으로 검사 | root instructions도 model inference도 없이 observable 규칙을 enforce | 의미적 설계 판단 전부 표현할 수 없고 작성 전 안내를 대신하지 않음 |

### 6.1 신뢰할 수 있는 task/file activation 계약 [제안]

1. **scope 선택은 활성화/범위 변경 시 독립 입력으로 받는다.** `local PC + project`, `project-shared`, `team-common`을 구별하고 기존 scope는 본문 수정만으로 넓히지 않는다. broader scope에는 해당 권한자 선택/승인이 필요하다.
2. **identity와 selection evidence를 분리한다.** 회사/개인 endpoint·계정·허용 tenant/project binding은 server/host가 검증한다. `task_text`, requested path, model-generated reason은 relevance evidence일 뿐 접근권한 증명은 아니다.
3. **경로는 명시된 파일, 현재 observed patch/diff, tool의 실제 structured input처럼 확인 가능한 입력부터 사용한다.** repo-relative normalized path·symlink/canonical boundary·rename/new file/cross-module 작업을 다룬다. arbitrary Bash의 효과를 regex로 완전히 해석한다고 주장하지 않는다.
4. **입력이 부족하면 자동으로 team corpus 전체를 넣지 않는다.** task만 있으면 task selector 결과를 제한하고 missing-path를 표시한다. 여러 scope가 섞이거나 mandatory path 판정이 필요한데 자료가 없으면 작업 전 확인/허용된 최소 정보 요청 또는 외부 실행 정책의 거부로 처리한다. 모델 추측으로 승인 scope를 넓히지 않는다.
5. **전달은 작은 active set으로 제한한다.** rule ID/version/scope/source와 지금 적용할 짧은 본문만 반환한다. full memory extraction, backup, 모든 team skill 본문을 startup/hook context에 넣지 않는다. references/get은 필요할 때 따로 요청한다.
6. **적용 근거와 enforcement를 분리한다.** skill injection event나 hook success는 전달 증거다. 검증 가능한 규칙은 linter/CI/서버 validation으로 확인하고, semantic convention은 명시적 검토 결과로 남긴다. 미실시 model evaluation을 준수 증거로 표시하지 않는다.

이 계약은 Agent Flow의 phase/isolated review/자체 resolver를 필요조건으로 두지 않는다. 작은 standalone 사용자는 native skill을 직접 호출하고 필요할 때 memory MCP를 검색할 수 있다. stronger automatic activation이 필요할 때만 supported hook 또는 독립 wrapper를 선택한다. 공식 `codex exec`/SDK는 CI에 쓸 수 있지만 여기서 paid model CI나 새 runner를 실행/구현한 것은 아니다.[D7, D9–D10]

### 6.2 회사와 개인의 권한 경계

회사 approved Claude/Codex inference를 쓰는 것과 회사 memory/rule/backup을 개인 서비스로 보내는 것은 별개다. **[제안]** 공통 service/domain 설계를 회사·개인에 각각 독립 배포하고 endpoint, storage, backup, rule publisher, tenant authorization을 나눈다. 회사 승인 모델 계정은 회사 데이터 경계를 유지한 채 추론에만 사용한다. 회사 convention을 `$HOME/.agents/skills`나 personal marketplace로 자동 복사하거나 개인 cloud로 동기화하지 않는다.

개인-local convention 작성에 team commit/push/승인을 요구하지 않는다. 반대로 local scope 선택으로 회사 mandatory policy를 끄거나 corporate-to-personal export를 승인하지 않는다. skill description의 “승인됨” 문구, marketplace의 `AVAILABLE`, plugin 설치, OAuth 로그인, hook trust는 **team rule publication authority**를 대신하지 않는다. mandatory 정책은 managed requirements, 서버 ACL, 실행/network 통제와 연결하고 default/user policy와 구분해야 한다.[D3–D6, D8]

## 7. PR #341과의 관계: 원래 spec와 새 요구를 분리

원래 #334/#341의 tracked `AGENTS` 또는 project skill promotion 선택지는 당시 요구에 대한 배포 설계다. root `AGENTS.md`에 convention을 승격하는 경로가 있다는 것만으로 원래 spec 위반이라고 판단하지 않는다. **현재 사용자의 root-free 요구에는 그 AGENTS 경로가 채택 불가**이고, project skill 경로는 lazy body·scope·명시 승인·비사용자 독립 사용 조건을 만족하도록 선택할 수 있다.

이 note의 Codex native skill/plugin/hook 발견은 Agent Flow의 `pathGlobs`/phase selector가 native Codex에서 동일하게 실행된다는 증거가 아니다. 반대로 별도 OSS memory service가 Agent Flow 없이는 작동할 수 없다는 근거도 아니다. 무엇을 재사용할지는 “선택된 규칙을 전달하는 adapter”와 “memory domain/권한/배포”를 분리해서 판단해야 한다.

## 1차 출처

### 공식 문서 — 2026-10-11 확인, 가변

- [D1] [Build skills](https://learn.chatgpt.com/docs/build-skills): progressive disclosure, 초기 목록 예산, `.agents/skills` 탐색, user/admin/system, symlink, explicit/implicit, invocation policy.
- [D2] [Custom instructions with AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md): global/project ancestor chain, fallback, byte budget, nested CWD.
- [D3] [Hooks](https://learn.chatgpt.com/docs/hooks): exact event/matcher/input/output, trust, tool coverage, context limits, async/MCP handler, fail-open 및 cloud 경계.
- [D4] [Package your plugin](https://developers.openai.com/plugins/build/plugins): portable/compatibility manifest, repo/personal marketplaces, project enable, installation/authentication policy, plugin hooks manual desktop/public-directory 제한, MCP approval configuration.
- [D5] [Plugins](https://learn.chatgpt.com/docs/plugins): desktop/CLI/browser, **IDE plugin 미지원**, API-key availability, workspace/connector 권한.
- [D6] [Managed configuration](https://learn.chatgpt.com/docs/enterprise/managed-configuration): defaults/requirements 차이, hook 관리, marketplace source allowlist, local/cloud/account 경계.
- [D7] [Codex App Server](https://learn.chatgpt.com/docs/app-server): exact skill input, skills/list/extraRoots, custom-client approvals/events, plugin RPC under-development와 WebSocket 경계.
- [D8] [Model Context Protocol](https://learn.chatgpt.com/docs/extend/mcp?surface=cli): local CLI/IDE/desktop config 공유, STDIO/HTTP, project trust, server instructions, enabled/disabled tools, approval mode, cloud orchestration 제한.
- [D9] [Non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode): exec/CI, prompt+stdin, JSON/schema, required MCP startup failure, ephemeral, 안전한 CI 인증. 이 조사에서는 실행하지 않음.
- [D10] [Codex SDK](https://learn.chatgpt.com/docs/codex-sdk): local automation, TypeScript/Python, app-server와 역할 차이.
- [D11] [Codex Cloud (Legacy)](https://learn.chatgpt.com/docs/environments/cloud-environment): code review/Linear/GitHub scope, checkout/container/setup/network. local config/hook parity의 근거로 사용하지 않음.
- [D12] [Agent Skills specification](https://agentskills.io/specification): metadata와 본문/reference 단계 공개, experimental allowed-tools. universal path/task selector를 정의하는 문서가 아님.

### 공식 released source — commit 고정

- [C1] [Release 0.162.1](https://github.com/openai/codex/releases/tag/rust-v0.162.1), [release API](https://api.github.com/repos/openai/codex/releases/latest): 조사 시 최신 정식 release 확인. latest API 자체는 가변.
- [C2] [Tag ref](https://api.github.com/repos/openai/codex/git/ref/tags/rust-v0.162.1), [annotated tag object](https://api.github.com/repos/openai/codex/git/tags/7a078f6bb4ce0dc2a81408b334ce52979d92c603): commit `092d3acd6bec3e3a14bdc7e7a2810ab628ab759d` 확인.
- [C3] [skills/src/selection.rs](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/skills/src/selection.rs): structured exact path, enabled 여부, plain name ambiguity 처리.
- [C4] [skills/src/model.rs](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/skills/src/model.rs): allow_implicit_invocation 기본 true와 실제 SkillPolicy fields. products field의 존재를 모든 경로 enforcement로 일반화하지 않음.
- [C5] [hooks/src/engine/output_parser.rs](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/hooks/src/engine/output_parser.rs): event-specific 추가 context/block/decision parser 및 unsupported fields 처리.
- [C6] [core/src/context/hook_additional_context.rs](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/core/src/context/hook_additional_context.rs): model-visible developer role.
- [C7] [UserPromptSubmit input schema](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/hooks/schema/generated/user-prompt-submit.command.input.schema.json): prompt/CWD/session/turn fields, changed-files field 없음.
- [C8] [PreToolUse output schema](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/hooks/schema/generated/pre-tool-use.command.output.schema.json): schema가 parse하는 enum과 runtime 지원을 구분하는 근거.
- [C9] [core/src/agents_md.rs](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/core/src/agents_md.rs): root→CWD 발견, eager read/concat, untrusted project skip, root marker 설정 경계.
- [C10] [core/src/agents_md_manager.rs](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/core/src/agents_md_manager.rs): startup/request boundary snapshot, environment/trust 변화 시 refresh, host thread contribution 별도 제한.
- [C11] [core/src/context/world_state/agents_md.rs](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/core/src/context/world_state/agents_md.rs): replacement/removal notice. arbitrary file-touch lazy loader나 과거 token 물리 삭제 증거는 아님.
- [C12] [features/src/lib.rs](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/features/src/lib.rs): `hooks` Stable/default true, `plugins` Stable/default true, `plugin_hooks` Removed.

`~/.codex/rules`의 `.rules`도 root-free artifact지만 **sandbox 밖 command prefix의 allow/prompt/forbidden을 정하는 execpolicy**다. Markdown convention을 파일별로 lazy load하는 기능과 혼동하지 않는다. [공식 Rules 문서](https://learn.chatgpt.com/docs/agent-configuration/rules)는 Starlark `prefix_rule`과 compound shell 처리 제한을 설명한다.
