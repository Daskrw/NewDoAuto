"""
Logging action handler for NewDoAuto.
"""

from typing import Any
from newdoauto.actions.base import ActionHandler
from newdoauto.core.evaluator import interpolate_variables
from newdoauto.core.logger import StructuredLogger
from newdoauto.core.state import ExecutionContext
from newdoauto.models.workflow import Action


class LogWriteHandler(ActionHandler):
    """Outputs a structured log message during workflow execution."""

    def execute(self, action: Action, context: ExecutionContext, logger: StructuredLogger) -> Any:
        context.cancellation_token.throw_if_cancelled()
        raw_msg = action.params["message"]
        level = action.params.get("level", "INFO").upper()
        message = str(interpolate_variables(raw_msg, context))

        if level == "ERROR":
            logger.error(message)
        elif level == "WARN":
            logger.warn(message)
        elif level == "DEBUG":
            logger.debug(message)
        else:
            logger.info(message)

        return {"level": level, "message": message}
