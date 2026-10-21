from __future__ import annotations

import asyncio
from typing import Any

from .config import Settings, resolve_binding
from .context import ContextBody, compose
from .domain import (
    ContextCommand,
    DomainError,
    FeedbackCommand,
    Principal,
    canonical_digest,
)
from .health import HealthCommand
from .judge import describe, load_state
from .judge_worker import JudgeWorker, public_status
from .lexical import tokens
from .selection import RecordInput
from .store import Store
from .wire import tool_result_bytes


class Application:
    def __init__(self, settings: Settings, store: Store) -> None:
        self.settings = settings
        self.store = store
        self.accepting = True
        self.inflight = 0
        self.judge: JudgeWorker | None = None

    def require_accepting(self) -> None:
        if not self.accepting:
            raise DomainError("SERVICE_DRAINING", "The service is draining", status=503)

    async def record(self, actor: Principal, command: RecordInput) -> dict[str, Any]:
        self.require_accepting()
        operation = await self.store.record(actor, command)
        return operation.model_dump(mode="json")

    async def feedback(self, actor: Principal, command: FeedbackCommand) -> dict[str, Any]:
        self.require_accepting()
        operation = await self.store.feedback(actor, command)
        return operation.model_dump(mode="json")

    async def health(self, actor: Principal, command: HealthCommand) -> dict[str, Any]:
        self.require_accepting()
        operation = await self.store.health(actor, command)
        if self.judge is not None:
            self.judge.notify()
        return operation.model_dump(mode="json")

    async def health_observer(self, actor: Principal, binding_id: str) -> dict[str, Any]:
        self.require_accepting()
        return await self.store.health_observer(actor, binding_id)

    async def inspect(
        self, actor: Principal, ref: str, binding_id: str | None, snapshot: str | None = None,
        *, byte_start: int = 0, max_bytes: int = 4096, claim_ids: tuple[str, ...] | None = None,
        rejection_cursor: str | None = None,
    ) -> dict[str, Any]:
        binding = resolve_binding(actor, binding_id)
        if ref == "judge":
            if claim_ids is not None or rejection_cursor is not None or byte_start != 0 or max_bytes != 4096:
                raise DomainError("INPUT_INVALID", "The judge provider view takes no window arguments", status=400)
            await self.store.authorize(actor, binding)
            return self.judge_view()
        return await self.store.inspect(
            actor, binding, ref, snapshot=snapshot, byte_start=byte_start, max_bytes=max_bytes,
            claim_ids=claim_ids, rejection_cursor=rejection_cursor,
            representation_bytes=self.settings.max_mcp_response_bytes, measure_json=tool_result_bytes,
        )

    def judge_view(self) -> dict[str, Any]:
        """Read-only provider view for agents: no key, fingerprint, credential or project data."""
        return {"kind": "judge", **describe(self.settings, load_state(self.settings), operator=False),
                "worker": public_status(self.judge)}

    async def context(self, actor: Principal, command: ContextCommand, *, include_stats: bool = True) -> dict[str, Any]:
        self.require_accepting()
        binding = resolve_binding(actor, command.binding_id)
        command = command.model_copy(update={"binding_id": binding})
        if command.causal_operation is not None:
            operation = await self.store.operation(actor, binding, command.causal_operation)
            if operation.state != "candidate_ready":
                raise DomainError("CAUSAL_NOT_READY", "The requested operation is not candidate-ready")
        rules = await self.store.rules(actor, binding)
        request_digest = canonical_digest(command.model_dump(mode="json", include={
            "query", "query_expansions", "paths", "purpose", "host", "snapshot", "code_workspace_id",
        }))
        if command.relevance is None:
            terms = tokens(" ".join((command.query, *command.query_expansions)))
            rows, admission = await self.store.search_lexical(
                actor, binding, terms, command.snapshot, 20, request_digest=request_digest,
                code_workspace_id=command.code_workspace_id,
            )
            candidates = [claim for claim, _ in rows]
            composed = compose(command, [rule for rule in rules if rule.required] if candidates else rules, (), ())
            delivered = await self.store.delivery(
                actor, binding, (), tuple(sorted((rule.id, rule.revision, rule.digest) for rule in rules)),
                command.snapshot, nonmodel_admission=admission,
                selected_claim_ids=tuple(claim.id for claim in candidates), include_stats=include_stats,
            )
            previews = []
            for claim, arms in rows:
                raw = claim.draft.statement.encode("utf-8")
                preview = raw[:160].decode("utf-8", errors="ignore")
                previews.append({
                    "claim_id": claim.id, "inspection_ref": claim.id,
                    "preview": preview, "partial": len(raw) > 160,
                    "polarity": claim.draft.polarity, "modality": claim.draft.modality,
                    "arms": list(arms),
                    "evidence_role": "unjudged_candidate_not_execution_authority",
                })
            result = self._context_result(
                composed, delivered,
                status="judgment_required" if candidates else None,
            )
            result.update({
                "admission_id": admission.id,
                "candidate_manifest": previews,
                "judgment_required": bool(candidates),
                "candidate_details": "Inspect each claim before submitting relevance for the complete manifest",
            })
            if tool_result_bytes(result) > self.settings.max_mcp_response_bytes:
                result["candidate_manifest"] = [
                    {"claim_id": claim.id, "inspection_ref": claim.id, "partial": True}
                    for claim in candidates
                ]
            if tool_result_bytes(result) > self.settings.max_mcp_response_bytes:
                raise DomainError("REQUIRED_CONTEXT_OVERFLOW", "Required rules and the complete candidate manifest exceed the wire budget")
            return result
        admission, claims = await self.store.recall_admission(
            actor, binding, command.admission_id, request_digest, command.snapshot,
        )
        by_id = {claim.id: claim for claim in claims}
        judgments = command.relevance
        if len(judgments) != len(by_id) or {item.claim_id for item in judgments} != set(by_id):
            raise DomainError("RELEVANCE_MANIFEST_INVALID", "Judge exactly the complete admitted candidate manifest")
        candidates = [by_id[item.claim_id] for item in judgments if item.relevant]
        relationships = await self.store.relations(
            actor, binding, tuple(claim.id for claim in candidates), snapshot=command.snapshot,
            code_workspace_id=command.code_workspace_id, workspace_scoped=True,
        )
        composed = compose(command, rules, candidates, relationships)
        delivered = await self.store.delivery(
            actor, binding, (), tuple(sorted((rule.id, rule.revision, rule.digest) for rule in rules)),
            command.snapshot, relation_ids=composed.relation_ids,
            nonmodel_admission=admission, selected_claim_ids=composed.claim_ids, include_stats=include_stats,
        )
        result = self._context_result(composed, delivered)
        result["judgment_required"] = False
        result["selection"] = "coding_agent_relevance_not_exhaustive"
        return result

    def _context_result(
        self, composed: ContextBody, delivered: dict[str, Any], *, status: str | None = None,
    ) -> dict[str, Any]:
        stats = delivered.get("stats")
        if stats is None:
            # Coverage was not assessed, so the response cannot claim to be complete.
            return {
                "capability": self.settings.capability,
                "status": status or "partial",
                "partial": True,
                **self._context_body(composed, delivered),
            }
        coverage = stats.get("coverage", {})
        health = stats.get("health", {})
        health_partial = any(health.get(key, 0) for key in ("withheld", "unknown_assessments", "closed_unknown_work"))
        partial = bool(
            composed.omitted or composed.unknown_rule_refs
            or any(stats.get(key, 0) for key in ("pending", "blocked", "failed", "dlq", "stale_index_claims"))
            or any(coverage.get(key, 0) for key in (
                "unclassified_sources", "incomplete_sources", "previous_policy_claims",
            ))
            or health_partial
        )
        result = {
            "capability": self.settings.capability,
            "status": status or (
                "partial" if partial else "ready" if composed.claim_ids or composed.rule_versions else "empty"
            ),
            "partial": partial,
            **self._context_body(composed, delivered),
            "pipeline": {key: stats.get(key, 0) for key in (
                "pending", "blocked", "failed", "dlq", "stale_index_claims",
            )},
            "coverage": coverage,
        }
        if health.get("enabled") or health_partial or health.get("rejected"):
            result["health"] = health
        return result

    @staticmethod
    def _context_body(composed: ContextBody, delivered: dict[str, Any]) -> dict[str, Any]:
        return {
            "context": composed.text,
            "context_bytes": composed.byte_count,
            "omitted": composed.omitted,
            "refs": list(composed.claim_ids),
            "stamp": {"epoch": delivered["epoch"], "rules": [list(v) for v in composed.rule_versions]},
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
            include_stats=False,
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
        state["local_drained"] = self.inflight == 0
        return state

    async def wait_closed(self) -> None:
        self.accepting = False
        while self.inflight:
            await asyncio.sleep(0.05)
