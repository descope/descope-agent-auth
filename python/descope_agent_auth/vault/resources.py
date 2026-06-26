"""ResourcesClient -- fetch a Resource token for the project.

Same ergonomic as ConnectionsClient. Resource tokens are tenant/resource-scoped
rather than per-user, so this maps onto the outbound tenant-token endpoints.

NOTE: the precise Descope "resource token" wire mapping is the least-pinned part
of the spec; this implementation targets the tenant-token endpoints and should be
confirmed against the API reference (see ``_endpoints`` UNVERIFIED notes).
"""

from __future__ import annotations

from typing import List, Optional

from .._endpoints import OUTBOUND_TENANT_TOKEN, OUTBOUND_TENANT_TOKEN_LATEST
from ..execution import Execution
from ..types import ApprovalRequest, VaultToken


def _cache_key(resource: str, tenant_id: Optional[str], scopes: Optional[List[str]]) -> str:
    scope_part = ",".join(sorted(scopes)) if scopes else "<defaults>"
    return f"vault:resource:{resource}:{tenant_id or '-'}:{scope_part}"


class ResourcesClient:
    def __init__(self, execution: Execution) -> None:
        self._execution = execution

    def get_token(
        self,
        *,
        resource: str,
        scopes: Optional[List[str]] = None,
        tenant_id: Optional[str] = None,
        with_refresh_token: bool = False,
        force_refresh: bool = False,
        require_approval: Optional[ApprovalRequest] = None,
    ) -> VaultToken:
        body: dict = {"appId": resource}
        if tenant_id:
            body["tenantId"] = tenant_id
        if with_refresh_token or force_refresh:
            body["options"] = {
                "withRefreshToken": with_refresh_token,
                "forceRefresh": force_refresh,
            }

        if scopes:
            path = OUTBOUND_TENANT_TOKEN
            body["scopes"] = list(scopes)
        else:
            path = OUTBOUND_TENANT_TOKEN_LATEST

        return self._execution.fetch_token(
            path=path,
            body=body,
            cache_key=_cache_key(resource, tenant_id, scopes),
            connection=resource,
            identifier=None,
            connect_body=None,  # resource tokens have no user-consent connect URL
            force_refresh=force_refresh,
            require_approval=require_approval,
        )
