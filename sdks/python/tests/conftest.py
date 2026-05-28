from __future__ import annotations

import pytest

from plynth_sdk.types import Tokens


@pytest.fixture
def tokens() -> Tokens:
    return {
        "access_token": "a1",
        "refresh_token": "r1",
        "token_type": "bearer",
        "expires_at": "2099-01-01T00:00:00Z",
    }
