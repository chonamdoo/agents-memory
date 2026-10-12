# Local-first 나머지 구성요소 OSS 조사 (2026-10-12)

**표기:** [근거]는 고정 source나 공식 문서를 직접 읽은 것, [추론]은 근거에서 도출한 것, [제안]은 설계 계약(구현 아님), [미확정]은 아직 확인하지 못한 것입니다.

**상태와 범위**
- 전부 source-only입니다. 설치, 빌드, 테스트, 로그인, cloud 호출은 0건입니다.
- 실행 근거는 parent의 SDK 2.3 probe 하나뿐입니다(SDK/HTTP/SQLite 범위). 제품, Hindsight, PG, native host를 증명하지 않습니다.
- GitHub 비인증 API가 rate-limit(403)에 걸렸습니다. 그 뒤의 pin은 `commits/<branch>.atom`의 최신 commit이고, HF 모델은 API `sha`입니다.
- 범주별로 대표 2~4개를 비교했습니다. 전체 Internet을 감사한 것은 아닙니다.
- CueFinder/codegraph 안은 제외했습니다. 아래 SQLite 비교는 일반 backend 비교입니다.

## 0. 결론
1. **DB:** 첫 local release와 이후 개인 cloud 모두 **PostgreSQL 18 + pgvector ≥0.8.7**을 단일 권위로 둡니다. SQLite는 host 쪽 임시 spool(표준 sqlite3, extension 없음)에만 씁니다.
2. **한국어 lexical:** extension 없이 app에서 토큰을 만들어 `array_to_tsvector` + GIN으로 색인합니다. 토큰은 kiwipiepy 형태소, 한글 음절 bigram, 코드 식별자 분해입니다. 품질 gate를 통과하지 못하면 2순위로 pg_bigm을 씁니다. PGroonga와 ParadeDB는 지금은 쓰지 않습니다.
3. **job:** 자체 최소 outbox에 lease와 fencing token을 둡니다. 검토한 OSS 큐는 완료나 heartbeat를 job id로만 갱신하므로 fencing 권위가 없습니다.
4. **migration:** Alembic, `pg_advisory_xact_lock`, migrator role, forward-only로 운영합니다. 앱 시작 시 자동 migration은 금지합니다.
5. **모델:** runtime은 llama.cpp `llama-server`입니다. embedding은 bge-m3, reranker는 bge-reranker-v2-m3입니다. 생성/추출 LLM 후보는 Qwen3.5-9B(Apache-2.0)입니다. 단, 회사 승인 route가 생기기 전까지 extraction/reflect는 `blocked`입니다. 개인 API나 기본값 fallback은 두지 않습니다. Team 구독은 새 background LLM 사용의 승인이 아닙니다.
6. **backup:** `pg_dump -Fc`를 age로 암호화합니다. 필요하면 pgBackRest ≥2.59.3으로 PITR을 더합니다. tombstone ledger는 restore 단위 밖에 두고 restore barrier를 거칩니다.
7. **배포:** macOS native(launchd + Homebrew 또는 Postgres.app)로 하고 Docker Desktop에 의존하지 않습니다. 접속은 loopback, SDK의 Host/Origin 자동 보호, 설치별 token으로 받습니다.

## 1. 고정 소스·라이선스 표

### DB·검색
| 대상 | pin | SPDX/조건 | 핵심 근거 | 판정 |
|---|---|---|---|---|
| PostgreSQL | 18.6 ([versioning](https://www.postgresql.org/support/versioning/)) | PostgreSQL | 18 EOL 2030-11-14, 14 EOL 2026-11-12 | Adopt 18 |
| pgvector | [f37c13f](https://github.com/pgvector/pgvector/blob/f37c13f68b57d2c3472b2214fbcff699d6d34876/README.md) (2026-10-12에도 master 그대로, README 0.8.7) | PostgreSQL-style | 기본은 exact(L197). ANN은 필터를 index scan 뒤에 적용(L450). iterative scan(L480). halfvec은 2d+8 bytes(L998). [0.8.7](https://www.postgresql.org/about/news/pgvector-087-released-3392/)에서 IVFFlat build overflow CVE-2026-103484 수정. 0.8.2 HNSW CVE-2026-3172는 검색 snippet으로만 확인 | Adopt ≥0.8.7, IVFFlat 미사용 |
| pg_trgm | [PG18 docs](https://www.postgresql.org/docs/18/pgtrgm.html) | PostgreSQL | 비단어 문자를 무시(L46). pg_bigm 문서는 pg_trgm이 비알파벳 언어를 지원하지 않는다고 명시 | Reference(ASCII 식별자 전용) |
| pg_bigm | [8c0a691](https://github.com/pgbigm/pg_bigm/blob/8c0a691b9e99c1f83d71ebd1bc066f0140fd1850/docs/pg_bigm_en.md) | PostgreSQL | 2-gram, 1~2자 검색이 빠름, PG 9.1~19 시험. [Cloud SQL 지원](https://docs.cloud.google.com/sql/docs/postgres/extensions)(L231·L362). Homebrew core formula 조회 결과 없음, [Postgres.app 목록](https://postgresapp.com/extensions)에도 없음 | 조건부 2순위 |
| PGroonga | [5ae9889](https://github.com/pgroonga/pgroonga/tree/5ae9889da187a03351e94b329c5ee059cb7485b7) | PostgreSQL. 의존하는 Groonga는 LGPL-2.1-or-later | Cloud SQL 목록에 없음 | Reject(현 단계) |
| ParadeDB pg_search | [9c7ff14](https://github.com/paradedb/paradedb/blob/9c7ff146c92648692647b5b337079ec8fb8b95e7/README.md) | Community는 AGPL-3.0, Enterprise는 상용 | L112-116 | Reject |
| SQLite FTS5/WAL | [fts5](https://www.sqlite.org/fts5.html), [wal](https://www.sqlite.org/wal.html) | public domain | trigram은 3자 미만이면 결과 없음(L842). writer는 한 번에 하나(L178). 네트워크 FS 불가(L72) | spool 전용 |
| sqlite-vec | [04d28bd](https://github.com/asg017/sqlite-vec/tree/04d28bd21773981e2d266bbf6aa4efbd011eb4f6) (v0.1.10-alpha.4) | MIT OR Apache-2.0 | "pre-v1, expect breaking changes". [macOS 기본 Python은 extension 로드 불가](https://alexgarcia.xyz/sqlite-vec/python.html) | 권위 저장소로는 Reject |
| kiwipiepy | [7cd9a9a](https://github.com/bab2min/kiwipiepy/commit/7cd9a9a4982e4db67153c419ce72e35e02719302), PyPI 0.24.0 | Apache-2.0(PyPI). 의존 패키지 `kiwipiepy_model` 라이선스는 [미확정] | – | 후보(품질 gate 필요) |
| Python driver | asyncpg, psycopg3 (master LICENSE, pin 안 함) | asyncpg는 Apache-2.0, psycopg3는 LGPL-3.0 | – | amm은 asyncpg |

### Job·migration
| 대상 | pin | SPDX | 판정 |
|---|---|---|---|
| Procrastinate | [8279a61](https://github.com/procrastinate-org/procrastinate/tree/8279a61789fdf8227d6f513ad15e4b26f1b78b49) | MIT (단 `psycopg[pool]` 필수 → LGPL-3.0) | Reference |
| PgQueuer | [3064102](https://github.com/janbjorge/pgqueuer/tree/3064102fa7a478987aefb0ff2f6e0ed6d1adaaa0) | MIT | Reference |
| DBOS Transact | [d3f2de7](https://github.com/dbos-inc/dbos-transact-py/tree/d3f2de758bbef8e10ca84a6b466108de07fd3be0) | MIT. Conductor는 hosted 상용 | Reject(core로는) |
| pgmq | [8cc0959](https://github.com/pgmq/pgmq/blob/8cc0959b2489c5622af5e5cf6fd8eb8a0b7fd459/pgmq-extension/README.md) | PostgreSQL | Reference |
| Node 큐(pg-boss, Graphile) | 조사 안 함 | – | Py core 원칙으로 Reject |
| Alembic | [1bc21b8](https://github.com/sqlalchemy/alembic/blob/1bc21b86dd6ddd07ac696e2d73b6cb200dd97bbd/alembic/runtime/migration.py) | MIT | Adopt |
| pgroll | [777a535](https://github.com/xataio/pgroll/blob/777a5350e09012b29d26b9611122046d8a96fc1c/README.md) | Apache-2.0 | Reference |

### Runtime·모델
| 대상 | pin | SPDX | 판정 |
|---|---|---|---|
| llama.cpp | [5c8854f](https://github.com/ggml-org/llama.cpp/blob/5c8854fd88319125125dc4b836c98b1b215b0f23/tools/server/README.md) | MIT | Adopt |
| Ollama | [eab97e9](https://github.com/ollama/ollama/blob/eab97e9f92b9a25c2d52d2cc6c1b1c99bd9fae21/docs/faq.mdx) | MIT | 대안 |
| mlx-lm | [ba8a08f](https://github.com/ml-explore/mlx-lm/blob/ba8a08fd2ed72bbc53de84f89933f91fe4743e4a/mlx_lm/SERVER.md) | MIT | Reject(daemon 용도) |
| SIE | [c571e0a](https://github.com/superlinked/sie/blob/c571e0a75d804cb6d49795a99cd03ea901307a69/README.md) | Apache-2.0 | Reference |
| [bge-m3](https://huggingface.co/BAAI/bge-m3/tree/5617a9f61b028005a4858fdac845db406aefb181) | sha 5617a9f | MIT | Adopt |
| [KURE-v1](https://huggingface.co/nlpai-lab/KURE-v1/tree/8b418a58414668e75532ed045c22d9ca018ae2b2) | sha 8b418a5 | MIT | A/B 후보 |
| [Qwen3-Embedding-0.6B](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B/tree/97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3) | sha 97b0c61 | Apache-2.0 | 후보 |
| [bge-reranker-v2-m3](https://huggingface.co/BAAI/bge-reranker-v2-m3/tree/953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e) | sha 953dc6f | Apache-2.0 | Adopt |
| [Qwen3-Reranker-0.6B](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B/tree/e61197ed45024b0ed8a2d74b80b4d909f1255473) | sha e61197e | Apache-2.0 | 후보 |
| [Qwen3.5-9B](https://huggingface.co/Qwen/Qwen3.5-9B/tree/c202236235762e1c871ad0ccb60c8ee5ba337b9a) | sha c202236 | Apache-2.0 | LLM 후보(승인 후) |
| [Qwen3.5-35B-A3B](https://huggingface.co/Qwen/Qwen3.5-35B-A3B/tree/59d61f3ce65a6d9863b86d2e96597125219dc754) | sha 59d61f3 | Apache-2.0 | 메모리 큰 Mac용 |
| [gpt-oss-20b](https://huggingface.co/openai/gpt-oss-20b/tree/6cee5e81ee83917806bbde320786a8fb61efebee) | sha 6cee5e8 | Apache-2.0 | 후보 |
| jina-embeddings-v3 | sha ab036b0 | CC-BY-NC-4.0 | Reject(업무 사용 불가) |
| EmbeddingGemma-300m | sha 57c266a | Gemma terms, 수동 gated | 법무 검토 전 보류 |
| EXAONE-4.5-33B, Qwen3.8-Flash-Next | – | license:other | 법무 검토 전 Reject |

### Backup·배포
| 대상 | pin | SPDX | 판정 |
|---|---|---|---|
| pgBackRest | [86936e1](https://github.com/pgbackrest/pgbackrest/tree/86936e1fa60b10b7592eaac09283c4bb5991265d) (stable 2.59.3, Homebrew arm64 bottle 있음) | MIT | Adopt(VM), local은 선택 |
| WAL-G | [2b8ee7f](https://github.com/wal-g/wal-g/tree/2b8ee7f2e6bdbc4b3246e98405bf9bf77abf9153) | Apache-2.0 | Reference |
| restic | [ca1c625](https://github.com/restic/restic/tree/ca1c625227b7d9f58af12e278feb561c1c1fd195) (Homebrew 0.19.1) | BSD-2-Clause | 개인 off-host 사본용 |
| age | [b74dce4](https://github.com/FiloSottile/age/blob/b74dce4cdbe35b5e5f66c06d9612b72f89028758/README.md) (v1.3.x) | BSD-3-Clause | Adopt |
| MCP python-sdk | [2118f14](https://github.com/modelcontextprotocol/python-sdk/tree/2118f14f8a19bc158d8a1cf90af58d85d187f849) (v2.3.0) | – | Adopt |
| Colima | [49dfe87](https://github.com/abiosoft/colima/commit/49dfe87aecc1645905d0fb8a0e43ce29e12138f6) | MIT | 컨테이너 대안 |
| Caddy | [d4165a4](https://github.com/caddyserver/caddy/commit/d4165a4eb1fdb129e8ce8390099021a00239ecf7) | Apache-2.0 | VM용 |
| Headscale | [a8d6f5b](https://github.com/juanfont/headscale/commit/a8d6f5be81e578a078001b908e41611ec03ce69e) | BSD-3-Clause | VM 대안 |
| Docker Desktop | [license](https://docs.docker.com/subscription/desktop-license/) | 독점. 250명 이상 또는 연매출 $10M 이상 조직은 유료(L10-19) | 필수로 두지 않음 |

## 2. PG+pgvector vs SQLite+FTS5/sqlite-vec
| 축 | PG 18 + pgvector | SQLite + FTS5 + sqlite-vec |
|---|---|---|
| 동시성 | MVCC, row lock, `SKIP LOCKED`, advisory lock, LISTEN/NOTIFY | WAL에서도 writer는 한 번에 하나, `SQLITE_BUSY` 가능, checkpoint starvation 가능. MCP 프로세스 여러 개 + worker + admin이 경합 |
| vector | exact가 기본이고 HNSW, halfvec, sparsevec 지원. 보안 수정이 계속 나옴 | pre-v1 alpha. 저장소에 diskann/ivf 파일이 있어 ANN은 실험 단계로 보임[추론] |
| lexical(한국어) | core FTS에는 한국어 설정 없음. pg_trgm은 비알파벳 언어 미지원. app 토큰화로 해결 가능 | trigram은 2음절 단어(예: '결정', '철회')를 놓침(L842). app 토큰화가 필요한 점은 같음 |
| 권한·격리 | role, GRANT, RLS | 파일 권한뿐 |
| backup·restore | pg_dump, PITR, pgBackRest | `.backup`/`VACUUM INTO`. PITR는 별도 도구 필요 |
| Hindsight 호환 | 필수 조건(PG 14 이상) | 불가. SQLite를 고르면 narrow core만 남음 |
| Python | asyncpg | stdlib로 되지만 macOS 기본 Python은 extension 로드 불가 |
| local과 cloud 동일 core | 같은 PG major·extension 버전을 VM에 그대로 올릴 수 있음 | 단일 disk VM은 가능하나 동시성 모델이 다름 |

**판정:** PG로 갑니다. SQLite는 host spool에만 씁니다. 이것은 event_id 기준 replay 버퍼일 뿐 권위가 아닙니다.

**저장 용량 산수 [추론, 측정 안 함]**
- halfvec(1024)는 행당 2,056 bytes입니다. 10만 chunk면 약 206MB(tuple·index 제외)입니다.
- vector(1024)는 4,104 bytes, 10만 chunk면 약 410MB입니다.
- exact 검색 한 번은 약 1.0e8 곱셈-덧셈입니다. 지연 시간은 측정하지 않았습니다.
- 원칙: scope 필터 안에서 exact로 시작하고, p95가 예산을 넘을 때 HNSW와 `iterative_scan=strict_order`를 켭니다.

**locale [근거: [locale](https://www.postgresql.org/docs/18/locale.html) L126-133]**
- `initdb --locale-provider=builtin --builtin-locale=C.UTF-8`(PG17+)을 씁니다. 문자 분류는 Unicode 기반이고 정렬은 codepoint입니다.
- 기대 효과는 macOS와 Linux의 동작 일치이고, libc 정렬 규칙 변화로 인한 index 위험을 피하는 것입니다[추론].
- Hangul이 분류 단계에서 어떻게 처리되는지와 Hindsight와의 호환은 [미확정]입니다.

## 3. 한국어·식별자 lexical 계약 [제안]
- **정규화:** NFKC를 적용하고 ASCII만 소문자로 바꿉니다.
- **토큰:** Kiwi 형태소(체언·용언 어간), 한글 음절 bigram, camel/snake 식별자 분해, 원문 ASCII 단어의 합집합입니다. 이를 `array_to_tsvector(text[])`로 저장하고 GIN으로 색인합니다. core PG만 쓰므로 Cloud SQL에도 그대로 이식됩니다.
- **정확 식별자:** btree `=`와 ASCII용 pg_trgm을 씁니다.
- **manifest:** 행마다 `tokenizer_rev`를 기록합니다. 버전이 바뀌면 새 revision으로 재색인하고, 서로 다른 manifest를 섞어서 질의하지 않습니다.
- **순위:** ts_rank_cd는 BM25가 아닙니다. 그렇게 부르지 않습니다.
- **fusion:** amm이 RRF로 합칩니다. lexical, amm vector(선택), Hindsight recall을 각각 하나의 arm으로 보고 arm별 status를 반환합니다. 예: `unavailable≠empty`.

## 4. Durable job: 홍보 문구 vs 실제 보장

### Procrastinate
- **claim:** `FOR UPDATE OF jobs SKIP LOCKED` 후 `doing`과 worker_id를 기록합니다(L210-262).
- **heartbeat:** workers table에 기록합니다. 기본 간격 10s, stalled 판정 30s입니다.
- **stalled 재시도:** 사용자가 만든 periodic task가 `get_stalled_jobs`를 돌려야 합니다. `nb_seconds` 방식은 "may lead to wrongly retrying jobs that are still running"이라는 이유로 deprecated입니다([docs](https://github.com/procrastinate-org/procrastinate/blob/8279a61789fdf8227d6f513ad15e4b26f1b78b49/docs/howto/production/retry_stalled_jobs.md)).
- **finish:** `WHERE id=job_id AND status IN('todo','doing')`만 검사합니다(L276, L285). worker나 세대는 보지 않으므로 재시도 후 되살아난 stale worker도 완료를 기록할 수 있습니다[추론].
- **cancel:** todo는 cancelled로, doing은 `abort_requested`(cooperative)로 바뀝니다.
- **중복 방지:** `queueing_lock`은 todo 상태에서만 unique, `lock`은 doing 상태에서만 unique입니다(L100-102). 같은 key의 직렬화는 되지만 이력 전체에 걸친 idempotency는 아닙니다.

### PgQueuer
- heartbeat가 timeout(기본 30s)을 넘긴 picked job은 자동으로 다시 pick됩니다(L426-436).
- 문서가 "A recovered job will run again from the start. Ensure ... idempotent"라고 경고합니다([reliability](https://github.com/janbjorge/pgqueuer/blob/3064102fa7a478987aefb0ff2f6e0ed6d1adaaa0/docs/guides/reliability.md)).
- heartbeat UPDATE(L750-751)와 log_job DELETE(L682-716)가 모두 `id`로만 동작합니다.
- 그 결과 stale worker의 heartbeat가 다시 pick된 job을 계속 살려 두고, 둘 중 먼저 끝난 쪽이 row를 지웁니다[추론].
- `dedupe_key`는 queued/picked 상태에서만 unique입니다.

### DBOS
- 보장: workflow는 완료까지 실행되고, step은 at-least-once이며, transaction은 exactly-once입니다([tutorial](https://docs.dbos.dev/python/tutorials/workflow-tutorial) L281-283).
- exactly-once는 같은 DB 안의 transaction에만 해당합니다.
- 분산 복구는 executor_id 운영으로 하거나 hosted Conductor를 써야 합니다. Conductor는 API key가 필요하고, metadata-only 모드는 Teams 요금제부터입니다([Conductor](https://docs.dbos.dev/conductor/overview)). 회사 환경에서는 반출 경로가 됩니다.

### pgmq
- "exactly once delivery ... within a visibility timeout"이라고 홍보합니다(L17, L347).
- delete/archive는 `msg_id`만 받습니다. 그래서 vt가 지난 뒤 stale consumer가 다른 consumer가 처리 중인 메시지를 지울 수 있습니다[추론].

### 오해 방지
- **SQL row lock은 외부 LLM 쓰기를 fencing하지 않습니다.** `SKIP LOCKED` lock은 claim transaction이 끝나면 사라집니다.
- LLM 호출 동안 transaction을 열어 두는 것은 안티패턴입니다(긴 transaction, connection 점유, vacuum 지연). 그래도 외부 side effect는 막지 못합니다.

### 자체 최소 outbox [제안]
**table** `amm.job(job_id, kind, scope_key, idem_key, req_digest, state, attempts, not_before, lease_owner, lease_token bigint, lease_expires_at, cancel_requested, generation)`
- `UNIQUE(kind, scope_key, idem_key)`는 부분 index가 아니고 이력 전체에 걸칩니다.
- 같은 key인데 req_digest가 다르면 409를 반환합니다.

**동작**
1. **claim:** 짧은 transaction 안에서 CTE `SELECT … FOR UPDATE SKIP LOCKED`를 한 뒤 `UPDATE state='leased', lease_token=nextval(seq), lease_expires_at=now()+ttl`을 실행합니다.
2. **heartbeat:** `UPDATE … WHERE job_id AND lease_token=$t AND state='leased' RETURNING cancel_requested, generation`을 실행합니다. 결과가 0행이거나 cancel 요청이 있거나 generation이 다르면 worker가 스스로 중단합니다.
3. **commit:** 하나의 transaction에서 `UPDATE job SET state='succeeded' WHERE job_id AND lease_token=$t AND generation=current_epoch`을 실행합니다. 0행이면 ROLLBACK합니다. 통과하면 같은 transaction에서 파생 candidate, evidence link, receipt, 다음 outbox를 기록합니다.
4. **reaper:** lease가 만료된 job을 queued로 되돌리거나 dead로 표시합니다.

**외부 side effect**
- LLM 호출은 막을 수 없습니다. 중복 비용으로 계산합니다.
- Hindsight 쓰기는 `document_id=amm:{event}:{rev}`로 replace해서 idempotent하게 만들고, 사후 reconcile로 정리합니다.

**자체 구현을 택한 이유:** 표 1개와 SQL 약 5문장입니다. fence는 어차피 우리 commit transaction 안에 직접 써야 합니다. LGPL 의존도 생기지 않습니다.

## 5. Schema migration
- **Alembic:** `runtime/migration.py`에 advisory 같은 migration lock 장치가 없습니다(grep 결과 없음). 두 프로세스가 동시에 upgrade하는 것을 도구가 막아 주지 않습니다[근거+추론].
- `autocommit_block`은 앞선 작업을 무조건 commit합니다(L272-312). `transaction_per_migration`을 씁니다.
- session 수준 advisory lock은 transaction 의미를 따르지 않습니다([explicit-locking](https://www.postgresql.org/docs/18/explicit-locking.html) L175). 그래서 env.py에서 `pg_advisory_xact_lock`을 겁니다.
- **권한:** migrator role만 CREATE/ALTER EXTENSION을 할 수 있고 app role은 CREATE 권한이 없습니다.
- **Hindsight:** 자체 alembic(약 100개 revision)이 있고 `RUN_MIGRATIONS_ON_STARTUP`의 기본값이 true입니다. false로 두고 명시적으로 실행합니다.
- **호환 matrix:** amm release, Hindsight pin, PG major, pgvector 버전, tokenizer/model manifest를 함께 관리합니다.
- **방향:** forward-only입니다. binary를 되돌리는 것과 schema를 되돌리는 것은 다릅니다. 롤백은 이전 image + restore + tombstone 재적용입니다.
- **pgroll:** expand/contract와 이중 schema view 방식입니다. 단일 사용자 local에는 필요 없어 참고로만 둡니다.

## 6. 로컬 ARM 모델·runtime

### llama.cpp
- `--offline`으로 cache만 쓰고 네트워크를 막습니다(L111).
- 기본 host는 127.0.0.1이고, 이 pin의 기본 port는 9931입니다(L191).
- `--api-key-file`을 지원합니다(L212).
- Web UI가 기본으로 켜져 있습니다(L208). `--no-webui`로 끕니다.
- `--embedding`과 `--rerank`(bge-reranker-v2-m3 + `--pooling rank`)를 지원합니다(L209-210, L764).
- json_schema 제약 생성(L153, L1342)은 문법만 보장하고 의미는 보장하지 않습니다. 그래서 validator와 "evidence 인용문이 원문의 substring인지" 검사를 거친 결과만 candidate로 씁니다.

### Ollama
- macOS 앱은 업데이트를 자동으로 내려받습니다(L7). 버전 drift와 egress가 생깁니다.
- cloud 기능이 기본으로 켜져 있습니다. `OLLAMA_NO_CLOUD=1` 또는 server.json으로 끕니다(L163-181).
- 기본 bind는 127.0.0.1이고(L185), CORS는 기본으로 127.0.0.1과 0.0.0.0 origin을 허용합니다(L222).

### mlx-lm
- SERVER.md가 스스로 "not recommended for production"이라고 씁니다(L7-9). cache에 없으면 HF에서 받습니다.

### SIE
- 익명 telemetry가 기본으로 켜져 있습니다. `SIE_TELEMETRY_DISABLED=1` 또는 `DO_NOT_TRACK=1`로 끕니다.
- 모델마다 첫 호출 때 weights를 받습니다.
- production은 K8s 중심입니다. sie_mcp는 `mcp<2`입니다(기존 조사).

### HF 환경 변수 ([docs](https://huggingface.co/docs/huggingface_hub/package_reference/environment_variables))
- `HF_HUB_OFFLINE=1`이면 HTTP 요청을 하지 않습니다(L114-120).
- `HF_HUB_DISABLE_TELEMETRY=1`(L168-173)과 `DO_NOT_TRACK`(L224-226)으로 telemetry를 끕니다.
- `revision=<sha>`로 고정하고 weights를 미리 반입합니다. SHA256 manifest를 둡니다.
- GGUF 변환본은 third-party일 수 있으므로 별도로 hash를 고정합니다.

### 한국어 품질 (저자 자체 보고, 일반 한국어 검색이며 agent memory나 코드 대상 아님)
[KURE README](https://huggingface.co/nlpai-lab/KURE-v1/raw/8b418a58414668e75532ed045c22d9ca018ae2b2/README.md) L113-133의 top-1 평균 recall:

| 모델 | top-1 recall |
|---|---|
| KURE-v1 | 0.5264 |
| bge-m3 | 0.5178 |
| multilingual-e5-large | 0.5005 |
| jina-v3 | 0.4829 |
| OpenAI text-embedding-3-large | 0.4488 |

→ bge-m3를 기준선으로 두고, 같은 1024차원인 KURE-v1을 A/B합니다.

### 메모리 상한 참고 [추론, 산수]
| 모델 | params | 크기 |
|---|---|---|
| bge-m3 | 약 568M | fp16 약 1.1GB |
| bge-reranker-v2-m3 | 567.8M | fp16 약 1.1GB |
| Qwen3.5-9B | 9.65B | BF16 약 19.3GB, Q4 약 6GB |
| Qwen3.5-35B-A3B | 35.95B | Q4 약 21GB, 32GB 이상 필요 |

- 32GB Mac 예산: PG 약 1GB + embed/rerank 약 2.5GB + 9B Q4와 KV cache 약 7~8GB → 합계 약 11GB.
- 16GB Mac: 4B LLM을 쓰거나, 승인된 원격 route가 생길 때까지 reflect를 blocked로 둡니다.
- 처리량은 측정하지 않았습니다.

### Hindsight 기본 모델
- 기본 embedding은 bge-small-en, reranker는 ms-marco로 둘 다 영어 중심입니다.
- 다국어 모델로 바꾸고 전체를 재임베딩해야 합니다.
- 모든 LLM slot을 승인된 endpoint로 명시합니다. slot이 비어 있으면 global 설정으로 fallback하므로 비워 두지 않습니다.

## 7. Backup·restore·암호화
- **pg_dump:** 출력은 더 새로운 PG에 load할 수 있지만, 자신보다 새로운 PG server는 dump하지 못합니다([docs](https://www.postgresql.org/docs/18/app-pgdump.html) L495). schema 단위로 포함/제외할 수 있습니다. PITR는 아닙니다.
- **PITR(basebackup + WAL):** cluster 전체가 되돌아갑니다. 같은 cluster 안의 tombstone도 함께 되돌아갑니다. PG17+ incremental backup은 WAL summary와 이전 backup chain이 필요하고, 작은 DB라면 full backup이 더 단순합니다([L119-127](https://www.postgresql.org/docs/18/continuous-archiving.html)).
- **pgBackRest:**
  - 2.59.3 이전 버전은 RNG 오류 때 약한 subkey/salt를 만들 수 있었습니다. 업그레이드해도 이미 만든 subkey는 바뀌지 않으므로 새 stanza를 만들어야 합니다.
  - 유지보수가 2026-04-27에 중단됐다가 2026-05-18에 sponsor coalition으로 재개됐습니다.
  - 2.59.0부터 기본 설정에서는 root로 restore만 실행할 수 있습니다.
- **restic:**
  - 삭제는 forget 뒤 prune을 해야 합니다. prune 전까지 데이터가 남습니다.
  - `--max-unused`(기본 5%) 때문에 일부만 쓰이는 pack이 남습니다.
  - append-only 모드에서는 prune을 할 수 없습니다.
  - 살아 있는 PGDATA를 restic으로 직접 백업하면 일관성이 없습니다. dump 파일이나 pgBackRest repo를 백업합니다.
- **age:**
  - 수신자 공개키로 파일을 암호화합니다. `-pq` 옵션으로 post-quantum hybrid를 씁니다.
  - SSH 수신자를 쓰면 공개키 tag가 파일에 남아 추적할 수 있습니다(L291).
  - corpus마다 key를 따로 두고 key를 폐기하면 corpus 단위 crypto-shred가 됩니다. 항목 단위 삭제는 아닙니다.
- **tombstone barrier [제안]:**
  - ledger는 본문 없이 id, scope, digest, epoch, actor, 시각을 담고 hash-chain으로 잇습니다.
  - restore 단위 밖에 둡니다. logical dump라면 제외 schema에, PITR라면 별도 파일이나 cluster에 둡니다. 보존 기간은 데이터 backup 이상입니다.
  - restore 절차: 읽기 닫기 → restore → generation 증가(stale worker fence) → ledger 재적용과 파생물 purge → 검증 → 읽기 열기.
  - 'purge 완료'는 그 내용을 담은 모든 backup set이 만료된 뒤에만 기록합니다.
- **버전 제약:** 물리 backup은 restore할 때 같은 PG major와 같은 extension binary(pgvector .so)가 있어야 합니다. logical dump는 대상에 extension이 설치돼 있어야 합니다.

## 8. 로컬 배포·ingress·보안
- **설치:** native launchd를 쓰고 Docker Desktop은 요구하지 않습니다.
  - Homebrew에 postgresql@18 18.6과 pgvector 0.8.7 arm64 bottle이 있습니다.
  - [Postgres.app](https://postgresapp.com/extensions)은 pgvector를 포함합니다.
- **PG 접속:** Unix socket 또는 127.0.0.1에 scram 인증을 씁니다. role은 migrator, amm_app, amm_worker, hindsight_app, readonly로 나눕니다.
- **MCP SDK:**
  - 기본 host는 127.0.0.1입니다(mcpserver/server.py L1112).
  - host가 loopback일 때만 Host/Origin 보호가 자동으로 켜집니다(lowlevel/server.py L747-753).
  - 설정 없이 0.0.0.0에 bind하면 보호가 꺼집니다(transport_security.py).
  - 요청 body 기본 상한은 4MiB입니다.
  - Host/Origin 검사는 인증이 아닙니다. 같은 UID의 다른 프로세스도 접속할 수 있으므로 0600 token 파일과 TokenVerifier를 둡니다. stdio shim에서 UDS로 붙는 방식도 같은 UID 내 격리는 제공하지 않습니다.
- **내부 서비스:** Hindsight와 llama-server는 모두 loopback에 두고 key를 걸며 MCP와 webui는 끕니다.
- **이후 개인 VM:** Caddy로 TLS를 받고 OAuth를 거쳐 amm에 연결한 뒤, 나머지 서비스는 loopback에 둡니다. 대안은 Headscale private overlay입니다. Tailscale SaaS를 쓰면 metadata가 vendor 쪽으로 갑니다[추론].

## 9. 추가 엔진 채택 조건
- **OpenSearch + nori:** app tokenizer와 pg_bigm을 써도 한국어 형태소 품질 gate를 통과하지 못할 때만 고려합니다. 비용은 두 번째 저장소의 이중 쓰기, 삭제·restore·backup 부담, JVM 운영입니다.
- **graph DB:** multi-hop 질의 개선이 측정으로 입증될 때만 고려합니다.
- **Redis/Valkey/Qdrant:** 이 규모에서는 메울 능력 공백이 없어 쓰지 않습니다. 조사하지 않았습니다.

## 10. 우리가 직접 지켜야 하는 DB 불변식
1. `accepted`는 event, receipt, outbox가 같은 transaction으로 commit된 뒤에만 반환합니다. `accepted≠queryable`입니다.
2. idempotency key는 이력 전체에서 unique하고 digest를 함께 저장합니다. 재요청은 같은 receipt를 돌려받습니다. RPC id나 session id로 대신하지 않습니다.
3. lease token은 단조 증가합니다. 모든 파생 쓰기는 같은 transaction에서 `(job, token, generation)`을 검사합니다. 외부 효과는 idempotent하게 만들고 reconcile합니다.
4. 모든 읽기 경로에 eligibility를 적용합니다: 3 scope, approved revision의 exact digest, tombstone 미해당, watermark 충족. selector가 넓어지면 재승인을 받습니다.
5. tombstone ledger는 restore 단위 밖에 있고, restore barrier와 generation 증가를 거칩니다.
6. index manifest(model sha, 차원, 정규화, tokenizer_rev)가 같은 것만 함께 질의합니다.
7. arm별 status를 반환합니다. `unavailable≠empty`이며, 실패를 빈 결과로 위장하지 않습니다.
8. migrator 하나가 lock을 잡고 실행합니다. schema version이 맞지 않으면 앱이 시작을 거부합니다.
9. company와 personal은 다른 cluster, 다른 backup repo, 다른 key를 씁니다. 자동 sync는 없습니다.
10. 모델 route는 승인 ID에 묶습니다. route가 없으면 `blocked`이고 fallback은 없습니다.

## 11. 판정과 비용·위험
| 대상 | 판정 | 비용·위험 |
|---|---|---|
| PG18 + pgvector ≥0.8.7 | Adopt | daemon 설치와 patch(pgvector CVE 주기). Cloud SQL은 0.8.5라 보안 수정 backport 여부 [미확정] |
| app 토큰화 + tsvector | Adopt | tokenizer 유지보수와 재색인. 품질 미측정 |
| pg_bigm | 조건부 | Mac에서는 PGXS로 직접 build해야 함 |
| 자체 outbox | Adopt | 직접 시험 책임 |
| Procrastinate, PgQueuer | Reference | fence 없음. Procrastinate는 LGPL 의존 |
| DBOS | Reject | SaaS HA, 실행 모델 종속 |
| pgmq | Reference | – |
| Alembic | Adopt | lock을 직접 구현 |
| pgroll | Reference | – |
| llama.cpp | Adopt | 변환본 hash 관리 |
| Ollama | 대안 | 자동 업데이트, cloud 기능 |
| SIE | Reference | telemetry, 무게 |
| mlx-lm server | Reject | production 비권장 |
| bge-m3, bge-reranker-v2-m3 | Adopt | – |
| Qwen3.5 계열 | 승인 후 후보 | – |
| NC 또는 'other' 라이선스 모델 | Reject | – |
| pg_dump + age | Adopt(local) | – |
| pgBackRest ≥2.59.3 | Adopt(VM) | – |
| restic | 개인 off-host 사본 | prune 지연과 잔존 데이터 |
| WAL-G | Reference | – |
| SQLite | spool 전용 | – |
| sqlite-vec, PGroonga, ParadeDB | Reject | – |

## 12. 직접 소스가 막힐 때의 대안
- **Homebrew나 Postgres.app을 쓸 수 없을 때:** Colima(MIT)와 container image를 씁니다. Docker Desktop은 회사 라이선스 확인이 필요합니다.
- **local PG 자체가 불가능할 때:** 승인된 내부 PG host를 씁니다. SQLite 권위로는 대체하지 않습니다.
- **llama.cpp를 쓸 수 없을 때:** Ollama를 pin된 CLI로 쓰고 `OLLAMA_NO_CLOUD=1`을 켜고 자동 업데이트를 끕니다. 그것도 안 되면 SIE에 telemetry를 끄고 egress를 차단해 씁니다.
- **승인된 model route가 전혀 없을 때:** capture와 lexical recall은 동작하더라도 `full_loop=unsupported`로 표시합니다.
- **Hindsight를 탈락시킬 때:** 같은 outbox와 index 위에 narrow PG core를 올립니다. 기능 축소는 하지 않습니다.

## 13. 미확정 항목과 나중에 할 검증 (미실행)
**미확정**
- builtin C.UTF-8에서 Hangul 처리와 Hindsight 호환
- kiwipiepy_model 라이선스
- pgvector 0.8.2 CVE 상세
- Cloud SQL backport 여부
- llama.cpp에서 연결이 끊길 때 생성이 중단되는지
- PgQueuer 완료 buffering의 상세

**검증 계획**
1. 한국어 fixture로 lexical 품질 확인: 2음절 단어, 조사, 코드 식별자
2. scope 필터를 건 상태에서 exact와 HNSW의 recall 비교
3. stale worker 시험: SIGSTOP, lease 회수, 재개 후 commit이 거부되는지
4. LLM 호출 중 cancel
5. 철회 전 backup을 restore한 뒤 철회 자료가 되살아나지 않는지
6. migrator 두 개를 동시에 실행
7. offline egress를 packet 수준에서 확인
8. 모델 hash와 라이선스 manifest 확인