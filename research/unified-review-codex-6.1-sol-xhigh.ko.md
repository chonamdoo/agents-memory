**1. 결론**

- **[INFERENCE] 기본안은 독립 `chonamdoo/agent-memory-mcp` installed service + thin MCP이며, 필요한 통제 변경을 포함한 고정 Hindsight + 외부 PostgreSQL을 재사용한다.**
- 회사 승인 내부 환경과 개인 persistent VM에 같은 release·schema·domain/API·operation 의미를 배포하는 **same pipeline은 가능**하다. 모델 출력·검색 순위·지연의 동일성은 별도다.
- event·provenance·candidate·승인·revision·worker·철회 계약은 공유하고, corpus·credential·host home/session·model route·logs·backup·운영자 권한은 분리한다.
- 회사 기본 환경에서는 승인된 업무 Claude/Codex 모델 처리를 유지한다. 새 worker/API/classifier/embed route와 provider 저장 기능에는 별도 승인 근거가 필요하다.
- 초기 전체 자동화 대상은 **검증할 버전을 고정한 Claude Code와 Codex 로컬 CLI**로 제한한다. 다른 surface의 MCP 접속을 전체 자동화 지원으로 표현하지 않는다.
- 승인된 capture·추론·서비스 운영 경로가 없으면 해당 전체 pipeline은 미지원이다. strict no-egress에 필요한 내부 compute·host가 없으면 그 profile은 불가능하다.
- 설계 방향은 조건부 채택하되 제품 보안·회사 인증·native 품질·token 비용·복구의 통과 판정은 보류한다.
- 이 응답은 packet 기반 단일 리뷰이며, 두 native 모델의 병렬 실행·canonical model·xhigh·byte-identical stdin을 입증하지 않는다.

**2. 실질 findings**

아래 P0–P2는 **미구현 제품의 설계 위험과 출시 차단 조건**이다. 가상 반례를 현재 제품에서 성공한 공격으로 보고하지 않는다. 근거는 제공 packet이며, 연결된 원문을 이번 응답에서 다시 조회하지 않았다.

**F1 — P0: 회사 MCP 접근권한과 이후 모델·저장 목적지의 권한을 연결하는 경계가 아직 구체화되지 않았다.**

**근거:** `company-approved-model-boundary.ko.md` §2–4, `company-personal-memory-skill-security.ko.md` §2–4. MCP token은 memory resource 접근을 허가하며 provider workspace를 증명하지 않는다. Hindsight의 기본 tenant와 단일 API key도 project ACL을 대신하지 않는다. [MCP Authorization](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization), [고정 Hindsight tenant 구현](https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-api-slim/hindsight_api/extensions/builtin/tenant.py#L8-L90).

**소비자-visible 반례:** 회사 인증으로 정상 recall한 뒤, 같은 UID의 개인 host가 그 결과를 개인 모델·계정 skill sync로 보낸다. 또는 adapter가 주소만 신뢰하여 같은 loopback port의 가짜 서버에 transcript를 전달한다. 서버 ACL이 정상이어도 회사 경계는 깨진다.

**최소 수정:** 회사 데이터 접근은 승인된 관리 host·실행 환경으로 제한하고, host의 모델 route와 worker의 목적별 route를 각각 고정한다. 회사·개인 home/config/session과 credential을 분리하되, 악성 같은 UID 프로세스를 위협으로 포함한다면 별도 OS 계정·VM·sandbox 등 실제 격리가 필요하다. endpoint identity를 credential과 결합해 검증하고, agent에는 DB·operator credential을 제공하지 않는다. 개인 키·default bank·미승인 provider fallback은 거절한다. no-training/no-public-disclosure/no-storage-outside-company/no-egress는 각각 표시한다.

**미실행 acceptance:** synthetic 회사 자료로 개인 endpoint·개인 모델 route·가짜 loopback 서버·다른 project·직접 DB 접근을 시도한다. 모두 거절하면서 승인된 업무 host의 정상 흐름은 유지해야 한다. 저장물·summary·vector·skill·logs·backup도 검사한다. MCP 인증만으로 이후 목적지를 통제할 수 없는 BYO client에는 그 보장을 제공하지 않는다.

**F2 — P1: 자동 capture와 최초 recall을 보장할 host별 실행 순서·receipt 계약이 부족하다.**

**근거:** `video-mAKUL12h1n8-portable.ko.md` §4, `primary-checks.ko.md`, `distribution-design-proposal.ko.md`의 capture·durability 계약. Claude launch SessionStart는 MCP tool hook을 skip하고, Codex SessionStart도 readiness 이전에 실행될 수 있다. transcript 지연·interrupt·실패·hosted WebSearch 누락도 남는다. [Claude hooks](https://code.claude.com/docs/en/hooks), [Codex hooks](https://learn.chatgpt.com/docs/hooks).

**소비자-visible 반례:** 최초 세션은 MCP 인증이 끝나기 전에 진행되어 과거 교정을 받지 못한다. 종료 시 transcript의 마지막 메시지가 아직 없는데 capture 완료로 표시한다. 다음 기기에서는 pending extraction의 빈 검색 결과를 “기억 없음”으로 해석한다.

**최소 수정:** 서비스·worker는 session 밖 supervisor가 소유한다. 지원 host에는 인증된 service API를 호출하는 command adapter와 최초 작업 전 recall 경계를 둔다. Claude SessionStart의 `type:http` handler 지원을 가정하지 않는다. spool 저장과 서버 DB commit을 구분하고, `accepted`는 durable commit 이후에만 반환한다. coverage watermark·누락·pending·operation ID를 노출하며 `accepted≠queryable`, `unavailable≠empty`를 유지한다. recall 오류 시 일반 작업은 현재 근거로 계속할 수 있지만, 필수 규칙이 필요한 보호 대상 행동은 별도 차단한다.

**미실행 acceptance:** cold start·인증 지연·서비스 중단·transcript 지연·interrupt·API failure·host 종료·중복 재전송·다른 기기 recall을 관찰한다. 마지막 승인 이벤트가 언제 durable/queryable이 되었는지 확인한다. event 접근이나 사전 전달을 제공하지 않는 host는 manual/export 기능만 별도로 표시하며 전체 지원으로 계산하지 않는다.

**F3 — P0: 세 가지 scope 선택은 명확하지만, 정확한 revision의 활성화 권위와 범위 확대 판정은 더 좁혀야 한다.**

**근거:** `company-personal-memory-skill-security.ko.md` §6, `pr341-spec-adoption.ko.md` §1, `distribution-design-proposal.ko.md`의 operator-plane. Elicitation은 UI 전달 수단이며 인간 신원·publication 권위의 구현이 아니다. [MCP Elicitation](https://modelcontextprotocol.io/specification/2026-07-28/client/elicitation).

**소비자-visible 반례:** 추천된 local 옵션을 응답 전에 적용한다. agent shell이 같은 operator credential로 승인 API를 호출한다. 기존 rule의 scope 문자열은 유지하면서 selector를 특정 경로에서 모든 경로로 바꿔 사실상 범위를 확대한다.

**최소 수정:** 새 활성화·범위 변경에는 정확히 **내 로컬·해당 프로젝트 / 프로젝트 공유 / 팀 공통**을 제시한다. 선택 전에는 candidate만 보존한다. 승인은 본문·조건·예외·대상·selector를 포함한 exact revision/digest에 결합한다. 내용 갱신은 기존 scope를 유지하되, 대상 project/team/device 추가나 적용 조건 확대는 재선택·해당 권한자 승인이 필요하다. 승인 원문은 scope별 한 정본에 두고, 활성·철회 ledger는 그 정본 digest를 참조한다. Git·host projection·Hindsight directive를 독립적인 활성 권위로 만들지 않는다.

로컬-only에는 팀 review·commit·push를 강제하지 않는다. 회사-derived local artifact는 회사 경계에 남는다. 강한 인간 승인 격리를 주장하려면 agent가 접근하지 못하는 operator principal 또는 검증 가능한 human-presence 경계가 필요하다. 권한 있는 일반 정정·철회까지 매번 강한 승인을 요구할 필요는 없다.

**미실행 acceptance:** 미응답·취소·위조 `approved=true`·다른 revision 승인·동시 수정·selector 확대·무권한 팀 승격을 검사한다. local 활성화는 Git 없이 가능해야 하며, project/team 선택만으로 무권한 publication이 발생하면 안 된다.

**F4 — P1: root-free 필수 규칙 공급은 검색 문제가 아니라 첫 행동 이전의 선택·전달 계약이다.**

**근거:** `root-free-claude-conventions.ko.md` §2–4, `root-free-codex-conventions.ko.md` §1–3·§6, `root-free-conventions-papers-oss.ko.md` §5. Claude path rule과 PreToolUse context는 이미 생성된 첫 tool input을 다시 계획하게 한다는 보장이 없다. Codex nested AGENTS는 CWD ancestor loading이다. [Claude context injection](https://code.claude.com/docs/en/hooks#add-context-for-claude), [고정 Codex skill selection](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/skills/src/selection.rs).

**소비자-visible 반례:** “로그인 오류 수정”에서 아직 없는 auth 파일을 처음 작성한다. semantic top-k는 audit 규칙을 놓치고, 최초 Write에서 rule이 로드되어도 생성된 입력은 그대로 실행된다. Bash 쓰기는 Edit matcher도 지나지 않는다.

**최소 수정:** 활성 scope와 승인 상태로 필수 집합을 먼저 정하고, task·phase·예정/변경 path에 승인된 명시 predicate를 적용한다. 입력 미확정은 허가나 규칙 부재로 바꾸지 않는다. 새 path에서 아직 전달하지 않은 필수 규칙이 생기면 지원되는 사전 경계에서 행동을 거절하고 재계획하게 한다. **추가 context와 allow만 반환하는 방식은 사전 전달 보장이 아니다.** 필수 최소 원문이 budget에 들어가지 않으면 작업 분할·범위 축소 또는 보호 대상 행동 차단이 필요하며 offered로 강등하지 않는다.

root 본문·목록·import bridge는 추가하지 않는다. 긴 내용을 unscoped rules나 passive skill로 옮기지 않는다. Claude는 지원되는 scoped rules, Codex는 정확한 skill identity·지원 hook/wrapper로 projection한다. 실행 가능한 보안 제한은 ACL·sandbox·egress·lint/CI에서 집행한다.

**미실행 acceptance:** root 수정 없이 파일 없는 작업·새 파일·rename·직접 자식/중첩 glob·Bash·subagent·compact·scope 변경을 검사한다. 선택·제출·소비·준수·실행 차단을 별도 판정한다. Agent Flow 설치 없이도 같은 검사를 통과해야 한다.

**F5 — P1: 원문 보존만으로 세 갈래 신호와 독립 episode·feedback의 의미가 보존되지는 않는다.**

**근거:** 전체 transcript의 20:05, 20:30–21:19, 26:01–28:18, 34:58–37:27, 50:46–53:09; `video-mAKUL12h1n8-portable.ko.md` §5–6; `papers.ko.md` §5–7. [영상의 세 갈래 설명](https://www.youtube.com/watch?v=mAKUL12h1n8&t=1205s), [LongMemEval](https://arxiv.org/html/2410.10813v2).

**소비자-visible 반례:** 하나의 parent 조사와 child 세 개·handback·종료 export를 반복 조사 다섯 번으로 센다. 긴 한국어 정정의 중간 부정을 제거하여 “이번 branch에서만”을 공통 규칙으로 만든다. 거절한 candidate가 표현만 바뀌어 매번 다시 추천된다.

**최소 수정:** codebase findings / human corrections / recurring investigations를 구분하고, event·message·root-run·parent/child·source span·file snapshot·조건·branch·valid time을 보존한다. 반복 횟수는 독립 episode 기준으로 계산하며 불명확한 lineage를 반복 근거로 승격하지 않는다. 누락·절단은 offset과 coverage로 표시한다. 인간 원문, AI 추출, 실행 결과, 승인 이벤트를 분리한다.

Hindsight의 generic extraction을 먼저 재사용하고 domain-specific schema·집계·feedback을 추가한다. BAML typed output과 Jev 판단은 사실성·승인 권위가 아니다. 승인/거절 revision과 이유를 유지하되, 이유 없는 거절을 “거짓”으로 학습하지 않는다. 코드 변화는 stale 재검토 trigger이며 자동 정정 권위가 아니다.

**미실행 acceptance:** 한국어 부정·간접 정정·임시 예외·exact code identifiers·child 중복·장문 누락·미실행 계획·인용 공격·거절 후보 재표현을 평가한다. 새 모델은 time-split 후속 coding task에서 no-memory와 matched RAG에 비교한다. quote/hash는 무결성 근거이며 의미적 진실·안전성 증명이 아니다.

**F6 — P0: 최소 backend 변경의 범위가 확정되지 않아 내부 publish·reflect·delete·restore의 단일 권위를 아직 보장할 수 없다.**

**근거:** `video-mAKUL12h1n8-primary-checks.ko.md`의 retraction 반례, `portable.ko.md` §6–7, `github-memory.ko.md` §4–6. 지정 helper는 모든 grounding ID가 사라진 경우 import ID 변경과 실제 철회를 구분하지 못해 prose를 유지할 수 있다. [고정 retractions.py](https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-api-slim/hindsight_api/engine/reflect/retractions.py), [고정 export 구현](https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-api-slim/hindsight_api/engine/transfer/export.py).

**소비자-visible 반례:** source를 철회했지만 mental model의 문장은 다음 refresh까지 살아 있다. 외부 recall 결과를 필터해도 내부 reflect가 그 문장을 읽어 답한다. 오래된 worker·import·backup이 revoked revision을 다시 queryable로 만든다.

**최소 수정:** 기존 engine의 writer·reader·consolidation·directive·mental-model·refresh·import 경로별로 통제 지점을 정한다. canonical PG ledger의 source generation·승인 revision·deletion epoch를 **실제 publication transaction과 모든 읽기 경계**에서 확인한다. worker는 lease fencing·CAS·expected version으로 stale commit을 거절한다. 최종 API 출력 검사만으로 내부 합성의 eligibility를 대체하지 않는다.

근거가 모두 사라졌거나 lineage가 불완전한 파생 문서는 즉시 제외·격리한다. import의 명시적 ID remap과 실제 retraction을 구분한다. restore는 복원 snapshot 밖의 신뢰 가능한 최신 deletion head와 화해하기 전 공개하지 않는다. logical ZIP transfer는 point-in-time backup이 아니며, directives·webhooks·route 설정을 무검토 재활성화하지 않는다. retract와 purge 완료 상태도 분리한다.

**미실행 acceptance:** commit 직전 철회·lease 만료·중복/역순 worker·전체 grounding 삭제·내부 reflect·오래된 import·backup restore·source 재수집을 검사한다. 철회 후 시작한 새 요청이 폐기 자료를 반환하거나 채택하지 않아야 한다. purge는 raw·derived·index·cache·spool·export·backup retention까지 별도 완료 증거가 필요하다.

**F7 — P1: 서비스 cache 철회와 이미 전달된 host context의 철회는 다른 계약이다.**

**근거:** `mcp-context-design.ko.md` §1–3, `company-personal-memory-skill-security.ko.md` §6, 두 root-free host 문서의 context lifecycle. [Claude skill lifecycle](https://code.claude.com/docs/en/skills#skill-content-lifecycle), [MCP 2026 changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog).

**소비자-visible 반례:** 서버에서 rule v3를 철회했지만 resume된 transcript·skill 본문·spill file·prompt prefix에는 남는다. service가 v4를 반환해도 agent가 예전 절차를 계속 사용한다. 반복 hook 주입은 deferred schemas의 절감 효과를 상쇄한다.

**최소 수정:** 승인 bundle은 실행별 snapshot으로 고정하고, cache key에는 principal·scope·source/정책/model/parser revision을 포함한다. 권한·철회 변경은 TTL보다 우선한다. delivered ID/revision은 중복 감소에 사용하되 compaction·새 thread에서 재전달 필요성을 판단한다. metadata·본문·wrapper·spill·후속 호출을 포함한 전체 예산을 설정한다.

긴급 철회는 live service 접근과 보호 대상 실행을 중단하고 cache·job·projection을 무효화한다. 필요한 관리 host 세션은 종료하고 새 context로 시작한다. 통제 불가능한 기존 BYO session의 문장을 원격 삭제했다고 주장하지 않는다. 일반 내용 변경의 다음 실행 적용과 긴급 철회를 구분한다.

**미실행 acceptance:** resume·compact·이미 실행 중인 reflect·cache hit·skill refresh·오래된 bundle·spill file 상태에서 철회한다. 서버 재조회 차단과 이전 context의 후속 행동을 따로 평가한다. 실제 rendered/input/cached tokens와 backend 추론 비용을 분리 측정한다.

**F8 — P2: Hindsight 재사용은 운영 비용을 없애지 않으며, 통제 fork의 유지 비용이 재사용 이익을 넘을 수 있다.**

**근거:** `distribution-design-proposal.ko.md`의 lifecycle·미실행 검증 항목, `github-memory.ko.md` §5–8, `papers.ko.md` §7. [Hindsight installation](https://hindsight.vectorize.io/developer/installation), [MemDelta](https://arxiv.org/html/2606.29914v1).

**소비자-visible 반례:** upstream update가 새 내부 read/write 경로를 추가하여 fence를 우회한다. image rollback 후 schema가 맞지 않거나 오래된 deletion 상태가 부활한다. offline 설치가 첫 기동에서 weights를 다운로드한다. uninstall이 다른 host 설정이나 고객 데이터를 제거한다.

**최소 수정:** 하나의 engine·PG·worker authority와 고정 release manifest를 유지한다. fork owner가 통제 지점과 upstream 변경 검토를 책임진다. 설치·migration lock·update/rollback·backup/restore·uninstall ownership을 명시한다. offline artifact·모델·license·dependency를 사전 반입하고, 자동 download/update와 개인 fallback을 금지한다. binary rollback과 schema rollback을 구분한다.

비용은 capture·추출·embedding·reflect·host 주입·인간 심사·재처리·저장·운영을 합산한다. 영상의 2센트는 session당 자기 워크로드 발언이며 제품 단가가 아니다. PG native text search와 English embedding 기본값도 한국어 품질 보장이 아니다.

**미실행 acceptance:** clean install·동시 client·종료 후 worker 완료·migration 실패·update/rollback·reinstall/uninstall·offline cold start·복구를 실제 두 배포에서 수행한다. 상태 oracle의 parity와 한국어/code 후속 행동 품질을 별도로 평가한다. 운영 인력·현금 비용·성능 수치는 현재 미산정이다.

**3. 같은 요구의 옵션 비교**

모든 옵션에 자동 capture→durable ingest→추출/선택→recall→근거 기반 reflect→정정/철회→후속 재사용을 요구한다. 기능을 줄여 비교 비용을 낮추지 않는다.

| 배포·접속 옵션 | 장점 | 같은 전체 계약의 부담·영향 | 조건부 채택 |
|---|---|---|---|
| **Installed service + thin MCP** | 하나의 durable authority, session 밖 worker, 다중 기기·agent 접속, 별도 관리 UI/CLI | 설치·auth·migration·worker·adapter·복구를 제품이 소유한다. MCP 연결만으로 capture가 생기지 않는다 | **기본 선택.** 지원 host의 자동화 경계와 운영 prerequisites를 검증해야 한다 |
| All-in-one session MCP가 DB·worker 소유 | agent 설정에서 시작하기 쉽고 별도 listener를 줄일 수 있다 | 종료 후 작업 완료, 동시 migration/worker, cross-device authority가 어렵다. persistent volume만으로 worker liveness가 생기지 않는다 | 유한 실행·중단/재개 의미가 동일 계약을 만족할 때만 제한 채택. 외부 supervisor/service에 맡기면 실질적으로 기본안이다 |
| CLI-only installed service | 관리·repair 경로가 단순하고 일부 coding host는 hook/shell로 전체 loop를 구성할 수 있다 | hosted client의 일반 연결 수단이 아니며 shell 권한·credential·host별 wrapper가 필요하다. direct DB CLI는 금지 | CLI 실행 가능한 host 집합에 한해 가능. “어디서든” 공통 agent-plane의 기본안으로는 부적합 |
| Native skills-only | 읽기 쉬운 versioned 절차, root-free 본문 loading | 단독으로 durable capture·worker·공유 ACL·derived purge·restore를 제공하지 않는다. 외부 runtime을 추가하면 skills-only가 아니다 | 승인된 rule/skill의 projection으로 채택. 전체 memory 제품의 대체로는 채택하지 않는다 |

| Engine·인프라 선택 | 장점 | 동일 계약의 비용·손실 | 판단 |
|---|---|---|---|
| **통제 변경을 포함한 Hindsight + PG** | 이미 있는 extraction·hybrid recall·reflect·mental model·operation 기능 재사용 | 내부 commit/read/refresh/restore까지 수정 범위를 소유해야 한다. wrapper-only는 부족하다 | 기본 후보. F6의 통제 지점과 fork 유지 범위를 확인해야 한다 |
| 좁은 신규 PG core + 필요한 extraction primitive 재사용 | evidence·episode·승인·철회 상태를 직접 설계하고 불필요한 기능을 제외할 수 있다 | durability·검색·reflect·auth·worker·복구·품질 책임이 남는다 | Hindsight 변경이 넓게 퍼져 유지 불가능할 때 **교체 대안**. 기존 engine 옆에 중복 generic engine을 추가하지 않는다 |
| PG memory core 전부 신규 제작 | 내부 동작·권위에 최대 통제력 | 검증해야 할 구현 면적과 검색/합성 품질 개발 비용이 가장 크다 | 처음부터 선택할 근거 부족 |
| SQLite 기반 작은 installed service/MCP | 단일 persistent-disk 배포와 backup 운영을 단순화할 수 있다 | 전체 승인·worker·lineage·삭제·restore·auth는 여전히 필요하다. replica/HA와 migration 제약을 소유한다 | SQLite 일반 대안은 유효하다. “작은 MCP”라는 이유로 기능 동등성을 가정하지 않는다 |
| Cloud Run·GCS·Tasks·Vertex·Neo4j | 분리 worker·managed infrastructure·관계 질의를 활용할 수 있다 | DB/object/queue 원자성, 재시도·HA·삭제·비용·회사 승인 경로가 각각 필요하다 | 관계 질의·규모의 이득이 입증될 때 검토. 초기 기본안에는 추가하지 않는다 |

OSS 후보는 packet의 고정 snapshot을 기준으로 비교한다. **아래 어느 후보도 이번 입력만으로 회사 인증·한국어 품질·삭제/복구의 production 통과가 입증되지는 않는다.**

| 후보 | 출처·권한·승인·삭제 계약에서의 판단 | Host·품질·운영 영향과 조건부 채택 |
|---|---|---|
| **Hindsight** | source carriers와 파생 lineage 기능이 유용하다. 기본 tenant/API key, directive, 내부 retraction·transfer에 보강 필요 | 동일 PG engine 양쪽 운영의 기본 후보. 일반 검색·추출을 재구현하지 않고 통제 변경에 집중 |
| **Mem0 OSS** | packet의 current v3는 ADD-only extraction이며 explicit CRUD는 남는다. history의 삭제 전 text도 purge 대상 | generic fact memory에 유효. MCP·reflect·승인 계약을 추가해야 하고 Platform 성능을 OSS에 이전할 수 없다 |
| **Graphiti** | episode·bitemporal fact에 장점. group/UUID 접근권한과 파생 삭제 계약 확인 필요 | experimental MCP와 graph 운영 부담. 필요한 temporal/multi-hop 이득이 있을 때 채택 |
| **LangMem** | extraction/reflection primitive 재사용 가능. provenance·approval·authorization·retention은 애플리케이션 책임 | 좁은 core의 라이브러리 후보. durable store·독립 MCP·운영 제품을 별도로 구성해야 한다 |
| **Honcho** | message/source와 비동기 representation이 유용하다. 원본 삭제 후 파생 conclusion·이식 계약은 미확정 | peer reasoning 중심이면 재평가. AGPL 의무·PG/Redis·single-instance MCP 운영 검토 필요 |
| **Cognee** | corpus/source 기반 pipeline과 export 기능. 승인·전체 purge·service restore는 별도 계약 | 광범위 company corpus에 유력하나 초기 storage/processing 운영 면적이 크다 |
| **Cavira LongMemory** | governed provenance·server-bound identity가 유용하다. hard purge·전체 restore 계약 추가 확인 필요 | SQLite 동일 배포의 현실적인 대안. 복수 replica/HA를 문서 예제로 보장하지 않는다 |
| **Letta Code** | MemFS·git memory·self-edit는 별도 harness 안의 계약 | agent continuity에는 유효하나 Claude/Codex를 유지하는 독립 memory-only 기본안으로는 부적합 |
| **Supermemory** | 현재 MCP·spaces·soft forget와 비공개 engine을 구분해야 한다 | 개인 managed UX 후보. 동일 공개 OSS engine을 회사/개인에 운영하는 요구의 대체는 아니다 |
| **claude-mem** | native capture·observer·단계적 검색을 참고할 수 있다. local/hosted 계약·승인·derived purge 보강 필요 | local SQLite/Chroma와 hosted PG/BullMQ의 parity를 가정하지 않는다. 회사 구독 credential 재사용은 별도 권한 문제 |
| **Serena** | versioned Markdown·명시 reference가 유용하다. read-only/ignored 설정은 완전한 ACL이 아니다 | memory 이름 목록 비용이 남고 full 자동 pipeline을 의도적으로 제공하지 않는다. projection·reference 패턴으로 참고 |

처음 두 영상과 GCP/Neo4j·trace-as-memory·read/write-cycle·LangSmith Engine 이미지의 방향은 역할 분리와 feedback loop의 참고 근거다. **trace 저장, 추출된 요약, reflect, 다음 행동의 변화, 총비용은 각각 평가해야 한다.** packet에 기록된 purge 미완료·migration·기기 설정 문제를 완성품 보증으로 바꾸지 않는다. 첫 한국어 영상의 직접 transcript 부재도 유지한다.

MCP 2026-07-28과 SDK 2.x는 배포·context·보안 계약을 대체하지 않는다. `server/discover`는 새 필수 client handshake가 아니고, request-scoped SSE는 남으며, `Mcp-Name`은 named methods에 한정된다. deprecation은 즉시 제거가 아니다. 지원 wire version은 실제 대상 host 검증으로 정한다. [MCP changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog).

SIE는 thin edge→configured cluster 패턴만 참고한다. pinned `mcp>=1.9,<2`의 `stateless_http=True`를 MCP2 지원으로 부르지 않는다. 로컬 edge와 upstream processing 위치를 구분하며, 기본 `0.0.0.0`·빈 `allowed_hosts`도 그대로 채택하지 않는다. [고정 SIE README](https://github.com/superlinked/sie/blob/c571e0a75d804cb6d49795a99cd03ea901307a69/packages/sie_mcp/README.md), [고정 pyproject](https://github.com/superlinked/sie/blob/c571e0a75d804cb6d49795a99cd03ea901307a69/packages/sie_mcp/pyproject.toml).

**4. Strongest dissent와 최소 결정 5개**

**가장 강한 반론:** 이 기본안은 이미 작은 wrapper 제품의 범위를 넘는다. 사용자가 원하는 비용 절감과 기억 재사용의 핵심에는 host capture·독립 episode·승인 UX·첫 행동 전 전달·현재 코드 재검증이 있다. Hindsight를 재사용해도 이 책임은 남는다. 동시에 내부 검색·합성·background refresh·import에 publication/retraction fence를 넣어야 하므로, upstream 기능을 많이 가져오는 것이 오히려 검증·유지 비용을 늘릴 수 있다.

따라서 Hindsight 선택의 근거는 benchmark 점수가 아니라 **이미 구현된 일반 memory 연산을 필요한 권위 계약 안에서 재사용할 수 있느냐**다. 핵심 통제 변경이 여러 내부 경로에 계속 퍼지고 이를 책임질 maintainer가 없다면 좁은 PG core로 교체하는 편이 현실적일 수 있다. 그때도 잃는 extraction·recall·reflect·운영 기능을 직접 보충해야 한다. 현재 packet에는 그 교체가 더 싸거나 더 좋은 품질이라는 실측이 없으므로 기본 선택을 뒤집지는 않는다.

최소 결정은 다음 다섯 가지다.

1. **제품·지원 범위를 고정한다.** 독립 repo, 하나의 고정 Hindsight 변경판, 외부 PG, session 밖 service/worker, 회사 승인 내부 배포와 개인 persistent VM을 기본으로 한다. 초기 자동화는 검증할 Claude Code/Codex CLI 조합으로 제한한다. 전체 지원이 불가능한 host·설치 환경은 명시한다.
2. **trust domain과 목적별 route를 고정한다.** 회사·고객·개인은 storage·credential·home/session·logs·backup을 분리한다. 승인 coding host를 유지하되 새 worker 경로는 자동 승인하지 않는다. strict profile은 승인된 내부 compute와 host가 있을 때만 제공한다.
3. **권위와 승인 UX를 고정한다.** evidence·candidate·approved rule·executable skill을 분리한다. 새 활성화/범위 변경은 정확한 세 옵션과 exact revision 승인으로 처리한다. local-only에는 Git·팀 review를 강제하지 않는다. 공유 원문 정본, activation ledger, host projection의 역할을 각각 하나로 정한다.
4. **root-free 사전 전달을 고정한다.** root 본문·목록·bridge 없이 필수 승인 규칙을 결정론적으로 선택한다. 최소 원문을 첫 보호 대상 행동 전에 전달하고 긴 근거·절차는 on-demand로 읽는다. Agent Flow 비사용자도 같은 standalone adapter 계약을 사용한다.
5. **출시 증거와 유지 owner를 고정한다.** 내부 commit/read 경계, 최신 deletion ledger, restore, schema rollback, host compatibility의 owner를 지정한다. F1–F8 acceptance와 동일 조건의 후속 행동·총비용 평가를 실시하기 전에는 회사 인증·즉시 forget·native 품질·token 절감을 검증됐다고 표시하지 않는다.

**5. 영향 범위와 요구별 판정**

| 영역 | 필요한 변화·책임 | 영향과 현재 검증 상태 |
|---|---|---|
| **Memory core** | durable event/operation, episode identity, 승인·activation/deletion ledger, 내부 commit/read fence, derived retraction·restore | 새 runtime·backend 변경은 미구현. fork 범위와 유지 비용 미확정 |
| **Host adapters** | opt-in capture, coverage/receipt, 최초 recall, 작업별 rule 선택, snapshot projection, 긴급 revoke | host별 구현 필요. 문서·released source는 실제 설치·준수 검증이 아니다 |
| **Agent Flow** | 선택적 adapter에서 route 이유·phase·예정/변경 path의 작은 계약 참고 | core/installer/reviewer에 engine 강제 없음. whole resolver·runner·gates 의존 없음. rollback된 #341을 현재 기능으로 취급하지 않음 |
| **회사 운영** | 승인 내부 storage, 관리 host, 목적별 모델 route, operator 격리, offline bundle·backup owner | 회사 auth·계약·설정 미검증. 팀 구독은 새 worker·저장 경로 승인 근거가 아니다 |
| **개인 cloud** | persistent service/PG/worker, TLS/OAuth/ACL, credential rotation, retention·backup·restore | self-host 운영 책임 발생. 회사 corpus 유입 금지. 실제 연결·보안·비용 미검증 |
| **사용자 승인·컨벤션** | 정확한 세 scope, revision 승인·거절, local-only 경로, versioned rule/skill·stale feedback | root 수정 없이 구현해야 한다. 전달·소비·준수·강제는 별도이며 native 품질·token metrics 미검증 |

다음 판정은 **설계 충족 가능성·채택 적합성**이며 구현 통과 판정이 아니다.

| 요구 | 개별 판정 |
|---|---|
| **1. 독립 cross-device/cross-agent OSS** | 조건부 충족. standalone service를 같은 project identity로 사용한다. 초기 지원 host 밖의 자동화는 별도 capability로 표시한다 |
| **2. 회사 local·개인 cloud same pipeline** | 가능. 같은 fixed backend/release/domain을 사용하며 데이터 경계·운영·모델 품질은 분리한다 |
| **3. 전체 loop** | 필수 유지. capture·자동 추출/선택·근거 기반 reflect·후속 사용을 manual/tool-only나 reflect-off로 축소하지 않는다. prerequisite 부재는 미지원으로 표시한다 |
| **4. 독립 repo·Agent Flow 비의존** | 채택. 다른 프로젝트에서도 등록·인증·adapter가 동작해야 한다. repo 생성·게시를 수행한 것은 아니다 |
| **5. MCP와 설치형 비교** | installed service+thin MCP 선택. stdio child의 transport와 DB/worker ownership을 구분한다 |
| **6. 회사 계정·egress** | 승인 업무 모델 처리 전제를 유지한다. 새 worker·API·저장 승인과 분리하며 개인 fallback 금지. strict no-egress는 별도 조건부 profile이다 |
| **7. 개인 보안·같은 UID·fake endpoint** | 보강 필요. localhost는 인증 경계가 아니며 endpoint identity·operator/DB 격리·관리 host 통제가 필요하다 |
| **8. versioned rule/skill·feedback** | 조건부 충족. AI evidence/candidate와 승인 규칙·실행 절차를 분리하고 거절·stale·새 모델 평가를 유지한다 |
| **9. 정확한 세 scope** | 그대로 채택. 선택 전 자동 적용 없음, 미응답/취소는 candidate만 보존. 내용 갱신은 scope 유지, 확대는 재선택·권한자 승인이다 |
| **10. root-free 필수 규칙** | 조건부 충족. root·unscoped eager 대체 금지. 필수 규칙은 deterministic selection이며 budget 부족을 누락 허가로 바꾸지 않는다 |
| **11. host/surface/version 차이** | 제한 채택. Claude paths rules와 Codex skills/hooks를 각각 구현한다. nested AGENTS·MCP 등록을 universal 자동화로 취급하지 않는다 |
| **12. #316/#334/#341 범위** | 원칙만 제한 채택. 고정 PR은 engine 구현이 아니며 사용자 rollback이 현재 ground truth다. 새 요구의 비호환을 원 PR 결함으로 과장하지 않는다 |
| **13. 첫 두 영상·이미지** | 방향 참고. trace→추출→reflect→다음 행동·비용을 분리한다. GCP 원자성·HA·purge는 별도이며 graph는 필수가 아니다 |
| **14. mAKUL12h1n8 전체 원문** | 세 신호·span·episode·장문 손실·trace-derived code map·feedback/health를 반영한다. 잘못된 특정 앱·static codegraph 파생안은 제외한다 |
| **15. Downloads 9개 자료** | 제공 inventory·transcript·source-corrected 분석을 사용한다. 이번 응답이 9개 파일을 직접 열거나 hash를 재계산한 것은 아니다. AI 앱 설계는 권위로 사용하지 않는다 |
| **16. 논문·OSS 동일 잣대** | 적용. source/approval/delete/host/품질/운영으로 비교한다. 다른 model/budget/judge 점수의 순위화와 중복 generic engine 추가는 하지 않는다 |
| **17. MCP 2026·SDK2** | packet의 protocol 근거를 채택한다. stateless protocol·지속 DB·context·반출 권한을 분리하며 shipping host 호환은 미검증이다 |
| **18. SIE localhost** | thin edge 패턴만 채택. SDK1 설정을 MCP2로 부르거나 upstream 처리까지 local이라고 주장하지 않는다 |
| **19. 동일 PG 운영 부담** | 소유 책임은 명시됐지만 미산정이다. 설치·모델 반입·license·migration·lease/fence·부분 실패·restore·한국어/branch/valid-time 품질을 실제 평가해야 한다 |
| **20. 한 기본 경로·검증 한계** | Hindsight 변경판+PG installed service+thin MCP를 선택한다. 대안은 비교·교체 조건이며 초기 다중 backend 지원안이 아니다 |

MCP localhost synthetic smoke가 입증한 범위는 **무상태 protocol 요청과 지속 application DB가 양립한다는 것**이다. 이 리뷰와 그 smoke는 제품 구현·회사 정책 승인·Agent Flow gate seal·보안·자동화·품질의 증거를 대신하지 않는다.
