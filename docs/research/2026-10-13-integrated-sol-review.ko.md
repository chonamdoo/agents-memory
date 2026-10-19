최소 일관 선택은 **B: A의 전체 계약 + 승인된 native 모델의 bounded batch 선별기**다. 차선은 **A만 도입**하는 것이다. 공식 TypeSafe Adapter(C)는 실제 typed-question 소비자가 필요할 때만 선택한다. D는 Claude 전용 최적화 후보, E는 기각한다.

이 선택은 **caller-grounded lexical capability**라는 제한 기능 제안이다. 기존 mandatory hybrid/rerank/full-semantic 계약의 예외를 명시적으로 채택하기 전에는 구현에 넣으면 안 된다. 현재 AF fresh12의 5개 `Request Changes`와 QA 미완료도 그대로다.

**자료 사실과 권고의 구분**

공개 packet의 source facts를 기준으로 보면, 그대로 가져올 완성품은 없다.

- Engram은 observation 저장 **후** 관계를 판정한다. conflict 관계가 저장을 막는 gate는 아니다.
- codex-agent-mem의 provenance·비파괴 exclusion overlay는 참고할 만하다. `source_span` descriptor와 `approved=1`은 검증된 원문 span·인간 승인과 다르다.
- Memharness의 lexical 후보 검색과 exact-ID revision은 참고할 만하다. advisory 뒤 insert는 무조건 실행된다.
- LangMem은 retrieved memories와 conversation에서 diff를 만들고 직접 put/delete한다. 기본 원문 span·승인 계약은 부족하다.
- mnema의 message membership·excerpt/hash·preview/apply 분리는 유용하다. 누락된 conflict verdict도 checked로 처리하는 문제는 가져오면 안 된다.
- 현재 Mem0는 ADD-only다. 파일에 남은 과거 4-operation prompt를 현재 실행 계약으로 해석하면 안 된다.

TypeSafe는 custom provider injection과 엄격한 응답 형식을 지원한다. 하지만 source ID/revision/span/speaker, entailment, 회사 권한을 만들어주지는 않는다. 확률 합 보정, all-zero의 uniform 처리, discrete의 confidence=1도 실측 정확도나 승인 증거가 아니다.

개인 smoke는 공식 client와 native Haiku 연결이 **작동할 수 있다는 proof**다. 3개 합성 source·약 5.018초는 품질 benchmark가 아니다. USD 0.0004921은 목록가 추정이며 구독 청구액이 아니다. cache usage 누락과 debug의 prompt 보존은 실제 관측된 한계다.

**같은 10기준으로 평가**

아래는 제안 판정이다. 비용·품질 우열은 별도 측정이 필요하다.

| 기준 | A: caller 제출 | B: A+native | C: B+Adapter | D: mods complete | E: 전체 교체 | 4views |
|---|---|---|---|---|---|---|
| ① 형식·의미·calibration | typed 계약 필요; 의미는 caller에 의존 | strict schema와 의미 평가 필요; 확률 보정 주장 금지 | 형식 검증은 강점; calibration 보장 없음 | 기존 partial parser 교체 필요 | 제품별 판정 의미가 다름 | 분류만으로 품질 향상 미측정 |
| ② 원문·근거 | ID/revision/UTF8 span/speaker 필수 | 실제 전체 판단 입력 lineage도 결합 | question 형식 밖에서 구현해야 함 | source 계약을 새로 붙여야 함 | 원문 span·맥락 연결에 공백 | 같은 ledger의 pointer 사용 |
| ③ 판단·저장·승인·오류 | 선별과 mutation 분리 | 누락·실패·차단을 exclude와 분리 | SDK validation 성공은 저장 승인 아님 | JSON 성공은 권한 증거 아님 | 저장 후 판정·직접 mutation 문제가 있음 | category에 승인 권한 없음 |
| ④ realm·grant·egress·auth | 기존 caller 권한도 현재 재검사 | native 호출·저장·egress 허가는 별도 | API provider가 구독 route를 뜻하지 않음 | 회사 mod와 runtime 승인 필요 | API key 자동 선택·우회 위험 | view로 접근 범위 확대 금지 |
| ⑤ 큰 session·batch·누락 | cursor와 covered window 필수; host 협조 필요 | bounded window와 verdict 완전성 검사 | 질문 수에 따른 입력량 제한 필요 | `maxTokens=160`을 그대로 적용하기 어려움 | 공통 coverage 계약 없음 | 별도 taxonomy call 기본 추가 금지 |
| ⑥ 비용·quota·latency | 별도 분류콜 생략 가능; 절감 미측정 | cold context·cache·실패콜까지 집계 | Adapter usage만으로 집계 부족 | CLI 시작 비용 회피 가능; 절감 미측정 | 자체 절감 주장 재사용 불가 | 기존 속성 조회부터 시작 |
| ⑦ 검색·시간·TTL | lexical/entity; vector 품질과 다름 | 선별기를 붙여도 embedding/rerank 대체 안 됨 | 확률 SDK가 검색 품질을 해결하지 않음 | 동일한 no-vector 제한 | 일부 흐름은 embedding 필수 | 시간 종류 분리; TTL≠삭제 |
| ⑧ deadline·cancel·publish | model-free 최종 manifest 필요 | lease·cancel·deadline·publication fence 필수 | 기본 retries=0; 취소는 provider 계약 필요 | timeout만으로 late publish 차단 불가 | 공통 보장 부족 | 동일 authority 적용 |
| ⑨ 영향·유지보수 | core/DB/hosts/restore까지 넓은 변경 | A 전체와 executor 운영 추가 | SDK·debug·usage 변환 유지비 추가 | host/build API pin 유지비 추가 | 교체·migration 비용과 계약 손실 큼 | readonly query/view부터 시작 |
| ⑩ 검증 수준 | 새 회사 path 미구현 | 개인 연결 proof만 있음 | 형식·debug·usage 일부 관측 | pinned source 근거; 운영 검증 없음 | static audit; 품질·성능 보장 없음 | 조건부 리뷰 의견; 검색 개선 미측정 |

**B도 반대자의 눈으로 보면 약점이 크다.** 작은 판단에 CLI 고정 입력이 더 비쌀 수 있다. lexical 후보 검색은 기존 충돌을 놓칠 수 있다. batch 경계는 조건이나 부정을 자를 수 있다. 따라서 B를 “Jev보다 싸고 정확한 대체품”으로 선언할 근거는 없다. B를 고르는 이유는 공통 core를 유지하면서 승인된 모델에 의미 판단을 맡길 수 있기 때문이다.

차선 A는 별도 classifier 호출을 줄일 가능성이 있다. 다만 host가 이미 읽은 구간과 제출 coverage를 알려줘야 한다. capture metadata만으로 usefulness를 판정하거나, 제출되지 않은 구간을 exclude로 처리해서는 안 된다.

C의 전체 응답 호환은 범용 `Choice/Score/Noul` 소비자에게만 가치가 있다. memory 선별만 필요하면 좁은 typed provider가 더 작은 계약이다. D는 승인된 Claude mods 환경에서만 B의 executor 후보로 쓴다. `complete`의 제한된 입력 특성은 유용하지만, 외부 MCP가 `$`를 생성할 수는 없다. Codex/omp 공통 engine의 유일 구현으로 삼지 않는다. Jevbridge·effortless·다른 memory engine의 통째 도입은 권한·근거·취소·저장 계약 차이 때문에 기각한다.

**최소 구현 계약**

흐름은 canonical capture → unclassified coverage → caller/native 판단 → 기존 validator → optional fact publication → lexical/entity recall → 최종 자격 재검사다.

선별값 `candidate/exclude/review`와 mutation `no-op/create/patch/conflict-hold`는 별개다. `failed/unavailable`도 따로 둔다. duplicate의 no-op를 usefulness exclude로 바꾸지 않는다. conflict-hold는 publication 전에 적용한다. patch는 정확한 target ID와 현재 revision에 묶는다.

host는 source/speaker/기록 시각/revision/identity를 보존한다. 모델은 의미·조건·본문의 사건 시각 후보를 낸다. `source_event_time`을 본문 사건의 발생 시각으로 확정하지 않는다. span 존재 검증도 entailment나 사실 정확성 검증과 구별한다.

최종 manifest에는 span뿐 아니라 판단에 실제 사용된 전체 source/claim 입력과 credential/realm/binding/revision/route/generation을 결합한다. publish와 delivery에서 현재 자격을 다시 검사한다. `delivery(admissions=())` 우회나 fake local model descriptor는 허용하지 않는다.

optional fact는 기존 authenticated grants와 publication fence로 처리한다. 모든 create에 새 인간 승인을 요구하지 않는다. 필수·공유 instruction 활성화, 권한 확대, 실제 철회는 기존 operator/approval 계약을 유지한다.

회사 native route가 차단되면 `unavailable`로 남긴다. 개인/cloud Jev fallback은 없다. native auth는 host가 관리하며 AF의 authfile 복제나 `danger-full-access` argv를 옮기지 않는다. CLI turn 수를 모델 요청 hard cap으로 추정하지 않는다.

자동 consolidation/reflection과 learned embedding/cross-encoder가 빠지는 범위를 공개한다. 기존 검색은 `text[]` GIN overlap·entity exact·vector RRF이며 `tsvector` FTS가 아니다. 새 no-vector route는 lexical/entity capability로 표시하고, 검색용 NFKC/bigram 복사를 원문 evidence로 쓰지 않는다.

변경 범위는 domain/config/semantic contract, jobs/store/application, MCP·CLI·wire·hosts·spool, forward migration·purge/restore floors·statistics/readiness, 관련 문서와 regression 검증까지다. 작은 wrapper ticket으로 축소할 수 없다.

**소비자가 볼 실패와 검증 사례**

- **P1 — 누락 판정이 exclude로 소실:** batch 응답에서 한 verdict를 제거한다. 해당 구간은 failed/unclassified로 남고 coverage cursor가 완료 처리되지 않아야 한다. 빈 candidates만으로 exclude를 추정하면 실패다.
- **P1 — 중간 scope 확대·회사→개인 fallback:** 판단 중 realm/grant/binding/route를 바꾼다. 기존 결과의 publish/delivery와 개인 endpoint 호출이 모두 차단돼야 한다.
- **P1 — 철회 중 inflight publish:** 실제 입력에 포함된 source/claim을 적법하게 철회한 뒤 계산을 재개한다. 근거 span 밖의 입력 철회도 파생자격을 막아야 한다. deadline/cancel/lease 만료 뒤 늦게 도착한 결과도 publish되지 않아야 한다.
- **P1 — debug 원문 복제:** prompt와 실패 응답에 고유 canary 문자열을 넣는다. receipt/outbox/audit/journal/telemetry에 남지 않아야 한다. Adapter의 성공·오류 debug를 통째로 dump하면 실패다.
- **P2 — 조건·부정 절단:** “개인 프로젝트만”, “고객 작업에서는 금지”가 batch 경계를 넘는 사례를 넣는다. 필요한 맥락이 없으면 review로 보내야 한다. assistant 진행상황이나 `agent_note` 요약을 human evidence로 승격하면 실패다.
- **P2 — no-vector를 vector처럼 선언:** learned vector 생성 없이 embedding/rerank를 호출하거나 동등 검색 품질을 표시하면 실패다. vector route와 비교해 누락률·conflict recall·latency를 별도로 측정한다.
- **P2 — TTL을 삭제로 오인:** TTL 만료 시 검색 비노출과 실제 retention purge를 따로 확인한다. purge 뒤 restore·재색인·잔여 job으로 되살아나면 실패다. source pointer 전량 영구 보존도 새 기본값으로 추가하지 않는다.

**4분류는 하나의 ledger에 겹치는 view로 둔다.** Profile은 optional 사용자 사실, Log는 관련 dated events, Notes는 단기 task 상태, files/skills는 필요할 때 검색/read한다. category가 권한·상시 주입·별도 store를 결정하지 않는다. 새 optional Profile의 auto-pin을 비워도 기존 승인된 mandatory rules는 유지한다. skill 지침 승격은 별도 승인 경로를 따른다.

주요 근거:

- [공식 Adapter `_client.py`](https://github.com/typesafe-ai/system-one-adapter-python/blob/e1d4cc938204b22fc5a3c3aca7044072fe3f712d/src/system_one_adapter/_client.py)
- [Claude mods 모델 호출 계약](https://code.claude.com/docs/en/plugins/mods/api#call-a-model)
- [Engram 관계 저장 흐름](https://github.com/Gentleman-Programming/engram/blob/5c4171845958f046968c14d7d57a325eb4a83b7e/internal/store/relations.go#L364-L746)
- [mnema conflict 처리](https://github.com/Ray0907/mnema/blob/eed19586156ae9664451cb94859f8f3f16b3ac4a/src/store.ts#L293-L423)
- [현재 Mem0 add 흐름](https://github.com/mem0ai/mem0/blob/b7ad69afda6b6ed030347c66d48a13e4de9dec08/mem0/memory/main.py#L897-L1077)

다음 단계는 기존 승인 base를 확정하고, B의 제한 품질 계약과 전체 변경 범위를 별도 scope로 검토하는 것이다. 이 보고서는 구현 승인이나 회사 운영 허가를 선언하지 않는다.