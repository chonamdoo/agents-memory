from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from agents_memory.config import Settings, load_settings, prepare_settings_upgrade
from agents_memory.domain import DomainError
from agents_memory.private_io import private_write


def configuration(tmp_path, mode):
    return Settings(deployment_id="upgrade-test", realm="realm-test", mode=mode,
                    database_dsn="postgresql://memory:retained@127.0.0.1/memory",
                    migrator_dsn="postgresql://operator:retained@127.0.0.1/memory",
                    state_dir=tmp_path / "authority", journal_dir=tmp_path / "journal")


@pytest.mark.parametrize("mode,capability", (("personal", "full_semantic"), ("company", "full_semantic"),
                                             ("company", "lexical_entity")))
def test_config_upgrade_is_explicit_and_preserves_authority_and_operational_settings(tmp_path, mode, capability):
    settings = configuration(tmp_path, mode)
    value = {**settings.model_dump(mode="json"), "capability": capability,
             "models": {"generation_url": "http://127.0.0.1:8000", "manifest_path": "/retained/historical.json"},
             "allowed_model_purposes": [], "lease_seconds": 120, "heartbeat_seconds": 10,
             "job_attempt_limit": 4}
    original = json.dumps(value).encode()
    path = tmp_path / "legacy.json"
    private_write(path, original)
    with pytest.raises(DomainError) as denied:
        load_settings(path)
    assert denied.value.code == "CONFIG_UPGRADE_REQUIRED"
    upgraded = prepare_settings_upgrade(original)
    assert upgraded == settings
    assert path.read_bytes() == original
    assert "models" not in upgraded.model_dump() and "lease_seconds" not in upgraded.model_dump()


@pytest.mark.parametrize("change", (
    {"unknown_authority": "discard-me"}, {"models": {"unknown_provider": "discard-me"}},
    {"capability": "unknown"}, {"lease_seconds": False}, {"allowed_model_purposes": ["unknown"]},
))
def test_config_upgrade_never_silently_discards_unknown_fields(tmp_path, change):
    value = {**configuration(tmp_path, "personal").model_dump(mode="json"),
             "capability": "full_semantic", **change}
    with pytest.raises(DomainError) as denied:
        prepare_settings_upgrade(json.dumps(value).encode())
    assert denied.value.code == "CONFIG_INVALID" and denied.value.effect == "not_started"


@pytest.mark.parametrize("field,value", (("cleanup_interval_seconds", 0), ("cleanup_interval_seconds", 86401),
                                         ("read_admission_timeout_seconds", 0), ("read_admission_timeout_seconds", 3601)))
def test_agent_judgment_operational_intervals_are_bounded(tmp_path, field, value):
    with pytest.raises(ValidationError):
        Settings.model_validate({**configuration(tmp_path, "personal").model_dump(), field: value})
