### 9. 실제 Opus 5.5 / Codex 6.1 Sol xhigh 병렬 적대적 리뷰

서브에이전트를 동시 실행하고 **각 실행 담당자가 해당 native CLI를 실제 호출**했다. 실행 담당자의 기본 모델에 이름만 붙여 결과를 대체한 것이 아니다. 두 모델은 위 고정 PR diff·제안·공식 source 조사로 구성한 **동일한 전체 입력 180,322 bytes**를 받고, 상대방의 리뷰를 보지 않았다. 도구/별도 web research 없이 packet을 공격한 설계 리뷰다.

| 실제 모델 | CLI와 설정 | 관찰한 native 결과 |
|---|---|---|
| Claude Opus 5.5 | Claude CLI `2.1.296`, `--model claude-opus-5-5 --effort xhigh`; empty cwd·safe-mode·tools 없음·strict empty MCP·no session persistence | exit0, JSON success/is_error=false, `modelUsage` canonical key=`claude-opus-5-5` |
| Codex GPT-6.1-Sol | Codex CLI `0.162.1`, `--model gpt-6.1-sol -c model_reasoning_effort="xhigh"`; empty cwd·auth-only isolated CODEX_HOME·ignore config/rules·ephemeral·read-only | exit0, native runtime banner=`gpt-6.1-sol / openai / xhigh`, 외부 명령/도구 호출 marker 관측 없음 |

성공 실행 중첩은 **2026-10-11 05:46:41.978–05:49:22.900 UTC, 160.922초**였다. 두 output hash를 다시 계산하고, Opus JSON의 원래 result와 저장한 리뷰 텍스트의 byte-equivalent 문자열 일치도 확인했다.

증거의 한계도 구분한다. Opus의 server-resolved effort는 반환되지 않아 CLI에 `xhigh`를 전달한 것 이상으로 attestation할 수 없다. Sol의 model/provider/effort는 native runtime banner 관찰이며 숨은 provider-side attestation은 아니다. 첫 Opus 실행은 실행 담당자가 불필요한 HOME 격리를 추가해 인증실패했으므로 리뷰로 계상하지 않고 별도 실패 기록으로 보존했다. 원래 인증 환경으로 정정한 성공 실행만 위 표에 포함했다. native CLI는 사용자 상태 파일(`~/.claude.json`) 메타데이터를 갱신했으며 내용/Keychain 불변까지 검사하거나 주장하지 않는다. credentials·세션 UUID·raw stderr/JSON은 이 댓글에 게시하지 않는다. 로그인·설정편집·설치·모델 fallback 명령은 사용하지 않았다.

**이 리뷰는 새 제안의 적대적 검토이지 #334의 Agent Flow run/gate approval이 아니다.**

#### 9.1 두 리뷰의 주요 반례와 채택 판단

아래 severity/ID는 각각 native 리뷰의 표기다. **구현이 없는 새 제품의 위험·수용 조건**이며 #334에서 공격에 성공한 취약점 목록이 아니다. 모든 관측 기준은 아직 제품에서 미실행이다.

| Native findings | 실제로 공격한 지점 | 통합 판단·수용 조건 |
|---|---|---|
| **Opus O1 P0·O7 P1 / Sol C2 P1** | 회사 작업의 같은 UID/global catalog에 개인 endpoint가 있으면 정상 write로 고객 원문이 개인 cloud/backup에 전송. local DB도 cloud host prompt까지 포함한 no-export 보장 아님 | 분리 수용. 회사/고객·개인의 home/session/token/DB/backup/egress를 별도로 강제. 회사 정책은 **local 저장+approved egress / no-external-egress·완전 air-gap / prerequisites 부족으로 unsupported**를 구분. installer profile marker만으로 보안 경계를 증명하지 않음 |
| **Opus O2 P1 / Sol C1 P1** | catalog는 연결됐지만 capture가 없거나 다음 task가 recall을 안 해 자동 loop 미완성. curl/IAM 통과와 native MCP/OAuth 사용도 다른 관측 | host×surface×version/plan별 capture trigger·recall/auth·coverage/watermark를 지원 단위로 고정. **사후 export/import 자체는 자동이 아님**; 승인된 event/schedule이 실제 자동 실행해야 자동 capture라고 표시. 모델이 가끔 retain하는 경로와 수동 import는 따로 표시 |
| **Opus O4 P1 / Sol C3 P1** | 같은 UID/browser/Compose.env의 approve CLI·direct PG·fake loopback endpoint로 operator 권위 위조 | CLI/UI는 service API client, DB credential 없음. 모든 transport가 같은 auth/scope 통과. 일반 scoped correction/retraction과 high-risk export/정책변경/scope병합/대량purge/directive승격 분리. **soft tombstone/undo는 물리 purge나 법적 삭제의 대체물이 아님** |
| **Sol C4 P1** | wrapper가 revision을 사전 확인해도 correction 뒤 engine 내부 stale retain/reflect commit이 나중에 게시 | Hindsight 재사용은 조건부. **publication/fencing/deletion을 실제 commit/read 지점에서 강제**할 수 있어야 함. gateway-only 보장 기각. 필요한 최소 backend patch/fork를 비교하고, 비용이 크면 새 PG core를 선택. 독립 원장 두 개를 권위로 두지 않음 |
| **Opus O5 P1 / Sol C5 P1** | DB와 old deletion ledger를 함께 restore, stale worker 완료, 이전 spool 재수집으로 철회 자료 부활 | 최신 deletion authority는 DB rollback/그 backup과 독립적으로 복구 가능. 최신성 확인 불가면 read fail closed. stable source identity·lineage·revision·operation digest로 raw/derived/cache/job/read/publish 경계를 통제. 해시만 붙여 해결됐다고 하지 않음. host/native/provider copy 삭제는 별도 범위 |
| **Opus O6 P1 / Sol C6 P2** | global hook 상속·tracked `.mcp.json`이 다른 사용자/cloud/reviewer에 전달, uninstall 전체 backup 복원으로 사용자 후속 편집 소실 | 기본 service-only 설치+host integration 별도 opt-in. dedicated/untracked local profile 기본, team-tracked 설정은 별도 공동 승인. owned entry/current-value 조건으로 update/remove. core 0줄≠author/reviewer 입력 영향0 |
| **Opus O3 P1 / Sol C7 P2** | tokenizer/PG extension/model dimension/revision 차이로 한국어·코드 lexical recall parity 깨짐 | 첫 baseline은 공통 release·PG/extension을 맞춘 local/cloud VM stack. managed PG는 **호환 extension/검색 fixture를 확인한 경우**만 지원하며 원천 불가라고 단정하지 않음. semantic contract와 출력·순위·품질 parity 분리 |
| **Opus O8 P2 / Sol C8 P2** | Run 응답 후 worker 중단·volatile DB·IAM/OAuth·enqueue gap·replica migration·image만 rollback | 개인 cloud 기본은 persistent VM/Compose+durable PG+실제 engine worker. 외부 IdP 재사용·migration one-shot ownership. Run은 real worker/reconcile/compatibility 경계 검증 후 별도 profile. 여러 cloud runtime과 자체 OAuth AS를 처음부터 구현하지 않음 |

#### 9.2 모델 간 차이와 최강 반론

- **Opus:** 새 memory 엔진 전부를 다시 쓰기보다 **Hindsight 기반 독립 OSS distribution**(installer·배포 profile·capture·접근경계·필요한 backend patch)을 더 강하게 권고했다. public OSS의 호환/보안 대응 책임부터 커지는 점과, 회사에서 상주 service가 금지될 수 있다는 반례도 제시했다.
- **Sol:** 재사용의 핵심 위험을 **wrapper 바깥 engine 내부 commit 권한**으로 좁혔다. 정확한 host 자동화 지원이 없으면 installer/OAuth/cloud topology만 커지는 것이 C의 가장 강한 반론이라고 봤다. managed PG를 조건부 선택으로 남겼고, A/B도 실제 제약에 맞으면 유효하다고 했다.
- **통합 판단:** C를 **local HTTP 우선의 C′**로 좁혀 채택한다. 엔진은 Hindsight 재사용을 우선 비교하되 ACL·fencing·철회·검색/복원을 제품이 실제 강제할 수 있어야 한다. 불변식을 wrapper-only로 못 지키면 backend patch/fork가 필요하다. fork 유지비가 재구현보다 크다는 근거가 생길 때 새 PG core로 전환하며, 두 엔진을 처음부터 동시 지원하지 않는다.
- **A를 일괄 금지하지 않는다.** 회사가 session subprocess만 허용한다면 같은 engine/PG·exclusive owner·durable pending queue·다음 session catch-up을 검증한 유한 실행 profile은 가능하다. “session 중에만 진행”이라는 운영 차이를 명시한다. session 종료 뒤 처리·복수 host 공유·Mac 없는 cloud 접근의 기본안은 아니다.
- **B도 일괄 금지하지 않는다.** 회사가 MCP를 금지하고 승인된 SDK/CLI/API capture·recall integration을 갖춘 경우 전체 pipeline을 운영할 수 있다. 그러나 일반 CLI 설치만으로 hosted chat 연결까지 된다고 하지 않는다.
- 공개 source를 먼저 내는 것 자체를 금지하지 않는다. 다만 공개 repo/registry 등록과 **production-ready·모든 host 지원** 표시는 별개다. Opus의 “비공개 운영검증 후 공개”는 유지관리상의 반론이며 사용자 요구를 임의로 비공개 제품으로 바꾸는 결론으로 채택하지 않았다.

#### 9.3 #334 PR의 Standards와 Spec — 별도 축

| 축 | Opus 신규 리뷰 | Sol 신규 리뷰 | 근거에 따른 판정 |
|---|---|---|---|
| **Standards** | 제공 diff의 hard violation을 찾지 못함. docs범위·정본 drift·byte 수용·draft 표현·#333 ledger 별도 PR를 judgement로 제안 | hard violation을 찾지 못함. 소비자 없는 stdio/vendor abstraction은 Speculative Generality 후보, transport/권한 경계인 adapter를 무조건 Middle Man으로 보지 않음 | hard violation 없음이라는 관찰을 approval로 바꾸지 않음. 소비자 없는 표면은 추가하지 않음. **ledger 분리 제안은 미채택**: 아래 고정 maintainer 정책이 다음 작업 PR에 누락 merged PR 기록을 보충하도록 요구 |
| **Spec** | host-memory 참고/원문 재확인/tracked teamrule/설치·reviewer 설명이라는 좁은 spec에는 부합. “No separate pipeline” 범위 한정과 shared-company memory의 별도 의미를 지적 | 좁은 spec에 부합. 새 runtime 부재는 원 spec 누락 아님. 실제 pointer bytes/skill 지침 영향과 PR 보고·실행 증거를 구분 | #334를 새제품 구현/승인으로 확대하지 않음. native/user-owned memory와 회사 shared service는 동일한 권한 의미가 아님. 외부 context 접속은 별도 opt-in/policy. 기존 CI·phase budget 수용·sealed review 미완료 상태를 유지 |

Opus의 ledger judgement는 packet에 main 정책 원문이 없는 상태에서 나온 의견이다. 부모가 이후 [고정 `maintainer/verification-policy.md`의 회귀 대조/design3](https://github.com/chonamdoo/agent-flow/blob/642d1792edf0b22bda2bb879ac65df145273dc19/maintainer/verification-policy.md#회귀-대조)를 읽어 **누락된 merged PR은 다음 작업 design에서 보충해 그 작업 PR에 포함**한다는 기준을 확인했다. 따라서 #333 원장 기록을 #334에서 빼는 결론을 내리지 않는다. 원 native 리뷰 텍스트는 수정하지 않았다. 이번 요청으로 PR 본문/코드는 편집하지 않는다.

### 10. 최종 권고와 명확한 불가능 조건

**별도 OSS는 좋은 방향이고, 기본 제품 형태는 “설치되는 공통 memory service + 필요한 MCP 연결 + 별도 operator 도구”다.** #334에 장기 runtime을 끼워 넣는 대신 독립 repo/release로 둔다. 회사 로컬과 개인 cloud는 **같은 engine을 두 곳에 배포**하고 corpus/identity/host/backup은 나눈다. 두 engine fork가 필요하다는 근거는 없고, 두 deployment/egress/host adapter·운영 절차는 반드시 필요하다.

처음부터 새 엔진·여러 storage backend·관리형 SaaS·Cloud Run·모든 host plugin·필수 stdio shim을 한꺼번에 약속하지 않는다. **Hindsight 기반 공통 distribution + local HTTP / 개인 VM remote HTTPS**를 우선 대상으로 삼아 전체 자동 pipeline과 불변식의 소유권을 검증한다. model weights/runtime·OS/arch별 artifact는 같은 release의 명시적 profile이지 byte-identical binary 약속이 아니다.

아래는 단순한 환경 설정 차이가 아니라 요구를 만족할 수 없는 조건이다.

1. 회사/고객 자료 반출이 금지인데 그 내용을 읽어야 하는 개인 cloud agent를 사용: 승인된 별도 경계 없이는 양립 불가. VPN/tunnel/local DB로 이름만 바꿔 해결되지 않는다.
2. 회사가 필요한 DB/service/모델·compute를 금지하고, 동일 domain을 충족하는 승인 유한 실행 대안도 없음: full pipeline 지원 불가. manual-only/reflect-off로 몰래 축소하지 않는다.
3. hosted host가 승인된 capture·native read/write/auth·다음 task recall 경로를 제공하지 않음: 그 surface의 자동 pipeline은 미지원. 직접 운영 VM/SDK는 별도 실행 표면이며 모든 hosted 제품 지원의 증거가 아니다.
4. agent와 operator의 실제 권한이 같은데 인간 승인·고객 경계·DB 직접 접근 차단을 보장한다고 주장: 해당 강한 보장 불가. plain profile/버튼/marker로 해결되지 않는다.
5. 최신 철회 상태를 old backup과 독립적으로 회복/확인하지 못함: forget-restore 보장 불가, 조회를 fail closed해야 한다.

이 조건을 숨기지 않으면 **코드는 공통으로, 회사·개인 데이터와 운영은 분리해서** 요구를 충족하는 제품을 설계할 수 있다. 이번 결과는 그 설계·영향·반례 분석의 완료이지 실제 memory 제품 완성/연결/운영 인증은 아니다.

### 11. 로컬에 보존한 재검증 자료

사용자 작업 디렉터리의 `research/`에 새 조사·고정 PR source·동일 reviewer packet·unmodified native 리뷰·각 실행 evidence·판정표·parallel proof를 보존했다. 고객/개인 corpus나 실제 memory server credential은 입력/게시물에 넣지 않았다.

- 동일 입력: `distribution-review-input.ko.md`, SHA256 `36d909bc0a8a024b958b76edb23bf7d62c77b1c780e99216a0835aa4d24455a5`.
- Opus 원문: `distribution-review-opus-5.5-xhigh.ko.md`, SHA256 `9fe356983dd512a8817d90dec631cf913123c9af2d98fb86d81e07748c10aa0a`.
- Sol 원문: `distribution-review-codex-6.1-sol-xhigh.ko.md`, SHA256 `44328e620c5fef598c5205cb51a48aa5aab6685626e3d5853134d3b78a097b39`.
- 독립 실제 실행 proof: `distribution-native-parallel-proof.json`; native output hash/Opus JSON result 일치, 두 성공 실행 overlap 확인.
- 추가 조사: `distribution-local-sources.ko.md`, `distribution-cloud-sources.ko.md`; 고정 PR: `distribution-pr334-source.json`; 원문을 변경하지 않은 채 반례의 수용/부분수용·미채택 근거는 `distribution-disposition-opus.ko.md`, `distribution-disposition-sol.ko.md`.
