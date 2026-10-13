# 로컬·클라우드 공용 에이전트 메모리: GitHub·공식 문서 구현 비교

조사 기준: 2026-10-11. 목적은 **Claude Code·Codex·다른 에이전트가 같은 개인 클라우드 메모리를 접근하는 독립 MCP 서비스**와 **외주회사 업무의 완전히 분리된 로컬 memory pipeline**의 후보 선정이다. 두 환경은 코드·schema·도메인 계약을 공유할 수 있는지 조사하되 업무 데이터·credential의 자동 동기화는 금지한다. Agent Flow core에 저장소를 넣거나 기존 호스트 메모리를 갈아엎는 제안이 아니다. 이 보고서는 공개 1차 자료와 고정 Git SHA를 읽은 구현 조사이며, 직접 설치·운영·보안 공격·성능 측정은 하지 않았다. 유료 API 호출, 계정 설정 변경, 클라우드 생성도 하지 않았다.

증거 표기: **[소스]** 공개 구현에서 읽은 동작, **[문서]** 공식 문서의 계약/설명, **[업체 주장]** 제품·성능 주장, **[추론]** 도입 판단. “미확인”은 기능이 없다는 단정이 아니라 이번 읽기에서 계약 또는 구현을 확정하지 못했다는 뜻이다. hosted 플랫폼의 동작을 OSS 라이브러리의 동작으로 옮겨 적지 않는다. GitHub 별·다운로드 수는 품질 근거로 사용하지 않았고, GitHub 전체를 전수 조사한 것도 아니다.

## 1. 먼저 바로잡아야 할 이름·버전

- **Mem0 OSS ≠ Mem0 Platform ≠ 예전 mem0-mcp.** 공식 `mem0ai/mem0-mcp` 저장소는 API에서 `archived=true`이며 README도 유지보수 종료와 새 hosted MCP `https://mcp.mem0.ai/mcp`를 안내한다. 과거 stdio wrapper는 플랫폼 API client이지 OSS 저장 엔진 자체가 아니다. 현재 hosted endpoint는 OAuth/브라우저 승인 또는 Bearer API key를 문서화한다. [M-old-mcp] [M-host-mcp]
- **mem0ai/OpenMemory ≠ CaviraOSS/OpenMemory.** 전자는 현재 Claude Code·Codex·OpenCode의 로컬 세션 이식 CLI이고, 옛 메모리 MCP/UI는 `openmemory-archive/`의 읽기 전용 snapshot이다. 그 snapshot은 Apache-2.0, 현재 repo 루트는 MIT다. 후자의 GitHub API canonical `full_name`은 현재 **CaviraOSS/LongMemory**이며, SQLite 기반 독립 memory engine과 HTTP/stdio MCP를 제공한다. 이름만 보고 같은 제품으로 취급하면 안 된다. [O-current] [O-archive] [CV-readme]
- **Supermemory MCP v1 ≠ 현재 MCP.** 옛 `supermemory-mcp` README는 v1 deprecated 및 `supermemory/apps/mcp` 이동을 안내한다. 옛 “no login/free” 문구로 현재 인증 모델을 판단하면 틀린다. 현재 공개 MCP는 OAuth/API key 검증과 organization/user/space를 다룬다. [S-old] [S-mcp] [S-auth]
- **Letta V1 API server ≠ 현재 Letta Code.** `letta-ai/letta` main은 현재 구현이 `letta-code`에 있다고 명시하고, V1은 retired `archive` branch에 남겼다. 현재 Cloud/로컬 MemFS 구조를 2025년의 PostgreSQL V1 구조로 설명하지 않는다. [L-old] [L-current]

## 2. 재현 가능한 저장소 snapshot

`gh api repos/{owner}/{repo}`와 `commits/HEAD`, recursive git tree, Contents API로 metadata와 실제 경로를 확인했다. 아래 날짜는 GitHub `pushed_at`이며 배포일·릴리스일·품질 지표가 아니다. `updated_at`도 수집했으나 활동/기능 근거로 사용하지 않는다. 라이선스는 API SPDX를 시작점으로 삼되 MCP reference와 OpenMemory 하위 snapshot은 LICENSE/README를 별도 확인했다. 실제 채택 시 파일별 권리·의존성 라이선스 재검토가 필요하다.

| 저장소 | SHA (고정 commit) | 공개 LICENSE/API 분류 | archived | pushed_at |
|---|---|---|---|---|
| [Hindsight](https://github.com/vectorize-io/hindsight) | [`a9eeed77f9bce99d8f97d39a30d3281747300824`](https://github.com/vectorize-io/hindsight/commit/a9eeed77f9bce99d8f97d39a30d3281747300824) | MIT | false | 2026-10-10T14:24:49Z |
| [Mem0](https://github.com/mem0ai/mem0) | [`b7ad69afda6b6ed030347c66d48a13e4de9dec08`](https://github.com/mem0ai/mem0/commit/b7ad69afda6b6ed030347c66d48a13e4de9dec08) | Apache-2.0 | false | 2026-10-09T06:17:43Z |
| [Graphiti](https://github.com/getzep/graphiti) | [`964bb11d1e7020e3cc67fab244268b0736b6c219`](https://github.com/getzep/graphiti/commit/964bb11d1e7020e3cc67fab244268b0736b6c219) | Apache-2.0 | false | 2026-10-10T15:14:17Z |
| [Supermemory](https://github.com/supermemoryai/supermemory) | [`709723dea69dba8340fc42c0aafd86a2b6a4a0f4`](https://github.com/supermemoryai/supermemory/commit/709723dea69dba8340fc42c0aafd86a2b6a4a0f4) | MIT | false | 2026-10-11T04:06:36Z |
| [Supermemory MCP v1](https://github.com/supermemoryai/supermemory-mcp) | [`84f5dc9f1cf077ba753decbf56805205b5c0443a`](https://github.com/supermemoryai/supermemory-mcp/commit/84f5dc9f1cf077ba753decbf56805205b5c0443a) | MIT | false | 2026-10-02T18:38:46Z |
| [Letta (pointer/역사)](https://github.com/letta-ai/letta) | [`5bcdd177d70fa2b31a754cfcd801e77b2e1ab16a`](https://github.com/letta-ai/letta/commit/5bcdd177d70fa2b31a754cfcd801e77b2e1ab16a) | Apache-2.0 | false | 2026-09-10T17:59:08Z |
| [Letta Code](https://github.com/letta-ai/letta-code) | [`271f119dcf37d58649a18e6c733386b3c710a456`](https://github.com/letta-ai/letta-code/commit/271f119dcf37d58649a18e6c733386b3c710a456) | Apache-2.0 | false | 2026-10-11T01:44:55Z |
| [LangMem](https://github.com/langchain-ai/langmem) | [`48e3c11f5bb527282c7d5339c6a87a0b35abccfc`](https://github.com/langchain-ai/langmem/commit/48e3c11f5bb527282c7d5339c6a87a0b35abccfc) | MIT | false | 2026-10-02T19:35:27Z |
| [Cognee](https://github.com/topoteretes/cognee) | [`0ec7a9fa61c9ff04bf7e02e0d57af363a993a5e1`](https://github.com/topoteretes/cognee/commit/0ec7a9fa61c9ff04bf7e02e0d57af363a993a5e1) | Apache-2.0 | false | 2026-10-09T22:31:57Z |
| [MCP reference servers](https://github.com/modelcontextprotocol/servers) | [`c003d0d807409b22fa640d1f8e11f38f15755721`](https://github.com/modelcontextprotocol/servers/commit/c003d0d807409b22fa640d1f8e11f38f15755721) | NOASSERTION; transition LICENSE 참조 | false | 2026-10-11T04:35:52Z |
| [Mem0 MCP archive](https://github.com/mem0ai/mem0-mcp) | [`624024deacbbe1948572a968abdb9d9e93ded548`](https://github.com/mem0ai/mem0-mcp/commit/624024deacbbe1948572a968abdb9d9e93ded548) | Apache-2.0 | true | 2026-03-24T23:36:56Z |
| [mem0ai OpenMemory](https://github.com/mem0ai/openmemory) | [`2df78cc48e5f688a771fee5b39899325accc2450`](https://github.com/mem0ai/openmemory/commit/2df78cc48e5f688a771fee5b39899325accc2450) | MIT | false | 2026-07-29T09:40:39Z |
| [Honcho](https://github.com/plastic-labs/honcho) | [`3922af856d78ec41133916deec4d821fa9c5a92e`](https://github.com/plastic-labs/honcho/commit/3922af856d78ec41133916deec4d821fa9c5a92e) | AGPL-3.0 | false | 2026-10-09T22:33:07Z |
| [Cavira LongMemory (old OpenMemory)](https://github.com/CaviraOSS/LongMemory) | [`9ee2c8e1ed42d83eb788afb9ffc3a82b84405da5`](https://github.com/CaviraOSS/LongMemory/commit/9ee2c8e1ed42d83eb788afb9ffc3a82b84405da5) | Apache-2.0 | false | 2026-09-20T11:57:46Z |

## 3. 운영·연결·격리 비교

“클라우드 가능”은 서버를 원격에 둘 수 있다는 뜻이지, 바로 안전한 멀티테넌트 SaaS라는 뜻은 아니다. stdio 프로세스가 **원격 HTTP API에 연결**하면 저장 위치는 클라우드일 수 있다. 반대로 HTTP로 로컬 JSONL 서버를 감싸기만 하면 인증·백업·격리가 자동으로 생기지 않는다.

| 후보 | 공개 범위 / 저장·운영 DB | Remote MCP / stdio | 인증·tenant/bank scope | 이번 요구에 대한 판단 |
|---|---|---|---|---|
| **Hindsight** | [소스] MIT API/메모리 엔진/MCP/worker 공개. PostgreSQL+pgvector 중심; Oracle 지원은 공식 문서 설명. 별도 hosted Cloud 존재. | 네이티브 HTTP MCP; Claude Code plugin에는 API를 호출하는 stdio subprocess도 존재. | 기본 `DefaultTenantExtension`은 no-auth/public schema. 기본 API-key extension은 같은 schema를 쓰는 single tenant. bank/tag와 auth boundary는 구분해야 하며 확장 tenant/operation validator 구성 필요. | **OSS 클라우드 memory service 1순위**. recall/reflect/mental-model까지 풍부하지만 공개 기본값 그대로 인터넷에 노출하면 안 됨. [H-readme] [H-mcp] [H-tenant] [H-stdio] |
| **Mem0 OSS / Platform** | [소스] Apache-2.0 Python/TS 엔진·SDK·self-host server. Python 엔진은 vector-store factory + SQLite history; 현재 compose는 pgvector/PostgreSQL. [문서] managed proprietary 최적화는 별도. | [문서] 현재 hosted HTTP MCP; 예전 archive wrapper는 stdio/HTTP. OSS API server 자체를 current hosted MCP와 동일시하면 안 됨. | user/agent/run 필터. self-host server는 JWT/X-API-Key 및 admin 검사; auth off는 명시적 env. hosted account/project 권한을 wrapper의 default user filter로 대체할 수 없음. | **운영 최소화 managed 1순위**. OSS를 선택하면 MCP 연결·서버 scope 계약을 별도 확정. [M-core] [M-compose] [M-auth] [M-host-mcp] [M-readme] |
| **Graphiti / Zep** | [소스] Apache-2.0 temporal graph 엔진/MCP 공개. MCP는 FalkorDB 기본, Neo4j 선택; core의 추가 backend와 MCP factory 지원 범위는 별개. [문서] Zep은 proprietary Context Graph Engine을 쓰는 managed 서비스. | HTTP(`/mcp/`)/SSE/stdio 구현. README는 MCP를 **experimental**로 명시. | `group_id`는 graph partition/검색 필터. FalkorDB는 group별 graph clone; 다른 backend는 동일 driver일 수 있음. 이 자체가 사용자 인증/권한이 아님. 읽은 MCP 초기화·도구에는 principal-to-group ACL이 나타나지 않음. | **시간·사실 provenance/관계가 핵심일 때**. auth gateway 및 UUID 접근 scope 보강 없이는 다중 사용자 공유 서버로 부적합. [G-readme] [G-mcp] [G-scope-driver] [G-id-tools] |
| **Supermemory / current MCP** | [소스] MIT repo에는 MCP·UI·SDK 관련 공개 코드. **서버 memory engine는 별도 비공개 codebase**, local binary도 OSS 아님. [문서] embedded proprietary graph engine, `.supermemory` data dir; cloud 내부 DB 계약 미확인. | current hosted HTTP MCP, OAuth discovery. local binary에는 managed MCP가 포함되지 않는다고 문서 명시. 이전 wrapper를 복제하는 것과 엔진 자체 self-host는 다름. | 현재 JWT issuer/audience 검증 또는 API-key session lookup; organization/user별 active space와 namespace. local binary는 single-key/single-org. | **managed 사용자 경험 우선의 4번째 shortlist**. 공개 wrapper MIT를 full engine OSS로 표기하면 안 됨. [S-mcp] [S-auth] [S-local] [S-enterprise] |
| **Letta / Letta Code** | [소스/문서] current Apache-2.0 harness/App Server/MemFS. 로컬 store는 disk JSON/JSONL 계열, MemFS는 git 추적; Cloud agents의 memory/identity/conversations 저장은 서비스 계약. Cloud 내부 DB 미확인. | 주 역할은 stateful agent harness 및 외부 MCP 소비/도구 관리. 읽은 current source에서 Claude/Codex 공용 standalone memory MCP server를 확인하지 못함. | agent/conversation별 state와 cloud login, memory repo sync. | 동일 agent를 여러 컴퓨터에서 쓰는 목적에는 맞지만 **호스트 교체 없는 독립 MCP** 요청에는 범위가 너무 큼. [L-current] [L-store] [L-memfs] |
| **LangGraph / LangMem** | [소스/문서] LangMem MIT extraction/consolidation/reflection/tools. LangGraph BaseStore 사용; InMemoryStore는 restart 시 손실, AsyncPostgresStore 등 DB-backed store 필요. | LangMem 자체는 memory primitives/agent tools이지 ready-made remote MCP endpoint가 아님. remote reflection은 LangGraph deployment API 연결. | namespace template/store key로 구획; HTTP principal/tenant 권한은 호출 애플리케이션 책임. | **직접 얇은 MCP를 만드는 대안**. 통제력은 높으나 auth/CRUD/export 운영까지 직접 소유. [LM-readme] [LM-tools] [LM-reflect] |
| **Cognee** | [소스] Apache-2.0 remember/recall/graph pipeline/MCP. 현재 기본 relational SQLite + vector LanceDB + graph **Ladybug**; Kuzu/Neo4j/PostgreSQL 옵션. 옛 자료의 Kuzu 기본 설명과 다름. managed Cloud도 별도. | stdio/HTTP/SSE, local/API/cloud client modes. | upstream API의 Bearer 또는 X-Api-Key와 datasets/owned memory. MCP Host/Origin guard는 DNS rebinding 방어이지 사용자 ACL의 대체가 아님. | 문서·코드 corpus/company brain에 강한 후보지만 이번 개인 cross-agent memory의 초기 운영면적은 큼. [C-mcp] [C-graph] [C-vector] [C-relational] |
| **Official MCP reference memory** | [소스] local JSONL entities/relations/observations. LICENSE는 MIT→Apache-2.0 transition/문서 CC-BY-4.0을 설명하므로 일괄 MIT 표기 금지. | 실행 entry는 stdio. HTTP cloud service/auth/tenancy는 이 구현이 제공하는 계약 아님. | 프로세스/파일 경계; authenticated tenant/bank 없음. | protocol 학습/reference 용도. 공식 README도 production-ready가 아니라고 경고. cloud backend shortlist 탈락. [R-memory] [R-license] [R-readme] |
| **mem0ai/OpenMemory** | current MIT session porter; 옛 Apache-2.0 memory MCP는 archive snapshot. | current 제품은 session import/export CLI, 새 cloud memory MCP 아님. | current local harness session 경계. | 구형 소개에 기대 새 서버를 선택하지 말 것. Mem0 self-host/platform으로 이관하라는 공식 안내. [O-current] [O-archive] |
| **CaviraOSS/LongMemory** (옛 OpenMemory) | [소스/문서] Apache-2.0 TS memory engine+SQLite, immutable/provenance/temporal 및 governed project memory. | stdio + stateless Streamable HTTP `/mcp`; self-host platform examples. | server-bound user/project/team/role/agent, tool allowlist/read-only. `resolve_user`/`resolve_project`는 다른 identity override 거부. network auth는 API key가 있을 때만 강제. | **cloud-ready OSS 차순위**. SQLite persistent-disk 단일 서비스 운영은 가능하나 hosted managed SLA/다중 replica 설계는 확인하지 못함. [CV-readme] [CV-mcp] [CV-permission] [CV-auth] [CV-app] |
| **Honcho** | [소스/문서] AGPL-3.0 FastAPI core, PostgreSQL/pgvector+Redis deriver; peer/session/representation 모델. hosted API 별도. | 공개 first-party MCP는 Cloudflare Worker/stdio/long-lived HTTP. HTTP 세션 map은 process memory여서 문서상 single instance. | Bearer auth, workspace/peer/session/scopes. workspace argument와 default header는 identity 인증과 별개. | 사람·프로젝트의 장기 표현/추론이 중요하면 유력 차순위. AGPL 의무·async derivation·stateful MCP 운영 평가 필요. [HO-readme] [HO-mcp] [HO-models] |

### 소유권과 비용에 관한 공통 판단

[추론] 관리형에서는 DB 운영은 줄지만 vendor API, 계정 scope, retention·DPA·지역·export 계약 의존성이 커진다. 직접 운영은 데이터 통제/코드 감사가 가능하나 TLS/auth, DB migrations, worker 큐, embedding 모델, 장애/복구, LLM extraction/reflect 비용을 운영자가 소유한다. 기능 표가 같아도 hosted/OSS의 저장 알고리즘·비용·품질이 같다는 결론은 나오지 않는다. 예를 들어 Mem0 README는 benchmark가 managed proprietary optimizations를 포함하며 OSS에서 동일 숫자를 기대하지 말라고 명시한다. [M-readme]

## 4. CRUD·forget·provenance·시간·학습·이식 비교

| 후보 | CRUD / forget / 중복·update | provenance·temporal·reflect | backup/export 범위와 한계 |
|---|---|---|---|
| Hindsight | retain, list/get/delete document/bank/model. `document_id`는 동일 문서 upsert를 명시; append/update 모드는 구분. mental-model settings patch와 refresh는 다른 작업. | semantic/keyword/graph/temporal recall. 원문 chunks/facts/observations와 model `based_on`, tool-driven reflect. 모델 refresh full/delta. | logical ZIP transfer: docs/facts/config/mental-model 및 attachment 등 분류. 벡터/links 재생성, observation history는 재구성, raw original uploads/alias 등은 그대로 운반하지 않음. **logical migration ≠ 물리 backup**. [H-upsert] [H-model-doc] [H-recall] [H-export] |
| Mem0 OSS / Platform | add/get/list/search/update/delete/delete_all/history. **현재 v3 inference는 ADD-only extraction**; 기존 기억 자동 UPDATE/DELETE라는 옛 설명은 current source와 다름. exact text hash는 검색된 기존 top-10+현재 batch에서 dedup하므로 global unique 보장 아님. explicit update/delete는 남아 있음. | user/agent/run metadata, timestamps/expiration·entity linking; SDK history. hosted temporal/multi-signal 고도화는 업체 설명과 OSS를 구분. Hindsight 같은 standalone reflect/mental-model을 이 경로에서 확인하지 못함. | hosted schema-based memory export 문서 존재하나 LLM/구조 변환 export는 byte-exact backup 아님. OSS는 vector DB뿐 아니라 SQLite history/messages도 보존/삭제 정책에 포함. [M-add] [M-crud] [M-delete] [M-export] |
| Graphiti | add episode/triplet, entity/fact 검색, UUID delete, episode remove, group clear. LLM entity/edge dedup·contradiction invalidation. 같은 episode 재입력을 idempotent PUT로 가정하면 안 됨. | episode provenance→entity nodes→fact edges. `created_at`/`expired_at`와 `valid_at`/`invalid_at`. hybrid RRF/node distance search. community/saga summary는 있지만 Hindsight의 reflect/mental-model API와 동일하지 않음. | 이번 MCP tool 목록에서 portable whole-bank export를 확인 못함. graph DB backup과 원문 episodes/LLM configuration 보존이 필요한 운영 경로 [추론]. episode removal의 파생 상태 영향은 아래 위험 참고. [G-ingest] [G-edge] [G-search] [G-remove] [G-mcp] |
| Supermemory | current MCP add/list/search/profile/get document/forget. hosted v5 API는 stable caller ID append/diff와 PATCH replace/reprocess를 구분. MCP forget는 의미 검색 top match 1개를 ID로 forget. | source document IDs를 list memories로 노출; stable/dynamic profile. hosted graph/extraction engine 비공개이므로 relation/temporal consistency 구현 감사 불가. | local data directory 이동/backup은 문서 설명; hosted full-fidelity export·purge/backup retention 보장 미확인. forget는 문서상 **soft delete**. [S-mcp] [S-updates] [S-forget] [S-forget-doc] [S-local] |
| Letta Code | memory files/blocks rewrite, git repo sync, agent/conversation 관리. harness 안에서 실행되는 self-edit/reflect. | git history/skills/prompt 학습; cloud conversation 유지. 독립 MCP contract 아님. | git MemFS + memory/conversation export는 존재한다는 문서. `.af` AgentFile 전체 export/import는 제거됨. cloud state 전체 복원과 memory repo 이동을 구분. [L-current] [L-memfs] |
| LangMem | tools가 namespace+UUID로 store put/delete. update/delete에는 ID 필수, create는 새 UUID. consolidation/extraction은 라이브러리 기능. | structured schema/background reflection. provenance/event validity를 필요대로 schema에 설계해야 함. | BaseStore/DB backup 및 사용자 export API를 직접 구성. InMemoryStore 예제는 durable cloud 아님. [LM-tools] [LM-readme] [LM-reflect] |
| Cognee | MCP remember/recall/forget, dataset 또는 data_id+dataset scope, owned everything delete. chunk incremental update 및 improve는 내부 API와 MCP advertised tools를 구분. | 문서→graph/vector pipeline, dataset/source 기반. 여러 search/reasoning 방식은 단일 reflect 계약과 다름. | public `cognee.export`: pydantic snapshot, cogx re-import archive, JSON/GraphML/Cypher. export는 dataset graph 중심; 서비스 auth/config/worker를 통째로 복구하는 DB backup이라고 단정 불가. [C-mcp] [C-forget] [C-export] |
| Reference memory | entity/relation/observation 생성/삭제. exact-string observations·name 기반 entity, case-insensitive substring search. | 자동 embedding/LLM extraction/temporal/reflect 없음; knowledge graph라는 이름은 동일 알고리즘 보장이 아님. | JSONL 파일 운반. 클라우드 동시성/tenant/service restore는 별도 설계. [R-memory] |
| mem0ai/OpenMemory | 현행 session 포팅/재-export CLI. 옛 memory CRUD를 current 기능으로 표기하지 않음. | raw harness session 이식은 학습된 fact recall과 다름. | local session import/export 자체가 주 기능; cross-device cloud service 아님. [O-current] |
| Cavira LongMemory | immutable ingest, task/decision/asset lifecycle. 13개 MCP allowlist에는 일반 memory hard-delete/forget 도구가 안 보임; archive/lifecycle는 물리 purge와 다름. | strict/historical/associative/world-grounded modes, provenance/valid-vs-recorded time, explanation·ACL gates. [문서] 선택적 evidence-grounded answer와 ordinary recall 분리. | SQLite data/migration JSON·JSONL import 설명. 완전 export/physical purge/restore 계약은 추가 확인 필요. [CV-readme] [CV-mcp] [CV-permission] |
| Honcho | messages/session/conclusion create/query/delete와 scopes. background deriver가 representation/conclusions 갱신; API 수락과 파생 state 반영 사이 지연. | peer-centered reasoning/representation, message/source_ids·time 데이터. Graphiti-style bitemporal edge invalidation으로 동작한다고 단정하지 않음. | PostgreSQL/Redis 운영 backup [추론], portable full graph/representation export와 원본 삭제 후 파생 conclusion purge 계약 미확인. [HO-readme] [HO-mcp] [HO-models] |

## 5. “recall/reflect/mental model/graph memory”의 실제 의미

### 5.1 Hindsight: 검색, 답변 생성, 지속 요약을 분리한다

1. **Recall은 기억 후보 검색이다.** `retrieve_all_fact_types_parallel`은 bank/fact types/tags/date를 받아 시간 제약을 추출하고 memories store의 `recall_unified`를 호출한다. 반환값은 semantic/BM25-label/graph/temporal arms로 나뉘며 fusion/rerank는 downstream이다. 소스가 이 경로를 검색이라고 구분하므로 recall 결과와 LLM이 만든 조언을 같은 데이터로 취급하면 안 된다. [소스: H-recall]
2. **검색 용어도 구현을 읽어야 한다.** 문서는 keyword arm을 BM25로 묶어 부르지만 `native` PostgreSQL backend는 `tsvector + ts_rank_cd`이며 **true BM25가 아니라고 공식 문서가 명시**한다. PGroonga bigram/pg_search tokenizers 같은 한국어·다국어 설정을 포함한 후보 평가가 필요하다. “hybrid 검색”이라는 이름만으로 한국어 품질을 확정하지 않는다. [문서: H-retrieval-doc]
3. **Reflect는 LLM tool-calling agent loop다.** `reflect_async`는 bank profile/directives, mental-model search/read, observation search, raw recall/expand 함수들을 `run_reflect_agent`에 전달하고 iteration/context/output/time budgets를 적용한다. 즉 검색 결과를 근거로 답변을 합성하는 추가 모델 실행이며 비용·지연·오류 가능성이 생긴다. mental-model→observation→raw-fact의 계층은 reflection tools와 문서화된 retrieval 전략에 나타나지만 모든 쿼리가 기계적으로 같은 순서를 보장한다는 뜻은 아니다. [소스: H-reflect] [H-reflect-tools]
4. **Mental model은 모델 가중치 학습이 아니라 DB에 저장된 지속 문서다.** 생성 코드가 `bank_id/name/source_query/content/tags/trigger`를 저장하고 embedding/index를 만든다. MCP에서는 주제를 정의해 비동기 content 생성/refresh를 시작한다. 독립 조회는 저장된 요약을 읽는 것이고, refresh는 다시 reflect를 수행한다. [소스: H-model-create] [문서: H-model-doc]
5. **Full/delta와 observation을 구분한다.** full은 live facts로 재생성, delta는 기존 페이지를 유지하며 변경 부분을 편집하고 이전 `based_on`을 ID로 누적 dedup한다. 현재 코드에는 사라진 source fact를 감지하는 `live_memory_ids`/retraction 처리 및 consolidation pending 시 지연도 있다. auto observations와 사용자가 질문/trigger를 정하는 pinned mental model은 같은 층이 아니다. “LLM이 자기 경험을 영구 학습한다”는 표현보다 “근거가 연결된 fact·consolidated observations·living summaries를 유지한다”가 구현에 가깝다. [소스: H-model-delta] [문서: H-model-doc]

**[추론] 적용 가치:** 코딩 규칙/사용자 선호/장기 의사결정을 모델 변경 후에도 부트스트랩하는 데 living summaries가 유용하다. 그러나 summary가 원본 fact보다 높은 신뢰도를 자동 획득하는 것은 아니며 reviewer가 읽을 memory scope와 생성 agent write scope를 분리해야 한다.

### 5.2 Graphiti: 시간·출처가 붙은 entity/fact graph를 incremental로 만든다

- **원본은 episode다.** `add_episode` 경로는 extracted nodes를 resolve/dedup하고, extracted edges를 resolve하며 새 facts와 invalidated edges를 합쳐 저장한다. node attributes/summaries도 갱신한다. “문서를 검색하는 graph RAG”에 그치지 않고 변경 사실을 시간창과 함께 다루는 엔진이다. 단, extraction/dedup/invalidation은 LLM 판단이 들어가는 추정이고 사실의 진위 인증은 아니다. [소스: G-ingest] [문서: G-readme]
- **Fact edge 자체에 provenance와 시간이 있다.** 저장 dict는 `episodes`, `created_at`, `expired_at`, `valid_at`, `invalid_at`, `reference_time`를 유지한다. ingestion/transaction time 계열과 event-validity 계열의 구분을 코드에서 확인할 수 있다. [소스: G-edge]
- **Recall에 해당하는 공개 동작은 hybrid graph search다.** `Graphiti.search`는 vector/text hybrid configuration을 쓰고 일반 RRF 또는 center-node distance reranking을 선택해 `EntityEdge`들을 반환한다. `search_`가 더 풍부한 설정 surface다. 이는 Hindsight `reflect`처럼 답변을 여러 retrieval tool로 작성하는 독립 reflection 서비스와 다르다. [소스: G-search]
- **Community/saga summaries ≠ Hindsight mental models.** Graphiti MCP는 communities/saga summary 도구를 제공하지만, 사용자 질문으로 지속 page를 pin하고 trigger/full/delta로 refresh하는 Hindsight 계약과 동일한 기능이라고 표기하면 안 된다. API에 `reflect`가 없다는 사실이 지능이나 추론이 전혀 없다는 의미도 아니다. [문서/소스: G-mcp] [G-readme]
- **OSS Graphiti ≠ Zep 운영 엔진.** 현재 README는 Zep이 proprietary Context Graph Engine을 사용한다고 명시한다. Graphiti의 Neo4j/FalkorDB 성능이나 백업 능력으로 hosted Zep의 SLA/격리를 증명할 수 없다. [문서: G-readme]

## 6. 소스에서 보이는 위험 4건: 조건과 영향 범위를 제한해서 읽기

### 위험 1 — 기본 tenant·API key를 auth/ACL로 착각

[소스] Hindsight 기본 extension은 모든 요청을 통과시키고 같은 public schema를 반환한다. simple API-key extension도 한 schema로 귀결되며 그 key만으로 사용자별 bank ACL을 만들어주지 않는다. archived Mem0 wrapper의 `MEM0_DEFAULT_USER_ID` 기본값은 `mem0-mcp`다. **동일 backend key+기본 scope로 여러 사용자/호스트를 연결하면 의도치 않은 기억 공유가 생길 수 있다 [추론].** hosted Mem0가 기본적으로 다른 계정의 데이터를 노출한다는 주장이나, Cloud Hindsight도 무인증이라는 주장은 아니다. [H-tenant] [M-old-scope]

현행 Cavira LongMemory도 API key가 없으면 `authorize`가 즉시 반환한다. Honcho의 **예제** compose에는 postgres/postgres와 `POSTGRES_HOST_AUTH_METHOD=trust`가 있다. 이는 sample/development deployment 경고이지 hosted 서비스 취약점 확인이 아니다. 인터넷 운영에서는 실제 key·ACL·DB network restriction이 선행되어야 한다. [CV-auth] [HO-compose]

### 위험 2 — Graphiti UUID 조회/삭제의 group scope는 인증 주체와 연결되지 않음

[소스] MCP `get_entity_edge`/`delete_entity_edge`는 client-supplied `group_id`로 driver를 골라 UUID 조회를 한다. `_driver_for_group`은 FalkorDB graph를 나누지만 다른 backend에서는 clone이 no-op일 수 있다고 설명한다. `EntityEdge.get_by_uuid`의 기본 Cypher는 **UUID predicate만 있고 group predicate가 없다**. [G-id-tools] [G-scope-driver] [G-edge]

**[추론] 조건부 IDOR 위험:** 같은 graph DB를 tenant가 공유하고 외부 gateway가 UUID 소유권을 검사하지 않는 deployment에서, 다른 group의 UUID를 알아낸 호출자가 조회/삭제할 가능성이 있다. UUID 추측 성공, 현재 hosted Zep 공격 성공, 전 backend에서 cross-tenant 접근을 실증한 것이 아니다. search의 `group_ids` 필터만 검사하고 UUID getter/deleter를 놓치지 않아야 한다.

### 위험 3 — forget/delete 성공은 원본·파생 상태·백업의 물리 삭제가 아님

- [소스] Mem0 OSS `_delete_memory`는 vector를 지운 뒤 **이전 text를 SQLite history의 DELETE 이벤트에 기록**한다. retrieval 제거와 PII 완전 삭제는 다른 계약이다. [M-delete]
- [소스/문서] Supermemory MCP forget는 supplied content를 의미 검색한 preview의 **첫 match**를 ID로 forget한다. 공식 문서는 memory forget를 soft-delete라고 설명한다. ID 확인·사용자 승인 없이 근접한 다른 기억이 대상이 될 수 있으며 [추론], physical purge나 source document 삭제를 이 응답으로 증명할 수 없다. [S-forget] [S-forget-doc]
- [소스] Graphiti `remove_episode`는 nodes에 mention count를 쓰지만 edges에는 `edge.episodes[0] == episode.uuid`로 삭제 여부를 정한다. 이것은 MCP docstring의 “다른 episode가 지원하는 facts 보존” 설명보다 좁지 않은 삭제 조건이다. 첫 원본을 지울 때 여러 원본이 지원하던 fact의 처리 및 node/community summary 잔존 여부는 별도 확인 대상이다. **삭제 전후 실험은 하지 않았다.** [G-remove] [G-id-tools]
- [소스] Hindsight는 retraction/refresh 처리가 있지만 consolidation이 pending이면 정정을 늦춘다. 즉 기반 fact 삭제와 derived living summary 갱신의 시점이 같다고 보장하면 안 된다. [H-model-delta]

### 위험 4 — 대화 원문과 주변 문맥이 모델/provider로 전달되는 경계

[소스] 현재 Mem0 inference 경로는 제출 `messages`를 parse하고 이전 session 메시지 최대 10개와 기존 검색 memory를 extraction prompt에 넣어 설정 LLM을 호출한다. 사용자가 전체 transcript를 messages로 제출하면 그 내용도 extraction input이 된다. “정제된 fact만 클라우드/LLM에 간다”는 가정은 성립하지 않는다. **모든 host plugin이 무조건 전체 transcript를 전송한다는 주장은 아니다**. 입력 선택·secret redaction·tool-output 제한은 연결 방식별로 따로 검토해야 한다. [M-add]

[문서] Supermemory local은 local embeddings/LLM로 text 처리를 오프라인에 둘 수 있지만 URL ingestion은 hosted reader, telemetry는 별도 opt-out이라고 명시한다. “local binary라서 모든 네트워크 전송이 없다”는 주장도 틀리다. 또한 pinned configuration 문서는 v0.0.8의 all-interface/implicit local auth 경고를 담고, overview는 v0.0.9 이상을 요구하므로 **문서의 release 표현이 불일치**한다. 버전을 확인하지 않고 현재 배포 모두 취약하다고 단정하지 않는다. [S-local] [S-local-auth]

## 7. 도입 shortlist와 탈락/유보 사유

**[추론] 최신 요구에서는 “회사 로컬/집 개인 클라우드에 같은 OSS 엔진을 독립 배포”하는 경로를 우선하고, managed는 집 개인환경의 선택지로 한정한다.** 다음 4개는 같은 프로토콜·동일 평가 데이터·동일 recall budget의 후보지만 hosted/OSS 내부 구현의 완전 동등성은 보장하지 않는다. 실제 도입을 수행하거나 성능 승자를 선언한 것은 아니다.

1. **Hindsight 동일 OSS engine의 local/self-host cloud** — 회사 로컬과 집 개인 클라우드에 코드/도메인 계약을 최대한 공통화하는 1순위. 단일 엔진의 pg0 개발 배포와 external PostgreSQL 운영 배포, local/cloud inference adapters를 선택할 수 있다. 회사 업무의 운영 배포도 pg0 편의 예제를 생산운영 보증으로 오인하지 않는다. auth/권한·출력 tracing·network egress 정책은 환경별 독립으로 둔다. managed Hindsight Cloud는 개인환경의 별도 선택지이지 같은 배포 구성이라는 증거가 아니다. [H-mcp] [H-reflect] [H-export] [H-portable-config] [H-install]
2. **Mem0 OSS / 개인환경의 official hosted MCP** — OSS 엔진을 양쪽에 self-host하면 코드 공통화는 가능하지만, 공식 hosted Platform/MCP와 OSS의 알고리즘/기능을 동일시하지 않는다. 운영면적을 줄이는 개인환경 managed 후보는 현재 hosted endpoint이며 archive wrapper를 새 서버 중심으로 선택하지 않는다. v3 ADD-only의 current-vs-past 영향, raw input/history retention, full export fidelity를 확인한다. 회사 로컬에는 local LLM+embedding과 `MEM0_TELEMETRY=false`가 별도 조건이다. [M-host-mcp] [M-old-mcp] [M-add] [M-export] [M-telemetry] [M-ollama] [M-ollama-embed]
3. **Graphiti OSS MCP** — 프로젝트/task/claim/source/event/entity/artifact처럼 relation과 provenance·event-validity가 핵심인 요구에서 shortlist. video/schema와 이름이 유사하다는 것만으로 동일 구현이라는 증거는 없다. experimental MCP, graph 운영 부담, group-vs-principal 권한과 UUID 접근의 gap을 먼저 해결해야 한다. 일반 개인 preference 몇 개 저장만 필요하면 과한 선택이다. [G-readme] [G-mcp] [G-edge] [G-id-tools]
4. **Supermemory current hosted MCP** — spaces/profile/문서 ingestion과 사용자-facing UX가 중요하고 비공개 engine·managed 의존성을 허용할 때. local binary를 MIT OSS 또는 drop-in managed MCP server로 오인하지 않는다. semantic forget 대신 정확한 target/삭제 계약이 필요한 요구를 먼저 검증한다. [S-mcp] [S-local] [S-forget]

**차순위/탈락:**

- **Cavira LongMemory:** 자체 클라우드 단일 persistent-disk 서버와 read-only reviewer boundary의 공개 구현은 매력적. 그러나 이번 요구에서 hard-forget/purge·full export·복수 replica 운영 및 managed 선택지를 확정하지 못해 top-4 다음. “로컬-first”라는 이름 때문에 클라우드 불가능으로 탈락시키는 것은 잘못이다. [CV-mcp] [CV-permission] [CV-readme]
- **Honcho:** reasoning-first peer memory가 중심이면 재평가. AGPL network-source 의무를 검토해야 하고 async deriver/representation의 삭제·이식 계약과 single-instance HTTP MCP 운영을 명확히 해야 한다. [HO-readme] [HO-mcp]
- **Cognee:** 광범위 company corpus/문서·코드 graph ingestion이 실제 요구로 추가되면 shortlist로 승격. 현 범위에서는 여러 storage 계층/processing lifecycle을 소유하는 비용이 크다. [C-readme] [C-graph] [C-vector] [C-relational]
- **LangMem:** 원하는 schema·정책을 직접 만드는 통제형 설계에는 적합하나 ready-made independent MCP를 선택하려는 목적에서는 추가 개발 책임이 많다. [LM-readme] [LM-tools]
- **Letta Code:** cross-device agent continuity 자체는 직접 지원하나 별도 stateful harness 도입이다. Claude/Codex를 그대로 쓰면서 memory만 독립시키는 요구에는 주 경로로 채택하지 않는다. [L-current]
- **Official reference / mem0ai OpenMemory archive:** reference 교육 서버 또는 유지보수 종료 snapshot. 새로운 클라우드 production memory backend 근거로는 부족하다. 현행 mem0ai OpenMemory porter는 다른 목적이다. [R-readme] [O-current] [O-archive]

### Agent Flow와의 영향 범위

[추론] 위 후보를 채택하더라도 Agent Flow core에 store·DB schema·memory lifecycle을 넣을 이유는 없다. memory MCP endpoint/auth/scope는 호스트에 연결하고, 회수된 내용은 출처·시각·scope를 표시한 **비신뢰 참고 데이터**로만 주입한다. reviewer에는 별도 read-only principal/tool set 또는 memory 미연결을 유지해야 한다. “공유 기억” 요구는 모든 에이전트가 모든 기억을 읽고 쓰라는 뜻이 아니다. 개인 preferences/project facts/agent-execution traces/reviewer context를 서로 다른 bank/namespace/권한으로 분리하는 것은 independent pipeline의 책임이다.

### 회사 로컬과 집 개인 클라우드: 같은 설계가 가능한 범위

**[추론] 가능하다. 다만 “같은 code/schema/domain contract”는 가능해도 “같은 운영 topology·모델 출력·보안 경계”까지 동일할 수는 없다.** 업무와 개인은 서로 다른 deployment/trust domain으로 두고, 개인 cloud agent가 회사 endpoint/DB/키에 접근하는 경로를 만들지 않는다. 비교 평가에 같은 synthetic/public corpus를 사용할 수 있다는 뜻이지 업무 memory를 개인 cloud로 복사하라는 뜻이 아니다.

| 층 | 공통화할 것 | 반드시 분리하거나 adapter로 선택할 것 |
|---|---|---|
| 도메인/API | fact/document ID, provenance, event/recorded time, CRUD/forget/export status, retrieval budget·error 계약, schema migrations, MCP tool schema | 업무 tenant/project identity와 개인 identity, reviewer 권한, retention 정책. 같은 문자열 `default`/`main`도 물리 환경이 다르면 다른 memory여야 함 |
| 저장 엔진 | 동일 OSS version·동일 DB family를 선택하면 최대 공통화 가능 | 업무 local DB/volume/backup와 개인 managed DB/backup/key. 다른 backend를 고르면 transaction/search/index semantics 검증 필요 |
| 모델 | 동일 prompt·extraction schema·embedding dimensions/rerank interface | 업무 local approved LLM/embedding/reranker vs 개인 cloud/local provider. 다른 모델은 extracted facts·dedup·반박 처리·요약·순위가 달라질 수 있음 |
| MCP transport/auth | 같은 tools/result schema, resource naming, scope enforcement policy | 회사 stdio/loopback/private HTTP vs 집 TLS remote HTTP, credential issuance/rotation·network gateway·session lifetime |
| 운영 | common version pin/migration/backup-restore playbook의 계약 | single machine vs API/worker/DB 분리, queue/concurrency, GPU, monitoring sink·egress allowlist, 장애·비용·RPO/RTO |
| 데이터 이동 | export/import 포맷을 양쪽 엔진에서 구현할 수 있음 | **회사→개인 자동 sync 없음**. cross-device 공유는 개인 trust domain 내부에서만; 업무 반출은 별도 회사 승인·redaction·감사 절차 없이 수행하지 않음 |

#### 후보별 실제 portable engine 근거

- **Hindsight:** source default DB는 `pg0`, embedding/reranker는 local이며 LLM은 기본 OpenAI다. 문서는 pg0가 embedded PostgreSQL이고 production에는 external PostgreSQL을 권고한다. full container는 embedding/reranker를 포함하지만 **LLM 자체는 별도 서비스**이고 Ollama/LM Studio/vLLM 등 local endpoint도 외부 프로세스로 연결한다. 따라서 local DB만 바꿔서 오프라인이 되는 것이 아니며 extraction/reflect/consolidation, embedding, reranker, OCR/URL 처리의 모든 egress 경로를 확인해야 한다. 모델은 첫 실행에 HuggingFace에서 다운로드하므로 air-gap은 artifacts 사전 반입/고정이 필요하다. [소스: H-portable-defaults] [문서: H-install] [H-models] [H-portable-config]
- **Graphiti:** MCP config는 FalkorDB/Neo4j와 OpenAI LLM/embedding을 기본으로 한다. factory는 local OpenAI-compatible endpoint를 감지해 `OpenAIGenericClient`를 쓰며 embedding custom endpoint도 지원한다. BGE fallback reranker는 optional dependency다. local/cloud 모두 **같은 graph backend를 유지**하면 코드 공통화가 쉬우나, FalkorDB→Neo4j 이동은 group routing·UUID 접근·검색/운영 semantics가 달라질 수 있어 backend change를 “설정만 바꾸면 동일”이라고 보장하지 않는다. 로컬 inference의 JSON/schema 준수와 entity/dedup/temporal extraction 품질도 별도 평가 대상이다. [G-portable-config] [G-portable-factory] [G-scope-driver]
- **Mem0 OSS:** local Ollama LLM/embedding source가 존재한다. embedding adapter는 모델이 없으면 pull을 수행하므로 network-isolated 환경에서는 사전 준비가 필요하다. OSS 엔진 양쪽 배포는 가능하나 hosted proprietary 최적화와 같은 엔진이라는 주장은 하지 않는다. Python history/messages SQLite와 vector DB가 함께 유지돼야 하므로 vector DB만 cloud-ready로 바꿔 state migration이 끝났다고 보면 안 된다. [M-ollama] [M-ollama-embed] [M-core] [M-readme]
- **Cognee:** local small-model extraction+embedding 모드가 있지만 첫 실행 모델 다운로드가 있으며 optional LLM 사용은 provider 호출을 만든다. SQLite/LanceDB/Ladybug 기반 회사 local과 PostgreSQL/Neo4j 기반 개인 cloud를 섞는 경우 adapter/backup·query differences를 소유해야 한다. [C-readme] [C-graph] [C-vector] [C-relational]
- **Cavira LongMemory:** 같은 TS engine+SQLite+MCP를 local/개인 persistent-disk server에 배포하는 일관성은 장점이다. 그러나 single-disk topology에서 managed scale-out로 바뀌는 것은 README 플랫폼 예제만으로 보장되지 않는다. 관리형 endpoint가 꼭 필요한 요구와 engine 소유 요구를 분리한다. [CV-readme] [CV-mcp]
- **Supermemory:** local binary는 비공개 engine, managed MCP는 platform-only다. “local과 cloud가 같은 API”라는 vendor 설명은 있지만 같은 공개 code를 양쪽에 운영하는 요구에는 맞지 않는다. local binary+custom MCP와 hosted MCP를 사용하면 프로토콜은 맞출 수 있어도 운영/내부 추론/권한 모델 동일성을 감사할 수 없다. **회사 local/집 cloud의 완전 공통 엔진 요구에서는 priority 하향**, 개인 managed UX 후보로만 남긴다. [S-local] [S-enterprise]

#### 로컬 저장과 오프라인·telemetry는 다른 요구다

| 제품 | 확인된 기본값/경계 | 업무 local profile에 필요한 판단 |
|---|---|---|
| Hindsight | [소스/문서] embedding/reranker local, LLM default OpenAI. 외부 OTEL traces는 기본 false지만 **DB LLM request tracing은 기본 true**, 1일 retention/입출력 최대 50,000 chars | approved local inference+미리 준비한 모델; 민감 prompt/output DB 복제·backup도 데이터 취급. 필요 시 `HINDSIGHT_API_LLM_TRACE_ENABLED=false`; OTEL/HTTP debug/log sink 별도 정책. 외부 telemetry가 모두 없다고 검증한 것은 아님. [H-portable-defaults] [H-portable-config] [H-trace] [H-otel] |
| Graphiti | [소스] anonymous usage telemetry 기본 enabled; config default LLM/embedder OpenAI. PostHog public ingestion key는 사용자 secret API key가 아님 | `GRAPHITI_TELEMETRY_ENABLED=false`, local LLM/embedding/reranker, model prefetch와 no-egress 검증. 수집 “usage metadata”와 전체 transcript 전송을 동일시하지 않음. [G-telemetry] [G-portable-config] |
| Mem0 OSS | [소스] `MEM0_TELEMETRY` 기본 True, PostHog usage capture. Ollama embedding은 모델 부재 시 pull | `MEM0_TELEMETRY=false`, approved local adapters와 artifacts, raw messages/history retention까지 검토. [M-telemetry] [M-ollama-embed] |
| Cognee | [소스] `TELEMETRY_DISABLED`가 설정되면 전송 중지, dev/test 환경도 생략; 그 외 event/identity metadata payload 경로 존재 | `TELEMETRY_DISABLED=true` 등 환경별 정책, local models 준비·URL/connectors/LLM의 egress를 별도 검사. [C-telemetry] [C-readme] |
| Supermemory local | [문서] telemetry opt-out, URL은 hosted reader, local model 최초 다운로드, binary release/auth 문서 불일치 | `SUPERMEMORY_DISABLE_TELEMETRY=1`만으로 URL 외부 전송까지 막는 것은 아님. text/local file+local LLM 조건과 binary version/라이선스·auth 검증 필요. [S-local] [S-local-auth] |

**[추론] 업무 end-to-end offline이 필요하면 호스트 모델도 별도 조건이다.** memory pipeline만 로컬이어도 회사 업무를 Claude Code/Codex의 원격 모델에 보내면 전체 워크플로는 local-only가 아니다. 여기서는 호스트/구독/회사 승인 정책을 변경하지 않으며, “로컬 memory”와 “업무 입력이 외부 모델에 전혀 전송되지 않는 업무 환경”을 구분한다. backend 장애 시 회사 요청을 개인 cloud로 자동 fallback하는 경로는 두지 않는다.

### 최신 조건의 도입 결론

**[추론] 동일 OSS Hindsight version+PostgreSQL family를 회사 로컬과 집 개인 클라우드에 완전히 독립 배포하는 설계를 우선 검토**한다. pg0는 개발 편의 옵션, 업무 production은 local external PostgreSQL도 가능하다. topology·모델 provider·auth/observability만 deployment adapters로 나누고, facts/provenance/scope/delete/export 도메인 계약은 공통화한다. Graphiti가 필요한 관계/시간 요구를 더 잘 충족하면 같은 backend로 양쪽 배포를 검토하되 auth gap과 파생 삭제 계약을 먼저 해결한다. managed Mem0/Supermemory는 개인환경의 선택지이며 **회사 local과 동일 내부 구현·운영을 요구하는 경로에서는 동등 대체가 아니다**.

## 8. 미확인 사항과 이후 검증 항목

다음은 수행 결과가 아니라 **이후 도입 승인 전 요구할 증거**다.

- 원문→fact→observation/profile/community/mental-model→history→backup의 삭제/retention map, hard purge 완료의 audit evidence.
- 같은 사용자 두 기기·두 host·한국어/영어 입력의 stable identity, upsert idempotency, “현재 vs 예전” 답변, source citation 정확도.
- tenant A가 tenant B의 bank/group/namespace/UUID를 넘긴 경우 get/search/update/delete/export 모두 거부되는지. reviewer credential로 write가 불가능한지.
- long-lived HTTP/session reconnect·process restart·worker retry·processing-after-read 일관성, namespace/scope의 서버 강제 여부.
- logical export→새 인스턴스 import 후 facts/provenance/config/파생 state의 fidelity; embedding 모델 변경 시 재색인 비용. 서비스의 백업 RPO/RTO와 export는 별도 계약.
- 동일 입력·모델·budget·한국어 corpus를 사용한 recall quality/temporal contradiction/삭제 누수 및 비용·p50/p95 측정. 업체 간 서로 다른 benchmark 숫자를 같은 축으로 순위화하지 않기.
- managed data region/subprocessor/LLM vendor retention·DPA·약관·가격 및 vendor 폐업/키 분실 시 접근 경로. 본 조사에서 계약상 보장을 확정하지 않았다.
- 현재 source snapshot과 실제 배포 version 확인. 특히 renamed/archive 제품, Supermemory local docs의 release 불일치, hosted proprietary engine 변경은 SHA로도 runtime 동일성을 증명하지 못한다.

현재 결론의 확신도: repo metadata/공개 source 동작 **높음**, 공식 API 문서상의 지원 **중간~높음**, 실제 hosted isolation·운영 신뢰도·한국어 품질·성능 우열 **미검증**. 이 문서는 딥리서치 evidence이고 Opus/Codex 적대적 실행 리뷰를 대신한 보고서가 아니다.

## 고정 원문 링크

[H-readme]: https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/README.md
[H-mcp]: https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-api-slim/hindsight_api/api/mcp.py#L114-L197
[H-tenant]: https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-api-slim/hindsight_api/extensions/builtin/tenant.py#L8-L90
[H-recall]: https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-api-slim/hindsight_api/engine/search/retrieval.py#L100-L240
[H-retrieval-doc]: https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-docs/docs/developer/retrieval.md#L25-L108
[H-reflect]: https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-api-slim/hindsight_api/engine/memory_engine.py#L15545-L15598
[H-reflect-tools]: https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-api-slim/hindsight_api/engine/reflect/tools.py#L118-L146
[H-model-create]: https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-api-slim/hindsight_api/engine/memory_engine.py#L17077-L17159
[H-model-delta]: https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-api-slim/hindsight_api/engine/memory_engine.py#L17575-L17646
[H-model-doc]: https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-docs/docs/developer/mcp-server.md#L270-L400
[H-export]: https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-api-slim/hindsight_api/engine/transfer/export.py#L55-L127
[H-upsert]: https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-api-slim/hindsight_api/engine/memory_engine.py#L6380-L6410
[H-stdio]: https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-integrations/claude-code/scripts/mcp_server.py
[M-readme]: https://github.com/mem0ai/mem0/blob/b7ad69afda6b6ed030347c66d48a13e4de9dec08/README.md
[M-core]: https://github.com/mem0ai/mem0/blob/b7ad69afda6b6ed030347c66d48a13e4de9dec08/mem0/memory/main.py#L487-L501
[M-add]: https://github.com/mem0ai/mem0/blob/b7ad69afda6b6ed030347c66d48a13e4de9dec08/mem0/memory/main.py#L918-L1045
[M-crud]: https://github.com/mem0ai/mem0/blob/b7ad69afda6b6ed030347c66d48a13e4de9dec08/mem0/memory/main.py#L1829-L1960
[M-delete]: https://github.com/mem0ai/mem0/blob/b7ad69afda6b6ed030347c66d48a13e4de9dec08/mem0/memory/main.py#L2114-L2140
[M-auth]: https://github.com/mem0ai/mem0/blob/b7ad69afda6b6ed030347c66d48a13e4de9dec08/server/auth.py#L144-L220
[M-compose]: https://github.com/mem0ai/mem0/blob/b7ad69afda6b6ed030347c66d48a13e4de9dec08/server/docker-compose.yaml
[M-export]: https://github.com/mem0ai/mem0/blob/b7ad69afda6b6ed030347c66d48a13e4de9dec08/docs/platform/features/memory-export.mdx
[M-host-mcp]: https://github.com/mem0ai/mem0/blob/b7ad69afda6b6ed030347c66d48a13e4de9dec08/docs/platform/mem0-mcp.mdx#L1-L119
[M-old-mcp]: https://github.com/mem0ai/mem0-mcp/blob/624024deacbbe1948572a968abdb9d9e93ded548/README.md
[M-old-scope]: https://github.com/mem0ai/mem0-mcp/blob/624024deacbbe1948572a968abdb9d9e93ded548/src/mem0_mcp_server/server.py#L64-L96
[G-readme]: https://github.com/getzep/graphiti/blob/964bb11d1e7020e3cc67fab244268b0736b6c219/README.md
[G-mcp]: https://github.com/getzep/graphiti/blob/964bb11d1e7020e3cc67fab244268b0736b6c219/mcp_server/README.md#L1-L29
[G-mcp-source]: https://github.com/getzep/graphiti/blob/964bb11d1e7020e3cc67fab244268b0736b6c219/mcp_server/src/graphiti_mcp_server.py#L403-L530
[G-search]: https://github.com/getzep/graphiti/blob/964bb11d1e7020e3cc67fab244268b0736b6c219/graphiti_core/graphiti.py#L1903-L1962
[G-ingest]: https://github.com/getzep/graphiti/blob/964bb11d1e7020e3cc67fab244268b0736b6c219/graphiti_core/graphiti.py#L1469-L1515
[G-edge]: https://github.com/getzep/graphiti/blob/964bb11d1e7020e3cc67fab244268b0736b6c219/graphiti_core/edges.py#L347-L405
[G-scope-driver]: https://github.com/getzep/graphiti/blob/964bb11d1e7020e3cc67fab244268b0736b6c219/mcp_server/src/graphiti_mcp_server.py#L191-L219
[G-id-tools]: https://github.com/getzep/graphiti/blob/964bb11d1e7020e3cc67fab244268b0736b6c219/mcp_server/src/graphiti_mcp_server.py#L695-L787
[G-remove]: https://github.com/getzep/graphiti/blob/964bb11d1e7020e3cc67fab244268b0736b6c219/graphiti_core/graphiti.py#L2164-L2192
[S-readme]: https://github.com/supermemoryai/supermemory/blob/709723dea69dba8340fc42c0aafd86a2b6a4a0f4/README.md
[S-mcp]: https://github.com/supermemoryai/supermemory/blob/709723dea69dba8340fc42c0aafd86a2b6a4a0f4/apps/mcp/README.md#L1-L88
[S-auth]: https://github.com/supermemoryai/supermemory/blob/709723dea69dba8340fc42c0aafd86a2b6a4a0f4/apps/mcp/src/server/auth/index.ts#L108-L188
[S-forget]: https://github.com/supermemoryai/supermemory/blob/709723dea69dba8340fc42c0aafd86a2b6a4a0f4/apps/mcp/src/server/client/index.ts#L210-L238
[S-forget-doc]: https://github.com/supermemoryai/supermemory/blob/709723dea69dba8340fc42c0aafd86a2b6a4a0f4/apps/docs/recall/memory-operations.mdx#L1-L119
[S-updates]: https://github.com/supermemoryai/supermemory/blob/709723dea69dba8340fc42c0aafd86a2b6a4a0f4/apps/docs/snippets/api-v5-document-updates.mdx
[S-local]: https://github.com/supermemoryai/supermemory/blob/709723dea69dba8340fc42c0aafd86a2b6a4a0f4/apps/docs/self-hosting/overview.mdx
[S-local-auth]: https://github.com/supermemoryai/supermemory/blob/709723dea69dba8340fc42c0aafd86a2b6a4a0f4/apps/docs/self-hosting/configuration.mdx
[S-enterprise]: https://github.com/supermemoryai/supermemory/blob/709723dea69dba8340fc42c0aafd86a2b6a4a0f4/apps/docs/self-hosting/local-vs-enterprise.mdx
[S-old]: https://github.com/supermemoryai/supermemory-mcp/blob/84f5dc9f1cf077ba753decbf56805205b5c0443a/README.md#L1-L39
[L-old]: https://github.com/letta-ai/letta/blob/5bcdd177d70fa2b31a754cfcd801e77b2e1ab16a/README.md
[L-current]: https://github.com/letta-ai/letta-code/blob/271f119dcf37d58649a18e6c733386b3c710a456/README.md#L15-L101
[L-store]: https://github.com/letta-ai/letta-code/blob/271f119dcf37d58649a18e6c733386b3c710a456/src/backend/local/local-store.ts
[L-memfs]: https://github.com/letta-ai/letta-code/blob/271f119dcf37d58649a18e6c733386b3c710a456/src/agent/memory-filesystem.ts
[LM-readme]: https://github.com/langchain-ai/langmem/blob/48e3c11f5bb527282c7d5339c6a87a0b35abccfc/README.md
[LM-tools]: https://github.com/langchain-ai/langmem/blob/48e3c11f5bb527282c7d5339c6a87a0b35abccfc/src/langmem/knowledge/tools.py#L263-L337
[LM-reflect]: https://github.com/langchain-ai/langmem/blob/48e3c11f5bb527282c7d5339c6a87a0b35abccfc/src/langmem/reflection.py#L110-L140
[C-readme]: https://github.com/topoteretes/cognee/blob/0ec7a9fa61c9ff04bf7e02e0d57af363a993a5e1/README.md
[C-mcp]: https://github.com/topoteretes/cognee/blob/0ec7a9fa61c9ff04bf7e02e0d57af363a993a5e1/cognee-mcp/README.md
[C-forget]: https://github.com/topoteretes/cognee/blob/0ec7a9fa61c9ff04bf7e02e0d57af363a993a5e1/cognee-mcp/src/server.py#L714-L787
[C-graph]: https://github.com/topoteretes/cognee/blob/0ec7a9fa61c9ff04bf7e02e0d57af363a993a5e1/cognee/infrastructure/databases/graph/config.py#L45-L87
[C-vector]: https://github.com/topoteretes/cognee/blob/0ec7a9fa61c9ff04bf7e02e0d57af363a993a5e1/cognee/infrastructure/databases/vector/config.py#L13-L53
[C-relational]: https://github.com/topoteretes/cognee/blob/0ec7a9fa61c9ff04bf7e02e0d57af363a993a5e1/cognee/infrastructure/databases/relational/config.py#L11-L32
[C-export]: https://github.com/topoteretes/cognee/blob/0ec7a9fa61c9ff04bf7e02e0d57af363a993a5e1/cognee/api/v1/export/export.py#L49-L99
[R-readme]: https://github.com/modelcontextprotocol/servers/blob/c003d0d807409b22fa640d1f8e11f38f15755721/README.md#L1-L14
[R-memory]: https://github.com/modelcontextprotocol/servers/blob/c003d0d807409b22fa640d1f8e11f38f15755721/src/memory/index.ts#L587-L682
[R-license]: https://github.com/modelcontextprotocol/servers/blob/c003d0d807409b22fa640d1f8e11f38f15755721/LICENSE#L1-L18
[O-current]: https://github.com/mem0ai/openmemory/blob/2df78cc48e5f688a771fee5b39899325accc2450/README.md
[O-archive]: https://github.com/mem0ai/openmemory/blob/2df78cc48e5f688a771fee5b39899325accc2450/openmemory-archive/README.md#L1-L16
[HO-readme]: https://github.com/plastic-labs/honcho/blob/3922af856d78ec41133916deec4d821fa9c5a92e/README.md
[HO-mcp]: https://github.com/plastic-labs/honcho/blob/3922af856d78ec41133916deec4d821fa9c5a92e/mcp/README.md
[HO-models]: https://github.com/plastic-labs/honcho/blob/3922af856d78ec41133916deec4d821fa9c5a92e/src/models.py#L213-L352
[HO-compose]: https://github.com/plastic-labs/honcho/blob/3922af856d78ec41133916deec4d821fa9c5a92e/docker-compose.yml.example#L112-L128
[CV-readme]: https://github.com/CaviraOSS/LongMemory/blob/9ee2c8e1ed42d83eb788afb9ffc3a82b84405da5/README.md
[CV-mcp]: https://github.com/CaviraOSS/LongMemory/blob/9ee2c8e1ed42d83eb788afb9ffc3a82b84405da5/docs/mcp.md#L45-L133
[CV-permission]: https://github.com/CaviraOSS/LongMemory/blob/9ee2c8e1ed42d83eb788afb9ffc3a82b84405da5/src/mcp/security/permissions.ts#L21-L84
[CV-auth]: https://github.com/CaviraOSS/LongMemory/blob/9ee2c8e1ed42d83eb788afb9ffc3a82b84405da5/src/server/middleware/auth.ts#L26-L32
[CV-app]: https://github.com/CaviraOSS/LongMemory/blob/9ee2c8e1ed42d83eb788afb9ffc3a82b84405da5/src/server/app.ts#L124-L145
[H-portable-config]: https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-docs/docs/developer/configuration.mdx
[H-portable-defaults]: https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-api-slim/hindsight_api/config.py
[H-install]: https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-docs/docs/developer/installation.md
[H-models]: https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-docs/docs/developer/models.mdx
[H-trace]: https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-docs/docs/developer/configuration.mdx#L2553-L2566
[H-otel]: https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-docs/docs/developer/configuration.mdx#L2613-L2631
[G-portable-config]: https://github.com/getzep/graphiti/blob/964bb11d1e7020e3cc67fab244268b0736b6c219/mcp_server/config/config.yaml
[G-portable-factory]: https://github.com/getzep/graphiti/blob/964bb11d1e7020e3cc67fab244268b0736b6c219/mcp_server/src/services/factories.py
[G-telemetry]: https://github.com/getzep/graphiti/blob/964bb11d1e7020e3cc67fab244268b0736b6c219/graphiti_core/telemetry/telemetry.py
[M-telemetry]: https://github.com/mem0ai/mem0/blob/b7ad69afda6b6ed030347c66d48a13e4de9dec08/mem0/memory/telemetry.py#L14-L23
[M-ollama]: https://github.com/mem0ai/mem0/blob/b7ad69afda6b6ed030347c66d48a13e4de9dec08/mem0/llms/ollama.py
[M-ollama-embed]: https://github.com/mem0ai/mem0/blob/b7ad69afda6b6ed030347c66d48a13e4de9dec08/mem0/embeddings/ollama.py
[C-telemetry]: https://github.com/topoteretes/cognee/blob/0ec7a9fa61c9ff04bf7e02e0d57af363a993a5e1/cognee/shared/utils.py#L602-L632
