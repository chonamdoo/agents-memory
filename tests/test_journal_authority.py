import json
import os
import stat
from concurrent.futures import ThreadPoolExecutor

import pytest

from agents_memory.domain import DomainError
from agents_memory.journal import DeletionJournal


def test_missing_journal_never_creates_a_deletion_floor(tmp_path):
    journal = DeletionJournal(tmp_path / "independent", "deployment_test")
    for action in (journal.verify, journal.entries):
        with pytest.raises(DomainError, match="independent deletion journal"):
            action()
    assert not journal.directory.exists()


def test_concurrent_intents_preserve_the_chain_without_identifiers(tmp_path):
    journal = DeletionJournal(tmp_path / "independent", "deployment_test")
    genesis = journal.initialize()
    def append(index):
        return journal.append("private_project", (f"private_source_{index}",), (f"private_origin_{index}",))
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(append, range(32)))
    head = journal.verify()
    assert head["sequence"] == 32
    assert {result["sequence"] for result in results} == set(range(1, 33))
    assert journal.entries()[0]["previous"] == genesis["head"]
    encoded = (journal.directory / "entries").read_bytes()
    assert b"private_project" not in encoded
    assert b"private_source" not in encoded
    assert b"private_origin" not in encoded
    assert stat.S_IMODE(journal.directory.stat().st_mode) == 0o700
    assert all(stat.S_IMODE((journal.directory / name).stat().st_mode) == 0o600 for name in ("key", "metadata", "entries", "head", "lock"))


def test_fsynced_intent_with_lagging_head_is_not_lost(tmp_path):
    journal = DeletionJournal(tmp_path / "independent", "deployment_test")
    genesis = journal.initialize()
    current = journal.append("project", ("source",), ("origin",))
    (journal.directory / "head").write_text(json.dumps({"head": genesis["head"], "sequence": 0}))
    assert journal.verify(current["head"])["head"] == current["head"]
    assert len(journal.entries()) == 1
    with pytest.raises(DomainError):
        journal.verify(genesis["head"])


def test_tamper_and_cross_deployment_fail_closed(tmp_path):
    journal = DeletionJournal(tmp_path / "independent", "deployment_test")
    journal.initialize()
    journal.append("project", ("source",), ())
    with pytest.raises(DomainError):
        DeletionJournal(journal.directory, "other_deployment").verify()
    path = journal.directory / "entries"
    entry = json.loads(path.read_text())
    entry["source_tokens"][0] = "0" * 64
    path.write_text(json.dumps(entry) + "\n")
    with pytest.raises(DomainError):
        journal.verify()


def test_symlink_and_shared_key_permissions_are_rejected(tmp_path):
    journal = DeletionJournal(tmp_path / "independent", "deployment_test")
    journal.initialize()
    key = journal.directory / "key"
    os.chmod(key, 0o644)
    with pytest.raises(DomainError):
        journal.source_token("source")
    os.chmod(key, 0o600)
    moved = journal.directory / "original-key"
    key.rename(moved)
    key.symlink_to(moved)
    with pytest.raises(DomainError):
        journal.verify()


def test_unacknowledged_torn_tail_recovers_without_losing_completed_intents(tmp_path):
    journal = DeletionJournal(tmp_path / "independent", "deployment_test")
    journal.initialize()
    completed = journal.append("project", ("source",), ())
    entries = journal.directory / "entries"
    original = entries.read_bytes()
    with entries.open("ab") as stream:
        stream.write(b'{"sequence":2,"previous":"torn')
    assert journal.verify(completed["head"])["head"] == completed["head"]
    assert entries.read_bytes() == original
    next_head = journal.append("project", ("next-source",), ())
    assert next_head["sequence"] == 2
    assert journal.verify(next_head["head"])["head"] == next_head["head"]


def test_torn_completed_head_never_recovers_by_discarding_acknowledged_intent(tmp_path):
    journal = DeletionJournal(tmp_path / "independent", "deployment_test")
    journal.initialize()
    completed = journal.append("project", ("source",), ())
    entries = journal.directory / "entries"
    torn = entries.read_bytes()[:-1]
    entries.write_bytes(torn)
    with pytest.raises(DomainError) as barrier:
        journal.verify(completed["head"])
    assert barrier.value.code == "DELETION_BARRIER"
    assert entries.read_bytes() == torn


@pytest.mark.parametrize("payload", ([], None, {"head": "0" * 64, "sequence": []}, {"head": "0" * 64, "sequence": True}))
def test_malformed_head_types_fail_closed_as_domain_error(tmp_path, payload):
    journal = DeletionJournal(tmp_path / "independent", "deployment_test")
    journal.initialize()
    (journal.directory / "head").write_text(json.dumps(payload))
    with pytest.raises(DomainError) as barrier:
        journal.verify()
    assert barrier.value.code == "DELETION_BARRIER"


@pytest.mark.parametrize("payload", ([], None, {"schema": True}, {"schema": 1, "deployment_id": "deployment_test", "nonce": [], "mac": []}))
def test_malformed_metadata_types_fail_closed_as_domain_error(tmp_path, payload):
    journal = DeletionJournal(tmp_path / "independent", "deployment_test")
    journal.initialize()
    (journal.directory / "metadata").write_text(json.dumps(payload))
    with pytest.raises(DomainError) as barrier:
        journal.verify()
    assert barrier.value.code == "DELETION_BARRIER"


@pytest.mark.parametrize("value", ("not-an-array", {}, None, 7))
def test_malformed_entry_token_containers_fail_closed(tmp_path, value):
    journal = DeletionJournal(tmp_path / "independent", "deployment_test")
    journal.initialize()
    journal.append("project", ("source",), ())
    entries = journal.directory / "entries"
    entry = json.loads(entries.read_text())
    entry["source_tokens"] = value
    entries.write_text(json.dumps(entry) + "\n")
    with pytest.raises(DomainError) as barrier:
        journal.verify()
    assert barrier.value.code == "DELETION_BARRIER"


def test_directional_artifact_intent_preserves_legacy_chain_without_upstream_floor(tmp_path):
    journal = DeletionJournal(tmp_path / "independent", "deployment_test")
    journal.initialize()
    legacy = journal.append("project", ("independent-source",), ("independent-origin",))
    refs = (("claim", "private-claim-id"), ("extract_source", "upstream-source-id"))
    current = journal.append("project", (), (), refs)
    entries = journal.entries()
    assert entries[1]["previous"] == legacy["head"]
    assert entries[1]["source_tokens"] == [] and entries[1]["origin_tokens"] == []
    assert set(entries[1]["artifact_tokens"]) == set(journal.artifact_tokens(refs).values())
    assert journal.verify(current["head"])["sequence"] == 2
    encoded = (journal.directory / "entries").read_bytes()
    assert b"private-claim-id" not in encoded and b"upstream-source-id" not in encoded


def test_purge_intent_retains_legacy_bytes_and_durable_body_free_artifact_closure(tmp_path):
    journal = DeletionJournal(tmp_path / "independent", "deployment_test")
    journal.initialize()
    legacy = journal.append("private-binding", ("private-source",), ("private-origin",))
    before = (journal.directory / "entries").read_bytes()
    refs = (("selection", "private-selection"), ("claim", "private-claim"))
    purged = journal.append("private-binding", ("private-source",), ("private-origin",), refs, purge=True)
    assert (journal.directory / "entries").read_bytes().startswith(before)
    reopened = DeletionJournal(journal.directory, "deployment_test")
    entries = reopened.entries()
    assert "purge" not in entries[0] and entries[1]["purge"] is True
    assert entries[1]["previous"] == legacy["head"]
    assert set(entries[1]["artifact_tokens"]) == set(reopened.artifact_tokens(refs).values())
    assert reopened.verify(purged["head"])["sequence"] == 2
    assert b"private-" not in (journal.directory / "entries").read_bytes()
    with pytest.raises(DomainError) as stale_head:
        reopened.verify(legacy["head"])
    assert stale_head.value.code == "DELETION_BARRIER"


@pytest.mark.parametrize("value", (None, 1, "true", [], {}))
def test_nonboolean_purge_intent_is_rejected_before_chain_mutation(tmp_path, value):
    journal = DeletionJournal(tmp_path / "independent", "deployment_test")
    genesis = journal.initialize()
    with pytest.raises(DomainError) as invalid:
        journal.append("project", ("source",), (), purge=value)
    assert invalid.value.code == "PURGE_INTENT_INVALID"
    assert journal.verify() == genesis
