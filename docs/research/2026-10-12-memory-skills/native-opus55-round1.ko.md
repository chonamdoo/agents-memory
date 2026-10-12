# agents-memory 추가 조사: 적대적 아키텍처 리뷰 (기준일 2026-10-12)

> **범위 고지**
> - 이 리뷰는 도구, 파일, URL에 접근하지 않고 브리프 본문만으로 작성했다. 브리프 본문은 자동자막 전문, 감사 요약, URL·커밋·타임스탬프로 구성된다.
> - 아래 URL과 로컬 감사 문서(`skills-source-audit.ko.md`, `memory-episode-source-audit.ko.md`, `docs/architecture.ko.md:93–147`)는 브리프에 적힌 그대로 인용했다. 이 리뷰에서 다시 열어 검증하지 않았다.
> - 실험, 측정, host 활성화 확인은 하나도 수행하지 않았다.
> - 공식 AF12-review/bg_134와는 분리된 제안 검토다. 최종 결정은 parent/user가 내린다.

---

## 1. 결론

| 안 | 판정 | 한 줄 사유 |
|---|---|---|
| **A** 현 4 tools 유지 | **채택** (불변 기준선·권위 경로·폴백) | 검증된 유일한 경로다. 나머지는 모두 A 위에 덧붙이는 형태여야 한다. |
| **B** trace→procedure candidate + bounded 피드백 입력 | **조건부 채택** (B1 먼저, B2는 게이트 통과 후) | host와 무관하고 기존 core 안에서 검증할 수 있으며, 실제로 있는 결함(피드백 소비자 미발견)을 닫는다. |
| **C** 유저 코드 dependency stamp + change-review 후보 | **보류** (stamp-only 연구까지만) | 위험 자체는 실재한다. 그러나 근거가 가장 약하고, 오탐이 승인 품질을 떨어뜨릴 수 있으며, fail-open 위험이 있다. |
| **D** 정적 read-only Skills projection | **보류** (코드 없는 설계만 진행, 게이트 충족 후 제한 시험) | 스펙은 Final이다. 하지만 SDK가 릴리스되지 않았고 host 활성화도 검증되지 않았다. 결정적 selector가 모델 판단으로 바뀌고, 철회가 보장되지 않는다. |
| **E** | **거부** | 아래 6절 참조. |

**추가 작업 우선순위:** B1 → D 설계 문서(코드 없음) → B2 → D 제한 시험(게이트 충족 시) → C stamp-only 연구.

**핵심 근거**

1. 영상에서 우리에게 옮겨올 수 있는 것은 원칙 하나다. "탐색을 재사용 가능한 절차 지식으로 바꾼다"[11:11–11:18]. 반면 "완전 자율·비동기·무인"[12:29–12:33]과 "회사 전체 클라이언트에 배포"[15:11–15:35]는 우리 계약과 정면으로 충돌하므로 옮길 수 없다. 충돌하는 계약은 승인 ledger, 정확히 3개인 적용범위, 회사 deny-egress다.
2. 36%→100%[12:36–13:16]는 단일 일화다. 발표자 진술상 증류 원천과 이후 평가 대상이 같은 과제다. 그래서 같은 해법을 다시 쓴 효과인지 일반화인지 구분할 수 없다. 우리 성능 보장의 근거가 될 수 없다.
3. A는 "아무것도 안 하는 안"이 아니다. 다만 A만으로 최종 상태를 고정하려면 결정이 하나 필요하다. 지금 idempotent하게 저장되는 feedback은 감사 범위 안에서 후속 생성 소비자 없이 쌓이고 있다. 이를 "감사 전용"으로 명시하든지, B1로 소비자를 붙이든지 정해야 한다.
4. D를 지금 구현하면 소비를 증명할 수 없는 표면만 늘어난다. 근거는 다음과 같다.
   - 설치된 SDK 2.3.0에는 Skills가 없다.
   - PR 3485는 2026-10-11T14:44:20Z에 merge됐지만 아직 릴리스되지 않았다.
   - Claude Code 2.1.296과 Codex CLI 0.162.1의 활성화 및 보안은 UNVERIFIED다.
   - OMP 18.10.1은 legacy resource와 local fallback만 지원한다.

---

## 2. 현재 구현, 미구현 제안, 외부 주장의 구분

| 구분 | 항목 | 주의 |
|---|---|---|
| 현재 구현 | 4 tools(context/inspect/record/feedback), opt-in bounded context | 유일한 권위 전달 경로 |
| 현재 구현 | PG canonical approved rule ledger | candidate나 reflect artifact는 approved rule이 아니다 |
| 현재 구현 | 승인 binding: body/selector/exception/required/targetset/authority/revision digest | |
| 현재 구현 | 적용범위 정확히 3개: ① 이 로컬 프로젝트 ② 승인한 explicit ID 집합(새 프로젝트는 재동의) ③ 설정된 approver/audience의 팀·프로젝트 공유 | 팀 전체 강제가 아니다 |
| 현재 구현 | auth/source/snapshot/lease/deletion admission/publication/delivery fence | |
| 현재 구현 | exact full-input provenance, source_speaker | source_speaker는 승인이나 사실을 보증하지 않는다 |
| 현재 구현 | root CLAUDE.md/AGENTS.md 미설치, startup body 0 | |
| 현재 구현 | feedback idempotent 저장 | 후속 생성 소비자는 감사 범위에서 발견되지 않았다(전역 부재 증명은 아님) |
| 현재 측정 | context 749B / catalog 3922B / discovery 282B | 특정 fixture의 wire 측정이다. 총 native prompt나 토큰 0을 보증하지 않는다 |
| 현재 검증 | 747 tests + native 3 소비 | 기존 memory에 대한 증거다. Skills 기능의 증거가 아니다 |
| 현재 검증 | OMP strict 설치는 write 전에 거부, advisory는 지원 | generic MCP에서 모델 행동 강제나 소비 증명은 불가능하다 |
| 현재 부재 | 유저 코드 dependency→change-review index, Skills 엔드포인트 | code snapshot, path selector, fence는 있다 |
| 미구현 제안 | B, C, D | 이 리뷰의 대상 |
| 외부 실제 코드 (각각 범위가 다르다) | HF server custom handlers, mcpc verified reader, fast-agent eager installer, HumanLayer `agent-iteration.ts`(MIT), BAML `ns_memory`(per-turn prototype, license 미확인), python-sdk main(미릴리스) | 우리 시스템 동작의 증거가 아니다 |
| 발표자 주장 (원천 미확보) | Runlayer distiller, PII/injection 검사, MCP gateway, 6개월 내부 운영[08:16–08:20], 36→100, 토큰 절감[13:22–13:42] | gate, ACL, tenant, adversarial eval, rollback의 원천 자료가 없다 |

---

## 3. 영상 주장 판독

**판독 기준**
- 타임스탬프는 사용자가 제공한 jDdgfTp_PXw(17:37)의 en-orig 자동자막 기준이다. 432 cue이며 끝은 17:35다.
- 원본 u-o0sW9nwmk(18:31, 440 cue, 끝 18:28)의 타임라인으로 환산하지 않았다.
- 기존 mAKUL12h1n8의 43–53분 stale/human feedback 논의와 섞지 않았다.
- 검수되지 않은 자동자막이다("Rumlayer", "run later", "MCB gateway", "SKS" 등 오인식이 보인다). 그래서 단어 수준의 논증은 피했다.

| 시각 | 발표자 주장 | 분류 | 우리에게의 함의 |
|---|---|---|---|
| [02:08–02:39] | progressive disclosure: 요약을 먼저 보고 필요할 때 본문을 주입한다 | 개념 정의 | ext-skills와 정합한다. 다만 "요약을 먼저 본다"는 것은 메타데이터 비용이 0이 아니라는 뜻이다(zero-body ≠ zero-metadata). |
| [05:49–06:18] | `npx skills`는 prompt injection, root 스크립트, 남의 API key를 함께 설치한다. 매일 수천 개를 스캔한다 | 위험 인식은 유효, 규모 주장은 검증 불가 | D를 하더라도 실행 파일이나 allowed-tools 없이 본문만 담아야 한다는 근거가 된다. |
| [07:54–08:12] | remote MCP를 회사의 source of truth로 두고 역할별 정책을 강제한다 | 발표자 설명 | 서버가 통제할 수 있는 것은 **전달**뿐이다. 모델의 **소비와 준수**는 강제하지 못한다. 우리 baseline과 같은 결론이다. |
| [08:28–08:36] | skills over MCP WG가 있고 API는 미확정이다 | 기준일 기준으로 낡음 | 현재는 ext-skills stable, SEP2640 Final이다. 발표가 이전 상태를 반영한다(발표일 자체는 미확인). |
| [08:43–08:55] | resources 지원이 혼재해 tools를 쓴다 | 관찰로서 우리 OMP 결과와 정합 | tools로 전달한 본문은 스펙의 consent, digest 검증, no-higher-authority 의미론을 얻지 못한다. 실질적으로 우리 4 tools와 같다. |
| [09:07–09:18] | "거의 모든 클라이언트에서 동작하고, 배포 문제는 사실상 해결" | **과장** | tool 호출 가능 ≠ skill 활성화 ≠ 소비. 우리 host 매트릭스와 충돌한다. |
| [11:11–11:18] | 탐색을 재사용 가능한 절차 지식으로 | 원칙 | 옮겨올 수 있는 유일한 핵심이다. |
| [11:22–11:39] | 성공 run의 trace를 frontier LLM으로 증류한다 | 발표자 설명 | 회사 deny-egress 아래에서는 서버에서 외부 LLM을 호출할 수 없다. |
| [11:41–12:27] | 실패가 가장 풍부한 신호다 | 주장 | 동의한다. 다만 실패 원인이 일회성(환경이나 특정 PR에 한정)인지 구분하지 않으면 잘못 일반화된다. |
| [12:29–12:33] | 완전 자율, 비동기, 무인 | 설계 선택 | 승인 ledger와 정면 충돌한다. **거부**. |
| [12:36–13:16] | Sonnet 4.6, Chromium fork, AWS Lambda에서 36%→100% | 단일 일화 | n, holdout, success oracle, task 변형, failure log, repo가 모두 불명이다. 증류 원천과 평가가 같은 과제이므로 일반화의 근거가 아니다. |
| [13:22–13:42] | 탐색 공간이 줄고 tool call과 토큰이 감소한다 | 수치 없음 | 가설이다. |
| [13:45–14:25] | 지능은 빌린 것이니 사라지기 전에 절차를 보존하라 | 동기 | 반론: 강한 모델이 증류한 절차를 약한 모델이 실행할 수 있다는 근거가 제시되지 않았다. |
| [15:11–15:35] | 유사 run을 묶어 증류 → PII/prompt injection "등" 검사 → 라이브러리 → gateway로 전 클라이언트에 배포 | 발표자 설명 | 검사 방식, 임계값, 우회 내성, ACL, tenant, rollback이 모두 불명이다. 우리의 3개 적용범위와 충돌한다. |
| [15:38–15:47] | "항상 최신, 계속 갱신" | 설계 선택 | 승인 없는 상시 변경은 authority drift다. 우리에게는 결함이다. |

**Voyager** (https://voyager.minedojo.org/, https://arxiv.org/abs/2305.16291)

브리프 요약상 Voyager의 구성은 다음과 같다.
- Minecraft, GPT-4, code-as-action
- 환경 피드백, 실행 오류, self-verification
- description embedding으로 top-5 skill 검색
- 가중치 미세조정 없음

우리 상황으로 옮길 때의 한계는 세 가지다.
- (a) 게임 상태라는 결정적인 성공 오라클이 있었다. 우리 규칙과 절차는 대부분 자연어다.
- (b) skill이 실행 가능한 코드여서 실행 오류로 교정됐다. 자연어 candidate는 틀려도 오류가 나지 않는다.
- (c) 단일 에이전트, 단일 환경이어서 tenant, 권한, 삭제 개념이 없다.

따라서 기업 코드나 메모리의 품질·안전성 근거가 되지 않는다.

---

## 4. A–D 비교 매트릭스

| 기준 | A 현상 유지 | B procedure candidate + 피드백 입력 | C dependency stamp | D Skills projection |
|---|---|---|---|---|
| **판정** | 채택(불변) | 조건부 채택(B1→B2) | 보류(stamp-only 연구) | 보류(설계만, 게이트 후 시험) |
| **착수 시점** | 계속 | B1 즉시. B2는 oracle과 model route 확정 후 | B 리뷰 부하를 관찰한 뒤 | SDK 릴리스, pin, host 검증 후 |
| **구현 영향** | 없음 | 중: 기존 typed extract에 새 kind 추가, 새 저장소 금지 | 중~대: 언어별 의존 추출, 오탐 튜닝 | 중: handler + URI/digest/index/cache policy를 직접 구현(SDK는 adapter뿐) |
| **장점** | 검증된 범위, host 무관, startup 0, 모든 fence 유지 | 실재 결함을 해소, host 무관, 기존 test 하네스로 검증 가능, 거절 재제안 방지 | 코드 변경에 따른 규칙 부패라는 실제 위험을 겨냥 | 표준 경로, immutable URI+digest로 감사 용이, read-only |
| **단점** | 피드백이 쓰이지 않고 쌓임, 절차 축적 경로 없음, 표준 host와 상호운용 없음 | 리뷰 큐 증가, trace 처리로 민감정보 노출면 증가, 효용 미측정 | 근거가 가장 약함, 리뷰 피로, binding 변경 시 기존 승인이 무효화될 위험 | 결정적 적용성이 모델 판단으로 바뀜, 철회 미보장, 메타데이터 비용, host 매트릭스 유지 비용 |
| **정확성** | 결정적 selector/exception 평가 | oracle이 없으면 운을 절차로 굳힘, 일회성 실패를 일반화, 승인 규칙의 재서술 중복 | path/hash는 의미 변경을 놓치고 rename으로 오탐. semantic_contract digest와 혼동 위험 | exception이 손실됨. required 의미를 전달할 수 없음(no higher directive authority) |
| **보안** | 공격면 최소 | trace의 tool output을 통한 간접 prompt injection 영속화, secret/PII, extractor egress | 직접 위험은 낮음. stale 판정이 required 제거로 이어지면 fail-open | host cache는 deletion fence 밖. cross-origin consent는 host 책임이며 미검증 |
| **context** | bounded opt-in. 측정값은 fixture 한정 | client context 증가 0이어야 함(서버 내부 입력, 상한 필요) | 변경 알림이 context에 섞이면 비용 발생 | discovery 메타데이터가 host별로 미측정. eager host에서는 on-demand 성질이 깨짐 |
| **host 지원** | generic MCP tools(소비 증명 불가는 모든 안 공통) | 무관(기존 inspect/feedback으로 표면화) | 무관 | Claude Code·Codex UNVERIFIED, OMP는 legacy fallback, mcpc reader만 실제 확인 |
| **운영 수용성** | 높음 | 중(승인자 rubber-stamp 위험, 큐 상한 필요) | 낮음~중(오탐 피로) | 중~낮음(게시·철회 runbook, 미릴리스 의존) |
| **미확인 전제** | 없음 | 로컬 또는 승인된 extractor route, success 판정 주체, trace 보존·삭제 정책 | 대상 언어와 저장소 범위, stamp 저장 위치 | SDK 릴리스, host activation 동작, 철회 전파 |
| **라이선스** | — | HumanLayer MIT 참조 가능(attribution). BAML 코드 복사 금지 | — | SDK와 spec 라이선스는 pin 시점에 확인 |

---

## 5. 안별 상세와 반론

### A: 채택 (불변 기준선)

- context tool이 **유일한 권위 경로**라는 점을 불변식으로 문서화한다. B, C, D의 산출물은 어떤 경우에도 A를 대체하거나 우회하지 않는다.
- **반론:** "A만으로 충분하다. 다른 안의 효용은 전부 가설이다."
  - **재반론:** 효용이 가설이라는 지적은 맞다. 이것이 B2와 D를 게이트 뒤에 둔 이유다.
  - 다만 쓰이지 않고 쌓이는 feedback 저장은 운영상 거짓 신호가 된다. 사용자는 피드백이 반영된다고 오인한다.
  - 따라서 "A 고정"을 선택하더라도 feedback을 감사 전용이라고 명시하는 것은 필수다.

### B: 조건부 채택 (좁게, 두 단계로)

**B1. bounded 피드백 소비자 (1순위)**

- **첫 작업:** 감사 범위 밖까지 포함해 피드백 소비자가 정말 없는지 전역으로 확인한다. 이미 있다면 B1은 불필요하다.
- **입력 위치:** candidate 생성 단계에만 넣는다.
  - 기존 영상의 "fourth input" 제안은 최종 report의 입력이었다. 모든 extract 입력이나 fine-tuning이 아니었다. 이 좁은 범위를 그대로 따른다.
- **입력 조건:**
  - 같은 scope, 같은 realm이어야 한다.
  - revision digest를 포함한다.
  - 건수와 바이트에 상한을 둔다.
- **거절 항목 처리:** 거절된 body 원문을 모델에 주입하면 anchoring 위험이 있다. 모델 입력에는 사유만 넣는다. 재제안 차단은 생성 후 digest와 정규화 텍스트를 결정적으로 비교해 처리한다.
- **분류:** durable 피드백과 instance(PR) 한정 피드백을 구분한다. HumanLayer `agent-iteration.ts`(MIT, 653b641)가 실제 controller 참조 사례다. instance 한정 피드백은 일반화 입력에서 제외한다.
- **출력:** 항상 candidate다.
  - required/authority/targetset은 extractor가 설정할 수 없다. 승인자가 binding 전체에 서명한다.
  - 기존 approved rule의 변경 제안은 새 revision candidate로만 만든다. 기존 rule은 바꾸지 않는다. supersede는 승인 시점에 원자적으로 처리한다.

**B2. trace→procedure candidate (게이트 후)**

- **게이트:** 아래 세 가지가 parent/user 결정으로 확정되어야 착수한다.
  - ① success 판정: 결정적 oracle(테스트, 명시적 사용자 확인)만 인정한다. 모델의 자가 판정은 `unverified` 라벨을 단다.
  - ② extractor route: 로컬 모델 또는 승인된 route만 쓴다.
  - ③ trace 보존 기간과 삭제 연쇄 정책.
- **독립 origin 하한:** 단일 run에서 증류한 candidate는 36→100 문제를 그대로 들여온다.
  - 서로 다른 과제나 세션에서 온 독립 origin이 최소 몇 개 필요한지를 파라미터로 둔다. 구체적 값은 검증 전이므로 제시하지 않는다.
  - 같은 agent가 같은 내용을 반복해서 말해도 독립 origin이 아니다.
- **lineage:**
  - source snapshot lease 아래에서 생성한다.
  - deletion admission이 진행 중인 source에서는 생성을 금지한다.
  - source가 삭제되면 파생 candidate를 격리하거나 삭제한다.
- **변형 B2':** host 세션(이미 팀 승인된 Claude/Codex)이 `record`로 candidate를 제출하는 방식이다. 서버에서 새로 외부로 나가는 egress는 없다.
  - 그러나 baseline은 "팀 승인은 MCP/외부 LLM 허용이 아니다"라고 명시한다. 이 방식이 허용 범위에 드는지는 정책 해석이 필요하다.
  - host 모델의 행동은 강제할 수 없다.
  - 이 리뷰는 허용된다고 가정하지 않는다.
- **반론:** "B는 Runlayer의 재구현이다. 기존 cited reflect로 충분하다."
  - **재반론:** 기존 reflect가 procedure를 표현할 수 있다면 B2는 불필요하다. 이 점은 **미확인**이며 B2 전에 확인해야 한다.
  - 어떤 경우에도 별도 파이프라인이나 저장소는 거부한다.
- **반론:** "승인 큐가 늘면 승인자가 rubber-stamp하게 되고, 승인 ledger의 의미가 약해진다."
  - **재반론:** 가장 강한 반론이다.
  - B1은 새 candidate 원천을 추가하지 않는다. 기존 생성의 품질만 바꾼다.
  - B2에는 scope별 큐 상한과 독립 origin 하한을 적용한다.
  - 승인 화면에 full-input provenance와 untrusted 세그먼트 표시를 함께 보여준다.
  - 승인을 제거해서 병목을 푸는 방식은 authority cutover이므로 불가하다.

### C: 보류 (stamp-only 연구)

- **최소 형태:**
  - 승인 시점에 selector가 해석한 경로 집합과 내용 digest를 **별도 관측 레코드**로 저장한다.
  - 이 레코드를 승인 binding digest에 넣지 않는다. 넣으면 기존 승인 전부의 digest 의미가 바뀌어 대량 재승인이나 무효화가 일어난다.
- **변경 감지 시:**
  - 상태는 `review_required` / freshness `UNKNOWN`으로 둔다.
  - **required 규칙은 계속 전달**하고 UNKNOWN 표시만 덧붙인다.
  - 무효화나 삭제는 승인자만 할 수 있다.
  - 이렇게 해야 "나중에 필수 규칙이 stale 취급으로 사라지는" fail-open을 막을 수 있다.
- 메모리 엔진 자체의 `semantic_contract` digest와 유저 코드 digest는 별개 차원이다. 이름과 저장 위치를 분리한다.
- **근거 상태:**
  - 원 영상의 code-map/stale은 "remaining problem / my one idea / would / could" 수준이었다.
  - 감사에서 dependency→change-review index는 관찰되지 않았다.
  - CueFinder나 코드 그래프 재사용 가정은 제외된 상태다.
- **반론:** "C야말로 차별점이다. 코드 변경에 따른 규칙 부패가 핵심 위험이다."
  - **재반론:** 위험은 인정한다. 그러나 오탐과 미탐 비율을 모르는 상태에서 알림을 켜면 리뷰 피로가 B의 승인 신뢰까지 갉아먹는다.
- **반론:** "변경 시 required를 유지하면 삭제된 코드에 대한 규칙을 계속 강요하게 된다."
  - **재반론:** 맞다. 오적용 비용과 누락 비용 사이의 비대칭 판단(누락이 더 위험하다는 전제) 자체가 parent/user가 결정할 사항이다.

### D: 보류 (설계만 진행, 게이트 후 제한 시험)

**스펙 근거**
- ext-skills stable 167da6c, SEP2640 Final 기준이다.
- 엔드포인트: `skills/list`, `skills/get`, `resources/read`, 선택적 directory.
- 필수 표시: 완전한 URI, digest, size, verbatim frontmatter.
- host 의무: bytes·size·YAML 검증, cache는 immutable일 때만 허용하거나 rehash, lazy fetch(connection/list/approval 시점에 prefetch 금지), cross-origin과 nested 리소스에 대한 fresh consent.
- 금지 사항: implicit execution/allowed-tools 금지, 상위 지시 권한 없음.
- 일반 `resources/read`는 activation도 consent도 아니다.
- **host에는 polling 의무가 없다.** 따라서 캐시를 즉시 철회하거나 이미 들어간 context를 잊게 할 보장이 없다.

**적격 기준 (첫 시험에 한정)**
- approved만 대상으로 한다. candidate와 reflect artifact는 절대 포함하지 않는다.
- secret과 PII가 없어야 한다.
- 적용범위는 ①(이 로컬 프로젝트)만이다. ②는 프로젝트 집합별 projection과 새 프로젝트 재동의가 필요하고, ③은 audience별 realm이 필요하므로 제외한다.
- selector가 단순(프로젝트 전체)하고 exception이 없는 항목만 대상으로 한다. selector/exception은 host가 평가하지 않는다. 모델은 description만 보고 활성화를 판단하므로 정확성이 떨어진다.
- **required 규칙은 첫 시험에서 제외한다.** revision이 바뀐 뒤 host cache에 남은 이전 본문이 새 본문과 충돌할 수 있고, D로는 required 의미도 전달할 수 없다.
- 실행 파일, allowed-tools, 스크립트 없이 단일 SKILL.md 본문만 둔다. 512 files/16 MiB floor보다 훨씬 작게 유지한다.

**게시와 철회**
- list, URI, digest를 하나의 PG 트랜잭션에서 publication fence 아래 원자적으로 갱신한다.
- revision은 immutable URI로 둔다.
- rollback은 이전 immutable revision을 가리키는 새 list를 게시하는 방식이다. 기존 것을 변경하지 않는다.
- retract는 list에서 제거하는 것이다. host 잔존 가능성은 "best-effort 철회"로 문서화한다.
- private TTL은 auth/realm cache key나 revocation을 대체하지 않는다.
- deletion admission 측면에서는 의미가 약해진다. "삭제됨"이 아니라 "우리 서버가 더 이상 제공하지 않음"이 된다. 사용자 문서에 그대로 밝힌다.

**SDK와 host 상태**
- PR 3485(9a754b0, `docs/advanced/skills.md`)는 handler adapter와 schema만 제공한다. discovery, index, cache policy, host YAML consent, origin trust는 제공하지 않는다.
- 지금 git으로 pin하면 미릴리스 코드에 의존하게 되어 재현성과 공급망 위험이 생긴다.
- HF `skill-resources.ts`(dce2d5f)는 서버 handler 형태를 보여주는 참조일 뿐이다.
- mcpc verified reader는 프로토콜 적합성을 확인하는 reader일 뿐, 모델 소비의 증거가 아니다.
- fast-agent는 eager installer다. 그 host에서는 우리의 on-demand/startup 0 성질이 성립하지 않는다.
- ChatGPT의 정적 plugin import는 Codex CLI나 live cache와 다르다.

**반론**
- **반론:** "스펙이 Final이니 지금 하면 선점할 수 있고, additive라 위험도 없다."
  - **재반론:** 선점 이득은 host가 activation을 구현해야 생긴다. 미검증 상태에서는 측정할 수 없는 표면, 철회되지 않는 사본, host 호환표 유지 비용만 늘어난다.
  - 그래서 지금은 적격 기준과 철회 의미론 문서만 만든다.
- **반론:** "Runlayer처럼 tools로 skill을 전달하면 host 문제를 피할 수 있다."
  - **재반론:** 그 역할은 이미 4 tools가 한다. tools 기반 전달을 skill이라고 부르면 consent, digest, authority 의미론 없이 이름만 빌리는 셈이다.

---

## 6. E 거부 사유

| 대상 | 거부 사유 |
|---|---|
| protocol 선행 전체 rewrite | 747 tests와 native 3 소비라는 검증 자산을 버리게 된다. 미릴리스 SDK에 의존한다. 스펙에도 host에도 rewrite를 요구하는 근거가 없다. |
| BAML/Jev 의존 | BAML v1의 typed return은 truth, approval, auth를 보증하지 않는다. 기존 Pydantic을 다시 작성할 근거가 없다. Jev는 TypeSafe hosted decision API로, weights나 local deployment에 대한 증거가 없고 회사 egress도 허용되지 않는다. BAML `ns_memory`(dcc3d33)는 model overwrite/delete, auto trust, 오류 은닉, approval ledger 부재를 가진 per-turn prototype이며 license가 미확인이라 코드 복사를 보류한다. |
| 조직 전체 auto-promote | 3개 적용범위 계약과 승인 binding을 위반한다. candidate가 권한을 얻는 authority cutover다. 영상의 무인 주장[12:29–12:33]을 그대로 옮기는 것이다. |
| giant catalog | global catalog는 상한이 없고, full catalog를 모델에 주입하는 것은 금지되어 있다. zero-body여도 zero-metadata가 아니다. |
| root full body | startup body 0과 root 미설치 계약을 위반한다. |

---

## 7. 공통 불변식 (모든 안의 게이트)

1. candidate는 approved rule을 덮어쓰지 않고 권한을 부여하지 않는다. promotion은 승인 binding 전체 digest에 대한 승인으로만 이루어진다.
2. stale, UNKNOWN, projection 실패 어느 것으로도 **required 규칙이 사라지지 않는다**(fail-open 금지). 열화가 생기면 required는 계속 전달하고 경고를 붙인다.
3. 생성되거나 투영된 모든 산출물은 exact full-input lineage를 보존한다. deletion admission 시 연쇄 처리된다.
   - **미해결 정책:** 승인 규칙의 원천이 삭제될 때 규칙을 존속시킬지 결정해야 한다.
   - 삭제된 데이터를 담은 본문이라면 deletion이 우선해야 한다.
   - 그 결과로 required가 소멸한다면 조용히 처리하지 말고 승인자에게 명시적으로 알려야 한다.
4. 회사 realm에서는 외부 LLM, telemetry, egress가 없다. 개인 cloud는 같은 core를 쓰되 realm, credentials, storage, cache, model routes, telemetry를 분리한다. 개인 cloud의 candidate는 회사 realm으로 흐르지 않는다.
5. startup body 0, root 설치 없음, full catalog 모델 주입 없음.
6. 4 tools의 context가 유일한 권위 경로다. D 산출물은 보조 사본이다.
7. 749/3922/282B 같은 fixture 수치를 일반 보증으로 표기하지 않는다.

---

## 8. 가장 약한 주장과 미확인 사항 (약한 순)

**발표자 주장**
1. "거의 모든 클라이언트에서 동작하고 배포는 해결됐다"[09:07–09:18]. 우리 host 매트릭스와 정면 충돌한다.
2. 36→100의 일반성[12:36–13:16]. 같은 과제로 재평가했고, n, oracle, holdout이 없다.
3. 무인 자율의 안전성[12:29–12:33]과 "검사로 충분하다"[15:15–15:33]. 검사의 실체, 우회 내성, rollback의 원천이 없다.
4. 토큰·비용 절감[13:22–13:42]. 수치가 없다.
5. Voyager의 기업 환경 전이[09:44–11:18]. 오라클과 실행 피드백 구조가 다르다.

**우리 측 전제**
6. "피드백 소비자 없음"은 감사 범위 안에서 확인한 부재일 뿐이다.
7. fixture 바이트 수치가 실제 context 비용을 대표한다는 암묵적 가정.
8. host가 스펙대로 digest/size/YAML 검증, lazy fetch, consent를 수행하는지. 전부 미검증이다.
9. 철회가 host cache와 이미 들어간 context까지 전파되는지. 스펙상 보장되지 않는다.
10. 로컬 extractor의 가용성과 품질. 미확인이다.
11. path/hash stamp가 의미적 적용성 변화를 포착하는지. 미확인이다.
12. 기존 cited reflect가 procedure를 표현할 수 있는지. 미확인이다.

**외부 사실**
13. 발표일, Python SDK의 Skills 릴리스 시점, Claude Code/Codex의 ext activation 구현.
14. BAML demos의 license, Jev의 local deployment 가능성.
15. 자동자막의 정확성(수동 검수나 별도 STT 없음).

---

## 9. 미실시 항목 (실시된 것으로 간주 금지)

| 대상 | 필요한 검증 (모두 미실시) |
|---|---|
| B1 | 동일 digest 재제안 0건을 확인하는 fixture 테스트. 거절 사유 반영에 대한 인간 평가. client context bytes 불변 확인. |
| B2 | source run과 eval task 분리(lineage run ID ∩ eval set = ∅). 승인률, 거절 사유, 리뷰 시간, 유해 candidate 비율. trace에 주입 문자열을 심은 adversarial fixture. |
| C | 실제 저장소 변경 이력을 replay해 오탐·미탐 측정. |
| D | host별 discovery 메타데이터 바이트, 실제 activation 여부, 철회 후 잔존 여부를 수동 관찰. mcpc로 적합성 확인(소비 증명과는 별개). |
| 공통 | 로컬 extractor 품질. injection 내성 adversarial eval. 미릴리스 SDK 코드의 동작. |

---

## 10. 결정 귀속

이 문서는 적대적 비판이며 채택 결정이 아니다. parent/user가 결정해야 할 항목은 다음과 같다.
- A의 피드백을 "감사 전용"으로 둘지, B1 소비자를 붙일지
- B2의 success oracle, extractor route, 독립 origin 하한
- B2' host 측 증류가 정책상 허용되는지
- C의 오적용과 누락 비대칭 판단
- 원천 삭제 시 승인 규칙을 존속시킬지
- D 게이트(SDK 릴리스, host 검증)의 충족 판정
