## 1. 결론

1. **기본안:** 설치형 독립 서비스, 얇은 MCP edge, opt-in host adapter의 세 층으로 구성한다. 회사에서는 로컬에, 개인 환경에서는 self-host VM에 같은 릴리스를 설치한다. host adapter는 Claude Code와 Codex CLI/IDE/desktop의 command hook만 대상으로 한다. engine은 baseline의 **Hindsight 재사용 대신 PostgreSQL 위의 좁은 canonical core**로 바꾼다. core가 소유하는 것은 이벤트, span, 후보·승인, rule registry, 삭제 epoch, hybrid 검색이다. 여기에 **프로필별 승인 추론 executor**를 붙인다. Hindsight는 기본 경로에서 빼고, 재도입 조건부 비교군으로만 둔다.
2. **Same pipeline:** 같게 만들 수 있는 것은 코드, schema, API, 상태 의미, 권한·철회 계약이다. executor, 모델, topology, 인증, 품질, latency, 비용은 같지 않으며 같다고 주장하지 않는다.
3. **반드시 분리할 것:** corpus와 파생물(요약·vector·trace·cache), 로그, 백업, 키, host home·config·session, 추론 route manifest, rule 배포 저장소, 운영자 권한. 회사→개인 sync는 없다.
4. **불가능 조건:**
   - (a) 회사가 무인 추론 route를 승인하지 않으면 회사 쪽 자동 추출과 batch reflect는 `blocked`다. 사용자가 승인된 세션에서 실행하는 host 위임만 가능하다.
   - (b) 단일 OS 계정에서 회사·개인 작업을 섞으면 회사 경계는 best-effort이지 보안 경계가 아니다.
   - (c) SaaS host를 쓰면서 strict no-egress를 주장할 수 없다.
   - (d) hosted web/cloud agent는 회사 로컬 memory에 연결하지 않는다.
   - (e) 모델 준수, 토큰 절감, 한국어 품질은 미측정이다. 아래 내용은 모두 미구현 설계다.

## 2. Findings

### F1 · P0 · 회사 프로필에는 승인된 무인 추론 route가 기본적으로 없다 — baseline engine이 회사에서 성립하지 않음

- **근거**
  - `company-approved-model-boundary.ko.md` §2, §4: 구독 승인은 worker/API 승인이 아니다. [Agent SDK](https://code.claude.com/docs/en/agent-sdk/overview)는 구독 credential의 제3자 제품 사용을 제한한다. [Codex access token](https://learn.chatgpt.com/docs/auth)은 일반 API credential이 아니다.
  - `github-memory.ko.md` §7: Hindsight는 LLM 기본값이 OpenAI이고, 첫 실행 때 HuggingFace에서 모델을 내려받는다.
  - `video-…-portable.ko.md` §7.1: 추출과 entity resolution에 LLM이 필요하다.
  - `video-…-tools.ko.md` §6.3: Jev는 기본이 원격 API이고 ZDR은 enterprise 조건이다.
- **반례:** 외주사 PC에 설치한다. capture는 쌓이지만 추출과 reflect는 계속 pending이고, recall은 마치 '없음'처럼 보인다. 사용자가 동작시키려고 개인 OpenAI 키나 Jev 키를 넣으면 회사 원문과 파생물이 미승인 계정으로 나간다. Hindsight를 기본값 그대로 두면 바로 OpenAI로 호출한다.
- **최소 수정**
  1. 추론을 executor로 분리한다: `api` / `local-model` / `host-delegated` / `approved-headless-cli`.
  2. 서명된 route manifest(endpoint·org/project·모델·목적)에 없는 키는 기동을 거부한다. fallback은 없다.
  3. 회사 기본값은 `host-delegated`다. 사용자가 승인된 세션에서 digest skill을 명시적으로 실행하면, 큐에 쌓인 추출·그룹핑·reflect를 기존 승인 모델 경로로 처리한다. 결과는 typed 후보와 source span으로만 돌려받는다.
  4. 무인 batch는 관리자가 승인한 경우에만 쓴다.
  5. raw span의 lexical 색인은 LLM 없이 즉시 queryable하게 한다.
  6. 모든 recall 응답에 `coverage: extraction=blocked(prerequisite=route)|pending N`을 표시한다.
- **미실행 확인 기준**
  - route가 없는 회사 프로필에서 capture→ingest→lexical recall→정정→철회가 완결되고, 추출은 `blocked`로 보인다.
  - manifest 밖의 키를 넣으면 기동이 실패한다.
  - service/worker의 outbound egress가 0으로 관측된다.
  - host 위임 결과는 후보로만 들어가고, span 불일치 시 reject된다.

### F2 · P1 · Hindsight 내부 권위 객체가 두 번째 canonical 권위가 된다

- **근거**
  - `video-…-portable.ko.md` §5: H1 directive(priority/is_active)가 reflect에 적용된다. mental model full/delta와 cron이 있다. invalidate는 soft-retire다. MCP reflect의 `include_based_on/trace` 기본값은 false다.
  - [retractions.py](https://raw.githubusercontent.com/vectorize-io/hindsight/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-api-slim/hindsight_api/engine/reflect/retractions.py) `unresolvable`: grounding이 전부 사라져도 다음 refresh까지 prose를 유지한다.
  - [H-trace](https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-docs/docs/developer/configuration.mdx#L2553-L2566): DB LLM tracing 기본 true, 최대 50,000자.
  - H8: 기본 무인증, 단일 schema. H9/H10: export는 비원자적이고 import는 fresh ID를 만든다.
- **반례:** source S를 purge하면 우리 ledger에서는 완료된다. 그러나 다음 일이 남는다.
  - mental model 문장이 남고, Hindsight reflect가 그 문장으로 답한다.
  - trace에 S 일부가 하루 동안 남는다.
  - 철회된 규칙이 directive로 저장돼 있었다면 reflect에 계속 적용된다.
  - export 복원 후에는 ID가 달라져 deletion ledger와 매칭되지 않는다.
- **최소 수정:** 승인, rule, 삭제 epoch, scope는 core만 소유한다. engine 내부의 directive, mental model, consolidation은 권위로 쓰지 않는다. Hindsight는 아래 네 조건을 **모두** 통과할 때만 "재빌드 가능한 파생 색인"으로 재도입한다.
  1. recall, reflect tool, refresh의 읽기 경로에 eligibility hook이 있거나 작은 patch로 넣을 수 있다.
  2. LLM 없이 chunk 색인이 가능하다.
  3. trace와 telemetry를 끄고 파생물 purge가 완결된다.
  4. tenant 확장으로 서버 측 ACL을 적용할 수 있다.
- **미실행 확인 기준:** purge 후 recall, reflect, mental model, trace, export, backup restore에서 정한 시간 안에 0건이다. 같은 corpus·모델·예산으로 core와 Hindsight의 검색 품질을 비교한다.

### F3 · P1 · root-free 필수 규칙이 첫 쓰기보다 늦게 도착한다

- **근거**
  - `video-…-primary-checks.ko.md`: Claude는 launch 시 SessionStart의 `mcp_tool`을 skip하고, SessionStart는 command·mcp_tool만 지원한다. Codex SessionStart의 MCP hook은 서버 ready 전에 실행될 수 있고 non-blocking이다.
  - `root-free-claude-conventions.ko.md` §2.3, §4.2–4.3: PreToolUse의 context는 다음 요청에 보인다. 기본은 fail-open이고 `onFailure:block`은 v2.1.295 이상에서만 된다. Bash 쓰기와 `@file`은 matcher를 거치지 않는다.
  - `root-free-codex-conventions.ko.md` §3.1, §3.3: `ask`는 미지원이라 그대로 계속 실행된다. hosted WebSearch는 제외된다. 정의 hash가 바뀌면 재검토 전까지 skip한다.
  - [Claude hooks](https://code.claude.com/docs/en/hooks), [Codex hooks](https://learn.chatgpt.com/docs/hooks)
- **반례**
  - "src/auth에 handler 추가" 요청에서, 첫 Write input은 auth 규칙 없이 이미 생성되고 규칙은 쓰기 뒤에 도착한다.
  - `sed -i`로 쓰면 path 규칙 자체가 걸리지 않는다.
  - adapter를 업데이트해 hook JSON이 바뀌면, Codex는 재검토 전까지 hook을 skip한다. capture와 전달이 조용히 멈춘다.
- **최소 수정**
  1. 시작 시 recall은 서비스와 IPC로 통신하는 command hook으로 한다. timeout은 짧게 두고 실패는 명시한다.
  2. UserPromptSubmit에서 scope 필수 규칙과 언급·계획된 경로의 규칙을 결정적으로 선택한다.
  3. PreToolUse(Edit|Write|apply_patch)에서, 대상 경로의 필수 rule set이 현재 context epoch에 전달되지 않았다면 **deny하고 상한 이내의 규칙 본문을 돌려준다**. 모델은 재계획한다.
  4. Bash와 외부 writer는 CI·lint·sandbox를 backstop으로 두고 '전달 미검증'으로 기록한다.
  5. hook 정의는 고정 command 경로로 유지하고, 로직은 서명된 binary에서 갱신해 hash를 바꾸지 않는다. doctor가 hook 이벤트 heartbeat 부재를 경고한다.
  6. 기존 root 지침은 수정하지 않는다. 충돌이 나면 표시만 한다.
- **미실행 확인 기준:** host·버전별 matrix로 다음을 본다. 첫 쓰기 deny 후 재계획, CI의 Bash 우회 검출, 서비스 down 시의 표시, compaction 후 재전달, 업데이트 후 hook 지속.

### F4 · P0 · 같은 OS 사용자에서 회사·개인 host 설정과 projection이 섞여 직접 반출 경로가 생긴다

- **근거**
  - `company-personal-memory-skill-security.ko.md` §3(3·4·5·7), §6: 본인 local 규칙을 전역 skill 폴더로 퍼뜨리지 않는다.
  - `root-free-codex-conventions.ko.md` §1.1: `$HOME/.agents/skills`는 user-wide다.
  - `root-free-claude-conventions.ko.md` §3.2, §5
  - `distribution-design-proposal.ko.md` "agent-plane과 operator-plane": fake port, 같은 UID의 승인 위조.
  - `mcp-2026-localhost-verification.ko.md`: SIE는 기본 bind가 0.0.0.0이고 allowed_hosts가 비면 보호가 꺼진다.
- **반례:** 같은 macOS 계정에서 회사·개인 작업을 한다.
  - (a) 개인 memory MCP가 user scope로 등록돼 회사 세션에서도 보인다. 모델이 회사 결정을 개인 cloud에 retain한다.
  - (b) 회사에서 나온 local 규칙을 `~/.agents/skills`에 projection하면 개인 세션에 노출된다.
  - (c) 서비스가 꺼진 동안 같은 UID 프로세스가 포트를 선점해 capture를 받는다.
  - (d) 같은 UID로 PG data dir과 토큰 파일을 직접 읽는다.
- **최소 수정**
  1. 회사의 강한 경계 주장은 회사 작업 전용 OS 계정이나 회사 관리 VM을 전제로 한다. 단일 계정이면 doctor가 `best-effort`로 표시한다.
  2. 서비스와 DB는 별도 서비스 계정이 소유한다. 서비스 소유 디렉터리의 UDS를 쓰고, peer credential을 확인하고, 설치별 키를 pinning한다. TCP는 host가 HTTP만 지원할 때만 쓴다. 이때 loopback에 명시적으로 bind하고 Host/Origin을 검증한다.
  3. projection은 프로젝트-local 경로에만 한다. user-global 경로는 금지한다.
  4. 회사 host config에 manifest 밖 MCP endpoint가 있으면 시작을 거부한다. 가능하면 managed allowlist로 막는다.
  5. operator 승인은 agent shell 밖의 step-up으로 받는다.
- **미실행 확인 기준:** 포트 선점, 같은 UID의 토큰·DB 직접 접근, 혼합 config 탐지, user-global projection 차단, 개인 세션에서 회사 rule 0건.

### F5 · P1 · episode·actor·feedback 구분이 없으면 반복 수와 정정이 부풀려진다

- **근거**
  - `video-…-portable.ko.md` §4: transcript는 비동기 지연이 있고, SubagentHandback이 있으며, PermissionDenied는 auto mode에서만 발생한다.
  - 같은 문서 §6.1–6.2: hook 이벤트 수는 반복 조사 수가 아니다. Codex subagent의 `session_id`는 부모 세션 ID다.
  - `…-reanalysis.ko.md`: [21:47](https://www.youtube.com/watch?v=mAKUL12h1n8&t=1307s)의 'do phase six'는 정정이 아니다. [20:30](https://www.youtube.com/watch?v=mAKUL12h1n8&t=1230s)에 장문 필터 버그가 있다. [24:02](https://www.youtube.com/watch?v=mAKUL12h1n8&t=1442s)는 자기 golden run 기준의 수치다.
  - `papers.ko.md` [P20][P21]
- **반례**
  - 조사 1회가 subagent 3개, handback, Stop, resume export로 "5세션 반복"이 된다.
  - 붙여넣은 동료 리뷰 문장이 '인간 정정'으로 분류된다.
  - tool 실행 허가가 사실 승인으로 기록된다.
  - 거절된 후보가 표현만 바뀌어 다시 제안된다.
- **최소 수정**
  1. episode key = (배포, host, root session, root turn) + child lineage로 둔다. 반복 수는 독립 root episode 수 × 서로 다른 principal 수로 센다. 우선순위 신호로만 쓴다.
  2. actor는 hook 필드로만 정한다. 인용·붙여넣기 구간은 `quoted`로 표시한다.
  3. 다음을 서로 다른 이벤트 타입으로 둔다: 실행 허가, capture 동의, 정정, 후보 승인, 규칙 승격.
  4. 거절은 후보 revision 단위로 기록한다. 이유가 없으면 `rejected_unknown_reason`으로 둔다. 승인·거절 이력을 batch의 네 번째 입력으로 넣고, 근사 중복 재제안은 억제한다.
  5. 장문은 중간을 절단하고 offset과 누락을 표시한다.
- **미실행 확인 기준:** subagent·resume·compaction fixture에서 반복 수가 변하지 않는다. quoted 오분류율, 재제안 탐지, 장문 누락을 확인한다.

### F6 · P1 · 철회·복원이 활성 context, resume, 백업에 닿지 않는다

- **근거**
  - `design-contract.ko.md` "철회·삭제·백업"
  - `distribution-design-proposal.ko.md` engine 계약 7
  - `root-free-claude-conventions.ko.md` §4.2: resume이 과거 context를 replay한다.
  - [data-usage](https://code.claude.com/docs/en/data-usage): 로컬 transcript는 plaintext로 30일, `/feedback` 공유는 5년이다.
  - `company-personal-memory-skill-security.ko.md` §6
- **반례**
  - 잘못된 보안 규칙을 긴급 철회해도 열린 세션은 계속 적용한다.
  - `--resume`이 철회된 규칙을 다시 주입한다.
  - 어제 백업으로 복원하면 purge한 source가 부활하고, 오래된 worker가 재추출한다.
- **최소 수정**
  1. `retract`(즉시 read fence, epoch 증가)와 `purge`(원문·파생·색인·cache·export 처리 후 receipt)를 분리한다.
  2. 세션별 delivered set을 기록한다. 철회된 revision이 전달된 세션에는 다음 hook에서 notice를 주입하고, 그 규칙을 근거로 한 쓰기는 deny하며, 새 세션을 권고한다. SessionStart(resume|compact)에서 현재 epoch를 재통지한다.
  3. deletion ledger는 DB 백업과 분리된 append-only로 둔다. 복원 후 ledger head를 적용하기 전에는 서비스를 공개하지 않는다.
  4. worker는 commit 직전에 epoch를 다시 확인한다.
  5. purge receipt에는 범위 밖 사본(host transcript, provider 보관, 사용자 export)을 명시한다.
- **미실행 확인 기준:** 활성·resume 세션으로 철회 전파, 복원 후 부활 0건, 오래된 worker 차단.

### F7 · P1 · 승인·scope 권위를 모델이 위조할 수 있다

- **근거**
  - 요구 9
  - `company-personal-memory-skill-security.ko.md` §6
  - `distribution-design-proposal.ko.md`: approve CLI나 버튼은 인간 존재 증거가 아니다.
  - `pr341-spec-adoption.ko.md` §5: `owner/approval` 메타데이터의 존재는 권한 검증이 아니다.
  - [MCP elicitation](https://modelcontextprotocol.io/specification/2026-07-28/client/elicitation)
- **반례**
  - README의 "테스트 생략이 검증된 성공" 문장이 후보가 된다. agent-plane에 `approve_rule`이 있으면 모델이 local 승인을 해 버리고, 영속 poisoning이 된다.
  - 내용을 수정할 때마다 범위 질문이 떠서 사용자가 실수로 '팀 공통'을 고른다.
- **최소 수정**
  1. agent-plane에는 제안·후보 도구만 둔다.
  2. 세 옵션 선택은 host가 렌더링하는 사용자 응답 채널(elicitation)이나 step-up operator CLI에서만 받는다. local은 추천으로 표시하되 미선택이면 후보 상태를 유지한다.
  3. 저장 위치:
     - local = 해당 배포 DB에 (principal, device, project)로 바인딩
     - 프로젝트 공유 = host가 탐색하지 않는 경로(예: `.agent-memory/rules/`)에 두고 통상 PR 리뷰
     - 팀 공통 = 회사 conventions 저장소에서 리뷰하고, 서비스는 승인된 digest만 활성화
  4. 내용 갱신은 기존 scope를 유지한다. 범위 확대만 재선택과 상위 권한자 승인을 요구한다.
  5. 회사 필수 정책은 local 규칙으로 완화할 수 없다. 충돌하면 중단하고 표시한다.
- **미실행 확인 기준:** agent 단독 승인 불가, 범위 확대 시 재승인, 취소·무응답 시 비활성, 충돌 시 중단.

### F8 · P2 · 한국어·코드 식별자 회상과 토큰 지표가 검증되지 않았다

- **근거**
  - `github-memory.ko.md` §5.1: native tsvector는 BM25가 아니다. §7: 기본 모델이 `bge-small-en`과 ms-marco다.
  - `video-…-tools.ko.md` §7.2: demo tokenizer가 ASCII 전용이라 한국어 query는 빈 결과가 된다. §5.4: Jev의 CJK 성능이 약하다.
  - `mcp-context-design.ko.md` §1, §3
  - `root-free-codex-conventions.ko.md` §3.4: hook 출력 ~2,500 tokens에서 spill한다.
- **반례**
  - 예외 질의가 활용형 '롤백하지'와 식별자 `PaymentRollbackGuard`를 놓치고 `empty`를 반환한다. 사용자는 '규칙 없음'으로 오인한다.
  - 필수 규칙이 cap을 넘어 파일로 spill된다. '전달됨'으로 기록되지만 실제로는 읽히지 않는다.
- **최소 수정**
  1. lexical 색인은 원형 식별자, camel/snake 분해, 한국어 ngram(또는 형태소)으로 이중 색인한다. vector는 반입·라이선스 검토를 거친 다국어 임베딩을 쓴다. 둘을 RRF로 합친다.
  2. 필수 규칙은 검색이 아니라 router(F3)로만 전달한다.
  3. `empty`와 `partial/unavailable`을 구분한다.
  4. 전달 receipt에 `inline` / `pointer-only`를 표시한다.
  5. startup, 첫 회상, 장기 세션의 비용을 분리해 측정하기 전에는 절감을 주장하지 않는다.
- **미실행 확인 기준:** 한국어 부정·임시예외·활용형과 식별자 fixture, spill receipt, 토큰 측정.

## 3. 옵션 비교

**배포·접속 형태**

| 옵션 | 장점 | 단점·반례 | 영향 | 판정 |
|---|---|---|---|---|
| 설치형 서비스 + thin MCP + opt-in adapter | 세션과 lifecycle 분리, 다중 기기·host, durable worker, 두 배포가 동일 release | 설치·migration·update/uninstall·OAuth·doctor 책임. 회사가 상주 서비스를 금지하면 불가. 같은 UID 경계가 약함(F4) | OSS 표면 최대 | **기본안**. 설치 불가 환경은 unsupported로 표시 |
| all-in-one session MCP (stdio child가 DB/worker 소유) | 설정 한 줄 | 세션이 끝나면 worker 중단. 동시 host가 migration·lock 중복. 기기 공유와 hosted 불가 | 내구성 없음 | 기각. stdio-only host용 **기존 서비스에 붙는 shim**으로만 사용 |
| CLI-only | 승인·백업·복구를 agent와 분리 | 비-shell 표면 불가, 자동 recall 없음, shell credential 노출, DB 직접 CLI는 권한 우회 | — | agent-plane 기각. **operator plane**으로 채택(서비스 API만 경유) |
| native skills-only | 서비스 없음, root-free 발견 | capture·ingest·추출·ACL·철회·백업·공유 없음. undertrigger, metadata 누적, user-global 누출 | — | full pipeline 불충족. **승인 rule의 프로젝트-local projection과 진입점 1–2개**로만 채택 |
| Cloud Run/GCS/Tasks/Neo4j | managed scale | GCS·queue·DB 원자성 문제, ID token≠MCP OAuth, Bucket Lock과 purge 충돌, 회사 topology와 이질적, graph는 필수가 아님 | 운영 다원화 | 개인 v1은 단일 VM+PG. Tasks는 wakeup 용도, Neo4j는 측정된 이득이 있을 때만 |

**engine**

| 옵션 | 장점 | 단점 | 판정 |
|---|---|---|---|
| Hindsight 재사용(+fork) | retain, 4-arm RRF recall, reflect, export, MCP 보유. PG family. MIT | F1(API형 LLM 필수), F2(내부 권위, read fence patch, trace), 영어 기본 모델, 기본 무인증, 일일 push되는 대형 engine의 fork 유지 | **조건부**: F2의 네 조건과 회사 route 승인을 통과하면 파생 색인으로 |
| 좁은 신규 PG core | canonical 권위 단일. LLM 없이 lexical queryable. executor 교체 가능. graph·서버 reflect·mental model 없음 | 추출 prompt, 그룹핑, 검색 품질을 직접 소유(요구 16 부담). entity·graph·temporal arm 상실 | **기본안**. 상실분은 경로·유효기간 구조 필터로 대체하고, Hindsight를 비교 baseline으로 측정 |
| SQLite 작은 MCP | 설치 단순 | 개인 cloud와 backend 이원화, 다중 프로세스 lease 약함 | 일반 대안으로 금지는 아님. 동일 backend 요구로 기각 |
| Mem0/Graphiti/Cavira/Honcho/Cognee/Supermemory/Letta/LangMem | 각자 강점 | ADD-only와 history에 원문 잔존, telemetry 기본 on, experimental MCP·UUID scope, purge 미확정, AGPL, 비공개 engine, harness 교체 | 기본 아님. vendor 점수로 순위화하지 않음 |

## 4. Strongest dissent와 최소 결정

**baseline에 대한 반론(채택):**

- 회사의 실제 승인 범위는 "host에서 쓰는 모델"뿐이다. LLM 필수 engine을 회사 경로의 중심에 두면 회사 기본 시나리오가 동작하지 않거나, 미승인 route로 새어 나간다(F1).
- engine 내부의 directive, mental model, trace는 gateway가 가로챌 수 없는 권위와 사본을 만든다(F2).
- '최소 backend 변경'은 recall, reflect tool, refresh, trace, export, tenancy에 걸치며 최소가 아니다.

**선택안에 대한 반론(남는 손실):**

- 검색과 추출을 다시 만든다는 요구 16 부담이 있다. 직접 만드는 범위는 span 색인, RRF, 세 갈래 추출 orchestration으로 제한한다.
- 회사에서는 자동 추출이 사용자 실행이나 관리자 승인에 걸려 "자동 기억" 기대에 못 미친다.
- 1인 사용자에게 PG, migration, OAuth, 백업 운영 부담이 크다.
- hook trust, 관리 정책, 버전 의존으로 지원 host가 2종에 그친다.
- deny-replan 왕복과 주입 누적으로 토큰 비용이 생긴다.

**최소 결정 7개**

1. **권위:** canonical은 PG core 하나다. engine 내부 rule·요약은 권위로 쓰지 않는다.
2. **추론:** 프로필별 서명 manifest와 executor를 둔다. 회사 기본은 host 위임, 무인 실행은 관리자 승인 시에만, fallback은 금지한다.
3. **scope(팀·개인 로컬):**
   - 세 옵션 선택은 사용자 채널에서만 받는다.
   - local은 배포 DB에 principal·기기·프로젝트로 바인딩한다. 회사에서 나온 local 규칙은 회사 배포 안에 둔다.
   - 공유와 팀은 비탐색 경로의 Git 리뷰 digest로 한다.
4. **root-free 필수 규칙:** UserPromptSubmit과 PreToolUse의 첫 쓰기 deny로 결정적 전달을 하고, CI로 backstop한다. semantic 검색은 evidence에만 쓴다. root 파일과 user-global 경로에는 쓰지 않는다.
5. **격리:**
   - 회사: 전용 OS 계정 권장, UDS와 peer credential, manifest 밖 endpoint는 기동 거부.
   - 개인: TLS와 resource-bound OAuth를 쓰는 단일 VM.
6. **Agent Flow·미사용자:** Agent Flow core는 0줄 변경이다. 선택형 adapter가 phase와 예정 경로를 route API에 넘기기만 한다. reviewer에는 memory를 주지 않는다. 미사용자는 Claude Code와 Codex native adapter만으로 완결된다.
7. **삭제:** retract와 purge를 분리한다. deletion ledger는 별도로 두고, 복원 후 ledger를 적용하기 전에는 공개하지 않는다. 철회는 활성 세션까지 전파하고, receipt에 범위 밖 사본을 명시한다.

## 5. 영향 범위

| 영역 | 변경·책임 | 공유 | 반드시 분리 | 상태 |
|---|---|---|---|---|
| memory core | ledger·outbox·ops, span, 후보·승인·rule registry, router, 삭제 epoch, hybrid 검색, executor 인터페이스, MCP edge, operator CLI | 동일 release·schema | DB, 키, manifest | **새 runtime 미구현**. MCP 2025/2026 host 호환 미검증 |
| host adapters | Claude Code와 Codex의 command hook(UserPromptSubmit, PreToolUse, Stop, SubagentStop, SessionStart), stdio shim, doctor | adapter 코드 | host home·config·세션(프로필별) | 미구현. IDE parity, hook trust 갱신, onFailure 버전 미검증. web/cloud는 unsupported |
| Agent Flow | core 0줄. 선택형 adapter만 | route API | reviewer 입력 | 미구현. #341 원 spec은 결함 아님(root 승격은 새 요구와의 채택 부적합) |
| 회사 운영 | 전용 계정·UDS, managed hook 배포가 필요할 수 있음, 모델·artifact 사전 반입(hash, 라이선스), 사내 백업, route 승인 | 운영 playbook 계약 | corpus, 백업, 키, route | **회사 auth·정책 미검증** |
| 개인 cloud | 단일 VM, PG, TLS, OAuth AS, 암호화 백업, 별도 deletion ledger | 동일 release | 개인 corpus·키 | host OAuth 호환 미검증 |
| 승인·컨벤션 | 세 옵션, local step-up, Git digest, 철회 흐름 | 상태 의미 | 회사·개인 rule 저장소 | elicitation 지원·**native 준수 품질·token 지표 미검증** |

**요구 판정** (판정 기호: ○ 가능 / △ 조건부 / × 불가)

| # | 판정 | 핵심 |
|---|---|---|
| 1 | △ | 배포별 기기·agent 공유. 지원 host는 Claude Code와 Codex |
| 2 | △ | 계약은 동일. executor와 품질은 상이(F1) |
| 3 | △ | 전체 loop 설계. 회사 추출은 route 전까지 `blocked`로 명시 |
| 4 | ○ | 독립 repo, Agent Flow는 선택형 |
| 5 | ○ | §3 비교 |
| 6 | △ | manifest·fallback 금지. strict no-egress는 별도 프로필이며 로컬 compute 필요 |
| 7 | △ | 개인 TLS·OAuth. 같은 UID에서는 best-effort(F4) |
| 8 | ○ | evidence / 후보 / rule / skill 분리, 거절 이력, stale은 재검토 trigger로만 |
| 9 | ○ | F7 |
| 10 | △ | 결정적 router. metadata 비용은 0이 아님. 준수는 미보장(F3) |
| 11 | ○ | host matrix. nested AGENTS는 lazy loader가 아님. 등록≠capture |
| 12 | ○ | 지침 PR 범위. selector 개념만 adapter에서 재사용 |
| 13 | ○ | trace≠적응. graph·GCP 기본 아님. [싸이월드 오승격](https://www.youtube.com/watch?v=aimqSS7qoIU&t=3993s)을 fixture로 |
| 14 | ○ | 세 갈래, lineage, 장문, Jev 제한, stale, 네 번째 입력 반영. CueFinder 제외 |
| 15 | ○ | 원 AI 보고서의 앱 설계를 권위로 쓰지 않음 |
| 16 | △ | Hindsight는 조건부. 순위화 없음 |
| 17 | ○ | stateless protocol≠무상태 memory. 지원 매트릭스 측정 전 universal support 주장 금지 |
| 18 | ○ | 패턴만 참고. `mcp<2`, 0.0.0.0, 원격 upstream |
| 19 | △ | 운영 항목 명시. branch fact는 target 재검증 전 승격 금지. 최신≠권위. 수치 미측정 |
| 20 | ○ | 단일 기본안 선택 |