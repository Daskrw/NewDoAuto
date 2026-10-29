"""
Cloud Workflow Repository for NewDoAuto.
Provides authenticated CRUD operations against Supabase PostgreSQL (public.workflows)
with schema validation, optimistic concurrency conflict detection, and sanitized errors.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import uuid

import httpx

from newdoauto.cloud.auth import SupabaseAuthService
from newdoauto.cloud.errors import (
    CloudError,
    CloudNetworkError,
    UnsupportedSchemaVersionError,
    WorkflowConflictError,
    WorkflowNotFoundError,
    sanitize_error_message,
)
from newdoauto.models.validation import validate_workflow
from newdoauto.models.workflow import Workflow

SUPPORTED_SCHEMA_VERSIONS = {"1.0.0"}
WORKFLOWS_TABLE = "workflows"


def _ensure_valid_uuid(value: str, field_name: str = "workflow_id") -> str:
    """Validates that a string is a canonical UUID."""
    try:
        parsed = uuid.UUID(str(value))
        return str(parsed)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Invalid {field_name} '{value}': must be a valid UUID.") from exc


@dataclass(frozen=True)
class CloudWorkflowRecord:
    """Represents a versioned workflow record stored in Supabase PostgreSQL."""
    id: str
    owner_id: str
    name: str
    description: Optional[str]
    schema_version: str
    version: int
    workflow: Workflow
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class WorkflowCloudRepository:
    """
    Dedicated cloud persistence service for NewDoAuto workflows.
    Remains completely independent of the desktop UIA execution engine.
    """

    def __init__(self, auth_service: SupabaseAuthService, table_name: str = WORKFLOWS_TABLE):
        self.auth_service = auth_service
        self.table_name = table_name

    def list_workflows(self) -> List[CloudWorkflowRecord]:
        """
        Lists all workflows owned by the currently authenticated user,
        ordered by updated_at descending.
        """
        session = self.auth_service.require_authenticated_session()
        try:
            response = (
                self.auth_service.client.table(self.table_name)
                .select("*")
                .eq("owner_id", session.user_id)
                .order("updated_at", desc=True)
                .execute()
            )
        except Exception as exc:
            self._handle_repo_exception(exc)

        rows = getattr(response, "data", None) or []
        return [self._row_to_record(row) for row in rows]

    def get_workflow(self, workflow_id: str) -> CloudWorkflowRecord:
        """
        Retrieves a single workflow by UUID for the authenticated user.
        Raises WorkflowNotFoundError if missing or inaccessible under RLS.
        """
        session = self.auth_service.require_authenticated_session()
        clean_id = _ensure_valid_uuid(workflow_id)

        try:
            response = (
                self.auth_service.client.table(self.table_name)
                .select("*")
                .eq("id", clean_id)
                .eq("owner_id", session.user_id)
                .execute()
            )
        except Exception as exc:
            self._handle_repo_exception(exc)

        rows = getattr(response, "data", None) or []
        if not rows:
            raise WorkflowNotFoundError(clean_id)

        return self._row_to_record(rows[0])

    def create_workflow(self, workflow: Workflow) -> CloudWorkflowRecord:
        """
        Validates and inserts a new workflow owned by the authenticated user.
        Preserves workflow.id if it is already a valid UUID; otherwise assigns a new UUID.
        """
        session = self.auth_service.require_authenticated_session()
        self._validate_workflow_for_cloud(workflow)

        try:
            clean_id = _ensure_valid_uuid(workflow.id)
        except ValueError:
            clean_id = str(uuid.uuid4())
            workflow.id = clean_id

        definition_dict = workflow.to_dict()
        definition_dict["id"] = clean_id

        payload = {
            "id": clean_id,
            "owner_id": session.user_id,
            "name": workflow.name.strip(),
            "description": workflow.description,
            "schema_version": workflow.schema_version,
            "definition": definition_dict,
            "version": 1,
        }

        try:
            response = (
                self.auth_service.client.table(self.table_name)
                .insert(payload)
                .execute()
            )
        except Exception as exc:
            self._handle_repo_exception(exc)

        rows = getattr(response, "data", None) or []
        if not rows:
            raise CloudError("Failed to create workflow: server returned no record.")

        return self._row_to_record(rows[0])

    def update_workflow(
        self,
        workflow_id: str,
        workflow: Workflow,
        expected_version: int,
    ) -> CloudWorkflowRecord:
        """
        Updates an existing workflow using optimistic concurrency control.
        Requires expected_version to match the stored version in Supabase.
        Increments version by 1 on success, or raises WorkflowConflictError if stale.
        """
        session = self.auth_service.require_authenticated_session()
        clean_id = _ensure_valid_uuid(workflow_id)

        if not isinstance(expected_version, int) or expected_version < 1:
            raise ValueError(f"expected_version must be a positive integer, got {expected_version!r}")

        workflow.id = clean_id
        self._validate_workflow_for_cloud(workflow)
        definition_dict = workflow.to_dict()

        new_version = expected_version + 1
        update_payload = {
            "name": workflow.name.strip(),
            "description": workflow.description,
            "schema_version": workflow.schema_version,
            "definition": definition_dict,
            "version": new_version,
        }

        try:
            response = (
                self.auth_service.client.table(self.table_name)
                .update(update_payload)
                .eq("id", clean_id)
                .eq("owner_id", session.user_id)
                .eq("version", expected_version)
                .execute()
            )
        except Exception as exc:
            self._handle_repo_exception(exc)

        rows = getattr(response, "data", None) or []
        if rows:
            return self._row_to_record(rows[0])

        # Zero rows updated: distinguish between a version conflict vs. missing/inaccessible workflow
        existing = self._fetch_version_only(clean_id, session.user_id)
        if existing is not None:
            actual_version = existing.get("version")
            raise WorkflowConflictError(
                workflow_id=clean_id,
                expected_version=expected_version,
                actual_version=int(actual_version) if actual_version is not None else None,
            )

        raise WorkflowNotFoundError(clean_id)

    def delete_workflow(self, workflow_id: str) -> bool:
        """
        Deletes a workflow owned by the authenticated user.
        Raises WorkflowNotFoundError if the workflow does not exist or is not owned by the user.
        """
        session = self.auth_service.require_authenticated_session()
        clean_id = _ensure_valid_uuid(workflow_id)

        try:
            response = (
                self.auth_service.client.table(self.table_name)
                .delete()
                .eq("id", clean_id)
                .eq("owner_id", session.user_id)
                .execute()
            )
        except Exception as exc:
            self._handle_repo_exception(exc)

        rows = getattr(response, "data", None) or []
        if not rows:
            raise WorkflowNotFoundError(clean_id)
        return True

    def _fetch_version_only(self, workflow_id: str, owner_id: str) -> Optional[Dict[str, Any]]:
        try:
            response = (
                self.auth_service.client.table(self.table_name)
                .select("id, version")
                .eq("id", workflow_id)
                .eq("owner_id", owner_id)
                .execute()
            )
            rows = getattr(response, "data", None) or []
            return rows[0] if rows else None
        except Exception as exc:
            self._handle_repo_exception(exc)
            return None

    @staticmethod
    def _validate_workflow_for_cloud(workflow: Workflow) -> None:
        if workflow.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise UnsupportedSchemaVersionError(workflow.schema_version)
        validate_workflow(workflow)

    def _row_to_record(self, row: Dict[str, Any]) -> CloudWorkflowRecord:
        if not isinstance(row, dict):
            raise CloudError("Invalid workflow record format returned from cloud database.")

        schema_version = str(row.get("schema_version", "1.0.0"))
        if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise UnsupportedSchemaVersionError(schema_version)

        definition = row.get("definition")
        if not isinstance(definition, dict):
            raise CloudError(f"Workflow '{row.get('id')}' has malformed definition payload.")

        wf = Workflow.from_dict(definition)
        wf.id = str(row["id"])
        wf.name = str(row.get("name", wf.name))
        wf.schema_version = schema_version
        if row.get("description") is not None:
            wf.description = str(row["description"])

        validate_workflow(wf)

        return CloudWorkflowRecord(
            id=str(row["id"]),
            owner_id=str(row["owner_id"]),
            name=wf.name,
            description=wf.description,
            schema_version=schema_version,
            version=int(row.get("version", 1)),
            workflow=wf,
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )

    @staticmethod
    def _handle_repo_exception(exc: Exception) -> None:
        clean_msg = sanitize_error_message(str(exc))
        if isinstance(exc, (httpx.RequestError, httpx.TimeoutException, TimeoutError, ConnectionError)):
            raise CloudNetworkError(f"Network error during cloud workflow operation: {clean_msg}") from exc

        lower = clean_msg.lower()
        if any(k in lower for k in ("timed out", "timeout", "connection refused", "connecterror", "network")):
            raise CloudNetworkError(f"Network error during cloud workflow operation: {clean_msg}") from exc

        raise CloudError(f"Supabase workflow operation failed: {clean_msg}") from exc

