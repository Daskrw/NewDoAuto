"""Supabase authentication and cloud workflow persistence for NewDoAuto."""

from newdoauto.cloud.auth import AuthSessionInfo, SupabaseAuthService
from newdoauto.cloud.config import SupabaseConfig, load_supabase_config
from newdoauto.cloud.errors import (
    AuthenticationError,
    AuthenticationRequiredError,
    CloudConfigError,
    CloudError,
    CloudNetworkError,
    InvalidCredentialsError,
    SessionExpiredError,
    UnsupportedSchemaVersionError,
    WorkflowConflictError,
    WorkflowNotFoundError,
    sanitize_error_message,
)
from newdoauto.cloud.repository import CloudWorkflowRecord, WorkflowCloudRepository

__all__ = [
    "AuthSessionInfo",
    "AuthenticationError",
    "AuthenticationRequiredError",
    "CloudConfigError",
    "CloudError",
    "CloudNetworkError",
    "CloudWorkflowRecord",
    "InvalidCredentialsError",
    "SessionExpiredError",
    "SupabaseAuthService",
    "SupabaseConfig",
    "UnsupportedSchemaVersionError",
    "WorkflowCloudRepository",
    "WorkflowConflictError",
    "WorkflowNotFoundError",
    "load_supabase_config",
    "sanitize_error_message",
]

