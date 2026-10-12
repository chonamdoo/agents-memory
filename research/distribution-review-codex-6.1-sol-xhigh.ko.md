**공통 memory pipeline은 설계상 가능하다. 공통 engine·domain API·schema·정정/철회 계약을 유지하고, 회사/고객과 개인의 데이터·인증·host session·추론 경로·backup은 독립 배포로 나눠야 한다.** 설치형과 MCP는 양자택일이 아니다. 일반 설치가 service·DB·worker 수명을 소유하고 MCP가 같은 service를 호출하는 **C를 조건부 채택**하는 것이 합리적이다. 실제 소비자가 local HTTP MCP를 지원한다면 stdio shim은 만들 이유가 없다.

다만 C만으로 “모든 agent에서 자동 기억”을 충족할 수는 없다. 호스트의 승인된 capture·recall adapter가 없거나 회사에서 필요한 모델·DB·service를 허용하지 않으면, 해당 환경의 full pipeline은 **unsupported**다. 개인 cloud도 사용자 Mac 없이 접근하는 실제 실행 표면의 인증·도구 등록·자동 수집 지원을 확인해야 한다.

이 판단은 제공된 고정 packet만 사용한 단일 독립 리뷰다. 아래 **[근거]**는 packet에 포함된 관찰, **[INFERENCE]**는 이번 판단이다. 채택 전 관측은 모두 미수행이며, 병렬 모델 실행·Agent Flow sealed review/gate·production readiness·이슈 게시를 뜻하지 않는다.

## PR Standards

**Hard violation:** 제공된 6개 diff에서 pinned [AGENTS.md](https://github.com/chonamdoo/agent-flow/blob/642d1792edf0b22bda2bb879ac65df145273dc19/AGENTS.md)와 [freeze policy](https://github.com/chonamdoo/agent-flow/blob/642d1792edf0b22bda2bb879ac65df145273dc19/docs/IDENTITY-AND-FREEZE-POLICY.md#no-go-list)의 확정 위반은 찾지 못했다. runner routing, workflow/gate/sandbox, reviewer 격리와 provider pool을 변경하지 않는다. 새 memory runtime이나 corpus를 설치 자산에 혼입하지도 않는다. 독립 제품의 worker를 원 저장소의 core daemon 금지로 기각하는 것은 정책 경계의 오독이다.

다만 필수 reviewer 증거와 전달량 증가의 수용은 미완료다. 이를 이번 독립 리뷰로 대체할 수 없다. API의 `draft=false` 역시 필요한 검증 완료를 입증하지 않는다.

**Judgement call:** Fowler smell baseline에서 6개 파일 변경 자체는 Shotgun Surgery가 아니다. skill·pointer·문서·test docstring은 같은 전달 경계에 연결된다. 반면 신규 제품에서 소비자 없는 stdio shim과 여러 storage/vendor 추상화를 먼저 만드는 것은 Speculative Generality 후보다. transport·권한·호환성을 실제로 분리하는 thin MCP adapter는 단순 전달이라는 이유만으로 Middle Man으로 확정할 수 없다. 이 판단을 #334의 기존 구현 결함으로 전이하지 않는다.

## PR Spec

**Hard violation:** #334의 좁은 spec은 사용자 host memory의 선택적 참고, 현재 근거 재확인, tracked 팀 규칙 제안, reviewer 전달 설명과 설치 ownership 정정이다. diff는 이에 부합한다. 신규 DB·자동 capture·추출·MCP·cloud sync가 없는 것은 spec 누락이 아니다. 반대로 #334가 신규 독립 제품 요구까지 충족했다는 주장도 성립하지 않는다.

**Judgement call:** 공통 skill의 두 항목은 모델이 따를 지침이며 자동 검증 기능이 아니다. pointer 수정은 installer 함수의 제어 흐름을 바꾸지 않지만 생성되는 사용자 지침 bytes를 바꾼다. reviewer의 프로젝트 `AGENTS.md` 영향은 문서가 명시한 미해결 문제이며 이번 PR이 해결했다고 읽을 수 없다.

검증은 **PR author report**다. focused 4 passed, 회귀 37 passed와 두 subtest failures, base에서도 같은 실패, clean package 설치 8관측을 이번에 재실행하지 않았다. 공통 skill +608 bytes와 phase-budget 비교 exit 1도 보고된 미완료 수용 사항이다. PR 본문의 “draft로 게시”와 API의 `draft=false`는 기록 정합성 확인 대상이다. 이 차이만으로 merge나 승인 완료를 추정하지 않는다.

## 제품/배포 adversarial findings

아래 8개는 신규 제품의 채택 조건이다. 제안이 이미 인지한 위험도 포함하지만, 이를 해결한 구현·운영 증거는 없다. **#334 구현 취약점으로 보고하는 항목은 아니다.**

### C1 · P1 — MCP 연결과 자동 pipeline 사이에 호스트 의존성이 남는다

- **[근거]** `distribution-cloud-sources.ko.md` §§5–6: 전체 conversation은 host 소유이며 cloud-orchestrated Work는 plugin hooks를 지원하지 않는다. Codex Cloud의 네트워크 허용은 arbitrary MCP native catalog 등록 증거가 아니다. 구형/신형 MCP와 계정·plan 지원도 구별되어 있다.
- **[INFERENCE] 실패 시나리오:** remote recall tool은 나타나지만 capture adapter가 없어 원문이 저장되지 않는다. 다음 task가 recall을 호출하지 않아 저장된 기억도 사용되지 않는다. private Run endpoint에는 사용자 MCP OAuth token만 전달되어 IAM에서 거절된다. 이를 “클라우드 memory 연결 성공”으로 발표하면 full pipeline 요구를 충족하지 못한다.
- **최소 수정:** 지원 단위를 **host/surface/version/plan + capture 경로 + recall 경로 + auth**로 제한한다. 사용자 OAuth와 Run IAM ID token을 구별하고, 필요한 경우 검증된 OAuth ingress와 private backend 경계를 둔다. 지원되지 않는 hook을 수동 note로 대체해 자동화 완료라고 표현하지 않는다.
- **채택 전 관측:** 실제 계정에서 native catalog·읽기/쓰기·자동 capture→추출→다음 task recall→reflect를 source ID로 연결한다. Mac을 끈 상태에서도 별도의 hosted agent 또는 own VM이 접근해야 한다. curl 성공은 별도 관측이다.

### C2 · P1 — 로컬 저장소는 고객 자료의 반출 금지를 보장하지 않는다

- **[근거]** `distribution-local-sources.ko.md` §§3·6–7: Hindsight local 안내의 기본 LLM provider는 OpenAI이며 embedding 다운로드가 있다. offline flag는 해당 라이브러리 범위에 한정된다. 회사 SaaS 허가는 strict no-export와 다르다.
- **[INFERENCE] 실패 시나리오:** extract/embed는 local이어도 고객 원문이 포함된 recall 결과가 cloud host 모델로 전달된다. 고객 A 내용을 읽은 같은 conversation을 개인 endpoint로 전환하면 개인 capture에 A 자료가 들어간다. 서버 ACL은 이미 host context에 들어간 내용을 제거하지 못한다.
- **최소 수정:** source collection부터 extract/embed/rerank/reflect와 **host 모델 호출까지** 승인 경로를 명시한다. 회사/고객/개인의 agent home·session·credential·backup도 분리한다. strict 배포에는 개인 endpoint fallback이나 고객 corpus sync/export를 넣지 않는다.
- **채택 전 관측:** 외부 연결을 차단한 전체 pipeline에서 요청 경로와 실패 상태를 관측한다. 모델 부재 시 pending/blocked/failed를 표시해야 한다. 고객 간 session·cache·log·backup 혼합도 확인한다.

### C3 · P1 — operator-plane을 이름만 분리하면 agent가 승인을 위조할 수 있다

- **[근거]** 제안의 `agent-plane과 operator-plane`은 같은 UID·credential·browser session에서 승인 위조가 가능하다고 명시한다. [고정 Hindsight tenant source](https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-api-slim/hindsight_api/extensions/builtin/tenant.py#L8-L90)의 기본 noauth와 단순 API key는 principal별 bank ACL을 제공하는 근거가 아니다.
- **[INFERENCE] 실패 시나리오:** agent shell이 `approve` CLI를 실행하거나 browser credential을 재사용해 export를 승인한다. CLI가 DB를 직접 수정하면 service의 정책·revision 검사를 우회한다. 고정 port에 fake service가 먼저 떠도 주소만 확인한 adapter가 고객 자료를 전송할 수 있다.
- **최소 수정:** service가 인증된 principal의 권한과 scope를 결정하고 CLI/MCP 모두 같은 domain authorization을 거친다. 정상 관리 CLI는 direct DB writer가 되지 않는다. 강한 인간 승인 주장은 agent가 사용할 수 없는 principal 또는 operation digest에 묶인 실제 human-presence 경계가 있을 때만 한다. endpoint도 credential/peer identity와 결합해 확인한다.
- **채택 전 관측:** 같은 UID의 agent가 승인·정책 변경·export를 위조할 수 있는지, 다른 bank와 fake endpoint 접근이 거절되는지 확인한다. ordinary correction·source 범위 철회까지 매번 강한 승인을 요구할 필요는 없다. 허용된 자동 수정과 고위험 operator action의 경계를 정해야 한다.

### C4 · P1 — engine 재사용에서 가장 어려운 부분은 wrapper 밖의 commit 권한이다

- **[근거]** 제안은 “하나의 transaction에서 operation/event/outbox”와 CAS/fencing을 요구한다. Hindsight의 PG task broker·worker 존재와 “workers without conflicts” 문구는 이 제품이 요구하는 철회 후 stale publish 차단의 검증 결과가 아니다.
- **[INFERENCE] 실패 시나리오:** wrapper가 source revision을 확인한 뒤 engine에 retain/reflect를 요청한다. 작업 중 correction이 발생했지만 engine이 이전 결과를 나중에 게시한다. wrapper의 사전 검사만으로 engine 내부 commit을 막을 수 없다. engine 응답 유실 후 재시도도 domain operation과 대응되지 않으면 중복 작업을 만든다.
- **최소 수정:** canonical operation·source revision·publication 권위를 어디서 소유하는지 하나로 정한다. event/job intent의 durable commit 후 ACK하고, queryable 완료는 분리한다. retry ID는 scope와 결합하고 동일 ID의 다른 payload는 거절한다. engine을 projection으로 쓴다면 그 출력도 현재 revision·deletion boundary를 통과해야 한다. 필요한 내부 fence는 제한된 fork 대상으로 인정한다.
- **채택 전 관측:** commit 후 응답 유실, session 종료, 복수 stdio 시작, lease 만료 뒤 옛 worker 복귀, correction/취소와 reflect 완료의 경쟁을 확인한다. worker ID만 고정하는 것으로 fencing이 입증되지는 않는다. transport disconnect와 이미 수락된 durable job 취소도 구별한다.

### C5 · P1 — forget의 핵심은 삭제 API보다 재노출 방지다

- **[근거]** prior engine research §6과 [Hindsight delta source](https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-api-slim/hindsight_api/engine/memory_engine.py#L17575-L17646)는 consolidation pending에 따른 정정 지연을 설명한다. 제안은 별도의 최신 deletion head 없이는 backup restore를 열지 않도록 요구한다.
- **[INFERENCE] 실패 시나리오:** source 삭제 후 summary/cache가 남거나 이전 extraction이 재게시된다. 과거 backup을 복원하면서 같은 backup에 있던 옛 deletion ledger도 복원하면 철회 자료가 살아난다. connector의 오래된 spool도 이를 재수집할 수 있다.
- **최소 수정:** source lineage·revision을 따라 raw/claim/summary/vector/index/cache/pending work의 읽기와 게시를 통제한다. 최신 삭제 상태는 해당 회사 또는 개인의 신뢰경계 안에서 DB rollback과 독립적으로 복구 가능해야 한다. 최신성을 확인할 수 없으면 fail closed한다. 동일 content hash만으로 서로 다른 권리·retention의 source를 합치지 않는다.
- **채택 전 관측:** 철회와 worker 완료의 경쟁, mixed-source summary invalidation, 오래된 backup·spool 재입력을 확인한다. 논리적 비노출과 물리 purge/backup retention은 별도 계약이어야 하며 tombstone에 삭제 본문을 복제하지 않아야 한다.

### C6 · P2 — core 0줄 변경이어도 설치와 입력의 영향 범위는 넓다

- **[근거]** #334의 `CLAUDE_POINTER_LINES`와 공통 skill은 실제 전달 bytes를 바꾼다. `distribution-local-sources.ko.md` §8은 Claude의 local scope가 home 파일에 저장될 수 있고 hooks가 merge·상속되며 Codex global 지침도 입력에 합쳐진다고 설명한다.
- **[INFERENCE] 실패 시나리오:** 신규 installer가 global MCP/hook을 추가해 다른 고객 repo와 subagent에서도 capture가 실행된다. uninstall 때 파일 전체를 예전 backup으로 복원해 사용자의 후속 변경을 지운다. reviewer에게 global config를 상속시켜 독립성도 바뀐다.
- **최소 수정:** host integration은 명시적 opt-in으로 두고 정확한 profile/path/entry 변경을 보여준다. ownership metadata와 현재 값 비교로 자신이 소유한 미수정 entry만 갱신·제거한다. program uninstall, credential revoke, corpus purge, backup purge를 구별한다.
- **채택 전 관측:** fresh/reinstall/update/uninstall·부분 실패·사용자 후속 편집에서 보존을 확인한다. author와 isolated reviewer의 실제 config/tool catalog/input을 각각 확인한다. #334의 pointer 테스트는 이 신규 integration 검증을 대신하지 않는다.

### C7 · P2 — 같은 schema를 검색·모델 품질의 동일성으로 약속할 수 없다

- **[근거]** prior research §5.1: Hindsight native keyword arm은 true BM25가 아니다. local sources §5의 pgvector 문서와 managed PG 문서는 서로 다른 extension version을 설명한다. 제안도 다른 모델·compute의 출력/순위 동일성을 약속하지 않는다.
- **[INFERENCE] 실패 시나리오:** local에서 선택한 한국어 tokenizer extension이 managed PG에 없거나 embedding revision이 바뀌어 기존 index와 맞지 않는다. 한국어 correction이나 코드 exact identifier를 찾지 못하면서 두 배포가 “같은 memory”라고 표시한다.
- **최소 수정:** 공통 지원 PG/extension·tokenizer·parser·embedding revision/dimension과 migration 범위를 고정한다. scope ACL과 exact identifier 검색 경로를 포함한다. 공유할 것은 상태·오류·정정 의미이며 출력·순위·성능은 별도 품질 계약이다. 같은 모델 설정도 매번 같은 문자열 출력을 보증하지 않는다.
- **채택 전 관측:** 한국어·코드 identifier·scope 차단·업데이트·abstention·철회 fixture를 두 배포에서 비교한다. 승인 local 모델/compute가 없으면 full parity를 unsupported로 표시한다. reflect를 조용히 끄고 완료로 처리해서는 안 된다.

### C8 · P2 — Cloud Run을 기본 배포로 넣으면 worker 운영을 별도로 해결해야 한다

- **[근거]** cloud sources §7: Hindsight worker는 PG polling 방식이고 Run의 filesystem·CPU·instance lifecycle은 지속 VM과 다르다. Cloud Tasks는 기존 polling worker를 자동으로 push-handler로 변환하지 않는다.
- **[INFERENCE] 실패 시나리오:** API가 성공 응답을 보낸 뒤 내부 coroutine으로 추출을 계속하다 instance 종료로 중단된다. Tasks만 추가하고 PG commit→enqueue 간 gap을 방치하거나 두 queue가 서로 다른 완료 상태를 보고한다.
- **최소 수정:** 초기 cloud baseline은 지속 VM/Compose worker를 우선 검토한다. Run을 지원하려면 외부 durable DB와 실제 지원 worker entrypoint 또는 명시적 job handler/reconciliation을 정한다. startup migration은 replica마다 경쟁시키지 않고 release 절차가 소유한다. binary rollback과 schema/PG rollback도 구별한다.
- **채택 전 관측:** instance 교체·enqueue 실패·중복/순서 역전·model timeout·동시 migration·이전 stack restore를 확인한다. model RAM/CPU·DB connection·backup 비용까지 포함해야 하며 scale-to-zero만으로 운영비 우위를 주장할 수 없다.

## A/B/C 비교

| 선택 | C보다 나을 수 있는 현실 조건 | 한계와 판단 |
|---|---|---|
| **A: session child가 engine·DB·worker 소유** | 단일 사용자·단일 host·전용 DB이며 session 밖 처리를 요구하지 않는 제한된 환경. 전체 자동 pipeline을 session 중 수행하고 중단 작업의 다음 session 복구를 수용할 때 설치 부담이 작다. | **좁은 조건부 선택.** exclusive ownership·durable pending state·복구가 필요하다. 복수 host의 공유 memory와 Mac 종료 후 독립 cloud 접근의 기본안으로는 기각한다. child가 외부 service를 호출한다면 실질적으로 C다. |
| **B: 독립 service와 CLI/UI, MCP 없음** | 회사가 MCP를 금지하거나 승인된 내부 agent/SDK의 capture·recall API adapter가 이미 고정되어 있을 때. protocol/OAuth 호환성 부담을 줄일 수 있다. | **유효한 선택.** 자동 pipeline은 유지할 수 있지만 일반 CLI만으로 hosted native tool 연결을 해결하지 못한다. agent에게 관리 credential을 주어 연결을 대신해서는 안 된다. |
| **C: 공통 service와 필요한 MCP adapter** | 여러 실제 소비자가 같은 지속 memory 권위를 사용하고 session 밖 worker 진행을 요구할 때. | **조건부 기본안.** local HTTP + remote HTTPS부터 제한한다. stdio-only 소비자가 입증될 때만 shim을 추가한다. CLI/UI도 실제 관리·승인 요구에 맞춰 선택한다. |

C의 장점은 동일한 domain 권위다. 그러나 service discovery, credential, protocol compatibility, capture adapter와 설치 lifecycle을 제품이 책임져야 한다. “한 번 설치하면 어디서나 자동 동작”이라는 약속을 붙이면 이 장점보다 미검증 지원 범위가 더 커진다.

## engine 재사용/신규구현 비교

아래 6개월 비용은 정량 견적이 아닌 **유지관리 책임의 상대 비교**다. 인력·corpus·사용량 근거가 없어 금액이나 출시 기간을 확정할 수 없다.

| 경로 | 6개월 동안의 주요 부담 | 핵심 불변식 소유권과 판단 |
|---|---|---|
| **Hindsight MIT 재사용·필요한 고정 fork** | upstream 보안/버그 변경 검토, 제한된 patch 유지, schema/PG/model 호환성, offline artifact와 host adapter 운영. 기존 extract/recall/reflect를 활용하므로 초기 부담은 줄일 수 있다. | **우선 후보지만 조건부.** ACL·revision/fencing·정정/철회 publication을 외부 wrapper만으로 강제할 수 있는지 불명확하다. 필요한 fork 범위가 크면 비용 이점이 줄어든다. |
| **새 PG 중심 core** | 전체 자동 추출·hybrid recall·reflect, lineage·worker 복구·invalidation·restore·품질·설치까지 직접 유지한다. | 불변식의 소유권은 가장 명확하지만 구현과 검증 부담이 가장 크다. 기존 engine의 필수 계약을 경제적으로 보완할 수 없다는 근거가 생길 때 선택한다. |
| **proprietary vendor API의 공개 wrapper** | wrapper 코드는 작을 수 있으나 API/auth 변경, 가격·retention·export·host 지원과 vendor 장애에 의존한다. | **이 요구의 주 경로로 기각.** 내부 불변식을 소유하지 않으며 동일 OSS engine의 local/cloud 배포도 아니다. 승인된 개인 managed 서비스라는 별도 선택지는 될 수 있다. |

**[INFERENCE] local/cloud를 별도 engine code fork로 해야 할 제약은 packet에서 입증되지 않았다.** OS/arch artifact, offline bundle, supervisor, 추론 endpoint, cloud auth와 backup 절차는 별도 package/profile이 필요하지만 공통 engine 분리의 이유는 아니다. managed PG의 extension 제약은 먼저 공통 지원 범위로 해결해야 한다. 해결할 수 없다면 기능·품질 차이나 unsupported 조건을 공개해야 한다.

고정 fork는 영구 동결을 뜻하지 않는다. 두 배포가 같은 fork/release를 사용하고 보안 업데이트·upstream merge 책임을 유지해야 한다. code license와 모델 weights/runtime의 재배포 권리도 별개다. offline bundle에는 정확한 artifact·model revision, signature/digest 검증 자료, license/NOTICE와 복구 가능한 이전 release가 필요하다.

## 영향 범위

| 대상 | 실제 영향 |
|---|---|
| **#334** | 선택적 memory 참고와 규칙 제안의 지침, installer pointer와 문서 설명이 바뀐다. 신규 runtime·store·sync는 없다. |
| **author** | opt-in MCP와 hook이 tool result·prompt·호출 비용·capture 범위를 바꾼다. memory 추출물은 현재 source/spec/AGENTS보다 높은 권위가 아니다. |
| **reviewer** | 사용자 home·memory·MCP·개인 credential의 격리를 유지해야 한다. 공통 skill 전달량은 늘어난다. worktree `AGENTS.md` 영향은 별도 미해결 문제다. |
| **회사/외주 운영자** | DB·model·권한·artifact 반입·patch·backup/restore·retention 책임이 생긴다. 고객별 경계는 endpoint label만으로 완성되지 않는다. |
| **개인 cloud 운영자** | TLS/OAuth·host onboarding·secret rotation·worker·DB·backup을 운영한다. 관리형 PG도 memory 철회 의미를 대신 처리하지 않는다. |

memory service의 철회는 이미 host context, provider native memory, 생성된 문서나 commit에 복제된 내용까지 자동으로 없애는 보장이 아니다. 이 삭제 경계도 사용자에게 보여야 한다.

## 채택/조건부/기각 판단과 strongest dissent

**채택할 설계 원칙:** 공통 engine/domain release와 독립 회사·개인 배포, 설치와 MCP의 결합, session과 분리된 durable worker 권위다.

**조건부 선택:** 필요한 HTTP MCP만 제공하는 C와 Hindsight 재사용을 우선 검토한다. 실제 필수 불변식을 소유하기 위해 필요한 최소 fork는 허용하되, wrapper만으로 해결된다고 가정하지 않는다. 개인 cloud는 VM/Compose를 초기 운영 기준으로 삼을 수 있다.

**기각할 약속:** 모든 hosted agent 자동 지원, local storage만으로 no-export, 고객 데이터의 개인 cloud sync, proprietary wrapper를 동일 OSS engine으로 표기하는 것, image 교체만으로 schema rollback이나 forget-restore가 해결된다는 주장이다. A/B 자체는 위의 좁은 환경에서 기각하지 않는다.

**가장 강한 반대 의견은 “C가 잘못된 구조”가 아니라 “C를 채택해도 가장 중요한 호스트 자동화 요구가 충족되지 않는데 운영 제품의 표면만 먼저 크게 만들 수 있다”는 것이다.** offline 모델 반입, 고객 격리, capture/export adapter, OAuth, protocol 호환성, installer와 두 cloud topology까지 한꺼번에 약속하면 6개월 유지관리 범위가 과해진다. 회사에서 승인된 내부 agent만 필요하다면 B가 더 합리적이고, 제한된 단일 사용자 환경이면 A도 낫다.

따라서 먼저 **지원할 정확한 host와 배포 profile**, **전체 pipeline의 승인 경로**, **engine 내부에서 강제해야 할 불변식**을 확정해야 한다. 자동 capture/extract/recall/reflect/correction/retraction은 유지하되, 구현할 수 없는 표면은 unsupported로 남기는 것이 정직한 결정이다. Reflect는 근거 연결 문서와 응답을 갱신하는 기능이지 모델 가중치 학습이나 매 실행의 개선 보장이 아니다.
