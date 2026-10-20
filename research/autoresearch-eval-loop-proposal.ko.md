# autoresearch식 검색 개선 루프 + 기억 무결성 평가 제안

상태: 제안(미구현, 미리뷰).

- 이미 정해진 합격선은 기존 #5 §5와 `docs/architecture.ko.md`(기록과 판정)를 그대로 쓴다. 이 문서는 새 합격선을 만들지 않는다.
- 새로 두는 수치(루프의 keep 규칙, dev gold 규모 등)는 **제안값**이다.
- 실측이 필요한 항목은 `[측정 필요]`로 표시한다.

## 0. 결론

1. **autoresearch 루프는 쓸 수 있다. 다만 대상은 "후보 생성(candidate index)" 한 층으로 좁힌다.** 이 층은 LLM 없이 결정적으로 돌고, 다시 돌리는 비용이 싸며, 결과가 흔들리지 않는다. autoresearch의 `val_bpb`에 해당하는 지표를 정직하게 만들 수 있는 유일한 층이다.
2. **이 루프는 새 방향이 아니다.** 2026-10-15 임베딩 리뷰(#5 댓글 6191076557)는 이렇게 결론냈다. "bge-m3 기본 채택 없이, production 변경 없는 **오프라인 비교 평가만**" 하고 비교군은 6개로 한다. 루프는 이 오프라인 비교를 자동으로 반복 실행하는 장치다.
3. **기억 무결성은 최적화하지 않는다. 위반 0건이 조건인 게이트다.** 측정은 변형(metamorphic) 테스트로 한다. 원본에 변형을 가하면 정답이 기계적으로 정해지므로 사람 라벨이 필요 없다. 이는 architecture의 "즉시 중단" 사건 목록과 같다: realm 누출, 철회 부활 등.
4. **적대적 리뷰는 매 반복마다 돌리지 않는다.** 쓰는 곳은 두 군데다. 하나는 승격 관문, 다른 하나는 반례 생성기다. 기존 관행(Opus·Codex 독립 병렬, read-only, 원문 보존)을 그대로 쓴다.
5. **"BM25+벡터" 대 "토큰 교집합+entity"는 어느 한쪽이 이기는 문제가 아니다.** 작업 유형마다 실패 원인이 다르다(§3). 코드 작업, 문서 작업, 동시 다발 작업을 각각 dev/holdout의 층(군)으로 나눠 따로 측정해야 한다.
6. **#10 trial을 대체하지 않는다.** 루프의 결과는 "후보 누락 진단" 수준의 엔지니어링 증거다. architecture §349의 정의와 같다. memory-on/off 효익의 증거가 아니다.

## 1. 현재 구조가 이렇게 된 이유 (이력)

| 시점 | 결정 | 근거 |
|---|---|---|
| 초기 (#3 계획) | 두 경로가 있었다. 개인은 `full_semantic`(로컬 Qwen 추출, BGE-M3 벡터, BGE reranker), 회사는 `lexical_entity`. 후보는 "`text[]` GIN overlap + entity exact + vector RRF, pool 20 → cross-encoder → final 3" | #5 댓글 6149015598 |
| 2026-10-12 | 회사에는 로컬 ML을 두지 않는다. "Qwen뿐 아니라 BGE 임베딩/reranker도 설치 불가인 회사". 회사 검색은 "모델 없는 경로"로 정했다. **BM25는 예시로만 언급됐고 채택되지 않았다** | 6149008264, 6149011851 |
| 2026-10-12 | lexical arm의 구현 형태를 정했다. "PG `text[]` GIN token overlap과 entity exact matching이다. `tsvector` FTS가 아니다" | 6149011851, `docs/research/2026-10-13-company-final-proposal.ko.md:13` |
| 2026-10-14 | 사용자 확정: Qwen을 제거하고, 판단은 현재 coding agent가 MCP로 한다. "lexical/entity 검색은 후보를 찾는 색인일 뿐 판단 주체나 기본값이 아니다". 개인과 회사 모두 `agent_judged` 하나로 통일했다. 서버의 embedding·rerank 실행 경로도 함께 제거됐다 | 6150124320, PR #6, migration `0006_agent_judged` |
| 2026-10-15 | 임베딩 재도입 리뷰. bge-m3를 기본으로 채택하지 않는다. 대신 오프라인으로 6개 비교군을 평가한다: 현행(+expansion) / expansion 제외 / lexical 개선 / dense-only / 현행+dense / 개선 lexical+dense. 지표는 기존 정답 손실, p95, RSS, 재색인 비용. **"IDF/길이 정규화가 없다는 사실만으로 현재 순위를 제품 버그라고 확정하지 않는다"** | 6191076557 |
| 2026-10-19 | opt-in fork recall(#17 → PR #21). 메인 컨텍스트가 누적되는 주원인은 inspect 잔여였다. 수락 조건은 gold 기반 비열위. 측정 결과 기록은 없다 | #17 |
| 열림 | #10 trial `not_started`. 원래 acceptance 18개 중 닫힌 것 0개. 사람 gold 120개 없음 | #10, 6229907743 |

정리하면 이렇다.

- 하이브리드(BM25 계열 + 벡터)는 **성능 실측에서 져서 빠진 것이 아니다.** 설치 제약(회사 no-local-ML)과 "판단은 agent"라는 결정 때문에 빠졌다.
- 그 결과 lexical arm에는 IDF와 길이 정규화가 없다. 이것이 결함인지는 **아직 측정되지 않았다.**
- 이 루프가 메우려는 빈칸이 바로 이것이다.

### 지켜야 할 기존 원칙 (루프가 바꾸면 안 되는 것)

- 서버 lexical 순위로 relevance를 정하지 않는다. 관련성은 항상 coding agent가 판단한다.
- 로컬 모델 자동 다운로드는 하지 않는다. 외부 전송(egress)은 default-deny이고, 자동 fallback은 없다.
- 실행 후 threshold나 표본을 유리하게 바꾸지 않는다.
- 다음 상한은 계약이다: 후보 ≤20, manifest ≤16KB, 최종 기본 3개 / 2,400B, lineage ≤128 sources.

## 2. 현재 검색의 실제 동작 (코드 확인)

- **lexical arm:** claim의 `lexical_tokens`와 질의 토큰의 교집합 **개수**로 순위를 매긴다(`store.py` `search_lexical`).
- **entity arm:** claim에 붙은 entity 이름과의 정확 일치 개수로 순위를 매긴다.
- **결합:** RRF `1/(60+rank)`로 합치고 상위 20개를 고른다.
- **토큰:** 원문, NFKC, casefold, 코드 식별자와 camel/snake 분해, 한글 bigram(`lexical.py`).
- **eligibility 필터:** active 상태, 대체되지 않음, realm, snapshot, 유효기간, health, 원문 revision 일치, code workspace 범위. SQL `eligible` CTE에 있다.
- **coding agent의 `query_expansions`:** 최대 8개까지 질의에 함께 토큰화된다(`domain.py`). egress 없이 의미 검색의 일부를 대신할 수 있는 통로다.

### 이 문서 작성 중 확인한 관찰 (작은 합성 예시, 근거가 아닌 원리 설명용)

claim 9개와 질의 6개로 코드, 문서, 인프라 작업을 섞은 corpus를 만들었다. 순위는 교집합 개수와 같은 토큰 위에서 계산한 BM25로 비교했다.

| 관찰 | 교집합 개수 | BM25 | 해석 |
|---|---|---|---|
| 키워드를 반복해 넣은 긴 회의록 claim | 1위 (잡음) | 2위로 하락 | 길이 정규화와 IDF가 stuffing을 줄인다 |
| `재시도는` 같은 조사 결합 | 정답 3위 | 정답 3위 | **순위 공식으로는 해결되지 않는다.** 토큰화 문제다 |
| 대체 표시가 없는 구버전 claim ("5회였다") | 2위 | **1위** | **어떤 순위 공식으로도 해결되지 않는다.** 무결성(supersede) 문제다 |
| `release tag 서명` → 영문 "signed tag" | 1위 (영문 토큰 덕분) | 1위 | 한영 교차 동의어는 lexical로 잡을 수 없다. 벡터나 agent expansion이 필요하다 |

규모가 작아 MRR은 두 방식 모두 0.89로 같았다. **효과 크기를 말하는 근거가 아니다.** 실패 원인이 세 갈래라는 점을 보여주는 예시다: 순위 공식, 토큰화, 무결성.

## 3. 작업 유형별 시나리오: 어떤 방식이 어디서 깨지는가

사용자는 개발뿐 아니라 문서 등 다양한 작업을 **동시에 여러 개** 돌릴 계획이다. 이 경우 전체 평균 지표 하나로는 판정할 수 없다. 기존 holdout 설계의 "10군 × 12개 이상"을 아래 작업 유형 층으로 채울 것을 제안한다.

| 군 | 시나리오 | 교집합+entity (현행) | BM25 | 벡터 | agent `query_expansions` | 범위/무결성 장치 |
|---|---|---|---|---|---|---|
| G1 | 코드 식별자 정확 조회 (`PaymentRetryPolicy.maxAttempts`) | **강함** (식별자 분해) | 강함 | 약함 (식별자 의미 희석) | 보조 | — |
| G2 | 한국어 산문 + 조사·어미 변형 | 약함 (bigram에 의존) | 약함 (토큰화가 같으므로) | 강함 | 중간 (agent가 원형을 함께 보내면) | — |
| G3 | 한영 혼용·동의어 ("서명" ↔ "signed") | 약함 | 약함 | **강함** (다국어 모델일 때) | 중간 | — |
| G4 | 긴 문서 claim (회의록, 설계 문서 요약) | **약함** (길이 편향) | 강함 (길이 정규화) | 중간 | — | claim 크기 상한 |
| G5 | 동시 다발 작업, 같은 프로젝트 공통 어휘 (프로젝트명, "정리했다") | **약함** (공통 토큰이 같은 가중치를 받아 상위 20 밀림) | 강함 (IDF) | 중간 (주제가 비슷하면 군집) | 중간 | **task 범위가 없다** (아래 참고) |
| G6 | 같은 작업의 신구 버전 (정책 변경 전과 후) | 구분 못 함 | 구분 못 함 | 구분 못 함 (오히려 둘을 비슷하게 봄) | — | **supersede/retract가 유일한 해결책** |
| G7 | 부정·조건·예외 ("X 단, Y이면 제외") | 회수는 됨 | 회수는 됨 | 회수는 됨 (부정에 둔감) | — | 최종 단계 `condition_omission` |
| G8 | no-match (관련 기억 없음) | 공통 토큰으로 잡음을 반환 | 점수가 낮아도 반환 | **항상 근접 이웃을 반환** | — | agent 판단, `no_match_false_returns` |
| G9 | poisoning, keyword stuffing | **취약** | 덜 취약 | union 검색에서 취약 (MemoryGraft: lexical+vector union poison 47.9%, `papers.ko.md:72`) | — | `decoy_displacement` |
| G10 | 다른 binding/realm, 삭제된 원문 | — | — | — | — | `eligible` CTE (절대 게이트) |

### 동시 다발 작업에 관한 구조적 사실

- **기억 블록 7종 중 일부가 없다.** 영상 자료의 7종(프로젝트, 태스크, 클레임, 소스, 이벤트, 엔티티, 아티팩트)과 비교하면 이렇다.
  - 있음: 프로젝트(`am_bindings`), 클레임, 소스, 엔티티(claim에 딸린 이름)
  - 없음: 태스크, 아티팩트. 이벤트는 `event_time`, `valid_*` 필드뿐이다.
  - 아티팩트에 가까운 것은 코드 workspace 링크(`am_code_links`)뿐이다.
- **같은 프로젝트 안에서 동시에 도는 작업들은 하나의 후보 pool을 공유한다.** 분리되는 것은 code workspace에 연결된 claim뿐이다. 문서 작업 기억처럼 코드에 연결되지 않은 claim은 모든 작업이 공유한다.
- **task 범위를 새로 만드는 것은 기존 결정과 충돌한다.** 두 리뷰 모델 모두 task 상태 테이블을 반대했다. 대안인 외부 `task_ref` label과 artifact-lite 앵커(P10)는 "trial 후" 항목이다(`local-concurrency-observer-design.ko.md:241-248`). 그래서 이 루프에서는 **task 범위를 만들지 않고, G5 군에서 공통 어휘 때문에 정답이 밀려나는 현상(crowding)을 측정만 한다.** 측정 결과가 P10과 task_ref 재검토의 근거가 된다.
- **비git 문서 작업은 기록 자체가 되지 않을 수 있다.** 전역 설치 제안(#22, open)은 "git 저장소가 아닌 곳은 기록하지 않는다"이다. 문서 작업 비중이 크다면 #22에서 따로 결정해야 한다. 이것은 검색 문제가 아니라 capture 범위의 문제다.
- **동시성 부하는 검색 순위 밖의 문제다.** 기존에 지적된 결함이 있다: `am_clock` 전역 직렬화, 세션 64개 초과 시 고착. 이것은 별도 부하 측정 대상이다. 루프의 p95 제약은 단일 질의 지연만 본다.

## 4. 목표와 수치

### 층 A. 무결성 게이트: 위반 0건, 다른 지표와 맞바꿀 수 없음

architecture "즉시 중단" 목록의 검색 쪽 부분을 변형 테스트로 만든다. gold claim `X`가 회수되던 질의 `q`에 대해 다음을 확인한다.

| ID | 변형 | 기대 결과 |
|---|---|---|
| I1 | `X` 철회(retract) | `q`의 후보에 `X`가 없다 (철회 부활 0) |
| I2 | `X`를 `X'`로 대체(supersede) | `X`가 없다 |
| I3 | 원문 revision 변경 또는 삭제 | 옛 revision에서 나온 `X`가 없다 |
| I4 | 같은 문장을 다른 binding/realm에 삽입 | 다른 쪽 claim이 후보에 절대 없다 (realm 누출 0) |
| I5 | `valid_until`을 과거로, snapshot 불일치, health 격리, 다른 code workspace | `X`가 없다 |
| I6 | 벡터 arm을 도입하는 경우 | 위 I1–I5를 벡터 인덱스에도 적용한다. 근사 인덱스와 scope 필터가 겹쳐 결과가 조용히 비는 현상(false-empty, Opus F9)도 확인한다 |

I1–I5는 현재 `eligible` CTE가 보장한다. 루프는 이 CTE를 수정할 수 없다. 매 반복마다 위 스위트로 회귀를 확인하고, **위반이 하나라도 있으면 점수와 무관하게 discard한다.**

### 층 B. 루프가 올리는 값 (후보 단계, 결정적)

- **주 지표:** `candidate_recall@20`. eligible gold 중 후보 20개 안에 든 비율이다. 기존 진단 함수에 정의돼 있고, 지금은 `unavailable_metrics`에 들어 있다.
  - 목표선은 기존 end-to-end Recall@20 ≥90%를 **후보 단계의 하한**으로 쓴다. 후보에서 빠진 gold는 agent가 결코 고를 수 없기 때문이다.
- **군별 하한:** 위 10군 각각에서 baseline보다 나빠지면 안 된다. 평균이 올라도 한 군이 무너지면 discard한다. 동시 다발 작업 환경에서 가장 중요한 규칙이다.
- **보조 지표 (악화 금지):**
  - `MRR@20`
  - `decoy_displacement`: 미끼 claim k개를 넣은 뒤 원래 후보에 있던 gold가 밀려난 비율
  - `crowding_loss`: G5에서 동시 작업 claim을 N배로 늘렸을 때의 recall 하락
  - no-match 질의의 반환 건수
- **제약:**
  - 기존 목표 p95 recall ≤5초 안에서 단일 질의 검색 p95 ≤ baseline × 1.25 [측정 필요]
  - manifest ≤16KB, 후보 ≤20 (계약이므로 고정)
  - 벡터 비교군은 RSS와 재색인 비용을 함께 기록한다 (6191076557의 지표)

### 층 C. end-to-end (승격할 때만)

기존 합격선을 그대로 쓴다. 다음 지표를 클러스터 paired bootstrap 95% CI로 판정한다.

- Recall@20, feasible coverage, agent-selected Precision@3: 각각 ≥90%
- 의미 보존 ≥95%, critical fixture 100%
- no-match 오반환과 false-empty: 각각 ≤5%
- 조건 누락, 근거 오류, false promotion: 비증가

후보 recall이 오르면 agent가 판단할 잡음도 늘 수 있다. 층 C는 이 부작용을 잡는 장치다.

> 주의: 이 합격선은 `full_semantic` + reranker 시기에 정했고, `agent_judged`로 바뀐 뒤에도 재산정 기록 없이 이어졌다. **루프를 시작하기 전에 그대로 동결할지 재산정할지를 사람이 결정해야 한다.** 실행 후에 바꾸는 것은 금지다.

### keep / promote 규칙 (제안값)

| 단계 | 조건 |
|---|---|
| **keep** (매 반복, dev) | 층 A 위반 0 AND 제약 통과 AND 주 지표 순증 ≥2 케이스 AND 어느 군도 baseline 미만이 아님 AND 보조 지표 악화 없음 |
| **promote** (keep 5회마다) | dev와 분리된 holdout에서 `candidate_recall@20` paired bootstrap CI 하한 > 0 AND 층 C 비열위 AND 독립 리뷰 2인의 P0/P1 미해결 0 |
| **rollback** | promote에 실패하면 마지막 promote 지점으로 되돌리고, 원인을 `program.md`에 기록한다 |

### gold

- **#10 trial용 사람 gold holdout(120개)은 루프가 절대 보지 않는다.** 보면 trial이 오염된다.
- 루프용 dev gold는 별도로 둔다. 합성 + 공개 자료로 만들고 회사·고객 자료는 제외한다. 10군 × 15개 이상, 클러스터 ≥30 (제안값).
- 루프용 내부 holdout은 10군 × 10개 이상 (제안값). 내용과 질의 문자열은 agent에게 보이지 않고 집계만 보인다.
- 기존 원칙대로 모델끼리 합의한 것은 gold로 보지 않는다. 라벨은 사람이 단다. 단, 변형 테스트처럼 정답이 기계적으로 정해지는 경우는 예외다.

## 5. 루프 구성

```
program.md            (사람)  목표, 금지 사항, 현재 가설, 실패 기록
retrieval_candidates/ (에이전트 수정 가능)
  tokenizer 변형 (조사 처리, n-gram 길이), 점수 SQL 조각 (overlap/BM25), arm 가중치, RRF k
eval/ (동결, digest 고정. 기존 ScoringProtocol의 digest 체계 재사용)
  corpus/ gold-dev/ gold-internal-holdout(봉인)/ metamorphic.py / decoys.py / crowding.py / harness.py
results.tsv           commit, 군별 recall@20, MRR, decoy, crowding, p95, 게이트, keep/discard
```

**하네스가 강제할 장치** (프롬프트에만 맡기지 않는다):

1. `eval/`과 `eligible` CTE의 digest가 바뀌면 실행을 거부한다.
2. diff가 허용 경로 밖을 건드리면 실행을 거부한다.
3. 하네스는 gold ID와 질의 문자열을 출력하지 않고 집계만 출력한다. 질의 하드코딩으로 점수를 올리는 것을 막는다.
4. 같은 commit을 반복 실행하면 결과가 완전히 같아야 한다. 결정성을 검사한다.
5. 실행 단위마다 run identity를 동결한다: source, corpus, gold digest, seed. architecture "평가 기록의 무결성" 절과 같은 규칙이다.

### 6개 비교군 (6191076557)을 루프에 대응시키기

| 비교군 | 루프에서의 위치 | 정책 영향 |
|---|---|---|
| 현행 (+expansion) | baseline | 없음 |
| expansion 제외 | 진단 (agent expansion의 기여도 측정) | 없음 |
| lexical 개선 | **루프 1단계의 탐색 공간**: BM25(df 통계와 길이 정규화를 SQL로), 한국어 조사 처리, RRF k, arm 가중치 | 없음. df 통계용 migration 하나 필요 |
| dense-only | 오프라인 측정만 | 측정용 모델은 오프라인 평가 환경에만 둔다. production 배포와는 무관하다 |
| 현행 + dense | 오프라인 측정만 | 같음 |
| 개선 lexical + dense | 오프라인 측정만 | 같음 |

dense 비교군에서 G2/G3의 남은 격차가 클 때만 벡터 도입을 **정책 결정 안건**으로 올린다. 그 전에 결정해야 할 것이 있다.

- 임베딩 모델을 어디에 둘지 (회사 no-local-ML 원칙, 다운로드 금지)
- 외부 임베딩 API를 쓸지 (egress default-deny)
- 삭제된 기억을 벡터 인덱스에서도 지우는 경로(purge)
- 임베딩 계산을 `am_clock` 전역 lock 밖에 둘지 (6191076557에서 기각된 안)

## 6. 적대적 리뷰를 결합하는 방식

| 역할 | 하는 일 | 빈도 |
|---|---|---|
| Proposer (루프 agent) | 가설 세우기, 수정, keep/discard 판정 | 매 반복 |
| Red team | ① diff에서 gaming 흔적 찾기: 질의 패턴 하드코딩, gold 어휘 주입, 필터 우회, 비결정성. ② 반례 생성: 미끼, 조사 변형, 한영 동의어, 신구 버전, 부정·조건 함정, 공통 어휘 군집 | promote마다 |
| 독립 리뷰 2인 | 기존 관행: Opus 5.5와 Codex 6.1 Sol을 xhigh로 병렬 실행, read-only, 서로의 답을 보지 않음, 원문 보존, P0/P1/P2 분류 | promote마다 |
| 사람 | 반례에 라벨 달기, 지적 처분, holdout 관리, 합격선 동결 결정 | promote마다 |

원칙:

- **Red team이 만든 케이스는 dev에만 넣는다.** holdout에 넣으면 루프가 이미 본 분포가 섞여 오염된다.
- **생성과 라벨을 분리한다.** 변형 테스트처럼 정답이 기계적으로 정해지는 케이스만 자동으로 편입하고, 나머지는 사람이 라벨을 단다.
- **리뷰 지적은 문서로 끝내지 않는다.** 반례 케이스나 게이트로 만들어 다음 반복부터 자동으로 검사되게 한다.
- **적대적 리뷰의 한계를 인정한다.** 리뷰는 "왜 이 점수가 오를 수 있었는가"를 의심하는 장치다. "점수가 올랐다"는 사실은 하네스가 증명한다.

## 7. 영향 범위와 장단점 비교

| 안 | 내용 | 코드 영향 | 정책·보안 영향 | 비용 | 측정 신뢰도 | Goodhart 위험 | 판정 |
|---|---|---|---|---|---|---|---|
| **A** | 후보 단계 루프 (lexical 개선) + 무결성 게이트 + 군별 하한 + 승격 시 리뷰 | `search_lexical`의 점수 SQL, `lexical.py`, df 통계 migration, `eval/` 신설 | 없음. eligibility 동결, egress 없음 | 낮음. LLM은 promote 때만 | 높음 (결정적) | 중간. 봉인 holdout, 반례, 리뷰로 억제 | **추천** |
| A+ | A + dense 비교군을 오프라인으로만 측정 | 평가 환경에만 추가 | 없음 (production 무관) | 중간 (평가 환경에 모델 필요) | 높음 | 중간 | **A와 함께 추천.** 6191076557 이행 |
| B | 벡터 arm을 production에 도입 | 색인 worker, 재색인, purge, schema 재사용 여부 | **큼.** 회사 no-local-ML, 다운로드 금지, egress 정책과 충돌. poisoning 공격면 증가 | 중간~높음 | 높음 | 중간 | A+에서 격차가 입증되고 정책이 승인된 뒤에만 |
| C | end-to-end(LLM 판단 포함)를 매 반복 최적화 | host 실행 자동화 | coding agent 반복 실행 | **높음** | 낮음 (비결정, 분산 큼) | **높음** | 비추천. 승격 관문으로만 사용 |
| D | 루프 없이 적대적 리뷰만 반복 | 없음 | 없음 | 중간 | 수치가 없음 | 낮음 | 단독 비추천. 개선을 증명하지 못함 |
| E | task 범위나 artifact 앵커를 먼저 추가해 동시 작업 문제 해결 | migration, 도구 계약 | 기존 "trial 먼저" 결정과 충돌 | 중간 | — | — | 보류. G5 crowding 측정 결과를 근거로 trial 후 재검토 |

### 안 A의 장점

- autoresearch 방식이 그대로 통한다. 결정적이고 싸고 빠르다.
- 기존 원칙(인덱스는 후보만, 판단은 agent)과 기존 결정(오프라인 비교 평가)에 맞는다.
- 기존 평가 코드를 재사용한다: `candidate_recall_at_20`, eligibility witness, bootstrap, digest 동결.
- G1–G10 군별 측정으로 "코드는 좋아졌는데 문서는 나빠졌다" 같은 퇴행을 잡는다.

### 안 A의 단점과 반론

1. **dev gold를 새로 만들어야 한다.** #10 gold와 분리해야 하므로 라벨 작업이 늘어난다. 합성 corpus는 실제 분포와 다르다. 따라서 결과는 "합성 범위의 개선"으로만 표현한다.
2. **후보 recall 개선이 최종 효익을 보장하지 않는다.** 층 C 비열위와 #10 trial이 따로 필요하다.
3. **IDF는 corpus 상태에 따라 바뀌는 순위를 만든다.** 동시 작업으로 claim이 늘면 같은 질의의 순위가 달라진다. 결정성 검사는 corpus 동결로만 성립한다. 운영 중의 순위 안정성은 별도 관찰 대상이다.
4. **lexical 개선만으로 G2·G3(한국어 변형, 한영 동의어)의 한계는 남는다.** agent `query_expansions`가 얼마나 메우는지가 핵심 질문이다. 이것은 agent의 행동이므로 층 C에서만 보인다.
5. **군별 하한 규칙은 보수적이다.** 군마다 12개 안팎이라 노이즈로 인한 거짓 discard가 생길 수 있다. 군별 판정은 순감 ≥2 케이스일 때만 퇴행으로 보는 식의 완충이 필요하다 [제안].
6. **G6(신구 버전)은 검색으로 해결할 수 없다.** 사용자가 supersede/retract를 실제로 하는지, agent가 정정을 제출하는지가 문제의 본체다. 이것은 #10 trial의 "정정 재사용" 지표가 다룬다.

## 8. 단계별 실행 계획

| 단계 | 산출물 | 완료 기준 |
|---|---|---|
| P0 | 사람이 결정: 기존 합격선을 동결할지 재산정할지. dev gold를 #10과 분리할지 | 결정 기록 |
| P1 | 무결성 변형 스위트(I1–I5)를 현재 코드에 적용 | 현재 baseline에서 위반 0 확인. 위반이 나오면 그 자체가 버그 |
| P2 | `eval/`: 10군 dev corpus/gold, 미끼, crowding, 동결 하네스, `results.tsv` | baseline 군별 수치 기록. 같은 commit 3회 실행 결과가 완전히 같음 |
| P3 | `program.md`와 수정 범위 강제. 루프 1차: 비교군 "lexical 개선" | keep commit 확보 또는 "개선 없음" 기록 (둘 다 결과로 인정) |
| P4 | dense 비교군 3개를 오프라인으로 측정 | 군별 격차표 → 벡터 정책 안건 여부 판단 |
| P5 | 승격 관문: 내부 holdout, 층 C, 독립 리뷰 2인 | 관문 통과분만 PR |
| P6 | #10 trial과 연결 | 루프 결과를 "후보 누락 진단"으로만 첨부하고, 효익은 trial로 판정 |

## 9. 한계

- baseline 수치는 측정하지 않았다. PG18 fixture 실행은 P2 범위다.
- §2의 관찰은 Python으로 토큰 집합을 계산한 작은 예시다. SQL 동점 처리, entity arm, RRF를 포함한 실제 순위가 아니다.
- autoresearch는 README 수준에서만 확인했다. keep 조건의 세부(`program.md`)는 확인하지 못했다.
- #5 댓글 중 OSS 조사 원문(S1–S4)과 CI 기록은 키워드로만 확인했다. 빠진 근거가 있을 수 있다.
- 이 제안은 아직 독립 적대적 리뷰를 받지 않았다.
