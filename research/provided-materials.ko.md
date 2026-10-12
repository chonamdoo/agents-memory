# 제공 자료 판독 — 2026-10-11

## 범위

#316 본문과 댓글 4개를 읽었다. 현재 agent-memory-mcp 디렉터리는 시작 시 비어 있었다. 구현한 메모리 서비스가 있다는 전제는 두지 않는다. Agent Flow 코어 불편입이라는 기존 판단과 새 cross-device/cloud memory 수요는 분리한다.

첨부 이미지 4장을 직접 열었다. 이미지1은 Mac Claude Code/Codex → 로컬 MCP/outbox → Cloud Run API → GCS 원문/Cloud Tasks → Worker/Vertex embedding → Neo4j Aura, Scheduler reconcile, Mac에서 암호화 후 별도 backup bucket 그림이다. 이미지2–4는 LangChain 발표의 trace→memory 루프·read/write cycle·LangSmith Engine/Context Hub 슬라이드다. 화면은 설계 설명이며 서비스 배포/보안/성능의 증거가 아니다.

## 영상1

- https://www.youtube.com/watch?v=0kVsv2WlL44
- 제목: [한영자막] AI 에이전트에 학습하는 메모리를 제공해 보세요 — Jake Broekhuizen, LangChain; 15:28, 업로드 2026-10-11. 직접 reader로 메타데이터 확인.
- 한국어 재업로드 원본 자막은 reader에서 확보하지 못했다. 영어 원본 https://www.youtube.com/watch?v=KGFyOtl5ktI 의 공개 자동 전사 https://ainotes.us/summary/giving-ai-agents-memory-that-learns-jake-broekhuizen-langchain 를 발화 부분과 AI summary를 구분해 읽었다. 재업로드와 영어 원본의 전체 편집/시각 일치는 검증하지 않았다.
- 발표자 공식 글 https://www.langchain.com/blog/how-to-give-your-agent-memory (2026-06-24)을 직접 대조. capture traces → diagnose → selectively update durable context. 많은 trace는 history/eval/code/tool-schema 수정으로 남겨야 하며, runtime refresh 경로 없이는 저장된 update가 다음 run에 전달되지 않는다.
- 영어 전사 14:54의 약75%는 발표자의 경험적 표현; 제품 정확도/개선율의 실측으로 쓰지 않는다. human-in-loop 권고와 우리가 선택한 승인 정책도 구분한다.

## 영상2

- https://www.youtube.com/watch?v=aimqSS7qoIU&t=3993s (1:06:33)
- 제목: 현업 메타 AI 엔지니어 유튜브 라이브 합니다. 무엇이든 물어보세요!; 1:32:39, 업로드 2026-10-10.
- reader와 일반 timedtext endpoint는 원문을 제공하지 않았다. 실제 Chromium YouTube 페이지에서 제목/설명/한국어 자동자막 track 존재를 확인하고 Show transcript를 열었다. modern transcript panel의 렌더링된 한국어 자동 전사를 추출했다. 원문 보존: video-aimqSS7qoIU.transcript.txt, 62,818자(panel UI의 timestamp/accessibility text 포함). 자동인식 오타를 수동 교정한 완전 전사라고 주장하지 않는다. 해당 시점 화면도 직접 확인했으며 첨부 이미지1의 클라우드 그림과 일치한다.

| 실제 자동자막 시각 | 확인된 내용 | 적용/한계 |
|---|---|---|
| 1:03:37–1:05:15 | 로컬 기억 저장·recall·reflect 설명; reflect 상세는 발표자가 자세히 모른다고 말함 | 기능 의미는 Hindsight 공식 docs/source로 별도 검증 |
| 1:05:22–1:06:45 | MacBook/Mac mini/cloud agent가 함께 접근하도록 cloud로 이동, Neo4j Aura project/task/claim/source/event/entity/artifact, MCP를 통해 먼저 기억 조회 | 이동성 요구에 부합; MCP가 자동 세션 전체 수집하는 것은 아님 |
| 1:06:53–1:08:23 | 개인 multi-device뿐 아니라 팀 공유, Cloud Run API/Tasks/worker | 팀 권한 분리는 그림만으로 증명 안 됨 |
| 1:08:23–1:09:48 | embeddings·cosine·BM25·raw source archive | retrieval 기술 설명, 성능 측정 아님 |
| 1:11:41–1:13:44 | 접수/반영/조회 가능 구별, keyword+semantic RRF, success/empty/partial/unavailable 상태 | accepted≠queryable 및 장애≠검색결과없음 계약에 재사용 |
| 1:13:56 | 철회·삭제표지·물리적 삭제, purge는 안한다고 표현 | hard deletion 구현 완료/개인정보 완전 삭제 보장 금지 |
| 1:14:03–1:15:00 | evaluation이 가장 어렵다; 특정 프로젝트를 만들었다는 사실을 좋아한다는 선호로 잘못 일반화하면 안 됨 | 한국어 negation/조건/scope 및 false preference promotion 평가 |
| 1:17:25–1:18:14 | 공유 cloud memory를 설명하면서 아직 옛 기억 상자 사용, migration 중·키 누락·기기 간 정보 불일치 언급 | production complete 사례가 아님; identity/consumer migration/health probe 필요 |

공개 원본 구현 repo/commit과 화면의 실제 배포 상태를 연결하는 근거는 확보하지 못했다. 사용자 제공 아키텍처를 그대로 채택하지 않고 표준·공식 클라우드 동작·다른 공개 구현과 대조한다.
