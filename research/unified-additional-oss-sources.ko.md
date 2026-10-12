# 전체 종합 보완: claude-mem·Serena 및 사용자 자료의 취급

공식 문서와 저장소를 다시 직접 읽었다. 실행/설치·기업 계정·제품 보안/품질 실측은 아니다. 원래 다운로드 보고서의 특정 앱 적용안은 사용자의 정정에 따라 제외하며, 그 앱의 코드그래프/SQLite 최소 구성으로 독립 memory 제품을 끼워 맞추지 않는다.

## claude-mem

고정 repo HEAD: `fa8ab09f06aa05f958c5225cf3756ce52a3ebb96`.[C0]

- 로컬 plugin은 SQLite memory DB와 loopback worker, lifecycle capture 및 observer를 사용한다. 공식 config의 provider 기본은 claude이고 auth 기본은 subscription이다. provider 선택에는 codex/gemini/openrouter/openai-compatible도 존재한다. 회사 구독/계정을 제3자 worker에 재사용할 권한은 문서의 기능 지원과 별개다.[C1]
- 현재 Codex observer는 isolated `codex app-server`와 file-backed ChatGPT CLI login을 사용한다고 공식 config가 명시한다. 일반 OpenAI API key 사용과 같지 않다. default-model/effort 및 실패 처리 설명도 있고, 이것을 우리 회사에서 승인·실행됐다는 증거로 쓰지 않는다.[C1]
- SessionStart 기본은 50 observations, main-agent-only true, all-sources false다. 모든 source를 매번 넣는 것을 정당화하거나 우리 제품의 token budget으로 그대로 복사하지 않는다. subagent capture와 SessionStart exclusion은 서로 다르고 episode dedup/recurring-investigation 판정을 대신하지 않는다.[C1]
- worker 기본 host는 127.0.0.1이고 Host/Origin 제한을 설명한다. worker autostart=false이면 hook이 work를 quietly skip할 수 있다고 문서가 명시한다. localhost/Origin을 authenticated project ACL 또는 complete automatic capture의 증거로 사용하지 않는다.[C1]
- Hosted Server Beta는 별도 Postgres HTTP `/v1` + BullMQ generation worker다. `(team_id, project_id)`와 API-key scopes를 설명한다. `/v1/mcp`는 **read-only** search/context/recent이며 write/delete는 다른 API 경로다. 문서는 capture/recall/deletion을 tested라고 주장하지만 이번 조사자가 재현한 것은 아니다. 첫 key bootstrap/dashboard/onboarding은 unfinished라고 명시한다.[C2]
- 따라서 로컬 SQLite/Chroma plugin과 hosted Postgres/BullMQ server가 API/검색/운영까지 동일한 engine이라는 가정은 하지 않는다. 개인 Cloud Sync와 팀 hosted service도 별개다. observer/capture·progressive retrieval의 구현 패턴은 유용하지만 회사 local/개인 cloud에 같은 core·operation/approval/retraction 계약을 그대로 만족하는 drop-in 승자로 선언할 근거는 없다.[C1–C3]
- 공식 config는 quota fallback provider를 별도로 선택할 수 있고 default off라고 설명한다. 원래 다운로드 보고서가 경고한 local OpenAI-compatible model misconfiguration fallback와 구분한다. 회사 profile은 승인되지 않은 fallback 자체를 허용하지 않는다.[C1]

## Serena

고정 repo HEAD: `1de556f71569f3acfc0743e526dd60aca40a545e`.[S0]

- project `.serena/memories/`, global `~/.serena/memories/global/`의 human-readable Markdown을 deliberate read/write하고 Git review 가능한 방향이다. 초기 memory name list는 전체를 전달하며 본문은 agent가 필요하다고 판단해 읽는다. name list도 startup 비용이므로 memory 규모가 커졌을 때 zero-context는 아니다.[S1]
- 공식 design rationale은 database-backed memory와 hooks/harness injection을 의도적으로 제외한다. 파일형 프로젝트 지식/절차에 좋은 비교안이지만 자동 capture→분류→규칙 candidate→후속 task의 full pipeline을 구현하는 서비스와 같지 않다. name/ref selection을 mandatory 회사 규칙의 결정론적 집행으로 읽지 않는다.[S1]
- read-only/ignored-memory 설정은 도구별 기능 경계다. ignored memory가 raw read_file을 통해 읽힐 수 있다는 공식 설명이 있으며, security 문서는 REPL code가 tool exclusions와 read_only를 우회할 수 있다고 명시한다. ACL/보안 sandbox로 재사용하지 않는다.[S1–S2]
- HTTP/network services는 기본 localhost다. untrusted network 접근 제한과 reverse proxy auth/firewall은 사용자 책임이라고 설명한다. single-project activation이나 trust label이 tenant authorization 또는 OS containment를 제공한다는 주장은 하지 않는다.[S2]
- 현행 application GPL-3.0-or-later, SolidLSP MIT는 component별 검토 대상이다. 공개 기능·라이선스가 회사 데이터 반출 승인이나 기업 운영 인증은 아니다.[S3]

## 동일 기능 계약에서의 판정 [INFERENCE]

| 대안 | 가져올 장점 | full 요구에 부족하거나 추가로 소유할 것 |
|---|---|---|
| claude-mem | 이미 있는 native capture/observer, 단계적 검색, 구체적인 local worker 운영 | local/hosted backend·검색 차이, 자동 capture coverage, approved rule/3 scopes/root-free mandatory delivery, company credential/egress, publish/derived purge/restore 불변식 |
| Serena | 읽기 쉬운 versioned Markdown·명시 reference와 root-free 본문 조회 | name catalog 비용, full 자동 추출/반성/host capture, 범위 권한·승인·철회·cloud canonical service; LSP/code index와 memory freshness를 혼동하지 않기 |

두 제품을 모르는 채 Hindsight를 승자로 정하지 않는다. 다만 이 둘로 더 좁은 수동/host-specific 기능을 선택해 기존 full pipeline 요구를 충족했다고 주장하지 않는다. 최종 reviewer는 같은 scope/출처/권위/삭제/host/운영 잣대로 이 반례도 비교한다.

## 사용자 제공 자료의 coverage 의미

9개 파일을 input inventory로 다루되 **AI가 만든 과거 보고서의 앱 적용 결론 자체를 현재 설계 요구로 승격하지 않는다**. full/timed transcript와 verified cue claims는 원문 근거이며 source-corrected 재분석·BAML/Jev·host/engine/OSS 조사로 현재 질문에 다시 적용한다. 원문, summary, research-index는 서로 다른 증거 수준이다. project-memory-pipeline의 특정 앱 적용 부분은 사용자 요청으로 의도적 제외다. AI 요약/비용/시연/후속 아이디어를 제품 acceptance로 쓰지 않는다.

## 직접 읽은 공식 출처

- [C0] https://github.com/thedotmack/claude-mem/commit/fa8ab09f06aa05f958c5225cf3756ce52a3ebb96
- [C1] https://docs.claude-mem.ai/configuration
- [C2] https://docs.claude-mem.ai/hosted-server
- [C3] 기존 제공 보고서가 직접 검토한 source locator: https://docs.claude-mem.ai/architecture/database ; https://docs.claude-mem.ai/usage/search-tools ; https://docs.claude-mem.ai/cloud-sync ; 우리 제품/양쪽 backend parity 실측 아님.
- [S0] https://github.com/oraios/serena/commit/1de556f71569f3acfc0743e526dd60aca40a545e
- [S1] https://github.com/oraios/serena/blob/1de556f71569f3acfc0743e526dd60aca40a545e/docs/02-usage/045_memories.md
- [S2] https://github.com/oraios/serena/blob/1de556f71569f3acfc0743e526dd60aca40a545e/docs/02-usage/070_security.md
- [S3] https://github.com/oraios/serena/blob/1de556f71569f3acfc0743e526dd60aca40a545e/LICENSE
