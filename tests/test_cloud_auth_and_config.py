"""
Unit and mocked tests for Supabase configuration validation, secret redaction,
and SupabaseAuthService authentication and session lifecycle.
"""

from __future__ import annotations
import base64
import json
import os
import time
from types import SimpleNamespace
import httpx
import pytest

from newdoauto.cloud.auth import AuthSessionInfo, SupabaseAuthService
from newdoauto.cloud.config import SupabaseConfig, load_supabase_config
from newdoauto.cloud.errors import (
    AuthenticationRequiredError,
    CloudConfigError,
    CloudNetworkError,
    InvalidCredentialsError,
    SessionExpiredError,
    sanitize_error_message,
)


def _make_fake_jwt(role: str = "anon") -> str:
    header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()).decode().rstrip("=")
    payload = base64.urlsafe_b64encode(
        json.dumps({"iss": "supabase", "role": role, "exp": 2085923364}).encode()
    ).decode().rstrip("=")
    sig = "fakesignature1234567890"
    return f"{header}.{payload}.{sig}"


class FakeAuthNamespace:
    """In-memory fake for client.auth used in deterministic unit tests."""

    def __init__(self):
        self.sign_up_response = None
        self.sign_in_response = None
        self.set_session_response = None
        self.refresh_session_response = None
        self.raise_on_call: Exception | None = None
        self.signed_out = False

    def sign_up(self, credentials: dict):
        if self.raise_on_call:
            raise self.raise_on_call
        return self.sign_up_response

    def sign_in_with_password(self, credentials: dict):
        if self.raise_on_call:
            raise self.raise_on_call
        return self.sign_in_response

    def set_session(self, access_token: str, refresh_token: str):
        if self.raise_on_call:
            raise self.raise_on_call
        return self.set_session_response

    def refresh_session(self, refresh_token: str):
        if self.raise_on_call:
            raise self.raise_on_call
        return self.refresh_session_response

    def sign_out(self):
        self.signed_out = True
        if self.raise_on_call:
            raise self.raise_on_call


class FakeSupabaseClient:
    def __init__(self):
        self.auth = FakeAuthNamespace()


# ---------------------------------------------------------------------------
# 1. Configuration & Secret Key Protection Tests
# ---------------------------------------------------------------------------


def test_load_supabase_config_valid_anon_jwt():
    anon_jwt = _make_fake_jwt(role="anon")
    cfg = load_supabase_config(
        url="https://exampleproj.supabase.co/",
        anon_key=anon_jwt,
        load_dotenv_file=False,
    )
    assert cfg.url == "https://exampleproj.supabase.co"
    assert cfg.anon_key == anon_jwt
    assert "[REDACTED]" in repr(cfg)
    assert anon_jwt not in repr(cfg)


def test_load_supabase_config_rejects_missing_or_placeholder(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)

    with pytest.raises(CloudConfigError, match="SUPABASE_URL is missing"):
        load_supabase_config(url="", anon_key=_make_fake_jwt("anon"), load_dotenv_file=False)

    with pytest.raises(CloudConfigError, match="placeholder"):
        load_supabase_config(
            url="https://your-project-id.supabase.co",
            anon_key=_make_fake_jwt("anon"),
            load_dotenv_file=False,
        )

    with pytest.raises(CloudConfigError, match="SUPABASE_ANON_KEY is missing"):
        load_supabase_config(
            url="https://exampleproj.supabase.co",
            anon_key="your-supabase-anon-public-key-here",
            load_dotenv_file=False,
        )


def test_load_supabase_config_rejects_service_role_and_secret_keys():
    service_jwt = _make_fake_jwt(role="service_role")
    with pytest.raises(CloudConfigError, match="Security violation.*service_role"):
        load_supabase_config(
            url="https://exampleproj.supabase.co",
            anon_key=service_jwt,
            load_dotenv_file=False,
        )

    with pytest.raises(CloudConfigError, match="Security violation.*sb_secret_"):
        load_supabase_config(
            url="https://exampleproj.supabase.co",
            anon_key="sb_secret_super_secret_server_key_123456",
            load_dotenv_file=False,
        )


# ---------------------------------------------------------------------------
# 2. Error Message Secret Sanitization Tests
# ---------------------------------------------------------------------------


def test_sanitize_error_message_redacts_tokens_and_passwords():
    jwt_token = _make_fake_jwt(role="authenticated")
    raw_msg = (
        f"Request failed with Authorization: Bearer {jwt_token} "
        f'and apikey=secret_key_9999999999999 and "password": "MySuperSecretPassword!23"'
    )
    sanitized = sanitize_error_message(raw_msg, extra_secrets=["CustomSecretValue"])
    assert jwt_token not in sanitized
    assert "secret_key_9999999999999" not in sanitized
    assert "MySuperSecretPassword!23" not in sanitized
    assert "[REDACTED_JWT]" in sanitized or "[REDACTED]" in sanitized
    assert "apikey=[REDACTED]" in sanitized


# ---------------------------------------------------------------------------
# 3. SupabaseAuthService Unit Tests
# ---------------------------------------------------------------------------


def test_auth_sign_in_persists_session_without_password(tmp_path):
    fake_client = FakeSupabaseClient()
    fake_client.auth.sign_in_response = SimpleNamespace(
        user=SimpleNamespace(id="11111111-2222-3333-4444-555555555555", email="alice@example.com"),
        session=SimpleNamespace(
            access_token="access_tok_abc",
            refresh_token="refresh_tok_xyz",
            expires_at=int(time.time()) + 3600,
        ),
    )
    session_file = str(tmp_path / "session.json")
    service = SupabaseAuthService(client=fake_client, session_file=session_file, persist_session=True)

    secret_pw = "CorrectHorseBatteryStaple99!"
    session = service.sign_in("alice@example.com", secret_pw)

    assert session.user_id == "11111111-2222-3333-4444-555555555555"
    assert session.email == "alice@example.com"
    assert "access_tok_abc" not in repr(session)
    assert os.path.exists(session_file)

    disk_content = (tmp_path / "session.json").read_text(encoding="utf-8")
    assert secret_pw not in disk_content
    parsed = json.loads(disk_content)
    assert parsed["user_id"] == "11111111-2222-3333-4444-555555555555"
    assert parsed["access_token"] == "access_tok_abc"


def test_auth_sign_in_invalid_credentials_and_redaction(tmp_path):
    fake_client = FakeSupabaseClient()
    secret_pw = "MyLeakedPassword123!"
    fake_client.auth.raise_on_call = RuntimeError(
        f"Invalid login credentials for password {secret_pw}"
    )
    service = SupabaseAuthService(
        client=fake_client,
        session_file=str(tmp_path / "session.json"),
        persist_session=True,
    )

    with pytest.raises(InvalidCredentialsError) as exc_info:
        service.sign_in("alice@example.com", secret_pw)

    assert secret_pw not in str(exc_info.value)
    assert "[REDACTED]" in str(exc_info.value)


def test_auth_restore_session_and_sign_out(tmp_path):
    session_file = str(tmp_path / "session.json")
    with open(session_file, "w", encoding="utf-8") as f:
        json.dump(
            {
                "user_id": "11111111-2222-3333-4444-555555555555",
                "email": "alice@example.com",
                "access_token": "old_access",
                "refresh_token": "old_refresh",
                "expires_at": int(time.time()) + 1800,
            },
            f,
        )

    fake_client = FakeSupabaseClient()
    fake_client.auth.set_session_response = SimpleNamespace(
        user=SimpleNamespace(id="11111111-2222-3333-4444-555555555555", email="alice@example.com"),
        session=SimpleNamespace(
            access_token="restored_access",
            refresh_token="restored_refresh",
            expires_at=int(time.time()) + 3600,
        ),
    )

    service = SupabaseAuthService(client=fake_client, session_file=session_file, persist_session=True)
    restored = service.restore_session()
    assert restored is not None
    assert restored.access_token == "restored_access"
    assert service.require_authenticated_session().user_id == "11111111-2222-3333-4444-555555555555"

    # Now sign out and verify disk token file is removed
    service.sign_out()
    assert service.current_session is None
    assert not os.path.exists(session_file)
    with pytest.raises(AuthenticationRequiredError):
        service.require_authenticated_session()


def test_auth_expired_session_refresh_and_failure(tmp_path):
    session_file = str(tmp_path / "session.json")
    fake_client = FakeSupabaseClient()
    # Sign in with an already-expired token timestamp
    fake_client.auth.sign_in_response = SimpleNamespace(
        user=SimpleNamespace(id="11111111-2222-3333-4444-555555555555", email="alice@example.com"),
        session=SimpleNamespace(
            access_token="expired_access",
            refresh_token="valid_refresh",
            expires_at=int(time.time()) - 10,
        ),
    )
    fake_client.auth.refresh_session_response = SimpleNamespace(
        user=SimpleNamespace(id="11111111-2222-3333-4444-555555555555", email="alice@example.com"),
        session=SimpleNamespace(
            access_token="fresh_access",
            refresh_token="fresh_refresh",
            expires_at=int(time.time()) + 3600,
        ),
    )

    service = SupabaseAuthService(client=fake_client, session_file=session_file, persist_session=True)
    service.sign_in("alice@example.com", "ValidPass123!")

    refreshed = service.require_authenticated_session()
    assert refreshed.access_token == "fresh_access"

    # Now simulate refresh token expiration/revocation
    service._current_session = AuthSessionInfo(
        user_id="11111111-2222-3333-4444-555555555555",
        email="alice@example.com",
        access_token="expired_access_2",
        refresh_token="revoked_refresh",
        expires_at=int(time.time()) - 10,
    )
    fake_client.auth.raise_on_call = RuntimeError("Invalid Refresh Token: Refresh Token Not Found")

    with pytest.raises(SessionExpiredError):
        service.require_authenticated_session()

    assert service.current_session is None
    assert not os.path.exists(session_file)


def test_auth_network_timeout_raises_cloud_network_error(tmp_path):
    fake_client = FakeSupabaseClient()
    fake_client.auth.raise_on_call = httpx.ConnectTimeout("Connection timed out to supabase.co")
    service = SupabaseAuthService(
        client=fake_client,
        session_file=str(tmp_path / "session.json"),
        persist_session=False,
    )

    with pytest.raises(CloudNetworkError, match="Network error"):
        service.sign_in("alice@example.com", "ValidPass123!")
