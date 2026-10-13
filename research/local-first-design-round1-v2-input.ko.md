# Current execution scope — superseding the planning-only scope

The latest user explicitly requests install latest https://github.com/chonamdoo/agent-flow, configure it for this Python local-memory-service project, and actually execute the final plan using Agent Flow. This is now an implementation delivery, not only docs; cloud still deferred until complete local behavior and1–2week real use. Parent is installing latestmain in a separate pinned checkout without replacingglobaltools/settings. Currentinstalled AgentFlow0.3.14; officialmain pyproject0.3.15 atHEAD0ffba881a0c3f1c20f41359f205ef4e517ed5482. Latestfreshinstaller leavesrootAGENTS/CLAUDE untouched and hasexplicitnative skill entry. Currenttargetrepo hasunbornmain, no commits, untrackedresearch; preserveexistingresearch, establishonlytaskownedbootstrap beforeAgentFlowisolatedworktree. Dockerbinaryexists butdefaultColimadaemonoff; Colimaavailable, no productdb/modelruntime testedyet. Do NOTdowngradefullsemanticsorpretendfake/SQLiteprobesasPGproduct. Recommenddecision-complete locallyimplementablearchitecture, moduleboundaries andbehavior-specificacceptance that canactually beexecuted; nativehosttrustnotautoapprovable. Peerround2 willincludecompletedSIE/storageOSSresearch and revisedconcreteimplementation contracts.

# 독립 설계 토론 1라운드 — 같은 입력, Korean answer

Latest user request: prior proposals now need complete implementable architecture + local-first plan, not only recommendation. Agent Flow and independent Claude Code/Codex/omp must work for normal prompts and many workflows. Correctness/consistent calls required; don't pretend LLMs are deterministic. No meaningless session-load context. Explicitly confirm Python official MCP2 viability. User now requires Superlinked SIE and relevant OSS across protocol, engine, DB/search, durablejobs, security, backup, modelruntime/licenses; two source scouts currently researching those updates, and BOTH models will receive the same completed updates in round2. No cloud provisioning; complete local semantic loop first, run it, actual1–2week usage, then personal cloud. Never send companycorpus to personalcloud. Exact3 rule activation scopes: this localproject / myprojects / team-or-project shared. No whole rules inrootCLAUDE.md/AGENTS.md. No forcedteamdistribution forpersonalprojectrule.

Execution honesty: source studies and actual SDK wire probe below are distinct. Repo onlyresearch, no productruntime. Previousproposal records older independent model reviews, NOT newcollaborative review. You must reconsider those decisions with newsourcefacts. Host source capability doesnotproveinstalledbinarywire success. FastMCP/library version isnotMCPprotocol major. Current actual Python2.3 SDK probe usedsameHTTPendpoint modernstore+legacyread+autodiscoverread+modernread withexactpublicsyntheticnote; notnativehost/PG/productproof.

Round1 task: choose a coherent concrete best architecture and enumerate strongest consumer-visible failure modes, ownership boundaries, data/API states/errors, identity/branch/fork/compaction handling, minimalon-demand contexts, fullsemanticchain, installer/modules/localimplementationmilestones, 1–2week trial hardstops/cloudcontract. Mustadversariallybreak ownpreferredarchitecture, especially unforkedHindsight+extension/authority proposal: engineinternalworker scope exceptions, stale commits, untaggeddirectives/sharedobservations, tombstone outside restoredschema, causalread fence beforeLLMnotonlypostfilter. Alternatively ownednarrowPGengine must preserveextract/recall/reflect/correction fullbehavior, notdowngrade tolocalnotes/rules/SQLitekeyword-only. Pick exactlywhichauthorityownsextraction/consolidation work; two independentqueues cannotbothownsame job. Distinguishsourcegroundedreuse from hypotheticalhooks orcheapfork. PythonSDK2 official oneedge dualera isnow proven techscenario: no needinventtwocores.

Output Korean 5–9 substantive sections, ideally~12–20KB (not a hard truncation), conclusion first, exacttradeoffs, defendable decisions and uncertainties. Cite packetfile/source URLs insteadofinventinglineevidence. Include 5–8 questions/issues for peer toattack, and explicitly which newevidence wouldchangeyourchoice. Do not claim implementation/test/nativehooks/productionproof. Do not fetch or use tools; only suppliedinput. Parentwill give BOTH newround1answers and OSSsourceupdates inround2; then you will respondpoint-by-point topeer andrevise.


---
## FROZEN SOURCE: research/unified-memory-pipeline-proposal.ko.md
# 메모리 파이프라인 최종 제안: 같은 제품, 분리된 배포, 설치형 서비스와 얇은 MCP

**추천은 독립 `agent-memory-mcp` 설치형 서비스 + PostgreSQL + 얇은 MCP + opt-in Claude/Codex 어댑터다. 회사와 개인은 같은 release·schema·operation 계약을 사용하되 데이터와 실행 환경은 분리한다.** MCP는 접속 수단이고 서비스 설치는 운영 방식이므로 둘 중 하나를 선택하는 문제가 아니다.

엔진 개발의 기본 선택은 **고정 Hindsight를 필요한 통제 변경까지 포함해 우선 재사용**하는 것이다. 전체 memory engine을 처음부터 다시 만들지는 않는다. 다만 MCP wrapper만 추가한 Hindsight를 기업용 완료 제품으로 부르지 않는다. 실제 publication/read/reflect/retraction/restore 경계의 통제와 유지 범위를 통과해야 채택할 수 있다. 이 조건을 만족하지 못하거나 변경 범위를 유지할 수 없으면 **좁은 PG core로 교체**한다. 두 generic engine을 나란히 운영하는 안은 아니다.

이 선택은 설계 판단 **[INFERENCE]** 이다. 절대적인 최고 검색 품질·최저비용을 실측한 결과가 아니다. 구현, 회사 계정 승인, token 절감, 보안 및 복구 통과는 아직 입증되지 않았다.

## 1. 실제 병렬 리뷰 근거

두 executor 서브에이전트가 요청한 native CLI를 각각 실제 호출했다. 최종 입력은 같은 v2 원문 529,500바이트다. 모델 간 답변이나 이전 native 답변은 서로의 최종 prompt에 넣지 않았다. parent가 최종 input/output의 byte 수와 SHA-256을 다시 계산해 각 receipt와 일치함을 확인했다.

| Native 실행 | 요청 모델·설정 | 관측 근거 | 최종 성공 구간(UTC, 2026-10-11) |
|---|---|---|---|
| Codex CLI 0.162.1 | `gpt-6.1-sol`, `model_reasoning_effort="xhigh"` | runtime banner `gpt-6.1-sol / openai / xhigh`, exit 0 | 15:13:44.311–15:26:25.869 |
| Claude Code 2.1.296 | `claude-opus-5-5`, `--effort xhigh` | native JSON `result/success`, `is_error=false`, `modelUsage`에는 `claude-opus-5-5`만 존재, exit 0 | 15:13:32.601–15:23:45.538 |

**실제 native 프로세스 실행 구간의 겹침: 601.227초.** provider 내부 GPU scheduling의 병렬성이나 숨겨진 모델 동작까지 증명한 것은 아니다. Opus 응답은 server-resolved effort를 반환하지 않았으므로 xhigh 설정 전달과 그 내부 실행 강도는 구분한다. Codex banner도 독립 provider attestation은 아니다.

최종 공통 input SHA-256:
`e2f36bcaa958e6af9d0854c0498afe890da49483c043845ef6ef62e23a4a0de9`

- [병렬 실행·hash 확인](unified-native-parallel-proof.json)
- [Codex native 원문](unified-review-codex-6.1-sol-xhigh.ko.md), [실행 receipt](unified-review-codex-6.1-sol-xhigh.evidence.json)
- [Opus native 원문](unified-review-opus-5.5-xhigh.ko.md), [실행 receipt](unified-review-opus-5.5-xhigh.evidence.json)
- [최종 동일 input](unified-review-input-v2.ko.md), [manifest](unified-review-input-v2.manifest.json)

보완 전 v1은 최종 검토에 포함하지 않는다. v1에 빠진 generic Serena/claude-mem 비교와 원래 제공된 9개 cue claims를 보완하고 두 모델 모두 fresh v2 invocation을 실행했다. Codex의 폐기된 v1 원문은 재구성하지 않았다. 웹·코드·논문 자료는 공통 packet으로 조사·검증해 전달했으며, native 모델 두 개가 이번 실행에서 독자적으로 웹 browsing한 것은 아니다.

## 2. 두 모델의 차이와 최종 판단

P0/P1은 미구현 설계의 위험과 출시 차단 조건이지, 현재 저장소에서 재현된 취약점 등급이 아니다. 모델별 severity를 평균내거나 투표로 결론을 만들지 않았다.

| 쟁점 | Codex 판단 | Opus 판단 | 최종 제안 [INFERENCE] |
|---|---|---|---|
| 서비스와 MCP | 설치형 service + thin MCP | 동일 | session 밖 service/worker가 DB·작업 생명주기를 소유한다 |
| 엔진 | 통제 변경을 포함한 Hindsight+PG를 기본 후보로 유지 | 좁은 PG control core+hybrid를 기본으로 하고 Hindsight는 조건부 projection; fork는 반대 | 재사용을 우선하되 내부 통제·유지 범위를 채택 조건으로 고정한다. 실패 시 교체하며 이중 engine은 금지 |
| 회사 모델 경로 | 승인 coding host와 새 worker 경로의 권한을 구분 | route manifest 없으면 default/fallback 반출 또는 추출 중단 | 회사 native host는 유지. 목적별 approved route가 없으면 전체 자동 pipeline 미지원으로 표시 |
| 승인 | exact revision·selectors까지 권한 결합 | scope 문자열 유지로 applicability를 확대할 위험 | 세 옵션 그대로 유지. 새 대상/적용 조건 확대는 재선택·승인, 보통 내용 갱신은 scope 유지 |
| 필수 규칙 | 첫 행동 이전 결정론적 선택·전달 필요 | 독립 rule bundle/resolver와 deny-once barrier 제안 | 메모리 의미 검색과 규칙 전달을 분리. 추가 context+allow만으로 처음 생성된 Write를 허용하지 않는다 |
| 같은 UID | 악성 같은 UID라면 OS/VM/sandbox 경계 필요 | 분리 HOME을 지원 조건으로 제안하나 same-UID 한계도 언급 | HOME 분리는 설정 혼용 방지일 뿐 강한 격리가 아니다. 실제 permission 경계가 필요한 환경은 OS identity/VM/sandbox/managed credential 격리 |
| 철회·복원 | 내부 reflect/read/commit fence까지 필요 | 한 권위 schema와 lineage·백업 밖 ledger 필요 | 출처·revision·deletion epoch를 실제 commit과 내부 합성 입력에서 확인; 결과 post-filter만으로 대체하지 않음 |
| context 비용 | 전달된 context는 서버 cache와 다름 | resume 재생·반복 주입·긴급 철회 강조 | ID/revision별 중복 억제, 작업별 예산, compact/resume 재평가. 이미 보낸 원문을 원격 삭제했다고 주장하지 않음 |

Opus의 가장 강한 반론은 받아들인다. 승인·episode·capture·rule delivery를 어차피 직접 소유하면서 Hindsight 내부까지 고치면 재사용 이익보다 유지비가 커질 수 있다. 반대로 Opus의 좁은 core도 자동 추출·recall·근거 기반 reflect·worker·복구·한국어 품질을 제공해야 하므로 작은 schema라는 이유로 공짜 대안이 되지는 않는다. 현재 두 구현의 유지비나 동일 조건 품질 실측이 없으므로 기존 연산 재사용을 우선하되, 막연한 '최소 patch'를 성공 조건으로 두지 않는다.

## 3. 공통 제품과 분리해야 할 배포

**동일한 것:** source/event envelope, episode identity, evidence/candidate/rule 구분, 승인·revision·삭제 의미, API/operation 상태, migrations, 상태 점검·backup/restore 절차, host adapter 계약.

**동일하다고 약속하지 않는 것:** 모델 출력, embedding/ranking, 응답 지연, hardware 및 관리형 인증·배포 환경. 같은 pipeline은 동일한 의미와 불변식을 뜻한다.

| 구분 | 회사·고객 프로젝트 | 개인 프로젝트 |
|---|---|---|
| 배포 | 회사 PC의 승인된 local service/PG/worker 또는 승인 내부 환경 | persistent VM의 같은 release/PG/worker |
| 접속 | 기본 loopback 또는 private IPC; 필요할 때 thin stdio shim | HTTPS MCP, OAuth/audience·issuer 확인, 서버-side 권한 |
| 저장 | raw·summary·vector·rule·spool·log·backup 모두 해당 회사/고객 경계 | 개인 cloud 경계; 암호화·retention·backup·restore 운영 |
| 추론 | 이미 승인된 업무 host + 별도 승인된 목적별 worker route | 명시적으로 선택한 개인 route |
| 연동 | 프로젝트별 배포 바인딩. 개인 endpoint/key로 fallback 없음 | 회사 corpus를 가져오거나 합치지 않음 |

개인 cloud의 암호화는 TLS와 disk/backup 보호를 기준으로 한다. 서버가 본문을 검색·추론하는 기본 설계이므로 client-only key를 쓰는 서버 평문 비접근 E2EE를 보장하지 않는다. cloud 운영자는 신뢰 경계 안에 있으며 key 관리·rotation도 운영 책임이다.

회사 메모리를 집 개인 cloud에 자동 동기화하는 기능은 없다. 외주 고객 간 corpus/credential/backup도 섞지 않는다. 개인 집 cloud를 쓰는 것은 개인 데이터의 별도 배포이지 회사 local memory의 원격 복제본이 아니다.

상주 service/PG/worker 설치와 승인 내부 대체 환경이 모두 불가능하면 같은 full pipeline을 제공할 수 없다. session child를 '동등한 간단 버전'으로 몰래 바꾸지 않는다. daemon 설치, 디스크, model 반입, 컨테이너 사용/라이선스는 명시적인 운영 조건이다.

## 4. 보안: 팀 계정과 memory route는 별개

회사 Claude/Codex Team/Enterprise를 사용한다는 전제는 유지한다. 그것을 오프라인 모델로 강제 대체하지 않는다. 다만 다음은 다른 승인이다.

- coding host의 해당 회사 workspace에서 처리하는 행위
- 별도 worker의 API/headless observer·classifier·embedding·reranker·reflect 처리
- provider의 저장·보관, telemetry/trace, third-party sync

`no-training`, `no-public-disclosure`, `no-storage-outside-company`, `no-egress`를 같은 보장으로 취급하지 않는다. SaaS 추론 자체도 전혀 밖으로 나가면 안 되는 strict no-egress와 양립하지 않는다. 회사가 승인한 SaaS 처리 예외와 새 memory 저장 반출 금지를 분리해서 설정한다. strict profile은 승인된 내부 host·compute·모델이 있을 때만 가능하다.

서비스/worker는 목적별 허용 route를 명시하고 개인 provider env/key를 상속하지 않는다. 승인되지 않은 default/fallback, 모델 weight 첫 실행 다운로드, telemetry를 허용하지 않는다. 실제 반출 차단은 managed host·credential·OS/network 정책에서 집행한다. MCP token이나 `_meta.clientInfo`, bank tag, repo 경로만으로 이후 어떤 모델/계정에 답변이 보내지는지 증명할 수 없다. 회사 데이터를 자유로운 BYO client에 제공하면서 이후 목적지까지 통제한다고 약속하지 않는다.

agent-plane에는 DB·operator credential·규칙 publish 권한을 주지 않는다. loopback에도 설치별 인증과 endpoint identity, Host/Origin 검증이 필요하다. local UI의 승인 클릭이 같은 UID에서 위조 불가능한 인간 승인인 것처럼 표현하지 않는다. 강한 공유 승인은 별도 approver 권한이나 기존 사내 PR/IdP 정책으로 처리한다.

### HOME 분리 반례의 실제 관측

별도 0700 HOME 디렉터리 두 개, 다른 HOME의 0600 synthetic marker로 `/usr/bin/env HOME=... /bin/test -r ...`를 실행했다. 같은 OS UID 프로세스는 그 파일을 읽을 수 있다고 판정했다(exit 0). 실제 credential은 읽지 않았다. 임시 파일은 제거했다. **HOME 분리는 accidental config/capture 혼용을 줄이지만 같은 UID filesystem 격리는 아니다.** 다른 OS 사용자 또는 제품 sandbox의 차단을 시험한 것은 아니다.[관측](unified-home-boundary-smoke.json)

## 5. full memory loop와 영상에서 가져올 것

자동 capture → durable ingest → 신호·claim 추출/선택 → scope에 맞는 recall → 현재 유효한 근거를 사용한 reflect → 정정/철회 → 후속 작업에서 재사용을 유지한다. MCP tool로 수동 메모 몇 개 저장하는 것으로 이 요구를 대체하지 않는다.

- MCP는 대화 전체나 native memory 파일을 자동 수집하지 않는다. 지원 host의 승인 hook/event/export adapter가 필요하다. 첫 작업 전 recall, transcript 지연, interrupt, 실패/child event, 서비스 readiness를 각각 정의한다.
- envelope에는 host/session/root-run/agent/message/event ID, source span/digest/offset, snapshot·branch·유효 조건, 잘림/coverage를 남긴다. parent/child/handback/종료 export는 같은 episode가 중복 기록될 수 있으므로 재전송과 독립 반복을 구분한다.
- **codebase findings / human corrections / recurring investigations**를 구분한다. 인용된 AI 로그는 human correction으로 승격하지 않는다. 계획·permission approval·도구 실행 결과·사실 정정·규칙 수락은 다른 event다.
- 원문, AI 추출, 참고 메모리, candidate, 승인 rule, 실행 skill은 서로 다른 권위를 가진다. 반복 횟수·confidence·Jev 확률·typed schema는 승인을 대신하지 않는다.
- 오류·mismatch·correction을 다음 동작의 근거로 연결한다. trace를 저장한 것만으로 다음 run이 개선됐다고 주장하지 않는다. 거절한 candidate를 문구만 바꿔 계속 재제안하지 않으며 새 근거를 구분한다.
- 원문 영상의 2 cents/session은 발표자의 해당 작업 수치다. 우리 제품 단가나 token 절감량은 아니다. BAML은 선택 가능한 typed extraction 도구, Query BAML은 해당 호출 관측 도구다. Jev는 선택적 판단 서비스이며 기본 security/approval authority로 넣지 않는다.
- health check·stale detection·fourth input은 시연 기능과 후속 아이디어를 구분한다. 코드 변화는 재검토 근거이지 자동 공통 규칙 변경 권한이 아니다. hidden chain-of-thought는 수집하지 않는다.

사용자가 정정한 특정 앱의 codegraph 재사용·SQLite/FTS5 최소 구성안은 이 설계의 요구나 결론에서 제외했다. SQLite라는 일반 backend 대안을 금지한 것이 아니라, 다른 앱 설계를 이 memory 제품에 잘못 적용한 결론을 제외한 것이다.

## 6. 컨벤션과 skill: 정확한 세 적용 범위

새 candidate를 활성화하거나 범위를 바꿀 때 정확히 다음 세 가지를 제시한다.

1. **내 로컬·해당 프로젝트**: 이 PC/프로젝트에서 적용. 팀 배포·Git commit/push를 강제하지 않는다. 회사 자료면 여전히 회사 경계 안에 남는다.
2. **프로젝트 공유**: 해당 프로젝트의 권한자가 검토·승인한 revision을 배포한다.
3. **팀 공통**: 해당 팀의 승인 권한과 팀/project 바인딩을 확인한다.

로컬 추천은 선택 전 자동 적용이 아니다. 취소/미응답은 candidate만 보존한다. 권한이 구성되지 않은 옵션은 세 선택지에서 없애지 말고 사용 불가 사유를 표시한다.

기존 내용 갱신은 scope를 유지하지만 새 revision 승인 규칙은 유지한다. 대상 device/project/team 추가, selector/phase 확대, required 여부 등 실제 적용 조건 확대는 scope 문자열이 같아도 재선택·권한자 승인을 요구한다. 승인은 본문·조건·예외·대상·selector의 exact revision/digest에 결합한다. 승격 시 이전 로컬 활성 revision을 계속 별도 권위로 두지 않는다.

원문 정본은 scope별 하나다. 승인 bundle의 본문 정본, 활성/철회 ledger, native host projection은 역할을 분리한다. Git 파일·PG 행·Hindsight directive가 서로 독립적으로 '현재 팀 규칙'을 선언하지 않는다. host 캐시는 projection이며 activation 권위가 아니다.

## 7. root-free 전달과 context 예산

팀 공통 규칙도 root `CLAUDE.md`/`AGENTS.md`에 **본문·목록·import bridge를 새로 넣지 않는다**. 기존 사용자의 지침을 삭제하는 뜻은 아니다. 같은 긴 본문을 unscoped `.claude/rules`나 passive skill로 옮겨 startup에 모두 로드하는 것도 피한다.

- memory MCP는 소수의 고정된 짧은 도구/스키마와 instructions만 공개한다. 전체 memory/rule catalog를 접속마다 전달하지 않는다. host의 deferred discovery가 지원되면 사용하되 universal 지원이나 0 token을 약속하지 않는다.
- 필수 규칙은 승인 scope + task/phase + 예정/변경 path의 명시 predicate로 결정한다. 선택적 참고 memory만 semantic top-k로 찾는다. mandatory 원문이 예산을 넘으면 작업 분할/범위 조정 또는 보호 대상 행동 차단이지 규칙 누락이 아니다.
- task가 정해진 시점과 첫 보호 대상 행동 전에 필요한 원문을 전달한다. 새 path에서 미전달 필수 rule이 생겼다면 지원 hook/wrapper가 행동을 거절하고 규칙을 받은 뒤 재계획하게 한다. PreToolUse에서 context만 추가한 뒤 이미 생성된 첫 Write를 allow하면 사전 준수 보장이 없다.
- Claude scoped rules와 Codex의 명시 skill identity·지원 hook/wrapper는 다른 구현이다. Codex nested AGENTS를 일반 lazy path loader로 부르지 않는다. Bash/IDE/외부 writer도 matcher 경계를 벗어날 수 있으므로 검사 가능한 규칙은 lint/CI, 보안은 ACL/sandbox/egress로 집행한다.
- session×rule ID/revision delivery receipt로 재주입을 줄이되 compact/new-thread/resume에서 유효성을 다시 본다. 서버 cache TTL이나 token 폐기는 이미 transcript/context에 들어간 내용을 지우지 못한다. 긴급 철회는 managed 보호 행동/세션을 중단하고 새 context가 필요할 수 있다.

보편적으로 적용되는 필수 규칙의 내용까지 0 context로 만들 수는 없다. 줄일 대상은 **무관한 본문·전체 목록·반복 주입**이며, token 숫자는 startup/첫 recall/장기 세션/compact-resume와 backend 추론을 분리해 실제 host에서 측정해야 한다.

## 8. authority·worker·삭제·복구

한 canonical PG authority에 durable event/operation과 outbox를 묶어 commit한다. `accepted`는 durable commit 후 반환하며 `accepted≠queryable`, `unavailable≠empty`를 유지한다. 원문을 별도 object store에 놓는다면 원자성·orphan·retention을 별도 해결해야 하므로 기본은 PG/persistent disk 중심으로 둔다.

Hindsight를 채택하려면 wrapper 밖 내부 writer/reader/consolidation/reflect/mental model/directive/refresh/import 경로까지 통제 지점을 명시한다. source generation·승인 revision·deletion epoch·lease fencing/CAS를 실제 publication transaction과 합성 입력에서 확인한다. lineage가 불완전하거나 전체 근거가 철회된 파생물을 사용할 수 없게 한다. 최종 응답 post-filter만으로 이미 오염된 내부 합성을 정상으로 만들지 않는다.

같은 source 재import·오프라인 spool·늦은 worker·old backup으로 철회된 자료가 부활하지 않게 scope-bound source identity와 본문 없는 tombstone을 유지한다. restore는 과거 snapshot과 별도로 신뢰할 수 있는 최신 deletion head를 확인·재적용하기 전 공개하지 않는다. logical export/import를 point-in-time backup으로 부르지 않는다.

logical retraction, physical purge, backup retention 완료는 서로 다른 상태다. raw·derived·index·cache·spool·jobs·exports·rule projection을 범위에 포함한다. 이미 외부 모델에 전달된 context나 provider retention까지 원격 삭제할 수 있다는 보장은 하지 않는다.

## 9. OSS와 인프라 비교에서 채택·제외하는 이유

같은 full loop·출처·승인·철회·host·운영 계약으로 비교했다. 서로 다른 model/dataset/token budget/judge의 vendor score는 순위표로 쓰지 않는다. 이 비교는 packet에 고정한 snapshot의 조사 결과이고 모든 repo/release의 완전 감사는 아니다.

| 선택 | 유용한 부분 | 동일 요구에서 남는 비용·판단 |
|---|---|---|
| Hindsight + PG | 기존 retain/recall/reflect·consolidation·operations 재사용 | 기본 route/trace/tenant와 내부 retraction·transfer·read/commit 경계 보강. 채택 조건을 통과하는 단일 engine 우선 후보 |
| 좁은 PG core + extraction primitive | source/episode/approval/deletion 권위를 직접 정의 | worker/검색/reflect/한국어 품질/복구 책임이 사라지지 않음. Hindsight 통제 변경의 유지가 불가능할 때 교체 후보 |
| claude-mem | 실제 native capture/observer·progressive retrieval 패턴 | local SQLite와 hosted PG/BullMQ·read-only hosted MCP의 parity를 가정하지 않음. startup 기본 observations와 silent skip·subscription observer 권한을 그대로 복사하지 않음 |
| Serena | versioned Markdown·명시 reference·필요한 본문 읽기 | 전체 name list의 비용, database/hook 배제, raw/REPL의 read_only 우회. full 자동 pipeline이나 ACL 대체는 아님 |
| Mem0 / Graphiti / LangMem | fact memory / episode·temporal / 추출·reflection primitive | OSS/Platform 차이, group·UUID 권한, history·derived purge, experimental MCP, 앱의 durability·approval 책임 확인 필요 |
| Honcho / Cognee / Cavira / Letta / Supermemory | peer reasoning / corpus pipeline / governed identity / continuity / managed UX | 라이선스, 다층 저장소·운영, purge/restore, harness 변경 또는 비공개 engine. 같은 공개 OSS+업무 host 유지 조건에서 자동 승자 아님 |
| session MCP / CLI-only / skills-only | 설치 entry / 관리 / 승인 절차 표현 | 각각 service 생명주기·공통 접속·durable 전체 loop를 단독으로 대체하지 못함. 기본 서비스의 adapter/admin/projection으로 사용 |
| SQLite 일반 대안 | single persistent-disk 운영 단순화 가능 | 전체 worker/승인/삭제/auth 책임은 유지. 회사/개인에 PG와 SQLite 두 의미를 병행하는 기본안은 선택하지 않음 |
| GCP/Tasks/GCS/Vertex/Neo4j | 관리형 queue/worker·graph 질의 | 회사 local parity, 다중 저장소 원자성·삭제·복구·비용 증가. graph/multi-hop 이익·규모가 입증되기 전 기본에 추가하지 않음 |

고정 primary-source 비교 및 논문 근거는 [OSS 조사](github-memory.ko.md), [논문 조사](papers.ko.md), [원문 영상 재분석](video-mAKUL12h1n8-reanalysis.ko.md), [추가 Serena/claude-mem 검증](unified-additional-oss-sources.ko.md)에 있다.

## 10. MCP 2026-07-28과 SIE localhost

공식 protocol revision은 `2026-07-28`, SDK semver는 별개다. 공식 changelog/transport 문서와 Python SDK 2.3.0·TypeScript SDK 2.3.1 release를 확인했다.[M1–M4]

- 새 wire에서 initialize/initialized와 protocol session/Mcp-Session-Id가 없어지고 request metadata를 사용한다. application memory DB와 durable jobs는 여전히 상태를 가진다.
- `server/discover`는 필수 server method지만 모든 client의 새 handshake라는 뜻은 아니다. MRTR은 input-required interaction을 처리한다. 독립 server request 제거를 모든 notification/SSE 제거로 확대하지 않는다.
- `Mcp-Method`와 protocol version을 전달하고 `Mcp-Name`은 named methods에 해당한다. request-scoped SSE/POST subscriptions는 남는다. stdio도 남는다.
- `ttlMs/cacheScope`는 cache freshness이며 auth/revocation을 대신하지 않는다. Roots/Sampling/Logging 등의 폐기는 즉시 삭제가 아니고 earliest removal을 구분한다.
- SIE pinned package는 `mcp>=1.9,<2`다. SDK1의 `stateless_http=True`가 새 protocol 지원을 증명하지 않는다. local edge는 configured `SIE_BASE_URL` cluster를 호출하므로 모든 실제 처리가 local이라고 말할 수 없다. CLI 기본 bind와 DNS-rebinding 설정을 그대로 기업 기본값으로 복사하지 않는다.[M5]

### 실제 protocol/state smoke

공식 Python `mcp==2.3.0`으로 localhost real HTTP server와 temporary SQLite를 실행했다. client A가 synthetic note를 저장하고 종료한 뒤 별도 client B가 같은 note를 조회했다. 최종 실행 exit 0. 네 wire 요청에서 `2026-07-28`, method/name, namespaced metadata를 관측했고 initialize 및 request/response `Mcp-Session-Id`는 없었다. 이는 **protocol 무상태와 application DB 지속성이 양립함**만 입증한다. Hindsight 제품, native host protocol 협상, 보안·capture·company auth·token 절감·crash recovery는 시험하지 않았다. 최초 throwaway assertion은 plain dict 출력의 structured-content 가정을 잘못해서 실패했고 명시 Pydantic output schema로 수정한 최종 관측과 구분한다. temporary script/data는 제거했다.[관측](mcp-2026-localhost-verification.ko.md)

## 11. Agent Flow와 다른 프로젝트의 영향

#316/#334/#341은 역할·규칙·reference 원칙을 검토하는 근거다. memory engine 구현이라고 취급하지 않는다. 사용자가 알린 #341 rollback은 현재 ground truth이며 이 조사에서 재설치하거나 되살리지 않았다.[A1–A3]

| 영역 | 필요한 변경 | 이익 | 책임/위험 |
|---|---|---|---|
| 독립 memory 제품 | API/operation·PG authority·engine 통제·worker·auth·lifecycle | 어떤 coding host에서도 같은 memory 의미를 제공 | 실제 구현/품질/보안·복구 검증 필요 |
| Claude/Codex 어댑터 | opt-in capture·readiness·recall·rule resolver/projection·version support matrix | Agent Flow 없이 사용 가능, root-free 선택적 로딩 | host hook/hash 승인·순서·Bash/IDE 한계, 종료·compact·resume |
| Agent Flow | 기본 core/runner/installer **0줄 변경**; optional adapter에서 phase/path·선택 이유 원칙 참고 | coupling·전용 framework 강제 없음 | author memory 입력은 행동·비용을 바꾼다. 격리 reviewer에 global memory/MCP/home을 상속하지 않기 |
| 회사/외주 운영 | 고객별 배포·관리 host·approved route·operator·offline artifacts·backup/restore | 저장/반출 경계 유지 | 팀 계정만으로 승인 완료가 아님. 설치·compute 조건 없는 환경은 full 지원 불가 |
| 개인 cloud | persistent VM/volume·TLS/OAuth/ACL·device token·encrypted backup | 같은 release의 다중 기기 사용 | patch·rotation·복구 운영, single VM을 HA로 홍보하지 않기 |
| 승인/컨벤션 | 세 범위 UI·exact revision·거절/재제안·활성/철회 ledger | local-only 및 공유 정책을 같은 모델로 처리 | 승인 피로와 정책 충돌, selector 확대 검사 |

Agent Flow의 전체 resolver·runner·worktree gates를 재사용하지 않는다. native Agent Skills 표준과 Agent Flow의 phase/reason selector를 같은 것으로 부르지 않는다. 독립 어댑터를 raw Claude Code/Codex에서 먼저 검증하고 Agent Flow는 같은 opt-in consumer로 둔다. MCP가 연결되는 web/mobile/IDE라도 capture나 첫 행동 전 rule 전달이 없으면 full automation 지원으로 표시하지 않는다.

## 12. 사용자 제공 9개 파일의 포함 범위

9개를 모두 직접 읽어 byte/hash inventory를 만들었다.[인벤토리](unified-downloads-source-coverage.json)

1. `memory-pipeline-research.md`
2. `verified-claims.json`
3. `video-summary.ko.md`
4. `transcript.timed.en.txt`
5. `transcript.en.txt`
6. `research-index.ko.md`
7. `open-source-memory-comparison.ko.md`
8. `project-memory-pipeline.ko.md`
9. `baml-jev-verification.ko.md`

두 모델에 9개 AI 문서를 무비판적으로 모두 원문 주입한 것은 아니다. 정확한 사용자 timed transcript 전체와 9개 cue claims를 v2에 넣었고, generic 자료는 primary-source 재검증 및 source-corrected 분석으로 넣었다. 특정 앱 적용안은 의도적으로 제외했다. 기존 retained transcript는 millisecond timestamp/header만 다르고 **1,511 cue의 발화 텍스트는 모두 원본과 같음**을 비교했다. v2는 supplied original timed 파일을 사용한다. 자막은 YouTube 자동 caption이며 word-level 수동 전사가 아니다. 첫 한국어 영상의 직접 자막 부재는 유지하며 screenshot/공개 자료보다 강한 주장을 하지 않는다.

## 13. 착수 전 확정할 검증 기준

아래는 미실행 acceptance이며 지금 통과했다고 표시하지 않는다. 수동/reflect-off/rules-only로 줄여 전체 제품이 완성됐다고 표시하지 않는다.

1. **company route와 경계:** 같은 public/synthetic 자료로 approved host의 정상 경로를 유지하면서 개인 endpoint·provider env·다른 project/client·fake loopback·operator/DB 접근을 거절한다. raw/derived/log/backup/skill과 실제 network egress를 확인한다.
2. **engine 재사용 가능성:** source/approval/deletion generation의 통제를 모든 commit/read/reflect/refresh/import 경로에서 보인다. 전체 grounding 철회·stale worker·old import·backup restore 후 부활이 없어야 한다. 이를 유지할 수 있는 patch 범위와 담당 책임을 확인한다. wrapper-only는 탈락이다.
3. **native host full loop:** pinned Claude/Codex 각각에서 cold start·MCP 지연·transcript 지연·interrupt·child 중복·실패·세션 종료 후 worker·다른 기기 recall을 관찰하고 coverage/accepted/queryable oracle을 일치시킨다.
4. **세 범위와 root-free:** cancel/미응답·위조 승인·revision 불일치·selector 확대·Git 없는 local 활성화·권한 없는 team 승격을 확인한다. root 수정 없이 새 파일/rename/glob/Bash/subagent/compact/resume에서 첫 보호 대상 행동 이전 전달과 행동 차단을 따로 확인한다.
5. **동일 조건 품질·비용:** 같은 model/embedding/corpus/token budget으로 no-memory, matched hybrid/RAG, 선택 engine의 후속 coding task를 비교한다. 한국어 부정·임시 예외·코드 식별자·사실성·출처·범위·false promotion·prompt poisoning을 포함한다. write/read/reflect/reprocess/host injection/human review/storage/운영을 합산한다. paper/vendor 숫자나 영상 단가를 목표 실측으로 쓰지 않는다.
6. **설치·업데이트·복구:** 회사 local과 개인 VM의 clean/offline install, 동시 client, migration interruption, update/rollback, reinstall/uninstall, restore를 실행한다. binary rollback≠schema rollback이며 config/data ownership 밖을 덮어쓰지 않는다. offline 모델·SBOM·license·signature/pins·installer 권한을 확인한다.

**최종 선택:** 서비스/PG/worker authority와 root-free rule plane을 분리하고, MCP·host adapter는 얇게 유지한다. engine은 검증 가능한 Hindsight 재사용을 우선한다. 이번 설계에서 확정할 수 없는 부분은 engine 내부 통제 변경의 유지 가능성과 실제 host 품질/비용이며, 이를 모른 채 engine 점수나 작은 구현 크기로 승자를 선언하지 않는다.

## 공식 출처와 관련 자료

- [M1] https://modelcontextprotocol.io/specification/2026-07-28/changelog
- [M2] https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http ; https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/stdio
- [M3] https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.3.0
- [M4] https://github.com/modelcontextprotocol/typescript-sdk/releases/tag/v2.3.1
- [M5] https://github.com/superlinked/sie/blob/c571e0a75d804cb6d49795a99cd03ea901307a69/packages/sie_mcp/README.md ; https://github.com/superlinked/sie/blob/c571e0a75d804cb6d49795a99cd03ea901307a69/packages/sie_mcp/pyproject.toml
- [H1] https://github.com/vectorize-io/hindsight/tree/a9eeed77f9bce99d8f97d39a30d3281747300824 ; https://hindsight.vectorize.io/developer/installation
- [H2] https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-api-slim/hindsight_api/engine/reflect/retractions.py
- [C1] https://docs.claude-mem.ai/configuration ; https://docs.claude-mem.ai/hosted-server
- [S1] https://github.com/oraios/serena/blob/1de556f71569f3acfc0743e526dd60aca40a545e/docs/02-usage/045_memories.md ; https://github.com/oraios/serena/blob/1de556f71569f3acfc0743e526dd60aca40a545e/docs/02-usage/070_security.md
- [P1] https://arxiv.org/html/2410.10813v2 ; https://arxiv.org/html/2606.29914v1 ; 기타 논문 목록과 저자 실험의 한계는 [논문 조사](papers.ko.md)
- [V1] https://www.youtube.com/watch?v=0kVsv2WlL44 ; https://www.youtube.com/watch?v=aimqSS7qoIU&t=3993s ; https://www.youtube.com/watch?v=mAKUL12h1n8&t=500s
- [A1] https://github.com/chonamdoo/agent-flow/issues/316
- [A2] https://github.com/chonamdoo/agent-flow/pull/334
- [A3] https://github.com/chonamdoo/agent-flow/pull/341 ; [고정 PR 검토](pr341-spec-adoption.ko.md)
- [Host] https://code.claude.com/docs/en/hooks ; https://code.claude.com/docs/en/skills ; https://learn.chatgpt.com/docs/hooks


---
## FROZEN SOURCE: research/local-first-invocation-contract.ko.md
# 로컬 우선 설계 계약 — native 모델 토론의 반박 대상

상태: 구현 전 설계안 [INFERENCE]. 저장소에 현재 product runtime은 없다. 이 문서는 기존 제안의 요구를 줄이지 않고 호출·정확성·context·실사용 완료 기준을 구체화한다. 새 source 조사와 두 native 모델의 상호 반박으로 최종 설계를 확정한다. 코드 구현·회사 정책 승인·검색 품질 실측과 구분한다.

## 1. 범위와 보장

독립 설치 service/worker와 단일 PostgreSQL 권위, 얇은 MCP edge, Claude Code/Codex/omp 별 opt-in 어댑터. Agent Flow는 일반 consumer, framework core·installer·isolated reviewer에 memory 강제 없음. 로컬 full loop 완성 및 1~2주 실사용 뒤 같은 release를 개인 persistent VM으로 전환한다. cloud provisioning은 지금 하지 않으며 회사 corpus를 개인 cloud로 이동하지 않는다.

API/DB에서 보장할 것: 승인 범위·identity·revision·출처 검증, 같은 idempotency request의 같은 효과와 replay 의미, stale publish 차단, 명시적 operation 상태, 제한된 결과 크기, source/derived 철회·복원 불변식. LLM의 사실 추출·순위·자발적 호출·준수를 100% 보장한다고 하지 않는다. 모든 workflow와 prompt가 같은 API를 사용할 수 있어야 하지만 MCP 등록만으로 매 turn 호출이 생기지 않는다. 자동화는 실제 지원 hook/wrapper 계약과 readiness를 검증한 surface에서 제공한다.

전체 loop는 capture→durable ingest→signal/claim extraction→scoped recall→grounded reflect→correction/retraction→next task. 승인 route가 없으면 extraction/reflect blocked를 노출하고 그 환경을 full 지원으로 표시하지 않는다. tool-only/manual/rules-only로 full 기능을 대체하지 않는다.

## 2. 호출 모델

- Agent-plane fixed small tool set candidate: `memory_context`(recall/explicit reflect), `memory_inspect`(선택 item의 근거·상태), `memory_record`(명시 note/candidate), `memory_feedback`(정정/거절/철회 요청). capture/approval/publish/admin는 별도 인증 API/CLI/UI. 최종 이름·schema는 모델 토론으로 한 세트 확정.
- native hooks와 omp extension, workflow wrapper, 일반 MCP 호출이 모두 같은 domain command handler를 사용한다. host별 ingest/search/승인 정책을 별도로 구현하지 않는다.
- producer가 보내는 event와 모델이 보내는 note를 구분한다. 모델 tool은 `human/approved` 권위를 자가 선언할 수 없다. 사업 session/root-run은 domain lineage이며 MCP wire session을 복원하는 우회 수단이 아니다.
- 회사/personal/customer 경계의 deployment identity와 project binding을 operator가 등록한다. repo remote·CWD·bank name·_meta.clientInfo는 권한 근거가 아니다. client credential은 principal/allowed deployment/project/purpose에 결합한다.
- server가 project를 임의로 추측해 default/global bank를 고르지 않는다. 미등록/모호한 repo·worktree·prompt project는 `BINDING_REQUIRED`다. 새 repo/project alias는 operator action. prompt에 path/phase가 없으면 unknown 상태를 보존하고 task-neutral approved 규칙과 일반 evidence만 제공하며 보호 대상 행동 전에 target resolution을 요구한다.
- workspace/worktree/fork/branch/file revision은 provenance/적용 조건, scope는 권한·공유 범위다. 동일 project의 다른 branch facts를 현재 code truth로 보여주지 않는다. 과거 facts는 historical 태그·validity로 분리한다.

## 3. 일관성·동시성 불변식

1. `schema_version`, domain command type, binding reference, client operation identity, causal minimum watermark, correlation ID를 명시한다. auth/role은 verified credential로 결정한다. model/client payload의 actor/scope 플래그는 권한을 늘리지 못한다.
2. protocol JSON-RPC request ID, MCP connection/session, operation ID, source event ID, root-run/episode identity, idempotency key는 서로 다른 개념이다.
3. 같은 `(principal, binding, command, idempotency_key)` + 같은 payload digest는 동일 effect/operation receipt. 같은 key + 다른 digest는 `IDEMPOTENCY_CONFLICT`. retry/reconnect/cancel 후에는 먼저 operation 상태를 조회하거나 같은 key를 replay한다. 삭제·승인 같은 변이는 새 key로 눈치껏 반복하지 않는다.
4. 최초 durable ingest와 outbox 등록은 한 PG transaction. producer spool flush와 server accepted는 다르다. `accepted≠queryable`, `unavailable≠empty`, `partial≠complete` 상태를 API/UI로 유지한다. exact-once delivery 대신 at-least-once delivery + effect dedup.
5. 단일 job lifecycle owner. engine 자체 operation/queue와 제품 ledger가 각각 final state를 선언하지 않도록 mapping/commit 책임을 명시한다. lease expiry·fencing token·expected generation/version으로 늦은 worker commit을 거절한다.
6. caller logical root-run과 child/handback/export dedup. actor role, typed human source, quotations, code snapshot, span, truncation/coverage를 보존한다. 동일 run 5개 event는 recurring investigation 5회가 아니다.
7. `memory_context`의 source selection/rule activation/permission은 명시 watermark snapshot. 모델 호출을 DB transaction 안에서 기다리지 않는다. reflect 완료 및 전달 전에 current source/permission/deletion eligibility를 다시 확인하며 stale이면 bounded re-evaluation 또는 `CONTEXT_STALE`다.
8. 읽기 linearization 지점과 취소/철회 순서를 계약한다. 철회 ack의 watermark 이후 요청은 최소 그 watermark를 요구한다. 이전에 시작/전달된 context가 자동 회수된다는 보장은 하지 않는다. 보호 행동은 latest policy check와 context generation이 필요하다.
9. timestamps는 기록/표시에 쓰고 최신 승인·lease·복원 권위를 client wall clock으로 결정하지 않는다. UUID/source ID collision·순서 역전·offset 재사용·파일 교체를 검출한다.
10. role/purpose 변경, scope 확대, body/selectors/applicability 수정은 exact revision에 결합. cancel/미응답 candidate only. local-only에 Git/team approval 강제 없음. 프로젝트 공유/팀 공통은 권한 있는 publication만 활성화.

## 4. root-free와 context 비용

- root CLAUDE/AGENTS에 새 본문·목록·bridge 없음. 기존 지침 삭제 아님. 다른 eager file/passive skill에 전체를 옮기지 않는다.
- session connect/start에서는 memory/rule 본문 0. fixed small schema만 노출. startup 모든 project·rule name list를 넣지 않는다. schema·native wrapper·server instructions도 실제 비용으로 측정한다.
- 작업이 정해진 때 deterministic approved rule routing; normal prompt의 phase/path unknown을 model 추측으로 허가하지 않는다. path가 새로 생기면 first-action barrier로 required minimal original을 전달하고 재계획하게 한다. semantic top-k는 optional memory용.
- per-request response budget을 bytes와 host/tokenizer의 actual rendered tokens로 관리. mandatory 집합을 예산 때문에 자르지 않는다. optional 내용부터 제외하고 부족하면 `REQUIRED_CONTEXT_OVER_BUDGET` 및 split/stop. 장문을 byte 중간에서 잘라 부정/예외를 없애지 않는다.
- private adapter API 응답의 control/receipt와 model_text를 분리한다. MCP consumer가 structured content를 전부 볼 수 있으므로 MCP 응답은 최소 stamp/coverage/citation 등으로 제한한다. detail은 inspect/status로 필요할 때만.
- delivery cache key는 principal/binding/purpose/context-generation/rule-ID/revision/policy epoch. host module-global dedup을 child sessions에 공유하지 않는다. compact/resume/newthread/fork 시 재평가. authoritative receipt와 client known-items는 권한을 대체하지 않는다.
- trace→memory→same prompt→trace recursive capture를 막는다. injected content/tool echoes는 source=user correction으로 승격하지 않고 source link/derived lineage를 유지한다.
- 최초 규칙은 pre-read/plan 단계에서 전달. PreToolUse additionalContext+allow만으로 이미 생성된 Write를 통과시키지 않는다. deny-once receipt도 미래 준수 보장이 아니며 CI/ACL/sandbox와 구분한다.

## 5. service·engine·model route

같은 PG/persistent topology를 회사 local과 이후 개인 VM에 쓴다. session child가 PG/worker owner가 아니다. thin stdio는 service client로만 필요 host에 제공한다. loopback + per-install auth + endpoint identity/Host-Origin 검사. shared company approval/DB privilege는 agent credential과 분리. HOME 분리만으로 같은 UID 격리를 보장하지 않는다.

Hindsight는 재사용 우선 후보지만 internal read/reflect/refresh/write/import가 canonical generation/retraction을 확인하는 bounded integration이 실제 source상 가능한지 평가한다. wrapper output-filter로 내부 합성 오염을 해결하지 않는다. 이를 유지할 수 없으면 단일 narrowPG core로 교체한다. 두 generic engine 병행·새 graph·Neo4j·Redis/object-store 기본 추가는 하지 않는다.

회사 approved Claude/Codex host는 유지. 새 worker/headless observer/API/embedding/reflect route는 별도 승인. allowed routes manifest·clean env·offline imported weights·no personal fallback·no implicit download/telemetry. native app-server/CLI 제공 기능과 회사 사용/구독 권한은 별개. no-training/no-storage/no-egress를 혼동하지 않는다. 클라우드에는 같은 제품 profile+TLS/IdP/approved routes만 추가; 지금 cloud 환경 부족은 local 검증을 막지 않는다.

## 6. 운영·설치·삭제

설치·project binding·host opt-in·service start는 별도 단계이며 global host config/rules 자동 overwrite 없음. owned config entry만 관리, uninstall은 data 보존이 기본이고 explicit purge는 별도. supervisor 하나, migration lock, readiness 구분, status/doctor에 capture watermarks·queue/blocked/error·protocol/capability/version 표시. service unavailable시 optional recall은 unavailable로, required protected action은 fail closed.

local spool bounded/권한/retention/backpressure·디스크 부족·무효 credential·permanent malformed job·retry exhaustion·crash recovery를 계획한다. queue는 durable PG, 다른 generic queue 기본추가 없음. 데이터·raw/derived trace 최소화; 본문은 삭제 가능 storage, immutable audit/tombstone에 삭제 본문 복제 금지.

forget/retract/physical purge/backup retention 완료를 분리. source·derived·index·cache·spool·job·exports·rule projections와 다시 import/replay되는 source identity를 통제. 과거 backup만으로 latest deletion head를 잃지 않는다. 복원 후 reconciliation 전 service 공개 금지. image rollback≠schema rollback. signed/pinned artifacts+SBOM/model/license/offline-model tests와 dataset versions, model prompt/parser/index generation 변경 시 reprocess 책임.

## 7. 로컬 구현·1~2주 실사용·cloud 전환

실행 순서의 완료 조건은 scope가 아니라 의존 관계다: contract/authority 결정→domain/PG durable operations/eligibility→통제된 engine/approved route→thin MCP와 three native host adapters→capture/rule/reflect/feedback/forget/restore 전체 smoke→local trial→cloud same release.

local completion은 Claude/Codex/omp 각각 normal prompt+workflow, new/resumed/compacted/forked sessions, same project cross-host recall, simultaneous writers/readers, error/cancel/replay, first-new-file rules, no-root-change, no-other-project/customer ingress, no-external unapproved inference, derived retraction/restore 전체 결과를 의미한다. source/docs만으로 runtime pass라고 쓰지 않는다. Agent Flow 없는 실행이 먼저 통과해야 한다.

trial은 개인 synthetic/public projects부터 시작, 회사자료는 별도 승인 후. 1~2주라는 날짜만 채우면 pass가 아니다. memory-on vs no-memory/동일조건 baseline을 비슷한 coding/review/일반질문 task로 관측: startup/turn/recall rendered tokens·extra roundtrips·p50/p95 local latency·candidate accept/reject/false promotion·중복/누락/blocked 작업·영구 실패·실제 후속 수정 품질·route/cost·운영시간. 수치 target은 측정 전 proposal로 표시하며 제품 성능으로 보고하지 않는다. 권한 혼선·반출·철회 부활·필수규칙 우회·silent capture gap이면 trial 중단/rollback. baseline root/user instructions와 private projects는 침해하지 않는다.

cloud 진입 조건은 local full acceptance와 trial guardrails 통과, same artifact/schema/policy semantics, persistent VM/TLS/auth/backup/restore 및 개인 route 결정이다. 지금 cloud account/infra를 만들지 않는다. 차후 데이터 이동은 개인 corpus의 명시 export/import 및 최신 deletion head·compatibility 검증; 회사 corpus는 이동하지 않는다.

## 8. 설계 산출물과 추가 검토 범위

최종 architecture와 domain/schema/command/result/error/operation-state 계약, scope/rule precedence, host/version/capability support matrix, local module/dependency structure, implementation milestones/acceptance matrix, token-budget instrumentation, install/update/runbook, local trial log와 cloud handoff 기준을 하나의 문서 세트로 연결한다. native model별 peer 반박·채택/기각·남은 disagreement와 실제 process/model/effort/input/output hashes를 보존한다.

추가 위험: same-UID credential/approval 접근, MCP2-only vs legacy host handshake, branch/worktree aliases, reused root-run IDs, schema/index/model drift, conflict/exception precedence, Unicode/한국어 부정·code identifier, recursion/poisoning, rate/resource budgets, observer effects, credential revocation/offline lease, disk/PG/worker failure, updates/rollback/restore source resurrection, supply-chain/licensing, provider retention and context already delivered. 위험마다 실제 domain/adapter/operations 책임과 acceptance를 매핑하고 무관한 multi-cloud/SaaS/HA scope는 추가하지 않는다.


---
## FROZEN SOURCE: research/local-first-host-evidence.ko.md
# 다중 host 통합: MCP wire·hook·lifecycle 근거 보고 (조사일 2026-10-12)

범위: 공식 문서·고정 source의 계약만 다룬다. 실제 runtime 성공, 제품 구현, native model 리뷰가 아니다. omp 문서는 설치본 기준(18.3 이상, 정확한 버전 미기록). Claude 문서는 버전 표기가 없고 v2.1.295까지 언급한다. Codex 문서도 버전 표기가 없다.

## A. 근거 사실 12개

**F1 omp는 legacy MCP client다.** `connectToServer()`는 initialize를 `2025-11-25`로 보내고 roots를 광고하며, `ping`과 `roots/list`에 응답한다(omp://mcp-runtime-lifecycle.md "Connection establishment"). 설치 문서 전체에 `2026-07-28`, `server/discover`, `resultType`이라는 표기가 없다. legacy `sse`는 2024-11-05다. 영향: 2026 전용 server에 연결하면 실패할 가능성이 높다 [INFERENCE: spec matrix 기준].

**F2 spec이 legacy client를 위한 합법적 경로를 정해 둔다.** versioning.md의 Compatibility Matrix 기준이다.
- Legacy client + Modern server는 실패, Legacy client + Dual-era server는 동작한다.
- dual-era server는 두 era를 같은 endpoint나 process에서 동시에 제공할 수 있다(MAY).
- initialize를 받으면 legacy semantics를 그 stdio process나 HTTP session 범위에서 적용한다.
- modern-only server는 initialize 오류에 지원 version을 적어야 한다(SHOULD).
- `serverInfo`는 보안 판단에 쓰면 안 된다(SHOULD NOT, discover.md).
- 끊긴 stream은 새 request ID로 다시 보내야 하며(MUST), `Mcp-Session-Id`는 제거됐다(changelog Major 1·9).
- 따라서 JSON-RPC id나 session은 idempotency key나 identity가 될 수 없다. cross-call state는 server가 발급한 handle을 tool 인자로 넘긴다.

**F3 host마다 MCP era가 다르다.**
- Claude Code: v2 runtime은 TS SDK 2.0 기반이며 2026-07-28을 지원한다. server에 지원 여부를 묻고, 지원하지 않으면 v1처럼 연결한다. feature flag를 가져오는 session은 v2.1.232 이상, 그 밖은 v2.1.274 이상에서 기본값이다. `MCP_PROTOCOL_NEGOTIATION=legacy`로 강제할 수 있다(code.claude.com/docs/en/mcp "MCP client runtimes").
- Codex: 문서는 initialize의 instructions를 쓴다고만 적고, 앞 512자를 권장한다. source commit `f2bee854`(2026-07-28)가 discovery, MRTR, legacy fallback(test 기준 2025-06-18)을 추가했다. 이 commit은 이전 조사에서 고정한 0.162.1 source `092d3acd`의 조상이다(GitHub compare 결과 ahead, behind 0). 설치본의 실제 runtime 동작은 확인하지 않았다.

**F4 model 입력 전 hook.**
- Claude `UserPromptSubmit`: `additionalContext`를 prompt 옆에 붙이거나 block할 수 있다. 기본 timeout은 30초이고, timeout이면 context는 버려지고 prompt는 그대로 진행된다. 막으려면 `onFailure:"block"`(v2.1.295 이상)이 필요하다. 사용자가 입력한 prompt 외에 scheduled task, background subagent 보고, 다른 session의 message에도 실행된다.
- Codex `UserPromptSubmit`: developer context를 추가하거나 block할 수 있고, matcher는 지원하지 않는다.
- omp:
  - `before_agent_start`는 일반 prompt와 dequeue된 batch마다 실행되며 같은 제출에 대해 재진입할 수 있다(최대 3회 시도). handler의 외부 side effect는 롤백되지 않는다.
  - `context`는 LLM 호출마다 message를 교체하고 저장하지 않는다.
  - `input`은 interactive와 RPC에서만 실행되고 print와 ACP에서는 실행되지 않는다(omp://extensions.md "Prompt and turn lifecycle").

**F5 tool 직전 차단과 context 전달 시점.**
- Claude PreToolUse: precedence는 deny > defer > ask > allow이고 deny 사유는 Claude가 본다. `additionalContext`는 tool result 옆에 붙는다. 사용자 정의 deny·ask rule은 hook 결과와 관계없이 계속 평가된다. `if` 필터는 best-effort이므로 강제가 필요하면 permission rule을 쓰라고 안내한다. timeout은 기본적으로 차단하지 않는다.
- Codex: deny, exit 2, legacy block을 지원한다. `updatedInput`은 allow와 함께일 때만 받는다. `ask`나 `continue:false`를 반환하면 hook이 실패로 처리되고 tool은 계속 실행된다. hosted tool(WebSearch 등)에는 hook이 없다. 문서 스스로 'complete enforcement boundary가 아니다'라고 쓴다.
- omp `tool_call`: block에서 short-circuit하고 handler throw나 timeout은 fail-closed다(30초). `additionalContext`는 tool이 실제로 실행되어 오류 없이 끝났을 때만 결과 뒤에 전달된다.
- 결론: context를 붙이고 allow하는 방식은 첫 쓰기 전에 규칙을 전달하지 못한다. 실행 전에 규칙을 보장하는 수단은 deny와 사유뿐이다.

**F6 compact·resume·fork 신호.**
- Claude:
  - `SessionStart`의 source는 startup·resume·clear·compact·fork다. v2.1.214 전에는 fork가 resume으로 보고됐다.
  - 주입한 text는 transcript에 저장되고 resume 때 hook을 다시 실행하지 않고 replay한다(값이 stale해질 수 있음). context를 회수할 수 없다는 근거다.
  - PreCompact는 block할 수 있고, PostCompact는 관찰만 한다.
  - skill은 compaction 뒤 skill당 5,000 token, 합계 25,000 token까지만 다시 붙는다.
- Codex:
  - SessionStart의 source에 fork가 없다.
  - compact 뒤 `source:compact`가 다음 요청 전에 실행되며 turn 중간에도 실행된다.
  - `thread/fork`는 새 id와 `forkedFromId`를 주지만 `sessionId`는 root 것을 유지한다(app-server.md).
- omp:
  - compact: `session_before_compact`(cancel 또는 교체), `session.compacting`(context, preserveData), `session_compact`.
  - fork: `session_before_switch`/`session_switch`를 reason fork로 내보내고, 새 id와 `parentSession`을 가진다. entry fork는 `session_branch`를 reason fork로 내보낸다.

**F7 child 상태 분리.**
- omp:
  - factory는 subagent마다 다시 bind되지만 module-level 변수는 공유된다(extensions.md L67).
  - `ctx.agent`(`kind`·`id`·`name`·`depth`·`parentId`)를 key로 써야 한다.
  - child는 parent의 MCP 연결을 공유하는 proxy를 쓴다(tools/task.md L190). server는 연결만으로 parent와 child를 구분할 수 없다.
  - `session_stop`은 subagent에서 발생하지 않고, `before_subagent_spawn`은 model 선택과 block만 할 수 있다.
- Claude:
  - tool hook에 `agent_id`와 `agent_type`이 들어온다.
  - SubagentStart context는 이미 child context에 있으면 다시 넣지 않는다.
  - fork가 아닌 subagent는 새 context에 CLAUDE.md 계층을 받는다(Explore와 Plan은 제외). fork는 전체 대화를 상속한다.
  - 이름으로 참조한 `mcpServers`는 parent 연결을 공유한다.
- Codex: subagent hook의 `session_id`는 parent 것이다. SubagentStart context는 child의 developer context로 들어가며 child 시작을 막을 수 없다. mcp_servers와 skills.config는 따로 지정하지 않으면 상속된다.
- 결론: 세 host 모두 session id만으로는 child나 fork lineage를 유일하게 식별할 수 없다.

**F8 출력 소유권, 동시 실행, 예산.**
- Claude: 여러 hook의 `additionalContext`가 모두 전달된다. 10,000자를 넘으면 파일로 넘기고 앞 2,000자 preview만 준다. async hook은 결정을 내릴 수 없다.
- Codex: 같은 event에 걸린 command hook을 동시에 실행한다. `additionalContext`가 약 2,500 token을 넘으면 temp 파일로 넘긴다. background hook은 session당 최대 8개다. MCP tool hook은 연결을 새로 만들지 않고, 오류가 나도 차단하지 않는다.
- omp: `tool_call`의 `input`은 마지막 handler 값이 적용되고, 같은 내용의 context는 중복 제거된다. `before_agent_start`는 첫 message만 유지한다.

**F9 관리자와 trust 설정이 hook을 무력화할 수 있다.**
- Claude:
  - `allowManagedHooksOnly`가 켜지면 user, project, local, plugin hook이 막힌다.
  - settings hook은 workspace trust를 확인한 뒤 실행된다.
  - SessionStart 시점의 `mcp_tool` hook은 launch 때 skip된다. command hook을 써야 한다.
- Codex:
  - 관리되지 않는 hook은 hash 기준으로 trust 받아야 실행된다.
  - project hook은 project가 trusted일 때만 실행된다.
  - `requirements.toml`로 hooks를 끌 수 있다.
- 회사 환경에서는 hook capability가 none일 수 있다.

**F10 schema 공개 지연과 hidden metadata.**
- Claude: tool search가 기본이라 처음에는 tool 이름과 server instructions만 load한다. 설명과 instructions는 2,048자에서 자른다. `_meta` key로 `anthropic/alwaysLoad`, `anthropic/maxResultSizeChars`(최대 500k), `anthropic/requiresUserInteraction`가 있다.
- omp: discoverable tool을 `xd://` catalog로 보이고 문서는 필요할 때 읽는다(settings.md L616-617). server instructions를 system prompt에 4,000자까지 붙인다. tool 호출 전에 `i` 필드 제거, 값이 빈 optional 생략, `local://`를 실제 경로로 바꾼다.
- vendor `_meta`는 host마다 다르다.

**F11 재전송 위험.**
- omp: MCPTool과 DeferredMCPTool은 retriable 연결 오류가 나면 reconnect 뒤 1회 재시도한다. 수락된 SSE POST 이후에는 다시 보내지 않는다. stdio는 자동 재시작하지 않고, manager가 backoff(0.5s→4s) 뒤 연결하며, 30초 안에 5회를 넘으면 circuit breaker가 작동한다.
- MCP 2026에서는 재전송할 때 request ID가 바뀐다.
- 따라서 상태를 바꾸는 operation에는 domain idempotency key가 필수다.

**F12 omp 규칙 파일 경로는 root-free 원칙과 맞지 않는다.**
- rulebook은 이름과 설명을 system prompt에 바로 나열하고, alwaysApply는 본문 전체를 바로 주입한다.
- TTSR은 stream을 끊고 주입하며, rulebook의 globs는 권고일 뿐 강제되지 않는다(rulebook-matching-pipeline.md §5-7).
- 승인된 규칙을 `.omp/rules`로 내보내면 eager listing이 생기거나 권위 있는 사본이 둘이 된다. 기본안으로 부적합하다.

## B. 공통 capability 어휘 [제안]

각 capability의 상태는 `native`, `partial`, `none`, `unknown` 중 하나이며, host·version별 manifest로 선언한다.

- `ctx.prompt`: model 입력 전 per-turn context
- `gate.prompt`: prompt 차단
- `ctx.session{startup,resume,clear,compact,fork}`: session 시작과 재평가 trigger
- `gate.tool.deny`: tool 실행 전 deny와 사유
- `tool.rewrite`: tool 입력 교체
- `ctx.tool.after`: tool 실행 뒤 context
- `ctx.child`: subagent 시작 context
- `lineage{session,agent,turn,tool_call}`: 식별자
- `fail_mode{open,closed,configurable}`: hook 실패 처리
- `ctx.persisted{replay,ephemeral}`: 주입한 context의 저장 여부
- `mcp.era{legacy,modern,dual}`: MCP era
- `capture.turn_end`: turn 종료 시 capture

## C. host별 matrix (문서·source 계약 기준)

| 항목 | omp(설치 docs) | Claude Code | Codex(docs/source) |
|---|---|---|---|
| mcp.era | legacy 2025-11-25 | v1 legacy, v2 dual | 문서는 initialize, source는 dual |
| ctx.prompt | before_agent_start, context | UPS additionalContext | UPS additionalContext |
| gate.tool.deny | tool_call block(fail-closed) | deny(기본 fail-open, onFailure 설정 시 차단) | deny/exit2(fail-open 추정) |
| ctx.session fork | switch/branch reason fork | source fork | none(app-server의 forkedFromId만) |
| compact | before, compacting, compact | PreCompact, PostCompact, SessionStart compact | Pre/Post, SessionStart compact |
| lineage | ctx.agent, toolCallId, parentSession | session, agent_id, prompt_id, tool_use_id | parent session_id, turn_id, agent_id |
| ctx.persisted | context는 ephemeral, 나머지 unknown | replay | unknown |
| 관리자 차단 | 없음(문서 기준) | allowManagedHooksOnly | trust hash, requirements |

## D. 오래된 initialize client를 위한 명시적 edge

omp, Claude v1 runtime, `MCP_PROTOCOL_NEGOTIATION=legacy`, Codex fallback 경로는 initialize를 쓴다. 이들은 dual-era server나 별도 legacy stdio edge에 붙을 수 있으며, spec은 Legacy + Dual-era를 동작하는 조합으로 정한다(versioning.md).

조건은 다음과 같다.
- 두 edge 모두 같은 domain operation, schema, handle, idempotency key, auth binding을 써야 한다.
- legacy session이나 `Mcp-Session-Id`, `clientInfo`를 identity, 권한, worker 상태로 쓰지 않는다.
- edge가 다르면 지원 범위를 다르게 선언한다(예: legacy edge에서 MRTR 없음).
- modern-only 배포가 omp에서 실패하는 것은 정상 결과다. 'v2만으로 모든 host와 호환'이라고 주장하지 않는다.

## E. 일반 prompt에서 project·phase·path를 모를 때 [제안]

- project: hook의 cwd를 git root로 해석해 정한다. 해석이 안 되면 `scope_unresolved`를 반환하고 화면에 보이게 한다. 개인 scope로 fallback하지 않는다.
- phase를 모르는 것을 wildcard로 취급하지 않는다. phase 조건이 있는 mandatory는 보내지 않는다.
- path 조건이 있는 mandatory는 첫 실제 path가 정해질 때 `gate.tool.deny`로 처리한다.
- optional semantic 결과는 별도 예산 안에서만 보낸다.
- 이미 전달한 rule ID와 revision은 lineage watermark로 중복을 막고, compact·resume·fork 때 다시 평가한다.

## F. local 수용 시나리오 [제안, 실행하지 않음]

1. dual-era stdio에서 omp initialize client와 modern client가 같은 operation을 호출하면 결과 digest와 revision이 같다.
2. modern-only server에 legacy client가 initialize를 보내면, 오류에 지원 version이 적혀 있다.
3. commit 뒤 응답이 유실되면, request id가 새로 바뀌어도 key가 같으면 durable record는 하나만 생긴다.
4. stdio의 `notifications/cancelled`와 HTTP stream 종료가 완료와 경합해도 반쯤 commit된 상태가 생기지 않는다.
5. host 3개에서 path 없는 일반 prompt를 처리할 때 phase·path 조건 rule은 빠지고 응답은 예산 안에 든다.
6. 첫 쓰기 시도는 deny와 rule ID·digest를 받고, watermark 확인 뒤 allow된다. allow와 context만 붙인 경우는 전달로 세지 않는다.
7. Claude의 compact·fork, Codex의 compact, omp의 compact·fork 뒤 watermark를 다시 평가하고 중복을 막는다.
8. omp module 변수에 상태를 저장하지 않는다. `ctx.agent`, Claude `agent_id`, Codex `agent_id` 기준으로 child 상태가 분리된다.
9. hook timeout이 나면 Claude는 fail-open하고 omp는 fail-closed한다. 어느 쪽이든 결과에 degraded로 표시한다.
10. company와 personal route를 adapter 설정으로 선택하고, `serverInfo`나 `clientInfo`로 정하지 않는다.

## G. 금지할 과대주장

- 모든 host가 MCP 2026을 지원한다, 또는 v2만으로 모든 host와 호환된다.
- hook 출력이 model 준수를 보장한다, 또는 allow와 context가 첫 쓰기 재계획을 보장한다.
- PreToolUse가 보안 경계다.
- session_id는 child나 fork마다 유일하다.
- 한번 주입한 context를 회수할 수 있다(Claude는 resume 때 replay).
- Claude SessionStart 시점에 mcp_tool hook을 쓸 수 있다.
- Codex hook이 hosted tool도 잡는다.
- omp가 Claude의 settings JSON hook을 실행한다(근거 없음).
- tool annotation이나 serverInfo를 신뢰할 수 있다.
- Codex 0.162.1에서 modern MCP가 실제로 동작함을 확인했다(source 조상 관계만 확인).

## H. 미확인

- 설치된 Claude, Codex, omp의 정확한 version과 실제 negotiate 결과
- Codex UPS context가 저장되는지, resume 때 replay되는지
- Codex PreToolUse context의 전달 시점과, exit 2가 아닌 실패의 처리
- Codex hook에 fork source가 있는지
- omp `before_agent_start` message의 저장 방식
- Claude `prompt_id`가 재시도 사이에 안정적인지
- `updatedInput`으로 lineage를 인자에 찍을 때 allow가 함께 적용되어 approval이 생략될 위험

---
## FROZEN SOURCE: research/local-first-engine-evidence.ko.md
# Hindsight 권위·fencing·철회·reflect + local-first 운영 + Python SDK 2.3 two-wire (2026-10-12)
표기: [근거]=고정 source나 공식 문서를 직접 읽음, [제안]=설계 계약(제품 구현 아님), [미확정]. 실행·설치는 0건.
약칭: HS/=https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-api-slim/hindsight_api/ (pyproject L7 기준 0.10.3). PY/=https://github.com/modelcontextprotocol/python-sdk/blob/2118f14f8a19bc158d8a1cf90af58d85d187f849/ (v2.3.0, 2026-10-02).
한계: memory_engine.py가 1,178,915 bytes라 reader가 L9924까지만 반환했습니다. reflect_async(L15545~)와 delta refresh(L17575~)는 기존 research 인용에 의존합니다.

## 1. Hindsight 내부 [근거]

### Queue / fencing
- 자체 async_operations 테이블에서 SKIP LOCKED로 claim하고 status=processing, worker_id, claimed_at을 기록합니다(HS/engine/db/ops_postgresql.py L1953-1968).
- lease 만료나 heartbeat가 없습니다. 복구 수단은 네 가지뿐입니다.
  - 같은 worker_id로 재시작(poller.py L1488-1540)
  - 종료 시 release(L1955)
  - admin decommission: processing 전부를 pending으로 되돌림(admin/cli.py L1444-)
  - API cancel
- source 주석도 공백을 인정합니다: "wedged processing holds its key/bank… general gap"(HS/engine/db/ops.py L116-118, L199-202).
- 종료 상태 쓰기는 fencing이 없습니다. _mark_completed가 `WHERE operation_id AND status='processing'`만 확인하고 worker나 세대는 보지 않습니다(poller.py L885-899).
- 엔진의 취소 확인은 task 시작 때 한 번뿐이고, 조회에 실패하면 계속 진행합니다(fail-open)(memory_engine.py execute_task L4505~).
- cancel은 cooperative입니다. 문서에 "in-flight may finish the batch"라고 되어 있습니다(api/http.py L8061-8077).
- document·mental model 키 단위, bank 단위 직렬화는 claim 조건(predicate)일 뿐입니다(ops.py L87-240, memory_engine L227-233).
- 프로세스 안 wall-timeout은 retain 3600s, consolidation idle 7200s, reflect 300s입니다(config L1881-1905).

### Retain
- MCP retain에는 idempotency key가 없습니다. 인자는 metadata(str→str), document_id, update_mode(replace 또는 append), tags입니다(mcp_tools.py L984-1012).
- 같은 document에 대한 여러 batch TXN은 row lock + content_hash 검사로 보호합니다(orchestrator.py L3056-3075).
- 같은 content를 다시 넣으면 no-op이거나 recovery로 처리되어 기존 unit을 보존합니다(L1721-1729, L2435).
- append는 base CAS만 있어서, 재전송하면 중복 append가 생길 수 있습니다[추론].
- 작업 완료 표시는 별도 TXN입니다(L5119). data commit과 원자적이지 않습니다.

### 읽기 범위 강제 (최종 출력 필터가 아님)
- resolve_tag_scope를 엔진이 recall, reflect와 그 tool, list, search, export에 AND로 주입합니다(operation_validator.py L884-926).
  - id로 단건 조회 시 범위 밖이면 404입니다.
  - mental model trigger는 scope_tag_groups를 기록해 refresh 때도 AND로 적용합니다.
  - whole-bank 작업은 403입니다.
- 예외 1: untagged directive는 범위와 무관하게 계속 적용됩니다.
- 예외 2: internal background 작업은 범위 제한을 받지 않습니다.
- 쓰기 범위는 별도입니다(L928-957). untagged 항목은 "모두의 것"으로 취급되어 범위가 제한된 caller의 쓰기는 거부됩니다.
- 기타 hook: validate_* (bank_write에는 directive CRUD, delete_document, update_bank_config 등 포함, L378-421), filter_mcp_tools(L1181). on_*_complete는 트랜잭션 밖에서 실행됩니다.
- consolidation은 tag 범위가 같은 batch만 LLM에 묶습니다(consolidator.py L1604-1688).
  - 단, retain에 `observation_scopes='shared'`를 주면 tag와 무관한 untagged observation이 만들어집니다(L483-496). 범위 확대 경로입니다.
- document tags PATCH는 모든 unit에 전파되고, 파생 observation을 무효화한 뒤 재consolidation을 큐에 넣습니다(http.py L7880-7900).

### Directive / reflect / 철회
- directive는 reflect system prompt 앞뒤에 들어가는 hard rule입니다(reflect/agent.py L630, L674). 승인, digest, host 규칙으로서의 권위는 없습니다.
- MCP reflect의 `apply_all_directives`는 caller가 켤 수 있습니다. `include_based_on`과 `include_trace`는 기본 false라 근거가 빠집니다(mcp_tools.py L1446-1527).
- 인용된 근거가 전부 사라지면 import로 id가 새로 생긴 경우와 구분할 수 없어서, 본문을 유지하는 false negative가 생깁니다(reflect/retractions.py L66-81).
- consolidation이 pending이면 철회 처리가 deferred_reason과 함께 미뤄집니다(engine/mental_model_refresh.py L196-226).
- fact id는 재retain이나 import 때 새 UUID가 됩니다. lineage 키로 쓸 수 없습니다.

### Invalidate / purge / backup
- invalidate는 row를 invalidated_memory_units로 옮기고(revert 가능), 누가 했는지(actor)는 기록하지 않습니다(alembic c9a1b2d3e4f5).
- document 삭제 후에도 observation_history snapshot이 orphan으로 남고, bank를 삭제해야 회수됩니다(alembic a1c9e7f3b2d8).
- llm_requests trace는 기본 on, 1일 보존, 50k chars입니다(config L1979-1982).
- audit_log는 기본 off입니다. 켜면 raw request/response JSONB를 무기한 보존하고, fire-and-forget이며 actor 컬럼이 없습니다(engine/audit.py L125-197, alembic c2d3e4f5g6h7).
- admin backup은 schema 전체를 REPEATABLE READ로 COPY합니다. async_operations, llm_requests, audit_log도 포함됩니다. restore는 전체 TRUNCATE CASCADE입니다(cli.py L49-90, L349, L421).
- extension 테이블은 extra_bank_tables로 backup과 delete_bank에 참여합니다. banks에 FK가 있으면 restore cascade로 함께 지워집니다(extensions/bank_tables.py, extensions/tenant.py).
- webhook outbox 이벤트는 retain.completed, consolidation.completed, memory_defense.triggered 세 가지뿐입니다(webhooks/models.py L8-11). 삭제, invalidate, refresh 이벤트는 없습니다.

### Identity / MCP
- RequestContext에는 api_key_id, tenant_id, allowed_bank_ids, internal, extra_headers(passthrough)가 있습니다(models.py L14-59).
- actor, source, generation 필드는 엔진에 없습니다. unit metadata(str→str)와 documents.retain_params.metadata만 있습니다.
- native MCP는 `fastmcp>=3.2.0`(상한 없음, pyproject L39)을 씁니다. `mcp_stateless` 기본값은 False이고, 세션 없는 GET에는 200을 반환합니다(api/mcp.py L383-430, L637-646).
- 2026 wire 지원은 [미확정]입니다. FastMCP 4.0.0이 새 프로토콜 대응 release라고 공지했습니다(https://gofastmcp.com/updates.md).

## 2. "싼 fork" 가정의 가장 강한 반례
fencing과 즉시 철회를 보장하려면 poller 한 곳이 아니라 모든 write 경로를 고쳐야 합니다.
- 대상 경로: retain의 여러 batch TXN, consolidation의 batch별 commit, refresh, import, delete.
- source가 직접 기술한 문제: orphan consolidation이 scope lock 불변식을 깹니다(consolidator L84-89).
- 현재 이 경로들은 claim 세대를 읽지 않습니다.
- decommission과 cancel은 살아 있는 stale worker를 멈추지 못합니다. 결과는 중복 LLM 비용과 상태 덮어쓰기입니다.
- restore는 같은 schema에 있는 invalidate, delete, 작업 상태까지 backup 시점으로 되돌립니다. 철회 자료가 부활하고 작업이 재실행됩니다.
- 패치 대상이 1.18MB 단일 모듈과 약 100개의 alembic version이라 충돌면이 큽니다.

역방향 반례도 있습니다. 단일 노드, 단일 worker, 같은 content 재retain 조건에서는 content_hash gate가 data 중복을 대부분 흡수합니다. 그래서 local 단계는 fork 없이도 운영할 수 있습니다.

## 3. 권장: bounded reuse [제안]

### 구성
- 엔진: Hindsight pin을 unforked로 사용합니다.
  - `MCP_ENABLED=false`, 고정 `WORKER_ID`, API 내장 worker 1개.
- 권위: amm schema(같은 cluster)에 둡니다.
  - capture_event(append-only): event_id, trust_domain, host/session/root-run/agent lineage, actor, source_uri, byte hash, generation
  - outbox: lease, fencing token, generation
  - receipt(operation_id)
  - state: candidate/approved/rejected, 3-scope, exact digest
  - tombstone
- amm이 Hindsight에 쓰는 유일한 writer입니다.

### Retain
- `document_id=amm:{event_id}:{rev}`로 고정하고 replace만 씁니다. append는 금지합니다.
- metadata에는 비권위 사본만 넣습니다.
- receipt를 잃으면 같은 document를 다시 제출합니다. 같은 content라면 Hindsight gate가 흡수합니다.
- 완료 확인: GET operations/{id} + loopback retain.completed webhook(at-least-once).
- lease를 잃거나 generation이 바뀌면 DELETE operations/{id} 후 결과를 재검증합니다.

### Eligibility
- `scope:*`·`state:*` tag를 resolve_tag_scope로 엔진 안에서 강제합니다.
- 승격이나 범위 변경은 amm 승인 후 document tags PATCH로 반영합니다.
- 그 operation이 완료되기 전까지 watermark로 해당 doc 읽기를 막습니다.
- 승인된 rule/skill 본문은 amm selector로 결정적으로 전달합니다. directive는 쓰지 않습니다.
  - agent principal의 directive CRUD는 validate_bank_write로 거부합니다.
- reflect 호출 시 `apply_all_directives=false`, `include_based_on=true`로 고정하고, 결과는 candidate로만 다룹니다.
- `observation_scopes` 확장은 쓰기 범위 검사로 거부합니다.

### 철회와 restore
- 처리 순서:
  1. tombstone head 기록
  2. invalidate/delete 실행
  3. retraction pending 동안 해당 observation과 mental model 읽기 차단
  4. 필요하면 observations clear 후 refresh
- restore 대응:
  - restore마다 generation을 올립니다.
  - tombstone은 backup에서 빼고 banks FK도 두지 않습니다. 그래야 TRUNCATE에 영향받지 않습니다[bank_tables 문서에서 추론].
  - tombstone을 다시 적용한 뒤에만 읽기를 엽니다.
- spool replay는 event_id로 중복을 제거합니다.

### 권한 / 정리
- DB role 분리: migration(`MIGRATION_DATABASE_URL`), app, amm, read-only reviewer.
- `ENABLE_BANK_CONFIG_API=false` 또는 get_allowed_config_fields가 빈 set을 반환하게 합니다.
- dry-run, OCR parser는 끕니다.
- TenantExtension으로 token→schema/allowed_bank_ids를 묶고, validator로 principal→읽기/쓰기 범위를 정합니다. bank-wide 작업은 operator만 합니다.
- purge 절차: document 삭제 + history orphan sweep + trace/audit 보존기간 정리 + backup 만료. tombstone에는 본문을 넣지 않습니다.

### Fork patch가 필요한 조건
- multi-worker fencing이 필요할 때
- invalidate 결과를 동기적으로 cascade해야 한다고 보장할 때
- 엔진 audit에 actor가 필요할 때

### 대안: narrow PG core로 교체하는 조건
- extension API가 pin 업그레이드 사이에 깨질 때
- shared observation, internal background, untagged directive 경로를 막을 수 없을 때
- 승인된 LLM의 한국어 추출 품질이 기준에 못 미칠 때
- 교체하더라도 capture→…→next task 전체 흐름을 같은 계약으로 대체해야 하며, 기능 축소는 허용하지 않습니다.

## 4. Local 운영

### PostgreSQL과 volume
- PG 14+와 pgvector가 필요합니다. migration이 vector와 pg_trgm extension을 만듭니다.
- named volume: PG data와 HF model cache(경로 [미확정]). file storage는 기본이 PG BYTEA라(config L1685) 별도 volume이 필요 없습니다. pg0는 dev 전용입니다.

### Update
- `RUN_MIGRATIONS_ON_STARTUP` 기본값은 True입니다(L1777). false로 바꿉니다.
- 순서: admin backup + pg_dump → run-db-migration → 기동.
- rollback은 이전 image + restore + tombstone 재적용입니다.
- worker 설정: API 내장(L1851), 기본 ID는 hostname이므로 고정값으로 지정, 최대 retry 3.

### Offline 모델
- 기본 embedding은 bge-small-en-v1.5, reranker는 ms-marco-MiniLM입니다(L1202-1266). 둘 다 영어 중심입니다.
- onnx용 multilingual-e5-small이 기본값으로 정의되어 있습니다.
- 모델을 바꾸면 전체 재임베딩이 필요합니다. 모델은 미리 반입하고 HF offline으로 설정합니다.

### 모델 경로
- 기본값: openai/gpt-4o-mini(L1082, L1117).
- RETAIN, REFLECT, CONSOLIDATION, MENTAL_MODEL_REFRESH, VLM마다 provider와 base_url을 따로 지정할 수 있습니다(L370-450). 지정하지 않으면 global로 fallback합니다.
- global과 모든 slot을 승인 endpoint로 명시합니다. 키가 없을 때 실패하는지(fail-closed)는 [미확정]입니다.
- 확인은 `POST …/health/llm`(http.py L6443)으로 합니다.
- Hindsight는 새로운 background LLM 소비자이므로 회사의 별도 승인이 필요합니다. 승인 전에는 blocked로 표시합니다.

### Egress 경로
LLM, VLM, OCR/iris/llama_parse, webhook, OTEL(기본 off), HF, litellm[미확정].

### 비용
- 매 retain마다 추출 LLM 호출이 생깁니다.
- auto-consolidation이 기본 on입니다. LLM 호출당 8 facts, cosine≥0.97이면 merge LLM 호출이 추가됩니다(L1703-1745).
- reflect는 최대 10 iteration, 100k context, 300s입니다. refresh는 곧 reflect입니다.
- tag 변경과 reprocess는 재파생 비용을 냅니다.

### 나중의 cloud VM (provisioning 없음)
- 1 VM: TLS proxy → amm adapter(HTTPS + TokenVerifier) → loopback Hindsight → local PG volume.
- 개인 creds, 모델, backup은 따로 둡니다. 회사 데이터 sync는 하지 않습니다.
- modern 요청은 세션이 없어 LB와 무관합니다. legacy client는 sticky routing이 필요합니다.

## 5. Python SDK 2.3 (two-wire) [근거]
- 지원 버전: handshake 2024-11-05, 2025-03-26, 2025-06-18, 2025-11-25 / modern 2026-07-28(PY/src/mcp-types/mcp_types/version.py).
- 같은 `MCPServer.streamable_http_app()`(stdio server도 동일)가 두 era를 동시에 서빙합니다.
  - 요청마다 `MCP-Protocol-Version` 헤더로 라우팅하고, 헤더가 없으면 legacy initialize로 처리합니다.
  - era를 끄는 옵션은 없습니다(https://py.sdk.modelcontextprotocol.io/run/legacy-clients/ , /whats-new/).
- modern 경로 `handle_modern_request`는 세션 ID를 발급하지 않습니다(PY/src/mcp/server/_streamable_http_modern.py L361-376).
- legacy session은 in-process dict입니다. `session_idle_timeout`(1800), `max_sessions`(10000)로 관리합니다.
- `stateless_http=True`는 legacy 쪽에만 적용되고 back-channel이 없어집니다.
- multi-replica MRTR에는 `RequestStateSecurity(keys=[...])`가 필요합니다.
- `Resolve(...)`는 era와 무관하게 쓸 수 있습니다. 알림은 `ctx.notify_*`와 `ctx.session.send_*`를 둘 다 호출해야 합니다.
- Client(https://py.sdk.modelcontextprotocol.io/protocol-versions/):
  - auto: `server/discover`를 먼저 시도하고 실패하면 initialize로 fallback
  - `mode="legacy"`: 2025-11-25
  - `mode="2026-07-28"`: pin, 이때 `server_info=None`. `prior_discover=`로 이전 결과를 넘길 수 있음
  - handshake 버전으로 pin하면 ValueError
- Auth: `MCPServer(token_verifier=…, auth=AuthSettings(issuer_url, resource_server_url, required_scopes, validate_token_resource))`, `get_access_token()`. stdio에는 auth가 없습니다(/run/authorization/index.md).
- 2.3.0 변경: 잘못된 x-mcp-header tool은 등록 단계에서 실패, legacy에는 빈 `_meta`를 보내지 않음, `MCPServer(subscriptions=False)` 추가(https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.3.0).

### Smoke 계획 [제안, 미실행]
준비: MCPServer 1개, Pydantic 반환 tool, 파일 DB, uvicorn loopback.
1. legacy로 쓰기: Mcp-Session-Id가 있고 버전이 2025-11-25인지 확인
2. auto로 읽기: 2026-07-28이고, Mcp-Method와 Mcp-Name 헤더가 있으며 세션이 없는지 확인
3. 방향을 바꿔 반복
4. 재시작 후 양쪽 모두 읽기 성공, 이전 legacy session은 404인지 확인
5. 구버전 initialize는 SDK로 pin할 수 없으므로 raw JSON-RPC로 확인
6. stateless 변형에서 NoBackChannelError가 나는지 확인
7. stdio로 두 era 모두 확인

이 smoke가 성공해도 native Claude/Codex 지원을 증명하지는 않습니다.

## 6. 미확정
- stdio 실행 API(`mcp.run("stdio")`로 추정)와 v2의 StdioServerParameters import 경로
- 구버전 initialize에 대한 counter-offer 값
- Hindsight native MCP의 2026 지원
- L9924 이후 reflect/refresh 코드
- invalidate가 파생 observation을 즉시 정리하는지
- tag scope 아래에서 `apply_all_directives`의 동작
- extension API의 버전 간 안정성
- bank config로 바꿀 수 있는 LLM 필드 범위
- litellm egress
- 실제 host들이 쓰는 wire 버전

---
## FROZEN SOURCE: research/local-first-python-mcp-feasibility.ko.md
# Python MCP 2.x: 같은 localhost endpoint의 modern·legacy 호출 확인

## 결정과 범위

**Python 3.12 + 공식 `mcp==2.3.0`을 서비스 언어·MCP SDK 후보로 채택할 수 있다.** Python으로 MCP `2026-07-28`을 구현하는 데 TypeScript 서버가 선행 조건은 아니다. 호스트 플러그인은 해당 호스트의 언어를 써도 서비스 API와 의미 계약은 하나다. SDK major version과 wire version은 별도 표기한다.

이는 제품 구현 완료 판정이 아니다. 현재 저장소에는 조사·설계 문서만 있다. Python SDK/HTTP 연결의 실측과 Hindsight/PG/실제 Claude·Codex·omp의 제품 연결 증거를 구분한다.

## 공식 근거

- [Python SDK protocol versions](https://py.sdk.modelcontextprotocol.io/protocol-versions/): `Client(..., mode="auto")`는 `server/discover`를 사용하고 구형 서버에서는 initialize로 fallback한다. `mode="legacy"`는 같은 서버와 handshake-era 연결한다. `mode="2026-07-28"`은 버전을 pin하므로 discovery 없이 시작하고 서버 신원·capability가 자동 확인되는 것은 아니다.
- [Python SDK ASGI app](https://py.sdk.modelcontextprotocol.io/run/asgi/): `MCPServer.streamable_http_app()`은 Starlette/ASGI app을 반환한다. 단독 앱은 lifespan을 관리한다. 다른 앱에 mount할 때 top-level lifespan에서 `mcp.session_manager.run()`을 관리해야 한다. localhost Host/Origin 보호는 endpoint 인증을 대체하지 않는다.
- [SDK legacy-clients](https://py.sdk.modelcontextprotocol.io/run/legacy-clients/): 하나의 앱으로 두 protocol era를 제공한다. `stateless_http` 옵션은 legacy 동작의 설정이고 modern 요청의 무상태성은 별도이다.
- [공식 Python SDK v2.3.0 고정 소스](https://github.com/modelcontextprotocol/python-sdk/tree/2118f14f8a19bc158d8a1cf90af58d85d187f849): 조사 시점의 버전·전송 소스 근거. 라이브 문서가 앞으로 변할 수 있으므로 설치 lock과 host matrix를 함께 관리한다.

## 이번 실제 실행

관측 파일: [`local-first-python-wire-observation.json`](local-first-python-wire-observation.json).

- 실제 Python **3.12.13**, 공식 MCP SDK **2.3.0**.
- `MCPServer` 하나, `streamable_http_app(json_response=True)` 하나, uvicorn의 `127.0.0.1` 임시 port 하나.
- 반환 모델은 Pydantic `Note`. 일반 문자열만 반환하는 fake 응답이 아니라 실제 저장 후 읽은 structured content를 비교했다.
- 임시 SQLite에 `public-synthetic-dual-era-note`라는 공개 합성 문자열을 저장했다. DB 선택 실험은 아니며 최종 PostgreSQL의 증거도 아니다.

| 실행 순서 | SDK client mode | 관측 wire version | 결과 |
|---|---|---|---|
| 1 | `2026-07-28` | `2026-07-28` | 합성 note 실제 저장 |
| 2 | `legacy` | `2025-11-25` | 동일 note 본문·ID 정확히 조회 |
| 3 | `auto` | `2026-07-28` | 동일 note 본문·ID 정확히 조회 |
| 4 | 별도 `2026-07-28` client | `2026-07-28` | 동일 note 본문·ID 정확히 조회 |

13개의 실제 HTTP 요청을 관측했다. Modern 요청에는 `Mcp-Method`, 해당 tool의 `Mcp-Name`, protocol header와 namespaced `_meta`가 있었다. Modern 구간의 요청·응답에는 `Mcp-Session-Id`가 없었다. Legacy 구간은 `initialize`·`notifications/initialized`와 session header를 사용했다. Auto 구간은 실제 `server/discover`를 보냈다. 저장·조회 요청은 HTTP 200, legacy initialized notification은 HTTP 202였다. 프로세스 exit **0**, 관측된 wall time **0.91초**. 이 시간은 합성 probe 총 실행 시간이며 제품 latency 예측값이 아니다.

원문 실행 로그의 합성 transport session ID는 관측 JSON에 넣지 않았다. 관측은 header 유무만 보존한다. 회사 코드·사용자 파일·실제 모델 인증 정보를 사용하지 않았다. 임시 script/DB/server는 종료·제거했다.

## 설계 반영

1. 하나의 공식 Python SDK edge에서 modern과 legacy를 처리하고 **같은 domain handler**를 호출한다. 별도 구형 엔진·의미 shim을 만들지 않는다.
2. 제품의 operation/episode/source revision은 MCP transport session ID나 JSON-RPC request ID에 의존하지 않는다.
3. Modern 연결을 쓴다고 tool catalog·description·rule body의 모델 토큰 비용이 사라지지 않는다. 연결 시 corpus/rule body 0, 작은 고정 catalog, 실제 작업에 필요한 bounded context를 별도로 설계한다.
4. pinned mode의 무왕복은 endpoint 인증이나 capability 검증을 생략해도 된다는 뜻이 아니다. 인증된 endpoint identity/host compatibility와 cache invalidation은 별도다.
5. 실제 native 호스트의 HTTP/stdio, hook, compaction·fork·subagent, timeout/retry 동작은 **각각 제품 acceptance scenario에서 검증**한다. Python client가 legacy mode로 통과했다는 사실만으로 omp/Claude/Codex 연결 완료라고 쓰지 않는다.
6. 첫 로컬 제품은 위에서 실행한 Python 3.12 계열을 대상으로 lock한다. OS 기본 Python 3.9에 맞추기 위한 SDK downgrade는 하지 않는다. 실제 지원 Python 최소 버전·dependency 충돌은 packaging milestone에서 pinned metadata로 확정한다.
7. 이후 cloud에서도 같은 ASGI app과 core를 쓰되 개인 deployment의 TLS/IdP/backup을 추가한다. Modern stateless 요청과 legacy in-process session의 scale-out 조건은 다르므로 무조건 다중 replica 호환이라고 주장하지 않는다.

## 아직 이 실행으로 증명하지 않은 것

제품 memory pipeline, PostgreSQL·pgvector, Hindsight, 인증·회사 외부 통신 차단, stale worker fencing, 승인·철회·restore, native host auto invocation, 실제 prompt token 절감, 다국어 memory 품질, cloud 배포. 이 항목들은 설계의 구현·수용 기준에 남긴다.
