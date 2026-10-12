# Codex GPT-6.1-Sol xhigh 리뷰 반영 결정

입력 SHA256 `0735cfb4c2fd2f2251acab3373f862d0e5c2d99e0191526edd5fa1def22f51d3`. 실제 native CLI 리뷰의 R01–R07에 대한 부모 통합 판단이다. **설계 문서의 수정/채택 조건**이지 구현된 통제·통과 시험은 아니다.

| Native ID | 판단 | 제안 계약에 추가할 내용 | 영향/비용 |
|---|---|---|---|
| R01 P1 | 수용 | Agent의 기록/제안 credential에는 promotion/export/restore 승인 capability를 주지 않음. 인간 control plane의 승인 증거는 서버가 생성한 content digest+revision+scope+조건+행위(필요 시 수신자/목적)+expiry/nonce에 결합. 변경 시 승인 무효화. 같은 OAuth subject라고 agent 호출을 human act로 인정하지 않음 | 두 배포 auth/승격/import-export 공통; 자동화 감소, 명시적 인간 경로 필요 |
| R02 P1 | 수용 | worker publish와 correction/forget가 같은 canonical guard row lock/CAS에서 source revision+deletion generation+필요 권한 generation+lease fencing token을 검증/commit. 밖에서 확인만 하고 나중에 쓰는 check-then-write 금지. 외부 graph/engine projection은 canonical barrier 검증 뒤만 공개 | worker·삭제·정정·재색인, 충돌/재시도 비용; LLM 부작용 과금은 rollback 안 됨 |
| R03 P1 | 수용 | manifest로 event의 필수/선택 projections·source chunks를 정함. queryable은 활성 serving generation의 필수 projection 완료를 의미. 부분 성공·처리 공백은 coverage/processed watermark와 partial에 노출. 재색인 generation은 검증 후 serving pointer를 원자적 전환, 구신 embed 혼용 금지 | operation/status/recall/embedding 변경 계약 공통 |
| R04 P1 | 수용, 보장 한정 | stable source identity와 scope별 keyed exact-content digest를 삭제 metadata로 취급해 승인 없는 동일 원문 재수집을 탐지하는 방안. 새 UUID가 삭제를 우회하지 않게 함. key/retention/restore 책임 명시. identity 잃은 import는 자동 승격 안 함. 임의 paraphrase나 외부 context의 같은 의미 전면 제거는 보장하지 않음 | capture/import/ledger, 민감 fingerprint 최소화와 reingest 방어 사이 trade-off |
| R05 P1 | 수용 | 현재 retrieval block ACK와 restore 보호를 분리. restore 보호 단계는 복원 대상 밖 승인된 매체의 durable deletion record와 신뢰 가능한 monotonic head/watermark 확보 후. 최신 head 확인 실패면 조회 재개 금지. 회사 local-strict의 ledger도 사내 경계; 모든 신뢰 기준 동시 소실/rollback의 극한은 미해결로 명시 | delete ACK/복구 가용성/backup 운영; 암호 서명만으로 과거 ledger의 최신성을 증명 못함 |
| R06 P2 | 수용하되 자동 정책 채택 보류 | 200문자/60overlap, 후보20, final20skip/≤5rerank/6–19rerank 제안은 출처 제한된 baseline으로만 기록. final count로 비용/순위가 갑자기 바뀌는 정책을 product default로 승인하지 않음. 초기 비교 baseline 및 fixed retrieval profiles로 reranker 유무·candidate K·budget을 독립 ablation; 운영 정책은 corpus 결과로 결정 | 기존 source heuristic과 충돌하는 **설계 수정 제안**을 명시하며 숨겨 변경하지 않음. 이번 조사에서 구현/운영값 변경 없음 |
| R07 P2 | 수용 | 통제 가능한 OSS engine 비교와 내부 모델/embedding/budget이 비공개인 managed 제품 전체 비교를 분리. managed는 같은 input/후속 task/외부 reader/공개 limits만 맞추고 내부조건 미확인. 작은 fixture+안전 contract 먼저, 선택차이 불명확할 때 평가 확대 | 평가 인과 주장 축소, 사용자 평가 부담 감소 |

추천 차이: Codex는 단일 PostgreSQL 권위 저장소의 최소 domain service를 우선한다. Hindsight와 benchmark 비교안은 병존할 수 있지만 **PG canonical + Hindsight를 두 권위 저장소로 병행 운영하면 안 됨**. 준비된 engine을 재사용하려면 native mutation 우회 차단과 실제 승인/CAS/delete/receipt 의미를 만족하는지 먼저 검사한다. 이 판단은 제품을 실행해서 확인한 결과가 아니다.
