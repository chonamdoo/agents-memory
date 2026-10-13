# 신규 Runlayer 영상: 추가 공개 저장소 확인

검사일: 2026-10-12. 이 문서는 동일 입력 적대적 리뷰 packet에 나중에 몰래 추가한 근거가 아니다. 별도 공개 자료 보충 기록이며, 아래 페이지의 당시 내용을 읽었다. 코드를 복사·설치·실행하지 않았고 commit 고정의 완전 재현 감사라고 주장하지 않는다.

## 직접 확인한 범위

- 발표자 [RafalWilinski GitHub](https://github.com/RafalWilinski)는 `@runlayer` 조직 및 `https://rwilinski.ai/`를 직접 연결한다. 고정 저장소에는 일반 Apple Notes/AWS MCP 및 Cloudflare RAG 등이 표시되며, 해당 목록만으로 전체 88개 저장소에 실험 코드가 없다고 판단하지 않는다.
- [Runlayer 조직](https://github.com/runlayer)은 조회 시 공개 저장소 4개를 표시한다: `plugins`, `okta-mcp`, `okta-mcp-server`, `runlayer-deploy-examples`.
- [plugins](https://github.com/runlayer/plugins)의 README에는 Claude Code/Cursor용 MCP-builder/plugin-builder와 Cursor hook의 Runlayer backend 검증, `.env`·MCP 설정 접근 차단을 설명한다. README의 MIT 표기는 확인했지만 실제 hook 구현의 완전한 보안 성질·회사 무반출·새 Skills Extension activation·실험 재현은 검증하지 않았다. 외부 backend 검증 제품의 구조를 그대로 회사 무반출 환경에 넣을 근거가 아니다.
- [runlayer-deploy-examples](https://github.com/runlayer/runlayer-deploy-examples)의 README는 TypeScript `tasks-mcp` 예제의 tools/resources/prompts/stateless Streamable HTTP를 설명한다. 이것은 Chromium/Lambda skill distiller나 36%→100% 실험 코드가 아니다.
- [Runlayer 공식 제품 페이지](https://www.runlayer.com/)는 catalog·identity controls·runtime scans·MCP gateway·skills/memory/workflows를 마케팅한다. 제품 기능 주장과 agents-memory의 권한/승인/취소·격리 E2E 증명은 구분한다.
- [발표자 RSS](https://rwilinski.ai/rss.xml)는 JSON generation/evals/agent principles/RAG 등 8개 글의 제목과 링크를 포함한다. 이 피드 및 위 공개 페이지에서 해당 36%→100% 사례의 표본 수·홀드아웃·성공 판정 oracle·반복 횟수·전체 실패 로그·재현 패키지는 얻지 못했다. 전 세계에 공개 코드가 없다고 증명한 것은 아니다.

## 설계에 미치는 결론

1. transport 배포 예제 및 progressive disclosure 개념은 참고할 수 있으나, 기존 Python/Pydantic/PG core를 갈아엎을 근거가 아니다.
2. Runlayer 발표의 자동 distillation은 후보 생성 아이디어로만 비교한다. 사람의 exact-revision 승인과 host의 별도 실행 동의는 제거하지 않는다.
3. 회사는 third-party backend·query/name/URI/description/telemetry를 포함한 반출을 별도 승인 없이 허용하지 않는다. 회사가 승인한 Claude/Codex 팀 계정은 임의의 외부 gateway나 Jev API에 대한 승인과 같지 않다.
4. 공개 README에 보안 hook이 있다고 모든 클라이언트의 비협조·shell·same-UID 공격을 차단한다고 주장하지 않는다. 기존 agents-memory의 host enforcement 보장 수준과 동일 잣대로, 지원된 경로에서 관찰한 효과만 적는다.

이 기록은 새로운 기능 도입 승인이나 완료된 구현 보고가 아니다.
