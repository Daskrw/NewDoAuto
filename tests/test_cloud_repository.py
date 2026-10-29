"""
Unit and mocked repository tests for WorkflowCloudRepository covering:
- Authenticated CRUD lifecycle (create, get, list, update, delete)
- Workflow JSON round-trip fidelity
- Optimistic concurrency conflict detection (WorkflowConflictError)
- Schema version & structural validation (UnsupportedSchemaVersionError, ValidationError)
- Network timeout handling (CloudNetworkError)
- Per-user ownership & RLS isolation semantics
"""

from __future__ import annotations
from datetime import datetime, timezone
import time
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
import httpx
import pytest

from newdoauto.cloud.auth import AuthSessionInfo, SupabaseAuthService
from newdoauto.cloud.errors import (
    AuthenticationRequiredError,
    CloudNetworkError,
    UnsupportedSchemaVersionError,
    WorkflowConflictError,
    WorkflowNotFoundError,
)
from newdoauto.cloud.repository import WorkflowCloudRepository
from newdoauto.models.validation import ValidationError
from newdoauto.models.workflow import Action, Workflow


class InMemoryPostgrestQueryBuilder:
    """
    Simulates Supabase PostgREST table query builder with PostgreSQL RLS
    enforcement for the active authenticated user.
    """

    def __init__(self, store: List[Dict[str, Any]], active_user_id_getter, raise_exc: Optional[Exception] = None):
        self._store = store
        self._get_uid = active_user_id_getter
        self._raise_exc = raise_exc
        self._op: str = "select"
        self._payload: Any = None
        self._filters: List[tuple[str, Any]] = []
        self._order_col: Optional[str] = None
        self._order_desc: bool = False

    def select(self, columns: str = "*"):
        self._op = "select"
        return self

    def insert(self, payload: Dict[str, Any]):
        self._op = "insert"
        self._payload = payload
        return self

    def update(self, payload: Dict[str, Any]):
        self._op = "update"
        self._payload = payload
        return self

    def delete(self):
        self._op = "delete"
        return self

    def eq(self, column: str, value: Any):
        self._filters.append((column, value))
        return self

    def order(self, column: str, desc: bool = False):
        self._order_col = column
        self._order_desc = desc
        return self

    def _matches(self, row: Dict[str, Any], uid: str) -> bool:
        # Enforce RLS: row is invisible unless row["owner_id"] == uid
        if row.get("owner_id") != uid:
            return False
        for col, val in self._filters:
            if row.get(col) != val:
                return False
        return True

    def execute(self):
        if self._raise_exc is not None:
            raise self._raise_exc

        uid = self._get_uid()
        now_iso = datetime.now(timezone.utc).isoformat()

        if self._op == "select":
            matched = [dict(r) for r in self._store if self._matches(r, uid)]
            if self._order_col:
                matched.sort(key=lambda r: r.get(self._order_col, ""), reverse=self._order_desc)
            return SimpleNamespace(data=matched)

        if self._op == "insert":
            row = dict(self._payload)
            # Enforce RLS WITH CHECK: owner_id must equal auth.uid()
            if row.get("owner_id") != uid:
                raise RuntimeError("new row violates row-level security policy for table \"workflows\"")
            row.setdefault("created_at", now_iso)
            row.setdefault("updated_at", now_iso)
            self._store.append(row)
            return SimpleNamespace(data=[dict(row)])

        if self._op == "update":
            updated_rows = []
            for row in self._store:
                if self._matches(row, uid):
                    if "owner_id" in self._payload and self._payload["owner_id"] != row["owner_id"]:
                        raise RuntimeError("Workflow owner_id is immutable and cannot be changed.")
                    row.update(self._payload)
                    row["updated_at"] = now_iso
                    updated_rows.append(dict(row))
            return SimpleNamespace(data=updated_rows)

        if self._op == "delete":
            deleted_rows = []
            remaining = []
            for row in self._store:
                if self._matches(row, uid):
                    deleted_rows.append(dict(row))
                else:
                    remaining.append(row)
            self._store[:] = remaining
            return SimpleNamespace(data=deleted_rows)

        raise ValueError(f"Unsupported operation: {self._op}")


class FakeTableClient:
    def __init__(self, store: List[Dict[str, Any]], active_user_id_getter):
        self.store = store
        self.active_user_id_getter = active_user_id_getter
        self.raise_exc: Optional[Exception] = None

    def table(self, name: str) -> InMemoryPostgrestQueryBuilder:
        assert name == "workflows"
        return InMemoryPostgrestQueryBuilder(
            self.store,
            self.active_user_id_getter,
            raise_exc=self.raise_exc,
        )


def _make_authenticated_repo(
    store: List[Dict[str, Any]],
    user_id: str = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    email: str = "user_a@example.com",
) -> tuple[WorkflowCloudRepository, FakeTableClient, SupabaseAuthService]:
    client = FakeTableClient(store, lambda: user_id)
    auth = SupabaseAuthService(client=client, persist_session=False)
    auth._current_session = AuthSessionInfo(
        user_id=user_id,
        email=email,
        access_token="valid_access_token",
        refresh_token="valid_refresh_token",
        expires_at=int(time.time()) + 3600,
    )
    repo = WorkflowCloudRepository(auth_service=auth)
    return repo, client, auth


def _sample_workflow(
    wf_id: str = "12345678-1234-4234-8234-1234567890ab",
    name: str = "Notepad Automation Flow",
) -> Workflow:
    return Workflow(
        id=wf_id,
        name=name,
        schema_version="1.0.0",
        description="Automated test workflow",
        variables={"greeting": "Hello Cloud"},
        actions=[
            Action(
                id="step_wait",
                type="flow.wait",
                description="Short Pause",
                params={"seconds": 0.1},
            ),
            Action(
                id="step_set_var",
                type="flow.set_variable",
                description="Update Var",
                params={"name": "greeting", "value": "Updated Value"},
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_repository_requires_authentication():
    store: List[Dict[str, Any]] = []
    client = FakeTableClient(store, lambda: "")
    auth = SupabaseAuthService(client=client, persist_session=False)
    repo = WorkflowCloudRepository(auth_service=auth)

    with pytest.raises(AuthenticationRequiredError):
        repo.list_workflows()

    with pytest.raises(AuthenticationRequiredError):
        repo.create_workflow(_sample_workflow())


def test_repository_crud_roundtrip_and_version_increment():
    store: List[Dict[str, Any]] = []
    repo, _, _ = _make_authenticated_repo(store)

    wf = _sample_workflow()
    created = repo.create_workflow(wf)
    assert created.id == wf.id
    assert created.version == 1
    assert created.name == "Notepad Automation Flow"
    assert created.workflow.variables["greeting"] == "Hello Cloud"
    assert len(created.workflow.actions) == 2

    # Get workflow by ID
    fetched = repo.get_workflow(wf.id)
    assert fetched.id == wf.id
    assert fetched.version == 1
    assert fetched.workflow.to_dict() == created.workflow.to_dict()

    # List workflows
    listed = repo.list_workflows()
    assert len(listed) == 1
    assert listed[0].id == wf.id

    # Update workflow with expected_version=1 -> version becomes 2
    wf.name = "Renamed Cloud Workflow"
    wf.variables["greeting"] = "Hello Version 2"
    updated = repo.update_workflow(wf.id, wf, expected_version=1)
    assert updated.version == 2
    assert updated.name == "Renamed Cloud Workflow"
    assert updated.workflow.variables["greeting"] == "Hello Version 2"

    # Delete workflow
    assert repo.delete_workflow(wf.id) is True
    assert repo.list_workflows() == []

    with pytest.raises(WorkflowNotFoundError):
        repo.get_workflow(wf.id)


def test_repository_optimistic_concurrency_conflict_detection():
    store: List[Dict[str, Any]] = []
    repo, _, _ = _make_authenticated_repo(store)

    wf = _sample_workflow()
    created = repo.create_workflow(wf)
    assert created.version == 1

    # Client 1 updates from v1 -> v2
    wf_v2 = _sample_workflow(name="Updated by PC 1")
    updated = repo.update_workflow(wf.id, wf_v2, expected_version=1)
    assert updated.version == 2

    # Client 2 (stale, still at expected_version=1) attempts to overwrite
    wf_stale = _sample_workflow(name="Stale Overwrite from PC 2")
    with pytest.raises(WorkflowConflictError) as exc_info:
        repo.update_workflow(wf.id, wf_stale, expected_version=1)

    assert exc_info.value.expected_version == 1
    assert exc_info.value.actual_version == 2

    # Confirm PC 1's version 2 was NOT overwritten
    current = repo.get_workflow(wf.id)
    assert current.version == 2
    assert current.name == "Updated by PC 1"


def test_repository_validates_schema_and_workflow_structure():
    store: List[Dict[str, Any]] = []
    repo, _, _ = _make_authenticated_repo(store)

    # Unsupported schema version
    bad_schema_wf = _sample_workflow()
    bad_schema_wf.schema_version = "99.0.0"
    with pytest.raises(UnsupportedSchemaVersionError):
        repo.create_workflow(bad_schema_wf)

    # Invalid workflow structure (unknown action type)
    invalid_wf = Workflow(
        id="12345678-1234-4234-8234-1234567890ab",
        name="Invalid Action Type",
        schema_version="1.0.0",
        actions=[Action(id="bad1", type="nonexistent.action", params={})],
    )
    with pytest.raises(ValidationError):
        repo.create_workflow(invalid_wf)


def test_repository_network_timeout_does_not_corrupt_state():
    store: List[Dict[str, Any]] = []
    repo, client, _ = _make_authenticated_repo(store)

    wf = _sample_workflow()
    repo.create_workflow(wf)

    # Simulate network timeout on update
    client.raise_exc = httpx.ReadTimeout("Read timed out while contacting Supabase PostgREST")
    with pytest.raises(CloudNetworkError, match="Network error"):
        repo.update_workflow(wf.id, wf, expected_version=1)

    # Restore network and verify original record is still intact at v1
    client.raise_exc = None
    record = repo.get_workflow(wf.id)
    assert record.version == 1


def test_repository_multi_user_rls_isolation():
    shared_store: List[Dict[str, Any]] = []
    repo_a, _, _ = _make_authenticated_repo(
        shared_store,
        user_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        email="user_a@example.com",
    )
    repo_b, _, _ = _make_authenticated_repo(
        shared_store,
        user_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        email="user_b@example.com",
    )

    wf_a = _sample_workflow(name="User A Private Workflow")
    created_a = repo_a.create_workflow(wf_a)

    # User B cannot see User A's workflow in list_workflows()
    assert repo_b.list_workflows() == []

    # User B cannot get User A's workflow by ID
    with pytest.raises(WorkflowNotFoundError):
        repo_b.get_workflow(created_a.id)

    # User B cannot update User A's workflow
    with pytest.raises(WorkflowNotFoundError):
        repo_b.update_workflow(created_a.id, wf_a, expected_version=1)

    # User B cannot delete User A's workflow
    with pytest.raises(WorkflowNotFoundError):
        repo_b.delete_workflow(created_a.id)

    # User A can still access their own workflow untouched
    assert repo_a.get_workflow(created_a.id).name == "User A Private Workflow"
