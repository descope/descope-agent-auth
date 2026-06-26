"""descope-agent-auth: acquire a Descope credential for an agent, then exchange it
for Connection / Resource tokens from the Descope vault. Two phases, nothing more.
"""

from .client import AgentAuthClient
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
    AuthorizationCodeProvider,
    CibaProvider,
    ClientCredentialsProvider,
    CredentialProvider,
    DeviceCodeProvider,
    ManagementKeyProvider,
)
from .store import MemoryTokenStore, TokenStore
from .tools import with_connection
from .types import (
    ApprovalRequest,
    Credential,
    CredentialKind,
    Mode,
    PendingAuthorization,
    VaultToken,
)

__version__ = "0.1.0"

__all__ = [
    "AgentAuthClient",
    # providers
    "CredentialProvider",
    "ClientCredentialsProvider",
    "DeviceCodeProvider",
    "AuthorizationCodeProvider",
    "CibaProvider",
    "ManagementKeyProvider",
    # store
    "TokenStore",
    "MemoryTokenStore",
    # tools
    "with_connection",
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
