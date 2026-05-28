from __future__ import annotations

from typing import Any

import httpx


class PlynthError(Exception):
    """Base class for all SDK exceptions."""


class PlynthApiError(PlynthError):
    """Raised for non-2xx HTTP responses. Carries the platform's error envelope."""

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.status = status
        self.code = code
        self.message = message
        self.details: dict[str, Any] = details or {}


class PlynthNetworkError(PlynthError):
    """Raised when the request never reaches the server (DNS, timeout, etc.)."""

    def __init__(self, message: str, cause: BaseException | None = None) -> None:
        super().__init__(message)
        self.__cause__ = cause


def parse_error_response(response: httpx.Response) -> PlynthApiError:
    try:
        body = response.json()
        if not isinstance(body, dict):
            body = {}
    except ValueError:
        body = {}
    code = str(body.get("code") or "http_error")
    message = str(body.get("message") or response.reason_phrase or "")
    details = body.get("details") if isinstance(body.get("details"), dict) else {}
    return PlynthApiError(response.status_code, code, message, details)
