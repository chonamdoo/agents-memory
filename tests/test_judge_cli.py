from __future__ import annotations

import io

import pytest
from test_cli_boundaries import cli_files
from test_store_authority import authority as authority

from agents_memory import cli
from agents_memory.domain import DomainError
from agents_memory.judge import judge_dir, load_state

KEY = "sk-jev-TEST-qwrtyuiopZXCVNMLKJH"


def non_terminal(monkeypatch):
    stdin = io.StringIO("2\n")
    assert not stdin.isatty()
    monkeypatch.setattr(cli.sys, "stdin", stdin)


def init_arguments(tmp_path, *extra, mode="personal"):
    for name in ("dsn", "migrator-dsn"):
        (tmp_path / f"{name}.txt").write_text("postgresql://not-used\n")
    return cli.parser().parse_args([
        "--config", str(tmp_path / "deployment.json"), "init", "--deployment-id", "deployment-001",
        "--realm", "personal", "--mode", mode, "--dsn-file", str(tmp_path / "dsn.txt"),
        "--migrator-dsn-file", str(tmp_path / "migrator-dsn.txt"), "--state-dir", str(tmp_path / "state"),
        "--journal-dir", str(tmp_path / "journal"), "--owner-id", "owner_test",
        "--operator-token-out", str(tmp_path / "operator.token"), *extra,
    ])


async def test_company_init_with_jev_is_refused_before_any_initialization_effect(tmp_path, monkeypatch):
    non_terminal(monkeypatch)
    key_file = tmp_path / "jev.key"
    key_file.write_text(KEY + "\n")
    key_file.chmod(0o600)

    def unexpected_verify(*args, **kwargs):
        pytest.fail("A company init verified a Jev key")

    monkeypatch.setattr(cli, "verify_key", unexpected_verify)
    args = init_arguments(tmp_path, "--judge", "jev", "--jev-key-file", str(key_file), mode="company")
    with pytest.raises(DomainError) as caught:
        await cli.execute(args)
    assert caught.value.code == "JUDGE_PROVIDER_FORBIDDEN"
    for effect in ("deployment.json", "state", "journal", "operator.token"):
        assert not (tmp_path / effect).exists()


async def test_non_terminal_init_defaults_to_agent_judgment(tmp_path, monkeypatch):
    non_terminal(monkeypatch)
    assert await cli.init_judge_plan(init_arguments(tmp_path)) == ("agent", None, [], None)


@pytest.mark.parametrize("judge", [["--judge", "agent"], []])
async def test_jev_key_file_without_jev_judgment_is_invalid(tmp_path, monkeypatch, judge):
    non_terminal(monkeypatch)
    args = init_arguments(tmp_path, *judge, "--jev-key-file", str(tmp_path / "unread.key"))
    with pytest.raises(DomainError) as caught:
        await cli.init_judge_plan(args)
    assert caught.value.code == "INPUT_INVALID"
    assert not (tmp_path / "state").exists()


async def test_judge_set_jev_without_any_key_source_requires_a_key_and_writes_nothing(authority, tmp_path, monkeypatch):
    settings = authority.store.settings
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    settings.state_dir.chmod(0o700)
    non_terminal(monkeypatch)

    def unexpected_verify(*args, **kwargs):
        pytest.fail("A missing key reached provider verification")

    monkeypatch.setattr("agents_memory.judge.verify_key", unexpected_verify)
    with pytest.raises(DomainError) as caught:
        await cli.execute(cli.parser().parse_args(cli_files(authority, tmp_path) + ["judge", "set", "jev"]))
    assert caught.value.code == "JUDGE_KEY_REQUIRED"
    directory = judge_dir(settings)
    assert not directory.exists() or list(directory.iterdir()) == []
    assert load_state(settings).provider == "agent"
