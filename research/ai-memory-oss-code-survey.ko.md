# AI 메모리 오픈소스 코드 조사 — 로컬 대 클라우드, 멀티 프로젝트 비교

조사일 2026-10-15. 4개 하위 조사가 각 GitHub 저장소의 고정 커밋 소스 파일을 `gh api`로 직접 읽었습니다(설치·실행 없음). 아래 1장은 종합이고, 2~5장은 하위 조사 원문입니다. 각 주장의 근거 링크는 원문 장에 있습니다. README에만 근거한 내용과 [추론]은 원문 표시를 따릅니다. 이 종합은 상위 세션이 원문을 읽고 정리한 것이며, 링크를 다시 대조하지는 않았습니다.

## 1. 종합

### 1.1 무엇을 기억할지 누가 판단하나
- **대부분 서버·라이브러리 쪽 LLM이 판단합니다.** mem0(ADD 전용 1회 추출), Graphiti, Cognee, Hindsight, Honcho, Redis AMS, MemMachine, MemOS 서버, Memobase, Cipher, claude-mem(별도 observer LLM, 기본 Claude Haiku).
- **호출하는 에이전트가 판단하는 소수:** basic-memory, MCP reference memory, memory-bank-mcp, ConPort, Serena, Engram(충돌 시 `mem_judge`), Letta/letta-code(메모리 파일 직접 편집), memU(스케줄된 `claude -p`), LangMem hot-path 도구.
- **원문 byte span과 revision을 서버가 검증하는 곳은 우리뿐입니다.** 에이전트 판단 계열도 출처 검증은 없습니다.

### 1.2 로컬 대 클라우드
| 유형 | 예 | 로컬에서 실제로 일어나는 일 |
|---|---|---|
| 같은 코드, 배포만 다름 | Honcho, MemMachine, Papr, Mem0 OSS, Hindsight, basic-memory | 차이는 주로 인증 기본값과 일부 클라우드 전용 기능. self-host 인증이 꺼져 있거나 없는 경우가 흔함(Honcho `USE_AUTH=False`, Redis V0, MemMachine) |
| 엔진 비공개, 공개는 SDK·MCP·플러그인 | Supermemory, Zep Cloud, Mem0 Platform, Memori | 로컬 바이너리는 비공개 빌드(Supermemory)이거나 없음. Memori는 BYODB 모드에서도 대화를 `memorilabs.ai`로 보내 추출 |
| OSS는 동결·축소 | Redis AMS(V0 연구용), Zep CE(deprecated), OpenMemory(제거), Letta 서버(archive) | 제품은 관리형으로 이동 |
| 로컬 전용 | MCP reference memory, ConPort, Serena, memory-bank, memvid, A-mem | 클라우드 없음 |

- **"로컬" 기본값도 외부 LLM을 부르는 경우가 많습니다.** mem0·Honcho·Graphiti·MemMachine·Papr는 기본 OpenAI, claude-mem은 tool 입출력을 Anthropic으로 보냅니다. 텔레메트리 기본 켜짐: Mem0(PostHog), Supermemory 로컬, MemOS 플러그인, memU.
- 우리는 서버 측 LLM이 없어 서버발 egress가 없습니다. 모델 처리는 이미 쓰고 있는 코딩 에이전트 경로뿐입니다.

### 1.3 저장소와 Docker
- 마켓플레이스·한 줄 설치가 되는 프로젝트는 내장 저장소를 씁니다: SQLite(+FTS5, sqlite-vec), Chroma(로컬 프로세스), LanceDB·Kuzu, Markdown 파일, 단일 파일(memvid).
- PostgreSQL을 유지하면서 Docker를 피한 사례는 Hindsight `pg0`(내장 PG 프로세스)와 Letta·MIRIX의 SQLite/PGlite fallback입니다.
- Docker가 사실상 필수인 쪽은 PG+Redis(Honcho, Memobase), Neo4j/Qdrant 조합(MemMachine, Papr, MemOS 서버), Redis(Redis AMS)입니다.

### 1.4 갱신·모순·삭제
- 시간 축과 모순 무효화를 코드로 강제: Graphiti(`valid_at`/`invalid_at`/`expired_at`), memvid(`entity:slot` supersedes), Cognee(선택). 나머지는 LLM 재작성·삭제이거나 처리가 없습니다.
- 관계를 에이전트가 제출하는 곳은 우리뿐입니다. 다른 곳은 LLM이나 규칙이 만듭니다.
- 삭제 저널(retract/purge 감사)이나 rejection feedback 구현은 조사 대상 어디에도 없습니다. mem0 history는 삭제 후에도 원문이 남습니다.

### 1.5 멀티 프로젝트
- project를 정식 단위로 두고 **서버가 자격증명으로 격리**하는 곳은 우리(`am_grants`), Memobase(`project_secret`), claude-mem server-beta(키에 묶인 `project_id`) 셋입니다. Cognee(dataset), Honcho(workspace)도 서버가 강제합니다.
- 나머지 대부분은 호출자가 바꿀 수 있는 필터이고, Graphiti·Redis AMS는 필터를 생략하면 전체를 조회합니다.
- 코딩 에이전트 플러그인(claude-mem, Mem0·Hindsight·Supermemory 플러그인)은 cwd·git root로 프로젝트를 자동 판별합니다. 우리는 operator가 등록한 binding을 권한 근거로 쓰고 cwd는 검사에만 씁니다.
- 발표의 7개 블록(프로젝트·태스크·클레임·소스·이벤트·엔티티·아티팩트)을 모두 갖춘 곳은 없습니다. 우리는 task·artifact 블록이 없고, entity는 claim에 딸린 이름 목록, event는 `event_time`·`valid_from/until` 필드뿐입니다. claim→source 출처는 byte span까지 연결해 가장 세밀합니다.


## 2. 코딩 에이전트용 메모리 (원문)

# 카테고리 A 코드 조사: 코딩 에이전트용 메모리 (Claude Code/Codex/Cursor 플러그인, MCP 메모리 서버, hook 캡처)

- **방법**: 모든 저장소는 2026-10-15 기준 기본 브랜치 HEAD SHA에 고정했습니다. `gh api`로 git tree를 받고 소스 파일 원문을 읽었습니다. README는 코드 위치를 찾는 데만 썼고, README로만 확인한 주장은 **[README-only]**로 표시했습니다. 코드로 확인하지 못한 판단은 **[추론]**입니다.
- **저장소 이전·아카이브**: 다음 세 곳은 조사 중 이름이 바뀌었거나 아카이브된 것을 확인했습니다.
  - `campfirein/cipher` → `campfirein/byterover-cli`로 redirect되며 아카이브되었습니다. Cipher 코드는 `cipher-final` 태그에만 남아 있습니다.
  - `CaviraOSS/OpenMemory` → `CaviraOSS/LongMemory`로 redirect되며, 코드가 완전히 다시 작성되었습니다.
  - `steveyegge/beads` → `gastownhall/beads`.

---

## 1. thedotmack/claude-mem

1. **기본 정보**: TypeScript/Bun 프로젝트입니다. Apache-2.0, ★약 10만, 2026-10-13에 push. 고정 커밋은 `fef3402`입니다.
2. **쓰기 경로 (Hook 캡처 + 서버 쪽 LLM이 판단)**
   - [hooks.json](https://github.com/thedotmack/claude-mem/blob/fef3402e674bebbf72a23aeb735e91c92cd34afd/plugin/hooks/hooks.json#L77)에 다음 hook이 등록되어 있습니다: SessionStart(context 주입), UserPromptSubmit(session-init), **PostToolUse/PostToolUseFailure matcher `*`**(observation), PreToolUse(file-context), Stop(summarize), SessionEnd.
   - [`observationHandler`](https://github.com/thedotmack/claude-mem/blob/fef3402e674bebbf72a23aeb735e91c92cd34afd/src/cli/handlers/observation.ts#L34)는 모든 tool 입출력을 worker spool에 넣습니다. 서브에이전트 호출과 `CLAUDE_MEM_SKIP_TOOLS` 목록은 걸러냅니다.
   - 무엇을 기억할지는 **별도 observer LLM**이 정합니다.
     - 기본 provider는 `claude`, 기본 모델은 `claude-haiku-4-5`입니다([Settings L400](https://github.com/thedotmack/claude-mem/blob/fef3402e674bebbf72a23aeb735e91c92cd34afd/src/shared/SettingsDefaultsManager.ts#L400), [L429](https://github.com/thedotmack/claude-mem/blob/fef3402e674bebbf72a23aeb735e91c92cd34afd/src/shared/SettingsDefaultsManager.ts#L429)).
     - 호출 방식은 `@anthropic-ai/claude-agent-sdk`의 `query()`입니다([ClaudeProvider L32](https://github.com/thedotmack/claude-mem/blob/fef3402e674bebbf72a23aeb735e91c92cd34afd/src/services/worker/ClaudeProvider.ts#L32)).
     - 대체 provider로 Gemini, OpenRouter, OpenAI 호환 API, Codex를 지원합니다.
   - 프롬프트는 [`src/sdk/prompts.ts` `renderObservationPrompt`](https://github.com/thedotmack/claude-mem/blob/fef3402e674bebbf72a23aeb735e91c92cd34afd/src/sdk/prompts.ts#L441)입니다. LLM은 `<observation>` XML(type/title/facts/narrative/concepts/files)이나 `<skip_summary reason="noise"/>` 중 하나를 반환합니다.
   - 명시적 쓰기 경로도 있습니다. MCP `save_memory` 도구는 에이전트가 직접 남기는 노트입니다([mcp-server L528](https://github.com/thedotmack/claude-mem/blob/fef3402e674bebbf72a23aeb735e91c92cd34afd/src/servers/mcp-server.ts#L528)).
3. **갱신·통합**
   - [`nearDuplicate.classifyPair`](https://github.com/thedotmack/claude-mem/blob/fef3402e674bebbf72a23aeb735e91c92cd34afd/src/services/dedup/nearDuplicate.ts#L49)는 IDF 가중 TF-IDF 코사인 값에 IDF veto를 적용해 근접 중복을 판정합니다.
   - LLM이 ADD/UPDATE/DELETE를 결정하는 단계는 찾지 못했습니다. 모순·대체(supersede) 관계 모델도 확인되지 않았습니다.
4. **검색**
   - [`SearchOrchestrator`](https://github.com/thedotmack/claude-mem/blob/fef3402e674bebbf72a23aeb735e91c92cd34afd/src/services/worker/search/SearchOrchestrator.ts#L96)는 Chroma 벡터 검색을 먼저 시도하고, 카테고리 결과가 비면 SQLite FTS로 보충합니다.
   - [`HybridSearchStrategy`](https://github.com/thedotmack/claude-mem/blob/fef3402e674bebbf72a23aeb735e91c92cd34afd/src/services/worker/search/strategies/HybridSearchStrategy.ts#L15)는 메타데이터 필터 결과와 Chroma 순위의 교집합을 씁니다.
   - 주입 방식: SessionStart hook이 `/api/context/inject` 결과를 `hookSpecificOutput.additionalContext`로 자동 주입합니다([context.ts L290](https://github.com/thedotmack/claude-mem/blob/fef3402e674bebbf72a23aeb735e91c92cd34afd/src/cli/handlers/context.ts#L290)). 이와 별도로 3단계 점진 공개형 MCP 도구 `mem_search`가 있습니다([L488](https://github.com/thedotmack/claude-mem/blob/fef3402e674bebbf72a23aeb735e91c92cd34afd/src/servers/mcp-server.ts#L488)).
5. **저장소**
   - 기본은 내장 SQLite `~/.claude-mem/claude-mem.db`입니다([paths L57](https://github.com/thedotmack/claude-mem/blob/fef3402e674bebbf72a23aeb735e91c92cd34afd/src/shared/paths.ts#L57)).
   - 여기에 Chroma가 붙습니다. `uvx chroma-mcp --client-type persistent --data-dir`로 로컬 프로세스를 띄우며 기본값은 enabled/local입니다([ChromaMcpManager L693](https://github.com/thedotmack/claude-mem/blob/fef3402e674bebbf72a23aeb735e91c92cd34afd/src/services/sync/ChromaMcpManager.ts#L693), [Settings L526](https://github.com/thedotmack/claude-mem/blob/fef3402e674bebbf72a23aeb735e91c92cd34afd/src/shared/SettingsDefaultsManager.ts#L526)).
   - 기본 경로에 Docker는 필요 없지만, uv/uvx와 Python이 필요합니다.
6. **로컬과 클라우드의 차이**
   - **runtime 선택**: `CLAUDE_MEM_RUNTIME`의 기본값은 `worker`(로컬)입니다([L619](https://github.com/thedotmack/claude-mem/blob/fef3402e674bebbf72a23aeb735e91c92cd34afd/src/shared/SettingsDefaultsManager.ts#L619)). `server`로 바꾸면 hook이 `/v1/events`로 전송하고, 설정이 불완전하면 worker로 되돌아갑니다([runtime-selector L39-L109](https://github.com/thedotmack/claude-mem/blob/fef3402e674bebbf72a23aeb735e91c92cd34afd/src/services/hooks/runtime-selector.ts#L39)).
   - **server runtime 구성**: API key와 team 단위로 다중 테넌트를 나누고, Postgres(`CLAUDE_MEM_SERVER_DATABASE_URL`)와 BullMQ/Redis 큐를 선택적으로 씁니다([postgres/config L32](https://github.com/thedotmack/claude-mem/blob/fef3402e674bebbf72a23aeb735e91c92cd34afd/src/storage/postgres/config.ts#L32), [redis-config L9](https://github.com/thedotmack/claude-mem/blob/fef3402e674bebbf72a23aeb735e91c92cd34afd/src/server/queue/redis-config.ts#L9)).
   - **유료 클라우드 동기화(cmem.ai)**: `CLAUDE_MEM_CLOUD_SYNC_HUB_URL`이 기본 공란이라 꺼져 있습니다([L548](https://github.com/thedotmack/claude-mem/blob/fef3402e674bebbf72a23aeb735e91c92cd34afd/src/shared/SettingsDefaultsManager.ts#L548)). 켜면 `synced_at IS NULL` 행을 hub로 push합니다([CloudSync.ts 헤더](https://github.com/thedotmack/claude-mem/blob/fef3402e674bebbf72a23aeb735e91c92cd34afd/src/services/sync/CloudSync.ts#L1)).
   - **Pro 추론 게이트웨이**: Pro 키가 있으면 observer 추론이 cmem.ai 게이트웨이로 가고, 구독이 만료되면 사용자의 Anthropic 플랜으로 되돌아갑니다([cmem-gateway L6](https://github.com/thedotmack/claude-mem/blob/fef3402e674bebbf72a23aeb735e91c92cd34afd/src/shared/cmem-gateway.ts#L6)).
   - **핵심**: 로컬 모드도 기본값에서 tool 입출력을 Anthropic(Claude 로그인/키)으로 보냅니다. 데이터가 밖으로 나가는 것이 기본 동작입니다.
7. **삭제·개인정보**
   - `<private>` 태그는 저장 전에 제거됩니다([tag-stripping L6](https://github.com/thedotmack/claude-mem/blob/fef3402e674bebbf72a23aeb735e91c92cd34afd/src/utils/tag-stripping.ts#L6)). 로그에 남는 Bash 명령은 redaction을 거칩니다.
   - 로컬 삭제는 `DELETE /api/observation/:id` 등이고, 클라우드 동기화용 tombstone을 남깁니다([DataRoutes L212](https://github.com/thedotmack/claude-mem/blob/fef3402e674bebbf72a23aeb735e91c92cd34afd/src/services/worker/http/routes/DataRoutes.ts#L212)).
   - server runtime에는 team 단위 삭제(erasure) 경로가 있습니다([data-deletion L3](https://github.com/thedotmack/claude-mem/blob/fef3402e674bebbf72a23aeb735e91c92cd34afd/src/storage/postgres/data-deletion.ts#L3)).
   - 텔레메트리는 opt-out 기본값이며 `DO_NOT_TRACK`을 존중합니다([consent L9](https://github.com/thedotmack/claude-mem/blob/fef3402e674bebbf72a23aeb735e91c92cd34afd/src/services/telemetry/consent.ts#L9)).
8. **설치**: Claude 플러그인 마케트플레이스(`.claude-plugin/marketplace.json`)나 npm `claude-mem` CLI(`src/npx-cli/commands/install.ts`)로 설치합니다. Cursor, Codex, Windsurf, OpenCode 등 hook 설치기도 `src/services/integrations/*`에 있습니다.

## 2. basicmachines-co/basic-memory

1. **기본 정보**: Python, AGPL-3.0, ★약 4천, 2026-10-14에 push. 고정 커밋은 `54b8d94`입니다.
2. **쓰기 경로 (에이전트가 판단, hook은 기록만)**
   - [hooks/__init__.py](https://github.com/basicmachines-co/basic-memory/blob/54b8d94b94cb8e4e526f438010ca771c5ad9f209/src/basic_memory/hooks/__init__.py#L3)에 설계 원칙이 명시되어 있습니다: *"Capture is dumb … durable knowledge is written separately by an active agent"*.
   - hook은 `~/.basic-memory/inbox/<uuid7>.json` WAL에 append만 합니다([inbox.py](https://github.com/basicmachines-co/basic-memory/blob/54b8d94b94cb8e4e526f438010ca771c5ad9f209/src/basic_memory/hooks/inbox.py#L1)).
   - PreCompact hook은 transcript에서 첫 요청과 최근 턴을 **LLM 없이 추출**해 checkpoint 노트를 씁니다([`_checkpoint_note`](https://github.com/basicmachines-co/basic-memory/blob/54b8d94b94cb8e4e526f438010ca771c5ad9f209/src/basic_memory/cli/commands/hook.py#L1048)). `primaryProject`가 설정되지 않으면 아무것도 하지 않습니다([L1238-L1243](https://github.com/basicmachines-co/basic-memory/blob/54b8d94b94cb8e4e526f438010ca771c5ad9f209/src/basic_memory/cli/commands/hook.py#L1238)).
   - 지식 기록은 에이전트가 MCP `write_note`를 호출해서 합니다([L303](https://github.com/basicmachines-co/basic-memory/blob/54b8d94b94cb8e4e526f438010ca771c5ad9f209/src/basic_memory/mcp/tools/write_note.py#L303)).
3. **갱신**
   - `write_note`는 기본적으로 덮어쓰기를 거부합니다. `overwrite=True`에 `expected_checksum`을 함께 주는 조건부 덮어쓰기(낙관적 동시성)를 지원합니다.
   - 관계는 Markdown 안의 `[[wikilink]]`/relation 문법을 파싱해 그래프로 만듭니다(`markdown/entity_parser.py`). 서버 LLM의 통합 단계는 없습니다.
4. **검색**
   - SQLite에서는 FTS5와 sqlite-vec를 씁니다([sqlite_search_repository](https://github.com/basicmachines-co/basic-memory/blob/54b8d94b94cb8e4e526f438010ca771c5ad9f209/src/basic_memory/repository/sqlite_search_repository.py#L1)). Postgres에서는 tsvector와 pgvector/Milvus를 씁니다.
   - 하이브리드 검색은 [`_semantic_search`](https://github.com/basicmachines-co/basic-memory/blob/54b8d94b94cb8e4e526f438010ca771c5ad9f209/src/basic_memory/repository/search_repository_base.py#L377)입니다.
   - 임베딩 기본값은 로컬 `fastembed bge-small-en-v1.5`이고([config_models L280](https://github.com/basicmachines-co/basic-memory/blob/54b8d94b94cb8e4e526f438010ca771c5ad9f209/src/basic_memory/config_models.py#L280)), reranker는 기본 off입니다([L419](https://github.com/basicmachines-co/basic-memory/blob/54b8d94b94cb8e4e526f438010ca771c5ad9f209/src/basic_memory/config_models.py#L419)).
   - 주입: SessionStart hook이 brief를 stdout으로 내보냅니다([plugin hooks.json](https://github.com/basicmachines-co/basic-memory/blob/54b8d94b94cb8e4e526f438010ca771c5ad9f209/plugins/claude-code/hooks/hooks.json)). 이와 별도로 `search_notes`/`build_context` MCP 도구가 있습니다.
5. **저장소**: 원본은 Markdown 파일이고, 인덱스는 SQLite입니다(`database_backend` 기본값 SQLITE, [L223](https://github.com/basicmachines-co/basic-memory/blob/54b8d94b94cb8e4e526f438010ca771c5ad9f209/src/basic_memory/config_models.py#L223)). Docker는 필요 없습니다.
6. **로컬과 클라우드의 차이**
   - 프로젝트마다 `ProjectMode.LOCAL/CLOUD` 라우팅을 둡니다. 로컬 설정에 없는 프로젝트는 기본으로 CLOUD로 라우팅됩니다([L833-L841](https://github.com/basicmachines-co/basic-memory/blob/54b8d94b94cb8e4e526f438010ca771c5ad9f209/src/basic_memory/config_models.py#L833)).
   - 클라우드 쪽: `cloud_host=https://cloud.basicmemory.com`, `bmc_` API key, rclone bisync/WebDAV 동기화를 씁니다(`cli/commands/cloud/*`).
   - 클라우드 컨테이너는 `BASIC_MEMORY_CLOUD_MODE`로 로컬 파일 인덱싱을 끄고, Postgres와 객체 스토리지를 씁니다([runtime/mode.py L51](https://github.com/basicmachines-co/basic-memory/blob/54b8d94b94cb8e4e526f438010ca771c5ad9f209/src/basic_memory/runtime/mode.py#L51)).
   - 로컬 모드는 LLM API를 호출하지 않습니다.
7. **삭제·개인정보**: `delete_note`는 영구 삭제입니다([L139](https://github.com/basicmachines-co/basic-memory/blob/54b8d94b94cb8e4e526f438010ca771c5ad9f209/src/basic_memory/mcp/tools/delete_note.py#L139)). inbox WAL은 owner 전용 권한으로 만들고, 처리된 항목은 30일 보존 후 정리합니다. 이 밖에 `redaction.py`가 있습니다.
8. **설치**: PyPI `basic-memory`(`bm` CLI). Claude Code 플러그인은 `plugins/claude-code`이며 hook 실행에 `uv run --script`를 씁니다.

## 3. doobidoo/mcp-memory-service

1. **기본 정보**: Python, Apache-2.0, ★약 2천, 2026-10-14에 push. 고정 커밋은 `1a5da67`입니다.
2. **쓰기 경로 (Hook과 규칙 기반 추출)**
   - [plugin hooks.json](https://github.com/doobidoo/mcp-memory-service/blob/1a5da675c5dcb976582bb7141ad0150c7fc9f76c/claude-hooks/.claude-plugin/hooks.json): SessionStart(서버 기동과 주입), UserPromptSubmit(mid-conversation), Stop(auto-capture), SessionEnd.
   - [auto-capture-hook.js](https://github.com/doobidoo/mcp-memory-service/blob/1a5da675c5dcb976582bb7141ad0150c7fc9f76c/claude-hooks/core/auto-capture-hook.js#L6)는 decision/error/learning **패턴(regex)**을 감지해 HTTP로 저장합니다([`storeMemory` L208](https://github.com/doobidoo/mcp-memory-service/blob/1a5da675c5dcb976582bb7141ad0150c7fc9f76c/claude-hooks/core/auto-capture-hook.js#L208)).
   - SessionEnd의 [`analyzeConversation`](https://github.com/doobidoo/mcp-memory-service/blob/1a5da675c5dcb976582bb7141ad0150c7fc9f76c/claude-hooks/core/session-end.js#L53)은 키워드 regex로 요약을 만듭니다.
   - 서버 쪽 harvest는 [PatternExtractor](https://github.com/doobidoo/mcp-memory-service/blob/1a5da675c5dcb976582bb7141ad0150c7fc9f76c/src/mcp_memory_service/harvest/extractor.py#L1)를 쓰고, 선택적으로 [LLM 분류기(Groq 등)](https://github.com/doobidoo/mcp-memory-service/blob/1a5da675c5dcb976582bb7141ad0150c7fc9f76c/src/mcp_memory_service/harvest/classifier.py#L1)를 붙일 수 있습니다. 키가 없으면 regex 결과를 그대로 씁니다.
   - 에이전트가 MCP `store_memory`로 명시적으로 저장하는 경로도 있습니다.
3. **갱신·통합**
   - 저장 시 content_hash 중복 검사와 [`_check_semantic_duplicate`](https://github.com/doobidoo/mcp-memory-service/blob/1a5da675c5dcb976582bb7141ad0150c7fc9f76c/src/mcp_memory_service/storage/mixins/store.py#L50)(24시간 이내, 유사도 0.85)를 거칩니다.
   - [`contradictions.py`](https://github.com/doobidoo/mcp-memory-service/blob/1a5da675c5dcb976582bb7141ad0150c7fc9f76c/src/mcp_memory_service/consolidation/contradictions.py#L1)는 임베딩 유사도 0.4–0.75 구간을 `contradicts` 엣지로 만들고 이전 메모리를 supersede합니다. 기본은 꺼져 있습니다.
   - [`DreamInspiredConsolidator`](https://github.com/doobidoo/mcp-memory-service/blob/1a5da675c5dcb976582bb7141ad0150c7fc9f76c/src/mcp_memory_service/consolidation/consolidator.py#L213)는 decay, clustering, association, compression, forgetting 단계를 돌립니다.
4. **검색**: [HybridMixin](https://github.com/doobidoo/mcp-memory-service/blob/1a5da675c5dcb976582bb7141ad0150c7fc9f76c/src/mcp_memory_service/storage/mixins/hybrid.py#L1)이 BM25(FTS5)와 벡터 결과를 가중합 또는 RRF로 합칩니다. 임베딩 기본값은 로컬 ONNX `all-MiniLM-L6-v2`입니다. SessionStart hook은 git 맥락, 최근 메모리, 태그 순으로 단계별 점수를 매겨 주입합니다.
5. **저장소**: 기본은 `sqlite_vec`입니다([config/base.py L357](https://github.com/doobidoo/mcp-memory-service/blob/1a5da675c5dcb976582bb7141ad0150c7fc9f76c/src/mcp_memory_service/config/base.py#L357)). 그 외에 `cloudflare`, `hybrid`, `milvus`를 선택할 수 있습니다. 기본 경로에 Docker는 필요 없습니다.
6. **로컬과 클라우드의 차이**
   - `cloudflare` 백엔드는 D1, Vectorize, R2와 Workers AI 임베딩(`@cf/baai/bge-base-en-v1.5`)을 쓰며, API token과 account id가 필수입니다([config/storage.py L170-L195](https://github.com/doobidoo/mcp-memory-service/blob/1a5da675c5dcb976582bb7141ad0150c7fc9f76c/src/mcp_memory_service/config/storage.py#L170)).
   - `hybrid`는 로컬 sqlite-vec를 주 저장소로 두고 Cloudflare로 백그라운드 동기화합니다([hybrid.py](https://github.com/doobidoo/mcp-memory-service/blob/1a5da675c5dcb976582bb7141ad0150c7fc9f76c/src/mcp_memory_service/storage/hybrid.py#L15)).
   - 원격 HTTP 모드에는 OAuth 2.1이 있습니다(`web/oauth/*`).
   - 로컬 기본 구성은 LLM 호출이 없습니다.
7. **삭제**: soft-delete(`deleted_at` tombstone)이고, `purge_deleted(30일)`로 영구 삭제합니다([delete.py](https://github.com/doobidoo/mcp-memory-service/blob/1a5da675c5dcb976582bb7141ad0150c7fc9f76c/src/mcp_memory_service/storage/mixins/delete.py#L24)). 태그나 기간 단위로도 일괄 삭제할 수 있습니다.
8. **설치**: PyPI `mcp-memory-service`(`memory` 및 `mcp-memory-server` 스크립트)와 `claude-hooks` 플러그인.

## 4. modelcontextprotocol/servers `src/memory` (레퍼런스 지식그래프 서버)

1. **기본 정보**: TypeScript. 라이선스는 MIT에서 Apache-2.0으로 전환 중입니다. ★약 9만(모노레포 전체). 고정 커밋은 `bbb701e`입니다.
2. **쓰기 경로**: 에이전트가 `create_entities`, `create_relations`, `add_observations`를 직접 호출합니다. hook도 LLM도 없습니다.
3. **갱신**: [`createEntities`](https://github.com/modelcontextprotocol/servers/blob/bbb701e7ac1e57f3edd1c2836b94c5457eaf7b9c/src/memory/index.ts#L517)는 같은 이름의 엔티티를 건너뛰는 것이 전부입니다. 모순이나 시간 개념은 없습니다.
4. **검색**: [`searchNodes`](https://github.com/modelcontextprotocol/servers/blob/bbb701e7ac1e57f3edd1c2836b94c5457eaf7b9c/src/memory/index.ts#L655)는 `toLowerCase().includes()` 부분 문자열 매칭입니다.
5. **저장소**: 단일 JSONL 파일(`MEMORY_FILE_PATH`, [L51](https://github.com/modelcontextprotocol/servers/blob/bbb701e7ac1e57f3edd1c2836b94c5457eaf7b9c/src/memory/index.ts#L51)). 파일 lock을 쓰며, Docker는 선택 사항입니다.
6. **로컬과 클라우드**: 로컬 전용입니다.
7. **삭제**: `delete_entities`, `delete_observations`로 하드 삭제합니다.
8. **설치**: npx `@modelcontextprotocol/server-memory`(`mcp-server-memory` bin).

## 5. Cipher (campfirein/cipher → byterover-cli, 아카이브) 및 현행 ByteRover CLI

1. **기본 정보**: TypeScript, Elastic License 2.0. ★약 5천. 저장소는 아카이브되었습니다. Cipher 코드는 `cipher-final` 태그(`ddbb782`, 2026-03-16)에만 있고, 현재 HEAD(`1052ac1`)는 ByteRover CLI v3입니다.
2. **Cipher의 쓰기 경로 (서버 LLM이 매 턴 강제 실행)**
   - 기본 MCP 모드는 `ask_cipher` 하나만 노출합니다([mcp_handler L85-L95](https://github.com/campfirein/byterover-cli/blob/ddbb782f8f53f710fbe3ce55a07e9f4a675ba628/src/app/mcp/mcp_handler.ts#L85)).
   - 응답 후 [`enforceMemoryExtraction`](https://github.com/campfirein/byterover-cli/blob/ddbb782f8f53f710fbe3ce55a07e9f4a675ba628/src/core/session/coversation-session.ts#L613)이 *"AI 판단과 무관하게 항상"* `extract_and_operate_memory`를 백그라운드에서 실행합니다.
3. **Cipher의 갱신**
   - [`extract_and_operate_memory`](https://github.com/campfirein/byterover-cli/blob/ddbb782f8f53f710fbe3ce55a07e9f4a675ba628/src/core/brain/tools/definitions/memory/extract_and_operate_memory.ts#L319)는 먼저 `isSignificantKnowledge` regex로 프로그래밍 관련 지식만 남깁니다.
   - 이어서 유사 메모리를 넣은 `DECISION_PROMPT`로 LLM이 **ADD/UPDATE/DELETE/NONE**을 결정합니다([L766-L800](https://github.com/campfirein/byterover-cli/blob/ddbb782f8f53f710fbe3ce55a07e9f4a675ba628/src/core/brain/tools/definitions/memory/extract_and_operate_memory.ts#L766)).
   - LLM이 실패할 때의 휴리스틱은 *"fact에 `not`이 있으면 DELETE"* 수준입니다([L845-L852](https://github.com/campfirein/byterover-cli/blob/ddbb782f8f53f710fbe3ce55a07e9f4a675ba628/src/core/brain/tools/definitions/memory/extract_and_operate_memory.ts#L845)).
4. **Cipher의 검색과 저장**
   - 벡터 저장소 기본값은 **in-memory**입니다. 그 밖에 Qdrant, Milvus, Chroma, pgvector, Pinecone, Redis, Weaviate, FAISS를 선택할 수 있습니다. 지식그래프는 neo4j 또는 in-memory이며 기본은 꺼져 있습니다([env.ts L60-L120](https://github.com/campfirein/byterover-cli/blob/ddbb782f8f53f710fbe3ce55a07e9f4a675ba628/src/core/env.ts#L60)).
   - 임베딩에는 OpenAI, Gemini, OpenRouter, Ollama 중 하나가 필수입니다([L436](https://github.com/campfirein/byterover-cli/blob/ddbb782f8f53f710fbe3ce55a07e9f4a675ba628/src/core/env.ts#L436)).
5. **ByteRover CLI v3 (현행)**
   - `.brv/context-tree` 아래 Markdown "context tree"를 씁니다([constants L1-L28](https://github.com/campfirein/byterover-cli/blob/1052ac1a5dd0fde4da8693d4712064f7876c269c/src/server/constants.ts#L1)).
   - `brv` 자체 LLM 에이전트가 `curate`로 ADD/UPDATE/UPSERT/MERGE/DELETE 연산을 만듭니다([curate-service](https://github.com/campfirein/byterover-cli/blob/1052ac1a5dd0fde4da8693d4712064f7876c269c/src/agent/infra/sandbox/curate-service.ts#L32)).
   - 검색은 MiniSearch(lexical)입니다.
   - Claude Code hook은 UserPromptSubmit에서 **지시문만** 주입합니다([hook-prompt-submit](https://github.com/campfirein/byterover-cli/blob/1052ac1a5dd0fde4da8693d4712064f7876c269c/src/oclif/commands/hook-prompt-submit.ts#L16)).
6. **로컬과 클라우드의 차이**
   - Cipher는 LLM과 임베딩 키가 반드시 필요했으므로, 로컬 모드도 기본적으로 외부 API로 데이터가 나갔습니다(Ollama는 예외).
   - ByteRover의 LLM provider 목록에서 priority 0은 "ByteRover account required" 내장 LLM입니다([provider-registry L98](https://github.com/campfirein/byterover-cli/blob/1052ac1a5dd0fde4da8693d4712064f7876c269c/src/server/core/domain/entities/provider-registry.ts#L98)). 이것이 기본값인지는 **[추론]**입니다.
   - 클라우드 push는 `byterover.dev` API의 `/organizations/{team}/projects/{space}/commits`로 갑니다([http-cogit-push-service L76](https://github.com/campfirein/byterover-cli/blob/1052ac1a5dd0fde4da8693d4712064f7876c269c/src/server/infra/cogit/http-cogit-push-service.ts#L76)).
7. **삭제·개인정보**: Cipher는 `REDACT_SECRETS` 기본값 true였습니다. ByteRover에는 큐레이트 결과를 승인/거부하는 review 워크플로가 있습니다 **[README-only]**.
8. **설치**: npm `byterover-cli`(`brv` bin).

## 6. alioshr/memory-bank-mcp

1. **기본 정보**: TypeScript, MIT, ★약 900, 2025-08 이후 활동 없음. 고정 커밋은 `559e422`입니다.
2. **쓰기 경로**: 에이전트가 `memory_bank_write`/`memory_bank_update`로 파일 전체를 씁니다([routes.ts](https://github.com/alioshr/memory-bank-mcp/blob/559e42274147bb60f263b24c496d54593fb7f807/src/main/protocols/mcp/routes.ts#L16)). 무엇을 쓸지는 에이전트 커스텀 규칙(Cline/Roo의 memory-bank 패턴)에 달려 있습니다.
3. **갱신**: `fs.writeFile`로 통째로 덮어씁니다([fs-file-repository L60-L99](https://github.com/alioshr/memory-bank-mcp/blob/559e42274147bb60f263b24c496d54593fb7f807/src/infra/filesystem/repositories/fs-file-repository.ts#L60)). 중복 제거나 모순 처리는 없습니다.
4. **검색**: 검색 기능이 없습니다. list와 read만 있습니다.
5. **저장소**: `MEMORY_BANK_ROOT/<project>/<file>` 형태의 디렉터리입니다([env.ts](https://github.com/alioshr/memory-bank-mcp/blob/559e42274147bb60f263b24c496d54593fb7f807/src/main/config/env.ts#L2)). path-security validator가 있습니다.
6. **로컬과 클라우드**: 로컬 전용입니다. "remote"라는 표현은 중앙 디렉터리를 뜻합니다.
7. **삭제**: 삭제 도구가 없습니다.
8. **설치**: npx `@allpepper/memory-bank-mcp`.

## 7. CaviraOSS/OpenMemory → **LongMemory** (재작성)

1. **기본 정보**: TypeScript, Apache-2.0, ★약 4.5천, 2026-09-20에 push. 고정 커밋은 `9ee2c8e`입니다. 패키지 이름이 `longmemory`로 바뀌었습니다.
2. **쓰기 경로 (규칙 기반 추출)**
   - 에이전트가 MCP `ingest`/`remember_decision` 도구를 호출합니다([remember_decision](https://github.com/CaviraOSS/LongMemory/blob/9ee2c8e1ed42d83eb788afb9ffc3a82b84405da5/src/mcp/tools/remember_decision.ts#L24)).
   - [claim_extractor](https://github.com/CaviraOSS/LongMemory/blob/9ee2c8e1ed42d83eb788afb9ffc3a82b84405da5/src/core/engine/claim_extractor.ts#L27)는 **정규식**(preference, location, copula)으로 SPO claim을 뽑습니다. LLM은 쓰지 않습니다.
3. **갱신**: [`IngestEngine`](https://github.com/CaviraOSS/LongMemory/blob/9ee2c8e1ed42d83eb788afb9ffc3a82b84405da5/src/core/engine/ingest_engine.ts#L112)은 claim이 충돌하면 `supersedes`/`contradicts` 엣지를 만듭니다(L420-L425). bitemporal/MVCC 모듈(`core/temporal/*`)이 있습니다.
4. **검색**: `core/recall/*`에서 fusion, rerank, activation spread를 씁니다. 임베딩 기본값은 **synthetic**(외부 호출 없음)이고, openai/gemini/ollama/aws 등은 선택입니다([environment.ts L44](https://github.com/CaviraOSS/LongMemory/blob/9ee2c8e1ed42d83eb788afb9ffc3a82b84405da5/src/core/embeddings/environment.ts#L44)).
5. **저장소**: better-sqlite3 `./longmemory.db`([server/config L82](https://github.com/CaviraOSS/LongMemory/blob/9ee2c8e1ed42d83eb788afb9ffc3a82b84405da5/src/server/config.ts#L82)). Dockerfile, docker-compose, DigitalOcean 배포 스펙은 선택 사항입니다.
6. **로컬과 클라우드**: 기본 바인딩은 `127.0.0.1:7331`이고 API key는 선택입니다. 키가 없으면 인증을 하지 않습니다([auth.ts L26-L31](https://github.com/CaviraOSS/LongMemory/blob/9ee2c8e1ed42d83eb788afb9ffc3a82b84405da5/src/server/middleware/auth.ts#L26)). 호스팱 SaaS 코드는 보지 못했습니다.
7. **개인정보**: MCP 도구 allowlist, 권한, audit 모듈이 있습니다(`src/mcp/security/*`).
8. **설치**: npm `longmemory`(bin). Claude Code 연동은 `.mcp.json`과 skill뿐이며 hook은 없습니다([.mcp.json](https://github.com/CaviraOSS/LongMemory/blob/9ee2c8e1ed42d83eb788afb9ffc3a82b84405da5/integrations/claude-code-longmemory/.mcp.json)).

## 8. coleam00/mcp-mem0 (+ 공식 mem0ai/mem0-mcp)

1. **기본 정보**: mcp-mem0은 Python, MIT, ★약 700, 2025-04 이후 활동 없음, 고정 커밋 `22fb7af`입니다. 공식 `mem0ai/mem0-mcp`는 Apache-2.0이며 아카이브되었습니다.
2. **쓰기 경로**
   - 에이전트가 `save_memory`를 호출하면 `mem0.add()`가 실행되며, 기본값이 `infer=True`입니다([main.py L53-L67](https://github.com/coleam00/mcp-mem0/blob/22fb7af0432e15fbe379ad7c7c7beac911fa2648/src/main.py#L53)).
   - uv.lock이 `mem0ai 0.1.88`로 고정되어 있습니다([uv.lock L418](https://github.com/coleam00/mcp-mem0/blob/22fb7af0432e15fbe379ad7c7c7beac911fa2648/uv.lock#L418)). 이 버전에서는 서버 LLM이 다음 두 단계로 판단합니다.
     - `get_fact_retrieval_messages`로 fact를 추출합니다.
     - `get_update_memory_messages`로 **ADD/UPDATE/DELETE/NONE**을 결정합니다([mem0 v0.1.88 main.py L187-L310](https://github.com/mem0ai/mem0/blob/3cc794fb9852cda704af5bd1601a888e9d170980/mem0/memory/main.py#L187)).
   - 참고: 현재 mem0 HEAD는 `ADDITIVE_EXTRACTION_PROMPT`와 md5 중복 제거를 쓰는 additive 방식으로 바뀌었습니다([HEAD main.py L944-L1024](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/mem0/memory/main.py#L944)).
3. **검색·저장**: 벡터 검색만 합니다. 저장소는 **Supabase/Postgres(pgvector)**로 고정되어 있습니다(`DATABASE_URL`, [utils.py L89-L97](https://github.com/coleam00/mcp-mem0/blob/22fb7af0432e15fbe379ad7c7c7beac911fa2648/src/utils.py#L89)). user_id는 `"user"`로 하드코딩되어 단일 사용자입니다.
4. **로컬과 클라우드**
   - mcp-mem0은 LLM_PROVIDER로 openai, openrouter, ollama를 고를 수 있습니다. Ollama를 쓰면 외부 API 호출 없이 동작할 수 있습니다.
   - 공식 mem0-mcp는 `MemoryClient`(호스팅 플랫폼)와 `MEM0_API_KEY`가 필수입니다([server.py L13-L64](https://github.com/mem0ai/mem0-mcp/blob/624024deacbbe1948572a968abdb9d9e93ded548/src/mem0_mcp_server/server.py#L13)). 즉 클라우드 전용이며 `enable_graph` 옵션이 있습니다.
5. **삭제**: mcp-mem0에는 삭제 도구가 없습니다. 공식 서버에는 `delete_memory`/`delete_all_memories`가 있습니다.
6. **설치**: mcp-mem0은 uv와 Dockerfile(SSE)입니다. 공식 서버는 Smithery 또는 HTTP입니다.

## 9. GreatScottyMac/context-portal (ConPort)

1. **기본 정보**: Python, Apache-2.0, ★약 800, 2026-01에 push. 고정 커밋은 `18bde46`입니다.
2. **쓰기 경로**: 에이전트가 `log_decision`, `log_progress`, `log_system_pattern`, `log_custom_data`, `link_conport_items` 같은 도구를 호출합니다([main.py L330 이하](https://github.com/GreatScottyMac/context-portal/blob/18bde469feb03c233d11c9a4941bd27bd859a5ff/src/context_portal_mcp/main.py#L330)). 언제 무엇을 기록할지는 `conport-custom-instructions/*` 규칙 프롬프트가 정합니다.
3. **갱신**: `get_item_history`(버전 이력)와 수동 링크 기능이 있습니다. 자동 중복 제거는 없습니다.
4. **검색**: SQLite FTS5([database.py L280](https://github.com/GreatScottyMac/context-portal/blob/18bde469feb03c233d11c9a4941bd27bd859a5ff/src/context_portal_mcp/db/database.py#L280))와, sentence-transformers `all-MiniLM-L6-v2`에 Chroma PersistentClient를 쓴 시맨틱 검색입니다([vector_store_service L59-L79](https://github.com/GreatScottyMac/context-portal/blob/18bde469feb03c233d11c9a4941bd27bd859a5ff/src/context_portal_mcp/db/vector_store_service.py#L59)).
5. **저장소**: 워크스페이스 안 `context_portal/` 폴더에 SQLite와 Chroma 파일을 둡니다. Docker는 필요 없습니다.
6. **로컬과 클라우드**: 로컬 전용이며 외부 API 호출이 없습니다. 첫 실행 때 임베딩 모델을 다운로드합니다.
7. **삭제**: `delete_*_by_id`로 하드 삭제합니다.
8. **설치**: PyPI `context-portal-mcp`(`conport-mcp`), uvx.

## 10. oraios/serena (memories)

1. **기본 정보**: Python. Serena 본체는 GPL-3.0-or-later, SolidLSP는 MIT입니다. ★약 3만. 고정 커밋은 `4f2520e`입니다.
2. **쓰기 경로**: 에이전트가 `write_memory`/`edit_memory`(regex 치환)로 Markdown을 씁니다([memory_tools L24](https://github.com/oraios/serena/blob/4f2520efb128dd02e66a2302095bdbbb26ddd5a0/src/serena/tools/memory_tools.py#L24)). `OnboardingTool`이 초기 메모리 작성을 유도합니다([workflow_tools L10](https://github.com/oraios/serena/blob/4f2520efb128dd02e66a2302095bdbbb26ddd5a0/src/serena/tools/workflow_tools.py#L10)).
3. **갱신**: `rename_memory`는 `mem:` 참조까지 갱신하고 참조 무결성을 검사합니다([memory_manager](https://github.com/oraios/serena/blob/4f2520efb128dd02e66a2302095bdbbb26ddd5a0/src/serena/memories/memory_manager.py#L28)).
4. **검색**: `list_memories(topic)`로 이름 목록을 보여 주고, 에이전트가 이름으로 관련성을 추론해 `read_memory`를 호출합니다. 인덱스는 없습니다.
5. **저장소**: 프로젝트의 `.serena/memories/*.md`와 전역 `global/` 디렉터리입니다.
6. **로컬과 클라우드**: 로컬 전용입니다.
7. **삭제**: `delete_memory`는 *"사용자의 명시적 지시나 허가가 있을 때만"* 호출하도록 도구 설명에 적혀 있습니다([L69-L76](https://github.com/oraios/serena/blob/4f2520efb128dd02e66a2302095bdbbb26ddd5a0/src/serena/tools/memory_tools.py#L69)).
8. **설치**: uvx와 MCP.

## 11. Gentleman-Programming/engram (추가 발견, 우리 설계와 가장 가까움)

1. **기본 정보**: Go, MIT, ★약 7천, 2026-10-15에 push. 고정 커밋은 `7c5da99`입니다.
2. **쓰기 경로**
   - 주 경로는 에이전트가 `mem_save`를 호출하는 것입니다([mcp.go L501](https://github.com/Gentleman-Programming/engram/blob/7c5da99fe28c9c721763fa015d3eb35951b22a76/internal/mcp/mcp.go#L501)).
   - 수동 캡처 hook도 있습니다. SubagentStop이 출력을 `/observations/passive`로 POST하고([subagent-stop.sh](https://github.com/Gentleman-Programming/engram/blob/7c5da99fe28c9c721763fa015d3eb35951b22a76/plugin/claude-code/scripts/subagent-stop.sh#L26)), 서버는 `## Key Learnings:` 섹션을 **규칙으로 파싱**합니다([`ExtractLearnings`](https://github.com/Gentleman-Programming/engram/blob/7c5da99fe28c9c721763fa015d3eb35951b22a76/internal/store/store.go#L13489)).
3. **갱신**
   - `topic_key`가 같으면 upsert하고 revision을 기록합니다([store.go L4273](https://github.com/Gentleman-Programming/engram/blob/7c5da99fe28c9c721763fa015d3eb35951b22a76/internal/store/store.go#L4273)).
   - 충돌하면 `mem_save`가 `judgment_required`와 candidates를 반환하고, **에이전트가 `mem_judge`로 판정**합니다([L1080](https://github.com/Gentleman-Programming/engram/blob/7c5da99fe28c9c721763fa015d3eb35951b22a76/internal/mcp/mcp.go#L1080)).
   - `mem_compare`는 *"판단은 당신(에이전트 LLM)이 하고, 기록만 한다"*는 도구입니다([L1151](https://github.com/Gentleman-Programming/engram/blob/7c5da99fe28c9c721763fa015d3eb35951b22a76/internal/mcp/mcp.go#L1151)).
   - 선택적으로 `ENGRAM_AGENT_CLI=claude|opencode`를 설정하면 CLI를 호출해 판정을 맡깁니다([llm/factory.go](https://github.com/Gentleman-Programming/engram/blob/7c5da99fe28c9c721763fa015d3eb35951b22a76/internal/llm/factory.go#L30)).
4. **검색**: SQLite FTS5([L1449](https://github.com/Gentleman-Programming/engram/blob/7c5da99fe28c9c721763fa015d3eb35951b22a76/internal/store/store.go#L1449))이며 벡터 검색은 없습니다. SessionStart와 compaction 이후 hook이 context를 주입합니다([hooks.json](https://github.com/Gentleman-Programming/engram/blob/7c5da99fe28c9c721763fa015d3eb35951b22a76/plugin/claude-code/hooks/hooks.json)).
5. **저장소**: 로컬 SQLite 단일 바이너리이며 Docker는 필요 없습니다.
6. **로컬과 클라우드**
   - "engram cloud"는 Postgres(pgx) 기반 동기화 서버입니다([cloudstore L40](https://github.com/Gentleman-Programming/engram/blob/7c5da99fe28c9c721763fa015d3eb35951b22a76/internal/cloud/cloudstore/cloudstore.go#L40)). JWT, admin, 프로젝트 허용 목록 설정이 있습니다.
   - 기본 DSN과 JWT secret이 dev 값입니다([cloud/config.go L26-L31](https://github.com/Gentleman-Programming/engram/blob/7c5da99fe28c9c721763fa015d3eb35951b22a76/internal/cloud/config.go#L26)).
   - 별도의 호스팅 SaaS 여부는 확인하지 못했습니다 **[추론: self-host용]**.
7. **삭제**: `mem_delete`는 기본 soft-delete이고 `hard_delete=true`로 영구 삭제합니다([L663](https://github.com/Gentleman-Programming/engram/blob/7c5da99fe28c9c721763fa015d3eb35951b22a76/internal/mcp/mcp.go#L663)).
8. **설치**: Claude 마케트플레이스 플러그인, Codex, OpenCode, Pi 등의 플러그인과 Go 바이너리.

## 12. supermemoryai/claude-supermemory (추가 발견, 클라우드 전용 대조군)

1. **기본 정보**: JS, LICENSE 파일 없음, ★약 2.8천, 2026-10-14에 push. 고정 커밋은 `8e98cb4`입니다.
2. **쓰기 경로**: Stop hook(async)이 transcript의 증분을 `redactSecrets`로 처리한 뒤, `entityContext`(EXTRACT/SKIP 규칙 프롬프트)와 함께 `POST /v3/documents`로 보냅니다([capture.js L84-L103](https://github.com/supermemoryai/claude-supermemory/blob/8e98cb48b5574bc68375754735ba05cad1545b17/plugin/hooks/capture.js#L84), [api.js L1-L21](https://github.com/supermemoryai/claude-supermemory/blob/8e98cb48b5574bc68375754735ba05cad1545b17/plugin/hooks/lib/api.js#L1)). 무엇을 기억할지는 **Supermemory 클라우드의 LLM**이 정합니다.
3. **검색**: SessionStart는 `/v4/profile`, UserPromptSubmit은 recall-directive로 자동 주입합니다([hooks.json](https://github.com/supermemoryai/claude-supermemory/blob/8e98cb48b5574bc68375754735ba05cad1545b17/plugin/hooks/hooks.json)). MCP는 로컬 proxy입니다.
4. **저장·클라우드**: `BASE_URL=https://api.supermemory.ai`가 기본이고, `SUPERMEMORY_API_URL`로 바꿀 수 있습니다([auth.js L7-L82](https://github.com/supermemoryai/claude-supermemory/blob/8e98cb48b5574bc68375754735ba05cad1545b17/plugin/hooks/lib/auth.js#L7)). 로컬 저장소는 없습니다.
5. **개인정보**: 클라이언트 쪽에서 키, 토큰, private key, URL 자격증명을 마스킹합니다([redact.js](https://github.com/supermemoryai/claude-supermemory/blob/8e98cb48b5574bc68375754735ba05cad1545b17/plugin/hooks/lib/redact.js#L1)).
6. **설치**: Claude 플러그인 마케트플레이스.

## 13. steveyegge/beads → gastownhall/beads (추가 발견)

1. **기본 정보**: Go, MIT, ★약 2.8만. 고정 커밋은 `7838c4b`입니다. 본체는 이슈 트래커이고, 메모리는 부가 기능입니다.
2. **쓰기 경로**: 에이전트가 CLI `bd remember "<insight>" --key`를 실행합니다. 같은 key면 in-place로 갱신하고, 전체 메모리 용량(budget)을 넘으면 거부합니다([memory.go L347](https://github.com/gastownhall/beads/blob/7838c4b44992be20ad4b52db1a3d6f68e957c1af/cmd/bd/memory.go#L347)).
3. **검색·주입**: SessionStart와 PreCompact hook에서 `bd prime --memories-only --hook-json`이 실행되어 주입합니다([prime.go L90-L130](https://github.com/gastownhall/beads/blob/7838c4b44992be20ad4b52db1a3d6f68e957c1af/cmd/bd/prime.go#L90)). `bd memories <keyword>`로 검색합니다.
4. **저장**: Dolt(버전 관리 SQL)입니다. embedded와 server 모드가 있습니다(`internal/doltserver`).
5. **LLM 사용**: 오래된 이슈 compaction에 Anthropic API(Haiku)를 쓰며 `ANTHROPIC_API_KEY`가 필요합니다([compact/haiku.go L47](https://github.com/gastownhall/beads/blob/7838c4b44992be20ad4b52db1a3d6f68e957c1af/internal/compact/haiku.go#L47)).
6. **삭제**: `bd forget <key>`.

## 14. openai/codex 내장 Memories (추가 발견)

1. **기본 정보**: Rust, Apache-2.0, ★약 13만. 고정 커밋은 `ac9db7d`입니다.
2. **쓰기 경로 (세션 시작 시 백그라운드 LLM 2단계)**
   - Phase 1: 유휴 상태가 된 rollout을 모델에 보내 `raw_memory`와 `rollout_summary`를 추출하고, 비밀값을 redaction합니다([README L40-L77](https://github.com/openai/codex/blob/ac9db7d8b556c7c34a73793aed34b1f980a4fe39/codex-rs/memories/README.md#L40), [phase1.rs L162](https://github.com/openai/codex/blob/ac9db7d8b556c7c34a73793aed34b1f980a4fe39/codex-rs/memories/write/src/phase1.rs#L162)).
   - Phase 2: 통합 서브에이전트가 no approval, no network, 로컬 쓰기만 허용된 상태에서 `~/.codex/memories`(`MEMORY.md`, `memory_summary.md`, `skills/`)를 git diff 기반으로 갱신합니다([README L79-L121](https://github.com/openai/codex/blob/ac9db7d8b556c7c34a73793aed34b1f980a4fe39/codex-rs/memories/README.md#L79), [phase2.rs L314-L351](https://github.com/openai/codex/blob/ac9db7d8b556c7c34a73793aed34b1f980a4fe39/codex-rs/memories/write/src/phase2.rs#L314)).
   - 사용 횟수와 마지막 사용 시각으로 순위를 매기고, `max_unused_days` 기준으로 정리합니다.
3. **저장**: 상태 DB(SQLite)와 파일 디렉터리입니다. 원격 엔드포인트 `/api/codex/memories/trace_summarize`도 있습니다([endpoint/memories.rs](https://github.com/openai/codex/blob/ac9db7d8b556c7c34a73793aed34b1f980a4fe39/codex-rs/codex-api/src/endpoint/memories.rs#L32)).
4. **로컬과 클라우드**: 추출과 통합은 설정된 모델 provider(기본 OpenAI)로 갑니다. 즉 대화 내용이 provider로 전송됩니다.

## 15. Digital-Process-Tools/claude-remember (Anthropic 공식 마케트플레이스 등록)

- 공식 마케트플레이스 `anthropics/claude-plugins-official`에 등록되어 있습니다([marketplace.json L3210](https://github.com/anthropics/claude-plugins-official/blob/c2bdb427efe8673f190ae862c273cfa368d2390f/.claude-plugin/marketplace.json#L3210)). 등록 시 고정 커밋은 `a5cc87c`, ★약 200입니다.
- hook 구성: SessionStart, UserPromptSubmit, PostToolUse, SessionEnd.
- **중첩 `claude -p --model haiku`**(또는 `codex exec`)로 대화를 요약하고 압축합니다. 모델이 `SKIP`을 반환하면 저장하지 않습니다([pipeline/haiku.py L71, L797-L802, L936](https://github.com/Digital-Process-Tools/claude-remember/blob/a5cc87c35567cff2ff603f598fc8a7134971a280/pipeline/haiku.py#L71)).
- 저장은 계층형 일별 로그 파일이며, 선택적으로 git 백업 hook을 씁니다.

## 16. tigerless-labs/agent-memory (추가 발견, 출처 범위 기반)

- Python, MIT, ★약 3.6천. 고정 커밋은 `7c4a00d`입니다.
- 경계 hook이 증분을 아카이브하고 watermark를 전진시킨 뒤, `mem record ... --provenance <message range>` 지시문을 만듭니다([capture.py L1-L46](https://github.com/tigerless-labs/agent-memory/blob/7c4a00da12703f777b14965c3224655fc7503540/packages/adapters/src/agent_memory/adapters/capture.py#L1)).
- 실제 기록 결정은 **호스트 CLI를 headless로 띄운 별도 executor 프로세스**가 합니다([hook_entry.py `launch_distill` L181](https://github.com/tigerless-labs/agent-memory/blob/7c4a00da12703f777b14965c3224655fc7503540/packages/adapters/src/agent_memory/adapters/hook_entry.py#L181)).
- 원본은 Markdown이고 인덱스는 SQLite FTS5와 벡터입니다([database.py](https://github.com/tigerless-labs/agent-memory/blob/7c4a00da12703f777b14965c3224655fc7503540/packages/core/src/agent_memory/core/database.py#L46)).

## 17. mksglu/context-mode (참고: 세션 연속성 계열)

- ELv2, ★약 2.9만. 고정 커밋은 `655c67f`입니다.
- tool 호출에서 13개 카테고리 이벤트를 **순수 규칙**으로 추출합니다([session/extract.ts](https://github.com/mksglu/context-mode/blob/655c67f9e1bb2d1c2a6db850447f1cfdcbbb1220/src/session/extract.ts#L1)).
- 저장과 검색은 SQLite FTS5(porter와 trigram 토크나이저, RRF 결합)입니다([store.ts L475, L1359](https://github.com/mksglu/context-mode/blob/655c67f9e1bb2d1c2a6db850447f1cfdcbbb1220/src/store.ts#L475)).
- compaction 이후 XML snapshot을 주입합니다([snapshot.ts](https://github.com/mksglu/context-mode/blob/655c67f9e1bb2d1c2a6db850447f1cfdcbbb1220/src/session/snapshot.ts#L1)). LLM은 쓰지 않습니다.

---

## 발견했지만 깊게 읽지 않은 프로젝트

- **코드 일부만 확인**
  - vshulcz/deja-vu(Go, ★1.2k): tree만 확인했습니다.
  - DeusData/codebase-memory-mcp(★4.7만): 코드 인덱스 그래프로, 세션 메모리와는 성격이 다릅니다.
- **미조사**
  - kitfunso/hippo-memory, Dataojitori/nocturne_memory, mkreyman/mcp-memory-keeper, memory-graph/memory-graph, 0xK3vin/MegaMemory, agentic-box/memora, yoloshii/ClawMem, majiayu000/remem, sdsrss/claude-mem-lite, davegoldblatt/total-recall, EliaAlberti/cpr-compress-preserve-resume, severity1/claude-code-auto-memory, Lyellr88/marm-memory, okf-memory/okf-agent-memory, Jakedismo/KuzuMem-MCP, mathomhaus/guild, pax-beehive/paxm
  - memory-bank 계열 포크: tuncer-byte, ipospelov, aakarsh-sasi
- **엔진 카테고리와 중복 [추론]**: getzep/graphiti MCP, mem0ai/mem0의 openmemory, cognee-mcp, MemTensor.
- **조사 범위 밖**: Claude Code 내장 auto-memory는 소스가 공개되지 않았습니다.

---

## 카테고리 요약표

| 프로젝트 | 기억 판단 주체 | 저장소 / Docker | 검색 | 로컬 vs 클라우드 핵심 차이 | 설치 |
|---|---|---|---|---|---|
| claude-mem | **별도 observer LLM**(기본 Claude Haiku, Agent SDK), PostToolUse `*` 전량 캡처 | SQLite + Chroma(uvx) / 불필요 | Chroma 벡터 → SQLite FTS 폴백, SessionStart 자동 주입 | 로컬도 기본으로 Anthropic에 tool I/O 전송. server runtime(PG/Redis, team 테넌트), cmem.ai 동기화와 Pro 게이트웨이는 opt-in | 플러그인 마케트플레이스, npm `claude-mem` |
| Basic Memory | **현재 에이전트**(write_note). hook은 WAL 기록과 규칙 기반 checkpoint만 | Markdown + SQLite(FTS5, sqlite-vec) / 불필요 | FTS+벡터 하이브리드(fastembed 로컬), 선택 rerank | 프로젝트별 LOCAL/CLOUD 라우팅(미등록 프로젝트는 CLOUD), 클라우드는 PG와 객체 스토리지, rclone. 로컬은 LLM 호출 없음 | PyPI `basic-memory`, 플러그인(uv) |
| mcp-memory-service | 에이전트 + hook의 **regex 패턴**, 선택적 Groq LLM 분류 | sqlite-vec / 불필요 | BM25+벡터(RRF), ONNX 로컬 임베딩 | cloudflare(D1/Vectorize) 또는 hybrid 동기화, OAuth 원격 | PyPI, claude-hooks 플러그인 |
| MCP reference memory | 에이전트 | JSONL 파일 / 선택 | 부분 문자열 | 로컬 전용 | npx |
| Cipher (아카이브) | **서버 LLM이 매 턴 강제** ADD/UPDATE/DELETE/NONE | in-memory 기본, Qdrant/Milvus/PG 등 | 벡터 | 로컬도 LLM과 임베딩 키 필수 | npm |
| ByteRover CLI | brv 자체 LLM 에이전트 curate(+review) | `.brv/context-tree` Markdown / 불필요 | MiniSearch | byterover.dev push/pull, 내장 LLM은 계정 필요 | npm `byterover-cli` |
| memory-bank-mcp | 에이전트(규칙 프롬프트) | 디렉터리 / 선택 | 없음 | 로컬 전용 | npx `@allpepper/...` |
| LongMemory (구 OpenMemory) | 에이전트 + **regex claim 추출** | SQLite / 선택 | fusion/rerank, synthetic 임베딩 기본 | self-host HTTP, API key는 선택 | npm `longmemory` |
| mcp-mem0 | **mem0 서버 LLM**(0.1.88 ADD/UPDATE/DELETE) | Supabase/PG 필수 | 벡터 | Ollama면 로컬 가능, 공식 mem0-mcp는 클라우드 전용 | uv, Docker |
| ConPort | 에이전트(규칙 프롬프트) | SQLite + Chroma 파일 / 불필요 | FTS5 + 로컬 ST 임베딩 | 로컬 전용 | PyPI `context-portal-mcp` |
| Serena | 에이전트(onboarding 유도) | `.serena/memories` md | 이름 목록만 | 로컬 전용 | uvx |
| Engram | **에이전트**(mem_save, 충돌 시 mem_judge) + 규칙 기반 passive | SQLite / 불필요 | FTS5, hook 주입 | self-host PG 클라우드 동기화 | 플러그인, Go 바이너리 |
| claude-supermemory | **Supermemory 클라우드 LLM** | 원격 전용 | 원격, hook 주입 | 로컬 모드 없음 | 마케트플레이스 |
| beads | 에이전트(`bd remember`) | Dolt | 키워드, prime 주입 | compaction에 Anthropic API | Go 바이너리 |
| Codex Memories | **백그라운드 LLM 2단계** + 통합 서브에이전트 | SQLite + `~/.codex/memories` | developer 지시문 주입, list/read/search 도구 | provider로 대화 전송 | Codex 내장 |
| claude-remember | 중첩 `claude -p` Haiku | 일별 로그 파일 | 로그 주입 | 사용자 Claude 크레딧 사용 | 공식 마케트플레이스 |
| tigerless agent-memory | headless 호스트 executor(provenance 범위) | Markdown + SQLite | FTS5 + 벡터 | 로컬 | — |
| context-mode | 순수 규칙 추출 | SQLite FTS5 | BM25/trigram RRF | 로컬 | 플러그인 |

### agents-memory와 비교한 시사점
- **판단 주체가 같은 쪽**: "현재 에이전트가 판단하고 서버는 검증만"인 설계는 Basic Memory(hook은 기록만), Engram(충돌을 `mem_judge`로 에이전트에게 위임), ConPort, Serena, beads와 같은 계열입니다. 이 중 **정확한 바이트 범위나 리비전을 검증하는 곳은 없습니다**.
  - 가장 근접한 것은 Basic Memory의 `expected_checksum` 조건부 덮어쓰기와 tigerless의 `--provenance <message range>`입니다.
- **반대 쪽**: claude-mem, Cipher, mem0, Codex, claude-remember, Supermemory는 별도 LLM이 전량 캡처한 내용에서 추출합니다. 이들은 모두 **로컬 모드에서도 기본으로 외부 LLM에 대화나 tool I/O를 보냅니다**.
- **Docker**: 조사한 코딩 에이전트용 메모리 대부분이 **Docker 없이 SQLite(FTS5, sqlite-vec) 내장**입니다. Postgres는 claude-mem server, Basic Memory cloud, Engram cloud, mcp-mem0처럼 클라우드나 팀 경로에서만 쓰입니다. 우리의 Docker/PG 필수 요구는 이 카테고리 기준으로 드문 편입니다.
- **삭제**: tombstone과 soft-delete(mcp-memory-service, Engram, claude-mem 동기화)는 흔합니다. 반면 **삭제 저널 또는 rejection feedback**에 해당하는 구현은 찾지 못했습니다.

## 3. 메모리 엔진 (원문)

# AI 메모리 엔진 코드 조사: 범주 B (추출·통합 파이프라인을 가진 범용 엔진)

## 결론
- **무엇을 기억할지는 거의 모든 엔진에서 서버나 라이브러리 쪽 LLM이 정합니다.**
  - 예외 ①: 에이전트 자신이 도구나 파일 편집으로 기억을 고치는 쪽 — Letta, letta-code, memU, LangMem의 hot-path 도구, mem0의 `infer=False`.
  - 예외 ②: 판단 기능 자체가 없는 저장 계층 — memvid.
- **"로컬" 기본 설정도 대부분 클라우드 LLM이나 임베딩 API를 부릅니다.**
  - 특히 Memori는 BYODB(자기 DB) 모드에서도 기억 추출을 `memorilabs.ai` API에 맡깁니다.
  - 기본값이 완전 로컬에 가까운 것은 memvid, MemOS local plugin(로컬 MiniLM 임베딩 + 호스트 LLM), A-mem(Ollama 지정 시)뿐입니다.
- **시간 축과 모순 처리를 코드로 강제하는 엔진은 적습니다.**
  - 코드 강제: Graphiti(`valid_at`/`invalid_at`/`expired_at` 양시간축), memvid(`entity:slot` 기준 supersedes), Cognee(선택 기능).
  - 나머지는 LLM 재작성이나 삭제(Honcho dreamer, MemOS resolver, MemMachine dedup)이거나, 처리가 없습니다(mem0 OSS 현재 버전, A-mem, MemoryOS).
- **삭제 journal은 23개 프로젝트 어디에서도 확인하지 못했습니다.**
  - 가장 가까운 것: memvid의 WAL tombstone, Honcho의 soft-delete 후 hard-delete, mem0 SQLite history. 단 mem0 history는 원문을 남기므로 purge가 아닙니다.
- **우리 문제(Docker로 PG 띄우기)와 직접 관련된 사례**
  - Hindsight: 기본 `DATABASE_URL="pg0"`이 PostgreSQL을 내장 프로세스로 띄워 Docker가 필요 없습니다.
  - Letta, MIRIX: Postgres가 없으면 SQLite나 PGlite로 대체됩니다.

방법: 모든 링크는 고정 SHA의 실제 파일이며 `gh api`(contents, trees)로 읽었습니다. 코드는 clone하거나 실행하지 않았습니다. 별 수와 마지막 활동은 2026-10-15 기준 GitHub API 값입니다. README에만 근거한 내용은 "(README 기준)", 추론은 [추론]으로 표시했습니다. mem0/LangMem/A-mem, Graphiti/Zep/Cognee, Letta/MIRIX/MemoryOS, Hindsight/Memobase/memU, Honcho/AMS/MemMachine, OpenViking/EverOS/ReMe/memvid는 하위 작업자 6명이 나눠 읽었고, MemOS/Memori/Memary와 추가 프로젝트 탐색은 직접 했습니다.

---

## 프로젝트별 결과

### 1. mem0 — `mem0ai/mem0` @ [`0724291`](https://github.com/mem0ai/mem0/tree/0724291bd864cf807e88ee8981c8226644e8fb42)

**1. 정체**
- Apache-2.0, 별 약 67k, 2026-10-14 push, Python과 TS.
- 기본 의존성에 qdrant-client, openai, posthog가 있습니다 ([pyproject#L6-L23](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/pyproject.toml#L6-L23)).
- 구조 변경
  - 그래프 메모리(`graph_memory.py`)가 2026-04 [a488e19](https://github.com/mem0ai/mem0/commit/a488e19044e4de9322a4e82be8d49ee67a322151)에서 삭제됐습니다.
  - `openmemory/`가 2026-07 [ea2ee07](https://github.com/mem0ai/mem0/commit/ea2ee0758635a9230bd60855c3fe339170f6cd18)에서 삭제됐습니다.

**2. 쓰기 경로**
- 명시적인 `Memory.add()` 호출로 시작합니다 ([main.py#L760-L879](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/mem0/memory/main.py#L760-L879)).
- `infer=False`면 원문을 그대로 저장합니다 ([#L882-L916](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/mem0/memory/main.py#L882-L916)).
- 기본값 `infer=True`는 "V3 phased batch" 파이프라인입니다 ([#L918-L971](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/mem0/memory/main.py#L918-L971)).
  1. SQLite에서 직전 메시지를 읽습니다.
  2. 기존 메모리 top-10을 벡터 검색하고, UUID를 정수로 바꿉니다.
  3. 서버 LLM을 `ADDITIVE_EXTRACTION_PROMPT`로 한 번 호출합니다.
- 프롬프트 핵심 ([prompts.py#L464-L516](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/mem0/configs/prompts.py#L464-L516))
  - "Your sole operation is ADD"
  - "When in doubt, extract" ([#L578](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/mem0/configs/prompts.py#L578))
  - 주석에 "Ported from platform/backend…"라고 적혀 있습니다. 클라우드 프롬프트를 OSS로 옮긴 것입니다.
- 옛 ADD/UPDATE/DELETE/NONE 프롬프트(`DEFAULT_UPDATE_MEMORY_PROMPT`, [#L176-L324](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/mem0/configs/prompts.py#L176-L324))는 정의만 남아 있고 `main.py`가 import하지 않습니다 ([main.py#L19-L24](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/mem0/memory/main.py#L19-L24)).

**3. 갱신과 통합**
- OSS에는 UPDATE/DELETE 결정이 없습니다.
- 중복 제거는 MD5 해시 비교뿐입니다 ([#L1007-L1026](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/mem0/memory/main.py#L1007-L1026)).
- LLM이 돌려주는 `linked_memory_ids`는 저장되지 않습니다 ([#L1017-L1041](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/mem0/memory/main.py#L1017-L1041)).
- `timestamp`/`reference_date`를 넘기면 "not supported by the OSS" 오류가 납니다 ([#L817-L818](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/mem0/memory/main.py#L817-L818)).
- 대체(supersede) 체인은 클라우드에만 있습니다: `delete_linked`, `latest_only` ([client/main.py#L524-L547](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/mem0/client/main.py#L524-L547)).
- 엔티티 저장소
  - spaCy NER로 엔티티를 뽑고, 유사도 0.95 이상이면 같은 엔티티로 병합합니다 ([#L1100-L1204](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/mem0/memory/main.py#L1100-L1204)).
  - 삭제 전 그래프 메모리는 `DELETE_RELATIONS_SYSTEM_PROMPT`로 고른 관계에 `r.valid=false, invalidated_at`을 기록하는 soft 무효화였습니다 ([@57f944e graph_memory.py#L420-L428](https://github.com/mem0ai/mem0/blob/57f944e18ad8ec3186297ea2caf7ff8e47ec3ec0/mem0/memory/graph_memory.py#L420-L428)).

**4. 검색**
- 의미 검색(과다 조회) + lemmatize BM25 + 엔티티 부스트를 가산 점수로 합칩니다 ([#L1642-L1745](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/mem0/memory/main.py#L1642-L1745), [scoring.py#L57-L133](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/mem0/utils/scoring.py#L57-L133)).
- rerank는 선택입니다.
- SDK 자체에는 주입 기능이 없습니다.

**5. 저장소**
- 임베디드 Qdrant `path=/tmp/qdrant`(`on_disk=False`) + SQLite `~/.mem0/history.db` ([qdrant.py#L75-L81](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/mem0/vector_stores/qdrant.py#L75-L81), [configs/base.py#L42-L44](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/mem0/configs/base.py#L42-L44)).
- 벡터 스토어는 약 25종으로 바꿀 수 있습니다.
- SDK는 Docker가 필요 없습니다. 셀프호스트 REST `server/`는 Docker(pgvector pg17)입니다 ([server/docker-compose.yaml](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/server/docker-compose.yaml)).

**6. 로컬과 클라우드**
- 로컬 기본값
  - LLM: OpenAI `gpt-5-mini` ([llms/openai.py#L39-L53](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/mem0/llms/openai.py#L39-L53))
  - 임베딩: `text-embedding-3-small`
  - PostHog 텔레메트리가 기본으로 켜져 있습니다 ([telemetry.py#L14-L16](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/mem0/memory/telemetry.py#L14-L16)).
- 클라우드 `MemoryClient`
  - `https://api.mem0.ai`, `Token` 인증, `/v1/ping/`에서 org/project를 알아냅니다 ([client/main.py#L240-L308](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/mem0/client/main.py#L240-L308)).
  - 플랫폼 전용: webhooks, decay, `latest_only`, timestamp 등.
- **Claude Code/Codex/Cursor 플러그인은 플랫폼에서만 동작합니다.**
  - 훅이 증거를 모으고, PreCompact와 SessionEnd에서 `/v3/memories/add/`에 `infer:True`로 보냅니다 ([memory_core.py#L1962-L2021](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/integrations/claude-code-plugin/core/memory_core.py#L1962-L2021)).
  - 키가 없으면 "local-only"로 저장하지 않습니다.
  - 첫 프롬프트에 `additionalContext`로 자동 주입합니다 ([hook_runner.py#L62-L92](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/integrations/claude-code-plugin/core/hook_runner.py#L62-L92)).

**7. 삭제와 프라이버시**
- `delete()`는 벡터를 지우지만 history에 `old_memory` 원문을 `is_deleted=1`로 남깁니다 ([#L2114-L2142](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/mem0/memory/main.py#L2114-L2142)).
- `reset()`은 테이블을 DROP합니다.
- 비밀정보 처리는 플러그인의 `SECRET_PATTERNS` redaction뿐입니다 ([memory_core.py#L140-L179](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/integrations/claude-code-plugin/core/memory_core.py#L140-L179)).

**8. 설치**: `pip install mem0ai`, npm `mem0ai`, 플러그인 마켓플레이스, `server/` compose.

### 2. LangMem — `langchain-ai/langmem` @ [`48e3c11`](https://github.com/langchain-ai/langmem/tree/48e3c11f5bb527282c7d5339c6a87a0b35abccfc)

**1. 정체**: MIT, 약 1.7k, 2026-10 push(의존성 bump 위주), Python.

**2. 쓰기 경로**: 두 모드가 있습니다.
- (a) 에이전트가 판단: `create_manage_memory_tool`의 create/update/delete ([tools.py#L271-L303](https://github.com/langchain-ai/langmem/blob/48e3c11f5bb527282c7d5339c6a87a0b35abccfc/src/langmem/knowledge/tools.py#L271-L303))
- (b) 백그라운드 LLM이 판단: `create_memory_manager`와 `create_memory_store_manager` ([extraction.py#L185-L206](https://github.com/langchain-ai/langmem/blob/48e3c11f5bb527282c7d5339c6a87a0b35abccfc/src/langmem/knowledge/extraction.py#L185-L206))
- 모델 기본값은 없습니다.

**3. 갱신과 통합**
- trustcall을 씁니다: insert, update는 `PatchDoc`(JSON-Patch), delete는 `RemoveDoc` ([#L253-L260](https://github.com/langchain-ai/langmem/blob/48e3c11f5bb527282c7d5339c6a87a0b35abccfc/src/langmem/knowledge/extraction.py#L253-L260)).
- `enable_deletes` 기본값이 함수마다 다릅니다: 팩토리 함수는 False, `MemoryStoreManager`를 직접 만들면 True ([#L845](https://github.com/langchain-ai/langmem/blob/48e3c11f5bb527282c7d5339c6a87a0b35abccfc/src/langmem/knowledge/extraction.py#L845)).
- 통합은 검색된 top-5 안에서만 일어납니다 ([#L1006-L1137](https://github.com/langchain-ai/langmem/blob/48e3c11f5bb527282c7d5339c6a87a0b35abccfc/src/langmem/knowledge/extraction.py#L1006-L1137)).
- 시간 모델은 없고 TTL만 있습니다. 그래프는 주석 처리돼 있습니다.

**4. 검색**
- `store.asearch`에 맡깁니다 ([tools.py#L436-L486](https://github.com/langchain-ai/langmem/blob/48e3c11f5bb527282c7d5339c6a87a0b35abccfc/src/langmem/knowledge/tools.py#L436-L486)).
- 자체 BM25나 rerank는 없습니다. 주입은 도구 호출이나 개발자 코드로 합니다.

**5. 저장소**
- LangGraph `BaseStore`입니다. 예제는 휘발성 `InMemoryStore` ([graphs/semantic.py#L7-L16](https://github.com/langchain-ai/langmem/blob/48e3c11f5bb527282c7d5339c6a87a0b35abccfc/src/langmem/graphs/semantic.py#L7-L16))이고, Postgres를 권장합니다 (README 기준).

**6. 로컬과 클라우드** ([reflection.py#L110-L330](https://github.com/langchain-ai/langmem/blob/48e3c11f5bb527282c7d5339c6a87a0b35abccfc/src/langmem/reflection.py#L110-L140))
- 로컬: `LocalReflectionExecutor`(스레드, 디바운스)
- 클라우드: `RemoteReflectionExecutor`(LangGraph Platform `runs.create`). 인증은 LangSmith `X-Api-Key`입니다 ([graphs/auth.py#L13-L45](https://github.com/langchain-ai/langmem/blob/48e3c11f5bb527282c7d5339c6a87a0b35abccfc/src/langmem/graphs/auth.py#L13-L45)).

**7. 삭제와 프라이버시**: `store.adelete`로 하드 삭제합니다. 이력과 비밀정보 처리는 없습니다.

**8. 설치**: `pip install langmem`. MCP는 없습니다.

### 3. A-mem — `agiresearch/A-mem` @ [`ceffb86`](https://github.com/agiresearch/A-mem/tree/ceffb860f0712bbae97b184d440df62bc910ca8d)

**1. 정체**
- MIT, 약 1.2k, 2025-12 이후 정체.
- 후속 포크 WujiangXu/A-mem-sys(약 400)가 아래 버그를 고쳤습니다.

**2. 쓰기 경로**
- `add_note`가 원문 전부를 노트로 저장합니다 ([memory_system.py#L233-L264](https://github.com/agiresearch/A-mem/blob/ceffb860f0712bbae97b184d440df62bc910ca8d/agentic_memory/memory_system.py#L233-L264)).
- `analyze_content`(keywords/tags를 만드는 LLM)는 정의만 있고 호출되지 않습니다 ([#L159-L231](https://github.com/agiresearch/A-mem/blob/ceffb860f0712bbae97b184d440df62bc910ca8d/agentic_memory/memory_system.py#L159-L231)).

**3. 갱신과 진화**
- `process_memory`가 이웃 5개를 찾고 `_evolution_system_prompt`로 판단합니다. 결과는 strengthen(링크 추가) 또는 update_neighbor(이웃 context/tags 재작성)입니다 ([#L590-L718](https://github.com/agiresearch/A-mem/blob/ceffb860f0712bbae97b184d440df62bc910ca8d/agentic_memory/memory_system.py#L590-L718)).
- DELETE, 모순 처리, 시간 처리는 없습니다.
- 버그: Chroma 순위 번호를 dict 삽입 순서 인덱스로 써서 엉뚱한 노트를 수정합니다 ([#L687-L716](https://github.com/agiresearch/A-mem/blob/ceffb860f0712bbae97b184d440df62bc910ca8d/agentic_memory/memory_system.py#L687-L716)).

**4. 검색**: Chroma 벡터 top-k + 링크 1-hop 확장입니다 ([#L509-L588](https://github.com/agiresearch/A-mem/blob/ceffb860f0712bbae97b184d440df62bc910ca8d/agentic_memory/memory_system.py#L509-L588)). 주입 장치는 없습니다.

**5. 저장소**
- 인메모리 Chroma에 로컬 MiniLM 임베딩입니다 ([retrievers.py#L42-L60](https://github.com/agiresearch/A-mem/blob/ceffb860f0712bbae97b184d440df62bc910ca8d/agentic_memory/retrievers.py#L42-L60)).
- 시작할 때 `reset()`을 호출해 **영속성이 없습니다** ([#L108-L119](https://github.com/agiresearch/A-mem/blob/ceffb860f0712bbae97b184d440df62bc910ca8d/agentic_memory/memory_system.py#L108-L119)).

**6. 로컬과 클라우드**
- 클라우드 제품은 없습니다.
- 기본 LLM은 OpenAI `gpt-4o-mini`이고, Ollama 백엔드로 완전 로컬 실행이 가능합니다 ([llm_controller.py#L13-L94](https://github.com/agiresearch/A-mem/blob/ceffb860f0712bbae97b184d440df62bc910ca8d/agentic_memory/llm_controller.py#L13-L22)).

**7. 삭제와 프라이버시**: 하드 삭제이고, 다른 노트에 dangling link가 남습니다 ([#L398-L413](https://github.com/agiresearch/A-mem/blob/ceffb860f0712bbae97b184d440df62bc910ca8d/agentic_memory/memory_system.py#L398-L413)).

**8. 설치**: clone 후 `pip install .`

### 4. Graphiti — `getzep/graphiti` @ [`aca3693`](https://github.com/getzep/graphiti/tree/aca369364226a666ca541b061ff2a1a54b80f2ff)

**1. 정체**: Apache-2.0, 약 32k, 2026-10-15 push, Python.

**2. 쓰기 경로**
- `add_episode` 순서: `extract_nodes` → `resolve_extracted_nodes` → `_extract_and_resolve_edges` → attributes → (선택) community ([graphiti.py#L1332-L1585](https://github.com/getzep/graphiti/blob/aca369364226a666ca541b061ff2a1a54b80f2ff/graphiti_core/graphiti.py#L1332-L1585)).
- 엣지 프롬프트는 사실과 `valid_at`/`invalid_at`을 함께 추출합니다 ([extract_edges.py#L95-L196](https://github.com/getzep/graphiti/blob/aca369364226a666ca541b061ff2a1a54b80f2ff/graphiti_core/prompts/extract_edges.py#L95-L196)).

**3. 갱신과 통합**
- 노드: 정확 일치 또는 MinHash/LSH Jaccard 0.9 이상이면 병합하고, 남은 후보는 LLM `dedupe_nodes`가 판정합니다("확신 없으면 -1") ([node_operations.py#L816-L910](https://github.com/getzep/graphiti/blob/aca369364226a666ca541b061ff2a1a54b80f2ff/graphiti_core/utils/maintenance/node_operations.py#L816-L910)).
- 엣지: `resolve_extracted_edges`에서 LLM `resolve_edge`가 `duplicate_facts`와 `contradicted_facts`를 냅니다. 프롬프트는 "최신성만으로 모순이라 추론하지 말라"입니다 ([edge_operations.py#L424-L646](https://github.com/getzep/graphiti/blob/aca369364226a666ca541b061ff2a1a54b80f2ff/graphiti_core/utils/maintenance/edge_operations.py#L424-L646), [dedupe_edges.py#L25-L95](https://github.com/getzep/graphiti/blob/aca369364226a666ca541b061ff2a1a54b80f2ff/graphiti_core/prompts/dedupe_edges.py#L25-L33)).
- 모순 처리: `resolve_edge_contradictions`가 코드로 날짜를 비교해 옛 엣지에 `invalid_at`과 `expired_at`을 기록합니다. **삭제하지 않습니다** ([#L715-L783](https://github.com/getzep/graphiti/blob/aca369364226a666ca541b061ff2a1a54b80f2ff/graphiti_core/utils/maintenance/edge_operations.py#L715-L783)).

**4. 검색**
- BM25 + cosine + BFS를 RRF, MMR, cross-encoder(gpt logprob), node_distance로 재정렬합니다 ([search_config.py#L32-L77](https://github.com/getzep/graphiti/blob/aca369364226a666ca541b061ff2a1a54b80f2ff/graphiti_core/search/search_config.py#L32-L77)).
- 만료된 엣지는 기본으로 걸러지지 않습니다 ([search_filters.py#L55-L65](https://github.com/getzep/graphiti/blob/aca369364226a666ca541b061ff2a1a54b80f2ff/graphiti_core/search/search_filters.py#L55-L65)).
- 주입은 SDK나 MCP로 합니다.

**5. 저장소**
- 기본은 Neo4j 서버입니다 ([graphiti.py#L328-L333](https://github.com/getzep/graphiti/blob/aca369364226a666ca541b061ff2a1a54b80f2ff/graphiti_core/graphiti.py#L328-L333)).
- FalkorDB, Neptune도 서버형이고, 임베디드는 falkordblite와 Kuzu(deprecated)입니다.
- Docker는 선택입니다.

**6. 로컬과 클라우드**
- 로컬 기본값은 전부 OpenAI입니다: LLM, `text-embedding-3-small`, reranker ([graphiti.py#L343-L360](https://github.com/getzep/graphiti/blob/aca369364226a666ca541b061ff2a1a54b80f2ff/graphiti_core/graphiti.py#L343-L360)).
- PostHog 텔레메트리가 켜져 있습니다 ([telemetry.py#L18-L22](https://github.com/getzep/graphiti/blob/aca369364226a666ca541b061ff2a1a54b80f2ff/graphiti_core/telemetry/telemetry.py#L18-L22)).
- 클라우드 코드는 없고, 격리 단위는 `group_id`뿐입니다. Zep Cloud는 비공개 "Context Graph Engine"입니다 (README 기준).

**7. 삭제와 프라이버시**
- `remove_episode`는 그 에피소드가 만든 엣지와 그 에피소드에서만 언급된 노드만 지웁니다 ([graphiti.py#L2164-L2192](https://github.com/getzep/graphiti/blob/aca369364226a666ca541b061ff2a1a54b80f2ff/graphiti_core/graphiti.py#L2164-L2192)).
- `clear_data`는 `DETACH DELETE`입니다.
- `store_raw_episode_content=False` 옵션으로 원문을 남기지 않을 수 있습니다.

**8. 설치와 MCP**
- `pip install graphiti-core`.
- MCP 도구 13개, http/stdio/sse, FalkorDB Docker 구성 ([graphiti_mcp_server.py#L402-L1146](https://github.com/getzep/graphiti/blob/aca369364226a666ca541b061ff2a1a54b80f2ff/mcp_server/src/graphiti_mcp_server.py#L402-L1146)).

### 5. Zep — `getzep/zep` @ [`3997767`](https://github.com/getzep/zep/tree/3997767fccf83bbea7b54ad5f73554f2e5bcd54e)

**1. 정체**
- 약 5k. 이 저장소는 Cloud용 예제와 통합 코드, 그리고 deprecated된 `legacy/` CE입니다 (README 기준, [L19-L31](https://github.com/getzep/zep/blob/3997767fccf83bbea7b54ad5f73554f2e5bcd54e/README.md#L19-L31)).

**2. 쓰기 경로**
- 클라이언트는 원문만 보냅니다: `thread.add_messages`, `graph.episode.add` ([graph_example.py#L45-L64](https://github.com/getzep/zep/blob/3997767fccf83bbea7b54ad5f73554f2e5bcd54e/examples/python/graph_example/graph_example.py#L45-L64)).
- 추출은 클라우드 LLM이 합니다.

**3. 갱신과 통합**: 이 저장소에는 코드가 없습니다. ontology와 instructions 설정 API만 호출합니다.

**4. 검색**: `thread.get_context`의 Context Block, `graph.search_*`. 주입은 middleware나 hook으로 합니다 ([middleware.ts#L258-L337](https://github.com/getzep/zep/blob/3997767fccf83bbea7b54ad5f73554f2e5bcd54e/integrations/vercel-ai/typescript/src/middleware.ts#L258-L337)).

**5. 저장소**
- 클라우드 전용입니다.
- 과거 CE는 Go + pgvector + graphiti(Neo4j, OpenAI) 구성이었습니다 ([docker-compose.ce.yaml](https://github.com/getzep/zep/blob/3997767fccf83bbea7b54ad5f73554f2e5bcd54e/legacy/docker-compose.ce.yaml#L5-L71)).

**6. 로컬과 클라우드**
- `https://api.getzep.com/api/v4`, `ZEP_API_KEY` ([client.go#L15](https://github.com/getzep/zep/blob/3997767fccf83bbea7b54ad5f73554f2e5bcd54e/integrations/adk/go/client.go#L15)).
- 엔진, 요약, 관찰, 템플릿 모두 비공개입니다.

**7. 삭제와 프라이버시**: `user.delete`는 비동기 task입니다. 실제 동작은 비공개입니다.

**8. 설치**: `pip install zep-cloud`. 저장소의 Go MCP는 deprecated이고, 공식 MCP는 hosted로 안내됩니다.

### 6. Cognee — `topoteretes/cognee` @ [`f154b32`](https://github.com/topoteretes/cognee/tree/f154b32a9e544dac73e7ddf2010327cf9988edcd)

**1. 정체**
- Apache-2.0, 약 32k, Python.
- API는 V1(`add/cognify/memify/search`)과 V2(`remember/recall/improve/forget/serve`) 두 층입니다.

**2. 쓰기 경로**
- `cognify` 순서: chunk → `extract_graph_and_summarize` ([cognify.py#L572-L652](https://github.com/topoteretes/cognee/blob/f154b32a9e544dac73e7ddf2010327cf9988edcd/cognee/api/v1/cognify/cognify.py#L572-L652)).
- 청크마다 LLM을 한 번 호출합니다. 프롬프트는 `generate_graph_prompt.txt`입니다 ([prompt](https://github.com/topoteretes/cognee/blob/f154b32a9e544dac73e7ddf2010327cf9988edcd/cognee/infrastructure/llm/prompts/generate_graph_prompt.txt#L1-L53)).
- `remember`는 session_id가 있으면 세션 캐시에 넣었다가 나중에 그래프로 옮깁니다.

**3. 갱신과 통합**
- 엔티티 ID가 `uuid5(소문자 이름)`이라 같은 이름은 같은 노드가 됩니다.
- `consolidate_entities`: 이름 cosine 0.85 이상을 union-find로 묶습니다 ([consolidate_entities.py#L450-L543](https://github.com/topoteretes/cognee/blob/f154b32a9e544dac73e7ddf2010327cf9988edcd/cognee/tasks/memify/consolidate_entities.py#L450-L543)).
- `detect_contradictions`(기본 꺼짐): LLM이 `contradicts` 엣지만 추가합니다 ([#L143-L236](https://github.com/topoteretes/cognee/blob/f154b32a9e544dac73e7ddf2010327cf9988edcd/cognee/tasks/graph/detect_contradictions.py#L143-L236)).
- `resolve_temporal_contradictions`: 단일값으로 선언된 관계에서 옛 엣지에 `superseded` 태그를 붙입니다. LLM은 쓰지 않습니다 ([link](https://github.com/topoteretes/cognee/blob/f154b32a9e544dac73e7ddf2010327cf9988edcd/cognee/tasks/graph/resolve_temporal_contradictions.py#L1-L22)).

**4. 검색**
- SearchType이 20종이고 `recall` 기본값은 HYBRID_COMPLETION입니다 ([query_router.py](https://github.com/topoteretes/cognee/blob/f154b32a9e544dac73e7ddf2010327cf9988edcd/cognee/api/v1/recall/query_router.py#L1-L28)).
- GRAPH_COMPLETION은 벡터로 트리플을 고른 뒤 LLM이 답을 만듭니다.

**5. 저장소**
- 기본은 모두 임베디드입니다: SQLite + LanceDB + Ladybug(Kuzu 계열 [추론]) ([graph/config.py#L47](https://github.com/topoteretes/cognee/blob/f154b32a9e544dac73e7ddf2010327cf9988edcd/cognee/infrastructure/databases/graph/config.py#L47)).
- Neo4j, Postgres, pgvector는 선택이고 Docker도 선택입니다.

**6. 로컬과 클라우드**
- 로컬 기본값은 OpenAI입니다. 키가 없으면 GLiNER demo 추출기와 fastembed로 전환합니다 ([cognify/config.py#L84-L152](https://github.com/topoteretes/cognee/blob/f154b32a9e544dac73e7ddf2010327cf9988edcd/cognee/modules/cognify/config.py#L84-L152)).
- 클라우드 연결(`serve()`): Auth0 device login → tenant 인스턴스 → 같은 API를 `X-Api-Key`로 프록시합니다 ([serve.py#L138-L294](https://github.com/topoteretes/cognee/blob/f154b32a9e544dac73e7ddf2010327cf9988edcd/cognee/api/v1/serve/serve.py#L138-L294), [cloud_client.py](https://github.com/topoteretes/cognee/blob/f154b32a9e544dac73e7ddf2010327cf9988edcd/cognee/api/v1/serve/cloud_client.py#L53-L590)).
- OSS에도 데이터셋 단위 ACL이 있습니다.

**7. 삭제와 프라이버시**
- `forget`은 data/dataset/everything/memory_only 범위를 고릅니다. provenance를 보고 공유 노드는 보존합니다 ([forget.py#L22-L188](https://github.com/topoteretes/cognee/blob/f154b32a9e544dac73e7ddf2010327cf9988edcd/cognee/api/v1/forget/forget.py#L22-L188)).
- PII는 탐지해서 리포트만 하고 마스킹하지 않습니다.

**8. 설치**
- `uv pip install cognee`.
- cognee-mcp(기본 stdio, 노출 도구 remember/recall/forget/improve) ([server.py#L209-L253](https://github.com/topoteretes/cognee/blob/f154b32a9e544dac73e7ddf2010327cf9988edcd/cognee-mcp/src/server.py#L209-L253)).
- Claude Code 플러그인은 별도 저장소입니다 (catalog 기준).

### 7. Letta V1 서버 — `letta-ai/letta` `archive` @ [`56ba9c2`](https://github.com/letta-ai/letta/tree/56ba9c25552605eec89de8ed3dc6394b625c1993)

**1. 정체**
- Apache-2.0, 약 25k.
- 기본 브랜치에는 README만 있고 "개발은 letta-code로 이전"이라고 안내합니다.

**2. 쓰기 경로**
- **에이전트 LLM이 직접 판단합니다.** 도구: `core_memory_append/replace`(정확 일치 치환), `memory_replace/insert/apply_patch/rethink`, `memory(command=…)` ([base.py#L10-L528](https://github.com/letta-ai/letta/blob/56ba9c25552605eec89de8ed3dc6394b625c1993/letta/functions/function_sets/base.py#L246-L280)).
- archival 도구는 deprecated입니다.

**3. 갱신과 통합**
- sleeptime 에이전트가 N턴마다 블록을 다시 씁니다 ([sleeptime_multi_agent_v4.py#L132-L243](https://github.com/letta-ai/letta/blob/56ba9c25552605eec89de8ed3dc6394b625c1993/letta/groups/sleeptime_multi_agent_v4.py#L132-L168), [sleeptime_v2](https://github.com/letta-ai/letta/blob/56ba9c25552605eec89de8ed3dc6394b625c1993/letta/prompts/system_prompts/sleeptime_v2.py#L12-L25)).
- 명시적인 dedup·모순 처리 코드는 없습니다.
- 이력: `BlockHistory`, git 메모리(`GitEnabledBlockManager`).

**4. 검색**
- core block은 `Memory.compile`이 system prompt에 항상 넣습니다 ([memory.py#L688-L732](https://github.com/letta-ai/letta/blob/56ba9c25552605eec89de8ed3dc6394b625c1993/letta/schemas/memory.py#L688-L732)).
- archival은 pgvector나 sqlite-vec로 찾습니다.
- 대화 검색은 OSS에서 ILIKE이고, Turbopuffer를 켤 때만 RRF입니다 ([message_manager.py#L977-L993](https://github.com/letta-ai/letta/blob/56ba9c25552605eec89de8ed3dc6394b625c1993/letta/services/message_manager.py#L977-L993)).

**5. 저장소**: `pg_uri`가 없으면 SQLite + sqlite-vec를 씁니다 ([settings.py#L492-L493](https://github.com/letta-ai/letta/blob/56ba9c25552605eec89de8ed3dc6394b625c1993/letta/settings.py#L492-L493)). Docker는 선택입니다.

**6. 로컬과 클라우드**
- cloud memfs 클라이언트는 import에 실패하면 로컬로 fallback하고, 그 파일은 OSS에 없습니다 ([memory_repo/__init__.py#L6-L10](https://github.com/letta-ai/letta/blob/56ba9c25552605eec89de8ed3dc6394b625c1993/letta/services/memory_repo/__init__.py#L6-L10)).
- Turbopuffer와 Pinecone은 hosted용입니다 [추론].

**7. 삭제와 프라이버시**: passage는 hard delete입니다. BlockHistory와 git에 과거 값이 남습니다 [추론]. 비밀정보 처리는 없습니다.

**8. 설치**: `letta/letta` Docker. 지금은 letta-code를 권장합니다.

### 8. letta-code — `letta-ai/letta-code` @ [`316e4c0`](https://github.com/letta-ai/letta-code/tree/316e4c0545b549c453e0f85cc81d3540404eff74)

**1. 정체**: Apache-2.0, 약 3.6k, TypeScript 코딩 에이전트 harness.

**2. 쓰기 경로**
- 메모리는 **git repo 파일 트리(MemFS)**입니다. 주 에이전트가 Bash나 Edit로 고치고 commit합니다 ([letta_local_memfs.md#L19-L66](https://github.com/letta-ai/letta-code/blob/316e4c0545b549c453e0f85cc81d3540404eff74/src/agent/prompts/letta_local_memfs.md#L19-L22)).
- 백그라운드 reflection subagent가 기본 25스텝마다 돌고 결과를 자동 merge합니다 ([post-turn-reflection.ts#L22-L80](https://github.com/letta-ai/letta-code/blob/316e4c0545b549c453e0f85cc81d3540404eff74/src/cli/helpers/post-turn-reflection.ts#L22-L80), [settings-manager.ts#L183-L186](https://github.com/letta-ai/letta-code/blob/316e4c0545b549c453e0f85cc81d3540404eff74/src/settings-manager.ts#L183-L186)).

**3. 갱신과 통합**
- 모두 프롬프트 규칙입니다. 예: "Contradiction resolution: fix the stale entry at the source", `ARCHIVE.md`로 은퇴 ([reflection-v2.md#L102-L104](https://github.com/letta-ai/letta-code/blob/316e4c0545b549c453e0f85cc81d3540404eff74/src/agent/subagents/builtin/reflection-v2.md#L102-L104)).
- 코드가 강제하는 것은 pre-commit의 frontmatter와 `read_only` 검사뿐입니다 ([memory-git-hooks.ts#L25-L35](https://github.com/letta-ai/letta-code/blob/316e4c0545b549c453e0f85cc81d3540404eff74/src/agent/memory-git-hooks.ts#L25-L35)).

**4. 검색**
- root 파일은 system prompt에 들어갑니다. deferred 메모리는 `Memory` 도구로 엽니다.
- recall은 로컬 TF 점수 계산이거나 Cloud `/v1/messages/search`입니다.

**5. 저장소**: `~/.letta/.../memory` git repo와 JSONL. Docker는 필요 없습니다.

**6. 로컬과 클라우드**
- 기본 서버 `https://api.letta.com`이 git remote이자 원본입니다 ([memory-git.ts#L228-L233](https://github.com/letta-ai/letta-code/blob/316e4c0545b549c453e0f85cc81d3540404eff74/src/agent/memory-git.ts#L228-L233)).
- 로컬 backend는 remote가 없고 experimental 플래그로 켭니다 ([backend-mode.ts#L24-L28](https://github.com/letta-ai/letta-code/blob/316e4c0545b549c453e0f85cc81d3540404eff74/src/backend/backend-mode.ts#L24-L28)).
- Cloud 전용 서버측 reflection API가 있습니다.
- App Server는 loopback이 기본이고, loopback이 아니면 인증을 요구합니다.

**7. 삭제와 프라이버시**: 프롬프트로만 정합니다("Never store secrets… may be synced off this machine"). git history를 purge하는 코드는 없습니다 [추론].

**8. 설치**: `npm i -g @letta-ai/letta-code`.

### 9. MIRIX — `Mirix-AI/MIRIX` @ [`8cb06a6`](https://github.com/Mirix-AI/MIRIX/tree/8cb06a62bbb7c478beb33dd4f2815696a72df482)

**1. 정체**: Apache-2.0, 약 3.5k, Python.

**2. 쓰기 경로**
- `/memory/add`가 큐에 넣고, 스크린샷·텍스트를 누적합니다(20개 단위) ([accumulator.py#L550-L566](https://github.com/Mirix-AI/MIRIX/blob/8cb06a62bbb7c478beb33dd4f2815696a72df482/mirix/agent/temporary_message_accumulator.py#L550-L566)).
- 서버측 meta-agent가 6종 중 어디로 보낼지 분류합니다 ([meta_memory_agent.txt](https://github.com/Mirix-AI/MIRIX/blob/8cb06a62bbb7c478beb33dd4f2815696a72df482/mirix/prompts/system/base/meta_memory_agent.txt#L1-L2)).
- 종류별 전용 에이전트 LLM이 실제로 씁니다.

**3. 갱신과 통합**
- episodic: insert, merge, replace 중 하나를 고릅니다 ([memory_tools.py#L114-L234](https://github.com/Mirix-AI/MIRIX/blob/8cb06a62bbb7c478beb33dd4f2815696a72df482/mirix/functions/function_sets/memory_tools.py#L114-L234)).
- semantic dedup은 완전 일치일 때만 건너뜁니다.
- 모순 정리는 수동 `POST /memory/auto_dream`으로만 돕니다 ([rest_api.py#L5708-L5729](https://github.com/Mirix-AI/MIRIX/blob/8cb06a62bbb7c478beb33dd4f2815696a72df482/mirix/server/rest_api.py#L5708-L5729)).

**4. 검색**
- 기본은 BM25(PG `ts_rank_cd`)입니다 ([agent.py#L1814](https://github.com/Mirix-AI/MIRIX/blob/8cb06a62bbb7c478beb33dd4f2815696a72df482/mirix/agent/agent.py#L1814)).
- LLM으로 topic을 뽑은 뒤 검색하고, 결과를 system prompt에 주입합니다.

**5. 저장소**: Postgres/PGlite/SQLite를 쓰고 Redis는 선택입니다 ([server.py#L270-L352](https://github.com/Mirix-AI/MIRIX/blob/8cb06a62bbb7c478beb33dd4f2815696a72df482/mirix/server/server.py#L270-L352)). Quick Start는 Docker입니다.

**6. 로컬과 클라우드**: `MirixClient` 기본값은 `localhost:8531`이고, `X-API-Key`, `X-Org-ID` 헤더로 테넌트를 나눕니다 ([remote_client.py#L114-L223](https://github.com/Mirix-AI/MIRIX/blob/8cb06a62bbb7c478beb33dd4f2815696a72df482/mirix/client/remote_client.py#L114-L127)).

**7. 삭제와 프라이버시**
- **Knowledge Vault가 비밀번호를 평문 컬럼에 저장합니다** ([orm/knowledge_vault.py#L72-L78](https://github.com/Mirix-AI/MIRIX/blob/8cb06a62bbb7c478beb33dd4f2815696a72df482/mirix/orm/knowledge_vault.py#L72-L78)).
- 채팅 프롬프트에는 high 민감도를 제외합니다.
- 삭제는 타입별 hard delete와 soft delete가 있습니다.

**8. 설치**: Docker compose와 `pip install mirix-client`. MCP 서버는 없습니다.

### 10. MemoryOS — `BAI-LAB/MemoryOS` @ [`587ed77`](https://github.com/BAI-LAB/MemoryOS/tree/587ed7755c7aed179965792830ff1b5ad9a6fa92)

**1. 정체**: Apache-2.0, 약 1.6k, 연구 코드. 변형들이 같은 코드를 복붙해 따로 들고 있습니다.

**2. 쓰기 경로**
- `add_memory(QA)`로 넣습니다.
- short-term이 가득 차면 LLM이 연속성 판정과 요약을 합니다 ([updater.py#L100-L183](https://github.com/BAI-LAB/MemoryOS/blob/587ed7755c7aed179965792830ff1b5ad9a6fa92/memoryos-pypi/updater.py#L100-L183)).

**3. 갱신과 통합**
- 유사도 + Jaccard가 0.6 이상이면 기존 세션에 병합합니다.
- heat(`α·방문 + β·대화량 + γ·최근성`)가 5를 넘으면 두 작업을 돌립니다 ([memoryos.py#L126-L224](https://github.com/BAI-LAB/MemoryOS/blob/587ed7755c7aed179965792830ff1b5ad9a6fa92/memoryos-pypi/memoryos.py#L126-L224)).
  - 90개 차원 profile을 **통째로 교체**
  - 지식 추출
- 모순 처리는 없습니다. 세션은 LFU로 축출하고, 장기 지식은 `deque(100)`이라 오래된 것부터 버려집니다.

**4. 검색**: 쿼리마다 FAISS를 즉석에서 만드는 벡터 검색이고, 결과를 프롬프트에 조립합니다.

**5. 저장소**: JSON 파일 또는 임베디드 Chroma. Docker는 선택입니다.

**6. 로컬과 클라우드**
- 기본 LLM은 OpenAI `gpt-4o-mini`, 임베딩은 로컬 MiniLM/BGE입니다 ([utils.py#L37-L196](https://github.com/BAI-LAB/MemoryOS/blob/587ed7755c7aed179965792830ff1b5ad9a6fa92/memoryos-pypi/utils.py#L37-L44)).
- 호스팅 Platform은 초대제입니다 (README 기준).

**7. 삭제와 프라이버시**: pypi/MCP 경로에 delete API가 없습니다. 추출 프롬프트가 "User private data"를 명시적으로 뽑아냅니다.

**8. 설치**: `pip install memoryos-pro`. stdio MCP 도구 3개 ([server_new.py#L114-L198](https://github.com/BAI-LAB/MemoryOS/blob/587ed7755c7aed179965792830ff1b5ad9a6fa92/memoryos-mcp/server_new.py#L114-L198)).

### 11. Hindsight — `vectorize-io/hindsight` @ [`d5b1d42`](https://github.com/vectorize-io/hindsight/tree/d5b1d4282f3325116c06f76ce3e79dce5ea4e22c)

**1. 정체**: MIT, 약 50k, Python 서버와 Rust CLI.

**2. 쓰기 경로**
- `retain`은 MCP, HTTP, SDK로 호출합니다. MCP 도구 설명이 에이전트에게 "PROACTIVELY" 저장하라고 지시합니다.
- 서버 LLM이 `_BASE_FACT_EXTRACTION_PROMPT`("Be SELECTIVE")로 추출합니다 ([fact_extraction.py#L1058-L1118](https://github.com/vectorize-io/hindsight/blob/d5b1d4282f3325116c06f76ce3e79dce5ea4e22c/hindsight-api-slim/hindsight_api/engine/retain/fact_extraction.py#L1058-L1118)).
- 사실 유형은 world와 experience이고, opinion은 제거됐습니다.
- Claude Code 플러그인은 `Stop` 훅에서 10턴마다 자동 retain합니다 ([retain.py#L76-L110](https://github.com/vectorize-io/hindsight/blob/d5b1d4282f3325116c06f76ce3e79dce5ea4e22c/hindsight-integrations/claude-code/scripts/retain.py#L76-L110)).

**3. 갱신과 통합**
- 엔티티: pg_trgm 유사도와 동시출현 가중치로 해석합니다.
- 링크: temporal, semantic, causal ([orchestrator.py#L762-L850](https://github.com/vectorize-io/hindsight/blob/d5b1d4282f3325116c06f76ce3e79dce5ea4e22c/hindsight-api-slim/hindsight_api/engine/retain/orchestrator.py#L762-L850)).
- 원시 사실은 무효화하지 않습니다. 비동기 observation 통합 단계에서 LLM이 create/update/delete를 냅니다("PREFER UPDATE", "PRESERVE HISTORY") ([consolidation/prompts.py#L37-L172](https://github.com/vectorize-io/hindsight/blob/d5b1d4282f3325116c06f76ce3e79dce5ea4e22c/hindsight-api-slim/hindsight_api/engine/consolidation/prompts.py#L37-L172)).
- 유사도 0.97 이상의 중복은 따로 판정합니다.

**4. 검색**
- semantic + BM25 + graph + temporal → RRF → cross-encoder → recency 가중 ([retrieval.py#L100-L128](https://github.com/vectorize-io/hindsight/blob/d5b1d4282f3325116c06f76ce3e79dce5ea4e22c/hindsight-api-slim/hindsight_api/engine/search/retrieval.py#L100-L128), [reranking.py#L174-L223](https://github.com/vectorize-io/hindsight/blob/d5b1d4282f3325116c06f76ce3e79dce5ea4e22c/hindsight-api-slim/hindsight_api/engine/search/reranking.py#L174-L223)).
- `UserPromptSubmit` 훅으로 자동 주입합니다.

**5. 저장소**
- PostgreSQL + pgvector + pg_trgm입니다.
- 기본 **`pg0` 내장 PG 프로세스라 Docker가 필요 없습니다** ([pg0.py#L19-L68](https://github.com/vectorize-io/hindsight/blob/d5b1d4282f3325116c06f76ce3e79dce5ea4e22c/hindsight-api-slim/hindsight_api/pg0.py#L19-L68), [config.py#L1100](https://github.com/vectorize-io/hindsight/blob/d5b1d4282f3325116c06f76ce3e79dce5ea4e22c/hindsight-api-slim/hindsight_api/config.py#L1100)).

**6. 로컬과 클라우드**
- 로컬 기본 LLM은 OpenAI `gpt-4o-mini`이고, 임베딩과 rerank는 로컬 모델입니다 ([config.py#L1102-L1286](https://github.com/vectorize-io/hindsight/blob/d5b1d4282f3325116c06f76ce3e79dce5ea4e22c/hindsight-api-slim/hindsight_api/config.py#L1102-L1137)). ollama, claude-code 제공자도 됩니다.
- 클라우드는 같은 API에 `base_url`과 Bearer 키만 다릅니다 ([hindsight_client.py#L265-L305](https://github.com/vectorize-io/hindsight/blob/d5b1d4282f3325116c06f76ce3e79dce5ea4e22c/hindsight-clients/python/hindsight_client/hindsight_client.py#L265-L305)).
- 테넌시는 확장으로 처리합니다(API key, Supabase JWT 사용자별 스키마).

**7. 삭제와 프라이버시**
- 하드 `DELETE` 후 재통합합니다. journal은 없습니다 [추론].
- Memory Defense 확장이 정규식으로 redact하거나 block합니다 ([memory_defense_regex.py](https://github.com/vectorize-io/hindsight/blob/d5b1d4282f3325116c06f76ce3e79dce5ea4e22c/hindsight-api-slim/hindsight_api/extensions/builtin/memory_defense_regex.py#L1-L40)).

**8. 설치**: `uvx hindsight-api … hindsight-local-mcp`, `uvx hindsight-embed`, Claude Code 등 플러그인 50개 이상.

### 12. Memobase — `memodb-io/memobase` @ [`358c16b`](https://github.com/memodb-io/memobase/tree/358c16bbc6d687937d79bc2f984a11c3be8da901)

**1. 정체**: Apache-2.0, 약 2.9k. 2026-01 이후 정체입니다.

**2. 쓰기 경로**
- 버퍼가 1024토큰을 넘거나 flush를 부르면 처리합니다.
- 서버 LLM 순서: 요약 → profile 슬롯 추출 → event 태깅 ([chat/__init__.py#L38-L182](https://github.com/memodb-io/memobase/blob/358c16bbc6d687937d79bc2f984a11c3be8da901/src/server/api/memobase_server/controllers/modal/chat/__init__.py#L38-L182)).

**3. 갱신과 통합**
- 슬롯마다 APPEND, UPDATE(재작성), ABORT 중 하나를 고릅니다 ([merge_profile.py#L9-L74](https://github.com/memodb-io/memobase/blob/358c16bbc6d687937d79bc2f984a11c3be8da901/src/server/api/memobase_server/prompts/merge_profile.py#L9-L74)).
- 슬롯이 15개를 넘으면 organize, 너무 길면 re_summary를 돌립니다. 이전 값의 유효기간은 관리하지 않습니다.

**4. 검색**
- `get_user_context`가 LLM 슬롯 필터 + event gist cosine 결과를 토큰 예산 안에 묶어 문자열로 돌려줍니다 ([context.py#L31-L206](https://github.com/memodb-io/memobase/blob/358c16bbc6d687937d79bc2f984a11c3be8da901/src/server/api/memobase_server/controllers/context.py#L31-L206)).
- OpenAI 패치로 주입하고, MCP 도구 3개가 있습니다.

**5. 저장소**: PG + Redis가 필수이고 사실상 Docker가 필요합니다.

**6. 로컬과 클라우드**
- 로컬 기본값은 OpenAI입니다.
- 클라이언트 기본 주소는 `api.memobase.dev`입니다.
- 클라우드는 `sk-proj` 키와 과금, 셀프호스트는 단일 `ACCESS_TOKEN`이고 미설정이면 무인증입니다 ([middleware.py#L115-L199](https://github.com/memodb-io/memobase/blob/358c16bbc6d687937d79bc2f984a11c3be8da901/src/server/api/memobase_server/api_layer/middleware.py#L115-L199)).

**7. 삭제와 프라이버시**
- 기본으로 flush 후 원본 blob을 하드 삭제합니다 ([buffer.py#L211-L215](https://github.com/memodb-io/memobase/blob/358c16bbc6d687937d79bc2f984a11c3be8da901/src/server/api/memobase_server/controllers/buffer.py#L211-L215)).
- 사용자 삭제는 CASCADE입니다. 기본 슬롯에 email과 phone이 있습니다.

**8. 설치**: compose와 `pip install memobase`.

### 13. memU — `NevaMind-AI/memU` @ [`bbf2d70`](https://github.com/NevaMind-AI/memU/tree/bbf2d7040d00c0b5b41b72505085a1349d9b9af6)

**1. 정체**
- 사실상 Apache-2.0입니다 ([LICENSE.txt](https://github.com/NevaMind-AI/memU/blob/bbf2d7040d00c0b5b41b72505085a1349d9b9af6/LICENSE.txt#L1-L3)). 약 14.5k.
- **과거의 resource→items→categories LLM 파이프라인은 이 SHA에 없습니다.**

**2. 쓰기 경로**
- 서버에는 LLM이 없습니다("Embedding-only… No LLM is involved", [service.py#L24-L32](https://github.com/NevaMind-AI/memU/blob/bbf2d7040d00c0b5b41b72505085a1349d9b9af6/src/memu/app/service.py#L24-L32)).
- OS 스케줄러가 headless `claude -p`를 실행합니다. 호스트 에이전트가 대화록을 읽고 markdown recall file을 씁니다.
- 지시는 `MEMORY_JOB_TEMPLATE`의 "Do nothing / Patch / Create"입니다 ([instructions.py#L17-L80](https://github.com/NevaMind-AI/memU/blob/bbf2d7040d00c0b5b41b72505085a1349d9b9af6/src/memu/hosts/bridging/instructions.py#L17-L80)).

**3. 갱신과 통합**
- 같은 키면 last-write-wins로 덮어씁니다. 줄 단위 diff로 바뀐 부분만 재임베딩합니다 ([agentic.py#L578-L668](https://github.com/NevaMind-AI/memU/blob/bbf2d7040d00c0b5b41b72505085a1349d9b9af6/src/memu/app/agentic.py#L578-L668)).
- 모순 처리는 에이전트에 맡깁니다.

**4. 검색**
- cosine만 씁니다 ([agentic.py#L187-L330](https://github.com/NevaMind-AI/memU/blob/bbf2d7040d00c0b5b41b72505085a1349d9b9af6/src/memu/app/agentic.py#L187-L330)).
- CLAUDE.md 지시와 skill로 에이전트가 직접 `retrieve`를 실행합니다.

**5. 저장소**: SQLite(기본), inmemory, PG+pgvector. Docker는 필요 없습니다.

**6. 로컬과 클라우드**
- `MEMU_MEMORY_MODE=cloud`면 `api.memu.so`로 갑니다. 같은 3개 연산만 원격으로 옮깁니다 ([cloud.py#L93-L194](https://github.com/NevaMind-AI/memU/blob/bbf2d7040d00c0b5b41b72505085a1349d9b9af6/src/memu/cloud.py#L93-L194)).
- 로컬 임베딩 기본은 OpenAI입니다.
- 로컬 모드에서도 템플릿 원격 갱신과 텔레메트리가 켜져 있습니다 ([events.py#L40-L79](https://github.com/NevaMind-AI/memU/blob/bbf2d7040d00c0b5b41b72505085a1349d9b9af6/src/memu/events.py#L40-L79)).

**7. 삭제와 프라이버시**: commit 경로에 삭제가 없습니다("Deletions are intentionally not returned", [manifest.py#L43-L56](https://github.com/NevaMind-AI/memU/blob/bbf2d7040d00c0b5b41b72505085a1349d9b9af6/src/memu/hosts/bridging/manifest.py#L43-L56)).

**8. 설치**: `memu-cli`(pip/npm), `memu-claude-code` 등.

### 14. MemOS — `MemTensor/MemOS` @ [`a7367d0`](https://github.com/MemTensor/MemOS/tree/a7367d07e55db61099f7b4e2c1108bc5831a24f3)

**1. 정체**
- Apache-2.0, 약 11.9k, 2026-10-10 push.
- Python 서버(`src/memos`), TS 로컬 플러그인(`apps/memos-local-plugin`), Cloud OpenClaw 플러그인으로 구성됩니다.
- README의 4개 진입점 표(Cloud API / Self-Host=Neo4j+Qdrant / Cloud Plugin / Local Plugin=SQLite)는 README 기준입니다 ([README.md](https://github.com/MemTensor/MemOS/blob/a7367d07e55db61099f7b4e2c1108bc5831a24f3/README.md)).

**2. 쓰기 경로**
- **서버는 LLM이 추출합니다.** 프롬프트 `SIMPLE_STRUCT_MEM_READER_PROMPT`의 주요 지시 ([mem_reader_prompts.py#L1-L36](https://github.com/MemTensor/MemOS/blob/a7367d07e55db61099f7b4e2c1108bc5831a24f3/src/memos/templates/mem_reader_prompts.py#L1-L36)):
  - "Do not omit any information… Prioritize completeness"
  - 상대 시간을 절대 시간으로 바꾸고, 3인칭으로 쓴다.
  - 출력은 `memory list[{key, memory_type: LongTermMemory|UserMemory, value, tags}]`
- `MemoryManager._process_memory`가 WorkingMemory 노드와 LongTerm/User 노드를 함께 만들고, reorganizer 큐에 `add`를 넣습니다 ([manager.py#L309-L427](https://github.com/MemTensor/MemOS/blob/a7367d07e55db61099f7b4e2c1108bc5831a24f3/src/memos/memories/textual/tree_text_memory/organize/manager.py#L309-L367)).
- **로컬 플러그인**
  - OpenClaw 훅 `before_prompt_build`가 recall을 주입합니다.
  - `agent_end`가 capture와 reward 체인을 fire-and-forget으로 돌립니다 ([adapters/openclaw/index.ts#L441-L453](https://github.com/MemTensor/MemOS/blob/a7367d07e55db61099f7b4e2c1108bc5831a24f3/apps/memos-local-plugin/adapters/openclaw/index.ts#L441-L453)).
  - 모든 턴을 L1 trace로 자동 캡처합니다. 그 뒤 LLM이 reflection·reward 점수, L2 policy 유도, L3 world model, skill crystallize를 수행합니다(ARCHITECTURE 문서 기준, [ARCHITECTURE.md](https://github.com/MemTensor/MemOS/blob/a7367d07e55db61099f7b4e2c1108bc5831a24f3/apps/memos-local-plugin/ARCHITECTURE.md)).
  - 프롬프트: [core/llm/prompts/](https://github.com/MemTensor/MemOS/tree/a7367d07e55db61099f7b4e2c1108bc5831a24f3/apps/memos-local-plugin/core/llm/prompts)(`l2-induction`, `l3-abstraction`, `reward`, `skill-crystallize`, `retrieval-filter`).

**3. 갱신과 통합**
- `GraphStructureReorganizer`는 `is_reorganize=True`일 때만 스레드를 띄우고, 100초마다 `optimize_structure`(클러스터 요약)를 돌립니다 ([reorganizer.py#L94-L106](https://github.com/MemTensor/MemOS/blob/a7367d07e55db61099f7b4e2c1108bc5831a24f3/src/memos/memories/textual/tree_text_memory/organize/reorganizer.py#L94-L106), [#L158-L159](https://github.com/MemTensor/MemOS/blob/a7367d07e55db61099f7b4e2c1108bc5831a24f3/src/memos/memories/textual/tree_text_memory/organize/reorganizer.py#L158-L159)). `MemoryManager`의 `is_reorganize` 기본값은 False입니다 ([manager.py#L63](https://github.com/MemTensor/MemOS/blob/a7367d07e55db61099f7b4e2c1108bc5831a24f3/src/memos/memories/textual/tree_text_memory/organize/manager.py#L54-L88)).
- `handle_add` → `NodeHandler.detect` ([reorganizer.py#L192-L206](https://github.com/MemTensor/MemOS/blob/a7367d07e55db61099f7b4e2c1108bc5831a24f3/src/memos/memories/textual/tree_text_memory/organize/reorganizer.py#L192-L206), [handler.py#L22-L75](https://github.com/MemTensor/MemOS/blob/a7367d07e55db61099f7b4e2c1108bc5831a24f3/src/memos/memories/textual/tree_text_memory/organize/handler.py#L22-L75)):
  - 임베딩 유사도 0.8 이상인 후보 5개를 고릅니다.
  - LLM `MEMORY_RELATION_DETECTOR_PROMPT`가 `contradictory | redundant | independent`로 분류합니다 ([tree_reorganize_prompts.py#L197-L208](https://github.com/MemTensor/MemOS/blob/a7367d07e55db61099f7b4e2c1108bc5831a24f3/src/memos/templates/tree_reorganize_prompts.py#L197-L208)).
- `resolve` ([handler.py#L76-L190](https://github.com/MemTensor/MemOS/blob/a7367d07e55db61099f7b4e2c1108bc5831a24f3/src/memos/memories/textual/tree_text_memory/organize/handler.py#L76-L129)):
  - `MEMORY_RELATION_RESOLVER_PROMPT`가 두 기억을 합칩니다. 지시는 "최신·고신뢰 우선, 해소 불가면 `<answer>No</answer>`"입니다 ([#L211-L230](https://github.com/MemTensor/MemOS/blob/a7367d07e55db61099f7b4e2c1108bc5831a24f3/src/memos/templates/tree_reorganize_prompts.py#L211-L230)).
  - 합치면 `_resolve_in_graph`가 두 원본을 `status: archived`로 바꾸고 `MERGED_TO` 엣지와 엣지 상속을 남깁니다.
  - "No"면 `_hard_update`가 `updated_at`이 더 오래된 노드를 **`delete_node`로 하드 삭제**합니다 ([#L131-L149](https://github.com/MemTensor/MemOS/blob/a7367d07e55db61099f7b4e2c1108bc5831a24f3/src/memos/memories/textual/tree_text_memory/organize/handler.py#L131-L149)).
- 자연어 피드백 수정
  - `semantics_feedback`이 LLM ADD/UPDATE를 만듭니다.
  - UPDATE가 5건 이상이면 `filter_fault_update`가 LLM으로 다시 검증합니다.
  - UPDATE는 새 항목을 추가하고 옛 항목은 archive하거나 version history를 남깁니다 ([mem_feedback/feedback.py#L269-L410](https://github.com/MemTensor/MemOS/blob/a7367d07e55db61099f7b4e2c1108bc5831a24f3/src/memos/mem_feedback/feedback.py#L269-L410), [#L788-L832](https://github.com/MemTensor/MemOS/blob/a7367d07e55db61099f7b4e2c1108bc5831a24f3/src/memos/mem_feedback/feedback.py#L788-L832)).

**4. 검색**
- 서버: graph(키·태그 메타데이터) + vector + BM25 + (fast 모드) fulltext를 병렬로 돌리고 합칩니다 ([recall.py#L81-L184](https://github.com/MemTensor/MemOS/blob/a7367d07e55db61099f7b4e2c1108bc5831a24f3/src/memos/memories/textual/tree_text_memory/retrieve/recall.py#L81-L184)). 그다음 reranker를 거칩니다.
- 로컬 플러그인
  - 채널: SQLite FTS5 trigram + 패턴 + brute-force cosine ([storage/keyword.ts](https://github.com/MemTensor/MemOS/blob/a7367d07e55db61099f7b4e2c1108bc5831a24f3/apps/memos-local-plugin/core/storage/keyword.ts), [storage/vector.ts#L1-L20](https://github.com/MemTensor/MemOS/blob/a7367d07e55db61099f7b4e2c1108bc5831a24f3/apps/memos-local-plugin/core/storage/vector.ts#L1-L20))
  - 채널별 RRF 가산(`RRF_WEIGHT=0.4`), MMR, 선택적 LLM 필터 ([retrieval/ranker.ts#L12-L128](https://github.com/MemTensor/MemOS/blob/a7367d07e55db61099f7b4e2c1108bc5831a24f3/apps/memos-local-plugin/core/retrieval/ranker.ts#L12-L34))
  - 결과는 `prependContext`로 주입합니다.

**5. 저장소**
- 서버: graph_dbs는 Neo4j(Enterprise/Community), PolarDB, Postgres 중 하나입니다 ([graph_dbs/](https://github.com/MemTensor/MemOS/tree/a7367d07e55db61099f7b4e2c1108bc5831a24f3/src/memos/graph_dbs)). 공식 경로는 compose(API + Neo4j + Qdrant)이며 Docker가 사실상 필요합니다 (README 기준).
- 로컬 플러그인: `better-sqlite3` WAL 단일 파일입니다 ([storage/connection.ts#L18-L46](https://github.com/MemTensor/MemOS/blob/a7367d07e55db61099f7b4e2c1108bc5831a24f3/apps/memos-local-plugin/core/storage/connection.ts#L18-L46)). Docker는 필요 없습니다.

**6. 로컬과 클라우드**
- 셀프호스트 서버의 예시 기본값은 **Alibaba DashScope**입니다: `qwen3-max` LLM, `text-embedding-v4` 임베딩 ([docker/.env.example#L6-L53](https://github.com/MemTensor/MemOS/blob/a7367d07e55db61099f7b4e2c1108bc5831a24f3/docker/.env.example#L6-L53)). 로컬 서버도 클라우드 LLM을 부르는 셈입니다.
- 서버 인증 ([middleware/auth.py#L26-L27](https://github.com/MemTensor/MemOS/blob/a7367d07e55db61099f7b4e2c1108bc5831a24f3/src/memos/api/middleware/auth.py#L26-L27), [#L60-L237](https://github.com/MemTensor/MemOS/blob/a7367d07e55db61099f7b4e2c1108bc5831a24f3/src/memos/api/middleware/auth.py#L157-L237)):
  - 기본 `AUTH_ENABLED=false`
  - 켜면 `krlk_<hex>` 키의 SHA-256을 Postgres `api_keys`에서 조회하고, scopes와 master key를 씁니다.
- 클라우드 클라이언트 `MemOSClient` ([api/client.py#L36-L62](https://github.com/MemTensor/MemOS/blob/a7367d07e55db61099f7b4e2c1108bc5831a24f3/src/memos/api/client.py#L36-L62)):
  - 기본 주소: `https://memos.memtensor.cn/api/openmem/v1`(CN), `https://api.memt.ai/platform/api/openmem/v1`(global)
  - `Authorization: Token MEMOS_API_KEY`
- 로컬 플러그인 기본값 ([config/defaults.ts#L35-L53](https://github.com/MemTensor/MemOS/blob/a7367d07e55db61099f7b4e2c1108bc5831a24f3/apps/memos-local-plugin/core/config/defaults.ts#L35-L53), [#L330-L340](https://github.com/MemTensor/MemOS/blob/a7367d07e55db61099f7b4e2c1108bc5831a24f3/apps/memos-local-plugin/core/config/defaults.ts#L330-L340)):
  - 임베딩: **로컬 `Xenova/all-MiniLM-L6-v2`**
  - LLM: 비어 있음. 비어 있으면 호스트(OpenClaw/DSH) LLM 브리지로 해석됩니다(ARCHITECTURE 기준).
  - hub(팀 공유): 꺼짐
  - **telemetry: 켜짐**
- Cloud 플러그인은 `before_prompt_build`/`agent_end`에서 MemOS Cloud `/add/message`, `/search/memory`를 호출하고, 중복 `agent_end`는 건너뜁니다 ([MemOS-Cloud-OpenClaw-Plugin/index.js#L854-L915](https://github.com/MemTensor/MemOS/blob/a7367d07e55db61099f7b4e2c1108bc5831a24f3/apps/MemOS-Cloud-OpenClaw-Plugin/index.js#L846-L915)).

**7. 삭제와 프라이버시**
- `handle_delete_memories`는 memory_ids, file_ids, filter 중 정확히 하나의 모드만 받습니다. 선택적으로 working binding도 정리합니다 ([memory_handler.py#L371-L420](https://github.com/MemTensor/MemOS/blob/a7367d07e55db61099f7b4e2c1108bc5831a24f3/src/memos/api/handlers/memory_handler.py#L371-L420)).
- reorganizer 경로에서는 archived(보존)와 hard delete(해소 불가 충돌)가 섞여 있습니다. journal은 없습니다 [추론].
- 로컬 플러그인은 `config.yaml`의 API 키 필드를 비밀 필드로 지정하고 viewer에서 가립니다 ([defaults.ts#L384-L391](https://github.com/MemTensor/MemOS/blob/a7367d07e55db61099f7b4e2c1108bc5831a24f3/apps/memos-local-plugin/core/config/defaults.ts#L384-L391)).
- 기억 내용에 대한 secret 필터는 확인하지 못했습니다.

**8. 설치**
- 클라우드: `mpg-` API 키.
- 셀프호스트: `docker compose up` 또는 uvicorn.
- MCP: `mcp_serve.py`의 FastMCP 도구(`add_memory`, `search_memories`, `delete_memory`, `delete_all_memories`, `share_cube` 등) ([mcp_serve.py#L139-L570](https://github.com/MemTensor/MemOS/blob/a7367d07e55db61099f7b4e2c1108bc5831a24f3/src/memos/api/mcp_serve.py#L139-L570)).
- 로컬 플러그인: npm과 `install.sh`(OpenClaw/Hermes/DSH).

### 15. Memori — `GibsonAI/memori` → `MemoriLabs/Memori` @ [`574b1ea`](https://github.com/MemoriLabs/Memori/tree/574b1ea3e876f100ef82c37817d603eb7e258e59)

**1. 정체**
- GitHub API는 라이선스를 NOASSERTION으로 표시하지만 LICENSE 파일은 Apache-2.0입니다. 약 17k, 2026-10-03 push.
- Python SDK, Rust core(`core/src`), TS SDK로 구성됩니다.

**2. 쓰기 경로**
- **LLM 클라이언트 래핑이 트리거입니다.** `memori.llm.register(client)`로 OpenAI, Anthropic, Google 등의 호출을 가로챕니다 ([memori/__init__.py#L91-L167](https://github.com/MemoriLabs/Memori/blob/574b1ea3e876f100ef82c37817d603eb7e258e59/memori/__init__.py#L117-L167)).
- 대화가 끝나면 `AdvancedAugmentation.process`가 실행됩니다 ([_augmentation.py#L39-L180](https://github.com/MemoriLabs/Memori/blob/574b1ea3e876f100ef82c37817d603eb7e258e59/memori/memory/augmentation/augmentations/memori/_augmentation.py#L125-L180)).
  - 최근 user/assistant 쌍, 요약, 시스템 프롬프트, entity/process ID 해시를 묶습니다.
  - **Memori API `sdk/augmentation`으로 보냅니다.**
  - 돌아온 facts와 triples를 로컬 DB에 씁니다.
- **무엇을 기억할지는 Memori 클라우드 LLM이 정합니다(비공개).** 추출 프롬프트는 OSS에 없습니다.

**3. 갱신과 통합**
- 로컬(BYODB)은 정확 해시 upsert뿐입니다.
  - `memori_entity_fact`: `ON CONFLICT(entity_id, uniq) DO UPDATE SET num_times+1, date_last_time`
  - 트리플: subject/predicate/object `uniq`로 같은 방식의 upsert ([sqlite/_driver.py#L233-L287](https://github.com/MemoriLabs/Memori/blob/574b1ea3e876f100ef82c37817d603eb7e258e59/memori/storage/drivers/sqlite/_driver.py#L233-L287), [#L414-L543](https://github.com/MemoriLabs/Memori/blob/574b1ea3e876f100ef82c37817d603eb7e258e59/memori/storage/drivers/sqlite/_driver.py#L414-L543))
- 모순과 시간 무효화는 OSS 코드에 없습니다. 클라우드에서 처리하는지는 확인할 수 없습니다 [추론].

**4. 검색**
- 로컬: 임베딩 cosine + lexical을 가중 결합합니다 (`dense_lexical_weights`, [search/_core.py#L116-L150](https://github.com/MemoriLabs/Memori/blob/574b1ea3e876f100ef82c37817d603eb7e258e59/memori/search/_core.py#L116-L150)). 기본 임베딩은 로컬 `all-MiniLM-L6-v2`, facts 5개, threshold 0.1입니다 ([_config.py#L62-L88](https://github.com/MemoriLabs/Memori/blob/574b1ea3e876f100ef82c37817d603eb7e258e59/memori/_config.py#L62-L88)).
- 주입: `inject_recalled_facts`가 매 LLM 호출마다 system에 `<memori_context>` "Relevant context about the user"를 자동으로 붙입니다 ([recall_injection.py#L107-L195](https://github.com/MemoriLabs/Memori/blob/574b1ea3e876f100ef82c37817d603eb7e258e59/memori/llm/pipelines/recall_injection.py#L107-L130)).

**5. 저장소**
- BYODB 드라이버: SQLite, PostgreSQL, MySQL, MongoDB, Oracle, OceanBase, TiDB, CockroachDB ([storage/drivers/](https://github.com/MemoriLabs/Memori/tree/574b1ea3e876f100ef82c37817d603eb7e258e59/memori/storage/drivers)). SQLite면 Docker가 필요 없습니다.

**6. 로컬과 클라우드** ([__init__.py#L145-L186](https://github.com/MemoriLabs/Memori/blob/574b1ea3e876f100ef82c37817d603eb7e258e59/memori/__init__.py#L145-L186))
- 모드 결정
  - `conn`을 넘기면 BYODB입니다.
  - 넘기지 않으면 `MEMORI_COCKROACHDB_CONNECTION_STRING`을 보고, 그것도 없으면 Cloud 모드이며 `MEMORI_API_KEY`가 필수입니다.
- **BYODB도 추출은 클라우드 API입니다.**
  - `Api`의 기본 base는 `https://{subdomain}.memorilabs.ai`이고, SDK에 하드코딩된 공용 `X-Memori-API-Key` 헤더를 씁니다 ([_network.py#L40-L62](https://github.com/MemoriLabs/Memori/blob/574b1ea3e876f100ef82c37817d603eb7e258e59/memori/_network.py#L40-L62)).
  - `MEMORI_API_KEY`가 없으면 "anonymous"로 다뤄지고, 429 응답에서 `QuotaExceededError`가 납니다 ([#L106-L112](https://github.com/MemoriLabs/Memori/blob/574b1ea3e876f100ef82c37817d603eb7e258e59/memori/_network.py#L106-L112), [#L233-L243](https://github.com/MemoriLabs/Memori/blob/574b1ea3e876f100ef82c37817d603eb7e258e59/memori/_network.py#L233-L243)).
  - 전송되는 것: 대화 원문, 요약, 시스템 프롬프트, LLM/프레임워크 메타데이터. 데이터 egress가 기본입니다.
- 클라우드 전용: `agent_recall`, `agent_compaction`, `agent_feedback` ([__init__.py#L266-L348](https://github.com/MemoriLabs/Memori/blob/574b1ea3e876f100ef82c37817d603eb7e258e59/memori/__init__.py#L266-L348)).
- Claude Code 통합
  - `api.memorilabs.ai/v1`과 `collector.memorilabs.ai`에 직접 연결하고 `/agent/recall`을 씁니다 ([integrations/claude-code/index.ts#L97-L98](https://github.com/MemoriLabs/Memori/blob/574b1ea3e876f100ef82c37817d603eb7e258e59/integrations/claude-code/index.ts#L97-L98), [#L301-L339](https://github.com/MemoriLabs/Memori/blob/574b1ea3e876f100ef82c37817d603eb7e258e59/integrations/claude-code/index.ts#L301-L339)).
  - hosted MCP는 `https://api.memorilabs.ai/mcp/`입니다 (README 기준).

**7. 삭제와 프라이버시**
- `delete_entity_memories`는 entity의 facts와 KG를 지우고 "conversations는 보존"합니다 ([__init__.py#L254-L264](https://github.com/MemoriLabs/Memori/blob/574b1ea3e876f100ef82c37817d603eb7e258e59/memori/__init__.py#L254-L264), [sqlite/_driver.py#L401](https://github.com/MemoriLabs/Memori/blob/574b1ea3e876f100ef82c37817d603eb7e258e59/memori/storage/drivers/sqlite/_driver.py#L401-L412)).
- entity/process ID만 해시해서 보냅니다 ([_augmentation.py#L101-L104](https://github.com/MemoriLabs/Memori/blob/574b1ea3e876f100ef82c37817d603eb7e258e59/memori/memory/augmentation/augmentations/memori/_augmentation.py#L101-L104)). 원문 redaction은 보지 못했습니다.

**8. 설치**: `pip install memori`, TS SDK, `claude mcp add --transport http memori https://api.memorilabs.ai/mcp/` (README 기준), OpenClaw/Hermes 플러그인.

### 16. Memary — `kingjulio8238/Memary` @ [`b2331a2`](https://github.com/kingjulio8238/Memary/tree/b2331a2c0844d66f69acd607b9e4dbaba56552c1)

**1. 정체**: MIT, 약 2.7k, **2024-10 이후 정체**. LlamaIndex 기반입니다.

**2. 쓰기 경로**
- `query()`가 ReAct 응답을 `data/external_response.txt`에 쓰고, `write_back()`이 `KnowledgeGraphIndex.from_documents(max_triplets_per_chunk=8)`로 LLM 트리플을 추출해 그래프에 넣습니다 ([base_agent.py#L222-L242](https://github.com/kingjulio8238/Memary/blob/b2331a2c0844d66f69acd607b9e4dbaba56552c1/src/memary/agent/base_agent.py#L222-L242)).
- 즉 에이전트의 **답변**을 LlamaIndex 기본 KG 추출 프롬프트에 그대로 넣는 구조입니다.

**3. 갱신과 통합**
- dedup과 모순 처리는 없습니다.
- `EntityKnowledgeStore`가 엔티티 언급 `count`만 합산합니다 ([entity_knowledge_store.py#L42-L64](https://github.com/kingjulio8238/Memary/blob/b2331a2c0844d66f69acd607b9e4dbaba56552c1/src/memary/memory/entity_knowledge_store.py#L42-L64)).

**4. 검색**
- `check_KG`가 KG query engine으로 찾고, 빈도 상위 엔티티와 memory stream을 프롬프트 컨텍스트에 넣습니다 ([base_agent.py#L244-L298](https://github.com/kingjulio8238/Memary/blob/b2331a2c0844d66f69acd607b9e4dbaba56552c1/src/memary/agent/base_agent.py#L244-L298)).

**5. 저장소**: Neo4j 또는 FalkorDB 서버 + JSON 파일 ([base_agent.py#L85-L126](https://github.com/kingjulio8238/Memary/blob/b2331a2c0844d66f69acd607b9e4dbaba56552c1/src/memary/agent/base_agent.py#L85-L126)).

**6. 로컬과 클라우드**: LLM은 OpenAI `gpt-3.5-turbo-instruct` 또는 Ollama입니다 ([#L135-L145](https://github.com/kingjulio8238/Memary/blob/b2331a2c0844d66f69acd607b9e4dbaba56552c1/src/memary/agent/base_agent.py#L135-L145)). 클라우드 제품은 없습니다.

**7. 삭제와 프라이버시**: 삭제 API가 없습니다.

**8. 설치**: `pip install memary` (README 기준).

### 17. Honcho — `plastic-labs/honcho` @ [`ed17042`](https://github.com/plastic-labs/honcho/tree/ed1704265e609364da6bf291bb3369bc9654f8dc)

**1. 정체**: **AGPL-3.0**, 약 7.6k, Python.

**2. 쓰기 경로**
- `POST messages` → 큐 → deriver 워커 순서입니다.
- 서버 LLM이 `minimal_deriver_prompt`("explicit atomic facts")로 추출합니다 ([deriver/prompts.py#L46-L100](https://github.com/plastic-labs/honcho/blob/ed1704265e609364da6bf291bb3369bc9654f8dc/src/deriver/prompts.py#L46-L100)).
- 결과는 observer/observed 범위로 나뉜 결론 문서입니다.

**3. 갱신과 통합**
- 정확 일치 dedup과, 거리 0.05 이하 의미 dedup을 합니다. 의미 dedup은 더 풍부한 텍스트를 남기고 패자를 soft-delete합니다 ([document.py#L1409-L1611](https://github.com/plastic-labs/honcho/blob/ed1704265e609364da6bf291bb3369bc9654f8dc/src/crud/document.py#L1597-L1611)).
- Dreamer의 `DeductionSpecialist`는 "시점별로 값이 다르면 deductive update를 만들고 오래된 observation을 즉시 DELETE"하며, 모순은 contradiction 레벨로 남깁니다. `source_ids` 인용이 필수입니다 ([specialists.py#L620-L678](https://github.com/plastic-labs/honcho/blob/ed1704265e609364da6bf291bb3369bc9654f8dc/src/dreamer/specialists.py#L620-L678)).

**4. 검색**
- pgvector와 FTS를 RRF로 합칩니다 ([utils/search.py#L36-L70](https://github.com/plastic-labs/honcho/blob/ed1704265e609364da6bf291bb3369bc9654f8dc/src/utils/search.py#L36-L70)).
- dialectic `chat`은 tool-loop 에이전트입니다.
- 주입은 SDK나 MCP를 명시적으로 호출해서 합니다.

**5. 저장소**: PG + pgvector + Redis + deriver. 사실상 Docker가 필요합니다.

**6. 로컬과 클라우드**
- 같은 코드입니다. SDK와 MCP(Cloudflare Worker) 기본 주소는 `api.honcho.dev`입니다 ([client.py#L50-L51](https://github.com/plastic-labs/honcho/blob/ed1704265e609364da6bf291bb3369bc9654f8dc/sdks/python/src/honcho/client.py#L50-L51)).
- 셀프호스트는 인증이 기본 꺼져 있고, 켜면 HS256 JWT(workspace/peer/session 스코프)입니다 ([security.py#L35-L190](https://github.com/plastic-labs/honcho/blob/ed1704265e609364da6bf291bb3369bc9654f8dc/src/security.py#L35-L190)).
- 로컬 기본 모델은 OpenAI `gpt-5.4-mini`입니다.

**7. 삭제와 프라이버시**: 세션 삭제는 비동기로 결론 문서까지 지웁니다. 문서 단위는 soft 후 hard 삭제입니다 ([document.py#L1621-L1694](https://github.com/plastic-labs/honcho/blob/ed1704265e609364da6bf291bb3369bc9654f8dc/src/crud/document.py#L1621-L1694)).

**8. 설치**: `honcho-cli` 마법사 → docker compose.

### 18. Redis Agent Memory Server — `redis/agent-memory-server` @ [`94192c3`](https://github.com/redis/agent-memory-server/tree/94192c39e2a4a154f441a5411e3d73c4f54974a6)

**1. 정체**
- 약 0.3k.
- **OSS는 `V0/`에 동결돼 있고 "더 이상 유지보수되지 않는다"고 명시합니다. 정식 제품은 관리형 Redis Iris입니다** (README 기준, [README#L1-L47](https://github.com/redis/agent-memory-server/blob/94192c39e2a4a154f441a5411e3d73c4f54974a6/README.md#L1-L47)).

**2. 쓰기 경로**
- working memory를 저장하면 백그라운드에서 long-term으로 승격합니다.
- 30초 debounce 후 서버 LLM이 추출합니다. 기본 전략은 `DiscreteMemoryStrategy`입니다 ([memory_strategies.py#L68-L183](https://github.com/redis/agent-memory-server/blob/94192c39e2a4a154f441a5411e3d73c4f54974a6/V0/agent_memory_server/memory_strategies.py#L68-L183)).
- 에이전트가 MCP로 직접 만들 수도 있습니다.

**3. 갱신과 통합**
- id → hash → semantic(0.35) 순으로 중복을 검사하고, 걸리면 LLM 병합을 합니다 ([long_term_memory.py#L1217-L1351](https://github.com/redis/agent-memory-server/blob/94192c39e2a4a154f441a5411e3d73c4f54974a6/V0/agent_memory_server/long_term_memory.py#L1217-L1351)).
- 10분마다 compaction을 돌립니다. 모순과 대체 처리는 없습니다.

**4. 검색**: semantic, keyword(BM25), hybrid(α=0.7). MCP `memory_prompt`로 주입합니다.

**5. 저장소**: Redis Stack이 필수입니다.

**6. 로컬과 클라우드**
- 로컬 기본 모델은 gpt-5와 gpt-5-mini, 인증은 꺼짐입니다.
- 클라우드 API 형태(`/v1/stores/{id}/…`)는 벤치마크 어댑터 코드에만 있습니다 ([redis_agent_memory_store.py#L45-L144](https://github.com/redis/agent-memory-server/blob/94192c39e2a4a154f441a5411e3d73c4f54974a6/agent-memory-benchmark/src/agent_memory_benchmark/memory/redis_agent_memory_store.py#L45-L75)).

**7. 삭제와 프라이버시**: 즉시 삭제하고 journal은 없습니다. 정책 기반 망각이 있지만 기본 꺼짐입니다.

**8. 설치**: compose 또는 `uvx` MCP.

### 19. MemMachine — `MemMachine/MemMachine` @ [`d5a39a8`](https://github.com/MemMachine/MemMachine/tree/d5a39a8e774e977fb1e6c22efb03555c4e51e05e)

**1. 정체**: Apache-2.0, 약 3.1k.

**2. 쓰기 경로**
- 에피소드는 원문을 그대로 저장합니다(Neo4j derivative 노드).
- 프로필은 백그라운드에서 서버 LLM이 처리합니다. 미처리 메시지 5개 이상 또는 5분 경과가 조건입니다.
- `build_update_prompt`가 `{"command":"add"|"delete"}`를 출력하고, "추론하라"고 지시합니다 ([semantic_prompt_template.py#L6-L153](https://github.com/MemMachine/MemMachine/blob/d5a39a8e774e977fb1e6c22efb03555c4e51e05e/packages/server/src/memmachine_server/semantic_memory/util/semantic_prompt_template.py#L6-L153)).

**3. 갱신과 통합**
- `_apply_commands`가 명령을 적용합니다 ([semantic_ingestion.py#L299-L346](https://github.com/MemMachine/MemMachine/blob/d5a39a8e774e977fb1e6c22efb03555c4e51e05e/packages/server/src/memmachine_server/semantic_memory/semantic_ingestion.py#L299-L346)).
- feature가 20개 이상이면 LLM 통합을 돌리고, keep 목록에 없으면 **기본 삭제**합니다 ([#L348-L501](https://github.com/MemMachine/MemMachine/blob/d5a39a8e774e977fb1e6c22efb03555c4e51e05e/packages/server/src/memmachine_server/semantic_memory/semantic_ingestion.py#L348-L501)).

**4. 검색**: 벡터 → 이웃 맥락 확장 → RRF(identity+BM25) rerank. MCP나 OpenClaw 훅으로 주입합니다.

**5. 저장소**: pgvector + Neo4j + Qdrant(compose). Docker를 안 쓰는 경로도 JDK와 Neo4j를 설치합니다.

**6. 로컬과 클라우드**
- TS SDK 기본 주소는 `api.memmachine.ai/v2`입니다.
- **OSS 서버에는 인증 검증이 없습니다.** org/user는 헤더로만 전달됩니다 ([mcp.py#L255-L317](https://github.com/MemMachine/MemMachine/blob/d5a39a8e774e977fb1e6c22efb03555c4e51e05e/packages/server/src/memmachine_server/server/api_v2/mcp.py#L255-L317)).
- 로컬 기본 모델은 gpt-4o-mini입니다.

**7. 삭제와 프라이버시**: 에피소드 삭제 시 의미 기억 쪽은 history 행만 지웁니다. 파생 feature가 남는지는 [추론]입니다.

**8. 설치**: compose 또는 `pip install memmachine-server`.

### 20. OpenViking — `volcengine/OpenViking` @ [`46e15a2`](https://github.com/volcengine/OpenViking/tree/46e15a248863831e34c4602dc96112b0b120aae2)

**1. 정체**: **AGPL-3.0**, 약 40k, Python + C++ + Rust.

**2. 쓰기 경로**
- `Session.commit_async` → `_extract_user_memories` 순서입니다. VLM이 없으면 예외를 던집니다 ([compressor_v3.py#L662-L812](https://github.com/volcengine/OpenViking/blob/46e15a248863831e34c4602dc96112b0b120aae2/openviking/session/compressor_v3.py#L662-L812)).
- ReAct `ExtractLoop`가 "create, update, delete, or reorganize"를 판단합니다.
- Claude Code 훅은 Stop 시점에 임계치를 넘으면 commit합니다.

**3. 갱신과 통합**
- 기억 종류는 YAML 스키마별 `merge_op`(immutable/patch)로 정의됩니다. events는 add_only입니다.
- 삭제는 LLM이 `DeleteId`를 내면 처리합니다.
- 병합 정책 프롬프트: "유사도만으로 같은 기억이라 판단하지 말 것" ([merge_policy.py#L5-L20](https://github.com/volcengine/OpenViking/blob/46e15a248863831e34c4602dc96112b0b120aae2/openviking/session/memory/merge_policy.py#L5-L20)).

**4. 검색**
- 전역 dense+sparse 검색 + 선택적 rerank입니다 ([hierarchical_retriever.py#L1-L5](https://github.com/volcengine/OpenViking/blob/46e15a248863831e34c4602dc96112b0b120aae2/openviking/retrieve/hierarchical_retriever.py#L1-L5)).
- 훅의 additionalContext로 주입합니다.

**5. 저장소**: 내장 벡터 엔진 + 로컬 RAGFS. Docker는 선택입니다.

**6. 로컬과 클라우드**
- **임베딩 기본값이 `volcengine`(클라우드)입니다** ([embedding_config.py#L69-L80](https://github.com/volcengine/OpenViking/blob/46e15a248863831e34c4602dc96112b0b120aae2/openviking_cli/utils/config/embedding_config.py#L69-L80)). 로컬 GGUF와 Ollama도 가능합니다.
- 클라우드 예시는 VikingDB + TOS + doubao 조합입니다.

**7. 삭제와 프라이버시**: `forget`은 `fs.rm`으로 영구 삭제하고 부모 요약을 다시 계산합니다.

**8. 설치**: `uv tool install openviking`.

### 21. EverOS (구 EverMemOS) — `EverMind-AI/EverOS` @ [`5d9fd4d`](https://github.com/EverMind-AI/EverOS/tree/5d9fd4d91a70098466ffa1bd62454c8362c2c8e9)

**1. 정체**: Apache-2.0, 약 13k. 알고리즘은 everalgo 패키지에 있습니다.

**2. 쓰기 경로**
- 서버 LLM 순서: 경계 탐지("default to merging") → episode → profile.
- LLM은 Tier-1 필수입니다 ([capabilities.py#L36-L41](https://github.com/EverMind-AI/EverOS/blob/5d9fd4d91a70098466ffa1bd62454c8362c2c8e9/src/everos/component/capabilities.py#L36-L41)).

**3. 갱신과 통합**
- profile은 add/update/delete/none 연산을 내고, 결정적으로 병합하며 stale 연산은 거부합니다 ([extract_user_profile.py#L219-L317](https://github.com/EverMind-AI/EverOS/blob/5d9fd4d91a70098466ffa1bd62454c8362c2c8e9/src/everos/memory/strategies/extract_user_profile.py#L219-L317)).
- 야간 Reflection이 episode를 통합합니다.

**4. 검색**: BM25/vector/RRF hybrid + LR 보정, agentic(rerank + LLM). 훅으로 주입합니다.

**5. 저장소**: **Markdown이 원본**이고 SQLite와 LanceDB 인덱스는 다시 만들 수 있습니다. Docker는 필요 없습니다.

**6. 로컬과 클라우드**
- 로컬 기본값도 OpenRouter LLM과 DeepInfra 임베딩·rerank입니다 ([default.toml#L68-L153](https://github.com/EverMind-AI/EverOS/blob/5d9fd4d91a70098466ffa1bd62454c8362c2c8e9/src/everos/config/default.toml#L68-L74)).
- 서버는 loopback 전용이고 인증이 없습니다.
- **저장소에 있는 Claude Code 플러그인의 기본 대상은 `api.evermind.ai` 클라우드입니다.**

**7. 삭제와 프라이버시**: 셀프호스트에는 `forget`이 없습니다. md 파일을 지우면 인덱스만 따라 지워집니다.

**8. 설치**: `pip install everos`.

### 22. ReMe — `agentscope-ai/ReMe` @ [`404aa6b`](https://github.com/agentscope-ai/ReMe/tree/404aa6bf3b0cbe5047c504b347271fbb7d268aeb)

**1. 정체**
- Apache-2.0, 약 3.6k.
- personal/task/tool op 구조는 사라졌고 "Markdown 파일 = 기억"으로 바뀌었습니다.

**2. 쓰기 경로**: Stop 훅 → 서버 LLM agent가 `daily_write`와 `edit` 도구로 노트를 편집합니다("Be comprehensive", [auto_memory.yaml](https://github.com/agentscope-ai/ReMe/blob/404aa6bf3b0cbe5047c504b347271fbb7d268aeb/reme/steps/evolve/auto_memory.yaml#L1-L23)).

**3. 갱신과 통합**
- 매일 23시 dream이 CREATE, CORROBORATE, REFINE, CORRECT 중 하나를 고릅니다.
- 모순은 지우지 않고 `contradicted by [[path]]`로 표시합니다 ([integrate.yaml#L38-L66](https://github.com/agentscope-ai/ReMe/blob/404aa6bf3b0cbe5047c504b347271fbb7d268aeb/reme/steps/evolve/dream/integrate.yaml#L38-L66)).

**4. 검색**: vector+BM25 RRF이지만 기본 설정에서는 사실상 BM25입니다 [추론]. `<reme-context>` 훅으로 주입합니다.

**5. 저장소**: Markdown + jsonl.zst. Docker는 선택입니다.

**6. 로컬과 클라우드**: 클라우드 제품은 없습니다. LLM 기본값은 Qwen/DashScope입니다.

**7. 삭제와 프라이버시**: 파일 하드 삭제입니다.

**8. 설치**: `pip install "reme-ai[core]"`.

### 23. memvid — `memvid/memvid` @ [`e6bd9f7`](https://github.com/memvid/memvid/tree/e6bd9f7b9c38cd8d5370fa0fc936ac1dcd751813)

**1. 정체**: Apache-2.0, 약 16.6k, Rust.

**2. 쓰기 경로**
- **LLM 없이 append합니다.** 호출 코드가 무엇을 넣을지 정합니다 ([mutation.rs#L3104-L3131](https://github.com/memvid/memvid/blob/e6bd9f7b9c38cd8d5370fa0fc936ac1dcd751813/src/memvid/mutation.rs#L3104-L3131)).
- LLM 추출 분기는 미구현입니다.

**3. 갱신과 버전**
- `update_frame`은 새 frame을 쓰고 이전 frame을 `Superseded`로 처리합니다.
- MemoryCard는 `entity:slot` 키 기준 시간 비교로 `supersedes`를 결정적으로 판정합니다 ([memory_card.rs#L248-L275](https://github.com/memvid/memvid/blob/e6bd9f7b9c38cd8d5370fa0fc936ac1dcd751813/src/types/memory_card.rs#L248-L275)).

**4. 검색**: Tantivy BM25 + HNSW를 RRF로 합치고, 답은 상위 snippet을 이어 붙이는 추출식입니다. MCP는 없습니다.

**5. 저장소**: 단일 `.mv2` 파일입니다. 서버와 Docker가 필요 없습니다.

**6. 로컬과 클라우드**: 로컬 ONNX 임베딩을 씁니다. 클라우드 연결은 서명된 용량 티켓뿐입니다.

**7. 삭제와 프라이버시**
- WAL tombstone + `vacuum`입니다. 지운 바이트가 물리적으로 사라지는지는 보장되지 않습니다 [추론].
- PII 마스킹은 질의 시점에만 적용됩니다.

**8. 설치**: `cargo add memvid-core`, npm, pip.

---

## 범주 요약 표

| 프로젝트 | 기억 판단 주체 | 저장소/Docker | 검색 | 로컬 vs 클라우드 핵심 차이 | 설치 |
|---|---|---|---|---|---|
| mem0 OSS | 서버 LLM ADD-only 1회 추출(`infer=False`면 원문). UPDATE/DELETE 없음 | 임베디드 Qdrant + SQLite / 없음(server는 Docker) | 의미 + BM25 + 엔티티 가산, 선택적 rerank | 로컬도 OpenAI·PostHog 기본. 대체·시간·`latest_only`는 플랫폼 전용. 코딩 플러그인은 API 키 필수 | pip/npm, 플러그인 마켓 |
| LangMem | 에이전트 도구 또는 백그라운드 LLM(trustcall patch/remove) | LangGraph BaseStore / 선택 | `store.asearch` | Local executor vs LangGraph Platform | pip |
| A-mem | 원문 전부 저장 + LLM evolution(링크·태그) | 인메모리 Chroma(영속 없음) / 없음 | 벡터 + 1-hop | 클라우드 없음. OpenAI 기본, Ollama 가능 | clone + pip |
| Graphiti | 서버 LLM 추출 + `resolve_edge`. 코드가 날짜로 무효화 | Neo4j/FalkorDB(서버), Kuzu·falkordblite(임베디드) / 선택 | BM25 + cos + BFS → RRF/MMR/CE | OSS엔 클라우드 코드 없음. 로컬 기본 OpenAI | pip, MCP(Docker) |
| Zep | 클라우드 LLM(비공개) | 클라우드 전용 | `get_context`, `graph.search_*` | 엔진 전체 비공개, `api.getzep.com` | zep-cloud SDK |
| Cognee | 서버 LLM 그래프 추출(키 없으면 GLiNER) | SQLite + LanceDB + Ladybug(임베디드) / 선택 | 20개 SearchType, hybrid completion | `serve()`로 Auth0 → tenant 프록시. 로컬 기본 OpenAI | uv pip, cognee-mcp |
| Letta V1 | 에이전트 self-edit 도구 + sleeptime | SQLite+sqlite-vec 또는 PG+pgvector / 선택 | core 상시 주입, archival 벡터 | cloud memfs·Turbopuffer는 hosted | Docker |
| letta-code | 에이전트가 MemFS 편집·commit + reflection | git 파일 / 없음 | system prompt + `Memory` 도구 | `api.letta.com`이 원본 remote, 로컬은 remote 없음 | npm |
| MIRIX | meta-agent + 종류별 LLM 에이전트 | PG/PGlite/SQLite / Quick Start는 Docker | PG FTS(BM25형) 기본 | API 키 + org 헤더. KV 비밀값 평문 | compose + pip |
| MemoryOS | 서버 LLM(heat 임계치 → profile 교체) | JSON + FAISS / 선택 | 벡터만 | OpenAI 기본, Platform 초대제 | pip, stdio MCP |
| Hindsight | 서버 LLM 추출 + observation 통합 | PG + pgvector, **pg0 내장 PG** / 불필요 | 4갈래 → RRF → CE → recency | 같은 API에 base_url·키만 다름. LLM은 OpenAI 기본, 임베딩·rerank는 로컬 | uvx, Claude 플러그인 |
| Memobase | 서버 LLM 슬롯 APPEND/UPDATE/ABORT | PG + Redis / 필수 | 슬롯 필터 + event cosine → context 문자열 | `api.memobase.dev`, 셀프호스트는 단일 토큰(미설정 시 무인증) | compose + pip |
| memU | **호스트 에이전트**(스케줄된 `claude -p`), 서버 LLM 없음 | SQLite / 불필요 | cosine만, 에이전트가 직접 retrieve | cloud 모드는 같은 3개 연산. 로컬도 OpenAI 임베딩·텔레메트리 | memu-cli |
| MemOS | 서버 LLM mem_reader + relation detect/resolve(archive 또는 delete) / 로컬 플러그인은 턴 자동 캡처 + LLM 귀납 | 서버: Neo4j(+Qdrant)/PG, Docker 사실상 필수 / 플러그인: SQLite, 불필요 | 서버 graph + vec + BM25 + fulltext / 플러그인 FTS5 + vec RRF + MMR | 셀프호스트 예시는 DashScope Qwen. 클라우드 `memos.memtensor.cn`·`api.memt.ai`. 플러그인 임베딩 로컬, telemetry on | compose, npm 플러그인 |
| Memori | **Memori 클라우드 LLM**(BYODB도 `sdk/augmentation` 호출) | BYODB 8종(SQLite 가능) / 없음 | 로컬 cosine + lexical, LLM 호출 시 자동 주입 | BYODB도 대화가 memorilabs.ai로 나감. agent recall 등은 클라우드 전용 | pip, hosted MCP |
| Memary | LlamaIndex KG 추출(답변 대상) | Neo4j/FalkorDB / 서버 | KG query + 빈도 엔티티 | OpenAI/Ollama, 정체 | pip |
| Honcho | 서버 LLM deriver + dreamer(삭제) | PG + Redis / 사실상 필수 | RRF + dialectic 에이전트 | 같은 코드, `api.honcho.dev`. 로컬 인증 꺼짐 | honcho-cli + compose |
| Redis AMS | 서버 LLM 전략 추출 + 병합 | Redis Stack / 필수 | semantic/BM25/hybrid | **OSS 동결(V0), 제품은 Iris 관리형** | compose, uvx |
| MemMachine | 프로필은 서버 LLM add/delete, 에피소드는 원문 | PG + Neo4j + Qdrant / 사실상 필수 | 벡터 + 맥락 확장 + RRF | OSS 서버 인증 없음, `api.memmachine.ai` | compose, pip |
| OpenViking | 서버 VLM ReAct upsert/delete | 내장 벡터 + RAGFS / 선택 | dense + sparse + rerank | 임베딩 기본이 volcengine 클라우드 | uv tool |
| EverOS | 서버 LLM(경계 → episode → profile) | Markdown + SQLite + LanceDB / 불필요 | hybrid RRF, agentic | 로컬도 OpenRouter/DeepInfra. 플러그인 기본은 클라우드 | pip |
| ReMe | 서버 LLM agent가 md 편집 + dream | Markdown + jsonl / 선택 | BM25 위주 + 훅 주입 | 클라우드 없음, DashScope 기본 | pip + 플러그인 |
| memvid | 호출 코드(LLM 없음) | 단일 `.mv2` / 불필요 | BM25 + HNSW RRF | 로컬 ONNX, 클라우드는 용량 티켓 | cargo/npm/pip |

## agents-memory와 비교한 시사점 [추론]
- **"호출 에이전트가 기억을 판단하고 서버는 LLM 없이 검증만 한다"는 설계는 소수입니다.**
  - 같은 계열: memU(헤드리스 에이전트가 파일 작성), letta-code(MemFS와 pre-commit 검증), LangMem hot-path 도구.
  - 그러나 원문 byte span 출처 검증이나 revision 검증은 셋 다 없습니다.
- **관계 모델링은 우리가 더 명시적입니다.**
  - 가장 가까운 것: Graphiti(duplicate/contradicted → 시간 무효화), memvid MemoryCard(Sets/Updates/Extends/Retracts + supersedes), Cognee(`contradicts`/`superseded`), MemOS(`MERGED_TO` + archived).
  - 이들 모두 관계를 LLM이나 규칙이 만듭니다. 에이전트가 제출하는 곳은 없습니다.
- **삭제 journal(retract/purge)은 어디에도 없습니다.** mem0 history는 삭제 후에도 원문이 남아 오히려 반례입니다.
- **Docker 의존을 줄이는 선례**
  - Hindsight `pg0`: PG를 유지하면서 내장 프로세스로 띄움.
  - Letta, MIRIX: SQLite/PGlite fallback.
  - MemOS local plugin, EverOS: SQLite나 파일을 원본으로 사용.
- **경쟁 제품의 "로컬"은 자주 데이터 egress를 동반합니다.** 우리 쪽 "서버측 LLM 없음 = egress 없음"은 차별점이 됩니다.
  - Memori BYODB의 augmentation, mem0 플러그인, EverOS 플러그인 기본값, memU 텔레메트리, MemOS 플러그인 telemetry.

## 찾았지만 정독하지 않은 프로젝트
- 메모리 엔진 / 연구 코드
  - mindverse/Second-Me (약 15.7k, 개인 모델 fine-tuning 중심)
  - zjunlp/LightMem (약 1.2k, ICLR'26 연구)
  - caspianmoon/memoripy (약 0.7k)
  - nemori-ai/nemori (약 0.2k)
  - memodb-io/Acontext (약 3.7k, skills-as-memory)
  - RedPlanetHQ/core (약 2k)
  - microsoft/kernel-memory (약 2.2k, RAG 성격)
  - getmetal/motorhead (약 0.9k, 사실상 중단)
  - Papr-ai/memory-opensource (AGPL)
  - RichmondAlake/memorizz, alash3al/stash, mudler/LocalRecall, rush-db/rushdb, Lumen-Labs/brainapi2
  - 연구 코드: MemoryBank-SiliconFriend, LongMem, Memento
- 코딩 에이전트 전용으로 범주 A에 해당하는 것: campfirein/byterover-cli, zilliztech/memsearch, Asymptote-Labs/agent-beacon, AVIDS2/memorix, yoloshii/ClawMem, harrylettering/CodeMemory, Lyellr88/marm-memory, mindmuxai/brain.md

## 4. 클라우드 우선 서비스 (원문)

# 카테고리 C: 클라우드 우선 AI 메모리 서비스의 오픈소스 코드 조사 (local 대 cloud)

`gh api`로 각 저장소의 HEAD 커밋을 고정하고 소스를 직접 읽었습니다. 아래 링크는 모두 그 SHA에 고정되어 있고, 기준일은 2026-10-15입니다. README나 docs에만 나오는 주장은 **[README/docs만]**, 코드에서 추론한 내용은 **[추론]**으로 표시했습니다. 셸은 worktree 보호 정책 때문에 쓰기와 clone이 막혀서, `gh api` 읽기 전용 접근만 사용했습니다.

## 먼저 볼 결론 (item 6 중심)

1. **Supermemory**: 엔진이 공개되어 있지 않습니다. 공개 저장소에는 MCP 서버(Cloudflare Worker), SDK, 플러그인만 있습니다. self-host 서버는 비공개 코드로 빌드한 바이너리이고, 무료 사용 한도(lite license)가 붙어 있습니다.
2. **Zep**: Cloud 엔진은 비공개입니다. 공개된 것은 Graphiti(엔진 라이브러리)와 지원이 끝난 CE(`legacy/`)입니다. CE 코드에서는 과금과 기능 활성화(enablement)가 mock으로 대체되어 있습니다.
3. **Redis**: 저장소 루트가 이제 managed "Redis Agent Memory"(Redis Cloud) 안내 페이지입니다. 원래 OSS 서버는 `V0/` 폴더로 옮겨졌고, "연구용 산출물이며 지원 대상 배포판이 아니다"라고 명시되어 있습니다.
4. **같은 코드를 클라우드와 self-host가 함께 쓰는 곳**: Honcho, MemMachine, Papr(`PAPR_EDITION` 플래그), Mem0 OSS. 이 경우 self-host와 클라우드의 차이는 주로 인증 기본값과 일부 클라우드 전용 기능 정도입니다.
5. **로컬 모드에서도 데이터가 외부로 나가는 경우가 흔합니다.**
   - Memori는 BYODB(자기 DB 사용) 모드에서도 대화 원문을 `api.memorilabs.ai/sdk/augmentation`으로 보내 메모리를 추출합니다.
   - Mem0, Honcho, Graphiti, Redis V0, MemMachine, Papr는 기본 LLM 공급자가 OpenAI입니다.
   - Mem0 OSS는 기본으로 PostHog 텔레메트리를 켜고, 원격 공지 설정을 GitHub raw에서 받아옵니다.
6. **"기억할지 판단하는 주체"는 거의 모두 서버 측 LLM입니다.** 예외에 가까운 경우는 셋입니다.
   - Letta: 에이전트(또는 메모리 서브에이전트)가 메모리 파일을 직접 편집합니다.
   - ByteRover: 자체 CLI 내장 에이전트가 curate 도구로 정리합니다.
   - Supermemory MCP의 `add_memory`: 호출하는 에이전트가 내용을 정하지만, 그 뒤 처리는 비공개 서버가 합니다.

---

## 1. Supermemory (`supermemoryai/supermemory` @ `5323f42`)

1. **식별**
   - MIT 라이선스(공개 저장소 한정), ★약 3.1만, 2026-10-14 push, TypeScript.
   - 공개 저장소에는 `apps/mcp`, `apps/web`, `packages/tools`, SDK 래퍼만 있습니다.
2. **쓰기 경로**
   - MCP `add_memory`는 SDK의 `client.add(namespace,{content})`만 호출합니다 ([client/index.ts#L192-L208](https://github.com/supermemoryai/supermemory/blob/5323f427d076c7a158a9154867d293b53acc3841/apps/mcp/src/server/client/index.ts#L192-L208)).
   - 무엇을 저장할지는 호출하는 에이전트가 정합니다. 이후의 추출과 그래프화는 비공개 서버에서 일어납니다.
   - Claude Code 플러그인은 `Stop` 훅에서 대화를 자동 캡처해 `/v3/documents`로 올리고, `SessionStart`·`UserPromptSubmit` 훅에서 `/v4/profile`로 recall합니다 ([hooks.json](https://github.com/supermemoryai/claude-supermemory/blob/8e98cb48b5574bc68375754735ba05cad1545b17/plugin/hooks/hooks.json), [api.js#L51-L62](https://github.com/supermemoryai/claude-supermemory/blob/8e98cb48b5574bc68375754735ba05cad1545b17/plugin/hooks/lib/api.js#L51-L62)).
3. **갱신/통합**: 서버 코드가 비공개라 확인할 수 없습니다. docs는 "graph engine"이라고만 설명합니다 [README/docs만].
4. **검색**: MCP가 `searchMode:"hybrid"`로 검색합니다 ([#L250-L257](https://github.com/supermemoryai/supermemory/blob/5323f427d076c7a158a9154867d293b53acc3841/apps/mcp/src/server/client/index.ts#L250-L257)). 실제 랭킹 방식은 비공개입니다.
5. **저장소**
   - Cloud: 비공개입니다.
   - Local 바이너리: 그래프 엔진이 내장되어 있고 DB를 따로 띄울 필요가 없습니다. 기본 임베딩은 로컬 `Xenova/bge-base-en-v1.5`입니다 ([overview.mdx#L20-L27](https://github.com/supermemoryai/supermemory/blob/5323f427d076c7a158a9154867d293b53acc3841/apps/docs/self-hosting/overview.mdx#L20-L27)) [docs만].
   - Docker 이미지도 선택적으로 제공합니다 ([docker.mdx](https://github.com/supermemoryai/supermemory/blob/5323f427d076c7a158a9154867d293b53acc3841/apps/docs/self-hosting/docker.mdx)).
6. **LOCAL vs CLOUD**
   - "서버 소스는 공개 저장소에 없다"고 docs에 명시되어 있습니다 ([local-vs-enterprise.mdx#L8](https://github.com/supermemoryai/supermemory/blob/5323f427d076c7a158a9154867d293b53acc3841/apps/docs/self-hosting/local-vs-enterprise.mdx#L8), [overview.mdx#L20,L65](https://github.com/supermemoryai/supermemory/blob/5323f427d076c7a158a9154867d293b53acc3841/apps/docs/self-hosting/overview.mdx#L65)). 릴리스 자산도 플랫폼별 `supermemory-server-*` 바이너리뿐입니다.
   - Local은 API 키 1개, 단일 조직이고 LLM 키는 사용자가 직접 넣습니다(BYO). URL 수집에는 호스팅된 reader 서비스를 씁니다. 텔레메트리는 켜져 있고 `SUPERMEMORY_DISABLE_TELEMETRY=1`로 끕니다 ([overview.mdx#L44](https://github.com/supermemoryai/supermemory/blob/5323f427d076c7a158a9154867d293b53acc3841/apps/docs/self-hosting/overview.mdx#L44)).
   - Enterprise 전용 기능: 자체 모델, 조직/역할, 커넥터(Drive, Notion, Gmail), 대시보드 ([local-vs-enterprise.mdx#L17-L22](https://github.com/supermemoryai/supermemory/blob/5323f427d076c7a158a9154867d293b53acc3841/apps/docs/self-hosting/local-vs-enterprise.mdx#L17)).
   - MCP 서버의 기본 연결 대상은 `https://api.supermemory.ai`와 `mcp.supermemory.ai`입니다 ([server/index.ts#L21-L22](https://github.com/supermemoryai/supermemory/blob/5323f427d076c7a158a9154867d293b53acc3841/apps/mcp/src/server/index.ts#L21-L22)).
   - MCP 인증은 `/v3/session` 원격 조회 또는 JWKS 기반 JWT 검증이고, 네임스페이스별 read/write RBAC가 있습니다 ([auth/index.ts#L30-L58](https://github.com/supermemoryai/supermemory/blob/5323f427d076c7a158a9154867d293b53acc3841/apps/mcp/src/server/auth/index.ts#L30-L58), [rbac.ts](https://github.com/supermemoryai/supermemory/blob/5323f427d076c7a158a9154867d293b53acc3841/apps/mcp/src/server/auth/rbac.ts)).
7. **삭제/프라이버시**
   - `forgetMemory`는 정확한 내용 일치로 지우지 못합니다. `forgetMatching(dryRun)`으로 의미상 가장 가까운 1건을 찾은 뒤 ID로 forget합니다 ([#L210-L248](https://github.com/supermemoryai/supermemory/blob/5323f427d076c7a158a9154867d293b53acc3841/apps/mcp/src/server/client/index.ts#L210-L248)). 엉뚱한 항목이 지워질 수 있습니다 [추론].
   - Claude 플러그인은 업로드 전에 `redactSecrets`로 비밀값을 가립니다 ([redact.js#L7](https://github.com/supermemoryai/claude-supermemory/blob/8e98cb48b5574bc68375754735ba05cad1545b17/plugin/hooks/lib/redact.js#L7)).
8. **설치**
   - 호스팅 MCP URL에 OAuth로 연결하거나, Claude 플러그인 마켓플레이스로 설치합니다.
   - 플러그인 기본 URL은 `api.supermemory.ai`이고 `SUPERMEMORY_API_URL`로 바꿀 수 있습니다 ([settings.js#L7,L81-L82](https://github.com/supermemoryai/claude-supermemory/blob/8e98cb48b5574bc68375754735ba05cad1545b17/plugin/hooks/lib/settings.js#L81-L82)).
   - local은 install.sh 바이너리나 Docker로 설치합니다.

## 2. Honcho (`plastic-labs/honcho` @ `ed17042`)

1. **식별**: AGPL-3.0, ★약 7.6천, 2026-10-14 push, Python (FastAPI 서버, SDK, MCP, CLI, 플러그인 포함).
2. **쓰기 경로**
   - 앱이 메시지를 저장합니다(SDK 또는 MCP `add_messages_to_session`). claude-honcho 플러그인은 `UserPromptSubmit`, `PostToolUse`, `PreCompact` 등의 훅에서 자동 저장합니다 ([hooks.json](https://github.com/plastic-labs/claude-honcho/blob/42797db4ede66c2db9e04fc9d14c27c4fdc61b6e/plugins/honcho/hooks/hooks.json)).
   - 무엇을 기억할지는 **백그라운드 deriver의 서버측 LLM**이 정합니다. 프롬프트는 `minimal_deriver_prompt`의 "Extract **explicit atomic facts**"입니다 ([deriver/prompts.py#L46-L100](https://github.com/plastic-labs/honcho/blob/ed1704265e609364da6bf291bb3369bc9654f8dc/src/deriver/prompts.py#L46-L100)).
   - 호출 흐름은 `honcho_llm_call` → `save_representation`입니다 ([deriver.py#L187,L267](https://github.com/plastic-labs/honcho/blob/ed1704265e609364da6bf291bb3369bc9654f8dc/src/deriver/deriver.py#L187)).
3. **갱신/통합**
   - `DERIVER_DEDUPLICATE=True` ([config.py#L937](https://github.com/plastic-labs/honcho/blob/ed1704265e609364da6bf291bb3369bc9654f8dc/src/config.py#L937)).
   - dreamer가 deduction/induction 전문 에이전트로 도구를 호출해 관찰을 생성·삭제하고, 중복 삭제는 deduction만 합니다 ([dreamer/specialists.py#L6-L8](https://github.com/plastic-labs/honcho/blob/ed1704265e609364da6bf291bb3369bc9654f8dc/src/dreamer/specialists.py#L6-L8)).
4. **검색**
   - pgvector 등 벡터 검색을 씁니다.
   - `DialecticAgent`가 도구를 호출해 필요한 컨텍스트를 모아 자연어로 답합니다 ([dialectic/core.py#L62](https://github.com/plastic-labs/honcho/blob/ed1704265e609364da6bf291bb3369bc9654f8dc/src/dialectic/core.py#L62)).
   - MCP 도구로 `chat`, `get_peer_context`, `query_conclusions`를 제공합니다.
5. **저장소**
   - PostgreSQL이 필수입니다 ([config.py#L723-L725](https://github.com/plastic-labs/honcho/blob/ed1704265e609364da6bf291bb3369bc9654f8dc/src/config.py#L723-L725)).
   - 벡터 저장소는 pgvector, turbopuffer, lancedb, qdrant, chromadb 중 고를 수 있습니다 ([#L1469-L1499](https://github.com/plastic-labs/honcho/blob/ed1704265e609364da6bf291bb3369bc9654f8dc/src/config.py#L1469-L1499)).
   - compose 예시는 pgvector, Redis, api, deriver로 구성됩니다 ([docker-compose.yml.example](https://github.com/plastic-labs/honcho/blob/ed1704265e609364da6bf291bb3369bc9654f8dc/docker-compose.yml.example)). Docker 없이 로컬 PG로도 가능하다고 README에 적혀 있습니다.
6. **LOCAL vs CLOUD**: 같은 서버 코드를 씁니다.
   - **`AUTH_USE_AUTH=False`가 기본값**이고, 이때 모든 요청이 admin 권한을 받습니다 ([security.py#L272-L273](https://github.com/plastic-labs/honcho/blob/ed1704265e609364da6bf291bb3369bc9654f8dc/src/security.py#L272-L273), [config.py#L756-L757](https://github.com/plastic-labs/honcho/blob/ed1704265e609364da6bf291bb3369bc9654f8dc/src/config.py#L756)).
   - 클라우드 방식은 HS256 JWT로 workspace/peer/session/named-scope 단위 권한을 줍니다 ([security.py JWTParams](https://github.com/plastic-labs/honcho/blob/ed1704265e609364da6bf291bb3369bc9654f8dc/src/security.py#L33-L70)).
   - 기본 LLM은 transport `openai`, 모델 `gpt-5.4-mini`입니다 ([#L929-L931](https://github.com/plastic-labs/honcho/blob/ed1704265e609364da6bf291bb3369bc9654f8dc/src/config.py#L929-L931)). 임베딩도 openai 기본입니다. 즉 self-host도 기본은 OpenAI 호출입니다.
   - `honcho start`(CLI)도 LLM 공급자 키와 Docker를 요구합니다 ([local/setup.py#L23-L38](https://github.com/plastic-labs/honcho/blob/ed1704265e609364da6bf291bb3369bc9654f8dc/honcho-cli/src/honcho_cli/local/setup.py#L23)).
   - **SDK 기본 연결 대상이 production(`api.honcho.dev`)**입니다 ([sdks/python/.../client.py#L49-L52,L288](https://github.com/plastic-labs/honcho/blob/ed1704265e609364da6bf291bb3369bc9654f8dc/sdks/python/src/honcho/client.py#L288)). MCP도 같습니다 ([mcp/src/config.ts#L91](https://github.com/plastic-labs/honcho/blob/ed1704265e609364da6bf291bb3369bc9654f8dc/mcp/src/config.ts#L91)).
   - MCP는 Cloudflare Worker로 배포됩니다 ([wrangler.toml](https://github.com/plastic-labs/honcho/blob/ed1704265e609364da6bf291bb3369bc9654f8dc/mcp/wrangler.toml)).
   - CloudEvents 텔레메트리는 기본 꺼짐입니다 ([#L1270](https://github.com/plastic-labs/honcho/blob/ed1704265e609364da6bf291bb3369bc9654f8dc/src/config.py#L1270)).
   - 코드 차원에서 클라우드 전용으로 막힌 기능은 찾지 못했습니다.
7. **삭제**: conclusion, session, workspace DELETE 라우트가 있습니다 ([conclusions.py#L166](https://github.com/plastic-labs/honcho/blob/ed1704265e609364da6bf291bb3369bc9654f8dc/src/routers/conclusions.py#L166), [workspaces.py#L122](https://github.com/plastic-labs/honcho/blob/ed1704265e609364da6bf291bb3369bc9654f8dc/src/routers/workspaces.py#L122)). 비밀값 마스킹 전용 로직은 확인하지 못했습니다.
8. **설치**: 관리형 `api.honcho.dev`, `honcho start`(Docker), 소스+compose, Claude/Hermes/Kilo 플러그인.

## 3. Zep / Graphiti (`getzep/zep` @ `3997767`, `getzep/graphiti` @ `aca3693`, `getzep/zep-python` @ `ec41ccd`)

1. **식별**
   - zep: Apache-2.0, ★약 5천. 현재는 예제, 통합 코드, 벤치마크, `mcp/`, `ingestion/`, `legacy/`만 담고 있습니다.
   - graphiti: Apache-2.0, ★약 3.2만, Python.
2. **쓰기 경로**
   - Graphiti `add_episode`([graphiti.py#L1332](https://github.com/getzep/graphiti/blob/aca369364226a666ca541b061ff2a1a54b80f2ff/graphiti_core/graphiti.py#L1332)) → `extract_edges` 등 LLM 추출 순서로 진행합니다.
   - 판단은 **서버측 LLM**이 합니다. 프롬프트는 [prompts/](https://github.com/getzep/graphiti/tree/aca369364226a666ca541b061ff2a1a54b80f2ff/graphiti_core/prompts)에 있습니다.
3. **갱신/통합**
   - `resolve_extracted_edges` → `_dedupe_extracted_edge` → `_apply_temporal_invalidation` / `resolve_edge_contradictions` 순서입니다 ([edge_operations.py#L424,L715,L748](https://github.com/getzep/graphiti/blob/aca369364226a666ca541b061ff2a1a54b80f2ff/graphiti_core/utils/maintenance/edge_operations.py#L715)).
   - LLM이 `contradicted_facts`를 돌려주면 해당 사실을 valid/invalid 시간축으로 무효화합니다 ([dedupe_edges.py#L30-L63](https://github.com/getzep/graphiti/blob/aca369364226a666ca541b061ff2a1a54b80f2ff/graphiti_core/prompts/dedupe_edges.py#L30)).
4. **검색**: cosine, BM25, BFS를 쓰고 RRF, MMR, cross-encoder, node_distance, episode_mentions로 재정렬합니다 ([search_config.py#L32-L75](https://github.com/getzep/graphiti/blob/aca369364226a666ca541b061ff2a1a54b80f2ff/graphiti_core/search/search_config.py#L32)).
5. **저장소**
   - Neo4j, FalkorDB, Kuzu(임베디드), Neptune 드라이버가 있습니다 ([driver/](https://github.com/getzep/graphiti/tree/aca369364226a666ca541b061ff2a1a54b80f2ff/graphiti_core/driver)).
   - MCP 기본은 falkordb, LLM 기본은 openai입니다 ([mcp_server/src/config/schema.py#L149-L150,L213](https://github.com/getzep/graphiti/blob/aca369364226a666ca541b061ff2a1a54b80f2ff/mcp_server/src/config/schema.py#L213)).
6. **LOCAL vs CLOUD**
   - **Zep Cloud 엔진은 비공개입니다.** CE는 "Deprecated, unsupported"로 `legacy/`에 옮겨졌습니다 ([README#L45,L66-L70](https://github.com/getzep/zep/blob/3997767fccf83bbea7b54ad5f73554f2e5bcd54e/README.md#L66)).
   - CE 코드의 `*_ce.go` 빌드 변형을 보면 클라우드와 코드를 공유하던 흔적이 있습니다.
     - `enablement.I()`는 `NewMockService()`를, `BillingPlan.IsFree()`는 항상 true를 반환합니다 ([enablement_ce.go](https://github.com/getzep/zep/blob/3997767fccf83bbea7b54ad5f73554f2e5bcd54e/legacy/src/lib/enablement/enablement_ce.go), [plan_ce.go](https://github.com/getzep/zep/blob/3997767fccf83bbea7b54ad5f73554f2e5bcd54e/legacy/src/lib/enablement/plan_ce.go)).
     - 인증은 단일 공유 `api_secret` 비교뿐입니다 ([secret_key_auth_ce.go#L29](https://github.com/getzep/zep/blob/3997767fccf83bbea7b54ad5f73554f2e5bcd54e/legacy/src/api/middleware/secret_key_auth_ce.go#L29)).
     - 메모리 처리는 Graphiti 서비스에 HTTP로 위임합니다 ([service_ce.go](https://github.com/getzep/zep/blob/3997767fccf83bbea7b54ad5f73554f2e5bcd54e/legacy/src/lib/graphiti/service_ce.go)).
     - compose는 zep, pgvector, graphiti, neo4j에 `OPENAI_API_KEY`가 필요합니다 ([docker-compose.ce.yaml](https://github.com/getzep/zep/blob/3997767fccf83bbea7b54ad5f73554f2e5bcd54e/legacy/docker-compose.ce.yaml)).
     - CE 텔레메트리는 기본 켜짐입니다 ([zep.yaml](https://github.com/getzep/zep/blob/3997767fccf83bbea7b54ad5f73554f2e5bcd54e/legacy/zep.yaml)).
   - Cloud SDK 기본 URL은 `https://api.getzep.com/api/v2`입니다 ([environment.py#L7](https://github.com/getzep/zep-python/blob/ec41ccdde6fe92dc0de378c7bfb0c2483af324ce/src/zep_cloud/environment.py#L7)).
   - **Zep MCP 서버(Go)는 `ZEP_API_KEY`가 필수이고 조회 도구만 13개 있습니다** (search_graph, get_user_context 등; [config.go#L27-L29](https://github.com/getzep/zep/blob/3997767fccf83bbea7b54ad5f73554f2e5bcd54e/mcp/zep-mcp-server/internal/config/config.go#L27), [tools.go#L9-L69](https://github.com/getzep/zep/blob/3997767fccf83bbea7b54ad5f73554f2e5bcd54e/mcp/zep-mcp-server/internal/server/tools.go#L9)). 쓰기는 SDK나 통합 코드로 합니다.
7. **삭제**: Graphiti MCP에 `delete_entity_edge`, `delete_episode`, `clear_graph`가 있습니다 ([graphiti_mcp_server.py#L695,L729,L1102](https://github.com/getzep/graphiti/blob/aca369364226a666ca541b061ff2a1a54b80f2ff/mcp_server/src/graphiti_mcp_server.py#L695)). CE `deleteMemory`는 `graphiti.DeleteGroup`입니다.
8. **설치**: `pip install zep-cloud` 또는 graphiti-core, Graphiti MCP는 Docker.

## 4. Mem0 (`mem0ai/mem0` @ `0724291`)

1. **식별**
   - Apache-2.0, ★약 6.7만, 2026-10-14 push.
   - **HEAD 트리에 `openmemory/` 디렉터리가 없습니다.** 대신 `server/`(FastAPI, 인증, 대시보드)와 다수의 에이전트 플러그인이 있습니다.
   - 독립 MCP 저장소 `mem0ai/mem0-mcp`는 archived 상태입니다.
2. **쓰기 경로**
   - `Memory.add(infer=True)` → `_add_to_vector_store` 순서입니다 ([main.py#L760,L881](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/mem0/memory/main.py#L881)).
   - **서버측 LLM**이 `ADDITIVE_EXTRACTION_PROMPT`로 단일 호출 추출을 합니다 ([#L944-L964](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/mem0/memory/main.py#L944)).
   - Claude Code 플러그인은 SessionStart, UserPromptSubmit, PostToolUse 등의 훅에서 **Platform(`api.mem0.ai`)**으로 전송합니다 ([memory_core.py#L31,L383](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/integrations/claude-code-plugin/core/memory_core.py#L31)).
3. **갱신/통합**
   - **현재 OSS의 add는 추가만 합니다.** 이전의 LLM ADD/UPDATE/DELETE 판정은 add 경로에 없고, md5 해시로 중복만 거릅니다 ([#L1022-L1025](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/mem0/memory/main.py#L1022)).
   - `_update_memory`/`_delete_memory`는 명시적 API용입니다 ([#L2052,L2114](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/mem0/memory/main.py#L2052)). 히스토리는 SQLite `history.db`에 남습니다.
4. **검색**: `score_and_rank`가 (semantic + BM25(lemmatize) + entity boost)를 정규화해 결합합니다 ([scoring.py#L60-L72](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/mem0/utils/scoring.py#L60)). rerank는 선택입니다.
5. **저장소**
   - 기본 벡터 저장소는 qdrant인데, `path="/tmp/qdrant"`의 임베디드 방식이고 `on_disk=False`입니다 ([vector_stores/configs.py#L9](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/mem0/vector_stores/configs.py#L9), [qdrant.py#L16-L23](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/mem0/configs/vector_stores/qdrant.py#L16)).
   - `server/` 기본 구성은 pgvector + OpenAI입니다 ([server/main.py#L120-L137](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/server/main.py#L120)).
6. **LOCAL vs CLOUD**
   - `MemoryClient`는 `https://api.mem0.ai`를 씁니다 ([client/main.py#L262](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/mem0/client/main.py#L262)).
   - Platform 전용 API: export, profile, project update, webhook, feedback ([#L769,L831,L1039,L1143,L1233](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/mem0/client/main.py#L769)).
   - **OSS에서는 temporal 파라미터(`timestamp`, `reference_date`)와 `decay`를 주면 예외가 납니다** ([main.py#L817-L818,L1446-L1447,L469-L471](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/mem0/memory/main.py#L817)).
   - OSS 기본 LLM과 임베딩은 openai입니다 ([llms/configs.py#L7](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/mem0/llms/configs.py#L7)).
   - PostHog 텔레메트리가 기본 켜짐입니다 (`MEM0_TELEMETRY="True"`, [telemetry.py#L14-L16](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/mem0/memory/telemetry.py#L14)).
   - 원격 공지 설정을 GitHub raw에서 받습니다 ([notices.py#L23,L62-L66](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/mem0/memory/notices.py#L62)). 업셀 문구는 현재 모두 꺼져 있습니다.
   - self-host `server/` 인증은 JWT, bcrypt API 키, `ADMIN_API_KEY` 중 하나입니다. `AUTH_DISABLED`는 경고만 내고 켤 수 있습니다 ([server/auth.py#L15-L44](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/server/auth.py#L15), [main.py#L90-L97](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/server/main.py#L90)).
7. **삭제**: `delete`, `delete_all`(배치 1000), `reset`, `history`가 있습니다 ([#L1883-L1960](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/mem0/memory/main.py#L1883)).
8. **설치**: `pip install mem0ai`, Platform API 키, `server/` docker-compose, 에이전트별 plugin 마켓플레이스.

## 5. Redis Agent Memory (`redis/agent-memory-server` @ `94192c3`)

1. **식별**
   - 라이선스 파일은 Apache-2.0 본문인데 GitHub API는 NOASSERTION으로 표시합니다. ★약 320, 2026-09-18 push.
   - **README 맨 위가 managed 제품(Redis Cloud "Agent Memory", Iris) 안내**이고, OSS 서버는 `V0/`에 "open research artifact, not the supported production distribution"으로 남아 있습니다 ([README#L45-L47](https://github.com/redis/agent-memory-server/blob/94192c39e2a4a154f441a5411e3d73c4f54974a6/README.md#L45)).
2. **쓰기 경로**
   - working memory에 메시지를 넣으면 백그라운드에서 `promote_working_memory_to_long_term` → `extract_memories_from_session_thread`가 돕니다 ([long_term_memory.py#L657,L1912](https://github.com/redis/agent-memory-server/blob/94192c39e2a4a154f441a5411e3d73c4f54974a6/V0/agent_memory_server/long_term_memory.py#L1912)).
   - 추출 전략은 Discrete, Summary, UserPreferences, Custom이고 모두 LLM 기반입니다 ([memory_strategies.py#L68-L378](https://github.com/redis/agent-memory-server/blob/94192c39e2a4a154f441a5411e3d73c4f54974a6/V0/agent_memory_server/memory_strategies.py#L68)).
   - MCP `create_long_term_memories`로 에이전트가 직접 저장할 수도 있습니다.
3. **갱신/통합**: `deduplicate_by_hash`/`by_id`/`by_semantic_search` + `merge_memories_with_llm` + `compact_long_term_memories` ([#L794,L905,L1556-L1786](https://github.com/redis/agent-memory-server/blob/94192c39e2a4a154f441a5411e3d73c4f54974a6/V0/agent_memory_server/long_term_memory.py#L1786)).
4. **검색**: semantic, keyword, hybrid(`hybrid_alpha=0.7`)에 recency rerank를 더합니다 ([#L1353-L1386](https://github.com/redis/agent-memory-server/blob/94192c39e2a4a154f441a5411e3d73c4f54974a6/V0/agent_memory_server/long_term_memory.py#L1353)). MCP에 `memory_prompt` 컨텍스트 주입 도구가 있습니다.
5. **저장소**: Redis(검색 모듈) 필수, Docker 권장입니다.
6. **LOCAL vs CLOUD**
   - V0 기본값: `disable_auth=True`, `auth_mode="disabled"`, `generation_model="gpt-5"`, `text-embedding-3-small` ([config.py#L337-L344,L422-L432](https://github.com/redis/agent-memory-server/blob/94192c39e2a4a154f441a5411e3d73c4f54974a6/V0/agent_memory_server/config.py#L422)).
   - token 모드는 bcrypt 해시를 쓰고, OAuth2는 JWKS로 검증합니다 ([auth.py#L266-L274](https://github.com/redis/agent-memory-server/blob/94192c39e2a4a154f441a5411e3d73c4f54974a6/V0/agent_memory_server/auth.py#L266)).
   - 클라우드 API 형태는 벤치마크 어댑터로만 볼 수 있습니다: `REDIS_AGENT_MEMORY_URL`/`STORE_ID`/`API_KEY`, `/v1/stores/{id}` ([redis_agent_memory_store.py#L46-L75](https://github.com/redis/agent-memory-server/blob/94192c39e2a4a154f441a5411e3d73c4f54974a6/agent-memory-benchmark/src/agent_memory_benchmark/memory/redis_agent_memory_store.py#L46)). Cloud 엔진 코드는 비공개입니다.
7. **삭제/프라이버시**
   - `delete_long_term_memories`가 있습니다.
   - `forget_long_term_memories` 정책(나이·비활성·top-N)은 기본 꺼짐입니다 ([config.py#L485-L490](https://github.com/redis/agent-memory-server/blob/94192c39e2a4a154f441a5411e3d73c4f54974a6/V0/agent_memory_server/config.py#L485)).
   - 프롬프트 인젝션 방어 모듈이 있습니다 ([prompt_security.py](https://github.com/redis/agent-memory-server/blob/94192c39e2a4a154f441a5411e3d73c4f54974a6/V0/agent_memory_server/prompt_security.py)).
8. **설치**: Redis Cloud 콘솔에서 서비스 생성, V0는 Docker/uv.

## 6. MemMachine (`MemMachine/MemMachine` @ `d5a39a8`)

1. **식별**: Apache-2.0, ★약 3천, 2026-10-15 push, Python 서버 + Python/TS 클라이언트.
2. **쓰기 경로**: MCP와 REST의 `add_memory`로 들어옵니다 ([mcp.py#L414](https://github.com/MemMachine/MemMachine/blob/d5a39a8e774e977fb1e6c22efb03555c4e51e05e/packages/server/src/memmachine_server/server/api_v2/mcp.py#L414)). episodic은 원문을 저장하고, semantic은 **서버측 LLM**이 명령을 만듭니다.
3. **갱신/통합**
   - `llm_feature_update`가 `SemanticCommandType` **ADD/DELETE**를 생성하고, `llm_consolidate_features`가 병합합니다 ([semantic_model.py#L21-L29](https://github.com/MemMachine/MemMachine/blob/d5a39a8e774e977fb1e6c22efb03555c4e51e05e/packages/server/src/memmachine_server/semantic_memory/semantic_model.py#L21), [semantic_llm.py#L70,L128](https://github.com/MemMachine/MemMachine/blob/d5a39a8e774e977fb1e6c22efb03555c4e51e05e/packages/server/src/memmachine_server/semantic_memory/semantic_llm.py#L70)).
   - 프로필 프롬프트(CRM, coding style 등)는 [server/prompt/](https://github.com/MemMachine/MemMachine/tree/d5a39a8e774e977fb1e6c22efb03555c4e51e05e/packages/server/src/memmachine_server/server/prompt)에 있습니다.
4. **검색**
   - `query_memory`는 short-term(요약)과 long-term을 함께 봅니다 ([episodic_memory.py#L353](https://github.com/MemMachine/MemMachine/blob/d5a39a8e774e977fb1e6c22efb03555c4e51e05e/packages/server/src/memmachine_server/episodic_memory/episodic_memory.py#L353)).
   - reranker는 BM25, cross-encoder, RRF-hybrid, Cohere, Bedrock 중에서 고르고, retrieval agent가 질의 분해를 합니다.
5. **저장소**
   - PG(pgvector), SQLite, Neo4j, Nebula, Qdrant, Milvus, sqlite-vec를 지원합니다 ([database_conf.py#L524-L532](https://github.com/MemMachine/MemMachine/blob/d5a39a8e774e977fb1e6c22efb03555c4e51e05e/packages/server/src/memmachine_server/common/configuration/database_conf.py#L524)).
   - compose는 postgres, neo4j, qdrant, memmachine입니다 ([docker-compose.yml](https://github.com/MemMachine/MemMachine/blob/d5a39a8e774e977fb1e6c22efb03555c4e51e05e/docker-compose.yml)).
6. **LOCAL vs CLOUD**
   - 서버 코드에서 인증 처리를 찾지 못했습니다. 미들웨어는 접근 로그와 메트릭뿐이고, code search에서도 서버 쪽 `Authorization` 처리가 없었습니다 ([middleware.py](https://github.com/MemMachine/MemMachine/blob/d5a39a8e774e977fb1e6c22efb03555c4e51e05e/packages/server/src/memmachine_server/server/middleware.py)).
   - 클라이언트 `api_key`는 "optional for local development"입니다 ([client.py#L95](https://github.com/MemMachine/MemMachine/blob/d5a39a8e774e977fb1e6c22efb03555c4e51e05e/packages/client/src/memmachine_client/client.py#L95)).
   - 테넌시는 요청에 담긴 `org_id`/`project_id`와 `MM_ORG_ID` 환경변수로 덮어쓰는 방식입니다 ([mcp.py#L158](https://github.com/MemMachine/MemMachine/blob/d5a39a8e774e977fb1e6c22efb03555c4e51e05e/packages/server/src/memmachine_server/server/api_v2/mcp.py#L158)). 클라우드 인증은 공개 저장소 밖의 게이트웨이에 있을 것으로 봅니다 [추론].
   - Cloud는 "MemMachine Platform" 콘솔입니다 [README만].
   - 샘플 설정은 OpenAI 키가 필요합니다 ([configuration.event.yml](https://github.com/MemMachine/MemMachine/blob/d5a39a8e774e977fb1e6c22efb03555c4e51e05e/sample_configs/configuration.event.yml)).
7. **삭제**: `delete_episodes`, `delete_session_episodes`, MCP `delete_memory`.
8. **설치**: `pip install memmachine-client`, docker compose, Helm.

## 7. Papr Memory (`Papr-ai/memory-opensource` @ `a0a816e`)

1. **식별**: AGPL-3.0, ★74, 2026-04-16 push, Python.
2. **쓰기 경로**: REST로 들어온 뒤 `process_memory_item_async`가 **서버측 LLM**을 여러 번 호출합니다: `generate_usecase_memory_item_async`, `generate_related_memories_async`, `generate_memory_graph_schema_async` ([memory_graph.py#L4337,L4381,L4842](https://github.com/Papr-ai/memory-opensource/blob/a0a816eb00f73b0819ef3fd7115bb6835cd18c39/memory/memory_graph.py#L4337)).
3. **갱신/통합**: LLM이 그래프 스키마와 관계를 생성합니다. 명시적인 contradiction 처리 코드는 찾지 못했습니다.
4. **검색**: Qdrant 벡터 검색에 더해 **LLM이 Cypher를 생성**합니다 (`generate_neo4j_cipher_query_async`, [#L8834](https://github.com/Papr-ai/memory-opensource/blob/a0a816eb00f73b0819ef3fd7115bb6835cd18c39/memory/memory_graph.py#L8834)).
5. **저장소**: MongoDB, Redis, Neo4j, Qdrant, Parse Server, Temporal+Postgres. Docker가 사실상 필수입니다 ([docker-compose.yaml](https://github.com/Papr-ai/memory-opensource/blob/a0a816eb00f73b0819ef3fd7115bb6835cd18c39/docker-compose.yaml)).
6. **LOCAL vs CLOUD (코드 레벨 에디션 플래그)**
   - `PAPR_EDITION=opensource|cloud`이고, OSS 저장소에는 `cloud.yaml`이 없어 opensource로 대체됩니다 ([features.py#L62-L72](https://github.com/Papr-ai/memory-opensource/blob/a0a816eb00f73b0819ef3fd7115bb6835cd18c39/config/features.py#L62)).
   - OSS에서 꺼진 기능: stripe, subscriptions, usage_metering, auth0, amplitude, azure_service_bus, sendgrid, rate_limiting ([opensource.yaml](https://github.com/Papr-ai/memory-opensource/blob/a0a816eb00f73b0819ef3fd7115bb6835cd18c39/config/opensource.yaml)).
   - 배치 한도를 넘으면 "use Papr Cloud" 문구가 나옵니다.
   - `remove_cloud_dirs.sh`로 클라우드 디렉터리를 지우고 공개한 흔적이 있습니다 ([scripts/remove_cloud_dirs.sh](https://github.com/Papr-ai/memory-opensource/blob/a0a816eb00f73b0819ef3fd7115bb6835cd18c39/scripts/remove_cloud_dirs.sh)). 그런데 `cloud_plugins/temporal`은 남아 있습니다.
   - `OPENAI_API_KEY`가 필수이고(gpt-5-nano), 임베딩은 로컬 Qwen3-Embedding-0.6B가 기본입니다 ([.env.example#L66-L72,L180-L190](https://github.com/Papr-ai/memory-opensource/blob/a0a816eb00f73b0819ef3fd7115bb6835cd18c39/.env.example#L66)).
   - PostHog 텔레메트리가 기본 켜짐입니다.
7. **삭제**: `delete_memory_item_parse` ([memory_management.py#L1630](https://github.com/Papr-ai/memory-opensource/blob/a0a816eb00f73b0819ef3fd7115bb6835cd18c39/services/memory_management.py#L1630)). ACL 모델이 있습니다.
8. **설치**: docker compose. 호스팅 API는 별도입니다.

## 8. ByteRover (`campfirein/byterover-cli` @ `1052ac1`)

1. **식별**
   - **Elastic-2.0**(source-available, OSI 오픈소스 아님, [package.json#L158](https://github.com/campfirein/byterover-cli/blob/1052ac1a5dd0fde4da8693d4712064f7876c269c/package.json#L158)), ★약 5천.
   - **2026-06-25에 archived** 되었습니다. 이전 이름은 Cipher입니다.
2. **쓰기 경로**
   - MCP `brv-curate`/`brv-query`를 제공합니다 ([brv-curate-tool.ts#L176](https://github.com/campfirein/byterover-cli/blob/1052ac1a5dd0fde4da8693d4712064f7876c269c/src/server/infra/mcp/tools/brv-curate-tool.ts#L176)).
   - 판단은 **brv 내장 에이전트 LLM**이 합니다. `curate` 도구가 `<bv-topic>` HTML 형식으로 토픽 파일을 씁니다 ([curate.txt](https://github.com/campfirein/byterover-cli/blob/1052ac1a5dd0fde4da8693d4712064f7876c269c/src/agent/resources/tools/curate.txt)).
   - review 기능으로 사람이 승인/거절할 수 있습니다 [README].
3. **갱신/통합**: context tree에 git 비슷한 vc(branch/merge)와 dream 기능이 있습니다 ([oclif/commands/vc](https://github.com/campfirein/byterover-cli/tree/1052ac1a5dd0fde4da8693d4712064f7876c269c/src/oclif/commands/vc)).
4. **검색**: 로컬 minisearch(BM25류, [package.json#L78](https://github.com/campfirein/byterover-cli/blob/1052ac1a5dd0fde4da8693d4712064f7876c269c/package.json#L78)).
5. **저장소**: 프로젝트 안의 파일(context tree)입니다. DB와 Docker가 필요 없습니다.
6. **LOCAL vs CLOUD**
   - 클라우드는 OIDC 로그인(IAM), cogit push/pull, billing, team/space입니다. `BRV_IAM_BASE_URL`, `BRV_COGIT_BASE_URL`, `BRV_BILLING_BASE_URL`, `BRV_LLM_BASE_URL`이 필수 환경변수입니다 ([environment.ts#L79-L104](https://github.com/campfirein/byterover-cli/blob/1052ac1a5dd0fde4da8693d4712064f7876c269c/src/server/config/environment.ts#L79)).
   - 내장 `byterover` LLM 공급자는 ByteRover 백엔드를 경유하고 로그인을 요구합니다 ([provider-config-resolver.ts#L117-L120](https://github.com/campfirein/byterover-cli/blob/1052ac1a5dd0fde4da8693d4712064f7876c269c/src/server/infra/provider/provider-config-resolver.ts#L117)). 코드 주석에 "Will be removed"라고 되어 있습니다 ([byterover.ts#L6](https://github.com/campfirein/byterover-cli/blob/1052ac1a5dd0fde4da8693d4712064f7876c269c/src/agent/infra/llm/providers/byterover.ts#L6)).
   - 로컬에서는 공급자 20여 개 중에서 BYO 키를 쓰면 됩니다.
7. **삭제**: `delete_memory`/`edit_memory` 도구가 있습니다.
8. **설치**: `npm i -g byterover-cli`, MCP 연결.

## 9. Letta (`letta-ai/letta` @ `5bcdd17` → `letta-ai/letta-code` @ `316e4c0`)

1. **식별**
   - letta 저장소는 README만 남았고, V1 서버는 `archive` 브랜치로 은퇴했습니다 ([README](https://github.com/letta-ai/letta/blob/5bcdd177d70fa2b31a754cfcd801e77b2e1ab16a/README.md)).
   - 현재 코드는 letta-code에 있습니다(Apache-2.0, ★약 3.6천, TS).
2. **쓰기 경로**: 메인 에이전트 또는 백그라운드 **memory 서브에이전트**가 git 기반 메모리 파일을 직접 Edit/Write하고 commit합니다 ([memory-v2.md](https://github.com/letta-ai/letta-code/blob/316e4c0545b549c453e0f85cc81d3540404eff74/src/agent/subagents/builtin/memory-v2.md)). 즉 **판단 주체는 에이전트 LLM**입니다.
3. **갱신/통합**: "Update existing entries rather than duplicating"이라는 프롬프트 규칙에 따르고, git merge와 conflict repair를 거칩니다.
4. **검색**: 메모리 파일을 시스템 프롬프트에 주입하고, 메시지와 트랜스크립트를 검색합니다 ([backend/local/transcript-search.ts](https://github.com/letta-ai/letta-code/blob/316e4c0545b549c453e0f85cc81d3540404eff74/src/backend/local/transcript-search.ts)).
5. **저장소**
   - 기본은 **Letta Cloud API**입니다.
   - 로컬 백엔드는 실험 플래그 `LETTA_LOCAL_BACKEND_EXPERIMENTAL`로 켜고, 파일과 JSONL에 저장합니다 ([paths.ts#L15](https://github.com/letta-ai/letta-code/blob/316e4c0545b549c453e0f85cc81d3540404eff74/src/backend/local/paths.ts#L15)).
6. **LOCAL vs CLOUD**
   - `getServerUrl()`이 `LETTA_BASE_URL`이 없으면 `https://api.letta.com`을 씁니다 ([server-url.ts#L8-L15](https://github.com/letta-ai/letta-code/blob/316e4c0545b549c453e0f85cc81d3540404eff74/src/backend/api/server-url.ts#L8), [oauth.ts#L10](https://github.com/letta-ai/letta-code/blob/316e4c0545b549c453e0f85cc81d3540404eff74/src/auth/oauth.ts#L10)).
   - `isCloudServerUrl`로 computers/environment 라우팅 같은 클라우드 전용 개념을 켭니다 ([#L17-L38](https://github.com/letta-ai/letta-code/blob/316e4c0545b549c453e0f85cc81d3540404eff74/src/backend/api/server-url.ts#L17)).
   - memfs git 원격은 클라우드 프록시를 거칩니다 ([memfs-git-proxy.ts](https://github.com/letta-ai/letta-code/blob/316e4c0545b549c453e0f85cc81d3540404eff74/src/backend/api/memfs-git-proxy.ts)).
   - self-host는 `letta server --listen`(App Server)이고, 비-loopback 연결에는 capability/signed token을 씁니다 ([server.ts#L11-L44](https://github.com/letta-ai/letta-code/blob/316e4c0545b549c453e0f85cc81d3540404eff74/src/cli/subcommands/server.ts#L11)).
7. **삭제**: 메모리 파일 편집과 git 이력으로 처리합니다 [추론].
8. **설치**: `npm i -g @letta-ai/letta-code`.

## 10. Pinecone Assistant MCP (`pinecone-io/assistant-mcp` @ `94eeaf4`)

- MIT, ★46, Rust.
- 도구는 `assistant_context` 하나뿐이고 조회 전용입니다 ([router.rs#L53](https://github.com/pinecone-io/assistant-mcp/blob/94eeaf4637cf927087aebbf1863550781c310ac5/src/router.rs#L53)).
- `PINECONE_API_KEY`가 필수이고, 기본 호스트는 `https://prod-1-data.ke.pinecone.io`입니다 ([config.rs#L12-L22](https://github.com/pinecone-io/assistant-mcp/blob/94eeaf4637cf927087aebbf1863550781c310ac5/src/config.rs#L12)).
- 로컬 모드도, 메모리 쓰기 경로도 없습니다. 지식 베이스 RAG 클라이언트이고 대화 메모리 시스템이 아닙니다.

## 11. 추가 발견 (클라우드/로컬 차이 위주로 짧게 확인)

- **Memori** (`MemoriLabs/Memori` @ `574b1ea`, Apache-2.0, ★약 1.7만)
  - 동작 모드는 세 가지입니다: cloud(`MEMORI_API_KEY`), CockroachDB 연결 문자열, BYODB 연결 ([__init__.py#L145-L185](https://github.com/MemoriLabs/Memori/blob/574b1ea3e876f100ef82c37817d603eb7e258e59/memori/__init__.py#L145)).
  - **BYODB에서도 `AdvancedAugmentation.process`가 대화 메시지와 요약을 `https://api.memorilabs.ai/sdk/augmentation`으로 POST합니다.** 코드에 x-api-key가 하드코딩되어 있고, 사용량 한도(quota) 예외가 있습니다 ([_augmentation.py#L125-L180](https://github.com/MemoriLabs/Memori/blob/574b1ea3e876f100ef82c37817d603eb7e258e59/memori/memory/augmentation/augmentations/memori/_augmentation.py#L125), [_network.py#L41-L66](https://github.com/MemoriLabs/Memori/blob/574b1ea3e876f100ef82c37817d603eb7e258e59/memori/_network.py#L41)).
  - 저장은 로컬에 하지만 기억 추출은 클라우드에서 합니다.
- **Hindsight** (`vectorize-io/hindsight` @ `d5b1d42`, MIT, ★약 5만)
  - **기본 DB URL이 `"pg0"`이고, `pg0-embedded`로 임베디드 Postgres를 띄웁니다.** Docker 없이 PG를 쓸 수 있습니다 ([config.py#L1099-L1106](https://github.com/vectorize-io/hindsight/blob/d5b1d4282f3325116c06f76ce3e79dce5ea4e22c/hindsight-api-slim/hindsight_api/config.py#L1099), [pg0.py](https://github.com/vectorize-io/hindsight/blob/d5b1d4282f3325116c06f76ce3e79dce5ea4e22c/hindsight-api-slim/hindsight_api/pg0.py)).
  - 기본 LLM은 openai `gpt-4o-mini`입니다.
  - 테넌시는 extension으로 바꿔 끼웁니다. 기본은 인증 없는 단일 schema이고 `ApiKeyTenantExtension`이 있습니다 ([builtin/tenant.py#L8-L44](https://github.com/vectorize-io/hindsight/blob/d5b1d4282f3325116c06f76ce3e79dce5ea4e22c/hindsight-api-slim/hindsight_api/extensions/builtin/tenant.py#L8)).
  - Claude Code 플러그인은 `UserPromptSubmit` 자동 recall, `Stop` 자동 retain입니다 ([README#L86-L88](https://github.com/vectorize-io/hindsight/blob/d5b1d4282f3325116c06f76ce3e79dce5ea4e22c/hindsight-integrations/claude-code/README.md#L86)).
- **Cognee** (`topoteretes/cognee` @ `f154b32`, Apache-2.0, ★약 3.2만)
  - 로컬 기본이 SQLite + LanceDB + Ladybug(Kuzu 계열)로 모두 임베디드입니다 ([relational/config.py#L22](https://github.com/topoteretes/cognee/blob/f154b32a9e544dac73e7ddf2010327cf9988edcd/cognee/infrastructure/databases/relational/config.py#L22), [vector#L32](https://github.com/topoteretes/cognee/blob/f154b32a9e544dac73e7ddf2010327cf9988edcd/cognee/infrastructure/databases/vector/config.py#L32), [graph#L47](https://github.com/topoteretes/cognee/blob/f154b32a9e544dac73e7ddf2010327cf9988edcd/cognee/infrastructure/databases/graph/config.py#L47)).
  - `cognee.serve()`를 쓰면 remember/recall이 Cognee Cloud로 라우팅됩니다 ([serve.py#L1-L52](https://github.com/topoteretes/cognee/blob/f154b32a9e544dac73e7ddf2010327cf9988edcd/cognee/api/v1/serve/serve.py#L1)).
- **memU** (`NevaMind-AI/memU` @ `bbf2d70`, LICENSE.txt Apache-2.0, ★약 1.5만)
  - 로컬 기본 저장소가 **inmemory(영속성 없음)**이고 sqlite/postgres를 선택할 수 있습니다 ([settings.py#L152-L159](https://github.com/NevaMind-AI/memU/blob/bbf2d7040d00c0b5b41b72505085a1349d9b9af6/src/memu/app/settings.py#L152)).
  - 클라우드는 `https://api.memu.so/api/v4/memory/`이고 user_id/agent_id 필터만 지원합니다 ([cloud.py#L13](https://github.com/NevaMind-AI/memU/blob/bbf2d7040d00c0b5b41b72505085a1349d9b9af6/src/memu/cloud.py#L13)).
- **Memobase** (`memodb-io/memobase` @ `358c16b`, Apache-2.0, ★약 2.9천, 2026-01 이후 정체)
  - 클라이언트 기본이 `https://api.memobase.dev`입니다 ([entry.py#L33](https://github.com/memodb-io/memobase/blob/358c16bbc6d687937d79bc2f984a11c3be8da901/src/client/memobase/core/entry.py#L33)).
  - OSS 서버에도 billing 컨트롤러가 들어 있습니다 ([billing.py#L21](https://github.com/memodb-io/memobase/blob/358c16bbc6d687937d79bc2f984a11c3be8da901/src/server/api/memobase_server/controllers/billing.py#L21)).
  - `llm_api_key`가 필수입니다 ([env.py#L194](https://github.com/memodb-io/memobase/blob/358c16bbc6d687937d79bc2f984a11c3be8da901/src/server/api/memobase_server/env.py#L194)).
- **MemOS** (`MemTensor/MemOS` @ `a7367d0`, Apache-2.0, ★약 1.2만)
  - 서버의 기본 그래프 DB는 `neo4j-community`입니다 ([api/config.py#L1234-L1235](https://github.com/MemTensor/MemOS/blob/a7367d07e55db61099f7b4e2c1108bc5831a24f3/src/memos/api/config.py#L1234)).
  - 파일 기반 로컬 플러그인이 따로 있고, Cloud 플러그인은 `memos.memtensor.cn/api/openmem/v1`에 `MEMOS_API_KEY`로 붙습니다 ([config-resolution-schema.js#L2-L3](https://github.com/MemTensor/MemOS/blob/a7367d07e55db61099f7b4e2c1108bc5831a24f3/apps/MemOS-Cloud-OpenClaw-Plugin/lib/config-resolution-schema.js#L2)).
- **Basic Memory** (`basicmachines-co/basic-memory` @ `54b8d94`, AGPL-3.0): 로컬은 Markdown + SQLite이고, 클라우드는 rclone bisync로 테넌트별 Tigris S3 버킷에 동기화합니다 ([rclone_config.py#L108-L121](https://github.com/basicmachines-co/basic-memory/blob/54b8d94b94cb8e4e526f438010ca771c5ad9f209/src/basic_memory/cli/commands/cloud/rclone_config.py#L108)).
- **AWS Bedrock AgentCore Memory SDK** (`aws/bedrock-agentcore-sdk-python` @ `b70e0b7`)
  - 클라우드 전용입니다. boto3 `bedrock-agentcore`(데이터 플레인)와 `-control`(컨트롤 플레인)을 씁니다 ([client.py#L99-L101](https://github.com/aws/bedrock-agentcore-sdk-python/blob/b70e0b709f6c8ec897b28fe873c3364e17f5cfec/src/bedrock_agentcore/memory/client.py#L99)).
  - 추출 전략은 `add_semantic_strategy` 등으로 서버 측에서 설정합니다 ([#L1403](https://github.com/aws/bedrock-agentcore-sdk-python/blob/b70e0b709f6c8ec897b28fe873c3364e17f5cfec/src/bedrock_agentcore/memory/client.py#L1403)).
- **EverOS** (구 EverMemOS, Apache-2.0, ★약 1.3만): Markdown + SQLite + LanceDB 로컬, EverOS Cloud, `uvx everos-mcp` [README만, [README#L63,L366](https://github.com/EverMind-AI/EverOS/blob/5d9fd4d91a70098466ffa1bd62454c8362c2c8e9/README.md#L366)].
- **발견했지만 깊이 읽지 않은 것**
  - Graphlit MCP: 클라우드 전용.
  - Google Vertex AI Memory Bank, Oracle agent memory: Redis 벤치마크 어댑터 목록에만 등장합니다.
  - langmem, doobidoo/mcp-memory-service, CaviraOSS/LongMemory(구 OpenMemory), zilliztech/memsearch: 로컬 우선이라 카테고리 C 밖입니다.

---

## 카테고리 요약표

| 프로젝트 | 기억 판단 주체 | 저장소/Docker | 검색 | 로컬 vs 클라우드 핵심 차이 | 설치 |
|---|---|---|---|---|---|
| Supermemory | 저장 내용: 호출 에이전트·훅 / 추출: 비공개 서버 | Cloud 비공개 · Local 내장 엔진 바이너리, Docker 선택 | hybrid (비공개) | **엔진 코드 비공개**, local은 무료 한도+키 1개, 커넥터·조직·자체 모델은 Enterprise | 호스팅 MCP+OAuth, Claude 플러그인, 바이너리 |
| Honcho | 서버 LLM deriver + dreamer + dialectic | PG(+pgvector 등) + Redis, Docker 선택 | 벡터 + 도구 쓰는 dialectic 에이전트 | 같은 코드, **기본 USE_AUTH=False(전원 admin)**, SDK·MCP 기본이 `api.honcho.dev`, 기본 LLM OpenAI | 관리형, `honcho start`, compose, 플러그인 |
| Zep / Graphiti | 서버 LLM (추출·dedup·모순 무효화) | Neo4j/FalkorDB/Kuzu/Neptune; CE는 PG+Neo4j+Docker | cosine+BM25+BFS, RRF/MMR/CE | **Cloud 엔진 비공개**, CE deprecated(billing mock, 공유 secret), Zep MCP는 조회 전용+클라우드 키 | `pip zep-cloud` / graphiti / Docker MCP |
| Mem0 | 서버 LLM (추가 전용 + md5 dedup) | 임베디드 Qdrant(/tmp) + SQLite, server/는 pgvector+Docker | semantic+BM25+entity 결합 | Platform 전용 API(temporal, decay, webhook, export 등), OSS 기본 OpenAI + PostHog 켜짐 + 원격 공지 fetch | pip, Platform 키, 에이전트 플러그인 |
| Redis Agent Memory | 서버 LLM 백그라운드 추출 + LLM merge | Redis 필수 | semantic/keyword/hybrid + recency | **OSS는 V0(연구용)**, 제품은 Redis Cloud, V0 기본 인증 꺼짐·gpt-5 | Redis Cloud 콘솔 / V0 Docker |
| MemMachine | 서버 LLM (semantic ADD/DELETE) | PG/SQLite/Neo4j/Qdrant 등, compose | episodic + 다양한 reranker, retrieval agent | 같은 코드, **서버에 인증 코드 없음**(org_id 요청 필드), Cloud는 Platform 콘솔 | pip client, compose, Helm |
| Papr | 서버 LLM (usecase·관계·스키마·Cypher 생성) | Mongo+Redis+Neo4j+Qdrant+Parse+Temporal, **Docker 필수** | Qdrant + LLM 생성 Cypher | `PAPR_EDITION` 플래그로 stripe/auth0/과금/rate limit 클라우드 전용, OpenAI 필수 | docker compose |
| ByteRover (archived) | brv 내장 에이전트 LLM (curate) + 사람 review | 프로젝트 파일, Docker 없음 | minisearch | Elastic-2.0, 클라우드 = OIDC + cogit push/pull + billing + 내장 LLM 프록시(로그인 필요) | npm, MCP |
| Letta (letta-code) | 에이전트·메모리 서브에이전트가 파일 직접 편집 | 기본 Letta Cloud / 실험적 로컬 파일 | 프롬프트 주입 + 트랜스크립트 검색 | **기본 백엔드가 `api.letta.com`**, 로컬은 실험 플래그, 클라우드 전용 라우팅 | npm |
| Pinecone assistant-mcp | (쓰기 없음) | Pinecone 호스팅 | Assistant context | 클라우드 전용 | Docker/바이너리 |
| Memori | 클라우드 API ("augmentation") | BYODB/CockroachDB/Cloud | — | **BYODB에서도 대화를 memorilabs.ai로 전송해 추출** | pip |
| Hindsight | 서버 LLM retain/reflect | **임베디드 PG(pg0), Docker 불필요** | (미확인) | tenant extension으로 다중 테넌트, 기본 OpenAI | pip, Claude 플러그인 |

## agents-memory와 비교한 시사점

- **판단 주체**: 위 시스템 중 "현재 코딩 에이전트가 정확한 byte span을 고르고, 서버는 검증만 하고, 서버측 LLM은 없다"는 구조는 없었습니다. 가장 가까운 것은 Letta(에이전트가 파일 편집)와 Supermemory MCP `add_memory`(에이전트가 내용 결정)입니다. 다만 Supermemory는 그 뒤에 서버 LLM이 처리합니다.
- **egress**: 서버측 LLM이 없다는 점 자체가 차별점입니다. Honcho, Mem0, Graphiti, Redis V0, MemMachine, Papr는 self-host 기본값으로도 OpenAI를 호출하고, Memori는 로컬 DB 모드에서도 원문을 벤더 API로 보냅니다.
- **인증 기본값**: Honcho(admin 우회), Redis V0(인증 꺼짐), MemMachine(인증 코드 없음), Mem0 server(`AUTH_DISABLED` 허용)처럼 self-host 인증이 기본으로 약한 경우가 흔합니다. 프로젝트별 자격증명과 loopback 바인딩은 비교 우위로 내세울 수 있습니다.
- **Docker 의존 문제**: Hindsight가 `pg0-embedded`로 Docker 없이 PG를 띄웁니다([pg0.py](https://github.com/vectorize-io/hindsight/blob/d5b1d4282f3325116c06f76ce3e79dce5ea4e22c/hindsight-api-slim/hindsight_api/pg0.py)). PostgreSQL을 계속 기준 저장소로 두면서 Docker 요구를 없앨 수 있는 선례입니다.
- **삭제 semantics**: Supermemory의 의미 유사도 1건 forget이나 Mem0의 hard delete와 history 같은 방식과 비교하면, 우리 쪽 retract/purge와 삭제 기록(deletion journal)은 감사 가능성 면에서 차별점입니다.

## 5. 멀티 프로젝트·기억 블록 (원문)

# 여러 프로젝트를 한 DB에 저장하는 방식과 기억 블록 유형: 19개 오픈소스 + 우리 프로젝트

19개 프로젝트 모두 소스 코드를 읽었습니다. 코드는 직접 확인한 결과이고, 직접 확인하지 못한 부분은 [추론]으로 표시했습니다.

먼저 알아 둘 조사 조건입니다.
- 일부 프로젝트는 HEAD 대신 다른 커밋을 봤습니다. 각 행의 근거 링크가 해당 커밋으로 고정되어 있습니다.
  - Letta: main 브랜치가 안내 페이지로 바뀌어 `archive` 브랜치 `56ba9c2`를 봤습니다.
  - cipher: `campfirein/cipher`가 `byterover-cli`로 리다이렉트되고 HEAD는 v3라서 `cipher-final` 태그 `ddbb782f`를 봤습니다.
  - OpenMemory: 모노레포에서 제거되기 직전 커밋 `540d23d`를 봤습니다.
  - Mem0 그래프 메모리: HEAD에서 삭제되어 `e44b46e`를 봤습니다.
- **줄 번호가 조금 어긋날 수 있습니다.** 한 서브에이전트가 `read` 도구가 연속된 빈 줄을 하나로 합친다고 보고했습니다. 그래서 일부 Python 링크의 `#L` 앵커는 ±1–2줄 틀릴 수 있습니다.
- **우리 프로젝트(agents-memory)는 SHA로 고정하지 못했습니다.** 이 세션에서 bash가 막혀 git을 실행할 수 없었습니다. 브랜치 `feat/agents-memory-resume-local`의 로컬 경로와 줄 번호로 인용했습니다.

## 1. 비교표

| project | 프로젝트 구분 방식 | 격리 강제 주체 | 코딩에이전트 프로젝트 판별 | 존재하는 기억 블록 유형 | 근거 링크 |
|---|---|---|---|---|---|
| **우리 (agents-memory)** | **정식 테이블.** `am_bindings`(`realm, owner_id, label, locator`=절대 디렉터리)가 있고, 기억 관련 테이블에 모두 `binding_id NOT NULL FK`가 있습니다. | **서버가 자격증명으로 강제합니다.** 토큰 해시 → `am_credentials` → `am_grants(credential_id, binding_id)` 순서로 묶이고, `_actor()`는 grant에 없는 binding이면 거부합니다. 프로젝트 간 승격은 `am_rules.scope ∈ {local_project, my_projects, shared}` + `am_rule_targets` + approver 자격증명으로 합니다. | operator가 `project add --label --locator`로 등록합니다. hook은 cwd가 등록된 project_root 아래인지 **검사만** 합니다(`registered_binding_plus_cwd_locator_check_not_cwd_authority`). cwd가 프로젝트를 정하지는 않습니다. | **project**: ✓<br>**source**: `am_sources`. `kind`=conversation/document/finding/correction/query, `event_time` 있음<br>**claim**: `am_claims`. `kind`=fact/preference/procedure/finding/rule_candidate, SPO 구조, `valid_from/until`. `am_claim_sources`와 바이트 단위 `am_spans`로 출처를 연결합니다.<br>**relation**: `am_relations`, claim↔claim. kind=duplicates/supports/contradicts/supersedes/conditional_variant/possible_same. 출처는 `am_relation_sources`.<br>**entity**: △. claim마다 이름만 있습니다(`am_entities`).<br>**reflection**, **rule**: 있음<br>**task, artifact, event 테이블**: 없음 | `src/agents_memory/migrations/versions/0001_authority.py:20-125`, `src/agents_memory/store.py:200-215`, `store.py:315-330`, `src/agents_memory/domain.py:133,291,352`, `src/agents_memory/hosts.py:121,1449-1456` |
| claude-mem | **로컬 SQLite**: 자유 문자열 `project TEXT NOT NULL` 컬럼만 있고 project 테이블은 없습니다. 병합 별칭으로 `merged_into_project`를 씁니다.<br>**server-beta(Postgres)**: `teams → projects` 테이블이 있고, 행마다 `(project_id, team_id)` FK가 있습니다. | **로컬**: 인증이 없고 호출 측이 넘기는 필터입니다.<br>**server-beta**: API 키가 `api_keys.project_id`에 묶이고, 다른 프로젝트를 요청하면 403입니다. | **cwd 기반 자동 판별.** 순서: env 매핑 → (옵트인) origin `org/repo` → `git rev-parse --show-toplevel`의 basename → 마커 파일 → cwd basename. worktree는 `parent/worktree` 형태입니다. | **source**: `tool_uses`, `user_prompts`, Postgres의 `agent_events`<br>**observation**: `type` 9종(bugfix, decision…)<br>**claim**: observation 안의 `facts` 필드<br>**세션 요약**: 있음<br>**task**: `work_state_entries`가 비슷합니다 [추론]<br>**artifact**: `files_read`/`files_modified` 컬럼만<br>**entity, relation**: 없음 | [SQLite DDL](https://github.com/thedotmack/claude-mem/blob/fef3402e674bebbf72a23aeb735e91c92cd34afd/src/services/sqlite/SessionStore.ts#L1185-L1241), [project-name](https://github.com/thedotmack/claude-mem/blob/fef3402e674bebbf72a23aeb735e91c92cd34afd/src/utils/project-name.ts#L269-L305), [PG schema](https://github.com/thedotmack/claude-mem/blob/fef3402e674bebbf72a23aeb735e91c92cd34afd/src/storage/postgres/schema.ts#L99-L131), [키 강제](https://github.com/thedotmack/claude-mem/blob/fef3402e674bebbf72a23aeb735e91c92cd34afd/src/server/routes/v1/ServerV1PostgresRoutes.ts#L1371-L1375) |
| basic-memory | **정식 `project` 테이블**(`path`=폴더, `is_default`). entity, observation, relation, `memory_time_index`에 모두 `project_id` FK가 있습니다. 로컬은 SQLite 하나에 여러 프로젝트를 담고, 클라우드는 tenant별 DB입니다. | **로컬**: 호출자가 `project` 파라미터를 넘깁니다. 단 `BASIC_MEMORY_MCP_PROJECT` 환경변수가 있으면 프로세스를 그 프로젝트에 고정합니다.<br>**클라우드**: tenant 라우팅을 하지만 인가 코드는 이 저장소에 없습니다 [추론].<br>`secondaryProjects`/`teamProjects`는 읽기 전용 recall입니다. | 명시 설정을 씁니다. hook은 가장 가까운 `.claude/settings*.json`의 `basicMemory.primaryProject`를 읽습니다. cwd나 git으로 자동 판별하지 않습니다. | **project**, **entity**(노트 파일), **claim**(`observation`), **relation**(`relation_type`은 자유 문자열), **event**(시간 단언, `memory_time_index`), **source**(markdown 원문)<br>**task, artifact**: 없음 | [Project](https://github.com/basicmachines-co/basic-memory/blob/54b8d94b94cb8e4e526f438010ca771c5ad9f209/src/basic_memory/models/project.py#L25-L59), [knowledge.py](https://github.com/basicmachines-co/basic-memory/blob/54b8d94b94cb8e4e526f438010ca771c5ad9f209/src/basic_memory/models/knowledge.py#L31-L120), [resolver](https://github.com/basicmachines-co/basic-memory/blob/54b8d94b94cb8e4e526f438010ca771c5ad9f209/src/basic_memory/project_resolver.py#L13-L100) |
| mcp-memory-service | project 컬럼이 없고, 프로젝트는 태그 관례(`proj:` 또는 hook이 붙이는 bare 태그)입니다. 별도로 `store TEXT DEFAULT 'default'` 파티션 컬럼이 있습니다. | **호출자 필터.** API 키 scope는 read/write/admin뿐이고 store와 묶이지 않습니다. `beliefs`와 `memory_graph` 테이블에는 store 컬럼이 없습니다. | hook이 판별합니다. 순서: `package.json` 같은 설정 파일 → git remote → cwd basename. 결과는 태그로만 저장되고 store는 지정하지 않아 `'default'`가 됩니다. | 단일 `memories` 테이블 + `memory_type` 12종<br>**task 성격 subtype**: `backlog_item`, `action_item`<br>**artifact 성격 subtype**: `code_edit`<br>**relation**: `memory_graph`(causes, contradicts, derived_from…)<br>**claim**: `beliefs`. `derived_from`이 근거 observation을 가리킵니다.<br>**entity 테이블**: 없음 | [DDL](https://github.com/doobidoo/mcp-memory-service/blob/1a5da675c5dcb976582bb7141ad0150c7fc9f76c/src/mcp_memory_service/storage/mixins/migrations.py#L401-L414), [store](https://github.com/doobidoo/mcp-memory-service/blob/1a5da675c5dcb976582bb7141ad0150c7fc9f76c/src/mcp_memory_service/storage/mixins/migrations.py#L491-L509), [ontology](https://github.com/doobidoo/mcp-memory-service/blob/1a5da675c5dcb976582bb7141ad0150c7fc9f76c/src/mcp_memory_service/models/ontology.py#L41-L209), [beliefs](https://github.com/doobidoo/mcp-memory-service/blob/1a5da675c5dcb976582bb7141ad0150c7fc9f76c/src/mcp_memory_service/storage/migrations/012_add_belief_store.sql), [detector](https://github.com/doobidoo/mcp-memory-service/blob/1a5da675c5dcb976582bb7141ad0150c7fc9f76c/claude-hooks/utilities/project-detector.js#L190-L270) |
| MCP `servers/src/memory` | 프로젝트 개념이 없습니다. JSONL 파일 하나가 그래프 하나이고, 파일은 `MEMORY_FILE_PATH`로 고릅니다. | 없음. 프로젝트를 나누려면 서버 인스턴스마다 다른 파일을 지정해야 합니다. | 없음 | **entity**(`entityType`은 자유 문자열), **claim**(`observations: string[]`, 엔터티 안에 내장), **relation**(`from`/`to`/`relationType`)<br>시간 정보와 출처 정보는 없습니다. | [index.ts#L54-L110](https://github.com/modelcontextprotocol/servers/blob/bbb701e7ac1e57f3edd1c2836b94c5457eaf7b9c/src/memory/index.ts#L54-L110) |
| cipher (ByteRover) | 기억 종류별 벡터 컬렉션이 따로 있습니다(knowledge/reflection/workspace). payload에 자유 문자열 `projectId`/`userId`/`workspaceMode`가 들어갑니다. | **클라이언트 쪽 후처리 필터.** `shared` 모드일 때만 거르고, 기본값 `isolated` 모드에서는 필터가 없습니다. | `CIPHER_PROJECT_NAME` 환경변수를 씁니다. cwd나 git 판별 경로는 찾지 못했습니다 [추론]. | **claim**: knowledge<br>**source 성격**: reflection(추론 과정)<br>**task 성격**: workspace의 `currentProgress`(feature/status), 버그 기록<br>**entity·artifact·relation**: KG 노드 `File/Function/Class/Module/Entity`와 엣지 `CALLS/DEPENDS_ON/…`<br>**감사 로그**: `memory_history`(`project_id NOT NULL`) | [payloads.ts](https://github.com/campfirein/byterover-cli/blob/ddbb782f8f53f710fbe3ce55a07e9f4a675ba628/src/core/brain/tools/definitions/memory/payloads.ts#L8-L64), [workspace-payloads.ts](https://github.com/campfirein/byterover-cli/blob/ddbb782f8f53f710fbe3ce55a07e9f4a675ba628/src/core/brain/tools/definitions/memory/workspace-payloads.ts#L13-L43), [search_memory.ts](https://github.com/campfirein/byterover-cli/blob/ddbb782f8f53f710fbe3ce55a07e9f4a675ba628/src/core/brain/tools/definitions/memory/search_memory.ts#L373-L391), [kg constants](https://github.com/campfirein/byterover-cli/blob/ddbb782f8f53f710fbe3ce55a07e9f4a675ba628/src/core/knowledge_graph/constants.ts#L174-L195) |
| Mem0 (OSS + 호스팅 client) | **OSS**: project 컬럼이 없습니다. 스코프 키는 `user_id`/`agent_id`/`run_id`(하나는 필수)입니다.<br>**플랫폼 client**: `app_id`가 추가되고, `org_id`/`project_id`는 API 키에서 정해집니다. | **OSS**: 호출자 필터입니다.<br>**플랫폼**: 키에 묶인 서버 측 격리로 보입니다 [추론: 서버 코드 비공개]. | Claude Code 플러그인이 `git rev-parse --show-toplevel`과 `remote.origin.url`로 판별합니다. `app_id`=repo, `agent_id`=프로젝트 공유 풀, `user_id`=개인, `run_id`=세션으로 씁니다. | **claim**: memory item<br>**entity**: entity store, `linked_memory_ids`로 fact와 연결<br>**source**: 일부. `messages` 테이블은 최근 10개만 보관합니다.<br>**event**: `history`(감사 로그)<br>**relation**: HEAD에서 그래프 메모리가 삭제되어 없습니다.<br>**project, task, artifact**: 없음 | [main.py#L303-L393](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/mem0/memory/main.py#L303-L393), [client#L284-L295](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/mem0/client/main.py#L284-L295), [plugin](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/integrations/claude-code-plugin/core/memory_core.py#L279-L319) |
| OpenMemory | `users`, `apps`, `memories(user_id FK, app_id FK)` 테이블이 있습니다. 여기서 app은 MCP 클라이언트 이름이고 프로젝트가 아닙니다. | ACL 테이블은 있지만 **인증이 없습니다.** 경로에 있는 `user_id`를 그대로 믿고, 앱 간 공유가 기본값입니다. | 없음 | **claim**: memory(`state`), category(M:N)<br>**event**: `memory_status_history`, `memory_access_logs`<br>**그 밖**: 없음 | [models.py](https://github.com/mem0ai/mem0/blob/540d23d610fcdc9a1f8795875c013af67d35ae93/openmemory/api/app/models.py#L34-L176), [mcp_server.py](https://github.com/mem0ai/mem0/blob/540d23d610fcdc9a1f8795875c013af67d35ae93/openmemory/api/app/mcp_server.py#L171-L180) |
| Hindsight | `bank_id`가 모든 테이블의 1급 컬럼입니다(memory_units는 bank_id로 LIST 파티션). 그 위의 tenant는 PostgreSQL schema 단위로 분리됩니다. | **tenant(schema)**: 서버가 `TenantExtension.authenticate()`로 강제합니다.<br>**bank**: 호출자가 고릅니다. `allowed_bank_ids` 필드는 선언만 있고 검사하는 코드는 찾지 못했습니다. | 플러그인이 정합니다. 순서: `directoryBankMap` → 정적 `bankId` → `dynamicBankId`(`agent::project`). 여기서 project는 git common-dir 상위 폴더 이름입니다. | **source**: documents → chunks<br>**claim**: memory_units, `fact_type` ∈ world/experience/observation, 시간 컬럼 포함<br>**entity**: entities, unit_entities<br>**relation**: `memory_links`(temporal/semantic/causes…)<br>**그 밖**: mental_models, directives<br>**project, task, artifact**: 없음 | [models.py](https://github.com/vectorize-io/hindsight/blob/d5b1d4282f3325116c06f76ce3e79dce5ea4e22c/hindsight-api-slim/hindsight_api/models.py#L120-L165), [tenant.py](https://github.com/vectorize-io/hindsight/blob/d5b1d4282f3325116c06f76ce3e79dce5ea4e22c/hindsight-api-slim/hindsight_api/extensions/tenant.py#L25-L51), [bank.py](https://github.com/vectorize-io/hindsight/blob/d5b1d4282f3325116c06f76ce3e79dce5ea4e22c/hindsight-integrations/claude-code/scripts/lib/bank.py#L50-L165) |
| Cognee | **Dataset**이 1급 엔터티입니다(`owner_id`, `tenant_id`). 접근제어를 켜면 dataset마다 graph DB와 vector DB를 물리적으로 따로 둡니다. | **서버가 강제합니다.** 사용자 API 키 + ACL(read/write/delete/share)로 dataset 권한을 검사합니다. 공유는 dataset ID로만 됩니다. | cwd·git은 쓰지 않습니다. MCP 기본 dataset은 `{clientInfo.name}_memory`입니다. | **source**: Document, DocumentChunk<br>**entity**: Entity, EntityType<br>**event**: Event, Timestamp, Interval<br>**relation**: Edge<br>**claim 성격**: Triplet<br>**요약**: TextSummary, CodeSummary<br>**artifact**: CodeFile로 일부만<br>**project, task**: 없음 | [Dataset.py](https://github.com/topoteretes/cognee/blob/f154b32a9e544dac73e7ddf2010327cf9988edcd/cognee/modules/data/models/Dataset.py#L9-L22), [ACL.py](https://github.com/topoteretes/cognee/blob/f154b32a9e544dac73e7ddf2010327cf9988edcd/cognee/modules/users/models/ACL.py#L8-L22), [DatasetDatabase.py](https://github.com/topoteretes/cognee/blob/f154b32a9e544dac73e7ddf2010327cf9988edcd/cognee/modules/users/models/DatasetDatabase.py#L8-L23), [DocumentChunk.py](https://github.com/topoteretes/cognee/blob/f154b32a9e544dac73e7ddf2010327cf9988edcd/cognee/modules/chunking/models/DocumentChunk.py#L36-L67) |
| Graphiti / Zep | 모든 노드와 엣지에 `group_id`가 있습니다. FalkorDB에서만 group마다 별도 graph를 쓰고, 다른 백엔드에서는 같은 DB 안의 속성 필터입니다. | **호출자 필터.** 인증 코드가 없습니다. 검색에서 `group_ids`를 생략하면 전체 group을 조회합니다. | `GRAPHITI_GROUP_ID`나 `--group-id`로 정하고, 도구 인자로 덮어쓸 수 있습니다. cwd·git은 쓰지 않습니다. | **source**: EpisodicNode<br>**entity**: EntityNode<br>**claim + relation**: `EntityEdge.fact`. 사실 시간(`valid_at`/`invalid_at`)과 시스템 시간을 둘 다 가집니다.<br>**출처 연결**: `MENTIONS` 엣지, `episodes[]`<br>**그 밖**: Community, Saga<br>**project, task, artifact**: 없음<br>Zep 서버 코드는 이 저장소에 없습니다. | [nodes.py](https://github.com/getzep/graphiti/blob/aca369364226a666ca541b061ff2a1a54b80f2ff/graphiti_core/nodes.py#L54-L98), [edges.py](https://github.com/getzep/graphiti/blob/aca369364226a666ca541b061ff2a1a54b80f2ff/graphiti_core/edges.py#L263-L290), [falkordb](https://github.com/getzep/graphiti/blob/aca369364226a666ca541b061ff2a1a54b80f2ff/graphiti_core/driver/falkordb_driver.py#L334-L347) |
| Letta | nullable `project_id` 컬럼이 agents, block, identities에만 있습니다. FK는 없고, OSS에는 projects 테이블도 없습니다. 실제 테넌트 단위는 `organization_id`입니다. | **org**: 서버가 모든 조회에 강제합니다.<br>**project**: 목록 필터일 뿐입니다.<br>OSS 인증은 공용 비밀번호 하나이고, actor는 `user_id` 헤더로 정해집니다. | 없음. 헤더나 파라미터로 명시해야 합니다. | **block**: `label` 자유 문자열(human, persona…), 에이전트 간 공유 가능<br>**source**: sources, files, passages, messages<br>**event**: messages, `block_history`<br>**entity**: identities<br>**claim 전용 타입, task, relation**: 없음 | [mixins](https://github.com/letta-ai/letta/blob/56ba9c25552605eec89de8ed3dc6394b625c1993/letta/orm/mixins.py#L17-L64), [block.py](https://github.com/letta-ai/letta/blob/56ba9c25552605eec89de8ed3dc6394b625c1993/letta/orm/block.py#L19-L48), [access predicate](https://github.com/letta-ai/letta/blob/56ba9c25552605eec89de8ed3dc6394b625c1993/letta/orm/sqlalchemy_base.py#L865-L895) |
| LangMem | 자유 형식 namespace 튜플입니다(기본 `("memories","{langgraph_user_id}")`). 프로젝트는 개발자가 튜플에 넣을 때만 생깁니다. | 라이브러리 자체는 강제하지 않습니다. LangGraph Platform의 auth 훅을 쓰면 namespace 앞에 `ctx.user.identity`가 강제로 붙습니다. | 없음. `configurable`에 명시해야 합니다. | store item 하나뿐입니다. `value.kind`가 스키마 클래스명입니다.<br>**semantic/episodic**: 사용자가 Pydantic 스키마로 정의합니다.<br>**procedural**: 프롬프트 최적화 결과 문자열이고 저장하지 않습니다.<br>**graph**: 코드가 전부 주석 처리되어 있습니다. | [utils.py](https://github.com/langchain-ai/langmem/blob/48e3c11f5bb527282c7d5339c6a87a0b35abccfc/src/langmem/utils.py#L14-L91), [auth.py](https://github.com/langchain-ai/langmem/blob/48e3c11f5bb527282c7d5339c6a87a0b35abccfc/src/langmem/graphs/auth.py#L12-L75) |
| A-MEM | 없음. 인메모리 Chroma 컬렉션 `"memories"`가 고정되어 있습니다. | 없음 | 없음 | 단일 `MemoryNote` 타입(keywords, tags, context, category, timestamp)<br>**relation 성격**: 타입 없는 `links`만 있습니다. | [memory_system.py](https://github.com/agiresearch/A-mem/blob/ceffb860f0712bbae97b184d440df62bc910ca8d/agentic_memory/memory_system.py#L24-L119) |
| MemOS | **서버**: MemCube(`cube_id`)를 그래프 노드의 `user_name` 속성으로 나눕니다. `project_id`는 요청에 담겨 전달만 됩니다 [추론].<br>**로컬 플러그인**: `owner_workspace_id` 컬럼이 있습니다. | **호출자 지정.** `readable_cube_ids`를 클라이언트가 넣습니다. 인증 기본값이 off이고, 큐브 접근 검사는 구버전 경로에만 있습니다. | **로컬 플러그인**: `workspaceDir` 해시로 workspaceId를 만들지만 기록만 하고 필터에는 쓰지 않습니다. | **memory_type** 10종(LongTerm, User, RawFile, ToolTrajectory, Skill…)<br>**source**: `sources[SourceMessage]`<br>**artifact**: `file_ids`<br>**relation**: 그래프 엣지<br>**event**: `memory_form`=event<br>**entity, task**: 없음 | [item.py](https://github.com/MemTensor/MemOS/blob/a7367d07e55db61099f7b4e2c1108bc5831a24f3/src/memos/memories/textual/item.py#L90-L209), [neo4j.py](https://github.com/MemTensor/MemOS/blob/a7367d07e55db61099f7b4e2c1108bc5831a24f3/src/memos/graph_dbs/neo4j.py#L425-L447), [namespace.ts](https://github.com/MemTensor/MemOS/blob/a7367d07e55db61099f7b4e2c1108bc5831a24f3/apps/memos-local-plugin/core/runtime/namespace.ts#L42-L125) |
| memU | project가 없고 `(user_id, agent_id)` 스코프만 있습니다. | **로컬**: 호출자 `where` 필터입니다.<br>**Cloud**: project API 키를 쓰지만 서버 코드가 없습니다 [추론]. | 판별하지 않습니다. hook이 `cwd`와 `gitBranch`를 지워서 모든 프로젝트가 기억 공간 하나를 씁니다. | **source**: `Resource`<br>**claim 성격**: `RecallFile`(track=memory/skill), `RecallFileSegment`<br>**그 밖**: 없음 | [models.py](https://github.com/NevaMind-AI/memU/blob/bbf2d7040d00c0b5b41b72505085a1349d9b9af6/src/memu/database/models.py#L17-L52), [sessions.py](https://github.com/NevaMind-AI/memU/blob/bbf2d7040d00c0b5b41b72505085a1349d9b9af6/src/memu/hosts/claude_code/sessions.py#L109-L112) |
| Memobase | **정식 파티션.** `projects(project_id, project_secret)` 테이블이 있고, 모든 PK가 `(id, project_id)`입니다. | **서버가 자격증명으로 강제합니다.** `sk-<project_id>-…` 토큰을 검증하고 project를 요청에 바인딩합니다. 단 OSS에서는 `__root__` 외 프로젝트 생성이 막혀 있습니다. | 없음. MCP는 고정 user를 씁니다. | **source**: `GeneralBlob`(chat/doc/code…)<br>**claim**: `UserProfile`(topic/sub_topic)<br>**event**: `UserEvent`, gist<br>**entity, relation**: 없음 | [database.py](https://github.com/memodb-io/memobase/blob/358c16bbc6d687937d79bc2f984a11c3be8da901/src/server/api/memobase_server/models/database.py#L179-L326), [middleware.py](https://github.com/memodb-io/memobase/blob/358c16bbc6d687937d79bc2f984a11c3be8da901/src/server/api/memobase_server/api_layer/middleware.py#L123-L196) |
| Supermemory | `containerTag` ↔ `Space(orgId, ownerId)`. document는 여러 space에 N:M으로 속할 수 있습니다. | **비공개 백엔드가 API 키 세션 scope로 판정합니다** [추론]. 공개된 MCP 코드는 실효 권한을 계산만 합니다. | 플러그인이 `repo_<name>__<remote-hash>`로 정합니다(README 근거, 비고정 링크). | **source**: document, chunk<br>**claim**: memory entry(버전 체인)<br>**relation**: updates/extends/derives<br>**출처 연결**: `MemoryDocumentSource`<br>**entity, event, task, artifact**: 없음 | [schemas.ts](https://github.com/supermemoryai/supermemory/blob/5323f427d076c7a158a9154867d293b53acc3841/packages/validation/schemas.ts#L218-L307), [rbac.ts](https://github.com/supermemoryai/supermemory/blob/5323f427d076c7a158a9154867d293b53acc3841/apps/mcp/src/server/auth/rbac.ts#L3-L36) |
| Honcho | `workspaces`가 테넌트이고, 모든 테이블에 `workspace_name` FK가 있습니다. project 개념은 없습니다. | **서버가 JWT로 강제합니다**(`w`/`p`/`s`/`sc` 클레임). `USE_AUTH`가 꺼지면 모든 요청이 admin입니다. | workspace 기본값은 호스트명입니다. session은 `per-directory`(기본)나 `git-branch`로 나눕니다(문서 근거). | **source**: messages<br>**claim**: documents. `level`=explicit/deductive/inductive/contradiction<br>**relation**: `document_sources` 추론 트리<br>**entity**: peer(사람·에이전트만)<br>**task, event, artifact**: 없음 | [models.py](https://github.com/plastic-labs/honcho/blob/ed1704265e609364da6bf291bb3369bc9654f8dc/src/models.py#L40-L578), [security.py](https://github.com/plastic-labs/honcho/blob/ed1704265e609364da6bf291bb3369bc9654f8dc/src/security.py#L260-L364) |
| Redis AMS (`V0/`) | 단일 인덱스에 자유 문자열 `namespace` TAG를 둡니다. | **호출자 필터.** 인증 기본값이 off이고, token 모드에서는 모든 토큰이 admin입니다. | env `DEFAULT_MCP_NAMESPACE`나 URL `/{namespace}/sse`로 정합니다. | **source**: message<br>**claim**: semantic<br>**event**: episodic + `event_date`<br>**entity, topic**: TAG 문자열만<br>**출처**: `extracted_from`<br>**relation, task, artifact**: 없음 | [models.py](https://github.com/redis/agent-memory-server/blob/94192c39e2a4a154f441a5411e3d73c4f54974a6/V0/agent_memory_server/models.py#L251-L342), [auth.py](https://github.com/redis/agent-memory-server/blob/94192c39e2a4a154f441a5411e3d73c4f54974a6/V0/agent_memory_server/auth.py#L314-L377) |
| MemMachine | `org_id`/`project_id`가 1급 API 키이고, `session_key = "{org}/{project}"`입니다. semantic `set_id`에 org와 project가 인코딩됩니다. | **호출자 값.** 서버 인증이 없습니다. org-level 세트는 같은 org 안 모든 프로젝트가 공유합니다. | 헤더 `proj-id`나 env `MM_PROJ_ID`로 정합니다. 기본값은 `mcp-{user_id}`입니다. | **source**: episode<br>**event**: Event → Segment → Derivative<br>**claim**: semantic feature<br>**출처 연결**: `citations`(feature→episode)<br>**entity, task, artifact, relation**: 없음 | [service.py](https://github.com/MemMachine/MemMachine/blob/d5a39a8e774e977fb1e6c22efb03555c4e51e05e/packages/server/src/memmachine_server/server/api_v2/service.py#L38-L51), [semantic_session_manager.py](https://github.com/MemMachine/MemMachine/blob/d5a39a8e774e977fb1e6c22efb03555c4e51e05e/packages/server/src/memmachine_server/semantic_memory/semantic_session_manager.py#L422-L497), [mcp.py](https://github.com/MemMachine/MemMachine/blob/d5a39a8e774e977fb1e6c22efb03555c4e51e05e/packages/server/src/memmachine_server/server/api_v2/mcp.py#L127-L186) |

## 2. 기억 블록 유형별 존재 여부

✓는 별도 테이블·타입·enum이 있음, △는 필드·라벨·관례로만 있음, ✗는 없음입니다.

| | project | task | claim | source | event | entity | artifact | relation | claim→source 출처 연결 |
|---|---|---|---|---|---|---|---|---|---|
| 우리 | ✓ | ✗ | ✓ | ✓ | △ | △ | ✗ | ✓ | ✓(바이트 span) |
| claude-mem | △/✓(PG) | △ | △ | ✓ | △ | ✗ | △ | ✗ | △(PG `observation_sources`) |
| basic-memory | ✓ | ✗ | ✓ | ✓ | △ | ✓ | △ | ✓ | △ |
| mcp-memory-service | ✗ | △ | ✓ | △ | △ | ✗ | △ | ✓ | ✓(`beliefs.derived_from`) |
| MCP memory | ✗ | ✗ | △ | ✗ | ✗ | ✓ | ✗ | ✓ | ✗ |
| cipher | △ | △ | ✓ | △ | ✗ | ✓ | ✓ | ✓ | △ |
| Mem0 | ✗ | ✗ | ✓ | △ | △ | ✓ | ✗ | ✗(삭제) | ✗ |
| OpenMemory | ✗ | ✗ | ✓ | ✗ | △ | ✗ | ✗ | ✗ | ✗ |
| Hindsight | △(bank) | ✗ | ✓ | ✓ | △ | ✓ | ✗ | ✓ | ✓ |
| Cognee | △(dataset) | ✗ | △ | ✓ | ✓ | ✓ | △ | ✓ | ✓ |
| Graphiti | △(group) | ✗ | ✓ | ✓ | △ | ✓ | ✗ | ✓ | ✓ |
| Letta | △ | ✗ | ✗ | ✓ | △ | △ | △ | ✗ | △(파일만) |
| LangMem | △ | ✗ | △ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| A-MEM | ✗ | ✗ | △ | ✗ | ✗ | ✗ | ✗ | △ | ✗ |
| MemOS | △(cube) | ✗ | ✓ | ✓ | △ | ✗ | △ | ✓ | ✓ |
| memU | ✗ | ✗ | △ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Memobase | ✓ | ✗ | △ | ✓ | ✓ | ✗ | △ | ✗ | ✗ |
| Supermemory | △ | ✗ | ✓ | ✓ | ✗ | ✗ | ✗ | ✓ | ✓ |
| Honcho | ✗ | ✗ | ✓ | ✓ | ✗ | △ | ✗ | △ | △ |
| Redis AMS | △ | ✗ | ✓ | ✓ | ✓ | △ | ✗ | ✗ | △ |
| MemMachine | ✓ | ✗ | ✓ | ✓ | ✓ | ✗ | ✗ | ✗ | ✓ |

## 3. 정리

- **프로젝트를 정식 단위로 두면서 서버가 자격증명으로 격리하는 곳은 소수입니다.**
  - project라는 이름의 정식 단위를 서버가 자격증명으로 강제하는 곳은 세 곳입니다: 우리(`am_grants`), Memobase(`project_secret` 토큰), claude-mem server-beta(키에 묶인 `project_id`).
  - Cognee는 dataset 단위, Honcho는 workspace 단위로 서버가 강제합니다.
  - 나머지 대부분(Graphiti, Redis AMS, MemMachine, mcp-memory-service, Mem0 OSS, OpenMemory, MemOS 서버)은 호출자가 값을 바꿀 수 있는 필터입니다. Graphiti와 Redis AMS는 필터를 생략하면 전체를 조회합니다.
- **코딩 에이전트의 프로젝트를 cwd나 git으로 자동 판별하는 쪽은 주로 플러그인입니다.**
  - claude-mem, Mem0·Hindsight·Supermemory의 플러그인, mcp-memory-service hook이 git root, remote, worktree 정규화를 씁니다. Honcho 문서도 세션을 디렉터리나 git 브랜치로 나눈다고 안내합니다.
  - 우리는 cwd를 **권한 근거로 쓰지 않습니다.** operator가 등록한 binding을 기준으로 삼고, cwd는 등록된 위치 아래에 있는지 검사하는 용도로만 씁니다. 판별 정확도보다 격리를 우선한 설계라 남들과 다릅니다.
- **프로젝트 간 공유나 승격을 스키마에 둔 곳**은 다음과 같습니다.
  - 우리: `am_rules.scope`가 `local_project`/`my_projects`/`shared`이고, `am_rule_targets`와 approver 자격증명이 필요합니다.
  - MemMachine: org-level 세트를 같은 org 안 모든 프로젝트가 공유합니다.
  - basic-memory: 읽기 전용 `secondaryProjects`가 있습니다.
  - claude-mem: `merged_into_project` 별칭이 있습니다.
  - Cognee: ACL의 share 권한으로 공유합니다.
  - Hindsight에는 bank 간 사실을 승격하는 경로가 보이지 않습니다 [추론].
- **발표에서 제안한 7개 블록을 모두 갖춘 프로젝트는 없습니다.**
  - **task**를 정식 블록으로 둔 곳은 없습니다. cipher의 workspace 진행상황, mcp-memory-service의 `backlog_item`/`action_item` subtype, claude-mem의 `work_state_entries`가 비슷한 정도입니다. 우리 `am_jobs`(extract/consolidate/reflect)는 처리 작업 큐이지 task 블록이 아닙니다.
  - **artifact(파일·코드)**를 독립 노드로 두는 곳은 cipher의 KG(File/Function/Class)뿐입니다. 나머지는 파일 경로 컬럼(claude-mem, Letta files, MemOS `file_ids`)에 그칩니다. 우리 `am_operations.artifact_id`는 이름과 달리 파생 레코드(selection, proposal, feedback 등)를 가리키는 포인터입니다(`store.py:872,907,979`).
  - 가장 흔한 조합은 **source + claim + entity + relation + 출처 연결**입니다(Graphiti, Hindsight, Cognee, Supermemory, MemOS). **event**를 별도 타입으로 둔 곳은 Cognee(Event/Interval), Memobase(UserEvent), Redis AMS(episodic + `event_date`), MemMachine(event_memory)입니다.
- **우리 스키마가 비어 있는 부분**은 세 가지입니다.
  - task 블록이 없습니다.
  - artifact(파일·코드) 블록이 없습니다.
  - entity는 claim에 딸린 이름만 있습니다(`am_entities(claim_id, name)`). 엔터티 노드 테이블이나 entity 간 관계가 없어서, Graphiti·Hindsight 수준의 entity graph가 아닙니다.
  - event는 별도 테이블 없이 `am_sources.event_time`과 `am_claims.valid_from/valid_until`로만 표현합니다.
  - 반면 claim→source 출처 연결은 바이트 span(`am_spans`)까지 내려가서, 비교한 프로젝트 중 가장 세밀합니다.

## 4. 확인하지 못한 항목

- **비공개라 코드로 확인할 수 없음**: Zep 상용 서버, Supermemory 백엔드, Mem0 플랫폼 서버, memU Cloud 서버. 이 부분의 격리 판단은 모두 [추론]입니다.
- **조회 도중 막힘**: 현행 `letta-code`가 cwd나 git으로 프로젝트를 판별하는지는 GitHub API 403(레이트 리밋) 때문에 확인하지 못했습니다.
- **별도 저장소라 읽지 않음**: Honcho의 Claude 플러그인 코드는 `plastic-labs/claude-honcho`에 있습니다. Honcho 행의 판별 방식은 공용 harness 코드와 문서를 근거로 했습니다.
