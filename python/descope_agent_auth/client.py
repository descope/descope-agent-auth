"""The public client(s) -- async core plus a synchronous facade.

The SDK core is async (``httpx.AsyncClient`` all the way down). ``AsyncAgentAuthClient``
is the async public entry point; ``AgentAuthClient`` is a synchronous facade with the
same API it has always had. The facade drives the async core on a dedicated
background event-loop thread (``_LoopBridge``), so existing synchronous callers and
tests are unaffected at the call site.

Configured once with the project, the Descope base URL, and a credential provider
that encodes the phase-1 strategy. Thereafter the developer calls phase-2 exchange
(``client.connections.get_token`` / ``client.resources.get_token``) repeatedly
without thinking about the bootstrap again; refresh happens transparently.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import Future
from typing import Any, Awaitable, Dict, List, Optional, TypeVar, Union

from ._http import HttpClient, RetryConfig
from .errors import AgentAuthError
from .execution import Execution, ToolRequest
from .providers.base import CredentialProvider
from .providers.ciba import CibaProvider
from .store.base import TokenStore
from .store.memory import MemoryTokenStore
from .types import ApprovalRequest, Credential, Mode, VaultToken
from .vault._base import VaultBackend
from .vault.connections import ConnectionsClient
from .vault.resources import ResourcesClient

_log = logging.getLogger("descope_agent_auth")

_T = TypeVar("_T")


class AsyncAgentAuthClient:
    """Async public client. Every phase-2 method is awaitable."""

    def __init__(
        self,
        *,
        project_id: str,
        credential: CredentialProvider,
        base_url: str = "https://api.descope.com",
        store: Optional[TokenStore] = None,
        mode: Union[Mode, str] = Mode.FETCH,
        approval: Optional[CibaProvider] = None,
        timeout: float = 30.0,
        retry: Optional[RetryConfig] = None,
        logger: Optional[logging.Logger] = None,
        cache_tokens: bool = True,
    ) -> None:
        self.project_id = project_id
        self.base_url = base_url
        self.mode = Mode(mode)
        self.store = store or MemoryTokenStore()
        self._log = logger or _log

        self._http = HttpClient(base_url, timeout=timeout, retry=retry, logger=self._log)

        # Phase 1: bind the provider so it can talk to Descope and persist its
        # credential (incl. refresh token) to the token store.
        self.credential = credential
        self.credential.bind(self._http, project_id, self.store)
        if self.credential.is_privileged:
            self._log.warning(
                "AgentAuthClient configured with a privileged (management-key) "
                "credential: vault exchanges will BYPASS Policies."
            )

        # Optional phase-2 approval gate: a CIBA provider used to require a fresh
        # user sign-off before a sensitive exchange (see require_approval).
        self._approval = approval
        if self._approval is not None:
            self._approval.bind(self._http, project_id, self.store)

        backend = VaultBackend(
            http=self._http,
            project_id=project_id,
            get_credential=self.get_credential,
            store=self.store,
            approval_gate=self._run_approval,
            cache_tokens=cache_tokens,
        )
        # The execution seam wraps the backend: fetch is wired, execute is stubbed
        # behind the mode flag so enabling it later is a config change, not a rewrite.
        execution = Execution(mode=self.mode, backend=backend)

        # Phase 2 entry points.
        # Connection tokens come from the vault (via the execution seam); Resource
        # tokens are minted by the token-exchange grant directly off the phase-1
        # credential, so ResourcesClient is wired to the HTTP + credential layer.
        self.connections = ConnectionsClient(execution)
        self.resources = ResourcesClient(
            http=self._http,
            get_credential=self.get_credential,
            store=self.store,
            mode=self.mode,
            approval_gate=self._run_approval,
            cache_tokens=cache_tokens,
        )

    async def _run_approval(self, request: ApprovalRequest) -> None:
        """Run a CIBA approval cycle for a sensitive exchange; raise on denial/timeout."""
        if self._approval is None:
            raise AgentAuthError(
                "require_approval was set but no approval provider is configured on the "
                "client; pass approval=CibaProvider(...) to AgentAuthClient"
            )
        await self._approval.authenticate(
            login_hint=request.login_hint,
            binding_message=request.binding_message,
            scopes=request.scopes,
            timeout_seconds=request.timeout_seconds,
        )

    # -- phase 1 passthroughs ----------------------------------------------

    async def get_credential(self) -> Credential:
        """Return the current phase-1 Descope credential, refreshing if needed."""
        return await self.credential.get_credential()

    async def refresh_credential(self) -> Credential:
        return await self.credential.refresh()

    # -- lifecycle ----------------------------------------------------------

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "AsyncAgentAuthClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()


class _LoopBridge:
    """Run the async core on a private daemon event-loop thread.

    ``run(coro)`` submits a coroutine to that loop and blocks the calling
    (synchronous) thread until it completes, returning the result or re-raising the
    exception. This lets the sync facade drive the async client without the caller
    ever seeing an event loop.
    """

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop, name="descope-agent-auth-loop", daemon=True
        )
        self._thread.start()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def run(self, coro: Awaitable[_T]) -> _T:
        future: Future[_T] = asyncio.run_coroutine_threadsafe(coro, self._loop)  # type: ignore[arg-type]
        return future.result()

    def close(self) -> None:
        if not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=5.0)
            self._loop.close()


class _SyncConnections:
    """Synchronous proxy over the async ``ConnectionsClient`` (explicit signatures)."""

    def __init__(self, bridge: _LoopBridge, inner: ConnectionsClient) -> None:
        self._bridge = bridge
        self._inner = inner

    def get_token(
        self,
        *,
        connection: str,
        identifier: str,
        scopes: Optional[List[str]] = None,
        tenant_id: Optional[str] = None,
        with_refresh_token: bool = False,
        force_refresh: bool = False,
        redirect_url: Optional[str] = None,
        connect_options: Optional[Dict[str, Any]] = None,
        require_approval: Optional[ApprovalRequest] = None,
        act_as_user_token: Optional[str] = None,
    ) -> VaultToken:
        return self._bridge.run(
            self._inner.get_token(
                connection=connection,
                identifier=identifier,
                scopes=scopes,
                tenant_id=tenant_id,
                with_refresh_token=with_refresh_token,
                force_refresh=force_refresh,
                redirect_url=redirect_url,
                connect_options=connect_options,
                require_approval=require_approval,
                act_as_user_token=act_as_user_token,
            )
        )

    def get_connect_url(
        self,
        *,
        connection: str,
        identifier: str,
        scopes: Optional[List[str]] = None,
        tenant_id: Optional[str] = None,
        redirect_url: Optional[str] = None,
        connect_options: Optional[Dict[str, Any]] = None,
        act_as_user_token: Optional[str] = None,
    ) -> Optional[str]:
        return self._bridge.run(
            self._inner.get_connect_url(
                connection=connection,
                identifier=identifier,
                scopes=scopes,
                tenant_id=tenant_id,
                redirect_url=redirect_url,
                connect_options=connect_options,
                act_as_user_token=act_as_user_token,
            )
        )

    def get_tenant_token(
        self,
        *,
        connection: str,
        tenant_id: str,
        scopes: Optional[List[str]] = None,
        with_refresh_token: bool = False,
        force_refresh: bool = False,
        require_approval: Optional[ApprovalRequest] = None,
        act_as_user_token: Optional[str] = None,
    ) -> VaultToken:
        return self._bridge.run(
            self._inner.get_tenant_token(
                connection=connection,
                tenant_id=tenant_id,
                scopes=scopes,
                with_refresh_token=with_refresh_token,
                force_refresh=force_refresh,
                require_approval=require_approval,
                act_as_user_token=act_as_user_token,
            )
        )

    def wait_for_connection(
        self,
        *,
        connection: str,
        identifier: str,
        scopes: Optional[List[str]] = None,
        tenant_id: Optional[str] = None,
        act_as_user_token: Optional[str] = None,
        poll_interval: float = 2.0,
        timeout: float = 300.0,
    ) -> VaultToken:
        return self._bridge.run(
            self._inner.wait_for_connection(
                connection=connection,
                identifier=identifier,
                scopes=scopes,
                tenant_id=tenant_id,
                act_as_user_token=act_as_user_token,
                poll_interval=poll_interval,
                timeout=timeout,
            )
        )

    def execute(
        self,
        *,
        request: ToolRequest,
        connection: str,
        identifier: str,
        scopes: Optional[List[str]] = None,
        tenant_id: Optional[str] = None,
        connect_options: Optional[Dict[str, Any]] = None,
        require_approval: Optional[ApprovalRequest] = None,
        act_as_user_token: Optional[str] = None,
    ) -> Any:
        return self._bridge.run(
            self._inner.execute(
                request=request,
                connection=connection,
                identifier=identifier,
                scopes=scopes,
                tenant_id=tenant_id,
                connect_options=connect_options,
                require_approval=require_approval,
                act_as_user_token=act_as_user_token,
            )
        )


class _SyncResources:
    """Synchronous proxy over the async ``ResourcesClient`` (explicit signatures)."""

    def __init__(self, bridge: _LoopBridge, inner: ResourcesClient) -> None:
        self._bridge = bridge
        self._inner = inner

    def get_token(
        self,
        *,
        resource: str,
        scopes: Optional[List[str]] = None,
        audience: Optional[List[str]] = None,
        require_approval: Optional[ApprovalRequest] = None,
        force_refresh: bool = False,
        act_as_user_token: Optional[str] = None,
    ) -> VaultToken:
        return self._bridge.run(
            self._inner.get_token(
                resource=resource,
                scopes=scopes,
                audience=audience,
                require_approval=require_approval,
                force_refresh=force_refresh,
                act_as_user_token=act_as_user_token,
            )
        )


class AgentAuthClient:
    """Synchronous facade over :class:`AsyncAgentAuthClient`.

    Public API is identical to the original synchronous client. Internally it builds
    an async client and a private event-loop thread (``_LoopBridge``) and runs each
    async call to completion before returning.
    """

    def __init__(
        self,
        *,
        project_id: str,
        credential: CredentialProvider,
        base_url: str = "https://api.descope.com",
        store: Optional[TokenStore] = None,
        mode: Union[Mode, str] = Mode.FETCH,
        approval: Optional[CibaProvider] = None,
        timeout: float = 30.0,
        retry: Optional[RetryConfig] = None,
        logger: Optional[logging.Logger] = None,
        cache_tokens: bool = True,
    ) -> None:
        self._bridge = _LoopBridge()
        # The async client builds an httpx.AsyncClient, which must be created on the
        # loop's thread so it binds to the right running loop.
        self._async = self._bridge.run(
            _make_async_client(
                project_id=project_id,
                credential=credential,
                base_url=base_url,
                store=store,
                mode=mode,
                approval=approval,
                timeout=timeout,
                retry=retry,
                logger=logger,
                cache_tokens=cache_tokens,
            )
        )
        self.connections = _SyncConnections(self._bridge, self._async.connections)
        self.resources = _SyncResources(self._bridge, self._async.resources)

    # -- attribute passthroughs (parity with the old public surface) -------

    @property
    def project_id(self) -> str:
        return self._async.project_id

    @property
    def base_url(self) -> str:
        return self._async.base_url

    @property
    def mode(self) -> Mode:
        return self._async.mode

    @property
    def store(self) -> TokenStore:
        return self._async.store

    @property
    def credential(self) -> CredentialProvider:
        return self._async.credential

    # -- phase 1 passthroughs ----------------------------------------------

    def get_credential(self) -> Credential:
        """Return the current phase-1 Descope credential, refreshing if needed."""
        return self._bridge.run(self._async.get_credential())

    def refresh_credential(self) -> Credential:
        return self._bridge.run(self._async.refresh_credential())

    # -- lifecycle ----------------------------------------------------------

    def close(self) -> None:
        try:
            self._bridge.run(self._async.aclose())
        finally:
            self._bridge.close()

    def __enter__(self) -> "AgentAuthClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


async def _make_async_client(**kwargs: Any) -> AsyncAgentAuthClient:
    """Construct the async client on the loop thread (so httpx binds to that loop)."""
    return AsyncAgentAuthClient(**kwargs)
