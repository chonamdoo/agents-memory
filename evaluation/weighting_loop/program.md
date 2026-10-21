# 확장 가중치 루프 (program.md)

이 문서의 규칙은 첫 측정 전에 고정한다. 진행 기록은 `LOG.md`에 남긴다. 사용자가 의미 검색 루프의 중간 결론(`evaluation/semantic_loop/LOG.md`)을 보고 이 루프를 열기로 결정했다(2026-10-21).

## 배경

agent 확장(`query_expansions`)은 의미 질의를 크게 살렸다. 20배 규모 의미 hit가 31에서 60–82로 늘었다(84개 중). 그러나 깨끗하게 생성한 확장 네 번 모두 20배 키워드 MRR이 0.564–0.576으로, 동결된 하한 0.580을 넘지 못했다.

원인은 운영 경로가 확장을 질의와 한 토큰 집합으로 합치는 데 있다. 순위는 겹친 토큰 수를 세므로, 확장 단어가 원래 질의 단어와 같은 무게를 갖는다. 이 루프는 순위가 질의 단어와 확장 단어를 따로 볼 수 있게 하고, 확장의 무게를 조정한다.

## 고정된 결정 (변경 금지)

- **기존 제품 합격선은 그대로 동결한다.**
  - Recall@20, feasible coverage, agent-selected Precision@3: 각각 ≥90%
  - 의미 보존 ≥95%, critical fixture 100%
  - no-match 오반환과 false-empty: 각각 ≤5%
  - off/on 성공률 각각 ≥80%, 성공률 차이의 CI 하한 ≥0
  - 조건 누락·근거 오류·false promotion 비증가
- **#10 trial용 사람 gold 120개는 보지 않는다.**
- **브랜치는 `claude/quirky-fermat-m0ogfo`만 쓴다.** main 직접 push와 병합은 하지 않는다.
- **실문서(사만다 정책서)는 `AM_LOOP_POLICY_DIR` 로컬에서만 읽는다.** 원문, 그것으로 만든 질의와 확장은 commit, PR, 리뷰 입력에 넣지 않고, 집계만 기록한다.
- **무결성 게이트는 필수다.** 다음이 확장 경로로도 섞이지 않아야 한다.
  - 삭제·철회된 기억
  - 다른 프로젝트(binding)·다른 realm의 기억
  - 기간 만료, 다른 snapshot, 운영자가 거부한 health, 다른 workspace의 기억

  모든 eligibility 판단은 동결된 `eligible` CTE가 한다. 순위 SQL은 그 안에서 순서만 정한다.

## 준비 (측정 전, 동작 중립)

1. `Store.search_lexical`에 `query_tokens`(호출자 질의의 토큰, 검색 토큰의 부분집합)를 추가한다.
   - 생략하면 모든 토큰을 질의 토큰으로 본다.
   - 저장소는 `eligible` 뒤에 한 행짜리 `query_terms`(`tokens`, `search_names`) CTE를 둔다.
   - `Application.context`는 `tokens(query)` 중 검색 토큰에 있는 것을 넘긴다.
2. 원래 순위 SQL은 `query_terms`를 읽지 않는다. 그러므로 이 배관은 동작을 바꾸지 않는다. 이를 다음으로 확인한다.
   - dev L0를 다시 재서 질의별 순위가 의미 루프의 저장된 baseline과 완전히 같아야 한다.
   - 확장 없는 검색이 `query_tokens` 생략과 명시에서 같은 순서를 내야 한다(`tests/test_retrieval_expansion_weight.py`).
3. 무결성 게이트에 `tests/test_retrieval_expansion_weight.py`를 더한다. 이 테스트는 확장 단어로만 닿는 기억이 다음 경우 나오지 않음을 확인한다.
   - 철회된 경우
   - 다른 binding에 있는 경우
   - 다른 realm에 있는 경우

## 수정 허용 파일

`src/agents_memory/retrieval_ranking.py`만 수정한다. 순위 SQL의 계약(같은 파일 docstring)은 바꾸지 않는다. 다른 파일은 동결 digest로 막는다.

## 비교군 (모두 같은 후보 순위 SQL로 잰다)

| ID | 확장 | 뜻 |
|---|---|---|
| L0c | 없음(corpus 자체의 G3 확장만) | 확장을 안 보내는 agent. 키워드 성능이 baseline과 같아야 한다 |
| X2c | `semantic_loop/expansions/v2-*.json` | 넓게 확장하는 agent(안내 v2) |
| X4c | `semantic_loop/expansions/v4-*.json` | 적게 확장하는 agent(안내 v4) |

- 기준(baseline)은 의미 루프에서 이미 잰 L0(원래 순위, 확장 없음)이다.
  - dev: `semantic_loop/state/baseline-dev.json`
  - holdout·실문서: `baseline-holdout.json`, `baseline-policy.json`(각각 한 번만 쟀다)
- 확장 두 세트를 함께 요구하는 이유가 있다. 가중치가 한 번의 생성 결과에만 맞춰지는 것을 막고, 확장을 많이 쓰는 agent와 적게 쓰는 agent 모두에서 성립해야 하기 때문이다.

## 탐색 공간 (순서대로)

1. **W(w):** 겹친 질의 토큰 수 + w × 겹친 확장 전용 토큰 수. entity 가지도 같은 방식으로 질의 entity 1, 확장 entity w로 센다. w ∈ {0.5, 0.25, 0.1}.
2. **R(α):** lexical·entity 가지는 질의 토큰만 쓴다. 확장 전용 토큰은 별도 RRF 가지로 넣고, 무게는 α ∈ {1, 0.5}다.
3. 위 결과를 보고 만드는 조합은 LOG에 근거를 남긴다.

모든 후보는 확장이 없을 때(질의 토큰 = 검색 토큰) 원래 순위와 같은 순서를 내야 한다.

## keep 규칙 (dev, 1·5·20배)

다음을 모두 만족하면 keep이다.

1. 무결성 게이트 전부 통과. 범위는 `test_retrieval_integrity.py`, `test_retrieval_integrity_vector.py`, `test_retrieval_expansion_weight.py`다.
2. **X2c와 X4c 각각** baseline 대비 다음을 만족한다.
   - 의미 질의 hit 순증 ≥3(1·5·20배 합)
   - 어느 키워드 군·규모에서도 hit 순감 ≥2가 없다
   - 각 규모에서 의미·키워드 두 세트의 MRR 하락 ≤0.02
3. **L0c** baseline 대비: 어느 키워드 군·규모에서도 hit 순감 ≥2가 없고, 각 규모에서 두 세트의 MRR 하락 ≤0.02다.
4. 지연: 세 비교군 모두 순위 SQL 포함 검색 p95(20배) ≤ baseline×1.25. **3회 측정 모두 통과해야 한다.** 측정 후 판정 방식을 바꾸지 않는다.

keep이 아니면 되돌린다. 모든 시도(실패 포함)는 `results.tsv`와 `LOG.md`에 남긴다.

## 승격 (최대 3회)

holdout을 보기 전에 독립 subagent 적대적 리뷰를 돌린다. P0/P1이 있으면 holdout을 보지 않고 고친다.

holdout·실문서용 확장은 첫 승격 시도 전에 dev와 같은 방식으로 만들어 동결한다.
- 생성: 도구 없는 subagent, 질의만 프롬프트로 제공, 정답이 겹치지 않는 묶음, 안내 v2·v4
- 실문서 확장은 로컬(`AM_LOOP_POLICY_EXPANSIONS`)에만 두고 commit하지 않는다.

승격은 아래를 모두 만족해야 한다.

1. **X2c와 X4c 각각**
   - 합성 holdout 의미 질의: 질의 단위 paired bootstrap 95% CI 하한 > 0
   - 합성 holdout 키워드: 군별 hit 감소 없음, MRR 하락 ≤0.02
   - 실문서 heading: recall 감소 없음, MRR 하락 ≤0.02
   - 실문서 바꿔 말한 질의: 평균 recall 변화 > 0
2. **L0c:** 합성 holdout 키워드와 실문서 heading 모두 군별 hit 감소 없음, MRR 하락 ≤0.02다.
3. 무결성 게이트와 기존 관련 테스트가 CI 런타임에서 통과한다.
4. 적대적 리뷰에서 P0/P1이 없다.

통과하면 PR을 만든다(병합하지 않음). PR에는 다음을 쓴다.
- 결과는 "합성·실문서 기준 후보 검색 품질 개선"이다.
- 효익은 #10 trial로 판정한다.
- agent 확장 안내(도구 설명) 변경 제안을 함께 담는다.

실패하면 마지막 keep 이전 순위로 되돌리고 계속한다.

## 멈춤

다음 중 하나가 되면 결과와 사유를 기록하고 멈춘다.
- 승격 3회가 모두 실패
- 시작 후 24시간 경과
- 탐색 공간 소진
