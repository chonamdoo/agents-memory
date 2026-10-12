# 부모의 추가 primary 교차 확인 — 2026-10-11

## Hindsight retraction의 정적 반례

직접 읽은 고정 raw source: https://raw.githubusercontent.com/vectorize-io/hindsight/a9eeed77f9bce99d8f97d39a30d3281747300824/hindsight-api-slim/hindsight_api/engine/reflect/retractions.py

`RetractedGrounding.unresolvable`은 cited_count>0이며 모든 cited grounding이 사라진 경우 true다. docstring은 whole-bank import의 fresh IDs를 실제 retract로 오인하면 영구 지식 삭제가 되므로 dangling citations를 prune하고 **prose는 그대로 둔다**고 설명한다. 동시에 모든 작은 grounding이 실제로 retract된 page는 stale sentence가 다음 refresh까지 남는 false negative를 명시한다. 이것은 지정 helper의 정책 확인이지 현재 API의 모든 query·refresh·delete path에서 공격이 성공했다는 runtime 결과가 아니다. 영상형 제품이 즉시 derived 기억 철회를 보장하려면 읽기 eligibility와 provenance repair/re-grounding 권위를 따로 입증해야 한다.

## 현재 Codex 공식 hook 계약

직접 읽은 https://learn.chatgpt.com/docs/hooks.md 의 support 문구:
- command와 mcp_tool 지원; prompt/agent handlers는 parsed but skipped.
- SessionStart MCP tool hook은 server ready 전에 실행될 수 있고 session을 block하지 않음. SessionEnd는 MCP tool hook 미지원.
- Work Cloud with local access/dots는 admin-managed remote MCP hooks. 개인 계정/Work Cloud without local access는 이 enterprise hooks를 쓰지 않음; local configuration/plugin/local-directory/command hooks를 cloud orchestration으로 확대하면 안 됨.
- hosted WebSearch는 local-function Pre/PostToolUse hooks를 거치지 않음.
- transcript_path는 string|null; subagent session_id는 parent session ID.
- additionalContext는 developer context로 들어갈 수 있음. 원문/source의 권위가 developer instruction이 됐다는 뜻은 아님.

이 계약을 읽었고 host capture/메모리 연결·행동을 실행한 것은 아니다. binary/version/실제 wire capability는 제품 acceptance가 필요하다.

## 현재 Claude Code startup 경계 — HTTP handler와 HTTP 호출 구별

직접 검색해 읽은 https://code.claude.com/docs/en/hooks 의 문구:
- launch SessionStart(`--continue`/`--resume` 포함)와 Setup은 MCP server가 ready 전이므로 mcp_tool hooks를 skip. /clear나 compaction 뒤의 SessionStart는 조건이 다름.
- `SessionStart`/`Setup`은 **command와 mcp_tool만 지원**하고 http/prompt/agent handler는 지원하지 않음.

따라서 portability 문서의 '준비된 로컬 HTTP 처리 경로'는 **SessionStart command handler가 허용된 HTTP client 요청을 하는 구현**이라면 가능하지만, `type:http` hook 하나를 SessionStart에 등록하는 뜻이라면 틀리다. localhost service가 있다는 이유로 ready를 자동 보장하지 않는다. transcript 비동기 지연·SubagentHandback·누락 이벤트·context spill 제한은 별도 계약이다.

## TypeSafe confidence의 의미

직접 읽은 https://docs.typesafe.ai/confidence.md 의 본문은 Choice/Score confidence를 probability distribution의 concentration statistic으로 설명한다. Noul은 별도 confidence가 없으며 p≈0.5는 uncertainty다. 예시 threshold는 위험/domain/실제 성능에 맞춰 검증해야 하는 수치다. 문서의 'high confidence act automatically' 예시를 임의 기업 규칙의 승인 권위나 확정 진실성으로 읽으면 안 된다. 같은 docs에서 high-stakes transfer 예시는 confirmation을 남긴다.

모델 API를 호출하지 않았고 한국어 calibration·행동 개선·실제 costs·runtime 도구 동등성은 확인하지 않았다.
