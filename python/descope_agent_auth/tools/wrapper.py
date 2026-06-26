"""The tool wrapper (three-line ergonomic).

A convenience layer so an AI-generated or handwritten tool gets its scoped,
fresh token injected without the author writing exchange logic. This is what the
``descope/skills`` generation pattern targets.

    @with_connection(client, connection="github", scopes=["repo"])
    def list_repos(token, identifier):
        gh = GitHub(auth=token)              # token injected, already scoped + fresh
        return [r.name for r in gh.repos.list_for_authenticated_user()]

    repos = list_repos(identifier="user@example.com")

The wrapper resolves the identifier (server-side, never from untrusted input),
fetches the scoped token via phase 2, injects it, and lets the
``ConnectionAuthorizationRequired`` re-auth signal propagate to the caller.
"""

from __future__ import annotations

import functools
from typing import Callable, List, Optional, TypeVar

from ..types import ApprovalRequest

F = TypeVar("F", bound=Callable[..., object])


def with_connection(
    client: "AgentAuthClient",  # noqa: F821  (avoid import cycle)
    *,
    connection: str,
    scopes: Optional[List[str]] = None,
    tenant_id: Optional[str] = None,
    require_approval: Optional[ApprovalRequest] = None,
) -> Callable[[F], F]:
    """Decorate a tool ``fn(token, identifier, *args, **kwargs)`` to auto-inject a token.

    The decorated callable is invoked as ``fn(identifier=..., *args, **kwargs)``;
    the wrapper fetches the scoped Connection token for that identity and calls the
    original function with the raw token string as its first positional argument.
    """

    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(identifier: str, *args: object, **kwargs: object) -> object:
            token = client.connections.get_token(
                connection=connection,
                identifier=identifier,
                scopes=scopes,
                tenant_id=tenant_id,
                require_approval=require_approval,
            )
            return fn(token.access_token, identifier, *args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator
