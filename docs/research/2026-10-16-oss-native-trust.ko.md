# Claude·Codex 신뢰 경계와 참고 OSS — 2026-10-16

## 조사 범위와 증거 수준

사용자는 휴대폰에서 작업 중이며, `claude-mem`과 이슈에서 참고한 OSS가 Claude Code/Codex 신뢰·설치·승인을 어떻게 처리하는지 확인해 달라고 요청했다. 기존 [86개 후보 조사](2026-10-15-oss-local-runtime.ko.md)의 범위를 재사용한다. 86은 고유한 native host 통합 제품 수가 아니며, alias·이전/폐기 wrapper·SDK·벤치마크·발표·카탈로그도 포함한다.

upstream은 고정 source와 공식 문서·이슈/PR 상태를 조사했다. upstream 설치 프로그램·벤치·메모리 서비스를 실행하지 않았고 코드를 복사하거나 의존성을 추가하지 않았다. 우리 환경에서 실행한 native metadata 관측과 upstream source 사실은 아래에서 구분한다. 이번 조사는 workspace/hook trust·permissions·managed 설정을 변경하거나 원격 제어 서버를 여는 승인이 아니다.

## 하나의 trust가 아니라 독립된 네 경계

| 경계 | 승인하는 대상 | 대체하지 못하는 것 |
|---|---|---|
| workspace/project trust | 해당 폴더의 설정·자동 실행 코드 로드. Git 하위 폴더에서 시작해도 저장소 root가 대상일 수 있음 | 개별 hook 정의 검토, MCP 도구 승인, corpus 저장/egress 허가 |
| plugin 설치·enable | bundle의 발견·설치·활성화와 지원되는 host scope | Codex non-managed hook의 현재 정의 hash 신뢰, 실제 callback 실행 |
| hook trust·enable | Codex의 개별 source/event/index key와 현재 정규화된 handler 정의 hash, 별도의 enabled 상태 | 실행 파일 bytes 무결성, 일회성/한 turn 승인, 후속 모델의 실제 기억 소비 |
| MCP 등록·도구 권한 | 서버 연결과 선택한 MCP 도구 실행 | project hook 활성, 첫 파일 변경 차단, Jev 외부 전송 허가 |

근거: [Codex hooks](https://developers.openai.com/codex/hooks/), [Codex plugins](https://developers.openai.com/codex/plugins/), [Claude security](https://code.claude.com/docs/en/security), [Claude MCP scope/approval](https://code.claude.com/docs/en/mcp#project-server-approvals-and-workspace-trust).

## Codex 0.162.1: TUI 전용이라는 설명 정정

**“데스크톱 TUI에서만 기술적으로 신뢰를 저장할 수 있다”는 결론은 틀리다.** native TUI도 공개된 범용 `config/batchWrite` app-server API를 사용한다. 다만 별도 동의 검증·일회성 승인 RPC가 있는 것은 아니다. 다음은 pinned `rust-v0.162.1` source 사실이며, write RPC를 실행한 결과가 아니다.

| 정상 native 동작 | source 사실·범위 |
|---|---|
| 폴더 상태 조회 | [`config/read` + `includeLayers` + cwd](https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/tui/src/config_update.rs#L198-L394)로 effective layer와 disabled reason, 실제 trust target을 해석한다. cwd 문자열만으로 승인 대상을 정하지 않는다. |
| 폴더 동의 | [화면](https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/tui/src/onboarding/trust_directory.rs#L61-L151)은 자동 코드 실행·신뢰 저장·저장소 root 범위를 고지한다. [지속화](https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/tui/src/onboarding/onboarding_screen.rs#L767-L838)는 user config의 해당 `projects.<resolved target>.trust_level`을 범용 API로 변경한다. 한 명령/한 turn 승인이 아니다. |
| 개별 hook 검토 | [`/hooks` handler 화면](https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/tui/src/bottom_pane/hooks_browser_view.rs#L243-L276)이 선택한 key/current hash를 전달한다. event overview의 trust-all과 구별해야 한다. |
| hook 신뢰 저장 | [`write_hook_trusts`](https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/tui/src/hooks_rpc.rs#L58-L100)는 `hooks.state`에 선택한 key의 `trusted_hash`만 sparse `upsert`한다. native helper는 `expectedVersion`을 지정하지 않는다. 신뢰 갱신은 `enabled=false`를 해제하지 않는다. |
| 실행 적격성 | [discovery](https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/hooks/src/engine/discovery.rs#L678-L823)는 project layer 로드와 handler enable/trust를 별도로 검사한다. plugin hook도 non-managed trust 대상이다. |
| API 결과의 한계 | [공개 schema](https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/app-server-protocol/src/protocol/v2/config.rs#L1098-L1136)와 [writer](https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/app-server/src/config_manager_service.rs#L218-L440)는 범용 설정 변경이다. `expectedVersion`은 user config version이지 hook-content CAS/사용자 동의 token이 아니다. `okOverridden`도 가능하므로 write 성공을 effective 승인으로 바꾸지 않는다. |

검토한 [공개 request 목록](https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/app-server-protocol/src/protocol/common.rs#L891-L895)·[설정 methods](https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/app-server-protocol/src/protocol/common.rs#L1418-L1454)와 [CLI subcommands](https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/cli/src/main.rs#L147-L244)에서는 전용 folder/hook consent RPC나 `codex hooks trust` CLI를 확인하지 못했다. 범용 API 사용 가능성과 사용자 검토가 있었다는 증명은 다르다. 사용자에게 정확한 지속 scope를 알리고 별도 UI에서 얻은 승인은 그 방식대로 기록해야 하며, native TUI 검토/인간 현존 증거로 포장하면 안 된다.

### hash가 보장하지 않는 것

[handler hash 구성](https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/hooks/src/engine/discovery.rs#L507-L635)·[정규화와 trust 판정](https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/hooks/src/engine/discovery.rs#L769-L823)은 event/matcher와 해당 handler 정의를 해시한다. 실행 script bytes·전이 의존성·MCP 서버 동작을 해시하지 않는다. 같은 command 경로의 script가 바뀌어도 이 정의 hash만으로 무결성을 입증할 수 없다. [state](https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/config/src/hook_config.rs#L19-L33)는 optional `enabled`/`trusted_hash`이며 expiry·실행 횟수·인간 서명이 없다.

## 휴대폰에서 가능한 것과 최초 bootstrap의 한계

| 방법 | 확인된 사실 | 현재 작업에 대한 판단 |
|---|---|---|
| Codex 공개 app-server 설정 API | native TUI와 같은 저장 mechanism. 로컬 stdio client로 사용 가능하며 원격 listener가 필수는 아님. [공식 API](https://developers.openai.com/codex/app-server/) | 기술적으로 headless 설정은 가능하다. 그러나 persistent folder trust와 exact hook trust를 별도 고지·검토해야 한다. 이번에는 호출하지 않았다. “전용 승인 API가 없다”를 “TUI 외에는 불가능”으로 확대하지 않는다. |
| Claude Remote Control | [공식 문서](https://code.claude.com/docs/en/remote-control)에 phone/web 연결·전달되는 permission prompt가 있다. 그러나 미신뢰 폴더에서는 연결 전에 local trust를 요구하고 비TTY이면 `Workspace not trusted`로 종료한다. `/plugin`도 local-only 명령에 속한다. | 이미 준비된 local session의 원격 사용 경로이지 미신뢰 폴더의 첫 승인 문제를 자동 해결하지 않는다. 세션 transcript는 Anthropic 서버에 저장되므로 별도 전송 경계를 검토해야 한다. 이번에는 켜지 않았다. |
| 웹/모바일 plugin 설치 | [Codex plugin 문서](https://developers.openai.com/codex/plugins/)는 web/mobile 설치가 local execution 환경에 hook script를 배포하지 않으며 hook 검토/신뢰가 별도라고 명시한다. | 모바일 catalog 설치를 이 Mac의 native hook 승인·실행 증거로 쓰지 않는다. |
| user/global plugin·hook 설치 | trusted project layer와 다른 설치 scope일 수 있다. | 전역 설치가 곧 trust bypass는 아니지만, 실행 범위가 넓어질 수 있다. 기존 project 격리·one-binding·명시 egress 계약을 유지해야 하며 승인 없이 현재 설치를 전역화하지 않는다. |

`approval_policy=never`, 개별 MCP `approval_mode`, sandbox mode, hook trust는 서로 다른 설정이다. 포괄 permission bypass·hook-trust bypass·managed 위장·기존 trusted user hook command에 다른 동작 끼워 넣기를 승인 대안으로 채택하지 않는다.

## 우리 환경의 실제 관측

- 실제 실행한 버전 metadata: Codex CLI `0.162.1`; 이번 조사에서 `claude --version`은 **2.1.300**을 반환했다. 이전 native 행동 smoke의 Claude 버전과 혼합하지 않는다. 버전 조회는 새 버전에서의 행동 smoke가 아니다.
- 사용자가 승인했다고 알린 뒤, 해당 합성 project의 정상 app-server `hooks/list`는 **trusted/enabled user hook 4개, project hook 0개**였다. `config/read`의 해당 project `.codex` layer는 trusted-project 등록을 요구하는 disabled reason을 반환했다. 이는 **현재 layer gating의 관측**이며, 과거 patch 실패의 유일 원인을 입증하지 않는다.
- metadata 증거: 공식 run `20261015-131245`의 `context/resume-codex-hook-status-post-user-approval.json`, `context/approved-codex-config-metadata.json`. private config 값·키·token은 공개하지 않았으며 설정/hook trust는 변경하지 않았다.
- 구독 Claude/Codex/OMP의 MCP 판단 성공은 native hook 보호 성공과 별개다. 이전 실제 Codex patch가 합성 파일을 변경한 실패는 그대로 유지한다. 신뢰 대상이 아직 inventory에 없는 상태에서 같은 무보호 patch를 반복하지 않았다.
- 메모리 core·adapter·런타임 코드는 이번 조사에서 변경하지 않았다. 기존 테스트 통과를 upstream 설치 검증이나 새 CLI 버전의 native 보호 증거로 확대하지 않는다. 실제 행동의 통과/실패는 [검증 기록](../verification.ko.md)을 따른다.

## claude-mem: 설치 자동화이지 native trust 자동 승인이 아님

현재 pin은 [`b8fc2ef9bab0dd1438d6cc8699c6884445ad409b`](https://github.com/thedotmack/claude-mem/tree/b8fc2ef9bab0dd1438d6cc8699c6884445ad409b), 이전 조사 pin은 `fef3402e674bebbf72a23aeb735e91c92cd34afd`다. 아래 설치 경로와 source 차이를 확인했으며 upstream 프로그램은 실행하지 않았다.

| 경로 | 실제 설치·설정 | 남는 trust/permission·실행 경계 |
|---|---|---|
| Claude Code | [npx installer](https://github.com/thedotmack/claude-mem/blob/b8fc2ef9bab0dd1438d6cc8699c6884445ad409b/src/npx-cli/commands/install.ts#L171-L217)가 marketplace/cache·user-scope installed plugin·`enabledPlugins`를 기록한다. [T3 경로](https://github.com/thedotmack/claude-mem/blob/b8fc2ef9bab0dd1438d6cc8699c6884445ad409b/src/services/integrations/T3CodeInstaller.ts#L229-L279)는 native `plugin install/enable --scope user`를 사용한다. | Codex와 같은 per-hook hash 승인 체계라고 일반화하지 않는다. [Claude 공식 보안 계약](https://code.claude.com/docs/en/plugins/security#understand-what-a-plugin-can-do)상 plugin hook·server 자체 코드는 user 권한/sandbox 밖에서 실행하고, 모델의 MCP tool 호출에는 별도 permission이 적용된다. plugin 설치 전 코드·scope 검토가 중요하다. |
| Codex | [writer](https://github.com/thedotmack/claude-mem/blob/b8fc2ef9bab0dd1438d6cc8699c6884445ad409b/src/services/integrations/CodexCliInstaller.ts#L455-L477)는 hooks feature·plugin enable과 소유 legacy MCP 정리를 수행한다. [실제 설치](https://github.com/thedotmack/claude-mem/blob/b8fc2ef9bab0dd1438d6cc8699c6884445ad409b/src/services/integrations/CodexCliInstaller.ts#L629-L690)는 native marketplace/plugin 등록 후 **여섯 hook을 검토·신뢰하고 이전 세션을 restart**하도록 안내한다. | 이 경로는 `projects.<path>.trust_level`이나 native `trusted_hash`를 기록하지 않는다. plugin enabled·worker healthy·MCP search 성공만으로 hook 실행을 보장하지 않는다. |
| T3 Code | [provider discovery](https://github.com/thedotmack/claude-mem/blob/b8fc2ef9bab0dd1438d6cc8699c6884445ad409b/src/services/integrations/T3CodeInstaller.ts#L49-L159)와 [connector](https://github.com/thedotmack/claude-mem/blob/b8fc2ef9bab0dd1438d6cc8699c6884445ad409b/src/services/integrations/T3CodeInstaller.ts#L229-L325)가 provider executable·native home에 설치한다. | [guide](https://github.com/thedotmack/claude-mem/blob/b8fc2ef9bab0dd1438d6cc8699c6884445ad409b/docs/public/t3code-integration.mdx#L7-L47)는 server machine 설치·restart/new thread·provider 정상 trust flow를 요구한다. UI가 prompt를 안 보여주면 같은 executable/`CODEX_HOME`의 terminal을 fallback으로 안내한다. connector 자체에 phone consent 전달/검증 구현이 있는 것은 아니다. |

### 이슈가 보여주는 설치 성공과 동작 성공의 차이

- [#3771](https://github.com/thedotmack/claude-mem/issues/3771): **worker 정상·plugin enabled·MCP search 가능인데 hook 미신뢰로 observation/summary가 없었다**는 사용자 보고다. 당시 Codex 0.147.0·다섯 hook이고 현재 pin의 여섯 event group과 구분한다. [#3773](https://github.com/thedotmack/claude-mem/pull/3773)의 merged 수정은 설치 후 수동 검토 안내이며 자동 trust 구현이 아니다.
- [#4520](https://github.com/thedotmack/claude-mem/pull/4520)의 merged T3 connector도 native trust를 provider 책임으로 남긴다. upstream의 isolated install 검증을 우리 Mac의 승인/실제 turn 성공으로 쓰지 않는다.
- **최신 상태 갱신:** 이전 조사 때 open이던 [#4766](https://github.com/thedotmack/claude-mem/pull/4766)·[#4771](https://github.com/thedotmack/claude-mem/pull/4771)은 2026-10-15 merged다. 각각 dependency 없는 host plugin root를 피하는 resolver와 Zod build 수정이다. trust 우회가 아니며, #4771 maintainer는 [committed worker 교체는 release rebuild 시점](https://github.com/thedotmack/claude-mem/pull/4771#issuecomment-6200199924)이라고 명시했다. source landed를 기존 설치 artifact의 복구 증거로 확대하지 않는다.
- 과거 [#2234](https://github.com/thedotmack/claude-mem/issues/2234)의 plugin disabled 후 기존 process 잔존 보고는 설정 변경과 프로세스 중지가 다르다는 사례다. 이 과거 보고만으로 현재 pin에도 같은 결함이 남았다고 주장하지 않는다.

### 그대로 복사하면 안 되는 설치 범위·상태 표시

- **[INFERENCE, source control-flow] 안내 유실:** [`bufferConsole`](https://github.com/thedotmack/claude-mem/blob/b8fc2ef9bab0dd1438d6cc8699c6884445ad409b/src/npx-cli/commands/install.ts#L113-L137)와 [Codex/T3 task 성공 분기](https://github.com/thedotmack/claude-mem/blob/b8fc2ef9bab0dd1438d6cc8699c6884445ad409b/src/npx-cli/commands/install.ts#L507-L537)는 interactive 성공 때 내부 안내를 버리고 generic OK만 반환할 수 있다. [일반 Next Steps](https://github.com/thedotmack/claude-mem/blob/b8fc2ef9bab0dd1438d6cc8699c6884445ad409b/src/npx-cli/commands/install.ts#L2983-L3010)도 trust를 보완하지 않는다. 이번에 UI로 재현하지 않았으므로 실행 결함 확정으로 쓰지 않는다.
- [공통 task 조건](https://github.com/thedotmack/claude-mem/blob/b8fc2ef9bab0dd1438d6cc8699c6884445ad409b/src/npx-cli/commands/install.ts#L2588-L2643)상 Codex/T3만 선택해도 기본 Claude home의 registry/plugin 설정을 만지는 경로가 있다. 우리 installer의 소유한 단일 project entry 변경 계약에 그대로 옮기지 않는다.
- standalone Codex installer의 `homedir()/.codex` 상수와 상속된 subprocess environment, T3의 명시 homePath는 [서로 다른 경로](https://github.com/thedotmack/claude-mem/blob/b8fc2ef9bab0dd1438d6cc8699c6884445ad409b/src/services/integrations/CodexCliInstaller.ts#L23-L30)다. custom `CODEX_HOME`을 항상 동일하게 처리한다고 일반화하지 않는다.

### read-gate·headless observer는 승인 대체물이 아님

현재 [file-context gate](https://github.com/thedotmack/claude-mem/blob/b8fc2ef9bab0dd1438d6cc8699c6884445ad409b/src/cli/handlers/file-context.ts#L260-L431)는 조건부 Claude full-file Read 효율 gate이며 실패 시 Read를 막지 않도록 설계돼 있다. 우리 필수 규칙의 fail-closed 집행과 다르다.

[Claude observer options](https://github.com/thedotmack/claude-mem/blob/b8fc2ef9bab0dd1438d6cc8699c6884445ad409b/src/sdk/hardened-options.ts#L178-L231)는 tool/MCP/settings 입력을 차단한다. [Codex observer](https://github.com/thedotmack/claude-mem/blob/b8fc2ef9bab0dd1438d6cc8699c6884445ad409b/src/services/worker/CodexAppServerClient.ts#L27-L83)는 hooks/plugins/shell 등 feature를 끄는 별도 격리 경로다. 이것은 native hook을 사용자 대신 승인하는 기능이 아니다. provider login 연결·모델 전송 허가도 native trust와 별개다.

## 나머지 참고 OSS와 채택 판단

[86행 상세 비교·전수 분류](2026-10-16-oss-native-trust-inventory.ko.md)에 각 pin·설치 source·관련 issue/merged PR·scope/egress 한계를 보존했다. 후보 열만 계산한 확인 결과는 **1–86 각각 한 번, 누락·중복 0**이다. 설명 열의 재인용 번호는 중복 후보가 아니다. 31개 entry는 설치/권한/evaluator 경로를 상세 조사했고, 나머지는 역할에 따른 triage 또는 별도 native-host 조사로 구분했다. 86개 제품을 실행·보안 감사했다는 의미가 아니다.

대조 결과를 우리 계약에 적용하면 다음과 같다.

1. **도구 자동 허용을 hook trust와 혼동하지 않는다.** doobidoo/mcp-memory-service의 [별도 opt-in](https://github.com/doobidoo/mcp-memory-service/blob/a2e53c6e76ad0a1b3e7861ca3d5012a5b301b96a/claude-hooks/install_hooks.py#L1671-L1707)은 다른 MCP 서버에도 영향을 준다. [#503](https://github.com/doobidoo/mcp-memory-service/issues/503)→[merged #504](https://github.com/doobidoo/mcp-memory-service/pull/504)는 이를 기본 No·전역 영향 경고로 바꿨다. 이름 기반 safe 목록에는 `store/remember/ingest`도 있다. 등록/출력 이벤트 불일치가 있어 이 pin의 실제 native allow 수용까지 입증하지 못했다. 우리에는 광역 자동 허용을 도입하지 않는다.
2. **설치 동의·추가 tool allowlist 동의·native trust를 나눈다.** Engram은 [별도 y/N](https://github.com/Gentleman-Programming/engram/blob/82846a101296e75351ae444953438cace88e9bea/cmd/engram/main.go#L3826-L3843) 뒤 선택한 agent-profile 도구를 user allowlist에 추가한다. Claude binder와 Codex binder의 allow 출력도 다르다. Basic Memory·agentmemory·OSK·context-mode는 설치 후 Codex hook 검토를 남긴다. 이들 패턴의 유용한 부분은 정확한 scope와 남은 승인 단계 표시이지 자동 승인 성공이라는 주장에 있지 않다.
3. **전역 설치와 corpus 격리를 따로 판단한다.** memU의 global instructions/session 수집, OpenKB의 default KB, OpenViking의 recall scope, Hindsight/Supermemory/Cognee hook의 직접 API 통신은 MCP tool prompt만으로 전체 capture·egress가 제한되지 않는 사례다. 우리 one-binding·독립 deployment·default-deny Jev·명시 저장/전송 허가·silent fallback 금지는 유지한다. 서버 교체나 global/default binding을 도입하지 않는다.
4. **생산과 evaluator의 bypass를 구분하되 어느 쪽도 승인 대안으로 복사하지 않는다.** agentmemory·Hindsight의 native fixture와 IWE Harbor는 bypass를 사용한 평가 경로가 있다. autoharness는 [생산 reflector argv](https://github.com/tigerless-labs/autoharness/blob/6bb7ea55aa6522c118ad4b7f317fce521399750f/src/autoharness/hook/spawn.py#L89-L108)에도 permission-skip을 쓴다. 후자를 단지 테스트용이라고 축소해서도 안 된다.
5. **Agent Flow 자체도 자동 trust를 해결해 주지 않는다.** pinned [broad trust 제거 코드](https://github.com/chonamdoo/agent-flow/blob/2fe8d3fe120b00dd501422ca3ea6cd6c6025a90c/lib/installer-shared.mjs#L3352-L3383)는 기존 user config의 해당 project `trust_level=\"trusted\"`를 제거하는 축소 동작이다. 이를 우리 현재 설치에서 실행하거나 기존 trust·guard·pin을 변경하지 않았다. 해당 source의 존재가 현재 metadata 원인이나 설치 이력의 증거도 아니다.

### 제안과 실제 적용 경계

**제안:** 자동 설치는 계속하되 결과를 `installed / layer active / hook trusted / hook enabled / callback observed / protected action denied`로 분리한다. 실제 provider executable·home·project·정의 hash·disabled reason을 확인하고, 승인 전에 열린 세션과 승인 후 새 세션을 구분한다. 설치 로그 안쪽의 “다음에 승인” 문구보다 최종 phone-readable 상태와 정확한 대상 표시가 중요하다. 이는 구현 제안이지 이번 조사에서 새 진단/승인 UI를 구현했다는 뜻이 아니다.

**폰 대응의 구현 후보:** 이미 존재하는 공개 Codex app-server API를 사용하는 별도 consent client라면 데스크톱 키 입력 없이도 지속 설정을 기록할 수 있다. 단, (a) 실제 resolved root와 계속 적용되는 folder trust를 고지하고, (b) 로드된 정확한 hook 정의/명령·key/hash를 따로 검토받고, (c) 다른 user hook·enabled=false·managed 정책을 보존하며, (d) version 충돌/override를 처리하고 fresh inventory와 실제 행동으로 확인해야 한다. 범용 API에는 인간 검토 증명·hook-source CAS가 없으므로 그런 보증을 붙이면 안 된다. 현재 조사에는 이 client 구현/설정 변경 승인이 없으며 실행하지 않았다.

**이번 실제 적용:** source-cited 조사 노트·이전 조사 후속 링크·검증 기록의 설명만 보완했다. upstream 설치·permission 확대·native trust 기록·전역 전환·외부 전송·제품 source 변경은 하지 않았다. normal native 활성과 실제 first-action/stop/recovery 보호, 이후 공식 review/QA/handoff 및 원래 publication gate는 여전히 미완료다. MCP-only 성공을 strict native 보호 성공으로 대신하지 않는다.

