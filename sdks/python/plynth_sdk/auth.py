from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Protocol

from plynth_sdk.types import Tokens


class TokenStore(Protocol):
    def get(self) -> Tokens | None: ...
    def set(self, tokens: Tokens) -> None: ...
    def clear(self) -> None: ...


class MemoryStore:
    def __init__(self) -> None:
        self._tokens: Tokens | None = None

    def get(self) -> Tokens | None:
        return self._tokens

    def set(self, tokens: Tokens) -> None:
        self._tokens = tokens

    def clear(self) -> None:
        self._tokens = None


class FileStore:
    """Persist tokens to a JSON file with mode 0600.

    Atomic writes via tempfile + rename. Useful for CLIs and long-running
    scripts. NOT suitable for multi-process concurrent writers.
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self._path = Path(path)

    def get(self) -> Tokens | None:
        if not self._path.exists():
            return None
        try:
            with self._path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        return data  # type: ignore[return-value]

    def set(self, tokens: Tokens) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=self._path.name, dir=self._path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(tokens, f)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self._path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def clear(self) -> None:
        try:
            self._path.unlink()
        except FileNotFoundError:
            pass
