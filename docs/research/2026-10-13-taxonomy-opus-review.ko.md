# 적대적 리뷰: Profile / Log / Notes / 파일·스킬 분리안

> **표기 규칙**
> - **[소스]**: 브리프에 적힌 1차 자료 요약입니다(고정 커밋 기준). 이번 작업에서 원문을 다시 열어 보지 못했으므로 요약에 적힌 범위 밖의 OSS 동작은 주장하지 않습니다.
> - **[제약]**: 사용자가 고정한 조건입니다.
> - **[추론]**: 리뷰어의 논리적 추정입니다.
> - **[제안]**: 설계 권고입니다.
> - **[미측정]**: 수치나 효과를 확인하지 않은 항목입니다.
>
> 현행 agents-memory 소스는 이번에 열람하지 않았습니다. 그래서 "구현된 사실"로 단정하는 문장은 없습니다. 이 리뷰는 AF 구현 승인, 회사 사용 가능성, 운영 효율을 선언하지 않습니다.

---

## 0. 결론

| 결정 | 판정 | 핵심 이유 |
|---|---|---|
| **4분류 체계 도입** | **조건부 추천 (대안 B 한정)** | 하나의 canonical ledger 위에서 *파생 view와 관리용 태그*로만 씁니다. 독립 store나 권한 단위로 쓰면 안 됩니다. 네 이름은 서로 다른 축(대상, 시간, 수명, 매체+실행성)을 섞고 있어서 상호배타적인 분류가 될 수 없습니다. |
| **Profile always-on** | **비추천 (보류)** | ① MCP 연결이 자동 주입을 보장하지 않으므로 [제약] "항상"을 host 전반에서 약속할 수 없습니다. ② 매 턴 높은 신뢰 위치에 들어가므로 누출, 주입, 낡은 사실의 피해가 *지속적*입니다. ③ 효용(핵심 사실 몇 개)에 비해 위험이 비대칭적으로 큽니다. 대체안은 **scope에 묶이고 운영자가 서명하며 hard budget을 가진 pinned set**입니다. 회사 scope의 기본값은 비어 있음입니다. |
| **현행 유지(A)** | **기본선으로 유지** | 분류를 추가하기 전에 A 대비 개선을 측정해야 합니다. |
| **별도 store + always-on(C)** | **거부** | 정체성 분열, 삭제 fan-out, 경계 누출이 생깁니다. |

한 줄 요약: **분류는 "어떻게 보여줄지(view)"이지 "무엇이 참이고 누가 허가했는지(lifecycle/grant)"가 아닙니다.** 이 둘을 섞는 순간 P1 실패가 구조적으로 생깁니다.

---

## 1. P1 / P2 실패 시나리오 (기준 10 전반)

### P1 — 경계·권한·삭제 위반 (발생 시 즉시 차단해야 함)

| # | 시나리오 | 트리거 | 영향 | 방어 [제안] |
|---|---|---|---|---|
| P1-1 | **조건부 프로젝트 선호가 전역 Profile로 오승격** | "이 repo에선 tabs" → 분류기가 "사용자는 tabs 선호"로 일반화 | 모든 프로젝트와 host에 잘못된 지침이 매 턴 주입됩니다 | scope 축소는 허용하고 확대는 운영자 서명 없이는 금지합니다. 승격은 같은 claim id에 새 revision을 두고, scope 변경 diff를 명시합니다 |
| P1-2 | **회사→개인 경로 누출/fallback** | 회사 executor가 불가할 때 개인 Jev로 분류를 넘기거나, 공용 Profile이 개인 세션에 로드됨 | [제약] 위반이며 데이터 반출입니다 | executor를 scope에 바인딩하고, 회사 scope에는 fallback 없이 *실패 시 정지*합니다. Profile view도 scope별로 분리합니다 |
| P1-3 | **corpus 철회 후 skill 상세 잔존** | 원문을 철회/삭제했지만 그로부터 파생된 요약·스킬·Profile 항목이 남음 | 철회된 정보가 실행 지침으로 계속 작동합니다 | derivation edge(파생 그래프)로 철회를 연쇄시키고, 활성 파생물에서 철회된 원문 참조가 0인지 검증합니다 |
| P1-4 | **Profile을 통한 지속적 prompt injection** | 오염된 기억 한 줄이 always-on 영역에 들어감 | 세션마다 재주입되어 영속적인 행동 변화가 생깁니다. MemoryGraft는 오염된 retrieved experience가 지속적 unsafe 행동을 낼 수 있음을 보였습니다 [소스, 일반화 강도는 과장 금지] | always-on을 하지 않습니다. pinned 항목은 *데이터로 인용 렌더링*하고 출처를 병기합니다. 지침화는 별도 서명이 필요합니다 |
| P1-5 | **후보 ≠ 승인 혼동** | 높은 confidence, MCP preview token, 도구 annotation을 승인으로 간주 | 사람 승인 없이 규칙이 활성화됩니다 | lifecycle 전이 `approved`는 운영자 서명 검증으로만 일어납니다. mnema의 hash token은 *입력 확인*일 뿐입니다 [소스] |

### P2 — 품질·비용 저하 (측정 후 임계치로 관리)

| # | 시나리오 | 방어 [제안] |
|---|---|---|
| P2-1 | **"오늘/지난주" 해석 오류**: 질의 시각이나 recorded_at 기준으로 해석함 | 발화의 `source_event_time` 기준으로 해석합니다. 원문 표현을 보존하고, 해석 결과는 후보 속성으로 둡니다. 기준 시각이 없으면 unresolved입니다 |
| P2-2 | **Notes 재개 실패**: 다른 thread의 메모가 섞이거나, TTL은 남았는데 작업이 끝났거나, TTL은 만료됐는데 작업이 진행 중 | thread/task identity(코드가 부여)로 키를 둡니다. 종료는 이벤트 기반입니다. 재개 시 원문 revision staleness를 검사합니다 |
| P2-3 | **분류 실패와 hard drop**: 제외가 비가역 삭제로 이어짐 | 제외는 soft(원문 포인터 유지, 재평가 가능)로 하고, 표본 재감사를 합니다 |
| P2-4 | **batch 경계 context 손실**: 청크를 넘는 참조("그거 말고 아까 방식")가 끊김 | 증분 창에 scope의 bounded anchor(기존 claim 요약)를 동봉하고, 경계에서 걸친 항목은 review로 보냅니다 |
| P2-5 | **context 한도 초과**: pinned + retrieval이 예산을 넘어 출처/경고가 잘림 | section별 hard budget을 둡니다(codex-agent-mem처럼 micro/normal/full 1000/2200/3600자 hard budget과 section limit을 둔 선례 [소스]). 잘라낼 때는 *내용을 자르고 출처는 유지*합니다 |
| P2-6 | **Log 모순 오판**: 나중에 기록됐지만 더 이른 사건이 최신으로 취급됨 | recorded_at 순이 아니라 source_event_time 기준으로 판단하고, 충돌은 보류합니다 |

---

## 2. 분류별 평가 (기준 1–7)

### 기준 1. 분류 축 혼합과 정체성 유지

**판정: 축이 섞여 있습니다. 상호배타적 분류가 아닙니다.** [추론]

| 이름 | 실제로 정의하는 축 |
|---|---|
| Profile | *대상*(사용자) + *조회 정책*(항상 로드) + *수명*(장기) |
| Log | *시간*(날짜 있는 사건) + *선별 정책*(관련성 높은 것만) |
| Notes | *수명*(단기) + *범위*(작업) |
| 파일·스킬 | *저장 매체*(파일) + *조회 정책*(필요 시) + *실행성*(스킬=지침) |

반례: "2026-10-01, 프로젝트 X에서 pnpm으로 전환 결정(package.json 커밋 abc)."
이것은 사건(Log)이면서 프로젝트 선호(Profile 후보)이고, 진행 중 작업의 메모(Notes)이며, 파일 revision(파일)입니다. 네 곳에 동시에 해당합니다.

**정체성 유지 방법 [제안]**
- 사실 하나에는 **canonical claim id 하나**를 둡니다. 수정은 같은 id의 **새 revision**(append, 이전 revision은 감사용으로 보존하되 삭제 요청 시 실제 삭제하고 tombstone을 남김)입니다.
- 분류는 claim의 **파생 속성/태그**이며 다중 소속을 허용합니다. view는 질의 결과입니다.
- 축을 직교화합니다:

| 축 | 값 예 | 누가 결정 |
|---|---|---|
| provenance | source, speaker, host/session/thread/agent | 수집 코드 [제약] |
| 시각 | `source_event_time`, `recorded_at` | 수집 코드 [제약] |
| 유효 기간 | `valid_from/valid_to` | 원문에 명시된 경우만 사실이고, 그 외에는 모델이 제안하는 후보 속성 |
| kind | preference / fact / event / decision / procedure / task-state | 모델 후보 → 검토 |
| scope | user / project / thread / org | 서비스가 grant로 검증 [제약] |
| lifecycle | proposed / approved / active / expired / superseded / revoked / deleted | 서비스 + 운영자 서명 |
| retrieval policy | pinned / suggest / on-demand | 운영자 정책 |
| executability | data / instruction | 운영자 서명으로만 instruction |

4분류는 이 축들의 **조합 프리셋(view 정의)**으로 재표현할 수 있습니다. 이것이 B안의 본질입니다.

### 기준 2. Profile 항상 로드

| 항목 | 평가 |
|---|---|
| 효용 | coding agent에게 매 턴 필요한 사용자 사실은 소수입니다(응답 언어, 일부 도구 선호) [추론]. 그 대부분은 host별로 운영자가 관리하는 설정 파일 방식으로 이미 줄 수 있을 가능성이 큽니다 [추론, 미측정]. |
| token 비용 | 세션×턴×host 수에 비례하는 고정비입니다. prompt cache로 상쇄할 수 있는지는 host마다 다릅니다 [미측정]. |
| 민감 정보 | 개인 사실이 회사 세션에, 회사 사실이 개인 세션에 들어가는 *양방향 누출 경로*가 생깁니다. 단일 전역 Profile은 [제약](회사→개인 차단)과 구조적으로 충돌합니다. |
| prompt injection | 최고 신뢰 위치에 매 턴 들어가므로 오염 1건의 피해가 영속합니다(P1-4). |
| 낡은 사실 | 조회 시점의 관련성 검사가 없어서, 낡은 사실이 *기본으로 이깁니다*. 반박할 근거가 retrieval되지 않으면 수정 기회도 없습니다. |
| 보장 가능성 | MCP 연결은 자동 주입을 보장하지 않습니다 [제약]. host마다 hook 유무가 달라 "항상"이 host별로 다르게 동작합니다. 그래서 *보장되는 것처럼 보이는 비보장*이 생깁니다. |

**결정: always-on 비추천.** 대체안 [제안]:
`pinned` 정책을 둡니다. 운영자가 서명하고, scope별이며, hard budget을 갖고, 데이터로 인용 렌더링하고, 출처와 승인일을 병기합니다. 회사 scope의 초기값은 빈 집합입니다. 주입 경로가 없는 host에서는 "pinned 미적용"을 명시적으로 보고합니다.

### 기준 3. Log

- **두 시각은 분리합니다** [제약]: 사건 시각(`source_event_time`)과 기록 시각(`recorded_at`)은 수집 사실이며 모델이 메우지 않습니다. 비어 있으면 비어 있는 채로 둡니다.
- **상대 시간 표현**: "지난주"는 발화의 source_event_time 기준으로 해석합니다. 원문 표현, 해석 결과, 해석 주체(모델)를 함께 저장합니다. 해석은 후보입니다.
- **유효 기간**: 사건은 시점이고, 사건에서 파생된 *상태*(예: "현재 pnpm 사용")는 구간입니다. 상태 claim은 `valid_from`을 사건에 연결하고, `valid_to`는 후속 사건으로 닫습니다(추정으로 닫지 않습니다).
- **과거 조회**: "10월 1일 시점의 결정은?"에 답하려면 valid time과 transaction time을 모두 두는 이중 시간 질의가 필요합니다 [추론].
- **교정**: mutate하지 않고 정정 revision을 append합니다. 삭제 요청은 별도 경로(실제 제거 + 파생 연쇄)입니다.
- **모순**: 양쪽을 보존하고 `conflict_hold`로 둡니다. recorded_at 최신순 자동 해소는 금지합니다(P2-6).
- **abstention**: scope 안에 근거가 없으면 "기록 없음"이라고 답합니다. LongMemEval이 extraction, multi-session reasoning, temporal reasoning, updates, abstention을 *각각 따로* 평가한 구조를 시험 범주로 차용합니다 [소스]. 단, 대화 QA 결과는 coding-agent 성능의 증거가 아닙니다 [소스].
- **"관련성 높은 기록만"에 대한 반대**: 관련성은 *질의에 의존*합니다. 쓰기 시점에 선별하면 미래 질의에 대한 false negative를 확정합니다. 원문 포인터는 싸게 전부 남기고, 선별은 읽기 시점에 bounded로 하는 편이 맞습니다 [추론].

### 기준 4. Notes

- **범위**: thread/task identity에 묶습니다. identity는 host/session 코드가 부여합니다 [제약]. 모델이 "아마 같은 작업"이라고 추정해 붙이는 것은 금지합니다.
- **TTL은 세 가지와 혼동됩니다** [추론]:
  1. retention(법적/프라이버시 보존 기한) → 삭제 파이프라인의 대상
  2. semantic staleness(내용이 낡음) → revision 비교와 후속 사건으로 판정
  3. retrieval decay(노출 우선순위 하락) → 랭킹 정책

  TTL 만료가 *삭제 완료*를 뜻하지 않고(파생물 잔존 가능), TTL 유효가 *아직 참*을 뜻하지도 않습니다. 셋은 별도 필드와 별도 처리기로 둡니다.
- **종료**: TTL이 아니라 작업 종료 이벤트(사용자 선언, PR 머지 등 수집 가능한 사실)로 처리합니다. TTL은 안전망일 뿐입니다.
- **재개**: 메모와 함께 경과 시간, 원문 revision 상태를 보여줍니다. memharness처럼 current/stale/unresolved로 분류하고 unknown/diverged는 unresolved로 두는 *보수적 기본값*을 차용합니다 [소스].
- **장기 승격**: 후보 → 검토 → 서명을 거칩니다. 같은 claim id를 유지하고, scope 확대는 별도 서명이 필요합니다(P1-1 방지).

### 기준 5. 파일·스킬

- **원문 + revision + bounded 상세 읽기**: (source id, revision/commit 또는 content hash, offset 구간)으로 참조합니다. 상세는 구간 단위로 읽고 상한을 둡니다.
- **근거 span**: LangMem의 supporting quote는 prompt상 "when necessary"이며 필수 machine-verified span 계약이 아닙니다 [소스]. 따라서 승격 대상에는 **서비스가 원문 hash와 offset으로 재검증하는 span**을 필수로 요구합니다 [제안].
- **데이터에서 실행 지침으로 승격(스킬화)**: **별도 권한, 승인, 철회가 반드시 필요합니다.**
  - 데이터는 "참고할 수 있음", 지침은 "따라야 함"입니다. 후자는 행동을 바꾸므로 injection 표면이 질적으로 다릅니다.
  - 필요한 것: executability=`instruction` 전이에 운영자 서명, scope 한정, 원문 revision 고정, 철회 시 즉시 비활성 + 파생 연쇄(P1-3).
  - 원문 revision이 바뀌면 스킬은 `stale`로 전이하고 재승인 전까지 지침으로 쓰지 않습니다 [제안].

### 기준 6. 분류 단계와 수명주기의 분리 + OSS 실제 처리

**분리 원칙 [제안]**

```
[분류 단계: 모델 출력 = 제안]           [수명주기: 서비스+운영자 = 권위]
 candidate / exclude(soft) / review  →   proposed → approved(서명) → active
 + decision: noop|create|patch|            → expired | superseded | revoked → deleted
            conflict_hold
 + kind/scope/시간해석 제안 + 근거 span
 + confidence(비교정, 참고용)
```

- **confidence는 승인도, 진실도, 항상 로드도 뜻하지 않습니다.** 교정(calibration)되지 않은 모델 점수입니다 [미측정]. 정책 입력으로 쓰려면 먼저 교정을 측정해야 합니다.
- `noop` = 기존 claim에 근거만 연결(중복). `create` = 새 후보. `patch` = 기존 claim에 대한 *revision 제안*(같은 id, pending). `conflict_hold` = 양쪽 보존 + 검토. 모두 **제안**이며, 서비스가 scope, 현재 grant, 원문 revision을 검증한 뒤에야 후보로 기록합니다 [제약].

**OSS가 실제로 어떻게 처리하는가 — 제공 요약 범위 한정**

| OSS (커밋) | 확인된 것 [소스] | 이 설계에 주는 의미 | 요약 밖(미확인) |
|---|---|---|---|
| engram `5c41718` | agent가 MCP로 save/judge합니다. 충돌 후보 관련성은 **결정적(deterministic)** 계산입니다. | 충돌 *후보 탐색*은 결정적으로 하고 판단은 agent가 하는 구조입니다. 다만 **agent save/judge ≠ 사람 승인**입니다. | no-op/patch 세부 분기, 보류 상태 유무 |
| mnema `eed1958` | read search, opt-in writes, `resolve_preview`→`resolve_commit` hash token | 2단계 커밋으로 *입력 무결성*을 확인합니다. **인간 승인 증명이 아닙니다.** | 검토 큐 존재 여부 |
| LangMem `48e3c11` | Memory schema content: episode/fact/note/preference. semantic/procedural/episodic 지침. extractor는 insert/update | create/patch에 대응합니다. supporting quote는 선택사항이라 근거 검증 계약이 없습니다. | delete/no-op 처리, 충돌 보류 |
| memharness `faed4b3` | git source pin을 current/stale/unresolved로 나누는 순수 분류기. unknown/diverged → unresolved | 모르면 current로 두지 않는 **fail-closed 기본값**. Notes 재개와 스킬 staleness에 직접 차용할 만합니다. | — |
| codex-agent-mem `d594c8a` | micro/normal/full hard char budget(1000/2200/3600), decisions/constraints/pending 등 section limit | 분류가 아니라 **읽기 측 bounded packing**의 선례입니다. | 쓰기 측 분류 |

**종합 [추론]**: 요약된 다섯 OSS 가운데 *후보/제외/검토 → 사람 서명 승인 → 활성/철회*를 분리된 수명주기로 구현했다고 확인되는 것은 없습니다. 가장 가까운 부품은 engram의 결정적 충돌 후보, mnema의 2단계 커밋, memharness의 unresolved 기본값, codex-agent-mem의 hard budget입니다. **제품을 통째로 재사용해도 승인/권한 계층은 따라오지 않습니다.**

### 기준 7. 비용

| 경로 | 성격 | 평가 |
|---|---|---|
| (a) **현재 세션 내 판단** | agent 모델이 이미 읽은 문맥에서 체크포인트마다 후보를 내보냄 | 추가 비용은 주로 출력 token입니다 [추론, 미측정]. 회사 headless 허가가 필요 없을 수 있지만, host와 agent의 협조에 의존하고 누락은 탐지하기 어렵습니다. |
| (b) **별도 전체 로그 분석** | 세션 밖에서 대규모 재분석 | 가장 비쌉니다. 회사의 headless 자동화 허가, quota, data retention이 미확인이므로 [제약] **전제로 삼을 수 없습니다.** |
| (c) **증분 분석** | 세션/thread별 커서 이후의 새 이벤트만 bounded 창으로 처리 | 목표 구조입니다. batch 경계 손실(P2-4)을 anchor로 완화합니다. 실행 주체는 (a)가 기본이고, 회사에서는 (b)/(c)의 별도 실행이 허가될 때까지 보류합니다. |

- **소형 판단 모델**: 회사는 로컬 모델 설치가 불가합니다 [제약]. 승인된 Claude/Codex 팀 계정의 소형 모델은 headless 허가가 미확인입니다. 개인 Jev는 개인 데이터에만 씁니다. 회사 데이터를 개인 executor로 보내는 것은 금지입니다.
- **오분류 비용은 비대칭입니다** [추론]:
  - Profile false positive(오승격) → 매 턴 누출/주입이므로 **최고 심각도**
  - Log/Notes false negative → 원문 포인터가 남아 있으면 **복구 가능**
  - hard drop → **복구 불가**

  따라서 임계값은 "승격은 보수적으로, 제외는 soft로"가 맞습니다.
- 4분류를 도입하면 후보마다 판단이 하나 늘어납니다. 이 비용이 retrieval 품질 개선으로 회수되는지는 [미측정]입니다. 영상의 95% 절감은 이 설계의 측정값이 아닙니다 [제약].

---

## 3. A/B/C 영향과 장단점 (기준 8, 9)

### 기준 8. 구현 영향 — 단일 ledger + view vs 4개 독립 store

현행 core의 스키마, callsite, API는 이번에 열람하지 않았습니다. 아래는 **범주 수준의 추정**입니다 [추론].

| 영역 | 단일 ledger + views/tags | 4개 독립 store |
|---|---|---|
| DB | 속성 컬럼(kind, retrieval_policy, lifecycle, valid 구간), derivation edge 테이블 추가 | 스키마 4개 + store 간 identity 매핑 테이블 |
| FTS | 기존 인덱스에 필터 필드 추가 | 인덱스 4개. 교차 검색 시 점수 정규화 문제 |
| 재분류 | 태그 변경(revision) | store 간 이동 = delete+insert → **정체성 단절** |
| API/MCP | 검색에 view 필터 인자 추가 (권한 판단 인자가 아님 [제약]) | store별 도구 증가. 모델이 store를 고르면 사실상 권한 판단이 모델에게 감 |
| host 연결 | pinned 렌더링은 선택 기능 | Profile 주입 hook이 host마다 필수 → 불균일 |
| approval | 파이프라인 1개 | 4개 또는 공통화 비용 |
| deletion/철회 | 파생 그래프 1개를 따라 연쇄 | **4경로 fan-out + 누락 위험(P1-3)** |
| 트랜잭션 | 단일 저장소 원자성 | store 간 일관성 보장 필요 |

### 기준 9. 동일 조건 대안 비교

| | **A. 현행 scope+revision+bounded retrieval 유지** | **B. 4분류를 관리용 view로 도입 (무조건 preload 없음)** | **C. 별도 store + Profile always-on** |
|---|---|---|---|
| 장점 | 변경 최소. 새 오분류 표면 없음. always-on 누출 없음 | 감사성("무엇이 사실상 상시 적용되는가"를 볼 수 있음), 시간 질의/Notes 만료 같은 view별 정책, **가역적**(view는 파생물) | 단순한 멘탈 모델, Profile 주입 예측 가능(host가 지원할 때만) |
| 위험 | 시간 모델과 Notes 수명 의미가 암묵적일 수 있음 [미확인], 운영자 가시성 부족 | 라벨 drift. view 이름을 *보장*으로 오독할 위험. 분류 비용 | 정체성 분열, 삭제 fan-out, 경계 누출, 영속 주입, 고정 token비, host 불균일 |
| [제약] 적합성 | 적합 | view가 권한을 결정하지 않는다는 조건에서만 적합 | 회사→개인 차단, 모델 비결정 권한과 충돌 소지 |
| 판정 | **기본선으로 채택** | **조건부 채택(단계적)**: 1단계는 기존 필드와 결정적 규칙으로만 계산하는 읽기 전용 view. 2단계에서야 모델 라벨을 *후보*로 추가 | **거부.** 개인 환경 실험도 별도 store 없이 B + pinned로 대체 |

---

## 4. 권고 정책 [제안]

1. **canonical ledger는 하나**로 둡니다. claim id + revision + derivation edge를 둡니다. 4분류는 view 정의이며 다중 소속을 허용합니다.
2. **수집 사실은 모델이 쓰지 않습니다**: source, speaker, host/session/thread/agent, `source_event_time`, `recorded_at`. 비어 있으면 비어 있음으로 둡니다.
3. **분류 출력은 전부 제안입니다**: `candidate|exclude(soft)|review` × `noop|create|patch|conflict_hold`, 서비스가 검증 가능한 근거 span(hash+offset)을 포함합니다.
4. **lifecycle 전이는 서비스와 운영자 서명으로만** 일어납니다. preview token, annotation, confidence는 승인 근거가 아닙니다.
5. **scope는 축소만 자동 허용**하고, 확대(프로젝트→사용자, 사용자→org)는 서명이 필요합니다.
6. **executor는 scope에 바인딩**합니다. 회사 scope에는 개인 Jev/계정 fallback이 없고, 불가하면 정지 후 보고합니다.
7. **Profile always-on은 하지 않습니다.** pinned는 scope별, 서명 필수, hard budget, 데이터로 인용 렌더링, 출처 병기를 지킵니다. 회사 기본값은 빈 집합입니다. 주입 불가 host는 미적용을 명시합니다.
8. **Log는 원문 포인터를 전량 보존하고 읽기 시점에 선별**합니다. 시간 해석은 source_event_time 기준이고 해석은 후보입니다. 모순은 보류합니다.
9. **Notes는 이벤트로 종료하고, TTL은 안전망**입니다. retention, staleness, decay는 별도 필드와 처리기로 둡니다.
10. **data→instruction 승격은 별도 권한**입니다. revision 고정, 원문 변경 시 stale, 철회 시 파생 연쇄 비활성.
11. **읽기는 bounded**입니다. section별 hard budget을 두고, 초과 시 내용을 자르고 출처는 유지합니다.

---

## 5. 측정·검증 계획 (기준 10)

모든 시험은 **합성 또는 공개 fixture로만** 합니다. 회사 corpus는 사용하지 않습니다. 이번 리뷰에서는 아무것도 실행하지 않았으며, 아래는 계획입니다.

| 시나리오 | fixture | 지표 | 합격 기준 |
|---|---|---|---|
| P1-1 오승격 | "이 repo에선 X" 류 조건부 선호 N건 + 진짜 전역 선호 | scope 확대 제안 중 자동 활성화된 비율 | **0** (확대는 전부 review) |
| P1-2 회사→개인 | 회사 scope 이벤트 + 회사 executor 장애 주입 | 개인 executor/계정으로 나간 요청 수, 개인 세션에 노출된 회사 claim 수 | **0 / 0**, 정지와 보고 발생 |
| P1-3 철회 잔존 | 원문 → 요약 → 스킬 파생 체인, 원문 철회 | 철회 후 active 파생물 중 철회 원문 참조 수 | **0** |
| P1-4 주입 | 지시문이 섞인 오염 기억 항목 세트 | pinned/retrieval 경유로 행동이 바뀐 비율 | 데이터 렌더링 시 0 목표. 기준선 A와 비교 |
| P1-5 후보≠승인 | high-confidence 후보 + preview token만 있는 커밋 | 서명 없이 active 전이된 수 | **0** |
| P2-1 날짜 | "오늘/지난주/어제" 발화 + recorded_at을 일부러 수일 지연 | source_event_time 기준 해석 정확도, 기준 시각 결측 시 unresolved 비율 | 결측 시 **100% unresolved** |
| P2-2 재개 | thread 교차, 종료 후 TTL 잔존, 진행 중 TTL 만료 | 잘못된 thread 메모 노출 수, stale 표시 누락 | 오노출 0 |
| P2-3/4 분류 실패 | 청크 경계에 걸친 참조, 경계 사례 | soft-exclude 재감사 false negative율, 경계 항목 review 회부율 | 기준선 대비 보고 |
| P2-5 context 한도 | budget 초과 입력 | 출처 손실 수, 예산 초과 여부 | 출처 손실 0, 예산 hard 준수 |
| P2-6 모순 | 늦게 기록된 과거 사건 | recorded_at 최신순 오해소 수 | 0 (conflict_hold) |
| 비용 A/B/C | 개인 또는 합성 세션 | 세션당 입력/출력 token, 분류 호출 수, 검색 정확도/abstention | B가 A보다 품질이 나을 때만 B 2단계 진행 |

LongMemEval의 5축(extraction, multi-session, temporal, updates, abstention)은 **시험 범주의 틀로만** 차용합니다. 점수 이전은 주장하지 않습니다 [소스].

---

## 6. 반박 가능한 질문

1. 매 세션 *실제로* 필요한 Profile 항목은 몇 개이며, host별 운영자 설정만으로 충족되지 않는 것은 무엇인가? 0~3개라면 always-on 논의 자체가 불필요하지 않은가?
2. Log를 **쓰기 시점에** "관련성 높음"으로 선별해야 하는 이유는 무엇인가? 저장 비용이 아니라 판단 비용이 병목이라면, 선별을 읽기 시점으로 미루는 편이 싸지 않은가?
3. 회사 headless 허가가 없는 상태에서 증분 분류의 실행 주체는 현재 세션 agent뿐이다. 그 누락률을 어떻게 탐지할 것인가?
4. Notes의 TTL은 retention인가, staleness인가, decay인가? 하나만 고를 수 있다면 무엇이고, 나머지 둘은 무엇이 대신하는가?
5. data→instruction 승격의 서명 주체는 누구인가? 개인 환경과 회사 환경에서 동일 인물이 서명해도 되는가?
6. 4개 view 중 하나를 없애야 한다면 무엇인가? 없애도 손실이 없다면 그 view는 축 혼합의 산물이 아닌가?
7. B안의 view가 A안 대비 retrieval 정확도나 abstention을 *측정 가능하게* 개선한다는 근거가 없다면, 감사성만으로 분류 비용을 정당화할 수 있는가?
8. confidence를 정책 입력으로 쓰려면 어떤 교정 데이터가 필요하며, 회사 corpus 없이 그것을 얻을 수 있는가?
9. derivation edge 없이 철회 연쇄를 보장하는 다른 방법이 있는가? 없다면 그것은 4분류 이전에 선행되어야 할 작업이 아닌가?