"""LangGraph integration: turn re-auth / approval signals into ``interrupt()``s.

A thin, optional helper. The core ``with_connection`` already drops a scoped token
into any tool; this variant additionally catches the SDK's re-auth / approval
exceptions and converts them into a LangGraph ``interrupt()``, so the graph pauses
for the human (for example, to complete an OAuth connect) and retries
automatically when the graph is resumed.

The SDK itself never depends on LangGraph. ``langgraph`` is resolved lazily and
only when an interrupt actually needs to fire -- a tool that never hits a re-auth
path never imports it. Install ``descope-agent-auth[langgraph]``, or pass your own
``interrupt`` callable (handy for tests or non-default setups).

    from descope_agent_auth.integrations.langgraph import connection_tool

    @connection_tool(client, connection="github", scopes=["repo"])
    def list_repos(token, identifier):
        return [r.name for r in GitHub(auth=token).repos.list_for_authenticated_user()]

On ``ConnectionAuthorizationRequired`` the graph interrupts with a payload carrying
the connect URL; resume it (``Command(resume=...)``) after the user connects and
the tool retries the exchange.
"""

from __future__ import annotations

import functools
from typing import Callable, List, Optional, Sequence, Type

from ..errors import (
    AgentAuthError,
    ApprovalDenied,
    ApprovalTimeout,
    ConnectionAuthorizationRequired,
)
from ..types import ApprovalRequest


def _default_interrupt() -> Callable[[object], object]:
    try:
        from langgraph.types import interrupt
    except ImportError as exc:  # pragma: no cover - exercised via a forced ImportError
        raise ImportError(
            "the LangGraph integration requires 'langgraph'. Install "
            "descope-agent-auth[langgraph], or pass interrupt=... explicitly."
        ) from exc
    return interrupt


def interrupt_payload(exc: AgentAuthError) -> dict:
    """Build the structured value handed to ``interrupt()`` for a given SDK error."""
    if isinstance(exc, ConnectionAuthorizationRequired):
        return {
            "type": "connection_authorization_required",
            "connection": exc.connection,
            "identifier": exc.identifier,
            "connect_url": exc.connect_url,
            "message": str(exc),
        }
    if isinstance(exc, ApprovalDenied):
        return {"type": "approval_denied", "message": str(exc)}
    if isinstance(exc, ApprovalTimeout):
        return {"type": "approval_timeout", "message": str(exc)}
    return {"type": "error", "message": str(exc)}


def connection_tool(
    client: "AgentAuthClient",  # noqa: F821  (avoid import cycle)
    *,
    connection: str,
    scopes: Optional[List[str]] = None,
    tenant_id: Optional[str] = None,
    require_approval: Optional[ApprovalRequest] = None,
    interrupt: Optional[Callable[[object], object]] = None,
    interrupt_on: Sequence[Type[AgentAuthError]] = (ConnectionAuthorizationRequired,),
) -> Callable[[Callable], Callable]:
    """LangGraph-aware variant of ``with_connection``.

    Wraps a tool ``fn(token, identifier, *args, **kwargs)``: fetches the scoped
    Connection token, and on any exception in ``interrupt_on`` calls
    ``interrupt(payload)`` so the graph pauses, retrying on resume. ``interrupt``
    defaults to ``langgraph.types.interrupt`` (resolved lazily); pass your own to
    avoid the dependency or for testing.
    """
    interruptible = tuple(interrupt_on)

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(identifier: str, *args: object, **kwargs: object) -> object:
            while True:
                try:
                    token = client.connections.get_token(
                        connection=connection,
                        identifier=identifier,
                        scopes=scopes,
                        tenant_id=tenant_id,
                        require_approval=require_approval,
                    )
                    return fn(token.access_token, identifier, *args, **kwargs)
                except interruptible as exc:
                    # Resolve interrupt lazily, only when one actually needs to fire,
                    # so a happy-path call never imports LangGraph. On the first pass
                    # interrupt() raises to pause the graph; on resume the node re-runs
                    # and we retry the exchange.
                    do_interrupt = interrupt or _default_interrupt()
                    do_interrupt(interrupt_payload(exc))

        return wrapper

    return decorator
