# 새 영상 native Codex 6.1 Sol xhigh — 근거별 판정

입력: `video-review-input.ko.md`, 205,168 bytes, SHA256 `c046de5447908e18d0762a533058d49fe8df4699bff90ac3bdc78a9fb0b5db3b`.
원문: `video-review-codex-6.1-sol-xhigh.ko.md`, native stdout를 변경하지 않았다. 모델이 VO1…VO8 ID를 선택했으므로 **Sol VOx**로 구별하고 다른 reviewer의 ID로 재번호화하지 않는다.

이는 구현되지 않은 제품의 위험/수용 조건이며 현 저장소 또는 AgentFlow PR에서 공격에 성공한 취약점 목록이 아니다. 많은 경계는 이미 제안 contract에 명시됐다. 새 리뷰는 그 강제 여부가 제품에서 입증되지 않았다는 점을 공격한다. 아래 runtime 관측은 모두 제품 채택 전에 필요하며 이번에 수행하지 않았다.

| Native ID/severity | 판정 | 설계에 반영할 내용과 범위 |
|---|---|---|
| Sol VO1/P0 | 수용 | 실행 허가·capture consent·정정·candidate 수락·rule 승격을 별개로 기록. authenticated operator 권위는 특정 revision/exact diff에 결합. 같은 UID가 credential/DB를 모두 읽는 환경의 강한 인간 승인 격리는 미지원으로 표시. 기존 source의 enable 버튼을 그 격리 증명으로 사용하지 않음 |
| Sol VO2/P0 | 수용 | local storage/승인 SaaS/strict no-egress profile 분리. 수집·모든 inference·trace/query·backup·recall을 받는 host까지 반출 경계. 회사 고객/개인 data/auth/host session/backup을 분리하고 silent cloud fallback 금지. 회사가 승인 SaaS를 허용하는 경우까지 일괄 금지하지 않음 |
| Sol VO3/P1 | 수용 | MCP/Query/installer와 capture·delivery completeness 분리. actual host/version과 cold start/resume/interrupt/error/child handback 확인 필요. Claude SessionStart의 HTTP 요청은 command handler 내부 호출과 type:http handler를 구분. 최신 docs를 설치된 모든 host 실행 증명으로 쓰지 않음 |
| Sol VO4/P1 | 수용 | evidence ID와 독립 investigation episode ID 분리. parent/child/summary/resume/retry는 같은 episode의 evidence일 수 있음. 조건·부정·고객/branch/revision·source spans·원문 누락을 보존. 영상 trace-derived code map을 특정 앱 static graph 재사용이나 전체 코드의 진실로 승격하지 않음 |
| Sol VO5/P1 | 수용 | typed output/probability/승인 상태 분리. no-match/불충분·source 지지·상충 확인과 한국어/인용 공격의 독립 평가. wrapper가 남긴 요청 model alias는 실제 resolved revision 증명과 다름. 모델 confidence만으로 fact/rule 승격하지 않음 |
| Sol VO6/P1 | 수용 | accepted/queryable/human-approved, durable ACK·worker ownership/fence/cancel, source/권한 최신 검사를 분리. cache는 stage/model/prompt/parser/policy/source revision을 포함하고 hit에도 eligibility 검사. best-effort Btel recording을 canonical durable event commit로 대체하지 않음 |
| Sol VO7/P0 | 수용 | rejected/stale/superseded/retracted/soft-retired/privacy-forgotten을 구분. source와 derived state의 read/publish/restore eligibility를 최신 deletion authority로 통제. Hindsight helper의 all-grounding-missing prose 유지 정책은 정적 반례이며 즉시 삭제/API 공격 성공 관찰로 포장하지 않음 |
| Sol VO8/P2 | 부분 수용 | 시연/자기 golden/idea 분리, independent held-out 후속 coding action과 한국어/code/negative strata 및 full lifecycle 비용 필요. **실제 여섯 달 운영 기록을 초기 출시의 필수 전제**로 읽지는 않음: 여섯 달 유지관리의 항목·위험·검증 가능한 범위를 비교하되 처음 출시 전 여섯 달 기다리는 추가 요구는 사용자 요청 밖. 일반 SLA/TCO 수치는 관측 근거가 있어야 함 |

## 유지/수정한 권고

- 유지: 공통 core/domain/release + 회사/개인 독립 deployment; MCP와 설치형은 직교. 다수 session/agent와 개인 cloud의 기본 후보는 C. 실제 MCP 소비자가 없으면 B, session 밖 진행이 필요 없고 kill/restart durable 복구를 만족하면 A도 유효하다.
- 유지: 기존 engine generic 추출/검색/reflect를 재사용하고 중복 generic engine를 만들지 않는다.
- 명확화: 재사용 후보다운 이점과 `thin wrapper만으로 full 영상형 제품`은 다르다. internal publish, 이중 추출의 근거/승인 대상 변형, 철회/ID remap/restore 권위를 통제 못 하면 patch 또는 교체/좁은 fixed-backend core 비교가 필요하다.
- 새 책임: three-branch signal·parent-run ledger·source revisions·조건부 shard/pointer·candidate/reject history·feedback/health. BAML/Jev는 선택 도구이며 특정 engine/DB 필수 근거는 영상에 없다.
- 불가능 조건과 제품 acceptance는 원문 조사/설계/native review의 완료와 별개. 실제 제품·host 연결·품질/복구 보증을 이번 native 실행으로 인증하지 않는다.
