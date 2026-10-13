# Claude Opus 5.5 xhigh 신규 리뷰 판정표

실제 native 출력 `distribution-review-opus-5.5-xhigh.ko.md` 전부와 evidence를 읽고 작성했다. 출력 SHA256 `9fe356983dd512a8817d90dec631cf913123c9af2d98fb86d81e07748c10aa0a`. 동일 frozen input180322bytes/SHA256 `36d909bc0a8a024b958b76edb23bf7d62c77b1c780e99216a0835aa4d24455a5`. CLI2.1.296, modelUsage native canonical key=`claude-opus-5-5`, success/is_error=false/exit0. --effort=xhigh 전달, resolved server effort는 반환되지 않았다.

성공 실행은 2026-10-11T05:46:41.978338Z–05:55:30.869822Z. Sol 성공 실행과 160.922초 중첩했다. 최초 임의 HOME 격리 실행은 인증실패하여 리뷰로 계상하지 않고 별도 실패 artifacts로 보존했다. 성공 실행은 원래 인증환경+empty cwd+safe-mode/tools없음/MCP없음. CLI가 ~/.claude.json 메타데이터를 갱신했고 내용/Keychain 불변은 검사하거나 주장하지 않는다. Runner가 설정/로그인/설치 명령을 실행한 것은 아니다.

'채택'은 설계 수용이지 구현 해결/테스트 통과가 아니다. Native severity를 임의 재평가하여 #334 취약점으로 바꾸지 않는다.

| Native ID·severity | 실제 반례 | 부모 판정 |
|---|---|---|
| O1 P0 | 회사/고객 작업의 같은 UID·global tool catalog에 개인 endpoint/token이 있으면 정상 principal write로 고객 내용이 개인 cloud와 backup에 반출 | 위험 수용, 조건부로 명시. 회사/customer와 개인의 home/session/token·backup 분리. OS user/VM 또는 동등하게 검증된 sandbox+egress 강제경계 필요. installer profile marker 거부는 UX guard일 뿐 악성 같은-UID 접근통제 증명이 아니므로 충분조건으로 채택하지 않음 |
| O2 P1 | MCP만 연결하고 host capture/다음 task injection이 없으면 '자동' pipeline이 사라지며 coverage 공백을 '사실 없음'으로 오독 | 수용+분류 정정. host별 capture mode/trigger·source watermark·coverage를 표시. 사후 export/import가 자동이라는 blanket 주장 기각; 승인 event/schedule이 실제 자동 실행할 때만 자동. 수동 import와 model-initiated retain은 따로 표시 |
| O3 P1 | local PG tokenizer/extension과 managed PG 최소공통분모가 달라 Korean/code lexical 결과 달라짐 | 조건부 수용. VM/Compose에서 공통 PG/extension release baseline. managed PG 무조건 불가라고 하지 않고 동일 지원 extension/tokenizer/품질 fixture를 확인한 profile만 허용. 확인 못한 기능을 지원 불가로 단정하지 않음 |
| O4 P1 | 같은 UID approve CLI/browser/Compose.env로 operator·direct PG writer 위조 | plane 분리 수용, soft-delete 해결안 제한. CLI/UI는 service API client로서 DB credential 없음. ordinary scoped correction/retraction의 read exclusion은 허용 data-plane으로 가능. soft tombstone/undo 기간이 physical purge/법적 삭제를 충족하지는 않으며 blanket 보존/undo 약속을 채택하지 않음. destructive purge/export/policy/directive엔 실효적 operator boundary |
| O5 P1 | old DB/old ledger restore, stale worker publish, old capture/spool re-ingest, logical operation ID 다른 payload 충돌 | 수용. DB rollback과 독립적인 최신 deletion authority; 최신성 확인 불가 fail closed; raw/derived/cache/job/read/publish/source lineage 전체범위, stable source identity/operation digest conflict. salted hash만으로 canonical identity·재수집차단이 증명되는 것이 아니므로 암호화 scheme을 고정하지 않음. host/native/provider copies는 제품 삭제 밖 |
| O6 P1 | global hook 상속·tracked .mcp.json의 다른 사용자/cloud/reviewer 전달·전체backup config복원 | 수용. 기본 service-only 설치, host별 explicit opt-in, dedicated/untracked local profile 기본; project-tracked 공유 설정은 team 승인 scope. ownership+현재값 보존. 원 PR의 reviewer memory 격리와 shared company external context 승인 범위는 별개 |
| O7 P1 | 모든 회사 배포를 offline이라고 부르면 SaaS 허가/금지·localcompute 부재·silent reflect off 가려짐 | 수용. local storage+approved-egress, no-external-egress/승인 사내추론(완전air-gap은 host까지local), unsupported 조건을 구분. unsupported는 제품 edition/stub가 아니라 실제 prerequisites 불충족. automatic full pipeline 범위 유지 |
| O8 P2 | Run IAM/OAuth·CPU/file/queue·replica startup migration 분기와 비용 | 수용. 초기 공통 cloud baseline VM/Compose+same engine/release/지원 PG·extension. 외부 IdP 재사용·schema one-shot ownership. OS/arch image가 다르면 byte-identical artifact라고 말하지 않음. Run과 managed PG를 원천기각하지 않고 별도 실제 worker/compat profile 검증 후지원 |

## 두 모델과 다른 판단 지점

- Opus는 Hindsight 위에 distribution/ACL/capture/installer를 얹는 범위 절약을 더 강하게 선호한다. Sol C4는 wrapper precheck로 backend stale commit을 막을 수 없음을 더 명확히 경고한다. 부모 판정: Hindsight core 재사용 우선이지만 authoritative publication/fence/delete는 engine 내부에 실제 적용할 수 있어야 함. 안 되면 최소 backend fork, fork 유지비가 크면 새 PGcore 비교. 얇은 gateway만으로 모두 해결됐다는 약속은 기각.
- Opus는 managed PG/Run을 초기조건에서 더 강하게 제외한다. Sol은 managed PG를 같은 common contract의 조건부 DB 선택으로 남긴다. 부모 판정: 첫 검증 topology를 VM/Compose로 단순화하고, managed PG/Run은 compatible version/extensions와 real worker lifecycle을 관측했을 때만 추가. managed가 본질적으로 다른 엔진이라고 말하지 않음.
- Opus의 공개시점 지연론은 운영검증 후 공개할 수 있다는 유지관리 판단이다. 사용자는 OSS제품을 제안했다. 부모는 공개 source를 운영검증 전 금지하지 않으며 공개해도 production-ready/universal-host 지원표시는 실제 acceptance 이후에만 허용. 비공개·fullpipeline 축소를 사용자 허락없이 결정하지 않음.

## PR Standards / Spec의 후검토

Native는 양쪽 hard violation을 찾지 못했다. judgement로 docs범위·정본 drift·draft표현/byte수용·#333ledger별도PR를 언급했다. 별도PR 제안은 **미채택**: native packet에는 해당 main 정책이 없었지만 부모가 이후 pinned `maintainer/verification-policy.md`를 읽었다. '회귀 대조/design3'은 초기원장 이후 누락 mergedPR을 다음 작업design에서 보충해 그 작업PR에 포함할 것을 명시한다. #333의 ledger 행을 #334에 포함하는 것은 이 정책과 맞는다. Source: https://github.com/chonamdoo/agent-flow/blob/642d1792edf0b22bda2bb879ac65df145273dc19/maintainer/verification-policy.md#회귀-대조 . Native 결과 원문은 수정하지 않고 이 판정만 추가한다.

'No separate memory-analysis pipeline is needed'의 Agent Flow 현범위 한정, 원본문draft↔APIstate 구분, source-of-truth와 delivery/consumption 차이는 기록 정확성 차원에서 수용한다. 이번 요청으로 원PR을 편집하지 않는다. 회사가 운영하는 shared memory는 #334의 user-owned native memory와 같다고 주장하지 않으며, explicit external context 연결로 별도 권한·scope를 판단한다.

Native Opus가 미확인으로 남긴 Claude safe-mode는 부모가 현재 CLI help에서 hooks/CLAUDE.md/installed plugins/MCP/custom commands 등 customizations disabled, auth normal임을 직접 확인했다. 이는 본 native 리뷰 isolation 근거이며 blocked Agent Flow run에서 실행한 proof나 실제 host capture/reviewer 통합 테스트로 바꾸지 않는다.
