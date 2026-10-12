# 로컬·클라우드 MCP 메모리 설계 계약 — 제안, 구현 아님

## 결정

새 cross-device/cross-agent 요구는 사용자 소유의 독립 `agent-memory-mcp` 서비스로 다룬다. Agent Flow 설치기·runner·reviewer·hooks를 변경하지 않는다. 기본 비교 기준은 **인증된 HTTP MCP + 단일 PostgreSQL canonical store/pgvector + redacted 원문 archive + 비동기 worker**. Hindsight self-host/managed memory를 같은 필수 계약으로 비교하고, Neo4j는 실제 multi-hop·temporal 관계 질의 이득을 확인할 때 추가하거나 저장 엔진을 바꾼다. graph DB가 기억의 진실·인간 권위·현재 코드 적합성을 해결한다는 전제는 두지 않는다.

이는 사용자에게 제안할 선택이다. 클라우드 배포, 실제 제품 사용, 자동 수집, 모델 호출에 의한 메모리 추출은 이번 조사에서 구현하지 않는다.

## 추가 요구: 외주 업무는 로컬, 개인 환경은 클라우드

**하나의 코드베이스·도메인 파이프라인·API·스키마를 두 배포에 사용할 수 있다. 두 배포의 데이터·자격증명·추론 경계까지 하나로 합치는 것은 별개이며 기본 금지한다.** 동일하게 보장할 것은 event identity, scope, provenance, 승격/철회 상태, accepted/queryable 의미, 정정 경쟁, 삭제/복원 계약이다. 같은 latency·HA·비용·모델 출력까지 동일하게 보장하지 않는다.

| 항목 | 외주 업무 로컬 배포 | 집/개인 클라우드 배포 | 공통/차이 |
|---|---|---|---|
| 도메인 코드/스키마 | 같은 service/worker와 migration | 같은 service/worker와 migration | 동일 release/schema; OS/arch별 빌드는 다를 수 있음 |
| canonical DB | 로컬 PostgreSQL+같은 vector extension | 관리형/자체 PostgreSQL+같은 extension | SQLite와 Neo4j로 양분하지 않아 두 DB 의미체계 운영을 피함 |
| transport/auth | localhost HTTP 또는 stdio shim, 로컬 trusted identity와 client token | remote HTTPS MCP, OAuth/PKCE/issuer+audience | public surface만 다름; localhost도 모든 same-uid 악성 프로세스로부터 자동 격리되는 것은 아님 |
| artifact store | 로컬 filesystem의 durable/atomic write와 restricted ACL | GCS conditional write+IAM+finite retention | artifact interface만 공통; fsync/rename vs generation/soft delete 차이를 명시 |
| 작업 queue | DB outbox와 lease worker/local supervisor | 같은 DB outbox와 lease worker; Tasks는 wakeup adapter | queue가 source of truth 아님; retry/CAS/deletion epoch는 동일 |
| inference | local-strict면 추출·embedding·reranker·reflect 모두 로컬 | 같은 self-host 모델 또는 허용된 외부 API | 모델/quantization/embed 변경 시 품질 동일성은 불가, capability와 manifest/eval 필요 |
| backup/restore | 고객이 승인한 로컬/사내 매체와 독립 deletion ledger | 개인 cloud backup와 독립 deletion ledger | 복원 전 철회 재적용 계약은 같고 RPO/RTO는 다름 |
| corpus/secret/cache | 고객별 데이터 디렉터리·키·DB·모델입력/log 분리 | 개인 corpus·키·DB·log 분리 | 외주→개인 자동 sync/export/import 없음 |

최소 환경 프로필은 `work-local-strict`, 계약이 허용할 때만 `work-local-approved-inference`, `personal-cloud`다. 이는 구현된 설정 이름이 아니라 제안이다. 잘못된 profile/endpoint/key가 있으면 fallback 또는 default bank를 선택하지 않고 시작을 거절한다. client MCP 설정에서도 업무 환경은 개인 endpoint를 발견/호출하지 못하도록 분리하고, 업무 서비스/worker의 outbound egress도 별도로 제한해야 한다. 단순 project 태그는 고객 간 보안 경계가 아니다.

- 회사가 **외부 전송 금지**라면 local DB+Claude/OpenAI extraction/Vertex embedding 조합은 local-strict가 아니다. LLM·embeddings·reranker·reflect·telemetry·crash reporting·backup까지 local/사내 경계를 검증한다. 단순 문자열 요약·벡터·error logs도 원문 파생물이라 개인정보/고객 기밀 전송일 수 있다.
- 메모리 stack을 로컬로 둬도 **호스트 Claude Code/Codex 자체가 클라우드 모델에 보내는 prompt/source는 별도 egress**다. 회사의 허용 provider 계약이 있거나 offline host 모델을 사용해야 전체 시스템 no-egress를 주장할 수 있다.
- strict local runtime은 인터넷 없는 상태에서도 기동/retain/recall/정정/철회/복원이 가능해야 한다. 이미지·패키지·모델은 승인된 staging에서 미리 가져와 version/hash를 고정하고 startup 자동 download/update를 금지한다. local model 오류에서 cloud fallback 금지.
- **cloud agent가 외주 고객의 local memory 내용까지 읽으면서 그 내용이 사내 경계를 벗어나지 않는다는 약속은 동시에 만족할 수 없다.** 고객이 승인한 사내 cloud/VPC/전송 경계가 없다면 그 data plane은 분리해야 한다. 집의 개인 memory만 cloud에서 공유하는 것은 이 제한과 충돌하지 않는다.
- 선택적 cross-boundary 이전이 필요하면 sync 버튼이 아니라 별도 승인된 export/import다. release authority, 목적/수신자, 최소 redaction, provenance, 재분류, 내용 digest, target scope, 감사 근거가 있어야 하며 default off다. 자동 양방향 sync는 추천하지 않는다.
- Hindsight는 공식 local MCP와 hosted API가 같은 기능 모델을 쓰고 embedded/external PostgreSQL을 지원한다. 그러나 embedded pg0는 공식적으로 dev용이고 production에 비추천. 외주 운영은 local external PostgreSQL을 기본 비교안으로 한다. local quickstart의 기본 LLM은 OpenAI라서 '로컬 실행'만으로 no-egress를 결론내리지 않는다. Ollama cloud 기능도 `OLLAMA_NO_CLOUD=1`과 egress 통제로 별도 차단할 수 있으나 이 설정 하나가 전체 stack의 offline 증거는 아니다.

근거: [Hindsight local MCP](https://hindsight.vectorize.io/sdks/integrations/local-mcp), [installation](https://hindsight.vectorize.io/developer/installation), [Ollama integration](https://hindsight.vectorize.io/blog/2026/03/10/run-hindsight-with-ollama), [Ollama FAQ](https://docs.ollama.com/faq). 공급자 문서와 우리의 보안/성능 실측은 구분한다.

**동일성 검증:** 동일 seed/event replay에서 status/version/scope/철회 결과를 local/cloud 양쪽으로 비교한다. deterministic oracle 계약은 일치해야 한다. 추출/reflect의 의미·한국어 정확도는 local/cloud별 같은 time-split fixture와 false-promotion 기준으로 평가한다. 모델/embedding/차원/normalizer/prompt/정책 manifest가 달라지면 '같은 memory revision' 비교로 숨기지 않고 별도 revision/reindex한다. Apple Silicon native MLX/Metal과 Linux CUDA/CPU의 binary·quantization까지 동일할 수 없으므로 문장 출력의 byte identity나 동일 latency를 보장하지 않는다.

## 실제로 제공해야 할 사용자 동작

1. 기기A의 Claude Code가 승인된 프로젝트 기억을 기록한다.
2. 기기B 또는 cloud의 Codex가 같은 account/project에 로그인해 출처·버전·조건이 붙은 기억을 회상한다.
3. 사용자가 정정·철회하면 이후 조회에서 이전 버전은 제외된다. 파생 요약/임베딩/캐시/restore에도 같은 규칙을 적용한다.
4. 지원되는 클라이언트는 직접 HTTP MCP로 연결하며, stdio-only host만 local shim을 사용한다. shim은 cloud canonical DB가 아니다.
5. 자동 대화 수집은 MCP와 별개인 명시적 opt-in host adapter다. 자동화가 없어도 explicit memory tool의 기록/조회/정정/철회 경로는 완결돼야 한다.

## 저장·권한 계약

- 서버는 인증된 principal에서 tenant/actor/허용 project/role을 계산한다. model이 전달한 user_id, human origin, approved=true, bank path, tag를 권한 근거로 쓰지 않는다. 단일 사용자여도 등록한 각 기기의 capability를 구분한다.
- `user / project / task-branch` scope를 분리한다. project URL과 branch 이름은 identity 또는 ACL이 아니다. repository alias는 명시적으로 등록하며 미병합 branch fact는 target checkout을 재검증하기 전 project-wide로 승격하지 않는다.
- memory version은 source event/span/digest, origin, semantic kind, condition/exception, approval, verified time, valid interval, derives-from/supersedes/retracts 관계를 갖는다. access time은 검증 시간이 아니다.
- agent가 만든 요약은 AI extraction이다. human이 approve해도 인간의 원문으로 소급하지 않는다. human 원문을 확인할 수 없으면 origin=unknown/agent로 남긴다.
- factual 참고 기억과 behavioral policy를 분리한다. service admin 승인과 managed instruction 변경 승인도 다르다. AGENTS.md/CLAUDE.md/installed skill의 자동 수정은 하지 않는다.
- review subprocess에는 이 store의 개인 메모리를 기본 제공하지 않는다. 필요한 프로젝트 원문 규칙은 기존 검토 입력 경로로 다루며, 외부 store의 결과가 gate 권한을 갖지 않는다.

## 파이프라인·장애 계약

- bounded redacted event를 PostgreSQL transaction으로 event ledger+operation+outbox에 저장한 뒤 `accepted`를 반환한다. object archive 및 Task enqueue는 dispatcher가 outbox에서 수행한다. GCS와 DB와 queue의 원자성을 주장하지 않는다. 큰 raw object를 먼저 올릴 경우 별도 staged object receipt/DB commit/orphan reconciliation 계약이 필요하다.
- Cloud Tasks duplicate/out-of-order delivery를 전제로 worker는 `(tenant, event_uuid, projection_version)`의 persistent unique key와 compare-and-set로 동일 projection의 중복/과거 version overwrite를 막는다. task-name dedup의 제한 시간만으로 영구 exactly-once를 주장하지 않는다.
- writes: `accepted / queryable / failed / quarantined`. recall: `success / empty / partial / unavailable`. accepted≠queryable, unavailable≠empty. 처리 상태는 operation ID로 확인할 수 있다.
- 정정은 expected version precondition을 받는다. concurrent correction은 conflict이며 조용한 last-write-wins로 인간 결정을 덮지 않는다. worker commit 전에 revocation/deletion epoch를 재확인한다.
- fail-open은 **coding task가 계속 진행**할 수 있다는 뜻이지 오래되거나 격리되지 않은 기억을 제공한다는 뜻이 아니다. memory fetch 자체는 validation 실패 시 생략/명시적 unavailable로 닫힌다.
- local encrypted outbox는 연결 단절/호스트 종료의 최소 전송 spool이다. max size/보관기한/계정 namespace/ack 삭제가 필요하며 로컬 장기 기억과 구분한다. durable local enqueue를 검증하지 않았다면 crash delivery를 보장하지 않는다.

## 회상·반성 계약

- principal/project/state/validity와 code/environment 조건으로 먼저 범위를 제한하고, lexical+vector 후보를 RRF로 합친다. 모델/source identifier는 keyword query에서 원형을 보존한다. 한국어는 whitespace FTS만 신뢰하지 않고 morphology 또는 ngram 확장과 한국어 fixture를 비교한다.
- RAG skill의 prose 기본값 200 chars/60 chars overlap, first-stage Top20, final≥20 reranker 생략은 출처·적용조건이 제한된 규칙이다. 이 설계는 atomized claim에는 chunk overlap을 쓰지 않고 source event의 문장/메시지 span을 보존한다. 긴 prose source의 비교 baseline은 200/60; code/table은 구조 단위다. 아직 corpus 미수집이므로 chunk count는 미측정.
- proposed first-stage lexical20+vector20 → RRF unique candidates≤40 → token-budgeted final≤20, reranker는 skill 기본에 맞춰 final20이면 생략, final≤5이면 사용, 6–19는 사용 제안으로 표시한다. retrieve-wide→rerank-few도 ablation 후보이며 수치가 최적이라고 주장하지 않는다. aggregate 질문은 pagination/structured SQL, Top-k로 '전부'를 증명하지 않는다.
- memory response는 사용한 canonical ID/version/digest/source locator/validity/condition과 실제 반환된 bytes의 token count를 갖는다. 사실 본문만의 budget과 metadata 전체 budget을 구분한다. 실제 host/provider에 주입됐는지 볼 수 없으면 unknown이다.
- `reflect`는 필요할 때만 memories를 합성하는 추론 경로다. 결과는 새로운 사실/승인/정책이 아니다. 영속 mental model은 명시적으로 생성하고 source lineage/version을 갖는 파생물이며 자동 refresh가 있더라도 active policy로 자동 승격하지 않는다.
- reasoning scratchpad/모델의 숨겨진 chain-of-thought를 수집하려 하지 않는다. 관측 가능한 messages, tool outcome, 선택한 rationale과 원문 근거만 허용한다.

## 철회·삭제·백업 계약

- `retract`: 현재 회상·재추출에서 제외하되 원문/기록 보관 여부는 별도다. `purge`: raw source/derived facts/embeddings/mental models/cache/export/backup 보관정책까지 처리하는 삭제 작업이다. 둘을 같은 forget 성공 응답으로 뭉개지 않는다.
- 권한 있는 삭제 요청을 canonical ledger에 먼저 기록하고 retrieval은 최종 canonical status를 검증한다. source가 철회된 derived summary는 exclude/rebuild한다. 이미 실행중인 외부 LLM context에서 지울 수 있다는 보장은 하지 않는다.
- tombstone에는 비밀 원문을 남기지 않고 scope-bound 최소 ID/삭제 generation을 유지한다. restore는 최신 deletion ledger를 적용하기 전 서비스 공개 금지. 오래된 source 재수집이 새 human approval 없이 금지 기억을 부활시키지 않아야 한다.
- 원문 archive는 application-level append-only/conditional-create 및 유한 retention을 선택한다. default Bucket Lock/WORM은 purge와 충돌하므로 사용하지 않는다. 규제상 WORM이 필요한 원문은 별도 데이터 범주/보관 법적 근거와 삭제 제한을 표시한다.
- cloud encryption at rest와 고객만 복호화하는 zero-knowledge는 다르다. worker가 추출·embedding·reflect하면 그 처리 주체가 평문을 볼 수 있다. backup client-side encryption은 backup 보호일 뿐 live inference의 provider-blindness를 뜻하지 않는다.

## 채택 평가

독립 프로젝트이므로 기존 #316의 호스트 메모리 off/on 실험을 그대로 재사용하지 않는다. 새로운 **직접 cloud memory 기능의 채택 결정**에 쓰는 비교를 설계한다: 동일한 time-split corpus/task/model/embedding/token budget에서 no-memory, 기본 hybrid RAG, Hindsight, managed memory. source capture·extraction·search·reflect·주입·재검증·human review·운영의 총비용을 포함한다.

필수 실패 시나리오: Claude→Codex/다른기기 round trip; fake human approval; account/project/branch crossing; Korean negation/temporary exception; archive-success enqueue-fail; duplicate/out-of-order tasks; embedding 실패; correct concurrent/revoked worker; reingest/restore resurrection; cache old version; MCP 2025/2026 호환; provider/model failure; memory poisoning 및 wrong preference inference.

이 문서는 제안 계약이며 이 시나리오가 통과했다는 결과가 아니다. 실제 논문·제품 수치와 우리의 검증은 별도다.
