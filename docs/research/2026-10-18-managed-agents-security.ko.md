# Managed Agents 영상의 보안 설계와 agents-memory 적용 판단

조사일: 2026-10-18. 대조 source: `5b42c12c91007cc5a6972c6325eb84c221682b54`.

## 판단

**현재 근거로 새로운 제품 subsystem이나 Managed Agents 전환을 제안하지 않는다.** 영상의 보안 원칙 상당수는 기존 role/권한 분리, 현재 admission 재검사, unknown-effect 재실행 금지, provenance/삭제 계약에 이미 반영되어 있다. 대조한 범위에서 새 credential-forwarding 결함을 확정하지 못했다. 이는 침해 부재나 전체 source 승인이라는 뜻이 아니다.

유효한 후속은 두 가지다. 악성 native 코드로부터 관리자 키까지 보호해야 하는 실제 운영 대상에는 기존에 명시한 별도 identity/OS 사용자/VM 경계를 구체화한다. 또 기존 native/PMPA acceptance에서 토큰 탈취와 허가된 도구의 오용을 별도로 판정한다. 둘 다 기존 미완료 조건에 연결하며 새 top-level 개발 누락으로 중복 등록하지 않는다. 현재 요청은 조사·제안이며 실행·운영 변경 승인이 아니다.

## 자료와 조사 한계

- [사용자가 지정한 14:39 영상](https://www.youtube.com/watch?v=3iOP4cXChAc)의 실제 자동 자막을 읽었다. Tech Bridge의 번역 재게시본이며 모델명 등의 전사 오류가 있어 API 사실의 근거로 삼지 않았다.
- [AI Engineer의 원본 17:39 발표와 전체 시간대별 스크립트](https://ai.engineer/talks/Uv0nAf_7tyU-decoupling-brain-from-hands-claude-managed-agents#edited-transcript), [발표자 정보](https://ai.engineer/speakers/priyanka-phatak)를 대조했다. 재게시본과 원본의 시간대를 서로 바꾸어 인용하지 않는다.
- [Anthropic 설계 원문](https://www.anthropic.com/engineering/managed-agents), 공식 Managed Agents 문서, 아래 명시한 현재 저장소 source/요구/운영 계약을 읽었다.
- 별도 read-only scout가 공식 문서를, security reviewer가 native/gateway/runtime/verifier의 credential 경계를 검토했다. 이는 정규 AgentFlow review 표가 아니다. scout는 영상 자막을 확보하지 못했으므로 영상 인용은 integration owner가 실제 읽은 자막·주최자 원문에만 근거한다.
- 정적 조사다. 실제 공격·침해·egress를 재현하지 않았다. 로컬 product runtime/import/test/collection/lint/build/syntax/format/smoke/Docker/native/OS 실행은 하지 않았다. 이 조사에서 새 Actions도 실행하지 않았다. 현재 checkpoint의 전체 CI/정규 review/QA 완료를 주장하지 않으며 기존 실패와 원래18개 완료0 상태를 보존한다.

## 스크립트의 보안 의미

| 원본 발표의 구간 | 확인한 설명 | 보장하지 않는 것 |
|---|---|---|
| [7:53–8:52](https://www.youtube.com/watch?v=Uv0nAf_7tyU&t=473s) | session log, harness/모델, sandbox/tool을 분리해 실행 환경과 harness를 교체한다. | 실패 전에 이미 발생한 외부 효과의 rollback, tool exactly-once, 모든 작업의 무조건 안전한 재시도 |
| [9:08–9:38](https://www.youtube.com/watch?v=Uv0nAf_7tyU&t=548s) | “credentials never entered our sandbox”. 외부 proxy가 인증 정보를 추가한다. | prompt injection 자체의 제거, 허가된 API/도구의 안전한 사용, sandbox가 읽을 수 있는 다른 비밀의 보호 |
| [9:51](https://www.youtube.com/watch?v=Uv0nAf_7tyU&t=591s) | 원본 event stream과 모델에 넣는 압축 context를 분리한다. | 모든 원문을 무기한 보관해도 된다는 개인정보·corpus 허가, 삭제·철회의 자동 충족, 로그를 읽은 agent의 재승인 |
| [13:57 이후](https://www.youtube.com/watch?v=Uv0nAf_7tyU&t=837s) | environment, agent/tool 구성, session/event를 별도로 정한다. | 네트워크 설정 하나가 모든 tool/외부 서비스/tenant 권한을 일괄 제한한다는 보장 |

성능 수치는 보안 근거가 아니다. 설계 원문은 p50 TTFT 약60%, p95 90% 초과 감소를 보고한다. 이를 우리 제품의 성능이나 전체 TTFT 90% 개선으로 옮기지 않는다.

## 적대적 검토

### 1. 토큰을 숨겨도 토큰의 권한은 악용할 수 있다

[Vault 공식 문서](https://platform.claude.com/docs/en/managed-agents/vaults)는 agent가 key가 허용하는 작업을 모두 할 수 있다고 명시한다. 예를 들어 공격자가 tool 결과에 민감 자료를 특정 외부 채널로 게시하라는 지시를 넣을 수 있다. 토큰 문자열을 읽지 못해도 해당 도구에 게시 권한이 있으면 오용 경로가 남는다. 이는 설명을 위한 공격 가정이며 실제 발생을 관측한 것이 아니다.

공식 문서는 추가로 다음 경계를 구분한다.

- credential의 `allowed_hosts`는 비밀을 어느 요청에 주입할지 정할 뿐 모든 네트워크 요청의 허용 목록이 아니다.
- body 주입은 header 주입보다 노출 면적이 넓다. API로 credential을 만들면서 `injection_location`을 통째로 생략하면 header/body가 모두 활성화되는 계약이다.
- secret으로 session token을 교환하면 반환 token은 sandbox에 가려지지 않은 채 들어온다. proxy가 모든 응답의 비밀을 지워 주는 것은 아니다.
- vault는 workspace 범위다. session metadata의 사용자 이름만으로 tenant 격리가 생기지 않는다.

우리 gateway는 body placeholder를 치환하는 범용 vault가 아니다. `evaluation_gateway.py:248–261`은 역할·binding·승인 upstream·한 authority를 제한하고 `292–313`은 native-facing client에 agent credential을 사용한다. coding gateway에 producer client를 붙이지 않는 controller 경로는 `evaluation.py:883–899`다. 실제 서버 credential 검증은 별도로 유지된다. 현재 경계를 버리고 범용 credential proxy를 추가할 이유는 확인하지 못했다.

### 2. 같은 사용자로 실행되는 native 작업은 관리자 파일과 격리되지 않는다

`evaluation_native.py:613–616`은 native executable을 현재 호스트에서 실행한다. 별도 UID나 sandbox를 지정하지 않으며 `env`도 지정하지 않는다. 따라서 일반 subprocess 의미상 부모 환경을 상속한다. 실제 환경 값이나 credential 파일 내용은 조사하지 않았다.

**[INFERENCE]** unrestricted native tool이 실행 사용자에게 읽기 가능한 operator/producer token, provider 설정, private run/oracle 파일을 읽거나 사용할 수 있다. `0700/0600`, 다른 CWD, hash, 별도 process group만으로 같은 UID의 악성 코드를 막을 수는 없다. 이는 새 침해 재현이 아니라 문서가 이미 밝힌 G0 한계다(`architecture.ko.md:95`, `requirements.ko.md:I21`). 부모 환경 allowlist만 추가해도 같은 UID의 파일 접근은 남으므로 이를 vault/강한 격리로 제안하지 않는다.

`evaluation_runtime.py:601–606,645–660,785`의 network-none, read-only mount, capability 제거와 non-root 실행은 **후속 Docker verifier subject**의 보호다. 앞선 native Claude/Codex 실행이 같은 보호를 받았다고 해석하지 않는다. handoff 파일의 no-follow/immutable 검사는 별도의 파일 수입 경계다.

### 3. session 복구는 작업 효과의 안전한 재실행과 다르다

영상과 설계 글은 내구성 있는 event log를 설명하지만 exactly-once 외부 효과를 약속하지 않는다. 외부 API가 반영된 뒤 응답만 유실되었다면 마지막 event부터 다시 수행하는 방식이 중복 효과를 낼 수 있다. 이는 일반적인 실패 가정이며 Managed Agents에서 실제 중복이 발생했다는 보고가 아니다.

우리 제품은 이미 `(principal,binding,command,idempotency_key)`와 payload digest를 묶고 현재 credential/admission을 재검사한다(`architecture.ko.md:87,99–109`, `requirements.ko.md:I04/I07/I33/I38`). 평가 controller도 intent는 있는데 terminal이 없는 경우 `CRASH_INTENT_NO_REPLAY`/unknown을 남기고 owned cleanup만 reconcile한다(`evaluation.py:773–787,1427–1440`). 이 안전장치를 무조건 retry로 바꾸거나 새 event bus/두 번째 job owner를 추가하지 않는다.

### 4. append-only는 삭제·보존 허가를 대신하지 않는다

[공식 overview](https://platform.claude.com/docs/en/managed-agents/overview)는 conversation/sandbox/output의 server-side 저장과 ZDR/BAA 비대상임을 명시한다. [데이터 보존](https://platform.claude.com/docs/en/manage-claude/api-and-data-retention), [session 삭제](https://platform.claude.com/docs/en/managed-agents/session-operations), [memory](https://platform.claude.com/docs/en/managed-agents/memory) 계약도 별개다. 공식 문서 조사에서는 session 삭제가 독립 memory store/vault 등을 지우지 않고 memory version에도 별도 보존 계약이 있음을 확인했다.

우리 메모리 서버에 발표의 “모든 event 보관”을 그대로 옮기면 이미 관측한 bounded 구간만 처리한다는 승인, hidden reasoning 미수집, secret의 digest/spool 전 거절, logical retract/physical purge/backup 구분을 훼손할 수 있다. 현재 source/receipt/audit를 하나의 raw transcript로 합치지 않는다. private evaluation evidence도 secret-free라는 보장은 없으며 운영 지침은 `RUN_DIR` 전체의 public artifact/PR 게시를 금지한다(`release-runbook.ko.md:242`).

### 5. sandbox 밖 도구와 공유 기억도 별도 경계다

[Web restrictions](https://platform.claude.com/docs/en/managed-agents/tools-web-restrictions)에 따르면 web 도구는 Anthropic 서버에서 실행된다. cloud `limited` networking의 `allowed_hosts`는 이 도구에도 적용되지만 unrestricted/self-hosted만으로 제한되지는 않고 각 tool의 domain 목록도 별도로 존재한다. 이 문서로 redirect 처리까지 보장한다고 하지 않는다.

[Self-hosted 보안 모델](https://platform.claude.com/docs/en/managed-agents/self-hosted-sandboxes-security)은 외부 통신, tool의 OS 권한, 작업 간 격리, 남은 memory working copy 정리를 운영자의 책임으로 둔다. `read_only` memory가 upload를 막아도 bash가 local working copy를 바꾸는 것까지 막지는 못한다고 명시한다.

우리 제품도 exact source 인용을 지시의 권위·진실성으로 취급하지 않는다. source selection/candidate와 required-rule 활성화가 분리되어 있고 PMPA/secret reentry 시나리오가 이미 있다(`architecture.ko.md:279–309`). 새 container만 만들거나 참고 memory를 read-only로 표시하는 것으로 기존 P01–P04/R01–R05/native acceptance를 대체할 수 없다.

## 권고와 영향 비교

두 권고는 기존 acceptance/운영 전제의 구체화다. 신규 제품 구현 승인이나 현재 검증 완료 처리가 아니다.

| 권고 | 기존 방식과의 차이·영향 범위 | 장점 | 비용·한계 | 판단 |
|---|---|---|---|---|
| 보호해야 할 운영 키가 있는 untrusted native 실행에 별도 identity/OS 사용자/관리 VM 경계를 적용 | 현재 same-UID G0와 달리 operator/DB/approver key·oracle·controller evidence를 native 파일/환경/mount 권한 밖에 둠. 운영 배치·키 보관·native 실행·필요한 좁은 IPC 연결이 대상이며 DB/schema/일반 memory 판단의 별도 인간 승인 기능을 추가하는 제안은 아님 | 단순 bearer role 분리로 못 막는 파일/환경/관리 권한 접근을 줄이는 실제 경계 | native 로그인·도구·파일 전달·network 허용·복구 운영이 달라질 수 있음. 별도 대상/권한과 실제 검증 필요. 같은 Docker socket/쓰기 mount로 관리자 권한을 다시 주면 경계가 무효 | 민감 운영에서 해당 위협을 막아야 할 때 채택. 기존 I21/native/운영 acceptance에 연결하고 현재 임의 실행하지 않음 |
| 기존 native/PMPA acceptance에서 credential disclosure와 허가된 도구 오용을 별도 판정 | P01/R01 및 실제 first-action/stop/recovery 증거에 synthetic token 읽기 시도, approval 사칭, 허가된 tool의 금지 효과, crash 뒤 unknown 중복 효과를 연결. 기존 보안 사례를 대체하거나 별도 top-level 목록을 만들지 않음 | proxy 존재만으로 안전하다고 결론 내리는 오판을 막고 실제 권한 경계의 효과를 확인 | 서버 API 거절만으로 native 준수를 증명하지 못함. 허용 native 실행 경로·고정 oracle·금지 부작용 관측이 필요. Codex strict unsupported는 계속 blocked | 기존 외부18의 native/matrix/PMPA/운영 항목 안에서 우선 대조. runtime은 계속 허용된 GitHub Actions 병렬 경로뿐이며 native/OS 필수 대상이 없으면 blocked 유지 |

선택적 환경 변수 allowlist는 우발적 ambient 권한 노출을 줄일 수 있으나 provider 인증/실행 호환성 요구를 먼저 정해야 하고 같은 UID 파일 접근은 해결하지 못한다. 이번 조사만으로 새 필수 개발 항목으로 등록하거나 설정을 바꾸지 않는다.

## 채택하지 않는 것

- 이 영상을 이유로 Managed Agents, hosted memory/vault, 새 event store·queue·trace 서비스로 교체하지 않는다. 처리·보존·cloud/corpus/egress 승인이 별도로 필요하다.
- full transcript/Stop/tool result의 무승인 수집, hidden reasoning 보관, 원문 자동 삭제/coalesce/retention, production hybrid/embedding/reranker와 의도적 보류 classifier를 추가하지 않는다.
- durable log에서 이어간다는 이유로 과거 credential/admission/human approval을 재사용하거나 unknown-effect mutation을 자동 재실행하지 않는다.
- trust/guard/settings/pins/판정/timeout/native 승인 UI를 변경하지 않는다. 새 실제 native·운영·trial·merge·release 승인으로 해석하지 않는다.

기존 미완료 개발·health·평가8개·외부18개·OSS 조사와 실패 이력은 그대로 이어간다. 이 메모는 영상 조사 결과이며 제품 수정·정규 독립 review·CI-only QA 완료 보고가 아니다.
