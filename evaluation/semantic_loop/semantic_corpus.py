"""Frozen semantic queries for the meaning-level retrieval loop.

The claims are exactly the claims of evaluation/retrieval_loop/corpus.py (dev and holdout,
same 1x/5x/20x background), so the cached PostgreSQL loads are reused. Only the queries
differ: they ask for a stored fact in other words, avoiding the fact's own key tokens where
the language allows. Labels are by construction (each query names the fact it paraphrases).

Groups:
  S1 paraphrase in the same language        S2 synonym, hypernym or related concept
  S3 cross-language, no expansions          S4 descriptive or indirect question
  S5 old and new versions (both gold)       S6 negation or condition asked indirectly
  S8 semantically near but unanswered (no gold)
The keyword queries of the lexical loop (groups G1-G9) are measured too, as a
non-regression set, by reusing corpus.Query objects unchanged.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "retrieval_loop"))

from corpus import CORPORA, Corpus, Query  # noqa: E402

SEMANTIC_GROUPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S8")

DEV = {
    "g1a": [("S1", "결제 실패 시 다시 시도하는 최대 횟수 기본 설정"), ("S3", "default number of payment retry attempts"),
            ("S4", "카드 승인이 실패하면 몇 번까지 자동으로 다시 해 보나")],
    "g1b": [("S1", "원장 기록을 디스크로 내보내는 주기 운영값"), ("S3", "how often does the ledger writer flush in production")],
    "g1c": [("S2", "중복 처리 방지 키가 없는 환불 메시지는 어떻게 되나"), ("S3", "refund worker rejects messages without a dedup key")],
    "g1d": [("S1", "정산 배치를 데이터베이스에 반영하지 않고 시험 실행하는 옵션"), ("S3", "settlement batch simulation mode without writing")],
    "g1e": [("S1", "원화 금액 반올림 처리 방식"), ("S3", "how are Korean won amounts rounded")],
    "g1f": [("S2", "결제 서비스 데이터베이스 커넥션 풀 최대치"), ("S3", "maximum database connection pool size for payments")],
    "g1g": [("S2", "웹훅 재전송 공격을 막는 시간 제한"), ("S3", "webhook replay protection time window")],
    "g2a": [("S1", "배포 변경 사항 정리 문서는 누가 언제 쓰나"), ("S3", "who writes the release notes and on which day"),
            ("S4", "이번 주 출시 내용 정리는 누구 담당이야")],
    "g2b": [("S2", "포스트모템에 반드시 넣어야 하는 항목"), ("S3", "what must every incident postmortem include")],
    "g2c": [("S1", "되돌리기 절차는 출시 전에 연습한다"), ("S3", "rehearse the rollback before deploying")],
    "g2d": [("S2", "고객 안내문 발송 전 CS 확인"), ("S3", "customer notices need support team sign-off before sending")],
    "g2e": [("S1", "미팅 기록은 언제 공유 폴더에 올리나"), ("S3", "when are meeting minutes uploaded to the shared drive"),
            ("S4", "회의 끝나고 기록은 바로 올려야 해")],
    "g2f": [("S2", "glossary 에서 승인의 영어 표기"), ("S3", "how is 승인 translated in the payment glossary")],
    "g3a": [("S1", "출시 전에 태그에 서명이 있어야 하나"), ("S2", "릴리스 태그 전자서명 필수 여부"),
            ("S4", "배포하기 전에 깃 태그는 어떻게 해야 해")],
    "g3b": [("S1", "스테이징 데이터베이스는 언제 초기화되나"), ("S2", "검증 환경 DB 리셋 요일과 시각"),
            ("S4", "월요일 아침에 스테이징 데이터가 사라진 이유")],
    "g3c": [("S1", "결제 대행사 응답이 없으면 자동으로 환불되나"), ("S2", "PG 타임아웃 시 자동 환불까지 걸리는 시간")],
    "g3d": [("S1", "특정 시점 복구를 위한 로그 보관 기간"), ("S3", "how long is WAL retained for point in time recovery")],
    "g3e": [("S1", "오래된 기능 토글은 언제 지워야 하나"), ("S2", "피처 스위치 정리 기준")],
    "g4a": [("S1", "출시 승인에 필요한 검토자 인원"), ("S3", "how many reviewers must approve a deployment")],
    "g4b": [("S1", "프로덕션 스키마 변경은 무슨 요일에 하나"), ("S3", "when can production schema migrations run")],
    "g4c": [("S2", "결제 API 지연 SLO"), ("S3", "payment API latency target")],
    "g4d": [("S2", "PAN 이 찍힌 로그 처리 방법"), ("S3", "card numbers in logs must be masked")],
    "g4e": [("S2", "릴리스 버전 매기는 규칙"), ("S3", "versioning scheme for release documents")],
    "g5a": [("S1", "정산 하루 마감은 몇 시"), ("S3", "daily settlement cutoff time")],
    "g5b": [("S1", "API 레퍼런스는 어떤 언어로 작성하나"), ("S3", "default language of the API docs")],
    "g5c": [("S2", "필요한 Postgres 메이저 버전"), ("S3", "which PostgreSQL version is required")],
    "g5d": [("S1", "부분 환불 금액 상한"), ("S3", "can a partial refund exceed the original charge"),
            ("S4", "결제한 것보다 더 많이 돌려줘도 되나")],
    "g5e": [("S2", "HTTPS 종단은 어느 프록시에서 하나"), ("S3", "where is TLS terminated")],
    "g6a1": [], "g6a2": [],
    "g6b1": [], "g6b2": [],
    "g6c1": [], "g6c2": [],
    "g7a": [("S6", "온라인일 때는 결제 캐시를 디스크에 안 쓰나"), ("S3", "is the payment cache persisted to disk when online")],
    "g7b": [("S6", "주말 직전 오후에 프로덕션 출시 가능한가"), ("S3", "can we deploy to production on Friday afternoon")],
    "g7c": [("S6", "테스트용 카드로 결제하면 실제로 돈이 나가나"), ("S3", "do test cards create real charges")],
    "g7d": [("S6", "핫픽스를 혼자 머지해도 되는 조건"), ("S3", "when may an emergency fix be merged without review")],
    "g7e": [("S6", "미팅 기록에 고객 이름을 적어도 되나"), ("S3", "can customer names appear in meeting notes")],
}
DEV_VERSIONS = [
    (("g6a1", "g6a2"), [("S5", "카드 결제 재시도 정책이 어떻게 바뀌었나"), ("S5", "how many times do we retry payments now")]),
    (("g6b1", "g6b2"), [("S5", "PR 병합에 필요한 승인 수 변경 이력"), ("S5", "how many approvals does a merge need")]),
    (("g6c1", "g6c2"), [("S5", "데이터베이스 연결 대기 한도 변경"), ("S5", "database connection timeout value")]),
]
DEV_NO_MATCH = ["결제 수수료율은 얼마인가", "환불 정책의 고객 귀책 기준", "배포 파이프라인 캐시 만료 시간",
                "데이터베이스 읽기 복제본 개수", "회의실 예약 규칙", "카드사 정산 주기"]

HOLDOUT = {
    "h1a": [("S1", "색인 병합 비율 기본 설정"), ("S3", "default merge factor of the index compactor")],
    "h1b": [("S1", "검색 조건 절 개수 상한을 넘으면"), ("S3", "what happens when a query has too many clauses")],
    "h1c": [("S1", "스냅샷을 S3 에 올릴 때 조각 크기"), ("S3", "multipart chunk size for snapshot uploads")],
    "h1d": [("S1", "전체 재색인 스크립트의 시작일 옵션 형식"), ("S3", "date format for the reindex since option")],
    "h1e": [("S2", "원격 빌드 캐시를 켜는 환경"), ("S3", "where is the remote Gradle build cache enabled")],
    "h2a": [("S1", "신입이 첫 주에 멘토와 보는 문서"), ("S3", "when do new hires read the onboarding guide"),
            ("S4", "입사하면 처음에 뭘 같이 읽어")],
    "h2b": [("S1", "고객 질문에 답해야 하는 시한"), ("S3", "response deadline for customer inquiries")],
    "h2c": [("S1", "새 직원 노트북은 언제까지 준비"), ("S3", "laptops for new hires must be ready before day one")],
    "h2d": [("S2", "환불은 CS 가 아니라 어느 부서가 처리"), ("S3", "which team processes refund requests")],
    "h3a": [("S1", "앱 오류 보고는 언제 전송되나"), ("S2", "크래시 로그 업로드 네트워크 조건"),
            ("S4", "모바일 데이터에서는 크래시 리포트가 안 올라가나")],
    "h3b": [("S1", "모바일 빌드에서 설정 캐시 사용 여부"), ("S2", "그래들 구성 캐시")],
    "h3c": [("S1", "상담 템플릿 검토 주기"), ("S2", "CS 매크로는 분기마다 점검")],
    "h3d": [("S1", "동의어 확장은 색인할 때가 아니라 검색할 때"), ("S3", "is the synonym filter applied at index time")],
    "h4a": [("S1", "스토어 심사 제출 전에 필요한 품질 승인"), ("S3", "app store submission requires QA sign-off")],
    "h4b": [("S1", "검색 색인을 처음부터 다시 만드는 시점"), ("S3", "when is a full index rebuild scheduled")],
    "h4c": [("S2", "CSAT 목표 점수"), ("S3", "customer satisfaction target score")],
    "h4d": [("S1", "입사 한 달 뒤 보내는 설문"), ("S3", "when is the onboarding survey sent")],
    "h5a": [("S1", "색인 작업 한 번에 처리하는 문서 수"), ("S3", "indexing batch size")],
    "h5b": [("S2", "API 레퍼런스 생성 도구"), ("S3", "how are API docs generated")],
    "h5c": [("S1", "에러 비율이 얼마면 경보가 울리나"), ("S3", "alert threshold on error rate")],
    "h5d": [("S2", "리저브드 인스턴스 계약 기간"), ("S3", "reserved instance commitment term")],
    "h6a1": [], "h6a2": [], "h6b1": [], "h6b2": [],
    "h7a": [("S6", "베타 테스터에게도 알림을 보내나"), ("S3", "do beta users receive push notifications")],
    "h7b": [("S6", "품질 검토 없이 동의어 목록을 바꿔도 되나"), ("S3", "when may the synonym dictionary be updated")],
    "h7c": [("S6", "중요 고객 문의에 자동 답변을 써도 되나"), ("S3", "can canned replies be used for VIP customers")],
}
HOLDOUT_VERSIONS = [
    (("h6a1", "h6a2"), [("S5", "검색 요청 제한 시간 변경"), ("S5", "current search timeout")]),
    (("h6b1", "h6b2"), [("S5", "고객센터 근무 시간 변경"), ("S5", "support hours now")]),
]
HOLDOUT_NO_MATCH = ["검색 결과 캐시 만료 시간", "앱 다크 모드 지원 여부", "상담원 교대 근무 규칙", "색인 샤드 복제 개수"]


def semantic(split: str) -> Corpus:
    """Claims of the lexical corpus; semantic queries first, then the lexical queries for non-regression."""
    base = CORPORA[split]()
    table, versions, no_match = (DEV, DEV_VERSIONS, DEV_NO_MATCH) if split == "dev" else (
        HOLDOUT, HOLDOUT_VERSIONS, HOLDOUT_NO_MATCH)
    known = {claim.key for claim in base.claims}
    queries: list[Query] = []

    def ask(group, text, gold):
        assert set(gold) <= known, gold
        index = sum(query.group == group for query in queries)
        queries.append(Query(f"{split}-{group}-{index:02d}", group, "semantic", text, tuple(gold)))

    for key, items in table.items():
        for group, text in items:
            ask(group, text, (key,))
    for gold, items in versions:
        for group, text in items:
            ask(group, text, gold)
    for text in no_match:
        ask("S8", text, ())
    base.queries = queries + base.queries
    return base


SEMANTIC = {"dev": lambda: semantic("dev"), "holdout": lambda: semantic("holdout")}
