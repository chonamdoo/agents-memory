"""Frozen synthetic corpora for the candidate-ranking loop.

Labels are by construction: each query lists the claim keys a reader needs from this corpus.
Dev (payments, release documents, DB infrastructure, meeting notes) and holdout (search
indexing, onboarding, mobile build, customer support) use disjoint domains and vocabularies.
The loop must not edit this file; harness.py refuses to run when its digest changes.

Groups: G1 code identifiers, G2 Korean particles/endings, G3 Korean/English mixed (every
query appears once without and once with agent expansions), G4 short facts among long
documents, G5 one project with many concurrent tasks sharing vocabulary, G6 old and new
versions without a supersede edge (both are gold), G7 negation/conditions, G8 no-match, G9
keyword-stuffed decoys. Scope/integrity is tests/test_retrieval_integrity.py.

Each gold fact has two or three queries mixing four forms: keyword, natural, fragment
(identifier or word piece) and typo. Background chatter is generated at 1x, 5x and 20x the
core claim count to measure crowding. Every body is one sentence so it yields one span.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

FORMS = ("keyword", "natural", "fragment", "typo")
SCALES = (1, 5, 20)


@dataclass(frozen=True)
class Claim:
    key: str
    body: str
    subject: str
    predicate: str
    object: str
    entities: tuple[str, ...] = ()


@dataclass(frozen=True)
class Query:
    id: str
    group: str
    form: str
    text: str
    gold: tuple[str, ...]
    expansions: tuple[str, ...] = ()


@dataclass
class Corpus:
    name: str
    claims: list[Claim] = field(default_factory=list)
    queries: list[Query] = field(default_factory=list)
    background: list[Claim] = field(default_factory=list)

    def fact(self, group, key, body, subject, predicate, obj, entities, *queries):
        self.claims.append(Claim(key, body, subject, predicate, obj, tuple(entities)))
        for form, text in queries:
            self.ask(group, form, text, key)

    def ask(self, group, form, text, *gold, expansions=()):
        assert form in FORMS
        index = sum(query.group == group for query in self.queries)
        self.queries.append(Query(f"{self.name}-{group}-{index:02d}", group, form, text, tuple(gold), tuple(expansions)))

    def mixed(self, key, body, subject, predicate, obj, entities, *queries):
        """G3: each (form, text, expansions) is asked twice, without and with expansions."""
        self.claims.append(Claim(key, body, subject, predicate, obj, tuple(entities)))
        for form, text, expansions in queries:
            self.ask("G3", form, text, key)
            self.ask("G3", form, text, key, expansions=expansions)

    def long(self, key, topic, words):
        self.claims.append(Claim(key, f"{topic} 문서에는 {words} 등 여러 논의가 길게 정리되어 있다.",
                                 topic, "summarizes", "discussion", (topic,)))

    def decoys(self, terms, count, seed):
        rng = random.Random(seed)
        fillers = ["회의록", "메모", "링크 모음", "논의 목록", "참고 자료", "체크리스트 초안", "회고 노트"]
        for index in range(count):
            picked = rng.sample(terms, k=min(len(terms), 9))
            body = f"{rng.choice(fillers)} {' '.join(picked)} {' '.join(rng.sample(picked, 5))} 관련 내용 정리."
            self.claims.append(Claim(f"decoy{index:02d}", body, picked[0], "mentions", "notes", (picked[0],)))

    def chatter(self, project, tasks, topics, artifacts, verbs, seed):
        """Concurrent-task background, 20x the core claims; a scale takes its prefix."""
        rng = random.Random(seed)
        for index in range(len(self.claims) * max(SCALES)):
            task, topic, artifact, verb = (rng.choice(tasks), rng.choice(topics), rng.choice(artifacts), rng.choice(verbs))
            self.background.append(Claim(f"bg{index:04d}", f"{project} {task} 작업에서 {topic} 관련 {artifact}를 {verb}.",
                                         task, verb, artifact, (project,)))

    def at_scale(self, scale: int) -> list[Claim]:
        return self.claims + self.background[:len(self.claims) * scale]


def dev() -> Corpus:
    c = Corpus("dev")
    # G1 code identifiers (payments service)
    c.fact("G1", "g1a", "PaymentRetryPolicy.maxAttempts 기본값은 3이다.", "PaymentRetryPolicy.maxAttempts", "default", "3",
           ("PaymentRetryPolicy.maxAttempts",),
           ("fragment", "maxAttempts 기본값"), ("keyword", "PaymentRetryPolicy maxAttempts"), ("typo", "maxAtempts 기본"))
    c.fact("G1", "g1b", "LedgerWriter.flushIntervalMs 는 운영에서 250으로 둔다.", "LedgerWriter.flushIntervalMs", "sets", "250",
           ("LedgerWriter.flushIntervalMs",),
           ("fragment", "flushIntervalMs 운영 값"), ("natural", "LedgerWriter 는 얼마마다 flush 하나"))
    c.fact("G1", "g1c", "refund_queue_worker 는 idempotency_key 없이 메시지를 처리하지 않는다.", "refund_queue_worker",
           "requires", "idempotency_key", ("refund_queue_worker", "idempotency_key"),
           ("fragment", "refund_queue idempotency"), ("keyword", "refund_queue_worker idempotency_key"),
           ("typo", "refund_queue_wroker 멱등키"))
    c.fact("G1", "g1d", "settlement-batch CLI 의 --dry-run 플래그는 DB 쓰기를 건너뛴다.", "settlement-batch", "skips",
           "DB writes", ("settlement-batch",),
           ("keyword", "settlement-batch dry-run"), ("natural", "정산 배치를 DB 에 안 쓰고 돌리는 방법"))
    c.fact("G1", "g1e", "CurrencyRounder.roundHalfEven 은 KRW 에서 소수점을 버린다.", "CurrencyRounder.roundHalfEven", "truncates",
           "KRW 소수점", ("CurrencyRounder.roundHalfEven", "KRW"),
           ("fragment", "roundHalfEven KRW"), ("natural", "원화 반올림은 소수점을 어떻게 처리하나"))
    c.fact("G1", "g1f", "PAYMENTS_DB_POOL_MAX 환경변수의 상한은 32다.", "PAYMENTS_DB_POOL_MAX", "max", "32",
           ("PAYMENTS_DB_POOL_MAX",),
           ("keyword", "PAYMENTS_DB_POOL_MAX"), ("fragment", "DB_POOL_MAX 상한"), ("typo", "PAYMENT_DB_POOL_MAX 최대"))
    c.fact("G1", "g1g", "webhookSignatureVerifier 는 5분 넘은 timestamp 를 거부한다.", "webhookSignatureVerifier",
           "rejects", "old timestamp", ("webhookSignatureVerifier",),
           ("fragment", "SignatureVerifier timestamp"), ("natural", "웹훅 서명 검증에서 오래된 요청은 어떻게 되나"))
    # G2 Korean prose, particles and endings differ between claim and query
    c.fact("G2", "g2a", "릴리스 노트는 배포 담당자가 매주 금요일에 작성한다.", "릴리스 노트", "작성", "금요일", ("릴리스 노트",),
           ("natural", "릴리스 노트를 누가 작성하나"), ("keyword", "릴리스노트 작성 요일"), ("typo", "릴리즈 노트 작성자"))
    c.fact("G2", "g2b", "장애 회고 문서에는 재발 방지 항목을 반드시 적는다.", "장애 회고", "포함", "재발 방지", ("장애 회고",),
           ("natural", "장애 회고에 꼭 들어가야 하는 것"), ("keyword", "회고 재발방지"))
    c.fact("G2", "g2c", "릴리스 체크리스트의 롤백 항목은 배포 전에 리허설한다.", "릴리스 체크리스트", "리허설", "롤백",
           ("릴리스 체크리스트",),
           ("natural", "롤백은 언제 연습해야 하나"), ("keyword", "체크리스트 롤백 리허설"), ("typo", "롤벡 리허설"))
    c.fact("G2", "g2d", "변경 공지문은 고객지원팀의 검토가 끝나야 발송한다.", "변경 공지문", "발송 조건", "고객지원팀 검토",
           ("변경 공지문",),
           ("natural", "변경 공지를 보내기 전에 누구 검토를 받나"), ("keyword", "공지문 발송 검토"))
    c.fact("G2", "g2e", "회의록은 회의가 끝난 당일에 공유 드라이브에 올린다.", "회의록", "업로드", "당일", ("회의록",),
           ("natural", "회의록을 언제 올려야 하나"), ("keyword", "회의록 업로드 시점"), ("typo", "회의룩 올리는 날"))
    c.fact("G2", "g2f", "결제 용어집에서는 승인을 authorization 으로 번역한다.", "결제 용어집", "번역", "authorization",
           ("결제 용어집",),
           ("natural", "용어집에서 승인은 어떻게 번역하나"), ("keyword", "결제 용어 승인 번역"))
    # G3 Korean/English mixed wording
    c.mixed("g3a", "Signed tags are required before publishing a release.", "release", "requires", "signed tag",
            ("release",),
            ("natural", "릴리스 배포 전에 서명된 태그가 필요한가", ("signed tag", "release publishing")),
            ("keyword", "릴리스 서명 태그", ("signed tags", "release")))
    c.mixed("g3b", "The staging database is reset every Monday at 09:00 KST.", "staging database", "reset", "Monday",
            ("staging database",),
            ("keyword", "스테이징 DB 초기화 주기", ("staging database reset",)),
            ("typo", "스테이징 데이타베이스 리셋", ("staging database",)))
    c.mixed("g3c", "Payment gateway timeouts trigger an automatic refund after 10 minutes.", "payment gateway",
            "triggers", "automatic refund", ("payment gateway",),
            ("natural", "결제 게이트웨이 타임아웃이 나면 환불이 되나", ("gateway timeout", "automatic refund")))
    c.mixed("g3d", "DB 백업은 point-in-time recovery 를 위해 WAL 을 7일 보관한다.", "DB 백업", "retains", "WAL 7일",
            ("DB 백업", "WAL"),
            ("keyword", "PITR WAL 보관 기간", ("point-in-time recovery", "WAL retention")),
            ("fragment", "백업 WAL", ("WAL",)))
    c.mixed("g3e", "Feature flags older than two sprints should be removed.", "feature flags", "remove", "two sprints",
            ("feature flags",),
            ("natural", "오래된 피처 플래그는 언제 지우나", ("feature flags remove",)))
    # G4 short facts among long documents that mention the same words
    c.fact("G4", "g4a", "배포 승인은 두 명 이상의 리뷰어가 필요하다.", "배포 승인", "필요", "리뷰어 두 명", ("배포 승인",),
           ("natural", "배포 승인에 필요한 리뷰어 수"), ("keyword", "배포 승인 조건"))
    c.fact("G4", "g4b", "운영 DB 마이그레이션은 화요일 오전에만 실행한다.", "운영 DB 마이그레이션", "실행 시점", "화요일 오전",
           ("운영 DB 마이그레이션",),
           ("natural", "운영 DB 마이그레이션은 언제 실행하나"), ("typo", "마이그레이숀 실행 요일"))
    c.fact("G4", "g4c", "결제 API 응답 시간 목표는 p95 300ms 다.", "결제 API 응답 시간", "목표", "p95 300ms",
           ("결제 API 응답 시간",),
           ("keyword", "결제 API p95 목표"), ("natural", "결제 API 는 얼마나 빨라야 하나"))
    c.fact("G4", "g4d", "카드번호가 포함된 로그는 마스킹한 뒤 저장한다.", "카드번호 로그", "저장 조건", "마스킹", ("카드번호 로그",),
           ("keyword", "카드번호 로그 마스킹"), ("natural", "카드 번호가 찍힌 로그는 어떻게 저장하나"))
    c.fact("G4", "g4e", "릴리스 문서의 버전 번호는 SemVer 를 따른다.", "릴리스 문서", "버전 규칙", "SemVer", ("릴리스 문서", "SemVer"),
           ("keyword", "릴리스 버전 번호 규칙"), ("fragment", "SemVer"))
    c.long("g4long0", "배포 프로세스 개편 회의",
           "배포 승인 리뷰어 배포 일정 배포 체크리스트 롤백 계획 배포 담당 승인 절차 리뷰 요청 배포 창 공지")
    c.long("g4long1", "DB 운영 회고", "운영 DB 마이그레이션 실행 순서 백업 확인 마이그레이션 스크립트 리뷰 실행 로그 운영 점검 화요일 일정")
    c.long("g4long2", "결제 성능 개선 스프린트 정리",
           "결제 API 응답 시간 측정 p95 p99 대시보드 캐시 개선 응답 지연 원인 분석 목표 재설정 부하 테스트")
    c.long("g4long3", "결제 보안 점검 결과 공유", "카드번호 로그 저장 정책 마스킹 대상 접근 권한 감사 로그 저장 기간 점검 항목 후속 조치")
    c.long("g4long4", "릴리스 문서 템플릿 논의", "릴리스 문서 버전 번호 변경 이력 SemVer 예외 태그 이름 배포 노트 형식 검토 순서")
    # G5 one payments project with many concurrent tasks sharing vocabulary
    c.fact("G5", "g5a", "pay-core 정산 작업에서 정산 마감 시각은 23시 30분으로 정했다.", "정산 마감", "fixed", "23시 30분",
           ("pay-core",),
           ("keyword", "정산 마감 시각"), ("natural", "pay-core 정산은 몇 시에 마감하나"), ("typo", "정산 마깜 시간"))
    c.fact("G5", "g5b", "pay-core 문서 작업에서 API 문서는 한국어를 기본으로 쓴다.", "API 문서", "language", "한국어",
           ("pay-core",),
           ("keyword", "API 문서 언어"), ("natural", "pay-core 문서는 어떤 언어로 쓰나"))
    c.fact("G5", "g5c", "pay-core 인프라 작업에서 PostgreSQL 18 을 필수로 정했다.", "PostgreSQL", "requires", "18",
           ("pay-core", "PostgreSQL"),
           ("keyword", "필수 PostgreSQL 버전"), ("fragment", "Postgres 18"))
    c.fact("G5", "g5d", "pay-core 환불 작업에서 부분 환불은 원 결제 금액을 넘을 수 없다.", "부분 환불", "limit", "원 결제 금액",
           ("pay-core",),
           ("keyword", "부분 환불 한도"), ("natural", "부분 환불을 원래 금액보다 많이 할 수 있나"), ("typo", "부분 활불 한도"))
    c.fact("G5", "g5e", "pay-core 배포 작업에서 Caddy 가 TLS 를 종료한다.", "Caddy", "terminates", "TLS", ("pay-core", "Caddy"),
           ("natural", "TLS 종료는 어디서 하나"), ("keyword", "pay-core 배포 TLS"))
    # G6 old and new versions, both needed so the reader can see the change
    c.fact("G6", "g6a1", "결제 재시도 횟수는 5회다.", "결제 재시도", "횟수", "5회", ("결제 재시도",))
    c.fact("G6", "g6a2", "결제 재시도 횟수를 3회로 줄였다.", "결제 재시도", "횟수", "3회", ("결제 재시도",))
    c.ask("G6", "keyword", "결제 재시도 횟수", "g6a1", "g6a2")
    c.ask("G6", "natural", "결제는 몇 번까지 재시도하나", "g6a1", "g6a2")
    c.ask("G6", "typo", "결재 재시도 몇 회", "g6a1", "g6a2")
    c.fact("G6", "g6b1", "코드 리뷰는 한 명 승인으로 머지할 수 있다.", "코드 리뷰", "머지 조건", "한 명", ("코드 리뷰",))
    c.fact("G6", "g6b2", "코드 리뷰 머지 조건이 두 명 승인으로 바뀌었다.", "코드 리뷰", "머지 조건", "두 명", ("코드 리뷰",))
    c.ask("G6", "keyword", "코드 리뷰 머지 조건", "g6b1", "g6b2")
    c.ask("G6", "natural", "머지하려면 승인이 몇 명 필요하나", "g6b1", "g6b2")
    c.fact("G6", "g6c1", "DB 커넥션 타임아웃은 30초다.", "DB 커넥션 타임아웃", "값", "30초", ("DB 커넥션 타임아웃",))
    c.fact("G6", "g6c2", "DB 커넥션 타임아웃을 5초로 낮췄다.", "DB 커넥션 타임아웃", "값", "5초", ("DB 커넥션 타임아웃",))
    c.ask("G6", "keyword", "DB 커넥션 타임아웃", "g6c1", "g6c2")
    c.ask("G6", "natural", "DB 연결은 몇 초 뒤에 타임아웃 되나", "g6c1", "g6c2")
    # G7 negation and conditions
    c.fact("G7", "g7a", "결제 캐시는 오프라인 모드일 때만 디스크에 저장한다.", "결제 캐시", "저장 조건", "오프라인 모드", ("결제 캐시",),
           ("natural", "결제 캐시를 디스크에 저장하나"), ("keyword", "캐시 디스크 저장 조건"))
    c.fact("G7", "g7b", "금요일 오후에는 운영 배포를 하지 않는다.", "운영 배포", "금지", "금요일 오후", ("운영 배포",),
           ("natural", "금요일에 배포해도 되나"), ("keyword", "운영 배포 금지 시간"), ("typo", "금욜 배포"))
    c.fact("G7", "g7c", "테스트 카드는 실제 결제를 일으키지 않는다.", "테스트 카드", "금지", "실제 결제", ("테스트 카드",),
           ("natural", "테스트 카드로 진짜 결제가 되나"), ("keyword", "테스트 카드 실결제"))
    c.fact("G7", "g7d", "긴급 패치는 사후 리뷰를 조건으로 단독 머지를 허용한다.", "긴급 패치", "허용 조건", "사후 리뷰",
           ("긴급 패치",),
           ("natural", "긴급 패치는 혼자 머지할 수 있나"), ("keyword", "핫픽스 단독 머지"))
    c.fact("G7", "g7e", "회의록에는 고객 실명을 쓰지 않는다.", "회의록 작성", "금지", "고객 실명", ("회의록 작성",),
           ("natural", "회의록에 고객 이름을 적어도 되나"), ("keyword", "회의록 실명"))
    # G8 no-match queries: nothing in this corpus answers them
    for form, text in (("keyword", "사내 식당 메뉴 변경"), ("natural", "모바일 앱 다크 모드 색상은 뭐로 하나"),
                       ("keyword", "연말 워크숍 장소"), ("fragment", "Kubernetes HPA"),
                       ("natural", "GraphQL 스키마 버전 규칙이 있나"), ("typo", "주차장 이용 규칚")):
        c.ask("G8", form, text)
    # G9 keyword-stuffed decoys against facts from G4, G6 and G7
    c.decoys(["결제", "재시도", "정책", "배포", "승인", "리뷰어", "캐시", "디스크", "오프라인", "마이그레이션",
              "운영", "DB", "API", "응답", "목표", "로그", "마스킹", "금요일"], 12, seed=23)
    for form, text, gold in (("keyword", "배포 승인 리뷰어 수", ("g4a",)), ("keyword", "캐시 디스크 오프라인", ("g7a",)),
                             ("natural", "운영 DB 마이그레이션은 무슨 요일에 하나", ("g4b",)),
                             ("keyword", "결제 API 응답 목표 p95", ("g4c",)), ("keyword", "로그 마스킹 저장", ("g4d",)),
                             ("natural", "금요일 오후에 운영 배포해도 되나", ("g7b",)),
                             ("keyword", "결제 재시도 횟수 변경", ("g6a1", "g6a2")), ("typo", "배포 승인 리뷰워", ("g4a",))):
        c.ask("G9", form, text, *gold)
    c.chatter("pay-core", ["정산", "문서", "인프라", "환불", "배포", "보안", "리뷰", "회의"],
              ["정산", "API 문서", "PostgreSQL", "환불", "TLS", "Caddy", "토큰", "스키마", "로그", "테스트", "설정", "정책"],
              ["메모", "체크리스트", "이슈", "초안", "결과", "질문 목록"],
              ["정리했다", "공유했다", "업데이트했다", "검토했다", "기록했다"], seed=11)
    return c


def holdout() -> Corpus:
    c = Corpus("holdout")
    # G1 code identifiers (search indexing service)
    c.fact("G1", "h1a", "IndexCompactor.mergeFactor 는 기본 10이다.", "IndexCompactor.mergeFactor", "default", "10",
           ("IndexCompactor.mergeFactor",),
           ("fragment", "mergeFactor 기본값"), ("keyword", "IndexCompactor mergeFactor"), ("typo", "mergeFacter"))
    c.fact("G1", "h1b", "QueryPlanner.maxClauseCount 를 넘으면 쿼리를 거부한다.", "QueryPlanner.maxClauseCount", "rejects", "쿼리",
           ("QueryPlanner.maxClauseCount",),
           ("fragment", "maxClauseCount 초과"), ("natural", "쿼리 절이 너무 많으면 어떻게 되나"), ("typo", "QueryPlaner 절 제한"))
    c.fact("G1", "h1c", "snapshot_uploader 는 S3 멀티파트 크기를 64MB 로 쓴다.", "snapshot_uploader", "uses", "64MB",
           ("snapshot_uploader",),
           ("fragment", "snapshot_uploader 멀티파트"), ("keyword", "스냅샷 업로드 파트 크기"), ("fragment", "uploader 64MB"))
    c.fact("G1", "h1d", "reindex-all 스크립트의 --since 옵션은 UTC 날짜만 받는다.", "reindex-all", "accepts", "UTC date",
           ("reindex-all",),
           ("keyword", "reindex-all since"), ("typo", "reindx-all 날짜 옵션"))
    c.fact("G1", "h1e", "GradleBuildCache.remoteEnabled 는 CI 에서만 켠다.", "GradleBuildCache.remoteEnabled", "enabled", "CI",
           ("GradleBuildCache.remoteEnabled",),
           ("fragment", "remoteEnabled CI"), ("natural", "원격 빌드 캐시는 어디서 켜나"), ("keyword", "GradleBuildCache remote"))
    # G2 Korean prose
    c.fact("G2", "h2a", "온보딩 가이드는 입사 첫 주에 멘토가 함께 읽는다.", "온보딩 가이드", "읽기", "첫 주", ("온보딩 가이드",),
           ("natural", "온보딩 가이드를 언제 읽나"), ("keyword", "온보딩 멘토 첫주"), ("typo", "온보딩 가이두"))
    c.fact("G2", "h2b", "고객 문의 답변은 영업일 기준 하루 안에 보낸다.", "고객 문의", "응답 기한", "하루", ("고객 문의",),
           ("natural", "고객 문의에 답하는 기한"), ("keyword", "문의 응답 기한"), ("typo", "고객 문이 답변 기한"))
    c.fact("G2", "h2c", "신규 입사자의 개발 장비는 입사 전날까지 준비한다.", "개발 장비", "준비 시점", "입사 전날", ("개발 장비",),
           ("natural", "새로 온 사람 노트북은 언제까지 준비하나"), ("keyword", "입사자 장비 준비"), ("typo", "개발 쟝비 준비"))
    c.fact("G2", "h2d", "환불 요청은 상담원이 아니라 정산팀이 처리한다.", "환불 요청", "처리 주체", "정산팀", ("환불 요청",),
           ("natural", "환불은 어느 팀이 처리하나"), ("keyword", "환불 처리 담당"), ("typo", "환불 처리팀이 어디"))
    # G3 mixed language
    c.mixed("h3a", "Crash reports are uploaded only on Wi-Fi.", "crash reports", "upload condition", "Wi-Fi",
            ("crash reports",),
            ("natural", "크래시 리포트는 언제 업로드되나", ("crash reports upload",)),
            ("keyword", "크래시 리포트 와이파이", ("crash reports Wi-Fi",)))
    c.mixed("h3b", "The mobile build uses Gradle configuration cache.", "mobile build", "uses", "configuration cache",
            ("mobile build",),
            ("keyword", "모바일 빌드 설정 캐시", ("Gradle configuration cache",)))
    c.mixed("h3c", "Support macros must be reviewed every quarter.", "support macros", "review", "quarter",
            ("support macros",),
            ("natural", "상담 매크로는 얼마나 자주 검토하나", ("support macros review",)),
            ("typo", "상담 메크로 검토", ("support macros",)))
    c.mixed("h3d", "검색 색인은 synonym graph filter 를 쿼리 시점에만 적용한다.", "검색 색인", "applies", "synonym graph",
            ("검색 색인", "synonym graph filter"),
            ("keyword", "동의어 필터 적용 시점", ("synonym graph filter", "query time")))
    # G4 short facts among long documents
    c.fact("G4", "h4a", "앱 스토어 제출은 QA 서명 후에만 한다.", "앱 스토어 제출", "조건", "QA 서명", ("앱 스토어 제출",),
           ("natural", "앱 스토어에 언제 제출할 수 있나"), ("keyword", "스토어 제출 QA"), ("typo", "앱 스토아 제출 조건"))
    c.fact("G4", "h4b", "검색 인덱스 전체 재구축은 주말 새벽에 한다.", "인덱스 재구축", "시점", "주말 새벽", ("인덱스 재구축",),
           ("natural", "인덱스 전체 재구축은 언제 하나"), ("typo", "인덱스 제구축 시간"))
    c.fact("G4", "h4c", "상담 만족도 목표는 4.5점 이상이다.", "상담 만족도", "목표", "4.5점", ("상담 만족도",),
           ("keyword", "상담 만족도 목표 점수"), ("natural", "만족도 목표가 몇 점이야"))
    c.fact("G4", "h4d", "온보딩 설문은 입사 30일째에 보낸다.", "온보딩 설문", "발송 시점", "30일째", ("온보딩 설문",),
           ("keyword", "온보딩 설문 시점"), ("natural", "입사 후 설문은 언제 보내나"), ("typo", "온보딩 설뮨 30일"))
    c.long("h4long0", "모바일 출시 회고", "앱 스토어 제출 QA 서명 출시 일정 심사 반려 스크린샷 준비 버전 번호 제출 체크리스트 서명 절차")
    c.long("h4long1", "검색 운영 주간 보고", "인덱스 재구축 일정 샤드 상태 주말 작업 새벽 배치 재구축 시간 실패 원인 디스크 사용량")
    c.long("h4long2", "고객 지원 분기 리뷰", "상담 만족도 목표 응답 시간 매크로 개선 상담원 교육 만족도 설문 점수 분포 이탈 원인")
    c.long("h4long3", "온보딩 프로그램 개선 회의", "온보딩 설문 시점 멘토 배정 첫 주 일정 장비 준비 설문 문항 입사 경험 개선 과제")
    # G5 concurrent tasks in one project
    c.fact("G5", "h5a", "search-platform 인덱싱 작업에서 배치 크기는 500 문서로 정했다.", "배치 크기", "fixed", "500",
           ("search-platform",),
           ("keyword", "인덱싱 배치 크기"), ("natural", "search-platform 은 몇 문서씩 색인하나"), ("typo", "인덱싱 베치 크기"))
    c.fact("G5", "h5b", "search-platform 문서 작업에서 API 문서는 OpenAPI 로 생성한다.", "API 문서", "generated", "OpenAPI",
           ("search-platform", "OpenAPI"),
           ("keyword", "API 문서 생성 방식"), ("fragment", "OpenAPI"))
    c.fact("G5", "h5c", "search-platform 모니터링 작업에서 알림 임계값은 오류율 2퍼센트다.", "알림 임계값", "threshold", "2퍼센트",
           ("search-platform",),
           ("keyword", "알림 임계값 오류율"), ("natural", "오류율이 얼마면 알림이 가나"), ("fragment", "search-platform 임계값"))
    c.fact("G5", "h5d", "search-platform 비용 작업에서 예약 인스턴스를 1년 약정으로 샀다.", "예약 인스턴스", "term", "1년",
           ("search-platform",),
           ("keyword", "예약 인스턴스 약정"), ("typo", "예약 인스턴트 기간"))
    # G6 versions
    c.fact("G6", "h6a1", "검색 타임아웃은 2초다.", "검색 타임아웃", "값", "2초", ("검색 타임아웃",))
    c.fact("G6", "h6a2", "검색 타임아웃을 800밀리초로 낮췄다.", "검색 타임아웃", "값", "800밀리초", ("검색 타임아웃",))
    c.ask("G6", "keyword", "검색 타임아웃 값", "h6a1", "h6a2")
    c.ask("G6", "natural", "검색은 몇 초 뒤에 타임아웃 되나", "h6a1", "h6a2")
    c.fact("G6", "h6b1", "상담 운영 시간은 오전 9시부터 오후 6시까지다.", "상담 운영 시간", "범위", "오전 9시부터 오후 6시까지", ("상담 운영 시간",))
    c.fact("G6", "h6b2", "상담 운영 시간을 오후 8시까지 연장했다.", "상담 운영 시간", "범위", "오후 8시", ("상담 운영 시간",))
    c.ask("G6", "keyword", "상담 운영 시간", "h6b1", "h6b2")
    c.ask("G6", "natural", "상담은 몇 시까지 하나", "h6b1", "h6b2")
    c.ask("G6", "typo", "상담 운용 시간", "h6b1", "h6b2")
    # G7 negation and conditions
    c.fact("G7", "h7a", "베타 사용자에게는 푸시 알림을 보내지 않는다.", "푸시 알림", "금지", "베타 사용자", ("푸시 알림",),
           ("natural", "베타 사용자에게 푸시를 보내나"), ("keyword", "푸시 알림 제외 대상"), ("typo", "베타 유저 푸쉬"))
    c.fact("G7", "h7b", "동의어 사전은 검색 품질 리뷰를 통과한 경우에만 갱신한다.", "동의어 사전", "갱신 조건", "품질 리뷰",
           ("동의어 사전",),
           ("keyword", "동의어 사전 갱신 조건"), ("natural", "동의어 사전은 언제 바꿀 수 있나"), ("fragment", "동의어 품질 리뷰"))
    c.fact("G7", "h7c", "VIP 고객 문의는 자동 응답 매크로를 쓰지 않는다.", "VIP 고객 문의", "금지", "자동 응답", ("VIP 고객 문의",),
           ("keyword", "VIP 문의 자동 응답"), ("typo", "VIP 문의 자동응담"))
    # G8 no-match
    for form, text in (("keyword", "사무실 이전 일정"), ("natural", "결제 게이트웨이 수수료는 얼마인가"),
                       ("fragment", "Terraform state"), ("typo", "디자인 시스탬 버튼 반경")):
        c.ask("G8", form, text)
    # G9 decoys
    c.decoys(["앱", "스토어", "제출", "QA", "서명", "인덱스", "재구축", "주말", "새벽", "상담", "만족도", "목표",
              "푸시", "알림", "베타", "검색", "타임아웃"], 10, seed=37)
    for form, text, gold in (("keyword", "앱 스토어 제출 QA", ("h4a",)), ("keyword", "인덱스 재구축 주말", ("h4b",)),
                             ("keyword", "상담 만족도 목표", ("h4c",)), ("natural", "베타 사용자 푸시 알림 보내나", ("h7a",)),
                             ("keyword", "검색 타임아웃 변경", ("h6a1", "h6a2"))):
        c.ask("G9", form, text, *gold)
    c.chatter("search-platform", ["인덱싱", "문서", "모니터링", "비용", "쿼리", "보안", "릴리스", "온보딩"],
              ["배치", "API 문서", "알림", "인스턴스", "샤드", "캐시", "로그", "대시보드", "권한", "스키마"],
              ["메모", "초안", "결과", "질문 목록", "체크리스트"],
              ["정리했다", "공유했다", "업데이트했다", "검토했다"], seed=31)
    return c


CORPORA = {"dev": dev, "holdout": holdout}
