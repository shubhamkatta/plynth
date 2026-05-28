from __future__ import annotations

import os

from plynth_sdk import FileStore, MemoryStore


def test_memory_store_roundtrip(tokens) -> None:
    s = MemoryStore()
    assert s.get() is None
    s.set(tokens)
    assert s.get() == tokens
    s.clear()
    assert s.get() is None


def test_file_store_roundtrip(tokens, tmp_path) -> None:
    path = tmp_path / "tokens.json"
    s = FileStore(path)
    assert s.get() is None
    s.set(tokens)
    assert s.get() == tokens
    mode = os.stat(path).st_mode & 0o777
    assert mode == 0o600
    s.clear()
    assert s.get() is None
    assert not path.exists()
