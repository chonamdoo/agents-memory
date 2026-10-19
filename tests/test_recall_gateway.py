from __future__ import annotations

import asyncio
import hashlib
import json
import threading
from dataclasses import replace

import pytest
from test_evaluation_gateway import (
    actual_upstream,
    call,
    payload,
    prepare_through_actual_wire,
    scope_for,
)
from test_evaluation_gateway import (
    authority as authority,
)

from agents_memory.domain import DomainError
from agents_memory.evaluation_gateway import EvaluationGateway


async def wire_call(gateway, name, arguments, identifier, *, deliver=True):
    request = {"jsonrpc": "2.0", "id": identifier, "method": "tools/call",
               "params": {"name": name, "arguments": arguments}}
    gateway._stdio_observe("gateway_stdio_received", json.dumps(request).encode() + b"\n")
    result = await asyncio.to_thread(gateway.call_tool, name, arguments, downstream_request_id=identifier)
    frame = json.dumps({"jsonrpc": "2.0", "id": identifier, "result": result}).encode() + b"\n"
    if deliver:
        gateway._stdio_observe("gateway_stdio_written", frame)
    return payload(result), frame


async def inspect_child(child, ref, *, deliver=True):
    collected = bytearray()
    start = 0
    while True:
        value, _ = await wire_call(child, "memory_inspect", {
            "ref": ref, "byte_start": start, "max_bytes": 4096,
        }, f"inspect-{ref}-{start}", deliver=deliver)
        window = value.get("draft_window")
        if window is None:
            return value
        collected.extend(window["body"].encode())
        start = window["next_byte"]
        if start is None:
            assert hashlib.sha256(collected).hexdigest() == window["digest"]
            return json.loads(collected)


async def prepared_pair(agent, producer):
    parent = EvaluationGateway(scope_for(agent), agent=agent, producer=producer, trace_sink=lambda _: None)
    child = EvaluationGateway(replace(scope_for(agent), invocation_id="engineering-child"),
                              agent=agent, producer=None, trace_sink=lambda _: None)
    await call(parent, "memory_required_context", parent.required_request)
    _, claims = await prepare_through_actual_wire(parent, inspect_claims=False)
    candidates, _ = await wire_call(parent, "memory_context", parent.required_request, "first")
    assert set(claims) == {item["claim_id"] for item in candidates["candidate_manifest"]}
    parent.observe_host_fork(
        child, host="claude", parent_generation="parent-generation", child_generation="child-generation",
        task_id="unchanged-task", admission_id=candidates["admission_id"],
        native_fork_ref="engineering-observed-fork", inherited_context_ref="engineering-inherited-history",
    )
    returned = {"admission_id": candidates["admission_id"], "status": "complete", "relevance": [
        {"claim_id": claim, "relevant": True, "reason": "The complete offline condition applies."}
        for claim in claims
    ]}
    return parent, child, candidates, returned, claims


def complete(parent, child, returned, **overrides):
    arguments = {"child_return": returned, "current_request": parent.required_request,
                 "current_task_id": "unchanged-task", "native_completion_ref": "engineering-native-completion",
                 "parent_validation_ref": "engineering-parent-validation", **overrides}
    return parent.observe_child_completion(child, **arguments)


async def test_linked_complete_child_only_credits_completed_parent_final_delivery(authority, tmp_path):
    async with actual_upstream(authority, tmp_path) as (agent, producer):
        parent, child, candidates, returned, claims = await prepared_pair(agent, producer)
        try:
            for item in candidates["candidate_manifest"]:
                await inspect_child(child, item["inspection_ref"])
            second = complete(parent, child, returned)
            assert not set(claims) & parent._inspected_claims
            assert set(claims) <= child._delivered_inspections
            assert parent.flow_observation()["final_read_observed"] is False
            _, frame = await wire_call(parent, "memory_context", second, "second", deliver=False)
            assert parent.flow_observation()["final_read_observed"] is False
            parent._stdio_observe("gateway_stdio_written", frame)
            observation = parent.flow_observation()
            assert observation["final_read_observed"] is True
            assert observation["final_reads"][0]["fork_link"]["child_invocation_id"] == child.scope.invocation_id
            assert observation["fork_links"][0]["parent_understanding"] is None
            assert not set(claims) & set(observation["parent_inspected_claims"])
            assert observation["parent_inspected_claims"] == tuple(sorted(parent._inspected_claims))
            assert set(claims) <= {claim for link in observation["fork_links"] for claim in link["child_inspected_claims"]}
            assert observation["pipeline_observed"] is True
            with pytest.raises(DomainError) as caught:
                await call(child, "memory_inspect", {"ref": claims[0]})
            assert caught.value.code == "FORK_CHILD_ALREADY_COMPLETED"
        finally:
            parent.close()
            child.close()


@pytest.mark.parametrize("failure", ["foreign", "incomplete", "undelivered", "stale", "partial", "cancelled"])
async def test_foreign_incomplete_or_undelivered_child_never_qualifies_parent(authority, tmp_path, failure):
    async with actual_upstream(authority, tmp_path) as (agent, producer):
        parent, child, candidates, returned, _ = await prepared_pair(agent, producer)
        foreign = EvaluationGateway(replace(scope_for(agent), invocation_id="foreign"),
                                    agent=agent, producer=None, trace_sink=lambda _: None)
        try:
            if failure != "incomplete":
                for item in candidates["candidate_manifest"]:
                    await inspect_child(child, item["inspection_ref"], deliver=failure != "undelivered")
            if failure in {"partial", "cancelled"}:
                returned["status"] = failure
            with pytest.raises((ValueError, DomainError)):
                complete(parent, foreign if failure == "foreign" else child, returned,
                         **({"current_task_id": "different-task"} if failure == "stale" else {}))
            observation = parent.flow_observation()
            assert observation["fork_links"] == ()
            assert observation["final_read_observed"] is False
            assert observation["pipeline_observed"] is False
        finally:
            parent.close()
            child.close()
            foreign.close()


async def test_inspected_but_uncompleted_child_never_links_parent_pipeline(authority, tmp_path):
    async with actual_upstream(authority, tmp_path) as (agent, producer):
        parent, child, candidates, _, claims = await prepared_pair(agent, producer)
        try:
            for item in candidates["candidate_manifest"]:
                await inspect_child(child, item["inspection_ref"])
            assert set(claims) <= child._inspected_claims
            observation = parent.flow_observation()
            assert observation["fork_links"] == ()
            assert not set(claims) & set(observation["parent_inspected_claims"])
            assert observation["pipeline_observed"] is False
        finally:
            parent.close()
            child.close()


async def test_exact_return_required_and_child_noninspect_calls_denied(authority, tmp_path):
    async with actual_upstream(authority, tmp_path) as (agent, producer):
        parent, child, candidates, returned, _ = await prepared_pair(agent, producer)
        try:
            with pytest.raises(DomainError) as caught:
                await call(child, "memory_context", child.required_request)
            assert caught.value.code == "FORK_CHILD_TOOL_DENIED"
            for item in candidates["candidate_manifest"]:
                await inspect_child(child, item["inspection_ref"])
            second = complete(parent, child, returned)
            second["relevance"][0]["reason"] = "A different unvalidated judgment."
            with pytest.raises(DomainError) as caught:
                await wire_call(parent, "memory_context", second, "changed-return")
            assert caught.value.code == "FORK_PARENT_VALIDATION_REQUIRED"
            assert parent.flow_observation()["final_read_observed"] is False
        finally:
            parent.close()
            child.close()


async def test_inline_flow_still_qualifies_without_child(authority, tmp_path):
    async with actual_upstream(authority, tmp_path) as (agent, producer):
        parent = EvaluationGateway(scope_for(agent), agent=agent, producer=producer, trace_sink=lambda _: None)
        try:
            await call(parent, "memory_required_context", parent.required_request)
            await prepare_through_actual_wire(parent)
            candidates = await call(parent, "memory_context", parent.required_request)
            for item in candidates["candidate_manifest"]:
                await call(parent, "memory_inspect", {"ref": item["inspection_ref"]})
            await call(parent, "memory_context", {
                **parent.required_request, "admission_id": candidates["admission_id"],
                "relevance": [{"claim_id": item["claim_id"], "relevant": True,
                               "reason": "Inline inspection includes the offline condition."}
                              for item in candidates["candidate_manifest"]],
            })
            observation = parent.flow_observation()
            assert observation["final_read_observed"] is True
            assert observation["fork_links"] == ()
        finally:
            parent.close()


async def test_fork_requires_delivered_first_admission(authority, tmp_path):
    async with actual_upstream(authority, tmp_path) as (agent, producer):
        parent = EvaluationGateway(scope_for(agent), agent=agent, producer=producer, trace_sink=lambda _: None)
        child = EvaluationGateway(replace(scope_for(agent), invocation_id="child"),
                                  agent=agent, producer=None, trace_sink=lambda _: None)
        try:
            await call(parent, "memory_required_context", parent.required_request)
            await prepare_through_actual_wire(parent, inspect_claims=False)
            candidates, _ = await wire_call(parent, "memory_context", parent.required_request, "first", deliver=False)
            with pytest.raises(ValueError, match="delivered"):
                parent.observe_host_fork(
                    child, host="claude", parent_generation="parent", child_generation="child",
                    task_id="task", admission_id=candidates["admission_id"], native_fork_ref="fork",
                    inherited_context_ref="history",
                )
        finally:
            parent.close()
            child.close()


async def test_failed_child_cannot_be_replaced_by_silent_inline_credit(authority, tmp_path):
    async with actual_upstream(authority, tmp_path) as (agent, producer):
        parent, child, candidates, returned, claims = await prepared_pair(agent, producer)
        try:
            for item in candidates["candidate_manifest"]:
                await call(parent, "memory_inspect", {"ref": item["inspection_ref"]})
            assert set(claims) <= parent._inspected_claims
            with pytest.raises(DomainError) as caught:
                await wire_call(parent, "memory_context", {
                    **parent.required_request, "admission_id": candidates["admission_id"],
                    "relevance": returned["relevance"],
                }, "unvalidated-fallback")
            assert caught.value.code == "FORK_PARENT_VALIDATION_REQUIRED"
            assert parent.flow_observation()["final_read_observed"] is False
            assert parent.flow_observation()["fork_links"] == ()
        finally:
            parent.close()
            child.close()


class _ContendedLock:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.contended = threading.Event()

    def __enter__(self) -> _ContendedLock:
        if not self._lock.acquire(blocking=False):
            self.contended.set()
            self._lock.acquire()
        return self

    def __exit__(self, *_) -> None:
        self._lock.release()


async def test_concurrent_inline_call_cannot_credit_an_admission_being_delegated(authority, tmp_path):
    async with actual_upstream(authority, tmp_path) as (agent, producer):
        parent = EvaluationGateway(scope_for(agent), agent=agent, producer=producer, trace_sink=lambda _: None)
        child = EvaluationGateway(replace(scope_for(agent), invocation_id="engineering-child"),
                                  agent=agent, producer=None, trace_sink=lambda _: None)
        try:
            await call(parent, "memory_required_context", parent.required_request)
            _, claims = await prepare_through_actual_wire(parent, inspect_claims=False)
            candidates, _ = await wire_call(parent, "memory_context", parent.required_request, "first")
            for item in candidates["candidate_manifest"]:
                await call(parent, "memory_inspect", {"ref": item["inspection_ref"]})
            assert set(claims) <= parent._inspected_claims
            lock = parent._lock = _ContendedLock()
            registering = threading.Event()

            def hold_registration(event: dict) -> None:
                if event["stage"] == "gateway_host_fork":
                    registering.set()
                    assert lock.contended.wait(10), "the racing call ran while the fork was registering"

            parent.trace_sink = hold_registration
            fork = asyncio.create_task(asyncio.to_thread(
                parent.observe_host_fork, child, host="claude", parent_generation="parent-generation",
                child_generation="child-generation", task_id="unchanged-task",
                admission_id=candidates["admission_id"], native_fork_ref="engineering-observed-fork",
                inherited_context_ref="engineering-inherited-history",
            ))
            assert await asyncio.to_thread(registering.wait, 10)
            inline = asyncio.create_task(call(parent, "memory_context", {
                **parent.required_request, "admission_id": candidates["admission_id"],
                "relevance": [{"claim_id": claim, "relevant": True, "reason": "Racing inline judgment."}
                              for claim in claims],
            }))
            await fork
            with pytest.raises(DomainError) as caught:
                await inline
            assert caught.value.code == "FORK_PARENT_VALIDATION_REQUIRED"
            observation = parent.flow_observation()
            assert observation["final_read_attempts"] == ()
            assert observation["final_read_observed"] is False
        finally:
            parent.close()
            child.close()
