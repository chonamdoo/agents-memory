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