# PR #341 채택 조사: root-free 선택 함수 smoke

## 실행과 범위

2026-10-11, `/Users/namdoo/Developer/Aiproject/agent-workflow/src`의 실제 `skill_resolver._catalog_entry`, `entry_activation`, `profile_routing.routed_profile_skills`를 Python에서 import하여 호출했다. checkout HEAD는 `1938aa191b169ac6fe9af80f7c1530d0e125a27a`; 이 함수들은 PR #341에서 변경되지 않는다. 임시 프로젝트는 root `CLAUDE.md`/`AGENTS.md`가 없는 상태이며 synthetic metadata만 입력했다. 제품/사용자 설정을 수정하지 않았고 임시 경로는 context manager 종료로 제거됐다.

전체 installer·`resolve_phase_skills`의 설치/아키텍처 계약 gate·native host·LLM은 실행하지 않았다. 파일 본문 전달/소비, 스킬 준수, 실제 토큰/비용/성능, 회사 정책 준수를 증명하지 않는다. 보고된 설치 실패를 재확인하거나 기존 suite를 재실행한 작업도 아니다.

## 관측

첫 호출에서 selector 없는 `project-local` entry는 `implement`/`src/server/request.py`와 `review`/`docs/release.md` 모두 `placement`로 활성화됐다. 이어 `src/server/**/*.py`가 직접 자식 `src/server/request.py`와 매칭할 것이라는 smoke 기대가 실패했다: 실제 결과 `None`. 이 실패를 숨기거나 PR defect로 분류하지 않았다.

실제 `_glob_matches`는 `fnmatchcase` 기반이며 맨 앞 `**/`만 추가 처리한다. 중간 `**/`의 zero-depth 의미를 다른 host의 glob과 동일하다고 가정하면 안 된다. 해당 관측 뒤 메타데이터를 `src/server/**`로 명시한 새 시나리오와 nested-only 예제를 실행해 다음 결과를 관측했다.

| 실제 입력 경계 | 관측 결과 |
| --- | --- |
| implement · `src/server/request.py` · `pathGlobs: [src/server/**]` | `path-globs` 활성화 |
| review · `src/server/api/request.py` · 같은 selector | `path-globs` 활성화 |
| review · `docs/release.md` · 같은 selector | 비활성 |
| design · `src/server/request.py` · phases implement/review | 비활성 |
| implement · `src/server/request.py` · 명시한 빈 `pathGlobs` | 비활성 |
| implement · `src/server/api/request.py` · `src/server/**/*.py` | nested 경로 활성화 |
| profile required_review 경로 `src/server/**` · review · 관련 파일 | `private-review` 선택 |
| 같은 profile · review · 문서 파일 | 선택하지 않음 |
| 같은 profile · design · 관련 파일 | 선택하지 않음 |

## 채택 판단

root 파일 없이도 **기존 경로·phase 선택 로직 자체**는 동작한다. `skills/` 또는 `.agent-flow/local-skills/`에 본문을 넣는 것만으로 lazy loading이 되는 것은 아니다. 선언 없는 placement는 광범위하게 활성화될 수 있으므로 selector와 phase를 명시해야 한다. 이 내부 camelCase metadata는 Agent Skills 표준의 범용 계약이 아니며 Claude/Codex에 그대로 복사할 수 없다. 독립 제품은 공통 scope/선택 의미를 정의하고 host별로 컴파일·검증해야 한다.

## 소스

- [고정 PR diff](https://github.com/chonamdoo/agent-flow/compare/1938aa191b169ac6fe9af80f7c1530d0e125a27a...023b6ee427afaeff0e49d2db000e11e59b14c45f)
- [카탈로그/활성화/경로 매칭](https://github.com/chonamdoo/agent-flow/blob/023b6ee427afaeff0e49d2db000e11e59b14c45f/src/agent_flow/core/skill_resolver.py#L1335-L1551)
- [profile router](https://github.com/chonamdoo/agent-flow/blob/023b6ee427afaeff0e49d2db000e11e59b14c45f/src/agent_flow/core/profile_routing.py)
