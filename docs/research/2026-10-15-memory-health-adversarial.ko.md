# 메모리 건강 관리 pipeline — 적대적 리뷰

## 판정

**조건부 제안 채택, 일괄 자동화는 기각한다.** 코드 provenance·정정 피드백·중복 projection·보존 관리는 유용하지만 한 ‘건강도 job’에 판단·승인·삭제·디스크 회수 권한을 합치면 안 된다. 우선순위는 **저장 증가 관측 → disposition 의미/복원 계약 → 제한된 일시 상태 정리 → shadow stale 검토 → 원본을 보존한 merge proposal**이다.

검토 대상은 사용자가 제공한 provenance → 세션 Health Audit → Accept/Reject → coalesce → 정기 유지보수 제안이다. 제공된48–52분 타임스탬프를 독립 확인한 영상 분석은 아니다. 새 subsystem·외부 audit inference·transcript 수집·자동 삭제/승격을 구현하거나 승인하지 않는다. OSS의 실제 성장 대책은 [별도 조사](2026-10-15-oss-db-growth.ko.md)에 코드·merged/open 상태·라이선스·물리 저장 실험을 정리했다.

## 실제 두 native 모델 검토

| 항목 | Opus | Codex |
|---|---|---|
| 실행 | Claude Code2.1.300, 요청/응답 metadata `claude-opus-5-5` | Codex0.162.1, 요청 `gpt-6.1-sol`, 별도 동일 모델 native header 확인 |
| 결과 | 최초 검토와 self-challenge addendum 모두 exit0/success, fallback 없음 | 독립 검토 exit0, timeout 없음, 모델 대체 없음 |
| 제한 | restricted·Read만, MCP0, no session persistence, permission denial0. `xhigh` 요청 | read-only snapshot, ignore user config/rules·ephemeral, web/MCP/hooks/plugins 비활성화. header effort는 **none** |
| 증거 범위 | source-only. addendum이 최초 과장/오분류를 명시 철회 | source-only. review JSON에 model field가 없어 별도 CLI header로 보강 |

최초 native 검토 process의 실제 겹침은 **222.20286초**다. Opus 최초12:25:38–12:33:39 UTC, Sol12:26:04.555761–12:29:46.758621 UTC. 동시 subagent 이름만으로 모델/parallel proof를 대신하지 않았다. Opus 추가 검토는 자기 최초 주장의 반증이지 양 모델의 두 번째 상호 토론이 아니다. 두 모델이 같은 effort나 원자적 동일 source snapshot을 읽었다고 주장하지 않는다. Sol은 순차 복사한 공개42개 파일, Opus는 allowlist의 당시 파일을 읽었다. CLI/header metadata는 backend의 암호학적 attestation이 아니다.

raw private logs·사용자 config/credential·추론 원문은 공개하지 않는다. 모델 검토는 test/build/DB/runtime proof가 아니며 parent의 저장소 실험과 섞지 않는다. 과거 embedding 검토·PR8 live Jev 증거를 이 검토 결과로 재사용하지 않는다.

## 1. 먼저 바로잡아야 할 용어와 현재 동작

| 사건 | 현재 실제 의미 | 같지 않은 것 |
|---|---|---|
| cleanup | `jobs.py:38-78`, `store.py:613-814`: bounded 판단 대기 생성·progress | retention·semantic truth 감사·purge·VACUUM |
| source selection remember/discard | exact 원문 창에 대한 판단. discard는 미래 재게시 비교의 rejection evidence | 인간 승인·operator 철회·원문 삭제 |
| feedback reject | `domain.py:186-205`, `store.py:1061-1083`: 이유가 있는 agent/operator feedback, 미래 remember 재진입 제어 | 기존 claim의 즉시 recall 제외·purge·human attestation |
| claim judgment | `store.py:816-871`: 원문 ID/revision manifest·명시 relation·전체 dependency 저장 | 원본을 합쳐 지우는 compaction·required rule 승인 |
| rule approval | exact body/digest·scope·target revision·현재 credential/서명 검증 | 반복 출현·confidence·Accept 문자열 |
| physical purge 응답 | 현재 source body NULL·파생 text scrub 상태 | OS 파일 축소·WAL/SSD snapshot/모든 backup erasure |

현재 feedback에는 범용 **Accept API가 없다.** `correct/reject/retract_request`만 있다. speaker=human도 producer 선언이며 인간 존재·사실 확인·규칙 승인이 아니다. audit 기능을 기존 계약이 이미 있는 것처럼 설명하지 않는다.

### Reject의 두 경계

**현재 claim이 Reject 뒤에도 후보로 보일 수 있다.** `store.py:1131-1144,2136-2145`의 claim/lexical eligibility와 현재 composer는 reject-target feedback으로 기존 claim을 숨기지 않는다. reject는 retract/purge와 다르다는 현행 계약에 맞으므로 이를 ‘삭제 fence 우회’라고 부르지 않는다. 다만 건강도 UX가 ‘거절=제외됨’이라고 표시하면 오해다.

최소 제안은 권한/현재 lineage를 확인한 **disposition marker와 의미 설명**이다. agent reject를 자동 suppression으로 바꾸면 operator 철회에 가까운 효과를 agent에게 줄 수 있다. 질의 한정 ‘무관함’은 `relevance=false`로 제출하고 원문 전체의 global reject와 섞지 않는다.

**backup 이후 Reject/discard는 되돌아갈 수 있다.** `journal.py:253-254,316-326`의 독립 journal은 source/origin/artifact deletion과 purge를 보존한다. PG에만 있는 backup 이후 rejection/discard를 별도 disposition ledger로 보존하지 않는다. restore는 최신 삭제 floor를 재적용하지만 post-backup feedback까지 되살리는 것은 아니다.

이는 **새 health 요구사항**이며 현 삭제 계약 위반이나 철회 본문 부활을 발견한 것이 아니다. ‘옛 backup 복원 뒤에도 거절/재검토 판단 유지’를 요구한다면 exact revision·actor·scope·reason의 별도 복원 계약과 disclosure가 필요하다. 기존 deletion journal에 모든 feedback을 무작정 추가하지 않는다.

## 2. 제안별 영향·장단점·공격 시나리오

### A. 코드 위치 provenance

**이익:** 바뀐 코드와 연결된 기억만 재검토하면 범위를 줄일 수 있다.

**현재:** `Source`는 source revision·origin/run/snapshot·event/recorded time을 보존하지만 검증된 code repository/commit/blob/path/symbol anchor 계약은 없다(`domain.py:267-280`). 정확한 원문 span은 ‘그때 그렇게 기록했다’는 증거이지 현재 코드가 같은 상태라는 증거가 아니다.

**반례:** rename·branch 전환·generated file·동일 경로 재사용·무관한 refactor·함수 이동·line shift. 파일이 바뀌었다고 원래 설계 결정이 틀린 것은 아니다. 반대로 파일이 안 바뀌어도 외부 API/정책이 달라져 기억이 틀릴 수 있다.

**제안:** 검증된 binding/repo identity와 관측 commit/blob·path·symbol/span·관측 주체를 선택적으로 연결한다. 변경은 `needs_review`, anchor 해석 불가는 `anchor_unresolved` 등 진단 신호다. 자동 Reject·만료·삭제나 required-rule scope 변경으로 쓰지 않는다. code path가 원문/모델 출력에 있다는 이유만으로 검증된 anchor로 승격하지 않는다.

승인 path selector가 rename 뒤 새 path에 FALSE인 것은 현재 승인 scope의 정상 동작이지 rule 삭제가 아니다(`context.py:64-75,165-170`). selector 변경은 승인 digest 변경이며 새 승인이 필요하다. 실제 tree를 보지 않는 서버에 ‘모든 경로를 확인했다’는 건강 점수를 주지 않는다.

### B. 세션 종료 Health Audit

**이익:** 사람이 정정한 이유·실패 맥락을 다음 작업의 후보 검토에 연결할 수 있다.

**반례:** crash로 Stop hook이 없음, child/compact/resume의 coverage gap, tool output·transcript의 일부만 관측, 제공한 기억을 실제 사용했다고 오인. audit 결과를 찾기 위해 모든 대화를 읽으면 기존 capture/egress 범위를 넘는다.

**제안:** offered·inspected·delivered·후속 model-input 관측·실제 action/outcome·인간 승인 사건을 분리한다. 기본은 현재 허가된 coding agent가 bounded pending/기억/정정 근거를 명시 inspect→판단하는 경로다. 새 LLM audit·embedding·summary rebuild·전체 transcript 전송은 별도 scope·명시 허가·예산이 필요하다. 기존 Jev 허가를 새로운 session-wide audit의 포괄 동의로 쓰지 않는다.

관측하지 못한 것은 `unobserved/partial`로 남긴다. 사용 횟수/LRU/인용 빈도만으로 유효성이나 폐기 허가를 추정하지 않는다. 추가 audit가 이력·token·비용·개인정보 보관을 더 늘릴 수 있다.

### C. Accept/Reject·정정 feedback

**이익:** 이유와 반례가 남아 동일 오류의 재진입을 막고 실제 정정으로 이어질 수 있다.

**반례:** query irrelevant를 global reject로 확대, agent의 Accept를 인간 사실 확인으로 승격, audit 직후 source correction/revoke, 이전 revision의 승인을 새 요약본에 재사용, 복원으로 disposition만 rollback.

**제안:** ‘현재 과제에서 유용함’, ‘후보로 보존’, ‘명시 인간 정정’, ‘required rule 승인’, ‘operator 철회/본문 삭제’는 서로 다른 사건이다. exact target/revision·actor·scope·reason·관측 범위와 현재 auth/deletion fence를 보존한다. 의미를 정하기 전 단일 accept boolean으로 합치지 않는다. 현재 feedback actor는 operation credential 경유로 추적되며 선언된 speaker만으로 human proof가 되지 않는다.

거절 이유 본문을 영구 보관하면 privacy/purge 요구와 충돌한다. 이유 본문, appeal/reopen 이력, 최소 exact-identity 비부활 metadata의 보존 목적을 분리한다. hash 하나로 paraphrase의 의미 재진입까지 막는다고 주장하지 않는다.

### D. Coalesce/Compaction

**이익:** 검색 결과의 중복과 context 비용을 줄일 수 있다.

**반례:** ‘항상’으로 조건 축약, 부정/예외/유효 시간 소실, 현재/계획/가설 혼합, 비슷하지만 다른 식별자, 한 판단에 들어간 모든 source와 독립 support를 혼동, 병합 두 개가 같은 입력을 동시에 소비, 소스 철회 뒤 늦은 병합 게시.

**현재 보호:** `ClaimDraft`의 polarity/modality/conditions/exceptions/valid time/evidence, exact source/span/revision, complete judgment manifest, publication/final-delivery fence. relation은 비파괴적이며 `supersedes` 관계를 만든다고 원래 claim을 자동 삭제하지 않는다. 오래된 canonical pointer migration과 현재 relation 의미는 다르다.

**현재 한계:** 한 A–B relation도 judgment 묶음 전체 claim/source에 의존한다(`store.py:845-863`). 참고한 C의 철회가 관계를 무효화할 수 있는 보수적 설계다. dependency를 임의로 떼지 말고 더 작은 독립 근거가 필요하면 별도 명시 판단을 만든다.

Jev의 kept span은 verbatim이지만 `individual/shared qualifications`와 validity는 비어 있고 다른 span은 unused일 수 있다(`judge_worker.py:476-485`). 같은 문장 안 부정은 text에 남지만 별도 문장의 조건이 빠지는 것은 structural grounding만으로 막지 못할 수 있다. 관계 방향도 claim 생성 시각에 의존한다(`judge_worker.py:536-568`). **소스상 의미 위험이며 새 live 모델 재현은 아니다.** 현재 관계는 비파괴적이지만 미래 hard merge/삭제 트리거로 쓸 때 위험이 커진다.

**제안:** 먼저 기존 duplicate/support/contradict/supersede 관계와 bounded projection으로 중복 노출만 줄인다. semantic 합성은 원문·조건·예외·부정·시간·반례·이전 ID·assertion별 lineage·동시 CAS·rollback/correction 경계의 별도 계약 후 평가한다. 요약을 `agent_note`로 저장했다고 독립 grounding source나 승인 규칙이 되지는 않는다. 원본 보존 정책과 본문 삭제는 별도 결정이다.

### E. 정기 유지보수·DB 비대화

**이익:** 명백한 일시 상태·불필요한 파생 저장·만료 backup의 증가를 제어할 수 있다.

**반례:** receipt TTL 뒤 같은 key 재실행, rejection/floor 제거로 stale replay/backup 부활, external vector cleanup 전에 ownership 삭제, 오래된 DB를 현재 schema처럼 열기, callback 성공만 보고 partial purge를 완료로 기록, disk-full 상황에 전량 rewrite.

**제안:** authoritative source/승인/거절과 disposable admission/index/cache/운영 이력을 분리한다. age/count/batch뿐 아니라 최대 시간·메모리·lock·work, stable cutoff·durable cursor·현재 상태 재검사·partial/unknown을 설계한다. 운영 DB를 계속 최소 크기로 재작성하는 것이 목적은 아니다. 정상 autovacuum으로 재사용하고 실제 disk 반환이 필요할 때만 별도 maintenance를 선택한다.

PG·SQLite의 실제 저장소 의미, WAL·TOAST/index·backup와 합성 관측값은 [DB 성장 조사 §3–5](2026-10-15-oss-db-growth.ko.md#3-우리-시스템과의-대조)를 따른다. 데이터를 지우지 않고 context만 줄이는 것이 storage retention은 아니며, logical purge를 media erasure로 부르지 않는다.

## 3. 성장 시 semantic health뿐 아니라 조회 비용도 커진다

두 모델이 source scaling 위험을 지적했다. **실제 p95/병목/성능 저하는 측정하지 않았으므로 아래는 source-backed 위험과 후속 제안이다.**

- `delivery()`는 authority clock lock 아래 current source/claim recheck와 `_stats`를 수행한다(`store.py:173-195,3164-3195`). `_stats`에는 history/legacy 집계도 있다. barrier journal 검증은 append-only entry 전체를 읽고 HMAC 검증한다(`journal.py:244-271`). 단순 row/file 크기뿐 아니라 읽기·전달 latency도 증가 후보이다.
- **stats를 그냥 lock 밖으로 옮기지 않는다.** `Application._context_result`는 같은 stamped 상태의 current coverage로 partial을 계산한다(`application.py:145-153`). stale stats는 unavailable/partial을 숨길 수 있다. 작은 후보는 required-context가 버리는 stats 계산을 별도 계약으로 생략하거나, 일반 delivery에는 실제 current coverage만 유지하고 역사 집계는 명시 stats로 분리하는 방안이다. 구현/성능 개선 완료가 아니다.
- artifact floor reconciliation은 여러 table ID 전체를 수집/HMAC하고 retracted epoch를 갱신한다. 비용은 reconcile 횟수×corpus 크기로 볼 소스 근거가 있지만 이를 무조건 quadratic이라고 부르지 않는다. journal caching이나 floor 단축은 authority fence 변경이므로 검증 없이 권하지 않는다.
- cleanup은 global sequence의20개 페이지를 binding/snapshot으로 묶는다. 별도 페이지의 오래된 결정과 새 반대 결정이 같은 manifest에서 비교된다고 보장하지 못한다. pending/held·interval guard도 최초 coverage를 지연할 수 있다. ‘전체 기억 정상’이 아니라 **검사한 범위·미검사/held 범위**를 공개해야 한다. 무조건 starvation이라는 최초 과장은 채택하지 않았다.

## 4. 구형 DB·옛 데이터·backup은 세 문제다

1. **schema migration:** 구조 호환과 권위 전환이다. 현재 명시 stopped-service migrate·원본 private config 보존·미확정 fence·legacy model claim awaiting_revalidation·original failed work retirement를 유지한다. migration 성공이 의미 재검증은 아니다.
2. **오래된 지식:** 나이·마지막 접근·코드 변경은 검토 신호다. 현재 조건/근거와 충돌하는지 판단해야 한다. 오래됐어도 안정적인 required rule·반례를 자동 제거하지 않는다.
3. **backup retention/restore:** 지원 archive/binary·최신 독립 deletion head·token rotation·rule 재승인을 유지한다. post-backup disposition rollback은 별도 요구사항으로 명시한다. backup 개수·기간·bytes·키 보존/폐기와 restore drill이 필요하며 암호화·row scrub·VACUUM 하나가 모든 복사본 삭제를 뜻하지 않는다.

## 5. 최소 제안과 acceptance

| 우선순위 | 제안 | 승인/확인 전 금지 | 완료 관측 |
|---|---|---|---|
| P0 | disposition·approval·deletion 의미, 지원 restore/replay 범위 고정 | Accept/confidence로 required rule 활성화, Reject를 무고지 operator 철회로 확대 | exact actor/revision/scope 사건 구분, post-backup feedback rollback disclosure |
| P1 | operator-only body-free growth/current coverage 진단 | 원문/추론 자동 telemetry·추가 audit 모델 | logical bytes·relation/index/TOAST·WAL·backup·rows·dead tuple 추정을 구분, 실제 사용/미관측 분리 |
| P1 | 만료 일시 상태와 파생 이력의 dry-run·제한된 유지보수 설계 | receipt/rejection/floor의 임의 TTL, source age purge | 대상+영향 preview, 현재 auth/revision 재검사, 작은 commit·durable resume·partial/unknown |
| P2 | 검증된 code anchor와 shadow stale 후보 | rename/mtime/LRU로 자동 삭제/Reject, 승인 selector 자동 변경 | rename/branch/generated/외부 정책 변경의 오탐·누락·anchor unresolved 평가 |
| P3 | 원본 보존 merge proposal·projection 비교 | 조건/예외/시간/반례 삭제, 새 요약의 self-approval | 기존 검색 대비 유효 기억·오탐·최종 task correctness, 동시 merge·correction·revoke·restore 경계 |

모든 단계에서 두 판단 provider의 기존 권한·원문·revision·삭제·최종 전달 계약을 유지한다. 새 Health Audit의 추가 전송·보관·자동화는 기존 Jev 키나 provider 허가로 추정하지 않는다. 실제 효익은 frozen 개발 대화·결정·오류·정정·거절 데이터와 후속 coding 행동으로 평가해야 하며 source 리뷰·합성 smoke가 실사용1–2주 trial을 대체하지 않는다.

## 6. 채택하지 않은 과장과 보존할 강점

**철회/기각:** Reject를 recall fence 위반으로 단정, cleanup 전체 starvation 단정, reconciliation 무조건 quadratic 단정, path selector 불일치를 rule 삭제로 간주, row purge를 OS/media 회수로 간주, 두 모델 모두 xhigh·동일 atomic snapshot이었다는 주장.

**보존:** candidate/판단/승인 분리, exact revision·UTF-8 span, final delivery fence, 비파괴 relation, 독립 body-free deletion journal, 방향성 lineage·독립 support, restore 후 token/rule 재승인, legacy 실패/audit 보존, truthful unknown 상태.

새 health 설계는 이 보호를 우회하는 별도 writer/DB/LLM engine이 아니라 기존 authority 아래의 진단·제안·명시 승인·제한된 실행이어야 한다. 현재 소스 검토가 승인한 것은 이 방향의 **후속 설계 제안**이지 자동 자기 치유 구현이나 운영 배포가 아니다.
