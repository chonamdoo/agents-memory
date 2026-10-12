# PR #341 Standards 검토

## Standards

**문서화된 기준 위반: 0건. 근거가 충분한 휴리스틱 냄새: 0건.**

검토 범위는 `1938aa191b169ac6fe9af80f7c1530d0e125a27a...023b6ee427afaeff0e49d2db000e11e59b14c45f`의 여섯 파일과 해당 변경의 소비 경계다. 임의의 최신 HEAD 변경은 판정에 넣지 않았다.

- `AGENTS.md`의 요청 밖 리팩터링·문서 추가 금지와 공통 skill의 최소 변경 원칙에 반하는 변경은 찾지 못했다. 메모리 지침·포인터·양언어 문서·테스트 설명은 요청된 변경이다. 원장의 #333 보충도 `maintainer/verification-policy.md`의 **회귀 대조 → design 3**에 따른 누락 merged PR 반영이므로 무관한 기능 추가로 보지 않는다.
- **Freeze list / No-go list**에 대조했다. diff는 runner 권한, gate, reviewer 실행·격리, installer 소유권 판정의 제어 흐름을 바꾸지 않는다. 새 memory 저장소·추출·주입·동기화나 metadata/schema/gate, 설치되는 평가 자료·개발 정책도 추가하지 않는다. 다만 공통 skill과 생성 포인터의 **지침 본문은 바뀐다**. 이를 입력·모델 행동까지 불변이라는 뜻으로 읽으면 안 된다.
- 공통 skill의 **Agent-Facing Documents**가 요구하는 구조·전달·모델 증거 구분을 유지한다. 포인터의 “this import does not establish reviewer delivery”는 `rootBootstrapBlock("CLAUDE.md", …)`의 기존 분기에서 만들어지고, `managedBootstrapMarkdown()`은 일반 본문을 보존해 참고 사본으로 전달한다. 테스트 변경은 docstring뿐이며 기존 단정을 약화하지 않는다. 영어·한국어의 새 절은 같은 선택적 메모리·승격·전달 한계를 설명한다.
- **판단:** Fowler 12개 기준에서 보고할 근거를 찾지 못했다. 양언어 설명과 skill·포인터·테스트의 관련 설명 병행은 동일 실행 로직 복제가 아니므로 **Duplicated Code**나 **Shotgun Surgery**로 지적하지 않는다. 새 추상화·분기·상속 계약도 도입하지 않는다.

현재 사용자의 root-free·개인 로컬 범위 요구와 tracked `AGENTS.md` 승격 경로의 차이는 별도 채택 적합성 문제이며 이 Standards 축의 결함이 아니다. 의도한 byte 증가의 수용을 위반으로 재분류하지 않았다. 보고된 CI·실패를 재실행하지 않았고 build/lint/test/formatter·모델 호출도 하지 않았다. 이 판정은 설치된 클라이언트의 실제 입력 소비·모델 준수나 merge 승인의 증명이 아니다.

## 근거

- [고정 diff](https://github.com/chonamdoo/agent-flow/compare/1938aa191b169ac6fe9af80f7c1530d0e125a27a...023b6ee427afaeff0e49d2db000e11e59b14c45f)
- 기준: [AGENTS](https://github.com/chonamdoo/agent-flow/blob/023b6ee427afaeff0e49d2db000e11e59b14c45f/AGENTS.md), [freeze](https://github.com/chonamdoo/agent-flow/blob/023b6ee427afaeff0e49d2db000e11e59b14c45f/docs/IDENTITY-AND-FREEZE-POLICY.md), [검증 정책](https://github.com/chonamdoo/agent-flow/blob/023b6ee427afaeff0e49d2db000e11e59b14c45f/maintainer/verification-policy.md)
- 변경: [공통 skill](https://github.com/chonamdoo/agent-flow/blob/023b6ee427afaeff0e49d2db000e11e59b14c45f/skills/code-generation-discipline/SKILL.md#L14-L20), [포인터·분기](https://github.com/chonamdoo/agent-flow/blob/023b6ee427afaeff0e49d2db000e11e59b14c45f/lib/installer-shared.mjs#L1723-L1748), [소비 함수](https://github.com/chonamdoo/agent-flow/blob/023b6ee427afaeff0e49d2db000e11e59b14c45f/bin/agent-flow-kit.mjs#L2345-L2367)
- 문서: [EN](https://github.com/chonamdoo/agent-flow/blob/023b6ee427afaeff0e49d2db000e11e59b14c45f/docs/TEAM-ADOPTION.md#L103-L190), [KO](https://github.com/chonamdoo/agent-flow/blob/023b6ee427afaeff0e49d2db000e11e59b14c45f/docs/ko/TEAM-ADOPTION.md#L96-L173), [테스트 문맥](https://github.com/chonamdoo/agent-flow/blob/023b6ee427afaeff0e49d2db000e11e59b14c45f/tests/test_custom_skill_install.py#L3102-L3130), [원장 #333](https://github.com/chonamdoo/agent-flow/blob/023b6ee427afaeff0e49d2db000e11e59b14c45f/maintainer/regression-ledger/ledger.md#L284)
- 결과 경계: [PR author 보고](https://github.com/chonamdoo/agent-flow/pull/341)
