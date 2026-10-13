# 동일 파이프라인·서로 다른 데이터 경계: 영향 및 대안

조사/설계 제안. 제품 구현·부하·보안·메모리 품질 실측 아님. 사용자의 추가 요구(외주 업무 local, 집/개인 cloud)를 포함한다.

## 무엇이 가능하고 무엇을 나눠야 하는가

| 요구 | 판정 | 이유와 분리할 부분 |
|---|---|---|
| local/cloud 동일 기억 API·event schema·상태전이·정정·철회 정책 | 가능하도록 설계할 수 있음 | 같은 engine, migration, policy manifest와 conformance suite를 두 배포에 사용 |
| 같은 source event가 같은 memory kind/provenance/승인 경계를 지킴 | 공통 불변식으로 검증해야 함 | 원문/추출/추론/사용자 승인을 분리. 모델 출력이 허위인 경우 quarantine/verification 처리 |
| local/cloud 물리 인프라·인증·queue·backup까지 완전히 동일 | 추천하지 않음 | local filesystem/process identity와 cloud GCS/OAuth/IAM의 실제 실패·보존 특성이 다름. adapter와 runbook을 분리 |
| 고객 회사자료와 개인 cloud를 자동 양방향 동기화 | 기본 금지 | 계약/정보분류/수신자 승인이 없는 외부 이전. project 태그·같은 로그인·본인 노트북이 반출 권한이 아님 |
| 외부 전송 금지 회사의 local corpus를 외부 cloud agent가 그대로 사용 | 동시에 보장 불가 | 기억 내용이 외부 agent/model에 전달되는 것 자체가 경계 밖 전송. 회사 승인된 사내 cloud/VPC나 승인된 최소 export가 필요 |
| local과 cloud에서 똑같은 문자열 답변/latency/비용/HA | 보장 불가 | LLM nondeterminism, 모델/quantization/hardware/네트워크/용량이 다름. 동일 계약과 품질 기준으로 평가 |
| 집 PC가 꺼져 있어도 개인 cloud agent가 기억 사용 | cloud canonical store로 가능하도록 설계 | 개인 기기는 필수 gateway가 아님. 개인 remote MCP 직접 연결, local offline queue만 선택 |
| MCP 설치 한 번으로 모든 host transcript 자동 수집 | MCP만으로 불가 | host별 승인된 capture/export adapter와 실제 tool 호출/주입 검증 별도 |

## 대안과 영향 범위

| 안 | 재사용/새로 소유할 범위 | 장점 | 단점·local/cloud parity 영향 | 제안 |
|---|---|---|---|---|
| 독립 PostgreSQL+pgvector domain service | 공통 memory contract/SQL schema, ingest ledger/outbox, MCP/auth, provenance/correction/delete; local/cloud artifact·wakeup·inference adapters | event+ACL+outbox를 같은 DB transaction에 결합, 두 배포 SQL 의미 통일, graph 없이 hybrid baseline | extraction/reflect/lineage/권한을 직접 운영. 작은 서비스라도 품질·삭제·로그 정책 구현 필요 | 정합성·외주 데이터 경계 검증의 기준안. 새로운 범용 memory framework/내부 추론 엔진을 무조건 직접 작성하라는 뜻 아님 |
| Hindsight self-host local/cloud | 같은 Hindsight version/API/Postgres, 배포/config; app auth+bank ACL, capture adapter, upstream semantics에 맞춘 correction/forget/outbox wrapper | retain/recall/reflect·time/graph·mental model 엔진 재사용. local/external PostgreSQL 공식 지원 | 기본 noauth와 single shared key는 bank ACL 아님. 기본 local LLM도 OpenAI. pg0 production 비추천. tool count/auto refresh 문서 불일치와 upstream 업데이트 검토 | ready-made engine의 우선 비교 후보. 동일 fixtures에서 최소 기능·노출·정정/삭제 계약을 통과하면 custom engine보다 재사용 우선 |
| Neo4j graph 중심 또는 PG ledger의 파생 graph | Cypher schema/entity resolution/temporal edge 관리, graph rebuild, Aura 및 local Neo4j 버전·edition 운영 | multi-hop/entity/time 관계가 중요한 업무에 적합할 수 있음 | graph는 진실/권위/철회를 해결하지 않음. Aura와 local edition/tier의 auth/backup 차이. SQL ledger를 더하면 DB 두 개의 운영/일관성 부담 | 실제 관계질의 개선과 전체 비용 이득이 관측될 때. 화면의 Neo4j 선택만으로 필수화하지 않음 |
| Managed memory (Hindsight Cloud/Mem0/Supermemory 등) | vendor onboarding/remote auth·API, 최소 capture/export/auth wrapper, contract+privacy 검토 | 개인 cloud의 빠른 연결, infra 운영 감소 | strict local에 같은 managed engine 배포 불가하면 제품 이원화. 데이터 처리/plan별 training/backup purge/export/vendor 변경 부담 | 개인 데이터에 한해 선택 가능. local/cloud 동일 engine 요구가 최우선이면 self-host 가능 여부 우선 |

Agent Flow 영향: 조사 기준 main `642d1792edf0b22bda2bb879ac65df145273dc19`. 기존 #316의 core memory freeze·reviewer 격리와 독립 memory service는 별개다. **초기 제안의 core code 변경은 0**: 설치기·provider launcher·reviewer gate·author envelope에는 새 store/자동 주입/새 설정을 넣지 않는다. host별 opt-in collector와 memory MCP 설치/인증은 독립 제품의 변경 범위다. 향후 collector를 Agent Flow core에 넣으려면 별도 명시적 요구와 기존 freeze 조건을 검토해야 하며 이 조사에서 추진하지 않는다.

## 운영 공통화의 구체적 최소 범위

- 같은 domain release/schema version과 SQL migration. local/managed PG 양쪽이 지원하는 vector extension·버전을 택하고 실제 지원표를 확인한다. upstream 최신을 managed latest로 가정하지 않는다.
- cloud provider SDK가 도메인 claim/state/retrieval policy를 결정하지 않게 한다. 필요한 차이만 artifact durability/auth identity/job wakeup/inference configuration에 둔다. 모든 DB·queue에 만능 플러그인을 만들지 않는다.
- `work-local-strict`와 `personal-cloud`는 별도 설치/endpoint·DB·키·logs·outbox·backup·cache. 고객별 배포도 독립 경계. 계정이나 project string만으로 나누지 않는다.
- 잘못된 프로필/secret/endpoint는 fail closed. 업무 local 오류에서 개인 cloud fallback은 금지. memory unavailable은 coding 작업을 계속할 수 있지만 내용을 재구성해 성공이라고 거짓말하지 않는다.
- 동일 conformance suite를 local/cloud 양쪽에서 실행: acceptance/queryability, duplicate/out-of-order, correction CAS, revoked worker, forget/reingest/restore, ACL/get/export/list, cache revision.
- 각 프로필의 운영 smoke를 따로 실행: local offline 기동과 egress denial, cloud 두 host roundtrip+auth revoke, restore recovery. conformance 통과가 HA/RPO/RTO나 prompt-injection immunity 증거는 아니다.
- 모델 capability/tool calling, embedding dimension/digest, tokenizer/normalizer, prompts/policy, schema/projection을 manifest로 고정. 변경 시 revision/reindex/eval. local model 실패로 extraction/reflect를 silently 생략하거나 cloud 대체하지 않는다.
- client-side encrypted backup과 live cloud zero-knowledge는 다른 신뢰 모델. 서버 추출/embedding에는 plaintext가 필요하며 벡터도 기밀 파생물로 처리한다.

## 소비자 행동 기준의 선택 평가

공통 동작을 만들지 말지의 허들은 실측 전 임의 %가 아니라 수용 불가 실패 조건부터다: 타 고객/개인 corpus 노출, 승인 위조, 철회 기억 복원/재주입, 실패 응답을 성공으로 포장, 회사 local의 외부 자동 fallback이 있으면 채택 불가. 이후 실제 한국어 업무 fixtures에서 missing fact/false preference/조건·부정 손실, source-grounded answer, cross-session 성공, 주입 token/latency, 전체 비용과 운영 시간을 비교한다. 제품 벤치마크 점수를 이 환경의 결과로 대신하지 않는다.
