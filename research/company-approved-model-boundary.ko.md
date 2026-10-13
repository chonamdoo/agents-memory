# 회사 승인 Claude/Codex와 memory pipeline의 데이터 경계

조사 기준: 2026-10-11. 공식 공개 문서만 조회한 설계 조사다. 실제 회사의 플랜, 계약, 데이터 등급별 승인 범위, 설치 버전과 관리 설정은 알 수 없으며 검사하지 않았다. 계정, credential, 내부 설정, 실제 endpoint를 조회하거나 호출하지 않았다.

## 결론

**회사가 초대한 회사 소유/팀 Claude Code와 Codex 계정을 승인했다는 전제를 유지한다. 회사가 완전 망분리 환경이라고 가정하거나, 기존 승인 SaaS 모델을 로컬 모델로 의무 교체할 이유는 없다.** 다만 승인된 coding host의 모델 사용과 새 memory worker의 API 사용, embedding 서비스, memory SaaS와 백업은 서로 다른 데이터 처리 경로다.

[설계 판단] 회사 memory 원문, 파생 기억, embedding, 팀 skills/rules, 로그와 백업은 회사 통제 환경에 둔다. 승인된 host에 필요한 기억만 전달할 수 있지만, **그 결과를 host가 모델 입력에 사용하면 승인 provider로 전송된다.** 'memory DB는 회사 내부'와 '회상 결과도 외부 전송 없음'은 같은 약속이 아니다. 사용자가 허용한 회사 provider 경로와 금지한 개인 계정/개인 cloud/미승인 제3자 경로를 구분해야 한다.

## 1. 공식 정책: 학습, 보관, 전송을 분리한다

| 제품/경로 | 문서가 보장하거나 설명하는 것 | 보장하지 않는 것 |
|---|---|---|
| Claude Code, Team/Enterprise 등 commercial terms | 코드와 prompt를 generative model 학습에 사용하지 않음. 고객이 model improvement 제공에 명시적으로 참여한 경우는 별도. Claude Code 문서의 Team/Enterprise/API 표준 보관은 30일 | 로컬 CLI라는 이유로 무전송, 무보관, ZDR가 되지 않음 |
| Claude Code, 자격을 충족하고 별도 활성화한 Enterprise ZDR 조직 | 해당 조직으로 인증되는 Claude Code inference의 prompt/response는 응답 후 저장하지 않음. 법률/오용 대응 예외가 있고 정책 위반 자료는 최대 2년 보관 가능 | Enterprise 기본 포함 아님. 개인 계정/다른 조직에 자동 적용 안 됨. claude.ai Chat, Cowork, 행정 metadata, 제3자 MCP 처리까지 포괄하지 않음 |
| Codex, ChatGPT Business/Enterprise/Edu | business 입력/출력은 기본적으로 모델 개선에 사용하지 않음. Business workspace의 Codex에도 같은 약속 적용 | Business를 Enterprise 관리 정책이나 ZDR와 동일시할 수 없음. 정확한 Codex 보관 기간을 모든 플랜에 '30일'로 일괄 적용할 근거 없음 |
| Codex, ChatGPT 로그인 | 해당 workspace 권한/RBAC와 Enterprise retention/residency 설정을 따름 | API key 로그인에 같은 workspace 설정이 자동 적용되지 않음 |
| Codex/API key 및 별도 OpenAI API worker | 해당 API organization의 retention/data-sharing 설정을 따름. API 데이터 학습은 기본 비사용. abuse monitoring logs는 기본 최대 30일이며 법률/보호 목적의 연장 예외 있음 | ChatGPT 구독 승인이 API organization/project 승인을 대신하지 않음. API no-training은 application state 무보관이 아님 |

근거: [Claude Code data usage](https://code.claude.com/docs/en/data-usage), [Claude Code ZDR](https://code.claude.com/docs/en/zero-data-retention), [Codex plan FAQ: Does OpenAI train on my Codex usage?](https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan), [Business privacy와 Codex](https://help.openai.com/en/articles/8798634-managing-data-sharing-and-privacy-in-chatgpt-business), [Codex authentication](https://learn.chatgpt.com/docs/auth), [OpenAI API data controls](https://developers.openai.com/api/docs/guides/your-data).

### 학습 비사용과 기밀유지

Anthropic Commercial Terms B는 Customer Content로 모델을 학습하지 않는다고 규정하며, E는 Customer Content를 고객의 기밀정보로 취급한다. OpenAI Services Agreement 4.2는 서비스 제공, 법률 준수, 정책 집행과 오용 방지에 필요한 사용을 허용하고 고객의 명시 동의 없이 서비스 개발/개선에 사용하지 않는다고 규정한다. 같은 계약 7과 Definitions는 Customer Content를 포함하는 기밀정보의 보호 의무와 허용 공개를 정한다. **이는 계약상 처리 목적과 기밀유지 약속이지, provider가 데이터를 받거나 처리하지 않는다는 뜻이 아니다.** 실제 회사의 별도 Order Form/DPA/예외 약정은 이번 조사로 확인할 수 없다.

근거: [Anthropic Commercial Terms B/C/E](https://www.anthropic.com/legal/commercial-terms), [OpenAI Services Agreement 4/5/7/17](https://openai.com/policies/services-agreement/).

### 전송과 저장의 구체적 차이

- Claude Code는 로컬 실행이어도 LLM과 상호작용할 때 prompt와 output을 네트워크로 전송한다. 공식 문서는 TLS 1.2+를 명시한다. 로컬 session transcript는 기본 `~/.claude/projects/`에 plaintext로 저장되고 기본 정리 기간은 30일이며 일부 Desktop/Cowork transcript는 예외다. 따라서 provider 정책 외에 단말, 동기화와 백업 정책도 필요하다.
- Claude의 `/feedback`, `/bug`, `/share`로 공유한 transcript는 5년 보관이다. 별도 선택형 session transcript 공유는 최대 6개월이다. coding request의 표준 30일과 피드백 전송을 혼동하지 않는다. 비필수 telemetry를 끄는 것만으로 inference가 오프라인이 되지 않는다.
- OpenAI API의 `/v1/embeddings`는 기본 abuse logs 30일, application state 없음, ZDR eligible로 표기된다. 그래도 **embedding 생성 입력은 API로 보내는 별도 전송**이다. `/v1/vector_stores`는 삭제까지 보관하고 ZDR eligible이 아니다. Responses API는 기본 application state 보관이 있고 `store=false`만으로 기본 abuse logs까지 없애지는 못한다.
- OpenAI API ZDR/MAM은 사전 승인과 organization/project 설정이 필요하고 endpoint/feature별 제한과 예외가 있다. API의 ZDR 설명을 ChatGPT Business 전체나 모든 Codex 기능의 무보관 약속으로 옮기지 않는다.
- ChatGPT 일반 chat은 삭제 또는 workspace retention에 따른 삭제까지 저장되고 삭제 후 통상 30일 내 영구 삭제 대상으로 처리된다. 이것은 일반 ChatGPT chat 정책이며 모든 Codex 저장물의 동일한 TTL을 입증하는 자료가 아니다. Enterprise retention 설정의 실제 값은 미확인이다.

근거: [Claude data flow/local cache/feedback](https://code.claude.com/docs/en/data-usage), [OpenAI endpoint retention table](https://developers.openai.com/api/docs/guides/your-data), [OpenAI enterprise privacy](https://openai.com/enterprise-privacy/), [ChatGPT chat/file retention](https://help.openai.com/en/articles/8983778-chat-and-file-retention-in-chatgpt).

## 2. 구독 승인과 worker 승인/권한은 별개다

공식 Claude 안내는 paid plan과 Console/API가 별도 제품이며 API 사용에는 별도 Console 설정이 필요하다고 설명한다. 현재 안내에는 **Max/Team의 월간 API credits**도 명시되어 있다. 따라서 '구독이면 API는 절대로 포함되지 않는다'는 단정도 부정확하다. 크레딧이 있더라도 조직, credential, 처리 범위와 회사 승인을 자동 확정하지 않는다.

OpenAI는 ChatGPT subscription 로그인과 API key usage-based 로그인을 구분하고, API key 사용은 Platform에 청구한다고 설명한다. 현재 Enterprise에는 승인된 trusted non-interactive Codex local workflows용 Codex access tokens도 있다. **모든 automation이 반드시 일반 API key만 써야 한다는 설명은 틀리지만, Codex access token도 일반 OpenAI API 호출용 credential은 아니다.** 설치 surface/플랜/권한의 실제 적용은 미확인이다.

Anthropic Agent SDK 문서는 사전 승인 없는 제3자 개발자가 자신의 제품에 claude.ai 로그인/구독 rate limits를 제공하는 것을 허용하지 않는다고 명시한다. 'OSS memory worker가 사용자의 coding subscription OAuth token을 복사해 일반 inference API처럼 호출한다'를 기본 아키텍처로 약속하지 않는다. 공식 CLI의 회사 승인 사용과 별도 제3자 제품의 구독 credential 재사용은 구분한다.

근거: [Claude paid plan/API 구분](https://support.claude.com/en/articles/9876003-i-have-a-paid-claude-subscription-pro-max-team-or-enterprise-plans-why-is-claude-api-usage-billed-separately-from-my-paid-claude-plan), [OpenAI authentication와 access tokens](https://learn.chatgpt.com/docs/auth), [OpenAI admin rollout의 Platform 경계](https://learn.chatgpt.com/docs/enterprise/admin-setup), [Anthropic Agent SDK overview의 인증 제한](https://code.claude.com/docs/en/agent-sdk/overview).

[설계 판단] coding host를 승인했다는 사실만으로 새 extraction/embedding API, 미승인 모델 proxy, SaaS memory DB, 외부 backup 또는 개인 계정을 승인했다고 추론하지 않는다. 이는 provider가 추가 전송을 전부 금지한다는 주장이 아니라 **회사 승인 범위가 아직 증명되지 않았다는 판단**이다. 같은 provider라도 계정/조직/region/feature/목적/보관 설정이 바뀌면 다른 승인 경로다.

## 3. managed host와 MCP 인증의 역할

### 문서상 지원하는 관리 기능

- Claude Code에는 managed settings, MCP allow/deny 및 managed-only 배포, OS sandbox/network allowlist, `forceLoginMethod`/`forceLoginOrgUUID`와 새 버전의 `allowedProviders`가 있다. 다만 org 검증은 claude.ai 로그인과 일부 surface에 적용되며 Console 로그인, gateway, cloud-provider와 일부 token 생성 경로에는 다른 제한/예외가 있다. server-managed 설정만으로 아직 회사 조직에 로그인하지 않은 개인 계정의 최초 사용을 회사 조직으로 유도/강제한다고 주장하지 않는다.
- 현재 Codex 문서는 로컬 system/MDM `requirements.toml`의 `allowed_login_methods`와 `allowed_chatgpt_workspaces`, credential-store 요구사항을 설명한다. 이 authentication 요구사항은 cloud-managed requirements에서는 무시되며 credential loading 전에 로컬에서 적용해야 한다. MCP allowlist는 이름과 identity가 승인 항목에 모두 맞아야 한다. `managed_config.toml` 같은 defaults와 사용자 변경 불가 requirements도 구분한다.

근거: [Claude admin setup](https://code.claude.com/docs/en/admin-setup), [Claude authentication의 org 제한과 예외](https://code.claude.com/docs/en/authentication#restrict-login-to-your-organization), [Codex managed configuration](https://learn.chatgpt.com/docs/enterprise/managed-configuration).

### MCP가 자동으로 증명하지 않는 것

MCP HTTP OAuth는 **memory resource server에 대한 접근권한**이다. specification은 이 서버를 intended audience로 하는 access token을 검증하도록 요구한다. Client ID Metadata Document는 앱 이름/redirect URI 등 client 등록 정보를 설명한다. 그것이 현재 Claude/Codex inference에 쓰는 provider workspace나 회사 계약을 증명하는 표준은 아니다. STDIO는 같은 HTTP OAuth 규약이 아니라 environment credential 등의 배포 경계를 사용한다.

[설계 판단] `client_name="Codex"`, `company=true`, `workspace_id` 같은 self-reported metadata나 tool argument를 회사 접근의 증거로 믿지 않는다. memory 서버는 회사 IdP/신뢰 issuer가 발급한 자기 audience용 token과 서버 측 membership/scope로 회사 데이터를 허가한다. 하지만 이것으로 **host의 이후 모델 전송 경로까지 증명되지는 않는다.** approved workspace/model routing은 별도 managed host/device/gateway 정책으로 제한하며, 둘 사이의 실제 보장이 없는 배포는 '회사 workspace verified'라고 표기하지 않는다. provider login token을 MCP token 대신 수집/통과시키는 구조도 사용하지 않는다.

근거: [MCP authorization roles/resource/audience/token handling](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization), [MCP client registration](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/client-registration). 마지막 단락은 해당 문서에 없는 generic provider-workspace attestation을 가정하지 않기 위한 설계 판단이다.

## 4. 사용자 전제를 유지하는 승인 경로와 선택형 오프라인

아래는 구현 완료 사실이 아닌 **[설계 제안]**이다.

1. **승인된 coding host 유지:** 회사 memory 서비스가 raw corpus/검색/보관/백업을 회사 환경에서 담당한다. 승인된 회사 Claude Code/Codex host가 필요한 최소 memory를 조회하고 이미 승인된 모델 경로에서 추론하여 memory/skill 후보를 회사 서비스에 돌려준다. 이것도 recall 결과와 추론 입력의 provider 전송을 포함하므로 데이터 등급/목적별 승인 범위 안에서만 사용한다. worker가 별도 inference API를 호출해야 하는 것은 아니다.
2. **독립 worker가 필요할 때:** 회사가 별도 승인한 organization/project/endpoint/credential로만 추출/반성 모델을 호출한다. embedding도 별도 승인 경로로 취급한다. 공식 Enterprise automation 경로를 선택한다면 그 host, token, 권한과 제한에 맞춰 사용하고 일반 API 권한과 혼용하지 않는다. 승인이 없는 기능은 개인 credential이나 다른 vendor로 자동 전환하지 않는다.
3. **추가 외부 API 없이 memory 사용:** 회사 내부 lexical/full-text 검색, 회사 통제 내부 embedding 또는 로컬 embedding, 규칙 기반 수집과 승인 host의 사용자 주도 정리로 운영할 수 있다. 이 상태는 memory backend의 외부 API 미사용이지 approved host까지 완전 오프라인인 것은 아니다.
4. **완전 오프라인 옵션:** 외부 model/embedding API, hosted coding tasks, sync/telemetry/feedback, 외부 backup과 네트워크 도구까지 사용하지 않는 별도 배포다. 필요한 모델/embedding도 승인된 내부 장비에서 실행하거나 비모델 처리로 대체하고 업데이트/배포도 내부 경로를 쓴다. 일반 SaaS Claude/Codex inference를 계속하면서 전체 pipeline이 완전 오프라인이라고 주장할 수 없다. 이 옵션은 더 강한 무반출 요구가 있는 환경을 위한 선택이며 현재 회사의 기본 전제가 아니다.

회사와 개인 환경에는 같은 OSS core/interface를 쓰되 서로 다른 deployment, 데이터 저장소, identity, secret와 backup을 사용한다. 회사 corpus를 personal cloud로 동기화하거나 회사 결과로 personal skills를 자동 업데이트하지 않는다. 팀 review 교훈과 conventions는 회사 통제 versioned skills/rules 저장소에서 검토/승인/배포하며, vector-store 검색 사실과 native host에 규칙이 실제 적용됐다는 사실을 별개로 다룬다. generic MCP 연결만으로 host 파일이 자동 갱신되거나 team skill이 강제 적용되는 것은 약속하지 않는다.

## 5. 미확정 범위

공개 문서는 실제 회사 보안 적합성 증명이 아니다. 정확한 계약/플랜, 별도 API 승인, data class별 allowed payload, 실제 조직/로그인 방법, 관리 설정/host version, retention/residency/ZDR 활성화, skills 배포 경로와 backup owner는 미확인이다. 이 불확실성은 '회사는 모든 SaaS를 금지한다'는 근거도, '기업 계정이면 모든 memory 전송이 허용된다'는 근거도 되지 않는다.

이번 작업은 새 조사 문서만 작성했다. 회사/private 설정이나 credential을 읽지 않았으며 코드 변경, live endpoint probe, build/lint/test/formatter 실행은 하지 않았다.
