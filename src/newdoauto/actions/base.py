"""
Base action handler interface for NewDoAuto.
"""

from abc import ABC, abstractmethod
from typing import Any
from newdoauto.core.logger import StructuredLogger
from newdoauto.core.state import ExecutionContext
from newdoauto.models.workflow import Action


class ActionHandler(ABC):
    """Abstract base class for all automation action handlers."""

    @abstractmethod
    def execute(self, action: Action, context: ExecutionContext, logger: StructuredLogger) -> Any:
        """
        Executes the action logic.
        Must check context.cancellation_token.throw_if_cancelled() where appropriate.
        Returns any action output result that can be referenced by downstream actions.
        """
        pass
