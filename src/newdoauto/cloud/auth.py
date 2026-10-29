"""
Authentication and session management layer for NewDoAuto using Supabase Auth.
Supports sign-up, sign-in, sign-out, and secure session restoration across restarts
without ever storing user passwords on disk.
"""

from __future__ import annotations
from dataclasses import dataclass
import json
import os
import time
from typing import Any, Optional

import httpx

from newdoauto.cloud.config import SupabaseConfig, load_supabase_config
from newdoauto.cloud.errors import (
    AuthenticationError,
    AuthenticationRequiredError,
    CloudNetworkError,
    InvalidCredentialsError,
    SessionExpiredError,
    sanitize_error_message,
)


def _default_session_file_path() -> str:
    """Returns a user-scoped path for storing non-password session tokens."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, "NewDoAuto", "session.json")
    return os.path.expanduser("~/.config/newdoauto/session.json")


@dataclass(frozen=True)
class AuthSessionInfo:
    """Public metadata for an active authenticated session (redacts tokens in repr)."""
    user_id: str
    email: str
    access_token: str
    refresh_token: str
    expires_at: Optional[int] = None

    def __repr__(self) -> str:
        return (
            f"AuthSessionInfo(user_id={self.user_id!r}, email={self.email!r}, "
            f"expires_at={self.expires_at!r}, access_token='[REDACTED]', refresh_token='[REDACTED]')"
        )

    def is_expired(self, clock_skew_seconds: int = 30) -> bool:
        if self.expires_at is None:
            return False
        return time.time() + clock_skew_seconds >= self.expires_at


class SupabaseAuthService:
    """
    Manages user authentication and session lifecycle against Supabase Auth.
    Can be initialized with an explicit Supabase client (or mock client for unit tests).
    """

    def __init__(
        self,
        config: Optional[SupabaseConfig] = None,
        client: Optional[Any] = None,
        session_file: Optional[str] = None,
        persist_session: bool = True,
    ):
        self.config = config or (load_supabase_config() if client is None else None)
        self._client = client
        self.session_file = session_file or _default_session_file_path()
        self.persist_session = persist_session
        self._current_session: Optional[AuthSessionInfo] = None

    @property
    def client(self) -> Any:
        if self._client is None:
            from supabase import create_client
            if self.config is None:
                self.config = load_supabase_config()
            self._client = create_client(self.config.url, self.config.anon_key)
        return self._client

    @property
    def current_session(self) -> Optional[AuthSessionInfo]:
        return self._current_session

    def sign_up(self, email: str, password: str) -> AuthSessionInfo:
        """
        Registers a new user account with email and password.
        Note: If email confirmation is required by the Supabase project, session tokens
        may not be issued until the email is verified.
        """
        self._validate_email_password(email, password)
        try:
            response = self.client.auth.sign_up({"email": email.strip(), "password": password})
        except Exception as exc:
            self._handle_auth_exception(exc, extra_secrets=[password])

        user = getattr(response, "user", None)
        session = getattr(response, "session", None)
        if user is None:
            raise AuthenticationError("Account registration did not return a user record.")

        if session is None:
            # Email confirmation enabled on project
            return AuthSessionInfo(
                user_id=str(user.id),
                email=str(getattr(user, "email", email.strip())),
                access_token="",
                refresh_token="",
                expires_at=None,
            )

        session_info = self._extract_session_info(user, session)
        self._current_session = session_info
        if self.persist_session:
            self._save_session_to_disk(session_info)
        return session_info

    def sign_in(self, email: str, password: str) -> AuthSessionInfo:
        """Authenticates an existing user with email and password."""
        self._validate_email_password(email, password)
        try:
            response = self.client.auth.sign_in_with_password(
                {"email": email.strip(), "password": password}
            )
        except Exception as exc:
            self._handle_auth_exception(exc, extra_secrets=[password])

        user = getattr(response, "user", None)
        session = getattr(response, "session", None)
        if user is None or session is None:
            raise InvalidCredentialsError("Invalid email or password.")

        session_info = self._extract_session_info(user, session)
        self._current_session = session_info
        if self.persist_session:
            self._save_session_to_disk(session_info)
        return session_info

    def sign_out(self) -> None:
        """Signs out the current user and clears any persisted local session tokens."""
        try:
            if self._client is not None:
                self.client.auth.sign_out()
        except Exception as exc:
            # Clear local state even if remote sign-out encounters a network error
            self._clear_local_session()
            self._handle_auth_exception(exc)
        finally:
            self._clear_local_session()

    def restore_session(self) -> Optional[AuthSessionInfo]:
        """
        Attempts to restore a previously saved session from disk on application startup.
        Validates/refreshes with Supabase Auth. Clears disk tokens if expired or revoked.
        """
        raw = self._load_session_from_disk()
        if not raw:
            return None

        access_token = raw.get("access_token", "")
        refresh_token = raw.get("refresh_token", "")
        if not access_token or not refresh_token:
            self._clear_local_session()
            return None

        try:
            response = self.client.auth.set_session(access_token, refresh_token)
            user = getattr(response, "user", None)
            session = getattr(response, "session", None)
            if user is None or session is None:
                self._clear_local_session()
                raise SessionExpiredError("Stored session is no longer valid. Please sign in again.")

            session_info = self._extract_session_info(user, session)
            self._current_session = session_info
            if self.persist_session:
                self._save_session_to_disk(session_info)
            return session_info
        except SessionExpiredError:
            raise
        except Exception as exc:
            if self._is_network_exception(exc):
                raise CloudNetworkError(
                    f"Network error while restoring session: {sanitize_error_message(str(exc))}"
                ) from exc
            self._clear_local_session()
            raise SessionExpiredError(
                f"Session expired or invalid: {sanitize_error_message(str(exc))}"
            ) from exc

    def require_authenticated_session(self) -> AuthSessionInfo:
        """
        Returns the active authenticated session, attempting to refresh if expired.
        Raises AuthenticationRequiredError or SessionExpiredError if unavailable.
        """
        if self._current_session is None or not self._current_session.access_token:
            raise AuthenticationRequiredError(
                "Authentication required. Please sign in before performing cloud workflow operations."
            )

        if self._current_session.is_expired():
            try:
                response = self.client.auth.refresh_session(self._current_session.refresh_token)
                user = getattr(response, "user", None)
                session = getattr(response, "session", None)
                if user is None or session is None:
                    self._clear_local_session()
                    raise SessionExpiredError("Session has expired and could not be refreshed.")
                self._current_session = self._extract_session_info(user, session)
                if self.persist_session:
                    self._save_session_to_disk(self._current_session)
            except SessionExpiredError:
                raise
            except Exception as exc:
                if self._is_network_exception(exc):
                    raise CloudNetworkError(
                        f"Network error while refreshing session: {sanitize_error_message(str(exc))}"
                    ) from exc
                self._clear_local_session()
                raise SessionExpiredError(
                    f"Session expired and refresh failed: {sanitize_error_message(str(exc))}"
                ) from exc

        return self._current_session

    @staticmethod
    def _validate_email_password(email: str, password: str) -> None:
        if not email or "@" not in email.strip():
            raise InvalidCredentialsError("A valid email address is required.")
        if not password or len(password) < 6:
            raise InvalidCredentialsError("Password must be at least 6 characters.")

    @staticmethod
    def _extract_session_info(user: Any, session: Any) -> AuthSessionInfo:
        return AuthSessionInfo(
            user_id=str(getattr(user, "id", "")),
            email=str(getattr(user, "email", "")),
            access_token=str(getattr(session, "access_token", "")),
            refresh_token=str(getattr(session, "refresh_token", "")),
            expires_at=getattr(session, "expires_at", None),
        )

    @staticmethod
    def _is_network_exception(exc: Exception) -> bool:
        if isinstance(exc, (httpx.RequestError, httpx.TimeoutException, TimeoutError, ConnectionError)):
            return True
        msg = str(exc).lower()
        return any(k in msg for k in ("timed out", "timeout", "connection refused", "network", "dns", "connecterror"))

    def _handle_auth_exception(self, exc: Exception, extra_secrets: Optional[list[str]] = None) -> None:
        clean_msg = sanitize_error_message(str(exc), extra_secrets=extra_secrets)
        if self._is_network_exception(exc):
            raise CloudNetworkError(f"Network error communicating with Supabase Auth: {clean_msg}") from exc

        lower = clean_msg.lower()
        if any(k in lower for k in ("invalid login credentials", "invalid email or password", "invalid_grant", "user not found")):
            raise InvalidCredentialsError(f"Authentication failed: {clean_msg}") from exc
        if any(k in lower for k in ("expired", "refresh_token_not_found", "invalid token", "jwt")):
            raise SessionExpiredError(f"Session expired: {clean_msg}") from exc

        raise AuthenticationError(f"Authentication error: {clean_msg}") from exc

    def _save_session_to_disk(self, session_info: AuthSessionInfo) -> None:
        if not session_info.access_token:
            return
        try:
            parent = os.path.dirname(self.session_file)
            if parent:
                os.makedirs(parent, exist_ok=True)
            payload = {
                "user_id": session_info.user_id,
                "email": session_info.email,
                "access_token": session_info.access_token,
                "refresh_token": session_info.refresh_token,
                "expires_at": session_info.expires_at,
            }
            with open(self.session_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except Exception:
            # Non-fatal if disk write fails in restricted environment
            pass

    def _load_session_from_disk(self) -> Optional[dict[str, Any]]:
        if not os.path.exists(self.session_file):
            return None
        try:
            with open(self.session_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def _clear_local_session(self) -> None:
        self._current_session = None
        if self.session_file and os.path.exists(self.session_file):
            try:
                os.remove(self.session_file)
            except Exception:
                pass

