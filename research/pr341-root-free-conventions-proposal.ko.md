# PR #341 재사용 및 root-free 컨벤션 적용 제안

조사일: **2026-10-11**. 현재 요구: 루트 `CLAUDE.md`·`AGENTS.md`에 **팀 공통 컨벤션도** 누적하지 않는다. Agent Flow가 없는 Claude/Codex 사용자도 독립 OSS 메모리를 사용할 수 있어야 하며, 회사 로컬과 개인 클라우드의 도메인 설계는 공유하되 데이터·계정·백업·배포 경계는 분리한다.

## 최종 결정

**별도 설치 서비스 + 얇은 MCP + 선택적 host adapter를 유지한다. 컨벤션은 root 파일이 아니라 승인된 범위별 원문과 작업별 선택으로 공급한다.** Claude/Codex/Agent Flow에 동일한 폴더·hook JSON을 강요하지 않는다. 회사·개인 운영에서 공통으로 유지할 것은 memory/evidence, rule/skill의 의미·승인·scope·유효 revision·조회 권한·선택 결과다. 실제 발견/주입·permissions·계정·cloud provisioning은 host/배포 adapter의 책임이다.

이는 **설계 제안**이며 구현 완료·배포 검증 보고가 아니다. 공개 근거를 다섯 병렬 조사로 검토했다: PR Standards, PR Spec/통합, Claude native, Codex native, 논문/OSS. 특정 Opus 5.5·Codex 6.1 Sol의 xhigh 모델 리뷰를 실행했다는 주장은 하지 않는다. 이번 모델 호출은 0회다. native executable과 `--help`는 확인했지만 계정/credential·실제 모델 응답은 검사하지 않았다.

## 1. PR #341에서 가져올 것과 제외할 것

고정 diff는 `1938aa191b169ac6fe9af80f7c1530d0e125a27a...023b6ee427afaeff0e49d2db000e11e59b14c45f`, 여섯 파일이다. **메모리 엔진 구현 PR이 아니다.** 기존 host memory의 참고·승격 기준, author root import와 reviewer 전달의 구별을 고친 지침/문서 변경이다.[R1–R3]

| 구분 | 채택 판단 | 영향/이유 |
| --- | --- | --- |
| 현재 근거 재확인, 프로젝트 규칙 우선 | 채택 | 과거 기억을 현재 사실·규칙으로 오인하지 않음 |
| 인간 교정 원문 / AI 요약 / 승인 기록 구분 | 채택 | 반복·요약 confidence가 승인 권위가 되지 않음 |
| evidence → 후보 → 범위 선택·승인 → 활성 rule/skill | 독립 제품 요구에 맞게 채택 | 로컬-only에는 tracked Git/팀 배포를 강제하지 않음 |
| 승인·선택·render·제출·소비 구분 | 채택 | hash/설치/self-report로 모델 준수를 주장하지 않음 |
| tracked root AGENTS 승격·CLAUDE import | 채택하지 않음 | 새 root-free 요구와 비호환; 본문 import는 lazy loading이 아님 |
| 공통 passive skill에 긴 컨벤션 추가 | 채택하지 않음 | 상시 입력을 다른 파일로 옮기는 같은 문제 |
| 기존 path/phase routing·예정 파일 고려·route 이유 | Agent Flow 연동에서 활용 | PR 이전부터 있는 기능. 실제 resolver는 설치/architecture/phase 계약에 결합됨 |
| resolver 전체·runner/gates·macOS isolated reviewer backend | 독립 제품에 복사하지 않음 | Agent Flow 미사용자의 필요조건이 아니며 memory service lifecycle과 다름 |

### Standards

고정 diff에서 **문서화된 기준 위반 0건, 근거 충분한 Fowler smell 0건**. 모델 입력까지 불변이라는 의미는 아니다. 전체 근거: [`pr341-standards-review.ko.md`](pr341-standards-review.ko.md).

### Spec

원래 #334/#341 요구에 대한 **입증 가능한 누락/범위 확장/잘못된 구현 없음**. 새 root-free·개인-local 요구와의 채택 비호환은 원래 PR 결함이 아니다. merge 승인 또는 native model acceptance를 뜻하지 않는다. 전체 근거: [`pr341-spec-adoption.ko.md`](pr341-spec-adoption.ko.md).

## 2. root 대신 무엇을 사용하는가

| 방식 | 장점 | 한계 | 선택 |
| --- | --- | --- | --- |
| 조건 없는 `.claude/rules` 또는 다른 상시 지침 | 쉬운 정리/공유 | root 밖이어도 eager body loading | 긴 팀 공통 기준의 기본값으로 제외 |
| Claude Code `paths`가 있는 `.claude/rules` | root bridge 없이 관련 파일 작업 시 조건부 로드 | 파일 없는 작업·일부 Bash/다른 writer 경로, 최초 Write 전 지식 전달 보장 미확인 | 짧은 파일별 기준에 활용 |
| native skills + 좁은 references | 선택된 절차/본문만 로드; Agent Flow 불필요 | metadata 비용·implicit undertrigger·context 잔류 | 긴 검토 절차·예외에 활용, 중요한 작업은 명시 호출 |
| 지원 native hook / 독립 wrapper | task/phase/예정 path로 필요한 규칙 선택 가능 | host/version/trust/coverage·실패 동작 다름; 모든 surface 보장 불가 | 강한 자동 선택이 필요한 지원 host만 opt-in |
| MCP 조회 | 같은 memory/rule service를 여러 host가 사용 | 연결만으로 작업 전 호출·관련 path 수집·의무 준수 보장 안 됨 | portable 조회 경계로 유지 |
| lint/static check/CI·서버 ACL·sandbox/egress | 검증 가능한 기준과 실제 권한을 모델 밖에서 집행 | 모든 설계/의미 판단을 표현할 수 없음 | 회사/개인 보안의 독립 실행 경계 |

공식 근거: Claude [memory/rules](https://code.claude.com/docs/en/memory#path-specific-rules), [skills](https://code.claude.com/docs/en/skills), [hooks](https://code.claude.com/docs/en/hooks); Codex [skills](https://learn.chatgpt.com/docs/build-skills), [hooks](https://learn.chatgpt.com/docs/hooks), [AGENTS discovery](https://learn.chatgpt.com/docs/agent-configuration/agents-md).[H1–H2]

Codex의 nested AGENTS는 CWD ancestor chain을 합쳐 읽는 방식이다. Claude형 native `paths` loader로 간주하지 않는다. `.agents/skills`와 explicit 호출을 기본으로 쓰고 supported hook/wrapper에서 필요한 규칙을 선택한다. `pathGlobs`·`taskTerms`는 Agent Skills 표준 selector가 아니며 동일 파일의 native 동작이 보장되지 않는다.[H2][S1]

**팀 공통은 배포 대상이지 모든 작업에서 전체 본문을 읽으라는 뜻이 아니다.** API/DB/UI/리뷰/배포 등의 적용 조건으로 나눈다. 실제 모든 작업에 필요한 규칙이라면 root를 없애도 그 규칙을 전달/집행할 비용은 사라지지 않는다. 보안처럼 검증 가능한 부분은 실행 통제로 옮기고, 모델에게 필요한 최소 원문은 해당 작업 입력에 제공한다. 숨기거나 optional top-k로 바꾸는 것은 해결이 아니다.

## 3. 공통 계약 — 저장 범위와 로딩 조건을 따로 둔다

새 활성화/범위 변경 시 사용자에게 다음 **세 옵션**만 묻는다: **내 로컬·해당 프로젝트 / 프로젝트 공유 / 팀 공통**. 기존 항목의 내용 수정은 기존 scope를 유지한다. 범위 확대는 다시 선택·승인한다. 선택이 게시 권한·회사 반출 승인을 대체하지 않는다.

작업 적용 시에는 별도로 다음을 처리한다.

1. 승인된 identity·회사/개인 배포·project binding에서 접근 가능한 scope를 확정한다. 모델이 보낸 프로젝트 이름/path는 relevance 입력이지 ACL 증거가 아니다.
2. 승인·유효 revision인 규칙 중 현재 task/phase·예정/변경 path에 적용되는 규칙을 선택한다. 필수 적용 조건은 semantic 검색 점수에 맡기지 않는다.
3. 필요한 짧은 규칙·ID/revision/scope/출처와 선택 이유만 전달한다. 긴 해설·과거 리뷰·참조는 별도 읽기로 제공한다. 선택된 필수 원문은 budget 때문에 조용히 탈락시키지 않는다. 초과/접근불가/불명확은 상태로 드러내고 작업 전 범위 분할·확인을 요구한다.
4. 같은 content/revision은 반복 주입하지 않되 compaction·새 worker·scope 변경은 host의 실제 context 상태와 구분한다. dedup 기록만으로 아직 모델이 알고 있다고 단정하지 않는다. 이전 scope의 문장은 cache 삭제로 모델 context에서 제거되지 않으며 큰 경계 전환에는 새 session이 필요할 수 있다.
5. path가 바뀌거나 새 파일/다른 module을 작업할 때 선택을 갱신한다. 관련 파일을 아직 읽지 않았다는 이유로 해당 규칙이 없는 것으로 판단하지 않는다.
6. 적용 가능한 필수 기준을 못 읽은 상태와 '규칙 없음'을 구분한다. 배포/전달 성공과 결과 준수를 별도로 기록·검토한다.

**같은 의미 계약, 다른 adapter**다. 로컬 회사 환경의 rule store/queue/index/backup은 회사 경계에 남기고 회사 승인 업무 모델만 사용한다. 회사-derived 개인-local 규칙도 개인 cloud/user-wide skill/account sync로 자동 보내지 않는다. cloud agent는 사용자의 PC 폴더를 읽지 못하므로 승인된 cloud 배포·권한·artifact 준비가 별도로 필요하다.[S1][H1–H2]

## 4. 적대적 검토에서 남은 위험

- **파일 이동 = lazy loading 아님:** Claude unscoped rules는 startup에 읽는다. Agent Flow의 일반 project/local skill도 selector 없이 placement만으로 여러 code phase에 required가 될 수 있다.[H1][R2]
- **rule 선택 = 실행 강제 아님:** native skill implicit 선택은 모델 판단이다. MCP resource의 context 포함 여부도 host가 결정한다. 모델이 읽었다는 답이나 digest는 소비/준수 증거가 아니다.[S1–S2]
- **PreToolUse context ≠ 첫 쓰기 재계획:** Claude 공식 hook docs에서 `additionalContext`는 tool result 옆에 들어가 다음 model request에 보인다. 첫 위험 tool input을 바꾸려면 사전 명시 읽기, 지원되는 deny/재계획 또는 결정론적 action 검사가 필요하다. native path-rule 첫 Write input 생성 이전 전달은 미확인이다.[H1]
- **hook ≠ 보안 sandbox:** Bash/script/IDE/다른 process, hosted tools, 이미 실행 중인 명령 등의 coverage 차이가 있다. 에러·timeout·잘못된 JSON의 실패 동작도 host/handler/version마다 다르다. 사용자 hook이 회사 필수 통제의 유일한 경계가 되면 안 된다.[H1–H2]
- **공통 파일 형식 ≠ 같은 runtime:** Claude/Codex skill/hook/plugin의 directory, invocation, precedence, trust, 지원 surface가 다르다. MCP만으로 native 설치·자동 갱신·reviewer 전달은 구현되지 않는다.[H1–H2]
- **모든 corpus를 후보 skill로 노출하지 않기:** discovery metadata도 누적되고 description/listing이 잘릴 수 있다. scope에 맞는 소수 entry와 bounded 조회를 기본으로 두되 generic entry의 undertrigger도 명시 호출로 보완한다.[H1–H2][P]

## 5. 논문/OSS 근거의 정확한 의미

논문은 **불필요한 상시 문서·중복 instruction의 비용을 의심할 근거**이며 'RAG로 모든 규칙을 옮기면 더 안전하고 저렴하다'는 증거가 아니다.[P]

- *Agent READMEs*는 파일 corpus/유지 이력의 관찰 연구다. 컨텍스트 파일로 성공률이 좋아졌다는 인과 실험이 아니다.
- *Evaluating AGENTS.md* v3는 특정 Python task/model/harness에서 context-file 조건과 비용/성공을 비교한다. 본 제품의 절감률 또는 dynamic retrieval 대 최소 all-loaded 우열을 측정하지 않았다.
- *RepoComplianceBench*는 별도 non-anchor 정책을 Native run에서 거의 열지 않고, 발견 이후에도 준수 문제가 있음을 보이는 반례다. mandatory 정책을 '필요하면 agent가 알아서 검색'에 맡기지 않는다.
- Continue의 path/content filtering, OpenCode의 역사적 read-triggered instruction delivery, 공식 skill의 metadata/body/reference 분리는 재사용할 **책임 분리 패턴**이다. 그 host 전용 config/문자열 path containment를 native Claude/Codex나 ACL 구현으로 복사하지 않는다.

판본·표본·원문 불일치·pinned OSS 코드·counterargument는 [`root-free-conventions-papers-oss.ko.md`](root-free-conventions-papers-oss.ko.md)에 기록했다. GitHub 전체 조사·최고 솔루션 선정·benchmark 재현을 주장하지 않는다.

## 6. 실제 실행 증거와 미검증 항목

실제 기존 `entry_activation`과 `routed_profile_skills`를 root CLAUDE/AGENTS 없는 임시 프로젝트의 synthetic metadata로 호출했다. 관련 직접/중첩 경로에서 선택되고, 무관련 경로·다른 phase·명시 빈 selector에서는 제외되는 **아홉 시나리오**를 관측했다. 첫 호출에서 selector 없는 local entry가 code/document 경로 모두 `placement`로 활성화되는 것도 관측했다.[R3]

또한 `src/server/**/*.py`가 직접 자식 `src/server/request.py`까지 매칭할 것이라는 최초 기대는 실제 `None` 결과로 실패했다. 기존 함수는 `fnmatchcase`와 leading `**/` 보정만 사용한다. 중간 `**` zero-depth 해석을 host 공통으로 가정하지 않는다. 실패를 PR patch defect로 분류하거나 지우지 않았다. 전체 fixture/관측/범위: [`pr341-root-free-routing-smoke.ko.md`](pr341-root-free-routing-smoke.ko.md).

이는 **순수 선택 경계의 실행 증거**이며 full resolver 설치 gate, native host의 first Write/compaction/skill selection, model 준수·token 절감, 회사 계정·retention·ACL/egress·worker 복구의 증거가 아니다. 제품 코드/host 설정/credentials/GitHub를 변경하지 않았다. 기존 보안 설계 노트는 최신 root-free 요구에 맞춰 관련 문단만 수정했다.

## 근거 노트

- [R1] [`pr341-standards-review.ko.md`](pr341-standards-review.ko.md) — 고정 diff와 저장소 기준, 원래 Standards 축.
- [R2] [`pr341-spec-adoption.ko.md`](pr341-spec-adoption.ko.md) — 원래 Spec 축, installer/resolver/reviewer의 고정 실제 source 및 재사용 영향.
- [R3] [`pr341-root-free-routing-smoke.ko.md`](pr341-root-free-routing-smoke.ko.md) — 실제 함수 실행 관측·glob 실패 및 한계.
- [H1] [`root-free-claude-conventions.ko.md`](root-free-claude-conventions.ko.md) — 공식 rules/skills/hooks와 first-party pinned source.
- [H2] [`root-free-codex-conventions.ko.md`](root-free-codex-conventions.ko.md) — 공식 문서 및 release 0.162.1 고정 source, surface별 지원 차이.
- [P] [`root-free-conventions-papers-oss.ko.md`](root-free-conventions-papers-oss.ko.md) — 논문 원문/판본/한계, pinned OSS implementation.
- [S1] [Agent Skills specification](https://agentskills.io/specification), [client implementation guide](https://agentskills.io/client-implementation/adding-skills-support) — progressive disclosure·discovery·cloud provision. 가이드의 일반 precedence 문구를 host별 실제 precedence 대신 쓰지 않는다.
- [S2] [MCP 2026-07-28 resources](https://modelcontextprotocol.io/specification/2026-07-28/server/resources) — application-driven context inclusion과 authorization에 따른 목록; protocol이 자동 적용/준수를 강제하지 않음.
