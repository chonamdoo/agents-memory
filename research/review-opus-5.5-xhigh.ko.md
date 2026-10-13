# 적대적 설계 리뷰 — 로컬·클라우드 MCP 메모리 (2026-10-11 동결 자료)

## 1. 판정

**공통 pipeline은 좁은 의미로만 가능하다.** 하나의 release(코드, SQL migration, MCP tool schema, 상태기계, 권한·삭제 의미, conformance suite)를 서로 아무것도 공유하지 않는 둘 이상의 배포에 설치하는 형태다. design-contract의 "데이터·자격증명·추론 경계까지 하나로 합치는 것은 기본 금지"라는 선언은 맞다.

다만 자료는 경계를 **데이터 계층**(DB, 키, log, backup)에만 그었다. 실제 반출이 일어나는 **OS 사용자, host 설정, host hook, shell 도구** 계층은 분리하지 않았다(F1, F2). 이 경계를 추가하지 않으면 요구 3·4는 충족되지 않는다.

| 구분 | 항목 |
|---|---|
| **동일 보장 가능** (conformance로 검증) | release digest, migration checksum, MCP tool 이름과 입출력 schema, write/recall 상태값과 전이, scope·authority·ACL 판정, 정정 CAS 충돌 응답, retract/purge 상태, deletion ledger 의미, manifest 형식, 오류 코드 |
| **조건부 근사** (같은 것을 고를 때만) | embedding 가중치 hash, tokenizer/normalizer, 런타임 계열(예: 양쪽 CPU 런타임), extension에 의존하지 않는 한국어 lexical 처리, PG·vector extension 버전(관리형 지원표가 허용할 때). 이 경우에도 벡터와 rank는 bitwise 동일이 아니라 허용 오차 내 근사다 |
| **불가** | LLM 추출·반성 출력, Metal/MLX와 CUDA/CPU 결과, latency·HA·RPO/RTO·비용, 백업 매체 특성, egress 표면, 모델 공급자 계약 |
| **반드시 분리** | OS 사용자(또는 기기/VM)와 host 설정 홈·keychain·hook, PG cluster·artifact·log·outbox·cache·LLM trace, 자격증명·IdP, 백업 매체와 deletion ledger 사본, egress 정책, 평가 fixture(업무 fixture는 업무 경계 밖으로 나가지 않음), 고객별 배포 상호 간 |

release artifact는 승인된 staging에서 각 배포로 **단방향**으로만 흐른다. 배포에서 공통 영역으로 향하는 데이터 흐름은 0이어야 한다.

### 추천안: "A-min"

**단일 release의 얇은 PostgreSQL 도메인 코어. v1에는 서버측 LLM이 없고, 업무(고객별)와 개인을 독립 배포한다.** 채택 조건은 다음과 같다.

1. 업무는 고객별, 개인은 별도의 macOS 사용자 계정에서 실행한다. 가능하면 기기나 VM을 분리한다(F1).
2. v1의 write 경로는 host agent가 명시적 tool로 원자적 claim과 source span을 제출하는 것 하나뿐이다. 서버는 추출·reflect·mental model을 하지 않는다. 그 결과 work-local-strict의 서버측 추론 표면은 "고정 hash 소형 embedding 모델 1개(선택적으로 reranker)"로 줄어든다(F3).
3. bounded event는 PG에만 저장한다. GCS 같은 객체 archive는 두지 않으며, 상한 초과 요청은 거절한다.
4. vector 검색은 scope 안 exact 검색으로 시작한다. lexical은 extension에 의존하지 않는 n-gram을 쓴다(F9).
5. authority 모델과 사람 승인 채널(F4), worker fencing(F5), ledger 선기록과 독립 사본(F6)을 갖춘다.
6. Agent Flow가 띄우는 세션에 memory tool이 보이지 않음을 관찰로 확인한다(F2).
7. host 지원은 실제 roundtrip이 확인된 행만 주장한다(F8).

**전환 조건**은 두 가지다.
- 사용자가 정한 dogfooding 기간 뒤 명시적 기록만으로 기억량이나 유용성이 부족하다면, 개인 cloud에서만 추출 capability를 flag로 켠다. 예를 들어 Hindsight를 outbox에서 재구성 가능한 비권위 projection으로 붙인다. 업무 쪽은 회사가 승인한 local 모델과 로컬 평가를 거친 뒤에만 켠다.
- 사용자가 parity보다 운영 최소화를 원한다면, 개인은 managed, 업무는 A-min 단독으로 간다(3장의 최강 반론 참조).

### local-strict 판정 보충

- A-min에서 서버측 egress 후보는 다음으로 좁혀진다.
  - artifact·모델·패키지 fetch(사전 반입으로 차단)
  - 라이브러리 telemetry와 crash report(비활성화와 deny)
  - OS 동기화·백업(F1)
  
  host 모델 egress는 별도 범주다.
- **memory는 egress 증폭기다.** host가 cloud 모델인 업무 세션(`work-local-approved-inference` 포함)에서 local memory는 중립이 아니다. recall은 과거 세션과 다른 프로젝트의 누적 corpus를 현재 prompt에 실어 provider로 보낸다. 승인 계약이 프로젝트나 목적 단위라면 cross-project recall 자체가 위반일 수 있다.
  - 업무 배포의 기본 recall scope는 현재 프로젝트로 한다.
  - 같은 고객 안의 cross-project recall도 기본 off로 둔다.

### 이미 충분히 다뤄져 발견으로 반복하지 않는 것

accepted≠queryable, unavailable≠empty, task-name dedup의 한계, GCS/queue 원자성 부재, WORM 기본 미사용, zero-knowledge≠at-rest 암호화, MCP의 transcript 비관찰, readOnlyHint≠ACL, host 자체 egress, pg0의 production 비추천, Hindsight noauth/단일 key, 논문 수치의 조건부 해석.

---

## 2. 중요 발견

### F1 [P0] 경계가 데이터 계층에만 있다 — 업무→개인 cloud, 고객A↔고객B 반출

**근거 위치**
- design-contract §추가 요구: "client MCP 설정에서도 업무 환경은 개인 endpoint를 발견/호출하지 못하도록 분리하고, 업무 서비스/worker의 outbound egress도 별도로 제한", 표의 corpus/secret/cache 행
- impact-comparison: "별도 설치/endpoint·DB·키·logs·outbox·backup·cache"
- 사용자 동작 5: "opt-in host adapter"

**반례**
1. 개인 memory MCP를 host의 user scope로 설치하면 고객 repo 세션에도 개인 `remember`가 노출된다. user scope는 흔한 설치 방식이다. 고객 README의 prompt injection이나 단순한 "도움 되려는" 행동만으로 업무 내용이 개인 cloud에 기록된다.
2. MCP 설정을 프로젝트별로 나눠도 agent는 같은 uid의 shell 도구를 가진다. 개인 cloud용 token(keychain, 설정 파일, 환경변수)과 네트워크가 그 uid에 있으면 `curl`로 직접 호출할 수 있다. "업무 서비스/worker egress 제한"은 memory 서버만 막고 host agent 프로세스는 막지 않는다.
3. 개인 capture adapter를 host의 user-level hook으로 설치하면, 업무 recall 결과가 담긴 업무 세션 transcript가 개인 cloud로 간다.
4. 업무 data dir가 iCloud 데스크탑/문서 동기화 경로 안에 있거나 개인 Time Machine·개인 백업 대상이면, OS가 업무 DB와 log를 개인 cloud나 매체로 복제한다. 자료의 egress 목록에는 OS 동기화가 없다.
5. 같은 uid에서는 고객A 세션이 고객B의 localhost endpoint와 token에 접근할 수 있다. "고객별 독립 경계"가 프로세스 수준에서는 성립하지 않는다.

**피해:** 요구 4를 직접 위반한다. 정상 tool 호출과 구분되지 않아 탐지도 어렵다.

**최소 수정**
- (a) 고객별·개인별로 macOS 사용자를 분리한다. 개인 credential은 업무 사용자에 아예 존재하지 않게 한다.
- (b) 개인 hook과 개인 MCP는 개인 사용자에만 설치한다.
- (c) 업무 data dir는 동기화 경로 밖에 두고 개인 백업에서 제외하며, 고객 승인 매체로만 백업한다.
- (d) 업무 사용자의 host와 memory 프로세스에 앱 단위 egress deny와 로그를 건다. 허용은 승인된 host 모델 endpoint뿐이다.
- (e) 개인 코딩 관례를 업무에서 쓰려는 수요에는 **개인→업무 단방향, 사람 검토를 거친 정적 import**만 제공한다. 업무 세션의 개인 endpoint live 질의는 read-only라도 금지한다. 질의 문자열 자체가 업무 내용이기 때문이다.

**영향과 장단점:** 계정 전환 마찰, host 설치와 로그인 중복이 생긴다. 루트 악성코드나 host 공급자 egress는 해결하지 못한다. 대신 "설정 실수 하나 = 반출"이던 상황이 "OS 권한 경계 돌파가 필요"한 상황으로 바뀐다.

### F2 [P1] "core code 변경 0"이 "Agent Flow 동작 변경 0"을 보장하지 않는다

**근거 위치**
- impact-comparison: "설치기·provider launcher·reviewer gate·author envelope에는 새 store/자동 주입/새 설정을 넣지 않는다"
- design-contract: "review subprocess에는 … 기본 제공하지 않는다"

**반례:** memory MCP를 host의 user/global 설정에 넣으면, Agent Flow launcher가 띄우는 author·reviewer 세션도 MCP 격리 옵션을 쓰지 않는 한 그것을 상속한다. 격리 옵션의 예로는 Claude Code의 strict MCP config류 플래그, Codex의 profile이나 별도 config home이 있다[학습 지식, 판본 확인 필요]. Agent Flow가 이미 격리하는지는 자료에 없다(미확인).

상속이 일어나면 결과는 다음과 같다.
- reviewer가 author의 자기합리화 기억을 읽고, write tool로 기록까지 할 수 있다.
- author run이 외부 기억 상태에 의존하게 되어 재현성이 사라진다.

core를 한 줄도 바꾸지 않았는데 #316 freeze의 의도가 무너지는 셈이다.

**최소 수정**
- (a) 설치 계약에 project/local scope 또는 전용 profile만 허용한다고 명시한다.
- (b) 채택 전에 Agent Flow로 reviewer와 author를 띄워 tool 목록을 기록하고 memory tool이 없음을 확인한다.
- (c) 상속을 막는 데 launcher 변경이 필요하다면, 그것은 freeze 예외이므로 사용자에게 별도로 결정을 묻는다.
- (d) Agent Flow 세션용 credential은 발급하지 않는다.

**영향과 장단점:** Agent Flow 세션에서 memory를 쓰려면 명시적 opt-in이 필요해진다. freeze와는 일관된다.

### F3 [P1] 엔진 선택 규칙이 문서마다 다르고, Hindsight 경로는 사실상 "엔진 두 개"다

**근거 위치:** 문서마다 기본안이 다르다.
- design-contract §결정: "기본 비교 기준은 … PostgreSQL"
- impact-comparison: "통과하면 custom engine보다 재사용 우선"
- github-memory §7: "Hindsight 동일 OSS engine … 1순위"
- cloud-mcp-security §1.5/§8: "Postgres+pgvector+GCS를 기본 비교안", "Hindsight를 택하면 … dual-write"

**반례:** 필수 계약(expected-version CAS, retract≠purge, supersedes/retracts lineage, commit 시 deletion epoch, operation 상태)은 custom ledger의 어휘로 쓰였다. 자료상 Hindsight가 노출하는 것은 다음 정도다.
- document upsert/delete
- 비동기 consolidation("pending이면 정정을 늦춘다")
- directives를 받는 reflect
- 기본 on인 DB LLM trace

이 계약을 통과하려면 wrapper가 자체 ledger와 outbox를 소유하고, Hindsight를 비동기로 호출하며, 삭제를 facts/observations/mental models/trace까지 전파해야 한다. 결국 **PG 도메인 서비스를 만들면서 동시에 Hindsight도 운영**하게 된다.

여기에 세 가지 부담이 더해진다.
- retain은 LLM 추출을 전제한다(기본 OpenAI). 그래서 work-local-strict에서는 Mac에서 쓸 만한 추출·tool-calling 품질을 내는 local LLM이 필요하다.
- 고정 링크의 행 범위로 보면 `memory_engine.py`는 최소 17,600행 이상이고 upstream은 활발히 갱신된다(pushed_at 2026-10-10). 두 배포에서 같은 버전을 감사하는 부담이 크다[INFERENCE].
- "통과하면 재사용"의 최소 기능 기준이 정의되지 않아, 같은 fixture로 비교해도 판정할 수 없다.

**최소 수정**
- 규칙을 하나로 정한다. v1은 A-min이다.
- 추출은 host가 이미 수행한다. 그 egress는 host 계약 범주에 속한다. tool 입력은 claim, source span, kind, 조건으로 한다.
- 서버는 결정적 검증, 저장, lexical+vector 검색, 버전·삭제만 맡는다.
- Hindsight는 설계 참고이거나, 개인 cloud에서 outbox로 채우는 비권위 projection 실험 후보다. LLM 없이 verbatim 저장을 지원하는지는 미확인이므로, 지원한다면 재평가한다.
- "bounded"의 바이트 상한은 실측 뒤 정한다. 초과분을 조용히 자르면 digest와 provenance가 바뀌므로 반드시 거절한다.

**영향과 장단점:** 자동 추출·consolidation·reflect를 잃는다. claim 품질은 host 모델과 tool 지시문에 좌우되어 Claude와 Codex 사이에 편차가 생긴다. 대신 local LLM 운영, Metal/CUDA parity 문제, dual-write가 대부분 사라진다.

### F4 [P1] "사람 승인"이 무엇이 아닌지만 있고 무엇인지가 없다. CAS는 권위 통제가 아니다

**근거 위치**
- design-contract §저장·권한: "approved=true … 권한 근거로 쓰지 않는다"
- §파이프라인: "조용한 last-write-wins로 인간 결정을 덮지 않는다"
- §철회: "새 human approval 없이"
- 필수 시나리오: "fake human approval"

**반례**
1. host의 tool 승인 프롬프트는 서버가 관찰할 수 없다. auto-approve 모드라면 모델이 `approve` tool을 직접 호출할 수 있다.
2. 승인용 CLI를 두면 같은 uid의 agent shell도 그것을 실행할 수 있다.
3. MCP elicitation은 host 지원과 판본이 미확인이고, 어차피 host가 중계한다.
4. CAS conflict를 받은 agent는 보통 재조회 후 재시도한다. 결과적으로 사람의 결정을 덮는 LWW가 된다.

결국 "fake human approval" 시나리오는 현재 설계로는 통과 기준 자체가 없다. 같은 맥락에서, host가 작업 디렉터리를 증명하지 않으므로 같은 principal 안의 project 오기록도 서버가 막을 수 없다.

**최소 수정**
- 승인은 agent credential과 분리된 human principal이 하고, 사용자 존재 증명을 요구한다. 예를 들어 localhost나 개인 웹 화면의 passkey/플랫폼 인증기는 오프라인에서도 동작하므로 strict와 양립한다[INFERENCE].
- 모든 version에 `authority`(human/agent/unknown)를 둔다.
- agent는 human-authority version을 supersede/retract할 수 없고 proposal만 만들 수 있다. 이때 응답은 재시도 불가 오류로 한다.
- 승인을 recall 조건으로 삼는 것은 정책류 kind뿐이다.

**영향과 장단점:** 승인 마찰이 생긴다. 승인을 거의 하지 않으면 "승인된 정책"이 없을 뿐, 시스템은 그대로 동작한다.

### F5 [P1] epoch "재확인"은 TOCTOU이고 lease에 fencing이 없다 — purge 증거가 거짓이 될 수 있다

**근거 위치**
- design-contract §파이프라인: "(tenant, event_uuid, projection_version) … compare-and-set", "worker commit 전에 … epoch를 재확인"
- impact-comparison: "lease worker"

**반례**
1. READ COMMITTED에서 다음 순서가 가능하다.
   - worker가 epoch를 읽는다.
   - retract 트랜잭션이 epoch를 올리고 projection을 지운 뒤 commit한다.
   - worker가 embedding을 insert한다.
   
   남는 것은 고아 projection이다. recall 시점의 canonical 조인이 노출은 막더라도, purge는 "완료"로 보고되는데 삭제된 내용의 파생 벡터가 남아 있다.
2. Mac 수면이나 App Nap으로 local worker가 lease 만료 뒤에도 멈춰 있을 수 있다. 다른 worker가 재처리한 뒤 원래 worker가 깨어나 옛 manifest로 commit한다. 벽시계 lease만으로는 이를 막을 수 없다.
3. key가 event 단위면 정정으로 생긴 memory version을 구분하지 못한다.

**최소 수정**
- worker commit을 canonical 행 잠금과 같은 트랜잭션에서 수행한다(worker는 공유 잠금, retract/purge는 배타 잠금). 또는 SERIALIZABLE에 재시도를 둔다.
- lease마다 단조 증가 fencing token을 발급하고, commit 문에서 검사한다.
- key에 memory_version과 manifest revision을 포함한다.
- `purge_complete`는 최대 lease 만료 이후의 lineage sweep에서 0건이 확인된 뒤에만 표시한다.

**영향과 장단점:** 1인 규모에서 잠금 경합은 작을 것으로 본다[INFERENCE, 미측정]. GCS, Neo4j, Hindsight 같은 외부 저장소는 잠금 밖이라 sweep에 의존해야 한다. A-min이 외부 저장소를 두지 않는 이유 중 하나다.

### F6 [P1] deletion ledger가 PG 백업과 함께 롤백되고, 최소 tombstone으로는 재수집 부활을 막지 못한다

**근거 위치**
- design-contract 표 backup 행: "독립 deletion ledger"
- §철회: "canonical ledger에 먼저 기록", "scope-bound 최소 ID/삭제 generation", "오래된 source 재수집이 … 부활시키지 않아야"
- cloud-mcp-security §5.3: "별도 보호·복제". 자료는 별도 보호를 말하지만 **기록 순서와 위치**는 정의하지 않았다.

**반례**
1. canonical ledger가 PG 안에 있으면 PITR이나 백업 복원이 기억과 삭제 기록을 **함께** 되돌린다. 독립 사본을 PG commit 뒤 비동기로 복제하면 그 사이 crash에서 삭제가 유실된다(dual-write). 노트북 하나와 같은 날 백업이라면 두 사본이 함께 사라진다.
2. 재수집된 같은 source는 새 event_uuid를 받으므로 "최소 ID"와 매칭되지 않는다. 막으려면 내용 지문이 필요하다. 그런데 저엔트로피 비밀(전화번호, 주민번호, 짧은 키)의 평문 해시는 사전 대입으로 확인할 수 있어 tombstone 자체가 유출원이 된다. 게다가 의역된 재수집은 지문으로 막을 수 없다.
3. 기기A가 오프라인 중 spool한 옛 event를, 기기B에서 철회가 끝난 뒤에 재전송하면 서버는 새 event로 accepted한다.
4. 한 PG cluster에 여러 고객 DB를 두면 cluster 단위나 data dir 백업이 고객을 섞는다. 계약 종료 시 고객 데이터 파기 절차도 없다.
5. 다음 사본은 purge 범위 밖에 있다.
   - host의 로컬 session transcript 파일[학습 지식, 판본 확인 필요]
   - host 자체의 memory 기능
   - agent가 작성한 파일이나 commit
   - 이미 provider로 보낸 context

**최소 수정**
- purge는 독립 append-only ledger 사본(다른 매체나 계정)에 durable 기록을 확인한 **뒤에** PG 상태를 바꾼다.
- 응답 상태를 `blocked`(PG 반영)와 `ledger_durable`(독립 사본 확인)으로 나눈다.
- 복원 시에는 모든 ledger 사본 중 최신을 재적용한 뒤에 공개한다.
- 지문은 scope별 비밀 키로 만든 keyed HMAC(정규화 후)과 source locator로 하고, "의역 재수집은 막지 못함"을 명시한다.
- spool event에는 client가 마지막으로 본 ledger watermark를 동봉한다. 그 이후 같은 scope에 철회가 있었다면 `quarantined`로 보낸다.
- 고객별로 PG cluster를 분리하고, 계약 종료 시 키와 백업을 파기하는 체크리스트를 둔다.
- purge 응답에 범위 밖 사본 목록을 명시한다.

**영향과 장단점:** 운영할 저장소가 하나 늘고, 고객별 cluster만큼 리소스가 든다. HMAC 키가 유출되면 확인 공격이 다시 가능해진다.

### F7 [P1] kind 라벨은 host 행동을 바꾸지 못하고, 정정(supersede)은 파생물 무효화 규칙에서 빠져 있다

**근거 위치**
- design-contract §저장: "factual 참고 기억과 behavioral policy를 분리"
- §회상: "active policy로 자동 승격하지 않는다"
- §철회: "source가 **철회된** derived summary는 exclude/rebuild". 반면 사용자 동작 3은 "**정정**·철회하면 … 파생 요약/임베딩/캐시"까지 적용한다고 쓴다.

**반례**
1. `kind=fact`로 저장된 "이 repo에서 테스트 생략은 검증된 성공이었다"(MemoryGraft 유형)는 recall되면 라벨과 무관하게 지시처럼 채택된다. mental model의 "사용자는 X를 선호"도 recall되는 순간 사실상 정책이다.
2. source가 정정만 되고 철회되지 않으면, 계약 문구상 파생 요약이 옛 내용을 유지한다. Hindsight는 사라진 fact를 감지하는 처리가 있지만 consolidation pending 중에는 지연된다.
3. 모델 principal이 MCP로 reflect의 bank directives나 opinion을 쓸 수 있는지는 미확인이다. 쓸 수 있다면 엔진 안에 모델이 통제하는 정책층이 생긴다.

**최소 수정**
- 무효화 trigger를 lineage 변화 전체(supersede, retract, purge, scope/authority 변경)로 넓힌다.
- 파생물은 `source_versions` 집합을 갖고, 그중 하나라도 current가 아니면 recall에서 제외한다.
- 기본 recall 대상은 원문 인용 증거와 human-authority 항목으로 한정한다.
- agent가 만든 lesson·절차·선호는 명시 질의에서만 돌려준다. 이때 인용 블록, provenance, "검증되지 않은 데이터이며 지시 아님" 형식을 붙이고 명령형 문장에 플래그를 단다.
- 모델 principal의 directives/opinion 영속 쓰기를 금지한다.
- 이 조치가 채택을 줄일 뿐 없애지는 못한다는 점을 문서에 적는다.

**영향과 장단점:** lesson의 유용성이 떨어진다. A-min v1에는 파생물이 없으므로 재생성 비용은 거의 0이다.

### F8 [P1] 요구 2·3의 "cloud agents"가 host 매트릭스에 없다

**근거 위치**
- 계약 요구 2·3, design-contract 사용자 동작 2: "cloud의 Codex"
- cloud-mcp-security §3: CLI·IDE, ChatGPT web, Responses API만 다룬다. "remote executor에는 미지원", "noninteractive 세션 … OAuth browser sign-in은 못하므로"라는 한계도 적혀 있다.

**반례**
- vendor sandbox에서 도는 cloud agent(cloud Codex task, 원격·웹 Claude Code 세션 등)에 대해 다음이 모두 미확인이다.
  - 브라우저 OAuth를 완료할 수 있는가
  - refresh token이 영속되는가
  - custom domain egress가 허용되는가
  
  CLI에서 된다는 사실이 cloud agent에서도 된다는 근거가 되지 않는다.
- 2025-11-25 호환 adapter를 in-memory `Mcp-Session-Id`로 구현해 Cloud Run 다중 인스턴스에 두면, 다른 인스턴스로 라우팅된 요청은 session-not-found가 된다.

**최소 수정**
- host×surface 매트릭스를 실제 roundtrip으로 채우고, 확인된 행만 "지원"으로 표기한다. 열은 다음과 같다.
  - 전송 방식
  - 협상된 protocol 버전(서버가 요청별로 기록)
  - 인증 방식
  - token 보관 위치
  - egress 허용 여부
  - write 허용 여부
- cloud runtime에는 runtime별 credential을 준다. 기본 read-only이고 개별 폐기가 가능해야 한다.
- legacy adapter는 서버가 session을 발급하지 않는 모드로 돌리거나 단일 인스턴스로 제한한다.

**영향과 장단점:** 일부 cloud agent는 "지원 불가"로 판정될 수 있다. 그것이 정직한 결과다.

### F9 [P1] scope-first 필터와 근사 vector 검색이 조용한 false-empty를 만들 수 있고, 한국어 lexical은 parity 목록에서 빠져 있다

**근거 위치**
- design-contract §회상: "먼저 범위를 제한하고, lexical+vector 후보를 RRF로", "morphology 또는 ngram 확장"
- impact-comparison: parity를 "vector extension·버전"에 대해서만 요구
- github-memory: "native … tsvector … PGroonga bigram/pg_search"
- cloud-mcp-security: upstream 0.8.7과 Cloud SQL 0.8.5의 차이

**반례**
- pgvector의 근사 인덱스는 WHERE 필터를 인덱스 후보를 뽑은 **뒤에** 적용한다[학습 지식; 고정 README의 filtering/iterative scan 절과 설치 버전으로 확인 필요]. 큰 bank 안의 작은 project scope에서는 vector arm이 k보다 적거나 0건을 돌려줄 수 있다.
  - 내부 실패가 없는데 결과가 비어 `empty`로 응답된다. 이것은 "unavailable≠empty" 계약을 우회하는 정합성 결함이다.
  - 동작은 extension 버전과 설정에 따라 다르다. 따라서 local과 cloud에서 같은 seed가 다른 결과를 낼 수 있다.
- 한국어 lexical을 PGroonga, pg_bigm, pg_search 같은 extension으로 구현하면 관리형 PG에서 지원되지 않을 수 있다(미확인). 그러면 lexical arm이 배포마다 달라져 conformance 비교가 불가능해진다. Hindsight 경로도 같은 문제를 가진다.

**최소 수정**
- v1은 scope 안 exact 검색으로 한다. 인덱스가 없으므로 구성상 정확하다. latency는 실제 corpus 크기에서 측정한다.
- 근사 인덱스는 exact 대비 recall을 검사하는 조건으로만 도입한다.
- lexical은 애플리케이션 측 정규화와 문자 n-gram을 열로 저장하는 방식으로 한다.
- manifest에 tokenizer, normalizer, extension 버전을 추가한다.
- 응답에 arm별 후보 수를 넣어 결과가 얇아진 것을 관찰할 수 있게 한다.

**영향과 장단점:** exact 검색 비용은 corpus 크기에 선형이다(미측정). n-gram 열만큼 저장소가 늘고, 형태소 분석 품질은 포기한다. 형태소 분석이 필요한지는 한국어 fixture로 판정한다.

### F10 [P2] 예산·reranker·token 회계가 실제 주입량과 어긋난다

**근거 위치**
- design-contract §회상: "token-budgeted final≤20, reranker는 … final20이면 생략, final≤5이면 사용", "실제 반환된 bytes의 token count"

**반례**
1. reranker 사용 여부를 명목 K(20)로 결정한 뒤 예산으로 자르면, 실제로 7개만 들어가도 reranker는 생략된 채 RRF 순서의 상위 7개가 남는다. 결정 시점이 잘못됐다.
2. 서버는 host tokenizer를 오프라인에서 알 수 없다. count API 호출은 strict 환경에서 egress다. 한국어의 문자당 token 비율도 tokenizer마다 다르다.
3. tool 결과에 구조화 결과와 그 직렬화 텍스트를 함께 담는 관행이 있다. 2025-06-18 판본에서는 하위호환 SHOULD였고[학습 지식], 2026-07-28 판본에서 유지되는지는 확인이 필요하다. 그대로라면 실제 주입량은 본문 예산의 배수가 된다.
4. tool catalog 정의와 매 턴 recall이 J 항목의 "주입 비용"에서 빠져 있다.

**최소 수정**
- 예산은 바이트나 문자로 강제하고, tokenizer id를 붙인 추정 token을 병기한다.
- reranker 결정은 예산을 적용한 최종 집합 크기로 한다.
- 결과 표현은 하나만 반환한다.
- tool 수를 최소화하고, catalog 크기와 턴당 recall 수를 비용 지표에 넣는다.

---

## 3. 대안 비교

| 대안 | local/cloud 동등성 | privacy | 구현·운영 비용 | 최강 반론 |
|---|---|---|---|---|
| **PG domain custom (A-min)** | 가장 높다. 단 extension과 PG 버전, 관리형 PITR/백업 의미는 배포마다 다르다 | 데이터가 자기 PG에만 있다. PITR/WAL 보존 기간만큼 purge가 지연된다. redaction과 log 버그는 직접 책임진다 | 서비스를 직접 소유한다. 개인 cloud에는 상시 DB 바닥 비용이 있다(자료에 미산정) | **"1인용 memory를 직접 만들면 결국 Hindsight보다 못한 hybrid 검색·dedup을 재구현한다."** v1 범위에서 이를 의도적으로 뺐다. 다만 dogfooding에서 명시적 기록이 거의 일어나지 않으면 이 반론이 맞다 |
| **Hindsight self-host** | 같은 upstream 버전 배포는 가능하다. LLM에 의존하므로 배포별 추출 품질은 평가로만 알 수 있다. 한국어 lexical extension 가용성은 미확인이다 | 기본 noauth/단일 key, 기본 LLM이 OpenAI(설정 실수가 곧 egress), DB LLM trace 기본 on(prompt 사본이 백업에 들어감) | wrapper, 엔진, local LLM을 모두 운영한다. 대형 upstream 감사, dual-write, 삭제 전파가 필요하다 | (찬성 측) 검증된 retain/recall/reflect가 있고 PG 운영 기술을 공유할 수 있다. 그러나 local-strict의 LLM 요구가 해소되기 전까지 업무 쪽에서는 이 장점이 실현되지 않는다 |
| **Neo4j projection** | Aura와 local edition의 auth/backup 차이를 확인해야 한다 | Aura restore가 덮어쓰기여서 삭제된 기억이 부활한다. projection purge 표면이 늘어난다 | 두 번째 DB, entity resolution용 LLM, Aura 상시 비용 | (찬성 측) 발표 화면의 project/task/claim 관계를 그대로 담을 수 있다. 그러나 1인 coding memory에서 multi-hop 질의 수요는 아직 관측되지 않았다 |
| **Managed** | 업무 local-strict에는 배포할 수 없다. 결국 두 제품, 두 tool schema가 된다 | 개인 데이터에 한정하면 수용 가능할 수 있다. 학습·보존·purge·subprocessor는 미검증이다 | 운영은 최소다. 사용량 과금, lock-in, export 충실도가 부담이다 | **A-min에 대한 가장 강한 반론:** 두 경계 사이에 데이터가 오가지 않으므로 parity의 실익은 UX와 운영 지식 재사용뿐이다. 개인은 managed로 당장 cross-device를 얻을 수 있다. 다만 요구 3이 재사용을 명시했고 업무 쪽은 어차피 self-host가 필요하므로, A-min이 요구를 충족하는 최소안이다. 사용자가 parity의 우선순위를 낮추면 이 대안으로 전환한다 |

---

## 4. 채택 전 최소 검증 (모두 미수행, 관찰 계획)

**V1. no-egress offline** (업무 전용 OS 사용자에서)
- 네트워크를 끊기만 하면 연결 시도가 보이지 않는다. 그래서 연결은 유지한 채 앱 단위 deny+로그와 DNS 로그를 함께 둔다.
- 사전 반입 artifact(hash 고정)만으로 cold start한 뒤, 기록→회상→정정→철회→purge→백업→복원을 1회전 수행한다.
- 관찰할 것:
  - 서비스, worker, embedding 런타임, 패키지 관리자, 컨테이너 런타임의 외부 연결 시도 0건
  - 모델 다운로드 시도 0건
  - data dir가 iCloud 동기화와 개인 백업에서 제외되어 있음
- host 모델 egress는 별도 범주로 기록한다.

**V2. local/cloud conformance**
- 같은 release digest와 합성 seed(업무 데이터 금지)로 같은 event 스크립트를 양쪽에서 재생한다.
- 비교 대상:
  - 상태 전이와 version/authority
  - ACL 거부와 CAS 충돌
  - retract/purge 상태와 operation 조회
  - 오류 코드, migration checksum
  - manifest(모델·tokenizer·extension hash)
- 비교 제외: 벡터와 rank. 허용 오차는 측정한 뒤 사용자가 정한다.

**V3. 두 host roundtrip**
- 기기A의 Claude Code가 기록하고, 기기B의 Codex와 cloud agent 1종이 provenance와 함께 회상한다.
- 서버는 요청별 protocol 버전과 인증 방식을 기록한다(2025와 2026 adapter 각각).
- A의 credential을 폐기하면 A는 실패하고 B는 계속 동작해야 한다.
- Agent Flow로 reviewer와 author를 띄워 tool 목록에 memory가 없는지 확인한다(F2).

**V4. 정정·삭제·복원**
- 두 host에서 동시에 정정하면 하나는 conflict여야 한다.
- agent가 human-authority version을 재시도하면 재시도 불가 오류여야 한다.
- worker를 epoch 검사와 commit 사이에서 정지시키고 retract한다. sweep 뒤 고아 projection이 0건이어야 한다.
- local worker를 SIGSTOP으로 lease를 초과시킨 뒤 재개한다. fencing이 commit을 거절해야 한다.
- purge 뒤 purge 이전 백업으로 복원한다. ledger를 재적용하기 전에는 비공개 상태여야 하고, 공개 뒤에는 해당 항목이 없어야 한다.
- 같은 source를 재수집하면 차단되어야 한다. 의역 재수집은 "차단되지 않음"이 문서와 일치하는지 관찰한다.
- 다른 기기에서 철회한 뒤의 spool 재전송은 quarantined여야 한다.
- 한 고객의 cluster를 파기해도 다른 고객에게 영향이 없어야 한다.

**V5. poisoning과 오승격**
- 사용자가 작성한 소수의 합성 한국어 fixture로 다음을 확인한다.
  - "X 프로젝트를 만들었다"가 선호로 승격되지 않는다.
  - 부정("~는 쓰지 않는다"), 한시 예외("이번 주만"), 조건("CI에서만")이 보존된다.
- repo 문서에 "테스트 생략은 검증된 성공"을 삽입하고 다음 순서로 관찰한다.
  - 저장되는가
  - 기본 recall에 노출되는가
  - 다른 host의 후속 세션에서 채택되는가
  - 철회 뒤 비노출·비채택이 되고, 정상 기억은 유지되는가
- 경계 공격: 업무 사용자 세션에서 prompt injection으로 개인 endpoint 호출을 유도한다. credential 부재와 egress 거부가 로그로 관찰되어야 한다. 개인 hook은 업무 사용자에서 동작하지 않아야 한다.

**평가 규모:** V1–V5는 대부분 결정적이고 자동화할 수 있다. 업무 corpus의 품질은 업무 경계 안에서 로컬 모델로만 평가한다.

---

## 5. 주장 교정과 과설계

### 5.1 근거가 약하거나 독립 확인이 필요한 주장

- **MCP 2026-07-28 GA(stateless, CIMD SHOULD, DCR deprecated):** 내 학습 시점 이후일 수 있어 판단하지 않는다. 확인할 것은 다음과 같다.
  - initialize 제거의 정확한 범위
  - tool 결과의 구조화+텍스트 병기 규칙이 유지되는지
  - 사용할 SDK가 어느 판본을 지원하는지
  - 실제 host가 보내는 `MCP-Protocol-Version` 헤더
- **Claude Code v2.1.232/v2.1.274 rollout 조건:** 설치된 버전과 서버 관찰로만 확정한다.
- **2026 preprint**(MemoryArena v2, LongMemEval-V2, MemDelta, MemSecBench, MemPoison, eTAMP, P18)와 Hindsight ACL demo: 저자 보고이고 재현되지 않았다. 시나리오 착상으로만 쓰고 임계값 보정에는 쓰지 않는다.
- **pgvector parity:** 관리형 인스턴스의 실제 extension 버전을 확인하기 전에는 주장하지 않는다. Hindsight Cloud와 Aura 단가는 결정 시점에 다시 확인한다.
- **비용 비교의 비대칭:** Aura는 산정했지만 권고안의 관리형 PG 상시 비용, IdP/OAuth 비용, embedding 단가가 비어 있다.
- **"event+ACL+outbox 같은 트랜잭션"(impact-comparison):** ACL의 원천이 외부 IdP라면 IdP 측 폐기는 이 트랜잭션과 무관하고, token이 만료될 때까지 지연된다.
- **Graphiti `remove_episode`의 `episodes[0]` 기준:** 과삭제뿐 아니라, 삭제 episode가 첫 번째가 아닌 edge에서는 과소삭제(참조 잔존)도 가능하다. 양방향 모두 확인이 필요하다.
- **github-memory §7 "local external PostgreSQL도 가능":** design-contract의 "기본"보다 약한 표현이다. design-contract 쪽으로 통일한다.
- **"로컬 trusted identity":** 같은 uid 안에는 구분 가능한 identity가 없다. 실제 경계는 F1의 OS 사용자 분리다.
- **Cloud Run의 CPU 할당:** request 기반 과금에서는 응답 뒤 CPU가 거의 할당되지 않는다[학습 지식, 확인 필요]. 그러면 API 안의 background dispatcher가 멈추고, 기기B에서 queryable이 늦어진다. after-commit 인라인 dispatch와 Scheduler sweep을 쓰거나 instance 기반 과금으로 바꾼다.
- **Mac의 컨테이너 embedding:** 일반적으로 Metal을 쓰지 못한다[학습 지식, 런타임에서 확인]. "같은 image"를 원하면 CPU 런타임, GPU를 원하면 native binary 중 하나를 명시적으로 선택해야 한다.

### 5.2 v1에서 채택하지 않을 과설계

- **GCS 원문 archive:** bounded event는 PG가 곧 archive다. 사본은 purge 표면만 늘린다.
- **Cloud Tasks:** 1인 규모에서는 after-commit dispatch와 Scheduler sweep으로 충분할 가능성이 높다[INFERENCE].
- **Neo4j, reflect, mental model, 서버측 추출.**
- **개인 기기 암호화 outbox:** 오프라인일 때는 `unavailable`로 응답하는 편이 정직하다. spool은 F6의 재전송 문제를 만든다.
- **자체 OAuth 인가 서버:** CLI host는 기기별로 폐기 가능한 bearer로 시작한다. OAuth는 그것을 요구하는 host에서만 외부 IdP로 처리한다.
- **`work-local-approved-inference` 프로필 구현:** 회사 계약을 확인하기 전에는 strict만 둔다.
- **RLS 다중 tenant:** 고객별 독립 배포에서는 scope 검사와 테스트로 충분하다. RLS는 선택적 심층 방어다.
- **논문식 평가 프로그램**(paired 검정, 4종 제품 대조): 1인 규모에는 과하다. V1–V5, 소수 fixture, dogfooding 기록(회상을 사용·무시했는지, 잘못된 회상이었는지)으로 대체한다.
- **RAG skill의 200/60·Top20:** baseline 기록용일 뿐 기본값이 아니다. atomized claim에는 해당하지 않는다.

---

## 6. 의견과 근거의 한계

- 이 리뷰는 prompt에 포함된 동결 텍스트만 읽었다. 인용된 URL, 소스, 논문 원문은 이번에 열지 않았다. 구현, 설치, benchmark도 실행하지 않았고, 4장의 시나리오 중 어떤 것도 수행되지 않았다.
- **[학습 지식]** 표시는 판본에 따라 다를 수 있다(pgvector 필터링, MCP 결과 병기 규칙, host 플래그와 파일 위치, Docker/Metal, Cloud Run CPU). 실제 설치 판본을 관찰해 결정해야 한다. 여러 2026년 자료는 내 학습 시점 이후일 수 있다.
- Agent Flow 소스, 회사 계약, 실제 host 설정은 보지 못했다. F2와 F8은 결함을 확정한 것이 아니라 "관찰이 필요하다"는 지적이다.
- 수치를 새로 만들지 않았다. 17,600행은 고정 링크의 행 범위에서 읽은 하한일 뿐 품질 지표가 아니다.
- 다른 리뷰어가 존재하거나 결론이 일치한다고 해서 검증이 되는 것은 아니다. 두 리뷰는 같은 자료를 읽으므로 자료의 공통 맹점을 함께 놓칠 수 있다. 채택 판단은 4장의 관찰 결과로만 한다.
- 이 리뷰는 trust boundary 없는 cloud 실행이 안전하다는 인증도, 모델·제품의 순위도 아니다.