# 영상·Skills 추가 조사: 실제 병렬 상호 반박 후 최종 결정

**현재 구현은 유지하고, 기존 계약의 결함을 먼저 고친다. 새 feedback consumer·trace 증류·Skills 배포는 지금 추가하지 않는다.** 영상의 절차 재사용 개념은 기존 기록·후보·정확한 revision 승인 경로의 로컬 사용 지침에 반영한다. 1–2주 실제 사용은 아직 시작·완료한 것으로 판정하지 않는다.

## 실제 두 모델 실행 근거

1차 보고서를 서로에게 전달하고, 같은 정정·소스 근거·평가 기준을 담은 79,277B 입력을 두 native CLI에 그대로 병렬 전달했다. SHA-256은 `0c4377976ea082438b887a0f48cd295578603c27a1d5fae5df1da3462b88b553`다. 두 실행 시간이 겹치고 각각 exit 0으로 완료했다. 도구와 파일/네트워크 조사 없이 고정 근거에만 반박했다.

| 실행 | 시작 UTC | 종료 UTC | 모델·effort 증거 | 보고서 |
|---|---|---|---|---|
| Claude | 2026-10-12 11:26:14 | 11:32:31 | CLI `claude-opus-5-5`, `xhigh`; 응답 modelUsage도 `claude-opus-5-5`. effort는 응답 독립 증거 없음 | [전체 2차 보고서](native-opus55-round2.ko.md), [sanitized proof](native-opus55-round2.proof.json) |
| Codex | 2026-10-12 11:26:22 | 11:32:04 | CLI `gpt-6.1-sol`, `model_reasoning_effort="xhigh"`; JSONL은 서버 모델/effort를 보고하지 않음. 설정 증거와 실제 served identity를 구분 | [전체 2차 보고서](native-sol61-round2.ko.md), [sanitized proof](native-sol61-round2.proof.json) |

원문 최종 응답 SHA-256: Opus `ec529bf634c334dea309af237d6427ccf6dd22e8f609d6f7a8d0b0c8eb8f6db8`, Sol `3ec42b401d88d83c7c2bdbc697e9c866b87b4ac2bbdcdcee32d611b4a43beb2f`. 원문은 수정하지 않고 보존했다. 숨겨진 reasoning·인증·환경값·provider raw 출력은 포함하지 않았다. 이 조사 리뷰는 제품 코드 승인이나 실행 성능 검증을 대신하지 않는다.

## 같은 잣대의 영향·장단점·채택 여부

| 대안 | 이득 | 주요 위험·영향 범위 | 결정 |
|---|---|---|---|
| A: 현 PG ledger·동일 core·4 tools 유지 | 기존 출처·lease·삭제·승인·scope·호스트 검증을 재사용; Agent Flow에 종속되지 않음 | 긴 optional 승인 본문의 도달성과 id순 선택 한계는 관찰 대상; 알려진 결함까지 정상이라고 보는 뜻은 아님 | **지금 유지**. 공개 회사 corpus와 개인 환경을 합치지 않음 |
| B: feedback·절차 재사용/증류 | 반복 오류·중복 제안 감소 가능; 기존 `rule_candidate`와 승인을 사용 | feedback 기록 ≠ 다음 생성에 소비 ≠ verified outcome ≠ authority. 실패·성공 오분류, 같은 root_run 중복, secret·간접 injection, 승인자 시간 증가 | **지금은 사용 지침만**. 새 consumer/증류 코드는 실제 trial 이후 별도 승인 |
| C: 코드 변경에 따른 재검토 | 파일·환경 변화와 오래된 절차 사이의 연결을 관찰 가능 | 해시 변경은 의미 변경의 증명이 아님; 외부 API/권한 변화 누락, 오탐 차단, binding 재승인 폭증 | **보류**. 필요가 관찰되면 binding 밖의 shadow 관측부터; applicability/approval 자동 변경 금지 |
| D: Skills Over MCP projection | 지원 host가 필요한 작은 절차만 읽는 보조 경로를 시험 가능 | SDK 병합/릴리스/host activation·consent가 다름; 두 read 경로의 revision 불일치, eager prefetch, cache의 삭제·realm 경계 | **지금 미도입**. 현 tools를 대체하거나 required 권한을 넘기지 않음 |
| E: 자동 승격·조직 broadcast·회사 gateway·대형 catalog | 조작을 줄인다는 주장 | 정확한 승인·회사 무반출·삭제 closure·bounded context와 충돌 | **기각** |

## 상호 반박에서 바뀐 결정

- Opus는 “새 procedure kind”와 “feedback consumer 즉시”를 철회했다. Sol도 C를 지금 착수하는 의미로 쓰지 않기로 수정했다. 둘 다 현 core 유지·trial 지침 우선·Skills 보류로 수렴했다.
- required applicability `UNKNOWN`은 경고 후 실행이 아니라 protected action **fail-closed**다. 코드 변경 신호가 자동으로 권한/적용성을 바꾸지 않는다.
- 원천 삭제 후에는 이전 인간 승인이 삭제 closure를 무력화하지 못한다. 이후 전달을 끊는 것과 이미 전달한 임의 host context의 망각 보장은 다르다. rollback/restore도 현재 eligibility를 재확인해야 한다.
- Skills에 selector 손실이 반드시 생긴다는 주장은 과하다. 서버가 현재 auth/realm/scope/eligibility를 확인할 수는 있다. 다만 실제 host 활성화·동의 증거와 추가 운영 비용 없이 이를 지금 채택할 이유는 없다.
- C와 D가 B 전체 구현에 기술적으로 의존한다는 단정도 하지 않는다. 현재 **착수 우선순위**와 각 기능의 **기술적 선행조건**을 구분한다.

## 부모 통합자가 실제 코드와 대조한 추가 정정

두 원문은 `MemoryWrite`/procedure 기록 표현을 사용한다. 실제 현재 코드는 `ClaimDraft.kind`에 `procedure`가 있지만, 공개 `RecordCommand.kind`는 **`note | rule_candidate`**뿐이다 (`domain.py:111-115,173-175`). `memory_record(kind=procedure)`라는 API를 만들었다거나 직접 호출할 수 있다고 주장하지 않는다.

사용 지침은 다음 경로만 제안한다.

1. 반복 작업의 조건·예외·원래 근거·관찰된 결과를 기존 `memory_record(kind=note)`에 좁게 기록한다. 이후 모델 추출의 `procedure` 분류는 후보이며 실행 권한이 아니다.
2. 컨벤션으로 만들 내용은 기존 `memory_record(kind=rule_candidate)`와 operator 제안·정확한 revision 승인 경로를 사용한다. 원천·scope·승인 연결을 우회하지 않는다.
3. 적용 범위는 반드시 **① 이 로컬 프로젝트 / ② 명시적으로 승인한 ID 집합의 내 프로젝트들 / ③ 설정된 승인자·audience의 팀·프로젝트 공유** 중 선택한다. ①을 몰래 기본 승인하지 않는다. 새 프로젝트는 재동의 대상이다.
4. 결과 검증이 없으면 unverified라고 적는다. 제공/inspect 기록만으로 소비·준수·성공·인과효과를 선언하지 않는다. 현재 feedback을 학습 데이터로 자동 소비한다고 주장하지 않는다.
5. 현재 UTF-8 inspect·host envelope 한도를 넘는 절차는 쪼개서 일부 승인하지 않고 승인/적용을 보류해 관찰 건으로 남긴다. required 본문 전체를 확인하지 못하면 실행하지 않는다.
6. 회사 자료·secret·PII를 개인 realm이나 외부 증류자로 보내지 않는다. 회사의 팀 모델 경로 승인은 별도 정책이며 메모리 서버의 외부 저장/전송 허가가 아니다.

또한 Sol 원문의 “Approve 후 BUILD→TYPECHECK→LINT, 최대3회”는 이 Python successor의 선언된 gate가 아니다. 실제 AF profile의 lint/test/package와 runner phase 계약을 따른다. 제공 입력에서 복구 근거를 못 봤다는 문장을 제품 전체의 복구 검증 부재로 확대하지 않는다.

## 후속 기능 검토 순서 — 현재 구현·승인 아님

- **먼저 실제 trial**: 승인/거절 사유·검토 시간, optional omitted/긴 본문 도달 실패, 잘못 선택된 규칙, required UNKNOWN 차단, 삭제 drill을 좁게 관찰한다. holdout과 원천 run을 분리하고 같은 root_run 재시도를 독립 증거로 세지 않는다.
- **O3/O4**: 안전한 optional 참조와 정확한 revision에 묶인 bounded/paged `inspect`, eligibility/applicability 이후 optional 관련성 선택. required는 relevance 점수로 탈락시키지 않고 완전 전달 또는 거절을 유지한다. 다섯 번째 도구는 만들지 않는다.
- **O5**: 제공된 정확한 rule revision·snapshot·확인 주체·검증 방법·관찰 결과를 연결한다. 모델 자기 평가와 feedback은 verified outcome의 대용이 아니다.
- **O6/O7/O8**: 이후 개인 프로젝트별 opt-in trace·candidate 전용 로컬 증류·advisory scan을 각각 평가한다. 자동 생성 전에 scan을 검토할 수 있지만 통과가 승인/permission grant는 아니다. 회사 trace나 무인 승격은 포함하지 않는다.
- **C**: 코드 변화와 실제 오적용 필요가 관찰된 때 shadow stamp/사람 검토를 시험한다. stamp 없음=최신이라는 추론을 금지한다.
- **D**: released SDK 기능 확인과 host별 discovery→read→activation→consent·digest 변경 재동의·lazy read·cache 격리·철회 증거가 모두 확보된 때에만 작은 optional 개인/합성 절차 projection을 재검토한다. 기본 MCP2 동작 증거를 Skills native 지원으로 재사용하지 않는다.

이 순서는 선택 이유와 평가 게이트이며 앞으로의 구현 약속이나 이미 통과한 결과가 아니다.

## 계속 유지할 1차 자료 정정

- CueFinder 제품/코드그래프/SQLite 최소 구성은 해당 메모리 영상의 설계 주장과 분리했다. 이번 제안의 영상 근거로 쓰지 않는다.
- `jDdgfTp_PXw`와 `u-o0sW9nwmk`는 동일 발화의 재업로드다. 36→100은 vendor 단일 사례이고 n/holdout/oracle/로그·전후 같은 모델/harness가 자막으로 확인되지 않았다. failure-run 증류 효과의 근거도 아니다.
- Python SDK PR3485의 병합 소스는 `mcp/client/extensions/skills.py`/`SkillsClient`다. 설치된 `mcp==2.3.0`에 Skills가 있다는 증거나 Claude/Codex/omp native activation·consent 증거가 아니다.
- MCP2 stateless는 무의미한 corpus preload를 없앨 설계와 양립한다. 그러나 0 startup **본문**은 0 tool metadata/전체 native prompt token이라는 뜻이 아니다. 과거 749/3922/282B는 특정 fixture의 body/catalog/discovery 관찰값이다.

## 업데이트와 재개의 실제 상태

업데이트 전 로컬 커밋은 `75474d9`, `970e9c8`이다. 추가 조사 전문과 두 native 1차 원문은 [이슈1 체크포인트](https://github.com/chonamdoo/agents-memory/issues/1#issuecomment-6123094993)와 [이슈2](https://github.com/chonamdoo/agents-memory/issues/2)에 게시하고 정확한 본문을 read-back했다.

사용자 소유 기존 worktree만 공식 abort/archive/remove로 삭제했고 branch/8개 interrupted 보고서/ignored 자산은 보존했다. 리더 `agents-memory` 기준 AF는 공식 0.3.15 source `5b92996a38c6411c61f36d7be10aed1dc26405e5`다. 전역 AF·main·타 프로젝트는 바꾸지 않았다. 이전에 승인받은 프로젝트 한정 timeout forwarding만 동일 공식 baseline hash를 확인한 후 재적용했다.

새 run은 **`development/20261012-113028`**, 공식 managed checkout `feat-agents-memory-resume`, technical branch `feat/agents-memory-resume-local`이다. AF의 hard-coded `feat/` 요건을 지키면서 리더 브랜드는 `agents-memory`로 유지했다. 실제 단계는 explore 완료 → **implement**다. 별도 plan phase는 없는 workflow이므로 fresh implementation/slice plan을 run에 기록했다. 과거 승인 marker는 재사용하지 않았다.

리더 실제 서비스의 doctor/API smoke는 통과했다: context payload 2,368/2,400B, wire 3,138B, pipeline 다섯 상태 0; active snapshot source inspect의 누락/불일치409·본문없음, 일치200·본문있음. 기록상 오래된 source는 현재 purged이고 metadata-only200이었다. 이 관찰을 active source leak로 잘못 해석하지 않았다. fresh native3·trial 기간·cloud·전체 zero-egress 증명으로 확대하지 않는다.

현재 successor에서는 config 손상, 원래 source 시각 누락, native strict denial budget/잘못된 durable hook state를 별도 결함 트랙으로 수정·검증 중이다. 연구 제안의 새 코드는 도입하지 않았다. 남은 완료 조건은 이 코드의 실제 변경 경로·전체 declared gates·fresh OS-confined AF review·QA·handoff와 로컬 커밋이다.
