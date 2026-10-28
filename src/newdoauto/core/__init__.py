"""Core package for NewDoAuto."""

from newdoauto.core.state import (
    ExecutionStatus,
    ExecutionContext,
    CancellationToken,
    CancellationException,
    ActionTimeoutException,
)
from newdoauto.core.logger import StructuredLogger
from newdoauto.core.evaluator import evaluate_condition, interpolate_variables
from newdoauto.core.engine import AutomationEngine

__all__ = [
    "ExecutionStatus",
    "ExecutionContext",
    "CancellationToken",
    "CancellationException",
    "ActionTimeoutException",
    "StructuredLogger",
    "evaluate_condition",
    "interpolate_variables",
    "AutomationEngine",
]
