# 참고 OSS의 DB 증가·오래된 데이터 대책 — 2026-10-15

## 결론

**실제로 해결한 사례가 있다. 가장 유용한 것은 무조건적인 ‘오래된 기억 삭제’가 아니라 저장 증폭 방지, 파생 데이터 GC, 제한된 유지보수, backup 보존 정책이다.**

1. **생성 원인부터 줄이기:** claude-mem의 불필요한 FTS·재색인 제거와 vector ID 갱신, Hindsight의 obsolete index·중복 archive embedding 제거.
2. **복구 가능한 상태와 폐기 가능한 이력 분리:** Engram의 scoped dead-letter 정리, Hindsight의 opt-in operation retention, Quivr의 재개 가능한 projection cleanup.
3. **삭제 전에 소유권·재시도 근거 보존:** Basic Memory·Cognee·WeKnora·OpenKB의 파생물/외부 객체 정리 순서.
4. **snapshot으로 복구 가능한 이력만 축소:** OpenViking의 snapshot-covered recovery delta 정리. 우리 삭제 journal에 그대로 적용하면 안 된다.
5. **실제 파일과 backup까지 별도로 관리:** MemPalace의 명시 SQLite compact·backup 개수 제한. logical row 감소, WAL checkpoint, OS 공간 반환, backup 만료는 서로 다른 결과다.
6. **semantic consolidation은 뒤로:** 원본·요약·버전·관계가 함께 남으면 DB가 오히려 커질 수 있다. 조건·예외·부정·거절 근거를 버리는 요약은 우리 authority ledger에 부적합하다.

이번 결과는 **조사·제안**이다. 새 health subsystem, 자동 audit/model 호출, transcript 수집, retention/purge/backup 삭제, 새 DB/검색 엔진을 구현하거나 켜지 않았다. 기존 로컬 운영 복구 변경과 구분한다.

## 조사 범위와 증거 수준

[통합 이슈 #5](https://github.com/chonamdoo/agents-memory/issues/5)에서 참고했던 후보를 [기존 86항목 inventory](2026-10-15-oss-local-runtime.ko.md#전체-후보-판정표)에 따라 DB·persistent storage 관련성으로 분류했다. 86은 고유 DB 제품 수가 아니며 동명 프로젝트·malformed alias·retired wrapper·문서/벤치·비공개 backend도 포함한다. `claude-mem`과 관련 storage 후보를 네 read-only 조사로 나눠 pinned 코드와 공개 이슈·PR을 대조했다. 파일/KV/index 제품을 SQL DB라고 부르지 않았다.

- **코드:** 아래 permalink의 고정 SHA 기준. 원문 구현과 실제 호출/기본값을 확인했다.
- **이슈/PR:** 2026-10-15 조사 시점 상태. closed, merged, 현재 pin에 존재, 배포된 바이너리 검증은 다르다. 핵심 PR 10건은 parent가 GitHub API의 `merged_at`·merge SHA를 추가 확인했다.
- **실행:** upstream 프로젝트 설치·build·test·benchmark는 하지 않았다. 아래 별도 PG/SQLite 실험은 우리 소유의 합성 저장소 의미 확인이지 upstream 성능 재현이 아니다.
- **라이선스:** 기존 inventory의 pinned 조건 유지. 코드/fixture/데이터 복사·새 의존성 추가 없음. AGPL·Elastic License·fair-code·미확인 라이선스는 개념 참고만 한다.

## 1. 실제 해결 사례

| 프로젝트·증가 원인 | 구현된 해결책·상태 | 남은 한계와 우리 적용 판단 |
|---|---|---|
| **claude-mem — FTS delete marker·불필요한 재색인** | [#3284 merged](https://github.com/thedotmack/claude-mem/pull/3284), merge `277e15b9`. v54가 사용하지 않는 prompt FTS를 제거하고 text column 변경 때만 trigger를 실행. 기존 FTS는 startup 밖에서 단계적 merge. [migration](https://github.com/thedotmack/claude-mem/blob/fef3402e674bebbf72a23aeb735e91c92cd34afd/src/services/sqlite/SessionStore.ts#L2116-L2168)·[maintenance](https://github.com/thedotmack/claude-mem/blob/fef3402e674bebbf72a23aeb735e91c92cd34afd/src/services/infrastructure/FtsMaintenance.ts#L14-L119) | PR 제목의 periodic optimize보다 현재 구현이 정본이다. FTS merge와 OS 파일 축소는 별개. marker는 완료 전 ‘started’에 기록되므로 중단 후 자동 재개를 보장하지 않는다. **재색인 증폭부터 제거하는 원칙 참고.** |
| **claude-mem — deterministic vector ID 재시도의 HNSW churn** | [#3268 merged](https://github.com/thedotmack/claude-mem/pull/3268), merge `08941fd6`. delete→add 대신 존재 ID update, 신규 ID는 별도 add. [mixed batch](https://github.com/thedotmack/claude-mem/blob/fef3402e674bebbf72a23aeb735e91c92cd34afd/src/services/sync/ChromaSync.ts#L769-L825) | 과거 index bloat 회수는 별도 offline maintenance다. blanket update는 없는 ID를 빠뜨릴 수 있다. **우리 stable-key/idempotency 유지; Chroma 도입 근거 아님.** |
| **claude-mem — raw tool I/O 누적** | [#4701 merged](https://github.com/thedotmack/claude-mem/pull/4701). observation이 실제 남아 있는 linked old tool row만 opt-in startup purge. [retention](https://github.com/thedotmack/claude-mem/blob/fef3402e674bebbf72a23aeb735e91c92cd34afd/src/services/sqlite/tool-uses.ts#L493-L548) | 기본 retention 0=영구 보존. unlinked/orphan-linked rows는 이 정책으로 정리되지 않는다. 64KiB 필드 cap은 row 수 cap이 아니다. **원문이 정말 중복인지 reference로 확인하는 원칙만 참고.** |
| **Engram — 전송 대상 없는 journal과 terminal dead rows** | [#1157 merged](https://github.com/Gentleman-Programming/engram/pull/1157), merge `980aa624`: 미등록 project journal 생성 억제·session upsert coalesce, 삭제 intent 보존. [#1783 merged](https://github.com/Gentleman-Programming/engram/pull/1783), merge `a451f0e2`: age+scope count cap, 기본 dry-run, recoverable retry exclusion. [journal](https://github.com/Gentleman-Programming/engram/blob/82846a101296e75351ae444953438cace88e9bea/internal/store/store.go#L11345-L11425)·[prune](https://github.com/Gentleman-Programming/engram/blob/82846a101296e75351ae444953438cace88e9bea/internal/store/dead_row_prune.go#L11-L178) | 30일/1,000은 모든 backlog cap이 아니다. 대상 전체를 메모리에 모아 한 transaction에서 처리하며 500개 chunk는 SQL parameter 수만 제한한다. **terminal 운영 이력과 영구 rejection/floor를 분리; 전체 work/time bound는 별도 설계.** |
| **Basic Memory — stale/orphan vector·ignore 대상 index** | [#1363 merged](https://github.com/basicmachines-co/basic-memory/pull/1363): 명시 preview/confirm `prune`, 원본 파일은 건드리지 않음. [#1612 merged](https://github.com/basicmachines-co/basic-memory/pull/1612), merge `20b15234`: correlated orphan cleanup을 set-based 처리로 교체. [prune](https://github.com/basicmachines-co/basic-memory/blob/54b8d94b94cb8e4e526f438010ca771c5ad9f209/src/basic_memory/cli/commands/prune.py#L15-L115)·[vector GC](https://github.com/basicmachines-co/basic-memory/blob/54b8d94b94cb8e4e526f438010ca771c5ad9f209/src/basic_memory/repository/sqlite_vec_index.py#L308-L353) | canonical accepted content·파일·backup TTL이 아니다. 외부 vector 삭제 실패 전 ownership manifest를 지우지 않는 [순서](https://github.com/basicmachines-co/basic-memory/blob/54b8d94b94cb8e4e526f438010ca771c5ad9f209/src/basic_memory/repository/accepted_note_vector_cleanup.py#L111-L182)가 유용하다. **AGPL 코드 복사 없음.** |
| **Hindsight — parent JSON 이력·unused index·파생 embedding 복제** | [#2007](https://github.com/vectorize-io/hindsight/pull/2007) history 분리, [#3204](https://github.com/vectorize-io/hindsight/pull/3204) obsolete global index 제거·reconcile 재생성 방지, [#2210](https://github.com/vectorize-io/hindsight/pull/2210) cold archive embedding 제거 — 모두 merged. [history migration](https://github.com/vectorize-io/hindsight/blob/01e2878f44f41ff4ef0ab58a262c28dc90bae54f/hindsight-api-slim/hindsight_api/alembic/versions/a7b8c9d0e1f2_split_history_into_own_tables.py#L46-L149)·[index migration](https://github.com/vectorize-io/hindsight/blob/01e2878f44f41ff4ef0ab58a262c28dc90bae54f/hindsight-api-slim/hindsight_api/alembic/versions/f2a6d8c4b1e9_drop_stale_global_memory_units_vector_index.py#L1-L81) | per-item history50개는 총 byte cap이 아니며 우리 approval/rejection 이력에 적용할 수 없다. DROP COLUMN은 metadata-only라 즉시 heap 축소가 아니다. archive 복구 시 re-embedding은 추가 비용·egress일 수 있다. **측정 후 파생 데이터·증폭 제거 원칙 우선.** |
| **Hindsight — 거대한 retention DELETE가 foreground를 지연** | [#3539 merged](https://github.com/vectorize-io/hindsight/pull/3539), merge `0480f171`: stable cutoff, 2,000-row chunk, chunk별 transaction, SKIP LOCKED, pause, sweep ceiling. [maintenance](https://github.com/vectorize-io/hindsight/blob/01e2878f44f41ff4ef0ab58a262c28dc90bae54f/hindsight-api-slim/hindsight_api/engine/maintenance.py#L253-L420). [#2819 merged](https://github.com/vectorize-io/hindsight/pull/2819)는 operation retention을 0/off로 되돌림 | upgrade로 기존 audit를 갑자기 삭제하지 않도록 opt-in한다. upstream LLM tracing default-on은 가져오지 않는다. **PG 유지보수의 cutoff·cursor·짧은 commit·partial 상태 참고.** |
| **OpenViking — snapshot이 이미 포함한 recovery delta 무한 누적** | [#5940 merged](https://github.com/volcengine/OpenViking/pull/5940), merge `db0d241b`: index persist 성공 뒤 가장 오래된 사용 가능 snapshot보다 앞선 delta 제거. [persist](https://github.com/volcengine/OpenViking/blob/621b1ddd9945c362464d18482adb1a48df5ee554/openviking/storage/vectordb/collection/local_collection.py#L1497-L1517)·[watermark](https://github.com/volcengine/OpenViking/blob/621b1ddd9945c362464d18482adb1a48df5ee554/openviking/storage/vectordb/collection/local_collection.py#L1026-L1033) | 앞선 [#5225](https://github.com/volcengine/OpenViking/pull/5225)의 streaming recovery는 RAM 문제만 줄였다. #5940의 byte 안정화는 upstream 보고이며 직접 재현하지 않았다. 기존 snapshot/writer race도 남음. **복구 이력과 삭제 방지 ledger는 다르다. AGPL 개념 참고만.** |
| **MemPalace — full-size backup 무한 누적·SQLite repair 후 빈 공간** | [#1697 merged](https://github.com/MemPalace/mempalace/pull/1697), merge `140c3805`: 기본 backup10개, 생성 뒤 prune. [#1523 merged](https://github.com/MemPalace/mempalace/pull/1523), merge `d74ca062`: FTS rebuild+VACUUM. [backup](https://github.com/MemPalace/mempalace/blob/d9bf01e24972de718b38da24b75c1918b504d084/mempalace/backups.py#L229-L282)·[explicit compact](https://github.com/MemPalace/mempalace/blob/d9bf01e24972de718b38da24b75c1918b504d084/mempalace/backends/sqlite_exact.py#L1562-L1600) | count cap은 byte cap이 아니며 실패를 허용하는 pruning도 있다. compact는 명시 maintenance이지 기본 TTL이 아니다. 앱 audit JSONL rotation [#573](https://github.com/MemPalace/mempalace/pull/573)은 closed/unmerged. **backup 정책과 실제 공간 회수 분리.** |
| **Quivr — abandoned search generation·ingestion intermediate 누적** | [#3908](https://github.com/The-Vibe-Company/quivr/pull/3908)·[#3901](https://github.com/The-Vibe-Company/quivr/pull/3901)·[#3914](https://github.com/The-Vibe-Company/quivr/pull/3914) merged. ownership 조건·grace·durable cursor·lease 내 checkpoint·adaptive ID windows. [PG sweep](https://github.com/The-Vibe-Company/quivr/blob/7b5ffe3eaa031ccbb1f49244b76e8b9bf5d11426/internal/adapters/postgres/ingestion_page_sweep.go#L14-L180)·[projection purge](https://github.com/The-Vibe-Company/quivr/blob/7b5ffe3eaa031ccbb1f49244b76e8b9bf5d11426/internal/adapters/weaviate/purge.go#L18-L134) | 삭제 응답 유실을 완료로 보지 않고 후속 zero-match로 확인한다. 모든 retired-space GC가 끝난 것은 아니다. 현재 Go V2는 evaluation-stage이며 production 사용 경고가 있다. **작은 운영 패턴만 참고, 엔진 도입 아님.** |

## 2. 그 밖의 구현과 반례

### 보존·삭제 순서에서 가져올 원칙

- **WeKnora:** [KB 삭제](https://github.com/Tencent/WeKnora/blob/450b6ed1b781c36983c53d9d564ffe65a863b3e8/internal/application/service/knowledgebase.go#L909-L1057)는 chunk를 지우기 전에 image/object 참조를 모은다. [durable pending cleanup](https://github.com/Tencent/WeKnora/blob/450b6ed1b781c36983c53d9d564ffe65a863b3e8/internal/application/service/knowledgebase.go#L1146-L1161)은 Redis trigger만 지워 startup에서 삭제 KB의 작업이 부활하는 일을 막는다. [#879](https://github.com/Tencent/WeKnora/issues/879)는 closed·현재 코드에 대응이 있지만 연결된 merge PR은 확인하지 못했다. historical backfill [#3594](https://github.com/Tencent/WeKnora/issues/3594)는 open이다. audit90일/0=off의 [삭제 SQL](https://github.com/Tencent/WeKnora/blob/450b6ed1b781c36983c53d9d564ffe65a863b3e8/internal/application/repository/audit_log.go#L117-L135)은 unbatched이며 request timeout을 작업량 상한으로 오인하면 안 된다.
- **Cognee:** [ownership planner](https://github.com/topoteretes/cognee/blob/f154b32a9e544dac73e7ddf2010327cf9988edcd/cognee/infrastructure/databases/unified/provenance_delete_planner.py#L66-L168)는 still-owned/unowned를 분리하고 retry 때 다시 찾을 참조를 남긴다. distributed transaction은 아니다. [#5161](https://github.com/topoteretes/cognee/pull/5161)은 merged into dev, shared PGVector prune이 metadata를 잘못 지우던 문제를 수정했다. collateral edge/normalized ID 보완 [#5629](https://github.com/topoteretes/cognee/pull/5629)는 open이다. whole-system prune은 일반 health 작업에 부적합하다.
- **OpenKB:** SQL DB가 아니라 파일 registry다. [#62 merged](https://github.com/VectifyAI/OpenKB/pull/62), [remove plan](https://github.com/VectifyAI/OpenKB/blob/ff54396e575ee6feb0113b631a34caa082b441cc/openkb/cli.py#L1470-L1558): exact hash identity, 이 삭제에 관련된 링크만 repair, PageIndex 실패 때 partial과 retry identity 보존. 여러 파일의 원자적 transaction은 아니다.
- **Tokenjam:** SQLite가 아닌 DuckDB다. [retention](https://github.com/Metabuilder-Labs/tokenjam/blob/57313d507b8865480fc5e4fc13cb149ea5fe6a85/tokenjam/core/db.py#L4537-L4626)은 삭제와 `retention_events`를 한 transaction에 기록하고 실제 delete 결과를 센다. 선택한 analysis span보다 짧은 retention을 막으며 all-history는 cleanup을 끈다. [#381](https://github.com/Metabuilder-Labs/tokenjam/pull/381)·[#531](https://github.com/Metabuilder-Labs/tokenjam/pull/531)은 merged: migration 번호만 믿지 않고 실제 column/base table drift를 검사한다. 이 자동 repair 정책을 우리 명시 migration의 대체로 가져오지는 않는다. DuckDB [VACUUM](https://duckdb.org/docs/current/sql/statements/vacuum.html#reclaiming-space)은 PG와 달리 disk reclaim 명령이 아니다.
- **LEANN:** derived ANN/파일 index다. [IVF removal](https://github.com/StarTrail-org/LEANN/blob/00710edff4aba84c41f4adfc75b79175b28132f2/packages/leann-core/src/leann/api.py#L859-L939)은 live passage JSONL을 재작성한다. [#279 merged](https://github.com/StarTrail-org/LEANN/pull/279)는 full rebuild가 incremental delta만 읽어 나머지 corpus를 날리던 문제를 수정했다. [#387 merged](https://github.com/StarTrail-org/LEANN/pull/387)는 관련 release/regression을 보완했다. 여러 FAISS/offset/metadata 파일의 일관된 generation publication은 별도 검증이 필요하다.

### ‘정리됐음’이라고 부르면 안 되는 것

| 후보·실제 저장소 | 확인한 동작 | 해결로 과장하면 안 되는 부분 |
|---|---|---|
| **Engram**, SQLite+FTS/version journal | [consolidation](https://github.com/Gentleman-Programming/engram/blob/82846a101296e75351ae444953438cace88e9bea/internal/store/consolidate.go#L93-L187): preview·fingerprint·transaction·provenance | source는 soft-delete로 남고 기본 survivor는 원문 연결, topic update는 version body도 저장. live 기억은 줄어도 저장량 증가 가능. fingerprint는 인간 승인 아님 |
| **context-mode**, content/session SQLite | [14일 source·7일 session cleanup](https://github.com/mksglu/context-mode/blob/655c67f9e1bb2d1c2a6db850447f1cfdcbbb1220/src/session/db.ts#L1683-L1724), event1000개, FTS optimize·close checkpoint | [stale WAL mtime 기반 DB unlink](https://github.com/mksglu/context-mode/blob/655c67f9e1bb2d1c2a6db850447f1cfdcbbb1220/src/store.ts#L222-L261)는 실제 process liveness 검사가 아님. session purge의 whole-store cleanup 호출도 [정적 위험](https://github.com/mksglu/context-mode/blob/655c67f9e1bb2d1c2a6db850447f1cfdcbbb1220/src/server.ts#L4550-L4588). 재현하지 않았으며 이 삭제 패턴은 기각. Elastic License 2.0 |
| **mcp-memory-keeper**, SQLite | explicit compress·retention utility·vacuum helper | [compress](https://github.com/mkreyman/mcp-memory-keeper/blob/4f33fb6e79fb787e555d06feb91c2c5a3de26df3/src/index.ts#L3233-L3340)는 category별100자 sample3개와 keys/count를 남긴 뒤 원본 삭제. lossless 아님. archive는 같은 DB의 다른 table.100MB 설정은 실제 enforced cap으로 확인되지 않음 |
| **codex-agent-mem**, SQLite+FTS+JSON snapshot | [identity별 hash dedup](https://github.com/MarceloCaporale/codex-agent-mem/blob/d594c8a86207fb9a8a5b48a6aab323349680707a/src/codex_agent_mem/db.py#L662-L709), health nonrecording default | raw turn payload와 parsed fields/observations를 함께 저장. retrieval dedup은 row GC 아님. inspected DB/API에서 일반 TTL·vacuum 정책 확인 못함. snapshot restore는 project 문서에 context를 추가하는 방식 |
| **doobidoo/mcp-memory-service**, SQLite/sqlite-vec·optional hybrid | [soft/hard deletion](https://github.com/doobidoo/mcp-memory-service/blob/a2e53c6e76ad0a1b3e7861ca3d5012a5b301b96a/src/mcp_memory_service/storage/mixins/delete.py#L166-L317), backup7일/최대10개 | [same-hash re-store](https://github.com/doobidoo/mcp-memory-service/blob/a2e53c6e76ad0a1b3e7861ca3d5012a5b301b96a/src/mcp_memory_service/storage/mixins/store.py#L25-L151)는 tombstone을 즉시 purge. [#1534](https://github.com/doobidoo/mcp-memory-service/pull/1534)·[#1542](https://github.com/doobidoo/mcp-memory-service/pull/1542)는 merged anti-resurrection 개선이지만 [#1522](https://github.com/doobidoo/mcp-memory-service/issues/1522)는 open: stale recreation 구분·unbounded sync_events 미해결. archive는 live row를 안 지우고 파일 copy를 늘릴 수 있음 |
| **Ray0907/mnema**, Markdown+SQLite FTS/vector | [90일 ranking half-life](https://github.com/Ray0907/mnema/blob/eed19586156ae9664451cb94859f8f3f16b3ac4a/src/store.ts#L533-L560), missing-file reconcile | decay는 retention 아님. embedding cache GC 확인 못함. [rebuild](https://github.com/Ray0907/mnema/blob/eed19586156ae9664451cb94859f8f3f16b3ac4a/src/store.ts#L440-L450)가 vector/meta를 함께 비우지 않는 정적 gap, lock 밖 op-key 검사도 동시성 한계 |
| **danielmarbach/mnemonic**, Markdown/JSON/Git | [supersession lineage 검증 후 prune](https://github.com/danielmarbach/mnemonic/blob/dbac069d3a346075457ec8b090bee5c548adbce6/src/tools/consolidate-helpers.ts#L1291-L1415) | DB 제품 아님. working tree unlink는 git history/backup erasure 아님. sidecar unlink 실패가 note 성공에 가려질 수 있음 |
| **rohitg00/agentmemory**, iii KV file/Redis | [#1416](https://github.com/rohitg00/agentmemory/pull/1416)·[#1419](https://github.com/rohitg00/agentmemory/pull/1419) merged: changed-vector 저장·월별 audit·resumable migration, bounded capture spool | `state_store.db`를 SQLite라 하면 틀림. audit retention 기본0/off라 월별 scope가 총 이력을 제한하지 않음. 기본 hourly age/importance forgetting은 우리 승인/거절 정책으로 기각. [provenance32개 cap](https://github.com/rohitg00/agentmemory/pull/1454)도 우리 full-input lineage와 호환되지 않음 |
| **nbkdoesntknowcoding/mnema**, PG/pgvector+Redis | [daily capture retention](https://github.com/nbkdoesntknowcoding/mnema/blob/fd578b94685eed04c46215f27d59a4cc94e8c5f9/apps/api/src/workers/cron.ts#L237-L319): tool_calls30일1000행 batch, 기타 일부30/90일 | canonical docs/version TTL 아님. soft-delete는 vector cascade를 실행하지 않음. [embedding replace](https://github.com/nbkdoesntknowcoding/mnema/blob/fd578b94685eed04c46215f27d59a4cc94e8c5f9/apps/api/src/workers/embeddings/job.ts#L17-L143)의 final hash/deletion recheck 부재는 정적 stale-write 위험. fair-code 제한 |
| **Mem0**, vector backend+SQLite history/messages | [expiry filter](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/mem0/memory/main.py#L748-L771), session별 최근 message10개, paged delete_all | expiry는 hard TTL 아님. update/delete가 old/new body history를 추가. raw messages 잔존으로 재추출 가능한 [#7452](https://github.com/mem0ai/mem0/issues/7452) open, [#7455](https://github.com/mem0ai/mem0/pull/7455) closed/unmerged. `infer=False`도 embedding egress는 별개 |
| **Graphiti**, Neo4j/graph | [temporal validity·episode lineage](https://github.com/getzep/graphiti/blob/aca369364226a666ca541b061ff2a1a54b80f2ff/graphiti_core/edges.py#L260-L289), [#1553](https://github.com/getzep/graphiti/pull/1553) merged MCP deletion wiring | invalidated edges를 보존. [#1912](https://github.com/getzep/graphiti/pull/1912) surviving support/summary rebuild와 [#1130](https://github.com/getzep/graphiti/pull/1130) orphan sweep은 open. source 하나 삭제를 shared fact 전체 삭제로 확대하면 안 됨 |
| **MemOS**, backend-dependent tree/Neo4j | soft/hard delete, optional oldest-item bucket trim | 기본 reorganize=false. [reorganizer](https://github.com/MemTensor/MemOS/blob/a7367d07e55db61099f7b4e2c1108bc5831a24f3/src/memos/memories/textual/tree_text_memory/organize/reorganizer.py#L309-L410)는 summary/inferred nodes를 추가. bucket count를 persistent byte cap으로 확인하지 못함 |
| **MemoryOS**, JSON/FAISS | short10·mid2000·knowledge100 container bounds | DB lifecycle 엔진 아님. LFU whole-session eviction·deque 제거는 lossy이며 JSON atomic replacement 미확인. deletion 질문 [#53](https://github.com/BAI-LAB/MemoryOS/issues/53)은 closed지만 답변은 미지원 |
| **memU**, 기본 in-memory·optional SQLite/PG | [#651 merged](https://github.com/NevaMind-AI/memU/pull/651): stable path update·unchanged vector reuse·segment diff 삭제 | [plan→embed→write](https://github.com/NevaMind-AI/memU/blob/bbf2d7040d00c0b5b41b72505085a1349d9b9af6/src/memu/app/agentic.py#L369-L489)는 전체 transaction 아님. `commit_results`도 embedding egress 가능. closed migration [#650](https://github.com/NevaMind-AI/memU/issues/650)은 실제 수정 없이 unused legacy로 설명됨 |
| **Neo4j MKG**, graph+embedding | [reject/stale 시 dead embedding 제거·provenance 보존](https://github.com/neo4j-labs/meta-knowledge-graph/blob/03e0b6f6dfd47ef40b480f4ea95066a35c97d0c4/hooks/consistency_gate.py#L766-L820), consolidated recall과 dedup 분리 | 원문/version은 남음. 자동 promotion은 우리 계약과 다름. backfill final status/revision fence 미확인. 라이선스 확인 전 개념만 |
| **Redis agent-memory-server V0** | [#114 merged](https://github.com/redis/agent-memory-server/pull/114): promotion도 dedup 거침, forgetting 기본off·manual dry-run, TTL-preserving format migration | unsupported research V0이지 managed Iris 구현 아님. semantic merge의 old-delete→new-index 순서는 손실 창 위험. key 삭제는 AOF/RDB/backup 축소 증거 아님 |
| **Zep legacy CE** | [hard purge+VACUUM ANALYZE helper](https://github.com/getzep/zep/blob/3997767fccf83bbea7b54ad5f73554f2e5bcd54e/legacy/src/store/db_utils_ce.go) | retired CE. 현재 hosted 제품의 동작 아님. helper 존재가 모든 purge entrypoint·embedding·OS byte 회수를 보장하지 않음 |
| **Letta / Letta Code** | [append-compaction transcript](https://github.com/letta-ai/letta-code/blob/cc4654acc3b424a68c385bce0fe0c00edaad5d7e/src/backend/local/local-store.ts#L3003-L3036), versioned migration backup | 현재 local backend는 JSON/JSONL·Git MemFS. prompt가 작아져도 transcript는 증가. retired V1 SQL 유지보수와 혼동 금지. backup expiry·Git history GC 미확인 |
| **Supermemory** | Local release 문서의 complete backup·migration 경고 | server source는 공개 tree에서 확인 못함. snapshot write amplification [#1413](https://github.com/supermemoryai/supermemory/issues/1413)은 open, [#1177](https://github.com/supermemoryai/supermemory/issues/1177)은 NOT_PLANNED. binary/release 주장과 source-verified remedy 구분 |
| **OpenMemory** | 현재 session porter / archived SQLite+Qdrant memory API 분리 | [archive import](https://github.com/mem0ai/openmemory/blob/2df78cc48e5f688a771fee5b39899325accc2450/openmemory-archive/api/app/routers/backup.py#L265-L459)가 과거 state/vector를 되살릴 정적 위험. current Codex overwrite [#6](https://github.com/mem0ai/openmemory/issues/6)은 reporter local 해결로 closed, upstream fix 아님 |
| **Claude Context**, Milvus/Zilliz+snapshot | [clear 전에 index task cancel+await](https://github.com/zilliztech/claude-context/blob/6fc318b4e3ce58e2898b00a9c3538ead9e24dee5/packages/mcp/src/handlers.ts#L909-L928) | worker 부활 방지 원칙은 유용. snapshot publication과 실제 index 완료가 다르며 Milvus compaction/backup 정책은 wrapper에서 확인 못함 |
| **LangMem**, injected LangGraph store | [allowed action 강제](https://github.com/langchain-ai/langmem/blob/48e3c11f5bb527282c7d5339c6a87a0b35abccfc/src/langmem/knowledge/tools.py#L263-L327) | storage/WAL/backup owner 아님. summarization은 checkpoint GC가 아니고 background store binding [#195](https://github.com/langchain-ai/langmem/pull/195)는 unmerged 제안 |

위 표의 ‘정적 위험’은 실행 재현이 아니다. 관련 검색에서 이슈가 없거나 PR을 확인하지 못한 경우 ‘그 기능이 어디에도 없다’고 확대하지 않는다.

## 3. 우리 시스템과의 대조

| 증가 종류 | 현재 실제 계약 | 남은 질문 |
|---|---|---|
| PG 원문·claim·span·index | `store.py`의 capture/선택 제한·retraction·별도 operator purge. purge는 body/draft/embedding/quote/reason scrub, entity 제거 | corpus 전체의 연령/byte retention은 별도 정책. active/승인/거절 근거를 날짜로 일괄 삭제하지 않음 |
| judgment·relation·selection·feedback | 원문 ID/revision manifest와 이유·전체 dependency 보존 | manifests를 ‘원문 전량 복제’로 과장하지 않음. 동일 입력 판단 억제와 full-lineage 보존을 함께 검토 |
| admission | `store.py:1194-1206`: 새 nonmodel admission 때 만료 최대64개 삭제, record 후 consumed 제거 | 유휴 상태에서도 만료 정리를 실행할지, count/time/lock 상한과 resume 계약 |
| operation·receipt·retired/pending | 원래 실패/attempt·idempotency·successor를 보존 | 먼저 replay horizon·key 재사용/conflict·최소 tombstone 의미 확정. 임의 TTL은 중복 실행 위험 |
| rejection·floor·독립 journal | 거절 재진입 차단, 삭제 floor, restore 밖 최신 head | 본문 삭제 허가와 최소 비부활 metadata 보존 분리. 지원 archive/binary/spool replay보다 먼저 ledger를 버리면 안 됨 |
| legacy vector | 0001의 `vector(1024)`와0006의 historical model-derived provenance 보존, 현재 agent_judged claim은 embedding NULL | 실제 남은 vector bytes와 역사 증거 요구부터 측정. upstream에 index 제거 fix가 있다고 우리에게 없는 HNSW index를 가정해 drop하지 않음 |
| SQLite spool | `spool.py:71-81,149-205,281-319`:24시간 payload TTL, receipt cap, incremental vacuum, TRUNCATE checkpoint, main/WAL/SHM 합산·page cap | 이미 회수 장치가 있음. 임시 spool 정책이 PG 정본 retention은 아님. legacy NONE DB는 pragma만으로 incremental 전환됐다고 할 수 없음. prune LIMIT128은 loop 전체 bound 아님 |
| backup·migration 보존물 | age encrypted archive·명시 migration·독립 deletion head·restore credential/rule fencing | archive 수/기간/bytes와 실제 폐기·restore drill, 최신 witness 보존. 암호화와 모든 사본 삭제는 별개 |

`CleanupScheduler`와 `store.schedule_cleanup()`는 bounded **판단 대기 생성**이다. 원문 유효성의 전체 감사, retention, purge 또는 VACUUM이 아니다. 판단 결과를 남기므로 DB 이력이 추가될 수 있다. UI/운영 문구에서 ‘cleanup 완료’를 ‘저장 공간 정리 완료’로 쓰지 않는다.

## 4. 물리 공간 — 별도 합성 실험

owned PostgreSQL18.6와 Python SQLite3.50.4에 합성1024개×4096-byte 자료를 넣고 절반을 삭제했다. 사용자 DB·현재 memory table·live corpus에는 적용하지 않았다. PG 실험 table의 autovacuum만 꺼서 수동 단계를 분리했고 종료 후 그 schema와 임시 SQLite/WAL/SHM을 제거했다.

| 엔진·단계 | live rows | 관측 bytes | 측정 범위 |
|---|---:|---:|---|
| PG 초기 |1024|5832704|`pg_total_relation_size`: relation+TOAST/index |
| PG 절반 DELETE |512|5832704|동일 |
| PG 일반 VACUUM ANALYZE |512|5849088|동일. 이 실험은 관리용 page 증가도 포함 |
| PG VACUUM FULL ANALYZE |512|2924544|동일. 별도 rewrite |
| SQLite 초기 checkpoint 후 |1024|4726784|main DB, WAL0 |
| SQLite 절반 DELETE+TRUNCATE checkpoint |512|4726784|main DB, WAL0·freelist512 |
| SQLite VACUUM+checkpoint |512|2367488|main DB, WAL0·freelist0 |

제품/OSS 성능 benchmark·절감률·production capacity·매체/backup erasure 증거가 아니다. 확인한 것은 **row 감소와 파일 축소가 별개**라는 저장소 의미다.

공식 근거:

- [PG18 vacuum](https://www.postgresql.org/docs/18/routine-vacuuming.html#VACUUM-FOR-SPACE-RECOVERY): UPDATE/DELETE 뒤 MVCC old version, 일반 VACUUM은 주로 재사용. 완전히 빈 tail page 반환은 예외다. FULL은 ACCESS EXCLUSIVE·새 copy용 추가 공간·I/O가 필요하므로 session-end/daily 자동 처방으로 삼지 않는다.
- [PG18 WAL](https://www.postgresql.org/docs/18/wal-configuration.html): `max_wal_size`는 hard cap이 아니다. archive 실패·뒤처진 replication slot은 WAL을 계속 붙잡을 수 있다. row cleanup만으로 해결되지 않는다.
- [SQLite WAL](https://www.sqlite.org/wal.html#avoiding_excessively_large_wal_files): checkpoint starvation·큰 transaction·autocheckpoint 비활성은 별도 증가 원인. busy checkpoint를 완료로 세지 않는다.
- [SQLite VACUUM](https://www.sqlite.org/lang_vacuum.html): `VACUUM INTO`는 새 compact backup을 만들 뿐 source는 unchanged. 재작성은 write lock·추가 disk가 필요하다. [auto_vacuum 전환](https://www.sqlite.org/pragma.html#pragma_auto_vacuum)은 기존 NONE DB에서 pragma 선언만으로 끝나지 않는다.

## 5. 우선순위 제안 — 구현 승인 아님

1. **P0: 저장소 inventory와 보존 목적.** source/claim/판단 이력·일시 admission·receipt·rejection/floor·파생 index·WAL·backup을 나누고 operator-only body-free 값으로 행 수, 논리 본문 bytes, relation/index/TOAST bytes, 증가율을 측정한다. `n_dead_tup`는 추정치이지 회수 byte가 아니다. 새 telemetry나 LLM이 없어도 가능하다.
2. **P0: restore/replay 안전선.** 지원하는 가장 오래된 archive/binary/spool replay, idempotency key 의미, 거절 이유와 최소 삭제 metadata 보존 기간을 먼저 정의한다. 일반 TTL이 permanent rejection·exact approval·deletion floor를 지우지 않게 한다.
3. **P1: 명백한 일시 상태부터 제한적 정리.** expired admissions·완전히 terminal한 운영 이력을 dry-run→exact 대상·현재 권한/revision 재검사→작은 commit→durable progress로 처리하는 설계를 우선한다. count뿐 아니라 시간·잠금·메모리·최대 work도 묶는다. 실패/취소/응답 유실은 partial/unknown으로 남긴다.
4. **P1: 파생 저장 증폭·backup을 별도 처리.** 실제 사용하지 않는 파생물/색인 여부를 측정하고 원본·공유 support·재시도 manifest를 보존한다. backup은 개수+기간+bytes·지원 restore 범위·최신 witness를 함께 관리한다. 기존 자료를 임의 삭제하지 않는다.
5. **P2: 코드 변경은 shadow 재검토 신호.** 검증된 code provenance와 실제 오탐/누락을 평가한 뒤 관련 기억을 다시 판단한다. 파일 수정/나이/LRU를 자동 global reject·purge로 바꾸지 않는다.
6. **P3: 관계 기반 projection 후 semantic merge 평가.** 기존 duplicate/support/contradict/supersede 관계와 bounded context를 먼저 활용한다. 새 병합은 조건·예외·부정·유효 시간·반례·assertion별 lineage·동시 commit·철회/복원 경계를 보존해야 한다. 요약본을 새 독립 인간 근거나 required rule로 승격하지 않는다.

**가져오지 않는 것:** 새 DB/메모리 엔진, 기본-on inference/trace, 원문 transcript 수집, 나이·중요도 기반 자동 망각, 영구 rejection 이력 cap, mtime 기반 DB unlink, daily VACUUM FULL, backup 안의 과거 승인 부활, maintenance ‘started’를 완료로 표시하는 방식.

## 6. 별도 무결성·버전 주의

[SQLite 공식 WAL-reset advisory](https://www.sqlite.org/wal.html#the_wal_reset_bug)는 드문 concurrent write/checkpoint race의 수정 버전을3.51.3+ 또는 backport3.50.7/3.44.6으로 명시한다. 이번 합성 실험의 Python은3.50.4로 관측됐다. 이것은 별도 runtime patch 검토 근거이며 **production 손상이나 실제 race를 재현했다는 뜻이 아니다.** 사용자 runtime을 임의 upgrade하지 않았다. application schema guard나 Bun/Node capability 판정은 SQLite engine patch-level 보장과 다르다.

## 7. 전체 inventory 처리와 한계

앞의 관련 후보 외에는 기존86항목을 다음처럼 분리했다. 전체 URL·pin·license는 [기존 표](2026-10-15-oss-local-runtime.ko.md#전체-후보-판정표)에 있다.

- **파일/artifact adjunct:** BAML demos·Civitas memory-governance·memory-bank-mcp·osk-system·second-brain-os·PageIndex·mnemonic·IWE·Claude Development Kit·continuity-v2·Serena·autoharness. 일부 파일 수명주기와 승인 패턴은 유용하지만 SQL retention 해결 증거로 세지 않는다.
- **host/SDK/protocol/inference/policy:** effort 도구2종·MCP SDK/spec·SIE·Jevbridge·OMP·HF MCP·Skills extension·mzyag governance·Codex·fast-jev-compaction·BAML·mcpc·agent-flow·fast-agent·12-factor-agents·system-one adapter. 이들의 prompt compaction·cache·debug 파일을 기억 정본의 물리 GC로 세지 않는다.
- **평가/catalogue/demo/docs/private-backend:** bekko·humanlayer skills·kev·memharness·awesome-agent-memory·jev-as-judge·Boundary demo2종·Claude 공개 repo·sales CRM·Runlayer adapter/examples·agent-memory-benchmark·feelings·OB1·ai-memory-governance·ai-that-works 영상 assets·LoCoMo audit·zep-papers·IWE skills. 공개 문서/adapter나 vendor 주장만으로 private DB 구현을 추정하지 않는다.
- **alias/retired:** malformed `mcp-memory-service.`는 canonical과 동일, Neo4j predecessor·archived mem0-mcp·deprecated supermemory-mcp는 새 유지보수 엔진이 아니다.

검색은 growth/size/retention/TTL/prune/vacuum/WAL/checkpoint/history/duplicate/index/orphan/migration/backup과 연결 이슈·PR을 대상으로 했다. 모든 backend/version의 전체 보안 감사는 아니다. context-mode는 공개 issue 접근 제한이 있고 일부 후보는 관련 공개 결과를 찾지 못했다. ‘찾지 못함’은 부재 증명이 아니다. 어떤 examined upstream도 모든 옛 backup에서 우리 고유의 승인·거절·철회 권위가 부활하지 않는다는 end-to-end 계약을 대신 제공하지 않는다.
