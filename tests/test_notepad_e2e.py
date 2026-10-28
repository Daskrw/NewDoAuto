"""
Real Windows Notepad End-to-End Integration Tests.
Verifies actual Windows UI Automation interaction with external Windows applications.
"""

import json
import os
import pytest
from newdoauto.core.engine import AutomationEngine
from newdoauto.core.logger import StructuredLogger
from newdoauto.core.state import ExecutionContext, ExecutionStatus
from newdoauto.models.workflow import Workflow, Action
from newdoauto.actions.uia_actions import UIElementNotFoundError


WORKFLOWS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "workflows"))


@pytest.mark.skipif(os.name != "nt", reason="Windows UI Automation tests require Windows OS")
def test_notepad_e2e_then_branch():
    """
    Executes the mandatory POC workflow against real Windows Notepad:
    1. Launches notepad.exe
    2. Writes 'NewDoAuto_POC_2026' via UIA
    3. Reads back text from the Document/Edit control
    4. Evaluates IF condition: '${observed_text} == 'NewDoAuto_POC_2026''
    5. Verifies that the THEN branch executed and logged the success
    6. Ensures clean process termination
    """
    poc_path = os.path.join(WORKFLOWS_DIR, "notepad_poc.json")
    with open(poc_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    wf = Workflow.from_dict(data)
    logger = StructuredLogger()
    engine = AutomationEngine(logger=logger, cleanup_processes_on_finish=True)
    ctx = ExecutionContext()

    engine.execute_workflow(wf, context=ctx)

    assert ctx.status == ExecutionStatus.COMPLETED, f"Workflow failed with error: {ctx.error}"
    assert ctx.get_variable("branch_executed") == "THEN_BRANCH_VERIFIED"
    assert "NewDoAuto_POC_2026" in ctx.get_variable("observed_text")
    print(f"\n[VERIFIED] Observed text from real Notepad: {ctx.get_variable('observed_text')!r}")


@pytest.mark.skipif(os.name != "nt", reason="Windows UI Automation tests require Windows OS")
def test_notepad_e2e_else_branch():
    """
    Executes the mismatched condition workflow to prove that the ELSE branch executes
    based on observed state when the condition is false.
    """
    poc_else_path = os.path.join(WORKFLOWS_DIR, "notepad_poc_else.json")
    with open(poc_else_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    wf = Workflow.from_dict(data)
    logger = StructuredLogger()
    engine = AutomationEngine(logger=logger, cleanup_processes_on_finish=True)
    ctx = ExecutionContext()

    engine.execute_workflow(wf, context=ctx)

    assert ctx.status == ExecutionStatus.COMPLETED, f"Workflow failed with error: {ctx.error}"
    assert ctx.get_variable("branch_executed") == "ELSE_BRANCH_VERIFIED"
    print(f"\n[VERIFIED] Successfully took ELSE branch based on evaluated state.")


@pytest.mark.skipif(os.name != "nt", reason="Windows UI Automation tests require Windows OS")
def test_notepad_missing_element_timeout_handling():
    """
    Verifies that requesting a nonexistent UI element times out gracefully
    and raises UIElementNotFoundError with meaningful diagnostics.
    """
    logger = StructuredLogger(quiet=True)
    engine = AutomationEngine(logger=logger, cleanup_processes_on_finish=True)

    wf = Workflow(
        name="Missing Element Test",
        actions=[
            Action(
                id="act-launch",
                type="app.launch",
                params={"command": "notepad.exe", "wait_after_launch_seconds": 1.0},
            ),
            Action(
                id="act-missing",
                type="uia.click",
                params={
                    "selector": {
                        "window": {"ClassName": "Notepad"},
                        "control": {"AutomationId": "TotallyNonExistentControlId99999"},
                    },
                    "timeout_seconds": 1.5,
                },
                timeout_seconds=2.0,
            ),
        ],
    )

    ctx = engine.execute_workflow(wf)
    assert ctx.status == ExecutionStatus.FAILED
    assert "not found" in ctx.error.lower() or "timed out" in ctx.error.lower()
    print(f"\n[VERIFIED] Missing element raised expected failure: {ctx.error}")
