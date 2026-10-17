# 참고 OSS 후속 조사: 원인·수정 코드·회귀·평가 대조

## 범위와 증거 수준

이슈 [#5](https://github.com/chonamdoo/agents-memory/issues/5)의 기존 [86개 링크 분류](2026-10-15-oss-local-runtime.ko.md), [DB 성장 조사](2026-10-15-oss-db-growth.ko.md), [native trust 조사](2026-10-16-oss-native-trust.ko.md)를 잇는다. 이슈 댓글44개의 외부 GitHub repository 링크를 정규화해 기존86행과 대조했고 누락 링크는 없었다. **86은 독립된 사용 가능 OSS86종이라는 뜻이 아니다.** 별칭·상용 host·문서·demo·retired project·비상업 라이선스 자료도 원래 분류대로 남긴다.

upstream issue/PR·고정 source·회귀 코드를 읽었다. upstream 설치·test·eval은 실행하지 않았다. **초기 작성 시점**에는 우리 수정이 미커밋·미push·CI 미실행이었고 이전 전체2311 pass를 최신 결과로 세지 않았다. 이후 명시 허용된 정상 CI checkpoint 게시와 실제 GitHub Actions를 수행했다. 후속 정확한 source·실패 전/성공 후·설치 소비 증거는 [검증 기록](../verification.ko.md#정상-재개와-실제-설치-wheel-소비-범위-확대--8aa611b)과 각 SHA의 Actions/receipts를 따른다. 사용자 지시로 로컬 test/collection/ruff/lint/build/syntax/추가 smoke는 계속 실행하지 않는다.

## upstream 상태 갱신

2026-10-16 GitHub API의 `merged`·`mergeCommit`을 확인했다. 이전 보고서의 당시 open/proposal 표시는 이력으로 보존하며 현재 채택 근거에서는 아래 상태를 사용한다.

| claude-mem 항목 | 현재 상태·고정 merge | 해결 원인과 검증 방법 |
|---|---|---|
| [#4626](https://github.com/thedotmack/claude-mem/pull/4626) remote spool | merged, `29685038be31fd8a972e7809de2d5da158a518e5` | lost ACK receipt·영구 거절 quarantine·전송 중 교체 보존·늦은 event 후속 flush. trusted network 전제까지 구분 |
| [#4792](https://github.com/thedotmack/claude-mem/pull/4792) Codex teardown | merged, `2f820dad30a1163d8a12904ff789994a8de34af1` | generation 무효화 뒤 자식 종료 전에 private runtime을 지우던 순서. TERM 때 state를 쓰는 자식으로 검증 |
| [#4794](https://github.com/thedotmack/claude-mem/pull/4794) silent worker | merged, `8009b0dab718c7ab97ab66fc687e6260215733e3` | 응답 지연만으로 살아 있는 worker를 회수하지 않도록 bounded heartbeat 대조. 우리에게 자동 kill을 도입할 근거는 아님 |
| [#4783](https://github.com/thedotmack/claude-mem/pull/4783) 사용자 hook 보존 | merged, `8678203f0bd63b2da824716357330941eaff7be9` | installer/uninstaller가 foreign hooks를 덮거나 제거하는 경계. 기존 사용자 entry 보존 회귀 |
| [#4798](https://github.com/thedotmack/claude-mem/pull/4798) spool test identity | merged, `b8fc2ef9bab0dd1438d6cc8699c6884445ad409b` | checkout과 다른 worker build로 검증하던 문제. 소비한 package/worker identity 고정 |
| [#4690](https://github.com/thedotmack/claude-mem/pull/4690) quota restart orphan | **open/unmerged** | 재시작 orphan 복구 제안. merged 해결이나 우리 적용으로 세지 않음 |

## 추가 적용한 세 가지 수정

### 1. 삭제 floor 재조정의 무변경 UPDATE 억제

**문제:** 새 purge 때 이미 scrub된 모든 과거 row와 변하지 않은 `legacy_revalidation` pending을 다시 UPDATE했다. PostgreSQL의 동일 값 UPDATE도 새 tuple을 만든다. global clock 권한 lock 아래 실행하므로 불필요한 WAL·dead tuple·lock 점유가 늘어난다. 실제 production 증가율·지연은 측정하지 않았다.

**근거:** Hindsight [#5630](https://github.com/vectorize-io/hindsight/pull/5630), 원인 [#5614](https://github.com/vectorize-io/hindsight/issues/5614), merge `f74ace549de5f984348e8ae195c34ba53587d54e`. 동일 문서 재전송 시 `updated_at` 불변을 확인하는 regression/system story가 있다. Quivr [#3929](https://github.com/The-Vibe-Company/quivr/pull/3929)의 [고정 retention 구현](https://github.com/The-Vibe-Company/quivr/blob/1f72133e27e1cc0a7a05fb35a93df0f9e33136c4/internal/adapters/postgres/history_retention.go#L21-L177)은 이미 compact된 body/evidence를 guard로 제외한다. [PostgreSQL18 문서](https://www.postgresql.org/docs/18/functions-trigger.html)는 redundant UPDATE의 물리적 효과를 설명한다.

**결정:** `store.py:_scrub_purge_floors`에 assigned field의 null-safe `IS DISTINCT FROM` 조건을 추가했다. 기존 target의 OR는 괄호 안에 보존한다. `_apply_floors`의 eligible source/claim 배열과 desired state를 CTE로 계산하고 달라진 row만 쓴다. `WITH ORDINALITY`로 원래 배열 순서를 유지한다. 새 trigger/migration·retention·삭제 journal pruning은 추가하지 않았다. retracted operation의 epoch 갱신·global clock·deletion head 의미는 바꾸지 않았다.

**회귀:** `tests/test_purge_reconcile_churn.py`는 실제 PG에서 A purge 후 `xmin/ctid`를 기록하고 B purge/reconcile 뒤 A와 무관 pending의 row version 불변, B scrub, eligible 배열 순서·held/retracted 전환을 검사한다. restore된 private payload가 다시 생긴 경우에는 **변경 guard가 반드시 재-scrub을 허용**하는지도 확인한다. row 불변만 확인해 삭제 복구를 깨뜨리는 최적화를 막는다. 후속8aa611b의 전체 source suite에서 이 파일5건이 통과했다. 해당 파일은 설치 wheel subset에는 포함되지 않으며 그 실행으로 확대하지 않는다.

### 2. 생성 native hook/MCP의 Python import 격리

**문제:** project CWD나 상속 `PYTHONPATH`의 `agents_memory.py`·동명 package·`json.py`가 생성된 `python -m agents_memory.cli`보다 먼저 로드될 수 있었다. 이는 단순 dependency 누락뿐 아니라 hook/stdio 시작 전 임의 코드 실행 경계다.

**근거:** claude-mem [#4766](https://github.com/thedotmack/claude-mem/pull/4766)의 [고정 resolver](https://github.com/thedotmack/claude-mem/blob/7b9a58ae558e9607f40a3b59a747d4cd75548774/src/build/hook-shell-template.ts)와 distribution 회귀는 잘못된 host root의 dependency 선택 문제를 다룬다. [#4771](https://github.com/thedotmack/claude-mem/pull/4771)은 committed bundle 소비를 검증한다. Python의 [`-I`](https://docs.python.org/3/using/cmdline.html#cmdoption-I)는 unsafe project path·`PYTHON*` 환경·user site를 배제한다. upstream JavaScript resolver를 복사하지 않았다.

**결정:** `hosts.py:_command`가 세 host의 hook과 MCP 모두에 `sys.executable -I -m agents_memory.cli`를 생성한다. Claude의 명시 `CLAUDE_CONFIG_DIR` 전달은 유지한다. adapter를6으로 올렸고, v5 receipt는 검증한 **owned cleanup-only** 경로로 읽어 기존 entry 제거·명시 재설치·pending spool 보존을 허용한다. old receipt 수정·새 alias·구형 active 실행 fallback은 없다. live 설치 환경을 덮어쓰지 않고 runbook의 owned uninstall→새 stable package→재등록 순서를 따른다.

**회귀:** `tests/test_host_import_isolation.py`는 Claude/Codex/OMP의 **실제 생성 command**를 불신 project CWD/PYTHONPATH와 module/package/stdlib shadow 아래 실행한다. 악성 sentinel 부재와 실제 stdio/hook 응답을 함께 관측한다. v5 local/remote·삭제된 project의 정리/재설치가 private pending을 보존하는지도 확인한다. `.github/ci/wheel-consumer.py`는 frozen dependency 환경의 editable app을 실제 build wheel로 교체하고 새 `-I` process에서 소비한다. 후속8aa611b에서 이 파일30건은 전체 source와 설치 wheel 양쪽 모두 통과했다. 이는 **CI용 online dependency 준비 환경**이며 offline 전체 closure·native hook 활성 증명이 아니다.

### 3. lifespan 전에 listen socket 확보

**문제:** locked uvicorn0.54의 startup 순서는 lifespan→bind다. 같은 port가 점유돼도 우리 lifespan은 먼저 DB/journal reconcile·judge/scheduler/recovery를 시작할 수 있었다. launchd의 비정상 종료 KeepAlive는 이 불필요한 시작을 반복할 수 있다.

**근거:** claude-mem [#4299](https://github.com/thedotmack/claude-mem/pull/4299), merge `c2fd7f68f98d8a68f19d9274b1b070f0e3eb8f4a`. EACCES/EADDRNOTAVAIL을 duplicate worker 성공으로 오분류하던 문제를 실제 TEST-NET-1 daemon boot와 typed failure로 구분했다. 우리 해결은 동일 코드 이식이 아니라 기존 IPv4 listen 계약의 순서 수정이다.

**결정:** `cli.py:execute`의 `serve/service-run`이 configured address에 socket을 bind/listen한 뒤 `server.serve(sockets=[listener])`에 넘긴다. 실패는 errno를 보존한 `SERVICE_BIND_FAILED/not_started`다. 임의 port fallback·기존 listener kill·설정 변경은 하지 않는다. context가 실패/종료 시 socket을 닫는다.

**회귀:** `tests/test_cli_bind.py`는 실제 CLI subprocess에서 점유 port+접속 불가능 DB로 **DB/journal/state 작업 전 typed 거절**을 확인한다. 별도 실제 PG fixture는 같은 prebound CLI의 DB-inclusive `/readyz`와 종료 뒤 port 회수를 확인한다. 후속8aa611b에서 파일2건은 전체 source suite에서 통과했고, 첫 negative1건은 실제 설치 wheel에서도 통과했다. PG positive까지 설치 subset에서 실행했다고 세지 않는다.

## 이미 반영된 메커니즘과 이번 검증 공백

| 영역 | upstream의 해결·반례 | 우리 계약·결정 |
|---|---|---|
| lost ACK·전송 중 교체 | claude-mem #4626/#4798 | spool key+digest+payload 비교·receipt·unknown 유지·single flush owner는 기존 구현. 테스트 identity는 source/wheel hash로 고정 |
| 실패 outbox 뒤 정상 유입 | 영구/일시 실패를 전체 drain 중단과 혼동 | recovery는 stop/budget/readiness 실패 때 미처리 batch를 보존. 실제 TLS의 bad-first AUTH_DENIED→retained healthy 전송·backoff 회귀3건이 후속8aa611b의 전체 source/실제 설치 wheel에서 통과 |
| 원격 중단 | socket cancel을 이미 보낸 mutation 취소로 오인 | pending TCP/TLS/GET·최초 send 전 stop은 not_started. 이미 보낸 business는 원래 deadline으로 응답 drain, 재전송 없음. socket/TLS/DNS 회귀7건은 전체 source에서 통과했고 선택된 실제 TLS stop/drain3건만 설치 wheel에서 통과 |
| child teardown | #4792와 [#4674](https://github.com/thedotmack/claude-mem/pull/4674)의 중간 cleanup 실패 | bounded process-group TERM/KILL·wait, lifespan `AsyncExitStack`/최종 Store close는 기존 구현. setsid 탈출 자식의 완전 containment 증거는 없음 |
| 사용자 설정 보존 | #4783·malformed/symlink 설정 덮어쓰기 | receipt-owned entry만 제거, malformed/ownership drift fail-closed. foreign native/Agent Flow/trust 유지. BOM 호환을 위해 parser를 완화하지 않음 |
| 삭제·anti-resurrection | [doobidoo #1522](https://github.com/doobidoo/mcp-memory-service/issues/1522)의 identity 경계 | origin/lineage floor·독립 journal·transaction별 barrier는 기존 구현. purge는 모든 미래 동일 본문의 blacklist나 media erase가 아님 |
| intent/effect·bounded cleanup | crash 후 completion marker·무한 foreground cleanup | durable intent와 effect 구분, bounded cursor/`more`, expired payload 제거 후 digest/key 유지. 새 자동 삭제/승격 정책 없음 |
| OMP/host capture | session switch·branch·compaction·큰 event | per-session/generation 상태·bounded child/output·명시 gap 유지. circuit breaker로 실패를 조용히 생략하지 않음 |

## 평가 방법: 채택한 계약과 채택하지 않은 점수

실제 eval/trial harness·human gold120·고정60 task×3 실행 자료는 아직 없다. 아래는 [architecture의 평가 무결성 계약](../architecture.ko.md#평가-기록의-무결성)에 반영했으며 수행 결과를 만들지 않았다.

| 단계 | 실제 판정 단위 | 근거·반례와 결정 |
|---|---|---|
| candidate retrieval | admission manifest의 exact claim ID, required/forbidden 집합, Recall@20·feasible coverage | [agent-memory-benchmark 고정 scorer](https://github.com/vectorize-io/agent-memory-benchmark/blob/aef3702e0586a959c845cc2c61f10d5e8ff0f94a/src/memory_bench/dataset/precisionmembench.py)는 empty 기대가 많은 데이터의 always-empty accuracy와 oracle 치환을 경고한다. fuzzy match를 정확 일치로 세지 않음 |
| agent 판단 | 전체 manifest relevance·remember/discard·condition/exception/polarity·abstention·R04 | 후보 hit와 agent의 정확한 선택은 별개. [memharness](https://github.com/las7/memharness)의 any-gold hit를 set recall로 이름 바꾸거나 old+new 동시 반환을 정정 성공으로 세지 않음 |
| 후속 coding task | 실제 최종 artifact·허용 diff·불변 영역·과제 verifier, on/off 전체 attempt | claude-mem [고정 trace 분석/불완전 run 검출](https://github.com/thedotmack/claude-mem/blob/fef3402e674bebbf72a23aeb735e91c92cd34afd/scripts/eval-read-gate.ts#L245-L519). tool-use/result ID의 시도·deny·success·unknown을 분리. 미시도/미완료를 성공으로 세지 않음 |

- **고정 identity:** source/wheel·harness/verifier·corpus/gold/task·model/host·prompt/budget/seed·도구/권한·egress/native memory 조건을 묶고 resume mismatch는 새 run으로 분리한다. Redis의 [고정 `_prepare_run`](https://github.com/redis/agent-memory-server/blob/94192c39e2a4a154f441a5411e3d73c4f54974a6/agent-memory-benchmark/src/agent_memory_benchmark/benchmark/runner.py#L113-L153)을 참고하되 dataset/harness 누락까지 보완한다.
- **분모와 실패:** 180 pair의 전체 attempt가 primary 분모다. busy/error/timeout/fallback/비교 불가를 버리지 않고 사전 고정 이유로 실패 또는 미완료를 보고한다. valid subset은 별도 진단만 허용한다. [IWE #5의 remediation row 혼합](https://github.com/iwe-org/skills/issues/5#issuecomment-5224089645)처럼 다른 run의 좋은 행으로 교체하지 않는다. 허가된 retry 조건/cap은 freeze하고 기본0이다.
- **verifier 대조군:** [IWE 고정 eval](https://github.com/iwe-org/skills/blob/e3908762d5fa661fcba41d836d5fcb75dba4cebc/evals/harbor/README.md)의 oracle1/no-op0, 실제 source byte/revision gold anchor를 확인한다. [locomo-audit](https://github.com/dial481/locomo-audit/blob/9493fb4b4af4256ed17a18e8fd0b3cfdeec29539/README.md)의 plausible-wrong·answerable abstention gold 반례도 사용한다. 인간 gold를 모델이 대신 만들어 완료 처리하지 않는다.
- **최종 부작용:** 새 숫자 regex 존재만으로 성공 처리하지 않는다. 허용 diff 외 파일·기존 내용 보존, 실제 action 시도·동일 ID deny·금지 부작용0을 함께 확인한다. [claude-mem edit grader](https://github.com/thedotmack/claude-mem/blob/fef3402e674bebbf72a23aeb735e91c92cd34afd/evals/read-gate/gate-on-edits-file/graders/edited.md)만으로 whole-file rewrite/truncation은 걸러지지 않는다.
- **오염·비용·불확실성:** native memory 잔존·실제 HOME·same UID의 약한 격리·arm 간 이력을 기록한다. unknown 비용은0이 아니다. 기존90%/80%·cluster bootstrap 합격 문턱은 바꾸지 않으며 소규모 언어/업무군 결과에는 불확실성을 병기한다.

## 보류·거절: 위험을 숨기지 않는 경계

| 후보 | 반례·위험 | 결정·필요한 acceptance |
|---|---|---|
| loopback server identity | **[INFERENCE, 공격 미실행]** 다른 OS 사용자가 public readyz의 deployment/realm을 읽고 원래 port를 먼저 점유하면, 같은 문자열 echo 뒤 bearer/source를 받을 수 있다. ingress의 loopback peer 검사는 outbound 서버 인증이 아님 | **보안 설계 보류.** public echo/liveness token을 암호학적 인증이라고 하지 않음. peer credential 가능한 transport 또는 별도 서버 인증·배포 호환 설계가 필요. 실제 cross-user negative/정상 consumer positive를 별도 승인 범위에서 검증해야 함 |
| 전체 journal replay/global lock | Hindsight [#3539](https://github.com/vectorize-io/hindsight/pull/3539)는 foreground stall을 다루지만, OpenViking [#5940](https://github.com/volcengine/OpenViking/pull/5940)의 watermark pruning을 삭제 권한 journal에 적용하면 rollback 뒤 부활 위험 | **측정 후 설계.** full-history 비용을 아직 측정하지 않았으며 journal/head·operation epoch를 줄이거나 cache로 barrier를 생략하지 않음 |
| exact identifier decoy flood | **[INFERENCE, 미실행]** lexical 확장 `Foo_v2→Foo`와 원래 `Foo`가 동점이고 claim UUID tie-break로 top20에서 진짜 후보가 밀릴 수 있음. 검색 함수에는 원래 토큰과 확장 토큰의 provenance 구분이 없음 | **ranking 변경 보류.** blind token weight·새 embedding engine을 넣지 않음. independent exact-ID required/forbidden gold와 decoy corpus, token provenance 계약을 먼저 고정. 현재 Recall@20 보장을 주장하지 않음 |
| network filesystem WAL guard | Engram [#1364](https://github.com/Gentleman-Programming/engram/pull/1364)는 NFS/SMB를 생성 전 거절. Python stdlib에는 동일 filesystem-name API가 없음 | local disk/WAL/flock 전제 유지. 새 ctypes/FFI·OS classifier는 별도 설계. unknown filesystem을 local로 표시하지 않음 |
| 자동 heartbeat reclaim/watchdog | #4794의 liveness는 공격자 인증도 아니고 느린 journal transaction의 안전한 kill 증거도 아님 | live authority kill·`kickstart -k`·전역 `pkill` 거절. owned exact process의 정상 stop/cleanup만 유지 |
| SKIP LOCKED/새 worker concurrency | 모든 write가 이미 `am_clock FOR UPDATE`에서 직렬화됨 | 새 lock ordering·권한 경계 변경 없이 이식하지 않음. 단순 추가로 global serialization을 해결했다고 주장하지 않음 |
| retention/자동 승격/원문 재수집 | 삭제 journal·unknown receipt·검토 거절 이력은 일반 cache가 아님. transcript 자동 import는 새 저장·처리 권한을 요구 | 새 retention 삭제·health subsystem·자동 audit/승격·telemetry·원문 이동·모델 egress를 켜지 않음 |
| upstream eval 점수/코드 복사 | forgiving judge·empty accuracy·이름만 recall·run 혼합·실패 분모 제거·불명 라이선스 | 점수 전이·부풀림·verifier oracle 치환 거절. locomo/LoCoMo의 CC-BY-NC, zep 자료의 CC-BY-NC-SA 및 license 불확명 코드/데이터는 복사하지 않음 |

## 라이선스·검증·남은 승인

추가한 구현은 개념을 기존 코드에 적용한 것이며 upstream source/data를 vendoring하지 않았다. 조사 pin의 Hindsight/Quivr/Engram/IWE/LEANN은 MIT, claude-mem/memharness/Redis benchmark는 Apache-2.0으로 분류한다. repository 현재 main의 모든 전이 dependency/license를 새로 승인했다는 뜻은 아니다. `agent-memory-benchmark`의 repository license 불확명과 제한 데이터는 계속 제외한다. app의 MIT를 전체 SBOM·NOTICE·재배포 승인으로 확대하지 않는다.

`.github/workflows/ci.yml`은 실제 PostgreSQL18/pgvector≥0.8.7·지원 Python/SQLite·PG18 native 도구·age를 준비한 Linux4개 test shard와 별도 lint/build/wheel consumer, 병렬 Mac3.12 ownership compatibility job을 구성한다. checks도 owned PG prerequisite를 준비한다. Linux shard의 전체 sorted node ID 동일 collection, 결정적 hash partition, exact disjoint union, setup/call/teardown, skip/xfail/수집 오류0·source identity·upstream job 상태와 현재 canonical19 selector의 실제 설치 소비를 aggregate가 함께 요구한다. Mac은 별도 실제 runtime과 full collection에서 유도한 아홉 function의36개 node/phase·동일 source를 요구한다. exact ID와 parameter ID를 모두 인정하되 선언한 family의 누락은 거절한다. 누락/취소/timeout을 통과로 합산하지 않는다. credential이 섞일 수 있는 raw traceback/captured output은 JUnit artifact에 싣지 않고 outcome-only XML을 작성한다.

**후속 실제 실행:** 8aa611b의 [Actions38977685346](https://github.com/chonamdoo/agents-memory/actions/runs/38977685346)는 `complete:true`다. 전체 source와 별도 installed subset, 두 집계 회귀의 실패 전/성공 후 및 모든 원본 artifact의 범위는 [검증 기록](../verification.ko.md#정상-재개와-실제-설치-wheel-소비-범위-확대--8aa611b)에 고정했다. 초기 미실행 기록·이전 Opus timeout/다섯 skipped와 Sol request-changes는 지우거나 승인으로 바꾸지 않았다.

**독립 리뷰 후 소유권 수정:** 4ad185c의 실제12개 독립 결과 중 Sol state-integrity의 request-changes를 유지하고 정상 fix-loop에서 leader의 조기 reap을 제거했다. 잘못된 가상시계 fixture의 취소를 별도 보존한 뒤, 유효 실패 전 aa17661과 성공 후7df1eb4의 source/실제 설치 소비를 [소유권 전후 기록](../verification.ko.md#group-leader-소유권-보존--7df1eb4)에 고정했다. 운영 native consent나 kernel wraparound로 확대하지 않으며 MCP 흐름은 직접 Store capture와 두 MCP inspect/record·별도 HTTP producer 권한 거절로 구분한다.

**다음 독립 리뷰의 Mac 회귀와 지연 고지:** 592b648의 실제 완료11개(10approve/1request-changes)와 Opus types timeout/null을 구분했다. 일반 reviewer의 CPython3.12 Mac `waitid` 부재는 실제 Actions의8setup 실패로 재현했다. kqueue 적용 뒤6통과/2EPERM 실패도 보존하고 fault model의 가상 owned target을 바로잡았다. 최종92cc360의 실제 병렬 Mac/Linux/installed 성공과 Linux full-grace 비용은 [검증 기록](../verification.ko.md#macos-python-312-소유권-회귀--92cc360)에 고정했다. source helper 회귀를 native 활성·운영 OS maintenance나 실제 평가로 바꾸지 않는다.

**추가 primary source와 제품 진단 정정:** f2d5f6d의 다음 실제12완료/5approve/7request-changes/timeout0을 수용했다. fixture-only 진단은 불완전했으며 실제 Darwin 정상 inventory도 실패했다. 새로 읽은 [Apple XNU의 고정 kernel/libproc source](https://github.com/apple-oss-distributions/xnu/blob/xnu-11215.81.4/bsd/kern/proc_info.c#L357-L482)는 reap 없는 leader exit와 UID별 누락 없는 원자적 group census를 결합하는 근거다. [Apple adv_cmds의 ps 구현](https://github.com/apple-oss-distributions/adv_cmds/blob/main/ps/ps.c#L557-L638)도 조사했지만 비원자적 상태 목록은 채택하지 않았다. 이는 기존86개 분류를 삭제·재집계한 것이 아니며 Apple source를 복사/vendoring하거나 전체 license closure를 승인하지 않았다. 정상 제품 before4실패, 첫 수정의 Python3.12 kqueue 수명 TypeError8실패, 수정2656828의 실제 Mac16/Linux2451/별도 설치92 성공은 [제품 전후 기록](../verification.ko.md#darwin-정상-inventory와-terminal-권한-오류-구분--2656828)에 고정했다. 살아 있는 다른 member가 있거나 관찰이 불확실하면 PermissionError를 보존하며 실제 setuid/native 승인·운영/평가 증거로 대체하지 않는다.


**검증 코드의 소유권·FIFO 후속:** b4051bf의 실제12완료/9approve/3request-changes가 지적한 두 test finalizer도 같은 소유권 원칙으로 고쳤다. [CPython3.12.13의 개별 Popen signal](https://github.com/python/cpython/blob/v3.12.13/Lib/subprocess.py#L2145-L2186)은 poll 뒤 알려진 종료를 피하지만 외부·동시 reaper의 일반 안전성을 보장하지 않는다. 단독 wait 소유자와 private 자손 IPC에 한정해 공통 fixture를 사용한다. [POSIX FIFO open](https://pubs.opengroup.org/onlinepubs/9799919799/functions/open.html)의 nonblocking reader/writer와 [released XNU fifo_read](https://github.com/apple-oss-distributions/xnu/blob/xnu-11417.140.69/bsd/miscfs/fifofs/fifo_vnops.c#L319-L375)의 첫 EOF 뒤 readiness 해제도 대조했다. 실제 before의19개 teardown 실패와 별도 집계1실패, 첫 수정의 Mac EOF 재관측19실패·CI lint 실패를 보존한 뒤 read-first로 고친6b082a5의 실제 source2452/설치92/Mac36 성공은 [검증 기록](../verification.ko.md)에 고정했다. 이 추가 primary source를 기존86개 삭제·재집계나 vendoring/license closure로 바꾸지 않는다. test fixture를 실제 native 보호나 임의 평가 artifact의 보안 격리로 사용했다는 뜻도 아니다.

**판정·승인 경계:** 이 절 갱신 뒤의 최신 source 정상 독립 Opus/Sol review·QA/handoff와 PR 상태는 [PR9의 source/run별 기록](https://github.com/chonamdoo/agents-memory/pull/9)을 따른다. native trust/activation·실제 first-action·PMPA/semantic matrix·human gold/paired workload·macOS maintenance·stable0004 cutover·cloud/corpus 권한·전체 OS/ABI/offline/license·1–2주 trial·merge/release·귀속 미확인5volume 등 원래18개 acceptance는 별도 미해결이다. 이 조사·합성 회귀·코드 수정·CI 게시를 그 승인이나 실행으로 대체하지 않는다.
