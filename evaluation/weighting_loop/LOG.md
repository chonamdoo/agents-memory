# 확장 가중치 루프 기록

규칙: `program.md`. 결과 표: `results.tsv`.

## 준비

- `Store.search_lexical(query_tokens=...)`와 `query_terms` CTE를 추가했다. `Application.context`는 질의 토큰을 따로 넘긴다.
- 동작 중립을 확인했다.
  - 원래 순위 SQL로 dev L0를 재면 질의별 결과가 의미 루프 baseline과 완전히 같다(186개 질의 × 3개 규모).
  - 확장 경로 무결성 테스트 6건(`tests/test_retrieval_expansion_weight.py`)이 통과한다. 이 테스트는 확장 단어로만 닿는 기억이 다음 경우 나오지 않음을 확인한다.
    - 철회·삭제
    - 다른 binding
    - 다른 realm
  - 기존 무결성 게이트 44건도 통과한다.
- holdout 확장 v2·v4(138개 질의)를 미리 만들어 동결했다. 실문서 확장(1,182개 질의)은 로컬에만 두고 commit하지 않는다.
  - 생성 agent는 안내문·질의 묶음·출력 파일 세 개만 다뤘다. 도구 호출 기록으로 검증했다.

## 시도

| # | 후보 | 결과 | 메모 |
|---|---|---|---|
