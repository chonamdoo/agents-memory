# agents-memory 업데이트 전 체크포인트 — 2026-10-12

## 결론과 상태

독립 Python 메모리 서비스가 기준이다. Agent Flow·Claude Code·Codex·omp는 소비자이며 제품의 런타임 의존성이 아니다. 회사 로컬과 향후 개인 클라우드는 같은 application handler·승인·철회·출처·publication 계약을 사용한다. 회사 corpus를 개인 클라우드로 동기화하지 않는다.

현재 구현과 실제 실행 근거는 보존하지만 **정식 AF 리뷰·QA·handoff 완료, 1–2주 실사용 완료, 클라우드 배포 완료를 주장하지 않는다.** 사용자가 기존 워크트리 삭제와 리더 기준 최신 AF 업데이트·작업 재개를 지시했다. 아래 실행 순서는 계획이며, 실행 결과는 GitHub 이슈와 후속 승계 기록에 별도로 남긴다.

## 이미 구현·실행한 범위

- 독립 `agents-memory` CLI / `agents_memory` 패키지 / 소비자 `.agents-memory` 이름. 과거 불투명 저장 경로·opaque ID는 이름 변경을 이유로 마이그레이션하지 않는다.
- 공식 Python MCP modern/legacy 전송이 동일한 application handler를 호출한다. 연결 시 corpus/rule body를 제공하지 않으며, 요청 시 bounded context만 제공한다.
- 실제 PostgreSQL 18·pgvector, durable fenced 작업 큐, credential-bound principal/project/purpose, 정확한 revision 승인과 철회, 삭제·restore publication barrier.
- capture → 추출·조건·시간·entity → consolidation → hybrid recall·rerank → 근거 인용 reflect → correction/retraction → 다음 consumer read. 승인되지 않은 candidate는 규칙 authority가 아니다.
- 적용 범위 세 가지: 이 로컬 프로젝트 / 이 배포 안의 내 프로젝트 / 팀·프로젝트 공유. 개인 프로젝트 규칙에 팀 배포를 강제하지 않는다.
- opt-in Claude/Codex/omp adapters, host별 truthful capability, source/snapshot 검사, local spool·doctor·token·암호화 backup/restore journal.
- 루트 AGENTS.md/CLAUDE.md에 전체 convention·skill·memory catalog를 넣지 않는다. 명시된 모델 경로 외의 외부 route, 회사→개인 fallback, 모델 자체 승인, 연결 시 preload를 금지한다.

### 관찰된 검증 — 기존 실행과 승계 후 실행을 구분

상세 원본: [verification.ko.md](verification.ko.md).

- 직전 전체 실행: **747 passed, 91.75s, skips 0**, ruff exit 0, package build exit 0.
- fresh wheel을 checkout 밖의 offline/no-deps 환경에서 설치하여 실제 snapshot inspect를 실행했다.
- R19 실제 서비스에서 Claude Opus 5.5 xhigh / omp Codex 6.1 Sol xhigh / Codex 6.1 Sol xhigh가 각각 실제 MCP 호출 3회를 수행했다. 수정된 14일 근거, 승인된 규칙이 아닌 사실/candidate, 이전 source 철회, 다음 조회의 stale body 미반환을 확인했다.
- 실제 API 및 설치 CLI의 source/snapshot missing·mismatch 거부와 exact match 반환을 확인했다.
- discovery 282 UTF-8 B / 4-tool catalog 3,922 B / connection instructions empty / context 749 B / 그 응답 wire 1,741 B를 관찰했다. **전체 native prompt 비용이 0이라는 뜻이 아니며, bytes를 token 수로 바꾸지 않는다.**
- 위 수치는 직전 실행 증거다. 워크트리·설치 경로를 바꾸면 실제 기동·호출을 다시 확인해야 한다.

## 추가 조사와 실제 native 1차 리뷰

저장소: [GitHub 설계 이슈 #1](https://github.com/chonamdoo/agents-memory/issues/1), [Runlayer 영상 조사 #2](https://github.com/chonamdoo/agents-memory/issues/2).

로컬의 [2026-10-12 조사 자료](research/2026-10-12-memory-skills/)에는 Boundary/HumanLayer/BAML 원문 조사, Skills over MCP 사양·SDK·host 조사, Runlayer 영상 Opus 원문 감사, 실제 Opus/Sol 1차 리뷰와 provenance, 추가 공개 소스 확인을 보존한다. 이 디렉터리는 **조사 자료이지 연결 시 주입되는 skill/corpus가 아니다.**

### 동일 잣대와 모델 실행 근거

- public/synthetic frozen packet: 27,917 UTF-8 B, SHA-256 `e616627f23ed5c7182956cbd990af6809894b96c490f2a9f4d146f5c1d15fac7`.
- 동일 prefix를 포함한 native stdin: 28,564 B, SHA-256 `13d0f5d8b2320888f428705fe99fc19b47d8a3fae71a0d880928907e48bb988f`.
- 두 작업을 병렬로 실행했다. Opus는 실제 Claude CLI `claude-opus-5-5 --effort xhigh`, exit 0, 411.454s; native JSON의 `modelUsage`에서도 모델 ID가 관찰되었다. effort는 전달한 CLI 설정이지 서버가 echo한 증명이 아니다.
- Sol은 실제 Codex CLI `gpt-6.1-sol`, `model_reasoning_effort="xhigh"`, exit 0, 308.157s; JSONL에 모델/effort 식별자가 별도 관찰되지는 않았다. argv 설정과 exit를 근거로 기록하며 self-report를 모델 증명으로 쓰지 않는다.
- 두 stdin이 같다는 증거이며 host system prompt까지 같다는 증거가 아니다. 두 리뷰는 read-only·도구 미사용이고 제품 성능 실험이 아니다.
- **신규 조사에 대한 1차 리뷰는 완료, 상호 반박/합의와 도입 결정은 미완료**다. 초기 설계 조사에서 완료했던 별도 round2와 혼동하지 않는다.

### 통합 시 바로잡아야 할 점

1. `procedure`는 이미 `MemoryWrite` 종류에 있다. 신규 memory kind를 만들자는 1차 리뷰 의견을 그대로 채택하지 않는다. 기존 `rule_candidate`도 승인 경로와 함께 재사용한다.
2. 새 Tech Bridge 영상 `jDdgfTp_PXw`와 AI Engineer 원본 `u-o0sW9nwmk`는 동일 발화의 재업로드다. 독립 두 사례가 아니다. 36→100은 vendor 단일 사례이며 n·기간·holdout·oracle·로그가 공개되지 않았다. 전후 동일 Sonnet 4.6·동일 harness를 자막만으로 검증하지 못했다.
3. Boundary 영상 `mAKUL12h1n8`의 stale-memory 대응·승인/거절 피드백·학습은 구현 수준과 향후 계획을 구분한다. **CueFinder 제품·codegraph 재사용·SQLite/FTS5 최소 구성 검토를 이 영상의 주장으로 포함하지 않는다.**
4. Python Skills SDK PR #3485 소스 병합은 실제 설치된 SDK 기능·Claude/Codex/omp native consent 지원을 증명하지 않는다. 확인한 SDK client 소스 위치는 `mcp/client/extensions/skills.py`다. main branch에 존재한다는 사실과 출시 패키지를 분리한다.
5. required applicability가 UNKNOWN이면 현재 계약의 fail-closed를 지킨다. 일반 advisory label로 바꿔 protected action을 진행시키지 않는다.
6. AGENTS/CLAUDE root 주입, catalog preload, untrusted skill의 자동 실행·자동승격, 조직 broadcast, 회사 cloud gateway, 부정적 feedback의 자동 authority 변경은 도입하지 않는다.

### 잠정 제안 — 코드 도입 승인이 아님

현 서비스·4개 bounded tool·PG authority·exact approval·lineage closure를 유지한다. 신규 기능을 즉시 추가하기보다 실제 trial에서 기존 procedure/candidate 경로의 재사용을 먼저 평가한다.

| 후보 | 현재 처리 | 이득 | 비용·위험·선행 조건 |
|---|---|---|---|
| 기존 procedure/candidate 재사용·명시적 사용자 feedback | trial 지침부터, 신규 authority 없음 | 잘못된 반복 제안·절차 재사용을 관찰 | feedback persist와 검증된 outcome을 혼동하지 않음; 승인/거절 revision을 정확히 연결 |
| 긴 규칙 stub + bounded/paged inspect·관련성 선택 | trial 후 별도 검토 | 긴 절차를 root preload 없이 필요할 때 읽음 | mandatory 범위·완전성·overflow·철회 검사 유지, 새 연결 시 catalog 금지 |
| 코드 의존성 변화에 따른 재검토 | stale trigger 설계부터 | 문서·코드 변화에 오래된 기억 재검토 | content hash를 코드 유효성 oracle로 취급하지 않음; unknown required는 거부 |
| opt-in verified outcome / 소량 tool trace / candidate distiller | 검증 기준과 host capture 가능성 확인 후 | 실패·수정의 원인과 다음 run 연계 | self-reported success가 verifier가 아님; 개인 opt-in, 경로 허용, 보존·삭제·비용 한도 |
| Skills over MCP | 지금 core 전환·5번째 대형 tool 없음 | 향후 정적·불변 읽기 전용 projection | 실제 출시 SDK·host consent·digest 재동의·origin identity·철회·lazy get을 먼저 검증 |
| 회사 corpus의 개인 클라우드 동기화·무인 자동승격 | 거절 | 해당 없음 | 보안·승인·배포 격리 불변식 위반 |

이 표는 동일 잣대의 현재 조사 분류다. 최종 순서·범위는 실제 두 native의 상호 반박 결과와 trial 근거로 확정한다.

## AF 업데이트 계약과 보존한 로컬 delta

- 이전 프로젝트 설치: v0.3.15, 공식 source `0ffba881a0c3f1c20f41359f205ef4e517ed5482`; global AF는 v0.3.14였다. 이번 요청은 **리더 프로젝트 설치**의 최신 갱신이며 global/다른 프로젝트를 임의 업그레이드하지 않는다.
- 2026-10-12 authenticated GitHub 조회에서 최신 공식 main은 `5b92996a38c6411c61f36d7be10aed1dc26405e5`였다. semver가 같아도 source commit이 달라 갱신 대상이다.
- `agent-flow update`는 확인 명령이지 설치 갱신 명령이 아니다. 공식 checkout과 리더에 복사된 managed assets를 별도로 갱신한다. active run 중 덮어쓰지 않는다.
- 선택 architecture는 `local`, frozen digest `11bb919aa0fe7defd4da85237192b8396c867740e8007753888d0d00b219a816`. `.agent-flow/project.yaml`, `profiles/python.local.yaml`, local architecture 원문·gates·모델 설정을 보존한다. 기존 run의 workflow binding/approval을 새 버전에 재핀하지 않는다.
- 사용자가 승인했던 프로젝트 private delta는 [timeout patch](../patches/agent-flow-0.3.15-review-timeout.patch)에 보관했다. default 600s; `AGENT_FLOW_REVIEW_TIMEOUT_S` 정수 1–3600; 실제 재리뷰 설정 1800s. 원 공식 `hosted.py` SHA-256은 `c55b644e6c7a1674776c500bfc870e019dd95e333a05666cf4ece882db7a897d`다.
- 패치의 실제 malformed/zero 설정은 CLI exit 2로 거부됐으며, 1800s native 재리뷰를 시작했다. 이전 600s timeout을 승인 verdict로 바꾸지 않았다. 새 공식 버전에 **무조건 재적용하지 않는다**. 공식 지원 여부와 exact source baseline을 확인하여 중복·충돌을 피한다.

## 다음 작업 — 순서 고정

1. 구현·문서·조사·승인된 runtime delta를 local commit으로 보존하고, 추가 조사 전체·현재 완료/미완료·모델 증거·원문 정정·다음 순서를 GitHub #1/#2에 게시한다. 소스 push·공개 배포는 하지 않는다.
2. 소유한 reviewer parent를 정상 interrupt하여 자식 process group을 종료한다. 지원되는 `abort`로 기존 run의 active 상태를 끝낸다. 공식 `abort`는 run 상태 변경이며 그 자체로 OS 프로세스 종료를 보장하지 않는다.
3. 기존 AF 설치·local profile·norm·원문·추가 조사 입력을 checkout 밖에 보존한다. 실제 지원되는 `worktree remove --keep-branch`의 run archive 검증을 이용해 **해당 owned checkout만** 삭제한다. DB·journal·tokens·모델·backup·사용자 연구 파일·다른 worktree는 삭제하지 않는다.
4. 리더를 보존된 `agents-memory` branch에 안전하게 전환하고, 개인 변경을 유지한 채 최신 공식 소스의 프로젝트 설치를 갱신한다. old run의 승인·marker를 새 run 완료로 재사용하지 않는다.
5. 게시된 GitHub 이슈와 승계 artifact를 다시 읽고, 최신 AF 계약으로 remaining-work successor run을 시작한다. Source 경로 변경 후 MCP 서비스·CLI·snapshot/native 경로를 실제 실행하여 확인한다.
6. 추가 조사 Opus/Sol 상호 반박: 각자가 상대 보고서와 위 원문 정정을 읽고 동일 잣대로 재평가한다. source 확인·제품 runtime proof·proposal을 구분하여 최종 도입/보류 결정을 기록한다.
7. 필요 수정만 구현하고 해당 경계 smoke를 수행한다. fresh formal reviewer 결과 → 필요한 수정 → gates → QA → handoff 순서를 완료한다. 그 뒤에 실제 1–2주 personal trial을 시작한다. trial 기간이 지나기 전 성공을 만들어 쓰지 않는다.
8. trial 결과로 장기 절차 전달·관련성·verified outcome 우선순위를 결정한다. 개인 cloud 인프라와 별도 credentials·network policy가 마련된 뒤에만 cloud deployment를 진행한다.

## 보안·취급 제한

회사 코드·대화·memory corpus·비밀을 GitHub/외부 연구 모델/개인 클라우드로 보내지 않는다. 팀 Claude/Codex 계약은 승인된 모델 route의 근거일 수 있으나 로컬 memory의 zero-egress 증명이 아니다. Git에는 token/DSN/age private key·개인 corpus·full raw provider internals·설치 venv를 넣지 않는다. 원문 자막 및 native 실행의 공용 근거 cache는 별도로 보존하고, 공개 성과로 과장하지 않는다.
