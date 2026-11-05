"""descope-agent-auth: acquire a Descope credential for an agent, then exchange it
for Connection / Resource tokens from the Descope vault. Two phases, nothing more.
"""

from .client import AgentAuthClient, AsyncAgentAuthClient
from .execution import Execution, ToolRequest
from .errors import (
    AgentAuthError,
    ApprovalDenied,
    ApprovalTimeout,
    ConnectionAuthorizationRequired,
    CredentialAcquisitionFailed,
    PolicyDenied,
    TokenExchangeFailed,
)
from .providers import (
    AccessTokenProvider,
    CibaProvider,
    ClientCredentialsProvider,
    CredentialProvider,
    DeviceCodeProvider,
    JwtBearerProvider,
    ManagementKeyProvider,
)
from .store import MemoryTokenStore, TokenStore
from .tools import with_connection, with_connection_async
from .types import (
    ApprovalRequest,
    Credential,
    CredentialKind,
    Mode,
    PendingAuthorization,
    VaultToken,
)

__version__ = "0.1.1"

__all__ = [
    "AgentAuthClient",
    "AsyncAgentAuthClient",
    # providers
    "CredentialProvider",
    "ClientCredentialsProvider",
    "DeviceCodeProvider",
    "CibaProvider",
    "JwtBearerProvider",
    "ManagementKeyProvider",
    "AccessTokenProvider",
    # store
    "TokenStore",
    "MemoryTokenStore",
    # tools
    "with_connection",
    "with_connection_async",
    # execution seam
    "Execution",
    "ToolRequest",
    # types
    "Credential",
    "CredentialKind",
    "Mode",
    "PendingAuthorization",
    "ApprovalRequest",
    "VaultToken",
    # errors
    "AgentAuthError",
    "ConnectionAuthorizationRequired",
    "PolicyDenied",
    "CredentialAcquisitionFailed",
    "TokenExchangeFailed",
    "ApprovalDenied",
    "ApprovalTimeout",
]
