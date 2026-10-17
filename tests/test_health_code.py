from __future__ import annotations

import hashlib

import pytest

from agents_memory.domain import DomainError
from agents_memory.health_code import observe_file, pin_root


def pinned(tmp_path):
    root = (tmp_path / "workspace").resolve()
    root.mkdir()
    return root, pin_root(root, "a" * 64)


def test_dirty_bytes_change_without_git_or_head_and_never_return_code(tmp_path):
    root, pin = pinned(tmp_path)
    path = root / "module.py"
    before = b"def answer():\n    return 1\n"
    after = b"def answer():\n    return 2\n"
    path.write_bytes(before)
    first = observe_file(pin, "module.py", ("answer",))
    path.write_bytes(after)
    second = observe_file(pin, "module.py", ("answer",))
    assert first.file_digest == hashlib.sha256(before).hexdigest()
    assert second.file_digest == hashlib.sha256(after).hexdigest()
    assert first.file_digest != second.file_digest
    assert first.symbols[0].span_digest != second.symbols[0].span_digest
    assert "return 1" not in second.model_dump_json()
    assert "return 2" not in second.model_dump_json()


def test_utf8_decorated_class_method_and_nested_function_spans_are_exact(tmp_path):
    root, pin = pinned(tmp_path)
    raw = (
        "# 한글\n"
        "@decorate\n"
        "class Container:\n"
        "    @wrap\n"
        "    async def 작업(self):\n"
        "        def nested():\n"
        "            return '값'\n"
        "        return nested()\n"
    ).encode()
    (root / "module.py").write_bytes(raw)
    result = observe_file(pin, "module.py", ("Container", "Container.작업", "Container.작업.nested"))
    assert result.symbol_coverage == "complete"
    assert [symbol.kind for symbol in result.symbols] == ["class", "method", "function"]
    for symbol in result.symbols:
        assert hashlib.sha256(raw[symbol.byte_start:symbol.byte_end]).hexdigest() == symbol.span_digest
    assert raw[result.symbols[0].byte_start:].startswith(b"@decorate")
    assert raw[result.symbols[1].byte_start:].startswith(b"@wrap")


def test_two_worktrees_same_bytes_have_independent_root_identity(tmp_path):
    first = (tmp_path / "first").resolve()
    second = (tmp_path / "second").resolve()
    first.mkdir()
    second.mkdir()
    for root in (first, second):
        (root / "module.py").write_bytes(b"def answer(): return 1\n")
    one = pin_root(first, "a" * 64)
    two = pin_root(second, "a" * 64)
    assert one.fingerprint != two.fingerprint
    assert observe_file(one, "module.py").file_digest == observe_file(two, "module.py").file_digest


def test_root_replacement_cannot_observe_a_new_worktree_as_the_old_one(tmp_path):
    root, pin = pinned(tmp_path)
    (root / "module.py").write_bytes(b"old = True\n")
    root.rename(tmp_path / "old-root")
    root.mkdir()
    (root / "module.py").write_bytes(b"new = True\n")
    result = observe_file(pin, "module.py")
    assert result.status == "unstable"
    assert result.file_digest is None and result.symbols == []


@pytest.mark.parametrize("where", ["file", "ancestor", "root"])
def test_symlinks_never_supply_content_witness(tmp_path, where):
    root, pin = pinned(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "module.py").write_bytes(b"private_code_body = True\n")
    if where == "file":
        (root / "module.py").symlink_to(outside / "module.py")
        relative = "module.py"
    elif where == "ancestor":
        (root / "linked").symlink_to(outside, target_is_directory=True)
        relative = "linked/module.py"
    else:
        root.rename(tmp_path / "previous")
        root.symlink_to(outside, target_is_directory=True)
        relative = "module.py"
    result = observe_file(pin, relative)
    assert result.status in {"unreadable", "unstable"}
    assert result.file_digest is None
    assert "private_code_body" not in result.model_dump_json()


def test_rename_copy_and_path_reuse_never_rebind_old_anchor(tmp_path):
    root, pin = pinned(tmp_path)
    raw = b"def answer(): return 1\n"
    original = root / "original.py"
    original.write_bytes(raw)
    initial = observe_file(pin, "original.py", ("answer",))
    original.rename(root / "renamed.py")
    assert observe_file(pin, "original.py").status == "missing"
    renamed = observe_file(pin, "renamed.py", ("answer",))
    assert renamed.relative_path != initial.relative_path
    assert renamed.file_digest == initial.file_digest
    (root / "copy.py").write_bytes(raw)
    assert observe_file(pin, "copy.py").relative_path == "copy.py"
    original.write_bytes(b"def different(): return 2\n")
    reused = observe_file(pin, "original.py", ("answer",))
    assert reused.file_digest != initial.file_digest
    assert reused.symbol_coverage == "partial" and reused.symbols == []


def test_unsupported_language_encoding_parse_limits_and_duplicate_names_are_honest(tmp_path):
    root, pin = pinned(tmp_path)
    cases = [
        ("module.ts", b"function answer() { return 1; }\n", "unsupported"),
        ("broken.py", b"def :\n", "unsupported"),
        ("encoding.py", b"# coding: latin-1\nname = '\\xe9'\n", "unsupported"),
        ("duplicate.py", b"def answer(): return 1\ndef answer(): return 2\n", "partial"),
        ("large.py", b"#" + b"x" * 131072, "partial"),
    ]
    for path, raw, coverage in cases:
        (root / path).write_bytes(raw)
        observed = observe_file(pin, path, ("answer",))
        assert observed.status == "present"
        assert observed.symbol_coverage == coverage and observed.symbols == []
    (root / "huge.py").write_bytes(b"x" * 262145)
    assert observe_file(pin, "huge.py").status == "oversized"
    assert observe_file(pin, "missing.py").status == "missing"


@pytest.mark.parametrize("relative", ["../escape.py", "/absolute.py", "./module.py", "a//b.py", "a\\b.py"])
def test_unsafe_relative_paths_are_rejected_before_read(tmp_path, relative):
    _, pin = pinned(tmp_path)
    with pytest.raises((ValueError, DomainError)):
        observe_file(pin, relative)


def test_pin_rejects_a_symlink_in_an_absolute_ancestor(tmp_path):
    actual = (tmp_path / "actual").resolve()
    actual.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(actual, target_is_directory=True)
    with pytest.raises(DomainError) as error:
        pin_root(linked, "a" * 64)
    assert error.value.code == "HEALTH_ROOT_UNAVAILABLE"
