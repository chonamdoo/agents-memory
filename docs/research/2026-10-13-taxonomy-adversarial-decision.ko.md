# Profile·Log·Notes·파일/스킬: 별도 적대적 리뷰와 채택 경계

## 결론

**하나의 canonical ledger 위에 겹칠 수 있는 관리용 view를 두는 방향을 채택 후보로 정한다. 네 개의 독립 저장소, 모델이 자동 선정한 Profile의 무조건 상시 주입은 기각한다.** 유용성 판정, 저장 변경, 원문/근거, 실행 지침의 권위, 읽기 노출은 서로 다른 축이다. 이번 결과는 설계 리뷰이며 네 view 구현/회사 운영/기존 AF 승인 완료가 아니다.

| 영역 | 필요한 의미 | 위험 | 제안된 관리 방식 |
|---|---|---|---|
| Profile | 현재 subject·realm에서 재사용할 핵심 사실/선호 | 프로젝트 예외를 전역 선호로 승격; 상시 비용·민감 노출; 데이터가 instruction으로 오독 | 기본은 관련성 기반 조회. 상시 pin이 실제 필요한 경우에만 명시 scope·원문·revision·짧은 예산·해제 조건. 기존 승인 mandatory rules는 별도 경로로 유지 |
| Log | 관측 사건/교정과 그 근거·시각 | 메시지 시각=사건 발생 시각=사실의 유효 기간이라고 오독; 늦은 기록을 최신 정답으로 덮어쓰기 | source message event_time, recorded_at, 서술된 occurrence/validity 해석을 구분. 보존은 authorized retention에 한정. 늦은 사건·교정·조건별 주장은 identity/revision/관계로 관리 |
| Notes | 특정 task/session의 단기 작업 맥락 | TTL 만료가 삭제·진실 부정·다른 task에 재사용되는 것으로 혼동 | task/binding 범위와 종료 사건, freshness/TTL을 구분. 재개 시 source revision·권한·상태 재검사. 오래된 note는 명시적으로 stale/미적용 |
| 파일 | 큰 상세 자료와 원문 reference | 요약 복제·검색 hit의 무단 export/수정·출처 변경 뒤 stale 요약 | 필요할 때 bounded read/search, pointer+hash/revision과 lineage. 검색 결과가 파일 변경 권한을 만들지 않음 |
| 스킬/규칙 | 실행 가능한 절차/필수 instruction | 반복·confidence·후보 label에서 자동 권위 부여 | data와 분리. 활성화할 exact revision/selector/target set에 기존 approval 계약 적용. 원문/규칙 철회 후 관리하는 파생 제공 경로 차단 |

Profile·Log·Notes는 내용/시간/수명 축이고 파일/스킬은 매체/권위 축이다. 하나의 preference가 Profile과 Log에 보이는 것은 가능하지만 원문과 claim을 복제하지 않는다. view 소속은 접근권한이나 rule approval를 늘리지 않는다. 제외 결정은 원문 purge 또는 이전 기억 철회가 아니다.

## 실제 별도 native 리뷰 증거

같은 공개 packet과 독립 반대검토 지시를 두 native CLI에 전달했다. stdin 6,834 bytes, SHA256 **9be1d5878a109ac49a228141bc93ce1402245c3a8ae8e8eff86094ca36002d56**가 일치한다. private source/corpus나 회사 인증은 입력하지 않았다.

| 실행 | 관측 및 한계 | 결과 |
|---|---|---|
| Claude CLI 2.1.296 | claude-opus-5-5 / xhigh 요청; CLI modelUsage의 claude-opus-5-5 관측. 서버 독립 attestation·회사 permission는 아님. exit0, is_error=false | 기존 A를 기준선, 1ledger+readonly views B를 조건부 채택, 4store+alwaysProfile C 기각 |
| Codex CLI 0.162.1 최종 실행 | gpt-6.1-sol / xhigh 요청. JSONL served model 미보고. exit0. web/apps/collab/command/file-change 0; builtin resource listing 2회, resources/templates 모두 [] | B 조건부 추천. always-on 순이익·회사 준비는 입증 안 됨 |

Codex 최초 실행은 옵션만으로 격리를 가정한 결과 web/apps 호출이 관측되어 최종 리뷰로 사용하지 않았다. 수정된 두 번째 호출의 native 최종 리뷰를 사용했다. 잔여 builtin listing이 있어 **tools=0 또는 회사 production sandbox 합격이라고 표시하지 않는다.** 원시 provider reasoning/JSONL은 공개하지 않는다. native 원문은 각 Opus/Sol 보고서, body-free metadata는 taxonomy-native-proof JSON에 보존한다.

## 모델 권고를 그대로 받지 않은 부분

1. **Opus의 모든 lifecycle·fact 승격에 human 서명 요구는 기각.** 승인된 모델과 인간 승인은 다른 문제다. optional fact의 machine processing는 기존 authenticated grants와 publication fence로 처리한다. 필수/공유 instruction·권한 확대·실제 철회에는 기존 operator/approval 계약을 유지한다.
2. **Log source pointers 전량 영구 보존은 기각.** 비용/감사 이점이 있어도 개인정보·고객 retention·삭제 계약을 넘어설 수 없다. 계약상 보존 범위 안에서 source pointer와 derivation을 유지한다.
3. **event_time의 혼동은 교정.** host가 관측한 메시지 시각은 본문에 서술된 사건의 시각을 자동 증명하지 않는다. 누락 timestamp를 recorded_at로 보충해 factual validity를 만들어내지 않는다.
4. **budget 초과 내용을 자르되 출처 유지한다는 규칙은 기각.** 부정·조건·예외를 절단하면 반대 의미가 된다. 의미상 필요한 전체 단위를 담지 못하면 통째로 omission/보류와 재조회 pointer로 표시한다.
5. **회사 Profile 빈 기본값은 기존 approved rules 삭제가 아니다.** 신규 자동 Profile pin을 만들지 않는 선택과 이미 승인된 필수 지침의 전달은 분리한다.

## 비용과 영향

4분류 view 때문에 새 taxonomy 모델 호출을 매 source마다 추가하지 않는다. 기존 subject/scope/source/task/time/provenance 필드로 readonly view부터 검토한다. 새 분류가 필요하면 유용성 판단의 기존 bounded batch와 결합하고 source coverage를 기록한다. accuracy/false-negative·발견된 기억의 실제 다음 task 유용성·상시 token 비용·운영자 검토 비용을 같은 workload로 비교해야 한다. 이번 native 리뷰의 실행 비용이나 LongMemEval를 제품 효과 수치로 재사용하지 않는다.

실제 확장 시 core authority·source/claim lineage는 유지한다. 조회/view definition, inspect/CLI/host 표시, 수명/temporal metadata, pin 계약, purge/restore, docs와 소비자 행태 회귀가 영향 범위다. 별도 store·새 queue·skill compiler를 부수적으로 도입하지 않는다. TypeSafe/native executor와 회사 lexical capability의 최종 결합 여부는 별도 통합 재리뷰에서 결정한다.

## 소비자 관측 기준 — 계획, 미실행

- 프로젝트 한국어 선호+회사/고객 예외가 전역 Profile로 바뀌지 않는다.
- Log의 사후 기록/교정이 occurrence/validity를 덮어쓰지 않는다.
- Notes 만료/다른 task 재개/권한 변경에서 부적합 메모를 노출하지 않는다.
- source 철회 후 claim·요약·승인된 skill·index·cache·managed host pack을 통한 다음 제공이 차단된다. 이미 통제 밖에 복제된 내용은 별도 한계다.
- timeout/부분 batch/잘못된 schema는 제외가 아니다. 동일 source 누락과 미검토 구간을 표시한다.
- 높은 confidence/preview hash/MCP 호출만으로 필수 규칙 활성화가 되지 않는다.
- 같은 전체 context 예산에서 view 사용의 품질·비용·민감 노출을 기준선과 비교한다.

원문 근거가 없는 view 자체를 제품 완료로 표시하지 않는다.
