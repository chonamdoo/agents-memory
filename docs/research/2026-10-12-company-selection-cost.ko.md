# 회사에서 Jev 없이 세션 선별 비용을 줄이는 방법

## 결론
개인은 Jev API를 사용할 수 있다. 회사의 문제는 로컬 모델 설치 불가와 **대규모 세션을 큰 모델로 다시 읽는 비용·사용량**이다. 우선 비교할 것은 모델 이름 교체가 아니라 두 경로다.

1. **현재 세션을 이미 읽는 승인 agent가 좁은 후보 판단을 MCP에 제출:** 현재 대화에서 새로 확인한 사실/교정/작업 상태만 판단하고 원문 포인터를 붙인다. 같은 전체 로그를 별도 모델에 다시 보내는 비용을 피할 수 있다. 다만 호출/관측되지 않은 구간은 capture gap이며 '전체 자동 수집 완료'로 취급하지 않는다.
2. **별도 선별이 필요한 신규 구간만 소형 승인 모델로 제한된 배치 처리:** 팀 계정의 Haiku/Luna 이용과 headless 자동화가 실제 허가되는 경우에만 사용한다. 별도 API 계약이 필요한 경우 팀 subscription을 API key처럼 우회 사용하지 않는다.

Jev는 TypeSafe의 System One 모델이다. Haiku/Luna는 같은 모델이 아니며, 생성형 모델의 자기보고 confidence를 Jev의 probability 분포와 같은 값으로 취급하지 않는다. 아래 설계는 비용 절감률·회사 허가·실제 coding-session 정확도를 검증한 결과가 아니다.

## 실제 작은 입력 실행에서 확인한 비용 주의점
개인 기존 native 로그인으로 공개 합성 이벤트 3개(durable 사실/진행 상황/injection)를 remember/discard/review schema로 분류한 기존 실행의 원문 결과를 읽었다. 두 출력은 remember/discard/discard였다. 회사 계정이나 회사 데이터를 사용하지 않았다.

| 관측 항목 | Claude Haiku 실행 | Codex Luna 실행 |
|---|---|---|
| 실제 응답에서 확인한 모델 | modelUsage=`claude-haiku-5-5` | JSONL에 served model 필드 없음; 요청 모델 `gpt-6-luna`는 실행 인자 기록 |
| 입력 토큰 | 일반 2 + cache creation 4,122 | 20,040; cached 0 |
| 출력 토큰 | 123 | 111; reasoning output 58 별도 보고 |
| 모델 호출 성공 | is_error=false, 구조화 3개 판단 | turn.completed, agent_message 구조화 3개 판단 |
| 비용 정보의 한계 | costUSD=0.0008861, costBasis=list인 client-side 보고값; 실제 subscription 청구액 아님 | 이번 JSONL에 dollar cost 없음 |

이것은 서로 다른 CLI context 조건의 한 번씩 실행이지 모델 가격/정확도의 공정한 비교가 아니다. **3개 판단에 CLI 입력 토큰이 20,040까지 보고된 사례는, 이벤트마다 새 native process를 띄우는 방식의 기본 context 비용부터 확인해야 한다는 근거**다. 작은 모델로 바꿨다는 이유만으로 싸다고 결론내리지 않는다. Jev의 영상 비용 절감률을 이 표에서 계산하거나 우리 제품에 적용하지 않는다.

## 동일 계약으로 비교할 경로

| 경로 | 장점 | 비용·누락 위험 | 권고 |
|---|---|---|---|
| 현재 caller가 읽은 구간에서 판단→MCP 후보 제출 | 별도 전체 재독해 감소; 서버 local ML 불필요 | caller가 후보 제출을 빠뜨리거나 compact된 원문을 기억으로 대체할 수 있음; 현재 모델의 추가 출력도 무료는 아님 | capture coverage와 실제 다음-task 소비가 확인되는 host부터 비교 |
| 신규 구간→팀 소형 native 모델 배치 | Jev API 없이 별도 선별 가능; 형식 제약 가능 | CLI 기본 context, usage/quota, batch 관계 손실, 로그인/약관/admin 자동화 조건 | 허가된 경우만 시험; per-event process 기본값 기각 |
| 회사가 승인한 별도 API/provider | 모델·batch·입출력 예산 제어가 명확할 수 있음 | 별도 계약/egress/API 비용; 지금 승인된 경로가 아님 | 사용 허가가 있는 경우만 별도 대안 |
| 회사 데이터→개인 Jev/개인 계정 | 기술적 전송은 가능해도 회사 권한 위반 위험 | 승인된 workspace·retention 경계 벗어남 | 금지; 자동 fallback 없음 |
| 분류기를 없애고 전량 또는 키워드만 저장 | 모델 호출 수 감소 | 의미 선별 기능 상실, false-negative, retrieval context 증가 | Jev 대체라고 부르지 않음 |

## 제한된 증분 선별 계약 — 제안
- **수집 단계:** host/speaker/session/thread/agent·실제 source event time·recorded_at·원문 revision을 코드가 기록한다. 모델이 만들어낸 origin/time는 거절한다.
- **결정적 사전 처리:** 빈 이벤트, 동일 원문 revision의 중복, 명확히 식별된 시스템 반복물만 제외한다. 전체 tool 결과·assistant 발화·짧은 교정을 event 종류만으로 버리지 않는다.
- **증분 단위:** 같은 source window의 마지막 확정 위치와 신규 이벤트를 사용한다. 화자·교정 대상·조건·예외를 알 수 있는 작은 인접 문맥을 함께 준다. batch가 잘렸다는 사실은 모델에 보이며, 보지 않은 구간의 부재를 근거로 discard하지 않는다.
- **작은 출력:** 후보/제외/검토의 선택, 제공된 event/claim 식별자, 필요한 원문 구간 선택. 모델의 설명은 판단 이유이지 원문 증거가 아니다. 원문은 코드가 현재 revision에서 읽어 정확한 span/hash/권한을 검증한다.
- **원문 재사용:** 동일 source revision·판단 계약·policy·사용할 현재 근거가 같을 때 결과를 재사용한다. 모든 provider/model이 같은 정확도를 내거나 판정이 영구 유효하다고 약속하지 않는다.
- **기억 추출:** 선별된 window만 더 구체적인 사실/교정/사건/작업 메모로 추출한다. 작은 후보 분류와 기존 기억의 update/delete/merge 판단은 다른 작업이다.
- **보류와 장애 구별:** 의미가 애매하거나 모순이면 review. provider timeout·invalid schema·미지원 계정은 failed/blocked이지 정상 discard/review 성공이 아니다. 그 결과로 원문이나 기존 기억을 삭제하지 않는다. 제한된 보관 기한 안에 재처리하지 못하면 누락을 보고한다.
- **권위:** 후보가 유용하다는 판단과 team rule/skill 지침의 operator 승인은 분리한다. confidence, 반복 횟수, 모델 이름은 승인권이 아니다.

회사에서 local embedding을 설치할 수 없다는 제약도 남는다. lexical/FTS shortlist와 승인 native model의 제한된 rerank는 가능한 설계 대안이지만 기존 vector retrieval과 동일한 품질·인터페이스를 확인한 것이 아니다. Claude/Codex에 숫자 벡터를 생성시켜 실제 embedding처럼 쓰는 대체는 제안하지 않는다. 회사용 전체 semantic executor는 아직 구현·승인된 상태가 아니다.

## 비교 검증 계획 — 아직 미실행
- 같은 공개 또는 회사 승인 corpus, 동일 correction/조건/예외/한국어/code 질문을 기준으로 full-session 대형 분석, caller-owned 후보, 신규-window 소형 배치를 비교한다.
- 전체/새로 전송한 토큰, CLI 기본 context, cached input, 호출 수, latency, 실제 요금 또는 workspace usage, retry/review 부담을 구분한다.
- 원문 대비 durable correction recall, 조건·예외 누락, false-negative, 잘못 승격한 기억, 모순/시점/abstention, 다음 실제 coding 행동을 측정한다. 분류 label만 맞은 결과를 성공으로 세지 않는다.
- 재시작·같은 source 재수집·조건이 다른 새 교정·cut batch·승인 계정 미지원에서 중복 publication 또는 무언의 discard가 없는지 확인한다.
- 회사→개인 Jev/credential/corpus 경로는 허용된 적이 없으면 차단한다.
- 통과 수치와 예산은 승인된 실제 workload에서 정한다. 영상의 95%나 일반 confidence 0.9를 초기 합격값으로 복사하지 않는다.

## 1차 근거
- [Claude programmatic CLI, structured output, client-side cost estimates, bare mode auth 제한](https://code.claude.com/docs/en/headless): `--bare`는 subscription OAuth/keychain을 읽지 않으므로 팀 로그인 재사용을 위해 무조건 적용할 수 없다. 현재 개인 probe는 safe mode/empty tools로 실행된 별도 조건이다.
- [Claude model configuration·managed restrictions](https://code.claude.com/docs/en/model-config): full model/alias와 admin 허용을 구분한다.
- [Codex authentication](https://developers.openai.com/codex/auth): ChatGPT sign-in의 workspace 권한·retention과 API 조직 정책은 다르다. 공식 문서는 CI/CD 같은 programmatic workflow에 API key를 사용하도록 안내한다. 회사 subscription headless daemon 허가를 이 문서만으로 추정하지 않는다.
- [TypeSafe state](https://docs.typesafe.ai/concepts/state.md): 관련 메시지·관계·정책을 함께 제공, 독립 질문은 같은 state를 본다.
- [TypeSafe confidence](https://docs.typesafe.ai/confidence.md): probability 분포의 집중도 요약; domain별 threshold 검증 필요. 권한/진실의 증명 아님.
- [Engram MCP caller judgment](https://github.com/Gentleman-Programming/engram/blob/5c4171845958f046968c14d7d57a325eb4a83b7e/internal/mcp/mcp.go): 기존 agent와 memory server의 판단/집행 분리를 참고한다.

원문 probe는 로컬 private checkpoint에 보존되어 있다. 공개 보고에는 회사 데이터·auth·native reasoning/provider internals를 포함하지 않는다. 이 조사로 기존 AF 구현 리뷰의 승인이나 회사 운영 완료를 주장하지 않는다.
