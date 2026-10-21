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

## baseline (2e236ce)

- dev recall@20: 1배 0.927 (97/104), 5배 0.906 (95/104), 20배 0.885 (93/104). MRR(5배) 0.608. p95(20배) 123ms.
- holdout(집계): 1배 0.921, 5배 0.921, 20배 0.895. 실문서(집계): recall 1.000, MRR 0.960.
- 같은 commit을 3회 측정한 질의별 결과가 동일하다.
- dev 미회수 원인:
  - G3에서 expansion 없는 한영 질의 6건. lexical로는 풀 수 없다.
  - 20배 crowding: 공통 어휘 동점이 id 순서로 갈린다.
  - entity arm: 배경 claim 전부가 `pay-core` entity를 가진다.

## 시도

| # | 가설 | 결과 | 이유 |
|---|---|---|---|
| H1 | entity arm 동점을 lexical 겹침 수로 깸 | discard | hit 285→285. MRR(5배) 0.608→0.617 |
| H2 | lexical arm을 BM25(IDF, 길이 정규화, tf=1)로 교체 | discard | hit 285→284. MRR(5배) 0.608→0.647. `API 문서 언어`(5배), `pay-core 배포 TLS`(20배) 이탈, `금욜 배포`(20배) 회수 |
| H3 | pool 상한보다 많은 claim이 공유하는 entity는 entity arm에서 제외 | discard | hit 285→285. MRR(5배) 0.608→0.722 |
| H4 | H3 + BM25 | discard | hit 285→285. MRR(5배) 0.608→0.772. 20배 `금욜 배포` 1위 회수, 5배 `API 문서 언어` 이탈 (정답과 배경 claim이 같은 토큰만 공유하고, baseline에서도 id 순서 운으로 18위였음) |
| H5 | H4 + 한글 자모 3-gram 토큰 (`lexical.py`) | discard | hit 285→292 (5배 95→98, 20배 93→97). MRR 0.80. 그러나 G8 평균 반환 3.83→11.67, p95 123→233ms |
| H6 | H5 + lexical arm은 단어 토큰이 하나 이상 맞아야 진입 (자모는 점수만) | discard | hit 285→290. G8 3.83 (baseline 수준). p95 123→774ms (행마다 배열을 재계산한 것으로 추정) |
| H6b | H6에서 단어 토큰 배열을 CTE로 한 번만 계산 | discard | hit 동일(290), p95 766ms. 실행 계획상 원인은 corpus_stats가 행마다 재계산되는 것(517회) |
| H6c | H6b + 통계 CTE를 MATERIALIZED로 고정 | discard | hit 동일(290), p95 219ms (한도 154ms) |
| H6d | H6c + 문서 빈도를 unnest 한 번으로 계산 | discard | hit 동일(290), p95 167ms (한도 154ms). SQL 밖의 고정 비용이 약 70ms라, 순위 SQL은 약 80ms 이내여야 함 |
| H6e | H6d + BM25 점수 계산을 claim 토큰 unnest와 hash join으로 처리 | **keep** | hit 285→290 (1배 97, 5배 95→97, 20배 93→96). MRR(5배) 0.608→0.797. p95(20배) 123→137ms. G8 반환 3.83(동일). 무결성 통과 |

### H6e keep 후 추가 확인

- `lexical.py`의 토크나이저는 rejection 후보와 관계 판단 후보 검색에도 쓰인다. 그래서 관련 테스트를 따로 돌렸다.
  - lexical, rejection, relation, store, company, source judgment 테스트: 245건 통과
  - `test_auto_recall.py` 14건은 이 컨테이너의 SQLite 3.45.1이 spool 요구 버전보다 낮아 실패한다. 변경 전 코드에서도 같은 14건이 실패한다.
  - CI와 같은 런타임(uv 0.13.0, managed Python 3.13.16, SQLite 3.53.1) venv에서 auto_recall, recall_gateway, health_backend 94건이 모두 통과했다.
- 승격 관문(`promote`)은 이 CI 런타임 venv의 Python으로 실행한다.

**현재 keep 지점: H6e.** BM25(IDF, 길이 정규화), 공유가 과도한 entity 제외, 한글 자모 3-gram은 점수만 더하고 진입은 단어 토큰이 맞아야 함.

## 1차 승격 시도 (H6e, c4059b7): 실패

- 무결성 테스트 15건 통과. 관련 테스트 282건 통과(CI 런타임).
- 합성 holdout(집계): 평균 +0.026, 95% CI [0.000, 0.066]. CI 하한이 0을 넘지 못해 미달.
- 실문서 holdout(집계): 평균 −0.0009, 군 하나에서 hit 감소. 퇴행.
- 독립 subagent 적대적 리뷰: P1 2건, P2 7건.
  - F1(P1): `~` 접두사가 한글보다 앞에 정렬된다. 그래서 health 감사 경로의 `sorted(tokens)[:2048]`가 한글 단어 토큰을 잘라낸다.
  - F3(P1): 저장된 `lexical_tokens`의 재색인 경로가 없다. 운영 상태가 측정 상태와 다르다.
  - P2: 2048 상한을 자모가 먼저 차지함, rejection 16토큰 슬롯, 문서 빈도 전체 스캔, float 동점, 상한에 따라 바뀌는 entity 기준, `$6` 확대, 탐색 순서 위반.
- 처리: 마지막 승격 지점(원래 baseline, 2e236ce)으로 순위 코드, 토크나이저, dev baseline을 되돌렸다.
| H7 | 원래 baseline 기준. 순위 SQL 안에서 질의 시점 자모 fuzzy + BM25 + 공유 과도 entity 제외(상수 20) + 점수 반올림 + 문서 빈도를 `&&`로 선필터. `lexical.py` 변경 없음 | discard | hit 285→289. MRR(5배) 0.789. p95 171ms (한도 154ms) |
| H7b | H7 + 질의 단어와 음절을 공유하는 claim 단어만 자모 분해(결과 동일), (claim, 단어) 대응은 fuzzy 단어에 대해서만 생성 | **keep** | hit 285→289 (5배 95→96, 20배 93→96). MRR(5배) 0.608→0.789. p95 123→134ms. G8 3.83(동일). 무결성 통과. 5배 `API 문서 언어`는 이탈(baseline에서도 id 순서 운으로 18위) |

**현재 keep 지점: H7b.** `lexical.py`를 바꾸지 않으므로 1차 리뷰의 F1–F4와 F8은 해당 없음. F5(문서 빈도 선필터), F6(점수 반올림), F7(entity 기준 상수 20)을 반영했다. F9(탐색 순서): 한국어 조사 처리는 자모 fuzzy가 조사 변형도 덮는 방식으로 대체했다. 조사 목록 기반 처리는 시도하지 않았다.
