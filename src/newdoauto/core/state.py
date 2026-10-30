"""
Execution state, cancellation tokens, and context tracking for NewDoAuto.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
import threading
import time
from typing import Any, Dict, List, Optional
import subprocess


class ExecutionStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CancellationException(Exception):
    """Raised when an operation is aborted via cancellation token."""
    pass


class ActionTimeoutException(Exception):
    """Raised when an action exceeds its allotted timeout."""
    pass


class CancellationToken:
    """Thread-safe cooperative cancellation token."""
    def __init__(self):
        self._cancelled = threading.Event()
        self._reason: Optional[str] = None

    def cancel(self, reason: str = "User requested cancellation") -> None:
        self._reason = reason
        self._cancelled.set()

    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    @property
    def reason(self) -> Optional[str]:
        return self._reason

    def throw_if_cancelled(self) -> None:
        if self.is_cancelled():
            raise CancellationException(self._reason or "Execution cancelled")


@dataclass
class ExecutionContext:
    """Carries dynamic state, variables, owned processes, and cancellation during workflow execution."""
    variables: Dict[str, Any] = field(default_factory=dict)
    action_results: Dict[str, Any] = field(default_factory=dict)
    cancellation_token: CancellationToken = field(default_factory=CancellationToken)
    status: ExecutionStatus = ExecutionStatus.IDLE
    current_action_id: Optional[str] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    error: Optional[str] = None
    failure_category: Optional[str] = None
    spawned_processes: List[subprocess.Popen] = field(default_factory=list)
    logs: List[Dict[str, Any]] = field(default_factory=list)

    def track_process(self, proc: subprocess.Popen) -> None:
        """Track an external process spawned by NewDoAuto for safe cleanup."""
        self.spawned_processes.append(proc)

    def cleanup_spawned_processes(self) -> None:
        """Safely terminate any processes explicitly owned and spawned by this workflow session."""
        for proc in self.spawned_processes:
            try:
                if proc.poll() is None:
                    proc.terminate()
                    time.sleep(0.2)
                    if proc.poll() is None:
                        proc.kill()
            except Exception:
                pass
        self.spawned_processes.clear()

    def set_variable(self, name: str, value: Any) -> None:
        self.variables[name] = value

    def get_variable(self, name: str, default: Any = None) -> Any:
        return self.variables.get(name, default)

    def set_action_result(self, action_id: str, result: Any) -> None:
        self.action_results[action_id] = result
        self.variables["last_result"] = result
