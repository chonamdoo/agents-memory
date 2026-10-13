# 클라우드 메모리 MCP: 원격 호환성·GCP 내구성·권한·삭제 조사

조사 기준: 2026-10-11. 범위는 공개 공식 스펙·호스트 문서·클라우드 문서·고정 SHA 소스이며 구현·설치·사용자 설정 변경·클라우드 생성·유료 모델 호출은 수행하지 않았다. 원래 첨부 이미지 파일을 이 조사 작업에서 직접 열지 않았으며, 아래 토폴로지 평가는 위임된 텍스트 설명을 대상으로 한다. GitHub 전수조사가 아니다.

표기: **[규범]** 스펙의 MUST/SHOULD, **[문서]** 운영 문서에 명시된 기능/한계, **[소스]** 고정 SHA 구현, **[제품 주장]** 가격·마케팅·사업자 정책, **[설계 제안/INFERENCE]** 이를 조합한 판단. 공급자의 보장과 이 프로젝트에서 실제 측정한 결과를 혼동하지 않는다.

## 1. 결론

1. **독립 클라우드 MCP를 접근면으로 하고, 단일 권위 저장소의 ingest ledger + transactional outbox를 정합성 중심으로 삼는 설계**를 권한다. Agent Flow core에 자체 메모리 store를 만들지 않고, 호스트가 소유한 대화/메모리와 명시적 외부 기억 서비스를 분리한다. Mac 수집기/outbox는 오프라인·로컬 호스트 통합용 선택 요소이지, 다른 기기가 Mac을 경유해야 하는 필수 게이트웨이가 아니다. [설계 제안; MCP 구조 S3, 트랜잭션 S16]
2. **최신 stable은 2026-07-28**이다. 공식 `/specification`이 해당 버전으로 연결되고 7월 28일 공식 GA 발표는 “officially pushing the release button”이라고 명시한다. 이 버전은 `initialize`/`initialized`, `Mcp-Session-Id`, HTTP GET stream을 제거한 stateless core다. 따라서 최신 스펙 설명에 2025의 session 모델을 그대로 넣으면 틀린다. 호스트별 실제 협상 버전은 이 조사에서 실행하지 않았다. 2025-11-25 호환 transport adapter와 2026-07-28 adapter를 명시적으로 나누고 같은 권한/메모리 도메인 서비스를 사용하도록 설계한다. [규범·공식 출시 S1–S5]
3. **서버는 MCP 연결만으로 세션 transcript 전체를 자동 관찰하지 않는다.** 호스트가 명시적으로 보낸 tool 인자·resource 요청과 승인된 입력만 얻는다. 자동 캡처는 호스트별 hook/plugin/export adapter의 별도 작업이다. “MCP 하나 설치하면 모든 Claude/Codex/ChatGPT 대화가 자동 동기화”는 근거 없는 약속이다. [규범 S3]
4. 스샷의 `GCS raw → Cloud Tasks → worker → embeddings → Neo4j`는 비동기 재처리에는 적합하지만 **GCS write와 enqueue의 dual-write 틈, forget와 WORM의 충돌, restore 후 삭제 부활, 모델이 주장하는 user/bank 권한**을 그림 자체로 해결하지 못한다. Scheduler는 누락 탐지·재조정 수단이지 원자적 commit의 대체가 아니다. [문서 S12–S15, 설계 제안]
5. **Postgres+pgvector+GCS를 기본 비교안**, **Neo4j+GCS는 관계 질의가 실제로 더 유용하다는 측정 후**, **Hindsight self-host는 완성된 memory engine을 재사용하고 운영·권한 경계를 추가하는 안**, **managed memory는 운영 부담 감소 대신 데이터 처리·삭제·수출 계약을 검토하는 안**으로 두는 것이 합리적이다. 이는 벤치마크 순위가 아니라 정합성/운영성 설계 판단이다. [S16–S22, S25–S28]

## 2. MCP 스펙·인증 근거표

| 쟁점 | 직접 확인한 근거 | 파이프라인에 미치는 영향 |
|---|---|---|
| stable 날짜 | [공식 현재 스펙](https://modelcontextprotocol.io/specification)은 `2026-07-28`로 연결. [GA 발표](https://blog.modelcontextprotocol.io/posts/2026-07-28/)는 “The 2026-07-28 Model Context Protocol specification is out”, “officially pushing the release button”을 명시. RC 검색 결과와 GA를 구별. [문서 S1–S2] | “2025-11-25가 최신”으로 고정하지 않음. |
| 2026-07-28 | [출시 변경](https://blog.modelcontextprotocol.io/posts/2026-07-28/#no-handshake-or-sessions): “retired the `initialize`/`initialized` exchange along with the `Mcp-Session-Id` header”. 요청별 버전·capabilities, 선택적 `server/discover`. [규범/공식 S2–S5] | Cloud Run round-robin에서 프로토콜 session 저장 불필요. 앱의 bank/workflow 상태까지 없어지는 것은 아님. |
| 2025-11-25 호환 | [현재 transport](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports)은 과거 handshake/session era fallback을 별도 정의. [2025 보안](https://modelcontextprotocol.io/docs/2025-11-25/tutorials/security/security_best_practices#session-hijacking)은 session hijacking을 다룸. [규범 S4, S8] | 배포된 이전 host와의 호환 endpoint/adapter를 별도로 검증. 최신 adapter에 legacy `Mcp-Session-Id`를 필수조건으로 넣지 않음. |
| Streamable HTTP | 2026에서는 단일 MCP endpoint의 POST, JSON 또는 request-scoped SSE 응답. `Accept`는 JSON/SSE 모두, `MCP-Protocol-Version`, `Mcp-Method`, 해당 요청의 `Mcp-Name` 필요. 헤더와 body mismatch 거절. `Last-Event-ID` 재개 미지원. [규범 S5] | HTTP는 SSE를 모두 없앤 것이 아님. request-scoped streaming과 장기 subscription을 일반 API/ingest와 구분. HTTP timeout/disconnect와 비즈니스 저장 성공을 별도 처리. |
| Origin·로컬 보안 | Origin 존재 시 허용 출처 검증, invalid이면 403; local HTTP는 localhost bind 권장. [규범 S5] | OAuth뿐 아니라 DNS rebinding/localhost 노출 방어. stdio shim도 실행 파일·파일 접근 범위 신뢰 검토 필요. |
| OAuth 2.1 | HTTP auth는 선택이나 구현 시 해당 스펙 준수 SHOULD, AS는 OAuth 2.1 MUST. 기반 문서는 OAuth 2.1 IETF **draft**이며 “최종 RFC 2.1”이라 하지 않는다. stdio는 이 HTTP flow 대신 환경에서 자격증명 취득 SHOULD. [규범 S6] | 외부 host와 표준 remote OAuth 인터페이스를 제공. 프로토콜 auth가 선택이라는 이유로 개인 메모리를 무인증 공개하면 안 됨. |
| PKCE | client는 PKCE MUST, 가능하면 S256 MUST, AS discovery metadata의 `code_challenge_methods_supported` 확인; 없으면 진행 거절. [규범 S7] | “OAuth 로그인 페이지 있음”만으로 호환 보장 못함. loopback callback, PKCE metadata, refresh 동작을 host별 검증. |
| resource metadata·audience | RFC9728 protected resource metadata MUST; AS RFC8414 또는 OIDC discovery 제공, client는 둘 지원. authorize/token 모두 `resource` MUST. 서버는 자신에게 발행된 token인지 MUST 검증. [규범 S6–S7] | issuer, audience/resource, expiry, signature/introspection, scope를 서버가 검증. `user_id` tool 인자로 인증하지 않음. |
| CIMD와 DCR | 2026은 CIMD SHOULD, DCR MAY이며 deprecated/과거 호환용. pre-registration도 가능. RFC9207 `iss` 검증 강화. [규범 S6; 공식 S2] | DCR만 구현해 “최신 표준 완성”으로 표현 금지. host 문서에 DCR 지원이 남아 있는 것과 현재 권장 방식 구별. |
| token passthrough | “MCP servers MUST NOT accept or transit any other tokens”; upstream API용 token은 별도 발행되어야 하며 client token passthrough 금지. [규범 S6–S7] | MCP access token을 GCS/Vertex/Neo4j에 그대로 보내지 않음. 서버 service identity로 downstream 수행; 사용자 ACL은 앱이 유지. |
| session/state 보안 | 2026 explicit handle도 인증 수단 아님. 서버측 `<verified_user>:<handle>` 귀속, 매 요청 auth. 2025 session도 secure random ID, authenticated principal binding, session만으로 auth 금지. [규범 S8] | bank ID, document ID, workflow handle, session ID를 알고 있다는 이유로 권한 부여하지 않음. |
| 전체 transcript | 구조 원칙: “Servers should not be able to read the whole conversation”, “Full conversation history stays with the host”. [문서 S3] | explicit `remember` 호출과 승인된 transcript import를 구별. sampling/MRTR input 요청도 host의 임의 전체 대화 공개 권한이 아님. |

**호환성 판단의 한계:** 공식 지원과 실제 접속을 구별한다. Claude Code는 SDK 2.0 기반 v2 runtime의 `2026-07-28` 지원을 직접 문서화한다. feature flags를 fetch하는 세션은 v2.1.232 이상, fetch하지 않는 세션의 기본 v2는 v2.1.274 이상 등 rollout 조건이 있으며 서버별 flag로 이전 protocol에 남길 수 있다. 실제 설치 버전·계정별 rollout·request trace를 측정하지 않았으므로 사용자 환경에서 `2026-07-28` 협상·OAuth 성공·stream 복구 성공은 미확인이다. Codex/ChatGPT의 remote transport 지원 문서만으로 최신 spec 협상을 단정하지 않는다. 문서의 “initialization/instructions” 표현이 남아 있다고 해당 host의 내부 버전을 역으로 단정하지도 않는다. [S9–S11]

## 3. “어디서든”의 호스트별 경계

| 호스트/접근면 | 공식 문서 확인 | 사용할 경로·확인할 경계 |
|---|---|---|
| Claude Code | remote HTTP 권장, Bearer header, stdio, OAuth 인증 관리 지원. v2 runtime은 `2026-07-28` 지원·협상을 문서화하며 미지원 서버는 v1 방식으로 연결. CIMD/DCR/pre-registration과 fixed callback port 설명도 있음. SSE deprecated, WebSocket은 OAuth 미지원. [S9] | 개인 Mac/다른 PC는 remote HTTP 직접 연결. version/feature flag 조건이 있고 실제 사용자 협상은 미검증. 오프라인 local outbox 필요 시 stdio collector/shim 선택. noninteractive 세션 자체에서 OAuth browser sign-in은 못하므로 사전 interactive 인증 필요. |
| Codex CLI/IDE/desktop | stdio와 Streamable HTTP, Bearer/OAuth, CIMD/DCR 지원. local config 공유와 project trust 경계, OAuth login 문서. 현재 공식 URL은 `learn.chatgpt.com/docs/extend/mcp?surface=cli`로 이동. [S10] | remote URL+OAuth를 공통 접근면으로. local headers helper는 local 환경용이고 remote executor에는 미지원이라는 문서 한계. static token의 수동 갱신을 표준 OAuth 대체로 오인 금지. |
| ChatGPT web custom MCP | 공식 Help 기준 Full MCP write는 Business/Enterprise/Edu beta, Pro는 read/fetch; web only, mobile 미지원. custom app은 agent mode에서 미사용, deep research는 read/fetch만. local server 직접 연결 불가; Secure MCP Tunnel 별도 경로 안내. [S11] | “모든 ChatGPT 사용자/모바일에서 동일 write 지원” 주장 불가. 계정·관리자 승인·도구 snapshot 갱신 필요. cloud에서 접근 가능한 MCP 또는 공식 tunnel이 필요. |
| OpenAI Responses API | remote Streamable HTTP 또는 HTTP/SSE, `authorization` access token, approvals/allow-list. Secure MCP Tunnel도 별도 안내. [S11a] | ChatGPT 앱 정책과 API transport 지원은 별개. API caller가 공급하는 토큰/승인 정책과 user OAuth onboarding을 따로 설계. |
| stdio→remote shim | stdio는 client가 실행하는 로컬 프로세스; HTTP auth flow는 stdio에 적용하지 않는다는 스펙. [S4, S6] | transport를 옮길 뿐 클라우드 데이터 내구성·자동 transcript 캡처·multi-tenant ACL을 제공하지 않음. refresh credential 저장·client별 설치·공급망·Mac offline/종료·프로토콜 버전 번역 부담 추가. ChatGPT cloud가 사용자의 Mac stdio를 직접 실행하지 않음. [설계 추론; S11] |

따라서 모든 기기의 source of truth는 cloud에 두되, **“cloud data 접근”과 “모든 호스트의 자동 수집”과 “모바일 동일 기능”은 세 가지 서로 다른 요구**다. 단일 사용자 초기에 Claude Code/Codex remote memory 도구를 쓰면서 명시적 저장을 시작할 수 있지만, ChatGPT capture나 write 범위를 거기에 맞춰 축소했다고 주장하지 않는다. 미지원 host 기능은 별도 capture/export adapter 또는 사용자 승인 import 경로가 필요하다는 범위로 남긴다.

## 4. 스샷 토폴로지 평가와 수정 제안

대상: `Mac local MCP + outbox → Cloud Run API → GCS raw immutable → Cloud Tasks → Cloud Run worker → Vertex embedding → Neo4j Aura`, `Scheduler reconcile`, `Mac encrypted backup → 별도 project`.

### 4.1 유지할 장점

- **GCS 원문과 파생 index 분리**: 원문 재처리, embedding model 교체, graph/schema 교체 가능. GCS는 object write/read/list/delete strong consistency와 단일 object atomicity를 제공한다. 단, 여러 객체 batch나 다른 서비스와의 write까지 atomic이라는 뜻은 아니다. [문서 S12]
- **Cloud Tasks 비동기 처리**: worker 과부하·외부 model rate를 제한하고 API 응답을 embedding 완료와 분리할 수 있다. private Cloud Run target에 Tasks service account의 OIDC ID token과 `run.invoker`를 쓰는 공식 패턴이 있다. [문서 S13–S14]
- **raw와 processed 상태 재조정**: Scheduler/worker가 원문·ledger·projection 상태를 비교해 누락을 찾는 것은 유용하다. 다만 어떤 저장소가 권위인지 먼저 정해야 한다. [설계 제안]
- **독립 암호화 백업**: 별도 project/IAM/키 경계는 동일 서비스 credential 손상의 피해를 줄일 가능성이 있다. 같은 소유자/조직 관리자/빌링 정지 권한까지 공유하면 완전 독립 재난 경계가 아니다. [INFERENCE; GCS redundancy S15]

### 4.2 원본 그림에서 보완할 필수 경계

**A. Mac이 availability의 중심이면 cross-device 요구를 만족하지 못한다.** 다른 host는 cloud MCP API로 직접 읽고 쓸 수 있어야 한다. Mac은 해당 기기의 capture와 durable outbox만 맡는다. local 저장 직후 `queued_local`과 cloud commit 후 `accepted_cloud`, 파생 index 완료 후 `indexed`를 구별한다. 네트워크 끊긴 상태를 “클라우드 기억 완료”로 답하지 않는다. [설계 제안]

**B. GCS write + enqueue에는 원자적 commit이 없다.** 예: GCS write 성공 직후 API crash면 task가 없고, task 먼저 만들면 worker가 아직 없는 객체를 읽는다. GCS의 strong consistency는 서비스 사이 distributed transaction을 만들어 주지 않는다. [S12, S16에 기초한 INFERENCE]

추천안:

1. raw를 cloud에 올리고 generation/hash를 얻는다. object 이름에는 평문 개인정보를 넣지 않는다. 동일 request ID에 conditional create/precondition으로 overwrite를 통제한다.
2. 권위 DB의 **한 트랜잭션**에 `event_id`, verified principal/tenant/project/bank, raw ref+generation+hash, schema/version, deletion epoch, processing state와 outbox row를 함께 commit한다. 이 commit이 완료되어야 cloud acceptance를 반환한다. Postgres transaction의 all-or-nothing을 이 경계에 적용한다. [S16; 설계 제안]
3. dispatcher는 committed outbox만 Tasks에 enqueue. enqueue 성공 직후 outbox 표시 전 crash는 duplicate를 만들 수 있으므로 worker idempotency는 여전히 필요하다. `event_id + projection_version` unique 처리, 완료 projection commit 뒤에만 Tasks에 2xx.
4. raw upload 성공/DB commit 실패로 생긴 orphan은 ACL·연령·ledger 대조 후 정리하며, committed 이벤트의 raw가 빠진 경우에는 오류로 표시하고 원문 backup/outbox에서 복구한다. Scheduler는 이 두 경우와 미완료 작업을 재조정한다.
5. graph/vector는 재생성 가능한 projection으로 취급한다. Neo4j를 원본 권위로 택한다면 해당 DB 내 event+outbox transaction을 쓰는 동등 설계가 필요하며, GCS/queue cross-service 원자성 문제는 사라지지 않는다.

**C. worker가 종료되면 재실행된다는 전제로 만든다.** Cloud Tasks는 at-least-once, 비순서 실행이며 드물게 duplicate가 발생한다. “99.999%가 한 번 실행”이라는 공급자 관측은 exactly-once 계약이 아니다. worker는 SDK 응답을 잃었어도 projection을 중복 생성하지 않도록 unique/upsert하고, 유료 embedding 호출 후 crash에 따른 재과금 가능성을 비용식에 넣는다. [문서 S13]

**D. graph 원자성과 embedding 부작용을 분리한다.** 이벤트의 extraction/embedding 결과는 model/version/chunk ID로 기록한다. 완료/실패 상태가 원문 commit과 독립적임을 API에서 드러낸다. 단순 retry가 이미 생성한 사실을 다시 늘리거나 삭제한 event를 재투영하지 않도록 worker 실행 시점의 tombstone/deletion epoch를 확인한다. [설계 제안]

### 4.3 Cloud Run IAM ID token은 일반 MCP OAuth access token과 다르다

Cloud Run IAM 호출은 Google-signed **OIDC ID token**, Cloud Run URL/custom audience와 `roles/run.invoker`를 요구한다. MCP 표준은 AS가 MCP resource에 발행한 **access token**, RFC9728 discovery와 OAuth 2.1/PKCE를 정의한다. Bearer라는 HTTP 표기만 같다고 동일 인증이 되는 것은 아니다. [문서 S14, 규범 S6–S7]

- **외부 공통 MCP endpoint**: 공개 network 접근은 허용하되 application-layer에서 MCP OAuth를 의무 검증하거나, MCP OAuth를 처리하는 gateway가 private backend에 자기 IAM ID token으로 호출한다. “unauthenticated Cloud Run”이라는 배포 용어는 앱을 무인증으로 만들자는 뜻이 아니다. protected resource metadata도 host가 읽을 수 있어야 한다. [설계 제안]
- **내부 API→worker**: 별도 service account, OIDC ID token, audience, least privilege. GCS/embedding/DB는 각 runtime service identity의 downstream 권한. client의 MCP access token passthrough 금지.
- Cloud Run은 `X-Serverless-Authorization`으로 IAM token을 별도 보내 앱의 `Authorization`을 유지하는 패턴을 문서화한다. 그러나 외부 host가 이 이중 token을 자동 발급한다고 검증된 것은 아니다. 개인 CLI custom-header/shim에는 가능성이 있으나 공통 onboarding 기본값으로 삼지 않는다. [S14; INFERENCE]
- **서비스 계정키 미보관**: Cloud Run attached identity와 GitHub Actions 등의 Workload Identity Federation은 장기 SA JSON key를 피하는 공식 방법. federation은 trusted IdP assertion·STS·attribute condition과 경우에 따라 service account impersonation이 필요하다. 임의 Mac에 자동 trusted workload identity가 생기는 것은 아니다. human identity용 Workforce와 workload용 Workload는 별도다. [S23]
- 사용자 Mac에는 적절한 interactive OAuth/단기 token+OS secure storage를 쓰는 방향을 검토한다. “SA key 없음”은 “refresh token/Neo4j credential/백업 복호키/외부 model credential도 전혀 없음”이라는 말이 아니다. [설계 제안]

## 5. 프라이버시·삭제·백업의 실제 의미

### 5.1 원문 immutable과 WORM을 구별

**논리적 append-only**는 기존 event를 수정하지 않고 새 event와 tombstone을 만드는 모델이다. **물리적 WORM/Bucket Lock**은 보존 기간 전 delete/replace를 막는 저장소 정책이다. GCS locked retention은 감소/해제가 불가능하고, 아직 보존 기간을 만족하지 않은 객체를 지울 수 없다. 해당 locked object를 암호화하는 Cloud KMS key version의 파괴도 제한된다. “forget 시 키를 바로 파괴하면 WORM와 삭제 요구 모두 충족”은 이 조건에서 성립하지 않는다. [문서 S17]

[설계 제안] 개인 기억 raw는 기본적으로 Bucket Lock을 걸지 않고, append-only 식별자/권한 통제로 비의도적 overwrite를 막되 authorized forget은 가능하게 한다. 법적 retention이 필요한 최소 audit 자료는 내용 없는 event ID/시간/결과 등으로 분리하고 법률 검토 전 삭제 가능성/준수 인증을 주장하지 않는다. retention을 걸었다면 `forget` 응답에는 검색 차단 시점과 최종 물리 purge 가능 시점을 분리한다.

### 5.2 forget는 파생물까지 역추적해야 함

삭제 대상은 raw text만이 아니다: chunks, facts, vector embeddings, graph nodes/edges, summaries/profile/mental model, cached retrieval, logs, queue payload, exports, local outbox, Mac 백업, cloud DB snapshots. **원문 event→파생 ID lineage**가 없으면 완전 삭제 범위를 찾기 어렵다. [설계 제안]

권장 의미:

- `blocked_for_retrieval`: 권위 저장소의 tombstone으로 즉시 검색/재투영 차단. worker는 ingestion time뿐 아니라 execution time에 삭제 epoch 확인.
- `active_data_purged`: active raw/projection/cache 제거 완료. ACL로 검색에 안 나온다는 사실만으로 storage purge라고 하지 않음.
- `backup_expiry_pending`: immutable/보존 backup의 잔존 기간 명시, 접근 제한, 자동 만료.
- `purge_complete`: 정의된 범위의 purge 증거 확보 후에만 표시. 외부 model/provider residual까지 입증하지 못하면 별도 한계 표시.

GCS soft delete는 일반적으로 **기본 7일**, 7–90일 조정 또는 0으로 비활성화. 삭제 후 해당 기간에는 영구 삭제가 안 되고 restore 가능하며 저장료도 계속 발생한다. 정책 변경은 이미 soft-deleted 객체의 기존 보존 기간을 없애지 않는다. Object Versioning 비현재 세대와 soft delete도 따로 확인해야 한다. [S18]

### 5.3 restore가 forget를 취소하지 않게

Neo4j Aura restore는 snapshot 데이터로 현재 DB를 **덮어쓴다**. Professional snapshot은 문서상 daily/7일, 상위 tier는 다르다. GCS restore는 soft-deleted 객체의 새 live copy를 만든다. GCS cross-bucket replication은 **source deletion을 destination으로 전달하지 않는다**. 따라서 삭제 후 이전 백업을 복원하면 삭제된 기억이 되살아날 수 있다. [문서 S15, S18, S19]

[설계 제안] 최신 deletion ledger는 restore 대상의 과거 snapshot만 믿지 말고 별도 보호·복제한다. 복원본을 격리된 환경에 올리고 최신 tombstones/deletion epochs를 적용·재검증한 뒤 검색을 재개한다. 백업 export에는 schema/projection/model version, watermark, hash manifest와 deletion watermark를 넣는다. backup key 복구 경로가 없으면 암호화 backup도 복구 불능이고, 업무 credential로 백업을 지울 수 있으면 별도 project의 효과가 약해진다. RPO는 실제 backup 간격·capture outbox 손실·replication 지연, RTO는 복원+재인덱싱+삭제 재적용 시간이다. 측정 전 수치 약속 금지.

### 5.4 암호화와 zero-knowledge의 차이

GCS CSEK는 고객 AES key를 요청 시 제공하고 작업 뒤 서버에서 purge하지만, 작업 중 Google 서비스가 그 key를 사용한다. 일반 metadata/object name은 CSEK 보호 범위가 아니다. 따라서 CSEK조차 client-side E2EE/zero-knowledge와 동일하지 않다. [문서 S20]

Vertex 계열 embedding API는 원문 `contents`를 입력받아 dense numeric vector를 반환한다. 서버측 extraction/embedding/reranking이 평문을 처리하는 설계에서 at-rest encryption이나 CMEK는 운영자/서비스가 평문을 전혀 볼 수 없다는 보장이 아니다. Neo4j vector similarity도 numeric vector property를 인덱스에 사용한다. **embedding은 의미 표현이지 암호문이 아니다.** [S21, S22; 설계 추론]

[설계 제안] truly client-side 암호화 raw backup은 가능하지만, client-only 복호키를 cloud worker에 주지 않으면 그 raw의 서버측 embedding을 할 수 없다. 로컬 embedding 후 cloud vector만 전송해도 vector가 민감한 의미 정보를 포함하는 별도 노출면은 남는다. 유사검색용 벡터를 일반 authenticated encryption으로 그대로 암호화하면 통상적인 cosine/HNSW 검색을 그대로 수행할 수 없다. 특수 privacy-preserving search는 별도 연구·성능 검증 없이 이 설계의 기능으로 주장하지 않는다.

## 6. 권한 계약: principal은 서버가 부여

아래는 구현 요구를 제안하는 것이며 현재 코드가 이 통제를 만족한다는 인증이 아니다. 근거는 MCP audience 검증/state binding 및 DB 정책 문서다. [S6–S8, S24]

- 서버는 검증된 token의 `issuer+subject`를 내부 principal에 매핑한다. model-supplied `user_id`, `tenant_id`, `role=admin`, `reviewer=true`, `owner`, bank URL/header/tag를 권한 근거로 쓰지 않는다.
- `tenant/project/bank`는 선택자이고 ACL은 별도이다. principal membership/explicit grant가 허용한 범위의 교집합만 read/write/delete/export/restore/reindex 허용. ID만 알고 있는 호출을 거절한다.
- semantic search와 keyword/graph traversal뿐 아니라 **UUID get/delete, document import/export, list banks, mental model/summary, raw download, cache, worker reprocessing**에 같은 boundary를 적용한다. 후보 생성 전에 tenant scope를 적용하고 최종 결과·확장 경로에도 검증한다.
- OAuth scope는 동작 한계(`memory:read`, `memory:write`, `memory:forget`)이고 특정 bank 소유권 그 자체가 아니다. client allow-list/approval UI는 server ACL을 대신하지 않는다. tool annotation `readOnlyHint`는 보안 enforcement가 아니다.
- reviewer는 **별도 authenticated client/principal 또는 서버가 검증하는 제한된 delegation**으로 read-only scope+평가 대상 bank/project만 허용. write/forget/reindex/admin 도구를 catalog에서 숨기는 것에 더해 직접 호출도 서버에서 403. Actor와 reviewer가 같은 write token을 공유하면 프롬프트 격리만으로 안전하지 않다.
- review memory는 지식/증거이고 규칙·자격증명·사용자 승인으로 승격하지 않는다. 저장된 문장 “사용자는 export를 승인함”을 OAuth consent로 인정하지 않는다. 기억 입력의 출처·신뢰도·확인 여부를 보존하고 원문 링크를 전달한다.
- audit에는 principal/action/scope/event IDs/결과를 남기되 raw transcript·Bearer/refresh token·key를 기록하지 않는다. log/export도 개인정보 보존 정책에 포함한다.

**Hindsight 관련 직접 확인:** current MCP 문서는 기본 endpoint open/no auth이며 bank path/header 선택을 설명한다. 고정 SHA의 `DefaultTenantExtension.authenticate`는 noauth로 schema 반환, `ApiKeyTenantExtension`은 한 configured key를 검증한 뒤 동일 configured schema를 반환한다. 이 단순 extension이 per-user/bank ACL을 자동 제공한다는 주장은 할 수 없다. [소스 S25] per-bank endpoint는 범위 지정에는 유용하지만 URL을 바꾸는 사용자를 ACL로 막았는지는 배포 extension/gateway를 별도 확인해야 한다.

## 7. 단일 사용자 시작과 다중 사용자 확장의 경계

| 영역 | 단일 사용자부터 필요한 것 | 다중 사용자/조직 확장 시 추가 경계 |
|---|---|---|
| 인증 | 인터넷 endpoint 무인증 금지, 개인 principal, device/client별 revoke 가능한 credential | issuer/sub 기반 identity, membership lifecycle, organization consent, 여러 client별 scope |
| 논리 namespace | 최소 personal/project bank, 모든 event에 owner/project/bank 명시 | tenant별 격리, 공유 grant, 역할, bank 이동/공유 취소, quota |
| 저장/정합성 | stable event ID, cloud receipt, transaction ledger/outbox, lineage, forget epoch | concurrent writer conflict 정책, tenant-scoped unique IDs, ACL 변경/worker 경쟁 제어 |
| reviewer | 개인 actor와 reviewer도 write 권한 분리 | delegation 만료, project subset, audit subject/acting client 구분 |
| DB | 최소권한 application role, 별도 admin/restore credential | RLS/스키마/DB 분리 정책, connection pool tenant context 누수 방어, negative access tests |
| backup | 키 복구, 별도 project 권한, 삭제 ledger 재적용 | tenant export/purge, backup 보존 계약, 권한 취소 뒤 잔존 데이터 |
| privacy | 캡처 동의, secret redaction, 수집 최소화 | residency/DPA/subprocessors/legal retention/security review |

Postgres RLS는 enable 후 policy가 없으면 default deny지만 owner·superuser·BYPASSRLS 예외가 있다. table owner의 `FORCE ROW LEVEL SECURITY`, non-owner runtime role 등의 통제가 필요하다. “RLS 있음=모든 DB 관리자까지 zero-knowledge”가 아니다. 정책의 다른 table 조회는 race/covert channel 검토도 필요하다고 공식 문서가 경고한다. [S24]

[설계 제안] 처음부터 모든 enterprise 기능을 만들자는 뜻은 아니다. **owner/namespace를 모델이 보내는 문자열로 신뢰하지 않는 계약, event lineage, deletion epoch는 처음부터** 필요하다. 조직 공유·복잡한 역할·multi-region은 실제 요구에 맞춰 확장하되 안전한 single-user를 “multi-tenant ready”로 과장하지 않는다.

## 8. 대안 비교: 동일한 판정 기준

| 비교 기준 | Neo4j Aura + GCS | Postgres + pgvector + GCS | Hindsight self-host | Managed memory |
|---|---|---|---|---|
| 직접 확인한 기능 | graph 관계와 numeric vector index, snapshot export/restore [S19, S22] | vectors를 다른 데이터와 저장, exact/ANN, joins/transaction, RLS [S16, S24, S26] | retain/recall/reflect, MCP, external/embedded PostgreSQL, MIT [S25, S27] | vendor MCP/API, memory CRUD/export, provider가 infra 운영 [S28–S29] |
| 정합성 경계 | Neo4j transaction 내 event+outbox는 가능 방향이나 GCS/queue dual-write 별도. graph projection 재처리 정책 필요 [설계] | event/ACL/outbox/vector rows를 같은 SQL transaction에 둘 수 있어 단순한 권위 ledger에 유리. GCS는 여전히 외부 [설계] | 내부 async 작업·문서 upsert·삭제·derived model 일관성은 engine의 semantics 확인. wrapper에서 durable receipt 계약 필요 [설계] | API acceptance/index completion/backups를 vendor 계약에 의존. SDK 성공=전체 pipeline exactly-once 아님 [설계] |
| 권한 | tier별 RBAC/세부 제어 차이, application tenant ACL 필요. paid 상위 tier만의 기능을 Professional에도 있다고 가정 금지 [S30] | RLS 가능하나 runtime owner/BYPASSRLS·pool context 주의 [S24] | 기본 noauth/single shared-key extension을 multi-user ACL로 오인 금지 [S25] | org/user/project filters와 실제 ACL 보장은 별개; vendor key를 reviewer와 공유 금지 [설계] |
| 복구/forget | snapshots가 삭제 전 내용을 담음; GCS 삭제·projection lineage 필요 [S17–S19] | SQL backup/PITR와 GCS retention의 삭제 재적용 필요; projection 재생 가능 [설계] | facts 외 mental models/directives/docs까지 삭제 경로 확인, backend backup 책임 self-host 운영자 [설계] | 삭제 API는 있으나 backup 최종 purge·처리업체 retention·training 정책·export 완전성 확인 [S28–S29] |
| 운영/비용 | provisioned RAM/hour 고정비, graph schema/Cypher·별도 vendor 관리 [S30] | DB compute/storage/backup 고정비 가능, SQL 한 곳에 ledger/ACL 결합 [설계] | 무료 license≠무료 DB/model/compute/backup 운영. retain/reflect 외부 LLM 비용과 선택한 embed/reranker 포함 [S27] | 초기 ops 적음, per-op/token/storage 요금·vendor dependency·DPA/egress/export 점검 [S29] |
| 선택 조건 | 실제 multi-hop/time/entity 관계 질문에서 baseline보다 유용함을 측정했을 때 | 단일 권위 transaction·삭제·ACL 단순성 우선인 기본 시작안 | 자동 fact/temporal/graph retrieval engine 재사용을 원하고 보안/배포 wrapper 운영 가능할 때 | 빠른 공통 remote 연결이 우선이고 계약·privacy 조건을 수용할 때 |

**추천의 이유와 한계:** Postgres안을 추천하는 것은 “graph가 항상 쓸모없다”가 아니라, cloud 동기화의 우선 문제인 acceptance·event identity·outbox·ACL·forget가 SQL transaction 경계와 잘 맞는다는 [INFERENCE]다. Neo4j의 더 나은 memory 정확도/latency는 이 조사에서 측정하지 않았다. graph가 실효성이 있으면 해당 event ledger에서 파생 graph로 추가할 수 있다. Hindsight를 택하면 그 engine의 저장소와 별도 ingest ledger 사이에도 dual-write가 생기므로 엔진 API 호출을 outbox-driven projection처럼 취급하거나 권위 수락 지점을 명확히 해야 한다.

**소스 스냅샷:** `gh api`로 Hindsight `a9eeed77f9bce99d8f97d39a30d3281747300824` (MIT, archived=false, pushed 2026-10-10), pgvector `f37c13f68b57d2c3472b2214fbcff699d6d34876` (archived=false, pushed 2026-10-08)을 확인했다. pgvector API license는 `NOASSERTION`이라 license 파일을 직접 읽었고 PostgreSQL-style permissive 문구를 확인했다. upstream README는 v0.8.7을 안내하지만 Cloud SQL 공식 지원표는 PG13+ pgvector 0.8.5라고 쓰므로 upstream 최신과 managed service 지원을 같다고 하지 않는다. [S26, S31]

**Managed privacy 예:** Mem0 2026-08-22 privacy policy는 Free Plan input/model training과 Paid Plan no-training을 구별하고, business customer 처리 정보에는 별도 계약/DPA가 적용될 수 있다고 명시한다. 이를 모든 Mem0 enterprise 데이터가 학습된다는 주장으로 확대하지 않는다. API delete 문서가 GDPR/CCPA 충족을 표현해도 그것은 사업자 주장이지 이 조사에서 backup·전체 파생물·법적 준수를 검증한 결과가 아니다. structured schema memory export도 byte-for-byte 원문/graph/index 전체 backup과 동일하다고 보장하지 않는다. [S28]

## 9. 비용: 확인 단가와 사용량 기반 식

USD 공개 온디맨드 기본표, 조회 시점 기준. 지역·통화·세금·약정·무료 tier 공유·서비스 revision·storage class에 따라 달라지며 사용량 정보가 없어 확정 월 견적은 제시하지 않는다.

| 항목 | 직접 확인한 공개 단가 | 고정/가변 주의 |
|---|---|---|
| Cloud Run request-based, 기본 표 us-central1 | active CPU $0.000024/vCPU-s, memory $0.0000025/GiB-s, requests $0.40/1M. idle minimum CPU $0.0000025/vCPU-s와 memory $0.0000025/GiB-s [S32] | min=0 request-based는 idle 미과금; min=1은 idle 바닥비용 추가. cold start 완화 목적이지 무중단 보장 아님. |
| Cloud Run instance-based, 기본 표 us-central1 | CPU $0.000018/vCPU-s, memory $0.000002/GiB-s [S32] | 전체 instance lifecycle 과금. request 밖 background 처리 필요 여부와 별개 선택. |
| Cloud Tasks | 최초 1M billable ops/month/account 무료, 이후 $0.40/1M. API call과 push attempt, 32KiB chunk 단위 [S33] | 이벤트 한 개≠한 op. enqueue+attempt+retries+list와 payload size 고려. raw 대신 작은 ref 전달. |
| GCS Standard, Iowa 기본 region | $0.000027397/GiB-hour, Class A $0.005/1000, Class B $0.0004/1000 [S34] | raw+noncurrent+soft-deleted+backup 각각 storage 비용; network·cross-region replication·retrieval 별도. |
| Scheduler | $0.10/job/31일, billing account 최초 3 jobs 무료; paused도 job으로 계산 [S35] | 실행 횟수별 과금이 아니나 reconcile 실행 자체 Run/GCS/DB 비용 있음. |
| AuraDB Professional | starting $0.09/GB-hour, minimum 1GB instance [S30] | provisioned capacity 기준. 730h 기준 1GB 가격식 `0.09×730`은 최소 용량을 계속 실행한다는 가정이지 이 설계의 총 월 비용이 아님. |
| Hindsight Cloud | retain $10/1M tokens, recall $0.75/1M tokens, reflect $0.05/call, 30일 초과 storage $0.25/1M stored tokens/month [S29] | 공식 pricing FAQ의 상품 단가. self-host 모델 비용과 직접 동일 비교하지 않음. |
| embedding/extraction | 공식 Vertex 계열 가격 페이지를 조회했으나 선택 model/region/batch의 embedding 단가를 이 보고서에 확정 인용하지 않음 [S36] | embedding corpus+query+retry+reembedding 토큰/문자 단위를 선택 model SKU에서 확정해야 함. 한국어 문자→token 고정 환산 금지. |

월 비용 모델 [설계식]:

`C_total = C_DB_capacity + C_Run_active + C_Run_idle_min + C_Tasks_attempts + C_GCS_live_versions_softdelete_backup + C_embedding_ingest_query_rebuild + C_extraction_rerank_reflect + C_network + C_logging_KMS_secrets_build + C_reconcile_backup_restore`

request-based Run 구성 요소는 `Σ(vCPU_s × p_CPU_active + GiB_s × p_RAM_active) + requests/1M × p_req + idle_min_seconds × (vCPU × p_CPU_idle + GiB × p_RAM_idle)`에서 해당 free allowance/discount를 적용한다. container 동시성 때문에 HTTP 요청 시간을 모두 더한 것과 billable instance 시간이 같지 않을 수 있다. 무료 tier는 billing account 전체 공유이며 서비스별 request/instance billing free units도 다르다. [S32]

**min=0/1 결정:** single-user low-frequency API/worker는 우선 0을 비교하고 실제 cold start/tool timeout 문제가 확인되면 API만 1을 고려한다. 항상 실행되는 DB·Aura 비용은 Run scale-to-zero로 사라지지 않는다. 1 warm instance를 durability나 HA의 증명으로 표현하지 않는다; 공식 문서는 minimum이 best-effort이며 restart/capacity/quota 문제가 있다고 명시한다. [S37; 설계 판단]

## 10. 실패 시나리오와 통제

| 실패/공격 | 피해 | 제안 통제 | 근거·미확인 |
|---|---|---|---|
| Mac offline/종료·disk 손상 | local queue 유실, 타 기기 새 기억 미보임 | durable local commit, cloud receipt 상태 구별, cloud direct access, 독립 backup | [설계] local durability/backup restore 실측 없음 |
| raw 성공→enqueue 전 crash | 원문은 있으나 영구 미색인 | DB event+outbox commit, committed outbox dispatch, reconcile | [S12, S16; INFERENCE] |
| worker commit→ACK 유실 | 재실행·중복 facts·embedding 재과금 | event/projection unique IDs, idempotent upsert, 완료 후 2xx | [S13–S14; 설계] |
| 오래된 task가 forget 뒤 실행 | 삭제된 기억 재생성 | current deletion epoch/ACL 확인, tombstone barrier | [설계] |
| 별도 project backup 복원 | 잊힌 원문/파생물 부활 | 복원 격리, latest deletion ledger 재적용, backup retention 정책 | [S15, S18–S19] |
| WORM retention 적용 뒤 forget | 물리 삭제/키 파괴 거절 | 기억 raw에는 기본 WORM 지양, legal retention 자료 분리, final purge 시간 공개 | [S17] |
| MCP token을 GCP token처럼 전달 | auth 실패 또는 confused deputy | application OAuth와 internal IAM token 분리, audience 검증 | [S6–S7, S14] |
| 모델이 victim bank ID/admin 권한 제시 | 타 사용자 get/delete/export | verified principal mapping, 모든 도구 ACL, reviewer read-only token | [S8, S24–S25; 설계] |
| retrieval memory에 악성 명령 저장 | 장기 prompt injection/허위 승인 | provenance, untrusted-data 취급, 서버 권한 검증, 승인 없는 외부 전송 금지 | [MCP 보안 S8; 설계] 완전 방어 측정 없음 |
| metadata/discovery URL 악용 | SSRF·cloud credential 노출 | HTTPS, reserved/private IP/redirect 제한, CIMD fetch egress 통제 | [S8] |
| raw/credential logging | 개인정보·token 이차 유출 | request redaction, 내용 없는 audit, 보존 제한 | [S7; 설계] |
| region outage/credential 파괴 | 저장/검색·복원 불가 | 선택 region/replication/backups/독립키, 재인덱싱 절차 | [S15] 11-nines는 GCS 설계 목표이지 end-to-end memory availability 측정치 아님 |

## 11. 후속 구현 전 확인 항목과 조사 한계

- Claude Code/Codex/ChatGPT의 실제 버전과 plan별 remote auth, 2025/2026 protocol negotiation, CIMD/registration, refresh expiry/revoke, SSE/disconnect 처리. 이 조사에서는 로그인을 시도하지 않았다.
- crash injection을 통한 cloud acceptance 이후 loss 여부, enqueue gap/duplicate/out-of-order, forgotten event replay, cold start/timeout, peak concurrency. 아직 구현·성능 시험 없음.
- active store·derivative·cache·noncurrent generation·soft delete·vendor backup·Mac export의 삭제 증거 및 restore 후 tombstone 재적용. 실제 삭제와 crypto erase를 검증하지 않았다.
- corpus별 exact/vector/hybrid/graph retrieval 품질, 한글 embedding chunking, privacy leakage, multi-hop 효용, ingestion/rebuild/query 비용. 제품 benchmark를 이 사용자의 품질 측정으로 대체하지 않았다.
- client-side encryption과 cloud semantic processing 중 어느 신뢰 모델을 선택하는지. E2EE/zero-knowledge 기능이나 보안 인증 성공을 주장하지 않는다.
- 법적 삭제/retention, DPA, subprocessor/region, paid/free training policy는 계약·플랜별 확인. 이 문서는 법률/준수 인증이 아니다.
- OpenAI 옛 developer-mode URL과 Mem0 추정 data-export URL은 404였고, OpenAI 공식 Help 문서와 Mem0 공식 `llms.txt`의 실제 memory-export/delete 경로로 재확인했다. GitHub metadata/API 접근은 성공했다. 문서 live URL은 이후 변할 수 있고, 코드 관련 근거는 SHA 고정 링크를 사용했다.

## 공식 출처 목록

- **S1** [MCP current stable specification](https://modelcontextprotocol.io/specification), [versioned 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28).
- **S2** [MCP 2026-07-28 GA release](https://blog.modelcontextprotocol.io/posts/2026-07-28/) — stateless, no handshake/session, CIMD, DCR deprecation 직접 문구.
- **S3** [MCP architecture](https://modelcontextprotocol.io/specification/2026-07-28/architecture) — host ownership, conversation isolation.
- **S4** [MCP transports overview](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports).
- **S5** [Streamable HTTP 2026](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http).
- **S6** [MCP authorization](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization).
- **S7** [Authorization security requirements](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/security-considerations).
- **S8** [Current MCP security best practices](https://modelcontextprotocol.io/docs/2026-07-28/tutorials/security/security_best_practices), [2025-11-25 session hijacking](https://modelcontextprotocol.io/docs/2025-11-25/tutorials/security/security_best_practices#session-hijacking).
- **S9** [Claude Code MCP reference](https://code.claude.com/docs/en/mcp).
- **S10** [Codex MCP reference](https://developers.openai.com/codex/mcp) → [current official reference](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).
- **S11** [ChatGPT developer mode and MCP apps](https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt).
- **S11a** [OpenAI Responses remote MCP](https://developers.openai.com/api/docs/guides/tools-connectors-mcp).
- **S12** [GCS consistency/atomicity](https://docs.cloud.google.com/storage/docs/consistency), [request preconditions](https://docs.cloud.google.com/storage/docs/request-preconditions) (전자는 직접 읽음, 후자는 전자의 권장 링크).
- **S13** [Cloud Tasks pitfalls/at-least-once/order](https://docs.cloud.google.com/tasks/docs/common-pitfalls).
- **S14** [Cloud Run service authentication/ID tokens](https://docs.cloud.google.com/run/docs/authenticating/service-to-service), [Tasks private worker](https://docs.cloud.google.com/run/docs/triggering/using-tasks).
- **S15** [GCS availability/durability/replication](https://docs.cloud.google.com/storage/docs/availability-durability).
- **S16** [Postgres transactions](https://www.postgresql.org/docs/18/tutorial-transactions.html).
- **S17** [GCS Bucket Lock](https://docs.cloud.google.com/storage/docs/bucket-lock).
- **S18** [GCS soft delete](https://docs.cloud.google.com/storage/docs/soft-delete).
- **S19** [Neo4j Aura backups/restore/export](https://neo4j.com/docs/aura/managing-instances/backup-restore-export/).
- **S20** [GCS customer-supplied keys](https://docs.cloud.google.com/storage/docs/encryption/customer-supplied-keys).
- **S21** [Vertex text embedding official document](https://cloud.google.com/vertex-ai/generative-ai/docs/embeddings/get-text-embeddings) → [current official Agent Platform page](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/embeddings/get-text-embeddings).
- **S22** [Neo4j vector indexes](https://neo4j.com/docs/cypher-manual/current/indexes/search-indexes/vector-indexes/).
- **S23** [Workload Identity Federation](https://docs.cloud.google.com/iam/docs/workload-identity-federation), [Workforce Identity Federation](https://docs.cloud.google.com/iam/docs/workforce-identity-federation).
- **S24** [Postgres RLS](https://www.postgresql.org/docs/18/ddl-rowsecurity.html).
- **S25** [Hindsight MCP official docs](https://hindsight.vectorize.io/developer/mcp-server), [pinned tenant implementation](https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-api-slim/hindsight_api/extensions/builtin/tenant.py).
- **S26** [pgvector pinned README](https://github.com/pgvector/pgvector/blob/f37c13f68b57d2c3472b2214fbcff699d6d34876/README.md), [pinned license](https://github.com/pgvector/pgvector/blob/f37c13f68b57d2c3472b2214fbcff699d6d34876/LICENSE).
- **S27** [Hindsight pinned README](https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/README.md).
- **S28** [Mem0 memory export](https://docs.mem0.ai/platform/features/memory-export), [delete API semantics](https://docs.mem0.ai/core-concepts/memory-operations/delete), [privacy policy](https://mem0.ai/privacy-policy).
- **S29** [Hindsight pricing](https://vectorize.io/pricing).
- **S30** [Neo4j pricing/tier differences](https://neo4j.com/pricing/).
- **S31** [Cloud SQL extensions/pgvector support versions](https://docs.cloud.google.com/sql/docs/postgres/extensions).
- **S32** [Cloud Run pricing](https://cloud.google.com/run/pricing).
- **S33** [Cloud Tasks pricing](https://cloud.google.com/tasks/pricing).
- **S34** [GCS pricing](https://cloud.google.com/storage/pricing).
- **S35** [Cloud Scheduler pricing](https://cloud.google.com/scheduler/pricing).
- **S36** [Vertex/Agent Platform pricing](https://cloud.google.com/vertex-ai/generative-ai/pricing).
- **S37** [Cloud Run minimum instances/billing/best-effort](https://docs.cloud.google.com/run/docs/configuring/min-instances).
