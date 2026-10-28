"""
Unit tests for execution engine cancellation, timeouts, and error handling policies.
"""

import time
import pytest
from newdoauto.core.engine import AutomationEngine
from newdoauto.core.logger import StructuredLogger
from newdoauto.core.state import (
    ActionTimeoutException,
    CancellationException,
    ExecutionContext,
    ExecutionStatus,
)
from newdoauto.models.workflow import Workflow, Action, ErrorPolicy
from newdoauto.actions.base import ActionHandler


class SlowMockHandler(ActionHandler):
    """Mock handler that sleeps to test timeout or cancellation."""
    def execute(self, action: Action, context: ExecutionContext, logger: StructuredLogger):
        sleep_dur = float(action.params.get("sleep", 1.0))
        end = time.time() + sleep_dur
        while time.time() < end:
            context.cancellation_token.throw_if_cancelled()
            time.sleep(0.05)
        return {"slept": sleep_dur}


class FlakyMockHandler(ActionHandler):
    """Mock handler that fails a specified number of times before succeeding."""
    def __init__(self, fail_count: int = 2):
        self.fail_count = fail_count
        self.attempts = 0

    def execute(self, action: Action, context: ExecutionContext, logger: StructuredLogger):
        self.attempts += 1
        if self.attempts <= self.fail_count:
            raise RuntimeError(f"Simulated failure attempt {self.attempts}")
        return {"status": "success", "attempts": self.attempts}


def test_cooperative_cancellation():
    logger = StructuredLogger(quiet=True)
    engine = AutomationEngine(logger=logger)
    engine.registry.register("test.slow", SlowMockHandler())

    wf = Workflow(
        name="Cancellation Test",
        actions=[
            Action(id="act-slow-1", type="test.slow", params={"sleep": 0.1}),
            Action(id="act-slow-2", type="test.slow", params={"sleep": 2.0}),
            Action(id="act-unreached", type="log.write", params={"message": "never"}),
        ],
    )

    ctx = ExecutionContext()
    # Trigger cancellation in a background timer after 0.2s
    import threading
    timer = threading.Timer(0.2, lambda: ctx.cancellation_token.cancel("User cancelled test"))
    timer.start()

    res_ctx = engine.execute_workflow(wf, context=ctx)
    timer.cancel()

    assert res_ctx.status == ExecutionStatus.CANCELLED
    assert "User cancelled test" in (res_ctx.error or "")
    assert "act-unreached" not in res_ctx.action_results


def test_error_policy_stop_by_default():
    logger = StructuredLogger(quiet=True)
    engine = AutomationEngine(logger=logger)
    engine.registry.register("test.flaky", FlakyMockHandler(fail_count=5))

    wf = Workflow(
        name="Stop on Error Test",
        actions=[
            Action(id="flaky-1", type="test.flaky", params={}),
            Action(id="never-run", type="log.write", params={"message": "should not run"}),
        ],
    )

    ctx = engine.execute_workflow(wf)
    assert ctx.status == ExecutionStatus.FAILED
    assert "Simulated failure" in ctx.error
    assert "never-run" not in ctx.action_results


def test_error_policy_continue():
    logger = StructuredLogger(quiet=True)
    engine = AutomationEngine(logger=logger)
    engine.registry.register("test.flaky", FlakyMockHandler(fail_count=5))

    wf = Workflow(
        name="Continue on Error Test",
        actions=[
            Action(
                id="flaky-1",
                type="test.flaky",
                params={},
                on_error=ErrorPolicy(policy="continue"),
            ),
            Action(id="after-flaky", type="log.write", params={"message": "executed successfully"}),
        ],
    )

    ctx = engine.execute_workflow(wf)
    assert ctx.status == ExecutionStatus.COMPLETED
    assert "flaky-1" in ctx.action_results
    assert "error" in ctx.action_results["flaky-1"]
    assert "after-flaky" in ctx.action_results


def test_error_policy_retry_success():
    logger = StructuredLogger(quiet=True)
    engine = AutomationEngine(logger=logger)
    flaky = FlakyMockHandler(fail_count=2)
    engine.registry.register("test.flaky", flaky)

    wf = Workflow(
        name="Retry Success Test",
        actions=[
            Action(
                id="flaky-retry",
                type="test.flaky",
                params={},
                on_error=ErrorPolicy(policy="retry", max_retries=3, retry_delay_seconds=0.05),
            )
        ],
    )

    ctx = engine.execute_workflow(wf)
    assert ctx.status == ExecutionStatus.COMPLETED
    assert flaky.attempts == 3  # Failed 2 times, succeeded on 3rd
    assert ctx.action_results["flaky-retry"]["status"] == "success"
