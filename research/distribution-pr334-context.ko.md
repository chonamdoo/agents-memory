# 독립 OSS 배포 검토의 Agent Flow 맥락 — 2026-10-11

## 사용자 요구와 범위

#316와 PR #334를 확인하고, 독립 오픈소스 메모리 제품을 회사/외주용 로컬 설치와 개인용 클라우드 배포로 운영하는 방안을 비교한다. MCP 또는 일반 로컬 설치형이 적절한지 실제 Claude Opus 5.5 / GPT-6.1-Sol xhigh 병렬 적대적 리뷰 후 #316 댓글에 정리한다. 이는 조사·설계·리뷰·게시 요청이다. 코드 구현, 저장소 생성, 설치, 호스트 설정 변경, 서비스 배포, PR 수정/merge를 요청한 것은 아니다.

## 고정 비교와 실제 PR 상태

- Base / merge base: `642d1792edf0b22bda2bb879ac65df145273dc19`.
- Head: `a57c0c8a67df2814324e4e197dcd82faaff1c8b3`.
- 동등 diff 표현: `git diff 642d1792edf0b22bda2bb879ac65df145273dc19...a57c0c8a67df2814324e4e197dcd82faaff1c8b3`.
- 실제 획득 방식: GitHub PR diff와 immutable compare API. 로컬에서 위 git diff를 실행한 것으로 주장하지 않는다.
- API 관찰: open, draft=false, merged=false, mergeable_state=unstable, 6개 파일 +131/-31. PR 본문 마지막의 draft 표현과 현재 API 상태가 다르다. ready 상태는 runner review 승인이나 CI 통과의 증거가 아니다.
- 비교 commit 3개: `fce99a248f153ad5a35e467513e995d77fb3ea04` (host memory/team rule boundaries), `34e47e5581aa9f8d61587b804ec7752fdfd96041` (latest main merge), `a57c0c8a67df2814324e4e197dcd82faaff1c8b3` (regression ledger 기록).
- 출처: [PR #334](https://github.com/chonamdoo/agent-flow/pull/334), [고정 비교](https://github.com/chonamdoo/agent-flow/compare/642d1792edf0b22bda2bb879ac65df145273dc19...a57c0c8a67df2814324e4e197dcd82faaff1c8b3).

## 실제 변경 6개와 하지 않은 변경

| 파일 | 확인한 diff | 독립 memory 제품과의 관계 |
|---|---|---|
| `skills/code-generation-discipline/SKILL.md` (+2/-0) | 사용자 host memory는 선택적 참고, 현재 직접 근거 재확인, 원문/현재 근거와 tracked rule 제안, AI 요약≠인간 원문/승인 | memory service의 저장/추출/주입 구현이 아님. 회사/개인 shared store를 만들어 주지 않음 |
| `lib/installer-shared.mjs` (+3/-10) | `CLAUDE_POINTER_LINES` 안내 문자열과 주석에서 author import와 isolated reviewer 전달을 구분, `@AGENTS.md` 유지 | 함수 본문 제어 흐름은 바꾸지 않지만 실제 생성 pointer bytes는 바뀜. 설치 영향이 없다는 말은 틀림 |
| `docs/TEAM-ADOPTION.md` (+67/-11) | root 보존/legacy ownership, host memory/team rules, reviewer 플랫폼·전달 한계·수동 평가 범위 | 새로운 service lifecycle과 별도 공개제품이 이 문서에 구현돼 있지 않음 |
| `docs/ko/TEAM-ADOPTION.md` (+56/-8) | 위 한국어 대응 | 다른 저장/주입 코드가 추가된 것은 아님 |
| `tests/test_custom_skill_install.py` (+2/-2) | 기존 pointer 회귀의 docstring만 정정; test assertion 변경 없음 | 실제 memory 정확도·동작·reviewer 전달을 검사하는 test 아님 |
| `maintainer/regression-ledger/ledger.md` (+1/-0) | #333의 architecture-lint import guard/알려진 공백 기록 | 개발용 원장이고 memory 제품 기능 아님 |

새 memory DB·writer/reader API·cloud sync·추출 모델·MCP server·SessionStart injection·Jev·reviewer provider 확대·workflow/gate/sandbox 동작 변경은 diff에 없다. common skill과 pointer의 사용자-visible bytes는 바뀐다. 독립 제품을 만드는 것이 PR #334의 자동 확장이나 이미 승인된 runtime 통합이라는 뜻은 아니다.

## PR에서 보고한 실행 한계 — 이번에 재실행하지 않음

- focused pointer/user-edit 테스트 4 passed.
- 회귀 node 실행 37 passed, ownership exit 75의 두 subtest failures. PR은 같은 base 환경에서도 두 실패를 보고한다. 이번 조사에서 재현하거나 통과로 바꾸지 않는다.
- clean npm snapshot 설치 8관측, 배포 파일 356개 동일, 4개 내용 변화라는 PR 보고. 이번 작업에서 npm pack/install은 하지 않는다.
- common skill +608 bytes, phase budget 37개 지원 조합, 증가로 비교 exit 1; 수용 label/--accept 미사용이라는 보고. 실제 model consumption/효과의 증거가 아니다.
- Agent Flow run `20261011-043042`는 Linux의 verified sandbox backend 부재로 reviewer launch 전 blocked; required CLI approvals/QA/handoff 미완료. 이번 별도 모델 설계 리뷰가 이 run의 approval을 대신하지 않는다.

## #316의 두 서로 다른 범위

1. Agent Flow core: 사용자 host memory는 optional 참고, reviewer 사용자 home/memory 격리 유지, 팀 규칙은 tracked AGENTS/skill의 기존 PR/review/gate. 자체 store/자동 host 설정·주입을 넣지 않음. 관련 최종 판정은 [6105568406](https://github.com/chonamdoo/agent-flow/issues/316#issuecomment-6105568406), PR #334.
2. 새 cross-host/local-cloud 제품: [6105788769](https://github.com/chonamdoo/agent-flow/issues/316#issuecomment-6105788769)은 독립 서비스의 동일 domain/schema/API 두 배포를 제안했다. 고객/개인 데이터·credential·host·egress·backup은 분리. 단일 PG 권위, 승인 capability, version/CAS/fencing, coverage/watermark, source-based 철회와 독립 최신 deletion head가 기준이며 아직 memory runtime 구현/배포/벤치마크/forget-restore를 수행하지 않았다.

독립 제품이 background worker를 운영한다고 해서 그것을 Agent Flow core의 daemon으로 설치하는 것은 아니다. core freeze를 새 독립 프로젝트의 존재 금지로 확대하지 않는다. 반대로 OSS installer가 global MCP/hook/native memory를 수정하면 core code를 안 바꿔도 author/reviewer 입력과 회사 보안에 영향을 줄 수 있다.

## 저장소 Standards / Spec 판단 기준

### Standards — PR의 원 저장소 기준

- [pinned AGENTS.md](https://github.com/chonamdoo/agent-flow/blob/642d1792edf0b22bda2bb879ac65df145273dc19/AGENTS.md): 요청되지 않은 refactor/docs 금지, runner routing authority, workflow YAML 단일 정본, installed asset/corpus 분리, core host boundary pre-block·lifecycle 예외 확장 금지.
- [freeze policy](https://github.com/chonamdoo/agent-flow/blob/642d1792edf0b22bda2bb879ac65df145273dc19/docs/IDENTITY-AND-FREEZE-POLICY.md#no-go-list): mandatory schema/gate, implicit workflow 선택, ownership 없는 덮어쓰기, live model required CI, 배포자산에 eval/runtime/corpus 혼입, writer/reader/CLI 없는 interface 금지. 이 원칙을 새 독립 OSS의 worker 자체를 금지하는 근거로 사용하지 않는다.
- 변경된 skill의 정본은 `skills/code-generation-discipline/SKILL.md`; 설치 사본에 별도 기준을 복제하지 않는다.
- 기존 테스트 wording/default/copy에 새 assertion을 붙일 필요가 없다. 실제 behavior를 통제한 근거가 없으면 delivery/compliance를 주장하지 않는다.

Smell baseline (판단용 heuristic, hard violation 아님; repo 규칙이 우선):
- Mysterious Name: 의도를 드러내지 않는 이름 → 실제 의미로 rename.
- Duplicated Code: 같은 logic hunk 반복 → 공유 shape 추출.
- Feature Envy: 다른 객체 데이터에 더 관심 → 소유 객체로 이동.
- Data Clumps: 필드 묶음이 반복 이동 → 작은 type으로 묶음.
- Primitive Obsession: domain 개념을 의미 없는 string/number로 취급 → domain type.
- Repeated Switches: 동일 분기 반복 → 단일 map 또는 실제 필요한 polymorphism.
- Shotgun Surgery: 한 변경에 여러 파일 무관 수정 → 책임 모음.
- Divergent Change: 한 파일이 무관 이유로 반복 변경 → 책임 분리.
- Speculative Generality: 소비자 없는 추상화/옵션 → 제거.
- Message Chains: 내부 탐색 chain 노출 → 구현 감춤.
- Middle Man: 단순 전달만 하는 계층 → 불필요하면 제거. transport/process/권한을 실제로 분리하는 MCP shim은 전달만 한다는 이유로 자동 smell 확정하지 않음.
- Refused Bequest: 상속 계약을 무시 → composition.

### Spec — #334가 원래 구현하려던 것

사용자 소유 host memory를 optional 참고로 재확인하고 유지 가치 있는 tracked 팀 규칙만 근거와 review/gate로 제안; reviewer 전달 과장 정정; 설치 ownership·현재 memory 의미의 문서화. 신규 DB/추출/동기화/자동 주입이 없는 것은 이 spec의 누락이 아니라 의도한 비범위다. 다만 새 독립 제품 요구를 #334만으로 충족했다고 말해서도 안 된다.
