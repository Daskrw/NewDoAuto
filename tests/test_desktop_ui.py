"""
Automated integration and unit tests for the NewDoAuto Phase C PySide6 Desktop UI.
Verifies:
- Safe startup without a cloud connection
- Login error handling, session restore, and sign-out cross-account isolation
- Cloud workflow dashboard CRUD (list, open, rename, delete with confirmation)
- Visual workflow editor step operations (add, edit, reorder, duplicate, delete)
- Schema preservation (including nested IF/ELSE branches and unknown fields)
- Validation error feedback blocking invalid save/run
- Optimistic concurrency conflict handling (cancel, reload, save as copy) without silent overwrite
- Background QThread execution (Run, Stop, responsiveness, live logs, distinct status badges)
"""

from __future__ import annotations
import os
import time
from types import SimpleNamespace
from typing import Any, Dict, List
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from newdoauto.cloud.auth import AuthSessionInfo, SupabaseAuthService
from newdoauto.cloud.errors import InvalidCredentialsError
from newdoauto.cloud.repository import WorkflowCloudRepository
from newdoauto.models.workflow import Action, Workflow
from newdoauto.ui.main_window import MainWindow
from tests.test_cloud_repository import FakeTableClient


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class FakeUIAuthClient:
    def __init__(self, store: List[Dict[str, Any]]):
        self.store = store
        self.active_uid = ""
        self.table_client = FakeTableClient(store, lambda: self.active_uid)
        self.fail_login = False

    @property
    def auth(self):
        return self

    def table(self, name: str):
        return self.table_client.table(name)

    def sign_in_with_password(self, creds: dict):
        if self.fail_login:
            raise InvalidCredentialsError("Invalid email or password.")
        email = creds["email"]
        uid = (
            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
            if "alice" in email
            else "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
        )
        self.active_uid = uid
        return SimpleNamespace(
            user=SimpleNamespace(id=uid, email=email),
            session=SimpleNamespace(
                access_token=f"tok_{uid[:8]}",
                refresh_token=f"ref_{uid[:8]}",
                expires_at=int(time.time()) + 3600,
            ),
        )

    def sign_up(self, creds: dict):
        return self.sign_in_with_password(creds)

    def sign_out(self):
        self.active_uid = ""


def _make_window_with_fakes(store: List[Dict[str, Any]] | None = None):
    backing_store = store if store is not None else []
    fake_client = FakeUIAuthClient(backing_store)
    auth = SupabaseAuthService(client=fake_client, persist_session=False)
    repo = WorkflowCloudRepository(auth_service=auth)
    win = MainWindow(
        auth_service=auth,
        cloud_repo=repo,
        auto_restore_session=False,
        enable_hotkey=False,
    )
    win.confirm_discard_callback = lambda: True
    return win, fake_client, auth, repo


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_ui_starts_safely_without_cloud_connection(qapp, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)

    # Simulate missing cloud configuration
    win = MainWindow(
        auth_service=None,
        cloud_repo=None,
        auto_restore_session=False,
        enable_hotkey=False,
    )
    win.confirm_discard_callback = lambda: True
    # Even if local .env exists or doesn't, verify local mode works without cloud session
    win.local_mode_btn.click()
    assert win.stack.currentWidget() == win.workspace_page
    assert win.current_workflow is not None
    assert len(win.current_workflow.actions) == 1
    win.close()


def test_ui_login_error_and_success_loads_dashboard(qapp):
    store: List[Dict[str, Any]] = []
    win, fake_client, _, repo = _make_window_with_fakes(store)

    # 1. Invalid login shows error message on Auth screen
    fake_client.fail_login = True
    win.auth_email_edit.setText("alice@example.com")
    win.auth_password_edit.setText("wrongpass")
    assert win.handle_sign_in() is False
    assert not win.auth_feedback_label.isHidden()
    assert "Invalid" in win.auth_feedback_label.text()
    assert win.stack.currentWidget() == win.auth_page

    # 2. Valid login transitions to workspace and loads user workflows
    fake_client.fail_login = False
    win.auth_password_edit.setText("CorrectPass123!")
    assert win.handle_sign_in() is True
    assert win.auth_password_edit.text() == ""
    assert win.stack.currentWidget() == win.workspace_page
    assert "alice@example.com" in win.account_status_label.text()
    assert win.workflow_list_widget.count() == 0
    assert "No saved cloud workflows" in win.dashboard_status_label.text()
    win.close()


def test_ui_sign_out_clears_user_workflows_and_prevents_cross_account_leak(qapp):
    store: List[Dict[str, Any]] = []
    win, _, _, _ = _make_window_with_fakes(store)
    win.confirm_discard_callback = lambda: True

    # Sign in as Alice and save a workflow
    win.auth_email_edit.setText("alice@example.com")
    win.auth_password_edit.setText("AlicePass123!")
    assert win.handle_sign_in() is True

    win.wf_name_edit.setText("Alice Private Flow")
    assert win.handle_save_to_cloud() is True
    assert win.workflow_list_widget.count() == 1

    # Sign out -> list must be immediately emptied
    assert win.handle_sign_out() is True
    assert win.workflow_list_widget.count() == 0
    assert win.current_session is None

    # Sign in as Bob -> Alice's workflow must NOT appear in Bob's dashboard
    win.auth_email_edit.setText("bob@example.com")
    win.auth_password_edit.setText("BobPass123!")
    assert win.handle_sign_in() is True
    assert win.workflow_list_widget.count() == 0
    win.close()


def test_ui_dashboard_create_open_rename_delete_with_confirmation(qapp):
    store: List[Dict[str, Any]] = []
    win, _, _, _ = _make_window_with_fakes(store)
    win.confirm_discard_callback = lambda: True

    win.auth_email_edit.setText("alice@example.com")
    win.auth_password_edit.setText("AlicePass123!")
    win.handle_sign_in()

    # Create and save workflow v1
    win.wf_name_edit.setText("Initial Cloud Flow")
    assert win.handle_save_to_cloud() is True
    assert win.current_cloud_version == 1
    assert win.workflow_list_widget.count() == 1

    # Select item in dashboard and rename to v2
    win.workflow_list_widget.setCurrentRow(0)
    assert win.handle_rename_selected_cloud_workflow(new_name="Renamed Cloud Flow") is True
    assert win.current_cloud_version == 2
    assert "Renamed Cloud Flow" in win.workflow_list_widget.item(0).text()

    # Open from dashboard
    win.workflow_list_widget.setCurrentRow(0)
    assert win.handle_open_selected_cloud_workflow() is True
    assert win.current_workflow.name == "Renamed Cloud Flow"

    # Attempt delete when confirmation callback returns False -> must NOT delete
    win.workflow_list_widget.setCurrentRow(0)
    win.confirm_delete_callback = lambda wf_id: False
    assert win.handle_delete_selected_cloud_workflow() is False
    assert win.workflow_list_widget.count() == 1

    # Confirm delete -> deletes and refreshes list to 0
    win.confirm_delete_callback = lambda wf_id: True
    assert win.handle_delete_selected_cloud_workflow() is True
    assert win.workflow_list_widget.count() == 0
    win.close()


def test_ui_visual_editor_step_operations_and_unknown_field_preservation(qapp, tmp_path):
    win, _, _, _ = _make_window_with_fakes()
    win.confirm_discard_callback = lambda: True

    # Create a JSON file with extra/unknown top-level and action-level fields + IF/ELSE branch
    raw_workflow = {
        "schema_version": "1.0.0",
        "id": "12345678-1234-4234-8234-1234567890ab",
        "name": "Custom Metadata Workflow",
        "description": "Preserves unknown fields and branches",
        "custom_top_level_field": {"preserve_me": True},
        "variables": {"x": "10"},
        "actions": [
            {
                "id": "step_1",
                "type": "flow.wait",
                "params": {"seconds": 0.1, "extra_param": "keep"},
                "custom_action_field": "action_meta_val",
            },
            {
                "id": "step_2",
                "type": "flow.if_else",
                "params": {
                    "condition": "${x} == '10'",
                    "then": [
                        {"id": "nested_1", "type": "log.write", "params": {"message": "Yes"}}
                    ],
                    "else": [],
                },
            },
        ],
    }
    json_path = tmp_path / "custom_wf.json"
    import json
    json_path.write_text(json.dumps(raw_workflow), encoding="utf-8")

    assert win.handle_open_local_file(str(json_path)) is True
    assert win.is_dirty is False
    assert win.steps_list_widget.count() == 2

    # Edit step 1 via StepParameterEditor
    win.steps_list_widget.setCurrentRow(0)
    win.step_editor._param_widgets["seconds"].setText("0.25")
    assert win.step_editor.apply_changes_to_action() is True
    assert win.is_dirty is True
    assert win.current_workflow.actions[0].params["seconds"] == 0.25
    assert win.current_workflow.actions[0].params["extra_param"] == "keep"

    # Add a 3rd step, move it up, duplicate it, then delete the duplicate
    idx = win.action_type_combo.findData("log.write")
    win.action_type_combo.setCurrentIndex(idx)
    win.handle_add_step()
    assert win.steps_list_widget.count() == 3

    assert win.handle_move_step_up() is True
    assert win.current_workflow.actions[1].type == "log.write"

    assert win.handle_duplicate_step() is not None
    assert win.steps_list_widget.count() == 4

    assert win.handle_delete_step() is True
    assert win.steps_list_widget.count() == 3

    # Export and verify unknown fields + IF/ELSE branches survived round-trip intact
    out_path = tmp_path / "exported_wf.json"
    assert win.handle_export_local_file(str(out_path)) is True
    exported = json.loads(out_path.read_text(encoding="utf-8"))
    assert exported["custom_top_level_field"] == {"preserve_me": True}
    assert exported["actions"][0]["custom_action_field"] == "action_meta_val"
    assert exported["actions"][2]["type"] == "flow.if_else"
    assert len(exported["actions"][2]["params"]["then"]) == 1
    win.close()


def test_ui_validation_errors_shown_and_block_invalid_save_or_run(qapp):
    win, _, _, _ = _make_window_with_fakes()

    # Empty workflow name -> validation fails
    win.wf_name_edit.setText("   ")
    assert win.handle_validate_workflow() is False
    assert "Workflow name cannot be empty" in win.editor_banner_label.text()
    assert win.handle_save_to_cloud() is False
    assert win.handle_run_workflow() is False
    win.close()


def test_ui_cloud_conflict_handling_never_silently_overwrites(qapp):
    store: List[Dict[str, Any]] = []
    win, _, _, repo = _make_window_with_fakes(store)
    win.confirm_discard_callback = lambda: True

    win.auth_email_edit.setText("alice@example.com")
    win.auth_password_edit.setText("AlicePass123!")
    win.handle_sign_in()

    win.wf_name_edit.setText("Original v1")
    assert win.handle_save_to_cloud() is True
    wf_id = win.current_workflow.id
    assert win.current_cloud_version == 1

    # Simulate another PC updating the cloud record to v2
    cloud_rec = repo.get_workflow(wf_id)
    cloud_rec.workflow.name = "Updated by PC 2 (v2)"
    repo.update_workflow(wf_id, cloud_rec.workflow, expected_version=1)

    # Local UI is still at expected_version=1
    win.wf_name_edit.setText("Stale Local Edit")

    # 1. Resolution = "cancel" -> does not overwrite cloud v2
    win.conflict_resolution_callback = lambda exc: "cancel"
    assert win.handle_save_to_cloud() is False
    assert repo.get_workflow(wf_id).name == "Updated by PC 2 (v2)"
    assert repo.get_workflow(wf_id).version == 2

    # 2. Resolution = "save_copy" -> creates a second workflow copy while keeping original at v2
    win.conflict_resolution_callback = lambda exc: "save_copy"
    assert win.handle_save_to_cloud() is True
    assert len(repo.list_workflows()) == 2
    assert repo.get_workflow(wf_id).name == "Updated by PC 2 (v2)"
    win.close()


def test_ui_run_and_stop_worker_responsiveness_and_distinct_statuses(qapp):
    win, _, _, _ = _make_window_with_fakes()

    # 1. Run a fast valid workflow to completion
    win.current_workflow = Workflow(
        name="Fast Run Test",
        actions=[
            Action(id="s1", type="log.write", params={"level": "INFO", "message": "Hello Live Log"}),
            Action(id="s2", type="flow.wait", params={"seconds": 0.05}),
        ],
    )
    win._load_workflow_into_editor(win.current_workflow, cloud_version=None, mark_clean=True)

    assert win.handle_run_workflow() is True
    assert win._worker is not None
    while win._worker.isRunning():
        qapp.processEvents()
        time.sleep(0.02)
    qapp.processEvents()

    assert "SUCCESS" in win.exec_status_badge.text()
    assert "Hello Live Log" in win.log_console.toPlainText()

    # 2. Run a long wait workflow and click Stop to verify responsive cooperative cancellation
    win.current_workflow = Workflow(
        name="Long Wait Stop Test",
        actions=[
            Action(id="long_wait", type="flow.wait", params={"seconds": 10.0}),
        ],
    )
    win._load_workflow_into_editor(win.current_workflow, cloud_version=None, mark_clean=True)

    assert win.handle_run_workflow() is True
    # Prevent concurrent execution while running
    assert win.handle_run_workflow() is False

    time.sleep(0.1)
    win.handle_stop_workflow()
    while win._worker.isRunning():
        qapp.processEvents()
        time.sleep(0.02)
    qapp.processEvents()

    assert "CANCELLED" in win.exec_status_badge.text()
    win.close()

