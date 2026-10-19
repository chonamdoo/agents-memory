# agents-memory 적대적 재리뷰

## 1. 판정

- **최소 coherent 선택: A (조건부)**
  - 구성: 승인된 host 세션이 이미 읽은 구간의 caller-grounded candidate, covered window/cursor, no-ML lexical/entity RRF, model-free 최종 manifest 재검사.
  - 이는 현행 mandatory hybrid/rerank/full semantic 계약의 **명시 예외인 새 제품 계약**이다. "제안 후 진행" 요청을 품질·완료기준 하향 동의로 볼 수는 없다(추론).
  - 따라서 사용자의 예외 채택과, 승인된 base 위의 신규 scope/plan 승인 전에는 코드에 반영하지 않는다.
  - request-changes가 남은 frozen AF successor에 끼워 넣거나 별도 engine으로 우회하는 것도 금지한다.
- **차선: B**
  - A의 선별 executor일 뿐 semantic full 대체가 아니다.
  - 해당 모델 route·egress·저장(daemon이면 자동화)에 대한 회사 승인 증거가 있을 때만 enable한다. 없으면 blocked/unavailable이다.
- **C**: 코어 의무화는 기각한다. 범용 typed-question 소비자가 실제로 생길 때 edge에서만 쓴다.
- **D**: Claude 전용, mod 승인 환경에 한정된 옵션이다. 공통 engine으로는 불가하다.
- **E**: 기각한다. span·승인·cancel·realm 계약이 불일치하고 값 coercion이 있다.
- **4분류**: 1 ledger + 기존 source/kind/task/time 속성 기반 read-only 겹침 view만 채택한다. 복수 store, 전역 always Profile, taxonomy 모델 호출은 기각한다.

## 2. A 자체 반박

- 의미판단 비용은 사라지지 않고 host 세션 토큰으로 이동할 뿐이다(미측정).
- host가 제출하지 않은 구간은 false negative다. coverage를 1급 상태로 두지 않으면 미판단이 제외로 보인다.
- GIN token overlap(tsvector 아님)과 entity만으로는 한국어 패러프레이즈 recall이 떨어질 수 있다(미측정).
- span 존재 ≠ entailment다. caller 요약이나 agent_note를 human 원문 evidence로 승격하면 안 된다.
- 영향 범위가 domain·config·store·jobs·wire·hosts·spool·migration·restore·readiness·docs·tests 전반이다. wrapper ticket으로 축소하면 안 된다.

## 3. 10기준 판정 (○적합 △조건부 ×부적합)

|기준|A|B|C|D|E|4V|
|-|-|-|-|-|-|-|
|①형식·의미·calibration|△validator, 의미=caller, calib 없음|△strict schema, 의미근거 개인 3건|×discrete conf1·rescale≠calib|△검증기 자체 필요|×noul 누락→0, empty→uniform+첫 선택|○추가 호출 없음|
|②ID·rev·span·speaker·entail|○exact UTF8 span·speaker, entail 아님|△A validator 재사용 시|×질문형식에 source/span 없음|△A validator 재사용 시|×span 없음|△포인터만, 본문 절단 금지|
|③판단·저장·규칙승인·오류state|○candidate/discard/review/failed, fact=grant+fence, 규칙=기존 승인|△timeout/partial→failed|△Noul→review 자동매핑 금지|△B와 동일|×direct mutation|○분류≠권한·상시주입|
|④realm·grant·egress·auth|△신규 egress 없음, 회사 저장승인 미확인|△증거 없으면 blocked|×Builtin=API Messages|△mod·session credential 승인 필요|×API key·auto backend|○무관|
|⑤증분 batch·FN|△cursor/window 필수, 미제출=uncovered|△batch 필수, cold per-event 고정비|–B 동일|○complete는 history 미첨부(fork 제외)|×|△Log 날짜·Notes task 경계|
|⑥token·quota·latency|○추가 호출 0|△3건에 cache create 689+read 5640, adapter input4로 cached 누락|×누락 그대로|△maxTokens160, 미측정|×|○taxonomy 호출 없음|
|⑦retrieval·vector·temporal·TTL|△vector=absent 명시|△embedding optional·disabled|–|–|×embedding/local model 의존 다수|△event ts≠valid time, TTL≠삭제|
|⑧deadline·cancel·lease·publish|○모델 없음, publish 재검사|△벽시계 deadline·kill, 모델 중 tx 없음, lease 만료→failed|△retry0, cancel 래핑 필요|△timeout6000, build별 shape pin|×cancel 계약 없음|○|
|⑨영향·유지보수|△크지만 필수|△+executor·config·readiness|×확률 SDK·debug 표면|×host 확장·$.http|×교체|○view만|
|⑩proof·허가·AF gate|△정적 scoping, 미구현|△개인 smoke 1회|△동일 smoke, benchmark 아님|×미실행|×정적 audit|△2모델 의견뿐|

## 4. 4분류 교정 (Opus/Sol 1차 반박)

- **Opus "모든 lifecycle·승격 인간서명" 기각**: optional machine fact는 grant와 publication fence로 처리한다. 기존 operator 승인은 필수/공유 지침 활성화, 권한 확대, 실제 철회에만 필요하다. 이 분리는 Sol이 맞다.
- **Opus "Log 포인터 전량·내용 절단" 기각**: 영구 raw 보존을 신규 default로 두지 않고 retention/purge floor를 지킨다. 절단 대신 span 포인터를 쓰거나 review로 보낸다.
- **시간 구분**: source_event_time(메시지 timestamp) ≠ 본문 사건의 valid time이다. 후자는 모델 후보 필드로 두고, 불명이면 unknown이다.
- **Profile**: 회사 optional Profile auto-pin의 빈 default ≠ 기존 mandatory rule 삭제다.
- **category 역할**: 권한·상시주입·store를 결정하지 않는다. 검색 향상이 측정되기 전에는 별도 호출을 추가하지 않는다.

## 5. OSS 힌트 (정적 source)

- **매핑**
  - patch: Memharness의 exact old ID revise→successor
  - conflict-hold: 우리 review state. Engram·mnema의 relation은 gate가 아니다.
  - no-op/exclude: codex-agent-mem의 비파괴 overlay
- **차용**
  - mnema: 실제 message ID membership, `supports_current_body=false`
  - LangMem: 기존 top memory와 대화를 함께 넣는 동시 추출(batch context)
- **비차용**
  - Engram: not_conflict 영구 저장
  - mnema: partial verdict를 checked로 처리, hash token ≠ 승인
  - Mem0 v1: NONE에서 metadata write
  - LangMem/Mem0: direct mutation

## 6. P1/P2 실패 → 검증

**P1**
1. **누락이 exclude로 소실**(timeout·partial·empty choice·noul 누락·caller 미제출) → 결함 주입 시 failed/unclassified, cursor 미전진, exclude row 0.
2. **회사→개인 fallback** → 회사 route deny + Jev key가 있는 상태에서 egress 0, blocked/unavailable.
3. **철회 중 inflight publish** → 모델 반환 후·publish 전에 retract나 grant 축소 시 최종 manifest 거부, 파생 0. `delivery(admissions=())` 우회 차단 테스트 포함.
4. **중간 scope 확대** → batch에 grant 밖 source나 revision 변경을 주입하면 manifest≠실입력 해시로 거부.
5. **조건/부정 절단**("고객X 제외" 꼬리) → byte budget 초과 fixture에서 항목 통째 제외 또는 review, 절단 문자열 0.
6. **prob debug 원문 복제** → canary로 audit/receipt/outbox/journal/telemetry/TypeSafeError 로그를 grep해 0건.

**P2**
7. **no-vector를 vector처럼 선언** → capability·readiness·context에 lexical_entity/vector=absent, 위조 vector 0.
8. **TTL≠삭제** → Notes 만료는 view 숨김만. purge·철회는 별도로 검증.
9. **conf1·Score rescale을 정확도로 노출** → calibrated=false.
10. **cached usage 누락, list price를 청구액으로 표기** → native cache 필드를 별도 기록.
11. **num_turns 3 관측** → turn cap ≠ request cap. 벽시계 deadline으로 제한.

## 7. 근거 구분

- **사실**: pinned source 정적 audit. 개인 합성 3source native Haiku smoke 1회 성공(약 5.0s, 5질문 검증). 이 smoke에서 debug에 prompt 존재, adapter usage의 cached 누락, maxturns1 실패를 관측했다.
- **제안**: A 채택안, B gating, view 설계, 위 테스트.
- **추론**: 세션 비용 이동, batch 고정비 상각.
- **미측정/미확인**: 품질·recall·calibration, 실청구액, 회사 승인 일체, AF QA/handoff(미완).
- **링크**:
  - [TypeSafe client](https://github.com/typesafe-ai/system-one-adapter-python/blob/e1d4cc938204b22fc5a3c3aca7044072fe3f712d/src/system_one_adapter/_client.py)
  - [mnema distill](https://github.com/Ray0907/mnema/blob/eed19586156ae9664451cb94859f8f3f16b3ac4a/src/distill.ts#L74-L177)
  - [effortless askHaiku](https://github.com/HeyCubit/effortless/blob/e553b18e9f5e8ce3533f3ce9c666e7e8bc9234f9/hooks/register.tsx#L762-L809)
  - [Jevbridge](https://github.com/tacticocc/Jevbridge/blob/d4e8f7d483b8a5649218970eedbaf4f4a1e1e832/src/llm-adapter.ts)

## 8. 다음 결정 (승인 선언 아님)

1. lexical capability 예외 채택 여부
2. 승인 base 선정과 신규 scope/plan 승인
3. B enable을 위한 회사 승인 증거

1·2 결정 전에는 구현에 착수하지 않는다.