"""
Flow control actions (wait, conditional branching, variable assignment) for NewDoAuto.
"""

from typing import Any, Callable, Dict, List, Optional
import time
from newdoauto.actions.base import ActionHandler
from newdoauto.core.evaluator import evaluate_condition, interpolate_variables
from newdoauto.core.logger import StructuredLogger
from newdoauto.core.state import ExecutionContext
from newdoauto.models.workflow import Action


class FlowWaitHandler(ActionHandler):
    """Waits for a specified duration while cooperatively polling for cancellation."""

    def execute(self, action: Action, context: ExecutionContext, logger: StructuredLogger) -> Any:
        seconds = float(interpolate_variables(action.params["seconds"], context))
        logger.info(f"Waiting for {seconds:.2f} second(s)...")

        end_time = time.time() + seconds
        while time.time() < end_time:
            context.cancellation_token.throw_if_cancelled()
            time.sleep(min(0.1, end_time - time.time()))

        return {"waited_seconds": seconds}


class FlowSetVariableHandler(ActionHandler):
    """Sets or updates a variable in the workflow context."""

    def execute(self, action: Action, context: ExecutionContext, logger: StructuredLogger) -> Any:
        context.cancellation_token.throw_if_cancelled()
        name = action.params["name"]
        raw_val = action.params["value"]
        value = interpolate_variables(raw_val, context)

        context.set_variable(name, value)
        logger.info(f"Set variable '${{{name}}}' = {value!r}")
        return {"name": name, "value": value}


class FlowIfElseHandler(ActionHandler):
    """
    Evaluates a condition and executes either the 'then' or 'else' branch of actions.
    Uses a step executor callable injected at runtime.
    """

    def __init__(self, step_executor: Optional[Callable[[List[Action], ExecutionContext, StructuredLogger], None]] = None):
        self.step_executor = step_executor

    def set_step_executor(self, executor: Callable[[List[Action], ExecutionContext, StructuredLogger], None]):
        self.step_executor = executor

    def execute(self, action: Action, context: ExecutionContext, logger: StructuredLogger) -> Any:
        context.cancellation_token.throw_if_cancelled()
        condition = action.params["condition"]
        is_true = evaluate_condition(condition, context)

        branch_name = "then" if is_true else "else"
        logger.info(f"Condition '{condition}' evaluated to: {is_true} -> Executing '{branch_name}' branch")

        branch_actions_raw = action.params.get(branch_name, [])
        branch_actions = [
            Action.from_dict(act) if isinstance(act, dict) else act
            for act in branch_actions_raw
        ]

        if self.step_executor:
            self.step_executor(branch_actions, context, logger)
        else:
            logger.warn("Step executor not bound on FlowIfElseHandler; branch actions skipped.")

        return {
            "condition": condition,
            "evaluated": is_true,
            "branch_executed": branch_name,
            "action_count": len(branch_actions),
        }
