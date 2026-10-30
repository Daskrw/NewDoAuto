"""
Beginner-friendly action catalog metadata, step summary formatting,
and visual parameter configuration forms for NewDoAuto's supported actions.
"""

from __future__ import annotations
import copy
import json
from typing import Any, Dict, List, Optional
import uuid

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from newdoauto.core.engine import AutomationEngine  # noqa: F401
from newdoauto.actions.registry import ActionRegistry
from newdoauto.models.validation import validate_action
from newdoauto.models.workflow import Action, ErrorPolicy


# Human-friendly metadata for the 10 supported action types in ActionRegistry
ACTION_METADATA: Dict[str, Dict[str, Any]] = {
    "app.launch": {
        "label": "Launch Application (app.launch)",
        "short_label": "Launch App",
        "description": "Starts a Windows application executable and optionally tracks it for automatic cleanup.",
        "default_params": {
            "command": "notepad.exe",
            "wait_after_launch_seconds": 1.0,
            "track_process": True,
        },
    },
    "app.close": {
        "label": "Close Application (app.close)",
        "short_label": "Close App",
        "description": "Terminates a running application by process name (e.g. notepad.exe) or PID.",
        "default_params": {
            "process_name": "notepad.exe",
        },
    },
    "uia.find": {
        "label": "Find UI Element (uia.find)",
        "short_label": "Find UI Element",
        "description": "Locates a Windows UI Automation control and records its metadata.",
        "default_params": {
            "selector": {
                "window": {"ClassName": "Notepad"},
                "control": {"searchDepth": 4},
            }
        },
    },
    "uia.get_text": {
        "label": "Read Text from UI Element (uia.get_text)",
        "short_label": "Read UI Text",
        "description": "Reads text from a Windows UI control via ValuePattern, TextPattern, or Name.",
        "default_params": {
            "selector": {
                "window": {"ClassName": "Notepad"},
                "control": {"searchDepth": 4},
            }
        },
    },
    "uia.set_text": {
        "label": "Type / Set Text in UI Element (uia.set_text)",
        "short_label": "Set UI Text",
        "description": "Enters text into a Windows UI control using ValuePattern or simulated keystrokes.",
        "default_params": {
            "selector": {
                "window": {"ClassName": "Notepad"},
                "control": {"searchDepth": 4},
            },
            "text": "Hello from NewDoAuto",
            "mode": "auto",
        },
    },
    "uia.click": {
        "label": "Click UI Element (uia.click)",
        "short_label": "Click UI Element",
        "description": "Clicks a button or control via UI Automation InvokePattern or cursor click.",
        "default_params": {
            "selector": {
                "window": {"ClassName": "Notepad"},
                "control": {"Name": "File", "searchDepth": 4},
            },
            "mode": "auto",
        },
    },
    "flow.wait": {
        "label": "Wait / Pause (flow.wait)",
        "short_label": "Wait",
        "description": "Pauses workflow execution for a number of seconds while remaining responsive to Stop.",
        "default_params": {
            "seconds": 1.0,
        },
    },
    "flow.set_variable": {
        "label": "Set Variable (flow.set_variable)",
        "short_label": "Set Variable",
        "description": "Creates or updates a workflow variable (can reference ${other_var} or ${action_id}).",
        "default_params": {
            "name": "my_var",
            "value": "sample_value",
        },
    },
    "flow.if_else": {
        "label": "IF / ELSE Condition (flow.if_else)",
        "short_label": "IF / ELSE",
        "description": "Evaluates a condition and executes either the THEN branch or the ELSE branch.",
        "default_params": {
            "condition": "${my_var} == 'sample_value'",
            "then": [
                {
                    "id": "then_log_1",
                    "type": "log.write",
                    "params": {"level": "INFO", "message": "Condition matched (THEN branch)"},
                }
            ],
            "else": [
                {
                    "id": "else_log_1",
                    "type": "log.write",
                    "params": {"level": "INFO", "message": "Condition did not match (ELSE branch)"},
                }
            ],
        },
    },
    "log.write": {
        "label": "Write Log Message (log.write)",
        "short_label": "Write Log",
        "description": "Writes a formatted message to the execution log (supports ${variable} interpolation).",
        "default_params": {
            "level": "INFO",
            "message": "Step completed.",
        },
    },
}


def get_supported_action_types(registry: Optional[ActionRegistry] = None) -> List[str]:
    """Returns the ordered list of action types actually registered in the engine."""
    reg = registry or ActionRegistry()
    registered = set(reg._handlers.keys())
    ordered = [k for k in ACTION_METADATA.keys() if k in registered]
    for extra in sorted(registered - set(ordered)):
        ordered.append(extra)
    return ordered


def create_default_action(action_type: str, step_number: int = 1) -> Action:
    """Creates a valid default Action instance for the requested action_type."""
    meta = ACTION_METADATA.get(action_type, {})
    short_slug = action_type.replace(".", "_")
    unique_suffix = uuid.uuid4().hex[:4]
    return Action(
        id=f"step_{step_number}_{short_slug}_{unique_suffix}",
        type=action_type,
        description=meta.get("short_label", action_type),
        params=copy.deepcopy(meta.get("default_params", {})),
        timeout_seconds=10.0,
        on_error=ErrorPolicy(policy="stop", max_retries=0, retry_delay_seconds=1.0),
    )


def format_step_summary(index: int, action: Action) -> str:
    """Produces a concise, beginner-readable one-line summary of an Action step."""
    meta = ACTION_METADATA.get(action.type, {})
    short_label = meta.get("short_label", action.type)
    p = action.params or {}

    detail = ""
    if action.type == "app.launch":
        detail = f"cmd: {p.get('command', '')}"
    elif action.type == "app.close":
        detail = f"target: {p.get('process_name') or p.get('pid', '')}"
    elif action.type in ("uia.find", "uia.get_text", "uia.set_text", "uia.click"):
        sel = p.get("selector", {})
        if isinstance(sel, dict):
            w = sel.get("window", {})
            c = sel.get("control", {})
            w_str = w.get("ClassName") or w.get("Name") or w.get("AutomationId") or "*"
            c_str = (
                c.get("Name")
                or c.get("AutomationId")
                or c.get("ControlTypeName")
                or c.get("ClassName")
                or "auto"
            )
            detail = f"window={w_str}, ctrl={c_str}"
        else:
            detail = f"selector={sel}"
        if action.type == "uia.set_text":
            detail += f" <- {p.get('text', '')!r}"
    elif action.type == "flow.wait":
        detail = f"{p.get('seconds', 0)}s"
    elif action.type == "flow.set_variable":
        detail = f"${{{p.get('name', '')}}} = {p.get('value', '')!r}"
    elif action.type == "flow.if_else":
        cond = p.get("condition", "")
        then_cnt = len(p.get("then", []) or [])
        else_cnt = len(p.get("else", []) or [])
        detail = f"if ({cond}) [then: {then_cnt}, else: {else_cnt}]"
    elif action.type == "log.write":
        detail = f"{p.get('message', '')!r}"

    desc_part = f" — {action.description}" if action.description else ""
    detail_part = f"  [{detail}]" if detail else ""
    return f"{index}. [{short_label}] ({action.id}){desc_part}{detail_part}"


def format_if_else_branch_overview(action: Action) -> str:
    """Returns a readable multi-line summary of an IF/ELSE action's nested branches."""
    params = action.params or {}
    then_list = params.get("then", []) or []
    else_list = params.get("else", []) or []

    lines: List[str] = []
    lines.append(f"IF Condition: {params.get('condition', '')}")
    lines.append(f"  THEN Branch ({len(then_list)} step(s)):")
    if not then_list:
        lines.append("    (no actions)")
    for i, item in enumerate(then_list, start=1):
        act = Action.from_dict(item) if isinstance(item, dict) else item
        lines.append(f"    {format_step_summary(i, act)}")

    lines.append(f"  ELSE Branch ({len(else_list)} step(s)):")
    if not else_list:
        lines.append("    (no actions)")
    for i, item in enumerate(else_list, start=1):
        act = Action.from_dict(item) if isinstance(item, dict) else item
        lines.append(f"    {format_step_summary(i, act)}")

    return "\n".join(lines)


class StepParameterEditor(QWidget):
    """
    Visual configuration panel for editing the currently selected Action step.
    Preserves unknown/extra fields and validates nested IF/ELSE branches before saving.
    """

    step_modified = Signal()
    validation_error = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._current_action: Optional[Action] = None
        self._loading = False

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        outer_layout.addWidget(scroll)

        container = QWidget()
        scroll.setWidget(container)
        self.main_layout = QVBoxLayout(container)

        self.header_label = QLabel("Select a step to configure its settings.")
        self.header_label.setWordWrap(True)
        self.header_label.setStyleSheet("font-weight: bold; font-size: 13px; padding: 4px;")
        self.main_layout.addWidget(self.header_label)

        self.type_desc_label = QLabel("")
        self.type_desc_label.setWordWrap(True)
        self.type_desc_label.setStyleSheet("color: #555555; padding: 0 4px 6px 4px;")
        self.main_layout.addWidget(self.type_desc_label)

        # 1. Common Step Settings Group
        self.common_group = QGroupBox("Step Identity & Execution Policy")
        common_form = QFormLayout(self.common_group)

        self.id_edit = QLineEdit()
        self.desc_edit = QLineEdit()
        self.timeout_spin = QDoubleSpinBox()
        self.timeout_spin.setRange(0.1, 3600.0)
        self.timeout_spin.setSingleStep(1.0)
        self.timeout_spin.setSuffix(" s")

        self.error_policy_combo = QComboBox()
        self.error_policy_combo.addItems(["stop", "continue", "retry"])

        self.max_retries_spin = QSpinBox()
        self.max_retries_spin.setRange(0, 50)

        self.retry_delay_spin = QDoubleSpinBox()
        self.retry_delay_spin.setRange(0.1, 300.0)
        self.retry_delay_spin.setSingleStep(0.5)
        self.retry_delay_spin.setSuffix(" s")

        common_form.addRow("Step ID:", self.id_edit)
        common_form.addRow("Description:", self.desc_edit)
        common_form.addRow("Timeout:", self.timeout_spin)
        common_form.addRow("On Error Policy:", self.error_policy_combo)
        common_form.addRow("Max Retries:", self.max_retries_spin)
        common_form.addRow("Retry Delay:", self.retry_delay_spin)
        self.main_layout.addWidget(self.common_group)

        # 2. Action-Specific Parameter Group (dynamically populated)
        self.params_group = QGroupBox("Action Parameters")
        self.params_layout = QVBoxLayout(self.params_group)
        self.main_layout.addWidget(self.params_group)

        # Apply button + error feedback banner
        self.feedback_label = QLabel("")
        self.feedback_label.setWordWrap(True)
        self.feedback_label.setVisible(False)
        self.main_layout.addWidget(self.feedback_label)

        btn_row = QHBoxLayout()
        self.apply_btn = QPushButton("Apply Step Changes")
        self.apply_btn.setStyleSheet("font-weight: bold; padding: 6px 12px;")
        self.apply_btn.clicked.connect(self.apply_changes_to_action)
        btn_row.addWidget(self.apply_btn)
        btn_row.addStretch()
        self.main_layout.addLayout(btn_row)
        self.main_layout.addStretch()

        self._param_widgets: Dict[str, Any] = {}
        self.set_action(None)

    def set_action(self, action: Optional[Action]) -> None:
        """Loads an Action into the parameter editor without mutating it until applied."""
        self._loading = True
        self._current_action = action
        self.feedback_label.setVisible(False)

        if action is None:
            self.header_label.setText("No step selected.")
            self.type_desc_label.setText("Select a step from the workflow list or add a new step.")
            self.common_group.setEnabled(False)
            self.params_group.setEnabled(False)
            self.apply_btn.setEnabled(False)
            self._clear_params_layout()
            self._loading = False
            return

        self.common_group.setEnabled(True)
        self.params_group.setEnabled(True)
        self.apply_btn.setEnabled(True)

        meta = ACTION_METADATA.get(action.type, {})
        self.header_label.setText(meta.get("label", f"Action ({action.type})"))
        self.type_desc_label.setText(meta.get("description", ""))

        self.id_edit.setText(action.id)
        self.desc_edit.setText(action.description or "")
        self.timeout_spin.setValue(float(action.timeout_seconds))

        idx = self.error_policy_combo.findText(action.on_error.policy)
        self.error_policy_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.max_retries_spin.setValue(int(action.on_error.max_retries))
        self.retry_delay_spin.setValue(float(action.on_error.retry_delay_seconds))

        self._build_type_specific_fields(action)
        self._loading = False

    def _clear_params_layout(self) -> None:
        self._param_widgets.clear()
        while self.params_layout.count():
            item = self.params_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
            elif item.layout() is not None:
                self._clear_sublayout(item.layout())

    def _clear_sublayout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_sublayout(item.layout())

    def _build_type_specific_fields(self, action: Action) -> None:
        self._clear_params_layout()
        form = QFormLayout()
        self.params_layout.addLayout(form)
        p = action.params or {}
        t = action.type

        if t == "app.launch":
            cmd_edit = QLineEdit(str(p.get("command", "")))
            args_val = p.get("args", [])
            args_str = json.dumps(args_val) if args_val else ""
            args_edit = QLineEdit(args_str)
            args_edit.setPlaceholderText('Optional JSON list, e.g. ["file.txt"]')

            wait_spin = QDoubleSpinBox()
            wait_spin.setRange(0.0, 120.0)
            wait_spin.setSingleStep(0.5)
            wait_spin.setValue(float(p.get("wait_after_launch_seconds", 1.0)))

            track_chk = QCheckBox("Track process for automatic cleanup on finish")
            track_chk.setChecked(bool(p.get("track_process", True)))

            form.addRow("Executable / Command:", cmd_edit)
            form.addRow("Arguments (JSON list):", args_edit)
            form.addRow("Wait After Launch (s):", wait_spin)
            form.addRow("", track_chk)

            self._param_widgets["command"] = cmd_edit
            self._param_widgets["args"] = args_edit
            self._param_widgets["wait_after_launch_seconds"] = wait_spin
            self._param_widgets["track_process"] = track_chk

        elif t == "app.close":
            proc_name_edit = QLineEdit(str(p.get("process_name", "")))
            proc_name_edit.setPlaceholderText("e.g. notepad.exe")
            pid_edit = QLineEdit(str(p.get("pid", "") if p.get("pid") is not None else ""))
            pid_edit.setPlaceholderText("Optional numeric PID or ${var}")
            form.addRow("Process Name:", proc_name_edit)
            form.addRow("Or Process PID:", pid_edit)
            self._param_widgets["process_name"] = proc_name_edit
            self._param_widgets["pid"] = pid_edit

        elif t in ("uia.find", "uia.get_text", "uia.set_text", "uia.click"):
            self._build_selector_fields(form, p.get("selector", {}))
            if t == "uia.set_text":
                text_edit = QLineEdit(str(p.get("text", "")))
                mode_combo = QComboBox()
                mode_combo.addItems(["auto", "value_pattern", "send_keys"])
                cur_mode = str(p.get("mode", "auto"))
                idx = mode_combo.findText(cur_mode)
                mode_combo.setCurrentIndex(idx if idx >= 0 else 0)
                form.addRow("Text to Enter:", text_edit)
                form.addRow("Input Mode:", mode_combo)
                self._param_widgets["text"] = text_edit
                self._param_widgets["mode"] = mode_combo
            elif t == "uia.click":
                mode_combo = QComboBox()
                mode_combo.addItems(["auto", "invoke", "click"])
                cur_mode = str(p.get("mode", "auto"))
                idx = mode_combo.findText(cur_mode)
                mode_combo.setCurrentIndex(idx if idx >= 0 else 0)
                form.addRow("Click Mode:", mode_combo)
                self._param_widgets["mode"] = mode_combo

        elif t == "flow.wait":
            sec_edit = QLineEdit(str(p.get("seconds", 1.0)))
            sec_edit.setPlaceholderText("Seconds (e.g. 1.5 or ${wait_var})")
            form.addRow("Wait Duration (seconds):", sec_edit)
            self._param_widgets["seconds"] = sec_edit

        elif t == "flow.set_variable":
            name_edit = QLineEdit(str(p.get("name", "")))
            val_edit = QLineEdit(str(p.get("value", "")))
            form.addRow("Variable Name:", name_edit)
            form.addRow("Variable Value:", val_edit)
            self._param_widgets["name"] = name_edit
            self._param_widgets["value"] = val_edit

        elif t == "log.write":
            level_combo = QComboBox()
            level_combo.addItems(["INFO", "WARN", "ERROR", "DEBUG"])
            cur_lvl = str(p.get("level", "INFO")).upper()
            idx = level_combo.findText(cur_lvl)
            level_combo.setCurrentIndex(idx if idx >= 0 else 0)
            msg_edit = QLineEdit(str(p.get("message", "")))
            form.addRow("Log Level:", level_combo)
            form.addRow("Log Message:", msg_edit)
            self._param_widgets["level"] = level_combo
            self._param_widgets["message"] = msg_edit

        elif t == "flow.if_else":
            cond_val = p.get("condition", "")
            cond_str = json.dumps(cond_val) if isinstance(cond_val, dict) else str(cond_val)
            cond_edit = QLineEdit(cond_str)
            cond_edit.setPlaceholderText("e.g. ${observed_text} == 'NewDoAuto_POC_2026'")
            form.addRow("Condition Expression:", cond_edit)
            self._param_widgets["condition"] = cond_edit

            overview_label = QLabel(format_if_else_branch_overview(action))
            overview_label.setWordWrap(True)
            overview_label.setStyleSheet(
                "background-color: #f4f6f8; border: 1px solid #d0d7de; "
                "padding: 6px; font-family: Consolas, monospace; font-size: 11px;"
            )
            self.params_layout.addWidget(QLabel("Branch Structure Overview:"))
            self.params_layout.addWidget(overview_label)
            self._param_widgets["branch_overview_label"] = overview_label

            then_edit = QPlainTextEdit(json.dumps(p.get("then", []), indent=2))
            then_edit.setMaximumHeight(130)
            else_edit = QPlainTextEdit(json.dumps(p.get("else", []), indent=2))
            else_edit.setMaximumHeight(130)

            self.params_layout.addWidget(QLabel("THEN Branch Actions (JSON List):"))
            self.params_layout.addWidget(then_edit)
            self.params_layout.addWidget(QLabel("ELSE Branch Actions (JSON List):"))
            self.params_layout.addWidget(else_edit)

            self._param_widgets["then_json"] = then_edit
            self._param_widgets["else_json"] = else_edit

    def _build_selector_fields(self, form: QFormLayout, selector: Any) -> None:
        win_spec: Dict[str, Any] = {}
        ctrl_spec: Dict[str, Any] = {}
        if isinstance(selector, str):
            win_spec = {"ClassName": selector}
        elif isinstance(selector, dict):
            w_raw = selector.get("window", {})
            win_spec = {"ClassName": w_raw} if isinstance(w_raw, str) else dict(w_raw or {})
            ctrl_spec = dict(selector.get("control", {}) or {})

        w_class = QLineEdit(str(win_spec.get("ClassName", "")))
        w_class.setPlaceholderText("e.g. Notepad")
        w_name = QLineEdit(str(win_spec.get("Name", "")))
        w_name.setPlaceholderText("Optional window title")
        w_aid = QLineEdit(str(win_spec.get("AutomationId", "")))

        c_type = QLineEdit(str(ctrl_spec.get("ControlTypeName", "")))
        c_type.setPlaceholderText("Leave blank to auto-detect Document/Edit, or e.g. ButtonControl")
        c_class = QLineEdit(str(ctrl_spec.get("ClassName", "")))
        c_name = QLineEdit(str(ctrl_spec.get("Name", "")))
        c_aid = QLineEdit(str(ctrl_spec.get("AutomationId", "")))
        c_depth = QSpinBox()
        c_depth.setRange(1, 25)
        c_depth.setValue(int(ctrl_spec.get("searchDepth", 4)))

        form.addRow("Window ClassName:", w_class)
        form.addRow("Window Name (Title):", w_name)
        form.addRow("Window AutomationId:", w_aid)
        form.addRow("Control Type:", c_type)
        form.addRow("Control ClassName:", c_class)
        form.addRow("Control Name:", c_name)
        form.addRow("Control AutomationId:", c_aid)
        form.addRow("Control Search Depth:", c_depth)

        self._param_widgets["sel_w_class"] = w_class
        self._param_widgets["sel_w_name"] = w_name
        self._param_widgets["sel_w_aid"] = w_aid
        self._param_widgets["sel_c_type"] = c_type
        self._param_widgets["sel_c_class"] = c_class
        self._param_widgets["sel_c_name"] = c_name
        self._param_widgets["sel_c_aid"] = c_aid
        self._param_widgets["sel_c_depth"] = c_depth

    def apply_changes_to_action(self) -> bool:
        """
        Validates form inputs and writes them back to the bound Action object.
        Preserves any extra/unknown keys in action.params.
        Returns True if valid and applied, or False if validation failed.
        """
        if self._current_action is None or self._loading:
            return False

        action = self._current_action
        new_id = self.id_edit.text().strip()
        if not new_id:
            self._show_error("Step ID cannot be empty.")
            return False

        new_params = copy.deepcopy(action.params or {})
        t = action.type

        try:
            if t == "app.launch":
                cmd = self._param_widgets["command"].text().strip()
                if not cmd:
                    raise ValueError("Executable / Command is required for app.launch.")
                new_params["command"] = cmd
                args_text = self._param_widgets["args"].text().strip()
                if args_text:
                    parsed_args = json.loads(args_text)
                    if not isinstance(parsed_args, list):
                        raise ValueError("Arguments must be a JSON list (e.g. [\"arg1\"]).")
                    new_params["args"] = parsed_args
                elif "args" in new_params:
                    del new_params["args"]
                new_params["wait_after_launch_seconds"] = float(
                    self._param_widgets["wait_after_launch_seconds"].value()
                )
                new_params["track_process"] = bool(self._param_widgets["track_process"].isChecked())

            elif t == "app.close":
                pname = self._param_widgets["process_name"].text().strip()
                pid_txt = self._param_widgets["pid"].text().strip()
                if not pname and not pid_txt:
                    raise ValueError("Either Process Name or Process PID is required for app.close.")
                if pname:
                    new_params["process_name"] = pname
                elif "process_name" in new_params:
                    del new_params["process_name"]
                if pid_txt:
                    new_params["pid"] = int(pid_txt) if pid_txt.isdigit() else pid_txt
                elif "pid" in new_params:
                    del new_params["pid"]

            elif t in ("uia.find", "uia.get_text", "uia.set_text", "uia.click"):
                existing_sel = new_params.get("selector")
                new_params["selector"] = self._collect_selector_dict(existing_sel)
                if t == "uia.set_text":
                    new_params["text"] = self._param_widgets["text"].text()
                    new_params["mode"] = self._param_widgets["mode"].currentText()
                elif t == "uia.click":
                    new_params["mode"] = self._param_widgets["mode"].currentText()

            elif t == "flow.wait":
                sec_raw = self._param_widgets["seconds"].text().strip()
                if not sec_raw:
                    raise ValueError("Wait duration is required.")
                try:
                    new_params["seconds"] = float(sec_raw)
                except ValueError:
                    new_params["seconds"] = sec_raw

            elif t == "flow.set_variable":
                vname = self._param_widgets["name"].text().strip()
                if not vname:
                    raise ValueError("Variable Name cannot be empty.")
                new_params["name"] = vname
                new_params["value"] = self._param_widgets["value"].text()

            elif t == "log.write":
                new_params["level"] = self._param_widgets["level"].currentText()
                new_params["message"] = self._param_widgets["message"].text()

            elif t == "flow.if_else":
                cond_txt = self._param_widgets["condition"].text().strip()
                if not cond_txt:
                    raise ValueError("Condition expression is required for flow.if_else.")
                if cond_txt.startswith("{") and cond_txt.endswith("}"):
                    new_params["condition"] = json.loads(cond_txt)
                else:
                    new_params["condition"] = cond_txt

                then_raw = json.loads(self._param_widgets["then_json"].toPlainText() or "[]")
                else_raw = json.loads(self._param_widgets["else_json"].toPlainText() or "[]")
                if not isinstance(then_raw, list) or not isinstance(else_raw, list):
                    raise ValueError("THEN and ELSE branches must each be a JSON list of action objects.")
                new_params["then"] = then_raw
                new_params["else"] = else_raw

            # Validate candidate action using existing validation module
            candidate = Action(
                id=new_id,
                type=action.type,
                params=new_params,
                timeout_seconds=float(self.timeout_spin.value()),
                on_error=ErrorPolicy(
                    policy=self.error_policy_combo.currentText(),
                    max_retries=int(self.max_retries_spin.value()),
                    retry_delay_seconds=float(self.retry_delay_spin.value()),
                    extra_fields=copy.deepcopy(action.on_error.extra_fields),
                ),
                description=self.desc_edit.text().strip() or None,
                extra_fields=copy.deepcopy(action.extra_fields),
            )
            errs = validate_action(candidate)
            if errs:
                raise ValueError("\n".join(errs))

        except Exception as exc:
            self._show_error(str(exc))
            return False

        # Commit validated changes to the action instance
        action.id = candidate.id
        action.description = candidate.description
        action.timeout_seconds = candidate.timeout_seconds
        action.on_error = candidate.on_error
        action.params = candidate.params

        if t == "flow.if_else" and "branch_overview_label" in self._param_widgets:
            self._param_widgets["branch_overview_label"].setText(format_if_else_branch_overview(action))

        self._show_success("Step changes applied.")
        self.step_modified.emit()
        return True

    def _collect_selector_dict(self, existing_selector: Any) -> Dict[str, Any]:
        base_sel: Dict[str, Any] = (
            copy.deepcopy(existing_selector) if isinstance(existing_selector, dict) else {}
        )
        win_dict: Dict[str, Any] = (
            copy.deepcopy(base_sel.get("window")) if isinstance(base_sel.get("window"), dict) else {}
        )
        ctrl_dict: Dict[str, Any] = (
            copy.deepcopy(base_sel.get("control")) if isinstance(base_sel.get("control"), dict) else {}
        )

        def set_or_pop(d: Dict[str, Any], key: str, val: str):
            if val:
                d[key] = val
            elif key in d:
                del d[key]

        set_or_pop(win_dict, "ClassName", self._param_widgets["sel_w_class"].text().strip())
        set_or_pop(win_dict, "Name", self._param_widgets["sel_w_name"].text().strip())
        set_or_pop(win_dict, "AutomationId", self._param_widgets["sel_w_aid"].text().strip())

        if not win_dict:
            raise ValueError(
                "At least one Window selector field (ClassName, Name, or AutomationId) is required."
            )

        set_or_pop(ctrl_dict, "ControlTypeName", self._param_widgets["sel_c_type"].text().strip())
        set_or_pop(ctrl_dict, "ClassName", self._param_widgets["sel_c_class"].text().strip())
        set_or_pop(ctrl_dict, "Name", self._param_widgets["sel_c_name"].text().strip())
        set_or_pop(ctrl_dict, "AutomationId", self._param_widgets["sel_c_aid"].text().strip())
        ctrl_dict["searchDepth"] = int(self._param_widgets["sel_c_depth"].value())

        base_sel["window"] = win_dict
        base_sel["control"] = ctrl_dict
        return base_sel

    def _show_error(self, msg: str) -> None:
        self.feedback_label.setText(f"Validation Error: {msg}")
        self.feedback_label.setStyleSheet(
            "color: #a40e26; background-color: #ffebe9; border: 1px solid #ff8182; padding: 6px;"
        )
        self.feedback_label.setVisible(True)
        self.validation_error.emit(msg)

    def _show_success(self, msg: str) -> None:
        self.feedback_label.setText(msg)
        self.feedback_label.setStyleSheet(
            "color: #1a7f37; background-color: #dafbe1; border: 1px solid #4ac26b; padding: 6px;"
        )
        self.feedback_label.setVisible(True)

