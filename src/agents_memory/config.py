from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator

from .domain import DomainError, Handle, TypedModel

MODEL_PURPOSES = ("extraction", "embedding", "consolidation", "rerank", "reflection")


class ModelConfig(TypedModel):
    generation_url: str | None = None
    generation_model: str = "memory-local"
    generation_key_file: Path | None = Field(default=None, repr=False)
    generation_artifact: Path | None = None
    embedding_path: Path | None = None
    reranker_path: Path | None = None
    manifest_path: Path | None = None
    embedding_dimensions: Literal[1024] = 1024
    timeout_seconds: int = Field(default=90, ge=5, le=300)
    interactive_wait_seconds: int = Field(default=3, ge=1, le=3)
    max_input_bytes: int = Field(default=32768, ge=4096, le=131072)
    max_output_tokens: int = Field(default=2048, ge=256, le=8192)
    cpu_threads: int = Field(default=8, ge=1, le=32)

    @field_validator("generation_url")
    @classmethod
    def loopback_generation(cls, value: str | None) -> str | None:
        if value is None:
            return None
        url = urlsplit(value)
        if (
            url.scheme not in {"http", "https"}
            or url.hostname not in {"127.0.0.1", "::1"}
            or url.username is not None
            or url.password is not None
            or url.query
            or url.fragment
        ):
            raise ValueError("generation_url must be a credential-free loopback URL")
        return value.rstrip("/")

    def manifest(self) -> dict:
        from .private_io import private_read
        from .wire import decode_json

        if self.manifest_path is None or not self.manifest_path.is_file():
            raise DomainError("MODEL_ROUTE_BLOCKED", "A verified local model manifest is required")
        try:
            value = decode_json(private_read(self.manifest_path, 262144, private=False))
        except (OSError, ValueError, DomainError):
            raise DomainError("MODEL_ROUTE_BLOCKED", "The local model manifest is invalid") from None
        if not isinstance(value, dict):
            raise DomainError("MODEL_ROUTE_BLOCKED", "The local model manifest is invalid")
        return value

    def revision(self) -> str:
        from .semantic_contract import route_revision

        return route_revision(self.manifest())

    def vector_revision(self) -> str:
        from .semantic_contract import embedding_revision

        return embedding_revision(self.manifest())


class Settings(TypedModel):
    deployment_id: Handle
    realm: Handle
    mode: Literal["personal", "company"]
    database_dsn: str = Field(repr=False)
    migrator_dsn: str | None = Field(default=None, repr=False)
    state_dir: Path
    journal_dir: Path
    port: int = Field(default=8768, ge=1024, le=65535)
    models: ModelConfig = ModelConfig()
    allowed_model_purposes: tuple[str, ...] = ()
    queue_limit: int = Field(default=1024, ge=1, le=100000)
    lease_seconds: int = Field(default=120, ge=20, le=600)
    heartbeat_seconds: int = Field(default=10, ge=1, le=60)
    job_attempt_limit: int = Field(default=4, ge=1, le=20)
    max_capture_bytes: int = Field(default=131072, ge=1024, le=1048576)
    max_http_body_bytes: int = Field(default=65536, ge=16384, le=262144)
    max_mcp_response_bytes: int = Field(default=16384, ge=4096, le=65536)
    spool_limit_bytes: int = Field(default=16777216, ge=65536, le=1073741824)
    strong_shared_approval: bool = False
    approver_public_key: Path | None = None

    @field_validator("allowed_model_purposes")
    @classmethod
    def valid_purposes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value) or any(p not in MODEL_PURPOSES for p in value):
            raise ValueError("allowed_model_purposes contains an invalid or duplicate purpose")
        return value

    @model_validator(mode="after")
    def bounded_policy(self) -> Settings:
        if self.heartbeat_seconds * 3 >= self.lease_seconds:
            raise ValueError("lease_seconds must exceed three heartbeat intervals")
        state = self.state_dir.resolve()
        journal = self.journal_dir.resolve()
        if state.is_relative_to(journal) or journal.is_relative_to(state):
            raise ValueError("journal_dir must be disjoint from the restore unit")
        if self.strong_shared_approval and self.approver_public_key is None:
            raise ValueError("strong shared approval requires an independently managed key")
        return self

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


def load_settings(path: Path) -> Settings:
    from .private_io import private_read

    try:
        return Settings.model_validate_json(private_read(path, 262144))
    except (OSError, ValueError):
        raise DomainError("CONFIG_INVALID", "The private deployment configuration is invalid") from None


def resolve_binding(actor, requested: str | None) -> str:
    if requested is not None:
        if requested not in actor.bindings:
            raise DomainError("SCOPE_DENIED", "The credential does not grant this project", status=403)
        return requested
    if len(actor.bindings) != 1:
        raise DomainError("BINDING_REQUIRED", "Choose one explicitly granted project")
    return actor.bindings[0]
