# 독립 MCP 메모리: 학술 근거·로컬/클라우드 동등성·평가·지속 공격

조사 기준일: **2026-10-11**. 대상은 Claude Code, Codex 및 다른 클라이언트가 사용하는 외부 기억이며, **외주회사 업무의 로컬 파이프라인과 집·개인환경의 cross-device 클라우드 파이프라인을 분리하면서 동일 설계·계약을 재사용**하는 요구를 포함한다. 회사 자료를 개인 cloud에 자동 동기화하는 안이 아니다. Agent Flow core에 자체 store를 넣거나 호스트의 기존 메모리를 대체하는 안도 아니다. 이 문서는 공개 논문 원문과 학회 원문을 검토한 조사이며, 논문의 시스템·벤치마크를 직접 실행하지 않았다. 모든 성능 수치는 **저자 보고**다. 아래 날짜는 최초 공개일과 실제 읽은 판본 날짜를 구분하며, 2026년 preprint는 출판·독립 재현의 보증이 아니다.

## 1. 결론부터

**논문 근거가 지지하는 것은 ‘많이 저장하면 더 똑똑해진다’가 아니라, 원문을 보존하고 출처·유효시점·범위를 붙여 필요한 증거를 회상하며, 검증된 실패/성공 피드백만 재사용 가능한 교훈으로 승격하는 시스템이다.** MemGPT는 외부 기억으로 context를 관리하는 가능성, LongMemEval은 원문 손실·시간·갱신·기권의 중요성, Reflexion은 피드백 기반 행동 개선의 가능성을 보여준다. 반대로 MemoryArena는 대화 QA 고득점이 연속 행동 성공을 뜻하지 않음을, 2026년 poisoning 연구는 저장된 ‘과거 성공’이 공격의 지속 매개가 될 수 있음을 보여준다. [P1][P3][P8][P13][P16][P20][P21]

따라서 권고는 **명시적 외부 기억 + 불변 증거 + 보수적 승격 + 권한 제한된 회상 + 별도 reflect + 비용/행동/보안이 분리된 평가**다. Graphiti/Hindsight와 같은 그래프·reflect 구현은 참고·후보이며, 서로 다른 논문 점수의 순위로 채택하지 않는다. 클라우드 공유·OAuth·동시 수정·삭제·백업은 아래 학술 실험만으로 검증되지 않는다.

## 2. ‘기억’과 ‘학습’의 구분

| 구분 | 실제로 바뀌는 것 | 독립 MCP로 가능한 범위 | 주의점 |
| --- | --- | --- | --- |
| Context/외부 기억 | DB·파일·벡터·그래프의 내용과 이후 prompt에 들어가는 증거 | opaque Claude/Codex 모델에도 tool 호출·context 주입으로 적용 가능 | 모델 가중치는 그대로다. 잘못된 기억도 더 지속적으로 재사용될 수 있다. [P1][P5][P6] |
| Verbal/episodic learning | 실패 피드백, 교훈, 다음 시도의 지시문 | 결과 증거를 남기고 검증된 교훈을 후속 작업에 회상 | Reflexion의 ‘verbal reinforcement learning’은 가중치 RL이 아니다. 내부 재시도·평가 호출 비용까지 맞춰야 한다. [P3] |
| 모델 가중치 학습 | fine-tuning/RL 또는 test-time neural memory의 파라미터 | 모델·학습 인프라를 통제해야 가능 | Titans는 아키텍처 내부 neural memory를 gradient로 갱신한다. 이를 MCP store로 붙이는 것은 같은 방법이 아니다. MemoryBank의 SiliconFriend LoRA와 외부 검색 개선도 분리해야 한다. [P10][P12] |
| 검색 개선 | 필요한 원문/evidence ID를 더 잘 가져옴 | Recall@k·NDCG·권한/시점 필터로 측정 | 정답 근거가 있어도 reader가 잘못 판단할 수 있다. [P8] |
| 행동 개선 | 다음 작업의 올바른 수정·테스트 통과·규칙 준수 | 다중 세션 coding workload와 실제 결과 판정으로 측정 | QA 점수·‘믿을 만한 대화’와 다르다. 검색 성공이 tool 실행 권한을 주지 않는다. [P2][P13][P16] |

**‘메모리 전체를 모델이 계속 학습한다’, ‘MCP를 붙이면 Claude/Codex 가중치가 개인화된다’는 이 조사로 뒷받침되지 않는다.** 가능한 것은 외부 기록을 이용한 in-context adaptation이다.

## 3. 핵심 논문 비교표

표의 ‘적용’은 본 조사자의 **설계 추론**이며 해당 논문이 cross-client coding cloud MCP를 실험했다는 뜻이 아니다. 정확한 workload·판본을 고정하지 않은 제품 마케팅의 ‘최고 점수’는 별도 근거로 취급하지 않았다.

### 3.1 기억 구조와 학습 루프

| 논문·공개/판본 날짜 | 방법 | 실험 workload·측정 | cross-client coding memory에 적용 / 한계 |
| --- | --- | --- | --- |
| **MemGPT: Towards LLMs as Operating Systems** — 2023-10-12, 읽은 v2 2024-02-12 [P1] | 작은 main context와 archival/recall 외부 기억; 모델의 함수 호출로 paging·수정·검색·heartbeat를 수행 | Multi-Session Chat 기반 5세션 대화 후 DMR QA; NQ 문서 QA; UUID nested key-value 탐색. GPT-4 계열 등 | 세션 context와 장기 store를 분리하는 직접적 근거. 그러나 오래된 작은 context 기준이며, cloud identity·기기 동기화·동시 수정·보안은 실험하지 않았다. |
| **Generative Agents: Interactive Simulacra of Human Behavior** — 2023-04, 읽은 v2 2023-08-06 [P2] | 관찰 memory stream; relevance/recency/importance 검색; 상위 reflection과 계획을 다시 기억 | GPT-3.5-turbo 기반 25 Smallville 에이전트, 2 game days; 인터뷰·사람의 believability 평가와 ablation | 관찰→증거 연결된 reflection→계획의 계층을 참고. 사회적 그럴듯함은 코딩 정확성·사실성·권한 준수와 다르다. 모델이 만든 중요도 점수는 신뢰도가 아니다. |
| **Reflexion: Language Agents with Verbal Reinforcement Learning** — 2023-03, 읽은 v4 2023-10-10 [P3] | Actor/Evaluator/Self-reflection; 환경 피드백을 텍스트 교훈으로 다음 시도에 제공; 가중치 갱신 없음 | ALFWorld 134 환경, HotPotQA 100문항, HumanEval/MBPP Python·Rust, LeetcodeHard 40. 코딩은 자체 생성 테스트를 사용한 반복 수정 후 hidden test 평가 | 실제 실패 원인·환경 결과를 교훈으로 저장하는 근거. 주로 동일 문제의 재시도이며 범용 평생 학습이나 Claude↔Codex 전이는 미검증. self-test 성공은 정답 보장이 아니다. |
| **A-Mem: Agentic Memory for LLM Agents** — 2025-02-17, 읽은 v11 2025-10-08 [P4] | Zettelkasten형 원자 note에 원문·시각·키워드·태그·context·embedding·링크; 새 기억이 기존 note의 표현과 관계를 evolve | LoCoMo와 DialSim; GPT-4o-mini/4o 및 여러 작은 open model; F1/BLEU 등. 검색 k를 질문 범주별 조정 | 이슈/결정/교훈 간 링크를 만들 수 있다. 기존 note 표현을 evolve하여 대체하는 방식은 출처 손실·오승격 위험이 있어, 우리 안에서는 원문/버전과 파생 note를 분리해야 한다. |
| **Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory** — v1 2025-04-28 [P5] | 새 메시지쌍·요약·최근 문맥에서 fact 추출; 기존 기억과 ADD/UPDATE/DELETE/NOOP. Mem0g는 entity/relation graph와 충돌 invalidation | 공개 LoCoMo 10대화; GPT-4o-mini; F1/BLEU·LLM judge J·검색/전체 응답 지연·회상 token. unanswerable adversarial 범주 제외 | 명시적 CRUD와 중복/충돌 관리의 실용적 패턴. 자동 fact 압축은 세부사항을 잃는다. 논문의 query 비용 절감은 전체 write/consolidation 비용 절감과 다르고, cloud 서비스/SDK 전체 기능의 증명이 아니다. |
| **Zep: A Temporal Knowledge Graph Architecture for Agent Memory** — v1 2025-01-20 [P6] | Graphiti: 원문 episode→entity/fact edge→community summary; event valid/invalid 시간과 transaction created/expired 시간을 분리; vector/BM25/BFS·재순위화 | DMR 500, LongMemEval-S 500(~115k token); graph 구축 GPT-4o-mini-2024-07-18, reader GPT-4o-mini 및 GPT-4o-2024-11-20 | ‘당시 참이었던 결정’과 ‘현재 유효한 규칙’을 분리하기 좋다. 최신 입력을 우선 invalidation하는 정책은 출처의 권위 판정이 아니다. Zep 서비스 실험을 bare Graphiti의 동일 성능 보장으로 읽지 않는다. |
| **Hindsight is 20/20: Building Agent Memory that Retains, Recalls, and Reflects** — v1 2025-12-14; **Hindsight: Structured Agent Memory that Retains, Recalls, and Reflects**, ACL demo 2026-07 [P7][P7a] | world facts / agent experiences / neutral observations / subjective opinions의 4 logical network; TEMPR retain/recall, CARA reflect. vector·keyword·graph·time 검색을 RRF/재순위화, token budget 내 증거 선택 | LongMemEval-S·LoCoMo QA; GPT-OSS-20B/120B·Gemini-3 Pro 구성, GPT-OSS-120B judge. ACL demo는 PostgreSQL+pgvector 구현 소개 | 사실/경험/파생 관찰을 구분하고 retain/recall/reflect 인터페이스를 참고. reflect가 의견을 써넣을 수 있으므로 read-only 분석과 persistent 변경을 분리해야 한다. 논문의 confidence는 믿음 강도이지 교정된 진실 확률이 아니다. v1 재현 조건 누락은 §4 참조. |
| **MemoryBank: Enhancing Large Language Models with Long-Term Memory** — 2023-05-17, 읽은 v3 2023-05-21 [P10] | 대화·일별/전체 event summary·user personality; dense 검색; Ebbinghaus형 decay와 접근 시 강화 | 15 가상 사용자×10일, 194 probing QA와 실제 대화 정성 사례. SiliconFriend는 심리 대화 약38k로 LoRA tuning | 중요하지 않은 cache의 우선순위 조절에 참고. 사용 빈도는 사실성/권한의 근거가 아니며, 보안 규칙·repo 결정을 오래 안 썼다는 이유로 삭제하면 안 된다. LoRA 효과와 memory 효과를 혼동하지 않는다. |
| **Memory OS of AI Agent** — arXiv 메타데이터 공개일 2025-05-30, 읽은 v1 [P11] | STM→FIFO dialogue-chain MTM pages/segments→heat 기반 long-term personal memory; 방문·길이·recency를 승격에 사용 | LoCoMo, GPT-4o-mini 등; F1/BLEU·개인화 기억 | 단기 작업 기록/중간 요약/장기 profile의 구분은 유용. ‘뜨거운’ 잘못된 설명의 반복이 자동 승격될 수 있어 heat를 trust로 취급하지 않는다. companion profile은 repo별 사실과 별개다. |
| **Titans: Learning to Memorize at Test Time** — v1 2024-12-31 [P12] | neural long-term memory module이 associative loss의 gradient·surprise·momentum·decay로 test-time 갱신; attention과 MAC/MAL/MAG 결합 | 언어 모델링·상식 추론·needle retrieval·시계열·DNA; 매우 긴 context 실험 | 외부 기억과 모델 내부 기억의 경계를 설명하는 비교 논문. 모델 아키텍처 접근 없는 Claude/Codex API에 MCP만으로 적용할 수 없다. ‘2M context’와 DB의 장기 보존량은 다른 수치다. |

### 3.2 평가·통제·지속 공격

| 논문·공개/판본 날짜 | 방법 | workload·측정 | 우리 설계에 적용 / 한계 |
| --- | --- | --- | --- |
| **LongMemEval: Benchmarking Chat Assistants on Long-Term Interactive Memory** — 2024-10-14, 읽은 v2 2025-03-04; ICLR 2025 [P8] | extraction·multi-session·temporal·knowledge-update·abstention 5능력; memory indexing/retrieval/reading을 분리 | human-curated 500 QA; evidence 세션은 Llama-3-70B 생성+사람 수정, irrelevant 대화 첨가. S~115k, M~1.5M token. GPT-4o-2024-08-06 judge; evidence Recall@k/NDCG 별도 | repo 의사결정 변경·timestamp·모르는 질문을 포함한 최소 진단용. 원문을 유지하고 index key만 fact로 enrich하는 결과가 중요. QA이며 수정 행동 성공을 측정하지 않는다. |
| **Evaluating Very Long-Term Conversational Memory of LLM Agents (LoCoMo)** — v1 2024-02-27 [P9] | persona·temporal event graph로 긴 다중 세션 대화 생성 후 사람 검토; evidence 기반 QA, event summary, multimodal generation | 원 논문 50대화, 평균304.9turn/19.3session/9,209token, 최대35session; 5 QA범주, F1 등 | 대화 기억의 기본 진단. natural user 50명의 대화가 아니며, QA의 adversarial은 ‘답할 수 없음’이지 prompt injection 공격이 아니다. 이후 10대화 release 사용 연구와 동일 corpus로 간주하지 않는다. |
| **Benchmarking Agent Memory in Interdependent Multi-Session Agentic Tasks (MemoryArena)** — 2026-02-18, 읽은 v2 2026-09-17 [P13] | session 간 raw trace 대신 memory만 전달, 후속 subtask가 앞선 action/feedback에 의존하는 Memory-Agent-Environment loop | v2 701 task: shopping150/travel270/search221/math40/physics20; 평균6.9 의존 subtask·57 action; success rate/partial progress | ‘잘 기억해서 다음 행동이 좋아지는가’를 별도 검증하는 근거. web/math/physics이며 coding은 아니다. agent 능력과 memory 효과가 섞여 paired fixed-agent 대조가 필요. v1/v2 task 수를 혼합하지 않는다. |
| **MemDelta: Controlled Baselines and Hidden Confounds in Agent Memory Evaluation** — v1 2026-06-29 [P14] | 동일 파이프라인의 embedding 교체, question-only/random-chunk/verbatim RAG/full-context/self-managed memory 대조; bootstrap CI·paired McNemar | LongMemEval-S. GPT-4o-mini 전체500; Sonnet/Gemini 일부 subset. 512-token chunk·top10 RAG; Mem0 비교는 n=88의 2 question type만 | 복잡한 메모리보다 embedding·budget·baseline이 점수를 설명할 수 있음을 통제. subset은 앞 n개라 범주 편향이 있고, Mem0/RAG embedding까지 완전히 같지는 않다. ‘memory는 필요 없다’는 보편 결론은 부당하다. |
| **LongMemEval-V2: Evaluating Long-Term Agent Memory Toward Experienced Colleagues** — v1 2026-05-12 [P15] | static state·dynamic tracking·workflow/gotcha·premise awareness; InsertTrajectory→Query→고정 reader. raw/events/strategy pool 및 파일 기반 coding agent evidence gathering | WebArena·WorkArena/++에서 successful/failed trajectory를 모은 451 human QA; small100 trajectory~25M token, medium500~115M token | 대화 profile보다 실행 흔적·실패·절차를 기억할 coding memory 평가에 가깝다. 여전히 evidence를 모아 QA하는 평가이며 미래 실제 작업 성공을 직접 측정하지 않는다. |
| **MemSecBench: Tracking Agent Memory Poisoning from Persistence to Consequence and Repair** — v1 2026-07-29 [P16] | Write–Execute–Forget. write 후 snapshot을 복제해 execution/repair 독립 평가; 저장·회상·adoption·외부 결과·benign 보존을 분리 | 310 case/48 context; OpenClaw·Hermes×Native/Mem0/Mem0Graph/A-MEM×DeepSeek-V4-Pro/MiniMax-M3/GPT-5.5=24구성. 2명 인간500 record 검토 | MCP의 write 허용만이 아니라 회상 후 행동과 삭제 후 회복까지 검증하는 강한 틀. benchmark adapter/harness/모델 전체 결과이며 특정 DB만의 취약률이 아니다. 계정 획득이나 cloud 인증 우회 실험은 아니다. |
| **Poison Once, Exploit Forever: Environment-Injected Memory Poisoning Attacks on Web Agents (eTAMP)** — 2026-04-03, 읽은 v2 2026-04-07 [P17] | web page content가 raw trajectory에 남아 다음 task에서 무단 cross-site 행동을 유도; 과부하/도구 오류 frustration 조건 | 약280 paired cross-site task; controlled pseudo Task-A trajectory에 payload를 넣은 Table1; GPT-5-mini/5.2 등; attacker URL 방문 ASR·clean task success | private cloud라도 repo/docs/tool result를 기억하면 간접 유입이 남는다. consolidated memory와 raw trace를 구분한다. 높은 ASR를 자연 유입 end-to-end 감염률로 쓰면 안 된다. |
| **Memory Poisoning Attack and Defense on Memory Based LLM-Agents** — v1 2026-01-09 [P18] | EHR MINJA 재현, input/output moderation와 memory sanitization의 2단계 방어 | MIMIC-III의 1 victim-target pair, 50 synthetic indication prompt; GPT-4o-mini/Llama-3.1-8B, Gemini defense 추가 | 학습된 신뢰 점수·기억량·오탐을 점검할 보조 근거. 단일 pair·작은 initial memory로 ‘큰 정상 corpus면 안전’을 일반화할 수 없다. 표/서술의 일부 수치 불일치로 수치 인용은 보류. |
| **MemPoison: Uncovering Persistent Memory Threats and Structural Blind Spots in LLM Agents** — v1 2026-07-16 [P19] | fact/preference/instruction/state 공격; 단일 명시 독·개별 정상처럼 보이는 조합·조건부 dormant 활성화; counterfactual interaction 진단 | 1,227 hand-validated case; user/tool/cross-agent channel; flat chunk/fact store/hierarchical notes, 여러 open/closed model | write-time filter만으로 조합/조건부 poison을 막는다고 가정하지 않는다. retrieval-time context와 authority 확인, cross-agent scope 평가 필요. 외부 기억 공격이며 모델 가중치 poisoning과 다르다. |
| **Memory Injection Attacks on LLM Agents via Query-Only Interaction (MINJA)** — 읽은 v5 2026-02-12 [P20] | 공격자는 DB를 못 쓰고 일반 query/feedback만 사용; bridging reasoning과 indication prompt를 점점 줄여 plausible record를 남김 | RAP/WebShop, EHRAgent/MIMIC-III·eICU, QA/MMLU; GPT-4/4o; agent/dataset별9 victim-target pair. injection·새 victim query·비표적 benign query 분리 | shared memory bank 가정은 tenant/repo/role isolation의 근거. user feedback을 진실 검증으로 취급하지 않는다. private bank는 cross-user 경로를 줄이나 환경 유입과 계정 침해까지 해결하지 않는다. ASR는 targeted reasoning 생성이지 모든 경우 실제 위해 행동 판정은 아니다. |
| **MemoryGraft: Persistent Compromise of LLM Agents via Poisoned Experience Retrieval** — v1 2025-12-18 [P21] | 문서의 실행 가능한 code가 benign/poisoned 경험 store를 만들게 함; ‘validated success’처럼 보이는 절차를 lexical+semantic union retrieval로 재사용 | MetaGPT DataInterpreter+GPT-4o, 100benign+10poison seed, 12 handcrafted probe; 주 정량 지표 poisoned retrieval proportion | 성공 기억의 의미 모방·절차 세탁 공격을 coding eval에 추가. provenance 없는 executable documentation·semi/white-box 단일 agent라는 강한 조건. 검색 오염 비율을 실제 unsafe action ASR로 바꾸어 쓰지 않는다. 방어안은 제안이지 효과 실측이 아니다. |

## 4. 성능 수치: 원문 조건과 인용 금지선

아래는 비교 순위가 아니라 **수치의 읽는 법**이다. 다른 행 사이의 점수는 모델·dataset variant·judge·metric·budget이 달라 비교하지 않는다. `%p`는 절대 percentage point, ‘상대 %’는 비율 변화다.

| 출처·원문 위치 | 저자 보고 수치와 실험 조건 | 올바른 해석 / 제한 |
| --- | --- | --- |
| MemGPT v2 §3.1/Table2 [P1] | DMR GPT-4-Turbo(`gpt-4-1106-preview`): recursive summary 35.3% vs MemGPT 93.4%; GPT-4(`gpt-4-0613`): 32.1% vs92.5% | 요약만 있는 baseline과 전체 과거를 검색할 수 있는 memory의 차이. 같은 정보량의 최신 full-context와의 비교가 아니다. 작은 DMR을 현재 모델도 반드시 같은 폭으로 개선한다고 주장할 수 없다. |
| Reflexion v4 coding Table [P3] | HumanEval Python pass@1 91.0 vs GPT-4 baseline80.1; MBPP Python77.1 vs baseline80.1 | 최종 1개 해를 hidden test로 판정하지만 그전에 자체 테스트·reflection·재시도를 사용한다. single-call pass@1 상승이나 전 workload 개선이 아니다. 내부 생성/평가 비용을 포함한 대조가 필요하다. |
| Mem0 v1 Table2 [P5] | GPT-4o-mini, 10대화 LoCoMo·unanswerable 제외: J full-context72.90±0.19 / Mem0 66.88±0.15 / Mem0g68.44±0.17. memory/context token 26,031/1,764/3,616. p95 전체 응답17.117/1.440/2.590초 | **이 실험은 full-context의 품질이 더 높고 memory는 비용·지연 trade-off**다. ‘26% improvement’는 OpenAI memory baseline J52.90 대비 Mem0의 상대 개선이지 +26%p나 full-context 초과가 아니다. J는10회 judging 평균/표준편차이며 dataset sampling CI와 다르다. 읽은 원문에서 정확한 judge endpoint/snapshot을 확정하지 못했다. 비용은 회상·응답 범위이며 ingestion/갱신 총비용까지 입증하지 않는다. |
| Zep v1 DMR Table [P6] | Zep94.8 vs full-context94.4; MemGPT93.4는 이전 연구 수치. Zep DMR reader는 `gpt-4-turbo-2024-04-09` | MemGPT Turbo endpoint와 다르며 DMR가 현대 context에 들어가는 조건이다. 소수 차이를 memory architecture의 결정적 우위로 읽지 않는다. Boston laptop→AWS us-west-2 지연 실험은 우리 cloud/클라이언트의 지연 보장이 아니다. |
| Hindsight v1 §7.3/Table3–4 [P7] | LongMemEval-S500: 동일 GPT-OSS-20B full-context39.0→Hindsight83.6(44.6%p). Table4 LoCoMo OSS-20B83.18, OSS-120B85.67, Gemini-3 89.61. 자체 judge GPT-OSS-120B temp0 | **§7.3 retrieval token budget이 `<add>` placeholder로 남아 있어 원문만으로 동일 예산 재현 불가.** §1 기여 서술은 20B LoCoMo85.67로 쓰지만 Table4는 그 수치를120B에 부여하므로 표를 우선하고 불일치를 표시한다. 이전 baseline들은 타 보고서/GPT-4o judge와 Backboard의 주장 수치를 가져와 자체 judge와 섞였다. ‘모든 방법 동일 judge’ 설명도 이 출처 설명과 긴장한다. 따라서 vendor 간 우위 순위는 인용하지 않는다. ACL demo의20B LoCoMo83.2는 Table4 반올림과 부합한다. |
| MemDelta v1 §4–6 [P14] | 동일 GPT-4o-mini·LongMemEval-S500·verbatim chunk/top10 pipeline: MiniLM embedding47.2%→`text-embedding-3-small`53.4%, paired McNemar p=.004. full-context49.8 vsMiniLM47.2 p=.34 | pipeline 고정 후 embedding 교체만으로6.2%p 차이가 났다는 통제 근거. p=.34는 통계적 유의 차이를 못 찾았다는 뜻이지 equivalence 증명은 아니다. Mem0 n88/2범주72.7 vscloud-RAG73.9/p1.0은 제한된 비교이며 Mem0 `ada-002`와 RAG embedding도 다르다. cloud endpoint·judge·부분집합 선택·추가 write비용을 모두 남겨야 한다. |
| eTAMP v2 Table1/footnote [P17] | GPT-5-mini frustration없음3.6%→frustration32.5%; GPT-5.2 6.4→23.4%. pseudo Task-A poisoned trajectory, Chaos Monkey click-drop.4/scroll-swap1/type Caesar-cipher1; maxstep15→37 | conditional stress test의 공격 URL 방문 ASR. 실제 자연 웹 페이지에서 retain까지 포함한 감염률이 아니며 clean task 성공이 낮아지는 조건도 봐야 한다. ‘현재 Claude/Codex도32.5% 감염’ 같은 전이는 금지한다. |
| MemSecBench v1 Abstract/평가 정의 [P16] | 집계 poisoned84.2%, end-to-end consequence50.3%는 전체 case 기준. execute59.6%, repair56.1%는 **poison 성공 상태 기준** | 분모가 달라 ASR 수치를 단순 비교하면 안 된다. repair는 독 제거/무력화 **및 요구 benign 정보 보존**을 모두 요구한다. 전체삭제나 delete tool 호출로 성공 판정하지 않는다. |
| MemoryGraft v1 §5.2–5.3 [P21] | 110seed/12probe, lexical·vector 각top3 union: 전체48retrieved record 중23poison, PRP47.9% | **retrieved item 비율**이지 task47.9%가 실제 악성 명령을 실행했다는 지표가 아니다. 안전한 과거 성공도 agent가 오염된 관찰에서 잘못 생성할 수 있으므로 서명만으로 의미적 안전이 보장되지 않는다. |

A-MEM의 token 절감도 retrieval/QA와 write/evolution의 생애주기 비용을 구분해야 하며, 범주별 k 조정·F1 기반 결과를 Mem0의 J나 Hindsight accuracy와 붙여 순위표를 만들면 안 된다. MemoryOS의 추상적 평균 상대 개선 주장 역시 baseline·범주·분모를 재현해 확인하기 전에는 우리 채택 효과의 수치로 쓰지 않는다. [P4][P11]

## 5. 평가 누수·오승격·지속 공격은 서로 다르다

1. **평가 누수:** ingestion/reflect가 정답·hidden test·judge feedback을 보았거나, 같은 test issue/trajectory를 development tuning에 사용하여 held-out처럼 보고하는 경우다. 모델의 사전학습 contamination 가능성과도 구분한다. Reflexion은 코딩 refine에 hidden test를 쓰지 않고 자체 테스트를 사용한다고 설명하지만, 공개 HumanEval 점수만으로 현대 coding-model contamination이 해결되지는 않는다. [P3]
2. **오승격:** 악의 없이 observation을 preference/규칙으로 잘못 일반화하거나, 한 번의 성공을 범용 workflow로 올리는 것이다. Generative Agents의 reflection 환각·LongMemEval의 fact compression 손실·A-MEM의 evolution 구조가 이 위험과 연결된다. ‘프로젝트 X를 구현했다’에서 ‘사용자는 항상 X를 선호한다’를 만들어서는 안 된다. [P2][P4][P8]
3. **지속 poisoning:** attacker가 일반 query, README/web/tool result 또는 다른 agent 메시지를 통해 외부 기억을 오염시켜 후속 깨끗한 세션에 영향을 주는 공격이다. DB 직접 수정 없이도 가능하나 각 논문의 실제 write path·shared-bank·실행 가능한 문서·pseudo trajectory 조건을 밝혀야 한다. [P16–P21]
4. **가중치 poisoning/backdoor:** training data·weights가 바뀌는 공격이다. 외부 memory bank를 삭제해 되돌리는 공격과 같지 않으며 이 조사에서의 MCP 핵심 위협과 별도로 모델 공급망 문제다. [P12][P20]

**원문을 보존하는 것과 원문을 신뢰하는 것은 다르다.** 동일 기록에 integrity hash/서명이 있어도 attacker 입력을 모델이 ‘성공 교훈’으로 세탁하고 정상 writer가 서명할 수 있다. provenance는 누가/어디서/어떤 과정으로 썼는지 증명할 뿐 의미적 참·안전성·사용자 승인까지 증명하지 않는다. MemoryGraft의 cryptographic attestation은 제안이며 이를 완결된 방어로 보지 않는다. [P20][P21]

## 6. 부모 보고서에 바로 넣을 9개 설계 시사점

다음은 논문을 바탕으로 한 **[설계 추론]**이지 직접 검증된 구현 결과가 아니다.

1. **원문 event와 파생 기억을 분리한다.** 불변 raw evidence(사용자 발언/파일·commit·관찰·실행 결과) 위에 fact·decision·lesson·preference를 별도 revision으로 둔다. LLM 요약/evolve로 원문을 덮어쓰지 않는다. raw 보존 자체는 retention/privacy 정책 안에서만 한다. [P4][P7][P8]
2. **client보다 사용자·repo·역할의 의미적 범위를 먼저 잡는다.** Claude↔Codex에서 공통 기억을 쓰되 tenant/repo/workspace/role을 server-side 접근 경계로 두고, reviewer는 author의 자기합리화 기억을 기본 공유하지 않는다. 클라이언트명을 namespace로만 쓰면 목표인 cross-client transfer가 깨진다. MINJA의 shared-bank 가정·MemPoison의 cross-agent channel이 역할/사용자 격리 이유다. [P19][P20]
3. **write와 promotion을 분리한다.** retain은 기록/후보의 수용, promotion은 증거·유효범위·승인된 결과로 enduring lesson/explicit preference를 만드는 다른 행위다. 사용 빈도·모델 confidence·‘validated’라는 문자열·user thumbs-up만으로 권한 있는 정책이 되지 않는다. [P7][P10][P11][P20][P21]
4. **갱신에는 두 시간과 근거를 남긴다.** event time/validity와 ingestion/update time을 분리하고 supersedes/contradicts/source를 보존한다. 새 메시지는 ‘최신’일 수 있지만 repo 문서나 사용자 명시 결정보다 ‘권위’가 높다는 뜻은 아니다. temporal 그래프는 시간 처리 도구이지 신뢰 해결책이 아니다. [P6][P8]
5. **회상은 top-k 고정 대신 권한·시간·증거·token budget으로 제어한다.** BM25+vector hybrid를 단순 baseline으로 시작하고 필요한 경우 entity/time/graph expansion을 비교한다. 결과는 원문 근거 ID·시점·타입·scope·승격 상태를 제공하며 retrieved text는 tool 실행을 승인하지 않는다. 검색 keys는 enrich해도 reading value는 가능한 한 원문을 유지한다. [P6][P7][P8][P14]
6. **reflect는 기본 read-only이며 durable write는 제안/승격 단계로 돌린다.** ‘지난 실패에서 무엇을 배웠나’를 실행 결과에 연결하고 여러 source/evidence와 함께 candidate lesson으로 만든다. 자기 반성 문장이 자동으로 사실/선호가 되거나 의견 강화 loop를 도는 것은 피한다. query 실행 자체가 memory mutation을 일으키는지 명시한다. [P3][P7]
7. **QA와 실제 coding 행동을 별도 acceptance로 둔다.** LongMemEval형 시간·갱신·기권·evidence recall을 통과해도 후속 repo task 성공이 입증되지 않는다. MemoryArena형 다중 세션 dependency loop와 LongMemEval-V2형 실패/workflow/gotcha를 coding 전용 held-out workload로 옮겨야 한다. [P8][P13][P15]
8. **복잡한 메모리는 통제된 baseline을 이겼을 때만 채택한다.** no-memory, 원문 full-context가 가능한 subset, 같은 embedding/budget의 plain RAG, structured fact, graph, reflect를 같은 host model/agent로 비교한다. write+consolidate+recall+read+repair 전체 비용과 동시성/지연을 측정해 graph나 reflect의 추가 가치를 결정한다. [P5][P14]
9. **보안 acceptance는 Write–Execute–Forget와 benign utility를 함께 둔다.** poisoning 후 새 client/세션에서 독이 회상되고 행동에 채택되는지, 삭제가 파생 note·graph·cache까지 재활성화를 막는지, 필요한 정상 기억을 유지하는지 별도 측정한다. conditional ASR·전체 E2E ASR·복구율의 분모를 표시하고 모든 기억을 거부/삭제한 시스템을 성공으로 판정하지 않는다. [P16][P17][P19–P21]

이 원칙을 새 MCP에 적용하는 인터페이스 후보는 **retain evidence → propose fact/lesson → promote/revise → scoped recall → read-only reflect → explicit approved revision → forget/repair**다. 단, Hindsight와 똑같은 API나 opinion layer를 구현해야 한다는 결론은 아니다. 실제 cloud resource/보안 제약은 별도의 운영·프로토콜 근거와 결합해 결정해야 한다.

## 7. 채택 전 평가 의사결정안

### 7.1 최소 대조군과 통제

- 고정 host agent/model snapshot, prompt, tool permission, 검색 예산, total model-call/step budget, temperature, seed/실행 순서를 기록한다. A→B와 B→A 전이는 **각 host의 no-memory와 같은-host memory 대조**로 비교한다. 다른 모델의 성능차를 기억 효과로 오인하지 않는다.
- no-memory / matched plain RAG / raw+structured / +temporal graph / +reflect를 ablation으로 분리한다. question-only·random memory는 질문 자체로 정답을 맞히는 정도와 memory irrelevant noise를 파악하는 진단용이며 실제 product fallback이 아니다. [P14]
- corpus split·dataset release/hash·질문 범주·정답 가능성·evidence ID·모델/embedding/judge snapshot·repo commit·framework/adapter version을 남긴다. 전체 vs 부분 n, 첫 n vs 무작위 추출, 카테고리 k tuning을 표시한다. judge를 바꾸면 동일 answer들을 다시 같은 judge로 평가해야 한다. [P4][P5][P8][P14]
- paired CI/검정을 사용하고, 여러 비교에서의 선택 편향·judge와 writer/reader의 공통 오류를 밝힌다. 일부 사람 검토와 exact outcome gate를 병행한다. judge temp0는 수학적으로 영구 determinism이나 정확성을 보장하지 않는다.
- 로컬/클라우드 비교는 두 실험으로 분리한다. **contract parity**에서는 동일 model/prompt/embedding snapshot·동일 evidence와 policy로 transport·권한·철회·삭제 동작을 비교하고, **provider/hardware 변경 실험**에서는 local model/quantization·cloud provider·embedding·context budget 변경을 독립 변수로 두어 extraction fidelity·회상·행동·지연 변화를 측정한다. hosted snapshot을 고정할 수 없으면 해당 조건을 표시하며 output byte 동일성을 전제하지 않는다. [설계 추론; P4][P8][P12][P14]

### 7.2 기능 acceptance: 무엇을 각각 측정할지

| 축 | 코딩 메모리용 사례 | 지표·판정 |
| --- | --- | --- |
| 저장/승격 fidelity | issue의 실제 요청 vs agent의 추측, repo 결정 vs 개인 취향, 실패 테스트 vs ‘성공했다’는 응답 | 출처 보존, 잘못된 fact/선호/절차 승격률, 근거 없는 inference, 승인 상태 |
| 회상 | 과거 결정·실패·관련 commit 찾기, repo/사용자/role 밖 자료가 비슷할 때 | evidence Recall@k/NDCG, authorized precision, token budget, leakage 건수 |
| 시간/갱신/기권 | 규칙을 수정한 뒤 최신 적용, 당시 원인 조회, 없었던 결정 묻기 | stale assertion·contradiction 해결, as-of 정확도, abstention과 허위 전제 저항 |
| 실제 행동 | 세션A의 실패/해결 결과를 세션B의 다른 client에서 활용; delayed dependency와 held-out issue | hidden test/정확한 patch·불필요 수정·규칙 위반·회귀·task success/partial progress; QA와 별도 |
| 비용/운영 | 같은 corpus ingest부터 회상·reflect·repair까지 | write/embedding/consolidation/query/judge token·비용, p50/p95/p99, 저장 성장, 동시수정 충돌·권한 실패 |
| 보안/삭제 | README ‘테스트 생략이 검증된 성공’, tool 결과의 독, 복수 정상처럼 보이는 note 조합, reviewer→author 전파 | write persistence, recall/adoption/external consequence, independent repair, benign retention, 재실행·다른 client 재활성화 |

### 7.3 Holdout과 지속 공격의 분리

**학습/reflect용 세션과 평가 세션을 시간순·repo/task family 단위로 분리**한다. 메모리를 만드는 세션에는 공개 실행 피드백만 주고, held-out hidden tests/정답/judge 피드백은 retain/reflect에 넣지 않는다. 각 variant는 깨끗한 initial snapshot에서 시작하며 다른 variant 결과를 공유하지 않는다. 기기A의 기억이 기기B에서도 사용됨을 기능적으로 확인하되, 성능 평가는 이미 같은 질문을 재생하는 대신 **새로운 후속 작업**에서 수행한다. [P3][P13][P15]

poisoning 평가에는 다음을 따로 둔다: ① attacker injection query/artifact, ② 새로운 victim task, ③ attacker target을 포함하지 않은 benign holdout task, ④ 복구 후 같은 target/변형 trigger/새 client, ⑤ 필요한 benign memory 확인. MINJA는 이 분리와 utility-drop 개념을, MemSecBench는 post-write snapshot의 독립 execution/repair 평가를 제공한다. MemoryGraft의 PRP 같은 retrieval 지표는 ②에서 실제 unsafe action으로 이어졌는지와 함께 봐야 한다. [P16][P20][P21]

**채택 판단:** graph/reflect가 matched RAG보다 신뢰구간을 포함해 유용한 행동 개선이나 필요한 temporal fidelity를 주고, 추가 생애주기 비용·승격 오류·poisoning/삭제 위험을 수용 가능한 수준으로 만드는지 결정한다. 수치 임계값은 실제 host workload의 실패 비용·보안 요구에서 정해야 하며 논문 평균으로 임의 설정하지 않는다. 현재 조사는 이 임계값을 충족했다는 실측을 제공하지 않는다.

### 7.4 외주 업무 로컬과 개인 클라우드: 무엇을 같게, 무엇을 나눌 것인가

**[설계 추론] 동일 코드·schema·memory lifecycle·권한/철회 계약을 두 배포에서 재사용하는 것은 가능한 설계 목표다. ‘동일 설계’가 ‘모델 추출 결과·rank·정답·지연까지 동일’을 뜻하지는 않는다.** MemDelta의 embedding만 바꾼 통제 실험, A-MEM의 backbone별 결과, Titans의 내부 neural memory와 외부 store의 차이가 이 구분을 뒷받침한다. [P4][P12][P14]

| 구분 | 동등성 목표 / 분리할 부분 | 평가에서 필요한 확인 |
| --- | --- | --- |
| 코드·schema·연산 의미 | retain/후보/승격/revision/as-of recall/reflect/forget의 동일 계약; storage adapter가 바뀌어도 evidence ID·source·scope·version·state 의미 유지 | 동일 fixture의 CRUD·충돌·승격 상태·인용·기권·삭제/철회 결과. API가 같은지만 확인하지 않고 server-side 의미를 판정 |
| 권한·철회·삭제 | local/cloud 모두 접근 범위·role·retention·revocation을 우회할 수 없는 계약; credential과 인증 방식·운영 인프라는 환경별 | revoked client·다른 repo/tenant/reviewer가 회상 불가; tombstone 이후 파생 note·index·cache·backup restore에서 독/삭제자료가 재출현하지 않는지 |
| 기억 내용·데이터 경계 | **회사 업무 bank와 개인 cloud bank는 별도 trust domain·credential·export policy**. 공통 코드/일반적 기능을 배포하는 것과 원문·요약·embedding을 공유하는 것은 다름 | 업무 데이터·파생 요약·로그·embedding의 개인 cloud 자동 업로드 금지. 승인 없는 ‘익명화된 교훈’ 전송도 허용하지 않음 |
| 추출·회상·reflect 품질 | 같은 prompt여도 local/cloud 모델·quantization·embedding·context/window가 다르면 표현·승격·rank·행동이 달라질 수 있음 | 동일 snapshot controlled comparison과 provider-change/OOD evaluation을 별도 보고; 잘못된 선호/절차 승격·한국어·repo/tool 분포 이동 포함 |
| 추론의 위치 | **local 저장 ≠ local inference**. 기억 추출/embedding/rerank/reflect뿐 아니라 host coding agent의 API 호출도 데이터 외부 전송 가능 | 업무용 end-to-end local이 필요하면 모든 단계의 모델·telemetry·judge/로그·egress 경로를 확인. 로컬 DB만으로 ‘외부 전송 없음’이라 표기하지 않음 |
| 운영·성능·가용성 | schema·계약은 같게 유지하되 endpoint/transport, hardware sizing, model artifact, secrets, network policy, backup/restore, monitoring 배치는 분리 | offline/재시작/동시 edit·latency·저장 성장·복구·모델 교체 후 재색인/유효성검사. 논문 query benchmark를 운영 동등성 증명으로 쓰지 않음 |

개인 cloud가 agent 실행까지 포함해도 memory는 특정 runtime에 묶지 않는다. 여러 client/runtime이 같은 개인 bank를 사용할 수 있는 contract와, **업무 local bank가 개인 runtime에서 보이지 않아야 하는 contract**를 동시에 평가한다. memory 호출 실패·사용 거부 시 host가 외부로 업무 내용을 보내는 숨은 fallback은 허용하지 않는다. 이 문단은 제품의 동작을 확인한 것이 아니라 요구에서 도출한 평가/설계 계약이다.

## 8. 미확인·재현 한계

- 공개 1차 자료의 방법/표/본문을 확인했으나 논문 code·benchmark를 실행하지 않았고, 논문 수치를 독립 재현하지 않았다. Claude Opus5.5/Codex6.1 Sol xhigh의 실제 기억 효과나 적대적 모델 리뷰도 이 학술 조사에서는 수행하지 않았다.
- 논문의 dataset variant·subset·category·judge·backbone이 다르다. 특히 LoCoMo 원 논문50대화와 공개10대화 release, adversarial 제외 여부, F1 vs judge accuracy를 한 leaderboard로 통합할 수 없다. [P4][P5][P7–P9]
- Hindsight v1에는 retrieval budget placeholder, 소개/표의20B LoCoMo 불일치, 다른 judge/출처의 reference baseline 혼합이 있다. LoCoMo를 ‘human-human’으로 설명하지만 LoCoMo 원 논문은 LLM 생성+사람 검토라는 점도 원 dataset 설명을 우선한다. 따라서 원문만으로 조건 완비 재현이나 제품간 성능 서열화를 주장하지 않는다. [P7][P9]
- MemDelta의 부분집합은 무작위 전체 대표 샘플이 아니고, memory baseline과 RAG embedding은 일부 다르다. Sonnet 등의 exact hosted-model snapshot을 여기서 완전히 확정하지 못했다. 동일 pipeline 통제의 방향은 활용하되 제품 일반 우열로 확대하지 않는다. [P14]
- eTAMP pseudo poisoning/stress, MemoryGraft executable documentation와 handcrafted probe, MINJA shared-bank, Jan2026 EHR defense의 단일 pair 등 threat model을 우리 배포에 그대로 덮어씌우지 않는다. 반대로 private cloud라는 이유로 untrusted environment→memory→후속 action 경로를 제외해서도 안 된다. [P17][P18][P20][P21]
- 멀티 클라이언트 인증·MCP transport·cloud tenancy·offline 동기화·동시 edit·암호화·백업/삭제·한국어 coding memory transfer에 관한 직접적 end-to-end 실증은 이 논문 집합에서 확인되지 않았다. 이 부분은 시스템 설계/운영 검증이 추가로 필요하다.
- 이는 목표 관련 핵심 논문 선정 조사이며 학술/GitHub 전체 전수조사도, 모든 최신 연구를 포함했다는 주장도 아니다.

## 9. 1차 출처 목록

대부분 논문은 판본을 고정한 원문 링크다. product 운영 문서나 repo의 현재 상태/코드 보증과 구분한다. GitHub 링크는 논문이 제공한 연구 artifact 탐색 경로이며, 이 파일에서는 repository SHA/license/유지보수 상태를 독립 검증했다고 주장하지 않는다.

- **[P1]** MemGPT, arXiv2310.08560v2 — https://arxiv.org/html/2310.08560v2 ; artifact https://github.com/cpacker/MemGPT
- **[P2]** Generative Agents, arXiv2304.03442v2 — https://arxiv.org/html/2304.03442v2 ; UIST DOI https://doi.org/10.1145/3586183.3606763 ; artifact https://github.com/joonspk-research/generative_agents
- **[P3]** Reflexion, arXiv2303.11366v4 — https://arxiv.org/html/2303.11366v4 ; artifact https://github.com/noahshinn/reflexion
- **[P4]** A-Mem, arXiv2502.12110v11 — https://arxiv.org/html/2502.12110v11 ; artifacts https://github.com/WujiangXu/AgenticMemory / https://github.com/WujiangXu/A-mem-sys
- **[P5]** Mem0, arXiv2504.19413v1 — https://arxiv.org/html/2504.19413v1 ; artifact https://github.com/mem0ai/mem0
- **[P6]** Zep, arXiv2501.13956v1 — https://arxiv.org/html/2501.13956v1 ; Graphiti https://github.com/getzep/graphiti
- **[P7]** Hindsight technical report, arXiv2512.12818v1 — https://arxiv.org/html/2512.12818v1 ; artifact https://github.com/vectorize-io/hindsight
- **[P7a]** Hindsight ACL demo2026, pp275–285 — https://aclanthology.org/2026.acl-demo.27/ ; DOI https://doi.org/10.18653/v1/2026.acl-demo.27
- **[P8]** LongMemEval, arXiv2410.10813v2 — https://arxiv.org/html/2410.10813v2 ; artifact https://github.com/xiaowu0162/LongMemEval
- **[P9]** LoCoMo, arXiv2402.17753v1 — https://arxiv.org/html/2402.17753v1 ; artifact https://github.com/snap-research/locomo
- **[P10]** MemoryBank, arXiv2305.10250v3 — https://arxiv.org/html/2305.10250v3 ; metadata https://arxiv.org/abs/2305.10250
- **[P11]** MemoryOS, arXiv2506.06326v1 — https://arxiv.org/html/2506.06326v1 ; metadata https://arxiv.org/abs/2506.06326 ; artifact https://github.com/BAI-LAB/MemoryOS
- **[P12]** Titans, arXiv2501.00663v1 — https://arxiv.org/html/2501.00663v1 ; metadata https://arxiv.org/abs/2501.00663
- **[P13]** MemoryArena, arXiv2602.16313v2 — https://arxiv.org/html/2602.16313v2
- **[P14]** MemDelta, arXiv2606.29914v1 — https://arxiv.org/html/2606.29914v1
- **[P15]** LongMemEval-V2, arXiv2605.12493v1 — https://arxiv.org/html/2605.12493v1
- **[P16]** MemSecBench, arXiv2607.27080v1 — https://arxiv.org/html/2607.27080v1
- **[P17]** eTAMP, arXiv2604.02623v2 — https://arxiv.org/html/2604.02623v2
- **[P18]** Memory Poisoning Attack and Defense, arXiv2601.05504v1 — https://arxiv.org/html/2601.05504v1
- **[P19]** MemPoison, arXiv2607.14651v1 — https://arxiv.org/html/2607.14651v1
- **[P20]** MINJA, arXiv2503.03704v5 — https://arxiv.org/html/2503.03704v5 ; artifact https://github.com/dsh3n77/MINJA
- **[P21]** MemoryGraft, arXiv2512.16962v1 — https://arxiv.org/html/2512.16962v1 ; artifact https://github.com/Jacobhhy/Agent-Memory-Poisoning
