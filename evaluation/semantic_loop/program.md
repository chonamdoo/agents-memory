# 의미 검색 루프 (program.md)

이 문서의 규칙은 첫 baseline 측정 전에 고정한다. 진행 기록은 `LOG.md`에 남긴다. 이전 루프(`evaluation/retrieval_loop/`)에서 얻은 교훈을 규칙에 미리 넣었다.

## 목표

같은 의미를 다른 말로 물어도 정답 기억이 후보 20개 안에 들어오게 한다. 대상은 바꿔 말하기, 동의어, 한영 교차, 설명형 질의다. 키워드 검색 능력과 기억 무결성은 지금 수준을 유지해야 한다.

## 고정된 결정 (변경 금지)

- **기존 제품 합격선은 그대로 동결한다.**
  - Recall@20, feasible coverage, agent-selected Precision@3: 각각 ≥90%
  - 의미 보존 ≥95%, critical fixture 100%
  - no-match 오반환과 false-empty: 각각 ≤5%
  - off/on 성공률 각각 ≥80%, 성공률 차이의 CI 하한 ≥0
  - 조건 누락·근거 오류·false promotion 비증가
- **#10 trial용 사람 gold 120개는 보지 않는다.**
- **브랜치는 `claude/quirky-fermat-m0ogfo`만 쓴다.** main 직접 push와 병합은 하지 않는다.
- **벡터(dense) 경로는 오프라인 측정만 한다.** 운영 코드에 넣지 않는다. 결과는 정책 결정의 근거로만 쓴다(로컬 모델, 외부 API, 회사 no-local-ML 제약).
- **실문서(사만다 정책서)는 `AM_LOOP_POLICY_DIR` 로컬에서만 읽는다.** 원문과 그것으로 만든 질의는 commit, PR, 리뷰 입력에 넣지 않고, 집계만 기록한다.

## 비교군

| ID | 내용 | 운영 영향 |
|---|---|---|
| L0 | 현재 lexical 순위(원래 순위 SQL). baseline | — |
| X | L0 + agent 확장. coding agent 역할의 subagent가 `expansion_guidance.md`를 읽고 질의마다 `query_expansions`(최대 8개)를 만든다. 생성 결과는 안내문 버전별로 동결한다 | 승격 시 도구 설명 변경 제안 |
| D(m) | 모델 m의 dense만 사용. eligible claim과 cosine 유사도로 상위 20개 | 오프라인 측정만 |
| H(m) | L0 + D(m)을 RRF로 결합 | 오프라인 측정만 |
| HX(m) | H(m) + X | 오프라인 측정만 |

- 모델 후보: `intfloat/multilingual-e5-large`(1024차원), `paraphrase-multilingual-MiniLM-L12-v2`, `minishlab/potion-multilingual-128M`(정적).
- dense 순위는 순위 SQL 안에서 `eligible` CTE에 join해서 계산한다. eligible을 거치지 않는 벡터 검색은 금지한다.

## 지표

- **주 지표:** 의미 질의(S1–S6)의 recall@20 hit 합계(1·5·20배 합).
- **비퇴행 세트:** 기존 키워드 질의(G1–G9)의 hit, 그리고 두 세트의 MRR.
- **보고 지표 (게이트 아님):**
  - S8/G8 no-match 평균 반환 수. dense는 항상 20개를 반환하므로 agent가 판단해야 할 양이 늘어난다.
  - 질의 임베딩 시간
  - 색인(임베딩) 비용
  - 모델 크기
- **지연:** 순위 SQL을 포함한 검색 p95(20배)를 잰다. 질의 임베딩 시간은 따로 보고한다.

## keep 규칙 (dev, 1·5·20배)

아래를 모두 만족하면 keep이다.

1. 무결성 게이트 전부 통과(벡터 경로 포함).
2. 의미 질의 hit 순증 ≥3.
3. 키워드 질의 비퇴행: 어느 군·규모에서도 hit 순감 ≥2가 없다.
4. 각 규모에서 두 세트의 MRR 하락이 0.02 이하다.
5. 지연: 순위 SQL 포함 검색 p95(20배)가 baseline×1.25 이하다. **3회 측정 모두 통과해야 한다.** 측정 후 판정 방식을 바꾸지 않는다.

keep이 아니면 되돌린다. 모든 시도는 `results.tsv`와 `LOG.md`에 남긴다. 기준점(baseline) 변경은 별도 commit으로 남긴다.

## 승격 (최대 3회)

holdout 판정보다 먼저 독립 subagent 적대적 리뷰를 돌린다. P0/P1이 있으면 holdout을 보지 않고 고친다. 승격은 아래를 모두 만족해야 한다.

1. **합성 holdout 의미 질의:** 질의 단위 paired bootstrap 95% CI 하한 > 0.
2. **합성 holdout 키워드 질의:** 군별 hit 감소 없음. 평균 MRR 하락 ≤0.02.
3. **실문서 holdout**
   - heading 질의: recall 감소 없음, MRR 하락 ≤0.02.
   - 바꿔 말한 질의: 평균 recall 변화 > 0.
4. 무결성 게이트와 기존 관련 테스트 통과(CI 런타임).
5. 적대적 리뷰에서 P0/P1 없음.

통과하면 PR을 만든다(병합하지 않음). PR에는 결과가 "합성·실문서 기준 후보 검색 품질 개선"이고 효익은 #10 trial로 판정한다고 쓴다. dense 경로가 이기면 PR은 측정 근거와 정책 결정 안건이며, 운영 코드 도입은 포함하지 않는다.

## 멈춤

승격 3회가 모두 실패하거나, 시작 후 24시간이 지나거나, 탐색 공간이 소진되면 결과와 사유를 기록하고 멈춘다. 일찍 멈출 때는 그 사실과 이유를 보고한다.
