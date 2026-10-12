# 독립 OSS local/cloud memory 제품의 영향 범위

상태: 문서·고정 source로 작성한 검토 전 영향 분석. 새 native 모델 리뷰가 진행 중이며 해당 모델의 결론으로 표기하지 않는다. 실제 product 구현·설치·배포·계정 연결·offline/restore·benchmark는 수행하지 않았다.

## 핵심 판단

'회사판'과 '개인판'은 **서로 다른 엔진 fork가 아니라 동일 release의 두 deployment profile**로 구분하는 것이 기본이다. MCP와 일반 installer는 다른 축이다. 공통 core를 공개하고 service를 설치한 뒤 host가 MCP로 접근하며, 사람은 별도 관리 도구로 운영하는 것이 목적에 맞는다. 단, '같은 코드'가 '모든 host에서 자동 기록'이나 '같은 추론 품질/비용/보안/운영'을 증명하지 않는다.

## 영향 matrix

| 경계 | #334 현재 변화 | 독립 제품에서 추가될 변화 | 장점 | 비용/거절 조건 |
|---|---|---|---|---|
| Agent Flow core/runner/workflow/gates | 신규 memory DB/worker/MCP 없음 | 기본 권고는 core 변경 없음, opt-in external context만 | finite run·sealed reviewer 경계 유지 | author가 memory를 읽으면 context/토큰/판단은 변함. core 0줄≠runtime 영향0 |
| Agent Flow 배포자산 | skill 2 bullets, pointer bytes/docs 안내 변경 | service/model/data/collector를 기존 installer payload에 혼입하지 않음 | 기존 설치 digest/phase budget과 별도 lifecycle | '한 installer로 둘 다'는 ownership/reviewer 입력/업데이트 범위 확대 |
| 독립 OSS repo/release | 원 PR에는 새 engine 구현 없음 | core/service/schema/migration/worker/MCP/operator 도구·profile별 배포 안내 | source audit·같은 release 배포 가능 | 코드·Docker·model·NOTICE의 rights; 공개 wrapper만으로 full engine OSS 주장 금지 |
| 설치/host 설정 | `@AGENTS.md` author pointer 유지·reviewer 전달 과장 정정 | dedicated namespace, install diff/ownership, 명시적 host+scope 연결·collector 등록 | MCP 연결과 운영 책임 분리 | global AGENTS/MCP/hook 덮어쓰기 금지, user edit/managed policy 충돌 fail closed |
| 지속 lifecycle | Agent Flow core는 장기 daemon 소유하지 않음 | 별도 program이 PG/API/worker start/stop/recovery 소유 | session 밖 비동기 memory 처리 | 회사 service/container/DB 설치 금지면 해당 topology 불가; child stdio로 숨겨서 동일성 주장 금지 |
| 회사/외주 고객 | 사용자 host memory 참고, corpus 이동 안 함 | 고객별 DB/home/token/collection/backup/egress 경계 | 고객 데이터 local residency 통제 | 같은 OS UID/session이 고객을 바꾸는 것만으로 격리 안 됨. 고객 정책 실제 승인 필요 |
| 개인 self-host cloud | 없음 | 개인 corpus만, durable PG/worker/TLS/OAuth/auth onboarding | Mac 꺼져도 다른 host에서 서비스 이용 가능 | remote agent의 실제 native MCP/capture 지원 및 private read/write 조건, 비용/운영 소유 |
| 저장소/queue/원문 | 없음 | 동일 PG authority와 event/job intent transaction; 추출/조회 상태 분리 | idempotency·audit·정정/철회 일관성 | DB backup/migration/lease/fencing; 객체저장소·queue 추가는 새 atomicity gap |
| 추론 backend | Agent Flow가 추출모델 운영 안 함 | local approved inference / personal approved provider의 명시적 profile | 회사 no-fallback, 개인 가용성 선택 | 모델 revision/차원/tokenizer/extension drift·한국어/code 품질·비용; local compute 부족 시 full parity 불가 |
| 자동 capture/recall | native host ownership, 자체 memory 주입 없음 | 승인된 host adapter/source allowlist→ingest→다음 task recall | 읽기/쓰기 loop가 실제 task에 연결 | MCP alone은 full transcript/native memory 접근권이 아님. hosted hooks 제한이면 해당 adapter 미지원 |
| 관리/승인 | tracked team rule는 기존 PR/review/gates | agent data plane과 정책/export/purge/operator plane 구분 | memory가 현재 팀 규칙을 자동 덮어쓰지 않음 | agent shell과 같은 UID/credential의 CLI 승인 위조; UI 존재≠human presence |
| 정정/철회/backup | 새 runtime 없음 | source lineage, derived invalidation, cache/worker revision·최신 deletion head | 오래된 실패/선호/삭제 자료의 부활 억제 | uninstall/OAuth grant revoke/logical export/physical purge/restore 모두 별개, 실제 복구검증 전 보장 불가 |
| 호환성/지원 OS | #334는 macOS verified reviewer 계약 유지 | OSS service의 OS/arch/artifact/PG/SDK/protocol/host matrix는 별도 | daemon cloud Linux 지원과 Agent Flow reviewer Linux fail-closed를 혼동하지 않음 | 어떤 container가 뜬다≠그 OS에서 reviewer write sandbox verified. memory product 지원은 새 관측 필요 |
| 비용/품질 | PR byte budget은 actual model effect 아님 | write/embed/recall/reflect/repair/DB/backup/updater 전체 비용/품질 비교 | managed 벤더 숫자 대신 workload 근거로 선택 | 아직 hardware/corpus/traffic 실측 없음. 달러/latency/정확도 우위 약속 금지 |

## engine 재사용 vs 신규 구현 vs wrapper

- **기존 OSS engine 재사용/필요한 고정 fork:** Hindsight `a9eeed77f9bce99d8f97d39a30d3281747300824` MIT와 동일 API/worker·PG 중심 운영은 가장 직접적인 후보다. 현재 local MCP launcher는 HTTP API startup이며 별도의 Claude plugin stdio가 API를 호출한다. pg0 production 비추천, 기본 cloud LLM/noauth, customer bank ACL, stable worker ID, derived correction/delete와 backup의 차이를 확인해야 한다. wrappers로 고칠 수 없는 commit/fencing/철회 불변식이면 backend 패치 소유권과 upstream merge 비용이 생긴다. 문서의 local privacy 문구를 믿고 무검증 설치하는 것은 추천하지 않는다.
- **자체 PG 중심 core:** 좁은 domain과 승인/정정/철회를 직접 소유하기 쉽지만 capture·추출·quality·job lifecycle·auth·migration·export·purge/restore·패키지 지원까지 모두 새 책임이다. 'PG+MCP 조립이면 끝'이 아니며 full pipeline을 보장할 소비자-visible 검증이 필요하다. 합당한 이유 없이 기존엔진과 자체엔진을 처음부터 동시에 지원하지 않는다.
- **proprietary vendor API의 공개 MCP wrapper:** 가장 작은 client code/운영 표면이나 hosted engine/source/retention/provider 의존을 남긴다. strict local full engine/self-host OSS 요구를 만족한다고 부를 수 없다. Supermemory의 self-host binary 가능과 공개 MCP repo가 존재하는 사실도 full backend source 공개를 뜻하지 않는다. archived Mem0 wrapper를 새제품 engine으로 재배포하는 방향도 추천하지 않는다.
- **Graphiti/LangMem 등 다른 OSS:** temporal relation이 실제 workload에 필요하면 Graphiti를 고려할 수 있지만 experimental MCP/group partition≠ACL, 별도 graph 운영·삭제의 비용이 있다. LangMem은 extraction/reflect primitives이지 완성된 auth/durable MCP service가 아니다. 초기 출시부터 optional graph backend N개와 다양한 DB provider를 추상화할 이유는 아직 없다.

## 최소 공개제품 범위와 분리할 것

공개: core memory domain/service, supported schema/migrations/worker, host capture·MCP adapters, operator lifecycle, 공통 synthetic parity/보안 fixture·지원 contract, installable release/OCI/offline manifest·LICENSE/NOTICE/SBOM·deployment guide. 아직 이러한 제품을 구현·출시한 것은 아니다.

분리: source/release는 공통; 고객/회사·개인의 corpus/credential/home/session/backup/egress는 독립; install assets와 private data는 독립; agent-plane과 operator 권위는 구분; installer lifecycle과 domain DB migration/restore는 구분. public MCP registry/Plugins universal publication은 namespace/discovery 유통 채널이지 개인 memory endpoint·corpus를 공개하라는 요청이 아니다.

출처: [고정 PR](https://github.com/chonamdoo/agent-flow/compare/642d1792edf0b22bda2bb879ac65df145273dc19...a57c0c8a67df2814324e4e197dcd82faaff1c8b3), [freeze policy](https://github.com/chonamdoo/agent-flow/blob/642d1792edf0b22bda2bb879ac65df145273dc19/docs/IDENTITY-AND-FREEZE-POLICY.md), [MCP architecture](https://modelcontextprotocol.io/specification/2026-07-28/architecture), [Hindsight installation](https://hindsight.vectorize.io/developer/installation), [고정 tenant/auth source](https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-api-slim/hindsight_api/extensions/builtin/tenant.py), [고정 plugin stdio adapter](https://github.com/vectorize-io/hindsight/blob/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-integrations/claude-code/scripts/mcp_server.py), [Supermemory self-host source 공개범위](https://supermemory.ai/docs/self-hosting/overview), [Claude cloud](https://code.claude.com/docs/en/cloud-environments.md), [OpenAI MCP](https://learn.chatgpt.com/docs/extend/mcp), [Cloud Run runtime](https://docs.cloud.google.com/run/docs/container-contract).
