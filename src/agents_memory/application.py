from __future__ import annotations

import asyncio
from typing import Any

from .config import Settings, resolve_binding
from .context import compose
from .domain import (
    ContextCommand,
    DomainError,
    FeedbackCommand,
    Principal,
    RecordCommand,
    SemanticRuntime,
)
from .lexical import tokens
from .store import Store


class Application:
    def __init__(self, settings: Settings, store: Store, runtime: SemanticRuntime | None) -> None:
        self.settings = settings
        self.store = store
        self.runtime = runtime
        self.accepting = True
        self.inflight = 0

    def model(self, purpose: str) -> SemanticRuntime:
        if self.runtime is None or purpose not in self.settings.allowed_model_purposes:
            raise DomainError("MODEL_ROUTE_BLOCKED", "An approved offline model route is required")
        return self.runtime

    def require_accepting(self) -> None:
        if not self.accepting:
            raise DomainError("SERVICE_DRAINING", "The service is draining", status=503)

    async def record(self, actor: Principal, command: RecordCommand) -> dict[str, Any]:
        self.require_accepting()
        operation = await self.store.record(actor, command)
        return operation.model_dump(mode="json")

    async def feedback(self, actor: Principal, command: FeedbackCommand) -> dict[str, Any]:
        self.require_accepting()
        operation = await self.store.feedback(actor, command)
        return operation.model_dump(mode="json")

    async def inspect(
        self, actor: Principal, ref: str, binding_id: str | None, snapshot: str | None = None
    ) -> dict[str, Any]:
        binding = resolve_binding(actor, binding_id)
        return await self.store.inspect(actor, binding, ref, snapshot=snapshot)

    async def context(self, actor: Principal, command: ContextCommand) -> dict[str, Any]:
        binding = resolve_binding(actor, command.binding_id)
        command = command.model_copy(update={"binding_id": binding})
        if command.mode == "reflect":
            receipt = await self.store.reflection_receipt(actor, command)
            if receipt is not None:
                return receipt.model_dump(mode="json")
        self.require_accepting()
        if command.causal_operation is not None:
            operation = await self.store.operation(actor, binding, command.causal_operation)
            if operation.state != "semantic_ready":
                raise DomainError("CAUSAL_NOT_READY", "The requested operation is not semantic-ready")
        rules = await self.store.rules(actor, binding)
        compose(command, rules, (), ())
        initial_stats = await self.store.stats(actor, binding, command.snapshot)
        admissions = []
        candidates = []
        ranking_arms: dict[str, tuple[str, ...]] = {}
        if initial_stats.get("active_claims", 0):
            runtime = self.model("embedding")
            embedding_admission = await self.store.admit_read(
                actor, binding, (), runtime.revision, "embedding", command.snapshot
            )
            admissions.append(embedding_admission)
            vector = (await runtime.embed((command.query,)))[0]
            await self.store.recheck(embedding_admission)
            rows = await self.store.search(
                actor, binding, vector, tokens(command.query), command.snapshot, 20
            )
            candidates = [claim for claim, _ in rows]
            ranking_arms = {claim.id: arms for claim, arms in rows}
            if candidates:
                reranker = self.model("rerank")
                admission = await self.store.admit_read(
                    actor,
                    binding,
                    tuple(claim.id for claim in candidates),
                    reranker.revision,
                    "rerank",
                    command.snapshot,
                )
                admitted = await self.store.admitted_claims(admission)
                scores = await reranker.rerank(command.query, admitted)
                await self.store.recheck(admission)
                by_id = {claim.id: claim for claim in admitted}
                if len(scores) != len(by_id) or {score.claim_id for score in scores} != set(by_id):
                    raise DomainError("MODEL_OUTPUT_INVALID", "Reranking must cover exactly its manifest")
                candidates = [
                    by_id[score.claim_id]
                    for score in sorted(scores, key=lambda score: (-score.score, score.claim_id))
                ]
                admissions.append(admission)
        rules = await self.store.rules(actor, binding)
        relationships = await self.store.relations(
            actor, binding, tuple(c.id for c in candidates), snapshot=command.snapshot
        )
        composed = compose(command, rules, candidates, relationships)
        rule_versions = tuple(sorted((rule.id, rule.revision, rule.digest) for rule in rules))
        delivered = await self.store.delivery(
            actor, binding, tuple(admissions), rule_versions, command.snapshot,
            relation_ids=composed.relation_ids,
        )
        if command.mode == "reflect":
            self.model("reflection")
            if not composed.claim_ids:
                raise DomainError("NO_ELIGIBLE_EVIDENCE", "Reflection requires currently eligible evidence")
            operation = await self.store.submit_reflection(actor, command, composed.claim_ids)
            return operation.model_dump(mode="json")
        stats = delivered["stats"]
        partial = bool(
            composed.omitted
            or composed.unknown_rule_refs
            or any(stats.get(key, 0) for key in ("pending", "blocked", "failed", "dlq", "stale_index_claims"))
            or (stats.get("active_claims", 0) and not composed.claim_ids)
        )
        status = "partial" if partial else "ready" if composed.claim_ids or composed.rule_versions else "empty"
        return {
            "status": status,
            "context": composed.text,
            "context_bytes": composed.byte_count,
            "omitted": composed.omitted,
            "selection": "top_k_not_exhaustive",
            "refs": list(composed.claim_ids),
            "retrieval_arms": {ref: list(ranking_arms.get(ref, ())) for ref in composed.claim_ids},
            "stamp": {"epoch": delivered["epoch"], "rules": [list(v) for v in composed.rule_versions]},
            "pipeline": {key: stats.get(key, 0) for key in ("pending", "blocked", "failed", "dlq", "stale_index_claims")},
            "unresolved_required_rule_count": composed.unknown_rule_count,
            "selector_authority": "caller_hints_not_execution_authority",
            "evidence_role": "memory_candidates_not_execution_authority",
        }

    async def required_context(self, actor: Principal, command: ContextCommand) -> dict[str, Any]:
        self.require_accepting()
        binding = resolve_binding(actor, command.binding_id)
        rules = await self.store.rules(actor, binding)
        composed = compose(
            command, [rule for rule in rules if rule.required], (), (), protected_action=True
        )
        delivered = await self.store.delivery(
            actor,
            binding,
            (),
            tuple(sorted((rule.id, rule.revision, rule.digest) for rule in rules)),
            command.snapshot,
        )
        return {
            "context": composed.text,
            "context_bytes": composed.byte_count,
            "stamp": {"epoch": delivered["epoch"], "rules": [list(v) for v in composed.rule_versions]},
            "required": bool(composed.rule_versions),
        }

    async def drain(self, timeout: float = 30) -> dict[str, Any]:
        self.accepting = False
        deadline = asyncio.get_running_loop().time() + timeout
        while self.inflight and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.05)
        state: dict[str, Any] = {"accepting": False, "active_requests": self.inflight}
        if self.runtime is not None:
            try:
                await self.runtime.close()
            except DomainError as error:
                state["model_close"] = error.code
            state["models"] = getattr(self.runtime, "drain_state", {"local_drained": "unobserved"})
        state["local_drained"] = self.inflight == 0 and not state.get("models", {}).get("local_drain_pending", False)
        return state
