# Shorts lTja2ZxXYyI — 원문 설명과 후보 검색 분석

## 결론과 관측 범위

**BGE-M3는 첫 단계 후보 검색의 비교 기준이다. Jev나 현재 coding-agent의 기억 채택·관계·관련성 판단을 대체할 근거는 아니다.** 아래 원문 설명은 문서 검색만 비교하며 업무·전문 문서는 측정하지 않았다고 명시한다. 이는 제작자의 에이전트 메모리 권고나 우리 시스템의 실측 결과가 아니다.

감사 경로: [요청 원본 Shorts](https://www.youtube.com/shorts/lTja2ZxXYyI) → 다음 설명 발췌 → 독립 분석 → 미실행 평가 제안. 전체 재생·청취·자막 확인, embedding 구현·benchmark·모델 다운로드·corpus 전송을 완료했다고 주장하지 않는다.

## 직접 관측한 1차 출처

관측일: **2026-10-16**. 브라우저 없이 정적 URL을 읽었다.

- 요청 URL: https://www.youtube.com/shorts/lTja2ZxXYyI
- 반환된 watch URL: https://www.youtube.com/watch?v=lTja2ZxXYyI
- 제목: `한국어 질문 1,000개로 임베딩 3종 문서 찾기 — 아직은 bge-m3`
- 채널: `Solostack`. [YouTube oEmbed](https://www.youtube.com/oembed?url=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3DlTja2ZxXYyI&format=json)도 같은 제목과 `author_name: Solostack`, `author_url: https://www.youtube.com/@Solostack-1`을 반환했다.
- reader metadata: 업로드일 `2026-10-15`, 길이 `2:20`, ID `lTja2ZxXYyI`. 길이는 재생을 확인한 시간이 아니다.

다음은 반환된 **설명 앞부분의 연속 발췌**다. 숫자는 제작자의 보고이며 프로젝트가 재현·독립 검증한 수치가 아니다.

> RAG에서 질문에 맞는 문서를 골라 LLM에게 건네는 임베딩 모델 3종(bge-m3, EmbeddingGemma 2, Qwen3-Embedding-0.6B)을 같은 조건에서 비교했습니다. 임베딩 모델의 일은 정답 문서를 골라 오는 데까지라서, 이번 영상은 그 부분만 다룹니다.
>
> 먼저 알아 두세요: ① 모두 Apple M5 Pro 맥 1대에서 1회 측정했습니다. ② 모델마다 공식 권장 질의/문서 형식, 문서 최대 512토큰, fp32, 코사인 유사도로 맞췄습니다. ③ EmbeddingGemma 2는 사진·영상·소리도 임베딩하지만 이번에는 글자 부분만 썼습니다. ④ 업무 문서·전문 문서는 측정하지 않았습니다. 내 문서로 먼저 재 보세요.
>
> ▶ 한국어 질문 1,000개(KorQuAD v1 표본) · 위키 문단 4,960개에서 정답 문단을 3개 안에 못 골라 온 질문: bge-m3 99개 · EmbeddingGemma 2 133개 · Qwen3-Embedding-0.6B 191개 (1위로 바로 찾은 질문: 773 · 747 · 667)

이는 전체 설명 snapshot이 아니다. 후속 설명에 McNemar 비교, MIRACL 한국어·Ko-StrategyQA 점수와 오답 사례가 있었지만 마지막 사례가 `홍콩 인구 통…`에서 잘렸다. 생략 문장·실험 코드·원자료를 추정하지 않으며 후속 수치로 통계 판정을 하지 않는다.

### 접근 경로와 한계

- Shorts와 watch URL(`hl=ko`)의 정적 읽기는 위 설명을 반환했다. reader는 `No subtitles/captions available`, `No transcript available for this video`를 표시했다. 해당 reader의 관측 한계이지 자막이 어디에도 없다는 증거는 아니다.
- raw HTML도 반환 구간이 잘려 전체 설명을 추출하지 못했다. oEmbed는 제목·채널을 별도로 확인했지만 설명·자막·원자료는 제공하지 않았다. exact-ID 웹 검색의 무결과는 영상 부재의 증거가 아니다.
- 조사 worker의 [issue #5](https://github.com/chonamdoo/agents-memory/issues/5), 공개 comments API, [기존 별도 embedding 댓글](https://github.com/chonamdoo/agents-memory/issues/5#issuecomment-6191076557) 정적 읽기는 404였다. worker의 인증된 읽기도 host/worktree 경계에 거절됐다. 따라서 그 worker가 기존 댓글 본문을 확인했다고 주장하지 않는다.
- 이번 발췌는 새로 관측한 설명이며 과거 분석과 동일한 historical snapshot이라고 주장하지 않는다. 별도 embedding 연구를 Shorts 원문으로 대체하지 않는다.

남은 원문 한계는 잘리지 않은 전체 설명, 재생·자막 및 실험 코드/원자료의 미확인이다. 현재 발췌로는 문서 후보 검색에 한정된 비교와 개발 corpus에서 별도 평가가 필요하다는 범위까지만 직접 인용할 수 있다.

정상으로 binding된 controller의 인증된 읽기에서는 issue #5 댓글 전체 pagination을 확인했지만 이 영상 ID를 포함한 댓글을 찾지 못했다. 이 결과는 `context/resume-github-provenance-observed.json`에 보존했다. PR #9 remote도 여전히 docs/images 8개·HEAD `1b52c4d487d0600d53cc85ec9dbca171d3cd9b3d`이며, 이 새 분석 문서는 작업트리의 보완이지 이미 게시된 과거 분석의 발견이 아니다.

## 별도 1차 출처: BGE-M3 카드

[BAAI/bge-m3 README, revision 5617a9f61b028005a4858fdac845db406aefb181](https://huggingface.co/BAAI/bge-m3/blob/5617a9f61b028005a4858fdac845db406aefb181/README.md)을 같은 관측일에 읽었다. 이는 YouTube 설명과 별개의 출처다.

- `Some suggestions for retrieval pipeline in RAG`는 `hybrid retrieval + re-ranking`을 권고하며 embedding+BM25와 cross-encoder 재순위화를 설명한다.
- `Comparison with BM25`는 BM25도 경쟁력 있는 비교 기준이라고 설명한다. 카드의 기능·공개 benchmark는 우리 개발 corpus의 정확도나 비용 측정이 아니다.
- 카드의 hybrid 권고를 Shorts가 hybrid/reranking을 실험했다는 주장과 섞지 않는다. 현재 실행 경로는 [architecture](../architecture.ko.md)의 lexical/entity 후보 검색과 coding-agent relevance 계약을 유지한다.

## 독립 분석과 채택 조건

**[추론] 후보 회수와 기억 판단은 다르다.** 문단 회수 결과만으로 기억할 가치, 중복·모순·대체 관계, 조건·예외, 철회 적격성이나 최종 개발 행동의 정확성을 판단할 수 없다. embedding 점수로 Jev 허가·명시선택이나 coding-agent 판단을 대체하지 않는다.

**[추론] 기준선이지 영구 승자가 아니다.** 위키 질의와 개발 대화는 식별자·시간·정정 방식이 다르고 제작자도 업무·전문 문서를 측정하지 않았다. BGE-M3를 검토할 근거는 있지만 우리 기억 시스템에서 우월하다는 결론은 별도 평가가 필요하다.

다음은 **제안이며 미실행**이다.

- 실제 개발 대화·결정·오류·정정·기각한 대안과 거절 이유로 평가한다. corpus 저장·외부 전송 허가를 먼저 지킨다.
- exact identifier·경로·에러 코드, 한영 혼합, 바꿔 쓴 표현, 유사하지만 다른 결정, 옛 결정·거절 사례, 적절한 기억이 없는 질의를 포함한다.
- 같은 frozen corpus·질의·후보/최종 context 예산에서 lexical/entity, dense, hybrid, hybrid+reranking을 비교한다. 기존 검색이 놓친 유효 기억, 기존 정답 손실, 무관·오래된·거절된 후보 유입을 분리한다.
- 최종 agent가 올바른 기억을 inspect하고 조건·예외·정정·거절을 반영해 올바른 다음 행동을 했는지 확인한다. 전달됨·인용됨·receipt 있음은 올바른 사용과 다르다.
- 지연·메모리·index 운영비·추가 context와 실패/부분 결과를 함께 기록한다. 적격성·권한·삭제 fence나 최종 agent 판단을 우회하지 않는다. 새 개선율·실측 결과를 만들지 않는다.

현재 판정은 BGE-M3 baseline과 hybrid+reranking 비교 필요성을 유지하는 것이다. 새 embedding engine·자동 모델 대체·판단 제거·실제 trial 또는 publication gate 통과를 선언하지 않는다. [별도 OSS 조사](2026-10-15-oss-local-runtime.ko.md)와 [건강 관리 적대적 리뷰](2026-10-15-memory-health-adversarial.ko.md)는 다른 근거다.
