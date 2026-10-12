# 독립 적대적 설계 리뷰 — `agent-memory-mcp` (claude-opus-5-5)

입력 packet만 근거로 했습니다. 외부 도구, 파일, 실행은 쓰지 않았습니다. 아래 내용은 모두 설계 판단입니다. 제품 구현, 보안 통과, 품질, 토큰 실측을 뜻하지 않습니다.

## 1. 결론

- **기본안:** 독립 OSS를 설치형 서비스(+관리 CLI), 얇은 MCP edge, opt-in host adapter로 구성합니다. 권위는 **우리가 소유하는 좁은 PostgreSQL control schema 하나**입니다(event/span·episode·candidate·approval·rule revision·deletion ledger·outbox). v1 회상은 같은 PG의 hybrid 검색입니다(한국어 ngram, 식별자 exact 일치, 사전 반입한 로컬 embedding, RRF).
- **packet 기본안과 다른 점:** Hindsight는 v1 핵심 경로에서 뺍니다. 다음 세 조건을 모두 통과할 때만 **fork하지 않은 파생 projection**으로 붙입니다. ① 승인된 LLM route가 있음 ② 같은 조건의 RAG보다 개선됨(matched ablation) ③ lineage·삭제·복원 acceptance 통과. fork는 기본값이 아닙니다(F3, §4).
- **같은 pipeline:** 가능합니다. release, schema, operation, receipt, eligibility의 의미가 같습니다. 추출 품질, 순위, latency까지 같다고는 약속하지 않습니다.
- **반드시 분리할 것:** corpus, credential, host home/config/session, capture spool, logs, backup, inference route, rule bundle 저장소, 운영자 권한. 회사→개인 sync/export는 기본으로 없습니다.
- **rule plane은 memory 서비스와 분리합니다.** 승인 bundle, 결정론적 resolver, 지원 hook의 first-write barrier로 구성하고 root 파일은 수정하지 않습니다.
- **불가능 조건:**
  - ① 회사에 승인된 추출/reflect route가 없으면 background 자동 추출은 `blocked`로 표시되고, host-delegated 경로만 남습니다.
  - ② 같은 OS UID/home에서 회사·개인을 섞어 쓰면 강한 분리와 위조 불가 승인이 성립하지 않습니다.
  - ③ strict no-egress와 SaaS host 추론은 동시에 성립할 수 없습니다.
  - ④ hook이 없는 surface(web/mobile, Claude cloud session, 일부 IDE)에서는 자동 capture와 필수 규칙 전달을 보장할 수 없습니다.
  - ⑤ 이미 모델 context에 들어간 내용은 회수할 수 없습니다.

## 2. 실질 findings

### F1 [P0] 회사 inference route가 미승인 상태면 기본 engine이 조용히 외부로 나가거나 멈춘다

**근거**
- `company-approved-model-boundary.ko.md` §2·§4
- `github-memory.ko.md` §7 표: Hindsight 기본 LLM은 OpenAI이고, DB LLM trace가 기본 true(1일, 50,000 chars)
- `video-mAKUL12h1n8-portable.ko.md` §7.1: retain/reflect에 LLM 필수
- C2: hook process는 parent env를 상속
- https://hindsight.vectorize.io/developer/installation , https://code.claude.com/docs/en/hooks

**소비자 반례**
- 회사 노트북 셸에 개인 `OPENAI_API_KEY`가 export되어 있고, 기본 config로 worker가 기동됩니다.
- 첫 retain이 회사 transcript를 개인 계정으로 보내고, prompt/output은 PG trace와 backup에 복제됩니다.
- 키가 없으면 retain이 실패해 recall은 영구히 empty인데, 사용자는 `accepted`만 봅니다.

**최소 수정**
- 배포 profile manifest에 기능별(추출·분류·embedding·rerank·reflect) 허용 route를 명시합니다. 미지정이거나 모호하면 **시작을 거부**합니다.
- worker는 정리된 env로 기동하고, 자격증명은 배포 secret store에서만 읽습니다.
- executor 종류는 네 가지로 고정합니다.
  - `approved-api`
  - `approved-local`
  - `approved-headless-host`(예: Enterprise의 승인된 Codex access token 경로)
  - `interactive-host-delegated`: 사용자가 명시 호출한 skill이 이미 승인된 host 세션 안에서 후보를 만들어 `propose_candidate`로 제출
- 아무 route도 없으면 `extraction: blocked(no approved route)`를 status와 recall 응답에 노출합니다. capture, recall, 정정/철회, 규칙은 계속 동작합니다.
- 어떤 engine을 쓰든 trace/telemetry를 끄고, worker 외부 egress는 OS/network 수준에서 차단합니다.

**미실행 확인 기준**
- 개인 키가 env에 있는 기본 설치가 시작을 거부하는가
- strict profile에서 worker 외부 연결이 0건인가(패킷 캡처)
- route 미승인 시 blocked가 표시되는가
- host-delegated 후보가 같은 schema와 검증을 통과하는가

### F2 [P0] 같은 UID/home에서의 route 혼합, 승인 위조, DB 직접 수정, fake endpoint

**근거**
- `distribution-design-proposal.ko.md` "agent-plane과 operator-plane"
- `company-personal-memory-skill-security.ko.md` §3-3·§3-7
- `mcp-2026-localhost-verification.ko.md`: SIE CLI 기본 bind 0.0.0.0, `allowed_hosts`가 비면 DNS rebinding 보호 off
- `root-free-claude-conventions.ko.md` §4.3: command hook은 사용자 전체 OS 권한으로 실행
- https://github.com/superlinked/sie/blob/c571e0a75d804cb6d49795a99cd03ea901307a69/packages/sie_mcp/src/sie_mcp/cli.py

**소비자 반례**
- (a) 개인 cloud capture hook을 user-scope(`~/.claude/settings.json`, `~/.codex/`)에 설치하면, 같은 계정으로 연 회사 repo 세션의 transcript가 개인 VM으로 갑니다.
- (b) agent가 Bash에서 `psql`로 approval 행을 직접 고치거나, 같은 credential로 operator CLI를 호출합니다.
- (c) agent child가 서비스보다 먼저 loopback 포트를 점유해 hook bearer token을 수집합니다.

**최소 수정**
- adapter는 project/local scope에만 설치합니다. 서비스에 **repo identity→deployment 바인딩**을 등록하고, 미등록 repo의 capture는 서버가 거부합니다.
- 한 기기에서 회사와 개인을 함께 쓰는 지원 조건은 **분리된 OS 사용자 또는 분리된 host home**입니다. 두 배포의 credential이 같은 home에서 보이면 `doctor`가 실패합니다.
- DB는 서비스 전용 사용자가 소유한 UDS peer auth로 접근합니다(관리자 권한이 있을 때). 그럴 수 없으면 "same-UID 위변조 방지 없음, 변조 탐지만"이라고 표기합니다.
- edge는 명시적 127.0.0.1 또는 UDS에 bind하고, per-install credential, 서버 identity 확인, Host/Origin 검사를 적용합니다.
- 승인 기능은 MCP tool로 노출하지 않습니다.

**미실행 확인 기준**
- 미등록 repo capture 거부
- 혼용 home에서 doctor 실패
- developer UID로 DB 접속 불가(불가능한 환경이면 표기가 나오는지)
- 선점된 fake server로 credential이 가지 않음
- DNS rebinding 시험

### F3 [P0] 권위 이중화와 파생 철회·복원 누락

**근거**
- `video-mAKUL12h1n8-primary-checks.ko.md`: `RetractedGrounding.unresolvable`이면 모든 grounding이 사라져도 prose를 유지하고, 다음 refresh까지 stale 문장이 남음
- `video-mAKUL12h1n8-portable.ko.md` §5: MCP에 `create_directive`/`invalidate_memory`가 노출되고, reflect `include_based_on`은 기본 false
- 같은 문서 §7.3: export가 원자적 시점이 아니고, import는 fresh ID를 발급
- 두 번째 영상 1:13:56: physical purge 미완료
- https://raw.githubusercontent.com/vectorize-io/hindsight/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-api-slim/hindsight_api/engine/reflect/retractions.py

**소비자 반례**
- 세션 S를 forget하면 fact는 cascade 삭제됩니다. 그런데 mental model "팀은 X를 쓴다"는 근거가 전부 사라져 import 오인 경로로 prose가 유지되고, reflect가 그 문장을 다시 제시합니다.
- 3일간 오프라인이던 노트북의 spool이 재접속하면서 S를 재업로드합니다.
- host 로컬 transcript(`~/.claude/projects/`, 30일 보관)를 재import해 S가 부활합니다.
- restore 이후 오래된 worker가 철회 전 job을 commit합니다.

**최소 수정**
- canonical은 control schema 하나입니다. engine 산출물은 모두 파생물이며, 전달 전에 canonical eligibility(scope, 상태, deletion epoch, **전체 lineage 생존**)를 통과해야 합니다.
- lineage가 불완전한 observation, mental model, 요약은 전달에서 제외합니다. engine의 directive, mental model, 자체 MCP는 비활성화합니다.
- tombstone은 본문 없이 source identity(host·session·message·digest, scope-bound)로 남깁니다. 이 tombstone으로 spool, transcript 재import, 재수집을 ingest 단계에서 거부합니다. spool은 tombstone을 pull합니다.
- worker commit 시 lease fencing token을 확인하고, source row를 lock한 뒤 deletion epoch를 재확인합니다.
- 복원 절차: 같은 PG cluster의 물리 snapshot/PITR → **백업 밖에 둔 deletion ledger**의 이후 항목 재적용 → 그 다음에만 서비스 공개.

**미실행 확인 기준**
- forget 후 recall, reflect, export, cache 어디에도 미노출
- spool·transcript 재import 거부
- 철회 전 job의 늦은 commit 거부
- 복원 후 ledger 재적용 전에는 closed 상태
- (engine 채택 시) 근거가 전부 철회된 파생물이 전달되지 않음

### F4 [P1] root-free 필수 규칙의 첫 사용 전달이 native 경로만으로는 늦거나 없다

**근거**
- `root-free-claude-conventions.ko.md` §2.3: path rule은 Read/Write/Edit 시점에 로드되므로 첫 Write 입력은 이미 생성된 뒤. YAML 파싱 실패 시 무조건 로드
- 같은 문서 §4.2: PreToolUse `additionalContext`는 tool result 옆, 다음 요청에 들어감
- primary-checks: SessionStart는 command/mcp_tool만 지원하고, launch 시 mcp_tool은 skip
- `root-free-codex-conventions.ko.md` §2·§3.3: nested AGENTS는 eager, `ask` 미지원, UserPromptSubmit에 changed-files 없음
- `root-free-conventions-papers-oss.ko.md` §5.1: P4에서 정책 파일을 연 경우 12/347, Native Refuse/Handoff 0
- `pr341-spec-adoption.ko.md` §3: `src/server/**/*.py`가 직접 자식 파일과 일치하지 않는 관측

**소비자 반례**
- 아직 읽은 적 없는 새 파일 `src/payments/refund.py`에 필수 규칙 "audit wrapper 경유"가 걸려 있습니다.
- Claude는 그 첫 Write 시점에야 규칙을 로드하므로, 첫 Write는 규칙 없이 생성됩니다.
- Codex에는 path rule이 아예 없고, implicit skill 선택은 모델 판단입니다.
- 오타 난 frontmatter의 scoped rule은 조용히 전역 상시 로드됩니다.

**최소 수정**
- rule plane을 서비스와 분리합니다. 승인 bundle(ID, rev, scope, applicability, digest, 짧은 본문, 긴 절차는 on-demand 참조)을 로컬에 캐시합니다.
- 결정론적 resolver가 task/phase/예정·변경 path로 규칙을 고릅니다.
- 지원 host의 PreToolUse(Edit/Write/`apply_patch`)에서 **해당 path×rule revision이 이 세션에 아직 전달되지 않았으면 첫 호출을 deny하고, 사유에 규칙 본문을 넣습니다**. 재시도는 허용합니다(deny-once barrier).
- 계획 단계용으로 `/rules-for <paths>` skill 하나를 둡니다.
- glob 의미(`**`가 0단계도 포함)를 테스트로 고정하고, projector가 frontmatter를 검증합니다.
- Bash, IDE, 외부 writer는 이 hook의 대상이 아니므로, 검사 가능한 규칙은 lint/CI로 돌립니다.
- hook을 쓸 수 없는 config에서는 "필수 전달 미지원"을 표시합니다.
- 전달, 소비, 준수, 강제는 별개로 기록합니다.

**미실행 확인 기준**
- Claude와 Codex 각각에서 새 파일 첫 Write가 거부되고, 재시도에 규칙이 반영되는가
- 서비스가 중단된 상태에서도 규칙 전달이 되는가
- malformed rule 거부
- 직접 자식 glob 일치
- 무관한 path에서 주입 0

### F5 [P1] "내용 변경은 scope 유지"가 적용 범위 확대의 우회로가 된다

**근거**
- 요구 9
- `company-personal-memory-skill-security.ko.md` §6 선택 계약
- `distribution-design-proposal.ko.md`: 같은 UID에서의 approve 버튼은 인간 존재 증거가 아님
- `pr341-spec-adoption.ko.md` §5: approval metadata는 권한 검증이 아님

**소비자 반례**
- "내용 수정"으로 `paths: src/payments/**`를 `**/*`로, phase를 review에서 all로 바꿉니다. scope 라벨은 그대로인데 실제로는 전역화됩니다.
- 로컬 규칙을 공유로 승격한 뒤에도 로컬 원본이 계속 활성이라 두 revision이 갈라집니다.
- 개인 배포에는 "팀"이 없어 세 옵션 중 하나가 숨거나 오동작합니다.

**최소 수정**
- scope를 (배포, 소유 도메인, 프로젝트/팀 ID) + **applicability**(selectors, phases, required 여부)로 정의합니다. applicability를 넓히는 변경은 범위 변경으로 보고 재선택과 재승인을 받습니다. 넓어지는지 판정할 수 없으면 모든 selector 변경을 범위 변경으로 봅니다.
- 승인은 정확한 revision digest에 결합합니다.
- 승인 권위:
  - 로컬: host UI를 통한 사용자 확인(동일 UID 위조 불가가 아님을 표기). Git commit은 불필요하지만 회사 경계 안에 둡니다.
  - 프로젝트 공유·팀 공통: 기존 사내 권위(회사 Git PR merge 또는 IdP 인증 admin plane)가 publication입니다.
- 승격 시 로컬 revision은 superseded-by 포인터로 바꿉니다.
- 세 옵션은 항상 표시하되, 권위가 구성되지 않은 옵션은 "사용 불가(사유)"로 보여줍니다. 취소나 미응답이면 candidate만 보존합니다.

**미실행 확인 기준**
- selector 확대 시 재선택 요구
- digest 불일치 본문 활성 거부
- 승격 후 로컬 비활성
- 회사 프로젝트의 로컬 규칙이 개인 배포에 저장되지 않음

### F6 [P1] capture 누락과 episode·feedback 집계 오염

**근거**
- `video-mAKUL12h1n8-portable.ko.md` §4·§6: transcript 비동기, Stop은 interrupt 시 미실행, SubagentHandback, hosted WebSearch 미관찰, subagent `session_id`=parent, PermissionDenied는 auto mode에서만
- reanalysis: 20:30 긴 메시지 필터 bug, 21:47 "do phase six", 50:46 fourth input
- 두 번째 영상 1:14 싸이월드 오승격

**소비자 반례**
- 한 조사가 subagent 3개 + handback + Stop + export로 다섯 번 기록되어 "반복 조사 5회"로 승격됩니다.
- 사용자가 붙여넣은 AI 로그 속 "틀렸다"가 human correction으로 분류됩니다.
- 거절된 후보가 표현만 바뀐 채 매주 재제안됩니다.
- tool 실행 허용이 fact 승인으로 기록됩니다.

**최소 수정**
- 공통 envelope을 둡니다: host·session·root-run·turn·agent·event ID, source digest/offset, 잘림 표시, coverage(complete/partial/unknown).
- recurrence는 서로 다른 root-run을 (세션·날짜·사람) 단위로 센 수입니다. 미확정 건은 반복으로 승격하지 않습니다.
- human origin은 host가 타입화한 user 메시지에만 부여합니다. 붙여넣기/인용으로 감지된 구간은 unknown입니다.
- 거절은 정규화 claim + 근거 집합에 결합하고, 재제안은 **새 근거 ID가 있을 때만** 허용합니다.
- 권한 승인, 취소, 사실 정정, 후보 수락, 규칙 승격은 서로 다른 이벤트 타입입니다.
- 반복 횟수, confidence, Jev 확률은 우선순위 신호이지 권위가 아닙니다.

**미실행 확인 기준**
- subagent fixture에서 반복=1
- 붙여넣기 fixture에서 origin≠human
- 재제안 억제, 단 새 근거가 있으면 허용
- 한국어 부정, 임시 예외, 싸이월드형 오일반화 fixture의 false-promotion 측정

### F7 [P1] context 잔류, resume 재생, 긴급 철회, 토큰 누적

**근거**
- `root-free-claude-conventions.ko.md` §4.2: hook context는 transcript에 저장되고 resume 시 재생, 10,000 chars 초과분은 파일로 spill
- 같은 문서 §6: tool names·server instructions는 startup에 잔류, 2,048 vs 4,096 불일치
- `root-free-codex-conventions.ko.md` §3.4: 메시지당 약 2,500 tokens 한도이며 총합 cap은 아님
- `mcp-context-design.ko.md` §3

**소비자 반례**
- 보안 사유로 rule R rev3을 철회했는데, 어제 세션을 resume하면 rev3 본문이 재생됩니다.
- 이후 tool 호출 없는 설계 답변에서는 hook이 불리지 않아 철회가 전달되지 않습니다.
- UserPromptSubmit마다 같은 묶음을 재주입해 장기 세션 context가 커집니다.

**최소 수정**
- 세션별 delivery receipt(session·rule·rev·digest)를 둡니다.
- SessionStart(startup/resume/compact) command hook은 본문이 아니라 **델타**(철회 목록 + 현재 필수 ID)만 주입합니다.
- UserPromptSubmit은 철회 epoch만 확인하고, 변경이 있을 때만 공지합니다.
- 긴급 철회 시 서비스 측 토큰 폐기와 cache 무효화를 합니다. 회사 고위험 건은 managed hook으로 다음 tool 호출을 차단하고 새 세션을 요구합니다(제품 밖 관리 정책).
- MCP 표면은 고정 5개 이하(recall, get_source, propose_candidate, correct/retract 요청, status)와 짧은 instructions로 제한하고, corpus는 주입하지 않습니다.
- recall은 본문 예산을 두고, 잘린 경우 `get_source(id)` 안내를 붙입니다.

**미실행 확인 기준**
- resume 첫 turn에 철회 공지
- 같은 rev 재주입 0
- host별로 fresh startup, 첫 회상, 장기 세션의 rendered token 실측(현재 미측정)

### F8 [P2] host·SDK·의존성 drift로 capture가 조용히 멈춘다

**근거**
- `root-free-codex-conventions.ko.md` §3.2: non-managed hook은 정의 hash 재검토 전 skip, plugin hook은 desktop 수동 설치 한정
- Claude `onFailure: block`은 v2.1.295 이상
- `mcp-2026-localhost-verification.ko.md`: SDK 2.x와 host 협상 버전은 별개
- `github-memory.ko.md`: Hindsight upstream이 고빈도로 갱신되고 엔진 파일이 17k행대

**소비자 반례**
- adapter 업데이트 후 Codex가 hook을 skip해 capture가 0건인데 오류가 보이지 않습니다.
- host가 구 protocol만 협상해 연결이 실패합니다.
- fork는 매 릴리스마다 rebase 충돌을 냅니다.

**최소 수정**
- 등록 repo×host별 last-capture heartbeat를 두고, status와 SessionStart 공지에 "capture stale since…"를 노출합니다.
- 지원 matrix를 host 버전에 고정하고, adapter의 version/hash를 표시해 재신뢰를 안내합니다.
- migration은 expand/contract 방식입니다. binary rollback과 schema rollback은 다릅니다.
- uninstall은 데이터 보존이 기본입니다.
- fork 대신 projection 경계를 두고 upstream PR을 우선합니다.

**미실행 확인 기준**
- 미신뢰 hook 상태에서 stale 경고
- host×version×protocol matrix 실측
- migration 중단 후 재시작
- uninstall이 owned config만 제거

## 3. 같은 요구 기준의 옵션 비교

**배포/런타임**

| 옵션 | 장점 | 단점·반례 | 영향 | 조건부 채택 |
|---|---|---|---|---|
| **A. 설치형 서비스 + thin MCP + opt-in adapter (선택)** | 세션과 분리된 worker·단일 DB·operation log. 다중 host/기기. 회사 local과 개인 VM이 같은 topology | 설치, migration, OAuth, doctor, adapter 유지 책임. 회사 노트북의 PG/컨테이너 전제조건. same-UID 한계 | 핵심 경로 | 기본. 상주 서비스 금지 조직은 승인 사내 서버로, 그것도 불가하면 미지원 표시 |
| B. 세션 stdio child가 DB/worker 소유 | 설정 하나, listener 없음 | 세션 종료 시 추출 중단. Claude·Codex child의 migration/worker 중복. web/cloud·cross-device 불가 | full loop 불충족 | 기존 서비스에 붙는 stdio shim으로만(=A) |
| C. CLI-only | operator plane 분리 | hosted/sandbox agent 불가, shell 권한·credential 노출, 자동 회상 없음 | 전달 축소 | A의 관리 CLI로만 |
| D. native skills/rules-only (+Git) | 설치 최소. Claude paths·skills로 root-free. 팀 PR 승인 재사용 | capture→추출→reflect→철회 loop 없음. Codex path rule 없음. cross-device memory 없음 | rule plane만 | A의 rule projection 계층. memory가 필요 없는 사용자에게 "rules-only 모드"로 정직하게 표기 |
| E. SQLite 작은 MCP 서비스 | 데몬 DB 없음, 파일 백업, trigram FTS | 사내 다중 사용자·lease에 약함. PG와 병행하면 두 backend | 단일 기기 | 모든 배포를 SQLite로 통일할 때만. v1은 PG |
| F. Cloud Run + Tasks + GCS + Neo4j | 관리형 확장, graph 질의 | DB·GCS·queue 원자성 없음. ID token≠MCP OAuth. purge/restore 별도 책임. 회사 local과 topology 상이. graph 필수 근거 없음 | 운영 면적 최대 | multi-hop 이득과 규모 실측 후 |

**engine**

| 선택 | 장점 | 단점 | 조건부 |
|---|---|---|---|
| **좁은 신규 core (선택):** control schema + PG hybrid + 추출 executor 인터페이스 | 권위 1개. LLM route 없이도 capture·회상·정정·철회·규칙이 동작. lexical은 accept 트랜잭션에서 바로 queryable. fork 없음 | 검색·rerank·한국어·추출 prompt를 직접 유지. temporal/graph/observation 없음. 초기 품질 미지 | 기본 |
| Hindsight, fork 없는 파생 projection | retain·consolidation·temporal recall·reflect 재사용 | LLM 필수(회사 기본 불가). lineage 불완전 산출물 제외 필요. 영어 기본 모델. trace/telemetry 설정. upstream 추적 | 승인 route + matched RAG 대비 개선 + 삭제·복원 acceptance 통과 시 |
| Hindsight fork (packet 기본안) | 내부 commit/read 경계 직접 통제 | 대형·고빈도 upstream 상시 rebase. 두 lifecycle 모델 공존 | projection으로 해결 불가한 결함이 입증될 때만 |
| 새 PG core 전부(graph·reflect agent 포함) | 완전 통제 | 범용 engine 재구현, 유지비 최대 | 비채택 |
| Mem0 / Graphiti / Supermemory / Cavira / Honcho / Cognee / Letta / LangMem | 패턴 참고 | 각각의 문제: v3 ADD-only + 삭제 text가 history에 남음 / UUID 경로가 group 미검사, MCP experimental / 엔진 비공개, forget이 top match soft delete / key 없으면 무인증, hard purge 미확인 / AGPL, single-instance MCP / 다층 저장소 / 하네스 교체 / 직접 구현 | 패턴만 |
| claude-mem / Serena | native capture·progressive retrieval / 읽기 쉬운 Markdown | local SQLite와 hosted PG가 상이, hosted MCP read-only, autostart off 시 조용히 skip, 구독 auth 기본 / name catalog 비용, DB/hook 배제, REPL이 read_only 우회 | 패턴만 |

## 4. strongest dissent와 최소 결정

### packet 기본안(Hindsight+PG, fork 전제)에 대한 가장 강한 반론

1. **회사 기본 조건에서 Hindsight의 가치가 사라집니다.** retain에는 LLM이 필수인데, 새 route는 팀 구독 승인에 포함되지 않는 것이 기본입니다(요구 6). 결과는 첫날부터 blocked이거나, fallback 유혹입니다.
2. **우리가 어차피 소유해야 하는 부분이 대부분입니다.** 3갈래 추출, episode, approval, rule registry, deletion ledger, adapter가 그렇습니다. Hindsight가 덜어주는 범용 산출물(observation, mental model, directive)은 우리 권위 모델과 충돌해 비활성화하거나 필터해야 합니다.
3. **fork 유지비가 큽니다.** 대형·고빈도 upstream입니다.
4. **엔진 우위의 근거가 없습니다.** MemDelta에서는 embedding 교체만으로 6.2%p 차이가 났고, Mem0 실험에서는 full-context가 더 높았으며, vendor 수치는 서로 비교할 수 없습니다.

### 내 선택에 대한 가장 강한 반론과 손실

- 검색 품질을 직접 책임져야 하며, 초기에는 temporal/multi-hop 성능이 Hindsight보다 나쁠 수 있습니다.
- host-delegated 추출은 UX가 무겁고 사용자 세션 토큰을 씁니다.
- deny-once barrier는 한 번의 왕복 비용과 혼란을 더합니다.
- Codex hook 재신뢰 프롬프트로 자동화 UX가 떨어집니다.
- 회사 노트북의 PG 서비스는 여전히 무겁습니다. 현실적인 대안은 "D(rules-only)를 먼저"일 수 있습니다. 그래서 rule plane을 서비스와 분리해, D가 A의 부분집합으로 먼저 출시될 수 있게 했습니다.

### 최소 결정

1. **권위:** canonical은 control schema 하나(PG)입니다. engine은 언제나 파생 projection입니다.
2. **inference route manifest:** executor 4종으로 고정하고, 개인 키·API fallback은 금지합니다. 미승인이면 `blocked`로 표시하고 조용히 축소하지 않습니다.
3. **배포·home 분리:** 회사와 개인은 별도 배포입니다. 한 기기에서 함께 쓰려면 OS 사용자나 host home 분리가 지원 조건입니다. adapter는 project/local scope에 설치하고 repo→deployment 바인딩을 둡니다.
4. **세 범위:**
   - **내 로컬·해당 프로젝트 / 프로젝트 공유 / 팀 공통**을 항상 제시합니다. local 추천은 선택 전 자동 적용이 아닙니다.
   - applicability 확대는 범위 변경입니다.
   - 로컬은 Git·팀 검토 없이 쓰되 회사 경계에 머뭅니다.
   - 공유·팀은 사내 권위(PR merge 또는 IdP)가 승인합니다.
   - 취소하면 candidate만 남습니다.
5. **root-free 필수 규칙:** root 파일 본문·목록·import를 쓰지 않습니다. 승인 bundle + 결정론적 resolver + first-write barrier + `/rules-for`로 전달합니다. semantic top-k는 참고 evidence에만 씁니다. hook을 쓸 수 없는 host는 미지원을 표시하고, 검사 가능한 규칙은 CI로 돌립니다.
6. **Agent Flow 미사용자가 일급 사용자:** adapter는 raw Claude Code/Codex를 대상으로 합니다. Agent Flow는 0줄 변경이며, 선택적 read-only 입력(phase, 예정 path)만 받습니다. 격리 reviewer에는 memory를 전달하지 않습니다.
7. **철회·복원:** source-identity tombstone, 백업 밖 deletion ledger, 복원 전 재적용, fencing.

## 5. 영향 범위

| 영역 | 변경·책임 | 장점 | 비용·위험 | 상태 |
|---|---|---|---|---|
| memory core | control schema, outbox/lease, hybrid 검색, executor I/F, deletion ledger, MCP edge(SDK 2.x, 구 revision 병행 여부는 matrix로 결정) | 단일 권위, LLM 없이 핵심 동작 | 검색 품질 자체 책임 | **새 runtime 미구현** |
| host adapters | Claude/Codex command hooks(SessionStart 델타, UserPromptSubmit epoch, PreToolUse barrier, Stop/SubagentStop/StopFailure → spool), skill 1–2개, 선택적 `.claude/rules` projection | 결정론적 전달 | 버전 drift, Bash 미포괄 | 미구현, **native 준수 품질 미검증** |
| Agent Flow | 0줄 변경. 선택적 read-only 입력 | core freeze 유지 | project-scope hook이 reviewer worktree에서 로드되지 않는지 확인 필요 | 미검증 |
| 회사 운영 | PG/서비스 설치, 사전 모델 반입, route 승인, managed hooks/MCP allowlist, backup·ledger, 컨테이너 license | 데이터가 사내에 남음 | 설치·승인 부담 | **company auth/정책 미검증** |
| 개인 cloud | persistent VM(Compose), TLS, MCP OAuth(audience 검증), 기기별 token, 암호화 backup | 회사 local과 같은 topology | 운영·패치 책임 | 미구현 |
| 사용자 승인·컨벤션 | 3-scope UI, candidate 검토, 사내 Git bundle 저장소 | 권위 명확 | 승인 피로 | **token metrics 미측정**, 비용·절감 수치 없음 |

### 요구별 판정

| # | 판정 |
|---|---|
| 1 | 조건부 충족: 지원 host와 등록 기기에서만. web/mobile/cloud는 수동 사용 또는 미지원 표시 |
| 2 | 설계상 충족: 같은 release·schema. 품질 동일성은 아님 |
| 3 | 조건부: 승인 route가 없으면 자동 추출·reflect는 blocked 표시, host-delegated만 가능 |
| 4 | 충족: 독립 repo, Agent Flow 비의존 |
| 5 | A 선택. B/C/D는 같은 기준에서 full loop 미충족 |
| 6 | 조건부: route manifest, fallback 금지. strict no-egress는 별도 profile이며 승인 compute가 필요 |
| 7 | 부분: same-UID 혼용에서는 강한 분리 불가. 분리 home이 조건 |
| 8 | 설계상 충족: evidence, candidate, 승인 규칙 분리. confidence는 권위가 아님 |
| 9 | 충족 가능(F5 수정 전제) |
| 10 | 조건부: hook 가능한 host에서 barrier. 그 외는 표시, CI 병행 |
| 11 | 반영. readiness·transcript·compaction 한계를 matrix로 관리 |
| 12 | 원 PR의 결함이 아님. 원칙은 재사용하고, root AGENTS 승격과 resolver 의존은 비채택 |
| 13 | 피드백 loop와 역할 분리는 채택. trace 저장만으로는 적응이 아님. Cloud Run/Neo4j는 v1 비채택 |
| 14 | 3갈래, episode, fourth input, stale 아이디어는 후보로 채택. BAML/Jev는 선택 사항. CueFinder 계열은 제외 |
| 15 | 원문은 근거로, AI 보고서는 권위가 아닌 것으로 취급 |
| 16 | 같은 잣대로 비교. vendor 점수 순위화 안 함. 범용 엔진은 중복으로 쌓지 않고 projection으로만 |
| 17 | 수용. synthetic localhost smoke는 protocol/application-state 분리만 입증. host matrix 미검증 |
| 18 | SIE는 edge 패턴만 차용. MCP2 reference 아님. upstream 처리가 로컬이라는 주장 금지 |
| 19 | 운영 부담 항목은 열거. 모든 수치는 미측정 |
| 20 | 단일 기본 경로(A + 좁은 core + 분리된 rule plane)와 acceptance를 명시. 모두 미실행 |