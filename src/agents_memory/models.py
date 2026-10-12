from __future__ import annotations

import asyncio
import hashlib
import http.client
import importlib.metadata
import json
import math
import os
import re
import socket
import threading
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import NoReturn, TypeVar

from pydantic import ValidationError

from .config import ModelConfig
from .domain import (
    Claim,
    Consolidation,
    DomainError,
    Extraction,
    RankedClaim,
    ReflectionDraft,
    Source,
    TypedModel,
)
from .prompts import (
    CONSOLIDATION_INSTRUCTION,
    EXTRACTION_INSTRUCTION,
    REFLECTION_INSTRUCTION,
    SYSTEM_INSTRUCTION,
)
from .semantic import (
    original_spans,
    resolve_extraction,
    validate_consolidation,
    validate_reflection,
)
from .semantic_contract import (
    GeneratedExtraction,
    explicit_generation_schema,
    require_generated_fields,
    route_revision,
)
from .wire import decode_json

T = TypeVar("T")
M = TypeVar("M", bound=TypedModel)
_LLAMA_REVISION = "5c8854fd88319125125dc4b836c98b1b215b0f23"
_PINS = {
    "generation": ("Qwen/Qwen3.5-9B", "c202236235762e1c871ad0ccb60c8ee5ba337b9a", "Apache-2.0"),
    "embedding": ("BAAI/bge-m3", "5617a9f61b028005a4858fdac845db406aefb181", "MIT"),
    "reranker": (
        "BAAI/bge-reranker-v2-m3", "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e", "Apache-2.0"
    ),
}
_ORIGINAL_BLOBS = {
    "embedding": {
        "config.json": "e6eda1c72da8f9dc30fdd9b69c73d35af3b7a7ad",
        "tokenizer_config.json": "dc69ac559dcba2694012009aaa108c614541789a",
        "special_tokens_map.json": "b1879d702821e753ffe4245048eee415d54a9385",
        "README.md": "e5a320176edd6ee1cfb256e68ee5ac0004de9447",
        "1_Pooling/config.json": "9bd85925f325e25246d94c4918dc02ab98f2a1b7",
    },
    "reranker": {
        "config.json": "9f62673cb00ec41dcec8947b9ed16f6f2eb23ba2",
        "tokenizer_config.json": "328a00a9a560aadcf2a3064f917517359eb3cc26",
        "special_tokens_map.json": "b1879d702821e753ffe4245048eee415d54a9385",
        "README.md": "553540879ec61aea21df00434c984c0f760a3fcc",
    },
}
_ORIGINAL_SHA256 = {
    "embedding": {
        "pytorch_model.bin": "b5e0ce3470abf5ef3831aa1bd5553b486803e83251590ab7ff35a117cf6aad38",
        "tokenizer.json": "21106b6d7dab2952c1d496fb21d5dc9db75c28ed361a05f5020bbba27810dd08",
        "sentencepiece.bpe.model": "cfc8146abe2a0488e9e2a0c56de7952f7c11ab059eca145a0a727afce0db2865",
    },
    "reranker": {
        "model.safetensors": "d9e3e081faff1eefb84019509b2f5558fd74c1a05a2c7db22f74174fcedb5286",
        "tokenizer.json": "69564b696052886ed0ac63fa393e928384e0f8caada38c1f4864a9bfbf379c15",
        "sentencepiece.bpe.model": "cfc8146abe2a0488e9e2a0c56de7952f7c11ab059eca145a0a727afce0db2865",
    },
}



class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise DomainError("MODEL_ROUTE_BLOCKED", "The local model endpoint attempted a redirect")


class LocalSemanticRuntime:
    def __init__(self, config: ModelConfig) -> None:
        self.config = config
        self._manifest = config.manifest()
        self.revision = route_revision(self._manifest)
        self._check_descriptors()
        self._embedding = None
        self._reranker = None
        self._verified = False
        self._stamps: dict[Path, tuple[int, int, int, int, int]] = {}
        self._validation_lock = threading.Lock()
        self._generation_slot = asyncio.Semaphore(1)
        self._interactive_slot = asyncio.Semaphore(1)
        self._inflight: set[asyncio.Task] = set()
        self._closed = False
        self._provider_unknown = False

    @property
    def drain_state(self) -> dict[str, object]:
        return {
            "accepting": not self._closed,
            "local_drain_pending": bool(self._inflight),
            "local_drained": not self._inflight,
            "provider_completion_unknown": self._provider_unknown,
        }

    def _blocked(self, message: str) -> NoReturn:
        raise DomainError("MODEL_ROUTE_BLOCKED", message)

    def _check_descriptors(self) -> None:
        if self._manifest.get("schema") != 1:
            self._blocked("The model manifest schema is unsupported")
        for purpose, (repo, revision, license_name) in _PINS.items():
            descriptor = self._manifest.get(purpose)
            if not isinstance(descriptor, dict) or (
                descriptor.get("repo"), descriptor.get("revision"), descriptor.get("license")
            ) != (repo, revision, license_name):
                self._blocked("The model manifest does not match approved source and license pins")
            if not isinstance(descriptor.get("artifacts"), list) or not descriptor["artifacts"]:
                self._blocked("The model manifest has no artifact evidence")
            for artifact in descriptor["artifacts"]:
                if (
                    not isinstance(artifact, dict)
                    or not isinstance(artifact.get("path"), str)
                    or not Path(artifact["path"]).is_absolute()
                    or not isinstance(artifact.get("sha256"), str)
                    or not re.fullmatch(r"[a-f0-9]{64}", artifact["sha256"])
                    or type(artifact.get("bytes")) is not int
                    or artifact["bytes"] <= 0
                ):
                    self._blocked("The model manifest has invalid artifact evidence")
            if purpose != "generation":
                if descriptor.get("runtime") != "sentence-transformers":
                    self._blocked("The checkpoint runtime must be sentence-transformers")
                try:
                    installed = importlib.metadata.version("sentence-transformers")
                except importlib.metadata.PackageNotFoundError:
                    self._blocked("Install the optional local-model dependencies offline")
                if (
                    descriptor.get("runtime_version") != installed
                    or tuple(int(part) for part in installed.split(".")[:2]) < (5, 7)
                    or not installed.startswith("5.")
                ):
                    self._blocked("The installed checkpoint runtime does not match supported 5.7+ APIs")
                try:
                    installed_torch = importlib.metadata.version("torch")
                    major, minor = (int(part) for part in installed_torch.split("+")[0].split(".")[:2])
                except (importlib.metadata.PackageNotFoundError, ValueError):
                    self._blocked("A supported local torch runtime is required")
                if descriptor.get("torch_version") != installed_torch or (major, minor) < (2, 7):
                    self._blocked("The installed torch runtime must exactly match its approved manifest")
        embedding = self._manifest["embedding"]
        if (
            self.config.embedding_dimensions != 1024
            or embedding.get("dimensions") != 1024
            or embedding.get("pooling") != "cls"
            or embedding.get("normalized") is not True
        ):
            self._blocked("BGE-M3 requires 1024-dimensional normalized CLS pooling")
        generation = self._manifest["generation"]
        executor = generation.get("executor", {})
        if not isinstance(executor, dict) or (
            executor.get("repo"), executor.get("revision")
        ) != ("ggml-org/llama.cpp", _LLAMA_REVISION):
            self._blocked("Generation requires the approved llama.cpp source pin")
        if not generation.get("quantization") or not isinstance(generation.get("conversion"), dict):
            self._blocked("Generation requires recorded quantization and conversion provenance")
        if not generation["conversion"]:
            self._blocked("Generation conversion provenance is empty")
        if not all((self.config.generation_url, self.config.generation_artifact,
                    self.config.embedding_path, self.config.reranker_path)):
            self._blocked("All local model routes must be explicitly configured")
        encoded = json.dumps(self._manifest).casefold()
        if re.search(r'"(?:api_key|api_token|access_token|token|secret|authorization|password)"\s*:', encoded):
            self._blocked("The public model manifest must not contain credentials")

    @staticmethod
    def _stamp(path: Path) -> tuple[int, int, int, int, int]:
        stat = path.stat()
        return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns

    def validate_artifacts(self) -> None:
        with self._validation_lock:
            try:
                if self.config.revision() != self.revision:
                    self._blocked("The model manifest changed; create a new approved runtime")
                self._check_descriptors()
                if self._verified:
                    if any(self._stamp(path) != stamp for path, stamp in self._stamps.items()):
                        self._blocked("A verified local model artifact changed")
                    self._verify_load_sets()
                    return
                stamps = {}
                for descriptor in self._manifest.values():
                    if not isinstance(descriptor, dict) or "artifacts" not in descriptor:
                        continue
                    for artifact in descriptor["artifacts"]:
                        path = Path(artifact["path"])
                        before = self._stamp(path)
                        digest = hashlib.sha256()
                        with path.open("rb") as stream:
                            for block in iter(lambda: stream.read(1024 * 1024), b""):
                                digest.update(block)
                        if before != self._stamp(path) or before[2] != artifact["bytes"]:
                            self._blocked("A model artifact has invalid size or changed during verification")
                        if digest.hexdigest() != artifact["sha256"]:
                            self._blocked("A local model artifact failed its SHA-256 verification")
                        stamps[path] = before
                self._verify_load_sets()
                for purpose, root in (("embedding", self.config.embedding_path),
                                      ("reranker", self.config.reranker_path)):
                    files = {Path(a["path"]): a for a in self._manifest[purpose]["artifacts"]}
                    for name, digest in _ORIGINAL_SHA256[purpose].items():
                        if files[root / name]["sha256"] != digest:
                            self._blocked("A checkpoint differs from its pinned original source")
                    for name, blob in _ORIGINAL_BLOBS[purpose].items():
                        body = (root / name).read_bytes()
                        actual = hashlib.sha1(
                            b"blob " + str(len(body)).encode() + b"\0" + body, usedforsecurity=False
                        ).hexdigest()
                        if actual != blob:
                            self._blocked("Checkpoint metadata differs from its pinned source")
                    model_config = json.loads((root / "config.json").read_bytes())
                    architecture = ("XLMRobertaModel" if purpose == "embedding"
                                    else "XLMRobertaForSequenceClassification")
                    if model_config.get("architectures") != [architecture]:
                        self._blocked("The checkpoint architecture does not match its route")
                with self.config.generation_artifact.open("rb") as stream:
                    if stream.read(4) != b"GGUF":
                        self._blocked("Generation requires a real converted GGUF artifact")
                self._stamps = stamps
                self._verified = True
            except (OSError, ValueError, KeyError, TypeError):
                self._blocked("Local model artifacts are incomplete or invalid")

    def _verify_load_sets(self) -> None:
        for purpose, root in (("embedding", self.config.embedding_path),
                              ("reranker", self.config.reranker_path)):
            files = {Path(a["path"]) for a in self._manifest[purpose]["artifacts"]}
            required = set(_ORIGINAL_BLOBS[purpose]) | set(_ORIGINAL_SHA256[purpose])
            if not root.is_dir() or any(root / name not in files for name in required):
                self._blocked("The original checkpoint, tokenizer and license evidence are required")
            for path in root.rglob("*"):
                if ".cache" in path.relative_to(root).parts:
                    continue
                if path.is_file() and path.suffix in {".json", ".bin", ".safetensors", ".model", ".pt"}:
                    if path not in files:
                        self._blocked("A checkpoint loadable file is not covered by the manifest")
                if path.name.startswith("adapter_"):
                    self._blocked("Checkpoint adapters are not approved for this route")
        generation_files = {Path(a["path"]) for a in self._manifest["generation"]["artifacts"]}
        if self.config.generation_artifact not in generation_files:
            self._blocked("The generation artifact is not covered by its manifest")

    async def _run(self, work: Callable[[], T], *, generation: bool = False) -> T:
        if self._closed:
            raise DomainError("MODEL_RUNTIME_CLOSED", "The local model runtime is closing")
        slot = self._generation_slot if generation else self._interactive_slot
        wait_seconds = self.config.timeout_seconds if generation else self.config.interactive_wait_seconds
        try:
            await asyncio.wait_for(slot.acquire(), wait_seconds)
        except TimeoutError:
            raise DomainError("MODEL_BUSY", "The local model computation slot is occupied") from None
        if self._closed:
            slot.release()
            raise DomainError("MODEL_RUNTIME_CLOSED", "The local model runtime is closing")

        def execute() -> T:
            self.validate_artifacts()
            try:
                return work()
            except DomainError:
                raise
            except (ImportError, OSError, ValueError, RuntimeError, TypeError, KeyError):
                raise DomainError("MODEL_EXECUTION_FAILED", "Local model computation failed") from None

        task = asyncio.create_task(asyncio.to_thread(execute))
        self._inflight.add(task)

        def completed(finished: asyncio.Task) -> None:
            self._inflight.discard(finished)
            slot.release()
            if not finished.cancelled():
                finished.exception()

        task.add_done_callback(completed)
        try:
            return await asyncio.wait_for(asyncio.shield(task), self.config.timeout_seconds)
        except TimeoutError:
            raise DomainError(
                "MODEL_TIMEOUT", "Model deadline elapsed; local computation may still be draining"
            ) from None

    def _bounded_payload(self, payload: object) -> str:
        if self._closed:
            raise DomainError("MODEL_RUNTIME_CLOSED", "The local model runtime is closing")
        text = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        if len(text.encode("utf-8")) > self.config.max_input_bytes:
            raise DomainError("MODEL_INPUT_TOO_LARGE", "The supplied model input exceeds its byte budget")
        return text

    def _http_json(self, path: str, payload: dict | None = None) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.config.generation_key_file is not None:
            from .private_io import private_read

            try:
                key = private_read(self.config.generation_key_file, 4096).decode("utf-8").strip()
            except (DomainError, OSError, ValueError):
                self._blocked("The private local generation credential is unavailable")
            if not key or len(key) > 4096 or any(character.isspace() for character in key):
                self._blocked("The local generation credential is invalid")
            headers["Authorization"] = "Bearer " + key
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        base = self.config.generation_url
        if base.endswith("/v1"):
            base = base[:-3]
        request = urllib.request.Request(
            base + path,
            data=None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
        )
        try:
            with opener.open(request, timeout=self.config.timeout_seconds) as response:
                body = response.read(262145)
            if len(body) > 262144:
                if payload is not None:
                    self._provider_unknown = True
                raise DomainError("MODEL_OUTPUT_INVALID", "The local model response exceeds its byte budget")
            return decode_json(body)
        except TimeoutError:
            if payload is not None:
                self._provider_unknown = True
            raise DomainError(
                "MODEL_TIMEOUT", "The endpoint timed out; inference termination is not implied"
            ) from None
        except urllib.error.URLError as error:
            if isinstance(error.reason, (socket.timeout, TimeoutError)):
                if payload is not None:
                    self._provider_unknown = True
                raise DomainError("MODEL_TIMEOUT", "The endpoint timed out") from None
            if payload is not None:
                self._provider_unknown = True
            raise DomainError("MODEL_EXECUTION_FAILED", "The local model endpoint is unavailable") from None
        except (ValueError, OSError, http.client.HTTPException):
            if payload is not None:
                self._provider_unknown = True
            raise DomainError("MODEL_OUTPUT_INVALID", "The local model response is invalid") from None

    def _generate(self, schema: type[M], instruction: str, data: str) -> M:
        props = self._http_json("/props")
        model_path = props.get("model_path")
        if not isinstance(model_path, str) or Path(model_path).resolve() != self.config.generation_artifact.resolve():
            self._blocked("The running generation server is not using the approved artifact")
        build_info = props.get("build_info", "")
        if not isinstance(build_info, str):
            self._blocked("The running generation server has invalid executor evidence")
        build_commit = re.search(r"-([a-f0-9]{7,40})(?:$|\b)", build_info)
        if (
            build_commit is None or not _LLAMA_REVISION.startswith(build_commit.group(1))
            or "dirty" in build_info
        ):
            self._blocked("The running generation server does not match the approved executor pin")
        output_schema = explicit_generation_schema(schema)
        response = self._http_json("/v1/chat/completions", {
            "model": self.config.generation_model,
            "messages": [{
                "role": "system",
                "content": SYSTEM_INSTRUCTION + instruction
                + "\nOutput JSON schema (not source evidence):\n"
                + json.dumps(output_schema, ensure_ascii=False, separators=(",", ":")),
            }, {"role": "user", "content": data}],
            "temperature": 0,
            "max_tokens": self.config.max_output_tokens,
            "stream": False,
            "cache_prompt": False,
            "chat_template_kwargs": {"enable_thinking": False},
            "reasoning_effort": "none",
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema.__name__, "strict": True, "schema": output_schema},
            },
        })
        try:
            choices = response["choices"]
            if (
                not isinstance(choices, list)
                or len(choices) != 1
                or not isinstance(choices[0], dict)
                or choices[0].get("finish_reason") != "stop"
            ):
                raise ValueError
            message = choices[0].get("message")
            if not isinstance(message, dict):
                raise ValueError
            if message.get("reasoning_content") or message.get("reasoning") or message.get("tool_calls"):
                raise ValueError
            content = message["content"]
            if not isinstance(content, str) or "<think>" in content or "</think>" in content:
                raise ValueError
            value = decode_json(content.encode("utf-8"))
            require_generated_fields(value, output_schema)
            return schema.model_validate_json(content, strict=True)
        except (KeyError, TypeError, ValueError, ValidationError):
            raise DomainError("MODEL_OUTPUT_INVALID", "The local model did not return a valid final artifact") from None

    async def extract(self, source: Source) -> Extraction:
        spans = original_spans(source)
        data = self._bounded_payload({
            "source": source.model_dump(mode="json", exclude={"body"}),
            "original_spans": [span.model_dump() for span in spans],
        })

        def work() -> Extraction:
            result = self._generate(GeneratedExtraction, EXTRACTION_INSTRUCTION, data)
            return resolve_extraction(result, source)

        return await self._run(work, generation=True)

    @staticmethod
    def _configure_offline_models() -> None:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"

    def _load_embedding(self) -> None:
        if self._embedding is not None:
            return
        self._configure_offline_models()
        import torch
        from sentence_transformers import SentenceTransformer
        from sentence_transformers.base.modules import Transformer
        from sentence_transformers.sentence_transformer.modules import Normalize, Pooling

        torch.set_num_threads(self.config.cpu_threads)
        offline = {"local_files_only": True, "trust_remote_code": False, "token": False}
        transformer = Transformer(
            str(self.config.embedding_path), max_seq_length=8192,
            model_kwargs={**offline, "use_safetensors": False, "weights_only": True},
            processor_kwargs=offline.copy(), config_kwargs=offline.copy(), backend="torch",
        )
        pooling = Pooling(1024, pooling_mode="cls")
        self._embedding = SentenceTransformer(
            modules=[transformer, pooling, Normalize()], device="cpu",
            local_files_only=True, trust_remote_code=False, token=False,
        )
        if self._embedding.get_sentence_embedding_dimension() != 1024:
            self._blocked("The loaded embedding model has an unexpected dimension")

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        inputs = list(texts)
        self._bounded_payload(inputs)
        if len(inputs) > 32 or any(not isinstance(text, str) or not text.strip() for text in inputs):
            raise DomainError("MODEL_INPUT_INVALID", "Embedding requires at most 32 nonempty texts")
        if not inputs:
            return []

        def work() -> list[list[float]]:
            self._load_embedding()
            lengths = self._embedding.tokenizer(
                inputs, truncation=False, return_length=True,
                return_attention_mask=False, return_token_type_ids=False,
            )["length"]
            if any(length > 8192 for length in lengths):
                raise DomainError("MODEL_INPUT_TOO_LARGE", "Embedding input would be truncated")
            output = self._embedding.encode(
                inputs, batch_size=2, show_progress_bar=False, convert_to_numpy=True,
                normalize_embeddings=False,
            ).tolist()
            if len(output) != len(inputs):
                raise DomainError("MODEL_OUTPUT_INVALID", "Embedding output cardinality is invalid")
            for vector in output:
                if len(vector) != 1024 or any(not math.isfinite(value) for value in vector):
                    raise DomainError("MODEL_OUTPUT_INVALID", "Embedding output is not finite 1024-dimensional data")
                if not math.isclose(sum(value * value for value in vector), 1.0, abs_tol=0.0001):
                    raise DomainError("MODEL_OUTPUT_INVALID", "Embedding output is not normalized")
            return output

        return await self._run(work)

    def _claims_payload(self, claims: Sequence[Claim]) -> list[dict]:
        if len(claims) > 32 or len({claim.id for claim in claims}) != len(claims):
            raise DomainError("MODEL_INPUT_INVALID", "The supplied claim manifest is invalid or too large")
        return [claim.model_dump(mode="json") for claim in claims]

    async def consolidate(self, claims: Sequence[Claim]) -> Consolidation:
        inputs = tuple(claims)
        data = self._bounded_payload({"claims": self._claims_payload(inputs)})
        if len(inputs) < 2:
            return Consolidation(relations=())

        def work() -> Consolidation:
            result = self._generate(Consolidation, CONSOLIDATION_INSTRUCTION, data)
            validate_consolidation(result, inputs)
            return result

        return await self._run(work, generation=True)

    async def rerank(self, query: str, claims: Sequence[Claim]) -> list[RankedClaim]:
        inputs = tuple(claims)
        self._bounded_payload({"query": query, "claims": self._claims_payload(inputs)})
        if not query.strip():
            raise DomainError("MODEL_INPUT_INVALID", "Reranking requires a nonempty query")
        if not inputs:
            return []

        def work() -> list[RankedClaim]:
            self._configure_offline_models()
            import torch
            from sentence_transformers import CrossEncoder

            torch.set_num_threads(self.config.cpu_threads)
            if self._reranker is None:
                self._reranker = CrossEncoder(
                    str(self.config.reranker_path), device="cpu", max_length=8192,
                    local_files_only=True, trust_remote_code=False, token=False,
                    activation_fn=torch.nn.Identity(), backend="torch",
                    model_kwargs={"use_safetensors": True},
                )
            pairs = [(query, json.dumps(claim.draft.model_dump(mode="json"), ensure_ascii=False))
                     for claim in inputs]
            lengths = self._reranker.tokenizer(
                [pair[0] for pair in pairs], text_pair=[pair[1] for pair in pairs],
                truncation=False, return_length=True,
                return_attention_mask=False, return_token_type_ids=False,
            )["length"]
            if any(length > 8192 for length in lengths):
                raise DomainError("MODEL_INPUT_TOO_LARGE", "Reranking input would lose claim qualifiers")
            scores = self._reranker.predict(
                pairs, batch_size=2, show_progress_bar=False, convert_to_numpy=True,
                activation_fn=torch.nn.Identity(),
            ).reshape(-1).tolist()
            if len(scores) != len(inputs) or any(not math.isfinite(score) for score in scores):
                raise DomainError("MODEL_OUTPUT_INVALID", "Reranking scores are invalid")
            ranked = [RankedClaim(claim_id=claim.id, score=float(score))
                      for claim, score in zip(inputs, scores, strict=True)]
            return sorted(ranked, key=lambda item: (-item.score, item.claim_id))

        return await self._run(work)

    async def reflect(self, query: str, claims: Sequence[Claim]) -> ReflectionDraft:
        inputs = tuple(claims)
        data = self._bounded_payload({"query": query, "claims": self._claims_payload(inputs)})
        if not inputs or not query.strip():
            raise DomainError("MODEL_INPUT_INVALID", "Reflection requires a query and evidence manifest")

        def work() -> ReflectionDraft:
            result = self._generate(ReflectionDraft, REFLECTION_INSTRUCTION, data)
            validate_reflection(result, inputs)
            return result

        return await self._run(work, generation=True)

    async def close(self) -> None:
        self._closed = True
        if self._inflight:
            pending = tuple(self._inflight)
            _, remaining = await asyncio.wait(pending, timeout=self.config.timeout_seconds)
            if remaining:
                raise DomainError("MODEL_DRAIN_PENDING", "Local model threads are still draining")
        self._embedding = None
        self._reranker = None
        if self._provider_unknown:
            raise DomainError(
                "MODEL_PROVIDER_COMPLETION_UNKNOWN",
                "Local tasks drained, but socket termination does not prove provider completion",
            )
