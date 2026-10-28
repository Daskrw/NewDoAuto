"""
Condition evaluation and variable interpolation engine for NewDoAuto.
Safely evaluates logic expressions without using unconstrained arbitrary eval().
"""

from __future__ import annotations
import re
from typing import Any, Dict, Optional, Union
from newdoauto.core.state import ExecutionContext


VAR_PATTERN = re.compile(r"\$\{([a-zA-Z0-9_\.\-]+)\}")


def interpolate_variables(template: Any, context: ExecutionContext) -> Any:
    """
    Recursively interpolates ${var_name} placeholders in strings, dicts, or lists
    using variables from the ExecutionContext.
    """
    if isinstance(template, str):
        def repl(match: re.Match) -> str:
            var_name = match.group(1)
            # Check variables first, then action_results
            if var_name in context.variables:
                return str(context.variables[var_name])
            if var_name in context.action_results:
                return str(context.action_results[var_name])
            return match.group(0)

        # If the string is EXACTLY "${var_name}", return the native type without string coercion
        m = VAR_PATTERN.fullmatch(template.strip())
        if m:
            var_name = m.group(1)
            if var_name in context.variables:
                return context.variables[var_name]
            if var_name in context.action_results:
                return context.action_results[var_name]

        return VAR_PATTERN.sub(repl, template)

    elif isinstance(template, dict):
        return {k: interpolate_variables(v, context) for k, v in template.items()}
    elif isinstance(template, list):
        return [interpolate_variables(item, context) for item in template]
    return template


def evaluate_condition(condition: Union[str, Dict[str, Any]], context: ExecutionContext) -> bool:
    """
    Evaluates a condition against the current execution context.
    Supports:
      1. Structured dictionary:
         {"left": "${var}", "operator": "equals|contains|not_contains|starts_with|ends_with|>|<|>=|<=", "right": "val"}
      2. Human-readable string expression:
         "${var} == 'value'", "${var} contains 'val'", "${num} > 5", "True", "False"
    """
    if isinstance(condition, dict):
        left_raw = interpolate_variables(condition.get("left", ""), context)
        op = condition.get("operator", "equals").lower().strip()
        right_raw = interpolate_variables(condition.get("right", ""), context)
        return _compare_values(left_raw, op, right_raw)

    if not isinstance(condition, str):
        return bool(condition)

    # String expression evaluation
    interpolated = interpolate_variables(condition.strip(), context)

    # Boolean literals
    if interpolated in ("True", "true", "1"):
        return True
    if interpolated in ("False", "false", "0"):
        return False

    # Regex to split on common binary operators
    # Supported operators: ==, !=, >=, <=, >, <, contains, not contains, startswith, endswith
    binary_regex = re.compile(
        r"^(.*?)\s+(==|!=|>=|<=|>|<|contains|not\s+contains|startswith|endswith)\s+(.*)$",
        re.IGNORECASE,
    )
    match = binary_regex.match(interpolated)
    if match:
        left_str, op, right_str = match.groups()
        left_val = _clean_literal(left_str.strip())
        right_val = _clean_literal(right_str.strip())
        return _compare_values(left_val, op.lower(), right_val)

    # Fallback to truthiness of the resolved string
    return bool(interpolated)


def _clean_literal(val: str) -> Any:
    """Strip quotes or parse integers/floats if applicable."""
    if (val.startswith("'") and val.endswith("'")) or (val.startswith('"') and val.endswith('"')):
        return val[1:-1]
    if val.lower() == "true":
        return True
    if val.lower() == "false":
        return False
    if val.lower() == "none" or val.lower() == "null":
        return None
    try:
        if "." in val:
            return float(val)
        return int(val)
    except ValueError:
        return val


def _compare_values(left: Any, op: str, right: Any) -> bool:
    """Performs type-safe comparison between left and right operands."""
    # Normalize string operators
    op_clean = op.replace("_", " ").strip()

    if op_clean in ("==", "equals", "equal", "eq"):
        return str(left) == str(right) if (isinstance(left, str) or isinstance(right, str)) else left == right

    if op_clean in ("!=", "not equals", "not equal", "ne"):
        return str(left) != str(right) if (isinstance(left, str) or isinstance(right, str)) else left != right

    if op_clean in ("contains", "has"):
        return str(right) in str(left)

    if op_clean in ("not contains", "does not contain"):
        return str(right) not in str(left)

    if op_clean in ("startswith", "starts with"):
        return str(left).startswith(str(right))

    if op_clean in ("endswith", "ends with"):
        return str(left).endswith(str(right))

    # Numeric comparisons
    try:
        l_num = float(left)
        r_num = float(right)
        if op_clean in (">", "gt", "greater than"):
            return l_num > r_num
        if op_clean in ("<", "lt", "less than"):
            return l_num < r_num
        if op_clean in (">=", "gte", "greater than or equal"):
            return l_num >= r_num
        if op_clean in ("<=", "lte", "less than or equal"):
            return l_num <= r_num
    except (ValueError, TypeError):
        pass

    raise ValueError(f"Unsupported or invalid comparison: {left!r} {op!r} {right!r}")
