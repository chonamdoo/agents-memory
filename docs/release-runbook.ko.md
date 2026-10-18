# 설치·업그레이드·장애 복구 runbook

이슈 [#5 §5](https://github.com/chonamdoo/agents-memory/issues/5)의 운영 절차다. **절차 작성, 합성 실행, 운영 전환, 배포 승인은 서로 다른 완료 조건**이다. 현재 실행 범위·실패·공식 review/QA/handoff·trial 상태는 [검증 기록](verification.ko.md)을 따른다. 이 문서가 실제 corpus 이동·egress·native trust 변경·운영 중단·출시를 승인하지 않는다.

## 1. 작업 범위와 복구 자료를 먼저 고정

- 대상 deployment/realm·개인/회사 운영 주체·project binding·로컬/원격 역할을 기록한다. 이름·CWD·Git branch·키 보유로 다른 배포 권한을 추론하지 않는다.
- 명령의 `AM_BIN`은 삭제되지 않는 설치 환경의 **검증한 절대 console-entrypoint 경로**다. 운영 중 `uv run`으로 checkout을 재동기화하거나 기존 venv/package bytes를 덮어쓰지 않는다.
- `CONFIG`, operator/agent/producer token, DB·migrator DSN, age identity, Jev key와 서명 intent는 private 복구 자료다. 값은 argv·터미널 출력·Git·이슈·PR·release manifest에 넣지 않는다. 프로그램에는 private 파일 경로만 전달한다.
- 최종 encrypted archive와 별개로 **DB restore 밖의 최신 삭제 journal/head**를 보존한다. archive는 journal·native 설치 receipt·spool·전체 state directory의 백업이 아니다. 회사/개인 배포 자료를 혼합하지 않는다.
- 원래 config/서명 init intent·token·host/service ownership receipt·고정 executable/import root·CA/profile·현재 migration/restore fence를 보존한다. 미확정 intent·fence를 지워서 정상화하지 않는다.

## 2. 호환성과 패키지 반입

| 대상 | 지원 계약 | 검증·반입 경계 |
|---|---|---|
| Python | package metadata `>=3.12` | 최신 이전 profile 성공은 Python3.13.16/SQLite3.54.0. metadata 범위를 모든 Python/OS 실행 검증으로 해석하지 않음 |
| PC SQLite spool | `>=3.51.3` 또는 patched `3.50.7≤v<3.51.0`, `3.44.6≤v<3.45.0` | 영향 WAL runtime은 spool 생성 전 거절. Python 버전만 확인해서는 부족 |
| PostgreSQL | 18.x + pgvector≥0.8.7 | serve/migrate/backup/restore 공통 계약. migration은 해당 deployment의 migrator DSN·현재 operator로 수행 |
| PG 도구 | `pg_dump`·`pg_restore`·`psql` major18 | local은 검증한 절대 경로 세 개, docker는 명시한 owned endpoint/container. PATH 추측/자동 fallback 없음 |
| 암호화 | 지원 age 실행 파일·검토한 recipient/identity | archive 복구 가능성과 key 보관을 확인. recipient 목록이 같은 realm/corpus 저장 권한을 부여하지 않음 |
| macOS supervisor | per-user GUI login domain의 launchd | PG/Docker 자체 시작은 관리하지 않음. Linux/Windows의 service installer로 일반화하지 않음 |
| native host | 해당 설치 버전·지원 callback/tool | Codex/OMP 신규 strict와 과거 strict receipt의 active 실행은 거절. passive owned 정리·명시 advisory/MCP는 유지하며 native 보호와 구분 |
| 원격 연결 | 검증 HTTPS + 명시 identity/auth/binding/profile | PC는 DB/operator를 갖지 않음. PC service는 cloud server/DB를 관리하지 않음 |

구현 근거: `spool.py:require_supported_sqlite`, `database.py:require_server/require_tool`, `service.py`의 platform/executable/receipt 검증, `hosts.py:install_host`. 정확한 public 명령은 설치된 `--help`와 [README](../README.md)를 함께 확인한다.

### 반입 acceptance

다음 자료를 서로 묶어 검토한다. **현재 이 목록의 완성된 offline release bundle이 제공됐다는 뜻이 아니다.**

- 최종 source ref와 실제 작업트리 content identity. dirty source에서 base HEAD나 package version `0.1.0`만으로 built bytes를 식별하지 않는다.
- app wheel·대상 OS/architecture/Python ABI에 맞는 **전체 runtime dependency wheel closure**·lock/선택 marker·SHA-256 목록.
- 각 배포 dependency의 license/NOTICE·SBOM·compatibility manifest·이 runbook의 버전·검증 보고. app의 MIT를 모든 dependency license로 기입하지 않는다.
- 깨끗한 환경·비어 있는 cache·네트워크 없는 설치와 실제 CLI/MCP 소비 실행. warmed uv cache, wheel `--no-deps` 설치, 다른 target wheel의 존재는 이 증거가 아니다.
- Python/SQLite·PostgreSQL/pgvector·PG18 도구·age·선택한 container image는 별도 prerequisite다. Python wheelhouse만으로 OS/container까지 offline이라고 하지 않는다.
- sdist의 build backend도 반입·고정한다. 현재 `hatchling==1.32.4`이며 실제 target의 backend/frontend 전이 closure9개는 별도 hash manifest로 고정했다. app `uv.lock`만으로 build toolchain 전체를 식별하지 않는다.

개발용 `uv sync --locked`와 cloud Dockerfile의 apt/registry/uv sync는 dependency를 취득할 수 있는 **online 준비 경로**다. 이를 offline 설치 명령으로 재명명하지 않는다. source build·dependency acquisition은 별도 준비 환경에서 수행하며 모델·telemetry·Jev를 활성화하지 않는다.

개발 검증의 [GitHub Actions CI](../.github/workflows/ci.yml)는 별도 online prerequisite 준비 경로다. 실제 test·collection·lint/build·추가 smoke는 현재 지시에 따라 Actions에서만 수행한다. 이 CI의 dependency 설치나 Linux wheel 소비를 offline bundle·macOS native 활성·운영 cutover 증거로 세지 않는다.

### 이번 candidate에서 실제 준비한 Python 범위

직전 checkpoint의 Python43파일·SQLite3.54.0 기록과 후속 candidate를 구분한다. 최신 후속 candidate는 macOS arm64 / 공식 PBS CPython3.13.16 / SQLite3.53.1이다. Python archive·build 도구9 wheels·runtime34 wheels·새 app wheel을 hash로 묶고, OS network-deny 아래 새 환경에서 sdist/wheel build→hash 필수 전체 local 설치→`pip check`→설치 native-status를 실행했다.46 package source 파일이 일치하며 의존성 누락은 offline 실패했다. 네트워크 차단은 별도 loopback positive/negative 대조로 관측했다. 준비 다운로드는 online이다.

공개 PG18/vector image와 새 Linux arm64 app image도 archive로 준비했다. 해당7aca image는 Python3.13.5·PG18.6 도구·age1.2.1·35 distributions/155 Debian copyright inventory이며 network-none/read-only 실행의 CLI·합성 암복호화·46 source 일치를 확인했다. 해당 image의 SQLite3.46.1을 PC spool용으로 반입하면 안 된다. macOS age1.3.2는 OS network-deny 암복호화에 이어 별도 private Sigsum 검증기의 proof positive·변조 negative도 통과했다. 공개 키는 고정한 공식 문서의 입력이며 out-of-band 신원 확인이나 source/binary 재현성 증명이 아니다. 후속 source wheel을 이전 image와 같다고 취급하지 않는다.

`uv0.11.8` experimental CycloneDX1.5 export는 lock graph이며 실제 platform closure·build closure·image provenance는 각각 inventory로 구분한다. license/NOTICE hash 보존은 재배포 승인이나 모든 copyleft source 제공 의무의 완료가 아니다. Docker/OS/native host 설치·인증·별도 독립 witness·다른 ABI·최종 release 승인은 남아 있다. 구독 coding agent와 Jev는 허가된 외부 연결을 필요로 하므로 **offline 설치 성공을 전체 제품의 offline 판단/운영 성공으로 표시하지 않는다**. 최신 [실행·실패 기록](verification.ko.md#남은-작업-후속--native-진단실제-판단오프라인-반입)과 source fingerprint·wheel hash를 같이 확인한다.

이미 검토된 candidate 자료를 반입한 뒤 실행한 설치 형태는 다음과 같다. `requirements-local.txt`에는 app wheel도 정확한 version/SHA-256으로 포함돼 있어야 한다.

```sh
"$PYTHON" -m pip --isolated --disable-pip-version-check install \
  --no-cache-dir --no-index \
  --find-links "$BUNDLE/wheelhouse" --find-links "$BUNDLE/package" \
  --require-hashes --requirement "$BUNDLE/requirements-local.txt"
"$PYTHON" -m pip --isolated check
```

`--no-index`는 registry 조회만 막으며 OS-level network 차단이 아니다. 반입한 requirements·wheel metadata에 direct URL/VCS 참조가 없는지도 확인해야 한다. 이 candidate의 누락 파일을 online으로 보충하거나 시스템 Python을 설치한 결과를 offline 성공으로 세지 않는다. 대상과 맞지 않는 wheel·누락 hash·불완전 closure는 준비 환경에서 해결하며 operator의 기존 배포에 임의로 덮어쓰지 않는다.

## 3. 신규 설치 순서

1. 위 compatibility·소유권·저장/처리 허가·필요한 offline 자료를 확인한다. 새로운 독립 deployment만 초기화한다. 기존 배포는 §4를 따른다.
2. 검증한 설치 entrypoint로 `init`을 실행한다. DSN은 private 파일로 전달하고 기본 판단은 `--judge agent --jev-policy deny`로 명시한다. `--resume`은 원래 owner/token·서명 intent·동일 인자로만 사용한다.
3. 명시 project를 등록하고 agent/producer의 분리된 credential에 그 binding 하나만 grant한다. locator는 설치 귀속 확인이며 memory authority 자체가 아니다.
4. 로컬 authority의 receipt-owned macOS `service install` 또는 운영자가 관리하는 cloud 서버를 준비하고 **DB 왕복·배포 identity·삭제 barrier를 포함한 readiness**를 확인한다. remote PC는 `client configure` 뒤 **PC의 `service install`을 먼저** 수행해야 다음 `host-install` bootstrap의 enabled-client 검사를 통과한다. PC supervisor는 outbox만 관리하며 cloud 서버/DB를 시작하지 않는다.
5. 명시 project/host/agent-token-file/producer-token-file로 `host-install`한다. remote PC는 verified profile·현재 bootstrap과 `--ack-remote-storage`가 추가로 필요하다. Codex/OMP는 명시 advisory만 지원하며 `--strict` 요청을 성공/자동 강등으로 바꾸지 않는다.
6. workspace/plugin/hook/MCP 도구 승인은 native host의 별도 경계다. 정확한 대상·지속 scope를 검토하고 현재 inventory/callback을 확인한다. [폰·headless 조사](research/2026-10-16-oss-native-trust.ko.md)의 API 가능성을 이미 구현된 승인 client로 표시하지 않는다.
7. §6의 전체 흐름을 합성 corpus로 실행한다. 그 뒤에만 허가된 실제 유입을 연다. Jev는 별도의 egress allow·유효 키·명시 provider 선택이 있어야 하며 실패 시 자동 agent fallback은 없다.

설치 프로그램이 접근할 수 없거나 ownership/CA/receipt drift가 있으면 거절 원인을 해결한다. 전역 권한·native trust·writable ancestry 검사를 완화하거나 다른 deployment를 fallback으로 사용하지 않는다.

### ingress 배포 전 확인

- local authority Host는 profile 미설정·`tls_proxy=none|loopback|private` 모두에서 실제 socket peer가 loopback이어야 한다. Host/Origin을 localhost로 바꾸거나 forwarded 주소를 주장해 local operator/bearer 경로를 선택할 수 없다. 알 수 없는 peer도 거절한다.
- CLI의 `proxy_headers=False`를 유지한다. 다른 ASGI host가 client/scheme을 임의 forwarded 값으로 재작성하면 실제 접속 주소 검증 전제가 깨진다.
- private proxy는 선언한 단일 IP·HTTPS 표식과 고정 public origin을 사용하고 backend port를 외부 publish하지 않는다. raw HTTP 위장 거절과 정상 loopback/TLS proxy 양쪽을 실제 격리 배포에서 확인한 뒤에만 운영 배포를 검토한다. 합성 검증은 운영 노출·침해 조사 결과가 아니다.


## 4. 기존 배포 전환 순서

### 4.1 유입 중지·중지 확인

1. 이 배포의 native 소비·producer 유입을 운영 절차로 중지한다. unrelated 프로젝트나 사용자 세션을 종료하지 않는다.
2. owned 서비스 상태를 확인하고 명시적으로 stop한다.

```sh
"$AM_BIN" --config "$CONFIG" service status
"$AM_BIN" --config "$CONFIG" service stop
```

`stop`은 durable disabled intent를 먼저 저장하고 native unload를 최대30초 확인한다. 실패/timeout은 성공이 아니다. `status.running=false`나 job 부재만으로 application drain·외부 provider 완료를 증명하지 않는다. 실제 serve는 admission 종료→recovery/judge/scheduler join→in-flight drain→Store close 순서를 수행한다. **별도 `drain` CLI는 없다.** exclusive maintenance lock을 획득할 수 없으면 다음 단계로 강행하지 않는다. 직접 SQL client 전체를 이 lock이 차단하는 것은 아니다.

`service start/stop` 오류의 `effect=committed`는 **durable enable/disable intent의 반영**을 뜻하며 native 시작/종료 성공을 뜻하지 않는다. native 완료가 불확정이면 status를 확인한 뒤 같은 명령으로 명시 재개한다. intent 저장 여부부터 불확정이면 unknown이다. receipt는 duplicate JSON key·비정수 UID를 거절한다.

### 4.2 최종 encrypted backup·복구 자료 확인

서비스/유입을 정지·drain한 상태에서 현재 package와 operator로 최종 backup을 만든다. local executor 예시의 세 PG 경로와 age는 실제 검증된 절대 경로여야 한다.

```sh
"$AM_BIN" --config "$CONFIG" --token-file "$OPERATOR_TOKEN_FILE" backup \
  --runtime local --age-binary "$AGE_BINARY" \
  --pg-dump-binary "$PG_DUMP_BINARY" \
  --pg-restore-binary "$PG_RESTORE_BINARY" --psql-binary "$PSQL_BINARY" \
  --output "$BACKUP_ARCHIVE" --recipients-file "$RECIPIENTS_FILE"
```

archive의 checksum/크기·migration/live version과 `journal_included=false`를 기록한다. 별도 journal 최신 head·private 복구 자료·복구 key가 없으면 archive 하나로 전체 복구 가능하다고 보고하지 않는다. 논리 삭제와 WAL/media/과거 archive erasure를 구분한다.

### 4.3 package/schema/host 전환

1. 이전 설치 환경은 복구용으로 보존하고 새 검증 package를 별도 stable 경로에 반입한다. 새 검증 절대 entrypoint는 `NEXT_AM_BIN`으로 구분하며 사용 중인 venv를 덮어쓰지 않는다. 아래 owned 제거가 끝날 때까지 `AM_BIN`은 원래 설치본이다.
2. 원래 host project·host·deployment의 owned uninstall을 수행한다. foreign hook·MCP·사용자 trust·pending spool은 보존한다. drift나 중단 intent가 있으면 같은 정확한 범위로 정상 재개한다.

   adapter6 전환에서도 원래 v5 receipt/command를 편집하지 않는다. 원래 entrypoint의 정상 owned uninstall을 우선하며, 새 설치본도 검증된 v5를 cleanup-only로 읽는다. 재설치 전 active v5 replay는 거절되고 pending private spool은 보존한다. 생성 command의 Python `-I`는 import 격리이며 native trust/strict 지원 범위를 바꾸지 않는다.

3. **config를 쓰기 전에**, 원래 entrypoint·원래 config가 receipt와 일치할 때 owned service도 제거한다. stopped 상태여도 config bytes는 pin되어 있으며 `migrate --upgrade-config` 뒤 uninstall은 serialization-only 변경에도 정상 거절된다. receipt/digest를 고치거나 ownership 검사를 우회하지 않는다.

```sh
"$AM_BIN" --config "$CONFIG" service uninstall
```

4. 원래 owned entries 제거를 확인한 뒤 새 검증 entrypoint로 전환하고 현재 operator·해당 deployment의 migrator 설정으로 명시 migrate한다.

```sh
AM_BIN="$NEXT_AM_BIN"
"$AM_BIN" --config "$CONFIG" --token-file "$OPERATOR_TOKEN_FILE" migrate \
  --confirm-deployment "$DEPLOYMENT_ID" --upgrade-config
```

5. 자동 schema downgrade/구형 binary fallback을 하지 않는다. 원래 config/audit가 보존됐는지 확인한다. migration fence가 남으면 §5의 matching migrate 재개를 따른다.
6. 새 entrypoint·config로 service를 명시 설치하고 DB-inclusive readiness 뒤 host를 재등록한다. 새 설치 activation은 운영자의 명시 결정이며 old receipt의 사후 uninstall로 대체하지 않는다. 바뀐 credential·endpoint·CA/profile을 정확한 owned 범위에 적용하고 새 credential이 필요하면 명시 발급·구 credential 실제 폐기를 확인한다. credential 파일 교체만으로 revoke됐다고 하지 않는다.
7. service 상태·DB-inclusive readiness와 §6을 확인한다. **유입 재개는 검증 후 별도 명시 단계**다. 이전 explicit stop을 이 명시 운영 절차 밖의 client/install replay/recovery가 자동 뒤집도록 만들지 않는다.

## 5. 장애별 대응

| 관측 | 정상 대응 | 하지 않는 것 |
|---|---|---|
| DB unavailable·readiness503 | DB 운영자가 원래 고정 endpoint를 복구. bounded spool 상태/gap을 확인하고 준비 후 background 전송 관측 | 새 DB/port 추측, unavailable을 empty memory로 처리, unknown mutation 재전송 |
| 사용자가 service stop | disabled/loaded/running을 구분. 재개 의사가 있을 때만 명시 start | health check/install replay가 stop을 뒤집거나 cloud server를 PC에서 시작 |
| service/host receipt·config·CA drift | 유입/소비 중지, 소유 항목과 변경 원인 확인. 정확한 정상 제거·재설치 또는 matching intent 재개 | receipt 수정·trust 위조·foreign 항목 덮어쓰기·guard 완화 |
| native hook가 미발견/미신뢰 | 실제 executable/home/project와 layer disabled reason·개별 정의/enablement 확인. 승인과 실제 callback을 분리 | MCP 검색·plugin list·버전 출력만으로 보호 성공 선언, hook-trust/permission bypass |
| host install/remove 중단 | 원래 인자/배포/소유 receipt로 같은 명령 재개. 삭제 project는 실제 삭제일 때만 `--project-deleted` | 이동/unmount를 삭제로 간주하거나 absent project를 임의 재생성 |
| mutation 응답 유실 | `effect`와 business idempotency key를 보존해 명시 reconcile. 검증된 not-started 경로만 기존 재연결 계약 사용 | unknown을 not_started로 바꾸거나 새 key로 무조건 재실행 |
| migration fence | 같은 current operator·배포·config·원본/목표 bytes·retirement 확인으로 **같은 migrate** 재개 | fence 삭제, `restore-recover`를 migration 복구에 사용 |
| restore fence/중단 | 현재 operator·배포·최신 독립 head로 정상 `restore-recover`; archive 효과는 별도 unknown으로 기록 가능 | 미발급 fresh token을 현 operator처럼 사용, 복구 성공을 archive 적용 성공으로 포장 |
| selected Jev 실패·키 유실 | pending/visible unavailable 보존, operator가 필요하면 provider를 명시 변경 | 구독 agent로 silent fallback, allow만으로 Jev 전송 |
| Jev 교체 fence 뒤 중단 | configured Jev·unavailable·retirement/issuance pending 확인 후 명시 `judge set jev`, 또는 사용자가 `judge set agent` 선택 | 실패를 agent 자동 선택/성공으로 바꾸거나 fence·미확정 credential intent 삭제 |
| 최초/재개 service install의 native 실패 | 저장된 installing/enabled intent와 native completion을 구분해 status·원래 인자로 명시 reconcile | durable 파일이 있는데 not_started로 취급하거나 receipt를 지워 재초기화 |
| fenced Jev인데 DB ready | 인증된 judgment/unavailable과 retirement/issuance pending을 함께 확인 | ready/db_ready만 보고 agent 자동 fallback 또는 Jev 정상으로 판정 |
| 빈 remote spool·원격 장애·stop | 빈 queue는 probe하지 않고 pending 실패는 cycle backoff. 준비/DNS 대기는 중단하고 이미 송신한 I/O는 원래 deadline으로 drain | 반복 TLS/DNS busy polling, 매 cycle backoff 초기화, unknown mutation 새 key 재전송 |
| 불완전 POST upload | 전체 body15초 뒤408/not_started·HTTP/1 연결 종료. 준비된 완전 요청을 새 연결로 실행 | chunk마다 deadline 연장, 부분 source 저장, unknown mutation 자동 재전송 |
| 삭제 journal/head 부재·불일치 | authority read 차단 유지, 독립 보존 자료·허가된 operator 절차로 복구 | DB archive의 옛 head를 최신이라고 승인하거나 삭제 floor 초기화 |
| backup/restore/recover의 `cleanup.complete=false` | 원래 code/effect와 bounded cleanup stage/code/type을 함께 보존. `committed`라면 작업에 맞는 archive 게시·marker 해제 상태를 확인하고 cleanup만 구분 | cleanup 오류를 원래 작업 미실행으로 바꾸거나 새 key로 무조건 재실행, 원래 실패·다른 close 시도 누락 |
| CLI Ctrl-C | `COMMAND_INTERRUPTED/unknown`과 원래 operation/intent를 보존해 효과를 확인 | exit130을 `not_started`로 간주하거나 SIGTERM·provider 취소/erasure의 성공으로 확대 |

### 명시 restore

검증된 archive/age identity와 최신 독립 삭제 head를 공급한다. 아래는 **DB 내용을 교체하는 운영**이므로 승인된 대상·중지·exclusive lock·복구 자료를 확인한 뒤에만 실행한다.

```sh
"$AM_BIN" --config "$CONFIG" --token-file "$OPERATOR_TOKEN_FILE" restore \
  --runtime local --age-binary "$AGE_BINARY" \
  --pg-dump-binary "$PG_DUMP_BINARY" \
  --pg-restore-binary "$PG_RESTORE_BINARY" --psql-binary "$PSQL_BINARY" \
  --archive "$BACKUP_ARCHIVE" --identity-file "$IDENTITY_FILE" \
  --expected-head "$LATEST_DELETION_HEAD" --confirm-deployment "$DEPLOYMENT_ID" \
  --operator-out "$FRESH_OPERATOR_TOKEN_FILE"
```

`restore-recover`는 동일 executor/age/세 PG 경로와 `--expected-head`·`--confirm-deployment`·`--operator-out`을 받지만 archive/identity 인자를 받지 않는다. 원래 현재 operator로 호출한다. 복구는 archive 적용을 증명하지 않을 수 있으므로 반환 effect와 `archive_replacement`를 보존한다. 성공 후 fresh operator·기존 token 폐기·필수 rule 재승인·fresh agent/producer 재등록을 확인하고 서비스/host를 갱신한다. 옛 package로 되돌리는 것만으로 schema/권한/삭제 상태가 rollback되지는 않는다.

`0007_memory_health` archive도 PG backup 시점의 판정만 복원한다. post-backup Reject/Accept·assessment가 최신이라는 별도 증거가 없으면 restored source에서 파생한 ordinary claim과 이후 파생 claim은 `unknown_after_restore`이며 fresh exact operator review가 필요하다. health/Jev 정책은 명시 재확인 전 비활성이다. 이를 보완한다며 새 disaster ledger/key/witness를 임의 생성하지 않는다. required rule 재승인·최신 독립 deletion head·credential 교체는 이 health 판정과 별개로 계속 필요하다.

## 6. 전환 후 합격 증거

- 설치 경로/Python/import-root·실제 package hash·네 도구 catalog·인증·one-binding denial·transport/TLS·DB readiness를 확인한다.
- 합성 원문 capture→inspect→호출 agent의 grounded selection/extraction·관계→전체 relevance→**동일 claim/근거/조건/예외가 포함된 다음 소비 read**를 확인한다. 단순 note 저장/도구 호출 수는 전체 흐름 증거가 아니다.
- 정정·철회·다음 read·기존 origin replay·권한 폐기·stale admission·unknown-effect·spool 상한/TTL·DB 장애/복구를 분리한다. 삭제는 identity/lineage floor이지 미래 모든 동일 본문의 영구 blacklist가 아니다.
- 지원되는 native 보호에서는 실제 첫 행동 시도·동일 action의 deny·금지 부작용0·중지 중 거절·명시 복구를 확인한다. adapter 함수/SDK 성공은 native 보호 증거가 아니다. 미지원 경로는 거절/미검증으로 남긴다.
- native memory 공존·PMPA·semantic re-entry·frozen paired trial은 별도 acceptance다. 기존 native 설정이나 corpus를 바꿔 통과시키지 않는다.
- actual login/reboot/sleep, clean 전체-dependency offline 설치, license/SBOM/checksum bundle, 공식 review/QA/handoff, 실제1–2주 trial, 배포 승인·publication은 각자의 증거가 필요하다. 절차·단위 테스트·합성 smoke로 이 항목들을 모두 완료 처리하지 않는다.
- paired 평가에는 [고정 run identity·전체 attempt 분모·oracle/no-op/plausible-wrong 대조군·최종 artifact 불변](architecture.ko.md#평가-기록의-무결성)을 적용한다. busy/error/timeout·비교 불가를 primary 분모에서 빼거나 다른 remediation run의 좋은 행으로 교체하지 않는다. candidate recall·agent 판단·후속 task 성공은 별도 결과다.

### 원래 계획 리뷰14건의 증거 연결

[삭제된 #3의 보존 원문](https://github.com/chonamdoo/agents-memory/issues/5#issuecomment-6149015598) 기준이다. 이후 Qwen 제거·agent 기본/선택 Jev·클라우드 개발 승인으로 바뀐 계약은 현재 이슈 #5 §0이 우선이다. 항목을 문서에 연결한 것과 실제 출시 acceptance 통과를 구분한다.

| ID | 현재 연결·남은 출시 조건 |
|---|---|
| A1 |§4.1–4.3 유입 차단/최종 backup. 안정 배포의 마지막 accepted operation→migration 실패/복구 drill 미완료 |
| A2 |§1·§5 독립 journal/head/key와 fail-closed. 합성 warm restore 이력은 전체 디스크 손실·새 witness 복구 증명이 아님 |
| A3 |§2·§5 로그인 의존 launchd/절대 경로/명시 stop. 실제 login/reboot/sleep·Docker 지연 운영 미완료 |
| A4 |§5 fence/효과별 `restore-recover`·fresh credential. 합성 실행과 현재 stable cutover를 분리 |
| A5 |§4.1·§5 runtime 차단/폐기·loaded provider unknown. 전체 native incident·host 재시작 확인 미완료 |
| A6 |§2 hash closure·네트워크 차단 빌드/설치·이미지/도구. OS/host prerequisite·전체 offline 운영·license 승인 별도 |
| A7 |§3·§4 단일 deployment lifecycle/foreground 운영 절차. 여러 native host의 장기 instance 관측은 trial에서 확인 |
| B1 |§6 expected denial과 capability를 분리. Codex/OMP strict는 negative pass/unsupported이며 positive 보호로 바꾸지 않음 |
| B2 |§6 원문 판단·전체 relevance·동일 claim 다음 read. 이전 실제3 host/HTTPS 이력과 새 Opus3사례는 전체 mode×host×transport 재검증의 대체가 아님 |
| B3 |검증 계획의 raw/feasible recall·언어군·고정 gold. 인간 검토120 holdout 미실행 |
| B4 |baseline/on 각각≥80%·paired CI와 matched allow. 세 판단 smoke에 causal benefit 주장을 붙이지 않음 |
| B5 |60 task×3회·seed/10,000 cluster bootstrap 사전 freeze·1회 판정. 실제 paired 실행 미완료 |
| B6 |busy 포함 attempt 분모·성공 terminal latency. 실제 고정 sequential/burst workload 미완료 |
| B7 |§2 network-deny와 별도 Linux container의 HOME/socket/loopback positive·negative, filesystem/resource/PID/fsize·자식 deadline canary는 관측. 전체 P3·모든 native 환경 격리 완료는 아님 |

## 7. 제거·보관

owned host/service만 정상 uninstall한다. 사용자·Agent Flow 설정, 명시 중지 의사, private pending spool과 미확정 mutation 이력을 보존한다. 코드/venv는 참조하는 live consumer가 없음을 확인한 뒤 제거한다. 메모리 retract/purge, DB 물리 공간 회수, journal 최소 metadata 보존, encrypted archive retention은 별도 정책·권한이다. 무관한 임시 파일·서비스·기존 배포를 정리 대상으로 포함하지 않는다.

## 평가 engineering 실행 계약

현재 run의 runtime 검증은 **허용된 GitHub Actions 병렬 job에서만** 수행한다. 아래는 설치 wheel의 CLI 계약이며 로컬 실행 지시·실제 native/model/corpus/egress 승인이나 trial 시작 허가가 아니다. `$EVAL_BIN`은 검증 대상 exact wheel의 entrypoint이고 위 stable `$AM_BIN`을 교체하지 않는다. 실제 target/권한·독립 gold/oracle이 없으면 해당 실행은 blocked다.

```sh
"$EVAL_BIN" evaluation prepare \
  --manifest "$MANIFEST" --expected-sha256 "$MANIFEST_SHA256" --run-dir "$RUN_DIR"
"$EVAL_BIN" evaluation run \
  --manifest "$MANIFEST" --expected-sha256 "$MANIFEST_SHA256" --run-dir "$RUN_DIR"
"$EVAL_BIN" evaluation report --run-dir "$RUN_DIR"
```

독립 adjudication을 실제로 받은 경우에만 마지막 명령에 `--adjudication-file "$ADJUDICATION_FILE"`을 추가한다. 입력은 읽기 전용이고 exact manifest·실제 final context·rubric에 묶여야 하며 없거나 관측이 부족하면 unknown이다. report는 전체 ledger에서 다시 구성하며 CLI exit0/완료 report를 목표 점수·180 valid pairs·출시 승인으로 해석하지 않는다.

| manifest 경계 | 제출·검사 계약 |
|---|---|
| 원본 identity | `schema=1`, `scope=engineering|evaluation`, `source_commit`, controller/verifier/settings/permissions digest와 **원본 manifest bytes**의 외부 `--expected-sha256`. `independence=provided_unattested`는 인간 승인 attestation이 아니다. |
| frozen files | 각 `{name,path,sha256,maximum_bytes}`. wheel/controller/verifier/native_driver/gateway_driver/scoring/diagnostics/**context_renderer**/corpus/gold/workload/rules/native_identity/**native_tool_mapping**/runtime가 필수다. 상대 path는 manifest 디렉터리 기준이고 digest·개별/합계 bound를 검사한다. |
| corpus·관계 | `corpus.schema=2`에 exact source/revision/전체 원문 window, 승인 claim의 완전한 inspect projection·health dependency digest와 eligible relation projection을 고정한다. 관계 manifest의 `id/revision`으로 현재 자격을 확인하고 전체 `relation_ids`를 읽는다. 미리보기8개를 전체 관계 집합으로 취급하지 않는다. |
| rule 집합 | measured `rules.schema=2`는 required triple뿐 아니라 현재 applicable optional rule의 body·exceptions·selector 적용 결과·revision/digest와 완전한 probe를 포함한다. probe는 후보 없는 bounded read여야 하며 omitted·unknown·불완전 열거를 빈 집합으로 바꾸지 않는다. 별도 preflight rule 파일은 `schema=1`의 required triple이다. |
| 독립 packing·F | 고정한 `context_renderer`로 statement·polarity·modality·조건·예외·valid time과 모든 evidence의 source/revision/span·speaker·event/recorded time을 costed claim과 대조한다. optional rule·관계 비용도 완전한 고정 집합과 같아야 한다. 자기 입력의 digest만 다시 맞춰 의미·근거를 바꿀 수 없으며 불완전 입력의 F는 unknown이다. |
| stdio 전달 | tool 반환은 전송 대기 상태다. 원래 JSON-RPC ID·tool·arguments·payload와 MCP `_meta["agents-memory/stamp"]`가 일치하는 response의 마지막 byte를 downstream에 쓴 뒤에만 receipt와 final-context credit을 기록한다. output cap·부분 write·broken pipe·취소·deadline·ID 충돌·응답 교체는 미완료로 남긴다. write 완료도 host/model의 실제 소비를 증명하지 않는다. |
| native tool 연결 | `native_tool_mapping={schema:1,backend,routes:[{route_ref,server,tools}]}`. measured/preflight의 exact route 집합과 `memory_required_context`·`memory_context`·`memory_inspect`·`memory_record`·`memory_feedback`의 native 이름을 모두 고정한다. Claude 이름은 `mcp__<server>__…`, Codex는 해당 server의 tool 이름이다. 같은 native invocation/generation의 실제 tool start/result·arguments·완전한 result content와 gateway 요청/완전 write가 모두 맞아야 한다. 별도 client의 성공·agentMessage만으로는 부족하다. |
| native 연결 receipt | Codex request `_meta.callId/threadId`를 실제 native item ID/thread와 연결하며 JSON-RPC ID 동일성을 가정하지 않는다. Claude의 동일 요청·결과 반복은 두 관측 stream의 비중첩 순서로만 구별하고 모호한 병렬 반복은 거절한다. immutable `ledger/<invocation-key>.native-tool-link.json`을 terminal digest에 묶고 health export/replay에서도 다시 계산한다. native result가 잘려 완전성을 관측하지 못하면 비교 불가이며 provider 소비는 unknown이다. |
| 실행 model identity | 초기 model/version/permissions와 원래 protocol event를 보존하고 driver·controller·health replay가 같은 관측 검사를 쓴다. Claude assistant model 불일치·다른 modelUsage 집합, Codex model/rerouted(원래 threadId/turnId/fromModel/toModel/reason 포함)는 비교 불가다. A→B→A도 재일치로 세지 않고 frozen identity digest를 부여하지 않는다. modelUsage의 subagent 혼합을 확정된 main fallback이라 단정하지 않으며, completed attempt·제출·usage/비용 미관측·cleanup과 실패 분모를 삭제하지 않는다. |
| 고정 scope·취소 | candidate/final dispatch 전 정규화한 `limit`·`max_bytes`·`code_workspace_id`를 frozen request와 대조한다. 원래 workspace가 null일 때만 생략/null이 같다. pair/control/current subject는 같은 stop event를 공유하며 취소 후 후속 control을 실행하거나 부분 선검증을 eligible로 세지 않는다. post-spawn helper 실패도 owned 종료·bounded final wait·각 pipe close와 원래/동시 실패를 보존한다. |
| candidate/final 동일성 | 동일한 typed normalization으로 admission의 내부 identity를 비교한다. frozen 값과 같은 default 생략/명시 또는 원래 null workspace의 생략/null 전환은 유지한다. 실제 native/request/write correlation에는 원래 raw arguments를 남기며 의미가 다른 query·selector를 동등 처리하지 않는다. |
| native 제출 경로 | 실행 전 승인 CWD의 root descriptor를 고정하고 nested submission의 모든 경로 성분을 no-follow로 연다. 전후 root identity·owned regular single-link leaf·byte bound·파일 안정성을 검사한다. root/중간 symlink·root 교체·parent backtracking·hardlink를 통해 밖의 파일을 수입하지 않는다. 정상 nested 파일은 허용하지만 host 전체 containment·escaped descendant 부재를 주장하지 않는다. |
| 비교·분모 | seed·repeats·concurrency·byte/event/artifact/verifier/usage budget·고정 bootstrap10,000/95% CI. retry는 사전 명시하지 않으면0이고 모든 원래 attempt·중단·오류·오염 pair를 보존한다. 비용 미관측은0이 아니다. |
| 실제 권한·격리 | current Actions owner·exact inspected Docker runtime/image·정상 native policy/capability·서로 다른 measured/preflight binding·명시 upstream/refs/required rule. token/file 경로·설정 digest가 trust/egress/실제 protected-action 승인을 대신하지 않는다. |
| 운영 평가 범위 | `scope=evaluation`은 원래60 task/60 cluster×3회와 gold120개 이상·10군별12개 이상을 요구한다. 작은 engineering protocol peer/합성 oracle 실행으로 이 요구를 줄이거나 인간 gold를 만들어 채우지 않는다. |

`RUN_DIR`은 absolute private retained directory이며 native 작업 CWD와 서로 포함되지 않아야 한다. `prepare`는 manifest/run identity·frozen inputs·전체 pair schedule을 먼저 보존한다. 이후 inputs/ledger/traces/artifacts/verifiers를 원본 실패·private receipt·cleanup과 함께 유지한다. body/corpus/credential이 있을 수 있으므로 run 디렉터리를 public Actions artifact나 PR에 통째로 게시하지 않는다. 이 준비만으로 실제 native consumption·oracle 독립성·clean/offline/ABI·trial 경과를 증명하지 않는다.

현재 controller는 measured corpus/rules의 이전 schema를 호환 입력으로 재해석하지 않는다. 과거 run의 원본 manifest·source·실패 receipt는 그대로 보관하고 새 schema와 새 run identity로 다시 고정한다. 같은 run의 입력·digest·기존 terminal을 덮어쓰지 않는다. arm 사이 optional rule이나 관계가 바뀌면 비교 불가인 원래 pair와 모든 시도를 남기며 유효 쌍으로 세지 않는다.

native mapping은 해당 host의 실제 server/tool 이름과 관측 가능한 protocol에 대한 고정 입력이지 자동 설치·trust·hook·MCP permission 승인이 아니다. Codex lineage 필드는 [고정 version의 call metadata](https://github.com/openai/codex/blob/rust-v0.163.0/codex-rs/core/src/mcp_tool_call.rs)와 [native item schema](https://github.com/openai/codex/blob/rust-v0.163.0/codex-rs/app-server-protocol/schema/typescript/v2/ThreadItem.ts)를 따른다. 필요한 metadata/start/result가 없는 host를 추정으로 지원 처리하지 않는다. `native_tool_mapping` 없는 과거 manifest도 같은 run에서 보충·재해석하지 않으며 원본 source/receipt를 보관하고 새 manifest/run identity로 고정한다.

controller의 read-only rule fence는 native arm budget을 재설정하는 경로가 아니다. 원래 frozen `rules.probe`를 별도 controller scope의 required/context request에 그대로 사용하고 health replay도 그 값을 대조한다. corpus 준비의 재열기·rule probe는 서로 다른 관측 invocation ID를 사용한다. native gateway의 budget/workspace 강제를 예외 처리하거나 controller-only judgment 권한을 native에 추가하지 않는다.

gateway observation은 invocation별 단일 `gateway.json`과 terminal의 digest 참조로 연결한다. report와 health replay는 같은 참조 bytes를 재검사하며 terminal 안에 receipt 본문을 중복 저장하지 않는다. inline receipt만 있는 과거 run을 새 계약으로 자동 해석·덮어쓰기하지 않고 해당 source와 원본 attempt를 보존한다.

## 건강 판정 입력과 admission

`health_work.claims`는 `id/revision`과 완전한 `ClaimMeaning` 필드를 담는다. statement·kind·subject/predicate/object·polarity·modality·conditions·exceptions·valid_from/valid_until·entities를 evidence 선택과 support 판단에 모두 전달한다. nullable/default 의미도 응답에 명시하며 빠진 필드를 추정해 statement-only 판단으로 되돌리지 않는다. 정확한 meaning digest를 live admission manifest에 묶으므로 과거 statement-only work/admission은 새 inspect 없이 재사용하지 않는다.

기존 health policy의 `max_audit_bytes`에는 전체 claim JSON과 source window의 UTF-8 bytes를 계산한다. 완전한 의미와 비어 있지 않은 source window가 안 들어가면 `HEALTH_BUNDLE_TOO_LARGE`이며, 의미를 축약하거나 예산·승인 fence를 완화하지 않는다. source-egress·provider·추가 health 처리 허가, 늦은 결과의 현재 권한/정책/claim revision 검사와 operator Reject·코드 stale·복구 quarantine 보호는 그대로다. typed 의미 전달과 engineering oracle은 실제 모델 정확성·인간 gold·freshness·자동 승인을 증명하지 않는다.

`/readyz`의 비인증 probe는 DB·배포/삭제 barrier와 `accepting`을 확인한다. operator 인증 응답은 judgment가 `unavailable`인 경우에도 503/`ready:false`이며 `db_ready:true`와 양립한다. 따라서 두 응답의 기준은 다르고 operator 503을 곧바로 DB 장애로 해석하지 않는다. 본문 없는 판단 오류 code와 DB 상태를 각각 확인하며 native hook trust는 이 endpoint가 증명하지 않는다.

닫힌 관측 segment의 assessment 완료는 해당 bounded 작업을 처리했다는 뜻이다. partial/unknown source coverage나 support/freshness를 complete로 표시하지 않는다. close 미관측·origin 누락·refresh conflict는 held로 남으며 다시 볼 수 없는 입력을 새로 수집하거나 판정을 추정해 해소하지 않는다.

작업을 unknown으로 명시 종결하거나 다시 열려면 먼저 권한 있는 `health:item:<pending_id>` inspect로 현재 `health_revision`과 scope를 읽는다. 완전한 strict mutation command에 `kind="health_work_disposition"`, `pending_id`, `expected_pending_revision`(읽은 `health_revision`), 해당 snapshot, `decision="close_unknown"|"reopen"`, 이유와 기존 binding/revision/idempotency 필드를 넣고 `health apply --command-file FILE`로 제출한다. operator 전용 API/CLI 명령이며 MCP agent record의 승인 권한을 늘리지 않는다.

`close_unknown`은 resolved history·불완전 coverage·unknown disposition을 남기고 admission을 닫는다. 사실의 정확성·freshness·인간 Accept나 source 분류 승인이 아니다. 늦은 agent 결과뿐 아니라 capture 성공·동일 입력 refresh·refresh 실패도 원래 operator disposition과 event 연결을 덮거나 작업을 자동 재개할 수 없다. 실제 새 입력이 revision을 바꾸면 이전 revision의 reopen은 거절된다. `reopen`은 최신 revision·권한·snapshot과 현재 queue capacity를 다시 검사하며, 근거가 여전히 없으면 그 gap을 유지한다. queue 상한이나 revision fence를 올려 재개하지 않는다. machine assessment가 완료된 작업의 실제 새 근거 재등록은 operator의 terminal unknown과 구분한다. operator의 exact Accept/Reject로 code 작업이 처리된 뒤에도 늦은 assessment를 새 성공으로 받지 않는다.

refresh 실패가 machine-assessed 작업에 남긴 event 없는 `deferred_unknown`은 operator가 명시 종결한 기록이 아니다. 실제 새 근거의 등록은 원래 capacity·revision 검사를 받아 다시 pending이 될 수 있다. capacity 거절을 무시하거나 queue 상한을 높이지 않으며, 운영자가 event와 함께 `close_unknown`한 작업은 최신 exact `reopen` 없이는 계속 닫힌다.

`health:quarantine`은 현재 binding·snapshot에서 보류된 기억의 bounded opaque ref/revision/version 목록이며 context의 `code_workspace_id`로 필터링하지 않는다. `context.partial`과 `context.health`의 `withheld`·`unknown_assessments`·`closed_unknown_work`를 empty corpus나 healthy 완료로 해석하지 않는다. current source policy/dependency 자격을 잃은 분류는 건강 분모에서 제외하며 인간의 exact review 기록이 그 분류를 현재 것으로 바꾸지 않는다. body가 필요한 판단은 원래 inspect/admission·권한 경로를 사용한다.

context의 `withheld`·`unknown_assessments`는 요청 workspace 범위지만 `closed_unknown_work`는 현재 binding·snapshot 전체이며 workspace로 좁히지 않는다. 다른 workspace의 종결 unknown 때문에 context가 partial일 수 있다. 이 수와 snapshot-wide quarantine을 맞추거나 일대일 대응으로 간주하지 않으며, 보수적 신호를 없애려고 종결 이력이나 필터를 임의 변경하지 않는다.

feedback의 accept/decline 판정 이력·opaque event/reason 참조는 원문 접근 허가가 아니다. 사유 source를 `inspect --snapshot SNAPSHOT`으로 읽을 때 현재 실제 target/source 공개 자격을 다시 검사한다. scoped target을 다른 snapshot에서 보지 못하면 그 판정 사유 원문도 읽을 수 없다. 전역 target은 판정을 받은 request snapshot과 다르다는 이유만으로 숨기지 않는다. 후보 또는 사유의 private 원문 삭제 뒤에도 본문 없는 기존 판정 이력과 version을 보존하며 삭제된 본문을 복원하지 않는다.

그 사유 source를 다시 가리키는 feedback도 최초 실제 target의 현재 공개 경계를 따른다. 중첩 feedback inspect·admission 재검사는 기존 bounded 재귀 manifest로 health 소유권과 dependency를 확인하며, scoped 사유를 nullable source snapshot만 보고 전역으로 공개하지 않는다. 정상 전역 target의 중첩 피드백은 다른 request snapshot에서도 공개할 수 있다.

정상 operator의 health observer에는 현재 권한이 유효한 producer의 등록만 남는다. 다른 producer의 revoke된 active 등록 때문에 전체 registry가 `AUTH_DENIED`로 중단되지는 않는다. revoke된 호출자 자신의401, agent의403, 예상 밖 DB/권한 서비스 실패는 여전히 실패이며 빈 registry 성공으로 처리하지 않는다.


