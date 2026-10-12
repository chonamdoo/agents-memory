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
