"""
Live Supabase integration and Row Level Security (RLS) verification tests.
Connects to the real Supabase project when SUPABASE_URL and SUPABASE_ANON_KEY are configured.
Never prints or logs secrets, tokens, or passwords.
"""

from __future__ import annotations
import os
import uuid
import pytest

from newdoauto.cloud.auth import SupabaseAuthService
from newdoauto.cloud.config import load_supabase_config
from newdoauto.cloud.errors import (
    CloudConfigError,
    InvalidCredentialsError,
    WorkflowConflictError,
    WorkflowNotFoundError,
)
from newdoauto.cloud.repository import WorkflowCloudRepository
from newdoauto.models.workflow import Action, Workflow


def _get_live_config_or_skip():
    try:
        return load_supabase_config()
    except CloudConfigError as exc:
        pytest.skip(f"Live Supabase configuration not available: {exc}")


def test_live_supabase_auth_rejects_invalid_credentials():
    """
    Verifies real network connectivity and authentication error handling against
    the live Supabase Auth endpoint (/auth/v1/token).
    """
    config = _get_live_config_or_skip()
    auth = SupabaseAuthService(config=config, persist_session=False)

    random_email = f"nonexistent_{uuid.uuid4().hex[:10]}@example.com"
    with pytest.raises(InvalidCredentialsError):
        auth.sign_in(random_email, "WrongPassword!987654")


def test_live_supabase_anon_table_protection():
    """
    Probes public.workflows on the live Supabase project using the unauthenticated anon client.
    - If the migration has been applied, verifies that anon cannot read any rows (42501 or empty []).
    - If the migration has not yet been applied in the Supabase SQL Editor (PGRST205), skips with exact status.
    """
    config = _get_live_config_or_skip()
    auth = SupabaseAuthService(config=config, persist_session=False)

    try:
        resp = auth.client.table("workflows").select("id").limit(1).execute()
        rows = getattr(resp, "data", None) or []
        assert rows == [], "Anonymous role must never be able to read rows from public.workflows"
    except Exception as exc:
        msg = str(exc)
        if "PGRST205" in msg or "Could not find the table 'public.workflows'" in msg:
            pytest.skip(
                "Remote table 'public.workflows' has not been created yet (PGRST205). "
                "Apply supabase/migrations/20261029000001_create_workflows_table.sql in the Supabase SQL Editor."
            )
        # Permission denied (42501) is the expected result because REVOKE ALL ON public.workflows FROM anon is in effect
        assert "42501" in msg or "permission denied" in msg.lower(), f"Unexpected error from live table probe: {msg}"


def test_live_supabase_two_user_rls_isolation():
    """
    End-to-end live RLS verification across two distinct Supabase Auth accounts (User A and User B).
    Requires:
      1. supabase/migrations/20261029000001_create_workflows_table.sql applied on the remote project.
      2. Either NEWDOAUTO_TEST_USER_A_EMAIL / PASSWORD and NEWDOAUTO_TEST_USER_B_EMAIL / PASSWORD set,
         or live sign-up with immediate session enabled on the project.
    """
    config = _get_live_config_or_skip()
    probe_auth = SupabaseAuthService(config=config, persist_session=False)

    # First check if public.workflows exists on the remote database
    try:
        probe_auth.client.table("workflows").select("id").limit(1).execute()
    except Exception as exc:
        msg = str(exc)
        if "PGRST205" in msg or "Could not find the table 'public.workflows'" in msg:
            pytest.skip(
                "Skipping live 2-user RLS test: remote table 'public.workflows' is not yet migrated (PGRST205). "
                "Run supabase/migrations/20261029000001_create_workflows_table.sql in Supabase SQL Editor first."
            )

    auth_a = SupabaseAuthService(config=config, persist_session=False)
    auth_b = SupabaseAuthService(config=config, persist_session=False)

    user_a_email = os.environ.get("NEWDOAUTO_TEST_USER_A_EMAIL", "").strip()
    user_a_pw = os.environ.get("NEWDOAUTO_TEST_USER_A_PASSWORD", "").strip()
    user_b_email = os.environ.get("NEWDOAUTO_TEST_USER_B_EMAIL", "").strip()
    user_b_pw = os.environ.get("NEWDOAUTO_TEST_USER_B_PASSWORD", "").strip()

    if user_a_email and user_a_pw and user_b_email and user_b_pw:
        session_a = auth_a.sign_in(user_a_email, user_a_pw)
        session_b = auth_b.sign_in(user_b_email, user_b_pw)
    else:
        pytest.skip(
            "Skipping live 2-user RLS test: set NEWDOAUTO_TEST_USER_A_EMAIL, NEWDOAUTO_TEST_USER_A_PASSWORD, "
            "NEWDOAUTO_TEST_USER_B_EMAIL, and NEWDOAUTO_TEST_USER_B_PASSWORD in .env to run live multi-user CRUD/RLS checks."
        )

    assert session_a.user_id != session_b.user_id

    repo_a = WorkflowCloudRepository(auth_service=auth_a)
    repo_b = WorkflowCloudRepository(auth_service=auth_b)

    wf = Workflow(
        id=str(uuid.uuid4()),
        name="Live RLS Verification Workflow",
        schema_version="1.0.0",
        description="Created during live RLS verification",
        actions=[Action(id="wait_1", type="flow.wait", params={"seconds": 0.1})],
    )

    created = repo_a.create_workflow(wf)
    try:
        assert created.version == 1
        assert created.owner_id == session_a.user_id

        # User A can read and update own workflow
        fetched_a = repo_a.get_workflow(created.id)
        assert fetched_a.id == created.id

        wf.name = "Live RLS Verification Workflow v2"
        updated_a = repo_a.update_workflow(created.id, wf, expected_version=1)
        assert updated_a.version == 2

        # Conflict check on live DB
        with pytest.raises(WorkflowConflictError):
            repo_a.update_workflow(created.id, wf, expected_version=1)

        # User B cannot read User A's workflow
        with pytest.raises(WorkflowNotFoundError):
            repo_b.get_workflow(created.id)

        # User B cannot update User A's workflow
        with pytest.raises(WorkflowNotFoundError):
            repo_b.update_workflow(created.id, wf, expected_version=2)

        # User B cannot delete User A's workflow
        with pytest.raises(WorkflowNotFoundError):
            repo_b.delete_workflow(created.id)

        # User B cannot insert a workflow spoofing User A's owner_id
        with pytest.raises(Exception):
            auth_b.client.table("workflows").insert(
                {
                    "id": str(uuid.uuid4()),
                    "owner_id": session_a.user_id,
                    "name": "Spoofed Owner Workflow",
                    "schema_version": "1.0.0",
                    "definition": wf.to_dict(),
                    "version": 1,
                }
            ).execute()
    finally:
        repo_a.delete_workflow(created.id)
        auth_a.sign_out()
        auth_b.sign_out()

