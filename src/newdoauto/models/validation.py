"""
Workflow validation module for NewDoAuto.
Validates workflow schema, action parameters, and semantic integrity before execution.
"""

from typing import Any, Dict, List, Optional, Set
from newdoauto.models.workflow import Workflow, Action

KNOWN_ACTION_TYPES: Set[str] = {
    "app.launch",
    "app.close",
    "uia.find",
    "uia.get_text",
    "uia.set_text",
    "uia.click",
    "flow.wait",
    "flow.if_else",
    "flow.set_variable",
    "log.write",
}

# Required parameters per action type
REQUIRED_PARAMS: Dict[str, List[str]] = {
    "app.launch": ["command"],
    "uia.find": ["selector"],
    "uia.get_text": ["selector"],
    "uia.set_text": ["selector", "text"],
    "uia.click": ["selector"],
    "flow.wait": ["seconds"],
    "flow.if_else": ["condition"],
    "flow.set_variable": ["name", "value"],
    "log.write": ["message"],
}


class ValidationError(Exception):
    """Raised when a workflow definition is invalid."""
    def __init__(self, message: str, errors: List[str] = None):
        super().__init__(message)
        self.errors = errors or [message]


def validate_action(action: Action, path: str = "", known_types: Optional[Set[str]] = None) -> List[str]:
    """Validates a single action and returns a list of error descriptions."""
    errors: List[str] = []
    prefix = f"Action '{action.id}' ({path}): " if path else f"Action '{action.id}': "
    allowed_types = known_types if known_types is not None else KNOWN_ACTION_TYPES

    if not action.type:
        errors.append(f"{prefix}missing action type")
        return errors

    if action.type not in allowed_types:
        errors.append(
            f"{prefix}unknown action type '{action.type}'. Known types: {sorted(list(allowed_types))}"
        )

    # Check required parameters for built-in types
    req_params = REQUIRED_PARAMS.get(action.type, [])
    for param in req_params:
        if param not in action.params:
            errors.append(f"{prefix}missing required parameter '{param}' for '{action.type}'")

    # Validate nested actions in flow.if_else
    if action.type == "flow.if_else":
        then_actions = action.params.get("then", [])
        if not isinstance(then_actions, list):
            errors.append(f"{prefix}'then' branch must be a list of actions")
        else:
            for idx, nested in enumerate(then_actions):
                nested_action = Action.from_dict(nested) if isinstance(nested, dict) else nested
                errors.extend(validate_action(nested_action, path=f"{action.id}.then[{idx}]", known_types=allowed_types))

        else_actions = action.params.get("else", [])
        if else_actions is not None:
            if not isinstance(else_actions, list):
                errors.append(f"{prefix}'else' branch must be a list of actions")
            else:
                for idx, nested in enumerate(else_actions):
                    nested_action = Action.from_dict(nested) if isinstance(nested, dict) else nested
                    errors.extend(validate_action(nested_action, path=f"{action.id}.else[{idx}]", known_types=allowed_types))

    # Validate timeout
    if action.timeout_seconds <= 0:
        errors.append(f"{prefix}timeout_seconds must be positive, got {action.timeout_seconds}")

    return errors


def validate_workflow(workflow: Workflow, known_types: Optional[Set[str]] = None) -> None:
    """
    Validates the entire workflow structure.
    Raises ValidationError if any errors are found.
    """
    errors: List[str] = []

    if not workflow.name or not workflow.name.strip():
        errors.append("Workflow name cannot be empty")

    if not workflow.schema_version:
        errors.append("Workflow schema_version is required")

    seen_ids: Set[str] = set()

    def check_unique_id(act: Action):
        if act.id in seen_ids:
            errors.append(f"Duplicate action id '{act.id}'")
        seen_ids.add(act.id)
        if act.type == "flow.if_else":
            for n in act.params.get("then", []):
                na = Action.from_dict(n) if isinstance(n, dict) else n
                check_unique_id(na)
            for n in act.params.get("else", []):
                na = Action.from_dict(n) if isinstance(n, dict) else n
                check_unique_id(na)

    for action in workflow.actions:
        check_unique_id(action)
        errors.extend(validate_action(action, known_types=known_types))

    if errors:
        raise ValidationError(
            f"Workflow '{workflow.name}' failed validation with {len(errors)} error(s):\n"
            + "\n".join(f" - {e}" for e in errors),
            errors=errors,
        )
