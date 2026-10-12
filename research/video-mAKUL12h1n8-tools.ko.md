# 영상 mAKUL12h1n8: BAML·Query·Jev·공개 데모의 도구 근거

조사일: **2026-10-11 UTC**. 아래의 현재 버전·가격은 이날 공개 문서/API 응답 기준이며 영상 촬영 당시 버전·청구서와 동일하다고 가정하지 않는다. GitHub는 repository metadata → 실제 default branch commit → immutable commit URL 순서로 조회했다. 설치·모델/API 인증 호출·로그인·제품 실행·build/test/lint/formatter·새 native 모델 리뷰는 **하지 않았다**. source의 테스트 파일을 읽은 것은 테스트 통과 관찰이 아니다.

표기: **[공식 문서]**는 공급자 문서의 명시, **[소스 확인]**은 pin한 공개 코드의 정적 확인, **[영상 발언]**은 원문 자막의 발언, **[설계 추론]**은 이 자료로부터 도출한 조건/반례다. 공급자의 정확도·성능 주장을 독립 재현 결과로 취급하지 않는다.

## 1. 먼저 고정해야 할 결론

1. **BAML v1은 legacy v0 DSL과 다른 언어다.** 현재 소개는 일반 프로그래밍 언어와 typed SDK를 설명한다. 다만 공식 소개는 여전히 pre-1.0, legacy 사이트 안내는 public beta라고 부른다. “v1”을 안정 semver 1.0 출시로 읽으면 안 된다.
2. **typed parser는 형식 복구/타입 적합성이지 의미적 사실성 검사기가 아니다.** 사실·정정·권한·provenance·규칙 승격의 유효성을 보장하지 않는다.
3. **BAML Query는 기록된 BAML 실행에 대한 관찰/질의 계층이다.** 임의 코딩 호스트의 전체 대화를 설치만으로 자동 수집하는 제품이라는 근거는 없다. host invocation도 명시적 계측을 거친다.
4. **원자료는 Btel recording + CAS, SQLite는 재구축 가능한 파생 질의 index다.** `query.sqlite`를 영상의 사용자 기억 원본 저장소/3갈래 memory schema와 동일시하면 안 된다.
5. **Jev는 제한된 후보 판정 모델이지 일반 생성 모델이 아니다.** API의 choice/noul/score, 모델의 확률, confidence, BAML의 typed float/bool 반환은 각각 다른 표면이다. 같은 요청의 질문은 서로의 답을 보지 않는다.
6. **현재 공식 episode의 “Demo Code” 링크에 전체 3갈래 pipeline/대시보드 구현은 없다.** 정확한 링크의 pin한 디렉터리는 `meta.md`와 thumbnail 두 파일뿐이다. 다른 공개 file-memory/agent-feedback 예제는 존재하나 영상 구현의 공개 증거로 대체할 수 없다.
7. **영상의 2센트는 per session으로 바로 정정된 자기 워크로드 발언이다.** 1주 전체 2센트나 모든 memory 운영 2센트라는 결론은 원문과 맞지 않는다.
8. **local storage/self-host service와 local inference/no egress는 별개다.** 현재 Jev 기본 API는 TypeSafe 원격 endpoint다. no-training과 ZDR도 별개이고, 공개 문서는 ZDR을 enterprise 조건으로 설명한다.

## 2. 버전과 출처 pin

| 대상 | 이번에 실제 확인한 pin/메타데이터 | 의미와 한계 |
|---|---|---|
| [BoundaryML/baml repository metadata](https://api.github.com/repos/BoundaryML/baml) 및 [canary commit](https://api.github.com/repos/BoundaryML/baml/commits/canary) | public, default `canary`, Apache-2.0. commit **`99edb5d249850ed92db987148feb78f551a93250`**, commit 날짜 2026-10-10T00:15:14Z. repository `pushed_at`는 2026-10-11T03:15:43Z | 알려진 옛 SHA를 최신이라고 가정한 것이 아니라 이날 canary 응답을 다시 조회해 같은 값임을 확인했다. repository pushed 시각은 그 브랜치 commit 시각과 같지 않다. 이후 canary 이동은 별도 조사 대상이다. |
| [GitHub latest release 응답](https://api.github.com/repos/BoundaryML/baml/releases/latest) | **`baml-language-0.21.1-nightly.20261009.a`**, target_commitish 위 SHA, published 2026-10-10T08:16:42Z. `prerelease:false`, `immutable:false` | release 태그의 API 플래그만으로 안정성/GA를 단정하지 않는다. 아래 코드는 mutable tag가 아닌 commit SHA로 인용한다. |
| [현재 언어 소개](https://boundaryml.com/explore.md), [quickstart](https://boundaryml.com/quickstart.md) | 2026-10-11 열람. 소개에 **pre-1.0** 명시. 문서 자체의 immutable revision은 노출되지 않아 source commit과 동일한 문서 build라고 단정하지 않음 | 문서 설명과 pin한 구현을 함께 읽되, 설치된 toolchain과 일치하는 기능 여부는 실행하지 않아 미확인이다. |
| [legacy init 문서](https://docs.boundaryml.com/ref/baml-cli/init.md) | 2026-10-11 열람. 상단 “BAML v0, the legacy DSL”; v1은 별개 full language/public beta | 이 보고서의 `legacy0`는 이 legacy v0 범위를 가리킨다. 정확한 `legacy0` branch/channel 실재는 확인되지 않았다. [heads/legacy prefix 조회](https://api.github.com/repos/BoundaryML/baml/git/matching-refs/heads/legacy)는 빈 배열, `branches/legacy0` 조회는 404였다. 이것을 v0 코드 자체의 부재로 해석하지 않는다. |
| [ai-that-works repository metadata](https://api.github.com/repos/ai-that-works/ai-that-works), [main commit](https://api.github.com/repos/ai-that-works/ai-that-works/commits/main) | public, default `main`, license metadata `null`. commit **`738a9c18b0302737d5d354d9988f34482966cce6`**, 2026-10-08T17:40:23Z | 공식 episode 링크의 현재 공개 범위 조사다. 2026-10-06 방송 당시의 화면/비공개 작업 디렉터리/다른 링크까지 공개 범위가 같았다는 증거는 아니다. |
| [BoundaryML/baml-demos metadata](https://api.github.com/repos/BoundaryML/baml-demos), [main commit](https://api.github.com/repos/BoundaryML/baml-demos/commits/main) | public, default `main`, license metadata `null`. commit **`dcc3d33f0fd2635d18515a62a10da91ae789f080`**, 2026-09-24T16:26:02Z. [aie/baml.toml](https://github.com/BoundaryML/baml-demos/blob/dcc3d33f0fd2635d18515a62a10da91ae789f080/aie/baml.toml) pins **`0.20.2-nightly.20260923.a`** | 별도 예제를 최신 BAML release/영상 source와 동일시하지 않는다. 공개 열람 가능하다는 것만으로 재배포 가능한 OSS license를 확정하지 않는다. |
| [Jev models](https://docs.typesafe.ai/models.md), [API](https://docs.typesafe.ai/api.md) | 2026-10-11 열람. 현재 **`jev-1.13.0`**, `jev-latest`/`jev-preview` 모두 이 버전. [jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13.md)는 applies `jev-1.13`, last reviewed **2026-10-02** | 공급자의 현재 공개 계약/알려진 제한이다. 실제 영상에서 쓴 Jev 정확한 버전은 본 조사로 확정하지 못했다. authenticated 모델 목록/청구 usage를 요청하지 않았다. |

큰 repository의 전체 recursive tree 응답은 읽기 도구에서 잘렸으므로 전체 저장소 부재 판정의 근거로 쓰지 않았다. Query/recording 관련 crate와 episode 디렉터리 등 좁은 subtree/파일을 조회했다. 특히 episode subtree는 GitHub 응답의 `truncated:false`를 확인했다.

## 3. BAML v1: typed programming/파서와 memory 권위는 다르다

### 3.1 공식으로 확인되는 표면

**[공식 문서]** [Explore](https://boundaryml.com/explore.md)는 BAML을 TypeScript와 유사한 일반 프로그래밍 언어로 소개하며 native Python/TypeScript SDK, green threads, typed errors, 함수 실행 CLI, AST-aware `baml describe`, standalone binary `baml pack`을 설명한다. [pin한 README](https://github.com/BoundaryML/baml/blob/99edb5d249850ed92db987148feb78f551a93250/README.md)도 generated `baml_sdk`와 언어 배포를 설명한다. 반대로 legacy 사이트의 `client<llm>`, Jinja/기존 generator/`baml_client` 중심 자료는 v1의 현재 문법/API 근거로 섞지 않는다. [version-matched skill source](https://github.com/BoundaryML/baml/blob/99edb5d249850ed92db987148feb78f551a93250/skills/baml-core/SKILL.md)에도 이전 DSL과 달라진 문법이 적혀 있다.

**[공식 문서]** Explore의 parser 문장은 “recover valid typed values from imperfect model output”이다. 깨진 출력에서 typed value를 복구한다는 뜻이지 실제 세계에서 참인 주장만 반환한다는 뜻이 아니다. legacy [Reducing Hallucinations](https://docs.boundaryml.com/examples/prompt-engineering/reducing-hallucinations.md)조차 prompt/pruning/reflection으로 hallucination을 줄이는 조언을 별도로 제공한다.

**[설계 추론]** `{fact:string, source_id:string}`가 정상 파싱되어도 source_id가 실제 발언을 지지하는지, 사용자가 부정한 사실인지, 현재 프로젝트/고객 범위인지, hostile 원문이 규칙으로 승격되는지는 타입 시스템이 결정하지 않는다. 존재하는 원문 span과 연결하고, 후보/검증된 기억/승인된 규칙의 권위를 분리해야 한다. source 없는 생성 요약을 원문 사실로 승격하는 것도 파서 통과로 정당화되지 않는다.

### 3.2 실행 가능한 언어와 완제품 설치를 혼동하지 않기

**[공식 문서]** quickstart의 `baml agent install`은 Claude Code/Codex에 version-matched **skill**을 설치하는 설명이다. 호스트 전체 대화 archive를 capture하는 collector 설치라고 설명하지 않는다. Explore는 harness/delegation surface가 개발 중이고, typed eval 예시/일부 scoped mocking은 “not available yet”, 아직 package manager가 없다고 명시한다.

**[설계 추론]** BAML로 CLI/MCP adapter/pipeline을 작성·배포할 수 있다는 주장과, 이미 완성된 cross-host capture+memory installer가 제공된다는 주장은 다르다. MCP는 호출 인터페이스, capture는 데이터 유입, installer는 바이너리·서비스·호스트 설정 배포다. 세 가지의 코드/운영 책임을 각각 확인해야 한다. type reflection 기능의 존재도 기억에 대한 사후 reflect job/정정·승인 workflow가 구현됐다는 증거가 아니다.

## 4. BAML Query·Btel·CAS·SQLite: 무엇이 자동이고 무엇이 아닌가

### 4.1 원자료와 질의 index

**[소스 확인]** [query crate lib.rs](https://github.com/BoundaryML/baml/blob/99edb5d249850ed92db987148feb78f551a93250/baml_language/crates/baml_query_btel/src/lib.rs)의 시작 설명은 명확하다.

> “Recording stays BTEL files plus CAS blobs.”
> “The first query creates a disposable SQLite index beside them (`.baml/btel/query.sqlite`).”
> “Captured values stay in CAS and are decoded lazily (and verified) only when a query asks for them.”

[store.rs](https://github.com/BoundaryML/baml/blob/99edb5d249850ed92db987148feb78f551a93250/baml_language/crates/baml_query_btel/src/store.rs)는 `query.sqlite`, writer lock, WAL과 schema/normalization version에 따른 transactional rebuild를 구현한다. recording 디렉터리가 없으면 lib.rs는 empty in-memory index를 사용하고 원자료/영구 index를 만들어내지 않는다. [query_command.rs](https://github.com/BoundaryML/baml/blob/99edb5d249850ed92db987148feb78f551a93250/baml_language/crates/baml_cli/src/query_command.rs)는 read-only SELECT와 새 recording refresh, `--no-refresh`, verification/budget 옵션을 다룬다.

**[소스 확인]** [btel_file/lib.rs](https://github.com/BoundaryML/baml/blob/99edb5d249850ed92db987148feb78f551a93250/baml_language/crates/btel_file/src/lib.rs)는 sealed bytes를 재인코딩하지 않고 `.btel` 순서 파일로 전달하며 `.btel.part`는 완성 기록이 아니라고 설명한다. 파일을 쓰고 닫고 rename하지만 강제 storage synchronization을 하지 않아 crash/power loss 때 최근 데이터가 손실/손상될 수 있다. finish 성공도 `RecordingEnd` 생성/완전한 metadata를 보장하지 않는다. [cas.rs](https://github.com/BoundaryML/baml/blob/99edb5d249850ed92db987148feb78f551a93250/baml_language/crates/btel_file/src/cas.rs)는 project/home-scoped immutable CAS와 format version/ID별 경로를 다룬다. CAS는 encryption이나 retention 정책의 동의어가 아니다.

**[설계 추론]** 이것은 recording의 provenance를 유지하면서 질의를 재구축하는 좋은 선례다. 그러나 Btel이라는 raw 실행 기록과 추출된 사실·정정·반복 조사 기억은 별도 레이어다. SQLite index row를 사용자 기억의 원본/승인 상태로 읽을 수 없다. durable memory commit, forget/retraction/restore와 CAS/raw log retention을 함께 설계해야 한다. derived index 삭제만으로 원본에 남은 민감 데이터가 잊혀지는 것도 아니다.

### 4.2 capture 범위의 실제 경계

**[소스 확인]** [catalog.rs](https://github.com/BoundaryML/baml/blob/99edb5d249850ed92db987148feb78f551a93250/baml_language/crates/baml_query_btel/src/catalog.rs)의 `processes` 설명은 **“One row per process that ran BAML”**다. host 종류와 BAML invocation input/output/network metadata를 다룬다. [host_inputs.rs](https://github.com/BoundaryML/baml/blob/99edb5d249850ed92db987148feb78f551a93250/baml_language/crates/baml_query_btel/tests/host_inputs.rs)는 engine recording 설정, `begin_host_invocation`, `TraceOptionsData`의 inputs/output capture, `HostCapture` 등을 명시적으로 호출한 뒤 Query가 이를 보도록 구성한다. 이를 실행하지는 않았다.

**[소스 확인]** [telemetry mode](https://github.com/BoundaryML/baml/blob/99edb5d249850ed92db987148feb78f551a93250/baml_language/crates/btel_settings/src/mode.rs)는 off/low/medium/high로 범위를 나눈다. medium은 기본값이며 ordinary functions의 timing과 LLM capture를 구분한다. [policy.rs](https://github.com/BoundaryML/baml/blob/99edb5d249850ed92db987148feb78f551a93250/baml_language/crates/btel_settings/src/policy.rs)는 input/output/error capture를 독립 설정하며 `NATIVE_DEFAULT_MODE`는 native instrumentation이 현재 unsupported라서 Hidden이라고 적는다. 따라서 모든 입력/출력/외부 native call이 무조건 원문으로 기록된다고 말할 수 없다.

**[영상 발언]** fresh timed 원문 38:47 부근은 특정 함수/LLM 호출의 자동 spans를 설명하고, 41:20 부근은 자체 server가 Query를 shell-out하는 구조를 설명한다. 이는 BAML로 실행된 pipeline의 관찰 가능성과 일치한다. Claude Code/Codex의 전체 대화가 Query 자체에 자동으로 들어오는 설명이 아니다. 원문 파일: `research/video-mAKUL12h1n8-transcript.timed.en.txt`; 부모가 직접 다시 받은 raw en-orig JSON3 SHA-256 **`a12be7a5b4cd8916e14ab0d027515e2f51ee915a5370b19f45c75edc8553b734`**. 본 담당자는 비용/관찰 구간을 직접 읽었으며 전체 자막 재확인은 부모가 별도로 수행했다.

**[설계 추론]** cross-host 독립 OSS에서는 host transcript adapter/import/event capture가 별도 필요하다. BAML을 호출하는 소수 함수만 기록한 경우 “전체 세션”이라는 provenance 표기를 붙이면 안 된다. 누락·omitted·truncated·capture pending·CAS missing을 빈 문자열/없음과 구분해야 한다. query_command의 `baml_value_state` 도움말도 이 상태들을 구분한다. 영상의 구어 “six tables”(43:21)는 현재 영구 schema의 보장/사용자 memory 테이블 6개라는 계약이 아니다.

### 4.3 local/cloud 의미와 egress

**[소스 확인]** query catalog는 local/Boundary cloud가 공유하는 public relation 계약이라고 설명하고, recorder의 [lib.rs](https://github.com/BoundaryML/baml/blob/99edb5d249850ed92db987148feb78f551a93250/baml_language/crates/btel_recorder/src/lib.rs)는 local/cloud publisher가 같은 RecordingBuilder를 쓴다고 적는다. 이는 recording/query 계약 재사용의 근거다. 동일 facts/correction authority·memory retention·tenant isolation·API response를 갖는 독립 self-host memory 제품의 완성 근거는 아니다. Boundary cloud의 모든 서버 구현/운영 계약을 이번 범위에서 검증하지 않았다.

**[소스 확인]** query_command는 `--local`로 local recordings를 선택한다. `BOUNDARY_API_KEY=local`도 local query를 선택하지만 project/environment와 양립하지 않는다. 반대로 명시적 `--local`이 없으면 API key 또는 saved login이 존재할 때 cloud query 경로를 선택할 수 있다. credential store 읽기 실패를 local로 조용히 fallback하지 않는다. [ENV_VARS.md](https://github.com/BoundaryML/baml/blob/99edb5d249850ed92db987148feb78f551a93250/baml_language/ENV_VARS.md)는 runtime `BAML_TELEMETRY`, Boundary endpoint/project/key, endpoint-scoped login cache 및 CLI anonymous analytics의 `DO_NOT_TRACK`를 **서로 다른 설정**으로 설명한다. login cache는 permission 제한을 둔 plaintext로 설명된다.

**[소스 확인]** [network.rs](https://github.com/BoundaryML/baml/blob/99edb5d249850ed92db987148feb78f551a93250/baml_language/crates/btel_settings/src/network.rs)는 traced HTTP의 allowlist 밖 header/query 값을 hash 처리하고 body capture 최대 **8MB**를 설정한다. 이것이 raw body의 모든 개인정보/기업 기밀을 자동 제거한다는 뜻은 아니다.

**[설계 추론]** `--local`은 **이 query의 datasource** 제어이지 모델 inference·runtime telemetry·CLI analytics·모든 외부 tool egress를 한 번에 금지하는 스위치가 아니다. 회사/외주 고객 local과 개인 self-host cloud를 같은 pipeline 의미로 운영하려면 동일 extraction/lifecycle 계약과 함께 데이터 root, tenant/source scope, credentials, inference/telemetry destination을 분리해야 한다. local에 파일을 저장하면서 원문을 Jev/생성 모델에 보내는 경우를 no-egress로 소개하면 안 된다.

## 5. Jev: primitive, 독립 질문, confidence와 BAML adapter

### 5.1 API 계약과 생성의 경계

**[공식 문서]** [API](https://docs.typesafe.ai/api.md)는 `POST /v1/systemone` 요청의 `state`, `model`, ID별 `questions`와 응답의 `model`, `answers`, `usage.input_tokens/output_tokens`를 설명한다.

| primitive | 문서의 반환/제약 | memory에 적용할 때의 경계 |
|---|---|---|
| **choice** | 최대 255 후보 중 한 option, 전체 probabilities와 confidence. 최소 후보 2개는 pin한 BAML adapter도 검사 | 원문에서 미리 만든 후보 분류/선택에는 맞는다. 정답 후보가 없으면 confident wrong도 가능하다. `not stated`/미확정 후보 필요성은 도메인 계약에 달림. 자유 서술 사실을 만들어내는 generation이 아니다. |
| **noul** | yes/true 확률 `[0,1]`. 별도 confidence 필드 없음 | durable/개인화/정정 여부 등 한 문장 조건의 gate에 쓸 수 있다. 0.5는 “중간 강도”가 아니라 yes/no 균형이다. 승격 권한/참의 인증서가 아니다. |
| **score** | 2–10 ordered levels, probabilities/legend/confidence, weighted score는 소수 가능 | relevance/priority 같은 ordinal 판단에 맞는다. 실제 수량/날짜/수치 정확도를 역산하는 장치가 아니다. |

**[공식 문서]** [Primitives](https://docs.typesafe.ai/primitives.md)의 동일 요청 질문은 같은 state를 보며 서로 독립적으로 평가된다. 한 질문의 답이 다른 질문에 전달되지 않는다. 추출 답을 바탕으로 다음 검증 질문의 state/options를 만들어야 하면 다음 요청이 필요하다. speculative fan-out은 의존 답을 자동 공유하는 실행 engine이 아니라 가능 분기를 미리 묻고 code가 불필요한 답을 무시하는 패턴이다.

**[공식 문서]** [jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13.md)는 생성용 훈련 모델이 아니며 choice chaining으로 생성을 강제하면 느리고 잘 되지 않는다고 적는다. candidate extraction은 regex/생성 모델, Jev는 후보 선택이라는 분업을 설명한다. 따라서 기억 본문·근거 요약·반복 조사 report 작성까지 Jev만으로 수행한다는 결론은 현재 문서에 맞지 않는다.

### 5.2 confidence ≠ correctness/authorization

**[공식 문서]** [Confidence](https://docs.typesafe.ai/confidence.md)는 probabilities의 집중도를 요약한 statistic이라고 설명한다. choice confidence는 `(p_max - 1/n)/(1 - 1/n)`으로 최고 option 확률을 정규화한다. score는 peak 주변 거리 기반 분산을 요약한다. noul에는 confidence가 따로 없으며 필요하면 `|2p-1|` 같은 derived quantity를 만들 수 있다. stakes/domain에 맞춘 threshold 선택이 필요하다.

**[설계 추론]** concentration이 높아도 원문이 조작됐거나 correct option이 빠졌거나 질문이 잘못됐으면 틀릴 수 있다. p≥0.5는 일반적 안전 승인 정책이 아니고, raw probability만으로 “이 기억을 규칙으로 승격해도 된다”는 결정을 대체할 수 없다. 원문 provenance/contradiction/retraction과 사용자/운영자의 승격 권위를 별도로 둬야 한다. held-out action 평가에서 기억 없음/기억 있음, false-positive promotion, 정정 반영, 잘못된 기억의 후속 행동 피해를 비교해야 한다.

### 5.3 현재 BAML wrapper와 TypeSafe API 전체는 동일하지 않다

**[소스 확인]** pin한 [typesafeai/ns_internal/jev.baml](https://github.com/BoundaryML/baml/blob/99edb5d249850ed92db987148feb78f551a93250/baml_language/crates/baml_builtins2/baml_std/typesafeai/ns_internal/jev.baml)을 읽었다.

- reflected class leaf들을 독립 질문으로 펼친다. 유한 enum/literal union, bool/float 등을 지원하나 arbitrary free text generation으로 확장하지 않는다. media/tools/tool history는 거부한다.
- `request`는 options 없는 leaf를 **noul**, options 있는 leaf를 **choice**로 보낸다. 이 adapter에 score request 생성은 없다.
- float는 noul의 `[0,1]` probability를 반환한다. bool은 그 probability를 **≥0.5**로 강제 변환한다. float type이라는 이유로 generic semantic numeric score를 얻는 것이 아니다.
- `Answer`는 type/noul/choice만 decode한다. API 전체 probabilities/confidence를 typed 반환값으로 보존하는 표면과 같지 않다.
- `Response`는 answers/optional usage를 decode하고 반환 `ai.ModelTurn.model`에는 **요청의 `c.model`**을 넣는다. API 문서의 실제 resolved version `model` 응답 필드를 이 source는 보존하지 않는다.
- `usage`는 input/output tokens를 전달하며 없으면 null. credentials는 `TYPESAFE_API_KEY`/client key, 기본 base URL은 **`https://api.typesafe.ai/v1`**이다.

**[설계 추론]** 영상 17:25의 typed float probability 설명은 이 종류의 gate와 맞지만 semantic truth 보장은 아니다. threshold calibration을 이 wrapper로 운용한다면 `jev-latest` 요청명을 로그에 남기는 것만으로 실제 버전 동일성이 증명되지 않는다. fixed `jev-1.13.0`와 prompt/schema/후처리/threshold 버전을 같이 고정하고, 확률/confidence 전체가 필요한 평가에는 API 응답 표면 보존 여부를 따로 확인해야 한다. 언어의 typed return syntax가 provider의 모든 primitive/metadata를 자동 제공한다는 가정은 반례가 있다.

### 5.4 한국어·context·오류 조건

**[공식 문서]** 현재 [Models](https://docs.typesafe.ai/models.md): text-only, **요청 전체 state+모든 질문 64k tokens**, **state+가장 긴 질문 32k tokens**. state는 같은 요청에서 한 번 처리하고 질문들은 parallel 평가한다. 무관 context가 커질수록 정확도가 떨어진다는 [jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13.md) 제한도 함께 읽어야 한다. English가 주 훈련 언어이며 가장 잘 되고 CJK는 지원되지만 동일 품질이 아니다. 수치 계산/세기/날짜 비교, double negatives/간접 판단, option-order bias, adversarial state가 알려진 약점이다. state를 기본적으로 hostile로 취급하지 않는다고 명시한다.

**[설계 추론]** 한국어 높임말·간접 정정·인용/부정·업무 jargon·코드 혼합·동명이인/고객 scope를 포함한 held-out 원문과 후속 action을 같은 pinned model로 평가해야 한다. English demo의 “valuable 100%” 자기 관찰을 한국어 보장으로 옮길 수 없다. 숫자/날짜에 의한 stale 정책은 가능하면 code에서 계산하고 Jev는 의미 판단에 제한한다. token 상한 이하라는 사실만으로 장문 원문 전부 투입이 품질상 유효하지도 않다.

**[공식 문서]** rate limit는 100K tokens/sec, 80 requests/sec이나 “adjusting dynamically”, 변경될 수 있다. API는 401/422/429/529 등 실패를 설명한다. SDK retry/backoff 설명은 공급자 SDK 계약이지 이번 연구의 실제 호출 성공 관찰이 아니다.

## 6. 가격·usage·ZDR: 2센트의 조건

### 6.1 원문 비용 발언을 정확하게 읽기

**[영상 발언, 직접 해당 자막 읽음]** 12:45–13:10에는 처음 “a week's worth ... $2”라고 말하다 “two cents”로 수정하고, **12:55.760에 다른 화자가 “Two cents per session”**, 12:56.720에 “Yeah. Two cents per session”으로 단위를 확정한다. 따라서 “1주 전체 원문을 총 $0.02에 처리했다”가 아니다. 37:34–37:47의 비용 절감 발언은 자동 자막도 반복/어긋남이 있어 정확한 퍼센트 benchmark로 인용하지 않는다. 이 구간은 pipeline에서 Jev가 cheap gating을 담당한다는 경험적 소개로 한정한다. 문서/청구 로그/원문별 usage가 공개되지 않은 상태에서 end-to-end 일반 단가를 검증했다고 말할 수 없다.

### 6.2 현재 가격으로 가능한 말과 불가능한 말

**[공식 문서]** 현재 Jev 1.13 가격은 **input $42/Btok = $0.042/Mtok**, output tokens free다. API usage의 input/output tokens를 받아 기록할 수 있다. 질문을 한 요청에 묶으면 shared state는 한 번 처리하지만 모든 질문 token budget이 있으며, 별도 요청/반복 호출에 동일 state를 넣는 비용이 없어진다는 뜻이 아니다.

**[설계 추론/산술]** 이 가격에서 Jev 호출만의 비용은 `Σ input_tokens × 0.042 / 1,000,000`이다. $0.02는 약 **476,190 input tokens**에 해당한다. 이 수치는 영상 workload의 실제 tokens 추정이 아니라 현재 가격 환산 예시다. 세션 길이/청크 수/후보 수/질문 반복, cache miss, 생성 모델 input/output, 재처리/reflect와 storage/운영 비용이 바뀌면 총액이 달라진다. 영상 18:38의 input-hash JSON disk cache 설명도 cache hit 재사용과 fresh inference를 분리해 비용을 재야 한다는 조건이다. 모델/prompt/schema/version을 달리한 결과를 같은 cache로 재사용하면 동일 모델 버전 평가가 아니다.

**[소스 확인]** 현재 BAML canary commit 메시지 자체가 모델 가격을 [btel_pricing](https://github.com/BoundaryML/baml/commit/99edb5d249850ed92db987148feb78f551a93250)으로 옮기고 누락된 `gpt-6-luna` 가격을 추가하는 변경이다. 메시지는 local Query가 읽을 때 가격을 계산하고 cloud projector는 write-time 저장한다고 설명한다. 따라서 tool cost column은 가격표/version 영향을 받는 추정 계층이며 billing receipt와 같다고 자동 가정하면 안 된다. 비용 비교는 provider usage, 가격 snapshot, cache hit/miss, 전체 pipeline 단계별 단위를 함께 남겨야 한다.

### 6.3 no training은 no retention/no egress가 아니다

**[공식 문서]** [Legal](https://docs.typesafe.ai/legal.md)는 고객 데이터로 모델을 train하지 않는다는 약속과 **enterprise ZDR 제공/문의 조건**을 별도로 적는다. [Privacy Policy](https://typesafe.ai/legal/privacy-policy)는 실제 마지막 수정 **2025-11-19**, Input(prompt/data/instructions)을 수집한다고 설명하며 service provider 제공 예외, 필요 기간 보유, 삭제 요청/법적 예외, 미국 hosting을 명시한다. page의 자동 published timestamp를 policy 수정일로 대신 쓰지 않는다. [DPA](https://typesafe.ai/legal/data-processing)는 마지막 수정 **2026-04-24**이며 processor/subprocessor/보유 조건을 다룬다.

**[설계 추론]** 원문이 고객 기밀이면 기본 API 사용이 허용되는지 별도 계약/egress 정책 판단이 선행한다. enterprise ZDR 문구만으로 무료/일반 API가 모두 즉시 무보유라는 주장을 할 수 없다. 이번 primary docs에서 Jev weights/local inference 설치 방법/무인증 self-host 모델 배포를 확인하지 못했다. self-host memory service를 만들 수 있다는 것과 Jev까지 self-host/no-egress라는 주장은 구별해야 한다.

## 7. 영상 Demo Code 공개 범위와 다른 예제의 범위

### 7.1 공식 episode 링크의 강한 반례

**[공식 페이지/소스 확인]** [episode page](https://boundaryml.com/podcast/2026-10-06-building-a-memory-pipeline)의 Demo Code는 [ai-that-works/2026-10-06-building-a-memory-pipeline](https://github.com/ai-that-works/ai-that-works/tree/main/2026-10-06-building-a-memory-pipeline)을 가리킨다. pin한 [meta.md](https://github.com/ai-that-works/ai-that-works/blob/738a9c18b0302737d5d354d9988f34482966cce6/2026-10-06-building-a-memory-pipeline/meta.md)는 `aitw-077`, season 2 episode 77, eventDate 2026-10-06T18:00:00Z와 같은 code 링크를 가진다. meta의 media URL은 해당 단일 video ID가 아니라 YouTube playlist다. 이 metadata만으로 단일 영상 ID 연결을 새로 증명했다고 주장하지 않는다.

pin한 episode subtree **`0764336bebce12bcfca3fef6aee1dfbe95cabdfa`**를 [GitHub tree API](https://api.github.com/repos/ai-that-works/ai-that-works/git/trees/0764336bebce12bcfca3fef6aee1dfbe95cabdfa?recursive=1)로 읽었고 `truncated:false`다. 파일은 정확히 두 개다.

- `meta.md`: blob **`9497c8bbd045225fbd66474583181dacb9645b4d`**, 1,100 bytes.
- `thumbnail_ep77.png`: blob **`b1fc4f66144faa8649c6cd0bbedcc7002a380d54`**, 1,243,496 bytes.

**판정:** 이 **정확한 공식 Demo Code 링크의 현재 공개 snapshot**에는 facts/corrections/recurring-investigation 3갈래 전체 pipeline 코드, dashboard/custom server 코드, raw session fixtures, 가격/품질 평가 데이터가 없다. “공식 코드 링크가 있다”는 사실은 “시연 구현을 그대로 clone/install할 수 있다”는 결론을 지지하지 않는다. 이는 영상에서 코드/대시보드가 실제 시연되지 않았다는 판정도 아니고, 인터넷 어디에도 공개 코드가 없다는 전역 부재 판정도 아니다. 다른 당시 링크/별도 브랜치/추후 공개는 미확인이다.

### 7.2 공개 file-memory 예제는 무엇을 실제로 하는가

**[소스 확인]** 별도 [baml-demos/aie/ns_memory/memory.baml](https://github.com/BoundaryML/baml-demos/blob/dcc3d33f0fd2635d18515a62a10da91ae789f080/aie/baml_src/ns_memory/memory.baml), [curator.baml](https://github.com/BoundaryML/baml-demos/blob/dcc3d33f0fd2635d18515a62a10da91ae789f080/aie/baml_src/ns_memory/curator.baml), [ns_agent/agent.baml](https://github.com/BoundaryML/baml-demos/blob/dcc3d33f0fd2635d18515a62a10da91ae789f080/aie/baml_src/ns_agent/agent.baml)을 읽었다.

- own agent turn 완료 후 supervisor가 **turn delta**만 별도 curator에 넘긴다. 외부 호스트 전체 대화 archive import가 아니다.
- memory는 작은 Markdown file이며 `name`, `keywords`, `body`다. 디렉터리는 `.bamlcode/memory` 또는 환경변수 override다.
- recall은 사용자 메시지를 lexical token으로 score해 상위 기본 3개를 주입한다. memory marker로 같은 history 재주입을 피한다.
- curator는 `claude-haiku-4-5-20251001`의 생성 호출을 사용한다. durable preferences/conventions/commands/decisions만 저장하라는 prompt, guesses/user-unconfirmed/secret 등을 제외하라는 prompt가 있다.
- memory edit는 `save/delete`, turn당 최대 5개이며 save는 같은 이름 overwrite, delete는 파일 제거다. 승인 UI/원문 span 링크/history/tombstone/restore가 이 source의 schema·write path에는 없다. “prompt에서 confirmed만 쓰라 함”과 source-level 승인 권한 enforcement는 다르다.
- 실패는 `curate_turn`의 catch-all에서 빈 edit list로 바뀐다. 이 패턴을 그대로 쓰면 “기억할 것 없음”과 “curation 실패”의 의미가 구분되지 않는다.
- **한국어 반례:** `tokenize`와 `slugify`는 **`is_ascii_alphanumeric()`**를 사용한다. 순수 한국어 query는 토큰이 비어 recall이 빈 배열을 반환할 수 있다. 비-ASCII만으로 된 이름은 공통 `memory` slug로 떨어져 overwrite 충돌 여지도 있다. 이것은 해당 source 경로의 정적 반례이며 한국어 runtime 테스트를 실행한 결과는 아니다.

**판정:** 분리된 write context, local file memory, 자동 turn-end curation/recall/correction/delete를 읽을 수 있는 유용한 교육용 예제다. 그러나 Jev gate+Btel Query+3갈래 추출/보고서+dashboard를 모두 가진 영상 구현이 아니며, raw provenance/선택 승인/규칙 승격/stale/retraction/forget-restore/tenant isolation을 해결한 완제품도 아니다. 특히 영어 lexical 예제의 recall을 한국어 운영 가능성 근거로 대체할 수 없다.

### 7.3 agent feedback와 memory-rule feedback를 혼동하지 않기

**[소스 확인]** 같은 저장소의 별도 [bamlcode README](https://github.com/BoundaryML/baml-demos/blob/dcc3d33f0fd2635d18515a62a10da91ae789f080/bamlcode/README.md)는 `ai.Agent` tool-enabled coding CLI/typed final answer/events/journal/pack 예제다. [agent.baml](https://github.com/BoundaryML/baml-demos/blob/dcc3d33f0fd2635d18515a62a10da91ae789f080/bamlcode/baml_src/ns_agent/agent.baml)의 `events_transcript`는 `ai.events.UserMessage`를 **`[SYSTEM FEEDBACK]`**로 문자열화하고 `agent_steps`는 이를 repair request 수로 센다. 그 source의 feedback 표기는 durable 사용자 정정 저장/선택 승인/규칙 승격 기능의 증거가 아니다. README의 테스트 성공·취소 속도·동시성 수치는 저자 자료이며 이번 담당자가 실행해 확인한 것이 아니다.

### 7.4 TypeSafe basic_memory도 다른 범위다

**[공식 문서/예제]** [basic_memory cookbook](https://docs.typesafe.ai/cookbooks/basic_memory.md)은 Python dict의 customer별 list에 raw request와 `Jev_answered`를 넣고, 다음 call의 routing state에 그 list를 포함하는 toy다. 먼저 routing, 그 뒤 separate lasting-fact gate를 호출하고 gate p≥0.5일 때 저장한다. gate는 Jev 답/암시에만 있는 사실과 이전 기억을 되풀이한 내용으로 자기 강화하지 않도록 prompt를 제한한다. author example은 pinned `jev-1.13.0`, 2026-09-28의 작은 두 고객/6 future-request routing case에서 memory 6/6 vs no-memory 2/6를 보여준다.

문서 스스로 **“memory only grows”**이고 relevance/size/expiry 한계가 있다고 명시한다. 이 toy 숫자는 열린 도메인 사실성·한국어·host 자동 capture·held-out 실제 action·정정 lifecycle·3갈래 pipeline 공개 구현의 검증이 아니다. file-memory 예제와 이 routing-memory toy를 합쳐 공식 episode code가 완전 공개됐다고 결론내릴 수도 없다.

## 8. 독립 OSS/동일 local·self-host pipeline 검토에 미치는 영향

다음은 도구 선택을 강제하는 결론이 아니라 위 증거의 **[설계 추론]**이다.

- **추출과 판정을 분리:** candidate extraction/generation과 작은 Jev-style gate/selection은 서로 다른 비용·오류 모델이다. 특정 공급자가 필수가 되지 않게 후보/확률/원문 provenance/threshold 버전을 명시하는 계약을 잡되, provider 모든 출력을 같은 의미로 간주하지 않는다.
- **capture 계약부터 명시:** MCP만 있는 제품은 호출된 자료만 보고, BAML Query만 있는 제품은 recording된 BAML 실행만 본다. 어떤 host/event/message/tool output을 언제 수집했고 무엇을 누락/잘랐는지가 자동 memory의 원문 범위를 결정한다.
- **raw와 memory authority 분리:** Btel/CAS 같은 원문 기록, 재구축 index, extracted candidate, accepted fact/correction, approved rule/report를 혼동하지 않는다. 원문 ID/span과 상태/정정 관계 없이 정상 typed value만 저장하는 것은 provenance가 아니다.
- **상태 전이는 별도 구현 대상:** stale/retraction/forget/restore와 선택적 승인·규칙 승격은 이번 source에서 end-to-end 완제품으로 확인되지 않았다. 영상 후반 health/stale/fourth-input는 원문상 후속 아이디어와 구현 관찰을 분리해야 한다. 값이 오래됐다고 무조건 삭제하거나 승인 없이 자동 규칙화하는 결론은 도구 문서에서 나오지 않는다.
- **deployment와 의미를 분리:** 회사/외주 고객 local과 개인 self-host cloud에 같은 pipeline 상태/권한/provenance 의미를 유지할 수는 있으나, datasource/credential/egress/tenant/backup·retention 경계는 각각 독립이어야 한다. `--local`, 자체 disk cache, local memory Markdown은 no-egress의 증거가 아니다.
- **한국어와 비용은 같은 pinned 조건으로 측정:** model ID, BAML toolchain, prompt/schema/gate/후처리, cache policy, 가격 snapshot을 고정한다. session당 total fresh tokens/생성 모델 비용/재처리 비용과 held-out 후속 action의 개선·악화·정정 반영을 함께 본다. 영상 자기 데이터 숫자나 toy 6/6로 일반화하지 않는다.
- **유지관리 최소화의 조건:** 전체 agent language/runtime을 선택할 이유는 기존 runtime·typed model orchestration·배포 이점을 실제로 필요로 할 때다. 반대로 raw capture/query의 계약과 상태 전이는 이미 갖춘 host/storage에서도 구현 가능하다. source 공개가 불완전한 episode를 “즉시 설치 가능한 OSS memory 제품”의 출발점으로 소개하지 않는다.

## 9. source ledger와 미확인

### pin한 최소 source의 Git blob 식별자

모두 BAML commit `99edb5d249850ed92db987148feb78f551a93250` 또는 위 별도 demos commit에 고정된 URL로 본문에서 직접 연결했다.

| 읽은 BAML source | Git blob SHA |
|---|---|
| `skills/baml-core/SKILL.md` (관련 첫 부분) | `a23ae0c15373f16d9aed653cee4b040f1fc7e103` |
| `baml_cli/src/query_command.rs` | `03d9ee99fe3d607fe15911f767b93e6504ca2229` |
| `baml_query_btel/src/lib.rs` | `dadcd42ec57370bfc6204f06889147996664cf81` |
| `baml_query_btel/src/store.rs` | `31c8da9b5d6598f54d678c6bd8ad35cea4917c5a` |
| `baml_query_btel/src/catalog.rs` (relation 계약 부분) | `59cff18181cf292c0605159ff13a735f9df77262` |
| `baml_query_btel/tests/host_inputs.rs` | `ebeb26fb977f15e45dc824e5831d747e639e0e36` |
| `btel_recorder/src/lib.rs` (builder/publisher 계약 부분) | `925328661f05b3aa0b0e832b45de839608a9b45a` |
| `btel_file/src/lib.rs` (local delivery 계약 부분) | `0df9360e3783b03db19503073c2b7a45ebd5d24d` |
| `btel_file/src/cas.rs` (publication 부분) | `82c9c19e6153cabca82360ce891707a1320f39b0` |
| `btel_settings/src/mode.rs` | `0b42f5939971a0a5d8561db50374dc10dff08224` |
| `btel_settings/src/policy.rs` | `44b5aaa0f038f722f9b03aa8b64660a1244e388b` |
| `btel_settings/src/network.rs` | `0f2eec965e429e0080551bb07a62acf2fae14304` |
| `baml_language/ENV_VARS.md` | `5deaca1e18db87befbcc8007e410f28b474b9e32` |
| `baml_builtins2/baml_std/typesafeai/ns_internal/jev.baml` | `d82df02873c10999ae2d2aa784fea664a059c9cd` |

| 읽은 별도 demo source (commit `dcc3d33f0fd2635d18515a62a10da91ae789f080`) | Git blob SHA |
|---|---|
| `aie/baml_src/ns_memory/memory.baml` (store/recall/tokenizer 부분) | `a0d4e7041b04f581f1cd8257407a44c2923dacd2` |
| `aie/baml_src/ns_memory/curator.baml` | `4ae287a7c1e2eefdd4d5bfdd079e05b739a8788b` |
| `aie/baml_src/ns_agent/agent.baml` (entry/supervisor 部分) | `06ac67a718867ef6280fb44c4d5228ba126081ca` |
| `aie/baml.toml` | `6429ee9bfb1cad32412bac8360f3eec593c57017` |
| `bamlcode/README.md` | `15e27f6123e56a37219d3244c6d0e8571d34a287` |
| `bamlcode/baml_src/ns_agent/agent.baml` (feedback/journal 部分) | `39169ba2cf422c0bfc43b1941464d5f690a5c8ea` |

mutable web docs의 immutable source revision은 공급자 페이지에서 확보하지 못했다. 따라서 해당 문서는 조사일·명시 모델 버전/last-reviewed/policy 수정일을 적었으며 commit pin과 동등한 재현성을 주장하지 않는다.

**미확인/미실행:** 영상 pipeline 전체 source와 exact model/toolchain/청구 usage; 공식 Demo Code 외 다른 전체 구현 링크; Jev local weights/self-host inference; 한국어 정확도/확률 calibration; cloud/local 실제 runtime 결과 동등성; 자동 host capture 전수 범위; raw log redaction/retention end-to-end 정책; stale/retraction/restore/승격 구현 완결성; native xhigh 두 모델의 새 리뷰. 공급자 문서·코드 읽기만으로 이 항목들이 검증됐다고 주장하지 않는다.
