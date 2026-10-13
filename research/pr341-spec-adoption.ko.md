# PR #341: 원래 명세 검토와 독립 메모리 제품의 채택 경계

## Spec — 원래 #334/#341 요구사항만 판정

**판정: 검토한 고정 diff에서 원래 명세에 대한 입증 가능한 누락·부분 구현·범위 확장·잘못된 구현은 찾지 못했다.** 이 판정은 아래의 새 root-free 요구에 적합하다는 뜻이나 Agent Flow 리뷰 승인·merge 승인이 아니다.

- [#334](https://github.com/chonamdoo/agent-flow/pull/334)는 “기존 Claude/Codex/Gemini 환경의 사용자 메모리를 선택적 참고로 활용하고, 유지할 가치가 있는 내용만 현재 근거를 확인해 팀 규칙 변경으로 제안”하며 “AI 요약을 사람의 교정 원문이나 승인 증거로 취급하지” 않도록 요구한다. 공통 skill의 두 추가 항목이 선택적 메모리, 현재 근거 재확인, 현재 프로젝트 규칙 우선, 별도 사용자 승인 변경을 명시한다.[S1]
- “승격 대상은 tracked `AGENTS.md`의 installer 관리 블록 밖 또는 tracked 프로젝트 skill”이라는 원래 요구는 skill 및 한·영 채택 문서에 반영됐다. 원문이 없으면 현재 근거로 새로 판단하되 과거 인간 교정으로 소급하지 않는다는 설명도 있다.[S1–S2] tracked 여부는 공유 의도와 파일 정체성의 근거이지 소비·준수의 증거가 아니다.
- “author의 `@AGENTS.md` import가 격리 reviewer에게도 전달을 보장한다는 잘못된 설명을 정정”하되 import와 opt-in 계약은 유지한다는 요구에 맞춰 생성 문구와 테스트 docstring을 정정했다. 기존 legacy 루트 포인터가 자동 갱신되지 않는 점은 문서가 의도적으로 공개한다. 실제 consumer인 참고 사본 생성과 provider별 reviewer 입력도 확인했다.[S2–S4]
- #334의 “별도 메모리 저장소·추출 모델·자동 주입·동기화는 추가하지 않습니다” 및 [#341](https://github.com/chonamdoo/agent-flow/pull/341)의 “새 기능·리팩터링·추가 문서는 넣지 않았습니다”에 맞춰 실행 함수·workflow·profile·gate·sandbox 변경은 없다. 원장 #333 보충도 #334 본문에 명시된 범위다. 명세가 자동 TTL, 메모리 엔진, Gemini reviewer, off/on 실험을 요구했다고 해석하지 않는다.

**새 요구와의 비호환은 별도 채택 판단이다.** tracked root `AGENTS.md` 승격, 모든 규칙의 팀 공유·Git 승인 전제, 배치만으로 코드 phase 전체에 붙는 기존 skill 동작은 새 로컬·공유·팀 범위 선택 및 root-free 요구에 그대로 복사할 수 없다. 이들은 원래 명세의 결함으로 보고하지 않는다.

## 검토 범위와 근거의 종류

비교는 base `1938aa191b169ac6fe9af80f7c1530d0e125a27a`에서 head `023b6ee427afaeff0e49d2db000e11e59b14c45f`까지의 고정 three-dot diff다. 변경 파일은 한·영 `TEAM-ADOPTION.md`, `lib/installer-shared.mjs`, 원장, 공통 skill, 기존 설치 테스트의 여섯 파일이다. 이하 resolver·routing·reviewer 코드는 **PR 이전부터 존재하던 통합 경계**다. 이를 #341이 새로 구현한 기능으로 셈하지 않는다.

원래 범위는 #334/#341 본문과 #316의 [최종 반영 판단](https://github.com/chonamdoo/agent-flow/issues/316#issuecomment-6105421905), [추가 리뷰](https://github.com/chonamdoo/agent-flow/issues/316#issuecomment-6105480938), [재리뷰 및 코드 반영 판정](https://github.com/chonamdoo/agent-flow/issues/316#issuecomment-6105568406)을 기준으로 했다. #316 최초 본문의 별도 분석 PoC 제안을 마지막 S0/S1 범위로 바꿔치기하지 않는다.

소스·diff·공개 PR 설명을 읽었으며 이 연구 작업에서는 installer, worker, Agent Flow run, build/lint/test/formatter, native model을 실행하지 않았다. PR 작성자가 보고한 CI·설치 관측과 모델 평가 부재는 작성자 보고로 구분한다. 코드의 가능한 경로, 실제 설치된 host/CLI의 동작, 모델의 지침 준수는 다른 증거다. 소스 링크의 행 번호는 Git blob/로컬 원문 기준이다. URL reader가 Python/JS 빈 줄을 정규화해 표시한 행 번호는 인용 기준으로 사용하지 않았다.

## 1. 재사용할 원칙: 메모리 사실과 규칙의 권위를 분리한다

원래 PR에서 재사용 가치가 큰 부분은 저장 기술이 아니라 **재확인·승인·출처를 구분하는 기준**이다.[S1–S2]

1. 기억은 조사 진입점이다. 연결 파일·branch·도구/API·팀 결정이 바뀌거나 현재 작업과 충돌하면 직접 근거를 다시 확인한다. 한 작업/branch의 사실을 팀 공통 규칙으로 넓히지 않는다.
2. 반복 횟수와 쉽게 읽을 수 있는 코드 사실만으로 규칙을 승격하지 않는다. 반복 조사는 후보 발견 신호이며 진실·영구 보존 가치의 증명이 아니다. 재사용 이유, 조건·예외, 현재 근거, 유지 비용을 함께 판단한다.
3. 인간 원문, AI 추출/요약, 검토자의 승인 기록을 분리한다. 사람이 AI 요약을 승인해도 요약의 출처가 인간 원문으로 바뀌지는 않는다. 원문이 없어도 현재 근거로 새 제안을 검토할 수 있지만 “과거 사람이 이렇게 교정했다”는 권위를 만들 수 없다.
4. 참고 memory, 활성 규칙, 적용 절차인 skill은 서로 다른 상태다. 과거 리뷰 의견·model confidence·파일 설치·Git commit은 자동 활성화나 범위 확대 승인으로 쓰지 않는다. 제안한 규칙이 자기 채택을 승인하거나 기존 검증을 완화해서는 안 된다.
5. 승인 파일 → 선택된 자료 → 렌더링된 입력 → 제출 입력 → 실제 소비/행동의 증거를 구분한다. 관측하지 않은 단계는 `unknown`이다. 이 PR은 새 schema·journal·mandatory gate를 추가한 것이 아니라 주장 가능한 범위를 제한한 것이다.[S2]

**[채택 제안]** 독립 제품에서는 tracked 파일 변경을 모든 사용자에게 강제하지 않는다. 새 규칙/skill 활성화 또는 범위 변경에만 **내 로컬·해당 프로젝트 / 프로젝트 공유 / 팀 공통**을 명시적으로 선택하게 하고, 동일 항목의 내용 갱신은 기존 범위를 유지한다. 로컬은 본인의 승인 정책을 따르며 팀 승인·commit·push를 요구하지 않는다. 공유/팀 공통은 해당 범위의 권한자 승인을 별도로 요구한다. 범위 선택은 게시 승인·회사 반출 허가·필수 회사 정책 면제가 아니다. 이 수명주기는 #341에 구현돼 있지 않다.

## 2. installer의 실제 root 경계: 참고 사본과 시작 입력은 다르다

`CLAUDE_POINTER_LINES`/`rootBootstrapBlock()`은 `@AGENTS.md`를 유지하면서 “for the Claude author session”과 reviewer 전달 한계를 명시한다.[S3] 그러나 이것을 “#341 설치가 모든 author/reviewer에게 root 규칙을 자동 전달한다”로 읽으면 틀린다.

- 실제 kit installer는 `.agent-flow/bootstrap/AGENTS.md`와 `.agent-flow/bootstrap/CLAUDE.md`에 참고 사본을 쓴다. `managedBootstrapMarkdown()`은 같은 `rootBootstrapBlock()` 출력을 사용하며 관리 마커·인덱스 자리를 제거한다. 사본 위치 자체는 session-start instruction root가 아니다.[S4]
- `rootContextPolicy()`는 새 설치의 opt-in, 기존 legacy, 소유권 불명 preserve를 구분한다. kit installer의 legacy branch는 소유권이 증명된 루트의 기존 인덱스를 갱신한다. root 포인터 본문을 일괄 새 문구로 교체하는 변경은 이번 PR에 없다.[S3–S4]
- 참고 사본을 사용자가 루트 `CLAUDE.md`로 채택하면 그 파일 옆의 `AGENTS.md`를 import하게 된다. import는 본문 중복을 없애지만, importer가 로드되는 author 세션에서 `AGENTS.md`의 내용까지 불러온다는 계약이다. **root 컨텍스트 누적을 조건부 로딩으로 해결한 것은 아니다.**[S2–S3]
- 기존 `migrateRootContext()`도 완전한 root-free 변환기가 아니다. 소유권이 증명된 관리 블록을 변환하면서 Context Economy/인덱스와 Claude의 `@...` import 줄을 보존한다. 따라서 “migration 플래그를 쓰면 root 규칙·참조가 전부 사라진다”고 보장할 수 없다. 이 경로는 원래 PR의 버그가 아니라 새 요구에 대한 비호환이다.[S3]

**실용적 영향:** 독립 메모리 제품은 root 포인터·root index를 자신의 발견/활성화 계약으로 복사하지 않는 편이 맞다. 이미 존재하는 사용자 root 파일도 이 연구나 제품 설치가 임의 정리할 대상은 아니다. 승인된 규칙의 정본은 root 밖에 두고, 활성 범위와 작업에 필요한 자료만 명시적인 소비 경계에서 고른다는 별도 설계가 필요하다. “파일을 옮겼다”와 “호스트의 시작 입력에서 빠졌다”는 각각 확인해야 한다.

## 3. root 밖에 skill을 놓아도 작업별로 좁혀지는 것은 아니다

### 배치와 공유 범위

`_DEFAULT_PROJECT_TEMPLATES`는 개인 `.agent-flow/local-skills/{skill}/SKILL.md`, 프로젝트 `skills/{skill}/SKILL.md`, bundled `.agent-flow/skills/`, vendor `.claude/skills/`·`.agents/skills/`를 구분한다.[S5] 첫 두 위치는 프로젝트 소유 **배치 자체가 적용 선언**이다. `_catalog_entry()`가 phase 미선언을 `CODE_PHASES`로 채우고 `entry_can_activate()`/`entry_activation()`이 placement source를 허용한다. frontmatter 없는 파일도 코드 생성·리뷰 단계 전체에 required로 붙을 수 있다.[S5–S6]

따라서 `.agent-flow/local-skills/`로 이동하는 것만으로 과잉 컨텍스트가 사라지지 않는다. 개인/공유 저장 범위와 작업별 로딩 범위는 별도 축이다. 보통 프로젝트의 `skills/`는 공유할 수 있는 정본이고 `.agent-flow/local-skills/`는 working-copy 로컬이다. **주의:** `skill_roots()`는 Agent Flow kit 소스 checkout의 `skills/`를 `bundled`로 재분류하는 예외도 갖는다. 일반 소비 프로젝트와 kit 개발 checkout을 동일 fixture처럼 취급해서는 안 된다.[S5]

### selector의 실제 강제 수준

| 경로 | 확인한 동작 | 독립 제품으로 가져올 때의 주의점 |
|---|---|---|
| 프로젝트 소유 skill의 `pathGlobs` | phase와 glob이 맞으면 activation을 만들고 resolver가 required에 넣는다 | 경로의 의미는 해당 matcher 구현 기준이다. glob 문자열이 같다고 host별 의미가 같지는 않다. |
| 프로젝트 소유/bundled skill의 `taskTerms` | `OWNED_SOURCES` 예외에 따라 required가 될 수 있다 | “자유 task 문구는 언제나 optional”로 일반화하면 안 된다. |
| `profile_routing.routed_profile_skills()` | 활성 profile 그룹의 path/task/concern selector 결과를 required에 합친다. selector 없는 그룹은 `_group_skills()`에서 비활성 | profile 선언과 실제 source phase allowlist가 계약이다. description/`when` 문장만으로 라우팅되지 않는다. |
| 외부 host/shared/fetched/vendor skill의 어휘 매칭 | `match_external()`은 domain/skill 어휘를 맞추며 task/path만으로는 offered. 활성 domain의 명시적 concern 또는 pin이 required를 만들 수 있다 | concern/pin도 required 수·byte budget으로 offered에 내려갈 수 있다. 필수 회사 정책의 누락 없는 공급 계약과 동일시하면 안 된다. |

근거는 resolver의 `resolve_phase_skills()` L626–710 및 `OWNED_SOURCES`/activation L1468–1534, profile routing L72–109·L150–218, external matching L100–173·L208–306이다.[S6–S8] selectors는 OR 매칭이다. `pathGlobs`와 `taskTerms`를 함께 적었다고 둘 다 일치해야 하는 계약은 아니다.

**부모 작업에서 전달받은 실제 관측:** `pathGlobs=['src/server/**/*.py']`와 직접 자식 `src/server/request.py` 조합은 `entry_activation()`이 `None`을 반환했다. `_glob_matches()`는 `fnmatchcase`를 사용하고 leading `**/`에 대해서만 zero-depth 대안을 추가한다. 내부 `/**/`의 zero-directory 해석을 보장하지 않는다.[S6] 이 관측은 작은 실제 selector 경계의 증거이며 full resolver·installer·host·model 검증은 아니다. PR 이전부터 있던 matcher를 이번 patch defect로 보고하거나 실패를 다시 실행해 지우지 않는다.

`local_skills.phase_skill_paths()`는 구현 phase에서 변경 파일과 slice-plan의 예상 파일을 합치고 `phase_skill_resolution()`이 같은 resolver로 전달한다.[S9] 아직 변경되지 않은 파일의 규칙을 미리 선택하는 구조는 참고할 수 있지만, Agent Flow plan/artifact/phase 계약을 독립 제품의 필수 형식으로 가져올 이유는 없다.

## 4. reviewer 전달: root import와 별도 provider 입력을 연결하지 않는다

producer뿐 아니라 consumer도 확인했다. `_reviewer_jobs()`는 provider별 `adapter.phase_resolution()`을 실행하고 `role='reviewer'`로 envelope를 렌더링해 `ReviewerJob.prompt_by_provider`에 넣는다. `distribute()`/`_reviewer_job_for_cli()`가 배정 provider의 prompt를 선택하며 `run_distribution()`은 그것을 CLI argv로 전달한다.[S10–S11] 따라서 reviewer에 필요한 규칙은 author root import가 아니라 **해당 provider가 해석한 reviewer 입력**에서 확인해야 한다.

다만 일반 required skill 본문이 전부 prompt 안에 자동 삽입된다는 뜻도 아니다. resolver는 일반 skill을 `NormativeDocument(inline=False)`로 캡처하고 `skill_prompt_block()`은 required-read plan의 경로·digest를 렌더링한다. 선택된 architecture root/참조는 inline 전달될 수 있다. 일반 skill은 reviewer가 그 파일을 실제 읽는 단계가 남는다.[S12] source capture/hash/required-read instruction을 model consumption으로 합치지 않는다.

`_run_multi_review_distribution()`은 provider 결과로 deliverable/document 기록을 남기며 유효 reviewer 산출물이 있어야 skill 적용 기록을 준다. 이는 runner가 인정하는 전달/산출물 조건이지 문장별 의미 준수의 증명은 아니다.[S10] author의 일반 read gate는 자기신고이고 hook 관측은 진단에 쓰인다. controller의 독립 reviewer 전달 조건은 별도다.[S9, S12]

격리 경계도 역할별이다. Claude argv에는 `--safe-mode --permission-mode plan --no-session-persistence`, Codex에는 `--ephemeral --ignore-user-config`와 scratch `CODEX_HOME`이 쓰인다.[S11, S13] 사용자 메모리 격리를 관측 편의 때문에 해제해서는 안 된다. 그렇지만 worktree에 놓인 프로젝트 `AGENTS.md`의 영향까지 제거됐다는 증거는 아니며 이 점은 PR 문서가 미해결로 공개한다.[S2] 사용자 memory는 원래 reviewer에 자동 전달하는 대상이 아니다.

## 5. Agent Flow 사용자와 독립 사용자에게 서로 다른 채택 경계를 둔다

| 대상 | 재사용 가능한 경계 | 그대로 가져오지 않을 부분 | 적용 영향 |
|---|---|---|---|
| Agent Flow 코드 작업 | 기존 profile/phase/changed-file resolver와 reviewer envelope의 제한된 소비 경계 | 별도 memory가 workflow 선택, runner routes, gates, review sealing을 대신하는 구조 | 기억은 참고 근거다. 규칙 변경은 해당 accepted task·기존 검토 권한을 따른다. |
| Agent Flow 없이 Claude/Codex/다른 host를 쓰는 사용자 | 근거 재확인·범위 선택·출처/승인 구분, 작업별 규칙 공급, 짧은 discovery와 필요 본문 분리라는 원칙 | `agent-flow` 설치·`.agent-flow` 디렉터리·CODE_PHASES·Completion Gate markers·worktree/runner·reviewer CLI pool | 독립 서비스/host adapter가 실제 로딩 표면과 권한을 구현·검증해야 한다. 파일 이름만 복사해 자동 적용을 약속할 수 없다. |
| 개인 로컬 사용자 | 본인 소유 규칙과 프로젝트-local 활성 범위 | 모든 변경의 tracked Git PR·팀 승인 강제 | commit/push 없이 로컬 활성화가 가능해야 한다. 범위 확대는 다시 선택/승인한다. |
| 프로젝트 공유·팀 공통 | 승인된 정본과 버전·조건·권한자 기록 | root 파일 누적, 단일 프로젝트 `skills/` 배치를 팀 전체 배포로 간주 | 활성 scope의 승인 규칙 집합을 결정적으로 선택하는 별도 배포/소비 계약이 필요하다. |

**[설계 제안]** 공통 OSS 도메인·API를 쓰되 회사와 개인의 memory/backup/rule 배포는 분리한다. 회사 승인 업무용 Claude/Codex 추론을 허용하는 전제와 회사 memory를 개인 cloud에 복사하는 권한은 다르다. 회사 정책에 의해 필수인 규칙은 개인-local 선택으로 완화하지 못한다. semantic 검색은 참고 memory/후보 발견에 쓰고, 필수 규칙은 활성 project/team/path/version과 승인 상태로 결정적으로 선택한다. 이는 #341이 구현한 기능도 MCP 인증만으로 달성한 권한 보장도 아니다.

코드 재사용 후보는 `selector_matches`/경로 매칭, typed selection 결과와 route 이유 보존, 동일 본문 deduplication, 역할별 delivery 구분처럼 책임이 분명한 작은 경계다.[S6, S12] 그러나 현재 Python 모듈은 architecture snapshots, 설치 완전성, profiles, workflow phases에 결합돼 있다. 독립 서비스에서 무조건 import/copy하면 Agent Flow 설치와 런 수명주기까지 의존하게 된다. 재사용 전 실제 소비자가 요구하는 작은 계약을 식별해야 하며 이 연구에서는 추출·리팩터링하지 않았다.

또한 `_catalog_entry()`의 `owner`/`approval`/`provenance` 메타데이터 존재를 제품 권한 검증으로 읽지 않는다. 여기서 검토한 activation 함수는 placement·phase·selectors를 판단하며 승인자의 신원·팀 권한을 검증하지 않는다.[S6] 같은 이름의 개인 skill이 프로젝트 skill보다 먼저 해결되는 기존 우선순위도 회사 필수 정책보다 개인 규칙을 우선한다는 새 제품의 보안 계약으로 복사할 수 없다.[S5]

## 6. 구현과 증거의 한계

- **이 PR은 메모리 엔진을 구현하지 않는다.** 여섯 파일 diff에는 수집·추출·검색·versioned approval·forget/revoke·동기화·자동 주입의 새 실행 경로가 없다. 기존 host memory를 선택적으로 참고할 때의 지침과 팀 규칙 변경 제안 기준이다. 기존 저장소의 다른 memory 검사 표면까지 완성된 엔진이라고 판정한 것은 아니다.
- **macOS 한계는 현재 Agent Flow reviewer backend의 한계다.** `verify_provider_sandbox_backend()`는 Darwin과 신뢰된 `/usr/bin/sandbox-exec`를 요구한다. 현재 CLI/home/sandbox 조건을 만족하지 못하면 Agent Flow 독립 리뷰는 차단된다.[S13] 이것을 독립 memory service가 Linux/Windows에서 동작할 수 없다는 보편 제품 한계로 확대하지 않는다. 반대로 macOS라는 사실만으로 reviewer 실행·승인을 보장하지 않는다.
- **Gemini/OMP author와 reviewer pool을 구분한다.** 다른 host의 phase prompt 사용 가능성을 해당 host가 Agent Flow 독립 reviewer로 지원된다는 뜻으로 쓰지 않는다.[S2, S11]
- **610 bytes·약 0.86%는 #341 작성자가 보고한 결정적 입력량 증가다.** token 절감이나 기억 정확도·오류 감소·규칙 준수 개선 실측이 아니다. 이전 Linux run의 reviewer 증거 공백을 CI 통과나 이 정적 연구로 대체하지 않는다.
- **root-free의 반론:** 매번 모델이 선택해서 읽는 방식은 읽지 않는 누락 경로가 있다. 그래서 필수 규칙까지 optional 어휘 검색에 맡기는 설계는 적합하지 않다. 필요한 공통 규칙을 항상 선택해야 하는 작업도 있을 수 있다. 새 요구는 필수 정책을 없애는 것이 아니라 root 시작 입력에 모든 본문을 누적하지 않는 것이다. 어떤 host가 선택된 규칙을 언제 제출하는지는 지원 표면별 실제 검증 대상이다.
- **현행 팀 팩의 한계:** `TEAM-ADOPTION`은 kit와 소비 repo에서 독립적으로 버전·리뷰·pin을 관리하는 팀 convention pack을 미구현으로 표시한다.[S14] 현재 project-local/source placement만으로 새 team-common 배포·승인 수명주기가 이미 해결됐다고 주장할 수 없다.

부모 통합 검증이 확인할 경계는 직접 자식/중첩 glob 포함·제외, placement defaults, owned taskTerms와 외부 offered의 차이, provider별 reviewer read-plan/inline 구분, root와 bootstrap 참고 사본의 차이다. 작은 synthetic selector 관측은 이 중 실행한 함수·fixture만 입증하며 실제 host 소비·회사 접근 통제·모델 행동은 별도의 증거가 필요하다.

## 고정 소스

모든 blob 링크는 head `023b6ee427afaeff0e49d2db000e11e59b14c45f`로 고정했다. PR 범위에서 변경되지 않은 runtime 파일은 baseline 경계로 인용한다.

- [S1: `skills/code-generation-discipline/SKILL.md` L13–20](https://github.com/chonamdoo/agent-flow/blob/023b6ee427afaeff0e49d2db000e11e59b14c45f/skills/code-generation-discipline/SKILL.md#L13-L20): 두 추가 메모리 원칙. 나머지 공통 skill은 Agent Flow phase/markers에 결합돼 있으므로 wholesale 채택 대상이 아니다.
- [S2: `docs/TEAM-ADOPTION.md` L103–186](https://github.com/chonamdoo/agent-flow/blob/023b6ee427afaeff0e49d2db000e11e59b14c45f/docs/TEAM-ADOPTION.md#L103-L186), [한국어 L95–174](https://github.com/chonamdoo/agent-flow/blob/023b6ee427afaeff0e49d2db000e11e59b14c45f/docs/ko/TEAM-ADOPTION.md#L95-L174): root/참고 사본, 출처·승인·freshness·관측 한계.
- [S3: `lib/installer-shared.mjs` L1723–1747](https://github.com/chonamdoo/agent-flow/blob/023b6ee427afaeff0e49d2db000e11e59b14c45f/lib/installer-shared.mjs#L1723-L1747), [`rootContextPolicy` L3796–3812와 `migrateRootContext` L3814–3884](https://github.com/chonamdoo/agent-flow/blob/023b6ee427afaeff0e49d2db000e11e59b14c45f/lib/installer-shared.mjs#L3796-L3884): 실제 포인터 및 보존/migration 경계.
- [S4: `bin/agent-flow-kit.mjs` L339–365](https://github.com/chonamdoo/agent-flow/blob/023b6ee427afaeff0e49d2db000e11e59b14c45f/bin/agent-flow-kit.mjs#L339-L365), [`managedBootstrapMarkdown` L2345–2370](https://github.com/chonamdoo/agent-flow/blob/023b6ee427afaeff0e49d2db000e11e59b14c45f/bin/agent-flow-kit.mjs#L2345-L2370): 참고 사본 consumer와 legacy 인덱스 갱신. [기존 설치 테스트 L3102–3132](https://github.com/chonamdoo/agent-flow/blob/023b6ee427afaeff0e49d2db000e11e59b14c45f/tests/test_custom_skill_install.py#L3102-L3132)는 파일/포인터 검사이며 native reviewer 전달 시험이 아니다.
- [S5: `src/agent_flow/core/skill_resolver.py` L39–90](https://github.com/chonamdoo/agent-flow/blob/023b6ee427afaeff0e49d2db000e11e59b14c45f/src/agent_flow/core/skill_resolver.py#L39-L90), [`skill_roots`/`resolve_skill` L351–419](https://github.com/chonamdoo/agent-flow/blob/023b6ee427afaeff0e49d2db000e11e59b14c45f/src/agent_flow/core/skill_resolver.py#L351-L419): source 우선순위와 kit-source 예외.
- [S6: `resolve_phase_skills` L626–710](https://github.com/chonamdoo/agent-flow/blob/023b6ee427afaeff0e49d2db000e11e59b14c45f/src/agent_flow/core/skill_resolver.py#L626-L710), [`_catalog_entry` L1335–1379](https://github.com/chonamdoo/agent-flow/blob/023b6ee427afaeff0e49d2db000e11e59b14c45f/src/agent_flow/core/skill_resolver.py#L1335-L1379), [`selector_matches`부터 `_glob_matches` L1422–1554](https://github.com/chonamdoo/agent-flow/blob/023b6ee427afaeff0e49d2db000e11e59b14c45f/src/agent_flow/core/skill_resolver.py#L1422-L1554): OR selector, 배치/owned taskTerms, 실제 glob 의미.
- [S7: `src/agent_flow/core/profile_routing.py` L72–109](https://github.com/chonamdoo/agent-flow/blob/023b6ee427afaeff0e49d2db000e11e59b14c45f/src/agent_flow/core/profile_routing.py#L72-L109), [`_group_skills`/`_selectors_match` L150–218](https://github.com/chonamdoo/agent-flow/blob/023b6ee427afaeff0e49d2db000e11e59b14c45f/src/agent_flow/core/profile_routing.py#L150-L218).
- [S8: `src/agent_flow/core/skill_matching.py` L100–173](https://github.com/chonamdoo/agent-flow/blob/023b6ee427afaeff0e49d2db000e11e59b14c45f/src/agent_flow/core/skill_matching.py#L100-L173), [`_truncate`/`_within_budget`/`_domain_active` L208–306](https://github.com/chonamdoo/agent-flow/blob/023b6ee427afaeff0e49d2db000e11e59b14c45f/src/agent_flow/core/skill_matching.py#L208-L306).
- [S9: `src/agent_flow/core/local_skills.py` L305–411](https://github.com/chonamdoo/agent-flow/blob/023b6ee427afaeff0e49d2db000e11e59b14c45f/src/agent_flow/core/local_skills.py#L305-L411), [`missing_local_skill_markers`의 자기신고/전달 분기 L468–525](https://github.com/chonamdoo/agent-flow/blob/023b6ee427afaeff0e49d2db000e11e59b14c45f/src/agent_flow/core/local_skills.py#L468-L525).
- [S10: `src/agent_flow/adapters/hosted.py`의 `_reviewer_jobs` L482–595](https://github.com/chonamdoo/agent-flow/blob/023b6ee427afaeff0e49d2db000e11e59b14c45f/src/agent_flow/adapters/hosted.py#L482-L595), [`_run_multi_review_distribution` L282–316](https://github.com/chonamdoo/agent-flow/blob/023b6ee427afaeff0e49d2db000e11e59b14c45f/src/agent_flow/adapters/hosted.py#L282-L316): producer와 관측 기록.
- [S11: `src/agent_flow/multi_review.py`의 `distribute`/`_reviewer_job_for_cli` L198–253](https://github.com/chonamdoo/agent-flow/blob/023b6ee427afaeff0e49d2db000e11e59b14c45f/src/agent_flow/multi_review.py#L198-L253), [`_reviewer_cli_args` L277–325](https://github.com/chonamdoo/agent-flow/blob/023b6ee427afaeff0e49d2db000e11e59b14c45f/src/agent_flow/multi_review.py#L277-L325), [`run_distribution` L486–510](https://github.com/chonamdoo/agent-flow/blob/023b6ee427afaeff0e49d2db000e11e59b14c45f/src/agent_flow/multi_review.py#L486-L510): 실제 prompt dispatch consumer.
- [S12: `skill_resolver.py` L799–849](https://github.com/chonamdoo/agent-flow/blob/023b6ee427afaeff0e49d2db000e11e59b14c45f/src/agent_flow/core/skill_resolver.py#L799-L849), [`skill_prompt_block` L1025–1197](https://github.com/chonamdoo/agent-flow/blob/023b6ee427afaeff0e49d2db000e11e59b14c45f/src/agent_flow/core/skill_resolver.py#L1025-L1197): 일반 skill reference, architecture inline, 역할별 전달·자기신고 경계. [`SkillResolution.delivery` L184–196](https://github.com/chonamdoo/agent-flow/blob/023b6ee427afaeff0e49d2db000e11e59b14c45f/src/agent_flow/core/skill_resolver.py#L184-L196)는 동일 본문 grouping이다.
- [S13: `src/agent_flow/providers/subprocess.py`의 `verify_provider_sandbox_backend` L474–492](https://github.com/chonamdoo/agent-flow/blob/023b6ee427afaeff0e49d2db000e11e59b14c45f/src/agent_flow/providers/subprocess.py#L474-L492), [`_prepare_provider_state` L540–560](https://github.com/chonamdoo/agent-flow/blob/023b6ee427afaeff0e49d2db000e11e59b14c45f/src/agent_flow/providers/subprocess.py#L540-L560).
- [S14: `docs/TEAM-ADOPTION.md` L268–273](https://github.com/chonamdoo/agent-flow/blob/023b6ee427afaeff0e49d2db000e11e59b14c45f/docs/TEAM-ADOPTION.md#L268-L273): 독립 team convention pack 미구현.
- [정체성·freeze 정책](https://github.com/chonamdoo/agent-flow/blob/023b6ee427afaeff0e49d2db000e11e59b14c45f/docs/IDENTITY-AND-FREEZE-POLICY.md), [검증 정책](https://github.com/chonamdoo/agent-flow/blob/023b6ee427afaeff0e49d2db000e11e59b14c45f/maintainer/verification-policy.md): 유한 coding run, runner 권한, installer 소유권, 격리 review, 구조/배포/모델 증거의 구분을 유지한다. 독립 메모리 제품의 운영 기능 전체를 금지하는 보편 규격이 아니다.
