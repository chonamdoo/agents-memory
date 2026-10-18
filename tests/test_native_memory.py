from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from agents_memory.native_memory import native_memory_status


@pytest.fixture
def layout(tmp_path):
    root = tmp_path.resolve()
    home, project = root / "home", root / "project"
    home.mkdir()
    project.mkdir()
    return home, project


def put(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def observe(layout, environment=None):
    home, project = layout
    return native_memory_status(project, home=home, environment={} if environment is None else environment)


@pytest.mark.parametrize(("shared", "local", "expected"), [
    (None, None, "configured_disabled"), (True, None, "configured_enabled"),
    (True, False, "configured_disabled"), (False, True, "configured_enabled"),
])
def test_claude_observed_file_precedence(layout, shared, local, expected):
    home, project = layout
    put(home / ".claude/settings.json", '{"autoMemoryEnabled":false}')
    for name, enabled in (("settings.json", shared), ("settings.local.json", local)):
        if enabled is not None:
            put(project / ".claude" / name, json.dumps({"autoMemoryEnabled": enabled}))
    assert observe(layout)["claude"]["configuration"] == expected


@pytest.mark.parametrize("invalid", ["{", '{"autoMemoryEnabled":"false"}',
    '{"autoMemoryEnabled":false,"autoMemoryEnabled":true}', '{"unrelated":NaN}',
    '{"unrelated":' + "[" * 30 + "0" + "]" * 30 + "}", "x" * 65537])
def test_uncertain_higher_claude_layer_cannot_silently_establish_disabled(layout, invalid):
    home, project = layout
    put(home / ".claude/settings.json", '{"autoMemoryEnabled":false}')
    put(project / ".claude/settings.local.json", invalid)
    assert observe(layout)["claude"]["configuration"] == "unknown"


def test_claude_diagnostic_process_force_enable_cannot_report_disabled(layout):
    home, _ = layout
    put(home / ".claude/settings.json", '{"autoMemoryEnabled":false}')
    result = observe(layout, {"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "0"})["claude"]
    assert result["configuration"] == "configured_enabled"
    assert result["source"] == "diagnostic_process_environment"


@pytest.mark.parametrize("layer", ["user", "project", "project_local"])
def test_claude_settings_environment_cannot_establish_disabled(layout, layer):
    home, project = layout
    put(home / ".claude/settings.json", '{"autoMemoryEnabled":false}')
    path = {
        "user": home / ".claude/settings.json",
        "project": project / ".claude/settings.json",
        "project_local": project / ".claude/settings.local.json",
    }[layer]
    put(path, '{"autoMemoryEnabled":false,"env":{"CLAUDE_CODE_DISABLE_AUTO_MEMORY":"0"}}')
    assert observe(layout)["claude"]["configuration"] == "unknown"


def test_claude_unknown_settings_environment_cannot_prove_process_disable(layout):
    home, project = layout
    put(home / ".claude/settings.json", '{"autoMemoryEnabled":false}')
    put(project / ".claude/settings.local.json", "{")
    result = observe(layout, {"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"})["claude"]
    assert result["configuration"] == "unknown"


def test_explicit_environment_disable_and_custom_native_homes(layout):
    home, _ = layout
    custom = home / "custom"
    put(custom / "settings.json", '{"autoMemoryEnabled":true}')
    put(home / ".codex/config.toml", "[features]\nmemories=false\n")
    codex = home / "codex-custom"
    put(codex / "config.toml", "[features]\nmemories=true\n[memories]\nuse_memories=true\ngenerate_memories=false\n")
    result = observe(layout, {"CLAUDE_CONFIG_DIR": str(custom), "CODEX_HOME": str(codex),
                              "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"})
    assert result["claude"]["configuration"] == "configured_disabled"
    assert result["claude"]["source"] == "diagnostic_process_environment"
    assert result["codex"]["configuration"] == "configured_enabled"
    assert result["codex"]["generation"] == "configured_disabled"


@pytest.mark.parametrize("override", ["[memories]\nuse_memories=true\n", 'profile="alternate"\n'])
def test_unresolved_codex_project_or_profile_cannot_mean_disabled(layout, override):
    home, project = layout
    put(home / ".codex/config.toml", "[features]\nmemories=false\n")
    put(project / ".codex/config.toml", override)
    assert observe(layout)["codex"]["configuration"] == "unknown"


@pytest.mark.parametrize("kind", ["symlink", "ancestor_symlink", "hardlink", "fifo", "unreadable"])
def test_unsafe_config_is_unknown_without_reading_target(layout, kind):
    home, project = layout
    target = put(home / "private-target", '{"autoMemoryEnabled":false,"secret":"synthetic-secret"}')
    local = project / ".claude/settings.local.json"
    local.parent.mkdir()
    if kind == "symlink":
        local.symlink_to(target)
    elif kind == "ancestor_symlink":
        local.parent.rmdir()
        other = home / "other-config"
        put(other / "settings.local.json", target.read_text())
        local.parent.symlink_to(other, target_is_directory=True)
    elif kind == "hardlink":
        os.link(target, local)
    elif kind == "fifo":
        os.mkfifo(local)
    else:
        local.write_text(target.read_text())
        local.chmod(0)
    result = observe(layout)
    assert result["claude"]["configuration"] == "unknown"
    assert "synthetic-secret" not in json.dumps(result)


def test_lingering_native_storage_and_settings_are_preserved_without_body_auth_reads(layout, monkeypatch):
    home, project = layout
    settings = put(home / ".claude/settings.json", '{"autoMemoryEnabled":false,"opaque":"synthetic-secret-setting"}')
    memory = put(home / ".claude/projects/native-project/memory/MEMORY.md", "synthetic-private-memory")
    auth = put(home / ".codex/auth.json", "synthetic-private-auth")
    codex = put(home / ".codex/config.toml", "[features]\nmemories=false\n")
    (home / ".codex/memories").mkdir()
    files = [settings, memory, auth, codex]
    before = [(path.read_bytes(), path.stat().st_mode) for path in files]
    original_open = os.open

    def guarded_open(path, *args, **kwargs):
        if Path(path).name in {"MEMORY.md", "auth.json"}:
            raise AssertionError("A metadata diagnostic must not open native memory or authentication")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", guarded_open)
    result = observe(layout)
    assert result["claude"]["storage"] == result["codex"]["storage"] == "present"
    assert result["claude"]["configuration"] == result["codex"]["configuration"] == "configured_disabled"
    assert "synthetic-private" not in json.dumps(result)
    assert "synthetic-secret" not in json.dumps(result)
    assert str(home) not in json.dumps(result)
    assert [(path.read_bytes(), path.stat().st_mode) for path in files] == before
