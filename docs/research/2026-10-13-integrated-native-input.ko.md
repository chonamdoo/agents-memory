# agents-memory: 회사 Jev 대체·실제 OSS 흐름·4분류·TypeSafe native provider 통합 적대적 재리뷰

## 사용자 요구

개인 외부/cloud에서는 Jev API를 쓸 수 있다. 회사/외주에서는 Qwen 등 local ML 모델 설치 불가; 회사 승인 Claude Code/Codex 팀 계정만 전제할 수 있다. 방대한 coding session에서 유용한 사실·교정·반복 질문 등 기억 후보/제외/검토를 싸고 빠르게 판단하고 원문 근거를 보존하고 싶다. 동일 3label이 없어도 유사 no-op/create/patch/conflict-hold를 쓰는 OSS 설계의 힌트를 찾아야 한다. rohitg00/agentmemory 유사제품 목록이 아니라 우리 common core·권한·근거·승인/철회·bounded MCP/host 구조에 가까운 것을 찾아야 한다. Profile(항상 필요한 사용자 핵심 사실), Log(관련 dated events), Notes(단기 task 메모), files/skills(필요 시 상세 검색/read) 분리도 별도 동일 기준으로 검토했다. 최신 추가 자료는 공식 TypeSafe adapter + 구독 Haiku 사례 effortless. 가장 적합한 최종 제안·영향·장단점을 정하고 실제 적용을 진행하라는 요청이다.

## 고정 경계

- host capture metadata는 semantic useful 판단이 아니다. source/speaker/time/revision/identity를 코드가 보존하고 모델은 의미·조건·시간해석 후보를 제시한다.
- 모델/CLI 기술 가능, SDK 있음, MIT license, no-training, 사용자 구독 로그인은 회사 daemon/CI 자동화·저장·고객 egress 승인 증거가 아니다. 그 승인은 이 공개/개인 조사로 확인 불가다.
- 회사→개인/cloud Jev fallback 없음. 회사 realm에서 차단이면 blocked/unavailable; exclude/no-op가 아니다. 개인 realm은 별도 explicit route 가능.
- 회사가 승인한 모델이라는 조건은 **모든 fact create마다 인간 승인을 추가하라는 조건이 아니다.** 기존 machine-extracted optional facts는 authenticated grants와 publication fence를 지킨다. 필수/공유 instruction 활성화, 권한 확대, 실제 철회는 기존 operator/approval 계약을 유지한다.
- text Claude/Codex로 learned embedding을 만들었다고 위장하지 않는다. lexical/entity-only가 가능하면 vector/rerank capability·검색 품질 차이를 명시한다.
- 원문 span 존재 검증 ≠ entailment ≠ 사실 정확성. confidence ≠ calibrated accuracy ≠ 승인. 원문 전량 무기한 저장은 privacy/retention 계약과 충돌할 수 있다.
- MCP 연결 ≠ 모든 host 자동 context 주입. 현재 AF 구현 리뷰와 새 조사/회사 executor 검증은 별개다. 기존 AF의 fresh12 native review에는 request-changes가 남아 있고 QA/handoff 완료가 아니다.

## 현행 core: 실제 architecture 문서에서 읽은 계약; 회사 native route는 아직 미구현

Python3.12 official MCP SDK2.3, PG authority, leased job owner, 같은 application handlers에 MCP4tools/CLI/host capture 연결. Immutable admission manifest에 실제 전체 source/claim 입력, credential/realm/binding/revision/route/generation를 결합하고 publish/delivery에 현재 자격 재검사. 원문은 canonical source에만, receipt/outbox/audit/journal에는 body 복제 금지. exact UTF8 span·speaker 보존. extraction/consolidation/index/recall/rerank/reflection/current-use correction. local structured model·learned embedding·cross-encoder 현재 path. Source/claim retract시 전체 실제 모델 입력 lineage로 파생자격 차단. 모델 계산 중 DB tx/lock 없음. Local roles G0≠악성 같은UID 차단, 회사 signed operator approval 강한운영경계는 별도. 다음 source scoping 결과는 읽기 전용 조사이며 새로운 구현 완료 주장이 아니다.

### 완료된 concrete core source scoping

- `domain.py` Capture/Record에는 원문-grounded selection union이 없다. `memory_record(note)`는 agent_note 원문을 만들고 기존 extract job enqueue; note summary를 human 원문 evidence로 승격하면 안 된다.
- `jobs.py Worker._process`: extraction route와embedding route둘다admit, claim마다embed후publish. `store.publish_extraction`: 모든claim의vector/lexicalrow필수; 이후consolidate. `application.context`: activeclaims면queryembedding→hybridsearch→rerank필수. 작은nativeclassifier하나추가하거나committedreceipt만반환해서는회사noMLpipeline완성이아니다.
- 현재검색은PGtext[]GINtokenoverlap+entityexact+vectorRRF, **tsvector FTS아님**. 한국어bigram/NFKC검색용복사는원문evidence가아니다. embeddingcolumnnullable지만no-vector를공개capability로처리하는코드·통계·deliverypath없음. Claude숫자로1024vector위조금지.
- 최소coherentA는①companyingest localjobdisabled/unclassifiedcoverage②sourceIDs/revisions/policy/idempotency/evidence/drafts typedrecord③candidate-ready/discard/review/failed별상태④existingvalidator+claim/spanlineage reuse⑤lexical/entity RRF explicitmode+knownconflicts+bytebudget⑥**model-free actual-input finalmanifest** source/grant/policyrecheck⑦selectionauthorityforwardmigration+purge/restorefloors/statistics⑧hosts의sourcepointer/coverage/receipt확장까지다.
- `delivery(admissions=())`는manifest전체최종검사를없애므로우회금지. route없는fake localmodeldescriptor금지. callercandidate에서consolidation/reflect미실행은공개하고기존localsemanticcontract는그대로보존. lexicalmode에서semantic_quality를동등하다고하거나기존full파이프라인완료기준을내리면안됨.
- 이A는limited**caller-grounded lexical capability**라는새제품계약이다. 현재mandatoryhybrid/rerank/fullsemantic요건의**명시예외를사용자가채택하기전에는코드에몰래반영금지**. 사용자최신요청은제안뒤작업진행이지만이품질/완료범위차이는별도명시결정이필요한지평가하라. NativeB는A의선별executor,semanticfull대체아님.
- 영향: domain/config/semantic-contract/store/application/jobs/edge/wire/CLI/client/stdio/hosts/hosttemplates/spool/newforwardmigration/opsrestore/init/readiness,관련behaviorregressions와architecture/requirements/verification/updatecheckpoint. 작은wrapperticket으로축소금지. AF는consumer이지runtimeimportdependency아님. AFprovider의authfilecopy/danger-full-accessargv를memoryruntime으로복사금지.
- frozen successor는source_event_time/source_recorded_at와bindingrelocation/strictstate등현재leader보다일부진전했지만freshAF12review중5request-changes,sourcefrozen이며QA/handoff없음. 새A/B를기존reviewedpatch에슬쩍끼우거나리더에별도engine로우회하지않는다. 기존approvedbase선정후공식새scope/plan승인필요.

## 실제 pinned source 조사 결과

1. Engram MIT `5c4171845958f046968c14d7d57a325eb4a83b7e`: mem_save observation commit **후** FTS/title/topic 후보를 pair pending relation로 저장; mem_judge caller 관계 판정 저장. conflicts/supersedes 관계가 observation을 보류/교체하는 gate는 아님. evidence optional free text, verified original span 없음. topic_key overwrite는 의미판단보다 먼저, negative not_conflict도 durable. https://github.com/Gentleman-Programming/engram/blob/5c4171845958f046968c14d7d57a325eb4a83b7e/internal/store/relations.go#L364-L746
2. codex-agent-mem Apache2 `d594c8a86207fb9a8a5b48a6aab323349680707a`: raw turn+hash/provenance를 저장, regex extraction; policy는 retrieval/pack 노출을 결정; 비파괴 exclusion overlay. conflict repair supported_apply=false. approved=1 literal≠human approval; source_span은 offset/span아닌 descriptor. https://github.com/MarceloCaporale/codex-agent-mem/blob/d594c8a86207fb9a8a5b48a6aab323349680707a/src/codex_agent_mem/policy_engine.py
3. Memharness Apache2 `faed4b346e445d2344ed02e8211759999acd946d`: same-subject lexical Jaccard advisory 뒤 remember unconditional insert. explicit revise exactoldID로 successor/validity history. git freshness current/stale/unresolved는 truth아님. MEMHARNESS_HYBRID=1 없으면 embedding provider없어FTS-only; hybridlocalmodel은회사불가. https://github.com/las7/memharness/blob/faed4b346e445d2344ed02e8211759999acd946d/packages/core/src/memory.ts#L349-L429
4. LangMem MIT `48e3c11f5bb527282c7d5339c6a87a0b35abccfc`: existing top retrieved memories+conversation same Trustcall extraction; store manager exactdiff put/delete. deletion-only 반환=[] 가능. defaultcontent schema에 original span없고 quote는whennecessary prompt. human gate 없는 directmutation. https://github.com/langchain-ai/langmem/blob/48e3c11f5bb527282c7d5339c6a87a0b35abccfc/src/langmem/knowledge/extraction.py#L988-L1116
5. mnema MIT `eed19586156ae9664451cb94859f8f3f16b3ac4a`: preview후applyLLM없음; 실제messageID membership검사/excerpt/hash, editedbody supports_current_body=false. Conflict judge partial/empty verdict도 checked로 처리하므로 completeness flaw. unresolvedrelation→preview/commit hash token은 content-bound UX, actor/signature/expiry/resolution binding없는 human승인아님. 현재conflict detection은embedding필수. https://github.com/Ray0907/mnema/blob/eed19586156ae9664451cb94859f8f3f16b3ac4a/src/distill.ts#L74-L177 ; https://github.com/Ray0907/mnema/blob/eed19586156ae9664451cb94859f8f3f16b3ac4a/src/store.ts#L293-L423
6. Mem0 Apache2 current `b7ad69afda6b6ed030347c66d48a13e4de9dec08` add는retrieval→singleLLM→ADD-only. old v1SHA394203d1은2LLM ADD/UPDATE/DELETE/NONE directmutations, NONE도metadatawrite가능. 현재prompt파일에old4op가남아도 currentcall아님. 원문span없는10messagecache는 evidencearchive아님. https://github.com/mem0ai/mem0/blob/b7ad69afda6b6ed030347c66d48a13e4de9dec08/mem0/memory/main.py#L897-L1077
7. Hash/trigram/Jaccard vector 계산은 learned ML 자체가 아니다. sqlitevec거리계산도 embedding inference와 구별해야 한다. 상세보고서들은 static source audit로 실행/성능보장아님.

## 최신 TypeSafe·native Haiku 근거

- Official System One Adapter MIT pin `e1d4cc938204b22fc5a3c3aca7044072fe3f712d`, package0.2.1. custom SyncProvider/AsyncProvider model객체 injection 실제가능. BuiltinAnthropicProvider는API.Messages notsubscription. strictPydantic questions/allowedlabels/fields/range0..1 validation, Choice/Score/Noul +usage+debug 응답. https://github.com/typesafe-ai/system-one-adapter-python/blob/e1d4cc938204b22fc5a3c3aca7044072fe3f712d/src/system_one_adapter/_client.py
- Default transient/corrective retries0. normalizationFalse default에서prob합1 미달도 반환하며debug오차; normalizeTrue는rescale, all0은uniform. discrete mode는1hot+confidence1 (실측확신아님). Scoreexpectation은reportedprobsnormalize옵션과무관rescale. https://github.com/typesafe-ai/system-one-adapter-python/blob/e1d4cc938204b22fc5a3c3aca7044072fe3f712d/src/system_one_adapter/_utils/probability_normalization.py
- debug.llm_attempts는messages/schema/rawresponse 보존, TypeSafeError.debug도fulltrace. 이를 audit/receipt/telemetry에dump하면canonical body-free계약위반위험. SourceID/revision/spans/meaningfulevidence는TypeSafequestion형식으로 자동생기지않음. ProviderResultinput/output만으론cachedinput·requested/servedmodel별usage충분하지않음.
- 실제 개인 합성 smoke: **pin의 공식Pythonclient + 임시 customprovider + native claude-haiku-5-5/low**를 실행. tools'',strictemptyMCP,safe-mode,slashdisable,nosessionpersist,원문stdin,APIkeyprovider사용없음. Returnexit0,is_errorFalse. s1개인프로젝트한국어+고객예외→candidate, s2assistant진행상황→exclude, s3불확실한tabs범위→review. Choice3+Noul1+Score1=5질문 반환·Pydantic검증, Choice분포sum1직접검사. 약5.018초. **개인3source smoke이지품질benchmark/회사승인/근거span제품계약아님.** Nativeusageinput4+cachecreation689+cacheRead5640, output595, CLIlistpriceestimateUSD0.0004921은실제구독청구액아님. Adapterusageinput4라cached처리누락실제로관측. Debug에prompt존재실제로관측. 첫 maxturns1 호출은processfail했고2로수정후success; 실제num_turns3, 그count를modelrequesthardcap으로추정하지않음. Memorymutation없음.
- Earlierpersonal3eventsprobe: Haiku input2+cachecreation4122/output123, CodexLuna input20040/output111; CLIcontexts통제되지않아가격fairbenchmark아님. Cold per-eventCLI가작은판단의입력고정비커질수있음. 영상95%절감우리측정값아님.
- effortless MIT `e553b18e9f5e8ce3533f3ce9c666e7e8bc9234f9` askHaiku는실제ClaudeCode**official mods API** $.model.complete(model,system,prompt,maxTokens160,effortlow,timeout6000) 사용, sessioncredentials와plan/API/provider에청구. Complete는sessionhistory/projectdocs/tools자동첨부없음;fork는다름. stock외부MCP에서$생성못함. build별types/resultshape pin필요. 전체plugin은compaction/handoff/gitupdate/logging등과대권한이므로단순classifier대용통째도입거부. JSONonlyprompt+partialparser,sourceevidence없음,ownclaimedbench측정안함. https://github.com/HeyCubit/effortless/blob/e553b18e9f5e8ce3533f3ce9c666e7e8bc9234f9/hooks/register.tsx#L762-L809 ; https://code.claude.com/docs/en/plugins/mods/api#call-a-model
- Jevbridge MIT `d4e8f7d483b8a5649218970eedbaf4f4a1e1e832`: Claudejudge APIkeyHTTPMessages, ACPnativeClaude/Codexupstream은별도generator이고judge구독credentialreuse아님. Missingnoul→0,emptychoice→uniform+firstchoice등coercion,backendauto키선택,timeout/cancelsourcecontract없음. 그대로companygate사용거부. https://github.com/tacticocc/Jevbridge/blob/d4e8f7d483b8a5649218970eedbaf4f4a1e1e832/src/llm-adapter.ts

## 별도 4분류 native 1차 결과 + 부모의 반박

동일stdin SHA `9be1d5878a109ac49a228141bc93ce1402245c3a8ae8e8eff86094ca36002d56`로 실제 Opus55xhigh와Sol61xhigh별도리뷰. 두모델은canonical ledger views(B)조건부추천,alwaysProfile/4independentstores(C)비추천,기준선A유지. Opusmetadata에claude-opus-5-5관측,Solservedmodelunobserved. Sol첫argv의web/apps호출격리실패;최종native는web/apps/collab/command0, builtinlisting2calls(emptyresources/templates)남음. Tools0/production sandbox증명아님.

상호반박할 점:
1. Opus의'모든lifecycle/승격은human서명'은optionalfact까지과도한scope확장. 필요한규칙/권한승인과machinefact처리분리해야함. Sol은지침승인과factdata를더잘분리.
2. Opus의Logsource포인터전량보존/내용잘라출처유지권고는retention·민감최소화·조건/부정절단위험과대조해야함. 영구전체raw보존을새default로추가하지않음.
3. Opus source_event_time을actual사건time처럼서술한부분은교정: messageeventtimestamp와본문의사건occurrence/validtime은다름. Sol이명시적으로구별.
4. 회사새Profileauto-pin빈default는기존승인된mandatoryrules를지우라는뜻이아님. optionalProfiles와현재rulecontext경로별개.
5. 4view추가가retrieval향상측정없으면고비용모델별도taxonomycall추가하지않음. source/kind/task/time기존속성으로readonly관리view우선; category가권한·상시주입·서로다른store를결정하지않음.

## 같은10기준으로 평가할 대안

A 현재승인caller가이미읽은구간의evidence-grounded candidates제출 + incrementalcursor/coveredsource window, noMLlexical/entity read. 추출중복콜줄일수있지만coverage와host협조필요.
B A+허가된nativeHaiku(orapprovedCodexmodel) boundedbatchclassifier/structuredsemanticruntime. 별도daemon은명시허용경우만; coldcontext/usage/isolation/timeout/approvalmanifest/operationalfailure처리필요. Embedding은optionaldisabled,semantictext와vectors호환분리.
C B+공식SystemOneAdapter전체응답compat. 범용typedquestionconsumer가정말필요할때선택적boundary, memorycore에확률SDK/debug/normalization의무추가할필요가있는지반대검토.
D Claudeonlyofficialmodscomplete smallsidecar, acceptedruntimepin+companymod승인있는환경만. CLIstartupcontext고정비회피가능하지만host확장·$.http/localboundary·MCPauthority·buildAPIvariations필요. Codex/omp공통계약의유일engine로삼지않음.
E wholeJevbridge/effortless/memoryengine교체. 원문/approval/cancel/realmnarrowcontract차이때문에강한재사용근거필요.
4분류는위대안과독립적으로1ledger+overlappingviews;전역alwaysProfile금지,skill지침승격은별도승인.

10기준: ①형식과의미품질/calibration②원문ID/revision/span/speaker/entailment③판단/저장/규칙승인·오류state④realm/grant/egress/nativeauth⑤중분batchcontext·false negatives⑥token/quota/latency/cached/failedcalls비용⑦retrievalvectors없음·4views·temporal/TTL/staleness⑧deadline/cancel/lease/publication/failure⑨기존commoncore/MCP/hosts/API/DB/docs/tests영향과유지보수⑩실제개인proof·미실행검증·회사허가·현재AFgate와구별.

## 산출물

독립반대자로권고안도반박하고최소coherent선택1개+차선선택+기각이유. A/B/C/D/E와4views를같은10기준으로판정. P1/P2소비자가볼수있는실패(누락판정이exclude로소실,중간scope확대,철회중inflightpublish,본문은조건/부정인데truncated,probdebug원문복제,회사개인fallback,노벡터가벡터처럼선언,TTL≠삭제)와검증사례를제시. 기존규칙승인은유지하되새권한/인간승인/대규모로그보존/복수store등불필요scope추가하지말것. 근거url몇개명시;sourcefacts/proposal/inference/unmeasured구별. **7000자 이내 한국어 최종 보고서**로 모든10기준을압축해서포함. Tool을호출하지말고공개packet만으로평가. 실제코드implementation approval이나companypermission 선언금지.
