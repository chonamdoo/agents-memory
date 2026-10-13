# Skills Over MCP: stable 계약·실제 지원·local-first memory 적용 소스 감사

조사 기준: 2026-10-12. **조사 문서만 작성했다.** 구현 worktree, 런타임, 설정, 승인 receipt, frozen skill, 기존 설계 문서는 변경하지 않았다. build/test/lint/formatter 및 실제 서버 연결·skill 활성화 실험은 실행하지 않았다. native client의 `--version`과 설치된 Python SDK 파일은 읽었다. 이 문서는 별도 native Claude/Codex adversarial 비교의 **공통 근거 입력**이며, 그 비교 결과를 대신하지 않는다.

## 1. 요약 판정

**공식 extension은 released stable이다. 그러나 Claude Code·Codex CLI·OMP가 현재 그 extension의 활성화·승인·검증 계약을 구현한다는 뜻은 아니다.** 일반 `resources/read`, 로컬 SKILL.md 지원, plugin submission-time import는 서로 다른 능력이다.

현재 memory의 canonical PG approval ledger와 source/snapshot/lease/auth/deletion fence는 유지한다. Skills는 승인된 workflow의 **선택적 transport/export projection** 후보이지 rule authority, mandatory-rule enforcement, memory extraction/consolidation 엔진의 대체가 아니다. 이번에는 cutover·SDK upgrade·host 설치를 하지 않는다.

가장 중요한 최신 차이: 공식 구현목록은 Python 지원을 아직 `in progress`라고 적지만, [Python SDK PR #3485](https://github.com/modelcontextprotocol/python-sdk/pull/3485)는 **2026-10-11 14:44:20 UTC merged**, merge commit **`9a754b0aabb873d9707d52dc165b569fb442ec8c`**이다. 반면 [최신 SDK release v2.3.0](https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.3.0)은 2026-10-02 22:02:27 UTC이며, 실제 설치된 `mcp==2.3.0`에는 이 새 Skills 모듈이 없다. **merged source와 released/installed API를 구분해야 한다.**

## 2. 근거의 우선순위와 pinned revision

- **[관찰·규범]** [ext-skills stable source](https://github.com/modelcontextprotocol/ext-skills/blob/167da6c0d42c247a8f8470228a10ca711e3f6c45/specification/stable/skills.mdx), repository revision **`167da6c0d42c247a8f8470228a10ca711e3f6c45`**. [README](https://github.com/modelcontextprotocol/ext-skills/blob/167da6c0d42c247a8f8470228a10ca711e3f6c45/README.md)는 이를 source of truth 및 released snapshot으로 명시한다. base MCP `2026-07-28` 이상, identifier `io.modelcontextprotocol/skills`. [SEP-2640](https://modelcontextprotocol.io/seps/2640-skills-extension)은 Final이며 README는 PR #2640 merge date를 2026-09-13으로 기록한다. repository [LICENSE](https://github.com/modelcontextprotocol/ext-skills/blob/167da6c0d42c247a8f8470228a10ca711e3f6c45/LICENSE)는 Apache-2.0.
- **[관찰·상태 목록]** [official client matrix](https://modelcontextprotocol.io/extensions/client-matrix)는 community-maintained이며, 지원 누락은 그 자체로 부지원 증명이 아니다. [implementations](https://github.com/modelcontextprotocol/ext-skills/blob/167da6c0d42c247a8f8470228a10ca711e3f6c45/docs/implementations.md)는 더 넓은 community 목록이고 `v1/partial/pre-v1/prototype/in progress/planned`를 분리한다.
- **[관찰·구현]** Python SDK merge **`9a754b0aabb873d9707d52dc165b569fb442ec8c`** ([server](https://github.com/modelcontextprotocol/python-sdk/blob/9a754b0aabb873d9707d52dc165b569fb442ec8c/src/mcp/server/skills.py), [example](https://github.com/modelcontextprotocol/python-sdk/blob/9a754b0aabb873d9707d52dc165b569fb442ec8c/docs_src/skills/tutorial001.py), [license MIT](https://github.com/modelcontextprotocol/python-sdk/blob/9a754b0aabb873d9707d52dc165b569fb442ec8c/LICENSE)). PR 본문의 coverage/conformance 수치는 **작성자 보고**이며 여기서 재현하지 않았다.
- **[관찰·구현]** Hugging Face server **`dce2d5f0f16392e22d6f3fdc039681f4698e8cdf`**, [handler](https://github.com/huggingface/hf-mcp-server/blob/dce2d5f0f16392e22d6f3fdc039681f4698e8cdf/packages/app/src/server/skills/skill-resources.ts), [loader](https://github.com/huggingface/hf-mcp-server/blob/dce2d5f0f16392e22d6f3fdc039681f4698e8cdf/packages/app/src/server/skills/skill-loader.ts), [MIT license](https://github.com/huggingface/hf-mcp-server/blob/dce2d5f0f16392e22d6f3fdc039681f4698e8cdf/LICENSE).
- **[관찰·구현]** OMP **`5d0aaffaf1f987503ce129a642fb6e30339615af`**, [package version 18.10.1/MIT](https://github.com/can1357/oh-my-pi/blob/5d0aaffaf1f987503ce129a642fb6e30339615af/packages/coding-agent/package.json); local binary 보고도 `omp/18.10.1`. source와 binary의 byte-for-byte 동일성은 검증하지 않았다.
- **[관찰·구현]** Codex source **`6e5f665feb9b71e1500a5721036fbdb8e871f4b0`**, local binary `codex-cli 0.162.1`, [latest release rust-v0.162.1](https://github.com/openai/codex/releases/tag/rust-v0.162.1), 2026-10-09. main commit을 설치 binary의 정확한 commit이라고 주장하지 않는다.
- **[관찰]** local Claude Code `2.1.296`. 제품의 비공개 내부 implementation은 읽지 못했고 공식 [MCP documentation](https://code.claude.com/docs/en/mcp#use-mcp-resources)을 기준으로 평가했다.
- **[관찰·구현]** mcpc **`356f1add925ae1a0c39dad73c2b9a038935aae61`**, [package 0.7.0/Apache-2.0](https://github.com/apify/mcpc/blob/356f1add925ae1a0c39dad73c2b9a038935aae61/package.json), [skill command source](https://github.com/apify/mcpc/blob/356f1add925ae1a0c39dad73c2b9a038935aae61/src/cli/commands/skills.ts). 설치하거나 실행하지 않았다.

`ext-skills` GitHub releases API는 조회 때 빈 배열이었다. 이를 “stable 미출시”라고 해석하지 않는다. README가 stable snapshot을 공식 release로 정의하며, 별도 GitHub release asset은 다른 사실이다.

## 3. 지원·활성화 matrix

아래에서 **미확인**은 실제 해당 host 연결·negotiation·승인·model-input을 검증하지 않았다는 뜻이다. protocol/schema 지원과 host security 완성도는 별도 열이다.

| 대상 | 공개/설치 상태 | 실제로 확인한 범위 | extension runtime 활성화·security 판정 |
|---|---|---|---|
| ext-skills specification | released stable, MCP2026-07-28+ | 필수 2 method, optional directory method, SHA-256+size, host consent/cache 계약 | 규범 문서. 동작하는 host라는 뜻 아님 |
| Python SDK 최신 merge | #3485 merged 2026-10-11 | `Skills(Extension)`/handler registration/result validation 구현과 최소 예제 | source 존재. release/현재 설치 활성화는 아님; host 승인·origin tagging·YAML 비교 등 별도 |
| 현재 memory venv mcp2.3.0 | 설치 METADATA 및 package source 관찰 | `Extension`, `MethodBinding`, `MCPServer`, ordinary resources, modern discover가 있음. `skills/list/get`, Skills class, skills extension ID, directory method 검색은 mcp/mcp_types 모두 없음 | built-in Skills 없음. 기존 일반 extension API로 adapter를 만들 가능성은 있으나 **미구현·미검증**, capability만 선언 금지 |
| Go / TS / C# 공식 SDK | 구현목록 in progress; 조회한 #1238/#2818/#1864 모두 open, merged_at null | PR 상태까지 | release 또는 설치지원 **미확인**. Go conformance 통과 문구는 목록/작성자 보고 |
| Hugging Face hf-mcp-server | 구현목록 v1, HTTP only | 실제 custom `skills/list/get/directory` handlers, resource serving, manifest loader | server 구현 관찰. Claude/Codex/OMP activation 증명 아님 |
| Claude Code 2.1.296 | official matrix에 별도 Skills row 없음 | 공식 문서는 resource @mention 및 자동 list/read tool 제공을 설명 | **Skills extension 미확인**. 일반 resource read를 activation/content-bound approval이라고 부르지 않음 |
| Codex CLI 0.162.1 | matrix의 ChatGPT Partial과 별개 | source에 ordinary list/read resource API, host/executor/cloud/local skill sources가 있음. 조사한 rmcp client 및 skill source 경로에 Skills extension 호출/identifier 없음 | **native extension 미확인**. 조사 범위의 부재는 전체 제품 부지원 단정이 아님. `mcp_skill_dependencies`는 skill이 요구하는 MCP server 설치이지 MCP-served skill discovery가 아님 |
| OMP18.10.1 | source의 protocol constant `2025-11-25`; initialize client capabilities는 roots만 | generic MCP resource read, native local skill URI, unknown local skill URI의 exact advertised MCP resource fallback | **stable extension 경로 없음으로 평가**한 소스 범위. binary end-to-end는 미확인. 읽는 것은 ordinary resource, manifest/approval activation 아님; OMP strict memory capability gap도 그대로 |
| ChatGPT plugin importer | official matrix Partial | OpenAI first-party 문서: Scan Tools 시 static snapshot, 최대 5 skills/10 pages/100 files per skill, 5MiB per skill 등 | **submission-time import**, runtime refresh/revocation 아님. 문서는 draft subset으로 표현하고 예제에 stable size/cache/result fields도 빠져 있어 stable 호환 증명 불가 |
| MCP Inspector | official matrix Partial; 구현목록 since2.6.0(2026-09-09) | CLI verification 기능 공개 링크 | 공개 목록의 partial 지원. 전체 acting-window/실행 approval host인지는 **미확인** |
| fast-agent | official matrix Partial | first-party docs: eager local-copy installer, 모든 file 검증 후 copy, sidecar provenance, update 시 full manifest revision 비교, dynamic 불허 | 명시적으로 transparent MCP cache/live reader가 아님. eager install/로컬 copy를 stable lazy host 구현과 동등시하지 않음 |
| mcpc0.7.0 source | official matrix Skills check | fresh get→resources read→size/digest→frontmatter 검사, name ambiguity error, no unverified print 구현 | protocol inspection client 증거. downstream agent의 acting-window/per-skill execution approval·revocation까지 강제한다는 증거는 **없음** |
| Tachyon / community github-stars Python server | 구현목록 v1 | 목록의 self-report/작성자 conformance 주장만 관찰 | 이번 감사에서 개별 code·release·host 활성화는 **미확인** |
| github-mcp-server demo / VSCode fork / Goose | prototype/prototype/planned | 구현목록이 demo branch not for merge, fork, issue-only를 분리 | production 지원으로 채택하지 않음 |

[Codex MCP API source](https://github.com/openai/codex/blob/6e5f665feb9b71e1500a5721036fbdb8e871f4b0/codex-rs/rmcp-client/src/rmcp_client.rs), [Codex skill source kinds](https://github.com/openai/codex/blob/6e5f665feb9b71e1500a5721036fbdb8e871f4b0/codex-rs/ext/skills/src/sources.rs), [dependency installer](https://github.com/openai/codex/blob/6e5f665feb9b71e1500a5721036fbdb8e871f4b0/codex-rs/core/src/mcp_skill_dependencies.rs), [first-party Codex MCP docs](https://developers.openai.com/codex/mcp), [OpenAI plugin import contract](https://developers.openai.com/plugins/build/mcp-server#import-skills-from-the-mcp-server), [fast-agent current scope](https://github.com/evalstate/fast-agent/blob/main/docs/docs/mcp/skills-over-mcp.md).

## 4. stable contract: 무엇이 MUST인가

아래 인용은 모두 pinned stable source이다. speculative ADR나 archived draft보다 우선한다.

### 4.1 Negotiation·identity·내용 경계

- [L29–67](https://github.com/modelcontextprotocol/ext-skills/blob/167da6c0d42c247a8f8470228a10ca711e3f6c45/specification/stable/skills.mdx#L29-L67): `server/discover.capabilities.extensions`에 declaration, resources capability도 필요. “A server that declares this extension **MUST** implement … `skills/list` and `skills/get`.” directoryRead=false가 기본이며 true 선언 전 호출 금지. 모든 request의 required `_meta`도 base contract다.
- [L190–198](https://github.com/modelcontextprotocol/ext-skills/blob/167da6c0d42c247a8f8470228a10ca711e3f6c45/specification/stable/skills.mdx#L190-L198): identity는 “the pair of the host's identity for the originating server and the skill's `uri`”; registry, approval, cache, model-facing path 모두 두 요소를 보존하고 URI-only key 금지. 파일 path에도 server identity를 encode한다.
- [L208–225](https://github.com/modelcontextprotocol/ext-skills/blob/167da6c0d42c247a8f8470228a10ca711e3f6c45/specification/stable/skills.mdx#L208-L225): name은 label, unique 보장 없음, per-origin disambiguation, silent shadow/substitution 금지. `resources`는 모든 file을 딱 한 번 포함하는 complete manifest 또는 명시적 `"dynamic"`. **resources 누락은 dynamic이 아니라 invalid**다.
- [L131–137](https://github.com/modelcontextprotocol/ext-skills/blob/167da6c0d42c247a8f8470228a10ca711e3f6c45/specification/stable/skills.mdx#L131-L137): nested SKILL.md는 supporting markdown; 따로 activate할 때 fresh explicit consent 필요. enclosing approval이 nested allowed-tools를 승인하지 않는다.

### 4.2 일반 읽기와 activation을 분리

[L429–437](https://github.com/modelcontextprotocol/ext-skills/blob/167da6c0d42c247a8f8470228a10ca711e3f6c45/specification/stable/skills.mdx#L429-L437): **“`resources/read` is transport.”** ordinary read는 자동 activation, 승인, acting window를 만들지 않는다. host의 skill-loading path가 검증·필요 승인·acting window를 담당한다.

[L443–479](https://github.com/modelcontextprotocol/ext-skills/blob/167da6c0d42c247a8f8470228a10ca711e3f6c45/specification/stable/skills.mdx#L443-L479):

- raw bytes의 SHA-256 및 **byte size**를 verify; mismatch는 사용 금지. UTF-8 text는 text를 UTF-8 encode한 bytes, blob은 decode한 bytes를 기준으로 한다. 모델에 넣기 전에 검사한다.
- acting window는 SKILL.md가 context에 들어간 때부터 최소한 context를 떠날 때까지. held manifest에서 빠진 지원 file은 신규 목록에서 발견해도 읽기/모델 노출 금지; entry refresh와 재승인이 필요하다.
- fetched SKILL.md의 frontmatter를 YAML parse하고 **field-by-field 전체 비교**해야 한다. digest 일치만으로 catalog frontmatter 진실성을 증명하지 않는다.
- **“Hosts MUST NOT retrieve a skill's files ahead of need, whether on connection, on listing, or at approval.”** 승인 시 모든 file을 fetch하는 host는 transparent lazy path와 다르다. 검사 UI에서 사용자가 실제 읽기를 요청하는 상황과 연결 자동 prefetch를 구별한다.
- **“Hosts MUST NOT treat a digest match as a security boundary.”** 서버 또는 gateway가 manifest와 content를 함께 바꾸면 hash가 맞아도 trust/authorship는 생기지 않는다.

### 4.3 실행·allowed-tools·origin read

[Security L837–869](https://github.com/modelcontextprotocol/ext-skills/blob/167da6c0d42c247a8f8470228a10ca711e3f6c45/specification/stable/skills.mdx#L837-L869):

- **“A server being connected does not make its skill content authoritative.”** skill은 untrusted model input, remote tool invocation보다 높은 위험. model context 진입 시 originating server 표시 필수.
- **“Hosts MUST NOT allow MCP-served skill content to cause host-side code execution without explicit per-skill user approval.”** hooks/frontmatter scripts만 아니라 body가 Bash 등 execution tool 호출을 유도하는 경우도 포함한다.
- `allowed-tools` 및 filesystem/tool permission 확대 필드를 자동 honor 금지. 명시 승인 없는 MCP-origin `allowed-tools`는 ignore해야 한다. Agent Skills 기본문서의 ‘pre-approved tools’ 문구보다 이 MCP-origin gate가 적용된다.
- model-callable resource read는 origin server로 bind. A의 skill이 B를 읽게 하면 **per-call explicit approval**, 양쪽 server 이름 표시가 필요하다. host-assigned label을 쓰고 self-reported serverInfo.name을 신원으로 신뢰하지 않는다.
- **“Skills are data, not directives.”** 더 높은 instruction authority로 올리지 않는다. user policy가 load 여부를 지배한다.

### 4.4 승인 invalidation·cache·offline 한계

[Security L870–882](https://github.com/modelcontextprotocol/ext-skills/blob/167da6c0d42c247a8f8470228a10ca711e3f6c45/specification/stable/skills.mdx#L870-L882): persisted per-skill approval은 당시 **모든 URI+digest set**에 bind. file 추가·삭제·rotation 등 set이 바뀐 새 entry를 받으면 prior approval은 revoked, loading/executing 전 re-prompt. size mismatch 역시 verify failure지만 approval의 규범 binding 문구는 URI+digest set이다. 우리 projection revision에는 size/frontmatter/policy binding도 함께 포함하는 것이 안전한 추가 정책이다.

정확한 제한 문구: **“A host need not poll for changes.”** 즉 삭제/철회가 모든 host cache에 즉시 push된다고 보장하지 않는다. 기존 verified cache의 bytes와 held entry가 일치하면 서버의 변화가 아직 관측되지 않을 수 있다. already-in-context prose를 protocol이 지우거나 모델에서 ‘unlearn’하지 않는다.

cache는 (a) host만 쓰고 in-place 수정하지 못하는 영역, 또는 (b) **매 access cached bytes SHA-256 재계산** 중 하나가 필수. digest label/mtime 비교만으로 부족하다. cache는 **모든 filesystem-skill discovery path에서 제외**해야 하며 host 재시작·서버 disconnected 후에도 MCP-origin 실행 gate가 유지된다. user가 서버를 제거하면 cache 삭제는 SHOULD이지 임의 host의 완전한 물리 삭제 보장이 아니다.

`ttlMs/cacheScope`는 list/get에서 required이고 freshness hint이지 integrity·ACL·revocation 보증이 아니다([L328–337](https://github.com/modelcontextprotocol/ext-skills/blob/167da6c0d42c247a8f8470228a10ca711e3f6c45/specification/stable/skills.mdx#L328-L337), [L414–423](https://github.com/modelcontextprotocol/ext-skills/blob/167da6c0d42c247a8f8470228a10ca711e3f6c45/specification/stable/skills.mdx#L414-L423)). [SEP-2549](https://modelcontextprotocol.io/seps/2549-TTL-for-list-results#cache-scope)의 private은 다른 user에게 shared cache가 재사용하면 안 된다는 뜻이다. realm/project/credential-revision까지 자동 isolate하지 않는다. 여기서 읽은 SEP는 historical record이며 stable의 required field를 historical 예제로 완화하지 않는다.

**정책 추론:** company required rule의 current eligibility를 확인할 수 없는 offline 상태는 현행 strict native 지원 경로에서 fail closed 유지. read-only offline inspection은 ‘과거 snapshot/현재 승인 미확인’으로 명확히 표시할 수 있지만 live approved rule로 재승격하지 않는다. personal static reference offline UX를 별도 opt-in할 수 있어도 memory 권한과 범위를 넓히면 안 된다.

## 5. zero-root progressive disclosure와 catalog 비용

[Agent Skills specification](https://agentskills.io/specification#progressive-disclosure)은 metadata 약100 tokens/skill을 startup에, main instructions는 활성화 때, support files는 필요할 때 읽는 모델을 설명한다. 이것은 **관례/대략치**, 이 서버·host의 실측 token 수가 아니다. root CLAUDE.md/AGENTS.md에 corpus나 rulebook을 설치할 필요는 없다. stable도 server instructions pointer는 MAY이고 user/known URI로 시작할 수 있다.

그러나 **zero body ≠ zero context/cost**다:

1. `skills/list` wire entry는 name/description뿐 아니라 **verbatim 전체 frontmatter + complete 모든-file manifest**다. host는 이를 비모델 registry에 보관하고 모델에는 최소 routing metadata만 보낼 수 있지만, 그런 구현/측정 없이 ‘list metadata가 0 tokens’라고 하지 않는다.
2. [L227–241](https://github.com/modelcontextprotocol/ext-skills/blob/167da6c0d42c247a8f8470228a10ca711e3f6c45/specification/stable/skills.mdx#L227-L241): conforming host 수용 floor는 **512 files / 16MiB per skill**. 전역 skill count/listing 크기는 제한하지 않는다. URI+74-character digest 문자열+size+JSON overhead만도 file마다 비용이 있고 수백 manifest entry는 현행 memory 16KiB response cap을 넘을 수 있다. 파일 contents가 lazy라고 manifest 비용까지 사라지지 않는다.
3. pagination은 skill **entry 단위 atomic**이므로 한 skill의 512 manifests를 여러 pages로 쪼갤 수 없다. page count 제한·cursor-repeat 방어·ACL scope 및 snapshot-bound cursor가 provider 구현에 필요하다. pagination 자체가 across-page 동일 snapshot을 보장하지 않는다.
4. empty/partial listing이 허용되고 absence는 no-skills 증명이 아니다. known URI → one `skills/get`은 full catalog refresh를 피한다. catalog를 model에게 통째로 넣는 새 tool이나 초대형 index.json을 만들 필요가 없다.
5. private skill의 **name/description/path/frontmatter 자체도 회사 데이터**일 수 있다. ACL은 body뿐 아니라 list/get/directory metadata/read/cursor/cache 모두에 적용한다. 스코프 밖 entry가 존재한다는 signal도 숨길 필요가 있다.
6. 초기 projection을 검증 가능한 **소수의 작은 static workflow, 각 최소 파일**로 제한하면 현행 body cap과 충돌을 피할 수 있다. 이는 우리 server가 작은 skill만 **제공**하는 정책이지 extension의 host 수용 floor를 임의로 낮춘 ‘full host compliance’ 주장이 아니다.

## 6. released SDK와 가장 작은 실제 adapter

### 6.1 실제 설치 SDK2.3.0

Worktree `pyproject.toml:13`은 `mcp==2.3.0`. 기존 `.venv/lib/python3.12/site-packages/mcp-2.3.0.dist-info/METADATA`는 Name=mcp, Version=2.3.0, License=MIT, dependency `mcp-types==2.3.0`을 확인했다. 별도 setup/install은 실행하지 않았다.

설치 `mcp/server/extension.py:58–135`의 실제 generic API는 `MethodBinding(method, params_type, handler, protocol_versions)` 및 `Extension.identifier/settings/resources/methods`. `mcp/server/lowlevel/server.py`에는 discover와 ordinary resources, extensions capability map이 있다. 따라서 기존 SDK를 기반으로 custom handler adapter를 작성하는 **구조적 여지**는 있으나, 지금 memory server에 Skills가 준비됐다는 증거가 아니다. Skills wire models·result validation·complete bytes manifest·ACL/snapshot projection까지 직접 구현해야 한다. identifier만 advertise하는 것은 false capability가 된다.

### 6.2 새 merge의 공개 최소 구현: filesystem provider 불필요

[official example](https://github.com/modelcontextprotocol/python-sdk/blob/9a754b0aabb873d9707d52dc165b569fb442ec8c/docs_src/skills/tutorial001.py)은 in-memory static 한-file skill을 `Skill/SkillResource`로 만들고 SHA-256/UTF-8 size를 계산한다. 다음은 upstream 실제 끝부분이다(여기서 실행하지 않았다):

```python
async def list_skills(ctx: ServerRequestContext[Any, Any], params: ListSkillsParams) -> ListSkillsResult:
    return ListSkillsResult(skills=[GIT_WORKFLOW])

async def get_skill(ctx: ServerRequestContext[Any, Any], params: GetSkillParams) -> GetSkillResult:
    if params.uri != SKILL_URI:
        raise MCPError(code=INVALID_PARAMS, message=f"unknown skill: {params.uri}")
    return GetSkillResult(skill=GIT_WORKFLOW)

mcp = MCPServer("catalog", extensions=[Skills(list_skills=list_skills, get_skill=get_skill)])
mcp.add_resource(TextResource(uri=SKILL_URI, name="SKILL.md", mime_type="text/markdown", text=SKILL_MD))
```

이 새 API를 현재2.3.0에 복사해 import가 된다고 제시하면 안 된다. 새 merge의 [server adapter](https://github.com/modelcontextprotocol/python-sdk/blob/9a754b0aabb873d9707d52dc165b569fb442ec8c/src/mcp/server/skills.py)는 `Skills(Extension)`으로 two required MethodBinding, optional directoryRead, outbound model revalidation, 현대 protocol의 cache fields와 private default를 구현한다. [SDK doc](https://github.com/modelcontextprotocol/python-sdk/blob/9a754b0aabb873d9707d52dc165b569fb442ec8c/docs/advanced/skills.md)은 filesystem discovery/hash/catalog/cache policy를 **제공하지 않는다**고 명시한다. DB immutable projection으로 공급해도 된다. host YAML frontmatter 비교, persisted approval, permission gate, origin label, cache isolation도 SDK만으로 해결되지 않는다.

### 6.3 이미 있는 server/CLI에서 재사용할 작은 부분

- HF [skill-resources.ts](https://github.com/huggingface/hf-mcp-server/blob/dce2d5f0f16392e22d6f3fdc039681f4698e8cdf/packages/app/src/server/skills/skill-resources.ts)는 ordinary resources 등록+custom two methods+optional directory handler의 실존 예다. public cacheScope는 **공개 동일-user-independent content**에 관한 예시이지 company projection에 복사할 정책이 아니다.
- HF [loader](https://github.com/huggingface/hf-mcp-server/blob/dce2d5f0f16392e22d6f3fdc039681f4698e8cdf/packages/app/src/server/skills/skill-loader.ts)는 percent-decode 후 `.`/`..`/slash/backslash/NUL 금지, realpath containment, lstat regular-file, directory traversal symlink 거부, UTF-8 fatal decode, unique YAML keys, complete snapshot/byte count의 참고 구현이다. **lstat/realpath/read 사이 TOCTOU가 존재할 수 있다는 것은 코드 순서의 추론**이며 exploit 재현이 아니다. hostile mutable export tree에서는 디렉터리 immutable ownership 또는 FD/no-follow 기반 검사를 추가 검토한다. DB bytes를 직접 serve하면 arbitrary filesystem walk 자체를 줄일 수 있다.
- mcpc `verifyAgainstManifest`는 size→digest, `verifyFrontmatter`는 parsed 전체 fields, ambiguous name은 error로 disambiguate한다. 그러나 `resources:'dynamic'`이면 integrity check를 skip하고, `--raw`는 source/session prefix를 억제한다. 이것을 Bash를 통해 모델에게 그대로 pipe하면 downstream origin tag/approval/acting-window 증거가 빠진다. 일반 CLI verification을 완전한 secure skill activation으로 포장하지 않는다.

## 7. 공개 문서의 시차·roadmap 함정

[decision log](https://github.com/modelcontextprotocol/ext-skills/blob/167da6c0d42c247a8f8470228a10ca711e3f6c45/docs/decisions.md)는 source spec이 아니다.

- 과거 `skill://index.json`, archive distribution, no-nesting 결정은 2026-07-16 v1 scope에서 superseded. **packed/archive retrieval은 stable에 없음**. batch read·archives·well-known distribution·dynamic tool loading은 미래 후보다. ZIP 추출을 당장 extension 구현의 필수 요소로 만들지 않는다.
- log의 2026-07-15/07-16 문구 일부는 dynamic resources를 ‘omit’라고 남겨 두었다. stable는 **명시적 `"dynamic"`만 허용**하고 누락을 reject한다. 이 차이를 copy하지 않는다.
- 2026-09-08 accepted decision/PR #139(09-10 merge)은 list/get CacheableResult 필수와 resources capability dependency를 명시했다. 오래된 SEP/example에 cache fields가 없다고 stable를 완화할 수 없다.
- OpenAI [plugin importer](https://developers.openai.com/plugins/build/mcp-server#import-skills-from-the-mcp-server)는 자체가 draft bounded static subset이라고 적는다. stable 존재와 모순되는 global release 판단으로 쓰지 말고 **그 importer 제품 contract**로 해석한다. import는 모든 파일을 fetch하여 static plugin snapshot을 만드는 행위이고 live cache가 아니다. 재스캔+새 plugin version submission 없이는 변경 전파가 없다.
- fast-agent docs는 “Installation signals your approval for running.”이라고 제품 정책을 설명한다. canonical PG rule approval·host execution consent를 자동 동일시할 근거가 없다. local-copy 설치 경로는 별도 보안/배포 계약이다.

## 8. 현재 설계와의 접점: 유지할 것과 진짜 추가할 것

현행 [architecture.ko.md §5–7](file:///Users/namdoo/.agent-flow/worktrees/agent-memory-mcp-97e899f21134/feat-local-first-memory-pipeline/docs/architecture.ko.md)은 이번 조사에서 읽었고 수정하지 않았다.

### 이미 맞는 부분 — 다시 만들 필요 없음

- capture→typed extraction→entities/time/conditions→consolidation→hybrid recall/rerank→cited reflect→correction/retract/next-use. Skills extension은 이를 규정하지 않으므로 대체할 이유 없음.
- generated/reflect candidate ≠ approved rule; body/selector/exception/required/targets/authority/revision digest 결합 승인; **PG ledger 유일 정본**, Git/skill export는 projection.
- 정확한 local project, 승인된 personal project ID set, configured team/project audience; 새 scope 자동 포함 금지.
- connection instructions/corpus/rule body0, root AGENTS.md/CLAUDE.md rulebook 설치 안 함; opt-in bounded retrieval. 일반 MCP receipt가 model compliance를 증명하지 않음.
- auth/source/snapshot/deletion fences 및 immutable delivery lineage; OMP advisory/manual only, strict installation은 쓰기 전 거부.

### 실제 extension trial을 하면 새로 필요한 부분

1. **Projection record**: canonical approved rule revision→동일 UTF-8 bytes로 생성한 immutable `SKILL.md`/support files+complete manifest. projection format/version·source rule IDs·realm/binding·scope/target-set revision·authority/approval revision를 내부 binding에 보존한다. 문자열 metadata는 routing/provenance 설명일 뿐 host permission/approval authority가 아니다. `io.modelcontextprotocol/` reserved metadata key에 자체 의미를 몰래 넣지 않는다.
2. **모든 method 동일 authorization**: list/get/read/optional directory 및 cursor에서 현재 principal/realm/project grants, source/snapshot/approval/deletion/current projection revision recheck. 인증 user가 다른 realm에 같은 URI를 갖더라도 분리. realm prefix가 보인다고 ACL을 대체하지 않는다.
3. **Host loading contract**: origin-host label+URI key, per-skill consent, full manifest bytes verify+YAML compare, permission grant 별도, held-entry window, nested consent, cross-origin read approval. server만 변경하면 이 중 host obligations가 저절로 생기지 않는다.
4. **두 승인 축**: PG의 ‘규칙 권위/범위 승인’과 host의 ‘untrusted skill 사용/실행 grant 승인’은 별개. 둘 다 유효해야 보호 행동의 근거로 사용하며, skill 설치 클릭이 PG ledger write/required 승격을 하지 않는다. 룰이 selector/target/authority에서 바뀌면 content가 우연히 같아도 projection eligibility는 invalidation해야 한다.
5. **읽기와 철회**: gateway/user-private cache에 realm/principal/project binding/credential·approval epoch/projection revision을 추가 key로 둔다. host ledger 관측 전 offline cached read의 current authority를 주장하지 않는다. deletion 때 own projection을 deny/tombstone하고 own cache 제거·관련 receipt invalidate; arbitrary host stale copies·already-context·backup forensic erase는 보장 밖으로 명시한다.
6. **small static first**: single workflow의 소수 files, optional directoryRead 없음부터 시작. `resources:'dynamic'`은 company/required rule projection에 금지한다. model-generated candidate가 수시로 변경되는 ‘dynamic skill’로 자동 publish되지 않도록 한다.

## 9. 회사 local/deny-egress와 개인 cloud: 같은 core, 별도 경계

이 부분은 **제안/정책 추론**이며 Skills protocol의 자체 보장으로 읽으면 안 된다.

- **회사**: local PG+local projection/provider, explicit approved model egress 정책, deny third-party memory/skill store/telemetry. Claude/Codex team 계정은 third-party HF·Runlayer·skill marketplace·MCP gateway로 회사 data를 보내는 권한이 아니다. name/description/URI 및 query·logs도 정보다. MCP로 local bytes를 읽은 뒤 cloud model context로 보내는 행위도 egress이므로 host provider 경계까지 검토해야 한다. ‘local memory’는 ‘모델도 offline’이라는 뜻이 아니다.
- **개인**: 같은 extraction/ledger/projection core를 사용할 수 있지만 별도 realm, DB/storage namespace, credentials, cache root, auth profile, telemetry destination/consent. company corpus를 평가/실험용 personal cloud로 이동하지 않는다.
- profile만 나누면 완전 격리가 되지 않는다. OMP [config docs](https://github.com/can1357/oh-my-pi/blob/5d0aaffaf1f987503ce129a642fb6e30339615af/docs/mcp-config.md)는 user-level profile isolation이 있지만 project/external-tool config는 profile-independent, authorized URL credential은 profile 내 다른 checkout에서도 자동 적용될 수 있다고 설명한다. 동일 realm 사용 의도 없는 server 연결을 계정 자동 인증만으로 승인하지 않는다.
- logging은 기본 body-free+opaque refs·local retention, credentials/query/raw frontmatter/content는 기록하지 않는다. **body-free도 무조건 안전은 아니다.** HF [skill-event-logger](https://github.com/huggingface/hf-mcp-server/blob/dce2d5f0f16392e22d6f3fdc039681f4698e8cdf/packages/app/src/server/utils/skill-event-logger.ts)는 content/frontmatter를 제외하되 `targetUri`, userHash, client/session/version을 남기고, dataset/token 설정 시 HF transport를 사용한다. 이것은 구현 참고일 뿐 회사 기본 logging template으로 복사하지 않는다.
- 공급망: pinned source/release+license+업데이트 검토, small instruction-only projection 우선. signed provenance가 필요하면 별도 신뢰체계가 필요하며 unsigned digest는 서명/승인 대신이 아니다. scripts/hooks/network bootstrap·`npx latest`를 workflow가 요구한다고 자동 실행/egress grant 하지 않는다.

## 10. 최소 fallback와 권고 단계

### 지금 권고: 구현 cutover 없이 유지

**unsupported/unverified client의 가장 작은 안전 fallback은 현재 네 tool 그대로다.** 사용자가 해당 작업에서 명시적으로 `memory_context`를 호출하게 하고 bounded cited context를 받아, 필요한 ref만 `memory_inspect`로 확인한다. 생성은 candidate로 기록하고 승인·철회는 현재 ledger/control path를 사용한다. mandatory root files, full skill catalog, 별도 거대한 `load_skill`/tool registry를 추가하지 않는다. tool metadata/schema 비용은 기존대로 존재하며 0 token이라 부르지 않는다.

generic resource read가 이미 있는 host에서 **명시 known URI를 ordinary reference로 읽는 fallback**은 가능한 추가 선택지이나, 현 서버에 resource projection을 구현했다고 주장하지 않는다. 도입 시 host-assigned server를 특정하고 bounded/authorized read, ‘MCP-origin untrusted reference’ 표시, no execution/allowed-tools grant를 유지한다. 그것은 extension activation이 아니다. OMP의 [현재 skill URI handler](https://github.com/can1357/oh-my-pi/blob/5d0aaffaf1f987503ce129a642fb6e30339615af/packages/coding-agent/src/internal-urls/skill-protocol.ts)는 local skill을 먼저 고르고, 그 name이 없을 때 advertised MCP resource를 읽는다. [generic router](https://github.com/can1357/oh-my-pi/blob/5d0aaffaf1f987503ce129a642fb6e30339615af/packages/coding-agent/src/internal-urls/mcp-protocol.ts)는 URI를 광고한 첫 server를 찾을 수 있다. 따라서 같은 URI의 multi-origin skill security route로 쓰면 안 된다. **현재 fallback은 네-tool ref 경로가 더 작고 명확하다.**

### local trial 후에만 권고

회사 corpus 없는 synthetic fixture, 별도 scratch server/client, upstream 정식 release/pinned APIs, small static workflow 한 개로만 다음 acceptance를 부모가 별도 검증할 것을 권고한다(이번에는 실행하지 않음):

- actual native request의 client/server extension negotiation 및 unsupported host의 graceful ordinary-resource 동작;
- connection/list/approval에서 content prefetch 없음, routing metadata/wire bytes/실제 host tokens 실측;
- same URI/name multi-server·local collision, origin tags·cross-origin approval;
- bytes/size/YAML mismatch, unlisted file, nested allowed-tools, rotation/add/remove에 따른 re-consent;
- cache tamper/restart/disconnect, realm/credential/project change, stale/offline/revoke/delete 및 cursor-snapshot boundary;
- script/Bash/hook/egress 동작이 승인 없이 실행되지 않는지, required rule의 **기존 native guard**를 우회하지 않는지;
- 성공 시에도 ‘protocol conforms’와 ‘모델 준수/strict host coverage’를 별도 보고.

trial이 맞으면 tiny read-only projection adapter를 **기존 core 위에 additive opt-in**으로 제안할 수 있다. 새 Python merged Skills adapter는 filesystem provider 없이 PG projection handlers에 맞기 때문에 참고 가치가 크지만 지금2.3.0을 fork/upgrade하거나 formal-review patch에 섞지 않는다.

### 기각/보류

- skill package/export를 canonical rule authority로 전환, import/installation을 PG approval로 대체;
- candidate 자동 승인, `allowed-tools`/nested grant 자동 honor, protocol로 mandatory-rule 자연어 준수 강제 주장;
- root CLAUDE.md/AGENTS.md body/catalog 설치, eager corpus copy, giant tool/index/catalog 확대;
- dynamic manifest를 required/company rule에 사용, digest를 publisher trust/security boundary로 취급;
- third-party cloud/telemetry에 company name/metadata/query/corpus 전송;
- protocol TTL/manifest update가 arbitrary host caches에 즉시 철회를 전파한다는 보장;
- ChatGPT static plugin import·fast-agent local-copy·mcpc CLI verified output을 Claude Code/Codex/OMP의 live secure Skills activation과 동등시;
- archived archive/index.json roadmap을 현재 stable mandatory feature로 구현.

## 최종 결론

**채택 가능한 것은 작은 instruction/workflow projection의 표준 transport 계약이다. 현재 memory의 권위·범위·철회·검증 core를 바꿀 이유는 없다.** root files 없이 on-demand progressive disclosure는 가능하지만 metadata/catalog 비용과 host 지원·승인·cache 보안은 실재하는 별도 요구사항이다. 지금은 네-tool bounded reference fallback을 유지하고, 공식 SDK release와 native client activation 증거를 분리하여 작은 local trial을 설계하는 것이 최소 안전 경로다.
