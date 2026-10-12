**A 유지, B 조건부 채택, C 제한된 조건부 채택, D 보류를 권고합니다. 신규 제안의 우선순위는 B → C → D입니다. E는 기각 대상입니다.**

가장 먼저 검토할 것은 **기존 core에서 작은 procedure candidate를 만들고, 승인·거절 feedback을 다음 생성에 제한적으로 쓰는 B**입니다. 자동 승격은 허용하지 않습니다. C는 코드 변경 뒤 적용 가능성을 다시 검토하는 보조 장치로 제한합니다. D는 SDK와 실제 host의 activation·consent 검증 전까지 정식 지원으로 선언하면 안 됩니다.

이것은 **제안에 대한 권고**입니다. 구현 채택, 성능 실험, host skill activation 완료 판정이 아닙니다. 공식 AF12-review/bg_134와도 분리됩니다. 도구·파일·메모리는 사용하지 않았으며, 구현 상태는 제공된 기준선과 source audit 요약에 근거합니다. 최종 결정은 parent/user의 몫입니다.

**현재 구현과 추가 제안의 경계부터 분명해야 합니다.**

| 구분 | 제공된 기준선상 현재 상태 | 추가로 검토하는 것 |
|---|---|---|
| Memory core | capture부터 correction/retract·next use까지 존재 | 이 파이프라인 전체를 새로 만드는 것이 아님 |
| 승인 | PG canonical approved rule ledger와 내용·범위·권한·revision binding 존재 | candidate나 reflect artifact를 승인된 규칙으로 취급하면 안 됨 |
| Feedback | idempotent 저장 존재 | 후속 generation consumer는 audit 범위에서 찾지 못함. 전역 부재 증명은 아님 |
| 코드 변경 | snapshot·path selector·fences 존재 | 사용자 코드 dependency에서 change-review 후보로 이어지는 경로는 관찰되지 않음 |
| Skills | 기존 four tools와 opt-in bounded context 존재 | 새 Skills projection과 host activation은 별도 기능 |
| 검증 | 기존 747 tests와 native 3개 소비 증거 | B·C·D의 추가 기능 증거가 아님 |

`context 749 UTF8B / catalog 3922B / discovery 282B`는 특정 fixture의 wire 측정입니다. 전체 native prompt 크기, token 비용, 모든 host의 startup context가 0이라는 뜻은 아닙니다.

또한 Python SDK PR #3485의 **2026-10-11T14:44:20Z merge**는 설치된 `mcp==2.3.0`에 Skills가 있다는 증거가 아닙니다. 새 SDK의 handler·schema 지원도 host의 YAML 검증, origin trust, consent 구현을 대신하지 않습니다. [PR #3485](https://github.com/modelcontextprotocol/python-sdk/pull/3485), [해당 commit의 Skills 문서](https://github.com/modelcontextprotocol/python-sdk/blob/9a754b0aabb873d9707d52dc165b569fb442ec8c/docs/advanced/skills.md).

**A–D의 직접 비교는 다음과 같습니다.**

| 안 | 권고·착수 시점 | 실제 차이와 영향 | 장점 | 단점 |
|---|---|---|---|---|
| **A: four tools 유지** | **현재 유지** | 변경 영향 최소. 현재 memory 경로를 기준선으로 유지 | 기존 승인·삭제·전달 경계를 활용 | feedback 소비와 코드 변경 검토의 공백은 남음 |
| **B: trace → procedure candidate + bounded feedback** | **조건부 채택**. 기존 reflect와의 실제 차이, 허용된 모델 경로, 평가 기준을 먼저 확정 | 후보 생성과 feedback 소비를 추가. 모델·저장·검토 비용 발생 | 반복 작업의 절차를 남길 수 있고 기존 core와 연결 가능 | 우연한 성공, 잘못된 실패 해석, feedback 오염을 재생산할 수 있음 |
| **C: dependency stamp → change-review 후보** | **좁은 범위 조건부 채택**. 관찰 가능한 dependency와 `UNKNOWN` 처리를 먼저 정의 | 사용자 코드 변경과 규칙 검토를 연결. dependency 유지 비용 발생 | 코드 변경 뒤 검토가 필요한 규칙을 찾는 데 도움 | stamp만으로 의미적 유효성을 판정할 수 없음. 누락과 과잉 경고 가능 |
| **D: immutable read-only Skills projection** | **보류**. SDK와 host 증거를 확보한 뒤 additive opt-in 시험 | ledger에서 작은 배포용 표현을 추가. protocol·cache·host 관리 비용 발생 | 지원 host에서 필요한 내용만 가져오는 경로를 시험 가능 | 기존 four tools와 중복될 수 있고 activation·cache 철회가 불확실 |

| 안 | 정확성 | 보안·권한 | Context | Host 지원·운영 수용 |
|---|---|---|---|---|
| **A** | 기존 증거 범위만 인정. semantic applicability의 완전성은 보장 못 함 | 현재 fences 유지. 모델의 임의 행동까지 강제할 수 없음 | bounded context 유지. 전체 prompt 비용은 별도 | 기존 소비 증거만 인정. strict가 불가능한 host에는 그 한계를 표시 |
| **B** | 관찰된 절차와 생성된 일반화를 분리. 성공·실패 모두 독립된 근거 필요 | trace·feedback은 권한 부여 근거가 아님. 모델 경로와 audience 제한 필요 | 입력 feedback과 출력 candidate 모두 제한. startup 주입 금지 | 기존 도구 경로로 검토 가능. 새 Skills 지원을 전제로 삼을 필요 없음 |
| **C** | 변경 감지는 correctness 판정이 아님. 필수 규칙의 `UNKNOWN`을 fail-open으로 처리 금지 | 자동 승인 취소·body 수정·authority cutover 금지 | 전체 코드나 dependency 목록을 prompt에 상시 주입하지 않음 | host와 무관한 후보 생성은 가능. 실제 실행 차단은 연결된 host gate 검증 필요 |
| **D** | ledger에서 승인된 정확한 revision만 projection. 읽기·activation·실행 동의를 구분 | auth·realm·audience·digest 경계 필요. read-only라도 지시 내용은 위험할 수 있음 | 전체 catalog 주입 금지. 필요 전 file prefetch 금지 | 실제 host별 activation·consent·cache 검증 전에는 정식 지원 선언 불가 |

B는 후보만 생성하는 범위라면 C의 완성을 기다릴 필요는 없습니다. 하지만 그 후보를 **변경된 코드나 더 넓은 프로젝트에 적용하는 근거**로 쓰려면 C가 드러내는 적용 가능성의 불확실성을 해결해야 합니다.

**가장 약한 주장과 반론은 다음과 같습니다.**

1. **“36% → 100%이므로 우리도 좋아진다”는 주장은 성립하지 않습니다.**

   제공된 사례는 같은 Sonnet 4.6으로 Chromium fork를 AWS Lambda에서 실행한 특정 발표자 사례입니다. `n`, holdout, success oracle, task 변형, failure logs, 실험 저장소가 없습니다. 재사용 절차가 도움이 될 수 있다는 가설은 지지하지만, 일반 성능이나 인과효과를 입증하지는 않습니다. [새 영상 12:36–13:14](https://www.youtube.com/watch?v=jDdgfTp_PXw&t=756s).

   같은 문제를 다시 풀어 성공한 것은 **재현**에 가깝습니다. 다른 버전·환경·조건에서도 성공하는지는 별도 문제입니다. 잘못된 절차가 탐색을 줄이면 더 빨리 잘못된 답에 도착할 수도 있습니다.

2. **“성공과 실패가 모두 skill을 개선한다”는 자동 보증이 없습니다.**

   성공은 잘못된 oracle, 누락된 승인, 우연한 환경 조건 때문에 나온 결과일 수 있습니다. 실패도 skill의 결함이 아니라 도구 오류나 환경 차이일 수 있습니다. LLM distillation은 그 원인을 잘못 일반화할 수 있습니다.

   따라서 trace에서 procedure candidate를 만드는 것과 approved rule로 승격하는 것은 분리해야 합니다. 발표자의 “완전자율·비동기·human 없이” 설명은 우리의 승인 정책을 대체하지 못합니다. [새 영상 11:22–12:33](https://www.youtube.com/watch?v=jDdgfTp_PXw&t=682s).

   예를 들어 “승인 없이 배포했지만 성공했다”는 trace에서 승인 생략을 학습하면 안 됩니다. rejected feedback도 필수 규칙을 우회하는 지시로 소비하면 안 됩니다.

3. **“PII·prompt injection 검사 뒤 배포하므로 안전하다”는 근거가 부족합니다.**

   검사를 수행한다는 발표자 설명은 있습니다. 하지만 구체적인 gate, ACL, tenant 격리, adversarial eval, rollback 근거는 제공되지 않았습니다. 검사 통과가 permission grant나 audience 확대를 뜻해서도 안 됩니다. [새 영상 15:15–15:33](https://www.youtube.com/watch?v=jDdgfTp_PXw&t=915s).

   회사 전체로 퍼질 때는 개선뿐 아니라 오류도 퍼집니다. 비슷한 여러 run이 같은 오염된 원본에서 나왔다면 독립된 증거 여러 개가 아닙니다.

4. **“MCP로 배포하면 거의 모든 client의 Skills 문제가 해결된다”는 주장도 과합니다.**

   MCP tool 결과를 받을 수 있다는 것과 native Skills discovery·activation·consent를 구현했다는 것은 다릅니다. 서버는 어떤 내용을 전달할지 통제할 수 있지만, generic MCP만으로 모델의 임의 tool 행동을 강제하거나 실제 소비를 증명할 수는 없습니다. [새 영상 07:54–09:18](https://www.youtube.com/watch?v=jDdgfTp_PXw&t=474s).

   제공된 audit에서 `Claude Code 2.1.296`, `Codex CLI 0.162.1`의 stable extension activation 보안은 **UNVERIFIED**입니다. `OMP 18.10.1`의 legacy resource·local Skill fallback도 stable activation 증거가 아닙니다. 기존 OMP strict 설치 거절과 advisory 지원 판정을 그대로 유지해야 합니다.

   HF의 custom handler 구현은 서버 측 구현의 구체적 사례입니다. 모든 host의 완전한 지원 증거는 아닙니다. [HF 공개 구현](https://github.com/huggingface/hf-mcp-server/blob/dce2d5f0f16392e22d6f3fdc039681f4698e8cdf/packages/app/src/server/skills/skill-resources.ts).

5. **“immutable projection이면 철회와 권한 문제가 해결된다”는 주장도 틀립니다.**

   immutable content는 bytes와 digest를 고정하는 데 유용합니다. 현재 권한이나 audience를 고정해 주지는 않습니다. `resources/read`도 activation이나 consent와 같지 않습니다. Skill content가 더 높은 지시 권한이나 실행 허가를 얻는 것도 아닙니다. [고정된 ext-skills 규격](https://github.com/modelcontextprotocol/ext-skills/blob/167da6c0d42c247a8f8470228a10ca711e3f6c45/specification/stable/skills.mdx).

   특히 host가 polling할 의무가 없다면, 서버 철회 뒤에도 기존 cache나 context에 내용이 남을 수 있습니다. 현재 eligibility를 확인해 새 전달을 막는 것과 이미 전달된 내용을 즉시 잊게 하는 것은 다릅니다. TTL만으로 auth·realm cache key·revocation을 대신할 수 없습니다.

6. **“dependency stamp가 있으면 stale 규칙을 안전하게 제거할 수 있다”는 주장은 위험합니다.**

   file 변경은 검토 신호입니다. 규칙이 틀렸다는 증거가 아닙니다. 반대로 file이 안 바뀌어도 runtime 설정, 외부 API, feature flag, 권한이 바뀌면 절차가 달라질 수 있습니다.

   엔진의 `semantic_contract` digest와 사용자 코드의 dependency는 별개입니다. C는 **change-review 후보 생성**까지만 주장해야 합니다. 완전한 graph나 자동 correctness 판정으로 확대하면 안 됩니다.

7. **Voyager는 아이디어의 근거이지 기업 memory의 안전성 증거가 아닙니다.**

   Voyager의 Minecraft/GPT-4 환경에서는 code-as-action, 환경 feedback, execution error, self-verification과 skill library를 사용합니다. 이를 회사의 자연어 규칙, 승인 권한, 개인정보, production rollback에 그대로 옮길 수 있다는 증거는 아닙니다. [Voyager 원문 사이트](https://voyager.minedojo.org/), [논문](https://arxiv.org/abs/2305.16291).

   절차를 저장하면 모델 변화에 덜 의존할 가능성은 있습니다. 하지만 오래된 절차가 새로운 모델·tool·환경에서도 올바르게 해석된다는 보장은 없습니다.

8. **공개 prototype이나 controller를 전체 pipeline의 증거로 확대하면 안 됩니다.**

   BoundaryML의 해당 `ns_memory`는 제공된 audit상 per-turn prototype입니다. overwrite·delete·autotrust 동작과 approval ledger 부재를 그대로 가져오면 현재 구조보다 후퇴합니다. 명시 license가 확인되지 않은 상태에서는 코드 복사를 보류해야 합니다. [고정된 공개 코드](https://github.com/BoundaryML/baml-demos/tree/dcc3d33f0fd2635d18515a62a10da91ae789f080/aie/baml_src/ns_memory).

   HumanLayer의 MIT controller는 durable feedback과 PR-specific feedback을 구분하는 실제 참고점입니다. 다만 우리의 PG feedback 저장, 후속 생성, 승인·삭제 경계가 이미 연결됐다는 증거는 아닙니다. [고정된 `agent-iteration.ts`](https://github.com/humanlayer/skills/blob/653b6411c1f70c275a18e37673b042ff99f67ceb/plugins/build-iterated-agentic-loop/skills/build-iterated-agentic-loop/references/agent-iteration.ts).

**절대로 넘으면 안 되는 경계가 있습니다.**

- **사실, candidate, approved rule, Skill 배포, execution consent는 각각 다릅니다.** Typed return과 exact full-input provenance는 사실 보증이나 승인 보증이 아닙니다. `source_speaker`도 승인권자 표시가 아닙니다.
- **필수 규칙의 `UNKNOWN`은 안전하게 빠지는 값이 아닙니다.** stale 표시 뒤 검색에서 사라졌다는 이유로 관련 실행을 허용하면 fail-open입니다. 적용 범위나 권한 freshness가 불명확하면 검토·해결 전까지 관련 실행을 보류해야 합니다. 그 보류를 실제 강제하는 host gate가 없으면 strict 지원을 선언할 수 없습니다.
- **candidate는 승인된 body를 덮어쓸 수 없습니다.** selector·exception·required·targetset·authority·revision digest 변경은 기존 승인 binding을 유지한 변경이 아닙니다.
- **rollback도 현재 eligibility를 다시 확인해야 합니다.** 과거 bytes로 돌아갔다고 과거 권한까지 되살아나는 것은 아닙니다.
- **범위는 정확히 세 가지입니다.** 이 로컬 프로젝트, 승인된 explicit ID 집합의 내 프로젝트들, 설정된 approver·audience의 팀/프로젝트 공유입니다. 새 프로젝트는 재동의 대상이며 팀 공유는 회사 전체 강제가 아닙니다.
- **회사 승인과 egress 승인은 별개입니다.** 팀 Claude/Codex 사용 승인이 외부 distillation, telemetry, 별도 MCP 허가를 뜻하지 않습니다. B에 허용된 모델 경로가 없다면 자동 distillation은 보류해야 합니다. 개인 cloud도 현재 수용 근거가 아닙니다.

**운영 수용에는 다음 추가 증거가 필요합니다. 이 시험을 실시했다는 결과는 제공되지 않았습니다.**

| 대상 | 필요한 검증 |
|---|---|
| **B** | 현재 reflect와 겹치는 부분 확인. 공개·합성 입력으로 성공/실패 oracle 정의. 서로 독립된 원본과 반례 보존. 후보 생성에 쓰지 않은 holdout에서 비교. 같은 harness 조건의 품질·비용·시간 측정 |
| **B feedback** | durable와 작업 한정 feedback 구분. approved/rejected 내용의 범위·revision·권한 연결. 거절을 우회 지시로 학습하지 않는지 확인 |
| **C** | 실제 dependency 변경, 무관한 변경, 누락된 dependency, runtime 조건 변경을 구분. 필수 규칙의 `UNKNOWN`에서 실행 허용이 발생하지 않는지 확인 |
| **B·C·D 공통** | auth·source·snapshot·lease·deletion fences가 새 경로에도 적용되는지 확인. publish·delivery 중 철회와 revision 변경의 경쟁 조건 검증. 파생 artifact의 source lineage와 삭제 전파 확인 |
| **D** | 실제 host별 discovery→read→activation→consent 구분. bytes·size·frontmatter 검증. origin·digest set 변경 재동의. realm별 cache 격리와 철회 한계 확인 |

D는 작은 projection이어야 합니다. 전체 catalog의 model 주입이나 필요 전 file prefetch는 배제해야 합니다. 제공된 규격의 `512 files / 16 MiB` 수치는 전체 catalog 상한이 아닙니다. startup body가 0이어도 metadata 비용은 남습니다. [ext-skills 규격](https://github.com/modelcontextprotocol/ext-skills/blob/167da6c0d42c247a8f8470228a10ca711e3f6c45/specification/stable/skills.mdx).

E의 protocol 선행 전면 rewrite, BAML/Jev 필수 의존, 회사 전체 자동 승격, giant catalog, root full-body 설치는 현재 증거로 정당화되지 않습니다. BAML의 범위가 schema DSL보다 넓다는 사실도 기존 Pydantic을 재작성할 근거는 아닙니다. Jev의 hosted API는 회사 no-egress 조건과 맞지 않으며 weights·local deployment 증거도 없습니다.

영상 근거의 시각은 **`jDdgfTp_PXw`의 17:37 버전** 기준입니다. 자동자막이며 수동 검수·별도 STT 결과가 아닙니다. [18:31 원본](https://www.youtube.com/watch?v=u-o0sW9nwmk)이나 [기존 Boundary/Aaron 영상의 43–53분](https://www.youtube.com/watch?v=mAKUL12h1n8&t=2580s)으로 시각을 옮겨 쓰면 안 됩니다. 기존 영상의 stale·feedback 논의도 제공된 audit상 제안과 남은 문제의 설명이지 완성된 구현 증거가 아닙니다.

다음 결정 대상으로는 **B의 실제 차이와 최소 후보 생성·feedback 소비 범위**를 권고합니다. 성능 향상과 Skills 지원 여부는 그 이후의 별도 검증 판정으로 남겨야 합니다.
