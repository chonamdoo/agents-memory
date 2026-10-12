# 회사·외주용 로컬 설치와 독립 OSS 배포: 1차 출처 조사

조사일: 2026-10-11. 범위: 배포·운영·격리·offline·라이선스. 논문 품질/benchmark 및 #316·PR #334 최신 상태는 부모 조사에 맡긴다. 기존 `issue-316-cloud-memory.ko.md`의 공통 domain service·독립 업무/개인 배포 원칙을 보완한다.

**표기:** `[문서 사실]`은 아래 직접 읽은 공식 문서 또는 고정 source의 내용이다. `[INFERENCE]`는 그 사실에서 도출한 설계 판단이며 제품의 구현 보증이 아니다. `[미실측]`은 설치·공격·왕복·복구·성능 등을 수행하지 않았다는 뜻이다. 공식 웹 문서는 조사 시점의 가변 문서이고 고정 SHA source와 동일 release임을 보증하지 않는다.

## 1. 결론: 설치형과 MCP는 대체재가 아니다

- `[문서 사실, S1]` MCP는 host–client–server의 context/tool 연결 계약이다. stdio는 client가 server를 subprocess로 실행하며, Streamable HTTP는 여러 client를 처리할 수 있는 독립 process의 endpoint다. **local HTTP도 MCP**다. installer·container·daemon은 배포와 lifecycle을 소유한다.
- `[INFERENCE]` 이 요구에는 **독립 OSS memory service + 로컬 설치/Compose 패키지 + MCP adapter + 필요 시 일반 API/CLI/UI**가 자연스럽다. MCP를 없앨 필요도, MCP child 안에 DB·추출 worker를 넣을 필요도 없다. adapter가 두 번째 memory domain/권위 ledger가 되지 않도록 같은 service의 API를 호출한다.
- `[문서 사실, S1]` 전체 대화는 host에 남으며 MCP server가 전체 history를 읽도록 설계되지 않았다. `[INFERENCE]` **MCP 등록 성공≠자동 수집 완성**이다. 승인된 host hook/plugin/export collector가 source를 전달하고, service가 자동 추출·embedding·회상·reflect·정정/철회를 처리해야 한다. 이를 수동 `retain`만 제공하는 제품으로 축소하지 않는다.
- `[INFERENCE]` **공통 code/domain/schema/정정·철회 계약**과 **실제 데이터·identity·추론 endpoint·host context·backup의 독립성**은 함께 달성할 수 있다. 회사/고객 corpus를 개인 cloud로 동기화하거나 업무 장애 시 개인 endpoint로 fallback하지 않는다.

## 2. stdio child와 durable service의 수명

| 옵션 | 장점 | 단점·핵심 반례 | 최소 지원요건 `[INFERENCE]` |
|---|---|---|---|
| session child stdio에 engine/worker/embedded DB 모두 포함 | 단일 사용자 개발 onboarding이 간단함; session과 tool process 수명이 명료 | host 종료가 ingestion/reflect worker 종료로 이어질 수 있음. 여러 host가 같은 data directory를 열거나 각자 별도 engine을 시작할 수 있음. 디스크 존속과 작업 지속은 별개 | 단일 process/DB lock, 종료·재시작·중단 작업 복구 계약, 백업/지원 platform 명시. 업무 production 기본값으로 삼지 않음 |
| 독립 local HTTP MCP service + 외부 로컬 PG + supervised worker | 두 host가 같은 domain service 사용; ingestion/reflect가 session 밖에서도 지속; 배포/DB 교체 분리 | port·auth·Origin·서비스 운영 부담. 단순 loopback만으로 다른 사용자/프로세스 접근이 막히지 않음 | supervisor/Compose, 범위별 auth/ACL, loopback/Origin 검사, 영속 queue/operation, lease·중복 처리·복구, backup |
| 독립 service + 얇은 stdio shim | stdio-only host 지원; HTTP service의 durable lifecycle 유지 | shim 버전·credential·오류/취소 변환 지원이 추가됨. localhost endpoint를 잘못 선택하면 고객 경계가 바뀜 | shim은 DB/worker owner가 아님; 명시적 고정 endpoint·scope·token, 연결 실패 표시, operation receipt/ID 전달 |
| 일반 API/CLI/UI만 제공 | 비-agent 앱·bulk 작업·관리/승인 UX에 좋음; MCP 호환성 관리가 필요 없음 | MCP host에는 별도 integration 필요. 일반 설치만으로 host history 자동 수집/회상이 되지 않음 | 동일 domain API/ACL·source/정정/철회 계약. agent 연결이 필요하면 MCP를 추가하면 됨 |

`[문서 사실, S1]` stdio shutdown은 stdin 닫기→exit 기다리기→필요 시 강제 종료이며, server는 EOF에 신속히 exit하는 것이 권고된다. 2026-07-28 spec은 예상치 못한 종료 후 client restart/retry를 권고하지만 **application side effect의 exactly-once를 제공하지 않는다**.

`[INFERENCE]` 예: DB에 write가 commit된 직후 child가 응답 전에 죽으면 재시도 write가 중복될 수 있다. 반대로 메모리의 queue에만 있던 extract 작업은 종료 시 유실될 수 있다. 따라서 service는 수락을 영속화한 operation/outbox와 idempotency·lease/fencing·진행상태를 소유하고, transport request 취소와 이미 수락된 durable operation의 취소 정책을 구분해야 한다. DB가 child 밖에 있다는 사실만으로 worker 복구까지 구현되지는 않는다.

**프로토콜 revision 주의:** S1의 2026-07-28 HTTP는 GET stream과 protocol session을 제거한 revision이다. 기존 2025 initialize/session 기반 host가 자동 호환된다는 뜻이 아니다. 지원 host·transport·revision matrix를 고정해야 하며, 본 조사에서 협상은 실행하지 않았다.

## 3. Hindsight: 로컬 production, pg0, thin wrapper를 혼동하지 않기

### 3.1 공식 문서와 고정 source의 대조

- `[문서 사실, S7]` installation은 PostgreSQL 14+와 지원 vector extension을 요구하며, 기본 pg0는 개발에 편리하지만 **production에 비추천**이라고 명시한다. production에는 self-hosted 외부 PostgreSQL도 지원한다. 여기서 **external은 memory process 밖의 DB**라는 뜻이며 internet/managed를 뜻하지 않는다. 같은 회사 VM의 local PG도 가능하다.
- `[문서 사실, S7]` 현재 local MCP 안내는 `hindsight-local-mcp`가 전체 API를 `localhost:8888`에 띄우고 HTTP `/mcp/`로 연결한다고 설명한다. pg0의 데이터는 `~/.pg0/hindsight-mcp/`에 존속하고 startup migration을 실행한다. 고정 `a9eeed77…/mcp_local.py` 역시 `pg0://hindsight-mcp`를 `setdefault`한 뒤 **main API entrypoint를 호출할 뿐**이다. **현재 이 파일은 thin HTTP launch wrapper이지 stdio bridge가 아니다.**
- `[문서 사실, S7]` local MCP 문서의 “All data stays on your machine” 문구와 함께 **기본 LLM provider는 OpenAI**, 첫 시작은 embedding model 다운로드라고 쓰여 있다. installation의 full image는 embedding/reranker를 포함하지만 LLM은 별도 inference server/API에 의존하며 Docker에 llama.cpp를 포함하지 않는다. `[INFERENCE]` 이 privacy 문구를 default no-egress 증명으로 인용하면 안 된다. local LLM을 골라도 host LLM 및 다른 provider/telemetry/update 경로를 따로 다뤄야 한다.
- `[문서 사실, S7]` Docker 예시는 `latest`, `--pull always`, embedded pg0 volume을 쓰는 quickstart다. 업무용 pinned offline production recipe와는 다르다. 문서는 container hostname이 재시작 때 바뀌면 claimed task가 이전 worker ID에 남을 수 있어 안정적인 `HINDSIGHT_API_WORKER_ID`를 권고한다. dedicated workers의 StatefulSet도 이를 위한 stable identity를 제공한다. `[INFERENCE]` 같은 ID를 모든 worker replica에 복사하라는 뜻은 아니며 replica별 identity/복구 정책이 필요하다.
- `[문서 사실, S7]` 고정 tenant source에서 기본 extension은 noauth이고, 단순 API-key extension은 key를 검사한 뒤 모든 인증 요청에 같은 configured schema를 반환한다. **bank URL 선택이나 tag filter는 principal→bank 권한 검증의 대체물이 아니다.** 현재 문서가 per-bank endpoint의 isolation을 홍보하더라도, endpoint 선택 제약과 인증된 고객 ACL을 같은 것으로 읽지 않는다.

### 3.2 실제 thin stdio adapter 사례 — local wrapper≠local engine

`[문서 사실, S8]` 공식 `mem0ai/mem0-mcp` 고정 `624024de…` source는 `MemoryClient(api_key=…)`를 만들고 tool에서 `client.add/search/...`를 호출하며 main은 `server.run(transport="stdio")`다. README도 **Mem0 Memory API wrapper**라고 명시한다. **host가 child stdio adapter를 실행해도 durable engine/API는 그 child와 별개의 system**이라는 실례다. 동시에 “local stdio 설치”가 “local/no-egress backend”를 뜻하지 않는 반례다.

이 저장소의 고정 README는 archived/no longer maintained와 공식 cloud-hosted MCP로의 이동을 명시한다. **구조 설명용 사례일 뿐 새 업무용 제품 추천이 아니다.** 또한 해당 source의 HTTP 설정은 `0.0.0.0` 및 DNS-rebinding protection disabled를 포함한다. 그러므로 이 예제를 그대로 production 보안 recipe로 복사하지 않는다. user-ID 기본 filter도 사용자 인증/권한 증명으로 취급하지 않는다.

## 4. Docker/Compose의 책임과 빠진 책임

### 4.1 Data volume, healthcheck, shutdown

- `[문서 사실, S2]` Compose는 dependency order로 시작/종료하지만 container가 **running**이라고 해서 준비되었다고 기다리지 않는다. `depends_on: condition: service_healthy`가 지정되면 dependency healthcheck 통과를 기다린다. migration의 one-shot 완료에는 `service_completed_successfully` 조건이 있다.
- `[INFERENCE]` `pg_isready`는 DB connection readiness의 한 신호이지 app schema version·vector extension·operation queue·모델 준비·전체 retain→recall→reflect 정상의 증명이 아니다. liveness, DB/model dependency readiness, background task 진행/오류를 별도로 설명해야 한다. healthcheck 하나가 HA·자동 복구·백업을 제공한다고 약속하지 않는다.
- `[문서 사실, S2]` `depends_on.restart: true` 예시는 **명시적인 Compose update/restart 작업** 후 dependent를 재시작하도록 한다. 이를 모든 runtime failure의 자동 dependent restart 보장으로 확대하지 않는다.
- `[문서 사실, S2]` 기본 `docker compose down`은 container/network를 제거하지만 named volume은 남는다. **`down -v`는 Compose에 선언된 named volume 및 붙은 anonymous volume을 제거**한다. external volume/network는 제거하지 않는다. anonymous volume은 다음 `up`에 안정적으로 재연결되지 않으므로 persistent data는 named volume/명시적 bind path를 쓴다.
- `[INFERENCE]` 영속 volume은 **container 교체 생존**을 위한 것이며, disk 고장·host 분실·잘못된 삭제·암호화키 분실에 대한 backup이 아니다. uninstall은 기본적으로 service/config만 해제하고 데이터 파기는 별도 명시적 행위로 구분해야 한다. encrypted 고객별 backup과 restore 절차가 필요하다.
- `[문서 사실, S7]` Hindsight Docker는 UID 1000으로 실행하며 bind mount는 맞는 소유권이 필요하다고 안내한다. `[INFERENCE]` 고객의 기존 디렉터리를 installer가 광범위하게 `chown -R`하는 방식보다 전용 path/volume을 명확하게 소유하는 방식이 안전하다.

### 4.2 Upgrade와 rollback은 세 층이다

1. **artifact rollback:** 승인된 이전 image/package/model을 다시 선택한다. S3의 digest 고정은 불변 artifact 선택을 도와준다.
2. **application/schema rollback:** 이전 API/worker가 새 schema, operation payload, embedding revision을 읽을 수 있는지 별개다. startup migration으로 column을 없애거나 queue format을 바꿨다면 image만 되돌리는 것은 복구가 아니다. `[INFERENCE]`
3. **DB engine/extension 복구:** `[문서 사실, S4]` `pg_upgrade`는 이후 major로의 upgrade 도구이며 extension binary 호환성이 필요하다. `--link` 후 새 cluster를 시작하면 옛 cluster를 다시 사용할 수 없다고 경고한다. `pg_dump`도 이전 major에 restore가 된다고 보장하지 않는다.

`[INFERENCE]` 그래서 **서명된 업데이트≠되돌릴 수 있는 업데이트**다. 서명은 artifact 출처/무결성에 관한 것이고 데이터 변환의 가역성은 증명하지 않는다. release manifest에 app–schema–PG–extension–model 호환 범위, backup/restore 경로, downtime/write pause와 RPO/RTO, rollback 불가 migration을 적어야 한다. downgrade보다 **업데이트 전 일관된 backup을 지원되는 옛 stack에 restore**하는 방식이 명료할 수 있다. 업데이트 이후 새 write를 잃는다면 이를 복구 성공으로 감추지 않는다. restore 후 철회 tombstone/deletion epoch까지 반영하지 않으면 이미 삭제된 자료를 부활시킬 수 있다.

`[미실측]` Hindsight의 특정 release migration의 역방향 안전성, backup consistency, stuck operation recovery, 실제 RPO/RTO는 검증하지 않았다.

## 5. PostgreSQL/pgvector local+managed: 공통 의미와 운영 차이

- `[문서 사실, S5]` pgvector는 PostgreSQL extension이며 DB마다 `CREATE EXTENSION vector`가 필요하다. 별도 cloud vector service가 아니다. vectors를 일반 data와 같이 저장하고 ACID/PITR/JOIN 등 PG 기능을 사용할 수 있다. 이 기능이 회사의 PITR 설정을 자동 완성한다는 뜻은 아니다.
- `[문서 사실, S5/S6]` 읽은 pgvector 고정 README는 v0.8.7 설치를 안내하지만 Cloud SQL 문서의 PG 13+ supported pgvector는 0.8.5다. Cloud SQL은 허용된 extension만 지원하며 사용자 정의 extension을 만들 수 없다. underlying binary maintenance 후에도 DB catalog의 `ALTER EXTENSION ... UPDATE`는 운영자 책임이다. **같은 “PostgreSQL+pgvector” 표기만으로 version/DDL/검색 동작 동일성을 보장하지 않는다.**
- `[INFERENCE]` 공통 domain release는 양쪽에서 지원하는 PG major·extension version/operator/index·migration·collation/tokenizer·embedding dimension/revision 범위를 선언해야 한다. managed에 없는 custom lexical extension을 local 기본값으로 고른다면 두 배포의 parity가 깨질 수 있다. 작은 corpus의 exact 검색과 ANN 전환/필터링은 별도 측정 대상이며, 이 조사에서 검색 품질을 재평가하지 않는다.
- `[INFERENCE]` self-host local은 DB 설치·patch·disk·backup·복구·접근통제를 운영자가 소유하고 data residency/no-egress를 통제하기 쉽다. managed는 실제 상품의 maintenance·backup·접속 경계를 이용할 수 있지만 허용 extension·권한·region·망 경로·운영 비용의 제약이 생긴다. **managed PG는 개인 cloud의 DB 선택지이지 회사 strict offline의 대체물이 아니다.** common schema가 customer/personal 데이터를 한 DB로 합치라는 뜻도 아니다.

## 6. Offline / no-egress / artifact supply chain

`[INFERENCE]` 세 표현을 분리한다. **local storage**는 DB 위치, **offline-capable**은 반입된 모든 artifact로 외부 연결 없이 기능 수행 가능, **no-egress**는 승인되지 않은 outbound 전송을 정책과 경계로 차단하는 운영 속성이다. 하나에서 다른 하나가 자동으로 따라오지 않는다.

### 최소한의 반입·배포 계약

- `[문서 사실, S3]` Docker는 tag 대신 digest로 image를 고정할 수 있다. 고정하면 security update도 자동 반영하지 않으므로 digest 갱신/승인이 필요하다. `docker image save`는 로컬 store에 있는 platform image/layers를 archive로 내보내고 `load`에 사용할 수 있다. **없는 architecture variant는 archive에 자동 생기지 않는다.**
- `[문서 사실, S7]` Hindsight는 published image의 Cosign keyless OIDC 서명 및 certificate identity/issuer를 지정한 verify 예시를 제공한다. `[INFERENCE]` downloader만 아니라 **staging에서 승인한 signer/issuer·정확한 digest·release manifest를 검증하는 절차**가 필요하다. signature가 존재한다는 설명만으로 이번 binary를 검증했다고 말하지 않는다. air-gap 검증은 필요한 trust material/verification evidence를 사전 반입하는 별도 절차이며 이 조사에서 실행하지 않았다.
- `[INFERENCE]` offline bundle은 app/API/worker/DB/model runtime의 OS·arch별 image/package와 transitive dependencies, extension binaries, tokenizer/config/weights, inference engine, migration/config, license/NOTICE, digest·model revision·차원 manifest, 복구 가능한 이전 release까지 포함한다. 모델 **이름/tag만 고정**하면 weights/tokenizer drift를 막지 못한다. install/first run의 `uvx`/`npx @latest`/model download가 남으면 air-gap bundle이 아니다.
- `[문서 사실, S10]` HF `HF_HUB_OFFLINE=1`은 Hub HTTP call을 막고 cache가 없으면 error를 낸다. cache가 있어도 일반 `hf_hub_download`는 metadata HTTP 요청을 하므로 offline flag가 의미 있다. telemetry와 CLI update check에는 별도 `HF_HUB_DISABLE_TELEMETRY`/`HF_HUB_DISABLE_UPDATE_CHECK`가 문서화되어 있다.
- `[INFERENCE]` 이 flag는 HF library의 범위다. app의 LLM provider·reranker·OTEL·crash reporting·updater·DNS·다른 SDK 및 **agent host의 모델 호출**을 전부 차단하지 않는다. 특히 offline memory server가 회상한 고객 내용을 cloud-hosted Opus/Codex의 prompt로 넘기면 memory backend가 local이어도 고객 내용은 반출된다. **strict no-egress가 host를 포함한다면 host 모델도 local/허용된 사내 경로여야 한다.** 회사 SaaS 계정의 계약상 보호와 전송 금지는 다르다.
- `[INFERENCE]` 자동 수집→추출→embedding→rerank→reflect 전체를 local/허용 사내 inference로 구성하고 cloud fallback을 fail-closed로 막는다. 모델 불재·오프라인에서는 완료로 위장하지 않고 pending/blocked/failed 상태를 구분한다. 이를 수동 기록 제품으로 바꾸거나 reflect를 조용히 끄는 방식은 원래 요구의 충족이 아니다.
- `[INFERENCE]` outbound enforcement는 회사/고객 VM·network 정책에서 적용하며 연결을 차단한 상태의 실제 동작과 outbound 시도를 관측해야 한다. “완전 air-gap에서도 안전한 최신 업데이트”는 offline approval/freshness 절차 없이 보장하지 않는다. 이전에 서명된 취약 release의 재사용도 서명 자체가 막지 않는다.

## 7. 회사 계정·고객별 user/VM·localhost/Origin/auth의 경계

| 통제 | 막거나 줄이는 것 | 못 막는 것 / 운영 주의 |
|---|---|---|
| 회사 소유 SaaS 계정/credential | `[INFERENCE]` 개인 결제/소유권 의존, 퇴사 시 접근 회수 문제를 줄임 | no-egress·고객 간 ACL·개인 host session 혼합을 자동 해결하지 않음 |
| 고객별 host profile/config/session | `[INFERENCE]` 잘못된 endpoint·history·cache·tool 상속을 줄임 | 같은 OS user의 악성 process가 config/token/file을 읽는 것의 보안 경계는 아님 |
| 고객별 OS user/service credential·파일 권한 | `[INFERENCE]` 올바른 권한 설정 아래 다른 비특권 user의 파일 접근을 제한 | network loopback endpoint는 파일 권한만으로 user별 제한되지 않음. 동일 user/root·공유 home·공유 backup·과도한 group 권한은 별도 |
| 고객별 VM/workspace/network/storage/backup key | `[INFERENCE]` host history·DB·inference·egress 경계를 함께 나눌 수 있음 | host admin/hypervisor/backup admin은 별도 신뢰 경계. container만으로 같은 수준의 VM 격리가 된다고 주장하지 않음 |
| loopback bind / loopback-only published port | `[문서 사실, S1]` local server는 `127.0.0.1` bind가 권고됨. `[INFERENCE]` LAN/외부에서 직접 접근하는 surface를 줄임 | 다른 local user/process 및 브라우저 경유 DNS rebinding 방어가 자동 완성되지 않음. container 내부 bind와 host port publishing 모두 확인해야 함 |
| Origin 검증 | `[문서 사실, S1]` invalid Origin이 있으면 403; incoming Origin 검증은 DNS rebinding 방어를 위해 MUST | `[INFERENCE]` Origin을 위조/생략할 수 있는 비-browser client의 identity 검증이 아님; token/ACL 대체물이 아님 |
| auth + principal-bound customer/bank ACL | `[INFERENCE]` 미인증 및 권한 밖 요청을 거절; 고객 경계를 서버가 강제 | 탈취된 credential, 이미 host가 읽은 정보, root/file 직접 접근을 해결하지 못함. 하나의 shared API key+임의 bank ID는 고객별 ACL이 아님 |

`[INFERENCE]` 외주에서는 고객 A와 B마다 독립 user 또는 VM, service endpoint/token, DB/volume, model 경로, collection allowlist, log/export/backup key·retention을 지정한다. 개인 cloud에는 개인-owned corpus만 보낸다. **A 자료가 이미 들어간 동일 host conversation을 B/개인 mode로 전환해서 안전하다고 주장하지 않는다.** server ACL은 host context를 지우지 못한다. 하나의 회사 account를 모든 고객이 공유하는 것과 고객별 권한/격리를 명확히 구별한다.

## 8. Installer가 host config/AGENTS/hooks를 수정할 때의 ownership

`[문서 사실, S9]` Claude Code MCP의 local scope는 현재 project에만 적용되지만 실제 파일은 `~/.claude.json`이다. project scope는 `.mcp.json`, user scope는 같은 home 파일에서 전 project에 적용된다. “local”이라는 이름을 보고 repo-local 파일만 변경한다고 판단하면 틀린다. hooks는 user/project/local/plugin/managed scope에서 merge되며 설정/plugin hooks는 subagent 안에서도 실행된다.

`[문서 사실, S9]` Codex는 global `~/.codex/AGENTS.override.md`/`AGENTS.md` 및 project root→cwd chain을 읽고 실행 instructions에 합친다. `CODEX_HOME`으로 profile을 바꿀 수 있다. `[INFERENCE]` 설치기가 global AGENTS를 추가/덮어쓰면 고객 repo 밖의 agent 행동도 바뀔 수 있다. **소스 코드 0 변경≠실행 영향 0**이다.

권고 설치 계약 `[INFERENCE]`:

1. 기본 설치는 service/artifact/data path만 소유하고 host integration은 **별도 명시적 opt-in**으로 분리한다. 자동 수집을 제공하되 수집 source·scope·event·반출 경로를 공개하고 승인받는다. `.mcp.json`이나 hook에 credential을 version-control로 넣지 않는다.
2. 적용 전 변경 대상 host/profile/path, 추가할 entry/block, hook executable/endpoint와 권한을 보여준다. 기존 AGENTS 내용·MCP entry·hook 배열을 일괄 overwrite하지 않는다. managed organization policy와 충돌하면 우회하지 않고 실패를 표시한다.
3. installer manifest에 설치한 entry ID/path·이전 값·적용값 hash·artifact/version·owner를 기록한다. upgrade/uninstall은 **자신이 소유한 entry만**, 설치 후 사용자가 변경하지 않았다는 확인 조건으로 제거/복원한다. 파일 전체를 이전 backup으로 되돌리면 사용자의 후속 변경과 다른 도구 설정이 사라질 수 있다.
4. 부분 설치 실패는 host config 변경과 service 등록을 되돌릴 수 있어야 하지만, 수집되어 DB에 들어간 customer data의 purge/보존은 별도 정책이다. uninstall·credential revoke·DB wipe·backup purge를 한 행위로 뭉치지 않는다.
5. Agent Flow 같은 core-frozen runner와 author/reviewer에는 global opt-in을 기본 적용하지 않는다. 전용 profile/project opt-in을 쓰고 실제 tool catalog/context·자동 hook 상속을 확인한다. 새 연결·자동 주입이 core workflow의 행동을 바꾼다면 별도 변경 요청 사항이다.

## 9. 독립 OSS core와 라이선스의 실질 비용

`[INFERENCE]` **독립 OSS 제품**이라고 하려면 실행 가능한 memory core/domain API·schema/migrations·자동 추출/회상/reflect·worker·정정/철회 경로를 공개된 지원 build로 운영할 수 있어야 한다. 공개 MCP wrapper만 있고 engine은 proprietary hosted API라면 “wrapper OSS”이지 같은 OSS engine의 local+cloud 배포가 아니다. 모델 weights를 반드시 자체 repo에 포함해야 한다는 뜻은 아니며, 지원하는 local model/runtime의 반입 경로와 사용 조건을 명시해야 한다.

| 선택 | 원문에 있는 의무/보호 `[문서 사실, S11]` | 실제 비용·한계 `[INFERENCE]` |
|---|---|---|
| MIT | 사용·수정·배포·판매 허용; copies/substantial portions에 copyright+permission notice 포함; AS IS/보증·책임 제한 | notice 관리가 단순함. Apache §3 같은 **명시적 patent grant/termination 조항은 MIT 본문에 없음**; 이것을 특허 문제가 반드시 발생한다는 뜻으로 확대하지 않음 |
| Apache-2.0 | §3 contributor patent grant와 patent litigation 시 termination; §4 license 동봉, 변경 파일 표시, 관련 attribution 보존, upstream NOTICE가 있으면 관련 내용 전달; §6 trademark grant 아님; §7–9 보증/책임 | NOTICE·변경 표시·dependency attribution 운영 부담이 더 명시적. 특허 grant도 contributor의 해당 contribution 관련 범위이며 무제한 특허 면책이 아님 |

**둘 다 고객용 보안 인증·SLA·indemnity·규제 준수·모델/데이터 권리를 보장하지 않는다.** 회사/외주에 배포 가능한가의 판단은 core 하나가 아니라 dependencies·container base layers·모델/tokenizer·재배포 대상 artifact·고객 계약을 포함한다. 본 문서는 법률 자문이 아니다.

`[문서 사실, S12]` local MCP 예시의 `llama3.2`와 관련된 Meta의 Llama 3.2 license는 MIT/Apache와 별개다. 읽은 publisher `LICENSE.txt`는 redistribution/service에 Agreement 사본과 **“Built with Llama”**, 배포 copy의 Notice, Acceptable Use Policy 준수를 요구하며 별도 commercial threshold도 둔다. `[INFERENCE]` 따라서 MIT memory core를 내보낸다고 weights/runtime bundle도 같은 조건으로 자유 재배포되는 것은 아니다. 특정 고객의 model choice, weights·quantization/tokenizer의 정확한 revision과 upstream license를 반입 manifest에 넣고 **core license와 모델 license를 분리 표시**한다. 재배포를 피하고 고객이 모델을 따로 반입해도 실제 사용 조건 검토가 사라지지는 않는다.

`[INFERENCE]` 독자 core는 회사 특허/기여 정책이 명확하다면 Apache-2.0가 기업 도입 시 명시적 patent/notice 조건을 제공하는 선택이고, 단순 attribution 중심이면 MIT가 간단하다. 어느 쪽이든 이미 도입한 upstream의 의무를 지켜야 하며 core license 선택으로 upstream model/third-party 의무를 지울 수 없다. 모델 license 전문의 jurisdiction/AUP 등 모든 조항을 이 요약으로 대체하지 않는다.

## 10. 우선 검증할 세 반례

1. **“로컬 MCP 설치 = offline” 반례:** 기본 cloud LLM·첫 embedding download·호스트 Opus/Codex로 recall 내용 전송. 서버만 offline이라고 해도 고객 정보가 host 경로로 나갈 수 있다. 추출/embed/rerank/reflect와 host 전체 경계를 정하고 network-denied full pipeline이 pending/failed를 정확히 드러내는지 확인한다. `[문서 사실 S1/S7/S10 + INFERENCE; 미실측]`
2. **“stdio session child = durable service” 반례:** host 종료/강제 kill 후 in-flight extraction과 reflect 중단, write commit 후 응답 유실·retry 중복, stable worker identity 미설정으로 claimed 작업 고립. 독립 DB+worker lifecycle·영속 operation/idempotency·복구가 필요한 이유다. `[문서 사실 S1/S7/S8 + INFERENCE; 미실측]`
3. **“서명된 이전 image로 되돌리면 복구” 반례:** startup schema migration·PG major/extension 변화 후 옛 code가 새 data를 읽지 못함. backup restore는 업데이트 이후 write 손실이나 철회 자료 부활 문제를 만들 수 있음. artifact signature, schema compatibility, DB restore/deletion replay를 각각 검증한다. `[문서 사실 S3/S4/S7 + INFERENCE; 미실측]`

## 11. 읽은 1차 출처 — 12개 근거 묶음

같은 기관의 직접 관련 문서/고정 source를 함께 묶었다. 각 링크는 실제 읽은 페이지 또는 읽은 source의 GitHub 표현이다. mutable docs를 고정 SHA source와 동등한 snapshot 증거로 취급하지 않는다.

- **S1 MCP 공식 architecture/transport (2026-07-28):** [Architecture](https://modelcontextprotocol.io/specification/2026-07-28/architecture), [transport overview](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports), [stdio lifecycle](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/stdio), [Streamable HTTP security/revision](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http). 핵심: host history 소유권, child shutdown, independent HTTP, Origin/loopback/auth의 별도 요구.
- **S2 Docker/Compose lifecycle:** [startup/shutdown order](https://docs.docker.com/compose/how-tos/startup-order), [compose down/volume removal](https://docs.docker.com/reference/cli/docker/compose/down/). 핵심: running≠ready, dependency healthcheck/명시적 restart, `down -v` 데이터 위험.
- **S3 Docker artifact 고정/반입:** [pull by digest](https://docs.docker.com/reference/cli/docker/image/pull), [image save](https://docs.docker.com/reference/cli/docker/image/save/). 핵심: immutable digest와 patch 승인, platform별 archive 반입. archive export는 DB backup이 아님.
- **S4 PostgreSQL 공식 18 문서:** [pg_dump compatibility/roles/restore warning](https://www.postgresql.org/docs/18/app-pgdump.html), [pg_upgrade / old cluster reversion](https://www.postgresql.org/docs/18/pgupgrade.html). 핵심: downgrade 미보장, extension binary, link-mode 복구 제약.
- **S5 pgvector 고정 README `f37c13f…`:** [README](https://github.com/pgvector/pgvector/blob/f37c13f68b57d2c3472b2214fbcff699d6d34876/README.md). 핵심: PG extension/DB별 활성화, exact/ANN, v0.8.7 설치와 PG 기능 재사용.
- **S6 Cloud SQL 공식:** [Configure PostgreSQL extensions](https://docs.cloud.google.com/sql/docs/postgres/extensions). 핵심: supported extensions만, pgvector version 차이, binary/catalog update 책임 구분.
- **S7 Hindsight 공식 문서+고정 code `a9eeed77…`:** [Installation](https://hindsight.vectorize.io/developer/installation), [Local MCP](https://hindsight.vectorize.io/sdks/integrations/local-mcp), [MCP server/auth](https://hindsight.vectorize.io/developer/mcp-server), [HTTP local entrypoint](https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-api-slim/hindsight_api/mcp_local.py), [tenant source](https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-api-slim/hindsight_api/extensions/builtin/tenant.py). 핵심: production external PG, pg0 dev, local HTTP/default cloud provider, stable worker ID, Cosign 안내, routing≠ACL.
- **S8 Mem0 공식 archived wrapper 고정 `624024de…`:** [README/archive notice](https://github.com/mem0ai/mem0-mcp/blob/624024deacbbe1948572a968abdb9d9e93ded548/README.md), [server / MemoryClient / stdio main](https://github.com/mem0ai/mem0-mcp/blob/624024deacbbe1948572a968abdb9d9e93ded548/src/mem0_mcp_server/server.py). 핵심: thin local stdio wrapper가 external hosted engine을 호출하는 사례. 신규 채택 추천 아님.
- **S9 공식 host configuration:** [Claude MCP scopes](https://code.claude.com/docs/en/mcp), [Claude hooks scope/merge/subagent](https://code.claude.com/docs/en/hooks), [Codex AGENTS discovery](https://learn.chatgpt.com/docs/agent-configuration/agents-md) (OpenAI Developers 링크가 공식 Learn 문서로 redirect). 핵심: home/project 변경과 자동 실행/instructions의 blast radius.
- **S10 Hugging Face 공식 Hub:** [environment variables](https://huggingface.co/docs/huggingface_hub/en/package_reference/environment_variables). 핵심: offline cache miss error, 별도 telemetry/update flag, Hub 범위 제한.
- **S11 실제 license 원문:** [Hindsight 고정 MIT LICENSE](https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/LICENSE), [Apache-2.0 전문](https://www.apache.org/licenses/LICENSE-2.0.txt). 핵심: attribution·patent·NOTICE·변경 표시·AS IS. OSI MIT 페이지는 도구가 무관한 RSS를 반환하여 근거로 쓰지 않았다.
- **S12 Meta publisher model license:** [Llama-3.2-1B LICENSE.txt](https://huggingface.co/meta-llama/Llama-3.2-1B/blob/main/LICENSE.txt). 직접 읽은 publisher file 화면은 마지막 변경 `5f235f068eb9e95fc947b21a764f1869eb0e0361`을 표시한다. 해당 fixed raw URL은 401, llama.com 원래 URL은 redirect 후 404여서 **고정 raw 전문을 읽었다고 주장하지 않는다**. 핵심: Agreement/Built with Llama/Notice/AUP/별도 commercial 조건; 실제 선택 model의 계약은 재확인 필요.

## 12. 미실측 및 부모 hand-off

문서·고정 source를 읽고 이 조사 파일만 작성했다. 모델 설치/호출, 제품 실행, project 코드/host config 수정, 배포, GitHub 게시, build/lint/test/formatter는 수행하지 않았다. 아래는 실행 결과가 아니라 제품 채택 전 확인할 항목이다.

- 지원 OS/arch별 offline bundle 설치와 full 자동 memory pipeline; cold start/RAM/GPU/한국어 latency·quality.
- 두 host의 실제 MCP revision/auth 왕복, 잘못된 Origin/무토큰/다른 고객 bank·다른 OS user 접근 거부.
- host 종료·worker restart·응답 유실 후 중복 처리/operation 복구·삭제 중 stale worker 부활 방지.
- image/model 서명·digest 확인, 이전 stack restore, schema/PG/extension upgrade/rollback, backup의 철회 자료 재노출 방지.
- installer install/upgrade/uninstall의 partial failure·사용자 후속 설정 보존·author/reviewer 기본 미연결.

**최소 지원 공약 `[INFERENCE]`:** 공통 domain/schema/정정·철회 release matrix, supervised API/worker와 외부 로컬 PG, 명시적 고객 경계, complete offline inference/artifact 경로, non-destructive host opt-in installer, 소유권 기반 rollback/uninstall, backup/restore 및 license manifest. Kubernetes/HA/무중단 upgrade를 작은 local 설치의 필수로 강제할 필요는 없지만, 단일 host의 downtime·복구 책임을 숨기지 않는다.
