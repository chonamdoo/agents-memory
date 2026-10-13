# Python MCP 2.x: 같은 localhost endpoint의 modern·legacy 호출 확인

## 결정과 범위

**Python 3.12 + 공식 `mcp==2.3.0`을 서비스 언어·MCP SDK 후보로 채택할 수 있다.** Python으로 MCP `2026-07-28`을 구현하는 데 TypeScript 서버가 선행 조건은 아니다. 호스트 플러그인은 해당 호스트의 언어를 써도 서비스 API와 의미 계약은 하나다. SDK major version과 wire version은 별도 표기한다.

이는 제품 구현 완료 판정이 아니다. 현재 저장소에는 조사·설계 문서만 있다. Python SDK/HTTP 연결의 실측과 Hindsight/PG/실제 Claude·Codex·omp의 제품 연결 증거를 구분한다.

## 공식 근거

- [Python SDK protocol versions](https://py.sdk.modelcontextprotocol.io/protocol-versions/): `Client(..., mode="auto")`는 `server/discover`를 사용하고 구형 서버에서는 initialize로 fallback한다. `mode="legacy"`는 같은 서버와 handshake-era 연결한다. `mode="2026-07-28"`은 버전을 pin하므로 discovery 없이 시작하고 서버 신원·capability가 자동 확인되는 것은 아니다.
- [Python SDK ASGI app](https://py.sdk.modelcontextprotocol.io/run/asgi/): `MCPServer.streamable_http_app()`은 Starlette/ASGI app을 반환한다. 단독 앱은 lifespan을 관리한다. 다른 앱에 mount할 때 top-level lifespan에서 `mcp.session_manager.run()`을 관리해야 한다. localhost Host/Origin 보호는 endpoint 인증을 대체하지 않는다.
- [SDK legacy-clients](https://py.sdk.modelcontextprotocol.io/run/legacy-clients/): 하나의 앱으로 두 protocol era를 제공한다. `stateless_http` 옵션은 legacy 동작의 설정이고 modern 요청의 무상태성은 별도이다.
- [공식 Python SDK v2.3.0 고정 소스](https://github.com/modelcontextprotocol/python-sdk/tree/2118f14f8a19bc158d8a1cf90af58d85d187f849): 조사 시점의 버전·전송 소스 근거. 라이브 문서가 앞으로 변할 수 있으므로 설치 lock과 host matrix를 함께 관리한다.

## 이번 실제 실행

관측 파일: [`local-first-python-wire-observation.json`](local-first-python-wire-observation.json).

- 실제 Python **3.12.13**, 공식 MCP SDK **2.3.0**.
- `MCPServer` 하나, `streamable_http_app(json_response=True)` 하나, uvicorn의 `127.0.0.1` 임시 port 하나.
- 반환 모델은 Pydantic `Note`. 일반 문자열만 반환하는 fake 응답이 아니라 실제 저장 후 읽은 structured content를 비교했다.
- 임시 SQLite에 `public-synthetic-dual-era-note`라는 공개 합성 문자열을 저장했다. DB 선택 실험은 아니며 최종 PostgreSQL의 증거도 아니다.

| 실행 순서 | SDK client mode | 관측 wire version | 결과 |
|---|---|---|---|
| 1 | `2026-07-28` | `2026-07-28` | 합성 note 실제 저장 |
| 2 | `legacy` | `2025-11-25` | 동일 note 본문·ID 정확히 조회 |
| 3 | `auto` | `2026-07-28` | 동일 note 본문·ID 정확히 조회 |
| 4 | 별도 `2026-07-28` client | `2026-07-28` | 동일 note 본문·ID 정확히 조회 |

13개의 실제 HTTP 요청을 관측했다. Modern 요청에는 `Mcp-Method`, 해당 tool의 `Mcp-Name`, protocol header와 namespaced `_meta`가 있었다. Modern 구간의 요청·응답에는 `Mcp-Session-Id`가 없었다. Legacy 구간은 `initialize`·`notifications/initialized`와 session header를 사용했다. Auto 구간은 실제 `server/discover`를 보냈다. 저장·조회 요청은 HTTP 200, legacy initialized notification은 HTTP 202였다. 프로세스 exit **0**, 관측된 wall time **0.91초**. 이 시간은 합성 probe 총 실행 시간이며 제품 latency 예측값이 아니다.

원문 실행 로그의 합성 transport session ID는 관측 JSON에 넣지 않았다. 관측은 header 유무만 보존한다. 회사 코드·사용자 파일·실제 모델 인증 정보를 사용하지 않았다. 임시 script/DB/server는 종료·제거했다.

## 설계 반영

1. 하나의 공식 Python SDK edge에서 modern과 legacy를 처리하고 **같은 domain handler**를 호출한다. 별도 구형 엔진·의미 shim을 만들지 않는다.
2. 제품의 operation/episode/source revision은 MCP transport session ID나 JSON-RPC request ID에 의존하지 않는다.
3. Modern 연결을 쓴다고 tool catalog·description·rule body의 모델 토큰 비용이 사라지지 않는다. 연결 시 corpus/rule body 0, 작은 고정 catalog, 실제 작업에 필요한 bounded context를 별도로 설계한다.
4. pinned mode의 무왕복은 endpoint 인증이나 capability 검증을 생략해도 된다는 뜻이 아니다. 인증된 endpoint identity/host compatibility와 cache invalidation은 별도다.
5. 실제 native 호스트의 HTTP/stdio, hook, compaction·fork·subagent, timeout/retry 동작은 **각각 제품 acceptance scenario에서 검증**한다. Python client가 legacy mode로 통과했다는 사실만으로 omp/Claude/Codex 연결 완료라고 쓰지 않는다.
6. 첫 로컬 제품은 위에서 실행한 Python 3.12 계열을 대상으로 lock한다. OS 기본 Python 3.9에 맞추기 위한 SDK downgrade는 하지 않는다. 실제 지원 Python 최소 버전·dependency 충돌은 packaging milestone에서 pinned metadata로 확정한다.
7. 이후 cloud에서도 같은 ASGI app과 core를 쓰되 개인 deployment의 TLS/IdP/backup을 추가한다. Modern stateless 요청과 legacy in-process session의 scale-out 조건은 다르므로 무조건 다중 replica 호환이라고 주장하지 않는다.

## 아직 이 실행으로 증명하지 않은 것

제품 memory pipeline, PostgreSQL·pgvector, Hindsight, 인증·회사 외부 통신 차단, stale worker fencing, 승인·철회·restore, native host auto invocation, 실제 prompt token 절감, 다국어 memory 품질, cloud 배포. 이 항목들은 설계의 구현·수용 기준에 남긴다.
