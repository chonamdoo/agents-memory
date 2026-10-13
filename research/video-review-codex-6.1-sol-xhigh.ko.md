1. **결론: 회사 local과 개인 self-host cloud에서 같은 pipeline 코드·schema·상태 계약을 쓰는 것은 가능하다.** corpus를 공유하거나 같은 모델 출력·검색 순위·비용을 보장하는 것은 별개의 주장이다. capture adapter, inference profile, 인증·권한, 데이터 root, recording·backup, 운영 설정은 환경별로 분리해야 한다. **[INFERENCE]**

조건부 기본안은 **C: 공통 설치 service/domain + 관리 CLI/UI + 필요한 MCP 접속면**이다. 실제 MCP 소비자가 없으면 B가 더 작다. 한 세션이 engine·worker의 실행 수명을 소유해도 요구를 충족하는 경우에는 A도 유효하다. MCP는 설치형과 양자택일하는 제품 형태가 아니라 접속 규약이다.

기존 OSS engine은 generic 추출·검색·reflect·curation을 재사용할 가치가 있다. 그러나 **승인·source revision·삭제 권위를 내부 worker, 합성 결과, import/restore까지 강제할 수 있어야 한다.** 이를 보장하지 못하는 engine에 thin wrapper만 붙이는 안은 기각한다. 반대로 해당 책임을 지원하는 engine을 두고 generic 기능을 다시 만드는 안도 기각한다. 좁은 신규 fixed-backend core는 이 통제 불가능성이 확인됐을 때 비교할 대안이다. **[INFERENCE]**

이 판정은 제공된 전체 자동 자막과 frozen 문서에 한정한다. 제품 acceptance는 모두 미실행이며 production-ready 판정이 아니다. 아래 출처 약어는 다음 packet을 뜻한다.

- **T:** `research/video-mAKUL12h1n8-transcript.timed.en.txt`
- **R:** `research/video-mAKUL12h1n8-reanalysis.ko.md`
- **D:** `research/video-mAKUL12h1n8-tools.ko.md`
- **P:** `research/video-mAKUL12h1n8-portable.ko.md`
- **X:** `research/video-mAKUL12h1n8-primary-checks.ko.md`

2. **원문 재분석 판정: 08:20은 지역별 context shard와 출처를 보여주는 추출·보고서 시연이다. 독립 memory 제품 전체의 완성 증거는 아니다.**

| 구간 | 원문에서 구분할 내용 | 판정 |
|---|---|---|
| 04:49–06:54 | tool call을 제거한 user/assistant 단일 추출 POC, citation, task/session enable 설명 | POC 설명과 화자의 품질 자기 평가. 조건부 shard·session/message/user citation은 유지할 설계 요소다. |
| 07:54–10:28 | 코드 영역별 Markdown, 탐색 경로·행동 규칙·언어 사실, 복수 session/person 근거 | 결과 시연. 발견한 사실과 인간이 요구한 행동 규칙은 권위가 다르다. 복수 citation은 승인이나 정확성의 증명이 아니다. |
| 10:30–11:48 | 반복 조사 보고서에 repo를 함께 주자 기존 `architecture.md` 참조 누락을 발견 | 새 사실을 계속 추가하기보다 기존 문서 pointer를 제안할 수 있다. pointer도 해당 revision·scope에서 확인해야 한다. |
| 20:05–28:18 | facts / human corrections / recurring investigations, session별 추출과 grouping | 세 갈래의 목적을 구분해야 한다. 사실 수, 정정 수, 독립 조사 episode 수를 같은 카운터로 합치면 안 된다. |
| 34:58–37:27 | parent→child 질문, tool paths, 실제 읽은 file contents, child final report로 code map 작성 | **trace-derived 질문·탐색·답변 근거**다. 전체 코드의 정적 관계·답변의 참·현재 코드와의 일치를 증명하지 않는다. 34:14에는 heat-map 시각화가 아직 없다고 말한다. |
| 38:08–43:48 | BAML 실행 recording을 Query로 읽고 custom server/UI에 표시 | 실행 관측 시연이다. 임의 coding host의 전체 capture나 canonical memory DB 시연으로 확대할 수 없다. |
| 12:55, 16:14, 24:02–24:30 | “Two cents per session”, 개발 탐색 약 $100와 보고서 50 cents, 60% text/100% valuable | 화자의 워크로드·golden run에 대한 자기 관찰이다. 일반 단가·한국어 품질·독립 benchmark가 아니다. |
| 44:06, 48:23, 49:11, 50:46–53:09 | health, memory-off backtest, stale 판단, 승인·거절을 넣는 fourth input | 후속 아이디어다. 완성된 health/feedback 운영 시연으로 판정하지 않는다. |

**유지해야 할 generic 설계**는 세 갈래 신호, 원문 citation, 조건부 전달, 기존 문서 pointer, cross-session 분석, 관측 가능한 stage다. 특정 앱의 기존 codegraph 재사용과 SQLite/FTS5 적용안은 이 결론에서 제외한다.

**수정해야 할 설계 해석**은 다음과 같다.

- 영상의 facts 단계가 personal preference를 제외하더라도 독립 개인 memory 제품 전체에서 선호를 버릴 이유는 없다. 개인 선호는 해당 actor·scope의 별도 memory로 다뤄야 한다. **[INFERENCE; T 29:31–30:00]**
- “모델이 썼으니 이미 weights에 있어 무가치”라는 일반 명제는 성립하지 않는다. 새 원문에서 추출한 내용은 입력으로 얻은 정보이며, 이미 아는 지식도 task에 맞게 조건을 명시하는 효용이 있을 수 있다. 채택 여부는 후속 행동으로 평가해야 한다. **[INFERENCE; T 22:23–22:58]**
- 중간 절단이나 처음/끝 보존도 blanket 규칙으로 채택하지 않는다. 자동 자막의 23:04 표현은 앞선 설명과도 어긋난다. 정확한 절단 구현보다 **누락 표시·원문 offset·재회수 경로**를 계약으로 삼아야 한다. **[T 20:30–21:19, 23:04–23:13]**
- feedback conditioning은 versioned workflow/context 개선이다. 모델 weights 학습이나 독립 품질 개선의 증거가 아니다. **[T 50:46–53:09]**

도구의 의미도 고정해야 한다.

| 도구 | packet이 지지하는 범위 | 승격하면 안 되는 의미 |
|---|---|---|
| BAML v1 | typed programming/SDK·parser·배포 도구. 제공 문서는 pre-1.0/public beta로 설명 | 안정 semver 1.0, 사실성 검사, 승인 engine. legacy v0 자료를 v1 API 근거로 섞으면 안 되며, `legacy0` branch 실재도 확인되지 않았다. |
| Query/Btel/CAS | raw recording은 Btel+content-addressable snapshots, SQLite는 재구축 가능한 query index | canonical 승인·삭제 DB, memory commit 보장. **content-addressable CAS는 concurrency compare-and-swap가 아니다.** |
| Jev | choice·noul·score의 제한된 판단. 같은 요청의 질문은 독립 평가 | 자유 서술 추출·보고서 generation, calibration·진실·인간 승인 |
| pin한 BAML Jev adapter | enum→choice, float→noul probability, bool→p≥0.5. score 요청 생성 없음 | provider 전체 probabilities/confidence 보존. 기록한 요청 모델명이 실제 resolved version의 증거라는 주장 |

출처: D §§2–5. 공식 episode의 지정 공개 snapshot에는 `meta.md`와 thumbnail만 있다. 이것은 **그 링크에서 전체 시연 pipeline을 재현할 수 없다는 근거**이며, 인터넷 전체에 구현이 없다는 판정은 아니다. 별도 file-memory·routing toy도 영상 구현을 대신하지 않는다. **[D §7]**

3. **Adversarial findings — 8개.** 아래 scenario는 모두 **[INFERENCE]**이며 실제 공격 성공이나 제품 test 실패를 뜻하지 않는다. P0는 해당 강한 정책을 약속할 때의 출시 차단 조건, P1은 기능·상태 계약의 중대한 결함, P2는 채택 근거의 부족이다. 관측기준은 모두 **미실행 acceptance**다.

**VO1 · P0 — 대화상의 correction·tool 허가가 규칙 승인으로 승격될 수 있다.**

- **근거:** T 09:54–10:25의 “rules which are like behavioral”, 51:22의 “the user approved it”; P §§3, 6.2, 7.2의 승인·tenant 경계. H5 validator는 확장점이며, H8 기본 tenant는 인증 없는 단일 schema다.
- **소비자에게 보이는 실패:** 인용된 “user” 문장이나 retain 실행 허가가 팀 directive로 발행되어 다음 작업을 바꾼다. 같은 UID의 agent가 operator credential/DB를 읽을 수 있다면 승인 API의 역할 구분만으로 강한 인간 승인을 보장하지 못한다.
- **최소 수정:** execution permission, capture consent, factual correction, candidate acceptance, rule promotion을 별도 이벤트로 둔다. 승인은 authenticated principal의 권한으로 **특정 candidate revision과 exact diff**에 결합한다. 저위험 evidence memory의 자동 처리는 명시 policy로 허용하되 규칙 승격과 분리한다. 강한 승인 격리는 agent가 읽을 수 없는 승인 수단·서비스 권한을 전제로 한다.
- **관측기준:** quoted “approve”, 다음 단계 요청, tool 실행 허가, 위조 actor label로 rule을 활성화할 수 없어야 한다. 승인 후 내용이 바뀌면 재승인이 필요해야 한다. 같은 UID에서 operator 권한을 획득할 수 있다면 강한 인간 승인 지원으로 표기하지 않는다.

**VO2 · P0 — local/self-host 표기가 전체 egress와 고객 격리를 대신할 수 있다.**

- **근거:** T 36:14–36:24의 “contents of every file”; D §§4.3, 5.3, 6.3; P §7. Jev 기본 endpoint, 별도 telemetry/query 설정, engine 모델·artifact 다운로드 경로가 기록돼 있다.
- **소비자에게 보이는 실패:** 회사 DB는 local인데 classifier·extractor·reflect·trace·backup 또는 recall을 받은 hosted LLM으로 회사 원문이 나간다. 개인 credential/home 설정이 업무 session에 상속되거나 caller tags로 고객 bank를 선택해 corpus가 섞인다.
- **최소 수정:** local storage, approved SaaS, strict no-egress를 별도 profile로 선언하고 capture부터 받는 host LLM까지 destination을 통제한다. 환경·고객별 principal, DB/corpus, spool, credential, logs, backup을 분리한다. strict profile의 모델 장애는 silent hosted fallback 대신 명시 실패로 처리한다.
- **관측기준:** 분류·추출·embedding·rerank·reflect·query·host delivery·backup 각각의 실제 destination을 관찰한다. 회사 session에 개인 credential을 넣어도 접근이 거부돼야 한다. 승인된 내부 inference/artifact가 없으면 strict full pipeline은 미지원이다.

**VO3 · P1 — MCP/Query가 capture completeness와 시작 시 recall을 보장하지 않는다.**

- **근거:** T 38:47의 “certain types of functions”; P §4와 X의 host 계약. Claude launch `SessionStart`는 MCP readiness 전에 tool hook을 skip하며, 해당 event는 command/mcp_tool handler만 지원한다. Codex prompt/agent handler는 “parsed but skipped”이고 hosted WebSearch는 local tool hooks를 거치지 않는다.
- **소비자에게 보이는 실패:** 처음 작업에는 기억이 전달되지 않았는데 자동 recall 지원으로 표시된다. interrupt·API error·지연 transcript·child handback이 누락된 자료를 전체 session으로 표시한다.
- **최소 수정:** host/version/surface별 capture·delivery capability와 누락 의미를 명시한다. Claude startup HTTP 호출은 지원되는 **command handler 안의 client 요청**으로 구현할 수 있지만 `type:http` handler로 설명하면 안 된다. service readiness, durable ingest receipt, pending/partial 상태를 노출한다.
- **관측기준:** cold start, resume, clear/compaction, interrupt, API failure, child handback에서 receipt와 실제 전달 내용을 대조한다. remote endpoint에 path만 보냈을 때 bytes를 받았다고 표시하지 않는다. own VM의 설치형 CLI와 일반 hosted 제품 지원을 분리한다.

**VO4 · P1 — grouping·절단·중복 집계가 출처의 조건과 독립성을 지울 수 있다.**

- **근거:** T 20:30–21:19의 장문 filtering bug, 27:35–28:18의 “facts that are the same thing”, 34:58–37:27의 parent/child 자료; P §6.1.
- **소비자에게 보이는 실패:** 한 요청의 child 보고서·parent 요약·resume/export가 여러 독립 조사로 계산된다. 서로 다른 고객·branch의 조건부 사실이나 부정문이 전역 규칙으로 합쳐진다. 많이 읽힌 파일이 현재의 정답 근거로 취급된다.
- **최소 수정:** source span·조건/부정·scope·revision을 보존하고, investigation episode identity와 evidence identity를 분리한다. grouping은 충돌을 남겨야 한다. unknown lineage는 반복으로 승격하지 않는다. code map에는 실제 읽은 snapshot과 답변의 지지 관계를 남긴다.
- **관측기준:** 한 요청→child 3개→parent 요약→재전송/export는 한 episode로 남아야 한다. 다른 날의 독립 조사는 bytes가 같아도 별도 episode다. 한국어 조건·부정·상충 branch와 장문 중간의 핵심 요청이 결과 또는 명시 누락 상태로 추적돼야 한다.

**VO5 · P1 — typed probability가 semantic correctness gate로 과대 해석될 수 있다.**

- **근거:** T 17:25–17:35의 “probability that it matches this description”; D §§5.1–5.4, X의 confidence 확인. 공급자는 CJK 품질 차이, option-order bias, double negatives와 adversarial state 약점을 설명한다.
- **소비자에게 보이는 실패:** 정답 option이 없는 choice가 높은 concentration으로 선택된다. 한국어 간접 정정이나 인용 공격을 bool p≥0.5로 통과시킨 뒤 “검증된 사실”로 저장한다.
- **최소 수정:** extraction과 제한된 judgment를 분리한다. no-match/불충분 상태, source entailment·충돌 확인, domain별 threshold를 둔다. 필요한 확률 metadata와 실제 모델 version을 보존한다. 타입 적합성·확률·승인 상태를 별도 필드로 다룬다.
- **관측기준:** option 순서 변경, 정답 후보 부재, 한국어 간접 정정·부정·quoted attack에서 false-positive와 abstention을 평가한다. 입력에 feedback을 넣은 개발 자료와 held-out 자료를 분리하며, 실제 후속 coding 피해까지 측정한다.

**VO6 · P1 — hash cache와 async accepted가 durable 작업 완료로 오인될 수 있다.**

- **근거:** T 18:56–19:01의 “hashing the inputs”; P §8의 retain `accepted` 의미; D §4.1의 recording 동기화·완결성 한계.
- **소비자에게 보이는 실패:** 저장됐다는 응답 뒤 session child가 종료되어 작업이 사라진다. 이전 revision을 추출한 worker가 correction 뒤에 완료되거나, 같은 원문의 cache가 다른 policy/권한 상태에서 재생되어 폐기된 기억을 발행한다.
- **최소 수정:** ingest/operation identity, durable ACK, retry/dedup, lease/fence/cancel, publish 시 최신 source·권한 상태 검사를 둔다. **ingest accepted, queryable, human-approved는 별도 의미**다. cache key는 stage·prompt/schema/parser·model·policy/source revision을 포함하고, hit에서도 현재 eligibility를 검사한다.
- **관측기준:** ACK 전후 kill·재시작, 동시 session, lease 만료, correction 중 extraction/reflect, cancel 뒤 완료, stale cache replay에서 작업 소실·중복 승격·오래된 publish가 없어야 한다. cache hit를 새 추론이나 새 승인으로 기록하지 않는다.

**VO7 · P0 — retired/retracted/forget과 restore가 같은 삭제 의미로 취급될 수 있다.**

- **근거:** T 49:11의 “my one idea”; P §§5, 6.3, 7.3와 X의 Hindsight 정적 확인. `RetractedGrounding.unresolvable`은 모든 cited ID가 사라진 경우 prose를 유지할 수 있다. invalidate는 soft-retire이며 Query index 삭제는 raw Btel/CAS 삭제가 아니다.
- **소비자에게 보이는 실패:** 원문 철회 뒤 derived prose가 다음 recall에 남는다. source를 forget했지만 recording/cache/spool/export/old backup 또는 오래된 worker가 복원한다. import의 ID 변경과 실제 철회가 구분되지 않는다.
- **최소 수정:** rejected, stale, superseded/retracted, soft-retired, privacy-forgotten 상태를 분리한다. 최신 deletion authority로 read·publish·restore를 차단하고 source→derived 의존성을 유지한다. 최신 삭제 head를 복원할 수 없으면 해당 scope를 fail closed한다. 이미 전달된 외부 context의 회수 가능 범위도 별도 계약으로 명시한다.
- **관측기준:** 전체 grounding 철회, ID-remap import, 작업 중 forget, cache/index rebuild, 오래된 backup restore 후 폐기된 내용이 recall·reflect·export에 재출현하지 않아야 한다. row 삭제와 derived 문장 eligibility를 함께 관찰해야 한다.

**VO8 · P2 — 시연·자기 golden run·불완전한 공개 코드로 제품 효용과 TCO를 입증할 수 없다.**

- **근거:** T 12:55의 “Two cents per session”, 24:27의 “100% of the data”, 44:06–53:09의 health/feedback 논의; D §§6–7의 비용·정확한 Demo Code 공개 범위.
- **소비자에게 보이는 실패:** 영어 개발 corpus의 자기 평가를 한국어·다른 host/model에 적용해 무효 기억을 주입한다. stage 비용을 운영 단가로 소개하지만 재처리·host context·검토·복구 비용이 빠진다.
- **최소 수정:** 시연·화자 주장·후속 아이디어를 제품 문서에서 구분한다. source/fixture/model/prompt/cache/가격 snapshot과 전체 lifecycle usage를 확보하고, memory-on/off를 같은 초기 task/repo state에서 독립 평가한다. 정책이 달라진 뒤 과거 후속 user 입력을 기계적으로 이어 붙이지 않는다.
- **관측기준:** 한국어·영어·code exact identifiers·negative/quoted attack strata의 held-out action, 정정 반영, 해로운 rule promotion, 비용·지연을 측정한다. 공개 가능한 구현·license·artifact와 여섯 달 유지관리 기록을 확인하기 전 일반 SLA/TCO 수치를 주장하지 않는다.

4. **같은 잣대의 비교표: 접속·수명주기 선택과 engine 선택은 서로 다른 축이다.**

| 제품 형태 | 유효한 조건 | 장점 | 같은 계약에서의 부담·가장 강한 반론 |
|---|---|---|---|
| **A — session child stdio가 engine/DB/worker 소유** | 단일 owner 중심이며 session 밖 진행을 요구하지 않음. kill 후 durable 작업을 다음 실행에서 복구할 수 있음 | 별도 daemon 운영이 작고 host 연결이 단순 | 동시 session·종료 후 worker·중복 DB owner·복구가 어려워진다. 항상 켜진 공통 owner를 추가하면 실질적으로 C에 가까워진다. |
| **B — 독립 service + 관리 CLI/UI, MCP 없음** | host adapter나 own application이 직접 API/command로 capture·recall을 연결 | 설치·worker·승인·복구 수명이 session과 분리됨. MCP 호환성 비용이 없음 | 각 소비자 integration을 소유해야 한다. **MCP가 없다는 이유로 자동 pipeline이 불가능한 것은 아니다.** |
| **C — 공통 service/domain + 관리 도구 + 필요한 MCP** | 여러 session/host와 실제 MCP 소비자가 있으며 설치·운영이 허용됨 | 공통 worker·권위·복구 계약을 유지하면서 local HTTP/personal HTTPS 제공. 필요할 때 thin stdio 사용 | service와 MCP·installer·host adapter를 모두 유지한다. 실제 MCP 소비자가 없으면 B보다 불필요한 면이 늘고, 상시 service만으로 같은 UID의 승인 격리가 해결되지 않는다. |

**C의 가장 강한 반론:** 실제 소비자가 하나이고 session 밖 작업이 필요 없는데 service·관리 UI·HTTP·stdio·hooks를 모두 넣으면 유지관리와 공격 면이 커진다. 설치나 권한 격리가 불가능한 환경에서는 C의 장점도 요구를 충족시키지 못한다. C를 보편 정답으로 정하지 않는다. **[INFERENCE]**

참고로 packet의 pin한 Hindsight `mcp_local.py` entrypoint는 HTTP API를 시작하는 wrapper다. 파일명이나 오래된 주석만으로 A의 stdio engine 소유 구조라고 분류하면 안 된다. **[P §2.2]**

| 동일 판단 축 | 기존 OSS engine + 작은 domain/control layer | 좁은 신규 fixed-backend core |
|---|---|---|
| 자동 추출·검색·reflect | generic 구현 재사용 가능. domain extraction이 기존 extension/custom strategy로 충족되는지 먼저 확인 | 필요한 범위만 구현할 수 있지만 추출·검색·reflect 품질과 worker까지 직접 소유 |
| source·approval 권위 | event/episode/revision·승인 ledger를 보완하되 engine 내부 publish에도 강제해야 함 | canonical 상태와 publish 계약을 함께 설계 가능. 구현·검증 부담은 그대로 남음 |
| 정정·삭제·복구 | 내부 합성·retraction·import 의미가 맞으면 큰 이득. 맞지 않으면 patch 유지 또는 채택 기각 | 의존성·tombstone·restore를 직접 통제할 수 있으나 빠뜨린 경로도 직접 책임 |
| 한국어·code 검색 | 기본 모델·후처리를 그대로 품질 보장으로 사용하지 않음 | backend를 좁혀도 한국어·identifier·조건 보존 문제는 해결되지 않음 |
| 배포·여섯 달 유지관리 | engine/DB/model 업그레이드와 extension 경계 변경 비용 | upstream engine 비용 대신 자체 migration·검색·worker·auth·복구 비용 |
| 기각 조건 | wrapper가 막을 수 없는 publish/restore, provenance 변형, 지속적인 깊은 patch 필요 | 좁은 이름 아래 full pipeline 책임을 생략하거나 generic engine를 중복 구현 |

**단일 engine 유지에 대한 strongest dissent:** 승인된 claim이 engine의 재추출 과정에서 일반화되고, 그 결과의 원문 span·revision 관계를 복구할 수 없다면 승인 대상을 유지할 수 없다. 철회 뒤 provenance 없는 prose가 살아남고 내부 worker/import가 최신 deletion authority를 확인하지 않는다면 gateway precheck로는 고칠 수 없다. 이 경우 engine 확장·수정 또는 교체가 필요하며, “작은 wrapper”라는 전제는 성립하지 않는다. **[INFERENCE; P §§5–7, X]**

BAML은 workflow/관측/배포 도구, Jev는 제한된 판단 도구다. 어느 쪽도 memory engine 대안과 동치가 아니며, 두 engine 선택 모두에 직교한다.

5. **영향 범위·조건부 채택: core code 변경이 없어도 agent 행동과 운영은 바뀐다.**

| 책임 | 제품에 생기는 영향·필수 경계 |
|---|---|
| Capture | 승인된 host events/transcript/file snapshots를 수집한다. host/version별 누락·지연·managed policy를 지원 계약에 포함한다. |
| Extraction | 자동 facts/corrections/investigations를 처리한다. actor 권위나 완료 여부를 원문 문자열에서 만들어내지 않는다. |
| Lineage | parent/child/resume/retransmission을 evidence로 연결하고 독립 episode 집계를 유지한다. |
| Candidate | 조건·부정·scope·revision·source spans를 보존한다. 반복은 우선순위 신호다. |
| Approval | candidate revision과 publication 권위를 관리한다. 현재 actor trust·UI outcome 전달은 미확정 prerequisite다. |
| Feedback | 거절 이유와 기존 승인 상태를 incremental workflow에 사용한다. 거절은 곧 거짓이라는 label이 아니다. |
| Delivery | scoped recall·pointer·context shard가 다음 행동을 바꾼다. hook의 높은 메시지 우선순위가 원문에 정책 권위를 부여하지 않는다. |
| Recording | raw transcript·file snapshots·Btel/CAS는 별도 민감 자료와 삭제 대상이다. |
| Cache | replay와 fresh inference를 구분하고 현재 source·권한·삭제 상태를 재검사한다. |
| Retraction | source와 derived 결과의 eligibility를 함께 갱신한다. stale 검토와 privacy forget을 분리한다. |
| Packaging | service·DB·worker·host 설정의 설치/업데이트/제거·migration·offline artifact·license를 소유한다. |
| Inference | 환경별 승인 모델·embedding·reranker·classifier를 선택한다. 같은 code가 품질 동등성을 보장하지 않는다. |
| 운영 | credentials·backup·logs·restore·지원 버전을 관리한다. 개인 memory/corpus를 isolated reviewer에 상속하지 않는다. |

tracked `AGENTS.md`/`CLAUDE.md` 변경은 후보 diff로 다루고, 승인 없이 global MCP/hook·home 설정을 덮어쓰지 않는다. 초기 설치 허가, capture consent, 문서 변경 승인은 계속 구별한다. **[INFERENCE]**

여섯 달 비용을 지금 금액이나 인력 수로 산정할 근거는 없다. 최소한 host hook/transcript 변경 대응, 모델 upgrade 후 품질 재평가, schema·source ID migration, worker 복구, 삭제/backup 복원, offline package와 dependency license, installer 제거를 유지관리 항목으로 잡아야 한다. 기존 engine의 generic extraction/search/reflect와 이를 복제한 두 번째 계층, 소비자 없는 stdio/HTTP adapter, 검증 전 멀티-backend abstraction은 불필요한 비용 후보이다. **[INFERENCE]**

VM/Compose는 지속 worker와 DB/artifact를 직접 소유하는 배포안이다. serverless도 durable queue·DB·worker 수명을 별도로 확보하면 가능하지만 request process만으로 이를 대체하지 못한다. own cloud VM에서 지원 CLI를 실행하는 표면과 일반 hosted 제품의 hook 지원은 별개다. **[INFERENCE]**

조건부 채택을 위한 prerequisite는 다음과 같다.

- **권위:** actor·tenant·operator 권한과 승인 UI/event, 내부 async publish·restore까지의 통제 가능성.
- **자동화:** 지원 host/version에서 capture·ingest·선택적 recall·reflect·후속 task 사용의 실제 연결과 누락 표시.
- **회복:** durable ACK·fencing·cancel·동시 session, correction/forget 이후 재출현 차단, 최신 deletion head 복구.
- **품질·운영:** 한국어/code/조건·부정/quoted attack의 held-out 행동 평가, 전체 비용, offline artifact·license·업데이트/제거 확인.

MCP current spec와 shipping host/SDK의 협상 revision·기능은 별도로 확인해야 한다. read/write tool 지원이나 annotation은 ACL이 아니며, elicitation 지원도 승인 권위를 구현하지 않는다. end-user OAuth와 Run IAM ID token도 서로 대체하지 않는다. **[P §§2–4; INFERENCE]**

승인된 내부 모델/compute가 없으면 strict no-egress 자동 pipeline은 미지원이다. 필요한 host capture가 없으면 full automatic 지원은 미지원이며 tool-only/export-only를 동등 지원으로 표시하지 않는다. DB/service 설치가 금지되고 필요한 대체 실행 환경도 허용되지 않으면 해당 배포는 불가능하다. 이러한 조건은 공통 domain code를 fork할 이유보다 **지원 profile을 분리할 이유**다. 서로 양립할 수 없는 source·권한·lifecycle 의미를 요구할 때에만 별도 core 분리를 검토한다. **[INFERENCE]**

이 리뷰는 독립 OSS memory 설계 판정이며, merged AgentFlow #334의 재리뷰·새 engine 구현·code review seal이 아니다.
