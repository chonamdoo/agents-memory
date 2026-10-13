# GPT-6.1-Sol xhigh 신규 리뷰 판정표

실제 native 출력 `distribution-review-codex-6.1-sol-xhigh.ko.md`를 읽고 작성했다. 리뷰 SHA256 `44328e620c5fef598c5205cb51a48aa5aab6685626e3d5853134d3b78a097b39`; input SHA256 `36d909bc0a8a024b958b76edb23bf7d62c77b1c780e99216a0835aa4d24455a5`. CLI0.162.1 runtime banner는 gpt-6.1-sol/openai/xhigh, exit0. Native API 내부 identity/effort attestation은 아니다. 성공 실행은 2026-10-11T05:43:47.290554Z–05:49:22.900235Z. 출력은 수정하지 않고 보관했다.

이 표의 '채택'은 설계 판단 수용이지 구현 완료·공격/운영/restore 검증 통과가 아니다. #334의 implementation 취약점으로 전이하지 않는다.

| Native ID·severity | 실제 반례 | 부모 판정·게시 반영 |
|---|---|---|
| C1 P1 | native catalog만 보여도 host capture/다음 task recall 없으면 pipeline 미완성; IAM/OAuth 혼동 | 채택. host/surface/version/plan+capture/recall/auth를 지원 단위로 선언. 실제 고객/사용자 계정 MCP 왕복 미실측. cloud storage가 있다는 사실로 모든 hosted agent 자동 지원을 약속하지 않음 |
| C2 P1 | local extract라도 고객 recall을 cloud host에 보내면 반출; 같은 session endpoint 전환은 과거 context를 지우지 않음 | 채택. 회사 정책이 local residency만인지 SaaS 허용인지 strict no-export인지 구분하고 고객/개인의 host·session·credential·backup 분리. 회사가 모든 cloud 모델을 금지한다고 임의 추정하지 않음 |
| C3 P1 | 같은 UID/browser/credential의 approve CLI·direct DB·fake endpoint로 operator 권한 위조 | 채택+범위 정정. 모든 transport의 domain authorization/인증 endpoint 필요. 일반 source 범위 정정·철회는 허용 data-plane 권한으로 수행; 정책변경·scope 통합·export·대량 파괴·directive승격 같은 고위험 action과 구분. 단순 UI/CLI 이름≠human presence |
| C4 P1 | wrapper의 사전 revision 검사 후 engine 내부 stale retain/reflect commit | 채택. operation/source revision/publication authority를 하나로 확정; engine 내부 commit/read fencing을 소유하지 못하면 최소 backend patch/fork 필요. 고정 worker ID만으로 fence 증명 불가. 신규 자체 core는 기존 engine의 필수 계약을 경제적으로 보완 못할 때 비교하며 처음부터 엔진 N개 동시지원 안 함 |
| C5 P1 | old backup과 old deletion ledger를 같이 restore하거나 source spool 재입력해 삭제 자료 부활 | 채택. 최신 deletion head는 같은 trust boundary 내에서 DB rollback과 독립적으로 보존; 최신성 입증 불가면 조회 fail closed. derived summary/vector/cache/worker의 재노출 차단. physical purge·retention·provider/host copy 삭제는 별개 |
| C6 P2 | global capture hook이 다른 고객/리뷰어에게 상속, 전체 config backup 복원으로 후속 사용자 편집 소실 | 채택. host integration 별도 opt-in·소유 entry/현재값 검증; Agent Flow core0줄≠behavior0. fresh/reinstall/update/uninstall/partial failure 관측 기준. ordinary install≠MCP연결·OAuth grant·corpus purge |
| C7 P2 | 한국어 tokenizer/pgvector/model dimension drift로 두 배포의 검색 품질 달라짐 | 채택. 공통 PG/extension·parser/tokenizer·embedding revision/dimension 지원 matrix. semantic contract와 model-output/quality parity 분리. localcompute 부족시 unsupported, 반사 기능 조용히 끄지 않음 |
| C8 P2 | request 후 coroutine·volatile DB·Tasks enqueue gap·복수 startup migration | 채택. 초기 cloud baseline은 VM/Compose+durable PG+기존 worker. Run 지원은 별도 실제 job/reconcile entrypoint 검증. image rollback≠DB/schema rollback, scale-to-zero≠총비용0 |

## PR review axes (합치거나 approval로 바꾸지 않음)

- Standards: 제공된 6개 diff에서 확정 hard violation을 찾지 못함. Fowler judgement로 소비자 없는 shim/vendor abstraction을 Speculative Generality 후보로 지적. 원 PR의 6파일 변경을 Shotgun Surgery로 오독하지 않음. required reviewer 증거/전달량 증가 수용 미완료.
- Spec: #334의 host memory optional 참고·현재 근거·tracked teamrule·설명/ownership 정정에는 부합. 신규 memory engine이 없다는 것은 원 spec 누락 아님. 신규 사용자 요구를 원 PR만으로 충족했다고 말하는 것도 틀림.

## 조건부 선택과 가장 강한 반대

C(local HTTP+remote HTTPS, 필요한 adapter만)+Hindsight 재사용이 우선 후보. A는 전용 단일 host/DB, session 중 전체 pipeline과 다음 session recovery 수용 시 유효. B는 회사가 MCP를 금지하거나 승인된 SDK/API integration을 이미 소유한 경우 유효. 영구 local/cloud engine fork 필요성은 packet에서 입증되지 않음.

최강 반대: C의 구조보다 host 자동화 미지원 상태에서 installer/offline bundle/OAuth/protocol/여러 cloud topology의 제품 표면을 먼저 키우는 것이 위험. full pipeline은 유지하면서 정확한 host·deployment profile만 지원해야 한다. Hindsight commit/fencing/삭제 계약을 wrapper만으로 해결했다고 가정하면 안 된다.
