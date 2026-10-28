"""
Core execution engine for NewDoAuto.
Coordinates workflow parsing, action dispatch, error recovery, and process containment.
"""

from __future__ import annotations
import time
from typing import List, Optional
from newdoauto.actions.registry import ActionRegistry
from newdoauto.actions.flow_actions import FlowIfElseHandler
from newdoauto.core.logger import StructuredLogger
from newdoauto.core.state import (
    ActionTimeoutException,
    CancellationException,
    ExecutionContext,
    ExecutionStatus,
)
from newdoauto.models.workflow import Action, Workflow
from newdoauto.models.validation import validate_workflow


class AutomationEngine:
    """Orchestrates validation, scheduling, and execution of automation workflows."""

    def __init__(
        self,
        registry: Optional[ActionRegistry] = None,
        logger: Optional[StructuredLogger] = None,
        cleanup_processes_on_finish: bool = True,
    ):
        self.registry = registry or ActionRegistry()
        self.logger = logger or StructuredLogger()
        self.cleanup_processes_on_finish = cleanup_processes_on_finish

        # Bind this engine's step execution into FlowIfElseHandler
        if "flow.if_else" in self.registry._handlers:
            handler = self.registry.get("flow.if_else")
            if isinstance(handler, FlowIfElseHandler):
                handler.set_step_executor(self.execute_steps)

    def execute_workflow(
        self,
        workflow: Workflow,
        context: Optional[ExecutionContext] = None,
    ) -> ExecutionContext:
        """
        Executes a complete workflow from start to finish.
        Performs pre-validation, manages status transitions, and enforces error policies.
        """
        # 1. Pre-execution schema validation
        known_types = set(self.registry._handlers.keys())
        validate_workflow(workflow, known_types=known_types)

        # 2. Context setup
        if context is None:
            context = ExecutionContext()

        # Seed initial variables from workflow definition
        for k, v in workflow.variables.items():
            context.set_variable(k, v)

        self.logger.context = context
        context.status = ExecutionStatus.RUNNING
        context.started_at = time.time()
        self.logger.info(f"Starting workflow '{workflow.name}' ({len(workflow.actions)} root actions)")

        try:
            self.execute_steps(workflow.actions, context, self.logger)
            context.status = ExecutionStatus.COMPLETED
            self.logger.info(f"Workflow '{workflow.name}' completed successfully.")
        except CancellationException as ce:
            context.status = ExecutionStatus.CANCELLED
            context.error = str(ce)
            self.logger.warn(f"Workflow cancelled: {ce}")
        except Exception as e:
            context.status = ExecutionStatus.FAILED
            context.error = str(e)
            self.logger.error(f"Workflow execution failed: {e}")
        finally:
            context.finished_at = time.time()
            context.current_action_id = None
            if self.cleanup_processes_on_finish:
                context.cleanup_spawned_processes()

        return context

    def execute_steps(
        self,
        actions: List[Action],
        context: ExecutionContext,
        logger: StructuredLogger,
    ) -> None:
        """
        Executes a sequence of actions sequentially.
        Used for root workflow actions and nested branch blocks (e.g. inside IF/ELSE).
        """
        for action in actions:
            context.cancellation_token.throw_if_cancelled()
            context.current_action_id = action.id

            handler = self.registry.get(action.type)
            retries = 0
            max_retries = action.on_error.max_retries

            while True:
                context.cancellation_token.throw_if_cancelled()
                start_step = time.time()
                try:
                    result = handler.execute(action, context, logger)
                    context.set_action_result(action.id, result)
                    break  # Success, advance to next action
                except CancellationException:
                    raise
                except Exception as step_err:
                    elapsed = time.time() - start_step
                    if action.timeout_seconds and elapsed >= action.timeout_seconds:
                        step_err = ActionTimeoutException(
                            f"Action '{action.id}' timed out after {elapsed:.1f}s (limit: {action.timeout_seconds}s)"
                        )

                    logger.error(
                        f"Action '{action.id}' ({action.type}) failed: {step_err}",
                        action_id=action.id,
                        data={"error": str(step_err), "retry": retries},
                    )

                    if retries < max_retries and action.on_error.policy == "retry":
                        retries += 1
                        delay = action.on_error.retry_delay_seconds
                        logger.warn(f"Retrying action '{action.id}' ({retries}/{max_retries}) in {delay:.1f}s...")
                        time.sleep(delay)
                        continue

                    # Policy resolution
                    if action.on_error.policy == "continue":
                        logger.warn(f"Continuing past failed action '{action.id}' per on_error policy.")
                        context.set_action_result(action.id, {"error": str(step_err)})
                        break
                    else:
                        # Default is "stop"
                        raise step_err
