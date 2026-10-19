# 공식 System One Adapter + native Haiku: 실제 연결 smoke

## 결론

**사용자가 제안한 custom provider 연결은 실제로 작동했다.** 공식 pin의 Python client에 임시 provider를 주입하고 기존 native Claude 로그인으로 Haiku를 호출하여 Choice/Score/Noul 응답을 받았다. API-key Anthropic provider로 대신하지 않았다. 이것은 개인 공개 합성 fixture의 호환성 실행 증거다. 회사 자동화 승인·classifier 품질·Jev 95% 절감·원문 근거 계약·완성된 memory pipeline의 증거는 아니다.

공식 소스: [System One Adapter pin e1d4cc9](https://github.com/typesafe-ai/system-one-adapter-python/tree/e1d4cc938204b22fc5a3c3aca7044072fe3f712d), [custom ProviderResult/SyncProvider 계약](https://github.com/typesafe-ai/system-one-adapter-python/blob/e1d4cc938204b22fc5a3c3aca7044072fe3f712d/src/system_one_adapter/providers/base.py), [client injection](https://github.com/typesafe-ai/system-one-adapter-python/blob/e1d4cc938204b22fc5a3c3aca7044072fe3f712d/src/system_one_adapter/_client.py#L327-L402).

## 실행 경계

- 저장소/AF 구현·설정 변경 없이 scratch에 throwaway Python provider를 만들었다. uv isolated/no-project로 위 exact git pin의 SDK를 설치했으며 local 모델을 설치/다운로드하지 않았다.
- 실제 requested model은 claude-haiku-5-5, effort low. native result.modelUsage에서도 같은 canonical model/firstParty를 관측했다. 이것은 CLI metadata이며 별도 server attestation은 아니다.
- source/state는 stdin. native JSON schema/system prompt는 SDK가 생성. tools empty, strict empty MCP config, safe-mode, slash commands disabled, no-session-persistence. bare는 사용하지 않았고 auth file을 읽거나 API용 credential로 복사하지 않았다.
- 3개의 합성 source에 Choice 3개, 명시 선호 Noul 1개, 일시 작업 상태의 durability Score 1개를 한 SDK evaluation로 질문했다.
- native exit0, subtype success, is_error=false. SDK strict response validation 통과. 세 Choice의 허용 label·question ID와 확률 합1을 probe에서 확인했다. durable memory mutation은 하지 않았다.
- 첫 호출은 subprocess failure였고 stdout/stderr를 선보존하지 않아 원인은 미관측이다. 진단 보존을 추가하고 max-turns1에서2로 변경한 뒤 성공했다. **첫 원인이 max-turns라고 단정하지 않는다.** 성공 JSON은 num_turns=3을 보고하므로 해당 값을 hard model invocation cap/청구횟수로 해석하지 않는다.

## 관측 결과

| 합성 입력의 의미 | 반환 Choice |
|---|---|
| 개인 프로젝트 한국어 선호, 회사 고객 예외 포함 | memory_candidate |
| assistant의 build log 확인 진행상황 | exclude |
| 어느 프로젝트인지 불명확한 tabs 선호 | review_needed |

Noul explicit_korean_personal=0.95, Score s2_durability=0.06도 반환했다. 이 값은 모델이 만든 판단/분포이지 실제 정답률·보정된 확률이 아니다. 3개 입력으로 precision/recall 또는 배치 경계 안전성을 측정했다고 하지 않는다.

| 지표 | 실제 관측 |
|---|---:|
| native wall latency seconds | 5.018 |
| native input_tokens | 4 |
| native cache_creation_input_tokens | 689 |
| native cache_read_input_tokens | 5,640 |
| native output_tokens | 595 |
| native thinking_tokens (output 내 세부값) | 151 |
| SDK input_tokens_total | 4 |
| SDK output_tokens_total | 595 |
| SDK n_retries | 0 |
| CLI list-price USD estimate | 0.0004921 |

cached input은 모델 처리량에서 빠지지 않는다. SDK input4만 표시하면 cache6,329를 누락한다. CLI list-price는 구독 계정의 실제 청구액/회사 quota 수치가 아니다. SDK retry0 및 debug attempt1은 native 내부 request 수를 증명하지 않는다. native iterations metadata도 독립 완전성 증거가 아니다.

**debug_contains_prompt=true를 실제 관측했다.** 전체 response/debug/error를 durable receipt·audit·journal·telemetry로 직렬화하는 것은 원문 복제 경계 위반 위험이다. SDK를 채택하더라도 body-free 운영 증거만 별도 저장하고 raw prompt/output debug를 정상 persistence에서 제외해야 한다.

## 이 smoke가 충족하지 않은 계약

- source ID/revision/UTF8 span/speaker와 모든 event coverage 검증
- 원문에서 선택한 근거의 의미 충족·부정/조건/예외 보존
- company managed settings/계정 entitlement/headless·daemon·retention·고객 egress 승인
- tool/hook/customization 실제 전체 isolation, kill/reap·quota·실패·route/source/credential revoke race
- memory admission/publication/delivery·purge/restore, lexical/vector/rerank 검색 품질
- Jev 대비 비용·지연·calibration 및 downstream task 유용성

회사 core 의존성이나 TypeSafe adapter feature를 추가하지 않았다. 임시 provider는 검증 뒤 제거하고 native raw synthetic proof는 private로 남긴다. 범용 TypeSafe question 계약이 별도 요구일 때 optional compatibility boundary로 고려하고, memory selection core가 이 SDK를 필수로 가져야 한다는 결론은 아니다.
