"""The fetch-vs-execute seam (forward-compat for the hosted proxy).

This is the most important architectural constraint in the spec, and it costs
almost nothing to design in now:

* ``mode="fetch"`` (default, ships today): phase 2 returns the raw downstream
  token to the caller's code. The token lives in the agent process.
* ``mode="execute"`` (future, lands with the proxy): phase 2 does NOT return the
  raw token. Instead the SDK routes the actual downstream API call through
  Descope's hosted execution endpoint, where the token stays vaulted, the call is
  policy-checked and audited, and only the result comes back.

Both modes share one ergonomic. Only the fetch path is wired here; the execute
path is stubbed behind the ``mode`` flag so flipping to it later is a config
change, not a rewrite.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

from .errors import AgentAuthError
from .types import Mode, VaultToken

if TYPE_CHECKING:
    from .vault._base import VaultBackend


@dataclass(frozen=True)
class ToolRequest:
    """Describes a downstream API call for execute mode.

    In execute mode the caller passes one of these (method, URL, body) instead of
    receiving a token; Descope makes the call with the vaulted token and returns
    only the result.
    """

    method: str
    url: str
    headers: Optional[dict] = None
    body: Any = None


class Execution:
    """Routes phase-2 operations according to the configured mode."""

    def __init__(self, *, mode: Mode, backend: "VaultBackend") -> None:
        self._mode = mode
        self._backend = backend

    @property
    def mode(self) -> Mode:
        return self._mode

    async def fetch_token(self, **fetch_args: Any) -> VaultToken:
        """Fetch path: return the raw vault token (fetch mode only)."""
        if self._mode is Mode.EXECUTE:
            raise AgentAuthError(
                "raw token fetch is disabled in execute mode; the token stays vaulted. "
                "Use execute() to route the call through Descope instead."
            )
        return await self._backend.fetch(**fetch_args)

    async def execute(self, *, request: ToolRequest, **fetch_args: Any) -> Any:
        """Execute path: route the call through Descope's hosted execution endpoint.

        Stubbed until core eng ships the endpoint. The seam exists so that turning
        this on is a ``mode`` change for the developer, not a rewrite.
        """
        if self._mode is not Mode.EXECUTE:
            raise AgentAuthError("execute() requires the client to be created with mode='execute'")
        raise NotImplementedError(
            "mode='execute' routes calls through Descope's hosted execution endpoint, "
            "which is not yet available in this SDK build. Use mode='fetch' for now."
        )
