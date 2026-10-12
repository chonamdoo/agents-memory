# 새 영상 native Opus 5.5 xhigh — 근거별 판정

입력: `video-review-input.ko.md`, 205,168 bytes, SHA256 `c046de5447908e18d0762a533058d49fe8df4699bff90ac3bdc78a9fb0b5db3b`.
원문: `video-review-opus-5.5-xhigh.ko.md`, raw JSON result 그대로 보존. native ID 순서는 VS3,VS1,VS2,VS4,VO2,VO3,VS5,VO1이며 재번호화하지 않는다. 신규 제품의 설계 위험/수용 조건이지 실제로 발견·실행한 취약점이나 제품 test 결과가 아니다.

| Native ID/severity | 판정 | 채택 범위·반론 |
|---|---|---|
| Opus VS3/P1 | 조건부 수용 | canonical candidate/revision·승인·삭제 authority와 engine index/파생 구분, 모든 read/publish/restore 경로 eligibility·최신 fence 필요. 승인 내용을 재추출한 prose로 바꾸지 않음. read-time join은 **식별 가능한 모든 의존성과 모든 전달 경로를 강제할 수 있을 때만** 충분; 불완전한 based_on이나 engine 내부 bypass를 해결했다고 가정하지 않음. reflect/mental models는 provenance가 있는 파생 후보로 계속 제공·검증해야 하며 꺼서 full pipeline을 축소하지 않음. 안 되면 backend patch/교체·좁은 core 비교 |
| Opus VS1/P1 | 수용, 경계 명확화 | **기억→주입→agent 반복→독립 지지 증가의 echo loop**는 기존 parent/child dedup와 별개다. delivery receipt(candidate/revision/hash/session/turn), injected/agent-claim/tool-observation/human-input origin과 derivation을 연결하고 echo를 독립 증거에서 제외. 이후의 새 revision tool 관측·실제 human correction까지 일괄 제외하지 않음. stale 자기판정은 재검토 trigger이며 확정 삭제/규칙 변경 권위 아님 |
| Opus VS2/P1 | 부분 수용 | code가 canonical stable ID를 할당·보존하고 모델은 existing/new/ambiguous 대응만 제안. 승인/거절은 ID+revision+exact text hash와 scope에 결합. **claim+지원 span 집합의 hash를 매번 identity로 쓰면 새 evidence가 추가될 때 ID가 바뀔 수 있음**; 영속 ID와 evidence/revision append를 분리. 동일 새 inference의 byte-identical 문장 출력을 일반 보장하지 않으며 persisted state/cache replay의 identity 안정성을 검증 |
| Opus VS4/P1 | 수용 | hook 채널의 우선순위를 memory authority로 오인하지 않음. low-risk fact 자동 accepted는 명시 policy이고 normative rule 승격은 별도 operator 승인. 미승인 candidate는 unverified 자료로 명확히 구분. host/version별 검증된 scope/region trigger, 실제 delivery receipt·사용자 가시성, reviewer/CI 비활성, tracked file 명시 승인. installer/service가 readiness를 자동 보장하지 않음 |
| Opus VO2/P1 | 부분 수용 | facts/corrections/recurring의 원문 종류·권위와 최종 Where/Rules/Facts 섹션은 다른 축. draft 문장별 source/candidate 지지와 unsupported addition을 확인. **Rules를 반드시 'human correction'에서만 생성**하는 제한은 채택하지 않음: authenticated 인간의 새 명시 standing instruction도 별도 승인으로 가능. 승인없는 agent 요약을 규칙으로 승격하지 않는 핵심은 수용 |
| Opus VO3/P1 | 부분 수용 | 반복은 고객/프로젝트의 authorized partition 안에서만 집계. 개인1인/팀9인 corpus와 최소지원량 차이는 profile별 signal 해석·평가. 한 번뿐인 권위 있는 correction도 후보로 보존. **개인 UI에서 people 수를 반드시 숨길 것**은 임의 표시 규칙이라 미채택; 소유자 수/발언자 수/명시 지지를 정확히 구별하면 됨. 교차 직원 분석은 명시 정책/허용 범위 |
| Opus VS5/P2(BAML 기록 채택시 P1) | 조건부 수용 | Btel/CAS/query/cache는 별도 raw copies, 데이터 root·credentials·egress·retention·forget 범위를 분리. 회사 profile의 query datasource 명시·telemetry/input capture 정책·권한 필요. 무조건 telemetry 전체 제거가 아니라 필요한 관측과 민감 원문 capture를 구분해 정책화. home-scoped shared CAS를 고객별 격리라고 광고하지 않음. Query의 read-only가 교차고객 read ACL이라는 뜻은 아님 |
| Opus VO1/P2 | 수용, source capability 경계 | session/message/user ID와 enable 버튼은 초기 POC 설명; 최종 시연에서 확인된 것은 session/people 집계와 코드영역별 결과이며 **message+offset+actor의 최종 보존은 미입증**. people 수를 인간의 explicit agreement 수로 표시하지 않음. host가 typed/pasted/injected provenance를 구별 못 하면 unknown을 보존하고 모델 추정으로 authenticated human-typed 판정을 만들지 않음 |

## 원문 분석의 추가 정정

1. 05:54의 message ID citation은 초기 좋지 않았던 POC schema 설명이다. 최종 결과에도 같은 granularity가 유지됐다고 검증한 것은 아니다.
2. 세 갈래 입력 신호와 Where/Rules/Language facts 출력 섹션은 같은 축이 아니다. 출력은 근거 종류/권위를 잃지 않도록 제품에서 설계해야 한다.
3. architecture.md pointer 사례는 report와 repo를 외부 agent에게 추가로 준 ad-hoc 발견/해결 제안이다. 영상 pipeline에 자동 pointer discovery 단계가 완성됐다고 주장하지 않는다.
4. '모델 작성=이미 weights에 있어 무용'이라는 일반 명제의 정확한 발언 위치는 **22:16–22:58**이다. 29:31 facts prompt의 generic/personal/unexecuted-plan exclusion과 분리한다.
5. 장문 prune에 대한 20:44와23:09 자동 자막 표현은 서로 어긋난다. exact 구현/blanket 절단 규칙을 원문만으로 확정하지 않는다.
6. 45:29–48:22의 타사 memory 구성 비평, cross-session correlation, labels/folders와 cron consolidation 토론을 추가한다. 타사 공개 문서를 실제로 완전히 검증한 제3자 판정으로 재사용하지 않고 화자의 비교 의견/후속 설계 아이디어로 표시한다.

## 모델 간 주요 차이와 부모 판단

- Opus는 **B-first + 나중 read/propose MCP**를 권고했고 A를 manual-only fallback으로 한정했다. Sol은 C 조건부 기본, 소비자가 없으면 B, durable session-bounded mode를 충족하면 A도 유효하다고 보았다.
- **B-first를 초기 제품 범위로 채택하지 않는다.** 사용자 목표는 여러 agent/개인 cloud의 MCP 접근 비교이며 실제 문서상 Claude/Codex MCP 소비자가 있다. 공통 설치 service를 중심으로 필요한 최소 MCP를 제공하는 C를 유지한다. 없는 소비자/복수 transport를 선제 구현하지는 않는다.
- A의 blanket 기각도 채택하지 않는다. 승인된 유한 실행+재시작 복구가 full domain 계약을 만족하는 좁은 경우는 유효하다. session 밖 주기 작업/개인 remote 접근을 요구하면 기본 C가 더 맞고 A를 full 자동 대체안으로 광고하지 않는다.
- 일반 agent MCP는 scoped read/reflect와 수집·candidate proposal을 중심으로 한다. operator 승인·rule 승격·고위험 forget/export 권위는 agent가 획득할 수 없는 별도 채널/권한으로 분리한다. **MCP라는 protocol 자체를 모든 관리 연산 금지의 이유로 쓰지 않는다.** 저위험 자동 evidence 처리는 명시 policy, 관리자의 별도 MCP/client 가능 여부는 권한모델에 따라 결정한다.
- engine은 아직 결정하지 않는다. 기존 core를 재구축 가능한 index로 취급하는 것만으로 full reflect/재현·삭제 문제를 해결했다고 가정하지 않으며, generic engine 재사용 이득이 검색만 남고 깊은 patch·두중 store가 필요하면 신규 좁은 core의 유지관리 비용과 비교한다.
