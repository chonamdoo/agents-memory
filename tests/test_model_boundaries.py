import asyncio
import copy
import json
import threading
from http.client import BadStatusLine, IncompleteRead

import pytest

from agents_memory.config import ModelConfig
from agents_memory.domain import (
    ClaimDraft,
    DomainError,
    Quote,
    ReflectionDraft,
)
from agents_memory.models import _LLAMA_REVISION, _PINS, LocalSemanticRuntime
from agents_memory.semantic_contract import GeneratedExtraction


@pytest.fixture
def model_config(tmp_path, monkeypatch):
    manifest = {"schema": 1}
    for purpose, (repo, revision, license_name) in _PINS.items():
        manifest[purpose] = {
            "repo": repo, "revision": revision, "license": license_name,
            "artifacts": [{"path": str(tmp_path / purpose), "sha256": "a" * 64, "bytes": 1}],
        }
        if purpose != "generation":
            manifest[purpose].update(
                runtime="sentence-transformers", runtime_version="5.7.0", torch_version="2.9.0+cpu",
            )
    manifest["embedding"].update(dimensions=1024, pooling="cls", normalized=True)
    manifest["generation"].update(
        executor={"repo": "ggml-org/llama.cpp", "revision": _LLAMA_REVISION},
        quantization="Q4_K_M", conversion={"source_revision": _PINS["generation"][1]},
    )
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    monkeypatch.setattr("agents_memory.models.importlib.metadata.version",
                        lambda package: "2.9.0+cpu" if package == "torch" else "5.7.0")
    return ModelConfig(
        manifest_path=path, generation_url="http://127.0.0.1:8000",
        generation_artifact=tmp_path / "generation", embedding_path=tmp_path / "embedding",
        reranker_path=tmp_path / "reranker", timeout_seconds=5,
    )


def runtime_without_artifact_io(config, monkeypatch):
    runtime = LocalSemanticRuntime(config)
    monkeypatch.setattr(runtime, "validate_artifacts", lambda: None)
    return runtime


def generated_response(runtime, monkeypatch, artifact):
    def response(path, payload=None):
        if path == "/props":
            return {"model_path": str(runtime.config.generation_artifact),
                    "build_info": "build-" + _LLAMA_REVISION}
        return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(artifact)}}]}

    monkeypatch.setattr(runtime, "_http_json", response)


@pytest.mark.parametrize("field", [
    "entities", "polarity", "modality", "assertion_id", "assertion_span_id",
])
def test_incomplete_generated_assertions_fail_closed(model_config, monkeypatch, field):
    runtime = runtime_without_artifact_io(model_config, monkeypatch)
    draft = ClaimDraft(
        statement="JSON is the format.", kind="fact", subject="format", predicate="is", object="JSON",
        polarity="positive", modality="asserted",
        evidence=(Quote(source_id="source_a", quote="JSON is the format."),),
    )
    fields = draft.model_dump(mode="json", exclude={
        "evidence", "conditions", "exceptions", "valid_from", "valid_until",
    })
    fields.update(assertion_id="a0000", assertion_span_id="s0000")
    fields.pop(field)
    generated_response(runtime, monkeypatch, {
        "claims": [fields], "individual_qualifications": [], "shared_qualifications": [],
        "validities": [], "unused_span_ids": [],
    })
    with pytest.raises(DomainError) as rejected:
        runtime._generate(GeneratedExtraction, "extract", "source data")
    assert rejected.value.code == "MODEL_OUTPUT_INVALID"


@pytest.mark.parametrize("field", [
    "claims", "individual_qualifications", "shared_qualifications", "validities", "unused_span_ids",
])
def test_incomplete_generated_inventory_is_not_silently_an_empty_extraction(model_config, monkeypatch, field):
    runtime = runtime_without_artifact_io(model_config, monkeypatch)
    artifact = {
        "claims": [], "individual_qualifications": [], "shared_qualifications": [],
        "validities": [], "unused_span_ids": [],
    }
    artifact.pop(field)
    generated_response(runtime, monkeypatch, artifact)
    with pytest.raises(DomainError) as rejected:
        runtime._generate(GeneratedExtraction, "extract", "source data")
    assert rejected.value.code == "MODEL_OUTPUT_INVALID"




def test_missing_reflection_limitations_are_rejected_before_default(model_config, monkeypatch):
    runtime = runtime_without_artifact_io(model_config, monkeypatch)
    generated_response(runtime, monkeypatch, {"sentences": [{"text": "JSON is the format.",
                                                           "claim_ids": ["claim_a"]}]})
    with pytest.raises(DomainError) as rejected:
        runtime._generate(ReflectionDraft, "reflect", "claim data")
    assert rejected.value.code == "MODEL_OUTPUT_INVALID"


@pytest.mark.parametrize("installed", ["2.9.0", "2.9.1+cpu", "2.10.0+cpu"])
def test_exact_torch_manifest_runtime_is_required(model_config, monkeypatch, installed):
    monkeypatch.setattr("agents_memory.models.importlib.metadata.version",
                        lambda package: installed if package == "torch" else "5.7.0")
    with pytest.raises(DomainError) as rejected:
        LocalSemanticRuntime(model_config)
    assert rejected.value.code == "MODEL_ROUTE_BLOCKED"




def test_changed_process_contract_invalidates_existing_runtime(model_config, monkeypatch):
    runtime = LocalSemanticRuntime(model_config)
    previous = runtime.revision
    monkeypatch.setattr("agents_memory.semantic_contract.process_contract_digest", lambda: "b" * 64)
    assert model_config.revision() != previous
    with pytest.raises(DomainError) as rejected:
        runtime.validate_artifacts()
    assert rejected.value.code == "MODEL_ROUTE_BLOCKED"


def test_changed_artifact_manifest_invalidates_existing_runtime(model_config):
    runtime = LocalSemanticRuntime(model_config)
    manifest = copy.deepcopy(model_config.manifest())
    manifest["generation"]["artifacts"][0]["sha256"] = "c" * 64
    model_config.manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(DomainError) as rejected:
        runtime.validate_artifacts()
    assert rejected.value.code == "MODEL_ROUTE_BLOCKED"


async def test_generation_does_not_occupy_interactive_slot_and_close_drains(model_config, monkeypatch):
    runtime = runtime_without_artifact_io(model_config, monkeypatch)
    started = threading.Event()
    release = threading.Event()

    def generation():
        started.set()
        release.wait()
        return "generated"

    pending = asyncio.create_task(runtime._run(generation, generation=True))
    closing = None
    try:
        await asyncio.wait_for(asyncio.to_thread(started.wait), 1)
        assert await runtime._run(lambda: "interactive") == "interactive"
        assert runtime.drain_state["local_drain_pending"] is True
        closing = asyncio.create_task(runtime.close())
        await asyncio.sleep(0)
        assert runtime.drain_state["accepting"] is False
        with pytest.raises(DomainError) as rejected:
            await runtime._run(lambda: "not started")
        assert rejected.value.code == "MODEL_RUNTIME_CLOSED"
    finally:
        release.set()
        assert await pending == "generated"
        if closing is not None:
            await closing
        else:
            await runtime.close()
    assert runtime.drain_state["local_drained"] is True






async def test_cancelled_generation_stays_in_drain_without_blocking_interactive_reads(
    model_config, monkeypatch,
):
    runtime = runtime_without_artifact_io(model_config, monkeypatch)
    started = threading.Event()
    release = threading.Event()

    def generation():
        started.set()
        release.wait()

    pending = asyncio.create_task(runtime._run(generation, generation=True))
    try:
        await asyncio.wait_for(asyncio.to_thread(started.wait), 1)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert runtime.drain_state["local_drain_pending"] is True
        assert await runtime._run(lambda: "still interactive") == "still interactive"
        assert runtime.drain_state["local_drain_pending"] is True
    finally:
        release.set()
        if not pending.done():
            await pending
        await runtime.close()
    assert runtime.drain_state["local_drained"] is True


def test_torch_runtime_drift_after_construction_is_blocked(model_config, monkeypatch):
    runtime = LocalSemanticRuntime(model_config)
    monkeypatch.setattr("agents_memory.models.importlib.metadata.version",
                        lambda package: "2.9.1+cpu" if package == "torch" else "5.7.0")
    with pytest.raises(DomainError, match="torch runtime must exactly match"):
        runtime.validate_artifacts()


@pytest.fixture
def isolated_semantic_sources(tmp_path, monkeypatch):
    from agents_memory import semantic_contract

    root = tmp_path / "semantic-implementation"
    root.mkdir()
    for name in semantic_contract._SOURCE_NAMES:
        (root / name).write_bytes((semantic_contract._SOURCE_ROOT / name).read_bytes())
    monkeypatch.setattr(semantic_contract, "_SOURCE_ROOT", root)
    monkeypatch.setattr(semantic_contract, "_PROCESS_SOURCES", semantic_contract._snapshot_sources())
    return root


def test_comment_only_semantic_touch_does_not_block_live_approval(model_config, isolated_semantic_sources):
    previous = model_config.revision()
    path = isolated_semantic_sources / "prompts.py"
    path.write_text(path.read_text() + "\n# A non-semantic operational comment.\n")
    assert model_config.revision() == previous


def test_live_changed_prompt_cannot_relabel_loaded_inference(model_config, isolated_semantic_sources):
    runtime = LocalSemanticRuntime(model_config)
    path = isolated_semantic_sources / "prompts.py"
    path.write_text(path.read_text() + '\nSYSTEM_INSTRUCTION += "Changed inference instruction."\n')
    with pytest.raises(DomainError) as caught:
        model_config.revision()
    assert caught.value.code == "MODEL_ROUTE_BLOCKED"
    with pytest.raises(DomainError) as caught:
        runtime.validate_artifacts()
    assert caught.value.code == "MODEL_ROUTE_BLOCKED"


@pytest.mark.parametrize("component", ["generation", "reranker"])
def test_nonembedding_model_upgrade_keeps_existing_vector_compatibility(model_config, component):
    previous_vector = model_config.vector_revision()
    previous_route = model_config.revision()
    manifest = model_config.manifest()
    manifest[component]["artifacts"][0]["sha256"] = "c" * 64
    model_config.manifest_path.write_text(json.dumps(manifest))
    assert model_config.vector_revision() == previous_vector
    assert model_config.revision() != previous_route


def test_same_embedding_relocated_between_local_and_cloud_keeps_compatibility(model_config):
    previous = model_config.vector_revision()
    manifest = model_config.manifest()
    manifest["embedding"]["artifacts"][0]["path"] = "/cloud/models/embedding"
    model_config.manifest_path.write_text(json.dumps(manifest))
    assert model_config.vector_revision() == previous
    manifest["embedding"]["artifacts"][0]["sha256"] = "c" * 64
    model_config.manifest_path.write_text(json.dumps(manifest))
    assert model_config.vector_revision() != previous


@pytest.mark.parametrize("message", [None, [], 1, True, "not a message"])
def test_malformed_generated_message_is_invalid_artifact_not_worker_crash(model_config, monkeypatch, message):
    runtime = LocalSemanticRuntime(model_config)

    def response(path, payload=None):
        if path == "/props":
            return {"model_path": str(runtime.config.generation_artifact),
                    "build_info": "build-" + _LLAMA_REVISION}
        return {"choices": [{"finish_reason": "stop", "message": message}]}

    monkeypatch.setattr(runtime, "_http_json", response)
    with pytest.raises(DomainError) as caught:
        runtime._generate(GeneratedExtraction, "extract", "synthetic evidence")
    assert caught.value.code == "MODEL_OUTPUT_INVALID"


@pytest.mark.parametrize("failure", [
    IncompleteRead(b"partial", 20),
    BadStatusLine("invalid status"),
])
async def test_generation_protocol_loss_preserves_unknown_executor_completion(model_config, monkeypatch, failure):
    runtime = LocalSemanticRuntime(model_config)

    class BrokenEndpoint:
        def open(self, *args, **kwargs):
            raise failure

    monkeypatch.setattr("agents_memory.models.urllib.request.build_opener", lambda *args: BrokenEndpoint())
    with pytest.raises(DomainError) as caught:
        runtime._http_json("/v1/chat/completions", {"messages": []})
    assert caught.value.code == "MODEL_OUTPUT_INVALID"
    assert runtime.drain_state["provider_completion_unknown"] is True
    with pytest.raises(DomainError) as caught:
        await runtime.close()
    assert caught.value.code == "MODEL_PROVIDER_COMPLETION_UNKNOWN"


@pytest.mark.parametrize("entity", ["", "현" * 257])
def test_generated_entity_boundaries_fail_before_artifact_admission(model_config, monkeypatch, entity):
    runtime = runtime_without_artifact_io(model_config, monkeypatch)
    draft = ClaimDraft(
        statement="JSON is the format.", kind="fact", subject="format", predicate="is", object="JSON",
        polarity="positive", modality="asserted",
        evidence=(Quote(source_id="source_a", quote="JSON is the format."),),
    )
    fields = draft.model_dump(mode="json", exclude={
        "evidence", "conditions", "exceptions", "valid_from", "valid_until",
    })
    fields.update(assertion_id="a0000", assertion_span_id="s0000", entities=[entity])
    generated_response(runtime, monkeypatch, {
        "claims": [fields], "individual_qualifications": [], "shared_qualifications": [],
        "validities": [], "unused_span_ids": [],
    })

    with pytest.raises(DomainError) as caught:
        runtime._generate(GeneratedExtraction, "extract", "JSON is the format.")

    assert caught.value.code == "MODEL_OUTPUT_INVALID"


@pytest.mark.parametrize("path,payload,unknown", [
    ("/props", None, False),
    ("/v1/chat/completions", {"messages": []}, True),
])
async def test_response_budget_abort_cannot_attest_generation_completion(model_config, monkeypatch, path, payload, unknown):
    runtime = LocalSemanticRuntime(model_config)

    class OverBudgetResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, maximum):
            return b" " * maximum

    class Endpoint:
        def open(self, *args, **kwargs):
            return OverBudgetResponse()

    monkeypatch.setattr("agents_memory.models.urllib.request.build_opener", lambda *args: Endpoint())

    with pytest.raises(DomainError) as caught:
        runtime._http_json(path, payload)

    assert caught.value.code == "MODEL_OUTPUT_INVALID"
    assert runtime.drain_state["provider_completion_unknown"] is unknown
    if unknown:
        with pytest.raises(DomainError) as caught:
            await runtime.close()
        assert caught.value.code == "MODEL_PROVIDER_COMPLETION_UNKNOWN"
