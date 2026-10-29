"""
Custom exception hierarchy and secret sanitization utilities for NewDoAuto Cloud.
Ensures credentials, JWTs, passwords, and sensitive tokens are never leaked in error messages.
"""

from __future__ import annotations
import re
from typing import Optional

# Matches standard JWTs (three base64url segments starting with eyJ)
_JWT_PATTERN = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")
# Matches Bearer tokens or apikey/password/secret headers, query params, or JSON fields
_BEARER_PATTERN = re.compile(
    r"""(?i)(bearer\s+|["']?(?:apikey|password|secret)["']?\s*[=:]\s*["']?)([^\s,;\"'&]+)""",
)


def sanitize_error_message(message: str, extra_secrets: Optional[list[str]] = None) -> str:
    """
    Removes JWT tokens, Bearer credentials, passwords, and any explicitly provided secret strings
    from an error message before logging or raising to callers.
    """
    if not message:
        return "Unknown cloud error"

    sanitized = _JWT_PATTERN.sub("[REDACTED_JWT]", str(message))
    sanitized = _BEARER_PATTERN.sub(r"\1[REDACTED]", sanitized)

    if extra_secrets:
        for secret in extra_secrets:
            if secret and len(secret) >= 6:
                sanitized = sanitized.replace(secret, "[REDACTED]")

    return sanitized


class CloudError(Exception):
    """Base exception for all NewDoAuto cloud operations."""

    def __init__(self, message: str):
        super().__init__(sanitize_error_message(message))


class CloudConfigError(CloudError):
    """Raised when Supabase URL or publishable anon key is missing, invalid, or unsafe."""
    pass


class AuthenticationError(CloudError):
    """Raised when authentication fails."""
    pass


class InvalidCredentialsError(AuthenticationError):
    """Raised when email/password sign-in or registration fails due to bad credentials."""
    pass


class AuthenticationRequiredError(AuthenticationError):
    """Raised when a cloud operation is attempted without an active authenticated session."""
    pass


class SessionExpiredError(AuthenticationError):
    """Raised when a stored or active session token has expired and cannot be refreshed."""
    pass


class CloudNetworkError(CloudError):
    """Raised when a network failure or timeout occurs while communicating with Supabase."""
    pass


class WorkflowNotFoundError(CloudError):
    """Raised when a requested workflow ID does not exist or is not accessible to the user."""

    def __init__(self, workflow_id: str):
        super().__init__(f"Workflow '{workflow_id}' was not found or is not accessible.")
        self.workflow_id = workflow_id


class WorkflowConflictError(CloudError):
    """
    Raised when an optimistic concurrency check fails during workflow update
    (i.e. expected_version does not match the current version in Supabase).
    """

    def __init__(self, workflow_id: str, expected_version: int, actual_version: Optional[int] = None):
        detail = (
            f"expected version {expected_version}, but cloud has version {actual_version}"
            if actual_version is not None
            else f"expected version {expected_version} is stale"
        )
        super().__init__(
            f"Conflict detected while updating workflow '{workflow_id}': {detail}. "
            "Refusing to overwrite newer cloud changes."
        )
        self.workflow_id = workflow_id
        self.expected_version = expected_version
        self.actual_version = actual_version


class UnsupportedSchemaVersionError(CloudError):
    """Raised when a workflow uses an unsupported schema_version."""

    def __init__(self, schema_version: str):
        super().__init__(f"Unsupported workflow schema_version '{schema_version}'.")
        self.schema_version = schema_version
