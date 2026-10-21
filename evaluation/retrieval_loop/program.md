# 검색 후보 단계 개선 루프 (program.md)

이 파일의 "규칙" 절은 동결 대상이다. 바꾸면 하네스가 실행을 거부한다. 진행 기록은 `LOG.md`에 남긴다.

## 목표

후보 검색 단계(`Store.search_lexical`가 반환하는 최대 20개)에서 정답 claim의 회수를 늘린다. 무결성은 그대로 지킨다. 결과는 "합성 기준 후보 검색 품질 개선"이다. memory-on/off 효익은 #10 trial로 판정한다.

## 고정된 결정 (변경 금지)

- **기존 합격선을 동결한다.**
  - Recall@20, feasible coverage, agent-selected Precision@3: 각각 ≥90%
  - 의미 보존 ≥95%, critical fixture 100%
  - no-match 오반환과 false-empty: 각각 ≤5%
  - off/on 성공률: 각각 ≥80%, 성공률 차이의 CI 하한 ≥0
  - 조건 누락, 근거 오류, false promotion: 비증가
  - 루프 시작 후에는 바꾸지 않는다.
- **#10 trial용 사람 gold 120개는 절대 보지 않는다.**
- **브랜치는 `claude/quirky-fermat-m0ogfo`만 쓴다.** main에 직접 push하지 않고, 병합하지 않는다.

## 규칙

1. **수정 허용 파일은 두 개뿐이다.** `src/agents_memory/retrieval_ranking.py`(순위 SQL)와 `src/agents_memory/lexical.py`(토크나이저). 나머지는 `frozen.json`의 digest로 고정된다. 고정 대상에는 `store.py`의 eligible CTE, corpus, 정책서 로더, 하네스, `tests/test_retrieval_integrity.py`가 모두 포함된다.
2. **한 반복에는 가설 하나만 시험한다.** 허용 파일만 고친 뒤 `harness.py run --record --label "<가설>"`을 실행한다.
3. **keep 조건**은 아래를 모두 만족하는 것이다. dev 기준이고 규모는 1배·5배·20배 모두 본다.
   - 무결성 테스트 전부 통과
   - 20배 규모 지연 p95 ≤ baseline×1.25
   - 채점 군(G1–G7, G9)의 정답 hit 순증 ≥2
   - 어느 군·규모에서도 hit 순감 ≥2 없음
   - 각 규모의 MRR 하락 ≤0.02
   - 5배 규모 G8 평균 반환 수 증가 ≤1

   keep이면 commit하고 baseline을 갱신한다(`run --baseline`). 아니면 `git checkout`으로 되돌린다.
4. **모든 시도를 기록한다.** 실패한 시도도 `results.tsv`와 `LOG.md`에 남긴다.
5. **holdout과 실문서 holdout은 튜닝에 쓰지 않는다.** 질의별 결과도 보지 않는다. 하네스는 두 세트의 집계만 출력한다. 질의별 진단(`--details`)은 dev만 허용한다.
6. **실문서(사만다 정책서) 원문은 commit, PR, 리뷰 입력 어디에도 넣지 않는다.** `AM_LOOP_POLICY_DIR` 로컬 경로에서만 읽는다. 원본 zip은 `/root/.claude/uploads/826825cb-77e6-57bf-bf50-534a12e24a3f/`에 있다. 컨테이너가 재시작되면 scratchpad에 다시 푼다.
7. **dense(벡터) 비교군은 오프라인 측정만 한다.** 운영 코드에는 도입하지 않는다.
8. **탐색 순서는 다음과 같다.** entity arm 동점 처리 → BM25(IDF, 길이 정규화) → 한국어 조사 처리 → RRF k와 arm 가중치.
9. **승격은 최대 3회 시도한다**(`harness.py promote`). 통과 조건은 아래를 모두 만족하는 것이다.
   - 합성 holdout: 질의 단위 paired bootstrap 95% CI 하한 > 0, 어느 군·규모도 hit 감소 없음
   - 실문서 holdout: 퇴행 없음(평균 변화 ≥0, 어느 군도 hit 감소 없음)
   - 무결성 테스트와 기존 관련 테스트 통과
   - 독립 subagent 적대적 리뷰(gaming, 필터 우회, 비결정성 점검)에서 P0/P1 없음

   통과하면 루프를 멈추고 PR을 생성한다(병합하지 않음). 실패하면 마지막 승격 지점으로 되돌리고 계속한다.
10. **멈춤 조건:** 승격 3회가 모두 실패하거나 시작 후 24시간이 지나면 "개선 없음"으로 기록하고 멈춘다.
11. **단계마다 commit과 push를 한다.** 턴이 끝날 때마다 `send_later`로 다음 재개를 예약한다.
