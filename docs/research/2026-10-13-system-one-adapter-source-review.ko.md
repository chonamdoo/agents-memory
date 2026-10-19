# TypeSafe System One Adapter: 회사 native 판단기로 재사용할 수 있는 것과 없는 것

## 결론

사용자가 제시한 공식 Python 어댑터는 **custom provider 주입 경계와 TypeSafe 응답 형식**을 실제로 제공한다. `ClaudeCLIProvider`를 추가하는 구상은 소스와 맞는다. 그러나 이 어댑터를 붙이는 것만으로 **Jev의 지연·가격·보정 품질, 원문 근거 검증, 회사 구독 자동화 승인, memory lifecycle**이 생기지는 않는다. 우리 메모리 3분류의 default 실행 엔진으로 바로 채택하기보다, 범용 TypeSafe 형식이 필요한 개인/허용 환경의 선택적 compatibility boundary로 비교해야 한다.

고정 공개 소스 검토 뒤 exact pin의 공식 SDK + custom provider + 기존 native Haiku 로그인을 실제 연결했다. 개인 합성 source 3개에 Choice/Score/Noul 5개 질문의 정상 반환·검증을 관측했다. 이 실행과 cached usage·debug 원문 보존 위험은 `2026-10-13-typesafe-native-smoke.ko.md` 및 body-free proof에 보존했다. 회사 사용 승인/환경 검증·품질 benchmark는 하지 않았다. 이전 단독 CLI probe의 비용 관측은 `2026-10-12-company-selection-cost.ko.md`와 구분한다.

## 확인한 버전

- 저장소: [typesafe-ai/system-one-adapter-python](https://github.com/typesafe-ai/system-one-adapter-python)
- 고정 SHA: `e1d4cc938204b22fc5a3c3aca7044072fe3f712d` (`gh api .../commits/main --jq .sha`로 관측)
- [pyproject](https://github.com/typesafe-ai/system-one-adapter-python/blob/e1d4cc938204b22fc5a3c3aca7044072fe3f712d/pyproject.toml): `system-one-adapter` 0.2.1, Python >=3.10, Pydantic/TypeSafe SDK/tenacity dependency. OpenAI/Anthropic/Gemini는 optional extras.
- [MIT LICENSE](https://github.com/typesafe-ai/system-one-adapter-python/blob/e1d4cc938204b22fc5a3c3aca7044072fe3f712d/LICENSE): 코드 재사용 가능, 상당 부분 복사 시 copyright/license notice 보존. 서비스·모델 계정 이용권 및 회사 승인을 뜻하지 않는다.

## 1. 실제 호출·변환 흐름

```text
state + typed questions
  → question/type/criteria 검증, 매 요청 output schema 생성
  → system instructions + JSON-serialized document 구성
  → injected SyncProvider/AsyncProvider.request(messages, schema, structured)
  → JSON decode + strict Pydantic schema validation
  → Noul / Choice / Score 답변 변환
  → TypeSafe-shaped answers + usage + debug
```

- [providers/base.py](https://github.com/typesafe-ai/system-one-adapter-python/blob/e1d4cc938204b22fc5a3c3aca7044072fe3f712d/src/system_one_adapter/providers/base.py): provider는 한 번의 모델 호출만 맡는다. `ProviderResult(text,input_tokens,output_tokens)`, `model_name`, `request`, `translate_error` 계약이다. `model` 인자에 provider 객체를 주면 client가 직접 사용하며 수명은 caller 소유다.
- [_client.py](https://github.com/typesafe-ai/system-one-adapter-python/blob/e1d4cc938204b22fc5a3c3aca7044072fe3f712d/src/system_one_adapter/_client.py): state를 JSON으로 직렬화하고 `<`/`>`를 escape해 document delimiter 모방을 줄인다. system prompt는 document를 untrusted로 취급하라고 요구한다. 이것은 prompt injection 불가능성 증명이 아니다.
- [providers/anthropic.py](https://github.com/typesafe-ai/system-one-adapter-python/blob/e1d4cc938204b22fc5a3c3aca7044072fe3f712d/src/system_one_adapter/providers/anthropic.py): built-in provider는 `anthropic.Anthropic(max_retries=0)`와 Messages API를 호출한다. Claude 구독 로그인이나 `claude` subprocess 실행 구현은 아니다.
- [_schema.py](https://github.com/typesafe-ai/system-one-adapter-python/blob/e1d4cc938204b22fc5a3c3aca7044072fe3f712d/src/system_one_adapter/_schema.py): 질문이 비면 거절, Choice/Score는 최소 두 criteria. 응답은 모든 question ID를 요구하고 extra fields를 금지하며 strict 타입·allowed labels·확률 범위 0..1을 로컬에서 검증한다. provider 제약상 숫자 bound 일부는 전달 schema에서 제거하되 Pydantic 검증은 유지한다.

## 2. 사용자가 가져온 설명의 정확한 경계

| 설명 | 소스 판정 | 우리에게 필요한 추가 경계 |
|---|---|---|
| custom Claude CLI 호출부를 붙일 수 있다 | 맞음: injected provider seam 및 exact SDK+native Haiku 개인 합성 실행 확인 | 회사 관리 설정·전체 tool/hook isolation·deadline/cancel·usage·원문 근거·lifecycle 검증은 별도 |
| choice/score/noul 및 TypeSafe 형식 | 맞음 | 우리 source ID/revision/span/speaker와 모든 event의 판정 coverage는 별도 |
| 검증·정규화 제공 | 부분적으로 맞음 | 타입/각 확률 범위 검증은 실제. 합계 1 정규화는 opt-in이며 기본 `normalize_probabilities=False` |
| 구독 Haiku로 Jev와 같은 형태 | 응답 compatibility의 의미에서는 가능 | Jev 가격·보정·지연·precision/recall 동등성은 아님 |
| 확률 0.9는 정답률 90%가 아니다 | 맞음 | 승인·철회·파괴적 연산의 자동 권위로 사용 금지 |
| `--bare`는 구독 로그인과 부적합 | 공식 Claude Code 문서와 맞음 | `--tools ''`만으로 프로젝트 설정·MCP·hooks 등 전체 격리가 완료됐다고 보지 않음 |

### 정규화와 confidence의 함정

[probability_normalization.py](https://github.com/typesafe-ai/system-one-adapter-python/blob/e1d4cc938204b22fc5a3c3aca7044072fe3f712d/src/system_one_adapter/_utils/probability_normalization.py)와 [confidence_metrics.py](https://github.com/typesafe-ai/system-one-adapter-python/blob/e1d4cc938204b22fc5a3c3aca7044072fe3f712d/src/system_one_adapter/_utils/confidence_metrics.py):

1. probability mode에서 각 값은 0..1이지만 합계가 1이 아니어도 기본 설정은 **응답을 반환하며** debug에 오차를 기록한다. `Choice`는 그 값들의 argmax를 택한다. "잘못된 분포는 항상 실패"라는 계약이 아니다.
2. normalization을 켜면 합계를 1로 rescale한다. 모든 값이 0이면 uniform으로 대체한다. 이는 모델의 의미 판단을 보정하거나 불확실성을 실측하는 작업이 아니다.
3. `Score.score` 계산은 reported distribution의 normalization 옵션과 무관하게 rescale한 기대값을 사용한다. raw probabilities 합계와 반환 score의 사용 분포가 다를 수 있다.
4. discrete mode는 선택한 라벨에 1, 나머지에 0을 만들어 `confidence=1`이 된다. **확신 100%를 관측한 것이 아니다.** discrete 출력을 confidence-based 자동 승인에 연결하면 위험하다.
5. choice confidence는 분포의 최대값을 uniform baseline 대비 scale한 집중도다. 보정된 사실 정확도나 인간 승인 증거가 아니다.

따라서 우리 memory gate는 categorical disposition과 error/blocked state를 직접 사용하고, uncalibrated confidence로 승인 여부를 결정하지 않는다. 실제 평가 전 임의 0.5/0.9 cutoff를 제품 계약으로 채택하지 않는다.

## 3. 비용과 privacy: 무조건 얇은 wrapper는 아니다

- `_client` default corrective retry=0, transient `RetryPolicy(max_retries=0)`이다. 자동 재시도가 기본이라고 설명하면 틀린다. 켜면 추가 provider 호출·토큰·latency가 생기므로 우리 durable retry ownership과 중복되지 않게 해야 한다.
- `ProviderResult`는 input/output counts만 받는다. Claude native의 cache-read/cache-creation 입력과 requested/served model 구분 등은 이 계약만으로 충분하지 않다. 기존 probe의 입력 2 + cache creation 4,122처럼 **input_tokens 하나만 읽으면 실제 처리량을 과소표시**할 수 있다.
- [capture_attempt](https://github.com/typesafe-ai/system-one-adapter-python/blob/e1d4cc938204b22fc5a3c3aca7044072fe3f712d/src/system_one_adapter/providers/base.py)은 messages와 schema를 snapshot한다. `_client.response()`는 `debug.llm_attempts`에 이를 붙이며 raw provider response도 보관할 수 있다. 최종 exception에도 debug traces를 붙이는 경로가 있다.
- [_response.py](https://github.com/typesafe-ai/system-one-adapter-python/blob/e1d4cc938204b22fc5a3c3aca7044072fe3f712d/src/system_one_adapter/_response.py)는 debug를 일반 JSON 직렬화 필드로 포함한다. **전체 response/exception을 audit, operation receipt, journal 또는 telemetry에 dump하면 원문·모델 output이 복제될 수 있다.** bounded in-memory validation와 body-free 운영 기록을 분리해야 한다.
- 문서의 간단한 `claude -p ... "$STATE"` 예는 설명용이다. 실제 호출은 source/state를 argv에 넣지 않고 stdin으로 전달해야 한다. 기존 로그인 native CLI를 사용하며 auth 파일을 읽거나 bearer를 API provider로 추출하지 않는다.
- managed company settings를 우회하는 옵션 조합이나 개인 provider fallback으로 실행 성공을 만들지 않는다. 팀 login 가능성과 daemon/CI 자동 호출 승인, memory 저장 승인, 고객별 egress 정책은 독립이다.

## 4. memory pipeline에서의 채택 비교

| 대안 | 장점 | 단점/영향 | 결정 전 확인 |
|---|---|---|---|
| 승인된 현재 caller가 읽은 대화에서 bounded candidates 제출 | 별도 전체 transcript 재분석을 피할 수 있음; 새 local ML 없음; 실제 MCP OSS와 가까움 | capture된 source와 evidence binding, 미검토 구간 coverage, caller 실패 상태 필요; 전 session 선별 보장 아님 | 현재 core의 source/candidate admission seam, 사용자 visible 결과 |
| 허가된 native Haiku의 신규 구간 batch judge | 작은 별도 판단기; exact SDK+native 개인 합성 연결 확인 | cold CLI context·cache·quota·isolation·deadline·cancellation; 회사 자동화 허가 필요 | 개인 smoke만으로 workload 품질/비용 합격은 아님; text 판단은 embedding 대체 불가 |
| native CLI + 공식 System One Adapter | 범용 question/Choice/Score/Noul 호환·strict schema 재사용 | 추가 SDK/response 계약과 full debug trace 처리; 확률 형식은 우리 원문 evidence 계약 아님 | 범용 TypeSafe API가 실제 요구인지; 불필요하면 core에 강제 의존성 넣지 않음 |
| 개인 Jev API | 개인 외부 허용 환경에서 specialized judge 활용 | 외부 endpoint·키·usage·data policy 별도; 회사 route 대체 불가 | 개인 corpus만, 회사 credential/원문 이동 없음 |

**분류·저장·지침 승인을 혼동하지 않는다.** 회사가 승인한 모델이라는 조건은 모든 fact create에 새로운 인간 서명을 요구하라는 조건이 아니다. optional fact/candidate의 machine processing는 기존 authenticated grants와 publication fences를 지키고, 필수/공유 instruction 활성화·권한 변경·실제 철회는 기존의 별도 operator/approval 계약을 유지한다. Profile view에 포함됐다는 이유로 instruction authority를 추가하지 않는다.

## 5. 완료된 별도 소스 조사와 통합 리뷰의 위치

`HeyCubit/effortless`와 `tacticocc/Jevbridge`의 pinned source 조사 결과는 `2026-10-13-native-judge-sources.ko.md`에 보존했다. effortless의 `$.model.complete()`는 공식 Claude Code mods API를 사용하는 실제 session-credential 호출이다. 외부 MCP에서 같은 `$`를 사용할 수 있다는 뜻은 아니며 전체 plugin은 과대 권한/기능이다. Jevbridge의 native ACP generation과 API-key 기반 판단기는 서로 다르다. 같은 이름의 `crystal-aim/effortless-claude-code` installer는 이 askHaiku 사례가 아니다.

별도 Profile/Log/Notes/files/skills 및 concrete core integration scope·새 source·실제 SDK smoke를 묶은 독립 native 통합 재리뷰를 완료했다. 동일 통합 stdin hash와 두 native 최종 원문은 `2026-10-13-integrated-native-proof.json`, `2026-10-13-integrated-opus-review.ko.md`, `2026-10-13-integrated-sol-review.ko.md`에 보존했다. 부모의 대안별 채택·기각·영향·명시 결정 전제는 `2026-10-13-company-final-proposal.ko.md` 및 GitHub issue1의 comment-6127752208에 있다. 기존 frozen AF fresh review는 request-changes가 남아 있으며 이번 조사·개인 probe를 implementation approval·QA/handoff로 대체하지 않는다.
