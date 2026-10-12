from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .domain import DomainError
from .models import _LLAMA_REVISION, _ORIGINAL_BLOBS, _ORIGINAL_SHA256, _PINS
from .private_io import private_write


def fetch_checkpoints(root: Path, *, allow_network: bool, mode: str = "personal") -> dict[str, str]:
    if not allow_network or mode != "personal":
        raise DomainError(
            "MODEL_DOWNLOAD_DENIED", "Public downloads require explicit personal operator permission"
        )
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["DO_NOT_TRACK"] = "1"
    os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
    os.environ["HF_HOME"] = str(root / ".hub-cache")
    from huggingface_hub import snapshot_download

    root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def fetch(purpose: str) -> tuple[str, str]:
        repo, revision, _ = _PINS[purpose]
        directory = root / f"{repo.split('/')[-1]}-{revision[:8]}"
        patterns = (
            ["*.json", "*.safetensors", "*.jinja", "LICENSE", "README.md"]
            if purpose == "generation"
            else sorted(set(_ORIGINAL_BLOBS[purpose]) | set(_ORIGINAL_SHA256[purpose]))
        )
        try:
            snapshot_download(
                repo_id=repo,
                revision=revision,
                local_dir=directory,
                allow_patterns=patterns,
                token=False,
                max_workers=4,
            )
        except Exception:
            raise DomainError("MODEL_DOWNLOAD_FAILED", "The explicit pinned artifact download failed") from None
        return purpose, str(directory)

    with ThreadPoolExecutor(max_workers=3) as pool:
        return dict(pool.map(fetch, _PINS))


def file_evidence(path: Path) -> dict:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(block)
            digest.update(block)
    return {"path": str(path.resolve()), "sha256": digest.hexdigest(), "bytes": size}


def write_model_manifest(
    destination: Path,
    generation_source: Path,
    generation_gguf: Path,
    embedding: Path,
    reranker: Path,
    *,
    quantization: str = "Q4_K_M",
    converter: Path,
) -> dict:
    generation_artifacts = [file_evidence(generation_gguf), file_evidence(converter)]
    for name in ("LICENSE", "README.md", "config.json", "chat_template.jinja"):
        path = generation_source / name
        if path.is_file():
            generation_artifacts.append(file_evidence(path))
    source_weights = [file_evidence(path) for path in sorted(generation_source.glob("*.safetensors"))]
    if not source_weights:
        raise DomainError("MODEL_MANIFEST_INVALID", "Original pinned generation weights are required")
    descriptors = {}
    for purpose, directory in (("embedding", embedding), ("reranker", reranker)):
        repo, revision, license_name = _PINS[purpose]
        paths = sorted(
            path for path in directory.rglob("*")
            if path.is_file() and ".cache" not in path.relative_to(directory).parts
        )
        descriptors[purpose] = {
            "repo": repo,
            "revision": revision,
            "license": license_name,
            "runtime": "sentence-transformers",
            "runtime_version": importlib.metadata.version("sentence-transformers"),
            "torch_version": importlib.metadata.version("torch"),
            "artifacts": [file_evidence(path) for path in paths],
        }
    descriptors["embedding"].update(dimensions=1024, pooling="cls", normalized=True)
    repo, revision, license_name = _PINS["generation"]
    manifest = {
        "schema": 1,
        "generation": {
            "repo": repo,
            "revision": revision,
            "license": license_name,
            "executor": {"repo": "ggml-org/llama.cpp", "revision": _LLAMA_REVISION},
            "quantization": quantization,
            "conversion": {
                "source_repo": repo,
                "source_revision": revision,
                "converter_revision": _LLAMA_REVISION,
                "converter_sha256": file_evidence(converter)["sha256"],
                "source_weights": source_weights,
                "intermediate_dtype": "f16",
                "quantization": quantization,
            },
            "artifacts": generation_artifacts,
        },
        **descriptors,
    }
    private_write(destination, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest
