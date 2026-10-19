# 회사 no-local-ML 기억 선별: 최종 권고·반대 근거·적용 경계

## 결정

**회사 기본안은 A: 현재 승인된 coding caller의 원문 연결 후보 제출 + 명시 lexical/entity 검색 capability다.** B: 허가된 native 소형 모델의 신규-window 배치 선별기는 동일 계약의 opt-in executor로 둔다. 개인 Jev API는 별도 개인 realm/deployment에만 연결한다. TypeSafe는 범용 Choice/Score/Noul 소비자가 실제 필요한 경우의 optional compatibility boundary이며 memory core 필수 의존성이 아니다. Profile·Log·Notes·파일/스킬은 각 deployment/realm의 하나의 canonical ledger를 가리키는 겹치는 관리 view로 제안한다. 회사/개인 데이터를 하나의 전역 ledger에 합치지 않는다.

**아직 채택 승인이 필요한 차이:** A는 기존 full semantic/mandatory hybrid/rerank와 동등하지 않다. classifier 하나로 learned embedding·cross-encoder·자동 consolidation/reflection이 생기지 않는다. 이 기능을 빠뜨리고 full pipeline 완료라고 선언하지 않는다. lexical capability를 명시 별도 기능으로 채택할지, 기존 full semantic 품질을 유지하며 승인된 embedding/rerank 실행 경로를 먼저 확보할지는 사용자 결정이다. 현재 승인 모델/구독 계정만으로 후자의 경로가 확보됐다는 증거는 없다.

## 가장 큰 구현 발견

현재 `memory_record(note)`는 agent_note source와 extract job을 만든다. `Worker._process`는 extraction과 embedding route를 모두 확보하고 claim마다 vector를 생성한다. `publish_extraction`은 vector+lexical row를 요구하며 consolidate를 enqueue한다. `Application.context`는 active claim이 있으면 query embedding과 rerank를 필수 실행한다. 따라서 **note receipt=committed나 custom Haiku provider 성공을 회사 기억의 저장→검색 완료로 바꾸면 거짓 완료다.** 회사용 A/B는 현재 미구현이다.

기존 검색의 lexical arm은 PG `text[]` GIN token overlap과 entity exact matching이다. `tsvector` FTS가 아니다. 검색용 Hangul bigram/정규화는 source quote가 아니며 learned embedding 대용도 아니다.

## 두 모델의 실제 반대검토와 부모 결정

별도 4분류 리뷰를 마친 뒤, OSS pinned source·사용자 추가 TypeSafe 자료·개인 SDK/native smoke·concrete core scope·기존 승인 경계를 모두 같은 새 packet으로 전달했다. 통합 stdin 17,840 bytes, SHA256 **652608762ebe333532a83ed81fd555c5a697c1c382bf9f6019337470d6668dba**가 두 native 실행에 일치한다.

- Opus는 A를 최소 coherent 선택, B를 차선으로 권고했다. CLI2.1.296의 modelUsage에서 claude-opus-5-5를 관측했다. xhigh는 요청값이며 서버 독립 attestation이 아니다. 첫 보고서 길이 초과로 같은 packet을 다시 실행한 사실과 두 실행 usage를 모두 보존했다. 내용/승인을 골라낸 재시도가 아니다. final JSON만 관측했으므로 절대 tools=0은 증명하지 않는다.
- Codex는 A 전체 계약+B를 최소 coherent 선택, A를 차선으로 권고했다. CLI0.162.1, gpt-6.1-sol/xhigh 요청; served model/effort 미관측. JSONL 관측 tool calls 0이지만 전체 read/network isolation 증거는 아니다. 원문이 요청한 7,000자를 넘었어도 편집하지 않고 그대로 보존했다.
- **차이는 B를 기본 구성으로 넣을지다.** 회사 자동화 허가/운영 isolation/비용 순이익이 미확인이고 A도 새 제품 계약이므로, A 기본+B 허가 시 opt-in을 선택한다. native Haiku가 더 싸다는 가능성과 현재 coding caller에 판단을 묶으면 추가 호출을 피할 수 있다는 가능성은 모두 미측정이다.
- 공통 반대: C core 강제/whole plugin 교체/4 independent stores/전역 alwaysProfile/무조건 영구 raw 보존 기각. 전체 optional fact에 인간 서명을 새로 붙이지 않는다. required/shared instructions·권한 확대·실제 철회의 기존 approval 계약은 유지한다.

이번은 architecture review다. frozen AF implementation approval·QA/handoff·실제 회사 운영 허가가 아니다.

## 같은 잣대의 대안 비교

| 선택 | 장점 | 단점·완료 범위 차이 | 결정 |
|---|---|---|---|
| A: 현재 caller의 source-grounded 판단+lexical/entity | 이미 읽은 source 재분석 중복을 줄일 수 있음; 새 local ML·별도 계정 필요 없음; common authority 유지 | caller 출력/tool 비용 존재. 미제출 window coverage 필요. paraphrase·conflict recall 저하 가능. 자동 semantic 기능 미지원 공개 필요 | 명시 capability 예외 채택 시 회사 기본 |
| B: A+native small-model bounded batch | 모든 제공 event의 3분류 완전성 검사·배치/usage 측정 가능; 별도 낮은 모델 선택 | company native/headless/daemon 권한, quota·고정 context·cache·deadline·kill/reap·managed isolation 필요. vector 대체 아님 | 별도 허가/검증 후 opt-in |
| C: B+공식 System One Adapter 전체 응답 | custom provider·strict questions/Choice/Score/Noul 재사용. 실제 native 연결 성공 | 원문 span/coverage/memory authority 없음. default non-unit 분포 허용, debug raw 보존, cached usage 보완 필요. 추가 SDK 유지비 | 실제 범용 typed consumer가 있을 때 edge 호환만 |
| D: official Claude mods complete | supplied prompt/system 단일 호출, session history 자동 미첨부; cold CLI 비용 회피 가능 | Claude 전용, mods 설치/승인과 build API pin 필요. 외부 MCP의 일반 API가 아님. 우리 evidence/cancel/fence 별도 | 허가된 Claude host 전용 최적화 후보 |
| E: effortless/Jevbridge/타 memory engine 통째 교체 | 기존 기능/패턴 활용 가능 | routing plugin≠memory classifier; API-key judge≠subscription. coercion·direct mutation·span/approval/retention 계약 손실 | 기각 |
| 개인 Jev API | 개인 허용 경로에서 specialized cheap judge 선택 가능 | 회사 데이터/credential 이동·fallback 금지. 비용/calibration은 개인 workload 측정 필요 | 개인 realm explicit route만 |

형식/의미·근거·상태/승인·realm/egress·증분/누락·비용/usage·검색/시간/TTL·lifecycle/fence·영향/유지보수·proof라는 10기준의 개별 판정은 두 native 원문 표에 보존했다. 위 표는 부모의 적용 결정이다.

## 3분류와 저장 작업을 섞지 않는다

- `candidate / exclude / review`는 usefulness 판단이다. `no-op / create / patch / conflict-hold`는 기억 변경 제안이다. `unclassified / blocked / failed / unavailable`는 coverage/실행 상태다.
- 모든 input event/window를 accounted로 검사한다. verdict 누락/빈 응답/timeout는 exclude가 아니며 완료 cursor를 전진시키지 않는다. 판단에서 중요한 부정·조건·예외가 잘리면 whole-unit omission 또는 review와 재조회 pointer다.
- source IDs/revisions·UTF8 offset·speaker·원문 quote를 서버가 검증한다. span 존재는 entailment/사실 정확성 보장이 아니다. agent_note 요약을 human 원문으로 승격하지 않는다.
- no-op도 감사/판단 receipt를 남길 수 있다. 이것을 유용성 제외와 혼동하지 않는다. exclude는 raw purge·기존 claim 삭제/철회가 아니다. negative judgment도 exact source revisions+policy contract와 retention에 묶으면 재판단 중복을 줄이는 근거로 사용할 수 있다. Opus의 negative cache 전면 기각은 채택하지 않는다.
- patch는 exact target/revision과 교정 근거, conflict-hold는 publication 전 별도 처리다. 자동 consolidation 미지원인 A/B에서 완전한 모순 탐지를 선언하지 않는다.
- caller가 이미 가진 전체 coding context를 서버가 독립 attestation했다고 하지 않는다. 제출/제공된 source window와 reported coverage를 구별하고 provenance 수준을 표시한다. native B는 서버가 구성한 실제 bounded source/claim 입력 전부를 admission manifest에 묶는다. 필요한 입력 lineage를 증명 못하면 더 강한 derived-authority 보장을 주장하지 않는다.

## 4분류 적용

- **Profile:** 필요할 때 scope/subject 기준 조회. 신규 자동 always pin 없음. 실제 필요가 있는 explicit bounded pin만 별도 계약. 기존 approved mandatory rules는 그대로 전달한다.
- **Log:** 원문 사건/교정 pointer와 관측 시각. 메시지 event_time·recorded_at과 본문 occurrence/validity를 구분하고 authorized retention을 지킨다.
- **Notes:** task/binding·종료 사건·freshness. TTL 비노출은 purge와 다르며 재개 시 current authority/revision을 확인한다.
- **파일:** source reference/hash/revision 기반 bounded read/search; 검색 hit는 수정/export 권한이 아니다.
- **스킬/규칙:** candidate data와 실행 instruction 분리; exact revision/selector/target set에 기존 approval와 withdrawal을 적용한다.

view 때문에 별도 taxonomy model을 매 event 호출하지 않는다. 기존 metadata 기반 readonly view부터 제안하고 검색 개선/운영 가시성의 순이익을 측정한다. view·category 자체는 grant·상시 주입·새 store를 만들지 않는다.

## 실제 적용의 coherent 변경 단위

| 계층 | 파일/변경 | 반드시 유지할 경계 |
|---|---|---|
| domain/policy | domain/config/semantic_contract/semantic; typed source-selection, coverage, candidate readiness, explicit retrieval capability | strict union/idempotency. label·claim-ready·execution failure 분리. 새 입력 shaping/validator/prompt fingerprint를 authority epoch에 결합 |
| authority/worker | store/jobs/application; unclassified capture, grounded candidate publish, lexical/entity recall, model-free final manifest | source/grant/revision/policy/deletion-floor publication+delivery fence. `delivery(admissions=())` 또는 fake model descriptor 우회 금지. current local vector path strict 유지 |
| durable lifecycle | 새 forward migration, journal/ops/restore/statistics/readiness | raw body 복제 금지, source lineage·purge/withdrawal closure, old backup resurrection 차단. no-vector 후보를 stale-index 실패로 오분류 금지 |
| MCP/CLI/hosts | edge/wire/CLI/client/stdio/hosts/templates/spool | 같은 application handler. 현재 4tools 유지안. producer ingest≠agent read 권한. pointer/covered window·receipt/strict host state 호환 |
| opt-in native | 별도 narrow selection executor, approved route descriptor, hard deadline/kill/reap/drain/byte budgets | auth file 미열람/미복사; 외부 API fallback 없음. cached/retry/unknown usage 분리, debug transcript 정상 persistence 금지. text classifier를 embedding-capable runtime으로 위장 금지 |
| verification/docs | 관련 authority/semantic/context/edge/CLI/host/spool/ops 회귀; README/requirements/architecture/plan/verification/checkpoint | actual capture→judge→candidate→recall/inspect→correction/retract→다음 consumer의 전체 경로. SDK 연결 성공/단위 테스트만으로 완료 선언 금지 |

작은 CLI wrapper만 추가하는 작업으로 축소하지 않는다. AF는 consumer이지 memory runtime 의존성으로 import하지 않는다. AF의 credential-copy/danger-full-access argv를 차용하지 않는다.

## 실제 검증과 아직 필요한 검증

**이번에 실행:** 공식 SDK exact pin+native Haiku의 개인 합성 Choice3/Noul1/Score1 성공 약5초. Pydantic/허용 labels/분포 sum1 확인. native cached input과 SDK 집계 차이, debug prompt 보존 실제 관측. 별도 4분류 및 통합 두 native 리뷰, GitHub 게시 후 본문 exact readback 수행. 임시 provider 제거. 회사 source·auth 파일을 열거나 복사하지 않았다.

**회사 feature 구현 뒤 필요, 현재 미실행:** local ML 없는 actual service full capability path, missing/duplicate/foreign verdict, multibyte offsets·반복 quote·조건/예외, source/credential/route revoke in-flight, cancel/overflow/quota, canary body-free persistence, known-conflict delivery, restore-old-backup와 capture gap, 같은 corpus의 paraphrase/conflict recall·false-negative·review 비용·다음 task 소비. native model의 0.9나 adapter confidence1을 정확도/승인으로 쓰지 않는다.

**현재 AF:** official status는 run20261012-113028 review/awaiting_host, required aggregate review.md가 아직 없다. fresh12 native outcomes는 approve7/request-changes5. Generalist가 새 route의 temporal reflection 실제 실패와 완료 증거 부족을 지적했다. 이는 새 회사 연구와 별개의 기존 결함이며 QA/handoff/완료가 아니다. frozen source에 A/B를 끼워 넣지 않는다. 권고 작업 순서는 기존 run의 결함→fresh review/QA/승인 base→새 회사 scope/plan 승인→coherent A→허가된 B다.

## 구현 전 필요한 명시 결정

1. **회사 기능 계약:** lexical/entity·caller-grounded capability를 full semantic과 별개로 채택할지, 아니면 기존 full semantic 품질 계약을 유지하고 approved embedding/rerank 경로를 먼저 확보할지.
2. **AF 대상/순서:** 현재 별도 작업의 active run이 있다. 권고는 기존 run의 request-changes를 먼저 해소한 후 새 회사 scope를 별도 공식 run으로 진행하는 것이다. 회사 구조 변경을 우선하려면 기존 run 보존/보류와 신규 대상 선택을 명시해야 한다.

회사 headless/unattended·모델 entitlement·customer egress/retention·저장소/daemon 허가는 repo/개인 probe에서 확인 불가다. 기술 구현과 실제 회사 enable을 분리하고 B는 그 증거 없이 enable하지 않는다. 위 두 결정 전에 existing source/spec를 몰래 바꾸거나 연구만으로 구현 완료 처리하지 않는다.
