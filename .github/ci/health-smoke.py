#!/usr/bin/env python3
"""Actions-only engineering smoke against the consumed product and PostgreSQL.

Only health-smoke.json is public. The uniquely owned RUNNER_TEMP directory is
intentionally retained, including exact requests, responses and failure evidence.
This is not native trust, human-presence, model, or original18 acceptance.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib
import importlib.metadata
import json
import os
import re
import secrets
import signal
import socket
import sys
import tempfile
import traceback
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

CASES = (
    "real_authority_ready", "producer_observer_body_free", "explicit_policy_opt_in",
    "frozen_workspace_preparation", "registration_and_exact_retry", "explicit_initial_observation",
    "grounded_claim_publication", "long_korean_complete_inspect", "independent_exact_approval",
    "dependency_change_refuses_approval", "complete_inspect_current_authority", "required_rule_approved",
    "exact_code_link_admission", "workspace_scoped_context", "changed_file_invalidates",
    "late_delivery_fenced", "operator_review_role_denial", "operator_reject_accept",
    "current_code_rebind", "required_rules_survive_ordinary_rejection",
    "observed_session_work", "late_session_input_fence", "bounded_session_assessment",
    "terminal_work_late_capture_ownership", "feedback_resolution_reason_disclosure",
)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def encoded(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def private_file(path: Path, raw: bytes) -> Path:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
    return path


class SmokeFailure(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code if re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", code) else "CONDITION_FAILED"


class Smoke:
    def __init__(self, root: Path, result: dict):
        self.root, self.result = root, result
        self.number = 0
        self.python = [sys.executable, *(["-I"] if sys.flags.isolated else [])]
        self.active = "real_authority_ready"
        self.server = None
        self.store = None
        self.admin = None
        self.schema = None
        self.schema_created = False
        self.schema_attempted = False
        self.host_install_attempted = False
        self.settings = None
        self.before = None
        self.module_root = None
        self.env = dict(os.environ)
        self.env.update(HOME=str(root / "home"), XDG_CONFIG_HOME=str(root / "home" / ".config"),
                        CLAUDE_CONFIG_DIR=str(root / "home" / ".claude"),
                        CODEX_HOME=str(root / "home" / ".codex"),
                        PYTHONDONTWRITEBYTECODE="1", NO_COLOR="1")
        self.env.pop("JEV_API_KEY", None)
        self.env.pop("TYPESAFE_API_KEY", None)
        (root / "home").mkdir(mode=0o700)
        (root / "home" / ".claude").mkdir(mode=0o700)
        self.config = root / "authority.json"
        self.project = root / "project"
        self.project.mkdir(mode=0o700)
        (self.project / "src").mkdir(mode=0o700)
        self.code = self.project / "src" / "cache.py"
        private_file(self.code, b"def cache():\n    return 'offline'\n")
        self.tokens = {}
        self.principals = {}
        self.binding = None

    def check(self, condition: bool, code: str):
        if not condition:
            raise SmokeFailure(code)

    def passed(self, case: str):
        self.result["outcomes"][case] = "passed"

    def begin(self, case: str):
        self.active = case

    def evidence(self, label: str, value) -> Path:
        self.number += 1
        return private_file(self.root / f"{self.number:04d}-{label}.json", encoded(value))

    def package_snapshot(self):
        files = sorted(path for path in self.module_root.rglob("*") if path.is_file()
                       and "__pycache__" not in path.parts and path.suffix != ".pyc")
        return {str(path.relative_to(self.module_root)): digest(path.read_bytes()) for path in files}

    async def process(self, argv, label):
        self.number += 1
        prefix = self.root / f"{self.number:04d}-{label}"
        private_file(prefix.with_suffix(".request"), encoded({"argv": argv}))
        with prefix.with_suffix(".stdout").open("xb") as out, prefix.with_suffix(".stderr").open("xb") as err:
            os.chmod(out.name, 0o600)
            os.chmod(err.name, 0o600)
            child = await asyncio.create_subprocess_exec(*argv, cwd=self.root, env=self.env,
                stdin=asyncio.subprocess.DEVNULL, stdout=out, stderr=err)
            try:
                await asyncio.wait_for(child.wait(), 25)
            finally:
                if child.returncode is None:
                    child.terminate()
                    try:
                        await asyncio.wait_for(child.wait(), 3)
                    except TimeoutError:
                        child.kill()
                        await asyncio.wait_for(child.wait(), 5)
        raw = prefix.with_suffix(".stdout").read_bytes()
        errors = prefix.with_suffix(".stderr").read_bytes()
        self.check(len(raw) <= 2 * 1024 * 1024 and len(errors) <= 65536, "PROCESS_OUTPUT_BOUND")
        return child.returncode, raw, errors

    async def cli(self, *arguments, role="operator", denied=()):
        argv = [*self.python, "-m", "agents_memory.cli", "--config", str(self.config),
                "--token-file", str(self.tokens[role]), *map(str, arguments)]
        returncode, raw, errors = await self.process(argv, "cli")
        if denied:
            self.check(returncode != 0, "CLI_EXPECTED_REFUSAL")
            response = json.loads(errors)
            self.check(response.get("error", {}).get("code") in denied, "CLI_REFUSAL_CODE")
            return response
        self.check(returncode == 0, "CLI_FAILED")
        value = json.loads(raw)
        self.check(isinstance(value, dict), "CLI_RESPONSE_SHAPE")
        return value

    async def api(self, route: str, payload: dict, *, role="agent", denied=()):
        import httpx2

        self.evidence("http-request", {"route": route, "role": role, "payload": payload})
        async with httpx2.AsyncClient(timeout=8, trust_env=False) as client:
            response = await client.post(self.settings.base_url + route, json=payload,
                headers={"Authorization": "Bearer " + self.tokens[role].read_text().strip()})
        raw = response.content
        private_file(self.root / f"{self.number:04d}-http-response", raw)
        self.check(len(raw) <= 262144, "HTTP_OUTPUT_BOUND")
        value = response.json()
        if denied:
            self.check(response.status_code >= 400, "HTTP_EXPECTED_REFUSAL")
            self.check(value.get("error", {}).get("code") in denied, "HTTP_REFUSAL_CODE")
        else:
            self.check(200 <= response.status_code < 300 and "error" not in value, "HTTP_FAILED")
        return value

    def mutation(self, kind: str, key: str, **fields):
        return {"kind": kind, "binding_id": self.binding, "expected_binding_revision": 1,
                "idempotency_key": key, **fields}

    async def apply(self, value: dict, *, role="operator", denied=()):
        path = self.evidence("health-command", value)
        return await self.cli("health", "apply", "--command-file", path, role=role, denied=denied)

    async def record(self, value: dict, *, denied=()):
        path = self.evidence("record-command", value)
        return await self.cli("record", "--judgment-file", path, role="agent", denied=denied)

    async def inspect(self, ref: str, *, role="agent", complete=False, window_bytes=4096, denied=()):
        args = ["inspect", "--binding", self.binding, "--ref", ref]
        if complete:
            args += ["--complete", "--max-total-bytes", "1048576", "--max-bytes", "1024"]
        elif window_bytes != 4096:
            args += ["--max-bytes", str(window_bytes)]
        return await self.cli(*args, role=role, denied=denied)

    async def capture(self, key: str, body: str, **fields):
        payload = {"binding_id": self.binding, "idempotency_key": key, "origin_key": key,
                   "body": body, "speaker": "human",
                   "coverage": {"status": "observed_window", "original_bytes": len(body.encode())}, **fields}
        return await self.api("/api/capture", payload, role="producer")

    async def setup(self):
        import asyncpg

        from agents_memory.config import Settings
        from agents_memory.domain import Role
        from agents_memory.journal import DeletionJournal
        from agents_memory.store import Store

        names = ("cli", "config", "store", "application", "edge", "health", "health_producer", "health_code")
        modules = {name: importlib.import_module("agents_memory." + name) for name in names}
        self.module_root = Path(modules["cli"].__file__).resolve().parent
        self.before = self.package_snapshot()
        self.result["consumed"] = {
            "distribution": importlib.metadata.version("agents-memory"),
            "module_identity": "agents_memory",
            "module_tree_digest": digest(encoded(self.before)),
            "modules": {name: {"identity": "agents_memory." + name,
                               "sha256": digest(Path(module.__file__).read_bytes())}
                        for name, module in modules.items()},
        }
        self.evidence("consumed-private-identities", {name: str(module.__file__) for name, module in modules.items()})
        identity_program = (
            "import importlib,json,pathlib,hashlib; "
            "names=" + repr(names) + "; "
            "mods={n:importlib.import_module('agents_memory.'+n) for n in names}; "
            "print(json.dumps({n:{'path':str(pathlib.Path(m.__file__).resolve()),"
            "'sha256':hashlib.sha256(pathlib.Path(m.__file__).read_bytes()).hexdigest()}"
            " for n,m in mods.items()}))"
        )
        returncode, stdout, _ = await self.process([*self.python, "-c", identity_program], "consumed-child-identity")
        self.check(returncode == 0, "CONSUMED_CHILD_IDENTITY_FAILED")
        child_identity = json.loads(stdout)
        self.check(all(child_identity[name]["path"] == str(Path(modules[name].__file__).resolve())
                       and child_identity[name]["sha256"] == self.result["consumed"]["modules"][name]["sha256"]
                       for name in names), "CONSUMED_CHILD_MODULE_MISMATCH")
        self.result["consumed"]["child_identity_matches"] = True
        raw_dsn = os.environ.get("PG_TEST_DSN")
        self.check(bool(raw_dsn), "PG_TEST_DSN_REQUIRED")
        parts = urlsplit(raw_dsn)
        query = dict(parse_qsl(parts.query))
        query.pop("schema", None)
        admin_dsn = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
        self.schema = "am_health_smoke_" + secrets.token_hex(16)
        self.evidence("owned-schema", {"schema": self.schema, "admin_dsn": admin_dsn})
        self.admin = await asyncpg.connect(admin_dsn, timeout=10, command_timeout=20)
        self.schema_attempted = True
        await self.admin.execute(f'CREATE SCHEMA "{self.schema}"')
        self.schema_created = True
        self.evidence("schema-created", {"schema": self.schema, "created": True})
        query["schema"] = self.schema
        dsn = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
        returncode, _, _ = await self.process(
            [*self.python, "-c", "from agents_memory.migrations import migrate; import sys; migrate(sys.argv[1])", dsn],
            "owned-schema-migration")
        self.check(returncode == 0, "PRIVATE_SCHEMA_MIGRATION_FAILED")
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        self.settings = Settings(deployment_id="health_smoke", realm="health_smoke", mode="company",
            database_dsn=dsn, migrator_dsn=dsn, state_dir=self.root / "authority",
            journal_dir=self.root / "independent-journal", port=port,
            max_http_body_bytes=262144, max_mcp_response_bytes=65536)
        self.settings.state_dir.mkdir(mode=0o700)
        self.settings.journal_dir.mkdir(mode=0o700)
        private_file(self.config, self.settings.model_dump_json().encode())
        self.store = Store(self.settings, DeletionJournal(self.settings.journal_dir, self.settings.deployment_id))
        self.result["setup_stage"] = "STORE_OPEN"
        await self.store.open()
        for role in ("operator", "agent", "producer", "reviewer"):
            self.tokens[role] = private_file(self.root / (role + ".token"), (secrets.token_urlsafe(48) + "\n").encode())
        self.result["setup_stage"] = "BOOTSTRAP"
        owner = await self.store.bootstrap(self.tokens["operator"].read_text().strip(), "engineering_owner")
        binding = await self.store.register_binding(owner, "Owned engineering health fixture", str(self.project), "register")
        self.binding = binding.id
        owner = await self.store.authenticate(self.tokens["operator"].read_text().strip())
        self.principals["operator"] = owner
        for role in ("agent", "producer"):
            self.principals[role] = await self.store.issue_token(owner, Role(role), (binding.id,), self.tokens[role].read_text().strip())
        # Fixture identity provisioning only: a distinct principal and credential,
        # not an independent human or native approval. All approvals use real CLI.
        reviewer_id = "credential_engineering_reviewer"
        async with self.store.pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute("SELECT singleton FROM am_clock WHERE singleton FOR UPDATE")
                await connection.execute("""INSERT INTO am_credentials(id,principal_id,realm,role,token_hash)
                    VALUES($1,$2,$3,'operator',$4)""", reviewer_id, "engineering_reviewer", self.settings.realm,
                    self.store._token_hash(self.tokens["reviewer"].read_text().strip()))
                await connection.execute("INSERT INTO am_grants(credential_id,binding_id) VALUES($1,$2)", reviewer_id, binding.id)
                await connection.execute("UPDATE am_clock SET epoch=epoch+1 WHERE singleton")
        self.principals["reviewer"] = await self.store.authenticate(self.tokens["reviewer"].read_text().strip())
        self.check(self.principals["reviewer"].id != owner.id, "INDEPENDENT_ACTOR_IDENTITY")
        self.evidence("fixture-principals", {key: value.model_dump(mode="json") for key, value in self.principals.items()})
        self.result["setup_stage"] = "SERVICE_START"
        # Keep the real CLI failure check reachable after Uvicorn replays TERM.
        launcher = private_file(self.root / "serve-entry.py",
            b"import signal\nfrom agents_memory.cli import main\n"
            b"signal.signal(signal.SIGTERM, lambda *_: None)\nmain()\n")
        out = (self.root / "service.stdout").open("xb")
        err = (self.root / "service.stderr").open("xb")
        os.chmod(out.name, 0o600)
        os.chmod(err.name, 0o600)
        try:
            self.server = await asyncio.create_subprocess_exec(*self.python, str(launcher),
                "--config", str(self.config), "serve", cwd=self.root, env=self.env,
                stdin=asyncio.subprocess.DEVNULL, stdout=out, stderr=err)
            self.evidence("owned-service", {"pid": self.server.pid,
                "proc_stat": Path(f"/proc/{self.server.pid}/stat").read_text(),
                "proc_cmdline_digest": digest(Path(f"/proc/{self.server.pid}/cmdline").read_bytes()),
                "config": str(self.config)})
        finally:
            out.close()
            err.close()
        import httpx2

        async with asyncio.timeout(20):
            self.result["setup_stage"] = "READINESS"
            async with httpx2.AsyncClient(timeout=1, trust_env=False) as client:
                while True:
                    self.check(self.server.returncode is None, "SERVICE_EXITED")
                    try:
                        response = await client.get(self.settings.base_url + "/readyz")
                        if response.status_code == 200 and response.json().get("ready") is True:
                            self.result["setup_stage"] = "READINESS_EVIDENCE"
                            self.evidence("readiness", response.json())
                            break
                    except httpx2.TransportError:
                        pass
                    await asyncio.sleep(0.1)
        self.passed("real_authority_ready")

    async def observer_and_workspace(self):
        self.begin("producer_observer_body_free")
        initial = await self.cli("health", "observer", "--binding", self.binding, role="producer")
        self.check(initial["kind"] == "health_observer" and initial["policy"]["enabled"] is False,
                   "POLICY_NOT_DEFAULT_DISABLED")
        self.check(not {"claims", "sources", "body", "reason", "catalog"}.intersection(initial), "OBSERVER_BODY_DISCLOSURE")
        await self.api("/api/health/observer", {"binding_id": self.binding}, denied=("SCOPE_DENIED", "ROLE_DENIED"))
        await self.api("/api/health/observer", {"binding_id": "binding_outside_scope"}, role="producer",
                       denied=("SCOPE_DENIED",))
        await self.api("/api/inspect", {"binding_id": self.binding, "ref": "health"}, role="producer",
                       denied=("SCOPE_DENIED",))
        self.passed("producer_observer_body_free")
        self.begin("explicit_policy_opt_in")
        policy = self.mutation("health_policy", "enable-health", expected_policy_revision=0, enabled=True,
                               allow_jev_health=False)
        await self.apply(policy, role="agent", denied=("SCOPE_DENIED",))
        await self.apply(policy)
        observer = await self.cli("health", "observer", "--binding", self.binding, role="producer")
        self.check(observer["policy"]["enabled"] and not observer["policy"]["allow_jev_health"], "EXPLICIT_POLICY")
        self.passed("explicit_policy_opt_in")
        self.begin("frozen_workspace_preparation")
        self.host_install_attempted = True
        installed = await self.cli("host-install", "--project", self.project, "--binding", self.binding,
            "--host", "claude", "--agent-token-file", self.tokens["agent"],
            "--producer-token-file", self.tokens["producer"])
        self.receipt = Path(installed["receipt"])
        self.check(self.receipt.is_relative_to(self.root), "RECEIPT_OUTSIDE_OWNED_ROOT")
        receipt = json.loads(self.receipt.read_bytes())
        self.runtime = Path(receipt["runtime_dir"])
        self.check(self.runtime.is_relative_to(self.root), "RUNTIME_OUTSIDE_OWNED_ROOT")
        self.prepared = self.root / "workspace-prepared.json"
        await self.cli("health", "workspace-prepare", "--receipt", self.receipt,
            "--workspace-id", "workspace_engineering", "--producer-credential-id", self.principals["producer"].credential_id,
            "--binding-revision", "1", "--workspace-revision", "0", "--key", "register-workspace",
            "--prepared-file", self.prepared)
        self.frozen = self.prepared.read_bytes()
        self.check(bool(json.loads(self.frozen)["config"]["pin"]["nonce"]), "FROZEN_NONCE_MISSING")
        self.check(not (self.runtime / "health-workspace.json").exists(), "PREMATURE_ACTIVATION")
        self.check(self.prepared.stat().st_mode & 0o077 == 0, "PREPARATION_NOT_PRIVATE")
        self.passed("frozen_workspace_preparation")
        self.begin("registration_and_exact_retry")
        first = await self.cli("health", "workspace-register", "--receipt", self.receipt, "--prepared-file", self.prepared)
        second = await self.cli("health", "workspace-register", "--receipt", self.receipt, "--prepared-file", self.prepared)
        self.check(first["workspace_configured"] and second["workspace_configured"] and
                   first["operation"]["id"] == second["operation"]["id"], "REGISTRATION_RETRY_CHANGED")
        self.check(self.prepared.read_bytes() == self.frozen, "PREPARATION_MUTATED")
        active = json.loads((self.runtime / "health-workspace.json").read_bytes())
        self.check(active == json.loads(self.frozen)["config"], "ACTIVATION_IDENTITY_CHANGED")
        observer = await self.cli("health", "observer", "--binding", self.binding, role="producer")
        self.check(observer["workspaces"][0]["root_fingerprint"] == json.loads(self.frozen)["command"]["root_fingerprint"],
                   "LIVE_REGISTRATION_MISMATCH")
        self.passed("registration_and_exact_retry")
        self.begin("explicit_initial_observation")
        paths = self.evidence("explicit-paths", [{"relative_path": "src/cache.py", "symbol_names": ["cache"]}])
        observed = await self.cli("health", "observe", "--receipt", self.receipt, "--paths-file", paths)
        self.check(observed["state"] == "observed" and observed["files"] == 1 and
                   observed["coverage"] == "explicit_paths", "INITIAL_OBSERVATION_NOT_COMMITTED")
        view = await self.inspect("health:workspace:workspace_engineering", complete=True)
        self.observation = next(item["ref"] for item in view["observations"] if item["symbol_name"] == "cache")
        self.check(next(item for item in view["observations"] if item["symbol_name"] == "cache")
                   ["metadata"]["file_digest"] == digest(self.code.read_bytes()), "OBSERVED_CODE_DIGEST")
        self.passed("explicit_initial_observation")

    async def publish_claim(self):
        self.begin("grounded_claim_publication")
        source = await self.capture("claim-source", "CacheKey is retained offline.")
        self.source = source["source_id"]
        window = await self.inspect(self.source)
        span = window["span_inventory"][0]
        command = {"kind": "source_selection", "binding_id": self.binding, "idempotency_key": "publish-claim",
            "admission_id": window["admission_id"], "reason": "Engineering caller inspected this exact original window.",
            "source_id": self.source, "source_revision": window["source_revision"],
            "binding_revision": window["binding_revision"], "snapshot": None,
            "byte_start": window["byte_start"], "byte_end": window["byte_end"], "window_digest": window["window_digest"],
            "policy_revision": window["policy_revision"], "policy_epoch": window["policy_epoch"],
            "label": "remember", "coverage": "complete_window", "rejection_comparisons": [],
            "extraction": {"claims": [{"assertion_id": "a0001", "assertion_span_id": span["span_id"],
                "statement": window["body"], "kind": "fact", "subject": "CacheKey", "predicate": "retained",
                "object": "offline", "polarity": "positive", "modality": "asserted", "entities": ["CacheKey"]}],
                "individual_qualifications": [], "shared_qualifications": [], "validities": [],
                "unused_span_ids": [item["span_id"] for item in window["span_inventory"][1:]]}}
        selected = await self.record(command)
        self.check(selected["state"] == "candidate_ready", "CLAIM_PUBLICATION_FAILED")
        selection = await self.inspect(selected["artifact_id"], complete=True)
        self.check(len(selection["claim_ids"]) == 1, "CLAIM_IDENTITY_AMBIGUOUS")
        self.claim = selection["claim_ids"][0]
        self.claim_ref = {"id": self.claim, "revision": 1}
        self.passed("grounded_claim_publication")

    async def approval(self, proposal: dict, key: str, *, denied=()):
        return await self.cli("rule", "approve", "--ref", proposal["proposal_id"], "--digest", proposal["digest"],
            "--scope", "local_project", "--target", self.binding, "--roster-revision", proposal["target_set_revision"],
            "--key", key, role="reviewer", denied=denied)

    async def proposals(self):
        self.begin("long_korean_complete_inspect")
        body = "한국어 제안: 고객 원문과 비밀을 외부 서비스로 보내지 않으며 승인된 범위만 사용한다.\n" * 70
        self.check(len(body.encode()) > 4096, "LONG_PROPOSAL_TOO_SHORT")
        body_file = private_file(self.root / "korean-proposal.txt", body.encode())
        exceptions = ["사용자가 해당 작업과 정확한 전송 대상을 별도로 승인한 경우만 예외로 한다.",
                      "가상 테스트 자료에는 실제 고객 정보를 포함하지 않는다."]
        sources = [await self.capture("proposal-evidence-" + str(index), "독립 근거 " + str(index) + ": 예외와 범위를 확인한다.")
                   for index in range(3)]
        arguments = ["rule", "propose", "--binding", self.binding, "--body-file", body_file, "--key", "korean-proposal"]
        for item in sources:
            arguments += ["--source", item["source_id"]]
        for exception in exceptions:
            arguments += ["--exception", exception]
        proposal = await self.cli(*arguments, role="agent")
        partial = await self.inspect(proposal["proposal_id"], window_bytes=1024)
        self.check(partial.get("draft_window", {}).get("next_byte") is not None, "PROPOSAL_DID_NOT_PAGE")
        complete = await self.inspect(proposal["proposal_id"], role="reviewer", complete=True)
        self.check(complete["body"] == body and complete["exceptions"] == exceptions, "COMPLETE_PROPOSAL_CONTENT")
        self.check(complete["digest"] == proposal["digest"] and complete["candidate"] is True, "COMPLETE_PROPOSAL_DIGEST")
        expected_sources = {item["source_id"] for item in sources} | {proposal["source_id"]}
        self.check({item["id"] for item in complete["input_sources"]} == expected_sources
                   and all(item["revision"] == 1 for item in complete["input_sources"]), "PROPOSAL_EXACT_SOURCES")
        self.check(complete["body_source_ref"] == {"id": proposal["source_id"], "revision": 1}, "PROPOSAL_BODY_IDENTITY")
        self.check(complete["inspection_authority"]["credential_id"] == self.principals["reviewer"].credential_id,
                   "INSPECTION_CURRENT_AUTHORITY")
        # Independently reassemble the real API windows as evidence of the CLI's
        # exact UTF-8 bytes/digest, without calling its reassembly implementation.
        cursor, chunks, identity = 0, [], None
        for _ in range(512):
            page = await self.api("/api/inspect", {"binding_id": self.binding, "ref": proposal["proposal_id"],
                "byte_start": cursor, "max_bytes": 1024}, role="reviewer")
            window = page["draft_window"]
            current = (window["digest"], window["total_bytes"])
            if identity is None:
                identity = current
            self.check(current == identity and window["byte_start"] == cursor, "WINDOW_IDENTITY_CHANGED")
            chunk = window["body"].encode()
            self.check(window["byte_end"] == cursor + len(chunk), "WINDOW_BYTE_CURSOR")
            chunks.append(chunk)
            cursor = window["byte_end"]
            if window["next_byte"] is None:
                break
            self.check(window["next_byte"] == cursor, "WINDOW_CONTINUATION_CURSOR")
        else:
            raise SmokeFailure("WINDOW_COUNT_BOUND")
        raw = b"".join(chunks)
        self.check(len(raw) == identity[1] and digest(raw) == identity[0], "REASSEMBLY_DIGEST")
        document = json.loads(raw)
        # epoch is live per transport call; all stored identity/content fields agree.
        self.check({key: value for key, value in document.items() if key != "epoch"} ==
                   {key: value for key, value in complete.items() if key != "epoch"}, "CLI_REASSEMBLY_MISMATCH")
        self.result["proposal_bytes"] = len(body.encode())
        self.result["proposal_windows"] = len(chunks)
        self.passed("long_korean_complete_inspect")
        self.begin("independent_exact_approval")
        active = await self.approval(proposal, "approve-exact-korean")
        self.check(active["body"] == body and active["exceptions"] == exceptions and
                   active["target_bindings"] == [self.binding], "EXACT_APPROVAL_CONTENT")
        self.passed("independent_exact_approval")
        self.begin("dependency_change_refuses_approval")
        stale_args = arguments.copy()
        stale_args[stale_args.index("korean-proposal")] = "korean-stale-proposal"
        stale = await self.cli(*stale_args, role="agent")
        await self.inspect(stale["proposal_id"], role="reviewer", complete=True)
        await self.cli("retract", "--binding", self.binding, "--ref", sources[0]["source_id"], "--key", "change-proposal-dependency")
        await self.approval(stale, "refuse-changed-dependency", denied=("APPROVAL_STALE", "INPUT_INELIGIBLE", "SOURCE_INELIGIBLE", "REF_INELIGIBLE"))
        self.passed("dependency_change_refuses_approval")
        self.begin("complete_inspect_current_authority")
        redacted = await self.inspect(stale["proposal_id"], role="reviewer", complete=True)
        self.check(redacted["state"] == "retracted" and "body" not in redacted and "draft_window" not in redacted,
                   "COMPLETE_INSPECTION_DISCLOSED_STALE_DEPENDENCY")
        self.passed("complete_inspect_current_authority")
        self.begin("required_rule_approved")
        short = private_file(self.root / "required-rule.txt", b"Always verify authorization before reusing CacheKey.\n")
        required = await self.cli("rule", "propose", "--binding", self.binding, "--body-file", short,
                                  "--required", "--key", "required-rule")
        self.required = await self.approval(required, "approve-required")
        self.passed("required_rule_approved")

    async def claim_health(self, *, role="operator", observation=None):
        ref = "health:claim:" + self.claim
        if observation:
            ref += ":observation:" + observation
        return await self.inspect(ref, role=role)

    async def review_command(self, decision, key, *, observations=(), role="operator"):
        view = await self.claim_health(role=role)
        return self.mutation("memory_review", key, admission_id=view["admission"]["id"],
            claim_ref=self.claim_ref, expected_health_version=view["health"]["version"],
            expected_review_event_id=view["health"]["review_event_id"], decision=decision,
            reason="Engineering operator reviewed the exact claim; human presence remains unattested.",
            revalidated_observation_refs=list(observations))

    async def context(self, *, admission=None, relevance=None, workspace=True, denied=()):
        arguments = ["context", "--binding", self.binding, "--query-file", self.query,
                     "--path", "src/cache.py", "--max-bytes", "6144", "--limit", "3"]
        if workspace:
            arguments += ["--code-workspace-id", "workspace_engineering"]
        if admission:
            arguments += ["--admission-id", admission, "--relevance-file", self.evidence("relevance", relevance)]
        return await self.cli(*arguments, role="agent", denied=denied)

    def judgments(self, pool):
        return [{"claim_id": item["claim_id"], "relevant": item["claim_id"] == self.claim,
                 "reason": "Engineering caller inspected this admitted CacheKey candidate."}
                for item in pool["candidate_manifest"]]

    def check_rules(self, context):
        rules = json.loads(context["context"])["approved_rules"]
        self.check(self.required["id"] in {item["ref"] for item in rules}, "REQUIRED_RULE_LOST")

    async def health_boundaries(self):
        self.begin("exact_code_link_admission")
        view = await self.claim_health(role="agent", observation=self.observation)
        command = self.mutation("code_link", "link-exact-code", admission_id=view["admission"]["id"],
            claim_ref=self.claim_ref, expected_health_version=view["health"]["version"],
            observation_refs=[self.observation], reason="This exact ordinary claim depends on the inspected cache symbol.")
        wrong = {**command, "idempotency_key": "wrong-exact-claim", "claim_ref": {"id": self.claim, "revision": 2}}
        await self.record(wrong, denied=("HEALTH_STALE", "ADMISSION_STALE"))
        linked = await self.record(command)
        self.check(linked["state"] == "health_recorded", "CODE_LINK_NOT_RECORDED")
        self.passed("exact_code_link_admission")
        self.begin("workspace_scoped_context")
        self.query = private_file(self.root / "query.txt", b"CacheKey offline")
        pool = await self.context()
        self.check(self.claim in {item["claim_id"] for item in pool["candidate_manifest"]}, "CURRENT_CODE_CLAIM_MISSING")
        self.check_rules(pool)
        selected = await self.context(admission=pool["admission_id"], relevance=self.judgments(pool))
        self.check(self.claim in selected["refs"], "CURRENT_CODE_NOT_DELIVERED")
        self.check_rules(selected)
        unscoped = await self.context(workspace=False)
        self.check(self.claim not in {item["claim_id"] for item in unscoped.get("candidate_manifest", [])}, "CODE_SCOPE_NOT_ENFORCED")
        inflight = await self.context()
        self.passed("workspace_scoped_context")
        self.begin("changed_file_invalidates")
        private_file(self.root / "original-code", self.code.read_bytes())
        with self.code.open("wb") as stream:
            stream.write(b"def cache():\n    return 'changed'\n")
        observed = await self.cli("health", "observe", "--receipt", self.receipt)
        self.check(observed["state"] == "observed" and observed["files"] == 1, "CHANGED_OBSERVATION_NOT_COMMITTED")
        changed = await self.claim_health()
        self.check(changed["health"]["freshness"] == "stale" and not changed["health"]["reusable"], "CHANGED_CODE_STILL_REUSABLE")
        current = await self.context()
        self.check(self.claim not in {item["claim_id"] for item in current.get("candidate_manifest", [])}, "STALE_CODE_RECALLED")
        self.check_rules(current)
        self.passed("changed_file_invalidates")
        self.begin("late_delivery_fenced")
        await self.context(admission=inflight["admission_id"], relevance=self.judgments(inflight),
                           denied=("CONTEXT_STALE", "ADMISSION_STALE"))
        self.passed("late_delivery_fenced")
        self.begin("operator_review_role_denial")
        forged = await self.review_command("accept", "agent-review-denied", role="agent")
        await self.apply(forged, role="agent", denied=("SCOPE_DENIED",))
        self.check((await self.claim_health())["health"]["review_event_id"] is None, "DENIED_REVIEW_MUTATED")
        self.passed("operator_review_role_denial")
        self.begin("operator_reject_accept")
        await self.apply(await self.review_command("reject", "operator-reject"))
        rejected = await self.claim_health()
        self.check(rejected["health"]["operator_review"] == "reject" and not rejected["health"]["reusable"], "OPERATOR_REJECT_FAILED")
        await self.apply(await self.review_command("accept", "cannot-waive-stale-code"), denied=("CODE_ANCHOR_INVALID",))
        self.passed("operator_reject_accept")
        self.begin("current_code_rebind")
        workspace = await self.inspect("health:workspace:workspace_engineering", complete=True)
        replacement = next(item["ref"] for item in workspace["observations"] if item["symbol_name"] == "cache")
        await self.apply(await self.review_command("accept", "rebind-current-code", observations=[replacement]))
        accepted = await self.claim_health()
        self.check(accepted["health"]["operator_review"] == "accept" and accepted["health"]["reusable"], "CURRENT_CODE_REBIND_FAILED")
        event = await self.inspect("health:event:" + accepted["health"]["review_event_id"], role="operator", complete=True)
        self.check(event["payload"]["provenance"] == "human_presence_unattested", "HUMAN_PRESENCE_OVERCLAIM")
        pool = await self.context()
        self.check(self.claim in {item["claim_id"] for item in pool["candidate_manifest"]}, "REBOUND_CLAIM_MISSING")
        async with self.store.pool.acquire() as connection:
            selection = await connection.fetchrow("""SELECT q.id,q.policy_revision
                FROM am_source_selections q JOIN am_claims c ON c.selection_id=q.id WHERE c.id=$1""", self.claim)
            await connection.execute("UPDATE am_source_selections SET policy_revision=$2 WHERE id=$1",
                                     selection["id"], "0" * 64)
        try:
            await self.apply(await self.review_command("accept", "review-obsolete-classification",
                                                       observations=[replacement]))
            obsolete_review = await self.claim_health()
            self.check(obsolete_review["health"]["operator_review"] == "accept" and
                       obsolete_review["health"]["reusable"] is False, "REVIEW_PROMOTED_OBSOLETE_CLASSIFICATION")
            obsolete_pool = await self.context()
            self.check(obsolete_pool["health"]["ordinary_claims"] == pool["health"]["ordinary_claims"] - 1,
                       "OBSOLETE_POLICY_IN_HEALTH_DENOMINATOR")
            self.check(obsolete_pool["coverage"]["unclassified_sources"] ==
                       pool["coverage"]["unclassified_sources"] + 1, "OBSOLETE_POLICY_SOURCE_COVERAGE")
            self.evidence("current-policy-health-qualification", {
                "before": pool["health"], "obsolete": obsolete_pool["health"],
                "coverage": obsolete_pool["coverage"], "review": obsolete_review["health"],
            })
        finally:
            async with self.store.pool.acquire() as connection:
                await connection.execute("UPDATE am_source_selections SET policy_revision=$2 WHERE id=$1",
                                         selection["id"], selection["policy_revision"])
        restored_pool = await self.context()
        self.check(restored_pool["health"]["ordinary_claims"] == pool["health"]["ordinary_claims"],
                   "INDEPENDENT_CURRENT_POLICY_NOT_PRESERVED")
        self.check((await self.claim_health())["health"]["reusable"] is True, "CURRENT_POLICY_REUSE_NOT_RESTORED")
        self.passed("current_code_rebind")
        self.begin("required_rules_survive_ordinary_rejection")
        await self.apply(await self.review_command("reject", "ordinary-reject-preserve-rules"))
        context = await self.context()
        self.check_rules(context)
        self.check(self.claim not in {item["claim_id"] for item in context.get("candidate_manifest", [])}, "REJECTED_CLAIM_RECALLED")
        await self.apply(await self.review_command("accept", "ordinary-accept-current", observations=[replacement]))
        observer = await self.cli("health", "observer", "--binding", self.binding, role="producer")
        self.check("CacheKey is retained offline." not in json.dumps(observer), "OBSERVER_LEAKED_CLAIM")
        self.check(not {"claims", "sources", "body", "reason", "catalog"}.intersection(observer), "OBSERVER_BODY_FIELDS")
        self.passed("required_rules_survive_ordinary_rejection")

    def assessment(self, view, key):
        return self.mutation("health_assessment", key, admission_id=view["admission"]["id"],
            pending_id=view["pending_id"], health_manifest_digest=view["health_manifest_digest"],
            input_sources=view["input_sources"], input_claims=view["input_claims"],
            assessments=[{"claim_ref": item, "support": "unknown", "freshness": "unknown", "relevance": "related",
                "reason": "Bounded engineering evidence does not establish full session or human presence."}
                for item in view["input_claims"]])

    async def sessions(self):
        self.begin("observed_session_work")
        common = {"stream_id": "stream_engineering", "segment_id": "segment_engineering",
                  "root_run_id": "run_engineering", "agent_path": "engineering_agent",
                  "claim_refs": [self.claim_ref], "coverage": "partial",
                  "gaps": ["HOST_HUMAN_PRESENCE_UNATTESTED", "HOST_SESSION_WINDOW_UNOBSERVED"]}
        await self.apply(self.mutation("session_observation", "session-start", event_id="event_start",
            sequence=1, event="start", **common), role="producer")
        ended = await self.apply(self.mutation("session_observation", "session-end", event_id="event_end",
            sequence=2, event="end", origin_keys=["late-session-source"], **common), role="producer")
        self.check(ended["state"] == "health_recorded", "SESSION_END_NOT_COMMITTED")
        pending = await self.inspect("health")
        self.check(pending["coverage"]["complete"] and pending["next_byte"] is None, "SESSION_PENDING_PAGE_INCOMPLETE")
        first = None
        for item in pending["items"]:
            view = await self.inspect(item["ref"])
            if "SESSION_ORIGIN_PENDING" in view.get("coverage", {}).get("gaps", []):
                first = view
                break
        self.check(first is not None and self.claim_ref in first["input_claims"], "SESSION_WORK_NOT_OBSERVED")
        self.check(not first["coverage"]["complete"], "SESSION_COMPLETENESS_OVERCLAIM")
        self.passed("observed_session_work")
        self.begin("late_session_input_fence")
        old = self.assessment(first, "old-session-assessment")
        late = await self.capture("late-session-source", "CacheKey session evidence remains bounded and incomplete.",
                                  root_run_id="run_engineering", agent_path="engineering_agent")
        current = await self.inspect("health:item:" + first["pending_id"])
        self.check(current["pending_id"] == first["pending_id"] and
                   current["health_manifest_digest"] != first["health_manifest_digest"], "LATE_SESSION_MANIFEST_UNCHANGED")
        self.check(late["source_id"] in {item["id"] for item in current["input_sources"]}, "LATE_SOURCE_NOT_ADMITTED")
        await self.record(old, denied=("ADMISSION_STALE", "HEALTH_STALE"))
        self.passed("late_session_input_fence")
        self.begin("bounded_session_assessment")
        recorded = await self.record(self.assessment(current, "current-bounded-session-assessment"))
        self.check(recorded["state"] == "health_recorded", "SESSION_ASSESSMENT_NOT_RECORDED")
        event = await self.inspect("health:event:" + recorded["artifact_id"], role="operator", complete=True)
        self.check(event["payload"]["health_manifest_digest"] == current["health_manifest_digest"], "ASSESSMENT_MANIFEST_NOT_PERSISTED")
        self.check(not event["payload"]["coverage"]["complete"], "ASSESSMENT_COVERAGE_OVERCLAIM")
        remaining = await self.inspect("health")
        self.check(first["pending_id"] not in {item["pending_id"] for item in remaining["items"]},
                   "BOUNDED_SESSION_WORK_NOT_COMPLETED")
        await self.apply(self.mutation("session_observation", "unresolved-segment-end",
            event_id="event_unresolved_end", sequence=1, event="end", origin_keys=["unavailable-origin"],
            **{**common, "segment_id": "segment_unknown_engineering"}), role="producer")
        unknown_page = await self.inspect("health")
        unknown_item = next(item for item in unknown_page["items"] if item["state"] in {"pending", "held"})
        unknown_work = await self.inspect(unknown_item["ref"])
        self.check("SESSION_ORIGIN_PENDING" in unknown_work["coverage"]["gaps"], "UNKNOWN_INPUT_WATERMARK_LOST")
        close_unknown = self.mutation("health_work_disposition", "close-unassessable-work",
            pending_id=unknown_item["pending_id"], expected_pending_revision=unknown_item["health_revision"],
            decision="close_unknown", reason="Missing observed inputs cannot establish fact freshness or full-session coverage.")
        await self.apply({**close_unknown, "idempotency_key": "agent-cannot-close-work"}, role="agent", denied=("SCOPE_DENIED",))
        await self.apply(close_unknown)
        closed = await self.inspect(unknown_item["ref"])
        self.check(closed["state"] == "resolved" and closed["disposition"] == "close_unknown"
                   and closed["assessment_complete"] is False and closed["admission"] is None,
                   "UNKNOWN_WORK_MISREPRESENTED_AS_ASSESSED")
        context = await self.context()
        self.check(context["partial"] and context["health"]["closed_unknown_work"] == 1, "UNKNOWN_WORK_HIDDEN_AS_READY")
        await self.apply({**close_unknown, "idempotency_key": "late-close-work"}, denied=("HEALTH_STALE",))
        await self.apply({**close_unknown, "idempotency_key": "reopen-unassessable-work",
            "decision": "reopen", "expected_pending_revision": closed["health_revision"]})
        reopened = await self.inspect(unknown_item["ref"])
        self.check(reopened["admission"] is not None and "SESSION_ORIGIN_PENDING" in reopened["coverage"]["gaps"],
                   "EXACT_UNKNOWN_WORK_REOPEN_FAILED")
        self.passed("bounded_session_assessment")
        self.begin("terminal_work_late_capture_ownership")
        reopened_page = await self.inspect("health")
        reopened_item = next(item for item in reopened_page["items"]
                             if item["pending_id"] == unknown_item["pending_id"])
        await self.apply({**close_unknown, "idempotency_key": "reclose-unassessable-work",
            "expected_pending_revision": reopened_item["health_revision"]})
        reclosed = await self.inspect(unknown_item["ref"])
        observed = await self.capture("unavailable-origin", "CacheKey newly observed evidence remains bounded.",
            root_run_id=common["root_run_id"], agent_path=common["agent_path"])
        retained = await self.inspect(unknown_item["ref"])
        self.check(retained["state"] == "resolved" and retained["disposition"] == "close_unknown"
                   and retained["assessment_complete"] is False and retained["admission"] is None,
                   "LATE_CAPTURE_REOPENED_OPERATOR_DISPOSITION")
        await self.apply({**close_unknown, "idempotency_key": "stale-reopen-after-late-capture",
            "decision": "reopen", "expected_pending_revision": reclosed["health_revision"]}, denied=("HEALTH_STALE",))
        await self.apply({**close_unknown, "idempotency_key": "exact-reopen-after-late-capture",
            "decision": "reopen", "expected_pending_revision": retained["health_revision"]})
        resumed = await self.inspect(unknown_item["ref"])
        self.check(observed["source_id"] in {item["id"] for item in resumed["input_sources"]}
                   and resumed["admission"] is not None and not resumed["coverage"]["complete"],
                   "EXPLICIT_REOPEN_DID_NOT_EXPOSE_BOUNDED_LATE_EVIDENCE")
        self.passed("terminal_work_late_capture_ownership")

    async def feedback_reasons(self):
        self.begin("feedback_resolution_reason_disclosure")
        source = await self.capture("scoped-feedback-source", "CacheKey scoped evidence remains bounded.",
                                    snapshot="snapshot_alpha")
        window = await self.cli("inspect", "--binding", self.binding, "--ref", source["source_id"],
                                "--snapshot", "snapshot_alpha")
        span = window["span_inventory"][0]
        selected = await self.record({
            "kind": "source_selection", "binding_id": self.binding, "idempotency_key": "publish-scoped-feedback-claim",
            "admission_id": window["admission_id"], "reason": "Engineering caller inspected this exact scoped original window.",
            "source_id": source["source_id"], "source_revision": window["source_revision"],
            "binding_revision": window["binding_revision"], "snapshot": "snapshot_alpha",
            "byte_start": window["byte_start"], "byte_end": window["byte_end"], "window_digest": window["window_digest"],
            "policy_revision": window["policy_revision"], "policy_epoch": window["policy_epoch"],
            "label": "remember", "coverage": "complete_window", "rejection_comparisons": [],
            "extraction": {"claims": [{"assertion_id": "a0001", "assertion_span_id": span["span_id"],
                "statement": window["body"], "kind": "fact", "subject": "CacheKey", "predicate": "remains",
                "object": "bounded", "polarity": "positive", "modality": "asserted", "entities": ["CacheKey"]}],
                "individual_qualifications": [], "shared_qualifications": [], "validities": [],
                "unused_span_ids": [item["span_id"] for item in window["span_inventory"][1:]]}})
        selection = await self.cli("inspect", "--binding", self.binding, "--ref", selected["artifact_id"],
                                   "--snapshot", "snapshot_alpha", "--complete")
        self.check(selected["state"] == "candidate_ready" and len(selection["claim_ids"]) == 1,
                   "SCOPED_FEEDBACK_CLAIM_NOT_GROUNDED")
        body = private_file(self.root / "feedback-candidate.txt", b"Synthetic correction requires independent review.")
        for scope, target in (("global", self.claim), ("scoped", selection["claim_ids"][0])):
            feedback = await self.cli("feedback", "--binding", self.binding, "--kind", "correct",
                "--ref", target, "--body-file", body, "--key", "consumer-feedback-" + scope, role="agent")
            candidate = await self.cli("inspect", "--binding", self.binding,
                "--ref", "health:feedback:" + feedback["artifact_id"], "--snapshot", "snapshot_alpha")
            reason = "Engineering operator declines an unsupported correction; human presence remains unattested."
            resolved = await self.apply(self.mutation("feedback_resolution", "consumer-resolution-" + scope,
                admission_id=candidate["admission"]["id"], feedback_ref=feedback["artifact_id"],
                expected_feedback_version=candidate["candidate"]["version"], decision="decline", reason=reason))
            event = await self.cli("inspect", "--binding", self.binding,
                "--ref", "health:event:" + resolved["artifact_id"], "--snapshot", "snapshot_beta")
            self.check(event["payload"]["decision"] == "decline" and reason not in json.dumps(event),
                       "BODY_FREE_FEEDBACK_HISTORY_NOT_PRESERVED")
            reason_ref = event["reason_source_ref"]
            allowed = await self.cli("inspect", "--binding", self.binding, "--ref", reason_ref,
                                     "--snapshot", "snapshot_alpha")
            self.check(allowed["body"] == reason, "AUTHORIZED_FEEDBACK_REASON_UNAVAILABLE")
            if scope == "scoped":
                await self.cli("inspect", "--binding", self.binding, "--ref", reason_ref,
                    "--snapshot", "snapshot_beta", denied=("INPUT_INELIGIBLE", "SOURCE_INELIGIBLE", "SNAPSHOT_INELIGIBLE"))
            else:
                global_reason = await self.cli("inspect", "--binding", self.binding, "--ref", reason_ref,
                                                "--snapshot", "snapshot_beta")
                self.check(global_reason["body"] == reason, "GLOBAL_FEEDBACK_REASON_OVERRESTRICTED")
        self.passed("feedback_resolution_reason_disclosure")

    async def cleanup(self):
        cleanup = self.result["owned_cleanup"]
        if self.host_install_attempted:
            try:
                removed = await self.cli("host-uninstall", "--project", self.project, "--host", "claude")
                self.check(removed.get("state") == "uninstalled", "ADAPTER_CLEANUP_UNCONFIRMED")
                cleanup["project_adapter"] = "removed"
            except BaseException:
                self.evidence("adapter-cleanup-failure", {"trace": traceback.format_exc()})
                cleanup["project_adapter"] = "unconfirmed"
        else:
            cleanup["project_adapter"] = "not_created"
        if self.server is not None:
            try:
                if self.server.returncode is None:
                    self.server.send_signal(signal.SIGTERM)
                    try:
                        await asyncio.wait_for(self.server.wait(), 15)
                    except TimeoutError:
                        self.server.kill()
                        await asyncio.wait_for(self.server.wait(), 5)
                        cleanup["service_forced"] = True
                cleanup["child_service"] = "stopped" if self.server.returncode is not None else "unconfirmed"
                cleanup["service_exit_code"] = self.server.returncode
                cleanup["service_exit_clean"] = self.server.returncode == 0 and not cleanup.get("service_forced", False)
            except BaseException:
                self.evidence("service-cleanup-failure", {"trace": traceback.format_exc()})
                cleanup["child_service"] = "unconfirmed"
        else:
            cleanup["child_service"] = "not_created"
        if self.store is not None:
            try:
                await asyncio.wait_for(self.store.close(), 10)
                cleanup["fixture_store"] = "closed"
            except BaseException:
                self.evidence("store-cleanup-failure", {"trace": traceback.format_exc()})
                cleanup["fixture_store"] = "unconfirmed"
        else:
            cleanup["fixture_store"] = "not_created"
        if self.admin is not None:
            try:
                if self.schema_created:
                    self.check(re.fullmatch(r"am_health_smoke_[0-9a-f]{32}", self.schema) is not None, "CLEANUP_SCHEMA_IDENTITY")
                    await asyncio.wait_for(self.admin.execute(f'DROP SCHEMA "{self.schema}" CASCADE'), 20)
                    exists = await self.admin.fetchval("SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname=$1)", self.schema)
                    cleanup["private_schema"] = "removed" if not exists else "unconfirmed"
                else:
                    cleanup["private_schema"] = "unconfirmed" if self.schema_attempted else "not_created"
            except BaseException:
                self.evidence("schema-cleanup-failure", {"trace": traceback.format_exc()})
                cleanup["private_schema"] = "unconfirmed"
            finally:
                try:
                    await asyncio.wait_for(self.admin.close(), 5)
                    cleanup["admin_connection"] = "closed"
                except BaseException:
                    cleanup["admin_connection"] = "unconfirmed"
        else:
            cleanup["private_schema"] = "not_created"
        cleanup["private_evidence"] = "retained"
        if self.before is not None:
            try:
                after = self.package_snapshot()
                self.result["source_unchanged"] = after == self.before
                self.result["consumed"]["module_tree_digest_after"] = digest(encoded(after))
            except BaseException:
                self.result["source_unchanged"] = None
                self.evidence("source-identity-failure", {"trace": traceback.format_exc()})

    async def run(self):
        loop = asyncio.get_running_loop()
        owner = asyncio.current_task()
        loop.add_signal_handler(signal.SIGTERM, owner.cancel)
        try:
            async with asyncio.timeout(300):
                await self.setup()
                await self.observer_and_workspace()
                await self.publish_claim()
                await self.proposals()
                await self.health_boundaries()
                await self.sessions()
                await self.feedback_reasons()
        except BaseException as error:
            self.result["outcomes"][self.active] = "failed"
            self.evidence("failure", {"case": self.active, "trace": traceback.format_exc()})
            self.result["failure"] = "HEALTH_SMOKE_FAILED"
            self.result["failure_code"] = error.code if isinstance(error, SmokeFailure) else "HEALTH_EXCEPTION"
            self.result["failure_stage"] = self.active if self.active in CASES else "UNKNOWN"
            self.result["failure_type"] = type(error).__name__ if type(error).__name__ in {
                "ValueError", "OSError", "TimeoutError", "RuntimeError", "DomainError",
                "TypeError", "KeyError", "AttributeError", "CancelledError", "SmokeFailure",
                "NameError", "ValidationError", "FileNotFoundError", "PermissionError",
                "ProcessLookupError", "JSONDecodeError", "NotImplementedError", "InvalidURL",
                "UniqueViolationError", "UndefinedTableError", "NotNullViolationError",
                "ForeignKeyViolationError", "InterfaceError", "DataError", "FileExistsError",
                "NotADirectoryError", "ArtifactError", "UnicodeDecodeError", "ImportError",
                "ModuleNotFoundError", "SSLError", "UnsupportedOperation", "UnboundLocalError"} else "BoundaryError"
            frame = error.__traceback__
            lines = []
            while frame is not None and len(lines) < 16:
                if frame.tb_frame.f_code.co_filename == __file__:
                    lines.append(frame.tb_lineno)
                frame = frame.tb_next
            self.result["failure_helper_lines"] = lines
        finally:
            await self.cleanup()
            loop.remove_signal_handler(signal.SIGTERM)
        cleanup = self.result["owned_cleanup"]
        self.result["complete"] = (all(value == "passed" for value in self.result["outcomes"].values())
            and self.result["source_unchanged"] is True
            and cleanup.get("service_exit_clean") is True
            and all(cleanup.get(key) in allowed for key, allowed in {
                "project_adapter": {"removed"}, "child_service": {"stopped"},
                "fixture_store": {"closed"}, "private_schema": {"removed"},
            }.items()) and cleanup.get("admin_connection") != "unconfirmed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result-dir", type=Path, default=Path(".ci-results"))
    args = parser.parse_args()
    # Refuse before creating state or importing any product dependency.
    if os.environ.get("GITHUB_ACTIONS") != "true" or sys.platform != "linux":
        print("HEALTH_SMOKE_ACTIONS_LINUX_REQUIRED", file=sys.stderr)
        return 2
    runner = os.environ.get("RUNNER_TEMP")
    sha = os.environ.get("CI_TESTED_SHA", "")
    if not runner or not Path(runner).is_absolute() or not re.fullmatch(r"[0-9a-f]{40}", sha):
        print("HEALTH_SMOKE_ACTIONS_IDENTITY_REQUIRED", file=sys.stderr)
        return 2
    os.umask(0o077)
    sys.dont_write_bytecode = True
    import resource

    soft, hard = resource.getrlimit(resource.RLIMIT_FSIZE)
    file_limit = 8 * 1024 * 1024
    if soft != resource.RLIM_INFINITY:
        file_limit = min(file_limit, soft)
    resource.setrlimit(resource.RLIMIT_FSIZE, (file_limit, hard))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    parent = Path(runner).resolve(strict=True)
    root = Path(tempfile.mkdtemp(prefix="agents-memory-health-smoke-", dir=parent))
    private_file(root / "owner-intent.json", encoded({
        "schema": 1, "surface": "health-api-cli", "tested_sha": sha,
        "run_id": os.environ.get("GITHUB_RUN_ID"), "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "job_id": os.environ.get("GITHUB_JOB"), "private_evidence_retained": True,
    }))
    result = {"schema": 1, "complete": False, "tested_sha": sha, "surface": "health-api-cli",
              "scope": "engineering_real_product_http_cli_not_native_acceptance", "original18_completed": 0,
              "consumed": None, "outcomes": dict.fromkeys(CASES, "not_run"),
              "owned_cleanup": {}, "source_unchanged": None}
    try:
        asyncio.run(Smoke(root, result).run())
    except BaseException:
        private_file(root / "harness-failure.json", encoded({"trace": traceback.format_exc()}))
        result["failure"] = "HEALTH_SMOKE_HARNESS_FAILED"
        result["complete"] = False
    # Public result contains only fixed labels, semantic outcomes and digests.
    # Never serialize exception messages, operation bodies or owned private paths.
    args.result_dir.mkdir(parents=True, exist_ok=True)
    destination = args.result_dir / "health-smoke.json"
    private_file(destination, encoded(result) + b"\n")
    print("HEALTH_SMOKE_COMPLETE" if result["complete"] else "HEALTH_SMOKE_FAILED")
    return 0 if result["complete"] else 1


if __name__ == "__main__":
    try:
        exit_code = main()
    except BaseException:
        print("HEALTH_SMOKE_RESULT_UNCONFIRMED", file=sys.stderr)
        exit_code = 1
    raise SystemExit(exit_code)
