# 루프 진행 기록

규칙은 `program.md`를 따른다. 각 시도는 `results.tsv`에도 한 줄씩 남는다.

## 준비 (2026-10-20)

- 순위 SQL을 `src/agents_memory/retrieval_ranking.py`로 분리했다. 동작은 바꾸지 않았다(기존 PG 테스트와 무결성 테스트 통과).
- corpus를 작성했다.
  - 합성 dev: 질의 102개, core claim 56개
  - 합성 holdout: 질의 80개, core claim 42개
  - 배경 claim: 1배·5배·20배
- 실문서 holdout(로컬 전용, 원문 미commit): claim 437개, 질의 1,062개
  - PT 690개, PI 345개, G6 27개
- 서버의 근거 검증(숫자·식별자는 원문에 있어야 함)에 맞게 corpus 필드를 조정했다.
  - 합성: 점으로 이어진 식별자는 원문 그대로 쓴다.
  - 정책서: 섹션 heading을 본문에 포함한다.
- 하네스가 토크나이저 변경 시 전체를 다시 적재하지 않고, 저장된 `lexical_tokens`만 다시 계산하도록 했다(재색인과 동일).
