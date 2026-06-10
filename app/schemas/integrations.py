"""Pydantic schemas for the platform's integrations passthrough endpoints.

Today: Google OAuth code/refresh exchange. The platform holds the
client_secret in the per-product env vault and performs the swap with
Google on the client's behalf so the secret never reaches a user
device.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class GoogleExchangeCodeRequest(BaseModel):
    """`authorization_code` grant — first exchange after the consent URL
    redirects back to the client's loopback. ``code_verifier`` is the
    plaintext PKCE verifier whose S256 hash equalled the
    ``code_challenge`` the client sent to Google's /auth endpoint."""

    model_config = ConfigDict(extra="forbid")

    grant_type:    Literal["authorization_code"]
    client_id:     str = Field(min_length=10, max_length=2048)
    code:          str = Field(min_length=10, max_length=2048)
    # PKCE verifier — RFC 7636 says 43-128 chars; we enforce that range.
    code_verifier: str = Field(min_length=43, max_length=128)
    redirect_uri:  str = Field(min_length=1, max_length=2048)


class GoogleExchangeRefreshRequest(BaseModel):
    """`refresh_token` grant — produces a fresh access_token. Google
    usually does NOT return a new refresh_token here; clients keep the
    one they already have."""

    model_config = ConfigDict(extra="forbid")

    grant_type:    Literal["refresh_token"]
    client_id:     str = Field(min_length=10, max_length=2048)
    refresh_token: str = Field(min_length=1, max_length=2048)


GoogleExchangeRequest = Annotated[
    GoogleExchangeCodeRequest | GoogleExchangeRefreshRequest,
    Field(discriminator="grant_type"),
]


class GoogleExchangeResponse(BaseModel):
    """Pass-through of Google's token response. ``refresh_token`` is
    present on first code-exchange and absent on most refresh-grant
    responses (do NOT synthesize it). ``scope`` and ``token_type`` are
    technically optional per RFC 6749 but Google always returns them."""

    # extra="allow" tolerates Google adding fields in the future
    # (e.g. id_token for openid scopes) — we pass them through.
    model_config = ConfigDict(extra="allow")

    access_token:  str
    expires_in:    int
    refresh_token: str | None = None
    scope:         str | None = None
    token_type:    str | None = None
    id_token:      str | None = None
