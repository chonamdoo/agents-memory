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
| native host | 해당 설치 버전·지원 callback/tool | Codex/OMP 신규 `--strict`는 거절. advisory/MCP와 native 보호는 별도이며 자동 강등하지 않음 |
| 원격 연결 | 검증 HTTPS + 명시 identity/auth/binding/profile | PC는 DB/operator를 갖지 않음. PC service는 cloud server/DB를 관리하지 않음 |

구현 근거: `spool.py:require_supported_sqlite`, `database.py:require_server/require_tool`, `service.py`의 platform/executable/receipt 검증, `hosts.py:install_host`. 정확한 public 명령은 설치된 `--help`와 [README](../README.md)를 함께 확인한다.

### 반입 acceptance

다음 자료를 서로 묶어 검토한다. **현재 이 목록의 완성된 offline release bundle이 제공됐다는 뜻이 아니다.**

- 최종 source ref와 실제 작업트리 content identity. dirty source에서 base HEAD나 package version `0.1.0`만으로 built bytes를 식별하지 않는다.
- app wheel·대상 OS/architecture/Python ABI에 맞는 **전체 runtime dependency wheel closure**·lock/선택 marker·SHA-256 목록.
- 각 배포 dependency의 license/NOTICE·SBOM·compatibility manifest·이 runbook의 버전·검증 보고. app의 MIT를 모든 dependency license로 기입하지 않는다.
- 깨끗한 환경·비어 있는 cache·네트워크 없는 설치와 실제 CLI/MCP 소비 실행. warmed uv cache, wheel `--no-deps` 설치, 다른 target wheel의 존재는 이 증거가 아니다.
- Python/SQLite·PostgreSQL/pgvector·PG18 도구·age·선택한 container image는 별도 prerequisite다. Python wheelhouse만으로 OS/container까지 offline이라고 하지 않는다.
- sdist를 offline build하려면 build backend도 반입·고정해야 한다. `hatchling>=1.27,<2` 선언과 app의 `uv.lock`만으로 전체 build toolchain이 고정됐다고 보지 않는다.

개발용 `uv sync --locked`와 cloud Dockerfile의 apt/registry/uv sync는 dependency를 취득할 수 있는 **online 준비 경로**다. 이를 offline 설치 명령으로 재명명하지 않는다. source build·dependency acquisition은 별도 준비 환경에서 수행하며 모델·telemetry·Jev를 활성화하지 않는다.

### 이번 candidate에서 실제 준비한 Python 범위

2026-10-16 작업트리 candidate는 macOS arm64 / CPython3.13.16 / SQLite3.54.0에서 app wheel과 runtime dependency34개를 hash 필수 입력으로 묶었다. 새 venv에 `--no-cache-dir --no-index`·local `--find-links`만으로 설치하고 `pip check`, isolated import의 Python43파일 일치, 설치된 CLI→advisory stdio MCP→HTTP/PG를 실제 실행했다. 준비 단계의 wheel 다운로드와 Python/pip 준비는 online이며 air-gap OS 검증이 아니다.

`uv0.11.8`의 experimental CycloneDX1.5 export는 lock 전체 graph이고 실제 platform closure는 wheel inventory로 따로 식별한다. app 포함35개 distribution의 declared license·license file hash를 보존했지만 license 호환성·재배포 승인으로 간주하지 않는다. Python/PG/pgvector/도구/age/OS library 반입, 다른 ABI/OS, 독립 witness와 최종 release 승인은 여전히 별도다. 이 source의 [실행·실패 이력](verification.ko.md#이슈-5-후속--승인-없는-구현과-설치-소비자-검증)과 content identity를 같이 확인한다.

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
4. receipt-owned macOS `service install` 또는 운영자가 관리하는 cloud 배포를 준비한다. 프로세스 존재가 아닌 **DB 왕복·배포 identity·삭제 barrier를 포함한 readiness**를 확인한다.
5. 명시 project/host/agent-token-file/producer-token-file로 `host-install`한다. remote PC는 verified profile·현재 bootstrap과 `--ack-remote-storage`가 추가로 필요하다. Codex/OMP는 명시 advisory만 지원하며 `--strict` 요청을 성공/자동 강등으로 바꾸지 않는다.
6. workspace/plugin/hook/MCP 도구 승인은 native host의 별도 경계다. 정확한 대상·지속 scope를 검토하고 현재 inventory/callback을 확인한다. [폰·headless 조사](research/2026-10-16-oss-native-trust.ko.md)의 API 가능성을 이미 구현된 승인 client로 표시하지 않는다.
7. §6의 전체 흐름을 합성 corpus로 실행한다. 그 뒤에만 허가된 실제 유입을 연다. Jev는 별도의 egress allow·유효 키·명시 provider 선택이 있어야 하며 실패 시 자동 agent fallback은 없다.

설치 프로그램이 접근할 수 없거나 ownership/CA/receipt drift가 있으면 거절 원인을 해결한다. 전역 권한·native trust·writable ancestry 검사를 완화하거나 다른 deployment를 fallback으로 사용하지 않는다.

## 4. 기존 배포 전환 순서

### 4.1 유입 중지·중지 확인

1. 이 배포의 native 소비·producer 유입을 운영 절차로 중지한다. unrelated 프로젝트나 사용자 세션을 종료하지 않는다.
2. owned 서비스 상태를 확인하고 명시적으로 stop한다.

```sh
"$AM_BIN" --config "$CONFIG" service status
"$AM_BIN" --config "$CONFIG" service stop
```

`stop`은 durable disabled intent를 먼저 저장하고 native unload를 최대30초 확인한다. 실패/timeout은 성공이 아니다. `status.running=false`나 job 부재만으로 application drain·외부 provider 완료를 증명하지 않는다. 실제 serve는 admission 종료→recovery/judge/scheduler join→in-flight drain→Store close 순서를 수행한다. **별도 `drain` CLI는 없다.** exclusive maintenance lock을 획득할 수 없으면 다음 단계로 강행하지 않는다. 직접 SQL client 전체를 이 lock이 차단하는 것은 아니다.

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

1. 이전 설치 환경은 복구용으로 보존하고 새 검증 package를 별도 stable 경로에 반입한다. 사용 중인 venv를 덮어쓰지 않는다.
2. 원래 host project·host·deployment의 owned uninstall을 수행한다. foreign hook·MCP·사용자 trust·pending spool은 보존한다. drift나 중단 intent가 있으면 같은 정확한 범위로 정상 재개한다.
3. 현재 operator와 해당 deployment의 migrator 설정으로 명시 migrate한다.

```sh
"$AM_BIN" --config "$CONFIG" --token-file "$OPERATOR_TOKEN_FILE" migrate \
  --confirm-deployment "$DEPLOYMENT_ID" --upgrade-config
```

4. 자동 schema downgrade/구형 binary fallback을 하지 않는다. 원래 config/audit가 보존됐는지 확인한다. migration fence가 남으면 §5의 matching migrate 재개를 따른다.
5. 새 package/executable·credential·endpoint·CA/profile이 바뀐 host/service 설정은 정확한 owned uninstall/reinstall로 갱신한다. 새 credential이 필요한 경우 명시 발급하고 구 credential을 실제 폐기한다. credential 파일만 교체해서 revoke됐다고 하지 않는다.
6. 명시 service start와 DB-inclusive readiness 후 §6을 실행한다. **유입 재개는 검증 후 별도 명시 단계**다. 이전 explicit stop을 client/install/recovery가 자동 뒤집도록 만들지 않는다.

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
| 삭제 journal/head 부재·불일치 | authority read 차단 유지, 독립 보존 자료·허가된 operator 절차로 복구 | DB archive의 옛 head를 최신이라고 승인하거나 삭제 floor 초기화 |

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

## 6. 전환 후 합격 증거

- 설치 경로/Python/import-root·실제 package hash·네 도구 catalog·인증·one-binding denial·transport/TLS·DB readiness를 확인한다.
- 합성 원문 capture→inspect→호출 agent의 grounded selection/extraction·관계→전체 relevance→**동일 claim/근거/조건/예외가 포함된 다음 소비 read**를 확인한다. 단순 note 저장/도구 호출 수는 전체 흐름 증거가 아니다.
- 정정·철회·다음 read·기존 origin replay·권한 폐기·stale admission·unknown-effect·spool 상한/TTL·DB 장애/복구를 분리한다. 삭제는 identity/lineage floor이지 미래 모든 동일 본문의 영구 blacklist가 아니다.
- 지원되는 native 보호에서는 실제 첫 행동 시도·동일 action의 deny·금지 부작용0·중지 중 거절·명시 복구를 확인한다. adapter 함수/SDK 성공은 native 보호 증거가 아니다. 미지원 경로는 거절/미검증으로 남긴다.
- native memory 공존·PMPA·semantic re-entry·frozen paired trial은 별도 acceptance다. 기존 native 설정이나 corpus를 바꿔 통과시키지 않는다.
- actual login/reboot/sleep, clean 전체-dependency offline 설치, license/SBOM/checksum bundle, 공식 review/QA/handoff, 실제1–2주 trial, 배포 승인·publication은 각자의 증거가 필요하다. 절차·단위 테스트·합성 smoke로 이 항목들을 모두 완료 처리하지 않는다.

## 7. 제거·보관

owned host/service만 정상 uninstall한다. 사용자·Agent Flow 설정, 명시 중지 의사, private pending spool과 미확정 mutation 이력을 보존한다. 코드/venv는 참조하는 live consumer가 없음을 확인한 뒤 제거한다. 메모리 retract/purge, DB 물리 공간 회수, journal 최소 metadata 보존, encrypted archive retention은 별도 정책·권한이다. 무관한 임시 파일·서비스·기존 배포를 정리 대상으로 포함하지 않는다.
