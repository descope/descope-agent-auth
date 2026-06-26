"""AgentAuthClient -- the main entry point.

Configured once with the project, the Descope base URL, and a credential provider
that encodes the phase-1 strategy. Thereafter the developer calls phase-2 exchange
(``client.connections.get_token`` / ``client.resources.get_token``) repeatedly
without thinking about the bootstrap again; refresh happens transparently.
"""

from __future__ import annotations

import logging
from typing import Optional, Union

from ._http import HttpClient, RetryConfig
from .errors import AgentAuthError
from .execution import Execution
from .providers.base import CredentialProvider
from .providers.ciba import CibaProvider
from .store.base import TokenStore
from .store.memory import MemoryTokenStore
from .types import ApprovalRequest, Credential, Mode
from .vault._base import VaultBackend
from .vault.connections import ConnectionsClient
from .vault.resources import ResourcesClient

_log = logging.getLogger("descope_agent_auth")


class AgentAuthClient:
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
        )

    def _run_approval(self, request: ApprovalRequest) -> None:
        """Run a CIBA approval cycle for a sensitive exchange; raise on denial/timeout."""
        if self._approval is None:
            raise AgentAuthError(
                "require_approval was set but no approval provider is configured on the "
                "client; pass approval=CibaProvider(...) to AgentAuthClient"
            )
        self._approval.authenticate(
            login_hint=request.login_hint,
            binding_message=request.binding_message,
            scopes=request.scopes,
            timeout_seconds=request.timeout_seconds,
        )

    # -- phase 1 passthroughs ----------------------------------------------

    def get_credential(self) -> Credential:
        """Return the current phase-1 Descope credential, refreshing if needed."""
        return self.credential.get_credential()

    def refresh_credential(self) -> Credential:
        return self.credential.refresh()

    # -- lifecycle ----------------------------------------------------------

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "AgentAuthClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
