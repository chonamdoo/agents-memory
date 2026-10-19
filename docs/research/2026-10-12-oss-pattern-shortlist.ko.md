# 제품 통째 채택보다 MCP 메모리 판단·근거·수명주기 패턴을 재사용한다

## 결론
우리 공통 core를 다른 memory 제품으로 바꾸지 않는다. 회사 로컬 ML 설치 불가, 승인 Claude/Codex caller, 개인 Jev, 원문 근거, 후보≠승인, 현재 scope, 철회, bounded 호출을 같은 잣대로 비교했다. 이름이 같은 3분류를 찾기보다 **누가 판단하고, 언제 저장되고, 무엇을 수정/제외하며, 어떤 원문으로 검증하는가**를 비교한다.

이번 조사는 고정 GitHub 소스의 정적 읽기다. 후보 OSS를 설치/빌드/운영하지 않았고 성능·회사 권한·MCP protocol revision 호환성을 실증하지 않았다. 기존 개인 local-model 구현의 AF 승인으로 사용할 수 없다.

## 넓게 찾은 재사용 후보

| 후보·고정 commit | 실제 참고 패턴 | 우리에게 주는 힌트 | 그대로 채택하지 않는 이유 |
|---|---|---|---|
| [Engram](https://github.com/Gentleman-Programming/engram/tree/5c4171845958f046968c14d7d57a325eb4a83b7e), MIT | MCP caller의 save/judge; deterministic conflict 후보 관련성 | 기억 선별은 이미 세션을 읽는 agent가 맡고 서버는 구조화된 저장·후속 판정을 집행할 수 있음 | caller 판정은 사람의 규칙 승인과 다름; 저장/판정 순서와 근거 의무는 별도 확인 |
| [codex-agent-mem](https://github.com/MarceloCaporale/codex-agent-mem/tree/d594c8a86207fb9a8a5b48a6aab323349680707a), Apache-2.0 | micro/normal/full 예산형 context pack, policy exclusion | 모든 장기 기억 대신 목적별 제한된 전달 묶음 | pack에 들어감≠현재 source/scope 검증·사용자 승인 |
| [memharness](https://github.com/las7/memharness/tree/faed4b346e445d2344ed02e8211759999acd946d), Apache-2.0 | source pin current/stale/unresolved; revision/supersession | 최신 commit과 같지 않아도 해당 경로가 바뀌지 않았으면 current; unknown/diverged는 unresolved | hybrid vector 경로의 설치·권한·한국어 품질은 미검증; caller source pin이 권한 증거는 아님 |
| [mnema](https://github.com/Ray0907/mnema/tree/eed19586156ae9664451cb94859f8f3f16b3ac4a), MIT | Markdown canonical + 재생성 인덱스; 충돌 relation, preview→commit hash token | 중복/모순을 즉시 overwrite하지 않고 관계와 보류 상태를 보존 | preview token은 인간 승인 아님; ConflictJudge/TransformersEmbedder 그대로 회사에 반입 불가 |
| [mcp-memory-keeper](https://github.com/mkreyman/mcp-memory-keeper/tree/4f33fb6e79fb787e555d06feb91c2c5a3de26df3), MIT | 명시적 retention age/count/size·dry-run; 문자 trigram hash vector | 유지 비용·삭제 영향의 사전 확인 | retention 삭제와 우리 철회/파생 closure/backup 삭제는 다름. **해시 벡터는 ML 추론이 아니다**; semantic embedding 품질을 약속하지 않음 |
| [memory-governance](https://github.com/mzyag/memory-governance/tree/db3a6d6c1a7729b8ed90a712ab78fbc501c645ea), MIT | role별 read/write, 카테고리 정책, PII 마스킹·감사 로그 | 콘텐츠 유형과 접근/보관 정책을 분리 | 정규식은 전수 비밀 제거를 보장하지 않음; append-only JSONL은 변조 방지/서명 증거가 아님 |
| [LangMem](https://github.com/langchain-ai/langmem/tree/48e3c11f5bb527282c7d5339c6a87a0b35abccfc), MIT | schema 기반 추출·기존 기억 비교·insert/update, semantic/procedural/episodic | 새 기록 판단과 기존 기억 mutation 판단은 다른 단계 | 완성된 MCP 제품 아님; 자동 store mutation과 '필요시 quote'는 승인/필수 원문span 계약이 아님 |
| [MemOS](https://github.com/MemTensor/MemOS/tree/a7367d07e55db61099f7b4e2c1108bc5831a24f3), Apache-2.0 | 수명주기·feedback/dream 설계 | 노후화/무효화 신호와 기억 삭제를 구별 | 읽은 dream maintenance는 stub, feedback 경로는 LLM·embedding에 의존; 문서 설계를 실행된 기능으로 채택하지 않음 |
| [OB1](https://github.com/NateBJones-Projects/OB1/tree/238df6cefd307745d1fe49d10b96797903bf25ac) | provenance chain·bounded graph traversal 제안 | 원문→후보→파생물 영향 범위를 제한된 깊이로 탐색 | proposal이며 GitHub license=NOASSERTION. 코드 복사 후보 아님 |

라이선스 값은 당시 GitHub repository API 결과다. 파일별 NOTICE·의존성·최종 재배포 권리를 검토 완료했다는 뜻이 아니다.

## 우선 차용할 것
1. **Engram의 caller-owned 판단 흐름:** 이미 현재 세션을 읽는 agent가 좁은 메모리 판단을 할 수 있다. MCP 서버가 모든 원문을 다시 고비용 모델에 보낼 필요가 있는지부터 구분한다. 판단 근거·권한·원문 revision은 서비스에서 검증해야 한다.
2. **mnema의 충돌 보류:** 해결되지 않은 모순을 지우거나 하나로 요약하지 않는다. preview 시 본 입력과 commit 시 본 입력이 같다는 점은 확인하되, operator 승인 권위는 우리 core에 둔다.
3. **codex-agent-mem의 제한된 전달 묶음:** 분류별 전체 dump 대신 task에 필요한 작은 요약/포인터만 전달한다. hard char budget은 token 정확 계측의 대체가 아니며, 필수 규칙을 무언으로 자르면 안 된다.
4. **memharness의 current/stale/unresolved:** 날짜가 오래됐다는 이유만으로 false라고 하지 않고, 근거 상태가 확인되지 않았다는 이유로 current라고도 하지 않는다.
5. **memory-governance의 policy 분리:** Profile/Log/Notes/파일 이름이 곧 접근권한·보관기한·승인·자동주입 정책이 되지 않게 한다.

## 반면교사
- 제3자 MCP 서버가 존재한다는 사실은 우리 회사 native 계정의 자동화 사용 허가가 아니다.
- 자동 기억 업데이트·LLM confidence·resolve token은 사람의 승인과 다르다.
- 로컬 DB를 쓴다는 사실은 로컬 ML 불필요/no-egress/host가 모든 세션을 관측한다는 증거가 아니다.
- 재생성 가능한 FTS/index와 canonical source/권위 ledger를 혼합하면 수정/철회 범위가 흐려진다.
- 철회는 현재 사용을 막는 상태 전이, purge는 보관된 내용 제거다. 단순 tombstone이나 source 삭제만으로 모든 파생물·backup의 제거를 보장하지 않는다.

## 읽은 핵심 구현 근거
- [Engram conflict candidate relevance](https://github.com/Gentleman-Programming/engram/blob/5c4171845958f046968c14d7d57a325eb4a83b7e/internal/store/candidate_relevance.go)
- [Engram MCP caller interface](https://github.com/Gentleman-Programming/engram/blob/5c4171845958f046968c14d7d57a325eb4a83b7e/internal/mcp/mcp.go)
- [Context pack budget](https://github.com/MarceloCaporale/codex-agent-mem/blob/d594c8a86207fb9a8a5b48a6aab323349680707a/src/codex_agent_mem/context_pack.py)
- [Source staleness](https://github.com/las7/memharness/blob/faed4b346e445d2344ed02e8211759999acd946d/packages/core/src/staleness.ts)
- [mnema write/resolve boundary](https://github.com/Ray0907/mnema/blob/eed19586156ae9664451cb94859f8f3f16b3ac4a/src/mcp-server.ts)
- [Keeper deterministic hash vectors](https://github.com/mkreyman/mcp-memory-keeper/blob/4f33fb6e79fb787e555d06feb91c2c5a3de26df3/src/utils/vector-store.ts)
- [LangMem extraction contracts](https://github.com/langchain-ai/langmem/blob/48e3c11f5bb527282c7d5339c6a87a0b35abccfc/src/langmem/knowledge/extraction.py)

후보별 실제 판단/저장/오류 흐름과 Profile/Log/Notes/파일·스킬 적대적 리뷰는 별도 조사 결과로 기록한다. 이 목록만으로 분류기의 정확도나 비용 절감률을 확정하지 않는다.
