# Opus 2차: Sol 1차 제안의 채택·반박·수정 (동일 잣대)

> **범위**
> - 사용한 자료는 제공된 frozen 근거, 통합 정정, 두 1차 보고서뿐이다.
> - 도구·파일·네트워크는 쓰지 않았다. 새 성능 실험, host 실행, 소스 확인도 하지 않았다.
> - G1–G8은 source-audit에서 관찰한 결과다. 규모별로 실패를 재현한 실험이 아니다.
> - 최종 결정은 parent/user가 한다.

---

## 1. 결론

**기존 코어에는 신규 기능 변경을 하지 않는다.**

**지금(now)**
- A를 유지한다.
- **trial 절차 재사용 지침**을 운영 문서로 둔다. 코드 변경은 없다.
- 경로는 기존 그대로다. MemoryWrite `procedure` 종류로 기록하고, 기존 `rule_candidate`를 거쳐, exact revision 승인 경로로 승인한다.

**별도 트랙: 기존 계약 결함 3건**
- 대상은 중복 purpose config 손상, event_time downstream 누락, strict denial budget 초과다.
- 이 3건은 결함 수정으로만 처리한다. B/C/D 기능 승인의 근거로 쓰지 않는다.
- 다만 O3·O5의 선행조건으로 묶는다(3절).

**after-trial (1–2주 로컬 trial 이후, 아직 미실시)**
- B 단계는 O3 → O4 → O5 → (O8, O6) → O7 순서로 진행한다.
- C는 O5 이후 shadow 모드로만 연구한다.
- D는 맨 마지막이다. 외부 게이트를 충족할 때만 재심한다.

**거절(decline)**
- 자동 승격, 조직 broadcast, 회사 gateway·회사 cloud
- 연결 catalog·대형 catalog, root full-body
- 5번째 대형 tool, 신규 procedure kind
- protocol 선행 rewrite, BAML/Jev 의존

| 안 | now | after-trial | decline |
|---|---|---|---|
| **A** 현 서비스 유지 | 채택. 유일한 권위 경로 | 유지 | — |
| **B** feedback·procedure 개선 | 지침만, 코드 없음 | O3→O4→O5→O8/O6→O7을 단계별로 채택 후보화 | 무인 distill, 자동 승격, 신규 kind |
| **C** 코드 변경 재검토 | 없음 | O5 이후 shadow stamp 연구 | stamp로 required를 제거하거나 UNKNOWN으로 자동 전환 |
| **D** Skills projection | 없음 | 외부 게이트 충족과 O3/O4 결과 확인 후 재심. 부족하면 decline 유지 | full catalog, required 투영, host 지원 선언 |

**Sol과 수렴한 점**
- A 유지, D 보류, E 기각
- required 불명확 시 실행 보류(fail-closed)
- rollback 시 현재 eligibility 재확인

**남은 주요 차이**
- C의 시점과 강도
- B 코드 착수 시점: Sol은 now 조건부, 이 2차는 after-trial

---

## 2. Sol 1차 제안 판정

| Sol 제안 (인용·식별) | 판정 | 근거 | 영향·이득 | 위험 | 검증 조건 |
|---|---|---|---|---|---|
| "우선순위 B → C → D" | **수정 채택** | C를 D보다 앞에 두는 순서는 채택한다. Opus 1차의 "D 설계 문서 2순위"는 철회한다. 단 B는 지금 지침만 두고 코드는 trial 이후에 착수한다. C는 O5 이후로 미룬다 | D는 활성화를 증명한 host가 없어 이득이 0에 가깝다. C는 내부에서 측정할 수 있다 | fail-closed 계약 아래에서는 C의 오탐이 그대로 작업 차단이 된다 | C의 FP/FN을 outcome(O5)과 대조해 측정 |
| "B 조건부 채택… 기존 reflect와의 실제 차이, 허용된 모델 경로, 평가 기준을 먼저 확정" | **채택하되 전제 정정** | `procedure` kind는 이미 있다. 그래서 B의 실제 차분은 distiller, 제한된 feedback 소비, outcome 연결뿐이다. 모델 경로는 로컬 Qwen3.5-9B와 로컬 embedding/rerank가 실제로 실행된 근거가 있다. 다만 증류 품질의 근거는 없다 | 새 저장소나 새 kind 없이 범위가 좁아진다 | "로컬 runtime이 있다"가 "증류 품질이 있다"로 확대 해석될 수 있다 | O7의 holdout 평가 |
| "C 좁은 범위 조건부 채택. 관찰 가능한 dependency와 `UNKNOWN` 처리를 먼저 정의" | **반박·수정** | required applicability UNKNOWN은 이미 protected action에서 fail-closed로 고정돼 있다. 새로 정의할 대상이 아니다. C는 applicability 상태를 바꾸지 않는 shadow 단계부터 시작한다 | 기존 계약을 흔들지 않는다 | C 신호를 UNKNOWN에 직접 연결하면 오탐률이 곧 차단률이 된다 | shadow 단계에서 applicability 상태 변경 0건 |
| "적용 범위나 권한 freshness가 불명확하면… 관련 실행을 보류. host gate가 없으면 strict 선언 불가" | **채택** | 통합 정정과 일치한다. Opus 1차의 "required는 계속 전달하고 UNKNOWN 표시·경고만" 표현을 이것으로 대체한다 | fail-open이 제거된다 | advisory host는 모델 행동을 강제하지 못한다(OMP strict 설치 거부 판정 유지) | 기존 fail-closed 테스트 무회귀 |
| "후보를 변경된 코드나 더 넓은 프로젝트에 적용하는 근거로 쓰려면 C가 드러내는 불확실성을 해결" | **부분 반박** | 더 넓은 프로젝트로 적용하는 문제는 scope ②/③의 재동의 문제다. C가 해결할 수 없다. C는 범위를 확장할 권한의 근거가 아니다 | scope 계약이 보존된다 | C를 범위 확장의 구실로 쓰게 될 수 있다 | 새 프로젝트 재동의 경로를 우회하는 경로 0 |
| "rollback도 현재 eligibility를 다시 확인. 과거 bytes로 돌아가도 과거 권한이 되살아나지 않음" | **채택·확장** | Opus 1차의 D rollback("이전 immutable revision을 가리키는 새 list 게시")에는 재확인이 빠져 있었다. 이를 백업 복구까지 확장한다 | 복구 시 삭제된 내용이 부활하는 것을 막는다 | 복구 절차가 복잡해진다 | 복구 후 deletion tombstone 재적용, 삭제 부활 0 |
| "immutable content는 현재 권한·audience를 고정하지 않음. TTL만으로 revocation 대체 불가" | **채택** | ext-skills 167da6c와 frozen 판정에 근거 | D의 한계를 정확히 표시한다 | — | — |
| "36%→100%… 같은 Sonnet 4.6… 재현에 가깝다" | **결론 채택, 전제 정정** | 전후가 같은 모델·같은 harness였는지는 자막만으로 검증할 수 없다. 이 사례는 성공 run에서 증류한 것이고, failure-run 증류의 성과가 아니다. jDdgfTp_PXw와 u-o0sW9nwmk는 같은 발화의 재업로드이므로 독립 근거 2건이 아니다 | 근거의 중복 계산을 막는다 | — | — |
| "'승인 없이 배포했지만 성공했다' trace에서 승인 생략을 학습하면 안 됨" / "같은 오염 원본의 유사 run은 독립 증거가 아님" | **채택·구체화** | O7 acceptance로 옮긴다. 독립성은 root_run(G3) 집계를 기준으로 계산한다. required를 우회하거나 UNKNOWN 상태에서 진행된 trace는 격리한다 | 오염된 증거의 증폭을 막는다 | root_run 집계가 없으면 독립성을 계산할 수 없다 | 같은 root_run에서 나온 다중 origin을 1건으로 계산 |
| "file이 안 바뀌어도 runtime 설정·외부 API·flag·권한이 바뀌면 절차가 달라질 수 있음" | **채택** | C 신호가 없다고 해서 fresh라는 증명은 아니다 | C의 과대 주장을 막는다 | — | "변경 없음 = fresh"로 추론하는 코드·문서 0 |
| "D… 지원 host에서 필요한 내용만 가져오는 경로를 시험 가능" | **반박** | 이 이득은 native activation이 증명된 host에서만 생긴다. 현재 그런 host는 0개다. 같은 on-demand 이득은 O3(stub+paged inspect)로 기존 경로에서 얻을 수 있다 | 이중 경로를 회피한다 | context tool과 host cache가 서로 다른 revision을 전달할 수 있다 | D 재심 시 두 경로의 revision 일치 |
| "PR #3485 merge는 설치된 `mcp==2.3.0` Skills의 증거가 아님. handler·schema 지원은 host consent를 대신하지 못함" | **결론 채택, 사실 정정** | 병합된 소스는 client 모듈 `mcp/client/extensions/skills.py`(`SkillsClient`)다. 서버 측 projection 지원 여부는 이 근거로 확인되지 않는다. 기본 MCP2 서버 동작(증명됨)과 Skills extension(미검증)을 분리한다 | released / source / native 구분이 정확해진다 | "SDK가 해준다"는 가정 아래 D의 구현 부담이 과소평가될 수 있다 | 릴리스 버전 pin 후 기능 확인, host별 관찰 |
| "다음 결정 대상: B의 실제 차이와 최소 후보 생성·feedback 소비 범위" | **수정** | 다음 결정 대상은 trial 지침 문안과 사전에 고정한 acceptance다. feedback 소비 범위는 O7과 함께 정한다 | 측정 전에 기능부터 만드는 것을 막는다 | 개선이 지연된다 | 4절의 trial acceptance |

### 2-b. Opus 1차 자기 정정

| Opus 1차 | 정정 |
|---|---|
| "기존 typed extract에 새 kind 추가" | **철회.** `procedure` kind는 이미 있다. `rule_candidate`와 exact revision 승인 경로를 재사용한다. |
| "B1(feedback 소비자) 즉시, 1순위" | **after-trial로 이동**해 O7과 함께 다룬다. 지금은 "feedback은 기록일 뿐 소비·결과·권한이 아니다"를 지침에 명시하는 데서 그친다. |
| C: "required는 계속 전달하고 UNKNOWN 표시만" / 불변식 2: "경고를 붙인다" | **철회.** required applicability UNKNOWN은 protected action에서 fail-closed로 유지한다. C shadow는 applicability 상태를 바꾸지 않는다. |
| 불변식 3: "원천 삭제 시 승인 규칙의 존속 여부는 미해결 정책" | **정정.** deletion closure가 우선한다. 삭제된 원천의 본문을 계속 제공하지 않는다. 그로 인해 생기는 required 공백은 세 가지로 다룬다. ① 기존 fail-closed ② 승인자에게 명시적으로 통지 ③ 삭제되지 않은 원천으로 새 revision을 만들어 재승인. 현재 정확한 동작은 이 리뷰에서 확인하지 않았다. |
| "로컬 extractor 가용성 미확인" | **정정.** Qwen3.5-9B와 로컬 embedding/rerank의 실제 실행, native3 소비, 747 tests 0 skips의 근거가 있다. 증류 품질, 장기 trial, Skills activation의 근거는 없다. |
| "PR 3485 = handler adapter+schema" | **정정.** client 측 `SkillsClient`다. 서버 측 지원은 확인되지 않았다. |
| 영상: "각자 고유한 timeline" | **정정.** 같은 발화의 재업로드다. 시각은 ID별로 표기하되, 길이 차이로 오프셋이 있을 수 있다. mAKUL12h1n8은 별개의 영상이다. |
| 순서: "B1 → D 설계 → B2 → D 시험 → C" | **철회.** 3절의 순서로 대체한다. |
| **유지하는 고유 제안** | 아래 네 가지는 유지한다. ① 거절된 body 원문 대신 사유만 입력하고, 재제안은 결정적 digest 비교로 차단한다. ② C stamp는 binding digest 밖의 별도 관측 레코드로 둔다. 대량 재승인을 막기 위해서다. ③ D의 첫 시험은 scope ①, approved, optional만 대상으로 하고 required는 제외한다. ④ 독립 origin 하한을 둔다. |

---

## 3. A–D 동일 잣대 비교와 선행관계

| 기준 | A 유지 | B feedback·procedure | C 코드 변경 재검토 | D Skills projection |
|---|---|---|---|---|
| **동작 정확성·호출 일관성** | selector와 exception은 결정적으로 평가된다. 다만 G4와 G5 때문에 **승인됐는데 도달할 수 없는 optional**이 생길 수 있다. G4: overflow가 ref 없이 omitted되고, inspect가 4096B 초과 본문을 반환하지 않는다. G5: optional을 id순으로 고르고, 빈 selector는 TRUE로 평가된다 | O3는 도달성을, O4는 순서를 개선한다. 둘 다 적용성의 의미는 바꾸지 않는다. distiller의 출력은 candidate뿐이다. 운이 좋았던 결과나 일회성 해법을 일반화하는 위험은 O5 없이는 판별할 수 없다 | path/hash는 의미 변화를 잡지 못하고 rename은 오탐을 낸다. 신호가 없어도 fresh는 아니다 | host 모델이 description만 보고 활성화를 판단하므로 selector/exception이 손실된다. context tool과 경로가 이중화되면 revision이 불일치할 수 있다 |
| **보안·회사 무반출·개인 격리** | 서버는 외부를 호출하지 않는다. 팀 모델 경로 승인은 별개 정책이며 zero-egress의 증명이 아니다 | trace에는 tool output을 통한 간접 injection과 secret이 쌓일 수 있다. 그래서 개인 realm, opt-in, 로컬 route로만 한정한다. O8은 라벨일 뿐 승인이나 권한이 아니다 | 외부로 이동하는 데이터는 없다. 주된 위험은 fail-closed 과잉 차단으로 인한 가용성 저하다 | host cache는 삭제·realm 경계 밖에 있다. cross-origin consent는 확인되지 않았다 |
| **컨텍스트 예산·lazy read** | startup body는 0이다. 이것이 catalog metadata나 harness token이 0이라는 뜻은 아니다. 749/3922/282B는 fixture 관찰값이다 | O3 stub은 omitted 대신 바이트를 소폭 늘린다. inspect 파라미터를 추가하면 catalog를 재측정해야 한다. O4 rerank는 지연을 늘린다 | context에 주입하지 않는다(shadow) | discovery 바이트를 host별로 측정하지 않았다. eager host에서는 lazy read가 깨진다 |
| **exact approval·3 scope·삭제 closure** | 현 계약 | candidate만 만든다. required, authority, targetset은 승인자만 정한다. 기존 rule의 변경은 새 revision candidate로 제출한다. lineage, lease, deletion admission이 적용된다 | stamp는 binding digest 밖에 둔다. 무효화는 승인자만 할 수 있다 | approved, scope ①만 대상이다. 철회는 best-effort이며, 의미는 "삭제됨"이 아니라 "더 이상 제공하지 않음"이다 |
| **released SDK / source / native** | 설치된 2.3.0에서 기본 MCP2 서버 동작과 native3 소비가 증명됐다 | 신규 SDK 의존이 없다 | 신규 SDK 의존이 없다 | 병합 소스, 설치 버전, host native 활성화가 전부 미증명이다 |
| **운영·백업/복구** | 기존 PG | trace와 outcome이 늘어나 백업의 민감도가 올라간다. 복구 시 tombstone을 재적용해야 한다. 승인 큐에 상한이 필요하다 | stamp는 다시 계산할 수 있는 파생물이다 | 복구나 rollback 시 eligibility를 재확인한 뒤 재게시해야 한다. host 호환표를 운영해야 한다 |
| **비용·지연·검증 게이트** | 없음 | 로컬 9B를 핫패스 밖에서 비동기로 돌린다. rerank p95와 승인자 시간이 비용이다 | 저장소 크기에 비례한다. 이력 replay로 검증한다 | SDK 릴리스 pin과 host별 activation·consent 관찰이 게이트다 |
| **판정** | now 채택 | now는 지침만. 코드는 after-trial | after-trial shadow | 외부 게이트 전에는 decline |

### 선행관계 결정

| 단계 | 해결하는 gap | 선행조건 | 이 위치인 이유 | 경계 |
|---|---|---|---|---|
| **now: trial 지침** | G4/G5의 실제 빈도 관찰 | A. 결함 트랙은 병행 | 코드 없이 우선순위의 근거를 확보한다 | 신규 kind나 tool 없음 |
| **O3** stub + paged inspect | G4 긴 규칙 전달 | trial 관찰, strict denial budget 결함 수정 | 승인됐는데 도달할 수 없는 것은 정확성 결함이다. 그래서 관련성 선택보다 먼저다 | 기존 inspect를 확장한다(5번째 tool 없음). 같은 revision digest 안에서만 paging한다. 도중에 revision이 바뀌면 재시작하고 섞지 않는다. 삭제 후에는 page 요청이 거부된다. **required 본문의 stub화는 별도 결정** |
| **O4** 관련성 선택 | G5 | O3 | stub이 있어야 선택에서 빠진 optional도 도달할 수 있다 | 순서는 eligibility(auth/realm/scope/삭제), applicability, required 전부, optional 순위 매기기다. selector 의미는 바꾸지 않는다(빈 selector=TRUE 유지, 순서만 조정). tie-break는 결정적으로 한다. rerank가 실패하면 현재의 id순으로 돌아간다 |
| **O5** verified outcome | G1/G8 | event_time 결함 수정, O3/O4(무엇이 제공됐는지 확정) | 성공·실패 라벨이 없으면 feedback 소비, 증류, C 평가 모두 근거가 없다 | feedback과는 별도 레코드로 둔다. 결정적 oracle만 verified로 인정하고, 모델의 자기 판정은 unverified로 둔다 |
| **O8** advisory scan | G6 | 늦어도 O7보다 먼저 | 자동 candidate가 승인 화면에 오기 전에 라벨이 있어야 한다 | 라벨은 승인이나 권한이 아니다. 수동 candidate에도 적용한다 |
| **O6** 개인 opt-in trace | G2/G3 | O5 | trace의 가치는 outcome과 연결될 때 생긴다. root_run 집계가 독립성 계산의 기반이다 | 개인 realm, 프로젝트별 opt-in, 보존 상한, 삭제 closure. **회사 realm trace는 범위 밖** |
| **O7** distiller + bounded feedback 소비 | B 본체 | O5, O6, O8 | 라벨, 원천, 스캔이 모두 갖춰진 뒤에야 의미가 있다 | 출력은 `procedure` kind의 `rule_candidate`다. 로컬 route만 쓴다. 입력에는 사유만 넣고 재제안은 결정적으로 차단한다. durable과 instance를 구분한다. 독립 origin 하한을 적용한다 |
| **C** shadow stamp | G7 | O5 | FP/FN을 평가하려면 outcome이 필요하다 | applicability 상태 변경 0건. 신호가 없어도 fresh로 간주하지 않는다 |
| **D** | — | O3/O4 결과, 릴리스된 SDK, host별 activation·consent 증거 | A 경로가 부족하다는 것이 입증될 때만 이득이 있다 | approved, scope ①, optional, 단일 SKILL.md |

---

## 4. 지금 코드로 추가하지 않을 범위와 acceptance

### 지금 추가하지 않음

- O3–O8, C, D의 모든 코드
- feedback 소비자
- 신규 procedure kind, 5번째 tool, Skills 엔드포인트, 미릴리스 SDK git pin
- 회사 realm trace 수집, 회사 cloud, 개인 cloud(trial 이후 별도 판단)
- required UNKNOWN 처리의 변경, deletion closure의 완화
- 결함 3건의 수정은 위 목록과 별개로 허용한다. 단 B/C/D 승인으로 간주하지 않는다.

### trial 지침의 핵심 문안 (제안)

- **기록 대상:** 반복될 다단계 작업을 실제로 해결했을 때 기존 `procedure`로 기록한다.
  - 검증 근거(테스트 통과, 사용자 확인)를 함께 적는다. 근거가 없으면 unverified라고 명시한다.
- **scope:** 3개 중 하나를 명시한다. 기본값은 ①이다.
- **기록하지 않을 내용:** secret, PII, 회사 식별 정보는 제거한다.
- **길이:** 본문은 현재 inspect 한도(UTF-8 4096B) 안에서 작성한다.
  - 한도를 넘으면 **분할하지 않는다.** 분할하면 G5 때문에 일부만 전달될 위험이 있다.
  - 대신 승인을 보류하고 관찰 건으로 기록한다.
  - required로 지정할 것은 승인 전에 envelope 한도 안에 드는지 확인한다.
- **feedback의 위상:** feedback은 기록일 뿐이다. 감사 범위 안에서 확인한 바로는 후속 생성에 소비되지 않는다. outcome의 증거도, 권한의 근거도 아니다.
- **금지:**
  - candidate를 approved처럼 사용
  - 거절된 내용을 같은 형태로 재제출
  - 회사 corpus를 외부 model, telemetry, gateway, 개인 cloud로 반출
- **trial 적용 realm:** user가 지정한다. 회사 realm에서 팀 승인 모델 경로를 쓰는 것이 허용되는지는 별도 정책이다.

### trial acceptance (trial 전에 user가 임계값을 고정해야 함, 미실시)

1. candidate 수, 승인·거절 수와 사유, 1건당 승인 시간
2. 승인 대상 중 envelope 초과, omitted, 4096B 초과 건수 → O3 착수 판단 근거
3. 관련 optional이 id순 때문에 누락된 관찰 건수 → O4 착수 판단 근거
4. 승인된 procedure가 이후에 제공되거나 inspect된 사례. 이는 소비나 준수의 증명이 아니다.
5. required UNKNOWN으로 인한 차단 건수와, 각 차단이 정당했는지에 대한 수동 판정
6. 회사 realm에서 서버의 외부 호출 0건을 deny-egress 로그로 관찰. 이는 전체 zero-egress의 증명이 아니다.
7. 삭제 drill: 원천을 삭제한 뒤 파생 candidate와 body에 closure가 적용되는지 확인
8. 결함 3건의 재발 여부

### after-trial 단계별 acceptance (전부 미실시)

| 단계 | acceptance |
|---|---|
| O3 | 같은 revision 안에서 paging 결과가 일관된다. 도중에 revision이 바뀌어도 섞이지 않는다. 삭제 후 접근이 거부된다. catalog/discovery를 재측정한다. 기존 테스트가 무회귀한다 |
| O4 | holdout을 분리한 synthetic fixture에서 id순 대비 관련 optional 포함률을 비교한다. 같은 입력에서 같은 출력이 나온다. **required 누락 0건.** p95 지연이 상한 안에 든다. rerank 장애 시 fallback이 동작한다 |
| O5 | verified와 unverified가 구분된다. provision과 outcome이 올바르게 연결된다. event_time이 일관된다 |
| O8 | injection이나 secret을 심은 synthetic 입력으로 탐지율을 보고한다(advisory). 스캔 통과가 승인 상태를 바꾸지 않는다 |
| O6 | opt-in이 없으면 수집 0건. 보존 기간 만료가 동작한다. 삭제가 파생물까지 전파된다. 회사 realm 수집 0건 |
| O7 | source run과 eval set이 겹치지 않는다(∩=∅). root_run 기준으로 독립성을 계산한다. 같은 digest의 재제안 0건. required, authority, targetset을 설정하지 않는다. required를 우회한 trace는 격리한다 |
| C | 저장소 이력을 replay해 FP/FN을 측정하고 O5 outcome과의 상관을 본다. applicability 상태 변경 0건 |
| D | host별 discovery 바이트를 측정한다. activation과 consent를 관찰한다. 철회 후 잔존 여부를 확인한다. rollback 시 eligibility를 재확인한다. context tool과 revision이 일치한다 |
| 운영 공통 | 백업 복구 후 삭제된 내용의 부활 0건. 승인 큐 상한이 유지된다 |

---

## 5. 남은 의견 차이와 불확실성

| 쟁점 | Opus 2차 | Sol 1차 | 상태 |
|---|---|---|---|
| C의 시점 | O5 이후 shadow만 | B 다음에 좁은 범위로 조건부 채택 | **남은 차이.** Sol 쪽 반론은 이력 replay만으로도 FP를 측정할 수 있다는 것이다. 이 반론은 일부 타당하다. 다만 replay가 주는 것은 플래그 발생 비율이고, 실제로 stale이었는지는 outcome이나 사람의 판정이 있어야 알 수 있다. user가 결정한다 |
| C 신호가 required UNKNOWN을 유발해도 되는가 | 미결정. 오적용과 누락 사이의 비대칭 판단이 필요하다 | 언급 없음 | user가 결정한다 |
| B 코드 착수 시점 | after-trial | now 조건부 | 통합 정정("trial 절차 재사용 지침부터")에 따라 after-trial로 수렴하는 것이 타당하다 |
| O3에서 required 본문을 stub·paging할 수 있는가 | 별도 결정 | — | 미결정 |
| O4에 로컬 rerank(비결정성 위험)를 쓸지, 결정적 lexical을 쓸지 | 결정적 tie-break와 fallback을 조건으로 함 | — | 미결정 |

**미확인 (새로 확인하지 않았음)**

- **기존 시스템 동작**
  - 원천을 삭제했을 때 required 공백이 현재 어떻게 드러나는가
  - 결함 3건이 O3/O5에 미치는 영향. 3절의 연결은 결함 이름에 근거한 추정이다.
  - feedback 소비자가 감사 범위 밖에서도 정말 없는가
  - 기존 reflect/procedure 경로가 B의 생성 부분을 이미 얼마나 덮는가
- **SDK와 host**
  - 설치된 2.3.0의 Skills 기능, PR3485의 서버 측 지원, 릴리스 시점
  - Claude Code 2.1.296, Codex CLI 0.162.1, OMP 18.10.1의 native activation과 consent
- **영상**
  - 재업로드 간 시각 오프셋, 발표일, 자동자막의 정확성
  - 36→100 사례의 n, oracle, holdout, 전후 동일 조건 여부
- **모델·trial**
  - 로컬 9B의 증류 품질
  - 1–2주 trial과 cloud는 **미실시**다.

최종 채택은 parent/user가 결정한다.