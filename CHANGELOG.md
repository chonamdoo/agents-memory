# Changelog

## Unreleased

### 판단 worker가 넘긴 대기 판단의 영속 기록과 agent 발견

- background 판단 worker(jev·subscription)가 확신하지 못해 coding agent에게 넘긴 판단이 프로세스 메모리와 버려지는 로그에만 남던 문제를 고쳤다. 그래서 재시작 때마다 같은 window를 provider에 다시 보냈고, agent는 할 일이 있다는 것을 알 수 없었다. 이제 넘길 때마다 다음으로 넘어가기 전에 `0008_judge_escalations`의 `am_judge_escalations`에 항목·window·health 단위로 남긴다. 사유 코드(`uncertain`, `instruction_injection`, `provider_response`, `record_*`, `item_*` 등)·시각·provider·provider revision·worker credential·데이터 버전(binding revision, source revision, window digest, cleanup manifest digest, health revision과 health 정책 revision)을 기록한다. 기록 실패는 원래 오류 코드를 담은 cycle 오류(`JUDGE_ESCALATION_UNRECORDED`)다. 같은 credential·같은 데이터 버전이면 재시작 뒤에도 다시 보내지 않고, `judge set`으로 credential이 바뀌거나 project 위치(binding revision)·원문 revision·cleanup manifest·health revision이 바뀌면 다시 판단한다. cleanup manifest가 바뀐 것은 누군가 그 항목을 inspect해 manifest를 다시 만들 때 알 수 있다. 버전은 항목 자신의 snapshot으로 계산하므로 전역 cleanup을 여러 snapshot에서 읽어도 하나다. worker는 넘기지 않은 cleanup만 버전을 읽은 뒤 inspect하고(주기 예산 1), 그 사이 버전이 바뀌었으면 그 항목을 다음 주기로 미룬다. 넘긴 cleanup은 worker가 다시 inspect하지 않으며, agent 등이 inspect해 바뀐 manifest가 드러나면 worker에게 돌아간다. selection 철회로 resolved에서 다시 열린 source 작업과, 이번에 철회된 selection의 source에 걸린 대기 작업(일부 window만 넘긴 경우)은 기록을 지우고 `am_pending_judgments.escalation_generation`을 올려 worker에게 돌려준다. 서비스 시작 때 journal을 다시 적용해도 이미 열린 작업의 기록은 지우지 않는다. `health:item` inspect는 admission에 들어간 `health_revision`을 함께 싣고, worker는 목록 이후 revision이 바뀐 health 작업을 그 주기에 보내지 않으며 기록할 때 health revision도 다시 확인한다. worker가 판단을 시작한 뒤 항목이 다시 열렸거나 manifest가 바뀌었거나 project가 옮겨졌으면 그 넘김은 기록하지 않고, worker는 그 항목 판단을 멈춘 뒤 다음 주기에 새 버전으로 다시 읽는다. 기존 `am_pending_judgments.state`·`reason`의 의미는 그대로이며 worker 상태의 `escalated_this_process`는 없앴다.
- `memory_context`의 두 응답은 agent가 판단할 대기 건이 있을 때만 `agent_judgments: {pending, next}`를 싣는다. `next`는 같은 snapshot의 `memory_inspect ref="pending"` → 항목 inspect → `memory_record source_selection`/`claim_judgment` 절차다. 건수에는 worker가 항목 단위로 넘긴 source_selection·cleanup, legacy_revalidation, 그리고 worker가 없거나 쓸 수 없는 상태(route 없음·egress 거부·같은 revision의 paused/refused/credential 무효·retiring credential·상태 파일 손상이나 읽기 실패·grant 없는 project)의 모든 대기 source_selection·cleanup이 들어간다. worker도 같은 항목 기록을 보고 그 항목을 건너뛰므로 한 항목의 처리 주체는 하나다. health는 provider마다 처리 주체가 달라 세지 않는다. provider별 분기는 없다. 최종 응답을 wire 크기로 재며 넘치면 먼저 포인터를 빼고, candidate 응답은 그다음 manifest를 ID로 줄인다. 4096 한도에서는 호출자가 context `max_bytes`를 그 한도에 맞게 줄여야 relevance 응답이 들어간다. hook context에는 포인터가 없다.
- `memory_inspect ref="pending"` 항목은 `awaiting: coding_agent|background_judge`와 최근 `escalation` 요약을 싣는다. 항목이 MCP wire 한도에 걸리면 먼저 `escalation` 요약을 빼고, 그래도 넘치면 page를 줄인다. page의 첫 항목은 다음 page로 미룰 수 없으므로 ID 미리보기도 비운다(개수는 남고 항목 inspect가 전체 ID를 준다). `awaiting`은 항상 남는다. 그래도 한도를 넘는 첫 항목(예: 4096 한도에서 512자 한글 snapshot)은 변경 전에도 한도를 넘던 크기이며, raw 한도 안이면 돌려줘 worker가 멈추지 않고 MCP edge는 기존처럼 `RESULT_TOO_LARGE`로 거절한다. pending item inspect는 넘긴 window가 있을 때만 최대 16개까지 보여 주고, wire 한도를 넘으면 목록을 줄여 `escalated_windows_partial`을 켠다. 표시가 하나도 들어가지 않으면 두 필드를 빼 변경 전 응답 모양으로 돌아간다. `memory_inspect` 도구 설명에 `pending` ref를 적었다.
- 남은 한계: admission이 없는 window와 cleanup manifest가 판단 불필요·revision 불일치로 끝나는 경로는 기존처럼 넘기지 않는다. 시간이 지나 claim 유효기간이 끝나는 식의 manifest 변화는 다음 inspect 전까지 반영되지 않는다.

### hook 경로의 필수 규칙 누락과 회상 지연

- OMP `read`의 줄 범위 같은 보기 지정(`src/a.py:1-20`, `data.json?q=…`, `archive.zip:member`)이 경로에 그대로 남아, 경로 selector가 있는 필수 규칙이 오류 없이 빠지던 문제를 고쳤다(I16). 이제 `read`는 `:`·`?` 앞에서 실제로 존재하는 가장 긴 경로를 대상으로 쓴다. 존재하는 경로가 없는데 마지막 경로 구성요소에 `:`·`?`가 있으면 없는 파일인지 보기 지정인지 알 수 없어 `HOST_FOOTPRINT_UNKNOWN`이다. 보기 지정 뒤에 `..` 경로 구성요소가 있으면 다른 파일을 가리킬 수 있어 역시 `HOST_FOOTPRINT_UNKNOWN`이다. 범위만 다른 read는 같은 파일이라 행동 직전 회상도 중복 제거된다. `write`·`edit`는 보기 지정이 없으므로 경로를 그대로 쓴다.
- hook의 1차 회상(행동 직전·`--prompt-recall`)은 새 `/api/hook-context`를 쓴다. 응답에 쓰지 않는 corpus 통계(`_stats`)를 계산하지 않는다. 이전에 실제 corpus에서 잰 `_stats` 시간은 약 1.3초였다. 새 경로의 회상 시간과 동시 hook이 2초 회상 예산 안에 드는지는 배포 후 측정한다. 통계를 평가하지 않았으므로 응답은 `partial: true`이고 `pipeline`·`coverage`·`health`를 넣지 않는다. MCP `memory_context`와 `/api/context`는 그대로 통계를 반환한다.
- 회상 검색(`search_lexical`)은 lock 없는 snapshot에서 검색·관계·원문 lineage·health manifest를 계산하고, 전역 clock lock은 credential 재확인과 admission 기록에만 짧게 잡는다. 검색과 기록 사이에 삭제가 commit되면(기록 transaction이 lock을 기다리는 동안 commit된 경우 포함) 한 번 다시 검색하고, 다시 바뀌면 `ADMISSION_STALE`이다. 실제 삭제 journal 불일치만 `DELETION_BARRIER`로 남는다. 그 사이 credential이 바뀌면 기존처럼 거절한다. admission은 검색이 본 snapshot의 epoch·deletion generation을 기록하며, 그 밖의 변경은 기존처럼 전달 시점 재검사가 거절한다.

### context 전달의 전역 lock 대기

- 읽기 전용인 `rules()`와 context `delivery`가 전역 `am_clock ... FOR UPDATE` lock을 잡던 문제를 고쳤다. delivery는 응답의 partial 판정용 corpus 통계(`_stats`, 실제 corpus에서 수천 번의 순차 DB 조회, 약 1.3초)를 이 lock 안에서 계산했다. 그래서 모든 agent의 read·write·edit hook(required-context와 행동 직전 회상)과 prompt capture가 한 줄로 기다렸다. 동시 hook은 4초 client 기한을 넘겨 `action: SERVICE_UNAVAILABLE`로 보였고, 같은 lock을 기다리는 입력 capture 때문에 Enter가 멈췄다.
- 두 경로는 이제 lock을 잡지 않는 read-only repeatable-read snapshot으로 실행한다. writer는 clock lock 아래에서 commit하므로 한 snapshot의 clock epoch·rule·통계는 같은 commit 시점을 가리킨다. stamp와 전체 rule 일치 검사, 철회·admission 재검사는 그대로다. 다른 lock 없는 reader(인증·health observer 등)는 요청 중 폐기된 credential을 반영하도록 문장 단위 읽기를 유지한다. 삭제가 journal intent를 쓰고 head를 commit하기 전 사이에 온 lock 없는 reader는 한 번 clock lock을 기다린 뒤 barrier를 판정한다. `/api/required-context`는 응답에 쓰지 않는 통계 계산도 하지 않는다.
- OMP는 input handler가 끝나야 제출을 queue에 넣는다. 확장이 capture 완료까지 기다려서, 같은 agent의 앞선 hook과 service 응답이 끝날 때까지 Enter가 멈췄다. 이제 input capture는 같은 agent queue에 동기적으로 넣고 기다리지 않는다. 그 제출의 preparation은 여전히 capture 뒤에 실행되어 연결 locator를 본다.
- `input: agents-memory: HOST_CAPTURE_DEGRADED` 경고가 전송만 미뤄진 capture에도 떴다. service가 잠시 바쁘거나 다른 hook이 같은 spool을 flush 중이면, local spool에 안전하게 남아 다음 hook이 보낼 capture도 pending으로 세어 경고했기 때문이다. 이제 이번 capture의 거절·격리·만료·유실, 남아 있는 격리 capture, service 혼잡이 아닌 flush 실패(credential 폐기 등), 5분을 넘긴 미전송 capture backlog만 경고한다. 결과의 `durably_spooled`·`pending` 표시는 그대로이며 전달됨으로 바꾸지 않는다. spool status는 health observation을 뺀 `oldest_pending_capture_seconds`를 함께 반환한다. OMP `/memory-status`는 실행 중인 input capture를 최대 2초 기다린 뒤 `queue_settled`와 함께 보고한다.

### 구독 CLI 판단 worker

- Jev 없이도 background worker가 원문 선택·관계를 자동 판단하도록 `subscription` provider를 추가했다. operator가 `judge policy allow-subscription --ack-egress`로 Jev와 독립된 default-deny 허가를 준 뒤 `judge set subscription --host claude|codex|omp [--model …] [--executable …]`로 선택한다. 선택할 때 CLI 절대 경로를 고정하고 합성 질문 1개로 로그인·모델을 확인한다. worker는 Jev와 같은 질문·임계값·서버 검증·fence로 기록하며, reason에는 `Subscription(<host>[:<model>])`이 남는다.
- 호출은 로그인된 CLI를 그대로 쓴다. 인증 파일은 읽지 않고, API 키·base URL·Bedrock/Vertex 전환 변수는 CLI 환경에서 지운다. 원문은 stdin으로만 보낸다. 호출마다 project 밖 private 임시 디렉터리에서 agents-memory hook·확장·skill·rule·세션 저장 없이 실행해 판단 호출이 다시 capture되지 않게 한다. OMP의 user MCP 도구 호출은 print 모드 승인 요구로 모두 거절된다. 재시도 없이 1회, 300초 기한, 출력·답 파일 4MiB 상한이다. 끝나거나 기한을 넘기거나 서비스가 멈추면, leader를 회수하기 전에 process group 전체를 종료한다. 마지막 허가 확인과 원문 전달은 judge authority lock 아래에서 수행하고, DB admission 재검사 뒤에 허가를 한 번 더 확인한다. choice 답은 모든 label·합 1·최댓값 선택을 검사한다. launchd의 최소 환경에서도 Node 기반 CLI와 Claude keychain 로그인을 찾도록 실행 파일 디렉터리를 `PATH` 앞에 두고 `USER`·`LOGNAME`을 채운다.
- 한 경로를 deny해도 다른 경로로 선택된 worker는 바뀌지 않는다. health 작업과 `health_dispositions`는 Jev 전용 health 전송 허가 대상이라 구독 worker가 보내지 않는다. `JevFailure`·`JevResult`는 공용 `ProviderFailure`·`ProviderResult`로 이름을 바꿨다.
- Jev 기본 모델을 `jev-1.14.0`으로 올렸다. 저장된 키로 합성 검증과 remember·kind 질문을 실제로 호출해 1.13.0과 같은 응답 형식임을 확인했다. 기존 배포는 `judge set jev --model jev-1.14.0`으로 명시 전환해야 하며, 저장된 키는 그대로 쓴다.

### 사용자 지시 없는 자동 회상

- advisory Claude·OMP 설치는 project 안 파일 read·write·edit 때 hook이 1차 `memory_context`를 대신 조회하고 admission·정확한 request·전체 후보 ID 목록을 모델 context에 넣는다. agent는 inspect 후 relevance만 제출한다. 판단하지 않은 후보 본문·미리보기는 넣지 않으며 전체 ID가 예산을 넘으면 일부 ID 대신 명시 gap을 넣는다. 같은 submission의 같은 경로는 다시 조회하지 않고, 실패는 기록하되 required 규칙과 행동 결과를 바꾸지 않는다. 기존 `manifest_not_delivered` 안내는 제거했다.
- `--prompt-recall`은 같은 handoff를 프롬프트 시점에 보조로 제공한다. Codex는 native 도구가 경로 목록을 안전하게 제공하지 않아 프롬프트 시점만 지원한다. strict는 변경 없음. `--no-action-recall`로 끈다.
- host 계약상 행동 직전 hook 내용은 그 도구 결과 뒤 모델에 전달된다. 읽지 않고 바로 쓰는 경우 후보는 쓴 뒤 도착한다.
- fork-experimental 설치에는 자동 회상이 없고, `--prompt-recall`은 admission·후보 ID 없이 설치된 recall workflow 실행 안내만 넣는다. strict Claude의 fork 선택은 쓰기 전에 거절한다. OMP는 terminal `agent_end` 뒤 같은 문장의 새 프롬프트를 새 submission으로 본다. evaluation gateway는 검증된 fork 자식의 inspect를 부모 기록과 분리해 pipeline 연결에 반영한다.

### 실험용 fork recall과 host별 평가

- [#17](https://github.com/chonamdoo/agents-memory/issues/17): Claude Code·Codex에 명시적인 `fork-experimental` recall 선택을 추가한다. 부모가 1차 조회와 최종 제출·수신을 맡고, 전체 대화를 상속한 fork 자식은 원문 inspect와 전체 manifest 관련성 판단만 맡는다. 기본 inline, required 독립 전달, 서버의 최종 span·revision·권한·철회·health 재검사는 유지한다. Jev provider와 독립이며 OMP 위임은 제외한다.
- 로컬 parent validator는 admission·전체 ID 집합·개수·완료 상태와 원래/현재 요청·작업 identity를 검증한다. 부분·취소·잘린 반환·다른 admission·맥락 변경은 최종 제출로 승격하지 않으며 자동 inline/fresh-child/Jev fallback하지 않는다. inspect-only는 실제 host 강제 제한을 확인한 경우에만 보장할 수 있다. 증거 파일은 호출별 project 밖 owner 전용 디렉터리에만 두고 끝나면 지운다. project 안·공유 디렉터리·symlink·hard link 증거는 거절한다. fork 설치는 `capabilities.recall`과 gap 경고를 receipt·설치 결과에 남긴다.
- 7–14일 실험 운영과 host별 inline/fork 비교 보고를 분리한다. 자식 inspection을 부모의 원문 이해로 세지 않고, 실제 native 입력·cache·총비용·지연·실패·gold 품질과 required/원문 계약 증거가 없는 host는 지원 기능으로 승격하지 않는다. 개발 태그 게시나 기간 경과 자체는 실측 합격이 아니다. 짝 비교에 `provider_route` 일치, arm 순서 교차, p95 표본 하한(20)을 요구한다. evaluation gateway의 fork 등록·완료 기록은 gateway lock 아래에서 수행한다.
- OMP의 입력·명시 capture가 실행 중 submission을 교체하거나 압축 callback이 그 submission을 지우던 lifecycle을 수정한다. preparation만 새 submission을 승격하고 capture identity·queued 입력 연결을 분리한다. 같은 문장의 입력이 대기 중이라 연결이 모호하면 submission을 바꾸지 않고 capture 연결을 남기지 않는다. session 교체·branch의 무효화, 실제 scope 실패와 strict 보호는 유지한다. preparation 없는 advisor도 부모 상태를 빌리지 않으며 가능한 required-context 조회·본문 전달은 시도한다.
- OMP callback의 queue·subprocess 전체 기한, bounded state-lock 대기, 남은 event 기한으로 제한한 service 요청, owned process 종료를 적용한다. `/memory-status`에 agent/session별 phase incident·code별 횟수·최근 실패·회복을 남긴다. 같은 code의 반복 warning은 집계하고 새 code는 처음 한 번 알린다. health 응답 형식도 검사해 잘못된 응답을 회복으로 표시하지 않는다. required 본문·명시 capture 결과와 실제 오류는 숨기거나 성공으로 바꾸지 않는다.
- OMP 행동 직전 required 규칙 본문이 `ctx.ui.notify`(사용자 화면 전용)로만 나가 모델 입력에 들어가지 않던 문제를 고쳤다. 이제 `tool_call` handler가 `additionalContext`를 반환하며, host 계약상 그 도구 결과 뒤 다음 모델 요청에 들어간다. 사용자 화면 표시는 유지한다.
- OMP hashline `edit`의 감싸지 않은 native 형식(`[경로#TAG]`+연산)을 `HOST_FOOTPRINT_UNKNOWN`으로 잘못 분류하던 문제를 고쳤다. `*** Begin Patch`로 시작했지만 끝나지 않은 입력 등 실제로 불완전한 입력은 계속 unknown이다.
- OMP 확장은 backend가 capture 가능으로 받아들인 입력에만 연결용 digest를 만든다. secret으로 거절된 입력은 확장 메모리에서도 hash·보관하지 않는다. secret으로 거절된 preparation은 진행 중 submission·generation을 바꾸지 않는다. `agent_end`는 `willContinue:true`(또는 `isTerminal:false`)면 진행 중으로 본다. 같은 세션 재시작·전환에서는 하위 agent를 포함한 모든 agent의 lifecycle을 초기화한다. 짝 비교는 frozen attempt·generation 재사용을 `DUPLICATE_EXECUTION_EVIDENCE`로, pipeline 사용량이 부모(+포함된 자식)보다 작으면 `USAGE_ACCOUNTING_INCONSISTENT`로 거절하고 고유 실행만 지연 표본으로 센다. fork 증거 디렉터리의 project 밖 검사는 대소문자·firmlink 다른 표기에도 파일 identity로 비교한다.
- `memory_context` MCP 설명에 fork 안내를 넣으면 최대 escaped JSON-RPC ID의 `tools/list` 응답이 16KiB를 넘었다. 전역 설명은 원래대로 두고 fork 안내는 opt-in skill에만 둔다.
- 작업 checkout에서 만든 sdist가 추적하지 않는 로컬 파일(검증용 DB·credential·trace)을 포함할 수 있었다. sdist를 추적 대상 최상위 항목으로 제한했다. 새 확장과 skill은 owned 재설치·host reload가 필요하다.

### advisory 설치의 project 밖 행동 경고 제거

- non-strict(OMP·Codex·Claude advisory) 설치에서 project 밖 행동·세션에 `HOST_SCOPE_UNRESOLVED` 경고를 내지 않는다. 대상이 모두 등록 project 밖인 행동(다른 worktree·`/tmp`·시스템 설정 등)과 cwd가 project 밖인 세션의 event는 `outside_advisory_coverage`로 끝나며 capture·context 전달·상태 기록을 하지 않는다. 그 세션의 명시 OMP capture 명령은 `not_captured` info를 표시한다. 일부 대상만 project 안인 OMP hashline edit은 그 대상의 규칙만 전달하고, 대소문자·Unicode 정규화만 다른 project 경로는 안으로 판정한다. cwd가 없거나 삭제된 event와 strict(Claude)는 기존처럼 거절한다.

### 명시 health 작업과 서비스 background 관측의 잠금 경합

- 로컬 서비스의 spool recovery가 등록 workspace를 주기적으로 관측하며 `health.lock`을 잡고, 관측을 queue에 넣은 뒤에는 spool flush lock 아래에서 전송한다. 그 사이 명시 `health workspace-register`·`health observe` CLI와 MCP `memory_context` 직전 관측이 즉시 `HEALTH_OBSERVER_BUSY` 또는 `HEALTH_OBSERVATION_UNCOMMITTED`로 실패하던 경합을 고쳤다. CI health smoke가 간헐적으로 이 오류로 실패했다. 명시 작업은 두 잠금을 합쳐 최대 10초 기다리고, 자동 hook과 background recovery는 기존처럼 기다리지 않는다. 한도를 넘으면 같은 오류다.

### CI 설치 wheel consumer 시간 예산

- 설치 wheel consumer 제한을 300초에서 600초로 올렸다. 약 900개 사례를 새 process로 다시 실행하는 현재 subset이 정상 runner에서도 290–305초가 걸려 main CI(`6ab6118`, run 39209425762)가 58% 지점에서 timeout으로 실패했다. lint 120초·build 300초·source shard 600초와 job 15분 제한, timeout을 실패로 집계하는 aggregate는 그대로다.

### OMP MCP tool device 호출 경고 분류

- OMP가 discoverable MCP 도구를 `write xd://<tool>`로 호출할 때마다 `HOST_FOOTPRINT_UNKNOWN` 경고가 뜨던 문제를 고쳤다([#13](https://github.com/chonamdoo/agents-memory/issues/13)). agents-memory core 도구 4개의 정확한 device 경로는 `delegated`, 그 외 `xd://` device `write`는 resource `read`와 같은 `outside_advisory_coverage`로 분류한다. `conflict://`·`vault://` 등 project 파일을 바꿀 수 있는 다른 scheme의 `write`, 로컬 경로 `write`의 footprint·required-context·범위 검사와 잘못된 경로의 `HOST_FOOTPRINT_UNKNOWN`은 유지한다. Claude·Codex non-strict는 MCP 호출을 hook으로 보내지 않아 같은 경고가 없음을 확인했다. 생성 확장(`omp.ts`)은 바뀌지 않으며 receipt가 가리키는 설치본의 패키지를 갱신하면 적용된다.

### OMP resource read 경고 분류

- advisory resource read를 로컬 경로의 `HOST_FOOTPRINT_UNKNOWN`으로 오분류하지 않고 기존 `outside_advisory_coverage`로 구분한다. scheme allowlist·backing path 추정·알림 필터는 추가하지 않으며 callback·receipt/envelope/cwd·실제 로컬 경로/required-context·IPC 거절은 유지한다.
- native selector와 공백·대괄호 파일명도 URL host 규칙으로 거절하지 않는다. 실제 생성 확장→Python hook→알림 소비와 별도 설치 wheel의 실패→성공, 독립 리뷰에서 발견한 추가 사례 및 검증 한계는 [검증 기록](docs/verification.ko.md#omp-resource-read의-host_footprint_unknown-수정)을 따른다. 이미 설치·로드된 확장의 갱신은 별도다.

### PR CI의 최소 MCP 응답 한도 회귀

- 임의의 고정 envelope 예약을 최대 escaped 요청 ID와 실제 SDK envelope 크기로 교체했다. 최신 SDK의 `resultType`·`serverInfo`와 기존 stamp를 포함하며 실제 server identity를 공유한다. 4096-byte 최소 한도에서 원문 inspect·grounded 게시와 긴 기록의 완전한 continuation을 보존하고 응답 상한·ID admission은 올리지 않는다.
- changed CI 합성 영수증에 이미 필수인 owned worker 종료·전송 증거를 보완하고 각각의 누락·잘못된 승인 주장·추가 retry를 거절하는 회귀를 추가했다. production aggregate는 완화하지 않았다. source·별도 설치의 실제 red/green과 독립 재리뷰는 [검증 기록](docs/verification.ko.md#pr-ci에서-드러난-mcp-응답-예산-수정)을 따른다.

### 명시적 메모리 건강 관리와 평가 engineering

- 코드/worktree/root·파일/Python AST symbol anchor와 현재 health dependency를 claim의 검색·admission·게시·최종 delivery·관계 입력에 연결했다. required rule을 ordinary stale 필터로 숨기지 않는다.
- 이미 허용된 관측 segment와 close watermark를 bounded pending으로 연결하고 다음 권한 있는 agent/별도 허용 Jev가 판단하는 경로를 추가했다. 새 transcript 수집·구독 agent 깨우기·자동 정정/승격/삭제는 추가하지 않았다.
- relevance·support/정확성 판단·freshness와 exact-revision operator Accept/Reject를 분리했다. 늦은 판정·삭제·철회·권한 변경·code 변경을 다시 검사한다. `0007_memory_health`와 archive/init/restore closure를 연결하며 restored source의 ordinary claim은 최신 판정 증거 없이 재사용하지 않는다. 새 health disaster ledger는 없다.
- shutdown의 false drain·eventual join·원래/동시 실패를 보존하고 실제 ASGI/Uvicorn 노출 진단을 body-free로 제한했다. proposal의 전체 UTF-8 body/예외/exact source revision inspect와 권한 제한 shared-rule projection을 구분했다. coverage·stats·pending·health 분모의 current request_snapshot/policy/review dependency 자격을 통일했다.
- workspace 등록의 malformed ACK와 건강 입력의 중첩 validation 실패를 각각 bounded unknown-effect·항목별 incomplete로 처리한다. 준비 파일·기존 활성 설정·미완료 작업을 보존하고 사적인 validation 세부를 출력하지 않는다.
- 공유 outbox에서 건강 거절·unknown ACK·queue full이 독립 capture를 굶기지 않도록 분리하되 ordinary capture의 unknown 앞 FIFO는 보존한다. 같은 committed code fingerprint의 receipt를 재사용하고 확정 미commit quarantine·bounded session metadata 경쟁을 처리한다.
- code 관측의 payload 만료·receipt 소실 뒤 현재 workspace/root와 더 높은 sequence의 실제 새 관측으로 복구한다. 원래 unknown·expiry/gap 이력·미완료 payload fence는 보존하며 새 committed ACK와 서버의 늦은 구형 sequence 거절을 요구한다.
- 다음 source-selection의 accepted context에 ordinary health 재사용 자격을 적용하고, exact Reject·현재 공개 가능한 사유를 별도 bounded `health_dispositions`로 전달한다. 발견과 admission·최종 검사가 같은 claim/event/reason 공개 자격을 사용하며 확인된 부적격 review가 무관한 원문 판단을 막지 않는다. 실제 표시한 health/code/review/reason dependency를 admission에 묶되 독립 근거나 내용 전체의 금지 목록으로 승격하지 않는다.
- 다음 Jev 판단에도 별도 health 허가가 있을 때만 exact Reject 사유·현재 revision advisory를 연결한다. 원문·advisory·기존 비교 근거의 전체 state input budget과 긴 사유의 incomplete 표시를 보존하며 일반 원문 판단·독립 근거를 blacklist로 막지 않는다.
- source·cleanup·health의 실제 첫 HTTP 시도·재시도·다단계 호출마다 원래 admission의 현재 권한·source/claim·snapshot·disclosure·health dependency를 canonical Store 경계에서 다시 확인한다. DB lock을 network 동안 잡거나 admission을 새로 만들어 철회를 우회하지 않는다. 이미 전송한 요청의 회수나 외부 wire 원자성을 주장하지 않는다.
- strict decoder의 공개 typing을 실제 Pydantic `BaseModel`과 임의 값의 `TypeAdapter` 두 소비 형태에 맞췄다. 기존 strict JSON/schema/오류 의미는 유지했다. R35–R37의 실제 source·설치 소비 실패→성공과 owned HTTP worker 증거는 [검증 기록](docs/verification.ko.md)을 따른다.
- 고정 manifest/전체 attempt ledger·정책을 상속하는 native CLI driver·required-only off/실제 wire gateway·immutable artifact/허용 diff witness·격리 Docker oracle/control·pair scheduler·cluster bootstrap/unknown cost·평가 CLI와 명시 health evidence compiler를 추가했다. task 성공은 자동 support/freshness나 인간 승인이 아니다. raw diagnostic gold와 engineering oracle은 `provided_unattested`이며 인간 holdout을 만들어 채우지 않는다.
- 건강 판정용 retained evidence는 private observation array를 포함해 bounded byte-exact로 보존한다. object 조건은 실제 typed object 소비 지점에서 검사하며 receipt·terminal·digest·현재 authority 검증은 유지한다.
- MCP catalog는 flat root와 variant의 required/allowed/null 제약을 유지하면서 schema 참조·중복을 줄였다. 실제 최대 escaped JSON-RPC ID의 응답 상한을 올리지 않는다. 출력 상한에 걸린 Docker exec는 container removal 전에 닫고 기존 deadline/TTL·소유권·exact cleanup을 유지한다.
- 복구 주기의 공유 discovery cursor를 직렬화하고 상태 갱신을 동기화했다. 새 scan이 끝나기 전에 이전 실패를 idle로 숨기지 않는다. 실제 `/readyz` 실패 전후와 event로 멈춘 scan의 판정 유지·후속 복구를 source/설치 wheel에서 검증했다.
- interrupted intent의 증명된 private-writer 임시 hardlink를 소유권 경계에서 복구한다. 읽기 전용 report는 ledger를 고치지 않고 unknown 분모를 보존하며, resume의 정리는 재실행 허가가 아니다. 임의·추가·symlink·비소유 link 및 frozen input의 single-link 제한은 유지한다. 별도 source/설치 wheel 실패→성공과 전체 engineering smoke를 Actions에서 검증했다.
- measured corpus/rules를 `schema=2`로 전환하고 실제 `context_renderer`를 frozen source identity에 포함했다. applicable optional rule과 eligible 관계의 전체 집합·의미·revision/digest를 고정해 arm 전후와 실제 context에 대조한다. bounded prefix·미리보기만으로 완전성을 추정하지 않으며 controller의 judgment 권한을 native에 넘기지 않는다.
- 독립 packing의 costed claim을 승인 projection의 완전한 의미·조건·예외·시점과 모든 evidence의 provenance에 연결했다. input digest를 다시 맞춰 내용·optional rule·관계를 줄이거나 바꿔도 완전한 F로 받아들이지 않는다. 불완전한 입력은 unknown을 유지한다.
- native delivery credit을 tool 반환에서 실제 downstream stdio response의 완전한 write로 옮겼다. 원래 ID·tool/arguments·payload·MCP metadata stamp와 wire bytes를 맞추며 부분 write·output cap·취소·deadline·중복 ID·대체 응답·receipt 실패를 완료로 세지 않는다. health evidence는 모든 유효 invocation의 실제 gateway trace를 보존·재검증하며 write 완료를 모델 소비로 확대하지 않는다.
- control 선검증에도 pair/current subject와 같은 stop event를 전달한다. 취소된 첫 control의 부분 receipt·intent·cleanup을 보존하고 후속 control과 잘못된 eligible 승격을 막는다.
- 평가 gateway가 candidate/final dispatch 전에 frozen `limit`·`max_bytes`·정규화한 `code_workspace_id`를 강제한다. 원래 workspace가 null인 경우의 생략/null 동등성은 보존한다.
- 필수 frozen `native_tool_mapping`과 immutable native-tool-link를 추가했다. 실제 native tool start/result·invocation/generation·정확한 arguments/result와 완료 gateway write를 연결하고 health export/replay에서도 검증한다. 별도 MCP client/agentMessage만의 성공, 다른 호출·server·결과·generation은 credit이 아니다. Codex native lineage와 JSON-RPC ID를 구분하고 Claude의 모호한 병렬 반복은 비교 불가로 남긴다. provider 소비·native 보호 증거로 확대하지 않는다.
- post-spawn helper 생성자 interruption과 selector 생성/close 실패에서도 owned process group을 reap 전 종료하고 bounded final wait·모든 pipe close를 시도한다. 원래 실패와 cleanup 실패를 함께 보존하며 미관측 회수를 성공으로 숨기거나 timeout을 늘리지 않는다.
- health work가 claim의 전체 typed 의미·조건·예외·부정/양태·valid time을 admission과 두 판단 단계에 보존하고 전체 JSON을 기존 byte budget에 계산한다. 의미가 빠지거나 예산을 넘으면 statement-only 판단으로 잘라내지 않는다. 같은 statement의 offline 조건이 online 정정 때문에 잘못 격리되는 회귀를 실제 건강 상태와 recall로 검증했다.
- candidate↔final context는 정규화한 내부 identity로 상관관계를 확인해 같은 default 생략/명시·null 전환의 실제 final read를 잃지 않는다. native/wire 원래 arguments·frozen scope·실제 write credit은 유지한다.
- native 제출은 실행 전에 승인 root descriptor를 고정하고 모든 경로 성분을 no-follow로 읽는다. root 교체·symlink·backtracking·hardlink·변경된 leaf를 수입하지 않으며 정상 nested 제출과 bounded cleanup을 보존한다.
- 초기 model 이름과 실제 실행 관측을 분리한다. driver·controller·health replay는 같은 typed model observation으로 Claude main 변경·다른 helper model·미귀속 pipeline 혼합과 Codex correlated/uncorrelated/malformed reroute를 구분한다. A→B→A·원래 identity/제출·완료 시도·usage/비용 미관측·cleanup과 전체 분모를 보존하며 pipeline 혼합만으로 main fallback을 단정하지 않는다.
- operator의 exact `close_unknown`은 늦은 capture·동일 입력 refresh·refresh 실패에도 원래 disposition/event와 닫힌 admission을 보존한다. 실제 새 입력은 revision fence만 갱신하며 최신 revision·권한·capacity를 검사한 explicit reopen과 machine-assessed 작업의 재등록을 구분한다.
- feedback 판정 사유의 source 읽기는 기존 disclosure 경계에서 현재 실제 target 자격을 재검사한다. 전역 공개를 request snapshot에 묶거나 지워진 후보·사유 원문 때문에 본문 없는 독립 판정 이력을 삭제하지 않는다.
- `1541ec4`의 [Actions39101868318](https://github.com/chonamdoo/agents-memory/actions/runs/39101868318)는 R14–R17 수정 후 source3127·별도 설치741·실제 Docker14·Mac ownership36, 양쪽 실제 health HTTP/CLI25개 outcome·전체 평가/health 소비·cleanup·canonical comments·8job strict aggregate를 통과했다. corrected-before16개 node의 전 phase 비교와 과도한 metadata 거절 기대·credential 혼용 fixture 실패는 [검증 기록](docs/verification.ko.md)에 구분 보존했다. fresh 전체 inherited source review·CI-only QA와 원래18개 외부 acceptance는 별도다.
- Claude assistant의 실행 model 필드 누락도 null과 같은 관측 불명으로 처리한다. 실제 stdio 완료·제출·usage는 보존하되 driver·controller·health replay가 frozen identity나 comparable 결과로 승격하지 않는다. 현재 다른 helper model의 허용 manifest는 없으며 pipeline 혼합의 비교 불가 한계를 명시했다.
- health 사유 source의 소유권·현재 target을 같은 bounded 재귀 disclosure manifest에 포함했다. 중첩 feedback의 다른 snapshot 공개와 구형 admission을 거절하되 정상 전역 target과 본문 없는 독립 판정 이력을 보존한다.
- bounded HTTP reader가 적용 가능한 `Content-Length`와 실제 본문 길이를 대조한다. 짧은 EOF의 유효 JSON을 producer202 ACK나 오류의 확정 효과로 받아들이지 않으며 정상 fixed/chunked/EOF framing·deadline·unknown 비재전송을 유지한다. relay의 중복 길이 검사는 공통 경계로 통합했다.
- operator event 없는 machine `deferred_unknown`을 명시 종결과 구분해 실제 새 근거의 capacity-checked 재등록을 보존했다. operator의 exact `close_unknown`·구형 revision 거절·명시 reopen 권한은 유지한다.
- `acb131c`의 [Actions39107089779](https://github.com/chonamdoo/agents-memory/actions/runs/39107089779)는 R18–R21 수정 후 source3138·별도 설치752·실제 Docker14·Mac36, 양쪽 health HTTP/CLI25 outcome·전체 평가/health 소비·cleanup·lint/build/comments·strict aggregate를 통과했다. 같은6개 유효 before node의 전 phase 성공과 앞선 fixture 실패를 [검증 기록](docs/verification.ko.md)에 분리 보존했다. 직전 정상 review의8approve/3request-changes/1timeout은 새 source 승인이나 whole-PR coverage가 아니다.
- revoke된 producer의 남은 workspace 등록을 operator health observer에서 현재 권한에 따라 제외한다. registry 조회 뒤 revoke된 경우도 같은 credential 경계를 사용하며 호출자401·agent403·예상 밖 `DATABASE_BUSY`503은 보존한다. scoring `evidence_refs`의 공개 annotation과 validator 반환 타입을 실제 읽기 전용 `Mapping`에 맞췄으며 기존 bounded JSON serializer는 유지했다.
- context의 workspace-scoped `withheld`·`unknown_assessments`와 binding/snapshot-wide `closed_unknown_work`를 문서에 구분했다. R20의 stdio relay 오류 코드 전환과 private incomplete-prefix 비보존을 명시하되 unknown·비재전송 의미는 바꾸지 않았다.
- `31f9f7c`의 [Actions39110710800](https://github.com/chonamdoo/agents-memory/actions/runs/39110710800)는 source3140·별도 설치754·실제 Docker14·Mac36·양쪽 실제 health HTTP/CLI25개 outcome·전체 평가 소비·owned cleanup·lint/build/comments·strict aggregate를 통과했다. 유효 `09e1b58` before의 두401 node와 실제 CLI `AUTH_DENIED`를 대조했고, 초기 잘못된 Store patch와 smoke `Role` NameError/F821은 별도 fixture 실패로 보존했다. 직전 review10approve/1request-changes/1timeout은 새 source나 전체 미검토 영역의 승인이 아니다.
- 설치된 canonical comment 정책과 같은 공개 immutable source/checksum을 Actions에서만 실행한다. 정확한 PR base/head의 전체 old/new code와 source·coverage receipt를 확인하며, 누락·불일치·정책 실패는 aggregate가 거절한다. 로컬 hook·guard·trust·settings·pins 변경은 없다.
- revoked 타 producer 때문에 정상 code relink가 중단되지 않도록 현재 authority를 검사하되 자기 caller401·scope/refusal·예상 밖 오류는 보존한다. journal로 철회한 health pending은 늦은 capture/session boundary 때문에 재개하지 않는다.
- Jev health의 비허용·불완전 입력을 shared paid budget에서 제외하고 같은 binding/snapshot/item의 최신 health·policy·provider·egress revision별 실패를 보존한다. 일반 source/cleanup·후속 binding 진행과 stop·권한 실패의 의미를 유지한다.
- 평가 CLI는 typed `EvaluationError`의 bounded code를 보존하고 일반 private 오류는 generic으로 남긴다. scoring/diagnostic 모델의 내부 `schema_version`과 외부 `schema` alias를 분리해 import 경고가 실제 CLI JSON 오류 출력을 오염시키지 않게 했다. warning filter는 추가하지 않았다.
- 생성 OMP hook은 실제 hashline edit의 전체 bounded 파일 footprint만 전송하고 원문 patch를 전달하지 않는다. capture는 누적 영수증 만료 이력과 현재 실패를 구분하며 이력·대기·격리 상태는 보존한다. 기존 설치본을 자동 변경하거나 native strict 지원을 추가하지 않는다.
- `a33615c`의 [Actions39120772813](https://github.com/chonamdoo/agents-memory/actions/runs/39120772813)에서 위 수정의 source·별도 설치 소비와 기존 전체 engineering gate를 통과했다. 유효 red/green·지원하지 않는 workspace 상태 fixture의 제외·중간 실패·정상 review의 request-changes는 [검증 기록](docs/verification.ko.md)에 구분했다. fresh whole-source review/QA와 원래 외부 acceptance 완료로 확대하지 않는다.
- file-effect observer 전에 exact owned container를 Docker daemon으로 동결하고 subject quiescence를 확인한다. 잔존 process나 불명 inventory·freeze/unfreeze 실패는 oracle 성공이 아니라 `runtime_unknown`이며 frozen 자원도 기존 owned cleanup으로 제거한다. 정상 private file·expected nonzero exit는 유지한다. 실제 defect before와 방어 후 [Actions39136163814](https://github.com/chonamdoo/agents-memory/actions/runs/39136163814)의 경계를 [검증 기록](docs/verification.ko.md)에 구분했다.
- `78184763`의 [Actions39077297030](https://github.com/chonamdoo/agents-memory/actions/runs/39077297030)는 R5–R9 수정 후 source3061·설치 wheel685·실제 Docker14·Mac compatibility36, source/설치 health·전체 native-event/health consumer·owned cleanup·8job strict aggregate를 통과했다. 두 test-only before와 중간 caller/fixture 실패를 보존한다. fresh whole-source canonical12review/QA는 별도 미완료다. source별 결과는 [PR9](https://github.com/chonamdoo/agents-memory/pull/9)와 [검증 기록](docs/verification.ko.md)을 따른다. 합성 native protocol peer를 실제 native 승인·모델 효익으로 세지 않으며 로컬 runtime 검증·native trust/운영/egress·human120/60task×3·실제1–2주 trial·merge/release 실행을 승인하거나 완료한 기록이 아니다.
- `76254a76`의 [Actions39079833321](https://github.com/chonamdoo/agents-memory/actions/runs/39079833321)는 R10–R12 수정 후 source3079·설치 wheel703·실제 Docker14·Mac compatibility36, 양쪽 health·전체 평가 consumer·owned cleanup·strict aggregate를 통과했다. genuine before의 source3062pass10fail/설치686pass10fail와 같은 node의 phase 비교를 보존한다. fresh whole-source canonical12review/QA와 원래18개 acceptance는 별도 미완료다.
- `5524a835`의 [Actions39084573279](https://github.com/chonamdoo/agents-memory/actions/runs/39084573279)는 R13 수정 후 source3088·설치 wheel712·실제 Docker14·Mac compatibility36, source/설치 health·전체 평가/health consumer·owned cleanup·strict aggregate를 통과했다. 제품 불변 test-only before의 source3080pass8fail/설치704pass8fail와 같은9node의 모든 phase 성공을 보존한다. 전체 지시/누락 전수 재대조·잔여 개발과 fresh canonical12review/QA·원래18개 acceptance는 별도 미완료다.

### 전수 재대조 후 잔여 경계 수정

- health item·feedback 이유의 현재 target/source disclosure와 snapshot을 재검사하고 전역 claim의 독립 게시·전역 reject floor는 유지했다. request-scoped selection audit를 전역 claim의 새 공개 제한으로 사용하지 않는다.
- 닫힌 bounded 관측 창의 작업 처리와 사실의 support/freshness·source coverage를 분리했다. operator 전용 exact-revision `health_work_disposition`의 unknown 종결·명시 reopen, capacity 검사와 late-result fence를 추가했으며 이미 resolved인 불완전 refresh는 unknown history로 보존한다.
- context의 bounded health partial metadata와 opaque quarantine 발견 경로를 연결하고 건강 분모·health reusable view의 current policy/dependency 자격을 공유했다. 인간 Accept 기록을 current source 분류로 승격하지 않는다.
- final recall의 관계 입력을 admission과 같은 workspace로 제한해 무관한 workspace의 code-linked 관계가 유효 전역 기억을 차단하지 않게 했다.
- recovery의 예상 밖 cycle 실패를 body-free로 남기고 stop 취소 뒤에도 task 소유권·join을 유지한다. 초기 인증의 `DATABASE_BUSY/not_started`와 judge 상태 실패의 정직한 readiness unavailable을 보존한다.
- backup/restore/recover의 모든 owned finalizer를 시도하며 원래 실패·bounded cleanup 실패·알려진 committed 효과를 구분한다. CLI Ctrl-C는 bounded `COMMAND_INTERRUPTED/unknown`·exit130으로 보고하며 SIGTERM과 native signal 의미는 바꾸지 않는다.
- 평가 gateway receipt를 digest-bound 단일 파일로 연결해 유효 terminal 완료를 중복 본문 크기로 잃지 않게 했다. report/health 소비자를 함께 이주하고 원래 byte/event/deadline·전체 attempt·unknown·cleanup을 유지한다.
- 원래14개 경계의 genuine Actions before와 후속 setup/call/teardown 성공, 잘못된 fixture·전역 공개 scope 진단·operator denial 기대를 구분해 보존한다. 정확한 새 전체 CI·정규 review/QA 범위는 [검증 기록](docs/verification.ko.md)을 따르며 checkpoint push를 final 검증·원래18개 완료로 표현하지 않는다.
- [Managed Agents 영상 보안 검토](docs/research/2026-10-18-managed-agents-security.ko.md)는 자막·공식 문서·현재 credential/격리/복구 경계를 대조한 조사다. 새 vault/event store·원문 수집·운영/egress/trust 변경은 채택하지 않았다.



- `b4c450c4`의 [Actions39095319703](https://github.com/chonamdoo/agents-memory/actions/runs/39095319703)는 전체 source3114·별도 설치 wheel728·실제 Docker14·Mac ownership36, 양쪽 실제 health HTTP/CLI23outcome·전체 평가/health·owned cleanup·8job9artifact strict aggregate를 통과했다. current-policy denominator의 genuine before와 잘못된 operator denial 기대의 정정을 구분한다. 문서 포함 head·fresh whole-source canonical12/QA와 원래18개는 별도이며 로컬 검증·실제 native/운영/trial·merge/release를 실행한 것은 아니다.

### CI 전용 검증 전환과 OSS 후속 보완

- GitHub Actions에 실제 PG18/pgvector·지원 Python/SQLite·Node·native PG18 도구·age 준비, 전체 collection의4개 disjoint shard, lint/build·설치 wheel 소비, 누락/skip/실패/source drift·artifact mismatch를 거절하는 최종 집계를 구성했다. raw failure/captured output 대신 outcome-only JUnit을 업로드한다.
- purge/reconcile의 동일 값 UPDATE를 null-safe 조건으로 억제했다. restore된 payload 재-scrub·삭제 floor·global clock·operation epoch 의미는 유지한다.
- adapter6의 생성 hook/MCP에 Python `-I`를 적용하고 validated v5는 owned cleanup/reinstall만 허용한다. pending spool·foreign native/Agent Flow 설정은 보존한다.
- serve/service-run은 lifespan 전에 configured socket을 확보하며 bind 실패를 `SERVICE_BIND_FAILED/not_started`로 반환한다. 임의 port fallback·기존 listener kill은 없다.
- ingress 권한 재확인, stop 가능한 remote TCP/TLS/GET·최초 send, 이미 전송한 business drain, retained bad-first recovery 공정성, service uninstall 효과·upgrade 순서의 회귀를 추가/보완했다.
- [OSS 후속 조사](docs/research/2026-10-16-oss-followup.ko.md)에서 원인·고정 PR/source·회귀·license·평가 방법과 추가 적용/기존 반영/보류/거절을 구분했다. paired 평가의 identity·전체 attempt 분모·oracle 대조군·최종 artifact 불변 계약을 보완했다.
- 첫 실제 두 CI 준비 실패와 uv selector 충돌 원인을 보존했다. `c59377e`의 [실제 Actions](https://github.com/chonamdoo/agents-memory/actions/runs/38917025242)는 전체2408/skip0·lint/build·설치 wheel subset31을 통과했다. 이는 해당 source의 CI 증거이며 이후 수정·native acceptance·정상 QA/handoff·release 승인이 아니다. 로컬 test/collection/lint/build/추가 smoke는 실행하지 않았다.
- 그 source의 정상 공식 리뷰는 request-changes를 유지했다. README를 원래 owned service uninstall→새 entrypoint의 config migration 순서로 맞추고, installed replay의 durable intent 제거 효과와 CI timeout의 잔존 process-group 정리를 보완했다. file publication 오류는 DB 장애로 바꾸기 전에 구분하며 실행 host template도 CI source digest에 포함한다. 새 회귀는 수정 전/후 GitHub Actions에서만 검증한다. 원본 reviewer timeout과 외부18개 acceptance는 별도 보존한다. 정확한 source·실행·리뷰 상태는 [검증 기록](docs/verification.ko.md)을 따른다.
- 후속 `bc30804`의 [Actions38922413453](https://github.com/chonamdoo/agents-memory/actions/runs/38922413453)는 전체2430/skip0·lint/build·별도 wheel31을 통과했다. 그 전 regression-only20실패와 첫 수정본의 기존 mock-echo assertion5실패도 보존했다. 실제 파일 오류 분류·durable 효과·명시 복구 검증은 유지하며 주입한 DB 오류값을 모든 DomainError에 기대하던 assertion만 제거했다. 이는 정상 fresh review/QA/handoff나 full issue5·출시 승인이 아니다.
- 후속 양 모델12개 angle은 실제 approve였지만 원래 요구 범위의 service readiness upgrade 오류와 소멸한 PGID 재신호 위험은 controller request-changes로 남겼다. owned config의 `CONFIG_UPGRADE_REQUIRED`를 readiness에도 보존하고, TERM/존재 확인에서 이미 사라진 group은 다시 신호하지 않되 owned parent reap·살아 있는 자손의 TERM/grace/KILL은 유지한다. 회귀-only Actions의 실제2435건 중5실패를 보존했고, 수정본877a56d의 [Actions38929819006](https://github.com/chonamdoo/agents-memory/actions/runs/38929819006)는 전체2435/skip0·lint/build·별도 wheel31과 앞선5건의 setup/call/teardown을 모두 통과했다. 이 수정본의 fresh formal review·QA/handoff와 외부 acceptance는 별도다.
- `8aa611b` 당시 설치 wheel 실행기와 집계는 단일13-selector 정책을 공유했고 checks에도 실제 owned PG 준비를 요구했다. self-consistent한 import-only receipt를 승인하던 회귀의 Actions 실패2건을 보존했다. [Actions38977685346](https://github.com/chonamdoo/agents-memory/actions/runs/38977685346)는 전체2436/skip0·lint/build와 별도 noneditable wheel85를 통과했다. 설치 소비에 service readiness·HTTP/MCP·operator 권한/publication·native child 정리·TLS stop/drain·bad-first recovery 및 ESRCH 뒤 PGID 재사용 주입의 native 두 경계를 포함한다. fixture 수준의 설치 소비를 실제 native activation·운영 cloud·kernel PID wraparound·human trial/출시 승인으로 확대하지 않는다.
- 정상 독립 리뷰의 group leader 조기 reap P1를 수용했다. native/CI cleanup은 중간 poll 없이 leader PID를 최종 group 신호까지 보존하고 이미 reap된 입력에는 신호하지 않는다. grace 상수·deadline·최종 parent wait는 유지하지만 Linux에서는 zombie leader 때문에 full grace를 기다리는 지연이 생긴다. 이 안전성 trade-off와 실제 call phase 측정은 [검증 기록](docs/verification.ko.md#group-leader-소유권-보존--7df1eb4)에 명시하며 macOS 지연은 추정하지 않는다. malformed fixture의 취소 이력을 보존했고, 유효 Actions의 실제 source4/installed-native2 실패(-9/-15) 뒤 7df1eb4의 [Actions38982950669](https://github.com/chonamdoo/agents-memory/actions/runs/38982950669)는 전체2440/skip0·lint/build·별도 설치87을 통과했다. MCP 증거도 직접 Store capture 후 modern/legacy inspect→record와 별도 HTTP producer 권한 거절로 좁혔다. 실제 kernel wraparound·native 활성·운영/평가/출시 승인을 주장하지 않는다.
- macOS CPython3.12에 없는 `os.waitid` 때문에 ownership 회귀8건이 setup 실패하던 지적을 수용했다. kqueue exit 등록 뒤 child를 해제해 reap 없는 관측을 보존하고, fault injector의 owned group만 가상 처리하되 소유권 상실 시 실제 survivor에 신호하는 조건을 유지한다. 제품 exception을 삼키거나 Mac을 skip하지 않았다. 병렬 Mac3.12 job과 exact-runtime/node/phase/source 집계를 추가했다. before8setup 실패와 첫 수정6통과/2call 실패를 보존했고, 92cc360의 [Actions38987056695](https://github.com/chonamdoo/agents-memory/actions/runs/38987056695)는 별도 Mac8·Linux full2443·설치87 및 lint/build/aggregate를 통과했다. 이는 실제 native 보호나 Mac 전체 suite·운영/평가/출시 승인 증명이 아니다.
- 후속 정상12개 독립 리뷰는5approve/7request-changes였고 “fixture만의 문제” 진단이 불완전했음을 확인했다. Darwin 제품 cleanup의 EPERM은 reap 없는 leader exit와 원자적·고정 크기 libproc group census가 **그 leader 하나만** 확인할 때만 terminal로 분류한다. live leader/다른 member/관찰 실패의 권한 오류는 유지한다. 정상 EOF/TERM inventory의 유효 before4실패와 첫 제품 수정의 kqueue context-manager TypeError8실패를 보존했다. `contextlib.closing`으로 고친2656828의 [Actions38991986933](https://github.com/chonamdoo/agents-memory/actions/runs/38991986933)는 실제 Mac16·Linux 전체2451·별도 설치92와 lint/build/aggregate를 통과했다. 실제 setuid/native 보호·Mac 설치 wheel·운영/평가/출시 승인으로 확대하지 않으며 원래18개는 완료0개다.
- 후속 독립 리뷰9approve/3request-changes가 찾은 테스트 finalizer의 reap 뒤 PGID 신호를 제거했다. 두 회귀는 공통 private IPC·원본 Popen 정리를 사용하며 별도 실제 process 생존과 reap 뒤 살아 있는 자손의 해제를 검증한다. FIFO EOF는 nonblocking read를 먼저 관측하고 집계는 매개변수 없는 ID도 인정한다. 유효19teardown 실패·별도 집계1call 실패와 첫 수정의 Mac19teardown·CI 미사용 import 실패를 모두 보존했다. 6b082a5의 [Actions39001624481](https://github.com/chonamdoo/agents-memory/actions/runs/39001624481)는 Linux 전체2452·별도 설치92·실제 Mac36의 모든 phase와 lint/build/aggregate를 통과했다. 실제 native 보호·운영/평가/출시 승인으로 확대하지 않으며 원래18개는 완료0개다.


### 네 번째 리뷰 후 권한·복구와 PR #9 ingress 보안 수정

- Jev 파일 게시를 현재 operator credential/generation과 같은 PostgreSQL clock 권한 경계로 직렬화했다. private state scalar는 strict하게 검증하고 오류 효과는 명시 상태로 선택한다.
- fenced Jev 선택의 unavailable을 authenticated readiness에도 보존한다. 최초/재개 service install과 fresh host 진단의 durable/native 효과, `CONFIG_UPGRADE_REQUIRED` 전파를 바로잡았다.
- 직접 부모 선종료 뒤에도 native 진단 자손·pipe를 정리한다. 원격 spool recovery는 pending-only·cycle 간 backoff·중단 가능한 준비/DNS·cycle 범위 해석 재사용을 사용하며 기존 단일 flush owner와 unknown-effect reconciliation을 유지한다.
- localhost Host는 ingress mode와 무관하게 실제 loopback peer가 있어야 허용한다. 누락/비 loopback peer의 local operator/bearer 우회를 거절하고 정상 loopback·public OAuth 경계를 회귀로 확인했다. README의 원격 PC `service install`을 host bootstrap 앞으로 옮겼다.
- 현재 설치본의 개인/회사 실제 PG·launchd·fenced readiness·명시 stop/start·capture 보존 smoke를 확인했다. 새 live Jev·구독 모델·native hook 보호·운영 배포의 증거는 아니다. 정확한 전체 gate와 보안 socket 검증 상태는 [검증 기록](docs/verification.ko.md)을 따른다.


### 세 번째 공식 리뷰 — body deadline·전환 효과·진단

- POST body 전체15초 deadline·408/not_started·HTTP/1 연결 종료로 slow/stalled upload의 슬롯 점유를 제한했다. 실제 설치 launchd/PG에서 부분 source0·용량 회수 뒤 capture202를 확인했다.
- Jev 교체 fence 뒤 오류·crash에서 선택 provider를 유지하고 구 worker를 차단한다. 명시 재선택으로 복구하며 durable policy/선택과 unknown credential 폐기·pending intent를 구분한다.
- service start/stop의 저장된 intent 뒤 native 실패를 not_started로 보고하지 않는다. strict receipt JSON/int UID, 과거 Codex strict의 cleanup-only 로딩, pending 설치 재개 경고를 보완했다.
- Claude 환경0의 force-on·settings env unknown·진단 프로세스 provenance를 반영했다. doctor는 effective provider를 사용하고 invalid project를 조기에 거절한다. native 상태의 부작용 필드는 관측 단정이 아닌 요청 범위로 변경했다.
- 이전 공식 wave는3 approve/8 request-changes/1 timeout이었다. 새 집중 실행826 pass/5 fixture fail 뒤 해당5개를 수정·통과했고 설치 byte46·실제 launchd crash/stop/start·PG Jev fence·CLI를 확인했다. 다음 독립 승인·공식 QA/handoff·전체 suite 결과를 대신하지 않는다.
- age Sigsum positive/변조 negative·Go module h1/license와 공개213 checksum, 격리 Linux canary를 추가 검증했다. 전체 P3·native 보호·법적/출시 승인은 아니다.

### Native 공존 진단과 offline build 준비

- DB/config 없이 실행하는 `native-status`와 명시 `doctor --project`, 신규/동일 `host-install`의 metadata-only 공존 경고를 추가했다. Claude/Codex 설정 증거·storage 잔존·unknown을 분리하며 본문/auth·사용자 설정은 변경하지 않는다.
- Codex 정상 `config/read`·`hooks/list`로 layer/hook 수를 조회하는 bounded opt-in 진단을 추가했다. native callback·실제 행동 차단·신뢰 승인을 대신하지 않는다. 새 회귀29개와 실제 Codex inventory CLI를 확인했다.
- source-build backend를 `hatchling==1.32.4`로 고정했다. 공식 standalone Python3.13.16/SQLite3.53.1과 hash 고정 build9/runtime34 wheels로 OS network-deny sdist/wheel build·새 환경 전체 설치·CLI를 실행했고, 누락 wheel은 거절했다. 공개 PG/vector·새 app image·macOS age artifact도 별도 보존하며 offline 설치와 전체 offline 운영/법적 승인은 구분한다.
- 안정 DB를 read-only transaction으로 관측했다: `0004_operation_successors`, failed6/DLQ6·retirement schema 없음. 현재 값이며 해결·migration 성공으로 표시하지 않는다.
- 새 source의 첫 전체 실행은1,954 pass/235 fail/1 error였다. 제품 guard를 유지하고 저장소 내부 QA 임시 경로만 바로잡은 뒤 동일236개 실패 항목을 전부 통과했다. Ruff/build도 통과했으며 새 단일 전체-pass 실행으로 표현하지 않는다.
- Jev deny/agent에서 실제 구독 Opus5.5가 합성 악성 원문/의미 재유입을 discard하고 정상 조건/예외 claim을 최종 MCP context로 재조회했다. 중간 MCP 오류4회와 제한된 oracle·native 소비 미관측을 기록한다. 전체 PMPA·paired 평가·trial·효익의 증명은 아니다.

### 이슈 #5 후속 — strict 설치 안전성과 삭제 재유입

- 이전 checkpoint source의 정확한 `uv run pytest -q`는 **2,161 pass/skip0/518.79초**다. 최초2113pass/48fail의 Homebrew symlink ownership 거절을 보존하고 private regular interpreter·정상 ownership·isolated source와69개 실패 표면을 먼저 검증했다. 제품 guard·Homebrew 권한은 변경하지 않았다.

- Codex 신규 `--strict`는 실제 native 보호 실패 상태에서 성공처럼 등록하지 않고 `HOST_STRICT_UNSUPPORTED/not_started`로 설정 쓰기 전에 거절한다. 자동 advisory downgrade는 없으며 명시 advisory/MCP·기존 owned 정리는 유지한다. Codex native 보호 구현 완료로 표시하지 않는다.
- 삭제 identity/lineage floor와 동일 본문의 새 origin 재판단을 문서화했다. retract/purge 두 회귀와 새 설치 CLI/advisory MCP→HTTP/PG에서 기존 origin 비부활·옛 본문 부재·재판단 전 비노출·새 claim/source만 citation을 확인했다. R05의 누락 비교·잘못된 reference·비독립 근거 오류를 구분했다.
- [설치·업그레이드·장애 복구 runbook](docs/release-runbook.ko.md)을 추가했다. 문서 절차와 실제 안정 cutover·OS login/reboot/sleep·restore 수행 증거를 혼동하지 않는다.
- app+runtime34 wheels를 hash 필수·index/cache 비활성 local 입력으로 설치하고 `pip check`·isolated Python43파일 일치를 확인했다. lock CycloneDX와 실제 target35 distributions의 license-file inventory를 준비했다. Python/PG/tools/age/OS·build backend·다른 ABI·license/배포 승인까지 포함한 offline release 완료는 아니다.
- 이 checkpoint source는 `744b84b1…297f15`다. 앞선2,164 pass는 이전 source 이력이며 해당 controller 실행·남은 공식/native/trial gate는 [검증 기록](docs/verification.ko.md#이슈-5-후속--승인-없는-구현과-설치-소비자-검증)을 따른다.


### 두 번째 공식 리뷰 — Jev 재시도·발급 복구·readiness

- Jev와 key 검증의 실제 HTTP 시도마다 현재 허가를 확인한다. backoff 중 철회·provider/policy revision 변경 뒤 새 전송을 차단하며 이미 admission된 요청의 회수를 주장하지 않는다.
- deny 중단 후 reallow는 agent 전환·폐기를 먼저 완결한다. 새 credential의 발급 전 private intent와 PG clock 직렬화로 lost-response/미확정 commit을 복구한다. 손상 provider는 명시 agent 복구를 요구한다.
- 익명 readiness도 삭제 barrier를 유지하되 Store 소유의 단일 live 검증을 공유한다. 실제 HTTP timeout8건·검증1개·health 유지·해제 후 DB readiness 회복과 새 wheel의 합성 live Jev remember/active claim을 확인했다.
- effective 허가와 configured provider를 구분하고 project add의 후속 grant 실패는 committed로 보고한다. bootstrap principal 용어와 [원래 Shorts 분석의 출처 연결](docs/research/2026-10-16-shorts-lTja2ZxXYyI.ko.md)을 보완했다.
- 같은 source에서 Ruff/build와 **정확한 `uv run pytest -q`:2,164 pass/skip0**를 확인했다. QA interpreter·isolated MCP project 설치 prerequisite를 고친 과정의 실패 이력은 보존했다. 새 noneditable wheel의 실제 구독 Claude/Codex/OMP도 deny/agent·키 없음에서 원문 판단·저장·같은 claim/예외 최종 context를 통과했다.
- 두 번째 공식 리뷰의 request-changes를 controller 실행으로 승인으로 바꾸지 않았다. Codex native trust/callback·실제 보호·수정 후 승인 리뷰·공식 QA/handoff·trial·runtime 게시는 여전히 별도 gate다.
- 재개 검증용 subscriber native 등록·credential·private trace/project와 QA env/cache를 정리하고 owned service/PG를 중지했다. 정상 native 승인 재검증용 최소 private fixture는 남아 있으며 전체 철거·운영 cutover 완료를 주장하지 않는다.

### 공식 리뷰 후 deadline·경합·운영 복구 수정

- HTTP DNS/connect/TLS/send/response 전체 deadline과 종료·회수 가능한 resolver를 적용했다. unknown mutation은 재전송하지 않는다. remote recovery20초 cycle budget과 private spool 단일 flush owner를 추가했다.
- launchd 설치/삭제 durable intent·중단 후 정상 명령 재개·disabled 보존을 구현했다. Jev setup/deny/provider/credential retirement와 실제 publication commit의 cross-process 경합을 막고 미완료 revoke intent를 보존한다.
- bootstrap identity/권한 경계, public operator 거절과 business route의 인증 전 journal sweep 제거, remote CA commit rollback, MixedCase Unix socket 및 Codex context 미출력 lifecycle metadata를 수정했다. 익명 readiness의 검증 누적은 위 두 번째 리뷰에서 별도로 해결했다.
- 이 첫 fix-loop 당시 직접 실행은 Ruff/build 성공·전체2,143 pass/skip0, 실제 HTTP/TLS16경우·launchd crash intent·새 개인/회사 HTTPS package·noneditable wheel·실제 구독 Claude/Codex/OMP MCP 판단/저장/최종 read다. 후속 source의 새 통과로 재사용하지 않으며 [관측과 한계](docs/verification.ko.md#공식-리뷰-후-fix-loop--development20261015-131245)를 구분한다.
- **Codex strict native 보호는 아직 입증되지 않았고 유효 patch의 실제 변경 실패를 기록했다.** 합성 파일은 원복했다. 설치/MCP 성공을 native 첫 행동 차단으로 취급하지 않으며 native 승인이나 workflow guard를 우회하지 않는다. fresh 공식 review/QA/handoff·전체 acceptance·trial·runtime 게시는 미완료다.

### 로컬·클라우드 원격 경로와 독립 판단 정책

- 개인/회사 × 로컬/클라우드 × Jev 허용/불가의 독립 축을 유지한다. 개인·회사 로컬은 별도 `egress-policy.json` default-deny, 명시 allow+확인과 provider 선택·키 검증을 분리했다. deny는 먼저 저장하고 agent 전환·worker credential 폐기, 요청·응답·게시 revision fence를 적용한다. 키·기존 personal 설정만으로 허가를 추론하지 않는다.
- per-user macOS launchd install/start/stop/status/uninstall, 로그인 시작 등록·비정상 종료 재시작·durable manual stop을 추가했다. native 제어와 DB-inclusive `/readyz`가 하나의 전체 기한을 공유하며 살아 있는 DB-unready 서비스를 죽이지 않는다. PostgreSQL/Docker 자체는 관리하지 않는다.
- provider와 독립적인 bounded capture spool recovery가 새 host event 없이 준비 회복 후 전송한다. 기존24시간 TTL·물리 상한·stable key/unknown-effect 계약을 유지하며 owned intermediate0755/leaf0700 설치 layout을 안전하게 처리한다. operator-only body-free 상태, 실패 격리된 worker shutdown·application drain·DB close를 추가했다.
- claude-mem OMP/Claude/Codex의 실제 구현·merged/open 수정과 #5의86개 후보를 [OSS 연구](docs/research/2026-10-15-oss-local-runtime.ko.md)에 정리했다. deadline·실패 격리·production pipe·설치 소비자·비공허 native gate 검증 패턴만 기존 계약에 독립 구현하며 새 memory engine/provider·transcript 수집을 도입하지 않는다.
- 새 정책에서 개인/회사 × 로컬/클라우드 실제 Jev remember·원문 span·재조회를 합성 데이터로 확인했다. 다운로드 원본 키는 프로그램만 읽고0600 서비스 사본을 사용하며 assistant/로그/GitHub에 값을 노출하지 않는다. 구독 Claude/Codex/OMP의 실제 MCP 판단·저장·동일 claim 재조회 및 no-call 관측 범위는 [검증 기록](docs/verification.ko.md)에 구분한다. 현재 작업트리를 PR #9 remote runtime·공식 QA·일반 출시로 표현하지 않는다.
- 메모리 건강 관리 제안을 실제 native Opus5.5/Sol6.1로 독립 리뷰하고 최초 과장을 반증·정정했다. [건강 관리 리뷰](docs/research/2026-10-15-memory-health-adversarial.ko.md)는 provenance/Accept-Reject/coalesce/retention·구형 DB/backup의 영향과 권한을 구분한다. [DB 성장 조사](docs/research/2026-10-15-oss-db-growth.ko.md)는 #5 후보의 실제 merged 수정·코드·기본값·재개/삭제 위험과 별도 PG/SQLite 합성 실험을 기록한다. Reject가 즉시 recall 제외·철회가 아니고 post-backup disposition rollback은 별도 요구임을 현재 문서에 명시했다. health subsystem·자동 망각·추가 전송은 도입하지 않았다.
- strict remote profile·verified HTTPS/public CA·전체 body deadline·현재 PG bearer/OAuth 매핑·one-binding bootstrap·DB 비밀 없는 PC host receipt와 remote client supervisor를 추가했다. 정확한404/not_started session만 안전하게 재초기화하며 unknown write 재전송·원격 authority 자동 기동은 하지 않는다.
- 실제 실패를 수정했다: unsupported SQLite의 WAL 쓰기 전 차단, CLI closed-pipe 성공 exit, Python3.13 symlink-loop와 missing-cwd 분류, custom Claude native 경로의 clean-env 보존, launchd 비동기 bootout 뒤 즉시 start race, SQLAlchemy Unix DSN host decode. 원문/권한 guard를 완화하거나 기억 없음으로 숨기지 않았다.
- Caddy shared-network-namespace의 app crash 후 영구 HTTPS 장애를 재현해 독립 private-network 컨테이너와 exact proxy IP 신뢰로 전환했다. non-root/read-only·backend 미공개·proxy의 app secret/journal/socket 미mount를 유지하고 자동 HTTPS+DB 회복을 확인했다. pgBackRest/restic/Headscale·외부 삭제 witness·실제 cloud 계정 provisioning은 추가하지 않았다.
- cloud 구현·합성 검증은 최신 지시로 trial과 별도 진행한다. 실제1–2주 trial·전체 #5 acceptance·fresh 공식 review/QA/handoff·publication gate와 실제 corpus 승인 경계는 유지한다.


### 이전 PR #8 판단 provider 선택 (agent | Jev)

아래는 당시 개인 전용 구현·검증 이력이다. 현재 허용 정책은 위의 운영 주체 독립 default-deny 계약을 따른다.

- 원문 선택·관계 정리 판단 provider를 `agent`(기본, 지금 쓰는 coding agent)와 `jev`(TypeSafe Jev, 개인 배포 전용) 중에서 고른다. `init --judge`(개인 터미널에서는 대화형 질문)로 설치 때 정하고 `judge set agent|jev`·`judge status`로 언제든 바꾸고 확인한다. MCP는 `memory_inspect(ref="judge")` 조회만 하며 provider를 바꿀 수 없다. relevance는 provider와 무관하게 coding agent가 판단한다.
- provider·키·worker token은 Settings·DB가 아니라 `state_dir/judge`의 0600 파일에 둔다. Settings digest·init intent·host receipt·backup/restore 형식은 바뀌지 않는다. 키는 `--key-file` 또는 화면 표시 없는 입력으로만 받고 합성 질문으로 검증한 뒤 저장하며, 응답에는 HMAC fingerprint만 나온다. 회사 모드는 설정과 worker 실행 모두에서 `JUDGE_PROVIDER_FORBIDDEN`이다.
- serve 안 `JudgeWorker`는 전용 agent credential로 pending source window와 cleanup manifest를 기존 `inspect → record` 검증으로 기록한다. p≥0.8 span만 원문 그대로 claim으로 쓰고, 모두 p≤0.2면 discard한다. 불확실·주입 의심·이전 거절과 같은 내용·검증 실패는 pending으로 남겨 agent에게 넘기며 자동 fallback은 없다. 매 요청·기록 직전에 provider를 다시 읽어 전환 즉시 전송을 멈춘다. `project add`는 Jev worker grant를 함께 추가하고 restore 뒤에는 `judge set jev`를 다시 실행한다.
- README에 로컬(현재)·클라우드(계획) 구조도 PNG와 SVG 원본(`docs/images/`)을 추가했다.
- 검증: 새 회귀 54개와 기존 suite 1726 passed/11 skipped(age·pg_dump binary 미지정 backup 경로), ruff 통과. 사용자 키로 live Jev smoke, native Claude Code·Codex가 Jev가 넘긴 pending을 MCP로 처리하는 것을 확인했다([검증 기록](docs/verification.ko.md)).

### stage-0 동시성·복구 수정

- legacy MCP 세션이 재시작·유휴 만료·세션 수 초과로 사라지면 edge가 `SESSION_NOT_FOUND`/404/`not_started`를 반환하고, 다른 credential의 세션에는 `SESSION_CREDENTIAL_DENIED`/403을 반환한다. stdio relay는 모든 필드가 검증된 `SESSION_NOT_FOUND`/`not_started`에서만 저장한 `initialize`로 다시 연결하고 원 요청을 한 번 다시 보낸다. 재연결이 실패하거나 서버가 다른 protocol version을 협상하면 요청을 보내지 않고 `SESSION_NOT_FOUND`/`not_started`를 반환하며, 다음 요청 전에 다시 연결을 시도한다.
- serve·migrate·backup·restore가 하나의 DB 지원 계약(PostgreSQL 18.x, pgvector ≥0.8.7, 같은 major의 PG 도구)을 쓴다. backup archive는 live 버전을 기록하고 restore는 같은 계약으로 검사한다. 지원하지 않는 도구·live server·archive는 journal reconcile·DDL·restore fence 전에(backup은 staging·recipients 전에도) `DATABASE_VERSION_UNSUPPORTED`/`not_started`로 거절한다.
- 같은 source revision·contract·요청 snapshot에서 겹치는 창은 active complete remember/discard 하나만 이긴다(`SELECTION_ALREADY_RECORDED`). 게시한 claim이 모두 철회된 remember는 창을 놓고, claim 없이 기록한 remember는 계속 잡는다. 응답을 잃은 판단은 같은 admission으로 새 key 재시도 시 원래 operation을 돌려받고, 같은 admission의 다른 판단은 `ADMISSION_CONSUMED`다. 기존 receipt digest·schema·archive 형식은 바뀌지 않는다.
- `max_concurrent_requests`(기본16) 초과는 인증 전 `SERVICE_BUSY`, `pool_acquire_timeout_seconds`(기본5초) 초과는 `DATABASE_BUSY`로 `not_started` 거절한다. legacy `GET /mcp`는 stream이 열릴 때까지 상한에 포함된다. 인증은 전역 `am_clock` 잠금 없이 read-only로 수행하고 변경 트랜잭션이 잠금 아래에서 다시 확인한다.
- `restore-recover`는 migration fence를 먼저 판별한 뒤 명시 runtime을 검증하고, 그다음에 복구가 필요한지 판단한다. 이전 순서에서는 marker가 없으면 `RECOVERY_NOT_REQUIRED`가 잘못된 실행 파일의 `BINARY_REQUIRED`를 가려, 기존 CLI 회귀 12개가 실패했다.
- 업그레이드 주의: 새 설정 두 개가 `Settings` 전체 digest에 들어가므로, 이전 build가 남긴 중단된 migration fence는 이 build에서 `MIGRATION_RECOVERY_CONFLICT`로 거절된다(fail-closed). 중단된 migration은 업그레이드 전에 이전 build로 마친다.

### 공통 coding-agent 판단 전환

- 개인·회사를 `agent_judged` 하나로 전환했다. 사용 중 Claude/Codex가 MCP source_selection·관계·relevance 판단을 제출하고 서버는 exact 원문·revision·권한을 검증한다. Qwen extraction/consolidation/reflection, 서버 embedding/reranking과 obsolete model 설정·명령·의존성을 제거했다. lexical/entity는 후보 색인이고 별도 회사 selection 승인은 없다.
- saved source/retrieval admissions, 네 관계와 explicit no-change cleanup, 주기적 pending 생성, rejection 이유·bounded 관련 후보 비교·선택적 history/review·독립 근거 reopening, query expansion·두 호출 relevance를 추가했다. agent_note는 raw log로 남지만 판단 admission/pending·독립 remember 근거로 쓰지 않는다.
- source secret은 digest/spool 이전에 generic refusal로 거절한다. 기존 unknown-effect spool payload는 body-free quarantine이며 원문을 rewrite하지 않는다. whitespace-only armor false positive를 수정했다. adapter v5는 unjudged optional 후보를 주입하지 않고, optional relevance 안내 때문에 mandatory rule 예산을 줄이지 않는다.
- forward0006은 legacy executable jobs와 operation evidence를 보존해 retired/pending/held로 옮기며 legacy model claims를 awaiting_revalidation으로 남긴다. explicit config upgrade는 원본을 보존한다. 현재 identity sequence만 정확히 허용하는 archive inventory와 strict bounded MCP schema 공유 참조를 적용했다. 구형 archive·삭제 floor·credential 회전 경계를 유지했다.
- MCP stdio가 설치 root 밖 CWD를 거절하던 검사를 제거했다. 리더/linked worktree에서 같은 credential/binding으로 원문을 읽고 다른 binding은 거절하는 실제 MCP→HTTP→PG 회귀를 검증했다. 설치 ownership/receipt와 자동 capture/protected-action 경로 검사는 유지한다. 현행 README·요구사항·architecture·구현 계획의 잘못된 CWD 제한 서술도 수정했다.
- 첫 native review의 request-changes를 반영해 source/request snapshot을 분리하고 거절 history를8개 page·review receipt·현재 전체 비교로 연결했다. 같은 source는 겹친 discard span만 차단하고 reject feedback은 query-only irrelevance와 구분한다. contract revision은 명시 version에 결합하며 source/AST hashing을 제거했다.
- cleanup은 현재 적격 입력과 pending ID에 결합한다. 빈 item은 해결하고 동일 manifest/관계는 재생성하지 않는다. claim_ids 공동 manifest, 전체128 relation ref·요약8개, 관계0 판단의 철회/purge 전파, 현재 복구/historical 실패 구분, binding별 신규 capture 한도를 적용했다.
- 16KiB 상한을 유지하며 큰 claim의 전체 JSON continuation과 digest를 제공한다. 최악 query expansion의 후보 IDs를 보존하고 선택적 preview만 줄이며, 후보0에서는 승인 optional rule을 전달한다. schema title만 줄여 native catalog 예산을 지킨다. secret 역할 타입/순환 import·Claude secret turn state·body-free scheduler 진단도 수정했다.
- 첫 리뷰 수정(R1) 전체 **1470 tests**가 DeprecationWarning=error에서 경고0으로 통과했고 lint/wheel build도 통과했다. 이전 wheel에서 만료 cleanup·관계0 judgment purge 실패를 재현했으며 수정본에서 통과했다. 실제 current-project MCP/native 수동 소비와 합성0004 backup/0006 restore 증거는 검증 기록에 실행 시점별로 구분했다. 안정 서비스 전환은 승인됐지만 worktree guard가 leader-root owned host 작업을 실행 전 차단해 미완료다. 기존 실패 이력·안정 config/DB/host는 변경하지 않았으며 공식 재리뷰·QA/local-handoff는 아직 완료가 아니다.
- R2에서 일부 source 철회 뒤 살아 있는 legacy pending을 보존하고 selection reason/comparison·feedback 별도 source의 삭제/restore 경계를 수정했다. 큰 저장 selection·judgment도16KiB 상한을 늘리지 않고 전체 JSON continuation으로 읽는다. 만료·미래 claim 제외, 실제 agent_note의 capture capacity 분리, empty host context handoff, aged secret spool의 key/digest receipt 유출 방지를 적용했다. direct comparison과 receipt-backed reopening 참조 규칙도 문서에서 구분했다.
- R2 최종 전체 **1533 tests**가 DeprecationWarning=error에서 보고된 경고0으로 통과했다. lint/build/offline install과 새 immutable wheel의 실제 HTTP MCP에서30,645B judgment·17,449B selection의 전체 복원 및 철회 뒤 continuation 비노출을 확인했다. 최대 관측 wire6,353B이며 native 모델 소비·안정 전환 증거와 구분한다. 격리 임시 자원은 정리했고 원래 failed6/DLQ6·안정 운영 상태는 그대로다.
- 중단·복구 테스트의 강제 fork/상속 closure를 fresh spawn worker와 명시적 인자로 교체하고 process handle을 닫도록 했다. 같은 실제 디스크 기록 직후 exit41·재개·unowned config 보존 경계를 유지한다. 경고를 숨기지 않고 DeprecationWarning=error로 host447개와 멀티스레드 부모의 실제 crash/recovery smoke를 검증했다.
- R3는 관련 rejection 후보 최대8개/선택적 live history로 전체 이력 게시 의무를 제거하고 exact evidence 차단·snapshot/feedback ancestry privacy·모든 label metadata 검증·non-null policy를 유지한다. genuine candidate-state legacy reject를 활성 보존하고 notes의 신규 판단 queue 오염을 막는다.
- 반복 relation은 각 판단의 독립 전체 lineage/edge로 보존하고 공개 duplicate/logical read만 정규화한다. non-deriving selection 철회는 floor 없이 uncovered work를 재개하며 restored legacy held를 유지한다. cleanup은 고정 insertion bucket·examined-work 상한·durable progress로 분할한다.
- complete stored feedback까지 neutral continuation을 적용하고 live epoch/source-context를 저장 body에서 분리했다. application이 실제 framing 예산을 소유하며 source/response cap을 늘리지 않는다. nonstrict Codex child secret gap과 뒤 legacy outbox secret scrub도 durable하게 처리한다.
- genuine format-one init과 exact-SHA model approval intent retirement/replay를 추가했다. 원래 private signed/config/token·route audit를 보존하고 모든 구형 route를 disable하며 uncertain approval을 성공으로 가장하거나 Qwen을 재활성화하지 않는다.
- R3 첫 전체는1,654 pass/4 fail이었으며 폐기 note 검증2개 제거·선택 history fixture2개 수정 뒤 관련52개가 통과했다. 사용자 지시로 전체 재검사를1,543 pass에서 중단했고 이후 실패 경로만 확인했다. 전체 green을 주장하지 않는다. lint/sdist/wheel/offline install과 새 설치 CLI/HTTP MCP의 complete feedback6,900B/2창·무관 write 안정성·철회 비노출·typed malformed-kind refusal을 확인했다. 소유 임시 자원은 정리했으며 stable S9/failed6와 fresh official review/QA는 미완료다.
- R4 native 지적3건을 수정했다. note/feedback reason·memory source를 미판단 coverage에서 제외하되 미해결 human/일반 assistant/tool/document partial을 보존한다. local spool 격리는 inspected key+digest+payload CAS와 실제 mutation별 gap/error를 사용해 acknowledged replacement 유실을 막는다. OMP는 IPC object/소비 문자열을 검증하고 malformed reply를 HOST_RESPONSE_INVALID로 거절한다. 새 실패15개만 red→green(3.69s, `-W error`)으로 확인했고 실제 current-source CLI→HTTP MCP→PG에서 note/reason partial=false와 미해결 원문 partial=true를 관측했다. 이는 native 모델·stable S9·전체 QA 완료가 아니다.
- R5는 OMP의 optional preparation/capture 소비 타입 검증, expiry receipt 퇴출 뒤 늦은 remote ACK·확정 거절의 replacement 보호, prepare secret refusal의 restart-visible body-free gap을 수정했다. 새 실패10개만 red→green(1.54s, `-W error`)으로 확인했다. 공유 CorrectCommand는 wire 변경 없이 domain으로 옮겼다. 실제 설치된 rendered TS→CLI child→HTTP capture, 별도 CLI 프로세스의 거부 gap 보존, MCP 판단 완료 뒤 관측 gap의 partial 유지, 실제 producer correction 뒤 old-source 비노출을 관측했다. 이 증거는 native 모델·원래 stable S9·post-merge Agent Flow 설치 완료가 아니다.
- R6는0005 admission의 NULL request_digest를 strict DTO 이전에 ADMISSION_STALE/not_started로 거절하고 audit를 보존한다. 동기 migration thread는 반복 취소에도 실제 종료까지 exclusive lock 안에서 join하며 unknown 결과는 exact operator/request-bound migration fence로 유지한다. restore intent와 구분하고 이미 발행된 target config도 보존 원본에 결합해 재개한다. 새 실패5건만1 passed/1.29s·4 passed/2.16s(`-W error`)로 확인했다. 실제 CLI startup 차단/명시 복구와 HTTP SDK MCP의 구형 admission 거절→새 같은-key 판단 commit을 관측했다. 원래 stable S9/failed6와 공식 승인·게시 완료를 뜻하지 않는다.

### 보존된 누적 구현 이력

아래의 Qwen·회사 lexical 전용 capability·별도 selection 승인·구형 migration 서술은 이전 실행 당시 이력이며 현행 기본 경로가 아니다.


- PR #4 운영 리뷰 수정: 세 backup/restore CLI의 local PG 절대 실행 경로를 필수 입력으로 만들고 Docker container 이름은 유지했다. 첫 durable restore marker→fresh token→executor 순서로 바꿔 marker 이전 실패의 token 누수와 동일 출력 경로 retry 차단을 없앴다. 발행 후 실패는 UNKNOWN/private recovery 경계를 유지한다.
- 프로젝트·배포 패키지·CLI·MCP server 이름을 `agents-memory`, Python namespace를 `agents_memory`, 소비 프로젝트의 숨김 경로를 `.agents-memory`로 통일. 기존 데이터·삭제 저널·backup framing·실행 이력은 보존한다.
- 독립 Python 3.12 서비스와 네 개 MCP tool. 공식 SDK2.3의 modern stateless 및 legacy client가 동일 인증된 core를 사용한다.
- PG18/pgvector authority, full-input evidence graph, lexical/vector/entity retrieval 및 실제 로컬 extraction/embedding/consolidation/rerank/cited reflection.
- Current credential/project grant, semantic idempotency, heartbeat/lease-generation fencing, causal readiness 및 publication/delivery 재검사.
- Trusted producer correction, independent HMAC/fsync deletion journal, original-origin replay floor, descendant hiding 및 local row purge.
- 정확히 세 convention scopes, exact digest/target-set 승인, frozen targets, 회사 공유의 managed Ed25519 approver 경계.
- 기본 optional 총 3개/2,400 UTF-8 bytes, 빈 선택의 context 본문 0, TextContent 단일 plane, required unknown/overflow fail-closed.
- 소유권/hash/drift를 검사하는 Claude/Codex/OMP 설치·해제, standalone CLI/MCP, bounded private capture spool과 native capability-gap 보고. native hook trust를 자동 변경하지 않는다.
- Pinned PostgreSQL dump + age streaming backup/restore, durable plaintext 없음, exclusive restore fence, fresh credentials, routes/rules/job 재승인·fencing 및 최신 surviving deletion floor 복구.
- 실제 실행에서 발견한 native JSON-schema envelope, qualification 누락/번역, unrelated consolidation, reflection bookkeeping prose, snapshot-aware retrieval 통계 결함 수정. 조건·예외를 원문 evidence 구절에 결합하는 regression을 추가했다.
- 적대적 리뷰 수정: 현재 eligibility·snapshot·route에 결합한 reflection receipt, 선택된 conflict/full-input relation lineage·final delivery, orphan job 종료, directional derived withdrawal와 원문 재생성 floor, producer의 protected-artifact 경계.
- 삭제 journal append 이후 오류는 committed floor/recovery-needed로 보고하며 fake rollback을 하지 않는다. installer의 interrupted ownership intent와 poison/backlog spool 복구, private no-clobber/durable write, restore fence·age identity stdin·구형 archive migration을 강화했다.
- 실제 원본 한국어/Vega evidence를 변경하지 않고 extraction/embedding/consolidation/recall/cited reflection을 검증했다. ISO8601 동등한 `Z`/UTC offset을 허용하고 다른 시각·비인용 timestamp는 거절하는 경계를 수정했다.
- 자동 prompt 의미 검색은 별도 `host-install --prompt-recall` opt-in으로 분리했다. 기본 설치는 무요청 memory body를 주입하지 않으며 명시 MCP 조회·capture·required action guard는 그대로 유지한다.
- 2차 적대적 리뷰 수정: correction origin을 floor 이전에 예약하고 committed/partial recovery를 구분. reflection query와 historical receipt는 body-free floor에 연결하며 upstream을 지우지 않는다. exact duplicate group의 withdrawal와 독립 provenance를 분리한다.
- Semantic route와 vector compatibility를 분리하고 embedding-only `index-recover`를 제공. 구형 archive의 migration prefix를 현재 forward target에 복원하며 immutable 기존 migration은 바꾸지 않는다.
- `init --resume`의 exact private intent·원래 owner/token 재검증, completed replay의 mutable 설정 보존. bounded no-follow/FIFO IO 및 subprocess 종료·drain·reap 경계를 강화했다.
- Required FALSE 제외·UNKNOWN 일반 조회의 opaque ref/본문 없음·protected action 거절. native UTF-8 envelope/marker 1,800-byte 상한, 16MiB action path projection, 24시간 TTL 및 물리적 spool 상한.
- Claude private local MCP의 실제 Git-worktree canonical scope를 수정하고 다른 worktree의 relay 실행을 거절한다. 설치·해제는 native trust와 사용자·AF 설정을 보존한다.
- 동일한 원본 30일→14일 정정 source를 바꾸지 않고 generic qualification/기간 grounding 지시를 수정해 실제 추출을 재검증했다. 세 native host가 다음 조회에서 14일·미승인 근거를 실제 소비했다. 과거 failed/DLQ 기록은 삭제하지 않았다.
- 3차 적대적 리뷰 수정: credential 폐기 전 body-free 영향 preview, required 영향의 명시 ack, 같은 immutable proposal/frozen target의 새 revision 재승인. 현재 migration은 `0004_operation_successors`다.
- 실패한 재처리의 원래 outcome과 successor를 분리. 관련 입력만 철회된 live capture는 남은 적격 manifest로 같은 causal owner를 복구하고 old lease/admission을 fence한다. 독립 relation derivation의 lineage는 유지하면서 recall의 동일 logical edge만 접는다.
- 구형 restore의 사전 FK/table 정리를 archive SQL과 같은 명시 transaction으로 이동. pinned `psql` executor는 age EOF/integrity와 SQL producer 성공 뒤에만 COMMIT하며 실패 시 현재 데이터/lineage/reservation을 보존한다. PG18의 별도 CHECK CONSTRAINT도 같은 schema/table allowlist로 검사한다.
- native advisory 훅은 지원 path tool만 선택하고 자체 MCP 호출은 broker에 위임한다. 관련 required rule이 없는 작업에 불필요한 context warning을 넣지 않으며 offered/current required revision 집합을 비교한다. producer HTTP credential은 capture/correct만 허용하고 context/inspect를 거절한다. UNKNOWN metadata는 fitting ref 수가 아니라 전체 미결 수다.
- 4차 리뷰 수정: index 복구도 원래 blocked/failed outcome과 새 successor를 분리한다. live recovery counts와 전체 durable row 상태 집계를 구분하고 중복 stats alias를 제거했다. unrelated roster 성장 후에도 같은 frozen target만 재승인한다.
- Claude 설치/recovery intent를 소유한 MCP key로 제한하고 실제 native mkdir lease에 협조한다. 현재 document와 publication 직전 lease/bytes를 재검사하여 무관한 native 설정을 보존한다. 비협조 writer·same-UID 경쟁에 대한 atomic CAS는 주장하지 않는다.
- 기존 schema의 명시 `migrate --confirm-deployment` operator CLI를 추가했다. current credential·동일 local migrator target·exclusive authority lock을 DDL 이전에 검사하며 살아 있는 서비스/restore fence에서는 거절한다.
- restore marker 발행 전후 실패의 `not_started`/`UNKNOWN` 효과를 구분했다. UNKNOWN 일반 조회의 fitting opaque stub에서 revision/digest를 제거하고 승인 stamp/body를 전달하지 않는다. 동일 원본 Korean Polaris query의 명시 실제 retry가 cited reflection으로 완료됐으며 현재 live pending/blocked/failed/DLQ/stale counts는 0이었다.
- 5차 실제 Codex 리뷰의 source 직접 inspect snapshot 우회를 수정했다. 같은 core의 MCP/API/CLI가 active 원문 반환 전에 누락·불일치를 거절하며 global source와 matching snapshot은 유지한다.
- spool TTL을 receipt뿐 아니라 pending·quarantine 본문에 집행한다. 원래 age를 durable하게 보존하고 overdue/unknown-age legacy row를 전송하지 않으며 body-free gap/expired receipt로 손실을 알린다. 대량 expiry tombstone 때문에 fresh confirmed receipt가 즉시 퇴출되는 문제도 수정했다.
- stdio relay가 검증한 bounded HTTP 오류의 effect를 보존한다. invalid/truncated/mismatched/disconnected 결과는 unknown으로 표시하고 raw 진단·자동 mutation retry를 하지 않는다. 실제 loopback transport와 private SQLite/same-source PG smoke를 별도로 관측했다.
- 6차 실제 native 리뷰: OMP `before_agent_start` 예외 뒤에도 실제 custom provider가 한 번 dispatch된 결함을 재현했다. 새 strict 설치를 쓰기 전에 거절하고 advisory를 유지한다. 역사적 strict receipt는 owned cleanup만 가능하며 실행/replay 권위로 쓰지 않는다.
- 일시적 journal/DB heartbeat 장애는 마지막 확인 lease의 monotonic deadline 안에서만 재갱신한다. 동일 owner의 더 최신 deadline은 admission에서만 허용하고 모든 나머지 lease field·exact heartbeat/publication fence·현재 credential/source/route 검사는 유지한다. 실제 isolated PG에서 마지막 attempt의 두 healthy 작업이 consolidation까지 semantic_ready가 됐고 old heartbeat는 거절됐다.
- authoritative source speaker를 claim span/recall/reflect 입력에 보존한다. 기존 source/spans를 읽을 때 metadata를 join하므로 재추출/DB migration 없이 현행 label을 전달한다. extract 입력에는 이미 speaker가 있었으며 extraction-loss 주장에 따라 불필요한 prompt/route 변경을 하지 않았다.
- 사용자 승인 프로젝트 한정 AF runtime compatibility patch: hosted review가 기존 public `run_distribution(timeout_s=...)`에 `AGENT_FLOW_REVIEW_TIMEOUT_S`를 전달한다. 기본600초·허용1–3600초이며 이 프로젝트의 private continue wrapper는1800초/동시3을 사용한다. global AF·frozen skill·모델/xhigh·12개 angle·verdict gate는 변경하지 않는다. malformed/0 timeout은 실제 CLI에서 review dispatch 전에 거절됐으며 전체 재리뷰 통과와는 구분한다.
- 원천의 nullable `source_event_time`·distinct `source_recorded_at`을 claim evidence/recall/inspect에 보존한다. reflection generation은 typed assertion 또는 cited-source 선택으로 나누고, inspect의 각 문장에 원래 source metadata를 `source_provenance`로 결정적으로 붙인다. 모델의 timestamp/field prose 예외를 제거하여 assertion·limitations의 quote-only grounding을 유지한다. event unknown을 recording/extraction 시각이나 validity·승인으로 대신하지 않는다.
- native required-context budget에 마지막 denial envelope를 예약하고 초과 시 본문 없는 refusal을 반환한다. durable generation/state·rule stamp의 typed bounded schema를 검증하여 malformed state를 reset하거나 rule 전달 성공으로 보고하지 않는다.
- `model approve`의 중복 purpose 등 설정 오류를 artifact 검사·설정 파일 publication 이전에 검증하여 기존 private config를 보존한다.
- operator `project relocate`의 exact locator/revision CAS·semantic idempotency·current grant 검사를 추가했다. 같은 binding·memory·승인 target을 유지하고 roster를 늘리지 않는다. 삭제된 linked worktree의 exact-owned modern native cleanup은 기록된 canonical project key만 제거하고 root/trust/spool을 보존한다.
- 추가 영상·Skills Over MCP의 두 native 상호 반박과 원문 정정을 보존했다. 현행 four-tool/PG ledger·candidate≠approval·bounded opt-in을 유지하고 trace/distiller/code-shadow/Skills 기능은 실제 trial 뒤의 독립 decision gate로 분리한다.
- fix-loop native 복구: 삭제된 normal/linked Claude root의 exact modern deletion-only `removing` intent를 receipt durability/native-key publication 중단 이후 반복 재개한다. validated private receipt bytes를 한 번만 parse한다. 실제 symlink-loop 등 예상 밖 adapter 실패는 strict native body-free denial/exit0 또는 advisory warning이며 durable generation state를 reset하지 않는다.
- fix-loop model approval: hash-only exact recovery intent·cooperative lock·최신 config 보존·확정 보상과 truthful effect를 적용한다. 재인증 principal/credential/generation/role/realm을 결합하고 초기 authority close를 publication 앞에 완료한다. pending retry의 초기 journal barrier도 `unknown`이며 원래 동일 credential 요청만 reconcile한다.
- fix-loop semantic input: cross-encoder에 qualified draft·원문 quote once·speaker/event/recorded clocks만 전달하고 opaque row/extraction-time noise를 제거한다. reflection 모델에는 원문 quote/speaker만 주고 source clocks는 코드에서 전달한다. 실제 input shaping의 `models.py`를 semantic fingerprint에 포함하며 embedding geometry compatibility는 독립 유지한다.
- fresh native 리뷰 수정: reflection inspect가 저장된 limitations를 보존하고 문장/provenance보다 먼저 예산에 예약한다. caveat 누락 시 assertion을 전달하지 않으며 JSON 구분자까지 4,096-byte 상한에 포함한다.
- 확정 보상된 model approval intent는 fsync 종료하여 폐기된 credential에 묶어 두지 않는다. unknown intent는 자동 폐기하지 않고 현재 operator의 `--supersede-pending-intent <exact SHA256>` 새 승인으로만 대체할 수 있다. actual isolated PG의 CLI adoption 직후 crash→restore authority recovery→fresh-credential 승인으로 검증했다.
- 같은 semantic revision의 승인 purpose 축소는 같은 DB transaction에서 빠진 purpose를 비활성화한다. 이전 설정의 소비자와 이전 admission도 즉시 거절하며 남은 purpose는 fresh admission이 필요하다.
- 재리뷰 must-fix: 없는 project 경로의 `host-uninstall`은 `HOST_PROJECT_ABSENT`로 거절하고 `--project-deleted` 확인 뒤에만 native 항목을 정리한다. 이 경우 `native_removed`/`native_uninstalled`와 `project_entries: unverified_absent`를 보고한다. 정리 범위는 durable `native_removing` 상태로 남아 중단 뒤에도 `removed`로 끝나지 않는다. root가 다시 나타나면 stale hook과 재설치는 `HOST_UNINSTALL_INCOMPLETE`이며 일반 uninstall이 project 항목을 제거해 `removed`로 끝낸다. 바뀐·이동한 owned hook, 바뀐 TOML·native key와 비정상 `mcp_servers` 값은 부재가 아니라 `HOST_OWNERSHIP_DRIFT`다. 이전 형식 native-only `removing` intent도 `native_removed`로 끝난다. 재등장 root 정리는 `native_finishing` 중단 뒤에도 현재 파일을 재검사한 경우에만 `removed`이며, install·uninstall은 lock 대기 전에 root를 descriptor로 고정하고 intent 기록·적용·재개와 uninstall 검사를 그 기준으로 하므로 경로가 이동했다 복원돼도 부재를 삭제 완료로 보지 않고 비워진 경로를 다시 만들지 않으며, lock 직후·intent 기록 전·terminal 기록 전 경로가 고정한 디렉터리를 가리키지 않으면(lock 대기 중 소실·교체, `host-install`의 중단된 `pending`/`removing` 재개, native writer lock 대기 포함) recovery intent를 보존한 채 `HOST_CONFIG_DRIFT`이고, owned 항목 변경을 시도했거나 intent를 기록·replay한 뒤의 모든 거절(rollback 실패, native publication 뒤 lease 상실, 재개 뒤 `HOST_UNINSTALL_INCOMPLETE`·마무리 검사 거절 포함)은 effect `unknown`이며, 명령 사이에 같은 경로의 디렉터리를 바꾼 경우는 경로에 묶인 receipt 모델대로 새 디렉터리를 그 project로 검사한다. owned 설정 경로의 디렉터리·socket은 `HOST_CONFIG_INVALID`이고, 따옴표가 든 receipt 경로의 Codex hook은 `args`가 있거나 `--receipt=PATH` 형식이어도 drift로 탐지하며 해석 불가한 남의 hook은 uninstall을 막지 않는다. 모델 입력 projection의 purpose별 필드를 회귀로 고정했다. 비정상 list 상태값도 `HOST_RECEIPT_INVALID`로 거절한다.
- 재리뷰 should-fix: supersede 교체 쓰기 실패는 `MODEL_APPROVAL_RECOVERY_REQUIRED`/unknown을 그대로 보고하고, 교체 뒤 확정 보상은 원래 unknown intent bytes를 복원한다. 모델 입력 projection을 `models.py`의 include-list로 바꿔 fingerprint 밖 `domain.py` 필드가 모델에 새지 않게 했다(현재 payload는 동일). consolidation 지시에 source clock≠validity·supersession 경계를 추가했다. architecture/implementation-plan에 relocation·deleted cleanup·approval intent/supersede·reflection provenance 계약을 기록했다.
- 회사 lexical/entity capability: `init --capability lexical_entity`로 로컬 ML 없는 회사 배포를 만든다. capture coverage와 body-free source pointer, `memory_record`의 strict `source_selection` 판단(remember/discard/review), grounded candidate 게시, lexical·entity RRF recall과 durable nonmodel admission·final delivery fence, binding별 selection policy 승인·epoch, `captured`/`selection_recorded`/`candidate_ready` terminal을 추가했다. reflection·reprocess·vector 복구·model 명령은 `CAPABILITY_UNAVAILABLE`이다. forward migration `0005_company_selection`, revision별 archive allowlist, purge floor 재scrub, init capability fingerprint, host adapter v4 pointer 전달을 연결했다. 개인 full-semantic 동작은 유지한다.
- 업그레이드 안내: host adapter v4 receipt는 배포 capability(`capability`)를 기록한다. 기존 v3 receipt와 이 변경 전에 설치한 v4 receipt는 실행 전에 거절되므로 `host-uninstall` 뒤 `host-install`로 다시 설치한다. prompt recall을 켜지 않은 설치는 capture 상태를 model context에 넣지 않고 hook 결과의 `capture` metadata로만 남긴다. selection 안내는 `lexical_entity` 설치에만 나온다. 삭제 journal의 새 `purge` 기록은 이전 binary가 읽지 못하므로 업그레이드 뒤 이전 버전으로 되돌리지 않는다.
- 회사 리뷰 수정: 생략한 `memory_record.kind`는 기존 note로 처리하며 MCP에는 deployment별 flat object schema를 제공한다. dense 원문 window는 span 수와 비ASCII escape가 포함된 wire 예산에 맞춰 줄이고 continuation을 반환한다. default capture coverage는 이전 digest를 유지하며 모순된 byte coverage는 거절한다. relocate·policy revision 변경 뒤 기존 candidate를 숨기지 않고 drift를 보고한다. candidate 없는 required-context는 selection policy와 분리하고, nonmodel admission은 bounded로 만료 정리한다. purge는 irreversible journal 기록 전에 target-bound key를 선점하며 새 purge floor와 restore 때만 전체 scrub을 수행한다.
- 회사 재리뷰 수정: 확정된 `CAPTURE_COVERAGE_INVALID`는 spool quarantine으로 격리해 후속 capture가 진행된다. unknown effect는 격리하지 않는다. 구형 operation의 두 provenance 필드가 모두 absent/null인 ACK와 exact correction-origin의 `kind=correct` ACK는 scope·provenance 검사를 유지하며 reconcile한다. capability 없는 기존 v4 receipt는 정확한 historical metadata·ownership이 검증된 공식 cleanup에만 허용하고 실행은 계속 거절한다.
- 현재 run 재리뷰 수정: flat `memory_record` schema에 typed variant의 required/allowed 조건을 보존하여 누락·혼합 입력을 사전 검증할 수 있게 했다. 로컬 API credential은 owned/private regular file에서 최대2050 bytes만 nonblocking으로 읽고, FIFO·symlink·oversize·불안전한 권한을 dispatch 전에 `CREDENTIAL_INVALID/not_started`로 거절한다.
- QA fixture 안정화: publication/withdrawal 회귀의 pending/attempt0(초기 또는 재계획) 작업만 명시적으로 due 상태로 준비한다. DB wall clock이 되돌아가도 fixture setup이 즉시 lease를 가정하지 않으며, operation 범위와 attempts0 조건으로 다른 예약 retry를 건드리지 않는다. 제품 scheduler·retry 정책·업무 assertions는 변경하지 않았다.

운영 상태·검증 층위는 검증 기록을 따른다. cloud provisioning과 실제 1–2주 trial 완료는 이 변경의 완료 주장에 포함하지 않는다.
