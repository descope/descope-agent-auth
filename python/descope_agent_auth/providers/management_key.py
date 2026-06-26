"""ManagementKeyProvider -- privileged, NOT recommended.

Wraps a static project Management Key. This is not a flow; it is a high-privilege
credential that grants access to effectively everything in the vault and
**bypasses Connection Policies**. Support it for server-side/administrative cases,
but make the recommended-path guidance unmissable: construction requires an
explicit ``allow_management_key=True`` opt-in and emits a warning on init.
"""

from __future__ import annotations

import logging

from ..errors import CredentialAcquisitionFailed
from ..types import Credential, CredentialKind
from .base import CredentialProvider

_log = logging.getLogger("descope_agent_auth.providers")


class ManagementKeyProvider(CredentialProvider):
    kind = CredentialKind.MANAGEMENT_KEY

    def __init__(self, *, management_key: str, allow_management_key: bool = False) -> None:
        super().__init__()
        if not allow_management_key:
            raise CredentialAcquisitionFailed(
                "ManagementKeyProvider bypasses Connection Policies and grants broad "
                "vault access. It is not the recommended path. To proceed deliberately, "
                "pass allow_management_key=True."
            )
        self._management_key = management_key
        _log.warning(
            "ManagementKeyProvider in use: this credential BYPASSES Connection Policies "
            "and grants broad vault access. Prefer an agent-token provider where possible."
        )

    def _acquire(self) -> Credential:
        # A management key is static -- no acquisition or refresh needed.
        return Credential(token=self._management_key, kind=self.kind, expires_at=None)

    def refresh(self) -> Credential:  # nothing to refresh
        return self._acquire()
