"""
Unit tests for workflow data models and schema validation.
"""

import pytest
from newdoauto.models.workflow import Workflow, Action, ErrorPolicy
from newdoauto.models.validation import validate_workflow, validate_action, ValidationError


def test_valid_workflow_parsing():
    raw = {
        "schema_version": "1.0.0",
        "id": "wf-test-1",
        "name": "Sample Workflow",
        "variables": {"count": 10},
        "actions": [
            {
                "id": "act-wait",
                "type": "flow.wait",
                "params": {"seconds": 0.5},
            },
            {
                "id": "act-log",
                "type": "log.write",
                "params": {"message": "Hello ${count}"},
            },
        ],
    }
    wf = Workflow.from_dict(raw)
    assert wf.name == "Sample Workflow"
    assert len(wf.actions) == 2
    assert wf.actions[0].id == "act-wait"
    assert wf.actions[0].type == "flow.wait"
    assert wf.actions[1].params["message"] == "Hello ${count}"

    # Roundtrip serialization
    serialized = wf.to_dict()
    assert serialized["name"] == raw["name"]
    assert len(serialized["actions"]) == 2

    # Validation should pass
    validate_workflow(wf)


def test_validation_rejects_empty_name():
    wf = Workflow(name="")
    with pytest.raises(ValidationError) as exc:
        validate_workflow(wf)
    assert "Workflow name cannot be empty" in str(exc.value)


def test_validation_rejects_unknown_action_type():
    wf = Workflow(
        name="Bad Action Workflow",
        actions=[
            Action(id="bad-1", type="unknown.action.type", params={})
        ],
    )
    with pytest.raises(ValidationError) as exc:
        validate_workflow(wf)
    assert "unknown action type 'unknown.action.type'" in str(exc.value)


def test_validation_rejects_missing_required_params():
    wf = Workflow(
        name="Missing Params Workflow",
        actions=[
            Action(id="app-1", type="app.launch", params={})  # missing 'command'
        ],
    )
    with pytest.raises(ValidationError) as exc:
        validate_workflow(wf)
    assert "missing required parameter 'command'" in str(exc.value)


def test_validation_rejects_duplicate_action_ids():
    wf = Workflow(
        name="Dup ID Workflow",
        actions=[
            Action(id="act-same", type="log.write", params={"message": "1"}),
            Action(id="act-same", type="log.write", params={"message": "2"}),
        ],
    )
    with pytest.raises(ValidationError) as exc:
        validate_workflow(wf)
    assert "Duplicate action id 'act-same'" in str(exc.value)


def test_validation_nested_if_else():
    wf = Workflow(
        name="IfElse Validation",
        actions=[
            Action(
                id="cond-1",
                type="flow.if_else",
                params={
                    "condition": "1 == 1",
                    "then": [
                        {"id": "then-act", "type": "log.write", "params": {"message": "ok"}}
                    ],
                    "else": [
                        {"id": "else-bad", "type": "bad.type", "params": {}}
                    ],
                },
            )
        ],
    )
    with pytest.raises(ValidationError) as exc:
        validate_workflow(wf)
    assert "unknown action type 'bad.type'" in str(exc.value)
