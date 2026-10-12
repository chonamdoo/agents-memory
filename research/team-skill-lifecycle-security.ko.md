# 팀 skill/rule의 승인·배포·철회 경계

확인일: 2026-10-11. 설계 조사만 수행했다. 실제 회사 설정·계정·자격 증명을 열람하지 않았고, skill 설치·실행·파일 동기화·회사 자료 생성·GitHub 게시를 하지 않았다. 아래 **공식 동작**은 이번 세션에 읽은 1차 문서, **설계 제안**은 이 OSS에 권장하는 계약이다. 제품 문서의 최신 기능이 실제 설치 버전에 있다는 보장은 아니다. 구현 소스는 확인하지 않았으므로 commit 근거는 없다.

## 1. 핵심 결론

- 회사가 승인한 회사 소유/팀 Claude·Codex 계정으로 작업하는 전제를 유지한다. 회사가 완전 망분리되어 있다거나 로컬 모델 대체가 필수라고 가정하지 않는다.
- 회사 memory/corpus/백업/팀 규칙의 저장·배포 원본은 회사 통제 저장소에 둔다. 개인 환경은 동일 OSS core와 인터페이스를 쓰되 배포·저장소·계정·credential·bundle을 분리한다. 회사 자료를 개인 cloud/account, 미승인 memory/inference/embedding API 또는 공개 OSS/GitHub로 내보내는 경로는 기본 차단한다. 이것은 **설계 정책**이며 현재 회사에 이미 적용되었다는 뜻이 아니다.
- 리뷰 교훈은 vector-store 검색 사실로만 남기지 않는다. **사건 기록 → 후보 → 범위를 명시한 사람 검토 → 버전 있는 승인 skill/rule → 배포 → 다음 실행에서 활성화**로 관리한다. 모델이 반복 관측이나 confidence만으로 의무 규칙을 승격하지 않는다.
- **MCP 연결 ≠ native skill 설치/갱신 ≠ 회사 모델 계정/작업공간 신원 증명.** MCP context 제공과 native host 배포 adapter는 별도 책임이다.

## 2. 공식 동작: skill, 상시 규칙, MCP는 다른 층

### 2.1 Skill은 재사용 절차이며 점진적으로 로드된다

Agent Skills 표준은 `SKILL.md`의 `name`/`description` 메타데이터, 선택 시 본문, 필요할 때 reference/script를 읽는 progressive disclosure를 규정한다. `metadata.version` 같은 메타데이터를 담을 수 있지만, 그것만으로 승인·서명·버전 고정·철회를 강제하는 표준은 아니다. `allowed-tools`도 host별 지원이 달라지는 실험적 필드다.[S1]

Claude Code는 일반 세션에서 description을 context에 넣고, 명시적 `/skill-name` 또는 모델 선택 시 본문을 로드한다. `disable-model-invocation: true`는 자동 호출을 막고 description도 모델 context에서 제외한다. `user-invocable: false`는 사용자 메뉴/직접 호출을 숨기는 것이지 모델 호출 차단이 아니다. preloaded subagent는 본문을 시작 시 넣는 예외다.[S2: Control who invokes a skill]

Codex도 name/description으로 발견하고 선택 시 본문을 읽는다. 명시적 `$skill` 또는 `/skills`, description 매칭에 의한 implicit invocation을 지원한다. `agents/openai.yaml`의 `policy.allow_implicit_invocation: false`는 자동 호출만 막으며 명시적 호출은 남는다. initial skill 목록에는 budget이 있어 description 축약 또는 일부 skill 누락 경고가 발생할 수 있다.[S3]

**설계 제안:** 승인된 재사용 절차는 native metadata에 정확한 적용 범위/trigger를 제공해 자동 발견을 유지한다. 메타데이터 자체도 회사 자료로 취급한다. 자동 **호출**과 자동 **승인/파일 수정/배포**를 혼동하지 않는다. 중요한 상시 의무 규칙은 description 매칭 성공 여부에 의존시키지 않는다.

### 2.2 상시 convention은 instruction/rule에, 사건은 memory에

Claude 문서는 build command·convention·항상 적용되는 규칙을 `CLAUDE.md`, 다단계 절차를 skill, 일부 파일에만 필요한 지침을 path-scoped `.claude/rules/`로 나누라고 설명한다. `CLAUDE.md`와 auto memory는 enforced configuration이 아닌 context다. 규칙 파일에서 native가 읽는 frontmatter는 `paths`뿐이다.[S4]

Codex 공식 문서는 `AGENTS.md`를 매번 적용할 project guidance, memory를 과거 작업의 context, skill을 repeatable process, MCP를 외부 시스템 접근으로 구분한다. 반복 리뷰 피드백을 가까운 범위의 `AGENTS.md`에 정리하는 feedback loop를 소개한다.[S5]

**설계 분류:**

| 종류 | 내용/권위 | 배치 |
| --- | --- | --- |
| episodic memory | 특정 리뷰/수정의 관측, 근거와 시점; 아직 팀 규범 아님 | 회사 memory store, provenance 포함 |
| reusable skill | 특정 작업에서 재사용하는 절차와 참조; 승인된 범위에서 선택 실행 | native skill bundle |
| mandatory convention | 항상/해당 코드 범위에서 따르는 승인 팀 규칙 | host instruction/rule adapter |
| 보안상 강제 통제 | 데이터 접근·배포·API/credential 허용 경계 | 서버 ACL, 배포 권한, 회사 승인 host 설정 등 모델 밖 |

문서상 context 우선순위와 실제 접근 강제력을 같은 것으로 다루지 않는다. 이 조사에서 특정 회사의 코드 리뷰 기준은 만들지 않았다.

### 2.3 MCP가 native skill 파일을 설치한다는 계약은 없다

MCP `prompts/list`와 `prompts/get`은 재사용 prompt의 발견·조회이고, `notifications/prompts/list_changed`는 목록 변경 통지다. prompt는 user-controlled로 설계되며 UI 방식은 host 재량이다. 이것은 `SKILL.md` 설치, local host instruction 재작성, 계정 profile 선택을 정의하는 API가 아니다.[S6]

Codex customization 문서도 skill이 workflow를 정하고 MCP가 외부 tool/resource/prompt를 연결한다고 구분한다. plugin은 skill과 MCP connection을 함께 배포할 수 있고 skill dependency가 MCP 설치/연결을 도울 수 있지만, **MCP 연결만 하면 역으로 native skill이 설치된다는 뜻은 아니다.**[S3][S5]

**설계 제안:** MCP core는 승인 bundle 목록/버전/본문을 권한에 맞게 제공할 수 있다. native 경로에 materialize하고 충돌·profile·변경 시점을 다루는 일은 **명시적으로 승인된 host-specific 배포 adapter**가 맡는다. 일반 MCP tool 호출 성공을 native 설치 완료 또는 model-side 적용 증거로 기록하지 않는다.

## 3. 공식 host별 로딩·배포 계약

아래는 필요한 경로/옵션만 기록했다. 실제 로컬 파일을 열거나 설정을 변경하지 않았다.

| Host | 팀/project 배포 | 전역·managed 범위와 주의 |
| --- | --- | --- |
| Claude Code | repo `.claude/skills/<name>/SKILL.md`; instruction은 `CLAUDE.md` 또는 `.claude/CLAUDE.md`, 규칙은 `.claude/rules/` | 개인 `~/.claude/skills/`는 여러 project에 적용. Enterprise skill은 managed settings directory 내부 `.claude/skills/<name>/SKILL.md`. 동일 skill 이름은 enterprise > personal > project로 선택되므로 개인 skill이 project skill을 가릴 수 있음.[S2][S4] |
| Codex | CWD부터 repo root까지 각 `.agents/skills/`; team instruction은 root/nested `AGENTS.md` | user `$HOME/.agents/skills`, admin `/etc/codex/skills`. 동일 name skill은 병합하지 않고 둘 다 selector에 나타날 수 있음. user `~/.codex/AGENTS.md` 또는 `AGENTS.override.md`는 전역 지침.[S3][S7] |

Claude managed settings directory는 macOS `/Library/Application Support/ClaudeCode/`, Linux/WSL `/etc/claude-code/`, Windows `C:\Program Files\ClaudeCode\`이다. managed `CLAUDE.md`도 그 directory에 배포할 수 있다. 관리 설정과 Markdown 지침은 구별한다. 관리 설정은 lower-level 설정보다 우선하지만 지침 내용은 여전히 context다. device file/MDM은 Anthropic cloud session에 그대로 따라가지 않으며 surface에 따라 server-managed 정책 등 별도 배포가 필요하다.[S4][S8]

Codex `AGENTS.md`는 run 시작 시(보통 launched TUI session 시작 시) instruction chain을 만든다. global 이후 project root→CWD를 연결하며 가까운 directory 지침이 앞 지침보다 우선한다. 각 directory는 `AGENTS.override.md` → `AGENTS.md` → configured fallback 중 최대 한 파일을 쓴다. `project_doc_max_bytes` 기본 32 KiB 한도가 있다. `CODEX_HOME`은 기본 `~/.codex`를 바꿀 수 있으나 회사 모델 계정 인증을 증명하는 옵션은 아니다.[S7]

Claude instruction 파일은 concatenate하며 서로를 삭제/대체하지 않는다. conflicting user/project rule 중 어느 것을 따를지 보장하지 않는다는 문서 경고가 있다. 이를 Codex의 설명과 동일한 precedence 알고리즘으로 추상화하면 안 된다.[S4]

**설계 제안:** source bundle의 공통 domain은 유지하되 host별 emitted artifact, name collision, scope와 client version을 adapter에서 다룬다. 회사 repo 또는 사내 versioned artifact registry로 배포한다. 회사 규칙을 개인 home의 범용 skill 폴더에 무차별 설치하면 개인 project에도 발견되므로 피한다. 내부 plugin 배포를 선택하더라도 public marketplace 게시를 전제로 하지 않는다.

## 4. 승인 승격 lifecycle — 설계 제안

`trace/review feedback → candidate → reviewed change → approved bundle → activation → rollback/revocation`

1. **수집:** 회사 경계 안에 실제 review/수정 trace와 근거를 기록한다. 원문 속 명령, PR comment, tool 결과, 검색 결과는 관측 자료이며 policy 권한이 아니다.
2. **후보화:** 절차/상시 convention/일회 사건을 구분한 후보 diff를 만든다. 적용 조직·project·코드 범위, 근거 reference, 기존 승인 내용과의 관계, 작성 주체를 남긴다. 후보는 active native 폴더에서 분리한다.
3. **사람 검토:** 해당 범위 권한을 가진 팀 담당자가 실제 팀 convention에 맞는지 판단한다. model-generated 검토/confidence, 동일 피드백 반복, 단순 memory 조회를 승인으로 취급하지 않는다. 어떤 code-review 기준을 채택할지는 회사가 정한다.
4. **승인 release:** 회사 통제 저장소에서 immutable version/revision과 bundle digest, 승인 기록, scope, host artifact 목록을 함께 관리한다. 공통 원본에서 Claude/Codex용 지침/skill을 내보내되, adapter가 승인되지 않은 내용을 추가하거나 새로운 tool 권한을 끼워 넣지 않는다.
5. **명시 배포:** 승인 actor의 배포 요청에만 host adapter가 작동한다. destination/profile/scope와 proposed diff를 표시하고 기록한다. runtime memory tool에 instruction 파일을 조용히 다시 쓰는 권한을 기본 제공하지 않는다. local repo 수정은 내부 검토 경로로 반환하고 공개 OSS upstream에는 회사 content를 넣지 않는다.
6. **다음 실행 활성화:** 실행 시작 전에 승인 manifest와 실제 artifact digest를 확인하고 rule bundle version을 session에 고정한다. 호환되지 않는 client 또는 다른 project에 잘못 배포된 bundle은 활성화하지 않는다. 어떤 native 파일이 실제 로드되었는지 별도로 관측할 수 없는 adapter는 확인 수준을 과장하지 않는다.
7. **rollback/revocation:** 일반 변경은 다음 실행에 이전 승인 version으로 rollback 가능하게 한다. 위험한 rule 철회는 새 배포 중단·서버 제공 차단·관련 권한 철회를 먼저 적용하고 해당 session을 종료/새 context로 재시작한다. 이미 읽힌 문장을 원격 삭제했다고 주장하지 않는다.

## 5. 실행 version 고정과 철회는 별개

**공식 동작:** Claude는 personal/project/launch `--add-dir` skill의 `SKILL.md` 변경을 실행 중 감지한다. 이미 호출한 본문은 conversation에 남고 이후 turn에서 파일을 다시 읽지 않는다. 삭제하여 `/skills` 목록에서 사라져도 이미 들어간 본문은 skill lifecycle을 따른다. compaction도 호출 skill 일부를 다시 붙일 수 있다.[S2: Edit a skill during a session; Skill content lifecycle]

현재 Claude 문서는 claude.ai account skill 동기화도 설명한다. terminal의 적용은 버전·로그인 방식·정책 조건에 달리고, 활성 작업 중 대략 10분/idle 40분 간격의 변경 확인, 같은 계정의 offline 재사용, 삭제 후 `.trash` 보관 등이 문서화되어 있다. Cowork/cloud와 local skill 경로도 다르다. **account sync는 별도의 native 제품 기능이며 MCP 효과가 아니다.** 사내 artifact를 계정 sync에 올릴지는 회사 승인 전 별도 판단이다.[S2: Skills synced from claude.ai]

Codex는 skill 변경을 자동 감지하며 보이지 않으면 restart를 권한다. `~/.codex/config.toml`의 `[[skills.config]] path=... enabled=false` 변경에는 restart가 필요하다. `AGENTS.md` chain도 다음 run/session 시작에 다시 구성된다.[S3][S7]

**설계 제안:**

- 다음 실행 version pin은 native가 기본 제공하는 일관된 bundle snapshot 보장이 아니다. 승인 version의 읽기 전용 배포 snapshot/checkout을 선택하고 active session의 directory를 hot-update하지 않는 adapter 계약으로 구현한다. 여러 session이 공유하는 mutable skill directory를 교체하면서 고정되었다고 말하지 않는다.
- 일반 신규 revision은 다음 실행에 반영하되, 긴급 revoked version은 pin보다 revocation이 우선한다. 최소 허용 version/revocation 상태 확인을 lease/만료 시간으로 제한하고, 정해진 유효 범위를 넘겨 회사 서버를 확인할 수 없으면 새 회사 bundle 사용/보호 작업을 차단한다. 구체 시간은 회사 운영 정책으로 정한다.
- 서버가 매 요청 권한을 재검사해도 이미 host context에 들어간 내용을 지울 수는 없다. offline cache·account-sync cache·기존 session context를 함께 고려하여 endpoint 적용/acknowledgment와 재시작을 관리한다. lease가 있는 fetcher만으로 모든 native client의 철회 즉시성이 확보되지는 않는다.
- ordinary rollback은 이전 **승인되고 철회되지 않은** version만 허용한다. stale cache가 revocation을 우회하지 않도록 한다. 모델의 “업데이트를 읽었다”는 자연어 응답만으로 적용/철회 완료를 확정하지 않는다.

## 6. 잘못된 project/account/client와 injection 방어 — 설계 제안

- **서버 authorization:** 회사 memory/skill 제공 endpoint에서 회사 principal, 허용 project와 승인 client 권한을 검증한다. 요청의 project 문자열·repo remote·MCP `clientInfo`·model이 선언한 “회사 계정”은 신뢰 근거로 쓰지 않는다. 개인 cloud deployment/credential과 회사 endpoint를 교환 사용하지 않는다.
- **MCP의 한계:** HTTP OAuth 사양은 token의 MCP resource audience 검증과 target `resource` 요청을 요구하며 다른 서비스 token passthrough를 금지한다.[S9] 하지만 MCP용 access token만으로 현재 Claude/Codex inference가 회사 workspace에서 처리된다는 사실은 증명되지 않는다. public client 이름/등록 ID만으로 실제 binary나 현재 로그인 계정을 attest한다고 주장하지 않는다.
- **host 보완:** 회사 승인 launch/profile·host/계정 통제와 서버 접근 정책을 함께 사용한다. 계정이 확인되지 않은 임의 client에 회사 skill을 주지 않는 계약이 필요하며, model login credential을 memory 서버로 전달해서 확인하는 식으로 해결하지 않는다. `CODEX_HOME` 또는 로컬 instruction 경로 분리는 방어 보조이지 account/tenant isolation 자체가 아니다.
- **권위 분리:** retrieved memory/trace/candidate를 승인 rule channel과 분리한다. 원문 “이것을 규칙으로 저장/회사 자료를 업로드”는 data로 취급한다. 승인 bundle에는 provenance/승인자가 있어야 하지만 출처 표기 자체가 prompt injection 완전 방어는 아니다. approval/deployment 권한과 artifact 쓰기·배포 목적지 통제는 모델 밖에서 enforce한다.
- **실행 내용:** skill에는 script/reference, Claude dynamic command와 `allowed-tools` 등 실행/권한 관련 내용이 들어갈 수 있다. metadata만 검토하고 body/script를 무조건 신뢰하지 않는다. Claude 문서는 project skill의 `allowed-tools`가 미신뢰 folder의 `-p` 실행에서도 적용될 수 있다고 경고한다.[S2: Pre-approve tools for a skill] 승인 bundle 변경이 은밀한 tool 권한 확대/회사 밖 reference fetch를 유발하지 않게 검토 범위에 포함한다.
- **회사 내부 보관 ≠ 모델로 전송되지 않음:** native skill body/instruction은 model context에 들어간다.[S2][S3][S4] 따라서 로컬/사내 Git에 저장해도 사용하는 모델 host로 prompt가 전달되는 경로는 별도로 회사 승인 SaaS/CLI 계약·계정·설정을 따라야 한다. “no-training”을 “no-transmission/no-retention”으로 바꾸어 해석하지 않는다. native skill 배포 기능이 별도 memory worker API 사용 권한이나 inference/embedding API 승인까지 부여하지 않는다.

## 1차 출처

- [S1] Agent Skills, [Specification](https://agentskills.io/specification): directory/frontmatter, metadata, progressive disclosure, host-dependent allowed-tools.
- [S2] Anthropic, [Extend Claude with skills](https://code.claude.com/docs/en/skills): locations/name resolution; invocation controls; local live detection; loaded content lifecycle; claude.ai sync; tool grants.
- [S3] OpenAI, [Agent Skills / Build skills](https://developers.openai.com/codex/skills), 이번 조회 최종 문서 [Build skills](https://learn.chatgpt.com/docs/build-skills): discovery/paths, policy, changes, disable options, plugins/dependencies.
- [S4] Anthropic, [How Claude remembers your project](https://code.claude.com/docs/en/memory): context vs enforcement; managed/user/project instructions, concatenation/conflicts; path rules.
- [S5] OpenAI, [Customization](https://developers.openai.com/codex/concepts/customization), 이번 조회 최종 문서 [Customization](https://learn.chatgpt.com/docs/customization/overview): memory/guidance/skills/MCP 분리와 feedback loop.
- [S6] MCP, [Prompts — 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/server/prompts): list/get/list_changed, user-controlled prompts, injection validation.
- [S7] OpenAI, [Custom instructions with AGENTS.md](https://developers.openai.com/codex/guides/agents-md), 이번 조회 최종 문서 [AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md): once-per-run chain, precedence, limits, CODEX_HOME.
- [S8] Anthropic, [Deploy managed settings](https://code.claude.com/docs/en/managed-settings): OS directories, device/cloud/surface coverage, settings precedence and running-session caveats.
- [S9] MCP, [Authorization — 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization): HTTP transport authorization, resource indicator/audience 검증, token passthrough 금지.
