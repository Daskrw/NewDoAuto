"""
Supabase configuration loader and security validator for NewDoAuto.
Ensures only publishable client keys are used and rejects privileged service_role keys.
"""

from __future__ import annotations
import base64
from dataclasses import dataclass
import json
import os
from typing import Optional

from newdoauto.cloud.errors import CloudConfigError

PLACEHOLDER_URLS = {
    "https://your-project-ref.supabase.co",
    "https://your-project-id.supabase.co",
    "your-supabase-url",
    "",
}

PLACEHOLDER_KEYS = {
    "your-supabase-publishable-anon-key",
    "your-supabase-anon-public-key-here",
    "your-anon-key",
    "",
}


def _extract_jwt_role(token: str) -> Optional[str]:
    """
    Inspects the unverified payload of a JWT to check its 'role' claim.
    Returns None if the token is not a standard 3-part JWT.
    """
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        payload_b64 = parts[1]
        # Pad base64url string
        padding = "=" * (-len(payload_b64) % 4)
        decoded = base64.urlsafe_b64decode(payload_b64 + padding).decode("utf-8")
        data = json.loads(decoded)
        if isinstance(data, dict):
            return data.get("role")
    except Exception:
        return None
    return None


@dataclass(frozen=True)
class SupabaseConfig:
    """Validated client-side configuration for Supabase."""
    url: str
    anon_key: str

    def __repr__(self) -> str:
        # Never print the anon_key in repr
        return f"SupabaseConfig(url={self.url!r}, anon_key='[REDACTED]')"


def load_supabase_config(
    url: Optional[str] = None,
    anon_key: Optional[str] = None,
    env_file: Optional[str] = None,
    load_dotenv_file: bool = True,
) -> SupabaseConfig:
    """
    Loads and validates Supabase configuration from parameters or environment variables.
    Automatically loads .env if python-dotenv is installed and load_dotenv_file is True.
    """
    if load_dotenv_file:
        try:
            from dotenv import load_dotenv
            load_dotenv(dotenv_path=env_file, override=False)
        except ImportError:
            pass

    resolved_url = (url if url is not None else os.environ.get("SUPABASE_URL", "")).strip()
    resolved_key = (anon_key if anon_key is not None else os.environ.get("SUPABASE_ANON_KEY", "")).strip()

    if not resolved_url or resolved_url in PLACEHOLDER_URLS:
        raise CloudConfigError(
            "SUPABASE_URL is missing or set to a placeholder. Configure SUPABASE_URL in your environment or .env file."
        )

    if not resolved_url.startswith("https://") and not resolved_url.startswith("http://localhost"):
        raise CloudConfigError(
            "Invalid SUPABASE_URL: must use https:// (or http://localhost for local testing)."
        )

    if not resolved_key or resolved_key in PLACEHOLDER_KEYS:
        raise CloudConfigError(
            "SUPABASE_ANON_KEY is missing or set to a placeholder. Configure SUPABASE_ANON_KEY with your publishable anon key."
        )

    # Security guard: refuse privileged service_role keys in the desktop client
    if resolved_key.startswith("sb_secret_"):
        raise CloudConfigError(
            "Security violation: A Supabase secret key ('sb_secret_...') was supplied as SUPABASE_ANON_KEY. "
            "Never use privileged secret keys in the desktop client; use the publishable/anon key with RLS."
        )

    role = _extract_jwt_role(resolved_key)
    if role == "service_role":
        raise CloudConfigError(
            "Security violation: A 'service_role' JWT was supplied as SUPABASE_ANON_KEY. "
            "Never use service_role keys in the desktop client; use the 'anon' publishable key with RLS."
        )

    return SupabaseConfig(url=resolved_url.rstrip("/"), anon_key=resolved_key)
