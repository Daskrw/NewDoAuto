"""
Main PySide6 Desktop Application Window for NewDoAuto (Phase C).
Integrates:
- Supabase Authentication (Login, Registration, Session Restore, Sign Out)
- Cloud Workflow Dashboard (List, Create, Open, Rename, Delete, Refresh)
- Visual Step-by-Step Workflow Editor (Add, Edit, Reorder, Duplicate, Delete, Validate)
- Background Automation Execution (Run, Stop, Ctrl+F12, Live Incremental Logs)
"""

from __future__ import annotations
import json
from typing import Any, Callable, Dict, List, Optional
import uuid

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from newdoauto.core.engine import AutomationEngine
from newdoauto.core.state import ExecutionContext
from newdoauto.actions.registry import ActionRegistry
from newdoauto.cloud.auth import AuthSessionInfo, SupabaseAuthService
from newdoauto.cloud.errors import (
    AuthenticationError,
    AuthenticationRequiredError,
    CloudConfigError,
    CloudError,
    CloudNetworkError,
    InvalidCredentialsError,
    SessionExpiredError,
    WorkflowConflictError,
)
from newdoauto.cloud.repository import CloudWorkflowRecord, WorkflowCloudRepository
from newdoauto.models.validation import ValidationError, validate_workflow
from newdoauto.models.workflow import Action, Workflow
from newdoauto.ui.action_forms import (
     ACTION_METADATA,
    StepParameterEditor,
    create_default_action,
    format_step_summary,
    get_supported_action_types,
)
from newdoauto.ui.worker import WorkflowExecutionWorker


class MainWindow(QMainWindow):
    """
    Primary Windows desktop interface for NewDoAuto.
    Calls existing Phase A and Phase B services without duplicating business logic.
    """

    def __init__(
        self,
        auth_service: Optional[SupabaseAuthService] = None,
        cloud_repo: Optional[WorkflowCloudRepository] = None,
        registry: Optional[ActionRegistry] = None,
        engine_factory: Optional[Callable[..., AutomationEngine]] = None,
        auto_restore_session: bool = True,
        enable_hotkey: bool = True,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("NewDoAuto — Personal Desktop Automation")
        self.resize(1280, 820)

        self.registry = registry or ActionRegistry()
        self.engine_factory = engine_factory or AutomationEngine
        self.enable_hotkey = enable_hotkey

        # Initialize cloud services safely (gracefully handles missing .env or offline startup)
        self.cloud_config_error: Optional[str] = None
        self.auth_service: Optional[SupabaseAuthService] = auth_service
        if self.auth_service is None:
            try:
                self.auth_service = SupabaseAuthService()
            except CloudConfigError as exc:
                self.cloud_config_error = str(exc)
            except Exception as exc:
                self.cloud_config_error = f"Cloud initialization warning: {exc}"

        self.cloud_repo: Optional[WorkflowCloudRepository] = cloud_repo
        if self.cloud_repo is None and self.auth_service is not None:
            self.cloud_repo = WorkflowCloudRepository(auth_service=self.auth_service)

        # State tracking
        self.current_workflow: Workflow = self._create_blank_workflow()
        self.current_cloud_version: Optional[int] = None
        self.cloud_workflows: List[CloudWorkflowRecord] = []
        self._is_dirty: bool = False
        self._updating_ui: bool = False
        self._worker: Optional[WorkflowExecutionWorker] = None

        # Injectable confirmation/resolution hooks for deterministic testing
        self.confirm_discard_callback: Optional[Callable[[], bool]] = None
        self.confirm_delete_callback: Optional[Callable[[str], bool]] = None
        self.conflict_resolution_callback: Optional[Callable[[WorkflowConflictError], str]] = None
        # Conflict resolution return values: "reload" | "save_copy" | "cancel"

        self._build_ui()
        self._load_workflow_into_editor(self.current_workflow, cloud_version=None, mark_clean=True)

        if auto_restore_session:
            self.try_restore_session_on_startup()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_dirty(self) -> bool:
        return self._is_dirty

    @property
    def is_running(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    @property
    def current_session(self) -> Optional[AuthSessionInfo]:
        if self.auth_service is None:
            return None
        return self.auth_service.current_session

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(6)

        # Top Account & Mode Bar
        top_bar = QHBoxLayout()
        self.app_title_label = QLabel("NewDoAuto Desktop")
        self.app_title_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        top_bar.addWidget(self.app_title_label)

        top_bar.addStretch()

        self.account_status_label = QLabel("Not signed in (Local Mode)")
        self.account_status_label.setStyleSheet("padding: 4px 8px; color: #444444;")
        top_bar.addWidget(self.account_status_label)

        self.toggle_auth_btn = QPushButton("Account / Sign In")
        self.toggle_auth_btn.clicked.connect(self._on_toggle_auth_view)
        top_bar.addWidget(self.toggle_auth_btn)

        self.sign_out_btn = QPushButton("Sign Out")
        self.sign_out_btn.setVisible(False)
        self.sign_out_btn.clicked.connect(self.handle_sign_out)
        top_bar.addWidget(self.sign_out_btn)

        root_layout.addLayout(top_bar)

        # Stacked Widget: Page 0 = Auth Screen, Page 1 = Main Workspace
        self.stack = QStackedWidget(self)
        root_layout.addWidget(self.stack, 1)

        self.auth_page = self._build_auth_page()
        self.workspace_page = self._build_workspace_page()

        self.stack.addWidget(self.auth_page)
        self.stack.addWidget(self.workspace_page)

        # Start on Auth page so user can sign in or click "Continue in Local Mode"
        self.stack.setCurrentWidget(self.auth_page)

    def _build_auth_page(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setAlignment(Qt.AlignCenter)

        card = QGroupBox("Supabase Cloud Account — Sign In or Create Account")
        card.setMinimumWidth(460)
        card.setMaximumWidth(540)
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(10)

        info = QLabel(
            "Sign in with your NewDoAuto Supabase account to access and synchronize "
            "your saved workflows across PCs, or continue in Local Mode."
        )
        info.setWordWrap(True)
        card_layout.addWidget(info)

        form = QFormLayout()
        self.auth_email_edit = QLineEdit()
        self.auth_email_edit.setPlaceholderText("you@example.com")
        self.auth_password_edit = QLineEdit()
        self.auth_password_edit.setEchoMode(QLineEdit.Password)
        self.auth_password_edit.setPlaceholderText("At least 6 characters")

        form.addRow("Email:", self.auth_email_edit)
        form.addRow("Password:", self.auth_password_edit)
        card_layout.addLayout(form)

        self.auth_feedback_label = QLabel("")
        self.auth_feedback_label.setWordWrap(True)
        self.auth_feedback_label.setVisible(False)
        card_layout.addWidget(self.auth_feedback_label)

        if self.cloud_config_error:
            self._set_auth_feedback(
                f"Cloud configuration notice: {self.cloud_config_error}. "
                "You can still use Local Mode to edit and run workflows.",
                is_error=True,
            )

        btn_row = QHBoxLayout()
        self.login_btn = QPushButton("Sign In")
        self.login_btn.setStyleSheet("font-weight: bold; padding: 6px 14px;")
        self.login_btn.clicked.connect(self.handle_sign_in)

        self.register_btn = QPushButton("Create Account")
        self.register_btn.setStyleSheet("padding: 6px 14px;")
        self.register_btn.clicked.connect(self.handle_sign_up)

        self.local_mode_btn = QPushButton("Continue to Editor (Local Mode)")
        self.local_mode_btn.setStyleSheet("padding: 6px 14px;")
        self.local_mode_btn.clicked.connect(lambda: self.stack.setCurrentWidget(self.workspace_page))

        btn_row.addWidget(self.login_btn)
        btn_row.addWidget(self.register_btn)
        btn_row.addWidget(self.local_mode_btn)
        card_layout.addLayout(btn_row)

        outer.addWidget(card)
        return page

    def _build_workspace_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)

        main_vertical_splitter = QSplitter(Qt.Vertical, page)
        layout.addWidget(main_vertical_splitter, 1)

        # Top horizontal splitter: Left Dashboard | Center Step Editor | Right Action Config
        top_splitter = QSplitter(Qt.Horizontal)
        main_vertical_splitter.addWidget(top_splitter)

        # 1. Left Panel: Cloud & Local Workflow Dashboard
        dashboard_group = QGroupBox("Workflow Dashboard")
        dash_layout = QVBoxLayout(dashboard_group)

        self.dashboard_status_label = QLabel("Sign in to view cloud workflows.")
        self.dashboard_status_label.setWordWrap(True)
        self.dashboard_status_label.setStyleSheet("color: #555555; font-size: 12px;")
        dash_layout.addWidget(self.dashboard_status_label)

        self.workflow_list_widget = QListWidget()
        self.workflow_list_widget.itemDoubleClicked.connect(lambda _: self.handle_open_selected_cloud_workflow())
        dash_layout.addWidget(self.workflow_list_widget, 1)

        dash_row1 = QHBoxLayout()
        self.new_wf_btn = QPushButton("+ New")
        self.new_wf_btn.clicked.connect(self.handle_new_workflow)
        self.open_cloud_wf_btn = QPushButton("Open")
        self.open_cloud_wf_btn.clicked.connect(self.handle_open_selected_cloud_workflow)
        self.refresh_cloud_btn = QPushButton("Refresh")
        self.refresh_cloud_btn.clicked.connect(self.refresh_cloud_workflows)
        dash_row1.addWidget(self.new_wf_btn)
        dash_row1.addWidget(self.open_cloud_wf_btn)
        dash_row1.addWidget(self.refresh_cloud_btn)
        dash_layout.addLayout(dash_row1)

        dash_row2 = QHBoxLayout()
        self.rename_cloud_wf_btn = QPushButton("Rename")
        self.rename_cloud_wf_btn.clicked.connect(self.handle_rename_selected_cloud_workflow)
        self.delete_cloud_wf_btn = QPushButton("Delete")
        self.delete_cloud_wf_btn.clicked.connect(self.handle_delete_selected_cloud_workflow)
        dash_row2.addWidget(self.rename_cloud_wf_btn)
        dash_row2.addWidget(self.delete_cloud_wf_btn)
        dash_layout.addLayout(dash_row2)

        dash_row3 = QHBoxLayout()
        self.open_local_btn = QPushButton("Open Local JSON...")
        self.open_local_btn.clicked.connect(self.handle_open_local_file)
        self.export_local_btn = QPushButton("Export JSON...")
        self.export_local_btn.clicked.connect(self.handle_export_local_file)
        dash_row3.addWidget(self.open_local_btn)
        dash_row3.addWidget(self.export_local_btn)
        dash_layout.addLayout(dash_row3)

        top_splitter.addWidget(dashboard_group)

        # 2. Center Panel: Visual Workflow Editor
        editor_group = QGroupBox("Visual Workflow Editor")
        editor_layout = QVBoxLayout(editor_group)

        # Workflow Metadata Header
        meta_header = QHBoxLayout()
        self.dirty_badge_label = QLabel("✓ Saved")
        self.dirty_badge_label.setStyleSheet("font-weight: bold; color: #1a7f37;")
        self.version_badge_label = QLabel("Local Draft")
        self.version_badge_label.setStyleSheet("color: #555555;")
        meta_header.addWidget(self.dirty_badge_label)
        meta_header.addSpacing(12)
        meta_header.addWidget(self.version_badge_label)
        meta_header.addStretch()

        self.validate_wf_btn = QPushButton("Validate Workflow")
        self.validate_wf_btn.clicked.connect(self.handle_validate_workflow)
        self.save_cloud_btn = QPushButton("Save to Cloud")
        self.save_cloud_btn.setStyleSheet("font-weight: bold; padding: 4px 12px;")
        self.save_cloud_btn.clicked.connect(self.handle_save_to_cloud)
        meta_header.addWidget(self.validate_wf_btn)
        meta_header.addWidget(self.save_cloud_btn)
        editor_layout.addLayout(meta_header)

        meta_form = QFormLayout()
        self.wf_name_edit = QLineEdit()
        self.wf_name_edit.textChanged.connect(self._on_workflow_metadata_edited)
        self.wf_desc_edit = QLineEdit()
        self.wf_desc_edit.setPlaceholderText("Optional description of what this workflow automates")
        self.wf_desc_edit.textChanged.connect(self._on_workflow_metadata_edited)
        self.wf_vars_edit = QLineEdit()
        self.wf_vars_edit.setPlaceholderText('Initial variables JSON object, e.g. {"my_var": "hello"}')
        self.wf_vars_edit.editingFinished.connect(self._on_workflow_variables_edited)

        meta_form.addRow("Workflow Name:", self.wf_name_edit)
        meta_form.addRow("Description:", self.wf_desc_edit)
        meta_form.addRow("Initial Variables (JSON):", self.wf_vars_edit)
        editor_layout.addLayout(meta_form)

        self.editor_banner_label = QLabel("")
        self.editor_banner_label.setWordWrap(True)
        self.editor_banner_label.setVisible(False)
        editor_layout.addWidget(self.editor_banner_label)

        # Add Step Toolbar
        add_step_bar = QHBoxLayout()
        self.action_type_combo = QComboBox()
        for act_type in get_supported_action_types(self.registry):
            meta = ACTION_METADATA.get(act_type, {})
            self.action_type_combo.addItem(meta.get("label", act_type), userData=act_type)
        add_step_bar.addWidget(QLabel("Action Type:"))
        add_step_bar.addWidget(self.action_type_combo, 1)

        self.add_step_btn = QPushButton("+ Add Step")
        self.add_step_btn.setStyleSheet("font-weight: bold;")
        self.add_step_btn.clicked.connect(self.handle_add_step)
        add_step_bar.addWidget(self.add_step_btn)
        editor_layout.addLayout(add_step_bar)

        # Step List Widget
        self.steps_list_widget = QListWidget()
        self.steps_list_widget.currentRowChanged.connect(self._on_selected_step_changed)
        editor_layout.addWidget(self.steps_list_widget, 1)

        # Step Manipulation Buttons (Reorder, Duplicate, Delete)
        step_ops_bar = QHBoxLayout()
        self.move_up_btn = QPushButton("▲ Move Up")
        self.move_up_btn.clicked.connect(self.handle_move_step_up)
        self.move_down_btn = QPushButton("▼ Move Down")
        self.move_down_btn.clicked.connect(self.handle_move_step_down)
        self.duplicate_step_btn = QPushButton("Duplicate Step")
        self.duplicate_step_btn.clicked.connect(self.handle_duplicate_step)
        self.delete_step_btn = QPushButton("Delete Step")
        self.delete_step_btn.clicked.connect(self.handle_delete_step)

        step_ops_bar.addWidget(self.move_up_btn)
        step_ops_bar.addWidget(self.move_down_btn)
        step_ops_bar.addWidget(self.duplicate_step_btn)
        step_ops_bar.addWidget(self.delete_step_btn)
        editor_layout.addLayout(step_ops_bar)

        top_splitter.addWidget(editor_group)

        # 3. Right Panel: Action Configuration Panel
        config_group = QGroupBox("Action Step Configuration")
        config_layout = QVBoxLayout(config_group)
        self.step_editor = StepParameterEditor(config_group)
        self.step_editor.step_modified.connect(self._on_step_modified)
        config_layout.addWidget(self.step_editor)
        top_splitter.addWidget(config_group)

        top_splitter.setStretchFactor(0, 2)
        top_splitter.setStretchFactor(1, 4)
        top_splitter.setStretchFactor(2, 3)

        # Bottom Panel: Execution Controls & Live Logs
        exec_group = QGroupBox("Execution Controls & Live Logs")
        exec_layout = QVBoxLayout(exec_group)

        exec_bar = QHBoxLayout()
        self.run_btn = QPushButton("▶ Run Workflow")
        self.run_btn.setStyleSheet(
            "font-weight: bold; background-color: #1f883d; color: white; padding: 6px 16px;"
        )
        self.run_btn.clicked.connect(self.handle_run_workflow)

        self.stop_btn = QPushButton("■ Stop (Ctrl+F12)")
        self.stop_btn.setStyleSheet(
            "font-weight: bold; background-color: #cf222e; color: white; padding: 6px 16px;"
        )
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.handle_stop_workflow)

        self.exec_status_badge = QLabel("STATUS: IDLE")
        self.exec_status_badge.setStyleSheet(
            "font-weight: bold; padding: 4px 10px; background-color: #eaeef2; border-radius: 4px;"
        )

        self.clear_logs_btn = QPushButton("Clear Logs")
        self.clear_logs_btn.clicked.connect(lambda: self.log_console.clear())

        exec_bar.addWidget(self.run_btn)
        exec_bar.addWidget(self.stop_btn)
        exec_bar.addSpacing(12)
        exec_bar.addWidget(self.exec_status_badge)
        exec_bar.addStretch()
        exec_bar.addWidget(self.clear_logs_btn)
        exec_layout.addLayout(exec_bar)

        self.log_console = QPlainTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setPlaceholderText(
            "Execution logs will appear here in real time when you click 'Run Workflow'."
        )
        self.log_console.setStyleSheet("font-family: Consolas, monospace; font-size: 12px;")
        exec_layout.addWidget(self.log_console, 1)

        main_vertical_splitter.addWidget(exec_group)
        main_vertical_splitter.setStretchFactor(0, 3)
        main_vertical_splitter.setStretchFactor(1, 1)

        return page

    # ------------------------------------------------------------------
    # Authentication Handlers
    # ------------------------------------------------------------------

    def try_restore_session_on_startup(self) -> bool:
        if self.auth_service is None:
            return False
        try:
            session = self.auth_service.restore_session()
            if session and session.access_token:
                self._on_authenticated(session)
                return True
        except SessionExpiredError as exc:
            self._set_auth_feedback(str(exc), is_error=True)
        except CloudNetworkError as exc:
            self._set_auth_feedback(str(exc), is_error=True)
        except Exception as exc:
            self._set_auth_feedback(f"Could not restore previous session: {exc}", is_error=True)
        return False

    def handle_sign_in(self) -> bool:
        if self.auth_service is None:
            self._set_auth_feedback(
                self.cloud_config_error or "Supabase configuration is not available.",
                is_error=True,
            )
            return False

        email = self.auth_email_edit.text().strip()
        password = self.auth_password_edit.text()

        try:
            session = self.auth_service.sign_in(email, password)
            self.auth_password_edit.clear()
            self._on_authenticated(session)
            return True
        except (InvalidCredentialsError, SessionExpiredError, CloudNetworkError, AuthenticationError, CloudError) as exc:
            self._set_auth_feedback(str(exc), is_error=True)
            return False
        except Exception as exc:
            self._set_auth_feedback(f"Sign-in error: {exc}", is_error=True)
            return False

    def handle_sign_up(self) -> bool:
        if self.auth_service is None:
            self._set_auth_feedback(
                self.cloud_config_error or "Supabase configuration is not available.",
                is_error=True,
            )
            return False

        email = self.auth_email_edit.text().strip()
        password = self.auth_password_edit.text()

        try:
            session = self.auth_service.sign_up(email, password)
            self.auth_password_edit.clear()
            if session.access_token:
                self._on_authenticated(session)
            else:
                self._set_auth_feedback(
                    f"Account created for {session.email}. Please check your email inbox "
                    "to confirm your address, then click Sign In.",
                    is_error=False,
                )
            return True
        except (InvalidCredentialsError, CloudNetworkError, AuthenticationError, CloudError) as exc:
            self._set_auth_feedback(str(exc), is_error=True)
            return False
        except Exception as exc:
            self._set_auth_feedback(f"Registration error: {exc}", is_error=True)
            return False

    def handle_sign_out(self) -> bool:
        if not self._check_can_discard_changes():
            return False

        if self.auth_service is not None:
            try:
                self.auth_service.sign_out()
            except Exception:
                pass

        # Immediately clear all user-specific cloud workflows and reset editor state
        self.cloud_workflows.clear()
        self.workflow_list_widget.clear()
        self.dashboard_status_label.setText("Signed out. Sign in to view cloud workflows.")
        self.account_status_label.setText("Not signed in (Local Mode)")
        self.sign_out_btn.setVisible(False)
        self.toggle_auth_btn.setText("Account / Sign In")

        self._load_workflow_into_editor(self._create_blank_workflow(), cloud_version=None, mark_clean=True)
        self._set_auth_feedback("You have been signed out.", is_error=False)
        self.stack.setCurrentWidget(self.auth_page)
        return True

    def _on_authenticated(self, session: AuthSessionInfo) -> None:
        self._set_auth_feedback(f"Signed in as {session.email}", is_error=False)
        self.account_status_label.setText(f"Signed in: {session.email}")
        self.sign_out_btn.setVisible(True)
        self.toggle_auth_btn.setText("Switch View")
        self.stack.setCurrentWidget(self.workspace_page)
        self.refresh_cloud_workflows()

    def _on_toggle_auth_view(self) -> None:
        if self.stack.currentWidget() == self.auth_page:
            self.stack.setCurrentWidget(self.workspace_page)
        else:
            self.stack.setCurrentWidget(self.auth_page)

    def _set_auth_feedback(self, message: str, is_error: bool = True) -> None:
        self.auth_feedback_label.setText(message)
        if is_error:
            self.auth_feedback_label.setStyleSheet(
                "color: #a40e26; background-color: #ffebe9; border: 1px solid #ff8182; padding: 8px;"
            )
        else:
            self.auth_feedback_label.setStyleSheet(
                "color: #1a7f37; background-color: #dafbe1; border: 1px solid #4ac26b; padding: 8px;"
            )
        self.auth_feedback_label.setVisible(True)

    # ------------------------------------------------------------------
    # Cloud Workflow Dashboard Handlers
    # ------------------------------------------------------------------

    def refresh_cloud_workflows(self) -> bool:
        """Loads the authenticated user's workflows from WorkflowCloudRepository."""
        self.workflow_list_widget.clear()
        self.cloud_workflows.clear()

        if self.cloud_repo is None or self.current_session is None:
            self.dashboard_status_label.setText("Not signed in. Using Local Mode.")
            return False

        self.dashboard_status_label.setText("Loading workflows from Supabase...")
        try:
            records = self.cloud_repo.list_workflows()
            self.cloud_workflows = records
            for rec in records:
                item = QListWidgetItem(f"{rec.name}  (v{rec.version})")
                item.setData(Qt.UserRole, rec.id)
                item.setToolTip(f"ID: {rec.id}\nUpdated: {rec.updated_at or 'N/A'}")
                self.workflow_list_widget.addItem(item)

            if not records:
                self.dashboard_status_label.setText("No saved cloud workflows yet.")
            else:
                self.dashboard_status_label.setText(f"Loaded {len(records)} cloud workflow(s).")
            return True
        except SessionExpiredError as exc:
            self.dashboard_status_label.setText(f"Session expired: {exc}")
            self.handle_sign_out()
            return False
        except CloudError as exc:
            self.dashboard_status_label.setText(f"Error loading workflows: {exc}")
            return False
        except Exception as exc:
            self.dashboard_status_label.setText(f"Unexpected error: {exc}")
            return False

    def handle_new_workflow(self) -> bool:
        if not self._check_can_discard_changes():
            return False
        wf = self._create_blank_workflow()
        self._load_workflow_into_editor(wf, cloud_version=None, mark_clean=True)
        self._show_editor_banner("Created new workflow draft.", is_error=False)
        return True

    def handle_open_selected_cloud_workflow(self) -> bool:
        item = self.workflow_list_widget.currentItem()
        if item is None or self.cloud_repo is None:
            self._show_editor_banner("Select a cloud workflow from the dashboard first.", is_error=True)
            return False

        if not self._check_can_discard_changes():
            return False

        wf_id = item.data(Qt.UserRole)
        try:
            record = self.cloud_repo.get_workflow(wf_id)
            self._load_workflow_into_editor(
                record.workflow.clone(),
                cloud_version=record.version,
                mark_clean=True,
            )
            self._show_editor_banner(
                f"Opened cloud workflow '{record.name}' (v{record.version}).",
                is_error=False,
            )
            return True
        except Exception as exc:
            self._show_editor_banner(f"Failed to load workflow: {exc}", is_error=True)
            return False

    def handle_rename_selected_cloud_workflow(self, new_name: Optional[str] = None) -> bool:
        item = self.workflow_list_widget.currentItem()
        if item is None or self.cloud_repo is None:
            self._show_editor_banner("Select a cloud workflow to rename.", is_error=True)
            return False

        wf_id = item.data(Qt.UserRole)
        try:
            record = self.cloud_repo.get_workflow(wf_id)
        except Exception as exc:
            self._show_editor_banner(f"Could not fetch workflow to rename: {exc}", is_error=True)
            return False

        if new_name is None:
            entered, ok = QInputDialog.getText(
                self,
                "Rename Workflow",
                "Enter new workflow name:",
                text=record.name,
            )
            if not ok or not entered.strip():
                return False
            new_name = entered.strip()

        record.workflow.name = new_name.strip()
        try:
            updated = self.cloud_repo.update_workflow(
                workflow_id=record.id,
                workflow=record.workflow,
                expected_version=record.version,
            )
            if self.current_workflow.id == updated.id:
                self._updating_ui = True
                self.current_workflow.name = updated.name
                self.wf_name_edit.setText(updated.name)
                self.current_cloud_version = updated.version
                self._update_badges()
                self._updating_ui = False
            self.refresh_cloud_workflows()
            self._show_editor_banner(f"Renamed workflow to '{updated.name}' (v{updated.version}).", is_error=False)
            return True
        except Exception as exc:
            self._show_editor_banner(f"Failed to rename workflow: {exc}", is_error=True)
            return False

    def handle_delete_selected_cloud_workflow(self) -> bool:
        item = self.workflow_list_widget.currentItem()
        if item is None or self.cloud_repo is None:
            self._show_editor_banner("Select a cloud workflow to delete.", is_error=True)
            return False

        wf_id = item.data(Qt.UserRole)
        wf_label = item.text()

        if self.confirm_delete_callback is not None:
            confirmed = self.confirm_delete_callback(wf_id)
        else:
            reply = QMessageBox.question(
                self,
                "Confirm Delete Workflow",
                f"Are you sure you want to permanently delete '{wf_label}' from Supabase?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            confirmed = reply == QMessageBox.Yes

        if not confirmed:
            return False

        try:
            self.cloud_repo.delete_workflow(wf_id)
            if self.current_workflow.id == wf_id:
                self.current_cloud_version = None
                self._mark_dirty(True)
            self.refresh_cloud_workflows()
            self._show_editor_banner(f"Deleted cloud workflow '{wf_label}'.", is_error=False)
            return True
        except Exception as exc:
            self._show_editor_banner(f"Failed to delete workflow: {exc}", is_error=True)
            return False

    def handle_save_to_cloud(self) -> bool:
        """
        Validates and saves the current workflow to Supabase via WorkflowCloudRepository.
        Handles optimistic concurrency conflicts (WorkflowConflictError) safely without
        silently overwriting newer cloud versions.
        """
        if not self._sync_metadata_and_validate():
            return False

        if self.cloud_repo is None or self.current_session is None:
            self._show_editor_banner(
                "Authentication required: Sign in to your Supabase account to save workflows to the cloud.",
                is_error=True,
            )
            return False

        try:
            if self.current_cloud_version is None:
                saved = self.cloud_repo.create_workflow(self.current_workflow)
            else:
                saved = self.cloud_repo.update_workflow(
                    workflow_id=self.current_workflow.id,
                    workflow=self.current_workflow,
                    expected_version=self.current_cloud_version,
                )

            self._load_workflow_into_editor(
                saved.workflow.clone(),
                cloud_version=saved.version,
                mark_clean=True,
            )
            self.refresh_cloud_workflows()
            self._show_editor_banner(
                f"Saved workflow '{saved.name}' to Supabase (v{saved.version}).",
                is_error=False,
            )
            return True

        except WorkflowConflictError as conflict_exc:
            return self._handle_cloud_conflict(conflict_exc)
        except (AuthenticationRequiredError, SessionExpiredError) as exc:
            self._show_editor_banner(str(exc), is_error=True)
            return False
        except Exception as exc:
            self._show_editor_banner(f"Cloud save failed: {exc}", is_error=True)
            return False

    def _handle_cloud_conflict(self, conflict_exc: WorkflowConflictError) -> bool:
        """
        Handles optimistic concurrency conflicts without ever overwriting newer cloud changes.
        Allows reloading the cloud version, saving local edits as a new workflow copy, or cancelling.
        """
        if self.conflict_resolution_callback is not None:
            choice = self.conflict_resolution_callback(conflict_exc)
        else:
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Warning)
            msg.setWindowTitle("Cloud Version Conflict Detected")
            msg.setText(str(conflict_exc))
            msg.setInformativeText(
                "Another PC or session saved a newer version of this workflow. "
                "How would you like to proceed?"
            )
            reload_btn = msg.addButton("Reload Cloud Version", QMessageBox.AcceptRole)
            copy_btn = msg.addButton("Save Local Edits as New Copy", QMessageBox.ActionRole)
            msg.addButton("Cancel (Keep Editing)", QMessageBox.RejectRole)
            msg.exec()
            clicked = msg.clickedButton()
            if clicked == reload_btn:
                choice = "reload"
            elif clicked == copy_btn:
                choice = "save_copy"
            else:
                choice = "cancel"

        if choice == "reload" and self.cloud_repo is not None:
            record = self.cloud_repo.get_workflow(self.current_workflow.id)
            self._load_workflow_into_editor(
                record.workflow.clone(),
                cloud_version=record.version,
                mark_clean=True,
            )
            self.refresh_cloud_workflows()
            self._show_editor_banner(
                f"Reloaded latest cloud version (v{record.version}).",
                is_error=False,
            )
            return True

        if choice == "save_copy" and self.cloud_repo is not None:
            self.current_workflow.id = str(uuid.uuid4())
            self.current_workflow.name = f"{self.current_workflow.name} (Copy)"
            saved = self.cloud_repo.create_workflow(self.current_workflow)
            self._load_workflow_into_editor(
                saved.workflow.clone(),
                cloud_version=saved.version,
                mark_clean=True,
            )
            self.refresh_cloud_workflows()
            self._show_editor_banner(
                f"Saved conflict copy as '{saved.name}' (v{saved.version}).",
                is_error=False,
            )
            return True

        self._show_editor_banner(
            f"Conflict unresolved: {conflict_exc}. Newer cloud changes were not overwritten.",
            is_error=True,
        )
        return False

    # ------------------------------------------------------------------
    # Local File Import / Export
    # ------------------------------------------------------------------

    def handle_open_local_file(self, filepath: Optional[str] = None) -> bool:
        if not self._check_can_discard_changes():
            return False

        if not filepath:
            filepath, _ = QFileDialog.getOpenFileName(
                self,
                "Open Workflow JSON File",
                "",
                "JSON Files (*.json);;All Files (*)",
            )
        if not filepath:
            return False

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            wf = Workflow.from_dict(data)
            validate_workflow(wf, known_types=set(self.registry._handlers.keys()))
            self._load_workflow_into_editor(wf, cloud_version=None, mark_clean=True)
            self._show_editor_banner(f"Loaded local workflow '{wf.name}'.", is_error=False)
            return True
        except Exception as exc:
            self._show_editor_banner(f"Failed to open workflow file: {exc}", is_error=True)
            return False

    def handle_export_local_file(self, filepath: Optional[str] = None) -> bool:
        if not self._sync_metadata_and_validate():
            return False

        if not filepath:
            filepath, _ = QFileDialog.getSaveFileName(
                self,
                "Export Workflow JSON File",
                f"{self.current_workflow.name.lower().replace(' ', '_')}.json",
                "JSON Files (*.json)",
            )
        if not filepath:
            return False

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(self.current_workflow.to_json(indent=2))
            self._show_editor_banner(f"Exported workflow to '{filepath}'.", is_error=False)
            return True
        except Exception as exc:
            self._show_editor_banner(f"Failed to export workflow: {exc}", is_error=True)
            return False

    # ------------------------------------------------------------------
    # Visual Workflow Step Editor Operations
    # ------------------------------------------------------------------

    def handle_add_step(self) -> Action:
        act_type = self.action_type_combo.currentData() or "flow.wait"
        new_act = create_default_action(act_type, step_number=len(self.current_workflow.actions) + 1)
        self.current_workflow.actions.append(new_act)
        self._refresh_steps_list(select_index=len(self.current_workflow.actions) - 1)
        self._mark_dirty(True)
        return new_act

    def handle_move_step_up(self) -> bool:
        row = self.steps_list_widget.currentRow()
        if row <= 0 or row >= len(self.current_workflow.actions):
            return False
        acts = self.current_workflow.actions
        acts[row - 1], acts[row] = acts[row], acts[row - 1]
        self._refresh_steps_list(select_index=row - 1)
        self._mark_dirty(True)
        return True

    def handle_move_step_down(self) -> bool:
        row = self.steps_list_widget.currentRow()
        acts = self.current_workflow.actions
        if row < 0 or row >= len(acts) - 1:
            return False
        acts[row + 1], acts[row] = acts[row], acts[row + 1]
        self._refresh_steps_list(select_index=row + 1)
        self._mark_dirty(True)
        return True

    def handle_duplicate_step(self) -> Optional[Action]:
        row = self.steps_list_widget.currentRow()
        acts = self.current_workflow.actions
        if row < 0 or row >= len(acts):
            return None
        source = acts[row]
        new_id = f"{source.id}_copy_{uuid.uuid4().hex[:4]}"
        cloned = source.clone(new_id=new_id)
        acts.insert(row + 1, cloned)
        self._refresh_steps_list(select_index=row + 1)
        self._mark_dirty(True)
        return cloned

    def handle_delete_step(self) -> bool:
        row = self.steps_list_widget.currentRow()
        acts = self.current_workflow.actions
        if row < 0 or row >= len(acts):
            return False
        acts.pop(row)
        next_sel = min(row, len(acts) - 1)
        self._refresh_steps_list(select_index=next_sel)
        self._mark_dirty(True)
        return True

    def handle_validate_workflow(self) -> bool:
        if self._sync_metadata_and_validate():
            self._show_editor_banner(
                f"Workflow '{self.current_workflow.name}' is VALID ({len(self.current_workflow.actions)} step(s)).",
                is_error=False,
            )
            return True
        return False

    # ------------------------------------------------------------------
    # Execution Controls (Run, Stop, Live Logs)
    # ------------------------------------------------------------------

    def handle_run_workflow(self) -> bool:
        """
        Validates and executes the current workflow in a background QThread worker
        using AutomationEngine. Prevents concurrent runs.
        """
        if self.is_running:
            self._show_editor_banner("A workflow is already running.", is_error=True)
            return False

        if not self._sync_metadata_and_validate():
            return False

        self.log_console.clear()
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self._set_execution_status_badge("RUNNING")

        self._worker = WorkflowExecutionWorker(
            workflow=self.current_workflow,
            registry=self.registry,
            engine_factory=self.engine_factory,
            cleanup_processes_on_finish=True,
            enable_hotkey=self.enable_hotkey,
            parent=self,
        )
        self._worker.log_emitted.connect(self._on_worker_log)
        self._worker.status_changed.connect(self._set_execution_status_badge)
        self._worker.execution_finished.connect(self._on_worker_finished)
        self._worker.start()
        return True

    def handle_stop_workflow(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.request_stop("Stopped by user from Desktop UI")

    def _on_worker_log(self, entry: Dict[str, Any]) -> None:
        ts = str(entry.get("timestamp", ""))[:19]
        lvl = str(entry.get("level", "INFO"))
        act = entry.get("action_id")
        msg = str(entry.get("message", ""))
        act_str = f" [{act}]" if act else ""
        self.log_console.appendPlainText(f"{ts} [{lvl:5s}]{act_str} {msg}")

    def _on_worker_finished(self, context: ExecutionContext, outcome: str) -> None:
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self._set_execution_status_badge(outcome.upper())

        if outcome == "completed":
            self._show_editor_banner("Workflow execution completed successfully.", is_error=False)
        elif outcome == "cancelled":
            self._show_editor_banner(f"Workflow cancelled: {context.error or 'Stopped by user'}", is_error=True)
        elif outcome == "timeout":
            self._show_editor_banner(f"Workflow timed out: {context.error}", is_error=True)
        else:
            self._show_editor_banner(f"Workflow failed: {context.error}", is_error=True)

    def _set_execution_status_badge(self, status_text: str) -> None:
        s = status_text.upper()
        if s == "RUNNING":
            style = "font-weight: bold; padding: 4px 10px; background-color: #ddf4ff; color: #0969da; border: 1px solid #54aeff;"
            label = "STATUS: RUNNING"
        elif s in ("COMPLETED", "SUCCESS"):
            style = "font-weight: bold; padding: 4px 10px; background-color: #dafbe1; color: #1a7f37; border: 1px solid #4ac26b;"
            label = "STATUS: SUCCESS (COMPLETED)"
        elif s == "TIMEOUT":
            style = "font-weight: bold; padding: 4px 10px; background-color: #fff8c5; color: #9a6700; border: 1px solid #d4a72c;"
            label = "STATUS: TIMEOUT"
        elif s == "CANCELLED":
            style = "font-weight: bold; padding: 4px 10px; background-color: #ffebe9; color: #cf222e; border: 1px solid #ff8182;"
            label = "STATUS: CANCELLED"
        elif s == "FAILED":
            style = "font-weight: bold; padding: 4px 10px; background-color: #ffebe9; color: #a40e26; border: 1px solid #ff8182;"
            label = "STATUS: FAILED"
        else:
            style = "font-weight: bold; padding: 4px 10px; background-color: #eaeef2; color: #444444;"
            label = f"STATUS: {s}"

        self.exec_status_badge.setText(label)
        self.exec_status_badge.setStyleSheet(style)

    # ------------------------------------------------------------------
    # Internal Helpers & State Sync
    # ------------------------------------------------------------------

    @staticmethod
    def _create_blank_workflow() -> Workflow:
        return Workflow(
            id=str(uuid.uuid4()),
            name="Untitled Workflow",
            schema_version="1.0.0",
            description="",
            variables={},
            actions=[create_default_action("flow.wait", step_number=1)],
        )

    def _load_workflow_into_editor(
        self,
        workflow: Workflow,
        cloud_version: Optional[int],
        mark_clean: bool = True,
    ) -> None:
        self._updating_ui = True
        self.current_workflow = workflow
        self.current_cloud_version = cloud_version

        self.wf_name_edit.setText(workflow.name)
        self.wf_desc_edit.setText(workflow.description or "")
        self.wf_vars_edit.setText(json.dumps(workflow.variables or {}))

        self._refresh_steps_list(select_index=0 if workflow.actions else -1)
        self._updating_ui = False
        self._mark_dirty(not mark_clean)

    def _refresh_steps_list(self, select_index: int = -1) -> None:
        self.steps_list_widget.blockSignals(True)
        self.steps_list_widget.clear()
        for idx, act in enumerate(self.current_workflow.actions, start=1):
            self.steps_list_widget.addItem(format_step_summary(idx, act))
        self.steps_list_widget.blockSignals(False)

        if 0 <= select_index < len(self.current_workflow.actions):
            self.steps_list_widget.setCurrentRow(select_index)
            self.step_editor.set_action(self.current_workflow.actions[select_index])
        else:
            self.step_editor.set_action(None)

    def _on_selected_step_changed(self, row: int) -> None:
        if 0 <= row < len(self.current_workflow.actions):
            self.step_editor.set_action(self.current_workflow.actions[row])
        else:
            self.step_editor.set_action(None)

    def _on_step_modified(self) -> None:
        row = self.steps_list_widget.currentRow()
        if 0 <= row < len(self.current_workflow.actions):
            item = self.steps_list_widget.item(row)
            if item is not None:
                item.setText(format_step_summary(row + 1, self.current_workflow.actions[row]))
        self._mark_dirty(True)

    def _on_workflow_metadata_edited(self) -> None:
        if self._updating_ui:
            return
        self.current_workflow.name = self.wf_name_edit.text()
        desc = self.wf_desc_edit.text().strip()
        self.current_workflow.description = desc if desc else None
        self._mark_dirty(True)

    def _on_workflow_variables_edited(self) -> None:
        if self._updating_ui:
            return
        raw = self.wf_vars_edit.text().strip()
        if not raw:
            self.current_workflow.variables = {}
            self._mark_dirty(True)
            return
        try:
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise ValueError("Initial variables must be a JSON object (e.g. {\"key\": \"val\"}).")
            self.current_workflow.variables = parsed
            self._mark_dirty(True)
        except Exception as exc:
            self._show_editor_banner(f"Invalid Initial Variables JSON: {exc}", is_error=True)

    def _sync_metadata_and_validate(self) -> bool:
        self.current_workflow.name = self.wf_name_edit.text().strip()
        desc = self.wf_desc_edit.text().strip()
        self.current_workflow.description = desc if desc else None

        raw_vars = self.wf_vars_edit.text().strip()
        if raw_vars:
            try:
                parsed_vars = json.loads(raw_vars)
                if not isinstance(parsed_vars, dict):
                    self._show_editor_banner("Initial Variables must be a JSON object.", is_error=True)
                    return False
                self.current_workflow.variables = parsed_vars
            except Exception as exc:
                self._show_editor_banner(f"Invalid Initial Variables JSON: {exc}", is_error=True)
                return False
        else:
            self.current_workflow.variables = {}

        if not self.current_workflow.actions:
            self._show_editor_banner("Workflow must contain at least one action step.", is_error=True)
            return False

        try:
            validate_workflow(
                self.current_workflow,
                known_types=set(self.registry._handlers.keys()),
            )
            return True
        except ValidationError as ve:
            self._show_editor_banner(str(ve), is_error=True)
            return False
        except Exception as exc:
            self._show_editor_banner(f"Validation error: {exc}", is_error=True)
            return False

    def _mark_dirty(self, dirty: bool) -> None:
        self._is_dirty = dirty
        self._update_badges()

    def _update_badges(self) -> None:
        if self._is_dirty:
            self.dirty_badge_label.setText("● Unsaved Changes")
            self.dirty_badge_label.setStyleSheet("font-weight: bold; color: #9a6700;")
            self.setWindowTitle(f"* {self.current_workflow.name} — NewDoAuto Desktop")
        else:
            self.dirty_badge_label.setText("✓ Saved")
            self.dirty_badge_label.setStyleSheet("font-weight: bold; color: #1a7f37;")
            self.setWindowTitle(f"{self.current_workflow.name} — NewDoAuto Desktop")

        if self.current_cloud_version is not None:
            self.version_badge_label.setText(f"Cloud Version: v{self.current_cloud_version}")
        else:
            self.version_badge_label.setText("Local Draft (Not yet saved to Cloud)")

    def _show_editor_banner(self, message: str, is_error: bool = False) -> None:
        self.editor_banner_label.setText(message)
        if is_error:
            self.editor_banner_label.setStyleSheet(
                "color: #a40e26; background-color: #ffebe9; border: 1px solid #ff8182; padding: 6px;"
            )
        else:
            self.editor_banner_label.setStyleSheet(
                "color: #1a7f37; background-color: #dafbe1; border: 1px solid #4ac26b; padding: 6px;"
            )
        self.editor_banner_label.setVisible(True)

    def _check_can_discard_changes(self) -> bool:
        if not self._is_dirty:
            return True
        if self.confirm_discard_callback is not None:
            return self.confirm_discard_callback()

        reply = QMessageBox.question(
            self,
            "Unsaved Changes",
            f"Workflow '{self.current_workflow.name}' has unsaved changes. Discard them?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return reply == QMessageBox.Yes

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._check_can_discard_changes():
            event.ignore()
            return
        if self.is_running and self._worker is not None:
            self._worker.request_stop("Application window closed")
            self._worker.wait(2000)
        event.accept()

