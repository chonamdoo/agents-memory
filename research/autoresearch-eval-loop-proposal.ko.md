# autoresearch식 검색 개선 루프 + 기억 무결성 평가 제안

상태: 제안(미구현). 이 문서의 수치 목표는 **제안값**이며 실측 baseline이 아니다. 실측이 필요한 항목은 `[측정 필요]`로 표시한다.

## 0. 결론

- **가능하다. 단, 루프를 돌릴 대상은 "후보 생성(candidate retrieval) 단계" 하나로 좁혀야 한다.** 이 단계는 LLM 없이 결정적으로 돌아가고, 몇 초 안에 다시 실행할 수 있으며, 측정 결과가 흔들리지 않는다. autoresearch의 `val_bpb`에 해당하는 것을 정확히 만들 수 있는 유일한 층이다.
- **기억 무결성은 최적화 대상이 아니라 절대 게이트(위반 0건)로 둔다.** 삭제·철회·대체된 기억이 되살아나는 경우, 다른 binding/realm의 기억이 섞이는 경우, 근거 span이 틀린 경우는 점수와 맞바꿀 수 없다. 사람이 라벨을 달지 않아도 정답이 기계적으로 정해지는 변형(metamorphic) 테스트로 측정한다.
- **적대적 리뷰는 루프의 매 반복이 아니라 "승격 관문"과 "반례 생성기"로 쓴다.** 리뷰가 측정을 대신할 수는 없다. 리뷰가 잘하는 일은 지표 gaming(Goodhart)과 불변식 우회를 찾는 것, 그리고 새 반례 케이스를 만드는 것이다.
- **벡터 임베딩 arm은 가장 마지막에, 정책 결정을 거친 뒤에 추가한다.** 이 저장소는 로컬 모델 자동 다운로드를 하지 않고 외부 전송을 default-deny로 막는다. 임베딩을 넣으면 둘 중 하나를 깨야 한다. 그 전에 BM25 정규화, 한국어 조사 처리, coding agent가 이미 보낼 수 있는 `query_expansions`로 의미 검색의 상당 부분을 egress 없이 시험할 수 있다.

## 1. 현재 상태 (코드로 확인한 사실)

| 항목 | 실제 구현 | 근거 |
|---|---|---|
| 키워드 검색 | **BM25가 아니다.** claim의 `lexical_tokens`와 질의 토큰의 교집합 **개수**로 순위를 매긴다. IDF도 길이 정규화도 없다 | `src/agents_memory/store.py` `search_lexical`의 `lexical_candidates` CTE |
| 두 번째 arm | 벡터가 아니라 **entity 이름 일치**다 | 같은 함수의 `entity_candidates` |
| 결합 | RRF `sum(1/(60+rank))`, 상위 20개 | 같은 함수의 `fused` |
| 벡터 | schema·설정(`embedding_dimensions=1024`, `full_semantic`)은 있지만 기본 경로인 `agent_judged`의 검색에서는 쓰지 않는다 | `config.py`, `store.py` |
| 토크나이저 | 단어, 코드 식별자, camelCase 조각, **한글 bigram** | `src/agents_memory/lexical.py` |
| 관련성 판단 | 인덱스는 후보만 고른다. 채택 여부는 coding agent가 판단한다 | README 원칙, `application.py`의 `judgment_required` |
| 무결성 필터 | 상태(active), 대체 여부, realm, snapshot, 유효기간, health, 원문 revision 일치를 SQL `eligible` CTE에서 적용 | `store.py` |
| 평가 체계 | 동결 digest, 클러스터 bootstrap(10000회, 95%), precision/recall, grounding 정확 일치, `candidate_recall_at_20`, `condition_omission`, `false_promotion` 진단 | `evaluation_scoring.py`, `evaluation_diagnostics.py`, `recall_evaluation.py` |
| 사람이 만든 gold·실제 trial | **아직 없음** | `docs/requirements.ko.md` U36 등 |

따라서 "BM25+벡터 하이브리드"라는 설명은 현재 코드와 맞지 않는다. 지금 구현은 "토큰 교집합 개수 + entity, RRF 결합"이다.

### 재현된 약점 (이 문서 작성 중 실행)

```text
질의: "결제 재시도 정책 변경"
정답 claim  "결제 재시도는 최대 3회로 제한한다"               → 교집합 3
잡음 claim  "결제 화면 재시도 버튼 정책 문서와 결제 실패 …"   → 교집합 6
```

- **길이 편향과 keyword stuffing.** 긴 claim이 토큰을 많이 가질수록 유리하다. 같은 이유로 poisoning 공격면이 된다.
- **한국어 조사.** `재시도는`이 `재시도`와 정확히 일치하지 않는다. 정답은 bigram(`재시`, `시도`) 덕분에 겨우 걸린다.

이 두 가지가 루프의 첫 실험 후보로 가장 명확하다.

## 2. autoresearch를 그대로 가져올 수 있는 부분과 없는 부분

| autoresearch | 그대로 가져옴 | 바꿔야 함 |
|---|---|---|
| 에이전트가 수정하는 파일 `train.py` 하나 | 수정 범위를 파일 하나로 제한 (`retrieval_candidates` 모듈) | 무결성 필터 SQL은 **반드시 수정 범위 밖**에 둔다 |
| 고정 파일 `prepare.py` (평가 포함) | 평가기·corpus·gold를 동결하고 digest로 고정 (기존 `ScoringProtocol` 활용) | holdout을 따로 봉인해야 한다. gold가 작아서 dev 과적합 위험이 크다 |
| 5분 고정 예산 | 실행 시간 예산 대신 **지연(p95)·후보 bytes 상한**을 제약으로 둔다 | 학습이 아니라 검색이므로 한 번 실행은 수 초 수준 [측정 필요] |
| `val_bpb` 하나 | 주 지표 하나: `eligible_candidate_recall@20` | 게이트(무결성 0건)와 제약을 반드시 함께 둔다 |
| 개선되면 keep, 아니면 discard | 같은 방식, git commit 단위 | dev 개선 + 게이트 통과 + 주기적 holdout 비열등성 확인 |
| `program.md` (사람이 연구 방향 지시) | 동일 | 금지 행위 목록(평가기·필터·gold 수정 금지)을 명시 |

`val_bpb`는 데이터가 크고 결정적이라 gaming이 어렵다. 우리 gold는 작고 사람 라벨은 비싸다. 그래서 **holdout 봉인, 반례 주입, 적대적 리뷰**라는 세 장치가 autoresearch보다 더 필요하다.

## 3. 목표와 수치 (3층 구조)

### 층 A. 무결성 게이트: 절대값, 위반 0건, 맞바꿀 수 없음

사람 라벨 없이 기계적으로 정답이 정해지는 변형 테스트로 측정한다. gold claim `X`가 검색되던 질의 `q`에 대해:

| ID | 변형 | 기대 결과 | 지표 |
|---|---|---|---|
| I1 | `X` 철회(retract) | `q`의 후보에 `X` 없음 | resurrection = 0 |
| I2 | `X`를 `X'`로 대체(supersede) | `X` 없음 (`X'`는 있으면 좋지만 게이트는 아님) | superseded_leak = 0 |
| I3 | 원문 revision 변경·삭제 | 옛 revision에서 나온 `X` 없음 | stale_revision_leak = 0 |
| I4 | 같은 claim을 다른 binding/realm에 삽입 | 다른 쪽 claim이 절대 후보에 없음 | cross_scope_leak = 0 |
| I5 | `valid_until`을 과거로, snapshot 불일치, health 격리 | `X` 없음 | ineligible_leak = 0 |
| I6 | 최종 전달 단계 | grounding 정확 일치가 아닌 span | grounding_errors = 0 (기존 지표) |

I1–I5는 지금 `eligible` CTE가 보장한다. 루프가 이 CTE를 건드리지 못하게 하고, 매 반복마다 이 스위트로 회귀를 확인한다. **하나라도 위반하면 점수와 상관없이 discard한다.**

### 층 B. 최적화 목표: 루프가 올리는 값

- **주 지표:** `eligible_candidate_recall@20`. 기존 `GoldEligibilityWitness`의 eligible gold 중 후보 20개 안에 든 비율이다. 기존 진단 함수에 이미 정의돼 있다.
- **보조 지표 (악화 금지):**
  - `MRR@20`
  - `decoy_displacement`: 케이스마다 keyword-stuffed 미끼 claim k개를 넣은 뒤, 원래 후보에 있던 gold가 밀려난 비율. poisoning 내성을 본다.
  - `korean_morph_recall`: 조사·어미가 붙은 질의 변형만 모은 하위 집합의 recall.
- **제약:** 검색 p95 지연 ≤ baseline × 1.25, 후보 manifest bytes는 늘지 않음 (상한 20개는 고정), 인덱스 크기 ≤ baseline × 1.5. 모두 [측정 필요].

### 층 C. end-to-end 품질: 승격할 때만, 비싸고 잡음이 있음

LLM coding agent가 실제로 관련성을 판단한 결과를 본다. 기존 `score_run`과 `score_retrieval_diagnostics`를 쓴다.

- 최종 precision/recall, `condition_omission`, `false_promotion`, `no_match_false_returns`
- 판정: 클러스터 paired bootstrap 95% CI. recall 개선의 하한 > 0, precision·condition_omission·false_promotion은 비열등(악화 하한이 margin 이내). 기존 `_Thresholds`의 margin=0 정책을 따른다.

후보 recall이 오르면 agent가 판단할 후보가 많아져 판단이 흔들릴 수 있다. 층 C가 이것을 잡는 장치다.

### keep / promote 규칙 (제안값)

| 단계 | 조건 |
|---|---|
| **keep** (매 반복, dev) | 층 A 위반 0 AND 제약 통과 AND dev 주 지표 순증 ≥ 2케이스 AND 보조 지표 악화 없음 |
| **promote** (keep N=5회마다, 또는 주 1회) | holdout 주 지표 paired bootstrap CI 하한 > 0 AND 층 C 비열등 AND 적대적 리뷰에 P0/P1 미해결 0건 |
| **rollback** | promote 실패 시 마지막 promote 지점으로 되돌리고, 실패 원인을 `program.md`에 기록 |

### gold 규모 (제안값)

- dev: ≥150 케이스, ≥30 클러스터
- holdout: ≥100 케이스, ≥20 클러스터 (`P95_MIN_SAMPLES=20`과 맞춤)
- 클러스터는 독립 출처 단위로 나눈다 (기존 `cluster_id` 규칙). holdout은 agent에게 내용과 결과를 모두 보여주지 않고, 집계 통과 여부만 알려준다.

## 4. 루프 구성

```
program.md            (사람)  목표·금지 사항·현재 가설
retrieval_candidates/ (에이전트 수정 가능)  토크나이저 변형, 점수 SQL 조각, arm 가중치, RRF k
eval/ (동결, digest 고정)
  corpus/ gold-dev/ gold-holdout(봉인)/ metamorphic.py / decoys.py / harness.py
results.tsv           commit, dev recall@20, MRR, decoy, p95, 게이트 결과, keep/discard
```

1. 에이전트가 `program.md`와 `results.tsv`를 읽고 가설 하나를 정한다.
2. `retrieval_candidates/`만 수정하고 commit한다.
3. `harness.py`가 fixture PG18(+pgvector)에 동결 corpus를 적재하고 층 A와 층 B를 실행한다. 결정적이다.
4. keep 규칙에 따라 유지하거나 `git reset`으로 되돌린다. 결과를 `results.tsv`에 기록한다.
5. N회마다 promote 관문(holdout, 층 C, 적대적 리뷰)을 실행한다.

**하네스가 강제할 장치** (프롬프트에만 맡기지 않는다):

- `eval/`과 `eligible` CTE 파일의 digest가 바뀌면 실행을 거부한다.
- diff가 허용 경로 밖을 건드리면 실행을 거부한다.
- 하네스는 gold claim ID나 질의 문자열을 출력하지 않고 집계만 출력한다. 질의별 하드코딩을 막기 위해서다.

## 5. 적대적 리뷰를 루프에 넣는 방법

| 역할 | 하는 일 | 빈도 |
|---|---|---|
| Proposer (autoresearch 에이전트) | 가설과 수정, keep/discard | 매 반복 |
| Red team | ① diff에서 gaming 흔적 찾기 (질의 패턴 하드코딩, gold 어휘 주입, 필터 우회, 비결정성). ② **반례 생성**: 미끼 claim, 조사 변형, 동의어, 부정/조건 함정, 언어 혼합(한·영·코드). 정답이 기계적으로 정해지는 것만 자동 편입하고, 나머지는 사람이 라벨을 단 뒤 dev에 넣는다 | promote마다 |
| 독립 리뷰 2인 | 기존 `research/adversarial-review-contract.ko.md` 형식. 동결 입력, 서로 답을 보지 않음, P0/P1/P2 | promote마다 |
| 사람 | 반례 라벨, 리뷰 지적 처분, holdout 관리 | promote마다 |

원칙:

- **Red team이 만든 케이스는 holdout에 넣지 않는다.** 루프가 이미 본 분포의 반례라서 holdout이 오염된다.
- **라벨은 생성자와 분리한다.** Red team이 만든 문제에 Red team이 정답까지 달면 자기 채점이 된다.
- **반복되는 지적은 반례 케이스로 만들어 회귀 테스트로 굳힌다.** 리뷰 결과가 문서에만 남지 않게 하기 위해서다.

## 6. 실험 후보 (권장 순서)

| # | 실험 | 기대 효과 | 수정 범위 | 정책 영향 |
|---|---|---|---|---|
| E1 | 교집합 개수를 BM25로 교체: df 통계 테이블 + 길이 정규화 (SQL 안에서 계산) | 길이 편향과 stuffing 감소 | 점수 SQL, migration 1개 (df 통계) | 없음 |
| E2 | 한국어 조사·어미 제거 (규칙 기반 접미사 목록) 또는 bigram 가중치 조정 | 조사 변형 recall | `lexical.py` + 재색인 | 없음 |
| E3 | RRF k, arm 가중치, arm별 상한 | 결합 균형 | 점수 SQL | 없음 |
| E4 | `query_expansions` 활용 지침과 가중치 (agent가 동의어·영문명을 보냄) | egress 없이 의미 검색 일부 | host 지침 + 점수 SQL | 없음 (agent 자신의 모델 경로) |
| E5 | 벡터 arm (pgvector, 3번째 RRF arm) | paraphrase recall | 색인 worker, schema 이미 있음 | **큼.** 임베딩 모델 위치(로컬 다운로드 금지 원칙, 외부 전송 default-deny)를 정책으로 먼저 결정해야 함 |

E1–E4는 정책 경계를 건드리지 않는다. E5는 E1–E4로 얻은 recall 한계를 층 B로 측정한 뒤, 남은 격차가 의미 검색 부족 때문인지 확인되면 진행한다.

## 7. 영향 범위와 장단점 비교

| 안 | 내용 | 코드 영향 | 보안·정책 영향 | 비용 | 측정 신뢰도 | Goodhart 위험 | 판정 |
|---|---|---|---|---|---|---|---|
| **A** | 후보 생성 단계만 autoresearch + 무결성 게이트 + 승격 시 적대적 리뷰 | `store.py` 점수 SQL, `lexical.py`, 평가 하네스 신설 | 없음 (필터 동결) | 낮음 (LLM 비용은 promote 때만) | 높음 (결정적) | 중간. holdout과 반례 주입으로 억제 | **추천** |
| B | A + 벡터 arm | A + 임베딩 색인·worker·재색인 경로 | **큼.** 임베딩 원문 egress 또는 로컬 모델 배포. 삭제 시 벡터 purge 경로 추가 | 중간 | 높음 | 중간 | E1–E4 이후 조건부 |
| C | end-to-end (LLM 판단 포함)를 매 반복 최적화 | A + host 실행 자동화 | coding agent 실행이 반복됨 | **높음** (반복마다 LLM 호출) | 낮음 (비결정, 분산 큼) | **높음.** 프롬프트·판단 쪽 gaming | 비추천 (층 C는 관문으로만) |
| D | 루프 없이 적대적 리뷰만 반복 | 없음 | 없음 | 중간 | 수치 없음 | 낮음 | 보조 수단. 단독으로는 개선을 증명하지 못함 |

### 안 A의 장점

- 결정적이고 빨라서 autoresearch 방식이 그대로 통한다.
- "인덱스는 후보만, 판단은 agent"라는 기존 원칙을 깨지 않는다. 무결성 필터를 동결하므로 안전 경계가 바뀌지 않는다.
- 기존 평가 코드(`candidate_recall_at_20`, eligibility witness, bootstrap)를 재사용한다.

### 안 A의 단점과 반론

1. **gold가 아직 없다.** 루프의 가장 큰 선행 비용이다. 합성 corpus로 시작하면 실제 분포와 다를 수 있으므로, 실제 trial corpus의 사람 라벨 holdout이 생기기 전에는 "개선"을 합성 범위로만 말한다.
2. **후보 recall이 올라도 최종 품질이 오른다는 보장은 없다.** 그래서 층 C 비열등성을 승격 조건에 넣었다.
3. **lexical 개선이 poisoning 공격면을 키울 수 있다.** `decoy_displacement`를 보조 지표로 둔 이유다. E1(BM25)은 오히려 공격면을 줄일 것으로 예상하지만 [측정 필요].
4. **작은 dev 집합에서 2케이스 순증은 노이즈일 수 있다.** dev keep은 싸게 탐색하는 단계로 보고, 진짜 판정은 holdout bootstrap에 맡긴다.
5. **SQL 점수는 PG 실행계획에 따라 지연이 크게 바뀔 수 있다.** p95 제약과 corpus 규모별(1k/10k/100k claim) 측정을 하네스에 포함한다.

## 8. 단계별 실행 계획과 완료 기준

| 단계 | 산출물 | 완료 기준 |
|---|---|---|
| P0 | 무결성 변형 스위트 (I1–I5)를 현재 코드에 적용 | 현재 baseline에서 위반 0 확인 (위반이 있으면 그 자체가 버그) |
| P1 | 합성 dev/holdout corpus·gold와 동결 하네스, `results.tsv` | baseline 수치 기록. 같은 commit을 3회 실행해 결과가 완전히 같음 |
| P2 | `program.md`, 수정 범위 강제, 루프 1차 (E1–E3) | keep 규칙으로 개선 commit 확보 또는 "개선 없음" 기록 |
| P3 | 승격 관문: holdout, 층 C, 독립 리뷰 2인 | 관문 통과분만 PR |
| P4 | 실제 trial corpus의 사람 라벨 holdout | 합성에서 얻은 개선이 실데이터에서 비열등 |
| P5 (조건부) | 벡터 arm 정책 결정 → E5 | 정책 승인 + 층 A·B·C 통과 |

## 9. 한계

- baseline 수치는 측정하지 않았다. PG18 fixture를 이용한 실행은 P1의 범위다.
- 1절의 약점 재현은 토큰 교집합 개수를 Python으로 계산한 것이다. 실제 SQL 순위(동점 처리, entity arm, RRF)까지 포함한 결과는 아니다.
- autoresearch 저장소는 README 수준에서만 확인했다. keep 조건의 세부(`program.md`)는 확인하지 못했다.
- 이 제안 자체는 아직 독립 적대적 리뷰를 받지 않았다.
