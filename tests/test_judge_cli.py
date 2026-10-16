from __future__ import annotations

import io

import pytest
from test_cli_boundaries import cli_files
from test_store_authority import authority as authority

from agents_memory import cli
from agents_memory.domain import DomainError
from agents_memory.judge import (
    has_key,
    judge_dir,
    load_egress_policy,
    load_state,
    set_egress_policy,
    set_jev,
)

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


@pytest.mark.parametrize("mode", ["personal", "company"])
async def test_denied_init_refuses_jev_before_key_verification_or_initialization(tmp_path, monkeypatch, mode):
    non_terminal(monkeypatch)
    key_file = tmp_path / "jev.key"
    key_file.write_text(KEY + "\n")
    key_file.chmod(0o600)

    def unexpected_verify(*args, **kwargs):
        pytest.fail("A denied deployment verified a Jev key")

    monkeypatch.setattr(cli, "verify_key", unexpected_verify)
    args = init_arguments(tmp_path, "--judge", "jev", "--jev-key-file", str(key_file), mode=mode)
    with pytest.raises(DomainError) as caught:
        await cli.execute(args)
    assert caught.value.code == "JUDGE_PROVIDER_FORBIDDEN"
    for effect in ("deployment.json", "state", "journal", "operator.token"):
        assert not (tmp_path / effect).exists()


@pytest.mark.parametrize("mode", ["personal", "company"])
async def test_init_egress_grant_requires_separate_ack_before_any_effect(tmp_path, monkeypatch, mode):
    non_terminal(monkeypatch)
    args = init_arguments(tmp_path, "--jev-policy", "allow", "--judge", "agent", mode=mode)
    with pytest.raises(DomainError) as caught:
        await cli.execute(args)
    assert caught.value.code == "JUDGE_EGRESS_ACK_REQUIRED"
    for effect in ("deployment.json", "state", "journal", "operator.token"):
        assert not (tmp_path / effect).exists()




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
    await set_egress_policy(settings, authority.store, authority.actor, jev_allowed=True)
    non_terminal(monkeypatch)

    def unexpected_verify(*args, **kwargs):
        pytest.fail("A missing key reached provider verification")

    monkeypatch.setattr("agents_memory.judge.verify_key", unexpected_verify)
    with pytest.raises(DomainError) as caught:
        await cli.execute(cli.parser().parse_args(cli_files(authority, tmp_path) + ["judge", "set", "jev"]))
    assert caught.value.code == "JUDGE_KEY_REQUIRED"
    assert load_egress_policy(settings).jev_allowed
    assert not has_key(settings)
    assert load_state(settings).provider == "agent"


async def test_cli_egress_grant_does_not_select_a_provider_or_create_a_key(authority, tmp_path):
    base = cli_files(authority, tmp_path) + ["judge", "policy", "allow-jev"]
    with pytest.raises(DomainError) as caught:
        await cli.execute(cli.parser().parse_args(base))
    assert caught.value.code == "JUDGE_EGRESS_ACK_REQUIRED"
    assert not load_egress_policy(authority.store.settings).jev_allowed
    await cli.execute(cli.parser().parse_args(base + ["--ack-egress"]))
    assert load_egress_policy(authority.store.settings).jev_allowed
    assert load_state(authority.store.settings).provider == "agent"
    assert not has_key(authority.store.settings)


async def test_project_add_reports_committed_binding_when_jev_grant_is_refused(authority, tmp_path):
    store, settings, actor = authority.store, authority.store.settings, authority.actor
    settings.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    settings.state_dir.chmod(0o700)
    await set_egress_policy(settings, store, actor, jev_allowed=True)
    await set_jev(settings, store, actor, KEY, verify=lambda *_: "jev-1.13.0")
    (judge_dir(settings) / "egress-policy.json").unlink()
    args = cli.parser().parse_args(cli_files(authority, tmp_path) + [
        "project", "add", "--label", "Committed despite grant refusal", "--key", "denied-worker-project",
    ])
    with pytest.raises(DomainError) as refused:
        await cli.execute(args)
    assert refused.value.code == "JUDGE_PROVIDER_FORBIDDEN" and refused.value.effect.value == "committed"
    committed = [binding for binding in await store.list_bindings(actor) if binding.label == args.label]
    assert len(committed) == 1
    await set_egress_policy(settings, store, actor, jev_allowed=False)
    replay = await cli.execute(args)
    assert replay["id"] == committed[0].id
