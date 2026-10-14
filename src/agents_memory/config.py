from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator

from .domain import DomainError, Handle, TypedModel


class Settings(TypedModel):
    deployment_id: Handle
    realm: Handle
    mode: Literal["personal", "company"]
    capability: Literal["agent_judged"] = "agent_judged"
    database_dsn: str = Field(repr=False)
    migrator_dsn: str | None = Field(default=None, repr=False)
    state_dir: Path
    journal_dir: Path
    port: int = Field(default=8768, ge=1024, le=65535)
    queue_limit: int = Field(default=1024, ge=1, le=100000)
    cleanup_interval_seconds: int = Field(default=3600, ge=1, le=86400)
    read_admission_timeout_seconds: int = Field(default=180, ge=1, le=3600)
    max_capture_bytes: int = Field(default=131072, ge=1024, le=1048576)
    max_http_body_bytes: int = Field(default=65536, ge=16384, le=262144)
    max_mcp_response_bytes: int = Field(default=16384, ge=4096, le=65536)
    spool_limit_bytes: int = Field(default=16777216, ge=65536, le=1073741824)
    strong_shared_approval: bool = False
    approver_public_key: Path | None = None

    @model_validator(mode="after")
    def bounded_policy(self) -> Settings:
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

    @property
    def max_inspection_json_bytes(self) -> int:
        from .wire import RESULT_ENVELOPE_BYTES

        # Direct authority reads use neutral JSON; the application supplies its physical renderer budget.
        return self.max_mcp_response_bytes - RESULT_ENVELOPE_BYTES


def load_settings(path: Path) -> Settings:
    from .private_io import private_read

    try:
        raw = private_read(path, 262144)
        from .wire import decode_json

        value = decode_json(raw)
        if isinstance(value, dict) and (
            value.get("capability") in {"full_semantic", "lexical_entity"}
            or any(name in value for name in ("models", "allowed_model_purposes",
                                             "lease_seconds", "heartbeat_seconds", "job_attempt_limit"))
        ):
            raise DomainError("CONFIG_UPGRADE_REQUIRED", "Run the stopped authority's explicit migrate --upgrade-config command")
        return Settings.model_validate(value)
    except (OSError, ValueError, TypeError):
        raise DomainError("CONFIG_INVALID", "The private deployment configuration is invalid") from None


class _RetiredModelSettings(TypedModel):
    generation_url: str | None = None
    generation_model: str = "memory-local"
    generation_key_file: Path | None = Field(default=None, repr=False)
    generation_artifact: Path | None = None
    embedding_path: Path | None = None
    reranker_path: Path | None = None
    manifest_path: Path | None = None
    embedding_dimensions: Literal[1024] = 1024
    timeout_seconds: int = Field(default=90, ge=5, le=300, strict=True)
    interactive_wait_seconds: int = Field(default=3, ge=1, le=3, strict=True)
    max_input_bytes: int = Field(default=32768, ge=4096, le=131072, strict=True)
    max_output_tokens: int = Field(default=2048, ge=256, le=8192, strict=True)
    cpu_threads: int = Field(default=8, ge=1, le=32, strict=True)

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


def prepare_settings_upgrade(raw: bytes) -> Settings:
    from .wire import decode_json

    try:
        value = decode_json(raw)
        retired = {"models", "allowed_model_purposes", "lease_seconds",
                   "heartbeat_seconds", "job_attempt_limit"}
        if not isinstance(value, dict) or set(value) - (set(Settings.model_fields) | retired):
            raise ValueError
        capability = value.get("capability", "full_semantic")
        if capability not in {"full_semantic", "lexical_entity", "agent_judged"}:
            raise ValueError
        if "models" in value:
            if not isinstance(value["models"], dict):
                raise ValueError
            _RetiredModelSettings.model_validate(value["models"])
        purposes = value.get("allowed_model_purposes", [])
        if (not isinstance(purposes, list) or any(not isinstance(item, str) for item in purposes)
                or len(set(purposes)) != len(purposes)
                or set(purposes) - {"extraction", "embedding", "consolidation", "rerank", "reflection"}):
            raise ValueError
        if capability == "lexical_entity" and (value.get("mode") != "company" or purposes):
            raise ValueError
        for name, lower, upper in (("lease_seconds", 20, 600), ("heartbeat_seconds", 1, 60),
                                    ("job_attempt_limit", 1, 20)):
            if name in value and (type(value[name]) is not int or not lower <= value[name] <= upper):
                raise ValueError
        if value.get("heartbeat_seconds", 10) * 3 >= value.get("lease_seconds", 120):
            raise ValueError
        return Settings.model_validate({
            **{name: item for name, item in value.items() if name not in retired},
            "capability": "agent_judged",
        })
    except (DomainError, ValueError, TypeError):
        raise DomainError("CONFIG_INVALID", "The private configuration has an unsupported or invalid upgrade shape") from None


def resolve_binding(actor, requested: str | None) -> str:
    if requested is not None:
        if requested not in actor.bindings:
            raise DomainError("SCOPE_DENIED", "The credential does not grant this project", status=403)
        return requested
    if len(actor.bindings) != 1:
        raise DomainError("BINDING_REQUIRED", "Choose one explicitly granted project")
    return actor.bindings[0]
