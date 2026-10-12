**1. 판정: 공통 파이프라인은 조건부로 가능하다. 현재 자료는 채택 통과 증거가 아니다.**

공통화할 대상은 API, event identity, 도메인 스키마, 출처·버전, 승인·정정·철회 상태, accepted/queryable 의미와 복원 규칙이다. corpus, credential, 고객별 scope, cache·outbox·log·export·backup, 호스트 모델의 전송 경계는 분리해야 한다. 파일시스템과 GCS, 로컬 인증과 OAuth, Mac Metal/MLX와 Linux CUDA/CPU는 adapter와 운영 절차가 달라진다. 동일 코드가 동일 출력·검색 순위·비용·latency·HA를 보장하지는 않는다.

추천은 **PostgreSQL을 단일 권위 저장소로 하는 최소 도메인 서비스**다. 명시적 저장·회상·정정·철회를 먼저 완결하고, 자동 추출·reflect는 승인 전 후보를 생성하는 기능으로 제한한다. 이 선택은 SQL transaction에 event·상태·outbox를 묶기 쉽다는 **[INFERENCE]**에 근거한다. 범용 추론 엔진을 새로 만드는 권고는 아니다. Hindsight는 대체 엔진으로 평가하되, 초기 구성에 두 개의 권위 있는 기억 저장소를 병행하지 않는다.

채택 조건은 아래 P1 계약을 구체화하고 실제 검증하는 것이다. 외부 전송 금지 업무에서는 메모리 서비스뿐 아니라 호스트 모델·embedding·reranker·reflect·URL/OCR 처리·telemetry·backup까지 승인된 로컬/사내 경계 안에 있어야 한다. 회사 계약은 미확인이다. 승인된 사내 cloud/VPC 또는 별도 최소 export는 조건부 경로이며, 업무→개인 자동 sync는 배제한다.

로컬 토큰은 same-user 악성 프로세스 격리, DNS rebinding 방어, stdio 실행 파일의 신뢰를 대신하지 못한다. 이 한계는 자료에 이미 명시돼 있으므로 새 취약점으로 세지 않는다. Agent Flow core memory freeze도 유지한다. 독립 서비스의 필요성을 과거 host memory 판단으로 축소할 근거는 없다.

**2. 중요 발견 7개**

아래 반례는 모두 **[INFERENCE]**다. 구현 취약점이나 실제 유출을 확인했다는 뜻이 아니다. P1은 해당 반례를 허용하는 구현을 채택할 경우 발생하는 소비자 안전·정합성 문제를 뜻한다.

**R01 · P1 — 인증된 사용자와 실제 인간 승인을 구별하는 계약이 부족하다.**

- **근거 위치:** `design-contract.ko.md` 「저장·권한 계약」, `papers.ko.md` §6의 write/promotion 분리.
- **반례·피해:** agent가 Alice의 위임 토큰으로 호출한다. 서버가 `approved=true`를 무시해도, 같은 토큰으로 승인 API를 호출할 수 있으면 “인증된 Alice의 승인”으로 처리될 수 있다. 승인 화면에서 확인한 버전과 실제 승격 버전이 달라지는 경쟁도 남는다.
- **최소 수정:** agent credential에는 기록·제안 권한만 부여한다. 인간 승인 경로는 별도 capability로 구분하고, 승인 증거를 정확한 content digest·revision·scope·조건·행위에 결합한다. 내용이나 범위가 바뀌면 재승인한다. export 승인은 수신자·목적에도 결합한다.
- **영향·장단점:** local/cloud 공통 권한 계약이다. 자동화는 줄지만 agent 추론이 인간 권위로 세탁되는 경로를 차단한다.

**R02 · P1 — commit 전 epoch 재확인은 원자적 경쟁 제어까지 규정하지 않는다.**

- **근거 위치:** `design-contract.ko.md` 「파이프라인·장애 계약」, `cloud-mcp-security.ko.md` §4.2 C–D.
- **반례·피해:** worker가 epoch를 확인한 직후 사용자가 철회하고, worker가 이전 결과를 commit한다. 또는 lease가 만료된 worker가 새 worker보다 늦게 결과를 게시한다. `(event_uuid, projection_version)` unique key는 서로 다른 정정 event나 여러 source로 만든 summary의 순서를 해결하지 못한다.
- **최소 수정:** 철회·정정·게시가 같은 guard row의 잠금 또는 CAS로 직렬화되도록 한다. 게시 조건에는 현재 source revision, deletion generation, 필요한 권한 상태와 lease fencing token을 포함한다. 외부 projection은 최신성 검증을 마친 뒤 조회 대상으로 공개한다.
- **영향·장단점:** worker·정정·삭제·재색인 전체에 적용된다. 경합과 재시도는 늘지만 늦은 worker가 인간 결정을 되돌리지 못한다. 이미 발생한 모델 호출 비용은 이 transaction으로 취소되지 않는다.

**R03 · P1 — queryable과 partial의 판정 단위가 불명확하다.**

- **근거 위치:** `design-contract.ko.md` 「파이프라인·장애 계약」 및 「동일성 검증」, `cloud-mcp-security.ko.md` §4.2 A.
- **반례·피해:** 한 event의 일부 chunk만 처리되거나 embedding은 실패하고 lexical index만 완성된다. 재색인 중 구·신 embedding generation이 섞일 수도 있다. 어느 시점에 queryable인지 정의하지 않으면 local/cloud가 다른 상태를 반환하거나, 미처리 근거가 있는 상태에서 `empty`를 완전한 검색 결과처럼 전달한다.
- **최소 수정:** manifest에 필수·선택 projection을 명시하고, event별 완료 상태와 조회 가능한 generation을 정의한다. 응답에는 검색 범위와 처리 watermark를 제공한다. 알려진 처리 공백은 `partial` 또는 명시적 coverage 한계로 드러낸다. 새 generation의 공개 전환도 정의한다.
- **영향·장단점:** 상태 API·검색·모델 교체에 적용된다. 상태 관리가 늘지만 accepted/queryable 구분이 실제 소비자 의미를 갖는다.

**R04 · P1 — 최소 ID tombstone만으로 새 ID의 재수집을 막을 수 없다.**

- **근거 위치:** `design-contract.ko.md` 「철회·삭제·백업 계약」의 최소 ID/삭제 generation과 재수집 금지 요구.
- **반례·피해:** 삭제된 원문을 다른 기기가 새 event UUID나 document ID로 import한다. 이전 ID의 tombstone은 일치하지 않는다. 반대로 공개 content hash를 오래 보존하면 짧은 민감 문장을 추측하는 표적이 될 수 있다.
- **최소 수정:** stable source identity와 내용 재입력의 처리 규칙을 함께 정한다. 정확히 같은 내용의 탐지에는 scope별 keyed digest 등을 검토하되, 그것도 민감한 삭제 metadata로 취급한다. 식별 연속성을 잃은 import는 자동 승격하지 않는다. 임의 paraphrase까지 완벽히 차단한다는 약속은 하지 않는다.
- **영향·장단점:** capture·import·export·삭제 ledger에 적용된다. 재수집 방어를 강화하지만 fingerprint 보존·키 복구와 privacy 사이의 비용을 소유해야 한다.

**R05 · P1 — 독립 deletion ledger가 최신이라는 사실을 확인하는 경로가 없다.**

- **근거 위치:** `design-contract.ko.md` 「철회·삭제·백업 계약」, `cloud-mcp-security.ko.md` §5.3.
- **반례·피해:** DB는 삭제 전 snapshot으로 복원되고, 별도 ledger의 복제본도 마지막 삭제를 누락한다. 복원 시스템이 그것을 “현재 접근 가능한 최신본”으로 받아들이면 삭제 기억이 부활한다. 서명된 과거 ledger도 최신성은 증명하지 못한다.
- **최소 수정:** 삭제 응답의 어느 단계가 독립 ledger의 durable 기록을 보장하는지 정의한다. 복원 대상 밖의 신뢰 가능한 head/watermark와 대조하고, 최신성 확인이 불가능하면 공개를 거절한다. local-strict에서는 그 기준도 고객이 승인한 로컬/사내 매체에 둔다.
- **영향·장단점:** 삭제 ACK와 재해 복구에 적용된다. 복원 가용성은 낮아질 수 있다. 모든 신뢰 기준이 함께 롤백·소실되는 상황까지 해결한다고 주장해서는 안 된다.

**R06 · P2 — 최종 K에 따른 reranker 전환은 근거 없는 동작 불연속을 만든다.**

- **근거 위치:** `design-contract.ko.md` 「회상·반성 계약」의 final 20 생략, 6–19 사용 제안.
- **반례·피해:** metadata 길이나 token budget 때문에 결과 수가 20에서 19로 바뀌면 모델 호출·지연·순위 결정 방식도 바뀐다. 실제 final count를 기준으로 한다면 rerank와 budget 적용 순서도 모호하다. 이 정책이 품질을 개선한다는 관찰은 없다.
- **최소 수정:** 먼저 reranker 없는 hybrid baseline을 고정한다. reranker 사용 여부·후보 수·출력 budget은 독립 변수로 비교하고, corpus 관찰 후 정책을 정한다.
- **영향·장단점:** 검색 품질·비용·local capability에 적용된다. 비교가 단순해지지만 적합한 정책을 찾는 작은 실험이 필요하다.

**R07 · P2 — managed 비교에서 동일 embedding·추론 예산을 강제할 수 있는지 미확인이다.**

- **근거 위치:** `design-contract.ko.md` 「채택 평가」, `papers.ko.md` §7.1, `github-memory.ko.md` §3의 hosted/OSS 차이.
- **반례·피해:** managed 제품의 내부 embedding·extraction·consolidation·reader budget이 비공개인데 “동일 모델·embedding·예산 비교”로 보고한다. 결과 차이를 저장 구조의 효과로 오인하고, 보이지 않는 write·repair 비용을 누락할 수 있다.
- **최소 수정:** 통제 가능한 self-host 비교와 managed 제품 전체 비교를 나눈다. 후자는 동일 입력·후속 작업·공개된 사용 한도·외부 reader 조건을 맞추고 내부 조건은 미확인으로 남긴다. 초기에는 안전 검증과 작은 업무 fixture를 수행하고, 채택 차이가 불명확할 때 평가를 확대한다.
- **영향·장단점:** 채택 판단과 사용자 평가 부담에 적용된다. 인과적 주장은 좁아지지만 불가능한 동등성과 과도한 평가 비용을 피한다.

**3. 대안 비교**

PG 기준안과 Hindsight 재사용 우선 후보는 논리적으로 양립한다. 다만 실제 구현에서는 **수락·정정·삭제의 권위를 누가 갖는지 하나로 확정**해야 한다. 별도 ledger와 Hindsight API를 함께 쓰면 전달은 outbox로 처리할 수 있어도, 두 저장소의 정정·삭제 의미까지 자동으로 같아지지는 않는다.

| 대안 | 동등성·privacy·비용에 대한 최강 반론 | 수용 조건 |
|---|---|---|
| **PG domain custom** | 같은 SQL schema는 기억의 의미적 정확성을 보장하지 않는다. 추출·lineage·승격·삭제·검색 정책을 직접 소유하므로 작은 API의 외형보다 구현·운영 책임이 크다. GCS와 모델 호출은 여전히 transaction 밖이다. | 명시적 기억 기능으로 시작하고 단일 권위 ledger를 유지한다. 자동 추론 엔진 전체를 재구현하지 않는다. |
| **Hindsight self-host** | 같은 engine version은 원하는 승인/CAS/삭제 계약의 동등성을 보장하지 않는다. wrapper가 이를 보충하다 엔진 상당 부분을 다시 소유할 수 있다. pg0, shared key, 기본 외부 LLM 문제는 자료가 이미 지적했다. | external PostgreSQL, 승인된 inference, 실제 bank ACL을 사용한다. native API 우회 경로를 닫고, 고정 판본의 mutation·정정·삭제 계약을 검증한다. 통과하면 custom 추론 구현보다 재사용 가치가 클 수 있다. |
| **Neo4j projection** | PG ledger와 graph를 운영하면 두 DB의 migration·재구축·지연을 소유한다. entity resolution과 temporal invalidation에도 추정이 들어간다. Aura/local edition의 운영 기능도 같지 않다. | 실제 multi-hop/time 질의의 개선이 관측돼야 한다. graph 결과도 canonical 상태와 source lineage를 검증하고, 재생 가능한 projection으로 둔다. |
| **Managed** | 같은 MCP 도구 이름은 같은 내부 engine·privacy·purge·export를 뜻하지 않는다. strict local과 동일 engine 요구를 충족하지 못하면 제품 이원화가 된다. 운영 감소 대신 vendor·plan·subprocessor·retention 의존성이 커진다. | 개인 데이터에 한해 계약을 확인한다. acceptance/indexing, 정확한 삭제 대상, backup 잔존, export fidelity와 전체 비용을 검증한다. |

**4. 채택 전 최소 검증**

모두 **수행할 시나리오**다. 문서 리뷰로 통과 판정하지 않는다. 업무 원문 대신 synthetic/public fixture로 시작할 수 있다.

| 시나리오 | 실제로 관찰할 내용 |
|---|---|
| **No-egress offline** | 승인된 artifacts만으로 cold start·retain·recall·정정·철회·restore를 수행한다. 호스트 모델부터 telemetry·URL/OCR·backup까지 전송 및 실패 시도 경로를 관찰한다. 모델 부재·provider 실패에도 외부 fallback이 없고 명시적 상태를 반환해야 한다. |
| **Local/cloud conformance** | 같은 event replay와 결정적 inference fixture로 ID·scope·version·상태·인용·충돌·철회 결과를 비교한다. duplicate/out-of-order, lease 만료, commit 후 ACK 유실을 주입한다. 큰 artifact의 upload 성공/DB 실패와 orphan 정리도 관찰한다. 하드웨어별 의미 품질은 별도 평가한다. |
| **권한·환경 경계** | 고객/개인 endpoint·credential·outbox를 잘못 조합한다. 다른 bank/UUID의 get/search/list/update/delete/import/export/raw/mental-model 접근을 시도한다. reviewer 직접 write 호출, RLS 예외·pool context 누수, Origin/DNS rebinding, stdio credential 노출 경계를 확인한다. |
| **두 host roundtrip** | Claude Code의 기록이 queryable이 된 뒤 다른 기기의 Codex가 정확한 출처·revision·조건을 받는지, 역방향 정정도 작동하는지 확인한다. 실제 설치 버전·protocol·OAuth·refresh/revoke·비대화형 인증을 기록한다. 도구 반환과 실제 모델 입력·사용은 별도로 관찰한다. |
| **Correction/delete/restore** | epoch 확인과 commit 사이에 철회하고, 두 인간 정정을 같은 expected version으로 경쟁시킨다. cache·summary·embedding·outbox·export·backup 잔존을 조사한다. 과거 DB/ledger 복원, 새 UUID 재수집, 재색인 후에도 삭제 자료가 조회되지 않아야 한다. 최신 ledger 확인 실패 시 공개를 거절해야 한다. |
| **Poisoning·false promotion** | 한국어 부정·일시 예외, “프로젝트 X 구현→항상 X 선호”, 가짜 승인, “테스트 생략이 검증된 성공”을 넣는다. 새 victim 작업에서 persistence→recall→adoption→행동을 구분한다. 복구 후 변형 trigger·새 host에서도 확인하고 정상 기억 보존을 함께 판정한다. reflect 전후의 영속 mutation도 조사한다. |
| **검색·전체 비용** | 한국어 근거, code identifier, 조건·부정·as-of 질의를 사용한다. chunk·K·reranker별 evidence recall과 실제 반환/주입 metadata 포함 token을 측정한다. write·consolidate·read·retry·reindex·repair·human review·운영 시간을 포함한다. |

**5. 주장 교정과 제외할 과설계**

- **프로토콜:** 동결 자료가 보고한 `2026-07-28` 설명을 작업 가정으로 사용한다. 본 리뷰에서 최신 stable을 독립 확인하지 않았다. 채택 시 스펙 판본·SDK 구현·실제 host 요청을 대조해야 한다. 학습된 2025 지식으로 덮어쓰거나 remote 지원 문서만으로 최신 협상을 확정해서는 안 된다. plan·mobile·capture 지원도 별도 항목이다.
- **논문:** 자료에 기록된 Hindsight v1의 budget placeholder와 본문/표 불일치는 재현 근거를 약화한다. Mem0의 상대 개선 주장은 full-context 우위를 뜻하지 않으며, MemoryGraft의 poisoned retrieval 비율은 행동 ASR가 아니다. QA 성적을 coding 행동 개선으로 옮길 수 없다. LoCoMo 판본·backbone·judge·budget이 다른 결과의 서열화도 배제한다. [Hindsight v1](https://arxiv.org/html/2512.12818v1), [Mem0 v1](https://arxiv.org/html/2504.19413v1), [MemoryGraft v1](https://arxiv.org/html/2512.16962v1)
- **기능 의미:** 논문 판본의 reflect 설명과 고정 SHA 구현의 실제 mutation을 대조해야 한다. facts·opinions·mental models·directives·refresh별 권한과 변경 범위를 확인한다. provenance와 승인 이력은 의미적 진실을 보장하지 않는다.
- **제품·배포:** repo SHA는 hosted runtime, 실제 설치 image, dependency와 model artifact를 고정하지 않는다. pgvector managed 지원 버전, renamed/archive 제품, local binary의 auth/release 불일치도 실제 배포 기준으로 확인한다. Hindsight의 native PostgreSQL keyword 경로를 true BM25라고 부르는 주장도 자료의 구분을 유지해야 한다.
- **가격:** 제시 단가는 동결 조사 시점의 인용값이다. 현재 가격이나 월 견적을 본 리뷰가 확인한 것은 아니다. 선택 SKU·region·plan과 실제 사용량, 재시도·재색인·삭제/복구·인간 운영 비용을 확인해야 한다.

초기에는 graph 필수화, 상시 reflect·자동 mental-model refresh, 범용 storage plugin, multi-region/복잡한 조직 공유, 전체 공개 benchmark 재현을 채택하지 않는다. WORM 기본 적용과 특수 암호화 검색도 요구·근거가 없다. 반면 event identity, 서버 ACL, 승인 경계, lineage, 정정 CAS, 삭제 generation, 복원 차단은 초기부터 필요한 계약이다.

**6. 의견과 근거의 한계**

이 리뷰는 prompt에 포함된 조사·설계 텍스트만 교차검토했다. URL을 직접 열거나 repository·private config를 읽지 않았고, memory 구현 실행·보안 공격·benchmark 재현도 하지 않았다. #316·이미지·영상은 제공된 판독 보고를 통해 사용했으며 원자료를 독립 확인하지 않았다.

따라서 결론은 **가능한 공통 설계와 남은 채택 조건**에 관한 것이다. trust boundary 없는 cloud 실행의 안전 인증, 제품 순위, 성능·내구성 보증이 아니다. 다른 리뷰어의 존재만으로 검증이 완료되지 않으며, 독립 리뷰의 일치도 실제 관찰을 대체하지 못한다.
