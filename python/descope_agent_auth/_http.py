"""Thin asynchronous HTTP layer over httpx.

Responsibilities kept deliberately small: build absolute URLs from ``base_url``,
apply timeout + bounded retry on transient failures, and -- critically -- never
emit credential values in logs. All higher layers (providers, vault) speak to
Descope through a single ``HttpClient`` instance.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

import httpx

from .errors import AgentAuthError

_REDACTED = "***redacted***"
_SENSITIVE_KEYS = {
    "authorization",
    "client_secret",
    "code",
    "code_verifier",
    "refresh_token",
    "access_token",
    "accesstoken",
    "refreshtoken",
    "token",
    "management_key",
    "device_code",
    "auth_req_id",
    "assertion",
}


def _redact(data: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Return a copy of ``data`` with sensitive values masked for logging."""
    if not data:
        return {}
    out: Dict[str, Any] = {}
    for key, value in data.items():
        if key.lower() in _SENSITIVE_KEYS:
            out[key] = _REDACTED
        elif isinstance(value, Mapping):
            out[key] = _redact(value)
        else:
            out[key] = value
    return out


@dataclass(frozen=True)
class RetryConfig:
    attempts: int = 3
    backoff_seconds: float = 0.25
    retry_statuses: frozenset = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    json: Any
    text: str

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300


class HttpClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 30.0,
        retry: Optional[RetryConfig] = None,
        logger: Optional[logging.Logger] = None,
        _transport: Optional[httpx.AsyncBaseTransport] = None,  # tests inject this
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._retry = retry or RetryConfig()
        self._log = logger or logging.getLogger("descope_agent_auth.http")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout,
            transport=_transport,
            headers={"User-Agent": "descope-agent-auth-python/0.1.0"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "HttpClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def post_json(
        self,
        path: str,
        *,
        json: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
    ) -> HttpResponse:
        return await self._request("POST", path, json=json, headers=headers)

    async def post_form(
        self,
        path: str,
        *,
        data: Mapping[str, Any],
        headers: Optional[Mapping[str, str]] = None,
    ) -> HttpResponse:
        return await self._request("POST", path, data=data, headers=headers)

    async def get(
        self,
        path: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
    ) -> HttpResponse:
        return await self._request("GET", path, params=params, headers=headers)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Optional[Mapping[str, Any]] = None,
        data: Optional[Mapping[str, Any]] = None,
        params: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
    ) -> HttpResponse:
        last_exc: Optional[Exception] = None
        for attempt in range(1, self._retry.attempts + 1):
            self._log.debug(
                "descope request %s %s body=%s headers=%s (attempt %d)",
                method,
                path,
                _redact(json or data),
                _redact(headers),
                attempt,
            )
            try:
                resp = await self._client.request(
                    method, path, json=json, data=data, params=params, headers=headers
                )
            except httpx.HTTPError as exc:  # transport-level failure
                last_exc = exc
                if attempt < self._retry.attempts:
                    await asyncio.sleep(self._retry.backoff_seconds * attempt)
                    continue
                raise AgentAuthError(f"HTTP transport error calling {path}: {exc}") from exc

            if resp.status_code in self._retry.retry_statuses and attempt < self._retry.attempts:
                await asyncio.sleep(self._retry.backoff_seconds * attempt)
                continue

            parsed: Any = None
            try:
                parsed = resp.json()
            except ValueError:
                parsed = None
            self._log.debug("descope response %s %s -> %d", method, path, resp.status_code)
            return HttpResponse(status_code=resp.status_code, json=parsed, text=resp.text)

        # Only reached if all attempts raised transport errors.
        raise AgentAuthError(f"HTTP request to {path} failed") from last_exc
