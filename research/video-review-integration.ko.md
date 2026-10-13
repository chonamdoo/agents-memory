### 12. 새 영상 원문 재분석 — 이전과 동일 잣대

대상: [Why AI Coding Agents Need a Memory Pipeline — Boundary](https://www.youtube.com/watch?v=mAKUL12h1n8), [사용자 지정 08:20](https://www.youtube.com/watch?v=mAKUL12h1n8&t=500s). 조사일 2026-10-11. **특정 기존 앱의 코드그래프 재사용·최소 DB 구성으로 연결한 해석은 제외한다.** 영상 자체의 trace-derived code map은 별개의 설계 논점이다.

#### 12.1 원문 확보·기존 자료 포함 범위

- 로그인/cookie 없이 yt-dlp로 YouTube **자동 영어 en-orig JSON3를 새로 다운로드**했다. metadata는 Boundary, upload `20261009`, duration 3,214초다. 공식 episode 폴더의 `2026-10-06`을 업로드 날짜로 쓰지 않는다.
- raw JSON3 **1,102,804 bytes**, SHA256 `a12be7a5b4cd8916e14ab0d027515e2f51ee915a5370b19f45c75edc8553b734`. text cue 1,511개, 첫 시점 00:00:00.160, 마지막 00:53:33.599. 새 timed transcript 1–1515행 **전체를 읽었다**.
- 새 자막과 제공된 cached raw JSON3의 정규화된 전체 text가 일치했다. 제공 plain transcript도 metadata 6행을 제외한 본문이 일치했다. **원문이 다른 것이 아니라 특정 프로젝트에 대입한 분석이 잘못된 것이다.** 기존 한국어 분석을 사실로 전제하지 않고 원문/공식 자료에서 다시 판단했다.
- cached MP4에 실제 ffprobe 실행: 3,213.914초, 286,685,607 bytes, AV1 1920×1080/24fps·Opus. **500초와2,325초 프레임을 새로 decode하여 직접 확인**했다. 08:20에는 코드영역별 `Where to look`/`Rules`/`Language facts`와 session/people 집계, 38:45에는 Jev·`GPT-6 Sol`·`Opus 5.5` stage 및 BAML Query가 보인다. 화면 model label은 provider-resolved model 증명과 다르다.
- header는 **1,040 sessions / 30,963 messages / 9 people / 2026-02-18–2026-06-18**. 화자의 '한 주' 및 세션당 2 cents와 동일 분모로 단정하지 않는다.
- **이전 §9 native 리뷰에 제공된 9개 Downloads 자료가 모두 들어갔다고 주장하지 않는다.** 이번 새 리뷰에는 새로 받은 전체 자막, 기존 verified-claims의9개 원문 locator 교차 확인, 재분석 및 공식 문서/고정 코드 검증을 포함한8개 파일을 동일 입력으로 전달했다. 9개 한국어 자료 전문을 전부 다시 전달한 것은 아니다. locator의 자막 일치는 발언 존재 확인이지 발언의 사실성/제품 성능 검증이 아니다.
- 새 video 파일 다운로드·전 프레임 재생/수동 재전사·시연 pipeline/Jev API/메모리 제품의 품질·복구 실행은 하지 않았다. **아래 §13의 실제 두 native 모델 리뷰 실행은 별도이며 성공했다.**

#### 12.2 실제 시연·자기보고·후속 아이디어 구분

| 원문 | 확인한 내용·상태 | 같은 잣대의 판정 |
|---|---|---|
| [04:49–06:38](https://www.youtube.com/watch?v=mAKUL12h1n8&t=289s) | user/assistant만 남기고 tool call을 뺀 Haiku POC가 좋지 않았다는 자기평가. session/message/user ID와 enable 설명 | **초기 POC**의 citation schema다. 최종 grouping 결과에 message+offset+actor까지 보존된 것이 증명됐다고 확대하지 않는다. 실패 사례도 모든 cheap model의 보편 성능 판정은 아님 |
| [07:54–10:28](https://www.youtube.com/watch?v=mAKUL12h1n8&t=474s) | 코드영역별 Markdown 및 Where/Rules/Facts, 복수 세션/people 수를 보여주는 시연 | scope에 맞는 context shard는 유용한 방향. people 수는 session 소유자 수이지 인간 여러 명의 명시적 지지나 승인 아님. 최종 source granularity·host 주입·다음 행동 개선은 별도 검증 |
| [10:30–11:48](https://www.youtube.com/watch?v=mAKUL12h1n8&t=630s) | 보고서와 repo를 외부 agent에게 추가로 주자 기존 architecture.md 참조 누락을 발견한 사례 | **ad-hoc 후속 분석**이다. pipeline에 자동 pointer discovery가 이미 구현됐다고 하지 않는다. 새 memory 대신 기존 문서 pointer가 적합한 경우를 설계 후보로 채택 |
| [12:45–13:10](https://www.youtube.com/watch?v=mAKUL12h1n8&t=765s), [16:14–16:24](https://www.youtube.com/watch?v=mAKUL12h1n8&t=974s) | $2→2 cents/session 정정, 강한 agent 개발 탐색 약$100, 최종 보고서50 cents라는 자기 사례 | 분모·cache·재실행·model·storage·검토 시간을 분리해 측정해야 함. 제품 단가/SLA/TCO로 일반화하지 않음 |
| [15:46–19:45](https://www.youtube.com/watch?v=mAKUL12h1n8&t=946s) | 강한 agent로 유용한 결과를 탐색한 뒤 stage와 float 판단·input-hash JSON cache를 만드는 개발 방법 | typed/probability가 truth/권한은 아님. replay는 개발 최적화; prompt/parser/model/policy/source revision과 삭제/권한 상태까지 포함하지 않은 hash는 재현/철회 보장이 아님 |
| [20:05](https://www.youtube.com/watch?v=mAKUL12h1n8&t=1205s), [26:01–28:18](https://www.youtube.com/watch?v=mAKUL12h1n8&t=1561s) | **facts / human corrections / recurring investigations** 세 갈래 추출·grouping 설명과 시연 | 세 입력 신호와 최종 Where/Rules/Language facts 섹션은 **다른 축**. 1:1 대응으로 추정하지 않음. 문장별 source kind·조건·부정·customer/project·branch/revision을 보존해야 함 |
| [20:30–21:19](https://www.youtube.com/watch?v=mAKUL12h1n8&t=1230s), [23:04–23:13](https://www.youtube.com/watch?v=mAKUL12h1n8&t=1384s) | 긴 메시지 필터로 중요한 요청을 버린 bug, input inspection 설명 | middle prune와top/bottom truncate 자동 자막 표현이 어긋남. exact 절단 구현은 확정하지 않음. blanket 필터 대신 원문 offset·누락 표시·회수 경로를 요구 |
| [21:47–22:02](https://www.youtube.com/watch?v=mAKUL12h1n8&t=1307s) | 'do phase six'는 correction이 아니라 continue request라는 예시 | 실행 허가·수집 동의·정정·candidate 승인·standing rule 승격을 분리 |
| [22:16–22:58](https://www.youtube.com/watch?v=mAKUL12h1n8&t=1336s) | 모델이 쓴 내용은 이미 weights에 있다는 일반적 발언 | **일반 명제는 기각.** 새 repo/tool 자료에서 모델이 추출한 task-specific 사실과 pretrained generic 조언은 다름. 새 facts의 지지 근거는 source에서 검증 |
| [24:02–24:30](https://www.youtube.com/watch?v=mAKUL12h1n8&t=1442s) | strong-agent 비교 run에서 text60%·유용한 정보100%라는 자기보고 | 모델 agreement/golden run이지 human ground truth/independent action outcome은 아님 |
| [29:31–31:45](https://www.youtube.com/watch?v=mAKUL12h1n8&t=1771s) | facts prompt의 generic advice/개인 선호/실행 안 된 plan 제외 및 grouped pre-screen+strong judgement | coding-team artifact의 목적 제한이다. **개인 memory의 허용된 preference까지 일괄 제거하지 않음**. quoted/negated/conditional·no-match·한국어 fixture 필요 |
| [34:58–37:27](https://www.youtube.com/watch?v=mAKUL12h1n8&t=2098s) | parent→subagent 질문, file path·실제 읽은 file contents·답변으로 report/code map 생성 | trace-derived 탐색 근거이며 graph DB/기존 앱 codegraph 재사용 요구가 아님. Jev의 '질문에 답함'은 responsiveness이지 correctness. parent/child 중복·snapshot·민감 file 반출은 새 책임 |
| [38:08–43:48](https://www.youtube.com/watch?v=mAKUL12h1n8&t=2288s) | BAML spans/Query와 custom web UI 시연 | **프로그램 관측≠임의 coding host 전체 capture**. Query index≠canonical memory·approval·forget DB. agent DB key 제안은 broad raw-read 권한으로 재사용하지 않음 |
| [44:06–45:25](https://www.youtube.com/watch?v=mAKUL12h1n8&t=2646s) | 과도한 memory/skills와 새 model을 방해하는 규칙, memory health 논의 | 문제 제기/미해결 논점. 자동 health 운영 완성 아님 |
| [45:29–48:22](https://www.youtube.com/watch?v=mAKUL12h1n8&t=2729s) | 다른 memory 방식의 single-session 한계, cross-session correlation·labels/folders·cron consolidation 토론 | 화자의 비교 의견/설계 아이디어. 타사 제품 전반에 대한 검증 완료 판정은 아님. 개인/팀 corpus의 크기 차이는 signal profile로 다룸 |
| [48:23–50:12](https://www.youtube.com/watch?v=mAKUL12h1n8&t=2903s) | memory-off backtest의 replay 한계, code 영역과 memory를 연결해 stale인지 agent에게 묻는 **아이디어** | 같은 task/repo state의 독립 후속 행동 평가. 과거 assistant trace를 답안으로 재생하지 않음. agent stale 주장은 review trigger이지 확정 삭제 권위 아님 |
| [50:46–53:09](https://www.youtube.com/watch?v=mAKUL12h1n8&t=3046s) | 승인한 기억/기존 문서·거절한 기억과 이유를 네 번째 입력에 넣는 incremental/feedback 제안 | **후속 설계**다. 영속 ID/revision·거절 중복 억제·독립 재평가 필요. prompt/context 개선을 online weight 학습이나 자동 품질 향상으로 부르지 않음 |

#### 12.3 도구·공개 코드 교차 확인 — 엔진 추천과 구분

- **영상 전체 공개 코드:** [공식 episode snapshot](https://github.com/ai-that-works/ai-that-works/tree/738a9c18b0302737d5d354d9988f34482966cce6/2026-10-06-building-a-memory-pipeline) 및 [truncated:false subtree](https://api.github.com/repos/ai-that-works/ai-that-works/git/trees/0764336bebce12bcfca3fef6aee1dfbe95cabdfa?recursive=1)에는 `meta.md`와 thumbnail만 있다. 이 링크로 전체 pipeline을 clone/install할 수 있다고 하지 않으며, 인터넷 전체에 구현이 없다는 주장도 아님.
- **BAML:** [현재 소개](https://boundaryml.com/explore.md)와 [고정 canary99edb5d](https://github.com/BoundaryML/baml/tree/99edb5d249850ed92db987148feb78f551a93250)를 확인했다. pre-1.0 nightly와legacy v0 예제를 혼합하지 않음. [Query 구현](https://github.com/BoundaryML/baml/blob/99edb5d249850ed92db987148feb78f551a93250/baml_language/crates/baml_query_btel/src/lib.rs)의 Btel+content-addressable CAS가 원자료이고 `query.sqlite`는 disposable index다. CAS는 concurrency compare-and-swap가 아님. `--local`은 전체 inference/telemetry no-egress 보장이 아니다. 기록의 flush/rename을 canonical transaction/fsync 내구성으로 취급하지 않음.
- **Jev:** [모델 문서](https://docs.typesafe.ai/models.md)는 `jev-1.13.0`, text-only, input $0.042/Mtok. [confidence](https://docs.typesafe.ai/confidence.md)는 분포 집중도이며 정답 보증이 아님. [BAML adapter](https://github.com/BoundaryML/baml/blob/99edb5d249850ed92db987148feb78f551a93250/baml_language/crates/baml_builtins2/baml_std/typesafeai/ns_internal/jev.baml)의 choice/noul·bool p≥0.5 표면은 전체 probability/confidence 및 API resolved-model metadata와 다르다. [no-training와enterprise ZDR](https://docs.typesafe.ai/legal.md)은 구분해야 한다. 저가 hosted gate는 strict no-egress 회사판의 기본 의존성이 될 수 없음.
- **다른 file-memory 예제:** [pin한 memory.baml](https://github.com/BoundaryML/baml-demos/blob/dcc3d33f0fd2635d18515a62a10da91ae789f080/aie/baml_src/ns_memory/memory.baml)은 영상 전체 구현이 아니며 버전도 다르다. ASCII tokenizer/slugifier의 한국어 lexical recall·non-ASCII 이름 충돌 정적 반례를 확인했다. 실제 recall/overwrite runtime test를 실행한 것은 아니다. 공개 열람 가능성은 재배포 license 증명과 다름.
- **Host adapter:** [Claude hooks](https://code.claude.com/docs/en/hooks)와 [Codex hooks](https://learn.chatgpt.com/docs/hooks)를 재사용할 수 있다. 단, Claude launch 시 SessionStart MCP hook의 skip 경로, SessionStart의 command/mcp_tool-only, interrupt/async transcript와 Codex fail-open readiness·nullable transcript·hosted WebSearch coverage·관리형 cloud hooks 제약을 선언해야 한다. **SessionStart command에서 HTTP 요청하는 것과 type:http handler 지원은 다르다.** 최신 live 문서는 설치된 모든 binary의 지원 증명이 아니다.
- **기존 engine의 구체 반례:** [Hindsight pinned retractions helper](https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-api-slim/hindsight_api/engine/reflect/retractions.py)는 모든 cited grounding이 사라지면 import의 fresh IDs와 실제 철회를 구별 못 해 prose를 유지하는 false negative를 명시한다. 이는 정적 source 정책 확인이지 실제 공격 성공 결과가 아니다. canonical eligibility/provenance repair 없이 wrapper-only strict 철회·restore를 보장하지 않음.

### 13. 새 영상 입력으로 실제 Opus 5.5 / Codex 6.1 Sol xhigh 병렬 적대적 리뷰

**§9의 PR/distribution 리뷰를 영상에 대한 승인으로 재사용하지 않았다.** 두 기계적 subagent가 서로 다른 native CLI를 실제 실행했고, 동일 frozen input에는 상대의 결과/이전 verdict를 넣지 않았다. 원문 자막·공식 출처·A/B/C·engine 재사용/좁은 core를 **동일한 full pipeline·출처/권위·승인/철회·동시성/내구성·보안/배포·host·한국어/효용·비용/6개월 유지관리 잣대**로 비교했다.

#### 13.1 실제 실행 증거와 한계

동일 stdin: **205,168 UTF-8 bytes**, SHA256 `c046de5447908e18d0762a533058d49fe8df4699bff90ac3bdc78a9fb0b5db3b`. 8개 frozen source 전체를 두 실행에 전달했고, 실행 후 입력·raw output hash 및 Opus JSON result의 원문 일치를 확인했다.

| 실제 native 실행 | 모델/effort 확인 | UTC 시작→종료 | 실행 결과 |
|---|---|---|---|
| Claude CLI2.1.296 | `--model claude-opus-5-5 --effort xhigh`; native JSON `modelUsage.claude-opus-5-5` | 12:59:38.388347→13:11:18.131229 | exit0 / success / is_error:false, 699.762초, result44,020 bytes |
| Codex CLI0.162.1 | `--model gpt-6.1-sol`·`model_reasoning_effort="xhigh"`; native runtime banner model/provider/xhigh | 12:59:44.836342→13:07:24.671981 | exit0 / native success, 459.848초, stdout26,732 bytes |

**성공한 두 실행의 겹침459.835초**(UTC timestamp millisecond 정밀도). sequential 결과나 다른 모델 fallback을 요청 모델의 병렬 실행으로 부르지 않았다.

Opus는 빈 임시 cwd·safe-mode·empty tools/MCP·dontAsk·slash-command/session-persistence off로 실행했다. 인증 때문에 original HOME을 사용했으므로 HOME isolation/config immutability를 주장하지 않는다. Codex는 auth-only isolated CODEX_HOME·빈 cwd·ignore user config/rules·ephemeral·read-only로 실행했다. 두 임시 실행 디렉터리는 삭제했다. Opus의 **server-resolved effort field는 없어 unknown**이고 Sol effort는 native banner 증거다. 도구 호출 미관측은 Opus final metadata/설정, Sol prompt-echo 제외 stderr 범위이며 provider 내부 완전 audit/독립 attestation은 아니다.

#### 13.2 모든 새 findings의 수용·부분수용 — 제품 runtime 취약점 판정 아님

IDs는 각 모델 원문 그대로 보존한다. Sol도 `VO1…VO8`을 썼으므로 반드시 모델 이름과 함께 구별한다. P0/P1/P2는 해당 모델의 **설계 위험 우선순위**다.

| 모델·native ID | 지적 | 부모의 판정·설계 영향 |
|---|---|---|
| Opus VS3/P1 | engine 재추출/파생물이 canonical 승인·철회를 우회 | **조건부 수용.** canonical authority와 index/projection 구별, 모든 read/publish/restore eligibility·fence. lineage/ID mapping/모든 경로를 강제할 수 있을 때만 read-time join이 충분. missing lineage를 wrapper metadata로 해결했다고 하지 않음 |
| Opus VS1/P1 | **기억→주입→agent 반복→독립 지지 증가의 echo loop** | **수용.** delivery receipt(candidate/revision/hash/session/turn), source origin/derivation을 기록하고 echo를 독립 support에서 제외. 이후의 실제 새 code 관측/인간 정정까지 일괄 제외하지 않음. receipt만으로 semantic paraphrase를 전부 식별했다는 보장도 하지 않음 |
| Opus VS2/P1 | 재생성/거절 후보의 identity drift | **부분 수용.** code가 영속 ID를 할당하고 approval/rejection은 ID+revision+exact text/scope에 연결. 지원 span 집합을 identity hash로 삼아 새 근거마다 ID가 바뀌게 만들지 않음. fresh inference의 byte-identical prose를 일반 보장하지 않고 persisted/replay 안정성과 ambiguous 재매핑을 검증 |
| Opus VS4/P1 | hook의 높은 채널 권위·미검증 region trigger | **수용.** eligibility와rule 권위를 분리, unverified candidate 표시, 실제 host/version capability·scope·delivery 가시성, reviewer/CI 비활성. install/service 자체가 readiness나 region event를 보장하지 않음 |
| Opus VO2/P1 | draft writer가 facts/corrections/recurring을 섞어 Rules로 승격 | **부분 수용.** 문장별 candidate/source kind·unsupported addition audit, 항목/revision 승인. 인간의 새 명시 standing instruction도 유효할 수 있으므로 'correction에서만 Rules 생성'이라는 불필요 제한은 채택하지 않음 |
| Opus VO3/P1 | 개인1인/팀9인 corpus·고객 partition에 따라 반복 신호 의미가 달라짐 | **부분 수용.** authorized partition 내 집계·profile threshold·한 번뿐인 correction 보존. people 수를 반드시 숨길 필요는 없지만 session 소유자/발언자/명시 지지를 분명히 구별 |
| Opus VS5/P2(기록 채택시P1) | Btel/CAS/raw Query가 추가 사본·agent 접근면 | **조건부 수용.** 데이터 root/credentials/ACL/egress/retention/forget 범위 및 local datasource 명시. 불필요 raw capture와 필요한 관측을 구별. home-scoped shared CAS를 고객 격리로 주장하지 않음 |
| Opus VO1/P2 | POC citation과people 수를 최종 span provenance/인간 동의로 과대 해석 | **수용.** 최종 message/offset actor 보존 미입증으로 정정. host가 typed/pasted/injected를 구별 못 하면 unknown을 보존; 모델 추정으로 authenticated human-typed를 만들지 않음 |
| Sol VO1/P0 | continue/correction/consent/approval/rule promotion 혼동 | **수용.** authenticated actor·정확한 revision/diff·operator 권위를 구별. 동일 UID/DB 접근에서 강한 인간 승인 격리를 보장하지 않음 |
| Sol VO2/P0 | local DB를 no-egress로 오인 | **수용.** capture→classifier/extract/embedding/reflect→recording/backup→recall을 받는 host까지 허용 목적지/profile/customer 격리 |
| Sol VO3/P1 | capture/readiness·interrupt/error/subagent·nullable transcript 차이 | **수용.** adapter별 capability 및 incomplete 표시·원문 회수, fail-open과skip 공개. HTTP command와type:http 구분; 모든 host 지원을 선언하지 않음 |
| Sol VO4/P1 | grouping/truncation/parent-child/retry로 독립 지지·조건 소실 | **수용.** source span과독립 root episode 구분, branch/revision/부정/고객 조건 보존. Opus echo 위험은 이것과 별개로 추가 |
| Sol VO5/P1 | typed probability를 truth/approval로 오인 | **수용.** no-match/불충분·actual model/version·한국어/인용/부정/option order calibration; semantic model은 권한·정확한 count·worker commit을 결정하지 않음 |
| Sol VO6/P1 | hash cache/async accepted를 내구성 완료로 오인 | **수용.** durable ingest ack·worker lease/fence·cancel/replay·eligibility-aware cache. 접수/queryable/human-approved 상태를 구별 |
| Sol VO7/P0 | 철회/forget/old restore resurrection | **수용.** canonical/derived/spool/cache/recording/export/backup 범위. 최신 deletion authority가 없으면 restore/read fail closed. 이미 전달된 host context/외부 provider 보존까지 소급 제거한다고 약속하지 않음 |
| Sol VO8/P2 | 자기 golden·2cents·불완전 공개 코드의 품질/TCO/OSS 일반화 | **부분 수용.** 독립 held-out action·한국어·비용 분모·license 검증 유지. **출시 전에 실제6개월 운영 기록이 필수**라는 범위 확대는 미채택; 6개월 유지관리 위험 분석과 SLA 근거 측정은 유지 |

#### 13.3 모델 간 반론·대안 장단점 — 동의만 모으지 않음

A = session child가 engine/DB/worker 소유. B = 설치형 service+CLI/UI, MCP 없음. C = 공통 service+필요한 MCP+operator 도구/host adapter.

| 대안·쟁점 | Opus | Sol | 최종 판단·장단점·영향 |
|---|---|---|---|
| **A session-owned** | 제품으로 기각, single-user/manual fallback | full 계약의 승인된 유한 실행·내구성/복구가 가능하면 유효 | **blanket 기각은 미채택.** 설치가 제한된 환경의 좁은 profile은 가능. 다만 session 밖 batch·다중 세션 worker·remote endpoint까지 대신한다고 광고하면 안 됨. lease/fence/재시작 책임은 사라지지 않음 |
| **B 설치형만** | 먼저 출시, MCP는 소비자 생긴 뒤 | MCP 소비자 없으면 적절 | 작은 표면/운영 통합이 장점, 사용자 목표의 cross-agent/cloud MCP 접근은 별도. **B-first로 이번 제품 범위를 축소하지 않음**. 근거 없는 추가 host/transport는 구현하지 않음 |
| **C 설치형+MCP** | 구조는C, 나중 read/propose MCP | 조건부 기본 | **기본 권고 유지.** service가 durable lifecycle, MCP가 client interface를 담당. hook은 capture/자동 recall, MCP는 agent-initiated read/write proposal. 추가 auth/version drift 비용이 있지만 MCP와설치의 책임을 혼동하지 않음 |
| **MCP admin 권위** | 승인/승격/forget/export를 MCP에 절대 노출하지 않음 | actor/approval 권위 분리 | 일반 agent catalog는 scoped recall/reflect·capture/candidate proposal 중심. operator rule 승격/고위험 purge/export 권위는 agent가 접근 못 하는 별도 plane. **protocol 자체가 관리 연산을 금지하는 것은 아님**. 명시 policy의 저위험 자동 evidence 처리와관리자 전용 client/권한 가능성은 구별 |
| **기존 OSS engine 재사용** | strict canonical join/provenance spike 통과시, 아니면 이득 축소 | engine 내부 권위 통제 가능시에만, duplicated generic engine 금지 | retain/recall/reflect/worker 재사용 장점. Hindsight는 후보이지 선정 완료 아님. wrapper로 missing lineage·내부 async publish를 통제 못 하면 patch/교체 필요. reflect/mental model을 꺼서 full 요구를 몰래 축소하지 않음 |
| **좁은 신규 core+단일 backend** | 기존 engine 이득이 검색만 남고patch/store 중복이 크면 유리할 수 있음 | 재사용 실패시 같은 full 계약으로 비교 | domain 소유권·단순 배포가 장점. 검색/한국어/reflect/worker/restore/auth를 모두 구현하는 비용이 단점. 여러 engine/backend 공통 추상화는 선제 구현하지 않음 |
| **BAML/Jev 채택** | engine과직교하는 조건부 workflow/gate | type/probability와품질/권한 구분 | BAML typed orchestration/관측과Jev 저가 semantic gate를 **선택 의존성**으로 비교. nightly/hosted egress/Korean/metadata 손실 비용. 영상만으로 필수 stack에 넣지 않음 |

**가장 강한 반대 의견:** engine을 쓰면서 canonical 승인/삭제/규칙 store를 다시 만들고, provenance 없는 reflect를 모두 막아야 한다면 재사용 이득은 embedding/search만 남고 PG·upstream·migration·이중 store 비용은 계속 든다. 반대로 새 좁은 core가 한국어+code retrieval와reflect 품질을 과소평가하면 싸 보이는 설계가 실제 행동을 악화시킨다. **두 경로 모두 같은 full pipeline spike/held-out 기준을 통과해야 하며 지금 엔진 승자를 정하지 않는다.**

#### 13.4 기존 권고의 유지·수정과 영향 범위

- **유지:** 독립 OSS/release, 하나의 공통 domain/schema/operation/state/receipt, 회사 local·개인 self-host cloud의 독립 배포. **fork 두 개는 필요하다는 근거가 없지만 데이터·인증·host·backup·egress·운영 절차는 반드시 나눠야 한다.** local HTTP / 개인 VM HTTPS는 초기 지원 표면이며 '어디서든'은 실제 지원 host/version/auth/capture capability 범위다.
- **수정:** §10의 Hindsight distribution은 **우선 spike할 재사용 후보**이지 backend 선정/production 인증이 아니다. 영상형 제품에는 signal/episode/source authority/candidate/feedback/delivery layer가 필요하다. 기존 generic extractor와동일 기능을 새로 두 번 만들지 않되, wrapper-only로 이 책임이 사라진다고 하지 않음.
- **새 핵심 불변식:** source event ID≠독립 episode ID≠candidate ID≠revision≠approval≠delivery receipt. 수집/재시도 dedup뿐 아니라 **memory-origin echo를 독립 지지에서 제외**한다. source actor를 알 수 없으면 unknown이지 human-confirmed가 아니다. 새 evidence는 ID를 무조건 바꾸지 않고, 바뀐 text/revision은 이전 승인을 조용히 승계하지 않는다.
- **회사/개인 profile:** 동일 상태 기계/승인·철회 의미를 유지하되 개인 preference/1인 corpus와팀 signal threshold·허용 local/hosted inference·auth를 선언한다. **다른 모델에서 byte-identical 문장/품질까지 동일하다고 주장하지 않음**. 고객 partition을 넘어 수를 채우지 않고, 한 번뿐인 correction도 버리지 않는다.
- **영향 단계:** capture adapter/consent·source envelope → semantic extraction/grouping → canonical candidate/approval → engine publication/read eligibility → scoped delivery/receipt → feedback/health → cache/recording/export/backup/restore. author opt-in hook·설치/업데이트/제거는 실제 author 행동 변경이며 core 코드0 변경을 행동 영향0이라고 쓰지 않는다. isolated reviewer/CI는 memory 수집·주입을 기본 상속하지 않는다.
- **6개월 유지관리 비용:** host hook·MCP revision, pinned upstream/PG schema, model/embedding upgrade와re-embed, BAML nightly/Jev alias, operator auth, 한국어+code fixtures, restore drill을 소유해야 한다. 측정 없는 금액/기간 추정은 하지 않는다. canonical authority는 하나, index/directive/invalidations는 단방향 projection; 소비자 없는 stdio·멀티 backend·대시보드 중복은 피한다.
- **불가능 조건 유지:** 회사 반출 금지와개인 cloud host가 해당 내용을 읽는 요구는 승인 경계 없이 양립 불가. 필요한 service/compute/model과동등 유한 대안이 모두 금지되면 full pipeline 미지원. host가 capture/next-task recall/auth를 제공하지 않으면 해당 자동 surface 미지원. agent/operator 권한이 실제 같으면 강한 인간 승인 격리 미지원. latest deletion head를 복구 못 하면 forget-restore 보장 미지원. 이름/profile/VPN/MCP marker만으로 해결되지 않음.

#### 13.5 채택 전 관측 기준 — 아직 실행하지 않은 수용 조건

1. supported host/version 실제 event trace: interrupt/error/subagent/async transcript·readiness·scope trigger·reviewer/CI 비활성 및 수집/전달 가시성.
2. 동일 root/child/retry와memory echo fixture: 독립 support 중복 없음, 새 인간 정정/새 revision 관측 보존, 한 번뿐인 correction candidate 보존, crossed-customer leakage 없음.
3. candidate identity/revision·거절 재제안·unsupported draft sentence audit: 명시 revision 없이 승인 text 변경 없음. fresh generation의 표면 문장 일치를 품질 지표로 삼지 않음.
4. canonical/engine race: 접수와commit 구별, 승인/삭제 후 늦은 worker·reflect·mental model·cache replay가 authority를 우회하지 않음. incomplete provenance는 authority 있는 답으로 사용하지 않으며 underlying 기능을 복구/패치해야 함.
5. forget canary·recording/CAS/export/old backup 복원·latest deletion head 차단, OS/credential 권한과전체 egress 관측. 이미 밖으로 전달된 사본의 삭제 불가능/retention 범위를 명시.
6. 한국어+code/부정/인용 공격/조건/개인 preference의 held-out task/repo state, memory-on/off 후속 행동. 자기 golden agreement가 아닌 outcome을 평가하고 cold/hot/replay·전체 인프라·검토 시간을 분리 측정.

**실행한 것은 원문 다운로드·전체 자막 검토·ffprobe/2개 frame 확인·공식 source 교차 확인·실제 두 native 모델의 병렬 리뷰와hash 대조다. 메모리 제품의 위 수용 조건/품질/복구 test 통과를 보고하는 것이 아니다.** chonamdoo/agent-flow#334의 새 code review/approval을 받은 것도 아니다.

#### 13.6 보존한 새 증거

모든 파일은 이 독립 저장소의 로컬 `research/`에 보존했다. 이번 이슈 갱신은 source commit/push·저장소 공개 전환·라이선스 채택·제품 구현을 의미하지 않는다.

- 원문: `video-mAKUL12h1n8-refetch.en-orig.json3`, `video-mAKUL12h1n8-transcript.timed.en.txt`, `video-mAKUL12h1n8-source-provenance.json`, `video-mAKUL12h1n8-claims-check.json`, 확인한2개 PNG.
- source 재분석: `video-mAKUL12h1n8-reanalysis.ko.md`, `video-mAKUL12h1n8-tools.ko.md`, `video-mAKUL12h1n8-portable.ko.md`, `video-mAKUL12h1n8-primary-checks.ko.md`.
- 고정 입력/manifest: `video-review-input.ko.md`, `video-review-manifest.json`.
- Opus 원문: `video-review-opus-5.5-xhigh.ko.md`, SHA256 `c21be59dbd61809d8455582f87e01ff9ca34da0d076d80461d3a2b45b7c71f66`. exact native JSON result 및raw JSON/evidence를 별도 보존.
- Sol 원문: `video-review-codex-6.1-sol-xhigh.ko.md`, SHA256 `67bed62334d1931a092ade70d36bd70ca898da2cb7db2c8a370bf32721af2edd`. native stdout/evidence 보존.
- 검증: `video-native-parallel-proof.json`; 원문 verdict를 고치지 않은 부모 판단은 `video-disposition-opus.ko.md`, `video-disposition-codex.ko.md`; 이번 통합은 `video-review-integration.ko.md`.
