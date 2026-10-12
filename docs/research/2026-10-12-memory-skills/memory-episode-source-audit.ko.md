# AI That Works 메모리 파이프라인: 원 영상·공개 소스 독립 감사

조사 기준일: 2026-10-12. **연구 결과이며 구현 변경·채택 결정이 아니다.** 기존 worktree의 코드, 런타임, 설정, frozen skill, 설계 문서, receipt, 배포를 변경하지 않았다. 빌드·lint·test·formatter·GitHub 게시를 실행하지 않았다. 실제 native Claude/Codex 비교는 이 문서의 결과가 아니며, 부모가 동일 통합 근거 묶음으로 별도 수행해야 한다.

## 1. 핵심 결론

1. 원 영상은 Boundary 채널의 **「Why AI Coding Agents Need a Memory Pipeline」, `mAKUL12h1n8`**이다. YouTube 원 `videoDetails.lengthSeconds=3214`, 즉 **53:34**이고, 보관 자막 마지막 cue는 **53:33**이다. 사용자가 제시한 43:53–53:11은 이 영상의 후반 논의다. 새 Runlayer 영상 `jDdgfTp_PXw`의 17:37 길이와 혼합하지 않는다. [V1]
2. 공식 저장소에는 **#77 / 2026-10-06 / Building a Memory Pipeline**가 있다. 해당 디렉터리는 조사한 고정 commit에서 `meta.md`, `thumbnail_ep77.png`만 가진다. **이 디렉터리에서 실행 소스를 못 얻었다는 것은 확인되지만, 전체 저장소 또는 인터넷 어디에도 관련 코드가 없다는 결론은 아니다.** 실제 다른 메모리 코드와 피드백 workflow를 찾았다. [R1–R5, C1–C5]
3. 원 영상은 세션의 facts / human corrections / recurring investigations를 추출·필터·그룹화하여 출처 있는 context shard와 보고서를 만드는 프로토타입을 설명한다. 하지만 **code-linked stale invalidation, 모델의 stale 판단, 사후 health 분석, 승인·기각 이력의 재입력, 앞단 추출 기준의 피드백 개선을 모두 구현된 기능처럼 합쳐 말하면 안 된다.** 후반부는 명시적으로 “remaining problem”, “my one idea”, “would”, “could”, “should”를 사용한다. [V1: 43:53–53:11]
4. **인간 승인/기각의 의미를 논의했다는 증거는 있지만, 이 영상의 시스템에 production-grade approve/decline UI·권한 ledger·승인 freshness·재학습 job이 이미 있었다는 공개 증거는 없다.** 원문 “user approved it”은 “그 상태를 다음 입력에 넣자”는 설계 논의 속에 있다. [V1: 50:15–53:09]
5. BAML은 이 사례에서 typed 모델 호출·입출력·프로그램 구성/관찰을 제공한다. 현행 v1은 단순 schema DSL보다 넓은 언어다. 그럼에도 **메모리의 진실성, 승인 권한, 데이터베이스의 정본성, tenant/security, 삭제·snapshot 경계, 실제 host 전달/집행은 애플리케이션이 소유해야 한다.** typed output이나 Jev 확률은 그 보장이 아니다. [B1–B4, J1–J3]
6. 현재 `agents_memory`에는 이미 typed extraction, 조건·예외·시간, source lineage, consolidation/dedupe, hybrid recall, cited reflection, correction/retraction, exact approval와 delivery recheck가 있다. 새로 검토할 실질적 여지는 **(a) 코드 변경→메모리 의존성 색인/검토 트리거, (b) 승인·기각 이력을 bounded incremental 입력으로 쓰는 중복 방지/거절 이유 신호, (c) authority freshness와 별개인 semantic applicability freshness**다. 기존 기능을 새 발견인 것처럼 다시 만들 필요는 없다. [L1–L7]

## 2. 증거 종류와 영상 식별의 한계

- **[원문 관찰]** 이번 조사에서 직접 읽은 원 자막, 원 YouTube 설명/metadata, 고정 commit의 소스·directory tree.
- **[공급자 주장]** 제작자 설명·README·제품 문서의 성능/품질/제품 구현 주장. 독립 실행 결과와 다르다.
- **[INFERENCE]** 원문에서 도출한 적용 판단이나 부재 추론. 실제 구현·검증 결과로 승격하지 않는다.
- **[공개 증거 미확인]** 검토 범위에서 근거를 확보하지 못한 것. 전역 부재 증명이 아니다.
- **[향후 제안]** 원문 자체가 would/could/should로 표현하는 발전 방향.

### 원 영상과 episode 메타데이터

YouTube 원 설명의 직접 인용:

> “In this episode of AI That Works, Dex is joined by Aaron for a hands-on walkthrough of a memory pipeline built by the Human Layer and Boundary teams.”

> “Aaron also walks through the engineering process behind the pipeline, including using BAML to define structured model inputs and outputs, experimenting with Jev for inexpensive classification, and building custom dashboards to inspect results.”

원 설명은 게스트를 **“Aaron Villalpando— Co-founder and CTO”**로 적는다. 보관 자동 자막은 01:37–01:39에서 Aaron을 BAML co-founder/CTO라고 소개하지만 일부 cue에는 Erin 등의 오인식이 있다. **Vaibhav는 공식 episode template의 기본 speaker이고, 그것만으로 이 영상의 실연자를 Vaibhav라고 바꿔 식별하면 안 된다.** 이번 문서에서 Aaron의 성은 YouTube 원 설명으로 확인한 것이다. [V1, R2]

YouTube 원 `publishDate/uploadDate`: `2026-10-09T15:30:15-07:00`. 공식 #77 `meta.md`: `guid: aitw-077`, `title: Building a Memory Pipeline`, `eventDate: 2026-10-06T18:00:00Z`. **행사일과 업로드일은 서로 다른 값**이다. [V1, R1–R3]

단, #77 `media.url`은 개별 영상이 아니라 generic playlist다. 조사한 공식 podcast HTML에는 `mAKUL12h1n8` 직접 문자열이 없고, YouTube 원 설명에는 #77 숫자가 없다. 따라서 **이 영상 자체의 식별은 확정**, **#77과의 대응은 제목·주제·일정·공동 팀·demo 설명으로 강하게 뒷받침되는 [INFERENCE]**이며, `meta.md`만으로 특정 YouTube ID가 직접 결합되었다고 주장하지 않는다. [R2–R3]

### 원 자막과 timestamp 계약

주 증거는 다음 보관 원 captions이며 해석본 `baml-jev-verification.ko.md` / `verified-claims.json`의 판정을 근거로 재사용하지 않았다. 해석본에 있던 URL은 조사 출발점으로만 사용하고 실제 원 source를 다시 읽었다.

- 원 JSON3: `/Users/namdoo/Downloads/cuefinder-memory-pipeline-mAKUL12h1n8/mAKUL12h1n8.en-orig.json3`
  - SHA-256 `a12be7a5b4cd8916e14ab0d027515e2f51ee915a5370b19f45c75edc8553b734`
- timed transcript: 같은 디렉터리의 `transcript.timed.en.txt`
  - SHA-256 `b1317247a0481f6977a327d09769606aadabd90a0cb608698c9095eb1ca5bdd3`
- untimed transcript: 같은 디렉터리의 `transcript.en.txt`
  - SHA-256 `e727dee4dcf2acdc88dd3c1b5342afda9ae5feadeb4bf4a0f433dd5fb0511240`

Timed 파일 header는 **YouTube automatic captions `en-orig JSON3`, 시간은 원 cue start이며 수동 검증한 단어 시간이나 별도 STT가 아니다**라고 명시한다. 이번 조사에서 후반의 핵심 문장을 원 JSON3 `tStartMs` 및 `segs[].utf8`로 직접 대조했다. 예: 43:53 cue `2633599ms`, 49:15 cue `2955520ms`, 50:46 cue `3046000ms`, 52:25 cue `3145920ms`, 53:11 cue `3191359ms`. 아래 `[mm:ss]`는 읽기 쉬운 cue 시작 표기이며 정밀 발화 시작/끝이나 발화자 diarization을 보장하지 않는다.

자동 자막의 “context chart”, “cloud MD”, “RAM sleep”, “Jeb/Jeff/Devon” 등을 인용문에서 임의로 제품명/정확한 기술명으로 교정하지 않는다. 본문 설명은 source 코드/원 설명과 함께 해석한다. 영상 화면의 버튼·승인 UI·코드 전체를 직접 시청 검증한 결과가 아니므로 **자막에서 UI 구현을 추정하지 않는다**.

## 3. claim–verdict 표

| 주장 | 판정 | 근거와 정확한 범위 |
|---|---|---|
| 이 후반 timestamp는 새 Runlayer 영상이다 | **아님** | `mAKUL12h1n8`는 원 metadata 53:34 / 마지막 자막 53:33. 이번 범위는 이 영상이다. [V1] |
| HumanLayer와 Boundary가 BAML을 사용하여 이 memory demo를 함께 만들었다 | **원문으로 확인되는 제작자 주장** | 원 설명, 01:54–02:25 자막이 BAML 사용과 공동 작업을 말한다. HumanLayer의 모든 runtime/제품이 BAML이라는 뜻은 아니다. 공개 feedback controller는 TypeScript다. [V1, C4] |
| #77의 `code` 디렉터리에 완성 pipeline source가 있다 | **조사 commit에서는 아님** | `738a9c18…`에서 메타/썸네일 두 파일만. [R4] |
| 그래서 관련 public memory source는 어디에도 없다 | **잘못된 일반화** | #13/#14 자료, Boundary `ns_memory` 구현, HumanLayer feedback-distillation controller가 공개되어 있다. 영상 전체 3갈래 analyzer와 동일한 것은 아니다. [R5–R6, C1–C5] |
| 영상의 완전한 단일 source repo는 공개되어 있지 않다 | **조사 범위에서는 확보하지 못함; 전역 부재는 증명 불가** | 01:15–01:20은 “excited to ship”, “hopefully … open source parts”라고 말한다. 현재 episode directory에도 없음. 그러나 과거 발언은 오늘의 모든 공개 저장소 상태를 보증하지 않는다. [V1, R4] |
| 메모리를 코드 영역에 연결하는 output은 이미 시연한 내용이다 | **원문상 확인** | 07:54–08:00 “three … MD files … tied to specific regions in the code.” 코드와 연계된 산출물이라는 설명이다. diff watcher·정확한 의존성 색인·자동 무효화 구현까지 증명하지 않는다. [V1] |
| 코드 변경을 감지해서 stale memory를 자동으로 안전하게 제거한다 | **향후 아이디어 / 공개 구현 미확인** | 43:53 “remaining problem”; 49:15 “my one idea”; code-map 연결을 stale 판단 수단으로 제안한다. [V1] |
| agent judgment가 memory health를 결정할 수 있다고 말한다 | **향후 제안 확인** | 49:38–49:52 “probably ask the agent”, “let the agent decide”. correctness·authority 보장은 아니다. [V1] |
| 사후 세션 재분석으로 잘못된 memory의 신호를 찾는다 | **제안 확인; health 운영 job은 미확인** | 49:53–50:10은 기존 session 분석 방식과 유사하게 agent correction 문장을 보자고 한다. 기존 pipeline의 분석 능력과 새로운 health feature를 구분한다. [V1] |
| 인간 approve/decline와 승인 memory의 재입력이 이미 구현됐다 | **논의는 확인, 완성 구현 증거 미확인** | 44:02 “maybe we accept”; 50:15 이후 feedback evolution 질문; 50:46 “would be … fourth input”; 51:26 “should … put that data”. [V1] |
| 승인된 shard를 모든 다음 extraction 단계에 재입력한다고 구현했다 | **과장** | 먼저 제안하는 위치는 **final draft/report의 fourth input**이다. 앞단 fact/correction criteria 변화는 52:35 이후 별도의 향후 feedback loop로 논의한다. [V1] |
| 거절된 memory로 모델을 이미 학습/fine-tune한다 | **아님 / 그런 증거 없음** | rejected examples와 이유를 다음 flow에 넣고 추출 기준을 개선하자는 제안. weight training·fine-tuning·실행된 rejection training job은 언급/공개 증거가 없다. [V1, J3] |
| Jev는 Jeff라는 일반 agent 또는 자유문서 생성 모델이다 | **아님** | Jev는 TypeSafe의 모델. 실제 public BAML client와 `/v1/systemone` API가 있다. bounded decision/classification 모델이며 free-form generation은 별도 생성 모델이 맡는다. [B3–B4, J1–J3] |
| BAML schema나 Jev confidence가 메모리 사실성/인간 승인/보안을 보증한다 | **성립하지 않음** | 타입·정해진 predicate/확률과 facts/승인 ledger/authorization은 별개. Jev 공식 문서도 adversarial input과 generation의 한계를 밝힌다. [B1–B4, J1–J3] |
| `agents_memory`에 extraction/dedupe/correction/approval가 없으므로 새로 구축해야 한다 | **현재 코드와 맞지 않음** | 기존 typed schema·worker·consolidation·correction·rule ledger·delivery freshness가 존재한다. 실제 남은 검토 범위는 아래 세 가지 증분 항목이다. [L1–L7] |

## 4. 43:53–53:11 원문: 구현과 발전 제안 분리

### 4.1 memory health는 명시적인 남은 문제

[43:53](https://www.youtube.com/watch?v=mAKUL12h1n8&t=2633s):

> “like one uh remaining problem here with”
> “this whole pipeline.”

[44:02–44:06](https://www.youtube.com/watch?v=mAKUL12h1n8&t=2642s):

> “a context chart and maybe we accept some”
> “of them and deny some of them like how”
> “do we track the health of a memory right”

[44:27–44:34](https://www.youtube.com/watch?v=mAKUL12h1n8&t=2667s):

> “Yeah. Yeah. And so I don't know if you”
> “had some ideas here. I don't have”
> “anything else here by the way in these”
> “slides, but if you have any ideas on how”
> “we could do the health of a of a memory.”

이는 health feature의 결과 시연이나 acceptance evidence가 아니라 토론으로 넘어가는 발언이다. 그 앞에서 실제 설명한 추출/그룹화/MD 보고서와 구분한다.

### 4.2 skill 대량 적재·Cognition 언급·주기적 consolidation

[44:47–45:16](https://www.youtube.com/watch?v=mAKUL12h1n8&t=2687s)은 CLAUDE.md/skill에 넣는 순진한 접근과 200개 one-fact skill의 attention 문제를 말하고, “I don't know if there's an eval for this”라고 한다. **200개가 특정 성능 임계값이라는 실험 결과가 아니다.**

[46:04–46:12](https://www.youtube.com/watch?v=mAKUL12h1n8&t=2764s):

> “But if we click here there's nothing”
> “that really tells you how something”
> “makes it into a memory. Uh so that's”
> “like I think that's the hardest part.”

이는 당시 화자의 Cognition 설명 평가다. 이번 task의 공식 source 범위에서 그 제품의 비공개 추출 알고리즘이나 내부 권한 계약을 확인한 것은 아니다.

[47:07–47:13](https://www.youtube.com/watch?v=mAKUL12h1n8&t=2827s):

> “with doing that is that if you're just”
> “in a single session, you're not able to”
> “make correlations across many sessions.”

이 비교는 single-session agent note와 cross-session 분석의 차이이며, 기존 `agents_memory`의 consolidation·독립 root-run 집계를 새로 만들어야 한다는 근거가 아니다.

[48:08–48:21](https://www.youtube.com/watch?v=mAKUL12h1n8&t=2888s)은 cron 같은 주기적 작업으로 memories를 compact/coalesce하자고 논의한다. 현재 운영 scheduler·lease·삭제 fence의 공개 구현 증거는 아니다.

[48:22–49:09](https://www.youtube.com/watch?v=mAKUL12h1n8&t=2902s)은 일부 세션을 memory 없이 돌리거나 새 모델로 과거 trace를 back-test하는 아이디어와 long-horizon 비교의 어려움을 말한다. **사용자 세션을 무작위로 저하시키는 실험을 바로 권고할 근거가 아니며**, 초기 행동이 달라진 후 과거 후속 user message를 그대로 먹이는 replay의 입력 동일성 문제가 명시되어 있다.

### 4.3 49:15 이후: code association / agent judgment / 사후 분석 / human review

[49:11–49:27](https://www.youtube.com/watch?v=mAKUL12h1n8&t=2951s):

> “Yeah. And I think my my one idea I had”
> “actually to like figure out how to”
> “figure out whether something is stale is”
> “um is I tie each sort of memory to like”
> “a place in the codebase or a or a region”
> “in the codebase”

[49:33–49:36](https://www.youtube.com/watch?v=mAKUL12h1n8&t=2973s):

> “doing that like the code map that I”
> “mentioned where like you tie each memory”
> “to like a place in the codebase.”

**코드 연계 output은 앞서 보여 준 것으로 설명하지만, 코드가 바뀌었을 때 자동으로 영향 집합을 계산하는 dependency index/검증/무효화 구현은 이 인용에서 나오지 않는다.** 코드 참조가 있다는 것과 참조가 완전하다는 것은 다르다.

[49:38–49:52](https://www.youtube.com/watch?v=mAKUL12h1n8&t=2978s):

> “Yeah. But also you can probably ask the”
> “agent also like hey if I'm here and this”
> “is in your context now and you just”
> “worked on these this file like is this”
> “outdated or not and then you kind of”
> “just let the agent decide like oh yeah”
> “this thing is stale it's incorrect let”
> “me fix that”

이는 **모델 기반 stale/correction 후보** 아이디어다. model judgment를 인간의 승인·철회 authority로 바꾸지 않는다.

[49:53–50:04](https://www.youtube.com/watch?v=mAKUL12h1n8&t=2993s):

> “or you just analyze it after the fact”
> “just like we did”
> “where we analyze the session again and”
> “we find the message where an agent says”
> “oh snap that was not correct let me fix”
> “that.”

[50:05–50:12](https://www.youtube.com/watch?v=mAKUL12h1n8&t=3005s):

> “Um and I think you could get a similar”
> “sense of like the health of a of a”
> “memory”
> “or let let a a human do it.”

사후 세션 분석을 health signal로 쓰자는 제안과 인간 검토 선택지를 각각 확인할 수 있다. **assistant 자기교정은 인간 승인 사실이 아니다.**

### 4.4 50:15 이후: 승인/기각 이력을 다음 보고서에 넣자는 fourth input

[50:15–50:43](https://www.youtube.com/watch?v=mAKUL12h1n8&t=3015s)은 하루/주 단위로 pipeline을 돌려 suggestions를 생성할 때, 사용자가 네 개를 유지하고 네 개를 나쁘다고 버린 feedback으로 pipeline 자체를 어떻게 개선할지를 질문한다. 동작 구현을 보고하는 문장이 아니다.

[50:46–50:58](https://www.youtube.com/watch?v=mAKUL12h1n8&t=3046s):

> “I think there would be like another”
> “fourth input. So you know how the”
> “pipeline had like three different”
> “inputs, there will be a fourth one that”
> “just goes into like the final draft and”
> “report that has either the existing uh”
> “save memories from previous sessions.”

[51:06–51:17](https://www.youtube.com/watch?v=mAKUL12h1n8&t=3066s)은 incremental하게 만들어 이미 circulation에 있는 memories의 report를 다시 생성하지 말자는 설명이다.

[51:20–51:32](https://www.youtube.com/watch?v=mAKUL12h1n8&t=3080s):

> “Exactly. Like there's it's almost like a”
> “memory gets upgraded into like approved,”
> “right? Like the the user approved it. So”
> “you should just put that data in there.”
> “Like if uh we run it again, we should”
> “put the memories that were already”
> “approved.”

**승인된 데이터의 재입력이라는 의도는 맞다. 다만 제안된 최초 위치는 final report이며, 승인 ledger·UI가 작동했다거나 모든 extraction 입력이 이미 바뀌었다는 뜻은 아니다.**

[52:03–52:11](https://www.youtube.com/watch?v=mAKUL12h1n8&t=3123s):

> “include by the way here's 10 memories”
> “that the user dismissed and maybe they”
> “even left feedback about why it's bad”
> “and like incorporate that into your next”
> “flow And maybe the final report has not”

52:15–52:23에는 사용자에게 이미 처리되었거나 관련 없는 memory를 제거하도록 제안할 수 있다고 덧붙인다. **model suggestion과 실제 irreversible 삭제/철회는 별개다.**

[52:35–53:09](https://www.youtube.com/watch?v=mAKUL12h1n8&t=3155s):

> “information, for example, what if”
> “there's memories that the human rejected”
> “or uh they're like this is bad, don't do”
> “this, then I think you could start”
> “building a feedback loop on the rest of”
> “the pipeline.”

이후 “do I need to change earlier steps”, “change what criteria I have for finding a fact or finding a correction”이라고 한다. **앞단 추출 기준을 바꾸는 feedback engine은 향후 제안**이다. 이를 곧바로 모델 weight training/fine-tuning으로 번역하지 않는다.

## 5. 실제로 찾은 공개 source / recipe와 라이선스

### 5.1 AI That Works: 해당 디렉터리의 부재와 저장소 전체의 관련 자료는 다르다

고정 commit: [`738a9c18b0302737d5d354d9988f34482966cce6`](https://github.com/ai-that-works/ai-that-works/tree/738a9c18b0302737d5d354d9988f34482966cce6). GitHub recursive tree는 `truncated=false`, 2,723 entries로 관찰했다. episode README index 및 memory 관련 directory/file을 조사했다. [R1, R4–R6]

- `2026-10-06-building-a-memory-pipeline/`: **`meta.md` + `thumbnail_ep77.png`만**. metadata blob SHA `9497c8bbd045225fbd66474583181dacb9645b4d`. 전체 3갈래 extraction prompt/grouping/report/dashboard 실행 코드가 이 디렉터리에 없다.
- `2025-07-08-context-engineering/`: 실제 memory/context 논의의 README와 #13 `-doV02eh8XI` 링크가 있다. “When creating summarization tasks, provide the model with the existing memory context”라는 recipe를 제시한다. 하지만 directory의 `baml_src/resume.baml` 같은 존재만으로 memory supervisor 전체 구현이라고 부르지 않는다.
- `2025-07-15-decaying-resolution-memory/`: 실제 public Python/BAML source가 있다. `examine_threads.py`는 Redis thread 검사/export, `redact_pii.py`는 chunk별 `b.RedactPII` 호출, `baml_src/redact_pii.baml`은 외부 `openai/gpt-4o-mini`로 redaction을 요청한다. README의 “production-ready DRM” 설명과 **실제 검토 코드의 증거 수준은 다르다**. `main.py`는 greeting entry일 뿐이며, 이 소스들로 #77의 facts/corrections/recurring-investigations 전체 또는 완성된 decay scheduler를 입증하지 못한다. [R5–R9]
- #13은 HumanLayer [Own your context window](https://github.com/humanlayer/12-factor-agents/blob/main/content/factor-03-own-your-context-window.md), Bryan Houlton의 [Building proactive AI agents](https://bryanhoulton1.substack.com/p/building-proactive-ai-agents)를 연결한다. 전자는 context ownership 설계 글, 후자는 Orin의 temporal DRM과 sliding-window summaries에 대한 작성자 사례/recipe다. **영상 #77의 공개 executable source repo가 아니다.**

이 조사 tree에서는 AI That Works의 `LICENSE` 파일을 찾지 못했다. 해당 #14 소스에 다른 저장소 BAML의 Apache-2.0을 자동 적용하지 않는다. **공개 열람 가능과 복사·재배포 라이선스 확보는 다르다.**

특히 `redact_pii.py`의 exception handler는 `return text  # Return original if error`다. 원문은 redaction 전에 이미 외부 생성 모델에 보내진다. **회사 data egress 경계/필터로 이 recipe를 가져오지 않는다.** [R8–R9]

### 5.2 Boundary `baml-demos`: 진짜 durable-memory 코드지만 영상 전체 pipeline은 아님

고정 commit: [`dcc3d33f0fd2635d18515a62a10da91ae789f080`](https://github.com/BoundaryML/baml-demos/tree/dcc3d33f0fd2635d18515a62a10da91ae789f080). [C1–C3]

실제 memory-specific 경로:

- `aie/baml_src/ns_memory/curator.baml`
- `aie/baml_src/ns_memory/memory.baml`
- `aie/baml_src/ns_memory/tests.baml` — 파일 존재 확인만; 테스트 실행 안 함.
- 호출 연결: `aie/baml_src/ns_agent/agent.baml`의 `run_turn`, `run_supervised`, `turn_delta`, `ask`.

관찰한 구현:

- 별도 작은 curator model `claude-haiku-4-5-20251001`이 finished **turn**을 자기 context에서 읽고 `MemoryEdit[]`의 `save|delete`를 반환한다.
- 이미 저장된 memory index를 curator에 넣는다. 같은 이름으로 save하면 overwrite, obsolete면 delete하도록 prompt에 적는다.
- `max_edits_per_turn=5`, 빈 이름/본문 검사·cap을 코드로 적용한다.
- 실제 supervisor가 `curate_turn(turn_delta(...))`를 호출한다. `turn_delta` 주석은 **전체 session이 아닌 새 turn만** 본다고 명시한다.
- store는 `.bamlcode/memory/<slug>.md` 파일이며 keywords/name/body lexical scoring, 기본 top-3 recall, marker 기반 같은 session의 재주입 방지를 구현한다.
- `BAMLCODE_MEMORY_DIR` 경로 변경, `BAMLCODE_MEMORY=off`로 recall/curation 비활성화.
- 기본 recall은 **자동 켜짐**이고, 본문은 “trust them unless the user contradicts them”으로 주입한다. 오류는 `catch_all => []`로 흡수한다.

중요한 분리:

- prompt의 “anything the user did not confirm” 금지는 **실제 human approval protocol이 아니다**. model이 직접 파일 overwrite/delete를 적용한다.
- 기존 index 재입력과 marker dedupe는 존재하지만, 승인/기각 ledger·거절 이유 학습·snapshot dependency·권한 검증으로 확장해 읽지 않는다.
- 한 turn curator와 파일 recall 예시는 **주간 cross-session 3갈래 analyzer / Jev filtering / code-map grouping / SQL dashboard**의 공개 source가 아니다.
- 조사한 repository metadata의 license는 null이고 tree에서 LICENSE를 찾지 못했다. 이 code가 BAML로 쓰였다는 이유로 BAML 본체의 Apache-2.0을 상속하지 않는다. **아이디어 참조는 가능하나 code copy/reuse는 명시 권한 확인 전 보류한다.**

### 5.3 HumanLayer `skills`: 인간 피드백→향후 guidance의 실제 controller

고정 commit: [`653b6411c1f70c275a18e37673b042ff99f67ceb`](https://github.com/humanlayer/skills/tree/653b6411c1f70c275a18e37673b042ff99f67ceb). 명시 [MIT License](https://github.com/humanlayer/skills/blob/653b6411c1f70c275a18e37673b042ff99f67ceb/LICENSE), Copyright 2026 HumanLayer. [C4–C5]

실제 경로:

- `plugins/build-iterated-agentic-loop/skills/build-iterated-agentic-loop/references/agent-iteration.ts`
- 같은 references의 `memory-template.md`
- 별도의 `design-control-loop` plugin에도 관련 template 파일이 tree에 있으나 본 문서의 구체 동작 근거는 위 inspected controller다.

`footer`는 `/iterate <feedback>`와 workflow marker를 PR에 설명한다. `prompt`는 기존 memory, PR, issue/review comments를 읽어 prompt를 구성한다. 실제 지시:

> “Distill durable feedback into … when it should influence future scheduled/manual runs of this workflow.”

> “Do not append raw transcripts or one-off PR details.”

> “If the feedback is only PR-specific, update the PR but do not add it to memory.”

따라서 **재사용 가능한 workflow plumbing과 durable feedback 정책은 공개된다.** 다만 agent가 distill할지를 판단하는 prompt이며, 모든 세션 correction mining·semantic 검증·approve/decline memory ledger·Jev classifier·거절 training engine이 구현된 것은 아니다. 이 controller의 commit/push/GitHub 접근 workflow 자체를 이번 조사에서 실행하거나 우리 로컬 memory 운영에 도입하지 않았다.

### 5.4 흔히 혼동할 다른 Boundary public repo

- `BoundaryML/feelings` commit `e0f07b4…`: Jev decision과 generative model writing을 BAML로 연결하는 typed judgment library/예제. README는 “Jev makes the decisions, an LLM does the writing, and BAML ties it together.”라고 한다. **memory pipeline source가 아니다.** [C6]
- `BoundaryML/analytics-demo` commit `8125575a…`: free-text 주소→BuildingRecord POST 서비스/trace SQL/dashboard demo. **memory 분석기가 아니다.** [C7]
- `BoundaryML/boundary-dashboard-template` commit `c61fb203…`: BAML traces를 SQL로 조회하는 **Boundary cloud dashboard starter**. 영상 memory dashboard 전체 구현이 아니고, 로컬 PG canonical ledger 대체재도 아니다. [C8]
- `BoundaryML/reflection-demos` commit `897a46ac…`: runtime reflection의 runnable demos라는 repository 설명/tree를 관찰했다. memory reflection/health의 전체 파이프라인 공개라는 근거로 쓰지 않는다.
- HumanLayer public organization 목록과 `humanlayer/humanlayer` commit `99abe673…`, `humanlayer/agentlayer` commit `6f853b31…`의 recursive tree도 살폈다. 이 조사에서 영상 전체 source를 연결하지 못했다. HumanLayer 조직의 모든 파일/branch/비공개 repo를 검색했다는 뜻은 아니다.

**최종 공개성 결론:** “episode #77 directory에는 실행 코드가 없다”는 확인. “공개된 memory-specific 코드/recipe는 있다”도 확인. “영상 전체 단일 source repo는 조사한 primary links와 후보 저장소에서 확보하지 못했다”는 한정된 결과. **‘인터넷 어디에도 완전한 구현이 없다’는 결론은 내리지 않는다.**

## 6. BAML / Jev가 실제로 소유하는 계약

### BAML

현행 BAML 본체 고정 commit: [`cd10232f9e39088ab046ddb8116ffb2a36919785`](https://github.com/BoundaryML/baml/tree/cd10232f9e39088ab046ddb8116ffb2a36919785), 명시 Apache-2.0. [B1–B4]

- 원 영상의 도입 역할: 모델 함수의 typed input/output, probability·enum 등의 구조적 반환, 프로그램 단계 구성/관찰. 원 설명이 이를 직접 말한다.
- 현재 v1은 Turing-complete language·runtime types·typed error handling·stdlib·tooling을 갖는다고 공식 설명한다. **‘BAML은 schema 생성만 가능한 작은 DSL’로 축소하지 않는다.**
- 하지만 반환 타입의 `fact`, `approved`, `correct` 문자열은 실제 사실/권한을 만들어 내지 않는다. 애플리케이션이 evidence, approver authentication, immutable digest, current source/dependency, scope, deletion, publish/read fence를 검증해야 한다. **이 ownership 경계는 [INFERENCE]이자 공개 sample과 현재 앱 구현으로 뒷받침되는 설계 판단**이다.
- `docs.boundaryml.com` checks/asserts 페이지는 **v0 legacy DSL**, v1은 별도 언어/public beta라고 경고한다. 그 `@assert`/`@check`는 작성한 범위·길이·regex 등의 predicate를 검사하는 계약이다. 본 문서에서는 v0 syntax를 v1 구현에 그대로 제안하지 않는다. [B2]
- 원 source span이 존재한다는 검사조차 entailment/현재 사실성/사람 승인 보장은 아니다. 우리 기존 Pydantic contract를 버리고 BAML로 재작성할 이유는 이번 근거로 확인되지 않았다. [L1–L3]

### Jev

**올바른 식별: TypeSafe의 Jev.** 사람 이름 Jeff/Jeb이나 Boundary의 독자 memory database가 아니다. [J1–J3]

- 실제 endpoint: `POST https://api.typesafe.ai/v1/systemone`.
- `state`, `model`, named `questions` → typed `answers` + resolved `model` + token `usage`.
- 원 API primitive는 **`noul`, `choice`, `score` 세 가지**. classification은 용도다.
- public BAML `typesafeai/client.baml`와 `ns_internal/jev.baml`이 실제 integration source다. bool/float는 Noul, enum/finite union은 Choice, class는 지원되는 leaf마다 질문을 만들며, unsupported/free-form output·tools·media를 HTTP 전에 거절한다. 이 BAML integration은 **Noul/Choice를 사용**하며 raw TypeSafe API의 Score를 사용한다고 말하지 않는다.
- client 기본값은 `jev-latest`, `TYPESAFE_API_KEY`, `https://api.typesafe.ai/v1`, `capture_wire=true`. 외부 hosted API 접근이지 local-only 모델이라는 증거가 아니다.
- 현재 공식 model 문서는 `jev-1.13.0`, English가 주 학습 언어이며 CJK가 동일하게 잘 처리되지 않을 수 있다고 말한다. 공식 jaggedness 문서는 adversarial state가 답을 움직일 수 있고, arithmetic/date ordering은 코드로 처리하며, free-form text generation은 다른 모델을 쓰라고 명시한다.
- “Jev is not fine-tuned or LoRA-adapted with customer data”라는 공식 설명도 있다. 영상의 rejection-feedback 논의를 이미 존재하는 per-customer Jev training으로 해석할 수 없다.
- **공개되어 확인한 것은 API 문서·BAML client/source integration이다.** 모델 weights·local deployment license·한국어 memory 품질·우리 회사 데이터 처리 허가를 확인한 것은 아니다. “not trained on customer requests”와 enterprise ZDR 안내는 외부 송신 허가 또는 모든 plan의 무보관 보장과 다르다.

따라서 Claude/Codex 팀 계정의 사용 허가로 Jev, Boundary cloud, 별도 telemetry/memory 서비스를 자동 허가하지 않는다. 이번 조사에는 회사 corpus를 사용하지 않았다.

## 7. 현재 `agents_memory`와의 비교: 이미 존재하는 것 vs 진짜 증분 여지

비교 대상은 지정 worktree의 관찰 source다. 아래 결과는 정적 source/document 감사이며 native host 실행·747 tests의 재실행/독립 확인이 아니다. 부모가 제공한 기존 검증 baseline을 재실험으로 포장하지 않는다.

### 이미 존재하므로 재구축하면 안 되는 기능

- `domain.py:173–219`: claim kind, subject/predicate/object, polarity, modality, conditions/exceptions, valid time, entities, exact evidence와 source revision/speaker; `Source`/`Claim`의 snapshot.
- `models.py:423–434`: source metadata와 original spans를 typed extraction에 입력. `502–513`: 기존 claims 기반 consolidation. `557–568`: query+claim manifest 기반 cited reflection.
- `jobs.py:82–111,127–136`: extract/consolidate/reindex/reflect의 기존 admission→model→publication 흐름. 새 독립 pipeline/DB를 만들 필요 없다.
- `store.py:503–520`: feedback receipt의 idempotency와 `am_feedback` persistence. **이미 저장할 수 있으므로 feedback table 자체가 없다고 말하지 않는다.**
- `store.py:543–552,587–596`: active source/revision/realm/binding/snapshot/valid-time eligibility와 dependency recheck.
- `store.py:888–908,926–957,995–1048`: exact proposal digest, source dependencies, 현재 approver credential generation/grant, shared signature, immutable scope/target/reapproval. **인간 승인이 없는 시스템이라는 주장은 틀리다.**
- `store.py:1802–1825,1860–1883`: 권한 있는 retract/correct 경로와 새로운 eligible correction evidence 요구. agent `memory_feedback`는 이를 자동 실행하는 승인/삭제 권한이 아니다.
- `store.py:1953–1979`: delivery 직전 actual input 및 완전한 active rule version set 재검사.
- `context.py:61–89`: selector path/purpose/host/snapshot의 true/false/unknown 구분.
- `docs/architecture.ko.md:93–147`: cross-session consolidation, 독립 root-run signal, correction→next-use, 세 가지 exact scope, zero eager body, bounded context, native host capability gap.

### 실제 관찰된 좁은 여지

**A. 코드 변경 감지와 indexed code dependency** — [INFERENCE: 개선 후보]

현재 entities/exact identifiers, source/claim snapshot, rule path/snapshot selector는 있다. 그러나 **`claim/rule → 실제 code file/symbol/region digest`를 canonical dependency로 색인하고, Git diff/rename/dirty change를 그 dependency와 연결해 검토하는 경로는 이번 `src` 검색에서 찾지 못했다.** `semantic_contract.py`의 source stamp/AST digest는 **메모리 엔진 자신의 semantic implementation 변경 검출**이며, 사용자 코드베이스 의존성 freshness와는 다른 기능이다. source `_dependencies`는 memory source revision 관계이고 AST/code dependency graph가 아니다.

기존 exact snapshot mismatch 차단을 “아무 freshness도 없다”로 잘못 말하지 않는다. 반대로 snapshot 문자열과 path selector만 있다고 코드 의미 변화의 자동 탐지/완전성이 생기지는 않는다.

**B. feedback 중복 억제·rejection signal의 후속 입력 소비** — [원문 관찰 + INFERENCE]

`store.feedback`는 idempotent하게 요청·target·kind·optional body를 저장하고 끝난다. `models.extract` 입력은 source+original spans, `consolidate`는 claims, `reflect`는 query+claims다. 조사한 `src` 전체의 `am_feedback` references에는 **이를 extraction/consolidation/report 입력으로 조회하는 SELECT/consumer를 찾지 못했다.** 따라서 “거절 이력이 자동으로 다음 후보 생성에 반영됨”은 현재 관찰 코드로 입증되지 않는다.

단, 일반 claim duplicate/supersede와 request idempotency는 이미 존재한다. 필요한 후보는 별도 **target revision/digest와 의미를 보존한 승인·기각 incremental ledger view**이지 또 다른 일반 dedupe engine이 아니다. 기존 `feedback` source는 `agent_note`로 저장되므로 그것을 곧바로 human-approved rejection이라고 취급해서도 안 된다.

**C. approval freshness의 두 층 분리** — [원문 관찰 + INFERENCE]

현재 approval의 authority freshness는 강하다: exact digest, source revision/active state, credentials, signer, grants, scope/targets, delivery set를 다시 확인한다. **부족하다고 볼 수 있는 후보는 “그 승인된 내용이 코드 변경/현재 환경/모델 능력 변화 뒤에도 적용상 유효한가”라는 semantic freshness review**다. 현재 확인한 rule ledger에는 code dependency 검토 stamp/semantic review deadline을 독립적으로 소비하는 흐름이 없다.

시간이 오래됐다는 이유로 모델이 승인 내용을 임의 갱신하거나 필수 규칙을 조용히 숨기게 해서는 안 된다. 새 내용/selector/exception/required/target 의미가 바뀌면 **새 immutable proposal과 실제 재승인**이 필요하다. 이 연구는 기존 approval가 보안상 무효라는 결론을 내리지 않는다.

### source snapshot 추적용 digest

이번 읽기 관찰 뒤 source checksum을 기록했다. 이는 build/test 결과가 아니다.

```text
src/agents_memory/store.py  f67ea12ffd848f560558e2a25db210a6b985c55e0f1978ed2ec7980255a3ea09
src/agents_memory/models.py c2de715d2ffcaa036c7db018759ef589bf17c9b4d87e920563e8046f78568266
src/agents_memory/jobs.py   f5116c3f894c97347debebd02f68818fb09292bbdc40ee9cfcfb35c2f7b8738b
src/agents_memory/domain.py 7e1b16352703981b159b6f84e1f19aeb0502f9688e5b6ddd17e56c6a53c2ebef
src/agents_memory/context.py f7ab3cae492cb2a289ba817e0524831054a54f8ab0c9b29236ffbdbfdeb1a826
docs/architecture.ko.md    379c5e56466735ab55ad021d6e109c2a7f5dc14acd46220ca56fb8d213fa239a
```

## 8. 가져올 것 / 기각·보류할 것

모두 **연구 제안 [INFERENCE]**이며 자동 채택하거나 현재 심사 runtime patch에 섞지 않는다.

### 낮은 위험으로 빌릴 원리

1. **기존 pipeline의 최종 후보/보고서 단계에 bounded 기존 승인·기각 view를 참조시키기.** 먼저 exact revision/digest로 이미 승인되어 유통 중인 항목의 재제안을 줄인다. “duplicate / incorrect / irrelevant / already documented / superseded / one-off” 등 거절 이유를 구분하고 사용자 원문/evidence를 유지한다. accepted/rejected를 임의 majority training signal로 만들지 않는다.
2. **코드 변경은 review trigger, model judgment는 후보라는 원칙.** code dependency stamp가 달라지면 관련 optional memory의 freshness를 검토할 수 있다. 정확한 diff/rename/symbol mapping을 못 할 경우 unknown을 보고하고, 모델이 ‘stale’라고 말했다는 이유만으로 사실/승인 ledger를 직접 overwrite/delete하지 않는다.
3. **일회성 task feedback과 durable guidance를 구분하기.** HumanLayer controller의 PR-specific feedback과 standing memory 분리는 기존 claim kind/conditions/evidence 정책에 참고할 수 있다. PR/GitHub workflow 자체를 가져오는 것은 별도다.
4. **생성·판정·집행 역할 분리.** generative model은 근거 있는 후보 문장을 만들고, bounded classifier는 advisory 신호를 제공하며, deterministic code와 approver는 scope/lineage/authority를 집행한다. 이를 위해 BAML/Jev 종속성을 반드시 추가할 필요는 없다.
5. **기존 원문과 시간/예외를 잃지 않는 사후 재분석.** 새 evidence event에서 correction 후보를 만들되 이미 주입한 memory echo나 동일 origin 재수집을 독립 지지 증거로 세지 않는 기존 계약을 유지한다.

### 기각 또는 별도 승인 전 보류

- 파일 curator가 모델 판단만으로 승인 ledger를 overwrite/delete하는 방식: **기각**. demo의 “trust them unless user contradicts”를 우리 authority 계약으로 채택하지 않는다.
- 모든 memory/skill/body를 root CLAUDE.md·AGENTS.md 또는 startup instructions에 적재: **기각**. 연결 시 body0·opt-in bounded context와 충돌한다.
- 코드 map/높은 confidence/반복 횟수만으로 자동 사실성·승인 승격: **기각**. 의존성 누락, branch/dirty snapshot, prompt injection, 오류 반복을 해결하지 못한다.
- 권한 없는 agent rejection을 규칙 철회/회사 공유 삭제로 해석: **기각**. feedback candidate와 승인자 action을 유지한다.
- approved/dismissed memory 전량을 모든 extraction에 주입: **보류**. 영상의 최초 제안도 final report input이다. 입력 범위·비용·echo·evidence independence·deletion fences를 먼저 설계해야 한다.
- 모델이 rejection을 보고 prompt/schema/semantic engine을 자율 수정/즉시 배포: **보류**. 기존 route/semantic contract approval과 native 검증을 우회한다.
- Jev/Boundary cloud 또는 demo의 외부 model을 회사 default로 호출: **기각**. 회사 데이터 외부 송신 허가는 없다.
- 라이선스가 확인되지 않은 AI That Works / baml-demos code 직접 복사: **보류**. 공개 URL만으로 재배포 권한을 확보한 것은 아니다.
- 라이브 사용자 세션을 임의로 memory 없이 실행하는 A/B: **보류**. 사전 동의·동일 task 조건·long-horizon 평가 문제가 남는다.
- model-based PII redaction을 회사 data egress의 보안 경계로 사용: **기각**. #14 recipe는 redaction 전 외부 송신하고 실패 시 원문을 반환한다.

## 9. 향후 제안을 채택할 경우의 영향 범위

아래는 설계 검토 항목이지 이번 작업이 추가한 schema/job/feature가 아니다.

| 면 | 최소 영향 / 유지해야 할 계약 |
|---|---|
| **Schema** | 코드 의존성 후보를 채택한다면 project/realm, memory/proposal exact revision, code path/symbol/region, snapshot/branch/dirty 상태, 검증된 digest와 관찰 provenance를 별도로 표현해야 한다. entity string을 verified dependency로 승격하지 않는다. feedback는 target revision/digest·주체/권한·이유·origin/evidence를 정확히 보존하고, idempotency receipt와 semantic duplicate를 구분한다. 새 rule body 변경은 immutable proposal이다. |
| **Jobs** | 기존 extract/consolidate/reflect와 admission/publication을 확장할지 검토한다. 새로운 index/diff-trigger 또는 bounded report feedback view가 필요할 수 있으나 scheduler를 별도 엔진으로 복제하지 않는다. source/snapshot/lease/auth/deletion fences와 route approval를 우회하지 않는다. stale worker가 오래된 승인·거절 view를 publish하지 못해야 한다. |
| **Read eligibility** | 현재 source revision/snapshot/time eligibility를 유지한다. dependency mismatch/검증 불가를 사실상 최신으로 반환하지 않는다. optional 후보와 mandatory approved rule을 구분한다. 필수 규칙은 모델이 ‘쓸모없다’고 판단해 조용히 제외할 수 없다. 지원 strict 경로의 applicability unknown은 기존 fail-closed 정책을 보존한다. |
| **Authority** | PG approved-rule ledger가 유일 정본. feedback와 generated report는 approval가 아니다. approver credential/signer/grants, body/selector/exception/required/targets/digest binding과 세 exact scope를 유지한다. 의미 변경은 재승인; target 확장·팀 공유·회사 data route 변경은 별도 실제 권한 결정이다. |
| **Hosts** | Claude/Codex/OMP용 capture·context generation·delivery 계약을 변경하지 않는다. startup instructions/corpus/root full body0, opt-in bounded context를 유지한다. OMP native callback의 strict capability gap과 **strict 설치의 쓰기 전 거절**을 새 research 기능으로 해소했다고 주장하지 않는다. advisory/manual 지원과 strict 경계를 그대로 표시한다. |
| **Operation** | local/explicitly approved model route만 사용한다. 회사 corpus를 외부 API·memory·telemetry·cloud로 보내지 않는다. licensed upstream code만 복사한다. Git rename/dirty tree/symbol migration/누락 의존성에서 unknown·재검토를 운영자가 볼 수 있어야 한다. 현재 백업/삭제 journal/restore/lease 장애 복구를 느슨하게 하지 않는다. |
| **품질 평가** | 중복 재제안 감소, 정당한 re-proposal 누락, 거절 이유의 scope 오염, outdated optional 반환, required unknown 처리, 한국어/조건/부정 손실을 **동일 근거 묶음**으로 평가한다. replay에서 후속 입력 동일성을 가정하지 않는다. 이런 검증은 이번 조사에서 실행하지 않았다. |

## 10. 남은 공개 증거 공백과 제한

1. **영상 전체 source**: facts/corrections/recurring investigations의 정확한 prompts, grouping/evidence rules, final report composer, 당시 dashboard/server/SQL 전체, 실행 manifest/모델 version/비용 breakdown을 단일 공개 source로 확보하지 못했다.
2. **승인·기각 구현**: 영상 자체의 승인 UI, ledger schema, actor authentication, approval freshness, rejected-memory consumption job, early extraction criteria feedback engine은 원 자막/검토 source로 확인되지 않았다.
3. **코드 invalidation 완전성**: code-map이 실제 영향을 빠짐없이 연결하는지, rename/dirty branch/refactor/change 이후 어떤 rule을 언제 숨기거나 재검토하는지 공개 proof가 없다.
4. **품질·보안 결과**: “2 cents/session” 등 제작자 사례를 우리 비용 또는 일반 요금으로 재사용하지 않았다. 한국어 memory 정확성, adversarial robustness, company-grade egress/deletion, 실제 downstream model input/규칙 준수도 이 영상으로 입증되지 않는다.
5. **원문 시청 한계**: cue text를 원 JSON3와 확인했지만 단어 단위 시간·발화자·영상 화면 approval UI를 수동 검증하지 않았다.
6. **공개성 조사 범위**: AI That Works 전체 current recursive tree/index, episode 및 이전 memory 자료, HumanLayer/Boundary public organization 목록, 위 후보 repository tree와 memory 관련 source를 검사했다. HumanLayer의 모든 repository content/모든 branch를 포괄한 것은 아니다. 뒤쪽 추가 GitHub API 조회가 unauthenticated rate-limit HTTP 403으로 종료되었지만, 핵심 source들은 고정 commit raw URL로 읽었다. 이 제한은 **‘공개 전체 pipeline 없음’의 전역 증거를 낼 수 없는 이유** 중 하나다.
7. **현재 앱의 정적 비교 한계**: 지정 worktree는 진행 중인 구현이다. 위 file digest 관찰 이후 바뀔 수 있다. 이 문서의 부재 판단은 명시된 search/input/reference 범위에 한정하고, 자동 완전성 보장을 약속하지 않는다.

**부모 통합에 사용할 문장:** “메모리 pipeline의 가치 있는 공개 원리는 cross-session evidence, final-report incremental context, durable feedback와 code-linked review다. 그러나 #77 디렉터리에는 실행 source가 없고, 찾은 별도 memory code/recipe는 영상 전체 시스템과 다르다. 기존 agents_memory의 권한·snapshot·삭제·host 계약은 유지하고, 코드 의존성 review와 승인/기각 incremental 입력을 연구 후보로만 평가한다.”

## 출처

### 원 영상 / episode

- [V1] [원 YouTube 영상·설명](https://www.youtube.com/watch?v=mAKUL12h1n8). 이번 조사에서 watch HTML의 `ytInitialPlayerResponse.videoDetails` / microformat 직접 추출: ID/title/author/lengthSeconds/전체 shortDescription/publishDate. 보관 원 `en-orig JSON3` 및 timed captions는 §2 경로·digest. 특정 논의는 §4의 timestamp 링크.
- [R1] [AI That Works README, 고정 commit](https://github.com/ai-that-works/ai-that-works/blob/738a9c18b0302737d5d354d9988f34482966cce6/README.md).
- [R2] [#77 metadata](https://github.com/ai-that-works/ai-that-works/blob/738a9c18b0302737d5d354d9988f34482966cce6/2026-10-06-building-a-memory-pipeline/meta.md).
- [R3] [공식 Boundary #77 podcast page](https://boundaryml.com/podcast/2026-10-06-building-a-memory-pipeline).
- [R4] [#77 directory, 고정 commit](https://github.com/ai-that-works/ai-that-works/tree/738a9c18b0302737d5d354d9988f34482966cce6/2026-10-06-building-a-memory-pipeline); [전체 recursive tree API](https://api.github.com/repos/ai-that-works/ai-that-works/git/trees/738a9c18b0302737d5d354d9988f34482966cce6?recursive=1).
- [R5] [#13 context/memory README](https://github.com/ai-that-works/ai-that-works/blob/738a9c18b0302737d5d354d9988f34482966cce6/2025-07-08-context-engineering/README.md).
- [R6] [#14 DRM README](https://github.com/ai-that-works/ai-that-works/blob/738a9c18b0302737d5d354d9988f34482966cce6/2025-07-15-decaying-resolution-memory/README.md).
- [R7] [#14 Redis 검사/export](https://github.com/ai-that-works/ai-that-works/blob/738a9c18b0302737d5d354d9988f34482966cce6/2025-07-15-decaying-resolution-memory/examine_threads.py); [main entry](https://github.com/ai-that-works/ai-that-works/blob/738a9c18b0302737d5d354d9988f34482966cce6/2025-07-15-decaying-resolution-memory/main.py).
- [R8] [#14 redaction Python](https://github.com/ai-that-works/ai-that-works/blob/738a9c18b0302737d5d354d9988f34482966cce6/2025-07-15-decaying-resolution-memory/redact_pii.py).
- [R9] [#14 external-model redaction BAML](https://github.com/ai-that-works/ai-that-works/blob/738a9c18b0302737d5d354d9988f34482966cce6/2025-07-15-decaying-resolution-memory/baml_src/redact_pii.baml).

### 실제 관련 public code

- [C1] [Boundary curator](https://github.com/BoundaryML/baml-demos/blob/dcc3d33f0fd2635d18515a62a10da91ae789f080/aie/baml_src/ns_memory/curator.baml).
- [C2] [Boundary memory store/recall](https://github.com/BoundaryML/baml-demos/blob/dcc3d33f0fd2635d18515a62a10da91ae789f080/aie/baml_src/ns_memory/memory.baml).
- [C3] [Boundary supervisor 실제 callsites](https://github.com/BoundaryML/baml-demos/blob/dcc3d33f0fd2635d18515a62a10da91ae789f080/aie/baml_src/ns_agent/agent.baml).
- [C4] [HumanLayer feedback controller](https://github.com/humanlayer/skills/blob/653b6411c1f70c275a18e37673b042ff99f67ceb/plugins/build-iterated-agentic-loop/skills/build-iterated-agentic-loop/references/agent-iteration.ts).
- [C5] [HumanLayer memory template](https://github.com/humanlayer/skills/blob/653b6411c1f70c275a18e37673b042ff99f67ceb/plugins/build-iterated-agentic-loop/skills/build-iterated-agentic-loop/references/memory-template.md); [MIT LICENSE](https://github.com/humanlayer/skills/blob/653b6411c1f70c275a18e37673b042ff99f67ceb/LICENSE).
- [C6] [Boundary feelings](https://github.com/BoundaryML/feelings/blob/e0f07b4ad1e01b4cd1326c8bc28e6e68041602d7/README.md).
- [C7] [Boundary address analytics demo](https://github.com/BoundaryML/analytics-demo/blob/8125575a5e2904283a60ce701c4d17bb4526f1de/README.md).
- [C8] [Boundary cloud dashboard starter](https://github.com/BoundaryML/boundary-dashboard-template/blob/c61fb20327a9b7f00f6bcbd8175803710303aa25/README.md).

### BAML / Jev

- [B1] [현행 BAML 설명](https://boundaryml.com/explore.md); [Apache-2.0 LICENSE](https://github.com/BoundaryML/baml/blob/cd10232f9e39088ab046ddb8116ffb2a36919785/LICENSE).
- [B2] [v0 checks/asserts와 version notice](https://docs.boundaryml.com/guide/baml-advanced/checks-and-asserts.md).
- [B3] [실제 BAML TypeSafe client](https://github.com/BoundaryML/baml/blob/cd10232f9e39088ab046ddb8116ffb2a36919785/baml_language/crates/baml_builtins2/baml_std/typesafeai/client.baml).
- [B4] [실제 Jev type→question mapping/request](https://github.com/BoundaryML/baml/blob/cd10232f9e39088ab046ddb8116ffb2a36919785/baml_language/crates/baml_builtins2/baml_std/typesafeai/ns_internal/jev.baml).
- [J1] [TypeSafe API](https://docs.typesafe.ai/api.md).
- [J2] [Jev 1.13 jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13.md), 문서 Last reviewed `2026-10-02`.
- [J3] [TypeSafe current models·언어·data handling](https://docs.typesafe.ai/models.md), 조사일 current 상태. 과거 영상 당시의 exact model/pricing 재현 자료는 아님.

### 현재 worktree 정적 근거

아래 file 링크는 공개 GitHub source가 아니라 지정 로컬 worktree다. line 번호와 §7 digest로 관찰 범위를 추적한다.

- [L1] [architecture §5–7](file:///Users/namdoo/.agent-flow/worktrees/agent-memory-mcp-97e899f21134/feat-local-first-memory-pipeline/docs/architecture.ko.md#L93-L147).
- [L2] [domain.py:132–219,320–363](file:///Users/namdoo/.agent-flow/worktrees/agent-memory-mcp-97e899f21134/feat-local-first-memory-pipeline/src/agents_memory/domain.py).
- [L3] [models.py:423–434,497–513,557–568](file:///Users/namdoo/.agent-flow/worktrees/agent-memory-mcp-97e899f21134/feat-local-first-memory-pipeline/src/agents_memory/models.py).
- [L4] [jobs.py:82–111,127–136](file:///Users/namdoo/.agent-flow/worktrees/agent-memory-mcp-97e899f21134/feat-local-first-memory-pipeline/src/agents_memory/jobs.py).
- [L5] [store.py:503–520,543–596,888–1048,1802–1825,1860–1883,1953–1979](file:///Users/namdoo/.agent-flow/worktrees/agent-memory-mcp-97e899f21134/feat-local-first-memory-pipeline/src/agents_memory/store.py).
- [L6] [context.py:61–89](file:///Users/namdoo/.agent-flow/worktrees/agent-memory-mcp-97e899f21134/feat-local-first-memory-pipeline/src/agents_memory/context.py).
- [L7] [semantic_contract.py:105–159](file:///Users/namdoo/.agent-flow/worktrees/agent-memory-mcp-97e899f21134/feat-local-first-memory-pipeline/src/agents_memory/semantic_contract.py), memory engine 자체 source contract freshness와 사용자 code dependency freshness 구분.
