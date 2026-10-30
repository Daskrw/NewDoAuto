"""
Background Qt worker thread for executing NewDoAuto workflows without blocking the UI thread.
"""

from __future__ import annotations
import os
from typing import Any, Callable, Dict, Optional

from PySide6.QtCore import QThread, Signal

from newdoauto.core.engine import AutomationEngine
from newdoauto.core.logger import StructuredLogger
from newdoauto.core.state import ExecutionContext, ExecutionStatus
from newdoauto.actions.registry import ActionRegistry
from newdoauto.models.workflow import Workflow
from newdoauto.safety.emergency_stop import EmergencyStopListener


class WorkflowExecutionWorker(QThread):
    """
    Executes a Workflow in a dedicated background thread using AutomationEngine.
    Emits real-time log entries and distinct final status categories:
    - 'completed' (Success)
    - 'failed' (Error)
    - 'timeout' (Timeout)
    - 'cancelled' (Stopped by user or Ctrl+F12)
    """

    log_emitted = Signal(dict)
    status_changed = Signal(str)
    execution_finished = Signal(object, str)  # (ExecutionContext, outcome_category)

    def __init__(
        self,
        workflow: Workflow,
        registry: Optional[ActionRegistry] = None,
        engine_factory: Optional[Callable[..., AutomationEngine]] = None,
        cleanup_processes_on_finish: bool = True,
        enable_hotkey: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self.workflow = workflow.clone()
        self.registry = registry
        self.engine_factory = engine_factory or AutomationEngine
        self.cleanup_processes_on_finish = cleanup_processes_on_finish
        self.enable_hotkey = enable_hotkey
        self.context = ExecutionContext()

    def request_stop(self, reason: str = "Stopped by user from Desktop UI") -> None:
        """Signals cooperative cancellation to the running workflow."""
        self.context.cancellation_token.cancel(reason)

    def _on_log_entry(self, entry: Dict[str, Any]) -> None:
        self.log_emitted.emit(entry)

    def run(self) -> None:
        self.status_changed.emit("RUNNING")
        logger = StructuredLogger(
            context=self.context,
            quiet=True,
            on_log=self._on_log_entry,
        )
        engine = self.engine_factory(
            registry=self.registry,
            logger=logger,
            cleanup_processes_on_finish=self.cleanup_processes_on_finish,
        )

        hotkey_listener: Optional[EmergencyStopListener] = None
        if self.enable_hotkey and os.name == "nt":
            hotkey_listener = EmergencyStopListener(self.context.cancellation_token)
            hotkey_listener.start(logger=logger)

        try:
            engine.execute_workflow(self.workflow, context=self.context)
        finally:
            if hotkey_listener is not None:
                hotkey_listener.stop()

        outcome = self._determine_outcome(self.context)
        self.status_changed.emit(outcome.upper())
        self.execution_finished.emit(self.context, outcome)

    @staticmethod
    def _determine_outcome(ctx: ExecutionContext) -> str:
        if ctx.status == ExecutionStatus.COMPLETED:
            return "completed"
        if ctx.status == ExecutionStatus.CANCELLED or ctx.failure_category == "cancelled":
            return "cancelled"
        if ctx.failure_category == "timeout":
            return "timeout"
        if ctx.error and ("timed out" in ctx.error.lower() or "not found after" in ctx.error.lower()):
            return "timeout"
        return "failed"

