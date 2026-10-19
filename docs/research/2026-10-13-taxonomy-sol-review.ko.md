# Codex 6.1 Sol xhigh 별도 적대적 분류체계 리뷰

## 실행 증거와 한계 — 정리 담당자가 추가한 메타데이터

- 실제 native CLI: `codex-cli 0.162.1`. 요청 모델 `gpt-6.1-sol`, 요청 reasoning effort `xhigh`. **관측 served model: `unobserved`**. JSONL에 served model 식별자가 없어 요청 인자만으로 실제 서버 라우팅을 증명하지 않는다.
- 공개 packet과 `독립적인 반대자의 관점에서 10기준 모두 평가, 한국어 Markdown`만 stdin으로 전달했다. 두 시도의 stdin은 동일하다. 기본 모델의 답변을 지정 모델 결과로 바꿔 표기하지 않았으며 다른 모델 fallback은 없다.
- cwd는 repo 밖 `/private/tmp`의 별도 mode 0700 directory. 개인 native auth를 기존 CLI가 사용하도록 두었고 auth 파일을 읽거나 복사·추출하지 않았다. timeout은 각 시도 1200초.
- **1차:** 지정된 정확 argv로 실행, exit `0`, 775.105초. web tool 4건, `codex_apps/github.fetch` 2건(총 6개 tool id / 12 started·completed events)이 관측되었다. 공개 packet의 링크를 조회한 호출이며 tools-disabled 격리 요구 실패로 별도 보존했다. stderr에는 collab spawn 실패가 있다. 이 시도의 답변은 아래 최종 본문으로 사용하지 않았다.
- **2차:** 동일 모델/effort/packet에 `web_search="disabled"`, `features.apps=false`, `features.multi_agent=false`를 추가했다. exit `0`, 437.02초. **built-in MCP resource listing calls=2, started/completed events=4**: `codex.list_mcp_resources`와 `codex.list_mcp_resource_templates`. 실제 결과는 각각 `resources: []`, `resourceTemplates: []`였다. web/apps/collab/command/file-change 호출은 이 JSONL에서 관측되지 않았다.
- **완전격리 또는 tools=0을 주장하지 않는다.** 빈 listing 결과와 관측된 호출만으로 provider 내부 접근이나 모든 서버 기능의 차단까지 증명할 수 없다. 관측 JSONL에는 회사/private resource 내용 조회, 외부 app/source 읽기, command 실행이 없다. 이는 회사 production sandbox 인증이나 회사 데이터 접근 허가 판정이 아니다.
- CLI 경고: `features.skills`는 unrecognized/ignored이며 `[features].web_search`는 deprecated이다. 2차의 top-level `web_search="disabled"` 적용 후 web 호출은 관측되지 않았다. 알려지지 않은 설정을 추가해 격리 성공처럼 표기하지 않았다.
- JSONL의 `item.completed` / `agent_message` 4개를 추출했다. 아래 본문은 마지막 답변 그대로이며, 앞선 공개 agent messages는 말미에 별도 보존한다. provider raw JSONL와 reasoning은 이 보고서에 포함하지 않는다.
- 두 호출의 요청 argv, effort, exit, timeout, 관측 tool events와 한계는 `local://agents-memory-taxonomy-codex-proof.json`에 있다. 1차 상세 proof는 `local://agents-memory-taxonomy-codex-attempt1-proof.json`. raw JSONL/stderr는 mode 0600 private artifact에만 보관한다. 공개 게시에는 raw/reasoning을 포함하지 않는다.
- 소스·설정·기존 AF artifact 수정, 설치, build/lint/tests/formatters는 수행하지 않았다. 본문은 독립적인 설계 리뷰이며 AF 구현 승인·회사 실행 가능·운영 효율의 증거가 아니다.

### 최종 리뷰에 사용한 실제 argv

```sh
codex exec --model gpt-6.1-sol --config 'model_reasoning_effort="xhigh"' --config 'mcp_servers={}' --config features.shell_tool=false --config features.web_search=false --config features.skills=false --config features.unified_exec=false --ignore-user-config --ignore-rules --ephemeral --sandbox read-only --skip-git-repo-check --json --config 'web_search="disabled"' --config features.apps=false --config features.multi_agent=false -
```

---

## Native 최종 agent_message — 원문

# 결론

**분류체계는 B처럼 관리용 view로 조건부 추천한다. Profile always-on은 추천하지 않는다.** 네 분류를 독립적인 저장소로 나누는 C도 현재는 보류한다. 검증 전에는 A를 기준선으로 유지하는 편이 낫다.

핵심 문제는 분류의 이름보다 **정체성·권한·시간·승인·철회가 분류를 넘어 유지되는가**다. 같은 사실을 Profile과 Log에 넣었을 때 각각 수정하거나 승인해야 한다면, 분류가 관리 비용과 모순을 만든다.

이 보고서의 근거를 다음처럼 구분한다.

- **입력 사실:** 사용자가 제공한 현행 구현 상태와 고정 제약. 저장소를 직접 확인한 결과는 아니다.
- **정적 소스 요약:** 사용자가 제공한 고정 commit의 관찰. 링크 원문을 이번에 재확인하지 못했다.
- **추론:** 그 사실과 설계에서 예상되는 실패 경로.
- **제안:** 아직 구현되거나 승인된 것으로 볼 수 없는 정책.
- **미측정:** 정확도·비용·운영 효율·공격 방어 효과.

소스·설정·AF artifact 변경, 설치, build/lint/tests/formatters 실행, credentials·회사 corpus 접근은 하지 않았다. 이 리뷰는 기존 AF 승인이나 회사 사용 가능 판정과 별개다.

# P1/P2 실패 시나리오

아래는 **발견된 구현 버그가 아니라 설계에 대한 공격 시나리오**다. P1은 권한·승인·철회 경계를 깨는 문제, P2는 기억의 정확도·재개·비용 문제로 둔다.

| 우선순위 | 공격 시나리오 | 실패 결과 | 필요한 방어 |
|---|---|---|---|
| P1 | “이 프로젝트에서는 npm을 쓴다”를 전역 Profile로 승격 | 다른 프로젝트나 회사 작업에 조건 없는 선호 적용 | 조건과 scope 보존. 전역 승격은 별도 판단·권한 검증 |
| P1 | 개인 Profile을 회사 host에 자동 주입 | 개인 정보 또는 다른 프로젝트 정보 누출 | 현재 recipient·scope·grant를 반환 시점에 서비스가 검증 |
| P1 | 검색된 경험의 명령문을 Profile이나 skill로 승격 | 공격 문장이 지속적인 행동 규칙이 됨 | 사실 데이터와 권위 있는 지침 분리. 실행 지침은 별도 서명 승인 |
| P1 | corpus 철회 후 생성한 skill 상세·캐시가 남음 | 철회된 원문이 다른 형태로 계속 제공됨 | 파생 관계 추적. 검색·상세 읽기·캐시·host pack 모두 차단 |
| P1 | 높은 confidence, `judge`, preview token을 승인으로 취급 | 모델의 판단이 권위 있는 규칙으로 활성화됨 | 판단 결과와 승인 증거를 별도 필드·전이로 관리 |
| P1 | 회사 executor 실패 시 개인 Jev로 fallback | 회사 데이터가 개인 경로로 이동 | 서비스의 실행 경로에서 차단. 모델 지침에 의존하지 않음 |
| P2 | “오늘/지난주”를 수집일이나 현재 날짜로 해석 | 사건 순서와 과거 조회 오류 | 원문 시각·timezone·해석 규칙 사용. 없으면 보류 |
| P2 | Notes TTL을 넘기면 삭제하거나, 재개하면 새 정보로 취급 | 재개 근거 소실 또는 낡은 메모의 오사용 | 만료·삭제·최신성·재개를 별도로 처리 |
| P2 | 분류 오류·timeout을 `excluded`로 hard drop | 유용한 기억이 복구 불가능하게 사라짐 | 기술 실패와 의미적 제외 분리. 제한된 재시도·검토 경로 |
| P2 | Profile이 context를 먼저 차지해 원문 근거가 잘림 | 기억의 주장만 남고 검증 근거가 사라짐 | 전체 예산 안에서 주장·근거·출처를 함께 제한 |
| P2 | 모순된 Log 중 `recorded_at`이 최신인 것을 선택 | 늦게 수집한 과거 사실이 현재 사실을 덮음 | 사건·유효 시간과 기록 시간을 분리. 충돌 보류·abstention |

날짜 오류가 권한의 유효 기간을 바꾸거나, 만료된 Notes가 민감 정보로 계속 노출되면 해당 문제도 P1이다.

# 분류별 평가

## 1. 분류 축과 사실의 정체성

**[추론] 네 분류는 같은 축이 아니다.**

| 분류 | 실제로 섞인 축 |
|---|---|
| Profile | 사용자에 대한 의미 + 반복 사용성 + 항상 로드 정책 |
| Log | 사건이라는 의미 + 시간 |
| Notes | 작업 범위 + 임시 수명 |
| 파일·스킬 | 저장 매체 + 상세 조회 방식 + 경우에 따라 실행 지침의 권위 |

“사용자가 프로젝트 X에서 npm을 선택했다”는 사건은 Log이고, 진행 중인 작업에는 Notes이며, 조건부 선호로는 Profile 후보다. 이를 하나의 배타적 분류로 강제하면 조건이나 근거를 잃는다.

**[제안] canonical ledger의 기록을 유지하고 분류는 겹칠 수 있는 view/tag로 둔다.**

- 서비스가 발급한 `memory_id`를 유지하고, 내용 변경은 새 revision으로 남긴다.
- 분류 변경은 복제나 새 사실 생성으로 취급하지 않는다.
- 출처 revision과 근거 위치, 조건, scope, 시간, 승인 상태를 분류와 별도로 둔다.
- `derived_from`, `supersedes`, `contradicts` 같은 관계로 파생·교정·모순을 구분한다.
- 비슷한 문장은 동일 사실로 자동 합치지 않는다. 적용 프로젝트나 기간이 다르면 함께 참일 수 있다.

`patch`는 현재 revision과 권한을 서비스가 확인해야 한다. 분류 변경만으로 scope를 넓히거나 승인을 승계해서는 안 된다.

## 2. Profile: 효용은 가능하지만 always-on 근거는 부족하다

**[추론]** 자주 필요한 언어·접근성·작업 선호는 반복 설명을 줄일 수 있다. 하지만 “항상 필요한 사실”이라는 정의 자체가 모든 host와 작업에서 필요한지를 증명하지 않는다.

항상 로드하면 다음 비용이 생긴다.

- 관련 없는 작업에서도 token과 context를 소비한다.
- 민감 정보의 노출 횟수와 노출 경로가 늘어난다.
- 개인·회사·프로젝트 조건이 압축 과정에서 사라질 수 있다.
- 낡은 선호가 현재 요청보다 먼저 영향을 줄 수 있다.
- 원문에 섞인 명령문이 반복 주입되는 공격 경로가 생긴다.

[MemoryGraft](https://arxiv.org/abs/2512.16962)는 오염된 검색 경험이 지속적인 위험 행동으로 이어질 수 있음을 다룬다. 이것이 이번 Profile 설계의 공격 성공률을 보여 주는 것은 아니다. 여기서는 **검색된 데이터의 지침 승격을 별도로 방어해야 한다는 근거**로만 사용한다.

**[제안] Profile은 제한된 조회 후보로 둔다.** 현재 요청·scope·grant·민감도·예산에 따라 필요한 항목만 선택한다. Profile 분류, 높은 confidence, 최근 기록이라는 이유만으로 preload하지 않는다.

일부 기본 선호의 자동 주입을 나중에 검토한다면 대상·host·예산·재확인 정책을 따로 정의해야 한다. 이번 제안의 포괄적인 Profile always-on과는 다른 결정이다.

## 3. Log: 날짜 하나로는 부족하다

**[제안] 다음 시간을 구분해야 한다.**

| 시간 | 의미 |
|---|---|
| `source_event_time` | 수집 경로가 확인한 원문 이벤트 시각 |
| `recorded_at` | 서비스가 기록한 시각 |
| 사건의 발생 시각·범위 | 원문이 설명하는 사건이 발생한 때 |
| 유효 기간 | 주장이나 규칙이 적용되는 기간 |

발화 시각이 사건 시각은 아니다. “지난주에 변경했다”라는 발화의 `source_event_time`을 변경 사건의 정확한 시각으로 복사하면 안 된다.

“오늘/지난주”는 원문 발화의 시각·timezone·해석 규칙에 묶어야 한다. 주 단위 표현은 범위로 남길 수 있다. 근거가 없으면 정확한 시각을 모델이 만들어 넣지 말고 미해결로 둔다.

과거 조회도 두 질문을 구분해야 한다.

- **그때 무엇이 유효했는가?**
- **그때까지 무엇을 알고 있었는가?**

나중에 들어온 교정은 현재 답을 바꿀 수 있지만, 과거에 무엇을 알고 있었는지까지 덮어쓰면 안 된다. 모순은 최신 기록일 하나로 해결하지 않는다. 같은 scope·조건·기간에서 충돌하는지 확인하고, 해결되지 않으면 abstention을 허용해야 한다.

## 4. Notes: TTL은 최신성이나 삭제가 아니다

**[추론]** Notes는 중단한 작업의 재개에 유용할 수 있다. 다만 “단기”가 session, thread, task, project 중 무엇을 뜻하는지 먼저 정해야 한다. 하나의 task가 여러 session에 걸칠 수 있다.

**[제안]**

- task와 관련 session/thread/agent identity를 연결한다. identity는 수집 경로의 사실이다.
- 작업 종료는 명시적인 상태로 남긴다. 무활동과 완료를 같게 취급하지 않는다.
- TTL은 기본 조회에서 빠지는 시점으로 정의할 수 있다.
- 재개할 때 현재 grant와 원문 revision을 다시 확인한다.
- 재개하거나 다시 기록했다고 의미적으로 최신 정보가 되지는 않는다.
- 장기 승격은 새 후보로 심사한다. 반복 조회 횟수만으로 승격하지 않는다.

TTL 만료, 원문 철회, 데이터 삭제는 별개의 동작이다. Notes에 있다는 이유로 민감 정보의 retention을 임의로 늘려서도 안 된다.

## 5. 파일·스킬: 저장 매체와 권위를 분리해야 한다

**[제안] 파일 검색 결과는 원문·revision·근거 위치에 묶는다.** 검색용 요약과 실제 상세 읽기가 서로 다른 revision을 가리키면 안 된다.

필요한 상세만 읽는 방식은 context를 줄일 가능성이 있다. 다만 검색 실패, 잘못된 요약, revision 누락으로 중요한 조건을 놓칠 수도 있다. 효과는 미측정이다.

파일의 설명을 skill로 바꾸는 일은 단순한 저장 위치 변경이 아니다. **데이터에서 실행 가능한 지침으로 승격하는 전이**다.

- 출처의 주장과 운영자가 승인한 규칙을 구분한다.
- 권위 있는 지침에는 승인 주체·서명·적용 scope·승인한 revision을 묶는다.
- 승인 후 내용이 바뀌면 기존 승인을 그대로 사용하지 않는다.
- corpus 철회 시 파생 skill의 상세와 캐시도 현재 사용 가능 여부를 검사한다.
- 승인 서명만으로 원문과의 파생 관계가 없어지지는 않는다.

서비스 밖으로 이미 전달된 내용이나 통제하지 못하는 복사본의 완전한 삭제는 별도 한계다. 회사 계정의 data retention도 미확인이다. 검색 제외만으로 철회·삭제 완료를 선언할 수 없다.

## 6. 후보 판단과 수명주기

**[제안] 다음 상태를 하나의 enum으로 섞지 않는다.**

| 차원 | 예 |
|---|---|
| 분류 판단 | 후보 / 제외 / 검토 필요 |
| 제안된 변경 | no-op / create / patch / 충돌 보류 |
| 승인·사용 상태 | 미승인 / 승인 / 활성 / 만료 / 철회 |
| 데이터 보관 상태 | 보관 / 삭제 진행 / 삭제 완료 |

높은 confidence는 분류기가 자기 판단에 확신한다는 뜻이다. **진실·인간 승인·권위·항상 로드**를 뜻하지 않는다.

모든 저위험 관찰을 사람이 건별 승인해야 한다는 결론도 아니다. 자동 처리가 필요하면 운영자가 서명한 사전 정책의 범위 안에서 수행하고, 승인 근거를 그 정책으로 남겨야 한다. 모델의 `save`나 `judge`가 그 근거를 대신할 수는 없다.

**[제안] 변경 결과의 계약도 명시한다.**

| 결과 | 서비스가 확인할 조건 |
|---|---|
| no-op | 이미 반영된 동일 입력·revision이거나 변경할 내용이 없음 |
| create | 허용된 scope의 새 기록. 모델이 새 권한을 만들지 않음 |
| patch | 대상 identity·현재 revision·변경 권한 확인 |
| 충돌 보류 | 의미 충돌, revision 변경, 권한 변경, 근거 부족 등을 구분 |

분류 실패나 근거 부족을 no-op으로 숨기면 운영자는 정상 처리와 실패를 구별할 수 없다.

### 공개 OSS에서 확인되는 범위

**[정적 소스 요약]** 아래는 제공된 자료가 보여 주는 부분이다. 모두 같은 층의 시스템은 아니므로 완성된 동일 파이프라인으로 비교할 수는 없다.

| 자료 | 확인된 처리 | 확인되지 않은 계약·해석 한계 |
|---|---|---|
| engram [MCP](https://github.com/Gentleman-Programming/engram/blob/5c4171845958f046968c14d7d57a325eb4a83b7e/internal/mcp/mcp.go), [candidate relevance](https://github.com/Gentleman-Programming/engram/blob/5c4171845958f046968c14d7d57a325eb4a83b7e/internal/store/candidate_relevance.go) | agent-owned save/judge, deterministic conflict candidate relevance | 사람 승인과 같지 않음. 요약만으로 전체 no-op/create/patch/보류 전이표는 확정할 수 없음 |
| [mnema](https://github.com/Ray0907/mnema/blob/eed19586156ae9664451cb94859f8f3f16b3ac4a/src/mcp-server.ts) | read search, opt-in writes, `resolve_preview`→`resolve_commit` hash token | token은 입력 확인이다. 인간 승인이나 현재 grant·철회 검증을 증명하지 않음 |
| [LangMem](https://github.com/langchain-ai/langmem/blob/48e3c11f5bb527282c7d5339c6a87a0b35abccfc/src/langmem/knowledge/extraction.py) | episode/fact/note/preference 내용 schema, insert/update extractor, semantic/procedural/episodic 지침 | supporting quote는 필요할 때 사용하는 prompt 지침. 필수 machine-verified span 계약이 아님 |
| [memharness](https://github.com/las7/memharness/blob/faed4b346e445d2344ed02e8211759999acd946d/packages/core/src/staleness.ts) | git source pin을 current/stale/unresolved로 분류. unknown/diverged는 unresolved | source freshness 판단이다. 의미적 진실·승인·유용성 판정이 아님 |
| [codex-agent-mem](https://github.com/MarceloCaporale/codex-agent-mem/blob/d594c8a86207fb9a8a5b48a6aab323349680707a/src/codex_agent_mem/context_pack.py) | micro/normal/full의 1000/2200/3600 **문자** 예산과 section limits | token 예산이나 선택 정확도 보장이 아님. 후보 승인·충돌 처리 전체 계약의 근거도 아님 |

이 자료는 기능별 선례를 제공한다. **네 분류의 타당성, 제품 통째 재사용 가능성, 회사 운영 가능성을 입증하지는 않는다.** 제공된 요약에 없는 제외 조건이나 no-op 동작을 추정해서 채우면 안 된다.

## 7. 비용: 분류와 전체 로그 재분석을 구분한다

**[제안] 비용을 줄일 첫 대상은 새 분류 모델보다 반복 분석이다.**

- 이미 모델이 읽고 있는 현재 세션에서 제한된 후보를 제안하게 한다.
- 새로 들어온 이벤트·변경된 revision·명시적인 재검토 대상만 처리한다.
- 코드로 확인할 metadata·권한·정확한 중복은 모델에 맡기지 않는다.
- 후보마다 원문과 근거의 최대 범위를 제한한다.
- 조회 결과 수, 상세 읽기량, context pack 전체 예산을 제한한다.

현재 세션에서 후보를 내는 것도 무료는 아니다. 추가 출력과 검증 비용이 든다. 다만 별도 호출로 전체 로그를 다시 읽는 방식과는 비용 구조가 다르다.

소형 판단에는 다음 위험이 있다.

- false-negative로 중요한 조건·사건을 놓친다.
- 성급한 hard drop이 재검토 근거를 없앤다.
- batch에서 speaker·scope·시간이 섞인다.
- 짧은 원문이 앞뒤의 부정·교정·인용 관계를 잃는다.

따라서 기술 실패는 의미적 제외와 분리하고, 제외 후보의 표본 검토와 제한된 복구 경로를 둬야 한다. 보관 범위와 기간은 별도 승인 정책을 따른다.

**[미측정]** B가 A보다 저렴하다는 보장은 없다. 분류·검토·재시도 비용이 검색 절감보다 클 수 있다. C의 Profile preload도 반복 비용에 포함해야 한다. 영상의 95% 절감 수치는 이 설계의 측정값이 아니다.

회사는 로컬 embedding/reranker 등 ML 모델을 설치할 수 없다. Claude/Codex 팀 계정이 있다는 사실만으로 headless 자동화·quota·retention이 허용된 것은 아니다. 현행 개인 local-model executor를 회사용 구현으로 볼 수 없고, 개인 Jev는 회사의 대체 경로가 될 수 없다.

# A/B/C 영향과 장단점

## 8. 구현 영향

**[추론] 변경량의 핵심은 view 추가와 독립 원장 추가의 차이다.** 실제 core/callsite/DB 코드를 읽지 않았으므로 파일·migration 수는 미확인이다.

| 영역 | B: canonical ledger + views/tags | C: 독립 store + Profile always-on |
|---|---|---|
| core | 분류·선택 정책 추가. identity·권한·revision 규칙 공유 | store 간 공통 identity·revision·권한·전이 규칙 필요 |
| callsite/API | 선택 view, 예산, 근거·상태 반환 계약 | 다중 store 읽기·쓰기·충돌·부분 실패 처리 |
| DB | 추가 필드·관계·조회 구조 | store 이동·복제·동기화·원자성 설계 |
| FTS/검색 | view와 현재 권한에 맞는 조회·무효화 | 여러 index의 권한 필터·삭제·revision 정합성 |
| host | CLI/MCP/Claude/Codex/omp의 요청별 선택 계약 | 각 host의 preload 실행·예산·철회 대응 |
| approval | 동일 기록의 승인과 분류 분리 | 복제·이동 시 승인 대상과 효력 재정의 |
| deletion | 원문→파생물→index/cache 영향 추적 | 모든 store와 파생 경로의 누락 방지 |

물리적인 table이나 index 분리는 canonical ledger와 양립할 수 있다. 문제는 네 store가 각자 사실의 권위 있는 원장이 되는 경우다. 이를 안전하게 만들려면 결국 공통 identity와 전이 규칙을 다시 구축해야 한다.

하나의 core를 두어도 host의 전달 방식은 별도로 검증해야 한다. **MCP 연결은 기억 전체의 자동 주입을 보장하지 않는다.**

## 9. 같은 조건에서 비교한 선택지

세 대안 모두 현재 grant, source revision, 승인, 철회, 회사 실행 경로 제약을 동일하게 적용해야 한다.

| 대안 | 장점 | 위험·한계 | 판정 |
|---|---|---|---|
| **A — scope+revision+bounded retrieval 유지** | 추가 분류 비용이 적고 기존 조회 경계를 유지 | 시간·task 상태·승인·파생 관계가 충분한지는 별도 확인 필요 | **기준선 유지** |
| **B — 네 분류를 관리용 view로 도입, 무조건 preload 없음** | 정리·재개·선택 조회를 돕고 같은 사실의 identity 유지 | 태그 오류, 관리 복잡도, materialized view의 낡은 권한, 분류 비용 | **조건부 추천** |
| **C — 독립 store + Profile always-on** | 종류별 보관·성능 정책을 분리할 여지 | 복제·모순·승인 승계·철회 누락·상시 context 비용 | **보류** |

B도 안전성을 자동으로 높이지 않는다. 태그가 권한 필터를 대신하거나, 나중에 Profile 태그를 preload 승인으로 취급하면 같은 실패가 생긴다.

C의 성능·보관상 이점은 가능성이다. 현재 자료에는 그 이점이 비용과 정합성 부담을 상쇄한다는 측정이 없다. A를 유지한다는 결정도 현행 회사 executor가 준비됐다는 뜻은 아니다.

# 권고 정책

**[제안] 채택 순서는 다음과 같다.**

1. **원장부터 유지한다.** identity, revision, 조건, 시간, 출처, 파생 관계를 공통 계약으로 둔다.
2. **분류를 view로 추가한다.** 겹치는 분류를 허용하고 분류 변경으로 scope·승인을 바꾸지 않는다.
3. **판단과 권한을 분리한다.** 모델은 후보와 변경을 제안한다. 서비스는 현재 grant·revision·철회·삭제 영향 범위를 검증한다.
4. **권위 있는 지침은 별도 승인한다.** 승인한 내용의 revision과 서명을 묶는다. preview token과 도구 annotation을 승인 증거로 쓰지 않는다.
5. **반환을 제한한다.** 항목 수뿐 아니라 원문·상세·근거·출처를 포함한 전체 context 예산을 둔다.
6. **실패를 숨기지 않는다.** 제외·충돌·근거 부족·executor 실패를 구분하고 제한된 검토 경로로 보낸다.
7. **회사·개인 실행 경로를 차단 경계로 둔다.** 회사 경로의 실패는 개인 호출로 복구하지 않는다.

출처, speaker, host/session/thread/agent identity, `source_event_time`, `recorded_at`은 수집·코드의 사실로 보존한다. 모델이 누락값을 보완해서는 안 된다.

# 측정 계획

## 10. 실패 조건과 통과 기준

**[제안·미실행]** 공개·합성 자료로 먼저 평가한다. 회사 corpus나 credentials를 사용하지 않는다.

| 검증 대상 | 입력·상황 | 확인할 결과 |
|---|---|---|
| 조건부 선호 | 프로젝트에만 적용되는 선호, 다른 프로젝트 요청 | 전역 승격·범위 밖 제공 없음 |
| 시간·과거 조회 | 오늘/지난주, 늦은 수집, timezone 누락, 사후 교정 | 임의 날짜 생성 없음. 유효 시점과 당시 지식을 구분 |
| Notes 재개 | 만료, 작업 종료, 다른 session 재개, grant 변경 | TTL과 삭제 구분. 재개 시 권한·revision 재확인 |
| 철회·삭제 | 원문에서 요약·skill·index/cache·host pack 생성 후 철회 | 관리되는 모든 제공 경로에서 차단. 통제 밖 복사본 한계 기록 |
| 분류 실패 | timeout, 잘못된 출력, false-negative, batch 혼선 | 오류가 제외로 처리되지 않음. 복구·검토 비용 측정 |
| 후보≠승인 | 높은 confidence, `judge`, preview token만 존재 | 권위 있는 규칙으로 자동 활성화되지 않음 |
| 회사→개인 차단 | 회사 executor 실패, 개인 endpoint fallback 제안 | 서비스 실행 경로에서 개인 호출 차단 |
| context 한도 | 긴 Profile, 긴 원문, 많은 Log·Notes | 전체 예산 준수. 필수 근거가 부족하면 보류 |
| 수정·모순 | 같은 사실의 여러 view, 동시 patch, 다른 조건의 유사 주장 | identity 유지. revision 충돌 보류. 조건이 다른 사실을 합치지 않음 |

권한·승인·철회·회사 경로 테스트는 통과해야 하는 불변 조건이다. 정확도와 비용은 A/B/C를 같은 자료·권한·전체 context 한도에서 비교한다.

측정 항목은 다음과 같다.

- 후보 precision/recall과 제외 항목의 false-negative.
- 시간 해석·교정·모순·abstention의 정확도.
- 최종 답의 원문 근거 일치와 검색 누락.
- 신규 이벤트당 처리량, 별도 분석 호출, 입력·출력 token.
- 분류·검색·검토·재시도를 합친 비용과 지연.
- Profile의 관련 항목 비율과 context 점유.
- 제외 검토·충돌 해결에 드는 운영자 시간.

[LongMemEval](https://arxiv.org/abs/2410.10813)의 extraction, multi-session reasoning, temporal reasoning, updates, abstention을 분리하는 관점은 참고할 수 있다. 해당 대화 QA 결과를 coding-agent 성능 증거로 옮기지는 않는다.

품질 허용오차와 비용 목표는 실험 전에 정한다. 측정 후 유리한 지표만 골라 “효율 향상”을 선언하면 안 된다.

# 반박 가능한 질문

1. **Profile always-on이 필요한가?** 같은 전체 context 한도에서 선택 조회보다 답의 품질이 좋아지고, 민감 정보 노출과 비용도 허용 범위인가?
2. **독립 store가 필요한가?** canonical ledger의 view·index로 해결하지 못하는 요구가 측정됐고, 수정·승인·철회 정합성도 유지되는가?
3. **분류기는 순이익을 내는가?** 분류·재시도·사람 검토 비용까지 합쳐 A보다 저렴하면서 false-negative가 허용 범위인가?
4. **시간 처리는 신뢰할 수 있는가?** 기준 없는 상대 날짜에 보류하고, 사후 교정 뒤에도 과거 조회를 정확히 답하는가?
5. **철회가 파생물까지 도달하는가?** 원문이 막힌 뒤 skill 상세·cache·host pack에서 같은 내용이 다시 제공되지 않는가?
6. **회사 실행 경로가 실제로 준비됐는가?** headless 허가·quota·retention과 대체 executor가 확인됐고, 실패 시 개인 경로 호출이 차단되는가?

현재 자료로는 **B의 관리 편의 가능성은 검토할 수 있지만, always-on의 순이익과 회사 운영 준비는 입증되지 않았다.**


---

## 앞선 native agent_message 원문

### Message 1

공개 자료와 설계 요구만으로 10개 기준을 검토하겠습니다. `research`와 `write-for-work` 스킬을 확인하고, 분류체계 도입과 Profile 항상 로드는 따로 판정하겠습니다.

### Message 2

현재 도구로는 스킬 파일과 공개 링크를 직접 읽을 수 없습니다. 제공된 고정 commit 요약을 근거로 검토하고, 소스 재확인과 측정은 수행하지 않았다고 표시하겠습니다. 네 분류를 관리용 view로 쓰는 결정과 항상 주입하는 결정은 분리해서 판단하겠습니다.

### Message 3

제공된 자료에서는 후보 판단, source revision 상태 분류, context budget, preview/commit을 서로 다른 단계에서 확인할 수 있습니다. 이것들을 인간 승인이나 Profile 항상 주입의 근거로 합쳐 해석할 수는 없습니다. 특히 같은 사실을 네 저장소에 복제하는 설계와, 원문 철회 뒤에도 skill 상세가 남는 경로를 주요 실패 시나리오로 검토하겠습니다.
